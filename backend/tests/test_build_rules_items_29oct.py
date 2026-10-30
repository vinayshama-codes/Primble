"""Michelle review, 29 Oct 2026 - the owner-approved builds (items 1, 2, 3, 5, 6).

Each test is a CLASS of package, never one fixture's values; the end-to-end
tests read the review page the way the route does (`reach100_harness.read_page`)
and answer it the way a producer would (`solve_contract`), so the scoring
contract (SCORING_RULES.md) is checked on every reading.

1. A proposed term starting after the current policies end is a WARNING (85):
   answerable on the page (effective date), listed with points, cleared by a
   confirmed or corrected date, never a hard stop; the wording names both dates
   and the uncovered days.
2. One document stating two different totals is asked in its own words
   ("<file> states more than one amount for <fact> (x, y)"), holds 85, and the
   Data Consistency pick clears it.
3. An application asking for a different limit / deductible / SIR than the
   current policy is an information note - never scored, never holding (P5).
5. A Data Consistency card's suggestion is the value the forms print, for every
   kind of fact (not only money).
6. "Period of restoration missing" stands down on an Actual Loss Sustained BI
   coverage, and stays on a period-of-restoration form.
"""
from __future__ import annotations

import copy
import os
import random
import sys

os.environ.setdefault("OPENAI_API_KEY", "sk-offline")
os.environ.setdefault("EVIDENCE_JUDGE", "0")
os.environ.setdefault("NARRATIVE_READER", "0")
sys.path.insert(0, os.path.dirname(__file__))

import pytest  # noqa: E402


def _env(v, source="ai"):
    return {"value": v, "source": source, "confidence": "ai_high"}


def _doc(i, doc_type, text="", **facts):
    return {"doc_id": f"d{i}", "filename": f"{doc_type}_{i}.pdf", "doc_type": doc_type,
            "text": text, "facts": {k: _env(v) for k, v in facts.items()}}


_ID = dict(applicant_name="Acme Plumbing LLC", fein="12-3456789")


def _assess(docs, merged=None, confirmations=None):
    from services.underwriting_consistency import assess_underwriting_consistency
    return assess_underwriting_consistency(docs, merged or {}, confirmations or {})


def _conflicts(docs, merged=None):
    return {f["fact_key"]: f for f in _assess(docs, merged)["fields"] if f["status"] == "conflict"}


@pytest.fixture(scope="module")
def solved_row():
    """A random synthetic package answered to exactly 100 - the base each
    end-to-end test adds ONE problem to."""
    import reach100_harness as H
    row = H.synthetic_package(random.Random(3))
    score, problems, row = H.solve_contract(row)
    assert score == 100 and not problems
    for d in row["docs"]:
        d.setdefault("doc_id", d["filename"])
    return row


# ── 1. Coverage gap between the current term and the proposed one ───────────
def _with_gap(row, eff="01/01/2027", end="12/01/2026"):
    row = copy.deepcopy(row)
    f = row["facts"]
    f["effective_date"] = {"value": eff, "source": "acord_form", "confidence": "acord_exact"}
    f["expiration_date"] = {"value": eff[:6] + str(int(eff[6:]) + 1), "source": "acord_form",
                            "confidence": "acord_exact"}
    f["prior_expiration_date"] = {"value": end, "source": "ai", "routed_from": "current_term"}
    for d in row["docs"]:
        (d.get("facts") or {}).pop("effective_date", None)
        (d.get("facts") or {}).pop("expiration_date", None)
    return row


def test_the_gap_wording_names_both_dates_and_the_uncovered_days():
    from services.cross_form_validator import _check_proposed_term_coverage_gap as check
    facts = {"effective_date": _env("01/01/2027"),
             "prior_expiration_date": {"value": "12/01/2026", "source": "ai",
                                       "routed_from": "current_term"}}
    (issue,) = check(facts, {}, set())
    m = issue["message"]
    assert "01/01/2027" in m and "12/01/2026" in m and "31 days with no coverage" in m
    assert issue["type"] == "soft_warning"


def test_the_gap_is_a_listed_warning_with_points_and_a_confirm_clears_it(solved_row):
    import reach100_harness as H
    row = _with_gap(solved_row)
    pkg, _kd, items = H.read_page(row)
    assert pkg["package_sqs_score"] == 85 and pkg["cap_applied"] == 85      # a warning, never 60
    plan = pkg["review_plan"]["items"]
    gap = [i for i in plan if i.get("code") == "proposed_term_coverage_gap"]
    assert gap and int(gap[0]["points"]) > 0
    card = next(i for i in items if i.get("code") == "proposed_term_coverage_gap")
    assert card["resolution"]["mode"] == "field" and card["resolution"]["facts"] == ["effective_date"]
    assert H.contract_problems(pkg) == []
    score, problems, after = H.solve_contract(row)
    assert score == 100 and problems == []


@pytest.mark.parametrize("fixed", ["12/01/2026", "12/02/2026"])
def test_moving_the_date_to_meet_the_current_term_clears_the_gap(fixed):
    from services.cross_form_validator import _check_proposed_term_coverage_gap as check
    facts = {"effective_date": _env(fixed),
             "prior_expiration_date": {"value": "12/01/2026", "source": "ai",
                                       "routed_from": "current_term"}}
    assert check(facts, {}, set()) == []


def test_the_gap_is_never_a_hard_stop_after_the_pre_form_demotion(solved_row):
    from services.stops_now import stops_now
    st = stops_now(_with_gap(solved_row), pre_form=True)
    assert not any("days with no coverage" in m for m in st["hard"])
    assert any("days with no coverage" in m for m in st["soft"])


# ── 2. One document contradicting its own total ─────────────────────────────
_TWO_TOTALS = "Total Payroll: $2,620,000\nNotes\nTotal annual payroll $2,900,000\n"


def test_one_document_two_totals_names_the_file_the_fact_and_the_amounts():
    d = _doc(1, "application", text=_TWO_TOTALS, total_payroll="$2,620,000", **_ID)
    card = _conflicts([d])["total_payroll"]
    assert card["one_document"] == "application_1.pdf"
    r = card["conflict_reason"]
    assert r.startswith("application_1.pdf states more than one amount for ")
    assert "$2,620,000" in r and "$2,900,000" in r and "confirm which one is right" in r
    assert "documents" not in r


def test_two_documents_keep_the_documents_wording():
    dec = _doc(1, "dec_page", total_revenue="$8,450,000", **_ID)
    app = _doc(2, "application", total_revenue="$9,200,000", **_ID)
    card = _conflicts([dec, app])["total_revenue"]
    assert card["one_document"] is None
    from services.stops_now import underwriting_conflict_stops
    uw = _assess([dec, app])
    (msg,) = [m for k, m, _b in underwriting_conflict_stops(uw, {}, [dec, app]) if k == "total_revenue"]
    assert ": documents disagree (" in msg


def test_the_one_document_warning_holds_85_and_the_pick_clears_it(solved_row):
    import reach100_harness as H
    row = copy.deepcopy(solved_row)
    f = row["facts"]
    payroll = H._fv0(f, "total_payroll") or "500000"
    f["total_payroll"] = _env(payroll)
    other = str(int(str(payroll).replace(",", "").replace("$", "")) + 280000)
    row["docs"].append({"doc_id": "app1", "filename": "application.pdf", "doc_type": "application",
                        "text": f"Total Payroll: {payroll}\nNotes\nTotal annual payroll ${int(other):,}\n",
                        "facts": {"total_payroll": _env(payroll),
                                  "applicant_name": copy.deepcopy(f["applicant_name"])}})
    row["underwriting_consistency"] = _assess(row["docs"], f)
    from services.stops_now import stops_now
    st = stops_now(row, pre_form=True)
    mine = [m for m in st["soft"] if "application.pdf states more than one amount for" in m]
    assert mine and not any("application.pdf" in m for m in st["hard"])
    pkg, _kd, _items = H.read_page(row)
    assert pkg["cap_applied"] == 85
    dc = [i for i in pkg["review_plan"]["items"] if i.get("kind") == "dc"
          and i.get("fact") == "total_payroll"]
    assert dc and int(dc[0]["points"]) > 0
    assert H.contract_problems(pkg) == []
    score, problems, after = H.solve_contract(row)
    assert score == 100 and problems == []
    assert "total_payroll" in (after.get("underwriting_confirmations") or {})


# ── 3. Requested vs current coverage: information only ──────────────────────
def _requested_docs(req="$2,000,000", cur="$1,000,000"):
    dec = _doc(1, "dec_page", umbrella_limit=cur, **_ID)
    app = _doc(2, "application", umbrella_limit=req, **_ID)
    return [dec, app]


def test_a_requested_limit_is_recorded_not_asked():
    res = _assess(_requested_docs())
    assert not any(f["fact_key"] == "umbrella_limit" and f["status"] == "conflict"
                   for f in res["fields"])
    (rq,) = [r for r in res["requested_terms"] if r["fact_key"] == "umbrella_limit"]
    assert rq["requested"] == "$2,000,000" and rq["current"] == "$1,000,000"
    from services.issue_registry import requested_coverage_notes, is_score_neutral
    (note,) = requested_coverage_notes(res)
    assert note["severity"] == "advisory" and note["score_neutral"] and is_score_neutral(note["code"])
    assert "$2,000,000" in note["message"] and "(current $1,000,000)" in note["message"]
    assert note["message"].startswith("Requested ")
    assert note["resolution"]["mode"] == "none"


@pytest.mark.parametrize("docs", [
    "same",          # the application asks for what the dec already carries
    "no_dec",        # nothing current to compare with
    "premium",       # a premium is not a coverage term asked for
])
def test_no_note_without_a_real_requested_change(docs):
    if docs == "same":
        res = _assess(_requested_docs(req="$1,000,000"))
    elif docs == "no_dec":
        res = _assess([_doc(2, "application", umbrella_limit="$2,000,000", **_ID)])
    else:
        res = _assess([_doc(1, "dec_page", total_premium="$10,000", **_ID),
                       _doc(2, "application", total_premium="$12,000", **_ID)])
    assert res["requested_terms"] == []


def test_two_proposals_disagreeing_stay_a_question_not_a_note():
    dec = _doc(1, "dec_page", umbrella_limit="$1,000,000", **_ID)
    a = _doc(2, "application", umbrella_limit="$2,000,000", **_ID)
    b = _doc(3, "quote", umbrella_limit="$5,000,000", **_ID)
    res = _assess([dec, a, b])
    assert res["requested_terms"] == []
    assert any(f["fact_key"] == "umbrella_limit" and f["status"] == "conflict" for f in res["fields"])


def test_the_note_is_on_the_page_but_moves_and_holds_nothing(solved_row):
    import reach100_harness as H
    row = copy.deepcopy(solved_row)
    f = row["facts"]
    cur = H._fv0(f, "umbrella_limit") or "$1,000,000"
    f["umbrella_limit"] = _env(cur)
    row["docs"][0]["facts"]["umbrella_limit"] = _env(cur)
    row["docs"].append({"doc_id": "app1", "filename": "application.pdf", "doc_type": "application",
                        "text": "", "facts": {"umbrella_limit": _env("$9,000,000"),
                                              "applicant_name": copy.deepcopy(f["applicant_name"])}})
    row["underwriting_consistency"] = _assess(row["docs"], f)
    assert row["underwriting_consistency"]["requested_terms"]
    pkg, _kd, items = H.read_page(row)
    assert pkg["package_sqs_score"] == 100 and pkg.get("cap_applied") is None
    notes = [i for i in items if i.get("code") == "requested_coverage_change"]
    assert notes and "Requested " in notes[0]["label"]
    plan = [i for i in (pkg.get("review_plan") or {}).get("items") or []
            if i.get("code") == "requested_coverage_change"]
    assert all(int(i.get("points") or 0) == 0 and not i.get("under") for i in plan)
    assert H.contract_problems(pkg) == []
    from services.stops_now import stops_now
    st = stops_now(row, pre_form=True)
    assert not any("Requested " in m for m in st["hard"] + st["soft"])


# ── 5. The suggestion is what the forms print, for every kind ───────────────
@pytest.mark.parametrize("fact,acord,dec", [
    ("mailing_address", "4150 S Kalamath St, Denver, CO 80223", "1720 Westland Rd, Lakewood, CO 80215"),
    ("entity_type", "LLC", "Corporation"),
    ("naics_code", "238220", "236220"),
])
def test_a_non_money_card_suggests_the_value_the_forms_print(fact, acord, dec):
    docs = [_doc(1, "dec_page", **{fact: dec}, **_ID), _doc(2, "application", **{fact: acord}, **_ID)]
    for merged_value in (acord, dec):
        merged = {fact: _env(merged_value), **{k: _env(v) for k, v in _ID.items()}}
        card = _conflicts(docs, merged).get(fact)
        assert card, f"{fact} should be a conflict"
        assert card["suggested_value"] == merged_value
        assert card["preselect"] is False


def test_no_suggestion_is_invented_when_the_forms_print_neither():
    docs = [_doc(1, "dec_page", entity_type="Corporation", **_ID),
            _doc(2, "application", entity_type="LLC", **_ID)]
    card = _conflicts(docs, {"entity_type": _env("Partnership")}).get("entity_type")
    assert card is None or card["suggested_value"] in (None, "Corporation", "LLC")


def test_money_cards_keep_naming_the_printed_amount():
    docs = [_doc(1, "dec_page", total_revenue="$8,450,000", **_ID),
            _doc(2, "application", total_revenue="$9,200,000", **_ID)]
    card = _conflicts(docs, {"total_revenue": _env("$8,450,000")})["total_revenue"]
    assert card["suggested_value"] == "$8,450,000"


# ── 6. Period of restoration on an Actual Loss Sustained BI coverage ────────
@pytest.mark.parametrize("line", [
    "Business Income with Extra Expense $750,000 Special 1/3 monthly limit ALS 72 hours",
    "Business Income - Actual Loss Sustained, 12 months",
    "BUSINESS INCOME: 12 MONTHS ALS",
    "Business Income Monthly Limit of Indemnity 1/4",
])
def test_als_wording_is_read_off_the_documents(line):
    from services.property_coverages import als_statement, derive_bi_actual_loss_sustained, \
        bi_actual_loss_sustained
    text = "PROPERTY DECLARATIONS\n" + line + "\nWindstorm or Hail 2%\n"
    assert als_statement(text)
    facts = {}
    derive_bi_actual_loss_sustained(facts, [{"text": text}])
    assert bi_actual_loss_sustained(facts)


@pytest.mark.parametrize("text", [
    "Business Income $250,000 Coinsurance 80%\nPeriod of Restoration: 72 hour waiting period",
    "Cyber Business Interruption - Actual Loss Sustained",   # not the property BI
    "Members: ALS Holdings LLC\nGeneral Liability",           # an abbreviation, no BI subject
])
def test_no_als_reading_without_a_property_bi_statement(text):
    from services.property_coverages import als_statement, derive_bi_actual_loss_sustained, \
        bi_actual_loss_sustained
    assert als_statement(text) is None
    facts = {}
    derive_bi_actual_loss_sustained(facts, [{"text": text}])
    assert facts["_bi_actual_loss_sustained"]["value"] is False
    assert not bi_actual_loss_sustained(facts)


def _property_facts(als: bool):
    f = {k: _env(v) for k, v in dict(
        business_income_limit="$750,000", locations=[{"address_line1": "1 Main St"}],
        occupancy_type="Office", construction_type="Masonry", property_building_value="$2,000,000",
        year_built="1990", roof_year="2015", sprinkler_system="Yes", fire_protection_class="3",
        distance_to_hydrant="500 ft", fire_department_type="Paid").items()}
    if als:
        f["_bi_actual_loss_sustained"] = {"value": True, "source": "derived", "confidence": "derived"}
    return f


@pytest.mark.parametrize("als", [True, False])
def test_the_period_of_restoration_warning_follows_the_bi_basis(als):
    from services.cross_form_validator import _check_property_bi_period_of_restoration as check
    flags = {"has_property_coverage": True, "property_has_bi_coverage": True}
    out = check(_property_facts(als), flags, {"ACORD_140"})
    codes = [i["code"] for i in out]
    if als:
        assert codes == []
    else:
        assert codes == ["bi_missing_period_of_restoration"]


@pytest.mark.parametrize("als", [True, False])
def test_the_property_pillar_charges_the_period_only_when_one_exists(als):
    from services.sqs_service import property_gap_items
    flags = {"has_property_coverage": True, "property_has_bi_coverage": True}
    gaps = [i["fact"] for i in property_gap_items(_property_facts(als), flags)]
    assert ("period_of_restoration" in gaps) is (not als)


def test_als_in_the_schedule_row_or_the_limit_wording_also_counts():
    from services.property_coverages import bi_actual_loss_sustained
    assert bi_actual_loss_sustained({"business_income_limit": _env("Actual Loss Sustained")})
    blob = {"sections": [{"coverages": [{"kind": "bi", "coverage": "Business Income",
                                          "limit": "$750,000", "options": ["ALS"]}]}]}
    assert bi_actual_loss_sustained({"_property_coverages": _env(blob)})
    blob["sections"][0]["coverages"][0]["options"] = ["80% coinsurance"]
    assert not bi_actual_loss_sustained({"_property_coverages": _env(blob)})


def test_a_persons_period_still_counts_on_als():
    from services.sqs_service import property_gap_items
    f = _property_facts(True)
    f["period_of_restoration"] = _env("12", source="producer")
    flags = {"has_property_coverage": True, "property_has_bi_coverage": True}
    assert "period_of_restoration" not in [i["fact"] for i in property_gap_items(f, flags)]


# ── Gap 1: an advice-only note is drawn, never counted as a warning ─────────
def test_info_notes_are_counted_apart_from_warnings():
    from services.issue_registry import build_grouped_view, make_issue
    view = build_grouped_view(
        [make_issue("requested_coverage_change", "advisory", "Requested Umbrella Limit $2,000,000 (current $1,000,000)."),
         make_issue("unmapped_coverage_line", "advisory", "Choose the line for these coverage parts: X."),
         make_issue("loss_history_attestation_conflict", "soft_warning", "b")], [], [])
    drawn = [c for cs in view["warnings"].values() for c in cs]
    assert view["counts"]["warnings"] == sum(c["count"] for c in drawn if not c.get("score_neutral")) == 1
    assert view["counts"]["info"] == sum(c["count"] for c in drawn if c.get("score_neutral")) == 2
    assert view["counts"]["hard_stops"] == 0


def test_the_review_counts_never_announce_a_note_as_a_warning():
    from services.issue_registry import build_grouped_view, make_issue
    from services.session_documents import review_counts
    view = build_grouped_view([make_issue("requested_coverage_change", "advisory", "Requested X $1 (current $2).")],
                              [], [])
    assert review_counts({"grouped_issues": view})["warnings"] == 0


def test_the_frontend_readers_keep_info_out_of_the_warning_count():
    root = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src", "components", "form")
    modal = open(os.path.join(root, "AcordModal.jsx"), encoding="utf-8").read()
    rail = open(os.path.join(root, "review", "ReviewRailLayout.jsx"), encoding="utf-8").read()
    assert "infoCount: typeof c.info" in modal                     # packageIssueCounts
    assert "warningCount + (reviewIssueCounts.infoCount || 0)) > 0" in modal   # section still drawn
    assert "warningClustersOnly(clusters)" in rail                 # badges / progress skip notes
    assert "openWarnTotal > 0 || openInfoTotal > 0" in rail        # a note-only page still draws it


# ── Gap 2: the questionnaires never ask for a period on ALS ─────────────────
def _als_session(als: bool):
    f = _property_facts(als)
    return {"facts": f, "flags": {"has_property_coverage": True, "property_has_bi_coverage": True},
            "docs": [], "selected_form_ids": ["ACORD_125", "ACORD_140"]}


@pytest.mark.parametrize("als", [True, False])
def test_the_narrative_questionnaire_asks_the_period_only_when_one_exists(als):
    from services.questionnaire import build_page
    page = build_page(_als_session(als))
    facts = [q.get("fact") for s in page["sections"] for q in s["questions"]]
    assert ("period_of_restoration" in facts) is (not als)


@pytest.mark.parametrize("als", [True, False])
def test_the_period_is_not_applicable_on_als(als):
    from services.fact_state import value_state_of, is_not_applicable_for
    f = _property_facts(als)
    assert (value_state_of(f, "period_of_restoration") == "not_applicable") is als
    assert is_not_applicable_for(f, "period_of_restoration", ["ACORD_140"]) is als
    f["period_of_restoration"] = _env("12", source="producer")      # a typed period stays a value
    assert value_state_of(f, "period_of_restoration") != "not_applicable"


@pytest.mark.parametrize("als", [True, False])
def test_the_client_questionnaire_drops_the_period_on_als(als):
    from services.arq_service import generate_arq_questions_from_facts
    s = _als_session(als)
    qs = generate_arq_questions_from_facts(s["facts"], s["flags"], ["ACORD_140"], [], [])
    (q,) = [q for q in qs if q.get("field_name") == "period_of_restoration"]
    # Never put to the client either way (insurance judgment); on ALS it is no
    # question at all - Not Applicable (`question_eligibility` step 1).
    assert q.get("suppressed") is True
    assert (q.get("suppressed_reason") == "not_applicable") is als
