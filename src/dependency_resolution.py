"""C21 explicit bounded continuation for original C20-shortlisted dependencies.

Only acquisition pagination changes: C14 qualification and monetary safeguards do
not. The legacy C12 schema retains its two-page bound and serialization.
"""
from pathlib import Path
from .parent_authority_acquisition import plan as legacy_plan, usable
from .source_bound_reporting import original, ROLES, EXTRA as C20_EXTRA
from .acquisition_planning import prepare, AcquisitionLimits
from .source_verification import DependencyVerificationExperiment, experiment, inspect_experiment
from .parent_history_probe import collect as collect_parent, read as read_parent
from .correction_reporting import report as qualify, _paths
from .history_preflight import monetary_preflight
from .evidence_io import EvidenceError, canonical, digest
from .award_validation import snapshot
from .pilot_store import PilotStore
from .review_packet_io import outside

EXTRA=('c21_parent_capture','c21_parent_history')
TARGETS={
 'evidence-resolution:v1:140225679eaffd3a8c3192bcabb490404c3f084a840d681f27d4e61e50040cdf':'709773e4609bed43b34fd7e341a20c29955af4328516dc2ecc618582995c56f0',
 'evidence-resolution:v1:ed25336764203d9fc45a4ece18775a7e5e14250bdaa8176526495587d73d8ba8':'7264220eb71cc407ea0647c3143c28761591423df80c37258a2e125bec0078cf',
}

def clean(case):return {k:v for k,v in case.items() if k not in EXTRA}
def inventory(path):return {n:s.byte_sha256 for n,s in snapshot(path).items()}

def plan(case,*,live=False):
    if type(case) is not dict:raise EvidenceError('explicit_dependency_case_required')
    c=clean(case)
    if any(c.get(k) for k in ROLES[2:]+C20_EXTRA):raise EvidenceError('C21_cannot_rebind_prior_acquisition')
    base=original(c);old=legacy_plan(base,live=live)
    if old['profile']=='live' and TARGETS.get(old['original_requirement_id'])!=old['original_case_sha256']:
        raise EvidenceError('C20_original_shortlist_target_required')
    q=prepare([base],limits=AcquisitionLimits(max_pages=4,page_size=10,max_requests=6,retries=0))
    jobs=[s for s in q.requests if s.source=='usaspending' and s.target_kind=='award_history']
    if len(jobs)!=1:raise EvidenceError('one_exact_USA_child_required')
    ex=DependencyVerificationExperiment(queue=q,request_id=jobs[0].request_id,
        mode='explicit_public_USA_validation' if live else 'synthetic_only' if old['profile']=='synthetic' else 'offline_only')
    return {**old,'schema_type':'SourceBoundDependencyAcquisitionPlan','experiment':ex.to_dict(),
        'maximum_requests':8,'maximum_transaction_rows':50,'child_maximum_pages':4,'child_page_size':10,
        'parent_maximum_pages':2,'parent_page_size':5,
        'qualification_rule':'unchanged_C14_source_local_parent_identity_and_primary_existence',
        'pagination_is_not_historical_completeness':True}

def collect(journal,case,*,live=False,synthetic=None):
    p=plan(case,live=live)
    if live and synthetic is not None or not live and (p['profile']!='synthetic' or synthetic is None):
        raise EvidenceError('offline_default_no_source_access')
    if not all(case.get(k) for k in EXTRA):raise EvidenceError('two_new_separate_capture_paths_required')
    child,parent=(case[k] for k in EXTRA);protected=_paths(original(clean(case)))
    for path,others in ((journal,protected+[child,parent]),(child,protected+[journal,parent]),(parent,protected+[journal,child])):outside(path,others)
    with PilotStore(journal,p) as store:
        store.write('child-start.json',{'plan_sha256':digest(p)})
        experiment(child,DependencyVerificationExperiment.from_dict(p['experiment']),live=live,
                   synthetic=None if live else synthetic['child'])
        source=inspect_experiment(child);store.write('child-complete.json',{'inventory_sha256':source['inventory_sha256']})
        if usable(source):
            store.write('parent-start.json',{'source_returned_parent':source['parent']['native_award_id']})
            if live:
                import time
                time.sleep(1.0)
            observed=collect_parent(parent,child,live=live,synthetic=None if live else synthetic['parent'])
            store.write('parent-complete.json',{'inventory_sha256':observed['inventory_sha256']})
        if plan(case,live=live)!=p:raise EvidenceError('C21_original_context_changed')
        store.write('acquisition-commit.json',{'schema_version':1,'files':store.inventory()})
    return replay(case)

def replay(case):
    p=plan(case,live=False);source=inspect_experiment(case[EXTRA[0]])
    expected=plan(case,live=p['profile']=='live')
    if source['experiment']!=expected['experiment']:raise EvidenceError('C21_capture_plan_conflict')
    parent=None;impacts=[];money=None
    if usable(source) and case.get(EXTRA[1]) and Path(case[EXTRA[1]]).exists():
        parent=read_parent(case[EXTRA[1]],case[EXTRA[0]])
        if parent['capture_contract_version']!=2:raise EvidenceError('C21_parent_v2_required')
        augmented={**original(clean(case)),'c12_capture':case[EXTRA[0]],'parent_history':case[EXTRA[1]]}
        enhanced=qualify([augmented])['cases'][0]
        if enhanced['original_case_sha256']!=p['original_case_sha256']:raise EvidenceError('C21_original_identity_changed')
        for x in enhanced['original_requirement_impacts']:
            if x['original_requirement_resolved']:
                if (x['original_plan_id']!=p['original_requirement_id'] or x['original_requirement']!=p['original_requirement']
                        or x['dimension']!='parent_identity' or x['native_context']['namespace']!='usaspending'):
                    raise EvidenceError('C21_unsupported_resolution_expansion')
                impacts.append(x)
        money=monetary_preflight(enhanced,augmented,None)
        if any(type(money[k]) is not int or money[k]!=0 for k in ('totals_or_deltas_computed','amount_comparisons_performed')) or money['financial_comparison_authorized'] is not False:
            raise EvidenceError('C21_financial_assessment_only_required')
    attempts=source['request_attempts']+(0 if parent is None else parent['request_attempts'])
    child_rows=sum(len(h['observations']) for h in (source['transaction_contract'] or {}).get('histories',[]))
    parent_rows=0 if parent is None else len(parent['records'])
    if attempts>8 or child_rows>40 or parent_rows>10 or child_rows+parent_rows>50:
        raise EvidenceError('C21_request_or_record_budget_exceeded')
    return {'schema_type':'DependencyAcquisitionAssessment','schema_version':1,'profile':p['profile'],
        'plan':expected,'source':source,'parent':parent,'resolved_original_impacts':impacts,
        'request_attempts':attempts,'child_transaction_rows':child_rows,'parent_action_rows':parent_rows,
        'financial_preflight':money,'financial_comparison_authorized':False,
        'historical_applicability_established':False,'correction_relationship_established':False}
