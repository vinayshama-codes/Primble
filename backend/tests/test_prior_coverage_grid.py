"""The prior-coverage grid: a 2-D grid (line x term), not four copies of one policy.

Client report (ACORD 125, Orbin Contracting) #17:
  "The form places the same current policy numbers into multiple unrelated
   columns: BBC7263 under GL, Property and Other; 6E74002 under Auto, GL,
   Property and Other. Carrier names and premiums are missing. The same
   2025-2026 dates used as the proposed/current term are also presented as prior
   coverage. ... Do not put GL or Auto numbers in the Property column."

Two defects in one section:
  * FOUR scalars (prior_policy_number / prior_carrier / prior_effective_date /
    prior_expiration_date) were mapped onto SIXTEEN boxes, so one value filled
    every column. A scalar cannot say WHICH line a policy covered.
  * The carrier and premium columns had no fact behind them at all, so they were
    always blank - which is why the client saw them missing.

`prior_coverage_by_line` had the right shape all along and never stamped, because
4 of its 5 `_SCHEDULE_REGISTRY` bindings name fields that exist on no form.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                        # noqa: E402


# The client's literal values - the CURRENT policy, which is all their dec page had.
CURRENT_ONLY = {
    "prior_policy_number":   "BBC7263",
    "prior_carrier":         "Employers Mutual Casualty Company",
    "prior_effective_date":  "07/15/2025",
    "prior_expiration_date": "07/15/2026",
}

REAL_HISTORY = {
    "prior_coverage_by_line": [
        {"line": "General Liability", "carrier": "Acme Mutual", "policy_no": "GL-111",
         "effective": "01/01/2024", "expiration": "01/01/2025", "premium": "$4,000"},
        {"line": "Commercial Auto", "carrier": "Beta Casualty", "policy_no": "AU-222",
         "effective": "01/01/2024", "expiration": "01/01/2025", "premium": "$2,500"},
        {"line": "General Liability", "carrier": "Acme Mutual", "policy_no": "GL-000",
         "effective": "01/01/2023", "expiration": "01/01/2024", "premium": "$3,800"},
        {"line": "Commercial Umbrella", "carrier": "Gamma Excess", "policy_no": "UM-333",
         "effective": "01/01/2024", "expiration": "01/01/2025", "premium": "$1,200"},
    ]
}

_COLUMNS = ("GeneralLiability", "Automobile", "Property", "OtherLine")


@pytest.mark.parametrize("column", _COLUMNS)
def test_current_policy_never_appears_as_prior_coverage(column):
    """THE CLIENT'S CASE. A dec page describes the CURRENT policy; presenting it
    as coverage history is a factual misstatement on a signed application."""
    for attr in ("PolicyNumberIdentifier", "InsurerFullName",
                 "EffectiveDate", "ExpirationDate"):
        field = f"PriorCoverage_{column}_{attr}_A"
        assert ps._deterministic_map(field, CURRENT_ONLY) is None, (
            f"{field} was filled from a current-policy scalar"
        )


def test_no_scalar_can_reach_the_grid_even_with_every_prior_fact_set():
    """Belt and braces: the resolver owns these cells and returns None when
    empty, so nothing falls through to _ACORD_FIELD_RULES."""
    facts = dict(CURRENT_ONLY, prior_carrier_naic="26247")
    filled = [
        f for f in (
            f"PriorCoverage_{c}_{a}_{r}"
            for c in _COLUMNS
            for a in ("PolicyNumberIdentifier", "InsurerFullName",
                      "TotalPremiumAmount", "EffectiveDate", "ExpirationDate")
            for r in "ABC"
        )
        if ps._deterministic_map(f, facts) is not None
    ]
    assert not filled, f"scalars still reaching the grid: {filled}"


def test_real_history_places_each_policy_in_its_own_column():
    m = ps._deterministic_map
    assert m("PriorCoverage_GeneralLiability_PolicyNumberIdentifier_A", REAL_HISTORY) == "GL-111"
    assert m("PriorCoverage_Automobile_PolicyNumberIdentifier_A", REAL_HISTORY) == "AU-222"
    # Umbrella is not one of ACORD's three named columns - it belongs in Other.
    assert m("PriorCoverage_OtherLine_PolicyNumberIdentifier_A", REAL_HISTORY) == "UM-333"
    # No prior property coverage, so that column stays empty.
    assert m("PriorCoverage_Property_PolicyNumberIdentifier_A", REAL_HISTORY) is None


def test_carrier_and_premium_columns_now_fill():
    """The client said these were missing. No scalar ever fed them."""
    m = ps._deterministic_map
    assert m("PriorCoverage_GeneralLiability_InsurerFullName_A", REAL_HISTORY) == "Acme Mutual"
    assert m("PriorCoverage_GeneralLiability_TotalPremiumAmount_A", REAL_HISTORY) == "$4,000"
    assert m("PriorCoverage_Automobile_TotalPremiumAmount_A", REAL_HISTORY) == "$2,500"


def test_other_column_names_the_line_it_holds():
    """Client: "Add line-of-business descriptions beside legitimate companion
    policies." The Other column has a box for it; nothing mapped it before."""
    assert ps._deterministic_map(
        "PriorCoverage_OtherLine_LineOfBusinessCode_A", REAL_HISTORY) == "Commercial Umbrella"


def test_rows_are_policy_terms_shared_across_columns():
    """There is ONE PolicyYear box per row, so a row must mean the same term in
    every column - otherwise row A would claim 2024 for GL and 2023 for Auto
    under a single year label."""
    m = ps._deterministic_map
    assert m("PriorCoverage_PolicyYear_A", REAL_HISTORY) == "2024"
    assert m("PriorCoverage_PolicyYear_B", REAL_HISTORY) == "2023"
    assert m("PriorCoverage_PolicyYear_C", REAL_HISTORY) is None
    # 2023 has GL only; Auto's row B must NOT borrow the 2024 auto policy.
    assert m("PriorCoverage_GeneralLiability_PolicyNumberIdentifier_B", REAL_HISTORY) == "GL-000"
    assert m("PriorCoverage_Automobile_PolicyNumberIdentifier_B", REAL_HISTORY) is None


def test_undated_history_falls_back_to_order_without_asserting_a_year():
    """A year we were never told must not be invented, but the policies we DO
    know about should still be shown."""
    facts = {"prior_coverage_by_line": [
        {"line": "General Liability", "policy_no": "GL-1"},
        {"line": "General Liability", "policy_no": "GL-2"},
    ]}
    m = ps._deterministic_map
    assert m("PriorCoverage_GeneralLiability_PolicyNumberIdentifier_A", facts) == "GL-1"
    assert m("PriorCoverage_GeneralLiability_PolicyNumberIdentifier_B", facts) == "GL-2"
    assert m("PriorCoverage_PolicyYear_A", facts) is None


# ── Column attribution ───────────────────────────────────────────────────────

@pytest.mark.parametrize("wording,expected", [
    ("General Liability", "GeneralLiability"),
    ("Commercial General Liability", "GeneralLiability"),
    # ACORD's column says "Automobile"; documents say Auto or Vehicle.
    ("Commercial Auto", "Automobile"),
    ("Business Auto", "Automobile"),
    ("Automobile", "Automobile"),
    ("Commercial Property", "Property"),
    # Everything ACORD does not give a column to lands in Other, by design.
    ("Commercial Inland Marine", "OtherLine"),
    ("Commercial Umbrella", "OtherLine"),
    ("Workers Compensation", "OtherLine"),
    ("Crime", "OtherLine"),
    # The decisive one: shares "liability" with the GL column and must NOT be
    # filed there.
    ("Liquor Liability", "OtherLine"),
    ("", "OtherLine"),
])
def test_column_attribution(wording, expected):
    assert ps._prior_coverage_column(wording) == expected


def test_stem_match_does_not_collapse_short_or_unrelated_words():
    assert ps._stem_match("auto", "automobile") is True
    assert ps._stem_match("liability", "liability") is True
    assert ps._stem_match("liquor", "liability") is False
    assert ps._stem_match("property", "proprietor") is False
    # Below the 4-character floor, only exact equality counts.
    assert ps._stem_match("gl", "general") is False


# ── Scope: must not touch other forms ────────────────────────────────────────

def test_forms_without_a_line_axis_are_untouched():
    """ACORD 130 and 131 have a plain PriorCoverage list with NO line columns
    (PriorCoverage_PolicyNumberIdentifier_A). Their scalar mapping must keep
    working - the new resolver has no business there."""
    assert ps._resolve_prior_coverage_cell(
        "PriorCoverage_PolicyNumberIdentifier_A", REAL_HISTORY) is ps._SCHED_SKIP
    assert ps._deterministic_map(
        "PriorCoverage_PolicyNumberIdentifier_A",
        {"prior_policy_number": "WC-999"}) == "WC-999"


def test_unknown_attributes_are_left_to_the_normal_rules():
    assert ps._resolve_prior_coverage_cell(
        "PriorCoverage_GeneralLiability_SomethingElse_A", REAL_HISTORY) is ps._SCHED_SKIP


def test_malformed_facts_are_survivable():
    for facts in ({}, {"prior_coverage_by_line": None},
                  {"prior_coverage_by_line": []},
                  {"prior_coverage_by_line": "nope"},
                  {"prior_coverage_by_line": ["a string, not a row"]},
                  {"prior_coverage_by_line": [{}]}):
        assert ps._deterministic_map(
            "PriorCoverage_GeneralLiability_PolicyNumberIdentifier_A", facts) is None


def test_no_live_rule_still_sprays_a_scalar_across_the_grid():
    """STANDING GUARD - fails the build if anyone re-adds a per-line prior
    coverage row to _ACORD_FIELD_RULES."""
    offenders = [
        (pat, fk) for pat, fk in ps._ACORD_FIELD_RULES
        if fk and pat.startswith("PriorCoverage_")
        and any(c in pat for c in _COLUMNS)
    ]
    assert not offenders, (
        "per-line prior-coverage cells must come from prior_coverage_by_line via "
        f"_resolve_prior_coverage_cell, not a scalar rule: {offenders}"
    )
