"""Fix C (14 Oct 2026): an AI value whose ONLY evidence is the wrong source.

The owner's parked class: a gap-fill value whose only evidence is another
policy's / section's / document role's text, the box's own tooltip example, or
a person's answer to a different question. Every live value below is read off
the stored Choice Electric runs (`ba7c709d`, `18f6914f`, `b117f010`,
`f83757cf`) with their stored AI answers replayed through the stamper; every
look-alike that must STAY is a shape the 660-package stored corpus holds.

Rules (services/ai_answer_guards unless named):
  (1) a person's identity answer to another question   AI_ANSWER_TO_ANOTHER_QUESTION
  (2) the box's own tooltip example, stated by nothing AI_TOOLTIP_EXAMPLE
  (3) a qualified box without its qualifier            AI_QUALIFIER_NOT_STATED
  (4) a middle initial made from the row's own name    AI_INITIAL_FROM_THE_NAME
  (5) another party's address on a driver's row        AI_ADDRESS_NOT_THIS_PERSONS
  (6) a rating factor as an identifier                 AI_FACTOR_AS_IDENTIFIER
  (7) a row reference as a description                 AI_ROW_REFERENCE_AS_DESCRIPTION
  (8) a form's unfilled label line as a value          AI_BLANK_FORM_LABEL
  (9) a covered auto symbol nothing states             AI_SYMBOL_NOT_STATED
  W10 a coverage table row as an explanation           AI_COVERAGE_ROW_AS_EXPLANATION
  X2  the 130 worksheet OTHER row naming its own row   AI_OTHER_ROW_HAS_ITS_OWN_BOXES
  ai_role_guards (e2): the general contact in a role nobody stated
  pdf_service: an AI deductible in an OTHER row with nothing named; the meaning
  gate's enveloped exposure witnesses.
"""
import json
from pathlib import Path

import pytest

from services import ai_answer_guards as g
from services import ai_role_guards as rg
from services import needs_attention as na
from services import pdf_service as ps

BACKEND = Path(__file__).resolve().parents[1]


def _schema(form_id):
    return json.loads((BACKEND / "forms_schemas" / f"{form_id}_schema.json").read_text())


S125, S126, S127, S130, S131, S140, S186 = (_schema(f) for f in (
    "ACORD_125", "ACORD_126", "ACORD_127", "ACORD_130", "ACORD_131", "ACORD_140", "ACORD_186"))
S137 = _schema("ACORD_137_CO")


def _person(v):
    return {"value": v, "source": "producer", "confidence": "filled", "value_state": "present"}


def _doc(v):
    return {"value": v, "source": "ai", "confidence": "medium"}


def _codes(out):
    return {f: why.split(":", 1)[0] for f, why in out.items()}


def _refuse(schema, form_id, mapped, raw, facts, ai=None):
    m = dict(mapped)
    return _codes(g.refuse_non_answers(m, schema, dict(facts), raw, set(ai or mapped), form_id)), m


# The Choice Electric documents as the stamper reads them (lines from the stored
# decs, the insured's mailing address redacted as it is on the real decs).
CE_WC = ("Item 3. A. Worker's Compensation Insurance: Part One of the Policy applies to the Workers "
         "Compensation Law of the states listed here: CO\n"
         "CO 001 8810 State Act - Clerical Office Employees NOC. 200,000 0.0900 180.00\n"
         "CO Total Manual Premium $2,626,500.00 38,377.00\n"
         "CO 9664 Small Deductible 6.5000 -2,495.00\n"
         "CO 9898 Experience Mod 1.0800 2,904.00\n")
CE_AUTO = ("Covered Autos Liability is written on covered auto symbols 1 (any auto)\n"
           "001 2001CHEVROLET EXPRESS G2500 111 DENVER, CO 80221 21,210\n"
           "002 1999GMC SAFARI XT 111 DENVER, CO 80221 23,316\n")
CE_UMB = ("SCHEDULE OF UNDERLYING INSURANCE\n"
          "The Schedule of Underlying Insurance is part of Policy No.\n"
          "Carrier, Policy Number, Type of Limits of\n")
CE_RAW = "\n".join(("COMMON POLICY DECLARATIONS\nAMERISURE INSURANCE COMPANY\nNAMEDINSURED:\n",
                    CE_WC, CE_AUTO, CE_UMB))
CE_FACTS = {
    "applicant_name": _doc("Choice Electric LLC"),
    "contact_name": _person("Dana Whitfield"),
    "mailing_address": _person("4800 Washington St, Denver, CO 80216"),
    "total_revenue": _person("4500000"),
    "total_payroll": _person("2626500"),
    "wc_payroll": {"value": "$2,626,500", "source": "derived"},
    "additional_remarks_text": _person(
        "Scope of work: about 70% new construction and tenant finish and 30% service and repair; "
        "no residential work. Location details: one premises at 4800 Washington St."),
}


# ══ (1) a person's identity answer to ANOTHER question ════════════════════════

def test_w16_the_typed_contact_is_not_a_vehicles_other_owner():
    out, m = _refuse(S127, "ACORD_127", {"AdditionalInterest_FullName_D": "Dana Whitfield"},
                     CE_RAW, CE_FACTS)
    assert out == {"AdditionalInterest_FullName_D": g.REASON_ANOTHER_QUESTION}
    assert m["AdditionalInterest_FullName_D"] is None


def test_the_typed_mailing_address_is_not_the_garage_description():
    f = "CommercialVehicleLineOfBusiness_GarageStorageDescription_A"
    out, _m = _refuse(S127, "ACORD_127", {f: "4800 Washington St, Denver, CO 80216"}, CE_RAW, CE_FACTS)
    assert out == {f: g.REASON_ANOTHER_QUESTION}


@pytest.mark.parametrize("why,raw,facts", [
    # printed in a document: there is document evidence (whose role it is, is another question)
    ("printed", CE_RAW + "\nOther owner: Dana Whitfield", CE_FACTS),
    # a document's own fact holds the same value
    ("document fact", CE_RAW, {**CE_FACTS, "loss_payee_name": _doc("Dana Whitfield")}),
    # no documents to read at all: not judged
    ("no documents", "", CE_FACTS),
])
def test_a_typed_identity_with_other_evidence_stays(why, raw, facts):
    out, _m = _refuse(S127, "ACORD_127", {"AdditionalInterest_FullName_D": "Dana Whitfield"}, raw, facts)
    assert out == {}, why


def test_a_person_answer_for_this_very_question_stays():
    # 125 CONTACT NAME is the contact_name question itself
    out, _m = _refuse(S125, "ACORD_125", {"NamedInsured_Contact_FullName_A": "Dana Whitfield"},
                      CE_RAW, CE_FACTS)
    assert out == {}


def test_a_typed_amount_is_not_judged_by_the_identity_rule():
    # 09cdcfeb: the typed business income limit is the 140's business income row
    facts = {"business_income_limit": _person("450000")}
    f = "CommercialProperty_Premises_LimitAmount_C"
    out, _m = _refuse(S140, "ACORD_140", {f: "$450,000"}, "PREMISES DECLARATIONS", facts)
    assert out == {}


def test_a_short_value_never_counts_as_a_copy():
    facts = {"contact_name": _person("Al")}
    out, _m = _refuse(S127, "ACORD_127", {"AdditionalInterest_FullName_D": "Al"}, CE_RAW, facts)
    assert out == {}


# ══ (2) the box's own tooltip example ═════════════════════════════════════════

def test_w3_contact_type_accounting_is_the_tooltip_example():
    f = "NamedInsured_Contact_ContactDescription_A"
    assert "accounting" in g.tooltip_options(S125[f]["tu"], minimum=1)
    out, _m = _refuse(S125, "ACORD_125", {f: "Accounting"}, CE_RAW, CE_FACTS)
    assert out == {f: g.REASON_TOOLTIP_EXAMPLE}


def test_sprinklers_as_fire_protection_is_the_tooltip_example():
    f = "BuildingFireProtection_Alarm_ProtectionDescription_A"
    out, _m = _refuse(S140, "ACORD_140", {f: "sprinklers"}, "PREMISES 001 BUILDING 001 FRAME", {})
    assert out == {f: g.REASON_TOOLTIP_EXAMPLE}


@pytest.mark.parametrize("raw,facts", [
    ("ACCOUNTING CONTACT: Priya Raman, Controller", {}),           # a document states it
    (CE_RAW, {"contact_type": _person("Accounting")}),              # a person gave it
])
def test_a_stated_example_stays(raw, facts):
    f = "NamedInsured_Contact_ContactDescription_A"
    out, _m = _refuse(S125, "ACORD_125", {f: "Accounting"}, raw, facts)
    assert out == {}


def test_a_code_boxs_example_is_a_reading_not_a_borrow():
    # 140 deductible type "dollars" beside a "$5,000" deductible: the option set
    f = "CommercialProperty_Premises_DeductibleTypeCode_A"
    out, _m = _refuse(S140, "ACORD_140", {f: "dollars"}, "DEDUCTIBLE $5,000", {})
    assert out == {}


# ══ (3) a qualified box needs its qualifier ═══════════════════════════════════

def test_w4_the_wc_payroll_is_not_paid_to_subcontractors():
    f = "Contractors_SubcontractorsPaidAmount_A"
    out, _m = _refuse(S126, "ACORD_126", {f: "$2,626,500"}, CE_RAW, CE_FACTS)
    assert out == {f: g.REASON_QUALIFIER_NOT_STATED}


@pytest.mark.parametrize("value", [
    "about 70% new construction and tenant finish and 30% service and repair; no residential work",
    "30% service and repair", "primarily consist of construction",
    "Residential and commercial roofing installation, repair and replacement",
])
def test_w6_a_scope_sentence_is_not_the_type_of_work_subcontracted(value):
    f = "GeneralLiabilityLineOfBusiness_TypeOfWorkSubcontractedDescription_A"
    out, _m = _refuse(S126, "ACORD_126", {f: value}, CE_RAW, CE_FACTS)
    assert out == {f: g.REASON_QUALIFIER_NOT_STATED}


@pytest.mark.parametrize("raw,facts,value", [
    # Orbin's GL schedule abbreviates the ISO class ("Contrctrs-sub work")
    ("91585 Contrctrs-sub work-in connection 3.4240 $1,198 2.293 $803\n"
     "w/constrctn,recon,repr,erctn of buildings -\nNOC\nPrem Basis: Total Cost\nExposure: $350,000",
     {}, "350,000"),
    ("91585 Contractors - subcontracted work Cost $960,000", {}, "960,000"),
    ("COMMON POLICY DECLARATIONS", {"subcontract_cost": _person("350000")}, "350,000"),
])
def test_a_subcontracted_cost_stated_as_one_stays(raw, facts, value):
    f = "ContractorsUnderwriting_SubcontractedWorkCostAmount_A"
    out, _m = _refuse(S186, "ACORD_186", {f: value}, raw, facts)
    assert out == {}


def test_total_revenue_is_not_foreign_gross_sales():
    f = "BusinessInformation_ForeignGrossSalesAmount_A"
    out, _m = _refuse(S131, "ACORD_131", {f: "$4,500,000"}, CE_RAW, CE_FACTS)
    assert out == {f: g.REASON_QUALIFIER_NOT_STATED}
    out, _m = _refuse(S131, "ACORD_131", {f: "$250,000"}, CE_RAW + "\nForeign sales: $250,000", CE_FACTS)
    assert out == {}


@pytest.mark.parametrize("value", ["Annual", "Applied for", "No prior insurance"])
def test_the_retro_plan_box_takes_a_retrospective_plan(value):
    f = "Policy_RetrospectiveRatingPlan_A"
    raw = CE_RAW + "\nADJUSTMENTS OF PREMIUM SHALL BE MADE ANNUALLY\nItem 5. Retroactive Date"
    out, _m = _refuse(S130, "ACORD_130", {f: value}, raw, CE_FACTS)
    assert out == {f: g.REASON_QUALIFIER_NOT_STATED}
    kept, _m = _refuse(S130, "ACORD_130", {f: "Large Risk Alternative"},
                       raw + "\nRetrospective rating plan: Large Risk Alternative", CE_FACTS)
    assert kept == {}


# ══ (4) a middle initial made from the row's own name ═════════════════════════

def _drivers(**over):
    rows = {"Driver_GivenName_A": "Marcus", "Driver_Surname_A": "Delgado",
            "Driver_GivenName_B": "Erin", "Driver_Surname_B": "Royal"}
    rows.update(over)
    return rows


def test_w8_the_first_initial_is_not_a_middle_initial():
    m = _drivers(Driver_OtherGivenNameInitial_A="M", Driver_OtherGivenNameInitial_B="Royal")
    out, _m = _refuse(S127, "ACORD_127", m, CE_RAW, {},
                      ai={"Driver_OtherGivenNameInitial_A", "Driver_OtherGivenNameInitial_B"})
    assert out == {"Driver_OtherGivenNameInitial_A": g.REASON_INITIAL_FROM_NAME,
                   "Driver_OtherGivenNameInitial_B": g.REASON_INITIAL_FROM_NAME}


@pytest.mark.parametrize("raw,initial", [
    ("1 MARCUS M. DELGADO 03/14/1979 08-417-2291 CO", "M"),     # printed with the name
    ("DELGADO, MARCUS M 03/14/1979", "M."),
    ("1 MARCUS J DELGADO 03/14/1979", "J"),                       # not made from the name
])
def test_a_printed_middle_initial_stays(raw, initial):
    m = _drivers(Driver_OtherGivenNameInitial_A=initial)
    out, _m = _refuse(S127, "ACORD_127", m, raw, {}, ai={"Driver_OtherGivenNameInitial_A"})
    assert out == {}


# ══ (5) another party's address on a driver's row ═════════════════════════════

def test_w9_the_garaging_line_is_not_the_drivers_address():
    m = _drivers(Driver_MailingAddress_CityName_A="Denver", Driver_MailingAddress_PostalCode_A="80221",
                 Driver_MailingAddress_StateOrProvinceCode_A="CO")
    ai = {"Driver_MailingAddress_CityName_A", "Driver_MailingAddress_PostalCode_A",
          "Driver_MailingAddress_StateOrProvinceCode_A"}
    out, _m = _refuse(S127, "ACORD_127", m, CE_RAW, {}, ai=ai)
    assert out == {b: g.REASON_ADDRESS_NOT_THIS_PERSONS for b in ai}


@pytest.mark.parametrize("raw", [
    "Driver 1\nName: Marcus Delgado\nAddress: 12 Elm St\nDenver, CO 80221",
    "1 MARCUS DELGADO 03/14/1979 12 ELM ST DENVER CO 80221",
])
def test_a_drivers_own_address_stays(raw):
    m = _drivers(Driver_MailingAddress_CityName_A="Denver", Driver_MailingAddress_PostalCode_A="80221",
                 Driver_MailingAddress_StateOrProvinceCode_A="CO")
    ai = {"Driver_MailingAddress_CityName_A", "Driver_MailingAddress_PostalCode_A",
          "Driver_MailingAddress_StateOrProvinceCode_A"}
    out, _m = _refuse(S127, "ACORD_127", m, raw, {}, ai=ai)
    assert out == {}


def test_a_row_with_nobody_on_it_is_not_judged_and_a_lone_state_says_nothing():
    out, _m = _refuse(S127, "ACORD_127", {"Driver_MailingAddress_PostalCode_A": "80221"}, CE_RAW, {})
    assert out == {}
    m = _drivers(Driver_MailingAddress_StateOrProvinceCode_A="CO")
    out, _m = _refuse(S127, "ACORD_127", m, CE_RAW, {}, ai={"Driver_MailingAddress_StateOrProvinceCode_A"})
    assert out == {}


# ══ (6) - (9) another section's text ══════════════════════════════════════════

def test_the_experience_mod_is_not_the_ncci_risk_id():
    f = "NamedInsured_NCCIRiskIdentifier_A"
    out, _m = _refuse(S130, "ACORD_130", {f: "1.0800"}, CE_RAW, {})
    assert out == {f: g.REASON_FACTOR_AS_IDENTIFIER}
    assert _refuse(S130, "ACORD_130", {f: "1.0800"}, "NCCI RISK ID: 1.0800", {})[0] == {}
    assert _refuse(S130, "ACORD_130", {f: "123456789"}, "NCCI RISK ID 123456789", {})[0] == {}


@pytest.mark.parametrize("value,refused", [
    ("Prem #: 001 Bldg #: 001", True), ("Prem. #: 001 Bldg #: 002", True), ("Bldg No. 2", True),
    ("Location 2 - Building 1", False), ("Office and electrical shop", False),
    ("Suite #210 office and warehouse", False),
])
def test_x7_a_row_reference_is_not_a_building_description(value, refused):
    f = "CommercialStructure_Building_SublocationDescription_A"
    out, _m = _refuse(S140, "ACORD_140", {f: value}, "Prem #: 001 Bldg #: 001 FRAME", {})
    assert (out == {f: g.REASON_ROW_REFERENCE}) is refused, value


def test_an_unfilled_form_label_is_not_underlying_information():
    f = "UnderlyingCoverage_InformationDescription_A"
    v = "The Schedule of Underlying Insurance is part of Policy No."
    out, _m = _refuse(S131, "ACORD_131", {f: v}, CE_RAW, {})
    assert out == {f: g.REASON_BLANK_FORM_LABEL}
    filled = CE_RAW.replace("Policy No.\n", "Policy No. CU 1234567\n")
    assert _refuse(S131, "ACORD_131", {f: v}, filled, {})[0] == {}


def test_symbols_one_to_seven_with_no_auto_policy_are_stated_by_nothing():
    rows = {f"Vehicle_BusinessAutoSymbol_OtherSymbolCode_{r}": str(i)
            for i, r in enumerate("ABCEFGH", start=1)}
    raw = "COMMON POLICY DECLARATIONS\nWORKERS COMPENSATION"
    out, _m = _refuse(S137, "ACORD_137_CO", rows, raw, {})
    assert out == {f: g.REASON_SYMBOL_NOT_STATED for f in rows}
    one = {"Vehicle_BusinessAutoSymbol_OtherSymbolCode_A": "7"}
    stated = "COVERED AUTOS LIABILITY: Symbol 07 - Specifically Described Autos"
    assert _refuse(S137, "ACORD_137_CO", one, stated, {})[0] == {}
    facts = {"auto_covered_symbols": [{"coverage": "liability", "symbols": [7]}]}
    assert _refuse(S137, "ACORD_137_CO", one, raw, facts)[0] == {}


# ══ ai_role_guards (e2): the general contact in a role nobody stated ══════════

_ROLE_BOXES = {"NamedInsured_AccountingContact_FullName_A": "Dana Whitfield",
               "NamedInsured_ClaimContact_FullName_A": "Dana Whitfield",
               "NamedInsured_InspectionContact_PhoneNumber_A": "303-555-0148"}


def test_the_general_contact_is_not_every_role_contact():
    facts = {"contact_name": _person("Dana Whitfield"), "contact_phone": _doc("(303) 555-0148")}
    m = dict(_ROLE_BOXES)
    out = rg.drop_role_mismatches(m, S130, facts, "Contact: Dana Whitfield, (303) 555-0148",
                                  set(m), "ACORD_130")
    assert _codes(out) == {f: rg.R_CONTACT_ROLE for f in _ROLE_BOXES}
    assert all(m[f] is None for f in _ROLE_BOXES)


def test_a_role_the_documents_state_stays_and_another_person_is_not_judged():
    facts = {"contact_name": _doc("Marcus Ellery")}
    raw = ("Inspection Contact Name: Marcus Ellery, Operations Manager\n"
           "Accounting Contact Name: Priya Raman, Controller")
    m = {"NamedInsured_InspectionContact_FullName_A": "Marcus Ellery",
         "NamedInsured_AccountingContact_FullName_A": "Priya Raman"}
    assert rg.drop_role_mismatches(dict(m), S130, facts, raw, set(m), "ACORD_130") == {}


# ══ pdf_service: an AI deductible in an OTHER row with nothing named ══════════

_OD, _ODD = "GeneralLiability_OtherDeductibleAmount_A", "GeneralLiability_OtherDeductibleDescription_A"


def _row126(**over):
    m = {f: None for f in S126}
    m.update(over)
    return m


def test_the_parked_5000_with_no_deductible_named_is_refused():
    m = _row126(**{_OD: "5,000"})
    ai = {_OD}
    ps._blank_unnamed_other_rows(m, ai, "ACORD_126")
    assert m[_OD] is None and _OD not in ai


@pytest.mark.parametrize("over,ai", [
    ({_OD: "1,000", _ODD: "Limited Pollution Coverage - Work Sites"}, {_OD}),   # named
    ({_OD: "$1,000 Each Pollution Incident"}, set()),                           # a rule's value
])
def test_a_named_or_stated_other_deductible_stays(over, ai):
    m = _row126(**over)
    ps._blank_unnamed_other_rows(m, set(ai), "ACORD_126")
    assert m[_OD] == over[_OD]


def test_frozen_forms_keep_their_other_deductibles():
    m = {"GeneralLiability_OtherDeductibleAmount_A": "1,000",
         "GeneralLiability_OtherDeductibleDescription_A": None}
    ps._blank_unnamed_other_rows(m, {"GeneralLiability_OtherDeductibleAmount_A"}, "ACORD_160")
    assert m["GeneralLiability_OtherDeductibleAmount_A"] == "1,000"


# ══ pdf_service: the meaning gate reads an enveloped exposure fact ════════════

def test_an_enveloped_payroll_witnesses_its_amount_and_a_value_never_does():
    facts = {"wc_payroll": {"value": "$2,626,500", "source": "derived"},
             "building_value": {"value": "$798,556", "source": "ai"},
             "_form_id": "ACORD_126"}
    w = ps._build_amount_witnesses(facts)
    assert w.get(2626500) == {"payroll"}
    assert 798556 not in w                                  # limit / value never from an envelope
    assert 2626500 not in ps._build_amount_witnesses({**facts, "_form_id": "ACORD_141"})


def test_w4_end_to_end_the_stamp_leaves_paid_to_subcontractors_blank(monkeypatch):
    monkeypatch.setattr(ps, "_EVIDENCE_JUDGE_ENABLED", False)
    f = "Contractors_SubcontractorsPaidAmount_A"
    report = []
    mapped, _c = ps.map_facts_to_form(
        dict(CE_FACTS), S126, form_id="ACORD_126", raw_text=CE_RAW,
        pre_filled_gpt={"filled_values": {f: "$2,626,500"}, "raw_text_fields": set(),
                        "question_grounding": {}}, guard_report=report)
    assert not str(mapped.get(f) or "").strip()
    row = {r["field"]: r for r in report}[f]
    assert row["reason"] in ("AMOUNT_STATED_AS_PAYROLL", g.REASON_QUALIFIER_NOT_STATED)


def test_the_parked_5000_end_to_end(monkeypatch):
    monkeypatch.setattr(ps, "_EVIDENCE_JUDGE_ENABLED", False)
    raw = CE_RAW + "\nLIMIT COINSURANCE DEDUCTIBLE\n$798,556 80% $5,000\nTHEFT CAUSE OF LOSS DEDUCTIBLE: $5,000"
    report = []
    mapped, _c = ps.map_facts_to_form(
        dict(CE_FACTS), S126, form_id="ACORD_126", raw_text=raw,
        pre_filled_gpt={"filled_values": {_OD: "5,000"}, "raw_text_fields": set(),
                        "question_grounding": {}}, guard_report=report)
    assert not str(mapped.get(_OD) or "").strip()
    assert {r["field"]: r for r in report}[_OD]["reason"] == g.REASON_OTHER_ROW_UNNAMED


# ══ the review says why, in plain words ══════════════════════════════════════

def test_every_new_reason_has_its_sentence_and_quotes_nothing():
    new = (g.REASON_ANOTHER_QUESTION, g.REASON_TOOLTIP_EXAMPLE, g.REASON_QUALIFIER_NOT_STATED,
           g.REASON_INITIAL_FROM_NAME, g.REASON_ADDRESS_NOT_THIS_PERSONS, g.REASON_FACTOR_AS_IDENTIFIER,
           g.REASON_ROW_REFERENCE, g.REASON_BLANK_FORM_LABEL, g.REASON_SYMBOL_NOT_STATED,
           g.REASON_OTHER_ROW_UNNAMED)
    for code in new:
        assert code in g.REASON_CODES
        s = g.held_back_sentence(code)
        assert s and s.endswith(".") and "—" not in s
        sentence, quotable = na.held_back(S125, "NamedInsured_Contact_ContactDescription_A",
                                          "Accounting", {}, None, False, reason=code)
        assert sentence == s and quotable is False


def test_frozen_forms_are_untouched():
    # ACORD 141 left the frozen set on 25 Oct 2026 (Z41 lane 3); ACORD 160 stays.
    s160 = _schema("ACORD_160")
    f = next(f for f in s160 if f.endswith("Description_A") and "Enter text" in str(s160[f].get("tu")))
    assert g.refuse_non_answers({f: "Prem #: 001 Bldg #: 001"}, s160, {}, CE_RAW, {f}, "ACORD_160") == {}


# ══ W10: a coverage table row is no explanation ═══════════════════════════════

_W10 = "CommercialUmbrellaLineOfBusiness_AnyProductWorkAccidentlocationBeenExcludedUninsuredExplanation_A"


def test_w10_the_umbrellas_own_schedule_row_explains_nothing():
    out, _m = _refuse(S131, "ACORD_131", {_W10: "EXCLUDED Employee Benefits Liability Each Employee "
                                                "Annual Aggregate"}, CE_RAW, {})
    assert out == {_W10: g.REASON_COVERAGE_ROW}


@pytest.mark.parametrize("value", [
    "Employee Benefits Liability",                                  # a line, no row
    "Products of a prior operation were excluded by the prior carrier",
    "Tail coverage was purchased on the General Liability",
    "Roofing work excluded from the prior GL policy",
])
def test_an_explanation_with_something_to_say_stays(value):
    assert _refuse(S131, "ACORD_131", {_W10: value}, CE_RAW, {})[0] == {}


# ══ X2: the worksheet's OTHER row is not a factor the worksheet prints ════════

_X2 = ("WorkersCompensationStateCoverage_Other_CoverageDescription_B",
       "WorkersCompensationStateCoverage_Other_ModificationFactor_B",
       "WorkersCompensationStateCoverage_Other_FactoredPremiumAmount_B")


@pytest.mark.parametrize("value", [
    "CO 9812: Employers Liab Incr Limits 1.1000 422.00", "CO 9664: Small Deductible 6.5000 -2,495.00",
    "Experience Modification Factor: 0.92",
])
def test_x2_a_factor_with_its_own_worksheet_row_is_not_other(value):
    m = {_X2[0]: value, _X2[1]: "1.1000", _X2[2]: "422.00"}
    out, _m = _refuse(S130, "ACORD_130", m, CE_RAW, {})
    assert out == {f: g.REASON_COVERAGE_HAS_ITS_OWN_ROW for f in _X2}


@pytest.mark.parametrize("value", [
    "Waiver of Our Right to Recover from Others - blanket", "Certified Risk Management Program credit",
    "Drug-free workplace credit",
])
def test_x2_a_charge_the_worksheet_has_no_row_for_stays(value):
    m = {_X2[0]: value, _X2[1]: "0.0200", _X2[2]: "500.00"}
    assert _refuse(S130, "ACORD_130", m, CE_RAW, {})[0] == {}


def test_the_other_coverage_rows_keep_their_letters_rule():
    # 137: "Medical Payments" names the form's own boxes (unchanged); a coverage
    # the 137 has no row for stays
    assert g.other_row_names_a_coverage_with_its_own_boxes(
        "Vehicle_OtherCoverageDescription_C", S137, {"Vehicle_OtherCoverageDescription_C": "Medical Payments"})
    assert not g.other_row_names_a_coverage_with_its_own_boxes(
        "Vehicle_OtherCoverageDescription_C", S137, {"Vehicle_OtherCoverageDescription_C": "Rental Reimbursement"})


def test_a_role_heading_above_the_contact_block_states_the_role():
    facts = {"contact_name": _doc("Marcus Ellery")}
    raw = ("INSPECTION CONTACT\nName: Marcus Ellery\nPhone: (303) 555-0233\n"
           "ACCOUNTING CONTACT\nName: Priya Raman\n")
    kept = {"NamedInsured_InspectionContact_FullName_A": "Marcus Ellery"}
    assert rg.drop_role_mismatches(dict(kept), S130, facts, raw, set(kept), "ACORD_130") == {}
    wrong = {"NamedInsured_AccountingContact_FullName_A": "Marcus Ellery"}
    out = rg.drop_role_mismatches(dict(wrong), S130, facts, raw, set(wrong), "ACORD_130")
    assert _codes(out) == {"NamedInsured_AccountingContact_FullName_A": rg.R_CONTACT_ROLE}


def test_the_unnamed_other_deductibles_ai_tick_goes_with_it_and_a_rules_tick_stays():
    tick = "GeneralLiability_OtherDeductibleIndicator_A"
    m = _row126(**{_OD: "5,000", tick: "Yes"})
    ps._blank_unnamed_other_rows(m, {_OD, tick}, "ACORD_126")
    assert m[_OD] is None and m[tick] is None
    m = _row126(**{_OD: "5,000", tick: "Yes"})
    ps._blank_unnamed_other_rows(m, {_OD}, "ACORD_126")
    assert m[_OD] is None and m[tick] == "Yes"


def test_a_middle_initial_standing_for_a_printed_middle_name_stays():
    m = {"Driver_GivenName_A": "Mary", "Driver_Surname_A": "Smith", "Driver_OtherGivenNameInitial_A": "M"}
    assert _refuse(S127, "ACORD_127", m, "1 MARY MARGARET SMITH 01/01/1980 CO", {},
                   ai={"Driver_OtherGivenNameInitial_A"})[0] == {}


@pytest.mark.parametrize("value", ["General Liability", "Automobile Liability", "Property"])
def test_a_line_of_business_example_is_a_reading_not_a_borrow(value):
    # loss history printed "CGL" / "AUTO" / "PROP": the line on the form is a reading
    f = "LossHistory_LineOfBusiness_A"
    out, _m = _refuse(S125, "ACORD_125", {f: value}, "LOSS RUN CGL 2024 $0 AUTO 2023 $0 PROP", {})
    assert g.REASON_TOOLTIP_EXAMPLE not in out.values()


def test_a_narrative_document_that_names_no_line_still_states_the_qualifier():
    # an applicant's narrative (no line of its own) says what is subcontracted
    raw = ("ACCOUNT NARRATIVE\nThe insured subcontracts its low-voltage cabling work, about 20% "
           "of revenue, to licensed specialty contractors.")
    f = "GeneralLiabilityLineOfBusiness_TypeOfWorkSubcontractedDescription_A"
    assert _refuse(S126, "ACORD_126", {f: "low-voltage cabling, about 20%"}, raw, {})[0] == {}


def test_a_value_printed_for_both_the_boxs_policy_and_another_is_not_a_person_borrow():
    # the person's contact is ALSO printed by a document (an application): evidence exists
    raw = CE_RAW + "\nAPPLICATION - Contact: Dana Whitfield"
    out, _m = _refuse(S127, "ACORD_127", {"AdditionalInterest_FullName_D": "Dana Whitfield"}, raw, CE_FACTS)
    assert g.REASON_ANOTHER_QUESTION not in out.values()


def test_x2_a_charge_named_with_the_word_premium_is_not_the_total_row():
    m = {_X2[0]: "Blanket waiver of subrogation premium", _X2[1]: "0.0200", _X2[2]: "500.00"}
    assert _refuse(S130, "ACORD_130", m, CE_RAW, {})[0] == {}
