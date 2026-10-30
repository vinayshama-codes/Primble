"""Strict hostile review, 29 Oct 2026 (offline, synthetic packages, no model / network).

1. A date fact that is not a string (an Excel serial 46023 read off a spreadsheet, a
   year 2027 from a model reply, a box value) raised inside `utils.validators.
   run_field_validations` (`date_str.strip()`), the package scorer failed, and the
   review page had NO score and NO plan - nothing listed to fix (R3). The format
   validators now read a scalar's text and skip a non-scalar.
2. The plan's stand-in for an expiration date was one year after the effective date
   on file - an ENDED term when that date is long past. The route refuses that save
   (`validators.term_save_refusal`), so the step did nothing and the card's points
   sat on no item ("P2 short by 15", repaired by the contract guard). The stand-in
   is now an expiration still to come.
"""
import logging
import os
import random

import pytest

import reach100_harness as H
from services import sqs_service as S
from utils.validators import run_field_validations


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("no model or network call")
    import httpx
    monkeypatch.setattr(httpx.Client, "send", refuse)
    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)
    monkeypatch.setenv("NARRATIVE_READER", "0")
    monkeypatch.setenv("EVIDENCE_JUDGE", "0")
    logging.getLogger("services.audit_service").setLevel(logging.CRITICAL)


# ── 1. a non-string fact never takes the score away ───────────────────────────
@pytest.mark.parametrize("value", [46023, 2027, 12.0, True, ["01/01/2027"], {"x": 1}])
@pytest.mark.parametrize("key", ["effective_date", "expiration_date", "fein", "contact_phone",
                                 "total_revenue", "coinsurance_percentage"])
def test_field_validations_read_any_fact_shape(key, value):
    hard, soft = run_field_validations({key: {"value": value, "source": "ai"},
                                        "effective_date": "01/01/2027"} if key != "effective_date"
                                       else {key: {"value": value, "source": "ai"}, "expiration_date": "01/01/2028"})
    assert isinstance(hard, list) and isinstance(soft, list)


def test_a_numeric_date_reads_as_its_digits_and_is_asked_to_be_corrected():
    _hard, soft = run_field_validations({"effective_date": 46023, "expiration_date": "01/01/2028"})
    assert any("Effective date '46023' could not be parsed" in s for s in soft)


@pytest.mark.parametrize("key,value", [("effective_date", 46023), ("expiration_date", 12),
                                       ("effective_date", True), ("expiration_date", 2027.0)])
def test_the_package_keeps_its_score_and_plan_with_a_non_string_date(key, value):
    row = H.contract_package(random.Random(24))
    row["facts"][key] = value
    pkg = S.current_package_sqs(row, None, None)
    assert pkg is not None and pkg.get("package_sqs_score") is not None
    pkg, _kd, _items = H.read_page(row)
    assert H.contract_problems(pkg) == []


# ── 2. the plan types an expiration a person can save ─────────────────────────
@pytest.mark.parametrize("value", ["2027", "46023", 12])
def test_an_unreadable_expiration_beside_an_old_start_reaches_100_and_adds_up(value):
    row = H.contract_package(random.Random(9))       # effective 03/15/2024, an ended term
    row["facts"]["expiration_date"] = {"value": value, "source": "ai"}
    pkg, _kd, _items = H.read_page(row)
    assert H.contract_problems(pkg) == []           # no "P2 short by 15" repair
    final, problems, _row = H.solve_contract(row)
    assert final == 100 and problems == []


def test_the_expiration_stand_in_is_never_an_ended_term():
    from datetime import date
    from services import review_plan as RP
    from services.normalization import normalize_date
    for eff in ("03/15/2024", "01/01/2019", None):
        facts = {"effective_date": {"value": eff, "source": "ai"}} if eff else {}
        out = RP._date_probe("expiration_date", facts)
        assert date.fromisoformat(normalize_date(out)) >= date.today(), (eff, out)
    # a current effective date still gets its own one-year term
    facts = {"effective_date": {"value": "12/01/2026", "source": "ai"}}
    assert RP._date_probe("expiration_date", facts) == "12/01/2027"


# ── 3. a dismissed card that still holds keeps its number on the page ─────────
# Before forms a dismissal never moves the score, so the plan still counts the
# card; the review page tucked it under "Resolved" with no number and the page's
# numbers added up to less than 100 minus the score (P2).
def _node(tmp_path, body):
    import json
    import shutil
    import subprocess
    import textwrap
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    front = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "frontend", "src"))
    helper = os.path.join(front, "utils", "screenPoints.js")
    js = tmp_path / "t.mjs"
    js.write_text(f"import * as SP from {json.dumps('file://' + helper)};\n" + textwrap.dedent(body))
    out = subprocess.run(["node", str(js)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_a_dismissed_card_still_firing_prints_its_plan_number(tmp_path):
    got = _node(tmp_path, """
        const pkg = { package_sqs_score: 85, review_plan: { items: [
          { id: "card:bi_missing", kind: "card", code: "bi_missing", issue_id: "iss_1", points: 3, exact: false,
            with_others: "counts when all 2 warnings are fixed" },
          { id: "card:cope", kind: "card", code: "cope", issue_id: "iss_2", points: 12, exact: true } ] } };
        const { cards } = SP.screenPoints(pkg, null, null);
        const live = { iid: "iss_1", status: "dismissed", live: true, item: { issue_id: "iss_1", message: "m" } };
        const gone = { iid: "iss_2", status: "dismissed", item: { issue_id: "iss_2" } };
        const fixed = { iid: "iss_2", status: "resolved", live: true, item: { issue_id: "iss_2" } };
        console.log(JSON.stringify([SP.dismissedRowPointsText(live, cards), SP.dismissedRowPointsText(gone, cards),
                                    SP.dismissedRowPointsText(fixed, cards), SP.dismissedRowPointsText(null, cards)]));
    """)
    assert got == ["+3 pts (counts when all 2 warnings are fixed)", "", "", ""]


def test_the_review_page_draws_the_number_on_its_resolved_rows():
    path = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "frontend",
                                         "src", "components", "form", "review", "ReviewRailLayout.jsx"))
    src = open(path, encoding="utf-8").read()
    assert "dismissedRowPointsText(r, screenPts.cards)" in src


# ── 4. a figure no float can hold is refused, never an OverflowError ──────────
@pytest.mark.parametrize("fact", ["total_revenue", "num_employees", "coinsurance_percentage", "gl_each_occurrence"])
@pytest.mark.parametrize("value", ["1" * 400, "1e400", "$" + "9" * 330])
def test_an_endless_number_is_refused_at_the_door_not_a_crash(fact, value):
    from routes.audit_routes import _validate_producer_answer
    from services.answer_semantics import build_fact_envelope, interpret_answer
    env = build_fact_envelope(fact, interpret_answer(fact, value), "producer", "filled")
    assert env.get("value") in (None, "")
    ok, err = _validate_producer_answer(fact, value)
    assert ok is False and err


def test_the_plan_copy_survives_an_endless_number():
    from services import review_plan as RP
    row = H.contract_package(random.Random(5))
    sim = RP._Sim(row)
    sim.answer("total_revenue", "1" * 400)        # raised OverflowError before
    pkg, _kd, _items = H.read_page(sim.session)
    assert pkg.get("package_sqs_score") is not None


# ── 5. the plan's copy re-runs the form recommender like the answer doors ─────
# Before forms an answer the recommender reads changes the recommended forms
# (`arq_service.refreshed_pre_form_recommendations`, every answer door's
# recalculation) and the stops follow those forms. The copy kept the page's list:
# "% subcontracted 25" added ACORD 186 and 126 for real, the row read +2, the
# save moved +1 (real-door replay, contract seed 18).
def test_the_plan_copy_follows_the_recommended_forms_an_answer_moves():
    import copy as _copy
    from services import review_plan as RP
    from services.arq_service import refreshed_pre_form_recommendations
    row = H.contract_package(random.Random(18))
    sim = RP._Sim(row)
    sim.measure()
    assert sim.form_ids == [r["form_id"] for r in row["recommendations"]]     # unmoved: the page's list
    before = _copy.deepcopy(sim.session)
    sim.answer("percent_subcontracted", "25")
    sim.measure()
    door = refreshed_pre_form_recommendations(sim.session, before)
    assert door is not None                                  # the door moves the list here
    assert sim.form_ids == [r["form_id"] for r in door["recommendations"]]
    assert "ACORD_186" in sim.form_ids


# ── An all-zero / one-digit FEIN is a placeholder (fixed 29 Oct) ───────────
@pytest.mark.parametrize("value", ["00-0000000", "000000000", "11-1111111", "99 999 9999"])
def test_an_all_zero_fein_is_not_an_answer(value):
    from routes.audit_routes import _validate_producer_answer
    ok, _err = _validate_producer_answer("fein", value)
    assert ok is False


def test_a_placeholder_fein_is_dropped_at_the_merge_like_an_extracted_na():
    from services.answer_semantics import extracted_non_answer
    from utils.validators import validate_fein
    assert extracted_non_answer("fein", "00-0000000") == "non_answer"
    assert extracted_non_answer("fein", {"value": "000000000", "source": "ai"}) == "non_answer"
    assert extracted_non_answer("fein", "84-1234567") is None
    assert extracted_non_answer("total_revenue", "000000000") is None   # FEIN facts only
    assert validate_fein("00-0000000")[0] is False
    assert validate_fein("84-1234567")[0] is True
    from routes.audit_routes import _validate_producer_answer
    assert _validate_producer_answer("fein", "12-3456789")[0] is True   # the plan's sample answer


# ── 2. a clipped company name is the same entity (Fixer 1, 29 Oct) ────────────
@pytest.mark.parametrize("a, b", [
    ("Summit Peak Casualty Compai", "Summit Peak Casualty Company"),
    ("Summit Peak Casualty Co.", "Summit Peak Casualty Compai"),
    ("Acme Corpor", "Acme Corporation"),
    ("SUMMIT PEAK CASUALTY COMPAN", "Summit Peak Casualty Company"),
])
def test_a_clipped_last_word_is_the_same_entity(a, b):
    from services.normalization import same_entity_name
    assert same_entity_name(a, b) and same_entity_name(b, a)


@pytest.mark.parametrize("a, b", [
    ("ABC Roofing", "ABC Roofers Supply"),
    ("ABC Roofing", "ABC Roofers"),
    ("Summit Peak Casualty", "Summit Peak Insurance"),
    ("Acme LLC", "Acme Inc"),
    ("Acme", "Acme Holdings"),
    ("Summit Peak Casualty Com", "Summit Peak Casualty Company"),   # under 4 letters
    ("North Peak Casualty Company", "Summit Peak Casualty Company"),
])
def test_two_different_names_are_never_joined(a, b):
    from services.normalization import same_entity_name
    assert not same_entity_name(a, b) and not same_entity_name(b, a)


def test_the_131_underlying_gl_insurer_prints_the_whole_name():
    from services import pdf_service as P
    f = {"_form_id": "ACORD_131", "has_umbrella": True,
         "coverage_lines": [{"line": "General Liability", "carrier": "Summit Peak Casualty Compai",
                             "policy_number": "CGL-4471209-25", "premium": "$28,416"}],
         "underlying_policies": [{"line": "General Liability",
                                  "carrier": "Summit Peak Casualty Company",
                                  "policy_number": "CGL-4471209-25"}]}
    box = "UnderlyingPolicy_GeneralLiability_InsurerFullName_A"
    assert P._resolve_underlying_policy_row(box, f) == "Summit Peak Casualty Company"
    f["underlying_policies"][0]["carrier"] = "Summit Peak Insurance"
    assert P._resolve_underlying_policy_row(box, f) is None     # a real conflict stays blank


# ── 3. a table cell that cannot be its type is not stored (Fixer 1, 29 Oct) ───
def test_impossible_table_cells_are_stored_blank_and_named():
    from services import schedule_capture as SC
    rows, rep = SC.validate_rows("auto_vin_schedule",
                                 [{"vin": "1HGCM82633A004352" + "X" * 23, "year": "99999", "make": "Ford"}])
    assert rows[0]["vin"] == "" and rows[0]["year"] == "" and rows[0]["make"] == "Ford"
    assert set(rep["refused"]["0"]) == {"vin", "year"}
    rows, rep = SC.validate_rows("loss_history",
                                 [{"date": "13/45/2022", "paid": "abc", "description": "Slip"},
                                  {"date": "05/17/2022", "paid": "$1,200", "description": "Hail",
                                   "reserved_amount": "1" * 30}])
    assert rows[0]["date"] == "" and rows[0]["paid"] == ""
    assert rows[1]["paid"] == "$1,200" and rows[1]["reserved_amount"] == ""
    assert set(rep["refused"]["0"]) == {"date", "paid"} and "reserved_amount" in rep["refused"]["1"]
    assert SC.refusal_message(rep).startswith("Row 1:")


def test_advisory_cells_stay_advisory():
    from services import schedule_capture as SC
    rows, rep = SC.validate_rows("auto_vin_schedule",
                                 [{"vin": "1HGCM82633A00435", "year": "1979", "make": "Ford"}])
    assert rows[0]["vin"] == "1HGCM82633A00435" and rows[0]["year"] == "1979"   # short VIN kept
    assert rep["refused"] == {}
    rows, rep = SC.validate_rows("loss_history",
                                 [{"date": "5/17/22", "paid": "None", "description": "Hail"}])
    assert rows[0]["date"] == "5/17/22" and rows[0]["paid"] == "None" and rep["refused"] == {}


def test_a_cell_left_as_the_table_showed_it_is_not_refused():
    from services import schedule_capture as SC
    shown = [{"date": "13/45/2022", "paid": "abc", "description": "Slip"}]
    rows, rep = SC.validate_rows("loss_history", [dict(shown[0])], shown=shown)
    assert rows[0]["date"] == "13/45/2022" and rep["refused"] == {}


# ── 4. counts print whole; 30 digits are refused (Fixer 1, 29 Oct) ───────────
@pytest.mark.parametrize("value, printed", [(12.0, "12"), ("12.0", "12"), ("1,200", "1,200"),
                                            (12, "12"), ("approx. 25", "approx. 25")])
def test_a_count_prints_as_a_whole_number(value, printed):
    from services.display_canonicalizer import canonicalize_for_field
    assert canonicalize_for_field("BusinessInformation_FullTimeEmployeeCount_A", value) == printed


def test_thirty_digits_are_noise_at_the_door_and_on_the_form():
    from services.display_canonicalizer import canonicalize_for_field
    from routes.audit_routes import _validate_producer_answer
    big = "1" * 30
    assert canonicalize_for_field("BusinessInformation_FullTimeEmployeeCount_A", big) == ""
    assert canonicalize_for_field("CommercialPolicy_AnnualRevenueAmount_A", big) == ""
    assert canonicalize_for_field("CommercialPolicy_AnnualRevenueAmount_A", 1.2e29) == ""
    three = "$1,000,000 / $2,000,000 / $3,000,000"            # three amounts, not one number
    assert canonicalize_for_field("CommercialPolicy_AnnualRevenueAmount_A", three) == three
    assert canonicalize_for_field("AdditionalInterest_MailingAddress_CountryCode_A", "US") == "US"
    for fact in ("total_revenue", "num_employees"):
        assert _validate_producer_answer(fact, big)[0] is False
    assert _validate_producer_answer("total_revenue", "$999,999,999,999,999")[0] is True


# ── 5. a non-list coverage_lines never takes the loss-run verdict (29 Oct) ────
@pytest.mark.parametrize("bad", ["General Liability", {"line": "GL"}, 5, None])
def test_a_non_list_coverage_lines_is_no_rows(bad):
    from services.loss_run_identity import _package_identity, match_loss_run_identity
    out = _package_identity([{"facts": {"coverage_lines": bad}}], {"coverage_lines": bad})
    assert out["policy"] == [] and out["carrier"] == []
    match_loss_run_identity([{"facts": {"coverage_lines": bad}, "doc_type": "dec_page"}],
                            "Acme LLC", {"coverage_lines": bad})


# ── An individual / sole proprietor may have no EIN (Fixer 1, 29 Oct) ────────
@pytest.mark.parametrize("entity, allowed", [("Sole Proprietor", True), ("Individual", True),
                                             ("Sole Proprietorship", True), ("LLC", False),
                                             ("Corporation", False), (None, False)])
@pytest.mark.parametrize("answer", ["N/A", "None", "No EIN"])
def test_a_fein_absence_is_an_answer_only_for_an_individual(entity, allowed, answer):
    from routes.audit_routes import _validate_producer_answer
    from services.answer_semantics import NOT_APPLICABLE, UNKNOWN, interpret_answer
    facts = {"entity_type": {"value": entity, "source": "producer"}} if entity else {}
    assert _validate_producer_answer("fein", answer, facts)[0] is allowed
    assert interpret_answer("fein", answer, facts=facts).intent == (NOT_APPLICABLE if allowed else UNKNOWN)
    assert _validate_producer_answer("fein", answer)[0] is False          # no package = refused


def test_an_individuals_na_fein_is_not_applicable_never_missing_and_follows_the_entity():
    from services.answer_semantics import build_fact_envelope, interpret_answer
    facts = {"entity_type": {"value": "Sole Proprietor", "source": "producer"}}
    facts["fein"] = build_fact_envelope("fein", interpret_answer("fein", "None", facts=facts),
                                        "producer", "filled")
    applicable, missing = S._tier2_entries(facts)
    assert not any("fein" in k for k, _ in applicable + missing)      # out of the denominator
    facts["entity_type"] = {"value": "LLC", "source": "producer"}     # the entity moved
    applicable, missing = S._tier2_entries(facts)
    assert any("fein" in k for k, _ in missing)                        # a gap again
