"""
Regression tests for two address-resolution bugs found during live production
testing on a generated ACORD 125 (Figure 26 client feedback: "address...
producer details... must be exact").

Bug 1 - _parse_address() (utils/helpers.py) silently dropped the middle segment
        of a 4-part address ("Street, Suite, City, ST ZIP") - a Suite/Unit
        never appeared anywhere on the stamped form.
Bug 2 - _deterministic_map() (services/pdf_service.py) resolved EVERY entity's
        mailing address (Producer / AdditionalInterest / CertificateHolder)
        from the NAMED INSURED's mailing_address fact, because extraction never
        captures a separate fact for those entities. This stamped the wrong
        entity's address onto the form (observed live: Producer's address block
        showed a mix of the Named Insured's street/city/zip).

Run from backend/:
    python tests/test_address_resolution.py
or:
    python -m pytest tests/test_address_resolution.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.helpers import _parse_address                    # noqa: E402
from services.pdf_service import _deterministic_map, fact_to_form_fields  # noqa: E402


# ── Bug 1: Suite/Unit must never be dropped ────────────────────────────────────

def test_four_part_address_keeps_suite_on_line2():
    p = _parse_address("7740 Foundry Lane, Suite 310, Aurora, Colorado 80011-2245")
    assert p["line1"] == "7740 Foundry Lane"
    assert p["line2"] == "Suite 310"
    assert p["city"] == "Aurora"
    assert p["zip"] == "80011-2245"


def test_three_part_address_unchanged_no_line2():
    # Regression guard: the ordinary "Street, City, ST ZIP" case (no unit) must
    # NOT gain a spurious line2.
    p = _parse_address("4800 Dahlia St, Denver, CO 80216")
    assert "line2" not in p
    assert p["line1"] == "4800 Dahlia St"
    assert p["city"] == "Denver"


def test_two_part_address_unchanged():
    # Regression guard: the 2-part branch is untouched by this fix.
    p = _parse_address("123 Main St, Littleton CO 80127")
    assert "line2" not in p
    assert p["city"] == "Littleton"


# ── Bug 2: mailing_address must only resolve NamedInsured_* fields ────────────

_FACTS = {
    "mailing_address": "7740 Foundry Lane, Suite 310, Aurora, Colorado 80011-2245",
    "physical_address": "7740 Foundry Lane, Suite 310, Aurora, Colorado 80011-2245",
}


def test_producer_address_no_longer_pulls_named_insured_address():
    for field in (
        "Producer_MailingAddress_LineOne_A",
        "Producer_MailingAddress_CityName_A",
        "Producer_MailingAddress_PostalCode_A",
    ):
        assert _deterministic_map(field, _FACTS) == "UNMATCHED", field


def test_additional_interest_and_certificate_holder_also_excluded():
    for field in (
        "AdditionalInterest_MailingAddress_CityName_A",
        "CertificateHolder_MailingAddress_CityName_A",
    ):
        assert _deterministic_map(field, _FACTS) == "UNMATCHED", field


def test_named_insured_own_address_still_resolves_correctly():
    assert _deterministic_map("NamedInsured_MailingAddress_LineOne_A", _FACTS) == "7740 Foundry Lane"
    assert _deterministic_map("NamedInsured_MailingAddress_LineTwo_A", _FACTS) == "Suite 310"
    assert _deterministic_map("NamedInsured_MailingAddress_CityName_A", _FACTS) == "Aurora"


def test_physical_address_loc_path_unaffected_by_entity_scoping():
    # "_loc_*" (physical/premises address) has only one legitimate meaning -
    # the insured's own premises - so it must NOT be restricted the same way.
    assert _deterministic_map("NamedInsured_PhysicalAddress_CityName_A", _FACTS) == "Aurora"


def test_fact_to_form_fields_excludes_producer_from_mailing_address():
    # field_qa's value-vs-source check relies on this: a Producer field is no
    # longer "deterministically fed by mailing_address" (it's gap-filled from
    # its own raw text), so it must not be compared against the wrong fact.
    mapping = fact_to_form_fields("mailing_address")
    if not mapping:
        return
    _, fields = next(iter(mapping.items()))
    assert not any(f.startswith("Producer_") for f in fields)
    assert not any(f.startswith("AdditionalInterest_") for f in fields)
    assert not any(f.startswith("CertificateHolder_") for f in fields)
    assert any(f.startswith("NamedInsured_") for f in fields)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
