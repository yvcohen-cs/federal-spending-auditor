"""Opt-in read-only keyboard evidence navigation; no AT conformance claim."""
from .coordinator_accessibility import safe_text
from .evidence_io import canonical, EvidenceError
from .pilot_review import StopInput

SECTIONS=('summary','citations','observations','assessments','unknowns','limitations')
KEYS={'s':'summary','c':'citations','o':'observations','a':'assessments','u':'unknowns','l':'limitations'}


def sections(task,source_root=None):
    result={'summary':['Claim: '+task.claim,'Rules: '+', '.join(task.rule_versions),
        'Evidence quality only. Acceptance cannot authorize financial arithmetic or production screening.',
        'Observation = saved source field; assessment = interpretation. Missing proof remains unknown.'],
        'citations':[],'observations':[],'assessments':[],'unknowns':list(task.missing_proof_obligations) or ['No additional obligation identified; this is not a global completeness claim.'],
        'limitations':list(task.limitations)}
    if source_root is not None:result['summary'].append('Read-only source root: '+canonical(str(source_root)))
    for i,c in enumerate(task.citations,1):
        e=c.evidence
        result['citations'].extend([f'Citation {i}: '+c.citation_id,
            'Role: '+('packet claim evidence' if c.citation_id in task.packet_citation_ids else 'returned context/counterevidence; identity not assumed'),
            'Source: '+e.reference.source,'Preserved path: '+canonical(e.artifact.relative_path),
            'SHA256: '+e.artifact.sha256,'Locator: '+canonical(e.reference.locator),
            'Representation: '+e.artifact.representation.value,'Retrieved UTC: '+canonical(e.artifact.retrieved_at_utc),'Source URL: '+canonical(e.reference.source_record_url or e.artifact.endpoint)])
    for field in task.observed_fields:
        result['observations'].extend(['Citation: '+field.citation_id,'Field: '+field.path,
            'Basis: '+field.basis,'Exact saved JSON value: '+field.original_json])
    for d in task.dimensions:result['assessments'].extend([d.name+': '+d.status.value,d.rationale])
    return {name:tuple(safe_text(line) for line in lines) for name,lines in result.items()}


def browse(task,position,total,*,input_fn=input,output=print,source_root=None,page_size=12):
    if type(page_size) is not int or not 4<=page_size<=40:raise EvidenceError('bounded_evidence_page_size_required')
    content=sections(task,source_root);section='summary';page=0
    emit=lambda text:output(safe_text(text))
    while True:
        lines=content[section];pages=max(1,(len(lines)+page_size-1)//page_size)
        emit(f'Evidence browser — task {position+1} of {total} — {section} — page {page+1} of {pages}')
        for line in lines[page*page_size:(page+1)*page_size]:emit(line)
        emit('s summary; c citations; o observations; a assessments; u unknowns; l limitations; n next; p previous; b begin response; ? help; q save/stop; w withdraw.')
        raw=input_fn('Evidence command: ').strip()
        if raw in ('q','w'):raise StopInput(raw=='w')
        if raw=='b':return
        if raw in KEYS:section=KEYS[raw];page=0
        elif raw=='n':page=min(page+1,pages-1)
        elif raw=='p':page=max(0,page-1)
        elif raw=='?':
            emit('Use keyboard commands and Enter. Navigation reads preserved evidence only; it does not select a decision, fill unknowns, fetch URLs or edit sources.')
            emit('Timing is optional. Declining timing permits untimed review. Save resumes the same task; withdrawal excludes prior responses.')
        else:emit('Unknown command. No input text retained. Use ? for help.')
