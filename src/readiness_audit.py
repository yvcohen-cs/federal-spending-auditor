"""Read-only primary-evidence readiness audit; never trusts a cached result."""
from collections import defaultdict
from pathlib import Path
import re

from .collection_sources import USA,FPDS,parse_page
from .evidence_io import EvidenceError,EvidenceRoot,canonical,digest,parts,strict_json
from .history_ingestion import reconstruct
from .history_pilot import native_request
from .history_reporting import metrics as history_metrics
from .matching_models import ordered
from .readiness_models import (ReadinessEvidenceRef,Measurement,CauseOccurrence,SlotAudit,CohortAudit,CONTROLS)
from .scope_models import ScopeStatus
from .review_packet_models import EvidenceCitation


def inventory(path):
    with EvidenceRoot(path,max_total_bytes=256*1024*1024,max_files=20000) as root:
        return {n:root.read(n).byte_sha256 for n in root.discover()}


def ref(logical,path,sha,detail,kind='source_fact',citation=None):
    source_url=(citation.evidence.reference.source_record_url or citation.evidence.artifact.endpoint) if citation else None
    return ReadinessEvidenceRef(logical_root=logical,relative_path=path,sha256=sha,kind=kind,detail=detail,citation=citation,source_url=source_url)


def unavailable_slot(slot,selected,logical,*,violation=False,detail='unavailable_primary_evidence'):
    evidence=ref(logical,'c3_plan.json',None,detail,'unknown')
    causes=(CauseOccurrence(subject_key='slot:'+str(slot),unit='slot',codes=('evidence_integrity_failure',) if violation else ('partial_source_coverage',),evidence_ids=(evidence.evidence_id,)),)
    return SlotAudit(slot=slot,selected_native_id=selected,processed=False,measurements=(),evidence=(evidence,),causes=causes,
        violations=('no_source_evidence_mutation',) if violation else (),unknown_controls=tuple(sorted(CONTROLS)))


def semantic_digest(run):
    # Different ordering is different raw evidence. This separate fingerprint
    # tests interpretation invariance, preserving multiplicity and raw values.
    records=[]
    for o in run.observations:
        a=o.scope_assessment
        records.append({'source':a.evidence.reference.source,'scope':a.status.value,
            'identity':a.observed.to_dict(),'money':[{'field':m.observation.original_field,'value':m.observation.value.to_dict(),
                'semantics':m.observation.semantics.to_dict(),'date':m.observation.action_date_raw,'currency':m.observation.declared_currency_raw} for m in o.money],
            'times':[t.to_dict() for t in o.freshness.temporal_fields],'issues':list(o.issues)})
    return digest({'records':sorted(records,key=canonical),'financial_status_counts':history_metrics(run)['financial_results'],
        'coverage':sorted([(c.source,c.pagination.value,c.historical_completeness.value) for c in run.coverage])})


def audit_collection(path,slot,selected,logical,*,discovery=False):
    before=inventory(path)
    with EvidenceRoot(path) as root: docs={n:root.read(n).data for n in root.discover()}
    refs=[ref(logical,n,before[n],'Preserved C3 control or response metadata; source facts, not identity verification') for n in sorted(docs) if n.endswith('.json')]
    violations=set();unknown=set();causes=defaultdict(set);cause_refs=defaultdict(set)
    def cause(subject,unit,code,evidence):
        causes[(unit,subject)].add(code);cause_refs[(unit,subject)].update(evidence)
    try:
        plan=strict_json(docs['c3_plan.json']);checkpoint=strict_json(docs['c3_checkpoint.json'])
        if len(plan['awards'])!=1 or plan['awards'][0]['generated_id']!=selected:
            raise EvidenceError('readiness_selection_conflict')
        for name,raw in docs.items():
            if re.fullmatch(r'c3_attempt_[0-9]{6}\.json',name) is None: continue
            meta=strict_json(raw);request=meta['request'];source=request['source']
            if request['endpoint']!={'usaspending':USA,'fpds':FPDS}.get(source): violations.add('approved_endpoints_only')
            if any(k.lower() in ('api_key','authorization','password','token') for k in request.get('parameters',{})):
                violations.add('no_credential_disclosure')
            body=name[:-5]+'.body'
            if meta['body_sha256'] is not None and before.get(body)!=meta['body_sha256']: violations.add('no_source_evidence_mutation')
            if meta['fingerprint']!=digest(plan): violations.add('no_source_evidence_mutation')
            seq=meta['sequence']
            if seq<len(checkpoint['events']) and checkpoint['events'][seq]['metadata_sha256']!=digest(meta): violations.add('no_source_evidence_mutation')
        if violations:
            for code in violations: cause('integrity', 'slot','evidence_integrity_failure',[r.evidence_id for r in refs])
            raise EvidenceError('readiness_unsafe_or_conflicting_source_controls')
        # Schema/semantic availability is distinct from declared-byte integrity.
        request=native_request(path,plan)
        first=reconstruct((path,),request);second=reconstruct((path,),request)
        hm=history_metrics(first)
    except (ValueError,TypeError,KeyError,IndexError) as exc:
        result=unavailable_slot(slot,selected,logical,violation='no_source_evidence_mutation' in violations,
            detail='source_control_or_schema_unavailable_no_synthetic_substitution')
        if inventory(path)!=before: violations.add('no_source_evidence_mutation')
        return __import__('dataclasses').replace(result,evidence=ordered(tuple(refs)+(result.evidence[0],)),violations=tuple(sorted(violations)),
            unknown_controls=tuple(sorted(CONTROLS)))
    if inventory(path)!=before: violations.add('no_source_evidence_mutation')
    # Boundedness is measured from the preserved plan, not inferred from success.
    limits=plan['limits']
    if not 1<=limits['max_pages']<=100000 or not 1<=limits['max_requests']<=1000: violations.add('bounded_pagination')
    if plan.get('collector_version') not in (1,2,3): unknown.add('no_silent_checkpoint_upgrades')
    if first.substantive_sha256!=second.substantive_sha256: unknown.add('no_fabricated_identity')
    if first.inputs[0].artifact_issues:
        for issue in first.inputs[0].artifact_issues:
            code='unsupported_schema' if 'schema' in issue or 'unsupported' in issue else 'partial_source_coverage'
            cause('source_artifact:'+issue.split(':')[0],'artifact',code,[r.evidence_id for r in refs])
    attempts=success=0;parsed_sources=set()
    for name,raw in sorted(docs.items()):
        if re.fullmatch(r'c3_attempt_[0-9]{6}\.json',name) is None: continue
        meta=strict_json(raw);attempts+=1
        good=meta['status'] is not None and 200<=meta['status']<300 and not meta['error_code'] and meta['body_complete']
        success+=int(good)
        rid=next(r.evidence_id for r in refs if r.relative_path==name)
        source=meta['request']['source']
        if not good: cause(source,'source_task','source_access_failure',(rid,));continue
        try:
            parse_page(source,docs[name[:-5]+'.body'],meta['request'],plan['awards'][0]);parsed_sources.add(source)
        except (ValueError,TypeError,KeyError): cause(source,'source_task','unsupported_schema',(rid,))
    record_refs={}
    for o in first.observations:
        a=o.scope_assessment;e=a.evidence
        pointer=ref(logical,e.artifact.relative_path,e.artifact.sha256,'Primary application-response bytes; original locator and provenance retained',citation=EvidenceCitation(evidence=e))
        refs.append(pointer)
        record_refs[a.assessment_id]=pointer.evidence_id
        # Content groups are retrieval/content units, never inferred real-world IDs.
        key=digest({'source':e.reference.source,'content':a.content_sha256,'values':[m.observation.value.to_dict() for m in o.money]})
        eid=(pointer.evidence_id,)
        if a.status is ScopeStatus.OUT_OF_SCOPE:
            cause(key,'record_content','query_imprecision',eid)
            if any(c.result=='conflict' for c in a.comparisons): cause(key,'record_content','identifier_mismatch',eid)
        if a.parent_state in ('unknown_omitted','unsupported_or_ambiguous'):
            cause(key,'record_content','parent_context_ambiguity',eid)
        if a.status is ScopeStatus.UNSUPPORTED or o.issues: cause(key,'record_content','unsupported_schema',eid)
    for c in first.comparisons:
        a=c.left.scope_assessment
        key=digest({'source':a.evidence.reference.source,'content':a.content_sha256,'values':[m.observation.value.to_dict() for m in c.left.money]})
        eids=(record_refs[a.assessment_id],)
        code={'revision_relationship_unknown':'revision_relationship_unknown','insufficient_history':'missing_source_counterpart',
            'incompatible_financial_scope':'incompatible_financial_basis','unsupported_semantics':'unsupported_schema'}.get(c.status.value)
        if code: cause(key,'record_content',code,eids)
    for coverage in first.coverage:
        eids=tuple(r.evidence_id for r in refs if r.relative_path=='c3_plan.json')
        if coverage.pagination.value!='complete': cause(coverage.source,'source_task','partial_source_coverage',eids)
        cause(coverage.source,'source_task','unverified_historical_completeness',eids)
        cause(coverage.source,'source_task','stale_or_unverified_update_status',eids)
    count=len(first.observations);pairs=len(first.comparisons);values=[]
    def m(name,n,d,unit,complete=True): values.append(Measurement(name=name,numerator=n,denominator=d,unit=unit,complete=complete))
    m('operational_slots',1,1,'selected_slots');m('provenance_slots',1,1,'selected_slots')
    m('source_http_success',success,attempts,'preserved_HTTP_attempts')
    m('source_parsed_tasks',len(parsed_sources),2,'expected_source_tasks')
    m('collection_complete_slots',int(len(first.coverage)==2 and all(c.pagination.value=='complete' for c in first.coverage)),1,'selected_slots')
    m('returned_occurrences',count,None,'enumerated_record_occurrences',hm['enumerated_occurrence_count_complete'])
    for status,name in ((ScopeStatus.IN_SCOPE,'scope_verified'),(ScopeStatus.OUT_OF_SCOPE,'scope_out'),(ScopeStatus.AMBIGUOUS,'scope_ambiguous'),(ScopeStatus.INSUFFICIENT,'scope_insufficient'),(ScopeStatus.UNSUPPORTED,'scope_unsupported')):
        m(name,sum(o.scope_assessment.status is status for o in first.observations),count,'enumerated_record_occurrences',hm['enumerated_occurrence_count_complete'])
    m('eligible_action_identities',hm['distinct_eligible_action_identities'],None,'distinct_native_keys_within_slot')
    m('modifications',hm['distinct_eligible_modifications'],None,'distinct_modification_strings_within_slot')
    m('observed_modification_records',len({(o.scope_assessment.evidence.reference.source,o.scope_assessment.content_sha256)
        for o in first.observations if o.modification.native is not None}),None,'distinct_source_record_contents_with_native_modification',hm['enumerated_occurrence_count_complete'])
    m('slots_with_actions',hm['awards_with_eligible_observed_actions'],1,'selected_slots')
    m('revision_aligned',sum(c.alignment is not None and c.alignment.status.value=='same_verified_action_compatible_revision' for c in first.comparisons),pairs,'observed_record_pair_results')
    m('revision_unknown',hm['revision_uncertainty_withheld'],pairs,'observed_record_pair_results')
    m('history_known_complete',0,len(first.coverage),'input_source_assessments');m('history_unknown',len(first.coverage),len(first.coverage),'input_source_assessments')
    m('financial_authorized',hm['newly_authorized_live_cross_source_comparisons'],pairs,'revision_conditioned_record_pair_results')
    for status,value in hm['financial_results'].items(): m('financial_'+status,value,pairs,'observed_record_pair_results')
    m('freshness_supported',0,count,'record_occurrences');m('freshness_unknown',count,count,'record_occurrences')
    m('review_traceable',count,count,'record_occurrences_with_C6_citation_and_locator')
    m('replay_consistent_slots',int(first.substantive_sha256==second.substantive_sha256),1,'selected_slots')
    return SlotAudit(slot=slot,selected_native_id=selected,processed=True,measurements=ordered(values),evidence=ordered(refs),
        causes=ordered(CauseOccurrence(subject_key=k[1],unit=k[0],codes=tuple(sorted(codes)),evidence_ids=tuple(sorted(cause_refs[k]))) for k,codes in causes.items()),
        violations=tuple(sorted(violations)),unknown_controls=tuple(sorted(unknown)),replay_first_sha256=first.substantive_sha256,
        replay_second_sha256=second.substantive_sha256,semantic_sha256=semantic_digest(first))


def audit_frozen(source,protocol):
    source=Path(source).absolute()
    try:
        inv=inventory(source)
        with EvidenceRoot(source) as root:
            sample=strict_json(root.read('sample.json').data);plan=strict_json(root.read('pilot-plan.json').data)
        selected=sample['selected']
        expected=protocol.profile=='frozen-live-pilot'
        if (expected and (digest(inv)!=protocol.frozen_inventory_sha256 or digest(sample)!=protocol.frozen_sample_sha256 or digest(plan)!=protocol.frozen_pilot_plan_sha256)):
            raise EvidenceError('frozen_evidence_lineage_conflict')
        if not 1<=len(selected)<=30: raise EvidenceError('unsupported_frozen_selection')
    except (ValueError,TypeError,KeyError,OSError):
        n=24 if protocol.profile=='frozen-live-pilot' else 1
        return CohortAudit(role='frozen_pilot',sample_sha256=None,inventory_sha256=None,
            source_plan_sha256=None,original_implementation_sha256=protocol.original_implementation_sha256,
            selected_count=n,slots=tuple(unavailable_slot(i,None,'frozen_pilot/slot-'+str(i),violation=source.exists(),detail='frozen_cohort_unavailable_or_hash_lineage_conflict') for i in range(n)),
            available=False,unchanged=True,profile='live' if protocol.profile=='frozen-live-pilot' else 'synthetic',limitations=('original_cohort_unavailable_no_substitution',))
    slots=[]
    with EvidenceRoot(source,max_total_bytes=256*1024*1024,max_files=20000) as original:
        for i,row in enumerate(selected):
            logical=f'frozen_pilot/slot-{i:03d}'
            try:
                desc=strict_json(original.read(f'award-{i:03d}/research/research-plan.json').data)['sources']
                if len(desc)!=1: raise EvidenceError('unsupported_source_count')
                d=desc[0]
                if d['managed']:
                    path=source/f'award-{i:03d}'/'research'/Path(*parts(d['path']))
                else:
                    historical=Path(d['path'])
                    if not historical.is_absolute() or historical.parts[-2:]!=(f'award-{i:03d}','discovery'):
                        raise EvidenceError('external_source_outside_frozen_slot')
                    # Historical absolute descriptors are provenance, not an
                    # instruction to read outside the current frozen snapshot.
                    path=source/f'award-{i:03d}'/'discovery'
                logical='frozen_pilot/'+path.relative_to(source).as_posix()
                slot=audit_collection(path,i,row['generated_id'],logical)
            except (ValueError,TypeError,KeyError,IndexError,OSError): slot=unavailable_slot(i,row.get('generated_id'),logical)
            slots.append(slot)
    unchanged=inventory(source)==inv
    return CohortAudit(role='frozen_pilot',sample_sha256=digest(sample),inventory_sha256=digest(inv),source_plan_sha256=digest(plan),
        original_implementation_sha256=plan['config']['implementation_sha256'],selected_count=len(selected),slots=tuple(slots),available=True,unchanged=unchanged,
        profile='live' if protocol.profile=='frozen-live-pilot' else 'synthetic',limitations=('original_selection_preserved','read_only_new_rule_evaluation_not_original_technical_completion','hashes_do_not_authenticate_source','convenience_cohort_not_population'))
