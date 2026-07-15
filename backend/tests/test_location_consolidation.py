"""
Regression tests for canonical multi-location consolidation (Figure 27 client
feedback: duplicate 4800 Dahlia Street premises rows with blank COPE fields
and no owner/tenant distinction on ACORD 125).

Covers three layers of the fix:
  * extraction_service._consolidate_property_locations — near-duplicate
    address mentions (case/punctuation/format drift across chunks or
    documents) collapse into ONE canonical location, merging whatever
    sub-fields each mention contributed rather than discarding data.
  * pdf_service._SCHEDULE_REGISTRY / _resolve_schedule_row — ACORD 125's
    repeating premises rows (A/B/C/D) pull DISTINCT sub-fields from distinct
    consolidated locations, not one broadcast scalar.
  * cross_form_validator._check_per_location_cope_completeness — a
    multi-location property submission with partial per-location COPE data
    is flagged for review.

Run from backend/:
    python tests/test_location_consolidation.py
or:
    python -m pytest tests/test_location_consolidation.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.extraction_service import _consolidate_property_locations  # noqa: E402
from services.pdf_service import (  # noqa: E402
    _resolve_schedule_row, _SCHED_SKIP, map_facts_to_form,
    _resolve_subject_of_insurance_row,
)
from services.cross_form_validator import _check_per_location_cope_completeness  # noqa: E402


# ── Figure 27: the four real screenshot variants ──────────────────────────────

_FIGURE_27_VARIANTS = [
    "4800 Dahlia St # D13",
    "4800 DAHLIA ST # D13",
    "4800 Dahlia St # D13, Denver, CO 80216-3121",
    "4800 DAHLIA STREET D13, DENVER CO 80216-3121",
]


def test_figure27_duplicate_addresses_collapse_to_one_location():
    facts = {"locations": list(_FIGURE_27_VARIANTS), "property_locations": []}
    _consolidate_property_locations(facts)

    locs = facts["property_locations"]
    assert len(locs) == 1, f"expected 1 consolidated location, got {len(locs)}: {locs}"
    assert facts["locations"] == [locs[0]["address"]]

    # The longest/most complete raw mention wins as the display address.
    assert "denver" in locs[0]["address"].lower()
    assert "80216" in locs[0]["address"]


def test_distinct_addresses_do_not_collapse():
    facts = {
        "locations": ["100 N Main St, Denver, CO 80202", "100 S Main St, Denver, CO 80202"],
        "property_locations": [],
    }
    _consolidate_property_locations(facts)
    assert len(facts["property_locations"]) == 2


def test_sub_fields_merge_across_near_duplicate_mentions_without_loss():
    # Same physical location mentioned twice with different formatting AND
    # each mention contributing DIFFERENT real sub-field data (as would
    # happen if one chunk saw the dec-page premises row and another saw an
    # attached schedule with the COPE detail). Nothing should be dropped.
    facts = {
        "property_locations": [
            {"address": "4800 Dahlia St #D13", "ownership": "owner", "full_time_employees": "12"},
            {"address": "4800 DAHLIA ST #D13, Denver, CO 80216",
             "construction_type": "Masonry", "building_value": "$500,000"},
        ]
    }
    _consolidate_property_locations(facts)

    assert len(facts["property_locations"]) == 1
    loc = facts["property_locations"][0]
    assert loc["ownership"] == "owner"
    assert loc["full_time_employees"] == "12"
    assert loc["construction_type"] == "Masonry"
    assert loc["building_value"] == "$500,000"


def test_address_decomposed_for_per_slot_stamping():
    facts = {"property_locations": [{"address": "4800 Dahlia St #D13, Denver, CO 80216-3121"}]}
    _consolidate_property_locations(facts)
    loc = facts["property_locations"][0]
    assert loc["address_city"] == "Denver"
    assert loc["address_state"] == "CO"
    assert loc["address_zip"] == "80216-3121"
    assert loc["location_id"] == "L1"


def test_ownership_derives_owner_tenant_booleans():
    facts = {"property_locations": [
        {"address": "1 Owner Way", "ownership": "Owner"},
        {"address": "2 Tenant Way", "ownership": "tenant"},
        {"address": "3 Unknown Way"},
    ]}
    _consolidate_property_locations(facts)
    by_addr = {l["address"]: l for l in facts["property_locations"]}
    assert by_addr["1 Owner Way"]["is_owner"] is True
    assert by_addr["1 Owner Way"]["is_tenant"] is False
    assert by_addr["2 Tenant Way"]["is_owner"] is False
    assert by_addr["2 Tenant Way"]["is_tenant"] is True
    # No ownership signal at all -> unknown, not a false "No".
    assert by_addr["3 Unknown Way"]["is_owner"] is None
    assert by_addr["3 Unknown Way"]["is_tenant"] is None


def test_city_limits_boolean_derives_inside_outside_pair():
    facts = {"property_locations": [
        {"address": "1 Inside Way", "inside_city_limits": True},
        {"address": "2 Outside Way", "inside_city_limits": False},
    ]}
    _consolidate_property_locations(facts)
    by_addr = {l["address"]: l for l in facts["property_locations"]}
    assert by_addr["1 Inside Way"]["is_inside_city_limits"] is True
    assert by_addr["1 Inside Way"]["is_outside_city_limits"] is False
    assert by_addr["2 Outside Way"]["is_inside_city_limits"] is False
    assert by_addr["2 Outside Way"]["is_outside_city_limits"] is True


def test_empty_property_locations_falls_back_to_physical_address():
    facts = {"locations": [], "property_locations": [], "physical_address": "9 Fallback Ave, Denver, CO 80202"}
    _consolidate_property_locations(facts)
    assert len(facts["property_locations"]) == 1
    assert facts["property_locations"][0]["address"] == "9 Fallback Ave, Denver, CO 80202"


def test_no_location_signal_at_all_is_a_noop():
    facts = {"locations": [], "property_locations": []}
    _consolidate_property_locations(facts)
    assert facts["property_locations"] == []


# ── pdf_service: distinct per-slot stamping via the schedule registry ─────────

def test_acord125_slots_pull_distinct_values_per_location():
    facts = {
        "property_locations": [
            {"address_line1": "100 First St", "address_city": "Denver", "address_state": "CO",
             "address_zip": "80202", "annual_revenue": "$1,000,000",
             "full_time_employees": "10", "is_owner": True, "is_tenant": False},
            {"address_line1": "200 Second St", "address_city": "Boulder", "address_state": "CO",
             "address_zip": "80301", "annual_revenue": "$500,000",
             "full_time_employees": "4", "is_owner": False, "is_tenant": True},
        ]
    }

    slot_a_addr = _resolve_schedule_row("CommercialStructure_PhysicalAddress_LineOne_A", facts)
    slot_b_addr = _resolve_schedule_row("CommercialStructure_PhysicalAddress_LineOne_B", facts)
    assert slot_a_addr == "100 First St"
    assert slot_b_addr == "200 Second St"
    assert slot_a_addr != slot_b_addr  # the exact Figure 27 failure mode

    assert _resolve_schedule_row("CommercialStructure_AnnualRevenueAmount_A", facts) == "$1,000,000"
    assert _resolve_schedule_row("CommercialStructure_AnnualRevenueAmount_B", facts) == "$500,000"

    assert _resolve_schedule_row("CommercialStructure_InsuredInterest_OwnerIndicator_A", facts) == "Yes"
    assert _resolve_schedule_row("CommercialStructure_InsuredInterest_TenantIndicator_A", facts) == "No"
    assert _resolve_schedule_row("CommercialStructure_InsuredInterest_OwnerIndicator_B", facts) == "No"
    assert _resolve_schedule_row("CommercialStructure_InsuredInterest_TenantIndicator_B", facts) == "Yes"

    # Slot C has no third location -> leave blank, not a repeat of A/B.
    assert _resolve_schedule_row("CommercialStructure_PhysicalAddress_LineOne_C", facts) is None


def test_loc_number_populates_sequentially_end_to_end():
    # Regression: CommercialStructure_Location_ProducerIdentifier_{row} (the
    # visible "LOC #" box) is a naming false-positive caught by
    # _is_nonfillable_field()'s broad "ProducerIdentifier" block, which runs
    # BEFORE schedule resolution and short-circuited it to permanently blank
    # even after the field was correctly registered in _SCHEDULE_REGISTRY.
    # Must go through the real map_facts_to_form() entry point, not just
    # _resolve_schedule_row(), since the bug lived in the OUTER nonfillable
    # check, not the schedule resolver itself.
    schema = {
        "CommercialStructure_Location_ProducerIdentifier_A": {"ft": "/Tx", "required": False},
        "CommercialStructure_Location_ProducerIdentifier_B": {"ft": "/Tx", "required": False},
        "Producer_CustomerIdentifier": {"ft": "/Tx", "required": False},
    }
    facts = {"property_locations": [{"address": "1 A St"}, {"address": "2 B St"}]}
    _consolidate_property_locations(facts)
    mapped, confidence = map_facts_to_form(facts, schema, form_id="ACORD_125", raw_text="")

    assert mapped["CommercialStructure_Location_ProducerIdentifier_A"] == "1"
    assert mapped["CommercialStructure_Location_ProducerIdentifier_B"] == "2"
    # The general "ProducerIdentifier" nonfillable block must still hold for
    # genuinely agency-assigned codes - this override must not be a blanket
    # unblock of every field containing "ProducerIdentifier".
    assert mapped.get("Producer_CustomerIdentifier") is None


def test_acord131_reuses_same_registry_for_its_own_A_D_rows():
    # Confirms the shared-field registration (not form-scoped) correctly
    # serves a second form (ACORD 131) that carries the identical ACORD field
    # concept, matching the existing LossHistory_*/PriorCoverage_* pattern.
    facts = {"property_locations": [{"address_line1": "1 Umbrella Ave"}]}
    assert _resolve_schedule_row("CommercialStructure_PhysicalAddress_LineOne_A", facts) == "1 Umbrella Ave"


def test_unregistered_field_still_skips():
    assert _resolve_schedule_row("Producer_FullName", {}) is _SCHED_SKIP


# ── pdf_service: resolved Owner/Tenant pairs must not false-flag as missing ───
# Regression for a bug found during manual re-verification: Owner/Tenant and
# Inside/Outside-City-Limits are COMPLEMENTARY checkbox pairs where exactly
# one side is a deliberate "No". _acord125_has_value() treats "No" as "no
# value" (correct for ordinary yes/no questions elsewhere on the form), which
# — before the fix — caused the correctly-resolved "No" half of the pair to
# be flagged missing_required, producing a false yellow highlight and a
# spurious client question re-asking something already known.

_ACORD125_LOCATION_SCHEMA = {
    "CommercialStructure_Location_ProducerIdentifier_A": {"ft": "/Tx", "required": False},
    "CommercialStructure_Location_ProducerIdentifier_B": {"ft": "/Tx", "required": False},
    "CommercialStructure_PhysicalAddress_LineOne_A": {"ft": "/Tx", "required": False},
    "CommercialStructure_InsuredInterest_OwnerIndicator_A": {"ft": "/Btn", "required": False},
    "CommercialStructure_InsuredInterest_TenantIndicator_A": {"ft": "/Btn", "required": False},
    "CommercialStructure_InsuredInterest_OtherIndicator_A": {"ft": "/Btn", "required": False},
    "CommercialStructure_InsuredInterest_OtherDescription_A": {"ft": "/Tx", "required": False},
    "CommercialStructure_RiskLocation_InsideCityLimitsIndicator_A": {"ft": "/Btn", "required": False},
    "CommercialStructure_RiskLocation_OutsideCityLimitsIndicator_A": {"ft": "/Btn", "required": False},
    "BuildingOccupancy_OccupiedArea_A": {"ft": "/Tx", "required": False},
    "Construction_BuildingArea_A": {"ft": "/Tx", "required": False},
}


def test_resolved_owner_tenant_pair_not_falsely_flagged_missing():
    facts = {"property_locations": [{"address": "100 First St", "ownership": "owner", "inside_city_limits": True}]}
    _consolidate_property_locations(facts)
    mapped, confidence = map_facts_to_form(facts, _ACORD125_LOCATION_SCHEMA, form_id="ACORD_125", raw_text="")

    assert mapped["CommercialStructure_InsuredInterest_OwnerIndicator_A"] == "Yes"
    assert mapped["CommercialStructure_InsuredInterest_TenantIndicator_A"] == "No"
    # The resolved "No" must NOT be flagged missing_required.
    assert confidence["CommercialStructure_InsuredInterest_TenantIndicator_A"] != "missing_required"
    assert confidence["CommercialStructure_InsuredInterest_OwnerIndicator_A"] != "missing_required"
    assert confidence["CommercialStructure_RiskLocation_OutsideCityLimitsIndicator_A"] != "missing_required"


def test_unknown_ownership_on_started_row_is_flagged_exactly_once():
    facts = {"property_locations": [{"address": "200 Second St"}]}  # no ownership signal at all
    _consolidate_property_locations(facts)
    mapped, confidence = map_facts_to_form(facts, _ACORD125_LOCATION_SCHEMA, form_id="ACORD_125", raw_text="")

    flagged = [
        f for f in (
            "CommercialStructure_InsuredInterest_OwnerIndicator_A",
            "CommercialStructure_InsuredInterest_TenantIndicator_A",
        )
        if confidence.get(f) == "missing_required"
    ]
    assert len(flagged) == 1, f"expected exactly one flagged field, got {flagged}"


# ── pdf_service: "Other" interest must not contradict a resolved Tenant/Owner ─
# Regression for a bug found via a real generated PDF: ownership text like
# "Tenant (leased office space)" was correctly resolving Tenant=Yes, but the
# separate, ungated InsuredInterest_OtherIndicator/OtherDescription fields
# were independently filled by GPT gap-fill ("Other" checked + "leased office
# space" description) - producing a contradictory PDF (Tenant AND Other both
# checked on the same row).

def test_tenant_resolution_suppresses_other_interest():
    facts = {"property_locations": [{"address": "1 A St", "ownership": "Tenant (leased office space)"}]}
    _consolidate_property_locations(facts)
    mapped, confidence = map_facts_to_form(facts, _ACORD125_LOCATION_SCHEMA, form_id="ACORD_125", raw_text="")

    assert mapped["CommercialStructure_InsuredInterest_TenantIndicator_A"] == "Yes"
    assert mapped["CommercialStructure_InsuredInterest_OtherIndicator_A"] == "No"
    assert mapped.get("CommercialStructure_InsuredInterest_OtherDescription_A") is None
    assert confidence["CommercialStructure_InsuredInterest_OtherIndicator_A"] != "missing_required"


def test_genuine_other_interest_resolves_deterministically_and_owner_not_flagged():
    facts = {"property_locations": [{"address": "1 A St", "ownership": "Licensee under a shared-use agreement"}]}
    _consolidate_property_locations(facts)
    mapped, confidence = map_facts_to_form(facts, _ACORD125_LOCATION_SCHEMA, form_id="ACORD_125", raw_text="")

    assert mapped["CommercialStructure_InsuredInterest_OtherIndicator_A"] == "Yes"
    assert mapped["CommercialStructure_InsuredInterest_OtherDescription_A"] == "Licensee under a shared-use agreement"
    # A resolved "Other" must count as resolved - Owner must not be flagged missing.
    assert confidence["CommercialStructure_InsuredInterest_OwnerIndicator_A"] != "missing_required"


# ── pdf_service: total_building_area must never be a silent copy of occupied_area ─
# Regression for a bug found via a real generated PDF: Construction_BuildingArea
# (the "TOTAL BUILDING AREA" column) was unregistered, fell to ungated GPT
# gap-fill, and got filled with a copy of occupied_area instead of staying
# blank when the source document never stated the whole building's size.

def test_total_building_area_stays_blank_when_not_provided():
    facts = {"property_locations": [{"address": "1 A St", "occupied_area": "4,200 sq ft"}]}
    _consolidate_property_locations(facts)
    mapped, confidence = map_facts_to_form(facts, _ACORD125_LOCATION_SCHEMA, form_id="ACORD_125", raw_text="")

    assert mapped["BuildingOccupancy_OccupiedArea_A"] == "4,200 sq ft"
    assert mapped.get("Construction_BuildingArea_A") is None
    assert mapped.get("Construction_BuildingArea_A") != mapped["BuildingOccupancy_OccupiedArea_A"]


def test_total_building_area_uses_its_own_value_when_provided():
    facts = {"property_locations": [{"address": "1 A St", "occupied_area": "4,200 sq ft", "total_building_area": "10,000 sq ft"}]}
    _consolidate_property_locations(facts)
    mapped, confidence = map_facts_to_form(facts, _ACORD125_LOCATION_SCHEMA, form_id="ACORD_125", raw_text="")

    assert mapped["Construction_BuildingArea_A"] == "10,000 sq ft"
    assert mapped["BuildingOccupancy_OccupiedArea_A"] == "4,200 sq ft"


# ── cross_form_validator: per-location COPE completeness ──────────────────────

def test_partial_per_location_cope_flagged():
    facts = {
        "property_locations": [
            {"address": "1 Complete St", "construction_type": "Masonry", "building_value": "$500,000"},
            {"address": "2 Incomplete St"},
        ]
    }
    flags = {"has_property_coverage": True}
    issues = _check_per_location_cope_completeness(facts, flags, {"ACORD_140"})
    assert len(issues) == 1
    assert issues[0]["code"] == "per_location_cope_incomplete"
    assert issues[0]["type"] == "soft_warning"


def test_all_locations_complete_no_issue():
    facts = {
        "property_locations": [
            {"address": "1 A St", "construction_type": "Masonry", "building_value": "$500,000"},
            {"address": "2 B St", "construction_type": "Frame", "bpp_value": "$100,000"},
        ]
    }
    issues = _check_per_location_cope_completeness(facts, {"has_property_coverage": True}, {"ACORD_140"})
    assert issues == []


def test_single_location_not_flagged_here_minimum_viable_cope_owns_it():
    facts = {"property_locations": [{"address": "1 Only St"}]}
    issues = _check_per_location_cope_completeness(facts, {"has_property_coverage": True}, {"ACORD_140"})
    assert issues == []  # single-location gap is _check_minimum_viable_cope_unit's job


def test_no_property_coverage_no_issue():
    facts = {"property_locations": [{"address": "1 A St"}, {"address": "2 B St"}]}
    issues = _check_per_location_cope_completeness(facts, {"has_property_coverage": False}, {"ACORD_140"})
    assert issues == []


# ── pdf_service: ACORD 140 "Subject of Insurance" per-premises grid ───────────
# Regression for a bug found via a real generated ACORD 140: this grid's row
# lettering is NOT "letter = premises index" (the scheme used everywhere else
# on the form). Confirmed against ACORD_140_schema.json: premises 1's address
# is CommercialStructure_PhysicalAddress_LineOne_A and premises 2's is _B, but
# CommercialProperty_Premises_LimitAmount jumps from _E straight to _G for
# premises 2's first subject row (each premises gets its own 6-letter block:
# 5 real subject rows + 1 unused spacer). Values from TWO DIFFERENT locations
# were landing in ONE premises block's grid before this was wired up.

def test_subject_of_insurance_maps_letter_blocks_to_correct_premises():
    facts = {"property_locations": [
        {"address": "1 A St", "building_value": "$0", "bpp_value": "$310,000"},
        {"address": "2 B St", "building_value": "$650,000", "bpp_value": "$95,000"},
    ]}
    # Premises 1 = A (Building), B (BPP). Premises 2 = G (Building), H (BPP).
    assert _resolve_subject_of_insurance_row("CommercialProperty_Premises_SubjectOfInsuranceCode_A", facts) == "Building"
    assert _resolve_subject_of_insurance_row("CommercialProperty_Premises_LimitAmount_A", facts) == "$0"
    assert _resolve_subject_of_insurance_row("CommercialProperty_Premises_SubjectOfInsuranceCode_B", facts) == "Business Personal Property"
    assert _resolve_subject_of_insurance_row("CommercialProperty_Premises_LimitAmount_B", facts) == "$310,000"
    assert _resolve_subject_of_insurance_row("CommercialProperty_Premises_SubjectOfInsuranceCode_G", facts) == "Building"
    assert _resolve_subject_of_insurance_row("CommercialProperty_Premises_LimitAmount_G", facts) == "$650,000"
    assert _resolve_subject_of_insurance_row("CommercialProperty_Premises_SubjectOfInsuranceCode_H", facts) == "Business Personal Property"
    assert _resolve_subject_of_insurance_row("CommercialProperty_Premises_LimitAmount_H", facts) == "$95,000"
    # The spacer letters (F, L, ...) are never real rows.
    assert _resolve_subject_of_insurance_row("CommercialProperty_Premises_LimitAmount_F", facts) is _SCHED_SKIP


def test_subject_of_insurance_survives_post_fill_dedup_guard_end_to_end():
    # Must go through the real map_facts_to_form() entry point, not just the
    # resolver in isolation — the bug lived in _enforce_post_fill_guards'
    # Guard 2 (repeating-row de-duplication), which runs AFTER Pass 1 and was
    # nulling out "Building" on premises 2 because it correctly matched
    # premises 1's "Building" label (two different, real locations both
    # having a Building subject looked, to that guard, like a false echo).
    schema = {}
    for letter in ("A", "B", "G", "H"):
        schema[f"CommercialProperty_Premises_SubjectOfInsuranceCode_{letter}"] = {"ft": "/Tx", "required": False}
        schema[f"CommercialProperty_Premises_LimitAmount_{letter}"] = {"ft": "/Tx", "required": False}

    facts = {"property_locations": [
        {"address": "1 A St", "building_value": "$0", "bpp_value": "$310,000"},
        {"address": "2 B St", "building_value": "$650,000", "bpp_value": "$95,000"},
    ]}
    _consolidate_property_locations(facts)
    mapped, confidence = map_facts_to_form(facts, schema, form_id="ACORD_140", raw_text="")

    assert mapped["CommercialProperty_Premises_SubjectOfInsuranceCode_A"] == "Building"
    assert mapped["CommercialProperty_Premises_SubjectOfInsuranceCode_G"] == "Building"
    assert mapped["CommercialProperty_Premises_LimitAmount_A"] == "$0"
    assert mapped["CommercialProperty_Premises_LimitAmount_G"] == "$650,000"


def test_subject_of_insurance_survives_dedup_even_with_coincidentally_equal_amounts():
    # Wider version of the same bug: even the LimitAmount (dollar) field would
    # have been silently nulled if two locations happened to share the exact
    # same figure - not just the "Building" label case the live test caught.
    schema = {
        "CommercialProperty_Premises_LimitAmount_A": {"ft": "/Tx", "required": False},
        "CommercialProperty_Premises_LimitAmount_G": {"ft": "/Tx", "required": False},
    }
    facts = {"property_locations": [
        {"address": "1 A St", "building_value": "$500,000"},
        {"address": "2 B St", "building_value": "$500,000"},
    ]}
    _consolidate_property_locations(facts)
    mapped, confidence = map_facts_to_form(facts, schema, form_id="ACORD_140", raw_text="")

    assert mapped["CommercialProperty_Premises_LimitAmount_A"] == "$500,000"
    assert mapped["CommercialProperty_Premises_LimitAmount_G"] == "$500,000"


if __name__ == "__main__":
    import inspect
    mod = sys.modules[__name__]
    tests = [obj for name, obj in inspect.getmembers(mod) if name.startswith("test_") and callable(obj)]
    passed, failed = 0, 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
