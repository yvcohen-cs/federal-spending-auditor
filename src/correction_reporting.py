"""C14 opt-in primary replay: directed claims and parent records, never finance."""
import argparse
from html import escape
from pathlib import Path

from .award_validation import snapshot
from .collection_sources import ATOM, FPDS_NAMESPACES
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, safe_xml, strict_json
from .historical_lineage_reporting import report as c13_report
from .history_qualification import requirement, QualificationStatus
from .identity_matching import decode_usa_id
from .parent_history_probe import collect as collect_parent, read as read_parent, ParentEvidenceState
from .pilot_store import PilotStore
from .review_packet_io import outside
from .revision_authority import directed_graph, statement_from_row
from .revision_lineage import LineageObservation, native

RULE = 'correction-parent-evidence-v1'


def _recipe(cases):
    if type(cases) not in (list, tuple) or not 1 <= len(cases) <= 24:
        raise EvidenceError('bounded_C14_case_recipe_required')
    allowed = {'collections', 'sam_captures', 'scope', 'interval', 'report',
        'c12_capture', 'historical_probe', 'comparison_interval', 'parent_history'}
    if any(type(c) is not dict or set(c) - allowed or c.get('parent_history') and not c.get('c12_capture') for c in cases):
        raise EvidenceError('supported_C14_recipe_and_anchor_required')
    return tuple(cases)


def _paths(case):
    return list(case.get('collections', ())) + list(case.get('sam_captures', ())) + [
        case[k] for k in ('c12_capture', 'historical_probe', 'parent_history') if case.get(k)]


def _original_row(node, case):
    """Resolve the existing exact source locator; no hash-to-entity lookup."""
    citation = strict_json(node.citation_json.encode())
    role = citation['input_role']
    if role == 'C13_reverse_probe':
        path = case['historical_probe']
        filename, sha, locator = citation['body_file'], citation['body_sha256'], citation['locator']
    else:
        if role == 'original_C10_primary':
            paths = list(case.get('collections', ())) + list(case.get('sam_captures', ()))
        elif role == 'prior_C12_primary':
            paths = [str(Path(case['c12_capture']) / 'transactions')]
        else:
            raise EvidenceError('unsupported_original_observation_role')
        path = paths[citation['input_index']]
        original = citation['original_reference']
        filename, sha = original['artifact']['relative_path'], original['artifact']['sha256']
        locator = original['reference']['locator']
    with EvidenceRoot(path) as root:
        body = root.read(filename)
        if body.byte_sha256 != sha:
            raise EvidenceError('C14_original_body_hash_conflict')
        if node.source == 'usaspending':
            if not locator.startswith('/results/') or not locator[9:].isascii() or not locator[9:].isdigit():
                raise EvidenceError('unsupported_USA_original_locator')
            row = strict_json(body.data)['results'][int(locator[9:])]
            if digest(row) != node.content_sha256 or row.get('id') != node.native_action_id:
                raise EvidenceError('C14_original_row_binding_conflict')
        elif node.source == 'fpds':
            if not locator.startswith('/feed/entry[') or not locator.endswith(']') or not locator[12:-1].isdigit():
                raise EvidenceError('unsupported_FPDS_original_locator')
            row = safe_xml(body.data)[1].findall(ATOM + 'entry')[int(locator[12:-1]) - 1]
        else:
            raise EvidenceError('SAM_uses_existing_native_field_citations')
        root.read(filename, recheck=True)
    return row


def _parent_modification(node, case):
    if node.source != 'fpds':
        return None
    row = _original_row(node, case)
    awards = [a for c in row.findall(ATOM + 'content') for a in c
        if a.tag in tuple('{' + ns + '}award' for ns in FPDS_NAMESPACES)]
    if len(awards) != 1:
        return None
    a = awards[0]
    ns = a.tag.split('}')[0] + '}'
    parents = a.findall(ns + 'awardID/' + ns + 'referencedIDVID')
    fields = parents[0].findall(ns + 'modNumber') if len(parents) == 1 else []
    if len(fields) != 1 or len(fields[0]) or fields[0].attrib or not fields[0].text:
        return None
    return fields[0].text


def _parent_assessments(nodes, case, old, probe):
    old_by_id = {p['node_id']: p for p in old['parent_relationships']}
    results = []
    for node in nodes:
        context = native(node)
        asserted = node.identity_supported and not node.outside_requested_context and all(
            context[k] is not None for k in ('parent_piid', 'parent_agency'))
        selected = None if probe is None else probe['selection']
        exact = bool(asserted and selected and (context['parent_piid'], context['parent_agency']) ==
            (selected['piid'], selected['agency_id']))
        # A cross-source parent pair is not a verified native action crosswalk.
        reassessment = None if probe is None else probe['record_reassessment']
        located = bool(exact and node.source == 'usaspending' and reassessment['records'] and not reassessment['failures'])
        records = reassessment['records'] if exact and not reassessment['failures'] else []
        parent_mod = _parent_modification(node, case)
        candidates = [r for r in records if r['row']['modification_number'] == parent_mod] if parent_mod is not None else []
        states = []
        if old_by_id[node.node_id]['current_source_parent_primary_supported']:
            states.append(ParentEvidenceState.CURRENT.value)
        if asserted:
            states.append(ParentEvidenceState.ASSERTED.value)
        if located:
            states.append(ParentEvidenceState.LOCATED.value)
        states.append(ParentEvidenceState.UNRESOLVED.value)
        results.append({'node_id': node.node_id, 'source': node.source, 'native_action_id': node.native_action_id,
            'native_parent_pair': [context['parent_piid'], context['parent_agency']], 'states': states,
            'child_citation': strict_json(node.citation_json.encode()),
            'current_parent_citations': old_by_id[node.node_id]['current_primary_citations'],
            'new_parent_record_citations': [r['citation'] for r in records] if located else [],
            'parent_action_modification_asserted': parent_mod,
            'cross_source_exact_parent_modification_candidates': candidates,
            'cross_source_parent_action_identity_established': False,
            'historical_parent_applicability_established': False,
            'remaining_dependencies': ['parent_effective_interval_and_revision_authority_missing',
                'record_action_date_not_applicability_or_snapshot_certificate'],
            'financial_comparison_authorized': False})
    return results


def report(cases):
    cases = _recipe(cases)
    inventories = [{p: {n: s.byte_sha256 for n, s in snapshot(p).items()} for p in _paths(c)} for c in cases]
    base = c13_report([{k: v for k, v in c.items() if k != 'parent_history'} for c in cases])
    assessed, new_records, partial_plans, resolved = [], set(), set(), set()
    for index, (case, old) in enumerate(zip(cases, base['cases'])):
        nodes = [LineageObservation.from_dict({k: v for k, v in n.items() if k != 'node_id'}) for n in old['graph']['nodes']]
        statements, unsupported = [], []
        for node in nodes:
            if node.source == 'usaspending':
                row = _original_row(node, case)
                statement = statement_from_row(node, row)
                if statement is not None:
                    statements.append(statement)
            elif node.source == 'samgov':
                fields = [m for m in strict_json(node.update_metadata_json.encode()) if m.get('meaning') == 'prior_identifier_context']
                if fields:
                    unsupported.append({'node_id': node.node_id, 'native_fields': fields,
                        'citation': strict_json(node.citation_json.encode()),
                        'reason': 'oldContractId_documents_old_identifiers_not_correction_precedence'})
        directed = directed_graph(nodes, statements)
        probe = read_parent(case['parent_history'], case['c12_capture']) if case.get('parent_history') else None
        if probe is not None and probe['profile'] != old['profile']:
            raise EvidenceError('parent_history_profile_conflict')
        parents = _parent_assessments(nodes, case, old, probe)
        located_nodes = {p['node_id'] for p in parents if p['new_parent_record_citations']}
        impacts = []
        for p in old['original_requirement_impacts']:
            context = p['native_context']
            matching = sorted(n.node_id for n in nodes if n.source == 'usaspending'
                and n.node_id in located_nodes and all(native(n).get(k) == context.get(k)
                    for k in ('piid', 'agency', 'parent_piid', 'parent_agency')))
            supported = p['dimension'] == 'parent_identity' and p['original_requirement']['status'] == 'INSUFFICIENT_EVIDENCE' and p['original_requirement'].get('evidence_kind') == 'missing_evidence' and bool(matching) and context.get('namespace') == 'usaspending'
            if supported:
                partial_plans.add(p['original_plan_id'])
            # Resolve only C10's exact missing-parent-primary obligation. Its
            # original definition is parent award identity/existence, not an
            # effective interval, revision certificate or monetary authority.
            originals = [n for n in nodes if n.source == 'usaspending'
                and strict_json(n.citation_json.encode())['input_role'] == 'original_C10_primary'
                and all(native(n).get(k) == context.get(k)
                    for k in ('piid', 'agency', 'parent_piid', 'parent_agency'))]
            by_node = {a['node_id']: a for a in parents}
            complete_parent_primary = bool(supported and originals
                and p['original_requirement']['reasons'] == ['parent_award_primary_record_not_observed']
                and all(n.existing_native_scope_verified and n.node_id in located_nodes
                    and by_node[n.node_id]['current_parent_citations'] for n in originals))
            updated = p['original_requirement']
            primary_refs = []
            if complete_parent_primary:
                for n in originals:
                    a = by_node[n.node_id]
                    primary_refs.append({'child_node_id': n.node_id, 'child_citation': a['child_citation'],
                        'current_parent_primary_citations': a['current_parent_citations'],
                        'parent_action_primary_citations': a['new_parent_record_citations']})
                new_citations = ['parent-record:v2:' + digest(c) for c in primary_refs]
                updated = requirement('parent_identity', QualificationStatus.QUALIFIED,
                    ('exact_USA_parent_IDV_primary_identity_observed_not_historical_applicability',),
                    tuple(p['original_requirement']['citation_ids']) + tuple(new_citations)).to_dict()
                resolved.add(p['original_plan_id'])
            impacts.append({**p, 'C14_parent_record_subproof': matching if supported else [],
                'original_remaining_dependencies': p['remaining_dependencies'],
                'remaining_dependencies': ['historical_parent_applicability_unresolved'] if complete_parent_primary else p['remaining_dependencies'],
                'updated_qualification': updated['status'], 'updated_requirement': updated,
                'original_requirement_resolved': complete_parent_primary,
                'resolved_claim_scope': 'source_local_parent_award_identity_and_primary_record_existence_only' if complete_parent_primary else None,
                'resolution_primary_references': primary_refs,
                'additional_remaining_blockers': ['historical_parent_applicability_unresolved'] if supported else []})
        if probe and not probe['record_reassessment']['failures']:
            new_records.update((probe['inventory_sha256'], r['citation']['body_sha256'], r['citation']['locator']) for r in probe['record_reassessment']['records'])
        assessed.append({'case_index': index, 'original_case_sha256': old['original_case_sha256'],
            'profile': old['profile'], 'observation_graph': old['graph'], 'directed_revision_graph': directed,
            'unsupported_revision_candidates': unsupported, 'parent_probe': probe,
            'historical_parent_assessments': parents, 'original_requirement_impacts': impacts})
    for case, expected in zip(cases, inventories):
        if {p: {n: s.byte_sha256 for n, s in snapshot(p).items()} for p in _paths(case)} != expected:
            raise EvidenceError('C14_primary_inputs_changed')
    profile = base['profile']
    before_after = [
        {'measure': 'original_requirements_fully_resolved', 'before': 0, 'after': len(resolved)},
        {'measure': 'original_requirements_remaining', 'before': len(base['remaining_original_plan_ids']), 'after': len(set(base['remaining_original_plan_ids']) - resolved)},
        {'measure': 'new_independently_captured_parent_action_records', 'before': 0, 'after': len(new_records)},
        {'measure': 'original_plans_with_new_parent_record_partial_subproof', 'before': 0, 'after': len(partial_plans)},
        {'measure': 'real_directed_correction_relationships', 'before': 0, 'after': 0},
        {'measure': 'historical_parent_applicability_established', 'before': 0, 'after': 0}]
    value = {'schema_type': 'CorrectionParentReport', 'schema_version': 1, 'rule_version': RULE,
        'profile': profile, 'C13_report_sha256': digest(base), 'cases': assessed,
        'before_after': before_after, 'resolved_original_real_source_requirements': sorted(resolved) if profile == 'live' else [],
        'resolved_original_synthetic_requirements': sorted(resolved) if profile == 'synthetic' else [],
        'real_source_partial_plan_ids': sorted(partial_plans - resolved) if profile == 'live' else [],
        'synthetic_partial_plan_ids': sorted(partial_plans - resolved) if profile == 'synthetic' else [],
        'parent_record_supported_plan_ids': sorted(partial_plans),
        'new_real_source_parent_action_records': len(new_records) if profile == 'live' else 0,
        'new_synthetic_parent_action_records': len(new_records) if profile == 'synthetic' else 0,
        'remaining_original_plan_ids': sorted(set(base['remaining_original_plan_ids']) - resolved),
        'financial_comparison_authorized': False, 'production_readiness_changed': False,
        'limitations': ['no_validated_live_directed_correction_adapter',
            'parent_record_location_not_historical_applicability', 'parent_date_not_effective_interval',
            'partial_pages_not_history_completeness', 'source_status_or_disappearance_not_deletion_lineage',
            'local_integrity_not_upstream_authentication', 'replay_not_new_independent_acquisition']}
    if len(canonical(value).encode()) > 12 * 1024 * 1024:
        raise EvidenceError('C14_report_byte_limit')
    return value


def projections(value):
    lines = ['# Correction lineage and historical parent evidence v1', '',
        'Cohort: ' + value['profile'],
        'No correction winner, financial authorization or readiness upgrade.', '',
        '| Evidence measure | Before | After |', '| --- | ---: | ---: |']
    for r in value['before_after']:
        lines.append('| ' + r['measure'] + ' | ' + str(r['before']) + ' | ' + str(r['after']) + ' |')
    lines += ['', 'Parent record location is distinct from historical applicability. Synthetic relations are fixture observations only.',
        '', '## Original evidence, directed claims and unresolved requirements', '', '```json',
        canonical(value).replace('`', '\\u0060'), '```', '']
    md = '\n'.join(lines)
    html = '<!doctype html><html lang="en"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; base-uri \'none\'"><title>Correction and parent evidence</title><pre>' + escape(md) + '</pre></html>\n'
    return {'correction.json': (canonical(value) + '\n').encode(), 'correction.md': md.encode(), 'correction.html': html.encode()}


def _plan():
    return {'schema_type': 'CorrectionParentReportPlan', 'schema_version': 1,
        'rule_version': RULE, 'config': {'max_run_bytes': 128 * 1024 * 1024}}


def write_report(path, cases):
    cases = _recipe(cases)
    outside(path, [p for c in cases for p in _paths(c)])
    value = report(cases)
    rendered = projections(value)
    if any(len(b) > 32 * 1024 * 1024 for b in rendered.values()) or sum(map(len, rendered.values())) > 96 * 1024 * 1024:
        raise EvidenceError('C14_projection_size_limit')
    with PilotStore(path, _plan()) as store:
        for name, body in rendered.items():
            store.write_bytes(name, body)
        store.write('correction-commit.json', {'schema_version': 1,
            'files': store.inventory(), 'report_sha256': digest(value)})
    return digest(value)


def verify_report(path, cases):
    with EvidenceRoot(path, max_bytes=32 * 1024 * 1024, max_total_bytes=128 * 1024 * 1024, max_files=5) as root:
        files = {n: root.read(n) for n in root.discover()}
        if {n: root.read(n, recheck=True).byte_sha256 for n in root.discover()} != {n: s.byte_sha256 for n, s in files.items()}:
            raise EvidenceError('C14_report_changed_during_read')
    value = report(cases)
    expected = projections(value)
    if set(files) != {*expected, 'pilot-plan.json', 'correction-commit.json'}:
        raise EvidenceError('C14_report_incomplete_or_extra')
    commit = {'schema_version': 1, 'files': {n: s.byte_sha256 for n, s in files.items() if n != 'correction-commit.json'}, 'report_sha256': digest(value)}
    if (files['pilot-plan.json'].data != (canonical(_plan()) + '\n').encode()
        or files['correction-commit.json'].data != (canonical(commit) + '\n').encode()
        or any(files[n].data != raw for n, raw in expected.items())):
        raise EvidenceError('C14_report_primary_replay_conflict')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description='Offline C14 lineage/parent replay; explicit capped USA parent probe only.')
    parser.add_argument('--cases', required=True)
    parser.add_argument('--capture-parent', action='store_true')
    parser.add_argument('--live', action='store_true')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--output')
    mode.add_argument('--verify-report')
    args = parser.parse_args(argv)
    try:
        source = Path(args.cases).absolute()
        with EvidenceRoot(source.parent, max_bytes=1048576) as root:
            cases = _recipe(strict_json(root.read(source.name).data))
            root.read(source.name, recheck=True)
        if args.live != args.capture_parent:
            raise EvidenceError('explicit_parent_probe_flags_required')
        if args.capture_parent:
            if len(cases) != 1 or not cases[0].get('parent_history') or not cases[0].get('c12_capture') or args.verify_report:
                raise EvidenceError('one_bound_C12_parent_probe_required')
            case = cases[0]
            outside(case['parent_history'], [source] + [p for p in _paths(case) if p != case['parent_history']])
            outside(args.output, [source] + _paths(case))
            report([{k: v for k, v in case.items() if k != 'parent_history'}])
            collect_parent(case['parent_history'], case['c12_capture'], live=True)
        if args.verify_report:
            value = verify_report(args.verify_report, cases)
        else:
            write_report(args.output, cases)
            value = verify_report(args.output, cases)
        print(canonical({'report_sha256': digest(value), 'original_real_source_requirements_resolved': len(value['resolved_original_real_source_requirements']),
            'new_real_source_parent_action_records': value['new_real_source_parent_action_records'],
            'financial_comparison_authorized': False}))
        return 1 if any(c['parent_probe'] and c['parent_probe']['failures'] for c in value['cases']) else 0
    except (ValueError, OSError, KeyError, IndexError, TypeError):
        print(canonical({'error_code': 'C14_failed_preserve_original_evidence', 'exit_code': 2}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
