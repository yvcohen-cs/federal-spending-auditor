"""Two-request USA reverse-order probe bound to preserved C12 primary evidence."""
from pathlib import Path
import hashlib
import time

from .collection import SelectedAward, CollectionLimits
from .collection_sources import HTTPTransport, FixtureTransport, request_for
from .evidence_io import EvidenceError, canonical, digest, strict_json
from .award_validation import snapshot, pagination
from .source_contracts import usa_transaction_contract
from .source_verification import inspect_experiment, VerificationExperiment, _metadata
from .identity_matching import decode_usa_id, agency_component
from .pilot_store import PilotStore
from .review_packet_io import outside
from .revision_lineage import RULE, NATIVE


def manifest(path):return {n:s.byte_sha256 for n,s in snapshot(path).items()}


def anchor(path):
    v=inspect_experiment(path);tx=v['transaction_contract']
    if v['issues'] or not tx or tx['failures'] or not tx['histories'] or not all(h['source_contract_satisfied'] for h in tx['histories']):raise EvidenceError('validated_C12_anchor_required')
    spec=VerificationExperiment.from_dict(v['experiment']).spec
    selected=SelectedAward.from_dict(strict_json(spec.selection_json.encode()))
    if selected.parent_piid is None or selected.parent_agency_id is None:raise EvidenceError('complete_source_native_parent_context_required_for_reverse_probe')
    return v,selected


def plan_for(base):
    v,a=anchor(base)
    return {'schema_type':'HistoricalWindowProbePlan','schema_version':1,'rule_version':RULE,
        'base_C12_inventory_sha256':v['inventory_sha256'],'selection':a.to_dict(),
        'profile':'synthetic' if v['knowledge_basis']=='SYNTHETIC_ONLY' else 'live',
        'allowlist':['usaspending'],'maximum_requests':2,'page_size':2,'maximum_rows':4,
        'order':'desc','sort':'action_date','retries':0,'redirects':False,'pace_seconds':1.0,
        'max_response_bytes':1048576,'config':{'max_run_bytes':8*1024*1024}}


def request(a,page):
    value=request_for('usaspending',a.to_dict(),page,2)
    value['parameters']['order']='desc'
    return value


def parse(raw,req,a):
    p=usa_transaction_contract(raw,req,a.to_dict())
    for row in p['rows']:
        c,issues=decode_usa_id(row['id']);c={**c,'agency':agency_component(c['agency']),'parent_agency':agency_component(c['parent_agency'])}
        expected={'piid':a.piid,'agency':a.agency_id,'parent_piid':a.parent_piid,'parent_agency':a.parent_agency_id}
        if issues or any(c[k].value!=v for k,v in expected.items() if v is not None) or any(c[k].value is None for k in ('piid','agency','modification','transaction')) or c['modification'].value!=row['modification_number']:
            raise EvidenceError('reverse_probe_native_context_conflict')
    return p


def collect(path,base,*,live=False,synthetic=None):
    if type(live) is not bool:raise EvidenceError('explicit_probe_mode_required')
    plan=plan_for(base);_,a=anchor(base)
    if live:
        if plan['profile']!='live' or synthetic is not None:raise EvidenceError('live_probe_requires_preserved_live_anchor_no_fixture')
    elif plan['profile']!='synthetic' or synthetic is None:raise EvidenceError('offline_default_no_network')
    if synthetic is not None:
        if type(synthetic) is not dict or type(synthetic.get('responses')) is not list or len(synthetic['responses'])>2:raise EvidenceError('bounded_two_response_transcript_required')
        transport=FixtureTransport(synthetic)
    outside(path,(base,))
    before=manifest(base)
    with PilotStore(path,plan) as store:
        if live:
            limits=CollectionLimits(retries=0,timeout_seconds=10.0,pace_seconds=1.0,max_response_bytes=1048576)
            transport=HTTPTransport(limits.to_dict())
        for index in range(2):
            req=request(a,index+1);stem=f'page-{index+1:03d}'
            store.write(stem+'-reservation.json',{'sequence':index,'request':req})
            if live and index:time.sleep(1.0)
            meta,raw=transport(req,index)
            if raw is not None and len(raw)>1048576:
                raw=raw[:1048576];meta={**meta,'body_complete':False,'error_code':'response_size_limit'}
            okay=_metadata(meta,raw)
            if raw is not None:store.write_bytes(stem+'.body',raw)
            store.write(stem+'.json',{'request':req,'response':meta,'body_sha256':hashlib.sha256(raw).hexdigest() if raw is not None else None,
                'representation':'synthetic_transcript_bytes' if plan['profile']=='synthetic' else 'HTTP_entity_bytes_after_content_decoding'})
            if not okay:break
            try:p=parse(raw,req,a)
            except (ValueError,KeyError,TypeError):break
            if not p['has_next']:break
        if manifest(base)!=before:raise EvidenceError('C12_anchor_changed_during_probe')
        store.write('probe-commit.json',{'schema_version':1,'files':store.inventory()})
    return read(path,base)


def read(path,base):
    values=snapshot(path);files={n:s.byte_sha256 for n,s in values.items()};plan=plan_for(base);a=SelectedAward.from_dict(plan['selection'])
    if 'probe-commit.json' not in values:raise EvidenceError('interrupted_probe_not_automatically_repaired')
    expected={'schema_version':1,'files':{n:h for n,h in files.items() if n!='probe-commit.json'}}
    if values['probe-commit.json'].data!=(canonical(expected)+'\n').encode() or values['pilot-plan.json'].data!=(canonical(plan)+'\n').encode():raise EvidenceError('probe_manifest_or_anchor_conflict')
    expected_files={'pilot-plan.json','probe-commit.json'};pages=[];records=[];failures=[];continuing=True;attempts=0
    for index in range(2):
        stem=f'page-{index+1:03d}';req=request(a,index+1)
        if not continuing:
            if any(n.startswith(stem) for n in values):raise EvidenceError('probe_followed_after_terminal_or_failure')
            continue
        if stem+'.json' not in values or stem+'-reservation.json' not in values:raise EvidenceError('missing_probe_request_history')
        expected_files|={stem+'.json',stem+'-reservation.json'};attempts+=1
        if values[stem+'-reservation.json'].data!=(canonical({'sequence':index,'request':req})+'\n').encode():raise EvidenceError('probe_request_reservation_conflict')
        m=strict_json(values[stem+'.json'].data);body=values.get(stem+'.body')
        if body is not None:expected_files.add(stem+'.body')
        representation='synthetic_transcript_bytes' if plan['profile']=='synthetic' else 'HTTP_entity_bytes_after_content_decoding'
        if set(m)!={'request','response','body_sha256','representation'} or canonical(m['request'])!=canonical(req) or m['representation']!=representation or m['body_sha256']!=(body.byte_sha256 if body else None):raise EvidenceError('probe_source_provenance_conflict')
        citation={'request':req,'metadata_file':stem+'.json','metadata_sha256':values[stem+'.json'].byte_sha256,'body_file':stem+'.body' if body else None,
            'body_sha256':m['body_sha256'],'retrieved_at_utc':m['response']['retrieved_at_utc'],'source_update_raw':m['response']['source_update_raw'],'representation':representation}
        if not _metadata(m['response'],None if body is None else body.data):
            failures.append({'citation':citation,'reason':'source_attempt_incomplete_or_failed'});continuing=False;continue
        try:p=parse(body.data,req,a)
        except (ValueError,TypeError,KeyError):
            failures.append({'citation':citation,'reason':'unsupported_native_fields_or_page_contract'});continuing=False;continue
        pages.append((index+1,p['has_next'],tuple(p['fingerprints'])))
        for i,row in enumerate(p['rows']):records.append({'row':row,'content_sha256':p['fingerprints'][i],'citation':{**citation,'locator':'/results/'+str(i)},'page':index+1})
        continuing=p['has_next']
    if set(values)!=expected_files or manifest(path)!=files:raise EvidenceError('probe_extra_or_changed_evidence')
    chain=pagination(pages);dates=[r['row']['action_date'] for r in records]
    if dates!=sorted(dates,reverse=True):failures.append({'reason':'descending_action_date_contract_violated'})
    if len({r['row']['id'] for r in records})!=len(records):failures.append({'reason':'duplicate_or_variant_native_transaction_ids'})
    valid=not failures and chain['bounded_observed_chain']=='consistent_terminal'
    original=anchor(base)[0]['transaction_contract']['histories'];forward={r['native_action_id']:r['record_sha256'] for h in original for r in h['observations'] if h['source']=='usaspending'}
    reverse={r['row']['id']:r['content_sha256'] for r in records}
    return {'schema_type':'HistoricalWindowProbe','schema_version':1,'rule_version':RULE,'inventory_sha256':digest(files),'profile':plan['profile'],
        'base_C12_inventory_sha256':plan['base_C12_inventory_sha256'],'selection':plan['selection'],'request_attempts':attempts,
        'knowledge_basis':'SYNTHETIC_ONLY' if plan['profile']=='synthetic' else 'PUBLIC_HTTP_OBSERVATION_AT_CAPTURE_REPLAY_ADDS_NO_REQUESTS',
        'records':records,'pagination':chain,'failures':failures,'valid_observed_descending_window':valid,
        'window_agreement':'same_observed_native_ids_and_record_contents' if valid and forward==reverse else 'different_or_partial_observed_window',
        'previously_unobserved_native_action_ids':sorted(set(reverse)-set(forward)) if valid else [],
        'content_comparison_basis':'canonical_parsed_row_fingerprints_not_wire_bytes_or_revision_identity','historical_interval_complete':'unknown','correction_lineage':'unknown','snapshot_consistency':'unknown',
        'financial_comparison_authorized':False,'limitations':['two_direction_agreement_is_not_historical_recall','same_source_reobservation_is_not_independent_corroboration','source_update_and_deletion_lineage_unestablished']}
