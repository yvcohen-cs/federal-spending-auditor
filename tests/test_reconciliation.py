from unittest.mock import Mock
import json

from src.reconciliation import FPDSClient, parse_fpds_feed, reconcile_awards


FPDS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:fpds="https://www.fpds.gov/FPDS">
  <link rel="next" href="https://www.fpds.gov/ezsearch/FEEDS/ATOM?start=10" />
  <entry>
    <title>Modified DELIVERY ORDER</title>
    <link rel="alternate" href="https://www.fpds.gov/ezsearch/search.do?q=PIID%3A00001" />
    <content><fpds:award>
      <fpds:awardID><fpds:awardContractID>
        <fpds:agencyID name="HOUSING AND URBAN DEVELOPMENT">8600</fpds:agencyID>
        <fpds:PIID>00001</fpds:PIID><fpds:modNumber>P00001</fpds:modNumber>
        <fpds:transactionNumber>2</fpds:transactionNumber>
      </fpds:awardContractID></fpds:awardID>
      <fpds:relevantContractDates><fpds:effectiveDate>2025-01-01</fpds:effectiveDate></fpds:relevantContractDates>
      <fpds:dollarValues><fpds:obligatedAmount>25.00</fpds:obligatedAmount></fpds:dollarValues>
      <fpds:totalDollarValues><fpds:totalObligatedAmount>125.00</fpds:totalObligatedAmount></fpds:totalDollarValues>
      <fpds:vendor><fpds:vendorName>Example Vendor</fpds:vendorName></fpds:vendor>
    </fpds:award></content>
  </entry>
</feed>"""


class FakeResponse:
    def __init__(self, text):
        self.text = text
        self.headers = {}

    def raise_for_status(self):
        return None


def test_parses_fpds_modification_and_obligation_fields():
    rows, next_url = parse_fpds_feed(FPDS_XML)

    assert next_url == "https://www.fpds.gov/ezsearch/FEEDS/ATOM?start=10"
    assert rows[0]["piid"] == "00001"
    assert rows[0]["contracting_agency_id"] == "8600"
    assert rows[0]["modification_number"] == "P00001"
    assert rows[0]["transaction_number"] == "2"
    assert rows[0]["obligated_amount"] == "25.00"
    assert rows[0]["total_obligated_amount"] == "125.00"
    assert rows[0]["source_record_url"].startswith("https://www.fpds.gov/")


def test_reconciliation_requires_exact_piid_and_agency_and_keeps_modifications():
    session = Mock()
    session.get.return_value = FakeResponse(
      FPDS_XML.replace(
        '<link rel="next" href="https://www.fpds.gov/ezsearch/FEEDS/ATOM?start=10" />',
        "",
      )
    )
    client = FPDSClient(session=session, retries=0, page_delay_seconds=0)
    awards = [
        {
            "internal_id": 1,
            "award_id": "00001",
            "generated_internal_id": "CONT_AWD_00001_8600",
            "awarding_sub_agency_code": "8600",
            "award_amount": 130,
            "source_record_url": "https://www.usaspending.gov/award/CONT_AWD_00001_8600",
        },
        {
            "internal_id": 2,
            "award_id": "00002",
            "generated_internal_id": "CONT_AWD_00002_8600",
            "awarding_sub_agency_code": "8600",
        },
    ]

    result = reconcile_awards(awards, client, sample_size=2)

    assert result[0]["fpds_status"] == "matched_identifiers"
    assert result[0]["fpds_record_count"] == 1
    assert result[0]["fpds_modifications"] == "P00001"
    assert result[0]["fpds_transaction_ids"] == "2"
    assert result[0]["amount_comparison_status"] == "values_available_definitions_may_differ"
    assert result[1]["fpds_status"] == "no_exact_identifier_match"
    assert "not evidence of misconduct" in result[1]["benign_explanations"]
    assert session.get.call_args_list[0].kwargs["params"]["q"] == (
        "PIID:00001 AND CONTRACTING_AGENCY_ID:8600"
    )


def test_fpds_request_saves_exact_query_metadata_and_raw_xml(tmp_path):
    session = Mock()
    session.get.return_value = FakeResponse(FPDS_XML)
    client = FPDSClient(session=session, retries=0, page_delay_seconds=0)

    client.search_award("00001", "8600", max_results=1, raw_path=tmp_path / "lookup.xml")

    metadata_path = tmp_path / "lookup_query.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["query"] == "PIID:00001 AND CONTRACTING_AGENCY_ID:8600"
    assert metadata["method"] == "GET"
    assert (tmp_path / "lookup_page_001.xml").is_file()


def test_malformed_fpds_xml_is_recorded_as_source_error():
    session = Mock()
    session.get.return_value = FakeResponse("<feed>")
    client = FPDSClient(session=session, retries=0, page_delay_seconds=0)
    award = {
        "award_id": "00001",
        "awarding_sub_agency_code": "8600",
    }

    result = reconcile_awards([award], client, sample_size=1)

    assert result[0]["fpds_status"] == "source_error"
    assert "no exact match" not in result[0]["fpds_status"]


def test_reconciliation_uses_unique_latest_modification_amount():
    second_entry = FPDS_XML.split("<entry>", 1)[1].split("</entry>", 1)[0]
    second_entry = second_entry.replace("P00001", "P00002")
    second_entry = second_entry.replace("2025-01-01", "2025-09-01")
    second_entry = second_entry.replace("125.00", "175.00")
    second_entry = second_entry.replace("</entry>", "")
    single_page = FPDS_XML.replace(
        '<link rel="next" href="https://www.fpds.gov/ezsearch/FEEDS/ATOM?start=10" />',
        "",
    ).replace("</feed>", f"<entry>{second_entry}</entry></feed>")
    session = Mock()
    session.get.return_value = FakeResponse(single_page)
    client = FPDSClient(session=session, retries=0, page_delay_seconds=0)
    award = {
        "award_id": "00001",
        "awarding_sub_agency_code": "8600",
        "award_amount": 200,
    }

    result = reconcile_awards([award], client, sample_size=1)[0]

    assert result["fpds_record_count"] == 2
    assert result["fpds_latest_action_date"] == "2025-09-01"
    assert result["fpds_total_obligated_amount"] == "175.00"
