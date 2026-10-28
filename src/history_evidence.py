"""Opt-in history CLI and committed research projections; no legacy integration."""
import argparse
from datetime import datetime, timezone
from pathlib import Path

from .collect_evidence import load_input
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json
from .history_ingestion import reconstruct
from .history_models import HistoryVerificationRun
from .history_reporting import research_report, bounded_json, render_text, render_html
from .pilot_store import PilotStore
from .review_packet_io import outside, new_directory, atomic_create
from .scope_models import ScopeRequest


def write_history(path,run,*,protected=()):
    target=outside(path,protected)
    report=research_report(run)
    files={'history.json':bounded_json({'report':report,'substantive_sha256':digest(report),
        'executed_at_utc':run.executed_at_utc}), 'history.txt':render_text(report).encode(),'history.html':render_html(report).encode()}
    if sum(len(v) for v in files.values())>32*1024*1024: raise EvidenceError('history_output_byte_limit')
    with PilotStore(target,{'schema_type':'HistoryReportPlan','schema_version':1,'rule_version':'history-v1',
            'config':{'max_run_bytes':40*1024*1024},'input_manifests':sorted(s.input_manifest_sha256 for s in run.inputs)}) as store:
        for name,raw in files.items(): store.write_bytes(name,raw)
        store.write('history-commit.json',{'schema_type':'HistoryOutputCommit','schema_version':1,'files':store.inventory()})
    return digest(report)


def read_history(path):
    with EvidenceRoot(path,max_bytes=32*1024*1024,max_total_bytes=40*1024*1024) as root:
        snapshots={n:root.read(n) for n in root.discover()}
        if set(snapshots)!={'pilot-plan.json','history.json','history.txt','history.html','history-commit.json'}:
            raise EvidenceError('incomplete_or_extra_history_output')
        expected={'schema_type':'HistoryOutputCommit','schema_version':1,'files':{n:s.byte_sha256 for n,s in snapshots.items() if n!='history-commit.json'}}
        if strict_json(snapshots['history-commit.json'].data)!=expected: raise EvidenceError('history_output_hash_conflict')
        doc=strict_json(snapshots['history.json'].data)
        if set(doc)!={'report','substantive_sha256','executed_at_utc'}: raise EvidenceError('unsupported_history_output_wrapper')
        run=HistoryVerificationRun.from_dict(doc['report']['run'])
        from dataclasses import replace
        run=replace(run,executed_at_utc=doc['executed_at_utc'])
        report=research_report(run)
        if doc['report']!=report or doc['substantive_sha256']!=digest(report): raise EvidenceError('history_report_projection_conflict')
        if snapshots['history.txt'].data!=render_text(report).encode() or snapshots['history.html'].data!=render_html(report).encode():
            raise EvidenceError('history_readable_projection_conflict')
        plan=strict_json(snapshots['pilot-plan.json'].data)
        expected_plan={'schema_type':'HistoryReportPlan','schema_version':1,'rule_version':'history-v1','config':{'max_run_bytes':40*1024*1024},
            'input_manifests':sorted(s.input_manifest_sha256 for s in run.inputs)}
        if plan!=expected_plan: raise EvidenceError('history_output_plan_conflict')
        for n,s in snapshots.items():
            if root.read(n,recheck=True).byte_sha256!=s.byte_sha256: raise EvidenceError('history_output_changed')
        if set(root.discover())!=set(snapshots): raise EvidenceError('history_output_changed')
    return run


def bounded_live(path,prior,requested,*,transport=None):
    """One previously studied award, <=2 HTTP requests, zero retries/fallbacks."""
    from .collection import SelectedAward, CollectionLimits, collect_selected
    from .scope_models import ScopeStatus
    # Revalidate the studied identity/evidence before issuing a new query.
    with EvidenceRoot(prior) as root:
        before={n:root.read(n).byte_sha256 for n in root.discover()}
        old=strict_json(root.read('c3_plan.json').data)
    reconstruct((prior,),requested)
    with EvidenceRoot(prior) as root:
        if {n:root.read(n).byte_sha256 for n in root.discover()}!=before: raise EvidenceError('history_prior_evidence_changed')
    award=SelectedAward.from_dict(old['awards'][0])
    target=outside(path,(prior,));new_directory(target)
    with EvidenceRoot(target) as root:
        atomic_create(root.fd,'live-plan.json',bounded_json({'schema_type':'HistoryLivePlan','schema_version':1,
            'maximum_awards':1,'maximum_http_requests':2,'retries':0,'prior_plan_sha256':digest(old),'requested':requested.to_dict(),
            'profile':'live' if transport is None else 'synthetic'}))
    paths=[];summaries=[];stopped=False
    for source in ('usaspending','fpds'):
        if source=='usaspending' and award.generated_id is None: continue
        root_path=target/source
        summary=collect_selected(root_path,(award,),sources=(source,),
            limits=CollectionLimits(max_awards=1,max_requests=1,max_pages=1,retries=0,pace_seconds=0.5),stop_on_context_mismatch=True,
            profile='live' if transport is None else 'fixture:'+digest({'mode':'history-live-control','source':source}),transport=transport)
        paths.append(root_path);summaries.append(summary)
        checked=reconstruct((root_path,),requested)
        if (any(t['error_code'] is not None for t in summary['tasks']) or any(s.artifact_issues for s in checked.inputs)
                or any(o.issues or o.scope_assessment.status in (ScopeStatus.UNSUPPORTED,ScopeStatus.OUT_OF_SCOPE) for o in checked.observations)):
            stopped=True;break
    run=reconstruct(paths,requested)
    with EvidenceRoot(prior) as root:
        if {n:root.read(n).byte_sha256 for n in root.discover()}!=before: raise EvidenceError('history_prior_evidence_changed')
    write_history(target/'report',run,protected=paths+( [prior] ))
    with EvidenceRoot(target) as root:
        atomic_create(root.fd,'live-result.json',bounded_json({'schema_type':'HistoryLiveResult','schema_version':1,
            'summaries':summaries,'stopped_on_unsupported_or_scope_change':stopped,'run_digest':run.substantive_sha256,
            'http_requests_reserved':sum(s['requests_reserved'] for s in summaries)}))
    return run


def main(argv=None):
    p=argparse.ArgumentParser(description='Opt-in observed histories; offline unless --live is explicitly supplied.')
    p.add_argument('--root',action='append',default=[]);p.add_argument('--request');p.add_argument('--run-dir',required=True)
    p.add_argument('--demo',action='store_true');p.add_argument('--live',action='store_true');p.add_argument('--execution-time',action='store_true')
    args=p.parse_args(argv)
    try:
        if args.demo:
            if args.live or args.root or args.request: raise EvidenceError('fixed_history_demo_context_required')
            from .history_demo import run_demo
            result=run_demo(args.run_dir);value=digest(result)
        else:
            if not args.root or not args.request: raise EvidenceError('explicit_preserved_roots_and_native_request_required')
            requested=ScopeRequest.from_dict(load_input(args.request))
            if args.live:
                if len(args.root)!=1: raise EvidenceError('history_live_requires_one_previously_studied_award')
                run=bounded_live(args.run_dir,args.root[0],requested)
                value=run.substantive_sha256
            else:
                run=reconstruct(args.root,requested,executed_at_utc=datetime.now(timezone.utc).isoformat() if args.execution_time else None)
                value=write_history(args.run_dir,run,protected=args.root)
        print(canonical({'substantive_sha256':value,'exit_code':1,'history':'unknown','freshness':'unknown'}));return 1
    except KeyboardInterrupt: return 130
    except (ValueError,TypeError,KeyError,IndexError,OSError):
        print(canonical({'error_code':'history_verification_failed','exit_code':2}));return 2


if __name__=='__main__': raise SystemExit(main())
