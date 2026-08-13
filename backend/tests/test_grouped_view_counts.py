"""The completion toast must quote the number of issue cards the screen draws.

Client report (2026-08-12, screenshot): the corner notification read
"1 warning found" while the review screen printed THREE warning clusters -
"Missing baseline form", "GL exposure basis" and "Auto optional coverage gaps".

Root cause: the toast counted `len(soft_stops)`, an array that is the SQS
capping input, not a headline count. Cross-form issues reach the display
through `structured_issues` (extraction_pipeline mirrors EVERY cross-form
issue into it, whatever its type) while `split_cross_form_issues` only ever
routes hard/soft into the stop arrays - every `advisory` rule is invisible to
len(). The legacy duplicate suppression pushes the same count the other way.

`build_grouped_view` now returns `counts`, derived from the clusters it
actually rendered. These lock that contract.
"""
from services.issue_registry import (
    build_grouped_view,
    build_structured_from_sources,
    classify_legacy,
    make_issue,
)

# Verbatim from the client's screenshot. The GL line carries the "Fix:" hint
# that extraction_pipeline._ensure_fix_hint stamps onto LEGACY stops only -
# which is how you tell the one array-backed warning from the two that are not.
GL_LEGACY = (
    "GL coverage detected but no revenue or payroll found "
    "Fix: Review and correct this before proceeding."
)
ACORD125_MISSING = {
    "code": "acord125_missing",
    "type": "soft_warning",
    "message": (
        "ACORD 125 (Commercial Insurance Application) was not detected. It is "
        "normally required for every commercial submission - please review the "
        "missing baseline data before generating forms."
    ),
    "forms": [],
}
UM_UIM_ADVISORY = {
    "code": "auto_um_uim_not_specified",
    "type": "advisory",
    "message": (
        "Uninsured/Underinsured Motorist (UM/UIM) coverage is not specified on "
        "the auto application. UM/UIM is required in many states - confirm with "
        "the insured whether coverage is desired or waived."
    ),
    "forms": ["ACORD_127"],
}


def _legacy_soft(msg):
    code, cluster, tier = classify_legacy(msg, "soft_warning")
    return make_issue(code or "legacy_soft_0", "soft_warning", msg,
                      cluster=cluster, tier=tier)


def _rendered(grouped):
    """What the screen prints: each tier header sums cluster["count"]."""
    return {
        "hard_stops": sum(c["count"] for c in grouped["hard_stops"]),
        "warnings": sum(c["count"] for cs in grouped["warnings"].values() for c in cs),
    }


def test_client_reported_case_toast_matches_the_three_rendered_cards():
    """Must never fail: the literal screenshot. 1 -> 3."""
    # extraction_pipeline.py appends every cross-form issue to structured_issues
    # regardless of type; only the legacy GL stop reaches soft_stops.
    structured = [_legacy_soft(GL_LEGACY)]
    for iss in (ACORD125_MISSING, UM_UIM_ADVISORY):
        structured.append(make_issue(iss["code"], iss["type"], iss["message"], iss["forms"]))

    grouped = build_grouped_view(structured, [], [GL_LEGACY])

    assert _rendered(grouped)["warnings"] == 3, "the screen draws three warning cards"
    assert grouped["counts"]["warnings"] == 3, 'toast used to say "1 warning found"'
    assert grouped["counts"]["hard_stops"] == 0
    # The three clusters from the screenshot, one per tier.
    assert {c["cluster"] for cs in grouped["warnings"].values() for c in cs} == {
        "Missing baseline form", "GL exposure basis", "Auto optional coverage gaps",
    }


def test_counts_always_equal_what_the_view_renders():
    """The whole contract, stated once. Any future change to clustering,
    suppression or the safety net keeps the toast honest for free."""
    cases = [
        ([], [], []),
        ([_legacy_soft(GL_LEGACY)], [], [GL_LEGACY]),
        (build_structured_from_sources(cross_issues=[ACORD125_MISSING]),
         [], [ACORD125_MISSING["message"]]),
        ([make_issue(UM_UIM_ADVISORY["code"], "advisory",
                     UM_UIM_ADVISORY["message"], UM_UIM_ADVISORY["forms"])], [], []),
    ]
    for structured, hard, soft in cases:
        grouped = build_grouped_view(structured, hard, soft)
        assert grouped["counts"] == _rendered(grouped)


def test_important_preview_is_never_double_counted():
    """"Important" echoes the top warning clusters that are ALSO listed in the
    tiers below, where they are actionable. Counting both would inflate the
    toast by up to 3."""
    # Five real legacy phrases that classify into five DIFFERENT clusters -
    # unclassified strings would all collapse into "Other validations" and the
    # preview would hold one cluster, proving nothing.
    soft = [
        "Peril-specific deductibles referenced but not defined - specify amounts for: wind/hail",
        "Property valuation method not specified - select RCV or ACV",
        "Business Income coverage detected but no limit stated",
        "Coinsurance percentage not stated",
        "Umbrella attaches over WC but Employers Liability limits are missing",
    ]
    structured = [_legacy_soft(m) for m in soft]

    grouped = build_grouped_view(structured, [], soft)

    assert len(grouped["important"]) == 3, "preview should be populated for this to prove anything"
    assert grouped["counts"]["warnings"] == 5
    inflated = grouped["counts"]["warnings"] + sum(c["count"] for c in grouped["important"])
    assert grouped["counts"]["warnings"] != inflated


def test_suppressed_legacy_twin_is_counted_once_not_twice():
    """The other direction: both engines report one problem, the display hides
    the legacy twin, and the raw array still carries it. The toast must follow
    the display, not the array."""
    legacy = "Property Minimum Viable COPE incomplete - missing: construction_type"
    coded = {
        "code": "minimum_viable_cope_missing",
        "type": "hard_stop",
        "message": "Property submission missing Minimum Viable COPE: construction_type",
        "forms": ["ACORD_140"],
    }
    coded_stop = coded["message"] + " (Affects: ACORD 140. Fix: Review the coverage/limit details for the affected form(s).)"
    hard = [legacy, coded_stop]
    structured = build_structured_from_sources(legacy_hard=[legacy], cross_issues=[coded])

    grouped = build_grouped_view(structured, hard, [], cross_issues=[coded])

    assert len(hard) == 2, "the capping array still carries both - it must not change"
    assert grouped["counts"]["hard_stops"] == 1
    assert grouped["counts"] == _rendered(grouped)


def test_counts_are_present_on_an_empty_view():
    """The frontend falls back to raw array length when `counts` is absent, so
    the key must exist even with nothing to report - otherwise a clean package
    silently takes the legacy path."""
    grouped = build_grouped_view([], [], [])
    assert grouped["counts"] == {"hard_stops": 0, "warnings": 0}


def test_hard_and_warning_counts_do_not_leak_into_each_other():
    hard_msg = "Umbrella detected but no underlying coverage found"
    soft_msg = "Coinsurance percentage not stated. Fix: Review and correct this."
    structured = build_structured_from_sources(legacy_hard=[hard_msg], legacy_soft=[soft_msg])

    grouped = build_grouped_view(structured, [hard_msg], [soft_msg])

    assert grouped["counts"] == {"hard_stops": 1, "warnings": 1}
