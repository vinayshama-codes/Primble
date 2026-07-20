"""
Regression tests for the download-completeness gate (Figure 35 client feedback:
"This should be a hard stop... If a draft is allowed, watermark or label it
clearly as incomplete").

Covers three layers:
  * placeholder_detector.is_placeholder_value - catches leaked instruction text
    ("1st distinct value") and template placeholders without false-positiving on
    real insurance data.
  * pdf_service.apply_acord140_missing_field_highlights - the ACORD 140 COPE
    completeness gate (building value, construction type, year built, roof,
    protection class), scoped to ONLY that form and ONLY "started" rows.
  * field_qa.check_hard_block - the fresh, independent gate a download route
    calls; must return placeholder + missing_required_gate fails and NOTHING
    else (ordinary missing_required / low_confidence stay non-blocking).

Run from backend/:
    python tests/test_download_gate.py
or:
    python -m pytest tests/test_download_gate.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.placeholder_detector import is_placeholder_value  # noqa: E402
from services.pdf_service import (  # noqa: E402
    apply_acord140_missing_field_highlights, _is_empty_llm_value, apply_draft_watermark,
)
from services.field_qa import run_field_qa, check_hard_block, _HARD_BLOCK_REASON_CODES  # noqa: E402


# ── pdf_service._is_empty_llm_value: fill-time prevention layer ─────────────

def test_is_empty_llm_value_catches_placeholder_echo():
    assert _is_empty_llm_value("1st distinct value") is True
    assert _is_empty_llm_value("2nd distinct value") is True


def test_is_empty_llm_value_still_catches_ordinary_sentinels():
    assert _is_empty_llm_value("N/A") is True
    assert _is_empty_llm_value(None) is True
    assert _is_empty_llm_value("") is True


def test_is_empty_llm_value_real_value_passes_through():
    assert _is_empty_llm_value("Orbin Contracting LLC") is False
    assert _is_empty_llm_value("$2,000,000") is False


# ── placeholder_detector ─────────────────────────────────────────────────────

def test_ordinal_digit_distinct_value_flagged():
    is_ph, reason = is_placeholder_value("1st distinct value")
    assert is_ph and reason == "ordinal_distinct_value"


def test_ordinal_word_distinct_value_flagged():
    is_ph, _ = is_placeholder_value("Second distinct value")
    assert is_ph


def test_distinct_value_fragment_flagged():
    is_ph, reason = is_placeholder_value("up to 3 distinct values found")
    assert is_ph and reason == "distinct_value_fragment"


def test_instruction_leak_flagged():
    is_ph, reason = is_placeholder_value("null if fewer distinct values exist")
    assert is_ph


def test_template_bracket_flagged():
    assert is_placeholder_value("<insert building value>")[0]
    assert is_placeholder_value("[TBD]")[0]


def test_filler_word_flagged():
    assert is_placeholder_value("Lorem Ipsum")[0]
    assert is_placeholder_value("placeholder")[0]


def test_real_values_not_flagged():
    for v in ["Orbin Contracting LLC", "$2,000,000", "07/15/2025", "Frame",
              "1995", "4800 Dahlia St #D13", "Sample Logistics LLC", "A", "12"]:
        is_ph, reason = is_placeholder_value(v)
        assert not is_ph, f"false positive on real value: {v!r} (reason={reason})"


def test_none_and_blank_not_flagged():
    assert is_placeholder_value(None) == (False, None)
    assert is_placeholder_value("") == (False, None)
    assert is_placeholder_value("   ") == (False, None)


# ── apply_acord140_missing_field_highlights ─────────────────────────────────

def test_acord140_untouched_row_not_flagged():
    # A premises row that was never started (no SubjectOfInsuranceCode, no
    # LimitAmount) must never be treated as a gap - matches the 125/126
    # "started row" convention exactly.
    field_state = {}
    confidence = {}
    out = apply_acord140_missing_field_highlights("ACORD_140", {}, field_state, confidence)
    assert out == {}


def test_acord140_started_row_missing_amount_flagged():
    field_state = {
        "CommercialProperty_Premises_SubjectOfInsuranceCode_A": "Building",
        # LimitAmount_A deliberately absent - this is the exact client screenshot bug
    }
    # In the real pipeline, map_facts_to_form's generic confidence pass (which runs
    # BEFORE this function) has already populated an entry for every schema field -
    # seeded here so the "is this field even part of this rendered schema" guard
    # (mirroring apply_acord125/126's own convention) behaves as it does in
    # production instead of skipping an unseeded field.
    confidence = {"CommercialProperty_Premises_LimitAmount_A": "low_confidence"}
    out = apply_acord140_missing_field_highlights("ACORD_140", {}, field_state, confidence)
    assert out.get("CommercialProperty_Premises_LimitAmount_A") == "missing_required_gate"


def test_acord140_started_row_with_amount_not_flagged():
    field_state = {
        "CommercialProperty_Premises_SubjectOfInsuranceCode_A": "Building",
        "CommercialProperty_Premises_LimitAmount_A": "$2,000,000",
    }
    confidence = {"CommercialProperty_Premises_LimitAmount_A": "low_confidence"}
    out = apply_acord140_missing_field_highlights("ACORD_140", {}, field_state, confidence)
    assert out.get("CommercialProperty_Premises_LimitAmount_A") != "missing_required_gate"


def test_acord140_building_characteristics_required_once_row_started():
    field_state = {
        "CommercialProperty_Premises_LimitAmount_A": "$2,000,000",
        "Construction_ConstructionCode_A": "Frame",
        # BuiltYear_A, RoofMaterialCode_A, ProtectionClassCode_A left blank
    }
    confidence = {
        "CommercialStructure_BuiltYear_A": "low_confidence",
        "Construction_RoofMaterialCode_A": "low_confidence",
        "BuildingFireProtection_ProtectionClassCode_A": "low_confidence",
    }
    out = apply_acord140_missing_field_highlights("ACORD_140", {}, field_state, confidence)
    assert out.get("CommercialStructure_BuiltYear_A") == "missing_required_gate"
    assert out.get("Construction_RoofMaterialCode_A") == "missing_required_gate"
    assert out.get("BuildingFireProtection_ProtectionClassCode_A") == "missing_required_gate"


def test_acord140_building_b_independent_of_building_a():
    # Building B's own row never started - it must not inherit A's requirement.
    field_state = {
        "CommercialProperty_Premises_LimitAmount_A": "$2,000,000",
        "Construction_ConstructionCode_A": "Frame",
        "CommercialStructure_BuiltYear_A": "1995",
        "Construction_RoofMaterialCode_A": "Composition",
        "BuildingFireProtection_ProtectionClassCode_A": "4",
    }
    confidence = {"CommercialStructure_BuiltYear_B": "low_confidence"}
    out = apply_acord140_missing_field_highlights("ACORD_140", {}, field_state, confidence)
    assert "CommercialStructure_BuiltYear_B" not in out or out["CommercialStructure_BuiltYear_B"] != "missing_required_gate"


def test_acord140_building_b_required_via_property_locations_even_when_premises_row_b_never_started():
    """Confirmed live bug (2026-07-17): a 2nd location's dollar amount can land
    in ANY premises row (B, C, G, ...) depending on gap-fill, NOT necessarily
    row B - so gating building B's COPE requirement on "did premises row B
    start" alone silently missed the gap whenever the amount landed elsewhere.
    property_locations having a 2nd real entry must trigger building B's COPE
    requirement on its own, independent of which premises row got the dollar
    amount."""
    field_state = {
        "CommercialProperty_Premises_LimitAmount_A": "$2,000,000",
        "Construction_ConstructionCode_A": "Frame",
        "CommercialStructure_BuiltYear_A": "1995",
        "Construction_RoofMaterialCode_A": "Composition",
        "BuildingFireProtection_ProtectionClassCode_A": "4",
        # Location 2's amount landed in row C, NOT row B - premises row B
        # itself never started.
        "CommercialProperty_Premises_SubjectOfInsuranceCode_C": "Building",
        "CommercialProperty_Premises_LimitAmount_C": "$1,500,000",
    }
    confidence = {
        "CommercialStructure_BuiltYear_B": "low_confidence",
        "Construction_RoofMaterialCode_B": "low_confidence",
        "BuildingFireProtection_ProtectionClassCode_B": "low_confidence",
    }
    facts = {"property_locations": [{"address": "1 A St"}, {"address": "2 B St"}]}
    out = apply_acord140_missing_field_highlights("ACORD_140", facts, field_state, confidence)
    assert out.get("CommercialStructure_BuiltYear_B") == "missing_required_gate"
    assert out.get("Construction_RoofMaterialCode_B") == "missing_required_gate"
    assert out.get("BuildingFireProtection_ProtectionClassCode_B") == "missing_required_gate"


def test_acord140_building_b_not_required_when_only_one_location_exists():
    # No 2nd location in facts AND premises row B never started - building B
    # genuinely doesn't exist, must not be flagged.
    field_state = {
        "CommercialProperty_Premises_LimitAmount_A": "$2,000,000",
    }
    confidence = {"CommercialStructure_BuiltYear_B": "low_confidence"}
    facts = {"property_locations": [{"address": "1 A St"}]}
    out = apply_acord140_missing_field_highlights("ACORD_140", facts, field_state, confidence)
    assert out.get("CommercialStructure_BuiltYear_B") != "missing_required_gate"


def test_acord140_other_forms_untouched():
    field_state = {"CommercialProperty_Premises_SubjectOfInsuranceCode_A": "Building"}
    confidence = {}
    out = apply_acord140_missing_field_highlights("ACORD_125", {}, field_state, confidence)
    assert out == {}


# ── field_qa placeholder + hard-block reason codes ──────────────────────────

def _form(confidence, mapped):
    return {"ACORD_140": {"confidence": confidence, "mapped": mapped, "schema": {}}}


def test_field_qa_flags_placeholder_value_as_fail():
    gen = _form(
        {"CommercialProperty_Premises_LimitAmount_A": "filled"},
        {"CommercialProperty_Premises_LimitAmount_A": "1st distinct value"},
    )
    r = run_field_qa(gen, merged_facts={})
    codes = [item["reason_code"] for item in r["results"]]
    assert "placeholder_value" in codes
    assert r["fail_count"] >= 1


def test_field_qa_missing_required_gate_is_fail_and_hard_block():
    gen = _form({"CommercialProperty_Premises_LimitAmount_A": "missing_required_gate"}, {})
    r = run_field_qa(gen, merged_facts={})
    item = next(i for i in r["results"] if i["field"] == "CommercialProperty_Premises_LimitAmount_A")
    assert item["verdict"] == "fail"
    assert item["reason_code"] == "missing_required_gate"
    assert item["reason_code"] in _HARD_BLOCK_REASON_CODES


def test_field_qa_plain_missing_required_not_hard_block():
    # Pre-existing behavior (ACORD 125/126) must be completely unaffected: a
    # plain "missing_required" fail is NOT in the hard-block set.
    gen = _form({"NamedInsured_FullName_A": "missing_required"}, {})
    r = run_field_qa(gen, merged_facts={})
    item = next(i for i in r["results"] if i["field"] == "NamedInsured_FullName_A")
    assert item["reason_code"] == "missing_required"
    assert item["reason_code"] not in _HARD_BLOCK_REASON_CODES


# ── check_hard_block: the actual download-gate data source ─────────────────

def test_check_hard_block_empty_when_nothing_wrong():
    gen = _form({"NamedInsured_FullName_A": "filled"}, {"NamedInsured_FullName_A": "Orbin Contracting LLC"})
    assert check_hard_block(gen) == []


def test_check_hard_block_returns_placeholder_and_gate_fails_only():
    gen = {
        "ACORD_140": {
            "confidence": {
                "CommercialProperty_Premises_LimitAmount_A": "missing_required_gate",
                "NamedInsured_FullName_A": "missing_required",   # plain - must NOT be returned
                "GeneralLiability_Hazard_ClassCode_A": "low_confidence",  # advisory - must NOT be returned
            },
            "mapped": {
                "CommercialProperty_Premises_SubjectOfInsuranceCode_A": "1st distinct value",
                "GeneralLiability_Hazard_ClassCode_A": "some ai guess",
            },
            "schema": {},
        }
    }
    blocking = check_hard_block(gen)
    codes = {b["reason_code"] for b in blocking}
    assert codes <= _HARD_BLOCK_REASON_CODES
    assert "placeholder_value" in codes
    assert "missing_required_gate" in codes
    fields = {b["field"] for b in blocking}
    assert "NamedInsured_FullName_A" not in fields
    assert "CommercialProperty_Premises_SubjectOfInsuranceCode_A" in fields  # the placeholder itself


def test_check_hard_block_respects_form_ids_filter():
    gen = {
        "ACORD_140": {"confidence": {"X_A": "missing_required_gate"}, "mapped": {}, "schema": {}},
        "ACORD_125": {"confidence": {"Y_A": "missing_required_gate"}, "mapped": {}, "schema": {}},
    }
    blocking = check_hard_block(gen, form_ids=["ACORD_140"])
    assert all(b["form_id"] == "ACORD_140" for b in blocking)


# ── apply_draft_watermark ────────────────────────────────────────────────────

def test_apply_draft_watermark_stamps_every_page():
    import glob
    import pikepdf

    tmpl = glob.glob(os.path.join(os.path.dirname(__file__), "..", "templates", "ACORD_140.pdf"))[0]
    with open(tmpl, "rb") as f:
        original = f.read()
    watermarked = apply_draft_watermark(original)
    assert watermarked != b""
    pdf = pikepdf.open(__import__("io").BytesIO(watermarked))
    stamped_pages = 0
    for page in pdf.pages:
        resources = page.get("/Resources")
        fonts = resources.get("/Font") if resources else None
        if fonts and "/PrimbleDraftWM" in fonts:
            stamped_pages += 1
    assert stamped_pages == len(pdf.pages)


def test_apply_draft_watermark_never_raises_on_garbage_input():
    # Defensive: malformed bytes must fall back to returning the input unchanged,
    # never raise - a watermark failure must never break a download outright.
    garbage = b"not a real pdf"
    out = apply_draft_watermark(garbage)
    assert out == garbage


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
