"""The owner's fresh run of 1 Oct 2026 (session 359b36b0): three defects.

1. A form save scored the form as the FIRST selected form. `update_pdf` called
   `calculate_sqs` without `form_id`, and the scorer falls back to
   `selected_form_ids[0]`. After a 127 save the 127 panel carried the 125's
   score and cards - the premises card was answered there, and the landlord
   cards it raised went to the 125 panel, which was not open.
2. A card first raised AFTER generation (the landlord cards) never reached the
   download review or the cover: cards were recorded only at generation.
3. The cover's needs-attention rows were a snapshot from the last generation or
   save, so an item answered on a card stayed on the cover while the review
   (which reads the live list) had dropped it.

Plus the side effect of fixing 2: a zero-point card ("kept for certificates")
must not print on the underwriter's cover, nor be handed to the cover's model.
"""
import ast
import asyncio
import json
from pathlib import Path

import pytest

import services.audit_service as au
import services.cover_service as cs
from routes import download_routes as dr
from services.sqs_service import calculate_sqs

BACKEND = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((BACKEND / "tests" / "fixtures" / "needs_attention_live_30sep.json")
                     .read_text(encoding="utf-8"))


def _live(tag):
    d = FIXTURE[tag]
    return d["generated_forms"], d["facts"], d["flags"]


def _score(tag, form_id=None):
    gf, facts, flags = _live(tag)
    kw = {"form_id": form_id} if form_id else {}
    return calculate_sqs(facts=facts, flags=flags,
                         mapped_data=gf["ACORD_125"].get("field_state") or {}, form_schema={},
                         selected_form_ids=["ACORD_125", "ACORD_127"], hard_stops=[],
                         soft_stops=[], tier2_score=50, **kw)


def _ids(sqs):
    return [r.get("rec_id") for r in sqs.get("recommendations") or [] if isinstance(r, dict)]


# ══════════════════════════════════════════════════════════════════════════════
# 1. Every scorer call names the form it scores
# ══════════════════════════════════════════════════════════════════════════════

def test_the_fallback_is_what_the_save_route_hit():
    """Guard for the guard: without a form id the "127" comes back as the 125,
    with the 125's premises card - the live shape of the defect."""
    wrong = _score("8992")
    assert wrong["form_id"] == "ACORD_125"
    assert "rec_premises_interest" in _ids(wrong)
    right = _score("8992", "ACORD_127")
    assert right["form_id"] == "ACORD_127"
    assert not any("premises" in i or "landlord" in i for i in _ids(right))


def test_the_landlord_cards_belong_to_the_125_only():
    assert {"rec_landlord_name", "rec_landlord_address"} <= set(_ids(_score("b8d6", "ACORD_125")))
    assert not any("landlord" in i for i in _ids(_score("b8d6", "ACORD_127")))


def _calls(path: Path, names):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
            if name in names:
                yield node


def _source_files():
    return (sorted((BACKEND / "routes").glob("*.py")) + sorted((BACKEND / "services").glob("*.py"))
            + [BACKEND / "worker.py"])


def test_every_scorer_call_names_its_form():
    """The one call that did not (form_routes.update_pdf, since May 2026) scored
    every non-first form by the first form's rules until the next recalculation."""
    missing = []
    for path in _source_files():
        for call in _calls(path, {"calculate_sqs", "calculate_sqs_from_facts"}):
            if not any(k.arg == "form_id" for k in call.keywords):
                missing.append(f"{path.name}:{call.lineno}")
    assert not missing, f"scorer calls without form_id: {missing}"


# ══════════════════════════════════════════════════════════════════════════════
# 2. The stored cards follow the forms
# ══════════════════════════════════════════════════════════════════════════════

class _Table:
    """An in-memory sqs_recommendation_audit behind the door's four primitives."""

    def __init__(self, rows=()):
        self.rows = {r["rec_id"]: dict(r) for r in rows}
        self.inserted = []

    async def log(self, session_id, user_id, sqs_result, model_version):
        for rec in sqs_result.get("recommendations") or []:
            self.inserted.append(au._card_id(rec))
            rid = au._card_id(rec)
            self.rows.setdefault(rid, {"rec_id": rid, "action": None, "producer_answer": None,
                                       "form_id": sqs_result.get("form_id")})

    async def stored(self, session_id):
        return [dict(r) for r in self.rows.values()]

    async def reopen(self, session_id, rec_ids):
        for rid in rec_ids:
            r = self.rows[rid]
            if r["action"] == "resolved" and not r.get("producer_answer"):
                r["action"] = None

    async def resolve(self, session_id, rec_id, sqs_score_at_action, model_version, user_id=None):
        r = self.rows.get(rec_id)
        if r and r["action"] in (None, "downloaded_anyway"):
            r["action"] = "resolved"
            return True
        return False

    async def repoint(self, session_id, points):
        for rid, pts in points.items():
            r = self.rows[rid]
            if r["action"] in (None, "downloaded_anyway"):
                r["score_impact"] = pts

    def action(self, rid):
        return self.rows[rid]["action"]


@pytest.fixture
def table(monkeypatch):
    t = _Table()
    monkeypatch.setattr(au, "log_recommendations_presented", t.log)
    monkeypatch.setattr(au, "_stored_card_rows", t.stored)
    monkeypatch.setattr(au, "_reopen_system_closed_cards", t.reopen)
    monkeypatch.setattr(au, "mark_recommendation_resolved", t.resolve)
    monkeypatch.setattr(au, "_repoint_open_cards", t.repoint)
    return t


def _sync(forms):
    return asyncio.run(au.sync_recommendation_cards("s", "u", forms, "v", score_at_action=73))


def _form(fid, *rec_ids):
    return {"form_id": fid, "recommendations": [{"rec_id": r, "message": r} for r in rec_ids]}


def test_a_card_raised_by_an_answer_is_recorded(table):
    """The live shape: Tenant answered (its card resolved with the answer), the
    125's re-score raises the two landlord cards."""
    table.rows = {"rec_premises_interest": {"rec_id": "rec_premises_interest", "action": "resolved",
                                            "producer_answer": "Tenant - the business rents its space"}}
    _sync([_form("ACORD_125", "rec_contact_name", "rec_landlord_name", "rec_landlord_address"),
           _form("ACORD_127", "rec_narrative_components")])
    assert table.action("rec_landlord_name") is None and table.action("rec_landlord_address") is None
    assert table.rows["rec_landlord_name"]["form_id"] == "ACORD_125"
    assert table.action("rec_premises_interest") == "resolved"        # the answer stands


def test_a_card_no_form_shows_is_resolved_even_when_acknowledged(table):
    table.rows = {"rec_contact_name": {"rec_id": "rec_contact_name", "action": None},
                  "rec_x": {"rec_id": "rec_x", "action": "downloaded_anyway"}}
    out = _sync([_form("ACORD_125", "rec_narrative_components")])
    assert table.action("rec_contact_name") == "resolved" and table.action("rec_x") == "resolved"
    assert out["resolved"] == 2


def test_a_card_another_form_still_shows_stays_open(table):
    """A save used to resolve a card the moment it left the SAVED form, though the
    126 still showed it - the review then missed a card on screen."""
    table.rows = {"rec_narrative_components": {"rec_id": "rec_narrative_components", "action": None}}
    _sync([_form("ACORD_125"), _form("ACORD_126", "rec_narrative_components")])
    assert table.action("rec_narrative_components") is None


def test_a_system_closed_card_that_is_live_again_is_reopened(table):
    table.rows = {"rec_a": {"rec_id": "rec_a", "action": "resolved", "producer_answer": None}}
    out = _sync([_form("ACORD_186", "rec_a")])
    assert table.action("rec_a") is None and out["reopened"] == 1


def test_the_producers_own_acts_are_never_touched(table):
    """Dismissed, and answered (the panel shows both under Reviewed) - live or not."""
    table.rows = {
        "rec_dismissed_live": {"rec_id": "rec_dismissed_live", "action": "dismissed"},
        "rec_dismissed_gone": {"rec_id": "rec_dismissed_gone", "action": "dismissed"},
        "rec_answered_live": {"rec_id": "rec_answered_live", "action": "resolved", "producer_answer": "x"},
    }
    _sync([_form("ACORD_125", "rec_dismissed_live", "rec_answered_live")])
    assert table.action("rec_dismissed_live") == "dismissed"
    assert table.action("rec_dismissed_gone") == "dismissed"
    assert table.action("rec_answered_live") == "resolved"


def test_findings_rows_keep_their_own_refresh(table):
    table.rows = {"fieldqa_attn_ACORD_125_missing": {"rec_id": "fieldqa_attn_ACORD_125_missing", "action": None},
                  "fieldmap_x": {"rec_id": "fieldmap_x", "action": None}}
    _sync([_form("ACORD_125")])
    assert table.action("fieldqa_attn_ACORD_125_missing") is None and table.action("fieldmap_x") is None


def test_no_scored_form_is_no_evidence(table):
    """Pre-form (nothing generated, nothing scored): the old pass resolved every
    open card on an empty list; the door changes nothing."""
    table.rows = {"rec_a": {"rec_id": "rec_a", "action": None}}
    assert _sync([]) == {"presented": 0, "reopened": 0, "resolved": 0, "repointed": 0}
    assert _sync([None]) == {"presented": 0, "reopened": 0, "resolved": 0, "repointed": 0}
    assert table.action("rec_a") is None


def test_every_form_clear_resolves_every_open_card(table):
    table.rows = {"rec_a": {"rec_id": "rec_a", "action": None}}
    _sync([_form("ACORD_125"), _form("ACORD_127")])
    assert table.action("rec_a") == "resolved"


def test_a_card_without_an_id_is_keyed_like_its_insert(table):
    """A plain-string card is stored under its message hash; the next sync must
    see it as live, not resolve it (the old pass read dict ids only)."""
    forms = [{"form_id": "ACORD_125", "recommendations": ["Add a narrative", {"message": "No id"}]}]
    _sync(forms)
    _sync(forms)
    assert all(r["action"] is None for r in table.rows.values())
    assert au._fallback_rec_id("Add a narrative") in table.rows


def test_the_reopen_statement_repeats_the_plans_test():
    """A card the producer answers between the plan and the UPDATE stays answered."""
    import inspect
    src = inspect.getsource(au._reopen_system_closed_cards)
    assert "action='resolved'" in src and "producer_answer IS NULL" in src


def test_a_failure_never_breaks_the_caller(monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("no pool")

    async def empty(*_a, **_k):
        return []
    monkeypatch.setattr(au, "_stored_card_rows", empty)
    monkeypatch.setattr(au, "log_recommendations_presented", boom)
    out = asyncio.run(au.sync_recommendation_cards("s", "u", [_form("ACORD_125", "rec_a")], "v"))
    assert out == {"presented": 0, "reopened": 0, "resolved": 0, "repointed": 0}


def test_only_new_cards_are_inserted(table):
    """One insert per NEW card - not one per live card on every save and answer."""
    table.rows = {"rec_a": {"rec_id": "rec_a", "action": None}}
    out = _sync([_form("ACORD_125", "rec_a", "rec_b"), _form("ACORD_126", "rec_b", "rec_c")])
    assert table.inserted == ["rec_b", "rec_c"] and out["presented"] == 2
    assert table.rows["rec_b"]["form_id"] == "ACORD_125"            # the first form names it
    table.inserted.clear()
    assert _sync([_form("ACORD_125", "rec_a", "rec_b")])["presented"] == 0
    assert table.inserted == []


def test_every_scoring_path_goes_through_the_door():
    """Generation, the worker, a save and the recalculation after an answer - and
    nobody else writes presented / auto-resolved card rows."""
    expect = {
        BACKEND / "routes" / "form_routes.py": 2,      # select_forms_bulk + update_pdf
        BACKEND / "worker.py": 1,
        BACKEND / "services" / "arq_service.py": 1,
    }
    for path, n in expect.items():
        assert len(list(_calls(path, {"sync_recommendation_cards"}))) == n, path.name
    for path in _source_files():
        if path.name == "audit_service.py":
            continue
        assert not list(_calls(path, {"log_recommendations_presented"})), path.name
        resolves = list(_calls(path, {"mark_recommendation_resolved"}))
        # The one other caller is the manual POST /api/audit/resolve route.
        assert len(resolves) == (1 if path.name == "audit_routes.py" else 0), path.name


# ══════════════════════════════════════════════════════════════════════════════
# 3. The cover reads the needs-attention rows live - as the review does
# ══════════════════════════════════════════════════════════════════════════════

_STALE_125 = {"rec_id": "fieldqa_attn_ACORD_125_missing", "form_id": "ACORD_125",
              "recommendation_type": "suggestion", "score_impact": None, "field": None,
              "action": "downloaded_anyway",
              "message": "ACORD 125 - Missing (10): ... Named insured's interest in the building ..."}
_CARD = {"rec_id": "rec_contact_name", "form_id": "ACORD_125", "recommendation_type": "missing_field",
         "score_impact": 5, "field": "contact_name", "action": None, "message": "ACORD 125 missing: contact info"}
_HARDBLOCK = {"rec_id": "fieldqa_hardblock_ACORD_125_X_placeholder", "form_id": "ACORD_125",
              "recommendation_type": "suggestion", "score_impact": None, "field": "X", "action": None,
              "message": "placeholder"}


def _attention(tag="8992"):
    from services.needs_attention import needs_attention_for_session
    gf, facts, flags = _live(tag)
    return needs_attention_for_session(gf, facts, flags=flags)


def test_the_stale_row_gives_way_to_the_live_list():
    att = _attention()
    out = au.with_live_attention_rows([_CARD, _STALE_125, _HARDBLOCK], att)
    ids = [r["rec_id"] for r in out]
    assert ids[:2] == ["rec_contact_name", _HARDBLOCK["rec_id"]]       # stored order kept
    assert ids.count("fieldqa_attn_ACORD_125_missing") == 1              # the stale one replaced
    missing = next(r for r in out if r["rec_id"] == "fieldqa_attn_ACORD_125_missing")
    assert "Missing (10)" not in missing["message"]
    live = next(f for f in att["forms"] if f["form_id"] == "ACORD_125")
    # The producer's to-dos and the applicant's own steps (sign and date) are
    # rows of their own, so the plain "Missing" card counts neither.
    n = live["counts"]["missing"] - sum(
        1 for r in live["rows"]
        if r["status"] == "missing" and (r.get("producer_todo") or r.get("applicant_step")))
    assert f"Missing ({n})" in missing["message"]
    assert missing["action"] == "downloaded_anyway"       # the acknowledgement survives
    assert missing["form_id"] == "ACORD_125" and missing["recommendation_type"] == "suggestion"
    assert _HARDBLOCK in out and _CARD in out              # never superseded


def test_a_form_the_live_list_could_not_read_keeps_its_stored_rows():
    att = {"forms": [{"form_id": "ACORD_125", "rows": [], "counts": {}, "ok": False}]}
    assert au.with_live_attention_rows([_STALE_125], att) == [_STALE_125]
    assert au.with_live_attention_rows([_STALE_125], None) == [_STALE_125]


def test_a_legacy_summary_row_goes_unless_a_form_failed():
    legacy = {"rec_id": "fieldqa_summary", "form_id": None, "message": "3 fields are required but empty"}
    ok = {"forms": [{"form_id": "ACORD_125", "rows": [], "counts": {}, "ok": True}]}
    bad = {"forms": [{"form_id": "ACORD_126", "rows": [], "counts": {}, "ok": False}]}
    assert au.with_live_attention_rows([legacy], ok) == []
    assert au.with_live_attention_rows([legacy], bad) == [legacy]


def test_the_download_door_reads_the_live_list(monkeypatch):
    async def stored(_sid):
        return [dict(_CARD), dict(_STALE_125)]
    monkeypatch.setattr(au, "get_unresolved_recommendations", stored)
    gf, facts, flags = _live("8992")
    out = asyncio.run(au.current_unresolved_recommendations(
        "s", {"generated_forms": gf, "facts": facts, "flags": flags}))
    assert not any("Missing (10)" in (r.get("message") or "") for r in out)
    # No forms (a Lite brief before generation): the stored rows, untouched.
    assert asyncio.run(au.current_unresolved_recommendations("s", {})) == [_CARD, _STALE_125]


def test_every_download_reads_the_door():
    src = (BACKEND / "routes" / "download_routes.py").read_text(encoding="utf-8")
    assert src.count("await current_unresolved_recommendations(session_id, proc_session)") == 3
    assert "get_unresolved_recommendations(" not in src


# ══════════════════════════════════════════════════════════════════════════════
# The underwriter's cover: no zero-point card, in the list or the paragraph
# ══════════════════════════════════════════════════════════════════════════════

def test_a_zero_point_card_stays_off_the_cover():
    gf, _facts, _flags = _live("b8d6")
    forms = {"ACORD_125": {"sqs": _score("b8d6", "ACORD_125")}}
    unscored = dr._unscored_card_ids(forms)
    assert {"rec_landlord_name", "rec_landlord_address"} <= unscored
    rows = [{"rec_id": "rec_landlord_name", "recommendation_type": "missing_field", "score_impact": 0,
             "message": "ACORD 125 premises: the insured rents ... landlord's full name?"},
            dict(_CARD),
            {"rec_id": "rec_landlord_address", "recommendation_type": "hard_stop", "score_impact": 0,
             "message": "a hard stop is never hidden"}]
    hard, soft = dr._split_open_recs(rows, unscored)
    assert soft == ["ACORD 125 missing: contact info (up to +5 pts)"]
    assert hard == ["a hard stop is never hidden"]
    # A stored 0 alone is no proof: a scored card whose pillar is full stores 0 too.
    assert dr._split_open_recs(rows[:1])[1] == [rows[0]["message"]]


def test_both_covers_leave_zero_point_cards_out():
    src = (BACKEND / "routes" / "download_routes.py").read_text(encoding="utf-8")
    assert src.count('_unscored_card_ids(proc_session.get("generated_forms"))') == 2


class _Model:
    def __init__(self):
        self.prompts = []

    async def __call__(self, _model, messages, max_tokens=None):
        self.prompts.append(messages[0]["content"])
        return json.dumps({"narrative": "N.", "sqs_reasoning": "R."})


def test_the_cover_paragraph_is_never_handed_a_zero_point_card(monkeypatch):
    m = _Model()
    monkeypatch.setattr(cs, "groq_chat", m)

    async def _none(*_a, **_k):
        return None
    monkeypatch.setattr(cs, "_cache_get", _none)
    monkeypatch.setattr(cs, "_cache_set", _none)
    sqs125 = _score("b8d6", "ACORD_125")
    assert any(isinstance(r, dict) and r.get("unscored") for r in sqs125["recommendations"])
    gf, facts, flags = _live("b8d6")
    asyncio.run(cs.generate_ai_cover_narrative(
        facts=facts, flags=flags, sqs_results={"ACORD_125": sqs125}, form_ids=["ACORD_125"],
        org_name="Agency", user={"full_name": "P"}, package_score=73))
    prompt = m.prompts[0]
    assert "landlord" not in prompt.lower()
    scored = [r for r in sqs125["recommendations"] if isinstance(r, dict) and not r.get("unscored")]
    assert scored and all(r["message"] in prompt for r in scored)       # the rest still reach it
