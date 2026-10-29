"""Read-only task projection from C6 packets plus existing parent/history readers."""
from .evidence import ComparisonStatus as C, Completeness
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json
from .matching_models import ordered
from .review_packet_models import EvidenceCitation
from .review_packet_builder import build_packets
from .review_packet_io import read_bundle
from .history_ingestion import reconstruct
from .history_pilot import native_request
from .parent_scope import assess_parent_collection
from .parent_identity import ParentStatus
from .review_validation_models import (ReviewDimension, ReviewObservedField, ReviewerTask,
    ReviewerTaskManifest, EvidenceStatus as S, RULE, workflow_spec)


def inventory(path):
    with EvidenceRoot(path,max_bytes=8*1024*1024,max_total_bytes=32*1024*1024,max_files=2000) as root:
        before={n:root.read(n) for n in root.discover()}
        hashes={n:s.byte_sha256 for n,s in before.items()}
        if {n:root.read(n,recheck=True).byte_sha256 for n in root.discover()}!=hashes:
            raise EvidenceError('review_validation_source_changed')
        return hashes


def project_tasks(manifest,parent,history,inventory_json):
    snapshot=digest({'packets':manifest.substantive_sha256,'parent':parent.substantive_sha256,
        'history':history.substantive_sha256,'inventory':strict_json(inventory_json.encode())})
    result=[]
    for packet in manifest.packets:
        citations=ordered(packet.citations+tuple(p.citation for p in parent.assessments)+tuple(EvidenceCitation(evidence=o.scope_assessment.evidence) for o in history.observations))
        ids=tuple(sorted(c.citation_id for c in citations)); known=set(ids)
        packet_ids=tuple(sorted(c.citation_id for c in packet.citations))
        parents=list(parent.assessments)
        observations=list(history.observations)
        decision=packet.claim.identity_result
        financial=packet.claim.financial_result
        if financial:
            decision=next(d for d in manifest.financial_run.identity_run.decisions if d.claim_id==financial.identity_claim_id)
        def status(s):
            return S.VERIFIED if s is C.VERIFIED_MATCH else S.CONFLICTING if s in (C.UNRESOLVED_DISCREPANCY,C.EXPLAINABLE_DIFFERENCE) else S.INSUFFICIENT
        parent_state=S.CONFLICTING if any(p.status is ParentStatus.CONFLICT for p in parents) else S.UNSUPPORTED if any(p.status is ParentStatus.UNSUPPORTED for p in parents) else S.VERIFIED if parents and all(p.status in (ParentStatus.VERIFIED,ParentStatus.NONE) for p in parents) else S.INSUFFICIENT
        fpds_parents=[p for p in parents if p.baseline.evidence.reference.source=='fpds']
        instrument=S.INSUFFICIENT if not fpds_parents else S.UNSUPPORTED if any(p.status is ParentStatus.UNSUPPORTED or p.instrument_type not in ('A','C','D') for p in fpds_parents) else S.INSUFFICIENT if not parents else S.VERIFIED
        fields=[]
        for source in packet.sources:
            for cid in source.citation_ids:
                for name in ('piid','agency','parent_piid','parent_agency','modification','transaction'):
                    fields.append(ReviewObservedField(citation_id=cid,path='C4.'+name,original_json=getattr(source.identity,name).original_json,basis='C4_component_interpretation'))
                for native in source.identity.native_identifiers:
                    fields.append(ReviewObservedField(citation_id=cid,path=native.namespace,original_json=canonical(native.value),basis='source_native_value'))
                for money in source.monetary_observations:
                    fields.append(ReviewObservedField(citation_id=cid,path=money.original_field,original_json=canonical(money.value.raw_text),basis='source_native_value'))
        for p in parents:
            fields.extend(ReviewObservedField(citation_id=p.citation.citation_id,path='C4.'+name,original_json=getattr(p.baseline.observed,name).original_json,basis='C4_component_interpretation') for name in ('piid','agency','parent_piid','parent_agency','modification','transaction'))
            fields.extend(ReviewObservedField(citation_id=p.citation.citation_id,path=f.path,original_json=f.raw_json,basis='source_native_value') for f in p.fields)
        for o in observations:
            fields.extend(ReviewObservedField(citation_id=EvidenceCitation(evidence=o.scope_assessment.evidence).citation_id,path=m.observation.original_field,original_json=canonical(m.observation.value.raw_text),basis='source_native_value') for m in o.money)
            fields.extend(ReviewObservedField(citation_id=EvidenceCitation(evidence=o.scope_assessment.evidence).citation_id,path=f.path,original_json=f.original_json,basis='source_native_value') for f in o.freshness.temporal_fields)
        states=[('claim',status(packet.claim.status),'Original automated claim status '+packet.claim.status.value+'; saved claim only.'),
            ('identity',status(decision.status),'Existing C4 identity result '+decision.status.value+'; no broader identity inference.'),
            ('parent',parent_state,'Native parent assertions assessed separately; missing fields never establish absence.'),
            ('instrument',instrument,'Source-specific instrument applicability; unsupported attributes are not repaired.'),
            ('pagination',S.INSUFFICIENT,'Unknown/partial query traversal; terminal pages never prove full history.'),
            ('history',S.INSUFFICIENT,'Missing counterpart and full transaction-history coverage remain separate unknowns.'),
            ('revision',S.INSUFFICIENT,'No authoritative common source revision established by accepting this packet.'),
            ('monetary_observations',S.NOT_EVALUATED if financial is None else S.CONFLICTING if financial.difference_usa_minus_fpds not in (None,'0') else status(financial.status),'Existing C5 values/result retained; unequal saved values do not establish wrongdoing or aligned revisions.'),
            ('financial_authorization',S.NOT_EVALUATED if financial is None else S.INSUFFICIENT,'This review layer cannot authorize additional arithmetic; existing C5 result is unchanged.'),
            ('traceability',S.VERIFIED,'Primary bytes, locators, provenance and packet projection revalidated; hashes are not source-authenticity proof.')]
        dimensions=ordered(ReviewDimension(name=n,status=s,rationale=t,citation_ids=ids) for n,s,t in states)
        result.append(ReviewerTask(packet_id=packet.packet_id,claim_id=packet.claim.claim_id,
            source_snapshot_sha256=snapshot,claim=packet.comparison.scope,rule_versions=tuple(sorted({RULE,workflow_spec()['version'],packet.rule_version,decision.rule_version,parent.rule_version,history.rule_version})),
            citations=citations,packet_citation_ids=packet_ids,context_citation_ids=tuple(sorted(known-set(packet_ids))),observed_fields=ordered(fields),dimensions=dimensions,
            limitations=tuple(sorted({l.detail for l in packet.limitations}|set(manifest.financial_run.limitations)|{'Reviewer labels are self-reported; no authenticated identity or source-reliability guarantee.'})),
            missing_proof_obligations=tuple(sorted(d.name for d in dimensions if d.status not in (S.VERIFIED,S.NOT_EVALUATED)))))
    return ordered(result)


def build_tasks(root,*,packet_bundle=None,claim_ids=None):
    before=inventory(root)
    if packet_bundle:
        saved,_=read_bundle(packet_bundle)
        if claim_ids is not None: raise EvidenceError('saved_packet_selection_is_frozen')
        packets=build_packets(root,claim_ids=saved.selected_claim_ids)
        if packets.substantive_sha256!=saved.substantive_sha256:
            raise EvidenceError('stale_review_task_packets')
    else:
        packets=build_packets(root,claim_ids=claim_ids,max_claims=100)
    with EvidenceRoot(root) as reader:
        plan=strict_json(reader.read('c3_plan.json').data)
    if len(plan['awards'])!=1: raise EvidenceError('one_explicit_award_context_per_task_manifest')
    requested=native_request(root,plan)
    history=reconstruct((root,),requested)
    parent=assess_parent_collection((root,),requested)
    if inventory(root)!=before: raise EvidenceError('review_validation_source_changed')
    text=canonical(before)
    return ReviewerTaskManifest(source_inventory_json=text,packets=packets,parent=parent,history=history,
        tasks=project_tasks(packets,parent,history,text))


def validate_primary(root,manifest):
    fresh=build_tasks(root,claim_ids=manifest.packets.selected_claim_ids)
    if fresh.substantive_sha256!=manifest.substantive_sha256:
        raise EvidenceError('stale_review_validation_primary_evidence')
    return fresh


def check_new_location(path,*,study=False):
    import os
    from pathlib import Path
    target=Path(path).absolute()
    markers=('pilot-plan.json','research-plan.json','c3_plan.json','output-manifest.json','review-context.json')+ (('study-plan.json',) if study else ())
    for ancestor in (target.parent,)+tuple(target.parent.parents):
        with EvidenceRoot(ancestor) as reader:
            for marker in markers:
                try:
                    os.stat(marker,dir_fd=reader.fd,follow_symlinks=False)
                except FileNotFoundError:
                    continue
                raise EvidenceError('new_review_store_inside_managed_evidence_or_output')
    return target
