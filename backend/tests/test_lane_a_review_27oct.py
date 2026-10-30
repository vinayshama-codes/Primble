"""Adversarial review of Lane A (27 Oct 2026, 25sepChanges.md Z44-A-R): each
test was written failing against the Lane A build, then the class was fixed."""
import copy
import inspect
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import pytest                                                     # noqa: E402

import services.scoped_evidence as se                             # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


def _schema(form):
    return json.loads((BACKEND / "forms_schemas" / f"{form}_schema.json").read_text(encoding="utf-8"))


S126, S131, S141 = (_schema(f) for f in ("ACORD_126", "ACORD_131", "ACORD_141"))


def _facts(form, *docs):
    facts = {"_form_id": form}
    se.attach_documents(facts, list(docs))
    return facts


# =============================================================================
# R1. Rule (h): a box whose NAME reads as another line than its form's
# =============================================================================
CRIME_DEC = {"filename": "Crime Policy.pdf", "text": (
    "COMMERCIAL CRIME COVERAGE PART DECLARATIONS\n"
    "EMPLOYEE THEFT LIMIT $100,000\n"
    "INSIDE THE PREMISES - THEFT OF OTHER PROPERTY LIMIT $25,000\n"
    "OUTSIDE THE PREMISES - OTHER PROPERTY WRITTEN ON A BLANKET BASIS LIMIT $25,000\n"),
    "facts": {"coverage_lines": [{"line": "Commercial Crime", "premium": "$500",
                                  "limit": "$100,000"}]},
    "flags": {"has_crime": True}}
PROP_DEC = {"filename": "Property Policy.pdf", "text": (
    "COMMERCIAL PROPERTY COVERAGE PART DECLARATIONS\nBUILDING LIMIT $1,000,000\n"),
    "facts": {"coverage_lines": [{"line": "Commercial Property", "premium": "$4,000",
                                  "limit": "$1,000,000"}]},
    "flags": {"has_property_coverage": True}}
OUTSIDE_BLANKET = "CrimeCoverage_OutsidePremisesOtherProperty_BlanketIndicator_A"


def test_r1_a_crime_section_box_named_other_property_stands_on_the_crime_policy():
    """ACORD 141's "Outside Premises - Other Property" is a CRIME coverage; its
    name reads as Property, so the crime dec - the box's own policy - was
    not a witness and its correct tick was refused."""
    facts = _facts("ACORD_141", CRIME_DEC, PROP_DEC)
    got = se.foreign_evidence_answers(
        {OUTSIDE_BLANKET: "1"}, S141, facts, "ACORD_141", {OUTSIDE_BLANKET},
        {OUTSIDE_BLANKET: "OUTSIDE THE PREMISES - OTHER PROPERTY WRITTEN ON A BLANKET BASIS"})
    assert got == {}


GL_DEC = {"filename": "GL Policy.pdf", "text": (
    "COMMERCIAL GENERAL LIABILITY COVERAGE PART DECLARATIONS\n"
    "EACH OCCURRENCE LIMIT $1,000,000\n"
    "CG 00 33 LIQUOR LIABILITY COVERAGE FORM\n"
    "CG 20 15 ADDITIONAL INSURED - VENDORS\n"),
    "facts": {"coverage_lines": [{"line": "Commercial General Liability", "premium": "$16,818"}]},
    "flags": {"has_general_liability": True}}
UMB_DEC = {"filename": "Umbrella Policy.pdf", "text": (
    "COMMERCIAL LIABILITY UMBRELLA DECLARATIONS\nEACH OCCURRENCE LIMIT $5,000,000\n"),
    "facts": {"coverage_lines": [{"line": "Commercial Liability Umbrella", "premium": "$17,082"}]},
    "flags": {"has_umbrella": True}}


@pytest.mark.parametrize("box,quote", [
    ("UnderlyingCoverage_Coverage_LiquorLiabilityIndicator_A", "CG 00 33 LIQUOR LIABILITY COVERAGE FORM"),
    ("UnderlyingCoverage_Coverage_VendorsLiabilityIndicator_A", "CG 20 15 ADDITIONAL INSURED - VENDORS"),
])
def test_r1_a_131_underlying_coverage_tick_stands_on_the_underlying_policy(box, quote):
    """"The underlying policy includes liquor / vendors liability" is answered
    by the UNDERLYING (GL) policy's own documents; rule (h) read only the
    umbrella's, and refused the correct tick."""
    facts = _facts("ACORD_131", GL_DEC, UMB_DEC)
    assert se.foreign_evidence_answers({box: "1"}, S131, facts, "ACORD_131", {box},
                                       {box: quote}) == {}


def test_r1_the_p15_6_refusal_still_holds():
    umb = copy.deepcopy(UMB_DEC)
    umb["text"] += "CU 24 61 AGGREGATE LIMITS OF INSURANCE (PER PROJECT)\n"
    box = "GeneralLiability_GeneralAggregate_LimitAppliesPerProjectIndicator_A"
    facts = _facts("ACORD_126", GL_DEC, umb)
    assert se.foreign_evidence_answers(
        {box: "1"}, S126, facts, "ACORD_126", {box},
        {box: "AGGREGATE LIMITS OF INSURANCE (PER PROJECT)"}) == {box: se.REASON_ANSWER_OTHER_POLICY}


# =============================================================================
# R2. 5c: the re-judge after a fact change reads no documents - a guard that
# asks "do the documents print it?" must not answer "no" for want of them
# =============================================================================
import services.pdf_service as pdf                                # noqa: E402

S140 = _schema("ACORD_140")
_P = lambda v: {"value": v, "source": "producer", "confidence": "producer"}    # noqa: E731
DED = "CommercialProperty_Premises_DeductibleAmount_A"


def test_r2_a_coinsurance_answer_never_blanks_a_printed_100_dollar_deductible():
    """Answering coinsurance 100% after forms re-judged the AI "$100"
    deductible with no documents attached (the re-stamp door's facts carry
    none), so "is $100 printed?" read as no and the correct value was
    blanked - generation, with the documents, keeps it."""
    before = {"_form_id": "ACORD_140"}
    after = {"_form_id": "ACORD_140", "coinsurance_percentage": _P("100")}
    vals = {DED: "$100"}
    assert pdf.ai_values_a_fact_change_refuses("ACORD_140", S140, vals, vals, {DED},
                                               before, after) == {}


def test_r2_with_the_documents_the_percent_rule_still_refuses_an_unprinted_amount():
    docs = [{"filename": "p.pdf", "text": "PROPERTY DEC\nCOINSURANCE 100%\nDEDUCTIBLE $1,000\n"}]
    m = {DED: "$100"}
    facts = {"_form_id": "ACORD_140", "coinsurance_percentage": _P("100")}
    se.attach_documents(facts, docs)
    got = pdf._refuse_misplaced_ai_values(m, facts, {DED})
    assert got == {DED: "PERCENT_IN_AMOUNT_BOX"}


# =============================================================================
# R3. ACORD 130 period totals: a period is covered only by a WORKERS COMP loss
# run - never by the merged span of runs for other lines (owner item 2)
# =============================================================================
import services.extraction_pipeline as ep                         # noqa: E402

_WC_CLAIM = {"date": "02/19/2023", "open": False, "paid": "18000", "reserved_amount": "0",
             "claim_number": "WC-1", "description": "Shoulder strain",
             "line_of_business": "Workers' Compensation"}
_GL_CLAIM = {"date": "05/05/2025", "open": False, "paid": "4000", "reserved_amount": "0",
             "claim_number": "GL-1", "description": "Slip and fall",
             "line_of_business": "General Liability"}
WC_RUN = {"filename": "WC loss run.pdf", "doc_type": "loss_run", "text": "WORKERS COMPENSATION LOSS RUN",
          "facts": {"loss_run_period_start": "01/01/2021", "loss_run_period_end": "01/01/2024",
                    "loss_run_valuation_date": "01/15/2024", "loss_history": [_WC_CLAIM]}}
GL_RUN = {"filename": "GL loss run.pdf", "doc_type": "loss_run", "text": "GENERAL LIABILITY LOSS RUN",
          "facts": {"loss_run_period_start": "01/01/2024", "loss_run_period_end": "01/01/2026",
                    "loss_run_valuation_date": "01/15/2026", "loss_history": [_GL_CLAIM]}}


def _facts130_two_runs(docs):
    f = {"_form_id": "ACORD_130",
         "loss_history": {"value": [copy.deepcopy(_WC_CLAIM), copy.deepcopy(_GL_CLAIM)], "source": "ai"},
         # the MERGED span of both runs - what the merge stores as scalars
         "loss_run_period_start": "01/01/2021", "loss_run_period_end": "01/01/2026",
         "loss_run_valuation_date": "01/15/2026",
         "coverage_lines": [{"line": "Workers Compensation", "effective_date": "01/01/2025",
                             "expiration_date": "01/01/2026"}]}
    f[pdf.WC_LOSS_RUN_SPANS_KEY] = pdf.wc_loss_run_spans(docs)
    return f


def _yrs(**rows):
    return {f"PriorCoverage_EffectiveYear_{k}": v for k, v in rows.items()}


def test_r3_a_period_only_another_lines_run_covers_is_never_a_zero():
    """WC run 2021-2024, GL-only run 2024-2026: the 2025 WC period is covered
    by no WC run - the merged span printed "0 claims" there, a wrong value."""
    got = pdf.wc_period_loss_values(_yrs(A="2025", B="2023"), _facts130_two_runs([WC_RUN, GL_RUN]))
    assert not any(k.endswith("_A") for k in got)
    assert got["LossHistory_ClaimCount_B"] == "1" and got["LossHistory_PaidAmount_B"] == "$18,000"


def test_r3_no_stored_wc_run_coverage_means_blank():
    f = _facts130_two_runs([WC_RUN, GL_RUN])
    f.pop(pdf.WC_LOSS_RUN_SPANS_KEY)
    assert pdf.wc_period_loss_values(_yrs(A="2025", B="2023"), f) == {}


def test_r3_a_run_is_wc_scoped_by_its_own_claims_or_its_own_wc_rows():
    clean_wc = {"filename": "WC clean.pdf", "text": "x",
                "facts": {"loss_run_period_start": "01/01/2024", "loss_run_valuation_date": "02/01/2026",
                          "coverage_lines": [{"line": "Workers Compensation", "premium": "$29,278"}],
                          "loss_history": []}}
    spans = pdf.wc_loss_run_spans([GL_RUN, clean_wc, WC_RUN, {"facts": None}, "junk",
                                   {**WC_RUN, "excluded": True}])
    # the GL-only run, an unreadable row and an EXCLUDED copy give nothing
    assert spans == [["2024-01-01", "2026-02-01"], ["2021-01-01", "2024-01-01"]]


def test_r3_the_merge_stores_the_wc_run_coverage_and_the_prompt_never_sees_it():
    assert pdf.WC_LOSS_RUN_SPANS_KEY in pdf._GAP_FILL_FACTS_EXCLUDE
    assert "WC_LOSS_RUN_SPANS_KEY" in inspect.getsource(ep._finalize_pipeline)


def test_r3_an_all_lines_account_run_covers_wc_but_a_gl_only_run_never_does():
    """The live Choice Electric runs are account runs ("2025-2026 | All lines |
    12 | ..."): their own statement covers every line, WC included."""
    acct = {"filename": "Loss_Runs_Current.csv", "text": "x",
            "facts": {"loss_run_period_start": "01/01/2025", "loss_run_period_end": "01/01/2026",
                      "loss_history": [{"date": None, "paid": "151700",
                                        "description": "All lines", "line_of_business": "All lines"}]}}
    assert pdf.wc_loss_run_spans([acct, GL_RUN]) == [["2025-01-01", "2026-01-01"]]
