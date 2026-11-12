"""C17 opt-in fallback reuses frozen C12/C14 collectors, at most five USA requests."""
from pathlib import Path
from .acquisition_planning import prepare, AcquisitionLimits
from .source_verification import VerificationExperiment, experiment, inspect_experiment
from .parent_history_probe import collect as collect_parent
from .correction_reporting import report as c14_report, _paths
from .authority_binding import c14_case, REASON
from .award_validation import snapshot
from .evidence_io import EvidenceError, canonical, digest
from .pilot_store import PilotStore
from .review_packet_io import outside


def plan(case, *, live=False):
    if type(case) is not dict:raise EvidenceError('typed_original_fallback_case_required')
    clean = {k:v for k,v in case.items() if k not in ('new_parent_capture','new_parent_history')}
    old = c14_report([c14_case(clean)])
    impacts = [p for p in old['cases'][0]['original_requirement_impacts'] if p['dimension']=='parent_identity'
        and p['native_context']['namespace']=='usaspending' and p['original_requirement']['status']=='INSUFFICIENT_EVIDENCE'
        and p['original_requirement']['reasons']==REASON and not p['original_requirement_resolved']]
    if len(impacts)!=1 or clean.get('c12_capture') or clean.get('parent_history'):
        raise EvidenceError('one_original_missing_parent_primary_target_required')
    queue=prepare([clean],limits=AcquisitionLimits(max_pages=1,page_size=10,max_requests=3))
    specs=[s for s in queue.requests if s.source=='usaspending' and s.target_kind=='award_history']
    if len(specs)!=1:raise EvidenceError('one_exact_public_USA_request_spec_required')
    profile=old['profile']
    if type(live) is not bool or live and profile!='live':raise EvidenceError('explicit_matching_source_profile_required')
    ex=VerificationExperiment(queue=queue,request_id=specs[0].request_id,
        mode='explicit_public_USA_validation' if live else 'synthetic_only' if profile=='synthetic' else 'offline_only')
    return {'schema_type':'ParentAuthorityAcquisitionPlan','schema_version':1,'profile':profile,
        'original_requirement_id':impacts[0]['original_plan_id'],'original_requirement':impacts[0]['original_requirement'],
        'original_case_sha256':old['cases'][0]['original_case_sha256'],'experiment':ex.to_dict(),
        'original_inventories':[{n:s.byte_sha256 for n,s in snapshot(p).items()} for p in _paths(c14_case(clean))],
        'source_allowlist':['usaspending'],'maximum_requests':5,'maximum_transaction_rows':20,
        'maximum_response_bytes':1048576,'timeout_seconds':10,'pace_seconds':1,'retries':0,'redirects':False,
        'financial_comparison_authorized':False,'config':{'max_run_bytes':1048576}}


def collect(journal,case,*,live=False,synthetic=None):
    p=plan(case,live=live)
    if live and synthetic is not None or not live and (p['profile']!='synthetic' or synthetic is None):
        raise EvidenceError('offline_default_no_source_access')
    if not case.get('new_parent_capture') or not case.get('new_parent_history'):
        raise EvidenceError('two_new_separate_capture_paths_required')
    source,parent=case['new_parent_capture'],case['new_parent_history']
    protected=_paths(c14_case({k:v for k,v in case.items() if k not in ('new_parent_capture','new_parent_history')}))
    for path,others in ((journal,protected+[source,parent]),(source,protected+[journal,parent]),(parent,protected+[journal,source])):
        outside(path,others)
    ex=VerificationExperiment.from_dict(p['experiment'])
    with PilotStore(journal,p) as store:
        store.write('child-start.json',{'request_id':ex.request_id})
        experiment(source,ex,live=live,synthetic=None if live else synthetic['child'])
        observed=inspect_experiment(source)
        store.write('child-complete.json',{'inventory_sha256':observed['inventory_sha256'],
            'current_parent_link':observed['current_source_parent_link']})
        if usable(observed):
            store.write('parent-start.json',{'source_returned_parent':observed['parent']['native_award_id']})
            value=collect_parent(parent,source,live=live,synthetic=None if live else synthetic['parent'])
            store.write('parent-complete.json',{'inventory_sha256':value['inventory_sha256'],'failures':value['failures']})
        if plan(case,live=live)!=p:raise EvidenceError('original_context_changed_during_capture')
        store.write('acquisition-commit.json',{'schema_version':1,'files':store.inventory()})
    return p


def usable(observation):
    contract=observation.get('transaction_contract')
    return (observation['current_source_parent_link']=='verified_source_local_summary_link'
        and bool(contract and contract['histories']) and not contract['failures']
        and all(h['source_contract_satisfied'] for h in contract['histories']))
