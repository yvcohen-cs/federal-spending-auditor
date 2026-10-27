"""Lossless bounded numeric parsing for C5; no binary-float monetary arithmetic."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Context, Decimal, Inexact, InvalidOperation, Overflow, Rounded, localcontext
from enum import Enum

from .evidence import Schema
from .evidence_io import EvidenceError


class RawKind(str, Enum):
    JSON_NUMBER = "json_number"
    JSON_STRING = "json_string"
    XML_TEXT = "xml_text"
    MISSING = "missing"
    UNSUPPORTED = "unsupported"


class NumericState(str, Enum):
    VALID = "valid"
    MISSING = "missing"
    INVALID = "invalid"
    UNSUPPORTED = "unsupported"


class NumberToken(str):
    """Original JSON token text; deliberately not a float or a monetary ID."""


def exact_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise EvidenceError("duplicate_json_key")
            result[key] = value
        return result

    def forbidden(_):
        raise EvidenceError("nonfinite_financial_json")

    try:
        return json.loads(raw.decode("utf-8"), parse_int=NumberToken, parse_float=NumberToken,
                          parse_constant=forbidden, object_pairs_hook=unique)
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, EvidenceError):
            raise
        raise EvidenceError("malformed_financial_json") from None


def normalize(value):
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if value.is_zero() else text


def parse_money(kind, raw):
    if kind is RawKind.MISSING:
        return NumericState.MISSING, None, None
    if kind not in (RawKind.JSON_NUMBER, RawKind.XML_TEXT):
        return NumericState.UNSUPPORTED, None, None
    pattern = r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?" if kind is RawKind.JSON_NUMBER else r"-?[0-9]+(?:\.[0-9]+)?"
    if type(raw) is not str or len(raw) > 128 or re.fullmatch(pattern, raw, flags=re.ASCII) is None:
        return NumericState.INVALID, None, None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return NumericState.INVALID, None, None
    # Bound both expansion and arithmetic precision before formatting/exponents.
    if not value.is_finite() or len(value.as_tuple().digits) > 80 or not -18 <= value.as_tuple().exponent <= 60 or value.adjusted() > 60:
        return NumericState.UNSUPPORTED, None, None
    return NumericState.VALID, format(value, "f"), normalize(value)


@dataclass(frozen=True, kw_only=True)
class MonetaryValue(Schema):
    raw_kind: RawKind
    raw_text: str | None
    state: NumericState
    decimal_text: str | None = None
    normalized: str | None = None

    def validate(self):
        if self.raw_kind is RawKind.MISSING and self.raw_text is not None:
            raise ValueError("missing amount must retain null")
        if self.raw_kind is not RawKind.MISSING and self.raw_text is None:
            raise ValueError("original amount representation required")
        if (self.state, self.decimal_text, self.normalized) != parse_money(self.raw_kind, self.raw_text):
            raise ValueError("numeric state/value contradict original token")


def monetary_value(kind, raw):
    state, decimal_text, normalized = parse_money(kind, raw)
    return MonetaryValue(raw_kind=kind, raw_text=raw, state=state, decimal_text=decimal_text, normalized=normalized)


def exact_difference(left, right):
    # Independent of process precision, rounding, traps and Emax/Emin. No
    # quantization, cent rounding or percentage tolerance is performed.
    if any(type(v) is not str or parse_money(RawKind.XML_TEXT, v)[0] is not NumericState.VALID for v in (left, right)):
        raise ValueError("bounded decimal text operands required")
    context = Context(prec=256, Emin=-999, Emax=999,
                      traps=[InvalidOperation, Overflow, Inexact, Rounded])
    with localcontext(context):
        return normalize(Decimal(left) - Decimal(right))


def has_cent_precision(value):
    if value.state is not NumericState.VALID:
        return False
    # Check lexical fractional digits without multiplying/rounding in a context.
    normalized = value.normalized
    return "." not in normalized or len(normalized.split(".")[1]) <= 2
