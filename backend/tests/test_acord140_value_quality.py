"""
Regression tests for two data-quality fixes found during live ACORD 140
testing (2026-07-17), both cosmetic/consistency defects rather than the
placeholder-echo or row-duplication bugs fixed earlier:

  1. ValuationCode inconsistency: a deterministically-filled row showed "RCV"
     while a gap-filled row (for the exact same concept) showed "R" - because
     the real ACORD 140/141 ValuationCode field's own tooltip documents a
     SINGLE-LETTER code (A/R/V/M), but the Pass 1 flat-rule mapping stamped
     the extraction-normalized 3-letter industry term ("RCV"/"ACV") verbatim
     instead of translating it. Fixed in _deterministic_map.

  2. A tooltip-declared "Enter number:" field (CommercialProperty_Summary_
     BlanketNumberIdentifier) came back filled with "Location 1"/"Location 2"
     - a real value, just the wrong entity's label, not a blanket grouping
     number. The existing wrong-type guard (_is_numeric_or_date_field)
     deliberately excludes "Number" field names (policy numbers are
     legitimately alphanumeric), so this specific class of error needed a
     tooltip-based check instead. Fixed as a new branch in Guard 3
     (_enforce_post_fill_guards).

Also covers two follow-up fixes found in the SAME live re-test after the two
above landed (2026-07-17, round 2):

  3. The ValuationCode fix above created a NEW false positive: field_qa's
     value-vs-source check compared the now-correctly-stamped "R" against the
     untranslated raw fact "RCV" and flagged a mismatch. Fixed with a
     dedicated, narrowly-scoped normalizer (services.normalization.
     normalize_valuation_method) so "R"/"RCV"/"Replacement Cost" all compare
     equal - deliberately NOT added to the generic synonym table, since a
     bare "R"/"A" would collide with unrelated fields' legitimate values.

  4. Guard 2 (repeating-row de-duplication) exempted the ENTIRE Subject-of-
     Insurance field pair (SubjectOfInsuranceCode AND LimitAmount) from
     duplicate-value blanking, reasoning that both "may legitimately repeat".
     True for SubjectOfInsuranceCode ("Building" at 2 different locations is
     normal) but not for LimitAmount (two different locations sharing the
     EXACT same dollar figure as row A is a real bug, not a coincidence) - a
     live test showed row A's amount duplicated into a later row with nothing
     catching it. Narrowed the exemption to SubjectOfInsuranceCode only.

Run from backend/:
    python tests/test_acord140_value_quality.py
or:
    python -m pytest tests/test_acord140_value_quality.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.pdf_service import (  # noqa: E402
    _deterministic_map, _enforce_post_fill_guards,
    _tooltip_declares_number, _looks_like_declared_number_value,
)
from services.normalization import normalize_value  # noqa: E402
from services.field_qa import run_field_qa  # noqa: E402


# ── ValuationCode: RCV/ACV -> single-letter ACORD code ──────────────────────

def test_valuation_code_rcv_translates_to_r():
    facts = {"valuation_method": "RCV"}
    assert _deterministic_map("CommercialProperty_Premises_ValuationCode_A", facts) == "R"


def test_valuation_code_acv_translates_to_a():
    facts = {"valuation_method": "ACV"}
    assert _deterministic_map("CommercialProperty_Premises_ValuationCode_A", facts) == "A"


def test_valuation_code_lowercase_and_whitespace_tolerant():
    # The lookup key is stripped+lowercased before matching, so extraction
    # variance in case/whitespace still resolves to the correct ACORD code.
    assert _deterministic_map("CommercialProperty_Premises_ValuationCode_A", {"valuation_method": "  rcv  "}) == "R"
    assert _deterministic_map("CommercialProperty_Premises_ValuationCode_A", {"valuation_method": "rcv"}) == "R"
    assert _deterministic_map("CommercialProperty_Premises_ValuationCode_A", {"valuation_method": "Acv"}) == "A"


def test_valuation_code_unrecognized_value_passes_through_unchanged():
    # Defensive: an unexpected valuation_method value must never be silently
    # dropped or corrupted - only the two known industry terms are translated.
    facts = {"valuation_method": "Agreed Value"}
    assert _deterministic_map("CommercialProperty_Premises_ValuationCode_A", facts) == "Agreed Value"


def test_row_b_valuation_code_falls_through_to_gap_fill_not_deterministic():
    # Non-primary rows (_B, _C, ...) are intentionally intercepted by the
    # "row-variant guard" earlier in _deterministic_map and never reach
    # _ACORD_FIELD_RULES at all - only row A's ValuationCode is ever
    # deterministically resolved (and now correctly translated to "A"/"R").
    # Row B correctly falls to gap-fill instead, which already reads the
    # field's own tooltip convention directly and produces the right code on
    # its own (confirmed live) - this test documents that division of labor
    # so a future change doesn't accidentally assume row B is deterministic.
    # (Returns None here, not the "UNMATCHED" sentinel string - the caller
    # treats both identically as "route to gap-fill", see _is_empty_llm_value.)
    facts = {"valuation_method": "ACV"}
    assert _deterministic_map("CommercialProperty_Premises_ValuationCode_B", facts) is None


# ── Guard 3 extension: tooltip-declared "Enter number:" fields ──────────────

def test_tooltip_declares_number_detection():
    assert _tooltip_declares_number({"tu": "Enter number: The identifying number for the blanket. "})
    assert not _tooltip_declares_number({"tu": "Enter text: The description of property covered. "})
    assert not _tooltip_declares_number({"tu": None})
    assert not _tooltip_declares_number({})


def test_looks_like_declared_number_value():
    for good in ["1", "2", "12345", "B-1", "#2", "  3  ", ""]:
        assert _looks_like_declared_number_value(good), f"should accept {good!r}"
    for bad in ["Location 1", "Location 2", "Building A", "Main Street"]:
        assert not _looks_like_declared_number_value(bad), f"should reject {bad!r}"


def test_guard3_blanks_location_label_in_blanket_number_field():
    schema = {
        "CommercialProperty_Summary_BlanketNumberIdentifier_A": {
            "ft": "/Tx", "tu": "Enter number: The identifying number for the blanket. ",
        },
        "CommercialProperty_Summary_BlanketNumberIdentifier_B": {
            "ft": "/Tx", "tu": "Enter number: The identifying number for the blanket. ",
        },
    }
    mapped = {
        "CommercialProperty_Summary_BlanketNumberIdentifier_A": "Location 1",
        "CommercialProperty_Summary_BlanketNumberIdentifier_B": "Location 2",
    }
    _enforce_post_fill_guards(mapped, schema, facts={})
    assert mapped["CommercialProperty_Summary_BlanketNumberIdentifier_A"] is None
    assert mapped["CommercialProperty_Summary_BlanketNumberIdentifier_B"] is None


def test_guard3_keeps_a_real_number_in_blanket_number_field():
    schema = {
        "CommercialProperty_Summary_BlanketNumberIdentifier_A": {
            "ft": "/Tx", "tu": "Enter number: The identifying number for the blanket. ",
        },
    }
    mapped = {"CommercialProperty_Summary_BlanketNumberIdentifier_A": "1"}
    _enforce_post_fill_guards(mapped, schema, facts={})
    assert mapped["CommercialProperty_Summary_BlanketNumberIdentifier_A"] == "1"


def test_guard3_does_not_touch_alphanumeric_policy_number_style_fields():
    # Regression: a field whose NAME contains "Number" but whose tooltip is
    # NOT the "Enter number:" convention (e.g. a real policy/identifier number
    # that legitimately mixes letters and digits) must be completely
    # unaffected by this new guard.
    schema = {
        "Policy_PolicyNumberIdentifier_A": {
            "ft": "/Tx", "tu": "Enter identifier: The identifier assigned by the insurer to the policy. ",
        },
    }
    mapped = {"Policy_PolicyNumberIdentifier_A": "POL-2026-004471"}
    _enforce_post_fill_guards(mapped, schema, facts={})
    assert mapped["Policy_PolicyNumberIdentifier_A"] == "POL-2026-004471"


# ── normalize_valuation_method: fixes the false value_mismatch introduced ───
# ── by the ValuationCode stamping fix above ─────────────────────────────────

def test_normalize_valuation_method_r_equals_rcv():
    assert normalize_value("valuation_method", "R") == normalize_value("valuation_method", "RCV")


def test_normalize_valuation_method_a_equals_acv():
    assert normalize_value("valuation_method", "A") == normalize_value("valuation_method", "ACV")


def test_normalize_valuation_method_full_phrase_equals_code():
    assert normalize_value("valuation_method", "Replacement Cost") == normalize_value("valuation_method", "R")


def test_normalize_valuation_method_r_and_a_are_distinct():
    assert normalize_value("valuation_method", "R") != normalize_value("valuation_method", "A")


def test_field_qa_no_longer_flags_r_vs_rcv_as_mismatch():
    # End-to-end reproduction of the exact live false positive: the field is
    # correctly stamped "R" (per the schema's own single-letter convention),
    # the underlying fact is still "RCV" (extraction's industry-term form) -
    # field_qa's value-vs-source check must treat these as equal, not flag a
    # fail.
    gen = {
        "ACORD_140": {
            "confidence": {"CommercialProperty_Premises_ValuationCode_A": "filled"},
            "mapped": {"CommercialProperty_Premises_ValuationCode_A": "R"},
            "schema": {},
        }
    }
    r = run_field_qa(gen, merged_facts={"valuation_method": "RCV"})
    mismatch_fields = [item["field"] for item in r["results"] if item["reason_code"] == "value_mismatch"]
    assert "CommercialProperty_Premises_ValuationCode_A" not in mismatch_fields


# ── Guard 2: LimitAmount duplication no longer exempted ─────────────────────

def test_guard2_blanks_duplicate_limit_amount_across_premises_rows():
    schema = {
        "CommercialProperty_Premises_LimitAmount_A": {"ft": "/Tx", "tu": "Enter limit: ..."},
        "CommercialProperty_Premises_LimitAmount_D": {"ft": "/Tx", "tu": "Enter limit: ..."},
    }
    mapped = {
        "CommercialProperty_Premises_LimitAmount_A": "$6,120,000",
        # Row D duplicates row A's exact figure - the live-test bug.
        "CommercialProperty_Premises_LimitAmount_D": "$6,120,000",
    }
    _enforce_post_fill_guards(mapped, schema, facts={})
    assert mapped["CommercialProperty_Premises_LimitAmount_A"] == "$6,120,000"
    assert mapped["CommercialProperty_Premises_LimitAmount_D"] is None


def test_guard2_keeps_distinct_limit_amounts_across_premises_rows():
    schema = {
        "CommercialProperty_Premises_LimitAmount_A": {"ft": "/Tx", "tu": "Enter limit: ..."},
        "CommercialProperty_Premises_LimitAmount_B": {"ft": "/Tx", "tu": "Enter limit: ..."},
    }
    mapped = {
        "CommercialProperty_Premises_LimitAmount_A": "$6,120,000",
        "CommercialProperty_Premises_LimitAmount_B": "$3,845,000",
    }
    _enforce_post_fill_guards(mapped, schema, facts={})
    assert mapped["CommercialProperty_Premises_LimitAmount_A"] == "$6,120,000"
    assert mapped["CommercialProperty_Premises_LimitAmount_B"] == "$3,845,000"


def test_guard2_still_allows_subject_of_insurance_code_to_repeat():
    # SubjectOfInsuranceCode legitimately repeats ("Building" at 2 different
    # locations) - must remain exempted, unlike LimitAmount above.
    schema = {
        "CommercialProperty_Premises_SubjectOfInsuranceCode_A": {"ft": "/Tx", "tu": "Enter code: ..."},
        "CommercialProperty_Premises_SubjectOfInsuranceCode_B": {"ft": "/Tx", "tu": "Enter code: ..."},
    }
    mapped = {
        "CommercialProperty_Premises_SubjectOfInsuranceCode_A": "Building",
        "CommercialProperty_Premises_SubjectOfInsuranceCode_B": "Building",
    }
    _enforce_post_fill_guards(mapped, schema, facts={})
    assert mapped["CommercialProperty_Premises_SubjectOfInsuranceCode_A"] == "Building"
    assert mapped["CommercialProperty_Premises_SubjectOfInsuranceCode_B"] == "Building"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
