"""Adversarial review of Lane B, 27 Oct 2026 (25sepChanges.md Z44-B-R).

Each test was written failing first against the Lane B tree.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("FIELD_ENCRYPTION_KEY", "kZ0aQ7Yy3pR8mN2vB6xL9tJ4hG1sD5fW8cE0uI3oA7k=")

from services.answer_semantics import (  # noqa: E402
    ABSENCE, NOT_APPLICABLE, UNKNOWN, VALUE, interpret_answer, name_answer_refusal,
)

# ══ R1. A company's name that opens with an absence word is a name ═══════════
# "No Limits Roofing LLC" for the applicant was REFUSED ("cannot be absent"),
# and for the DBA / contact / prior carrier / holder it was stored as "there is
# none" - in the editor that CLEARED the fact the producer had just typed.
_NAMES = ["None Such LLC", "No Limits Roofing LLC", "Nothing But Noodles", "Zero Gravity Inc",
          "Never Again Ltd", "Nil Corp", "Mr. None", "No. 1 Pizza Co", "No Frills Inc",
          "Nothing Bundt Cakes", "None Such", "Nada Moo LLC", "No Name Bar"]
_NAME_FACTS = ["applicant_name", "dba_name", "contact_name", "prior_carrier",
               "certificate_holder_name", "landlord_name", "carrier_name"]


@pytest.mark.parametrize("fact", _NAME_FACTS)
@pytest.mark.parametrize("name", _NAMES)
def test_r1_a_name_opening_with_an_absence_word_is_a_name(fact, name):
    got = interpret_answer(fact, name)
    assert got.intent == VALUE and got.value == name, (fact, name, got)
    assert name_answer_refusal(fact, name) == ""


@pytest.mark.parametrize("name", ["Unknown Pleasures LLC", "TBD Construction LLC",
                                  "N/A Holdings Inc", "Not Applicable Inc", "Later Days Co"])
def test_r1_a_name_closed_by_a_legal_form_is_a_name(name):
    for fact in ("applicant_name", "dba_name", "prior_carrier"):
        got = interpret_answer(fact, name)
        assert got.intent == VALUE and got.value == name, (fact, name, got)


@pytest.mark.parametrize("text", ["None", "none.", "None at this time", "None currently",
                                  "Nothing yet", "No DBA", "none known", "No contact",
                                  "None - not applicable", "no prior carrier", "None so far",
                                  "N/A", "  N / A ", "not applicable"])
def test_r1_optional_name_absences_still_read_as_absences(text):
    fact = {"No DBA": "dba_name", "No contact": "contact_name",
            "no prior carrier": "prior_carrier"}.get(text, "dba_name")
    got = interpret_answer(fact, text)
    assert got.intent in (ABSENCE, NOT_APPLICABLE), (fact, text, got)


@pytest.mark.parametrize("text", ["none.", "  N / A ", "same as above!", "TBD - will send",
                                  "None at this time", "Same as the named insured.", "F.I.O.",
                                  "owner", "unknown"])
def test_r1_required_name_non_answers_still_refused(text):
    assert not interpret_answer("applicant_name", text).accepted


def test_r1_non_name_facts_unchanged():
    # The name rule must not leak into ordinary facts: their short-answer
    # absence reading is exactly as before.
    for fact in ("prior_losses_description", "num_employees_text", "wc_prior_carrier_reason"):
        assert interpret_answer(fact, "None at this time").intent == ABSENCE
        assert interpret_answer(fact, "None such here").intent == ABSENCE


# ══ R2. A subtotal row inside an officer table is not the next table ═════════
# `_starts_another_table` (Lane B 4b) read "| SUBTOTAL | | |" - one word, no
# digit, no officer title - as the next table's header, so the officers after
# it lost their titles (HEAD found "Vice President").
@pytest.mark.parametrize("text,expected", [
    ("| NAME | TITLE | OWN % |\n|---|---|---|\n| Jane Roe | President | 60% |\n"
     "| SUBTOTAL | | |\n| Marcus Ruiz | Vice President | 40% |", {"Vice President"}),
    ("NAME | TITLE | OWNERSHIP\nJane Roe | President | 60%\nPartners | |\n"
     "Marcus Ruiz | Treasurer | 40%", {"Treasurer"}),
    # Lane B's own cases still end the table
    ("NAME | TITLE | OWNERSHIP\nJane Roe | President | 60%\nCONTACT | ROLE | PHONE\n"
     "Marcus Ruiz | Secretary | 303-555-0100", set()),
    ("NAME | TITLE | OWNERSHIP\nJane Roe | President | 60%\nLOCATION | CITY | STATE\n"
     "Marcus Ruiz | Denver | CO", set()),
])
def test_r2_a_break_row_inside_the_officer_table_keeps_the_table(text, expected):
    from services.extraction_service import _titles_printed_for
    assert _titles_printed_for("Marcus Ruiz", [{"text": text}]) == expected


# ══ R3. A line that only USES the word "insured" names no insured ═════════════
# `_names_the_insured` (Lane B 4d) took any "insured" / "applicant" word as the
# insured's line, so a carrier's letterhead over "Insured: see schedule" or an
# "Applicant Information" heading over "Home Office: <carrier's address>" kept
# the carrier's home office as the insured's address (HEAD refused it).
_CARRIER_ADDR = "671 S High St, Columbus OH 43215"


@pytest.mark.parametrize("between,own,expected", [
    ("Insured: see schedule", ["Choice Electric LLC"], True),
    ("Applicant Information", ["Choice Electric LLC"], True),
    ("Insured: see schedule", [], True),
    ("Applicant Information", [], True),
    # Lane B's own cases: the insured NAMED between them - its own home office
    ("Named Insured: Choice Electric LLC", ["Choice Electric LLC"], False),
    ("CHOICE ELECTRIC LLC", ["Choice Electric LLC"], False),
    ("Named Insured: Choice Electric LLC", [], False),
])
def test_r3_only_a_named_insured_owns_the_home_office_below_a_carrier(between, own, expected):
    from services.insured_scope import address_is_a_party_office
    text = f"GRANGE MUTUAL CASUALTY COMPANY\n{between}\nHome Office: {_CARRIER_ADDR}"
    assert address_is_a_party_office(_CARRIER_ADDR, [text], own_names=own) is expected
