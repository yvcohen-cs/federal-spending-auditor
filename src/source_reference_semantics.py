"""C20 reviewed native-reference instructions, never temporal certification."""
import re
from copy import deepcopy
from pathlib import Path

from .evidence import _timestamp
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json
from .historical_source_authority import VisibleText, assess

DOCUMENTS = {
    'fpds-glossary': ('fpds', 'https://www.fpds.gov/help/Glossary.htm',
        'b0953aee540665d60686547763dccfc2bfa53247cb709de6ae13494199060e3f',
        'Report the Modification number of the IDV against which the order is placed.'),
    'fpds-order-help': ('fpds', 'https://www.fpds.gov/help/Create_a_DO_TO_IDV.htm',
        '0ee80f11f56d11cafb935c2a42d81c5f1e9ef356b45408bfc7b993a3edd05506',
        'Enter the Contract Number of the IDV against which the order is placed.'),
    'sam-guide': ('samgov', 'https://open.gsa.gov/api/contract-awards/',
        '033a7007b702d25f1582f06feb8c0dd5d6dce3afee056cb57b61995e0e7443c7',
        'contractId.referencedIDVModificationNumber'),
    'usa-transactions': ('usaspending', 'https://raw.githubusercontent.com/fedspendingtransparency/usaspending-api/c2b82690eb044e130afc80b546343a2af0b4af1a/usaspending_api/api_contracts/contracts/v2/transactions.md',
        '76a50f3445670d8ee5488770d6583a7f6399a093a903dabfbab77344f1eba078', 'hasNext'),
}


def visible_projection(raw, content_type):
    """Decode only a supported declared encoding; retain original entity bytes.

    Header/meta conflicts and undeclared non-ASCII encodings fail closed. The
    result is an inspection projection, not a wire capture or publisher version.
    """
    if type(content_type) is not str:
        raise EvidenceError('document_content_type_unknown')
    header = re.findall(r'charset\s*=\s*["\']?([a-zA-Z0-9_-]+)', content_type.lower())
    meta = re.findall(br'charset\s*=\s*["\']?([a-zA-Z0-9_-]+)', raw[:8192].lower())
    declared = header + [v.decode('ascii') for v in meta]
    aliases = {'utf-8': 'utf-8', 'utf8': 'utf-8', 'windows-1252': 'cp1252', 'cp1252': 'cp1252'}
    if any(v not in aliases for v in declared) or len({aliases[v] for v in declared}) > 1:
        raise EvidenceError('unsupported_or_conflicting_document_encoding')
    encoding = aliases[declared[0]] if declared else 'ascii'
    text = raw.decode(encoding, errors='strict')
    parser = VisibleText(); parser.feed(text)
    return ' '.join(parser.values), encoding, 'HTTP_or_HTML_declaration' if declared else 'ASCII_bytes_only'


def read_documents(path):
    result = []
    with EvidenceRoot(path, max_bytes=1048576, max_total_bytes=8*1048576) as root:
        for name, (source, url, reviewed, quote) in DOCUMENTS.items():
            metadata = root.read(name+'.json')
            meta = strict_json(metadata.data)
            expected = {'schema_version','request','status','retrieved_at_utc','body_complete',
                        'body_sha256','representation','location','content_type'}
            if (type(meta) is not dict or set(meta) != expected or type(meta['schema_version']) is not int
                    or meta['schema_version'] != 1 or type(meta['status']) is not int
                    or type(meta['body_complete']) is not bool
                    or meta['request'] != {'method':'GET','url':url,'redirects':False}
                    or meta['representation'] != 'HTTP_entity_bytes_after_content_decoding'
                    or type(meta['retrieved_at_utc']) is not str):
                raise EvidenceError('C20_document_capture_contract_conflict')
            _timestamp(meta['retrieved_at_utc'])
            body = root.read(name+'.body')
            if meta['body_sha256'] != body.byte_sha256:
                raise EvidenceError('C20_document_entity_digest_conflict')
            available = meta['status'] == 200 and meta['body_complete'] and meta['location'] is None
            text, encoding, basis = visible_projection(body.data, meta['content_type']) if available else ('',None,None)
            known = available and body.byte_sha256 == reviewed
            start = text.find(quote) if known else -1
            state = ('UNAVAILABLE_OR_INCOMPLETE' if not available else 'UNREVIEWED_DOCUMENT_VERSION'
                     if not known else 'REVIEWED_CLAUSE_OBSERVED' if start >= 0 else 'REVIEWED_CLAUSE_MISSING')
            result.append({'source':source,'document_name':name,'state':state,'metadata':meta,
                'body_file':name+'.body','metadata_file':name+'.json','metadata_sha256':metadata.byte_sha256,
                'visible_projection_sha256':digest(text) if available else None,'projection_encoding':encoding,
                'encoding_basis':basis,'clause':quote if start >= 0 else None,
                'visible_text_character_span':[start,start+len(quote)] if start >= 0 else None,
                'publisher_document_version':None,'historical_document_applicability':'unknown',
                'historical_effective_rule_established':False,'source_wide_completeness_established':False})
            root.read(name+'.body', recheck=True);root.read(name+'.json', recheck=True)
    return result


def reference_assessment(previous, documents, *, profile):
    """Revalidate the primary citations already independently replayed by C19."""
    if (type(previous) is not dict or previous.get('schema_type') != 'HistoricalSourceAuthorityAssessment'
            or type(previous.get('schema_version')) is not int or previous.get('schema_version') != 1 or previous.get('profile') != profile
            or previous.get('verified_historical_relationships') != []
            or previous.get('authoritative_correction_edges') != []
            or previous.get('financial_comparison_authorized') is not False):
        raise EvidenceError('C20_replayed_C19_authority_assessment_required')
    previous=deepcopy(previous)
    documents=deepcopy(documents)
    native = {'schema_type':'HistoricalParentModificationAssessment','schema_version':1,
        'selected_native_action':previous['selected_native_action'],
        'original_child_evidence':previous['primary_child_citations'],
        'parent_modification_candidates':previous['primary_parent_citations'],
        'conflicting_child_assertions_or_variants':previous['conflicting_observations_preserved'],
        'reused_parent_modification_label':previous['reused_parent_modification_label'],
        'historical_parent_applicability_intervals':[],'authoritative_correction_relationships':[],
        'financial_comparison_authorized':False}
    recomputed = assess(native, profile=profile)
    if canonical(recomputed) != canonical(previous):
        raise EvidenceError('C20_authority_assertion_not_recomputed_from_primary_citations')
    if (type(documents) is not list or len(documents) != 4
            or {d['document_name'] for d in documents} != set(DOCUMENTS)):
        raise EvidenceError('C20_exact_document_contract_set_required')
    glossary = next(d for d in documents if d['document_name']=='fpds-glossary')
    refs = [c for c in previous['primary_child_citations'] if c['source']=='fpds'
            and c['referenced_parent_modification'] is not None]
    supported = (glossary['state']=='REVIEWED_CLAUSE_OBSERVED' and bool(refs)
        and glossary['metadata']['body_sha256']==DOCUMENTS['fpds-glossary'][2]
        and glossary['clause']==DOCUMENTS['fpds-glossary'][3])
    return {'schema_type':'SourceBoundReferenceAssessment','schema_version':1,
        'selected_native_action':previous['selected_native_action'],'preserved_five_level_assessment':recomputed,
        'source_native_reference_interpretation': 'DOCUMENTED_INSTRUCTION_AND_SELECTED_REFERENCE_OBSERVED'
            if supported else 'INSUFFICIENT_DOCUMENT_OR_PRIMARY_REFERENCE',
        'interpretation_scope':'FPDS_reports_the_IDV_modification_against_which_the_order_is_placed',
        'supporting_primary_references':refs if supported else [],
        'supporting_document_citation':glossary if supported else None,
        'historical_applicability_rule_established':False,'historical_applicability_independently_verified':False,
        'verified_historical_relationships':[],'authoritative_correction_edges':[],
        'remaining_authority_obligations':['document_version_applicability_to_the_historical_record_schema',
            'source_native_parent_action_namespace_crosswalk','retained_child_and_parent_revision_binding',
            'historical_publication_and_deletion_coverage','independent_application_of_an_admitted_effective_rule'],
        'financial_comparison_authorized':False,'production_readiness_changed':False}
