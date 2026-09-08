"""SYS-07 - "Yes", boolean true, "X" and a checked box are ONE affirmative.

Client, September 1 live test (P0 systemic correction, Normalization / boolean
fields):

    "The same affirmative answer can arrive as 'Yes,' boolean true, X, or a
    checked box depending on the source document and extraction path. These
    representation differences should not create false conflicts."

    Expected: "Normalize common affirmative representations to one canonical
    true value and common negative representations to one canonical false value
    BEFORE comparison. Route this through the SAME pre-comparison
    canonicalization layer used for other equivalent values so warnings are
    created only after normalization and formatting or representation
    differences alone cannot produce a conflict."

Reported case: the Data Consistency panel printed **Auto Hired Nonowned -
VALUES DIFFER - CONFIRM**, "Yes" from *2526 Package Policy (Complete Copy).pdf*
against "X" from *CRS COI FiO - Orbin CERT ONLY.pdf*. Same answer.

ROOT CAUSE (measured, not assumed). The Yes/No comparator already existed and
worked; it was never REACHED. `fact_equivalence.value_kind` guessed a fact's
type from the spelling of its KEY, and its only route to `KIND_YESNO` was
`if "indicator" in tokens or "required" in tokens`. Of the eight facts
FACT_REGISTRY itself declares "Yes or No", three compared as free TEXT and two -
`agreed_value_endorsement`, `inside_city_limits` - reached the MONEY tokens
("value", "limits") first and were compared as dollar amounts.

Underneath it, EIGHT modules carried a private "what counts as affirmative"
list and no two agreed. The one that mattered most:
`pdf_service._resolve_bool_indicator("X")` returned **"No"** - an affirmative X
would have ticked the NEGATIVE box on a signed ACORD form - and the /Btn
checkbox writer accepted "x" but not "y".

These tests drive the REAL modules with the client's literal values. They are
grouped by the thing they protect, and the last group is the anti-rot guard.
"""
import ast
import pathlib

import pytest

from services import fact_comparison as fc
from services import fact_equivalence as fe
from services import normalization as norm
from services import pdf_service as ps
from services.extraction_service import BOOLEAN_FACT_KEYS
from services.fact_registry import FACT_REGISTRY
from services.underwriting_consistency import (
    assess_underwriting_consistency, validate_confirmation,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]

# The client's own two documents and their two printings of one answer.
_POLICY = "2526 Package Policy (Complete Copy).pdf"
_CERT = "CRS COI FiO - Orbin CERT ONLY.pdf"


# ─────────────────────────────────────────────────────────────────────────────
# 1. THE REPORTED CASE, end to end through the real picker
# ─────────────────────────────────────────────────────────────────────────────

def _docs(policy_value, cert_value):
    return [
        {"doc_id": "1", "filename": _POLICY, "doc_type": "policy", "text": "",
         "facts": {"applicant_name": "ORBIN CONTRACTING LLC",
                   "auto_hired_nonowned": policy_value}},
        {"doc_id": "2", "filename": _CERT, "doc_type": "certificate", "text": "",
         "facts": {"applicant_name": "ORBIN CONTRACTING LLC",
                   "auto_hired_nonowned": cert_value}},
    ]


def _picker_row(policy_value, cert_value):
    res = assess_underwriting_consistency(
        _docs(policy_value, cert_value),
        {"applicant_name": "ORBIN CONTRACTING LLC",
         "auto_hired_nonowned": policy_value}, {})
    for f in res["fields"]:
        if f["fact_key"] == "auto_hired_nonowned":
            return f
    return None


def test_the_client_reported_case_is_no_longer_a_conflict():
    """MUST NEVER FAIL: the literal screenshot values, through the real picker."""
    row = _picker_row("Yes", "X")
    assert row is None or not row.get("review_required"), (
        "'Yes' from the policy and 'X' from the certificate are one answer")


def test_a_real_disagreement_between_the_same_two_documents_still_asks():
    """The other direction. Normalizing must not silence principle 4."""
    row = _picker_row("Yes", "No")
    assert row is not None and row["review_required"]
    assert sorted(v["display"] for v in row["values"]) == ["No", "Yes"]


@pytest.mark.parametrize("cert_value", [
    "X", "x", "Y", "y", "true", "TRUE", "1", "on", "/Yes", "yes",
    "✓", "✔", "☑", "☒",       # ✓ ✔ ☑ ☒
    "[X]", "(x)", "{X}", "Yes.", " X ", "checked", "Included", True,
])
def test_every_affirmative_printing_agrees_with_yes(cert_value):
    assert fc.compare("auto_hired_nonowned", ["Yes", cert_value]).verdict in (
        "equivalent", "single")


@pytest.mark.parametrize("cert_value", [
    "N", "n", "false", "0", "off", "no", "☐", "[N]", "unchecked",
    "Excluded", False,
])
def test_every_negative_printing_agrees_with_no(cert_value):
    assert fc.compare("auto_hired_nonowned", ["No", cert_value]).verdict in (
        "equivalent", "single")


@pytest.mark.parametrize("yes_form,no_form", [
    ("Yes", "No"), ("X", "N"), ("true", "false"), ("✓", "☐"),
    ("Y", "no"), ("1", "0"), ("Included", "Excluded"),
])
def test_an_affirmative_never_merges_with_a_negative(yes_form, no_form):
    assert fc.compare("auto_hired_nonowned", [yes_form, no_form]).verdict == "conflict"


# ─────────────────────────────────────────────────────────────────────────────
# 1b. LIVE RUN 1 - the answer arrived carrying its own question
#
# The extractor returned the WHOLE printed line for the certificate
# ("Hired and Non-Owned Auto Coverage: X") where the same layout gave a bare
# "X" in the control package. A label is the question restated, not a
# qualifier on the answer - so it is read; "Yes - see the attached schedule" is
# a qualifier, and is not.
# ─────────────────────────────────────────────────────────────────────────────

_LIVE_LABELLED = "Hired and Non-Owned Auto Coverage: X"


def test_the_live_run_labelled_value_is_the_same_answer_as_yes():
    """MUST NEVER FAIL: run 1's literal card, through the real door."""
    assert norm.yes_no_answer(_LIVE_LABELLED) == "Y"
    assert norm.canonical_yes_no(_LIVE_LABELLED) == "Yes"
    assert norm.normalize_value("auto_hired_nonowned", _LIVE_LABELLED) == "yes"
    assert fc.compare("auto_hired_nonowned", ["Yes", _LIVE_LABELLED]).verdict \
        == "equivalent"


def test_the_live_run_card_is_gone_end_to_end():
    row = _picker_row("Yes", _LIVE_LABELLED)
    assert row is None or not row.get("review_required")


@pytest.mark.parametrize("value,expected", [
    # EVERY separator a printed form uses to divide a question from its answer.
    # The first cut took ":" and "=" only - the two the live run happened to
    # print - which is fitting the fixture. A real dec page, broker worksheet or
    # flattened table uses all of these.
    ("Hired and Non-Owned Auto Coverage: X", "Y"),
    ("Hired and Non-Owned Auto Coverage = X", "Y"),
    ("Hired and Non-Owned Auto Coverage - X", "Y"),        # hyphen
    ("Hired and Non-Owned Auto Coverage – X", "Y"),        # en dash
    ("Hired and Non-Owned Auto Coverage — X", "Y"),        # em dash
    ("Hired and Non-Owned Auto Coverage | X", "Y"),        # table cell boundary
    ("Hired and Non-Owned Auto Coverage\tX", "Y"),         # tab
    ("Hired and Non-Owned Auto Coverage    X", "Y"),       # a COLUMN GAP
    ("Hired and Non-Owned Auto Coverage ....... X", "Y"),  # dot leader
    ("Hired and Non-Owned Auto Coverage.......X", "Y"),
    ("HIRED / NON-OWNED AUTO LIABILITY:  [X]", "Y"),
    ("Hired & Non-Owned Auto   ✓", "Y"),
    ("Non-Owned Auto Liability - ☑", "Y"),
    ("Sprinkler System:Yes", "Y"),
    ("Automatic Sprinklers Throughout   YES", "Y"),
    ("Prior Cyber Incidents or Data Breaches - N", "N"),
    ("Vehicle Maintenance Program ....... No", "N"),
    ("Coverage Elected | true", "Y"),
    ("Auto: Hired and Non-Owned: X", "Y"),      # splits on the LAST separator
])
def test_a_labelled_answer_is_read(value, expected):
    assert norm.yes_no_answer(value) == expected


@pytest.mark.parametrize("value", [
    "Total Losses - 0",          # a labelled COUNT, not a No
    "Employee Dishonesty  -  0",
    "Number of Claims: 0",
    "Years in Business - 1",
    "Coverage Elected|1",
])
def test_a_bare_digit_behind_a_label_is_a_number_not_an_answer(value):
    """A bare "0"/"1" ALONE on a Yes/No field can only be the answer - there is
    nothing else the box holds. Behind a label it is exactly the shape of a
    labelled count or amount, and "Total Losses - 0" is not a No. Found by the
    fuzz sweep, not by reasoning: the first cut read it as one."""
    assert norm.yes_no_answer(value) is None
    # ...while the bare digit itself is still read.
    assert norm.yes_no_answer("0") == "N" and norm.yes_no_answer("1") == "Y"


@pytest.mark.parametrize("value", [
    "Yes — subject to underwriting approval",
    "Yes - only scheduled autos",
    "No - refer to endorsement CA 99 03",
    "Yes if requested by written contract",
    "24 - 7", "1 - 1", "3 - 0",
    "Combined Single Limit - 1,000,000",
    "Covered Autos: Symbol 1 - Any Auto",
    "Not Applicable - X", "unknown | X", "none ....... X",
    "X (Hired and Non-Owned Auto)",   # mark-first parenthetical: ambiguous, refused
])
def test_widening_the_separators_did_not_widen_what_is_accepted(value):
    """THE SAFETY ARGUMENT for accepting every separator: the TAIL test does the
    work, not the separator. A qualifier is never a bare Yes/No token, so it
    fails however it is divided from the answer."""
    assert norm.yes_no_answer(value) is None


@pytest.mark.parametrize("value", [
    "Yes - see the attached schedule",     # a QUALIFIER, never flattened
    "Yes, 3 vehicles",
    "1:0",                                 # a ratio: the two halves contradict
    "0:1",
    "10:30",                               # a time
    "Deductible: $1,000",
    "Policy Period: 09/25/2026",
    "Covered Autos: Symbol 1 - Any Auto",
    "N/A: X",                              # the label is a non-answer
    "Not Applicable = X",
    "unknown: X",
    ("The applicant confirms coverage is in force. A full schedule of "
     "underlying insurance is attached and has been reviewed: X"),  # a paragraph
    "Hired and Non-Owned Auto Coverage: maybe",
])
def test_a_value_that_is_not_a_labelled_answer_is_refused(value):
    assert norm.yes_no_answer(value) is None


def test_a_stray_separator_around_a_bare_mark_is_still_just_the_mark():
    """": X" has no label - it is an "X" with punctuation noise around it, and
    the STRICT reader already trims punctuation from both ends. Pinned so the
    trim and the label rule cannot drift into disagreeing about it."""
    assert norm.yes_no_token(": X") == "Y"
    assert norm.yes_no_answer(": X") == "Y"


def test_the_strict_reader_is_deliberately_unchanged():
    """`yes_no_token` stays bare-token-only. It is what licenses the
    value-shaped fallback, which runs on facts NOTHING declares - reading a
    labelled value there would be an opinion on no evidence."""
    assert norm.yes_no_token(_LIVE_LABELLED) is None
    assert norm.yes_no_token("X") == "Y"
    assert fe.same_fact(_UNDECLARED, "Yes", _LIVE_LABELLED) != fe.SAME


def test_a_labelled_answer_never_wins_the_display():
    keep = "Yes" if fe._prefer("auto_hired_nonowned", "Yes", _LIVE_LABELLED) \
        else _LIVE_LABELLED
    assert keep == "Yes"


def test_the_merge_folds_a_labelled_answer_into_its_bare_twin():
    from services.extraction_service import _variant_group_key as k
    assert k(_LIVE_LABELLED, "auto_hired_nonowned") == k("Yes", "auto_hired_nonowned")
    assert k(_LIVE_LABELLED, "auto_hired_nonowned") != k("No", "auto_hired_nonowned")
    assert k(_LIVE_LABELLED) != k("Yes")      # no fact key -> no Yes/No fold


def test_a_labelled_answer_still_disagrees_with_the_opposite_answer():
    assert fc.compare("auto_hired_nonowned",
                      ["No", _LIVE_LABELLED]).verdict == "conflict"


def test_the_yn_box_gate_writes_the_canonical_answer_for_a_labelled_value():
    """Before, the gate could not read it, so the box was dropped to gap fill."""
    schema = {"Box_Question_AAACode_A": {"ft": "/Tx",
              'tu': 'Enter Y for a "Yes" response. Input N for "No" response. '
                    'The response to the question, "Does the applicant own autos"?'}}
    assert ps._yn_gate("Box_Question_AAACode_A", _LIVE_LABELLED, schema) == "Yes"


# ─────────────────────────────────────────────────────────────────────────────
# 2. WHAT THE READER REFUSES TO DECIDE - core principles 3 and 7
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [
    "N/A", "n/a", "not applicable", "none", "None", "null", "unknown",
    "TBD", "see attached", "", "   ", None, "-", "[ ]", "[]",
])
def test_a_non_answer_is_never_read_as_yes_or_no(value):
    """Missing does not mean No (core principle 3), and a non-answer is not a
    value. Every one of these must be "cannot say"."""
    assert norm.yes_no_token(value) is None
    assert norm.canonical_yes_no(value) is None


@pytest.mark.parametrize("value", [
    "Yes - see the attached schedule", "No prior losses", "Yes, 3 vehicles",
    "Yes for GL only",
    # "not covered" USED to sit here. It is not a qualifier - it is a two-word
    # negative a declarations grid actually prints, and since 2026-09-05 the
    # negation rule reads it as the No it is. Pinned in its own test below.
])
def test_a_qualified_answer_is_not_flattened_to_a_bare_yes_or_no(value):
    """Only a WHOLE bare token is read. A qualified answer keeps its words and
    falls through to ordinary text comparison, so nothing is lost."""
    assert norm.yes_no_token(value) is None


def test_a_bare_ballot_x_glyph_with_no_box_gets_no_opinion():
    """U+2717 / U+2718 mean "checked" in a column and "wrong" standing alone.
    Ambiguous, so no opinion - never a guess in either direction."""
    assert norm.yes_no_token("✗") is None
    assert norm.yes_no_token("✘") is None


def test_a_real_boolean_false_is_read_as_no_not_as_absent():
    """The previous reader did ``str(value or "")``, so ``False`` became the
    empty string and a stored boolean False was silently unreadable."""
    assert norm.yes_no_token(False) == "N"
    assert norm.canonical_yes_no(False) == "No"
    assert norm.yes_no_token(True) == "Y"
    assert fe.same_fact("auto_hired_nonowned", False, "No") == fe.SAME
    assert fe.same_fact("auto_hired_nonowned", False, "Yes") == fe.DIFFERENT


def test_a_bare_boolean_false_is_still_not_a_rival_value_in_the_picker():
    """DELIBERATE, and it is defect B8. Every non-tri-state boolean in the
    extraction schema is `false` when the document simply never mentioned the
    subject, so a bare False must not become a candidate that conflicts with
    another document's "Yes". `fact_comparison._usable` still filters it and
    this change did NOT touch that."""
    assert fc.compare("auto_hired_nonowned", ["Yes", False]).verdict == "single"


# ─────────────────────────────────────────────────────────────────────────────
# 3. THE TYPE IS READ FROM THE DECLARATION, NOT GUESSED FROM THE KEY'S NAME
# ─────────────────────────────────────────────────────────────────────────────

def test_the_reported_field_is_now_typed_yes_no():
    assert fe.value_kind("auto_hired_nonowned") == fe.KIND_YESNO


@pytest.mark.parametrize("key", sorted(BOOLEAN_FACT_KEYS))
def test_every_key_llm_call_1_declares_boolean_compares_as_yes_no(key):
    assert fe.value_kind(key) == fe.KIND_YESNO


def test_every_registry_declared_yes_no_fact_compares_as_yes_no():
    """The registry's OWN declaration, which nothing used to read. Two of these
    were being compared as dollar amounts."""
    declared = [k for k, v in FACT_REGISTRY.items()
                if str(v.get("format_hint") or "").strip().lower().startswith("yes or no")]
    assert declared, "the registry must still declare some Yes/No facts"
    assert [k for k in declared if fe.value_kind(k) != fe.KIND_YESNO] == []


@pytest.mark.parametrize("key,was", [
    ("agreed_value_endorsement", "money"),      # the token "value"
    ("inside_city_limits", "money"),            # the token "limits"
    ("auto_split_limits", "money"),
    ("property_has_peril_deductibles", "money"),
    ("gl_is_claims_made", "count"),
    ("wc_multi_state", "state"),
    ("has_motor_carrier_coverage", "name"),     # compared with strict_entity_key!
    ("has_garage_operations", "narrative"),     # always INCOMPARABLE
    ("is_certificate_doc", "identifier"),
])
def test_the_facts_the_name_guess_got_wrong(key, was):
    """Each of these is a boolean that the key-shape guess routed to a
    comparator built for something else. Pinned by their OLD kind so the
    regression is unmistakable if the ordering is ever changed back."""
    assert was != "yesno"
    assert fe.value_kind(key) == fe.KIND_YESNO


@pytest.mark.parametrize("key,kind", [
    ("has_umbrella", "yesno"),          # a boolean
    ("has_umbrella_limit", "money"),    # ...the same prefix over an AMOUNT
    ("is_renewal", "yesno"),
    ("is_effective_date", "date"),
    ("required_limit_amount", "money"),
    ("indicator_premium_amount", "money"),
])
def test_the_shape_guess_never_outranks_a_key_that_names_another_type(key, kind):
    """`has_` and `is_` are a GUESS. A guess must not beat a key that says
    outright it holds an amount, a count or a date - so the shape route is
    blocked by those tokens while the DECLARATION route is not."""
    assert fe.value_kind(key) == kind


def test_every_yes_no_classification_can_name_its_source():
    """Nothing is typed Yes/No by accident: each one is either declared (by the
    registry or by LLM call 1's schema) or carries the indicator shape."""
    import re as _re
    from services.extraction_service import _EXTRACT_SCHEMA
    from services.underwriting_consistency import RECONCILABLE_FIELDS
    keys = (set(FACT_REGISTRY) | set(RECONCILABLE_FIELDS)
            | set(_re.findall(r'"([a-z_][a-z0-9_]*)"\s*:', _EXTRACT_SCHEMA)))
    yn = [k for k in keys if fe.value_kind(k) == fe.KIND_YESNO]
    assert len(yn) > 40
    assert [k for k in sorted(yn)
            if not norm.declares_yes_no(k) and not norm.yes_no_field_shape(k)] == []


def test_no_identity_field_was_captured_by_the_yes_no_rule():
    """The blast-radius gate. A declaration outranks a guess, but it must never
    outrank the identity tables that were already authoritative."""
    identity = (norm.NAME_FIELDS | norm.DATE_FIELDS | norm.ADDRESS_FIELDS
                | norm.CARRIER_FIELDS | norm.FEIN_FIELDS
                | norm.ENTITY_TYPE_FIELDS | norm.VALUATION_METHOD_FIELDS)
    assert [k for k in sorted(identity) if fe.value_kind(k) == fe.KIND_YESNO] == []


@pytest.mark.parametrize("key,kind", [
    ("gl_each_occurrence", "money"), ("total_payroll", "money"),
    ("num_employees", "count"), ("years_in_business", "count"),
    ("effective_date", "date"), ("applicant_name", "name"),
    ("carrier_name", "name"), ("mailing_address", "address"),
    ("fein", "fein"), ("policy_number", "identifier"),
    ("naics_code", "code"), ("operations_description", "narrative"),
])
def test_no_other_fact_changed_its_comparator(key, kind):
    assert fe.value_kind(key) == kind


# ─────────────────────────────────────────────────────────────────────────────
# 4. THE VALUE-SHAPED FALLBACK, AND ITS STRUCTURAL SECOND CONDITION
# ─────────────────────────────────────────────────────────────────────────────

_UNDECLARED = "undeclared_mystery_answer"


def test_an_undeclared_fact_still_folds_yes_against_x():
    """The declaration route covers every key we can name; this covers a key
    we have never seen."""
    assert fe.value_kind(_UNDECLARED) == fe.KIND_TEXT
    assert fc.compare(_UNDECLARED, ["Yes", "X"]).verdict == "equivalent"
    assert fc.compare(_UNDECLARED, ["No", "☐"]).verdict == "equivalent"


@pytest.mark.parametrize("a,b", [
    ("1", "0"),      # two numbers on an untyped field, NOT Yes vs No
    ("1", "x"),      # a mark against a digit: no unambiguous word, no fold
    ("0", "n"),
    ("t", "f"),      # two initials
    ("on", "off"),
])
def test_a_mark_alone_never_licenses_the_fold_on_an_undeclared_fact(a, b):
    """THE STRUCTURAL SECOND CONDITION (H1-F's standing lesson). Both sides
    reading as Yes/No is necessary but not sufficient - one side must be an
    unambiguous English boolean word."""
    verdict = fe.same_fact(_UNDECLARED, a, b)
    assert verdict != fe.SAME, (
        f"{a!r} and {b!r} must not be pronounced the same value on a fact "
        "nothing declares to be a Yes/No")


def test_a_declared_yes_no_field_does_fold_one_against_zero():
    """The same pair on a field that IS declared Yes/No is a real answer -
    the second condition is only needed where the type is unknown."""
    assert fe.same_fact("auto_hired_nonowned", "1", "0") == fe.DIFFERENT
    assert fe.same_fact("auto_hired_nonowned", "1", "Yes") == fe.SAME


def test_a_count_field_keeps_comparing_numbers():
    """The pathological case the second condition exists for, on a real key."""
    assert fc.compare("num_employees", ["1", "0"]).verdict == "conflict"
    assert fc.compare("num_employees", ["12", "12"]).verdict == "equivalent"


def test_an_enumerated_field_keeps_its_other_values():
    """`sprinkler_system` accepts Yes/No AND Wet/Dry/Partial. It is now typed
    Yes/No, and its non-boolean values must still compare as text."""
    assert fe.value_kind("sprinkler_system") == fe.KIND_YESNO
    assert fc.compare("sprinkler_system", ["Yes", "X"]).verdict == "equivalent"
    assert fc.compare("sprinkler_system", ["Wet", "Dry"]).verdict == "conflict"


# ─────────────────────────────────────────────────────────────────────────────
# 5. ONE CANONICAL VALUE - the second half of the acceptance criteria
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("values,expected", [
    (["X", "Yes"], "Yes"), (["Yes", "X"], "Yes"),
    (["true", "Y"], "Y"), (["✓", "No"], "No"),
    (["1", "yes"], "yes"),
])
def test_the_canonical_printing_wins_the_display(values, expected):
    """`_prefer` used to keep the SHORTEST printing for a Yes/No, which is
    right for an amount and wrong here: the moment these facts started
    comparing as Yes/No it would have put the certificate's bare "X" in front
    of the producer with a Suggested badge on it, and stamped that X."""
    keep = values[0] if fe._prefer("auto_hired_nonowned", values[0], values[1]) \
        else values[1]
    assert keep == expected


def test_the_picker_shows_yes_not_the_certificates_x():
    from services.underwriting_consistency import _merge_equivalent_value_groups
    groups = [{"normalized": "x", "display": "X", "sources": [{"filename": _CERT}]},
              {"normalized": "yes", "display": "Yes", "sources": [{"filename": _POLICY}]}]
    merged = _merge_equivalent_value_groups("auto_hired_nonowned", groups)
    assert len(merged) == 1
    assert merged[0]["display"] == "Yes"
    assert len(merged[0]["sources"]) == 2, "both documents keep their attribution"


def test_normalize_value_canonicalizes_a_yes_no_before_any_comparison():
    """The client asked for this to live in the pre-comparison canonicalization
    layer. `normalize_value` IS that layer, and `field_qa` reads it too - so a
    stamped "Yes" now agrees with a source fact of "X"."""
    for v in ("Yes", "X", "true", "1", "✓", "[X]", True):
        assert norm.normalize_value("auto_hired_nonowned", v) == "yes"
    for v in ("No", "N", "false", "0", "☐", False):
        assert norm.normalize_value("auto_hired_nonowned", v) == "no"
    # An unrelated field is untouched.
    assert norm.normalize_value("applicant_name", "X") != "yes"


def test_a_confirmed_value_is_stored_in_its_canonical_printing():
    """The producer confirming the certificate's X is confirming the ANSWER."""
    assert validate_confirmation("auto_hired_nonowned", "X",
                                 _docs("Yes", "X")) == "Yes"
    assert validate_confirmation("auto_hired_nonowned", "☐",
                                 _docs("Yes", "X")) == "No"
    # A non-Yes/No field is returned exactly as typed.
    assert validate_confirmation("applicant_name", " Orbin Contracting LLC ",
                                 _docs("Yes", "X")) == "Orbin Contracting LLC"


# ─────────────────────────────────────────────────────────────────────────────
# 6. THE MERGE - one canonical fact (core principle 1)
# ─────────────────────────────────────────────────────────────────────────────

def test_the_merge_no_longer_splits_one_answers_own_vote():
    """`yes` / `x` / `true` / `y` were FOUR rivals for one answer, so the
    winner was decided by which spelling appeared most often and "X" could
    become the stored fact - and then the value stamped on every form."""
    from services.extraction_service import _variant_group_key as k
    keys = {k(v, "auto_hired_nonowned") for v in ("Yes", "yes", "X", "x", "Y",
                                                  "true", "1", "✓", "[X]")}
    assert len(keys) == 1
    assert k("No", "auto_hired_nonowned") != k("Yes", "auto_hired_nonowned")


def test_the_merge_elects_the_canonical_printing():
    from services.extraction_service import _prefer_variant as p
    assert p("Yes", "X", "auto_hired_nonowned") is True
    assert p("X", "Yes", "auto_hired_nonowned") is False


def test_the_merge_is_untouched_for_every_other_fact():
    """`_variant_group_key`'s fact_key is optional so the existing callers and
    their pinned behaviour are byte-identical."""
    from services.extraction_service import _variant_group_key as k
    assert k("07/15/25") == k("07/15/2025")
    assert k("$1,000,000") == k("$ 1,000,000")
    assert k("Yes") != k("X")                 # no key -> no Yes/No fold
    assert k("Yes", "applicant_name") != k("X", "applicant_name")


def test_two_documents_merge_to_one_canonical_answer():
    from services.extraction_service import _merge_list_fields
    merged = _merge_list_fields([
        {"_chunk_idx": 0, "facts": {"auto_hired_nonowned": "X"}, "flags": {}},
        {"_chunk_idx": 1, "facts": {"auto_hired_nonowned": "X"}, "flags": {}},
        {"_chunk_idx": 2, "facts": {"auto_hired_nonowned": "Yes"}, "flags": {}},
    ], [])
    assert merged["facts"]["auto_hired_nonowned"] == "Yes", (
        "the answer is one value however it is spelled, and it is stored "
        "canonically even when the mark outnumbers the word")


# ─────────────────────────────────────────────────────────────────────────────
# 7. THE STAMPING SIDE - the copy that ticked the wrong box
# ─────────────────────────────────────────────────────────────────────────────

def test_an_affirmative_x_no_longer_ticks_the_negative_box():
    """`_resolve_bool_indicator("X")` returned "No"."""
    for v in ("X", "x", "✓", "[X]", "Y", "y", "true", "1", "checked", True):
        assert ps._resolve_bool_indicator(v) == "Yes", v
    for v in ("N", "n", "No", "false", "0", "☐", False):
        assert ps._resolve_bool_indicator(v) == "No", v


@pytest.mark.parametrize("value,checked", [
    ("Yes", True), ("yes", True), ("true", True), ("1", True), ("on", True),
    ("x", True), ("X", True),
    ("Y", True),          # the local tuple was missing "y" - box stayed OFF
    ("✓", True), ("[X]", True), ("Included", True),
    ("No", False), ("N", False), ("false", False), ("0", False),
    ("☐", False), ("Excluded", False), ("banana", False), ("", False),
])
def test_the_checkbox_writer_ticks_on_every_affirmative(value, checked):
    """The real /Btn decision, isolated. Every value that ticked before still
    ticks - this only ever added printings."""
    assert (ps._yes_no_token(value) == "Y") is checked


def test_the_yn_box_gate_leaves_acords_own_printings_untouched():
    """Nothing that works today moves."""
    schema = {"Box_Question_AAACode_A": {"ft": "/Tx",
              'tu': 'Enter Y for a "Yes" response. Input N for "No" response. '
                    'The response to the question, "Does the applicant own autos"?'}}
    for v in ("Y", "N", "Yes", "No", "y", "n"):
        assert ps._yn_gate("Box_Question_AAACode_A", v, schema) == v


def test_the_yn_box_gate_converts_a_mark_to_the_canonical_printing():
    schema = {"Box_Question_AAACode_A": {"ft": "/Tx",
              'tu': 'Enter Y for a "Yes" response. Input N for "No" response. '
                    'The response to the question, "Does the applicant own autos"?'}}
    for v in ("X", "✓", "[X]", "true", "1", "on", "Included"):
        assert ps._yn_gate("Box_Question_AAACode_A", v, schema) == "Yes"
    for v in ("false", "0", "☐", "Excluded"):
        assert ps._yn_gate("Box_Question_AAACode_A", v, schema) == "No"


def test_the_yn_box_gate_still_drops_a_value_that_is_not_an_answer():
    """The gate's original job (2 Sep 2026): a rule that pasted an amount or an
    ISO form number into a Y/N box is dropped so call 2 is ASKED."""
    schema = {"Box_Question_AAACode_A": {"ft": "/Tx",
              'tu': 'Enter Y for a "Yes" response. Input N for "No" response. '
                    'The response to the question, "Does the applicant own autos"?'}}
    for v in ("$2,000,000", "CG 00 01 04 13", "Combined Single Limit"):
        assert ps._yn_gate("Box_Question_AAACode_A", v, schema) is None


def test_the_yn_box_gate_never_touches_a_field_that_is_not_a_yes_no_box():
    schema = {"NamedInsured_FullName_A": {"ft": "/Tx", "tu": "Enter name:"}}
    assert ps._yn_gate("NamedInsured_FullName_A", "X-Ray Imaging LLC",
                       schema) == "X-Ray Imaging LLC"
    # No schema in context -> no opinion, value passes through.
    assert ps._yn_gate("Anything", "X", None) == "X"


def test_the_three_deterministic_writers_share_one_gate():
    """Pass 1, Pass 1.5 and the schedule-row producer each had their own copy
    of the gate sequence. SYS-07 had to add a step to all three, which is when
    three copies become a bug."""
    src = (ROOT / "services" / "pdf_service.py").read_text(encoding="utf-8")
    assert src.count("def _yn_gate(") == 1
    assert "_yn_gate(field_name, result," in src
    assert "_yn_gate(field_name, _v," in src
    alias = (ROOT / "services" / "alias_stamper.py").read_text(encoding="utf-8")
    assert "_ps._yn_gate(" in alias
    assert "_coerce_yn_by_field_concept" not in alias, (
        "the alias stamper must ask the gate, not re-implement it")


# ─────────────────────────────────────────────────────────────────────────────
# 8. THE HUMAN PATH
# ─────────────────────────────────────────────────────────────────────────────

def test_a_producer_who_types_a_mark_on_a_yes_no_question_is_understood():
    from services.answer_semantics import interpret_answer as read, VALUE
    for v in ("X", "x", "✓", "[X]", "1", "true", "checked"):
        r = read("auto_hired_nonowned", v)
        assert r.intent == VALUE and r.value == "Yes", (v, r.intent, r.value)


def test_the_mark_rule_is_gated_on_the_FIELD_not_on_the_value():
    """"1" means one employee on a count box and Yes only on a Yes/No box."""
    from services.answer_semantics import interpret_answer as read, VALUE
    r = read("num_employees", "1")
    assert r.intent == VALUE and str(r.value) == "1"


def test_a_bare_no_keeps_its_existing_meaning():
    """Placed AFTER the absence step on purpose - `_attested_true` and
    `new_venture_answer` depend on today's reading of a bare "No"."""
    from services.answer_semantics import interpret_answer as read, ABSENCE
    assert read("auto_hired_nonowned", "No").intent == ABSENCE


def test_a_client_ticking_a_checkbox_question_with_a_mark_is_recorded():
    """`arq_service` accepted exactly ("Yes","No","true","false") and stored
    NOTHING for anything else - the answer was given and we dropped it."""
    from services.normalization import canonical_yes_no
    for v in ("X", "Y", "1", "✓", "true"):
        assert canonical_yes_no(v) == "Yes"
    src = (ROOT / "services" / "arq_service.py").read_text(encoding="utf-8")
    assert 'raw_val in ("Yes", "No", "true", "false") else None' in src, (
        "the literal tuple survives only as the fail-open fallback")
    assert "canonical_yes_no as _cyn" in src


# ─────────────────────────────────────────────────────────────────────────────
# 9. ANTI-ROT - a ninth private vocabulary has to be a DECISION
# ─────────────────────────────────────────────────────────────────────────────

_YES_PROBE = {"y", "yes", "true", "t", "1", "on", "checked", "x",
              "included", "include"}
_NO_PROBE = {"n", "no", "false", "f", "0", "off", "unchecked",
             "excluded", "exclude"}

# Every combined Yes/No vocabulary that is allowed to exist, and why. Keyed by
# (file, the sorted tokens) so moving one does not silently re-permit another.
_PINNED_VOCABULARIES = {
    # THE OWNER.
    ("normalization.py", ("checked", "false", "no", "true", "unchecked", "yes")),
    # Fail-open fallbacks for the case where `normalization` cannot be imported.
    # Each sits directly under a call to the shared reader.
    ("fact_equivalence.py", ("checked", "false", "no", "true", "unchecked", "yes")),
    ("pdf_service.py", ("0", "1", "false", "n", "no", "off", "on", "true", "x",
                        "y", "yes")),
    # `_yn_gate`'s "ACORD's own printing - leave it alone" test. Not a
    # vocabulary: it is the list of spellings the gate must NOT rewrite.
    ("pdf_service.py", ("n", "no", "y", "yes")),
    # Not a Yes/No reader: values the AI reasons out rather than copying, so a
    # presence check against the document text is meaningless for them.
    ("pdf_service.py", ("false", "n", "n/a", "na", "no", "none", "null", "off",
                        "on", "true", "x", "y", "yes")),
    # COLUMN-SCOPED, and correct as it stands: `_truthy` is only ever asked
    # about the WC officer table's own `include` / `exclude` cells, where a
    # cell reading "Excluded" is an affirmative answer to "is exclude set?".
    # Folding it into the shared vocabulary would invert it.
    ("coverage_evidence.py", ("1", "exclude", "excluded", "include", "included",
                              "on", "true", "x", "y", "yes")),
    # The fail-open fallback under `arq_service`'s call to the shared reader.
    ("arq_service.py", ("false", "no", "true", "yes")),
}

# `fact_registry.py` is exempt as a FILE: its Yes/No literals are inside
# `validate` lambdas, which DECLARE a fact's domain. That declaration is what
# `normalization.declares_yes_no` reads - it is the source of truth this fix
# added, not a rival copy of it.
_EXEMPT_FILES = {"fact_registry.py"}


def _vocabulary_literals():
    for sub in ("services", "utils", "routes"):
        for f in sorted((ROOT / sub).glob("*.py")):
            if f.name in _EXEMPT_FILES:
                continue
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"))
            except SyntaxError:                              # pragma: no cover
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Set, ast.List, ast.Tuple)):
                    continue
                toks = {e.value.strip().lower() for e in node.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)}
                if len(toks) > 25:
                    continue          # a general word list, not a Yes/No table
                if len(toks & _YES_PROBE) >= 2 and len(toks & _NO_PROBE) >= 2:
                    yield f.name, node.lineno, tuple(sorted(toks))


def test_no_module_declares_its_own_yes_no_vocabulary():
    """EIGHT copies of "what counts as affirmative" is how an affirmative X
    came to tick the No box while the comparison layer read the same X as a
    Yes. A ninth must be a decision, not an accident: add it to
    `_PINNED_VOCABULARIES` WITH the reason it cannot use the shared one."""
    offenders = [(name, line, toks) for name, line, toks in _vocabulary_literals()
                 if (name, toks) not in _PINNED_VOCABULARIES]
    assert offenders == [], (
        "A module declares its own Yes/No vocabulary. Use "
        "services.normalization.yes_no_token / canonical_yes_no instead, or "
        f"pin it with its reason: {offenders}")


def test_the_guard_actually_harvests_something():
    """C25's lesson: a coverage test that harvests nothing passes vacuously."""
    found = list(_vocabulary_literals())
    assert len(found) >= 5
    assert any(n == "normalization.py" for n, _, _ in found)


def test_the_vocabulary_tables_have_no_overlap():
    """A token cannot be both. Cheap, and it would be a silent disaster."""
    assert not (norm._YES_TOKENS & norm._NO_TOKENS)
    assert norm._YES_NO_STRONG_WORDS <= (norm._YES_TOKENS | norm._NO_TOKENS)


def test_the_declaration_sources_are_derived_not_hand_listed():
    """`YES_NO_FIELDS` is the override hatch and must stay empty: everything
    real comes from a declaration that already exists, so a Yes/No fact added
    tomorrow is classified correctly with no list to remember."""
    assert norm.YES_NO_FIELDS == frozenset()
    assert len(BOOLEAN_FACT_KEYS) > 40
    assert "inside_city_limits" in BOOLEAN_FACT_KEYS
    assert norm.declares_yes_no("auto_hired_nonowned")       # via the registry
    assert norm.declares_yes_no("inside_city_limits")        # via the schema
    assert norm.yes_no_field_shape("hired_auto_indicator")   # via the key shape
    assert not norm.declares_yes_no("gl_each_occurrence")
    assert not norm.is_yes_no_field("applicant_name")


# ---------------------------------------------------------------------------
# 2026-09-05 - the shapes a REAL scanned / flattened broker document produces.
# Found by an adversarial sweep, not by the client: every one of these was a
# FALSE CONFLICT before this date.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [
    "Covered", "Elected", "Purchased", "Applies", "Provided", "Afforded",
    "Carried", "Granted", "Included",
])
def test_a_declarations_grid_affirmative_reads_as_yes(value):
    """A dec page does not print "Yes". It prints that the coverage is there."""
    assert norm.yes_no_token(value) == "Y"
    assert norm.canonical_yes_no(value) == "Yes"


@pytest.mark.parametrize("value", [
    "Not Covered", "not covered", "No Coverage", "Declined", "Rejected",
    "Waived", "Not Purchased", "Not Elected", "Excluded",
])
def test_a_declarations_grid_negative_reads_as_no(value):
    assert norm.yes_no_token(value) == "N"
    assert norm.canonical_yes_no(value) == "No"


@pytest.mark.parametrize("value", [
    "Not Applicable", "not applicable", "N/A", "None", "Unknown", "TBD",
])
def test_negation_never_turns_a_non_answer_into_a_no(value):
    """CORE PRINCIPLE 3. The negation rule reads "not <affirmative>" as a No,
    which is exactly why "applicable" is NOT in the affirmative vocabulary -
    "Not Applicable" says the question does not apply, and an absence must
    never become a negative."""
    assert norm.yes_no_token(value) is None


@pytest.mark.parametrize("value,expected", [
    ("Hired and Non-Owned Auto Coverage\nX", "Y"),   # two-line table cell
    ("Sprinkler System\nYes", "Y"),
    ("Hired and Non-Owned Auto X", "Y"),             # one space, flattened grid
    ("Sprinkler System Yes", "Y"),
    ("Coverage Excluded", "N"),
])
def test_a_label_divided_by_a_line_break_or_one_space_still_yields_its_answer(value, expected):
    assert norm.yes_no_answer(value) == expected


@pytest.mark.parametrize("value", [
    "Hired Auto Not Covered", "Physical Damage Not Purchased",
    "Employee Benefits Not Elected", "Coverage Never Provided",
])
def test_a_negation_before_the_tail_can_never_be_read_as_a_yes(value):
    """The inversion the single-space separator made reachable. The head ends in
    a negation, so it belongs to the tail - refuse and compare as text."""
    assert norm.yes_no_answer(value) != "Y"


@pytest.mark.parametrize("value", [
    "Not Applicable - X", "Not Applicable = X", "unknown | X", "none - X",
    "N/A: X", "TBD - Yes",
])
def test_a_non_answer_label_is_still_refused_once_it_carries_a_separator(value):
    """REGRESSION, 2026-09-05, caught by this suite's own existing tests.
    Widening the separator to a single space let the greedy head keep the real
    separator ("Not Applicable -"), which is not the string the non-answer table
    holds - so the label escaped every check and the X was read as a Yes on a
    question that does not apply."""
    assert norm.yes_no_answer(value) is None


@pytest.mark.parametrize("value,expected", [
    ("X]", "Y"), ("[X", "Y"), ("Yes)", "Y"), ("(N", "N"),
])
def test_ocr_dropping_half_a_bracket_does_not_lose_the_mark(value, expected):
    assert norm.yes_no_token(value) == expected


@pytest.mark.parametrize("value,expected", [
    ("Y e s", "Y"), ("N o", "N"), ("y e s", "Y"),
])
def test_ocr_letter_spacing_on_a_scan_still_reads(value, expected):
    assert norm.yes_no_token(value) == expected


@pytest.mark.parametrize("value", ["A B C", "I B M", "U S A"])
def test_letter_spacing_does_not_invent_an_answer(value):
    assert norm.yes_no_token(value) is None
