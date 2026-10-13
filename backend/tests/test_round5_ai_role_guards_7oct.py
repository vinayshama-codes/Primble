"""Round 5 (7 Oct 2026) - an AI value must hold the ROLE of its box.

The owner's live run (real AI fill) printed values that ARE in the documents but
belong to another box: the construction type as the fire-protection description,
the LOC number as the highest floor, a WC rating line's premium as the WC
deductible, the expiring term's date as the BINDER date, and the account's
contact name / phone as the producer's CSR / CELL phone.

Each class is pinned by its SHAPE (no client strings), each with the negative
controls that must keep printing - the legitimate equalities measured on the
stored corpus. `services/ai_role_guards.py` holds the rules; the binder box is
an owned blank in `pdf_service._resolve_policy_status`.
"""
import copy
import json
import os

import pytest

import services.ai_role_guards as rg
import services.pdf_service as ps

_SCHEMAS = os.path.join(os.path.dirname(__file__), "..", "forms_schemas")


def _schema(form_id):
    with open(os.path.join(_SCHEMAS, f"{form_id}_schema.json")) as fh:
        return json.load(fh)


def _run(mapped, form_id, facts=None, raw="", ai=None):
    m = dict(mapped)
    out = rg.drop_role_mismatches(m, _schema(form_id), dict(facts or {}), raw,
                                  set(ai if ai is not None else mapped), form_id)
    return m, out


# ══ (a) another categorical fact's value ═════════════════════════════════════

_FIRE_DESC = "BuildingFireProtection_Alarm_ProtectionDescription_A"


class TestAnotherFactsValue:
    def test_construction_type_in_the_fire_protection_box_is_borrowed(self):
        m, out = _run({_FIRE_DESC: "FRAME"}, "ACORD_140", {"construction_type": "FRAME"})
        assert m[_FIRE_DESC] is None
        assert out[_FIRE_DESC].startswith(rg.R_OTHER_FACT + ":")

    def test_a_schedule_row_column_is_the_same_fact(self):
        facts = {"property_locations": [{"construction_type": "Joisted Masonry"}]}
        m, out = _run({_FIRE_DESC: "joisted  masonry"}, "ACORD_140", facts)
        assert _FIRE_DESC in out

    def test_the_facts_own_box_keeps_it(self):
        m, out = _run({"Construction_ConstructionCode_A": "FRAME"}, "ACORD_140",
                      {"construction_type": "FRAME"})
        assert out == {} and m["Construction_ConstructionCode_A"] == "FRAME"

    def test_a_box_whose_name_names_the_subject_keeps_it(self):
        # Construction_RoofMaterialCode names construction; the other legal
        # entity's description names the entity.
        m, out = _run({"Construction_RoofMaterialCode_A": "Masonry"}, "ACORD_140",
                      {"construction_type": "Masonry"})
        assert out == {}
        m, out = _run({"NamedInsured_LegalEntity_OtherDescription_A": "Limited Liability Company"},
                      "ACORD_125", {"entity_type": "Limited Liability Company"})
        assert out == {}

    def test_a_value_acord_offers_in_the_box_is_never_borrowed(self):
        # "AN - Annual" is one of the payment-plan box's own options.
        m, out = _run({"Policy_Payment_PaymentScheduleCode_A": "Annual"}, "ACORD_125",
                      {"wc_payroll_period": "annual"})
        assert out == {}
        # "B - Building" is a subject of insurance, whatever fact also says it.
        m, out = _run({"CommercialProperty_Premises_SubjectOfInsuranceCode_A": "Building"},
                      "ACORD_140", {"occupancy_type": "Building"})
        assert out == {}

    def test_a_condition_of_the_facts_own_row_keeps_it(self):
        # FORMS AND CONDITIONS TO APPLY sits in the premises row whose
        # VALUATION box is the valuation's own: "AGREED VALUE" is a condition
        # of that row (the owner verified it on the live run).
        m, out = _run({"CommercialProperty_Premises_FormsAndConditions_B": "AGREED VALUE"},
                      "ACORD_140", {"valuation_method": "Agreed Value"})
        assert out == {}
        # ...but a CODE box of the same row is another attribute.
        m, out = _run({"CommercialProperty_Premises_SubjectOfInsuranceCode_A": "Agreed Value"},
                      "ACORD_140", {"valuation_method": "Agreed Value"})
        assert "CommercialProperty_Premises_SubjectOfInsuranceCode_A" in out

    def test_a_description_of_the_risk_itself_may_use_its_attributes(self):
        box = "CommercialStructure_Building_SublocationDescription_A"
        m, out = _run({box: "Cabinet shop and warehouse"}, "ACORD_140",
                      {"occupancy_type": "Cabinet shop and warehouse"})
        assert out == {}

    def test_a_coverage_form_type_in_another_coverage_row_is_borrowed(self):
        box = "GeneralLiability_OtherCoverageDescription_A"
        m, out = _run({box: "Occurrence"}, "ACORD_126", {"gl_form_type": "Occurrence"})
        assert box in out

    def test_an_entity_type_in_a_relationship_or_a_marital_box_is_borrowed(self):
        m, out = _run({"Subsidiary_ParentSubsidiaryRelationshipDescription_A": "LLC"},
                      "ACORD_125", {"entity_type": "LLC"})
        assert "Subsidiary_ParentSubsidiaryRelationshipDescription_A" in out
        m, out = _run({"Driver_MaritalStatusCode_A": "Limited Liability Company"},
                      "ACORD_127", {"entity_type": "Limited Liability Company"})
        assert "Driver_MaritalStatusCode_A" in out

    def test_a_valuation_in_an_amount_box_is_borrowed(self):
        m, out = _run({"Vehicle_Coverage_AgreedOrStatedAmount_A": "ACV"}, "ACORD_127",
                      {"auto_physical_damage_valuation": "ACV"})
        assert "Vehicle_Coverage_AgreedOrStatedAmount_A" in out

    @pytest.mark.parametrize("value", ["3", "Yes", "None", "N/A", "", "Other",
                                       "a very long sentence that is no category at all here"])
    def test_numbers_answers_and_placeholders_are_never_categories(self, value):
        m, out = _run({_FIRE_DESC: value}, "ACORD_140", {"construction_type": value,
                                                        "fire_protection_class": value})
        assert out == {}

    def test_a_value_no_categorical_fact_states_is_not_judged(self):
        m, out = _run({_FIRE_DESC: "Wet pipe sprinklers"}, "ACORD_140",
                      {"construction_type": "FRAME"})
        assert out == {}

    def test_a_deterministic_or_persons_value_is_never_judged(self):
        m, out = _run({_FIRE_DESC: "FRAME"}, "ACORD_140", {"construction_type": "FRAME"}, ai=set())
        assert out == {} and m[_FIRE_DESC] == "FRAME"

    def test_a_checkbox_is_another_guards(self):
        box = "BuildingFireProtection_Alarm_CentralStationIndicator_A"
        m, out = _run({box: "FRAME"}, "ACORD_140", {"construction_type": "FRAME"})
        assert box not in out


# ══ (b) a short count with no labelled witness ═══════════════════════════════

_FLOOR = "Location_HighestFloorCount_A"
# Generation-time facts: the declarations index exists (here with nothing that
# counts floors). The purge deletes it after generation - see TestPurgedIndex.
_IDX = {"dec_page_entries": []}


class TestShortCounts:
    def test_the_loc_number_as_the_highest_floor_is_refused(self):
        raw = "LOC 1 Prem. #: 001 Bldg #: 001\n1133 Avenue of the Americas, 32nd Floor"
        m, out = _run({_FLOOR: "1", "Location_HighestFloorCount_B": "1"}, "ACORD_130", _IDX, raw=raw)
        assert m[_FLOOR] is None and m["Location_HighestFloorCount_B"] is None
        assert out[_FLOOR].startswith(rg.R_COUNT + ":")

    @pytest.mark.parametrize("raw", ["Building 1: 2 STORY FRAME", "Number of Floors: 2",
                                     "Stories: 2", "a two story building"])
    def test_a_storey_or_floor_printed_beside_the_number_keeps_it(self, raw):
        m, out = _run({_FLOOR: "2"}, "ACORD_130", raw=raw)
        assert out == {} and m[_FLOOR] == "2"

    def test_a_verified_entry_or_a_fact_keeps_it(self):
        entries = [{"label": "Number of Stories", "value": "3", "section": "Premises"}]
        assert _run({_FLOOR: "3"}, "ACORD_130", {"dec_page_entries": entries})[1] == {}
        assert _run({_FLOOR: "3"}, "ACORD_130", {"building_floors": "3"})[1] == {}

    def test_a_seating_capacity_needs_its_seats(self):
        box = "Vehicle_SeatingCapacityCount_A"
        assert box in _run({box: "5"}, "ACORD_127", _IDX, raw="RADIUS NA")[1]
        assert _run({box: "5"}, "ACORD_127", _IDX, raw="2019 SEDAN 5 SEATS")[1] == {}
        assert _run({box: "5"}, "ACORD_127", _IDX, raw="Seating Capacity: 5")[1] == {}

    def test_zero_and_long_values_are_not_this_rules(self):
        assert _run({_FLOOR: "0"}, "ACORD_130")[1] == {}
        assert _run({_FLOOR: "1200"}, "ACORD_130")[1] == {}

    def test_a_count_the_tooltip_already_names_is_left_to_the_count_guard(self):
        # "The number of employees" - `_drop_unstated_counts` owns it.
        assert _run({"BusinessInformation_EmployeeCount_A": "4"}, "ACORD_131")[1] == {}

    def test_a_measurement_is_not_a_count(self):
        assert _run({"BuildingFireProtection_HydrantDistanceFeetCount_A": "3"}, "ACORD_140")[1] == {}

    def test_expected_life_in_months_needs_its_months(self):
        box = "ProductAndCompletedOperations_ExpectedLifeMonthCount_A"
        assert box in _run({box: "12"}, "ACORD_126", _IDX, raw="Policy Number 12")[1]
        assert _run({box: "12"}, "ACORD_126", _IDX, raw="useful life of 12 months")[1] == {}


# ══ (c) a premium-line amount in a coverage-amount box ═══════════════════════

_WC_DED = "WorkersCompensation_DeductibleAmount_A"
_WC_RATING = (
    "CO 001 5190 State Act - Electrical Wiring 2,000,000 1.8800 37,600.00\n"
    "CO 9664 Small Deductible 6.5000 -2,495.00\n"
    "CO 0930 Waiver of Our Right to Recover from Others Endorsement-Blanket 0.0200 500.00\n"
    "CO | | 0930 | Waiver of Our Right to Recover from Others | | 0.0200 | 500.00\n"
)
_PACKAGE_DEC = (
    "CRIMEANDFIDELITY COVERAGEPART $ 500.00\n"
    "DEDUCTIBLE\n$500. Exceptions: SEE SCHEDULE\n"
    "CONTRACTORS ADVANTAGE COMMERCIAL PROPERTY COVERAGE FORM $500.00\n"
)
_ENTRIES = [
    {"label": "CRIMEANDFIDELITY COVERAGEPART", "value": "$ 500.00",
     "section": "COMMON POLICY DECLARATIONS", "line_of_business": "Crime"},
    {"label": "DEDUCTIBLE", "value": "$500. Exceptions: SEE SCHEDULE",
     "section": "COMMERCIAL PROPERTY COVERAGE PART DECLARATIONS PAGE",
     "line_of_business": "Property"},
]


class TestPremiumLineAmounts:
    def test_the_wc_rating_lines_premium_is_not_the_wc_deductible(self):
        m, out = _run({_WC_DED: "$500"}, "ACORD_130", {"dec_page_entries": _ENTRIES},
                      raw=_PACKAGE_DEC + _WC_RATING)
        assert m[_WC_DED] is None
        assert out[_WC_DED].startswith(rg.R_PREMIUM + ":")

    def test_a_wc_deductible_the_documents_state_keeps_it(self):
        raw = _PACKAGE_DEC + _WC_RATING + "Medical Deductible: $500 per claim\n"
        assert _run({_WC_DED: "$500"}, "ACORD_130", {"dec_page_entries": _ENTRIES}, raw=raw)[1] == {}

    def test_an_unplaced_non_premium_occurrence_keeps_it(self):
        # Without the entries placing the property line, "$500. Exceptions" is
        # an unexplained occurrence - the box keeps its value.
        assert _run({_WC_DED: "$500"}, "ACORD_130", {}, raw=_PACKAGE_DEC + _WC_RATING)[1] == {}

    def test_a_rate_is_the_misplaced_guards_and_the_credit_is_a_premium(self):
        box = "WorkersCompensation_DeductibleAmount_A"
        m, out = _run({box: "2,495"}, "ACORD_130", raw=_WC_RATING)
        assert out[box].startswith(rg.R_PREMIUM)

    def test_premium_wording_before_the_amount_on_its_line(self):
        raw = "Total Expiring Annual Premium: $86,400\n"
        m, out = _run({"OtherPolicy_CoverageLimitAmount_A": "$86,400"}, "ACORD_25", raw=raw)
        assert "OtherPolicy_CoverageLimitAmount_A" in out

    @pytest.mark.parametrize("raw", [
        "Total Premium for Limit of $1,000,000\n",          # the limit is named nearer
        "Each Occurrence $1,000,000 Premium Included\n",    # premium word after it
        "LIMIT 1,000,000 RATE .125 PREMIUM 1,250\n",        # not the line's last amount
        "Each Occurrence Limit $1,000,000\n",
    ])
    def test_a_limit_is_never_read_as_a_premium(self, raw):
        assert _run({"OtherPolicy_CoverageLimitAmount_A": "$1,000,000"}, "ACORD_25",
                    raw=raw)[1] == {}

    def test_an_amount_the_documents_never_print_is_not_this_rules(self):
        assert _run({_WC_DED: "$750"}, "ACORD_130", raw=_WC_RATING)[1] == {}

    def test_non_coverage_amount_boxes_are_out_of_scope(self):
        box = "WorkersCompensation_RateClass_EstimatedManualPremiumAmount_A"
        assert _run({box: "37,600"}, "ACORD_130", raw=_WC_RATING)[1] == {}


class TestPurgedIndex:
    """Production deletes `dec_page_entries` after generation
    (PURGE_DEC_INDEX_AFTER_GENERATION); a form stamped later (form_addition)
    runs without it. No rule may refuse MORE then - the registration in
    test_dec_index_purge.py rests on this."""

    def test_the_count_rule_stands_down_without_the_index(self):
        raw = "LOC 1 Prem. #: 001 Bldg #: 001"
        assert _FLOOR in _run({_FLOOR: "1"}, "ACORD_130", _IDX, raw=raw)[1]
        assert _run({_FLOOR: "1"}, "ACORD_130", {}, raw=raw)[1] == {}
        assert _run({_FLOOR: "1"}, "ACORD_130", {"dec_page_entries": None}, raw=raw)[1] == {}

    def test_a_count_only_the_index_witnessed_is_kept_both_sides_of_the_purge(self):
        entries = [{"label": "Number of Stories", "value": "3"}]
        assert _run({_FLOOR: "3"}, "ACORD_130", {"dec_page_entries": entries}, raw="LOC 3")[1] == {}
        assert _run({_FLOOR: "3"}, "ACORD_130", {}, raw="LOC 3")[1] == {}

    def test_the_premium_rule_keeps_the_box_without_the_index(self):
        raw = _PACKAGE_DEC + _WC_RATING
        assert _WC_DED in _run({_WC_DED: "$500"}, "ACORD_130", {"dec_page_entries": _ENTRIES}, raw=raw)[1]
        assert _run({_WC_DED: "$500"}, "ACORD_130", {}, raw=raw)[1] == {}


# ══ (e) a producer role the account does not state ═══════════════════════════

_PRODUCER = {"producer_name": "Example Agency", "producer_contact_name": "Pat Doe",
             "producer_contact_phone": "5551234567", "producer_contact_email": "pat@agency.test"}
_CSR = "Producer_CustomerServiceRepresentative_FullName_A"
_CELL = "Producer_ContactPerson_CellPhoneNumber_A"


class TestProducerRoles:
    def test_the_contacts_name_as_csr_and_phone_as_cell_are_refused(self):
        m, out = _run({_CSR: "Pat Doe", _CELL: "555-123-4567"}, "ACORD_130", _PRODUCER)
        assert m[_CSR] is None and m[_CELL] is None
        assert out[_CSR].startswith(rg.R_PRODUCER_ROLE) and out[_CELL].startswith(rg.R_PRODUCER_ROLE)

    def test_the_applicants_contact_is_refused_too(self):
        m, out = _run({_CSR: "Lee Roe"}, "ACORD_130", {"contact_name": "Lee Roe"})
        assert _CSR in out

    @pytest.mark.parametrize("raw", ["CSR: Pat Doe", "Customer Service Rep: Pat Doe",
                                     "Cell: (555) 123-4567 Pat Doe"])
    def test_the_documents_naming_the_role_keep_it(self, raw):
        m, out = _run({_CSR: "Pat Doe", _CELL: "(555) 123-4567"}, "ACORD_130", _PRODUCER, raw=raw)
        assert (_CSR in out) != ("CSR" in raw or "Customer" in raw)
        assert (_CELL in out) != ("Cell" in raw)

    def test_a_value_the_account_does_not_state_is_not_judged(self):
        assert _run({_CSR: "Sam Poe"}, "ACORD_130", _PRODUCER)[1] == {}

    def test_a_box_with_its_own_fact_is_another_rules(self):
        assert _run({"Producer_ContactPerson_FullName_A": "Example Agency"}, "ACORD_130",
                    _PRODUCER)[1] == {}

    def test_an_agency_name_as_a_customer_id_is_refused(self):
        assert "Producer_CustomerIdentifier_A" in _run(
            {"Producer_CustomerIdentifier_A": "Example Agency"}, "ACORD_130", _PRODUCER)[1]


# ══ (d) the binder date is an owned blank without a binder ═══════════════════

_BINDER = "Binder_EffectiveDate_A"


class TestBinderBox:
    def test_owned_blank_on_a_package_without_a_binder(self):
        facts = {"_package_doc_types": ["dec_page"], "effective_date": "01/01/2025"}
        assert ps._resolve_policy_status(_BINDER, facts) is None
        assert ps._is_authoritative_blank_field(_BINDER, facts)
        assert ps._deterministic_map(_BINDER, facts) is None
        # unknown document types are no binder either
        assert ps._resolve_policy_status(_BINDER, {}) is None

    def test_a_binder_document_hands_the_box_back(self):
        for facts in ({"_package_doc_types": ["dec_page", "binder"]}, {"_doc_type": "binder"}):
            assert ps._resolve_policy_status(_BINDER, facts) is ps._SCHED_SKIP
            assert not ps._is_authoritative_blank_field(_BINDER, facts)

    def test_the_model_is_never_asked_and_its_answer_never_prints(self):
        schema = _schema("ACORD_130")
        facts = {"_package_doc_types": ["dec_page"], "_form_id": "ACORD_130"}
        _mapped, unmatched, _det = ps.compute_form_gaps("ACORD_130", schema, facts)
        assert _BINDER not in unmatched
        m, _c = ps.map_facts_to_form(facts, schema, form_id="ACORD_130", raw_text="x",
                                     pre_filled_gpt={"filled_values": {_BINDER: "01/01/2025"},
                                                     "raw_text_fields": set(),
                                                     "question_grounding": {}},
                                     guard_report=[], allow_llm=False)
        assert not m.get(_BINDER)

    def test_only_binder_boxes(self):
        assert not rg.is_binder_box("Policy_Status_BoundIndicator_A")
        assert rg.is_binder_box(_BINDER)
        assert ps._resolve_policy_status("Policy_EffectiveDate_A", {}) is ps._SCHED_SKIP


# ══ the guard chain: one call, reasons recorded ═══════════════════════════════

def test_the_live_run_shapes_through_map_facts_to_form():
    """The four AI values of the live ACORD 130 go through the real guard chain
    and leave with their reason codes on the guard report."""
    schema = _schema("ACORD_130")
    facts = dict(_PRODUCER, construction_type="FRAME", dec_page_entries=copy.deepcopy(_ENTRIES),
                 _package_doc_types=["dec_page"], _form_id="ACORD_130")
    ai = {_FLOOR: "1", _WC_DED: "$500", _CSR: "Pat Doe", _CELL: "555-123-4567"}
    report = []
    m, _c = ps.map_facts_to_form(facts, schema, form_id="ACORD_130",
                                 raw_text=_PACKAGE_DEC + _WC_RATING + "LOC 1\n",
                                 pre_filled_gpt={"filled_values": dict(ai), "raw_text_fields": set(),
                                                 "question_grounding": {}},
                                 guard_report=report, allow_llm=False)
    for f in ai:
        assert not m.get(f), f
    reasons = {r["field"]: r.get("reason") for r in report}
    assert reasons.get(_FLOOR) == rg.R_COUNT
    assert reasons.get(_WC_DED) == rg.R_PREMIUM
    assert reasons.get(_CSR) == rg.R_PRODUCER_ROLE
    assert reasons.get(_CELL) == rg.R_PRODUCER_ROLE


def test_bad_input_never_raises():
    assert rg.drop_role_mismatches(None, None, None, None, None) == {}
    assert rg.drop_role_mismatches({"X_A": "1"}, {}, {}, "", {"X_A"}) == {}
    assert rg.drop_role_mismatches({"X_A": None}, None, "facts", 5, {"X_A", 3}) == {}


def test_frozen_forms_are_untouched():
    """ACORD 141 / 160 frozen (owner, 14 Sep 2026); the corpus replay showed the
    rules acting there ("ACV" as a 160 roof material, an entity type as a 141
    employee) - junk, but not this round's to change."""
    box = "Construction_RoofMaterialCode_A"
    for fid in ("ACORD_160", "ACORD_141"):
        sch = _schema(fid)
        if box not in sch:
            box2 = next(f for f in sch if f.endswith("_A") and sch[f].get("ft") == "/Tx")
        else:
            box2 = box
        assert rg.drop_role_mismatches({box2: "ACV"}, sch, {"valuation_method": "ACV"}, "",
                                       {box2}, fid) == {}


def test_reason_texts_carry_no_em_dash():
    m, out = _run({_FIRE_DESC: "FRAME"}, "ACORD_140", {"construction_type": "FRAME"})
    m2, out2 = _run({_CSR: "Pat Doe"}, "ACORD_130", _PRODUCER)
    for why in list(out.values()) + list(out2.values()):
        assert "—" not in why
