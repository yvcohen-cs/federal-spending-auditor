"""Frozen C4 task selection, primary revalidation and versioned C5 preparation."""
from pathlib import Path
from .evidence_io import EvidenceError,canonical,digest,strict_json
from .review_validation_study import protocol as c4_protocol,replay_study,selected_tasks
from .review_validation_tasks import inventory,build_tasks
from .pilot_session_models import PilotTaskSet,TaskBinding,StudyProtocol,MeasurementKind,PREPARATION_SHA

DOCS=Path(__file__).resolve().parents[1]/'docs'


def preparation():
    value=strict_json((DOCS/'pilot-preparation-protocol-v1.json').read_bytes())
    if digest(value)!=PREPARATION_SHA:raise EvidenceError('pilot_preparation_protocol_changed')
    for name,sha in (('pilot-usability-requirements-v1.json','dde379ecff99d42ca9684bdce2fa7d71c6e671fa8a6b0c46e05308e86325fc54'),('pilot-future-plan-v1.json','e2ce5f9e7fd8b58e7101e58abd0ae58da12bf7583ae0e814b537de0f783ab590')):
        if digest(strict_json((DOCS/name).read_bytes()))!=sha:raise EvidenceError('pilot_versioned_plan_changed')
    return value


def expected_order(version):
    base=tuple(c['case_id'] for c in c4_protocol()['cases'] if not c['expect_integrity_block'])
    return base+(('preserved_public',) if version=='pilot-mixed-v1' else ())


def build_task_set(study_root,*,public_root=None):
    # C4 validates the entire immutable control capture, including its rejected
    # citation fixture, before exposing any positive task.
    replay_study(study_root)
    entries=[]
    for spec in c4_protocol()['cases']:
        if spec['expect_integrity_block']:continue
        source=Path(study_root)/spec['case_id']/'source';manifest=selected_tasks(source,spec['case_id']);task=manifest.tasks[0]
        reference=task.permitted_decisions[0] if spec['case_id']=='verified_identity' else None
        entries.append(TaskBinding(logical_root=spec['case_id'],source_root=str(source.absolute()),source_inventory_json=manifest.source_inventory_json,
            selected_claim_ids=manifest.packets.selected_claim_ids,task=task,origin='authored_synthetic_control',reference_decision=reference,
            reference_scope='authored_narrow_property_only_not_award_truth' if reference else 'NOT_MEASURED_no_reliable_reference_answer'))
    if public_root is not None:
        plan=strict_json((DOCS/'review-existing-evidence-plan-v1.json').read_bytes())
        if digest(inventory(public_root))!=plan['source_inventory_sha256']:raise EvidenceError('frozen_public_task_inventory_conflict')
        full=build_tasks(public_root);claim=min(full.packets.selected_claim_ids)
        manifest=build_tasks(public_root,claim_ids=(claim,));task=manifest.tasks[0]
        entries.append(TaskBinding(logical_root='preserved_public',source_root=str(Path(public_root).absolute()),source_inventory_json=manifest.source_inventory_json,
            selected_claim_ids=(claim,),task=task,origin='preserved_public_unverified'))
    result=PilotTaskSet(entries=tuple(entries),selection_version='pilot-mixed-v1' if public_root is not None else 'pilot-controls-v1')
    pin_sources(result);return result


def pin_sources(task_set):
    for e in task_set.entries:
        if canonical(inventory(e.source_root))!=e.source_inventory_json:raise EvidenceError('pilot_source_evidence_changed')


def revalidate_tasks(task_set):
    pin_sources(task_set)
    for e in task_set.entries:
        if e.origin=='preserved_public_unverified':
            plan=strict_json((DOCS/'review-existing-evidence-plan-v1.json').read_bytes())
            if digest(strict_json(e.source_inventory_json.encode()))!=plan['source_inventory_sha256']:raise EvidenceError('public_source_not_preregistered')
        elif any('synthetic_fixture_only' not in c.evidence.artifact.limitations for c in e.task.citations):
            raise EvidenceError('authored_control_cannot_be_real_source')
        fresh=build_tasks(e.source_root,claim_ids=e.selected_claim_ids)
        if fresh.tasks!=(e.task,):raise EvidenceError('pilot_task_projection_conflict')
    pin_sources(task_set)


def governance_sha():
    import hashlib
    value=hashlib.sha256((DOCS/'pilot-governance-v1.md').read_bytes()).hexdigest()
    if value!='399471cfb597d245d7ae166bb3ee18dd46d46af7fb7d62b7c3f830038b5aa57f':raise EvidenceError('pilot_governance_changed')
    return value


def make_protocol(task_set,*,kind=MeasurementKind.SIMULATED,timing=False,instance_id=None):
    preparation()
    if instance_id is None and kind is MeasurementKind.HUMAN:raise EvidenceError('actual_study_requires_explicit_new_batch_id')
    return StudyProtocol(task_set_digest=task_set.task_set_digest,evidence_inventory_digest=task_set.evidence_inventory_digest,
        governance_sha256=governance_sha(),measurement_kind=kind,instance_id=instance_id or 'BATCH-aaaaaaaa00000001',timing_enabled=timing,selection_version=task_set.selection_version)
