"""test_answer_routing.py

Guard tests for the recommendation-card answer contract
(`services/answer_routing`).

Why this file exists
--------------------
The card used to decide for itself what a producer could do with a
recommendation - `answerable = !!rec.field` in AcordModal.jsx - while the server
decided with `arq_service._canonical_key`. Two layers, two definitions of one
predicate, and they disagreed:

  * `rec_narrative_components` declared `acord101_remarks`, a legacy READ-only
    alias. The card drew an input; the server answered "This item can't be
    answered directly. Attach a supporting document or dismiss it with a note."
    every single time, on every package with a narrative gap. Reported live
    2026-09-08.

  * `rec_auto_vin_schedule` and `rec_wc_class_codes` declare LIVE CAPTURE
    SCHEDULES. The card drew a single-line box; typing into it replaced the
    whole extracted table with one string and printed "Resolved". Nobody
    reported this one - it looks like a success.

The identical contract had existed on the ISSUE side since 2026-08-08
(`issue_registry.RESOLUTION_MAP` + the two guards in test_legacy_rules.py).
Recommendations were simply never brought under it. These tests are what stops
that happening again: they drive the REAL scorer across all 17 real schemas and
fail the build if any card it can emit offers a control the server would refuse
or a typed box over a table.
"""

import glob
import os

import pytest

from services import answer_routing as AR

_SCHEMA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "forms_schemas")


def _all_form_ids():
    ids = [os.path.basename(p).replace("_schema.json", "")
           for p in glob.glob(os.path.join(_SCHEMA_DIR, "*_schema.json"))]
    assert len(ids) >= 17, f"expected the 17 real ACORD schemas, found {len(ids)}"
    return sorted(ids)


# Every coverage flag on, so EVERY per-form checklist fires and no branch is
# skipped for want of an exposure. Empty facts, so every gap is open and every
# recommendation this scorer can build is actually built.
_ALL_COVERAGE_FLAGS = {
    "has_auto_coverage":    True,
    "has_workers_comp":     True,
    "has_property_coverage": True,
    "has_umbrella":         True,
    "has_gl_coverage":      True,
    "has_inland_marine":    True,
}


def _harvest_recommendations():
    """Every recommendation the per-form scorer can emit, across all 17 forms."""
    from services.sqs_service import calculate_sqs

    form_ids = _all_form_ids()
    out = []
    for fid in form_ids:
        res = calculate_sqs({}, dict(_ALL_COVERAGE_FLAGS), {}, {}, form_ids,
                            [], [], 0, form_id=fid)
        for rec in res.get("recommendations") or []:
            if isinstance(rec, dict):
                out.append((fid, rec))
    # A harvest that silently came back empty would make every test below pass
    # vacuously - the exact trap improving-ll.md C25 documents.
    assert len(out) >= 30, f"recommendation harvest looks empty ({len(out)})"
    return out


@pytest.fixture(scope="module")
def harvested():
    return _harvest_recommendations()


# ── 1. The derived tables are real ───────────────────────────────────────────

def test_derived_tables_are_not_empty():
    """Every rule in this module reads a declaration elsewhere. If any of those
    reads silently returns nothing, the whole contract passes vacuously."""
    assert AR._schedule_keys(), "no live schedules resolved"
    assert AR._narrative_keys(), "no narrative facts resolved"
    assert AR.record_list_facts(), "no row-shaped facts resolved from the schema"


def test_record_list_shape_matches_the_extraction_schema():
    """`[{...}]` in the schema is a table; `[string]` is a typeable list.

    Both halves are asserted: a rule that only ever says "table" would also
    pass a one-sided check while breaking every scalar list fact.
    """
    rows = AR.record_list_facts()
    for fact in ("auto_vin_schedule", "wc_class_codes", "loss_history",
                 "inland_marine_items", "gl_class_codes_by_location"):
        assert fact in rows, f"{fact} is declared [{{...}}] and must read as a table"
    for fact in ("lines_of_business", "locations", "additional_named_insureds",
                 "contractor_high_hazard_ops"):
        assert fact not in rows, f"{fact} is declared [string] and must stay typeable"


# ── 2. Every card the scorer can draw is coherent ────────────────────────────

def test_every_recommendation_carries_a_valid_mode(harvested):
    bad = [(fid, r.get("rec_id"), r.get("answer_mode"))
           for fid, r in harvested
           if r.get("answer_mode") not in AR.VALID_MODES]
    assert not bad, f"recommendations with no/invalid answer_mode: {bad}"


def test_field_mode_recommendations_are_writable(harvested):
    """A `field`-mode card offers a typed box. If the producer-answer door
    cannot write that fact, the box is refused on every submission - the
    client's reported defect."""
    from services.arq_service import _canonical_key

    bad = [(fid, r.get("rec_id"), r.get("field"))
           for fid, r in harvested
           if r.get("answer_mode") == AR.MODE_FIELD and not _canonical_key(r.get("field"))]
    assert not bad, f"field-mode recommendations that are NOT writable: {bad}"


def test_field_mode_recommendations_are_not_schedule_backed(harvested):
    """A fact with a live capture table must open the TABLE, never a text box -
    a typed scalar there replaces every extracted row. This is the same rule
    `test_legacy_rules.test_field_mode_facts_are_not_schedule_backed` has
    enforced on the issue side since 2026-08-08."""
    sched = AR._schedule_keys()
    bad = [(fid, r.get("rec_id"), r.get("field"))
           for fid, r in harvested
           if r.get("answer_mode") == AR.MODE_FIELD and r.get("field") in sched]
    assert not bad, f"schedule-backed facts offered as a typed input: {bad}"


def test_schedule_mode_recommendations_name_a_live_schedule(harvested):
    sched = AR._schedule_keys()
    rows = [(fid, r) for fid, r in harvested if r.get("answer_mode") == AR.MODE_SCHEDULE]
    assert rows, "no schedule-mode recommendation harvested - guard would be vacuous"
    bad = [(fid, r.get("rec_id"), r.get("schedule_key"))
           for fid, r in rows if r.get("schedule_key") not in sched]
    assert not bad, f"schedule-mode recommendations with no live schedule: {bad}"


def test_narrative_mode_recommendations_name_a_prose_fact(harvested):
    narr = AR._narrative_keys()
    rows = [(fid, r) for fid, r in harvested if r.get("answer_mode") == AR.MODE_NARRATIVE]
    assert rows, "no narrative-mode recommendation harvested - guard would be vacuous"
    bad = [(fid, r.get("rec_id"), r.get("field"))
           for fid, r in rows if r.get("field") not in narr]
    assert not bad, f"narrative-mode recommendations on a non-prose fact: {bad}"


def test_none_mode_recommendations_explain_themselves(harvested):
    """A card with no input must say why, so it never reads as though the fix
    feature skipped it (the same requirement `_r_review` carries on the issue
    side)."""
    bad = [(fid, r.get("rec_id"))
           for fid, r in harvested
           if r.get("answer_mode") == AR.MODE_NONE and not (r.get("answer_note") or "").strip()]
    assert not bad, f"none-mode recommendations with no explanation: {bad}"


def test_the_client_reported_card_is_answerable(harvested):
    """The literal reported case: the Narrative Quality card offered a box and
    the server refused it. It must now route to the narrative fact, which the
    producer-answer door CAN write. Must never fail."""
    from services.arq_service import _canonical_key

    recs = [r for _f, r in harvested if r.get("rec_id") == "rec_narrative_components"]
    assert recs, "rec_narrative_components was not emitted - fixture no longer covers it"
    rec = recs[0]
    assert rec["answer_mode"] == AR.MODE_NARRATIVE
    assert rec["field"] == "additional_remarks_text"
    assert _canonical_key(rec["field"]), "the narrative card's fact must be writable"
    assert rec["field"] != "acord101_remarks", "the read-only alias is back"


def test_the_unreported_destructive_cards_open_a_table(harvested):
    """`rec_auto_vin_schedule` / `rec_wc_class_codes` used to accept a typed
    scalar that wiped the schedule. Must never fail."""
    by_id = {r.get("rec_id"): r for _f, r in harvested}
    for rec_id, key in (("rec_auto_vin_schedule", "auto_vin_schedule"),
                        ("rec_wc_class_codes",    "wc_class_codes")):
        rec = by_id.get(rec_id)
        assert rec, f"{rec_id} was not emitted - fixture no longer covers it"
        assert rec["answer_mode"] == AR.MODE_SCHEDULE, f"{rec_id} is typeable again"
        assert rec["schedule_key"] == key


# ── 3. The router itself ─────────────────────────────────────────────────────

@pytest.mark.parametrize("field,expected", [
    (None,                                     AR.MODE_NONE),
    ("",                                       AR.MODE_NONE),
    ("   ",                                    AR.MODE_NONE),
    ("acord101_remarks",                       AR.MODE_NONE),   # read-only alias
    ("not_a_fact_at_all_xyz",                  AR.MODE_NONE),
    ("_internal_sub_part",                     AR.MODE_NONE),
    ("additional_remarks_text",                AR.MODE_NARRATIVE),
    ("operations_description",                 AR.MODE_NARRATIVE),
    ("auto_vin_schedule",                      AR.MODE_SCHEDULE),
    ("wc_class_codes",                         AR.MODE_SCHEDULE),
    ("loss_history",                           AR.MODE_SCHEDULE),
    ("schedule::auto_vin_schedule",            AR.MODE_SCHEDULE),
    ("schedule::not_a_schedule",               AR.MODE_NONE),
    ("umbrella_limit",                         AR.MODE_FIELD),
    ("lines_of_business",                      AR.MODE_FIELD),
    ("loss_history_no_prior_losses_indicator", AR.MODE_FIELD),
])
def test_answer_mode_cases(field, expected):
    assert AR.answer_mode(field)["mode"] == expected


def test_a_schedule_never_degrades_to_a_text_box_even_when_empty():
    """Order matters: the schedule test runs before anything that looks at the
    current value, so an empty fleet still opens the table."""
    assert AR.answer_mode("auto_vin_schedule", {})["mode"] == AR.MODE_SCHEDULE
    assert AR.answer_mode("auto_vin_schedule", {"auto_vin_schedule": []})["mode"] == AR.MODE_SCHEDULE


# ── 4. holds_rows: narrow by construction ────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    (None,                                   False),
    ("",                                     False),
    ("a typed sentence",                     False),
    ([],                                     False),
    (["GL", "Auto"],                         False),   # list of STRINGS - typeable
    ([{"vin": "X"}],                         True),
    ([{"vin": "X"}, {"vin": "Y"}],           True),
    ({"value": [{"vin": "X"}]},              True),    # envelope
    ({"value": ["GL"]},                      False),   # envelope, scalar list
    ({"value": None},                        False),
    ({"value": []},                          False),
    ({"not_an_envelope": 1},                 False),
])
def test_holds_rows(value, expected):
    assert AR.holds_rows(value) is expected


def test_can_write_scalar_protects_only_populated_tables():
    # Empty table: the typed box is how these gaps have always been closed.
    assert AR.can_write_scalar("gl_class_codes_by_location", {}) is True
    assert AR.can_write_scalar("gl_class_codes_by_location",
                               {"gl_class_codes_by_location": []}) is True
    # Populated table with no declared reader: refused.
    assert AR.can_write_scalar(
        "gl_class_codes_by_location",
        {"gl_class_codes_by_location": [{"location": "A", "codes": ["91580"]}]}) is False
    # A list of plain strings is NOT a table - the tier-1 "lines of business"
    # fix has always written one and must keep working.
    assert AR.can_write_scalar("lines_of_business",
                               {"lines_of_business": ["GL", "Auto"]}) is True
    # `auto_covered_symbols` is row-shaped but declares a validator, because
    # `auto_symbols.parse_symbols` really does read producer free text. Four
    # cross-form resolutions depend on that staying true.
    assert AR.accepts_typed_input("auto_covered_symbols") is True
    assert AR.can_write_scalar(
        "auto_covered_symbols",
        {"auto_covered_symbols": [{"coverage": "Liability", "symbols": [1]}]}) is True


def test_auto_covered_symbols_is_the_only_typed_row_fact():
    """Not a claim about that fact - a claim about the RULE. If a second
    row-shaped fact gains a validator, somebody has decided its typed value can
    be read, and this test is where they say so out loud."""
    typed_rows = sorted(f for f in AR.record_list_facts() if AR.accepts_typed_input(f))
    assert typed_rows == ["auto_covered_symbols"], (
        f"row-shaped facts declaring a typed-input validator changed: {typed_rows}"
    )


# ── 5. The write door actually refuses ───────────────────────────────────────

def test_the_write_door_refuses_a_scalar_over_a_table(monkeypatch):
    """Drives the REAL `apply_producer_answer_to_session`. A guard that only
    exists in `answer_routing` protects the callers that remember to ask; this
    proves the door itself holds, which is what covers the resolution modal and
    the held-client-answer review too."""
    import asyncio

    import repositories.session_repository as sr
    from services import arq_service

    store = {
        "facts": {"auto_vin_schedule": [{"vin": "4S4BRCGC9C3217772", "make": "Subaru"}]},
        "flags": {},
        "generated_forms": {},
    }

    async def _get(_sid):
        return {k: (dict(v) if isinstance(v, dict) else v) for k, v in store.items()}

    async def _upd(_sid, payload, delete_facts=None):
        store.update(payload or {})
        return True

    monkeypatch.setattr(sr, "get_processing_session", _get)
    monkeypatch.setattr(sr, "upd_processing_session", _upd)

    ok, _ = asyncio.run(arq_service.apply_producer_answer_to_session(
        "s", "auto_vin_schedule", "2019 Ford Transit"))
    assert ok is False, "a typed scalar was allowed to replace a vehicle table"
    assert store["facts"]["auto_vin_schedule"] == [
        {"vin": "4S4BRCGC9C3217772", "make": "Subaru"}
    ], "the extracted fleet was destroyed"


def test_the_write_door_still_writes_an_ordinary_fact(monkeypatch):
    """The other direction. A guard that refuses everything would pass the test
    above and break the product."""
    import asyncio

    import repositories.session_repository as sr
    from services import arq_service

    store = {"facts": {}, "flags": {}, "generated_forms": {}}

    async def _get(_sid):
        return {k: (dict(v) if isinstance(v, dict) else v) for k, v in store.items()}

    async def _upd(_sid, payload, delete_facts=None):
        store.update(payload or {})
        return True

    monkeypatch.setattr(sr, "get_processing_session", _get)
    monkeypatch.setattr(sr, "upd_processing_session", _upd)

    ok, _ = asyncio.run(arq_service.apply_producer_answer_to_session(
        "s", "umbrella_limit", "$5,000,000"))
    assert ok is True
    assert store["facts"].get("umbrella_limit")


# ── 6. The narrative door appends, never overwrites ──────────────────────────

@pytest.mark.parametrize("existing,addition,expected", [
    ("",                          "first",  "first"),
    (None,                        "first",  "first"),
    ({"value": "first"},          "second", "first\nsecond"),
    ({"value": "first\nsecond"},  "second", "first\nsecond"),   # idempotent
    ({"value": "first"},          "   ",    "first"),
    ("first",                     "second", "first\nsecond"),
])
def test_compose_narrative_answer(existing, addition, expected):
    from services.arq_service import compose_narrative_answer
    assert compose_narrative_answer(existing, addition) == expected


# ── 7. The pre-form screen: a stop never arrives without its fix ─────────────
#
# The Review screen draws Hard Stops and Warnings from `grouped_issues`, where
# every row carries its rule code and therefore its "Open to fix" control. Given
# only the raw `hard_stops` / `soft_stops` arrays it falls back to printing the
# sentences as dead text - no fix, no Resolve, no Dismiss - on blockers holding
# the score at 60. `reopen_issue` did exactly that (found 2026-09-08): it
# refreshed the arrays and left the cards behind.
#
# Same defect class as the recommendation cards above, one screen over: the
# display layer inferring what it can offer instead of being told.

def _panel_payload_dicts():
    """Every dict literal in audit_routes that refreshes the SQS panel.

    Identified by `updated_forms` - the key `_applyCrossIssuePanelUpdate` reads
    - rather than by endpoint name, so a new endpoint is covered the day it is
    written.
    """
    import ast
    import os

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "routes", "audit_routes.py")
    tree = ast.parse(open(path, encoding="utf-8").read())
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Dict):
            continue
        keys = {k.value for k in n.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        # Only payloads that actually SHIP stops. A dismiss/answer reply that
        # refreshes scores without touching the arrays leaves the banners alone
        # and is correctly out of scope - `_applyCrossIssuePanelUpdate` guards
        # each array with its own `Array.isArray` check.
        if "updated_forms" in keys and (
                {"hard_stops", "soft_stops"} & keys
                or _spreads_form_selection_view(n)):
            out.append((n, keys))
    return out


def _spreads_form_selection_view(node) -> bool:
    """True when the dict does `**_form_selection_view(...)` - a `None` key in
    the AST, whose value is the call."""
    import ast

    for k, v in zip(node.keys, node.values):
        if k is None and isinstance(v, ast.Call):
            fn = v.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if name == "_form_selection_view":
                return True
    return False


def test_every_panel_refresh_ships_the_grouped_view():
    """A response that hands the Review screen fresh stops must hand it the
    grouped view too, or the screen degrades to dead text."""
    payloads = _panel_payload_dicts()
    assert payloads, "no panel-refresh payloads found - this guard is vacuous"
    bad = []
    for node, keys in payloads:
        if "grouped_issues" in keys or _spreads_form_selection_view(node):
            continue
        bad.append((node.lineno, sorted(keys & {"hard_stops", "soft_stops", "cross_issues"})))
    assert not bad, (
        "panel-refresh payloads carrying stops with NO grouped_issues "
        f"(line, keys): {bad}"
    )


def test_form_selection_view_returns_the_whole_banner_payload():
    """The shared helper is what makes the guard above satisfiable. It must
    return every key the Review banners read, and a REAL grouped view."""
    from routes.audit_routes import _form_selection_view

    sess = {
        "hard_stops": ["Minimum Viable COPE incomplete"],
        "soft_stops": ["Property valuation method not specified"],
        "structured_issues": [],
        "flags": {},
    }
    view = _form_selection_view(sess, [])
    for key in ("hard_stops", "soft_stops", "grouped_issues",
                "can_proceed_with_warning", "warning_stops"):
        assert key in view, f"{key} missing from the form-selection view"
    grouped = view["grouped_issues"]
    assert grouped and grouped.get("hard_stops"), "grouped view came back empty"
    # And the row it produced is actionable, not dead text.
    item = grouped["hard_stops"][0]["items"][0]
    assert (item.get("resolution") or {}).get("mode") == "field", item


# ── 8. A 60-cap blocker is clickable, not just legible ──────────────────────

def test_cap_hard_stops_ship_an_actionable_row():
    """`cap_hard_stops` made the cap LEGIBLE in 2026-08-31; it stayed a dead end
    until 2026-09-08. Every sentence must arrive with the rule code and
    resolution the panel needs to draw "Open to fix"."""
    from services.sqs_service import calculate_sqs

    scenarios = [
        # Property gate: BI limit with no period of restoration.
        ("ACORD_140",
         {"applicant_name": "X", "business_income_limit": "$450,000",
          "property_building_value": "$3,750,000", "occupancy_type": "Office",
          "construction_type": "Joisted Masonry", "locations": ["1 A St"]},
         {"has_property_coverage": True}),
        # Property gate: minimum viable COPE.
        ("ACORD_140", {"applicant_name": "X"}, {"has_property_coverage": True}),
        # Umbrella gate: no underlying at all.
        ("ACORD_131", {"applicant_name": "X", "umbrella_limit": "$5,000,000"},
         {"has_umbrella": True}),
        # Umbrella gate: underlying present, supporting detail incomplete.
        ("ACORD_131",
         {"applicant_name": "X", "gl_each_occurrence": "$300,000",
          "gl_aggregate": "$600,000", "auto_liability_limit": "$300,000"},
         {"has_umbrella": True, "has_gl_coverage": True, "has_auto_coverage": True}),
    ]
    seen = 0
    for fid, facts, flags in scenarios:
        res = calculate_sqs(facts, flags, {}, {}, [fid], [], [], 0, form_id=fid)
        stops = res.get("cap_hard_stops") or []
        items = res.get("cap_hard_stop_items") or []
        assert len(items) == len(stops), f"{fid}: items/stops mismatch"
        for msg in stops:
            seen += 1
            row = next((i for i in items if i.get("message") == msg), None)
            assert row, f"{fid}: no row for {msg!r}"
            assert row.get("code"), f"{fid}: {msg!r} classified to no rule"
            mode = (row.get("resolution") or {}).get("mode")
            assert mode in ("field", "schedule", "narrative"), \
                f"{fid}: {msg!r} has no actionable fix (mode={mode})"
    assert seen >= 4, f"only {seen} cap sentences exercised - guard is thin"


# ── 9. A cap sentence from EITHER engine is clickable ───────────────────────

def test_cap_rows_inherit_a_coded_cross_form_identity():
    """A cap reason is often a CROSS-FORM message, not a legacy one.

    `classify_legacy` has no row for those wordings and never will - they are not
    legacy messages. A live run (2026-09-08) showed the result: the package
    HARD STOPS block printed the cross-form business-income sentence as bare
    text with nothing to click, while the very same problem carried a working
    "Open to fix" a few inches below in Cross-Form Validation.
    """
    from services.sqs_service import _cap_stop_items

    msg = ("Business Income limit is specified but Period of Restoration is "
           "missing. Both are required when BI coverage is requested.")
    coded = [{"code": "bi_missing_period_of_restoration", "message": msg,
              "type": "hard_stop", "forms": ["ACORD_140"]}]

    # Without the coded issue there is nothing to inherit - honest, and the
    # sentence still survives.
    bare = _cap_stop_items([msg])[0]
    assert bare["message"] == msg
    assert bare["code"] is None

    row = _cap_stop_items([msg], coded_issues=coded)[0]
    assert row["code"] == "bi_missing_period_of_restoration"
    assert (row["resolution"] or {}).get("mode") == "field"
    assert "period_of_restoration" in (row["resolution"] or {}).get("facts", [])
    assert row["forms"] == ["ACORD_140"]


def test_package_cap_block_ships_clickable_rows():
    """The package block falls back to `cap_reason` when `cap_hard_stops` is
    empty - the COMMON case, since a cap whose reason is already a hard stop
    deliberately produces no extra entry. That fallback must still be clickable."""
    from services.sqs_service import calculate_package_sqs

    msg = ("Business Income limit is specified but Period of Restoration is "
           "missing. Both are required when BI coverage is requested.")
    cross = [{"code": "bi_missing_period_of_restoration", "message": msg,
              "type": "hard_stop", "forms": ["ACORD_140"]}]
    pkg = calculate_package_sqs(
        {"applicant_name": "X", "business_income_limit": "$450,000",
         "property_building_value": "$3,750,000", "occupancy_type": "Shop",
         "construction_type": "Non-Combustible", "locations": ["1 A St"]},
        {"has_property_coverage": True, "has_gl_coverage": True},
        [], cross, [msg], [], {})

    assert pkg.get("cap_applied") == 60
    assert not pkg.get("cap_hard_stops"), "fixture no longer exercises the fallback"
    items = pkg.get("cap_hard_stop_items") or []
    assert items, "the package cap has no clickable row"
    assert items[0]["code"] == "bi_missing_period_of_restoration"
    assert (items[0]["resolution"] or {}).get("mode") == "field"


# ── 10. The umbrella pillar reaches 0 two ways - never claim only one ───────

def test_umbrella_zero_never_claims_missing_underlying_when_they_are_stated():
    """The 60-cap gate was corrected for this on 2026-08-31 via the shared
    `_umbrella_has_underlying` door. Its sibling - the Key Issues sentence and
    the "Provide underlying limits" card - was left behind, so a LIVE RUN showed
    both on one screen for a package stating $300,000 GL and $300,000 auto CSL.
    Worse, the card asked for values already on file while the actually-missing
    umbrella limit went unasked."""
    from services.sqs_service import calculate_sqs

    stated = {"applicant_name": "X", "gl_each_occurrence": "$300,000",
              "gl_aggregate": "$600,000", "auto_liability_limit": "$300,000",
              "umbrella_sir": "$10,000"}
    flags = {"has_umbrella": True, "has_gl_coverage": True, "has_auto_coverage": True}
    res = calculate_sqs(stated, flags, {}, {}, ["ACORD_131"], [], [], 0,
                        form_id="ACORD_131")
    assert res["breakdown"]["umbrella_limit_adequacy"] == 0, "fixture no longer hits 0"

    issues = res.get("issues") or []
    assert not any("no underlying GL/Auto limits" in i for i in issues), (
        f"false claim on a package that states both underlying limits: {issues}")

    recs = {r.get("rec_id"): r for r in (res.get("recommendations") or [])
            if isinstance(r, dict)}
    assert "rec_underlying_limits" not in recs, \
        "asked for underlying limits that are already on file"
    card = recs.get("rec_umbrella_supporting_detail")
    assert card, "no card asks for the fact that IS missing"
    assert card["field"] == "umbrella_limit"
    assert card["answer_mode"] == "field"

    # THE OTHER DIRECTION. A guard that never says "no underlying" would pass
    # the assertions above and delete a true warning.
    none_stated = calculate_sqs({"applicant_name": "X", "umbrella_limit": "$5,000,000"},
                                {"has_umbrella": True}, {}, {}, ["ACORD_131"],
                                [], [], 0, form_id="ACORD_131")
    assert none_stated["breakdown"]["umbrella_limit_adequacy"] == 0
    assert any("no underlying GL/Auto limits" in i
               for i in (none_stated.get("issues") or [])), \
        "the genuine no-underlying case lost its warning"
    assert "rec_underlying_limits" in {
        r.get("rec_id") for r in (none_stated.get("recommendations") or [])
        if isinstance(r, dict)}


def test_cap_rows_survive_the_affects_suffix():
    """`cross_form_validator` appends "(Affects: ACORD 140. Fix: ...)" to some
    messages AFTER the issue itself was captured, so the stop list carries the
    long string while the coded issue carries the short one.

    Byte-exact matching found nothing and the red box lost its "Open to fix" -
    reported live 2026-09-08. `issue_registry._present_in` has used a prefix
    rule for this since it was written; this follows it rather than inventing a
    second one."""
    from services.sqs_service import _cap_stop_items

    short = ("Business Income limit is specified but Period of Restoration is "
             "missing. Both are required when BI coverage is requested.")
    long = short + (" (Affects: ACORD 140. Fix: Review the coverage/limit "
                    "details for the affected form(s).)")
    coded = [{"code": "bi_missing_period_of_restoration", "message": short,
              "forms": ["ACORD_140"]}]

    for label, msg in (("exact", short), ("suffixed", long)):
        row = _cap_stop_items([msg], coded_issues=coded)[0]
        assert row["code"] == "bi_missing_period_of_restoration", label
        assert (row["resolution"] or {}).get("mode") == "field", label

    # A DIFFERENT sentence must not borrow this row's identity just because the
    # match loosened - a prefix rule that matches everything is worse than none.
    other = _cap_stop_items(["Minimum Viable COPE incomplete"], coded_issues=coded)[0]
    assert other["code"] != "bi_missing_period_of_restoration"
