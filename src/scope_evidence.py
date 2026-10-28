"""Opt-in offline scope demonstration/evaluation; default C1-C7 behavior unchanged."""
import argparse
from dataclasses import replace

from .collect_evidence import load_input
from .collection import CollectionLimits, collect_selected
from .collection_sources import FixtureTransport
from .evidence_io import EvidenceError, canonical, digest
from .financial_ingestion import reconcile_collection
from .matching_ingestion import match_collection
from .pilot_store import PilotStore
from .research_demo import CASES, demo_case
from .scope_ingestion import assess_collection
from .scope_models import ScopeRequest,ScopeStatus


def evaluate(path,requested):
    scope=assess_collection(path,requested)
    scoped=match_collection(path,scope_request=requested)
    finance=reconcile_collection(path,scope_request=requested)
    baseline=None
    try: baseline=reconcile_collection(path)
    except (ValueError,TypeError,KeyError): pass
    from .identity_matching import key_for,ACTION_FIELDS
    from .scope_matrix import identity_matrix
    eligible_fpds={key_for(a.record,ACTION_FIELDS) for a in scope.assessments if a.record and a.record.source=='fpds' and a.status is ScopeStatus.IN_SCOPE}
    eligible_fpds.discard(None)
    subjects={a.record.record_id:a for a in scope.assessments if a.record and a.record.source=='usaspending'}
    withheld=sum(a.status is not ScopeStatus.IN_SCOPE or key_for(a.record,ACTION_FIELDS) is None or key_for(a.record,ACTION_FIELDS) not in eligible_fpds for a in subjects.values())
    metrics={**scope.metrics,'scoped_award_action_counts':scoped.counts,
        'scoped_financial_claims':len(finance.results),
        'scoped_numeric_comparisons':sum(d.difference_usa_minus_fpds is not None for d in finance.results),
        'scoped_financial_counts':finance.counts,
        'distinct_usa_subjects_withheld_by_scope':len({a.record.record_id for a in scope.assessments if a.record and a.record.source=='usaspending' and a.status is not ScopeStatus.IN_SCOPE}),
        'financial_action_contexts_withheld':withheld,
        'withheld_context_denominator':len(subjects),
        'baseline_financial_claims':len(baseline.results) if baseline else None,
        'baseline_numeric_comparisons':sum(d.difference_usa_minus_fpds is not None for d in baseline.results) if baseline else None,
        'baseline_financial_counts':baseline.counts if baseline else None}
    return {'scope':scope.to_dict(),'scope_digest':scope.substantive_sha256,'metrics':metrics,
        'identity':scoped.to_dict(),'financial':finance.to_dict(),'identity_matrix':identity_matrix(),
        'limitations':['scope_is_not_independent_source_corroboration','no_parent_absence_inferred','history_and_freshness_unknown','C6_and_C7_defaults_not_changed']}


def run_demo(path):
    cases=CASES+('out_of_scope','unsupported_record')
    plan={'schema_type':'ScopeDemoPlan','schema_version':1,'config':{'max_run_bytes':64*1024*1024},'cases':list(cases),'profile':'synthetic'}
    with PilotStore(path,plan) as store:
        results=[]
        for case in cases:
            a,fixture=demo_case(case if case in CASES else 'agreement')
            if case=='out_of_scope':
                fixture['responses'][-1]['text']=fixture['responses'][-1]['text'].replace('<f:PIID>'+a.piid+'</f:PIID>','<f:PIID>SYNTH-OTHER</f:PIID>')
            if case=='unsupported_record':
                fixture['responses'][-1]['text']=fixture['responses'][-1]['text'].replace('<f:agencyID>0001</f:agencyID>','<f:agencyID>0001</f:agencyID><f:agencyID>9999</f:agencyID>')
            root=store.path/case
            collect_selected(root,(a,),limits=CollectionLimits(max_awards=1,max_pages=2,max_records_per_source_award=40,max_records_total=100,retries=1,pace_seconds=0.0,backoff_seconds=0.0),
                transport=FixtureTransport(fixture),profile='fixture:'+digest(fixture),sleep=lambda _:None)
            request=ScopeRequest(piid=a.piid,agency=a.agency_id,parent_piid=a.parent_piid,parent_agency=a.parent_agency_id)
            results.append({'case':case,**evaluate(root,request)})
        from .scope_matrix import identity_matrix
        report={'schema_type':'ScopeDemonstration','schema_version':1,'profile':'synthetic','results':results,'identity_matrix':identity_matrix()}
        store.write('scope-report.json',{'report':report,'substantive_sha256':digest(report)})
        store.write_bytes('scope-summary.txt',('\n'.join([r['case']+': '+canonical(r['metrics']) for r in results])+'\nScope is a narrow identity assertion; no misconduct, history or freshness inference.\n').encode())
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description='Offline record-scope assessment and opt-in C4/C5 eligibility; no collection fallback.')
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--root');mode.add_argument('--sam-root');mode.add_argument('--demo',action='store_true')
    p.add_argument('--request');p.add_argument('--run-dir',required=True)
    args=p.parse_args(argv)
    try:
        if args.demo:
            if args.request: raise EvidenceError('demo_request_is_fixed')
            report=run_demo(args.run_dir)
        else:
            from .review_packet_io import outside
            source=args.root or args.sam_root
            target=outside(args.run_dir,(source,))
            if args.sam_root:
                if args.request: raise EvidenceError('sam_request_bound_by_capture')
                from .sam_contracts import assess_sam_directory
                scope=assess_sam_directory(source)
                report={'scope':scope.to_dict(),'metrics':scope.metrics,'sam_cross_source_matching':'not_implemented_no_automatic_crosswalk'}
            else:
                if not args.request: raise EvidenceError('explicit_native_scope_request_required')
                requested=ScopeRequest.from_dict(load_input(args.request))
                report=evaluate(source,requested)
            with PilotStore(target,{'schema_type':'ScopeEvaluationPlan','schema_version':1,'config':{'max_run_bytes':32*1024*1024}}) as store:
                store.write('scope-report.json',{'report':report,'substantive_sha256':digest(report)})
                store.write_bytes('scope-summary.txt',(canonical(report['metrics'])+'\nSaved source identity only; no history or misconduct inference.\n').encode())
        print(canonical({'substantive_sha256':digest(report),'exit_code':1}))
        return 1
    except KeyboardInterrupt: return 130
    except (ValueError,TypeError,KeyError,IndexError,OSError):
        print(canonical({'error_code':'scope_evaluation_failed','exit_code':2}));return 2


if __name__=='__main__': raise SystemExit(main())
