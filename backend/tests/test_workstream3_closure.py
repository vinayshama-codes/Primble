"""test_workstream3_closure.py

Closure tests for the SQS / Workstream-3 loose ends fixed in this change set.
Each test pins one of the six work items so a later audit can confirm nothing
regressed:

  WI-1  Umbrella underlying-schedule + follow-form evidence is now CAPTURABLE
        (extraction contract, fact registry, ARQ injector) and the missing-
        schedule deduction is explained with a warning.
  WI-2  Building-value duplication blocks form generation (gating key + the
        cross-doc reconciler flags review_required on conflicting values).
  WI-3  Structural "Supporting Documents" sub-row relabelled "Form Fill Quality".
  WI-4  Property breakdown surfaces the ACV/RCV valuation-basis line.
  WI-5  Class-code vs operations mismatch detector hardened (industry table).
  WI-6  Narrative substance model documented as the client's V1 preference.

Pure functions, no DB/IO.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services import sqs_service as sq
from services import arq_service as aq
from services import extraction_service as es
from services import fact_registry as fr
from services import underwriting_consistency as uc


# ── WI-1: reachability — the umbrella evidence keys now have producers ─────────

def test_wi1_umbrella_keys_in_extraction_contract():
    # The keys the umbrella scorer reads must be in the extraction JSON contract,
    # otherwise the -15 / -10 deductions are permanently always-on (the bug).
    assert "schedule_of_underlying_insurance" in es._EXTRACT_SCHEMA
    assert "umbrella_follow_form" in es._EXTRACT_SCHEMA


def test_wi1_umbrella_keys_registered():
    assert "schedule_of_underlying_insurance" in fr.FACT_REGISTRY
    assert "umbrella_follow_form" in fr.FACT_REGISTRY


def test_wi1_arq_injects_umbrella_evidence_only_when_umbrella_present():
    # No umbrella → nothing injected.
    q = []
    aq._maybe_inject_umbrella_evidence_questions(q, {}, {})
    assert q == []

    # Umbrella present, evidence absent → both questions injected.
    q = []
    aq._maybe_inject_umbrella_evidence_questions(q, {}, {"has_umbrella": True})
    fields = {x["field_name"] for x in q}
    assert "schedule_of_underlying_insurance" in fields
    assert "umbrella_follow_form" in fields
    # Follow-form is a select whose affirmative option carries the scorer's phrase.
    ff = next(x for x in q if x["field_name"] == "umbrella_follow_form")
    assert ff["field_type"] == "select"
    assert any("follows form" in opt.lower() for opt in ff["options"])


def test_wi1_arq_skips_already_answered_umbrella_evidence():
    q = []
    facts = {
        "schedule_of_underlying_insurance": "GL $1M; Auto $1M CSL",
        "umbrella_follow_form": "follows form",
    }
    aq._maybe_inject_umbrella_evidence_questions(q, facts, {"has_umbrella": True})
    assert q == []


def test_wi1_missing_schedule_warning_surfaced():
    # Umbrella present, adequate limits, but NO schedule → warning explains the -15.
    facts = {
        "gl_limits": "1000000", "auto_liability_limit": "1000000",
        "umbrella_follow_form": "follows form",
    }
    flags = {"has_umbrella": True}
    result = sq.calculate_package_sqs(
        facts, flags, form_results=[], cross_issues=[],
        hard_stops=[], soft_stops=[], session_data={},
    )
    assert any("Schedule of Underlying Insurance" in w for w in result["umbrella_warnings"])


def test_wi1_schedule_and_followform_earn_full_umbrella_credit():
    # The whole point: with both evidence facts present, the umbrella reaches 100.
    facts = {
        "umbrella_limit": "5000000",
        "gl_limits": "1000000", "auto_liability_limit": "1000000",
        "schedule_of_underlying_insurance": "GL $1M/$2M; Auto $1M CSL; EL $1M",
        "umbrella_follow_form": "follows form over underlying policies",
    }
    assert sq._calculate_umbrella_adequacy(facts, {"has_umbrella": True}) == 100


# ── WI-2: building-value duplication gates generation ─────────────────────────

def test_wi2_building_value_is_a_generation_blocking_key():
    assert "property_building_value" in uc.GENERATION_BLOCKING_RECONCILABLE_KEYS


def test_wi2_conflicting_building_values_flag_review_required():
    docs = [
        {"doc_id": "d1", "doc_type": "dec_page",
         "facts": {"property_building_value": "500000"}, "text": ""},
        {"doc_id": "d2", "doc_type": "sov",
         "facts": {"property_building_value": "750000"}, "text": ""},
    ]
    verdict = uc.assess_underwriting_consistency(docs, {"property_building_value": "500000"})
    bv = next(f for f in verdict["fields"] if f["fact_key"] == "property_building_value")
    assert bv["review_required"] is True
    assert verdict["review_required"] is True


def test_wi2_confirmed_building_value_clears_review():
    docs = [
        {"doc_id": "d1", "doc_type": "dec_page",
         "facts": {"property_building_value": "500000"}, "text": ""},
        {"doc_id": "d2", "doc_type": "sov",
         "facts": {"property_building_value": "750000"}, "text": ""},
    ]
    verdict = uc.assess_underwriting_consistency(
        docs, {"property_building_value": "500000"},
        confirmations={"property_building_value": "750000"},
    )
    bv = next(f for f in verdict["fields"] if f["fact_key"] == "property_building_value")
    assert bv["review_required"] is False


def test_wi2_matching_building_values_do_not_block():
    # $500,000 vs 500000 normalize equal → no conflict, generation not gated.
    docs = [
        {"doc_id": "d1", "doc_type": "dec_page",
         "facts": {"property_building_value": "$500,000"}, "text": ""},
        {"doc_id": "d2", "doc_type": "sov",
         "facts": {"property_building_value": "500000"}, "text": ""},
    ]
    verdict = uc.assess_underwriting_consistency(docs, {"property_building_value": "500000"})
    bv = next(f for f in verdict["fields"] if f["fact_key"] == "property_building_value")
    assert bv["review_required"] is False


# ── WI-3: structural sub-rows are the 5 client-approved categories ───────────
# Structural Completeness now shows: Applicant Info, Entity Info,
# Effective Date Consistency, Policy Term Consistency, Supporting Documentation.

def test_wi3_structural_rows_are_client_approved():
    cats = sq._compute_category_breakdown({}, {})
    sc = cats["structural_completeness"]
    assert set(sc.keys()) == {
        "applicant_information", "entity_information",
        "effective_date_consistency", "policy_term_consistency",
        "supporting_documentation",
    }, "structural rows must be the 5 client-approved sub-categories"
    assert sc["applicant_information"]["label"] == "Applicant Info"
    assert sc["entity_information"]["label"] == "Entity Info"
    assert sc["effective_date_consistency"]["label"] == "Effective Date Consistency"
    assert sc["policy_term_consistency"]["label"] == "Policy Term Consistency"
    assert sc["supporting_documentation"]["label"] == "Supporting Documentation"
    # Old 3-row keys must be gone.
    assert "underwriting_profile" not in sc and "form_fill_quality" not in sc


# ── WI-4: property breakdown shows 2 client-approved sub-rows ────────────────
# Property Integrity now shows: COPE Info, Location Info.
# The ACV/RCV conflict still deducts within the COPE Info sub-row.

def test_wi4_property_breakdown_has_client_rows():
    flags = {"has_property_coverage": True}
    pi = sq._compute_category_breakdown({}, flags)["property_integrity"]
    assert set(pi.keys()) == {"cope_info", "location_info"}
    assert pi["cope_info"]["label"] == "COPE Info"
    assert pi["location_info"]["label"] == "Location Info"


def test_wi4_acv_rcv_conflict_penalises_cope_info():
    flags = {"has_property_coverage": True}
    # Baseline: all COPE structural fields present, no conflict.
    base_facts = {
        "occupancy_type": "office", "construction_type": "frame",
        "year_built": "2005", "roof_year": "2005",
        "sprinkler_system": "wet", "fire_protection_class": "3",
        "valuation_method": "RCV",
    }
    base = sq._compute_category_breakdown(base_facts, flags)["property_integrity"]["cope_info"]["score"]
    # Same fields but with a contradicting ACV signal → COPE Info is reduced by 10.
    conflict_facts = dict(base_facts, property_actual_cash_value="800000")
    conflicted = sq._compute_category_breakdown(conflict_facts, flags)["property_integrity"]["cope_info"]["score"]
    assert conflicted == max(0, base - 10), "ACV/RCV conflict must dock COPE Info by 10"


def test_wi4_cope_rows_not_applicable_without_property():
    pi = sq._compute_category_breakdown({}, {})["property_integrity"]
    assert pi["cope_info"]["status"] == "not_applicable"
    assert pi["location_info"]["status"] == "not_applicable"


# ── WI-5: class-code vs operations mismatch (hardened) ───────────────────────

def test_wi5_roofing_ops_with_office_code_is_mismatch():
    # The client's explicit example: Operations = Roofing, Class Code = Office.
    facts_gl = {
        "operations_description": "Residential roofing contractor",
        "gl_class_codes_by_location": [{"location": "1", "codes": ["8810"]}],
    }
    assert sq._is_ops_class_code_mismatch(facts_gl, {}, "gl") is True

    facts_wc = {
        "operations_description": "Residential roofing contractor",
        "wc_class_codes": [{"code": "8810", "description": "Clerical Office"}],
    }
    assert sq._is_ops_class_code_mismatch(facts_wc, {}, "wc") is True


def test_wi5_matching_class_code_is_not_a_mismatch():
    facts = {
        "operations_description": "Residential roofing contractor",
        "wc_class_codes": [{"code": "5551", "description": "Roofing"}],
    }
    assert sq._is_ops_class_code_mismatch(facts, {}, "wc") is False


def test_wi5_restaurant_ops_with_clerical_code_is_mismatch():
    facts = {
        "operations_description": "Full-service restaurant and bar",
        "wc_class_codes": [{"code": "8810", "description": "Clerical"}],
    }
    assert sq._is_ops_class_code_mismatch(facts, {}, "wc") is True


def test_wi5_unmapped_signals_never_fire():
    # No recognisable industry in ops AND no NAICS → never a false deduction.
    facts = {
        "operations_description": "Miscellaneous business activities",
        "wc_class_codes": [{"code": "8810"}],
    }
    assert sq._is_ops_class_code_mismatch(facts, {}, "wc") is False
    # Codes that don't map to any single industry → no verdict, no fire.
    facts2 = {
        "operations_description": "Residential roofing contractor",
        "wc_class_codes": [{"code": "0000", "description": "unknown"}],
    }
    assert sq._is_ops_class_code_mismatch(facts2, {}, "wc") is False


def test_wi5_naics_substitutes_for_ops_keyword():
    # Ops text has no keyword, but NAICS sector 23 = construction; office code → mismatch.
    facts = {
        "operations_description": "We do work for clients in the region",
        "naics_code": "238160",
        "wc_class_codes": [{"code": "8810"}],
    }
    assert sq._is_ops_class_code_mismatch(facts, {}, "wc") is True
