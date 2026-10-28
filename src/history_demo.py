"""Fictional known-answer history controls; no production revision mappings."""
from copy import deepcopy

from .collection import collect_selected, CollectionLimits
from .collection_sources import FixtureTransport
from .evidence_io import digest
from .history_ingestion import reconstruct
from .history_reporting import research_report
from .pilot_store import PilotStore
from .research_demo import demo_case
from .scope_models import ScopeRequest

CASES=('initial_and_modifications','equal_revision_unknown','equal_control','unequal_control','different_revisions',
    'missing_intermediate','multiple_transactions','out_of_order','duplicate_observations','contradictory_observations',
    'missing_parent','scope_mismatch','malformed_date','incompatible_signed_date','cumulative_only','partial_pagination','empty_feed','corrected_action')


def fixture(case):
    base='modifications' if case in ('initial_and_modifications','missing_intermediate','out_of_order') else 'ambiguous_parent' if case=='missing_parent' else 'agreement'
    award,data=demo_case(base)
    rows=data['responses'][0]['json']['results'];fpds=data['responses'][-1]
    controlled=case not in ('equal_revision_unknown','missing_parent','partial_pagination','empty_feed')
    if controlled:
        for row in rows: row['_history_control']={'profile':'history-control-v1','revision':'SYNTH-R1'}
        fpds['text']=fpds['text'].replace('<entry>','<entry><h:revision xmlns:h="urn:synthetic-history-control:v1">SYNTH-R1</h:revision>')
    if case=='initial_and_modifications':
        # C7 supplies initial + negative + zero. Add a positive modification.
        r=deepcopy(rows[1]);r['id']=r['id'].replace('P00001','P00003');r['modification_number']='P00003';r['federal_action_obligation']=50;rows.append(r)
        start=fpds['text'].index('<entry>');end=fpds['text'].index('</entry>')+8
        fpds['text']=fpds['text'].replace('</feed>',fpds['text'][start:end].replace('<f:modNumber>0</f:modNumber>','<f:modNumber>P00003</f:modNumber>',1).replace('<f:obligatedAmount>100.00</f:obligatedAmount>','<f:obligatedAmount>50.00</f:obligatedAmount>',1)+'</feed>')
    if case=='missing_intermediate':
        rows.pop(1)
        import re
        fpds['text']=re.sub(r'<entry>.*?</entry>',lambda m:'' if '<f:modNumber>P00001</f:modNumber>' in m[0] else m[0],fpds['text'])
    if case=='out_of_order': rows.reverse()
    if case=='unequal_control': fpds['text']=fpds['text'].replace('<f:obligatedAmount>100.00','<f:obligatedAmount>101.00',1)
    if case=='different_revisions': fpds['text']=fpds['text'].replace('SYNTH-R1','SYNTH-R2')
    if case=='multiple_transactions':
        r=deepcopy(rows[0]);r['id']=r['id'][:-1]+'1';rows.append(r)
        start=fpds['text'].index('<entry>');end=fpds['text'].index('</entry>')+8
        fpds['text']=fpds['text'].replace('</feed>',fpds['text'][start:end].replace('<f:transactionNumber>0','<f:transactionNumber>1')+'</feed>')
    if case=='duplicate_observations': rows.append(deepcopy(rows[0]))
    if case=='contradictory_observations':
        r=deepcopy(rows[0]);r['federal_action_obligation']=101;rows.append(r)
    if case=='scope_mismatch': fpds['text']=fpds['text'].replace('<f:PIID>'+award.piid+'</f:PIID>','<f:PIID>SYNTH-OTHER</f:PIID>')
    if case=='malformed_date': rows[0]['action_date']='2024-99-99'
    if case=='incompatible_signed_date': fpds['text']=fpds['text'].replace('<f:signedDate>2024-10-01','<f:signedDate>2024-10-02')
    if case=='cumulative_only': fpds['text']=fpds['text'].replace('<f:dollarValues><f:obligatedAmount>100.00</f:obligatedAmount></f:dollarValues>','')
    if case=='partial_pagination': data['responses'][0]['json']['page_metadata']['hasNext']=True
    if case=='empty_feed': fpds['text']='<feed xmlns="http://www.w3.org/2005/Atom"/>'
    return award,data


def collect_fixture(path,award,data):
    return collect_selected(path,(award,),limits=CollectionLimits(max_awards=1,max_requests=2,max_pages=1,retries=0,pace_seconds=0.0),
        transport=FixtureTransport(data),profile='fixture:'+digest(data),sleep=lambda _:None)


def run_demo(path):
    with PilotStore(path,{'schema_type':'HistoryDemonstrationPlan','schema_version':1,'config':{'max_run_bytes':128*1024*1024},'profile':'synthetic','cases':list(CASES)}) as store:
        results=[]
        for case in CASES:
            a,data=fixture(case);root=store.path/case
            collect_fixture(root,a,data)
            request=ScopeRequest(piid=a.piid,agency=a.agency_id,parent_piid=a.parent_piid,parent_agency=a.parent_agency_id)
            paths=[root]
            if case=='corrected_action':
                later=deepcopy(data)
                for r in later['responses'][0]['json']['results']:
                    r['_history_control']['revision']='SYNTH-R2';r['federal_action_obligation']=90
                later['responses'][0]['retrieved_at_utc']='2025-02-01T00:00:00Z'
                later['responses'][-1]['text']=later['responses'][-1]['text'].replace('SYNTH-R1','SYNTH-R2').replace('<f:obligatedAmount>100.00','<f:obligatedAmount>90.00',1)
                later['responses'][-1]['retrieved_at_utc']='2025-02-02T00:00:00Z'
                second=store.path/(case+'-later');collect_fixture(second,a,later);paths.append(second)
            run=reconstruct(paths,request)
            report=research_report(run)
            results.append({'case':case,'run_digest':run.substantive_sha256,'metrics':report['metrics']})
            from .history_reporting import bounded_json
            store.write_bytes(case+'-history.json',bounded_json({'report':report,'substantive_sha256':digest(report)}))
        result={'schema_type':'HistoryDemonstration','schema_version':1,'profile':'synthetic','results':results}
        store.write('history-demo.json',{'report':result,'substantive_sha256':digest(result)})
    return result
