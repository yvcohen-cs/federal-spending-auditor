"""SAM Contract Awards v1 bounded first-page boundary; no FPDS/financial aliasing."""
import argparse
import html
import http.client
import logging
import os
from contextlib import contextmanager
from urllib.parse import unquote

import requests

from .collection import CollectionLimits
from .collection_sources import HTTPTransport
from .evidence import EvidenceArtifact, EvidenceRecordRef, Representation, SourceIdentifier
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json
from .identity_matching import component, agency_component
from .matching_models import MatchEvidenceReference
from .pilot_store import PilotStore
from .scope_models import ScopeRequest, ObservedIdentity, ScopeRun, assessment, conflicting_occurrences

ENDPOINT="https://api.sam.gov/contract-awards/v1/search"
VERSION="sam-contract-awards-v1-first-page"


def _plan(requested,limit,profile):
    return {'schema_type':'SAMCollectionPlan','schema_version':1,'adapter_version':VERSION,
        'config':{'max_run_bytes':4*1024*1024},'requested':requested.to_dict(),'request':public_request(requested,limit),
        'authentication':'environment_material_omitted','maximum_requests':1,'maximum_pages':1,'profile':profile}


def public_request(requested,limit=10):
    if requested.namespace!='samgov-v1' or type(limit) is not int or not 1<=limit<=10:
        raise EvidenceError('explicit_sam_native_request_required')
    p={'piid':requested.piid,'piidSubtierCode':requested.agency,'limit':limit,'offset':0,'includeSections':'contractId','awardOrIDV':'Award'}
    if requested.parent_piid is not None:
        p.update(referencedIdvPiid=requested.parent_piid,referencedIdvPIIDSubtierCode=requested.parent_agency)
    if requested.modification is not None: p['modificationNumber']=requested.modification
    return {'source':'samgov','endpoint':ENDPOINT,'method':'GET','parameters':p}


def _safe_body(raw,key):
    if raw is None: return True
    text=raw.decode('utf-8',errors='replace')
    if key in text or key in unquote(html.unescape(text)): return False
    try:
        doc=strict_json(raw)
    except ValueError:
        return False  # Unsupported/error payloads may echo a credential URL.
    if not isinstance(doc,dict) or set(doc)!={'awardSummary','totalRecords','limit','offset'} or not isinstance(doc['awardSummary'],list):
        return False
    def safe(value):
        if isinstance(value,dict):
            for name,nested in value.items():
                normalized=''.join(c for c in name.lower() if c.isalpha())
                if any(s in normalized for s in ('apikey','token','authorization','password','cookie','secret')) or not safe(nested): return False
        elif isinstance(value,list): return all(safe(v) for v in value)
        elif isinstance(value,str): return key not in value and key not in unquote(html.unescape(value))
        return True
    return safe(doc)


@contextmanager
def _quiet_client():
    # Requests normally logs no credentials; explicitly suppress its connection
    # debug output, because the official API requires api_key in the query.
    if http.client.HTTPConnection.debuglevel:
        raise EvidenceError('sam_wire_debug_must_be_disabled')
    class Suppress(logging.Filter):
        def filter(self,record): return False
    f=Suppress()
    loggers=[logging.getLogger(n) for n in ('urllib3.connectionpool','requests.packages.urllib3.connectionpool')]
    for logger in loggers: logger.addFilter(f)
    try: yield
    finally:
        for logger in loggers: logger.removeFilter(f)


def collect_sam(path,requested,*,live=False,limit=10,session=None,profile='live'):
    if not live: raise EvidenceError('sam_live_opt_in_required')
    if profile not in ('live','synthetic') or (session is not None)!=(profile=='synthetic'):
        raise EvidenceError('explicit_sam_fixture_profile_required')
    key=os.environ.get('SAM_GOV_API_KEY')
    if not key: raise EvidenceError('sam_credentials_unavailable')
    if len(key)>4096 or not key.strip() or any(ord(c)<=32 or ord(c)==127 for c in key):
        raise EvidenceError('sam_credentials_invalid')
    request=public_request(requested,limit)
    if key in canonical(request): raise EvidenceError('sam_credential_in_public_context')
    plan=_plan(requested,limit,profile)
    actual=session or requests.Session()
    class CredentialSession:
        def request(self,method,endpoint,**kwargs):
            # Credential material never enters request provenance or exceptions.
            kwargs['params']={**kwargs['params'],'api_key':key}
            return actual.request(method,endpoint,**kwargs)
    limits=CollectionLimits(max_response_bytes=1024*1024,timeout_seconds=10.0,pace_seconds=0.5,retries=0)
    with PilotStore(path,plan) as store:
        store.write('sam-request-reserved.json',{'request':request,'maximum_attempts':1})
        try:
            with _quiet_client():
                fields,raw=HTTPTransport(limits.to_dict(),session=CredentialSession())(request,0)
        except Exception:
            raise EvidenceError('sam_transport_failed_no_sensitive_exception') from None
        header_rejected=False
        for name in ('retry_after','source_update_raw'):
            value=fields.get(name)
            if isinstance(value,str) and (key in value or key in unquote(html.unescape(value))):
                fields[name]=None;header_rejected=True
        rejected=not _safe_body(raw,key) or fields['status'] is not None and not 200<=fields['status']<300
        if rejected: raw=None
        if raw is not None: store.write_bytes('sam-response.body',raw)
        import hashlib
        metadata={**fields,'body_sha256':hashlib.sha256(raw).hexdigest() if raw is not None else None,
            'capture_rejected':rejected,'authentication_material_preserved':False,
            'header_capture_rejected':header_rejected,
            'representation':'application_response_bytes_not_wire_capture'}
        store.write('sam-response.json',metadata)
        files=store.inventory()
        store.write('sam-commit.json',{'schema_type':'SAMCaptureCommit','schema_version':1,'files':files})
    return metadata


def _counter(value):
    if type(value) is int and value>=0: return value
    if isinstance(value,str) and value.isascii() and value.isdigit() and len(value)<=10: return int(value)
    raise EvidenceError('unsupported_sam_pagination_metadata')


def parse_sam(raw,requested,artifact,*,limit=10):
    body=strict_json(raw)
    if (not isinstance(body,dict) or set(body)-{'awardSummary','totalRecords','limit','offset'}
            or not isinstance(body.get('awardSummary'),list) or len(body['awardSummary'])>limit
            or _counter(body.get('offset'))!=0 or _counter(body.get('limit'))!=limit
            or _counter(body.get('totalRecords'))<len(body['awardSummary'])):
        raise EvidenceError('unsupported_sam_search_response')
    result=[]
    observation='observation:v1:'+digest({'version':1,'source':'samgov','endpoint':artifact.endpoint,'method':artifact.method,
        'request_json':artifact.request_json,'retrieved_at_utc':artifact.retrieved_at_utc,'representation':artifact.representation.value})
    for index,row in enumerate(body['awardSummary']):
        c=row.get('contractId') if isinstance(row,dict) else None
        valid=isinstance(c,dict)
        c=c if valid else {}
        agency=c.get('subtier');parent=c.get('referencedIDVSubtier')
        if agency is not None and not isinstance(agency,dict) or parent is not None and not isinstance(parent,dict): valid=False
        values={'piid':c.get('piid'),'agency':agency.get('code') if isinstance(agency,dict) else None,
            'parent_piid':c.get('referencedIDVPiid'),'parent_agency':parent.get('code') if isinstance(parent,dict) else None,
            'modification':c.get('modificationNumber'),'transaction':c.get('transactionNumber')}
        if any(v is not None and not isinstance(v,str) for v in values.values()): valid=False
        observed=ObservedIdentity(**{k:agency_component(component(v)) if k in ('agency','parent_agency') else component(v) for k,v in values.items()})
        native=SourceIdentifier(source='samgov',namespace='contractId.piid',value=values['piid']) if component(values['piid']).value is not None else None
        ref=EvidenceRecordRef(source='samgov',artifact_id=artifact.artifact_id,locator=f'/awardSummary/{index}',native_id=native)
        evidence=MatchEvidenceReference(reference=ref,artifact=artifact,observation_id=observation,
            metadata_paths=('pilot-plan.json','sam-response.json'))
        result.append(assessment(requested,observed,evidence,digest(row),supported=valid,original_identity_json=canonical({'contractId':c,'contractId_present':isinstance(row,dict) and 'contractId' in row})))
    conflicts=conflicting_occurrences(result)
    return tuple(sorted((assessment(a.requested,a.observed,a.evidence,a.content_sha256,supported=a.supported,
        conflicting=a.assessment_id in conflicts,original_identity_json=a.original_identity_json) for a in result),key=lambda a:a.assessment_id))


def assess_sam_directory(path):
    with EvidenceRoot(path,max_bytes=2*1024*1024,max_total_bytes=4*1024*1024) as root:
        names=root.discover();snapshots={n:root.read(n) for n in names}
        required={'pilot-plan.json','sam-request-reserved.json','sam-response.json','sam-commit.json'}
        if not required<=set(names) or set(names)-required-{'sam-response.body'}:
            raise EvidenceError('unsupported_sam_capture_inventory')
        commit=strict_json(snapshots['sam-commit.json'].data)
        expected={'schema_type':'SAMCaptureCommit','schema_version':1,'files':{n:s.byte_sha256 for n,s in snapshots.items() if n!='sam-commit.json'}}
        if digest(commit)!=digest(expected): raise EvidenceError('sam_capture_hash_conflict')
        plan=strict_json(snapshots['pilot-plan.json'].data)
        requested=ScopeRequest.from_dict(plan['requested'])
        if plan.get('profile') not in ('live','synthetic') or digest(plan)!=digest(_plan(requested,plan['request']['parameters']['limit'],plan['profile'])):
            raise EvidenceError('unsupported_sam_capture_plan')
        reservation=strict_json(snapshots['sam-request-reserved.json'].data)
        if digest(reservation)!=digest({'request':plan['request'],'maximum_attempts':1}): raise EvidenceError('sam_reservation_conflict')
        meta=strict_json(snapshots['sam-response.json'].data)
        if meta['authentication_material_preserved'] is not False or meta['representation']!='application_response_bytes_not_wire_capture':
            raise EvidenceError('unsupported_sam_capture_representation')
        issues=[];rows=()
        if meta['capture_rejected'] or 'sam-response.body' not in snapshots or meta['error_code'] or not meta['body_complete'] or meta['status'] is None or not 200<=meta['status']<300:
            issues=['sam_response_unavailable_or_unusable']
        else:
            body=snapshots['sam-response.body']
            if body.byte_sha256!=meta['body_sha256']: raise EvidenceError('sam_body_hash_conflict')
            artifact=EvidenceArtifact(source='samgov',relative_path='sam-response.body',sha256=body.byte_sha256,
                representation=Representation.RESPONSE_BYTES,hash_basis='original_bytes',endpoint=ENDPOINT,method='GET',
                request_json=canonical(plan['request']['parameters']),retrieved_at_utc=meta['retrieved_at_utc'],http_status=meta['status'],
                limitations=('application_response_bytes_not_wire_capture','credential_material_omitted_from_request_context','shared_fpds_lineage_not_independent_corroboration','history_and_freshness_unknown')+ (('synthetic_fixture_only',) if plan['profile']=='synthetic' else ()))
            try: rows=parse_sam(body.data,requested,artifact,limit=plan['request']['parameters']['limit'])
            except (ValueError,TypeError,KeyError): issues=['unsupported_sam_response_schema']
        for n,s in snapshots.items():
            if root.read(n,recheck=True).byte_sha256!=s.byte_sha256: raise EvidenceError('sam_evidence_changed')
        return ScopeRun(requested=requested,input_manifest_sha256=digest(commit),assessments=rows,artifact_issues=tuple(issues))


def main(argv=None):
    p=argparse.ArgumentParser(description='Opt-in SAM Contract Awards first-page prototype; no automatic legacy replacement.')
    p.add_argument('--live',action='store_true',required=True);p.add_argument('--request',required=True);p.add_argument('--run-dir',required=True)
    args=p.parse_args(argv)
    try:
        from .collect_evidence import load_input
        requested=ScopeRequest.from_dict(load_input(args.request))
        collect_sam(args.run_dir,requested,live=args.live)
        scope=assess_sam_directory(args.run_dir)
        print(canonical({'metrics':scope.metrics,'substantive_sha256':scope.substantive_sha256,'live_functionality':'unverified_prototype'}))
        return 1
    except KeyboardInterrupt: return 130
    except EvidenceError as exc:
        print(canonical({'error_code':exc.code,'exit_code':2}));return 2
    except Exception:
        print(canonical({'error_code':'sam_capture_unavailable_or_invalid','exit_code':2}))
        return 2


if __name__=='__main__': raise SystemExit(main())
