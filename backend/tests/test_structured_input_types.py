"""Figure 18: structured data types for currency, codes and dates.

Covers the three things that change:
  1. `_resolve_input_type` classifies single-scalar fields and - critically -
     REFUSES to classify compound ones.
  2. The normalizers coerce what a human actually types.
  3. `_clean_answer_ex` never discards a client's answer (the data-loss bug).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.arq_service import (  # noqa: E402
    _attach_input_types,
    _blocks_submit,
    _clean_answer,
    _clean_answer_ex,
    _clean_duplicate_words,
    _normalize_code,
    _normalize_currency,
    _normalize_date,
    _resolve_input_type,
)


# ---------------------------------------------------------------------------
# 1. Type resolution
# ---------------------------------------------------------------------------

def test_curated_scalar_fields_get_structured_types():
    assert _resolve_input_type("total_payroll")   == "currency"
    assert _resolve_input_type("total_revenue")   == "currency"
    assert _resolve_input_type("gl_deductible")   == "currency"
    assert _resolve_input_type("effective_date")  == "date"
    assert _resolve_input_type("expiration_date") == "date"
    assert _resolve_input_type("naics_code")      == "code"
    assert _resolve_input_type("sic_code")        == "code"
    assert _resolve_input_type("fein")            == "code"
    assert _resolve_input_type("num_employees")   == "number"
    assert _resolve_input_type("year_built")      == "number"


def test_compound_answer_fields_are_never_typed_as_currency():
    """The guard that makes the curated allowlist worth having.

    `gl_limits` holds "$1,000,000 per occurrence / $2,000,000 aggregate" and
    `auto_liability_limit` holds "$1,000,000 combined single limit". A
    name-regex sweep on "limit" would force both into a single-amount input
    and make the CORRECT answer untypeable.
    """
    for field in ("gl_limits", "auto_liability_limit"):
        assert _resolve_input_type(field) == "text", field


def test_narrative_and_freetext_fields_stay_text():
    for field in ("operations_description", "wc_class_codes", "additional_insured",
                  "narrative_risk_controls", "submission_urgency", "prior_carrier"):
        assert _resolve_input_type(field) == "text", field


def test_canonical_key_resolves_raw_acord_field_names():
    assert _resolve_input_type("PolicyXYZ_Blah_9", "total_payroll") == "currency"


def test_inference_is_limited_to_date_and_the_amount_suffix():
    """Only two conventions are inferred, and neither is the coarse
    `_field_format_type` substring regex.

    That regex matches "limit"/"value"/"payroll" ANYWHERE in a name, which is
    how a compound field would wrongly become a currency box. The Amount rule
    is anchored to the END of the name instead.
    """
    # ACORD-style date field resolves by name.
    assert _resolve_input_type("Policy_EffectiveDate_A") == "date"
    # Ends in Amount -> a real single monetary field.
    assert _resolve_input_type("SomeCoverage_LimitAmount_B") == "currency"
    # Contains "limit"/"value" but does NOT end in Amount -> untouched. This is
    # the assertion that fails if anyone swaps in the substring regex.
    assert _resolve_input_type("SomeCoverage_LimitDescription_B") == "text"
    assert _resolve_input_type("SomeCoverage_ValueNarrative_A")   == "text"


# ---------------------------------------------------------------------------
# 2. Normalizers
# ---------------------------------------------------------------------------

def test_normalize_date_accepts_what_people_actually_type():
    assert _normalize_date("06/01/2025")   == "06/01/2025"
    assert _normalize_date("2025-06-01")   == "06/01/2025"
    assert _normalize_date("6/1/2025")     == "06/01/2025"
    assert _normalize_date("6-1-25")       == "06/01/2025"
    assert _normalize_date("June 1, 2025") == "06/01/2025"
    assert _normalize_date("Jun 1 2025")   == "06/01/2025"
    assert _normalize_date("1 June 2025")  == "06/01/2025"
    assert _normalize_date("June 1st, 2025") == "06/01/2025"


def test_normalize_date_rejects_impossible_and_unreadable_dates():
    assert _normalize_date("02/31/2025") is None   # not a real calendar day
    assert _normalize_date("13/01/2025") is None   # month 13
    assert _normalize_date("sometime in June") is None
    assert _normalize_date("") is None


def test_normalize_currency_formats_and_expands_shorthand():
    assert _normalize_currency("75000")    == "$75,000"
    assert _normalize_currency("$75,000")  == "$75,000"
    assert _normalize_currency("75k")      == "$75,000"
    assert _normalize_currency("1.5m")     == "$1,500,000"
    assert _normalize_currency("200000")   == "$200,000"


def test_normalize_currency_keeps_a_trailing_qualifier():
    """`business_income_limit` is documented to the client as
    "$20,000 per month" - dropping "per month" would lose real meaning."""
    assert _normalize_currency("20000 per month") == "$20,000 per month"


def test_normalize_currency_leaves_compound_amounts_alone():
    """Two amounts is not one amount - never silently mangle it to the first."""
    assert _normalize_currency("$1,000,000 / $2,000,000") is None
    assert _normalize_currency("not a number") is None


def test_normalize_code_widths_and_fein_formatting():
    assert _normalize_code("238160", "naics_code") == ("238160", True)
    assert _normalize_code("1761", "sic_code")     == ("1761", True)
    # FEIN is conventionally XX-XXXXXXX on ACORD forms.
    assert _normalize_code("123456789", "fein")    == ("12-3456789", True)
    assert _normalize_code("12-3456789", "fein")   == ("12-3456789", True)


def test_normalize_code_flags_a_wrong_width_but_keeps_the_value():
    val, ok = _normalize_code("2381", "naics_code")   # 4 digits, expected 6
    assert ok is False
    assert val == "2381"                              # kept, not discarded


# ---------------------------------------------------------------------------
# 3. The data-loss fix: nothing a client types is ever discarded
# ---------------------------------------------------------------------------

def test_unreadable_date_is_kept_and_flagged_not_dropped():
    """The reported bug: a client typing a date we could not parse had the
    answer silently deleted and was still shown a success screen."""
    val, reason = _clean_answer_ex("sometime in June", "effective_date")
    assert val == "sometime in June"
    assert reason


def test_readable_date_is_normalized_with_no_flag():
    val, reason = _clean_answer_ex("June 1, 2025", "effective_date")
    assert val == "06/01/2025"
    assert reason == ""


def test_iso_date_is_canonicalized_to_mmddyyyy():
    val, reason = _clean_answer_ex("2025-06-01", "effective_date")
    assert val == "06/01/2025"
    assert reason == ""


def test_currency_is_normalized_and_bad_currency_is_kept():
    assert _clean_answer_ex("75000", "total_payroll")[0] == "$75,000"
    val, reason = _clean_answer_ex("about 75 grand", "total_payroll")
    assert val == "about 75 grand"
    assert reason


def test_wrong_width_code_is_kept_and_flagged():
    val, reason = _clean_answer_ex("2381", "naics_code")
    assert val == "2381"
    assert "6-digit" in reason


def test_bad_email_and_phone_are_kept_and_flagged():
    for raw, field in (("not-an-email", "contact_email"), ("abc", "contact_phone")):
        val, reason = _clean_answer_ex(raw, field)
        assert val == raw, field
        assert reason, field


def test_not_sure_and_blank_still_yield_no_answer():
    """A NON-answer is still discarded - and there are now three kinds of input,
    not two.

    SUPERSEDED ASSERTION, recorded rather than deleted (V1 H4, 2026-08-27):
    this test used to assert `_clean_answer_ex("n/a", "total_payroll") ==
    (None, "")`. That line was the test-side pin of defect F15 (v1-20AUG.md
    C3-C, 2026-08-25): the client questionnaire DESTROYED "None" / "N/A" /
    "none" before `answer_semantics` ever saw them, so a client answering our
    own question "Who provided your business insurance most recently? (If none,
    write 'None')" had the answer thrown away, while the PRODUCER path read the
    identical word correctly. Brent, 2026-08-24: *"we can't treat 'N/A' as '0'.
    These are not the same. 'No known losses' is a legitimate answer."*

    The property this test protects - "a non-answer never becomes data" - is
    unchanged and is now asserted more widely than before.
    """
    # 1. NON-ANSWERS: still discarded, and the net is now WIDER. The three
    #    phrases at the end used to sail through and get STAMPED onto an ACORD
    #    box while an empty envelope was written over the extracted fact.
    for raw in ("__NOT_SURE__", "", "   ", "null", "-", "--", "?",
                "tbd", "unknown", "not sure",
                "I will confirm later", "no idea", "waiting on my accountant"):
        assert _clean_answer_ex(raw, "effective_date") == (None, ""), raw

    # 2. ABSENCES / INAPPLICABILITY: real answers, KEPT, and deliberately with
    #    NO review_reason - that empty string is what keeps them away from
    #    `_blocks_submit`, which used to refuse the WHOLE submission (422) when
    #    a client with no umbrella typed "nil" into a currency box.
    for raw, field in (("n/a", "total_payroll"), ("N/A", "fein"),
                       ("None", "prior_carrier"), ("none", "num_claims"),
                       ("nil", "umbrella_limit")):
        value, reason = _clean_answer_ex(raw, field)
        assert value == raw, f"{raw!r} on {field} was discarded again (F15)"
        assert reason == "", f"{raw!r} on {field} would block the submission"

    # 3. A REQUIRED IDENTITY FACT IS NEITHER. The submission does not exist
    #    without an applicant name, so "N/A" there is refused rather than
    #    counted as an answer - otherwise one word in every box scored a
    #    perfect Structural pillar.
    for field in ("applicant_name", "mailing_address", "effective_date"):
        assert _clean_answer_ex("N/A", field) == (None, ""), field

    # 4. AND A YES/NO ANSWER IS NEVER AN ABSENCE. "No" on a checkbox is the
    #    ANSWER; reading it as "there is none" would blank the box.
    assert _clean_answer_ex("no", "Building_SprinkleredIndicator_A") == ("No", "")
    assert _clean_answer_ex("yes", "Building_SprinkleredIndicator_A") == ("Yes", "")


def test_clean_answer_wrapper_stays_backwards_compatible():
    """The single-value signature is still what existing callers expect."""
    assert _clean_answer("June 1, 2025", "effective_date") == "06/01/2025"
    assert _clean_answer("__NOT_SURE__", "effective_date") is None


# ---------------------------------------------------------------------------
# 4. The attach pass never reclassifies an already-typed question
# ---------------------------------------------------------------------------

def test_attach_input_types_upgrades_only_plain_text_questions():
    questions = [
        {"field_name": "total_payroll",  "field_type": "text"},
        {"field_name": "naics_code",     "field_type": "text"},
        {"field_name": "sprinkler_system", "field_type": "checkbox"},
        {"field_name": "valuation_method", "field_type": "select"},
        {"field_name": "auto_vin_schedule", "field_type": "schedule"},
        {"field_name": "gl_limits",      "field_type": "text"},
    ]
    _attach_input_types(questions)
    by_name = {q["field_name"]: q for q in questions}

    assert by_name["total_payroll"]["field_type"] == "currency"
    assert by_name["naics_code"]["field_type"]    == "code"
    assert by_name["naics_code"]["code_digits"]   == 6
    # Structurally incapable of being reclassified:
    assert by_name["sprinkler_system"]["field_type"]  == "checkbox"
    assert by_name["valuation_method"]["field_type"]  == "select"
    assert by_name["auto_vin_schedule"]["field_type"] == "schedule"
    # Compound answer stays free text:
    assert by_name["gl_limits"]["field_type"] == "text"


# ---------------------------------------------------------------------------
# 5. Raw ACORD monetary fields (found during live testing)
# ---------------------------------------------------------------------------

def test_raw_acord_amount_fields_resolve_to_currency():
    """The three WC employers-liability limits came back as plain textareas in
    a live run - they are single dollar amounts and must be typed."""
    for field in (
        "WorkersCompensationEmployersLiability_EmployersLiability_EachAccidentLimitAmount_A",
        "WorkersCompensationEmployersLiability_EmployersLiability_DiseasePolicyLimitAmount_A",
        "WorkersCompensationEmployersLiability_EmployersLiability_DiseaseEachEmployeeLimitAmount_A",
        "Vehicle_CostNewAmount_B",
        "Vehicle_Coverage_AgreedOrStatedAmount_C",
    ):
        assert _resolve_input_type(field) == "currency", field


def test_amount_indicator_checkboxes_are_not_currency():
    """`...StatedAmountIndicator` is a /Btn checkbox, not a value. The `$`
    anchor on the Amount rule is what keeps it out."""
    assert _resolve_input_type("Vehicle_Coverage_ValuationStatedAmountIndicator_A") == "text"


def test_compound_curated_questions_beat_the_amount_convention():
    """A curated question worded as two amounts stays free text even if its
    ACORD field name ends in Amount."""
    assert _resolve_input_type("SomeForm_EachOccurrenceLimitAmount_A", "gl_limits") == "text"
    assert _resolve_input_type("SomeForm_LimitAmount_A", "auto_liability_limit") == "text"


# ---------------------------------------------------------------------------
# 6. Repeated-phrase cleanup in client-facing question text
# ---------------------------------------------------------------------------

def test_repeated_phrase_is_collapsed_in_question_text():
    """Live defect: ACORD repeats a section name inside the field name, so the
    client was shown "...employers liability employers liability each..."."""
    got = _clean_duplicate_words(
        "Please provide your workers compensation employers liability "
        "employers liability each accident limit amount."
    )
    assert "employers liability employers liability" not in got.lower()
    assert got == ("Please provide your workers compensation employers liability "
                   "each accident limit amount.")


def test_single_word_repeat_behaviour_is_unchanged():
    assert _clean_duplicate_words("the the value") == "the value"
    assert _clean_duplicate_words("policy policy number") == "policy number"


def test_legitimately_repeated_words_that_are_not_adjacent_survive():
    text = "List each class code and the payroll for that class code."
    assert _clean_duplicate_words(text) == text


# ---------------------------------------------------------------------------
# 7. Submit blocking - only on checks the client's browser also runs
# ---------------------------------------------------------------------------

def test_client_visible_format_errors_block_submit():
    """A badly formatted answer must never reach an ACORD box."""
    assert _blocks_submit("date",     "effective_date")  is True
    assert _blocks_submit("currency", "total_payroll")   is True
    assert _blocks_submit("code",     "naics_code")      is True
    assert _blocks_submit("number",   "num_employees")   is True
    # Email / phone are validated in the browser by field name.
    assert _blocks_submit("text", "contact_email") is True
    assert _blocks_submit("text", "contact_phone") is True


def test_server_only_checks_never_block_the_client():
    """The stuck-client guard.

    These fail server-side checks the client's browser does NOT run, so
    blocking on them would produce a 422 the client can neither see nor fix.
    They must stay advisory (kept + flagged for the producer).
    """
    # `_field_format_type` matches "limit" anywhere -> "number", but this
    # renders as a free-text box.
    assert _blocks_submit("text", "SomeCoverage_LimitDescription_A") is False
    # The "indicator" branch expects Yes/No, but this reaches the client as a
    # text box.
    assert _blocks_submit("text", "Building_SprinkleredIndicator_A") is False
    # Ordinary narrative fields are never blocked.
    assert _blocks_submit("text", "operations_description") is False


def test_a_blocked_field_is_still_normalized_not_mangled():
    """Blocking is about the FORMAT check, not about corrupting the value:
    an answer we CAN read still passes cleanly and is never blocked."""
    val, reason = _clean_answer_ex("Dec 1, 2026", "expiration_date")
    assert val == "12/01/2026"
    assert reason == ""            # readable -> no error -> submits fine

    val, reason = _clean_answer_ex("sometime in December", "expiration_date")
    assert reason                  # unreadable -> error -> submission blocked
    assert _blocks_submit("date", "expiration_date") is True


def test_attach_input_types_is_idempotent():
    questions = [{"field_name": "effective_date", "field_type": "text"}]
    _attach_input_types(questions)
    _attach_input_types(questions)
    assert questions[0]["field_type"] == "date"
