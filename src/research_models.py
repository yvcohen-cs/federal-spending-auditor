"""C7 v1 research execution contracts; technical completion is not assurance."""
from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .collection import CollectionLimits, SelectedAward
from .evidence import Schema, _hash, _timestamp
from .evidence_io import canonical, digest, parts, strict_json
from .financial_models import FinancialLimits
from .matching_models import MatchLimits, _ComputedIdentity


STAGES = ("acquire", "verify", "identity", "finance", "packets", "summary")
PIPELINE_VERSION = "research-pipeline-v1"
RULES = ("evidence-schema-v1", "ingestion-v1", "collector-v2", "identity-v1",
         "field-semantics-v1", "financial-v1", "review-packet-v1")


MAX_IMPLEMENTATION_MODULES = 128


def implementation_digest():
    """Source compatibility fingerprint, not a signature or inferred git revision."""
    files = sorted(Path(__file__).parent.glob("*.py"))
    if not files or len(files)>MAX_IMPLEMENTATION_MODULES:
        raise ValueError("unsupported source installation")
    contents,total = [],0
    for p in files:
        if p.is_symlink():
            raise ValueError("unsupported source installation")
        with p.open("rb") as stream:
            raw=stream.read(8*1024*1024+1)
        total+=len(raw)
        if total>8*1024*1024:
            raise ValueError("implementation fingerprint size limit")
        contents.append((p.name,raw))
    return digest([(name,hashlib.sha256(raw).hexdigest()) for name,raw in contents])


class StageState(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True, kw_only=True)
class ResearchConfig(Schema):
    mode: str = "existing"
    collection: CollectionLimits = field(default_factory=CollectionLimits)
    matching: MatchLimits = field(default_factory=MatchLimits)
    financial: FinancialLimits = field(default_factory=FinancialLimits)
    selected_awards: tuple[SelectedAward, ...] = ()
    demo_cases: tuple[str, ...] = ()
    demo_damage: str | None = None
    claim_ids: tuple[str, ...] = ()
    max_claims: int = 100
    max_output_bytes: int = 8*1024*1024
    max_run_bytes: int = 256*1024*1024
    max_attempts: int = 5
    stage_order: tuple[str, ...] = STAGES
    pipeline_version: str = PIPELINE_VERSION
    implementation_sha256: str = field(default_factory=implementation_digest)

    def validate(self):
        _hash(self.implementation_sha256)
        if self.pipeline_version != PIPELINE_VERSION or self.stage_order != STAGES:
            raise ValueError("unsupported pipeline version or dependency ordering")
        if self.mode not in ("existing", "demo", "live"):
            raise ValueError("explicit research mode required")
        if not 1 <= self.max_claims <= 1000 or not 1024 <= self.max_output_bytes <= 32*1024*1024 or not 1024 <= self.max_run_bytes <= 512*1024*1024 or not 1 <= self.max_attempts <= 20:
            raise ValueError("unsupported research limits")
        if self.claim_ids != tuple(sorted(set(self.claim_ids))) or len(self.claim_ids) > self.max_claims:
            raise ValueError("claim selection must be bounded, unique and sorted")
        if self.mode == "live":
            if not self.selected_awards or len(self.selected_awards) > min(3, self.collection.max_awards):
                raise ValueError("explicit bounded live selections required")
            if (self.collection.max_pages > 5 or self.collection.max_requests > 30 or self.collection.max_records_total > 100
                    or self.collection.max_records_per_source_award > 50 or self.collection.page_size > 50 or self.collection.retries > 2):
                raise ValueError("live research limits exceed conservative C7 policy")
            for a in self.selected_awards:
                if any(v is None for v in (a.generated_id,a.piid,a.agency_id)) or (a.parent_piid is None) != (a.parent_agency_id is None):
                    raise ValueError("both source selections and paired parent context required")
        elif self.selected_awards:
            raise ValueError("live selections only in live mode")
        if self.mode != "demo" and (self.demo_cases or self.demo_damage):
            raise ValueError("synthetic configuration cannot enter another mode")
        if self.demo_damage not in (None,"missing","tampered"):
            raise ValueError("unsupported synthetic damage")


@dataclass(frozen=True, kw_only=True)
class ResearchInput(Schema):
    label: str
    evidence_sha256: str
    collection_plan_sha256: str | None
    selected_awards: tuple[SelectedAward, ...]
    query_scope_json: str
    profile: str
    location: str = field(metadata={"execution": True})

    def validate(self):
        if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}",self.label) is None:
            raise ValueError("bounded research input label required")
        _hash(self.evidence_sha256)
        if self.collection_plan_sha256 is not None:
            _hash(self.collection_plan_sha256)
        if canonical(strict_json(self.query_scope_json.encode())) != self.query_scope_json or self.profile not in ("live","synthetic","unknown"):
            raise ValueError("unsupported research input scope")


@dataclass(frozen=True, kw_only=True)
class ResearchArtifact(Schema):
    name: str
    sha256: str
    byte_count: int
    storage_path: str = field(metadata={"execution": True})

    def validate(self):
        parts(self.name); parts(self.storage_path); _hash(self.sha256)
        if self.byte_count < 0:
            raise ValueError("invalid artifact size")


@dataclass(frozen=True, kw_only=True)
class ResearchDiagnostic(Schema):
    stage: str
    category: str
    code: str

    def validate(self):
        if self.stage not in STAGES or self.category not in ("collection","network","parsing","integrity","identity","financial","reporting","storage","configuration","interrupted","internal"):
            raise ValueError("unsupported diagnostic category")
        if re.fullmatch(r"[a-z0-9_]{1,100}",self.code) is None:
            raise ValueError("sanitized fixed diagnostic code required")


@dataclass(frozen=True, kw_only=True)
class ResearchStage(Schema):
    stage: str
    state: StageState
    input_sha256: str
    artifacts: tuple[ResearchArtifact, ...] = ()
    diagnostic: ResearchDiagnostic | None = None

    def validate(self):
        if self.stage not in STAGES:
            raise ValueError("unknown stage")
        _hash(self.input_sha256)
        if self.state is StageState.COMPLETED and (not self.artifacts or self.diagnostic is not None):
            raise ValueError("completed stage requires committed outputs")
        if self.state is not StageState.COMPLETED and self.artifacts:
            raise ValueError("incomplete outputs cannot become committed artifacts")
        if self.state is StageState.FAILED and self.diagnostic is None:
            raise ValueError("failed stage needs explicit diagnostic")
        if self.diagnostic is not None and self.diagnostic.stage!=self.stage:
            raise ValueError("diagnostic stage conflict")
        names = [a.name for a in self.artifacts]
        if names != sorted(set(names)) or len({a.storage_path for a in self.artifacts}) != len(self.artifacts):
            raise ValueError("unique canonical stage output references required")


@dataclass(frozen=True, kw_only=True)
class QualityGate(Schema):
    name: str
    state: str
    detail: str

    def validate(self):
        if self.state not in ("passed","failed","unknown"):
            raise ValueError("unsupported gate state")


@dataclass(frozen=True, kw_only=True)
class ResearchRun(_ComputedIdentity):
    _computed_name = "run_id"
    config: ResearchConfig
    inputs: tuple[ResearchInput, ...]
    stages: tuple[ResearchStage, ...]
    metrics_json: str
    quality_gates: tuple[QualityGate, ...]
    rules: tuple[str, ...] = RULES
    executed_at_utc: str | None = field(default=None, metadata={"execution": True})

    @property
    def run_id(self):
        return "research-run:v1:" + digest({"config":self.config.to_dict(),"inputs":[i.to_dict(substantive=True) for i in self.inputs],"rules":self.rules})

    def validate(self):
        _timestamp(self.executed_at_utc)
        if self.rules != RULES or tuple(s.stage for s in self.stages) != STAGES:
            raise ValueError("incompatible research rules/stages")
        if len({i.label for i in self.inputs}) != len(self.inputs):
            raise ValueError("duplicate research inputs")
        seen_incomplete = False
        for s in self.stages:
            if not seen_incomplete and s.state is StageState.BLOCKED:
                raise ValueError("blocked stage requires a failed dependency")
            if seen_incomplete and s.state is not StageState.BLOCKED:
                raise ValueError("a stage cannot run past a failed dependency")
            if s.state is not StageState.COMPLETED:
                seen_incomplete = True
        metrics = strict_json(self.metrics_json.encode())
        if not isinstance(metrics,dict) or canonical(metrics) != self.metrics_json:
            raise ValueError("canonical metrics required")
        for key,value in metrics.items():
            if key in ("identity_counts","financial_counts","evidence_validation"):
                if not isinstance(value,dict) or any(type(v) is not int or v<0 for v in value.values()):
                    raise ValueError("strict nonnegative metric counts required")
            elif key=="source_diagnostics":
                if not isinstance(value,list) or len(value)>100:
                    raise ValueError("bounded diagnostics required")
                for d in value:
                    ResearchDiagnostic.from_dict(d)
            elif type(value) is not int or value<0:
                raise ValueError("strict nonnegative metric counts required")
        from .research_summary import quality_gates
        if self.quality_gates != quality_gates(self.stages,metrics):
            raise ValueError("quality gates contradict observed results")

    @property
    def technical_success(self):
        return all(s.state is StageState.COMPLETED for s in self.stages)

    @property
    def evidentiary_complete(self):
        return bool(self.quality_gates) and all(g.state == "passed" for g in self.quality_gates)

    @property
    def substantive_sha256(self):
        return digest(self.to_dict(substantive=True))

    @property
    def exit_code(self):
        if any(s.diagnostic and s.diagnostic.category == "interrupted" for s in self.stages):
            return 130
        if not self.technical_success:
            return 2
        return 0 if all(g.state == "passed" for g in self.quality_gates if g.name not in ("historical_completeness","source_freshness","source_authenticity")) else 1
