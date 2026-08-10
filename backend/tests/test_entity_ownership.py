"""Entity ownership of facts: one party's value must never fill another's box.

Client report (ACORD 125, Orbin Contracting, 2026-08-08/09):
  * "The insured phone is 303-996-7800, which is the producer's phone number."
  * "The website is www.emcins.com, which appears to be the insurer's website."
  * "CONTACT INFORMATION - not populating correctly; it looks like a mixture of
     client and carrier information."
  * "Fax: 303-996-7800 ... appears copied from the producer's phone."

None of that was a model hallucination. `_ACORD_FIELD_RULES` mapped ONE fact into
several different parties' boxes on purpose: `contact_phone` fed
Producer_ContactPerson_Phone AND NamedInsured_PhoneNumber AND
NamedInsured_Primary_PhoneNumber AND NamedInsured_Contact_PrimaryPhoneNumber.

See `fix-form-stamping.md` (repo root) for the full mechanism write-up.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                       # noqa: E402
from services.fact_registry import (                     # noqa: E402
    FACT_REGISTRY, _is_email, _is_phone, _is_url,
)


# ── The client's literal values ──────────────────────────────────────────────
# Per the `replay-client-report-verbatim` rule: reproduce with the reported
# strings, not a tidied-up equivalent.
PRODUCER_PHONE = "303-996-7800"
CARRIER_SITE = "Www.emcins.com"
PRODUCER_CONTACT = "Erin Royal"


def test_client_reported_case_producer_phone_does_not_reach_the_applicant():
    """The decisive test. One phone number, labelled to the producer."""
    facts = {
        "producer_contact_phone": PRODUCER_PHONE,
        "producer_contact_name": PRODUCER_CONTACT,
        "carrier_website": CARRIER_SITE,
    }
    # The party that owns it still gets it - the fix must not cost fill.
    assert ps._deterministic_map(
        "Producer_ContactPerson_PhoneNumber_A", facts) == PRODUCER_PHONE

    # The applicant's boxes stay empty rather than borrowing.
    for field in (
        "NamedInsured_PhoneNumber_A",
        "NamedInsured_Primary_PhoneNumber_A",
        "NamedInsured_Contact_PrimaryPhoneNumber_A",
        "NamedInsured_Primary_WebsiteAddress_A",
    ):
        got = ps._deterministic_map(field, facts)
        assert got in (None, "", "UNMATCHED"), (
            f"{field} was filled with another party's value: {got!r}"
        )


def test_fax_is_not_derived_from_the_phone():
    """Client #1: a fax is only a fax when the document says so."""
    facts = {"producer_contact_phone": PRODUCER_PHONE}
    assert ps._deterministic_map("Producer_FaxNumber_A", facts) in (None, "", "UNMATCHED")
    facts["producer_fax"] = "303-996-7801"
    assert ps._deterministic_map("Producer_FaxNumber_A", facts) == "303-996-7801"


@pytest.mark.parametrize("field,fact", [
    ("Producer_ContactPerson_Phone_A", "contact_phone"),
    ("Producer_ContactPerson_EmailAddress_A", "contact_email"),
    ("Producer_ContactPerson_FullName_A", "contact_name"),
    ("NamedInsured_PhoneNumber_A", "producer_contact_phone"),
    ("NamedInsured_Primary_WebsiteAddress_A", "carrier_website"),
    ("Insurer_FullName_A", "applicant_name"),
    ("AdditionalInterest_FullName_A", "carrier_name"),
])
def test_guard_fires_on_every_cross_party_pairing(field, fact):
    assert ps._entity_mismatch(field, fact) is True


@pytest.mark.parametrize("field,fact", [
    ("Producer_ContactPerson_Phone_A", "producer_contact_phone"),
    ("NamedInsured_PhoneNumber_A", "contact_phone"),
    ("Insurer_FullName_A", "carrier_name"),
    ("NamedInsured_FullName_A", "applicant_name"),
    # Unowned fields must never be constrained - these carry most of the form.
    ("BusinessInformation_NumberOfEmployees_A", "num_employees"),
    ("CommercialPolicy_OperationsDescription_A", "operations_description"),
    ("Policy_EffectiveDate_A", "effective_date"),
])
def test_guard_is_silent_on_legitimate_pairings(field, fact):
    assert ps._entity_mismatch(field, fact) is False


def test_no_live_rule_stamps_across_parties():
    """THE STANDING GUARD. Sweeps every rule against every real schema field on
    all 17 forms and fails if any pairing crosses a party boundary - so the next
    person to add a row to `_ACORD_FIELD_RULES` cannot reintroduce this."""
    offenders = []
    for form_id, schema in ps._all_form_schemas().items():
        for field in schema:
            fact = None
            for pattern, fk in ps._ACORD_FIELD_RULES:
                if pattern in field:
                    fact = fk
                    break
            if fact and ps._entity_mismatch(field, fact):
                offenders.append(f"{form_id}:{field} <- {fact}")
    assert not offenders, (
        "these rules stamp one party's fact into another party's box:\n  "
        + "\n  ".join(sorted(set(offenders)))
    )


def test_every_owned_fact_exists_in_the_registry():
    """A typo in _FACT_ENTITY would silently disable the guard for that fact."""
    missing = [f for f in ps._FACT_ENTITY if f not in FACT_REGISTRY]
    assert not missing, f"_FACT_ENTITY names facts that do not exist: {missing}"


def test_entity_prefixes_are_real_acord_prefixes():
    """Guards against a prefix typo making _field_entity always return None."""
    all_fields = {f for s in ps._all_form_schemas().values() for f in s}
    for prefix in ps._FIELD_ENTITY_PREFIXES:
        assert any(f.startswith(prefix) for f in all_fields), (
            f"_FIELD_ENTITY_PREFIXES contains {prefix!r}, which matches no field "
            f"in any of the 17 schemas"
        )


# ── Shape validators the client's report needed ──────────────────────────────

def test_shape_validators_reject_the_client_reported_values():
    assert _is_email("ERIN ROYAL") is False              # client #1
    assert _is_email("Claim Reporting: (888) 362-2255") is False   # client #11
    assert _is_url("ERIN ROYAL") is False
    assert _is_phone("ERIN ROYAL") is False


def test_shape_validators_accept_real_values():
    assert _is_email("erin.royal@crsinc.com") is True
    assert _is_phone(PRODUCER_PHONE) is True
    assert _is_phone("(303)996-7800") is True
    assert _is_url(CARRIER_SITE) is True                 # capitalised, as printed
    assert _is_url("https://orbincontracting.com/about") is True


def test_phone_validator_requires_actual_digits():
    """The pattern it replaced accepted punctuation-only strings."""
    assert _is_phone("(   )   -    ") is False
    assert _is_phone("----------") is False
