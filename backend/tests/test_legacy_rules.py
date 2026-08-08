"""test_legacy_rules.py

Guard tests for the LEGACY field-level stop engine's rule table
(issue_registry._LEGACY_MESSAGE_RULES).

Why this file exists
--------------------
`sqs_service.evaluate_stops()` / `utils.validators.run_field_validations()` /
`sqs_service.validate_effective_date_window()` / `sqs_service.validate_naics_code()`
return plain STRINGS with no rule code on the wire. Every one of them used to be
tagged at the call site with a throwaway index code (`legacy_soft_0`,
`legacy_soft_1`, ...), so `resolution_for()` had nothing to look up and each one
rendered a Resolve/Dismiss row that opened onto nothing - the reported client
defect ("Carrier-Grade COPE incomplete ... I could not resolve this because
there is nothing that pops up to fill in the missing info").

`_LEGACY_MESSAGE_RULES` now carries a real code and a fix mode per rule. That
table is matched by SUBSTRING, first match wins, which makes two things silently
breakable:

  1. a NEW rule added to the engine with no row here falls into the default
     "Other validations" bucket with no code and no fix - i.e. exactly the bug
     above, reintroduced quietly (this is not hypothetical: the NAICS warnings
     had been doing precisely that until these tests were written);
  2. a row whose phrase is a substring of another rule's message SHADOWS it, so
     a producer clicks one warning and is asked for an unrelated field.

These tests fail the build on both.
"""

import ast
import inspect
import textwrap

import pytest

from services.issue_registry import (
    _LEGACY_MESSAGE_RULES,
    _LEGACY_CODE_RESOLUTIONS,
    _RECOMPUTED_CODE_PREFIXES,
    CLUSTER_MAP,
    RESOLUTION_MAP,
    DEFAULT_CLUSTER,
    classify_legacy,
    make_issue,
    resolution_for,
)

_VALID_MODES = {"field", "schedule", "narrative", "none"}
_LEGACY_PREFIX = "legacy_"


# ── Message harvesting: what the engine can ACTUALLY emit ────────────────────

def _literal_prefix(node) -> str | None:
    """The constant leading text of an append() argument, or None.

    Handles both a plain string and an f-string / concatenation whose first
    piece is a literal (e.g. f"Revenue-to-payroll ratio is {x:.1f}x - ..."),
    which is the part the rule table matches on.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and node.values:
        first = node.values[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _literal_prefix(node.left)
    return None


def _harvest_static_messages() -> list[str]:
    """Every message literal appended to hard/soft inside evaluate_stops().

    Static rather than dynamic because evaluate_stops' branches are mutually
    exclusive - no single facts/flags dict can trip all of them - so driving it
    would silently under-cover. The AST sees every branch.
    """
    import services.sqs_service as sqs

    src = textwrap.dedent(inspect.getsource(sqs.evaluate_stops))
    tree = ast.parse(src)
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "append":
            continue
        target = node.func.value
        if not (isinstance(target, ast.Name) and target.id in ("hard", "soft")):
            continue
        if not node.args:
            continue
        text = _literal_prefix(node.args[0])
        if text and len(text.strip()) > 10:
            out.append(text)
    return out


def _harvest_field_validation_messages() -> list[str]:
    """Every message run_field_validations() produces, by actually running it
    with a deliberately invalid value in every field it inspects."""
    from utils.validators import run_field_validations

    bad_facts = {
        "mailing_address": "",
        "contact_phone": "not-a-phone",
        "contact_email": "not-an-email",
        "fein": "nope",
        "effective_date": "not-a-date",
        "expiration_date": "not-a-date",
        "percent_subcontracted": "999",
        "coinsurance_percentage": "999",
        "building_ITV_percentage": "999",
        "total_revenue": "abc",
        "total_payroll": "abc",
        "wc_payroll": "abc",
        "property_building_value": "abc",
        "property_bpp_value": "abc",
        "umbrella_limit": "abc",
        "gl_each_occurrence": "abc",
        "gl_aggregate": "abc",
        "auto_liability_limit": "abc",
        "business_income_limit": "abc",
    }
    hard, soft = run_field_validations(bad_facts)
    return list(hard) + list(soft)


def _harvest_standalone_validator_messages() -> list[str]:
    """The two validators sqs_service calls directly from evaluate_stops but
    which live outside run_field_validations - a THIRD and FOURTH message
    source. The NAICS pair had no rule row at all until 2026-08-08."""
    from services.sqs_service import validate_effective_date_window, validate_naics_code

    out: list[str] = []
    for facts in (
        {"effective_date": "01/01/2019"},               # far in the past
        {"effective_date": "01/01/2099"},               # far in the future
    ):
        res = validate_effective_date_window(facts)
        if res:
            out.append(res[1])
    for facts in (
        {"naics_code": "12345678"},                     # wrong length
        {"naics_code": "abcdef"},                       # not digits
        {"naics_code": "0000"},                         # invalid sector prefix
    ):
        res = validate_naics_code(facts)
        if res:
            out.append(res[1])
    return out


def _all_emittable_messages() -> list[str]:
    return (
        _harvest_static_messages()
        + _harvest_field_validation_messages()
        + _harvest_standalone_validator_messages()
    )


# ── 1. Coverage: nothing the engine emits may fall through ───────────────────

def test_harvesting_actually_found_messages():
    """Sanity-check the harvester itself. If a refactor renames the local
    accumulators or moves these functions, the coverage test below would pass
    vacuously on an empty list - which is precisely the trap the ORIGINAL
    coverage test in this codebase fell into (see C25 in CLAUDE.md)."""
    assert len(_harvest_static_messages()) >= 20
    assert len(_harvest_field_validation_messages()) >= 10
    assert len(_harvest_standalone_validator_messages()) >= 2


@pytest.mark.parametrize("message", _all_emittable_messages())
def test_every_emittable_message_matches_a_rule_row(message):
    """No message may fall through to the default bucket. A fall-through means
    no code, therefore no inline fix, therefore the reported client defect."""
    code, cluster, _tier = classify_legacy(message, "soft_warning")
    assert code, (
        f"no _LEGACY_MESSAGE_RULES row matches:\n  {message!r}\n"
        "Add a row (phrase, cluster, tier, code, resolution) for it."
    )
    assert cluster != DEFAULT_CLUSTER, f"{message!r} landed in the default bucket"


# ── 2. Ordering: a row must not be shadowed by an earlier one ────────────────

def test_no_rule_row_is_shadowed_by_an_earlier_row():
    """The table is first-match-wins, so a short phrase placed above a longer
    one silently steals its messages - the producer would click one warning and
    be asked for a different rule's field. Each row's own phrase must resolve
    to that row's code."""
    shadowed = []
    for phrase, _cluster, _tier, code, _res in _LEGACY_MESSAGE_RULES:
        matched, _c, _t = classify_legacy(phrase, "soft_warning")
        if matched != code:
            shadowed.append((phrase, code, matched))
    assert not shadowed, (
        "rows shadowed by an earlier row (phrase, own code, code it actually hit): "
        f"{shadowed}"
    )


def test_real_messages_route_to_their_intended_rule():
    """Spot-check the substring collisions most likely to bite: short format
    phrases ("WC payroll", "Total payroll", "Building value") sitting near
    longer domain messages that contain similar words."""
    cases = [
        # The client's exact reported string.
        ("Carrier-Grade COPE incomplete - SQS capped at 85. Missing: year built, "
         "roof year, sprinkler system, fire protection class",
         "legacy_carrier_grade_cope"),
        ("Workers Comp detected but payroll is missing", "legacy_wc_payroll_missing"),
        ("WC payroll must be a valid monetary amount", "legacy_wc_payroll_format"),
        ("Total payroll must be a valid monetary amount", "legacy_total_payroll_format"),
        ("Multi-state WC - payroll breakdown by state and class code required",
         "legacy_wc_multi_state_no_breakdown"),
        ("Building value must be a valid monetary amount", "legacy_building_value_format"),
        ("Building ITV percentage must be between 0 and 100",
         "legacy_building_itv_format"),
        ("Business income limit must be a valid monetary amount",
         "legacy_business_income_limit_format"),
        ("Business Income coverage detected - BI limit and Period of Restoration "
         "should be provided", "legacy_bi_no_limit"),
        ("Property Minimum Viable COPE incomplete - missing: occupancy type",
         "legacy_minimum_viable_cope"),
    ]
    for message, expected in cases:
        code, _c, _t = classify_legacy(message, "soft_warning")
        assert code == expected, f"{message!r} -> {code!r}, expected {expected!r}"


# ── 3. Table integrity ───────────────────────────────────────────────────────

def test_rows_are_well_formed_and_codes_unique():
    seen = set()
    for row in _LEGACY_MESSAGE_RULES:
        assert len(row) == 5, f"row must be (phrase, cluster, tier, code, resolution): {row}"
        phrase, cluster, tier, code, res = row
        assert phrase and isinstance(phrase, str)
        assert cluster and isinstance(cluster, str)
        assert tier in ("required", "recommended", "binder_followup"), f"{code}: bad tier {tier!r}"
        assert code and code.startswith(_LEGACY_PREFIX), f"{code!r} must start with {_LEGACY_PREFIX!r}"
        assert code not in seen, f"duplicate legacy code: {code}"
        seen.add(code)
        assert isinstance(res, dict) and res.get("mode") in _VALID_MODES, f"{code}: bad resolution"


def test_legacy_codes_never_collide_with_the_cross_form_namespace():
    """A legacy code that equals a cross-form code would defeat
    _LEGACY_SUPERSEDED_BY_CODE's duplicate suppression: the legacy row would
    look like its own coded twin, protect itself from suppression, and both
    near-identical bullets would render."""
    collisions = [c for c in _LEGACY_CODE_RESOLUTIONS if c in CLUSTER_MAP or c in RESOLUTION_MAP]
    assert not collisions, f"legacy codes colliding with cross-form codes: {collisions}"

    leaked = [c for c in list(CLUSTER_MAP) + list(RESOLUTION_MAP) if c.startswith(_LEGACY_PREFIX)]
    assert not leaked, f"cross-form codes must not use the '{_LEGACY_PREFIX}' namespace: {leaked}"


def test_recomputed_prefix_covers_every_legacy_code():
    """replace_recomputed_issues() swaps out exactly the issues a recalculation
    regenerates, keyed by code prefix. A legacy code it does NOT match would be
    preserved forever, so a stop the client already fixed keeps rendering as an
    open blocker."""
    missed = [c for c in _LEGACY_CODE_RESOLUTIONS if not c.startswith(_RECOMPUTED_CODE_PREFIXES)]
    assert not missed, f"legacy codes not matched by _RECOMPUTED_CODE_PREFIXES: {missed}"
    # The pre-2026-08-08 throwaway codes must still match, or sessions persisted
    # before the rename stop recalculating correctly.
    assert "legacy_hard_0".startswith(_RECOMPUTED_CODE_PREFIXES)
    assert "legacy_soft_12".startswith(_RECOMPUTED_CODE_PREFIXES)


# ── 4. Every offered fix must actually work ──────────────────────────────────

def test_field_mode_facts_are_writable_via_producer_answer():
    """A `field`-mode fact that isn't writable by POST /api/audit/resolve-issue
    gives the producer an input box whose Apply silently does nothing."""
    from services.arq_service import _canonical_key

    bad = []
    for code, res in _LEGACY_CODE_RESOLUTIONS.items():
        if res.get("mode") != "field":
            continue
        assert res.get("facts"), f"{code}: field mode with no facts"
        for fact in res["facts"]:
            if not _canonical_key(fact):
                bad.append((code, fact))
    assert not bad, f"legacy field-mode facts that are NOT writable: {bad}"


def test_schedule_mode_keys_are_live_schedules():
    from services import schedule_capture

    bad = [
        (code, res["schedule_key"])
        for code, res in _LEGACY_CODE_RESOLUTIONS.items()
        if res.get("mode") == "schedule"
        and schedule_capture.get_def(res["schedule_key"]) is None
    ]
    assert not bad, f"legacy schedule-mode keys with no live SCHEDULE_DEFS entry: {bad}"


def test_field_mode_facts_are_not_schedule_backed():
    """A fact backed by a live capture schedule is a TABLE (vehicles, drivers,
    locations, loss runs). Offering it as a single text box would let a typed
    scalar overwrite a repeating structure - it must use `schedule` mode
    instead. Checked across BOTH maps, since the same mistake is possible on
    the cross-form side."""
    from services import schedule_capture
    from services.issue_registry import RESOLUTION_MAP as _CROSS

    sched_keys = set(getattr(schedule_capture, "SCHEDULE_DEFS", {}) or {})
    assert sched_keys, "no live schedules found - this guard would pass vacuously"

    bad = [
        (code, fact)
        for src in (_LEGACY_CODE_RESOLUTIONS, _CROSS)
        for code, res in src.items()
        if res.get("mode") == "field"
        for fact in res["facts"]
        if fact in sched_keys
    ]
    assert not bad, f"schedule-backed facts offered as a typed input: {bad}"


def test_none_mode_rules_explain_themselves():
    """A rule that genuinely can't be typed must say WHY, so the row reads as a
    deliberate decision rather than a row the fix feature skipped."""
    silent = [
        code for code, res in _LEGACY_CODE_RESOLUTIONS.items()
        if res.get("mode") == "none" and not res.get("note")
    ]
    assert not silent, f"'none'-mode legacy rules with no explanation note: {silent}"


def test_resolution_for_returns_a_copy_of_legacy_entries():
    """A caller mutating the returned dict must not corrupt the shared table."""
    a = resolution_for("legacy_carrier_grade_cope")
    b = resolution_for("legacy_carrier_grade_cope")
    assert a == b and a is not b
    a["facts"].append("junk")
    assert "junk" not in resolution_for("legacy_carrier_grade_cope")["facts"]


# ── 5. The reported client defect, end to end ────────────────────────────────

def test_client_reported_cope_warning_is_now_typeable():
    """Replay of the exact reported string (see replay-client-report-verbatim):
    the warning the client could not resolve must now carry a typed-value fix
    naming every field its own rule checks."""
    message = (
        "Carrier-Grade COPE incomplete - SQS capped at 85. Missing: year built, "
        "roof year, sprinkler system, fire protection class"
    )
    code, cluster, tier = classify_legacy(message, "soft_warning")
    assert code == "legacy_carrier_grade_cope"
    assert cluster == "Property COPE quality"
    assert tier == "binder_followup"

    issue = make_issue(code, "soft_warning", message, cluster=cluster, tier=tier)
    res = issue["resolution"]
    assert res["mode"] == "field"
    assert set(res["facts"]) == {
        "year_built", "roof_year", "sprinkler_system",
        "fire_protection_class", "valuation_method", "coinsurance_percentage",
    }


def test_hard_stop_umbrella_no_underlying_is_typeable_on_both_engines():
    """The hard stop that caps a package at 60 was work-tracking-only on BOTH
    the coded and the legacy path - a dead button on the most expensive
    blocker in the system."""
    coded = resolution_for("umbrella_no_underlying_coverage")
    legacy = resolution_for("legacy_umbrella_no_underlying")
    for res in (coded, legacy):
        assert res["mode"] == "field"
        assert set(res["facts"]) == {"gl_each_occurrence", "gl_limits", "auto_liability_limit"}


# ── 6. The fallback gate: other sources keep their own routing ───────────────

def test_other_issue_sources_never_pick_up_a_legacy_resolution_by_substring():
    """The rule table holds short phrases ("FEIN", "Effective date", "Phone")
    that appear verbatim inside cross-document conflict and low-OCR-confidence
    messages. Those families are resolved through the Data Consistency picker,
    not a typed box, so the message fallback must stay gated on the code."""
    cases = [
        ("ocr_low_confidence_fein", "FEIN read with low confidence - please confirm"),
        ("doc_conflict_hard_fein", "FEIN differs between documents: 12-3456789 vs 98-7654321"),
        ("doc_conflict_warn_effective_date", "Effective date differs between documents"),
        ("underwriting_reconciliation_total_revenue", "Total revenue differs across documents"),
    ]
    for code, message in cases:
        issue = make_issue(code, "soft_warning", message)
        assert issue["resolution"] is None, (
            f"{code} wrongly picked up a legacy resolution from its message text"
        )


def test_uncovered_safety_net_still_gets_a_fix_from_its_message():
    """A message that reaches the grouped view WITHOUT going through make_issue
    (build_grouped_view's uncovered_* safety net) has no code, so the message
    route is the only thing that can give it a fix - it must still work."""
    from services.issue_registry import build_grouped_view

    msg = "Total payroll must be a valid monetary amount"
    grouped = build_grouped_view([], [], [msg])
    rows = [i for c in grouped["warnings"].values() for cl in c for i in cl["items"]]
    row = next(r for r in rows if r["message"] == msg)
    assert row["resolution"]["mode"] == "field"
    assert row["resolution"]["facts"] == ["total_payroll"]
