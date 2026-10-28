from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from src.evidence_io import EvidenceError,canonical,digest
from src.history_demo import fixture,collect_fixture
from src.readiness_audit import audit_collection,inventory
from src.readiness import load_protocol
from src.readiness_holdout import collect_holdout,audit_holdout
from src.readiness_reporting import read_readiness,write_readiness
from readiness_fixtures import HoldoutTransport


@pytest.mark.parametrize('change',['missing_body','tampered_hash','checkpoint_version','malformed_xml','malformed_json'])
def test_bad_primary_evidence_abstains_without_mutation(tmp_path,change):
    a,data=fixture('equal_control');root=tmp_path/'source'
    if change=='malformed_xml': data['responses'][-1]['text']='<broken>'
    if change=='malformed_json': data['responses'][0].pop('json');data['responses'][0]['text']='{"broken":'
    collect_fixture(root,a,data)
    if change=='missing_body': (root/'c3_attempt_000000.body').unlink()
    if change=='tampered_hash': (root/'c3_attempt_000000.body').write_text('changed')
    if change=='checkpoint_version':
        path=root/'c3_checkpoint.json';doc=json.loads(path.read_text());doc['schema_version']=2;path.write_text(canonical(doc))
    before=inventory(root);result=audit_collection(root,0,a.generated_id,'synthetic/source')
    assert inventory(root)==before
    if change in ('missing_body','tampered_hash'): assert 'no_source_evidence_mutation' in result.violations
    elif change=='checkpoint_version': assert not result.processed and result.unknown_controls
    else: assert result.causes  # Unparseable body stays visible; no invented row count.


def test_source_symlink_is_rejected_without_following_it(tmp_path):
    a,data=fixture('equal_control');root=tmp_path/'source';collect_fixture(root,a,data)
    link=tmp_path/'link';link.symlink_to(root,target_is_directory=True)
    with pytest.raises((ValueError,OSError)): audit_collection(link,0,a.generated_id,'synthetic/source')


def reanchor(path):
    commit=path/'holdout-commit.json'
    files={str(f.relative_to(path)):hashlib.sha256(f.read_bytes()).hexdigest() for f in path.rglob('*') if f.is_file() and f!=commit}
    commit.write_text(canonical({'schema_type':'ReadinessHoldoutCommit','schema_version':1,'files':files})+'\n')


def test_empty_selection_cannot_hide_supported_favorable_or_unfavorable_candidates(tmp_path):
    p=replace(load_protocol(),profile='synthetic-control');out=tmp_path/'capture';t=HoldoutTransport()
    collect_holdout(out,p,[],live=True,transport=t)
    file=out/'holdout-selection.json';doc=json.loads(file.read_text());doc['selected']=[];file.write_text(canonical(doc))
    result=out/'holdout-result.json';r=json.loads(result.read_text());r['selection_sha256']=digest(doc);r['slots']=[];result.write_text(canonical(r))
    reanchor(out)
    with pytest.raises(EvidenceError,match='selection_changed'): audit_holdout(out,p,[])


@pytest.mark.parametrize('change',['request_count','expanded_limits','extra_file','capture_profile'])
def test_holdout_commit_does_not_authorize_unsupported_plan_changes(tmp_path,change):
    p=replace(load_protocol(),profile='synthetic-control');out=tmp_path/'capture';t=HoldoutTransport(error=403)
    collect_holdout(out,p,[],live=True,transport=t)
    if change=='extra_file': (out/'unregistered.txt').write_text('SYNTHETIC')
    else:
        name='holdout-result.json' if change=='request_count' else 'pilot-plan.json'
        file=out/name;doc=json.loads(file.read_text())
        if change=='request_count': doc['http_requests_reserved']=2
        elif change=='expanded_limits': doc['maximum_http_requests']=48
        else: doc['profile']='fabricated-live'
        file.write_text(canonical(doc))
    reanchor(out)
    with pytest.raises(EvidenceError): audit_holdout(out,p,[])


def test_missing_frame_timestamp_never_fabricates_valid_selection(tmp_path):
    p=replace(load_protocol(),profile='synthetic-control');out=tmp_path/'capture';base=HoldoutTransport();calls=[]
    def no_time(request,seq):
        calls.append(request);fields,raw=base(request,seq);fields['retrieved_at_utc']=None;return fields,raw
    collect_holdout(out,p,[],live=True,transport=no_time)
    assert len(calls)==1
    result=audit_holdout(out,p,[])
    assert not result.available and result.selected_count==0
    assert result.evidence and result.auxiliary_measurements[0].denominator==1
