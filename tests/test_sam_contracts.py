import json
import logging
from unittest.mock import Mock

import pytest
import requests

from src.evidence import EvidenceArtifact,Representation
from src.evidence_io import EvidenceError,canonical
from src.sam_contracts import ENDPOINT,collect_sam as _collect_sam,assess_sam_directory,parse_sam,public_request
from src.scope_models import ScopeRequest,ScopeStatus


KEY='SYNTHETIC_TEST_CREDENTIAL_NEVER_REAL'


def collect_sam(*args,**kwargs):
    if 'session' in kwargs: kwargs.setdefault('profile','synthetic')
    return _collect_sam(*args,**kwargs)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(requests.Session,'request',Mock(side_effect=AssertionError('no real network')))
    monkeypatch.delenv('SAM_GOV_API_KEY',raising=False)


def request(**kw):
    return ScopeRequest(piid='SYNTH-0001',agency='0001',parent_piid='PARENT',parent_agency='0002',namespace='samgov-v1',**kw)


def body(**changes):
    contract={'piid':'SYNTH-0001','subtier':{'code':'0001'},'referencedIDVPiid':'PARENT',
        'referencedIDVSubtier':{'code':'0002'},'modificationNumber':'P00001','transactionNumber':'0'}
    contract.update(changes)
    return {'awardSummary':[{'contractId':contract}],'totalRecords':'1','limit':'10','offset':'0'}


def session(raw,status=200):
    r=Mock(status_code=status,headers={})
    r.iter_content.return_value=[raw]
    return Mock(request=Mock(return_value=r))


def test_missing_credential_no_request_or_directory(tmp_path):
    with pytest.raises(EvidenceError,match='credentials_unavailable'):
        collect_sam(tmp_path/'no',request(),live=True)
    assert not (tmp_path/'no').exists()
    with pytest.raises(EvidenceError,match='opt_in'):
        collect_sam(tmp_path/'no',request())


def test_documented_capture_no_key_in_metadata_and_scope_native_strings(tmp_path,monkeypatch,caplog):
    monkeypatch.setenv('SAM_GOV_API_KEY',KEY)
    raw=canonical(body()).encode();s=session(raw)
    p=tmp_path/'sam'
    collect_sam(p,request(),live=True,session=s)
    assert s.request.call_count==1
    args,kw=s.request.call_args
    assert args==('GET',ENDPOINT) and kw['params']['api_key']==KEY
    assert not kw['allow_redirects'] and kw.get('verify') is not False
    assert kw['params']['offset']==0 and kw['params']['includeSections']=='contractId'
    assert (p/'sam-response.body').read_bytes()==raw
    assert all(KEY.encode() not in f.read_bytes() for f in p.iterdir()) and KEY not in caplog.text
    scope=assess_sam_directory(p)
    assert scope.assessments[0].status is ScopeStatus.IN_SCOPE
    assert scope.assessments[0].observed.agency.value=='0001'
    assert scope.assessments[0].record is None  # never masquerades as FPDS C4 input.


@pytest.mark.parametrize('value',[{'api_key':KEY},{'url':'https://api.sam.gov/?api_key='+KEY},{'exportToken':'SYNTH-TOKEN'}])
def test_credential_echo_or_export_tokens_never_preserved(tmp_path,monkeypatch,value):
    monkeypatch.setenv('SAM_GOV_API_KEY',KEY)
    p=tmp_path/'sam';collect_sam(p,request(),live=True,session=session(canonical(value).encode()))
    assert not (p/'sam-response.body').exists()
    assert all(KEY.encode() not in f.read_bytes() for f in p.iterdir())
    assert assess_sam_directory(p).artifact_issues


def test_sensitive_exceptions_are_sanitized(tmp_path,monkeypatch,capsys):
    monkeypatch.setenv('SAM_GOV_API_KEY',KEY)
    s=Mock(request=Mock(side_effect=ValueError(KEY)))
    with pytest.raises(EvidenceError,match='sam_transport_failed') as err:
        collect_sam(tmp_path/'sam',request(),live=True,session=s)
    assert KEY not in str(err.value) and KEY not in capsys.readouterr().out


@pytest.mark.parametrize('status',[301,403,405,429,503])
def test_no_redirect_follow_retry_or_export_fallback(tmp_path,monkeypatch,status):
    monkeypatch.setenv('SAM_GOV_API_KEY',KEY)
    s=session(canonical({'error':'synthetic unavailable'}).encode(),status)
    collect_sam(tmp_path/'sam',request(),live=True,session=s)
    assert s.request.call_count==1
    assert assess_sam_directory(tmp_path/'sam').artifact_issues


def test_schema_changes_and_numeric_identifiers_never_coerced(tmp_path,monkeypatch):
    monkeypatch.setenv('SAM_GOV_API_KEY',KEY)
    collect_sam(tmp_path/'sam',request(),live=True,session=session(canonical(body(piid=1)).encode()))
    scope=assess_sam_directory(tmp_path/'sam')
    assert scope.assessments[0].status is ScopeStatus.UNSUPPORTED


def test_tampered_capture_refused_and_namespace_not_crosswalked(tmp_path,monkeypatch):
    monkeypatch.setenv('SAM_GOV_API_KEY',KEY)
    p=tmp_path/'sam';collect_sam(p,request(),live=True,session=session(canonical(body()).encode()))
    (p/'sam-response.body').write_bytes(b'changed')
    with pytest.raises(EvidenceError,match='hash_conflict'): assess_sam_directory(p)
    with pytest.raises(EvidenceError): public_request(ScopeRequest(piid='X',agency='0001'))


def test_unknown_pagination_never_followed(tmp_path,monkeypatch):
    monkeypatch.setenv('SAM_GOV_API_KEY',KEY)
    data={**body(),'next':'https://evil.invalid/'}
    s=session(canonical(data).encode())
    collect_sam(tmp_path/'sam',request(),live=True,session=s)
    assert s.request.call_count==1 and assess_sam_directory(tmp_path/'sam').artifact_issues


def test_credential_in_headers_is_omitted_without_altering_body(tmp_path,monkeypatch):
    monkeypatch.setenv('SAM_GOV_API_KEY',KEY)
    raw=canonical(body()).encode();s=session(raw)
    s.request.return_value.headers={'Last-Modified':KEY,'Retry-After':KEY}
    p=tmp_path/'sam';collect_sam(p,request(),live=True,session=s)
    assert (p/'sam-response.body').read_bytes()==raw
    assert all(KEY.encode() not in f.read_bytes() for f in p.iterdir())
    meta=json.loads((p/'sam-response.json').read_text())
    assert meta['header_capture_rejected'] and meta['retry_after'] is None and meta['source_update_raw'] is None


def test_wire_debug_is_refused_without_request(tmp_path,monkeypatch):
    import http.client
    monkeypatch.setenv('SAM_GOV_API_KEY',KEY)
    monkeypatch.setattr(http.client.HTTPConnection,'debuglevel',1)
    s=session(canonical(body()).encode())
    with pytest.raises(EvidenceError): collect_sam(tmp_path/'sam',request(),live=True,session=s)
    s.request.assert_not_called()


def test_library_debug_logging_cannot_expose_credential(tmp_path,monkeypatch,caplog):
    monkeypatch.setenv('SAM_GOV_API_KEY',KEY)
    s=session(canonical(body()).encode())
    result=s.request.return_value
    def emit(*a,**kw):
        logging.getLogger('urllib3.connectionpool').warning('SYNTHETIC URL api_key=%s',KEY)
        return result
    s.request.side_effect=emit
    collect_sam(tmp_path/'sam',request(),live=True,session=s)
    assert KEY not in caplog.text


@pytest.mark.parametrize('data',[{'awardSummary':[],'limit':10,'offset':10,'totalRecords':10},
    {'awardSummary':[],'limit':100,'offset':0,'totalRecords':0},{'awardSummary':[],'limit':10,'offset':0,'totalRecords':-1}])
def test_unsupported_counter_semantics_never_imply_pagination_success(tmp_path,monkeypatch,data):
    monkeypatch.setenv('SAM_GOV_API_KEY',KEY)
    collect_sam(tmp_path/'sam',request(),live=True,session=session(canonical(data).encode()))
    assert assess_sam_directory(tmp_path/'sam').artifact_issues


def test_interrupted_capture_does_not_reissue_or_overwrite(tmp_path,monkeypatch):
    monkeypatch.setenv('SAM_GOV_API_KEY',KEY)
    p=tmp_path/'sam'
    with pytest.raises(KeyboardInterrupt):
        collect_sam(p,request(),live=True,session=Mock(request=Mock(side_effect=KeyboardInterrupt)))
    before={f.name:f.read_bytes() for f in p.iterdir()}
    s=session(canonical(body()).encode())
    with pytest.raises(OSError): collect_sam(p,request(),live=True,session=s)
    s.request.assert_not_called()
    assert before=={f.name:f.read_bytes() for f in p.iterdir()}
