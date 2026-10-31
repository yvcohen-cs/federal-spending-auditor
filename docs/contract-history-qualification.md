# Phase 4C10: evidence-gap resolution and contract-history qualification

This opt-in offline engine advances C9 diagnostics into source-local histories, ten independent evidence requirements, and deterministic resolution plans. It has no collector or financial/readiness integration. Previous reports and frozen protocols remain unchanged.

## Reconstruction and evidence quality

`src.history_qualification` revalidates primary C3 USAspending/FPDS collections and C2 SAM captures through the existing adapters. Inventories are pinned before and after the independent passes. Serialized C9 conclusions are never accepted as primary evidence. No network calls, credential reads, financial arithmetic, participant operations, or production screening are added.

A source-local contract groups exact native PIID, identity agency, parent context, and namespace. Missing native context isolates occurrences; it never creates a partial-key identity match. FPDS's existing narrow 1.4/1.5 definitive-contract rule can establish parent non-applicability. It cannot establish the same for USAspending or SAM. A delivery-order child reference is distinguished from a separately observed, authoritative parent IDV record: the latter remains an unresolved proof obligation. Raw parent fields can support an observed context group without certifying the relationship. Unsupported instruments remain unclassified.

Actions retain original modifications and transaction identifiers, including leading zeros and punctuation. Duplicate occurrences remain present and are distinguished from content variants. Reused source-native record IDs with incompatible contexts remain ambiguous bindings requiring validated identifier/revision semantics, with every affected primary citation retained. They do not by themselves establish contradictory source evidence. Different content at one action may reflect a correction, deletion/reinstatement, or revision; no winner or supersession direction is inferred. No missing modification is inferred from a numbering gap. Historical ordering shows UTC retrieval time and local sequence only, separately from original source temporal fields. It never orders authoritative revisions by modification labels, amounts, timestamps, or content hashes.

SAM native award class, instrument and action fields remain separate. Captured native modification contexts can be grouped without treating document versions as revision certificates. Input inventory plus original claim ID constructs an occurrence ID; this is explicitly not a source-native record ID. SAM pagination contradictions are bound to the exact subject request and capture. Its two pagination hypotheses do not become a live API contract. No SAM-to-FPDS/USAspending crosswalk is inferred. Existing complete-component USAspending/FPDS counterpart candidates can be cited as observed counterparts; their common revision remains unproven.

Each source-local contract evaluates native identity, parent identity, source completeness, revision completeness, monetary semantics, as-of alignment, currency/amount compatibility, observed counterpart coverage, provenance integrity, and freshness independently. States are `QUALIFIED_EVIDENCE`, `INSUFFICIENT_EVIDENCE`, `CONFLICTING_EVIDENCE`, and `NOT_EVALUATED`. Missing evidence and contradictory observations have different typed evidence kinds. Unknown SAM monetary mappings are not evaluated. Negative and zero obligations are ordinary supported observations. Cumulative award amounts cannot substitute for missing action obligations; unsupported precision is never rounded. Content variants are not automatically parent contradictions: the engine independently assesses each occurrence's parent fields while retaining the original pooled scope result. Records demonstrably outside the requested native context are not evaluated for that context, rather than counted as source contradictions. Internal incompatible identifier fields remain genuinely conflicting observations. Conflicting amount observations remain alternatives pending revision resolution, not allegations.

The overall evidence state is conflicting if any requirement conflicts, otherwise insufficient if any is missing, otherwise not evaluated if any is not evaluated, and qualified only if every required dimension qualifies. This is a logical evidence classification, never a confidence score or permission for arithmetic. Current adapters cannot establish complete source history, revision lineage, freshness, or common as-of visibility; current real captures therefore cannot achieve overall qualification. Positive narrow requirements remain useful and independently cited. Even an all-qualified synthetic model cannot set `financial_comparison_authorized` true.

## Resolution plans and schema

Version 1 uses standard-library dataclasses/enums: `HistoricalInterval`, `ProofRequirement`, `ContractQualification`, and `EvidenceResolutionPlan`. Strict schema readback rejects unknown versions, missing/duplicate dimensions, inconsistent status/evidence kinds, unauthorized flags, and contradictory aggregate results.

Every unresolved contract requirement has exactly one hash-identified plan containing its source(s), preserved native contract and observed action identifiers, requested historical interval/as-of scope, exact missing observation, official documentation dependencies, verification procedure, expected primary artifact, and stop condition. Missing scope dates remain null. Requested dates are not observed coverage. Counterpart plans identify FPDS and USAspending separately; SAM has no implicit target mapping. No plan executes collection, expands entitlement, or fabricates an unobserved identifier.

Documentation links are dependencies inherited from earlier source/financial research, not claims of current endpoint availability or validated query behavior. The next investigator must establish document version, field semantics, query support, authorized scope and applicable historical bounds before obtaining separately preserved evidence. Failure to establish these is a stop condition.

`ContractHistoryQualificationReport` has schema version 1 and rule `contract-history-qualification-v1`. It includes source-local contract requirements, original evidence citations, all observed actions, history limitations, source and pagination observations, deterministic gap triage, and resolution plans. Unavailable SAM captures retain explicit blockers and no positive contract claims. Reports distinguish observed subsets from full histories and absence from non-observation.

## Offline use and verification

```sh
python -m src.history_qualification_reporting \
  --collection /path/to/preserved-c3-capture --scope /path/to/scope.json \
  --history-start 2024-01-01 --history-end 2024-12-31 --as-of 2025-01-01 \
  --output /path/to/new-qualification-report

python -m src.history_qualification_reporting \
  --collection /path/to/preserved-c3-capture --scope /path/to/scope.json \
  --history-start 2024-01-01 --history-end 2024-12-31 --as-of 2025-01-01 \
  --verify-report /path/to/new-qualification-report
```

Dates above are an example requested scope, not a claim about any source's history. Omit them to retain unknown scope. Repeat `--collection` at most eight times, or `--sam-capture` at most three times; SAM-only use needs no C3 scope. A scope JSON uses the existing `ScopeRequest.to_dict()` schema. Cohort/profile restrictions are inherited from C9. There is no live mode.

Outputs: `qualification.json`, `qualification.md`, escaped static `qualification.html`, a plan, and a last-written commit manifest. Existing output directories, source-nested outputs, symlinks/hardlinks, altered captures and incomplete report bundles fail closed. Output hashes, history/action summaries, triage, plan references, qualification requirements and citation closure are checked on readback. Primary `--verify-report` replay is required to trust substantive claims. Local checksums and internally consistent serialized observations cannot establish independent source authenticity; a writer capable of replacing a complete bundle can recompute its hashes.

Tests use authored synthetic controls and opt-in read-only evaluation of permitted preserved captures. They do not validate current live APIs. Remaining priorities are authoritative parent-IDV captures, native revision/correction/deletion lineage, documented historical coverage/query recall, source-specific monetary mappings and common as-of proof. No existing financial eligibility or production readiness decision is upgraded.
