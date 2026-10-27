"""No floats in financial conversion/arithmetic; original lexical values survive."""
from dataclasses import replace
from decimal import localcontext, ROUND_UP

import pytest

from src.evidence_io import EvidenceError
from src.financial_values import (NumericState as N, RawKind as K, exact_difference,
                                  exact_json, has_cent_precision, monetary_value)


@pytest.mark.parametrize("raw,normalized", [("0", "0"), ("-0.00", "0"), ("001.2300", "1.23"), ("-123.4500", "-123.45"), ("100.00", "100")])
def test_xml_exact_values_and_raw_precision(raw, normalized):
    value = monetary_value(K.XML_TEXT, raw)
    assert value.state is N.VALID and value.raw_text == raw and value.normalized == normalized


@pytest.mark.parametrize("raw,normalized", [("1e2", "100"), ("1.2300E+2", "123"), ("-2e-2", "-0.02"), ("9007199254740992.01", "9007199254740992.01")])
def test_json_numeric_lexemes(raw, normalized):
    value = monetary_value(K.JSON_NUMBER, raw)
    assert value.state is N.VALID and value.normalized == normalized and value.raw_text == raw


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity", "$1.00", "1,000.00", " 1.00", "1.00 ", "+1", "1_000", "1.", ".1", "--1", "", "0x10", "１２.００"])
def test_invalid_xml_money_never_becomes_numeric(raw):
    value = monetary_value(K.XML_TEXT, raw)
    assert value.state is N.INVALID and value.normalized is None and value.decimal_text is None


@pytest.mark.parametrize("raw", ["01", "+1", "1.", ".1", "NaN", "1_0"])
def test_json_number_format_strict(raw):
    assert monetary_value(K.JSON_NUMBER, raw).state is N.INVALID


@pytest.mark.parametrize("raw", ["1e9999", "1e-9999", "9" * 81, "1.0000000000000000001"])
def test_numeric_expansion_and_precision_bounds(raw):
    assert monetary_value(K.JSON_NUMBER, raw).state is N.UNSUPPORTED


def test_missing_not_zero_and_string_json_not_numeric():
    assert monetary_value(K.MISSING, None).state is N.MISSING
    assert monetary_value(K.JSON_STRING, "0").state is N.UNSUPPORTED
    assert monetary_value(K.UNSUPPORTED, "false").state is N.UNSUPPORTED


def test_exact_json_retains_number_tokens_not_floats():
    doc = exact_json(b'{"a":9007199254740992.01,"b":1.2300e+2,"c":-0.00,"d":"1.00"}')
    assert str(doc["a"]) == "9007199254740992.01" and str(doc["b"]) == "1.2300e+2"
    assert str(doc["c"]) == "-0.00"
    assert type(doc["a"]).__name__ == "NumberToken" and type(doc["d"]) is str


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'{"a":01}', b'\xff'])
def test_bad_json_rejected(raw):
    with pytest.raises(EvidenceError):
        exact_json(raw)


def test_arithmetic_independent_of_ambient_decimal_context():
    with localcontext() as ctx:
        ctx.prec, ctx.Emax, ctx.Emin, ctx.rounding, ctx.capitals = 2, 2, -2, ROUND_UP, 0
        assert exact_difference("9007199254740992.01", "9007199254740992") == "0.01"
        assert monetary_value(K.JSON_NUMBER, "1e3").decimal_text == "1000"
        assert exact_difference("0.01", "-0.02") == "0.03"


def test_no_rounding_or_tolerance_hides_subcent():
    assert has_cent_precision(monetary_value(K.XML_TEXT, "1.230000"))
    assert not has_cent_precision(monetary_value(K.XML_TEXT, "1.230001"))
    assert exact_difference("1.230001", "1.23") == "0.000001"


def test_forged_value_or_state_rejected():
    value = monetary_value(K.XML_TEXT, "1.00")
    for kw in ({"normalized": "2"}, {"decimal_text": "1"}, {"state": N.MISSING}, {"raw_text": None}):
        with pytest.raises(ValueError):
            replace(value, **kw)


@pytest.mark.parametrize("bad", [0.1, 1, True, None, "NaN", "1e99999"])
def test_public_arithmetic_helper_cannot_accept_float_or_unsupported_operand(bad):
    with pytest.raises(ValueError):
        exact_difference(bad, "0")


def test_value_constructor_rejects_binary_float_input():
    with pytest.raises(ValueError):
        monetary_value(K.JSON_NUMBER, 0.1)
