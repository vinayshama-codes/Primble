"""
Regression tests for the Display Canonicalization layer
(Beta Report Sec 5 follow-up / Figure 26 trust feedback).

The canonicalizer produces the CLEAN value stamped onto ACORD forms. Unlike the
comparison normalizer (services/normalization.py), it must be NON-destructive:
it standardizes formatting while PRESERVING all content (entity suffix, unit
number, ZIP+4). These tests lock that contract in place.

Run from backend/:
    python tests/test_display_canonicalizer.py
or:
    python -m pytest tests/test_display_canonicalizer.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.display_canonicalizer import (  # noqa: E402
    canonicalize_date, canonicalize_currency, canonicalize_state,
    canonicalize_city, canonicalize_name, canonicalize_address,
    canonicalize_entity_type, category_for_field, canonicalize_for_field,
)


# ── Dates -> MM/DD/YYYY ───────────────────────────────────────────────────────

def test_date_formats_all_resolve_to_mmddyyyy():
    for raw in ("07/15/25", "7/15/2025", "2025-07-15", "07/15/2025"):
        assert canonicalize_date(raw) == "07/15/2025", raw


def test_date_unparseable_returned_unchanged():
    assert canonicalize_date("see policy") == "see policy"
    assert canonicalize_date("") == ""


# ── Currency -> $X,XXX ────────────────────────────────────────────────────────

def test_currency_variants_group_consistently():
    for raw in ("$1,000,000", "1000000", "1,000,000.00", "$1000000.0"):
        assert canonicalize_currency(raw) == "$1,000,000", raw


def test_currency_keeps_real_cents():
    assert canonicalize_currency("2500.50") == "$2,500.50"


def test_currency_non_numeric_unchanged():
    assert canonicalize_currency("TBD") == "TBD"


# ── State -> 2-letter uppercase ───────────────────────────────────────────────

def test_state_full_name_to_abbrev():
    assert canonicalize_state("Colorado") == "CO"
    assert canonicalize_state("new york") == "NY"


def test_state_already_abbrev_uppercased():
    assert canonicalize_state("co") == "CO"


def test_state_unknown_unchanged():
    assert canonicalize_state("Ontario") == "Ontario"


# ── Names: content PRESERVED, casing fixed ────────────────────────────────────

def test_name_keeps_llc_suffix_and_fixes_casing():
    # The whole point: LLC is KEPT (not stripped like the comparison key), and
    # ALL-CAPS OCR is title-cased.
    assert canonicalize_name("ORBIN CONTRACTING, LLC") == "Orbin Contracting, LLC"


def test_name_standardizes_word_suffix():
    assert canonicalize_name("acme cleaning services inc") == "Acme Cleaning Services Inc"


def test_name_preserves_internal_capitals():
    # McDonald must not become Mcdonald.
    assert canonicalize_name("McDonald Plumbing LLC") == "McDonald Plumbing LLC"


# ── Address: abbreviated, unit KEPT, ZIP+4 preserved ──────────────────────────

def test_address_abbreviated_and_unit_preserved():
    got = canonicalize_address("4800 DAHLIA STREET, SUITE D13")
    assert got == "4800 Dahlia St, Ste D13", got


def test_address_hash_unit_and_zip4_preserved():
    got = canonicalize_address("4800 dahlia st #D13, denver, colorado 80216-3121")
    # # unit kept, state uppercased, ZIP+4 intact (NOT truncated to ZIP5).
    assert got == "4800 Dahlia St #D13, Denver, CO 80216-3121", got


def test_address_directional_abbreviated():
    assert canonicalize_address("123 North Main Boulevard") == "123 N Main Blvd"


# ── Entity type -> canonical display ──────────────────────────────────────────

def test_entity_type_display_form():
    assert canonicalize_entity_type("LLC") == "Limited Liability Company"
    assert canonicalize_entity_type("limited liability company") == "Limited Liability Company"


def test_entity_type_unknown_unchanged():
    assert canonicalize_entity_type("Trust") == "Trust"


# ── Field-name category inference ─────────────────────────────────────────────

def test_category_inference_precedence():
    # City / state / postal sub-fields must resolve BEFORE the generic name/address.
    assert category_for_field("NamedInsured_MailingAddress_CityName_A") == "city"
    assert category_for_field("NamedInsured_MailingAddress_StateOrProvinceCode_A") == "state"
    assert category_for_field("NamedInsured_MailingAddress_PostalCode_A") is None
    assert category_for_field("NamedInsured_MailingAddress_LineOne_A") == "address"
    assert category_for_field("NamedInsured_FullName_A") == "name"
    assert category_for_field("Policy_EffectiveDate_A") == "date"
    assert category_for_field("CommercialStructure_AnnualRevenueAmount_A") == "currency"
    assert category_for_field("SomeCoverage_LimitCode_A") is None


# ── Dispatcher safety ─────────────────────────────────────────────────────────

def test_dispatcher_skips_checkboxes_and_empty():
    assert canonicalize_for_field("Foo_Indicator_A", "Yes") == "Yes"
    assert canonicalize_for_field("Foo_Indicator_A", "No") == "No"
    assert canonicalize_for_field("NamedInsured_FullName_A", None) is None
    assert canonicalize_for_field("NamedInsured_FullName_A", "") == ""


def test_dispatcher_untyped_field_untouched():
    # A field whose type can't be inferred is returned byte-for-byte unchanged.
    assert canonicalize_for_field("Random_ClassCode_A", "07 blah") == "07 blah"


def test_dispatcher_end_to_end():
    assert canonicalize_for_field("Policy_EffectiveDate_A", "7/15/25") == "07/15/2025"
    assert canonicalize_for_field(
        "NamedInsured_MailingAddress_LineOne_A", "4800 DAHLIA STREET, SUITE D13"
    ) == "4800 Dahlia St, Ste D13"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
