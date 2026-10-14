"""One status from start to finish (owner, 14 Oct 2026).

Brent: "Why do we have something flagged as a warning pre-form that is
re-flagged as a hard stop once the form exists? ... We know what's likely going
to be an issue." Owner's decision: a check keeps the SAME status before and
after forms - no promotion at generation.

Before this change C75 demoted every cross-form hard stop to a warning while no
form existed, and every post-form scorer (generation through the stops door,
the post-form recalculation behind answers / resolve / reopen / added
documents, the field-edit re-score) put it back at full force - capping the
package at 60 for a check the Review screen had called a warning. Now one
function decides the severity (`stops_now.cross_form_severity`) and every one
of those paths asks it. Field-level hard stops and blocking cross-document /
Data Consistency conflicts are hard before forms AND after (unchanged).

The "Becomes a hard stop when ACORD 140 is generated" tag and its count are
gone with the promotion they announced.
"""
from __future__ import annotations

import ast
import asyncio
import copy
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

from services import stops_now as sn                                     # noqa: E402
from services.issue_registry import (                                    # noqa: E402
    build_structured_from_sources, grouped_with_package_caps,
)
from services.sqs_service import HARD_STOP_CAP, calculate_package_sqs    # noqa: E402

BI = "Business Income limit is specified but Period of Restoration is missing"
MV_LEGACY = "Property Minimum Viable COPE incomplete"
MV_CODED = "Property submission missing Minimum Viable COPE"


def _facts(**over):
    facts = {
        "applicant_name": "Choice Electric LLC",
        "locations": ["5405 S Lowell Blvd, Littleton, CO 80123"],
        "property_locations": [{"address": "5405 S Lowell Blvd, Littleton, CO 80123",
                                "construction_type": "Frame", "building_value": "$798,556"}],
        "construction_type": "Frame",
        "property_building_value": "$798,556",
        "occupancy_type": {"value": "Contractor shop or yard", "source": "producer",
                           "confidence": "filled"},
        "business_income_limit": "$1,000,000",
    }
    facts.update(over)
    return facts


_FLAGS = {"has_property_coverage": True, "property_has_bi_coverage": True}


def _session(facts=None, **over):
    s = {"facts": facts if facts is not None else _facts(), "flags": dict(_FLAGS),
         "recommendations": [{"form_id": "ACORD_140"}]}
    s.update(over)
    return s


def _both(session, forms=("ACORD_140",)):
    """(before forms, after forms) through the one stops door."""
    return (sn.stops_now(session, list(forms), pre_form=True),
            sn.stops_now(session, list(forms), pre_form=False))


def _score(session, st):
    return calculate_package_sqs(
        facts=session["facts"], flags=session["flags"], form_results=[],
        cross_issues=st["cross_issues"], hard_stops=st["hard"], soft_stops=st["soft"],
        session_data=session, _probe=True)


def _listed(fragment, stops):
    return any(fragment in m for m in stops)


# ── the door: one severity, before forms and after ───────────────────────────

def test_a_cross_form_hard_stop_is_a_warning_before_forms_and_after():
    pre, post = _both(_session())
    for st in (pre, post):
        assert not _listed(BI, st["hard"]), st["pre_form"]
        assert _listed(BI, st["soft"]), st["pre_form"]
        bi = [i for i in st["cross_issues"] if i.get("code") == "bi_missing_period_of_restoration"]
        assert [i["type"] for i in bi] == ["soft_warning"], st["pre_form"]
        assert not any(i.get("type") == "hard_stop" for i in st["cross_issues"])
    # the same issue, the same status, in the same place in the list
    assert [m for m in post["soft"] if BI in m] == [m for m in pre["soft"] if BI in m]


def test_after_generation_the_package_is_not_capped_at_60_by_it():
    session = _session()
    pre, post = _both(session)
    for st in (pre, post):
        pkg = _score(session, st)
        assert pkg["cap_applied"] != HARD_STOP_CAP
        assert BI not in str(pkg.get("cap_reason") or "")
    assert _score(session, pre)["package_sqs_score"] == _score(session, post)["package_sqs_score"]


def test_a_field_level_hard_stop_stays_hard_both_times():
    facts = _facts()
    facts.pop("occupancy_type")
    session = _session(facts)
    pre, post = _both(session)
    for st in (pre, post):
        assert _listed(MV_LEGACY, st["hard"]), st["pre_form"]
        # its coded cross-form twin is a warning both times
        assert not _listed(MV_CODED, st["hard"]) and _listed(MV_CODED, st["soft"])
        pkg = _score(session, st)
        assert pkg["cap_applied"] == HARD_STOP_CAP
        assert MV_LEGACY in str(pkg.get("cap_reason") or "")


def test_a_blocking_document_conflict_stays_hard_both_times():
    uw = {"review_required": True, "fields": [
        {"fact_key": "property_building_value", "label": "Building Value", "review_required": True,
         "values": [{"display": "$798,556"}, {"display": "$421,714"}]}]}
    pre, post = _both(_session(underwriting_consistency=uw))
    for st in (pre, post):
        assert _listed("Building Value: documents disagree", st["hard"]), st["pre_form"]


def test_the_severity_door_changes_only_hard_stops():
    issues = [{"code": "a", "type": "hard_stop", "message": "A"},
              {"code": "b", "type": "soft_warning", "message": "B"},
              {"code": "c", "type": "advisory", "message": "C", "form_choice": True},
              "not a dict", None]
    before = copy.deepcopy(issues)
    out = sn.cross_form_severity(issues)
    assert [getattr(i, "get", lambda _k: i)("type") if isinstance(i, dict) else i for i in out] == \
        ["soft_warning", "soft_warning", "advisory", "not a dict", None]
    assert out[1] is issues[1] and out[2] is issues[2]
    assert issues == before, "the caller's issues are never mutated"
    assert sn.cross_form_severity(None) == [] and sn.cross_form_severity([]) == []


# ── every path that scores after forms makes the same choice ────────────────

def test_the_post_form_recalculation_keeps_the_warning(monkeypatch):
    """The real `recalculate_session_scores` (answers, resolve, reopen, added
    documents, policy lines) on a generated package: BI stays a warning, the
    package is not held at 60, and the stored card copies say warning too."""
    import tests.test_reopen_takes_the_fix_back_9oct as H
    row = H._row()
    row["facts"].update(_facts())
    row["flags"] = dict(row["flags"], **_FLAGS)
    row["generated_forms"]["ACORD_140"] = {
        "mapped": {}, "confidence": {}, "schema": {}}
    row["selected_form_ids"] = ["ACORD_125", "ACORD_140"]
    # a current term: no expired-term field-level hard stop in the way
    from datetime import datetime, timedelta
    row["facts"]["effective_date"] = H._producer(H._mdY(datetime.now() - timedelta(days=30)))
    row["facts"]["expiration_date"] = H._producer(H._mdY(datetime.now() + timedelta(days=335)))
    s = H._Session(row)
    s.recalc()
    store = s.store
    assert not _listed(BI, store["hard_stops"]) and _listed(BI, store["soft_stops"])
    assert not any(isinstance(i, dict) and i.get("type") == "hard_stop"
                   for i in store.get("cross_issues_last") or [])
    pkg = store["package_sqs"]
    assert pkg["cap_applied"] != HARD_STOP_CAP, pkg.get("cap_reason")
    bi_cards = [i for i in store.get("structured_issues") or []
                if i.get("code") == "bi_missing_period_of_restoration"]
    assert all((i.get("severity") or i.get("type")) != "hard_stop" for i in bi_cards)


def _functions(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            calls = {getattr(c.func, "id", getattr(c.func, "attr", None))
                     for c in ast.walk(fn) if isinstance(c, ast.Call)}
            yield fn, calls


def test_no_scorer_runs_the_cross_form_rules_without_the_severity_door():
    """ANTI-ROT. A function that runs the cross-form rules AND scores the
    package must decide their severity through `cross_form_severity` (or take
    the lists from the stops door). The re-promotion lived in exactly this
    shape: an inline `split_cross_form_issues` feeding `hard_stops`."""
    files = sorted((BACKEND / "services").glob("*.py")) + sorted((BACKEND / "routes").glob("*.py")) \
        + [BACKEND / "worker.py"]
    offenders = []
    for path in files:
        if path.name == "stops_now.py":
            continue
        for fn, calls in _functions(path):
            if "run_cross_form_validation" in calls and "calculate_package_sqs" in calls:
                if "cross_form_severity" not in calls and "stops_now" not in calls:
                    offenders.append(f"{path.name}:{fn.lineno} {fn.name}")
    assert not offenders, "re-promotes cross-form hard stops:\n" + "\n".join(offenders)
    # ...and the two inline post-form scorers this change fixed are among them
    names = {fn.name for p in (BACKEND / "routes" / "form_routes.py",
                               BACKEND / "services" / "arq_service.py")
             for fn, calls in _functions(p) if "cross_form_severity" in calls}
    assert {"update_pdf", "recalculate_session_scores"} <= names


def test_the_door_has_no_severity_branch_on_pre_form():
    """`pre_form` picks the scope and the form-choice deferral, never the
    severity: no `hard += cf_hard` path is left in the door."""
    src = (BACKEND / "services" / "stops_now.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "stops_now")
    seg = ast.get_source_segment(src, fn)
    assert "hard += list(cf_hard)" not in seg
    assert "cross_form_severity(cross)" in seg


# ── no "Becomes a hard stop when ... is generated" ───────────────────────────

def test_nothing_becomes_a_hard_stop_at_generation():
    # The retired shims were removed once nothing called them (14 Oct 2026).
    for name in ("generation_tag", "becomes_hard_at_generation", "with_generation_hard_stops"):
        assert not hasattr(sn, name), name


def test_the_review_view_emits_no_becomes_hard_tag_or_count():
    session = _session()
    st = sn.stops_now(session, None, pre_form=True)
    structured = build_structured_from_sources(legacy_hard=st["evaluate_hard"],
                                               legacy_soft=st["evaluate_soft"],
                                               cross_issues=st["cross_issues"])
    # a package stored before 14 Oct still carries the old entries: ignored
    stale = {"becomes_hard_at_generation": [{
        "code": "bi_missing_period_of_restoration", "message": BI, "forms": ["ACORD_140"],
        "tag": "Becomes a hard stop when ACORD 140 is generated"}]}
    view = grouped_with_package_caps(structured, st["hard"], st["soft"], stale, facts=session["facts"])
    rows = [it for c in view["hard_stops"] for it in c["items"]] + \
        [it for t in view["warnings"].values() for c in t for it in c["items"]]
    assert rows, "the view draws the package's rows"
    assert "becomes_hard" not in view
    assert not any("becomes_hard_tag" in r or "becomes_hard_forms" in r for r in rows)
    with pytest.raises(TypeError):
        from services.issue_registry import build_grouped_view
        build_grouped_view([], [], [], becomes_hard=[])


def test_the_pre_form_payload_carries_no_generation_hard_stops(monkeypatch):
    from routes import form_routes as fr
    from services import form_dry_run as fdr

    async def no_dry(*_a, **_k):
        return None

    monkeypatch.setattr(fdr, "dry_run_payload", no_dry)
    monkeypatch.setattr(fr, "current_package_sqs", lambda *a, **k: {"package_sqs_score": 41})
    row = _session()
    pkg, _kd = asyncio.run(fr._pre_form_status("sid-one-status", row["facts"], row["flags"], {},
                                               {"id": "u"}, session_row=row))
    assert "becomes_hard_at_generation" not in (pkg or {})
