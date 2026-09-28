"""A125 kit, test 2 (21 Sep 2026) - the complete fix.

ADVERSARIAL CASES ARE WRITTEN FIRST IN EVERY SECTION (D22). Each fix here can
do damage by over-reaching, and the case that proves it does not is the one
that matters - a fixture easier than reality proves nothing.

Root causes closed:
  RC-B  a placeholder reaching a printed box              (Guard 13)
  RC-A  a single-entity fact model against N-row tables   (per-entity resolvers)
  RC-C  no deterministic floor under compliance questions (disclosure answers)
  RC-D  one narrative fact, two distinct ACORD boxes
  RC-E  a code the document never states                  (country owned blank)
  RC-G  an abbreviated table header with no lexical bridge
"""
from __future__ import annotations

import glob
import json
import os
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
SCHEMA_DIR = BACKEND / "forms_schemas"


@pytest.fixture(scope="module")
def ps():
    import services.pdf_service as _ps
    return _ps


@pytest.fixture(scope="module")
def a125():
    return json.loads((SCHEMA_DIR / "ACORD_125_schema.json").read_text())


@pytest.fixture
def schema_ctx(ps, a125):
    ps._set_schema_context(a125)
    yield a125
    ps._set_schema_context(None)


def _all_schemas():
    for p in sorted(glob.glob(str(SCHEMA_DIR / "*_schema.json"))):
        yield os.path.basename(p).replace("_schema.json", ""), json.loads(Path(p).read_text())


# ═══════════════════════════════════════════════════════════════════════════
# RC-B - a placeholder is not a value
# ═══════════════════════════════════════════════════════════════════════════

# THE ADVERSARIAL SET. Every one of these is a value a broker signs, and every
# one is the kind of thing a too-eager absence rule deletes. "$0" reserved on a
# claim, "0" square feet open to the public and "N" on a Y/N question were all
# on the live form this fix came from.
_MUST_SURVIVE = [
    "0", "zero", "$0", "0.00", "N", "No", "n", "OR", "US", "1", "A", "S",
    "Statutory", "Included", "See schedule", "see attached", "pending",
    "not required", "None of the buildings are sprinklered",
    "No losses in the last five years", "2250 NW Vaughn St",
    "Meridian Ironworks & Mechanical, LLC", "93-2841760",
    "-5", "$", "%", "#1",
]


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_whitespace_is_blank_not_a_placeholder(value):
    """The branch the dash fix split: an EMPTY value is not this door's
    business (the caller already treats it as blank)."""
    from services.answer_semantics import is_placeholder_text
    assert is_placeholder_text(value) is False
_MUST_BLANK = [
    "(None)", "None", "none", "NONE", "[N/A]", '"unknown"', "- none -",
    "N/A", "n/a", "n / a", "n.a.", "NA", "TBD", "t.b.d", "to be determined",
    "not provided", "NOT STATED", "not specified", "null", "nil",
    "  (none)  ", "no data", "unknown", "not available", "none known",
    # 28 Sep (FR125 kit): pure decoration is a printed "nothing here"
    "--", "-", "\u2014", "\u2013", "---", "- -", "...", "()", "[ ]",
]


@pytest.mark.parametrize("value", _MUST_SURVIVE)
def test_a_real_value_is_never_read_as_a_placeholder(value):
    """ADVERSARIAL, AND THE WHOLE POINT. `answer_semantics._ABSENCE_TOKENS`
    contains "0", "zero", "no" and "n" because it reads a HUMAN's answer to a
    known fact. Reusing it on a form box would delete a $0 reserve and every
    "N" on the form."""
    from services.answer_semantics import is_placeholder_text
    assert is_placeholder_text(value) is False, value


@pytest.mark.parametrize("value", _MUST_BLANK)
def test_a_placeholder_is_recognised_through_its_decoration(value):
    from services.answer_semantics import is_placeholder_text
    assert is_placeholder_text(value) is True, value


def test_guard_13_blanks_the_live_defect_and_spares_the_live_values(ps, a125):
    """The exact boxes from the 21 Sep run, graded together."""
    mapped = {
        "NamedInsured_MailingAddress_LineTwo_B": "(None)",
        "NamedInsured_MailingAddress_LineTwo_C": "(None)",
        "NamedInsured_MailingAddress_LineOne_B": "811 SE Ironwood Ct",
        "LossHistory_ReservedAmount_A": "$0",
        "LossHistory_ReservedAmount_C": "$0",
        "BuildingOccupancy_OpenToPublicArea_B": "0",
        "LossHistory_ClaimStatus_OpenCode_A": "N",
        "LossHistory_ClaimStatus_SubrogationCode_C": "Y",
        "Policy_Audit_FrequencyCode_A": "A",
        "NamedInsured_FullName_C": "Tualatin Valley Mechanical Services, LLC",
    }
    ps._enforce_post_fill_guards(mapped, a125, {}, set())
    assert mapped["NamedInsured_MailingAddress_LineTwo_B"] is None
    assert mapped["NamedInsured_MailingAddress_LineTwo_C"] is None
    assert mapped["NamedInsured_MailingAddress_LineOne_B"] == "811 SE Ironwood Ct"
    assert mapped["LossHistory_ReservedAmount_A"] == "$0"
    assert mapped["LossHistory_ReservedAmount_C"] == "$0"
    assert mapped["BuildingOccupancy_OpenToPublicArea_B"] == "0"
    assert mapped["LossHistory_ClaimStatus_OpenCode_A"] == "N"
    assert mapped["Policy_Audit_FrequencyCode_A"] == "A"
    assert mapped["NamedInsured_FullName_C"].startswith("Tualatin")


def test_the_placeholder_vocabulary_has_exactly_one_home():
    """ANTI-ROT. Two copies of one rule is how this file's history of
    duplicated-rule defects started.

    pdf_service DOES keep `_LLM_EMPTY_SENTINELS`, and that is not the
    duplication being guarded against - it predates this work, it is consulted
    at absorb time, and it carries template-placeholder concerns this door has
    no opinion on. What must never happen is a SECOND decoration-aware
    vocabulary growing inside the new guard. The guard calls the door.

    (This test earned its keep on its first run: it is what surfaced
    `_LLM_EMPTY_SENTINELS`, which turned out to be the door that SHOULD have
    caught "(None)" and did not, because its membership test is a bare exact
    match. That is now fixed at the source rather than only backstopped.)"""
    src = (BACKEND / "services" / "pdf_service.py").read_text()
    assert src.count("from services.answer_semantics import is_placeholder_text") == 2, (
        "both the absorb-time door and Guard 13 must delegate to answer_semantics")
    start = src.index("Guard 13: a placeholder is not a value")
    block = src[start:src.index('Guard 9: a "Yes" may not stand', start)].lower()
    for token in ("to be determined", "not provided", "none known", "n.a.", "tbd"):
        assert token not in block, (
            f"Guard 13 has grown its own copy of the placeholder vocabulary "
            f"({token!r}) - it belongs in answer_semantics")


def test_the_decoration_hole_is_closed_at_the_source_not_only_backstopped():
    """The absorb-time door is where "(None)" should have died. Guard 13 is the
    backstop for values that arrive by another path (Pass 1, the alias
    stamper), not the only line of defence."""
    import services.pdf_service as ps
    for value in ("(None)", "- none -", '"unknown"', "n / a", "[N/A]"):
        assert ps._is_empty_llm_value(value) is True, value
    for value in ("0", "N", "No", "$0", "OR", "US", "Statutory", "See schedule"):
        assert ps._is_empty_llm_value(value) is False, value


def test_guard_13_runs_before_the_naked_yes_guard():
    """POSITION IS LOAD-BEARING. An affirmative whose explanation turns out to
    be a placeholder must be blanked with it, not shipped as a naked Yes."""
    src = (BACKEND / "services" / "pdf_service.py").read_text()
    assert src.index("Guard 13: a placeholder is not a value") < \
        src.index('Guard 9: a "Yes" may not stand without its explanation')


# ═══════════════════════════════════════════════════════════════════════════
# RC-A - a single-entity fact model against N-row ACORD tables
# ═══════════════════════════════════════════════════════════════════════════

def test_a_package_level_website_no_longer_broadcasts_across_the_table(ps):
    """THE LIVE DEFECT. One scalar returned for every row letter, then Guard 2
    deleted B and C as echoes of A - so the SECOND insured's website printed on
    the FIRST insured's row and the right box stayed empty."""
    facts = {"applicant_website": "www.cedarbluffsteel.com"}
    assert ps._resolve_applicant_website(
        "NamedInsured_Primary_WebsiteAddress_A", facts) == "www.cedarbluffsteel.com"
    for row in "BCDEN":
        assert ps._resolve_applicant_website(
            f"NamedInsured_Primary_WebsiteAddress_{row}", facts) is ps._SCHED_SKIP


def test_an_old_session_with_no_detail_fact_is_left_exactly_as_it_is(ps):
    """ADVERSARIAL, AND THE REASON _SCHEDULE_REGISTRY WAS THE WRONG DOOR.
    `_resolve_schedule_row_inner` returns an owned blank when its list fact is
    missing, which would have darkened every one of these boxes on every
    session extracted before v22 - including the ones gap fill gets RIGHT
    (test 2 filled row B's FEIN, SIC and NAICS from call 2 alone)."""
    for field in ("NamedInsured_TaxIdentifier_B", "NamedInsured_SICCode_C",
                  "NamedInsured_Primary_WebsiteAddress_B",
                  "NamedInsured_MailingAddress_CityName_B"):
        assert ps._resolve_named_insured_detail(field, {}) is ps._SCHED_SKIP, field
    assert ps._resolve_contact_detail(
        "NamedInsured_Contact_FullName_B", {}) is ps._SCHED_SKIP
    assert ps._resolve_additional_interest_detail(
        "AdditionalInterest_FullName_A", {}) is ps._SCHED_SKIP
    assert ps._resolve_organization_relationship(
        "BusinessInformation_ParentOrganizationName_A", {}) is ps._SCHED_SKIP
    assert ps._resolve_safety_program_element(
        "CommercialPolicy_FormalSafetyProgram_OSHAIndicator_B", {}) is ps._SCHED_SKIP


def test_each_named_insured_row_carries_its_own_entitys_values(ps):
    # The ROSTER is required: since 22 Sep a detail row is matched to the entity
    # whose NAME the row prints, not to the row's ordinal. Without a roster the
    # resolver cannot say whose row this is and steps aside - pinned by
    # `test_no_roster_means_the_resolver_steps_aside`.
    facts = {"additional_named_insureds": [
        "Cedar Bluff Steel Fabricators, Inc.",
        "Tualatin Valley Mechanical Services, LLC"],
        "named_insured_details": [
        {"name": "Cedar Bluff Steel Fabricators, Inc.", "fein": "26-0459318",
         "sic": "3441", "naics": "332312", "website": "www.cedarbluffsteel.com",
         "city": "Gresham", "postal_code": "97030"},
        {"name": "Tualatin Valley Mechanical Services, LLC",
         "fein": "47-3318805", "city": "Tigard"},
    ]}
    assert ps._resolve_named_insured_detail("NamedInsured_TaxIdentifier_B", facts) == "26-0459318"
    assert ps._resolve_named_insured_detail("NamedInsured_TaxIdentifier_C", facts) == "47-3318805"
    assert ps._resolve_named_insured_detail("NamedInsured_SICCode_B", facts) == "3441"
    assert ps._resolve_named_insured_detail(
        "NamedInsured_Primary_WebsiteAddress_B", facts) == "www.cedarbluffsteel.com"
    # row C states no SIC - the fact exists and says so, so the box is blank
    assert ps._resolve_named_insured_detail("NamedInsured_SICCode_C", facts) is None
    # row D is past the end of the roster
    assert ps._resolve_named_insured_detail("NamedInsured_TaxIdentifier_D", facts) is None


def test_row_a_is_never_taken_from_the_other_insureds_list(ps):
    """ADVERSARIAL. Row A is the applicant and keeps its own scalars. If this
    resolver ever claimed row A, entry 1 (the SECOND insured) would be stamped
    onto the FIRST insured's row - the very defect being fixed, inverted."""
    facts = {"named_insured_details": [{"name": "Cedar Bluff", "fein": "26-0459318"}]}
    for base in ("NamedInsured_TaxIdentifier", "NamedInsured_SICCode",
                 "NamedInsured_MailingAddress_CityName"):
        assert ps._resolve_named_insured_detail(f"{base}_A", facts) is ps._SCHED_SKIP


def test_the_second_contact_gets_its_own_block(ps):
    """The live run printed the SECOND contact's phone in the FIRST contact's
    SECONDARY box, because that box had no fact and gap fill filled it with the
    next number it could see."""
    facts = {"applicant_contacts": [
        {"contact_type": "Inspection", "name": "Rosalind Achterberg",
         "phone": "(503) 555-0156", "email": "rachterberg@meridianiw.com"},
        {"contact_type": "Accounting", "name": "Wendell Pardoe",
         "phone": "(503) 555-0193"},
    ]}
    assert ps._resolve_contact_detail("NamedInsured_Contact_FullName_A", facts) == "Rosalind Achterberg"
    assert ps._resolve_contact_detail("NamedInsured_Contact_FullName_B", facts) == "Wendell Pardoe"
    assert ps._resolve_contact_detail("NamedInsured_Contact_PrimaryPhoneNumber_B", facts) == "(503) 555-0193"
    assert ps._resolve_contact_detail("NamedInsured_Contact_ContactDescription_B", facts) == "Accounting"
    # THE VIOLATION: contact A states no secondary number, so the box is blank
    assert ps._resolve_contact_detail("NamedInsured_Contact_SecondaryPhoneNumber_A", facts) is None


def test_a_second_additional_interest_can_reach_the_form(ps):
    """CORRECTED 28 Sep 2026. On ACORD 125 `AdditionalInterest_FullName_B` is
    NOT a second interest - its tooltip reads "As used here, this is the name
    of the trust" (question 11). This test asserted the Vaughn Street mortgagee
    there, the same misreading the A125 kit key carried; it passed only while no
    schema was in context. The second interest reaches the form where ACORD
    prints a second interest row - ACORD 127."""
    facts = {"additional_interests": [
        {"name": "Ironbridge Capital Leasing Corporation",
         "interest_reason": "Equipment finance agreement", "rank": "1",
         "lien_amount": "$412,000", "item_description": "Fabrication equipment"},
        {"name": "Vaughn Street Holdings LP", "interest_type": "Mortgagee"},
    ]}
    assert ps._resolve_additional_interest_detail(
        "AdditionalInterest_FullName_A", facts).startswith("Ironbridge")
    assert ps._resolve_additional_interest_detail(
        "AdditionalInterest_FullName_B", dict(facts, _form_id="ACORD_127")) == \
        "Vaughn Street Holdings LP"
    assert ps._resolve_additional_interest_detail(
        "AdditionalInterest_FullName_B", dict(facts, _form_id="ACORD_125")) is ps._SCHED_SKIP
    assert ps._resolve_additional_interest_detail(
        "AdditionalInterest_InterestReasonDescription_A", facts) == "Equipment finance agreement"
    assert ps._resolve_additional_interest_detail(
        "AdditionalInterest_FullName_C", facts) is None


# ═══════════════════════════════════════════════════════════════════════════
# RC-E - a code the document never states
# ═══════════════════════════════════════════════════════════════════════════

def test_a_country_the_document_never_names_is_an_owned_blank(ps):
    """The live run printed "US" on a package that names no country anywhere.
    It is CORRECT, which is what makes the class dangerous - the same
    mechanism supplies a plausible NAIC and a plausible class code."""
    assert ps._resolve_additional_interest_detail(
        "AdditionalInterest_MailingAddress_CountryCode_A", {}) is None
    assert ps._resolve_additional_interest_detail(
        "AdditionalInterest_MailingAddress_CountryCode_A",
        {"additional_interests": [{"name": "X"}]}) is None
    # ...but a STATED country still prints
    assert ps._resolve_additional_interest_detail(
        "AdditionalInterest_MailingAddress_CountryCode_A",
        {"additional_interests": [{"name": "X", "country": "CA"}]}) == "CA"


def test_the_country_blank_does_not_leak_into_the_other_columns(ps):
    """ADVERSARIAL. The unconditional blank is scoped to COUNTRY alone; every
    other column must still SKIP when there is no fact, or an old session loses
    boxes gap fill fills today."""
    for base in ("AdditionalInterest_FullName",
                 "AdditionalInterest_MailingAddress_StateOrProvinceCode",
                 "AdditionalInterest_MailingAddress_PostalCode",
                 "AdditionalInterest_LoanAmount"):
        assert ps._resolve_additional_interest_detail(f"{base}_A", {}) is ps._SCHED_SKIP, base


def test_every_country_box_in_the_product_is_covered_by_this_resolver():
    """The unconditional blank is only defensible because NOTHING else can
    fill these. If a future schema adds a country box on another family, this
    fails and the reasoning gets revisited."""
    found = []
    for form, schema in _all_schemas():
        for field in schema:
            if "CountryCode" in field:
                found.append((form, field))
    assert found, "no country boxes at all - the sweep is broken"
    for form, field in found:
        assert field.startswith("AdditionalInterest_"), (form, field)


# ═══════════════════════════════════════════════════════════════════════════
# RC-A4 / safety - ACORD's own row mapping
# ═══════════════════════════════════════════════════════════════════════════

def test_a_parent_only_fact_never_fills_the_subsidiary_block(ps):
    """ADVERSARIAL, AND I GOT THIS BACKWARDS ONCE ALREADY. Row A is the PARENT
    block (question 1a) and row B is the SUBSIDIARY block (1b) - except for the
    subsidiary's NAME, which ACORD puts at _A. Quoted from the tooltips."""
    facts = {"organization_relationships": [
        {"role": "parent", "name": "Harbor Line Capital Partners, LLC",
         "relationship_description": "Majority member since 03/2019",
         "percent_owned": "65%"}]}
    assert ps._resolve_organization_relationship(
        "BusinessInformation_ParentOrganizationName_A", facts) == "Harbor Line Capital Partners, LLC"
    assert ps._resolve_organization_relationship(
        "Subsidiary_ParentOwnershipPercent_A", facts) == "65%"
    # THE ADVERSARIAL HALF: the applicant has no subsidiaries, so 1b is blank
    assert ps._resolve_organization_relationship("Subsidiary_OrganizationName_A", facts) is None
    assert ps._resolve_organization_relationship("Subsidiary_ParentOwnershipPercent_B", facts) is None


def test_the_row_mapping_matches_acords_own_tooltips(a125):
    """The mapping is quoted, not inferred from the field names."""
    assert "parent organization" in a125["BusinessInformation_ParentOrganizationName_A"]["tu"].lower()
    assert "subsidiary of the company" in a125["Subsidiary_OrganizationName_A"]["tu"].lower()


def test_only_the_safety_elements_the_document_names_are_ticked(ps):
    facts = {"safety_program_elements": ["Safety Manual", "Monthly Meetings"]}
    r = ps._resolve_safety_program_element
    assert r("CommercialPolicy_FormalSafetyProgram_SafetyManualIndicator_A", facts) == "Y"
    assert r("CommercialPolicy_FormalSafetyProgram_MonthlyMeetingsIndicator_B", facts) == "Y"
    assert r("CommercialPolicy_FormalSafetyProgram_SafetyPositionIndicator_B", facts) is None
    assert r("CommercialPolicy_FormalSafetyProgram_OSHAIndicator_B", facts) is None


def test_a_programme_with_no_element_named_ticks_nothing(ps):
    """ADVERSARIAL. An EMPTY list is an answer - "there is a programme, the
    document does not say what is in it" - and must not be read as an absence
    that lets gap fill guess, nor as a reason to tick anything."""
    facts = {"safety_program_elements": []}
    for f in ("SafetyManualIndicator_A", "SafetyPositionIndicator_B",
              "MonthlyMeetingsIndicator_B", "OSHAIndicator_B"):
        assert ps._resolve_safety_program_element(
            f"CommercialPolicy_FormalSafetyProgram_{f}", facts) is None


# ═══════════════════════════════════════════════════════════════════════════
# RC-D - one narrative fact, two distinct ACORD boxes
# ═══════════════════════════════════════════════════════════════════════════

def test_the_other_named_insureds_narrative_has_its_own_fact(ps):
    facts = {"additional_named_insureds": ["Cedar Bluff", "Tualatin Valley"],
             "other_named_insured_operations": "Cedar Bluff performs shop fabrication."}
    assert ps._resolve_other_named_insured_operations(
        "CommercialPolicy_OperationsDescription_B", facts) == "Cedar Bluff performs shop fabrication."


def test_row_b_is_left_to_the_party_scoped_guard_when_there_is_no_other_insured(ps):
    """ADVERSARIAL. `_resolve_party_scoped_row` already blanks this box when
    the package has ONE named insured. This must not claim it and assert an
    operations narrative for a party that does not exist."""
    facts = {"additional_named_insureds": [],
             "other_named_insured_operations": "something"}
    assert ps._resolve_other_named_insured_operations(
        "CommercialPolicy_OperationsDescription_B", facts) is ps._SCHED_SKIP


def test_the_primary_operations_box_is_not_claimed_by_this_resolver(ps):
    facts = {"additional_named_insureds": ["X"],
             "other_named_insured_operations": "other insureds text"}
    assert ps._resolve_other_named_insured_operations(
        "CommercialPolicy_OperationsDescription_A", facts) is ps._SCHED_SKIP


# ═══════════════════════════════════════════════════════════════════════════
# RC-C - the deterministic floor under the GENERAL INFORMATION block
# ═══════════════════════════════════════════════════════════════════════════

def _disclosure_facts():
    return {"disclosure_answers": [
        {"topic": "uncorrected_fire_safety_violations", "answer": "Y",
         "explanation": "Gresham Fire Marshal notice cites an obstructed sprinkler head.",
         "occurrence_date": "05/19/2025", "resolution": None, "resolution_date": None,
         "evidence_quote": "Gresham Fire Marshal notice dated 05/19/2025"},
        {"topic": "business_in_trust", "answer": "N",
         "evidence_quote": "The business has not been placed in a trust."},
    ]}


def test_a_shared_question_code_never_answers_the_wrong_question(ps, schema_ctx):
    """THE ADVERSARIAL CASE THIS DESIGN EXISTS FOR. ACORD 125 carries BOTH
    `CommercialPolicy_Question_ABBCode_A` ("Has business been placed in a
    trust?") and `CommercialStructure_Question_ABBCode_A` ("Any area leased to
    others?"). Matching on the CODE would answer a premises question with a
    trust answer, on all four premises rows."""
    facts = _disclosure_facts()
    assert ps._resolve_disclosure_answer("CommercialPolicy_Question_ABBCode_A", facts) == "N"
    for row in "ABCD":
        assert ps._resolve_disclosure_answer(
            f"CommercialStructure_Question_ABBCode_{row}", facts) is ps._SCHED_SKIP


def test_a_question_the_document_never_addressed_is_not_answered(ps, schema_ctx):
    """ADVERSARIAL. Brent's flagship rule: blank is not No. Questions 9 and 12
    held blank on both live runs and must keep doing so - a fact that omits a
    topic must not become an "N"."""
    facts = _disclosure_facts()
    for field in ("CommercialPolicy_Question_KAKCode_A",   # bankruptcy
                  "CommercialPolicy_Question_KACCode_A",   # foreign operations
                  "CommercialPolicy_Question_KAOCode_A"):  # hires drone operators
        assert ps._resolve_disclosure_answer(field, facts) is ps._SCHED_SKIP, field


def test_an_answer_with_no_evidence_quote_is_declined(ps, schema_ctx):
    """ADVERSARIAL. The shipped compliance pass requires a grounding quote for
    every Y/N on every form. A deterministic answer that skipped it would be a
    hole in the same rule, on the same boxes."""
    facts = {"disclosure_answers": [
        {"topic": "business_in_trust", "answer": "Y", "evidence_quote": ""}]}
    assert ps._resolve_disclosure_answer(
        "CommercialPolicy_Question_ABBCode_A", facts) is ps._SCHED_SKIP


def test_the_block_follows_its_question_and_an_undated_resolution_stays_blank(ps, schema_ctx):
    facts = _disclosure_facts()
    assert ps._resolve_disclosure_answer("CommercialPolicy_Question_AAFCode_A", facts) == "Y"
    assert ps._resolve_disclosure_answer(
        "CommercialPolicy_UncorrectedFireCodeViolationExplanation_A", facts).startswith("Gresham")
    assert ps._resolve_disclosure_answer(
        "CommercialPolicy_UncorrectedFireCodeViolation_OccurrenceDate_A", facts) == "05/19/2025"
    # THE MATERIAL MISSTATEMENT FROM RUN 1: the document states no resolution.
    # The RESOLVER declines (silence in the fact is not a statement that the box
    # is empty - see `test_a_disclosure_with_no_explanation_column_...`); GUARD
    # 12b is what refuses a resolution whose text denies completion, and Guard 6
    # is what keeps a dependent out from under a question that is not a Yes.
    assert ps._resolve_disclosure_answer(
        "CommercialPolicy_UncorrectedFireCodeViolation_ResolutionDescription_A",
        facts) is ps._SCHED_SKIP


def test_a_no_answer_carries_no_explanation(ps, schema_ctx):
    """ADVERSARIAL. Guards 5 and 6 enforce this downstream; the floor must not
    hand them a block to clean up."""
    facts = {"disclosure_answers": [
        {"topic": "uncorrected_fire_safety_violations", "answer": "N",
         "explanation": "should never print",
         "evidence_quote": "There are no uncorrected fire code violations."}]}
    assert ps._resolve_disclosure_answer("CommercialPolicy_Question_AAFCode_A", facts) == "N"
    assert ps._resolve_disclosure_answer(
        "CommercialPolicy_UncorrectedFireCodeViolationExplanation_A", facts) is None


def test_every_disclosure_topic_resolves_to_exactly_one_question_per_form():
    """ANTI-ROT, SWEPT OVER ALL 17 REAL SCHEMAS. A topic phrase that starts
    matching two different ACORD questions would answer one with the other, and
    nothing else in the pipeline would notice."""
    import services.pdf_service as ps
    for form, schema in _all_schemas():
        seen = {}
        for field, meta in schema.items():
            question = ps._compliance_question_text(str((meta or {}).get("tu") or "")).lower()
            if not question:
                continue
            hit = [t for t, phrase in ps._DISCLOSURE_TOPIC_PHRASES.items() if phrase in question]
            assert len(hit) <= 1, f"{form} {field} matches {hit}"
            if hit and "_Question_" in field:
                seen.setdefault(hit[0], []).append(field)
        for topic, fields in seen.items():
            assert len(fields) == 1, f"{form}: topic {topic} claims {fields}"


def test_the_topic_map_reaches_real_questions_on_the_anchor_form(a125):
    import services.pdf_service as ps
    mapping = ps._disclosure_field_map(
        tuple((k, str((v or {}).get("tu") or "")) for k, v in a125.items()))
    answers = {f for f, (_t, role) in mapping.items() if role == "answer"}
    # 16 general-information questions carry a topic; the premises "leased to
    # others" question deliberately carries none.
    assert len(answers) >= 15, sorted(answers)
    assert "CommercialStructure_Question_ABBCode_A" not in mapping


# ═══════════════════════════════════════════════════════════════════════════
# Schema / registry anti-rot
# ═══════════════════════════════════════════════════════════════════════════

_NEW_LIST_FACTS = ("named_insured_details", "applicant_contacts",
                   "additional_interests", "organization_relationships",
                   "safety_program_elements", "disclosure_answers")


@pytest.mark.parametrize("fact", _NEW_LIST_FACTS)
def test_every_new_list_fact_is_registered_in_both_merge_registries(fact):
    """A list missing from _LONG_DOC_LIST_KEYS is merged as a SCALAR: one
    chunk's rows win and the rest of the document's are lost. A named insured
    on page 3 and an additional interest on page 74 are in different chunks."""
    from services import extraction_service as es
    assert fact in es._LIST_FIELDS, fact
    assert fact in es._LONG_DOC_LIST_KEYS, fact
    assert f'"{fact}"' in es._EXTRACT_SCHEMA, fact


def test_the_prompt_version_moved_with_the_schema():
    from services import extraction_service as es
    # v23 since 2026-09-28 (FR125 v2 tests 3-5): additive submission_* facts,
    # nonrenewal_reasons and three columns. THE TEST MOVED, NOT ITS SUBJECT -
    # this edit bumped. See improving-ll.md C98 (v23), C99 (v24) and C100 (v25,
    # the same day: two v23 definitions reworded).
    assert es.PROMPT_VERSION == es.SCHEMA_VERSION == "v25"


@pytest.mark.parametrize("base", [
    "NamedInsured_TaxIdentifier", "NamedInsured_SICCode", "NamedInsured_NAICSCode",
    "NamedInsured_Primary_WebsiteAddress", "NamedInsured_MailingAddress_CityName",
    "NamedInsured_Contact_FullName", "NamedInsured_Contact_SecondaryPhoneNumber",
    "AdditionalInterest_FullName", "AdditionalInterest_InterestReasonDescription",
    "AdditionalInterest_MailingAddress_CountryCode",
])
def test_every_new_binding_names_a_field_that_really_exists(base):
    """CLAUDE.md: 50 of 87 existing _SCHEDULE_REGISTRY entries match NO real
    schema field. Not one more."""
    for _form, schema in _all_schemas():
        if any(re.match(rf"^{re.escape(base)}_[A-N]$", f) for f in schema):
            return
    pytest.fail(f"{base} matches no field on any of the 17 real schemas")


def test_the_premises_table_names_its_abbreviated_headers():
    """RC-G. Four columns of one riffled table stamped correctly and two did
    not; the two that failed are the only ones whose header is an abbreviation
    with no lexical bridge to the fact name."""
    from services import extraction_service as es
    for token in ("# FULL TIME EMPL", "# PART TIME EMPL"):
        assert token in es._EXTRACT_SCHEMA, token


# ═══════════════════════════════════════════════════════════════════════════
# The "ProducerIdentifier" naming false positive, closed from ACORD's own type
# ═══════════════════════════════════════════════════════════════════════════

def test_a_reference_number_is_not_an_agency_code(ps, schema_ctx):
    """ACORD's own tooltip draws this line, so the rule is derived, not listed:
    "Enter CODE: the identification code assigned to the producer" stays
    blocked; "Enter NUMBER: the building number for the premises" does not.

    An explicit allow for LOC # already existed - BLD # and the additional
    interest's item-location box are the SAME false positive one box over, and
    were simply missed."""
    for field in ("CommercialStructure_Location_ProducerIdentifier_A",
                  "CommercialStructure_Building_ProducerIdentifier_A",
                  "AdditionalInterest_Item_LocationProducerIdentifier_A"):
        assert ps._is_nonfillable_field(field) is False, field
    # ADVERSARIAL HALF: the boxes the broad substring was actually added for
    for field in ("Insurer_ProducerIdentifier_A", "Insurer_SubProducerIdentifier_A"):
        assert ps._is_nonfillable_field(field) is True, field


def test_every_producer_identifier_declares_one_type_or_the_other():
    """ANTI-ROT over all 17 schemas. The rule only holds while ACORD keeps
    declaring these as either a code or a number; a third shape would fall
    through the derivation silently."""
    import re as _re
    seen = 0
    for _form, schema in _all_schemas():
        for field, meta in schema.items():
            if "ProducerIdentifier" not in field:
                continue
            tu = str((meta or {}).get("tu") or "").strip().lower()
            if not tu:
                continue
            seen += 1
            assert tu.startswith("enter number:") or tu.startswith("enter code:"), \
                f"{_form} {field} declares neither: {tu[:60]!r}"
    assert seen > 20, seen


def test_the_premises_detail_resolver_skips_a_pre_v22_schedule(ps):
    """ADVERSARIAL. property_locations exists on every old session; its rows
    just lack the two new columns. Binding these through _SCHEDULE_REGISTRY
    made them owned blanks - measured, then reverted. The pre-v22 test is
    structural: if NOT ONE row carries the column, step aside."""
    pre = {"property_locations": [{"address": "2250 NW Vaughn St", "city": "Portland"}]}
    for field in ("CommercialStructure_Building_ProducerIdentifier_A",
                  "CommercialStructure_Question_ABBCode_B"):
        assert ps._resolve_premises_detail(field, pre) is ps._SCHED_SKIP, field
    post = {"property_locations": [
        {"address": "a", "building_number": "001", "any_area_leased_to_others": "N"},
        {"address": "b", "building_number": "001", "any_area_leased_to_others": "Y"}]}
    assert ps._resolve_premises_detail("CommercialStructure_Building_ProducerIdentifier_A", post) == "001"
    assert ps._resolve_premises_detail("CommercialStructure_Question_ABBCode_B", post) == "Y"
    assert ps._resolve_premises_detail("CommercialStructure_Question_ABBCode_D", post) is None


# ═══════════════════════════════════════════════════════════════════════════
# ROW A'S SCALARS - the one place a detail resolver could DELETE a correct value
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("row", [
    pytest.param([{"name": "Dana Reyes"}], id="partial-row"),
    pytest.param([{}], id="empty-row"),
    pytest.param([{"contact_type": "Inspection"}], id="type-only"),
    pytest.param([{"name": "Dana Reyes", "phone": "303-555-0142"}], id="no-email"),
])
def test_a_partial_contact_row_never_deletes_the_applicants_own_scalars(ps, schema_ctx, row):
    """FOUND BY ADVERSARIAL REVIEW, 22 Sep, and it was CRITICAL.

    `applicant_contacts` declares every column "string or null", so a partial
    row is permitted BY CONSTRUCTION and is the ordinary case - a document
    printing "Inspection contact: Dana Reyes, 303-555-0142" states no email.
    `_detail_cell` returns an owned blank the moment a row exists but a column
    is empty, so that partial row turned `contact_phone` and `contact_email` -
    populated, correct, Tier-1 facts - into empty boxes that gap fill was never
    asked about.

    Every OTHER detail resolver was already guarded against this: the
    named-insured one offsets past row A, the premises one has a structural
    pre-v22 escape. This was the only one that claims row A, and row A is the
    only place a competing populated scalar exists."""
    facts = {"contact_name": "Dana Reyes", "contact_phone": "303-555-0142",
             "contact_email": "dana@meridian.com", "applicant_contacts": row}
    mapped, _u, _d = ps.compute_form_gaps("ACORD_125", schema_ctx, dict(facts))
    assert mapped.get("NamedInsured_Contact_PrimaryPhoneNumber_A") == "303-555-0142"
    assert mapped.get("NamedInsured_Contact_PrimaryEmailAddress_A") == "dana@meridian.com"


def test_the_secondary_box_keeps_its_owned_blank(ps, schema_ctx):
    """ADVERSARIAL HALF. The row-A claim exists for the SECONDARY boxes - the
    live defect where the SECOND contact's phone printed in the FIRST contact's
    SECONDARY slot. No scalar can fill those, so an empty cell there really is
    the answer and the fallback must not reopen them to gap fill."""
    facts = {"contact_name": "Dana Reyes", "contact_phone": "303-555-0142",
             "applicant_contacts": [{"name": "Dana Reyes", "phone": "303-555-0142"},
                                    {"name": "Wendell Pardoe", "phone": "503-555-0193"}]}
    mapped, unmatched, _d = ps.compute_form_gaps("ACORD_125", schema_ctx, dict(facts))
    for f in ("NamedInsured_Contact_SecondaryPhoneNumber_A",
              "NamedInsured_Contact_SecondaryEmailAddress_A"):
        assert mapped.get(f) is None and f not in unmatched, f
    # ...and contact B still reaches its own block
    assert mapped.get("NamedInsured_Contact_PrimaryPhoneNumber_B") == "503-555-0193"


def test_no_detail_resolver_can_shadow_a_populated_scalar(ps, schema_ctx):
    """ANTI-ROT, generalised past the one resolver that had the bug.

    Drives every field the detail resolvers can claim with the scalars
    populated and a deliberately SPARSE v22 row, and fails if any box that
    carried a value without the row goes dark with it. A future detail resolver
    that claims row A inherits this test."""
    scalars = {"contact_name": "Dana Reyes", "contact_phone": "303-555-0142",
               "contact_email": "dana@meridian.com",
               "applicant_website": "www.meridianiw.com",
               "fein": "93-2841760", "sic_code": "1711", "naics_code": "238220",
               "operations_description": "Mechanical contracting.",
               "additional_named_insureds": ["Cedar Bluff Steel Fabricators, Inc."]}
    sparse = {**scalars,
              "applicant_contacts": [{"name": "Dana Reyes"}],
              "named_insured_details": [{"name": "Cedar Bluff Steel Fabricators, Inc."}],
              "additional_interests": [{"name": "Ironbridge Capital"}],
              "property_locations": [{"address": "2250 NW Vaughn St"}]}
    before, _u1, _d1 = ps.compute_form_gaps("ACORD_125", schema_ctx, dict(scalars))
    after, _u2, _d2 = ps.compute_form_gaps("ACORD_125", schema_ctx, dict(sparse))
    lost = [f for f, v in before.items()
            if v not in (None, "", []) and after.get(f) in (None, "", [])]
    assert lost == [], f"a sparse v22 row darkened boxes the scalars filled: {lost}"


# ═══════════════════════════════════════════════════════════════════════════
# The detail row is matched BY NAME - RC-A's own defect, nearly reintroduced
# ═══════════════════════════════════════════════════════════════════════════

_CB = {"name": "Cedar Bluff Steel Fabricators, Inc.", "fein": "26-0459318",
       "sic": "3441", "city": "Gresham"}
_TV = {"name": "Tualatin Valley Mechanical Services, LLC", "fein": "47-3318805",
       "sic": "1711", "city": "Tigard"}
_ME = {"name": "Meridian Ironworks & Mechanical, LLC", "fein": "93-2841760",
       "sic": "1711", "city": "Portland"}
_ROSTER = ["Cedar Bluff Steel Fabricators, Inc.",
           "Tualatin Valley Mechanical Services, LLC"]


@pytest.mark.parametrize("details,ident", [
    pytest.param([_CB, _TV], "in-order", id="in-order"),
    pytest.param([_TV, _CB], "reversed", id="reversed"),
    pytest.param([_ME, _CB, _TV], "applicant-prepended", id="applicant-prepended"),
])
def test_a_detail_row_follows_its_ENTITY_not_its_position(ps, schema_ctx, details, ident):
    """FOUND BY ADVERSARIAL REVIEW, 22 Sep. CRITICAL, and the most embarrassing
    kind: RC-A's own "Fate 1 is the dangerous one" - a real, correctly shaped,
    document-present value on the WRONG ENTITY of a signed application -
    reintroduced by the fix for it.

    Row B is the ONE place on this form where the NAME comes from one fact
    (`additional_named_insureds`) and every other column comes from ANOTHER
    (`named_insured_details`). Reading the second by ordinal assumes the two
    lists keep the same length and order forever. They do not:
    `_drop_transaction_party_rows` filters the roster and not the detail;
    `_merge_list_fields` unions each list independently with no `name` subkey in
    `_natural_id_keys`; and the model can simply answer in another order.

    `scripts/score_a125_extraction.py` had this right the day it was written -
    "rows are matched by NAME, never by position". The resolver did not."""
    facts = {"additional_named_insureds": list(_ROSTER),
             "named_insured_details": [dict(d) for d in details]}
    mapped, _u, _d = ps.compute_form_gaps("ACORD_125", schema_ctx, dict(facts))
    assert mapped.get("NamedInsured_TaxIdentifier_B") == "26-0459318", ident
    assert mapped.get("NamedInsured_SICCode_B") == "3441", ident
    assert mapped.get("NamedInsured_MailingAddress_CityName_B") == "Gresham", ident
    assert mapped.get("NamedInsured_TaxIdentifier_C") == "47-3318805", ident
    assert mapped.get("NamedInsured_MailingAddress_CityName_C") == "Tigard", ident


def test_an_entity_with_no_detail_row_gets_a_blank_not_a_neighbours_values(ps, schema_ctx):
    """ADVERSARIAL. The roster names two parties and only the SECOND is
    described. Positionally, row B would have printed Tualatin's FEIN under
    Cedar Bluff's name - which is the defect, not a near miss."""
    facts = {"additional_named_insureds": list(_ROSTER),
             "named_insured_details": [dict(_TV)]}
    mapped, unmatched, _d = ps.compute_form_gaps("ACORD_125", schema_ctx, dict(facts))
    assert mapped.get("NamedInsured_TaxIdentifier_B") is None
    assert "NamedInsured_TaxIdentifier_B" not in unmatched
    assert mapped.get("NamedInsured_TaxIdentifier_C") == "47-3318805"


def test_the_entity_type_tick_follows_the_same_name_alignment(ps, schema_ctx):
    """The legal-entity tick reads the same list and had the same ordinal bug."""
    facts = {"additional_named_insureds": list(_ROSTER),
             "named_insured_details": [
                 {**_TV, "entity_type": "LLC"},
                 {**_CB, "entity_type": "Corporation"}]}          # reversed
    mapped, _u, _d = ps.compute_form_gaps("ACORD_125", schema_ctx, dict(facts))
    assert mapped.get("NamedInsured_LegalEntity_CorporationIndicator_B") == "Y"
    assert mapped.get("NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_C") == "Y"


def test_no_roster_means_the_resolver_steps_aside(ps):
    """Without the roster we cannot say whose row this is, so today's behaviour
    runs rather than a guess being attached to an unnamed row."""
    assert ps._resolve_named_insured_detail(
        "NamedInsured_TaxIdentifier_B", {"named_insured_details": [dict(_CB)]}
    ) is ps._SCHED_SKIP


def test_an_unverifiable_warrant_may_not_answer_a_compliance_question():
    """FOUND BY ADVERSARIAL REVIEW, 22 Sep. CRITICAL.

    `_resolve_disclosure_answer` requires an `evidence_quote` but CANNOT verify
    it - a resolver is handed (field, facts) and never sees the document. That
    made the DETERMINISTIC path weaker than the LLM path it replaces: the
    evidence gate blanks an ungrounded Y/N from gap fill, while the same value
    with the same invented quote stamped straight from a fact. Reproduced with
    five 'N' answers on a declarations-only package - fraud/arson, abuse &
    molestation, declined coverage, judgment-or-lien and bankruptcy - which is
    "Blank is not No" failing on the five most material questions on the form.

    The merge tail is the one place holding both the facts and the text."""
    from services import extraction_service as es
    doc = ("ACORD 125 Commercial Insurance Application. Orbin Contracting LLC. "
           "Roofing operations. No other information.")
    facts = {"disclosure_answers": [
        {"topic": "fraud_arson_conviction", "answer": "N",
         "evidence_quote": "No such matter is reported anywhere."},
        {"topic": "judgement_or_lien", "answer": "N",
         "evidence_quote": "There have been no liens of any kind."},
        {"topic": "business_in_trust", "answer": "N",
         "evidence_quote": "Orbin Contracting LLC"},
    ]}
    docs = [{"doc_id": "d1", "filename": "f.pdf", "doc_type": "dec_page",
             "text": doc, "facts": dict(facts), "flags": {}}]
    merged = es.merge_facts(docs, docs[0])[0]
    kept = {r.get("topic") for r in (merged.get("disclosure_answers") or [])}
    assert "fraud_arson_conviction" not in kept
    assert "judgement_or_lien" not in kept
    assert "business_in_trust" in kept, "a grounded answer must survive"


def test_the_grounding_check_is_silent_when_there_is_no_document():
    """ADVERSARIAL. Absence of the text is not evidence against the quote - a
    re-merge with no doc text must not strip a package's disclosures."""
    from services import extraction_service as es
    facts = {"disclosure_answers": [
        {"topic": "business_in_trust", "answer": "N", "evidence_quote": "a quote"}]}
    docs = [{"doc_id": "d1", "filename": "f.pdf", "doc_type": "dec_page",
             "text": "", "facts": dict(facts), "flags": {}}]
    merged = es.merge_facts(docs, docs[0])[0]
    assert len(merged.get("disclosure_answers") or []) == 1


# ═══════════════════════════════════════════════════════════════════════════
# THE SEAM - a key nobody writes
# ═══════════════════════════════════════════════════════════════════════════

def test_the_attachment_resolver_is_actually_wired_into_the_stamper():
    """FOUND BY ADVERSARIAL REVIEW, 22 Sep. `_resolve_attachment_indicator` was
    registered in `_AUTHORITATIVE_BLANK_RESOLVERS` on 21 Sep and returned "Y"
    correctly - and never ticked a box on any form, because that registry only
    closes the GAP-FILL door. Measured: resolver -> 'Y',
    `_deterministic_map` -> 'UNMATCHED', `compute_form_gaps` -> None.

    Same "registration is not wiring" defect that hid this session's own seven
    resolvers. Registering without wiring produces a resolver that reports as
    owning its boxes while leaving every one of them empty."""
    import json as _json
    import services.pdf_service as _ps
    schema = _json.loads((SCHEMA_DIR / "ACORD_125_schema.json").read_text())
    _ps._set_schema_context(schema)
    try:
        field = "CommercialPolicy_Attachment_ContractorsSupplementIndicator_A"
        assert field in schema
        facts = {"_package_form_ids": ["ACORD_125", "ACORD_186"]}
        assert _ps._resolve_attachment_indicator(field, facts) == "Y"
        assert _ps._deterministic_map(field, facts) == "Y", (
            "the resolver answers but the stamper never asks it")
        mapped, unmatched, _det = _ps.compute_form_gaps("ACORD_125", schema, dict(facts))
        assert mapped.get(field) == "Y"
        # ...and a 125-only package leaves it an owned blank, not a guess
        m2, u2, _ = _ps.compute_form_gaps("ACORD_125", schema,
                                          {"_package_form_ids": ["ACORD_125"]})
        assert m2.get(field) is None and field not in u2
    finally:
        _ps._set_schema_context(None)


def test_the_package_form_list_reads_a_session_key_somebody_writes():
    """ANTI-ROT FOR THE SEAM, and it is the test that would have caught this.

    `process_single_form` built `_package_form_ids` from
    `session["selected_forms"]` - a key NO writer puts at the top level of a
    session row (form_routes nests that name inside `clarity_result`). So the
    package list silently collapsed to [this form] on every first generation and
    the ATTACHMENTS boxes could only tick on a RE-generation. Verified against a
    real session row: `selected_forms` absent, `selected_form_ids` present.

    Every session key this reads must be one something in the codebase writes.

    Reads the helper's own body (25 Sep 2026): the list moved into
    `form_service.package_form_ids`, which both stamping and the shared gap fill
    now call. Locating "the first mention of _package_form_ids" found the shared
    gap fill's call site instead, whose window reads facts / flags / docs."""
    import re as _re
    src = (BACKEND / "services" / "form_service.py").read_text()
    start = src.index("def package_form_ids(")
    block = src[start: src.index("\ndef ", start + 1)]
    keys = set(_re.findall(r'session\.get\("([a-z_]+)"\)', block))
    assert keys, "could not find the session keys this reads"
    assert "selected_form_ids" in keys, (
        "the package list must read `selected_form_ids` - the key that exists")
    writers = ""
    for sub in ("routes", "services", "repositories"):
        for path in (BACKEND / sub).rglob("*.py"):
            writers += path.read_text()
    for key in keys:
        assert (f'"{key}":' in writers or f"'{key}':" in writers
                or f'[{key!r}]' in writers), (
            f"form_service reads session[{key!r}] but nothing writes it")


# ═══════════════════════════════════════════════════════════════════════════
# Round 2 of the adversarial review - five more confirmed findings
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("word,box", [
    ("Not For Profit", "NotForProfitIndicator_B"),
    ("S Corporation", "SubchapterSCorporationIndicator_B"),
    ("LLP", "PartnershipIndicator_B"),
    ("Limited Partnership", "PartnershipIndicator_B"),
    ("Sole Proprietorship", "IndividualIndicator_B"),
    ("Corporation", "CorporationIndicator_B"),
    ("LLC", "LimitedLiabilityCorporationIndicator_B"),
])
def test_row_b_reads_the_same_entity_door_as_row_a(ps, schema_ctx, word, box):
    """The first cut carried its own eight-word map - a weaker copy of
    `normalization.entity_family` + `_ENTITY_BOX_WORDS`, the door row A has used
    since 2026-08-27 precisely because three places were each guessing. The copy
    silently dropped six of the eight words the v22 schema tells the model to
    use, so row A ticked correctly while row B printed a name with no entity
    type at all - and the box was removed from gap fill, so nothing recovered
    it."""
    roster = ["Cedar Bluff Steel Fabricators, Inc."]
    facts = {"additional_named_insureds": roster,
             "named_insured_details": [{"name": roster[0], "entity_type": word}]}
    mapped, _u, _d = ps.compute_form_gaps("ACORD_125", schema_ctx, dict(facts))
    assert mapped.get(f"NamedInsured_LegalEntity_{box}") == "Y", word


def test_a_disclosure_with_no_explanation_column_leaves_the_box_to_gap_fill(ps, schema_ctx):
    """Extraction found the disclosure and quoted it but did not fill the
    explanation column. That is a gap in the FACT, not a statement that the box
    is empty. Claiming it removed the box from gap fill, Guard 9 then saw an
    affirmative with an empty paired explanation and deleted the correct "Y",
    and a material judgment/lien disclosure shipped as a blank question."""
    facts = {"disclosure_answers": [
        {"topic": "judgement_or_lien", "answer": "Y", "explanation": None,
         "evidence_quote": "A mechanic's lien was filed against the premises in March 2024."}]}
    mapped, unmatched, _d = ps.compute_form_gaps("ACORD_125", schema_ctx, dict(facts))
    assert mapped.get("CommercialPolicy_Question_KALCode_A") == "Y"
    assert "CommercialPolicy_JudgementOrLienExplanation_A" in unmatched


def test_an_undated_but_real_resolution_survives(ps, a125):
    """Guard 12b's first version read the DATE box - true of ACORD's layout, not
    of documents. Plenty of real remedies are described without a date, and it
    deleted every one, which made `disclosure_answers.resolution` dead by
    construction."""
    R = "CommercialPolicy_UncorrectedFireCodeViolation_ResolutionDescription_A"
    mapped = {"CommercialPolicy_Question_AAFCode_A": "Y",
              "CommercialPolicy_UncorrectedFireCodeViolationExplanation_A":
                  "Gresham Fire Marshal cites an obstructed sprinkler head.",
              R: "Exit cleared and the premises passed re-inspection."}
    ps._enforce_post_fill_guards(mapped, a125, {}, set())
    assert mapped[R] == "Exit cleared and the premises passed re-inspection."


@pytest.mark.parametrize("resolution", [
    "Abatement is scheduled, the premises has not yet been re-inspected.",
    "Re-inspection is scheduled for 06/2025 and has not taken place.",
    "Remediation is pending.",
])
def test_a_resolution_whose_text_denies_completion_is_refused(ps, a125, resolution):
    """The live misstatement, plus the case the DATE test could never see - a
    DATED resolution whose own words say it has not happened."""
    R = "CommercialPolicy_UncorrectedFireCodeViolation_ResolutionDescription_A"
    mapped = {"CommercialPolicy_Question_AAFCode_A": "Y",
              "CommercialPolicy_UncorrectedFireCodeViolationExplanation_A": "A violation.",
              "CommercialPolicy_UncorrectedFireCodeViolation_ResolutionDate_A": "06/01/2025",
              R: resolution}
    ps._enforce_post_fill_guards(mapped, a125, {}, set())
    assert mapped[R] is None


@pytest.mark.parametrize("explanation", [
    "Has the applicant had a judgment or lien during the past five (5) years? Lien filed 03/2024.",
    "Does applicant own / lease / operate any drones? Yes - two vans.",
])
def test_a_short_explanation_after_an_echo_is_kept(ps, a125, explanation):
    """Guard 12a's tail test was a LENGTH proxy for "says something of its own",
    so a tail carrying a lien and a date - three long tokens - was blanked, and
    Guard 9 then deleted the correct affirmative. It is a containment test now:
    does the tail add any token the question did not already contain."""
    Q = ("CommercialPolicy_Question_KALCode_A" if "judgment" in explanation
         else "CommercialPolicy_Question_KANCode_A")
    E = ("CommercialPolicy_JudgementOrLienExplanation_A" if "judgment" in explanation
         else "CommercialPolicy_ApplicantOwnLeaseOperateDronesExplanation_A")
    mapped = {Q: "Y", E: explanation}
    ps._enforce_post_fill_guards(mapped, a125, {}, set())
    assert mapped[E], "a real explanation after an echo must survive"
    assert mapped[Q] == "Y", "and its affirmative with it"


def test_a_pure_echo_is_still_blanked(ps, a125):
    """ADVERSARIAL HALF - the containment test must not reopen the defect."""
    mapped = {"CommercialPolicy_Question_KALCode_A": "Y",
              "CommercialPolicy_JudgementOrLienExplanation_A":
                  "Has applicant had a judgment or lien?"}
    ps._enforce_post_fill_guards(mapped, a125, {}, set())
    assert mapped["CommercialPolicy_JudgementOrLienExplanation_A"] is None


def test_the_schema_never_licenses_the_applicant_into_the_detail_list():
    """The name clause said "must match a name in additional_named_insureds OR
    applicant_name" and then, two clauses later, "The FIRST named insured is NOT
    in this list". A model obeying the first half emits the applicant as entry
    0, and row B then prints the SECOND insured's name with the APPLICANT's FEIN
    - a worse version of the defect being fixed."""
    from services import extraction_service as es
    assert "or applicant_name - this is the SAME party" not in es._EXTRACT_SCHEMA
    assert "must match a name in additional_named_insureds EXACTLY" in es._EXTRACT_SCHEMA


# ═══════════════════════════════════════════════════════════════════════════
# Three v22 columns that were extracted, paid for, and thrown away
# ═══════════════════════════════════════════════════════════════════════════

def test_the_detail_resolvers_outrank_the_family_blankers(ps, schema_ctx):
    """Sitting at the END of `_deterministic_map` these were intercepted by
    older whole-FAMILY resolvers that blank by name shape -
    `_resolve_member_manager_count` blanks every MemberManagerCount box and
    `_resolve_party_fax` blanks every non-producer fax. So a member count and a
    loss payee's fax were collected on every extraction call and discarded
    before they could reach a box.

    They run early now: a fact carrying THIS row and THIS column is strictly
    more specific than a family default. Only the conflicted-fact withhold
    outranks them, and it must."""
    facts = {"additional_named_insureds": ["Cedar Bluff Steel Fabricators, Inc."],
             "named_insured_details": [{"name": "Cedar Bluff Steel Fabricators, Inc.",
                                        "member_manager_count": "2"}],
             "additional_interests": [{"name": "Ironbridge Capital",
                                       "fax": "(503) 555-0222"}]}
    mapped, _u, _d = ps.compute_form_gaps("ACORD_125", schema_ctx, dict(facts))
    assert mapped.get("NamedInsured_LegalEntity_MemberManagerCount_B") == "2"
    assert mapped.get("AdditionalInterest_Primary_FaxNumber_A") == "(503) 555-0222"


def test_a_stated_phone_kind_ticks_its_own_box(ps, schema_ctx):
    facts = {"applicant_contacts": [
        {"name": "Rosalind Achterberg", "phone": "(503) 555-0156",
         "phone_kind": "Business"}]}
    mapped, _u, _d = ps.compute_form_gaps("ACORD_125", schema_ctx, dict(facts))
    assert mapped.get("NamedInsured_Contact_PrimaryBusinessPhoneIndicator_A") == "Y"
    for other in ("Home", "Cell"):
        assert mapped.get(f"NamedInsured_Contact_Primary{other}PhoneIndicator_A") is None


def test_a_phone_kind_with_no_phone_number_ticks_nothing(ps, schema_ctx):
    """ADVERSARIAL, and it is the live J6 defect: the form printed a BUS tick
    beside an EMPTY phone box on the second contact. A kind is an attribute of
    a number; with no number there is nothing to describe."""
    facts = {"applicant_contacts": [
        {"name": "Rosalind Achterberg", "phone": "(503) 555-0156", "phone_kind": "Business"},
        {"name": "Wendell Pardoe", "phone_kind": "Cell"}]}
    mapped, unmatched, _d = ps.compute_form_gaps("ACORD_125", schema_ctx, dict(facts))
    for kind in ("Home", "Business", "Cell"):
        f = f"NamedInsured_Contact_Primary{kind}PhoneIndicator_B"
        assert mapped.get(f) is None and f not in unmatched, f


def test_no_v22_column_is_collected_and_read_by_nobody():
    """ANTI-ROT. Every column the v22 schema asks LLM call 1 for costs tokens on
    every extraction call. One that no product code reads is pure waste, and
    three of them were: `phone_kind`, `member_manager_count` and the additional
    interest's `fax`."""
    import services.pdf_service as _ps
    src = (BACKEND / "services" / "pdf_service.py").read_text()
    for column in ("phone_kind", "member_manager_count", "fax",
                   "item_location_number", "evidence_requested",
                   "any_area_leased_to_others", "building_number",
                   "percent_owned", "relationship_description",
                   "interest_reason", "item_description", "entity_type"):
        assert f'"{column}"' in src, f"v22 collects {column!r} and nothing reads it"


def test_the_applicants_own_columns_never_broadcast_down_the_table(ps, schema_ctx):
    """Row A of the applicant table had no fact for its business phone, GL class
    code or member/manager count - `named_insured_details` describes the OTHER
    insureds only - so three boxes could not be filled by anything.

    Added as a ROW-A resolver, not an `_ACORD_FIELD_RULES` substring: a
    substring matches every row letter, and a package-level scalar broadcast
    across a table of entities is the RC-A defect this family exists to fix."""
    facts = {"applicant_business_phone": "(503) 555-0162",
             "applicant_gl_class_code": "91746",
             "applicant_member_manager_count": "4",
             "sales_installation_repair_percent": "100%",
             "sales_installation_repair_off_premises_percent": "85%"}
    mapped, _u, _d = ps.compute_form_gaps("ACORD_125", schema_ctx, dict(facts))
    assert mapped.get("NamedInsured_Primary_PhoneNumber_A") == "(503) 555-0162"
    assert mapped.get("NamedInsured_GeneralLiabilityCode_A") == "91746"
    assert mapped.get("NamedInsured_LegalEntity_MemberManagerCount_A") == "4"
    assert mapped.get("CommercialStructure_InstallationRepairWorkPercent_A") == "100%"
    for row in "BC":
        assert mapped.get(f"NamedInsured_Primary_PhoneNumber_{row}") is None, row


def test_the_applicant_scalars_skip_when_absent(ps):
    """Pre-v22 sessions keep exactly today's behaviour."""
    for field in ("NamedInsured_Primary_PhoneNumber_A",
                  "NamedInsured_GeneralLiabilityCode_A"):
        assert ps._resolve_applicant_row_a_scalar(field, {}) is ps._SCHED_SKIP
