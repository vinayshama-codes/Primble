"""Lane A, 27 Oct 2026 (25sepChanges.md Z44-A): seven open ends, each closed as
a class and pinned on the real ACORD schemas with the live data shapes.

  1. P15-6 - a Yes / No about ONE POLICY answered from another policy's text
     (`scoped_evidence.foreign_evidence_answers`, rule (h)).
  2. ACORD 130 per-period loss totals (`pdf_service.wc_period_loss_values`).
  3. A line with no limit fact reads its declarations' limits
     (`policy_lines.dec_line_limits`).
  4. A form added after generation re-stamps the forms already generated
     (`arq_service.restamp_for_package_change`).
  5. (a) a checkbox pairs only with its own description; (b) a vehicle row with
     no vehicle prints nothing; (c) an AI value is re-judged when a person
     changes a fact it was judged by.
  6. A held client answer about one building of several is written per building.
  7. The per-form fallback goes through the line-scoped door.
"""
import asyncio
import copy
import inspect
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import pytest                                                     # noqa: E402

import services.arq_service as arq                                # noqa: E402
import services.pdf_service as pdf                                # noqa: E402
import services.policy_lines as pl                                # noqa: E402
import services.scoped_evidence as se                             # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


def _schema(form):
    return json.loads((BACKEND / "forms_schemas" / f"{form}_schema.json").read_text(encoding="utf-8"))


S125, S126, S127, S130, S131, S140 = (_schema(f) for f in (
    "ACORD_125", "ACORD_126", "ACORD_127", "ACORD_130", "ACORD_131", "ACORD_140"))
_NO_LLM = {"filled_values": {}, "raw_text_fields": set(), "question_grounding": {}}


# =============================================================================
# 1. P15-6 - an answer about a policy stands on that policy's own text
# =============================================================================
PER_PROJECT = "GeneralLiability_GeneralAggregate_LimitAppliesPerProjectIndicator_A"
VENDORS_Q = "GeneralLiabilityLineOfBusiness_Question_ABHCode_A"
VENDORS_EXP = "GeneralLiabilityLineOfBusiness_VendorCoverageRequiredExplanation_A"
BLASTING_Q = "Contractors_Question_AAICode_A"
SAFETY_Q = "Contractors_Question_AAGCode_A"

GL_DEC = {"filename": "25-26 Package Policy.pdf", "text": (
    "COMMERCIAL GENERAL LIABILITY COVERAGE PART DECLARATIONS\n"
    "EACH OCCURRENCE LIMIT $1,000,000\nGENERAL AGGREGATE LIMIT $2,000,000\n"
    "CG 00 01 04 13 COMMERCIAL GENERAL LIABILITY COVERAGE FORM\n"),
    "facts": {"coverage_lines": [{"line": "Commercial General Liability", "premium": "$16,818",
                                  "carrier": "AMERISURE INSURANCE COMPANY"}]},
    "flags": {"has_general_liability": True}}
UMB_DEC = {"filename": "25-26 Umbrella Policy.pdf", "text": (
    "COMMERCIAL LIABILITY UMBRELLA DECLARATIONS\nEACH OCCURRENCE LIMIT $5,000,000\n"
    "SCHEDULE OF FORMS AND ENDORSEMENTS\n"
    "CU 24 61 12 20 AGGREGATE LIMITS OF INSURANCE (PER PROJECT)\n"
    "CU 24 03 12 20 ADDITIONAL INSURED - VENDORS\n"
    "THE INSURED DOES NO BLASTING OR EXPLOSIVES WORK\n"
    "SCHEDULE OF UNDERLYING INSURANCE\nCOMMERCIAL GENERAL LIABILITY $1,000,000 EACH OCCURRENCE\n"),
    "facts": {"coverage_lines": [{"line": "Commercial Liability Umbrella", "premium": "$17,082",
                                  "carrier": "AMERISURE MUTUAL INSURANCE COMPANY"}]},
    "flags": {"has_umbrella": True, "has_general_liability": True}}


def _facts126(*docs):
    facts = {"_form_id": "ACORD_126"}
    se.attach_documents(facts, list(docs))
    return facts


def test_p15_6_the_per_project_tick_from_the_umbrellas_forms_schedule_is_refused():
    facts = _facts126(GL_DEC, UMB_DEC)
    got = se.out_of_scope_values({PER_PROJECT: "Yes"}, S126, facts, "ACORD_126", {PER_PROJECT},
                                 grounding={PER_PROJECT: "AGGREGATE LIMITS OF INSURANCE (PER PROJECT)"})
    assert got == {PER_PROJECT: se.REASON_ANSWER_OTHER_POLICY}
    assert se.held_back_text(se.REASON_ANSWER_OTHER_POLICY)


def test_p15_6_the_gl_policys_own_per_project_endorsement_stands():
    gl = copy.deepcopy(GL_DEC)
    gl["text"] += "X. AGGREGATE LIMITS PER PROJECT\nY. AGGREGATE LIMITS PER LOCATION\n"
    facts = _facts126(gl, UMB_DEC)
    assert se.out_of_scope_values({PER_PROJECT: "Yes"}, S126, facts, "ACORD_126", {PER_PROJECT},
                                  grounding={PER_PROJECT: "AGGREGATE LIMITS PER PROJECT"}) == {}


def test_p15_6_evidence_printed_by_both_policies_stands():
    gl = copy.deepcopy(GL_DEC)
    gl["text"] += "CU 24 61 12 20 AGGREGATE LIMITS OF INSURANCE (PER PROJECT)\n"
    facts = _facts126(gl, UMB_DEC)
    assert se.out_of_scope_values({PER_PROJECT: "Yes"}, S126, facts, "ACORD_126", {PER_PROJECT},
                                  grounding={PER_PROJECT: "AGGREGATE LIMITS OF INSURANCE (PER PROJECT)"}) == {}


@pytest.mark.parametrize("grounding", [None, {}, {PER_PROJECT: ""}, {PER_PROJECT: "per"},
                                       {PER_PROJECT: "a sentence no document prints anywhere"}])
def test_p15_6_no_usable_evidence_is_not_judged_here(grounding):
    facts = _facts126(GL_DEC, UMB_DEC)
    assert se.foreign_evidence_answers({PER_PROJECT: "Yes"}, S126, facts, "ACORD_126",
                                       {PER_PROJECT}, grounding) == {}


def test_p15_6_a_refused_yes_takes_its_ai_explanation_with_it():
    facts = _facts126(GL_DEC, UMB_DEC)
    m = {VENDORS_Q: "Y", VENDORS_EXP: "ADDITIONAL INSURED - VENDORS"}
    got = se.foreign_evidence_answers(m, S126, facts, "ACORD_126", {VENDORS_Q, VENDORS_EXP}, {})
    assert got == {VENDORS_Q: se.REASON_ANSWER_OTHER_POLICY, VENDORS_EXP: se.REASON_ANSWER_OTHER_POLICY}


def test_p15_6_a_question_about_the_applicant_may_stand_on_any_document():
    """Blasting is the insured's operations, not the GL policy's terms: the
    umbrella's own statement of it is the insured's documents speaking."""
    facts = _facts126(GL_DEC, UMB_DEC)
    assert se.foreign_evidence_answers({BLASTING_Q: "N"}, S126, facts, "ACORD_126", {BLASTING_Q},
                                       {BLASTING_Q: "THE INSURED DOES NO BLASTING OR EXPLOSIVES WORK"}) == {}


def test_p15_6_the_applicants_own_written_policy_is_not_an_insurance_policy():
    wc = {"filename": "WC.pdf", "text": "WORKERS COMPENSATION DECLARATIONS\nCERTIFIED SAFETY PROGRAM CREDIT\n",
          "facts": {"coverage_lines": [{"line": "Workers Compensation", "premium": "$29,278"}]}}
    facts = _facts126(GL_DEC, wc)
    assert se._asks_about_the_applicants_own_policy(pdf._yes_no_question_text(SAFETY_Q, S126))
    assert se.foreign_evidence_answers({SAFETY_Q: "Y"}, S126, facts, "ACORD_126", {SAFETY_Q},
                                       {SAFETY_Q: "CERTIFIED SAFETY PROGRAM CREDIT"}) == {}


@pytest.mark.parametrize("form", ["ACORD_125", "ACORD_101", "ACORD_25", "ACORD_160"])
def test_p15_6_package_forms_and_frozen_forms_are_not_judged(form):
    facts = _facts126(GL_DEC, UMB_DEC)
    facts["_form_id"] = form
    assert se.foreign_evidence_answers({PER_PROJECT: "Yes"}, S126, facts, form, {PER_PROJECT},
                                       {PER_PROJECT: "AGGREGATE LIMITS OF INSURANCE (PER PROJECT)"}) == {}


def test_p15_6_a_rule_or_person_tick_is_never_judged_only_the_ai_set():
    facts = _facts126(GL_DEC, UMB_DEC)
    assert se.foreign_evidence_answers({PER_PROJECT: "Yes"}, S126, facts, "ACORD_126", set(),
                                       {PER_PROJECT: "AGGREGATE LIMITS OF INSURANCE (PER PROJECT)"}) == {}


def test_p15_6_without_documents_nothing_changes():
    assert se.foreign_evidence_answers({PER_PROJECT: "Yes"}, S126, {"_form_id": "ACORD_126"},
                                       "ACORD_126", {PER_PROJECT},
                                       {PER_PROJECT: "AGGREGATE LIMITS OF INSURANCE (PER PROJECT)"}) == {}


def test_p15_6_the_seam_map_facts_to_form_blanks_the_stored_ai_tick():
    """The guard is reached from the stamp with the AI's own grounding quote
    (an offline probe proves the function, never the seam)."""
    facts = _facts126(GL_DEC, UMB_DEC)
    facts.update({"has_general_liability": True, "_package_form_ids": ["ACORD_125", "ACORD_126"]})
    pre = {"filled_values": {PER_PROJECT: "Yes"}, "raw_text_fields": {PER_PROJECT},
           "question_grounding": {PER_PROJECT: "AGGREGATE LIMITS OF INSURANCE (PER PROJECT)"}}
    raw = GL_DEC["text"] + "\n" + UMB_DEC["text"]
    report = []
    m, _c = pdf.map_facts_to_form(facts, S126, form_id="ACORD_126", raw_text=raw,
                                  pre_filled_gpt=pre, guard_report=report, allow_llm=False)
    assert not str(m.get(PER_PROJECT) or "").strip()


# =============================================================================
# 2. ACORD 130 - each prior-coverage row's loss totals for ITS policy period
# =============================================================================
# The live f575160b loss table, verbatim shapes (Choice Electric, 25 Oct 2026).
F575_LOSSES = [
    {"date": "03/13/2025", "open": False, "paid": "12000", "reserved_amount": "0", "claim_number": "SIM-AUTO-001",
     "description": "V009 | 2017 Chevrolet Express G2500 | Third-party vehicle property damage",
     "line_of_business": "Business Auto"},
    {"date": "04/16/2025", "open": False, "paid": "10500", "reserved_amount": "0", "claim_number": "SIM-PKG-001",
     "description": "Inland marine | Tool theft from service jobsite", "line_of_business": "Commercial Package"},
    {"date": "02/19/2025", "open": True, "paid": "18000", "reserved_amount": "8200", "claim_number": "SIM-WC-001",
     "description": "5190 | Field electrician | Shoulder strain while lifting conduit",
     "line_of_business": "Workers' Compensation"},
    {"date": "07/09/2025", "open": False, "paid": "10200", "reserved_amount": "0", "claim_number": "SIM-WC-002",
     "description": "5190 | Field electrician | Fall from short ladder / ankle injury",
     "line_of_business": "Workers' Compensation"},
    {"date": "04/10/2025", "open": True, "paid": "10000", "reserved_amount": "60000", "claim_number": "SIM-EPL-001",
     "description": "Alleged wrongful termination", "line_of_business": "Employment Practices Liability"},
    # the current run's footer: the detail rows' own paid total
    {"date": None, "open": False, "paid": "60700", "claim_date": None, "description": "All lines",
     "claim_number": None, "line_of_business": "All lines"},
    # the 2021-2024 run: one claim of no named line, printed only as a total
    {"date": None, "open": False, "paid": "4200", "claim_date": None, "claim_number": None,
     "description": "2023-2024 | All lines | 1 | 4200 | 0 | 0 | 4200", "line_of_business": "All lines"},
]


def _facts130(losses=None, **extra):
    f = {"_form_id": "ACORD_130",
         "loss_history": {"value": copy.deepcopy(F575_LOSSES if losses is None else losses), "source": "ai"},
         "loss_run_period_start": "01/01/2021", "loss_run_period_end": "01/01/2026",
         "loss_run_valuation_date": "10/15/2026",
         # Z44-A-R: the WC loss run's own period (stored at the merge) is what
         # covers a period - the merged scalars above no longer do.
         pdf.WC_LOSS_RUN_SPANS_KEY: [["2021-01-01", "2026-01-01"]],
         "coverage_lines": [{"line": "Workers' Compensation and Employers' Liability",
                             "carrier": "AMERISURE INSURANCE COMPANY", "premium": "29,278.00",
                             "effective_date": "01/01/2025", "expiration_date": "01/01/2026"}]}
    f.update(extra)
    return f


def _years(**rows):
    return {f"PriorCoverage_EffectiveYear_{k}": v for k, v in rows.items()}


def test_130_each_period_row_totals_only_its_wc_claims():
    got = pdf.wc_period_loss_values(_years(A="2025"), _facts130())
    assert got == {"LossHistory_ClaimCount_A": "2", "LossHistory_PaidAmount_A": "$28,200",
                   "LossHistory_ReservedAmount_A": "$8,200"}


def test_130_a_period_a_loss_runs_total_may_hide_a_wc_claim_in_stays_blank():
    got = pdf.wc_period_loss_values(_years(A="2025", B="2024", C="2023"), _facts130())
    assert not any(k.endswith(("_B", "_C")) for k in got)
    assert got["LossHistory_ClaimCount_A"] == "2"


def test_130_a_covered_period_with_no_wc_claim_prints_zero():
    losses = [r for r in F575_LOSSES if "2023-2024" not in str(r.get("description"))]
    got = pdf.wc_period_loss_values(_years(A="2025", B="2022"), _facts130(losses))
    assert got["LossHistory_ClaimCount_B"] == "0"
    assert got["LossHistory_PaidAmount_B"] == "$0" and got["LossHistory_ReservedAmount_B"] == "$0"


def test_130_a_period_the_loss_runs_do_not_cover_stays_blank():
    losses = [r for r in F575_LOSSES if "2023-2024" not in str(r.get("description"))]
    got = pdf.wc_period_loss_values(_years(A="2020", B="2026"), _facts130(losses))
    assert got == {}


def test_130_no_loss_run_period_or_no_wc_claims_means_nothing():
    f = _facts130()
    f.pop(pdf.WC_LOSS_RUN_SPANS_KEY)            # no WC loss run on file
    assert pdf.wc_period_loss_values(_years(A="2025"), f) == {}
    no_wc = [r for r in F575_LOSSES if "Workers" not in str(r.get("line_of_business"))]
    assert pdf.wc_period_loss_values(_years(A="2025"), _facts130(no_wc)) == {}


def test_130_a_claim_of_no_line_in_the_period_blanks_the_row():
    losses = copy.deepcopy(F575_LOSSES) + [{"date": "05/05/2025", "paid": "500", "claim_number": "X-1",
                                            "description": "Claim", "line_of_business": ""}]
    assert pdf.wc_period_loss_values(_years(A="2025"), _facts130(losses)) == {}


def test_130_an_undated_wc_claim_blanks_every_row():
    losses = copy.deepcopy(F575_LOSSES) + [{"date": None, "paid": "500", "claim_number": "WC-9",
                                            "description": "Back strain",
                                            "line_of_business": "Workers Compensation"}]
    assert pdf.wc_period_loss_values(_years(A="2025"), _facts130(losses)) == {}


def test_130_an_open_claim_with_no_reserve_leaves_the_reserve_blank():
    losses = copy.deepcopy(F575_LOSSES)
    losses[2]["reserved_amount"] = ""
    got = pdf.wc_period_loss_values(_years(A="2025"), _facts130(losses))
    assert got["LossHistory_ClaimCount_A"] == "2" and "LossHistory_ReservedAmount_A" not in got


def test_130_a_year_box_that_is_not_a_year_or_another_form_gives_nothing():
    assert pdf.wc_period_loss_values({"PriorCoverage_EffectiveYear_A": "MUTUAL INS"}, _facts130()) == {}
    assert pdf.wc_period_loss_values(_years(A="2025"), {**_facts130(), "_form_id": "ACORD_125"}) == {}


def test_130_two_terms_beginning_one_year_cannot_be_told_apart():
    cl = [{"line": "Workers Compensation", "effective_date": "01/01/2025", "expiration_date": "07/01/2025"},
          {"line": "Workers Compensation", "effective_date": "07/01/2025", "expiration_date": "07/01/2026"}]
    assert pdf.wc_period_loss_values(_years(A="2025"), _facts130(coverage_lines=cl)) == {}


def test_130_the_seam_generation_prints_the_totals_beside_the_ai_year():
    pre = {"filled_values": {"PriorCoverage_EffectiveYear_A": "2025"},
           "raw_text_fields": {"PriorCoverage_EffectiveYear_A"}, "question_grounding": {}}
    m, c = pdf.map_facts_to_form(_facts130(), S130, form_id="ACORD_130", raw_text="2025",
                                 pre_filled_gpt=pre, allow_llm=False)
    assert pdf._currency_to_int(m["LossHistory_PaidAmount_A"]) == 28200
    assert m["LossHistory_ClaimCount_A"] == "2" and c["LossHistory_ClaimCount_A"] == "filled"
    assert not str(m.get("LossHistory_ClaimCount_B") or "").strip()


def test_130_a_loss_table_save_after_forms_refreshes_the_totals_and_keeps_a_persons_box():
    state = {"PriorCoverage_EffectiveYear_A": "2025", "LossHistory_ClaimCount_A": "1",
             "LossHistory_PaidAmount_A": "$999"}
    conf = {"LossHistory_ClaimCount_A": "filled", "LossHistory_PaidAmount_A": "producer"}
    assert arq._refresh_wc_period_totals("ACORD_130", S130, state, conf, _facts130())
    assert state["LossHistory_ClaimCount_A"] == "2"
    assert state["LossHistory_PaidAmount_A"] == "$999"           # a person's box stands
    assert not arq._refresh_wc_period_totals("ACORD_125", S125, dict(state), dict(conf), _facts130())


# =============================================================================
# 3. A line with no limit fact reads its own declarations' limits
# =============================================================================
F575_ENTRIES = [
    {"label": "Aggregate Limit of Liability", "value": "$1,000,000", "owner": "policy",
     "section": "EMPLOYMENT PRACTICES LIABILITY COVERAGE PART", "policy_number": None,
     "line_of_business": "Employment Practices Liability"},
    {"label": "(C) Retentions: (1) Each Employment Claim", "value": "$10,000", "owner": "policy",
     "section": "EMPLOYMENT PRACTICES LIABILITY COVERAGE PART", "policy_number": None,
     "line_of_business": "Employment Practices Liability"},
    {"label": "COMMERCIALINLANDMARINECOVERAGEPART", "value": "$ 2,431.00", "owner": "policy",
     "section": "COMMON POLICY DECLARATIONS", "policy_number": None, "line_of_business": "Inland Marine"},
    {"label": "CRIMEANDFIDELITY COVERAGEPART", "value": "$ 500.00", "owner": "policy",
     "section": "COMMON POLICY DECLARATIONS", "policy_number": None, "line_of_business": "Crime"},
    {"label": "LIMIT", "value": "$798,556", "section": "COMMERCIAL PROPERTY COVERAGE SCHEDULE",
     "policy_number": None, "line_of_business": "Commercial Property"},
    {"label": "LIMIT", "value": "$73,008", "section": "COMMERCIAL PROPERTY COVERAGE SCHEDULE",
     "policy_number": None, "line_of_business": "Commercial Property"},
    {"label": "EACH OCCURRENCE LIMIT", "value": "$5,000,000", "section": "UMBRELLA",
     "policy_number": None, "line_of_business": "General Liability"},
]


def _recs():
    return [{"id": "epli#unnumbered", "line": "epli"}, {"id": "inland_marine#unnumbered", "line": "inland_marine"},
            {"id": "crime#unnumbered", "line": "crime"}, {"id": "property#unnumbered", "line": "property"},
            {"id": "general_liab#unnumbered", "line": "general_liab"}]


def test_limits_epl_carries_its_declarations_aggregate_never_its_retention():
    got = pl.record_limits({"dec_page_entries": copy.deepcopy(F575_ENTRIES)}, _recs())
    assert got["epli#unnumbered"] == [{"label": "aggregate", "amount": "$1,000,000"}]


def test_limits_a_line_printed_only_as_a_premium_has_no_limit():
    got = pl.record_limits({"dec_page_entries": copy.deepcopy(F575_ENTRIES)}, _recs())
    assert got["inland_marine#unnumbered"] == [] and got["crime#unnumbered"] == []


def test_limits_one_label_two_amounts_is_nobodys():
    got = pl.record_limits({"dec_page_entries": copy.deepcopy(F575_ENTRIES)}, _recs())
    assert got["property#unnumbered"] == []


def test_limits_a_settled_line_never_reads_the_index_c23():
    """GL's limits are the merge's to settle; an umbrella amount tagged GL in
    the index must never become the GL limit."""
    got = pl.record_limits({"dec_page_entries": copy.deepcopy(F575_ENTRIES)}, _recs())
    assert got["general_liab#unnumbered"] == []


def test_limits_an_im_schedule_that_states_its_limit_prints_it():
    entries = [{"label": "Contractors Equipment Limit of Insurance", "value": "$250,000",
                "line_of_business": "Commercial Inland Marine", "policy_number": "IM-77"}]
    got = pl.record_limits({"dec_page_entries": entries},
                           [{"id": "im", "line": "inland_marine", "policy_number": "IM-77"}])
    assert got["im"] == [{"label": "contractors equipment", "amount": "$250,000"}]
    other = pl.record_limits({"dec_page_entries": entries},
                             [{"id": "im", "line": "inland_marine", "policy_number": "IM-99"}])
    assert other["im"] == []                                     # another policy's entry


def test_limits_two_policies_on_one_line_get_none():
    got = pl.record_limits({"dec_page_entries": copy.deepcopy(F575_ENTRIES)},
                           [{"id": "e1", "line": "epli"}, {"id": "e2", "line": "epli"}])
    assert "e1" not in got and "e2" not in got


def test_limits_survive_the_index_purge_through_the_stored_reading():
    f = {"dec_page_entries": copy.deepcopy(F575_ENTRIES)}
    stored = pl.dec_line_limits(f)
    purged = {pl.DEC_LINE_LIMITS_KEY: stored}
    assert pl.record_limits(purged, _recs())["epli#unnumbered"] == [
        {"label": "aggregate", "amount": "$1,000,000"}]
    assert pl.dec_line_limits({}) == {}


def test_limits_the_stored_reading_never_reaches_the_gap_fill_prompt():
    assert pl.DEC_LINE_LIMITS_KEY in pdf._GAP_FILL_FACTS_EXCLUDE
    import services.extraction_pipeline as ep
    src = inspect.getsource(ep)
    assert "DEC_LINE_LIMITS_KEY" in src


@pytest.mark.parametrize("entries", [None, [], "junk", [None, 3, {"label": None}],
                                     [{"label": "Limit", "value": "Included", "line_of_business": "EPL"}]])
def test_limits_malformed_index_never_raises(entries):
    assert isinstance(pl.dec_line_limits({"dec_page_entries": entries}), dict)


# =============================================================================
# 4. A form added after generation: the other forms follow the package
# =============================================================================
LONG_REMARK = ("The insured is an electrical contractor performing commercial tenant improvement "
               "work across the Denver metro area. ") * 4


def _gen125(pkg, facts):
    m, c = pdf.map_facts_to_form({**facts, "_form_id": "ACORD_125", "_package_form_ids": pkg}, S125,
                                 form_id="ACORD_125", raw_text="", pre_filled_gpt=dict(_NO_LLM),
                                 allow_llm=False)
    return {"ACORD_125": {"schema": S125, "mapped": m, "field_state": dict(m), "confidence": dict(c)}}


def _remark_facts():
    return {"applicant_name": "Choice Electric LLC",
            "additional_remarks_text": {"value": LONG_REMARK.strip(), "source": "producer",
                                        "confidence": "filled"}}


def test_adding_acord_101_moves_the_125_long_remark_to_the_pointer():
    facts = _remark_facts()
    gen = _gen125(["ACORD_125"], facts)
    assert gen["ACORD_125"]["field_state"]["CommercialPolicy_RemarkText_A"].startswith("The insured")
    touched = arq.restamp_for_package_change(gen, facts, ["ACORD_125"], ["ACORD_125", "ACORD_101"])
    assert touched == ["ACORD_125"]
    assert gen["ACORD_125"]["field_state"]["CommercialPolicy_RemarkText_A"] == pdf._REMARKS_ON_101_POINTER
    assert gen["ACORD_125"]["pdf_bytes"] is None


def test_adding_acord_186_ticks_the_125_contractors_supplement_attached():
    facts = _remark_facts()
    gen = _gen125(["ACORD_125"], facts)
    box = "CommercialPolicy_Attachment_ContractorsSupplementIndicator_A"
    assert not str(gen["ACORD_125"]["field_state"].get(box) or "").strip()
    arq.restamp_for_package_change(gen, facts, ["ACORD_125"], ["ACORD_125", "ACORD_186"])
    assert gen["ACORD_125"]["field_state"][box] == "Y"


def test_a_persons_remark_box_stays_when_the_package_changes():
    facts = _remark_facts()
    gen = _gen125(["ACORD_125"], facts)
    gen["ACORD_125"]["field_state"]["CommercialPolicy_RemarkText_A"] = "Typed by the producer."
    gen["ACORD_125"]["confidence"]["CommercialPolicy_RemarkText_A"] = "producer"
    arq.restamp_for_package_change(gen, facts, ["ACORD_125"], ["ACORD_125", "ACORD_101"])
    assert gen["ACORD_125"]["field_state"]["CommercialPolicy_RemarkText_A"] == "Typed by the producer."


def test_an_ai_answer_a_rule_now_owns_blank_is_cleared_when_126_is_added():
    """ACORD 186's starred questions are left to an attached 126."""
    box = "Contractors_Question_AABCode_A"
    s186 = _schema("ACORD_186")
    gen = {"ACORD_186": {"schema": s186, "field_state": {box: "N"}, "confidence": {box: "ai_verified"}}}
    touched = arq.restamp_for_package_change(gen, {}, ["ACORD_186"], ["ACORD_186", "ACORD_126"])
    assert touched == ["ACORD_186"] and not gen["ACORD_186"]["field_state"][box]
    same = {"ACORD_186": {"schema": s186, "field_state": {box: "N"}, "confidence": {box: "ai_verified"}}}
    assert arq.restamp_for_package_change(same, {}, ["ACORD_186"], ["ACORD_186"]) == []


def test_form_addition_runs_the_package_change_restamp():
    import services.form_addition as fa
    src = inspect.getsource(fa.add_form_to_session)
    assert "restamp_for_package_change" in src and 'sorted(present) + [form_id]' in src


# =============================================================================
# 5a. A checkbox pairs only with its own description
# =============================================================================
def test_131_named_insured_on_fire_policy_has_no_borrowed_description():
    pairs = pdf._question_explanation_pairs(S131)
    assert "CareCustodyAndControl_InsuredLiability_IsNamedInsuredOnFirePolicy_A" not in pairs


def test_every_checkbox_pair_on_all_17_forms_is_its_own_description():
    total = 0
    for p in sorted((BACKEND / "forms_schemas").glob("*_schema.json")):
        s = json.loads(p.read_text(encoding="utf-8"))
        for q, exp in pdf._question_explanation_pairs(s).items():
            if pdf._QUESTION_CODE_RE.search(q):
                continue
            total += 1
            assert pdf._checkbox_owns_description(q, exp), (p.name, q, exp)
    assert total == 66                       # 67 before; the one false pair gone


@pytest.mark.parametrize("box,desc,ok", [
    ("Vehicle_Use_OtherIndicator_A", "Vehicle_Use_OtherDescription_A", True),
    ("BuildingSecurity_GuardWatchmenOtherIndicator_B", "BuildingSecurity_GuardWatchmenOtherDescription_B", True),
    ("Vehicle_Use_OtherIndicator_A", "Vehicle_Use_OtherDescription_B", False),
    ("CareCustodyAndControl_InsuredLiability_IsNamedInsuredOnFirePolicy_A",
     "CareCustodyAndControl_InsuredLiability_OtherDescription_A", False),
    ("", "", False), (None, None, False)])
def test_checkbox_owns_description_shapes(box, desc, ok):
    assert pdf._checkbox_owns_description(box, desc) is ok


# =============================================================================
# 5b. A vehicle row with no vehicle prints nothing - every column, every source
# =============================================================================
AUTO_FACTS = {"_form_id": "ACORD_127", "has_auto_coverage": True,
              "auto_vehicle_use": {"value": "Service", "source": "policy_doc_text", "confidence": "filled"},
              "auto_covered_symbols": [{"coverage": "Comprehensive", "symbols": ["7"]},
                                       {"coverage": "Collision", "symbols": ["7"]}],
              "auto_deductible_comp": "$1,000", "auto_deductible_collision": "$1,000",
              "applicant_name": "Choice Electric LLC"}


def _stamp127(facts, pre=None):
    m, _c = pdf.map_facts_to_form(copy.deepcopy(facts), S127, form_id="ACORD_127", raw_text="",
                                  pre_filled_gpt=pre or dict(_NO_LLM), allow_llm=False)
    return m


def test_127_row_a_with_no_vehicle_prints_no_use_tick():
    m = _stamp127(AUTO_FACTS)
    assert not any(str(v or "").strip() for k, v in m.items()
                   if k.startswith("Vehicle_Use_") and k.endswith("_A"))


def test_127_row_a_with_its_vehicle_keeps_every_column():
    f = {**AUTO_FACTS, "auto_vin_schedule": [{"vin": "1GCWGAFP7H1234567", "year": "2017",
                                              "make": "Chevrolet", "model": "Express"}]}
    m = _stamp127(f)
    assert m["Vehicle_Use_ServiceIndicator_A"] == "Yes"
    assert m["Vehicle_VINIdentifier_A"] == "1GCWGAFP7H1234567"


def test_127_an_ai_value_on_a_vehicle_less_row_a_goes_too_but_an_ai_vehicle_anchors_it():
    pre = {"filled_values": {"Vehicle_CostNewAmount_A": "$58,900"}, "raw_text_fields": set(),
           "question_grounding": {}}
    assert not str(_stamp127(AUTO_FACTS, pre).get("Vehicle_CostNewAmount_A") or "").strip()
    m = {"Vehicle_VINIdentifier_A": "1GCWGAFP7H1234567", "Vehicle_CostNewAmount_A": "$58,900"}
    assert pdf._cells_of_rows_without_a_vehicle(m, S127, {}) == []


def test_127_a_schedule_row_with_no_naming_cell_is_still_a_vehicle():
    m = {"Vehicle_Use_ServiceIndicator_A": "Yes"}
    assert pdf._cells_of_rows_without_a_vehicle(m, S127, {"auto_vin_schedule": [{"cost_new": "1"}]}) == []
    assert pdf._cells_of_rows_without_a_vehicle(m, S127, {}) == ["Vehicle_Use_ServiceIndicator_A"]


def test_127_the_modified_equipment_question_table_is_never_a_vehicle_column():
    """ACORD 127's "any vehicles modified?" table (`Vehicle_Question_Modified
    Equipment*`, rows A-B of the four vehicle rows) is a General Information
    answer that shares the prefix - P15-3's own warning. Never judged here."""
    m = {"Vehicle_Question_ModifiedEquipmentDescription_A": "Lift gate",
         "Vehicle_Question_ModifiedEquipmentCostAmount_B": "$4,000"}
    assert pdf._cells_of_rows_without_a_vehicle(m, S127, {}) == []
    single = "Vehicle_Question_OnlyOnRowA_A"
    schema = {**S127, single: {"ft": "/Tx", "tu": "Enter text: a description."}}
    assert pdf._cells_of_rows_without_a_vehicle({single: "x"}, schema, {}) == []


def test_127_forms_with_no_naming_cell_are_never_judged():
    m = {"Vehicle_Use_ServiceIndicator_A": "Yes"}
    assert pdf._cells_of_rows_without_a_vehicle(m, {"Vehicle_Use_ServiceIndicator_A": {},
                                                    "Vehicle_Use_ServiceIndicator_B": {}}, {}) == []
    assert pdf._cells_of_rows_without_a_vehicle(None, S127, None) == []


def test_127_the_restamp_guards_refuse_a_planned_use_tick_on_a_vehicle_less_row():
    trial = {"Vehicle_Use_ServiceIndicator_A": "Yes"}
    pdf._enforce_post_fill_guards(trial, S127, dict(AUTO_FACTS), gpt_filled_set=set(),
                                  deterministic_ticks={"Vehicle_Use_ServiceIndicator_A"})
    assert not trial.get("Vehicle_Use_ServiceIndicator_A")


# =============================================================================
# 5c. An AI value is re-judged when a person changes a fact it was judged by
# =============================================================================
RATING = ("Policy_RatingEffectiveDate_A", "Policy_NormalAnniversaryRatingDate_A")


def _gen130(eff, exp, rating="01/01/2026", label="ai_verified"):
    state = {"Policy_EffectiveDate_A": eff, "Policy_ExpirationDate_A": exp}
    conf = {"Policy_EffectiveDate_A": "filled", "Policy_ExpirationDate_A": "filled"}
    for b in RATING:
        state[b], conf[b] = rating, label
    return {"ACORD_130": {"schema": S130, "mapped": dict(state), "field_state": dict(state),
                          "confidence": conf}}


def _term(eff, exp, source="producer"):
    return {"effective_date": {"value": eff, "source": source, "confidence": "filled"},
            "expiration_date": {"value": exp, "source": source, "confidence": "filled"}}


def test_rejudge_the_door_refuses_only_what_the_change_moved():
    before = {**_gen130("01/01/2026", "01/01/2027")["ACORD_130"]["field_state"]}
    after = {**before, "Policy_EffectiveDate_A": "01/01/2027", "Policy_ExpirationDate_A": "01/01/2028"}
    ai = set(RATING)
    fb = {**_term("01/01/2026", "01/01/2027", "derived"), "_form_id": "ACORD_130"}
    fa = {**_term("01/01/2027", "01/01/2028"), "_form_id": "ACORD_130"}
    got = pdf.ai_values_a_fact_change_refuses("ACORD_130", S130, before, after, ai, fb, fa)
    assert set(got) == set(RATING)
    assert pdf.ai_values_a_fact_change_refuses("ACORD_130", S130, before, before, ai, fb, fb) == {}
    assert before["Policy_RatingEffectiveDate_A"] == "01/01/2026"      # pure


def test_rejudge_a_value_already_refused_before_the_change_is_not_this_changes():
    before = {**_gen130("01/01/2027", "01/01/2028")["ACORD_130"]["field_state"]}
    fb = {**_term("01/01/2027", "01/01/2028"), "_form_id": "ACORD_130"}
    fa = {**_term("01/01/2027", "01/01/2028"), "_form_id": "ACORD_130", "applicant_name": "X"}
    assert pdf.ai_values_a_fact_change_refuses("ACORD_130", S130, before, before, set(RATING), fb, fa) == {}


def test_rejudge_through_the_restamp_door_after_the_proposed_date_is_retyped():
    gen = _gen130("01/01/2026", "01/01/2027")
    fb, fa = _term("01/01/2026", "01/01/2027", "derived"), _term("01/01/2027", "01/01/2028")
    touched = arq._restamp_changed_boxes(gen, fb, fa, own_keys={"effective_date", "expiration_date"})
    form = gen["ACORD_130"]
    assert "ACORD_130" in touched
    assert "2027" in str(form["field_state"]["Policy_EffectiveDate_A"])
    assert all(not form["field_state"][b] for b in RATING)
    assert all(b not in form["confidence"] for b in RATING)
    assert {r["field"] for r in form["guard_blanks"]} >= set(RATING)


def test_rejudge_a_persons_rating_date_is_never_touched():
    gen = _gen130("01/01/2026", "01/01/2027", label="producer")
    arq._restamp_changed_boxes(gen, _term("01/01/2026", "01/01/2027", "derived"),
                               _term("01/01/2027", "01/01/2028"), own_keys={"effective_date"})
    assert all(gen["ACORD_130"]["field_state"][b] == "01/01/2026" for b in RATING)


def test_rejudge_the_edited_form_itself_through_propagate_fact_edits():
    gen = _gen130("01/01/2027", "01/01/2028")       # the person just typed the new term on the 130
    touched = arq.propagate_fact_edits(gen, "ACORD_130", _term("01/01/2026", "01/01/2027", "derived"),
                                       _term("01/01/2027", "01/01/2028"),
                                       ["effective_date", "expiration_date"])
    assert touched == ["ACORD_130"]
    assert all(not gen["ACORD_130"]["field_state"][b] for b in RATING)


# =============================================================================
# 6. A held client answer about ONE building of several
# =============================================================================
def _row(n, line1, **kw):
    return {"location_number": str(n), "address_line1": line1, "address_city": "Denver",
            "address_state": "CO", "address_zip": "80202", **kw}


def _bld_session(held):
    rows = [_row(1, "1 Main St", construction_type="Frame"), _row(2, "2 Oak Ave", construction_type="Masonry")]
    return {"facts": {"applicant_name": "Acme LLC", "property_locations": {"value": rows, "source": "ai"}},
            "flags": {"has_property_coverage": True},
            "generated_forms": {"ACORD_140": {"schema": S140, "field_state": {}, "confidence": {}}},
            "client_answer_conflicts": held}


def _resolve(session, key, choice="use_client"):
    import services.client_answer_review as car
    store = {"s": session}

    async def _get(_sid):
        return copy.deepcopy(store["s"])

    async def _upd(_sid, payload, delete_facts=None):
        s = store["s"]
        for k, v in payload.items():
            if k == "generated_forms":
                s.setdefault("generated_forms", {}).update(v)
            elif k == "facts":
                s["facts"] = {**(s.get("facts") or {}), **v}
            else:
                s[k] = v

    with patch("repositories.session_repository.get_processing_session", _get), \
         patch("repositories.session_repository.upd_processing_session", _upd), \
         patch.object(arq, "recalculate_session_scores", AsyncMock(return_value={"ok": True})), \
         patch("services.audit_service.log_underwriting_confirmation", AsyncMock(return_value=None)):
        out = asyncio.run(car.resolve_client_answer("s1", key, choice))
    return out, store["s"]


def test_held_building_answer_accepted_lands_on_its_own_row_only():
    held = {"year_built@loc2": {"client_value": "1998", "source_value": "", "field_name": "year_built@loc2",
                                "row_address": "2 Oak Ave, Denver, CO 80202", "row_building": ""}}
    from services.premises_interest import premises_address
    held["year_built@loc2"]["row_address"] = premises_address(_row(2, "2 Oak Ave"))
    out, s = _resolve(_bld_session(held), "year_built@loc2")
    assert out["ok"], out
    rows = s["facts"]["property_locations"]["value"]
    assert rows[1]["year_built"] == "1998" and not rows[0].get("year_built")
    assert "year_built" not in s["facts"] or not (s["facts"]["year_built"] or {}).get("value")
    assert "year_built@loc2" not in (s.get("client_answer_conflicts") or {})
    form = s["generated_forms"]["ACORD_140"]
    assert form["field_state"].get("CommercialStructure_BuiltYear_B") == "1998"
    assert form["confidence"].get("CommercialStructure_BuiltYear_B") == "producer"
    assert not form["field_state"].get("CommercialStructure_BuiltYear_A")


def test_held_building_answer_whose_row_moved_is_refused_and_kept():
    held = {"year_built@loc2": {"client_value": "1998", "field_name": "year_built@loc2",
                                "row_address": "99 Elsewhere Rd, Denver, CO 80202", "row_building": ""}}
    out, s = _resolve(_bld_session(held), "year_built@loc2")
    assert not out["ok"] and "location table" in out["message"]
    assert "year_built@loc2" in s["client_answer_conflicts"]
    assert not s["facts"]["property_locations"]["value"][1].get("year_built")


def test_held_package_building_detail_on_two_buildings_is_never_one_value():
    held = {"year_built": {"client_value": "1998", "source_value": "", "field_name": "year_built"}}
    out, s = _resolve(_bld_session(held), "year_built")
    assert not out["ok"] and "2 buildings" in out["message"]
    assert "year_built" in s["client_answer_conflicts"]
    assert "year_built" not in s["facts"]


def test_the_client_apply_holds_a_package_building_detail_on_two_buildings():
    session = _bld_session({})
    arq_row = {"id": "arq-1", "status": "submitted", "session_id": "s1",
               "answers": {"year_built": "1998"},
               "questions": [{"field_name": "year_built", "question": "Year built?", "form_ids": []}]}
    saved: dict = {}

    async def _upd(_sid, payload, delete_facts=None):
        saved.update(payload)

    with patch.object(arq, "get_arq_by_id", AsyncMock(return_value=arq_row)), \
         patch("repositories.session_repository.get_processing_session", AsyncMock(return_value=session)), \
         patch("repositories.session_repository.upd_processing_session", _upd):
        ok, _ = asyncio.run(arq.apply_arq_answers_to_session("arq-1", "s1"))
    assert ok
    held = saved.get("client_answer_conflicts") or (saved.get("facts") or {}).get("_client_answer_conflicts") or {}
    assert held["year_built"]["kind"] == "per_building"
    assert "year_built" not in (saved.get("facts") or {})


def test_one_building_package_detail_is_still_written():
    assert arq._per_building_hold_reason("year_built", {"property_locations": [_row(1, "1 Main St",
                                                                                 construction_type="Frame")]}) is None
    assert arq._per_building_hold_reason(None, {}) is None
    assert arq._per_building_hold_reason("applicant_name", _bld_session({})["facts"]) is None


# =============================================================================
# 7. The per-form fallback goes through the one line-scoped door
# =============================================================================
def _fallback_session():
    import services.form_service as fs
    return {"facts": {"applicant_name": "Choice Electric LLC", "has_general_liability": True},
            "flags": {}, "docs": [{"filename": "a.pdf", "text": "COMMERCIAL GENERAL LIABILITY"}],
            "all_forms": fs.filter_available_forms(fs.load_all_forms()),
            "selected_form_ids": ["ACORD_125"]}


def test_fallback_never_runs_the_unscoped_per_form_fill(monkeypatch):
    import services.form_service as fs
    from services import form_instances as fi
    asked, scoped = [], []
    monkeypatch.setattr(pdf, "_fill_unmatched_with_gpt",
                        lambda *a, **k: asked.append(a) or {"filled_values": {}})

    def _combined(forms_to_unmatched, facts, raw_text, model=None, forms_to_mapped=None,
                  line_scopes=None):
        scoped.append((sorted(forms_to_unmatched), line_scopes is not None))
        return {}
    monkeypatch.setattr(pdf, "combined_gap_fill", _combined)
    session = _fallback_session()
    meta = fi.form_meta_for(session["all_forms"], "ACORD_125", session["facts"])
    res = fs.process_single_form(meta, session, None)
    assert asked == []
    assert scoped and scoped[0][0] == ["ACORD_125"] and scoped[0][1]
    assert res["mapped"].get("NamedInsured_FullName_A")


def test_fallback_uses_the_scoped_answers_when_the_door_gives_them(monkeypatch):
    import services.form_service as fs
    from services import form_instances as fi
    monkeypatch.setattr(pdf, "_fill_unmatched_with_gpt",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("unscoped fill")))
    answers = {"filled_values": {"X": "y"}, "raw_text_fields": set(), "question_grounding": {}}
    monkeypatch.setattr(pdf, "combined_gap_fill", lambda f, *a, **k: {fid: answers for fid in f})
    handed = []
    real = fs.map_facts_to_form
    monkeypatch.setattr(fs, "map_facts_to_form",
                        lambda *a, **k: handed.append(k.get("pre_filled_gpt")) or real(*a, **k))
    session = _fallback_session()
    meta = fi.form_meta_for(session["all_forms"], "ACORD_125", session["facts"])
    fs.process_single_form(meta, session, None)
    assert handed == [answers]               # the scoped door's answers, as stamped


def test_every_generation_call_still_hands_process_single_form_its_answers():
    from tests.test_client_retest_24sep import TestItem6LineSeparation
    TestItem6LineSeparation().test_no_generation_call_skips_the_one_scoped_door()
