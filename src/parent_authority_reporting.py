"""C17 offline historical parent audit and unchanged original-claim qualification."""
import argparse
from html import escape
from pathlib import Path

from .authority_reporting import report as c16_report
from .authority_binding import c14_case, parent_sources, PARENT_DOCUMENTATION
from .parent_modification_authority import assess
from .parent_authority_acquisition import plan, collect, usable
from .correction_reporting import report as c14_report, _paths as c14_paths
from .evidence_package import verified_directory, _recipe
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json
from .award_validation import snapshot
from .parent_history_probe import read as read_parent
from .source_verification import inspect_experiment
from .history_preflight import monetary_preflight
from .pilot_store import PilotStore
from .review_packet_io import outside


def clean(case):
    return {k:v for k,v in case.items() if k not in ('new_parent_capture','new_parent_history')}


def paths(case):
    c=clean(case)
    return c14_paths(c14_case(c))+([c['continuation']] if c.get('continuation') else [])+([c['authority_binding']] if c.get('authority_binding') else [])+[case[k] for k in ('new_parent_capture','new_parent_history') if case.get(k) and Path(case[k]).exists()]


def report(cases,*,baseline_package,selected_action):
    if type(cases) not in (list,tuple) or not 1<=len(cases)<=24 or any(type(c) is not dict for c in cases) or sum(bool(c.get('new_parent_capture')) for c in cases)>1:
        raise EvidenceError('bounded_C17_cases_one_fallback_required')
    if type(selected_action) is not dict or set(selected_action)!={'original_case_sha256','modification','transaction'}:
        raise EvidenceError('one_exact_original_action_selection_required')
    before={p:{n:s.byte_sha256 for n,s in snapshot(p).items()} for c in cases for p in paths(c)}
    with verified_directory(baseline_package,expected_phase='C16') as (root,verified):
        packaged,prior,_=_recipe(root,'C16')
        base=c16_report([clean(c) for c in cases],baseline_package=prior)
        chosen=[]
        for binding in verified['verified_case_bindings']:
            matches=[i for i,c in enumerate(base['baseline']['baseline']['cases']) if c['original_case_sha256']==binding['original_case_sha256']
                and (None if c['parent_probe'] is None else c['parent_probe']['inventory_sha256'])==binding['parent_inventory_sha256']]
            if len(matches)!=1:raise EvidenceError('C17_original_baseline_case_binding_conflict')
            chosen.append(clean(cases[matches[0]]))
        if digest(c16_report(chosen,baseline_package=prior))!=verified['report_sha256']:
            raise EvidenceError('C17_preserved_C16_primary_replay_conflict')
        with verified_directory(prior,expected_phase='C15') as (parent_root,parent_verified):
            sources=parent_sources(parent_root,parent_verified)
        selected=[(c,old) for c,old in zip(cases,base['baseline']['baseline']['cases']) if old['original_case_sha256']==selected_action['original_case_sha256']]
        if len(selected)!=1:raise EvidenceError('selected_original_action_not_unique')
        c,old=selected[0]
        scope=c['scope']
        source=[s for s in sources if (s['parent_piid'],s['parent_identity_agency'])==(scope['parent_piid'],scope['parent_agency'])]
        if len(source)!=1:raise EvidenceError('one_preserved_parent_context_required')
        historical=assess(clean(c),source[0]['record_observations'],modification=selected_action['modification'],transaction=selected_action['transaction'])
        results=[];new=set()
        for i,(case,original) in enumerate(zip(cases,base['baseline']['baseline']['cases'])):
            observation,parent,enhanced=None,None,None
            if case.get('new_parent_history') and not case.get('new_parent_capture'):
                raise EvidenceError('new_parent_requires_separate_child_anchor')
            if case.get('new_parent_capture'):
                planned=plan(case,live=base['profile']=='live')
                if planned['original_requirement_id'] not in base['remaining_original_plan_ids']:
                    raise EvidenceError('fallback_must_be_original_unresolved_C16_requirement')
                observation=inspect_experiment(case['new_parent_capture'])
                if observation['experiment']!=planned['experiment']:
                    raise EvidenceError('fallback_capture_not_bound_to_original_request_plan')
                if usable(observation) and case.get('new_parent_history') and Path(case['new_parent_history']).exists():
                    parent=read_parent(case['new_parent_history'],case['new_parent_capture'])
                    if parent['capture_contract_version']!=2:raise EvidenceError('C17_new_parent_capture_contract_v2_required')
                    augmented={**c14_case(clean(case)),'c12_capture':case['new_parent_capture'],'parent_history':case['new_parent_history']}
                    enhanced=c14_report([augmented])['cases'][0]
                    if enhanced['original_case_sha256']!=original['original_case_sha256']:
                        raise EvidenceError('fallback_original_identity_changed')
                    for p in enhanced['original_requirement_impacts']:
                        if p['original_requirement_resolved']:
                            if (p['original_plan_id']!=planned['original_requirement_id'] or p['dimension']!='parent_identity'
                                or p['native_context']['namespace']!='usaspending' or p['original_requirement']!=planned['original_requirement']):
                                raise EvidenceError('unsupported_C17_resolution_expansion')
                            new.add(p['original_plan_id'])
            results.append({'case_index':i,'original_case_sha256':original['original_case_sha256'],
                'child_parent_capture':observation,'new_parent_probe':parent,
                'fallback_requirement_impacts':None if enhanced is None else enhanced['original_requirement_impacts'],
                'monetary_compatibility':None if enhanced is None else monetary_preflight(enhanced,augmented,None),
                'financial_comparison_authorized':False})
    for p,expected in before.items():
        if {n:s.byte_sha256 for n,s in snapshot(p).items()}!=expected:raise EvidenceError('C17_primary_changed')
    real=sorted(new) if base['profile']=='live' else []
    synth=sorted(new) if base['profile']=='synthetic' else []
    prior_real=sorted(base['previously_resolved_real_source_requirements']+base['newly_resolved_real_source_requirements'])
    prior_synth=sorted(base['previously_resolved_synthetic_requirements']+base['newly_resolved_synthetic_requirements'])
    value={'schema_type':'HistoricalParentAuthorityReport','schema_version':1,'profile':base['profile'],
        'selected_action':selected_action,'source_documentation':[PARENT_DOCUMENTATION,
            {'source':'samgov','url':'https://open.gsa.gov/api/contract-awards/', 'body_sha256':'033a7007b702d25f1582f06feb8c0dd5d6dce3afee056cb57b61995e0e7443c7',
             'documented_fields':['contractId.referencedIDVModificationNumber','oldContractId','deletedStatus'], 'selected_primary_behavior':'UNVERIFIED'},
            {'source':'fpds','url':'https://www.fpds.gov/help/Correct_a_Transaction.htm','body_sha256':'a0cf18db18c4490dab34d362f7797da6db016b05084bc379358d755a4891c5a9','documented_capability':'final_record_correction_workflow_not_retained_predecessor_archive'},
            {'source':'usaspending','url':'https://raw.githubusercontent.com/fedspendingtransparency/usaspending-api/c2b82690eb044e130afc80b546343a2af0b4af1a/usaspending_api/api_contracts/contracts/v2/transactions.md','body_sha256':'76a50f3445670d8ee5488770d6583a7f6399a093a903dabfbab77344f1eba078','claim_scope':'finite_transaction_query_not_source_recall_or_historical_asof'}],
        'baseline':base,'baseline_report_sha256':digest(base),
        'baseline_original_plan_ids':base['baseline_original_plan_ids'],'evidence_package_verification':verified,
        'historical_parent_assessment':historical,'cases':results,
        'previously_resolved_real_source_requirements':prior_real,'previously_resolved_synthetic_requirements':prior_synth,
        'newly_resolved_real_source_requirements':real,'newly_resolved_synthetic_requirements':synth,
        'remaining_original_plan_ids':sorted(set(base['remaining_original_plan_ids'])-new),
        'real_source_partial_subproofs':[historical] if base['profile']=='live' else [],
        'synthetic_only_subproofs':[historical] if base['profile']=='synthetic' else [],
        'historical_parent_applicability_intervals_established':0,'authoritative_real_source_correction_edges':0,
        'financial_comparison_authorized':False,'production_readiness_changed':False,
        'source_observations':{'capture_request_attempts':sum((c['child_parent_capture']['request_attempts'] if c['child_parent_capture'] else 0)+(c['new_parent_probe']['request_attempts'] if c['new_parent_probe'] else 0) for c in results),
            'validated_distinct_parent_action_ids':sorted({r['row']['id'] for c in results if c['new_parent_probe'] and not c['new_parent_probe']['record_reassessment']['failures'] for r in c['new_parent_probe']['record_reassessment']['records']}),
            'replay_makes_new_requests':False,'repeated_observations_are_independent_corroboration':False},
        'source_access':{'samgov':'NOT_ACCESSED_REQUIRES_EXISTING_AUTHORIZATION_NOT_READ_DURING_OFFLINE_REPLAY',
            'usaspending':'EXPLICIT_BOUNDED_OPT_IN_OR_OFFLINE_REPLAY'},
        'evidence_classes':{'historical_assessment':'PRESERVED_SOURCE_REPLAY','fallback':'REAL_SOURCE_OBSERVATION' if base['profile']=='live' else 'SYNTHETIC_FIXTURE',
            'historical_effective_rule':'UNVERIFIED_ASSUMPTION'}}
    if len(canonical(value).encode())>20*1024*1024:raise EvidenceError('C17_report_size_limit')
    return value


def projections(value):
    md='# Historical parent modification authority v1\n\nPreviously resolved real: '+str(len(value['previously_resolved_real_source_requirements']))+'\nNewly resolved real: '+str(len(value['newly_resolved_real_source_requirements']))+'\nRemaining: '+str(len(value['remaining_original_plan_ids']))+'\nHistorical applicability and correction authority remain unresolved. No financial authorization.\n\n```json\n'+canonical(value).replace('`','\\u0060')+'\n```\n'
    html='<!doctype html><html lang="en"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; base-uri \'none\'"><title>Parent authority</title><pre>'+escape(md)+'</pre></html>\n'
    return {'parent-authority.json':(canonical(value)+'\n').encode(),'parent-authority.md':md.encode(),'parent-authority.html':html.encode()}


def _plan():return {'schema_type':'ParentAuthorityReportPlan','schema_version':1,'config':{'max_run_bytes':128*1024*1024}}


def write_report(path,cases,*,baseline_package,selected_action):
    outside(path,[p for c in cases for p in paths(c)]+[baseline_package])
    value=report(cases,baseline_package=baseline_package,selected_action=selected_action)
    raw=projections(value)
    if any(len(b)>32*1024*1024 for b in raw.values()) or sum(map(len,raw.values()))>96*1024*1024:raise EvidenceError('C17_projection_limit')
    with PilotStore(path,_plan()) as store:
        for n,b in raw.items():store.write_bytes(n,b)
        store.write('parent-authority-commit.json',{'schema_version':1,'files':store.inventory(),'report_sha256':digest(value)})
    return digest(value)


def verify_report(path,cases,*,baseline_package,selected_action):
    with EvidenceRoot(path,max_bytes=32*1024*1024,max_total_bytes=128*1024*1024,max_files=5) as root:
        saved={n:root.read(n) for n in root.discover()}
        if {n:root.read(n,recheck=True).byte_sha256 for n in root.discover()}!={n:s.byte_sha256 for n,s in saved.items()}:raise EvidenceError('C17_report_changed')
    value=report(cases,baseline_package=baseline_package,selected_action=selected_action);raw=projections(value)
    commit={'schema_version':1,'files':{n:s.byte_sha256 for n,s in saved.items() if n!='parent-authority-commit.json'},'report_sha256':digest(value)}
    if (set(saved)!={*raw,'pilot-plan.json','parent-authority-commit.json'} or saved['pilot-plan.json'].data!=(canonical(_plan())+'\n').encode()
        or saved['parent-authority-commit.json'].data!=(canonical(commit)+'\n').encode() or any(saved[n].data!=b for n,b in raw.items())):
        raise EvidenceError('C17_report_primary_replay_conflict')
    return value


def main(argv=None):
    p=argparse.ArgumentParser(description='C17 offline parent authority; explicit bounded public fallback only.')
    p.add_argument('--cases',required=True);p.add_argument('--baseline-package',required=True);p.add_argument('--selected-action',required=True)
    m=p.add_mutually_exclusive_group(required=True);m.add_argument('--output');m.add_argument('--verify-report');m.add_argument('--plan-fallback',action='store_true')
    p.add_argument('--capture-fallback',action='store_true');p.add_argument('--live',action='store_true');p.add_argument('--journal')
    a=p.parse_args(argv)
    try:
        def load(path):
            file=Path(path).absolute()
            with EvidenceRoot(file.parent) as root:return strict_json(root.read(file.name).data)
        cases=load(a.cases);selection=load(a.selected_action)
        if type(cases) not in (list,tuple) or not 1<=len(cases)<=24 or any(type(c) is not dict for c in cases):
            raise EvidenceError('bounded_typed_C17_cases_required')
        if a.live!=a.capture_fallback or (a.plan_fallback or a.verify_report) and a.capture_fallback:raise EvidenceError('explicit_nonconflicting_C17_flags_required')
        if a.plan_fallback or a.capture_fallback:
            targets=[c for c in cases if c.get('new_parent_capture')]
            if len(targets)!=1:raise EvidenceError('one_fallback_target_required')
            if a.plan_fallback:print(canonical(plan(targets[0],live=False)));return 0
            if not a.journal:raise EvidenceError('separate_acquisition_journal_required')
            report([clean(c) for c in cases],baseline_package=a.baseline_package,selected_action=selection)
            for path in (a.journal,targets[0]['new_parent_capture'],targets[0]['new_parent_history'],a.output):
                outside(path,[a.cases,a.selected_action,a.baseline_package]+[p for c in cases for p in paths(clean(c))])
            outside(a.output,[a.journal,targets[0]['new_parent_capture'],targets[0]['new_parent_history']])
            collect(a.journal,targets[0],live=True)
        if a.verify_report:value=verify_report(a.verify_report,cases,baseline_package=a.baseline_package,selected_action=selection)
        else:
            outside(a.output,[a.cases,a.selected_action]);write_report(a.output,cases,baseline_package=a.baseline_package,selected_action=selection)
            value=verify_report(a.output,cases,baseline_package=a.baseline_package,selected_action=selection)
        print(canonical({'report_sha256':digest(value),'new_real':len(value['newly_resolved_real_source_requirements']),
            'remaining':len(value['remaining_original_plan_ids']),'financial_comparison_authorized':False}));return 0
    except (ValueError,OSError,KeyError,TypeError,IndexError):
        print(canonical({'error_code':'parent_authority_failed_preserve_evidence'}));return 2


if __name__=='__main__':raise SystemExit(main())
