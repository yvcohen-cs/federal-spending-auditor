"""Read-only experimental parent/query explanation. No C4/C5 eligibility export."""
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from .evidence import Schema
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json
from .identity_matching import ACTION_FIELDS, key_for
from .parent_identity import ParentAssessment, ParentStatus, RULE, SOURCES, assess_parent
from .readiness_audit import inventory
from .scope_ingestion import assess_collection
from .scope_models import ScopeRequest, ScopeStatus


@dataclass(frozen=True, kw_only=True)
class ParentScopeRun(Schema):
    requested: ScopeRequest
    input_inventories_json: str
    assessments: tuple[ParentAssessment,...]
    artifact_issues: tuple[str,...]
    submitted_requests_json: str
    rule_version: str = RULE

    def validate(self):
        if self.rule_version != RULE:
            raise ValueError('unsupported experimental scope rule')
        for text in (self.input_inventories_json,self.submitted_requests_json):
            if canonical(strict_json(text.encode())) != text:
                raise ValueError('canonical input context required')
        if any(a.baseline.requested != self.requested for a in self.assessments):
            raise ValueError('requested native identity conflict')
        ids = [a.baseline.assessment_id for a in self.assessments]
        if ids != sorted(set(ids)):
            raise ValueError('unique sorted occurrence assertions required')
        for a in self.assessments:
            expected = assess_parent(a.baseline,tuple(b.baseline for b in self.assessments))
            if a != expected:
                raise ValueError('missing or fabricated cross-snapshot conflict evidence')

    @property
    def substantive_sha256(self): return digest(self.to_dict())


def assess_parent_collection(paths, requested):
    paths = tuple(Path(p).absolute() for p in paths)
    if not 1 <= len(paths) <= 4 or len(set(paths)) != len(paths):
        raise EvidenceError('bounded_distinct_collection_roots_required')
    before = [inventory(p) for p in paths]
    runs = [assess_collection(p,requested) for p in paths]
    baseline = {}
    for run in runs:
        for a in run.assessments:
            if a.assessment_id in baseline:
                raise EvidenceError('overlapping_input_occurrence')
            baseline[a.assessment_id] = a
    if len(baseline)>2000: raise EvidenceError('parent_record_limit')
    peers = tuple(baseline.values())
    values = tuple(assess_parent(baseline[k],peers) for k in sorted(baseline))
    requests = []
    for index,path in enumerate(paths):
        with EvidenceRoot(path) as root:
            for name in root.discover():
                if name.startswith('c3_attempt_') and name.endswith('.json'):
                    meta = strict_json(root.read(name).data)
                    requests.append({'input':index,'metadata_path':name,'request':meta['request'],
                                     'status':meta['status'],'body_complete':meta['body_complete'],'error_code':meta['error_code'],'retrieved_at_utc':meta['retrieved_at_utc'],
                                     'body_sha256':meta['body_sha256']})
    if [inventory(p) for p in paths] != before:
        raise EvidenceError('parent_source_evidence_changed')
    return ParentScopeRun(requested=requested,input_inventories_json=canonical(before),assessments=values,
        artifact_issues=tuple(sorted(f'input-{i}:'+issue for i,r in enumerate(runs) for issue in r.artifact_issues)),
        submitted_requests_json=canonical(requests))


def transition_metrics(slots):
    """Each slot has its own cohort label; no global action/award inference."""
    groups = defaultdict(list)
    for slot,run in slots:
        for a in run.assessments:
            groups[(a.baseline.status.value,a.new_scope_status.value)].append((slot,a))
    transitions = []
    for (old,new),values in sorted(groups.items()):
        transitions.append({'previous':old,'new':new,'occurrences':len(values),
            'distinct_source_contents':len({(a.baseline.evidence.reference.source,a.baseline.content_sha256) for _,a in values}),
            'affected_slot_ids':sorted({s for s,_ in values}),'rules':sorted({a.rationale for _,a in values}),
            'authorization_ids':[a.assessment_id for _,a in values]})
    values = [(slot,a) for slot,r in slots for a in r.assessments]
    count = len(values)
    action_counts = {}
    for label,run in slots:
        action_counts[label] = len({key_for(a.baseline.record,ACTION_FIELDS) for a in run.assessments
            if a.new_scope_status is ScopeStatus.IN_SCOPE and a.baseline.record is not None and key_for(a.baseline.record,ACTION_FIELDS) is not None})
    return {'cohort_slots':[s for s,_ in slots],'unit':'enumerated_verification_record_occurrences','denominator':count,
        'previous':{s.value:sum(a.baseline.status is s for _,a in values) for s in ScopeStatus},
        'new':{s.value:sum(a.new_scope_status is s for _,a in values) for s in ScopeStatus},
        'parents':{s.value:sum(a.status is s for _,a in values) for s in ParentStatus},
        'distinct_source_contents':len({(a.baseline.evidence.reference.source,a.baseline.content_sha256) for _,a in values}),
        'changed_occurrences':sum(a.baseline.status is not a.new_scope_status for _,a in values),
        'affected_distinct_award_slots':len({s for s,a in values if a.baseline.status is not a.new_scope_status}),
        'eligible_action_identities':{'count':sum(action_counts.values()),'unit':'sum_distinct_complete_native_action_keys_within_slot_experimental_scope_only','by_slot':action_counts},
        'newly_eligible_financial_comparisons':0,'financial_integration':'disabled_by_design_not_a_measured_counterfactual',
        'transitions':transitions,'population_precision':'not_estimated',
        'occurrence_count_complete':all(not r.artifact_issues for _,r in slots)}


def query_explanation(run):
    requests = strict_json(run.submitted_requests_json.encode())
    rows = []
    duplicates = Counter((a.baseline.evidence.reference.source,a.baseline.content_sha256) for a in run.assessments)
    for a in run.assessments:
        b = a.baseline
        submitted = [r for r in requests if r['metadata_path'] in b.evidence.metadata_paths and r['request']['source']==b.evidence.reference.source
                     and r['metadata_path'].removesuffix('.json')+'.body' == b.evidence.artifact.relative_path
                     and r['request']['parameters'] == strict_json(b.evidence.artifact.request_json.encode())
                     and r['body_sha256']==b.evidence.artifact.sha256 and r['retrieved_at_utc']==b.evidence.artifact.retrieved_at_utc]
        # Same relative path in different roots may coincide: collapse exact
        # request descriptions, never assert a unique journal from a filename.
        rows.append({'assessment_id':a.assessment_id,'requested_native':run.requested.to_dict(),
            'submitted_request_contexts':submitted,'source_query_support':'documented_filters_not_verified_exact_native_identity_enforcement',
            'returned_native':b.observed.to_dict(),'parent':{'status':a.status.value,'instrument_type':a.instrument_type,
                'fields':[f.to_dict() for f in a.fields],'rationale':a.rationale,'rule_version':a.rule_version},
            'citation':a.citation.to_dict(),'previous_inclusion':b.status.value,'inclusion':a.new_scope_status.value,
            'requested_native_query':{'piid':run.requested.piid,'identity_agency':run.requested.agency,'parent_piid':run.requested.parent_piid,
                'parent_agency':run.requested.parent_agency,'modification':run.requested.modification,'transaction':run.requested.transaction},
            'query_limitations':['Legacy FPDS query filters PIID and CONTRACTING_AGENCY_ID; contracting agency is not asserted equivalent to award identity agency.',
                'Parent/modification/transaction requested constraints are checked locally, not submitted in the legacy FPDS query.',
                'Tokenization, partial matching, parent query enforcement, recall and historical server cause remain unverified.'],
            'known_component_conflicts':[f.name for f in b.comparisons if f.result=='conflict'],
            'duplicate_content_occurrences':duplicates[(b.evidence.reference.source,b.content_sha256)],
            'explanation':'record_identity_decision_not_server_defect_or_parent_existence_proof',
            'recommended_action':'Confirm requested parent with native award documentation; preserve corrections and establish revision lineage before financial comparison.'})
    return rows


def report_for(slots, *, protocol, unavailable=(), downstream=()):
    if len({s for s,_ in slots}) != len(slots) or {s for s,_ in slots} & {s['slot'] for s in unavailable}:
        raise ValueError('duplicate or both processed and unavailable slot')
    summary = transition_metrics(slots)
    summary['selected_slot_denominator'] = len(slots)+len(unavailable)
    summary['inspected_slots'] = len(slots)
    summary['occurrence_count_complete'] = summary['occurrence_count_complete'] and not unavailable
    summary['by_cohort'] = {cohort:transition_metrics(tuple((s,r) for s,r in slots if s.split('/')[0]==cohort))
        for cohort in sorted({s.split('/')[0] for s,_ in slots})}
    return {'schema_type':'ParentIdentityResearchReport','schema_version':1,'version':RULE,'profile':'synthetic' if slots and all('synthetic_fixture_only' in a.baseline.evidence.artifact.limitations for _,r in slots for a in r.assessments) else 'saved_evidence_experiment',
        'protocol':protocol,'protocol_sha256':digest(protocol),
        'official_semantics':[{'id':key,'url':url,'reviewed_on':'2026-10-28','limitation':detail} for key,url,detail in SOURCES],
        'metrics':summary,'unavailable_slots':list(unavailable),
        'runs':[{'slot':s,'run':r.to_dict(),'substantive_sha256':r.substantive_sha256,'query_explanations':query_explanation(r)} for s,r in slots],
        'downstream_baseline':list(downstream),
        'limitations':['Source-native parent assertion does not prove independent parent existence.',
            'No new financial eligibility, history/revision/freshness assurance, or readiness decision.',
            'No inferred agency crosswalk, generated-ID absence proof, PIID-position classification, or independent corroboration.',
            'Missing, blank, null, omitted and placeholder fields alone never prove no parent.',
            'Legacy cached reports and review workflow unchanged; raw bytes revalidated.'],
        'http_requests':0}
