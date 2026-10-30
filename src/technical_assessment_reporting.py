"""Deterministic engineering assessment, with explicit local-test evidence scope."""
import argparse
from collections import Counter
from html import escape
from pathlib import Path
import hashlib
import re
import os
import stat
import xml.etree.ElementTree as ET

from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json, safe_xml
from .review_packet_io import atomic_create, new_directory
from .pilot_session_store import private_location, _private_fd
from .technical_assessment import ROOT, PROTOCOL_SHA, protocol, documents, code_digest

LIMIT=8*1024*1024


def test_receipt(raw):
    """Normalize generated JUnit, excluding times, paths, output and user text.

    Local receipts are not authenticated CI attestations. Bound source properties
    prevent accidental reuse after edits, not forgery by a filesystem owner.
    """
    if len(raw)>LIMIT:raise EvidenceError('test_receipt_size_limit')
    _,tree=safe_xml(raw)
    if tree.tag not in ("testsuite","testsuites"):raise EvidenceError("unsupported_test_receipt_root")
    properties=[e.attrib.get('value') for e in tree.iter('property') if e.attrib.get('name')=='technical_assessment_code_sha256']
    if not properties or set(properties)!={code_digest()}:
        raise EvidenceError('test_receipt_not_bound_to_current_code')
    outcomes={}
    for case in tree.iter('testcase'):
        if not case.attrib.get('classname') or not case.attrib.get('name'):
            raise EvidenceError('missing_test_identity')
        if any(child.tag not in ('properties','failure','error','skipped','system-out','system-err') for child in case):
            raise EvidenceError('unsupported_test_outcome_element')
        identifier=case.attrib['classname']+'::'+case.attrib['name']
        if identifier in outcomes:raise EvidenceError('duplicate_test_result')
        states=[tag for tag in ('failure','error','skipped') if case.find(tag) is not None]
        if len(states)>1:raise EvidenceError('contradictory_test_outcome')
        outcomes[identifier]=states[0] if states else 'passed'
    if not outcomes:raise EvidenceError('empty_test_receipt')
    for suite in tree.iter('testsuite'):
        cases=list(suite.iter('testcase'))
        expected={'tests':len(cases),'failures':sum(c.find('failure') is not None for c in cases),
            'errors':sum(c.find('error') is not None for c in cases),'skipped':sum(c.find('skipped') is not None for c in cases)}
        for key,value in expected.items():
            if key in suite.attrib and suite.attrib[key]!=str(value):raise EvidenceError('contradictory_test_summary')
    counts=dict(Counter(outcomes.values()))
    return {'category':'AUTOMATED_TEST_RESULT','scope':'LOCAL_JUNIT_DECLARATION_NOT_AUTHENTICATED_EXTERNAL_ATTESTATION',
        'code_sha256':code_digest(),'normalized_outcomes_sha256':digest(outcomes),'counts':counts,
        'all_recorded_tests_passed':set(counts)=={'passed'},'recorded_test_count':len(outcomes)},outcomes


def assessment(raw=None):
    p=protocol();docs=documents()
    receipt,outcomes=test_receipt(raw) if raw is not None else ({'category':'UNKNOWN','status':'NOT_EVALUATED_no_test_receipt'}, {})
    findings=[]
    for entry in docs['technical-findings-v1.json']['findings']:
        f=dict(entry)
        matches={test:[state for name,state in outcomes.items() if name.split('::')[-1].split('[')[0]==test] for test in f['tests']}
        f['automated_verification']='RECORDED_LOCAL_REGRESSIONS_PASSED' if matches and all(v and set(v)=={'passed'} for v in matches.values()) else 'NOT_ESTABLISHED_BY_RECEIPT'
        f['evidence_category']='TECHNICAL_CODE_REVIEW'
        findings.append(f)
    current={name:hashlib.sha256((ROOT/'src'/name).read_bytes()).hexdigest() for name in p['reviewed_modules']}
    readiness=[]
    statuses={
        'software_integrity':('PREPARED_WITH_LIMITATIONS','Local regression evidence is separate from external inspection.'),
        'evidence_traceability':('LOCAL_HASH_BINDING','Preserved bytes do not authenticate remote sources.'),
        'session_authorization':('LOCAL_CAPABILITY_ONLY','No person authentication or global copy revocation.'),
        'consent_state_enforcement':('SOFTWARE_GATE_ONLY','Voluntariness, eligibility and understanding require external verification.'),
        'deletion_safety':('SIMULATED_ONLY','V2 binds retained objects; v1 read-only. No real-data deletion enabled.'),
        'backup_governance':('UNKNOWN','No authenticated managed-copy or backup deletion evidence.'),
        'privacy_controls':('PREPARED_WITH_LIMITATIONS','Minimization and suppression are not anonymity or legal certification.'),
        'accessibility':('UNKNOWN','Software presentation checks do not establish assistive-technology performance.'),
        'independent_approval_authenticity':('UNKNOWN','No independent authority or external review verified.'),
        'human_usability_evidence':('UNKNOWN','No actual human study.'),
        'human_throughput_evidence':('UNKNOWN','No actual human throughput measurement.'),
        'historical_financial_source_readiness':('UNCHANGED_UNRESOLVED','Frozen financial history/revision/source proof obligations remain separate.')}
    for dimension in p['readiness_dimensions']:
        status,reason=statuses[dimension];readiness.append({'dimension':dimension,'status':status,'reason':reason})
    return {'schema_type':'TechnicalAssessmentReport','schema_version':1,'version':'technical-assessment-report-v1',
        'starting_main_commit':p['starting_commit'],'preregistration_sha256':PROTOCOL_SHA,
        'assessment_code_sha256':code_digest(),'reviewed_baseline_modules':p['reviewed_modules'],'current_modules':current,
        'preserved_document_hashes':p['frozen_documents'],
        'historical_inventories':{'expected':p['frozen_inventories'],'verification':'NOT_EVALUATED_BY_GENERATOR_requires_original_permitted_roots'},
        'input_document_digests':{name:digest(v) for name,v in docs.items()},
        'technical_review':{'category':'TECHNICAL_CODE_REVIEW','scope':'engineering_challenge_not_independent_human_certification',
            'findings':findings,'finding_counts':dict(Counter(f['category'] for f in findings)),
            'severity_counts':dict(Counter(f['severity'] for f in findings))},
        'automated_tests':receipt,'documented_requirements':{'category':'DOCUMENTED_REQUIREMENT',
            'pre_pilot_checklist':docs['pre-pilot-checklist-v1.json']['requirements']},
        'external_approval':{'category':'EXTERNAL_APPROVAL','status':'NOT_ESTABLISHED','records':[]},
        'actual_human_observation':{'category':'ACTUAL_HUMAN_OBSERVATION','status':'NOT_CONDUCTED','records':[]},
        'unknown':{'category':'UNKNOWN','outcomes':['Independent authority authenticity','Human accessibility/usability/throughput',
            'Encryption, physical access, backups, snapshots, global revocation and secure erasure']},
        'readiness':readiness,'combined_score':None,'actual_pilot_authorized':False,
        'real_data_deletion_enabled':False,'financial_eligibility_changed':False,'frozen_readiness_upgrade':False,
        'production_screening_authorized':False,
        'remediation_priorities':['Independently inspect target binding and real-data deletion design.',
            'Obtain externally verified approval, storage, backup and consent arrangements.',
            'Perform separately approved assistive-technology checks before considering voluntary pilot enrollment.'],
        'next_phase':'Phase 4C8: independent external sign-off and nonparticipant assistive-technology/storage validation; no automatic pilot authorization.'}


def markdown(value):
    lines=['# Phase 4C7 engineering assessment','', 'No external audit, approval, human study, real-data deletion or production authority is established.']
    for name in sorted(value):lines.extend(['','## '+name,'','    '+canonical(value[name])])
    return '\n'.join(lines)+'\n'


def html(value):
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; base-uri \'none\'; form-action \'none\'"><title>Technical assessment</title><h1>Technical assessment</h1><pre>'+escape(markdown(value))+'</pre></html>'


def files(value):
    return {'assessment.json':(canonical({'report':value,'substantive_sha256':digest(value)})+'\n').encode(),
        'assessment.md':markdown(value).encode(),'assessment.html':html(value).encode()}


def write_report(path,raw=None):
    value=assessment(raw);target=private_location(path)
    for ancestor in (target,)+tuple(target.parents):
        if any((ancestor/n).exists() for n in ('coordinator-context.json','coordinator-report-commit.json','assessment-commit.json')):
            raise EvidenceError('assessment_output_inside_managed_root')
    content=files(value)
    if sum(map(len,content.values()))>LIMIT:raise EvidenceError('assessment_report_limit')
    new_directory(target)
    with EvidenceRoot(target,max_bytes=LIMIT,max_total_bytes=2*LIMIT) as root:
        for name,data in content.items():atomic_create(root.fd,name,data)
        if value!=assessment(raw):raise EvidenceError('assessment_inputs_changed')
        atomic_create(root.fd,'assessment-commit.json',(canonical({'schema_type':'TechnicalAssessmentCommit','schema_version':1,
            'files':{n:hashlib.sha256(b).hexdigest() for n,b in content.items()}})+'\n').encode())
    return digest(value)


def read_report(path,raw=None):
    with EvidenceRoot(path,max_bytes=LIMIT,max_total_bytes=2*LIMIT,max_files=4) as root:
        _private_fd(root.fd);data={n:root.read(n) for n in root.discover()}
        if set(data)!={'assessment.json','assessment.md','assessment.html','assessment-commit.json'}:raise EvidenceError('truncated_assessment_report')
        for name in data:
            st=os.stat(name,dir_fd=root.fd,follow_symlinks=False)
            if st.st_uid!=os.getuid() or stat.S_IMODE(st.st_mode)!=0o600:raise EvidenceError('private_assessment_report_required')
        expected={'schema_type':'TechnicalAssessmentCommit','schema_version':1,'files':{n:s.byte_sha256 for n,s in data.items() if n!='assessment-commit.json'}}
        if strict_json(data['assessment-commit.json'].data)!=expected:raise EvidenceError('assessment_report_hash_conflict')
        value=assessment(raw)
        if any(data[n].data!=b for n,b in files(value).items()):raise EvidenceError('assessment_not_primary_projection')
        if {n:root.read(n,recheck=True).byte_sha256 for n in root.discover()}!={n:s.byte_sha256 for n,s in data.items()}:raise EvidenceError('assessment_changed')
    return value


def main(argv=None):
    p=argparse.ArgumentParser(description='Offline engineering assessment, not external certification.')
    p.add_argument('--output',required=True);p.add_argument('--test-results')
    a=p.parse_args(argv)
    try:
        raw=None
        if a.test_results:
            target=Path(a.test_results).absolute()
            with EvidenceRoot(target.parent,max_bytes=LIMIT,max_total_bytes=LIMIT) as root:raw=root.read(target.name).data
        print(canonical({'substantive_sha256':write_report(a.output,raw),'actual_human_study':'NOT_CONDUCTED'}));return 1
    except (ValueError,TypeError,KeyError,IndexError,OSError,RecursionError):
        print(canonical({'error_code':'assessment_blocked_or_invalid_no_private_details'}));return 2


if __name__=='__main__':raise SystemExit(main())
