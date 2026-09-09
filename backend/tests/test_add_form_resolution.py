"""UX-05 - "Add form" from a validation finding.

A validation that says "ACORD 186 is missing" used to open a modal offering
Dismiss / Mark resolved. Neither adds the form, and after generation there is no
route back to the form list, so the finding was a dead end.

Decision_Tree.txt L501 asked for the missing half in terms - "Prompt user to
generate ACORD 25/28 post-bind" - and only the warning was ever built.

THE ANTI-ROT TEST IS THE POINT OF THIS FILE.
`test_every_add_a_form_message_declares_the_form` HARVESTS every `_issue(...)`
call in cross_form_validator and fails the build when a message instructs the
producer to add or attach an ACORD form without declaring `add_forms`. The
standing lesson from BUG-05 is that an anti-rot harvester is only as wide as the
emission path it walks, so this walks the AST of the real module rather than a
copy of the rule list.

The reverse guard matters just as much: `test_no_rule_declares_a_form_its_
message_never_mentions` fails if a declaration drifts away from the sentence the
producer actually reads.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services import cross_form_validator as cfv           # noqa: E402
from services.cross_form_validator import (                # noqa: E402
    _filter_add_forms, _issue, run_cross_form_validation,
)
from services.issue_registry import (                      # noqa: E402
    build_structured_from_sources, make_issue, resolution_for,
)
from services import form_addition                          # noqa: E402


# ── Harvest: what does every rule actually SAY? ──────────────────────────────

_SOURCE = inspect.getsource(cfv)
_TREE = ast.parse(_SOURCE)

# "ACORD 186" / "ACORD_186" / "ACORD 137_CA" -> the id the form list uses.
_ACORD_RE = re.compile(r"ACORD[ _]?(\d{2,3}(?:_[A-Z]{2})?)")

# Cue matching is PHRASE-SCOPED, not message-scoped, and the two directions are
# deliberately different. Getting this wrong in the first draft produced four
# false positives on one run - the message-wide version read "Add operations
# detail or attach ACORD 101" and concluded the rule wanted ACORD *125* added,
# because 125 appeared in the same sentence as the word "Add".
#
# BEFORE the form name: an imperative. "add / attach ACORD 101" is an
# instruction to put that form in the package.
_ADD_BEFORE_RE = re.compile(
    r"\b(add|attach|include|generate|explained\s+via)\b[^.]{0,12}$", re.I)

# AFTER the form name: an absence. "ACORD 125 ... was not detected" says the
# same thing with the form as the subject. Imperatives are deliberately NOT in
# this set - a later "Add <something else>" in the same sentence must not make
# an earlier, unrelated form look addable.
_ADD_AFTER_RE = re.compile(
    r"\b(?:was |is |are )?not (?:detected|included|provided|in the selected forms)\b|"
    r"\bis missing\b|\bwas not detected\b", re.I)

# "Add EL limits ON ACORD 130" is an instruction about a VALUE on a form that is
# already there. A preposition immediately before the form name means the form
# is the LOCATION of the fix, not the fix.
_LOCATIVE_RE = re.compile(r"\b(on|in|across|between|from|of|to|per)\s+(an?\s+)?ACORD\s*$", re.I)

_BEFORE_WINDOW = 50
_AFTER_WINDOW = 55


def _literal_str(node) -> str:
    """Every literal character of a message, however it is assembled.

    Messages here are built four ways - a plain literal, implicit concatenation
    inside parentheses, `+` concatenation, and f-strings interpolating a count.
    `ast.literal_eval` handles only the first two and returns "" for the rest,
    which made the first version of this harvester BLIND on nine real rules
    while reporting green. Interpolated values become a space: they are numbers
    and names, never a form id.
    """
    if node is None:
        return ""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else ""
    if isinstance(node, ast.JoinedStr):
        return "".join(_literal_str(v) for v in node.values)
    if isinstance(node, ast.FormattedValue):
        return " "
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _literal_str(node.left) + _literal_str(node.right)
    if isinstance(node, ast.IfExp):
        # A message whose closing sentence branches on state (2026-09-09:
        # `acord101_required` says "Attach ACORD 101" or "add the narrative"
        # depending on whether the form is already there). BOTH branches ship to
        # a producer, so both must be harvested - returning "" here would have
        # made this rule invisible to the guards below while they stayed green,
        # which is exactly the blindness the f-string case already cost once.
        return _literal_str(node.body) + " " + _literal_str(node.orelse)
    if isinstance(node, ast.Call):
        # e.g. `"; ".join(reason_parts)` - no literal form id can hide in there.
        return " "
    return ""


def _harvest_issue_calls():
    """(code, message, declared_add_forms, lineno) for every `_issue(...)`.

    Walks the real module's AST, so a rule added tomorrow is harvested the day
    it lands - the device `test_legacy_rules` uses for `evaluate_stops`.
    """
    out = []
    for node in ast.walk(_TREE):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Name) and fn.id == "_issue"):
            continue
        args = node.args
        code = _literal_str(args[1]) if len(args) > 1 else ""
        message = _literal_str(args[2]) if len(args) > 2 else ""
        declared = []
        for kw in node.keywords:
            if kw.arg == "add_forms":
                try:
                    v = ast.literal_eval(kw.value)
                    declared = list(v) if isinstance(v, (list, tuple)) else []
                except Exception:
                    declared = ["<dynamic>"]
        out.append((code, message, declared, node.lineno))
    return out


_ISSUE_CALLS = _harvest_issue_calls()


def test_the_harvester_is_not_vacuous():
    """A harvest of zero would make every test below pass while proving nothing.

    This is the C25 trap written down: the full-document coverage test passed
    over a pipeline dropping 46% of a document because its recorder never
    exercised the path. A harvester needs its own floor.
    """
    assert len(_ISSUE_CALLS) > 60, f"only harvested {len(_ISSUE_CALLS)} _issue() calls"
    assert any(c == "contractor_missing_acord186" for c, _, _, _ in _ISSUE_CALLS)
    assert sum(1 for _, _, d, _ in _ISSUE_CALLS if d) >= 17


def _forms_the_message_tells_you_to_add(message: str):
    """Form ids a broker reading THIS sentence would go and add."""
    found = set()
    for m in _ACORD_RE.finditer(message):
        before = message[max(0, m.start() - _BEFORE_WINDOW):m.start()]
        after = message[m.end():m.end() + _AFTER_WINDOW]
        # A form named as the PLACE the fix happens is never the fix itself.
        if _LOCATIVE_RE.search(before):
            continue
        if _ADD_BEFORE_RE.search(before) or _ADD_AFTER_RE.search(after):
            found.add("ACORD_" + m.group(1))
    return found


def test_the_cue_reader_separates_an_instruction_from_a_mention():
    """The harvester's own unit test. It decides whether a build passes, so a
    silent regression in it would disarm every guard below - the C25 trap.

    Every string here is real message text from the module.
    """
    # Instructions - these MUST be recognised.
    assert _forms_the_message_tells_you_to_add(
        "Operations indicate a contracting business (GL coverage present) but "
        "ACORD 186 Contractors Supplement is not included. Add ACORD 186 to "
        "capture subcontracting and high-hazard details.") == {"ACORD_186"}
    assert _forms_the_message_tells_you_to_add(
        "ACORD 125 (Commercial Insurance Application) was not detected.") == {"ACORD_125"}
    assert _forms_the_message_tells_you_to_add(
        "Verify each insured location is represented on both forms or add "
        "ACORD 101 explanation.") == {"ACORD_101"}
    # Mentions - these must NOT be.
    assert _forms_the_message_tells_you_to_add(
        "Liability limits are not provided. Add EL limits on ACORD 130.") == set()
    assert _forms_the_message_tells_you_to_add(
        "ACORD 131 (Umbrella/Excess) is present but neither ACORD 126 (GL) nor "
        "ACORD 127 (Auto) underlying policies were found. Umbrella cannot "
        "attach without required underlying limits.") == set()
    assert _forms_the_message_tells_you_to_add(
        "ACORD 186 reports 40% subcontracted work but no Workers Comp payroll "
        "is provided. WC payroll is required when subcontracting exceeds 30%.") == set()
    # Mixed - the imperative governs the LATER form only. This exact sentence is
    # what broke the message-wide first draft.
    assert _forms_the_message_tells_you_to_add(
        "GL class codes are present on ACORD 126 but ACORD 125 has no operations "
        "description. Add operations detail or attach ACORD 101.") == {"ACORD_101"}
    assert _forms_the_message_tells_you_to_add(
        "ACORD 125 lists 3 location(s) but ACORD 140 has 1. Location counts must "
        "match or be explained via ACORD 101.") == {"ACORD_101"}


def test_every_add_a_form_message_declares_the_form():
    """ANTI-ROT. A new rule that says "add ACORD X" must declare add_forms=[X].

    Without this, the next missing-form rule ships a sentence telling the
    producer to add a form and a card with no way to add it - which is the
    entire defect UX-05 reported, reintroduced.
    """
    missing = []
    for code, message, declared, lineno in _ISSUE_CALLS:
        wanted = _forms_the_message_tells_you_to_add(message)
        if not wanted:
            continue
        undeclared = wanted - set(declared)
        if undeclared:
            missing.append(f"L{lineno} {code or '?'}: says to add {sorted(undeclared)} "
                           f"but declared {declared or 'nothing'}")
    assert not missing, (
        "cross_form_validator rules instruct the producer to add a form without "
        "declaring it, so the card cannot offer the action:\n  "
        + "\n  ".join(missing)
    )


def test_no_rule_declares_a_form_its_message_never_mentions():
    """The reverse guard: a declaration must match what the producer READS.

    A drifted declaration is worse than a missing one - the card would offer to
    generate a form the sentence above it never asked for.
    """
    drifted = []
    for code, message, declared, lineno in _ISSUE_CALLS:
        for fid in declared:
            num = fid.replace("ACORD_", "")
            if not re.search(r"ACORD[ _]?" + re.escape(num), message):
                drifted.append(f"L{lineno} {code or '?'}: declares {fid}, message never names it")
    assert not drifted, "add_forms declarations drifted from their messages:\n  " + "\n  ".join(drifted)


def test_declared_forms_are_real_acord_form_ids():
    """A typo would render an Add button for a form that cannot be generated."""
    from services.form_service import filter_available_forms, load_all_forms
    real = {f["form_id"] for f in filter_available_forms(load_all_forms())}
    assert real, "no ACORD templates available - fixture problem, not a code problem"
    bad = []
    for code, _msg, declared, lineno in _ISSUE_CALLS:
        for fid in declared:
            if fid not in real:
                bad.append(f"L{lineno} {code or '?'}: {fid} is not a generatable form")
    assert not bad, "add_forms names a form with no template:\n  " + "\n  ".join(bad)


# ── The filter: only ever offer a form that is genuinely absent ──────────────

def test_a_declared_form_that_is_already_selected_is_not_offered():
    issues = [_issue("advisory", "acord101_required", "Attach ACORD 101 with narrative.",
                     ["ACORD_101"], add_forms=["ACORD_101"])]
    _filter_add_forms(issues, {"ACORD_125", "ACORD_101"})
    assert "add_forms" not in issues[0]["resolution"], (
        "offered a form that is already in the package"
    )


def test_the_key_is_removed_not_emptied():
    """Every display layer tests truthiness; `[]` would draw a dead button."""
    issues = [_issue("soft_warning", "contractor_missing_acord186", "Add ACORD 186.",
                     ["ACORD_186"], add_forms=["ACORD_186"])]
    _filter_add_forms(issues, {"ACORD_186"})
    assert "add_forms" not in issues[0]["resolution"]


def test_a_declared_form_that_is_missing_survives():
    issues = [_issue("soft_warning", "contractor_missing_acord186", "Add ACORD 186.",
                     ["ACORD_186"], add_forms=["ACORD_186"])]
    _filter_add_forms(issues, {"ACORD_125", "ACORD_126"})
    assert issues[0]["resolution"]["add_forms"] == ["ACORD_186"]


def test_partial_filtering_keeps_only_the_absent_ones():
    issues = [_issue("soft_warning", "x", "Add ACORD 101 and ACORD 186.",
                     ["ACORD_101"], add_forms=["ACORD_101", "ACORD_186"])]
    _filter_add_forms(issues, {"ACORD_101"})
    assert issues[0]["resolution"]["add_forms"] == ["ACORD_186"]


def test_filter_is_safe_on_issues_with_no_resolution_at_all():
    _filter_add_forms([{"code": "x", "message": "y"}, None, {}], {"ACORD_125"})  # must not raise


def test_an_unmapped_code_still_gets_an_add_form_envelope():
    """A code with no RESOLUTION_MAP row can still be closed by adding a form."""
    assert resolution_for("totally_unknown_code_xyz") is None
    iss = _issue("soft_warning", "totally_unknown_code_xyz", "Add ACORD 186.",
                 ["ACORD_186"], add_forms=["ACORD_186"])
    assert iss["resolution"]["mode"] == "none"
    assert iss["resolution"]["add_forms"] == ["ACORD_186"]


def test_add_forms_never_replaces_an_existing_mode():
    """`acord101_required` must keep its narrative box AND gain the form."""
    iss = _issue("advisory", "acord101_required", "Attach ACORD 101 with narrative.",
                 ["ACORD_101"], add_forms=["ACORD_101"])
    assert iss["resolution"]["mode"] == "narrative"
    assert iss["resolution"]["add_forms"] == ["ACORD_101"]


def test_declaring_add_forms_does_not_mutate_the_shared_template():
    """`_copy_resolution` isolates the map; prove `add_forms` cannot leak into it.

    The shallow-copy bug this guards against was real (2026-08-08) and silently
    corrupted every future issue carrying the same code.
    """
    _issue("advisory", "acord101_required", "Attach ACORD 101.", ["ACORD_101"],
           add_forms=["ACORD_101"])
    clean = resolution_for("acord101_required")
    assert "add_forms" not in clean, "add_forms leaked into RESOLUTION_MAP"


# ── The mirror: the grouped view must not lose the affordance ────────────────

def test_add_forms_survives_the_grouped_mirror():
    """`build_structured_from_sources` rebuilds every cross-form issue through
    `make_issue`, which re-derives the resolution from the CODE - and a code
    knows nothing about which forms this package has. Before UX-05 threaded it
    through, the flat editor list had the Add button and the grouped Select
    Forms banners did not: a fix in the wrong layer, passing every unit test."""
    src = _issue("soft_warning", "contractor_missing_acord186",
                 "Operations indicate a contracting business but ACORD 186 is not "
                 "included. Add ACORD 186.", ["ACORD_126", "ACORD_186"],
                 add_forms=["ACORD_186"])
    structured = build_structured_from_sources(cross_issues=[src])
    assert structured, "the mirror dropped the issue entirely"
    assert structured[0]["resolution"]["add_forms"] == ["ACORD_186"]


def test_make_issue_without_add_forms_is_unchanged():
    """Every other emitter must behave exactly as before."""
    a = make_issue("acord125_missing", "soft_warning", "m", ["ACORD_125"])
    assert "add_forms" not in (a["resolution"] or {})


# ── End to end through the real rule engine ─────────────────────────────────

def _contractor_facts():
    return {"operations_description": "General contracting and roofing",
            "gl_class_codes_by_location": [{"code": "91580"}]}


def test_the_reported_case_offers_acord_186():
    """The client's literal screenshot: contractor, GL present, no ACORD 186."""
    issues = run_cross_form_validation(
        _contractor_facts(), {"is_contractor": True, "has_general_liability": True},
        {"ACORD_125", "ACORD_126"},
    )
    hit = [i for i in issues if i.get("code") == "contractor_missing_acord186"]
    assert hit, "the reported rule did not fire on the reported shape"
    assert hit[0]["resolution"]["add_forms"] == ["ACORD_186"]


def test_the_same_package_with_186_selected_offers_nothing():
    issues = run_cross_form_validation(
        _contractor_facts(), {"is_contractor": True, "has_general_liability": True},
        {"ACORD_125", "ACORD_126", "ACORD_186"},
    )
    for i in issues:
        assert "add_forms" not in (i.get("resolution") or {}) or \
               "ACORD_186" not in i["resolution"]["add_forms"]


def test_no_issue_ever_offers_a_form_already_in_the_trigger_set():
    """The invariant, driven over the real engine on a rich package.

    This is the BUG-05 rule restated: a card must only offer what the server
    accepts, and the server refuses to add a form the package already has.
    """
    facts = {
        "applicant_name": "Orbin Contracting LLC",
        "operations_description": "General contracting, roofing and excavation",
        "total_revenue": 2_000_000, "total_payroll": 1_800_000,
        "wc_payroll": 1_750_000, "percent_subcontracted": 60,
        "num_claims": 4, "certificate_holder": "First National Bank",
        "mortgagee_name": "First National Bank",
        "property_building_value": 900_000,
        "gl_class_codes_by_location": [{"code": "91580"}],
        "locations": [{"address": "1 A St"}, {"address": "2 B St"}],
    }
    flags = {"is_contractor": True, "has_general_liability": True,
             "has_property_coverage": True, "has_workers_comp": True,
             "has_umbrella": True, "has_certificate_request": True,
             "has_property_evidence_request": True}
    triggered = {"ACORD_125", "ACORD_126", "ACORD_130", "ACORD_140",
                 "ACORD_131", "ACORD_101", "ACORD_25", "ACORD_28", "ACORD_186"}
    for iss in run_cross_form_validation(facts, flags, triggered):
        offered = set((iss.get("resolution") or {}).get("add_forms") or [])
        assert not (offered & triggered), (
            f"{iss.get('code')} offers {sorted(offered & triggered)} which is already selected"
        )


# ── The write side: the server never trusts the wire ────────────────────────

def test_requested_form_ids_reads_the_stored_issues():
    session = {"cross_issues_last": [
        {"code": "contractor_missing_acord186",
         "resolution": {"mode": "none", "add_forms": ["ACORD_186"]}},
        {"code": "other", "resolution": {"mode": "field", "facts": ["x"]}},
        {"code": "no_resolution"},
        "a legacy plain string",
    ]}
    assert form_addition.requested_form_ids(session) == {"ACORD_186"}


def test_requested_form_ids_is_empty_when_nothing_asks():
    assert form_addition.requested_form_ids({}) == set()
    assert form_addition.requested_form_ids({"cross_issues_last": []}) == set()


def test_package_form_ids_is_the_union_of_selected_and_generated():
    session = {"selected_form_ids": ["ACORD_125"],
               "generated_forms": {"ACORD_126": {}}}
    assert form_addition._package_form_ids(session) == {"ACORD_125", "ACORD_126"}


def test_pre_generation_is_refused_with_the_right_reason(monkeypatch):
    """Before generation the Select Forms list is the correct door, and it is
    free. Refusing keeps one invariant on this path: everything it does is an
    addition to a package that already exists."""
    async def _fake_get(_sid):
        return {"generated_forms": {}, "all_forms": [], "cross_issues_last": []}
    monkeypatch.setattr("repositories.session_repository.get_processing_session",
                        _fake_get, raising=False)
    outcome, _ = asyncio.run(form_addition.add_form_to_session("s1", "ACORD_186"))
    assert outcome == form_addition.NOT_GENERATED_YET


def test_a_form_nobody_asked_for_is_refused(monkeypatch):
    """The owner's ruling, executable: no free-form "add any form later"."""
    async def _fake_get(_sid):
        return {
            "generated_forms": {"ACORD_125": {}},
            "selected_form_ids": ["ACORD_125"],
            "all_forms": [{"form_id": "ACORD_141", "template_file": "x.pdf"}],
            "cross_issues_last": [],
        }
    monkeypatch.setattr("repositories.session_repository.get_processing_session",
                        _fake_get, raising=False)
    outcome, _ = asyncio.run(form_addition.add_form_to_session("s1", "ACORD_141"))
    assert outcome == form_addition.NOT_REQUESTED


def test_a_form_already_in_the_package_is_idempotent(monkeypatch):
    """A double-click must never regenerate a form the producer has edited."""
    async def _fake_get(_sid):
        return {
            "generated_forms": {"ACORD_186": {"form_id": "ACORD_186"}},
            "selected_form_ids": ["ACORD_125", "ACORD_186"],
            "all_forms": [{"form_id": "ACORD_186", "template_file": "x.pdf"}],
            "cross_issues_last": [
                {"resolution": {"add_forms": ["ACORD_186"]}}],
        }
    monkeypatch.setattr("repositories.session_repository.get_processing_session",
                        _fake_get, raising=False)
    outcome, _ = asyncio.run(form_addition.add_form_to_session("s1", "ACORD_186"))
    assert outcome == form_addition.ALREADY_PRESENT


def test_a_form_with_no_template_is_refused(monkeypatch):
    async def _fake_get(_sid):
        return {
            "generated_forms": {"ACORD_125": {}},
            "selected_form_ids": ["ACORD_125"],
            "all_forms": [],                       # not offerable for this session
            "cross_issues_last": [
                {"resolution": {"add_forms": ["ACORD_186"]}}],
        }
    monkeypatch.setattr("repositories.session_repository.get_processing_session",
                        _fake_get, raising=False)
    outcome, _ = asyncio.run(form_addition.add_form_to_session("s1", "ACORD_186"))
    assert outcome == form_addition.UNKNOWN_FORM


def test_a_blank_form_id_is_refused_without_touching_the_session():
    outcome, _ = asyncio.run(form_addition.add_form_to_session("s1", "   "))
    assert outcome == form_addition.UNKNOWN_FORM


def test_every_outcome_has_a_broker_readable_sentence():
    for outcome in (form_addition.ALREADY_PRESENT, form_addition.UNKNOWN_FORM,
                    form_addition.NOT_REQUESTED, form_addition.NOT_GENERATED_YET,
                    form_addition.FAILED):
        msg = form_addition.message_for(outcome)
        assert msg and msg[0].isupper() and msg.endswith((".", "!")), outcome


def test_a_cluster_never_offers_a_form_its_headline_did_not_ask_for():
    """`_make_clusters` borrows a resolution from the first member that has one,
    which need not be the member whose message the cluster PRINTS. Harmless for
    a mode; wrong for a form - the card would show one sentence and offer to
    generate a form a different sentence asked for."""
    from services.issue_registry import build_grouped_view
    headline = _issue("soft_warning", "certificate_requested_but_acord25_missing",
                      "A certificate was requested but ACORD 25 is not in the "
                      "selected forms. Add ACORD 25 to satisfy the request.",
                      ["ACORD_25"])
    headline["resolution"] = {"mode": "none"}          # no add_forms of its own
    other = _issue("soft_warning", "property_evidence_requested_but_acord28_missing",
                   "A mortgagee was detected but ACORD 28 is not in the selected "
                   "forms. Add ACORD 28 to satisfy the lender requirement.",
                   ["ACORD_28"], add_forms=["ACORD_28"])
    view = build_grouped_view(
        build_structured_from_sources(cross_issues=[headline, other]),
        [], [headline["message"], other["message"]],
    )
    clusters = [c for tier in (view.get("warnings") or {}).values() for c in tier] \
        if isinstance(view.get("warnings"), dict) else (view.get("warnings") or [])
    shared = [c for c in clusters if c.get("count", 0) > 1]
    for c in shared:
        offered = (c.get("resolution") or {}).get("add_forms") or []
        own = (c["items"][0].get("resolution") or {}).get("add_forms") or []
        assert offered == own, (
            f"cluster prints {c['primary_message'][:40]!r} but offers {offered}"
        )
    # The per-row control still carries each member's own offer.
    for c in clusters:
        for item in c["items"]:
            if item["code"] == "property_evidence_requested_but_acord28_missing":
                assert item["resolution"]["add_forms"] == ["ACORD_28"]


# ── Conditionality: no rule is ever compulsory ──────────────────────────────
#
# Owner's question, 2026-09-09: "confirm that all forms are not gonna be
# recommended on all the data, and that each form is recommended because of a
# reason". Driven over the REAL engine, one signal at a time.

_PLAIN_FACTS = {
    "applicant_name": "Meridian Office Supply Co",
    "operations_description": "Retail sale of office furniture from a single leased showroom.",
    "gl_each_occurrence": "$1,000,000", "gl_aggregate": "$2,000,000",
}
_PLAIN_FLAGS = {"has_general_liability": True}
_SEL = {"ACORD_125", "ACORD_126"}


def _offers(facts, flags, selected=None):
    out = {}
    for iss in run_cross_form_validation(facts, flags, set(selected or _SEL)):
        for fid in ((iss.get("resolution") or {}).get("add_forms") or []):
            out.setdefault(fid, set()).add(iss.get("code"))
    return out


def test_a_package_with_none_of_the_signals_offers_no_form():
    """The floor. A plain GL retailer must be told nothing is missing."""
    assert _offers(_PLAIN_FACTS, _PLAIN_FLAGS) == {}


def test_each_offer_needs_its_own_signal_and_only_its_own():
    """One signal in, one form offered - never the whole catalogue."""
    cases = [
        ({}, {"is_contractor": True}, "ACORD_186"),
        ({"certificate_holder": "Ridgeline Commercial Properties LP"}, {}, "ACORD_25"),
        ({"mortgagee_name": "Blue Ridge Community Bank, NA"}, {}, "ACORD_28"),
        ({"num_claims": "4"}, {}, "ACORD_101"),
    ]
    for extra_facts, extra_flags, expected in cases:
        got = _offers({**_PLAIN_FACTS, **extra_facts}, {**_PLAIN_FLAGS, **extra_flags})
        assert set(got) == {expected}, f"{extra_facts or extra_flags} -> {set(got)}"


def test_a_signal_under_its_threshold_offers_nothing():
    """`acord101_required` needs MORE THAN two claims - two is not enough."""
    assert _offers({**_PLAIN_FACTS, "num_claims": "2"}, _PLAIN_FLAGS) == {}


def test_the_contractor_offer_needs_the_gl_section_in_the_package():
    """Every rule is form-scoped; none fires on facts alone."""
    facts, flags = _PLAIN_FACTS, {**_PLAIN_FLAGS, "is_contractor": True}
    assert _offers(facts, flags, {"ACORD_125"}) == {}
    assert set(_offers(facts, flags, {"ACORD_125", "ACORD_126"})) == {"ACORD_186"}


def test_every_signal_present_but_every_form_selected_offers_nothing():
    """The BUG-05 contract at the far end: a card only offers what the server
    would accept, and the server refuses a form already in the package."""
    facts = {**_PLAIN_FACTS, "certificate_holder": "L", "mortgagee_name": "B",
             "num_claims": "4"}
    flags = {**_PLAIN_FLAGS, "is_contractor": True}
    everything = {"ACORD_125", "ACORD_126", "ACORD_186", "ACORD_25",
                  "ACORD_28", "ACORD_101"}
    assert _offers(facts, flags, everything) == {}


# ── The PRE-GENERATION half ─────────────────────────────────────────────────
#
# Before generation the cross-form trigger set is the RECOMMENDED forms, not the
# selected ones. So whether an offer appears there depends on `match_forms`, and
# the two can disagree: a rule can want a form the recommender did not suggest.
# Driven over BOTH real engines, because reasoning about it got it wrong once
# (the kit's README claimed "before generation: nothing" and was corrected
# 2026-09-09 when this was actually measured).

def _pre_generation_offers(facts, flags):
    from services.form_service import (
        filter_available_forms, load_all_forms, match_forms,
    )
    available = filter_available_forms(load_all_forms())
    recommended = {r["form_id"] for r in match_forms(facts, flags, available)}
    out = {}
    for iss in run_cross_form_validation(facts, flags, recommended):
        for fid in ((iss.get("resolution") or {}).get("add_forms") or []):
            out.setdefault(fid, set()).add(iss.get("code"))
    return recommended, out


# The kit's own fact shape, so this test cannot drift from what the live run
# does. An earlier version paired `is_contractor` with a RETAIL operations
# sentence - a combination extraction never produces - and `match_forms` then
# failed to recommend ACORD 186, so the test "proved" a pre-generation offer the
# live screen does not show. The fixture has to be the live data shape (D22).
_KIT_FACTS = {
    "applicant_name": "Kestrel Ridge Builders LLC",
    "operations_description": (
        "licensed general contracting firm performing commercial tenant "
        "improvement and light structural renovation work"
    ),
    "gl_each_occurrence": "$1,000,000", "gl_aggregate": "$2,000,000",
    "certificate_holder": "Ridgeline Commercial Properties LP",
    "mortgagee_name": "Blue Ridge Community Bank, NA",
    "num_claims": "4", "property_building_value": 1_750_000,
    "property_bpp_value": 425_000, "percent_subcontracted": 25,
    "gl_class_codes_by_location": [{"code": "91340"}],
}
_KIT_FLAGS = {
    "is_commercial_policy": True, "has_general_liability": True,
    "is_contractor": True, "has_property_coverage": True,
    "has_certificate_request": True,
}


def test_the_pre_generation_offer_is_reachable():
    """It has to be, or the Select-Forms half of the feature is dead code.

    Live-verified 2026-09-09: on the kit document exactly ONE offer survives the
    recommended set - ACORD 25 - because 186 / 28 / 101 are all recommended and
    are therefore not missing yet. That is the screen the owner sees.
    """
    recommended, offers = _pre_generation_offers(_KIT_FACTS, _KIT_FLAGS)
    assert offers, (
        "no add-form offer survives the RECOMMENDED trigger set, so the "
        f"pre-generation button can never render (recommended={sorted(recommended)})"
    )
    assert set(offers) == {"ACORD_25"}, (
        f"kit pre-generation offers changed: {sorted(offers)} "
        f"(recommended={sorted(recommended)}) - update README-HOW-TO-TEST.md"
    )


def test_a_recommended_form_is_never_offered_pre_generation():
    """The same invariant as post-generation, one layer up: an offer for a form
    the producer is already being shown in the list is noise at best and a
    control the server would refuse at worst."""
    recommended, offers = _pre_generation_offers(_KIT_FACTS, _KIT_FLAGS)
    clash = set(offers) & recommended
    assert not clash, f"offered already-recommended {sorted(clash)}"


def test_a_package_needing_nothing_offers_nothing_pre_generation():
    _recommended, offers = _pre_generation_offers(
        _PLAIN_FACTS, {**_PLAIN_FLAGS, "is_commercial_policy": True})
    assert offers == {}


# ── acord101_required must be SATISFIABLE, not just dismissable ─────────────
#
# Found live 2026-09-09: the producer added ACORD 101, typed the explanation,
# and the row stayed. The rule read neither the form list nor the narrative, so
# the only way to clear it was Resolve / Dismiss - overruling a warning instead
# of satisfying it. Same family as BUG-05.

_101_FACTS = {
    "applicant_name": "Kestrel Ridge Builders LLC",
    "operations_description": "licensed general contracting firm performing commercial work",
    "gl_each_occurrence": "$1,000,000", "gl_aggregate": "$2,000,000",
    "num_claims": "4",
}
_101_FLAGS = {"is_commercial_policy": True, "has_general_liability": True}


def _fires_101(facts, selected):
    return any(i.get("code") == "acord101_required"
               for i in run_cross_form_validation(facts, _101_FLAGS, set(selected)))


def test_acord101_advisory_clears_when_the_form_and_the_narrative_are_both_there():
    assert _fires_101(
        {**_101_FACTS, "additional_remarks_text": "Four prior claims, all closed."},
        {"ACORD_125", "ACORD_126", "ACORD_101"},
    ) is False


def test_acord101_advisory_survives_an_empty_form():
    """An ACORD 101 in the package with nothing written on it is not an
    explanation - the message asks for the form WITH narrative."""
    assert _fires_101(_101_FACTS, {"ACORD_125", "ACORD_126", "ACORD_101"}) is True
    assert _fires_101({**_101_FACTS, "additional_remarks_text": "   "},
                      {"ACORD_125", "ACORD_126", "ACORD_101"}) is True


def test_acord101_advisory_survives_a_narrative_with_no_form_to_print_it_on():
    assert _fires_101({**_101_FACTS, "additional_remarks_text": "Explained."},
                      {"ACORD_125", "ACORD_126"}) is True


def test_satisfying_the_acord101_advisory_moves_no_stop_and_so_no_score():
    """It is `advisory`, so it never reaches hard_stops / soft_stops and nothing
    caps on it. Measured rather than argued: the stop lists must be identical
    before and after it clears (D6 - a score move needs Brent first)."""
    from services.cross_form_validator import split_cross_form_issues
    before = split_cross_form_issues(run_cross_form_validation(
        _101_FACTS, _101_FLAGS, {"ACORD_125", "ACORD_126", "ACORD_101"}))
    after = split_cross_form_issues(run_cross_form_validation(
        {**_101_FACTS, "additional_remarks_text": "Four prior claims, all closed."},
        _101_FLAGS, {"ACORD_125", "ACORD_126", "ACORD_101"}))
    assert before[0] == after[0], "hard stops moved"
    assert before[1] == after[1], "soft stops moved"


def test_the_advisory_still_fires_on_a_package_that_has_done_nothing():
    """The floor - satisfying it must not have made it unfirable."""
    assert _fires_101(_101_FACTS, {"ACORD_125", "ACORD_126"}) is True


def test_the_acord101_sentence_names_the_work_that_is_actually_left():
    """The closing sentence must read the state, not recite a fixed string.

    Reported 2026-09-09: with ACORD 101 already in the package the row still
    said "Attach ACORD 101 with narrative", telling the producer to attach a
    form sitting in their own package while the one thing still missing - the
    narrative - was buried mid-sentence.
    """
    def _msg(selected):
        for i in run_cross_form_validation(_101_FACTS, _101_FLAGS, set(selected)):
            if i.get("code") == "acord101_required":
                return i["message"]
        return ""

    absent = _msg({"ACORD_125", "ACORD_126"})
    present = _msg({"ACORD_125", "ACORD_126", "ACORD_101"})

    assert "Attach ACORD 101 with narrative" in absent
    assert "ACORD 101 is in this package" in present
    assert "Attach ACORD 101 with narrative" not in present, (
        "still telling the producer to attach a form that is already there"
    )
    # The REASONS are identical either way - only the ask changes.
    assert absent.split(". ")[0] == present.split(". ")[0]


def test_the_add_button_is_offered_only_by_the_sentence_that_asks_for_the_form():
    """Message and affordance must agree: the "attach the form" wording carries
    the button, the "add the narrative" wording does not."""
    def _issue_for(selected):
        for i in run_cross_form_validation(_101_FACTS, _101_FLAGS, set(selected)):
            if i.get("code") == "acord101_required":
                return i
        return None

    absent = _issue_for({"ACORD_125", "ACORD_126"})
    present = _issue_for({"ACORD_125", "ACORD_126", "ACORD_101"})
    assert (absent["resolution"] or {}).get("add_forms") == ["ACORD_101"]
    assert "add_forms" not in (present["resolution"] or {})


def test_the_harvester_can_read_a_branching_message():
    """Guard on the guard. `_literal_str` returned "" for an `IfExp` before
    2026-09-09, so a state-dependent message would have gone invisible to every
    check in this file while they all reported green - the C25 trap, second
    occurrence (the first was f-strings)."""
    harvested = next((m for c, m, _d, _l in _ISSUE_CALLS if c == "acord101_required"), "")
    assert "Attach ACORD 101 with narrative" in harvested
    assert "add the narrative" in harvested
