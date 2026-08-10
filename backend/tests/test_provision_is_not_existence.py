"""A coverage provision is not proof the entity or condition exists.

Client feedback, Parts 11 and 12. Their summary of the whole class:

  "Primble is treating policy language describing who COULD be covered as
   evidence that the entity or condition EXISTS."
  "An endorsement covering subsidiaries does not prove that subsidiaries exist."

Three defects, one theme:

1. EMC Insurance Companies stamped as an ADDITIONAL INSURED, with its servicing
   address and a phone number, on the policy it services. Primble had found
   blanket additional-insured wording ("parties required by written contract may
   qualify") and treated the insurer as the named interest.
2. "parent company" / 50% owned / "subsidiary" filled in, with NO parent or
   subsidiary NAME anywhere - inferred from a blanket endorsement that merely
   says a qualifying subsidiary WOULD be covered.
3. The same Commercial Auto policy listed twice in "other insurance", once in
   the declarations format "6E7-40-02---26" and once in the compact internal
   form "6E74002".

The first two share a mechanism with the orphan Named Insured row: a detail box
whose SUBJECT is unnamed asserts nothing. The difference here is that an
additional interest is OPTIONAL, so unlike the Named Insured its row A gets the
same treatment.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                        # noqa: E402

_SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "..", "forms_schemas")


def _acord125():
    with open(os.path.join(_SCHEMA_DIR, "ACORD_125_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


# ── 1. An unnamed additional interest ────────────────────────────────────────

EMC_ROW = {
    "AdditionalInterest_FullName_A": "",
    "AdditionalInterest_MailingAddress_LineOne_A": "5445 Dtc Pkwy, Ste 320",
    "AdditionalInterest_MailingAddress_CityName_A": "Greenwood Village",
    "AdditionalInterest_Primary_PhoneNumber_A": "720-200-3700",
    "AdditionalInterest_InterestReasonDescription_A": "additional insured",
}


def test_an_unnamed_additional_interest_row_is_flagged():
    """Row A included, unlike the Named Insured: an additional interest is
    OPTIONAL, so there is no guarantee row A is a real record."""
    flagged = ps._unanchored_entity_row_fields(EMC_ROW, _acord125())
    assert "AdditionalInterest_MailingAddress_LineOne_A" in flagged
    assert "AdditionalInterest_Primary_PhoneNumber_A" in flagged
    assert "AdditionalInterest_InterestReasonDescription_A" in flagged


def test_a_named_additional_interest_is_untouched():
    """A real lienholder or loss payee must keep every one of its details."""
    named = dict(EMC_ROW, AdditionalInterest_FullName_A="Wells Fargo Equipment Finance")
    assert ps._unanchored_entity_row_fields(named, _acord125()) == set()


def test_the_named_insured_row_a_is_still_never_questioned():
    """The distinction that makes this safe: the form IS about the named
    insured, so their row A always exists."""
    mapped = {"NamedInsured_FullName_A": "", "NamedInsured_TaxIdentifier_A": "84-2210987"}
    assert ps._unanchored_entity_row_fields(mapped, _acord125()) == set()


def test_optional_entity_list_is_bounded():
    assert set(ps._OPTIONAL_ENTITY_PREFIXES) == {"AdditionalInterest", "CertificateHolder"}
    for prefix in ps._OPTIONAL_ENTITY_PREFIXES:
        assert prefix in ps._FIELD_ENTITY_PREFIXES


# ── 2. Parent / subsidiary detail with nobody named ──────────────────────────

def test_parent_detail_without_a_parent_name_is_flagged():
    """Client: "Nothing in the declarations identifies a parent company or says
    that Orbin Contracting is 50% owned by another entity." """
    mapped = {
        "BusinessInformation_ParentOrganizationName_A": "",
        "Subsidiary_ParentSubsidiaryRelationshipDescription_A": "parent company",
        "Subsidiary_ParentOwnershipPercent_A": "50%",
    }
    assert ps._unanchored_detail_fields(mapped, _acord125()) == {
        "Subsidiary_ParentSubsidiaryRelationshipDescription_A",
        "Subsidiary_ParentOwnershipPercent_A",
    }


def test_subsidiary_detail_without_a_subsidiary_name_is_flagged():
    """Client: "An endorsement covering subsidiaries does not prove that
    subsidiaries exist." """
    mapped = {
        "Subsidiary_OrganizationName_A": "",
        "Subsidiary_ParentSubsidiaryRelationshipDescription_B": "subsidiary",
        "Subsidiary_ParentOwnershipPercent_B": "100%",
    }
    flagged = ps._unanchored_detail_fields(mapped, _acord125())
    assert "Subsidiary_ParentSubsidiaryRelationshipDescription_B" in flagged
    assert "Subsidiary_ParentOwnershipPercent_B" in flagged


def test_a_real_parent_keeps_its_detail():
    mapped = {
        "BusinessInformation_ParentOrganizationName_A": "Orbin Holdings LLC",
        "Subsidiary_ParentSubsidiaryRelationshipDescription_A": "Wholly owned operating subsidiary",
        "Subsidiary_ParentOwnershipPercent_A": "100%",
    }
    assert ps._unanchored_detail_fields(mapped, _acord125()) == set()


def test_anchored_groups_reference_real_fields():
    """A typo silently disables the guard for that group."""
    schema = _acord125()
    for anchor, dependents in ps._ANCHORED_DETAIL_GROUPS:
        assert anchor in schema, anchor
        for field in dependents:
            assert field in schema, field


# ── 3. The same policy listed twice ──────────────────────────────────────────

def test_the_compact_policy_number_is_removed():
    """Client: "These two entries are the same policy: 6E7-40-02---26 and
    6E74002... Keep only 6E7-40-02---26." Equality fails here - "6E740026" vs
    "6E74002" - so the comparison is by PREFIX."""
    mapped = {
        "OtherPolicy_PolicyNumberIdentifier_A": "6E7-40-02---26",
        "OtherPolicy_LineOfBusinessCode_A": "Commercial Auto",
        "OtherPolicy_PolicyNumberIdentifier_B": "BBC7263",
        "OtherPolicy_LineOfBusinessCode_B": "General Liability",
        "OtherPolicy_PolicyNumberIdentifier_C": "6E74002",
        "OtherPolicy_LineOfBusinessCode_C": "",
    }
    ps._enforce_post_fill_guards(mapped, _acord125(), {})
    assert mapped["OtherPolicy_PolicyNumberIdentifier_A"] == "6E7-40-02---26"
    assert mapped["OtherPolicy_PolicyNumberIdentifier_C"] is None
    # The other line keeps its own entry.
    assert mapped["OtherPolicy_PolicyNumberIdentifier_B"] == "BBC7263"


def test_the_declarations_format_wins_whichever_row_it_is_in():
    """Client asked for "the consistent declarations-page format"."""
    mapped = {
        "OtherPolicy_PolicyNumberIdentifier_A": "BBC7263",
        "OtherPolicy_PolicyNumberIdentifier_B": "BBC7263-26",
    }
    ps._enforce_post_fill_guards(mapped, _acord125(), {})
    assert mapped["OtherPolicy_PolicyNumberIdentifier_A"] is None
    assert mapped["OtherPolicy_PolicyNumberIdentifier_B"] == "BBC7263-26"


def test_genuinely_different_policies_are_all_kept():
    """THE LOAD-BEARING TEST. This removes a duplicate, never a real policy."""
    mapped = {
        "OtherPolicy_PolicyNumberIdentifier_A": "BBC7263-26",
        "OtherPolicy_PolicyNumberIdentifier_B": "6E7-40-02---26",
        "OtherPolicy_PolicyNumberIdentifier_C": "CPP1234567",
    }
    before = dict(mapped)
    ps._enforce_post_fill_guards(mapped, _acord125(), {})
    assert mapped == before


@pytest.mark.parametrize("a,b", [("12345", "123456"), ("AB12", "AB1234")])
def test_short_numbers_are_never_collapsed(a, b):
    """Below the 6-character floor a prefix match is meaningless."""
    mapped = {
        "OtherPolicy_PolicyNumberIdentifier_A": a,
        "OtherPolicy_PolicyNumberIdentifier_B": b,
    }
    ps._enforce_post_fill_guards(mapped, _acord125(), {})
    assert mapped["OtherPolicy_PolicyNumberIdentifier_A"] == a
