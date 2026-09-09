"""BUG-06: "Something went wrong applying your answer" - the producer-answer door.

Client report, reproduced live by the owner 2026-09-08: the correct-value modal
accepted two umbrella dates and answered "Something went wrong applying your
answer." Investigation found FOUR separate defects behind that one sentence, and
this file is the executable guard for all of them.

  1. THE 500. `arq_service.apply_producer_answer_to_session` bound `_nv_delete`
     only inside `elif canon == NEW_VENTURE_FIELD:` and read it on every path,
     so EVERY producer answer except New Venture raised UnboundLocalError. That
     is POST /api/audit/resolve-issue (field + narrative), POST /api/audit/answer
     and services/client_answer_review.py. Shipped in commit d6d09c7 and walked
     straight through ~4800 green tests, because not one of them EXECUTED that
     function - all three references in the suite assert on its SOURCE TEXT.
     Hence section 1: it drives the real function.

  2. THE DEAD DROPDOWNS. Seven facts offered a closed list whose options their
     own FACT_REGISTRY validator refused - five refusing EVERY option, so those
     cards could not be resolved at all. Root cause: `answer_semantics` step 0b
     returned the chosen label verbatim on the assumption that "the catalogue's
     exact wording" is canonical. It is not; the fact's validator defines what
     the fact can hold, and extraction already writes that same shape
     (`"valuation_method": "RCV"|"ACV"|null`).

  3. THE USELESS MESSAGE. A 500 was produced OUTSIDE CORSMiddleware, so it
     carried no Access-Control-Allow-Origin, the browser killed it and every
     caller's catch block printed a generic string.

  4. THE DUPLICATE. `carrier_grade_cope_incomplete` was missing from
     `_LEGACY_SUPERSEDED_BY_CODE`, so both twins of the Carrier-Grade COPE rule
     rendered in one cluster.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import textwrap
from unittest.mock import patch

import pytest

import repositories.session_repository as sr
import services.answer_options as ao
import services.answer_semantics as asem
import services.arq_service as arq
import services.issue_registry as ir
from routes.audit_routes import _validate_producer_answer
from services.fact_registry import FACT_REGISTRY


# ══ 1. The write door, EXECUTED ═════════════════════════════════════════════

def _apply(field: str, value: str, *, facts=None, flags=None):
    """Drive the real apply_producer_answer_to_session against an in-memory
    session. Returns (ok, stored_session)."""
    store = {
        "facts": dict(facts or {}),
        "flags": dict(flags or {}),
        "generated_forms": {},
    }

    async def _get(_sid):
        return {k: (dict(v) if isinstance(v, dict) else v) for k, v in store.items()}

    async def _upd(_sid, payload, delete_facts=None):
        for k, v in (payload or {}).items():
            store[k] = v
        for k in (delete_facts or []):
            store.get("facts", {}).pop(k, None)
        return True

    with patch.object(sr, "get_processing_session", _get), \
         patch.object(sr, "upd_processing_session", _upd):
        ok, _updated = asyncio.run(
            arq.apply_producer_answer_to_session("sid-bug06", field, value))
    return ok, store


# One per shape a card or the modal can produce. The umbrella dates are the
# client's own case; the rest prove it was never about dates or values.
_SHAPES = [
    ("umbrella_effective_date",   "03/22/2027"),
    ("umbrella_expiration_date",  "03/22/2028"),
    ("effective_date",            "11/15/2026"),
    ("umbrella_limit",            "$5,000,000"),
    ("gl_each_occurrence",        "$2,000,000"),
    ("property_building_value",   "$3,750,000"),
    ("business_income_limit",     "$450,000"),
    ("auto_deductible_comp",      "$2,500"),
    ("total_payroll",             "$2,150,000"),
    ("valuation_method",          "RCV"),
    ("construction_type",         "Joisted Masonry"),
    ("year_built",                "1998"),
    ("coinsurance_percentage",    "90"),
    ("applicant_name",            "Halvorsen Ridge Millwork LLC"),
    ("additional_remarks_text",   "Umbrella term confirmed with the carrier."),
    ("fire_protection_class",     "3"),
    ("period_of_restoration",     "6"),
    ("sprinkler_system",          "Yes"),
]


@pytest.mark.parametrize("field,value", _SHAPES)
def test_every_producer_answer_applies(field, value):
    """The regression test that did not exist. Before the fix, 17 of these 18
    raised UnboundLocalError; only new_venture_indicator survived."""
    ok, store = _apply(field, value)
    assert ok is True, f"{field} was refused"
    assert field in store["facts"], f"{field} was not written to the session"


def test_the_three_flag_deriving_facts_still_apply():
    """The if/elif chain the defect lived in. All three branches must work, and
    so must the fall-through - that asymmetry WAS the bug."""
    for field, value in ((arq.NO_LOSS_INDICATOR_FIELD, "Yes"),
                         (arq.NEW_VENTURE_FIELD, "Yes"),
                         (arq.CARRIER_MARKETING_FIELD, "Premium increase")):
        ok, _ = _apply(field, value)
        assert ok is True, f"{field} was refused"


def test_new_venture_still_derives_and_deletes():
    """The branch that DOES populate _nv_delete must keep doing so - the fix
    must not have neutered the derivation it was added for."""
    ok, store = _apply(arq.NEW_VENTURE_FIELD, "Yes")
    assert ok is True
    assert store["flags"].get("new_venture_confirmed") is True


def test_a_non_new_venture_answer_derives_nothing():
    """`[]` is the pre-d6d09c7 behaviour: nothing to delete, so the session
    update passes delete_facts=None and no unrelated fact is retracted."""
    ok, store = _apply("year_built", "1998",
                       facts={"applicant_name": {"value": "Keep Me"}})
    assert ok is True
    assert store["facts"]["applicant_name"]["value"] == "Keep Me"


def test_an_unwritable_field_is_refused_not_crashed():
    """A key that resolves to no canonical fact must return False, not raise -
    the caller turns that into "attach a document or dismiss with a note"."""
    ok, _ = _apply("_not_a_real_fact_at_all", "x")
    assert ok is False


# ── Anti-rot: the defect CLASS, not the one line ────────────────────────────

def test_no_conditionally_bound_name_is_read_after_the_branch():
    """A name assigned only inside an if/elif chain with no else, then read
    after it, is exactly what shipped BUG-06. Fails the build if it returns
    anywhere in arq_service - a NameError in this module reaches production as
    an HTTP 500 on the producer's screen.

    A later statement that re-binds the name before reading it is safe and is
    not reported (`_clean_answer_ex`'s `normalized` does this legitimately).
    """
    src = inspect.getsource(arq)
    tree = ast.parse(src)
    hits = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        safe = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
        for stmt in fn.body:
            if isinstance(stmt, ast.If):
                continue
            for n in ast.walk(stmt):
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                    safe.add(n.id)
        for i, stmt in enumerate(fn.body):
            if not isinstance(stmt, ast.If):
                continue
            node, bound = stmt, set()
            while True:
                for n in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                        bound.add(n.id)
                if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
                    node = node.orelse[0]
                    continue
                break
            if node.orelse:                      # chain ends in else - all paths bind
                continue
            risky = bound - safe
            for later in fn.body[i + 1:]:
                rebound = {n.id for n in ast.walk(later)
                           if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
                for n in ast.walk(later):
                    if (isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                            and n.id in risky and n.id not in rebound):
                        hits.append(f"{fn.name}() reads conditionally-bound {n.id!r}")
                        risky.discard(n.id)
    assert not hits, "conditionally-bound names read after their branch: " + "; ".join(hits)


# ══ 2. Every offered option must be an answer the fact accepts ══════════════

def _real_options(fact_key):
    return [o for o in (ao.options_for(fact_key) or []) if o != ao.OTHER]


@pytest.mark.parametrize("fact_key", sorted(ao._CATALOGUE))
def test_every_offered_option_is_accepted(fact_key):
    """THE CONTRACT. A closed list may not offer a choice the door refuses.

    Measured before the fix, driving this same door: fire_protection_class 11 of
    11 refused, period_of_restoration 7 of 7, sprinkler_system 4 of 4,
    valuation_method 5 of 5, wc_xmod 4 of 4, construction_type 6 of 7,
    gl_form_type 1 of 3. Five of those cards could not be resolved by any input
    the producer was offered.
    """
    refused = []
    for opt in _real_options(fact_key):
        ok, msg = _validate_producer_answer(fact_key, opt)
        if not ok:
            refused.append(f"{opt!r} -> {msg}")
    assert not refused, f"{fact_key} offers options its own door refuses: {refused}"


def test_other_is_refused_everywhere_with_an_actionable_message():
    """"Other" is the affordance that reveals the free-text box, never a value.
    Stored literally it would print the word "Other" on an ACORD form."""
    for fact_key in sorted(ao._CATALOGUE):
        ok, msg = _validate_producer_answer(fact_key, ao.OTHER)
        assert ok is False, f"{fact_key} accepted the bare word 'Other' as a value"
        assert "Other" in msg and "type" in msg.lower(), \
            f"{fact_key}'s refusal does not tell the producer what to do: {msg!r}"


@pytest.mark.parametrize("fact_key,label,expected", [
    # The reduction is generic; these pin what it must produce.
    ("valuation_method",      "Replacement Cost",                    "RCV"),
    ("valuation_method",      "Actual Cash Value",                   "ACV"),
    ("fire_protection_class", "Protection Class 3",                  "3"),
    ("fire_protection_class", "Protection Class 10 - unprotected",   "10"),
    ("period_of_restoration", "6 months",                            "6"),
    ("sprinkler_system",      "Yes - fully sprinklered",             "Yes"),
    ("sprinkler_system",      "No - not sprinklered",                "No"),
    ("construction_type",     "Frame - wood construction",           "Frame"),
    ("construction_type",     "Modified Fire Resistive",             "Modified Fire Resistive"),
    ("wc_xmod",               "1.00 - neither a credit nor a debit mod", "1.00"),
    ("gl_form_type",          "Occurrence",                          "Occurrence"),
])
def test_option_labels_canonicalize_to_what_the_fact_holds(fact_key, label, expected):
    interp = asem.interpret_answer(fact_key, label)
    assert interp.accepted and interp.intent == asem.VALUE
    assert interp.value == expected


def test_canonical_value_matches_what_extraction_writes():
    """The reason we store the SHORT form and not the label: extraction's own
    schema line is `"valuation_method": "RCV"|"ACV"|null`. If a producer answer
    stored "Replacement Cost", one fact would carry two shapes depending on who
    supplied it, and every string comparison downstream would disagree."""
    from services import extraction_service as es
    assert '"valuation_method": "RCV"|"ACV"|null' in es._EXTRACT_SCHEMA


def test_a_list_entry_that_cannot_be_a_value_is_read_as_absence():
    """wc_xmod is a decimal, and two of its options exist to say the modifier
    does not exist. They must land as answers, not as malformed decimals."""
    assert asem.interpret_answer("wc_xmod", "Not applicable").intent == asem.NOT_APPLICABLE
    assert asem.interpret_answer(
        "wc_xmod", "No experience modifier has been assigned").intent == asem.ABSENCE


def test_a_label_that_already_passes_is_returned_unchanged():
    """Candidate one is the label itself, so the eleven catalogues that worked
    before the fix are byte-identical. This is the no-regression guard."""
    for fact_key in sorted(ao._CATALOGUE):
        entry = FACT_REGISTRY.get(fact_key) or {}
        checker = entry.get("validate")
        if not callable(checker):
            continue
        for opt in _real_options(fact_key):
            if checker(opt):
                assert asem.canonical_option_value(fact_key, opt, entry) == opt, \
                    f"{fact_key}: {opt!r} already valid but was reshaped"


def test_a_fact_with_no_validator_keeps_its_label():
    """No declared shape means the label IS the value - unchanged behaviour."""
    assert asem.canonical_option_value("occupancy_type", "Vacant building") == "Vacant building"


def test_the_reduction_never_invents_a_value_the_validator_refuses():
    """Self-checking by construction: every candidate is tested against the
    fact's own validator, so this can never produce something the door then
    rejects. Proved over every catalogue rather than asserted."""
    for fact_key in sorted(ao._CATALOGUE):
        entry = FACT_REGISTRY.get(fact_key) or {}
        checker = entry.get("validate")
        for opt in _real_options(fact_key):
            canon = asem.canonical_option_value(fact_key, opt, entry)
            if canon is not None and callable(checker):
                assert checker(canon), f"{fact_key}: {opt!r} -> {canon!r} fails its own validator"


def test_valuation_method_offers_only_what_the_fact_can_hold():
    """It offered four methods against a validator accepting two. ACORD 140's
    own tooltip lists Agreed Amount and Market Value too - widening the fact to
    carry them is an owner decision (extraction schema + validator + stamping
    move together), not something a bug fix does quietly."""
    assert _real_options("valuation_method") == ["Replacement Cost", "Actual Cash Value"]


# ══ 3. A 500 must reach the browser ═════════════════════════════════════════

def _main_module():
    """Import the app module, or skip.

    `main` pulls routes/auth_routes.py -> google.oauth2.id_token, which resolves
    fine on its own but collides with another test's google.* import during a
    full-collection run (same family as the documented httpx/openai baseline
    failure). The behavioural assertions below therefore run when this file is
    exercised directly; `test_the_middleware_and_the_error_path_share_one_policy`
    reads main.py off DISK and so guards the structure on every run regardless.
    """
    try:
        import main
        return main
    except Exception as ex:                                   # noqa: BLE001
        pytest.skip(f"main.py not importable in this collection: {type(ex).__name__}: {ex}")


def test_a_500_carries_the_cors_header_for_an_allowed_origin():
    """Starlette puts ServerErrorMiddleware OUTSIDE CORSMiddleware, so an
    app-level Exception handler's response never gets the header injected.
    Cross-origin that makes `fetch` reject, which is why one backend NameError
    reached producers as three different meaningless strings."""
    main = _main_module()
    from starlette.requests import Request

    allowed = (main.ALLOWED_ORIGINS or [None])[0]
    if not allowed:
        pytest.skip("no explicit allowed origin configured in this environment")

    scope = {"type": "http", "method": "POST", "path": "/api/audit/resolve-issue",
             "headers": [(b"origin", allowed.encode())], "query_string": b""}
    resp = asyncio.run(main._unhandled_exception_handler(
        Request(scope), RuntimeError("boom")))
    assert resp.status_code == 500
    assert resp.headers.get("access-control-allow-origin") == allowed
    assert resp.headers.get("vary") == "Origin"


def test_a_500_never_echoes_a_disallowed_origin():
    """The echo asks the SAME policy object the middleware uses, and a bare '*'
    is illegal alongside allow_credentials."""
    main = _main_module()
    from starlette.requests import Request

    scope = {"type": "http", "method": "POST", "path": "/x",
             "headers": [(b"origin", b"https://not-allowed.example")], "query_string": b""}
    resp = asyncio.run(main._unhandled_exception_handler(
        Request(scope), RuntimeError("boom")))
    assert resp.headers.get("access-control-allow-origin") is None
    assert "*" not in (resp.headers.get("access-control-allow-origin") or "")


def test_the_error_body_discloses_nothing():
    """The traceback goes to the log; the wire carries a fixed string."""
    main = _main_module()
    from starlette.requests import Request

    scope = {"type": "http", "method": "POST", "path": "/x", "headers": [], "query_string": b""}
    resp = asyncio.run(main._unhandled_exception_handler(
        Request(scope), RuntimeError("secret applicant name in the message")))
    assert b"secret" not in resp.body


def test_the_middleware_and_the_error_path_share_one_policy():
    """Two copies of an allow-list is how they drift.

    Read off DISK, not through an import, so this guard runs on every collection
    even where `main` itself will not import (see _main_module)."""
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(here, "main.py"), encoding="utf-8").read()
    assert "_cors_policy = CORSMiddleware(app=None, **_CORS_KWARGS)" in src,         "the error path no longer borrows the middleware's own allow-check"
    assert "app.add_middleware(CORSMiddleware, **_CORS_KWARGS)" in src,         "the middleware no longer shares _CORS_KWARGS with the error path"
    # The echo must stay conditional. A bare wildcard is illegal alongside
    # allow_credentials and would be a real weakening of the policy.
    assert "_cors_policy.is_allowed_origin(origin)" in src
    assert '"Access-Control-Allow-Origin"] = origin' in src


# ══ 4. The Carrier-Grade COPE twins ═════════════════════════════════════════

_LEGACY_COPE = ("Carrier-Grade COPE incomplete - Submission Quality Score (SQS) capped "
                "at 85. Missing: year built, roof year, sprinkler system, fire "
                "protection class, valuation method, coinsurance percentage")
_CODED_COPE = ("Carrier-Grade COPE detail incomplete - missing: year built, roof "
               "year, sprinkler system, protection class. Submission can proceed "
               "but your Submission Quality Score (SQS) will be capped.")


def _view_codes(structured, cross, soft):
    import json
    view = ir.build_grouped_view(structured, [], soft, cross_issues=cross)
    return json.dumps(view, default=str)


def test_the_legacy_cope_twin_is_hidden_when_the_coded_one_is_present():
    """Reported live 2026-09-08: the Property COPE quality cluster rendered both,
    each with its own Open to fix."""
    legacy = {"code": "legacy_carrier_grade_cope", "message": _LEGACY_COPE,
              "severity": "soft_warning", "forms": ["ACORD_140"]}
    coded = {"code": "carrier_grade_cope_incomplete", "message": _CODED_COPE,
             "severity": "soft_warning", "forms": ["ACORD_140"]}
    out = _view_codes([legacy], [coded], [_LEGACY_COPE, _CODED_COPE])
    assert "legacy_carrier_grade_cope" not in out
    assert "carrier_grade_cope_incomplete" in out


def test_the_legacy_cope_twin_still_shows_when_it_fires_alone():
    """Suppression is conditional. The coded rule has a form-trigger gate the
    legacy one does not, so a blocker must never be lost."""
    legacy = {"code": "legacy_carrier_grade_cope", "message": _LEGACY_COPE,
              "severity": "soft_warning", "forms": ["ACORD_140"]}
    out = _view_codes([legacy], [], [_LEGACY_COPE])
    assert "legacy_carrier_grade_cope" in out


def test_the_suppression_phrase_cannot_match_its_own_keeper():
    """Substring suppression that matched the coded message would delete both."""
    phrase = ir._LEGACY_SUPERSEDED_BY_CODE["carrier_grade_cope_incomplete"]
    assert phrase in _LEGACY_COPE
    assert phrase not in _CODED_COPE


def test_suppressing_the_legacy_twin_loses_no_fix_path():
    """THE REASON THE CODED RESOLUTION WAS WIDENED FIRST. Measured 2026-09-08:
    with coinsurance the only missing COPE item, `evaluate_stops` emits ONLY the
    legacy COPE warning - there is no dedicated coinsurance card the way there is
    for valuation method. Hiding the legacy twin while the coded one offered four
    facts would have deleted the producer's only way to type it."""
    legacy_facts = set()
    for phrase, _cluster, _tier, code, res in ir._LEGACY_MESSAGE_RULES:
        if code == "legacy_carrier_grade_cope":
            legacy_facts = set((res or {}).get("facts") or ())
    coded_facts = set((ir.resolution_for("carrier_grade_cope_incomplete") or {}).get("facts") or ())
    assert legacy_facts, "the legacy COPE rule lost its resolution"
    assert legacy_facts <= coded_facts, (
        "the coded COPE card no longer offers everything the suppressed legacy "
        f"card did - missing {sorted(legacy_facts - coded_facts)}")


def test_every_suppression_entry_still_names_a_real_legacy_message():
    """Guards the whole map, not just the new row: a phrase that matches nothing
    silently suppresses nothing and reads as fixed."""
    legacy_phrases = [r[0] for r in ir._LEGACY_MESSAGE_RULES]
    for code, phrase in ir._LEGACY_SUPERSEDED_BY_CODE.items():
        assert any(phrase in p or p in phrase for p in legacy_phrases), \
            f"{code} suppresses {phrase!r}, which no legacy rule can emit"


# ══ 5. The renewal umbrella term: one fact key, two footings ════════════════
#
# Found by the owner on the FIRST live run after the fixes above, because the
# 500 had been hiding it. `legacy_umbrella_renewal_term_unknown` asks the
# producer to state the PROPOSED umbrella term; `_package_period_on_umbrella_
# footing` then compared that answer to the EXPIRING package term and raised two
# HARD STOPS, capping the package at 60. Measured before the fix: the proposed
# term hard-stopped, the DERIVED proposed term hard-stopped, and the only input
# that cleared it was the expiring term - i.e. the wrong answer to the question
# the card asked. A rule no correct answer can satisfy is the defect.

import services.cross_form_validator as cfv

_ROUTED_RENEWAL = {
    "renewal_dates_routed": True,
    "prior_effective_date": "07/25/2025", "prior_expiration_date": "07/25/2026",
    # What _route_renewal_dates derives and flags for producer confirmation.
    "effective_date":  {"value": "07/25/2026", "source": "derived", "confidence": "low_confidence"},
    "expiration_date": {"value": "07/25/2027", "source": "derived", "confidence": "low_confidence"},
}


def _umbrella_issues(facts):
    out = cfv._check_umbrella_attachment_stack(
        facts, {"has_umbrella": True}, {"ACORD_125", "ACORD_131"})
    return ([i for i in out if i.get("type") == "hard_stop"],
            [i for i in out if i.get("type") == "soft_warning"])


def _with_umbrella(eff, exp, source):
    return dict(_ROUTED_RENEWAL,
                umbrella_effective_date={"value": eff, "source": source, "confidence": "filled"},
                umbrella_expiration_date={"value": exp, "source": source, "confidence": "filled"})


def test_answering_the_renewal_card_correctly_raises_nothing():
    """THE reported case. The producer states the proposed term the card asked
    for; it matches the proposed package term, so nothing is raised at all."""
    hard, soft = _umbrella_issues(_with_umbrella("07/25/2026", "07/25/2027", "producer"))
    assert not hard, [i["message"] for i in hard]
    assert not soft, [i["message"] for i in soft]


def test_a_producer_answer_is_never_compared_to_the_expiring_term():
    """The footing flips with provenance. A genuinely different proposed term
    is still reported - that is real - but against the PROPOSED package term,
    and as a warning, never a 60 cap on a value we only guessed."""
    hard, soft = _umbrella_issues(_with_umbrella("03/22/2027", "03/22/2028", "producer"))
    assert not hard, "a stated value must not hard-stop against a derived one"
    assert len(soft) == 2
    for issue in soft:
        assert "expiring GL/policy" not in issue["message"], issue["message"]


def test_extraction_sourced_dates_keep_the_expiring_footing():
    """The 2026-08-16 fix this helper exists for must be untouched: on a routed
    renewal, dates read off the umbrella's own dec page ARE the expiring term."""
    hard, soft = _umbrella_issues(_with_umbrella("07/25/2025", "07/25/2026", "ai"))
    assert not hard and not soft
    _hard2, soft2 = _umbrella_issues(_with_umbrella("01/01/2025", "01/01/2026", "ai"))
    assert len(soft2) == 2
    assert all("expiring GL/policy" in i["message"] for i in soft2)


def test_a_non_renewal_package_still_hard_stops():
    """THE REGRESSION GUARD. Nothing above may weaken the ordinary case: a
    stated package term and a misaligned umbrella is still a hard stop."""
    facts = {"effective_date": "01/01/2026", "expiration_date": "01/01/2027",
             "umbrella_effective_date": "03/01/2026",
             "umbrella_expiration_date": "03/01/2027"}
    hard, _soft = _umbrella_issues(facts)
    assert len(hard) == 2

    aligned = dict(facts, umbrella_effective_date="01/01/2026",
                   umbrella_expiration_date="01/01/2027")
    assert _umbrella_issues(aligned) == ([], [])

    explained = dict(facts, additional_remarks_text="Umbrella renews on its own anniversary.")
    hard3, soft3 = _umbrella_issues(explained)
    assert not hard3 and len(soft3) == 2      # ACORD 101 exception intact

    # A producer-supplied date on a NON-renewal has no derived value to be
    # measured against, so it must still hard-stop.
    typed = dict(facts,
                 umbrella_effective_date={"value": "03/01/2026", "source": "producer"},
                 umbrella_expiration_date={"value": "03/01/2027", "source": "producer"})
    hard4, _s4 = _umbrella_issues(typed)
    assert len(hard4) == 2


def test_the_footing_asks_one_table_who_counts_as_human():
    """No second copy of "which sources are people" - it reads fact_state's."""
    from services.fact_state import _HUMAN_SOURCES
    for src in _HUMAN_SOURCES:
        assert cfv._umbrella_dates_are_proposed(
            {"umbrella_effective_date": {"value": "01/01/2027", "source": src}}), src
    for src in ("ai", "derived", "dec_entry", ""):
        assert not cfv._umbrella_dates_are_proposed(
            {"umbrella_effective_date": {"value": "01/01/2027", "source": src}}), src


# ══ 6. The modal's primary button must match the note ═══════════════════════

def test_the_note_and_the_button_share_one_computation():
    """The footer used to offer a pink "Apply the fix" above a note reading
    "Resolve it from the validation panel when you are ready" - telling the
    producer to do something unavailable, right after a save that succeeded."""
    from routes.audit_routes import _trade_off_note, _trade_off_settleable_here

    # Keyed on the rule code; the sentence rides along for display.
    introduced = {"legacy_umbrella_gl_expiration_misaligned": {
        "message": "Umbrella and GL expiration dates misaligned",
        "facts": ["umbrella_expiration_date", "expiration_date"]}}

    # Nothing typeable on this screen -> the note says so, and so must the flag.
    note = _trade_off_note(introduced, [], "umbrella_effective_date", facts={})
    here = _trade_off_settleable_here(introduced, [], "umbrella_effective_date", facts={})
    assert "Resolve it from the validation panel" in note
    assert here == []

    # A fact the modal offers and that is still empty -> settleable here.
    open_facts = ["umbrella_effective_date", "expiration_date"]
    note2 = _trade_off_note(introduced, open_facts, "umbrella_effective_date", facts={})
    here2 = _trade_off_settleable_here(introduced, open_facts, "umbrella_effective_date", facts={})
    assert "You can settle it here" in note2
    assert here2 == ["expiration_date"]

    # The flag is never true while the note says to leave, and vice versa.
    for n, h in ((note, here), (note2, here2)):
        assert bool(h) == ("You can settle it here" in n)


def test_the_endpoint_returns_the_flag_the_modal_reads():
    """Structural: the wire contract between the two halves of the fix."""
    import inspect as _i
    import routes.audit_routes as _ar
    src = _i.getsource(_ar.resolve_issue)
    assert '"note_settle_here":' in src
    assert "_trade_off_settleable_here(" in src


def test_the_auto_wc_sibling_stands_down_on_a_proposed_umbrella_term():
    """Same footing defect, one check over. Auto/WC dates come off their own dec
    pages, so on a renewal they are EXPIRING while a producer-answered umbrella
    term is PROPOSED. There is no proposed Auto/WC term fact to compare with, so
    the check stands down rather than hard-stopping on a mismatch of footings."""
    facts = dict(_ROUTED_RENEWAL,
                 auto_effective_date="07/25/2025", auto_expiration_date="07/25/2026",
                 wc_effective_date="07/25/2025", wc_expiration_date="07/25/2026",
                 umbrella_effective_date={"value": "07/25/2026", "source": "producer"},
                 umbrella_expiration_date={"value": "07/25/2027", "source": "producer"})
    flags = {"has_umbrella": True, "has_auto_coverage": True, "has_workers_comp": True}
    out = cfv._check_umbrella_period_vs_auto_wc(
        facts, flags, {"ACORD_127", "ACORD_130", "ACORD_131"})
    assert out == [], [i["message"] for i in out]


def test_the_auto_wc_sibling_is_otherwise_untouched():
    """The regression guard for the stand-down above: extraction-sourced dates
    on a renewal, and every non-renewal, still compare and still hard stop."""
    flags = {"has_umbrella": True, "has_auto_coverage": True}
    trig = {"ACORD_127", "ACORD_131"}

    extracted = dict(_ROUTED_RENEWAL,
                     auto_effective_date="07/25/2025", auto_expiration_date="07/25/2026",
                     umbrella_effective_date="01/01/2025",
                     umbrella_expiration_date="01/01/2026")
    assert cfv._check_umbrella_period_vs_auto_wc(extracted, flags, trig)

    non_renewal = {"auto_effective_date": "01/01/2026", "auto_expiration_date": "01/01/2027",
                   "umbrella_effective_date": {"value": "03/01/2026", "source": "producer"},
                   "umbrella_expiration_date": {"value": "03/01/2027", "source": "producer"}}
    out = cfv._check_umbrella_period_vs_auto_wc(non_renewal, flags, trig)
    assert [i for i in out if i.get("type") == "hard_stop"]


# ══ 7. A shrinking warning is not a new one ═════════════════════════════════

_COPE_6 = ("Carrier-Grade COPE incomplete - Submission Quality Score (SQS) capped at "
           "85. Missing: year built, roof year, sprinkler system, fire protection "
           "class, valuation method, coinsurance percentage")
_COPE_5 = ("Carrier-Grade COPE incomplete - Submission Quality Score (SQS) capped at "
           "85. Missing: year built, roof year, sprinkler system, fire protection "
           "class, coinsurance percentage")


def test_filling_one_field_of_a_list_warning_raises_nothing():
    """Reported live 2026-09-08. Supplying valuation method makes the COPE
    warning SHORTER; a message-keyed before/after diff read the shortened
    sentence as a brand new issue and told the producer their fix had raised
    one. The modal exists to end that loop, not to manufacture it."""
    from routes.audit_routes import _issues_bound_to_fact, _trade_off_note

    before = _issues_bound_to_fact({"soft_stops": [_COPE_6]}, "valuation_method")
    after = _issues_bound_to_fact({"soft_stops": [_COPE_5]}, "valuation_method")
    assert list(before) == list(after) == ["legacy_carrier_grade_cope"]

    introduced = {k: v for k, v in after.items() if k not in before}
    assert introduced == {}
    assert _trade_off_note(introduced, ["valuation_method"], "valuation_method",
                           facts={}) == ""


def test_a_genuinely_new_rule_still_raises_a_note():
    """The guard must not silence the real trade - only the churn."""
    from routes.audit_routes import _issues_bound_to_fact, _trade_off_note

    before = _issues_bound_to_fact({"soft_stops": []}, "valuation_method")
    after = _issues_bound_to_fact({"soft_stops": [_COPE_6]}, "valuation_method")
    introduced = {k: v for k, v in after.items() if k not in before}
    assert list(introduced) == ["legacy_carrier_grade_cope"]
    note = _trade_off_note(introduced, ["valuation_method"], "valuation_method", facts={})
    assert "raised a new issue" in note and "Carrier-Grade COPE" in note


def test_identity_is_the_rule_code_not_the_sentence():
    """Structural: two different sentences from ONE rule collapse to one entry."""
    from routes.audit_routes import _issues_bound_to_fact
    found = _issues_bound_to_fact({"soft_stops": [_COPE_6, _COPE_5]}, "valuation_method")
    assert len(found) == 1


# ══ 8. The ticket's own first acceptance criterion ══════════════════════════
#   "Reproduce with the captured date values."
# The client typed TWO-DIGIT years. Every other test in this file uses four, and
# a fix can pass all of them and still miss the reported case - which is why the
# reported values get pinned verbatim rather than paraphrased.

def test_the_clients_literal_values_apply():
    ok, store = _apply("umbrella_effective_date", "07/15/25")
    assert ok is True
    ok2, store2 = _apply("umbrella_expiration_date", "07/15/26")
    assert ok2 is True
    # Canonicalized to four digits on the way in, so the stored value matches
    # the shape extraction writes and the ACORD date box expects.
    assert store["facts"]["umbrella_effective_date"]["value"] == "07/15/2025"
    assert store2["facts"]["umbrella_expiration_date"]["value"] == "07/15/2026"


def test_a_two_digit_year_never_reads_as_a_different_date():
    """The stored four-digit form must not manufacture a misalignment against a
    two-digit one elsewhere in the package."""
    assert not cfv._dates_differ("07/15/25", "07/15/2025")
    assert not cfv._dates_differ("07/15/26", "07/15/2026")
    assert cfv._dates_differ("07/15/25", "07/15/2026")
