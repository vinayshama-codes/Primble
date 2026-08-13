"""Run 5 of the client's live document. Four defects, one question each time:

    "who is entitled to say this?"

1. `NamedInsured_Initials_A` - a text fragment where the insured initials. The
   tooltip literally reads "Initial here:". Initialling is signing, and the
   signature block was already closed to the machine; the initials box was not.

2. `Policy_SectionAttached_ElectronicDataProcessingIndicator_A` ticked because
   the inland-marine schedule mentions Electronic Data Processing. The box does
   not ask whether the policy has EDP coverage - it asks whether an ACORD EDP
   SECTION is attached to the application WE are producing. No model can know
   that. Four of the eight boxes in the family had no rule at all.

3. `Subsidiary_ParentSubsidiaryRelationshipDescription_A` filled with
   endorsement wording. The client's own rule, written for the Yes/No gate:
   "Never convert generic policy terminology into applicant-history facts." The
   gate never saw this because the gate only runs on Yes/No fields.

4. `Property` stayed ticked on a package whose dec page prints "PROPERTY - NO
   COVERAGE", because extraction attached the INLAND MARINE policy number to an
   entry it named "Property". Covered in test_entity_and_grant_guards.py.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                        # noqa: E402

_SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "..", "forms_schemas")


def _schema(form="ACORD_125"):
    with open(os.path.join(_SCHEMA_DIR, f"{form}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


# ── 1. Initialling is signing ────────────────────────────────────────────────

def test_the_insured_initials_box_is_closed_to_the_machine():
    assert ps._is_nonfillable_field("NamedInsured_Initials_A")


def test_a_middle_initial_is_still_an_ordinary_name_field():
    """THE LOAD-BEARING TEST. "Initial" appears inside a legitimate NAME field on
    ACORD 127; only the plural, whole-segment form is a signature."""
    assert not ps._is_nonfillable_field("Driver_OtherGivenNameInitial_A")
    assert not ps._is_nonfillable_field("NamedInsured_OtherGivenName_A")


def test_every_initials_field_on_every_form_is_covered():
    import glob
    boxes = {
        name
        for path in glob.glob(os.path.join(_SCHEMA_DIR, "*_schema.json"))
        for name in json.load(open(path, encoding="utf-8"))
        if "_Initials" in name
    }
    assert boxes, "harvest is empty - test would pass vacuously"
    assert all(ps._is_nonfillable_field(b) for b in boxes)


# ── 2. "Section attached" is a claim about our own package ───────────────────

UNMAPPED = [
    "ElectronicDataProcessing", "GlassAndSign", "Dealer",
    "AccountsReceivableValuablePapers",
]
MAPPED = ["OpenCargo", "VehicleSchedule", "DriverInformationSchedule",
          "InstallationBuildersRisk"]


@pytest.mark.parametrize("section", UNMAPPED)
def test_an_unmapped_section_box_is_never_handed_to_the_model(section):
    """THE REPORTED DEFECT. Deleting a rule is not enough - an unmapped field
    falls through to gap fill and gets ticked anyway (the Open Cargo lesson)."""
    field = f"Policy_SectionAttached_{section}Indicator_A"
    assert ps._deterministic_map(field, {}) is None
    assert ps._is_authoritative_blank_field(field, {})


@pytest.mark.parametrize("section", MAPPED)
def test_a_mapped_section_box_still_answers_from_its_own_rule(section):
    """COVERAGE PROTECTION. The new blanket rule must defer to every existing
    deterministic rule, or four boxes that fill correctly today go dark."""
    field = f"Policy_SectionAttached_{section}Indicator_A"
    assert not ps._is_authoritative_blank_field(field, {})
    assert ps._deterministic_map(field, {
        "has_open_cargo": True, "has_builders_risk": True,
        "auto_vin_schedule": [{"vin": "4S4BRCGC9C3217772"}],
        # A REAL driver-schedule row. This fixture used to read
        # `[{"name": "Erin Royal"}]`, which is not a driver schedule - it is
        # page 92's DRIVE OTHER CAR endorsement naming an individual, and it was
        # ticking this box on a package with no drivers (live 2026-08-13, the C22
        # decoy). The box now needs a row carrying more than a name; this test's
        # subject is that the MAPPED rule still answers, so the fixture gets a
        # licence number exactly as the vehicle fixture above gets a VIN.
        # See _schedule_has_substance and the two tests beneath this one.
        "auto_drivers": [{"name": "Erin Royal", "license_number": "12-345-6789"}],
    }) == "Yes"


def test_the_family_is_fully_partitioned_on_every_form():
    """STANDING GUARD. Every member of the family either has a rule or is
    closed. A new ACORD section can never quietly reopen to the model."""
    import glob
    boxes = {
        name
        for path in glob.glob(os.path.join(_SCHEMA_DIR, "*_schema.json"))
        for name in json.load(open(path, encoding="utf-8"))
        if ps._SECTION_ATTACHED_RE.match(name)
    }
    assert len(boxes) >= 8, f"harvest looks wrong: {len(boxes)}"
    for box in boxes:
        has_rule = box.rsplit("_", 1)[0] in ps._INDICATOR_RULES
        closed = ps._is_authoritative_blank_field(box, {})
        assert has_rule != closed, f"{box}: rule={has_rule} closed={closed}"


def test_a_coverage_indicator_is_not_caught_by_the_section_rule():
    """Only the SectionAttached family. An ordinary coverage checkbox that says
    something about the POLICY is a different question and stays fillable."""
    for field in ("Policy_LineOfBusiness_CommercialPropertyIndicator_A",
                  "CommercialPolicy_Attachment_ContractorsSupplementIndicator_A"):
        assert ps._resolve_section_attached_indicator(field, {}) is ps._SCHED_SKIP


# ── 3. The policy talking about itself, in a box about the applicant ─────────

CONTRACT_LANGUAGE = [
    "Bankruptcy or insolvency of the insured or the insured's estate will not "
    "relieve us of our obligations under this policy.",
    "This insurance does not apply to bodily injury arising out of the operation "
    "of any auto.",
    "We will not pay for loss caused by or resulting from any dishonest act "
    "committed by the insured.",
    "The following endorsement modifies coverage provided under this policy: "
    "subsidiaries and affiliated companies.",
    "Coverage is provided for any subsidiary in which the named insured owns "
    "more than 50% of the voting stock.",
]

APPLICANT_STATEMENTS = [
    "Orbin Contracting LLC is a wholly owned subsidiary of Orbin Holdings LLC.",
    "Commercial general contractor performing roofing and sheet metal work on "
    "residential and light commercial buildings.",
    "The parent company owns 100% of the applicant and provides administrative "
    "support only.",
    "Employee slipped on wet flooring at the Dahlia Street warehouse; medical "
    "only, closed 03/2024.",
    "We have had no claims in the past five years and carry no prior workers "
    "compensation coverage.",
    "Applicant leases three trucks from Ryder System under a long term full "
    "service lease agreement.",
    "The trust holds title to the premises at 4800 Dahlia Street and is named as "
    "loss payee.",
    "All subcontractors are required to carry their own general liability "
    "insurance and name the applicant as additional insured.",
    "Operations include installation of metal roofing systems; no work is "
    "performed above three stories.",
    "Applicant does not own or rent any parking facilities at any of its "
    "locations.",
]

NARRATIVE = "Subsidiary_ParentSubsidiaryRelationshipDescription_A"


@pytest.mark.parametrize("clause", CONTRACT_LANGUAGE)
def test_contract_language_never_becomes_an_applicant_fact(clause):
    assert ps._is_policy_contract_language(NARRATIVE, clause)


@pytest.mark.parametrize("statement", APPLICANT_STATEMENTS)
def test_a_real_applicant_statement_survives(statement):
    """THE LOAD-BEARING TEST. The anchors are the INSURER speaking as a party,
    never a topic word, so an applicant writing about coverage, subsidiaries or
    claims is untouched."""
    assert not ps._is_policy_contract_language(NARRATIVE, statement)


def test_acord_101_remarks_may_carry_policy_text():
    """ACORD 101's overflow rows exist to hold exactly this."""
    assert not ps._is_policy_contract_language(
        "AdditionalRemarks_Remark_A", CONTRACT_LANGUAGE[0])


def test_a_short_coincidental_match_is_left_alone():
    """Below the length floor a match is a coincidence, not a clause."""
    assert not ps._is_policy_contract_language(NARRATIVE, "We will pay")


def test_empty_and_malformed_values_are_survivable():
    for value in (None, "", "   ", 0, []):
        assert not ps._is_policy_contract_language(NARRATIVE, value)


def test_the_guard_only_ever_reads_gap_fill_values():
    """SCOPE. The blanking loop iterates `gpt_filled_set`, so a deterministic or
    client-supplied narrative can never be removed by it - the same scoping the
    impossible-value guard uses."""
    import inspect
    src = inspect.getsource(ps.map_facts_to_form)
    marker = "if _is_policy_contract_language(_f, mapped.get(_f)):"
    assert marker in src
    preceding = src[:src.index(marker)]
    assert preceding.rstrip().endswith("for _f in list(gpt_filled_set):")
