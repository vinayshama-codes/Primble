"""Michelle review, 29 Oct 2026 - an underwriter's pass over what Primble raises.

Each test is a CLASS of package, never one fixture's values:

1. One document's own schedule is not a disagreement (I2) - generic: a text-scan
   reading is the document's item when that document's own extraction gives the
   amount to an item / another fact, or every line printing it is a schedule row.
   A document that states two different TOTALS is still asked, worded as itself.
2. A coverage term (limit / deductible / SIR / premium) on an application or quote
   is the term APPLIED FOR - not a rival to the current dec's; two proposals that
   disagree are compared with each other only (the same for the policy dates).
3. A form of ours echoing the documents is no second witness for the date check.
4. Labels read initialisms in capitals.
5. A WC dec that places the monopolistic state with the state fund (stop-gap row)
   needs no "confirm the state fund" warning; a person's answer still decides.
6. A loss run's "no losses reported for this policy term" is about that term.
7. An address-only row at a documented premises is not another location missing COPE.
8. A proposed term that starts after the current policies end is a coverage gap
   (warning, confirmable).
"""
from __future__ import annotations

import os

os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import pytest


def _env(v, source="ai"):
    return {"value": v, "source": source, "confidence": "ai_high"}


def _doc(i, doc_type, text="", **facts):
    return {"doc_id": f"d{i}", "filename": f"{doc_type}_{i}.pdf", "doc_type": doc_type,
            "text": text, "facts": {k: _env(v) for k, v in facts.items()}}


_ID = dict(applicant_name="Acme Plumbing LLC", fein="12-3456789")


def _conflicts(docs, merged=None, confirmations=None):
    from services.underwriting_consistency import assess_underwriting_consistency
    res = assess_underwriting_consistency(docs, merged or {}, confirmations or {})
    return {f["fact_key"]: f for f in res["fields"] if f["status"] == "conflict"}


# ── 1. One document's own schedule ──────────────────────────────────────────
_BLDGS = [{"building_number": "1", "building_value": "$2,350,000"},
          {"building_number": "2", "building_value": "$1,780,000"},
          {"building_number": "3", "building_value": "$910,000"}]


@pytest.mark.parametrize("layout", [
    # labelled once per building, the schedule extracted
    "Building Limit $2,350,000\nBuilding Limit $1,780,000\nBuilding Limit $910,000\n",
    # a table with cells
    "| 1 | 1 | Building | $2,350,000 |\n| 1 | 2 | Building | $1,780,000 |\n| 2 | 1 | Building | $910,000 |\n",
])
def test_a_documents_per_building_values_are_not_rival_totals(layout):
    d = _doc(1, "dec_page", text=layout, property_building_value="$2,350,000",
             property_locations=_BLDGS, **_ID)
    assert "property_building_value" not in _conflicts([d])


@pytest.mark.parametrize("layout", [
    "Bldg 1 Building Limit $2,350,000\nBldg 2 Building Limit $1,780,000\n",
    "1 2 Building $1,780,000 Special 90% Replacement Cost $5,000\n"
    "1 1 Building $2,350,000 Special 90% Replacement Cost $5,000\n",
])
def test_printed_schedule_rows_are_items_even_when_extraction_missed_the_schedule(layout):
    d = _doc(1, "dec_page", text=layout, property_building_value="$2,350,000", **_ID)
    assert "property_building_value" not in _conflicts([d])


def test_per_class_payroll_rows_are_items():
    text = ("CO 5537 HVAC Systems - installation & drivers $1,240,000 2.86 $35,464\n"
            "CO 5183 Plumbing NOC & drivers $860,000 2.41 $20,726\n")
    d = _doc(1, "dec_page", text=text, wc_class_codes=[
        {"code": "5537", "state": "CO", "payroll": "$1,240,000"},
        {"code": "5183", "state": "CO", "payroll": "$860,000"}], **_ID)
    assert "total_payroll" not in _conflicts([d])


def test_one_document_stating_two_totals_is_asked_as_itself():
    text = "Total Payroll: $2,620,000\nNotes\nTotal annual payroll $2,900,000\n"
    d = _doc(1, "application", text=text, total_payroll="$2,620,000", **_ID)
    card = _conflicts([d]).get("total_payroll")
    assert card, "a document contradicting its own total must be asked"
    assert {v["display"] for v in card["values"]} == {"$2,620,000", "$2,900,000"}
    assert "application_1.pdf states more than one amount" in card["conflict_reason"]
    assert "documents state" not in card["conflict_reason"]


def test_two_documents_disagreeing_offer_only_their_totals_not_the_schedule():
    dec_text = ("Annual Gross Revenue $8,450,000\n"
                "Bldg 1 Annual Revenue $3,000,000\nBldg 2 Annual Revenue $5,450,000\n")
    dec = _doc(1, "dec_page", text=dec_text, total_revenue="$8,450,000", **_ID)
    app = _doc(2, "application", total_revenue="$9,200,000", **_ID)
    card = _conflicts([dec, app]).get("total_revenue")
    assert card
    assert {v["display"] for v in card["values"]} == {"$8,450,000", "$9,200,000"}
    assert card["conflict_reason"] == "the documents state different amounts"


def test_a_scan_echo_of_another_fact_the_document_read_is_dropped():
    from services.underwriting_consistency import _drop_own_schedule_items
    d = _doc(1, "dec_page", text="Payroll $2,380,000\n", total_payroll="$2,620,000",
             wc_payroll="$2,380,000")
    values = [
        {"normalized": "2620000", "display": "$2,620,000",
         "sources": [{"doc_id": "d1", "source_method": "llm", "raw": "$2,620,000"}]},
        {"normalized": "2380000", "display": "$2,380,000",
         "sources": [{"doc_id": "d1", "source_method": "text_scan", "raw": "$2,380,000"}]},
    ]
    kept = _drop_own_schedule_items("total_payroll", "currency", values, [d])
    assert [g["display"] for g in kept] == ["$2,620,000"]
    # what extraction read AS this fact is never judged
    llm_only = [dict(values[1], sources=[dict(values[1]["sources"][0], source_method="llm")])]
    assert _drop_own_schedule_items("total_payroll", "currency", values[:1] + llm_only, [d]) \
        == values[:1] + llm_only


def test_a_digit_inside_an_address_or_date_is_no_item():
    from services.underwriting_consistency import _document_own_item_amounts
    got = _document_own_item_amounts(
        {"mailing_address": _env("4150 S Kalamath St, Denver, CO 80223"),
         "effective_date": _env("12/01/2025"), "property_locations": _env(_BLDGS)},
        "total_revenue", "currency")
    assert "4150" not in got and "80223" not in got and "12012025" not in got
    assert {"2350000", "1780000", "910000"} <= got


def test_a_pick_clears_the_card():
    dec = _doc(1, "dec_page", total_revenue="$8,450,000", **_ID)
    app = _doc(2, "application", total_revenue="$9,200,000", **_ID)
    assert "total_revenue" in _conflicts([dec, app])
    assert "total_revenue" not in _conflicts([dec, app], confirmations={"total_revenue": "$9,200,000"})


# ── 2. Requested vs current coverage terms ───────────────────────────────────
@pytest.mark.parametrize("fact,cur,req", [
    ("umbrella_limit", "$1,000,000", "$2,000,000"),
    ("gl_deductible", "$1,000", "$2,500"),
    ("total_policy_premium", "$10,000", "$12,000"),
    ("umbrella_sir", "$10,000", "$25,000"),
])
@pytest.mark.parametrize("role", ["application", "quote", "acord_form"])
def test_a_requested_coverage_term_is_not_a_rival_to_the_current_one(fact, cur, req, role):
    dec = _doc(1, "dec_page", **{fact: cur}, **_ID)
    prop = _doc(2, role, **{fact: req}, **_ID)
    assert fact not in _conflicts([dec, prop])


def test_two_current_documents_disagreeing_on_a_limit_still_conflict():
    a = _doc(1, "dec_page", umbrella_limit="$1,000,000", **_ID)
    b = _doc(2, "certificate", umbrella_limit="$3,000,000", **_ID)
    assert "umbrella_limit" in _conflicts([a, b])


def test_two_proposals_disagreeing_are_compared_with_each_other_only():
    dec = _doc(1, "dec_page", effective_date="12/01/2025", **_ID)
    app = _doc(2, "application", effective_date="01/01/2027", **_ID)
    quote = _doc(3, "quote", effective_date="12/01/2026", **_ID)
    card = _conflicts([dec, app, quote]).get("effective_date")
    assert card
    assert {v["display"] for v in card["values"]} == {"01/01/2027", "12/01/2026"}


def test_is_coverage_term_fact():
    from services.underwriting_consistency import is_coverage_term_fact
    for k in ("umbrella_limit", "gl_each_occurrence", "gl_aggregate", "umbrella_sir",
              "cyber_retention", "total_policy_premium", "umbrella_attachment_point",
              "auto_deductible_comp"):
        assert is_coverage_term_fact(k), k
    for k in ("total_revenue", "total_payroll", "num_employees", "property_building_value",
              "fein", "policy_number", "carrier_name", "effective_date"):
        assert not is_coverage_term_fact(k), k


# ── 3. Our own echo is no witness in the date check ─────────────────────────
def test_our_echoed_form_is_no_second_witness_for_the_policy_dates():
    from services.sqs_service import check_doc_consistency
    app = _doc(1, "application", effective_date="01/01/2027", **_ID)
    ours = _doc(2, "acord_form", **_ID)
    ours["facts"]["effective_date"] = {"value": "12/01/2026", "source": "acord_form",
                                       "echo_of": "documents"}
    assert not any("date_conflict" in m for m in check_doc_consistency([app, ours]))
    # a real second proposal still conflicts
    other = _doc(3, "acord_form", effective_date="12/01/2026", **_ID)
    assert any("date_conflict" in m for m in check_doc_consistency([app, other]))


# ── 4. Labels ────────────────────────────────────────────────────────────────
def test_labels_keep_initialisms():
    from services.underwriting_consistency import _humanize
    assert _humanize("naics_code") == "NAICS Code"
    assert _humanize("gl_each_occurrence") == "GL Each Occurrence"
    assert _humanize("business_start_date") == "Business Start Date"
    assert _humanize("wc_xmod") == "WC X-Mod"


# ── 5. Monopolistic state placed with the state fund by the documents ───────
_MONO_FLAGS = {"has_workers_comp": True, "wc_has_monopolistic_state": True}


def _mono(facts):
    from services.sqs_service import evaluate_stops
    hard, soft = evaluate_stops(dict(facts), dict(_MONO_FLAGS))
    return ([m for m in hard if "Monopolistic" in m],
            [m for m in soft if "Monopolistic" in m and "wc_monopolistic_payroll" not in m])


_ROWS = [{"code": "5537", "state": "CO", "payroll": "$1,240,000", "description": "HVAC"},
         {"code": "5537", "state": "WY", "payroll": "$240,000",
          "description": "HVAC - stop-gap Employers Liability only (WY state fund)"}]


def test_a_stop_gap_row_for_the_monopolistic_state_answers_the_warning():
    facts = {"wc_class_codes": _env(_ROWS), "wc_monopolistic_payroll": _env({"WY": "$240,000"}),
             "wc_payroll_by_state": _env({"CO": "$1,240,000", "WY": "$240,000"})}
    assert _mono(facts) == ([], [])


def test_without_that_evidence_the_warning_still_asks():
    rows = [dict(r, description="HVAC") for r in _ROWS]
    facts = {"wc_class_codes": _env(rows), "wc_payroll_by_state": _env({"CO": "1", "WY": "1"})}
    hard, soft = _mono(facts)
    assert hard == [] and len(soft) == 1


def test_every_monopolistic_state_must_be_placed():
    rows = _ROWS + [{"code": "5537", "state": "WA", "payroll": "$10,000", "description": "HVAC"}]
    facts = {"wc_class_codes": _env(rows)}
    assert len(_mono(facts)[1]) == 1


def test_a_persons_private_carrier_answer_still_hard_stops():
    from services.answer_options import WC_STATE_FUND_OPTIONS
    facts = {"wc_class_codes": _env(_ROWS),
             "wc_state_fund_acknowledged": _env(WC_STATE_FUND_OPTIONS[1], "producer")}
    hard, soft = _mono(facts)
    assert len(hard) == 1 and soft == []


# ── 6. A loss run's per-term "no losses" ─────────────────────────────────────
def test_no_losses_for_this_policy_term_is_about_that_term():
    from services.normalization import no_loss_statements
    from services.loss_history_state import no_loss_statements_contradict
    text = ("Policy CGL-1-20 Term 12/01/2020 - 12/01/2021\n"
            "NO LOSSES REPORTED FOR THIS POLICY TERM AS OF THE VALUATION DATE.\n")
    st = no_loss_statements(text)
    assert st and all(s["scope"] == "term" for s in st)
    facts = {"num_claims": _env("3"), "loss_history": _env([
        {"date": "06/09/2022", "paid": "$36,240", "line_of_business": "GL"}])}
    assert not no_loss_statements_contradict(st, facts)
    # an account statement still contradicts real claims
    assert no_loss_statements_contradict(no_loss_statements("The insured has had no losses."), facts)


# ── 7. Address-only echo of a documented premises ───────────────────────────
def test_an_address_only_echo_is_not_another_location_missing_cope():
    from services.cross_form_validator import _check_per_location_cope_completeness as check
    full = {"address": "4150 S Kalamath St, Denver, CO", "address_line1": "4150 S Kalamath St",
            "construction_type": "Joisted Masonry", "building_value": "$2,350,000"}
    second = dict(full, address="1720 Westland Rd", address_line1="1720 Westland Rd")
    echo = {"address": "4150 S Kalamath St, Suite 200, Denver, CO 80223",
            "address_line1": "4150 S Kalamath St", "location_number": "4"}
    flags = {"has_property_coverage": True}
    assert check({"property_locations": [full, second, echo]}, flags, set()) == []
    # a different street with no COPE is a real gap
    bare = {"address": "9 Elm St, Denver, CO", "address_line1": "9 Elm St"}
    out = check({"property_locations": [full, second, bare]}, flags, set())
    assert out and out[0]["code"] == "per_location_cope_incomplete"


# ── 8. Coverage gap between the current term and the proposed one ───────────
def _gap(eff, prior_exp, eff_source="acord_form"):
    from services.cross_form_validator import run_cross_form_validation
    facts = {"effective_date": {"value": eff, "source": eff_source, "confidence": "x"},
             "prior_expiration_date": {"value": prior_exp, "source": "ai",
                                        "routed_from": "current_term"}}
    return [i for i in run_cross_form_validation(facts, {}, {"ACORD_125"})
            if i["code"] == "proposed_term_coverage_gap"]


def test_a_gap_after_the_current_term_is_a_warning():
    out = _gap("01/01/2027", "12/01/2026")
    assert len(out) == 1 and out[0]["type"] == "soft_warning"
    assert "31 days" in out[0]["message"] and "12/01/2026" in out[0]["message"]
    assert out[0]["resolution"]["mode"] == "field"
    assert out[0]["resolution"]["facts"] == ["effective_date"]


@pytest.mark.parametrize("eff", ["12/01/2026", "12/02/2026", "11/15/2026"])
def test_no_gap_when_the_term_meets_or_overlaps(eff):
    assert _gap(eff, "12/01/2026") == []


def test_a_persons_confirmed_date_stands_the_gap_down():
    assert _gap("01/01/2027", "12/01/2026", eff_source="producer") == []


def test_the_gap_reads_one_shared_current_expiration_from_the_lines():
    from services.cross_form_validator import _check_proposed_term_coverage_gap as check
    lines = [{"line": "GL", "effective_date": "12/01/2025", "expiration_date": "12/01/2026"},
             {"line": "Auto", "effective_date": "12/01/2025", "expiration_date": "12/01/2026"}]
    facts = {"effective_date": _env("02/01/2027"), "coverage_lines": _env(lines)}
    assert len(check(facts, {}, set())) == 1
    lines[1]["expiration_date"] = "03/01/2026"          # two different ends: no single answer
    assert check(facts, {}, set()) == []


def test_the_gap_card_is_registered():
    from services.issue_registry import VERIFY_FIGURE_CODES, resolution_for
    from services.cross_form_validator import rule_codes
    assert "proposed_term_coverage_gap" in rule_codes()
    assert "proposed_term_coverage_gap" in VERIFY_FIGURE_CODES
    assert resolution_for("proposed_term_coverage_gap")["mode"] == "field"
