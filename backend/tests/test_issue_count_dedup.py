"""Distinct-issue counting for the post-remediation report (Figure 24).

The field-level engine (sqs_service.evaluate_stops) and cross_form_validator
report the SAME underlying deficiency in different words, so a raw len() over
the combined stop list double counts it and disagrees with the clustered view
the producer actually sees on screen. These lock the dedup behaviour.
"""
from services.issue_registry import (
    DEFAULT_CLUSTER,
    _LEGACY_SUPERSEDED_BY_CODE,
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


# ── Display-level de-duplication (client review #4) ──────────────────────────
# count_distinct_issues() above dedups the COUNT, but the reported defect is that
# the GROUPED VIEW still rendered both twins as two bullets in one cluster - only
# one carrying "Open to fix". These lock the display suppression in
# build_grouped_view: the legacy twin is hidden when its coded counterpart is
# present, but never when it is the only source of the blocker.
def test_grouped_view_shows_only_the_resolvable_twin():
    """The screenshot bug: COPE + peril each appeared twice, once without a fix
    affordance. After suppression each cluster has ONE item - the coded, resolvable
    one."""
    legacy_peril = (
        "Peril-specific deductibles referenced but not defined - specify amounts "
        "for: wind/hail, earthquake, flood"
    )
    coded_peril = {
        "code": "peril_deductible_referenced_but_undefined",
        "type": "hard_stop",
        "message": "Peril-specific deductible referenced on document but amounts "
                   "undefined: wind/hail, earthquake, flood.",
        "forms": ["ACORD_140", "ACORD_141"],
    }
    hard = [LEGACY_COPE, legacy_peril, CROSS_COPE_STOP, coded_peril["message"]]
    structured = build_structured_from_sources(
        legacy_hard=[LEGACY_COPE, legacy_peril],
        cross_issues=[CROSS_COPE_ISSUE, coded_peril],
    )
    grouped = build_grouped_view(
        structured, hard, [], cross_issues=[CROSS_COPE_ISSUE, coded_peril]
    )
    by_cluster = {c["cluster"]: c for c in grouped["hard_stops"]}
    assert "Property COPE completeness" in by_cluster
    assert "Property deductible completeness" in by_cluster
    for cl in ("Property COPE completeness", "Property deductible completeness"):
        c = by_cluster[cl]
        assert c["count"] == 1, f"{cl} still duplicated: {c['count']}"
        # The surviving item is the coded one (carries a resolution / Open-to-fix).
        assert c["items"][0]["code"] in _LEGACY_SUPERSEDED_BY_CODE
        assert c.get("resolution")


def test_legacy_twin_survives_when_coded_counterpart_absent():
    """The no-ACORD_140 edge case: the legacy engine fires COPE but the coded rule
    (which requires ACORD_140 triggered) does not. Suppression MUST NOT drop the
    legacy blocker when it is the only one present."""
    structured = build_structured_from_sources(legacy_hard=[LEGACY_COPE])
    grouped = build_grouped_view(structured, [LEGACY_COPE], [], cross_issues=[])
    all_msgs = [it["message"] for c in grouped["hard_stops"] for it in c["items"]]
    assert any(LEGACY_COPE in m for m in all_msgs), "legacy blocker was wrongly dropped"


# ── Structured-dict conflict splitting lands as separate cross-document items
# (client screenshot #6) ───────────────────────────────────────────────────────
# extraction_service.detect_source_conflicts now emits one message PER differing
# sub-key of a structured dict field (e.g. risk_transfer.mortgagee_name,
# risk_transfer.waiver_of_subrogation_required) instead of one bundled dict-repr
# blob. This locks the DOWNSTREAM half of that fix: extraction_pipeline.py derives
# a `source_conflict_<field>` code from the real fact key the detector now returns
# (return_fields=True - NOT a regex on the display message any more, since client
# #1 stripped the raw key out of the message), and issue_registry's prefix rule
# ("source_conflict_", "Cross-document data conflicts", "required") clusters each
# sub-key message as its OWN item in that cluster - never re-bundled, correctly
# labelled "Cross-document data conflicts". Client #4: each nested sub-key item
# now carries an HONEST REVIEW NOTE (mode "none" + note) rather than nothing, so
# it never looks skipped - but never a functional typed-value button either,
# since risk_transfer's sub-fields have no scalar apply path.
def _source_conflict_issue(field, message):
    """Mirror extraction_pipeline.py's code derivation for detect_source_conflicts()
    output (`source_conflict_<field>` / `source_conflict_carrier_<field>`), so
    this test exercises the exact code shape the real pipeline emits."""
    is_carrier = message.startswith("Carrier names differ")
    code = f"source_conflict_{'carrier_' if is_carrier else ''}{field}"
    return {"code": code, "type": "soft_warning", "message": message, "forms": []}


def test_structured_dict_conflict_splits_into_separate_cross_document_items():
    mortgagee_msg = (
        "Conflicting values for Mortgagee Name across documents - "
        "Dec Page: First National Bank, Certificate of Insurance: Second City Trust. "
        "Fix: Review and confirm the correct value."
    )
    waiver_msg = (
        "Conflicting values for Waiver Of Subrogation Required "
        "across documents - Dec Page: Yes, Certificate of Insurance: No. "
        "Fix: Review and confirm the correct value."
    )
    issues = [
        _source_conflict_issue("risk_transfer.mortgagee_name", mortgagee_msg),
        _source_conflict_issue("risk_transfer.waiver_of_subrogation_required", waiver_msg),
    ]
    soft = [mortgagee_msg, waiver_msg]
    structured = build_structured_from_sources(cross_issues=issues)
    grouped = build_grouped_view(structured, [], soft, cross_issues=issues)

    by_cluster = {
        c["cluster"]: c for tier_clusters in grouped["warnings"].values() for c in tier_clusters
    }
    assert "Cross-document data conflicts" in by_cluster
    cluster = by_cluster["Cross-document data conflicts"]
    assert cluster["count"] == 2, "sub-key conflicts were re-bundled into one item"
    msgs = {it["message"] for it in cluster["items"]}
    assert msgs == {mortgagee_msg, waiver_msg}
    # Client #4: a nested sub-field conflict now carries an HONEST REVIEW NOTE
    # (mode "none" + note) so the row isn't a bare Resolve/Dismiss that looks
    # skipped - but it is NOT a functional typed-value/schedule button, because
    # risk_transfer sub-fields have no scalar apply path.
    for it in cluster["items"]:
        res = it.get("resolution") or {}
        assert res.get("mode") == "none", "nested sub-field must not get a typed-value button"
        assert res.get("note"), "review note explaining why it can't be auto-applied"
