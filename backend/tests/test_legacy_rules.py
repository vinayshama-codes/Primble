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
    # 21 Oct 2026: a backwards term read off a document is a WARNING with its
    # own sentence - unparseable dates above never reach the range check, so it
    # is driven separately (the hard twin is driven in _hard_stop_fixtures).
    _h2, soft2 = run_field_validations(
        {"effective_date": "07/15/2027", "expiration_date": "07/15/2026"})
    return list(hard) + list(soft) + list(_h2) + list(soft2)


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


def _harvest_cap_gate_reasons(cap: str | None = None) -> list[str]:
    """The sentences the CAP GATES print, which no other harvester can see.

    THIS IS THE BLIND SPOT THAT SHIPPED FOUR UNFIXABLE BLOCKERS.
    `_harvest_static_messages` walks `evaluate_stops`' own `hard.append(...)` /
    `soft.append(...)` sites. The three cap gates in `calculate_sqs` do not
    append anywhere - they pass a sentence to `_resolve_cap` as
    `extra_hard_reason` / `extra_soft_reason`, and `calculate_sqs` then returns
    it in `cap_hard_stops` for the UI to render as the hard stop it already was
    (2026-08-31). So on the day the cap was MADE VISIBLE, four sentences with no
    rule row started printing to producers - under "Other validations", with no
    Open-to-fix control and no Resolve target - and the build stayed green.

    Two of them were internal rule names shown to a broker: "Property integrity
    gate" and "Property integrity warning".

    Harvested from the AST for the same reason the static harvester is: the
    gates are mutually exclusive, so no single facts/flags dict trips them all.

    `cap="hard"` / `cap="soft"` keeps only the sentences that feed the 60 / the
    85 (20 Oct 2026: the caps are back; since 19 Oct the property gate and the
    umbrella "supporting detail" sentence are soft - only COPE and "no
    underlying" are hard gates, pinned by `test_every_cap_gate_reason_offers_a_real_fix`).
    """
    import services.sqs_service as sqs

    src = textwrap.dedent(inspect.getsource(sqs.calculate_sqs))
    tree = ast.parse(src)
    out: list[tuple[str, str]] = []

    def _collect(node, kind: str) -> None:
        for n in ast.walk(node):
            text = _literal_prefix(n) if isinstance(
                n, (ast.Constant, ast.JoinedStr, ast.BinOp)) else None
            if text and len(text.strip()) > 10:
                out.append((kind, text))

    for node in ast.walk(tree):
        # `_gate_hard_reason = (...)` - the COPE / umbrella / property ladder.
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in (
                        "_gate_hard_reason", "_gate_soft_reason"):
                    _collect(node.value, "hard" if t.id == "_gate_hard_reason" else "soft")
        # `extra_hard_reason=` / `extra_soft_reason=` passed to _resolve_cap.
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg in ("extra_hard_reason", "extra_soft_reason"):
                    _collect(kw.value, "hard" if kw.arg == "extra_hard_reason" else "soft")
            # `_prop_hard_because("...")` / `_prop_soft_because("...")`
            if (isinstance(node.func, ast.Name)
                    and node.func.id in ("_prop_hard_because", "_prop_soft_because")
                    and node.args):
                _collect(node.args[0],
                         "hard" if node.func.id == "_prop_hard_because" else "soft")

    return sorted({text for kind, text in out if cap in (None, kind)})


# ── The short hard-stop list (19 Oct 2026, Brent) ────────────────────────────
# A hard stop holds the score at 60 (back on 20 Oct 2026) and BLOCKS "Submission
# Ready" (19 Oct), and Brent keeps the list short - only what is essential to the
# submission. One fixture per HARD rule the field-level engine can raise (its
# branches are mutually exclusive, so each needs its own facts), each tripping
# exactly its own rule. Driven, not harvested: a literal opening such as "ACORD
# 125 minimum field missing: " is the Tier 1 BACKSTOP row on its own - only the
# full sentence names its field.

def _producer(value):
    return {"value": value, "confidence": "filled", "source": "producer"}


def _hard_stop_fixtures() -> dict:
    """{rule: (facts, flags, the sentence's opening words)}. Dates are relative
    to today, so the ended term stays ended and the proposed term stays ahead."""
    from datetime import datetime, timedelta

    def _d(days):
        return (datetime.now() + timedelta(days=days)).strftime("%m/%d/%Y")

    term = {"effective_date": _d(30), "expiration_date": _d(395)}
    return {
        "no proposed term": (
            {}, {}, "ACORD 125 minimum field missing: Proposed effective date"),
        # A person typed the term (21 Oct 2026, Brent: hard only when
        # verified). Bare document dates that run backwards are a warning now;
        # this fixture used them and pinned the old any-source rule.
        "a period that runs backwards": (
            {"effective_date": _producer(_d(395)), "expiration_date": _producer(_d(30))}, {},
            "Effective date is on or after expiration date - policy period is invalid"),
        "an ended term a person typed": (
            {"effective_date": _producer(_d(-455)), "expiration_date": _producer(_d(-90))},
            {}, "Policy term already expired"),
        "property without Minimum Viable COPE": (
            dict(term), {"has_property_coverage": True},
            "Property Minimum Viable COPE incomplete - missing:"),
        # The person's placement answer - the rule's one real input. This used
        # `wc_carrier_type="private"`, a key nothing writes (removed from the
        # rule 21 Oct 2026); the fixture drove the stop through a phantom.
        "a private carrier in a monopolistic WC state": (
            dict(term, wc_state_fund_acknowledged=_producer(
                "No - private-carrier coverage is being requested for those states")),
            {"has_workers_comp": True, "wc_has_monopolistic_state": True},
            "Monopolistic WC state (ND/OH/WA/WY) requires the state fund"),
        "an umbrella with no underlying limits": (
            dict(term), {"has_umbrella": True},
            "Umbrella detected but no underlying GL or Auto limits found"),
        # The same kind, line by line (21 Oct 2026, Brent's rule 2 -
        # b-umbrella-underlying): a line the umbrella's OWN schedule of
        # underlying insurance lists, with no limit found anywhere.
        "a line the umbrella's own schedule lists with no limit": (
            dict(term, gl_each_occurrence="$1,000,000",
                 underlying_policies=[{"line": "General Liability", "limit": "$1,000,000"},
                                      {"line": "Automobile Liability", "limit": ""}]),
            {"has_umbrella": True},
            "Umbrella's own schedule of underlying insurance lists "),
    }


def _driven_hard_stops() -> list[str]:
    """The hard sentences the fixtures above make the engine emit, as stored."""
    from services.sqs_service import evaluate_stops

    out: list[str] = []
    for facts, flags, _opening in _hard_stop_fixtures().values():
        hard, _soft = evaluate_stops(facts, flags)
        out.extend(m for m in hard if m not in out)
    return out


def _hard_append_sites() -> list[tuple[str, int, str | None]]:
    """Every `hard.append(...)` in the two functions that raise field-level hard
    stops: (function, line, literal opening - None for a computed sentence)."""
    import services.sqs_service as sqs
    from utils import validators

    sites = []
    for fn in (sqs.evaluate_stops, validators.run_field_validations):
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "append"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "hard" and node.args):
                sites.append((fn.__name__, node.lineno, _literal_prefix(node.args[0])))
    return sites


def _all_emittable_messages() -> list[str]:
    return (
        _harvest_static_messages()
        + _harvest_field_validation_messages()
        + _harvest_standalone_validator_messages()
        + _harvest_cap_gate_reasons()
        # 19 Oct 2026: the full hard sentences too - they block Submission Ready.
        + _driven_hard_stops()
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
    assert len(_harvest_cap_gate_reasons()) >= 6
    # (19 Oct 2026, kept) ...and every hard stop on Brent's short list is found.
    assert len(_driven_hard_stops()) == len(_hard_stop_fixtures()) >= 6


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


def test_the_property_gate_always_names_its_cause():
    """`_prop_soft` may only be raised through the helper that also records WHY.

    The gate used to surface as the literal "Property integrity gate" /
    "Property integrity warning" - our internal rule names, printed to a broker
    on a red blocker with no fix control. Each branch now supplies its own
    sentence, phrased so `classify_legacy` matches it and the row gets a real
    Open-to-fix.

    A future branch doing `_prop_soft = True` inline would quietly reopen that
    hole: the flag would be set, no reason recorded, and the generic fallback
    printed instead of the specific cause. This makes that a build failure.

    19 Oct 2026 (Brent's short hard-stop list, kept under the restored caps):
    the property gate is a WARNING only - a missing Period of Restoration holds
    85, not 60 - so `_prop_hard` / `_prop_hard_because` are gone, and a hard
    property gate coming back fails here too.
    """
    import services.sqs_service as sqs

    src = textwrap.dedent(inspect.getsource(sqs.calculate_sqs))
    tree = ast.parse(src)
    # The helper is the ONE place allowed to set the flag - it is also the
    # place that records the reason, which is the whole point.
    helpers = {"_prop_soft_because"}
    allowed = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in helpers:
            allowed.update(id(n) for n in ast.walk(node))
    assert allowed, "the _prop_soft_because helper is gone - this guard is vacuous"

    inline = []
    for node in ast.walk(tree):
        if id(node) in allowed or not isinstance(node, ast.Assign):
            continue
        if not (isinstance(node.value, ast.Constant) and node.value.value is True):
            continue
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id in ("_prop_hard", "_prop_soft"):
                inline.append((t.id, node.lineno))
    assert not inline, (
        "property gate raised without naming its cause - use "
        f"_prop_soft_because(): {inline}"
    )

    hard_gate = sorted(
        {n.id for n in ast.walk(tree)
         if isinstance(n, ast.Name) and n.id.startswith("_prop_hard")}
        | {n.name for n in ast.walk(tree)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
           and n.name.startswith("_prop_hard")})
    assert not hard_gate, f"the property gate holds 60 again: {hard_gate}"


def test_every_cap_gate_reason_offers_a_real_fix():
    """A sentence that CAPS the score at 60 or 85 must carry a fix, not just a
    code. The four umbrella/property gate sentences printed under "Other
    validations" with nothing to click from 2026-08-31 to 2026-09-08.

    19 Oct 2026 (Brent's short list, kept under the restored caps): only two
    gates hold 60 - Minimum Viable COPE and an umbrella with no underlying limit
    at all. The property gate, Period of Restoration included, and the umbrella
    "supporting detail" sentence (a limit stated only in words) hold 85.
    """
    reasons = _harvest_cap_gate_reasons()
    assert reasons, "cap-gate harvest is empty - this guard would pass vacuously"
    dead = []
    for message in reasons:
        code, _cluster, _tier = classify_legacy(message, "hard_stop")
        res = resolution_for(code) or {}
        if res.get("mode") not in ("field", "schedule", "narrative"):
            dead.append((message[:60], code, res.get("mode")))
    assert not dead, f"cap-gate sentences with no actionable fix: {dead}"

    assert _harvest_cap_gate_reasons("hard") == [
        "Minimum Viable COPE incomplete",
        "Umbrella present with no underlying GL or Auto limits",
    ]
    soft = _harvest_cap_gate_reasons("soft")
    assert "Business income limit present but period of restoration not specified" in soft
    assert any(m.startswith("Umbrella coverage is present but its supporting detail is "
                            "incomplete") for m in soft), soft


def test_every_hard_stop_offers_a_real_fix():
    """Every hard stop holds the score at 60 and (19 Oct 2026, kept) blocks
    "Submission Ready", so every one is a red row the producer must clear - and
    every one must open a real fix. Brent keeps the list short: every
    `hard.append` site must have its fixture above, so a new hard stop cannot
    ship without someone deciding it is essential.
    """
    from services.sqs_service import evaluate_stops

    sites = _hard_append_sites()
    fixtures = _hard_stop_fixtures()
    assert len(sites) == len(fixtures), (
        f"{len(sites)} hard.append sites but {len(fixtures)} fixtures - a hard stop "
        "was added or removed. Brent keeps the list short (19 Oct 2026): once it "
        f"is agreed, give it a fixture in _hard_stop_fixtures. Sites: {sites}"
    )
    driven = {}
    for rule, (facts, flags, opening) in fixtures.items():
        hard, _soft = evaluate_stops(facts, flags)
        assert len(hard) == 1 and hard[0].startswith(opening), (rule, hard)
        driven[rule] = hard[0]
    unseen = [s for s in sites if s[2] and not any(m.startswith(s[2]) for m in driven.values())]
    assert not unseen, f"hard.append sites no fixture trips: {unseen}"
    dead = []
    for rule, message in driven.items():
        code, _cluster, _tier = classify_legacy(message, "hard_stop")
        res = resolution_for(code) or {}
        if res.get("mode") not in ("field", "schedule", "narrative"):
            dead.append((rule, code, res.get("mode")))
    assert not dead, f"hard stops with no actionable fix: {dead}"


def test_no_cap_gate_reason_is_an_internal_rule_name():
    """"Property integrity gate" is what we call the rule. It is not something a
    broker can act on, and it was printed to one.

    The red blocker rows print the hard stops too (19 Oct 2026, kept), so the
    same rule reads them."""
    banned = ("integrity gate", "integrity warning", "_prop_", "gate)")
    bad = [m for m in _harvest_cap_gate_reasons() + _driven_hard_stops()
           if any(b in m.lower() for b in banned)]
    assert not bad, f"internal rule names printed to producers: {bad}"


# ── 5. Every rule's own phrase still resolves to its own row ─────────────────

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
        # + employers liability (21 Oct 2026, Brent's rule 2: an EL limit is an
        # applicable underlying limit, so it clears the stop too).
        assert set(res["facts"]) == {"gl_each_occurrence", "gl_limits", "auto_liability_limit",
                                     "employers_liability_limits"}


# ── 6. The fallback gate: other sources keep their own routing ───────────────

def test_other_issue_sources_never_pick_up_a_legacy_resolution_by_substring():
    """The rule table holds short phrases ("FEIN", "Effective date", "Phone")
    that appear verbatim inside cross-document conflict and low-OCR-confidence
    messages. Those families are resolved through the Data Consistency picker,
    not a typed box, so the message fallback must stay gated on the code."""
    # A low-OCR card opens its OWN field by its code since 15 Oct 2026 (a person's
    # value is what clears it - stops_now.ocr_review_stops); it still never picks up
    # ANOTHER rule's resolution from its words - pinned just below.
    ocr = make_issue("ocr_low_confidence_fein", "soft_warning", "FEIN read with low confidence - please confirm")
    assert ocr["resolution"]["mode"] == "field" and ocr["resolution"]["facts"] == ["fein"]
    cases = [
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


# ── A `none`-mode resolution must name its own cause (2026-09-22) ────────────
# WHY THIS EXISTS. `legacy_gl_no_class_codes` shipped as `_r_review()` on the
# stated grounds that GL class codes were "a per-location SCHEDULE with no live
# capture table, so there is nothing to type into". True when written. FALSE
# from the day `services/answer_routing.py` shipped (BUG-05, 2026-09-08) - the
# ONE DOOR for "can a human answer this?" returns `{"mode": "field"}` for
# `gl_class_codes_by_location` whenever it is empty, which is precisely when the
# rule fires. Two declarations of one thing, no test between them, so they
# drifted silently and a GL package whose documents print no class codes was
# pinned at SOFT_STOP_CAP (85) with a Resolve button that refused, a note that
# pointed at ACORD 126 (which has no writeback to either GL class-code fact) and
# a Dismiss whose credit `final_score_with_credits` clamps straight back under
# the same ceiling. Reported live as "we cannot get the Orbin package over 85".
#
# The house pattern is already established for cap gates - `_prop_soft_because`
# ("a cap gate must name its own cause"). This is the same rule for the other
# end: a resolution that offers NO fix must say why, and when the reason is
# "that is not a fact a human can write", the one door has to agree.
#
#   ()          - genuinely not about any fact (a placement, a form, unknowable)
#   ("fact",)   - it IS about these facts; a HUMAN decided none-mode anyway
_NO_FIX_CAUSE: dict[str, tuple[str, ...]] = {
    # Fixed by ADDING an ACORD form; each carries `add_forms` at its emit site,
    # so the card already offers the only action that clears it.
    "contractor_missing_acord186": (),
    "acord127_missing_state_137": (),
    "certificate_requested_but_acord25_missing": (),
    "property_evidence_requested_but_acord28_missing": (),
    "acord125_missing": (),
    # 19 Oct 2026: the expiring policies / endorsements ACORD 125 and 130 have
    # no room for print on ACORD 101 - the card's Add button is the fix.
    "acord101_for_expiring_policies": (),
    # Fixed by placing the coverage, not by typing a value.
    "crime_silent_exposure": (),
    "cyber_silent_exposure": (),
    # WC in ND/OH/WA/WY: the fix is the PLACEMENT (state fund vs private
    # carrier). The one door agrees - neither backing key is writable.
    # legacy_wc_monopolistic_state / _private_carrier left this list 15 Oct 2026:
    # both now ask the placement question the rule reads (wc_state_fund_acknowledged).
    # The STATIC entry only: what a view drawn without the facts can say. On the
    # Review screen the card is rebuilt per package with a choice of line for
    # each part (issue_registry.unmapped_line_issue, 14 Oct 2026).
    "unmapped_coverage_line": (),
    # ── Named, and left as `none` by a HUMAN decision (not by drift) ─────────
    # These fire on a value that is PRESENT and looks wrong for the risk, not on
    # an empty fact, so "type the value" is not obviously the fix. Listed here
    # so the choice is visible and re-checkable rather than silent. Revisit with
    # the owner; do NOT flip them without one.
    # The Tier 1 backstop: reached only by a sentence whose label is not one
    # check_tier1 emits, so the field it means is genuinely unknown. A real
    # Tier 1 sentence is classified by label before this row is consulted and
    # gets `_r_field` naming the exact fact - see _tier1_code_from_message.
    "legacy_tier1_unrecognised_field": (),
    # `acv_high_value_building` left this list on 14 Oct 2026 (owner: "if we
    # have any other similar like this, fix them too"): its fix IS the
    # valuation choice, offered as `valuation_method`'s own list.
    "rcv_old_building": ("valuation_method",),
    "auto_drive_other_car_not_specified": ("auto_drivers",),
}


def test_every_no_fix_resolution_declares_its_cause():
    """A new `none`-mode rule cannot ship without someone deciding WHY it has no
    fix. Without this, the next hand-authored dead end is invisible until a
    customer reports a score that will not move."""
    from services.issue_registry import RESOLUTION_MAP

    undeclared = sorted(
        code
        for src in (_LEGACY_CODE_RESOLUTIONS, RESOLUTION_MAP)
        for code, res in src.items()
        if (res or {}).get("mode") in (None, "none")
        and not (res or {}).get("add_forms")
        and code not in _NO_FIX_CAUSE
    )
    assert not undeclared, (
        "these resolutions offer the producer no fix and do not say why: "
        f"{undeclared} - add each to _NO_FIX_CAUSE with the fact(s) it is "
        "about, or give it a real resolution mode"
    )


def test_a_no_fix_rule_about_nothing_is_confirmed_by_the_one_door():
    """`_NO_FIX_CAUSE[code] == ()` claims "there is no fact behind this".
    `services/answer_routing.py` is the ONE DOOR for that question, so it has to
    agree. This is the exact drift that stranded legacy_gl_no_class_codes."""
    from services.answer_routing import answer_mode
    from services.issue_registry import RESOLUTION_MAP

    _all = {**_LEGACY_CODE_RESOLUTIONS, **RESOLUTION_MAP}
    # Facts each "about nothing" rule could plausibly be about, so the claim is
    # tested rather than asserted. Empty tuple = the rule names no fact at all.
    _backing = {
        "legacy_wc_monopolistic_state": ("wc_state_fund_acknowledged", "wc_carrier_type"),
        "legacy_wc_monopolistic_private_carrier": ("wc_state_fund_acknowledged", "wc_carrier_type"),
    }
    bad = []
    for code, facts in _NO_FIX_CAUSE.items():
        if facts or code not in _all:
            continue
        for fact in _backing.get(code, ()):
            if answer_mode(fact, {}).get("mode") != "none":
                bad.append((code, fact, answer_mode(fact, {}).get("mode")))
    assert not bad, (
        "a rule declared 'no fact behind this' but answer_routing says the fact "
        f"IS answerable: {bad} - the card and the write door disagree"
    )


def test_gl_class_codes_can_actually_be_answered():
    """The live regression, pinned at the shape the customer hit: a GL package
    with no class codes must offer a fix that WRITES the fact the rule reads.

    21 Oct 2026 (Brent 17 Oct item 6): the fix is the GL classification window -
    the capture table on `gl_class_code_schedule`, which the rule reads - not a
    free-text box on `gl_class_codes_by_location`. The one door agrees (a card
    on the old fact opens the table too), and the typed write door still takes
    the old fact (the ARQ text question, an older tab)."""
    from services import schedule_capture
    from services.answer_routing import answer_mode, can_write_scalar
    from services.arq_service import _canonical_key
    from services.issue_registry import _legacy_message_resolution
    from services.sqs_service import evaluate_stops

    msg = "GL coverage detected but no class codes found"
    res = _legacy_message_resolution(msg)
    assert res["mode"] == "schedule", "the GL class-code warning has no table to fill again"
    table = res["schedule_key"]
    assert schedule_capture.get_def(table) is not None, "the window names no live table"
    assert answer_mode("gl_class_codes_by_location", {})["schedule_key"] == table
    assert _canonical_key("gl_class_codes_by_location") and \
        can_write_scalar("gl_class_codes_by_location", {}), "the typed door was closed"

    facts = {"gl_limits": {"value": "$1,000,000"}}
    flags = {"has_general_liability": True}
    _, soft = evaluate_stops(facts, flags)
    assert msg in soft, "the warning no longer fires - rewrite this test, not the rule"

    rows, _ = schedule_capture.validate_rows(table, [{"location": "Location 1", "class_code": "91580",
                                                      "classification": "Carpentry - residential"}])
    facts[table] = schedule_capture.rows_for_facts(table, rows)
    _, soft_after = evaluate_stops(facts, flags)
    assert msg not in soft_after, (
        "answering the table the card opens does NOT clear the warning - the "
        "85 ceiling would stand after a correct answer"
    )
