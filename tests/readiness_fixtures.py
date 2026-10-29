from dataclasses import replace
from copy import deepcopy
import json

from src.evidence_io import digest,canonical
from src.pilot_pipeline import run_pilot
from src.pilot_sampling import PilotConfig
from src.research_models import implementation_digest
from src.readiness import load_protocol
from src.readiness_audit import inventory
from src.research_demo import demo_case
from src.collection_sources import FixtureTransport,fpds_query
from src.federal_spending_auditor import API_URL


def frozen(path,count=2):
    run_pilot(path,PilotConfig(mode='synthetic',target=count,implementation_sha256=implementation_digest()))
    sample=json.loads((path/'sample.json').read_text());plan=json.loads((path/'pilot-plan.json').read_text())
    protocol=replace(load_protocol(),profile='synthetic-control',frozen_sample_sha256=digest(sample),frozen_inventory_sha256=digest(inventory(path)),
        frozen_pilot_plan_sha256=digest(plan),original_implementation_sha256=plan['config']['implementation_sha256'])
    return protocol,[s['generated_id'] for s in sample['selected']]


class HoldoutTransport:
    def __init__(self,excluded=(),*,error=None,scope_conflict=False,unsafe=False):
        self.calls=[];self.data={};self.awards={};self.error=error;self.scope_conflict=scope_conflict;self.unsafe=unsafe
        for i in range(3):
            a,d=demo_case('agreement');piid='SYNTH-HOLDOUT-'+str(i)
            new=replace(a,piid=piid,generated_id='SYNTH-GENERATED-'+str(i))
            d=deepcopy(d)
            for row in d['responses'][0]['json']['results']: row['id']=row['id'].replace(a.piid,piid)
            d['responses'][-1]['text']=d['responses'][-1]['text'].replace(a.piid,piid)
            self.data[new.generated_id]=d;self.awards[new.generated_id]=new
        self.rows=[{'generated_internal_id':i,'Award ID':i} for i in list(excluded)[:1]+list(self.data)]

    def __call__(self,request,sequence):
        self.calls.append(request)
        if self.error is not None:
            return {'status':self.error,'retrieved_at_utc':'2025-01-01T00:00:00Z','body_complete':True,'error_code':None,'retry_after':None,'source_update_raw':None},b'{"error":"synthetic unavailable"}'
        if request['endpoint']==API_URL:
            body={'results':self.rows,'page_metadata':{'page':1,'hasNext':False}}
            return {'status':200,'retrieved_at_utc':'2025-01-01T00:00:00Z','body_complete':True,'error_code':None,'retry_after':None,'source_update_raw':None},canonical(body).encode()
        if request['source']=='usaspending': key=request['parameters']['award_id'];item=deepcopy(self.data[key]['responses'][0])
        else:
            key=next(k for k,a in self.awards.items() if request['parameters']['q']==fpds_query(a.to_dict()))
            item=deepcopy(self.data[key]['responses'][-1])
            if self.scope_conflict: item['text']=item['text'].replace('<f:agencyID>0001</f:agencyID>','<f:agencyID>9999</f:agencyID>')
            if self.unsafe: item['text']=item['text'].replace('</feed>','<link rel="next" href="https://evil.invalid/"/></feed>')
        return FixtureTransport({'schema_version':1,'responses':[item]})(request,0)
