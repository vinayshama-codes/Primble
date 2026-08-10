"""Guards shipped 2026-08-09 for the ACORD 125 live-run regressions.

Three independent defects, one theme: a value was stamped after the context
that qualifies it had been stripped away (see fix-form-stamping.md).

W1  A `coverage_lines` MENTION was read as a GRANT, so the declared-absent
    downgrade was vetoed and Commercial Property stayed ticked on a package
    whose dec page reads "PROPERTY - NO COVERAGE".
W2  Gap fill put the CARRIER's name into the applicant's parent-organization
    box and the PRODUCER's phone into the applicant's contact block. Every
    ownership guard in the codebase runs on the deterministic path only.
W3  The SIC grounding gate matched the label "sic" as a bare substring, so
    "basic" / "classic" / "physician" satisfied it on every document.

The coverage-protection tests below are as important as the defect tests: the
standing product rule is that a correctness fix must never cost a legitimate
fill.
"""

import pytest

from services.extraction_service import apply_declared_absent_downgrades
from services.pdf_service import (
    _drop_foreign_entity_values,
    _drop_ungrounded_classification_codes,
)


# ══════════════════════════════════════════════════════════════════════════
# W1 - a mention is not a grant
# ══════════════════════════════════════════════════════════════════════════

DECS = (
    "COMMERCIAL GENERAL LIABILITY   $3,954\n"
    "COMMERCIAL INLAND MARINE       $300\n"
    "PROPERTY                       NO COVERAGE\n"
    "CRIME AND FIDELITY             NO COVERAGE\n"
)


def _flags():
    return {
        "has_property_coverage": True,
        "has_crime": True,
        "has_general_liability": True,
        "has_inland_marine": True,
    }


def test_bare_line_name_no_longer_vetoes_the_downgrade():
    """THE REPORTED DEFECT. A line entry carrying nothing but its own name is a
    mention. Before this fix it vetoed the downgrade and the box stayed ticked."""
    flags = _flags()
    facts = {"coverage_lines": [{"line": "Commercial Property"}]}
    changed = apply_declared_absent_downgrades(flags, facts, DECS)
    assert "has_property_coverage" in changed
    assert flags["has_property_coverage"] is False


def test_a_denial_inside_the_entry_is_not_evidence():
    """The client's own run stamped the literal string "No Coverage" into the
    Property premium box, so this entry shape is observed, not hypothetical."""
    flags = _flags()
    facts = {"coverage_lines": [
        {"line": "Commercial Property", "premium": "No Coverage"},
    ]}
    changed = apply_declared_absent_downgrades(flags, facts, DECS)
    assert "has_property_coverage" in changed
    assert flags["has_property_coverage"] is False


@pytest.mark.parametrize("evidence", [
    {"premium": "$5,000"},
    {"limit": "$1,000,000"},
])
def test_real_coverage_is_never_downgraded(evidence):
    """COVERAGE PROTECTION. A line the document actually grants keeps its flag,
    whatever the prose elsewhere says. This is the test that must never be
    relaxed to make a downgrade fire.

    MONEY is the grant. A carrier charges a premium or promises a limit only for
    coverage it is actually writing, so either one outranks a "NO COVERAGE"
    string found elsewhere in the text - the two genuinely conflict and coverage
    wins.
    """
    flags = _flags()
    entry = {"line": "Commercial Property"}
    entry.update(evidence)
    facts = {"coverage_lines": [entry]}
    changed = apply_declared_absent_downgrades(flags, facts, DECS)
    assert "has_property_coverage" not in changed
    assert flags["has_property_coverage"] is True


@pytest.mark.parametrize("evidence", [
    {"policy_number": "6C7-40-02---26"},
    {"carrier": "EMC Property & Casualty Company"},
    {"naic": "21415"},
    {"effective_date": "07/15/2025"},
])
def test_policy_metadata_cannot_outrank_a_printed_denial(evidence):
    """RUN 5. Extraction attached the INLAND MARINE policy number to an entry it
    named "Property", and that one borrowed number vetoed the dec page's own
    printed "PROPERTY - NO COVERAGE" - so the box stayed ticked, took an "other
    line of business" row AND filled a Q4 row, three symptoms from one cause.

    A number, a carrier, a NAIC or a date can all sit against a line that is
    merely REFERENCED - a cancellation notice, a prior-carrier block, a
    schedule cross-reference. None of them says the carrier is writing it.
    An explicitly printed denial does say the opposite, in the document's own
    words, so it wins. This is the client's mention-versus-grant distinction
    applied one level deeper than the checkbox.
    """
    flags = _flags()
    entry = {"line": "Commercial Property"}
    entry.update(evidence)
    changed = apply_declared_absent_downgrades(
        flags, {"coverage_lines": [entry]}, DECS)
    assert "has_property_coverage" in changed
    assert flags["has_property_coverage"] is False


def test_metadata_plus_money_still_keeps_the_coverage():
    """The realistic granted shape - a number AND a premium - is untouched."""
    flags = _flags()
    changed = apply_declared_absent_downgrades(flags, {"coverage_lines": [
        {"line": "Commercial Property", "policy_number": "BBC7263-26",
         "premium": "$5,000"}]}, DECS)
    assert "has_property_coverage" not in changed


def test_the_run_5_package_downgrades_only_the_denied_lines():
    """End to end on the live entry set: Property and Crime go, GL and Inland
    Marine - both of which the dec page prices - stay."""
    flags = _flags()
    changed = apply_declared_absent_downgrades(flags, {"coverage_lines": [
        {"line": "Commercial General Liability", "premium": "$3,954"},
        {"line": "Commercial Inland Marine", "premium": "$300"},
        {"line": "Property", "policy_number": "6C7-40-02---26"},
        {"line": "Crime", "carrier": "EMC"},
    ]}, DECS)
    assert set(changed) == {"has_property_coverage", "has_crime"}
    assert flags["has_general_liability"] is True
    assert flags["has_inland_marine"] is True


def test_a_carrier_name_in_the_line_slot_cannot_veto():
    """"EMC Property & Casualty Company" contains the token "property" and
    would otherwise protect the Property box forever."""
    flags = _flags()
    facts = {"coverage_lines": [
        {"line": "EMC Property & Casualty Company", "premium": "$3,954"},
    ]}
    changed = apply_declared_absent_downgrades(flags, facts, DECS)
    assert "has_property_coverage" in changed


def test_silence_never_downgrades_anything():
    """The oldest rule in this area: absence of a mention leaves a flag alone."""
    flags = _flags()
    changed = apply_declared_absent_downgrades(
        flags, {}, "COMMERCIAL GENERAL LIABILITY $3,954\n")
    assert changed == []
    assert flags["has_property_coverage"] is True


def test_a_granted_line_elsewhere_does_not_protect_a_denied_one():
    """Per-line, not per-package: GL being granted must not veto Property."""
    flags = _flags()
    facts = {"coverage_lines": [
        {"line": "Commercial General Liability", "premium": "$3,954"},
        {"line": "Commercial Inland Marine", "premium": "$300"},
    ]}
    changed = apply_declared_absent_downgrades(flags, facts, DECS)
    assert "has_property_coverage" in changed
    assert "has_crime" in changed
    assert flags["has_general_liability"] is True
    assert flags["has_inland_marine"] is True


def test_the_downgrade_never_turns_a_flag_on():
    flags = {"has_property_coverage": False}
    changed = apply_declared_absent_downgrades(flags, {}, DECS)
    assert flags["has_property_coverage"] is False
    assert "has_property_coverage" not in changed


# ══════════════════════════════════════════════════════════════════════════
# W2 - another party's value in an applicant-owned box
# ══════════════════════════════════════════════════════════════════════════

FACTS = {
    "applicant_name":         "Orbin Contracting LLC",
    "carrier_name":           "Employers Mutual Casualty Company",
    "producer_name":          "Commercial Risk Solutions, Inc.",
    "producer_contact_phone": "303-996-7800",
}


def test_the_carrier_is_not_the_applicants_parent_company():
    """THE REPORTED REGRESSION. A signed ACORD 125 asserted that the applicant
    is a subsidiary of its own insurer."""
    mapped = {"BusinessInformation_ParentOrganizationName_A": "Emc Insurance Companies"}
    dropped = _drop_foreign_entity_values(
        mapped, FACTS, {"BusinessInformation_ParentOrganizationName_A"})
    assert dropped == ["BusinessInformation_ParentOrganizationName_A"]
    assert mapped["BusinessInformation_ParentOrganizationName_A"] is None


def test_a_reformatted_producer_phone_is_still_the_producers():
    """The live regression added `(303)996-7800` to the applicant's secondary
    phone box. Comparison is format-blind on purpose."""
    field = "NamedInsured_Contact_SecondaryPhoneNumber_A"
    mapped = {field: "(303)996-7800"}
    dropped = _drop_foreign_entity_values(mapped, FACTS, {field})
    assert dropped == [field]
    assert mapped[field] is None


def test_a_carrier_name_in_the_insurer_block_is_left_alone():
    """SCOPE GUARD. Third-party blocks are out of scope - a carrier name is
    correct in several of them, and blanking it would be a pure fill loss."""
    mapped = {"Insurer_FullName_A": "Employers Mutual Casualty Company"}
    dropped = _drop_foreign_entity_values(mapped, FACTS, {"Insurer_FullName_A"})
    assert dropped == []
    assert mapped["Insurer_FullName_A"] == "Employers Mutual Casualty Company"


def test_a_deterministic_value_is_never_touched():
    """Pass 1 / alias / client values are outside this guard by construction."""
    field = "BusinessInformation_ParentOrganizationName_A"
    mapped = {field: "Emc Insurance Companies"}
    dropped = _drop_foreign_entity_values(mapped, FACTS, set())
    assert dropped == []
    assert mapped[field] == "Emc Insurance Companies"


def test_an_ambiguous_value_keeps_the_fill():
    """A captive agency, or an extraction that mixed the two parties: if the
    value is ALSO one of the applicant's own facts we cannot say whose it is,
    and ambiguity fails toward keeping the fill."""
    facts = dict(FACTS, applicant_name="Employers Mutual Casualty Company")
    field = "NamedInsured_FullName_A"
    mapped = {field: "Employers Mutual Casualty Company"}
    dropped = _drop_foreign_entity_values(mapped, facts, {field})
    assert dropped == []


def test_the_applicants_own_name_is_never_blanked():
    """COVERAGE PROTECTION. The single most important value on the form."""
    field = "NamedInsured_FullName_A"
    mapped = {field: "Orbin Contracting LLC"}
    dropped = _drop_foreign_entity_values(mapped, FACTS, {field})
    assert dropped == []
    assert mapped[field] == "Orbin Contracting LLC"


def test_no_carrier_or_producer_facts_means_no_op():
    """The guard cannot fire on a submission where we hold nothing to compare."""
    mapped = {"BusinessInformation_ParentOrganizationName_A": "Some Holding Co"}
    dropped = _drop_foreign_entity_values(
        mapped, {"applicant_name": "Orbin Contracting LLC"},
        {"BusinessInformation_ParentOrganizationName_A"})
    assert dropped == []


def test_a_short_value_can_never_coincide_into_a_drop():
    """A 2-3 character token is not distinctive enough to prove ownership."""
    facts = {"carrier_name": "EMC"}
    field = "BusinessInformation_ParentOrganizationName_A"
    mapped = {field: "EMC"}
    dropped = _drop_foreign_entity_values(mapped, facts, {field})
    assert dropped == []


def test_the_producers_name_in_a_driver_box_is_dropped():
    """improving-ll.md C22, closed from the OWNERSHIP side. C22 caught
    `Driver_TaxIdentifier = "ERIN ROYAL"` by declared TYPE and recorded that the
    same value in `Driver_GenderCode` was invisible to a type check. It is not
    invisible to ownership."""
    facts = dict(FACTS, producer_contact_name="Erin Royal")
    mapped = {"Driver_TaxIdentifier_I": "ERIN ROYAL",
              "Driver_GenderCode_A": "ERIN ROYAL"}
    dropped = _drop_foreign_entity_values(mapped, facts, set(mapped))
    assert sorted(dropped) == ["Driver_GenderCode_A", "Driver_TaxIdentifier_I"]


def test_a_real_drivers_name_survives():
    """COVERAGE PROTECTION for the block just added to scope."""
    mapped = {"Driver_FullName_A": "Michael Torres"}
    dropped = _drop_foreign_entity_values(mapped, FACTS, {"Driver_FullName_A"})
    assert dropped == []


@pytest.mark.parametrize("field", [
    "UnderlyingPolicy_Insurer_FullName_A",   # ACORD 131 - the underlying carrier
    "OtherInsurance_CarrierName_A",          # ACORD 160 - another carrier
    "PriorCoverage_NAICCode_A",
    "CertificateHolder_FullName_A",
])
def test_blocks_where_a_carrier_name_is_correct_stay_out_of_scope(field):
    """STANDING GUARD. The 17-form sweep that produced the scope list found
    these; adding any of them would blank a legitimate carrier name. If someone
    widens `_APPLICANT_OWNED_PREFIXES` carelessly, this fails."""
    mapped = {field: "Employers Mutual Casualty Company"}
    dropped = _drop_foreign_entity_values(mapped, FACTS, {field})
    assert dropped == []
    assert mapped[field] == "Employers Mutual Casualty Company"


def test_facts_in_the_confidence_envelope_are_understood():
    """Facts arrive as {"value": ..., "confidence": ...} in production."""
    facts = {"carrier_name": {"value": "Employers Mutual Casualty Company",
                              "confidence": 0.9}}
    field = "BusinessInformation_ParentOrganizationName_A"
    mapped = {field: "Employers Mutual Casualty Company"}
    dropped = _drop_foreign_entity_values(mapped, facts, {field})
    assert dropped == [field]


# ══════════════════════════════════════════════════════════════════════════
# W3 - the SIC grounding gate was matching a bare substring
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("doc", [
    "The policy provides basic coverage for the premises.",
    "A classic car endorsement applies.",
    "Physician services are excluded.",
    "Intrinsic value is not covered.",
])
def test_an_accidental_substring_no_longer_grounds_a_sic_code(doc):
    """THE DEFECT. Every one of these satisfied `"sic" in raw_text.lower()`."""
    field = "NamedInsured_SICCode_A"
    mapped = {field: "7383"}
    dropped = _drop_ungrounded_classification_codes(
        mapped, doc + " rate class 7383", {field})
    assert dropped == [field]
    assert mapped[field] is None


@pytest.mark.parametrize("doc", [
    "SIC: 1761",
    "SIC Code 1761",
    "sic 1761",
    "(SIC) 1761",
])
def test_a_real_sic_label_still_grounds_the_code(doc):
    """COVERAGE PROTECTION. A genuinely stated SIC code must survive."""
    field = "NamedInsured_SICCode_A"
    mapped = {field: "1761"}
    dropped = _drop_ungrounded_classification_codes(mapped, doc, {field})
    assert dropped == []
    assert mapped[field] == "1761"


def test_naics_grounding_is_unchanged():
    field = "NamedInsured_NAICSCode_A"
    mapped = {field: "238160"}
    dropped = _drop_ungrounded_classification_codes(
        mapped, "NAICS: 238160", {field})
    assert dropped == []


def test_a_deterministic_classification_code_is_never_dropped():
    """Only values this run's gap-fill LLM authored are in scope."""
    field = "NamedInsured_SICCode_A"
    mapped = {field: "7383"}
    dropped = _drop_ungrounded_classification_codes(
        mapped, "basic coverage", set())
    assert dropped == []
    assert mapped[field] == "7383"
