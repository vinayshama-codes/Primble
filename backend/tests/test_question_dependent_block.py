"""A compliance question owns the whole block of detail boxes that follows it.

Client report (ACORD 125, Orbin Contracting), page 3 - four separate items:
  "Delete the fire-code occurrence date 07/15/2025."
  "Delete both bankruptcy boilerplate explanations."
  "Delete 'judgment or lien'."
  "The policy's bankruptcy language is a contract condition - not evidence of an
   actual bankruptcy."

Every one of those questions was answered "N", and Guard 5 ("an Explanation whose
paired Question is not Yes is answering a question that was never asked - blank
it") already existed and should have caught them. It never fired, because
`_question_explanation_pairs` requires STRICT IMMEDIATE adjacency and ACORD puts
an OccurrenceDate box between the question and its Explanation:

    CommercialPolicy_Question_KALCode_A                        <- the question
    CommercialPolicy_JudgementOrLien_OccurrenceDate_A          <- +1, blocks pairing
    CommercialPolicy_JudgementOrLienExplanation_A              <- +2, the explanation
    CommercialPolicy_JudgementOrLien_ResolutionDescription_A
    CommercialPolicy_JudgementOrLien_ResolutionDate_A

So the fix is not a new guard - it is making two existing, working guards
reachable for these fields.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                        # noqa: E402

_SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "..", "forms_schemas")


def _schema(form_id):
    with open(os.path.join(_SCHEMA_DIR, f"{form_id}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


Q_FIRE = "CommercialPolicy_Question_AAFCode_A"
Q_BANKRUPTCY = "CommercialPolicy_Question_KAKCode_A"
Q_JUDGMENT = "CommercialPolicy_Question_KALCode_A"


@pytest.mark.parametrize("question,explanation", [
    (Q_FIRE, "CommercialPolicy_UncorrectedFireCodeViolationExplanation_A"),
    (Q_BANKRUPTCY, "CommercialPolicy_ForeclosureRepossessionBankruptcyExplanation_A"),
    (Q_JUDGMENT, "CommercialPolicy_JudgementOrLienExplanation_A"),
])
def test_the_three_unpaired_questions_are_now_paired(question, explanation):
    pairs = ps._question_explanation_pairs(_schema("ACORD_125"))
    assert pairs.get(question) == explanation


def test_client_page_three_boilerplate_is_blanked():
    """THE CLIENT'S CASE, verbatim. Every question answered "N"; every dependent
    box filled with policy boilerplate."""
    schema = _schema("ACORD_125")
    mapped = {
        Q_FIRE: "N",
        "CommercialPolicy_UncorrectedFireCodeViolation_OccurrenceDate_A": "07/15/2025",
        Q_BANKRUPTCY: "N",
        "CommercialPolicy_ForeclosureRepossessionBankruptcyExplanation_A":
            "Bankruptcy or insolvency of the insured or of the insured's estate "
            "will not relieve us of our obligations",
        "CommercialPolicy_ForeclosureRepossessionBankruptcyExplanation_B":
            'Bankruptcy or insolvency of the "underlying insurer" will not relieve us',
        Q_JUDGMENT: "N",
        "CommercialPolicy_JudgementOrLienExplanation_A": "judgment or lien",
    }
    ps._enforce_post_fill_guards(mapped, schema, {})
    for field in list(mapped):
        if field.endswith("Code_A"):
            continue
        assert mapped[field] is None, f"{field} survived with {mapped[field]!r}"


def test_a_genuine_yes_keeps_its_explanation():
    """The guards must only strip detail that has no question behind it. A real
    "Y" keeps everything - this fix may not cost a legitimate fill."""
    schema = _schema("ACORD_125")
    mapped = {
        Q_JUDGMENT: "Y",
        "CommercialPolicy_JudgementOrLienExplanation_A":
            "Mechanic's lien filed by subcontractor, released March 2024",
        "CommercialPolicy_JudgementOrLien_OccurrenceDate_A": "03/01/2024",
    }
    ps._enforce_post_fill_guards(mapped, schema, {})
    assert mapped["CommercialPolicy_JudgementOrLienExplanation_A"]
    assert mapped["CommercialPolicy_JudgementOrLien_OccurrenceDate_A"] == "03/01/2024"


def test_a_blank_question_also_strips_its_dependents():
    """Guard 6's rule, now reaching these fields: a detail box has no standalone
    meaning when its parent question was never answered."""
    schema = _schema("ACORD_125")
    mapped = {
        Q_BANKRUPTCY: "",
        "CommercialPolicy_ForeclosureRepossessionBankruptcyExplanation_A": "boilerplate",
    }
    ps._enforce_post_fill_guards(mapped, schema, {})
    assert mapped["CommercialPolicy_ForeclosureRepossessionBankruptcyExplanation_A"] is None


# ── The detector's precision is the whole safety argument ────────────────────

def test_exactly_three_questions_qualify_across_all_seventeen_forms():
    """STANDING GUARD on blast radius.

    Requiring TWO OR MORE consecutive same-stem fields is what makes this safe -
    single-field adjacency has documented coincidences (`_PAIRING_EXCLUDED`),
    several consecutive unrelated fields sharing one stem does not happen.
    Measured: exactly three questions qualify, all on ACORD 125, and all three
    are client-reported defects. If a schema change makes this number jump,
    review every new pair by hand before accepting it.
    """
    found = {}
    for name in sorted(os.listdir(_SCHEMA_DIR)):
        if not name.endswith("_schema.json"):
            continue
        form_id = name.replace("_schema.json", "")
        block = ps._question_dependent_block(_schema(form_id))
        if block:
            found[form_id] = sorted(block)
    assert found == {"ACORD_125": [Q_FIRE, Q_BANKRUPTCY, Q_JUDGMENT]}, found


def test_a_single_following_field_is_not_a_block():
    """One neighbour is adjacency, which the primary check already handles and
    which has real false positives. Two is a block."""
    schema = {
        "X_Question_AAACode_A": {"ft": "/Tx"},
        "X_SomeThingExplanation_A": {"ft": "/Tx"},
        "Y_Unrelated_A": {"ft": "/Tx"},
    }
    assert ps._question_dependent_block(schema) == {}


def test_the_run_stops_at_a_non_dependent_field():
    schema = {
        "X_Question_AAACode_A": {"ft": "/Tx"},
        "X_Thing_OccurrenceDate_A": {"ft": "/Tx"},
        "X_ThingExplanation_A": {"ft": "/Tx"},
        "X_TotallyDifferentField_A": {"ft": "/Tx"},   # not dependent-shaped
        "X_Thing_ResolutionDate_A": {"ft": "/Tx"},
    }
    block = ps._question_dependent_block(schema)
    assert block == {"X_Question_AAACode_A": (
        "X_Thing_OccurrenceDate_A", "X_ThingExplanation_A")}


def test_the_run_stops_when_the_stem_changes():
    schema = {
        "X_Question_AAACode_A": {"ft": "/Tx"},
        "X_Alpha_OccurrenceDate_A": {"ft": "/Tx"},
        "X_AlphaExplanation_A": {"ft": "/Tx"},
        "X_Beta_OccurrenceDate_A": {"ft": "/Tx"},     # different stem
    }
    assert ps._question_dependent_block(schema)["X_Question_AAACode_A"] == (
        "X_Alpha_OccurrenceDate_A", "X_AlphaExplanation_A")


def test_stem_handles_acords_inconsistent_separator():
    """`JudgementOrLien_OccurrenceDate` has an underscore before the suffix and
    `JudgementOrLienExplanation` does not. An earlier version keyed on the
    underscore, missed all three real cases, and produced two unrelated pairs
    instead."""
    assert ps._dependent_stem("CommercialPolicy_JudgementOrLien_OccurrenceDate_A") == \
        ps._dependent_stem("CommercialPolicy_JudgementOrLienExplanation_A")
    # A field that is not dependent-shaped ends a run.
    assert ps._dependent_stem("NamedInsured_FullName_A") == ""


def test_existing_pairs_are_preserved():
    """The new fallback is additive - it must not displace anything the
    adjacency check already found."""
    schema = _schema("ACORD_125")
    pairs = ps._question_explanation_pairs(schema)
    assert len(pairs) >= 30
    # A pair the ORIGINAL adjacency rule produced must still be present.
    keys = list(schema)
    adjacent = {
        k: keys[i + 1] for i, k in enumerate(keys[:-1])
        if ps._QUESTION_CODE_RE.search(k)
        and any(t in keys[i + 1] for t in ps._EVIDENCE_REQUIRED_TOKENS)
    }
    assert adjacent, "harvest found no adjacency pairs - the schema changed"
    for q, exp in adjacent.items():
        assert pairs.get(q) == exp, f"{q} lost its original pairing"
