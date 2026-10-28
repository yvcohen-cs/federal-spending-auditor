"""Read-only C3 occurrence adapter; scope eligibility never edits source records."""
import re
import xml.etree.ElementTree as ET

from .collection_sources import ATOM, parse_page
from .evidence import EvidenceArtifact, EvidenceRecordRef, Representation, SourceIdentifier
from .evidence_ingestion import ValidationStatus, inspect_directory
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, safe_xml, strict_json
from .identity_matching import identify, match_records
from .matching_ingestion import _check_fpds_contexts
from .matching_models import MatchEvidenceReference
from .scope_models import ObservedIdentity, ScopeRun, ScopeStatus, assessment, conflicting_occurrences


def assess_collection(path,requested,*,max_records=1000):
    if type(max_records) is not int or not 1<=max_records<=10000:
        raise EvidenceError("scope_record_limit")
    scan=inspect_directory(path)
    if not scan.complete:
        raise EvidenceError("incomplete_scope_evidence_scan")
    entries={e.relative_path:e for e in scan.entries}
    required=("c3_plan.json","c3_checkpoint.json")
    if any(n not in entries or entries[n].status is not ValidationStatus.VERIFIED for n in required):
        raise EvidenceError("scope_requires_valid_c3_controls")
    if any(n not in (*required,"c3_summary.json") and not re.fullmatch(r"c3_attempt_[0-9]{6}\.(?:json|body)",n) for n in entries):
        raise EvidenceError("scope_requires_one_flat_c3_collection")
    result,issues=[],[]
    with EvidenceRoot(path) as root:
        inventory={n:root.read(n) for n in root.discover()}
        if set(inventory)!=set(entries) or any(e.byte_sha256 is not None and inventory[n].byte_sha256!=e.byte_sha256 for n,e in entries.items()):
            raise EvidenceError("scope_evidence_changed")
        plan=strict_json(inventory["c3_plan.json"].data)
        if len(plan['awards'])!=1:
            raise EvidenceError('scope_requires_single_award_collection')
        selected_context=plan['awards'][0]
        for name,native in (('piid','piid'),('agency','agency_id'),('parent_piid','parent_piid'),('parent_agency','parent_agency_id')):
            if selected_context[native] is not None and getattr(requested,name)!=selected_context[native]:
                raise EvidenceError('scope_request_conflicts_with_collection_selection')
        for name in sorted(inventory):
            if re.fullmatch(r'c3_attempt_[0-9]{6}\.json',name) and name[:-5]+'.body' not in inventory:
                issues.append(name+':response_body_unavailable_record_count_unknown')
        for name,snap in sorted(inventory.items()):
            if not name.endswith('.body'): continue
            meta_name=name[:-5]+'.json'
            if meta_name not in entries or entries[meta_name].status is not ValidationStatus.VERIFIED:
                issues.append(name+":unverified_provenance");continue
            meta=strict_json(inventory[meta_name].data)
            if meta["body_sha256"]!=snap.byte_sha256:
                raise EvidenceError("scope_body_hash_conflict")
            if meta["error_code"] or not meta["body_complete"] or not 200<=meta["status"]<300:
                issues.append(name+":failed_or_partial_source_response");continue
            req=meta["request"];source=req["source"]
            selected=plan["awards"][req["task_index"]//len(plan["sources"])]
            artifact=EvidenceArtifact(source=source,relative_path=name,sha256=snap.byte_sha256,
                representation=Representation.RESPONSE_BYTES,hash_basis="original_bytes",endpoint=req["endpoint"],method=req["method"],
                request_json=canonical(req["parameters"]),retrieved_at_utc=meta["retrieved_at_utc"],http_status=meta["status"],
                limitations=("application_response_bytes_not_wire_capture","scope_assessment_not_history_or_authenticity",)+(() if plan["profile"]=="live" else ("synthetic_fixture_only",)))
            observation="observation:v1:"+digest({"version":1,"source":source,"endpoint":artifact.endpoint,"method":artifact.method,
                "request_json":artifact.request_json,"retrieved_at_utc":artifact.retrieved_at_utc,"representation":artifact.representation.value})
            try:
                if source=="usaspending":
                    body=strict_json(snap.data);rows=body['results']
                    if not isinstance(rows,list): raise EvidenceError('unsupported_scope_rows')
                else:
                    _,tree=safe_xml(snap.data)
                    if tree.tag!=ATOM+'feed': raise EvidenceError('unsupported_fpds_scope_root')
                    rows=tree.findall(ATOM+'entry')
            except (ValueError,TypeError,KeyError):
                issues.append(name+":unparseable_source_schema");continue
            global_supported=True
            try: parse_page(source,snap.data,req,selected)
            except EvidenceError as exc:
                global_supported=exc.code in ('conflicting_fpds_identifiers','unsupported_fpds_identifier_namespace')
            if len(rows)> (req['parameters']['limit'] if source=='usaspending' else 10):
                global_supported=False
            for index,row in enumerate(rows):
                if len(result)>=max_records: raise EvidenceError('scope_record_limit')
                locator=f'/results/{index}' if source=='usaspending' else f'/feed/entry[{index+1}]'
                ref=EvidenceRecordRef(source=source,artifact_id=artifact.artifact_id,locator=locator)
                evidence=MatchEvidenceReference(reference=ref,artifact=artifact,observation_id=observation,
                    metadata_paths=tuple(sorted((meta_name,'c3_plan.json','c3_checkpoint.json'))))
                known=entries[name].observation
                if known:
                    refs=[r.reference for r in known.records if r.reference.locator==locator]
                    if len(refs)==1:
                        evidence=MatchEvidenceReference(reference=refs[0],artifact=known.artifact,observation_id=known.observation_id,metadata_paths=known.metadata_paths)
                record=None
                content=digest(row) if source=='usaspending' else digest({'derived_entry_xml':ET.tostring(row,encoding='unicode')})
                try:
                    if not global_supported: raise EvidenceError('unsupported_scope_schema')
                    if source=='usaspending':
                        if not isinstance(row,dict): raise EvidenceError('unsupported_scope_record')
                        native=row
                    else:
                        derived=ET.Element(ATOM+'feed');derived.append(row)
                        raw=ET.tostring(derived,encoding='utf-8')
                        content=_check_fpds_contexts(raw)[0]
                        native=parse_page(source,raw,req,selected)['rows'][0]
                    record=identify(source,native,(evidence,),content)
                except (ValueError,KeyError,IndexError,TypeError):
                    pass
                result.append(assessment(requested,ObservedIdentity.from_record(record) if record else ObservedIdentity.missing(),
                    evidence,content,record=record,supported=record is not None,
                    original_identity_json=canonical({k:row[k] for k in ('id','modification_number') if k in row}) if isinstance(row,dict) else canonical({'derived_entry_xml':ET.tostring(row,encoding='unicode')}) if source=='fpds' else canonical({'unsupported_row':row})))
        for n,snap in inventory.items():
            if root.read(n,recheck=True).byte_sha256!=snap.byte_sha256:
                raise EvidenceError('scope_evidence_changed')
        if set(root.discover())!=set(inventory): raise EvidenceError('scope_inventory_changed')
    conflicts=conflicting_occurrences(result)
    result=[assessment(a.requested,a.observed,a.evidence,a.content_sha256,record=a.record,supported=a.supported,
        conflicting=a.assessment_id in conflicts,original_identity_json=a.original_identity_json) for a in result]
    return ScopeRun(requested=requested,input_manifest_sha256=scan.substantive_sha256,
        assessments=tuple(sorted(result,key=lambda a:a.assessment_id)),artifact_issues=tuple(sorted(issues)))


def scoped_match_collection(path,requested,*,limits=None):
    from .matching_models import MatchLimits
    from dataclasses import replace
    limits=limits or MatchLimits()
    scope=assess_collection(path,requested,max_records=limits.max_records)
    eligible=[a.record for a in scope.assessments if a.status is ScopeStatus.IN_SCOPE and a.record is not None]
    run=match_records(eligible,input_manifest_sha256=scope.input_manifest_sha256,limits=limits)
    return replace(run,limitations=run.limitations+("record-scope-v1:"+digest(requested.to_dict()),))
