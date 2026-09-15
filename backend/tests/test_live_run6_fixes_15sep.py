"""Live run 6 (session 2748fcbf, 15 Sep 2026, Orbin policy only) - the seven
things still wrong after rounds 1 and 2, each driven with the LIVE values.

1. ACORD 126 hazard row 3 repeated row 1 - the extractor read the class rows a
   second time under "Location 000" (the policy-level heading) and a schedule
   that prints no territory could never de-duplicate. Also: LOC # was blank.
2. ACORD 126 "PROPERTY DAMAGE $1,000" - the pollution endorsement's deductible;
   its tick was refused but the orphan rule only knew three vehicle rows.
3. Guard 4 deleted real data: 127's garaging street (a PART of the applicant's
   own address) and 131's primary-row description (no owner, so both copies
   went). 131's primary NAME had no rule either.
4. ACORD 131 CARE, CUSTODY, CONTROL printed a lone LOC "1" - the generic
   location binding ran before the owned blank was asked.
5. Five one-line values clipped at the templates' fixed 8pt font.
6. ACORD 131 Q2 edition "04 13" vanished - the only witness was the dec index.
7. The cover-page "left blank on purpose" list repeated labels and listed
   copies of values the form already prints.
"""
import copy
import io
import json
import os
import re

import pikepdf
import pytest

import services.pdf_service as ps
import services.field_qa as fq
import services.extraction_service as es
from services.extraction_pipeline import _derive_gl_coverage_form_edition
from services.normalization import normalize_address

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _schema(form_id):
    with open(os.path.join(BACKEND, "forms_schemas", f"{form_id}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _gpt(values):
    return {"filled_values": values, "raw_text_fields": set(), "question_grounding": {}}


_OPS = ("Contractors - Executive Supervisors or Executive Superintendents; "
        "Contrctrs-sub work-in connection w/constrctn,recon,repr,erctn of buildings - NOC")
_LOCATION = {"address": "4800 DAHLIA STREET D13, DENVER CO. 80216-3121",
             "address_line1": "4800 DAHLIA ST", "address_line2": "# D13",
             "address_city": "DENVER", "address_state": "CO", "address_zip": "80216-3121",
             "location_id": "L1", "location_number": "1"}


def _row(loc, code, cls, basis, exposure):
    return {"location": loc, "class_code": code, "classification": cls,
            "premium_basis": basis, "exposure_amount": exposure,
            "territory": None, "subcontractor_pct": None}


_EXEC = "Contractors - Executive Supervisors or Executive Superintendents"
_SUB = "Contrctrs-sub work-in connection w/constrctn,recon,repr,erctn of buildings - NOC"
# Run 6's literal `gl_class_code_schedule` - the document prints 91580 once.
_LIVE_ROWS = [
    _row("Location 001", "91580", _EXEC, "Payroll", "$39,300"),
    _row("Location 001", "91585", _SUB, "Total Cost", "$350,000"),
    _row("Location 000", "91580", _EXEC, "Payroll", "$39,300"),
    _row("Location 000", "91585", _SUB, "Total Cost", "$350,000"),
]


# ═════════════════════════════════════════════════════════════════════════════
# 1. The GL hazard schedule
# ═════════════════════════════════════════════════════════════════════════════

def test_the_live_policy_level_copies_fold_into_their_rows():
    got = es._dedupe_schedule_rows("gl_class_code_schedule", copy.deepcopy(_LIVE_ROWS))
    assert [(r["location"], r["class_code"], r["exposure_amount"]) for r in got] == [
        ("Location 001", "91580", "$39,300"), ("Location 001", "91585", "$350,000")]


def test_order_does_not_decide_which_location_survives():
    """A location numbered zero is the carrier's policy-level bucket; a real
    premises number beats it whichever row the extractor listed first."""
    got = es._dedupe_schedule_rows("gl_class_code_schedule",
                                   copy.deepcopy(list(reversed(_LIVE_ROWS))))
    assert len(got) == 2
    assert {r["location"] for r in got} == {"Location 001"}


@pytest.mark.parametrize("single_partial", [True, False])
def test_both_merge_paths_dedupe(single_partial):
    """The single-chunk shortcut and the multi-chunk merge are two doors."""
    if single_partial:
        partials = [{"facts": {"gl_class_code_schedule": copy.deepcopy(_LIVE_ROWS)}, "flags": {}}]
    else:
        partials = [
            {"facts": {"gl_class_code_schedule": copy.deepcopy(_LIVE_ROWS[:2])}, "flags": {},
             "_chunk_idx": 0},
            {"facts": {"gl_class_code_schedule": copy.deepcopy(_LIVE_ROWS[2:])}, "flags": {},
             "_chunk_idx": 1},
        ]
    merged = es._merge_list_fields(partials, ["gl_class_code_schedule"])
    rows = merged["facts"]["gl_class_code_schedule"]
    assert len(rows) == 2, rows


def test_two_territories_sharing_a_figure_stay_two_rows():
    """The strong key is untouched: territory is what separates them."""
    rows = [dict(_row("001", "91580", _EXEC, "Payroll", "$39,300"), territory="004"),
            dict(_row("002", "91580", _EXEC, "Payroll", "$39,300"), territory="005")]
    assert len(es._dedupe_schedule_rows("gl_class_code_schedule", rows)) == 2


def test_a_copy_that_lost_its_territory_folds_into_the_one_row_it_repeats():
    rows = [dict(_row("001", "91580", _EXEC, "Payroll", "$39,300"), territory="004"),
            _row("002", "91580", _EXEC, "Payroll", "$39,300")]
    got = es._dedupe_schedule_rows("gl_class_code_schedule", rows)
    assert len(got) == 1 and got[0]["territory"] == "004" and got[0]["location"] == "001"


def test_a_territoryless_row_matching_two_territory_rows_is_never_guessed():
    rows = [dict(_row("001", "91580", _EXEC, "Payroll", "$39,300"), territory="004"),
            dict(_row("002", "91580", _EXEC, "Payroll", "$39,300"), territory="005"),
            _row("003", "91580", _EXEC, "Payroll", "$39,300")]
    assert len(es._dedupe_schedule_rows("gl_class_code_schedule", rows)) == 3


def test_a_different_premium_basis_is_never_the_same_row():
    rows = [_row("001", "91580", _EXEC, "Payroll", "$39,300"),
            _row("001", "91580", _EXEC, "Gross Sales", "$39,300")]
    assert len(es._dedupe_schedule_rows("gl_class_code_schedule", rows)) == 2


def test_an_exposure_with_no_figure_has_no_identity():
    rows = [_row("001", "91580", _EXEC, "Payroll", "If Any"),
            _row("002", "91580", _EXEC, "Payroll", "If Any")]
    assert len(es._dedupe_schedule_rows("gl_class_code_schedule", rows)) == 2


def test_the_extracted_rows_are_never_mutated():
    rows = copy.deepcopy(list(reversed(_LIVE_ROWS)))
    before = copy.deepcopy(rows)
    es._dedupe_schedule_rows("gl_class_code_schedule", rows)
    assert rows == before


def test_other_schedules_pass_through_the_weak_identity_untouched():
    rows = [{"name": "A"}, {"name": "A"}]
    assert es._merge_by_weak_identity("auto_drivers", [], rows) == rows


@pytest.mark.parametrize("label,facts,expected", [
    ("Location 001", {"property_locations": [_LOCATION]}, "1"),   # ACORD 125's printing
    ("Location 001", {}, "001"),                                  # the document's printing
    ("001", {}, "001"),
    ("Location 000", {"property_locations": [_LOCATION]}, None),  # policy-level bucket
    ("Loc #2", {}, "2"),
    ("Bldg 2 Loc 1", {}, "1"),
    ("Main Street", {}, "Main Street"),
    ("", {}, None),
])
def test_the_loc_number_is_read_out_of_the_label(label, facts, expected):
    assert ps._hazard_location_number(label, facts) == expected


def test_two_premises_printing_one_number_differently_is_not_a_cross_reference():
    facts = {"property_locations": [dict(_LOCATION), dict(_LOCATION, location_number="01")]}
    assert ps._hazard_location_number("Location 001", facts) == "001"


def test_the_126_grid_prints_loc_and_haz_and_owns_the_zero_location():
    facts = {"gl_class_code_schedule": copy.deepcopy(_LIVE_ROWS),
             "property_locations": [_LOCATION], "_form_id": "ACORD_126"}
    ps._set_schema_context(_schema("ACORD_126"))
    loc = lambda r: ps._deterministic_map(f"GeneralLiability_Hazard_LocationProducerIdentifier_{r}", facts)
    haz = lambda r: ps._deterministic_map(f"GeneralLiability_Hazard_HazardProducerIdentifier_{r}", facts)
    assert (loc("A"), loc("B")) == ("1", "1")
    assert (haz("A"), haz("B")) == ("1", "2")
    # row C is the undeduplicated "Location 000" copy: an OWNED blank, never asked
    assert loc("C") is None
    assert ps._is_authoritative_blank_field(
        "GeneralLiability_Hazard_LocationProducerIdentifier_C", facts)
    assert ps._resolve_phantom_gl_hazard_row(
        "GeneralLiability_Hazard_ClassCode_C", facts) is ps._SCHED_SKIP


# ═════════════════════════════════════════════════════════════════════════════
# 2. A deductible amount beside its own tick
# ═════════════════════════════════════════════════════════════════════════════

_EXPECTED_PAIRS = {
    "ACORD_126": {("GeneralLiability_PropertyDamage_DeductibleIndicator",
                   "GeneralLiability_PropertyDamage_DeductibleAmount"),
                  ("GeneralLiability_BodilyInjury_DeductibleIndicator",
                   "GeneralLiability_BodilyInjury_DeductibleAmount")},
    "ACORD_127": {("Vehicle_Coverage_CollisionIndicator", "Vehicle_Collision_DeductibleAmount")},
}
for _f in ("ACORD_137_CA", "ACORD_137_CO"):
    _EXPECTED_PAIRS[_f] = {
        ("Vehicle_Coverage_ComprehensiveDeductibleIndicator", "Vehicle_Comprehensive_DeductibleAmount"),
        ("Vehicle_Coverage_SpecifiedCauseOfLossDeductibleIndicator",
         "Vehicle_SpecifiedCauseOfLoss_DeductibleAmount"),
        ("Vehicle_Coverage_CollisionIndicator", "Vehicle_Collision_DeductibleAmount"),
    }


def test_the_derived_pairs_over_all_17_schemas():
    """ANTI-ROT. The pairs are derived from the schemas; a schema change that
    adds or loses a pair must be looked at, not absorbed silently."""
    got = {}
    for fn in sorted(os.listdir(os.path.join(BACKEND, "forms_schemas"))):
        if not fn.endswith("_schema.json"):
            continue
        fid = fn[:-len("_schema.json")]
        pairs = {(re.sub(r"_[A-Z]$", "", t), re.sub(r"_[A-Z]$", "", a))
                 for t, a in ps._deductible_tick_amount_pairs(_schema(fid))}
        if pairs:
            got[fid] = pairs
    assert got == _EXPECTED_PAIRS


def test_an_other_row_is_governed_by_its_description_not_its_tick():
    pairs = ps._deductible_tick_amount_pairs(_schema("ACORD_126"))
    assert not [p for p in pairs if "Other" in p[0]]


_POLLUTION_TEXT = ("CG 72 76 11 16 Limited Pollution Coverage - Work Sites; Each Pollution "
                   "Incident Limit - $1,000,000; Pollution Liability Aggregate Limit - "
                   "$1,000,000; Property Damage Deductible $1,000 Each Pollution Incidents")


def test_the_pollution_deductible_leaves_the_property_damage_row():
    """The live shape: both ticks refused (no grounding), the endorsement's
    $1,000 on the PD row and, correctly labelled, on the OTHER row."""
    schema = _schema("ACORD_126")
    mapped, _c = ps.map_facts_to_form({}, schema, "ACORD_126", raw_text=_POLLUTION_TEXT,
                                      pre_filled_gpt=_gpt({
        "GeneralLiability_PropertyDamage_DeductibleIndicator_A": "Yes",
        "GeneralLiability_PropertyDamage_DeductibleAmount_A": "1,000",
        "GeneralLiability_OtherDeductibleIndicator_A": "Yes",
        "GeneralLiability_OtherDeductibleDescription_A": "Limited Pollution Coverage - Work Sites",
        "GeneralLiability_OtherDeductibleAmount_A": "1,000",
    }))
    assert not mapped.get("GeneralLiability_PropertyDamage_DeductibleAmount_A")
    assert mapped.get("GeneralLiability_OtherDeductibleDescription_A") == \
        "Limited Pollution Coverage - Work Sites"
    assert mapped.get("GeneralLiability_OtherDeductibleAmount_A") == "1,000"


def test_a_ticked_row_keeps_its_amount_and_a_stated_amount_is_never_touched():
    schema = _schema("ACORD_126")
    amt = "GeneralLiability_PropertyDamage_DeductibleAmount_A"
    tick = "GeneralLiability_PropertyDamage_DeductibleIndicator_A"
    assert ps._orphaned_deductible_amounts({amt: "1,000", tick: "Yes"}, schema, {amt}) == []
    assert ps._orphaned_deductible_amounts({amt: "1,000"}, schema, set()) == []
    assert ps._orphaned_deductible_amounts({amt: "1,000"}, schema, {amt}) == [(amt, tick)]


# ═════════════════════════════════════════════════════════════════════════════
# 3. Guard 4 must not delete the applicant's own data
# ═════════════════════════════════════════════════════════════════════════════

def _own(*texts):
    return [normalize_address(t).split() for t in texts]


@pytest.mark.parametrize("text,own", [
    ("4800 DAHLIA STREET D13", True),                  # the live garaging street
    ("4800 Dahlia St # D13 Denver", True),
    ("DENVER CO 80216-3121", True),                    # city / state / ZIP run
    ("4800 DAHLIA ST # D13, DENVER CO 80216-3121", True),
    ("Mail notices to 4800 Dahlia St # D13", False),   # boilerplate around it
    ("Denver CO", False),                              # too short, no number
    ("4800 Dahlia Denver", False),                     # not contiguous
])
def test_a_part_of_the_applicants_address_is_its_address(text, own):
    tokens = _own("4800 DAHLIA ST # D13, DENVER CO 80216-3121")
    assert ps._is_own_address_text(normalize_address(text), tokens) is own


def test_premises_and_garaging_addresses_count_as_own():
    texts = ps._own_address_texts({
        "property_locations": [_LOCATION],
        "auto_garaging_addresses": ["100 Yard Rd, Denver CO 80216", {"address": "7 Lot Ln"}],
    })
    assert "4800 DAHLIA STREET D13, DENVER CO. 80216-3121" in texts
    assert "4800 DAHLIA ST # D13 DENVER CO 80216-3121" in texts
    assert "100 Yard Rd, Denver CO 80216" in texts and "7 Lot Ln" in texts


_VEHICLE = [{"year": "2012", "make": "Subaru", "model": "Outback", "vin": "4S4BRCGC9C3217772"}]


def test_the_live_garaging_street_survives_in_both_boxes():
    """Run 5 AND run 6: the model wrote the insured's own street as the
    garaging street and as the garage description; Guard 4 deleted both."""
    facts = {"property_locations": [_LOCATION], "auto_vin_schedule": _VEHICLE,
             "mailing_address": "4800 DAHLIA ST # D13, DENVER CO 80216-3121"}
    raw = "GARAGE LOCATION 4800 DAHLIA STREET D13 DENVER CO. 80216-3121 2012 SUBARU OUTBACK"
    mapped, _c = ps.map_facts_to_form(facts, _schema("ACORD_127"), "ACORD_127", raw_text=raw,
                                      pre_filled_gpt=_gpt({
        "Vehicle_PhysicalAddress_LineOne_A": "4800 DAHLIA STREET D13",
        "CommercialVehicleLineOfBusiness_GarageStorageDescription_A": "4800 DAHLIA STREET D13",
    }))
    assert mapped.get("Vehicle_PhysicalAddress_LineOne_A")
    assert mapped.get("CommercialVehicleLineOfBusiness_GarageStorageDescription_A")


def test_boilerplate_that_mentions_the_address_is_still_bleed():
    sentence = "Mail all notices to 4800 Dahlia St # D13 Denver CO by first class mail"
    facts = {"property_locations": [_LOCATION],
             "mailing_address": "4800 DAHLIA ST # D13, DENVER CO 80216-3121"}
    mapped = {"CommercialPolicy_OperationsDescription_B": sentence,
              "AdditionalInterest_ItemDescription_A": sentence}
    ps._enforce_post_fill_guards(mapped, _schema("ACORD_125"), facts)
    assert mapped["CommercialPolicy_OperationsDescription_B"] is None
    assert mapped["AdditionalInterest_ItemDescription_A"] is None


_131_FACTS = {"applicant_name": "ORBIN CONTRACTING LLC", "operations_description": _OPS,
              "property_locations": [_LOCATION]}


def test_131_primary_row_is_the_applicant_and_subsidiaries_are_not():
    facts = {**_131_FACTS, "_form_id": "ACORD_131"}
    ps._set_schema_context(_schema("ACORD_131"))
    assert ps._deterministic_map("BusinessInformation_OperationsDescription_A", facts) == _OPS
    assert ps._deterministic_map("CommercialStructure_Location_FullName_A", facts) == \
        "ORBIN CONTRACTING LLC"
    for r in "BCDEF":
        assert ps._deterministic_map(f"BusinessInformation_OperationsDescription_{r}", facts) != _OPS
        assert ps._deterministic_map(f"CommercialStructure_Location_FullName_{r}", facts) != \
            "ORBIN CONTRACTING LLC"


def test_160_first_premises_gets_the_description_and_the_second_does_not():
    facts = {**_131_FACTS, "_form_id": "ACORD_160"}
    ps._set_schema_context(_schema("ACORD_160"))
    assert ps._deterministic_map("BusinessInformation_OperationsDescription_A", facts) == _OPS
    assert ps._deterministic_map("BusinessInformation_OperationsDescription_B", facts) != _OPS


def test_the_name_rule_does_not_reach_133s_payroll_records_box():
    assert ps._first_rule_fact("Location_FullName_A") != "applicant_name"


def test_131_no_longer_asks_the_model_for_its_own_primary_row():
    _m, unmatched, _d = ps.compute_form_gaps("ACORD_131", _schema("ACORD_131"), _131_FACTS)
    assert "BusinessInformation_OperationsDescription_A" not in unmatched
    assert "CommercialStructure_Location_FullName_A" not in unmatched


def test_the_description_keeps_its_owner_and_the_q11_copy_goes():
    """The live Guard 4 case: the same sentence in the description and in Q11.
    The fact owns the description; the Q11 copy is the bleed."""
    mapped, _c = ps.map_facts_to_form(_131_FACTS, _schema("ACORD_131"), "ACORD_131",
                                      raw_text=_OPS, pre_filled_gpt=_gpt({
        "BusinessInformation_OperationsDescription_A": _OPS,
        "Contractors_WorkContractedDescription_A": _OPS,
    }))
    assert mapped.get("BusinessInformation_OperationsDescription_A") == _OPS
    assert mapped.get("CommercialStructure_Location_FullName_A")
    assert not mapped.get("Contractors_WorkContractedDescription_A")


# ═════════════════════════════════════════════════════════════════════════════
# 4. An owned blank wins at the non-fillable schedule door
# ═════════════════════════════════════════════════════════════════════════════

_CCC_LOC = "CareCustodyAndControl_Location_ProducerIdentifier_A"


def test_131_care_custody_loc_is_blank_on_both_paths():
    schema = _schema("ACORD_131")
    gm, _u, _d = ps.compute_form_gaps("ACORD_131", schema, _131_FACTS)
    mm, _c = ps.map_facts_to_form(_131_FACTS, schema, "ACORD_131", raw_text="ORBIN",
                                  pre_filled_gpt=_gpt({}))
    assert not gm.get(_CCC_LOC) and not mm.get(_CCC_LOC)
    assert gm.get("CommercialStructure_Location_ProducerIdentifier_A") == "1"
    assert mm.get("CommercialStructure_Location_ProducerIdentifier_A") == "1"


def test_the_door_change_reaches_only_the_care_custody_column():
    """BLAST RADIUS, over all 17 schemas: every non-fillable box a schedule
    value reaches is checked, and the owned blank now wins on exactly one."""
    facts = {"property_locations": [dict(_LOCATION), dict(_LOCATION, location_number="2")],
             "wc_class_codes": [{"code": "8810", "rate": "0.25", "location": "1",
                                 "state": "CO", "payroll": "100000"}],
             "wc_officers": [{"name": "Ann Bee", "location": "1"}]}
    blocked = []
    for fn in sorted(os.listdir(os.path.join(BACKEND, "forms_schemas"))):
        if not fn.endswith("_schema.json"):
            continue
        fid = fn[:-len("_schema.json")]
        schema = _schema(fid)
        ps._set_schema_context(schema)
        f = {**facts, "_form_id": fid}
        for field in schema:
            if not ps._is_nonfillable_field(field):
                continue
            bound = ps._resolve_schedule_row(field, f)
            if bound is ps._SCHED_SKIP or bound is None or ps._is_empty_llm_value(bound):
                continue
            if ps._owned_blank_claim(field, f):
                blocked.append(f"{fid}:{field}")
    assert blocked == [f"ACORD_131:{_CCC_LOC}"]


def test_a_resolver_that_owns_a_box_with_a_value_is_not_a_blank_claim():
    facts = {"gl_coverage_form_edition": {"value": "04 13", "source": "policy_doc_text"}}
    field = "UnderlyingPolicy_GeneralLiability_FormEditionDate_A"
    assert ps._is_authoritative_blank_field(field, facts)
    assert not ps._owned_blank_claim(field, facts)


# ═════════════════════════════════════════════════════════════════════════════
# 5. A one-line value fits its box
# ═════════════════════════════════════════════════════════════════════════════

def _filled_fields(form_id, data):
    """Plain snapshots (name, DA, width, value) read back from the real
    generated PDF - the Pdf object is closed before the caller looks."""
    def snap(f):
        widget = f
        if f.get("/Rect") is None:           # a parent field: its widget is a kid
            kids = [k for k in (f.get("/Kids") or []) if k.get("/Rect") is not None]
            widget = kids[0] if kids else None
        rect = widget.get("/Rect") if widget is not None else None
        da = (widget.get("/DA") if widget is not None else None) or f.get("/DA")
        return {"name": str(f.get("/T")), "da": str(da),
                "width": abs(float(rect[2]) - float(rect[0])) if rect is not None else 0.0,
                "value": str(f.get("/V") or "")}

    with pikepdf.open(io.BytesIO(ps.fill_pdf(
            os.path.join(BACKEND, "templates", f"{form_id}.pdf"), data, {}))) as pdf:
        return {str(f.get("/T")): snap(f)
                for f in pdf.Root.AcroForm.Fields if f.get("/T") is not None}


def _size(field):
    da = field["da"] if isinstance(field, dict) else str(field.get("/DA"))
    return float(re.search(r"(\d+(?:\.\d+)?)\s+Tf", da).group(1))


def _fits(field):
    from reportlab.pdfbase.pdfmetrics import stringWidth
    width = field["width"] - 2 * ps._FIT_SIDE_PAD_PT
    return stringWidth(" ".join(field["value"].split()), "Helvetica", _size(field)) <= width


def test_the_five_live_clipped_values_now_fit():
    f125 = _filled_fields("ACORD_125", {"Policy_Audit_FrequencyCode_A": "Annual",
                                        "BuildingOccupancy_OperationsDescription_A": _OPS})
    f126 = _filled_fields("ACORD_126", {
        "GeneralLiability_OtherDeductibleDescription_A": "Limited Pollution Coverage - Work Sites"})
    f131 = _filled_fields("ACORD_131", {
        "CommercialStructure_PhysicalAddress_PostalCode_A": "80216-3121",
        "UnderlyingPolicy_Automobile_InsurerFullName_A": "EMPLOYERS MUTUAL CASUALTY COMPANY",
        "BusinessInformation_OperationsDescription_A": _OPS})
    for field in (f125["Policy_Audit_FrequencyCode_A"],
                  f125["BuildingOccupancy_OperationsDescription_A"],
                  f126["GeneralLiability_OtherDeductibleDescription_A"],
                  f131["CommercialStructure_PhysicalAddress_PostalCode_A"],
                  f131["UnderlyingPolicy_Automobile_InsurerFullName_A"],
                  f131["BusinessInformation_OperationsDescription_A"]):
        assert _size(field) < 8 and _fits(field), (field["name"], _size(field))


def test_a_value_that_fits_and_a_multiline_box_keep_their_size():
    f = _filled_fields("ACORD_125", {"NamedInsured_FullName_A": "Orbin Contracting LLC",
                                     "CommercialPolicy_OperationsDescription_A": _OPS * 3})
    assert _size(f["NamedInsured_FullName_A"]) == 8
    assert _size(f["CommercialPolicy_OperationsDescription_A"]) == 8   # multi-line wraps


def test_the_floor_holds_for_a_value_that_can_never_fit():
    f = _filled_fields("ACORD_125", {"Policy_Audit_FrequencyCode_A": "A" * 300})
    assert _size(f["Policy_Audit_FrequencyCode_A"]) == ps._FIT_MIN_FONT_PT


def test_auto_size_and_comb_boxes_are_left_alone():
    auto = pikepdf.Dictionary(Rect=[0, 0, 20, 10], DA=pikepdf.String("/F2 0 Tf 0 g"))
    ps._fit_text_to_box(auto, "a much longer value than the box")
    assert str(auto.DA) == "/F2 0 Tf 0 g"
    comb = pikepdf.Dictionary(Rect=[0, 0, 20, 10], DA=pikepdf.String("/F2 8 Tf 0 g"), Ff=1 << 24)
    ps._fit_text_to_box(comb, "a much longer value than the box")
    assert str(comb.DA) == "/F2 8 Tf 0 g"


def test_a_widget_kid_gets_the_smaller_size():
    kid = pikepdf.Dictionary(Rect=[0, 0, 20, 10])
    field = pikepdf.Dictionary(DA=pikepdf.String("/F2 8 Tf 0 g"), Kids=pikepdf.Array([kid]))
    ps._fit_text_to_box(field, "Annual value")
    assert _size(field.Kids[0]) < 8


# ═════════════════════════════════════════════════════════════════════════════
# 6. The CGL coverage-form edition
# ═════════════════════════════════════════════════════════════════════════════

_FORMS_PAGE = ("Endorsement Schedule\nCG 00 01 04 13 Commercial General Liability Coverage Form\n"
               "CG 00 69 12 23 Exclusion - Violation of Law\n"
               "CG 21 47 12 07 Employment-Related Practices Exclusion\n")
_FORM_FOOTER = "CG 00 01 04 13 © Insurance Services Office, Inc.,2012 Page 1of 16\n"


@pytest.mark.parametrize("text,expected", [
    (_FORMS_PAGE + _FORM_FOOTER * 3, "04 13"),              # the live shape
    (_FORMS_PAGE + "CG 00 01 12 07 Commercial General Liability", None),   # two editions
    ("CG 00 69 12 23 Exclusion\nCG 21 47 12 07 Exclusion", None),         # endorsements only
    ("CG 00 01 (04-13)", "04 13"),
    ("CG 00 01 04/13", "04 13"),
    ("CG0001 0413", "04 13"),
    ("CG 00 02 04 13 Claims-Made Coverage Form", "04 13"),  # claims-made base form
    ("CG 00 01 2013", None),                                 # a year is not an edition
    ("", None),
])
def test_the_edition_is_read_off_the_document(text, expected):
    assert ps.cgl_coverage_form_edition_in_text(text) == expected


@pytest.mark.parametrize("value,expected", [
    ("04 13", "04 13"), ("04/13", "04 13"), ("4/13", "04 13"), ("0413", "04 13"),
    ("CG 00 01 04 13", "04 13"), ("13/04", None), ("next year", None), ("", None),
])
def test_a_stored_edition_is_read_in_any_spelling(value, expected):
    assert ps._edition_from_fact(value) == expected


_EDITION = "UnderlyingPolicy_GeneralLiability_FormEditionDate_A"
_GL_ENTRY = {"label": "Coverage Form", "value": "CG 00 01 04 13",
             "line_of_business": "General Liability"}
_AUTO_ENTRY = {"label": "Form", "value": "CA 00 01 11 20", "line_of_business": "Commercial Auto"}


def test_the_resolver_reads_both_witnesses():
    fact = {"value": "04 13", "source": "policy_doc_text"}
    assert ps._resolve_underlying_gl_form_edition(_EDITION, {"gl_coverage_form_edition": fact}) == "04 13"
    assert ps._resolve_underlying_gl_form_edition(   # run 6: dec index silent, text speaks
        _EDITION, {"gl_coverage_form_edition": fact, "dec_page_entries": [_AUTO_ENTRY]}) == "04 13"
    assert ps._resolve_underlying_gl_form_edition(   # both agree
        _EDITION, {"gl_coverage_form_edition": fact, "dec_page_entries": [_GL_ENTRY]}) == "04 13"
    disagree = dict(_GL_ENTRY, value="CG 00 01 12 07")
    assert ps._resolve_underlying_gl_form_edition(   # disagree: ambiguous
        _EDITION, {"gl_coverage_form_edition": fact, "dec_page_entries": [disagree]}) is None
    assert ps._resolve_underlying_gl_form_edition(_EDITION, {}) is ps._SCHED_SKIP


def test_the_pipeline_writes_the_edition_from_active_documents_only():
    facts = {}
    docs = [{"text": _FORMS_PAGE + _FORM_FOOTER},
            {"text": "CG 00 01 12 07 prior term policy", "excluded": True}]
    assert _derive_gl_coverage_form_edition(facts, docs) == "04 13"
    assert facts["gl_coverage_form_edition"] == {
        "value": "04 13", "confidence": "filled", "source": "policy_doc_text"}


def test_the_pipeline_never_overwrites_a_human_edition():
    facts = {"gl_coverage_form_edition": {"value": "12 07", "source": "producer"}}
    assert _derive_gl_coverage_form_edition(facts, [{"text": _FORM_FOOTER}]) is None
    assert facts["gl_coverage_form_edition"]["value"] == "12 07"


def test_ambiguous_documents_write_no_edition():
    facts = {"gl_coverage_form_edition": {"value": "04 13", "source": "policy_doc_text"}}
    docs = [{"text": _FORM_FOOTER}, {"text": "CG 00 01 12 07 prior term policy"}]
    assert _derive_gl_coverage_form_edition(facts, docs) is None
    assert "gl_coverage_form_edition" not in facts


def test_the_pipeline_calls_the_derivation():
    src = open(os.path.join(BACKEND, "services", "extraction_pipeline.py"), encoding="utf-8").read()
    body = src[src.index("async def _finalize_pipeline("):]
    assert "_derive_gl_coverage_form_edition(merged_facts, active_docs)" in body


# ═════════════════════════════════════════════════════════════════════════════
# 7. The "left blank on purpose" list
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("removed,printed,copy_", [
    ("DENVER", "Denver", True),
    ("CO", "CO", True),
    ("Employers Mutual Casualty Company", "EMPLOYERS MUTUAL CASUALTY COMPANY", True),
    ("Contrctrs-sub work-in connection w/constrctn", _OPS, True),     # contained, long
    ("# D13", "# D13", True),
    ("1", "1", False),                   # a short number is a coincidence
    ("No", "No", False),                 # tick vocabulary
    ("work", "Contractors work", False),  # short containment is not a copy
    ("238990", "Orbin Contracting LLC", False),
])
def test_a_printed_copy_is_recognised(removed, printed, copy_):
    keys = fq._printed_value_keys({"mapped": {"Other_Box_A": printed}})
    assert fq._is_printed_copy(removed, "Refused_Box_A", keys) is copy_


# Run 6's ACORD 125 list, literally: 32 refusals, 20 of them copies of the first
# named insured into the other-named-insured rows or of the carrier's name.
_LIVE_125_REFUSED = [
    ("AdditionalInterest_FullName_A", "EMC Property & Casualty Company"),
    ("AdditionalInterest_FullName_B", "Employers Mutual Casualty Company"),
    ("CommercialPolicy_OperationsDescription_B", _SUB),
    ("CommercialStructure_InstallationRepairWorkOffPremisesPercent_A", "100%"),
    ("CommercialStructure_InstallationRepairWorkPercent_A", "100%"),
    ("NamedInsured_BusinessStartDate_A", "07/15/25"),
] + [(f"NamedInsured_GeneralLiabilityCode_{r}", "91580") for r in "ABC"] + [
    (f"NamedInsured_MailingAddress_{box}_{r}", val)
    for r in "BC" for box, val in (("CityName", "DENVER"), ("LineOne", "4800 DAHLIA ST"),
                                   ("LineTwo", "# D13"), ("PostalCode", "80216-3121"),
                                   ("StateOrProvinceCode", "CO"))
] + [(f"NamedInsured_NAICSCode_{r}", "238990") for r in "ABC"] \
  + [(f"NamedInsured_Primary_PhoneNumber_{r}", "303-996-7800") for r in "ABC"] \
  + [(f"NamedInsured_SICCode_{r}", "1799") for r in "ABC"] \
  + [(f"NamedInsured_TaxIdentifier_{r}", "ORBIN CONTRACTING LLC") for r in "ABC"] \
  + [("Subsidiary_OrganizationName_A", "ORBIN CONTRACTING LLC")]
_LIVE_125_PRINTED = {
    "NamedInsured_FullName_A": "Orbin Contracting LLC",
    "NamedInsured_MailingAddress_CityName_A": "Denver",
    "NamedInsured_MailingAddress_LineOne_A": "4800 Dahlia St",
    "NamedInsured_MailingAddress_LineTwo_A": "# D13",
    "NamedInsured_MailingAddress_PostalCode_A": "80216-3121",
    "NamedInsured_MailingAddress_StateOrProvinceCode_A": "CO",
    "Insurer_FullName_A": "EMPLOYERS MUTUAL CASUALTY COMPANY",
    "CommercialPolicy_OperationsDescription_A": _OPS,
}


def test_the_live_125_list_names_only_what_the_form_does_not_already_print():
    assert len(_LIVE_125_REFUSED) == 32
    blanks = [{"form_id": "ACORD_125", "field": f, "removed_value": v}
              for f, v in _LIVE_125_REFUSED]
    qa = fq.run_field_qa({"ACORD_125": {"mapped": dict(_LIVE_125_PRINTED), "confidence": {},
                                        "schema": {}, "guard_blanks": blanks}},
                         merged_facts={}, confirmations={})
    listed = {r["field"] for r in qa["results"] if r["reason_code"] == "guard_removed_value"}
    assert len(listed) == 16
    assert "NamedInsured_MailingAddress_CityName_B" not in listed
    assert "NamedInsured_TaxIdentifier_A" not in listed
    assert "AdditionalInterest_FullName_B" not in listed           # the printed carrier
    assert "AdditionalInterest_FullName_A" in listed                # EMC P&C is not printed
    assert "NamedInsured_NAICSCode_A" in listed
    msg = [r["message"] for r in fq.to_recommendation_rows(qa)
           if "left blank on purpose" in (r["message"] or "")][0]
    assert "16 fields" in msg and "+5 more" in msg                  # 8 distinct boxes
    assert len(blanks) == 32                                        # arq's list is untouched


def test_a_repeated_box_is_listed_once_with_its_count():
    blanks = [{"form_id": "ACORD_126", "field": f"AdditionalInterest_FullName_{r}",
               "removed_value": "COMMERCIAL RISK SOLUTIONS, INC."} for r in "ABC"]
    qa = fq.run_field_qa({"ACORD_126": {"mapped": {}, "confidence": {}, "schema": {},
                                        "guard_blanks": blanks}},
                         merged_facts={}, confirmations={})
    msg = [r["message"] for r in fq.to_recommendation_rows(qa)
           if "left blank on purpose" in (r["message"] or "")][0]
    assert "3 fields" in msg and "AdditionalInterest FullName (x3)" in msg
    assert msg.count("AdditionalInterest FullName") == 1
