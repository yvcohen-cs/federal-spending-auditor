"""Append-only bounded SAM research journal. No production collector integration."""
from dataclasses import dataclass
import hashlib
import base64
import http.client
import html
import os
from pathlib import Path
import re
import time
from urllib.parse import unquote

import requests

from .evidence import Schema, EvidenceArtifact, Representation, _hash, _timestamp
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, parts, strict_json
from .pilot_store import PilotStore
from .sam_contracts import ENDPOINT, _quiet_client
from .sam_validation_models import SAMPage, parse_page
from .scope_models import ScopeRequest

VERSION='sam-research-capture-v1'
PROTOCOL=Path(__file__).resolve().parents[1]/'docs'/'sam-validation-protocol-v1.json'
PROTOCOL_SHA='fc079d50e894be93f57d5e14a77cf63a4001503f6f18a532f99dfdb3e134dfb2'


def protocol():
    value=strict_json(PROTOCOL.read_bytes())
    if digest(value)!=PROTOCOL_SHA: raise EvidenceError('sam_validation_protocol_changed')
    return value


@dataclass(frozen=True,kw_only=True)
class SAMResearchSelection(Schema):
    subjects: tuple[ScopeRequest,...]
    limit: int = 2
    pagination_rule: str = 'unvalidated'
    profile: str = 'live'

    def validate(self):
        if not 1<=len(self.subjects)<=3 or len({canonical(s.to_dict()) for s in self.subjects})!=len(self.subjects):
            raise ValueError('one_to_three_distinct_preselected_native_subjects_required')
        if not 1<=self.limit<=10 or self.profile not in ('live','synthetic'):
            raise ValueError('bounded_explicit_SAM_profile_required')
        if self.pagination_rule not in ('unvalidated','synthetic_row_offset','synthetic_page_index') or self.profile=='live' and self.pagination_rule!='unvalidated':
            raise ValueError('live_offset_contract_unvalidated_no_continuation')
        for subject in self.subjects:
            if subject.namespace!='samgov-v1': raise ValueError('explicit_SAM_namespace_required')
            for v in (subject.piid,subject.agency,subject.parent_piid,subject.parent_agency,subject.modification,subject.transaction):
                if v is not None and (any(c in v for c in '&|{}^\\~![]"?%#=') or v!=v.strip()):
                    raise ValueError('unsafe_SAM_query_token_native_value_not_modified')


def public_request(subject,limit,offset):
    from .sam_contracts import public_request as legacy_request
    request=legacy_request(subject,limit)
    request['parameters'].update(includeSections='contractId,coreData,awardDetails',offset=offset)
    return request


def plan_for(selection):
    return {'schema_type':'SAMResearchPlan','schema_version':1,'version':VERSION,'protocol_sha256':digest(protocol()),
        'selection':selection.to_dict(),'config':{'max_run_bytes':32*1024*1024},
        'maximum_requests':12,'maximum_pages_per_subject':2,'maximum_response_bytes':1048576,
        'timeout_seconds':10,'retries':0,'redirects':False,'authentication_material_preserved':False,
        'continuation_contract':'unvalidated_live_first_page_only','source_wide_completeness':'unknown'}


def secret_free(value,key=None):
    """No key, credential field, signed URL or export token is journaled.

    Safe JSON bodies remain byte-exact application payloads. Rejected bodies are
    omitted, never edited and called raw. Unknown encodings fail closed.
    """
    variants=(key,base64.b64encode(key.encode()).decode(),base64.urlsafe_b64encode(key.encode()).decode(),key.encode().hex()) if key else ()
    def strings_safe(text):
        for _ in range(5):
            if any(v in text for v in variants): return False
            if re.search(r'(?i)(api[_%-]*key|authorization|access[_-]?token|signature|password|cookie)\s*(?:=|:|%3d)',text): return False
            decoded=unquote(html.unescape(text))
            if decoded==text: break
            text=decoded
        if unquote(html.unescape(text))!=text: return False
        return not any(v in text for v in variants)
    if isinstance(value,dict):
        for name,item in value.items():
            normalized=''.join(c for c in name.lower() if c.isalpha())
            if any(v in normalized for v in ('apikey','authorization','token','password','secret','cookie','signature')):
                return False
            if not strings_safe(name) or not secret_free(item,key): return False
        return True
    if isinstance(value,list): return all(secret_free(v,key) for v in value)
    return not isinstance(value,str) or strings_safe(value)


def body_safe(raw,key=None):
    try: return secret_free(strict_json(raw),key)
    except (ValueError,TypeError,UnicodeError,RecursionError): return False


def credential():
    key=os.environ.get('SAM_GOV_API_KEY')
    if not key: raise EvidenceError('sam_credentials_unavailable')
    if len(key)>4096 or any(ord(c)<=32 or ord(c)==127 for c in key):
        raise EvidenceError('sam_credentials_invalid')
    return key


def wire_debug_enabled():
    from urllib3 import connection
    return any(c.debuglevel for c in (http.client.HTTPConnection,http.client.HTTPSConnection,connection.HTTPConnection,connection.HTTPSConnection))


class SAMResearchTransport:
    def __init__(self,key,session=None):
        if session is not None: raise EvidenceError('injected_live_session_forbidden')
        self.key=key
        self.session=requests.Session()
        # No transparent adapter-level retries; preserve inherited proxy/CA.
        for adapter in self.session.adapters.values():
            adapter.max_retries=0

    def __call__(self,request,sequence):
        from .collection_sources import utcnow
        response=None;raw=bytearray();status=None;complete=False;error=None;headers={};header_rejected=False
        try:
            if wire_debug_enabled(): raise EvidenceError('sam_wire_debug_must_be_disabled')
            with _quiet_client():
                response=self.session.request('GET',ENDPOINT,params={**request['parameters'],'api_key':self.key},
                    timeout=(10,10),allow_redirects=False,stream=True)
                status=response.status_code
                for name in ('Content-Type','ETag','Last-Modified','Retry-After','X-API-Version'):
                    v=response.headers.get(name)
                    if isinstance(v,str) and len(v)<=512 and not any(ord(c)<32 or ord(c)==127 for c in v) and secret_free(v,self.key):
                        headers[name.lower()]=v
                    elif v is not None: header_rejected=True
                for chunk in response.iter_content(65536):
                    remaining=1048576-len(raw);raw.extend(chunk[:remaining])
                    if len(chunk)>remaining:
                        error='response_size_limit';break
                else: complete=True
        except requests.exceptions.SSLError: error='tls_error'
        except requests.Timeout: error='timeout'
        except requests.RequestException: error='request_error'
        except Exception: error='transport_error_sensitive_details_omitted'
        finally:
            if response is not None: response.close()
        return {'status':status,'retrieved_at_utc':utcnow() if status is not None else None,
            'body_complete':complete,'error_code':error,'headers':headers,'header_capture_rejected':header_rejected},bytes(raw) if status is not None else None


def artifact_for(name,raw,request,meta,profile):
    return EvidenceArtifact(source='samgov',relative_path=name,sha256=hashlib.sha256(raw).hexdigest(),
        representation=Representation.RESPONSE_BYTES,hash_basis='original_bytes',endpoint=ENDPOINT,method='GET',
        request_json=canonical(request['parameters']),retrieved_at_utc=meta['retrieved_at_utc'],http_status=meta['status'],
        limitations=('application_response_bytes_not_wire_capture','credential_material_omitted_from_request_context',
            'shared_procurement_lineage_not_independent_corroboration','history_revision_and_freshness_unknown')+
            (('synthetic_fixture_only',) if profile=='synthetic' else ()))


def pagination_issue(page,previous,seen):
    if previous and page.total!=previous.total: return 'changing_total_count'
    contents=[r.content_sha256 for r in page.records]
    if any(c in seen for c in contents) or len(set(contents))!=len(contents): return 'duplicate_page_content_occurrences'
    if page.pagination_rule=='unvalidated': return 'offset_contract_unvalidated_stop'
    return None


def collect(path,selection,*,live=False,fixture_transport=None,sleep=time.sleep):
    if not live: raise EvidenceError('sam_research_explicit_opt_in_required')
    if (fixture_transport is not None)!=(selection.profile=='synthetic'):
        raise EvidenceError('synthetic_transport_profile_required')
    key=credential() if selection.profile=='live' else None
    plan=plan_for(selection)
    if not secret_free(plan,key): raise EvidenceError('unsafe_sam_public_plan')
    if selection.profile=='live':
        if wire_debug_enabled(): raise EvidenceError('sam_wire_debug_must_be_disabled')
    transport=fixture_transport or SAMResearchTransport(key)
    attempts=0;pages=[];stop=None
    with PilotStore(path,plan) as store:
        for index,subject in enumerate(selection.subjects):
            previous=None;seen=set()
            for page_index in range(2):
                if attempts>=12: stop='request_cap';break
                offset=0 if page_index==0 else selection.limit if selection.pagination_rule=='synthetic_row_offset' else 1
                request=public_request(subject,selection.limit,offset)
                name=f'sam-attempt-{attempts:03d}';attempts+=1
                store.write(name+'-reserved.json',{'schema_version':1,'subject_index':index,'page_index':page_index,
                    'request':request,'maximum_attempts':1})
                # A pending reservation without completion is uncertain; never
                # automatically reissue it or declare the run complete.
                if selection.profile=='live' and attempts>1: sleep(0.5)
                try:
                    fields,raw=transport(request,attempts-1)
                except KeyboardInterrupt:
                    raise
                except Exception:
                    fields={'status':None,'retrieved_at_utc':None,'body_complete':False,'error_code':'transport_error_sensitive_details_omitted','headers':{}}
                    raw=None
                # Validate untrusted transport outputs without persisting error strings.
                status=fields.get('status');stamp=fields.get('retrieved_at_utc');headers=fields.get('headers',{})
                valid=(status is None or type(status) is int and 100<=status<=599) and type(fields.get('body_complete')) is bool
                if status is None and (raw is not None or fields.get('body_complete') is True): valid=False
                try:
                    _timestamp(stamp)
                    if status is not None and stamp is None: valid=False
                except (ValueError,TypeError): valid=False
                if not valid: raise EvidenceError('invalid_sam_transport_metadata')
                allowed_errors=(None,'tls_error','timeout','request_error','response_size_limit','transport_error_sensitive_details_omitted')
                error=fields.get('error_code') if fields.get('error_code') in allowed_errors else 'transport_error_sensitive_details_omitted'
                safe_headers={n:v for n,v in headers.items() if n in ('content-type','etag','last-modified','retry-after','x-api-version')
                    and isinstance(v,str) and len(v)<=512 and not any(ord(c)<32 or ord(c)==127 for c in v) and secret_free(v,key)} if isinstance(headers,dict) else {}
                rejected=raw is not None and (not isinstance(raw,bytes) or len(raw)>1048576 or not body_safe(raw,key))
                if rejected: raw=None
                if raw is not None: store.write_bytes(name+'.body',raw)
                meta={'schema_type':'SAMResearchResponse','schema_version':1,'request':request,'subject_index':index,'page_index':page_index,
                    'status':status,'retrieved_at_utc':stamp,'body_complete':fields['body_complete'],'error_code':error,
                    'headers':safe_headers,'header_capture_rejected':safe_headers!=headers or fields.get('header_capture_rejected') is True,'capture_rejected':rejected,
                    'body_sha256':hashlib.sha256(raw).hexdigest() if raw is not None else None,
                    'authentication_material_preserved':False,'representation':'application_response_bytes_not_wire_capture'}
                store.write(name+'.json',meta)
                if status in (401,403): stop='authentication_failure'
                elif error or status is None or not 200<=status<300 or not fields['body_complete'] or rejected or raw is None: stop='source_error_or_unsafe_capture'
                if stop: break
                try:
                    parsed=parse_page(raw,subject,artifact_for(name+'.body',raw,request,meta,selection.profile),name+'.json',
                        offset=offset,limit=selection.limit,pagination_rule=selection.pagination_rule)
                    if any(not r.supported_schema for r in parsed.records): raise ValueError('unsupported_record_schema')
                    if safe_headers.get('x-api-version') not in (None,'v1','1.0'): raise ValueError('unsupported_api_version')
                except (ValueError,TypeError,KeyError): stop='unexpected_schema_or_pagination';break
                pages.append({'subject_index':index,'page_index':page_index,'response':name+'.json'})
                stop=pagination_issue(parsed,previous,seen)
                if stop: break
                seen.update(r.content_sha256 for r in parsed.records);previous=parsed
                if parsed.bounded_query_terminal is True: break
                if page_index==1: stop='page_cap_unverified_coverage'
            if stop: break
        result={'schema_type':'SAMResearchResult','schema_version':1,'attempts_reserved':attempts,'pages':pages,
            'stop_reason':stop,'collection_state':'bounded_capture_closed_not_history_complete',
            'history':'unknown','freshness':'unknown','source_wide_completeness':'unknown'}
        store.write('sam-result.json',result)
        store.write('sam-research-commit.json',{'schema_type':'SAMResearchCommit','schema_version':1,'files':store.inventory()})
    return result


def replay(path):
    """Primary bytes and controls are revalidated; no credential is read here."""
    with EvidenceRoot(path,max_bytes=2*1024*1024,max_total_bytes=32*1024*1024,max_files=60) as root:
        snapshots={n:root.read(n) for n in root.discover()}
        names=set(snapshots)
        required={'pilot-plan.json','sam-result.json','sam-research-commit.json'}
        if not required<=names: raise EvidenceError('interrupted_sam_capture_no_trusted_completion')
        if any(n not in required and re.fullmatch(r'sam-attempt-[0-9]{3}(?:-reserved\.json|\.json|\.body)',n) is None for n in names):
            raise EvidenceError('unsupported_sam_research_inventory')
        expected={'schema_type':'SAMResearchCommit','schema_version':1,'files':{n:s.byte_sha256 for n,s in snapshots.items() if n!='sam-research-commit.json'}}
        if strict_json(snapshots['sam-research-commit.json'].data)!=expected: raise EvidenceError('sam_research_hash_conflict')
        plan=strict_json(snapshots['pilot-plan.json'].data);selection=SAMResearchSelection.from_dict(plan['selection'])
        if plan!=plan_for(selection): raise EvidenceError('sam_research_plan_conflict')
        result=strict_json(snapshots['sam-result.json'].data)
        n=result['attempts_reserved']
        if type(n) is not int or not 1<=n<=min(12,len(selection.subjects)*2): raise EvidenceError('sam_request_budget_conflict')
        expected_names=set(required)
        pages=[];issues=[];last_subject=0;previous={};seen={};computed_stop=None;parsed_refs=[]
        for i in range(n):
            name=f'sam-attempt-{i:03d}';expected_names.update((name+'-reserved.json',name+'.json'))
            if name+'-reserved.json' not in names or name+'.json' not in names: raise EvidenceError('uncertain_sam_reservation')
            reservation=strict_json(snapshots[name+'-reserved.json'].data);meta=strict_json(snapshots[name+'.json'].data)
            index=reservation['subject_index'];page_index=reservation['page_index']
            if type(index) is not int or not 0<=index<len(selection.subjects) or type(page_index) is not int or page_index not in (0,1):
                raise EvidenceError('unsupported_sam_subject_page_context')
            if i==0 and (index,page_index)!=(0,0) or i>0 and (index,page_index) not in ((last_subject,1),(last_subject+1,0)):
                raise EvidenceError('sam_capture_order_conflict')
            if computed_stop is not None: raise EvidenceError('request_after_sam_stop')
            if page_index==1 and (index not in previous or selection.pagination_rule=='unvalidated' or previous[index].bounded_query_terminal is True):
                raise EvidenceError('unjustified_sam_continuation')
            if index>last_subject and previous.get(last_subject) is not None and previous[last_subject].bounded_query_terminal is not True:
                raise EvidenceError('sam_subject_advanced_before_terminal')
            offset=0 if page_index==0 else selection.limit if selection.pagination_rule=='synthetic_row_offset' else 1
            req=public_request(selection.subjects[index],selection.limit,offset)
            if reservation!={'schema_version':1,'subject_index':index,'page_index':page_index,'request':req,'maximum_attempts':1}:
                raise EvidenceError('sam_reservation_request_conflict')
            fields={'schema_type','schema_version','request','subject_index','page_index','status','retrieved_at_utc','body_complete','error_code','headers','header_capture_rejected','capture_rejected','body_sha256','authentication_material_preserved','representation'}
            if (set(meta)!=fields or meta['schema_type']!='SAMResearchResponse' or type(meta['schema_version']) is not int or meta['schema_version']!=1
                    or meta['request']!=req or meta['subject_index']!=index or meta['page_index']!=page_index
                    or meta['authentication_material_preserved'] is not False or meta['representation']!='application_response_bytes_not_wire_capture'
                    or any(type(meta[k]) is not bool for k in ('body_complete','header_capture_rejected','capture_rejected'))):
                raise EvidenceError('sam_response_metadata_conflict')
            _timestamp(meta['retrieved_at_utc'])
            status=meta['status']
            if status is None and (meta['body_complete'] or meta['body_sha256'] is not None or meta['retrieved_at_utc'] is not None):
                raise EvidenceError('contradictory_sam_unavailable_response')
            if meta['capture_rejected'] and meta['body_sha256'] is not None: raise EvidenceError('rejected_body_cannot_be_preserved_as_raw')
            if status is not None and (type(status) is not int or not 100<=status<=599 or meta['retrieved_at_utc'] is None):
                raise EvidenceError('invalid_sam_response_status')
            if (type(meta['subject_index']) is not int or type(meta['page_index']) is not int
                    or not isinstance(meta['headers'],dict) or set(meta['headers'])-{'content-type','etag','last-modified','retry-after','x-api-version'}
                    or any(not isinstance(v,str) or len(v)>512 or any(ord(c)<32 or ord(c)==127 for c in v) for v in meta['headers'].values())
                    or meta['error_code'] not in (None,'tls_error','timeout','request_error','response_size_limit','transport_error_sensitive_details_omitted')):
                raise EvidenceError('unsupported_sam_metadata_fields')
            if not secret_free(meta): raise EvidenceError('unsafe_sam_metadata')
            raw=None
            if name+'.body' in snapshots:
                expected_names.add(name+'.body');snap=snapshots[name+'.body'];raw=snap.data
                if snap.byte_sha256!=meta['body_sha256'] or len(raw)>1048576 or not body_safe(raw): raise EvidenceError('sam_response_body_conflict')
            elif meta['body_sha256'] is not None: raise EvidenceError('missing_sam_response_body')
            if status in (401,403): computed_stop='authentication_failure'
            elif meta['error_code'] or status is None or not 200<=status<300 or not meta['body_complete'] or meta['capture_rejected'] or raw is None:
                computed_stop='source_error_or_unsafe_capture'
            else:
                try:
                    if meta['headers'].get('x-api-version') not in (None,'v1','1.0'): raise ValueError('unsupported_api_version')
                    page=parse_page(raw,selection.subjects[index],artifact_for(name+'.body',raw,req,meta,selection.profile),name+'.json',
                        offset=offset,limit=selection.limit,pagination_rule=selection.pagination_rule)
                    # Unsupported records remain inspectable; the capture stops.
                    pages.append((index,page_index,page))
                    if any(not r.supported_schema for r in page.records): raise ValueError('unsupported_record_schema')
                    parsed_refs.append({'subject_index':index,'page_index':page_index,'response':name+'.json'})
                    computed_stop=pagination_issue(page,previous.get(index),seen.setdefault(index,set()))
                    seen[index].update(r.content_sha256 for r in page.records);previous[index]=page
                    if computed_stop is None and page_index==1 and page.bounded_query_terminal is not True: computed_stop='page_cap_unverified_coverage'
                except (ValueError,TypeError,KeyError): computed_stop='unexpected_schema_or_pagination'
            if computed_stop is not None: issues.append(computed_stop)
            last_subject=index
        expected_result={'schema_type':'SAMResearchResult','schema_version':1,'attempts_reserved':n,'pages':parsed_refs,
            'stop_reason':computed_stop,'collection_state':'bounded_capture_closed_not_history_complete',
            'history':'unknown','freshness':'unknown','source_wide_completeness':'unknown'}
        if result!=expected_result or names!=expected_names: raise EvidenceError('sam_capture_result_or_inventory_conflict')
        if computed_stop is None and (last_subject!=len(selection.subjects)-1 or previous[last_subject].bounded_query_terminal is not True):
            raise EvidenceError('sam_capture_silently_dropped_subjects')
        if {n:root.read(n,recheck=True).byte_sha256 for n in root.discover()}!={n:s.byte_sha256 for n,s in snapshots.items()}:
            raise EvidenceError('sam_evidence_changed')
    return selection,tuple(pages),result,digest(expected),tuple(issues)
