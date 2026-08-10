"""Per-line CURRENT policy columns - ACORD 25's certificate rows.

NOT from a client report. Found 2026-08-09 by sweeping every `_ACORD_FIELD_RULES`
entry against every real schema field on all 17 forms, looking for the defect
shape the client DID report on ACORD 125 (one fact feeding several parallel
columns). See fix-form-stamping.md "CROSS-FORM SWEEP".

ACORD 25 is a CERTIFICATE OF LIABILITY INSURANCE - issued to a third party who
relies on it - and one `policy_number` scalar was filling the Automobile
Liability, General Liability AND Workers Compensation rows, with
`effective_date` / `expiration_date` filling three rows each. Telling a
certificate holder that workers comp sits under the auto policy number is a
misstatement to someone acting on the document.

This is the client's own #3 ("Do not present the Auto policy number as though it
governs every selected line") landing where it does the most harm.
"""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                        # noqa: E402

_SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "..", "forms_schemas")

GL = "Policy_GeneralLiability_PolicyNumberIdentifier_A"
AU = "Policy_AutomobileLiability_PolicyNumberIdentifier_A"
EX = "Policy_ExcessLiability_PolicyNumberIdentifier_A"
WC = "Policy_WorkersCompensationAndEmployersLiability_PolicyNumberIdentifier_A"

# The client's real package: two affiliated carriers, different policy numbers.
MULTI = {
    "policy_number": "6E7-40-02---26",
    "effective_date": "07/15/2025",
    "expiration_date": "07/15/2026",
    "coverage_lines": [
        {"line": "Commercial General Liability", "policy_number": "BBC7263-26",
         "carrier": "EMC Property & Casualty Company",
         "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
        {"line": "Commercial Auto", "policy_number": "6E7-40-02---26",
         "carrier": "Employers Mutual Casualty Company"},
        {"line": "Commercial Umbrella", "policy_number": "UMB-555"},
    ],
}


def test_each_line_shows_its_own_policy_number():
    m = ps._deterministic_map
    assert m(GL, MULTI) == "BBC7263-26"
    assert m(AU, MULTI) == "6E7-40-02---26"


def test_umbrella_reaches_the_excess_liability_row():
    """ACORD 25's column is "ExcessLiability"; the document says "Umbrella".
    ACORD's own ExcessUmbrella_* tooltips call it "excess or umbrella liability
    policy"."""
    assert ps._deterministic_map(EX, MULTI) == "UMB-555"


def test_a_coverage_the_package_does_not_have_stays_blank():
    """There is no workers comp on this package. The old mapping put the AUTO
    policy number in the WC row of a certificate."""
    assert ps._deterministic_map(WC, MULTI) is None


def test_dates_are_not_sprayed_across_coverage_rows():
    m = ps._deterministic_map
    assert m("Policy_GeneralLiability_EffectiveDate_A", MULTI) == "07/15/2025"
    # Auto's entry states no dates, and a package-level date cannot be assumed
    # to be this line's date when several lines exist.
    assert m("Policy_AutomobileLiability_EffectiveDate_A", MULTI) is None
    assert m("Policy_WorkersCompensationAndEmployersLiability_EffectiveDate_A", MULTI) is None


def test_single_line_package_uses_the_package_scalar():
    """With exactly one coverage line, the package policy number unambiguously
    belongs to it - so this must NOT cost a fill."""
    one = {"policy_number": "GL-ONLY-1",
           "coverage_lines": [{"line": "Commercial General Liability"}]}
    assert ps._deterministic_map(GL, one) == "GL-ONLY-1"
    assert ps._deterministic_map(AU, one) is None


def test_no_coverage_lines_preserves_the_legacy_scalar_path():
    """Sessions extracted before RULE 16 have no per-line data. Blanking them
    would be a pure regression with no correctness gain, so the existing scalar
    rule is left alone. This change may only remove borrowing, never fill."""
    legacy = {"policy_number": "LEGACY-9"}
    assert ps._deterministic_map(GL, legacy) == "LEGACY-9"
    assert ps._deterministic_map(AU, legacy) == "LEGACY-9"


def test_conflicting_values_for_one_line_leave_it_blank():
    facts = {"coverage_lines": [
        {"line": "General Liability", "policy_number": "GL-1"},
        {"line": "Commercial General Liability", "policy_number": "GL-2"},
    ]}
    assert ps._deterministic_map(GL, facts) is None


def test_malformed_facts_are_survivable():
    for facts in ({"coverage_lines": "nope"}, {"coverage_lines": [None]},
                  {"coverage_lines": [{}]}, {"coverage_lines": [{"line": ""}]}):
        assert ps._deterministic_map(GL, facts) in (None, "UNMATCHED")


# ── The synonym set must stay honest ─────────────────────────────────────────

def test_line_synonyms_are_corroborated_by_acord_tooltips():
    """STANDING GUARD. Every synonym pair must be supported by a real tooltip in
    a shipped schema that uses BOTH words for one coverage - so nobody can add an
    invented equivalence. Same discipline as
    test_every_symbol_description_matches_acord_tooltip in the auto-symbol work.
    """
    tooltips = []
    for name in os.listdir(_SCHEMA_DIR):
        if not name.endswith("_schema.json"):
            continue
        with open(os.path.join(_SCHEMA_DIR, name), encoding="utf-8") as fh:
            for meta in json.load(fh).values():
                tu = (meta or {}).get("tu")
                if tu:
                    tooltips.append(tu.lower())
    assert tooltips, "no tooltips loaded - the schema format changed"

    for group in ps._LINE_SYNONYMS:
        words = sorted(group)
        assert any(all(w in tu for w in words) for tu in tooltips), (
            f"synonym group {words} is not corroborated by any ACORD tooltip - "
            "do not encode an equivalence ACORD's own text does not state"
        )


def test_synonyms_do_not_merge_genuinely_different_coverages():
    """A synonym group must never let one coverage answer for another."""
    assert ps._line_words_match("excess", "umbrella") is True
    assert ps._line_words_match("general", "liquor") is False
    assert ps._line_words_match("automobile", "general") is False
    assert ps._line_words_match("property", "liability") is False


def test_liquor_liability_does_not_reach_the_general_liability_row():
    """Shares "liability" with the GL column; every token must match, not one."""
    facts = {"coverage_lines": [
        {"line": "Commercial General Liability", "policy_number": "GL-1"},
        {"line": "Liquor Liability", "policy_number": "LQ-9"},
    ]}
    assert ps._deterministic_map(GL, facts) == "GL-1"


# ── Scope ────────────────────────────────────────────────────────────────────

def test_only_real_acord_25_columns_are_claimed():
    """The resolver must own exactly the per-line certificate cells and nothing
    else that happens to start with Policy_."""
    with open(os.path.join(_SCHEMA_DIR, "ACORD_25_schema.json"), encoding="utf-8") as fh:
        schema = json.load(fh)
    owned = [f for f in schema
             if ps._resolve_current_policy_line_cell(f, MULTI) is not ps._SCHED_SKIP]
    assert len(owned) == 12, f"expected 4 lines x 3 attributes, got {sorted(owned)}"
    # Plain policy fields keep their ordinary scalar rule.
    assert ps._resolve_current_policy_line_cell(
        "Policy_EffectiveDate_A", MULTI) is ps._SCHED_SKIP


def test_other_forms_plain_policy_fields_are_untouched():
    assert ps._deterministic_map(
        "Policy_EffectiveDate_A", {"effective_date": "01/01/2026"}) == "01/01/2026"
    assert ps._deterministic_map(
        "Policy_PolicyNumberIdentifier_A", {"policy_number": "P-1"}) == "P-1"


def test_the_scalar_rules_still_exist_because_the_fallback_needs_them():
    """The per-line scalar rows in `_ACORD_FIELD_RULES` are deliberately KEPT.

    An earlier version of this test banned them - and it was wrong. Rule 4 of
    `_resolve_current_policy_line_cell` returns _SCHED_SKIP when `coverage_lines`
    is absent precisely so those rules still answer for sessions extracted before
    RULE 16 existed. Deleting them would blank certificate policy numbers on
    every such session: a pure regression.

    The resolver runs FIRST in `_deterministic_map`, so whenever per-line data
    exists the scalar never gets a say. That ordering is the real invariant, and
    the test below is what actually guards it.
    """
    patterns = {
        pat for pat, fk in ps._ACORD_FIELD_RULES
        if fk and re.match(r"^Policy_(GeneralLiability|AutomobileLiability|"
                           r"ExcessLiability|WorkersCompensationAnd"
                           r"EmployersLiability)_", pat)
    }
    assert patterns, "the legacy fallback rules were removed - rule 4 is now dead"


def test_no_value_appears_in_a_column_the_document_did_not_put_it_in():
    """STANDING GUARD - the actual anti-spray invariant.

    With per-line data present, a package-level scalar must never surface in a
    coverage row that the document did not attribute it to. This is what the
    client reported and what must never come back, however the rules are later
    rearranged.
    """
    package_scalar = MULTI["policy_number"]
    for field, expected_owner in ((GL, "BBC7263-26"), (WC, None)):
        got = ps._deterministic_map(field, MULTI)
        assert got == expected_owner, f"{field} -> {got!r}"
    # The scalar may appear ONLY on the Auto row, which is the line the document
    # actually attributes it to.
    showing = [
        f for f in (GL, AU, EX, WC)
        if ps._deterministic_map(f, MULTI) == package_scalar
    ]
    assert showing == [AU], (
        f"the package policy number leaked into {showing}"
    )
