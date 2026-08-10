"""Fields no automated pass may ever fill: signatures and attestations.

Client report (ACORD 125, Orbin Contracting):
  #20 "Primble appears to have populated the producer signature. The signature
      field contains ERIN ROYAL. That should never be automatically inferred
      from the producer's name."
  #19 "Privacy-notice confirmation needs an actual agency action. Retain it only
      if the agency actually provided the required notice to the applicant."

A signature and an attestation are ACTIONS, not values found in a document.
This is the one place in this whole workstream where blank is the only correct
answer - no confidence colour makes an auto-signed application acceptable.

`map_facts_to_form` has always blanked signature fields via
`_is_nonfillable_field`. The hole was elsewhere: `arq_service`'s two restamp
paths write a client-confirmed value straight into any schema field whose
canonical key matches, and neither consulted that rule.
`Producer_AuthorizedRepresentative_Signature_A` resolves to a contact-name
canonical, and "Who is the main person we should contact about this insurance
application?" is a TIER 1 question asked of every client - so answering it wrote
that name into the producer's signature box, labelled `client_arq` (green,
"client supplied").
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                        # noqa: E402
import services.arq_service as arq                       # noqa: E402

SIGNATURE_FIELDS = (
    "Producer_AuthorizedRepresentative_Signature_A",
    "NamedInsured_Signature_A",
    "NamedInsured_SignatureDate_A",
)
ATTESTATION_FIELDS = ("Policy_InformationPracticesNoticeIndicator_A",)


@pytest.mark.parametrize("field", SIGNATURE_FIELDS + ATTESTATION_FIELDS)
def test_never_fillable(field):
    assert ps._is_nonfillable_field(field) is True


def test_the_producer_signature_still_resolves_to_a_canonical_fact():
    """The hole was NOT that the field was unmapped - it maps to a real fact.
    Guarding it has to happen at the restamp, not by hoping nothing matches."""
    assert arq._canonical_key(
        "Producer_AuthorizedRepresentative_Signature_A") is not None


def test_arq_restamp_refuses_to_sign_the_form():
    """THE CLIENT'S CASE. A confirmed contact name must not reach the signature
    box, even though the canonical key matches it."""
    generated = {
        "ACORD_125": {
            "schema": {
                "Producer_AuthorizedRepresentative_Signature_A": {"ft": "/Tx"},
                "Producer_ContactPerson_FullName_A": {"ft": "/Tx"},
            },
            "field_state": {},
            "confidence": {},
        }
    }
    facts = {"producer_contact_name": "Erin Royal"}
    arq._restamp_canonical_into_forms(generated, "producer_contact_name", facts)
    state = generated["ACORD_125"]["field_state"]
    assert state.get("Producer_AuthorizedRepresentative_Signature_A") is None, (
        "the form was auto-signed"
    )
    # ...while the legitimate box for that fact still receives it.
    assert state.get("Producer_ContactPerson_FullName_A") == "Erin Royal"


def test_backfill_path_also_refuses():
    """There are TWO restamp paths and both had the hole."""
    generated = {
        "ACORD_125": {
            "schema": {"Producer_AuthorizedRepresentative_Signature_A": {"ft": "/Tx"}},
            "field_state": {},
            "confidence": {},
        }
    }
    arq._backfill_and_resolve_present(generated, {"producer_contact_name": "Erin Royal"})
    assert generated["ACORD_125"]["field_state"].get(
        "Producer_AuthorizedRepresentative_Signature_A") is None


def test_attestation_is_blocked_on_every_form_that_has_one():
    """Verified across all 17 schemas: ACORD 125 and 130 carry this box."""
    import glob
    import json
    found = 0
    for path in glob.glob(os.path.join(os.path.dirname(__file__), "..",
                                       "forms_schemas", "*_schema.json")):
        with open(path, encoding="utf-8") as fh:
            for field, meta in json.load(fh).items():
                tu = ((meta or {}).get("tu") or "").lower()
                if "notice of information practices" in tu:
                    found += 1
                    assert ps._is_nonfillable_field(field), (
                        f"{field} is an agency attestation and must never be filled"
                    )
    assert found == 2, f"expected 2 attestation boxes across 17 forms, found {found}"


def test_ordinary_fields_are_unaffected():
    """The block must stay narrow - this is the only justified blank."""
    for field in ("NamedInsured_FullName_A", "Producer_ContactPerson_FullName_A",
                  "Policy_EffectiveDate_A", "CommercialPolicy_OperationsDescription_A"):
        assert ps._is_nonfillable_field(field) is False


def test_glass_and_sign_is_not_mistaken_for_a_signature():
    """"Sign" appears inside "GlassAndSign". A naive substring would blank a real
    coverage checkbox."""
    assert ps._is_nonfillable_field(
        "Policy_SectionAttached_GlassAndSignIndicator_A") is False
