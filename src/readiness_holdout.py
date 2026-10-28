"""Preregistered new holdout: <=3 awards, <=10 requests; never a scale switch."""
from dataclasses import replace
import hashlib
import re
import subprocess
from pathlib import Path

from .collection import CollectionLimits,SelectedAward,collect_selected
from .collection_sources import HTTPTransport
from .evidence_io import EvidenceError,EvidenceRoot,digest,strict_json,parts
from .federal_spending_auditor import API_URL
from .history_ingestion import reconstruct
from .history_pilot import native_request
from .pilot_store import PilotStore
from .readiness_audit import audit_collection,inventory,unavailable_slot
from .readiness_models import CohortAudit,Measurement,CauseOccurrence
from .matching_models import ordered
from .scope_models import ScopeStatus
from .research_models import implementation_digest


def frame_request(protocol):
    return {'source':'usaspending','endpoint':API_URL,'method':'POST','parameters':{
        'filters':{'time_period':[{'start_date':'2022-10-01','end_date':'2023-09-30'}],'award_type_codes':['D']},
        'fields':['Award ID','Award Amount','Awarding Agency','Start Date','Contract Award Type','generated_internal_id'],
        'sort':'Award ID','order':'asc','page':1,'limit':protocol.holdout_frame_limit}}


def selection(raw,excluded,protocol):
    doc=strict_json(raw)
    if (not isinstance(doc,dict) or not isinstance(doc.get('results'),list) or len(doc['results'])>protocol.holdout_frame_limit
            or not isinstance(doc.get('page_metadata'),dict) or type(doc['page_metadata'].get('hasNext')) is not bool):
        raise EvidenceError('unsupported_holdout_frame_schema')
    grouped={};overlap=[];conflicts=[]
    for row in doc['results']:
        if not isinstance(row,dict): raise EvidenceError('unsupported_holdout_frame_row')
        identifier=row.get('generated_internal_id')
        if type(identifier) is not str or not identifier.strip() or len(identifier)>256 or any(ord(c)<32 or ord(c)==127 for c in identifier):
            raise EvidenceError('unsupported_holdout_native_selection_id')
        if identifier in excluded: overlap.append(identifier)
        else: grouped.setdefault(identifier,[]).append(row)
    eligible=[]
    for key,rows in sorted(grouped.items()):
        if len({digest(r) for r in rows})!=1: conflicts.append(key)
        else: eligible.append(key)
    return {'schema_type':'ReadinessHoldoutSelection','schema_version':1,'selected':eligible[:protocol.holdout_award_limit],
        'overlap_exclusions':sorted(set(overlap)),'conflicting_frame_exclusions':conflicts,'frame_rows':len(doc['results']),
        'frame_sha256':hashlib.sha256(raw).hexdigest(),'protocol_sha256':protocol.protocol_sha256,'replacement_policy':'none'}


def collect_holdout(path,protocol,excluded,*,live=False,transport=None):
    if not live: raise EvidenceError('readiness_holdout_live_opt_in_required')
    profile='live' if transport is None else 'synthetic'
    limits=CollectionLimits(max_awards=1,max_requests=1,max_pages=1,retries=0,max_response_bytes=1024*1024,timeout_seconds=10.0,pace_seconds=0.5)
    actual=transport or HTTPTransport(limits.to_dict())
    fingerprint=implementation_digest()
    implementation_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=Path(__file__).resolve().parent.parent,text=True,timeout=5).strip()
    reserved=0
    def bounded(request,sequence):
        nonlocal reserved
        if reserved>=protocol.holdout_http_limit: raise EvidenceError('readiness_holdout_http_budget_exhausted')
        reserved+=1
        return actual(request,reserved-1)
    plan={'schema_type':'ReadinessHoldoutPlan','schema_version':1,'protocol':protocol.to_dict(),'profile':profile,
        'implementation_sha256':fingerprint,'implementation_commit':implementation_commit,
        'config':{'max_run_bytes':32*1024*1024},'excluded_original_ids':sorted(excluded),'maximum_http_requests':protocol.holdout_http_limit,
        'frame_request':frame_request(protocol),'retries':0,'pages_per_task':1}
    with PilotStore(path,plan) as store:
        request=frame_request(protocol)
        store.write('frame-reserved.json',{'request':request,'maximum_attempts':1})
        fields,raw=bounded(request,0)
        if raw is not None: store.write_bytes('frame.body',raw)
        store.write('frame-response.json',{**fields,'body_sha256':hashlib.sha256(raw).hexdigest() if raw is not None else None,
            'representation':'application_response_bytes_not_wire_capture'})
        stopped=False;reason=None;chosen=None;entries=[]
        good=fields['status'] is not None and 200<=fields['status']<300 and not fields['error_code'] and fields['body_complete'] and raw is not None
        if good:
            from .evidence import _timestamp
            try:
                if fields['retrieved_at_utc'] is None: raise ValueError('missing retrieval time')
                _timestamp(fields['retrieved_at_utc'])
            except (ValueError,TypeError): good=False
        if good:
            try: chosen=selection(raw,set(excluded),protocol)
            except (ValueError,KeyError,TypeError): reason='unsupported_frame_schema';stopped=True
        else: reason='frame_access_unavailable';stopped=True
        if chosen is None:
            chosen={'schema_type':'ReadinessHoldoutSelection','schema_version':1,'selected':[],'overlap_exclusions':[],
                'conflicting_frame_exclusions':[],'frame_rows':None,'frame_sha256':None,'protocol_sha256':protocol.protocol_sha256,'replacement_policy':'none'}
        store.write('holdout-selection.json',chosen)  # Freeze before discovery.
        for index,identifier in enumerate(chosen['selected']):
            folder=f'award-{index:03d}';entry={'slot':index,'selected_native_id':identifier,'collection':None,'status':'not_requested_after_stop'}
            entries.append(entry)
            if stopped: continue
            store.mkdir(folder)
            discovered=store.path/folder/'discovery'
            summary=collect_selected(discovered,(SelectedAward(generated_id=identifier),),sources=('usaspending',),limits=limits,
                profile='live' if profile=='live' else 'fixture:'+digest(plan),transport=bounded,stop_on_context_mismatch=True)
            entry['collection']=folder+'/discovery';entry['status']='discovery_only'
            if any(t['error_code'] for t in summary['tasks']): stopped=True;reason='discovery_source_error';continue
            with EvidenceRoot(discovered) as root: discovered_plan=strict_json(root.read('c3_plan.json').data)
            try: native=native_request(discovered,discovered_plan)
            except (ValueError,KeyError,TypeError): entry['status']='native_context_unavailable';continue
            award=SelectedAward(generated_id=identifier,piid=native.piid,agency_id=native.agency,parent_piid=native.parent_piid,parent_agency_id=native.parent_agency)
            collection=store.path/folder/'collection'
            # Two source tasks, still one page and one attempt each. To stop
            # globally after either task, collect into separate immutable roots.
            paths=[]
            for source in ('usaspending','fpds'):
                child=store.path/folder/source
                summary=collect_selected(child,(award,),sources=(source,),limits=limits,profile='live' if profile=='live' else 'fixture:'+digest(plan),
                    transport=bounded,stop_on_context_mismatch=True)
                paths.append(folder+'/'+source)
                try: checked=reconstruct((child,),native)
                except (ValueError,KeyError,TypeError):
                    stopped=True;reason='unsupported_or_inconsistent_source_evidence';break
                if (any(t['error_code'] for t in summary['tasks']) or any(s.artifact_issues for s in checked.inputs)
                        or any(o.issues or o.scope_assessment.status in (ScopeStatus.OUT_OF_SCOPE,ScopeStatus.UNSUPPORTED) for o in checked.observations)):
                    stopped=True;reason='source_error_schema_scope_or_unsafe_continuation';break
            entry['collections']=paths;entry['status']='stopped' if stopped else 'bounded_collection_complete'
        if implementation_digest()!=fingerprint: raise EvidenceError('holdout_implementation_changed')
        store.write('holdout-result.json',{'schema_type':'ReadinessHoldoutResult','schema_version':1,'profile':profile,'selection_sha256':digest(chosen),
            'http_requests_reserved':reserved,'stopped':stopped,'stop_reason':reason,'slots':entries,'history':'unknown','freshness':'unknown'})
        store.write('holdout-commit.json',{'schema_type':'ReadinessHoldoutCommit','schema_version':1,'files':store.inventory()})
    return path


def audit_holdout(path,protocol,excluded):
    path=Path(path).absolute();before=inventory(path)
    with EvidenceRoot(path,max_files=2000) as root:
        docs={n:root.read(n).data for n in root.discover()}
    commit=strict_json(docs['holdout-commit.json'])
    expected={'schema_type':'ReadinessHoldoutCommit','schema_version':1,'files':{n:h for n,h in before.items() if n!='holdout-commit.json'}}
    if commit!=expected: raise EvidenceError('holdout_hash_or_inventory_conflict')
    plan=strict_json(docs['pilot-plan.json']);chosen=strict_json(docs['holdout-selection.json']);result=strict_json(docs['holdout-result.json'])
    allowed={'pilot-plan.json','frame-reserved.json','frame-response.json','frame.body','holdout-selection.json','holdout-result.json','holdout-commit.json'}
    if any(n not in allowed and re.fullmatch(r'award-[0-9]{3}/(?:discovery|usaspending|fpds)/(?:c3_plan\.json|c3_checkpoint\.json|c3_summary\.json|c3_attempt_[0-9]{6}\.(?:json|body))',n) is None for n in before):
        raise EvidenceError('unsupported_holdout_inventory')
    expected_plan={'schema_type':'ReadinessHoldoutPlan','schema_version':1,'protocol':protocol.to_dict(),'profile':plan.get('profile'),
        'implementation_sha256':plan.get('implementation_sha256'),'implementation_commit':plan.get('implementation_commit'),
        'config':{'max_run_bytes':32*1024*1024},'excluded_original_ids':sorted(excluded),'maximum_http_requests':protocol.holdout_http_limit,
        'frame_request':frame_request(protocol),'retries':0,'pages_per_task':1}
    if plan!=expected_plan or plan['profile'] not in ('live','synthetic'):
        raise EvidenceError('holdout_protocol_or_exclusion_conflict')
    from .evidence import _hash
    _hash(plan['implementation_sha256'])
    if re.fullmatch('[0-9a-f]{40}',plan['implementation_commit']) is None: raise EvidenceError('holdout_implementation_lineage_invalid')
    if strict_json(docs['frame-reserved.json'])!={'request':frame_request(protocol),'maximum_attempts':1}: raise EvidenceError('holdout_frame_reservation_conflict')
    fm=strict_json(docs['frame-response.json'])
    good=fm['status'] is not None and 200<=fm['status']<300 and not fm['error_code'] and fm['body_complete'] and 'frame.body' in docs
    if good:
        from .evidence import _timestamp
        try:
            if fm['retrieved_at_utc'] is None: raise ValueError('missing time')
            _timestamp(fm['retrieved_at_utc'])
        except (ValueError,TypeError): good=False
    expected_selection=None
    if good:
        try: expected_selection=selection(docs['frame.body'],set(excluded),protocol)
        except (ValueError,KeyError,TypeError): pass
    if expected_selection is not None and expected_selection!=chosen: raise EvidenceError('holdout_selection_changed')
    if expected_selection is None and chosen!= {'schema_type':'ReadinessHoldoutSelection','schema_version':1,'selected':[],'overlap_exclusions':[],
        'conflicting_frame_exclusions':[],'frame_rows':None,'frame_sha256':None,'protocol_sha256':protocol.protocol_sha256,'replacement_policy':'none'}:
        raise EvidenceError('unsupported_holdout_selection_state')
    if result['selection_sha256']!=digest(chosen) or not 1<=result['http_requests_reserved']<=protocol.holdout_http_limit:
        raise EvidenceError('holdout_budget_or_selection_conflict')
    if result['http_requests_reserved']!=1+sum(re.fullmatch(r'award-[0-9]{3}/(?:discovery|usaspending|fpds)/c3_attempt_[0-9]{6}\.json',n) is not None for n in before):
        raise EvidenceError('holdout_request_count_conflict')
    if len(result['slots'])!=len(chosen['selected']): raise EvidenceError('holdout_selected_slot_count_conflict')
    registered=set()
    for i,entry in enumerate(result['slots']):
        if entry['collection'] is not None: registered.add(f'award-{i:03d}/discovery')
        registered.update(entry.get('collections',[]))
    if any(n.startswith('award-') and '/'.join(n.split('/')[:2]) not in registered for n in before):
        raise EvidenceError('unselected_or_unregistered_holdout_capture')
    frame_meta=strict_json(docs['frame-response.json'])
    if frame_meta['body_sha256']!=before.get('frame.body'): raise EvidenceError('holdout_frame_body_hash_conflict')
    if frame_meta['representation']!='application_response_bytes_not_wire_capture': raise EvidenceError('holdout_representation_conflict')
    for name,raw in docs.items():
        if name.endswith('/c3_plan.json'):
            cp=strict_json(raw)
            if cp['profile']!=('live' if plan['profile']=='live' else 'fixture:'+digest(plan)) or cp['limits']['max_pages']!=1 or cp['limits']['retries']!=0 or cp['limits']['max_requests']!=1 or cp.get('stop_on_context_mismatch') is not True:
                raise EvidenceError('holdout_capture_limits_or_profile_conflict')
    metadata=[(n,strict_json(raw)) for n,raw in docs.items() if n=='frame-response.json' or re.fullmatch(r'award-[0-9]{3}/(?:discovery|usaspending|fpds)/c3_attempt_[0-9]{6}\.json',n)]
    http_good=sum(m['status'] is not None and 200<=m['status']<300 and not m['error_code'] and m['body_complete'] for _,m in metadata)
    from .readiness_audit import ref
    evidence=ordered(ref('holdout',n,before[n],'Preserved holdout HTTP metadata including frame/discovery; distinct from record quality') for n,_ in metadata)
    auxiliary=[]
    for name,m in metadata:
        if m['status'] is None or not 200<=m['status']<300 or m['error_code']:
            auxiliary.append(CauseOccurrence(subject_key=name,unit='artifact',codes=('source_access_failure',),
                evidence_ids=(next(e.evidence_id for e in evidence if e.relative_path==name),)))
    slots=[]
    for i,identifier in enumerate(chosen['selected']):
        entry=result['slots'][i]
        if entry['slot']!=i or entry['selected_native_id']!=identifier: raise EvidenceError('holdout_slot_selection_conflict')
        # Combine the two independently validated single-source roots into one
        # slot audit without fabricating a C3 journal or editing either root.
        paths=entry.get('collections',[])
        if len(paths)==2:
            from .readiness_merge import audit_snapshot_pair
            if paths!=[f'award-{i:03d}/usaspending',f'award-{i:03d}/fpds']: raise EvidenceError('holdout_collection_path_conflict')
            slots.append(audit_snapshot_pair([path/Path(*parts(p)) for p in paths],i,identifier,f'holdout/award-{i:03d}'))
        elif len(paths)==1:
            if paths!=[f'award-{i:03d}/usaspending']: raise EvidenceError('holdout_partial_source_path_conflict')
            slots.append(audit_collection(path/Path(*parts(paths[0])),i,identifier,'holdout/'+paths[0]))
        elif entry['collection'] is not None:
            if entry['collection']!=f'award-{i:03d}/discovery': raise EvidenceError('holdout_discovery_path_conflict')
            slots.append(audit_collection(path/Path(*parts(entry['collection'])),i,identifier,'holdout/'+entry['collection']))
        else: slots.append(unavailable_slot(i,identifier,f'holdout/slot-{i:03d}'))
    return CohortAudit(role='holdout',sample_sha256=digest(chosen),inventory_sha256=digest(before),source_plan_sha256=digest(plan),
        original_implementation_sha256=plan['implementation_sha256'],selected_count=len(chosen['selected']),slots=tuple(slots),available=bool(chosen['selected']),
        unchanged=inventory(path)==before,profile=plan['profile'],limitations=('new_bounded_sorted_prefix_not_probability_sample','no_replacements_after_discovery','shared_procurement_lineage_not_independent'),
        auxiliary_measurements=(Measurement(name='all_holdout_HTTP_success',numerator=http_good,denominator=len(metadata),unit='all_holdout_HTTP_requests_including_frame_and_discovery'),),
        evidence=evidence,auxiliary_causes=ordered(auxiliary))
