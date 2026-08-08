"""Post-remediation issue diff + structured-issue refresh (Figure 24).

Covers the three defects this area had:
  1. structured_issues was written once at extraction time and never refreshed,
     so a hard stop the client RESOLVED kept rendering as a blocker.
  2. cross-form issues were never added to structured_issues, so every one of
     them collapsed into a single "Other validations" cluster.
  3. there was no issue-level diff at all - only a score delta.
"""
from services.issue_registry import (
    DEFAULT_CLUSTER,
    build_grouped_view,
    build_structured_from_sources,
    diff_grouped_views,
    drop_confirmed_ocr_issues,
    index_clusters,
    make_issue,
    replace_recomputed_issues,
)

COPE_HARD = "Property Minimum Viable COPE incomplete - missing: locations, occupancy type"
COPE_HARD_PARTIAL = "Property Minimum Viable COPE incomplete - missing: occupancy type"
UMBRELLA_HARD = "Umbrella detected but no underlying coverage found"

UM_UIM = {
    "code": "auto_um_uim_not_specified",   # cluster: Auto optional coverage gaps
    "message": "UM/UIM coverage is not specified on the auto application",
    "forms": ["ACORD_127"],
}


def _legacy(hard=(), soft=()):
    return build_structured_from_sources(legacy_hard=list(hard), legacy_soft=list(soft))


# ── 1. structured_issues refresh ─────────────────────────────────────────────

def test_resolved_hard_stop_stops_rendering_as_a_blocker():
    """The reported defect: build_grouped_view holds an issue at its ORIGINAL
    severity when its message is in neither final list, so a stale entry keeps
    showing as a hard stop forever."""
    persisted = _legacy(hard=[COPE_HARD])

    # Old behaviour: stop is resolved (absent from both lists) but still renders.
    stale_view = build_grouped_view(persisted, [], [])
    assert len(stale_view["hard_stops"]) == 1

    # New behaviour: the recomputed entries are replaced with what the fresh
    # evaluation actually produced (nothing), so the blocker disappears.
    refreshed = replace_recomputed_issues(persisted, _legacy(hard=[]))
    assert build_grouped_view(refreshed, [], [])["hard_stops"] == []


def test_refresh_preserves_sources_the_recalculation_does_not_rerun():
    """Doc conflicts / OCR / Tier-1 entries must survive: nothing in the
    recalculation re-runs those detectors, so it cannot know they cleared."""
    persisted = [
        make_issue("doc_conflict_hard_carrier", "hard_stop", "Carrier name conflict between documents"),
        make_issue("ocr_low_confidence_fein", "soft_warning", "Low OCR confidence on FEIN"),
        make_issue("tier1_missing_applicant_name", "soft_warning", "Applicant name is missing"),
    ] + _legacy(hard=[COPE_HARD])

    refreshed = replace_recomputed_issues(persisted, _legacy(hard=[]))

    codes = [i["code"] for i in refreshed]
    assert "doc_conflict_hard_carrier" in codes
    assert "ocr_low_confidence_fein" in codes
    assert "tier1_missing_applicant_name" in codes
    assert not any(c.startswith("legacy_") for c in codes)


# ── OCR "confirm this field" warnings ────────────────────────────────────────

def _ocr(field):
    return make_issue(
        f"ocr_low_confidence_{field}", "soft_warning",
        f"Low OCR confidence on critical field - confirm: {field}",
    )


def test_ocr_warning_clears_once_the_client_supplies_the_field():
    """The one preserved source an answer CAN settle. The warning asks a human
    to confirm the value; the questionnaire asks the client for exactly these
    fields, so leaving it open after they answer under-reports the fix."""
    issues = [_ocr("fein"), _ocr("applicant_name")]
    facts = {
        "fein": {"value": "84-2210987", "source": "client_arq"},
        "applicant_name": {"value": "Acme LLC", "source": "doc", "confidence": "ai_low"},
    }
    kept = drop_confirmed_ocr_issues(issues, facts=facts)
    codes = [i["code"] for i in kept]
    assert "ocr_low_confidence_fein" not in codes           # client answered it
    assert "ocr_low_confidence_applicant_name" in codes     # still only OCR's word


def test_ocr_warning_clears_on_producer_entry_and_on_confirmation():
    facts = {"fein": {"value": "84-2210987", "source": "producer"}}
    assert drop_confirmed_ocr_issues([_ocr("fein")], facts=facts) == []

    # Confirmed through the Data Consistency picker instead of typed in.
    assert drop_confirmed_ocr_issues(
        [_ocr("total_revenue")], facts={}, confirmed_keys={"total_revenue"},
    ) == []


def test_ocr_drop_is_fail_safe_for_anything_it_cannot_resolve():
    """Only drop when the code resolves to a demonstrably human-supplied fact.
    Everything else is kept, so the worst case is the prior behaviour."""
    facts = {"fein": {"value": "x", "source": "doc", "confidence": "ai_low"}}
    # Field absent from facts entirely.
    assert len(drop_confirmed_ocr_issues([_ocr("unknown_field")], facts=facts)) == 1
    # Fact present but still extractor-sourced.
    assert len(drop_confirmed_ocr_issues([_ocr("fein")], facts=facts)) == 1
    # Bare value (no envelope) proves nothing about who supplied it.
    assert len(drop_confirmed_ocr_issues([_ocr("fein")], facts={"fein": "x"})) == 1
    # Malformed code with no field suffix.
    assert len(drop_confirmed_ocr_issues(
        [make_issue("ocr_low_confidence_", "soft_warning", "m")], facts=facts)) == 1
    # No facts at all.
    assert len(drop_confirmed_ocr_issues([_ocr("fein")])) == 1


def test_other_preserved_sources_are_never_dropped():
    """Doc and source conflicts describe two DOCUMENTS disagreeing. A client
    answer cannot make them agree, so they must survive untouched even when the
    same field was answered."""
    issues = [
        make_issue("doc_conflict_hard_carrier", "hard_stop", "Carrier name conflict"),
        make_issue("source_conflict_fein", "soft_warning", "FEIN differs across documents"),
        _ocr("fein"),
    ]
    facts = {"fein": {"value": "84-2210987", "source": "client_arq"}}
    codes = [i["code"] for i in drop_confirmed_ocr_issues(issues, facts=facts)]
    assert codes == ["doc_conflict_hard_carrier", "source_conflict_fein"]


def test_cleared_ocr_warning_reports_as_resolved_in_the_diff():
    """End to end: the producer should be credited for it."""
    prior = build_grouped_view([_ocr("fein")], [], [_ocr("fein")["message"]])
    facts = {"fein": {"value": "84-2210987", "source": "client_arq"}}
    current = build_grouped_view(drop_confirmed_ocr_issues([_ocr("fein")], facts=facts), [], [])

    d = diff_grouped_views(prior, current)
    assert d["resolved_count"] == 1
    assert d["resolved"][0]["cluster"] == "Low OCR confidence"


def test_refresh_handles_empty_and_missing_inputs():
    assert replace_recomputed_issues(None, None) == []
    # A legacy stop carries its REAL rule code (not the old throwaway
    # `legacy_hard_<index>`), which is what lets resolution_for() find its fix
    # mode. The shared "legacy_" prefix is what replace_recomputed_issues keys
    # off, so it must survive.
    refreshed = replace_recomputed_issues([], _legacy(hard=[COPE_HARD]))
    assert refreshed[0]["code"] == "legacy_minimum_viable_cope"
    assert refreshed[0]["code"].startswith("legacy_")


# ── 2. cross-form issues cluster properly ────────────────────────────────────

def test_cross_issues_kwarg_gives_real_clusters():
    cross = [
        {"type": "hard_stop", "code": "minimum_viable_cope_missing",
         "message": "Property submission missing Minimum Viable COPE: construction type",
         "forms": ["ACORD_140"]},
        {"type": "hard_stop", "code": "umbrella_no_underlying_coverage",
         "message": UMBRELLA_HARD, "forms": ["ACORD_131"]},
    ]
    hard = [c["message"] for c in cross]

    without = build_grouped_view([], hard, [])
    assert len(without["hard_stops"]) == 1
    assert without["hard_stops"][0]["cluster"] == DEFAULT_CLUSTER

    with_cross = build_grouped_view([], hard, [], cross_issues=cross)
    assert len(with_cross["hard_stops"]) == 2
    assert DEFAULT_CLUSTER not in {c["cluster"] for c in with_cross["hard_stops"]}


def test_cross_issue_already_in_structured_is_not_counted_twice():
    """Injection must be idempotent against a caller that also persisted it."""
    cross = [{"type": "hard_stop", "code": "umbrella_no_underlying_coverage",
              "message": UMBRELLA_HARD, "forms": ["ACORD_131"]}]
    structured = build_structured_from_sources(cross_issues=cross)

    view = build_grouped_view(structured, [UMBRELLA_HARD], [], cross_issues=cross)
    assert len(view["hard_stops"]) == 1
    assert view["hard_stops"][0]["count"] == 1


# ── 3. the diff itself ───────────────────────────────────────────────────────

def test_diff_reports_resolved_new_and_still_open():
    prior = build_grouped_view(_legacy(hard=[COPE_HARD, UMBRELLA_HARD]),
                               [COPE_HARD, UMBRELLA_HARD], [])
    # COPE fixed, umbrella still open, a brand-new auto warning appeared.
    current = build_grouped_view(
        _legacy(hard=[UMBRELLA_HARD]), [UMBRELLA_HARD], [UM_UIM["message"]],
        cross_issues=[{**UM_UIM, "type": "soft_warning"}],
    )
    d = diff_grouped_views(prior, current)

    assert [i["cluster"] for i in d["resolved"]] == ["Property COPE completeness"]
    assert [i["cluster"] for i in d["new"]] == ["Auto optional coverage gaps"]
    assert [i["cluster"] for i in d["still_open"]] == ["Umbrella underlying coverage"]
    assert d["resolved_count"] == 1
    assert d["new_count"] == 1
    assert d["still_open_count"] == 1
    assert d["worsened_count"] == 0


def test_diff_flags_a_warning_that_became_a_hard_stop():
    """'Which got worse': the client's answer escalated an existing area."""
    soft_issue = {**UM_UIM, "type": "soft_warning"}
    hard_issue = {**UM_UIM, "type": "hard_stop"}
    prior = build_grouped_view([], [], [UM_UIM["message"]], cross_issues=[soft_issue])
    current = build_grouped_view([], [UM_UIM["message"]], [], cross_issues=[hard_issue])

    d = diff_grouped_views(prior, current)
    assert d["worsened_count"] == 1
    assert d["worsened"][0]["cluster"] == "Auto optional coverage gaps"
    assert d["worsened"][0]["severity"] == "hard_stop"
    # Worsened is a subset of still_open, not a separate disappearance.
    assert d["resolved_count"] == 0 and d["new_count"] == 0
    assert d["still_open_count"] == 1


def test_a_hard_stop_that_stays_hard_is_not_worsened():
    view = build_grouped_view(_legacy(hard=[COPE_HARD]), [COPE_HARD], [])
    d = diff_grouped_views(view, view)
    assert d["worsened_count"] == 0
    assert d["still_open_count"] == 1
    assert d["resolved_count"] == 0 and d["new_count"] == 0


def test_partial_fix_does_not_read_as_resolved_plus_new():
    """Legacy stop strings embed their own detail, so fixing ONE missing field
    rewrites the message. Diffing per message would report 1 resolved + 1 new;
    the truth is one issue, still open. This is why the diff is cluster-level."""
    prior = build_grouped_view(_legacy(hard=[COPE_HARD]), [COPE_HARD], [])
    current = build_grouped_view(_legacy(hard=[COPE_HARD_PARTIAL]), [COPE_HARD_PARTIAL], [])

    d = diff_grouped_views(prior, current)
    assert d["resolved_count"] == 0
    assert d["new_count"] == 0
    assert d["still_open_count"] == 1
    assert d["still_open"][0]["cluster"] == "Property COPE completeness"


def test_display_grouping_never_loses_a_cross_form_row():
    """The editor's Cross-Form Validation panel renders the raw cross_issues
    list, which INCLUDES advisories (UM/UIM, ACORD 101 narrative). Grouping it
    for display must surface every row - dropping advisories would silently
    delete issues the old flat list showed. Mirrors get_session()."""
    cross = [
        {"type": "hard_stop", "code": "minimum_viable_cope_missing",
         "message": "Property submission missing Minimum Viable COPE: construction type",
         "forms": ["ACORD_140"]},
        {"type": "soft_warning", "code": "auto_hired_nonowned_symbols_missing",
         "message": "Hired/Non-Owned auto exposure detected but symbols not defined",
         "forms": ["ACORD_127"]},
        {"type": "advisory", "code": "auto_um_uim_not_specified",
         "message": "UM/UIM coverage is not specified", "forms": ["ACORD_127"]},
        {"type": "advisory", "code": "acord101_required",
         "message": "ACORD 101 is required to explain subcontracting",
         "forms": ["ACORD_101"]},
    ]
    grouped = build_grouped_view(
        build_structured_from_sources(cross_issues=cross, include_advisories=True),
        [i["message"] for i in cross if i["type"] == "hard_stop"],
        [i["message"] for i in cross if i["type"] == "soft_warning"],
    )

    shown = [it["message"] for c in grouped["hard_stops"] for it in c["items"]]
    for clusters in grouped["warnings"].values():
        shown += [it["message"] for c in clusters for it in c["items"]]

    assert len(shown) == len(cross), f"lost rows: {set(i['message'] for i in cross) - set(shown)}"
    assert "UM/UIM coverage is not specified" in shown
    assert "ACORD 101 is required to explain subcontracting" in shown
    # And they are sequenced, not dumped in one bucket.
    assert DEFAULT_CLUSTER not in {c["cluster"] for c in grouped["hard_stops"]}


def test_legacy_warning_spelling_is_not_silently_dropped():
    """sqs_service.cross_validate() (used at form-generation time) emits
    type="warning" and no rule code, while cross_form_validator emits
    type="soft_warning" with a code. Filtering on the literal string dropped
    every legacy issue, so the panel silently fell back to its flat list at
    exactly the moment the producer first sees it."""
    legacy = [
        {"type": "warning", "message": "GL coverage detected - ACORD 126 should be included"},
        {"type": "warning", "message": "Property valuation method not specified on ACORD 140"},
        {"type": "hard_stop", "message": "Named insured missing - required on all forms"},
    ]
    structured = build_structured_from_sources(cross_issues=legacy, include_advisories=True)
    assert len(structured) == 3, "legacy issues were dropped"
    assert {i["severity"] for i in structured} == {"soft_warning", "hard_stop"}

    grouped = build_grouped_view(
        structured,
        ["Named insured missing - required on all forms"],
        [i["message"] for i in legacy if i["type"] == "warning"],
    )
    shown = [it["message"] for c in grouped["hard_stops"] for it in c["items"]]
    for clusters in grouped["warnings"].values():
        shown += [it["message"] for c in clusters for it in c["items"]]
    assert len(shown) == 3


def test_uncoded_cross_issue_still_reaches_a_real_cluster():
    """An uncoded legacy message whose text matches a known phrase must land in
    its real cluster, not the 'Other validations' catch-all."""
    legacy = [{"type": "warning",
               "message": "Property valuation method not specified on ACORD 140"}]
    structured = build_structured_from_sources(cross_issues=legacy, include_advisories=True)
    assert structured[0]["cluster"] == "Property valuation method"


def test_counting_still_excludes_advisories_by_default():
    """The display includes advisories; the COUNT must not - they are never in
    hard_stops/soft_stops, so counting them would overstate the problem list."""
    advisory = [{"type": "advisory", "code": "auto_um_uim_not_specified",
                 "message": "UM/UIM coverage is not specified", "forms": ["ACORD_127"]}]
    assert build_structured_from_sources(cross_issues=advisory) == []
    assert len(build_structured_from_sources(cross_issues=advisory, include_advisories=True)) == 1


def test_preserved_sources_are_still_open_never_resolved_or_new():
    """Load-bearing invariant. A recalculation does not re-run doc-consistency /
    OCR / Tier-1 detection, and their messages are absent from the stop lists it
    rebuilds. Because those entries are carried into BOTH sides of the diff
    unchanged, they must always land in still_open - never be announced as
    resolved (claiming a fix that never happened) or as new (alarming the
    producer about something that was always there)."""
    doc_conflict = make_issue(
        "doc_conflict_hard_carrier", "hard_stop",
        "Carrier name conflict between documents",
    )
    persisted = [doc_conflict] + _legacy(hard=[COPE_HARD])

    prior = build_grouped_view(persisted, [COPE_HARD], [])
    # Client resolves COPE; the doc conflict is neither re-checked nor cleared.
    refreshed = replace_recomputed_issues(persisted, _legacy(hard=[]))
    current = build_grouped_view(refreshed, [], [])

    d = diff_grouped_views(prior, current)
    clusters = lambda key: [i["cluster"] for i in d[key]]

    assert "Document identity & date conflicts" in clusters("still_open")
    assert "Document identity & date conflicts" not in clusters("resolved")
    assert "Document identity & date conflicts" not in clusters("new")
    assert clusters("resolved") == ["Property COPE completeness"]


def test_everything_resolved():
    prior = build_grouped_view(_legacy(hard=[COPE_HARD]), [COPE_HARD], [])
    current = build_grouped_view([], [], [])
    d = diff_grouped_views(prior, current)
    assert d["resolved_count"] == 1
    assert d["still_open_count"] == 0 and d["new_count"] == 0


def test_diff_of_empty_views_is_empty():
    empty = build_grouped_view([], [], [])
    d = diff_grouped_views(empty, empty)
    assert d == {
        "resolved": [], "new": [], "worsened": [], "updated": [], "still_open": [],
        "resolved_count": 0, "new_count": 0, "worsened_count": 0,
        "updated_count": 0, "still_open_count": 0,
    }
    assert diff_grouped_views({}, {})["resolved_count"] == 0


def test_partial_progress_is_reported_as_updated():
    """The client answered SOME of a rule's missing fields. The cluster is still
    open, so it is not "resolved" - but reporting nothing at all tells the
    producer the questionnaire achieved nothing, which is false."""
    before = "Property Minimum Viable COPE incomplete - missing: locations, occupancy type"
    after  = "Property Minimum Viable COPE incomplete - missing: occupancy type"

    prior   = build_grouped_view(_legacy(hard=[before]), [before], [])
    current = build_grouped_view(_legacy(hard=[after]),  [after],  [])
    d = diff_grouped_views(prior, current)

    assert d["resolved_count"] == 0      # honest: the rule is not cleared
    assert d["new_count"] == 0           # and this is not a brand-new problem
    assert d["still_open_count"] == 1
    assert d["updated_count"] == 1       # ...but the producer is told it moved
    assert d["updated"][0]["cluster"] == "Property COPE completeness"


def test_message_formatting_must_match_extraction_or_everything_looks_updated():
    """extraction_pipeline appends a "Fix: ..." hint to every evaluate_stops
    message before storing structured_issues. The ARQ recalculation rebuilds
    those messages, and if it does NOT apply the same hint the text differs, the
    issue_id differs, and every cluster containing a field-level stop reports as
    "updated" on the first recalculation despite nothing having changed.

    This pins the contract: whatever recalculate_session_scores rebuilds must be
    byte-identical to what extraction stored for an unchanged stop.
    """
    from services.extraction_pipeline import _ensure_fix_hint

    raw = [
        "Property valuation method not specified on ACORD 140",
        "GL coverage detected but no class codes found",
    ]
    stored = _ensure_fix_hint(list(raw))
    assert stored != raw, "extraction no longer rewrites messages - update this test"

    prior = build_grouped_view(
        build_structured_from_sources(legacy_soft=stored), [], stored)

    # Raw rebuild (the bug) invents changes that never happened.
    buggy = build_grouped_view(
        build_structured_from_sources(legacy_soft=raw), [], raw)
    assert diff_grouped_views(prior, buggy)["updated_count"] > 0

    # Rebuilt the way recalculate_session_scores now does it: silent.
    correct = build_grouped_view(
        build_structured_from_sources(legacy_soft=_ensure_fix_hint(list(raw))),
        [], _ensure_fix_hint(list(raw)))
    d = diff_grouped_views(prior, correct)
    assert d["updated_count"] == 0
    assert d["resolved_count"] == 0
    assert d["new_count"] == 0


def test_unchanged_cluster_is_not_reported_as_updated():
    """Guards the obvious false positive: an untouched issue must stay quiet."""
    view = build_grouped_view(_legacy(hard=[COPE_HARD]), [COPE_HARD], [])
    d = diff_grouped_views(view, view)
    assert d["updated_count"] == 0
    assert d["still_open_count"] == 1


def test_worsened_and_updated_never_double_report():
    """A cluster that escalated to a hard stop is 'worsened', not also
    'updated' - two chips for one event would overstate what happened."""
    soft_issue = {**UM_UIM, "type": "soft_warning"}
    hard_issue = {**UM_UIM, "type": "hard_stop",
                  "message": UM_UIM["message"] + " (now blocking)"}
    prior = build_grouped_view([], [], [soft_issue["message"]], cross_issues=[soft_issue])
    current = build_grouped_view([], [hard_issue["message"]], [], cross_issues=[hard_issue])

    d = diff_grouped_views(prior, current)
    assert d["worsened_count"] == 1
    assert d["updated_count"] == 0
    worsened_clusters = {i["cluster"] for i in d["worsened"]}
    updated_clusters = {i["cluster"] for i in d["updated"]}
    assert not (worsened_clusters & updated_clusters)


def _cross(code, message, forms=("ACORD_140",)):
    return {"type": "soft_warning", "code": code, "message": message, "forms": list(forms)}


def _cross_view(issues):
    """Grouped view of coded cross-form issues, assembled the way get_session does."""
    return build_grouped_view(
        build_structured_from_sources(cross_issues=issues, include_advisories=True),
        [], [i["message"] for i in issues],
    )


# Both map to "Location & address data" via CLUSTER_MAP.
ADDR_A = _cross("physical_vs_mailing_address_unclear",
                "Mailing address captured but physical operating address is missing",
                ["ACORD_125"])
ADDR_B = _cross("location_address_mismatch",
                "Location addresses do not align between ACORD 125 and ACORD 140",
                ["ACORD_125", "ACORD_140"])
# Both map to "Property deductible completeness".
DED_AOP = _cross("property_aop_deductible_missing",
                 "Property coverage present but AOP deductible not specified")
DED_PERIL_BEFORE = _cross("peril_deductible_referenced_but_undefined",
                          "Peril deductibles undefined: wind/hail, earthquake, flood")
DED_PERIL_AFTER = _cross("peril_deductible_referenced_but_undefined",
                         "Peril deductibles undefined: earthquake, flood")
VALUATION = _cross("property_valuation_method_missing",
                   "Property valuation method is missing - select RCV or ACV")


def test_an_issue_added_to_an_existing_cluster_is_new_not_merely_updated():
    """A second, distinct problem appearing in an already-open area is a NEW
    problem - the producer sees a new row. Burying it under "updated" would
    under-report something the client's answers actually caused."""
    d = diff_grouped_views(_cross_view([ADDR_A]), _cross_view([ADDR_A, ADDR_B]))

    assert d["new_count"] == 1
    assert d["new"][0]["cluster"] == "Location & address data"
    assert d["resolved_count"] == 0 and d["updated_count"] == 0


def test_an_issue_cleared_from_a_still_open_cluster_is_resolved():
    """The defect this replaced: one issue in a cluster was cleared, the cluster
    stayed open, and it reported as "updated" - so a warning the producer
    watched disappear was never credited as resolved."""
    d = diff_grouped_views(
        _cross_view([DED_AOP, DED_PERIL_BEFORE, VALUATION]),
        _cross_view([DED_AOP, DED_PERIL_BEFORE]),          # valuation answered
    )
    assert d["resolved_count"] == 1
    assert d["updated_count"] == 0
    assert "Property valuation method" in {i["cluster"] for i in d["resolved"]}
    # The deductible cluster is untouched and must stay quiet.
    assert "Property deductible completeness" not in {i["cluster"] for i in d["resolved"]}


def test_changed_count_reports_what_moved_not_cluster_size():
    """"Updated (3)" must mean three issues changed, not "this area holds three
    issues, one of which changed"."""
    d = diff_grouped_views(
        _cross_view([DED_AOP, DED_PERIL_BEFORE]),
        _cross_view([DED_AOP, DED_PERIL_AFTER]),
    )
    assert d["updated_count"] == 1              # one issue moved
    entry = d["updated"][0]
    assert entry["cluster"] == "Property deductible completeness"
    assert entry["count"] == 2                  # ...inside a 2-issue cluster
    assert entry["changed"] == 1


def test_index_clusters_lets_a_hard_stop_win_its_cluster():
    """Same cluster reported at both severities must index as the hard stop."""
    cope_soft = "Carrier-Grade COPE incomplete - SQS capped at 85. Missing: year built"
    view = build_grouped_view(
        _legacy(hard=[COPE_HARD], soft=[cope_soft]), [COPE_HARD], [cope_soft],
    )
    idx = index_clusters(view)
    assert idx["Property COPE completeness"]["severity"] == "hard_stop"
    # The soft one is a different cluster, so it survives separately.
    assert idx["Property COPE quality"]["severity"] == "soft_warning"


def test_slim_payload_drops_items_but_keeps_what_the_ui_needs():
    prior = build_grouped_view(_legacy(hard=[COPE_HARD]), [COPE_HARD], [])
    d = diff_grouped_views(prior, build_grouped_view([], [], []))
    entry = d["resolved"][0]
    assert "items" not in entry
    assert set(entry) == {
        "cluster", "issue_id", "message", "severity", "tier", "forms", "count", "changed",
    }
    assert entry["message"] == COPE_HARD
