"""test_issue_resolution.py

Guard tests for the SQS-panel inline issue resolution feature
(issue_registry.RESOLUTION_MAP + cross_form_validator._issue + the grouped view).

The whole feature hinges on RESOLUTION_MAP being CORRECT and COMPLETE: a
`field`-mode resolution that names a fact the producer-answer path can't write,
or a `schedule`-mode resolution naming a schedule that doesn't exist, produces an
"Open" button that opens onto nothing - silently, with every other test green.
These tests fail the build when that happens, mirroring the existing
test_every_schedule_column_binds_to_a_live_acord_field guard.
"""

from services.issue_registry import (
    RESOLUTION_MAP,
    CLUSTER_MAP,
    resolution_for,
    make_issue,
    build_grouped_view,
    build_structured_from_sources,
)

_VALID_MODES = {"field", "schedule", "narrative", "none"}


def test_every_cross_form_cluster_code_has_a_resolution():
    """Every cross-form rule code (CLUSTER_MAP is the authoritative list) must
    have a resolution descriptor, so no validation ever renders a dead pill."""
    missing = sorted(c for c in CLUSTER_MAP if c not in RESOLUTION_MAP)
    assert not missing, f"cross-form codes with no RESOLUTION_MAP entry: {missing}"


def test_no_orphan_resolution_codes():
    """Every RESOLUTION_MAP code must be a real cross-form code (in CLUSTER_MAP),
    so the map can't rot with entries for renamed/deleted rules."""
    orphans = sorted(c for c in RESOLUTION_MAP if c not in CLUSTER_MAP)
    assert not orphans, f"RESOLUTION_MAP codes not emitted by any rule: {orphans}"


def test_modes_are_well_formed():
    for code, res in RESOLUTION_MAP.items():
        mode = res.get("mode")
        assert mode in _VALID_MODES, f"{code}: invalid mode {mode!r}"
        if mode == "field":
            facts = res.get("facts")
            assert facts and isinstance(facts, list), f"{code}: field mode needs non-empty facts"
            assert all(isinstance(f, str) and f for f in facts), f"{code}: bad fact name"
        elif mode == "schedule":
            assert res.get("schedule_key"), f"{code}: schedule mode needs schedule_key"


def test_field_mode_facts_are_writable_via_producer_answer():
    """Every `field`-mode fact must resolve through arq_service._canonical_key,
    i.e. actually be writable by POST /api/audit/resolve-issue. If not, the modal
    input would silently fail to apply."""
    from services.arq_service import _canonical_key

    bad = []
    for code, res in RESOLUTION_MAP.items():
        if res.get("mode") != "field":
            continue
        for fact in res["facts"]:
            if not _canonical_key(fact):
                bad.append((code, fact))
    assert not bad, f"field-mode facts that are NOT writable canonical facts: {bad}"


# ── Tier-1 baseline fields (client review #4) ────────────────────────────────
# "ACORD 125 minimum field missing: X (Fix: Provide this value manually...)" is a
# soft warning generated per-field by form_routes.py (code = f"tier1_missing_{label}"),
# NOT a RESOLUTION_MAP entry - resolution_for() derives it dynamically via
# _tier1_resolution(). These lock that every real tier1 label actually resolves
# (so the "Open to fix" button that now appears for these rows is never a dead
# end) and that a garbage/renamed label safely falls back to None instead of
# crashing or fabricating a resolution.
def test_every_tier1_label_resolves_to_a_writable_fact():
    from services.sqs_service import TIER1_FIELDS, TIER1_CONTACT
    from services.arq_service import _canonical_key

    bad = []
    for label in list(TIER1_FIELDS.values()) + ["Contact information"]:
        res = resolution_for(f"tier1_missing_{label}")
        if not res or res.get("mode") != "field" or not res.get("facts"):
            bad.append((label, res))
            continue
        for fact in res["facts"]:
            if not _canonical_key(fact):
                bad.append((label, fact))
    assert not bad, f"tier1 labels with no writable resolution: {bad}"

    # "Contact information" is the one label backed by more than one fact (any
    # of the three satisfies check_tier1()) - confirm all three ride along so
    # the producer isn't limited to typing just one specific contact field.
    contact_res = resolution_for("tier1_missing_Contact information")
    assert set(contact_res["facts"]) == set(TIER1_CONTACT)


def test_unknown_tier1_label_returns_none_not_a_fabricated_resolution():
    """A label that doesn't match any known tier1 field (e.g. after a future
    rename of TIER1_FIELDS) must fall back to None - never crash, never invent
    a fact-less resolution that would render a broken 'Open to fix'."""
    assert resolution_for("tier1_missing_Some Renamed Or Bogus Label") is None


# ── Cross-document source conflicts (client review #4) ───────────────────────
def test_scalar_source_conflict_is_typed_fixable():
    """A conflict on a plain writable scalar becomes a typed 'Open to fix' - the
    producer picks the correct value, applied like any other field resolution."""
    from services.arq_service import _canonical_key
    for field in ["num_employees", "prior_carrier"]:
        res = resolution_for(f"source_conflict_{field}")
        assert res and res["mode"] == "field"
        assert res["facts"] == [field]
        assert _canonical_key(field), f"{field} must be writable"
    # The carrier variant prefixes an extra "carrier_"; it is stripped back to the
    # real field WITHOUT mis-truncating a field legitimately named carrier_*.
    res = resolution_for("source_conflict_carrier_carrier_name")
    assert res["mode"] == "field" and res["facts"] == ["carrier_name"]


def test_nested_structured_source_conflict_gets_review_note_not_a_button():
    """A nested sub-field conflict (dotted key) can't be typed as a scalar and
    isn't held by the Data-Consistency picker, so it gets an honest 'none'-mode
    review note - never a dead typed-value button."""
    res = resolution_for("source_conflict_risk_transfer.additional_insured_names")
    assert res and res["mode"] == "none"
    assert res.get("note")                       # context-specific wording
    assert "facts" not in res                    # no fabricated input


# ── Typeable legacy stops (client review #5) ─────────────────────────────────
def test_typeable_legacy_stops_get_a_field_resolution_from_their_message():
    """evaluate_stops() emits uncoded strings, so make_issue derives the fix from
    the MESSAGE. Every mapped fact must be a writable canonical scalar."""
    from services.arq_service import _canonical_key
    cases = [
        ("GL coverage detected but no revenue or payroll found. Fix: ...",
         {"total_revenue", "total_payroll"}),
        ("Workers Comp detected but payroll is missing. Fix: ...",
         {"wc_payroll", "total_payroll"}),
        ("Physical damage coverage present but deductibles not specified.",
         {"auto_deductible_comp", "auto_deductible_collision"}),
        ("GL policy is claims-made - retro date is required.", {"retro_date"}),
    ]
    for msg, expect in cases:
        iss = make_issue("legacy_soft_0", "soft_warning", msg)
        res = iss.get("resolution")
        assert res and res["mode"] == "field", msg
        assert set(res["facts"]) == expect, msg
        for f in res["facts"]:
            assert _canonical_key(f), f"{f} not writable"


def test_non_typeable_legacy_stops_stay_worktracking_only():
    """A stop with no clean single-value fix (a class-code schedule with no live
    capture table, a symbol/structure gap) must NOT get a fabricated button."""
    for msg in [
        "GL coverage detected but no class codes found. Fix: ...",
        "Split liability structure selected but symbols undefined.",
        "Some entirely unrelated future stop with no mapping.",
    ]:
        assert make_issue("legacy_soft_0", "soft_warning", msg).get("resolution") is None


def test_schedule_mode_keys_are_live_schedules():
    """Every `schedule`-mode schedule_key must be a real capture schedule with
    live ACORD bindings (schedule_capture.SCHEDULE_DEFS)."""
    from services import schedule_capture

    bad = [
        (code, res["schedule_key"])
        for code, res in RESOLUTION_MAP.items()
        if res.get("mode") == "schedule" and schedule_capture.get_def(res["schedule_key"]) is None
    ]
    assert not bad, f"schedule-mode keys with no live SCHEDULE_DEFS entry: {bad}"


def test_resolution_for_returns_a_copy():
    """resolution_for must not hand out the shared template, or a caller mutating
    it would corrupt every future issue with that code."""
    a = resolution_for("location_count_mismatch")
    b = resolution_for("location_count_mismatch")
    assert a == b and a is not b
    a["mode"] = "mutated"
    assert resolution_for("location_count_mismatch")["mode"] == "schedule"


def test_uncoded_and_legacy_issues_have_no_resolution():
    """Field-level / legacy stops (no cross-form code) must NOT get a resolution;
    they keep their existing Resolve/Dismiss controls."""
    assert resolution_for("legacy_hard_0") is None
    assert resolution_for("ocr_low_confidence_applicant_name") is None
    assert resolution_for(None) is None
    assert make_issue("legacy_soft_3", "soft_warning", "x").get("resolution") is None


def test_resolution_flows_into_grouped_view_items_and_clusters():
    """The whole point: a cross-form issue's resolution must survive the trip
    through build_structured_from_sources -> build_grouped_view onto both the
    cluster and its items (what the SQS panel actually renders)."""
    from services.cross_form_validator import _issue

    cross = [_issue(
        "hard_stop", "location_count_mismatch",
        "ACORD 125 lists 4 location(s) but ACORD 140 has 2.",
        ["ACORD_125", "ACORD_140"],
    )]
    grouped = build_grouped_view(
        build_structured_from_sources(cross_issues=cross, include_advisories=True),
        ["ACORD 125 lists 4 location(s) but ACORD 140 has 2."],
        [],
    )
    cluster = grouped["hard_stops"][0]
    assert cluster["resolution"] == {"mode": "schedule", "schedule_key": "property_locations"}
    assert cluster["items"][0]["resolution"]["mode"] == "schedule"


def test_clear_canonical_from_forms_only_touches_producer_stamped_fields():
    """Reopen (SQS panel) must blank a field it stamped, leave an unrelated
    field on the same form alone, and leave a DIFFERENT form's
    extraction-sourced value for the same fact completely untouched - clearing
    an inline fix must never look like clearing real document data."""
    from services.arq_service import _clear_canonical_from_forms

    generated = {
        "ACORD_140": {
            "schema": {"period_of_restoration": {"tu": "x"}, "other_field": {"tu": "y"}},
            "field_state": {"period_of_restoration": "12 months", "other_field": "unrelated"},
            "confidence": {"period_of_restoration": "producer", "other_field": "extracted"},
            "client_filled_fields": ["period_of_restoration"],
        },
        "ACORD_101": {
            "schema": {"period_of_restoration": {"tu": "x"}},
            "field_state": {"period_of_restoration": "from extraction"},
            "confidence": {"period_of_restoration": "extracted"},
            "client_filled_fields": [],
        },
    }
    cleared = _clear_canonical_from_forms(generated, "period_of_restoration")

    assert cleared == ["ACORD_140"]
    fd140 = generated["ACORD_140"]
    assert fd140["field_state"]["period_of_restoration"] == ""
    assert "period_of_restoration" not in fd140["confidence"]
    assert fd140["field_state"]["other_field"] == "unrelated"
    assert fd140["confidence"]["other_field"] == "extracted"
    assert fd140["client_filled_fields"] == []

    fd101 = generated["ACORD_101"]
    assert fd101["field_state"]["period_of_restoration"] == "from extraction"
    assert fd101["confidence"]["period_of_restoration"] == "extracted"


def test_clear_canonical_from_forms_is_a_noop_when_nothing_stamped():
    """No producer/client_arq-sourced value anywhere -> nothing changes, no
    form is reported as touched."""
    from services.arq_service import _clear_canonical_from_forms

    generated = {
        "ACORD_140": {
            "schema": {"period_of_restoration": {"tu": "x"}},
            "field_state": {"period_of_restoration": "from extraction"},
            "confidence": {"period_of_restoration": "extracted"},
            "client_filled_fields": [],
        },
    }
    cleared = _clear_canonical_from_forms(generated, "period_of_restoration")
    assert cleared == []
    assert generated["ACORD_140"]["field_state"]["period_of_restoration"] == "from extraction"


def test_resolution_does_not_change_issue_id():
    """issue_id is keyed on message+forms only; attaching a resolution must not
    shift it, or a stored resolution-status would fail to re-attach after a
    re-run (see cross-issues-single-source / issue-diff-is-cluster-level)."""
    from services.cross_form_validator import _issue
    from services.issue_registry import issue_id_for

    iss = _issue("hard_stop", "location_count_mismatch", "msg X", ["ACORD_140", "ACORD_125"])
    assert iss["issue_id"] == issue_id_for("msg X", ["ACORD_140", "ACORD_125"])
    assert "resolution" in iss  # sanity: this code does carry one
