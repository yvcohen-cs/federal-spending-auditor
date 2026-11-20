"""C21 primary replay; C20 boundary stub explicitly synthetic, not source evidence."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import hashlib,json,shutil
import pytest
from src.evidence_io import canonical,digest
from src.correction_reporting import report as old_report
from src.dependency_resolution import collect
from src.dependency_reporting import report,write_report,verify_report,projections
from src.dependency_source_semantics import documentation,DOCUMENTS
from src.evidence_package import build_package,verify_package,_recipe
from tests.test_historical_source_authority import original_case
from tests.test_historical_authority_reporting import transcript
from tests.test_evidence_acquisition import inventory
from tests.test_parent_coverage import rewrite_zip


def docs(root,monkeypatch):
 root.mkdir()
 for name,(source,url,known,quote) in list(DOCUMENTS.items()):
  body=b'<meta charset="utf-8"><p>Authored synthetic source document</p>'+(quote or 'Synthetic unavailable or unreviewed document').encode()
  sha=hashlib.sha256(body).hexdigest();status=301 if name=='fpds-v14-dictionary' else 503 if name=='dod-2016-guidance' else 200
  m={'schema_version':1,'request':{'method':'GET','url':url,'redirects':False},'status':status,'retrieved_at_utc':'2026-01-01T00:00:00Z','body_complete':True,'body_sha256':sha,'representation':'HTTP_entity_bytes_after_content_decoding','location':'https://sam.gov/contracting' if status==301 else None,'content_type':'text/html; charset=utf-8'}
  (root/(name+'.body')).write_bytes(body);(root/(name+'.json')).write_text(canonical(m))
  if known:monkeypatch.setitem(DOCUMENTS,name,(source,url,sha,quote))
 return root

@pytest.fixture
def context(tmp_path,monkeypatch):
 base,a,_=original_case(tmp_path/'base');o=old_report([base])['cases'][0]
 prior=next(p['original_plan_id'] for p in o['original_requirement_impacts'] if p['dimension']=='parent_identity' and p['native_context']['namespace']=='usaspending')
 archives=[];roots={};receipts={}
 for i in (0,1):
  archive=tmp_path/('baseline-'+str(i)+'.zip');marker=('EXPLICIT_SYNTHETIC_C20_STUB_'+str(i)).encode();archive.write_bytes(marker)
  root=tmp_path/('baseline-root-'+str(i));root.mkdir();shutil.copytree(base['collections'][0],root/'base');(root/'report').mkdir()
  (root/'cases.json').write_text(canonical({'schema_version':1,'cases':[{**base,'collections':['base']}],'baseline_package':'unused-prior.zip'}))
  model={'previously_resolved_real_source_requirements':[],'newly_resolved_real_source_requirements':[],
    'previously_resolved_synthetic_requirements':[prior],'newly_resolved_synthetic_requirements':[],
    'financial_comparison_authorized':False,'historical_parent_applicability_intervals_established':0,'authoritative_real_source_correction_edges':0,
    'historical_authority_assessment':{'evidence_class':'SYNTHETIC_STUB','historical_applicability_rule_established':False}}
  (root/'report/source-bound.json').write_text(canonical(model))
  receipt={'profile':'synthetic','archive_sha256':hashlib.sha256(marker).hexdigest(),'report_sha256':digest(model),
   'verified_case_bindings':[{'original_case_sha256':o['original_case_sha256'],'parent_inventory_sha256':None}],
   'package_files':{p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}}
  roots[marker]=root;receipts[marker]=receipt;archives.append(str(archive))
 @contextmanager
 def verified(path,*,expected_phase):
  assert expected_phase=='C20';marker=Path(path).read_bytes()
  if marker not in roots:raise ValueError('changed synthetic C20 boundary')
  yield roots[marker],deepcopy(receipts[marker])
 monkeypatch.setattr('src.dependency_reporting.verified_directory',verified)
 cases=[]
 for i in (1,2):
  c,a,d=original_case(tmp_path/('original-'+str(i)),suffix='C21-'+str(i));c.update(c21_parent_capture=str(tmp_path/('child-'+str(i))),c21_parent_history=str(tmp_path/('parent-'+str(i))))
  collect(tmp_path/('journal-'+str(i)),c,synthetic=transcript(a,d));cases.append(c)
 return {'root':tmp_path,'cases':cases,'baselines':archives,'docs':docs(tmp_path/'docs',monkeypatch),'baseline_roots':roots,'receipts':receipts,'base':base}

def kw(c):return {'baseline_packages':c['baselines'],'source_documents':c['docs']}

def test_verified_baseline_imports_preserve_prior_claims_without_source_copies(context):
 c=context;r=report(c['cases'],**kw(c))
 assert len(r['original_case_bindings'])==3 and len(r['supplied_original_case_bindings'])==2
 assert len(r['previously_resolved_synthetic_requirements'])==1 and len(r['newly_resolved_synthetic_requirements'])==2
 assert not r['newly_resolved_real_source_requirements'] and not r['financial_comparison_authorized']
 assert r['dependency_assessment']['baseline_unresolved_count']-r['dependency_assessment']['current_remaining_count']==2
 assert sum(r['dependency_assessment']['exclusive_group_counts'].values())==r['dependency_assessment']['baseline_unresolved_count']
 assert r['source_document_evidence_class']=='SYNTHETIC_DOCUMENT_FIXTURE'

@pytest.mark.parametrize('kind',['hash','profile','historical','duplicates'])
def test_bad_or_conflicting_C20_baselines_rejected(context,kind):
 c=context;receipt=list(c['receipts'].values())[0]
 if kind=='hash':next(iter(c['baseline_roots'].values())).joinpath('base/c3_summary.json').write_text('{}')
 if kind=='profile':receipt['profile']='live'
 if kind=='historical':
  root=next(iter(c['baseline_roots'].values()));p=root/'report/source-bound.json';m=json.loads(p.read_text());m['historical_authority_assessment']['fabricated_rule']=True;p.write_text(canonical(m))
 if kind=='duplicates':c['baselines'][1]=c['baselines'][0]
 with pytest.raises(ValueError):report(c['cases'],**kw(c))

def test_supplied_prior_role_substitution_rejects(context):
 c=context;other=deepcopy(c['base']);other['c20_parent_capture']=c['cases'][0]['c21_parent_capture']
 with pytest.raises(ValueError):report([other,*c['cases']],**kw(c))

def test_duplicate_original_or_profile_confusion_rejects(context):
 with pytest.raises(ValueError):report(context['cases']*2,**kw(context))

def test_repeated_reports_escape_untrusted_text_and_resigned_false_finance_rejects(context):
 c=context;a=c['root']/'a';b=c['root']/'b'
 assert write_report(a,c['cases'],**kw(c))==write_report(b,c['cases'],**kw(c)) and inventory(a)==inventory(b)
 r=verify_report(a,c['cases'],**kw(c));r['untrusted']='<script>alert(1)</script>```'
 assert b'<script>' not in projections(r)['dependency-resolution.html']
 r['financial_comparison_authorized']=True;r['historical_parent_applicability_intervals_established']=1
 for n,raw in projections(r).items():(a/n).write_bytes(raw)
 commit=json.loads((a/'dependency-resolution-commit.json').read_text());commit['report_sha256']=digest(r);commit['files']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in a.iterdir() if p.name!='dependency-resolution-commit.json'};(a/'dependency-resolution-commit.json').write_text(canonical(commit)+'\n')
 with pytest.raises(ValueError):verify_report(a,c['cases'],**kw(c))

@pytest.mark.parametrize('field,value',[('status',True),('schema_version',True),('body_sha256','0'*64),('representation','wire_exact_HTTP'),('retrieved_at_utc',None)])
def test_forged_document_metadata_rejects(context,field,value):
 c=context;p=c['docs']/'sam-guide.json';m=json.loads(p.read_text());m[field]=value;p.write_text(canonical(m))
 with pytest.raises(ValueError):documentation(c['docs'])

def test_unavailable_historical_documents_never_become_authority(context):
 d=documentation(context['docs']);assert all(x['state']=='UNAVAILABLE_OR_INCOMPLETE' for x in d[:2])
 assert all(not x['historical_applicability_rule_established'] and not x['directed_correction_supported'] for x in d)
 assert all(not x['redirect_followed'] for x in d)

@pytest.mark.parametrize('phase',['C14','C15','C16','C17','C18','C19','C20'])
def test_C21_roots_require_explicit_new_package_phase(tmp_path,phase):
 cases=[{'collections':[],'c21_parent_capture':'missing'}];value={'schema_version':1,'cases':cases,'baseline_package':'prior.zip'}
 if phase in ('C17','C18'):value['selected_action']={}
 if phase=='C18':value['sam_action_captures']=[]
 (tmp_path/'cases.json').write_text(canonical(cases if phase=='C14' else value))
 with pytest.raises(ValueError,match='C21_fields'):_recipe(tmp_path,phase)

def test_C21_small_package_imports_two_baselines_and_primary_rejects_resigned_authority(context):
 c=context;stage=c['root']/'stage';stage.mkdir();rel=[];absolute=[]
 for i,case in enumerate(c['cases']):
  rr=deepcopy(case);aa=deepcopy(case)
  for role in ('collections','c21_parent_capture','c21_parent_history'):
   many=role=='collections';paths=case[role] if many else [case[role]];names=[f'case-{i}-{role}-{j}' for j in range(len(paths))]
   for old,name in zip(paths,names):shutil.copytree(old,stage/name)
   rr[role]=names if many else names[0];absnames=[str(stage/n) for n in names];aa[role]=absnames if many else absnames[0]
  rel.append(rr);absolute.append(aa)
 for i,base in enumerate(c['baselines']):shutil.copyfile(base,stage/f'baseline-{i}.zip')
 shutil.copytree(c['docs'],stage/'official-documents');bases=[str(stage/f'baseline-{i}.zip') for i in (0,1)]
 (stage/'cases.json').write_text(canonical({'schema_version':1,'cases':rel,'baseline_packages':['baseline-0.zip','baseline-1.zip']}))
 write_report(stage/'report',absolute,baseline_packages=bases,source_documents=stage/'official-documents')
 output=c['root']/'c21.zip';a=build_package(stage,output,phase='C21');assert a==verify_package(output,expected_phase='C21')
 assert not a['resolved_real_source_plan_ids'] and len(a['verified_case_bindings'])==3
 def forge(files):
  r=json.loads(files['report/dependency-resolution.json']);r['financial_comparison_authorized']=True
  for n,raw in projections(r).items():files['report/'+n]=raw
  commit=json.loads(files['report/dependency-resolution-commit.json']);commit['report_sha256']=digest(r);commit['files']={n[7:]:hashlib.sha256(raw).hexdigest() for n,raw in files.items() if n.startswith('report/') and n!='report/dependency-resolution-commit.json'};files['report/dependency-resolution-commit.json']=(canonical(commit)+'\n').encode()
  index=json.loads(files['evidence-index.json']);index['report_sha256']=digest(r);files['evidence-index.json']=(canonical(index)+'\n').encode()
 bad=c['root']/'resigned.zip';rewrite_zip(output,bad,forge,resign=True)
 with pytest.raises(ValueError):verify_package(bad)

@pytest.mark.parametrize('phase',['C14','C15','C16','C17','C18','C19','C20'])
def test_C21_contract_cannot_be_smuggled_into_old_capture_role(tmp_path,phase):
 (tmp_path/'newchild').mkdir();(tmp_path/'newchild/pilot-plan.json').write_text(canonical({'experiment':{'schema_type':'DependencyVerificationExperiment'}}))
 cases=[{'collections':[],'c12_capture':'newchild'}];value={'schema_version':1,'cases':cases,'baseline_package':'prior.zip'}
 if phase in ('C17','C18'):value['selected_action']={}
 if phase=='C18':value['sam_action_captures']=[]
 (tmp_path/'cases.json').write_text(canonical(cases if phase=='C14' else value))
 with pytest.raises(ValueError,match='C21_source_contract'):_recipe(tmp_path,phase)

def test_package_order_does_not_change_substantive_output(context):
 c=context;r=report(c['cases'],**kw(c));other={**kw(c),'baseline_packages':list(reversed(c['baselines']))}
 assert canonical(r)==canonical(report(c['cases'],**other))

def test_offline_replay_never_initializes_HTTP(context,monkeypatch):
 monkeypatch.setattr('src.collection_sources.HTTPTransport',lambda *_a,**_k:pytest.fail('network initialized'))
 monkeypatch.setattr('requests.sessions.Session.request',lambda *_a,**_k:pytest.fail('request attempted'))
 assert report(context['cases'],**kw(context))['financial_comparison_authorized'] is False

def test_frozen_documents_remain_byte_identical():
 p=json.loads(Path('docs/dependency-resolution-protocol-v1.json').read_text());assert len(p['frozen_files'])==78
 for n,h in p['frozen_files'].items():assert hashlib.sha256(Path(n).read_bytes()).hexdigest()==h

@pytest.mark.parametrize('bad',['https://unapproved.invalid/doc','http://open.gsa.gov/api/contract-awards/','https://open.gsa.gov/api/contract-awards/?api_key=synthetic'])
def test_unapproved_document_URL_rejected(context,bad):
 p=context['docs']/'sam-guide.json';m=json.loads(p.read_text());m['request']['url']=bad;p.write_text(canonical(m))
 with pytest.raises(ValueError):documentation(context['docs'])

def test_unreviewed_PDF_cannot_supply_historical_authority(context):
 p=context['docs']/'fpds-v14-dictionary.json';m=json.loads(p.read_text());m.update(status=200,location=None,content_type='application/pdf');p.write_text(canonical(m))
 d=documentation(context['docs'])[0];assert d['state']=='UNREVIEWED_DOCUMENT_VERSION' and not d['historical_applicability_rule_established']
