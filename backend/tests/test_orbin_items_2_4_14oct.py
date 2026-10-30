"""Orbin 22 Sep items 2 and 4 / 11 (owner, 14 Oct 2026).

2  - Brent: "we should not be requiring the forms to be created in order to
     get the score ... I don't want to portray messaging that we are heavily
     forms dependent." The "so far / It can change when forms are generated"
     wording is gone, the marketing page no longer calls SQS a download
     preflight, and the dashboard shows the pre-form score (a display-only
     `pre_form_score` copy saved by the pre-form actions).
4 / 11 - the proposed term is the next anniversary on or after today: a next
     term more than 30 days under way rolls on to the one after it (Brent
     retyped Choice Electric's 01/01/2026 as 01/01/2027-01/01/2028).
"""
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from services import extraction_service as es

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "frontend" / "src"
NO_FORMS = "Scored from your documents and answers - no forms needed."


# ── 2: the words ──────────────────────────────────────────────────────────────

def test_no_screen_says_the_score_waits_for_forms():
    rail = (SRC / "components/form/review/ReviewRailLayout.jsx").read_text()
    modal = (SRC / "components/form/AcordModal.jsx").read_text()
    gen = (SRC / "utils/packageGeneration.js").read_text()
    for src in (rail, modal, gen):
        assert "It can change when forms are generated" not in src
        assert "Score so far" not in src and "Submission Quality Score so far" not in src
    assert NO_FORMS in rail and NO_FORMS in modal
    assert '"Total Package Score" : "Submission Score"' in gen


def test_the_marketing_page_does_not_tie_the_score_to_forms():
    page = (SRC / "components/pages/PlatformPage.jsx").read_text()
    for gone in ("before you can complete a download", "Per-form scoring", "SQS per-form"):
        assert gone not in page
    assert "with or without ACORD forms" in page
    assert "—" not in page and "–" not in page


# ── 2: the dashboard's score before forms ────────────────────────────────────

def _remember(row, pkg, monkeypatch):
    import routes.form_routes as fr
    writes = []

    async def _fake(sid, updates, *a, **k):
        writes.append((sid, updates))
    monkeypatch.setattr(fr, "upd_processing_session", _fake)
    asyncio.run(fr._remember_pre_form_score("s1", row, pkg))
    return writes


def test_the_pre_form_score_is_saved_for_the_dashboard(monkeypatch):
    # (19 Oct 2026, Brent: "Quote Ready" needs no open hard stop) - the copy carries the readiness flag too.
    pkg = {"package_sqs_score": 92, "tier": "Almost There", "submission_ready": False}
    snap = {"package_sqs_score": 92, "tier": "Almost There", "submission_ready": False}
    w = _remember({"facts": {}}, pkg, monkeypatch)
    assert w == [("s1", {"pre_form_score": snap})]
    # unchanged -> no write; forms exist -> the saved package score rules, no write
    same = {"pre_form_score": dict(snap)}
    assert _remember(same, pkg, monkeypatch) == []
    assert _remember({"generated_forms": {"ACORD_125": {}}}, {"package_sqs_score": 72}, monkeypatch) == []
    # a copy saved before 19 Oct 2026 (no flag) is rewritten once, with it
    old = {"pre_form_score": {"package_sqs_score": 92, "tier": "Almost There"}}
    assert _remember(old, pkg, monkeypatch) == [("s1", {"pre_form_score": snap})]
    # no score (integrity review, scorer failure) clears a stale copy
    assert _remember(same, None, monkeypatch) == [("s1", {"pre_form_score": None})]
    # the dashboard reads the flag from the same score as the number
    repo = (ROOT / "backend/repositories/session_repository.py").read_text()
    assert "ELSE data->'pre_form_score'->>'submission_ready' END" in repo


def test_the_pre_form_actions_and_the_page_view_keep_it_current():
    # REVERSED 30 Oct 2026 (owner: "at any point the package's score is x, the
    # dashboard shows x"): the page load also refreshes the copy when it differs.
    src = (ROOT / "backend/routes/form_routes.py").read_text()
    assert src.count("remember_score=True") == 5
    view = src[src.index('@router.get("/api/session/{session_id}/extraction-result")'):]
    view = view[:view.index("@router.", 1)] if "@router." in view[1:] else view
    assert "remember_score=True" in view
    repo = (ROOT / "backend/repositories/session_repository.py").read_text()
    assert "(data->'pre_form_score'->>'package_sqs_score')::int" in repo
    assert "COALESCE((data->'package_sqs'->>'package_sqs_score')::int," in repo


# ── 4 / 11: the next anniversary on or after today ───────────────────────────

def _route(eff, exp):
    f = lambda d: d.strftime("%m/%d/%Y")
    mf = {"effective_date": {"value": f(eff), "source": "ai"},
          "expiration_date": {"value": f(exp), "source": "ai"}, "is_renewal": "Yes"}
    es._route_renewal_dates(mf)
    return mf


def _ymd(mf, key):
    v = es._fv(mf, key)
    return datetime.strptime(v, "%m/%d/%Y").date() if v else None


def test_a_next_term_well_under_way_rolls_to_the_next_anniversary():
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    exp = today - timedelta(days=90)                 # the dec ended 90 days ago
    mf = _route(exp - timedelta(days=365), exp)
    assert _ymd(mf, "effective_date") == (exp + timedelta(days=365)).date()
    assert _ymd(mf, "effective_date") >= today.date()
    assert mf["effective_date"]["derivation"].get("rolled_to_next_anniversary") is True
    assert es.is_derived_proposed_term(mf["effective_date"])      # still "Please verify"
    assert _ymd(mf, "prior_expiration_date") == exp.date()


def test_a_renewal_a_few_days_late_keeps_its_own_term():
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    exp = today - timedelta(days=5)
    mf = _route(exp - timedelta(days=365), exp)
    assert _ymd(mf, "effective_date") == exp.date()
    assert "rolled_to_next_anniversary" not in mf["effective_date"]["derivation"]


def test_documents_two_terms_old_are_still_asked():
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    exp = today - timedelta(days=400)                # the next term ended too
    mf = _route(exp - timedelta(days=365), exp)
    assert not es._fv(mf, "effective_date") and not es._fv(mf, "expiration_date")


def test_brents_choice_electric_retype():
    mf = {"effective_date": {"value": "01/01/2025", "source": "ai"},
          "expiration_date": {"value": "01/01/2026", "source": "ai"}, "is_renewal": "Yes"}
    es._route_renewal_dates(mf)
    now = datetime.now()
    if datetime(2026, 1, 31) < now < datetime(2027, 1, 1):
        assert (es._fv(mf, "effective_date"), es._fv(mf, "expiration_date")) == ("01/01/2027", "01/01/2028")
