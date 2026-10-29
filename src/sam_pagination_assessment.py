"""Independent, offline SAM pagination hypotheses; never authorizes collection."""
from dataclasses import dataclass
from enum import Enum

from .evidence import Schema, _hash
from .evidence_io import canonical
from .sam_validation_models import counter


class Interpretation(str, Enum):
    PAGE_INDEX = 'page_index'
    RECORD_OFFSET = 'record_offset'
    UNRESOLVED = 'unresolved'
    CONTRADICTORY = 'contradictory_response_metadata'
    INCOMPLETE = 'incomplete_or_interrupted_capture'


@dataclass(frozen=True, kw_only=True)
class PaginationObservation(Schema):
    """Parsed counters retain original JSON types; hashes identify content only."""
    submitted_parameters_json: str
    response_counters_json: str | None
    record_content_sha256: tuple[str, ...]
    http_status: int | None
    response_complete: bool
    error: bool

    def validate(self):
        from .evidence_io import strict_json
        params = strict_json(self.submitted_parameters_json.encode())
        if not isinstance(params, dict) or canonical(params) != self.submitted_parameters_json:
            raise ValueError('canonical_submitted_parameters_required')
        if self.response_counters_json is not None:
            value = strict_json(self.response_counters_json.encode())
            if not isinstance(value, dict) or canonical(value) != self.response_counters_json:
                raise ValueError('canonical_response_counters_required')
        if self.http_status is not None and not 100 <= self.http_status <= 599:
            raise ValueError('invalid_http_status')
        for sha in self.record_content_sha256:
            _hash(sha)
        if len(self.record_content_sha256) > 10:
            raise ValueError('pagination_record_bound')


def assess(observations, *, profile, interrupted=False):
    """Two zero-origin hypotheses, not an API contract or query-recall proof.

    Exact request/response metadata is emitted alongside the assessment. Unknown
    counter keys/types are contradictory. Duplicate content blocks completeness;
    hashes never stand in for native action identity. Two pages cannot prove
    stable ordering, snapshot isolation, complete history or freshness.
    """
    from .evidence_io import strict_json
    if profile not in ('synthetic', 'live', 'offline_no_capture') or type(interrupted) is not bool:
        raise ValueError('explicit_pagination_evidence_profile_required')
    if len(observations) > 2:
        raise ValueError('two_page_assessment_bound')
    issues = set(); parsed = []; seen = set()
    incomplete = interrupted
    for observation in observations:
        if not isinstance(observation, PaginationObservation):
            raise TypeError('typed_pagination_observation_required')
        params = strict_json(observation.submitted_parameters_json.encode())
        if (observation.error or not observation.response_complete or observation.http_status is None
                or not 200 <= observation.http_status < 300 or observation.response_counters_json is None):
            incomplete = True
            issues.add('response_unavailable_failed_or_unparsed')
            continue
        counters = strict_json(observation.response_counters_json.encode())
        try:
            if set(counters) != {'offset', 'limit', 'totalRecords'}:
                raise ValueError('counter_fields')
            offset, limit, total = (counter(counters[k]) for k in ('offset', 'limit', 'totalRecords'))
            submitted_offset, submitted_limit = (counter(params[k]) for k in ('offset', 'limit'))
            if not 1 <= limit <= 10 or (offset, limit) != (submitted_offset, submitted_limit):
                raise ValueError('counter_request_conflict')
            n = len(observation.record_content_sha256)
            if n > limit or n > total:
                raise ValueError('record_count_conflict')
        except (ValueError, TypeError, KeyError):
            issues.add('invalid_or_conflicting_counters')
            continue
        contents = observation.record_content_sha256
        if len(set(contents)) != len(contents) or seen.intersection(contents):
            issues.add('duplicate_or_overlapping_content')
        seen.update(contents)
        if parsed and total != parsed[0][2]:
            issues.add('changing_totalRecords')
        if parsed and limit != parsed[0][1]:
            issues.add('changing_limit')
        parsed.append((offset, limit, total, n))
    candidates = []
    terminal = {}
    for rule in (Interpretation.PAGE_INDEX, Interpretation.RECORD_OFFSET):
        valid = bool(parsed) and parsed[0][0] == 0
        previous = None
        for offset, limit, total, n in parsed:
            start = offset * limit if rule is Interpretation.PAGE_INDEX else offset
            if start + n > total or not n and start < total:
                valid = False
            if previous is not None:
                po, pl, pt, pn = previous
                expected = po + (1 if rule is Interpretation.PAGE_INDEX else pl)
                previous_start = po * pl if rule is Interpretation.PAGE_INDEX else po
                if offset != expected or pn < pl or previous_start + pn >= pt:
                    valid = False
            previous = (offset, limit, total, n)
        if valid:
            candidates.append(rule.value)
            o, l, t, n = parsed[-1]
            terminal[rule.value] = (o*l if rule is Interpretation.PAGE_INDEX else o) + n == t
    if parsed and not candidates:
        issues.add('neither_zero_origin_hypothesis_consistent')
    state = Interpretation.UNRESOLVED
    if issues - {'response_unavailable_failed_or_unparsed'}:
        state = Interpretation.CONTRADICTORY
    elif incomplete:
        state = Interpretation.INCOMPLETE
    elif len(candidates) == 1:
        state = Interpretation(candidates[0])
    if not observations:
        issues.add('no_page_observations')
    if len(candidates) > 1:
        issues.add('hypotheses_not_distinguishable')
    if parsed and len(parsed) == 1 and not parsed[0][3]:
        issues.add('empty_feed_inconclusive_query_support_and_scope_unverified')
    complete = None
    # Even coherent authenticated observations cannot override the frozen live
    # contract. Only synthetic fixtures can demonstrate bounded completion here.
    if (profile == 'synthetic' and state in (Interpretation.PAGE_INDEX, Interpretation.RECORD_OFFSET)
            and terminal.get(state.value) and not issues):
        complete = True
    if parsed and not all(terminal.values()) and candidates:
        issues.add('nonterminal_page_limit_or_partial_history')
    return {'schema_type': 'SAMPaginationAssessment', 'schema_version': 1,
        'interpretation': state.value, 'evidence_basis': 'SYNTHETIC_ONLY' if profile == 'synthetic' else
            'AUTHENTICATED_OBSERVED' if profile == 'live' and any(
                o.http_status is not None and 200 <= o.http_status < 300 and o.response_complete and not o.error
                for o in observations) else 'UNKNOWN',
        'compatible_hypotheses': candidates, 'hypothetical_terminal': terminal,
        'bounded_query_pagination_complete': complete,
        'transaction_history_complete': 'unknown', 'source_wide_complete': 'unknown', 'freshness': 'unknown',
        'live_continuation_authorized': False, 'issues': sorted(issues),
        'observations': [o.to_dict() for o in observations]}
