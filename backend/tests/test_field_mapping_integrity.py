"""
Regression tests for the field-mapping integrity guard (Figure 33 client feedback).

Locks in the two things the client asked for:
  * HIGH-IMPACT classification - insured/owner identity fields plus auto
    ownership / HNOA / leasing / hazardous-materials / maintenance questions.
  * CONTAMINATION detection - carrier/policy data stamped into an insured/owner
    field must be caught and surfaced as a WARNING on the pre-download and
    post-download screens ("Show a warning ... never block the download").
    Includes the exact ACORD 127 scenario from the report: carrier names in the
    vehicle owner boxes.

This module never blocks anything - it only produces advisory rows consumed by
audit_service.run_and_log_field_mapping_check.

Run from backend/:
    python tests/test_field_mapping_integrity.py
or:
    python -m pytest tests/test_field_mapping_integrity.py -v
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.field_mapping_integrity import (  # noqa: E402
    is_insured_owner_field, is_insured_identity_field, is_high_impact_field,
    looks_like_carrier, looks_like_policy_number, detect_field_mapping_contamination,
    to_recommendation_rows, is_value_contaminated, _CARRIER_FACT_KEYS, _POLICY_FACT_KEYS,
)

_SCHEMAS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "forms_schemas")
_ALL_SCHEMA_FILES = sorted(f for f in os.listdir(_SCHEMAS_DIR) if f.endswith(".json")) if os.path.isdir(_SCHEMAS_DIR) else []


# ── Field-role classification ─────────────────────────────────────────────────

def test_insured_owner_fields_recognized():
    assert is_insured_owner_field("NamedInsured_FullName_A")
    assert is_insured_owner_field("NamedInsured_DBAName_A")
    assert is_insured_owner_field("AdditionalInterest_FullName_A")   # 127 "other owner"


def test_wc_officer_owner_schedule_recognized():
    # ACORD 130's REAL officer/partner/owner field name (verified against
    # forms_schemas/ACORD_130_schema.json - NOT the fictional "Owner_FullName_A",
    # which does not exist on the real form and was never actually protected).
    assert is_insured_owner_field("WorkersCompensation_Individual_FullName_A")
    assert is_insured_owner_field("WorkersCompensation_Individual_FullName_D")
    # Sibling sub-fields of the SAME schedule row (date/percent/code/description)
    # must NOT false-positive just because "individual" appears in their name too.
    assert not is_insured_owner_field("WorkersCompensation_Individual_BirthDate_A")
    assert not is_insured_owner_field("WorkersCompensation_Individual_OwnershipPercent_A")
    assert not is_insured_owner_field("WorkersCompensation_Individual_DutiesDescription_A")
    assert not is_insured_owner_field("WorkersCompensation_Individual_RatingClassificationCode_A")
    # The unrelated ACORD 125/126/127 "is the insured an Individual?" entity-type
    # CHECKBOX must not match either (it is a legal-entity indicator, not a name).
    assert not is_insured_owner_field("NamedInsured_LegalEntity_IndividualIndicator_A")


def test_peo_employer_organization_recognized():
    # ACORD 133's real PEO Notice-of-Assignment employer-identity field.
    assert is_insured_owner_field(
        "WorkersCompensationNoticeOfAssignment_EmployerOrganization_FullName_A"
    )


def test_certificate_holder_recognized():
    # ACORD 25's real certificate-holder field - the third party OWED proof of
    # coverage. Same risk class as an additional interest: a carrier name here
    # misrepresents who the coverage runs to.
    assert is_insured_owner_field("CertificateHolder_FullName_A")
    # Its address sub-fields must still be excluded.
    assert not is_insured_owner_field("CertificateHolder_MailingAddress_CityName_A")


def test_location_name_recognized_when_it_may_be_a_company_name():
    # ACORD 131/133's real location-name fields - tooltip confirms these may
    # legitimately hold the insured's own business name.
    assert is_insured_owner_field("CommercialStructure_Location_FullName_A")
    assert is_insured_owner_field("CommercialStructure_Location_FullName_F")
    assert is_insured_owner_field("Location_FullName_A")


def test_driver_employee_auditor_parent_org_deliberately_excluded():
    # These are real, present-on-real-forms name fields that were evaluated and
    # deliberately left OUT of scope: none of them define who the coverage is
    # for, who owns what's insured, or who is owed proof. A carrier name landing
    # here is a different (lower-severity) risk than what this module targets.
    assert not is_insured_owner_field("Driver_FullName_A")               # ACORD 133
    assert not is_insured_owner_field("Employee_FullName_A")             # ACORD 141
    assert not is_insured_owner_field("Auditor_FullName_A")              # ACORD 141
    assert not is_insured_owner_field("Audit_SignsControlsFullName_A")   # ACORD 141
    assert not is_insured_owner_field("BusinessInformation_ParentOrganizationName_A")  # 125
    assert not is_insured_owner_field("Subsidiary_OrganizationName_A")   # ACORD 125


def test_non_identity_subfields_excluded():
    # A field containing "name" that is really an address/city/contact must NOT
    # be treated as an insured/owner NAME slot.
    assert not is_insured_owner_field("NamedInsured_MailingAddress_CityName_A")
    assert not is_insured_owner_field("NamedInsured_MailingAddress_StateOrProvinceCode_A")
    assert not is_insured_owner_field("Producer_FaxNumber_A")


def test_insurer_field_is_not_an_insured_slot():
    # The carrier field must never be classified as an insured/owner slot.
    assert not is_insured_owner_field("Insurer_FullName_A")
    assert not is_insured_identity_field("Insurer_FullName_A")


def test_high_impact_auto_questions():
    assert is_high_impact_field("CommercialVehicleLineOfBusiness_VehiclesLeasedToOthersExplanation_A")
    assert is_high_impact_field("CommercialVehicleLineOfBusiness_OperationInvolveTransportingHazardousMaterialsExplanation_A")
    assert is_high_impact_field("CommercialVehicleLineOfBusiness_VehicleMaintenanceProgramInOperationExplanation_A")
    assert is_high_impact_field("NamedInsured_FullName_A")   # identity is high-impact too
    # An ordinary, low-stakes field is not high-impact.
    assert not is_high_impact_field("Producer_FaxNumber_A")


def test_high_impact_yesno_answer_field_needs_tooltip():
    # ACORD gives the Yes/No ANSWER field an opaque internal code as its NAME
    # (only the sibling "...Explanation" field has a descriptive name) - the
    # topic is recoverable only from the schema tooltip. Real field names +
    # real tooltip text, verified against ACORD_127_schema.json /
    # ACORD_131_schema.json.
    auto_ownership_tu = (
        "Indicates the response to the question, \"With the exception of "
        "encumbrances, are any vehicles not solely owned by and registered to "
        "the application\"?. "
    )
    leasing_tu = "Indicates the response to the question, \"Are any vehicles leased to others?\". "
    hazmat_tu = (
        "Indicates the response to the question, \"Do operations involve "
        "transporting hazardous material?\". "
    )
    maintenance_tu = (
        "Indicates the response to the question, \"Is there a vehicle "
        "maintenance program in operation?\". "
    )
    hnoa_tu = "The response to the question, \"Are hired and non-owned coverages provided?\" "
    # Without the tooltip, the opaque-coded name alone is NOT recognized -
    # documents the limitation the tooltip parameter closes.
    assert not is_high_impact_field("CommercialVehicleLineOfBusiness_Question_AAJCode_A")
    # With the tooltip, every one of the client's named categories is caught.
    assert is_high_impact_field("CommercialVehicleLineOfBusiness_Question_AAJCode_A", auto_ownership_tu)
    assert is_high_impact_field("CommercialVehicleLineOfBusiness_Question_ABCCode_A", leasing_tu)
    assert is_high_impact_field("CommercialVehicleLineOfBusiness_Question_AAFCode_A", hazmat_tu)
    assert is_high_impact_field("CommercialVehicleLineOfBusiness_Question_KADCode_A", maintenance_tu)
    assert is_high_impact_field("CommercialUmbrellaLineOfBusiness_Question_AAICode_A", hnoa_tu)
    # An unrelated Yes/No question's tooltip must NOT be swept in.
    assert not is_high_impact_field(
        "CommercialVehicleLineOfBusiness_Question_AAECode_A",
        "Indicates the response to the question, \"Are ICC, PUC or other filings required?\". ",
    )


def test_hnoa_synonyms_across_other_forms():
    # HNOA is phrased at least THREE different ways across the 17 forms - all
    # three must be recognized, using the REAL field names and REAL tooltip
    # text from each form (verified by direct schema inspection, not assumed).

    # ACORD 160/25/137/138: SINGULAR "hired auto[s]" / "non-owned auto[s]" -
    # the original phrases (copied from 131's plural wording) did not match
    # this singular form until checked directly against these forms' tooltips.
    assert is_high_impact_field(
        "GeneralLiability_HiredAutoLiabilityBodilyInjury_IncludedIndicator_A",
    )  # caught by field NAME alone ("hiredauto" substring) - no tooltip needed
    assert is_high_impact_field(
        "GeneralLiability_NonOwnedAuto_IncludedIndicator_A",
    )  # caught by field NAME alone ("nonowned" substring)
    assert is_high_impact_field(
        "Vehicle_HiredAutosIndicator_A",
        "Check the box (if applicable): Indicates the vehicle policy covers hired autos only. ",
    )

    # ACORD 137_CA/137_CO: opaque numeric-SYMBOL field names (no "hired"/"owned"
    # substring at all) - only the tooltip reveals the topic.
    assert is_high_impact_field(
        "Vehicle_BusinessAutoSymbol_EightIndicator_A",
        "Check the box (if applicable): Indicates that hired autos only are covered. ",
    )
    assert is_high_impact_field(
        "Vehicle_TruckersSymbol_FiftyIndicator_A",
        "Check the box (if applicable): Indicates that non-owned autos only are covered. ",
    )

    # ACORD 137_CA/137_CO: a THIRD synonym, "hired / borrowed" - caught by
    # field NAME alone this time ("hiredborrowed" substring).
    assert is_high_impact_field("Vehicle_HiredBorrowed_YesIndicator_A")
    assert is_high_impact_field("Vehicle_TruckersHiredBorrowed_NoIndicator_B")
    # Belt-and-suspenders: also caught via tooltip even if the name changed.
    assert is_high_impact_field(
        "Vehicle_SomeOtherFieldName_A",
        "Check the box (if applicable): Indicates if hired / borrowed coverage applies. ",
    )

    # ACORD 141: "leased FROM others" (employees, not vehicles) - the "TO
    # others" case was already covered; "FROM others" was a separate gap until
    # checked directly against the real ACORD 141 tooltip.
    assert is_high_impact_field(
        "CrimeLineOfBusiness_Question_KACCode_A",
        "Indicates the response to the question, \"Any employees leased from others?\". ",
    )


# ── Carrier-shape heuristic ───────────────────────────────────────────────────

def test_looks_like_carrier_true_for_carrier_names():
    assert looks_like_carrier("EMCASCO Insurance Company")
    assert looks_like_carrier("Employers Mutual Casualty Company")
    assert looks_like_carrier("Travelers Indemnity Co")


def test_looks_like_carrier_false_for_ordinary_business():
    assert not looks_like_carrier("Orbin Contracting LLC")
    assert not looks_like_carrier("Wells Fargo Bank")
    assert not looks_like_carrier("Ryder Truck Rental")


def test_looks_like_policy_number_true_for_code_shaped_values():
    # Policy numbers / identifier codes - digit-dominated compact tokens.
    assert looks_like_policy_number("CPP1234567")
    assert looks_like_policy_number("GL 000 123 456")
    assert looks_like_policy_number("WC-9988776")
    assert looks_like_policy_number("842210987")          # bare FEIN pasted into a name box
    assert looks_like_policy_number("1FTBF3B69JEA12345")  # bare VIN pasted into a name box


def test_looks_like_policy_number_false_for_ordinary_business_names():
    # Ordinary owner/business names, including ones that contain a number -
    # letter-dominated, so never mistaken for a policy code.
    assert not looks_like_policy_number("Ryder Truck Rental")
    assert not looks_like_policy_number("3M Company")
    assert not looks_like_policy_number("1st National Bank")
    assert not looks_like_policy_number("84 Lumber Company")
    assert not looks_like_policy_number("12345 Holdings LLC")
    assert not looks_like_policy_number("Wells Fargo Bank")
    assert not looks_like_policy_number("")


def test_looks_like_carrier_can_false_positive_on_a_legitimate_third_party():
    # Documents a KNOWN, accepted trade-off (not a bug to silently paper over):
    # a genuinely correct lienholder/certificate holder whose own real legal
    # name happens to be insurance-shaped still fires the shape heuristic, since
    # it has no extracted carrier fact to be exempted against. This is why the
    # shape-only finding message is worded as a hedge ("if this is really the
    # correct name...") rather than a flat assertion of error - see
    # test_shape_only_finding_is_hedged_fact_match_is_assertive below.
    assert looks_like_carrier("Sunshine Insurance Company") is True


# ── Contamination detection ───────────────────────────────────────────────────

def _forms(mapped, form_id="ACORD_127", field_state=None):
    fr = {"mapped": mapped, "confidence": {}, "schema": {}}
    if field_state is not None:
        fr["field_state"] = field_state
    return {form_id: fr}


def test_carrier_fact_in_insured_field_is_flagged():
    gen = _forms({"NamedInsured_FullName_A": "Employers Mutual Casualty Company"})
    r = detect_field_mapping_contamination(
        gen, merged_facts={"applicant_name": "Orbin Contracting LLC",
                           "carrier_name": "Employers Mutual Casualty Company"},
    )
    assert r["review_required"] is True
    assert r["findings"][0]["reason_code"] == "carrier_in_insured_owner_field"


def test_carrier_shaped_value_in_owner_field_is_flagged_without_a_matching_fact():
    # The Figure 33 case: a carrier name in the vehicle owner box, with no
    # carrier fact to match against - the shape heuristic must still catch it.
    gen = _forms({"AdditionalInterest_FullName_A": "EMCASCO Insurance Company"})
    r = detect_field_mapping_contamination(gen, merged_facts={})
    assert r["review_required"] is True
    assert r["findings"][0]["reason_code"] == "carrier_shaped_value_in_insured_owner_field"


def test_shape_only_finding_is_hedged_fact_match_is_assertive():
    # A fact-matched finding (the value literally equals the extracted carrier
    # name) states the problem plainly. A shape-only finding (no extracted fact
    # confirms it - just LOOKS carrier-shaped) is worded as a hedge, since it
    # can legitimately fire on a correct value (a lienholder whose real name is
    # insurance-shaped) - see test_looks_like_carrier_can_false_positive_on_a_
    # legitimate_third_party. The two must read differently so a broker can
    # tell "this is almost certainly wrong" from "please double-check this".
    fact_matched = detect_field_mapping_contamination(
        _forms({"NamedInsured_FullName_A": "Employers Mutual Casualty Company"}),
        merged_facts={"carrier_name": "Employers Mutual Casualty Company"},
    )["findings"][0]["message"]
    shape_only = detect_field_mapping_contamination(
        _forms({"AdditionalInterest_FullName_A": "Sunshine Insurance Company"}),
        merged_facts={},
    )["findings"][0]["message"]
    assert fact_matched != shape_only
    assert "matches your" in fact_matched
    assert "if this is really the correct name" in shape_only.lower()


def test_policy_number_in_insured_field_is_flagged():
    gen = _forms({"NamedInsured_FullName_A": "CPP1234567"})
    r = detect_field_mapping_contamination(
        gen, merged_facts={"applicant_name": "Orbin Contracting LLC",
                           "policy_number": "CPP1234567"},
    )
    assert r["review_required"] is True
    assert r["findings"][0]["reason_code"] == "policy_in_insured_owner_field"


def test_policy_shaped_value_in_owner_field_is_flagged_without_a_matching_fact():
    # Fix for the asymmetry gap: a hallucinated policy/identifier code in an
    # owner field must be caught by SHAPE even when no extracted policy fact
    # matches it (parity with the carrier-shape fallback). Note empty facts.
    gen = _forms({"AdditionalInterest_FullName_C": "CPP1234567"})
    r = detect_field_mapping_contamination(gen, merged_facts={})
    assert r["review_required"] is True
    assert r["findings"][0]["reason_code"] == "policy_shaped_value_in_insured_owner_field"
    # Its message is worded for a policy code, not a carrier name.
    assert "policy number or identifier code" in r["findings"][0]["message"]
    # And the fill-time single-value check agrees (so it goes orange too).
    assert is_value_contaminated("AdditionalInterest_FullName_C", "CPP1234567", {}) is True


def test_numbered_business_name_in_owner_field_is_not_a_false_policy_positive():
    # The other side of the guard: a legitimate owner name containing a number
    # must NOT be flagged as policy-shaped.
    gen = _forms({"AdditionalInterest_FullName_C": "84 Lumber Company"})
    r = detect_field_mapping_contamination(gen, merged_facts={})
    assert r["review_required"] is False


def test_acord130_wc_officer_field_holds_carrier_name_is_flagged():
    # Same failure class as the ACORD 127 image, on a different form: a carrier
    # name landed in the WC officer/partner/owner schedule instead of a person's
    # name. Proves the FULL pipeline (not just the classifier) catches it now.
    gen = _forms(
        {"WorkersCompensation_Individual_FullName_A": "Employers Mutual Casualty Company"},
        form_id="ACORD_130",
    )
    r = detect_field_mapping_contamination(
        gen, merged_facts={"carrier_name": "Employers Mutual Casualty Company"},
    )
    assert r["review_required"] is True
    assert r["findings"][0]["reason_code"] == "carrier_in_insured_owner_field"


def test_acord130_wc_officer_field_holds_wc_prior_carrier_is_flagged():
    # wc_prior_carrier (ACORD 130's "previous WC carrier" fact) is a SEPARATE
    # extraction key from carrier_name/prior_carrier/current_carrier - it was
    # missing from _CARRIER_FACT_KEYS (found in audit), so a value equal to it
    # landing in the WC officer/owner schedule would NOT have been caught by
    # the fact-match path, only by the weaker carrier-shape heuristic.
    gen = _forms(
        {"WorkersCompensation_Individual_FullName_B": "Old Republic Insurance Company"},
        form_id="ACORD_130",
    )
    r = detect_field_mapping_contamination(
        gen, merged_facts={"wc_prior_carrier": "Old Republic Insurance Company"},
    )
    assert r["review_required"] is True
    assert r["findings"][0]["reason_code"] == "carrier_in_insured_owner_field"
    assert r["findings"][0]["matched_fact_key"] == "wc_prior_carrier"


def test_acord127_owner_boxes_hold_carrier_names_is_flagged():
    # Reproduces the report figure exactly: two "Name of Other Owner" boxes
    # holding carrier names. Must be flagged as a warning (never blocks).
    gen = _forms({
        "AdditionalInterest_FullName_A": "EMCASCO Insurance Company",
        "AdditionalInterest_FullName_B": "EMPLOYERS MUTUAL CASUALTY COMPANY",
    })
    r = detect_field_mapping_contamination(gen, merged_facts={})
    assert r["review_required"] is True
    assert len(r["findings"]) == 2


def test_clean_package_is_not_flagged():
    gen = _forms({
        "NamedInsured_FullName_A": "Orbin Contracting LLC",
        "AdditionalInterest_FullName_A": "Wells Fargo Bank",   # legit lienholder
    })
    r = detect_field_mapping_contamination(
        gen, merged_facts={"applicant_name": "ORBIN CONTRACTING, LLC",
                           "carrier_name": "Employers Mutual Casualty Company"},
    )
    assert r["review_required"] is False
    assert r["findings"] == []


def test_insured_that_is_itself_an_insurance_company_is_exempt():
    # If the applicant genuinely IS an insurance-shaped business and the insured
    # field correctly holds that name, it must not be flagged (no false warning).
    gen = _forms({"NamedInsured_FullName_A": "Acme Insurance Company"})
    r = detect_field_mapping_contamination(
        gen, merged_facts={"applicant_name": "Acme Insurance Company"},
    )
    assert r["review_required"] is False


def test_formatting_only_difference_still_matches_carrier():
    # ALL-CAPS stamped value vs mixed-case carrier fact -> still a match (the
    # shared normalizer makes formatting-only differences equal).
    gen = _forms({"NamedInsured_FullName_A": "EMPLOYERS MUTUAL CASUALTY COMPANY"})
    r = detect_field_mapping_contamination(
        gen, merged_facts={"applicant_name": "Orbin Contracting LLC",
                           "carrier_name": "Employers Mutual Casualty Company"},
    )
    assert r["review_required"] is True


def test_field_state_edit_clears_the_finding():
    # A producer correction lives in field_state; detection must prefer it over
    # the original mapping so a fixed field stops being flagged.
    gen = _forms(
        {"AdditionalInterest_FullName_A": "EMCASCO Insurance Company"},
        field_state={"AdditionalInterest_FullName_A": "Ryder Truck Rental"},
    )
    r = detect_field_mapping_contamination(gen, merged_facts={})
    assert r["review_required"] is False


def test_empty_inputs_are_safe():
    assert detect_field_mapping_contamination(None)["review_required"] is False
    assert detect_field_mapping_contamination({})["review_required"] is False


# ── Single-value check (pdf_service fill-time confidence override) ───────────
# Same classification rules as detect_field_mapping_contamination, exercised at
# the single-(field, value) granularity pdf_service actually calls it at.

def test_is_value_contaminated_true_for_carrier_shaped_owner_value():
    assert is_value_contaminated(
        "AdditionalInterest_FullName_C", "EMCASCO Insurance Company", {},
    ) is True


def test_is_value_contaminated_true_for_carrier_fact_match():
    assert is_value_contaminated(
        "NamedInsured_FullName_A", "Employers Mutual Casualty Company",
        {"carrier_name": "Employers Mutual Casualty Company"},
    ) is True


def test_is_value_contaminated_false_for_clean_owner_name():
    assert is_value_contaminated(
        "AdditionalInterest_FullName_A", "Ryder Truck Rental", {},
    ) is False


def test_is_value_contaminated_false_for_non_owner_field():
    # Even an obviously carrier-shaped value is not "contaminated" for a field
    # that was never an insured/owner slot in the first place (e.g. the
    # legitimate carrier-name field itself).
    assert is_value_contaminated(
        "Insurer_FullName_A", "EMCASCO Insurance Company", {},
    ) is False


def test_is_value_contaminated_respects_applicant_exemption():
    assert is_value_contaminated(
        "NamedInsured_FullName_A", "Acme Insurance Company",
        {"applicant_name": "Acme Insurance Company"},
    ) is False


def test_is_value_contaminated_false_for_empty_value():
    assert is_value_contaminated("NamedInsured_FullName_A", "", {}) is False
    assert is_value_contaminated("NamedInsured_FullName_A", None, {}) is False


def test_is_value_contaminated_agrees_with_detect_field_mapping_contamination():
    # The two entry points must never disagree - same shared classifier.
    field, value = "WorkersCompensation_Individual_FullName_A", "Employers Mutual Casualty Company"
    facts = {"carrier_name": "Employers Mutual Casualty Company"}
    single = is_value_contaminated(field, value, facts)
    whole = detect_field_mapping_contamination(_forms({field: value}), merged_facts=facts)
    assert single is True
    assert whole["review_required"] is True


# ── pdf_service fill-time override: ALL fill sources, not just GPT ───────────
# Live-testing reproduction: CertificateHolder_FullName has its OWN
# deterministic rule (-> the "certificate_holder" fact, distinct from
# "carrier_name"). When a real document's certificate_holder happens to equal
# its carrier, the field was filled deterministically and stayed fully
# trusted (no orange highlight) - inconsistent with a GPT-filled equivalent,
# even though the separate post-generation warning still caught it either way.
# These lock in the fix: the fill-time check now runs on every fill source.

def test_deterministically_filled_owner_field_still_gets_flagged():
    from services.pdf_service import map_facts_to_form
    schema = {"CertificateHolder_FullName_A": {"ft": "/Tx", "tu": "the certificate holder's full name", "required": False}}
    facts = {
        "carrier_name": "Liberty Mutual Insurance Company",
        "certificate_holder": "Liberty Mutual Insurance Company",   # coincidentally == the carrier
    }
    mapped, confidence = map_facts_to_form(facts, schema, form_id="ACORD_25", raw_text="")
    assert mapped["CertificateHolder_FullName_A"] == "Liberty Mutual Insurance Company"   # never blanked
    assert confidence["CertificateHolder_FullName_A"] == "low_confidence"                 # orange, not trusted


def test_deterministically_filled_owner_field_stays_trusted_when_clean():
    from services.pdf_service import map_facts_to_form
    schema = {
        "NamedInsured_FullName_A": {"ft": "/Tx", "tu": "named insured full name", "required": True},
        "CertificateHolder_FullName_A": {"ft": "/Tx", "tu": "the certificate holder's full name", "required": False},
    }
    facts = {
        "applicant_name": "Orbin Contracting LLC",
        "carrier_name": "Liberty Mutual Insurance Company",
        "certificate_holder": "First National Bank",   # genuinely different, correct holder
    }
    mapped, confidence = map_facts_to_form(facts, schema, form_id="ACORD_25", raw_text="")
    assert confidence["NamedInsured_FullName_A"] == "filled"
    assert confidence["CertificateHolder_FullName_A"] == "filled"


# ── Presentation: findings -> warning rows (never blocks) ────────────────────

def test_rows_empty_when_no_findings():
    assert to_recommendation_rows({"findings": []}) == []
    assert to_recommendation_rows(None) == []


def test_rows_one_per_finding_never_hard_stop():
    gen = _forms({
        "AdditionalInterest_FullName_A": "EMCASCO Insurance Company",
        "AdditionalInterest_FullName_B": "EMPLOYERS MUTUAL CASUALTY COMPANY",
    })
    result = detect_field_mapping_contamination(gen, merged_facts={})
    rows = to_recommendation_rows(result)
    # Every finding is surfaced individually - never rolled into a summary,
    # never a different count than the findings themselves.
    assert len(rows) == 2
    assert all(r["type"] == "suggestion" for r in rows)          # soft; never hard_stop
    assert all(r["rec_id"].startswith("fieldmap_") for r in rows)  # isolated audit-table prefix
    assert all(r["message"] for r in rows)
    fields = {r["field"] for r in rows}
    assert fields == {"AdditionalInterest_FullName_A", "AdditionalInterest_FullName_B"}


def test_rows_rec_id_stable_and_collision_safe():
    gen = _forms({"NamedInsured_FullName_A": "Employers Mutual Casualty Company"})
    result = detect_field_mapping_contamination(
        gen, merged_facts={"carrier_name": "Employers Mutual Casualty Company"},
    )
    rows1 = to_recommendation_rows(result)
    rows2 = to_recommendation_rows(result)
    # Same finding -> same rec_id every time (so DB ON CONFLICT dedupes re-runs).
    assert rows1[0]["rec_id"] == rows2[0]["rec_id"]


# ── Exhaustive sweep: every real field on every real form (not a sample) ─────
# Loads forms_schemas/*.json directly - the classifier must never crash on any
# real field name/tooltip across all 17 forms, and every form the client's
# generic-risk claim covers must show at least one recognized owner/insured
# field. This is the regression net against a future ACORD schema change
# silently reopening a gap like the ACORD 130 one found and fixed this session.

def test_all_17_schema_files_present():
    # If this list shrinks, every other test in this file is silently testing
    # fewer forms than it claims to.
    assert len(_ALL_SCHEMA_FILES) == 17, _ALL_SCHEMA_FILES


def test_classifier_never_crashes_on_any_real_field_in_any_real_schema():
    total_fields = 0
    for fname in _ALL_SCHEMA_FILES:
        schema = json.load(open(os.path.join(_SCHEMAS_DIR, fname), encoding="utf-8"))
        for field, meta in schema.items():
            total_fields += 1
            tooltip = meta.get("tu") if isinstance(meta, dict) else None
            # Must return a bool, never raise, for every field name + tooltip
            # combination that actually exists in a real ACORD schema today.
            assert is_insured_owner_field(field) in (True, False)
            assert is_high_impact_field(field, tooltip) in (True, False)
    assert total_fields > 5000, total_fields  # sanity: we actually swept real data


def test_every_form_with_additional_interest_has_a_recognized_owner_field():
    # Forms confirmed (Sec "GENERIC" docstring) to carry an AdditionalInterest_
    # FullName_* field must have at least one field the classifier recognizes.
    forms_with_additional_interest = (
        "ACORD_125_schema.json", "ACORD_126_schema.json", "ACORD_127_schema.json",
        "ACORD_140_schema.json", "ACORD_160_schema.json", "ACORD_28_schema.json",
    )
    for fname in forms_with_additional_interest:
        schema = json.load(open(os.path.join(_SCHEMAS_DIR, fname), encoding="utf-8"))
        recognized = [f for f in schema if is_insured_owner_field(f)]
        assert recognized, f"{fname}: no owner/insured field recognized at all"


def test_wc_and_peo_forms_have_recognized_owner_fields():
    schema_130 = json.load(open(os.path.join(_SCHEMAS_DIR, "ACORD_130_schema.json"), encoding="utf-8"))
    assert any("workerscompensation" in f.lower() and "individual" in f.lower()
               for f in schema_130 if is_insured_owner_field(f))
    schema_133 = json.load(open(os.path.join(_SCHEMAS_DIR, "ACORD_133_schema.json"), encoding="utf-8"))
    assert any("employerorganization" in f.lower() for f in schema_133 if is_insured_owner_field(f))
    assert any(f == "Location_FullName_A" for f in schema_133 if is_insured_owner_field(f))


def test_certificate_and_location_forms_have_recognized_owner_fields():
    schema_25 = json.load(open(os.path.join(_SCHEMAS_DIR, "ACORD_25_schema.json"), encoding="utf-8"))
    assert any("certificateholder" in f.lower() for f in schema_25 if is_insured_owner_field(f))
    schema_131 = json.load(open(os.path.join(_SCHEMAS_DIR, "ACORD_131_schema.json"), encoding="utf-8"))
    assert any("commercialstructure_location" in f.lower() for f in schema_131 if is_insured_owner_field(f))


def test_hnoa_forms_have_at_least_one_recognized_high_impact_field():
    # Every form confirmed (by direct grep) to carry hired/non-owned auto
    # language must have at least one field the classifier recognizes as
    # high-impact, using that form's REAL tooltip text.
    hnoa_forms = (
        "ACORD_131_schema.json", "ACORD_137_CA_schema.json", "ACORD_137_CO_schema.json",
        "ACORD_138_CA_schema.json", "ACORD_138_CO_schema.json", "ACORD_160_schema.json",
        "ACORD_25_schema.json",
    )
    for fname in hnoa_forms:
        schema = json.load(open(os.path.join(_SCHEMAS_DIR, fname), encoding="utf-8"))
        recognized = [
            f for f, meta in schema.items()
            if is_high_impact_field(f, meta.get("tu") if isinstance(meta, dict) else None)
        ]
        assert recognized, f"{fname}: no HNOA-related field recognized as high-impact"


# ── CI regression guard: BOTH deterministic fill paths, not just the AI path ─
# pdf_service's fill-time low-confidence override (map_facts_to_form) only
# covers GPT-filled fields - a deterministic value is trusted by construction
# and left untouched there. That is correct today because NEITHER deterministic
# path (Pass 1's _ACORD_FIELD_RULES substring table, or Pass 1.5's per-form
# alias-map -> CANONICAL_TO_EXTRACTION bridge) currently routes a carrier/
# policy fact into an owner-shaped field - but nothing enforced that as an
# invariant. Without these two tests, adding such a rule in the future would
# not fail CI; it would only surface later as a downstream advisory row from
# the separate post-generation detect_field_mapping_contamination pass. These
# tests turn "currently true" into "must stay true, checked on every run".

_FORBIDDEN_FACTS = frozenset(_CARRIER_FACT_KEYS) | frozenset(_POLICY_FACT_KEYS)


def test_no_pass1_rule_maps_carrier_or_policy_into_an_owner_field():
    from services.pdf_service import _ACORD_FIELD_RULES
    bad = [
        (pattern, fact_key) for pattern, fact_key in _ACORD_FIELD_RULES
        if fact_key in _FORBIDDEN_FACTS and is_insured_owner_field(pattern)
    ]
    assert not bad, (
        f"_ACORD_FIELD_RULES maps a carrier/policy fact into an owner-shaped "
        f"field - this would stamp carrier/policy data with FULL trust "
        f"(confidence='filled', no highlight), bypassing every guard in this "
        f"module: {bad}"
    )


def test_no_alias_map_stamps_carrier_or_policy_into_an_owner_field():
    from services.alias_stamper import CANONICAL_TO_EXTRACTION
    forbidden_canonicals = {
        canon for canon, fact_key in CANONICAL_TO_EXTRACTION.items()
        if fact_key in _FORBIDDEN_FACTS
    }
    alias_dir = os.path.join(os.path.dirname(_SCHEMAS_DIR), "forms_aliases")
    alias_files = [
        f for f in sorted(os.listdir(alias_dir))
        if f.endswith(".json") and not f.startswith("_")
    ]
    assert len(alias_files) == 17, alias_files  # same 17 forms as the schema sweep
    bad = []
    for fname in alias_files:
        alias_map = json.load(open(os.path.join(alias_dir, fname), encoding="utf-8"))
        for acord_field, canonical in alias_map.items():
            if isinstance(canonical, str) and canonical in forbidden_canonicals:
                if is_insured_owner_field(acord_field):
                    bad.append((fname, acord_field, canonical))
    assert not bad, (
        f"A per-form alias map aliases an owner-shaped ACORD field to a "
        f"canonical name that resolves to a carrier/policy fact - same risk as "
        f"the Pass-1 case, via the alias-stamping path instead: {bad}"
    )


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
