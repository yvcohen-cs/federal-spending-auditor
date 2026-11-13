"""Read-only SAM native prior-ID analysis. No admitted real correction rule.

An explicit oldContractId field is a source assertion about identifier context;
it is not an immutable predecessor, verified alias, or effective-date rule.
Only records revalidated by the existing SAM capture reader reach this audit.
"""
from collections import defaultdict
from .evidence_io import EvidenceError,canonical,digest,strict_json
from .sam_validation_models import SAMObservedRecord,fields_for,native_identity,lookup,Presence
from .scope_models import ScopeStatus

COMPONENTS=('piid','agency','parent_piid','parent_agency','modification','transaction')


def _context(entry):
    identity=native_identity(fields_for({'contractId':entry}))
    return {k:getattr(identity,k).to_dict() for k in COMPONENTS}


def assess(records,*,profile):
    if profile not in ('live','synthetic') or type(records) not in (tuple,list) or len(records)>100:
        raise EvidenceError('bounded_typed_SAM_primary_records_required')
    if any(not isinstance(r,SAMObservedRecord) for r in records):
        raise EvidenceError('replayed_SAM_record_models_required')
    results=[];groups=defaultdict(list);labels=defaultdict(list)
    for record in records:
        # Revalidate computed assertions, not a serialized conclusion from a caller.
        record.validate()
        synthetic='synthetic_fixture_only' in record.citation.evidence.artifact.limitations
        if synthetic!=(profile=='synthetic'):
            raise EvidenceError('SAM_revision_profile_conflict')
        row=strict_json(record.original_record_json.encode())
        current={k:getattr(record.identity,k).to_dict() for k in COMPONENTS}
        current_values=tuple(current[k]['value'] for k in COMPONENTS)
        supported=record.supported_schema and record.scope is ScopeStatus.IN_SCOPE and all(v is not None for v in current_values)
        old_state='OMITTED' if 'oldContractId' not in row else 'NULL' if row['oldContractId'] is None else 'OBSERVED_ARRAY' if type(row['oldContractId']) is list else 'UNSUPPORTED_SHAPE'
        previous=[]
        if old_state=='OBSERVED_ARRAY':
            if len(row['oldContractId'])>20:raise EvidenceError('bounded_old_contract_identifiers_required')
            for index,entry in enumerate(row['oldContractId']):
                if type(entry) is not dict:
                    previous.append({'array_index':index,'status':'UNSUPPORTED_ENTRY','original_json':canonical(entry)});continue
                context=_context(entry)
                values=tuple(context[k]['value'] for k in COMPONENTS)
                complete=all(v is not None for v in values)
                status=('INSUFFICIENT_NATIVE_COMPONENTS' if not complete else
                    'SAME_NATIVE_CONTEXT_NOT_REVISION' if values==current_values else 'DISTINCT_NATIVE_IDENTIFIER_CONTEXT_CANDIDATE')
                previous.append({'array_index':index,'status':status,'original_json':canonical(entry),'native_context':context,
                    'source_field':'oldContractId/'+str(index),'correction_direction_established':False,'verified_identity_alias':False})
        complete_prior={canonical(p['native_context']) for p in previous if 'native_context' in p and p['status']!='INSUFFICIENT_NATIVE_COMPONENTS'}
        parent_mod=next(f for f in record.fields if f.path=='contractId.referencedIDVModificationNumber')
        dates=[f.to_dict() for f in record.fields if f.meaning in ('signed','performance_start','created','approved','last_modified','closed','document_version','native_status')]
        result={'schema_type':'SAMRevisionAuthorityObservation','schema_version':1,'claim_id':record.claim_id,
            'source_namespace':'samgov-v1','evidence_class':'REAL_SOURCE_OBSERVATION' if profile=='live' else 'SYNTHETIC_FIXTURE',
            'citation':record.citation.to_dict(),'current_native_context':current,
            'selected_record_scope_status':record.scope.value,'native_identity_supported':supported,
            'referenced_parent_modification':parent_mod.to_dict(),
            'parent_modification_reference_observed':supported and parent_mod.presence is Presence.VALUE,
            'old_contract_id_presence':old_state,'old_identifier_observations':previous,
            'multiple_prior_contexts_require_disambiguation':len(complete_prior)>1,
            'date_status_and_version_observations':dates,
            'historical_applicability_established':False,'verified_identifier_aliases':[], 'directed_correction_edges':[],
            'financial_comparison_authorized':False,
            'blockers':['prior_identifier_context_is_not_a_retained_predecessor_certificate',
                'referenced_parent_label_requires_authoritative_applicability_rule_and_parent_primary',
                'created_modified_document_version_and_final_status_are_not_publication_or_precedence',
                'deleted_only_six_month_visibility_is_not_full_history']}
        results.append(result)
        if supported:
            groups[current_values].append(record);labels[current_values[:5]].append(record)
    competing=[]
    for key,items in sorted(groups.items()):
        if len(items)>1:
            competing.append({'native_components':dict(zip(COMPONENTS,key)),
                'claim_ids':sorted(r.claim_id for r in items),'observed_content_digests':sorted({r.content_sha256 for r in items}),
                'status':'CONFLICTING_OR_VARIANT_SOURCE_CONTENT' if len({r.content_sha256 for r in items})>1 else 'REPEATED_SOURCE_OBSERVATION',
                'independent_corroboration':False,'selected_winner':None,'correction_direction_established':False})
    return {'schema_type':'SAMRevisionAuthorityAssessment','schema_version':1,'profile':profile,
        'observations':results,'repeated_or_competing_observations':competing,'observed_record_occurrences':len(records),
        'reused_modification_label_contexts':[{'native_award_and_modification':list(key),'native_transaction_values':sorted({r.action.transaction for r in items}),
            'modification_is_unique_action_identifier':False,'correction_direction_established':False} for key,items in sorted(labels.items()) if len({r.action.transaction for r in items})>1],
        'authoritative_correction_edges':[],'historical_parent_applicability_intervals':[],
        'verified_cross_source_mappings':[],'financial_comparison_authorized':False,'readiness_changed':False}


def replay(path):
    from .sam_validation_capture import replay as read_capture
    selection,pages,run,inventory,issues=read_capture(path)
    records=[record for _,_,page in pages for record in page.records]
    value=assess(records,profile=selection.profile)
    return {**value,'capture_inventory_sha256':inventory,'selection':selection.to_dict(),'capture_result':run,'request_attempts':run['attempts_reserved'],
        'capture_issues':list(issues),'query_coverage':'UNKNOWN' if issues else 'FINITE_OBSERVED_QUERY_NOT_HISTORY',
        'transaction_history_complete':'unknown','source_wide_complete':'unknown','replay_makes_new_requests':False}


def compare_reference(value,expected,preserved_references):
    """Compare literal field observations under an explicit selection only.

    This does not verify a SAM/FPDS namespace crosswalk or effective applicability.
    """
    from copy import deepcopy
    if (type(expected) is not dict or set(expected)!=set(COMPONENTS)
        or any(type(v) is not str or not v for v in expected.values())
        or type(preserved_references) not in (list,tuple) or len(preserved_references)>16
        or any(type(v) is not str or not v for v in preserved_references)):
        raise EvidenceError('exact_literal_selected_context_and_references_required')
    if (value.get('schema_type')!='SAMRevisionAuthorityAssessment' or value.get('schema_version')!=1
        or value.get('financial_comparison_authorized') is not False or value.get('authoritative_correction_edges')!=[]
        or value.get('historical_parent_applicability_intervals')!=[] or value.get('verified_cross_source_mappings')!=[]):
        raise EvidenceError('unsupported_serialized_authority_assertion')
    result=deepcopy(value)
    for observation in result['observations']:
        if {k:c['value'] for k,c in observation['current_native_context'].items()}!=expected:
            raise EvidenceError('SAM_capture_not_exact_selected_native_action')
        field=observation['referenced_parent_modification'];raw=strict_json(field['original_json'].encode())
        observation['preserved_FPDS_reference_comparison']=('UNKNOWN_REFERENCE' if not observation['native_identity_supported'] or not preserved_references or field['presence']!='value' else
            'CONSISTENT_LITERAL_REFERENCE_NOT_APPLICABILITY' if raw in preserved_references else 'CONFLICTING_SOURCE_REFERENCE_NOT_CORRECTION')
    return result
