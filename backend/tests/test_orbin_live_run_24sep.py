"""Owner's live run of orbin_retest_kit (24 Sep 2026, session ed46dede).

The run passed the client's 11 items and found ten more wrong values on the
generated forms. Every test here reads the LIVE values from
`tests/fixtures/orbin_live_24sep.json` - what the forms printed and the
evidence (declarations index, document text, extracted facts) the fixes read -
and each fix is also pinned in the other direction, so it cannot overreach.

Offline: no database, no LLM.
"""
import copy
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import services.extraction_service as es                     # noqa: E402
import services.pdf_service as ps                            # noqa: E402
from services import auto_symbols as sym                     # noqa: E402

BACKEND = os.path.join(os.path.dirname(__file__), "..")
with open(os.path.join(os.path.dirname(__file__), "fixtures", "orbin_live_24sep.json"),
          encoding="utf-8") as _fh:
    LIVE = json.load(_fh)
MF = LIVE["merged_facts"]
STORED = LIVE["stored"]
TEXT = LIVE["text"]


def _schema(form_id):
    with open(os.path.join(BACKEND, "forms_schemas", f"{form_id}_schema.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def _v(raw):
    return raw.get("value") if isinstance(raw, dict) and "value" in raw else raw


def _facts(**extra):
    f = copy.deepcopy(MF)
    f.update(LIVE["flags"])
    f["dec_page_entries"] = copy.deepcopy(LIVE["dec_page_entries"])
    f.update(extra)
    return f


def _before(form_id, field):
    return (STORED[form_id].get(field) or {}).get("value")


# =============================================================================
# 1. The old broker's AGENT NO. printed as ACORD 186's contractor licence
# =============================================================================
class TestProducerIdentifiers:

    def test_the_live_run_printed_the_agent_number(self):
        assert _before("ACORD_186", "ContractorsUnderwriting_LicenseNumberIdentifier_A") == "W6258-0001"

    def test_every_identifier_of_the_old_broker_is_recognised(self):
        own, foreign = ps._producer_identifiers(_facts())
        for ident in [("code", "W6258 0001"), ("code", "AW 6258"), ("code", "W6258"),
                      ("phone", "3039967800"), ("phone", "3037577719"),
                      ("email", "twroblewski@crsdenver.com")]:
            assert ident in foreign, ident
        assert ("email", "vinaysharma@astreait.com") in own

    def test_the_licence_box_is_blanked(self):
        mapped = {"ContractorsUnderwriting_LicenseNumberIdentifier_A": "W6258-0001",
                  "Policy_PolicyNumberIdentifier_A": "BBC7263-26",
                  "GeneralLiability_Hazard_ClassCode_A": "91580"}
        cleared = ps._blank_producer_identifiers(mapped, _facts())
        assert cleared == ["ContractorsUnderwriting_LicenseNumberIdentifier_A"]
        assert mapped["Policy_PolicyNumberIdentifier_A"] == "BBC7263-26"
        assert mapped["GeneralLiability_Hazard_ClassCode_A"] == "91580"

    @pytest.mark.parametrize("value", ["AW 6258", "W6258", "(303) 996-7800", "303-996-7800",
                                       "twroblewski@crsdenver.com", "W6258-0001 (CO)"])
    def test_every_printing_is_refused_outside_the_block(self, value):
        mapped = {"NamedInsured_Primary_PhoneNumber_A": value}
        ps._blank_producer_identifiers(mapped, _facts())
        assert mapped["NamedInsured_Primary_PhoneNumber_A"] is None

    def test_the_new_producers_own_email_stays_in_its_block_only(self):
        mapped = {"Producer_ContactPerson_EmailAddress_A": "vinaysharma@astreait.com",
                  "NamedInsured_Primary_EmailAddress_A": "vinaysharma@astreait.com"}
        ps._blank_producer_identifiers(mapped, _facts())
        assert mapped["Producer_ContactPerson_EmailAddress_A"] == "vinaysharma@astreait.com"
        assert mapped["NamedInsured_Primary_EmailAddress_A"] is None

    @pytest.mark.parametrize("box", ["Producer_StateLicenseIdentifier_A", "Insurer_ProducerIdentifier_A",
                                     "Insurer_SubProducerIdentifier_A"])
    def test_another_agencys_code_is_refused_even_in_the_producer_block(self, box):
        mapped = {box: "W6258-0001"}
        ps._blank_producer_identifiers(mapped, _facts())
        assert mapped[box] is None

    @pytest.mark.parametrize("box", ["Producer_StateLicenseIdentifier_A", "Insurer_ProducerIdentifier_A"])
    def test_an_incumbent_keeps_its_own_code_in_its_own_block(self, box):
        """No expiring producer recorded: the documents' agency IS the
        submitting one, and ACORD 125's CODE box (named Insurer_ProducerIdentifier)
        legitimately holds its code."""
        facts = _facts()
        for k in list(facts):
            if k.startswith("expiring_producer_"):
                facts.pop(k)
        mapped = {box: "W6258-0001", "ContractorsUnderwriting_LicenseNumberIdentifier_A": "W6258-0001"}
        ps._blank_producer_identifiers(mapped, facts)
        assert mapped[box] == "W6258-0001"
        assert mapped["ContractorsUnderwriting_LicenseNumberIdentifier_A"] is None

    def test_the_125_code_boxes_are_the_producers_by_acords_own_definition(self):
        s = _schema("ACORD_125")
        assert "assigned to the producer" in s["Insurer_ProducerIdentifier_A"]["tu"].lower()

    @pytest.mark.parametrize("value", ["9780 S MERIDIAN BLVD STE 400 ENGLEWOOD, CO 80112-6072",
                                       "Denver", "80216", "CO", "COMMERCIAL RISK SOLUTIONS, INC."])
    def test_addresses_cities_zips_and_names_are_never_identifiers(self, value):
        assert ps._identifier_shape(value) is None


# =============================================================================
# 2. ACORD 186's "minimum GL limits required of subcontractors"
# =============================================================================
class TestMinimumLimitBoxes:
    BOXES = ["GeneralLiability_EachOccurrence_LimitAmount_A", "GeneralLiability_GeneralAggregate_LimitAmount_A"]

    def test_the_live_run_printed_orbins_own_limits(self):
        assert [_before("ACORD_186", b) for b in self.BOXES] == ["1,000,000", "2,000,000"]

    @pytest.mark.parametrize("box", BOXES)
    def test_the_186_minimum_boxes_are_owned_blanks(self, box):
        facts = {"_form_id": "ACORD_186", "gl_each_occurrence": {"value": "$1,000,000"},
                 "gl_aggregate": {"value": "$2,000,000"}}
        assert ps._deterministic_map(box, facts) is None
        assert ps._is_authoritative_blank_field(box, facts)
        assert "this is the minimum limit" in _schema("ACORD_186")[box]["tu"].lower()

    @pytest.mark.parametrize("form_id", ["ACORD_126", "ACORD_131"])
    def test_the_applicants_own_limit_still_prints_on_its_own_forms(self, form_id):
        facts = {"_form_id": form_id, "gl_each_occurrence": {"value": "$1,000,000"}}
        assert ps._deterministic_map("GeneralLiability_EachOccurrence_LimitAmount_A", facts) == "$1,000,000"


# =============================================================================
# 3. ACORD 127: $100,000 stated amount (the hired-auto limit) beside ACV
# =============================================================================
class TestStatedAmount:

    def test_the_live_run_printed_it_beside_acv(self):
        assert _before("ACORD_127", "Vehicle_Coverage_AgreedOrStatedAmount_A") == "100,000"
        assert _before("ACORD_127", "Vehicle_Coverage_ValuationActualCashValueIndicator_A") in ("Yes", "Y", "1")

    def test_acv_blanks_the_amount(self):
        mapped = {"Vehicle_Coverage_AgreedOrStatedAmount_A": "100,000",
                  "Vehicle_Coverage_ValuationActualCashValueIndicator_A": "Yes"}
        assert ps._blank_unexplained_stated_amount(mapped) == ["Vehicle_Coverage_AgreedOrStatedAmount_A"]

    @pytest.mark.parametrize("tick", ["Vehicle_Coverage_ValuationAgreedAmountIndicator_A",
                                      "Vehicle_Coverage_ValuationStatedAmountIndicator_A"])
    def test_an_agreed_or_stated_valuation_keeps_it(self, tick):
        mapped = {"Vehicle_Coverage_AgreedOrStatedAmount_A": "25,000", tick: "Yes"}
        assert ps._blank_unexplained_stated_amount(mapped) == []

    def test_with_no_valuation_ticked_the_amount_is_left_alone(self):
        """Only the explicit contradiction is refused: a document can state a
        real amount whose tick the fill missed (16 Aug 2026 decision)."""
        mapped = {"Vehicle_Coverage_AgreedOrStatedAmount_A": "26,680"}
        assert ps._blank_unexplained_stated_amount(mapped) == []


# =============================================================================
# 4. The vehicle block's own COST NEW and USE cells
# =============================================================================
class TestVehicleBlockCells:

    def _mf(self, **over):
        mf = {"auto_vin_schedule": copy.deepcopy(MF["auto_vin_schedule"]),
              "auto_vehicle_use": copy.deepcopy(MF["auto_vehicle_use"])}
        mf.update(over)
        return mf

    def _docs(self, lines=None):
        return [{"text": "\n".join(lines or TEXT["vehicle_block"])}]

    def test_the_live_run_had_no_cost_new_and_an_inferred_use(self):
        assert "cost_new" not in _v(MF["auto_vin_schedule"])[0]
        assert _v(MF["auto_vehicle_use"]) == "commercial"
        assert _before("ACORD_127", "Vehicle_Use_CommercialIndicator_A") == "Yes"

    def test_cost_new_is_read_off_the_vehicles_own_block(self):
        mf = self._mf()
        es._read_vehicle_block_cells(mf, self._docs())
        assert _v(mf["auto_vin_schedule"])[0]["cost_new"] == "26680"
        f = {"_form_id": "ACORD_127", **mf}
        assert ps._deterministic_map("Vehicle_CostNewAmount_A", f) == "26,680"

    def test_use_na_clears_the_inferred_use_and_every_use_box(self):
        mf = self._mf()
        es._read_vehicle_block_cells(mf, self._docs())
        assert "auto_vehicle_use" not in mf
        f = {"_form_id": "ACORD_127", **mf}
        for box in ("Commercial", "Service", "Retail", "Pleasure", "Farm"):
            assert ps._deterministic_map(f"Vehicle_Use_{box}Indicator_A", f) in (None, "No", ps._SCHED_SKIP)
        assert ps._deterministic_map("Vehicle_Use_CommercialIndicator_A", f) is None

    def test_a_persons_answer_is_never_overridden(self):
        mf = self._mf(auto_vehicle_use={"value": "service", "source": "producer"})
        es._read_vehicle_block_cells(mf, self._docs())
        assert _v(mf["auto_vehicle_use"]) == "service"

    def test_a_printed_use_class_is_taken(self):
        lines = [l.replace("USE: NA", "USE: SERVICE") for l in TEXT["vehicle_block"]]
        mf = self._mf()
        es._read_vehicle_block_cells(mf, self._docs(lines))
        assert _v(mf["auto_vehicle_use"]) == "Service"

    def test_a_cost_new_extraction_returned_is_never_replaced(self):
        rows = copy.deepcopy(_v(MF["auto_vin_schedule"]))
        rows[0]["cost_new"] = "31000"
        mf = self._mf(auto_vin_schedule=rows)
        es._read_vehicle_block_cells(mf, self._docs())
        assert _v(mf["auto_vin_schedule"])[0]["cost_new"] == "31000"

    def test_two_vehicles_printing_different_uses_decide_nothing(self):
        other = ["2019 FORD F-150 VIN 1FTEW1EP5KFA12345", "COST NEW: 41000 RADIUS: 50 USE: SERVICE ."]
        mf = self._mf()
        es._read_vehicle_block_cells(mf, self._docs(TEXT["vehicle_block"] + other))
        assert _v(mf["auto_vehicle_use"]) == "commercial"


# =============================================================================
# 5. ACORD 127's rating-symbol columns (owner decision, 24 Sep 2026)
# =============================================================================
class TestVehicleRatingSymbols:

    def test_the_live_run_printed_the_covered_auto_symbol_there(self):
        assert [_before("ACORD_127", f) for f in ("Vehicle_SymbolCode_A", "Vehicle_ComprehensiveSymbolCode_A",
                                                  "Vehicle_CollisionSymbolCode_A")] == ["7", "07", "07"]

    @pytest.mark.parametrize("box", ["Vehicle_SymbolCode_A", "Vehicle_ComprehensiveSymbolCode_B",
                                     "Vehicle_CollisionSymbolCode_D"])
    def test_127_prints_no_covered_auto_symbol(self, box):
        f = _facts(_form_id="ACORD_127")
        assert ps._deterministic_map(box, f) is None
        assert ps._is_authoritative_blank_field(box, f)

    def test_the_137_still_prints_the_physical_damage_symbols(self):
        f = _facts(_form_id="ACORD_137_CO")
        mapped, _c = ps.map_facts_to_form(f, _schema("ACORD_137_CO"), form_id="ACORD_137_CO", raw_text="")
        assert mapped.get("Vehicle_BusinessAutoSymbol_SevenIndicator_F") == "Yes"
        assert mapped.get("Vehicle_BusinessAutoSymbol_SevenIndicator_H") == "Yes"


# =============================================================================
# 6. "ACORD 129 attached for additional vehicles" with one vehicle
# =============================================================================
class TestAttachmentOverflow:
    BOX = "CommercialVehicleLineOfBusiness_Attachment_VehicleScheduleIndicator_A"
    DRIVERS = "CommercialVehicleLineOfBusiness_Attachment_CommercialAutoDriverInformationScheduleIndicator_A"

    def _f(self, key, n):
        return {"_form_id": "ACORD_127", "_package_form_ids": ["ACORD_127"],
                key: [{"vin": f"V{i}", "name": f"N{i}", "license_number": f"L{i}"} for i in range(n)]}

    def test_the_live_run_ticked_it(self):
        assert _before("ACORD_127", self.BOX) == "Y"

    def test_one_vehicle_fits_the_127(self):
        assert ps._resolve_attachment_indicator(self.BOX, self._f("auto_vin_schedule", 1)) is None
        assert ps._resolve_attachment_indicator(self.BOX, self._f("auto_vin_schedule", 4)) is None

    def test_a_fifth_vehicle_overflows_onto_the_129(self):
        assert ps._resolve_attachment_indicator(self.BOX, self._f("auto_vin_schedule", 5)) == "Y"

    def test_the_capacity_is_read_from_the_form(self):
        assert ps._schedule_row_capacity("ACORD_127", "Vehicle_VINIdentifier_") == 4
        assert ps._schedule_row_capacity("ACORD_127", "Driver_GivenName_") == 13
        assert ps._resolve_attachment_indicator(self.DRIVERS, self._f("auto_drivers", 13)) is None
        assert ps._resolve_attachment_indicator(self.DRIVERS, self._f("auto_drivers", 14)) == "Y"


# =============================================================================
# 7. ACORD 126: the pollution deductible printed as PD AND BI deductibles
# =============================================================================
class TestGlDeductible:
    PD, BI = "GeneralLiability_PropertyDamage_DeductibleAmount_A", "GeneralLiability_BodilyInjury_DeductibleAmount_A"
    OTHER_AMT, OTHER_DESC = "GeneralLiability_OtherDeductibleAmount_A", "GeneralLiability_OtherDeductibleDescription_A"

    def test_the_live_run_printed_it_three_times(self):
        assert [_before("ACORD_126", b) for b in (self.PD, self.BI, self.OTHER_AMT)] == ["1,000"] * 3

    def test_the_live_lines_classify_it_as_the_pollution_deductible(self):
        mf = {"gl_deductible": MF["gl_deductible"]}
        assert es._classify_gl_deductible(mf, [{"text": "\n".join(TEXT["deductible_lines"])}]) == "other"
        assert "Pollution" in mf["_gl_deductible_scope"]["text"]

    def test_the_auto_deductibles_beside_it_are_not_gl_evidence(self):
        for ln in TEXT["deductible_lines"]:
            if "AUTO" in ln.upper():
                assert es._DEDUCTIBLE_NOT_GL_RE.search(ln), ln

    def test_it_prints_on_the_other_row_only(self):
        f = {"_form_id": "ACORD_126", "gl_deductible": MF["gl_deductible"],
             "_gl_deductible_scope": {"scope": "other",
                                      "text": "Property Damage Deductible $1,000 Each Pollution Incidents"}}
        assert ps._deterministic_map(self.PD, f) is None
        assert ps._deterministic_map(self.BI, f) is None
        assert ps._deterministic_map(self.OTHER_AMT, f) == _v(MF["gl_deductible"])
        assert "Pollution" in ps._deterministic_map(self.OTHER_DESC, f)

    @pytest.mark.parametrize("line, scope, pd, bi", [
        ("Property Damage Liability Deductible $1,000 Per Claim", "pd", True, False),
        ("Bodily Injury Liability Deductible $1,000 per occurrence", "bi", False, True),
        ("Bodily Injury and Property Damage Liability Deductible $1,000 per occurrence", "bi_pd", True, True),
        ("CG 03 00 01 96 Deductible Liability Insurance - Property Damage $1,000 per claim", "pd", True, False)])
    def test_a_plain_liability_deductible_goes_to_its_own_box(self, line, scope, pd, bi):
        mf = {"gl_deductible": "$1,000"}
        assert es._classify_gl_deductible(mf, [{"text": line}]) == scope
        f = {"_form_id": "ACORD_126", "gl_deductible": "$1,000", **mf}
        assert (ps._deterministic_map(self.PD, f) == "$1,000") is pd
        assert (ps._deterministic_map(self.BI, f) == "$1,000") is bi
        assert ps._deterministic_map(self.OTHER_AMT, f) is None

    @pytest.mark.parametrize("text", ["Deductible $1,000",
                                      "Property Damage Deductible $1,000 per claim\n"
                                      "Property Damage Deductible $1,000 Each Pollution Incident"])
    def test_no_or_contradicting_wording_changes_nothing(self, text):
        mf = {"gl_deductible": "$1,000"}
        assert es._classify_gl_deductible(mf, [{"text": text}]) is None
        f = {"_form_id": "ACORD_126", "gl_deductible": "$1,000"}
        assert ps._deterministic_map(self.PD, f) == "$1,000"          # legacy rule


# =============================================================================
# 8. ACORD 137 CO: "other symbol 1" on the uninsured-motorists row
# =============================================================================
class TestCoveredAutoSymbols:

    def test_the_live_run_printed_it(self):
        assert _before("ACORD_137_CO", "Vehicle_BusinessAutoSymbol_OtherSymbolCode_C") == "1"

    def test_the_certificates_umbrella_row_no_longer_reaches_um(self):
        parsed = sym.symbols_by_coverage(MF)
        assert parsed.get(sym.UM_UIM) == [2]
        assert parsed.get(sym.LIABILITY) == [1]

    @pytest.mark.parametrize("label, expect", [
        ("umbrella liability", ["liability"]), ("UM/UIM", ["um_uim"]), ("UM", ["um_uim"]),
        ("Uninsured and Underinsured Motorists", ["um_uim"]), ("Comp/Coll", ["comprehensive", "collision"]),
        ("company", ["unspecified"]), ("Premium", ["unspecified"]), ("maximum", ["unspecified"]),
        ("Liab.", ["liability"]), ("physicaldamage", ["physical_damage"])])
    def test_short_abbreviations_are_whole_words(self, label, expect):
        assert sym.normalize_coverages(label) == expect

    @pytest.mark.parametrize("label", ["commercial general liability", "umbrella liability", "Excess Liability",
                                       "Workers Compensation", "Inland Marine"])
    def test_a_non_auto_line_designates_no_auto_symbol(self, label):
        assert sym.parse_symbols([{"coverage": label, "symbols": [1]}]) == {}

    def test_auto_lines_still_parse(self):
        assert sym.parse_symbols([{"coverage": "automobile liability", "symbols": [1]}]) == {"liability": [1]}
        # "property damage" is an AUTO liability component: the non-auto filter
        # must not drop it (it parses as it always did).
        assert sym.parse_symbols([{"coverage": "Property Damage", "symbols": [1]}]) == {"unspecified": [1]}

    def test_the_137_grid_prints_what_the_dec_prints(self):
        f = _facts(_form_id="ACORD_137_CO")
        mapped, _c = ps.map_facts_to_form(f, _schema("ACORD_137_CO"), form_id="ACORD_137_CO", raw_text="")
        ticked = {k for k, v in mapped.items() if "BusinessAutoSymbol" in k and v == "Yes"}
        assert ticked == {"Vehicle_BusinessAutoSymbol_OneIndicator_A", "Vehicle_BusinessAutoSymbol_TwoIndicator_B",
                          "Vehicle_BusinessAutoSymbol_TwoIndicator_C", "Vehicle_BusinessAutoSymbol_SevenIndicator_F",
                          "Vehicle_BusinessAutoSymbol_SevenIndicator_H"}
        assert not mapped.get("Vehicle_BusinessAutoSymbol_OtherSymbolCode_C")

    @pytest.mark.parametrize("unknown", [5, 10])
    def test_a_symbol_acord_prints_nowhere_still_uses_other(self, unknown):
        f = {"_form_id": "ACORD_137_CO", "has_auto_coverage": True,
             "auto_covered_symbols": [{"coverage": "liability", "symbols": [1]},
                                      {"coverage": "uninsured motorists", "symbols": [unknown]}]}
        mapped, _c = ps.map_facts_to_form(f, _schema("ACORD_137_CO"), form_id="ACORD_137_CO", raw_text="")
        assert mapped.get("Vehicle_BusinessAutoSymbol_OtherSymbolCode_C") == str(unknown)


# =============================================================================
# 9. 131 Q14 "Y" and 126 Q4 "N" - one question, answered both ways
# =============================================================================
class TestCrossFormYesNo:
    Q126, Q131 = "Contractors_Question_ABBCode_A", "CommercialUmbrellaLineOfBusiness_Question_ABBCode_A"

    def _per_form(self, a126, a131):
        return {"ACORD_126": {"filled_values": {self.Q126: a126, "Contractors_Question_AADCode_A": "N"},
                              "question_grounding": {}},
                "ACORD_131": {"filled_values": {self.Q131: a131,
                                                "CommercialUmbrellaLineOfBusiness_Question_AAICode_A": "Y"},
                              "question_grounding": {}}}

    def _schemas(self):
        return {"ACORD_126": _schema("ACORD_126"), "ACORD_131": _schema("ACORD_131")}

    def test_the_live_run_answered_both_ways(self):
        assert _before("ACORD_126", self.Q126) == "N"
        assert _before("ACORD_131", self.Q131) == "Y"

    def test_a_contradiction_blanks_both_and_nothing_else(self):
        pf = self._per_form("N", "Y")
        removed = ps.reconcile_cross_form_yes_no(pf, self._schemas())
        assert sorted(removed) == sorted([f"ACORD_126:{self.Q126}", f"ACORD_131:{self.Q131}"])
        assert pf["ACORD_126"]["filled_values"] == {"Contractors_Question_AADCode_A": "N"}
        assert pf["ACORD_131"]["filled_values"] == {"CommercialUmbrellaLineOfBusiness_Question_AAICode_A": "Y"}

    def test_agreement_is_kept(self):
        pf = self._per_form("N", "N")
        assert ps.reconcile_cross_form_yes_no(pf, self._schemas()) == []

    def test_the_same_question_matches_however_the_form_words_it(self):
        s126, s131 = self._schemas()["ACORD_126"], self._schemas()["ACORD_131"]
        a = ps._question_identity(s126[self.Q126]["tu"])
        b = ps._question_identity(s131[self.Q131]["tu"])
        assert len(a & b) / len(a | b) >= 0.8
        # ACORD 126 PRINTS it "Do your subcontractors carry coverages or limits
        # less than yours?" - pronouns and "applicant" carry no identity.
        printed = ('Enter Y for a "Yes" response. Input N for "No" response. The response to the '
                   'question, "Do your subcontractors carry coverages or limits less than yours?".')
        c = ps._question_identity(printed)
        assert len(c & b) / len(c | b) >= 0.8

    def test_different_questions_never_match(self):
        s = _schema("ACORD_126")
        a = ps._question_identity(s[self.Q126]["tu"])
        b = ps._question_identity(s["Contractors_Question_AADCode_A"]["tu"])
        assert len(a & b) / len(a | b) < 0.8


# =============================================================================
# 10. "INSURED IS: LLC BUSINESS DESC: COMMERCIAL GENERAL CONTRA"
# =============================================================================
class TestOperationsDescription:

    def _docs(self):
        return copy.deepcopy(LIVE["documents"])

    def test_the_live_run_printed_the_dec_field(self):
        assert _before("ACORD_125", "CommercialPolicy_OperationsDescription_A").startswith("INSURED IS:")

    def test_the_applicants_own_words_win(self):
        mf = {"operations_description": {"value": "INSURED IS: LLC BUSINESS DESC: COMMERCIAL GENERAL CONTRA",
                                         "source": "ai"}}
        es._prefer_submission_operations_description(mf, self._docs())
        assert _v(mf["operations_description"]).startswith("Commercial general contractor. The company manages")

    def test_with_no_submission_description_the_labels_are_stripped(self):
        docs = [d for d in self._docs() if d["doc_type"] != "narrative"]
        mf = {"operations_description": {"value": "INSURED IS: LLC BUSINESS DESC: COMMERCIAL GENERAL CONTRA"}}
        es._prefer_submission_operations_description(mf, docs)
        assert _v(mf["operations_description"]) == "COMMERCIAL GENERAL CONTRA"

    def test_a_persons_answer_stands(self):
        mf = {"operations_description": {"value": "Roofing contractor", "source": "producer"}}
        es._prefer_submission_operations_description(mf, self._docs())
        assert _v(mf["operations_description"]) == "Roofing contractor"

    def test_an_applications_description_is_not_replaced_by_the_narrative(self):
        docs = self._docs() + [{"doc_type": "application", "facts": {
            "operations_description": "General contractor for tenant improvements in office buildings."}}]
        mf = {"operations_description": {"value": "General contractor for tenant improvements in office buildings."}}
        assert es._prefer_submission_operations_description(mf, docs) is None

    @pytest.mark.parametrize("value", ["Commercial general contractor", "Retail - desc of goods sold"])
    def test_an_ordinary_description_is_untouched(self, value):
        assert es._strip_operations_labels(value) == value


# =============================================================================
# 11. The cover called an ended term "current" and the account "in force"
# =============================================================================
class TestCoverTerm:

    def test_the_live_term_has_ended(self):
        from services.cover_service import _cover_info_values, _moved_term_ended
        assert _moved_term_ended(MF) is True
        period = _cover_info_values(MF, LIVE["flags"], {"full_name": "vinay sharma"}, "Astrea")["period"]
        assert "expired term" in period and "current" not in period

    def test_an_in_force_term_is_still_current(self):
        from services.cover_service import _moved_term_ended
        assert _moved_term_ended({"prior_effective_date": "07/15/2026",
                                  "prior_expiration_date": "07/15/2099"}) is False
