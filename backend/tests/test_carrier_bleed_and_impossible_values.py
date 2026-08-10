"""Carrier-group data reaching applicant fields through the gap-fill path.

Three defects that survived four consecutive live runs, all with the same shape:
the gap-fill LLM had no reason not to use a value, and every ownership guard we
had compared against a value we ALREADY HELD.

1. `Emcasco Insurance Company` - a member of the carrier's GROUP, never named as
   the carrier itself - in the applicant's SUBSIDIARY box, off the back of an
   endorsement listing group companies. No comparison against `carrier_name`
   could ever have caught it, because the two strings share nothing.

2. `0482854` - the carrier's ACCOUNT number - in the FEIN box, four runs
   running. It was correctly DEMOTED to orange each time, so we stopped claiming
   it was verified, but the value kept landing. A 7-digit string in a 9-digit
   federal tax ID box is not "uncertain", it is impossible.

3. `PRODUCER'S NAME (Please Print)` came back "Scott R. Jean" on one run and
   "Todd A. Strother" on the next, from the SAME document - EMC executives named
   in policy boilerplate. The box reads `producer_contact_name`, and when that
   fact is absent it fell through to gap fill, where the only personal names in
   a declarations package belong to the carrier.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                        # noqa: E402


# ── 1. A carrier by SHAPE, not by matching a value we hold ───────────────────

@pytest.mark.parametrize("name", [
    "Emcasco Insurance Company",
    "Employers Mutual Casualty Company",
    "EMC Property & Casualty Company",
    "Hartford Fire Insurance Co.",
    "Zurich American Insurance Corporation",
    "Berkley Risk Retention Group",
])
def test_an_insurance_carrier_is_recognised_by_shape(name):
    assert ps._looks_like_an_insurance_carrier(name)


@pytest.mark.parametrize("name", [
    "Orbin Contracting LLC",
    "Orbin Holdings LLC",
    "Ridgeline Roofing & Sheet Metal LLC",
    # The tricky ones - a bare "insurance", "mutual", "underwriting" or
    # "casualty" must NOT qualify.
    "Summit Insurance Agency, Inc.",
    "Denver Mutual Water Company",
    "Front Range Underwriting Services LLC",
    "Casualty Restoration Services LLC",
    "Acme Manufacturing Co.",
])
def test_a_real_applicant_name_is_never_mistaken_for_a_carrier(name):
    """THE LOAD-BEARING TEST. Anchored on insurer noun PHRASES, never a bare
    word."""
    assert not ps._looks_like_an_insurance_carrier(name)


def test_the_live_run_subsidiary_bleed_is_blanked():
    facts = {"applicant_name": "Orbin Contracting LLC",
             "carrier_name": "Employers Mutual Casualty Company"}
    mapped = {
        "Subsidiary_OrganizationName_A": "Emcasco Insurance Company",
        "NamedInsured_FullName_A": "Orbin Contracting LLC",
        "BusinessInformation_ParentOrganizationName_A": "Orbin Holdings LLC",
    }
    ps._drop_foreign_entity_values(mapped, facts, set(mapped))
    assert mapped["Subsidiary_OrganizationName_A"] is None
    # The applicant's own values are untouched.
    assert mapped["NamedInsured_FullName_A"] == "Orbin Contracting LLC"
    assert mapped["BusinessInformation_ParentOrganizationName_A"] == "Orbin Holdings LLC"


def test_an_applicant_that_really_is_an_insurance_business_is_protected():
    """If the APPLICANT itself is carrier-shaped, the check stands down - it
    cannot tell the applicant from a foreign carrier, so it must not guess."""
    facts = {"applicant_name": "Summit Insurance Company"}
    mapped = {"NamedInsured_FullName_A": "Summit Insurance Company"}
    ps._drop_foreign_entity_values(mapped, facts, set(mapped))
    assert mapped["NamedInsured_FullName_A"] == "Summit Insurance Company"


def test_a_deterministic_value_is_never_touched():
    """Only GAP-FILL values are in scope."""
    facts = {"applicant_name": "Orbin Contracting LLC"}
    mapped = {"Subsidiary_OrganizationName_A": "Emcasco Insurance Company"}
    ps._drop_foreign_entity_values(mapped, facts, set())      # empty gpt set
    assert mapped["Subsidiary_OrganizationName_A"] == "Emcasco Insurance Company"


# ── 2. An impossible value is refused, not coloured ──────────────────────────

@pytest.mark.parametrize("value", ["0482854", "W6258-0001", "84-22109871", "abc"])
def test_an_impossible_fein_is_rejected(value):
    assert ps._shape_violation("NamedInsured_TaxIdentifier_A", value) is not None


@pytest.mark.parametrize("value", ["84-2210987", "842210987"])
def test_a_real_fein_is_accepted(value):
    assert ps._shape_violation("NamedInsured_TaxIdentifier_A", value) is None


def test_only_the_four_hard_shapes_can_blank_a_value():
    """Everything else still DEMOTES rather than blanks - "stamp it and
    highlight it" remains the rule for anything merely uncertain. An amount box
    holding "Statutory" must never be blanked (C22)."""
    for field, value in (
        ("GeneralLiability_EachOccurrenceLimit_A", "Statutory"),
        ("CommercialPolicy_OperationsDescription_A", "Commercial general contractor"),
        ("Policy_EffectiveDate_A", "07/15/2025"),
    ):
        assert ps._shape_violation(field, value) is None


# ── 3. The producer's printed name ───────────────────────────────────────────

PRINTED = "Producer_AuthorizedRepresentative_FullName_A"


def test_the_printed_name_uses_the_producer_contact_we_hold():
    assert ps._deterministic_map(PRINTED, {"producer_contact_name": "Erin Royal"}) == "Erin Royal"


def test_without_a_producer_contact_the_box_stays_empty():
    """A signature block identifies the person signing. If we do not know who
    the producer contact is, no model may nominate one - and the only names in a
    declarations package belong to the carrier."""
    assert ps._deterministic_map(
        PRINTED, {"carrier_name": "Employers Mutual Casualty Company"}) is None


def test_the_printed_name_is_never_handed_to_gap_fill():
    """Without this the box is refilled from raw text and flips between runs."""
    assert ps._is_authoritative_blank_field(PRINTED, {})


def test_the_signature_itself_remains_non_fillable():
    """The printed name is now anchored; the signature was already blocked."""
    assert ps._is_nonfillable_field("Producer_AuthorizedRepresentative_Signature_A")
