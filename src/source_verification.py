"""Opt-in C12 public-source experiment and offline primary replay; no pipeline hook."""
import argparse
from dataclasses import dataclass
from html import escape
from pathlib import Path

from .acquisition_planning import AcquisitionQueue, AcquisitionLimits, prepare, case_report
from .award_validation import snapshot
from .collection import SelectedAward, CollectionLimits, collect_selected
from .collection_sources import HTTPTransport, FixtureTransport
from .evidence import Schema, _timestamp
from .evidence_acquisition import PreservedReplay, acquire, resolution_replay
from .evidence_io import EvidenceError, canonical, digest, strict_json
from .history_reporting import bounded_json
from .pilot_store import PilotStore
from .review_packet_io import outside
from .source_contracts import (RULE, detail_request, award_detail,
    parent_lookup, collection_contract)


@dataclass(frozen=True,kw_only=True)
class VerificationExperiment(Schema):
    queue:AcquisitionQueue
    request_id:str
    mode:str='offline_only'

    def validate(self):
        if self.mode not in ('offline_only','explicit_public_USA_validation','synthetic_only'):
            raise ValueError('unsupported_experiment_mode')
        s=self.spec
        if s.source!='usaspending' or s.target_kind!='award_history' or s.selection_json is None or s.request_json is None:
            raise ValueError('USA_native_history_spec_required')
        if s.limits.retries!=0 or s.limits.max_pages>2 or s.limits.page_size>10:
            raise ValueError('experiment_two_pages_ten_rows_zero_retries_required')
        if (s.evidence_profile=='synthetic')!=(self.mode=='synthetic_only'):
            raise ValueError('synthetic_live_provenance_confusion')

    @property
    def spec(self):
        matches=[s for s in self.queue.requests if s.request_id==self.request_id]
        if len(matches)!=1:raise ValueError('exact_original_queue_request_required')
        return matches[0]


def files(values):return {n:s.byte_sha256 for n,s in values.items()}


def _metadata(value,raw):
    if type(value) is not dict or set(value)!={'status','retrieved_at_utc','body_complete','error_code','retry_after','source_update_raw'}:
        raise EvidenceError('unsupported_experiment_response_metadata')
    if (value['status'] is not None and (type(value['status']) is not int or not 100<=value['status']<=599)
        or type(value['body_complete']) is not bool or value['status'] is None and raw is not None
        or raw is not None and (type(raw) is not bytes or len(raw)>1048576)):
        raise EvidenceError('invalid_experiment_response')
    for key in ('retrieved_at_utc','error_code','retry_after','source_update_raw'):
        text=value[key]
        if text is not None and (type(text) is not str or len(text)>256 or any(ord(c)<32 or ord(c)==127 for c in text)):
            raise EvidenceError('unsafe_experiment_metadata')
    if value['retrieved_at_utc'] is not None:_timestamp(value['retrieved_at_utc'])
    if value['status'] is not None and value['retrieved_at_utc'] is None:raise EvidenceError('missing_retrieval_timestamp')
    return value['error_code'] is None and value['body_complete'] and value['status'] is not None and 200<=value['status']<300 and raw is not None


def experiment(path,plan,*,live=False,synthetic=None):
    """At most four public USA requests, no redirects, retries, keys or fallback.

    Synthetic inputs are transcripts, not arbitrary transport callbacks. The
    installed public transport is only constructed after explicit mode checks.
    """
    if not isinstance(plan,VerificationExperiment) or type(live) is not bool:
        raise EvidenceError('typed_explicit_experiment_required')
    if live:
        if plan.mode!='explicit_public_USA_validation' or synthetic is not None:
            raise EvidenceError('explicit_public_USA_mode_required')
    elif plan.mode!='synthetic_only' or synthetic is None:
        raise EvidenceError('offline_default_no_source_access')
    if synthetic is not None:
        if type(synthetic) is not dict or set(synthetic)!={'details','transactions'} or type(synthetic['details']) is not list or len(synthetic['details'])>2:
            raise EvidenceError('bounded_synthetic_transcript_required')
        canonical(synthetic)
        detail_transport=FixtureTransport({'schema_version':1,'responses':synthetic['details']})
        transaction_transport=FixtureTransport(synthetic['transactions'])
    s=plan.spec;a=SelectedAward.from_dict(strict_json(s.selection_json.encode()))
    limits=CollectionLimits(max_awards=1,max_pages=s.limits.max_pages,page_size=s.limits.page_size,
        max_records_per_source_award=s.limits.max_pages*s.limits.page_size,
        max_records_total=s.limits.max_pages*s.limits.page_size,max_requests=s.limits.max_pages,
        retries=0,timeout_seconds=10.0,pace_seconds=1.0,max_response_bytes=1048576)
    outside(path,())
    capture_plan={'schema_type':'SourceVerificationCapturePlan','schema_version':1,'rule_version':RULE,
        'experiment':plan.to_dict(),'public_source_allowlist':['usaspending'],
        'maximum_HTTP_requests':2+s.limits.max_pages,'maximum_transaction_rows':s.limits.max_pages*s.limits.page_size,
        'config':{'max_run_bytes':16*1024*1024}}
    with PilotStore(path,capture_plan) as store:
        if live:detail_transport=HTTPTransport(limits.to_dict());transaction_transport=None
        details=[];issues=[]
        request=detail_request(a.generated_id)
        for index in range(2):
            # Reservation precedes access; missing completion remains an
            # interrupted capture, never a source retry or implicit resume.
            store.write(f'detail-{index:03d}-reservation.json',{'request':request,'sequence':index})
            if live and index:
                import time
                time.sleep(1.0)
            meta,raw=detail_transport(request,index)
            okay=_metadata(meta,raw)
            if raw is not None:store.write_bytes(f'detail-{index:03d}.body',raw)
            store.write(f'detail-{index:03d}.json',{'request':request,'response':meta,
                'body_sha256':None if raw is None else __import__('hashlib').sha256(raw).hexdigest(),
                'representation':'HTTP_entity_bytes_after_content_decoding' if live else 'synthetic_transcript_bytes',
                'source':'usaspending'})
            details.append(index)
            if not okay:issues.append('detail_request_failed_or_incomplete');break
            try:
                child=award_detail(raw,a.generated_id,a.piid) if index==0 else award_detail(raw,child['parent']['generated_unique_award_id'],a.parent_piid,parent=True)
                following=parent_lookup(child,a) if index==0 else None
            except (ValueError,TypeError,KeyError):issues.append('detail_native_contract_unvalidated');break
            if following is None:break
            request=following
        if not issues:
            if live:
                import time
                time.sleep(1.0)
            # Retains existing C3 request controls, atomic checkpoint boundaries,
            # original body files and native transaction ingestion. No new source
            # is enabled in the legacy collector or default pipeline.
            collect_selected(store.path/'transactions',(a,),sources=('usaspending',),limits=limits,
                transport=transaction_transport,profile='live' if live else 'fixture:'+digest(synthetic),
                stop_on_context_mismatch=True,**({} if live else {'sleep':lambda _:None}))
        store.write('experiment.json',{'schema_version':1,'detail_attempts':len(details),'issues':issues,
            'transaction_collection_created':not issues,'financial_comparison_authorized':False})
        store.write('experiment-commit.json',{'schema_version':1,'files':store.inventory()})
    return inspect_experiment(path)


def inspect_experiment(path):
    before=snapshot(path);names=files(before)
    if 'experiment-commit.json' not in before:raise EvidenceError('incomplete_source_experiment_preserve_capture')
    commit=strict_json(before['experiment-commit.json'].data)
    if canonical(commit)!=canonical({'schema_version':1,'files':{n:h for n,h in names.items() if n!='experiment-commit.json'}}):
        raise EvidenceError('source_experiment_integrity_conflict')
    capture_plan=strict_json(before['pilot-plan.json'].data)
    plan=VerificationExperiment.from_dict(capture_plan['experiment']);s=plan.spec
    # Reconstruct every plan control instead of trusting locally edited flags.
    expected={'schema_type':'SourceVerificationCapturePlan','schema_version':1,'rule_version':RULE,
        'experiment':plan.to_dict(),'public_source_allowlist':['usaspending'],'maximum_HTTP_requests':2+s.limits.max_pages,
        'maximum_transaction_rows':s.limits.max_pages*s.limits.page_size,'config':{'max_run_bytes':16*1024*1024}}
    if canonical(capture_plan)!=canonical(expected) or plan.mode=='offline_only':raise EvidenceError('source_experiment_plan_conflict')
    a=SelectedAward.from_dict(strict_json(s.selection_json.encode()));child=parent=None;citations=[];issues=[];attempts=0
    expected_names={'pilot-plan.json','experiment.json','experiment-commit.json'}
    next_request=detail_request(a.generated_id)
    for index in range(2):
        stem=f'detail-{index:03d}';reservation=stem+'-reservation.json';name=stem+'.json'
        if next_request is None:
            if name in before or reservation in before:raise EvidenceError('unexpected_parent_request')
            break
        if name not in before or reservation not in before:raise EvidenceError('missing_detail_attempt')
        attempts+=1;expected_names|={reservation,name}
        raw=before.get(stem+'.body');rawbytes=None if raw is None else raw.data
        if raw:expected_names.add(stem+'.body')
        if canonical(strict_json(before[reservation].data))!=canonical({'request':next_request,'sequence':index}):raise EvidenceError('detail_reservation_scope_conflict')
        m=strict_json(before[name].data)
        representation='synthetic_transcript_bytes' if plan.mode=='synthetic_only' else 'HTTP_entity_bytes_after_content_decoding'
        if (set(m)!={'request','response','body_sha256','representation','source'} or canonical(m['request'])!=canonical(next_request)
            or m['source']!='usaspending' or m['representation']!=representation or m['body_sha256']!=(raw.byte_sha256 if raw else None)):
            raise EvidenceError('detail_provenance_conflict')
        citations.append({'source':'usaspending','request':m['request'],'metadata_file':name,
            'metadata_sha256':before[name].byte_sha256,'body_file':stem+'.body' if raw else None,'body_sha256':m['body_sha256'],
            'retrieved_at_utc':m['response']['retrieved_at_utc'],'representation':representation})
        if not _metadata(m['response'],rawbytes):issues.append('detail_request_failed_or_incomplete');next_request=None;break
        try:
            if index==0:
                child=award_detail(rawbytes,a.generated_id,a.piid);next_request=parent_lookup(child,a)
            else:
                parent=award_detail(rawbytes,child['parent']['generated_unique_award_id'],a.parent_piid,parent=True);next_request=None
        except (ValueError,TypeError,KeyError):issues.append('detail_native_contract_unvalidated');next_request=None;break
    collection=None
    if not issues:
        collection=collection_contract(Path(path)/'transactions')
        if (collection['profile']=='synthetic')!=(plan.mode=='synthetic_only'):raise EvidenceError('transaction_capture_provenance_confusion')
        primary=strict_json(before['transactions/c3_plan.json'].data)
        if primary['awards']!=[a.to_dict()] or primary['sources']!=['usaspending']:
            raise EvidenceError('transaction_selection_substitution')
        # Transaction source controls are independently replayed by C9. Also
        # enforce C12's stricter page/size/retry and attempt budget caps.
        l=CollectionLimits.from_dict(primary['limits'])
        if (l.max_pages,l.page_size,l.max_requests,l.retries,l.max_response_bytes,l.pace_seconds)!=(s.limits.max_pages,s.limits.page_size,s.limits.max_pages,0,1048576,1.0):
            raise EvidenceError('transaction_budget_scope_changed')
        txattempts=sum(n.startswith('transactions/c3_attempt_') and n.endswith('.json') for n in before)
        if txattempts>s.limits.max_pages:raise EvidenceError('experiment_request_budget_exceeded')
        attempts+=txattempts;expected_names|={n for n in before if n.startswith('transactions/')}
    summary={'schema_version':1,'detail_attempts':len(citations),'issues':issues,
        'transaction_collection_created':not issues,'financial_comparison_authorized':False}
    if canonical(strict_json(before['experiment.json'].data))!=canonical(summary) or set(before)!=expected_names:
        raise EvidenceError('experiment_history_or_summary_conflict')
    if files(snapshot(path))!=names:raise EvidenceError('experiment_changed_during_replay')
    verified=not issues and child is not None and parent is not None
    return {'schema_type':'AuthoritativeSourceObservation','schema_version':1,'rule_version':RULE,
        'experiment':plan.to_dict(),'inventory_sha256':digest(names),
        'knowledge_basis':'SYNTHETIC_ONLY' if plan.mode=='synthetic_only' else 'NEW_PUBLIC_HTTP_OBSERVATION_AT_CAPTURE_NOT_NEW_REQUEST_ON_REPLAY',
        'replay_creates_new_observations':False,'source':'usaspending','request_attempts':attempts,'citations':citations,'child':child,'parent':parent,
        'current_source_parent_link':'verified_source_local_summary_link' if verified else 'insufficient_evidence',
        'historical_parent_link':'unknown','issues':issues,'transaction_contract':collection,
        'history_complete':'unknown','revision_complete':'unknown','source_wide_complete':'unknown','freshness':'unknown',
        'financial_comparison_authorized':False,'production_readiness_changed':False,
        'limitations':['same_source_link_not_independent_corroboration','current_summary_not_historical_parent_certificate',
            'no_FPDS_or_SAM_namespace_crosswalk','hashes_not_upstream_authentication','content_decoding_not_byte_exact_HTTP_wire',
            'no_correction_deletion_or_asof_certificate']}


def integrate(cases,experiment_path,acquisition_path):
    """C11 remains offline: newly captured C3 bytes enter as a preserved replay."""
    observation=inspect_experiment(experiment_path);plan=VerificationExperiment.from_dict(observation['experiment'])
    if canonical(prepare(cases,limits=plan.queue.limits).to_dict())!=canonical(plan.queue.to_dict()):raise EvidenceError('original_case_queue_binding_required')
    if observation['issues'] or not observation['transaction_contract'] or not all(h['source_contract_satisfied'] for h in observation['transaction_contract']['histories']) or not observation['transaction_contract']['histories']:
        raise EvidenceError('incomplete_source_contract_cannot_integrate')
    acquire(plan.queue,acquisition_path,preserved=(PreservedReplay(request_id=plan.request_id,path=str(Path(experiment_path)/'transactions')),))
    return assessment(cases,experiment_path,acquisition_path)


def assessment(cases,experiment_path,acquisition_path=None):
    obs=inspect_experiment(experiment_path);p=VerificationExperiment.from_dict(obs['experiment'])
    if canonical(prepare(cases,limits=p.queue.limits).to_dict())!=canonical(p.queue.to_dict()):raise EvidenceError('original_case_queue_binding_required')
    baseline=[case_report(c) for c in cases]
    replay=None if acquisition_path is None else resolution_replay(cases,acquisition_path)
    # Bind C11's optional bundle to THIS experiment's unchanged C3 inventory,
    # so a valid but unrelated replay cannot be attributed to this observation.
    if replay is not None:
        if obs['issues'] or not obs['transaction_contract'] or not obs['transaction_contract']['histories'] or not all(h['source_contract_satisfied'] for h in obs['transaction_contract']['histories']):
            raise EvidenceError('unvalidated_source_contract_cannot_gain_from_replay')
        receipts=replay['run']['receipts'];tx=obs['transaction_contract']
        if tx is None or len(receipts)!=1 or receipts[0]['request_id']!=p.request_id or receipts[0].get('inventory_sha256')!=tx['inventory_sha256']:
            raise EvidenceError('acquisition_experiment_inventory_mismatch')
    target_cases={t.case_id for t in p.spec.requirements}
    targets=[{'plan_id':v['plan_id'],'contract_id':v['contract_id'],'case_id':digest(b),
        'original_requirement_json':canonical(v['requirement'])}
        for b in baseline if digest(b) in target_cases for v in b['resolution_plans']
        if v['source']=='usaspending' and v['requirement']['dimension']=='parent_identity'
        and {k:strict_json(v['native_identifiers_json'].encode()).get(k) for k in ('piid','agency','parent_piid','parent_agency')}==strict_json(p.spec.native_context_json.encode())]
    parent_proofs=[{'original_plan_id':t['plan_id'],'original_contract_id':t['contract_id'],
        'original_case_id':t['case_id'],'original_native_context':strict_json(p.spec.native_context_json.encode()),'original_requirement':strict_json(t['original_requirement_json'].encode()),
        'dimension':'parent_identity','narrow_proof':'current_source_parent_record_and_child_summary_link',
        'status':obs['current_source_parent_link'],'supporting_citations':obs['citations'],
        'original_historical_requirement_resolved':False,
        'remaining_blockers':['historical_action_parent_applicability','revision_alignment','asof_alignment','history_completeness','freshness']} for t in targets]
    resolved=[] if replay is None else replay['resolved_plan_ids']
    coverage=[]
    for source in ('usaspending','fpds','samgov'):
        rows=[r for b in baseline for c in b['contracts'] for r in c['observed_occurrences'] if r['source']==source]
        observed=[r for h in (obs['transaction_contract'] or {}).get('histories',[]) if h['source']==source for r in h['observations']]
        old_native={n['value'] for r in rows for n in r['native_identifiers'] if n['namespace'] in ('id','atom_id')}
        fresh_native={r['native_action_id'] for r in observed if r['native_action_id'] is not None}
        coverage.append({'source':source,'baseline_record_occurrences':len(rows),'new_capture_record_occurrences':len(observed),
            'previously_unobserved_native_action_ids':sorted(fresh_native-old_native),
            'reobserved_native_action_ids':sorted(fresh_native&old_native),
            'bounded_pagination_verified':any(h['source']==source and h['source_contract_satisfied'] for h in (obs['transaction_contract'] or {}).get('histories',[])),
            'historical_completeness_improved':False,'financial_comparison_authorized':False})
    synthetic=p.mode=='synthetic_only'
    return {'schema_type':'SourceVerificationAssessment','schema_version':1,'rule_version':RULE,
        'observation':obs,'baseline_case_sha256':[digest(b) for b in baseline],
        'original_unresolved_requirements':sum(len(b['resolution_plans']) for b in baseline),
        'parent_proof_impacts':parent_proofs,'source_coverage':coverage,'acquisition_resolution':replay,
        'resolved_real_source_plan_ids':[] if synthetic else resolved,'resolved_synthetic_plan_ids':resolved if synthetic else [],
        'new_current_parent_subproofs':sum(v['status']=='verified_source_local_summary_link' for v in parent_proofs),
        'remaining_original_requirements':sum(len(b['resolution_plans']) for b in baseline)-len(resolved),
        'financial_comparison_authorized':False,'production_readiness_changed':False,
        'interpretation':'Source-local current facts and observed page contracts only; no fraud inference, historical recall guarantee or financial authorization.'}


def markdown(value):
    return '\n'.join(('# Authoritative source verification v1','',
        'Observed facts, interpretation, missing proof and financial authorization remain separate.',
        'Knowledge basis: '+value['observation']['knowledge_basis'],
        'Real-source historical requirements resolved: '+str(len(value['resolved_real_source_plan_ids'])),
        'Synthetic-only historical requirements resolved: '+str(len(value['resolved_synthetic_plan_ids'])),
        'Current parent subproofs (not full historical qualification): '+str(value['new_current_parent_subproofs']),
        'Historical completeness, revision alignment and freshness remain unknown. Financial authorization remains false.',
        '', '```json',canonical(value).replace('`','\\u0060'),'```',''))


def html(value):
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; base-uri \'none\'"><title>Source verification</title><pre>'+escape(markdown(value))+'</pre></html>\n'


def write_report(path,cases,experiment_path,acquisition_path=None):
    protected=[experiment_path]+[v for c in cases for v in c.get('collections',())]+[v for c in cases for v in c.get('sam_captures',())]
    if acquisition_path is not None:protected.append(acquisition_path)
    outside(path,protected);value=assessment(cases,experiment_path,acquisition_path)
    with PilotStore(path,{'schema_type':'SourceVerificationReportPlan','schema_version':1,'rule_version':RULE,'config':{'max_run_bytes':64*1024*1024}}) as store:
        store.write_bytes('verification.json',bounded_json(value));store.write_bytes('verification.md',markdown(value).encode());store.write_bytes('verification.html',html(value).encode())
        store.write('verification-commit.json',{'schema_version':1,'files':store.inventory(),'report_sha256':digest(value)})
    return digest(value)


def verify_report(path,cases,experiment_path,acquisition_path=None):
    values=snapshot(path);value=assessment(cases,experiment_path,acquisition_path)
    expected={'pilot-plan.json','verification.json','verification.md','verification.html','verification-commit.json'}
    if set(values)!=expected:raise EvidenceError('incomplete_verification_report')
    manifest={'schema_version':1,'files':{n:s.byte_sha256 for n,s in values.items() if n!='verification-commit.json'},'report_sha256':digest(value)}
    if (values['verification-commit.json'].data!=(canonical(manifest)+'\n').encode() or values['verification.json'].data!=bounded_json(value)
        or values['verification.md'].data!=markdown(value).encode() or values['verification.html'].data!=html(value).encode()):
        raise EvidenceError('source_verification_primary_replay_conflict')
    return value


def main(argv=None):
    parser=argparse.ArgumentParser(description='C12 bounded USA verification; offline replay by default. No SAM credentials or FPDS requests.')
    parser.add_argument('--cases',required=True);parser.add_argument('--run-dir',required=True)
    parser.add_argument('--capture',action='store_true');parser.add_argument('--live',action='store_true')
    parser.add_argument('--report-dir');parser.add_argument('--verify-report');parser.add_argument('--acquisition-dir')
    args=parser.parse_args(argv)
    try:
        # Bounded regular-file reading, no credential or directory discovery.
        from .evidence_io import EvidenceRoot
        p=Path(args.cases).absolute()
        with EvidenceRoot(p.parent,max_bytes=1048576) as root:
            saved=root.read(p.name);cases=strict_json(saved.data)
            root.read(p.name,recheck=True)
        if type(cases) is not list or not 1<=len(cases)<=24:raise EvidenceError('bounded_explicit_cases_required')
        if args.live and not args.capture:raise EvidenceError('live_requires_explicit_capture')
        if args.capture:
            if not args.live:raise EvidenceError('capture_requires_explicit_public_access')
            q=prepare(cases,limits=AcquisitionLimits(max_pages=2,page_size=2,retries=0))
            jobs=[s for s in q.requests if s.source=='usaspending' and s.target_kind=='award_history' and s.request_json is not None]
            if len(jobs)!=1:raise EvidenceError('one_explicit_USA_award_required')
            experiment(args.run_dir,VerificationExperiment(queue=q,request_id=jobs[0].request_id,mode='explicit_public_USA_validation'),live=True)
        if args.verify_report:value=verify_report(args.verify_report,cases,args.run_dir,args.acquisition_dir)
        else:
            if args.acquisition_dir and not Path(args.acquisition_dir).exists():integrate(cases,args.run_dir,args.acquisition_dir)
            value=assessment(cases,args.run_dir,args.acquisition_dir)
            if args.report_dir:write_report(args.report_dir,cases,args.run_dir,args.acquisition_dir)
        print(canonical({'report_sha256':digest(value),'resolved_real_source_requirements':len(value['resolved_real_source_plan_ids']),
            'financial_comparison_authorized':False}))
        observation=value['observation'];collection=observation['transaction_contract']
        complete=(collection is not None and bool(collection['histories']) and not collection['failures']
            and all(h['source_contract_satisfied'] for h in collection['histories']))
        return 0 if not observation['issues'] and complete else 1
    except (ValueError,TypeError,OSError,KeyError,IndexError):
        print(canonical({'error_code':'source_verification_failed_preserve_evidence','exit_code':2}));return 2


if __name__=='__main__':raise SystemExit(main())
