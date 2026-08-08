"""test_producer_answer_validation.py

Regression test for the "NOT COVERED DEDUCTIBLE - EARTHQUAKE COVERAGE is not a
valid monetary amount" client report (2026-08-07).

`_validate_producer_answer` (routes/audit_routes.py) is shared by
POST /api/audit/answer and POST /api/audit/resolve-issue. For any field whose
name looks money-ish (limit/value/premium/amount/deductible/...) it forced
every answer through `validate_monetary`, which strips non-digits and rejects
anything that doesn't parse as a number - including the exact non-numeric
answers services/pdf_service.py's declared-type guard (`_rejects_declared_type`,
see test_declared_type_guard.py::_LEGIT_BY_TYPE) already treats as legitimate
data for these same fields: "Not covered", "Waived", "Statutory", "See
schedule". A peril the document says isn't covered has no dollar deductible -
"Not covered" IS the correct answer, not garbage to reject.

Fix mirrors the declared-type guard's own philosophy: permissive by default,
reject only what's actually broken. A monetary-field answer with no digits at
all is accepted as a legitimate descriptive value; only a value that DOES
contain digits and still fails to parse (a genuinely malformed number) is
rejected.
"""

import pytest

from routes.audit_routes import _validate_producer_answer


@pytest.mark.parametrize("field,value", [
    ("property_deductible_earthquake", "NOT COVERED DEDUCTIBLE - EARTHQUAKE COVERAGE"),
    ("property_deductible_flood", "NOT COVERED DEDUCTIBLE - FLOOD COVERAGE"),
    ("property_deductible_wind", "Not covered"),
    ("gl_deductible", "Waived"),
    ("wc_el_each_accident", "Statutory"),
    ("auto_deductible_comp", "See schedule"),
])
def test_legitimate_non_numeric_deductible_answers_are_accepted(field, value):
    ok, err = _validate_producer_answer(field, value)
    assert ok, f"legitimate value wrongly rejected: {err!r}"


@pytest.mark.parametrize("field,value", [
    ("property_deductible_wind", "$1,000"),
    ("gl_deductible", "1000"),
    ("auto_deductible_comp", "$0"),
])
def test_real_dollar_amounts_still_accepted(field, value):
    ok, err = _validate_producer_answer(field, value)
    assert ok, f"real amount wrongly rejected: {err!r}"


@pytest.mark.parametrize("field,value", [
    ("property_deductible_wind", "$1,234.56.78"),   # two decimal points - a typo, not a value
    ("gl_deductible", "12.3.4"),
])
def test_malformed_numbers_are_still_rejected(field, value):
    """The fix must not swallow genuine garbage - it only exempts answers with
    NO digits at all (a real descriptive convention), never a botched number.
    validate_monetary strips everything but digits/periods before parsing, so a
    value needs a shape like two decimal points to still fail float() here."""
    ok, err = _validate_producer_answer(field, value)
    assert not ok, "malformed numeric-looking value should still be rejected"
