"""test_answer_semantics.py - what a human's answer MEANS, on every field.

2026-08-24. The answer path used to store whatever was typed as the fact's
VALUE, so three different meanings collapsed into one. Measured before the fix:
typing "N/A" into every Tier-2 field scored a perfect 100, while a legitimate
"None" scored as a GAP. Both wrong, from one root cause - *"what is the
value?"* and *"did they answer?"* were the same test, `bool(value)`.

These tests drive the real module and the real validation gate. They are
deliberately parametrised over MANY phrasings per idea: the point of the design
is that a person can answer however they like, so a test that only proves the
curated wording works would prove nothing.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import pytest

from services.answer_semantics import (
    ABSENCE, NOT_APPLICABLE, UNKNOWN, VALUE,
    build_fact_envelope, fact_answered, interpret_answer, is_absence_affirmative,
    words_to_number,
)


def _i(field, answer):
    return interpret_answer(field, answer)


# ── The three meanings that used to collapse into one ────────────────────────

def test_the_three_meanings_are_distinguished():
    """The whole design in one test."""
    value = _i("prior_carrier", "Travelers")
    absent = _i("prior_carrier", "None")
    unknown = _i("prior_carrier", "TBD")

    assert (value.intent, value.value, value.answered) == (VALUE, "Travelers", True)
    # An absence IS an answer, but carries NO value - so completeness credits
    # it while `has_carrier`-style checks correctly see nothing.
    assert (absent.intent, absent.value, absent.answered) == (ABSENCE, "", True)
    # A non-answer is never stored at all.
    assert (unknown.intent, unknown.answered, unknown.accepted) == (UNKNOWN, False, False)
    assert unknown.message, "a refusal must tell the producer what to do"


# ── 1. Negative existence, however it is phrased ─────────────────────────────

@pytest.mark.parametrize("answer", [
    "None", "none", "NONE", "Nil", "nothing", "zero", "no", "N",
    "none at all", "none known", "none reported", "nothing to report",
    "no prior carrier", "no previous coverage", "we have no coverage",
    "never insured", "never carried insurance", "we never had coverage",
    "previously uninsured", "first-time buyer", "First time buying insurance",
    "there is no policy", "does not have coverage",
])
def test_absence_however_phrased(answer):
    r = _i("prior_carrier", answer)
    assert r.intent == ABSENCE, f"{answer!r} -> {r.intent} ({r.reason})"
    assert r.value == "" and r.answered


# ── 2. Uncertainty: a NON-answer, never stored ───────────────────────────────

@pytest.mark.parametrize("answer", [
    "don't know", "dont know", "do not know", "dunno", "not sure", "unsure",
    "unknown", "unclear", "no idea", "can't say", "cannot say",
    "TBD", "tbd", "T.B.D.", "to be confirmed", "to be determined",
    "will confirm", "will check", "will get back to you", "need to check",
    "awaiting", "waiting on the client", "following up", "ask the client",
    "not yet known", "not available yet", "?", "  ?  ",
])
def test_uncertainty_is_never_stored(answer):
    r = _i("prior_carrier", answer)
    assert r.intent == UNKNOWN, f"{answer!r} -> {r.intent} ({r.reason})"
    assert not r.accepted and not r.answered


def test_uncertainty_beats_negation():
    """"no idea" contains "no" - a keyword scan would call it an absence.
    This is the precedence rule that makes it judge meaning, not words."""
    assert _i("prior_carrier", "no idea").intent == UNKNOWN


# ── 3. Inapplicability: an answer, per Brent ─────────────────────────────────

@pytest.mark.parametrize("answer", [
    "N/A", "n/a", "na", "not applicable", "Not Applicable",
    "does not apply", "doesn't apply", "not relevant",
])
def test_not_applicable_is_an_answer(answer):
    r = _i("prior_carrier", answer)
    assert r.intent == NOT_APPLICABLE
    assert r.answered, "Brent: 'we can't treat N/A as 0. These are not the same.'"


# ── 4. Numbers, written any way a person writes them ─────────────────────────

@pytest.mark.parametrize("answer,expected", [
    ("12", "12"), ("five", "5"), ("twelve", "12"), ("twenty five", "25"),
    ("about 12", "12"), ("approx 7", "7"), ("~9", "9"), ("12 employees", "12"),
    ("0", "0"),
])
def test_counts_however_written(answer, expected):
    assert _i("num_employees", answer).value == expected


@pytest.mark.parametrize("answer,expected", [
    ("2000000", "2000000"), ("2,000,000", "2000000"), ("$2,000,000", "2000000"),
    ("$2M", "2000000"), ("2m", "2000000"), ("2mm", "2000000"),
    ("2 million", "2000000"), ("1.5k", "1500"), ("3bn", "3000000000"),
    ("about $2 million", "2000000"),
])
def test_money_however_written(answer, expected):
    assert _i("total_revenue", answer).value == expected


@pytest.mark.parametrize("answer", [
    "07/15/2026", "7/15/2026", "July 15 2026", "15 July 2026", "2026-07-15",
])
def test_dates_however_written(answer):
    assert _i("effective_date", answer).value == "07/15/2026"


def test_a_zero_count_is_a_value_not_an_absence():
    """Precedence: a parseable value of the field's own type beats negation.
    "0" employees is a real number, not "there is none"."""
    r = _i("num_employees", "0")
    assert r.intent == VALUE and r.value == "0"


# ── 5. The guards - things that must NOT be misread ──────────────────────────

@pytest.mark.parametrize("carrier", [
    "Travelers", "Hartford", "Nationwide", "EMC Insurance Companies",
    "Stone Ridge Mutual", "Bonneville Casualty", "Northbridge Indemnity",
    "First American Insurance", "Non-Profit Insurance Alliance",
])
def test_a_real_carrier_name_is_never_read_as_negation(carrier):
    r = _i("prior_carrier", carrier)
    assert r.intent == VALUE and r.value == carrier


def test_a_descriptive_sentence_containing_not_stays_a_value():
    """Negation needs SCOPE. A long descriptive answer that merely contains
    "do not" is a value, not an absence."""
    text = ("We do commercial roofing and do not perform any work above three "
            "stories or on occupied structures")
    r = _i("operations_description", text)
    assert r.intent == VALUE and r.value == text


@pytest.mark.parametrize("field,answer", [
    ("fein", "84-2210987"), ("naics_code", "238160"), ("sic_code", "1761"),
])
def test_identifier_codes_are_never_numerically_coerced(field, answer):
    """An identifier is a STRING of digits, not a quantity. Coercing
    "84-2210987" as a number yields 84 and destroys the value - a real
    regression this test exists to prevent."""
    assert _i(field, answer).value == answer


@pytest.mark.parametrize("answer", [
    "Not covered", "Waived", "Statutory", "See schedule", "Included",
    "NOT COVERED DEDUCTIBLE - EARTHQUAKE COVERAGE",
])
def test_descriptive_amount_conventions_survive(answer):
    """ACORD amount boxes legitimately hold these. Mirrors the permissive-by-
    default rule in pdf_service's declared-type guard."""
    r = _i("gl_deductible", answer)
    assert r.intent == VALUE and r.value == answer


def test_a_malformed_number_is_still_refused():
    assert _i("gl_deductible", "12.34.56").intent == UNKNOWN
    assert words_to_number("12.34.56") is None


# ── 6. Negative-polarity facts: "none" FILLS them ────────────────────────────

@pytest.mark.parametrize("key,expected", [
    ("loss_history_no_prior_losses_indicator", True),
    ("no_prior_losses", True),
    ("asserts_no_known_losses", True),
    ("prior_carrier", False), ("num_employees", False), ("year_built", False),
])
def test_negative_polarity_detection_is_derived_from_the_key(key, expected):
    assert is_absence_affirmative(key) is expected


@pytest.mark.parametrize("answer", [
    "None", "no claims", "Zero claims", "loss free", "clean loss history",
    "No - no claims or losses in the past 5 years",
])
def test_none_fills_a_negative_polarity_fact(answer):
    """On "no prior losses", answering "None" is the AFFIRMATIVE answer - it
    fills the fact rather than emptying it, and the readers that already parse
    this family must keep working."""
    from services.loss_history_state import attested_true
    r = _i("loss_history_no_prior_losses_indicator", answer)
    assert r.intent == VALUE
    assert attested_true(r.value) is True


def test_a_bare_no_keeps_its_legacy_meaning_on_the_attestation():
    from services.loss_history_state import attested_true
    r = _i("loss_history_no_prior_losses_indicator", "No")
    assert attested_true(r.value) is False


# ── 7. "Answered" vs "has a value" - the separation that fixes the scoring ───

def test_fact_answered_credits_an_absence_but_not_a_blank():
    assert fact_answered({"value": "", "value_state": "explicit_no"}) is True
    assert fact_answered({"value": "", "value_state": "not_applicable"}) is True
    assert fact_answered({"value": "", "value_state": "not_stated"}) is False
    assert fact_answered({"value": "Travelers"}) is True
    assert fact_answered("") is False
    assert fact_answered(None) is False


def test_an_absence_answer_no_longer_costs_completeness_points():
    """Brent 2026-08-24: a legitimate "none" must not be penalised."""
    from services.sqs_service import check_tier2
    real = {"fein": "84-2210987", "operations_description": "commercial roofing crews",
            "total_revenue": "2000000", "num_employees": "12",
            "years_in_business": "9", "naics_code": "238160",
            "total_payroll": "800000"}
    scored_real, _ = check_tier2(real, {})
    with_absence = dict(real)
    with_absence["total_payroll"] = build_fact_envelope(
        "total_payroll", _i("total_payroll", "None"), "producer", "filled")
    scored_absence, missing = check_tier2(with_absence, {})
    assert scored_absence == scored_real == 100
    assert not missing


def test_nothing_answered_still_scores_zero():
    """The other direction: the fix must not make emptiness look answered."""
    from services.sqs_service import check_tier2
    assert check_tier2({}, {})[0] == 0


# ── 8. The gate: a non-answer can never become data ──────────────────────────

@pytest.mark.parametrize("field", [
    "total_revenue", "num_employees", "prior_carrier", "effective_date",
    "year_built", "operations_description",
])
@pytest.mark.parametrize("answer", ["TBD", "don't know", "will confirm"])
def test_no_field_anywhere_accepts_a_non_answer(field, answer):
    """Measured 2026-08-24: "N/A" in every Tier-2 field scored 100 before this
    gate. Parametrised across field TYPES so the guarantee is not per-field."""
    from routes.audit_routes import _validate_producer_answer
    ok, msg = _validate_producer_answer(field, answer)
    assert ok is False and msg


def test_the_envelope_keeps_the_person_s_own_words():
    """Canonicalizing must never lose what they actually typed - the audit
    trail is the point."""
    env = build_fact_envelope(
        "total_revenue", _i("total_revenue", "about $2 million"),
        "producer", "filled")
    assert env["value"] == "2000000"
    assert env["answer_text"] == "about $2 million"
    assert env["value_state"] == "present"

    env2 = build_fact_envelope(
        "prior_carrier", _i("prior_carrier", "we never had coverage"),
        "producer", "filled")
    assert env2["value"] == "" and env2["value_state"] == "explicit_no"
    assert env2["answer_text"] == "we never had coverage"
