"""Authored synthetic C5 values and source-shaped offline collections."""
from src.financial_models import FinancialObservation, FPDS_ACTION, USA_ACTION, field_semantics, signed_date
from src.financial_values import RawKind, monetary_value
from src.identity_matching import match_records
from tests.matching_fixtures import record, scenario, usa_row


def observation(identity, raw="100.00", *, field=None, kind=None, date="2025-01-01", currency=None):
    source = identity.source
    field = field or (USA_ACTION if source == "usaspending" else FPDS_ACTION)
    kind = kind or (RawKind.JSON_NUMBER if source == "usaspending" else RawKind.XML_TEXT)
    return FinancialObservation(record_id=identity.record_id, source=source, original_field=field,
             value=monetary_value(kind, raw), semantics=field_semantics(source, field), evidence=identity.evidence[0],
             action_date_raw=date, action_date=signed_date(date), declared_currency_raw=currency)


def pair(left="100.00", right="100.00", *, left_kw=None, right_kw=None):
    a, b = record(), record("fpds")
    identity = match_records((a, b), input_manifest_sha256="0" * 64)
    return identity, (observation(a, left, **(left_kw or {})), observation(b, right, **(right_kw or {})))


def financial_scenario(left_token="100.00", right_text="100.00", *, signed="2025-01-01", effective="2024-09-30", more=False):
    # Insert a literal JSON number token, preserving its precision and exponent.
    from src.evidence_io import canonical
    data = scenario([usa_row(federal_action_obligation="EXACT_SYNTHETIC_TOKEN")], more=more)
    usa_payload = data["responses"][0].pop("json")
    data["responses"][0]["text"] = canonical(usa_payload).replace('"EXACT_SYNTHETIC_TOKEN"', left_token)
    from xml.sax.saxutils import escape
    date_xml = ("<f:signedDate>" + escape(signed) + "</f:signedDate>") if signed is not None else ""
    dollars = "<f:dollarValues><f:obligatedAmount>" + escape(right_text) + "</f:obligatedAmount></f:dollarValues>"
    dates = "<f:relevantContractDates>" + date_xml + "<f:effectiveDate>" + escape(effective) + "</f:effectiveDate></f:relevantContractDates>"
    data["responses"][1]["text"] = data["responses"][1]["text"].replace("</f:award>", dollars + dates + "</f:award>")
    return data
