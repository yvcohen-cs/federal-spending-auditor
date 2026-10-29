"""Deterministic SAM research findings. Synthetic evidence never certifies access."""
from collections import Counter
from html import escape
from pathlib import Path

from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json
from .history_reporting import bounded_json
from .pilot_store import PilotStore
from .review_packet_io import outside
from .review_packet_models import RecommendedVerificationAction
from .sam_validation_capture import protocol, replay
from .scope_models import ScopeStatus

DOC='https://open.gsa.gov/api/contract-awards/'
OPENAPI=DOC+'v1/openapi.yaml'
VARIANCE=DOC+'v1/FPDSvsSAM-ContractDataAPI.pdf'
SCHEMA_SHA='87ab11d503a19a622dfbb1a1ea8fa840f19440a83b0b2d89cf6132ddb3cfb8fc'

# A documentation matrix, never a projection of mock data into authenticated facts.
RESEARCH=(
 ('access','api_key / roles / IP / quota','documented','GET production v1 requires authorized account key; account-dependent quotas/visibility; no authenticated access observed'),
 ('pagination','offset / limit / totalRecords','contradictory','HTML says page index default0, OpenAPI query default1; examples offset25 limit5 and counters encoded as strings; live continuation unvalidated'),
 ('identity','contractId.piid / subtier.code','documented','Native identity subtier is separate from contracting/funding subtier; exact query enforcement and recall unverified'),
 ('parent','referencedIDVPiid / referencedIDVSubtier.code','documented','Native pair is a record assertion; null/omission not verified no-parent; no FPDS absence rule automatically transferred'),
 ('instrument','coreData.awardOrIDV / awardOrIDVType.code','documented','Award/IDV context required before interpreting type letters; coreVersionId is not API v1 or certified action revision'),
 ('action','modificationNumber / transactionNumber','documented','Native components retained; matching components do not establish synchronized source revisions'),
 ('revision','awardDetails.transactionData.version','unknown','Documented field observed only in synthetic fixtures; examples1.4/1.5 may be document schema, not unique immutable revision IDs'),
 ('status','awardDetails.transactionData.status','contradictory','OpenAPI declares string; HTML table/examples show object. Preserve original shape; do not infer deletion/current status'),
 ('dates','dates.dateSigned / periodOfPerformanceStartDate','documented','Signed date and performance start are distinct; no effective-date alias or invented timezone'),
 ('updates','createdDate / approvedDate / lastModifiedDate / publicDeltaDate','documented','Publication/reveal delta query and native update timestamps differ from retrieval time; no freshness certificate'),
 ('deletion','deletedStatus=yes','documented','Deleted-only query covers last6months and visibility limits; not complete deletions or correction history. No deleted query added here'),
 ('correction','oldContractId','unknown','Prior identifier context retained; neither a fallback identity nor verified correction/deletion lineage'),
 ('money','dollars.actionObligation / totalContractDollars','documented','Separate raw dollar labels, action and totals; currency/basis/revision compatibility not mapped to C5'),
 ('history','source-wide transaction/revision history','unknown','No complete-history guarantee established; query terminal page cannot certify complete action histories'),
 ('independence','SAM / FPDS / USA lineage','inferred','Shared procurement lineage cannot count as independent corroboration'),
)
DIMENSIONS=('authorized_access','stable_response_schema','validated_pagination','native_identity_precision','parent_relationship_evidence',
    'action_revision_lineage','correction_deletion_semantics','financial_field_compatibility','historical_coverage','freshness','provenance_security','operational_reproducibility')


def matrix():
    return [{'dimension':d,'field':f,'knowledge_state':s,'finding':text,'sources':[DOC,OPENAPI] if s=='contradictory' else [DOC],
        'reviewed_on':'2026-10-28','authenticated_observed':False} for d,f,s,text in RESEARCH]


def readiness(profile,metrics,issues):
    live=profile=='live'
    result=[]
    for dimension in DIMENSIONS:
        state='UNKNOWN';n=None;d=None;unit='unavailable_authenticated_observations'
        rationale='Documentation/synthetic results do not establish authenticated source behavior.'
        if live and dimension=='authorized_access':
            n=metrics['HTTP_successful'];d=metrics['HTTP_attempted'];unit='authenticated_HTTP_attempts'
            state='CONDITIONAL' if n and not issues else 'FAIL' if 'authentication_failure' in issues else 'UNKNOWN'
            rationale='Observed bounded attempts only; roles, quotas and scale entitlement remain unverified.'
        if dimension in ('provenance_security','operational_reproducibility'):
            n=d=1 if metrics['capture_inventory_verified'] else None;unit='inspected_capture_journals'
            state='PASS' if n else 'UNKNOWN'
            rationale='Replayed immutable journal and deterministic projections; not universal security or API certification.'
        result.append({'dimension':dimension,'status':state,'numerator':n,'denominator':d,'unit':unit,'evidence_scope':profile,'rationale':rationale})
    return result


def report(path=None,*,access='not_checked_offline_no_credential_read'):
    if access not in ('not_checked_offline_no_credential_read','unavailable_no_configured_credential',
        'configured_material_present_not_authenticated','synthetic_no_credential_used',
        'configured_credential_used_entitlement_not_certified','offline_capture_replay_no_credential_read'):
        raise ValueError('unsupported_or_sensitive_credential_availability_label')
    pages=();selection=None;result=None;inventory_sha=None;issues=()
    if path is not None:
        selection,pages,result,inventory_sha,issues=replay(path)
    profile=selection.profile if selection else 'offline_no_capture'
    rows=[r for _,_,p in pages for r in p.records]
    attempts=[]
    if path:
        with EvidenceRoot(path,max_total_bytes=32*1024*1024) as root:
            snapshots={n:root.read(n) for n in root.discover()}
            expected={'schema_type':'SAMResearchCommit','schema_version':1,'files':{n:s.byte_sha256 for n,s in snapshots.items() if n!='sam-research-commit.json'}}
            if digest(expected)!=inventory_sha or strict_json(snapshots['sam-research-commit.json'].data)!=expected:
                raise EvidenceError('sam_report_source_changed')
            for n in snapshots:
                if n.startswith('sam-attempt-') and n.endswith('.json') and not n.endswith('-reserved.json'):
                    attempts.append({'relative_path':n,'sha256':snapshots[n].byte_sha256,'metadata':strict_json(snapshots[n].data)})
            if {n:root.read(n,recheck=True).byte_sha256 for n in root.discover()}!={n:s.byte_sha256 for n,s in snapshots.items()}:
                raise EvidenceError('sam_report_source_changed')
    counts={s.value:sum(r.scope is s for r in rows) for s in ScopeStatus}
    native_exact=sum(all(getattr(r.identity,k).value==getattr(r.requested,k) for k in ('piid','agency')) for r in rows)
    contents=Counter(r.content_sha256 for r in rows)
    keys={}
    for r in rows:
        full=tuple(getattr(r.identity,k).value for k in ('piid','agency','parent_piid','parent_agency','modification','transaction'))
        if all(v is not None for v in full): keys.setdefault(full,set()).add(r.content_sha256)
    m={'subjects_requested':len(selection.subjects) if selection else 0,
        'subjects_attempted':len({a['metadata']['subject_index'] for a in attempts}),
        'HTTP_attempted':len(attempts),'HTTP_successful':sum(a['metadata']['status'] is not None and 200<=a['metadata']['status']<300 for a in attempts),
        'pages_parsed':len(pages),'native_record_occurrences':len(rows),'record_denominator':len(rows),
        'exact_PIID_identity_agency_occurrences':native_exact,'scope_counts':counts,
        'verified_parent_relationship_occurrences':sum(r.parent_status=='verified_parent_relationship' for r in rows),
        'verified_no_parent_occurrences':0,'unknown_parent_occurrences':sum(r.parent_status=='parent_relationship_unknown' for r in rows),
        'parent_conflict_occurrences':sum(r.parent_status=='parent_relationship_conflict' for r in rows),
        'unsupported_parent_occurrences':sum(r.parent_status=='unsupported_parent_semantics' for r in rows),
        'distinct_record_contents':len(contents),'duplicate_content_occurrences':sum(c-1 for c in contents.values()),
        'complete_native_action_keys_with_content_variants':sum(len(v)>1 for v in keys.values()),
        'revision_relationships_established':0,'financial_comparisons_authorized':0,
        'financial_observations_withheld':sum(f.meaning=='money' and f.presence.value not in ('omitted','null') for r in rows for f in r.fields),
        'history_complete':'unknown','source_wide_complete':'unknown','freshness':'unknown',
        'capture_inventory_verified':path is not None,'units':'HTTP_attempts_pages_and_record_occurrences_are_separate_not_population_estimates'}
    live_metrics=m if profile=='live' else None
    return {'schema_type':'SAMValidationReport','schema_version':1,'version':'sam-validation-report-v1','protocol':protocol(),
        'profile':profile,'credential_availability':access,'authenticated_live_metrics':live_metrics,
        'synthetic_or_offline_metrics':m if profile!='live' else None,'metrics':m,'capture_inventory_sha256':inventory_sha,
        'official_documentation':{'reviewed_on':'2026-10-28','sources':[DOC,OPENAPI,VARIANCE],
            'published_openapi':'3.0.1 / info.version1.0','openapi_bytes_sha256':SCHEMA_SHA,'downloaded_schema_committed':False,
            'behavioral_validation':'authenticated_behavior_unavailable_without_access'},
        'field_research_matrix':matrix(),
        'phase4c1_comparison':'Prior FPDS/USA rule remains unchanged; its no-parent inference is not transferred to SAM. Frozen metrics are a separate historical reference.','readiness':readiness(profile,m,issues),
        'migration_recommendation':'B. Bounded research adapter' if profile=='live' and pages and all(r.supported_schema for r in rows) and set(issues)<= {'offset_contract_unvalidated_stop'} else 'A. Offline prototype only',
        'production_migration_authorized':False,'expanded_collection_authorized':False,'C4_C5_eligibility_changed':False,'readiness_upgrade':False,
        'capture_result':result,'artifact_issues':list(issues),'request_evidence':attempts,
        'pages':[{'subject_index':s,'page_index':p,'page':page.to_dict()} for s,p,page in pages],
        'identity_evidence_table':[{'claim_id':r.claim_id,'source':'samgov','before':r.previous_scope.value,'after':r.scope.value,
            'parent':r.parent_status,'native_award':r.award.to_dict(),'native_action':r.action.to_dict(),'citation':r.citation.to_dict()} for r in rows],
        'frozen_reference':{'cohort':'separate_4C1_frozen_pilot_plus_holdout','occurrences':381,
            'scope':{'verified_in_scope':154,'verified_out_of_scope':88,'ambiguous_scope':139},
            'kind':'historical_reference_not_reclassified_or_pooled_with_SAM','comparative_authenticated_findings':None if profile!='live' else 'subject_linkage_requires_manual_native_namespace_validation'},
        'revision_evidence_matrix':[
            {'relationship':k,'status':'UNKNOWN','record_denominator':len(rows),'established':0,'limitation':v} for k,v in (
                ('shared_revision','Versions, timestamps and amounts do not establish synchronized revisions.'),
                ('correction_lineage','Old identifiers are not correction certificates.'),('deletion_history','Deleted-only six-month visibility is not complete deletion history.'),
                ('freshness','Retrieval/last-modified/public delta are different concepts.'),('historical_completeness','Terminal query pages never certify full transaction history.'))],
        'next_actions':[RecommendedVerificationAction(instruction=t).to_dict() for t in (
            'Through the authorized environment workflow, configure an already authorized SAM credential before a separately approved bounded live observation.',
            'Resolve offset default/page semantics and status-type contradictions with authoritative documentation and bounded authenticated evidence before continuation.',
            'Validate native parent/no-parent, action/revision/correction/deletion lineage, monetary definitions and history/freshness separately before parallel migration review.')],
        'limitations':['Synthetic fixtures validate harness behavior only; live metrics remain unavailable without authenticated captures.',
            'No credential acquisition, redirects, retries, alternative endpoints, exports, aggregation, broader searches or production replacement.',
            'No SAM positive absence rule, agency crosswalk, name/amount/date identity inference, financial arithmetic or independent corroboration claim.',
            'An empty response is inconclusive; unknown pagination, history and freshness are not complete.',
            'Saved reports are projections, not primary-evidence trust anchors; re-read captures to verify.',
            'Unstable ordering and full query recall cannot be established by one or two pages.']}


def text_report(value):
    m=value['metrics']
    lines=['SAM Contract Awards validation research','Profile: '+value['profile'],
        'Credential availability: '+value['credential_availability'],
        'Migration recommendation: '+value['migration_recommendation'],
        'Authenticated live metrics: '+('UNAVAILABLE' if value['authenticated_live_metrics'] is None else canonical(value['authenticated_live_metrics'])),
        'Metrics (explicit profile, separate request/page/occurrence units): '+canonical(m),
        '', '| Dimension | Result | Numerator / denominator | Evidence and limits |','|---|---|---|---|']
    lines.extend('| '+r['dimension']+' | '+r['status']+' | '+str(r['numerator'])+' / '+str(r['denominator'])+' | '+r['rationale']+' |' for r in value['readiness'])
    lines.extend(['','Official sources: '+canonical(value['official_documentation']), 'Field semantics:'])
    lines.extend(canonical(v) for v in value['field_research_matrix'])
    lines.append('Request and pagination evidence:')
    lines.extend(canonical(v) for v in value['request_evidence'])
    lines.extend(canonical({'subject_index':p['subject_index'],'page_index':p['page_index'],
        'offset':p['page']['offset'],'total':p['page']['total'],'bounded_query_terminal':p['page']['bounded_query_terminal'],
        'history_complete':p['page']['history_complete'],'source_wide_complete':p['page']['source_wide_complete']}) for p in value['pages'])
    lines.append('Identity and parent evidence (all source occurrences retained):')
    lines.extend(canonical(v) for v in value['identity_evidence_table'])
    lines.extend(['Revision/correction/deletion evidence:',canonical(value['revision_evidence_matrix']),
        'Separate historical cohort reference: '+canonical(value['frozen_reference']),
        'Capture issues: '+canonical(value['artifact_issues']),'Limitations:',*value['limitations'],'Next actions:'])
    lines.extend(a['instruction'] for a in value['next_actions'])
    return '\n'.join(lines)+'\n'


def html_report(value):
    return '<!doctype html><meta charset="utf-8"><title>SAM validation research</title><h1>SAM validation research</h1><pre>'+escape(text_report(value))+'</pre>'


def write_report(path,value,*,protected=(),capture=None):
    if value!=report(capture,access=value['credential_availability']):
        raise EvidenceError('sam_report_primary_projection_conflict')
    protected=tuple(protected)+((capture,) if capture is not None else ())
    target=outside(path,protected)
    raw=bounded_json({'report':value,'substantive_sha256':digest(value)})
    text=text_report(value).encode();html=html_report(value).encode()
    if sum(map(len,(raw,text,html)))>32*1024*1024: raise EvidenceError('sam_validation_output_size_limit')
    with PilotStore(target,{'schema_type':'SAMValidationOutputPlan','schema_version':1,'protocol_sha256':digest(protocol()),'config':{'max_run_bytes':32*1024*1024}}) as store:
        store.write_bytes('sam-validation.json',raw);store.write_bytes('sam-validation.md',text);store.write_bytes('sam-validation.html',html)
        store.write('sam-validation-commit.json',{'schema_type':'SAMValidationOutputCommit','schema_version':1,'files':store.inventory()})
    return digest(value)


def read_report(path,*,capture=None):
    with EvidenceRoot(path,max_bytes=32*1024*1024,max_total_bytes=32*1024*1024) as root:
        data={n:root.read(n) for n in root.discover()}
        if set(data)!={'pilot-plan.json','sam-validation.json','sam-validation.md','sam-validation.html','sam-validation-commit.json'}:
            raise EvidenceError('unsupported_sam_validation_report_inventory')
        expected={'schema_type':'SAMValidationOutputCommit','schema_version':1,'files':{n:s.byte_sha256 for n,s in data.items() if n!='sam-validation-commit.json'}}
        if strict_json(data['sam-validation-commit.json'].data)!=expected: raise EvidenceError('sam_validation_report_hash_conflict')
        expected_plan={'schema_type':'SAMValidationOutputPlan','schema_version':1,'protocol_sha256':digest(protocol()),'config':{'max_run_bytes':32*1024*1024}}
        if strict_json(data['pilot-plan.json'].data)!=expected_plan: raise EvidenceError('sam_report_plan_conflict')
        doc=strict_json(data['sam-validation.json'].data);value=doc['report']
        regenerated=report(capture,access=value['credential_availability'])
        if value!=regenerated or doc!={'report':value,'substantive_sha256':digest(value)}:
            raise EvidenceError('sam_validation_report_projection_conflict')
        if data['sam-validation.md'].data!=text_report(value).encode() or data['sam-validation.html'].data!=html_report(value).encode():
            raise EvidenceError('sam_validation_readable_projection_conflict')
        for n,s in data.items():
            if root.read(n,recheck=True).byte_sha256!=s.byte_sha256: raise EvidenceError('sam_validation_report_changed')
        if set(root.discover())!=set(data): raise EvidenceError('sam_validation_report_changed')
    return value
