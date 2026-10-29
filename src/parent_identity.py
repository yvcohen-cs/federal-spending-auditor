"""Experimental native parent semantics. No collector or downstream eligibility hook.

A serialized assertion is not a trust anchor: use assess_parent_collection to
revalidate immutable source bytes. Original XML here is a derived representation.
"""
from dataclasses import dataclass
from enum import Enum
import xml.etree.ElementTree as ET

from .collection_sources import ATOM, FPDS_NAMESPACES
from .evidence import Schema
from .evidence_io import canonical, digest, safe_xml, strict_json
from .review_packet_models import EvidenceCitation
from .scope_models import ScopeAssessment, ScopeStatus

RULE = 'parent-scope-v1'
PARENT_RULE = 'native-parent-v1'
SOURCES = (
    ('fpds-dictionary-1.4.4', 'https://www.fpds.gov/downloads/Version_1.4.4_specs/FPDSNG_DataDictionary_V1.4.4.pdf', 'Elements 1G/1H and 12B; indexed official legacy dictionary; XML 1.0 and later; current URL redirects to SAM'),
    ('fpds-dictionary-1.5', 'https://www.fpds.gov/downloads/Version_1.5_specs/FPDS_DataDictionary_V1.5.pdf', 'Elements 1G/1H: parent applicability differs by instrument; indexed official legacy document; no live API guarantee'),
    ('fpds-definitive-form', 'https://www.fpds.gov/help/Create_a_Stand_Alone_Contract.htm', 'Definitive Contract only: Referenced IDV ID not applicable; no general missing-field rule'),
    ('fpds-xsd-1.5', 'https://www.fpds.gov/downloads/FPDS-Specifications-Version15-Changes.pdf', 'Version 1.4 to 1.5: contractData/contractActionType with description; indexed official specification'),
    ('fpds-xsd-1.4', 'https://www.fpds.gov/downloads/FPDS-Specifications-Version14-Changes.pdf', 'Version 1.4 contractData/contractActionType and description; indexed official specification'),
    ('fpds-atom', 'https://www.fpds.gov/wiki/index.php/Atom_Feed_Specifications', 'Historical award XML mapping; current URL redirects to SAM; not a current API guarantee'),
    ('fpds-query', 'https://www.fpds.gov/wiki/index.php/Atom_Feed_Usage', 'Historical PIID and CONTRACTING_AGENCY_ID filters; exact identity/parent enforcement unverified'),
    ('sam-v1', 'https://open.gsa.gov/api/contract-awards/', 'contractId.subtier versus contractingSubtier; referencedIDVPiid and referencedIDVSubtier; no authenticated validation'),
    ('usa-guide', 'https://www.usaspending.gov/federal-spending-guide', 'Parent award PIID is summary linkage; generated keys alone do not prove no parent'),
    ('far-4.1603', 'https://www.acquisition.gov/far/4.1603', 'Instrument and supplementary modification identifiers; no PIID-position inference implemented'),
)


class ParentStatus(str, Enum):
    VERIFIED = 'verified_parent_relationship'
    NONE = 'verified_no_parent'
    CONFLICT = 'parent_relationship_conflict'
    UNKNOWN = 'parent_relationship_unknown'
    UNSUPPORTED = 'unsupported_parent_semantics'


@dataclass(frozen=True, kw_only=True)
class NativeParentField(Schema):
    path: str
    presence: str
    raw_json: str

    def validate(self):
        if self.path not in ('award/@version', 'award/contractData/contractActionType',
                             'award/awardID/referencedIDVID', 'award/awardID/referencedIDVID/PIID',
                             'award/awardID/referencedIDVID/agencyID', 'id/parent_piid', 'id/parent_agency'):
            raise ValueError('unsupported native parent field')
        value = strict_json(self.raw_json.encode())
        if canonical(value) != self.raw_json or self.presence not in ('omitted', 'null', 'empty', 'value', 'malformed', 'unavailable'):
            raise ValueError('invalid presence representation')
        if (self.presence in ('omitted','null','unavailable') and value is not None
                or self.presence == 'empty' and value != ''
                or self.presence == 'value' and (not isinstance(value,str) or not value)):
            raise ValueError('contradictory presence')


def field(path, nodes):
    if not nodes:
        return NativeParentField(path=path, presence='omitted', raw_json='null')
    allowed = {'description'} if path.endswith('contractActionType') else {'name'} if path.endswith('agencyID') else set()
    if len(nodes) == 1 and nodes[0].attrib == {'{http://www.w3.org/2001/XMLSchema-instance}nil':'true'} and not nodes[0].text and not list(nodes[0]):
        return NativeParentField(path=path,presence='null',raw_json='null')
    if len(nodes) != 1 or list(nodes[0]) or set(nodes[0].attrib)-allowed:
        return NativeParentField(path=path, presence='malformed', raw_json=canonical([ET.tostring(n, encoding='unicode') for n in nodes]))
    raw = nodes[0].text
    return NativeParentField(path=path, presence='empty' if raw is None or raw == '' else 'value', raw_json=canonical(raw or ''))


def native_fields(baseline):
    """Only pinned expanded paths; no names, suffix matching, or IDV substitution."""
    if baseline.evidence.reference.source != 'fpds':
        return tuple(NativeParentField(path='id/'+k, presence='unavailable' if strict_json(getattr(baseline.observed,k).original_json.encode()) is None else 'empty' if strict_json(getattr(baseline.observed,k).original_json.encode()) == '' else 'malformed' if not isinstance(strict_json(getattr(baseline.observed,k).original_json.encode()),str) else 'value',
                                      raw_json=getattr(baseline.observed,k).original_json) for k in ('parent_piid','parent_agency'))
    context = strict_json(baseline.original_identity_json.encode())
    if set(context) != {'derived_entry_xml'}:
        return ()
    # Wrapping preserves entry.tail whitespace, which is part of C4's exact
    # structural content fingerprint. Parsing as a document would discard it.
    _, wrapper = safe_xml(('<wrapper>'+context['derived_entry_xml']+'</wrapper>').encode())
    if len(wrapper) != 1:
        return ()
    entry = wrapper[0]
    if entry.tag != ATOM+'entry':
        return ()
    if baseline.supported:
        from .matching_ingestion import _check_fpds_contexts
        feed = ET.Element(ATOM+'feed'); feed.append(entry)
        if _check_fpds_contexts(ET.tostring(feed,encoding='utf-8')) != [baseline.content_sha256]:
            raise ValueError('derived XML does not match preserved record content')
    contents = entry.findall(ATOM+'content')
    awards = [n for c in contents for n in c if n.tag in tuple('{'+ns+'}award' for ns in FPDS_NAMESPACES)]
    if len(contents) != 1 or len(awards) != 1:
        return ()
    award = awards[0]; ns = award.tag.split('}')[0]+'}'
    guarded = {'contractData','contractActionType','awardID','referencedIDVID','PIID','agencyID'}
    if any(n.tag.rsplit('}',1)[-1] in guarded and not n.tag.startswith(ns) for n in award.iter()):
        return ()
    if len(award.findall(ns+'contractData')) > 1:
        return ()
    primary_parents = award.findall(ns+'awardID/'+ns+'referencedIDVID')
    if any(n not in primary_parents for n in award.iter(ns+'referencedIDVID')):
        return ()
    result = [NativeParentField(path='award/@version', presence='value' if 'version' in award.attrib else 'omitted', raw_json=canonical(award.get('version')))]
    for path in ('contractData/contractActionType', 'awardID/referencedIDVID', 'awardID/referencedIDVID/PIID', 'awardID/referencedIDVID/agencyID'):
        nodes = award.findall('/'.join(ns+p for p in path.split('/')))
        if path == 'awardID/referencedIDVID' and len(nodes) == 1 and not nodes[0].attrib:
            # Container children are expected, preserve a derived XML value.
            result.append(NativeParentField(path='award/'+path, presence='value', raw_json=canonical(ET.tostring(nodes[0],encoding='unicode'))))
        else:
            result.append(field('award/'+path, nodes))
    return tuple(result)


def parent_conclusion(baseline, fields):
    if not baseline.supported:
        return ParentStatus.UNSUPPORTED, None, 'unsupported_source_schema'
    observed = baseline.observed
    if baseline.conflicting_versions or any(getattr(observed,k).state.value == 'conflicting' for k in ('parent_piid','parent_agency')):
        return ParentStatus.CONFLICT, None, 'contradictory_native_versions'
    p,a = observed.parent_piid.value, observed.parent_agency.value
    lookup = {f.path:f for f in fields}
    instrument = None
    if baseline.evidence.reference.source == 'fpds':
        version = lookup.get('award/@version')
        if version is None or strict_json(version.raw_json.encode()) not in ('1.4','1.5'):
            return ParentStatus.UNSUPPORTED, None, 'unvalidated_native_schema_version'
        f = lookup['award/contractData/contractActionType']
        instrument = strict_json(f.raw_json.encode()) if f.presence == 'value' else None
        if any(x.presence == 'malformed' for x in fields):
            return ParentStatus.UNSUPPORTED, None, 'malformed_or_repeated_parent_or_instrument_field'
        if instrument == 'D':
            if p is not None or a is not None:
                return ParentStatus.CONFLICT, instrument, 'definitive_instrument_conflicts_with_referenced_IDV'
            parent_fields = [lookup['award/awardID/referencedIDVID/'+k] for k in ('PIID','agencyID')]
            context = strict_json(baseline.original_identity_json.encode())
            _, wrapped = safe_xml(('<wrapper>'+context['derived_entry_xml']+'</wrapper>').encode())
            root_award = next(n for n in wrapped[0].iter() if n.tag in tuple('{'+ns+'}award' for ns in FPDS_NAMESPACES))
            ns = root_award.tag.split('}')[0]+'}'
            containers = root_award.findall(ns+'awardID/'+ns+'referencedIDVID')
            unexpected_context = any(c.tag not in (ns+'PIID',ns+'agencyID') for container in containers for c in container)
            if all(f.presence in ('omitted','empty') for f in parent_fields) and not unexpected_context:
                return ParentStatus.NONE, instrument, 'fpds_v1_4_or_1_5_award_D_dictionary_12B_and_definitive_form_IDV_not_applicable'
            return ParentStatus.UNKNOWN, instrument, 'parent_placeholder_or_null_semantics_unverified'
        if instrument not in ('A','C'):
            return ParentStatus.UNKNOWN, instrument, 'parent_applicability_not_validated_for_native_instrument'
    # A source-native pair establishes only this record's asserted relationship,
    # not independently the requested award's relationship or the parent's existence.
    if p is not None and a is not None:
        if p in ('-NONE-','-none-','NONE','N/A','NULL') or a in ('NONE','NULL'):
            return ParentStatus.UNKNOWN, instrument, 'placeholder_not_relationship_evidence'
        if baseline.requested.parent_piid is not None and (p,a) != (baseline.requested.parent_piid,baseline.requested.parent_agency):
            return ParentStatus.CONFLICT, instrument, 'requested_native_parent_pair_conflict'
        return ParentStatus.VERIFIED, instrument, 'supported_source_native_parent_pair_only'
    return ParentStatus.UNKNOWN, instrument, 'missing_parent_pair_never_establishes_absence'


def scope_conclusion(baseline, parent_status):
    if baseline.status in (ScopeStatus.OUT_OF_SCOPE, ScopeStatus.UNSUPPORTED):
        return baseline.status
    if parent_status is ParentStatus.CONFLICT:
        return ScopeStatus.AMBIGUOUS
    if baseline.conflicting_versions:
        return ScopeStatus.AMBIGUOUS
    if parent_status is ParentStatus.NONE and baseline.requested.parent_piid is not None:
        return ScopeStatus.OUT_OF_SCOPE
    if baseline.status is ScopeStatus.IN_SCOPE:
        return ScopeStatus.IN_SCOPE if parent_status is ParentStatus.VERIFIED else ScopeStatus.AMBIGUOUS
    if (baseline.status is ScopeStatus.AMBIGUOUS and parent_status is ParentStatus.NONE
            and all(f.result in ('exact','not_requested') for f in baseline.comparisons)):
        return ScopeStatus.IN_SCOPE
    return baseline.status


@dataclass(frozen=True, kw_only=True)
class ParentAssessment(Schema):
    baseline: ScopeAssessment
    citation: EvidenceCitation
    fields: tuple[NativeParentField,...]
    status: ParentStatus
    instrument_type: str|None
    rationale: str
    new_scope_status: ScopeStatus
    contradictory_versions: tuple[ScopeAssessment,...] = ()
    rule_version: str = PARENT_RULE
    scope_rule_version: str = RULE

    @property
    def assessment_id(self):
        return 'parent-assessment:v1:'+digest({'baseline':self.baseline.to_dict(), 'rule':self.rule_version, 'scope_rule':self.scope_rule_version})

    def validate(self):
        if self.rule_version != PARENT_RULE or self.scope_rule_version != RULE:
            raise ValueError('unsupported parent/scope rule')
        if self.citation != EvidenceCitation(evidence=self.baseline.evidence) or self.fields != native_fields(self.baseline):
            raise ValueError('native parent evidence/citation conflict')
        if any(not version_conflict(self.baseline,b) for b in self.contradictory_versions):
            raise ValueError('unrelated records cannot establish a version conflict')
        if tuple(sorted({b.assessment_id for b in self.contradictory_versions})) != tuple(b.assessment_id for b in self.contradictory_versions):
            raise ValueError('canonical unique conflicting occurrences required')
        expected = (ParentStatus.CONFLICT,None,'contradictory_native_action_contents') if self.contradictory_versions else parent_conclusion(self.baseline,self.fields)
        if (self.status,self.instrument_type,self.rationale) != expected or self.new_scope_status != scope_conclusion(self.baseline,self.status):
            raise ValueError('unsupported positive assertion or contradictory parent/scope result')


def version_conflict(a,b):
    # A child PIID/agency/action tuple without its parent is not a stable award
    # identity. Different parent-bound awards may legitimately reuse that tuple.
    if a.evidence.reference.source != b.evidence.reference.source or a.content_sha256 == b.content_sha256:
        return False
    native_a = {(n.namespace,n.value) for n in a.record.native_identifiers if n.namespace in ('id','atom_id')} if a.record else set()
    native_b = {(n.namespace,n.value) for n in b.record.native_identifiers if n.namespace in ('id','atom_id')} if b.record else set()
    names = ('piid','agency','parent_piid','parent_agency','modification','transaction')
    key = tuple(getattr(a.observed,n).value for n in names)
    full_key = all(v is not None for v in key) and key == tuple(getattr(b.observed,n).value for n in names)
    return bool(native_a & native_b) or full_key


def assess_parent(baseline, peers=()):
    fields = native_fields(baseline)
    contradictions = tuple(sorted((p for p in peers if version_conflict(baseline,p)),key=lambda a:a.assessment_id))
    status,instrument,rationale = (ParentStatus.CONFLICT,None,'contradictory_native_action_contents') if contradictions else parent_conclusion(baseline,fields)
    return ParentAssessment(baseline=baseline,citation=EvidenceCitation(evidence=baseline.evidence),fields=fields,
        status=status,instrument_type=instrument,rationale=rationale,new_scope_status=scope_conclusion(baseline,status),contradictory_versions=contradictions)
