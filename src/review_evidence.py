"""Review-ready evidence packaging and unverified copy/backup declarations.

No actual approval, participant authentication, enrollment or real-data deletion.
Only allowlisted public repository source hashes/links and normalized tests leave
this module. Raw JUnit, private study files and arbitrary attachments are excluded.
"""
import argparse
from dataclasses import dataclass
from enum import Enum
from html import escape
from pathlib import Path
import hashlib
import os
import re
import stat
import subprocess

from .evidence import Schema, _hash
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json, safe_xml
from .review_packet_io import atomic_create, new_directory
from .pilot_session_store import private_location, _private_fd
from .technical_assessment_reporting import assessment

ROOT=Path(__file__).resolve().parents[1]
PROTOCOL_SHA='7f627ef251d66f272abea7bcf5a444b4daa7af7f9a41d2a683328ef2ad08122b'
LIMIT=16*1024*1024


class CopyState(str,Enum):
    UNKNOWN='UNKNOWN'
    PRESENT='PRESENT'
    CLAIMED_DELETED='CLAIMED_DELETED'


class InventoryState(str,Enum):
    UNKNOWN='UNKNOWN'
    PARTIAL='PARTIAL'
    DECLARED_COMPLETE='DECLARED_COMPLETE'


@dataclass(frozen=True,kw_only=True)
class CopyDeclaration(Schema):
    copy_id: str
    kind: str
    state: CopyState
    evidence_sha256: str | None = None

    def validate(self):
        if not re.fullmatch(r'COPY-[a-f0-9]{16}',self.copy_id) or self.kind not in ('MANAGED_COPY','BACKUP','SNAPSHOT'):
            raise ValueError('opaque_scoped_copy_reference_required')
        if self.evidence_sha256 is not None:_hash(self.evidence_sha256)
        if self.state is CopyState.CLAIMED_DELETED and self.evidence_sha256 is None:
            raise ValueError('deletion_claim_requires_referenced_evidence_not_local_unlink')


@dataclass(frozen=True,kw_only=True)
class CopyInventory(Schema):
    scope_sha256: str
    declarations: tuple[CopyDeclaration,...] = ()
    completeness: InventoryState = InventoryState.UNKNOWN

    def validate(self):
        _hash(self.scope_sha256)
        if len(self.declarations)>128:raise ValueError('copy_inventory_limit')
        ids=[digest(d.to_dict()) for d in self.declarations]
        if len(ids)!=len(set(ids)):raise ValueError('duplicate_copy_declaration')


def copy_assessment(value,scope_sha256):
    if value.scope_sha256!=scope_sha256:raise EvidenceError('copy_inventory_scope_replay')
    groups={}
    for d in value.declarations:groups.setdefault(d.copy_id,[]).append(d)
    conflicting=sum(len({(d.kind,d.state) for d in records})>1 for records in groups.values())
    return {'known_declared_copy_count':len(groups),'declared_completeness':value.completeness.value,
        'conflicting_copy_count':conflicting,'verified_copy_count':None,'unmanaged_copy_count':None,
        'backup_deletion_verified':False,'approval_authenticity':'UNKNOWN',
        'status':'CONFLICTING_DECLARATIONS' if conflicting else 'EXTERNAL_VERIFICATION_REQUIRED',
        'actual_enrollment_authorized':False,'real_data_deletion_authorized':False,
        'limitations':'No files/copies/backups are discovered, revoked or erased; declarations and hashes are not authenticated approvals.'}


def protocol():
    p=strict_json((ROOT/'docs'/'review-preparation-protocol-v1.json').read_bytes())
    if digest(p)!=PROTOCOL_SHA:raise EvidenceError('review_preparation_protocol_changed')
    for name,sha in p['frozen_documents'].items():
        if hashlib.sha256((ROOT/'docs'/name).read_bytes()).hexdigest()!=sha:raise EvidenceError('review_frozen_document_changed')
    return p


def allowed(name):
    path=Path(name)
    return (len(path.parts)==2 and path.parts[0] in ('src','tests') and path.suffix=='.py'
        or len(path.parts)==2 and path.parts[0]=='docs' and path.suffix in ('.json','.md')
        or name in ('README.md','requirements.txt'))


def source_manifest():
    names=['README.md','requirements.txt']
    for folder,suffixes in (('src',('.py',)),('tests',('.py',)),('docs',('.md','.json'))):
        names.extend(p.relative_to(ROOT).as_posix() for p in (ROOT/folder).iterdir() if p.suffix in suffixes)
    with EvidenceRoot(ROOT,max_bytes=LIMIT,max_total_bytes=LIMIT,max_files=2000) as root:
        manifest={name:root.read(name).byte_sha256 for name in sorted(names)}
        if any(not allowed(name) for name in manifest):raise EvidenceError('source_manifest_scope_expansion')
        if {n:root.read(n,recheck=True).byte_sha256 for n in manifest}!=manifest:raise EvidenceError('review_source_changed')
    return manifest


def input_digest():
    protocol();return digest(source_manifest())


def git_binding(manifest,expected_head):
    if not isinstance(expected_head,str) or re.fullmatch('[a-f0-9]{40,64}',expected_head) is None:
        raise EvidenceError('exact_review_commit_required')
    def git(*args):
        try:return subprocess.check_output(['git',*args],cwd=ROOT,stderr=subprocess.DEVNULL).decode().strip()
        except (subprocess.SubprocessError,UnicodeError):raise EvidenceError('review_git_binding_unavailable') from None
    if git('rev-parse','HEAD')!=expected_head:raise EvidenceError('review_head_changed')
    algorithm=git('rev-parse','--show-object-format')
    if algorithm not in ('sha1','sha256'):raise EvidenceError('unsupported_git_object_format')
    entries={}
    for line in git('ls-tree','-r',expected_head,'--','src','tests','docs','README.md','requirements.txt').splitlines():
        meta,name=line.split('\t',1)
        if not allowed(name):continue
        mode,kind,oid=meta.split()
        if mode not in ('100644','100755') or kind!='blob':raise EvidenceError('review_source_link_or_unsupported_type')
        entries[name]=oid
    if set(entries)!=set(manifest):raise EvidenceError('uncommitted_or_missing_review_source')
    with EvidenceRoot(ROOT,max_bytes=LIMIT,max_total_bytes=LIMIT) as root:
        for name,oid in entries.items():
            raw=root.read(name).data
            if hashlib.sha256(raw).hexdigest()!=manifest[name] or hashlib.new(algorithm,b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=oid:
                raise EvidenceError('review_source_not_exact_commit')
    return {name:{'sha256':manifest[name],'git_blob':entries[name],
        'url':'https://github.com/yvcohen-cs/federal-spending-auditor/blob/'+expected_head+'/'+name} for name in sorted(entries)}


def package(raw,expected_head,inventory=None):
    p=protocol();manifest=source_manifest();scope=digest(manifest)
    _,xml=safe_xml(raw)
    values=[v.attrib.get('value') for v in xml.iter('property') if v.attrib.get('name')=='review_preparation_input_sha256']
    if not values or set(values)!={scope}:raise EvidenceError('review_receipt_not_bound_to_package_inputs')
    technical=assessment(raw)
    if not technical['automated_tests'].get('all_recorded_tests_passed'):raise EvidenceError('review_tests_not_all_passed')
    sources=git_binding(manifest,expected_head)
    return {'schema_type':'IndependentReviewEvidencePackage','schema_version':1,'version':'review-evidence-v1',
        'starting_main':p['starting_main'],'review_head':expected_head,'input_sha256':scope,
        'protocol_sha256':PROTOCOL_SHA,'source_files':sources,'technical_assessment':technical,
        'copy_backup_governance':copy_assessment(inventory or CopyInventory(scope_sha256=scope),scope),
        'review_requirements':[{'scope':s,'status':'NOT_ESTABLISHED','responsible_role':role,'required_evidence':e} for s,role,e in (
            ('security','independent_security_reviewer','Inspect exact commit, deletion journal, fault tests and residual same-user/inode threats.'),
            ('privacy','privacy_officer','Verify minimization, requests, copies/backups, retention and disclosure responsibilities.'),
            ('accessibility','accessibility_specialist','Evaluate terminal/AT versions and nonparticipant navigation; unit tests are not conformance.'),
            ('institutional','institutional_authority','Independently authenticate all seven prospective approval categories and consent scope.'),
            ('storage','storage_administrator','Verify encryption/access/isolation, copy inventory and authenticated backup deletion evidence.'))],
        'external_approval':{'status':'NOT_ESTABLISHED','records':[]},'actual_human_study':'NOT_CONDUCTED',
        'actual_enrollment_enabled':False,'real_data_deletion_enabled':False,'production_screening_enabled':False,
        'financial_eligibility_changed':False,'frozen_readiness_upgrade':False,
        'package_limits':['Public source hashes and immutable repository links only; no source study files or arbitrary attachments.',
            'Normalized local tests are not authenticated external attestations.',
            'No claim of secure erasure, global copy revocation, host isolation or actual AT/human performance.']}


def markdown(value):
    lines=['# Phase 4C8 independent-review evidence package','',
        'Prepared for independent review. No independent approval or real-study authorization is established.']
    for key in sorted(value):lines.extend(['','## '+key,'','    '+canonical(value[key])])
    return '\n'.join(lines)+'\n'


def files(value):
    text=markdown(value)
    html='<!doctype html><html lang="en"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; base-uri \'none\'; form-action \'none\'"><title>Independent review package</title><h1>Independent review package</h1><pre>'+escape(text)+'</pre></html>'
    return {'review-package.json':(canonical({'package':value,'sha256':digest(value)})+'\n').encode(),
        'review-package.md':text.encode(),'review-package.html':html.encode()}


def write_package(path,raw,expected_head,inventory=None):
    value=package(raw,expected_head,inventory);target=private_location(path)
    for parent in (target,)+tuple(target.parents):
        if any((parent/n).exists() for n in ('coordinator-context.json','coordinator-report-commit.json','assessment-commit.json','review-package-commit.json')):
            raise EvidenceError('review_package_inside_managed_root')
    content=files(value)
    if sum(map(len,content.values()))>LIMIT:raise EvidenceError('review_package_limit')
    new_directory(target)
    with EvidenceRoot(target,max_bytes=LIMIT,max_total_bytes=2*LIMIT) as root:
        for name,data in content.items():atomic_create(root.fd,name,data)
        if value!=package(raw,expected_head,inventory):raise EvidenceError('review_inputs_changed')
        atomic_create(root.fd,'review-package-commit.json',(canonical({'schema_type':'ReviewPackageCommit','schema_version':1,
            'files':{n:hashlib.sha256(data).hexdigest() for n,data in content.items()}})+'\n').encode())
    return digest(value)


def read_package(path,raw,expected_head,inventory=None):
    with EvidenceRoot(path,max_bytes=LIMIT,max_total_bytes=2*LIMIT,max_files=4) as root:
        _private_fd(root.fd);data={n:root.read(n) for n in root.discover()}
        if set(data)!={'review-package.json','review-package.md','review-package.html','review-package-commit.json'}:raise EvidenceError('truncated_review_package')
        for name in data:
            st=os.stat(name,dir_fd=root.fd,follow_symlinks=False)
            if st.st_uid!=os.getuid() or stat.S_IMODE(st.st_mode)!=0o600:raise EvidenceError('private_review_package_required')
        expected={'schema_type':'ReviewPackageCommit','schema_version':1,'files':{n:s.byte_sha256 for n,s in data.items() if n!='review-package-commit.json'}}
        if strict_json(data['review-package-commit.json'].data)!=expected:raise EvidenceError('review_package_hash_conflict')
        value=package(raw,expected_head,inventory)
        if any(data[n].data!=raw for n,raw in files(value).items()):raise EvidenceError('review_package_not_primary_projection')
        if {n:root.read(n,recheck=True).byte_sha256 for n in root.discover()}!={n:s.byte_sha256 for n,s in data.items()}:raise EvidenceError('review_package_changed')
    return value


def main(argv=None):
    p=argparse.ArgumentParser(description='Offline independent-review package; no actual enrollment or real-data deletion.')
    p.add_argument('--test-results',required=True);p.add_argument('--expected-head',required=True);p.add_argument('--output',required=True)
    a=p.parse_args(argv)
    try:
        path=Path(a.test_results).absolute()
        with EvidenceRoot(path.parent,max_bytes=LIMIT,max_total_bytes=LIMIT) as root:raw=root.read(path.name).data
        print(canonical({'package_sha256':write_package(a.output,raw,a.expected_head),'external_approval':'NOT_ESTABLISHED'}));return 1
    except (ValueError,TypeError,KeyError,IndexError,OSError,RecursionError):
        print(canonical({'error_code':'review_package_blocked_or_invalid_no_private_details'}));return 2


if __name__=='__main__':raise SystemExit(main())
