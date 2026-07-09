"""
Regression tests for the field-mapping integrity guard (Figure 33 client feedback).

Locks in the two things the client asked for:
  * HIGH-IMPACT classification - insured/owner identity fields plus auto
    ownership / HNOA / leasing / hazardous-materials / maintenance questions.
  * CONTAMINATION detection - carrier/policy data stamped into an insured/owner
    field must be caught so the download can be blocked ("Block download if
    carrier/policy data is mapped into insured/owner fields"). Includes the exact
    ACORD 127 scenario from the report: carrier names in the vehicle owner boxes.

Run from backend/:
    python tests/test_field_mapping_integrity.py
or:
    python -m pytest tests/test_field_mapping_integrity.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.field_mapping_integrity import (  # noqa: E402
    is_insured_owner_field, is_insured_identity_field, is_high_impact_field,
    looks_like_carrier, detect_field_mapping_contamination,
)


# ── Field-role classification ─────────────────────────────────────────────────

def test_insured_owner_fields_recognized():
    assert is_insured_owner_field("NamedInsured_FullName_A")
    assert is_insured_owner_field("NamedInsured_DBAName_A")
    assert is_insured_owner_field("AdditionalInterest_FullName_A")   # 127 "other owner"
    assert is_insured_owner_field("Owner_FullName_A")                # 130 owner


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


# ── Carrier-shape heuristic ───────────────────────────────────────────────────

def test_looks_like_carrier_true_for_carrier_names():
    assert looks_like_carrier("EMCASCO Insurance Company")
    assert looks_like_carrier("Employers Mutual Casualty Company")
    assert looks_like_carrier("Travelers Indemnity Co")


def test_looks_like_carrier_false_for_ordinary_business():
    assert not looks_like_carrier("Orbin Contracting LLC")
    assert not looks_like_carrier("Wells Fargo Bank")
    assert not looks_like_carrier("Ryder Truck Rental")


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


def test_policy_number_in_insured_field_is_flagged():
    gen = _forms({"NamedInsured_FullName_A": "CPP1234567"})
    r = detect_field_mapping_contamination(
        gen, merged_facts={"applicant_name": "Orbin Contracting LLC",
                           "policy_number": "CPP1234567"},
    )
    assert r["review_required"] is True
    assert r["findings"][0]["reason_code"] == "policy_in_insured_owner_field"


def test_acord127_owner_boxes_hold_carrier_names_blocks():
    # Reproduces the report figure exactly: two "Name of Other Owner" boxes
    # holding carrier names. The package must be blockable.
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
    # field correctly holds that name, it must not be flagged (no false block).
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
    # the original mapping so a fixed field no longer blocks.
    gen = _forms(
        {"AdditionalInterest_FullName_A": "EMCASCO Insurance Company"},
        field_state={"AdditionalInterest_FullName_A": "Ryder Truck Rental"},
    )
    r = detect_field_mapping_contamination(gen, merged_facts={})
    assert r["review_required"] is False


def test_empty_inputs_are_safe():
    assert detect_field_mapping_contamination(None)["review_required"] is False
    assert detect_field_mapping_contamination({})["review_required"] is False


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
