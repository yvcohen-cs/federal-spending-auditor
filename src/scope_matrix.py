"""Field availability/lineage matrix, never an automatic agency crosswalk."""


def identity_matrix():
    fields={
        'usaspending':{'piid':'supported CONT_TX component','agency':'supported CONT_TX identity agency',
            'parent':'CONT_TX parent PIID/agency components; sentinels unavailable','action':'modification_number + CONT_TX transaction component'},
        'fpds':{'piid':'awardID/awardContractID/PIID','agency':'awardID/awardContractID/agencyID',
            'parent':'awardID/referencedIDVID/PIID + agencyID','action':'awardContractID/modNumber + transactionNumber'},
        'samgov':{'piid':'contractId.piid','agency':'contractId.subtier.code',
            'parent':'contractId.referencedIDVPiid + referencedIDVSubtier.code','action':'contractId.modificationNumber + transactionNumber'}}
    return {'version':'identity-matrix-v1','fields':fields,'pairs':[
        {'sources':['usaspending','fpds'],'automatic_matching':'existing_C4_rules_only_after_scope_eligibility'},
        {'sources':['usaspending','samgov'],'automatic_matching':'unsupported_pending_validated_cross_source_adapter'},
        {'sources':['fpds','samgov'],'automatic_matching':'documented_field_correspondence_not_implemented_identity_equivalence'}],
        'lineage':'shared_or_not_established_independent_procurement_lineage',
        'independent_corroboration':False,'unsupported_equivalences':['funding_agency_to_identity_agency','department_to_subtier',
            'display_name_to_native_code','missing_parent_to_no_parent','SAM_financial_fields_to_C5_registry']}
