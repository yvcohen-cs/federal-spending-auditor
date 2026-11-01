"""C13 primary-input history replay and deterministic reports, offline by default."""
import argparse
from html import escape
from pathlib import Path

from .acquisition_planning import case_report
from .award_validation import snapshot
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json
from .financial_ingestion import _usa_fields
from .financial_models import field_semantics
from .financial_values import exact_json, monetary_value
from .history_models import temporal_parse
from .identity_matching import decode_usa_id
from .pilot_store import PilotStore
from .review_packet_io import outside
from .revision_lineage import RULE,NATIVE,FACETS,HistoryFacet,CoverageState,LineageObservation,graph,facets
from .source_verification import inspect_experiment,VerificationExperiment
from .historical_probe import read as read_probe,collect as collect_probe


def _cases(cases):
    if type(cases) not in (list,tuple) or not 1<=len(cases)<=24 or any(type(c) is not dict for c in cases):raise EvidenceError('bounded_case_sequence_required')
    allowed={'collections','sam_captures','scope','interval','report','c12_capture','historical_probe','comparison_interval'}
    if any(set(c)-allowed or c.get('historical_probe') and not c.get('c12_capture') for c in cases):raise EvidenceError('explicit_supported_history_recipe_required')
    return tuple(cases)


def _date(raw):
    return raw if type(raw) is str and len(raw)==10 and temporal_parse(raw)==raw else None


def _from_qualification(report,*,role):
    nodes=[]
    for c in report['contracts']:
        for r in c['observed_occurrences']:
            if r['source']=='samgov':
                a=r['context']['award'];context={'piid':a['piid'],'agency':a['identity_subtier'],'parent_piid':a['parent_piid'],'parent_agency':a['parent_subtier'],
                    'modification':None if r['action'] is None else r['action'][0],'transaction':None if r['action'] is None else r['action'][1]}
            else:context={**{k:r['context'].get(k) for k in NATIVE[:4]},'modification':None if r['action'] is None else r['action'][0],'transaction':None if r['action'] is None else r['action'][1]}
            ids=r['native_identifiers'];nid=next((n['value'] for n in ids if n['namespace'] in ('id','atom_id')),None)
            dates={t['parsed'] for t in r['temporal_fields'] if t['meaning']=='signed' and _date(t['parsed']) is not None}
            citation={'input_role':role,'input_index':r['input_index'],'input_inventory_sha256':report['inputs'][r['input_index']]['inventory_sha256'],'original_reference':r['citation']}
            metadata=list(r['temporal_fields'])
            if r['source']=='samgov':metadata.append({'source_native_award_context':r['context']['award']})
            if r.get('native_action') is not None:metadata.append({'native_action_metadata':r['native_action'],'semantics':'source_native_version_not_correction_precedence'})
            nodes.append(LineageObservation(source=r['source'],profile=report['profile'],original_occurrence_id=r['id'],native_context_json=canonical(context),
                native_identifiers_json=canonical(ids),native_action_id=nid,action_date=next(iter(dates)) if len(dates)==1 else None,
                update_metadata_json=canonical(metadata),monetary_fields_json=canonical([{k:v for k,v in m.items() if k not in ('evidence','record_id')} for m in r['money']]),citation_json=canonical(citation),provenance_sha256=digest(citation),content_sha256=r['content_sha256'],
                parent_assertion_basis={'usaspending':'encoded_USA_native_transaction_components','fpds':'direct_FPDS_referenced_IDV_fields','samgov':'direct_SAM_contractId_fields'}[r['source']],
                identity_supported=r['identity_observed'] and not r['identity_conflict'] and not r['reused_native_identifier'] and r['parent']['status']!='parent_relationship_conflict',outside_requested_context=r['outside_requested_context'],
                issues=tuple(sorted(set(r['diagnostic_gaps'])|({'contradictory_signed_date_fields'} if len(dates)>1 else set())|({'within_record_native_component_conflict'} if r['identity_conflict'] else set())|({'within_record_parent_component_conflict'} if r['parent_context_conflict'] or r['parent']['status']=='parent_relationship_conflict' else set()))),
                existing_native_scope_verified=r.get('legacy_scope_status')=='verified_in_scope' and r['parent']['status']!='parent_relationship_conflict'))
    return nodes


def _sam_details(nodes,case):
    """Retain native SAM temporal, monetary and prior-ID fields without mapping
    them into C5 amounts, USA/FPDS namespaces or correction precedence."""
    from dataclasses import replace
    from .sam_semantics_reporting import capture_report
    fields={}
    for path in case.get('sam_captures',()):
        capture,records=capture_report(path)
        if capture['state']!='revalidated_bounded_capture':raise EvidenceError('unvalidated_SAM_history_capture')
        for r in records:fields[r.claim_id]=r
    out=[]
    for n in nodes:
        if n.source!='samgov':out.append(n);continue
        # C10 retains the original native claim ID in the occurrence recipe;
        # recover by its exact citation, not source hashes as entity identity.
        cite=strict_json(n.citation_json.encode())['original_reference']
        matches=[r for r in fields.values() if r.citation.to_dict()==cite]
        if len(matches)!=1:raise EvidenceError('SAM_original_record_reference_ambiguous')
        r=matches[0]
        times=[f.to_dict() for f in r.fields if f.meaning in ('signed','created','approved','last_modified','document_version','native_status','prior_identifier_context','parent_modification')]
        signed=next((strict_json(f.original_json.encode()) for f in r.fields if f.meaning=='signed'),None)
        out.append(replace(n,action_date=_date(signed),update_metadata_json=canonical(strict_json(n.update_metadata_json.encode())+times),monetary_fields_json=canonical([f.to_dict() for f in r.fields if f.meaning=='money'])))
    return out


def _probe_nodes(path,value):
    data=snapshot(path);nodes=[]
    for r in value['records']:
        c,_=decode_usa_id(r['row']['id']);context={k:c[k].value for k in NATIVE}
        citation={'input_role':'C13_reverse_probe','input_inventory_sha256':value['inventory_sha256'],**r['citation']}
        # Exact numeric lexemes, including deobligations, stay observable;
        # they are not totaled or converted to another monetary definition.
        raw=exact_json(data[r['citation']['body_file']].data)['results'][int(r['citation']['locator'].split('/')[-1])]
        signed,fields=_usa_fields(raw);money=[]
        for field,kind,text,currency in fields:
            money.append({'original_field':field,'value':monetary_value(kind,text).to_dict(),'semantics':field_semantics('usaspending',field).to_dict(),'action_date_raw':signed,'declared_currency_raw':currency})
        nodes.append(LineageObservation(source='usaspending',profile=value['profile'],original_occurrence_id='probe-occurrence:v1:'+digest(citation),native_context_json=canonical(context),
            native_identifiers_json=canonical([{'source':'usaspending','namespace':'id','value':r['row']['id']}]),native_action_id=r['row']['id'],action_date=r['row']['action_date'],
            update_metadata_json=canonical([] if r['citation']['source_update_raw'] is None else [{'path':'http:Last-Modified','meaning':'http_last_modified','original_json':canonical(r['citation']['source_update_raw']),'parsed':temporal_parse(r['citation']['source_update_raw'])}]),monetary_fields_json=canonical(money),citation_json=canonical(citation),provenance_sha256=digest(citation),content_sha256=r['content_sha256'],
            parent_assertion_basis='encoded_USA_native_transaction_components',identity_supported=True,outside_requested_context=False,
            issues=() if value['valid_observed_descending_window'] else ('partial_probe_no_window_completeness_credit',),existing_native_scope_verified=True))
    return nodes


def report(cases):
    cases=_cases(cases);case_results=[];inventories=[];all_plan_ids=[];node_work=0;seen_cases=set()
    for case_index,case in enumerate(cases):
        paths=list(case.get('collections',()))+list(case.get('sam_captures',()))
        for name in ('c12_capture','historical_probe'):
            if case.get(name):paths.append(case[name])
        initial=[{n:s.byte_sha256 for n,s in snapshot(p).items()} for p in paths]
        old=case_report(case)
        if digest(old) in seen_cases:raise EvidenceError('duplicate_original_case_not_independent_history')
        seen_cases.add(digest(old))
        from .history_qualification import HistoricalInterval
        requested_interval=case.get('comparison_interval',old['requested_interval'])
        requested_interval=(HistoricalInterval.from_dict(requested_interval) if type(requested_interval) is dict else requested_interval)
        if not isinstance(requested_interval,HistoricalInterval):raise EvidenceError('typed_history_interval_required')
        requested_interval=requested_interval.to_dict()
        nodes=_sam_details(_from_qualification(old,role='original_C10_primary'),case);base_nodes=list(nodes);current=None;probe=None
        if case.get('c12_capture'):
            current=inspect_experiment(case['c12_capture']);spec=VerificationExperiment.from_dict(current['experiment']).spec
            if digest(old) not in {t.case_id for t in spec.requirements} or old['profile']!=('synthetic' if current['knowledge_basis']=='SYNTHETIC_ONLY' else 'live'):raise EvidenceError('C12_original_case_or_profile_binding_conflict')
            # Add original C12 transaction observations to BOTH C13 baseline and
            # updated graph. These are prior observations, not new C13 evidence.
            prior=case_report({**case,'report':None,'collections':[str(Path(case['c12_capture'])/'transactions')]})
            extra=_from_qualification(prior,role='prior_C12_primary');nodes.extend(extra);base_nodes.extend(extra)
        if case.get('historical_probe'):
            probe=read_probe(case['historical_probe'],case['c12_capture'])
            if probe['profile']!=old['profile']:raise EvidenceError('probe_history_profile_conflict')
            nodes.extend(_probe_nodes(case['historical_probe'],probe))
        node_work+=len(nodes)
        if node_work>1000:raise EvidenceError('combined_history_node_limit')
        before_graph=graph(base_nodes);after_graph=graph(nodes)
        parents=[]
        for n in nodes:
            ctx=strict_json(n.native_context_json.encode());pair=[ctx['parent_piid'],ctx['parent_agency']]
            supported_current=(current is not None and current['current_source_parent_link']=='verified_source_local_summary_link' and n.source=='usaspending'
                and not n.outside_requested_context and n.identity_supported and ctx['piid']==current['child']['piid'] and ctx['agency']==strict_json(VerificationExperiment.from_dict(current['experiment']).spec.native_context_json.encode())['agency'] and pair==[current['child']['parent'].get('piid'),current['child']['parent'].get('sub_agency_id')])
            parents.append({'node_id':n.node_id,'native_parent_pair':pair,'assertion_basis':n.parent_assertion_basis,'action_date':n.action_date,
                'record_asserted_parent':all(v is not None for v in pair),'current_source_parent_primary_supported':supported_current,
                'current_primary_citations':current['citations'] if supported_current else [],'historical_applicability_interval':'unknown',
                'historical_parent_validated':False,'parent_change_or_correction_established':False})
        window_verified=bool(probe is not None and probe['valid_observed_descending_window'] and probe['window_agreement']=='same_observed_native_ids_and_record_contents')
        original_window_checks=[]
        if window_verified:
            from .source_contracts import collection_contract
            from .scope_models import ScopeRequest
            for path in case.get('collections',()):
                checked=collection_contract(path,requested=ScopeRequest.from_dict(old['requested_scope']))
                original_window_checks.append({'inventory_sha256':checked['inventory_sha256'],'USA_windows_verified':bool(checked['histories']) and any(h['source']=='usaspending' for h in checked['histories']) and not checked['failures'] and all(h['source_contract_satisfied'] for h in checked['histories'] if h['source']=='usaspending')})
        all_original_windows_verified=bool(original_window_checks) and all(w['USA_windows_verified'] for w in original_window_checks)
        source_facets=[]
        attempted={s['source'] for p in old['pagination_evidence'] for s in p.get('sources',())}|{n.source for n in nodes}
        for source in ('usaspending','fpds','samgov'):
            ns=[n for n in nodes if n.source==source]
            verified=source=='usaspending' and window_verified and all_original_windows_verified
            assessments=(facets(ns,pagination_verified=verified,interval_known=requested_interval['start_date'] is not None) if ns or source in attempted else [HistoryFacet(dimension=d,status=CoverageState.NOT_EVALUATED,defined_scope='finite_revalidated_observations_not_universal_history',reasons=('no_preserved_source_capture_no_access_assumption',),node_ids=()).to_dict() for d in FACETS])
            overall=('CONFLICTING_EVIDENCE' if any(f['status']=='CONFLICTING_EVIDENCE' for f in assessments) else 'PARTIALLY_OBSERVED' if ns else 'INSUFFICIENT_EVIDENCE' if source in attempted else 'NOT_EVALUATED')
            source_facets.append({'source':source,'facets':assessments,
                'overall_historical_status':overall,'full_historical_completeness':'unknown','financial_comparison_authorized':False})
        impacts=[]
        for p in old['resolution_plans']:
            context=strict_json(p['native_identifiers_json'].encode())
            matching=[n.node_id for n in nodes if n.source==p['source'] and all(strict_json(n.native_context_json.encode()).get(k)==context.get(k) for k in NATIVE[:4])]
            impacts.append({'original_plan_id':p['plan_id'],'original_contract_id':p['contract_id'],'original_requirement':p['requirement'],
                'native_context':context,'new_evidence_node_ids':sorted(set(matching)-{n.node_id for n in base_nodes}),
                'dimension':p['requirement']['dimension'],'original_qualification_after_replay':p['requirement']['status'],
                'original_requirement_resolved':False,'partial_subproof':'bounded_bidirectional_observed_window_agreement' if window_verified and p['source']=='usaspending' and p['requirement']['dimension']=='source_completeness' else None,
                'remaining_dependencies':p['requirement']['reasons'],'financial_comparison_authorized':False})
        all_plan_ids.extend(p['plan_id'] for p in old['resolution_plans'])
        for path,expected in zip(paths,initial):
            if {n:s.byte_sha256 for n,s in snapshot(path).items()}!=expected:raise EvidenceError('historical_primary_inputs_changed')
        inventories.append({'case_index':case_index,'primary_inventory_sha256':[digest(i) for i in initial]})
        def counts(ns):
            return {s:(None if s=='samgov' and any(n.source=='samgov' for n in ns) else len({n.native_context_json for n in ns if n.source==s and n.identity_supported and not n.outside_requested_context})) for s in ('usaspending','fpds','samgov')}
        case_results.append({'case_index':case_index,'original_case_sha256':digest(old),'profile':old['profile'],'original_qualification_sha256':digest(old),
            'baseline_graph_sha256':digest(before_graph),'graph':after_graph,'parent_relationships':parents,'historical_assessments':source_facets,
            'requested_historical_interval':requested_interval,'original_qualification_requested_interval':old['requested_interval'],'interval_coverage':'not_certified_by_observed_date_range',
            'unresolved_intervals':[{'start':requested_interval['start_date'],'end':requested_interval['end_date'],'status':'entire_requested_interval_uncertified' if requested_interval['start_date'] is not None else 'historical_interval_not_defined'}],
            'original_requirement_impacts':impacts,'probe':probe,'current_parent_proof_is_prior_C12_evidence':current is not None,'original_window_checks':original_window_checks,
            'before_source_native_action_counts':counts(base_nodes),'after_source_native_action_counts':counts(nodes),
            'new_historical_completeness_certificates':0,'new_current_parent_primary_proofs':0,
            'new_bidirectional_window_subproofs':int(probe is not None and probe['valid_observed_descending_window'] and probe['window_agreement']=='same_observed_native_ids_and_record_contents'),
            'financial_comparison_authorized':False})
    profiles={c['profile'] for c in case_results}
    if len(profiles)>1:raise EvidenceError('mixed_live_synthetic_history_cohorts')
    value={'schema_type':'HistoricalLineageReport','schema_version':1,'rule_version':RULE,'profile':next(iter(profiles)),'inputs':inventories,'cases':case_results,
        'new_real_source_window_subproofs':len({c['probe']['inventory_sha256'] for c in case_results if c['profile']=='live' and c['new_bidirectional_window_subproofs']}),
        'new_synthetic_window_subproofs':len({c['probe']['inventory_sha256'] for c in case_results if c['profile']=='synthetic' and c['new_bidirectional_window_subproofs']}),
        'original_resolution_plan_ids':sorted(set(all_plan_ids)),'original_plan_occurrences':len(all_plan_ids),
        'resolved_original_real_source_requirements':[],'resolved_original_synthetic_requirements':[],
        'remaining_original_plan_ids':sorted(set(all_plan_ids)),
        'financial_comparison_authorized':False,'production_readiness_changed':False,
        'correction_precedence_authority':'unestablished_no_winner_selected',
        'limitations':['current_observations_not_a_revision_archive','action_dates_are_not_revision_precedence','parent_pairs_are_not_historical_applicability_intervals',
            'terminal_pagination_and_reverse_agreement_do_not_prove_universal_history','SAM_namespace_mapping_and_authenticated_access_unestablished',
            'FPDS_current_query_documentation_unverified','no_financial_totals_or_deltas','local_hashes_not_upstream_authentication']}
    if len(canonical(value).encode())>8*1024*1024:raise EvidenceError('historical_report_byte_limit')
    return value


def markdown(value):
    lines=['# Historical lineage and completeness v1','',
        'Observed source records only. No revision winner, financial authorization or production readiness upgrade.',
        'Evidence cohort: '+value['profile'],
        'Original requirement occurrences: '+str(value['original_plan_occurrences']),
        'Original real-source requirements resolved: '+str(len(value['resolved_original_real_source_requirements'])),
        'Original synthetic requirements resolved: '+str(len(value['resolved_original_synthetic_requirements'])),
        'Real-source bounded window subproofs: '+str(value['new_real_source_window_subproofs']),
        'Synthetic-only bounded window subproofs: '+str(value['new_synthetic_window_subproofs']),'']
    def cell(v):return escape(str(v) if v is not None else 'UNKNOWN').replace('|','&#124;').replace('\n',' ')
    for case in value['cases']:
        lines.extend(('## Case '+str(case['case_index']),'',
            'Source-native action counts before: '+canonical(case['before_source_native_action_counts']),
            'Source-native action counts after: '+canonical(case['after_source_native_action_counts']),
            'Exact mapped USA/FPDS component groups: '+str(len({canonical(r['native_components']) for r in case['graph']['cross_source_observations']})),
            'Historical parent applicability and correction precedence remain unestablished. Repeated occurrences are not independent awards.','',
            '| Source | PIID | Modification | Transaction | Action date | Parent PIID / agency | Observed content | Occurrences |',
            '| --- | --- | --- | --- | --- | --- | --- | ---: |'))
        rows={}
        for n in case['graph']['nodes']:
            c=strict_json(n['native_context_json'].encode())
            key=(n['source'],c['piid'],c['modification'],c['transaction'],n['action_date'],c['parent_piid'],c['parent_agency'],n['content_sha256'])
            rows[key]=rows.get(key,0)+1
        for key,count in sorted(rows.items(),key=lambda p:canonical(p[0])):
            source,piid,mod,tx,date,parent,agency,sha=key
            lines.append('| '+' | '.join(cell(v) for v in (source,piid,mod,tx,date,str(parent)+' / '+str(agency),sha[:16],count))+' |')
        lines.extend(('', '| Source | Dimension | Assessment |', '| --- | --- | --- |'))
        for s in case['historical_assessments']:
            for f in s['facets']:lines.append('| '+cell(s['source'])+' | '+f['dimension']+' | '+f['status']+' |')
        lines.extend(('', 'Date-order edges are display relations, never correction precedence. All primary references, competing observations, source fields and remaining proof obligations follow.',''))
    lines.extend(('## Exact graph, source citations and unresolved requirements','', '```json',canonical(value).replace('`','\\u0060'),'```',''))
    return '\n'.join(lines)


def html(value):
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; base-uri \'none\'"><title>Historical lineage</title><pre>'+escape(markdown(value))+'</pre></html>\n'


def write_report(path,cases):
    cases=_cases(cases);protected=[p for c in cases for k in ('collections','sam_captures') for p in c.get(k,())]+[c[k] for c in cases for k in ('c12_capture','historical_probe') if c.get(k)]
    outside(path,protected);value=report(cases)
    with PilotStore(path,{'schema_type':'HistoricalLineageReportPlan','schema_version':1,'rule_version':RULE,'config':{'max_run_bytes':128*1024*1024}}) as store:
        rendered=projections(value)
        if any(len(body)>32*1024*1024 for body in rendered.values()) or sum(map(len,rendered.values()))>96*1024*1024:raise EvidenceError('historical_projection_byte_limit')
        for name,body in rendered.items():store.write_bytes(name,body)
        store.write('lineage-commit.json',{'schema_version':1,'files':store.inventory(),'report_sha256':digest(value)})
    return digest(value)


def projections(value):return {'lineage.json':(canonical(value)+'\n').encode(),'lineage.md':markdown(value).encode(),'lineage.html':html(value).encode()}


def verify_report(path,cases):
    with EvidenceRoot(path,max_bytes=32*1024*1024,max_total_bytes=128*1024*1024,max_files=5) as root:
        values={n:root.read(n) for n in root.discover()}
        if {n:root.read(n,recheck=True).byte_sha256 for n in root.discover()}!={n:s.byte_sha256 for n,s in values.items()}:raise EvidenceError('lineage_report_changed_during_read')
    value=report(cases);plan={'schema_type':'HistoricalLineageReportPlan','schema_version':1,'rule_version':RULE,'config':{'max_run_bytes':128*1024*1024}}
    expected=projections(value)
    if set(values)!={*expected,'pilot-plan.json','lineage-commit.json'} or values['pilot-plan.json'].data!=(canonical(plan)+'\n').encode():raise EvidenceError('incomplete_or_unsupported_lineage_report')
    commit={'schema_version':1,'files':{n:s.byte_sha256 for n,s in values.items() if n!='lineage-commit.json'},'report_sha256':digest(value)}
    if values['lineage-commit.json'].data!=(canonical(commit)+'\n').encode() or any(values[n].data!=raw for n,raw in expected.items()):raise EvidenceError('lineage_report_primary_replay_conflict')
    return value


def main(argv=None):
    p=argparse.ArgumentParser(description='Offline historical lineage; explicit bounded USA reverse probe only with --capture-probe --live.')
    p.add_argument('--cases',required=True);p.add_argument('--capture-probe',action='store_true');p.add_argument('--live',action='store_true')
    mode=p.add_mutually_exclusive_group(required=True);mode.add_argument('--output');mode.add_argument('--verify-report')
    args=p.parse_args(argv)
    try:
        source=Path(args.cases).absolute()
        with EvidenceRoot(source.parent,max_bytes=1048576) as root:
            saved=root.read(source.name);cases=_cases(strict_json(saved.data));root.read(source.name,recheck=True)
        if args.live!=args.capture_probe:raise EvidenceError('explicit_bounded_probe_flags_required')
        if args.capture_probe:
            if len(cases)!=1 or not cases[0].get('historical_probe') or not cases[0].get('c12_capture') or args.verify_report:raise EvidenceError('one_original_C12_case_and_new_probe_path_required')
            protected=[source]+[v for c in cases for k in ('collections','sam_captures') for v in c.get(k,())]
            outside(cases[0]['historical_probe'],protected)
            report([{k:v for k,v in cases[0].items() if k!='historical_probe'}])
            collect_probe(cases[0]['historical_probe'],cases[0]['c12_capture'],live=True)
        if args.verify_report:value=verify_report(args.verify_report,cases)
        else:
            write_report(args.output,cases);value=verify_report(args.output,cases)
        print(canonical({'report_sha256':digest(value),'original_real_source_requirements_resolved':0,'financial_comparison_authorized':False}))
        return 1 if any(c['probe'] is not None and not c['probe']['valid_observed_descending_window'] for c in value['cases']) else 0
    except (ValueError,TypeError,OSError,KeyError,IndexError):
        print(canonical({'error_code':'historical_lineage_failed_preserve_evidence','exit_code':2}));return 2


if __name__=='__main__':raise SystemExit(main())
