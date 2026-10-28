"""Deterministic research projection using C6 citations/actions; no note store."""
from html import escape
import json
from datetime import datetime

from .evidence_io import EvidenceError, digest
from .history_models import HistoricalStatus, Alignment, HistoryVerificationRun
from .history_rules import native_key
from .pilot_evaluation import rate
from .review_packet_models import EvidenceCitation, EvidenceLimitation, RecommendedVerificationAction
from .matching_models import ordered


def metrics(run):
    obs=run.observations
    contents={(o.scope_assessment.evidence.reference.source,o.scope_assessment.content_sha256) for o in obs}
    source_counts={s:sum(o.scope_assessment.evidence.reference.source==s for o in obs) for s in ('usaspending','fpds')}
    statuses={s.value:sum(c.status is s for c in run.comparisons) for s in HistoricalStatus}
    known_states={(o.scope_assessment.evidence.reference.source,native_key(o) or ('unresolved_observation',o.history_observation_id),t.path,t.original_json) for o in obs for t in o.revision.update_markers if t.parsed is not None}
    return {'version':'history-metrics-v1','returned_record_occurrences':len(obs),'by_source_occurrences':source_counts,
        'verified_in_scope_occurrences':sum(o.eligible for o in obs),'scope_uncertain_occurrences':sum(not o.eligible for o in obs),
        'awards_with_eligible_observed_actions':int(any(o.action_key is not None for o in obs)),
        'distinct_eligible_action_identities':len({o.action_key for o in obs if o.action_key is not None}),
        'distinct_eligible_modifications':len({o.modification.native for o in obs if o.eligible and o.modification.native is not None}),
        'distinct_source_record_contents':len(contents),'duplicate_record_occurrences':len(obs)-len(contents),
        'retrieval_observations':len({o.scope_assessment.evidence.observation_id for o in obs}),
        'declared_update_states':len(known_states),'known_certified_cross_source_revisions':0,
        'revision_relationships':{s.value:sum(c.alignment is not None and c.alignment.status is s for c in run.comparisons) for s in Alignment},
        'financial_results':statuses,'financial_comparison_denominator':len(run.comparisons),
        'authorized_numeric_comparisons':sum(c.difference_left_minus_right is not None for c in run.comparisons),
        'revision_uncertainty_withheld':statuses[HistoricalStatus.REVISION_UNKNOWN.value],
        'scope_uncertainty_withheld':statuses[HistoricalStatus.SCOPE_UNCERTAIN.value],
        'content_freshness_known':0,'content_freshness_unknown':len(obs),'freshness_denominator':len(obs),
        'historical_completeness_known':0,'historical_completeness_unknown':len(run.coverage),'coverage_denominator':len(run.coverage),
        'authorized_comparison_fraction':rate(sum(c.difference_left_minus_right is not None for c in run.comparisons),len(run.comparisons)),
        'newly_authorized_live_cross_source_comparisons':0,
        'unit':'bounded_observed_record_pairs_not_population_actions_or_contract_totals'}


def research_report(run):
    # Typed readback recomputes outcomes before a report can project them.
    run=HistoryVerificationRun.from_dict(run.to_dict())
    citations=ordered(EvidenceCitation(evidence=o.scope_assessment.evidence) for o in run.observations)
    ids=tuple(c.citation_id for c in citations)
    limitations=(EvidenceLimitation(code='observed_subset',detail='Bounded observed actions only; no complete history, missing-action gap rule or financial total.',citation_ids=ids),
        EvidenceLimitation(code='revision_and_freshness',detail='Retrieval and declared update times do not certify source synchronization, correction precedence or current content.',citation_ids=ids),
        EvidenceLimitation(code='claim_boundary',detail='Observed agreements and differences are narrow evidence statements; neither establishes financial correctness or misconduct.',citation_ids=ids))
    actions=(RecommendedVerificationAction(instruction='Obtain authoritative source-native revision linkage and publication/update criteria before comparing cross-source monetary vintages.',citation_ids=ids),
        RecommendedVerificationAction(instruction='Resolve excluded identity contexts and missing action evidence; preserve earlier snapshots and examine official corrections without inventing a modification sequence.',citation_ids=ids))
    def observed_order(o):
        stamp=o.freshness.retrieved_at_utc
        return (o.scope_assessment.evidence.reference.source,stamp is not None,datetime.fromisoformat(stamp.replace('Z','+00:00')) if stamp else None,
            o.input_manifest_sha256,o.retrieval_sequence,o.source_page,o.scope_assessment.evidence.reference.locator)
    timeline=sorted(run.observations,key=observed_order)
    return {'schema_type':'HistoricalResearchReport','schema_version':1,'run':run.to_dict(substantive=True),'metrics':metrics(run),
        'observed_timeline':[{'observation_id':o.history_observation_id,'source':o.scope_assessment.evidence.reference.source,
            'eligible_for_grouping':o.eligible and o.action_key is not None,'modification':o.modification.to_dict(),
            'temporal_fields':[t.to_dict() for t in o.freshness.temporal_fields],
            'retrieval_sequence':o.retrieval_sequence,'source_page':o.source_page,
            'citation_id':EvidenceCitation(evidence=o.scope_assessment.evidence).citation_id} for o in timeline],
        'ordering_basis':'source_then_observed_retrieval_time_and_journal_order_not_authoritative_action_sequence',
        'citations':[c.to_dict() for c in citations],'limitations':[l.to_dict() for l in limitations],
        'contradictions_requiring_verification':sorted({o.history_observation_id for o in run.observations if o.issues}|
            {o.history_observation_id for c in run.comparisons if c.context_conflict for o in (c.left,c.right) if o is not None}),
        'unresolved_questions':['What primary evidence establishes a common source revision?',
            'Does a source expose complete corrections/deletions or only the currently visible record?',
            'What authoritative rule could establish freshness or full action coverage for this subset?'],
        'recommended_actions':[a.to_dict() for a in actions],
        'review_boundary':'Read-only historical supplement; C6 packets and reviewer events retain their existing separate workflow. No reviewer assertions are created.'}


def bounded_json(value,max_bytes=32*1024*1024):
    chunks=[];size=0
    for chunk in json.JSONEncoder(sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).iterencode(value):
        encoded=chunk.encode();size+=len(encoded)
        if size>max_bytes: raise EvidenceError('history_report_byte_limit')
        chunks.append(encoded)
    return b''.join(chunks)+b'\n'


def render_text(report):
    run=report['run'];lines=['Observed contract action history (history-v1)',
        'Requested native identity: '+json.dumps(run['scope']['requested'],sort_keys=True),
        'Ordering is observed retrieval order, not a complete historical sequence.',
        'Financial comparisons:']
    for c in run['comparisons']:
        a=c['left']['modification'];right=c['right']
        lines.append(f"{c['claim_id']}: modification={a['native']!r} transaction={a['transaction']!r}; {c['status']}; delta={c['difference_left_minus_right']!r}; reasons={','.join(c['reasons'])}")
        if c['alignment']: lines.append('Revision alignment: '+c['alignment']['status']+'; '+c['alignment']['reason'])
        for side in ('left','right'):
            o=c[side]
            if o is None: continue
            for money in o['money']:
                m=money['observation']
                if m['original_field']==c[side+'_field']:
                    lines.append(side+' value: '+json.dumps({'source':m['source'],'field':m['original_field'],'value':m['value'],'semantics':m['semantics'],'signed_date_raw':m['action_date_raw']},sort_keys=True))
    lines.append('Coverage: '+json.dumps(run['coverage'],sort_keys=True))
    lines.append('Metrics: '+json.dumps(report['metrics'],sort_keys=True))
    for row in report['observed_timeline']: lines.append('Observed action: '+json.dumps(row,sort_keys=True))
    for c in report['citations']:
        e=c['evidence'];a=e['artifact'];r=e['reference']
        lines.append('Primary evidence: '+json.dumps({'citation_id':c['citation_id'],'source':r['source'],'body_sha256':a['sha256'],
            'path':a['relative_path'],'locator':r['locator'],'retrieved_at_utc':a['retrieved_at_utc'],'source_record_url':r.get('source_record_url')},sort_keys=True))
    for q in report['unresolved_questions']: lines.append('Unresolved: '+q)
    for a in report['recommended_actions']: lines.append('Next verification: '+a['instruction'])
    lines.append('Full primary evidence references and exact source values are in history.json. No financial total, freshness certification or misconduct assertion.')
    return '\n'.join(lines)+'\n'


def render_html(report):
    # No scripts, dynamic URLs, remote assets or unescaped native/source text.
    return '<!doctype html><meta charset="utf-8"><title>Observed action history</title><h1>Observed action history</h1><pre>'+escape(render_text(report))+'</pre>'
