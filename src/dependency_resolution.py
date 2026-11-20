"""C21 explicit bounded continuation for original C20-shortlisted dependencies.

Only acquisition pagination changes: C14 qualification and monetary safeguards do
not. The legacy C12 schema retains its two-page bound and serialization.
"""
from pathlib import Path
from .parent_authority_acquisition import plan as legacy_plan, usable
from .source_bound_reporting import original, ROLES as PRIOR_ROLES, EXTRA as C20_EXTRA
from .acquisition_planning import prepare, AcquisitionLimits
from .source_verification import DependencyVerificationExperiment, experiment, inspect_experiment
from .parent_history_probe import collect as collect_parent, read as read_parent
from .correction_reporting import report as qualify, _paths
from .history_preflight import monetary_preflight
from .evidence_io import EvidenceError, canonical, digest
from .award_validation import snapshot
from .pilot_store import PilotStore
from .review_packet_io import outside

EXTRA=('c21_parent_capture','c21_parent_history')
TARGETS={
 'evidence-resolution:v1:140225679eaffd3a8c3192bcabb490404c3f084a840d681f27d4e61e50040cdf':'709773e4609bed43b34fd7e341a20c29955af4328516dc2ecc618582995c56f0',
 'evidence-resolution:v1:ed25336764203d9fc45a4ece18775a7e5e14250bdaa8176526495587d73d8ba8':'7264220eb71cc407ea0647c3143c28761591423df80c37258a2e125bec0078cf',
}

def clean(case):return {k:v for k,v in case.items() if k not in EXTRA}
def inventory(path):return {n:s.byte_sha256 for n,s in snapshot(path).items()}

def plan(case,*,live=False):
    if type(case) is not dict:raise EvidenceError('explicit_dependency_case_required')
    c=clean(case)
    if any(c.get(k) for k in PRIOR_ROLES[2:]+C20_EXTRA):raise EvidenceError('C21_cannot_rebind_prior_acquisition')
    base=original(c);old=legacy_plan(base,live=live)
    if old['profile']=='live' and TARGETS.get(old['original_requirement_id'])!=old['original_case_sha256']:
        raise EvidenceError('C20_original_shortlist_target_required')
    q=prepare([base],limits=AcquisitionLimits(max_pages=4,page_size=10,max_requests=6,retries=0))
    jobs=[s for s in q.requests if s.source=='usaspending' and s.target_kind=='award_history']
    if len(jobs)!=1:raise EvidenceError('one_exact_USA_child_required')
    ex=DependencyVerificationExperiment(queue=q,request_id=jobs[0].request_id,
        mode='explicit_public_USA_validation' if live else 'synthetic_only' if old['profile']=='synthetic' else 'offline_only')
    return {**old,'schema_type':'SourceBoundDependencyAcquisitionPlan','experiment':ex.to_dict(),
        'maximum_requests':8,'maximum_transaction_rows':50,'child_maximum_pages':4,'child_page_size':10,
        'parent_maximum_pages':2,'parent_page_size':5,
        'qualification_rule':'unchanged_C14_source_local_parent_identity_and_primary_existence',
        'pagination_is_not_historical_completeness':True}

def collect(journal,case,*,live=False,synthetic=None):
    p=plan(case,live=live)
    if live and synthetic is not None or not live and (p['profile']!='synthetic' or synthetic is None):
        raise EvidenceError('offline_default_no_source_access')
    if not all(case.get(k) for k in EXTRA):raise EvidenceError('two_new_separate_capture_paths_required')
    child,parent=(case[k] for k in EXTRA);protected=_paths(original(clean(case)))
    for path,others in ((journal,protected+[child,parent]),(child,protected+[journal,parent]),(parent,protected+[journal,child])):outside(path,others)
    with PilotStore(journal,p) as store:
        store.write('child-start.json',{'plan_sha256':digest(p)})
        experiment(child,DependencyVerificationExperiment.from_dict(p['experiment']),live=live,
                   synthetic=None if live else synthetic['child'])
        source=inspect_experiment(child);store.write('child-complete.json',{'inventory_sha256':source['inventory_sha256']})
        if usable(source):
            store.write('parent-start.json',{'source_returned_parent':source['parent']['native_award_id']})
            if live:
                import time
                time.sleep(1.0)
            observed=collect_parent(parent,child,live=live,synthetic=None if live else synthetic['parent'])
            store.write('parent-complete.json',{'inventory_sha256':observed['inventory_sha256']})
        if plan(case,live=live)!=p:raise EvidenceError('C21_original_context_changed')
        store.write('acquisition-commit.json',{'schema_version':1,'files':store.inventory()})
    return replay(case)

def replay(case):
    p=plan(case,live=False);source=inspect_experiment(case[EXTRA[0]])
    expected=plan(case,live=p['profile']=='live')
    if source['experiment']!=expected['experiment']:raise EvidenceError('C21_capture_plan_conflict')
    parent=None;impacts=[];money=None
    if usable(source) and case.get(EXTRA[1]) and Path(case[EXTRA[1]]).exists():
        parent=read_parent(case[EXTRA[1]],case[EXTRA[0]])
        if parent['capture_contract_version']!=2:raise EvidenceError('C21_parent_v2_required')
        augmented={**original(clean(case)),'c12_capture':case[EXTRA[0]],'parent_history':case[EXTRA[1]]}
        enhanced=qualify([augmented])['cases'][0]
        if enhanced['original_case_sha256']!=p['original_case_sha256']:raise EvidenceError('C21_original_identity_changed')
        for x in enhanced['original_requirement_impacts']:
            if x['original_requirement_resolved']:
                if (x['original_plan_id']!=p['original_requirement_id'] or x['original_requirement']!=p['original_requirement']
                        or x['dimension']!='parent_identity' or x['native_context']['namespace']!='usaspending'):
                    raise EvidenceError('C21_unsupported_resolution_expansion')
                impacts.append(x)
        money=monetary_preflight(enhanced,augmented,None)
        if any(type(money[k]) is not int or money[k]!=0 for k in ('totals_or_deltas_computed','amount_comparisons_performed')) or money['financial_comparison_authorized'] is not False:
            raise EvidenceError('C21_financial_assessment_only_required')
    attempts=source['request_attempts']+(0 if parent is None else parent['request_attempts'])
    child_rows=sum(len(h['observations']) for h in (source['transaction_contract'] or {}).get('histories',[]))
    parent_rows=0 if parent is None else len(parent['records'])
    if attempts>8 or child_rows>40 or parent_rows>10 or child_rows+parent_rows>50:
        raise EvidenceError('C21_request_or_record_budget_exceeded')
    return {'schema_type':'DependencyAcquisitionAssessment','schema_version':1,'profile':p['profile'],
        'plan':expected,'source':source,'parent':parent,'resolved_original_impacts':impacts,
        'request_attempts':attempts,'child_transaction_rows':child_rows,'parent_action_rows':parent_rows,
        'financial_preflight':money,'financial_comparison_authorized':False,
        'historical_applicability_established':False,'correction_relationship_established':False}


# Official-document attempt contracts.
from .evidence import _timestamp
from .evidence_io import EvidenceRoot,EvidenceError,digest,strict_json
from .source_reference_semantics import visible_projection

DOCUMENTS={
 'fpds-v14-dictionary':('fpds','https://www.fpds.gov/downloads/FPDSNG_DataDictionary_V14_OT.pdf',None,None),
 'dod-2016-guidance':('dod','https://www.acq.osd.mil/dpap/dars/pgi/pgi_htm/r20161021/PGI204_6.htm',None,None),
 'sam-guide':('samgov','https://open.gsa.gov/api/contract-awards/','033a7007b702d25f1582f06feb8c0dd5d6dce3afee056cb57b61995e0e7443c7','contractId.referencedIDVModificationNumber'),
 'usa-transactions':('usaspending','https://raw.githubusercontent.com/fedspendingtransparency/usaspending-api/c2b82690eb044e130afc80b546343a2af0b4af1a/usaspending_api/api_contracts/contracts/v2/transactions.md','76a50f3445670d8ee5488770d6583a7f6399a093a903dabfbab77344f1eba078','hasNext'),
}

def documentation(path):
 out=[]
 with EvidenceRoot(path,max_bytes=2*1048576,max_total_bytes=12*1048576) as root:
  for name,(source,url,known,quote) in DOCUMENTS.items():
   ms=root.read(name+'.json');m=strict_json(ms.data);body=root.read(name+'.body')
   if (type(m) is not dict or set(m)!={'schema_version','request','status','retrieved_at_utc','body_complete','body_sha256','representation','location','content_type'}
       or type(m['schema_version']) is not int or m['schema_version']!=1
       or type(m['status']) is not int or not 100<=m['status']<=599 or type(m['body_complete']) is not bool
       or m['request']!={'method':'GET','url':url,'redirects':False}
       or m['representation']!='HTTP_entity_bytes_after_content_decoding' or m['body_sha256']!=body.byte_sha256
       or type(m['retrieved_at_utc']) is not str):raise EvidenceError('C21_document_provenance_conflict')
   _timestamp(m['retrieved_at_utc']);available=m['status']==200 and m['body_complete'] and m['location'] is None
   reviewed=available and known is not None and known==body.byte_sha256
   text,encoding,basis=visible_projection(body.data,m['content_type']) if reviewed else ('',None,None)
   start=text.find(quote) if reviewed else -1
   out.append({'source':source,'name':name,'metadata':m,'metadata_sha256':ms.byte_sha256,
     'body_file':name+'.body','metadata_file':name+'.json',
     'state':'UNAVAILABLE_OR_INCOMPLETE' if not available else 'REVIEWED_CLAUSE_OBSERVED' if start>=0 else 'UNREVIEWED_DOCUMENT_VERSION',
     'clause':quote if start>=0 else None,'visible_character_span':[start,start+len(quote)] if start>=0 else None,
     'projection_encoding':encoding,'encoding_basis':basis,'publisher_version':None,
     'historical_applicability_rule_established':False,'directed_correction_supported':False,
     'source_wide_completeness_supported':False,'redirect_followed':False})
   if root.read(name+'.json',recheck=True).byte_sha256!=ms.byte_sha256 or root.read(name+'.body',recheck=True).byte_sha256!=body.byte_sha256:raise EvidenceError('C21_document_changed')
 return out


# Verified baseline imports and deterministic offline reporting.
import argparse
from contextlib import ExitStack
from html import escape
from pathlib import Path
from .source_bound_reporting import original,paths as old_paths,ROLES,EXTRA as OLD_EXTRA
from .correction_reporting import report as original_report
from .historical_authority_reporting import ORIGINAL_IDS
from .evidence_dependency_triage import assess_dependencies
from .evidence_package import verified_directory,_recipe,MAX_FILE,MAX_TOTAL,MAX_FILES
from .evidence_io import EvidenceError,EvidenceRoot,canonical,digest,strict_json
from .pilot_store import PilotStore
from .review_packet_io import outside

ROLES=ROLES+OLD_EXTRA

def paths(case):return old_paths(clean(case))+[case[k] for k in EXTRA if case.get(k) and Path(case[k]).exists()]
def bounded(cases):
 if (type(cases) not in (list,tuple) or not 1<=len(cases)<=24 or any(type(c) is not dict for c in cases)
     or sum(bool(c.get(EXTRA[0])) for c in cases)>2):raise EvidenceError('bounded_C21_cases_required')
 return cases

def same_roles(a,b):
 for role in ROLES:
  many=role in ('collections','sam_captures');x=a.get(role);y=b.get(role)
  x=(x or []) if many else [] if x is None else [x];y=(y or []) if many else [] if y is None else [y]
  if type(x) is not list or type(y) is not list or len(x)!=len(y) or any(inventory(u)!=inventory(v) for u,v in zip(x,y)):
   raise EvidenceError('C21_preserved_primary_role_substitution')

def package_inventory(root):
 with EvidenceRoot(root,max_bytes=MAX_FILE,max_total_bytes=MAX_TOTAL,max_files=MAX_FILES) as reader:
  return {n:reader.read(n).byte_sha256 for n in reader.discover()}

def report(cases,*,baseline_packages,source_documents):
 cases=bounded(cases)
 if type(baseline_packages) not in (tuple,list) or not 1<=len(baseline_packages)<=2:raise EvidenceError('one_or_two_verified_C20_baselines_required')
 before={p:inventory(p) for c in cases for p in paths(c)};docs=documentation(source_documents)
 originals=original_report([original(clean(c)) for c in cases])['cases'];provided={x['original_case_sha256']:c for c,x in zip(cases,originals)}
 if len(provided)!=len(cases):raise EvidenceError('C21_duplicate_original_case')
 with ExitStack() as stack:
  baseline={};receipts=[];baseline_files=[];prior_real=set();prior_synthetic=set();historical=None;imports=[];profile=originals[0]['profile']
  for archive in baseline_packages:
   root,receipt=stack.enter_context(verified_directory(archive,expected_phase='C20'))
   if package_inventory(root)!=receipt['package_files']:raise EvidenceError('C21_imported_package_changed_after_verification')
   baseline_files.append((root,receipt['package_files']))
   if receipt['profile']!=profile or any(x['archive_sha256']==receipt['archive_sha256'] for x in receipts):raise EvidenceError('C21_duplicate_or_mixed_baseline_profile')
   saved,_,_=_recipe(root,'C20');bindings=receipt['verified_case_bindings']
   for entry in saved:
    for role in ROLES:
     values=entry.get(role) or []
     if role not in ('collections','sam_captures'):values=[] if not values else [values]
     for path in values:
      prefix=Path(path).relative_to(root).as_posix()+'/'
      expected={n[len(prefix):]:h for n,h in receipt['package_files'].items() if n.startswith(prefix)}
      if inventory(path)!=expected:raise EvidenceError('C21_imported_primary_differs_from_verified_inventory')
   if len(saved)!=len(bindings):raise EvidenceError('C21_baseline_case_binding_count')
   with EvidenceRoot(Path(root)/'report',max_bytes=16*1048576) as reader:old=strict_json(reader.read('source-bound.json').data)
   if old['financial_comparison_authorized'] is not False or old['historical_parent_applicability_intervals_established']!=0 or old['authoritative_real_source_correction_edges']!=0:raise EvidenceError('C21_non_authorizing_C20_baseline_required')
   if historical is not None and historical!=old['historical_authority_assessment']:raise EvidenceError('C21_conflicting_historical_baselines')
   historical=old['historical_authority_assessment'];receipts.append(receipt)
   prior_real.update(old['previously_resolved_real_source_requirements']+old['newly_resolved_real_source_requirements'])
   prior_synthetic.update(old['previously_resolved_synthetic_requirements']+old['newly_resolved_synthetic_requirements'])
   for c,b in zip(saved,bindings):
    key=b['original_case_sha256']
    if key in baseline:same_roles(baseline[key],c)
    baseline[key]=c
    if key in provided:same_roles(provided[key],c)
    imports.append({'archive_sha256':receipt['archive_sha256'],'original_case_sha256':key,
      'parent_inventory_sha256':b['parent_inventory_sha256'],'supplied_again':key in provided})
  combined=list(cases)+[baseline[k] for k in sorted(set(baseline)-set(provided))]
  combined_before={p:inventory(p) for c in combined for p in paths(c)}
  all_old=original_report([original(clean(c)) for c in combined]);old_cases=all_old['cases']
  if [c['original_case_sha256'] for c in old_cases]!=list(provided)+sorted(set(baseline)-set(provided)):
   raise EvidenceError('C21_recomputed_original_binding_conflict')
  if any(c['profile']!=profile for c in old_cases):raise EvidenceError('C21_mixed_source_profiles')
  ids=sorted({p['original_plan_id'] for c in old_cases for p in c['original_requirement_impacts']});prior=prior_real|prior_synthetic
  if prior_real&prior_synthetic or not prior<=set(ids):raise EvidenceError('C21_prior_partition_conflict')
  full=profile=='live' and len(combined)==24
  if profile=='live':
   if full:
    if len(ids)!=1570 or digest(ids)!=ORIGINAL_IDS:raise EvidenceError('C21_immutable_original_ID_set_changed')
   elif not set(provided)<=set(baseline)|set(TARGETS.values()):raise EvidenceError('C21_unregistered_original_case')
  remaining=set(ids)-prior;results=[];new=set()
  for c,old in zip(cases,originals):
   if c.get(EXTRA[1]) and not c.get(EXTRA[0]):raise EvidenceError('C21_parent_requires_child_anchor')
   if c.get(EXTRA[0]):
    expected=plan(c,live=profile=='live')
    if expected['original_requirement_id'] not in remaining:raise EvidenceError('C21_original_unresolved_target_required')
    if Path(c[EXTRA[0]]).exists():
     result=replay(c)
     for p in result['resolved_original_impacts']:new.add(p['original_plan_id'])
    else:result={'schema_type':'UncollectedDependency','schema_version':1,'plan':expected,'state':'NOT_COLLECTED','financial_comparison_authorized':False}
    results.append({'original_case_sha256':old['original_case_sha256'],'assessment':result})
  triage=assess_dependencies(old_cases,sorted(remaining),resolved_now=sorted(new))
  bindings=[{'original_case_sha256':c['original_case_sha256'],'parent_inventory_sha256':None if c['parent_probe'] is None else c['parent_probe']['inventory_sha256']} for c in old_cases]
  for p,v in {**before,**combined_before}.items():
   if inventory(p)!=v:raise EvidenceError('C21_primary_changed_during_replay')
  if any(package_inventory(root)!=expected for root,expected in baseline_files):raise EvidenceError('C21_baseline_changed_during_replay')
  if documentation(source_documents)!=docs:raise EvidenceError('C21_document_changed_during_replay')
  return {'schema_type':'DependencyResolutionReport','schema_version':1,'profile':profile,
   'qualification_scope':'original_24_case_cohort' if full else 'included_cases_and_verified_baseline_imports',
   'baseline_package_verifications':sorted(receipts,key=lambda x:x['archive_sha256']),'verified_baseline_imports':sorted(imports,key=lambda x:(x['archive_sha256'],x['original_case_sha256'])),'original_case_bindings':bindings,
   'supplied_original_case_bindings':[b for b in bindings if b['original_case_sha256'] in provided],
   'baseline_original_plan_ids':ids,'previously_resolved_real_source_requirements':sorted(prior_real),
   'previously_resolved_synthetic_requirements':sorted(prior_synthetic),
   'newly_resolved_real_source_requirements':sorted(new) if profile=='live' else [],
   'newly_resolved_synthetic_requirements':sorted(new) if profile=='synthetic' else [],
   'remaining_original_plan_ids':sorted(remaining-new),'dependency_assessment':triage,
   'historical_authority_assessment':historical,'source_document_attempts':docs,
   'source_document_evidence_class':'REAL_PUBLIC_DOCUMENT_CAPTURE' if profile=='live' else 'SYNTHETIC_DOCUMENT_FIXTURE',
   'cases':results,'historical_parent_applicability_intervals_established':0,'authoritative_real_source_correction_edges':0,
   'financial_comparison_authorized':False,'financial_eligibility_changed':False,'production_readiness_changed':False,
   'source_observations':{'capture_request_attempts':sum(c['assessment'].get('request_attempts',0) for c in results),
      'replay_creates_new_observations':False,'duplicates_are_independent_corroboration':False}}

def projections(value):
 md=('# Source-bound dependency resolution v1\n\nScope: '+value['qualification_scope']+'\nPrior real: '+str(len(value['previously_resolved_real_source_requirements']))
  +'\nNew real: '+str(len(value['newly_resolved_real_source_requirements']))+'\nRemaining: '+str(len(value['remaining_original_plan_ids']))
  +'\nHistorical authority, financial eligibility and production readiness are not upgraded.\n'
  +'NOT_EVALUATED is not a discrepancy. Terminal observations are not historical coverage.\n\n```json\n'+canonical(value).replace('`','\\u0060')+'\n```\n')
 html='<!doctype html><html lang="en"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; base-uri \'none\'"><title>Dependency resolution</title><pre>'+escape(md)+'</pre></html>\n'
 return {'dependency-resolution.json':(canonical(value)+'\n').encode(),'dependency-resolution.md':md.encode(),'dependency-resolution.html':html.encode()}

def _plan():return {'schema_type':'DependencyResolutionReportPlan','schema_version':1,'config':{'max_run_bytes':64*1048576}}

def write_report(path,cases,*,baseline_packages,source_documents):
 outside(path,[p for c in bounded(cases) for p in paths(c)]+list(baseline_packages)+[source_documents])
 value=report(cases,baseline_packages=baseline_packages,source_documents=source_documents);raw=projections(value)
 if any(len(b)>16*1048576 for b in raw.values()):raise EvidenceError('C21_projection_size_limit')
 with PilotStore(path,_plan()) as store:
  for n,b in raw.items():store.write_bytes(n,b)
  store.write('dependency-resolution-commit.json',{'schema_version':1,'files':store.inventory(),'report_sha256':digest(value)})
 return digest(value)

def verify_report(path,cases,*,baseline_packages,source_documents):
 with EvidenceRoot(path,max_bytes=16*1048576,max_total_bytes=64*1048576,max_files=5) as reader:
  saved={n:reader.read(n) for n in reader.discover()}
  if any(reader.read(n,recheck=True).byte_sha256!=v.byte_sha256 for n,v in saved.items()):raise EvidenceError('C21_report_changed')
 value=report(cases,baseline_packages=baseline_packages,source_documents=source_documents);raw=projections(value)
 commit={'schema_version':1,'files':{n:v.byte_sha256 for n,v in saved.items() if n!='dependency-resolution-commit.json'},'report_sha256':digest(value)}
 if (set(saved)!={*raw,'pilot-plan.json','dependency-resolution-commit.json'} or saved['pilot-plan.json'].data!=(canonical(_plan())+'\n').encode()
     or saved['dependency-resolution-commit.json'].data!=(canonical(commit)+'\n').encode() or any(saved[n].data!=b for n,b in raw.items())):
  raise EvidenceError('C21_report_not_recomputed_from_primary')
 return value

def main(argv=None):
 p=argparse.ArgumentParser(description='Offline source-bound dependency resolution; network collection requires separate explicit opt-in API.')
 p.add_argument('--cases',required=True);p.add_argument('--baseline-package',action='append',required=True);p.add_argument('--source-documents',required=True)
 m=p.add_mutually_exclusive_group(required=True);m.add_argument('--output');m.add_argument('--verify-report');m.add_argument('--plan-acquisition',action='store_true')
 args=p.parse_args(argv)
 try:
  f=Path(args.cases).absolute()
  with EvidenceRoot(f.parent) as reader:cases=bounded(strict_json(reader.read(f.name).data))
  if args.plan_acquisition:
   if len(cases)!=1:raise EvidenceError('one_explicit_C21_target_required')
   print(canonical(plan(cases[0])));return 0
  kwargs={'baseline_packages':args.baseline_package,'source_documents':args.source_documents}
  if args.verify_report:value=verify_report(args.verify_report,cases,**kwargs)
  else:
   outside(args.output,[args.cases]);write_report(args.output,cases,**kwargs);value=verify_report(args.output,cases,**kwargs)
  print(canonical({'report_sha256':digest(value),'new_real':len(value['newly_resolved_real_source_requirements']),'remaining':len(value['remaining_original_plan_ids']),'financial_authorized':False}));return 0
 except (ValueError,TypeError,OSError,KeyError,IndexError,AttributeError):
  print(canonical({'error_code':'dependency_resolution_failed_preserve_inputs'}));return 2

if __name__=='__main__':raise SystemExit(main())
