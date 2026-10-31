"""Context-bound per-object journal for simulated deletion only.

Local HMACs/locks are not actor authentication. Pending-intent absence recovery is
an observation, not proof that this process performed the unlink. No real-data
request intake, identity mapping, secure erasure or backup deletion is supplied.
"""
import hashlib
import hmac
import os
from pathlib import Path
import re
import stat

from .evidence_io import EvidenceError, EvidenceRoot, _directory, canonical, digest, strict_json
from .review_packet_io import atomic_create

PREFIX='deletion-progress-'
MAX_ENTRIES=8192


def plan(manifest):
    result=[]
    for scope in ('outputs','batch'):
        entries=manifest[scope]
        files=sorted(n for n in entries if not n.startswith(('identity:','directory:')))
        directories=sorted((n[len('directory:'):] for n in entries if n.startswith('directory:')),key=lambda n:(-len(n.split('/')),n))
        for name in files+directories+['.']:
            identity=entries.get('identity:'+name)
            if identity is None:raise EvidenceError('object_progress_requires_bound_capture')
            result.append({'scope':scope,'relative':name,'identity':identity,'sha256':entries.get(name) if identity[2]=='file' else None})
    if not result or len(result)*2>MAX_ENTRIES:raise EvidenceError('object_progress_limit')
    return result


def names(root):
    found=sorted(n for n in os.listdir(root.fd) if n.startswith(PREFIX))
    if len(found)>MAX_ENTRIES or any(re.fullmatch(PREFIX+r'[0-9]{6}\.json',n) is None for n in found):
        raise EvidenceError('partial_or_unsupported_deletion_progress')
    return found


def object_id(context,item):return digest({'context':digest(context),'object':item})


def load(root,context,manifest,secret):
    objects=plan(manifest);found=names(root)
    if found!=[f'{PREFIX}{i:06d}.json' for i in range(len(found))]:raise EvidenceError('missing_or_reordered_object_progress')
    records=[];previous=None;index=0;pending=False
    for sequence,name in enumerate(found):
        value=strict_json(root.read(name).data)
        if not isinstance(value,dict) or set(value)!={'schema_type','schema_version','sequence','previous','context_sha256','object_index','object_id','action','outcome','mac'}:
            raise EvidenceError('invalid_object_progress')
        signed={k:v for k,v in value.items() if k!='mac'}
        if (value['schema_type']!='DeletionObjectEvent' or type(value['schema_version']) is not int or value['schema_version']!=1
                or type(value['sequence']) is not int or value['sequence']!=sequence or value['previous']!=previous
                or value['context_sha256']!=digest(context) or type(value['object_index']) is not int or value['object_index']!=index
                or index>=len(objects) or value['object_id']!=object_id(context,objects[index])
                or not isinstance(value['mac'],str) or not hmac.compare_digest(value['mac'],hmac.new(secret,canonical(signed).encode(),hashlib.sha256).hexdigest())):
            raise EvidenceError('forged_or_replayed_object_progress')
        if not pending:
            if value['action']!='INTENT' or value['outcome'] is not None:raise EvidenceError('object_intent_required')
            pending=True
        else:
            if value['action']!='COMMIT' or value['outcome'] not in ('REMOVED','ABSENCE_OBSERVED_AFTER_INTENT'):
                raise EvidenceError('unsupported_object_completion')
            pending=False;index+=1
        previous=digest(value);records.append(value)
    return objects,records,index,pending


def append(root,context,secret,objects,records,index,action,outcome=None):
    value={'schema_type':'DeletionObjectEvent','schema_version':1,'sequence':len(records),
        'previous':digest(records[-1]) if records else None,'context_sha256':digest(context),
        'object_index':index,'object_id':object_id(context,objects[index]),'action':action,'outcome':outcome}
    value['mac']=hmac.new(secret,canonical(value).encode(),hashlib.sha256).hexdigest()
    atomic_create(root.fd,f'{PREFIX}{len(records):06d}.json',(canonical(value)+'\n').encode())
    records.append(value)


def location(root,item):
    target=Path(root.path)/('retired-'+item['scope'])
    return target if item['relative']=='.' else target/item['relative']


def verify(root,context,manifest,secret):
    objects,records,index,pending=load(root,context,manifest,secret)
    for i,item in enumerate(objects):
        path=location(root,item);present=os.path.lexists(path)
        if i<index:
            if present:raise EvidenceError('completed_deletion_object_reappeared')
        elif not present and not (i==index and pending):
            raise EvidenceError('deletion_object_missing_without_intent')
    return objects,records,index,pending


def _check_target(parent,name,item):
    st=os.stat(name,dir_fd=parent,follow_symlinks=False)
    kind='directory' if stat.S_ISDIR(st.st_mode) else 'file' if stat.S_ISREG(st.st_mode) else 'unsupported'
    if [st.st_dev,st.st_ino,kind]!=item['identity'] or st.st_uid!=os.getuid() or st.st_mode&0o077:
        raise EvidenceError('deletion_progress_target_changed')
    if kind=='file' and st.st_nlink!=1:raise EvidenceError('deletion_progress_hardlink')


def erase(root,context,manifest,secret,boundary):
    objects,records,index,pending=verify(root,context,manifest,secret)
    for i in range(index,len(objects)):
        item=objects[i];path=location(root,item)
        if not (i==index and pending):
            append(root,context,secret,objects,records,i,'INTENT');boundary('object_intent')
        present=os.path.lexists(path)
        if present:
            parent=_directory(path.parent)
            try:
                st=os.fstat(parent)
                if item['relative']=='.':expected_parent=[context['root_device'],context['root_inode'],'directory']
                else:expected_parent=manifest[item['scope']]['identity:'+Path(item['relative']).parent.as_posix()]
                if [st.st_dev,st.st_ino,'directory']!=expected_parent or st.st_uid!=os.getuid() or st.st_mode&0o077:
                    raise EvidenceError('deletion_progress_parent_changed')
                _check_target(parent,path.name,item)
                if item['identity'][2]=='file':
                    with EvidenceRoot(path.parent,max_bytes=64*1024*1024) as reader:
                        if reader.read(path.name).byte_sha256!=item['sha256']:raise EvidenceError('deletion_progress_bytes_changed')
                    _check_target(parent,path.name,item)
                    os.unlink(path.name,dir_fd=parent)
                else:
                    boundary('before_rmdir');_check_target(parent,path.name,item)
                    os.rmdir(path.name,dir_fd=parent)
                os.fsync(parent)
            finally:os.close(parent)
            boundary('object_unlinked')
            outcome='REMOVED'
        else:outcome='ABSENCE_OBSERVED_AFTER_INTENT'
        append(root,context,secret,objects,records,i,'COMMIT',outcome);boundary('object_committed')
        if present:
            if item['identity'][2]=='file':boundary('unlink')
            elif item['relative']=='.':boundary('remove_root')
            else:boundary('after_rmdir')
        pending=False
    _,records,index,pending=verify(root,context,manifest,secret)
    if pending or index!=len(objects):raise EvidenceError('incomplete_object_deletion')
    hashes=[root.read(n,recheck=True).byte_sha256 for n in names(root)]
    return {'schema_version':1,'objects':len(objects),'entries':len(hashes),'entry_hashes':hashes,
        'journal_sha256':digest(hashes),'absence_recoveries':sum(r['outcome']=='ABSENCE_OBSERVED_AFTER_INTENT' for r in records)}


def validate_receipt(value):
    if not isinstance(value,dict) or set(value)!={'schema_version','objects','entries','entry_hashes','journal_sha256','absence_recoveries'}:
        raise EvidenceError('invalid_deletion_progress_receipt')
    hashes=value['entry_hashes']
    if (type(value['schema_version']) is not int or value['schema_version']!=1 or not isinstance(hashes,list)
            or any(not isinstance(h,str) or re.fullmatch('[a-f0-9]{64}',h) is None for h in hashes)
            or any(type(value[k]) is not int for k in ('objects','entries','absence_recoveries'))
            or not 0<value['entries']<=MAX_ENTRIES or value['entries']!=len(hashes) or value['entries']!=value['objects']*2
            or not 0<=value['absence_recoveries']<=value['objects'] or value['journal_sha256']!=digest(hashes)):
        raise EvidenceError('contradictory_deletion_progress_receipt')


def cleanup(root,receipt,boundary=lambda _:None):
    validate_receipt(receipt)
    found=names(root)
    for name in found:
        i=int(name[len(PREFIX):-5])
        if i>=receipt['entries'] or root.read(name).byte_sha256!=receipt['entry_hashes'][i]:
            raise EvidenceError('deletion_cleanup_record_changed')
    for name in found:
        os.unlink(name,dir_fd=root.fd);os.fsync(root.fd);boundary('progress_cleanup')
