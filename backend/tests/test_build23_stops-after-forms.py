"""Build 23 (22 Oct 2026), lane STOPS - 25sepChanges.md part Z32-STOPS.

1. EVERY PACKAGE SCORER TAKES ITS STOPS FROM THE ONE DOOR (Z28 E "named, not
   fixed"). After forms the recalculation behind every answer / resolve / reopen
   / added document (`arq_service.recalculate_session_scores`) and the field
   edit (`form_routes.update_pdf`) built their own lists - field-level, the
   documents' identity conflicts and the cross-form rules - and never the Data
   Consistency picker's open conflicts, the documents' source conflicts or the
   OCR "confirm this field" warnings that generation's door scores with. A stop
   the Review screen and generation held stopped holding its 60 / 85 the first
   time anything was answered or edited after forms. Now every
   `calculate_package_sqs` caller takes hard / soft / cross from
   `stops_now.stops_now` (pinned structurally below); the Clarity route's
   cross-form list too (it fed the legacy 16-rule `cross_validate`).
   Forward-simulated readers, fixed with it: a dismiss credit's form ceiling
   (the session's lists are the package's) and the field edit's credit ceiling.
2. THE COVER'S "CRITICAL - Hard Stops" lists every open hard stop the score
   holds (`ready_blocker_items`), not only the cards typed hard stop - the name
   / FEIN conflicts and the monopolistic private carrier were missing.
3. A SAVE THAT LEAVES THE PROPOSED TERM ALREADY ENDED is refused, through the
   backwards-term door (`validators.term_save_refusal`).
4. Verified: (a) the 126 per-form Exposure reads both GL homes - fixed by Z16,
   pinned here; (b) the "no class codes" warning on GL rows a WC table repeats
   - still open, fixed here: the score asks the stamper's own rule.

Adversarial cases first in every section.
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
import copy
import inspect
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

from models.schemas import (                                                 # noqa: E402
    AnswerRecommendationRequest, PDFUpdateRequest, ResolveIssueRequest,
)
from repositories import session_repository as sr                           # noqa: E402
from routes import audit_routes as ar                                        # noqa: E402
from routes import download_routes as dr                                     # noqa: E402
from routes import form_routes as fr                                         # noqa: E402
from services import arq_service as arq                                      # noqa: E402
from services import audit_service as au                                     # noqa: E402
from services import pdf_service as ps                                       # noqa: E402
from services import sqs_service as sq                                       # noqa: E402
from services import stops_now as sn                                         # noqa: E402
from utils import validators as V                                            # noqa: E402

SCHEMA_125 = json.loads((BACKEND / "forms_schemas" / "ACORD_125_schema.json").read_text(encoding="utf-8"))
SCHEMA_126 = json.loads((BACKEND / "forms_schemas" / "ACORD_126_schema.json").read_text(encoding="utf-8"))


# ══ 1a. The structural pin: every package scorer's stops come from the door ══

_PKG_SCORERS = {"calculate_package_sqs", "_PACKAGE_SCORER"}
_STOP_ARGS = ("hard_stops", "soft_stops", "cross_issues")
_MUTATORS = {"append", "extend", "insert", "remove", "pop", "clear", "update", "__setitem__"}
_SCORER_PARAMS = list(inspect.signature(sq.calculate_package_sqs).parameters)


def _product_files():
    for folder in ("routes", "services"):
        yield from sorted((BACKEND / folder).glob("*.py"))
    yield BACKEND / "worker.py"


def _call_name(func) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _door_names(tree) -> set:
    """`stops_now` and every alias a module imports it under."""
    names = {"stops_now"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("stops_now"):
            names |= {a.asname or a.name for a in node.names if a.name == "stops_now"}
    return names


def _from_door(expr, derived: set, door: set) -> bool:
    """Is this expression the door's own output (or a plain copy / item of it)?
    Adding to it, filtering it or building it elsewhere is not."""
    if isinstance(expr, ast.Call):
        if _call_name(expr.func) in door:
            return True
        if (isinstance(expr.func, ast.Name) and expr.func.id in ("list", "tuple")
                and len(expr.args) == 1 and not expr.keywords):
            return _from_door(expr.args[0], derived, door)
        if isinstance(expr.func, ast.Attribute) and expr.func.attr == "get":
            return _from_door(expr.func.value, derived, door)
        return False
    if isinstance(expr, ast.Name):
        return expr.id in derived
    if isinstance(expr, ast.Subscript):
        return _from_door(expr.value, derived, door)
    if isinstance(expr, ast.BoolOp) and isinstance(expr.op, ast.Or):
        return (_from_door(expr.values[0], derived, door)
                and all(isinstance(v, (ast.List, ast.Tuple)) and not v.elts for v in expr.values[1:]))
    return False


def _bindings(fn) -> dict:
    """{name: [value, ...]} for every binding of a name in `fn` (nested bodies
    included - stricter); None stands for a binding whose value cannot be read
    (a parameter, a loop target, an unpacked call, an augmented assign, a
    mutation of the list in place)."""
    out: dict = {}

    def bind(target, value):
        if isinstance(target, ast.Name):
            out.setdefault(target.id, []).append(value)
        elif isinstance(target, (ast.Tuple, ast.List)):
            vals = value.elts if isinstance(value, (ast.Tuple, ast.List)) and \
                len(value.elts) == len(target.elts) else [None] * len(target.elts)
            for t, v in zip(target.elts, vals):
                bind(t, v)
        elif isinstance(target, (ast.Subscript, ast.Attribute)):
            base = target.value
            while isinstance(base, (ast.Subscript, ast.Attribute)):
                base = base.value
            if isinstance(base, ast.Name):
                out.setdefault(base.id, []).append(None)
        elif isinstance(target, ast.Starred):
            bind(target.value, None)

    for a in list(fn.args.args) + list(fn.args.kwonlyargs) + list(fn.args.posonlyargs):
        out.setdefault(a.arg, []).append(None)
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                bind(t, node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            bind(node.target, node.value)
        elif isinstance(node, ast.AugAssign):
            bind(node.target, None)
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            bind(node.target, None)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    bind(item.optional_vars, None)
        elif isinstance(node, ast.NamedExpr):
            bind(node.target, node.value)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr in _MUTATORS and isinstance(node.func.value, ast.Name)):
            out.setdefault(node.func.value.id, []).append(None)
    return out


def _derived_names(fn, door: set) -> set:
    binds = _bindings(fn)
    derived: set = set()
    while True:
        new = {n for n, vals in binds.items()
               if vals and all(v is not None and _from_door(v, derived, door) for v in vals)}
        if new == derived:
            return derived
        derived = new


def _scorer_argument(call, name):
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    idx = _SCORER_PARAMS.index(name)
    if idx < len(call.args) and not any(isinstance(a, ast.Starred) for a in call.args[:idx + 1]):
        return call.args[idx]
    return None


def _scorer_calls(tree):
    found = []

    def visit(node, stack):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stack = stack + [node]
        if isinstance(node, ast.Call) and _call_name(node.func) in _PKG_SCORERS:
            found.append((node, stack))
        for child in ast.iter_child_nodes(node):
            visit(child, stack)

    visit(tree, [])
    return found


def _offenders(source: str, label: str = "<src>"):
    """(offences, the functions that score the package) for one module."""
    tree = ast.parse(source)
    door = _door_names(tree)
    offences, scorers = [], set()
    for call, stack in _scorer_calls(tree):
        if not stack:
            offences.append(f"{label}:{call.lineno} a package score outside any function")
            continue
        if any(fn.name == "calculate_package_sqs" for fn in stack):
            continue                  # the scorer's own probe re-scores its own inputs
        outer = stack[0]
        scorers.add(outer.name)
        derived = _derived_names(outer, door)
        if any(kw.arg is None for kw in call.keywords):
            offences.append(f"{label}:{call.lineno} {outer.name} passes **kwargs to the scorer")
            continue
        for arg in _STOP_ARGS:
            value = _scorer_argument(call, arg)
            if value is None or not _from_door(value, derived, door):
                offences.append(f"{label}:{call.lineno} {outer.name} -> {arg} not from stops_now")
    return offences, scorers


def test_every_package_scorer_takes_its_stops_from_the_door():
    offences, found = [], set()
    for path in _product_files():
        off, scorers = _offenders(path.read_text(encoding="utf-8"), path.name)
        offences += off
        found |= {(path.name, s) for s in scorers}
    # The harvester sees the real callers - an empty harvest would pass vacuously.
    assert {("form_routes.py", "select_forms_bulk"), ("form_routes.py", "update_pdf"),
            ("form_routes.py", "clarity_analyze"), ("arq_service.py", "recalculate_session_scores"),
            ("worker.py", "_process_form_generation_job"),
            ("sqs_service.py", "score_package_pre_generation"),
            ("sqs_service.py", "package_sqs_without_forms")} <= found, found
    assert not offences, "a package scorer builds its own stops:\n" + "\n".join(offences)


_BAD_OWN_LISTS = '''
def recalc(proc):
    from services.sqs_service import evaluate_stops, calculate_package_sqs
    hard, soft = evaluate_stops(proc["facts"], proc["flags"])
    return calculate_package_sqs(facts={}, flags={}, form_results=[], cross_issues=[],
                                 hard_stops=hard, soft_stops=soft, session_data=proc)
'''

_BAD_DOOR_PLUS_OWN = '''
def edit(session):
    from services.stops_now import stops_now
    door = stops_now(session, None, pre_form=False)
    hard = list(door["hard"])
    hard.append("my own stop")
    return calculate_package_sqs(facts={}, flags={}, form_results=[], cross_issues=door["cross_issues"],
                                 hard_stops=hard, soft_stops=door["soft"], session_data=session)
'''

_BAD_LEGACY_CROSS = '''
def clarity(session):
    from services.stops_now import stops_now as _sn
    st = _sn(session, None, pre_form=True)
    cross = cross_validate(session["facts"], {}, [])
    return calculate_package_sqs(facts={}, flags={}, form_results=[], cross_issues=cross,
                                 hard_stops=st["hard"], soft_stops=st["soft"], session_data=session)
'''

_BAD_STORED = '''
def worker(session):
    from services.stops_now import stops_now
    st = stops_now(session, None, pre_form=False)
    return calculate_package_sqs(facts={}, flags={}, form_results=[], cross_issues=st["cross_issues"],
                                 hard_stops=session.get("hard_stops"), soft_stops=st["soft"],
                                 session_data=session)
'''

_BAD_REASSIGNED = '''
def recalc(session, pre_form):
    from services.stops_now import stops_now
    st = stops_now(session, None, pre_form=False)
    hard = st["hard"]
    if pre_form:
        hard = session["hard_stops"]
    return _PACKAGE_SCORER(facts={}, flags={}, form_results=[], cross_issues=st["cross_issues"],
                           hard_stops=hard, soft_stops=st["soft"], session_data=session)
'''

_GOOD_POSITIONAL_ALIAS = '''
def gen(session):
    from services.stops_now import stops_now as _door
    st = _door(session, None, pre_form=False)
    hard, soft = st["hard"], st["soft"]
    cross = list(st["cross_issues"])
    return calculate_package_sqs(session["facts"], {}, [], cross, hard, soft, session)
'''


@pytest.mark.parametrize("src", [_BAD_OWN_LISTS, _BAD_DOOR_PLUS_OWN, _BAD_LEGACY_CROSS,
                                 _BAD_STORED, _BAD_REASSIGNED],
                         ids=["own-lists", "door-plus-own", "legacy-cross", "stored-list", "reassigned"])
def test_the_pin_bites_on_every_shape_of_the_defect(src):
    offences, scorers = _offenders(src)
    assert scorers and offences, src


def test_the_pin_passes_the_doors_own_shapes():
    offences, scorers = _offenders(_GOOD_POSITIONAL_ALIAS)
    assert scorers == {"gen"} and offences == []


# ══ 1b. The recalculation after forms keeps every stop the door holds ════════

def F(v, src="ai"):
    return {"value": v, "confidence": "ai_high", "source": src}


def P(v):
    return {"value": v, "confidence": "filled", "source": "producer"}


_NOW = datetime.now()
_EFF = (_NOW + timedelta(days=30)).strftime("%m/%d/%Y")
_EXP = (_NOW + timedelta(days=395)).strftime("%m/%d/%Y")
_NARRATIVE = (
    "Panel Test LLC is a residential carpentry and remodelling contractor founded in 2013 and "
    "operating for twelve years in Warren, Michigan. The company employs fourteen full time "
    "carpenters and supervisors, performs framing, trim and kitchen remodelling for homeowners, "
    "and subcontracts no structural work. Safety program: weekly toolbox talks, fall protection "
    "on every roof job, OSHA 10 training for every employee and a written safety manual. No "
    "losses in the past five years; prior carrier Acme Mutual, no cancellations or non-renewals. "
    "Revenue $2,500,000 with payroll $800,000; limits requested $1,000,000 / $2,000,000 "
    "occurrence form.")
_BASE = {
    "applicant_name": F("PANEL TEST LLC"), "mailing_address": F("100 Main St, Warren, MI 48089"),
    "fein": F("84-2210987"), "effective_date": F(_EFF), "expiration_date": F(_EXP),
    "entity_type": F("LLC"), "producer_name": F("PANEL BROKERAGE"),
    "operations_description": F("Residential carpentry and remodelling contractor"),
    "total_revenue": F("2500000"), "total_payroll": F("800000"), "num_employees": F("14"),
    "naics_code": F("238160"), "gl_each_occurrence": F("1000000"), "gl_aggregate": F("2000000"),
    "gl_limits": F("each occurrence $1,000,000; aggregate $2,000,000"),
    "gl_class_codes_by_location": F("91580 Carpentry - residential"), "gl_form_type": F("occurrence"),
    "years_in_business": F("12"), "lines_of_business": F(["General Liability"]),
    "contact_name": F("Jordan Reyes"), "contact_email": F("jordan@paneltest.example"),
    "contact_phone": F("2485551212"), "sic_code": F("1751"),
    "loss_history_no_prior_losses_indicator": P("Yes"),
    "additional_remarks_text": P(_NARRATIVE),
}
_REVENUE_CONFLICT = {
    "review_required": True, "assessed_keys": ["total_revenue"],
    "fields": [{"fact_key": "total_revenue", "label": "Gross Sales / Annual Revenue",
                "review_required": True,
                "values": [{"display": "$2,500,000"}, {"display": "$3,000,000"}]}]}
_NAME_CONFLICT = {
    "review_required": True, "assessed_keys": ["applicant_name"],
    "fields": [{"fact_key": "applicant_name", "label": "Applicant / Named Insured",
                "review_required": True,
                "values": [{"display": "PANEL TEST LLC"}, {"display": "OTHER BUILDERS INC"}]}]}


def _doc(i, **facts):
    return {"doc_id": f"d{i}", "filename": f"doc{i}.pdf", "doc_type": "declarations",
            "facts": {**copy.deepcopy(_BASE), **facts}}


def _row(**over):
    """A generated GL package whose own score sits above 85 with nothing open
    (raw 92), so any 85 / 60 the stops hold shows on the number."""
    row = {
        "user_id": "u-b23", "facts": copy.deepcopy(_BASE),
        "flags": {"has_general_liability": True, "no_prior_losses": True},
        "docs": [_doc(1), _doc(2)], "recommendations": [{"form_id": "ACORD_125"}],
        "selected_form_ids": ["ACORD_125"], "integrity": {},
        "generated_forms": {"ACORD_125": {
            "form_id": "ACORD_125", "form_name": "ACORD 125",
            "form": {"template_file": "__no_template_in_tests__.pdf"},
            "schema": SCHEMA_125, "mapped": {k: "x" for k in SCHEMA_125},
            "field_state": {k: "x" for k in SCHEMA_125},
            "confidence": {k: "producer" for k in SCHEMA_125}, "sqs": {}}},
        "hard_stops": [], "soft_stops": [], "structured_issues": [], "sqs_history": [],
        "underwriting_consistency": {}, "underwriting_confirmations": {},
    }
    row.update(over)
    return row


class _Session:
    """The REAL recalculation and routes against an in-memory row; every DB /
    audit side effect is stubbed."""

    def __init__(self, row):
        self.store = copy.deepcopy(row)
        self.writes = 0

    async def _get(self, _sid, *_a, **_k):
        return copy.deepcopy(self.store)

    async def _upd(self, _sid, payload, delete_facts=None):
        self.writes += 1
        for k, v in (payload or {}).items():
            v = copy.deepcopy(v)
            if k == "facts" and isinstance(v, dict):
                self.store.setdefault("facts", {}).update(
                    {fk: fv for fk, fv in v.items() if fv not in (None, "", [], {})})
            elif k == "generated_forms" and isinstance(v, dict):
                gen = self.store.setdefault("generated_forms", {})
                for fid, data in v.items():
                    gen[fid] = {**(gen.get(fid) or {}), **data} if isinstance(data, dict) else data
            else:
                self.store[k] = v
        for k in (delete_facts or []):
            self.store.get("facts", {}).pop(k, None)
        return True

    def run(self, coro_fn, *args, **kwargs):
        async def _none(*_a, **_k):
            return None

        async def _empty(*_a, **_k):
            return []

        async def _true(*_a, **_k):
            return True

        async def _no_credits(*_a, **_k):
            return 0, []

        async def _token(*_a, **_k):
            return "tok"

        stubs = [
            (sr, "get_processing_session", self._get), (sr, "upd_processing_session", self._upd),
            (ar, "get_processing_session", self._get), (ar, "log_field_change", _none),
            (ar, "set_issue_status", _true),
            (fr, "get_processing_session", self._get), (fr, "upd_processing_session", self._upd),
            (fr, "check_payment_access", lambda *_a, **_k: None), (fr, "try_acquire_heavy", _token),
            (fr, "release_heavy", _none), (fr, "log_field_change", _none),
            (fr, "sync_recommendation_cards", _none), (fr, "run_and_log_field_qa", _none),
            (fr, "run_and_log_field_mapping_check", _none),
            (au, "log_audit_event", _none), (au, "log_sqs_snapshot_if_changed", _none),
            (au, "get_open_recommendations", _empty), (au, "mark_recommendation_resolved", _none),
            (au, "mark_recommendation_answer_recorded", _none),
            (au, "sync_recommendation_cards", _none), (au, "active_score_credits", _no_credits),
        ]
        with contextlib.ExitStack() as stack:
            for mod, name, stub in stubs:
                stack.enter_context(patch.object(mod, name, stub))
            return asyncio.run(coro_fn(*args, **kwargs))

    def recalc(self):
        return self.run(arq.recalculate_session_scores, "sid-b23")

    def edit(self, updates):
        req = PDFUpdateRequest(session_id="sid-b23", field_updates={"__form_id__": "ACORD_125", **updates})
        return json.loads(self.run(fr.update_pdf, req, current_user={"id": "u-b23"}).body)

    def package(self):
        return self.store.get("package_sqs") or {}


def _generation_recipe(store):
    """What generation scores this row with: the door's lists, the stored forms."""
    door = sn.stops_now(store, None, pre_form=False)
    return sq.calculate_package_sqs(
        facts=store["facts"], flags=store["flags"],
        form_results=[fd["sqs"] for fd in store["generated_forms"].values() if fd.get("sqs")],
        cross_issues=door["cross_issues"], hard_stops=door["hard"], soft_stops=door["soft"],
        session_data=store, _probe=True)


def test_the_fixture_scores_above_85_with_nothing_open():
    """Guard for the guard: the clean row's raw score is above the 85, so the
    tests below see a held number, not a coincidence."""
    s = _Session(_row())
    s.recalc()
    pkg = s.package()
    assert pkg["cap_applied"] is None and pkg["package_sqs_score"] > 85
    assert s.store["hard_stops"] == [] and s.store["soft_stops"] == []


@pytest.mark.parametrize("over, held, fragment", [
    ({"underwriting_consistency": _REVENUE_CONFLICT}, 85, "Gross Sales / Annual Revenue: documents disagree"),
    ({"underwriting_consistency": _NAME_CONFLICT}, 60, "Applicant / Named Insured: documents disagree"),
    ({"docs": [dict(_doc(1), manual_confirmation_required=["fein"]), _doc(2)]}, 85,
     "Low OCR confidence on critical field"),
    ({"docs": [_doc(1, contact_email=F("a@x.example")), _doc(2, contact_email=F("b@y.example"))]}, 85,
     "Conflicting values for Contact Email"),
], ids=["picker-warning", "picker-name-hard-stop", "ocr-confirm", "source-conflict"])
def test_a_recalculation_after_forms_keeps_the_stop(over, held, fragment):
    s = _Session(_row(**over))
    s.recalc()
    pkg = s.package()
    assert pkg["raw_sqs_score"] > 85
    assert pkg["cap_applied"] == held and pkg["package_sqs_score"] == min(pkg["raw_sqs_score"], held)
    assert str(pkg["cap_reason"]).startswith(fragment)
    listed = s.store["hard_stops"] if held == 60 else s.store["soft_stops"]
    assert any(m.startswith(fragment) for m in listed)
    # the stored lists ARE the door's - the display cache says what the score used
    door = sn.stops_now(s.store, None, pre_form=False)
    assert s.store["hard_stops"] == door["hard"] and s.store["soft_stops"] == door["soft"]
    # ...and the number is generation's recipe on the same row
    assert pkg["package_sqs_score"] == _generation_recipe(s.store)["package_sqs_score"]
    if held == 60:
        assert any(m.startswith(fragment) for m in pkg["ready_blockers"])


def test_one_form_is_never_scored_with_the_packages_own_stops():
    """Spec 10: the picker, source and OCR stops cap the PACKAGE only."""
    s = _Session(_row(underwriting_consistency=_REVENUE_CONFLICT))
    s.recalc()
    form = s.store["generated_forms"]["ACORD_125"]["sqs"]
    assert form["cap_applied"] is None and form["sqs_score"] > 85


def test_a_persons_answer_after_forms_clears_the_ocr_stop():
    s = _Session(_row(docs=[dict(_doc(1), manual_confirmation_required=["fein"]), _doc(2)]))
    s.recalc()
    assert s.package()["cap_applied"] == 85
    s.store["facts"]["fein"] = P("84-2210987")
    s.recalc()
    assert s.package()["cap_applied"] is None
    assert not any("Low OCR confidence" in m for m in s.store["soft_stops"])


def test_the_pre_form_recalculation_reads_the_same_door():
    row = _row(generated_forms={}, selected_form_ids=[], underwriting_consistency=_REVENUE_CONFLICT)
    s = _Session(row)
    s.recalc()
    door = sn.stops_now(s.store, ["ACORD_125"], pre_form=True)
    assert s.store["hard_stops"] == door["hard"] and s.store["soft_stops"] == door["soft"]
    assert s.package()["package_sqs_score"] == sq.current_package_sqs(copy.deepcopy(s.store))["package_sqs_score"]


def test_the_stored_messages_are_worded_as_the_upload_words_them():
    """The door shapes evaluate_stops' sentences once (`Fix:` line, the address
    source); the recalculation used to store them raw after forms."""
    row = _row()
    row["facts"].pop("gl_class_codes_by_location")                     # a stop with no Fix line
    row["facts"]["mailing_address"] = F("100 Main St, Warren, MI")     # an address-format stop
    for d in row["docs"]:
        d["facts"]["mailing_address"] = F("100 Main St, Warren, MI")
    s = _Session(row)
    s.recalc()
    raw_hard, raw_soft = sq.evaluate_stops(s.store["facts"], s.store["flags"])
    assert any("Fix: " not in m for m in raw_hard + raw_soft)
    assert any(m.startswith("Address missing ZIP code") for m in raw_soft)
    stored = s.store["hard_stops"] + s.store["soft_stops"]
    assert stored
    for m in stored:
        assert "Fix: " in m, m
        assert m.count("(Source:") <= 1, m
    assert any(m.startswith("Address missing ZIP code") and "(Source: doc1.pdf, doc2.pdf." in m
               for m in s.store["soft_stops"])


# ══ 1c. The field edit keeps them too ═══════════════════════════════════════

def test_an_unrelated_field_edit_keeps_the_data_consistency_warning():
    s = _Session(_row(underwriting_consistency=_REVENUE_CONFLICT))
    s.recalc()
    stored = (list(s.store["hard_stops"]), list(s.store["soft_stops"]))
    out = s.edit({"Form_CompletionDate_A": _NOW.strftime("%m/%d/%Y")})
    pkg = out["package_sqs"]
    assert pkg["cap_applied"] == 85 and pkg["package_sqs_score"] == 85
    assert str(pkg["cap_reason"]).startswith("Gross Sales / Annual Revenue: documents disagree")
    # nothing moved, so the save stores what it found and runs no second rescore
    assert (s.store["hard_stops"], s.store["soft_stops"]) == stored
    assert "forms_sqs" not in out


def test_a_field_edit_that_supplies_the_ocr_field_settles_it_on_that_save():
    s = _Session(_row(docs=[dict(_doc(1), manual_confirmation_required=["fein"]), _doc(2)]))
    s.recalc()
    assert s.package()["cap_applied"] == 85
    out = s.edit({"NamedInsured_TaxIdentifier_A": "84-2210987"})
    assert out["package_sqs"]["cap_applied"] is None
    assert not any("Low OCR confidence" in m for m in s.store["soft_stops"])
    assert "forms_sqs" in out                      # the stops moved: every form refreshed


def test_the_edits_credit_ceiling_for_a_form_is_the_forms_own():
    src = inspect.getsource(fr.update_pdf)
    assert "_form_cap, _ = _resolve_cap(_re_hard, _re_soft)" in src
    assert "_form_cap, _ = _resolve_cap(fresh_hard_stops, fresh_soft_stops)" not in src


# ══ 1d. A dismiss credit's form ceiling is the form's own ════════════════════

def _run_dismiss_credit(monkeypatch, pkg, form, stops):
    class _Conn:
        def __init__(self):
            self.writes = []

        async def fetchrow(self, sql, *a):
            return dict(zip(("hard_total", "soft_total", "hard_cross", "soft_cross"), stops))

        async def fetchval(self, sql, *a):
            for key in ("open_hard_stops", "raw_sqs_score", "package_sqs_score", "cap_applied"):
                if f"'{key}')::int" in sql:
                    return pkg.get(key)
            return {} if "data->'facts'" in sql else None

        async def fetch(self, sql, *a):
            return [dict({"stored_cap": None}, **form, form_id="ACORD_125", form_credits=6)]

        async def execute(self, sql, *a):
            self.writes.append((sql, a))

    conn = _Conn()

    class _Ctx:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(ar, "get_pool", lambda: type("P", (), {"acquire": lambda self: _Ctx()})())

    async def _credits(session_id, facts=None):
        return 6, [{"rec_id": "r1", "score_impact": 6}]

    monkeypatch.setattr(ar, "active_score_credits", _credits)
    out = asyncio.run(ar._apply_dismiss_score_credit("s", "r1", 85, 6))
    forms = [a for sql, a in conn.writes if "generated_forms" in sql]
    return out, forms


def test_a_package_warning_never_lowers_an_uncapped_form(monkeypatch):
    """ADVERSARIAL - the live shape after forms: one OCR / picker / source
    warning open on the PACKAGE (stored soft list), a form its own scorer left
    uncapped at 92. The credit used to clamp the form to the package's 85."""
    out, forms = _run_dismiss_credit(
        monkeypatch, pkg={"package_sqs_score": 85, "raw_sqs_score": 92, "open_hard_stops": 0,
                          "cap_applied": 85},
        form={"score": 92, "raw_score": 92, "open_hard": 0, "stored_cap": None}, stops=(0, 1, 0, 0))
    assert out["new_package_sqs_score"] == 85                 # the package keeps its 85
    [form] = forms
    assert form[1] == 98                                      # the form: 92 + 6, not 85


def test_a_forms_own_ceiling_still_holds(monkeypatch):
    out, forms = _run_dismiss_credit(
        monkeypatch, pkg={"package_sqs_score": 85, "raw_sqs_score": 92, "cap_applied": 85},
        form={"score": 85, "raw_score": 92, "open_hard": 0, "stored_cap": 85}, stops=(0, 1, 0, 0))
    assert forms == []                                        # 85 -> 85: nothing to write
    out, forms = _run_dismiss_credit(
        monkeypatch, pkg={"package_sqs_score": 60, "raw_sqs_score": 92, "cap_applied": 60},
        form={"score": 60, "raw_score": 92, "open_hard": 1, "stored_cap": 60}, stops=(1, 0, 0, 0))
    assert forms == []


def test_a_legacy_form_payload_keeps_the_counted_ceiling(monkeypatch):
    out, forms = _run_dismiss_credit(
        monkeypatch, pkg={"package_sqs_score": 80},
        form={"score": 80, "raw_score": None, "open_hard": None, "stored_cap": None}, stops=(0, 1, 0, 0))
    [form] = forms
    assert form[1] == 85                                      # 80 + 6 held at the counted 85


# ══ 2. The cover's CRITICAL list reads the score's open hard stops ═══════════

_NAME_STOP = ("Applicant / Named Insured: documents disagree (PANEL TEST LLC, OTHER BUILDERS INC). "
              "Fix: Confirm the correct value to apply it across forms.")
_MONO_STOP = ("Monopolistic WC state (ND/OH/WA/WY) requires the state fund - private-carrier WC "
              "cannot be quoted. Remove private-carrier request or acknowledge state-fund handling.")
_EFF_STOP = "ACORD 125 minimum field missing: Proposed effective date Fix: Review and correct this before proceeding."


def _card(rec_id, field, message, kind="hard_stop", impact=None):
    return {"rec_id": rec_id, "field": field, "message": message,
            "recommendation_type": kind, "score_impact": impact}


def test_a_hard_stop_that_is_no_card_reaches_the_cover():
    """ADVERSARIAL - the two kinds the cover missed: no card names them."""
    pkg = {"ready_blocker_items": sq._cap_stop_items([_NAME_STOP, _MONO_STOP]),
           "ready_blockers": [_NAME_STOP, _MONO_STOP]}
    hard, soft = dr._split_open_recs([], package_sqs=pkg)
    assert hard == [_NAME_STOP, _MONO_STOP] and soft == []


def test_a_card_a_stop_covers_is_that_stops_line_and_keeps_its_points():
    pkg = {"ready_blocker_items": sq._cap_stop_items([_EFF_STOP, _NAME_STOP])}
    cards = [_card("rec_eff", "effective_date", "Proposed effective date", impact=13),
             _card("rec_min_cope", "locations", "Required: occupancy", impact=4),
             _card("rec_x", "total_revenue", "Gross sales", kind="soft_warning", impact=3)]
    hard, soft = dr._split_open_recs(cards, package_sqs=pkg)
    assert hard == [f"{_EFF_STOP} (-13 pts)", _NAME_STOP, "Required: occupancy (-4 pts)"]
    assert soft == ["Gross sales (up to +3 pts)"]


def test_a_score_without_readiness_fields_keeps_the_cards():
    cards = [_card("rec_eff", "effective_date", "Proposed effective date", impact=13)]
    for pkg in (None, {}, {"package_sqs_score": 60}):
        assert dr._split_open_recs(cards, package_sqs=pkg)[0] == ["Proposed effective date (-13 pts)"]
    # nothing open: the cards no stop covers, as before
    assert dr._split_open_recs(cards, package_sqs={"ready_blocker_items": []})[0] == \
        ["Proposed effective date (-13 pts)"]


def test_one_stop_is_listed_once():
    item = sq._cap_stop_items([_NAME_STOP])[0]
    hard, _soft = dr._split_open_recs([], package_sqs={"ready_blocker_items": [item, dict(item)]})
    assert hard == [_NAME_STOP]
    # a card carrying the stop's own sentence is that line too
    hard, _soft = dr._split_open_recs([_card("rec_dup", None, _NAME_STOP, impact=9)],
                                      package_sqs={"ready_blocker_items": [item]})
    assert hard == [f"{_NAME_STOP} (-9 pts)"]


def test_the_cover_lists_the_scores_own_hard_stops_end_to_end():
    facts = copy.deepcopy(_BASE)
    facts["wc_state_fund_acknowledged"] = P("No - private carrier")
    flags = {"has_general_liability": True, "has_workers_comp": True, "wc_has_monopolistic_state": True,
             "no_prior_losses": True}
    session = _row(facts=facts, flags=flags, underwriting_consistency=_NAME_CONFLICT)
    door = sn.stops_now(session, None, pre_form=False)
    pkg = sq.calculate_package_sqs(facts=facts, flags=flags, form_results=[],
                                   cross_issues=door["cross_issues"], hard_stops=door["hard"],
                                   soft_stops=door["soft"], session_data=session)
    assert pkg["open_hard_stops"] >= 2
    hard, _soft = dr._split_open_recs([], package_sqs=pkg)
    assert any(m.startswith("Applicant / Named Insured: documents disagree") for m in hard)
    assert any(m.startswith("Monopolistic WC state (ND/OH/WA/WY) requires the state fund") for m in hard)
    assert len(hard) == pkg["open_hard_stops"]


def test_both_cover_downloads_hand_the_package_score_to_the_list():
    src = inspect.getsource(dr)
    assert src.count("_live_card_points(proc_session.get(\"generated_forms\")), package_sqs=_pkg_now)") == 2
    body = inspect.getsource(dr.download_all)
    assert body.index("_pkg_now = _package_score_now(") < body.index("_split_open_recs(")


# ══ 3. A save that leaves the proposed term already ended is refused ═════════

_TODAY = datetime(2026, 10, 22).date()


def _d(days):
    return (datetime(2026, 10, 22) + timedelta(days=days)).strftime("%m/%d/%Y")


_DOC_ENDED = {"effective_date": F(_d(-465)), "expiration_date": F(_d(-100))}


def _refuse(stored, supplied):
    return V.term_save_refusal(stored, supplied, today=_TODAY)


def test_a_term_in_force_is_never_refused():
    """ADVERSARIAL - the spec's own line: a past EFFECTIVE date with a future
    expiration is a term under way, not an ended one."""
    assert _refuse({}, {"effective_date": _d(-200), "expiration_date": _d(165)}) == ""
    assert _refuse(_DOC_ENDED, {"expiration_date": _d(30)}) == ""          # extend the doc's term
    assert _refuse({}, {"effective_date": _d(-364), "expiration_date": _d(0)}) == ""   # ends today
    assert _refuse({}, {"effective_date": _d(0), "expiration_date": _d(365)}) == ""
    assert _refuse({}, {"effective_date": _d(30), "expiration_date": _d(395)}) == ""


def test_confirming_a_documents_ended_term_is_refused_box_by_box():
    save = {"effective_date": _d(-465), "expiration_date": _d(-100)}
    for field in save:
        assert _refuse(_DOC_ENDED, save) == V.TERM_ENDED_REFUSAL, field
    assert _refuse({}, {"effective_date": _d(-366), "expiration_date": _d(-1)}) == V.TERM_ENDED_REFUSAL


def test_one_typed_date_that_leaves_the_stored_expiration_ended_is_refused():
    assert _refuse(_DOC_ENDED, {"effective_date": _d(-300)}) == V.TERM_ENDED_REFUSAL
    assert _refuse(_DOC_ENDED, {"expiration_date": _d(-1)}) == V.TERM_ENDED_REFUSAL


def test_a_backwards_pair_keeps_its_own_sentence():
    assert _refuse({}, {"effective_date": _d(-10), "expiration_date": _d(-20)}) == V.TERM_BACKWARDS_REFUSAL
    assert _refuse(_DOC_ENDED, {"effective_date": _d(10)}) == V.TERM_BACKWARDS_REFUSAL


def test_the_save_is_judged_after_its_own_follow():
    """A typed effective date takes a DERIVED expiration with it
    (`follow_proposed_expiration`) - the term the save leaves is judged, never
    the stale derived date it replaces (neither as ended nor as backwards)."""
    derived = {"value": _d(-100), "confidence": "low_confidence", "source": "derived",
               "derivation": {"rule": "proposed_expiration_follows_effective"}}
    stored = {"effective_date": P(_d(-465)), "expiration_date": derived,
              "prior_effective_date": F(_d(-830)), "prior_expiration_date": F(_d(-465))}
    assert _refuse(stored, {"effective_date": _d(20)}) == ""
    # ...while a STATED expiration is never followed: the pair is backwards
    stated = dict(stored, expiration_date=F(_d(-100)))
    assert _refuse(stated, {"effective_date": _d(20)}) == V.TERM_BACKWARDS_REFUSAL


@pytest.mark.parametrize("stored, supplied", [
    (_DOC_ENDED, {}),                                             # no term date in the save
    (_DOC_ENDED, {"umbrella_expiration_date": _d(-30)}),          # not the proposed term
    (_DOC_ENDED, {"effective_date": "not a date"}),               # the format rule's job
    (_DOC_ENDED, {"effective_date": "   "}),
    ({}, {"effective_date": _d(-30)}),                            # nothing to compare yet
    ({"expiration_date": F("sometime next year")}, {"effective_date": _d(-30)}),
])
def test_nothing_to_judge_is_never_refused(stored, supplied):
    assert _refuse(stored, supplied) == ""


def test_the_sentence_is_plain():
    assert V.TERM_ENDED_REFUSAL == "The proposed policy term has already ended. Enter the upcoming term's dates."
    assert not any(ch in V.TERM_ENDED_REFUSAL for ch in ("—", "–"))


def test_both_answer_doors_refuse_an_ended_term_and_write_nothing():
    stored = _row()
    stored["facts"].update({"effective_date": F(_d(-465)), "expiration_date": F(_d(-100))})
    s = _Session(stored)
    ended = (_NOW - timedelta(days=1)).strftime("%m/%d/%Y")
    out = json.loads(s.run(ar.resolve_issue, ResolveIssueRequest(
        session_id="sid-b23", mode="field", field="expiration_date", value=ended,
        code="legacy_policy_term_expired", issue_id="iss",
        same_save={"expiration_date": ended}), current_user={"id": "u-b23"}).body)
    assert out == {"success": False, "validation_error": V.TERM_ENDED_REFUSAL}
    out = json.loads(s.run(ar.answer_recommendation, AnswerRecommendationRequest(
        session_id="sid-b23", rec_id="rec_exp", field="expiration_date", answer=ended),
        current_user={"id": "u-b23"}).body)
    assert out == {"success": False, "validation_error": V.TERM_ENDED_REFUSAL}
    assert s.writes == 0
    # ...and the upcoming term goes through the same door
    upcoming = (_NOW + timedelta(days=300)).strftime("%m/%d/%Y")
    assert ar._term_save_refusal(stored["facts"], "expiration_date", upcoming) == ""


def test_the_route_door_is_the_validators_door():
    src = inspect.getsource(ar._term_save_refusal)
    assert "term_save_refusal(stored_facts or {}, supplied)" in src
    assert not hasattr(V, "backwards_term_refusal")           # one door, renamed - no second copy


# ══ 4. Verified: (a) the 126 Exposure block, (b) GL codes a WC table repeats ═

_GL_FLAGS = {"has_general_liability": True}


def _gl_row(code, **extra):
    return {"class_code": code, "classification": "Heating and Air Conditioning Systems",
            "premium_basis": "Payroll", "exposure_amount": "250000", **extra}


def _126_exposure(facts):
    res = sq.calculate_sqs(facts, _GL_FLAGS, {}, SCHEMA_126, ["ACORD_126"], [], [], 0, form_id="ACORD_126")
    return res["breakdown"]["exposure_consistency"]


def test_a_full_gl_schedule_answers_the_126_exposure_block():
    """(a) FIXED by Z16 (14 Oct): the block reads `gl_class_codes_present`, both
    homes. A full schedule in `gl_class_code_schedule` alone used to score 60."""
    base = {"gl_class_code_schedule": [_gl_row("91580"), _gl_row("91585")],
            "total_payroll": "800000", "operations_description": "HVAC contractor",
            "gl_limits": "$1,000,000 / $2,000,000"}
    assert _126_exposure(base) == 100
    assert _126_exposure(dict(base, gl_class_code_schedule=[])) == 60     # control: no codes at all


def test_a_gl_code_a_wc_table_repeats_is_still_gl():
    """(b) STILL OPEN until today, fixed: the score dropped a five-digit GL code
    because the WC table repeats it (the extraction misfile of three stored
    kits) - while the 126 printed it. One rule now, the stamper's."""
    facts = {"gl_class_code_schedule": [_gl_row("91580")],
             "wc_class_codes": [{"code": "91580", "description": "Heating and Air Conditioning Systems",
                                 "payroll": "250000"}],
             "operations_description": "HVAC contractor"}
    assert sq.gl_class_codes(facts) == ["91580"] and sq.gl_class_codes_present(facts)
    hard, soft = sq.evaluate_stops(facts, _GL_FLAGS)
    assert not any("no class codes found" in m for m in hard + soft)


def test_a_wc_class_filed_under_gl_is_still_another_lines():
    """ADVERSARIAL - Brent: "Do not substitute WC class codes for GL codes"."""
    facts = {"gl_class_code_schedule": [_gl_row("5183"), _gl_row("8810")],
             "wc_class_codes": [{"code": "5183"}, {"code": "8810"}]}
    assert sq.gl_class_codes(facts) == [] and not sq.gl_class_codes_present(facts)
    _hard, soft = sq.evaluate_stops(facts, _GL_FLAGS)
    assert any("no class codes found" in m for m in soft)
    # a person's saved window still speaks for itself (unchanged)
    assert "_human_schedules" not in facts


@pytest.mark.parametrize("code", ["91580", "92478", "5183", "8810", "7383", "01499", "123456", "9158"])
def test_the_score_and_the_stamper_give_one_answer(code):
    """One door: for every shape, a code another line's table repeats counts for
    the score exactly when the 126 keeps its row."""
    facts = {"gl_class_code_schedule": [_gl_row(code)], "wc_class_codes": [{"code": code}]}
    elsewhere = ps._gl_codes_owned_elsewhere(facts)
    stamper_keeps = not ps._gl_row_is_another_lines(facts["gl_class_code_schedule"][0], elsewhere)
    assert (code in sq.gl_class_codes(facts)) is stamper_keeps
    assert stamper_keeps is (len(code) == 5 and code.isdigit())


def test_a_gl_code_no_other_line_claims_is_untouched():
    facts = {"gl_class_code_schedule": [_gl_row("5183")]}            # four digits, no WC table
    assert sq.gl_class_codes(facts) == ["5183"]
    assert sq.gl_class_codes({}) == [] and sq.gl_class_codes(None) == []
