"""Offline history evaluation of frozen pilot slots; never recollect or rewrite."""
import argparse
from pathlib import Path

from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, parts, strict_json
from .evidence_ingestion import inspect_directory
from .history_evidence import write_history
from .history_ingestion import reconstruct
from .history_reporting import bounded_json, metrics
from .identity_matching import decode_usa_id
from .review_packet_io import atomic_create, new_directory, outside
from .scope_models import ScopeRequest


def native_request(path,plan):
    a=plan['awards'][0]
    if a['piid'] is not None and a['agency_id'] is not None:
        return ScopeRequest(piid=a['piid'],agency=a['agency_id'],parent_piid=a['parent_piid'],parent_agency=a['parent_agency_id'])
    scan=inspect_directory(path);contexts=set()
    for entry in scan.entries:
        observation=entry.observation
        if observation is None or observation.artifact.source!='usaspending': continue
        for row in observation.records:
            for native in row.identifiers:
                if native.namespace!='id': continue
                fields,issues=decode_usa_id(native.value)
                if not issues:
                    context=tuple(fields[k].value for k in ('piid','agency','parent_piid','parent_agency'))
                    if context[0] is not None and context[1] is not None: contexts.add(context)
    if len(contexts)!=1: raise EvidenceError('pilot_native_context_unknown_or_ambiguous')
    piid,agency,parent,parent_agency=next(iter(contexts))
    if (parent is None)!=(parent_agency is None): parent=parent_agency=None
    return ScopeRequest(piid=piid,agency=agency,parent_piid=parent,parent_agency=parent_agency)


def evaluate_pilot(source,destination):
    source=Path(source).absolute();target=outside(destination,(source,))
    with EvidenceRoot(source,max_total_bytes=256*1024*1024,max_files=20000) as original:
        inventory={n:original.read(n).byte_sha256 for n in original.discover()}
        sample=strict_json(original.read('sample.json').data)
        plan=strict_json(original.read('pilot-plan.json').data)
        if sample.get('version')!='pilot-v1' or not isinstance(sample.get('selected'),list) or not 1<=len(sample['selected'])<=30:
            raise EvidenceError('unsupported_history_pilot_sample')
        new_directory(target)
        with EvidenceRoot(target) as output:
            atomic_create(output.fd,'history-pilot-plan.json',bounded_json({'schema_type':'HistoricalPilotPlan','schema_version':1,
                'sample_sha256':digest(sample),'source_plan_sha256':digest(plan),'execution_mode':'offline_saved_evidence_only',
                'source_inventory_sha256':digest(inventory),'baseline_metrics':'unchanged_separate_reports'}))
        slots=[]
        for index,selected in enumerate(sample['selected']):
            name=f'award-{index:03d}'
            research=strict_json(original.read(name+'/research/research-plan.json').data)
            if len(research['sources'])!=1: raise EvidenceError('unsupported_pilot_source_count')
            descriptor=research['sources'][0]
            if descriptor['managed']:
                collection=source/name/'research'/Path(*parts(descriptor['path']))
            else:
                collection=Path(descriptor['path'])
                if collection!=source/name/'discovery': raise EvidenceError('unsupported_external_pilot_source')
            with EvidenceRoot(collection) as c: cp=strict_json(c.read('c3_plan.json').data)
            if len(cp['awards'])!=1 or cp['awards'][0]['generated_id']!=selected['generated_id']:
                raise EvidenceError('pilot_history_frozen_selection_conflict')
            try:
                requested=native_request(collection,cp)
                run=reconstruct((collection,),requested)
                report_digest=write_history(target/f'slot-{index:03d}',run,protected=(source,))
                slots.append({'slot':index,'status':'evaluated','metrics':metrics(run),'run_digest':run.substantive_sha256,'report_digest':report_digest})
            except (ValueError,TypeError,KeyError,IndexError):
                # An unprocessable slot remains in the denominator, never a
                # zero-action or successful-verification observation.
                slots.append({'slot':index,'status':'unavailable_or_unsupported_evidence','metrics':None})
        available=[s['metrics'] for s in slots if s['metrics'] is not None]
        counters=('awards_with_eligible_observed_actions','distinct_eligible_action_identities','distinct_eligible_modifications',
            'returned_record_occurrences','duplicate_record_occurrences','declared_update_states','authorized_numeric_comparisons',
            'revision_uncertainty_withheld','scope_uncertainty_withheld','content_freshness_known','content_freshness_unknown',
            'historical_completeness_known','historical_completeness_unknown','unusable_source_artifacts')
        aggregate={k:sum(m[k] for m in available) for k in counters}
        aggregate.update({'slot_denominator':len(slots),'evaluated_slots':len(available),'unevaluated_slots':len(slots)-len(available),
            'enumerated_occurrence_count_complete':len(available)==len(slots) and all(m['enumerated_occurrence_count_complete'] for m in available),
            'action_count_unit':'sum_of_distinct_eligible_native_keys_per_frozen_slot_not_global_unique_actions',
            'financial_result_pair_denominator':sum(m['financial_comparison_denominator'] for m in available),
            'financial_results':{k:sum(m['financial_results'][k] for m in available) for k in available[0]['financial_results']} if available else {}})
        if {n:original.read(n,recheck=True).byte_sha256 for n in original.discover()}!=inventory:
            raise EvidenceError('original_pilot_evidence_changed')
        result={'schema_type':'HistoricalPilotEvaluation','schema_version':1,'version':'history-pilot-v1','sample_sha256':digest(sample),
            'source_inventory_sha256':digest(inventory),'metrics':aggregate,'slots':slots,'http_requests':0,'baseline_metrics':'unchanged_separate_reports'}
        with EvidenceRoot(target,max_total_bytes=128*1024*1024,max_files=2000) as output:
            atomic_create(output.fd,'history-pilot.json',bounded_json({'report':result,'substantive_sha256':digest(result)}))
            atomic_create(output.fd,'history-pilot.txt',('Historical frozen-pilot evaluation; all source history/freshness remain unknown.\n'+canonical(aggregate)+'\n').encode())
            files={n:output.read(n).byte_sha256 for n in output.discover()}
            atomic_create(output.fd,'history-pilot-commit.json',bounded_json({'schema_type':'HistoricalPilotCommit','schema_version':1,'files':files}))
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description='Offline frozen-pilot histories; no network fallback.')
    p.add_argument('--root',required=True);p.add_argument('--run-dir',required=True);a=p.parse_args(argv)
    try:
        report=evaluate_pilot(a.root,a.run_dir)
        print(canonical({'substantive_sha256':digest(report),'metrics':report['metrics'],'exit_code':1}));return 1
    except KeyboardInterrupt: return 130
    except (ValueError,TypeError,KeyError,IndexError,OSError):
        print(canonical({'error_code':'history_pilot_failed','exit_code':2}));return 2


if __name__=='__main__': raise SystemExit(main())
