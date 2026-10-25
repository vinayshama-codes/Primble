"""The narrative questionnaire page - backend (Brent's attachment A, 23 Oct 2026;
25sepChanges.md Z36-Q).

Drives the REAL routes (`routes/questionnaire_routes.py`), the real producer
answer door (`audit_routes.resolve_issue` -> `arq_service.apply_producer_answer_to_session`)
and the real scorer against an in-memory session row that merges writes the way
`upd_processing_session` does. No database, no network: the carrier narrative's
model call is stubbed, and the suite runs with CARRIER_NARRATIVE=0.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

os.environ.setdefault("FIELD_ENCRYPTION_KEY", "kZ0aQ7Yy3pR8mN2vB6xL9tJ4hG1sD5fW8cE0uI3oA7k=")

import repositories.session_repository as sr          # noqa: E402
import routes.arq_routes as arq_r                     # noqa: E402
import routes.audit_routes as ar                      # noqa: E402
import routes.questionnaire_routes as qr              # noqa: E402
import services.arq_service as arq                    # noqa: E402
import services.audit_service as au                   # noqa: E402
from services import questionnaire as qn              # noqa: E402
from services.fact_registry import FACT_REGISTRY      # noqa: E402

_SID = "sid-qn-23oct"
_UID = "u-qn-23oct"
_USER = {"id": _UID, "email": "p@agency.test", "full_name": "Pat Producer", "payment_status": "ok"}


def _mdY(dt):
    return dt.strftime("%m/%d/%Y")


def _doc_env(value):
    """A value the documents print (verified against the text at merge)."""
    return {"value": value, "confidence": "ai_high", "verified_in_text": True}


def _producer(value):
    return {"value": value, "source": "producer", "confidence": "filled"}


_DOCS = [
    {"doc_id": "d1", "filename": "Package Dec.pdf", "doc_type": "dec_page",
     "text": ("[Document page 1]\nNamed Insured: Acme Electric LLC\nMailing address: 1 Main St, "
              "Denver, CO 80202\n[Document page 2]\nAnnual revenue $1,200,000\n"),
     "facts": {"applicant_name": "Acme Electric LLC", "total_revenue": "$1,200,000"}},
    {"doc_id": "d2", "filename": "Application.pdf", "doc_type": "application",
     "text": "Applicant: Acme Electric LLC\nRevenue: $2,400,000\n",
     "facts": {"applicant_name": "Acme Electric LLC", "total_revenue": "$2,400,000"}},
]


def _row(**over):
    """A pre-form package with a current, producer-typed term (no term cap)."""
    facts = {
        "producer_name": _producer("Best Agency"),
        "applicant_name": _doc_env("Acme Electric LLC"),
        "mailing_address": _doc_env("1 Main St, Denver, CO 80202"),
        "lines_of_business": ["General Liability"],
        "entity_type": _producer("LLC"),
        "contact_name": _producer("Pat Doe"), "contact_phone": _producer("303-555-0100"),
        "contact_email": _producer("pat@acme.test"),
        "fein": _producer("12-3456789"),
        "operations_description": _doc_env("Electrical contracting"),
        "total_revenue": _doc_env("$1,200,000"),
        "num_employees": _producer("12"),
        "naics_code": _producer("238210"),
        "effective_date": _producer(_mdY(datetime.now() - timedelta(days=165))),
        "expiration_date": _producer(_mdY(datetime.now() + timedelta(days=200))),
    }
    base = {
        "user_id": _UID, "facts": facts, "flags": {"has_general_liability": True},
        "hard_stops": [], "soft_stops": [], "recommendations": [{"form_id": "ACORD_125"}],
        "cross_form_issues": [], "structured_issues": [], "docs": copy.deepcopy(_DOCS),
        "integrity": {}, "generated_forms": {}, "selected_form_ids": [],
        "underwriting_consistency": {},
    }
    for k, v in over.items():
        if k == "facts":
            base["facts"].update(v)
        else:
            base[k] = v
    return base


class _Session:
    """The real routes against an in-memory row that merges writes like the
    store: facts additively (last write per key, empty values skipped),
    `delete_facts` after the merge, generated forms per form, every other key
    replaced."""

    def __init__(self, row):
        self.store = copy.deepcopy(row)

    async def _get(self, _sid, *a, **k):
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
                    if fid in gen and isinstance(gen[fid], dict):
                        gen[fid].update(data)
                    else:
                        gen[fid] = data
            else:
                self.store[k] = v
        for k in (delete_facts or []):
            self.store.get("facts", {}).pop(k, None)
        return True

    def run(self, coro_fn, *args, extra=(), **kwargs):
        async def _none(*_a, **_k):
            return None

        async def _empty(*_a, **_k):
            return []

        async def _no_credits(*_a, **_k):
            return 0, []

        async def _true(*_a, **_k):
            return True

        import routes.form_routes as fr
        patches = [
            patch.object(sr, "get_processing_session", self._get),
            patch.object(sr, "upd_processing_session", self._upd),
            patch.object(ar, "get_processing_session", self._get),
            patch.object(fr, "get_processing_session", self._get),
            patch.object(fr, "upd_processing_session", self._upd),
            patch.object(ar, "log_field_change", _none),
            patch.object(ar, "set_issue_status", _true),
            patch.object(au, "mark_recommendation_answer_recorded", _none),
            patch.object(au, "log_audit_event", _none),
            patch.object(au, "log_sqs_snapshot_if_changed", _none),
            patch.object(au, "get_open_recommendations", _empty),
            patch.object(au, "mark_recommendation_resolved", _none),
            patch.object(au, "sync_recommendation_cards", _none),
            patch.object(au, "active_score_credits", _no_credits),
            *extra,
        ]
        for p in patches:
            p.start()
        try:
            return asyncio.run(coro_fn(*args, **kwargs))
        finally:
            for p in reversed(patches):
                p.stop()

    def recalc(self):
        return self.run(arq.recalculate_session_scores, _SID)

    def body(self, resp):
        return json.loads(resp.body)

    def page(self, all_sections=False):
        return self.body(self.run(qr.get_questionnaire, _SID, all=all_sections, current_user=_USER))

    def act(self, qid, action, value=None, **kw):
        req = qr.QuestionnaireAnswerRequest(question_id=qid, action=action, value=value, **kw)
        return self.body(self.run(qr.answer_question, _SID, req, current_user=_USER))

    def score(self):
        return (self.store.get("package_sqs") or {}).get("package_sqs_score")

    def raw(self):
        return (self.store.get("package_sqs") or {}).get("raw_sqs_score")


def _fresh(**over):
    s = _Session(_row(**over))
    s.recalc()
    return s


def _q(page, qid):
    return qn.find_rendered(page, qid)


def _section_ids(page):
    return [s["id"] for s in page["sections"]]


# ══ The questions as data ═════════════════════════════════════════════════════

def test_every_question_maps_to_a_fact_the_system_knows():
    from services.schedule_capture import SCHEDULE_DEFS
    canon = arq._canonical_fact_keys()
    assert len(qn.QUESTIONS) == sum(len(s.questions) for s in qn.SECTIONS)       # ids unique
    assert [s.id for s in qn.SECTIONS] == list("ABCDEFGHIJKL")
    for q in qn.QUESTIONS.values():
        assert q.answer_type in qn.ANSWER_TYPES, q.id
        assert "—" not in q.text + q.group, q.id                            # no em-dash in UI copy
        if q.computed:
            assert q.fact is None
            continue
        if q.table:
            assert q.table in SCHEDULE_DEFS and q.answer_type == "table", q.id
            continue
        assert q.fact in canon, f"{q.id} reads {q.fact}, which no door writes"
    existing, new = qn.mapped_facts()
    assert len(existing) >= 55 and len(new) == 65


def test_new_facts_are_registered_unscored_unextracted_and_typed_as_asked():
    from services.answer_semantics import _declared_kind, _registry_entry
    from services.lob_canon import fact_line_family
    from services.pdf_service import _GAP_FILL_FACTS_EXCLUDE_PREFIX
    want = {"date": "date", "number": "integer", "currency": "currency"}
    _existing, new = qn.mapped_facts()
    for key in new + [qn.NARRATIVE_FACT]:
        e = FACT_REGISTRY[key]
        assert e["validate"] is None and e["tier"] is None and e["forms"] == set(), key
        assert fact_line_family(key) is None, key           # never evidence of a coverage line
        if key != "contact_title":
            assert key.startswith(_GAP_FILL_FACTS_EXCLUDE_PREFIX)
    for q in qn.QUESTIONS.values():
        if q.fact in new:
            assert _declared_kind(q.fact, _registry_entry(q.fact)) == want.get(q.answer_type), q.id


def test_the_gap_fill_facts_block_skips_questionnaire_facts():
    import inspect
    from services import pdf_service
    src = inspect.getsource(pdf_service)
    assert "str(_k).startswith(_GAP_FILL_FACTS_EXCLUDE_PREFIX)" in src


# ══ Which sections show ═══════════════════════════════════════════════════════

def test_core_sections_always_show_and_modules_follow_the_requested_lines():
    page = qn.build_page(_row(flags={}, facts={"lines_of_business": []}))
    assert _section_ids(page) == ["A", "B", "C", "K", "L"]          # K.4: manual additions
    assert [q["id"] for q in page["sections"][3]["questions"]] == ["K.4"]

    every = qn.build_page(_row(
        flags={"has_general_liability": True, "has_workers_comp": True, "has_auto_coverage": True,
               "has_property_coverage": True, "has_umbrella": True},
        facts={"lines_of_business": ["General Liability", "Cyber Liability",
                                     "Employment Practices Liability", "Crime"]}))
    assert _section_ids(every) == list("ABCDEFGHIJKL")
    j = [q["id"] for s in every["sections"] if s["id"] == "J" for q in s["questions"]]
    assert j == ["J.1"]                                             # EPLI only, not D&O / E&O / EBL
    k = [q["id"] for s in every["sections"] if s["id"] == "K" for q in s["questions"]]
    assert k == ["K.2a", "K.2b", "K.4"]


def test_a_declined_line_hides_its_module_and_a_selected_form_shows_it():
    declined = qn.build_page(_row(flags={"has_workers_comp": True},
                                  facts={"_lines_not_requested": ["workers_comp"],
                                         "lines_of_business": []}))
    assert "E" not in _section_ids(declined)
    applied = qn.build_page(_row(flags={}, facts={"lines_of_business": []},
                                 selected_form_ids=["ACORD_125", "ACORD_130"]))
    assert "E" in _section_ids(applied)


def test_contractor_shows_d_and_the_contractor_items_without_gl():
    page = qn.build_page(_row(flags={"is_contractor": True}, facts={"lines_of_business": []}))
    assert "D" in _section_ids(page)
    assert _q(page, "B.3b") and _q(page, "B.3d")
    plain = qn.build_page(_row(flags={}, facts={"lines_of_business": []}))
    assert _q(plain, "B.3b") is None and "D" not in _section_ids(plain)


def test_all_sections_is_the_manual_addition():
    page = qn.build_page(_row(flags={}, facts={"lines_of_business": []}), all_sections=True)
    assert _section_ids(page) == list("ABCDEFGHIJKL")
    assert page["counts"]["total"] == len(qn.QUESTIONS)


# ══ Prefill and states ════════════════════════════════════════════════════════

def _conflict_row():
    return _row(facts={"_uw_conflict_keys": ["total_revenue"]},
                underwriting_consistency={"fields": [{
                    "fact_key": "total_revenue", "status": "conflict", "review_required": True,
                    "conflict_scope": [],
                    "values": [{"display": "$1,200,000", "sources": [{"filename": "Package Dec.pdf"}]},
                               {"display": "$2,400,000", "sources": [{"filename": "Application.pdf"}]}]}]})


def test_prefill_states_sources_and_both_conflicting_values():
    page = qn.build_page(_row(
        facts={"dba_name": {"value": "Acme Sparks", "confidence": "ai_high"},          # model only
               "contact_title": {"value": "Owner", "source": "client_arq", "confidence": "client_arq"},
               "expiration_date": {"value": "07/15/2027", "source": "derived"},
               "cyber_controls_mfa": False}),
        all_sections=True)
    a1 = _q(page, "A.1a")
    assert a1["state"] == "extracted" and not a1["needs_input"]
    assert a1["sources"][0] == {"document": "Package Dec.pdf", "page": 1, "value": "Acme Electric LLC"}
    assert _q(page, "A.1d")["state"] == "producer_confirmed"
    assert _q(page, "A.1e")["state"] == "insured_confirmed"
    assert _q(page, "A.1b")["state"] == "unverified" and _q(page, "A.1b")["needs_input"]
    assert _q(page, "A.3e")["state"] == "missing" and _q(page, "A.3e")["needs_input"]
    # A blank control is not "False" (Brent, section I).
    assert _q(page, "I.2a")["state"] == "missing" and _q(page, "I.2a")["display_value"] is None
    # The FEIN is a secure field.
    fein = _q(page, "B.1b")
    assert fein["value"] is None and fein["display_value"] == "**-***6789" and fein["critical"]

    conflict = qn.build_page(_conflict_row())
    rev = _q(conflict, "B.4a")
    assert rev["state"] == "conflicting" and rev["needs_input"]
    assert {(c["value"], c["document"]) for c in rev["conflict_values"]} == {
        ("$1,200,000", "Package Dec.pdf"), ("$2,400,000", "Application.pdf")}
    assert conflict["counts"]["needs_input"] >= 1


def test_a_fallback_fact_prefills_and_the_open_items_list_names_what_needs_confirming():
    page = qn.build_page(_row(flags={"has_auto_coverage": True},
                              facts={"auto_garaging_addresses": ["100 Yard Rd, Denver, CO"]}))
    g = _q(page, "F.2a")
    assert g["prefilled_from"] == "auto_garaging_addresses"
    assert g["display_value"] == "100 Yard Rd, Denver, CO" and g["fact"] == "qn_garaging_locations"
    a5 = _q(qn.build_page(_conflict_row()), "A.5")
    assert a5["computed"] and not a5["needs_input"]
    assert "B.4a" in a5["display_value"] and "(conflicting)" in a5["display_value"]


# ══ Each action through the real door ═════════════════════════════════════════

@pytest.mark.parametrize("forms", ["pre-form", "editor"])
def test_an_answer_goes_through_the_producer_door_and_moves_the_score(forms):
    over = {}
    if forms == "editor":
        over = {"generated_forms": {"ACORD_125": {
            "mapped": {"NamedInsured_FullName_A": "Acme Electric LLC"},
            "confidence": {"NamedInsured_FullName_A": "ai_high"},
            "schema": {"NamedInsured_FullName_A": {"ft": "/Tx", "tu": "Enter name"}}}},
            "selected_form_ids": ["ACORD_125"]}
    s = _fresh(**over)
    before, before_raw = s.score(), s.raw()
    assert _q(s.page(), "B.1c")["state"] == "missing"
    out = s.act("B.1c", "answer", "12")
    assert out["ok"] is True and out["error"] is None
    assert s.store["facts"]["years_in_business"]["source"] == "producer"
    assert out["question"]["state"] == "producer_confirmed" and out["question"]["display_value"] == "12"
    assert s.raw() > before_raw and s.score() >= before
    assert out["package_sqs"]["package_sqs_score"] == s.score() or forms == "pre-form"
    assert "grouped_issues" in out and "counts" in out and "updated_forms" in out


def test_a_refused_answer_says_why_and_writes_nothing():
    s = _fresh()
    out = s.act("B.3a", "answer", "Electrical 70%, Solar 20%")          # does not total 100%
    assert out["ok"] is False and "100" in out["error"]
    assert "qn_operations_mix" not in s.store["facts"]
    out = s.act("A.3e", "answer", "TBD")                                 # a non-answer is refused
    assert out["ok"] is False and "qn_decision_deadline" not in s.store["facts"]
    out = s.act("B.3a", "answer", "Electrical 70%, Solar 30%")
    assert out["ok"] is True and s.store["facts"]["qn_operations_mix"]["source"] == "producer"


def test_confirm_records_user_confirmed_evidence_and_keeps_the_value():
    s = _fresh()
    value_before = s.store["facts"]["operations_description"]["value"]
    out = s.act("B.2a", "confirm")
    assert out["ok"] is True
    env = s.store["facts"]["operations_description"]
    assert env["value"] == value_before
    assert env["evidence_state"] == "user_confirmed" and env["evidence_actor"] == "producer"
    assert env["confirmed_by"] == "producer"
    assert out["question"]["state"] == "producer_confirmed"
    # Nothing to confirm on a blank; a disagreement is chosen, never confirmed.
    assert s.act("A.3e", "confirm")["ok"] is False
    c = _Session(_conflict_row())
    c.recalc()
    assert c.act("B.4a", "confirm")["ok"] is False


def test_unknown_pending_and_na_are_statuses_never_values_never_scored():
    s = _fresh()
    facts_before, score_before, raw_before = copy.deepcopy(s.store["facts"]), s.score(), s.raw()
    for qid, action in (("B.1c", "unknown"), ("B.4b", "pending"), ("A.1b", "not_applicable")):
        out = s.act(qid, action, owner="insured", note="asked on the call")
        assert out["ok"] is True and out["question"]["state"] == action
        assert out["question"]["status"]["owner"] == "insured"
    assert s.store["facts"] == facts_before                       # no value written
    s.recalc()
    assert (s.score(), s.raw()) == (score_before, raw_before)      # and nothing scored
    stored = s.store[qn.STATUS_KEY]
    assert set(stored) == {"B.1c", "B.4b", "A.1b"} and stored["B.1c"]["status"] == "unknown"
    # Answering the item takes the status off.
    assert s.act("B.1c", "answer", "8")["ok"] is True
    assert "B.1c" not in s.store[qn.STATUS_KEY]
    assert _q(s.page(), "B.1c")["state"] == "producer_confirmed"


def test_a_status_yields_once_the_fact_changes_some_other_way():
    s = _fresh()
    s.act("B.4b", "pending", owner="insured")
    s.store["facts"]["qn_prior_year_revenue"] = {"value": "$1,000,000", "source": "client_arq",
                                                  "confidence": "client_arq"}
    assert _q(s.page(), "B.4b")["state"] == "insured_confirmed"


def test_an_answer_to_a_disagreement_goes_through_data_consistency():
    s = _Session(_conflict_row())
    s.recalc()
    calls = []

    async def _dc(req, current_user=None):
        calls.append((req.fact_key, req.value, req.scope))
        return None

    import routes.form_routes as fr
    out = s.body(s.run(qr.answer_question, _SID,
                       qr.QuestionnaireAnswerRequest(question_id="B.4a", action="answer", value="$2,400,000"),
                       current_user=_USER,
                       extra=(patch.object(fr, "underwriting_confirm_value", _dc),)))
    assert out["ok"] is True
    assert calls == [("total_revenue", "$2,400,000", None)]
    assert "total_revenue" in s.store["facts"] and s.store["facts"]["total_revenue"]["value"] == "$1,200,000"


# ══ G is per building ═════════════════════════════════════════════════════════

_TWO_BUILDINGS = [
    {"address_line1": "1 Main St", "address_city": "Denver", "address_state": "CO",
     "construction_type": "Frame", "year_built": "1999", "building_value": "500000",
     "location_number": "1", "building_number": "1"},
    {"address_line1": "2 Oak St", "address_city": "Denver", "address_state": "CO",
     "location_number": "2", "building_number": "1"},
]


def test_property_questions_are_per_building_and_never_one_value_for_all():
    s = _fresh(flags={"has_general_liability": True, "has_property_coverage": True},
               facts={"property_locations": copy.deepcopy(_TWO_BUILDINGS)})
    g2 = _q(s.page(), "G.2a")
    assert g2["state"] == "missing" and g2["critical"] and g2["table_key"] == "property_locations"
    per = g2["per_building"]
    assert len(per) == 2 and per[0]["missing"] == [] and per[1]["missing"] == ["Construction", "Year built"]
    # The page posts the whole table, as the fix window does (a row left out is
    # a row deleted); only building 2's view cells were typed - and only its
    # own view's columns, so every other cell comes from its stored row.
    rows_in = []
    for r in g2["value"]:
        if r["address_line1"] == "2 Oak St":
            rows_in.append({"_row_id": r["_row_id"], "address_line1": "2 Oak St",
                            "construction_type": "Joisted Masonry", "year_built": "2004"})
        else:
            rows_in.append({k: r[k] for k in ("_row_id", *qn.QUESTIONS["G.2a"].columns) if k in r})
    out = s.act("G.2a", "answer", rows_in)
    assert out["ok"] is True, out["error"]
    rows = {r["address_line1"]: r for r in s.store["facts"]["property_locations"]
            if isinstance(r, dict)}
    assert rows["1 Main St"]["year_built"] == "1999" and rows["1 Main St"]["construction_type"] == "Frame"
    assert str(rows["2 Oak St"]["year_built"]) == "2004"
    assert rows["2 Oak St"]["construction_type"] == "Joisted Masonry"
    assert rows["1 Main St"].get("building_value") in ("500000", 500000, "$500,000")   # untouched
    assert out["question"]["state"] == "producer_confirmed"


def test_an_extended_period_of_indemnity_is_never_a_period_of_restoration():
    docs = copy.deepcopy(_DOCS)
    docs[0]["text"] += "[Document page 3]\nEXTENDED PERIOD OF INDEMNITY 540 DAYS\n"
    s = _fresh(flags={"has_property_coverage": True}, docs=docs,
               facts={"period_of_restoration": {"value": "540 days", "confidence": "ai_high"}})
    g6 = _q(s.page(), "G.6")
    assert g6["state"] == "unverified" and "Extended Period of Indemnity" in g6["help"]
    out = s.act("G.6", "answer", "Extended period of indemnity - 540 days")
    assert out["ok"] is False and "not a Period of Restoration" in out["error"]
    assert s.act("G.6", "answer", "12 months")["ok"] is True


# ══ Send to client - the existing ARQ door ════════════════════════════════════

def test_send_to_client_goes_through_the_arq_send_door():
    s = _fresh(flags={"has_general_liability": True, "has_property_coverage": True},
               facts={"property_locations": copy.deepcopy(_TWO_BUILDINGS)})
    stored = {}

    async def _create(**kw):
        stored.update(kw)
        return {"arq_id": "arq-1", "token": "tok", "expires_at": "2026-11-01"}

    async def _none(*_a, **_k):
        return None

    extra = (patch.object(arq_r, "get_processing_session", s._get),
             patch.object(arq_r, "create_arq_session", _create),
             patch.object(arq_r, "send_arq_email", lambda **_k: True),
             patch.object(arq_r, "record_event", _none))
    req = qr.QuestionnaireSendRequest(question_ids=["A.1a", "B.1b", "L.1", "C.3", "G.2a", "G.3a"])
    out = s.body(s.run(qr.send_to_client, _SID, req, current_user=_USER, extra=extra))
    assert out["ok"] is True and out["link"].endswith("/questionnaire/tok") and out["sent"] == 4
    assert stored["client_email"] == "pat@acme.test"                  # the insured's contact on file
    names = [q["field_name"] for q in stored["questions"]]
    assert names == ["applicant_name", "qn_safety_program", "schedule::property_locations"]
    assert "fein" not in names and "qn_submission_reason" not in names   # secure / producer-only
    confirm = stored["questions"][0]
    assert confirm["confirm"] is True and confirm["current_value"] == "Acme Electric LLC"
    statuses = s.store[qn.STATUS_KEY]
    assert set(statuses) == {"A.1a", "C.3", "G.2a", "G.3a"}
    assert all(v["status"] == "pending" and v["owner"] == "insured" for v in statuses.values())
    # One mailer: the route's own body is the shared function.
    import inspect
    assert "send_questions_to_client(" in inspect.getsource(arq_r.send_arq)


def test_send_to_client_needs_an_insured_question_and_an_address():
    s = _fresh(facts={"contact_email": None})
    s.store["facts"].pop("contact_email", None)
    out = s.body(s.run(qr.send_to_client, _SID,
                       qr.QuestionnaireSendRequest(question_ids=["L.1"]), current_user=_USER))
    assert out["ok"] is False and out["link"] is None
    out = s.body(s.run(qr.send_to_client, _SID,
                       qr.QuestionnaireSendRequest(question_ids=["C.3"]), current_user=_USER))
    assert out["ok"] is False and "e-mail" in out["error"]


# ══ The carrier narrative ═════════════════════════════════════════════════════

def _stub_llm(reply, seen):
    async def _chat(model, messages, **kw):
        seen.append(messages)
        return json.dumps(reply)
    return _chat


def test_the_narrative_is_written_from_extracted_and_confirmed_answers_only(monkeypatch):
    monkeypatch.setenv("CARRIER_NARRATIVE", "1")
    row = _conflict_row()
    row["facts"]["dba_name"] = {"value": "Unverified Sparks DBA", "confidence": "ai_high"}
    row["facts"]["qn_safety_program"] = _producer("Weekly toolbox talks and quarterly site audits.")
    s = _Session(row)
    s.recalc()
    seen = []
    reply = {"sections": [
        {"heading": "Account overview",
         "text": "Acme Electric LLC is an electrical contractor. It holds 7 patents. "
                 "The safety program runs weekly toolbox talks.",
         "cites": ["A.1a", "B.2a", "C.3"]},
        {"heading": "Invented", "text": "Nothing here is cited.", "cites": ["Z.9"]},
    ]}
    import config.settings as cs
    monkeypatch.setattr(cs, "groq_chat", _stub_llm(reply, seen))
    out = s.body(s.run(qr.draft_narrative, _SID, current_user=_USER))
    assert out["ok"] is True
    prompt = seen[0][1]["content"]
    assert "Acme Electric LLC" in prompt and "Weekly toolbox talks" in prompt
    assert "Unverified Sparks DBA" not in prompt              # unverified - never written from
    assert "$2,400,000" not in prompt and "[B.4a]" not in prompt   # conflicting - never written from
    assert "12-3456789" not in prompt                         # the secure field
    text = out["text"]
    assert text.startswith("ACCOUNT OVERVIEW") and "weekly toolbox talks" in text
    assert "7 patents" not in text                            # a number no answer states is dropped
    assert "Nothing here is cited" not in text                # an uncited section is dropped
    assert out["narrative"]["state"] == "draft"
    blob_raw = s.store[qn.NARRATIVE_KEY]
    assert isinstance(blob_raw, str) and "Acme" not in blob_raw   # encrypted at rest
    assert qn.NARRATIVE_FACT not in s.store["facts"]          # a draft never prints


def test_the_narrative_switch_makes_no_call(monkeypatch):
    monkeypatch.setenv("CARRIER_NARRATIVE", "0")
    import config.settings as cs

    async def _boom(*_a, **_k):
        raise AssertionError("no model call with CARRIER_NARRATIVE=0")
    monkeypatch.setattr(cs, "groq_chat", _boom)
    s = _fresh()
    out = s.body(s.run(qr.draft_narrative, _SID, current_user=_USER))
    assert out["ok"] is False and "switched off" in out["error"]


def test_an_approved_narrative_prints_on_acord_101():
    from services.pdf_service import _acord101_blocks, _resolve_acord101_box
    s = _fresh()
    text = "ACCOUNT OVERVIEW\nAcme Electric LLC is an electrical contractor in Denver."
    out = s.body(s.run(qr.approve_narrative, _SID, qr.NarrativeApproveRequest(text=text),
                       current_user=_USER))
    assert out["ok"] is True and out["narrative"]["state"] == "approved"
    assert out["narrative"]["text"] == text and out["narrative"]["approved_at"]
    fact = s.store["facts"][qn.NARRATIVE_FACT]
    assert fact["value"] == text and fact["source"] == "producer"
    blocks = _acord101_blocks(s.store["facts"])
    assert blocks[0] == ("ACORD_125", "SUBMISSION NARRATIVE\n" + text)
    box = _resolve_acord101_box("AdditionalRemark_RemarkText_A",
                                {**s.store["facts"], "_form_id": "ACORD_101"})
    assert box.startswith("SUBMISSION NARRATIVE\n" + text)
    page = s.page()
    assert page["narrative"]["state"] == "approved"


def test_an_approved_narrative_restamps_a_generated_acord_101():
    form = {"mapped": {"AdditionalRemark_RemarkText_A": ""},
            "confidence": {},
            "schema": {"AdditionalRemark_RemarkText_A": {"ft": "/Tx", "tu": "Enter text: Remarks."}}}
    s = _fresh(generated_forms={"ACORD_101": form}, selected_form_ids=["ACORD_101"])
    text = "ACCOUNT OVERVIEW\nAcme Electric LLC is an electrical contractor in Denver."
    out = s.body(s.run(qr.approve_narrative, _SID, qr.NarrativeApproveRequest(text=text),
                       current_user=_USER))
    assert out["ok"] is True and out["on_acord_101"] is True
    box = s.store["generated_forms"]["ACORD_101"]["mapped"]["AdditionalRemark_RemarkText_A"]
    assert "SUBMISSION NARRATIVE" in box and "electrical contractor in Denver" in box


# ══ What the frontend reads (coordinator, 23 Oct) ═════════════════════════════

def test_a_table_question_carries_the_fix_window_schedule_spec():
    s = _fresh(flags={"has_general_liability": True, "has_property_coverage": True},
               facts={"property_locations": copy.deepcopy(_TWO_BUILDINGS)})
    page = s.page()
    g2 = _q(page, "G.2a")
    spec = g2["table"]
    for key in ("schedule_key", "schedule_label", "schedule_singular", "columns", "rows",
                "dedup_keys", "vin_decode", "row_capacity"):
        assert key in spec, key
    assert spec["schedule_key"] == "property_locations" == g2["table_key"]
    assert [c["key"] for c in spec["columns"]] == list(qn.QUESTIONS["G.2a"].columns)   # the view's own
    assert spec["rows"] == g2["value"] and len(spec["rows"]) == 2
    loss = _q(page, "C.2a")["table"]
    assert loss["schedule_key"] == "loss_history" and loss["columns"]                # a whole table
    assert _q(page, "B.1c")["table"] is None


def test_narrative_cards_find_their_question_by_fact():
    """The page deep-links an "Explain via ACORD 101" card to the question
    asking the card's fact, falling back to the remarks box - so the remarks
    box and the narrative facts must each be some question's `fact`."""
    from services.narrative_facts import NARRATIVE_FACT_KEYS
    page = qn.build_page(_row(flags={}, facts={"lines_of_business": []}))
    facts_asked = {q["fact"] for s in page["sections"] for q in s["questions"]}
    assert qn.REMARKS_FACT == "additional_remarks_text" and qn.REMARKS_FACT in facts_asked
    assert "operations_description" in facts_asked
    assert {k for k in NARRATIVE_FACT_KEYS if k in facts_asked} >= {"additional_remarks_text",
                                                                     "operations_description"}


def test_the_remarks_question_appends_through_the_narrative_door_or_replaces():
    s = _fresh(facts={"additional_remarks_text": _producer("Losses: none in five years.")})
    l6 = _q(s.page(), "L.6")
    assert l6["value"] == "Losses: none in five years." and l6["state"] == "producer_confirmed"
    out = s.act("L.6", "answer", "Losses: none in five years.\nOperations: commercial electrical work.")
    assert out["ok"] is True
    remarks = s.store["facts"]["additional_remarks_text"]["value"]
    assert remarks.count("Losses: none in five years.") == 1 and "commercial electrical work" in remarks
    out = s.act("L.6", "answer", "Operations: commercial electrical work only.")
    assert out["ok"] is True
    assert s.store["facts"]["additional_remarks_text"]["value"] == "Operations: commercial electrical work only."


def test_each_answer_reply_refreshes_the_one_page_copy():
    """The page keeps ONE copy of the GET payload and patches it from each
    reply's `question` and `counts` - so they must equal a fresh GET's."""
    s = _fresh()
    out = s.act("B.1d", "answer", "15")
    fresh = s.page()
    assert out["question"] == _q(fresh, "B.1d")
    assert out["counts"] == fresh["counts"]
    out = s.act("B.1e", "pending", owner="insured")
    fresh = s.page()
    assert out["question"] == _q(fresh, "B.1e") and out["counts"] == fresh["counts"]


# ══ The form list follows a pre-form answer (small-items agent's contract) ════

def test_answering_the_vehicles_state_co_before_forms_adds_137_co():
    """The answer reaches the recalculation with the row as it was, so the
    recommender re-runs and the reply carries the new list (and only then)."""
    from services import form_service as fs
    facts = {"applicant_name": "Acme Electric LLC", "producer_name": "Best Agency",
             "operations_description": "Electrical contracting", "entity_type": "LLC",
             "contact_name": "Pat Doe"}
    flags = {"has_auto_coverage": True, "has_general_liability": True}
    recs = fs.match_forms_deterministic(dict(facts), dict(flags), text="")
    ids = lambda rs: {r["form_id"] for r in rs or []}                    # noqa: E731
    assert "ACORD_137_CO" not in ids(recs)
    s = _Session({"user_id": _UID, "facts": copy.deepcopy(facts), "flags": dict(flags), "docs": [],
                  "recommendations": recs, "account_profile": {}, "selected_form_ids": [],
                  "generated_forms": {}, "integrity": {}, "hard_stops": [], "soft_stops": [],
                  "structured_issues": [], "cross_form_issues": [], "sqs_history": [],
                  "underwriting_consistency": {}, "underwriting_confirmations": {}})
    s.recalc()
    assert qn.QUESTIONS["B.6a"].fact == "state_of_operations"
    out = s.act("B.6a", "answer", "CO")
    assert out["ok"] is True
    assert "ACORD_137_CO" in ids(s.store["recommendations"])
    assert "ACORD_137_CO" in ids(out["recommendations"])
    assert "all_available_forms" in out
    # An answer that moves no form sends no list.
    out = s.act("B.1d", "answer", "20")
    assert out["ok"] is True and "recommendations" not in out


def test_every_questionnaire_rescore_hands_the_recalc_its_before_row():
    import inspect
    src = inspect.getsource(qr)
    assert "recalculate_session_scores(session_id, before=before)" in src
    assert "**refreshed_form_list(impact, sess)" in src
    assert src.count("rescore=True") == src.count("rescore=True, before=")


# ══ Review of Z36 (23 Oct) ════════════════════════════════════════════════════

def test_one_building_view_never_blanks_another_views_values():
    """The page holds each view's own copy of the location rows; saving G.3a
    from its (older) copy after G.2a saved must keep G.2a's cells."""
    s = _fresh(flags={"has_general_liability": True, "has_property_coverage": True},
               facts={"property_locations": copy.deepcopy(_TWO_BUILDINGS)})
    page = s.page()
    g2_rows, g3_rows = copy.deepcopy(_q(page, "G.2a")["value"]), copy.deepcopy(_q(page, "G.3a")["value"])
    for r in g2_rows:
        if r["address_line1"] == "2 Oak St":
            r.update(construction_type="Frame", year_built="2004")
    assert s.act("G.2a", "answer", g2_rows)["ok"] is True
    for r in g3_rows:                                   # the stale copy: no year built on building 2
        if r["address_line1"] == "2 Oak St":
            r["building_value"] = "750000"
    assert s.act("G.3a", "answer", g3_rows)["ok"] is True
    rows = {r["address_line1"]: r for r in s.store["facts"]["property_locations"] if isinstance(r, dict)}
    assert str(rows["2 Oak St"]["year_built"]) == "2004" and rows["2 Oak St"]["construction_type"] == "Frame"
    assert str(rows["2 Oak St"]["building_value"]).replace(",", "").replace("$", "") == "750000"
    # A new row with no stored id keeps every cell it carries.
    new = qn.merged_table_rows(qn.QUESTIONS["G.3a"], s.store,
                               [{"address_line1": "3 Elm St", "year_built": "2010", "building_value": "1"}])
    assert new == [{"address_line1": "3 Elm St", "year_built": "2010", "building_value": "1"}]


def test_looks_right_on_one_view_confirms_only_that_views_columns():
    rows = copy.deepcopy(_TWO_BUILDINGS)
    rows[1].update(construction_type="Frame", year_built="2004", building_value="750000")
    s = _fresh(flags={"has_general_liability": True, "has_property_coverage": True},
               facts={"property_locations": rows})
    page = s.page()
    assert _q(page, "G.2a")["state"] == "extracted" and _q(page, "G.3a")["state"] == "extracted"
    out = s.act("G.2a", "confirm")
    assert out["ok"] is True and out["question"]["state"] == "producer_confirmed"
    page = s.page()
    assert _q(page, "G.3a")["state"] == "extracted"             # the other view is not confirmed
    assert _q(page, "G.1a")["state"] == "extracted"
    from services.confirm_known import CONFIRMATIONS_KEY
    assert "schedule::property_locations" not in s.store["facts"][CONFIRMATIONS_KEY]
    # Saving one view marks that view, not its siblings.
    g3 = copy.deepcopy(_q(page, "G.3a")["value"])
    g3[0]["bpp_value"] = "100000"
    assert s.act("G.3a", "answer", g3)["ok"] is True
    page = s.page()
    assert _q(page, "G.3a")["state"] == "producer_confirmed"
    assert _q(page, "G.1a")["state"] == "extracted" and _q(page, "G.4a")["state"] != "producer_confirmed"


def _misaligned_umbrella_row():
    """A pre-form package whose ONLY open item is the umbrella / auto period
    warning (85), with remarks already on file."""
    P = _producer
    return _row(flags={"has_general_liability": True, "has_umbrella": True, "has_auto_coverage": True},
                facts={"effective_date": P("05/11/2026"), "expiration_date": P("05/11/2027"),
                       "umbrella_effective_date": P("05/11/2026"), "umbrella_expiration_date": P("05/11/2027"),
                       "auto_effective_date": P("06/01/2026"), "auto_expiration_date": P("05/11/2027"),
                       "umbrella_limit": P("$5,000,000"), "gl_each_occurrence": P("$1,000,000"),
                       "gl_aggregate": P("$2,000,000"), "auto_liability_limit": P("$1,000,000"),
                       "employers_liability_limits": P("$1,000,000"),
                       "gl_class_codes_by_location": P("91580"),
                       "physical_address": P("1 Main St, Denver, CO 80202"),
                       "auto_covered_symbols": P("1"),
                       "auto_vin_schedule": [{"year": "2020", "make": "Ford", "model": "F-150",
                                              "vin": "1FTEW1EP5LFA12345"}],
                       "auto_drivers": [{"name": "Pat Doe", "dob": "01/01/1980",
                                         "license_number": "123456789", "license_state": "CO"}],
                       "additional_remarks_text": P("Umbrella written by a different carrier.")},
                recommendations=[{"form_id": "ACORD_125"}, {"form_id": "ACORD_127"},
                                 {"form_id": "ACORD_131"}])


def test_an_explanation_opened_from_its_card_clears_it_and_open_again_takes_it_back():
    from models.schemas import ReopenIssueRequest
    from services.issue_registry import explained_issue_codes
    code = "umbrella_auto_period_misaligned"
    s = _Session(_misaligned_umbrella_row())
    s.recalc()
    msg = next(m for m in s.store["soft_stops"] if m.startswith("Umbrella effective date"))
    assert s.store["package_sqs"]["cap_applied"] == 85
    l6 = _q(s.page(), "L.6")
    out = s.act("L.6", "answer", l6["value"] + "\nThe auto policy incepts three weeks later because the "
                "fleet was bought mid-term; the umbrella follows it from that date.",
                code=code, issue_id="iss-umb")
    assert out["ok"] is True
    assert code in explained_issue_codes(s.store["facts"])
    assert msg not in (s.store.get("soft_stops") or [])
    assert s.store["package_sqs"].get("cap_applied") != 85           # its 85 is gone
    remarks = s.store["facts"]["additional_remarks_text"]["value"]
    assert remarks.count("Umbrella written by a different carrier.") == 1
    back = s.body(s.run(ar.reopen_issue, ReopenIssueRequest(session_id=_SID, issue_id="iss-umb", code=code,
                                                             message=msg), current_user=_USER))
    assert back.get("cleared") is True
    assert code not in explained_issue_codes(s.store["facts"])
    assert s.store["facts"]["additional_remarks_text"]["value"] == "Umbrella written by a different carrier."
    assert msg in s.store["soft_stops"] and s.store["package_sqs"]["cap_applied"] == 85


def test_a_rewritten_remarks_answer_still_answers_its_card():
    from services.issue_registry import explained_issue_codes
    code = "umbrella_auto_period_misaligned"
    s = _Session(_misaligned_umbrella_row())
    s.recalc()
    out = s.act("L.6", "answer", "The fleet was bought mid-term, so the auto policy starts on 06/01/2026.",
                code=code, issue_id="iss-umb2")
    assert out["ok"] is True
    assert code in explained_issue_codes(s.store["facts"])
    assert s.store["package_sqs"].get("cap_applied") != 85


def test_a_number_in_a_narrative_heading_must_be_stated_too():
    evidence = [{"id": "A.1a", "section": "A", "question": "Named insured", "answer": "Acme Electric LLC"},
                {"id": "C.1a", "section": "C", "question": "Loss history years", "answer": "5"}]
    reply = {"sections": [
        {"heading": "Loss free since 2015 - 12 years", "text": "Acme Electric LLC reports no losses.",
         "cites": ["A.1a"]},
        {"heading": "Loss history - 5 years", "text": "Acme Electric LLC supplied 5 years of loss runs.",
         "cites": ["C.1a"]}]}
    text, report = qn.gate_narrative(reply, evidence)
    assert "2015" not in text and "12 YEARS" not in text
    assert text.startswith("LOSS HISTORY - 5 YEARS") and report["headings_dropped"] == 1


def _fein_conflict_row():
    return _row(facts={"_uw_conflict_keys": ["fein"], "fein": _doc_env("12-3456789")},
                underwriting_consistency={"fields": [{
                    "fact_key": "fein", "status": "conflict", "review_required": True, "conflict_scope": [],
                    "values": [{"display": "12-3456789", "sources": [{"filename": "Package Dec.pdf"}]},
                               {"display": "98-7654321", "sources": [{"filename": "Application.pdf"}]}]}]})


def test_use_this_on_a_secure_disagreement_posts_the_index_never_the_value():
    s = _Session(_fein_conflict_row())
    s.recalc()
    fein = _q(s.page(), "B.1b")
    assert fein["state"] == "conflicting"
    assert [(c["value"], c["choice"]) for c in fein["conflict_values"]] == [("**-***6789", 0),
                                                                          ("**-***4321", 1)]
    assert "98-7654321" not in json.dumps(fein)                       # never on the wire
    calls = []

    async def _dc(req, current_user=None):
        calls.append((req.fact_key, req.value))

    import routes.form_routes as fr
    req = qr.QuestionnaireAnswerRequest(question_id="B.1b", action="answer", choice=1)
    out = s.body(s.run(qr.answer_question, _SID, req, current_user=_USER,
                       extra=(patch.object(fr, "underwriting_confirm_value", _dc),)))
    assert out["ok"] is True and calls == [("fein", "98-7654321")]
    # A masked value typed back is refused; an index out of range too.
    assert s.act("B.1b", "answer", "**-***4321")["ok"] is False
    assert s.act("B.1b", "answer", choice=7)["ok"] is False


def test_contact_title_never_reaches_the_gap_fill_prompt():
    from services.pdf_service import _GAP_FILL_FACTS_EXCLUDE
    assert "contact_title" in _GAP_FILL_FACTS_EXCLUDE
