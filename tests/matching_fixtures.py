"""Authored synthetic identity examples; no source data or network."""
from xml.sax.saxutils import escape

from src.collection_sources import FPDS, USA
from src.evidence import EvidenceArtifact, EvidenceRecordRef, Representation
from src.evidence_io import digest
from src.identity_matching import identify
from src.matching_models import MatchEvidenceReference


def usa_row(*, piid="SYNTH-00001", agency="0001", parent="SYNTH-PARENT", parent_agency="0002", mod="P00001", transaction="0", **extra):
    return {"id": f"CONT_TX_{agency}_{parent_agency}_{piid}_{mod}_{parent}_{transaction}",
            "modification_number": mod, "action_date": "2025-01-01", "federal_action_obligation": -20, **extra}


def fpds_row(*, piid="SYNTH-00001", agency="0001", parent="SYNTH-PARENT", parent_agency="0002", mod="P00001", transaction="0", parent_mod="0", **extra):
    return {"PIID": piid, "agencyID": agency, "modNumber": mod, "transactionNumber": transaction,
            "parent_context": [{"PIID": parent, "agencyID": parent_agency, "modNumber": parent_mod}], **extra}


def evidence(source, row, *, index=0, timestamp="2025-01-01T00:00:00Z"):
    sha = digest(row)
    a = EvidenceArtifact(source=source, relative_path=f"c3_attempt_{index:06d}.body", sha256=sha,
                         representation=Representation.RESPONSE_BYTES, hash_basis="original_bytes",
                         endpoint=USA if source == "usaspending" else FPDS,
                         method="POST" if source == "usaspending" else "GET", request_json="{}",
                         retrieved_at_utc=timestamp, http_status=200, limitations=("synthetic_fixture_only",))
    r = EvidenceRecordRef(source=source, artifact_id=a.artifact_id, locator=f"/synthetic/{index}")
    observation_id = "observation:v1:" + digest({"version": 1, "source": a.source, "endpoint": a.endpoint,
                     "method": a.method, "request_json": a.request_json, "retrieved_at_utc": a.retrieved_at_utc,
                     "representation": a.representation.value})
    return MatchEvidenceReference(reference=r, artifact=a, observation_id=observation_id,
                                  metadata_paths=(f"c3_attempt_{index:06d}.json", "c3_checkpoint.json", "c3_plan.json"))


def record(source="usaspending", row=None, **kw):
    row = row if row is not None else (usa_row() if source == "usaspending" else fpds_row())
    return identify(source, row, (evidence(source, row, **kw),), digest(row))


def entry(row):
    def tags(values):
        return "".join(f"<f:{k}>{escape(v)}</f:{k}>" for k, v in values.items() if v is not None)
    contract = {k: row.get(k) for k in ("agencyID", "PIID", "modNumber", "transactionNumber")}
    parent = "".join("<f:referencedIDVID>" + tags(p) + "</f:referencedIDVID>" for p in row.get("parent_context", []))
    return ("<entry><content><f:award><f:awardID><f:awardContractID>" + tags(contract)
            + "</f:awardContractID>" + parent + "</f:awardID></f:award></content></entry>")


def scenario(usa_rows=None, fpds_rows=None, *, more=False):
    return {"schema_version": 1, "responses": [
        {"source": "usaspending", "json": {"page_metadata": {"page": 1, "hasNext": more}, "results": usa_rows if usa_rows is not None else [usa_row()]}},
        {"source": "fpds", "text": '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:f="https://www.fpds.gov/FPDS">'
         + "".join(entry(r) for r in (fpds_rows if fpds_rows is not None else [fpds_row()])) + "</feed>"}]}
