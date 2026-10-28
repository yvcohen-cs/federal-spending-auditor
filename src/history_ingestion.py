"""Read-only reconstruction from revalidated C3 bytes and 4B2 scope assessments."""
from pathlib import Path
import re

from .collection_sources import ATOM, FPDS_NAMESPACES, parse_page
from .evidence import Completeness
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, safe_xml, strict_json
from .financial_ingestion import _fpds_fields, _usa_fields
from .financial_models import FinancialObservation, field_semantics, signed_date
from .financial_values import NumberToken, exact_json, monetary_value
from .history_models import (CONTROL, ContractHistoryScope, ContractActionObservation, ModificationIdentity,
    FinancialObservationContext, SourceRevisionEvidence, FreshnessAssessment, HistoryCoverageAssessment,
    HistoryVerificationRun, temporal)
from .history_rules import compare_observations
from .matching_models import ordered
from .scope_ingestion import assess_collection

CONTROL_NS='{urn:synthetic-history-control:v1}'


def _fields(source,row):
    """Known paths only; repeated/compound fields are explicit unsupported evidence."""
    fields=[];issues=[];control=None
    if source=='usaspending':
        value=row.get('action_date')
        if isinstance(value,NumberToken): value={'unsupported_json_number_token':str(value)}
        fields.append(temporal('action_date','signed',value))
        control=row.get('_history_control')
        if '_history_control' in row and control is None: issues.append('unsupported_synthetic_control')
    else:
        for name,meaning in (('updated','updated'),('published','published')):
            nodes=row.findall(ATOM+name)
            if len(nodes)>1 or any(len(n) or n.attrib for n in nodes): issues.append('compound_atom_'+name)
            elif nodes: fields.append(temporal('atom:'+name,meaning,nodes[0].text))
        awards=[a for c in row.findall(ATOM+'content') for a in c if a.tag in tuple('{'+ns+'}award' for ns in FPDS_NAMESPACES)]
        if len(awards)==1:
            a=awards[0];ns=a.tag.split('}')[0]+'}'
            for container,name,meaning in (('relevantContractDates','signedDate','signed'),('relevantContractDates','effectiveDate','effective'),
                ('transactionInformation','createdDate','created'),('transactionInformation','lastModifiedDate','updated'),('transactionInformation','approvedDate','approved')):
                parents=a.findall(ns+container)
                nodes=[n for parent in parents for n in parent.findall(ns+name)]
                if len(parents)>1 or len(nodes)>1 or any(len(n) or n.attrib for n in nodes): issues.append('compound_temporal_'+container+'/'+name)
                elif nodes: fields.append(temporal(container+'/'+name,meaning,nodes[0].text))
        else: issues.append('unsupported_temporal_award_container')
        controls=row.findall(CONTROL_NS+'revision')
        if len(controls)==1 and not len(controls[0]) and not controls[0].attrib:
            control={'profile':CONTROL,'revision':controls[0].text}
        elif controls: issues.append('unsupported_synthetic_control')
    if any(t.parsed is None and strict_json(t.original_json.encode()) is not None for t in fields):
        issues.append('malformed_or_unsupported_temporal_value')
    return ordered(fields),control,issues


def _one(path,requested):
    # Pin the entire inventory across independent C2/4B2 parsing and final reread.
    with EvidenceRoot(path) as root:
        names=root.discover();snapshots={n:root.read(n) for n in names}
        scope=assess_collection(path,requested)
        plan=strict_json(snapshots['c3_plan.json'].data)
        checkpoint=strict_json(snapshots['c3_checkpoint.json'].data)
        observations=[];parsed={}
        for a in scope.assessments:
            evidence=a.evidence;source=evidence.reference.source;name=evidence.artifact.relative_path
            if snapshots[name].byte_sha256!=evidence.artifact.sha256: raise EvidenceError('history_artifact_hash_conflict')
            meta=strict_json(snapshots[name[:-5]+'.json'].data)
            if name not in parsed: parsed[name]=exact_json(snapshots[name].data) if source=='usaspending' else safe_xml(snapshots[name].data)[1]
            locator=evidence.reference.locator
            match=re.fullmatch(r'/results/([0-9]+)' if source=='usaspending' else r'/feed/entry\[([0-9]+)\]',locator)
            if match is None: raise EvidenceError('unsupported_history_locator')
            index=int(match[1]);body=parsed[name]
            row=body['results'][index] if source=='usaspending' else body.findall(ATOM+'entry')[index-1]
            times,control,issues=_fields(source,row) if source=='fpds' or isinstance(row,dict) else ((),None,['unsupported_record'])
            if meta['source_update_raw'] is not None:
                times=ordered(times+(temporal('http:Last-Modified','http_last_modified',meta['source_update_raw']),))
            token=None
            if control is not None:
                if (plan['profile'].startswith('fixture:') and 'synthetic_fixture_only' in evidence.artifact.limitations
                        and isinstance(control,dict) and set(control)=={'profile','revision'} and control['profile']==CONTROL
                        and type(control['revision']) is str and control['revision'].strip() and len(control['revision'])<=128):
                    token=control['revision']
                else: issues.append('unsupported_or_live_synthetic_revision_control')
            money=[]
            supported_signed=all(type(strict_json(t.original_json.encode())) in (str,type(None)) for t in times if t.meaning=='signed')
            if a.record is not None and supported_signed:
                try:
                    raw_date,values=_usa_fields(row) if source=='usaspending' else _fpds_fields(row)
                    if len(values)>32: raise EvidenceError('history_financial_field_count_limit')
                    for field,kind,text,currency in values:
                        if len(field)>256 or text is not None and len(text)>4096 or raw_date is not None and len(raw_date)>4096 or currency is not None and len(currency)>256:
                            raise EvidenceError('history_financial_field_limit')
                        o=FinancialObservation(record_id=a.record.record_id,source=source,original_field=field,
                            value=monetary_value(kind,text),semantics=field_semantics(source,field),evidence=evidence,
                            action_date_raw=raw_date,action_date=signed_date(raw_date),declared_currency_raw=currency)
                        money.append(FinancialObservationContext(observation=o))
                except (ValueError,TypeError,KeyError):
                    money=[];issues.append('unsupported_or_compound_financial_fields')
            observations.append(ContractActionObservation(input_manifest_sha256=scope.input_manifest_sha256,scope_assessment=a,
                modification=ModificationIdentity(native=a.observed.modification.value,transaction=a.observed.transaction.value,
                    original_modification_json=a.observed.modification.original_json,original_transaction_json=a.observed.transaction.original_json),
                freshness=FreshnessAssessment(retrieved_at_utc=evidence.artifact.retrieved_at_utc,temporal_fields=times),
                revision=SourceRevisionEvidence(update_markers=ordered(t for t in times if t.meaning=='updated'),synthetic_control_revision=token),
                money=ordered(money),retrieval_sequence=meta['sequence'],source_page=meta['request']['page_index'],issues=tuple(sorted(set(issues)))))
        coverage=[]
        for source in plan['sources']:
            pages={};attempted=set();issues=list(scope.artifact_issues);bad=False
            for name,snapshot in sorted(snapshots.items()):
                if re.fullmatch(r'c3_attempt_[0-9]{6}\.json',name) is None: continue
                meta=strict_json(snapshot.data)
                if meta['request']['source']!=source: continue
                attempted.add(meta['request']['page_index'])
                body_name=name[:-5]+'.body'
                if meta['error_code'] or not meta['body_complete'] or meta['status'] is None or not 200<=meta['status']<300 or body_name not in snapshots:
                    # A later successful retry of the same page can resolve transport
                    # failure for pagination, but not erase the failed observation.
                    continue
                try:
                    page=parse_page(source,snapshots[body_name].data,meta['request'],plan['awards'][0])
                    pages[meta['request']['page_index']]=page['has_next']
                except (ValueError,KeyError,TypeError): bad=True
            terminal=bool(pages) and not pages[max(pages)] and sorted(pages)==list(range(1,max(pages)+1)) and attempted<=pages.keys()
            pending=checkpoint.get('pending')
            if pending and pending['request']['source']==source: terminal=False
            pagination=Completeness.COMPLETE if terminal and not bad else Completeness.PARTIAL if pages else Completeness.UNKNOWN
            coverage.append(HistoryCoverageAssessment(source=source,input_manifest_sha256=scope.input_manifest_sha256,pagination=pagination,
                observed_action_count=len({o.action_key for o in observations if o.scope_assessment.evidence.reference.source==source and o.action_key is not None}),issues=tuple(sorted(set(issues)))))
        for n,s in snapshots.items():
            after=root.read(n,recheck=True)
            if after.stamp!=s.stamp or after.byte_sha256!=s.byte_sha256: raise EvidenceError('history_evidence_changed')
        if root.discover()!=names: raise EvidenceError('history_inventory_changed')
    return scope,observations,coverage


def reconstruct(paths,requested,*,executed_at_utc=None):
    scope=ContractHistoryScope(requested=requested)
    paths=tuple(Path(p).absolute() for p in paths)
    if not 1<=len(paths)<=8 or len(set(paths))!=len(paths): raise EvidenceError('history_input_limit_or_duplicate_root')
    inputs=[];observations=[];coverage=[]
    # Pin all roots until all have been evaluated, not merely each root in turn.
    inventories=[]
    for p in paths:
        with EvidenceRoot(p) as root: inventories.append({n:root.read(n).byte_sha256 for n in root.discover()})
    for path in paths:
        s,o,c=_one(path,requested);inputs.append(s);observations.extend(o);coverage.extend(c)
        if len(observations)>1000: raise EvidenceError('history_observation_limit')
    run=HistoryVerificationRun(scope=scope,inputs=ordered(inputs),observations=ordered(observations),coverage=ordered(coverage),
        comparisons=compare_observations(observations),executed_at_utc=executed_at_utc)
    for p,inventory in zip(paths,inventories):
        with EvidenceRoot(p) as root:
            if {n:root.read(n).byte_sha256 for n in root.discover()}!=inventory: raise EvidenceError('history_evidence_changed')
    return run
