"""C18 original-claim closure and SAM prior-ID audit; no new network adapter."""
import argparse
from html import escape
from pathlib import Path

from .parent_authority_reporting import report as c17_report, paths as prior_paths, clean as prior_clean
from .parent_authority_acquisition import plan,collect,usable
from .authority_binding import c14_case
from .correction_reporting import report as c14_report
from .source_verification import inspect_experiment
from .parent_history_probe import read as read_parent
from .history_preflight import monetary_preflight
from .sam_revision_authority import replay as sam_replay,compare_reference
from .evidence_package import verified_directory,_recipe
from .evidence_io import EvidenceError,EvidenceRoot,canonical,digest,strict_json
from .award_validation import snapshot
from .pilot_store import PilotStore
from .review_packet_io import outside

EXTRA=('action_parent_capture','action_parent_history')


def clean(case):return {k:v for k,v in case.items() if k not in EXTRA}


def fallback(case):
    c=clean(case)
    if c.get('new_parent_capture') or c.get('new_parent_history'):
        raise EvidenceError('C18_target_cannot_rebind_prior_C17_capture')
    return {**c,'new_parent_capture':case.get(EXTRA[0]),'new_parent_history':case.get(EXTRA[1])}


def paths(case):return prior_paths(clean(case))+[case[k] for k in EXTRA if case.get(k) and Path(case[k]).exists()]


def bounded(cases):
    if type(cases) not in (list,tuple) or not 1<=len(cases)<=24 or any(type(c) is not dict for c in cases):
        raise EvidenceError('bounded_typed_C18_cases_required')
    if sum(bool(c.get(EXTRA[0])) for c in cases)>1:raise EvidenceError('one_C18_fallback_only')
    return cases


def report(cases,*,baseline_package,selected_action,sam_action_captures=()):
    cases=bounded(cases)
    if type(sam_action_captures) not in (tuple,list) or len(sam_action_captures)>2:raise EvidenceError('at_most_two_explicit_SAM_captures')
    before={p:{n:s.byte_sha256 for n,s in snapshot(p).items()} for c in cases for p in paths(c)}
    with verified_directory(baseline_package,expected_phase='C17') as (root,verified):
        _,prior,_=_recipe(root,'C17')
        base=c17_report([clean(c) for c in cases],baseline_package=prior,selected_action=selected_action)
        if base['profile']!=verified['profile']:raise EvidenceError('C18_baseline_profile_conflict')
        original=base['baseline']['baseline']['baseline']['cases']
        selected=[]
        for binding in verified['verified_case_bindings']:
            matches=[i for i,c in enumerate(original) if c['original_case_sha256']==binding['original_case_sha256']
                and (None if c['parent_probe'] is None else c['parent_probe']['inventory_sha256'])==binding['parent_inventory_sha256']]
            if len(matches)!=1:raise EvidenceError('C18_original_C17_case_binding_conflict')
            selected.append(clean(cases[matches[0]]))
        if digest(c17_report(selected,baseline_package=prior,selected_action=selected_action))!=verified['report_sha256']:
            raise EvidenceError('C18_preserved_primary_replay_disagreement')
        sam=[]
        # The original selected tuple is an explicit SAM query selection, not an
        # admitted namespace crosswalk or identity/revision certificate.
        expected=base['historical_parent_assessment']['selected_native_action']
        for capture in sam_action_captures:
            value=sam_replay(capture)
            if value['profile']!=base['profile']:raise EvidenceError('C18_SAM_profile_conflict')
            value=compare_reference(value,expected,base['historical_parent_assessment']['source_specific_parent_modification_assertions'])
            sam.append(value)
        results=[];new=set()
        for index,(case,old) in enumerate(zip(cases,original)):
            source,parent,impacts,money=None,None,[],None
            if case.get(EXTRA[1]) and not case.get(EXTRA[0]):raise EvidenceError('parent_actions_require_new_child_anchor')
            if case.get(EXTRA[0]):
                target=fallback(case);planned=plan(target,live=base['profile']=='live')
                if planned['original_requirement_id'] not in base['remaining_original_plan_ids']:
                    raise EvidenceError('C18_target_must_be_original_unresolved_requirement')
                source=inspect_experiment(case[EXTRA[0]])
                if source['experiment']!=planned['experiment']:raise EvidenceError('C18_original_plan_or_budget_conflict')
                if usable(source) and case.get(EXTRA[1]) and Path(case[EXTRA[1]]).exists():
                    parent=read_parent(case[EXTRA[1]],case[EXTRA[0]])
                    if parent['capture_contract_version']!=2:raise EvidenceError('C18_parent_capture_v2_required')
                    augmented={**c14_case(prior_clean(clean(case))),'c12_capture':case[EXTRA[0]],'parent_history':case[EXTRA[1]]}
                    enhanced=c14_report([augmented])['cases'][0]
                    if enhanced['original_case_sha256']!=old['original_case_sha256']:raise EvidenceError('C18_original_case_changed')
                    for p in enhanced['original_requirement_impacts']:
                        if p['original_requirement_resolved']:
                            if (p['original_plan_id']!=planned['original_requirement_id'] or p['dimension']!='parent_identity'
                                or p['native_context']['namespace']!='usaspending' or p['original_requirement']!=planned['original_requirement']):
                                raise EvidenceError('unsupported_C18_qualification_expansion')
                            new.add(p['original_plan_id']);impacts.append(p)
                    money=monetary_preflight(enhanced,augmented,None)
            results.append({'case_index':index,'original_case_sha256':old['original_case_sha256'],
                'child_parent_capture':source,'parent_probe':parent,'resolved_original_impacts':impacts,
                'financial_preflight':money,'financial_comparison_authorized':False})
    for p,h in before.items():
        if {n:s.byte_sha256 for n,s in snapshot(p).items()}!=h:raise EvidenceError('C18_primary_inputs_changed')
    value={'schema_type':'ActionAuthorityReport','schema_version':1,'profile':base['profile'],'selected_action':selected_action,
        'baseline':base,'baseline_report_sha256':digest(base),'baseline_original_plan_ids':base['baseline_original_plan_ids'],
        'evidence_package_verification':verified,'cases':results,
        'sam_primary_assessments':sam,'SAM_primary_observations_obtained':sum(a['observed_record_occurrences'] for a in sam),
        'SAM_primary_status':'OBSERVED_NOT_HISTORICAL_AUTHORITY' if any(a['observed_record_occurrences'] for a in sam) else 'NO_PRIMARY_CAPTURE_OFFLINE_REPLAY_MAKES_NO_AUTHORIZATION_CLAIM',
        'previously_resolved_real_source_requirements':sorted(base['previously_resolved_real_source_requirements']+base['newly_resolved_real_source_requirements']),
        'previously_resolved_synthetic_requirements':sorted(base['previously_resolved_synthetic_requirements']+base['newly_resolved_synthetic_requirements']),
        'newly_resolved_real_source_requirements':sorted(new) if base['profile']=='live' else [],
        'newly_resolved_synthetic_requirements':sorted(new) if base['profile']=='synthetic' else [],
        'remaining_original_plan_ids':sorted(set(base['remaining_original_plan_ids'])-new),
        'real_source_partial_subproofs':[{'json_pointer':'/baseline/historical_parent_assessment','evidence_class':'PRESERVED_SOURCE_REPLAY','applicability_verified':False}] if base['profile']=='live' else [],
        'synthetic_only_results':sam if base['profile']=='synthetic' else [],
        'source_observations':{'capture_request_attempts':sum((c['child_parent_capture']['request_attempts'] if c['child_parent_capture'] else 0)+(c['parent_probe']['request_attempts'] if c['parent_probe'] else 0) for c in results),
            'new_parent_native_record_ids':sorted({r['row']['id'] for c in results if c['parent_probe'] and not c['parent_probe']['record_reassessment']['failures'] for r in c['parent_probe']['record_reassessment']['records']}),
            'replay_makes_new_requests':False,'repeated_records_are_independent_corroboration':False},
        'historical_parent_applicability_intervals_established':0,'authoritative_real_source_correction_edges':0,
        'financial_comparison_authorized':False,'financial_eligibility_changed':False,'production_readiness_changed':False,
        'limitations':['no_validated_historical_parent_effective_rule','old_identifier_context_is_not_a_verified_alias_or_directed_correction',
            'no_complete_historical_deletion_archive_or_common_asof_certificate','all_existing_financial_gates_remain_required']}
    if len(canonical(value).encode())>24*1024*1024:raise EvidenceError('C18_report_limit')
    return value


def projections(value):
    md='# Primary action and revision authority v1\n\nPreviously resolved real: '+str(len(value['previously_resolved_real_source_requirements']))+'\nNew real resolutions: '+str(len(value['newly_resolved_real_source_requirements']))+'\nRemaining: '+str(len(value['remaining_original_plan_ids']))+'\nNo historical applicability, correction or financial authorization.\n\n```json\n'+canonical(value).replace('`','\\u0060')+'\n```\n'
    html='<!doctype html><html lang="en"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; base-uri \'none\'"><title>Primary action authority</title><pre>'+escape(md)+'</pre></html>\n'
    return {'action-authority.json':(canonical(value)+'\n').encode(),'action-authority.md':md.encode(),'action-authority.html':html.encode()}


def _plan():return {'schema_type':'ActionAuthorityReportPlan','schema_version':1,'config':{'max_run_bytes':128*1024*1024}}


def write_report(path,cases,*,baseline_package,selected_action,sam_action_captures=()):
    outside(path,[p for c in bounded(cases) for p in paths(c)]+[baseline_package]+list(sam_action_captures))
    value=report(cases,baseline_package=baseline_package,selected_action=selected_action,sam_action_captures=sam_action_captures)
    raw=projections(value)
    if any(len(v)>32*1024*1024 for v in raw.values()) or sum(map(len,raw.values()))>96*1024*1024:raise EvidenceError('C18_projection_limit')
    with PilotStore(path,_plan()) as store:
        for n,b in raw.items():store.write_bytes(n,b)
        store.write('action-authority-commit.json',{'schema_version':1,'files':store.inventory(),'report_sha256':digest(value)})
    return digest(value)


def verify_report(path,cases,*,baseline_package,selected_action,sam_action_captures=()):
    with EvidenceRoot(path,max_bytes=32*1024*1024,max_total_bytes=128*1024*1024,max_files=5) as root:
        saved={n:root.read(n) for n in root.discover()}
        if {n:root.read(n,recheck=True).byte_sha256 for n in root.discover()}!={n:s.byte_sha256 for n,s in saved.items()}:raise EvidenceError('C18_report_changed')
    value=report(cases,baseline_package=baseline_package,selected_action=selected_action,sam_action_captures=sam_action_captures);raw=projections(value)
    commit={'schema_version':1,'files':{n:s.byte_sha256 for n,s in saved.items() if n!='action-authority-commit.json'},'report_sha256':digest(value)}
    if (set(saved)!={*raw,'pilot-plan.json','action-authority-commit.json'} or saved['pilot-plan.json'].data!=(canonical(_plan())+'\n').encode()
        or saved['action-authority-commit.json'].data!=(canonical(commit)+'\n').encode() or any(saved[n].data!=b for n,b in raw.items())):
        raise EvidenceError('C18_report_primary_replay_conflict')
    return value


def main(argv=None):
    p=argparse.ArgumentParser(description='C18 offline primary-action audit; explicit bounded USA fallback only.')
    p.add_argument('--cases',required=True);p.add_argument('--baseline-package',required=True);p.add_argument('--selected-action',required=True)
    p.add_argument('--sam-action-capture',action='append',default=[])
    mode=p.add_mutually_exclusive_group(required=True);mode.add_argument('--output');mode.add_argument('--verify-report');mode.add_argument('--plan-fallback',action='store_true')
    p.add_argument('--capture-fallback',action='store_true');p.add_argument('--live',action='store_true');p.add_argument('--journal')
    a=p.parse_args(argv)
    try:
        def load(path):
            f=Path(path).absolute()
            with EvidenceRoot(f.parent) as root:return strict_json(root.read(f.name).data)
        cases=bounded(load(a.cases));selected=load(a.selected_action)
        if a.live!=a.capture_fallback or (a.plan_fallback or a.verify_report) and a.capture_fallback:raise EvidenceError('explicit_nonconflicting_C18_flags_required')
        if a.plan_fallback or a.capture_fallback:
            targets=[c for c in cases if c.get(EXTRA[0])]
            if len(targets)!=1:raise EvidenceError('one_original_C18_fallback_required')
            target=fallback(targets[0])
            if a.plan_fallback:print(canonical(plan(target)));return 0
            if not a.journal:raise EvidenceError('separate_C18_journal_required')
            report([clean(c) for c in cases],baseline_package=a.baseline_package,selected_action=selected,sam_action_captures=a.sam_action_capture)
            protected=[a.cases,a.selected_action,a.baseline_package]+a.sam_action_capture+[p for c in cases for p in paths(clean(c))]
            for path in (a.journal,target['new_parent_capture'],target['new_parent_history'],a.output):outside(path,protected)
            outside(a.output,[a.journal,target['new_parent_capture'],target['new_parent_history']])
            collect(a.journal,target,live=True)
        kwargs={'baseline_package':a.baseline_package,'selected_action':selected,'sam_action_captures':a.sam_action_capture}
        if a.verify_report:value=verify_report(a.verify_report,cases,**kwargs)
        else:
            outside(a.output,[a.cases,a.selected_action]);write_report(a.output,cases,**kwargs);value=verify_report(a.output,cases,**kwargs)
        print(canonical({'report_sha256':digest(value),'new_real':len(value['newly_resolved_real_source_requirements']),'remaining':len(value['remaining_original_plan_ids']),'financial_comparison_authorized':False}));return 0
    except (ValueError,OSError,KeyError,TypeError,IndexError):
        print(canonical({'error_code':'action_authority_failed_preserve_evidence'}));return 2


if __name__=='__main__':raise SystemExit(main())
