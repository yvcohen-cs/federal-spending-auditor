"""Transparent two-root holdout projection, never a fabricated combined journal."""
from collections import defaultdict
from pathlib import Path

from .evidence_io import EvidenceRoot,strict_json,digest
from .history_ingestion import reconstruct
from .history_pilot import native_request
from .history_reporting import metrics
from .matching_models import ordered
from .readiness_audit import audit_collection,semantic_digest
from .readiness_models import SlotAudit,Measurement,CauseOccurrence


def audit_snapshot_pair(paths,slot,selected,logical):
    children=[audit_collection(p,slot,selected,logical+'/'+Path(p).name) for p in paths]
    if not all(c.processed for c in children):
        from .readiness_audit import unavailable_slot
        from dataclasses import replace
        missing=unavailable_slot(slot,selected,logical,violation=any('no_source_evidence_mutation' in c.violations for c in children))
        return replace(missing,evidence=ordered(missing.evidence+tuple(r for c in children for r in c.evidence)),
            violations=tuple(sorted({v for c in children for v in c.violations})))
    with EvidenceRoot(paths[0]) as root: plan=strict_json(root.read('c3_plan.json').data)
    requested=native_request(paths[0],plan)
    run=reconstruct(paths,requested);replay=reconstruct(paths,requested);hm=metrics(run)
    evidence=ordered(r for c in children for r in c.evidence)
    values=[]
    summed=defaultdict(list)
    for c in children:
        for m in c.measurements: summed[m.name].append(m)
    for name,items in summed.items():
        n=sum(m.numerator for m in items if m.numerator is not None)
        d=sum(m.denominator for m in items if m.denominator is not None) if any(m.denominator is not None for m in items) else None
        if name in ('operational_slots','provenance_slots'): n=d=1
        if name=='replay_consistent_slots': n=int(run.substantive_sha256==replay.substantive_sha256);d=1
        if name=='source_parsed_tasks': d=2
        if name=='collection_complete_slots': n=int(all(c.pagination.value=='complete' for c in run.coverage));d=1
        if name=='eligible_action_identities': n=hm['distinct_eligible_action_identities']
        if name=='modifications': n=hm['distinct_eligible_modifications']
        if name=='slots_with_actions': n=hm['awards_with_eligible_observed_actions'];d=1
        if name.startswith('financial_'):
            n=hm['newly_authorized_live_cross_source_comparisons'] if name=='financial_authorized' else hm['financial_results'][name.removeprefix('financial_')]
            d=len(run.comparisons)
        if name=='revision_aligned': n=sum(c.alignment is not None and c.alignment.status.value=='same_verified_action_compatible_revision' for c in run.comparisons);d=len(run.comparisons)
        if name=='revision_unknown': n=hm['revision_uncertainty_withheld'];d=len(run.comparisons)
        values.append(Measurement(name=name,numerator=n,denominator=d,unit=items[0].unit,complete=all(m.complete for m in items)))
    codes=defaultdict(set);refs=defaultdict(set)
    replaced={'missing_source_counterpart','revision_relationship_unknown','incompatible_financial_basis'}
    for c in children:
        for a in c.causes:
            k=(a.unit,a.subject_key);codes[k].update(set(a.codes)-replaced);refs[k].update(a.evidence_ids)
    for c in run.comparisons:
        a=c.left.scope_assessment
        key=digest({'source':a.evidence.reference.source,'content':a.content_sha256,'values':[m.observation.value.to_dict() for m in c.left.money]})
        code={'revision_relationship_unknown':'revision_relationship_unknown','insufficient_history':'missing_source_counterpart','incompatible_financial_scope':'incompatible_financial_basis','unsupported_semantics':'unsupported_schema'}.get(c.status.value)
        if code:
            k=('record_content',key);codes[k].add(code)
            refs[k].update(r.evidence_id for r in evidence if r.sha256==a.evidence.artifact.sha256)
    return SlotAudit(slot=slot,selected_native_id=selected,processed=True,measurements=ordered(values),evidence=evidence,
        causes=ordered(CauseOccurrence(subject_key=k[1],unit=k[0],codes=tuple(sorted(v)),evidence_ids=tuple(sorted(refs[k]))) for k,v in codes.items() if v),
        violations=tuple(sorted({v for c in children for v in c.violations})),unknown_controls=tuple(sorted({v for c in children for v in c.unknown_controls})),
        replay_first_sha256=run.substantive_sha256,replay_second_sha256=replay.substantive_sha256,semantic_sha256=semantic_digest(run))
