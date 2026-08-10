"""
Regression tests for Client-Questionnaire Controls (Beta Report §8) + the
post-remediation recalculation plumbing (§6.2 / §8.2.7).

Covers the acceptance criteria:
  • The default questionnaire does NOT select every missing field.
  • Internal / producer-side items are not auto-sent (audience + suppression).
  • Questions are grouped by topic, audience, and priority.
  • Score-impact is indicated per question.
  • The Beta Test 2 leak examples (producer fax, national identifier, policy
    coverage code, business location mismatch) are correctly routed.
  • ARQ answers map back to canonical facts so scores can move.

Run from backend/:
    python tests/test_question_controls.py
or:
    python -m pytest tests/test_question_controls.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.question_classifier import (  # noqa: E402
    AUDIENCE_CLIENT, AUDIENCE_PRODUCER, AUDIENCE_INTERNAL, AUDIENCE_DO_NOT_SEND,
    AUDIENCE_CARRIER,
    BUCKET_CLIENT, BUCKET_AGENCY, BUCKET_UNDERWRITING, BUCKET_DO_NOT_SEND,
    PRIORITY_CRITICAL, PRIORITY_IMPORTANT, PRIORITY_OPTIONAL,
    TOPIC_APPLICANT, TOPIC_GL, TOPIC_WC, TOPIC_UMBRELLA, TOPIC_PROPERTY,
    TOPIC_PRODUCER, TOPIC_LOSS, DEFAULT_SELECT_CAP,
    classify_question, decorate_questions, apply_default_selection, derive_topic,
)
from services.arq_service import (  # noqa: E402
    _canonical_key, _is_curated_client_field, _present_fact_keys,
)


# ── §8.1 — the Beta Test 2 leak examples are correctly routed ─────────────────

def test_producer_fax_is_do_not_send_and_suppressed():
    tax = classify_question("Producer_FaxNumber", ["ACORD_125"])
    assert tax["audience"] == AUDIENCE_DO_NOT_SEND
    assert tax["suppressed"] is True
    assert tax["topic_group"] == TOPIC_PRODUCER


def test_national_identifier_is_producer_not_client():
    # "National identifier fields unless contextually necessary": routed to the
    # producer audience (visible in the producer review panel, supplied by the
    # producer when the form needs it) - never a default client question.
    tax = classify_question("Producer_NationalProducerNumber", ["ACORD_125"])
    assert tax["audience"] == AUDIENCE_PRODUCER
    assert tax["suppressed"] is True

    tax2 = classify_question("national_identifier", ["ACORD_125"])
    assert tax2["audience"] == AUDIENCE_PRODUCER
    assert tax2["suppressed"] is True


def test_policy_coverage_code_is_internal():
    tax = classify_question("CommercialPolicy_CoverageCode", ["ACORD_125"])
    assert tax["audience"] == AUDIENCE_INTERNAL
    assert tax["suppressed"] is True


def test_naic_is_producer_not_client():
    # NAIC is a national identifier: producer-side, never a client default.
    tax = classify_question("Insurer_NAICCode", ["ACORD_125"])
    assert tax["audience"] == AUDIENCE_PRODUCER
    assert tax["suppressed"] is True


def test_insurer_underwriter_is_carrier_review():
    # The carrier's own underwriter is "Carrier/underwriter review" - never a
    # client question and not generic plumbing.
    from services.question_classifier import AUDIENCE_CARRIER
    tax = classify_question("Insurer_Underwriter_FullName_A", ["ACORD_125"])
    assert tax["audience"] == AUDIENCE_CARRIER
    assert tax["suppressed"] is True
    assert tax["suppressed_reason"] == "carrier_underwriter_review"


def test_contractor_operations_not_swept_into_carrier():
    # A "ContractorsUnderwriting_*Percent" field is a client-answerable operations
    # figure - it must NOT be mis-routed to carrier by the underwriting patterns.
    from services.question_classifier import AUDIENCE_CARRIER
    tax = classify_question("ContractorsUnderwriting_ResidentialWorkPercent_A", ["ACORD_186"])
    assert tax["audience"] != AUDIENCE_CARRIER


def test_naics_code_still_client_despite_naic_substring():
    # The "naic" producer pattern is a substring of "naics_code"; the client
    # whitelist must keep the industry classification a client question.
    tax = classify_question("naics_code", ["ACORD_125"], is_curated_client=True)
    assert tax["audience"] == AUDIENCE_CLIENT


def test_crossform_conflict_is_internal_flag_by_default():
    # Client clarification (2026-07): a cross-form conflict is an Underwriting /
    # Internal Review flag by DEFAULT - it is NEVER auto-sent to the client. The
    # location_count_mismatch fix (`locations`) is a client-answerable fact, so it
    # stays escalatable ("Add to client") and keeps its severity + hard-stop signal.
    tax = classify_question("locations", ["ACORD_125", "ACORD_140"],
                            is_cross_form=True, severity="hard_stop",
                            is_curated_client=True, canonical_key="locations")
    assert tax["audience"] == AUDIENCE_INTERNAL
    assert tax["bucket"] == BUCKET_UNDERWRITING
    assert tax["priority"] == PRIORITY_CRITICAL
    assert tax["suppressed"] is True
    assert tax["escalatable_to_client"] is True
    assert tax["score_impact"]["hard_stop_resolution"] is True


def test_crossform_judgment_conflict_is_not_escalatable():
    # A cross-form conflict with no client-answerable fix (raw reconciliation
    # field, no canonical fact) is a pure internal flag - not escalatable.
    tax = classify_question("SomeReconciliation_InternalField", ["ACORD_125"],
                            is_cross_form=True, severity="soft_warning")
    assert tax["audience"] == AUDIENCE_INTERNAL
    assert tax["bucket"] == BUCKET_UNDERWRITING
    assert tax["escalatable_to_client"] is False


# ── §8.2 item 2 — priority classification ─────────────────────────────────────

def test_tier1_fields_are_critical_client():
    for f in ("applicant_name", "mailing_address", "effective_date",
              "lines_of_business", "contact_name"):
        tax = classify_question(f, ["ACORD_125"], is_curated_client=True)
        assert tax["audience"] == AUDIENCE_CLIENT, f
        assert tax["priority"] == PRIORITY_CRITICAL, f


def test_producer_name_is_producer_not_client_critical():
    # producer_name is a tier-1 SCORING field but it's the agency's own name —
    # a producer-side item, NOT a client question.
    tax = classify_question("producer_name", ["ACORD_125"], is_curated_client=True)
    assert tax["audience"] == AUDIENCE_PRODUCER
    assert tax["priority"] != PRIORITY_CRITICAL


def test_tier2_and_coverage_fields_are_important():
    for f in ("fein", "total_revenue", "gl_each_occurrence", "umbrella_limit",
              "wc_payroll"):
        tax = classify_question(f, ["ACORD_126"], is_curated_client=True)
        assert tax["audience"] == AUDIENCE_CLIENT, f
        assert tax["priority"] == PRIORITY_IMPORTANT, f


def test_raw_acord_client_fields_scored_on_canonical_key():
    # Regression: the producer forms key every field by its raw ACORD name. When
    # the resolved canonical key is supplied, a client fact arriving under its raw
    # name must be scored as the fact it represents (critical/important) instead of
    # being demoted to optional or swept into the internal panel.
    crit = classify_question(
        "NamedInsured_FullName", ["ACORD_125"],
        is_curated_client=True, canonical_key="applicant_name",
    )
    assert crit["audience"] == AUDIENCE_CLIENT
    assert crit["priority"] == PRIORITY_CRITICAL
    assert crit["topic_group"] == TOPIC_APPLICANT

    imp = classify_question(
        "CommercialGeneralLiability_GeneralAggregateLimit_Amount", ["ACORD_126"],
        is_curated_client=True, canonical_key="gl_aggregate",
    )
    assert imp["audience"] == AUDIENCE_CLIENT
    assert imp["priority"] == PRIORITY_IMPORTANT
    assert imp["topic_group"] == TOPIC_GL


def test_raw_acord_plumbing_still_internal_even_with_canonical_signal():
    # The canonical-key fix must not weaken Rule 7 or the suppression patterns.
    fax = classify_question("Producer_FaxNumber", ["ACORD_125"], canonical_key=None)
    assert fax["audience"] == AUDIENCE_DO_NOT_SEND
    assert fax["suppressed"] is True

    obscure = classify_question("GeneralLiability_Obscure_Field_7", ["ACORD_126"])
    assert obscure["audience"] == AUDIENCE_INTERNAL
    assert obscure["suppressed"] is True


def test_uncurated_raw_field_defaults_to_internal():
    # Rule 7 — the workhorse. An obscure raw PDF field nobody curated is internal.
    tax = classify_question("GeneralLiability_SupplementalSubcode_Indicator_B", ["ACORD_126"])
    assert tax["audience"] == AUDIENCE_INTERNAL
    assert tax["suppressed"] is True


def test_curated_but_noncore_field_is_optional_client():
    tax = classify_question("mortgagee_name", ["ACORD_140"], is_curated_client=True)
    assert tax["audience"] == AUDIENCE_CLIENT
    assert tax["priority"] == PRIORITY_OPTIONAL


# ── §8.2 item 5 — topic grouping ──────────────────────────────────────────────

def test_topic_grouping():
    assert derive_topic("gl_each_occurrence", ["ACORD_126"]) == TOPIC_GL
    assert derive_topic("wc_payroll", ["ACORD_130"]) == TOPIC_WC
    assert derive_topic("umbrella_sir", ["ACORD_131"]) == TOPIC_UMBRELLA
    assert derive_topic("property_building_value", ["ACORD_140"]) == TOPIC_PROPERTY
    assert derive_topic("applicant_name", ["ACORD_125"]) == TOPIC_APPLICANT
    assert derive_topic("num_claims", ["ACORD_125"]) == TOPIC_LOSS
    assert derive_topic("Producer_FullName", ["ACORD_125"]) == TOPIC_PRODUCER
    # Unknown field falls back to the form's topic.
    assert derive_topic("SomeMysteryField", ["ACORD_130"]) == TOPIC_WC


# ── §8.2 item 6 — score impact ────────────────────────────────────────────────

def test_score_impact_flags():
    crit = classify_question("applicant_name", ["ACORD_125"], is_curated_client=True)
    assert crit["score_impact"]["sqs"] is True
    assert crit["score_impact"]["submission_readiness"] is True
    assert crit["score_impact"]["form_completion"] is True

    internal = classify_question("Producer_FaxNumber", ["ACORD_125"])
    assert internal["score_impact"]["sqs"] is False
    assert internal["score_impact"]["submission_readiness"] is False


# ── §8.2 item 3 + §11 #20 — curated default selection + cap ───────────────────

def _mk(field_name, audience, priority, suppressed=False):
    return {
        "field_name": field_name, "audience": audience, "priority": priority,
        "suppressed": suppressed, "topic_group": "applicant_information",
    }


def test_default_selection_only_critical_client():
    qs = [
        _mk("applicant_name", AUDIENCE_CLIENT, PRIORITY_CRITICAL),
        _mk("fein", AUDIENCE_CLIENT, PRIORITY_IMPORTANT),
        _mk("mortgagee_name", AUDIENCE_CLIENT, PRIORITY_OPTIONAL),
        _mk("Producer_FaxNumber", AUDIENCE_DO_NOT_SEND, "suppressed", suppressed=True),
        _mk("RawField_X", AUDIENCE_INTERNAL, "suppressed", suppressed=True),
    ]
    summary = apply_default_selection(qs)
    by_name = {q["field_name"]: q for q in qs}
    assert by_name["applicant_name"]["default_selected"] is True
    assert by_name["fein"]["default_selected"] is False
    assert by_name["fein"]["suggested"] is True            # important -> suggested
    assert by_name["mortgagee_name"]["default_selected"] is False
    assert by_name["Producer_FaxNumber"]["default_selected"] is False
    assert by_name["RawField_X"]["default_selected"] is False
    assert summary["default_selected"] == 1
    # Acceptance: default does NOT select every missing field.
    assert summary["default_selected"] < summary["total"]


def test_default_selection_respects_cap():
    qs = [_mk(f"crit_{i}", AUDIENCE_CLIENT, PRIORITY_CRITICAL) for i in range(40)]
    summary = apply_default_selection(qs)
    assert summary["default_selected"] == DEFAULT_SELECT_CAP
    assert sum(1 for q in qs if q["default_selected"]) == DEFAULT_SELECT_CAP


# ── §8.2 item 4 — suppress what's already answered ────────────────────────────

def test_already_provided_is_suppressed():
    qs = [{"field_name": "total_payroll", "form_ids": ["ACORD_130"],
           "_canonical_key": "total_payroll"}]
    decorate_questions(qs, present_fact_keys={"total_payroll"})
    assert qs[0]["suppressed"] is True
    assert qs[0]["suppressed_reason"] == "already_provided"


def test_decorate_then_default_collapses_a_realistic_explosion():
    # Simulate a slice of the 1,790 explosion: a handful of client fields plus a
    # pile of raw internal form fields. Default selection must stay tiny.
    qs = []
    qs.append({"field_name": "applicant_name", "form_ids": ["ACORD_125"],
               "_is_curated_client": True, "_canonical_key": "applicant_name"})
    qs.append({"field_name": "gl_each_occurrence", "form_ids": ["ACORD_126"],
               "_is_curated_client": True, "_canonical_key": "gl_each_occurrence"})
    qs.append({"field_name": "Producer_FaxNumber", "form_ids": ["ACORD_125"]})
    for i in range(200):
        qs.append({"field_name": f"GeneralLiability_Obscure_Field_{i}", "form_ids": ["ACORD_126"]})

    decorate_questions(qs)
    summary = apply_default_selection(qs)
    client = [q for q in qs if q["audience"] == AUDIENCE_CLIENT and not q["suppressed"]]
    internal = [q for q in qs if q["audience"] != AUDIENCE_CLIENT or q["suppressed"]]
    assert len(client) == 2                 # only the two curated client fields
    assert len(internal) == 201             # fax + 200 obscure -> internal bucket
    assert summary["default_selected"] == 1  # only the critical one pre-selected


# ── ARQ answer -> canonical fact reverse mapping (recalc foundation) ──────────

def test_canonical_key_resolution():
    # Direct canonical key.
    assert _canonical_key("total_payroll") == "total_payroll"
    # Raw ACORD schema field -> mapped fact via _ACORD_FIELD_RULES.
    assert _canonical_key("NamedInsured_FullName") == "applicant_name"
    assert _canonical_key("NamedInsured_AnnualRevenue") == "total_revenue"
    # CHANGED 2026-08-09: Producer_FaxNumber used to map to nothing because no
    # fact existed for it, which left it to gap fill - and gap fill copied the
    # producer's PHONE number into it (client report #1). It now has its own
    # `producer_fax` fact, so a fax is stamped only when the document labels one.
    assert _canonical_key("Producer_FaxNumber") == "producer_fax"
    # A field belonging to one party must never resolve to another party's fact.
    assert _canonical_key("Producer_ContactPerson_Phone") == "producer_contact_phone"


def test_is_curated_client_field():
    assert _is_curated_client_field("applicant_name") is True
    assert _is_curated_client_field("gl_limits") is True
    assert _is_curated_client_field("location_address_2") is True   # prefix map
    assert _is_curated_client_field("Totally_Made_Up_Raw_Field") is False


def test_present_fact_keys_unwraps_envelopes():
    facts = {
        "applicant_name": "Orbin Contracting LLC",
        "total_revenue": {"value": "1000000", "confidence": "ai_high"},
        "fein": "",
        "naics_code": None,
    }
    present = _present_fact_keys(facts)
    assert "applicant_name" in present
    assert "total_revenue" in present     # envelope unwrapped + non-empty
    assert "fein" not in present          # empty
    assert "naics_code" not in present    # None


# ── 3-bucket model (client clarification 2026-07) ─────────────────────────────

def test_bucket_derivation():
    # Client fact -> Client bucket.
    assert classify_question("applicant_name", ["ACORD_125"],
                             is_curated_client=True)["bucket"] == BUCKET_CLIENT
    # Fax -> Never send row.
    assert classify_question("Producer_FaxNumber", ["ACORD_125"])["bucket"] == BUCKET_DO_NOT_SEND
    # Obscure raw plumbing (Rule 7) -> Underwriting / Internal.
    assert classify_question("GeneralLiability_Obscure_Field_7",
                             ["ACORD_126"])["bucket"] == BUCKET_UNDERWRITING


def test_prior_carrier_and_policy_numbers_are_agency():
    # The client re-classified prior carrier + all policy numbers as AGENCY items
    # (producer / CSR answers them), NOT client questions.
    for f, canon in (("prior_carrier", "prior_carrier"),
                     ("policy_number", None),
                     ("prior_policy_number", None)):
        tax = classify_question(f, ["ACORD_125"], is_curated_client=True, canonical_key=canon)
        assert tax["audience"] == AUDIENCE_PRODUCER, f
        assert tax["bucket"] == BUCKET_AGENCY, f
        assert tax["suppressed"] is True, f


def test_insurer_info_is_agency_but_underwriter_stays_carrier():
    # Carrier INFORMATION (insurer name/policy/phone) -> Agency; the carrier's OWN
    # underwriter -> Carrier review (Underwriting bucket), never conflated.
    info = classify_question("Insurer_FullName", ["ACORD_125"])
    assert info["bucket"] == BUCKET_AGENCY
    uw = classify_question("Insurer_Underwriter_FullName_A", ["ACORD_125"])
    assert uw["audience"] == AUDIENCE_CARRIER
    assert uw["bucket"] == BUCKET_UNDERWRITING


def test_submission_strategy_is_agency():
    # "Submission goal / market selection / coverage intent" == producer strategy.
    # (submission_urgency was moved OUT of this set - see
    # test_submission_urgency_is_client_and_preselected below: a deadline the
    # client knows about is not the same thing as the agent's marketing strategy.)
    for f in ("carrier_marketing_reason",):
        tax = classify_question(f, ["ACORD_125"], is_curated_client=True)
        assert tax["bucket"] == BUCKET_AGENCY, f


def test_submission_urgency_is_client_and_preselected():
    # Figure 16 (2026-07-21): the "upcoming deadlines or urgency" question is a
    # client-answerable fact, not agent strategy - it must route to the Client
    # bucket as Important priority, AND be pre-selected by default (a deliberate
    # exception to "Important = suggested, not pre-selected" - see
    # _FORCE_PRESELECT_FIELDS in question_classifier.py).
    tax = classify_question("submission_urgency", ["ACORD_125"], is_curated_client=True)
    assert tax["bucket"] == BUCKET_CLIENT
    assert tax["audience"] == AUDIENCE_CLIENT
    assert tax["priority"] == PRIORITY_IMPORTANT

    q = {"field_name": "submission_urgency", **tax}
    apply_default_selection([q])
    assert q["default_selected"] is True
    assert q["suggested"] is True


def test_desired_limits_stay_client_not_agency():
    # "Coverage intent" -> Agency does NOT drag the insured's desired LIMITS out of
    # the Client bucket - they stay Client and keep driving SQS.
    for f in ("gl_limits", "umbrella_limit", "auto_liability_limit",
              "property_building_value"):
        tax = classify_question(f, ["ACORD_126"], is_curated_client=True)
        assert tax["bucket"] == BUCKET_CLIENT, f
        assert tax["audience"] == AUDIENCE_CLIENT, f


def test_apply_default_selection_reports_bucket_counts():
    qs = [
        _mk("applicant_name", AUDIENCE_CLIENT, PRIORITY_CRITICAL),
        _mk("prior_carrier", AUDIENCE_PRODUCER, "internal", suppressed=True),
        _mk("xconflict", AUDIENCE_INTERNAL, PRIORITY_CRITICAL, suppressed=True),
        _mk("Producer_FaxNumber", AUDIENCE_DO_NOT_SEND, "suppressed", suppressed=True),
    ]
    # bucket is derived from audience inside apply_default_selection when absent.
    summary = apply_default_selection(qs)
    assert summary["bucket_client"] == 1
    assert summary["bucket_agency"] == 1
    assert summary["bucket_underwriting"] == 1
    assert summary["bucket_do_not_send"] == 1
    # Only the critical client question is pre-selected.
    assert summary["default_selected"] == 1


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
