"""Explicit offline Phase 4C1 evaluation and deterministic safe reports."""
import argparse
from html import escape
from pathlib import Path

from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, parts, strict_json
from .history_ingestion import reconstruct
from .history_pilot import native_request
from .history_reporting import bounded_json, metrics as history_metrics
from .parent_scope import ParentScopeRun, assess_parent_collection, report_for
from .pilot_store import PilotStore
from .readiness_audit import inventory
from .readiness_holdout import audit_holdout
from .readiness_models import ReadinessProtocol
from .review_packet_io import outside

PROTOCOL_PATH = Path(__file__).resolve().parents[1]/'docs'/'parent-identity-protocol-v1.json'


PROTOCOL_DIGEST = '2aed20d36722a1bddf2b7000ebf8fae185f83298c79b8e7467fa9c5e70b5d723'


def protocol():
    value = strict_json(PROTOCOL_PATH.read_bytes())
    if digest(value) != PROTOCOL_DIGEST:
        raise EvidenceError('parent_protocol_v1_changed_use_new_version')
    return value


def text_report(report):
    m = report['metrics']
    lines = ['Phase 4C1 parent-award identity research',
        'Narrow source-record claims only. No financial eligibility or population precision inference.',
        'Protocol: '+report['protocol_sha256'],
        f"Inspected slots: {m['inspected_slots']} / {m['selected_slot_denominator']}; enumerated verification occurrences: {m['denominator']}",
        '', '| Scope status | Previous occurrences | Experimental occurrences |', '|---|---:|---:|']
    lines.extend(f"| {s} | {m['previous'][s]} | {m['new'][s]} |" for s in sorted(m['previous']))
    lines.extend(['', '| Previous → new | Occurrences | Distinct source contents | Affected slots | Rule |', '|---|---:|---:|---:|---|'])
    lines.extend('| '+' | '.join((t['previous']+' → '+t['new'],str(t['occurrences']),str(t['distinct_source_contents']),
        str(len(t['affected_slot_ids'])),', '.join(t['rules'])))+' |' for t in m['transitions'])
    lines.extend(['', 'Parent classifications (occurrence denominator '+str(m['denominator'])+'): '+canonical(m['parents']),
        'Eligible complete action keys (within slot): '+str(m['eligible_action_identities']['count']),
        'New financial eligibility: zero; experimental scope is not consumed downstream.',
        '', 'Official semantic sources:'])
    lines.extend(s['id']+': '+s['url']+'; '+s['limitation'] for s in report['official_semantics'])
    lines.extend(['','Unavailable slots (retained):',canonical(report['unavailable_slots']),
        '', 'Legacy history/financial results (unchanged):'])
    lines.extend(canonical(d) for d in report['downstream_baseline'])
    for r in report['runs']:
        lines.extend(['','Award slot: '+r['slot'],'Input inventories: '+r['run']['input_inventories_json']])
        for q in r['query_explanations']:
            e = q['citation']['evidence']; a = e['artifact']
            lines.extend(['', 'Claim: '+q['assessment_id'],
                'Requested native identity: '+canonical(q['requested_native_query']),
                'Submitted request context: '+canonical(q['submitted_request_contexts']),
                'Returned native components: '+canonical(q['returned_native']),
                'Parent evidence: '+canonical(q['parent']),
                'Scope: '+q['previous_inclusion']+' → '+q['inclusion'],
                'Citation: '+q['citation']['citation_id']+'; '+(e['reference']['source_record_url'] or a['endpoint'])+'; '+e['reference']['locator']+'; artifact SHA256 '+a['sha256']+'; retrieved '+str(a['retrieved_at_utc']),
                'Query limitations: '+ '; '.join(q['query_limitations']),
                'Next verification: '+q['recommended_action']])
        lines.append('Artifact issues: '+canonical(r['run']['artifact_issues']))
    lines.extend(['','Limitations:',*report['limitations']])
    return '\n'.join(lines)+'\n'


def html_report(report):
    return '<!doctype html><meta charset="utf-8"><title>Parent identity evidence</title><h1>Parent identity evidence</h1><pre>'+escape(text_report(report))+'</pre>'


def write_report(path,report,protected=()):
    target = outside(path,protected)
    validate_report(report)
    payload = bounded_json({'report':report,'substantive_sha256':digest(report)})
    text,html = text_report(report).encode(),html_report(report).encode()
    if sum(map(len,(payload,text,html))) > 96*1024*1024:
        raise EvidenceError('parent_output_byte_limit')
    with PilotStore(target,{'schema_type':'ParentIdentityOutputPlan','schema_version':1,'protocol_sha256':report['protocol_sha256'],
                            'config':{'max_run_bytes':100*1024*1024}}) as store:
        store.write_bytes('parent-identity.json',payload)
        store.write_bytes('parent-identity.md',text)
        store.write_bytes('parent-identity.html',html)
        store.write('parent-identity-commit.json',{'schema_type':'ParentIdentityOutputCommit','schema_version':1,'files':store.inventory()})
    return digest(report)


def validate_report(report):
    if report['protocol'] != protocol():
        raise EvidenceError('parent_report_protocol_conflict')
    slots = [(r['slot'],ParentScopeRun.from_dict(r['run'])) for r in report['runs']]
    if [r['substantive_sha256'] for r in report['runs']] != [r.substantive_sha256 for _,r in slots]:
        raise EvidenceError('parent_run_digest_conflict')
    expected = report_for(slots,protocol=report['protocol'],unavailable=report['unavailable_slots'],downstream=report['downstream_baseline'])
    if report != expected:
        raise EvidenceError('parent_report_projection_conflict')


def read_report(path):
    with EvidenceRoot(path,max_bytes=64*1024*1024,max_total_bytes=100*1024*1024) as root:
        snapshots = {n:root.read(n) for n in root.discover()}
        if set(snapshots) != {'parent-identity.json','parent-identity.md','parent-identity.html','parent-identity-commit.json','pilot-plan.json'}:
            raise EvidenceError('incomplete_parent_report')
        expected = {'schema_type':'ParentIdentityOutputCommit','schema_version':1,'files':{n:s.byte_sha256 for n,s in snapshots.items() if n!='parent-identity-commit.json'}}
        if strict_json(snapshots['parent-identity-commit.json'].data) != expected:
            raise EvidenceError('parent_report_hash_conflict')
        doc = strict_json(snapshots['parent-identity.json'].data); report = doc['report']
        if set(doc) != {'report','substantive_sha256'} or digest(report) != doc['substantive_sha256']:
            raise EvidenceError('parent_report_digest_conflict')
        validate_report(report)
        if strict_json(snapshots['pilot-plan.json'].data) != {'schema_type':'ParentIdentityOutputPlan','schema_version':1,'protocol_sha256':report['protocol_sha256'],'config':{'max_run_bytes':100*1024*1024}}:
            raise EvidenceError('parent_report_plan_conflict')
        if snapshots['parent-identity.md'].data != text_report(report).encode() or snapshots['parent-identity.html'].data != html_report(report).encode():
            raise EvidenceError('parent_readable_projection_conflict')
        if any(root.read(n,recheck=True).byte_sha256 != s.byte_sha256 for n,s in snapshots.items()) or set(root.discover()) != set(snapshots):
            raise EvidenceError('parent_report_changed')
        return report


def evaluate_frozen(frozen,holdout=None):
    frozen = Path(frozen).absolute(); holdout = Path(holdout).absolute() if holdout else None
    p = protocol(); before = inventory(frozen)
    if digest(before) != p['cohorts']['frozen_pilot']['inventory_sha256']:
        raise EvidenceError('frozen_parent_evaluation_inventory_conflict')
    with EvidenceRoot(frozen,max_total_bytes=256*1024*1024,max_files=20000) as root:
        sample = strict_json(root.read('sample.json').data)
        if len(sample['selected']) != p['cohorts']['frozen_pilot']['slots']:
            raise EvidenceError('frozen_slot_count_conflict')
        sources = []
        for i,row in enumerate(sample['selected']):
            base = f'award-{i:03d}'
            d = strict_json(root.read(base+'/research/research-plan.json').data)['sources']
            if len(d) != 1: raise EvidenceError('unsupported_parent_pilot_source_count')
            d = d[0]
            if d['managed']:
                path = frozen/base/'research'/Path(*parts(d['path']))
            else:
                legacy = Path(d['path'])
                if not legacy.is_absolute() or legacy.parts[-2:] != (base,'discovery'):
                    raise EvidenceError('unsafe_legacy_parent_descriptor')
                path = frozen/base/'discovery'
            sources.append((f'frozen_pilot/slot-{i:03d}',(path,),row['generated_id']))
    holdout_before = None
    if holdout:
        if holdout == frozen: raise EvidenceError('distinct_cohort_roots_required')
        holdout_before = inventory(holdout)
        if digest(holdout_before) != p['cohorts']['holdout']['inventory_sha256']:
            raise EvidenceError('holdout_parent_evaluation_inventory_conflict')
        b4 = ReadinessProtocol.from_dict(strict_json((PROTOCOL_PATH.parent/'readiness-protocol-v1.json').read_bytes()))
        # Existing validator independently checks preregistered selection and all
        # capture controls. Its outcomes are not rewritten by the experiment.
        audit_holdout(holdout,b4,{s['generated_id'] for s in sample['selected']})
        with EvidenceRoot(holdout) as root:
            selection = strict_json(root.read('holdout-selection.json').data)
            result = strict_json(root.read('holdout-result.json').data)
        if len(selection['selected']) != p['cohorts']['holdout']['slots']:
            raise EvidenceError('holdout_slot_count_conflict')
        for i,(identifier,entry) in enumerate(zip(selection['selected'],result['slots'])):
            names = entry.get('collections',[])
            if names != [f'award-{i:03d}/usaspending',f'award-{i:03d}/fpds']:
                raise EvidenceError('unsupported_parent_holdout_layout')
            sources.append((f'holdout/slot-{i:03d}',tuple(holdout/Path(*parts(n)) for n in names),identifier))
    slots,unavailable,downstream = [],[],[]
    for label,paths,identifier in sources:
        try:
            with EvidenceRoot(paths[0]) as root: cp = strict_json(root.read('c3_plan.json').data)
            if cp['awards'][0]['generated_id'] != identifier: raise EvidenceError('parent_frozen_selection_conflict')
            requested = native_request(paths[0],cp)
            run = assess_parent_collection(paths,requested)
            history = reconstruct(paths,requested)
            slots.append((label,run))
            downstream.append({'slot':label,'unit':'legacy_history_record_pair_results','metrics':history_metrics(history),
                'history_sha256':history.substantive_sha256,'experimental_scope_consumed':False})
        except (ValueError,TypeError,KeyError,IndexError,OSError):
            unavailable.append({'slot':label,'selected_native_id':identifier,'reason':'unavailable_or_invalid_primary_evidence_no_substitution'})
    if inventory(frozen) != before or holdout and inventory(holdout) != holdout_before:
        raise EvidenceError('parent_cohort_inventory_changed')
    return report_for(slots,protocol=p,unavailable=unavailable,downstream=downstream)


def demo(path):
    from .collection import CollectionLimits, collect_selected
    from .collection_sources import FixtureTransport
    from .research_demo import demo_case
    from dataclasses import replace
    from .scope_models import ScopeRequest
    target = Path(path)
    slots = []
    with PilotStore(target,{'schema_type':'ParentSyntheticDemo','schema_version':1,'config':{'max_run_bytes':4*1024*1024}}) as store:
        for case in ('standalone_D','missing_type','order_parent','unknown_requested_parent'):
            award,fixture = demo_case('agreement')
            if case in ('standalone_D','missing_type'):
                award = replace(award,parent_piid=None,parent_agency_id=None)
                row = fixture['responses'][0]['json']['results'][0]
                row['id'] = row['id'].replace('0001_0002_','0001_-NONE-_').replace('_SYNTH-PARENT_','_-NONE-_')
                text = fixture['responses'][-1]['text']; start = text.index('<f:referencedIDVID>'); end = text.index('</f:referencedIDVID>')+len('</f:referencedIDVID>')
                text = text[:start]+text[end:]
                fixture['responses'][-1]['text'] = text.replace('<f:award>','<f:award version="1.5">').replace('</f:award>',('<f:contractData><f:contractActionType>D</f:contractActionType></f:contractData>' if case=='standalone_D' else '')+'</f:award>')
            else:
                fixture['responses'][-1]['text'] = fixture['responses'][-1]['text'].replace('<f:award>','<f:award version="1.5">').replace('</f:award>','<f:contractData><f:contractActionType>C</f:contractActionType></f:contractData></f:award>')
            if case == 'unknown_requested_parent':
                award = replace(award,parent_piid=None,parent_agency_id=None)
            root = store.path/case
            collect_selected(root,(award,),limits=CollectionLimits(max_awards=1,max_requests=2,retries=0,pace_seconds=0.0),
                transport=FixtureTransport(fixture),profile='fixture:'+digest(fixture),sleep=lambda _:None)
            requested = ScopeRequest(piid=award.piid,agency=award.agency_id,
                parent_piid=None if case=='unknown_requested_parent' else award.parent_piid,
                parent_agency=None if case=='unknown_requested_parent' else award.parent_agency_id)
            slots.append(('synthetic/'+case,assess_parent_collection((root,),requested)))
    return report_for(slots,protocol=protocol())


def main(argv=None):
    parser = argparse.ArgumentParser(description='Offline experimental parent identity evidence; no HTTP or financial integration.')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--root'); mode.add_argument('--demo',action='store_true')
    parser.add_argument('--holdout-root'); parser.add_argument('--run-dir',required=True)
    args = parser.parse_args(argv)
    try:
        if args.demo:
            if args.holdout_root: raise EvidenceError('demo_cannot_consume_live_cohort')
            target = Path(args.run_dir)
            # Synthetic source journals are in a distinct sibling, never inside
            # the report root and never a fallback for missing real evidence.
            source = target.with_name(target.name+'-synthetic-evidence')
            report = demo(source)
            value = write_report(target,report,protected=(source,))
        else:
            protected = tuple(p for p in (args.root,args.holdout_root) if p)
            outside(args.run_dir,protected)
            report = evaluate_frozen(args.root,args.holdout_root)
            value = write_report(args.run_dir,report,protected=protected)
        print(canonical({'substantive_sha256':value,'exit_code':1})); return 1
    except KeyboardInterrupt: return 130
    except (ValueError,TypeError,KeyError,IndexError,OSError):
        print(canonical({'error_code':'parent_identity_evaluation_failed','exit_code':2})); return 2


if __name__ == '__main__': raise SystemExit(main())
