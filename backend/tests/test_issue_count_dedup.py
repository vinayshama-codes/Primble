"""Distinct-issue counting for the post-remediation report (Figure 24).

The field-level engine (sqs_service.evaluate_stops) and cross_form_validator
report the SAME underlying deficiency in different words, so a raw len() over
the combined stop list double counts it and disagrees with the clustered view
the producer actually sees on screen. These lock the dedup behaviour.
"""
from services.issue_registry import (
    DEFAULT_CLUSTER,
    build_grouped_view,
    build_structured_from_sources,
    count_distinct_issues,
)

# Verbatim message shapes from the two real producers:
#   sqs_service.py::evaluate_stops        -> LEGACY_COPE
#   cross_form_validator.py::_check_minimum_viable_cope_unit -> CROSS_COPE_MSG
LEGACY_COPE = (
    "Property Minimum Viable COPE incomplete - missing: construction_type, year_built"
)
CROSS_COPE_MSG = "Property submission missing Minimum Viable COPE: construction_type"
# split_cross_form_issues() appends this attribution suffix on the way to the
# plain string list, so the stop string is NOT byte-identical to the issue dict's
# message. build_grouped_view's prefix matching is what has to bridge that.
CROSS_COPE_STOP = (
    CROSS_COPE_MSG
    + " (Affects: ACORD 140. Fix: Review the coverage/limit details for the affected form(s).)"
)
CROSS_COPE_ISSUE = {
    "code": "minimum_viable_cope_missing",
    "type": "hard_stop",
    "message": CROSS_COPE_MSG,
    "forms": ["ACORD_140"],
}
UMBRELLA_ISSUE = {
    "code": "umbrella_no_underlying_coverage",
    "type": "hard_stop",
    "message": "Umbrella detected but no underlying coverage found",
    "forms": ["ACORD_131"],
}


def test_same_problem_from_both_engines_counts_once():
    """The reported defect: incomplete COPE is one problem, counted twice."""
    hard = [LEGACY_COPE, CROSS_COPE_STOP]
    counts = count_distinct_issues(
        hard_stops=hard,
        soft_stops=[],
        legacy_hard=[LEGACY_COPE],
        legacy_soft=[],
        cross_issues=[CROSS_COPE_ISSUE],
    )
    assert len(hard) == 2       # raw string count double counts
    assert counts["hard"] == 1  # ...but there is only one real problem


def test_genuinely_distinct_problems_are_not_merged():
    """Dedup must not become under-reporting: unrelated stops stay separate."""
    hard = [LEGACY_COPE, UMBRELLA_ISSUE["message"]]
    counts = count_distinct_issues(
        hard_stops=hard,
        soft_stops=[],
        legacy_hard=[LEGACY_COPE],
        legacy_soft=[],
        cross_issues=[UMBRELLA_ISSUE],
    )
    assert counts["hard"] == 2


def test_coded_cross_form_issues_do_not_collapse_into_other_validations():
    """Cross-form issues are never added to structured_issues by the pipeline,
    so build_grouped_view's uncoded safety net drops every one of them into the
    single "Other validations" bucket. Counting THAT would under-report badly,
    which is why build_structured_from_sources feeds them in with their codes.
    """
    hard = [CROSS_COPE_STOP, UMBRELLA_ISSUE["message"]]

    structured = build_structured_from_sources(
        cross_issues=[CROSS_COPE_ISSUE, UMBRELLA_ISSUE]
    )
    grouped = build_grouped_view(structured, hard, [])
    assert len(grouped["hard_stops"]) == 2
    assert DEFAULT_CLUSTER not in {c["cluster"] for c in grouped["hard_stops"]}

    # Without the coded feed the two unrelated problems collapse into one
    # bucket - the behaviour that made a naive cluster count wrong.
    naive = build_grouped_view([], hard, [])
    assert len(naive["hard_stops"]) == 1
    assert naive["hard_stops"][0]["cluster"] == DEFAULT_CLUSTER


def test_advisories_are_excluded():
    """Advisories never reach hard_stops/soft_stops, so counting them would
    report problems the caller is not actually surfacing."""
    advisory = {
        "code": "acv_high_value_building",
        "type": "advisory",
        "message": "Valuation basis conflict on a high-value building",
        "forms": ["ACORD_140"],
    }
    structured = build_structured_from_sources(cross_issues=[advisory])
    assert structured == []

    counts = count_distinct_issues(
        hard_stops=[], soft_stops=[], cross_issues=[advisory]
    )
    assert counts == {"hard": 0, "soft": 0}


def test_soft_stops_are_clustered_across_all_tiers():
    """Warnings are bucketed by tier; the count must span every bucket, not
    just the required one."""
    binder_tier = {
        "code": "auto_um_uim_not_specified",       # TIER_MAP -> binder_followup
        "type": "soft_warning",
        "message": "UM/UIM coverage is not specified on the auto application",
        "forms": ["ACORD_127"],
    }
    recommended_tier = {
        "code": "claims_made_missing_retro_date",  # TIER_MAP -> recommended
        "type": "soft_warning",
        "message": "Claims-made GL policy is missing a retroactive date",
        "forms": ["ACORD_126"],
    }
    soft = [binder_tier["message"], recommended_tier["message"]]
    counts = count_distinct_issues(
        hard_stops=[], soft_stops=soft,
        cross_issues=[binder_tier, recommended_tier],
    )
    assert counts["hard"] == 0
    assert counts["soft"] == 2


def test_empty_and_none_inputs_are_safe():
    assert count_distinct_issues([], []) == {"hard": 0, "soft": 0}
    assert count_distinct_issues(None, None, None, None, None) == {"hard": 0, "soft": 0}
    assert build_structured_from_sources() == []


def test_inputs_are_never_mutated():
    """Read-only contract: the stop lists feed SQS capping elsewhere."""
    hard = [LEGACY_COPE, CROSS_COPE_STOP]
    soft = ["Coinsurance percentage not stated"]
    issues = [dict(CROSS_COPE_ISSUE)]
    hard_copy, soft_copy, issues_copy = list(hard), list(soft), [dict(issues[0])]

    count_distinct_issues(
        hard_stops=hard, soft_stops=soft,
        legacy_hard=[LEGACY_COPE], legacy_soft=soft, cross_issues=issues,
    )

    assert hard == hard_copy
    assert soft == soft_copy
    assert issues == issues_copy
