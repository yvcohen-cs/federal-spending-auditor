"""Deterministic C10 reports; primary-input replay is required to trust claims."""
import argparse
from html import escape

from .award_validation import snapshot
from .evidence_io import EvidenceError, canonical, digest, strict_json
from .history_qualification import (RULE, DIMENSIONS, ContractQualification, EvidenceResolutionPlan,
    HistoricalInterval, QualificationStatus, qualify, _qualify, resolution, project_contract, project_triage, relevant_pages)
from .history_reporting import bounded_json
from .pilot_store import PilotStore
from .review_packet_io import outside
from .scope_models import ScopeRequest

FLAGS=('qualification_authorizes_arithmetic','financial_eligibility_changed','production_readiness_changed',
       'new_collection_enabled','real_participant_operations_enabled')


def check(value):
    if (type(value) is not dict or value.get('schema_type')!='ContractHistoryQualificationReport'
        or type(value.get('schema_version')) is not int or value['schema_version']!=1 or value.get('rule_version')!=RULE
        or any(value.get(k) is not False for k in FLAGS)):
        raise EvidenceError('unsupported_or_authorizing_qualification_report')
    interval=HistoricalInterval.from_dict(value['requested_interval'])
    if value['requested_scope'] is not None: ScopeRequest.from_dict(value['requested_scope'])
    registry={}
    for c in value['contracts']:
        q=ContractQualification.from_dict(c['qualification'])
        rows=c['observed_occurrences']
        if tuple(sorted(r['id'] for r in rows))!=q.occurrence_ids or any(r['source']!=q.source or canonical(r['context'])!=q.native_context_json for r in rows):
            raise EvidenceError('qualification_occurrence_binding_conflict')
        for row in rows:
            if row['id'] in registry: raise EvidenceError('duplicate_qualification_occurrence')
            registry[row['id']]=row
        pages=relevant_pages(q.source,rows,value['pagination_evidence'])
        expected=_qualify(q.source,rows,strict_json(q.native_context_json.encode()),pages,interval)
        if canonical(expected.to_dict())!=canonical(q.to_dict()): raise EvidenceError('qualification_requirement_conflict')
        if canonical(c)!=canonical(project_contract(q,rows,interval)): raise EvidenceError('qualification_history_projection_conflict')
    plans={}
    for raw in value['resolution_plans']:
        plan=EvidenceResolutionPlan.from_dict({k:v for k,v in raw.items() if k!='plan_id'})
        if plan.plan_id!=raw['plan_id'] or plan.plan_id in plans: raise EvidenceError('resolution_plan_identity_conflict')
        plans[plan.plan_id]=plan
    expected_keys=set()
    for c in value['contracts']:
        q=ContractQualification.from_dict(c['qualification'])
        for req in q.requirements:
            if any(cid not in registry for cid in req.citation_ids): raise EvidenceError('missing_qualification_citation')
            if req.status is not QualificationStatus.QUALIFIED:
                expected_keys.add((q.contract_id,req.dimension))
                expected_plan=resolution(q,req,interval,c['observed_occurrences'])
                matches=[p for p in plans.values() if canonical(p.to_dict())==canonical(expected_plan.to_dict())]
                if len(matches)!=1: raise EvidenceError('missing_or_contradictory_resolution_plan')
    if {(p.contract_id,p.requirement.dimension) for p in plans.values()}!=expected_keys or len(plans)!=len(expected_keys):
        raise EvidenceError('extra_or_duplicate_resolution_plan')
    if canonical(value['gap_triage'])!=canonical(project_triage(value['contracts'],value['resolution_plans'])):
        raise EvidenceError('qualification_triage_projection_conflict')
    return value


def markdown(value):
    lines=['# Contract-history evidence qualification v1','','Evidence quality only. Financial arithmetic and production screening remain unauthorized.','',
           '| Source-local contract | Status | Unresolved requirements |','| --- | --- | ---: |']
    lines.insert(4,'Unusable C3 artifacts: '+str(len(value['unavailable_artifact_issues']))+'; unrevalidated SAM captures: '+str(sum(c['state']!='revalidated_bounded_capture' for c in value['sam_capture_assessments']))+'. No positive contract claim is made from an unrevalidated capture.')
    lines.insert(5,'')
    for c in value['contracts']:
        q=c['qualification'];count=sum(r['status']!='QUALIFIED_EVIDENCE' for r in q['requirements'])
        lines.append('| '+escape(q['source']+' '+q['contract_id'])+' | '+q['status']+' | '+str(count)+' |')
    for c in value['contracts']:
        q=c['qualification'];lines.extend(('', '## '+escape(q['contract_id']),''))
        for r in q['requirements']:
            lines.append('- '+r['dimension']+': **'+r['status']+'** — '+escape(', '.join(r['reasons'])))
        lines.extend(('', 'History remains an observed subset. No amendment sequence or revision winner is inferred.'))
    lines.extend(('', '## Evidence-resolution priorities (no collection authorization)', ''))
    for p in sorted(value['resolution_plans'],key=lambda p:(DIMENSIONS.index(p['requirement']['dimension']),p['source'],p['contract_id'])):
        lines.extend(('- '+p['source']+' / '+p['requirement']['dimension']+': '+escape(p['missing_observation']),
            '  Native context: '+escape(p['native_identifiers_json'])+'; interval: '+escape(canonical(p['historical_interval'])),
            '  Supporting citations: '+', '.join(p['requirement']['citation_ids'])))
    lines.extend(('', '## Exact source citations, history and resolution procedures', '', '```json',
        canonical(value).replace('`','\\u0060'), '```', ''))
    return '\n'.join(lines)


def html(value):
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; base-uri \'none\'"><title>Contract evidence qualification</title><h1>Offline contract-history qualification</h1><pre>'+escape(markdown(value))+'</pre></html>\n'


def write_report(path,value,*,protected=()):
    check(value);outside(path,protected)
    with PilotStore(path,{'schema_type':'HistoryQualificationPlan','schema_version':1,'rule_version':RULE,
                          'config':{'max_run_bytes':128*1024*1024}}) as store:
        store.write_bytes('qualification.json',bounded_json(value))
        store.write_bytes('qualification.md',markdown(value).encode())
        store.write_bytes('qualification.html',html(value).encode())
        store.write('qualification-commit.json',{'schema_version':1,'files':store.inventory(),'report_sha256':digest(value)})
    return digest(value)


def read_report(path):
    values=snapshot(path)
    if set(values)!={'pilot-plan.json','qualification.json','qualification.md','qualification.html','qualification-commit.json'}:
        raise EvidenceError('incomplete_qualification_report')
    commit=strict_json(values['qualification-commit.json'].data)
    value=strict_json(values['qualification.json'].data)
    expected={'schema_version':1,'files':{n:s.byte_sha256 for n,s in values.items() if n!='qualification-commit.json'},'report_sha256':digest(value)}
    if canonical(commit)!=canonical(expected) or values['qualification-commit.json'].data!=(canonical(expected)+'\n').encode():
        raise EvidenceError('qualification_report_integrity')
    check(value)
    if values['qualification.md'].data!=markdown(value).encode() or values['qualification.html'].data!=html(value).encode():
        raise EvidenceError('qualification_projection_conflict')
    return value


def verify_report(path,collections=(),requested=None,*,sam_captures=(),interval=None):
    value=read_report(path)
    if canonical(value)!=canonical(qualify(collections,requested,sam_captures=sam_captures,interval=interval)):
        raise EvidenceError('qualification_primary_replay_conflict')
    return value


def main(argv=None):
    parser=argparse.ArgumentParser(description='Offline contract-history qualification and evidence-resolution plans; no collection or financial authorization.')
    parser.add_argument('--collection',action='append',default=[])
    parser.add_argument('--sam-capture',action='append',default=[])
    parser.add_argument('--scope')
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--output');mode.add_argument('--verify-report')
    parser.add_argument('--history-start');parser.add_argument('--history-end');parser.add_argument('--as-of')
    args=parser.parse_args(argv)
    try:
        from .collect_evidence import load_input
        requested=ScopeRequest.from_dict(load_input(args.scope)) if args.scope else None
        interval=HistoricalInterval(start_date=args.history_start,end_date=args.history_end,as_of_date=args.as_of)
        if args.verify_report:
            value=verify_report(args.verify_report,args.collection,requested,sam_captures=args.sam_capture,interval=interval)
        else:
            protected=tuple(args.collection+args.sam_capture+([args.scope] if args.scope else []))
            outside(args.output,protected)
            value=qualify(args.collection,requested,sam_captures=args.sam_capture,interval=interval)
            write_report(args.output,value,protected=protected)
        print(canonical({'report_sha256':digest(value),'financial_comparison_authorized':False,'report_complete':True}))
        return 0
    except (ValueError,TypeError,KeyError,IndexError,OSError):
        print(canonical({'error_code':'offline_history_qualification_blocked'}));return 2


if __name__=='__main__':
    raise SystemExit(main())
