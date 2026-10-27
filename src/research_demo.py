"""Authored fictional C7 demonstration; no downloaded data or network fallback."""
from __future__ import annotations

from xml.sax.saxutils import escape

from .collection import SelectedAward

CASES = ("agreement","financial_gap","ambiguous_parent","modifications","scope_mismatch","duplicates")


def demo_case(name):
    if name not in CASES:
        raise ValueError("unsupported synthetic scenario")
    piid = "SYNTH-C7-"+name.upper().replace("_","-")
    parent = "SYNTH-PARENT"
    selected = SelectedAward(generated_id=f"CONT_AWD_{piid}_0001_{parent}_0002",piid=piid,agency_id="0001",
                             parent_piid=None if name=="ambiguous_parent" else parent,
                             parent_agency_id=None if name=="ambiguous_parent" else "0002")
    mods = [("0",100),("P00001",-20),("P00002",0)] if name=="modifications" else [("P00001",100)]
    rows = []
    entries = []
    for mod,amount in mods:
        usa_parent,usa_parent_agency = ("-NONE-","-NONE-") if name=="ambiguous_parent" else (parent,"0002")
        rows.append({"id":f"CONT_TX_0001_{usa_parent_agency}_{piid}_{mod}_{usa_parent}_0",
            "modification_number":mod,"action_date":"2024-10-01","federal_action_obligation":amount,
            **({"fy_federal_action_obligation":900,"lifetime_obligations":2000} if name=="scope_mismatch" else {})})
        parents = (parent,"SYNTH-OTHER-PARENT") if name=="ambiguous_parent" else (parent,)
        for p in parents:
            actual = amount+1 if name=="financial_gap" else amount
            signed = "2024-09-30" if name=="scope_mismatch" else "2024-10-01"
            # An effective date on another FY boundary is intentionally distinct.
            entries.append('<entry><content><f:award><f:awardID><f:awardContractID>'
                +f'<f:agencyID>0001</f:agencyID><f:PIID>{escape(piid)}</f:PIID><f:modNumber>{mod}</f:modNumber><f:transactionNumber>0</f:transactionNumber>'
                +'</f:awardContractID><f:referencedIDVID>'
                +f'<f:agencyID>0002</f:agencyID><f:PIID>{p}</f:PIID><f:modNumber>0</f:modNumber>'
                +'</f:referencedIDVID></f:awardID><f:dollarValues>'
                +f'<f:obligatedAmount>{actual}.00</f:obligatedAmount></f:dollarValues>'
                +'<f:totalDollarValues><f:obligatedAmount>2000.00</f:obligatedAmount><f:totalBaseAndAllOptionsValue>10000.00</f:totalBaseAndAllOptionsValue></f:totalDollarValues>'
                +f'<f:relevantContractDates><f:signedDate>{signed}</f:signedDate><f:effectiveDate>2024-09-30</f:effectiveDate></f:relevantContractDates></f:award></content></entry>')
    usa = {"source":"usaspending","json":{"page_metadata":{"page":1,"hasNext":name=="duplicates"},"results":rows},"retrieved_at_utc":"2025-01-01T00:00:00Z"}
    responses = [usa]
    if name=="duplicates":
        # Identical whole response bytes at distinct observation times/statuses.
        responses.insert(0,{**usa,"status":503,"retry_after":"0","retrieved_at_utc":"2024-12-31T00:00:00Z"})
        responses.append({**usa,"json":{"page_metadata":{"page":2,"hasNext":False},"results":rows},"retrieved_at_utc":"2025-01-02T00:00:00Z"})
    responses.append({"source":"fpds","text":'<feed xmlns="http://www.w3.org/2005/Atom" xmlns:f="https://www.fpds.gov/FPDS">'+"".join(entries)+"</feed>","retrieved_at_utc":"2025-01-03T00:00:00Z"})
    return selected,{"schema_version":1,"responses":responses}
