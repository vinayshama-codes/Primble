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
