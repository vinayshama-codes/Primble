"""The field's own DESCRIPTION, stamped as its ANSWER - short form.

CLIENT REPORT, ACORD 125 (Orbin), reproduced with their literal values:

    Subsidiary_ParentSubsidiaryRelationshipDescription_A  = "parent company"
    Subsidiary_ParentSubsidiaryRelationshipDescription_B  = "subsidiary"
    CommercialPolicy_JudgementOrLienExplanation_A         = "judgment or lien"
    CancelNonRenew_UnderwritingConditionCorrectedDescription_A =
        "The description of how the underwriting condition that caused the
         policy not to be written..."

None of those came from the document. Each is that field's own ACORD tooltip
read back as the answer. Guard 8 exists for exactly this and caught NONE of
them, for two independent reasons measured 2026-08-12:

  1. `_TOOLTIP_ECHO_MIN_CHARS = 30` skipped anything shorter. "parent company"
     is 14 characters, "judgment or lien" is 16.
  2. The long one WAS over 30 but the check was an exact substring test, and
     the model transposed two words - it wrote "caused the policy NOT TO be
     written", ACORD writes "caused the policy TO NOT be written". No match.
     (ACORD also spells it "judgement"; the model wrote "judgment".)

THE SAFETY ARGUMENT IS THE POINT OF THIS FILE. Loosening an auto-blanking rule
is how real declarations-page data gets deleted, which is worse than the defect.
Three independent constraints keep it safe, and each has a test below:

  * The short path only runs on values THIS RUN'S GAP-FILL MODEL authored.
    A Pass 1 / alias value came from an extracted fact and is never touched.
  * It requires TWO significant tokens. Every false positive found in testing
    was a single word ("Building" in a sublocation-description box) - 19 of
    them, all one token. This is why the client's one-word "subsidiary" is
    deliberately NOT caught: a missed echo is one stray word a broker deletes,
    a false positive is a real value silently deleted.
  * It only reads the tooltip's DEFINITION half. ACORD tooltips frequently
    name valid answers ("Examples include Building, Contents, or Combined
    Building and Contents") and the shipped check was BLANKING those - a real
    deletion on all four rows of ACORD 140's blanket summary, fixed here.
"""
import glob
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                        # noqa: E402

_SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "..", "forms_schemas")


def _schema(form_id):
    with open(os.path.join(_SCHEMA_DIR, f"{form_id}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


# ── The client's literal values ──────────────────────────────────────────────

_CLIENT_ECHOES = [
    ("Subsidiary_ParentSubsidiaryRelationshipDescription_A", "parent company"),
    ("CommercialPolicy_JudgementOrLienExplanation_A", "judgment or lien"),
    ("CancelNonRenew_UnderwritingConditionCorrectedDescription_A",
     "The description of how the underwriting condition that caused the policy "
     "not to be written"),
]


@pytest.mark.parametrize("field,value", _CLIENT_ECHOES)
def test_client_reported_echo_is_blanked(field, value):
    """Replayed with the client's exact strings, not a paraphrase."""
    schema = _schema("ACORD_125")
    mapped = {field: value}
    ps._enforce_post_fill_guards(mapped, schema, {}, gpt_filled_set={field})
    assert mapped[field] is None


def test_the_transposition_that_defeated_the_old_check():
    """"not to be written" vs ACORD's "to not be written" - the value must be
    matched by MEANING-PRESERVING token overlap, not exact substring."""
    field = "CancelNonRenew_UnderwritingConditionCorrectedDescription_A"
    meta = _schema("ACORD_125")[field]
    value = ("The description of how the underwriting condition that caused the "
             "policy not to be written")
    assert "not to be written" in value
    assert "to not be written" in (meta.get("tu") or "")   # they really differ
    assert ps._is_tooltip_echo(value, meta, field, allow_short=True)


def test_acord_spells_it_judgement_and_the_model_wrote_judgment():
    """A one-letter spelling variant must not be an escape hatch."""
    field = "CommercialPolicy_JudgementOrLienExplanation_A"
    meta = _schema("ACORD_125")[field]
    assert "judgement" in (meta.get("tu") or "").lower()
    assert ps._is_tooltip_echo("judgment or lien", meta, field, allow_short=True)


def test_single_word_echo_is_deliberately_not_caught():
    """STANDING DECISION, not an oversight. The client's "subsidiary" is one
    token. Catching single tokens produced 19 false positives on real schemas
    ("Building", "Owner"), and deleting a real value is the worse failure."""
    field = "Subsidiary_ParentSubsidiaryRelationshipDescription_B"
    meta = _schema("ACORD_125")[field]
    assert not ps._is_tooltip_echo("subsidiary", meta, field, allow_short=True)


# ── Safety constraint 1: AI-authored values only ─────────────────────────────

@pytest.mark.parametrize("field,value", [
    ("Subsidiary_ParentSubsidiaryRelationshipDescription_A", "parent company"),
    ("CommercialPolicy_JudgementOrLienExplanation_A", "judgment or lien"),
])
def test_short_path_never_touches_a_deterministic_value(field, value):
    """LOAD-BEARING. A Pass 1 / alias value came from an extracted fact. The
    short path is aggressive enough that it must never reach one."""
    meta = _schema("ACORD_125")[field]
    assert not ps._is_tooltip_echo(value, meta, field, allow_short=False)


def test_allow_short_defaults_off():
    """Any caller that does not opt in keeps the conservative behaviour."""
    field = "Subsidiary_ParentSubsidiaryRelationshipDescription_A"
    meta = _schema("ACORD_125")[field]
    assert not ps._is_tooltip_echo("parent company", meta, field)


# ── Safety constraint 2: two significant tokens ──────────────────────────────

def test_two_token_minimum_is_pinned():
    assert ps._ECHO_SHORT_MIN_SIG_TOKENS == 2


@pytest.mark.parametrize("form_id,field,value", [
    ("ACORD_140", "CommercialStructure_Building_SublocationDescription_A", "Building"),
    ("ACORD_140", "BuildingExposure_RightDescription_A", "Building"),
    ("ACORD_160", "BuildingOccupancy_OccupancyDescription_A", "Building"),
])
def test_single_word_answers_on_narrative_fields_survive(form_id, field, value):
    """Each of these was a MEASURED false positive before the two-token rule -
    real fields on real forms, not hypotheticals. Pinned to the form that
    actually owns them so this can never quietly skip."""
    schema = _schema(form_id)
    assert field in schema, f"{field} vanished from {form_id} - fix the test, not the guard"
    assert not ps._is_tooltip_echo(value, schema[field], field, allow_short=True)


# ── Safety constraint 3: ACORD's example lists are ANSWERS, not the question ──

def test_the_shipped_check_was_deleting_an_acord_example_answer():
    """REGRESSION THIS FIXES. ACORD 140's blanket-summary tooltip literally
    reads "Examples include Building, Contents, or Combined Building and
    Contents" - and the substring check blanked that exact value on all four
    rows. Guard 8 must never touch it again."""
    schema = _schema("ACORD_140")
    fields = [f for f in schema if "BlanketTypeDescription" in f]
    assert fields, "ACORD 140 blanket summary columns not found"
    for field in fields:
        assert not ps._is_tooltip_echo(
            "Combined Building and Contents", schema[field], field, allow_short=True)


def _harvest_example_answers(tooltip):
    """Values ACORD itself names as valid for a field, from that field's own
    tooltip. These are legitimate BY ACORD'S OWN AUTHORITY - flagging one is a
    false positive by definition, not by my opinion."""
    body = ps._TOOLTIP_PREFIX_RE.sub("", tooltip or "")
    cut = ps._TOOLTIP_EXAMPLE_CUT_RE.search(body)
    if not cut:
        return []
    tail = re.split(r"(?<=[.;])\s", body[cut.end():])[0]
    out = []
    for part in re.split(r",|\bor\b|\band\b|/", tail):
        part = part.strip(" .;:\"'()")
        if 2 < len(part) < 60 and not part.lower().startswith(("the ", "a ", "an ")):
            out.append(part)
    return out


def test_zero_false_positives_on_acords_own_stated_answers():
    """THE ADVERSARIAL TEST, and the one that actually constrains the rule. A
    hand-written value list only proves what its author thought of."""
    offenders, harvested = [], 0
    for path in glob.glob(os.path.join(_SCHEMA_DIR, "*_schema.json")):
        with open(path, encoding="utf-8") as fh:
            schema = json.load(fh)
        for field, meta in schema.items():
            if (meta or {}).get("ft") != "/Tx":
                continue
            for answer in _harvest_example_answers((meta or {}).get("tu") or ""):
                harvested += 1
                if ps._is_tooltip_echo(answer, meta, field, allow_short=True):
                    offenders.append(f"{field} <- {answer!r}")
    assert harvested > 300, f"harvest collapsed to {harvested} - the test would pass vacuously"
    assert not offenders, f"{len(offenders)} ACORD-stated answers flagged: {offenders[:5]}"


def test_other_description_fields_are_exempt_from_the_short_path():
    """An `..._OtherDescription` box asks for what the enumerated checkboxes
    MISSED, so its tooltip necessarily recites them ("the risk location if not
    inside nor outside the city limits"). "Inside" there is an answer."""
    schema = _schema("ACORD_125")
    field = "CommercialStructure_RiskLocation_OtherDescription_A"
    assert field in schema, "the field this rule was derived from is gone"
    assert ps._echo_is_other_field(field)
    for value in ("Inside city limits", "Outside city limits"):
        assert not ps._is_tooltip_echo(value, schema[field], field, allow_short=True)


def test_remark_prefixed_field_asking_for_a_form_number_is_not_narrative():
    """`AdditionalRemark_FormIdentifier_A` contains "Remark" but asks for a form
    NUMBER. Narrative status is decided by the LEAF segment, not the whole name."""
    assert not ps._echo_is_narrative_field("AdditionalRemark_FormIdentifier_A")
    assert ps._echo_is_narrative_field("AdditionalRemark_RemarkText_A")


# ── The same defect in the EVIDENCE, not the answer ──────────────────────────
# LIVE RUN 2026-08-12. `evidence_gate KEPT_YES` printed the sentence that ticked
# two boxes on the client's ACORD 125:
#
#   CancelNonRenew_NonPaymentIndicator_A   quote: "for non-payment of premium"
#   AdditionalInterest_Interest_AdditionalInsuredIndicator_A
#                                          quote: "additional insured"
#
# Neither says anything about THIS applicant. Each is the field's own question
# read back. The gate already rejected exclusion clauses, contract language and
# glossary definitions, and had no answer for a quote that is simply the label.
#
# `_is_tooltip_echo` could NOT be reused: it is scoped to VALUES on narrative
# fields with a 30-char floor, and both quotes slip under it (26 and 18 chars,
# on checkbox fields). Measured, not assumed - the first attempt at this fix
# used it and kept both.

def _gate_quote_verdict(form_id, field, quote):
    """Drive the REAL gate and report whether the tick survived."""
    schema = _schema(form_id)
    raw = ("COMMERCIAL POLICY. If we cancel this policy we will mail notice. We "
           "may cancel for non-payment of premium. Blanket additional insured "
           "where required by written contract. Date of Issue: 07/16/2025. "
           "INSURED IS: LLC.\n")
    # EVERY quote under test must actually occur above. A quote absent from the
    # document is blanked by the gate's presence check, NOT by the rule under
    # test - which is how the first version of this fixture "proved" a correct
    # value was rejected when the gate had in fact kept it.
    pre = {"filled_values": {field: "Yes"}, "raw_text_fields": set(),
           "question_grounding": {field: quote}, "model_used": "stub"}
    mapped, _ = ps.map_facts_to_form(
        {"applicant_name": "Orbin Contracting LLC"}, schema,
        form_id=form_id, raw_text=raw, pre_filled_gpt=pre)
    return "BLANKED" if mapped.get(field) is None else "KEPT"


@pytest.mark.parametrize("field,quote", [
    ("CancelNonRenew_NonPaymentIndicator_A", "for non-payment of premium"),
    ("AdditionalInterest_Interest_AdditionalInsuredIndicator_A", "additional insured"),
])
def test_a_quote_that_restates_the_question_is_not_evidence(field, quote):
    """Both are verbatim from the client's live run."""
    assert _gate_quote_verdict("ACORD_125", field, quote) == "BLANKED"


@pytest.mark.parametrize("field,quote", [
    # From the SAME run - these are real and must survive.
    ("Policy_Status_IssueIndicator_A", "Date of Issue: 07/16/2025"),
    ("NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A", "INSURED IS: LLC"),
])
def test_a_quote_carrying_real_data_still_grounds_a_yes(field, quote):
    """THE LOAD-BEARING SIDE. Each carries a token the question does not - a
    date, an entity code - so it is a statement, not a restatement."""
    assert _gate_quote_verdict("ACORD_125", field, quote) == "KEPT"


@pytest.mark.parametrize("quote", [
    "Scrap and used cutting fluid are stored on site and removed by a licensed hauler",
    "The applicant stores acetylene and oxygen cylinders in a locked cage",
    "Prior carrier non-renewed the policy effective 04/2023 for underwriting reasons",
])
def test_genuine_affirmative_evidence_is_untouched(quote):
    """This may only remove quotes that are the question itself."""
    schema = _schema("ACORD_125")
    field = "CommercialPolicy_Question_ABBCode_A"
    meta = schema[field]
    q_toks = ps._echo_tokens(quote)
    d_toks = ps._echo_definition_tokens(meta.get("tu") or "")
    assert not ps._echo_all_tokens_present(q_toks, d_toks)
