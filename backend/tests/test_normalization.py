"""
Regression tests for the Value Normalization Layer (Beta Report §5 / Workstream 2).

Covers every §5.2 acceptance criterion: equivalent values (formatting/terminology
differences) must NOT produce a conflict, while values that materially differ
after normalization still must. Also verifies the two doc-level conflict
detectors (check_doc_consistency, detect_source_conflicts) consume the layer.

Run from backend/:
    python tests/test_normalization.py
or:
    python -m pytest tests/test_normalization.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.normalization import (  # noqa: E402
    normalize_name, normalize_date, normalize_entity_type, normalize_address,
    normalize_carrier, normalize_general, normalize_value,
    distinct_normalized, values_conflict,
)
from services.sqs_service import check_doc_consistency  # noqa: E402
from services.extraction_service import detect_source_conflicts  # noqa: E402


# ── §5.2 Applicant Name Normalization ─────────────────────────────────────────

def test_applicant_name_variants_equivalent():
    names = ["ORBIN CONTRACTING LLC", "Orbin Contracting LLC", "Orbin Contracting, LLC"]
    norms = {normalize_name(n) for n in names}
    assert norms == {"orbin contracting"}, norms
    assert not values_conflict("applicant_name", names)


def test_genuinely_different_names_conflict():
    names = ["Orbin Contracting LLC", "Wake County Government"]
    assert values_conflict("applicant_name", names)


# ── §5.2 Date Normalization ───────────────────────────────────────────────────

def test_date_variants_equivalent():
    dates = ["07/15/25", "7/15/2025", "07/15/2025", "2025-07-15"]
    norms = {normalize_date(d) for d in dates}
    assert norms == {"2025-07-15"}, norms
    assert not values_conflict("effective_date", dates)


def test_written_date_equivalent():
    assert normalize_date("July 15, 2025") == "2025-07-15"
    assert normalize_date("Jul 15 2025") == "2025-07-15"
    assert normalize_date("15 July 2025") == "2025-07-15"


def test_different_dates_conflict():
    assert values_conflict("expiration_date", ["07/15/2025", "08/01/2025"])


def test_unparseable_date_falls_back_to_text():
    # Two genuinely different non-date strings should still differ.
    assert values_conflict("effective_date", ["see schedule A", "see schedule B"])
    # ...but identical garbage should not.
    assert not values_conflict("effective_date", ["pending", "Pending"])


# ── §5.2 Entity Type Normalization ────────────────────────────────────────────

def test_entity_type_synonyms_equivalent():
    assert normalize_entity_type("LLC") == normalize_entity_type("Limited Liability Company")
    assert normalize_entity_type("Inc.") == normalize_entity_type("Incorporated")
    assert normalize_entity_type("Corp.") == normalize_entity_type("Corporation")
    assert normalize_entity_type("Co.") == normalize_entity_type("Company")
    assert normalize_entity_type("Ltd.") == normalize_entity_type("Limited")
    assert normalize_entity_type("LLP") == normalize_entity_type("Limited Liability Partnership")
    assert normalize_entity_type("LP") == normalize_entity_type("Limited Partnership")
    assert not values_conflict("entity_type", ["LLC", "Limited Liability Company"])


def test_entity_type_genuinely_different_conflict():
    assert values_conflict("entity_type", ["LLC", "Corporation"])


# ── §5.2 Address Normalization ────────────────────────────────────────────────

def test_address_variants_equivalent():
    a = "4800 DAHLIA ST #D13"
    b = "4800 Dahlia Street D13"
    assert normalize_address(a) == normalize_address(b) == "4800 dahlia st d13"
    assert not values_conflict("mailing_address", [a, b])


def test_address_suffix_and_unit_synonyms():
    assert normalize_address("100 Main Avenue Suite 5") == normalize_address("100 Main Ave Ste 5")
    assert normalize_address("100 Main Ave Ste 5") == normalize_address("100 Main Ave #5")
    assert normalize_address("12 Oak Road") == normalize_address("12 Oak Rd")
    assert normalize_address("12 Oak Boulevard") == normalize_address("12 Oak Blvd")


def test_address_genuinely_different_conflict():
    assert values_conflict("physical_address", ["4800 Dahlia St", "900 Elm St"])


def test_address_directionals_equivalent():
    # North/N, Southwest/SW, etc. standardize so "North Main" == "N Main".
    assert normalize_address("100 North Main St") == normalize_address("100 N Main St")
    assert normalize_address("250 Southwest 5th Ave") == normalize_address("250 SW 5th Ave")
    assert not values_conflict("mailing_address", ["100 North Main St", "100 N Main St"])
    # Distinct directions MUST stay distinct - never merge two different addresses.
    assert normalize_address("100 N Main St") != normalize_address("100 S Main St")
    assert values_conflict("physical_address", ["100 N Main St", "100 S Main St"])


def test_fein_requires_exactly_nine_digits():
    from services.normalization import normalize_fein
    # Clean 9-digit FEIN (with or without hyphen) is preserved.
    assert normalize_fein("12-3456789") == "123456789"
    assert normalize_fein("123456789") == "123456789"
    # Over-long OCR/extraction artifact -> '' (no signal) so it cannot manufacture
    # a false cross-document FEIN conflict; matches submission_integrity's rule.
    assert normalize_fein("1234567890") == ""
    assert normalize_fein("12-345678") == ""   # too short
    assert not values_conflict("fein", ["12-3456789", "1234567890"])


# ── §5.2 Insurance Terminology Normalization ──────────────────────────────────

def test_insurance_terms_equivalent():
    pairs = [
        ("CSL", "Combined Single Limit"),
        ("CGL", "Commercial General Liability"),
        ("GL", "General Liability"),
        ("WC", "Workers Compensation"),
        ("BPP", "Business Personal Property"),
        ("TIV", "Total Insured Value"),
        ("EPLI", "Employment Practices Liability Insurance"),
        ("HNOA", "Hired and Non-Owned Auto"),
        ("COPE", "Construction, Occupancy, Protection, Exposure"),
        # ("BI", "Building") was DELETED 2026-08-24 (v1-20AUG.md C1-R). In
        # commercial lines "BI" is Bodily Injury or Business Interruption;
        # folding it into Building is the over-mapping client 1.7 forbids and
        # D9 requires product approval for. The code was right; the pair was
        # wrong. Do not restore it and do not "fix" normalize_general for it.
    ]
    for abbrev, expanded in pairs:
        assert normalize_general(abbrev) == normalize_general(expanded), (abbrev, expanded)


def test_cgl_distinct_from_gl():
    # CGL (Commercial General Liability) is NOT the same token as GL.
    assert normalize_general("CGL") != normalize_general("GL")
    assert normalize_general("Commercial General Liability") == normalize_general("CGL")


def test_currency_formatting_equivalent_in_general():
    assert normalize_general("$1,000,000") == normalize_general("1000000")
    assert normalize_general("1,000,000.00") == normalize_general("1000000")
    assert normalize_general("$1,000,000 CSL") == normalize_general("1000000 Combined Single Limit")


# ── §5.2 Carrier Alias Handling ───────────────────────────────────────────────

def test_carrier_seed_alias_collapses():
    assert normalize_carrier("Employers Mutual Casualty Company") == "emc"
    assert normalize_carrier("EMC Property & Casualty Company") == "emc"
    assert normalize_carrier("EMC Insurance") == "emc"
    assert not values_conflict(
        "carrier_name",
        ["Employers Mutual Casualty Company", "EMC Property & Casualty Company"],
    )


def test_carrier_different_carriers_conflict():
    assert values_conflict("carrier_name", ["Travelers", "The Hartford"])


# ── Detector integration ──────────────────────────────────────────────────────

def _doc(facts, doc_type="dec_page"):
    return {"facts": facts, "doc_type": doc_type, "filename": f"{doc_type}.pdf"}


def test_check_doc_consistency_no_false_name_hard_stop():
    docs = [
        _doc({"applicant_name": "ORBIN CONTRACTING LLC", "effective_date": "07/15/25"}),
        _doc({"applicant_name": "Orbin Contracting, LLC", "effective_date": "7/15/2025"},
             doc_type="certificate"),
    ]
    issues = check_doc_consistency(docs)
    # No hard stops or warnings — formatting differences should produce [info] notices only
    assert not any("[hard_stop]" in i or "[warning]" in i for i in issues), issues
    # [info] notices should be emitted for name and date formatting differences
    info = [i for i in issues if i.startswith("[info]")]
    assert len(info) >= 2, f"Expected [info] notices for name + date, got: {issues}"


def test_check_doc_consistency_real_conflict_still_hard_stops():
    docs = [
        _doc({"applicant_name": "Orbin Contracting LLC"}),
        _doc({"applicant_name": "Wake County Government"}, doc_type="narrative"),
    ]
    issues = check_doc_consistency(docs)
    assert any("name_conflict" in i and "hard_stop" in i for i in issues), issues


def test_check_doc_consistency_entity_type_synonym_no_warning():
    docs = [
        _doc({"entity_type": "LLC"}),
        _doc({"entity_type": "Limited Liability Company"}, doc_type="application"),
    ]
    issues = check_doc_consistency(docs)
    # [info] notices are allowed — only hard stops and warnings must be absent
    blocking = [i for i in issues if i.startswith("[hard_stop]") or i.startswith("[warning]")]
    info_only = [i for i in issues if i.startswith("[info]") and "entity_type" in i]
    assert not blocking, blocking
    # An [info] notice is expected: the values differed in format but were normalized
    assert len(info_only) == 1, f"Expected exactly 1 [info] notice, got: {issues}"


def test_detect_source_conflicts_suppresses_formatting():
    docs = [
        _doc({"some_limit": "$1,000,000", "coverage": "CSL"}),
        _doc({"some_limit": "1000000", "coverage": "Combined Single Limit"},
             doc_type="certificate"),
    ]
    conflicts = detect_source_conflicts(docs)
    assert conflicts == [], conflicts


def test_detect_source_conflicts_carrier_flagged_for_review():
    docs = [
        _doc({"carrier_name": "Travelers Indemnity"}),
        _doc({"carrier_name": "The Hartford"}, doc_type="certificate"),
    ]
    conflicts = detect_source_conflicts(docs)
    assert len(conflicts) == 1
    assert "review" in conflicts[0].lower(), conflicts


def test_detect_source_conflicts_carrier_alias_no_conflict():
    docs = [
        _doc({"carrier_name": "Employers Mutual Casualty Company"}),
        _doc({"carrier_name": "EMC Property & Casualty Company"}, doc_type="certificate"),
    ]
    assert detect_source_conflicts(docs) == []


def test_normalize_value_empty_signals_ignored():
    # Empty / null-ish values normalize to '' and never manufacture a conflict.
    assert distinct_normalized("applicant_name", [None, "", "  "]) == set()
    assert not values_conflict("applicant_name", ["Orbin Contracting LLC", None])


# ── Validator integration (the "effective_date format unrecognized" bug) ──────

def test_effective_date_window_accepts_two_digit_year():
    """07/15/25 (two-digit year from dec page) must NOT produce a warning."""
    from services.sqs_service import validate_effective_date_window
    # 07/15/25 is in the past but within 2 years — result should be None (no issue)
    # or at most the "2 years past" warning, never "format unrecognized".
    result = validate_effective_date_window({"effective_date": "07/15/25"})
    assert result is None or "unrecognized" not in (result[1] if result else ""), result


def test_validate_date_format_accepts_all_common_formats():
    from utils.validators import validate_date_format
    for date_str in ["07/15/2025", "7/15/2025", "07/15/25", "2025-07-15", "2025/07/15",
                     "July 15, 2025", "Jul 15 2025"]:
        ok, msg = validate_date_format(date_str, "Test date")
        assert ok, f"Rejected valid date {date_str!r}: {msg}"


# ── Cross-form validator uses normalize_address for location reconciliation ────

def test_cross_form_location_normalizer_uses_shared_layer():
    """Street/Avenue/suffix differences must not cause false location mismatches."""
    from services.normalization import normalize_address
    a = normalize_address("4800 DAHLIA STREET")
    b = normalize_address("4800 Dahlia St")
    assert a == b, f"{a!r} != {b!r}"

    c = normalize_address("100 Main Avenue Suite 5")
    d = normalize_address("100 Main Ave Ste 5")
    assert c == d, f"{c!r} != {d!r}"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
