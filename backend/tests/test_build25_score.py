"""Build 25, lane A (23 Oct 2026) - Brent's 23 Oct answers, items 1 and 2.

Item 1 (Z34-1 #1, Brent: "Yes, this is acceptable. Especially since we've already
downgraded the fill rate."): the PACKAGE score is independent of the forms. After
forms it is the before-forms recipe (no Form Fill Rate slice) on every path -
generation, save, recalculation, the worker - and the fill rate is the "Forms ready"
meter (values to confirm, boxes to fill) instead of a slice of the number. Per-form
scores are unchanged (Brent's Q4 is TBD).

Item 2 (Z34-1 #2): (a) an attested No Known Losses nothing contradicts keeps its logic
(left out of the score) but reads "Unable to Verify / Confirmation Required", never
"Not Applicable"; (b) loss-run years are judged against the years the business has
existed - full credit at min(5, age rounded up), "5 years preferred" only for a 5+
year business, unknown age keeps the 5-year rule, an older business keeps the
shortfall as incomplete.
"""
from __future__ import annotations

import ast
import copy
import inspect
import json
import pathlib
import shutil
import subprocess

import pytest

from services import loss_history_state as lhs
from services import sqs_service as sq

BACKEND = pathlib.Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
UTILS = ROOT / "frontend" / "src" / "utils"
MODAL = ROOT / "frontend" / "src" / "components" / "form" / "AcordModal.jsx"
RAIL = ROOT / "frontend" / "src" / "components" / "form" / "review" / "ReviewRailLayout.jsx"


def _env(v, source="producer"):
    return {"value": v, "source": source, "confidence": "producer"}


def _complete_facts():
    f = {k: _env("x") for k in list(sq.TIER1_FIELDS) + list(sq.TIER2_FIELDS)}
    f.update({"applicant_name": _env("Acme LLC"), "effective_date": _env("01/01/2027"),
              "expiration_date": _env("01/01/2028"), "contact_name": _env("Dana"),
              "num_employees": _env("41"), "naics_code": _env("238210"),
              "total_revenue": _env("$5,000,000"), "years_in_business": _env("17"),
              "fein": _env("12-3456789"), "operations_description": _env("Electrical contractor")})
    return f


def _score(facts, **kw):
    base = dict(facts=facts, flags={}, form_results=[], cross_issues=[], hard_stops=[],
                soft_stops=[], session_data={"docs": [], "sqs_history": []}, _probe=True)
    base.update(kw)
    return sq.calculate_package_sqs(**base)


# ══ Item 1 - one package score before and after forms ═════════════════════════
@pytest.mark.parametrize("fill", [0, 40, 93, 100])
def test_a_form_fill_rate_never_moves_the_package_score(fill):
    facts = _complete_facts()
    before = _score(facts)
    after = _score(facts, form_results=[{"form_id": "ACORD_125", "confidence_fill_rate": fill},
                                        {"form_id": "ACORD_126", "confidence_fill_rate": fill}],
                   mapped_data={"A": "x", "B": None}, confidence_dict={"A": "ai_low"},
                   calculation_stage="form_generated")
    assert after["package_sqs_score"] == before["package_sqs_score"]
    assert after["raw_sqs_score"] == before["raw_sqs_score"]
    assert after["pillars"] == before["pillars"]
    rows = after["score_trace"]["structural"]
    assert len(rows) == 2 and all("fill" not in str(r).lower() for r in rows), rows


def test_mapped_data_alone_never_brings_the_slice_back():
    facts = _complete_facts()
    assert (_score(facts, mapped_data={"A": "x"}, confidence_dict={"A": "ai_low"})["package_sqs_score"]
            == _score(facts)["package_sqs_score"])


def test_the_default_recipe_is_the_without_forms_one():
    assert inspect.signature(sq.calculate_package_sqs).parameters["form_fill"].default is False


def test_a_post_form_score_prints_one_number():
    """`without_forms` was the second number ("Without forms X · With forms Y"); with
    one recipe there is nothing to compare, so a post-form score carries none."""
    facts = _complete_facts()
    session = {"facts": facts, "flags": {}, "docs": [], "sqs_history": [],
               "generated_forms": {"ACORD_125": {}}, "selected_form_ids": ["ACORD_125"]}
    pkg = sq.calculate_package_sqs(facts=facts, flags={}, cross_issues=[], hard_stops=[], soft_stops=[],
                                   form_results=[{"form_id": "ACORD_125", "confidence_fill_rate": 80}],
                                   session_data=session, calculation_stage="form_generated")
    assert pkg["without_forms"] is None


def test_after_forms_equals_the_before_forms_door_on_the_same_stops():
    """The score generation persists equals `package_sqs_without_forms` - the
    before-forms recipe - when the forms add no check of their own."""
    facts = _complete_facts()
    session = {"facts": facts, "flags": {}, "docs": [], "sqs_history": [],
               "recommendations": [{"form_id": "ACORD_125"}]}
    before = sq.package_sqs_without_forms(session)
    after = sq.calculate_package_sqs(
        facts=facts, flags={}, cross_issues=[], hard_stops=[], soft_stops=[],
        form_results=[{"form_id": "ACORD_125", "confidence_fill_rate": 55}],
        session_data={**session, "generated_forms": {"ACORD_125": {}}},
        calculation_stage="form_generated")
    assert after["package_sqs_score"] == before["package_sqs_score"]


def test_per_form_scores_keep_their_own_fill_rate():
    """Brent's Q4 is TBD: a form's own score still counts its boxes."""
    facts = _complete_facts()
    common = dict(facts=facts, flags={}, form_schema={"a": {}, "b": {}, "c": {}, "d": {}},
                  selected_form_ids=["ACORD_125"], hard_stops=[], soft_stops=[],
                  tier2_score=100, form_id="ACORD_125")
    full = sq.calculate_sqs(mapped_data={"a": "1", "b": "2", "c": "3", "d": "4"},
                            confidence_dict={k: "producer" for k in "abcd"}, **common)
    thin = sq.calculate_sqs(mapped_data={"a": "1", "b": None, "c": None, "d": None},
                            confidence_dict={"a": "ai_low"}, **common)
    assert thin["confidence_fill_rate"] < full["confidence_fill_rate"]


_SCORERS = {"calculate_package_sqs", "_PACKAGE_SCORER"}
_PROD = [BACKEND / "services", BACKEND / "routes", BACKEND / "worker.py"]


def _prod_files():
    for p in _PROD:
        yield from ([p] if p.is_file() else sorted(p.rglob("*.py")))


def test_no_production_caller_brings_the_fill_slice_back():
    """Every package-score path after forms is the without-forms recipe: no call
    may pass `form_fill` anything but a literal False (the default)."""
    bad = []
    for path in _prod_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
            if name not in _SCORERS:
                continue
            for kw in node.keywords:
                if kw.arg != "form_fill":
                    continue
                if isinstance(kw.value, ast.Constant) and kw.value.value is False:
                    continue
                # The scorer's own probe forwards its caller's value (always False).
                if (path.name == "sqs_service.py" and isinstance(kw.value, ast.Name)
                        and kw.value.id == "form_fill"):
                    continue
                bad.append(f"{path.relative_to(BACKEND)}:{node.lineno}")
    assert not bad, bad


# ══ Item 2a - "Unable to Verify / Confirmation Required" ═════════════════════
_WORDS = "Unable to Verify / Confirmation Required"
_ATTESTED = "no_known_losses_not_applicable"


def _attested_account():
    facts = {"applicant_name": "Acme Roofing LLC", "years_in_business": "12",
             "lines_of_business": ["General Liability"],
             "loss_history_no_prior_losses_indicator": _env("Yes - no known losses", "client_arq")}
    return facts, {"has_general_liability": True, "no_prior_losses": True}


def test_the_attested_state_keeps_its_logic():
    facts, flags = _attested_account()
    assert lhs.attested_no_losses_not_applicable(facts, flags) is True
    score, recs = sq.calculate_p4_loss_history(facts, flags)
    assert score is None                                   # still left out of the score
    assert recs == [sq._ATTESTED_NOT_APPLICABLE_REC]
    assert sq._get_loss_history_state(facts, flags) == _ATTESTED


def test_the_attested_state_reads_unable_to_verify():
    label = sq.LOSS_HISTORY_STATE_LABELS[_ATTESTED]
    assert label.startswith(_WORDS) and "not applicable" not in label.lower()
    rec = sq._ATTESTED_NOT_APPLICABLE_REC
    assert _WORDS in rec and "not applicable" not in rec.lower()
    assert "—" not in rec and "—" not in label
    # Still a status notice: routes to no field, never reads as "needs a document".
    assert sq.loss_recommendation_field(rec) is None
    assert any(p in rec.lower() for p, _f in sq._LOSS_RECOMMENDATION_FIELDS)
    assert not any(p in rec.lower() for p in ("no loss history provided", "loss runs", "required for carrier"))
    assert rec in sq._LOSS_NOT_APPLICABLE_NOTICES
    # The other two Not Applicable routes are genuinely Not Applicable - unchanged.
    assert "Not Applicable" in sq._NEW_VENTURE_NOT_APPLICABLE_REC
    assert "Not Applicable" in sq._UNDER_A_YEAR_NOT_APPLICABLE_REC


def test_the_package_payload_says_it():
    facts, flags = _attested_account()
    pkg = sq.calculate_package_sqs(facts=facts, flags=flags, form_results=[], cross_issues=[],
                                   hard_stops=[], soft_stops=[], session_data={"docs": [], "sqs_history": []})
    assert pkg["pillars"]["loss_history_alignment"] is None
    assert pkg["loss_history_state"] == _ATTESTED
    assert sq.LOSS_HISTORY_STATE_LABELS[pkg["loss_history_state"]].startswith(_WORDS)


def test_the_screen_says_it_where_it_said_not_applicable():
    src = MODAL.read_text(encoding="utf-8")
    assert f'no_known_losses_not_applicable:  "{sq.LOSS_HISTORY_STATE_LABELS[_ATTESTED]}"' in src
    assert 'const UNABLE_TO_VERIFY = "Unable to Verify / Confirmation Required";' in src
    # Every pillar chip asks the one helper, never a bare "N/A".
    assert src.count("{pillarNaText(key, ") == 3
    assert ">N/A</span>" not in src
    assert "Not applicable - No Known Losses attested" not in src


# ══ Item 2b - loss-run years by the years the business has existed ═══════════
def _runs(age, years, **extra):
    facts = {"loss_history_years": str(years), "loss_run_age_days": "30", "prior_carrier": "EMC", **extra}
    if age is not None:
        facts["years_in_business"] = str(age)
    return sq.calculate_p4_loss_history(facts, {}, has_loss_run_doc=True, loss_run_match="strong")


@pytest.mark.parametrize("age,years,score", [
    ("1", 1, 100), ("2", 2, 100), ("3", 3, 100), ("2.1", 3, 100), ("4", 4, 100),
    ("4", 3, 85), ("4.5", 4, 85), ("4.5", 3, 85), ("2.5", 2, 70), ("1.5", 1, 70), ("3", 2, 70),
    ("0", 1, 100), ("0.4", 1, 100),
])
def test_runs_are_judged_against_the_business_age(age, years, score):
    got, recs = _runs(age, years)
    assert got == score, (age, years, recs)
    assert not any("5 years preferred" in r for r in recs)     # never said to a young business
    if score < 100:
        r = next(r for r in recs if r.startswith("Loss history incomplete"))
        assert f"cover {years} of the {age} year" in r
        assert sq.loss_recommendation_field(r) == "loss_history_years"
        assert "—" not in r


@pytest.mark.parametrize("age", ["5", "12", None, "", "not known"])
@pytest.mark.parametrize("years,score,words", [
    (5, 100, None), (7, 100, None),
    (4, 85, "3 years of loss runs provided - 5 years preferred for full credit"),
    (3, 85, "3 years of loss runs provided - 5 years preferred for full credit"),
    (2, 70, "Loss history incomplete - fewer than 3 years provided"),
    (1, 70, "Loss history incomplete - fewer than 3 years provided"),
])
def test_an_established_or_unknown_age_keeps_todays_rule(age, years, score, words):
    got, recs = _runs(age, years)
    assert got == score
    if words:
        assert words in recs


def test_unreadable_years_are_not_full_credit_for_a_new_business():
    """The minimum of one year: a run whose claim years are unreadable (0) is
    Path B, never "covers the whole life of a 0-year business"."""
    got, _ = _runs("0", 0)
    assert got == 60                                           # Path B, strong match - unchanged


@pytest.mark.parametrize("raw,required", [
    (None, None), ("", None), ("abc", None), ("-1", None), ("nan", None),
    ("0", 1), ("0.4", 1), ("1", 1), ("2.1", 3), ("3", 3), ("4.2", 5), ("5", 5), ("12", 5),
    ("1,000", 5), ("inf", 5),
])
def test_loss_years_required(raw, required):
    facts = {} if raw is None else {"years_in_business": raw}
    assert lhs.loss_years_required(facts) == required


@pytest.mark.parametrize("raw,band", [
    ("0.5", lhs.BAND_YOUNG), ("1", lhs.BAND_YOUNG), ("3", lhs.BAND_ESTABLISHING),
    ("4.9", lhs.BAND_ESTABLISHING), ("5", lhs.BAND_ESTABLISHED), ("12", lhs.BAND_ESTABLISHED),
    ("", lhs.BAND_UNKNOWN), ("-2", lhs.BAND_UNKNOWN), ("twelve", lhs.BAND_UNKNOWN),
])
def test_the_band_reads_the_same_years(raw, band):
    assert lhs.years_in_business_band({"years_in_business": raw}) == band


def test_the_per_form_score_uses_the_same_rule():
    facts = {"loss_history_years": "3", "loss_run_age_days": "30", "prior_carrier": "EMC",
             "years_in_business": "3", "applicant_name": "Acme LLC"}
    res = sq.calculate_sqs(facts=facts, flags={}, mapped_data={"a": "x"}, form_schema={"a": {}},
                           selected_form_ids=["ACORD_125"], hard_stops=[], soft_stops=[],
                           tier2_score=80, form_id="ACORD_125", has_loss_run_doc=True,
                           loss_run_match="strong")
    assert res["breakdown"]["loss_history_alignment"] == 100


# ══ Frontend: one number, and the Forms ready meter ═══════════════════════════
def _node(tmp_path, module, body):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    script = tmp_path / "check.mjs"
    script.write_text(f"import * as M from {json.dumps((UTILS / module).as_uri())};\n" + body + "\n",
                      encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


_ATTENTION = {"forms": [
    {"form_id": "ACORD_125", "form_label": "ACORD 125", "rows": [
        {"status": "verify"}, {"status": "verify"}, {"status": "missing"},
        {"status": "missing", "applicant_step": True}, {"status": "ai_held_back"}]},
    {"form_id": "ACORD_126", "form_label": "ACORD 126", "rows": [{"status": "verify"}]},
    {"form_id": "ACORD_101", "form_label": "ACORD 101", "rows": []},
]}


def test_the_forms_ready_meter(tmp_path):
    out = _node(tmp_path, "scoreWithForms.js", f"""
const att = {json.dumps(_ATTENTION)};
console.log(JSON.stringify({{
  all: M.formsReady(att), one: M.formsReady(att, "ACORD_125"), empty: M.formsReady(att, "ACORD_101"),
  none: M.formsReady(undefined), failed: M.formsReady(null),
  clean: M.formsReadyText({{verify: 0, missing: 0}}), single: M.formsReadyText({{verify: 1, missing: 1}}),
  gone: typeof M.formsEffect,
}}));""")
    assert out["all"]["overall"] == {"verify": 3, "missing": 1,
                                     "text": "Forms ready: 3 values to confirm · 1 box to fill",
                                     "detail": "3 values to confirm · 1 box to fill"}
    assert out["one"]["form"]["text"] == "Forms ready: 2 values to confirm · 1 box to fill"
    assert out["empty"]["form"]["text"] == "Forms ready: nothing left to confirm or fill"
    assert [f["form_id"] for f in out["all"]["forms"]] == ["ACORD_125", "ACORD_126", "ACORD_101"]
    assert out["none"] is None and out["failed"] is None
    assert out["single"] == "Forms ready: 1 value to confirm · 1 box to fill"
    assert out["clean"] == "Forms ready: nothing left to confirm or fill"
    assert out["gone"] == "undefined"
    assert "—" not in json.dumps(out, ensure_ascii=False)


def test_the_fill_rate_row_is_gone_from_the_score_list(tmp_path):
    pkg = {"package_sqs_score": 99, "without_forms": {"score": 100},
           "weights_used": {"structural_completeness": 0.25},
           "pillars": {"structural_completeness": 98},
           "category_breakdown": {"structural_completeness": {"fill": {"score": 93, "weight": 0.25}}},
           "top_recommendations": []}
    out = _node(tmp_path, "recommendations.js", f"""
const m = M.buildRecommendations({{packageSqs: {json.dumps(pkg)}, attention: {json.dumps(_ATTENTION)}, formsExist: true}});
console.log(JSON.stringify({{ids: m.score.map((s) => s.id), fill: typeof M.fillRateItem, left: typeof M.scoreLeftOnForms}}));""")
    assert "score:fill" not in out["ids"]
    assert out["fill"] == "undefined" and out["left"] == "undefined"


def test_both_screens_draw_the_meter_where_the_two_numbers_were():
    rail = RAIL.read_text(encoding="utf-8")
    modal = MODAL.read_text(encoding="utf-8")
    for src in (rail, modal):
        assert "formsEffect" not in src and "data-forms-effect" not in src
        assert "Without forms" not in src
    assert 'data-forms-ready="review"' in rail and "formsReady(recAttention)" in rail
    assert "overview-forms-left" not in rail and "scoreLeftOnForms" not in rail
    assert "data-forms-ready-form={f.formId}" in rail          # each form's part
    assert 'data-forms-ready="editor"' in modal and "formsReady(formsAttention, activeFormId)" in modal
