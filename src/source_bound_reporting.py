"""C20 source-bound progress and literal unresolved-dependency prioritization.

Network collection remains separate. All qualifying rules are the existing
C14/C16/C17 rules; documentation and triage never authorize financial work.
"""
import argparse
from html import escape
from pathlib import Path

from .historical_authority_reporting import original as c19_original, paths as c19_paths, ORIGINAL_IDS
from .parent_authority_acquisition import plan, usable
from .correction_reporting import report as c14_report
from .source_verification import inspect_experiment
from .parent_history_probe import read as read_parent
from .source_contracts import collection_contract
from .scope_models import ScopeRequest
from .source_reference_semantics import read_documents, reference_assessment
from .evidence_dependency_triage import assess_dependencies, PARENT
from .evidence_package import verified_directory, _recipe
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json
from .award_validation import snapshot
from .history_preflight import monetary_preflight
from .pilot_store import PilotStore
from .review_packet_io import outside

EXTRA = ('c20_parent_capture','c20_parent_history')
ROLES = ('collections','sam_captures','c12_capture','historical_probe','parent_history','continuation',
         'authority_binding','new_parent_capture','new_parent_history','action_parent_capture',
         'action_parent_history','c19_parent_capture','c19_parent_history')
LIVE_TARGETS = {
    'evidence-resolution:v1:624256863be3731784140bc2e42581337b07051f950a8938169989b4297dff61':
        ('4dba6cb285eb781f86a52da403928c42010f254a755d7a569a21894eabb850da','3fa8a82ec1010aaa208aff3eb873333a49d7d421cb715a296d600355a900c8e0'),
    'evidence-resolution:v1:2831ff526539c5f2b251bd8fa633ffa38f391f0f671c28efb5f4618e9335843f':
        ('dc22c95244441251bcad5c93accf9a30b63495bd90cd28750f2f686f3253f268','2e445d1c8076700b9e47bbe907173c21e9002d124ba9aaa67c2646650521e99f'),
}


def clean(case):return {k:v for k,v in case.items() if k not in EXTRA}
def original(case):return c19_original(clean(case))
def paths(case):return c19_paths(clean(case))+[case[k] for k in EXTRA if case.get(k) and Path(case[k]).exists()]
def inventory(path):return {n:s.byte_sha256 for n,s in snapshot(path).items()}


def bounded(cases):
    if (type(cases) not in (tuple,list) or not 1<=len(cases)<=24
            or any(type(c) is not dict for c in cases) or sum(bool(c.get(EXTRA[0])) for c in cases)>2):
        raise EvidenceError('bounded_unique_C20_original_cases_required')
    return cases


def fallback(case):
    if any(case.get(k) for k in ('new_parent_capture','new_parent_history','action_parent_capture',
                                 'action_parent_history','c19_parent_capture','c19_parent_history')):
        raise EvidenceError('C20_cannot_rebind_preserved_acquisition')
    return {**original(case),'new_parent_capture':case.get(EXTRA[0]),'new_parent_history':case.get(EXTRA[1])}


def _bind(root,verified,cases,originals):
    packaged,_,_=_recipe(root,'C19')
    if len(packaged)!=len(verified['verified_case_bindings']):
        raise EvidenceError('C20_baseline_binding_count_conflict')
    for saved,binding in zip(packaged,verified['verified_case_bindings']):
        matches=[i for i,c in enumerate(originals) if c['original_case_sha256']==binding['original_case_sha256']
            and (None if c['parent_probe'] is None else c['parent_probe']['inventory_sha256'])==binding['parent_inventory_sha256']]
        if len(matches)!=1:raise EvidenceError('C20_original_case_binding_conflict')
        for role in ROLES:
            expected,supplied=saved.get(role),cases[matches[0]].get(role)
            many=role in ('collections','sam_captures')
            expected=(expected or []) if many else [] if expected is None else [expected]
            supplied=(supplied or []) if many else [] if supplied is None else [supplied]
            if type(supplied) is not list or len(expected)!=len(supplied):
                raise EvidenceError('C20_preserved_evidence_role_changed')
            if any(inventory(a)!=inventory(b) for a,b in zip(expected,supplied)):
                raise EvidenceError('C20_preserved_evidence_inventory_changed')


def _candidates(cases,originals,remaining,profile):
    """Plans describe a supported route, never untested current accessibility."""
    result=[]
    for case,old in zip(cases,originals):
        eligible=[p for p in old['original_requirement_impacts'] if p['original_plan_id'] in remaining
            and p['dimension']=='parent_identity' and p['native_context']['namespace']=='usaspending'
            and p['original_requirement']['status']=='INSUFFICIENT_EVIDENCE'
            and p['original_requirement']['reasons']==[PARENT]]
        if not eligible:continue
        prepared=plan(original(case),live=profile=='live')
        roots=case.get('collections',[])
        if len(roots)!=1:raise EvidenceError('one_original_USA_query_context_required')
        contract=collection_contract(roots[0],requested=ScopeRequest.from_dict(case['scope']))
        histories=[h for h in contract['histories'] if h['source']=='usaspending']
        citations=[o['citation'] for h in histories for o in h['observations']]
        original_nodes=[n for n in old['observation_graph']['nodes'] if n['source']=='usaspending'
                        and strict_json(n['citation_json'].encode())['input_role']=='original_C10_primary']
        if not citations:citations=[strict_json(n['citation_json'].encode()) for n in original_nodes]
        result.append({'plan':prepared,'preserved_query_terminal':bool(histories) and all(
            h['source_contract_satisfied'] and h['pagination']['bounded_observed_chain']=='consistent_terminal' for h in histories),
            'preserved_record_occurrences':len(original_nodes),
            'preserved_query_citations':citations,'preserved_query_contract_issues':contract['failures']})
    return result


def report(cases,*,baseline_package,source_documents):
    cases=bounded(cases);before={p:inventory(p) for c in cases for p in paths(c)}
    documents=read_documents(source_documents)
    old=c14_report([original(c) for c in cases]);originals=old['cases'];profile=old['profile']
    case_ids=[c['original_case_sha256'] for c in originals]
    if len(set(case_ids))!=len(case_ids):raise EvidenceError('duplicate_C20_original_case')
    ids=sorted({p['original_plan_id'] for c in originals for p in c['original_requirement_impacts']})
    with verified_directory(baseline_package,expected_phase='C19') as (root,verified):
        with EvidenceRoot(Path(root)/'report',max_bytes=16*1048576) as reader:
            base=strict_json(reader.read('historical-authority.json').data)
        if verified['profile']!=profile:raise EvidenceError('C20_source_profile_conflict')
        _bind(root,verified,cases,originals)
        prior_real=sorted(base['previously_resolved_real_source_requirements']+base['newly_resolved_real_source_requirements'])
        prior_synth=sorted(base['previously_resolved_synthetic_requirements']+base['newly_resolved_synthetic_requirements'])
        prior=set(prior_real+prior_synth)
        if (len(prior)!=len(prior_real+prior_synth) or not prior<=set(ids)
                or not set(base['baseline_original_plan_ids'])<=set(ids)):
            raise EvidenceError('C20_preserved_requirement_partition_conflict')
        full=profile=='live' and len(cases)==24
        if profile=='live':
            if full:
                if len(ids)!=1570 or digest(ids)!=ORIGINAL_IDS:raise EvidenceError('C20_immutable_original_ID_set_changed')
            else:
                allowed={b['original_case_sha256'] for b in verified['verified_case_bindings']}|{v[0] for v in LIVE_TARGETS.values()}
                if not set(case_ids)<=allowed:raise EvidenceError('C20_unregistered_live_case')
        historical=reference_assessment(base['historical_authority_assessment'],documents,profile=profile)
    remaining=set(ids)-prior
    candidate_plans=_candidates(cases,originals,remaining,profile)
    results=[];new=set();access=[]
    for index,(case,previous) in enumerate(zip(cases,originals)):
        source=parent=money=None;impacts=[]
        if case.get(EXTRA[1]) and not case.get(EXTRA[0]):raise EvidenceError('C20_parent_requires_child_primary_anchor')
        if case.get(EXTRA[0]):
            target=fallback(case);prepared=plan(target,live=profile=='live');key=prepared['original_requirement_id']
            if key not in remaining:raise EvidenceError('C20_target_not_original_unresolved')
            if profile=='live' and LIVE_TARGETS.get(key)!=(prepared['original_case_sha256'],digest(prepared)):
                raise EvidenceError('C20_target_not_preregistered_plan')
            source=inspect_experiment(case[EXTRA[0]])
            if source['experiment']!=prepared['experiment']:raise EvidenceError('C20_capture_plan_conflict')
            if usable(source) and case.get(EXTRA[1]) and Path(case[EXTRA[1]]).exists():
                parent=read_parent(case[EXTRA[1]],case[EXTRA[0]])
                if parent['capture_contract_version']!=2:raise EvidenceError('C20_parent_contract_version_required')
                augmented={**original(case),'c12_capture':case[EXTRA[0]],'parent_history':case[EXTRA[1]]}
                enhanced=c14_report([augmented])['cases'][0]
                if enhanced['original_case_sha256']!=previous['original_case_sha256']:raise EvidenceError('C20_original_native_context_changed')
                for p in enhanced['original_requirement_impacts']:
                    if p['original_requirement_resolved']:
                        if (p['original_plan_id']!=key or p['dimension']!='parent_identity'
                                or p['native_context']['namespace']!='usaspending'
                                or p['original_requirement']!=prepared['original_requirement']):
                            raise EvidenceError('C20_unsupported_qualification_expansion')
                        new.add(key);impacts.append(p)
                money=monetary_preflight(enhanced,augmented,None)
                if (type(money['totals_or_deltas_computed']) is not int or money['totals_or_deltas_computed']!=0
                        or type(money['amount_comparisons_performed']) is not int or money['amount_comparisons_performed']!=0
                        or money['financial_comparison_authorized'] is not False):
                    raise EvidenceError('C20_financial_assessment_only_required')
            access.append({'original_plan_id':key,'source':'usaspending','profile':profile,
                'state':'EXACT_BOUNDED_PARENT_PRIMARY_TEST_SUCCEEDED' if impacts else 'FAILED_OR_INCONCLUSIVE_NO_ABSENCE_CLAIM',
                'child_capture_inventory_sha256':source['inventory_sha256'],
                'parent_capture_inventory_sha256':None if parent is None else parent['inventory_sha256'],
                'other_native_contexts_accessible':None,'historical_completeness':'unknown',
                'financial_comparison_authorized':False})
        results.append({'case_index':index,'original_case_sha256':previous['original_case_sha256'],
            'child_parent_capture':source,'parent_probe':parent,'resolved_original_impacts':impacts,
            'financial_preflight':money,'financial_comparison_authorized':False})
    triage=assess_dependencies(originals,sorted(remaining),candidates=candidate_plans,resolved_now=sorted(new))
    for path,expected in before.items():
        if inventory(path)!=expected:raise EvidenceError('C20_source_changed_during_replay')
    if read_documents(source_documents)!=documents:raise EvidenceError('C20_document_capture_changed')
    return {'schema_type':'SourceBoundEvidenceReport','schema_version':1,'profile':profile,
        'qualification_scope':'original_24_case_cohort' if full else 'included_cases_only',
        'baseline_original_plan_ids':ids,'baseline_report_sha256':verified['report_sha256'],
        'baseline_package_verification':verified,'original_case_bindings':[
            {'original_case_sha256':c['original_case_sha256'],'parent_inventory_sha256':None
             if c['parent_probe'] is None else c['parent_probe']['inventory_sha256']} for c in originals],
        'source_documentation':documents,'source_documentation_evidence_class':'REAL_PUBLIC_DOCUMENT_CAPTURE'
            if profile=='live' else 'SYNTHETIC_DOCUMENT_FIXTURE',
        'historical_authority_assessment':historical,'baseline_dependency_assessment':triage,
        'current_phase_access_observations':access,'cases':results,
        'previously_resolved_real_source_requirements':prior_real,
        'previously_resolved_synthetic_requirements':prior_synth,
        'newly_resolved_real_source_requirements':sorted(new) if profile=='live' else [],
        'newly_resolved_synthetic_requirements':sorted(new) if profile=='synthetic' else [],
        'remaining_original_plan_ids':sorted(remaining-new),
        'source_observations':{'capture_request_attempts':sum((c['child_parent_capture']['request_attempts']
            if c['child_parent_capture'] else 0)+(c['parent_probe']['request_attempts'] if c['parent_probe'] else 0) for c in results),
            'parent_native_record_ids':sorted({r['row']['id'] for c in results if c['parent_probe']
                and not c['parent_probe']['record_reassessment']['failures'] for r in c['parent_probe']['record_reassessment']['records']}),
            'replay_makes_new_requests':False,'repeated_records_are_independent_corroboration':False},
        'real_source_partial_subproofs':[historical] if profile=='live' else [],
        'synthetic_only_subproofs':[historical] if profile=='synthetic' else [],
        'historical_parent_applicability_intervals_established':0,'authoritative_real_source_correction_edges':0,
        'financial_comparison_authorized':False,'financial_eligibility_changed':False,'production_readiness_changed':False}


def projections(value):
    triage=value['baseline_dependency_assessment']
    md=('# Source-bound evidence v1\n\nScope: '+value['qualification_scope']+'\nPrior real: '
        +str(len(value['previously_resolved_real_source_requirements']))+'\nNew real: '
        +str(len(value['newly_resolved_real_source_requirements']))+'\nRemaining: '
        +str(len(value['remaining_original_plan_ids']))+'\nNo historical or financial authorization.\n\n'
        +'| Original missing dependency | Count |\n| --- | ---: |\n'
        +''.join('| '+k+' | '+str(v)+' |\n' for k,v in triage['exclusive_group_counts'].items())
        +'\nNOT_EVALUATED is not a source discrepancy. Prospective paths do not certify current access.\n\n```json\n'
        +canonical(value).replace('`','\\u0060')+'\n```\n')
    html=('<!doctype html><html lang="en"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" '
        +'content="default-src \'none\'; base-uri \'none\'"><title>Source-bound evidence</title><pre>'+escape(md)+'</pre></html>\n')
    return {'source-bound.json':(canonical(value)+'\n').encode(),'source-bound.md':md.encode(),'source-bound.html':html.encode()}


def _plan():return {'schema_type':'SourceBoundReportPlan','schema_version':1,'config':{'max_run_bytes':64*1048576}}


def write_report(path,cases,*,baseline_package,source_documents):
    outside(path,[p for c in bounded(cases) for p in paths(c)]+[baseline_package,source_documents])
    value=report(cases,baseline_package=baseline_package,source_documents=source_documents);raw=projections(value)
    if any(len(b)>16*1048576 for b in raw.values()):raise EvidenceError('C20_report_projection_limit')
    with PilotStore(path,_plan()) as store:
        for n,b in raw.items():store.write_bytes(n,b)
        store.write('source-bound-commit.json',{'schema_version':1,'files':store.inventory(),'report_sha256':digest(value)})
    return digest(value)


def verify_report(path,cases,*,baseline_package,source_documents):
    with EvidenceRoot(path,max_bytes=16*1048576,max_total_bytes=64*1048576,max_files=5) as reader:
        saved={n:reader.read(n) for n in reader.discover()}
        if any(reader.read(n,recheck=True).byte_sha256!=s.byte_sha256 for n,s in saved.items()):raise EvidenceError('C20_report_changed')
    value=report(cases,baseline_package=baseline_package,source_documents=source_documents);raw=projections(value)
    commit={'schema_version':1,'files':{n:s.byte_sha256 for n,s in saved.items() if n!='source-bound-commit.json'},'report_sha256':digest(value)}
    if (set(saved)!={*raw,'pilot-plan.json','source-bound-commit.json'}
            or saved['pilot-plan.json'].data!=(canonical(_plan())+'\n').encode()
            or saved['source-bound-commit.json'].data!=(canonical(commit)+'\n').encode()
            or any(saved[n].data!=b for n,b in raw.items())):
        raise EvidenceError('C20_report_not_recomputed_from_primary_inputs')
    return value


def main(argv=None):
    parser=argparse.ArgumentParser(description='Offline source-bound evidence and dependency triage; no credential or network reads.')
    parser.add_argument('--cases',required=True);parser.add_argument('--baseline-package',required=True)
    parser.add_argument('--source-documents',required=True)
    mode=parser.add_mutually_exclusive_group(required=True);mode.add_argument('--output');mode.add_argument('--verify-report')
    args=parser.parse_args(argv)
    try:
        file=Path(args.cases).absolute()
        with EvidenceRoot(file.parent) as reader:cases=bounded(strict_json(reader.read(file.name).data))
        kwargs={'baseline_package':args.baseline_package,'source_documents':args.source_documents}
        if args.verify_report:value=verify_report(args.verify_report,cases,**kwargs)
        else:
            outside(args.output,[args.cases]);write_report(args.output,cases,**kwargs)
            value=verify_report(args.output,cases,**kwargs)
        print(canonical({'report_sha256':digest(value),'new_real':len(value['newly_resolved_real_source_requirements']),
            'remaining':len(value['remaining_original_plan_ids']),'financial_authorized':False}));return 0
    except (ValueError,OSError,KeyError,TypeError,IndexError,AttributeError):
        print(canonical({'error_code':'source_bound_evidence_failed_preserve_inputs'}));return 2


if __name__=='__main__':raise SystemExit(main())
