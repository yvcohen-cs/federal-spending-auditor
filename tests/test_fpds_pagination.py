"""Authored VERSION fixtures and adversarial continuation scope, no live data."""
from dataclasses import replace
from unittest.mock import Mock
from urllib.parse import urlencode
from xml.sax.saxutils import escape

import pytest
import requests

from src.collection import CollectionLimits, SelectedAward, collect_selected, make_plan
from src.collection_ingestion import validate_request
from src.collection_sources import FPDS, FixtureTransport, parse_page, request_for, safe_next
from src.collection_store import CollectionStore
from src.evidence_ingestion import inspect_directory
from src.evidence_io import EvidenceError, canonical, digest, strict_json
from src.financial_ingestion import reconcile_collection
from src.fpds_probe import main as probe_main, probe
from src.research_demo import demo_case


AWARD=SelectedAward(generated_id="CONT_AWD_SYNTH-0001_0001_PARENT_0002",piid="SYNTH-0001",agency_id="0001",parent_piid="PARENT",parent_agency_id="0002")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(requests.Session,"request",Mock(side_effect=AssertionError("network forbidden")))


def request():
    return request_for("fpds",AWARD.to_dict(),1,10)


def href(offset=10,**changes):
    params={"FEEDNAME":"PUBLIC","q":request()["parameters"]["q"],"VERSION":"1.5.3","s":"FPDS","start":str(offset)}
    params.update(changes)
    return FPDS+"?"+urlencode(params)


def page(next_link=None,mod="0"):
    link='' if next_link is None else '<link rel="next" href="'+escape(next_link,{'"':'&quot;'})+'"/>'
    return '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:f="https://www.fpds.gov/FPDS">'+link+\
        '<entry><content><f:award><f:awardID><f:awardContractID><f:agencyID>0001</f:agencyID><f:PIID>SYNTH-0001</f:PIID>'+\
        f'<f:modNumber>{mod}</f:modNumber><f:transactionNumber>0</f:transactionNumber></f:awardContractID>'+\
        '<f:referencedIDVID><f:agencyID>0002</f:agencyID><f:PIID>PARENT</f:PIID></f:referencedIDVID></f:awardID></f:award></content></entry></feed>'


def scenario(*texts):
    return {"schema_version":1,"responses":[{"source":"fpds","text":t,"retrieved_at_utc":f"2025-01-0{i+1}T00:00:00Z"} for i,t in enumerate(texts)]}


def collect(path,data,**kwargs):
    return collect_selected(path,(AWARD,),sources=("fpds",),limits=CollectionLimits(max_awards=1,max_pages=3,max_requests=3,
        max_records_per_source_award=30,max_records_total=30,retries=0,pace_seconds=0.0),
        transport=FixtureTransport(data),profile="fixture:"+digest(data),sleep=lambda _:None,**kwargs)


def snapshot(path):
    return {p.relative_to(path).as_posix():p.read_bytes() for p in path.rglob("*") if p.is_file()}


def test_version_backend_continuation_reproduces_documented_structure():
    accepted=safe_next(href(),request())
    assert accepted=={"start":10,"s":"FPDS","VERSION":"1.5.3"}
    following=request_for("fpds",AWARD.to_dict(),2,10,accepted)
    assert following["parameters"]["q"]==request()["parameters"]["q"]
    assert safe_next("?start=20",following)=={"start":20,"s":"FPDS","VERSION":"1.5.3"}


@pytest.mark.parametrize("version",["", "1.5", "1.5.2", "1.5.4", "01.5.3", "1.5.3 ", "1.5.3/../../", "1"*300, "opaque-token", "1.5.3\x00"])
def test_unknown_or_malformed_versions_remain_unsupported(version):
    with pytest.raises(EvidenceError):
        safe_next(href(VERSION=version),request())


@pytest.mark.parametrize("suffix",["&q=OTHER","&q=", "&VERSION=1.5.3", "&VERSION=1.5.2", "&s=FPDS", "&unknown=1"])
def test_duplicate_even_identical_and_unknown_parameters_rejected(suffix):
    with pytest.raises(EvidenceError):
        safe_next(href()+suffix,request())


@pytest.mark.parametrize("q",['PIID:"OTHER" AND CONTRACTING_AGENCY_ID:"0001"','PIID:"SYNTH-0001"',
    'PIID:"SYNTH-0001" AND CONTRACTING_AGENCY_ID:"9999"','PIID:* OR *:*'])
def test_piid_agency_or_query_rewrite_cannot_widen_scope(q):
    with pytest.raises(EvidenceError,match="scope_conflict"):
        safe_next(href(q=q),request())


@pytest.mark.parametrize("removed",['PARENT_PIID:"PARENT"','SIGNED_DATE:[2024/01/01,2024/12/31]','AWARD_TYPE:"C"'])
def test_all_original_parent_date_type_restrictions_are_lexically_pinned(removed):
    r=request()
    original=r["parameters"]["q"]
    r["parameters"]["q"]+=" AND "+removed
    with pytest.raises(EvidenceError,match="scope_conflict"):
        safe_next(href(q=original),r)
    assert safe_next(href(q=r["parameters"]["q"]),r)["start"]==10


@pytest.mark.parametrize("url",[
    'http://www.fpds.gov/ezsearch/FEEDS/ATOM?start=10','https://evil.invalid/ezsearch/FEEDS/ATOM?start=10',
    'https://www.fpds.gov:443/ezsearch/FEEDS/ATOM?start=10','https://user@www.fpds.gov/ezsearch/FEEDS/ATOM?start=10',
    'https://www.fpds.gov/other?start=10','https://www.fpds.gov/ezsearch/FEEDS/%41TOM?start=10',
    '?start=10#','?start=10#fragment','?start=10%0a','?start=10&%56ERSION=1.5.3',
    '?start=10&VERSION=%ff','?start=10&VERSION=%zz','../FEEDS/ATOM?start=10',
    '//evil.invalid/ezsearch/FEEDS/ATOM?start=10','?start=10&start=10',
])
def test_url_parser_and_encoding_attacks_fail_closed(url):
    with pytest.raises(EvidenceError):
        safe_next(url,request())


@pytest.mark.parametrize("url",["?start=10","/ezsearch/FEEDS/ATOM?start=10","ATOM?start=10",FPDS+"?start=10",FPDS+"?s=FPDSNG.COM&start=10"])
def test_previously_supported_relative_absolute_and_legacy_links(url):
    assert safe_next(url,request())["start"]==10


def test_backend_protocol_cannot_change_mid_chain():
    r=request_for("fpds",AWARD.to_dict(),2,10,safe_next(href(),request()))
    with pytest.raises(EvidenceError,match="protocol_changed"):
        safe_next(href(20,s="FPDSNG.COM"),r)
    with pytest.raises(EvidenceError):
        safe_next("?start=20&s=FPDS",request())
    with pytest.raises(EvidenceError,match="scope_conflict"):
        request_for("fpds",AWARD.to_dict(),2,10,{"start":10,"q":"OTHER"})


@pytest.mark.parametrize("rel",['<link rel="NEXT" href="?start=10"/>','<x:link xmlns:x="https://example.invalid" rel="next" href="?start=10"/>','<link rel="next"/>','<link rel="next" href="?start=10"/><link rel="next" href="?start=10"/>'])
def test_malformed_next_relation_is_not_terminal_completion(rel):
    raw=page().replace('</feed>',rel+'</feed>').encode()
    with pytest.raises(EvidenceError):
        parse_page("fpds",raw,request(),AWARD.to_dict())


def test_contiguous_three_pages_capture_rationale_but_not_history(tmp_path):
    data=scenario(page(href()),page(href(20),"P00001"),page(mod="P00002"))
    p=tmp_path/"run"
    result=collect(p,data)
    t=result["tasks"][0]
    assert t["pages"]==3 and t["terminal_page_seen"] and t["pagination"]=="complete"
    assert len(t["continuations"])==2 and t["history"]==t["freshness"]==t["source_wide"]=="unknown"
    assert t["query_scope"]=="unknown" and t["status"]=="scope_unverified"
    assert t["continuations"][0]["decoded_atom_href"]==href()
    assert t["continuations"][0]["rule_version"]=="fpds-continuation-v1"
    assert inspect_directory(p).exit_code==0
    before=snapshot(p)
    again=collect(p,data,resume=True)
    assert again==result and snapshot(p)==before


@pytest.mark.parametrize("bad",["?start=10", "?start=30", "?index=20"])
def test_loops_skips_and_offset_protocol_switch_stop_before_third_request(tmp_path,bad):
    r=collect(tmp_path/"run",scenario(page(href()),page(bad,"P00001"),page(mod="P00002")))
    assert r["requests_reserved"]==2 and r["tasks"][0]["pagination"]=="partial"
    assert not r["tasks"][0]["terminal_page_seen"]


def test_empty_terminal_page_remains_inconclusive_history_unknown(tmp_path):
    r=collect(tmp_path/"run",scenario('<feed xmlns="http://www.w3.org/2005/Atom"/>'))
    assert r["tasks"][0]["status"]=="inconclusive_empty_feed"
    assert r["tasks"][0]["terminal_page_seen"] and r["tasks"][0]["history"]=="unknown"


def test_v2_readable_but_not_resumed_and_new_tokens_require_v3(tmp_path):
    plan=make_plan((AWARD,),CollectionLimits(),("fpds",),"fixture:test",collector_version=2)
    req={**request_for("fpds",AWARD.to_dict(),2,10,{"start":10,"VERSION":"1.5.3","s":"FPDS"}),"task_index":0,"page_index":2,"attempt_index":0}
    with pytest.raises(EvidenceError):
        validate_request(req,plan)
    v3=make_plan((AWARD,),CollectionLimits(),("fpds",),"fixture:test")
    validate_request(req,v3)
    req["page_index"]=1
    with pytest.raises(EvidenceError):
        validate_request(req,v3)


@pytest.mark.parametrize("boundary",["before_reserve","after_reserve","after_retrieval","after_body","after_metadata","after_commit"])
def test_interrupted_second_page_preserves_observations_and_reservations(tmp_path,monkeypatch,boundary):
    p=tmp_path/"run"
    data=scenario(page(href()),page(mod="P00001"))
    original_reserve,original_finish,original_create,original_commit=CollectionStore.reserve,CollectionStore.finish,CollectionStore._create,CollectionStore._commit
    fired=False
    def once(self,when):
        nonlocal fired
        if not fired and len(self.state["events"])==1 and boundary==when:
            fired=True
            raise KeyboardInterrupt
    def reserve(self,req):
        once(self,"before_reserve")
        original_reserve(self,req)
        once(self,"after_reserve")
    def finish(self,fields,body):
        once(self,"after_retrieval")
        return original_finish(self,fields,body)
    def create(self,name,raw):
        original_create(self,name,raw)
        if name.endswith('.body'): once(self,"after_body")
        if name.endswith('.json') and name.startswith('c3_attempt_'): once(self,"after_metadata")
    def commit(self,meta):
        original_commit(self,meta)
        if meta["sequence"]==1 and boundary=="after_commit":
            raise KeyboardInterrupt
    with monkeypatch.context() as m:
        m.setattr(CollectionStore,"reserve",reserve);m.setattr(CollectionStore,"finish",finish)
        m.setattr(CollectionStore,"_create",create);m.setattr(CollectionStore,"_commit",commit)
        with pytest.raises(KeyboardInterrupt): collect(p,data)
    before={n:v for n,v in snapshot(p).items() if n.startswith('c3_attempt_')}
    if boundary=="after_body":
        with pytest.raises(EvidenceError,match="incomplete_preserved_observation"):
            collect(p,data,resume=True)
    else:
        result=collect(p,data,resume=True)
        assert result["requests_reserved"]<=3
        if boundary in ("after_reserve","after_retrieval"):
            assert result["tasks"][0]["error_code"]=="interrupted_request_outcome_unknown"
        else:
            assert result["tasks"][0]["terminal_page_seen"]
    assert all((p/n).read_bytes()==raw for n,raw in before.items())


def test_read_validator_binds_second_page_to_preserved_first_page(tmp_path):
    p=tmp_path/"run"
    collect(p,scenario(page(href()),page(mod="P00001")))
    meta=strict_json((p/"c3_attempt_000001.json").read_bytes())
    meta["request"]["parameters"]["s"]="FPDSNG.COM"  # individually allowed, never issued by predecessor.
    (p/"c3_attempt_000001.json").write_text(canonical(meta))
    cp=strict_json((p/"c3_checkpoint.json").read_bytes())
    cp["events"][1]["metadata_sha256"]=digest(meta)
    (p/"c3_checkpoint.json").write_text(canonical(cp))
    scan=inspect_directory(p)
    assert any(e.error_code=="c3_continuation_scope_conflict" for e in scan.entries)


def test_probe_requires_opt_in_and_stops_after_unknown_protocol(tmp_path):
    data=scenario(page('?VERSION=opaque&start=10'))
    with pytest.raises(EvidenceError):
        probe(tmp_path/"no",(AWARD,))
    report,_=probe(tmp_path/"probe",(AWARD,replace(AWARD,piid="OTHER")),live=True,
        transport=FixtureTransport(data),profile="fixture:probe")
    assert report["request_slots_reserved"]==1 and report["executed_queries"]==1
    assert report["results"][0]["historical_completeness"]=="unknown"
    with pytest.raises(SystemExit):
        probe_main(["--selection","absent","--run-dir",str(tmp_path/"cli")])


def test_strict_probe_stops_before_continuation_on_parent_or_native_mismatch(tmp_path):
    wrong=page(href()).replace('<f:PIID>PARENT</f:PIID>','<f:PIID>OTHER-PARENT</f:PIID>')
    report,_=probe(tmp_path/"probe",(AWARD,),live=True,transport=FixtureTransport(scenario(wrong,page())),profile="fixture:wrong-parent")
    task=report["results"][0]["summary"]["tasks"][0]
    assert report["request_slots_reserved"]==1
    assert task["error_code"]=="selected_context_mismatch"
    assert not task["terminal_page_seen"] and task["query_scope"]=="partial"


def test_configured_page_bound_can_proceed_to_next_selected_probe_query(tmp_path):
    data=scenario(page(href()))
    base=FixtureTransport(data)
    def transport(req,seq):
        fields,body=base(req,seq)
        if 'OTHER' in req['parameters']['q']:
            body=body.replace(b'SYNTH-0001',b'OTHER')
        return fields,body
    report,_=probe(tmp_path/"probe",(AWARD,replace(AWARD,piid="OTHER",generated_id="OTHER")),live=True,max_pages=1,
        transport=transport,profile="fixture:bounded-two")
    assert report["executed_queries"]==2 and report["request_slots_reserved"]==2


@pytest.mark.parametrize("raw",['<feed xmlns="http://www.w3.org/2005/Atom"><link rel="next" href="?start=10"/></feed>', '<broken>',
    page().replace('</feed>',page().split('<entry>')[1].split('</entry>')[0]*11+'</feed>')])
def test_empty_with_next_and_changed_xml_do_not_establish_terminal_page(raw):
    if raw.startswith('<feed') and '<broken>' not in raw and '<entry>' in raw:
        entry=page().split('<entry>')[1].split('</entry>')[0]
        raw='<feed xmlns="http://www.w3.org/2005/Atom" xmlns:f="https://www.fpds.gov/FPDS">'+('<entry>'+entry+'</entry>')*11+'</feed>'
    with pytest.raises(EvidenceError):
        parse_page('fpds',raw.encode(),request(),AWARD.to_dict())


@pytest.mark.parametrize("change",[{'terminal_page_seen':True,'pagination':'partial'},{'continuations':[{}]}])
def test_contradictory_pagination_summary_rejected(tmp_path,change):
    p=tmp_path/'run'
    result=collect(p,scenario(page(href()),page(mod='P00001')))
    result['tasks'][0].update(change)
    (p/'c3_summary.json').write_text(canonical(result))
    assert inspect_directory(p).exit_code!=0


def test_repeated_modification_rows_are_observations_not_duplicate_financial_actions(tmp_path):
    award,fixture=demo_case('modifications')
    usa=fixture['responses'][0]
    xml=fixture['responses'][1]['text']
    entries=['<entry>'+s.split('</entry>')[0]+'</entry>' for s in xml.split('<entry>')[1:]]
    q=request_for('fpds',award.to_dict(),1,10)['parameters']['q']
    link=FPDS+'?'+urlencode({'q':q,'FEEDNAME':'PUBLIC','VERSION':'1.5.3','s':'FPDS','start':10})
    start='<feed xmlns="http://www.w3.org/2005/Atom" xmlns:f="https://www.fpds.gov/FPDS">'
    first=start+'<link rel="next" href="'+escape(link,{'"':'&quot;'})+'"/>'+''.join(entries[:2])+'</feed>'
    second=start+''.join(entries[1:])+'</feed>'
    data={'schema_version':1,'responses':[usa,{'source':'fpds','text':first,'retrieved_at_utc':'2025-01-02T00:00:00Z'},
        {'source':'fpds','text':second,'retrieved_at_utc':'2025-01-03T00:00:00Z'}]}
    p=tmp_path/'run'
    result=collect_selected(p,(award,),limits=CollectionLimits(max_awards=1,max_pages=2,max_requests=3,max_records_total=30,max_records_per_source_award=20,retries=0,pace_seconds=0.0),
        transport=FixtureTransport(data),profile='fixture:overlap',sleep=lambda _:None)
    assert result['tasks'][1]['duplicate_retrieval_rows']==1
    financial=reconcile_collection(p)
    assert len(financial.results)==3 and all(r.status.value=='verified_match' for r in financial.results)
    assert {r.left_normalized for r in financial.results}=={'100','-20','0'}
