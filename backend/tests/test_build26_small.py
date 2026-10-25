"""Build 26 small items (23 Oct 2026, Z36-S).

1. THE RECOMMENDER RE-CHECK AFTER A PRE-FORM ANSWER. The producer answers the
   state question (Z35-C, `state_of_operations`) before forms: the form list
   used to pick up ACORD 137 CO only on the next pipeline re-run. The answer
   doors now re-run the recommender (its logic untouched) and store its list
   - only before forms, only when the answer moved what it recommends. The
   producer's ticks live on the screen and are left alone.

2. ACORD 131's OTHER POLICY rows read the row letter: row A the first other
   underlying line, row B the second, one line never twice. The read used to
   ignore the letter - row B repeated row A and only the post-fill row dedup
   blanked it; two lines left both rows blank beside the coverage list naming
   them.
"""
from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("OPENAI_API_KEY", "sk-offline")
os.environ.setdefault("FIELD_ENCRYPTION_KEY", "kZ0aQ7Yy3pR8mN2vB6xL9tJ4hG1sD5fW8cE0uI3oA7k=")

import repositories.session_repository as sr                          # noqa: E402
import routes.audit_routes as ar                                      # noqa: E402
import routes.form_routes as fr                                       # noqa: E402
import services.arq_service as arq                                    # noqa: E402
import services.audit_service as au                                   # noqa: E402
from models.schemas import ReopenIssueRequest, ResolveIssueRequest    # noqa: E402
from services import form_service as fs                               # noqa: E402
from services import pdf_service as ps                                # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend" / "src"
_SID, _UID = "sid-b26", "u-b26"
CO = "ACORD_137_CO"


# ══ 1. The recommender re-check after a pre-form answer ═══════════════════════

_FACTS = {
    "applicant_name": "Acme Electric LLC", "producer_name": "Best Agency",
    "operations_description": "Electrical contracting",
    "entity_type": "LLC", "contact_name": "Pat Doe",
}
_FLAGS = {"has_auto_coverage": True, "has_general_liability": True}


def _person(value):
    return {"value": value, "source": "producer", "confidence": "filled"}


def _ids(recs):
    return {r["form_id"] for r in recs or []}


def _recs(facts, flags=_FLAGS):
    return fs.match_forms_deterministic(facts, dict(flags), text="")


def _row(**over):
    """A pre-form auto package whose autos' state no document states."""
    row = {
        "user_id": _UID, "facts": copy.deepcopy(_FACTS), "flags": dict(_FLAGS),
        "docs": [], "recommendations": _recs(_FACTS), "account_profile": {},
        "selected_form_ids": [], "generated_forms": {}, "integrity": {},
        "hard_stops": [], "soft_stops": [], "structured_issues": [], "cross_form_issues": [],
        "sqs_history": [], "underwriting_consistency": {}, "underwriting_confirmations": {},
    }
    row.update(over)
    return row


class _Session:
    """The REAL routes and recalculation against an in-memory row; DB and audit
    side effects stubbed."""

    def __init__(self, row):
        self.store = copy.deepcopy(row)

    async def _get(self, _sid, *_a, **_k):
        return copy.deepcopy(self.store)

    async def _upd(self, _sid, payload, delete_facts=None):
        for k, v in (payload or {}).items():
            v = copy.deepcopy(v)
            if k == "facts" and isinstance(v, dict):
                merged = sr.resolve_facts_write(self.store, v, _sid)
                if merged is not None:
                    self.store["facts"] = merged
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

        stubs = [
            (sr, "get_processing_session", self._get), (sr, "upd_processing_session", self._upd),
            (ar, "get_processing_session", self._get), (ar, "log_field_change", _none),
            (ar, "set_issue_status", _true),
            (fr, "get_processing_session", self._get), (fr, "upd_processing_session", self._upd),
            (au, "log_audit_event", _none), (au, "log_sqs_snapshot_if_changed", _none),
            (au, "get_open_recommendations", _empty), (au, "mark_recommendation_resolved", _none),
            (au, "mark_recommendation_answer_recorded", _none),
            (au, "sync_recommendation_cards", _none), (au, "active_score_credits", _no_credits),
        ]
        with contextlib.ExitStack() as stack:
            for mod, name, stub in stubs:
                stack.enter_context(patch.object(mod, name, stub))
            return asyncio.run(coro_fn(*args, **kwargs))

    def fix(self, field, value, issue_id=None):
        return json.loads(self.run(ar.resolve_issue, ResolveIssueRequest(
            session_id=_SID, mode="field", field=field, value=value, issue_id=issue_id),
            current_user={"id": _UID}).body)


def test_the_package_starts_without_137_co():
    assert "ACORD_127" in _ids(_recs(_FACTS))
    assert CO not in _ids(_recs(_FACTS))


def test_the_helper_re_runs_the_recommender_only_when_the_answer_moves_it():
    before = _row()
    after = _row(facts={**_FACTS, "state_of_operations": _person("CO")})
    got = arq.refreshed_pre_form_recommendations(after, before)
    assert got and CO in _ids(got["recommendations"])
    assert isinstance(got["account_profile"], dict)
    # an answer the recommender does not decide on
    unrelated = _row(facts={**_FACTS, "fein": _person("12-3456789")})
    assert arq.refreshed_pre_form_recommendations(unrelated, before) is None
    # no "before" (a door that did not pass one), after forms, forms chosen, review pending
    assert arq.refreshed_pre_form_recommendations(after, None) is None
    assert arq.refreshed_pre_form_recommendations(
        {**after, "generated_forms": {"ACORD_125": {}}}, before) is None
    assert arq.refreshed_pre_form_recommendations(
        {**after, "selected_form_ids": ["ACORD_125"]}, before) is None
    assert arq.refreshed_pre_form_recommendations(
        {**after, "integrity": {"review_required": True}}, before) is None


def test_the_comparison_is_which_forms_never_their_confidences():
    a = [{"form_id": "ACORD_125", "tier": "recommended", "confidence": 0.61}]
    b = [{"form_id": "ACORD_125", "tier": "recommended", "confidence": 0.74}]
    assert arq._recommended_forms_key(a) == arq._recommended_forms_key(b)
    assert arq._recommended_forms_key(a) != arq._recommended_forms_key(
        a + [{"form_id": CO, "tier": "recommended"}])
    assert arq._recommended_forms_key(None) == frozenset()


def test_answering_co_before_forms_adds_137_co_to_the_stored_list():
    s = _Session(_row())
    out = s.fix("state_of_operations", "CO")
    assert out["success"] is True
    assert CO in _ids(s.store["recommendations"])                # stored, as the pipeline stores it
    assert CO in _ids(out["recommendations"])                    # and sent to the form list
    assert isinstance(out["all_available_forms"], list)
    assert isinstance(out["account_profile"], dict)
    # the stops this run scored were scoped to the new list (the 127 state card retires)
    assert not any(i.get("code") == "auto_state_unverified"
                   for i in s.store.get("cross_form_issues") or [])


def test_an_unrelated_answer_leaves_the_stored_list_untouched():
    # A stored list a fresh run would not reproduce (an older row): an answer
    # the recommender does not decide on must never rewrite it.
    sentinel = [{"form_id": "ACORD_125", "tier": "recommended", "confidence": 0.123},
                {"form_id": "ACORD_127", "tier": "recommended", "confidence": 0.456}]
    s = _Session(_row(recommendations=copy.deepcopy(sentinel)))
    out = s.fix("fein", "12-3456789")
    assert out["success"] is True
    assert s.store["recommendations"] == sentinel
    assert "recommendations" not in out and "all_available_forms" not in out


def test_after_forms_nothing_re_runs():
    sentinel = [{"form_id": "ACORD_127", "tier": "recommended", "confidence": 0.5}]
    row = _row(recommendations=copy.deepcopy(sentinel), selected_form_ids=["ACORD_127"],
               generated_forms={"ACORD_127": {"schema": {}, "mapped": {}, "field_state": {},
                                              "confidence": {}}})
    s = _Session(row)
    out = s.fix("state_of_operations", "CO")
    assert out["success"] is True
    assert s.store["recommendations"] == sentinel
    assert "recommendations" not in out


def test_open_again_takes_the_form_back_off_the_list():
    s = _Session(_row())
    assert s.fix("state_of_operations", "CO", issue_id="iss-state")["success"] is True
    assert CO in _ids(s.store["recommendations"])
    out = json.loads(s.run(ar.reopen_issue, ReopenIssueRequest(
        session_id=_SID, issue_id="iss-state", code="auto_state_unverified", message="m"),
        current_user={"id": _UID}).body)
    assert out.get("cleared") is True
    assert CO not in _ids(s.store["recommendations"])
    assert CO not in _ids(out["recommendations"])


def test_every_producer_answer_door_hands_the_recalc_its_before_row():
    src = Path(ar.__file__).read_text(encoding="utf-8")
    assert "recalculate_session_scores(req.session_id, before=_pre_session)" in src      # resolve-issue
    assert "recalculate_session_scores(req.session_id, before=_prev_sess or None)" in src  # answer
    assert "recalculate_session_scores(req.session_id, before=_pre_reopen)" in src      # reopen-issue
    # resolve-issue, reopen-issue and (Z36 review, 23 Oct) the card answer route
    assert src.count("**_refreshed_form_list(") == 3


def test_the_screen_takes_the_new_list_and_keeps_the_ticks():
    jsx = (FRONTEND / "components" / "form" / "AcordModal.jsx").read_text(encoding="utf-8")
    body = jsx[jsx.index("const _applyCrossIssuePanelUpdate = (data) => {"):]
    body = body[:body.index("\n  };\n")]
    assert "if (Array.isArray(data.recommendations)) setRecommendations(data.recommendations);" in body
    assert "if (Array.isArray(data.all_available_forms)) setAllAvailableForms(data.all_available_forms);" in body
    assert "resetFormTicks()" not in body                        # ticks / an unticked 125 stay as they are
    assert "setCheckedFormIds(" not in body and "setDeclined125(" not in body


# ══ 2. ACORD 131 OTHER POLICY rows: each row its own line ═════════════════════

def _line(name, carrier, prem, num):
    return {"line": name, "carrier": carrier, "premium": prem, "policy_number": num,
            "effective_date": "01/01/2026", "expiration_date": "01/01/2027"}


def _tower(extra):
    lines = [_line("Commercial Liability Umbrella", "UMB CO", "$5,000", "UMB-1"),
             _line("Commercial General Liability", "GL CO", "$10,000", "GL-1"),
             _line("Business Auto", "AUTO CO", "$8,000", "BA-1")] + list(extra)
    schedule = [{"line": l["line"], "carrier": l["carrier"], "policy_no": l["policy_number"],
                 "effective_date": l["effective_date"], "expiration_date": l["expiration_date"]}
                for l in lines[1:]]
    return {"_form_id": "ACORD_131", "applicant_name": "Acme LLC",
            "coverage_lines": lines, "underlying_policies": schedule}


_LIQUOR = _line("Liquor Liability", "LIQ CO", "$700", "LL-1")
_POLLUTION = _line("Pollution Liability", "POL CO", "$900", "PL-1")
_ROW = "UnderlyingPolicy_OtherPolicy_{}_{}"


@pytest.fixture(scope="module")
def schema_131():
    return json.load(open(BACKEND / "forms_schemas" / "ACORD_131_schema.json"))


def _stamp(facts, schema):
    report: list = []
    mapped, _conf = ps.map_facts_to_form(copy.deepcopy(facts), schema, form_id="ACORD_131",
                                         raw_text="", allow_llm=False, guard_report=report)
    return mapped, report


def _box(mapped, attr, row):
    v = mapped.get(_ROW.format(attr, row))
    return None if v in (None, "", "UNMATCHED") else v


def test_one_other_line_prints_once_in_row_a(schema_131):
    facts = _tower([_LIQUOR])
    for attr in ("InsurerFullName", "PolicyNumberIdentifier", "PolicyEffectiveDate"):
        assert ps._resolve_underlying_policy_row(_ROW.format(attr, "B"), facts) is None, attr
    mapped, report = _stamp(facts, schema_131)
    assert _box(mapped, "InsurerFullName", "A") == "LIQ CO"
    assert _box(mapped, "PolicyNumberIdentifier", "A") == "LL-1"
    assert _box(mapped, "PolicyTypeDescription", "A") == "Liquor Liability"
    assert _box(mapped, "PolicyEffectiveDate", "A") == "01/01/2026"
    for attr in ("InsurerFullName", "PolicyNumberIdentifier", "PolicyTypeDescription",
                 "PolicyEffectiveDate", "PolicyExpirationDate", "CoverageDescription"):
        assert _box(mapped, attr, "B") is None, attr
    # nothing for the row dedup to clear any more (it was six refused values)
    assert not [r for r in report if "UnderlyingPolicy_OtherPolicy_" in str(r.get("field"))]


def test_two_other_lines_take_row_a_and_row_b(schema_131):
    mapped, report = _stamp(_tower([_LIQUOR, _POLLUTION]), schema_131)
    assert _box(mapped, "InsurerFullName", "A") == "LIQ CO"
    assert _box(mapped, "InsurerFullName", "B") == "POL CO"
    assert _box(mapped, "PolicyNumberIdentifier", "A") == "LL-1"
    assert _box(mapped, "PolicyNumberIdentifier", "B") == "PL-1"
    assert _box(mapped, "PolicyTypeDescription", "B") == "Pollution Liability"
    # one term for both policies: row B keeps its own dates
    assert _box(mapped, "PolicyEffectiveDate", "B") == "01/01/2026"
    assert _box(mapped, "PolicyExpirationDate", "B") == "01/01/2027"
    # the coverage list beside the rows names the same two lines in the same order
    assert mapped.get("UnderlyingCoverage_Coverage_OtherDescription_A") == "Liquor Liability"
    assert mapped.get("UnderlyingCoverage_Coverage_OtherDescription_B") == "Pollution Liability"
    assert not [r for r in report if "UnderlyingPolicy_OtherPolicy_" in str(r.get("field"))]


def test_more_lines_than_rows_or_none_stay_blank(schema_131):
    third = _line("Professional Liability", "PRO CO", "$1,100", "PR-1")
    facts = _tower([_LIQUOR, _POLLUTION, third])
    assert ps._other_policy_row_count() == 2
    assert len(ps._other_underlying_lines(facts["coverage_lines"], facts)) == 3
    for row in ("A", "B"):                     # which two take the rows is not ours to pick
        assert ps._resolve_underlying_policy_row(_ROW.format("InsurerFullName", row), facts) is None
    none = _tower([])
    for row in ("A", "B"):
        assert ps._resolve_underlying_policy_row(_ROW.format("InsurerFullName", row), none) is None


def test_the_excess_copy_keeps_row_b_for_one_line_only():
    box = ps._upper_layer_underlying_line_box
    marker = {"key": "excess", "index": 1, "count": 2, "layer": "excess", "below": {},
              "underlying_lines": [], "base_underlying_policies": _tower([])["underlying_policies"]}
    one = _tower([_LIQUOR])
    one_held = dict(marker, base_underlying_policies=one["underlying_policies"])
    assert box(_ROW.format("InsurerFullName", "B"), one, one_held) == "LIQ CO"
    two = _tower([_LIQUOR, _POLLUTION])
    two_held = dict(marker, base_underlying_policies=two["underlying_policies"])
    assert box(_ROW.format("InsurerFullName", "B"), two, two_held) is None



# ══ Z36 review (23 Oct): the remaining save paths ═════════════════════════════

def test_the_card_answer_route_returns_the_list_it_stored():
    from models.schemas import AnswerRecommendationRequest
    s = _Session(_row())
    out = json.loads(s.run(ar.answer_recommendation, AnswerRecommendationRequest(
        session_id=_SID, rec_id="rec-state", field="state_of_operations", answer="CO"),
        current_user={"id": _UID}).body)
    assert out["success"] is True
    assert CO in _ids(s.store["recommendations"]) and CO in _ids(out["recommendations"])
    out = json.loads(s.run(ar.answer_recommendation, AnswerRecommendationRequest(
        session_id=_SID, rec_id="rec-fein", field="fein", answer="12-3456789"),
        current_user={"id": _UID}).body)
    assert out["success"] is True and "recommendations" not in out


class _Req:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def test_the_producer_table_save_hands_the_recalc_its_before_row_and_returns_the_list():
    import routes.arq_routes as arq_r
    s = _Session(_row())
    seen = {}

    async def _recalc(session_id, *, trigger="recalc", before=None):
        seen["before"] = before
        return {"ok": True, "recommendations_refreshed": True}

    async def _none(*_a, **_k):
        return None

    with patch.object(arq, "recalculate_session_scores", _recalc), \
         patch.object(arq_r, "get_processing_session", s._get), \
         patch.object(au, "log_field_change", _none):
        out = json.loads(s.run(arq_r.save_session_schedule_route, _SID, _Req({
            "schedule_key": "auto_vin_schedule",
            "rows": [{"year": "2020", "make": "Ford", "model": "F-150"}]}),
            current_user={"id": _UID}).body)
    assert out["success"] is True
    assert seen["before"] is not None and "auto_vin_schedule" not in (seen["before"].get("facts") or {})
    assert "recommendations" in out and "all_available_forms" in out


def test_the_client_submit_and_the_policy_lines_keep_the_list_current():
    src = (BACKEND / "routes" / "arq_routes.py").read_text(encoding="utf-8")
    sub = src[src.index('@router.post("/submit/{token}")'):]
    sub = sub[:sub.index("@router.", 1)]
    # The client's answers re-run the recommender before forms (the list is stored
    # for the producer) - and the client's own reply never carries it.
    assert "trigger=CLIENT_ANSWERS_TRIGGER, before=_row_before" in sub
    assert sub.index("_row_before = await get_processing_session(") < sub.index(
        "apply_arq_answers_to_session(")
    assert "refreshed_form_list" not in sub and '"recommendations"' not in sub
    # A pre-form policy-line change re-runs the whole pipeline - the recommender
    # with it - and answers with that list (the confirm-value shape).
    pl_src = (BACKEND / "routes" / "policy_line_routes.py").read_text(encoding="utf-8")
    change = pl_src[pl_src.index("async def _change("):pl_src.index('@router.get("/api/policy-lines/options")')]
    assert "_finalize_pipeline(" in change and "_pre_form_response(session_id, result" in change
    assert '"recommendations": result.get("recommendations")' in pl_src
