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


def test_non_typeable_legacy_stops_never_get_a_typed_input():
    """A stop with no clean single-value fix (a class-code schedule with no live
    capture table, a symbol/structure gap) must NEVER get a typed-value or
    schedule button that opens onto nothing.

    Since 2026-08-08 these rules carry an honest `none`-mode review NOTE instead
    of no resolution at all - the modal shows the reason it can't be typed here
    rather than looking like the fix feature skipped the row. The contract that
    matters is unchanged and asserted below: never `field`, never `schedule`."""
    for msg in [
        "GL coverage detected but no class codes found. Fix: ...",
        "Monopolistic WC state (ND/OH/WA/WY) requires the state fund.",
    ]:
        res = make_issue("legacy_soft_0", "soft_warning", msg).get("resolution")
        assert res and res["mode"] == "none", msg
        assert res.get("note"), f"{msg}: 'none' mode must explain why"
        assert "facts" not in res and "schedule_key" not in res, msg

    # "Split liability limits incomplete" LEFT this list on 2026-08-26 (V1 H1
    # audit). It was here because the rule read `bi_per_person` /
    # `bi_per_accident` / `pd_per_accident` - keys nothing has ever written -
    # and the note claimed those were "not writable canonical facts". The
    # writable facts are `auto_bi_per_person` / `auto_bi_per_accident` /
    # `auto_pd_per_accident` (schema, registry, stamped onto ACORD 127); both
    # engines now read them, so the honest resolution is to TYPE the three
    # limits. The old shape made the hard stop unsatisfiable on every
    # split-limit policy.
    res = make_issue("legacy_soft_0", "hard_stop",
                     "Split liability limits incomplete - all three components required.",
                     ).get("resolution")
    assert res and res["mode"] == "field"
    assert set(res["facts"]) == {"auto_bi_per_person", "auto_bi_per_accident",
                                 "auto_pd_per_accident"}

    # A message no rule matches still gets nothing at all - never a fabricated
    # resolution invented from thin air.
    assert make_issue(
        "legacy_soft_0", "soft_warning", "Some entirely unrelated future stop."
    ).get("resolution") is None


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


def test_resolution_for_copy_is_deep_enough_for_the_facts_list():
    """Reassigning a scalar key is isolated by any shallow copy, so the test
    above passed for months over a `facts` LIST that was still shared with the
    template - appending to it corrupted every future issue with that code.
    Mutate the list itself, which is what actually catches it."""
    a = resolution_for("minimum_viable_cope_missing")
    original = list(a["facts"])
    a["facts"].append("junk_fact")
    assert resolution_for("minimum_viable_cope_missing")["facts"] == original


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


# ── The follow-up note must never ask for a value already provided ──────────
# LIVE RUN S10 (2026-08-25): filling Building Value and BPP Value in one go
# produced "You can settle it here - fill in Occupancy Type / Construction Type
# / Property Bpp Value above and apply again" - naming a field just filled -
# and the re-apply then refused with "Enter at least one value." A prompt that
# asks for something already provided is a dead end.

_COPE_MSG = ("Property Minimum Viable COPE incomplete - missing: occupancy "
             "type, construction type")
_COPE_FACTS = ["occupancy_type", "construction_type",
               "property_building_value", "property_bpp_value"]


def _note(applied_field, facts):
    from routes.audit_routes import _trade_off_note
    return _trade_off_note({_COPE_MSG: _COPE_FACTS}, _COPE_FACTS,
                           applied_field, facts=facts)


def test_the_followup_note_names_only_still_missing_fields():
    note = _note("property_building_value",
                 {"property_building_value": "2400000",
                  "property_bpp_value": "310000"})
    assert "Occupancy Type" in note and "Construction Type" in note
    assert "Bpp" not in note, "must not ask for a value already provided"


def test_the_followup_note_stops_promising_a_fix_that_is_not_there():
    """When nothing on this screen is still missing, say so - do not tell the
    producer to 'fill in ... above' with nothing left to fill."""
    note = _note("property_building_value", {
        "property_building_value": "2400000", "property_bpp_value": "310000",
        "occupancy_type": "Office", "construction_type": "Frame - wood construction",
    })
    assert "settle it here" not in note
    assert "validation panel" in note


def test_an_absence_answer_counts_as_provided_in_the_followup_note():
    """A producer who answered "None" has ANSWERED (Brent 2026-08-24) - the
    note must not turn round and ask for it again."""
    note = _note("property_building_value", {
        "property_building_value": "2400000", "property_bpp_value": "310000",
        "occupancy_type": {"value": "", "value_state": "explicit_no"},
        "construction_type": {"value": "", "value_state": "explicit_no"},
    })
    assert "settle it here" not in note


def test_the_note_is_unchanged_when_no_session_facts_are_available():
    """Fail-safe: with no post-apply state the prior behaviour stands rather
    than silently dropping the guidance."""
    note = _note("property_building_value", None)
    assert "settle it here" in note


def test_no_note_at_all_when_nothing_was_introduced():
    from routes.audit_routes import _trade_off_note
    assert _trade_off_note({}, _COPE_FACTS, "property_building_value", facts={}) == ""
