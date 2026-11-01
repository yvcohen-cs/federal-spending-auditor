"""C12 source-local contracts. Observed rows are not certified historical recall."""
from datetime import date
from urllib.parse import quote

from .award_validation import snapshot, validate as diagnose, pagination
from .collection_sources import USA, parse_page
from .evidence import _text
from .evidence_io import EvidenceError, canonical, digest, strict_json
from .scope_models import FIELDS

RULE = 'authoritative-source-verification-v1'
DETAIL = 'https://api.usaspending.gov/api/v2/awards/'
USA_DOC = 'https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/api_contracts/contracts/v2/'
DOCUMENTATION = {
    'usaspending': (USA_DOC+'awards/award_id.md', USA_DOC+'transactions.md', USA_DOC+'idvs/awards.md'),
    'fpds': ('https://www.fpds.gov/wiki/index.php/Atom_Feed_Usage',),
    'samgov': ('https://open.gsa.gov/api/contract-awards/', 'https://open.gsa.gov/api/contract-awards/v1/openapi.yaml'),
}
IDV_TYPES = ('IDV_A','IDV_B','IDV_B_A','IDV_B_B','IDV_B_C','IDV_C','IDV_D','IDV_E')


def identifier(value):
    # Source strings are preserved, never trimmed, normalized or decoded into IDs.
    if type(value) is not str or len(value)>256:
        raise EvidenceError('unsupported_source_native_identifier')
    _text(value,'native identifier')
    if any(c in value for c in ('/','\\','?','#','%')) or value in ('.','..'):
        raise EvidenceError('unsupported_source_native_identifier')
    return value


def detail_request(native_id):
    return {'source':'usaspending','method':'GET','endpoint':DETAIL+quote(identifier(native_id),safe='')+'/', 'parameters':{}}


def award_detail(raw, expected_id, expected_piid, *, parent=False):
    value=strict_json(raw)
    if type(value) is not dict:
        raise EvidenceError('unsupported_USA_award_detail')
    key=identifier(value.get('generated_unique_award_id'));piid=identifier(value.get('piid'))
    if key!=expected_id or piid!=expected_piid:
        raise EvidenceError('USA_detail_native_selection_conflict')
    category='idv' if parent else 'contract'
    if value.get('category')!=category or value.get('type') not in (IDV_TYPES if parent else ('A','B','C','D')):
        raise EvidenceError('unsupported_USA_instrument_context')
    # Only the documented parent fields establish a lookup, not names or a
    # reconstructed CONT_IDV key. Omitted/null fields never become false facts.
    if 'parent_award' not in value:
        relationship={'state':'unknown_missing_parent_field'}
    elif value['parent_award'] is None:
        relationship={'state':'observed_null_summary_not_historical_absence'}
    else:
        p=value['parent_award']
        if type(p) is not dict:
            raise EvidenceError('unsupported_USA_parent_details')
        relationship={'state':'observed_parent_reference',
            **{k:identifier(p.get(k)) for k in ('generated_unique_award_id','piid','sub_agency_id')}}
    return {'source':'usaspending','native_award_id':key,'piid':piid,'category':category,
        'instrument_type':value['type'],'parent':relationship,
        'field_locators':['/generated_unique_award_id','/piid','/category','/type','/parent_award'],
        'historical_parent_validity':'unknown','revision_alignment':'unknown',
        'monetary_arithmetic_authorized':False}


def parent_lookup(child, selection):
    p=child['parent']
    if p['state']!='observed_parent_reference':return None
    # Parent agency is the documented child ParentDetails.sub_agency_id;
    # awarding/funding agency fields are not used as contract identity aliases.
    if selection.parent_piid is None or (p['piid'],p['sub_agency_id'])!=(selection.parent_piid,selection.parent_agency_id):
        raise EvidenceError('USA_child_parent_reference_conflicts_with_original_context')
    if p['generated_unique_award_id']==child['native_award_id']:
        raise EvidenceError('self_referencing_parent')
    return detail_request(p['generated_unique_award_id'])


def usa_transaction_contract(raw, request, award):
    parsed=parse_page('usaspending',raw,request,award);body=strict_json(raw);m=body['page_metadata'];p=request['parameters']['page']
    # Frozen C3 only validates page/hasNext; C12 additionally tests the complete
    # documented pointer tuple. Missing metadata is unknown, not terminal proof.
    required={'page','next','previous','hasNext','hasPrevious'}
    if not required<=set(m):raise EvidenceError('USA_pagination_metadata_missing')
    if type(m['hasPrevious']) is not bool or m['hasPrevious']!=(p>1):raise EvidenceError('USA_previous_flag_conflict')
    for key,wanted in (('next',p+1 if m['hasNext'] else None),('previous',p-1 if p>1 else None)):
        if type(m[key]) is not type(wanted) or m[key]!=wanted:
            raise EvidenceError('USA_pagination_pointer_conflict')
    if any(c!='query_bound_candidate' for c in parsed['contexts']):raise EvidenceError('USA_transaction_context_unvalidated')
    for r in parsed['rows']:
        identifier(r['id'])
        if r['modification_number'] is not None:identifier(r['modification_number'])
        try:
            if date.fromisoformat(r['action_date']).isoformat()!=r['action_date']:raise ValueError()
        except (ValueError,TypeError):raise EvidenceError('USA_action_date_unsupported') from None
    return parsed


def collection_contract(path, *, requested=None):
    """Revalidate primary captures before checking source-specific field contracts."""
    before=snapshot(path);files={n:s.byte_sha256 for n,s in before.items()}
    plan=strict_json(before['c3_plan.json'].data)
    if requested is None:
        from .scope_models import ScopeRequest
        if len(plan['awards'])!=1:raise EvidenceError('one_explicit_contract_scope_required')
        a=plan['awards'][0]
        requested=ScopeRequest(piid=a['piid'],agency=a['agency_id'],parent_piid=a['parent_piid'],parent_agency=a['parent_agency_id'])
    d=diagnose((path,),requested)
    chains={};rows={};failures=[];citations=[]
    for issue in d['artifact_issues']:
        failures.append({'issue':'unusable_primary_artifact','detail':issue})
    for record in d['records']:
        context=record['native_context']
        if (record['scope_status'] in ('verified_out_of_scope','unsupported_schema')
            or any(v['state'] in ('conflicting','malformed','unsupported') for v in context.values())
            or any(context[k]['state']!='valid' for k in ('piid','agency','modification','transaction'))
            or any(context[k]['value']!=getattr(requested,k) for k in FIELDS if getattr(requested,k) is not None)):
            failures.append({'issue':'native_record_not_bound_to_requested_context','citation':record['citation']})
    for name,s in sorted(before.items()):
        if not name.startswith('c3_attempt_') or not name.endswith('.json'):continue
        meta=strict_json(s.data);request=meta['request'];source=request['source'];body=before.get(name[:-5]+'.body')
        citation={'metadata':name,'metadata_sha256':s.byte_sha256,'body':name[:-5]+'.body' if body else None,
            'body_sha256':body.byte_sha256 if body else None,'request':request,'retrieved_at_utc':meta['retrieved_at_utc'],
            'source':source,'representation':'preserved_HTTP_entity_body_not_wire_message'}
        citations.append(citation)
        if meta['error_code'] or not meta['body_complete'] or meta['status'] is None or not 200<=meta['status']<300 or body is None:
            failures.append({'citation':citation,'issue':'incomplete_or_failed_source_attempt'});continue
        award=plan['awards'][request['task_index']//len(plan['sources'])]
        try:
            parsed=usa_transaction_contract(body.data,request,award) if source=='usaspending' else parse_page(source,body.data,request,award)
            if any(c!='query_bound_candidate' for c in parsed['contexts']):raise EvidenceError('native_query_context_unvalidated')
        except (ValueError,TypeError,KeyError) as exc:
            failures.append({'citation':citation,'issue':str(exc) if isinstance(exc,EvidenceError) else 'unsupported_source_contract'});continue
        task=(source,request['task_index']);chains.setdefault(task,[]).append((request['page_index'],parsed['has_next'],tuple(parsed['fingerprints'])))
        for index,r in enumerate(parsed['rows']):
            rows.setdefault(task,[]).append({'native_action_id':r.get('id') if source=='usaspending' else r.get('atom_id'),
                'modification_number':r.get('modification_number') if source=='usaspending' else r.get('modNumber'),
                'transaction_number':None if source=='usaspending' else r.get('transactionNumber'),
                'action_date':r.get('action_date') if source=='usaspending' else r.get('signedDate'),
                'source_update_raw':None if source=='usaspending' else r.get('updated'),
                'record_sha256':parsed['fingerprints'][index],'record_index':index,'citation':citation})
    histories=[]
    for (source,task),pages in sorted(chains.items()):
        occurrences=rows.get((source,task),[]);chain=pagination(pages);variants={};dates=[]
        for r in occurrences:
            if r['native_action_id'] is not None:variants.setdefault(r['native_action_id'],set()).add(r['record_sha256'])
            if r['action_date'] is not None:dates.append(r['action_date'])
        conflicting=sorted(k for k,v in variants.items() if len(v)>1)
        # Action-date display ordering does not establish correction precedence.
        ordered=None if source!='usaspending' else dates==sorted(dates)
        histories.append({'source':source,'task_index':task,'pagination':chain,'observations':occurrences,
            'conflicting_native_action_ids':conflicting,'action_date_order_observed':ordered,
            'repeated_identical_observations':len(occurrences)-len({r['record_sha256'] for r in occurrences}),
            'source_contract_satisfied':not failures and chain['bounded_observed_chain']=='consistent_terminal' and not conflicting and ordered is not False,
            'missing_modifications_inferred':False,'correction_winner_selected':False,'history_complete':'unknown',
            'deletion_visibility':'unknown','freshness':'unknown','financial_comparison_authorized':False})
    if files!={n:s.byte_sha256 for n,s in snapshot(path).items()}:raise EvidenceError('source_contract_capture_changed')
    return {'rule_version':RULE,'inventory_sha256':digest(files),'profile':d['profile'],'histories':histories,
        'failures':failures,'citations':citations,'legacy_diagnostic_sha256':digest(d),
        'documentation':{s:list(DOCUMENTATION[s]) for s in plan['sources']},
        'limitations':['terminal_pages_do_not_certify_recall_or_history','absence_is_not_nonexistence',
            'modification_labels_not_contiguous_sequence','action_dates_not_revision_precedence','source_updates_not_freshness_certificate']}
