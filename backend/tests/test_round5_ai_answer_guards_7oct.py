"""Round 5 (7 Oct 2026): AI gap-fill answers that are not answers.

services/ai_answer_guards.py - PROBLEMS.md classes #2 (a party's name as a
description), #3 (the question read back, a one-word operations description,
a rating class as operations), #4 (a form / endorsement title), #5 (a
cross-reference phrase) and the option-list half of #11. Every live value
below is the owner's 7 Oct run (session b248c194); every look-alike is a value
the 690-session corpus holds and the rules must keep.
"""
import json
import re
from pathlib import Path

import pytest

from services import ai_answer_guards as g
from services import needs_attention as na
from services import pdf_service as ps

BACKEND = Path(__file__).resolve().parents[1]
SCHEMA_FILES = sorted((BACKEND / "forms_schemas").glob("ACORD_*_schema.json"))


def _schema(form_id):
    return json.loads((BACKEND / "forms_schemas" / f"{form_id}_schema.json").read_text())


S125, S126, S127, S130, S131, S140 = (_schema(f) for f in (
    "ACORD_125", "ACORD_126", "ACORD_127", "ACORD_130", "ACORD_131", "ACORD_140"))
S25 = _schema("ACORD_25")

_WC_CLASSES = [
    {"code": "5190", "description": "State Act - Electrical Wiring-Within Buildings & Drivers.",
     "state": "CO", "payroll": "2,000,000"},
    {"code": "8810", "description": "State Act - Clerical Office Employees NOC.", "state": "CO"},
]
_FACTS = {"applicant_name": "Choice Electric LLC", "carrier_name": "AMERISURE INSURANCE COMPANY",
          "producer_name": "Astrea It services", "wc_class_codes": _WC_CLASSES}


def _codes(out):
    return {f: why.split(":", 1)[0] for f, why in out.items()}


# ══ (a) a cross-reference is not a value ══════════════════════════════════════

@pytest.mark.parametrize("value", [
    "SEE SCHEDULE", "$SEE SCHEDULE", "SEE SCHEDULE FOR DED .",
    "SEE ITEM FOUR FOR HIRED OR BORROWED AUTOS",
    "SEE ITEM FOUR FOR HIRED OR BORROWED AUTOS; SEE ITEM FIVE FOR NON-OWNERSHIP COVERED AUTOS",
    "SEE ITEM FOUR FOR HIRED OR BORROWED AUTOS / SEE ITEM FIVE FOR NON-OWNE",
    "See Section Declarations To: 07/15/2026", "See attached schedule for applicable amounts.",
    "SEE ATTACHED SCHEDULE FOR LIMITS AND DESCRIPTION OF COVERAGES", "SEE ITEM SIX",
    "Refer to the declarations", "As per declarations", "Per schedule on file",
    "Listed on schedule A", "As shown on the attached schedule", "Please see remarks",
])
def test_a_pointer_to_another_page_is_a_cross_reference(value):
    assert g.is_cross_reference(value)


@pytest.mark.parametrize("value", [
    # corpus look-alikes: a basis, a description, a name, a sentence with data
    "Per claim $2,500", "PER OCCURRENCE", "Per policy", "Per item", "PER CLAIM",
    "SCHEDULED EQUIPMENT FINANCED UNDER MASTER LEASE 4471-B", "SCHEDULED LOCATION 1",
    "See's Candies", "Attached garage", "Included in BPP limit", "Refer to underwriter",
    "See schedule; deductible $1,000", "Hired and non-owned autos - see item four",
    "Schedule of underlying insurance included with this submission: Yes", "",
    "Seed company", "Central station, certificate on file",
])
def test_look_alikes_are_not_cross_references(value):
    assert not g.is_cross_reference(value)


def test_only_a_box_about_an_attachment_takes_a_reference():
    assert g._box_asks_for_a_reference(
        "CommercialPolicy_Attachment_OtherDescription_A",
        S125["CommercialPolicy_Attachment_OtherDescription_A"]["tu"])
    for f in ("Alarm_Burglar_AlarmDescription_A", "Construction_RoofMaterialCode_A",
              "BuildingExposure_FrontDescription_A"):
        assert not g._box_asks_for_a_reference(f, S140[f]["tu"]), f
    # ACORD 127's remarks say "ACORD 101 ... may be attached" - an instruction, not its subject
    assert not g._box_asks_for_a_reference(
        "AccidentConviction_TrafficViolationDescription_A",
        S127["AccidentConviction_TrafficViolationDescription_A"]["tu"])


def test_the_live_140_pointers_are_refused_and_a_rule_value_is_never_touched():
    boxes = ("Alarm_Burglar_AlarmDescription_A", "BuildingExposure_FrontDescription_A",
             "BuildingSecurity_GuardWatchmenOtherDescription_A",
             "Construction_BuildingCodeEffectivenessGradeCode_A",
             "Construction_RoofMaterialCode_A", "Construction_RoofMaterialCode_B")
    mapped = {f: "SEE SCHEDULE" for f in boxes}
    mapped["Construction_ConstructionCode_A"] = "SEE SCHEDULE"          # a rule's value
    out = g.refuse_non_answers(mapped, S140, dict(_FACTS), "", set(boxes), "ACORD_140")
    assert _codes(out) == {f: g.REASON_CROSS_REFERENCE for f in boxes}
    assert all(mapped[f] is None for f in boxes)
    assert mapped["Construction_ConstructionCode_A"] == "SEE SCHEDULE"


# ══ (b) a party's name is not a description ═══════════════════════════════════

def test_the_applicants_name_as_its_operations_is_refused_on_125_and_130():
    for schema, fid in ((S125, "ACORD_125"), (S130, "ACORD_130")):
        mapped = {"CommercialPolicy_OperationsDescription_A": "CHOICE ELECTRIC LLC"}
        out = g.refuse_non_answers(mapped, schema, dict(_FACTS), "", set(mapped), fid)
        assert _codes(out) == {"CommercialPolicy_OperationsDescription_A": g.REASON_PARTY_NAME}
        assert mapped["CommercialPolicy_OperationsDescription_A"] is None


def test_a_party_without_its_legal_form_glued_or_with_its_address_is_still_a_name():
    facts = {"applicant_name": "Cascade Metal Works LLC",
             "certificate_holder": "Cascade Terminal Authority, 900 Alexander Ave, Tacoma, WA 98421",
             "contact_name": "Vinay S", "certificate_holder_2": "x"}
    parties = g._party_names(facts)
    assert g._is_party_name("Cascade Metal Works", parties)
    assert g._is_party_name("CASCADEMETALWORKSLLC", parties)
    assert g._is_party_name("Cascade Terminal Authority, 900 Alexander Ave, Tacoma, WA 98421", parties)
    assert g._is_party_name("Vinay S", parties)


@pytest.mark.parametrize("value", [
    # 27 AI sentences in the corpus open with a party's name - each a real description
    "Ironclad Fabrication & Welding LLC is a metal fabrication and welding contractor.",
    "Choice Electric LLC performs commercial electrical installation in Denver.",
    "Electric", "Roofing", "Ironclad", "",
])
def test_a_sentence_about_a_party_or_a_partial_name_is_not_its_name(value):
    assert not g._is_party_name(value, g._party_names({"applicant_name": "Choice Electric LLC",
                                                       "dba_name": "Ironclad Fab"}))


def test_a_box_that_asks_for_a_name_keeps_one():
    # ACORD 125's product box "may also be used to name the subsidiary company"
    mapped = {"Insurer_ProductDescription_A": "AMERISURE INSURANCE COMPANY"}
    out = g.refuse_non_answers(mapped, S125, dict(_FACTS), "", set(mapped), "ACORD_125")
    assert out == {} and mapped["Insurer_ProductDescription_A"] == "AMERISURE INSURANCE COMPANY"


def test_a_name_box_is_never_judged_as_a_description():
    mapped = {"NamedInsured_FullName_A": "CHOICE ELECTRIC LLC",
              "AdditionalInterest_FullName_A": "AMERISURE INSURANCE COMPANY"}
    out = g.refuse_non_answers(mapped, S125, dict(_FACTS), "", set(mapped), "ACORD_125")
    assert out == {}


# ══ (c) the question read back, one word, a rating class ═════════════════════

def test_service_explaining_install_service_or_demonstrate_is_an_echo():
    f = "GeneralLiabilityLineOfBusiness_ApplicantInstallServiceProductsExplanation_A"
    assert g.echoes_its_question(f, "service", S126)
    assert g.echoes_its_question(f, "Installation and service", S126)
    assert not g.echoes_its_question(f, "Installs electrical panels and lighting", S126)
    assert not g.echoes_its_question(f, "Installation of 3 generators", S126)    # digits are content


def test_an_example_answer_is_never_an_echo_but_the_definition_is():
    f = "NamedInsured_Contact_ContactDescription_A"
    assert g.echoes_its_question(f, "Contact", S125)                  # 47 corpus boxes
    assert not g.echoes_its_question(f, "Accounting", S125)           # ACORD's own example
    assert not g.echoes_its_question(f, "Claims", S125)
    sub = "CommercialStructure_Building_SublocationDescription_A"
    assert not g.echoes_its_question(sub, "Building", S140)           # "An example might be"
    assert not g.echoes_its_question(sub, "Location 2 - Building 1", S140)
    assert g.echoes_its_question("Subsidiary_ParentSubsidiaryRelationshipDescription_A",
                                 "parent company", S125)


@pytest.mark.parametrize("path", SCHEMA_FILES, ids=lambda p: p.name[:-12])
def test_no_example_acord_names_is_ever_an_echo(path):
    """The sweep: every example answer a narrative box's own tooltip lists is
    a valid answer on ACORD's authority - none may read as an echo."""
    schema = json.loads(path.read_text())
    for field, meta in schema.items():
        if (meta or {}).get("ft") == "/Btn" or not g._is_narrative_box(field):
            continue
        for opt in g.tooltip_options((meta or {}).get("tu") or ""):
            assert not g.echoes_its_question(field, opt, schema), (field, opt)


def test_a_one_word_operations_description_is_not_a_description():
    f = "BusinessInformation_OperationsDescription_A"
    assert g.is_one_word_operations(f, "service", S131)
    assert not g.is_one_word_operations(f, "Electrical contractor - commercial wiring", S131)
    assert not g.is_one_word_operations("GeneralLiabilityLineOfBusiness_ApplicantInstallServiceProductsExplanation_A",
                                        "service", S126)             # not an operations box


def test_a_rating_class_with_its_schedule_prefix_is_not_an_operations_description():
    words = g._classification_wordings(_FACTS)
    f = "BusinessInformation_OperationsDescription_B"
    assert g.is_classification_wording(f, "State Act - Electrical Wiring-Within Buildings & Drivers.", S131, words)
    assert g.is_classification_wording(f, "Electrical Wiring-Within Buildings & Drivers", S131, words)
    assert g.is_classification_wording(f, "5190 - Electrical Wiring-Within Buildings & Drivers.", S131, words)
    assert not g.is_classification_wording(
        f, "Commercial electrical contractor - wiring within buildings", S131, words)
    # ACORD 130's rate-class box ASKS for the classification wording
    assert not g.is_classification_wording(
        "WorkersCompensation_RateClass_DutiesDescription_A",
        "State Act - Electrical Wiring-Within Buildings & Drivers.", S130, words)


def test_the_live_131_operations_rows_are_refused_each_with_its_own_reason():
    mapped = {"BusinessInformation_OperationsDescription_A": "service",
              "BusinessInformation_OperationsDescription_B":
                  "State Act - Electrical Wiring-Within Buildings & Drivers."}
    out = g.refuse_non_answers(mapped, S131, dict(_FACTS), "", set(mapped), "ACORD_131")
    assert _codes(out) == {"BusinessInformation_OperationsDescription_A": g.REASON_ONE_WORD_OPERATIONS,
                           "BusinessInformation_OperationsDescription_B": g.REASON_CLASSIFICATION}


# ══ (d) a form / endorsement title ════════════════════════════════════════════

_FORMS_SCHEDULE = (
    "FORMS AND ENDORSEMENTS\n"
    "CA 00 01 10 13 BUSINESS AUTO COVERAGE FORM\n"
    "CA 71 65 09 11 DESIGNATED INSURED-PRIMARY NON-CONTRIB COV WHEN REQ BY INSURED CONTRACT OR CERT\n"
    "CG 72 76 11 16 Limited Pollution Coverage - Work Sites\n"
    "Limited Pollution Coverage - Work Sites $150\n"
    "CA7312(11-15) Rental Vehicle Extensions\n"
    "ACME HOLDINGS LLC NY 10001\n"
)
_TITLE = "DESIGNATED INSURED-PRIMARY NON-CONTRIB COV WHEN REQ BY INSURED CONTRACT OR CERT"


def test_a_value_printed_only_beside_its_form_number_is_a_title():
    assert g.printed_only_as_form_title(_TITLE, _FORMS_SCHEDULE)
    assert g.printed_only_as_form_title("Rental Vehicle Extensions", _FORMS_SCHEDULE)
    # also printed as a priced coverage line - a coverage, left to other guards
    assert not g.printed_only_as_form_title("Limited Pollution Coverage - Work Sites", _FORMS_SCHEDULE)
    # a state and ZIP is not a form number (no edition)
    assert not g.printed_only_as_form_title("ACME HOLDINGS LLC", _FORMS_SCHEDULE)
    # printed in running text too
    assert not g.printed_only_as_form_title(
        "Business Auto Coverage Form", _FORMS_SCHEDULE + "Coverage under the Business Auto Coverage Form applies.\n")
    assert not g.printed_only_as_form_title("Two words", _FORMS_SCHEDULE)
    assert not g.printed_only_as_form_title(_TITLE, "")


@pytest.mark.parametrize("norm,ok", [
    ("ca 71 65 09 11", True), ("cg 70 22a 04 17", True), ("il ds 71 05 02 08", True),
    ("ca7312 11 15", True), ("cm7001a 09 97", True), ("wc 00 00 00 c", True),
    ("form ca 00 01 10 13", True), ("ny 10001", False), ("co 80221", False),
    ("page 1 of 2", False), ("ca 71 65", False),
])
def test_a_form_number_is_read_by_its_edition(norm, ok):
    assert bool(g._DESIGNATOR_NORM_RE.match(norm)) is ok


def test_only_a_box_that_does_not_take_titles_refuses_one():
    assert not g._box_takes_a_title("UnderlyingCoverage_InformationDescription_A",
                                    S131["UnderlyingCoverage_InformationDescription_A"]["tu"])
    for schema, f in ((S140, "CommercialProperty_Premises_FormsAndConditions_A"),
                      (S125, "Policy_LineOfBusiness_OtherLineOfBusinessDescription_A"),
                      (S127, "CommercialVehicleLineOfBusiness_RemarkText_A"),
                      (S25, "GeneralLiability_OtherCoverageDescription_A"),
                      (S131, "UnderlyingPolicy_OtherPolicy_PolicyTypeDescription_A")):
        assert g._box_takes_a_title(f, schema[f]["tu"]), f


def test_the_live_131_endorsement_title_is_refused():
    f = "UnderlyingCoverage_InformationDescription_A"
    mapped = {f: _TITLE}
    out = g.refuse_non_answers(mapped, S131, dict(_FACTS), _FORMS_SCHEDULE, {f}, "ACORD_131")
    assert _codes(out) == {f: g.REASON_FORM_TITLE}
    keep = {"CommercialProperty_Premises_FormsAndConditions_A": _TITLE}
    assert g.refuse_non_answers(keep, S140, dict(_FACTS), _FORMS_SCHEDULE, set(keep), "ACORD_140") == {}


# ══ (e) the tooltip's option list, copied in order ═══════════════════════════

def test_option_lists_are_read_off_the_tooltip():
    tu = lambda s, f: s[f]["tu"]                                      # noqa: E731
    assert g.tooltip_options(tu(S140, "CommercialCoverage_Summary_BlanketTypeDescription_A")) == [
        "building", "contents", "combined building and contents"]
    assert g.tooltip_options(tu(S140, "Alarm_Burglar_AlarmDescription_A")) == [
        "safe", "premises", "perimeter", "ultrasonic"]
    assert g.tooltip_options(tu(S140, "BuildingFireProtection_Alarm_ProtectionDescription_A")) == [
        "sprinklers", "standpipes", "chemical systems"]
    assert g.tooltip_options(tu(S140, "CommercialProperty_Premises_DeductibleTypeCode_A")) == [
        "percent", "dollars", "number of days"]
    assert g.tooltip_options(tu(S140, "Construction_RoofMaterialCode_A"))[:2] == ["composition", "metal"]
    assert g.tooltip_options(tu(S127, "Vehicle_ManufacturersName_A")) == []     # "Ford, Chevy": two
    assert g.tooltip_options(tu(S125, "NamedInsured_Contact_ContactDescription_A")) == []


def test_the_live_blanket_rows_are_a_dump_and_one_example_is_an_answer():
    base = "CommercialCoverage_Summary_BlanketTypeDescription_"
    mapped = {base + "A": "Building", base + "B": "Contents", base + "C": "Combined Building and Contents"}
    out = g.refuse_non_answers(dict(mapped), S140, dict(_FACTS), "", set(mapped), "ACORD_140")
    assert _codes(out) == {f: g.REASON_OPTION_LIST for f in mapped}
    one = {base + "A": "Building"}
    assert g.refuse_non_answers(dict(one), S140, dict(_FACTS), "", set(one), "ACORD_140") == {}
    two_real = {base + "A": "Building", base + "B": "Business Personal Property"}
    assert g.refuse_non_answers(dict(two_real), S140, dict(_FACTS), "", set(two_real), "ACORD_140") == {}
    # a rule's row breaks the run: the AI did not copy the list
    out = g.refuse_non_answers(dict(mapped), S140, dict(_FACTS), "", {base + "A", base + "B"}, "ACORD_140")
    assert out == {}


def test_a_two_row_box_filled_with_two_of_its_examples_is_a_dump():
    a, b = "Alarm_Burglar_AlarmDescription_A", "Alarm_Burglar_AlarmDescription_B"
    for vals in (("safe", "premises"), ("premises", "perimeter")):
        mapped = {a: vals[0], b: vals[1]}
        out = g.refuse_non_answers(mapped, S140, dict(_FACTS), "", {a, b}, "ACORD_140")
        assert _codes(out) == {a: g.REASON_OPTION_LIST, b: g.REASON_OPTION_LIST}
    mapped = {a: "premises", b: "safe"}                              # out of order
    assert g.refuse_non_answers(mapped, S140, dict(_FACTS), "", {a, b}, "ACORD_140") == {}
    one = {"BuildingFireProtection_Alarm_ProtectionDescription_A": "sprinklers, standpipes, chemical systems"}
    assert _codes(g.refuse_non_answers(one, S140, dict(_FACTS), "", set(one), "ACORD_140")) == {
        "BuildingFireProtection_Alarm_ProtectionDescription_A": g.REASON_OPTION_LIST}


# ══ scope: AI values only, never the gate's boxes, never a frozen form ════════

def test_scope_is_ai_text_values_only():
    mapped = {"CommercialPolicy_OperationsDescription_A": "CHOICE ELECTRIC LLC",
              "CommercialPolicy_Question_AAHCode_A": "Y"}
    assert g.refuse_non_answers(dict(mapped), S125, dict(_FACTS), "", set(), "ACORD_125") == {}
    assert g.refuse_non_answers(dict(mapped), S125, dict(_FACTS), "", None, "ACORD_125") == {}
    out = g.refuse_non_answers(dict(mapped), S125, dict(_FACTS), "", set(mapped), "ACORD_125")
    assert "CommercialPolicy_Question_AAHCode_A" not in out


def test_frozen_forms_are_untouched():
    s160 = _schema("ACORD_160")
    f = "BusinessInformation_OperationsDescription_A"
    mapped = {f: "service"}
    assert g.refuse_non_answers(mapped, s160, dict(_FACTS), "", {f}, "ACORD_160") == {}
    assert g.explanation_non_answer(f, "service", s160, {"_form_id": "ACORD_160"}) is None


def test_an_explanation_under_a_rule_stamped_yes_is_left_alone():
    q = "GeneralLiabilityLineOfBusiness_Question_AAJCode_A"
    f = "GeneralLiabilityLineOfBusiness_ApplicantInstallServiceProductsExplanation_A"
    mapped = {q: "Y", f: "service"}
    assert g.refuse_non_answers(dict(mapped), S126, dict(_FACTS), "", {f}, "ACORD_126") == {}
    assert _codes(g.refuse_non_answers(dict(mapped), S126, dict(_FACTS), "", {q, f}, "ACORD_126")) == {
        f: g.REASON_ECHO}


def test_an_other_row_whose_name_is_refused_takes_its_ai_amount_and_tick_with_it():
    d, a, t = ("GeneralLiability_OtherDeductibleDescription_A", "GeneralLiability_OtherDeductibleAmount_A",
               "GeneralLiability_OtherDeductibleIndicator_A")
    mapped = {d: "Deductible", a: "1,000", t: "Y"}
    out = g.refuse_non_answers(mapped, S126, dict(_FACTS), "", {d, a, t}, "ACORD_126")
    assert _codes(out) == {d: g.REASON_ECHO, a: g.REASON_ROW_NAME_REFUSED, t: g.REASON_ROW_NAME_REFUSED}
    # a rule's amount stays
    mapped = {d: "Deductible", a: "1,000"}
    assert _codes(g.refuse_non_answers(mapped, S126, dict(_FACTS), "", {d}, "ACORD_126")) == {d: g.REASON_ECHO}
    assert mapped[a] == "1,000"


def test_an_other_deductible_naming_a_printed_row_is_left_to_its_own_door():
    """`_misfiled_other_deductibles` moves the amount to the PROPERTY DAMAGE
    row or clears the whole OTHER row; refusing the name first stranded the
    amount (live run 7 pin)."""
    d, a = "GeneralLiability_OtherDeductibleDescription_A", "GeneralLiability_OtherDeductibleAmount_A"
    mapped = {d: "Property Damage Deductible", a: "1,000"}
    assert g.refuse_non_answers(mapped, S126, dict(_FACTS), "", {d, a}, "ACORD_126") == {}


def test_bad_input_never_raises():
    assert g.refuse_non_answers(None, S125, {}, "", {"x"}) == {}
    assert g.refuse_non_answers({"x": "SEE SCHEDULE"}, None, None, None, {"x"}) == {}
    assert g.explanation_non_answer(None, "x", S125, {}) is None
    assert g.explanation_non_answer("NotAField", "SEE SCHEDULE", S125, {}) is None


# ══ the evidence gate: a non-answer is not evidence ═══════════════════════════

@pytest.fixture
def no_judge(monkeypatch):
    monkeypatch.setattr(ps, "_EVIDENCE_JUDGE_ENABLED", False)


def _stamp(schema, form_id, values, raw_text, grounding=None, facts=None):
    report = []
    mapped, conf = ps.map_facts_to_form(
        dict(facts or _FACTS), schema, form_id=form_id, raw_text=raw_text,
        pre_filled_gpt={"filled_values": dict(values), "raw_text_fields": set(),
                        "question_grounding": dict(grounding or {})},
        guard_report=report)
    return mapped, conf, {r["field"]: r for r in report}


_Q = "GeneralLiabilityLineOfBusiness_Question_AAJCode_A"
_EXP = "GeneralLiabilityLineOfBusiness_ApplicantInstallServiceProductsExplanation_A"
_QUOTE = "The applicant installs and services electrical equipment for its commercial customers."
_RAW_126 = ("Choice Electric LLC electrical contractor. Products service and repair. " + _QUOTE
            + " Policy period 01/01/2025 to 01/01/2026.")


def test_a_yes_that_stood_only_on_its_echo_falls_with_it(no_judge):
    mapped, _c, report = _stamp(S126, "ACORD_126", {_Q: "Y", _EXP: "service"}, _RAW_126)
    assert not str(mapped.get(_Q) or "").strip()
    assert not str(mapped.get(_EXP) or "").strip()
    assert report[_EXP]["reason"] == g.REASON_ECHO
    assert report[_Q]["reason"] == g.REASON_ECHO


def test_a_yes_with_its_own_quote_keeps_it_and_the_quote_replaces_the_echo(no_judge):
    mapped, _c, _r = _stamp(S126, "ACORD_126", {_Q: "Y", _EXP: "service"}, _RAW_126, {_Q: _QUOTE})
    assert str(mapped.get(_Q)).strip().upper() in ("Y", "YES")
    assert mapped.get(_EXP) == _QUOTE


def test_a_stranded_pointer_never_ticks_its_other_box(no_judge):
    ind, desc = "BuildingSecurity_GuardWatchmenOtherIndicator_A", "BuildingSecurity_GuardWatchmenOtherDescription_A"
    raw = "DEDUCTIBLE $500. Exceptions: SEE SCHEDULE\nGuards make rounds every hour."
    # The stranded description: Pass B used to tick OTHER from it (live CE 140).
    mapped, _c, report = _stamp(S140, "ACORD_140", {desc: "SEE SCHEDULE"}, raw)
    assert not str(mapped.get(desc) or "").strip()
    assert str(mapped.get(ind) or "").strip().lower() not in ("y", "yes", "on", "true", "1")
    assert report[desc]["reason"] == g.REASON_CROSS_REFERENCE
    # The AI ticked it too: the gate's own artifact check takes both, as before.
    mapped, _c, _r = _stamp(S140, "ACORD_140", {desc: "SEE SCHEDULE", ind: "Y"}, raw)
    assert not str(mapped.get(desc) or "").strip()
    assert str(mapped.get(ind) or "").strip().lower() not in ("y", "yes", "on", "true", "1")


def test_the_guard_report_names_each_rule_and_the_review_says_why(no_judge):
    values = {"CommercialPolicy_OperationsDescription_A": "CHOICE ELECTRIC LLC"}
    mapped, _c, report = _stamp(S125, "ACORD_125", values, "CHOICE ELECTRIC LLC declarations")
    row = report["CommercialPolicy_OperationsDescription_A"]
    assert row["reason"] == g.REASON_PARTY_NAME
    sentence, quotable = na.held_back(S125, row["field"], row["removed_value"], dict(_FACTS),
                                      row.get("kind"), row.get("in_documents"), reason=row["reason"])
    assert sentence == g.held_back_sentence(g.REASON_PARTY_NAME) and quotable is False
    assert na.held_back_reason(S125, row["field"], row["removed_value"], dict(_FACTS),
                               row.get("kind"), row.get("in_documents"), reason=row["reason"]) == sentence


def test_every_reason_has_a_plain_sentence_and_old_callers_are_unchanged():
    for code in g.REASON_CODES:
        s = g.held_back_sentence(code)
        assert s and "—" not in s and s.endswith(".")
        assert g.held_back_sentence(code + ": detail") == s
    assert g.held_back_sentence("REPEATS_ROW_A") is None and g.held_back_sentence(None) is None
    # a reason this module does not own falls through to the old reading
    a = na.held_back(S125, "NamedInsured_SICCode_A", "7383", {}, None, None)
    b = na.held_back(S125, "NamedInsured_SICCode_A", "7383", {}, None, None, reason="REPEATS_ROW_A")
    assert a == b
