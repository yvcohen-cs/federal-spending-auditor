"""C11 offline acquisition and primary-evidence resolution replay. No live transport."""
import argparse
from dataclasses import dataclass
from html import escape
from pathlib import Path
import re

from .acquisition_planning import (RULE, AcquisitionQueue, AcquisitionLimits, QuerySupport,
    case_report, prepare)
from .award_validation import snapshot, validate as diagnose, pagination
from .collection import CollectionLimits, SelectedAward, collect_selected
from .collection_sources import FixtureTransport, parse_page
from .evidence import Schema
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json
from .history_qualification import QualificationStatus as Q, HistoricalInterval
from .history_reporting import bounded_json
from .pilot_store import PilotStore
from .review_packet_io import outside
from .sam_validation_capture import (SAMResearchSelection, collect as collect_sam, secret_free)
from .scope_models import ScopeRequest


@dataclass(frozen=True,kw_only=True)
class PreservedReplay(Schema):
    request_id:str
    path:str


@dataclass(frozen=True,kw_only=True)
class SyntheticScenario(Schema):
    request_id:str
    scenario_json:str

    def validate(self):
        value=strict_json(self.scenario_json.encode())
        if not isinstance(value,dict) or canonical(value)!=self.scenario_json or not secret_free(value):
            raise ValueError('canonical_credential_free_synthetic_scenario_required')
        if set(value)!={'schema_version','responses'} or type(value['schema_version']) is not int or value['schema_version']!=1 or not isinstance(value['responses'],list) or len(value['responses'])>64:
            raise ValueError('bounded_synthetic_transcript_required')


def manifest(values):return {n:s.byte_sha256 for n,s in values.items()}


def scope_for(spec):
    n=strict_json(spec.native_context_json.encode())
    return ScopeRequest(namespace='samgov-v1' if spec.source=='samgov' else 'usa-fpds-v1',**n)


def inspect_capture(path,spec):
    before=snapshot(path);files=manifest(before)
    if 'c3_plan.json' in before:
        if spec.source=='samgov':raise EvidenceError('wrong_source_capture_adapter')
        plan=strict_json(before['c3_plan.json'].data)
        if len(plan['awards'])!=1 or spec.source not in plan['sources']:raise EvidenceError('capture_selection_mismatch')
        a=plan['awards'][0];n=strict_json(spec.native_context_json.encode())
        if (a['piid'],a['agency_id'],a['parent_piid'],a['parent_agency_id'])!=(n['piid'],n['agency'],n['parent_piid'],n['parent_agency']):raise EvidenceError('capture_native_context_mismatch')
        selected=SelectedAward.from_dict(strict_json(spec.selection_json.encode()))
        if spec.source=='usaspending' and a['generated_id']!=selected.generated_id:raise EvidenceError('capture_USA_query_id_mismatch')
        diagnostic=diagnose((path,),scope_for(spec))
        pages=[p for c in diagnostic['pagination'] for p in c['sources'] if p['source']==spec.source]
        attempts=[strict_json(s.data) for n,s in before.items() if re.fullmatch(r'c3_attempt_[0-9]{6}\.json',n)]
        # A bounded successful retry may supply a narrow observation without
        # erasing the failed attempt or certifying historical completeness.
        successful=[];attempted=set();bad=False
        for name,saved in before.items():
            if re.fullmatch(r'c3_attempt_[0-9]{6}\.json',name) is None:continue
            meta=strict_json(saved.data)
            if meta['request']['source']!=spec.source:continue
            attempted.add(meta['request']['page_index'])
            body=before.get(name[:-5]+'.body')
            if meta['error_code'] or meta['status'] is None or not 200<=meta['status']<300 or not meta['body_complete'] or body is None:continue
            try:
                parsed=parse_page(spec.source,body.data,meta['request'],plan['awards'][0])
                successful.append((meta['request']['page_index'],parsed['has_next'],tuple(parsed['fingerprints'])))
            except (ValueError,TypeError,KeyError):bad=True
        chain=pagination(successful)
        status='validated_observed_subset' if not bad and chain['bounded_observed_chain']=='consistent_terminal' and attempted<={p[0] for p in successful} else 'partial_empty_or_conflicting_capture'
        profile='synthetic' if plan['profile'].startswith('fixture:') else plan['profile']
    else:
        if spec.source!='samgov':raise EvidenceError('wrong_source_capture_adapter')
        diagnostic=diagnose(sam_captures=(path,));c=diagnostic['sam_assessment']['captures'][0]
        if c['state']!='revalidated_bounded_capture':raise EvidenceError('unvalidated_SAM_capture')
        plan=strict_json(before['sam-research-plan.json'].data) if 'sam-research-plan.json' in before else strict_json(before['pilot-plan.json'].data)
        selection=SAMResearchSelection.from_dict(plan['selection']);wanted=scope_for(spec)
        if not any(s==wanted for s in selection.subjects):raise EvidenceError('capture_SAM_native_selection_mismatch')
        pages=[p['assessment'] for p in c['pagination']]
        attempts=[strict_json(s.data) for n,s in before.items() if re.fullmatch(r'sam-attempt-[0-9]{3}\.json',n)]
        bad=any(p['interpretation'] in ('contradictory_response_metadata','incomplete_or_interrupted_capture') or 'nonterminal_page_limit_or_partial_history' in p['issues'] for p in pages)
        status='validated_observed_subset' if pages and not bad and not c['blockers'] else 'partial_empty_or_conflicting_capture'
        profile=c['profile']
    if profile!=spec.evidence_profile:raise EvidenceError('synthetic_and_preserved_live_cohorts_must_not_mix')
    records=[r for r in diagnostic['records'] if r['source']==spec.source]
    wanted_native=strict_json(spec.native_context_json.encode())
    def matches(row):
        if row['scope_status'] in ('verified_out_of_scope','unsupported_schema'):return False
        if spec.source=='samgov':
            a=row['native_award'];actual={'piid':a['piid'],'agency':a['identity_subtier'],'parent_piid':a['parent_piid'],'parent_agency':a['parent_subtier']}
        else:
            actual={k:v['value'] for k,v in row['native_context'].items()}
            if any(v['state']=='conflicting' for v in row['native_context'].values()):return False
        return all(v is None or actual.get(k)==v for k,v in wanted_native.items())
    if not records:status='empty_inconclusive_no_absence_claim'
    elif not any(matches(r) for r in records):status='native_scope_unresolved'
    all_attempts=len(attempts)
    if spec.source!='samgov':attempts=[m for m in attempts if m['request']['source']==spec.source]
    else:
        target_index=selection.subjects.index(wanted)
        attempts=[m for m in attempts if m['subject_index']==target_index]
    if len(attempts)>spec.limits.max_requests or any(len(s.data)>spec.limits.max_response_bytes for n,s in before.items() if n.endswith('.body')):
        raise EvidenceError('capture_request_or_response_budget_exceeded')
    if manifest(snapshot(path))!=files:raise EvidenceError('acquisition_source_changed')
    return before,{'inventory_sha256':digest(files),'recorded_attempts':len(attempts),'all_source_attempts_preserved':all_attempts,'source':spec.source,
        'evidence_profile':profile,'observed_records':len(records),'status':status,
        'capture_limitations':diagnostic['artifact_issues'] if spec.source!='samgov' else c['blockers'],
        'knowledge_basis':'SYNTHETIC_ONLY' if profile=='synthetic' else 'PRESERVED_SOURCE_OBSERVATION_NOT_NEW_HTTP_REQUEST',
        'transaction_history_complete':'unknown','source_wide_complete':'unknown','freshness':'unknown',
        'new_live_requests':0,'financial_comparison_authorized':False}


def materialize(path,spec,scenario,remaining):
    if spec.evidence_profile!='synthetic':raise EvidenceError('synthetic_scenario_cannot_populate_live_evidence_cohort')
    value=strict_json(scenario.scenario_json.encode())
    if spec.source in ('usaspending','fpds'):
        limits=CollectionLimits(max_awards=1,max_pages=spec.limits.max_pages,page_size=spec.limits.page_size,
            max_records_per_source_award=10*spec.limits.max_pages,max_records_total=10*spec.limits.max_pages,
            max_requests=min(remaining,spec.limits.max_requests),retries=spec.limits.retries,
            pace_seconds=0.0,backoff_seconds=0.0,max_retry_after_seconds=0.0,max_response_bytes=spec.limits.max_response_bytes)
        collect_selected(path,(SelectedAward.from_dict(strict_json(spec.selection_json.encode())),),sources=(spec.source,),limits=limits,
            transport=FixtureTransport(value),profile='fixture:'+digest(value),sleep=lambda _:None,stop_on_context_mismatch=True)
    else:
        subject=ScopeRequest.from_dict(strict_json(spec.selection_json.encode()))
        selection=SAMResearchSelection(subjects=(subject,),limit=spec.limits.page_size,profile='synthetic',pagination_rule='unvalidated')
        def send(request,index):
            if index>=remaining or index>=len(value['responses']):raise EvidenceError('synthetic_transcript_exhausted')
            r=value['responses'][index]
            if r.get('source')!='samgov':raise EvidenceError('synthetic_source_mismatch')
            raw=canonical(r['json']).encode() if 'json' in r else None
            if raw is not None and len(raw)>spec.limits.max_response_bytes:raise EvidenceError('synthetic_response_budget')
            return {'status':r.get('status',200),'retrieved_at_utc':r.get('retrieved_at_utc','2025-01-01T00:00:00Z'),
                'body_complete':r.get('body_complete',True),'error_code':r.get('error_code'),'headers':{}},raw
        # Explicit fixture transport and synthetic profile: no credentials or
        # HTTP transport is instantiated. Frozen SAM retry/continuation stays 0.
        collect_sam(path,selection,live=True,fixture_transport=send,sleep=lambda _:None)


def acquire(queue,path,*,preserved=(),synthetic=(),live=False):
    if type(live) is not bool or live:raise EvidenceError('live_access_and_authorization_not_verified_no_live_transport')
    if not isinstance(queue,AcquisitionQueue):raise EvidenceError('typed_acquisition_queue_required')
    preserved=tuple(preserved);synthetic=tuple(synthetic);bindings=preserved+synthetic
    if any(not isinstance(v,(PreservedReplay,SyntheticScenario)) for v in bindings):raise EvidenceError('offline_binding_type_required')
    specs={s.request_id:s for s in queue.requests}
    if len({v.request_id for v in bindings})!=len(bindings) or any(v.request_id not in specs for v in bindings):raise EvidenceError('duplicate_or_unknown_request_binding')
    outside(path,tuple(v.path for v in preserved));receipts=[];spent=0
    plan={'schema_type':'OfflineAcquisitionPlan','schema_version':1,'rule_version':RULE,'queue':queue.to_dict(),'config':{'max_run_bytes':64*1024*1024}}
    with PilotStore(path,plan) as store:
        for index,binding in enumerate(sorted(bindings,key=lambda b:b.request_id)):
            spec=specs[binding.request_id]
            receipt={'request_id':binding.request_id,'mode':'preserved_replay' if isinstance(binding,PreservedReplay) else 'synthetic_materialization',
                'capture_dir':None,'status':'not_acquired','request_budget_charged':0,'new_live_requests':0,'financial_comparison_authorized':False}
            if spec.query_support is not QuerySupport.DOCUMENTED_SUBSET:
                receipt['status']='query_requires_additional_validation';receipts.append(receipt);continue
            if spent>=queue.limits.max_requests:
                receipt['status']='request_budget_exhausted';receipts.append(receipt);continue
            reservation=min(queue.limits.max_requests-spent,1 if spec.source=='samgov' else spec.limits.max_pages*(spec.limits.retries+1))
            spent+=reservation;receipt['request_budget_charged']=reservation
            try:
                source=binding.path if isinstance(binding,PreservedReplay) else str(Path(path).with_name(Path(path).name+f'-synthetic-{index:03d}'))
                if isinstance(binding,SyntheticScenario):materialize(source,spec,binding,reservation)
                values,stats=inspect_capture(source,spec)
                if stats['recorded_attempts']>reservation:raise EvidenceError('reserved_request_budget_exceeded')
                name=f'capture-{index:03d}';store.mkdir(name)
                for relative,snapshot_value in sorted(values.items()):
                    if '/' in relative:raise EvidenceError('one_flat_source_capture_required')
                    store.write_bytes(name+'/'+relative,snapshot_value.data)
                if manifest(snapshot(source))!=manifest(values):raise EvidenceError('acquisition_source_changed')
                # Revalidate the copied primary capture, not merely its copied hash.
                _,copied=inspect_capture(store.path/name,spec)
                if canonical(copied)!=canonical(stats):raise EvidenceError('copied_capture_provenance_conflict')
                spent-=reservation-stats['recorded_attempts'];receipt['request_budget_charged']=stats['recorded_attempts']
                receipt.update(stats,capture_dir=name)
            except (ValueError,TypeError,KeyError,IndexError,OSError):
                receipt['status']='acquisition_failed_primary_evidence_retained'
            receipts.append(receipt)
        result={'schema_type':'OfflineAcquisitionRun','schema_version':1,'rule_version':RULE,'queue_sha256':queue.queue_sha256,
            'receipts':receipts,'recorded_attempts':sum(r.get('recorded_attempts',0) for r in receipts),'request_budget_charged':spent,'new_live_requests':0,'financial_comparison_authorized':False,
            'not_supplied_request_ids':sorted(set(specs)-{b.request_id for b in bindings})}
        store.write('acquisition.json',result)
        store.write('acquisition-commit.json',{'schema_version':1,'files':store.inventory(),'run_sha256':digest(result)})
    return result


def read_run(path):
    with EvidenceRoot(path,max_bytes=32*1024*1024,max_total_bytes=64*1024*1024,max_files=4096) as root:
        values={n:root.read(n) for n in root.discover()}
        hashes=manifest(values)
        if {n:root.read(n,recheck=True).byte_sha256 for n in root.discover()}!=hashes:raise EvidenceError('acquisition_run_changed')
    if not {'acquisition.json','acquisition-commit.json','pilot-plan.json'}<=values.keys():raise EvidenceError('incomplete_acquisition_run')
    run=strict_json(values['acquisition.json'].data);plan=strict_json(values['pilot-plan.json'].data)
    queue=AcquisitionQueue.from_dict(plan['queue'])
    expected_plan={'schema_type':'OfflineAcquisitionPlan','schema_version':1,'rule_version':RULE,'queue':queue.to_dict(),'config':{'max_run_bytes':64*1024*1024}}
    if canonical(plan)!=canonical(expected_plan):raise EvidenceError('unsupported_acquisition_plan_or_budget')
    commit=strict_json(values['acquisition-commit.json'].data)
    expected={'schema_version':1,'files':{n:s.byte_sha256 for n,s in values.items() if n!='acquisition-commit.json'},'run_sha256':digest(run)}
    if canonical(commit)!=canonical(expected) or values['acquisition-commit.json'].data!=(canonical(expected)+'\n').encode():raise EvidenceError('acquisition_manifest_conflict')
    if run.get('schema_type')!='OfflineAcquisitionRun' or type(run.get('schema_version')) is not int or run['schema_version']!=1 or run.get('rule_version')!=RULE or run.get('new_live_requests')!=0 or type(run['new_live_requests']) is not int or run.get('financial_comparison_authorized') is not False or run.get('queue_sha256')!=queue.queue_sha256:
        raise EvidenceError('unsupported_or_authorizing_acquisition_run')
    specs={s.request_id:s for s in queue.requests};seen=set();spent=0;known=0;allowed={'acquisition.json','acquisition-commit.json','pilot-plan.json'}
    for r in run['receipts']:
        if r['mode'] not in ('preserved_replay','synthetic_materialization') or r['mode']=='synthetic_materialization' and specs.get(r['request_id']) is not None and specs[r['request_id']].evidence_profile!='synthetic':raise EvidenceError('unsupported_or_false_live_acquisition_mode')
        if r['request_id'] not in specs or r['request_id'] in seen:raise EvidenceError('unknown_or_replayed_acquisition_receipt')
        seen.add(r['request_id'])
        charged=r['request_budget_charged']
        if type(charged) is not int or not 0<=charged<=queue.limits.max_requests:raise EvidenceError('invalid_request_budget_charge')
        spent+=charged
        if r['new_live_requests']!=0 or type(r['new_live_requests']) is not int or r['financial_comparison_authorized'] is not False:raise EvidenceError('acquisition_receipt_authority_conflict')
        if r['capture_dir'] is not None:
            if not re.fullmatch(r'capture-[0-9]{3}',r['capture_dir']):raise EvidenceError('unsafe_acquisition_capture_path')
            _,stats=inspect_capture(Path(path)/r['capture_dir'],specs[r['request_id']])
            if any(canonical(r.get(k))!=canonical(v) for k,v in stats.items()):raise EvidenceError('acquisition_receipt_evidence_conflict')
            if charged!=stats['recorded_attempts']:raise EvidenceError('capture_budget_charge_conflict')
            known+=stats['recorded_attempts']
            allowed.update(n for n in values if n.startswith(r['capture_dir']+'/'))
        elif r['status'] not in ('query_requires_additional_validation','request_budget_exhausted','acquisition_failed_primary_evidence_retained'):
            raise EvidenceError('unsupported_acquisition_failure_state')
    # Partial source files may remain after failure. They must not become a
    # complete run or silently disappear under a newly signed positive receipt.
    if set(values)!=allowed or type(run.get('request_budget_charged')) is not int or spent!=run['request_budget_charged'] or type(run['recorded_attempts']) is not int or known!=run['recorded_attempts'] or spent>queue.limits.max_requests or run['not_supplied_request_ids']!=sorted(set(specs)-seen):
        raise EvidenceError('acquisition_inventory_or_budget_conflict')
    return queue,run


def _native_action(row):
    c=row['context']
    if row['source']=='samgov' or row['action'] is None:return None
    values=tuple(c.get(k) for k in ('piid','agency','parent_piid','parent_agency'))+tuple(row['action'])
    return values if all(v is not None for v in values) else None


def resolution_replay(cases,run_path):
    cases=tuple(cases);queue,run=read_run(run_path)
    if canonical(prepare(cases,limits=queue.limits).to_dict())!=canonical(queue.to_dict()):raise EvidenceError('queue_must_replay_original_primary_requirements')
    specs={s.request_id:s for s in queue.requests};before=[case_report(c) for c in cases];after=[];events=[];changes=[];observations=[]
    blocked=any(r['status']!='validated_observed_subset' for r in run['receipts'])
    for case,old in zip(cases,before):
        case_id=digest(old);collections=list(case.get('collections',()));sam=list(case.get('sam_captures',()))
        used={i['inventory_sha256'] for i in old['inputs']};supplied=[]
        for receipt in run['receipts']:
            spec=specs[receipt['request_id']]
            if not any(t.case_id==case_id for t in spec.requirements) or receipt['capture_dir'] is None:continue
            duplicate=receipt['inventory_sha256'] in used
            supplied.append({'request_id':spec.request_id,'inventory_sha256':receipt['inventory_sha256'],'duplicate_existing_input':duplicate,'incorporated':not blocked and not duplicate})
            if not blocked and not duplicate:
                used.add(receipt['inventory_sha256']);target=sam if spec.source=='samgov' else collections;target.append(str(Path(run_path)/receipt['capture_dir']))
        new=old if blocked else case_report({**case,'report':None,'collections':collections,'sam_captures':sam})
        oldcontracts={c['qualification']['contract_id']:c for c in old['contracts']};newcontracts={c['qualification']['contract_id']:c for c in new['contracts']}
        oldids={r['id'] for c in old['contracts'] for r in c['observed_occurrences']}
        for c in new['contracts']:
            for row in c['observed_occurrences']:
                if row['id'] in oldids:continue
                observations.append({'case_id':case_id,'observation_id':row['id'],'source':row['source'],
                    'native_context':row['context'],'native_action':row['action'],'source_native_identifiers':row['native_identifiers'],
                    'observed_monetary_fields':row['money'],'observed_temporal_fields':row['temporal_fields'],
                    'retrieved_at_utc':row['retrieved_at_utc'],'native_revision_fields':row.get('native_action'),
                    'provenance_reference':row['citation'],'revision_winner_selected':False,'missing_modifications_inferred':False})
                matched=False
                for receipt in run['receipts']:
                    spec=specs[receipt['request_id']]
                    if receipt['capture_dir'] is None or receipt['inventory_sha256']!=new['inputs'][row['input_index']]['inventory_sha256']:continue
                    for t in spec.requirements:
                        if t.case_id!=case_id:continue
                        original=oldcontracts[t.contract_id];prior=strict_json(t.original_requirement_json.encode())
                        applicable=spec.source==row['source'] and (c['qualification']['contract_id']==t.contract_id or t.dimension=='counterpart_coverage' and row['source']!='samgov' and not row['outside_requested_context'] and _native_action(row) is not None and any(_native_action(r)==_native_action(row) for r in original['observed_occurrences']))
                        current=next((r for r in newcontracts.get(t.contract_id,original)['qualification']['requirements'] if r['dimension']==t.dimension),prior)
                        resolved=applicable and not blocked and prior['status']!=Q.QUALIFIED.value and current['status']==Q.QUALIFIED.value
                        if len(events)>=10000:raise EvidenceError('resolution_trace_record_limit')
                        events.append({'case_id':case_id,'request_id':spec.request_id,'original_plan_id':t.plan_id,'original_requirement':prior,
                            'new_observation_id':row['id'],'source':row['source'],'native_context':row['context'],'native_action':row['action'],'provenance_reference':row['citation'],
                            'source_native_identifiers':row['native_identifiers'],'supplied_as_unrequested_context':spec.source!=row['source'],
                            'remaining_contract_blockers':[{'dimension':r['dimension'],'status':r['status'],'reasons':r['reasons']} for r in newcontracts.get(t.contract_id,original)['qualification']['requirements'] if r['status']!=Q.QUALIFIED.value],
                            'dimension_affected':t.dimension,'applicable_native_context':applicable,'requirement_resolved':resolved,'recomputed_requirement':current,
                            'remaining_blockers':current['reasons'] if current['status']!=Q.QUALIFIED.value else [],'financial_comparison_authorized':False})
                        matched=True
                if not matched:raise EvidenceError('new_observation_without_original_request_trace')
        after.append(new);changes.append({'case_id':case_id,'before_sha256':digest(old),'after_sha256':digest(new),'supplied_evidence':supplied,
            'qualification_recomputed':not blocked,'remaining_requirements':[{'contract_id':c['qualification']['contract_id'],'requirement':r} for c in new['contracts'] for r in c['qualification']['requirements'] if r['status']!=Q.QUALIFIED.value]})
    if len(events)>10000:raise EvidenceError('resolution_trace_record_limit')
    return {'schema_type':'EvidenceAcquisitionResolutionReport','schema_version':1,'rule_version':RULE,'queue':queue.to_dict(),'run':run,
        'cases':changes,'incorporated_observations':sorted(observations,key=canonical),'observation_impacts':sorted(events,key=canonical),'resolved_plan_ids':sorted({e['original_plan_id'] for e in events if e['requirement_resolved']}),
        'acquisition_failure_blocks_incorporation':blocked,'financial_comparison_authorized':False,'production_readiness_changed':False,
        'new_live_requests':0,'interpretation':'Offline preserved replay and labeled synthetic controls only; no new live federal API observation or allegation.'}


def markdown(value):
    lines=['# Offline targeted evidence acquisition v1','','No live requests or financial authorization.','',
        'Prepared requests: '+str(len(value['queue']['requests'])),
        'Documented offline request subsets: '+str(sum(s['query_support']==QuerySupport.DOCUMENTED_SUBSET.value for s in value['queue']['requests'])),
        'Requests requiring selection/source validation: '+str(sum(s['query_support']!=QuerySupport.DOCUMENTED_SUBSET.value for s in value['queue']['requests'])),
        'Preserved replay receipts: '+str(sum(r['mode']=='preserved_replay' for r in value['run']['receipts']))+'; synthetic materializations: '+str(sum(r['mode']=='synthetic_materialization' for r in value['run']['receipts'])),
        'Original query attempts observed: '+str(value['run']['recorded_attempts'])+'; budget charged including uncertainty: '+str(value['run']['request_budget_charged']),
        'Resolved narrow requirement plans: '+str(len(value['resolved_plan_ids'])),
        'Failed acquisition blocks incorporation: '+str(value['acquisition_failure_blocks_incorporation']),
        'Historical/source-wide completeness and freshness remain unknown.','','```json',canonical(value).replace('`','\\u0060'),'```','']
    return '\n'.join(lines)


def html(value):return '<!doctype html><html lang="en"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; base-uri \'none\'"><title>Offline evidence acquisition</title><pre>'+escape(markdown(value))+'</pre></html>\n'


def write_report(path,value,*,protected=()):
    if value.get('financial_comparison_authorized') is not False or value.get('production_readiness_changed') is not False or type(value.get('new_live_requests')) is not int or value['new_live_requests']!=0:raise EvidenceError('acquisition_report_cannot_authorize_operations')
    outside(path,protected)
    with PilotStore(path,{'schema_type':'AcquisitionReportPlan','schema_version':1,'config':{'max_run_bytes':128*1024*1024}}) as store:
        store.write_bytes('resolution.json',bounded_json(value));store.write_bytes('resolution.md',markdown(value).encode());store.write_bytes('resolution.html',html(value).encode())
        store.write('resolution-commit.json',{'schema_version':1,'files':store.inventory(),'report_sha256':digest(value)})
    return digest(value)


def verify_report(path,cases,run_path):
    values=snapshot(path)
    if set(values)!={'resolution.json','resolution.md','resolution.html','resolution-commit.json','pilot-plan.json'}:raise EvidenceError('incomplete_acquisition_report')
    value=strict_json(values['resolution.json'].data);commit=strict_json(values['resolution-commit.json'].data)
    expected={'schema_version':1,'files':{n:s.byte_sha256 for n,s in values.items() if n!='resolution-commit.json'},'report_sha256':digest(value)}
    if canonical(commit)!=canonical(expected) or values['resolution-commit.json'].data!=(canonical(expected)+'\n').encode():raise EvidenceError('resolution_manifest_conflict')
    if canonical(value)!=canonical(resolution_replay(cases,run_path)) or values['resolution.md'].data!=markdown(value).encode() or values['resolution.html'].data!=html(value).encode():raise EvidenceError('resolution_primary_replay_conflict')
    return value


def main(argv=None):
    parser=argparse.ArgumentParser(description='Bounded offline source acquisition and evidence resolution; no live transport is authorized.')
    parser.add_argument('--cases',required=True);parser.add_argument('--run-dir',required=True)
    parser.add_argument('--replay-map');parser.add_argument('--fixture-map');parser.add_argument('--live',action='store_true')
    parser.add_argument('--max-jobs',type=int,default=8);parser.add_argument('--max-requests',type=int,default=16)
    mode=parser.add_mutually_exclusive_group(required=True);mode.add_argument('--report-dir');mode.add_argument('--verify-report')
    args=parser.parse_args(argv)
    try:
        if args.live:raise EvidenceError('live_access_and_authorization_not_verified_no_live_transport')
        from .collect_evidence import load_input
        cases=load_input(args.cases)
        if not isinstance(cases,list):raise EvidenceError('case_list_required')
        if args.verify_report:value=verify_report(args.verify_report,cases,args.run_dir)
        else:
            queue=prepare(cases,limits=AcquisitionLimits(max_jobs=args.max_jobs,max_requests=args.max_requests))
            replay=tuple(PreservedReplay.from_dict(v) for v in load_input(args.replay_map)) if args.replay_map else ()
            synthetic=tuple(SyntheticScenario(request_id=v['request_id'],scenario_json=canonical(v['scenario'])) for v in load_input(args.fixture_map)) if args.fixture_map else ()
            protected=tuple(p for c in cases for p in tuple(c.get('collections',()))+tuple(c.get('sam_captures',()))+((c['report'],) if c.get('report') else ()))+(args.cases,)+(tuple(v.path for v in replay))
            outside(args.run_dir,protected);outside(args.report_dir,protected+(args.run_dir,))
            acquire(queue,args.run_dir,preserved=replay,synthetic=synthetic)
            value=resolution_replay(cases,args.run_dir);write_report(args.report_dir,value,protected=protected+(args.run_dir,))
        print(canonical({'report_sha256':digest(value),'new_live_requests':0,'financial_comparison_authorized':False,'resolved_plan_count':len(value['resolved_plan_ids']),'acquisition_failure_blocks_incorporation':value['acquisition_failure_blocks_incorporation']}));return 1 if value['acquisition_failure_blocks_incorporation'] else 0
    except (ValueError,TypeError,KeyError,IndexError,OSError):
        print(canonical({'error_code':'offline_acquisition_blocked_no_sensitive_details'}));return 2


if __name__=='__main__':raise SystemExit(main())
