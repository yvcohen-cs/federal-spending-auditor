"""Preregistered authored fixtures and two scripted, nonhuman reviewer sequences."""
from copy import deepcopy
from pathlib import Path
from xml.sax.saxutils import escape

from .collection import CollectionLimits, SelectedAward, collect_selected
from .collection_sources import FixtureTransport
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json
from .review_packet_io import atomic_create, new_directory, write_bundle
from .review_packet_html import render_html
from .review_validation_models import DecisionRationale, ReviewDecision as D, ReviewKind
from .review_validation_tasks import build_tasks, inventory, check_new_location
from .review_validation_events import append_decision, read_decisions
from .review_packet_models import RecommendedVerificationAction

PROTOCOL_SHA='499022ecd94bc5c0753ca3bacbddfa53659e498e0552bfc628fd6f829091fe8f'
PROTOCOL_PATH=Path(__file__).resolve().parents[1]/'docs'/'review-validation-protocol-v1.json'
FOCUS={'verified_identity':'identity','ambiguous_identity':'identity','missing_parent':'parent',
    'contradictory_parent':'parent','unsupported_instrument':'instrument','incomplete_pagination':'pagination',
    'duplicate_records':'identity','missing_counterpart':'history','unknown_revision':'revision',
    'conflicting_money':'monetary_observations','unavailable_capture':'history'}


def protocol():
    value=strict_json(PROTOCOL_PATH.read_bytes())
    if digest(value)!=PROTOCOL_SHA: raise EvidenceError('review_validation_protocol_changed')
    return value


def put(path,name,value):
    with EvidenceRoot(path,max_bytes=32*1024*1024,max_total_bytes=64*1024*1024) as root:
        atomic_create(root.fd,name,(canonical(value)+'\n').encode())


def fixture(case_id):
    # Author-generated source-shaped records, never actual award data.
    row={'id':'CONT_TX_0001_0002_SYNTH-REVIEW-0001_P00001_SYNTH-REVIEW-PARENT_0',
        'modification_number':'P00001','action_date':'2025-01-01','federal_action_obligation':100}
    entry=('<entry><content><f:award version="1.5"><f:contractData><f:contractActionType>C</f:contractActionType></f:contractData>'
        '<f:awardID><f:awardContractID><f:agencyID>0001</f:agencyID><f:PIID>SYNTH-REVIEW-0001</f:PIID>'
        '<f:modNumber>P00001</f:modNumber><f:transactionNumber>0</f:transactionNumber></f:awardContractID>'
        '<f:referencedIDVID><f:agencyID>0002</f:agencyID><f:PIID>SYNTH-REVIEW-PARENT</f:PIID></f:referencedIDVID></f:awardID>'
        '<f:dollarValues><f:obligatedAmount>100.00</f:obligatedAmount></f:dollarValues>'
        '<f:relevantContractDates><f:signedDate>2025-01-01</f:signedDate></f:relevantContractDates></f:award></content></entry>')
    rows=[row];entries=[entry]
    if case_id=='ambiguous_identity':
        row['id']=row['id'].removesuffix('_0')+'_-NONE-'
        entries.append(entry.replace('<f:transactionNumber>0','<f:transactionNumber>1'))
    elif case_id=='missing_parent':
        start=entry.index('<f:referencedIDVID>');end=entry.index('</f:referencedIDVID>')+len('</f:referencedIDVID>')
        entries=[entry[:start]+entry[end:]]
        row['id']=row['id'].replace('_SYNTH-REVIEW-PARENT_','_-NONE-_')
    elif case_id=='contradictory_parent': entries=[entry.replace('SYNTH-REVIEW-PARENT','SYNTH-OTHER-PARENT')]
    elif case_id=='unsupported_instrument': entries=[entry.replace('<f:contractActionType>','<f:contractActionType unsupported="true">')]
    elif case_id=='duplicate_records': rows.append(deepcopy(row));entries.append(entry)
    elif case_id=='missing_counterpart': entries=[]
    elif case_id=='conflicting_money': entries=[entry.replace('100.00','101.00')]
    response={'source':'fpds','text':'<feed xmlns="http://www.w3.org/2005/Atom" xmlns:f="https://www.fpds.gov/FPDS">'+''.join(entries)+'</feed>'}
    if case_id=='unavailable_capture': response.update(status=503,body_complete=False)
    return {'schema_version':1,'responses':[{'source':'usaspending','json':{'page_metadata':{'page':1,'hasNext':case_id=='incomplete_pagination'},'results':rows}},response]}


def study_inventory(path):
    with EvidenceRoot(path,max_bytes=8*1024*1024,max_total_bytes=32*1024*1024,max_files=1000) as root:
        before={n:root.read(n) for n in root.discover()}
        hashes={n:s.byte_sha256 for n,s in before.items()}
        if {n:root.read(n,recheck=True).byte_sha256 for n in root.discover()}!=hashes:
            raise EvidenceError('review_study_source_changed')
        return hashes


def selected_tasks(source,case_id=None):
    full=build_tasks(source)
    packet=next(p for p in full.packets.packets if p.claim.financial_result) if case_id in ('conflicting_money','unknown_revision') else next(p for p in full.packets.packets if p.claim.identity_result and p.claim.identity_result.claim=='action_equivalence')
    return build_tasks(source,claim_ids=(packet.claim.claim_id,))


def create_study(path):
    plan=protocol();target=check_new_location(path,study=True);new_directory(target)
    put(target,'study-plan.json',{'schema_type':'OfflineReviewStudyPlan','schema_version':1,'protocol_sha256':PROTOCOL_SHA,
        'cases':[c['case_id'] for c in plan['cases']],'actual_human_participants':None,'network_requests':0})
    award=SelectedAward(generated_id='CONT_AWD_SYNTH-REVIEW-0001_0001_SYNTH-REVIEW-PARENT_0002',
        piid='SYNTH-REVIEW-0001',agency_id='0001',parent_piid='SYNTH-REVIEW-PARENT',parent_agency_id='0002')
    for spec in plan['cases']:
        case=target/spec['case_id'];new_directory(case)
        data=fixture(spec['case_id'])
        collect_selected(case/'source',(award,),limits=CollectionLimits(max_pages=1,retries=0,pace_seconds=0.0),
            profile='fixture:'+digest(data),transport=FixtureTransport(data),sleep=lambda _:None)
        tasks=selected_tasks(case/'source',spec['case_id'])
        if spec['expect_integrity_block']:
            bundle=case/'invalid-packet-bundle';write_bundle(bundle,tasks.packets,render_html(tasks.packets))
            # Authored adversarial fixture: coherent outer hash, invalid inner
            # citation. Source evidence is never modified by this operation.
            doc=strict_json((bundle/'packets.json').read_bytes())
            doc['packets'][0]['citations'][0]['evidence']['artifact']['sha256']='0'*64
            (bundle/'packets.json').write_text(canonical(doc)+'\n')
            commit={'schema_type':'ReviewOutputCommit','schema_version':1,'files':{n:s for n,s in inventory(bundle).items() if n!='output-manifest.json'}}
            (bundle/'output-manifest.json').write_text(canonical(commit)+'\n')
            continue
        task=tasks.tasks[0]
        # Each sequence is separately specified in the preregistration; B never
        # reads A's output and neither represents an actual person.
        for sequence in ('A','B'):
            decision=D(spec['sequence_'+sequence])
            rationale=DecisionRationale(interpretation='Preregistered simulated evidence-quality decision for '+spec['case_id']+'.',
                scope_explanation='Only this saved narrow claim; no financial, identity or misconduct authority added.',
                uncertainty='All listed proof obligations remain unresolved; scripted choices do not measure human performance.',
                citation_ids=tuple(sorted(c.citation_id for c in task.citations)),acknowledged_obligations=task.missing_proof_obligations)
            append_decision(case/('sequence-'+sequence),case/'source',tasks,task_id=task.task_id,
                decision=decision,rationale=rationale,kind=ReviewKind.SIMULATED,attribution_label='SIMULATED:sequence-'+sequence,
                timestamp_utc='2025-02-01T00:00:00Z',follow_up=(RecommendedVerificationAction(instruction='Obtain the missing primary proof and request independent adjudication if decisions conflict.',citation_ids=rationale.citation_ids),),
                protected=(target/'study-plan.json',))
    hashes=study_inventory(target)
    put(target,'study-commit.json',{'schema_type':'OfflineReviewStudyCommit','schema_version':1,'files':hashes})
    return target


def replay_study(path):
    from .review_validation_reporting import task_report
    before=study_inventory(path)
    with EvidenceRoot(path,max_bytes=8*1024*1024,max_total_bytes=32*1024*1024,max_files=1000) as reader:
        commit=strict_json(reader.read('study-commit.json').data)
        saved_plan=strict_json(reader.read('study-plan.json').data)
    expected={'schema_type':'OfflineReviewStudyCommit','schema_version':1,'files':{n:s for n,s in before.items() if n!='study-commit.json'}}
    if commit!=expected or saved_plan!={'schema_type':'OfflineReviewStudyPlan','schema_version':1,'protocol_sha256':PROTOCOL_SHA,
            'cases':[c['case_id'] for c in protocol()['cases']],'actual_human_participants':None,'network_requests':0}:
        raise EvidenceError('review_study_plan_or_inventory_conflict')
    results=[]
    for spec in protocol()['cases']:
        case=Path(path)/spec['case_id']
        if spec['expect_integrity_block']:
            selected_tasks(case/'source',spec['case_id'])  # valid primary baseline required
            try:
                build_tasks(case/'source',packet_bundle=case/'invalid-packet-bundle')
            except (ValueError,TypeError,KeyError,IndexError):
                results.append({'case_id':spec['case_id'],'integrity_blocked':True,'tasks':[],
                    'focus_status':'INSUFFICIENT','simulated_histories':[],
                    'expected_control_met':True,'positive_claims':False})
                continue
            raise EvidenceError('tampered_study_control_unexpectedly_accepted')
        manifest=selected_tasks(case/'source',spec['case_id']);task=manifest.tasks[0];histories=[]
        focus=next(d for d in task.dimensions if d.name==FOCUS[spec['case_id']])
        for sequence in ('A','B'):
            events=read_decisions(case/('sequence-'+sequence),case/'source',manifest,ReviewKind.SIMULATED)
            if len(events)!=1 or events[0].attribution_label!='SIMULATED:sequence-'+sequence:
                raise EvidenceError('study_sequence_envelope_conflict')
            histories.append({'sequence':sequence,'events':[e.to_dict() for e in events],
                'expected_decision_met':events[0].decision.value==spec['sequence_'+sequence]})
        choices={h['events'][0]['decision'] for h in histories}
        result=task_report(case/'source',manifest,())
        results.append({'case_id':spec['case_id'],'integrity_blocked':False,'tasks':result['tasks'],
            'focus_status':focus.status.value,'focus_dimension':FOCUS[spec['case_id']],
            'parent_assessments':result['parent_assessments'],'source_history_summary':result['source_history_summary'],
            'expected_focus_status':spec['expected_focus_status'],'simulated_histories':histories,
            'simulated_disagreement':len(choices)>1,'contradictory_simulated_decisions':{'ACCEPT_EVIDENCE','REJECT_EVIDENCE'}<=choices,
            'disagreement_action':'Preserve both assertions; independent adjudication with new cited evidence; no winner selected.',
            'expected_control_met':focus.status.value==spec['expected_focus_status'] and all(h['expected_decision_met'] for h in histories),
            'financial_authorization':False})
    if study_inventory(path)!=before: raise EvidenceError('review_study_source_changed')
    return results,digest(before)
