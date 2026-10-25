"""Z41 lane 3 (25 Oct 2026, live run f575160b): AI values borrowed across
roles, and a coverage carried only as a premium. See 25sepChanges.md "Z41
lane 3"."""
import os
import pickle
import copy

import pytest

from services import scoped_evidence as se
from services import ai_answer_guards as g


def _doc(name, text, lines=None, own=None):
    return se.Doc(name, frozenset(lines) if lines else None, text,
                  frozenset(own) if own else None)


PACKAGE_DEC = ("COMMERCIALPROPERTY COVERAGEPART $ 6,275.00\n"
               "CRIMEANDFIDELITY COVERAGEPART $ 500.00\n"
               "EMPLOYMENT-RELATEDPRACTICESLIABILITYCOVERAGEPART $\n")
CYBER_DEC = "Cyber, Privacy and Network Security Liability Limit $1,000,000 Retention $10,000\n"


def _facts(docs, rows=None, **extra):
    f = {"coverage_lines": rows if rows is not None else [
        {"line": "Crime and Fidelity", "premium": "$ 500.00", "_policy_key": "crime#unnumbered"},
        {"line": "Commercial Property", "premium": "$ 6,275.00", "_policy_key": "property#unnumbered"}]}
    f[se.DOCS_KEY] = tuple(docs)
    f.update(extra)
    return f


# ── (a) premium-only line: never asked, stored AI value blank ────────────────
def test_premium_only_crime_section_is_not_asked():
    facts = _facts([_doc("pkg", PACKAGE_DEC, {"property", "crime"}, {"property", "crime"}),
                    _doc("cyber", CYBER_DEC, {"cyber"}, {"cyber"})])
    assert se.premium_only_line(facts, "ACORD_141") == "crime"
    out = se.absent_section_fields("ACORD_141", [
        "CrimeCoverage_EmployeeTheft_LimitAmount_A", "Employee_FullName_A",
        "Auditor_MailingAddress_LineOne_A", "NamedInsured_FullName_A", "Policy_EffectiveDate_A"],
        facts)
    assert out["CrimeCoverage_EmployeeTheft_LimitAmount_A"] == se.REASON_PREMIUM_ONLY
    assert "Employee_FullName_A" in out and "Auditor_MailingAddress_LineOne_A" in out
    assert "NamedInsured_FullName_A" not in out and "Policy_EffectiveDate_A" not in out


@pytest.mark.parametrize("detail", [
    "CRIME COVERAGE EMPLOYEE THEFT LIMIT $250,000 DEDUCTIBLE $1,000\n",
    "Crime and Fidelity - Each Loss $100,000\n",
])
def test_a_printed_crime_detail_keeps_the_section(detail):
    facts = _facts([_doc("pkg", PACKAGE_DEC + detail, {"crime"}, {"crime"})])
    assert se.premium_only_line(facts, "ACORD_141") is None


def test_crime_facts_or_own_policy_keep_the_section():
    docs = [_doc("pkg", PACKAGE_DEC, {"crime"}, {"crime"})]
    assert se.premium_only_line(_facts(docs, crime_employee_theft_limit="250000"), "ACORD_141") is None
    docs2 = docs + [_doc("crime policy", "Crime Policy Declarations", {"crime"}, {"crime"})]
    assert se.premium_only_line(_facts(docs2), "ACORD_141") is None


def test_no_premium_or_no_row_or_no_docs_is_not_judged():
    docs = [_doc("pkg", PACKAGE_DEC, {"crime"}, {"crime"})]
    assert se.premium_only_line(_facts(docs, rows=[]), "ACORD_141") is None
    assert se.premium_only_line(_facts(docs, rows=[{"line": "Crime", "premium": None}]),
                                "ACORD_141") is None
    assert se.premium_only_line({"coverage_lines": []}, "ACORD_141") is None


def test_lines_with_detail_facts_are_never_premium_only():
    docs = [_doc("pkg", "GENERAL LIABILITY $ 9,000.00\n", {"general_liab"}, {"general_liab"})]
    rows = [{"line": "Commercial General Liability", "premium": "$9,000", "_policy_key": "general_liab#x"}]
    assert se.premium_only_line(_facts(docs, rows=rows, gl_each_occurrence="1000000"),
                                "ACORD_126") is None
    # 160 / 138 stay frozen; 125 / 28 / 131 are not a line's section form.
    for fid in ("ACORD_160", "ACORD_125", "ACORD_28", "ACORD_131"):
        assert se.premium_only_line(_facts([_doc("pkg", PACKAGE_DEC, {"crime"})]), fid) is None


def test_stored_ai_value_is_blank_on_a_premium_only_line():
    facts = _facts([_doc("pkg", PACKAGE_DEC, {"property", "crime"}, {"property", "crime"})])
    mapped = {"CrimeCoverage_ComputerFraud_LimitAmount_A": "1,000,000", "NamedInsured_FullName_A": "X"}
    out = se.out_of_scope_values(mapped, {}, facts, "ACORD_141", set(mapped))
    assert out == {"CrimeCoverage_ComputerFraud_LimitAmount_A": se.REASON_PREMIUM_ONLY}


# ── (b) guards on every form ────────────────────────────────────────────────
def test_box_label_as_value():
    tu = ("Enter text: The complete description of the property including merchandise and "
          "stock subject to crime coverage.")
    assert g.box_label_as_value("The complete description of the property", tu)
    assert not g.box_label_as_value("Office furniture and tools", tu)
    assert not g.box_label_as_value("the property", tu)          # too short to judge


def test_drivers_are_not_employees_elsewhere():
    facts = {"auto_drivers": [{"name": "Daniel Mercer"}, {"name": "Alicia Bennett"}]}
    raw = "Driver Name DOB\nDaniel Mercer 04/17/1982\n"
    assert g.person_from_another_schedule("Employee_FullName_A", "Daniel Mercer", facts, raw)
    assert not g.person_from_another_schedule("Driver_FullName_A", "Daniel Mercer", facts, raw)
    # stated in the role -> stands
    assert not g.person_from_another_schedule(
        "Employee_FullName_A", "Daniel Mercer", facts, raw + "Employee: Daniel Mercer, foreman\n")
    facts2 = dict(facts, wc_officers=[{"name": "Daniel Mercer", "title": "President"}])
    assert not g.person_from_another_schedule("Officer_FullName_A", "Daniel Mercer", facts2, raw)
    assert not g.person_from_another_schedule("Employee_FullName_A", "Eric Berger", facts, raw)


def test_office_address_with_an_abbreviated_street():
    raw = ("COMMON POLICY DECLARATIONS\nAMERISURE INSURANCE COMPANY\n26777 HALSTED ROAD\n"
           "FARMINGTON HILLS, MI 48331-3586\n")
    assert g._office_address("26777 Halsted Rd", raw, party_names=["AMERISURE INSURANCE COMPANY"])
    assert not g._office_address("1234 W Colfax Ave", raw + "Insured: 1234 W COLFAX AVE\n",
                                 party_names=["AMERISURE INSURANCE COMPANY"])
    assert g._OTHER_PARTY_ADDRESS_BOX_RE.match("Auditor_MailingAddress_LineOne_A")
    assert not g._OTHER_PARTY_ADDRESS_BOX_RE.match("Insurer_MailingAddress_LineOne_A")


def test_office_address_takes_its_row_parts():
    out = {"Auditor_MailingAddress_LineOne_A":
           f"{g.REASON_ADDRESS_NOT_THIS_PERSONS}: '26777' is printed only as an office's address"}
    mapped = {"Auditor_MailingAddress_StateOrProvinceCode_A": "MI",
              "Auditor_MailingAddress_CityName_A": "Farmington Hills",
              "Auditor_MailingAddress_CityName_B": "Denver"}
    g._office_address_companions(out, mapped, set(mapped))
    assert "Auditor_MailingAddress_StateOrProvinceCode_A" in out
    assert "Auditor_MailingAddress_CityName_A" in out
    assert "Auditor_MailingAddress_CityName_B" not in out


# ── (c) states ──────────────────────────────────────────────────────────────
def test_state_form_takes_only_its_state():
    assert g.state_not_this_forms("Vehicle_NonOwned_StateOrProvinceCode_C", "WY", "ACORD_137_CO")
    assert not g.state_not_this_forms("Vehicle_NonOwned_StateOrProvinceCode_A", "CO", "ACORD_137_CO")
    assert not g.state_not_this_forms("Vehicle_NonOwned_StateOrProvinceCode_C", "WY", "ACORD_127")
    assert not g.state_not_this_forms("NamedInsured_MailingAddress_StateOrProvinceCode_A", "WY",
                                      "ACORD_137_CO")


def test_licence_state_is_not_a_mailing_state():
    mapped = {"Driver_LicensedStateOrProvinceCode_C": "WY"}
    assert g.licence_state_as_mailing_state("Driver_MailingAddress_StateOrProvinceCode_C", "WY", mapped)
    mapped2 = dict(mapped, Driver_MailingAddress_CityName_C="Cheyenne")
    assert not g.licence_state_as_mailing_state("Driver_MailingAddress_StateOrProvinceCode_C", "WY",
                                                mapped2)
    assert not g.licence_state_as_mailing_state("Driver_MailingAddress_StateOrProvinceCode_C", "CO",
                                                mapped)


# ── (d) a person's answer is evidence only for its own question ─────────────
def test_person_answer_for_another_question():
    said = {"roof_year"}
    assert g.person_answer_for_another_question("BuildingImprovement_WiringYear_A", "2018", said,
                                                "Enter year: wiring", "Built 2005\n")
    assert not g.person_answer_for_another_question("BuildingImprovement_WiringYear_A", "2018", said,
                                                    "Enter year:", "WIRING UPDATED 2018\n")
    assert not g.person_answer_for_another_question("BuildingImprovement_RoofingYear_A", "2018",
                                                    {"roofing_year"}, "Enter year:", "")
    # a long amount is the meaning rules' question, not this one
    assert not g.person_answer_for_another_question("CrimeInformation_AnnualGrossReceiptsAmount_A",
                                                    "3200000", {"total_revenue"}, "", "x\n")
    # the box's own words name the fact
    assert not g.person_answer_for_another_question(
        "EmployeeClass_OtherOfficersAndEmployees_EmployeeCount_A", "28", {"num_employees"}, "", "x\n")


# ── (e) ACORD 28 ────────────────────────────────────────────────────────────
def test_another_lines_form_on_the_property_form():
    mapped = {"FormEndorsement_CopyrightOwnerCode_A": "CA", "FormEndorsement_FormDate_A": "09/11"}
    assert g.form_from_another_line("FormEndorsement_FormDate_A", mapped, "ACORD_28")
    mapped2 = {"FormEndorsement_CopyrightOwnerCode_A": "CP"}
    assert not g.form_from_another_line("FormEndorsement_CopyrightOwnerCode_A", mapped2, "ACORD_28")
    mapped3 = {"FormEndorsement_CopyrightOwnerCode_A": "IL"}
    assert not g.form_from_another_line("FormEndorsement_CopyrightOwnerCode_A", mapped3, "ACORD_28")


def test_deductible_needs_its_coverage_label():
    raw = ("WINDSTORM OR HAIL DEDUCTIBLE: 2%\nTHEFT CAUSE OF LOSS DEDUCTIBLE: $5,000\n"
           "COVERAGE: BUILDING-EQUIPMENT BREAKDOWN\nLIMIT DEDUCTIBLE\nINCLUDED $5,000\n")
    f = "CommercialPropertyCoverage_NamedWindstorm_DeductibleAmount_A"
    assert g.amount_not_for_this_coverage(f, "$5,000", raw)
    assert not g.amount_not_for_this_coverage(
        "CommercialPropertyCoverage_EquipmentBreakdown_DeductibleAmount_A", "$5,000", raw)
    assert not g.amount_not_for_this_coverage(f, "$5,000", "NAMED WINDSTORM DEDUCTIBLE $5,000\n")
    assert not g.amount_not_for_this_coverage("CommercialPropertyCoverage_Building_LimitAmount_A",
                                              "$5,000", raw)


def test_issue_date_is_not_a_prior_evidence_date():
    raw = "POLICY PERIOD: FROM 01/01/2025 TO 01/01/2026\nIssue Date: 01/16/2025\n"
    tu = ("Enter date: The date the prior Evidence of Property Insurance, which this form "
          "replaces, was issued to this additional interest.")
    assert g.issue_date_as_value("EvidenceOfProperty_PriorEvidenceDate_A", "01/16/2025", tu, raw)
    assert not g.issue_date_as_value("EvidenceOfProperty_PriorEvidenceDate_A", "01/01/2025", tu, raw)
    assert not g.issue_date_as_value("Policy_IssueDate_A", "01/16/2025", "", raw)


def test_141_is_judged_again_160_stays_frozen():
    assert "ACORD_141" not in g._FROZEN_FORMS and "ACORD_160" in g._FROZEN_FORMS
    assert "ACORD_141" not in se._NOT_JUDGED_FORMS and "ACORD_160" in se._NOT_JUDGED_FORMS


# ── The owner's stored package (skipped where the snapshot is absent) ───────
_SNAP = os.environ.get("Z41_SNAPSHOT", "/private/tmp/claude-501/-Users-vinaysharma-Downloads-"
                       "Primble-16thsep/427f82bb-424b-4678-bf06-9112a9013561/scratchpad/live26/"
                       "f575_forms.pkl")


@pytest.mark.skipif(not os.path.exists(_SNAP), reason="live snapshot not on this machine")
def test_live_snapshot_f575():
    d = pickle.load(open(_SNAP, "rb"))
    base = {**d["facts"], **d["flags"]}
    raw = "\n\n".join(x.get("text") or "" for x in d["docs"] if not x.get("excluded"))
    refused = {}
    for fid, form in d["generated_forms"].items():
        facts = dict(base, _form_id=fid.split("__")[0])
        se.attach_documents(facts, d["docs"])
        m = copy.deepcopy(form["mapped"])
        ai = {f for f, lab in form["confidence"].items()
              if lab in ("ai_verified", "low_confidence") and m.get(f) not in (None, "")}
        r = g.refuse_non_answers(m, form["schema"], facts, raw, set(ai), fid)
        r.update(se.out_of_scope_values(m, form["schema"], facts, fid, set(ai) - set(r)))
        refused[fid] = r
    r141 = refused["ACORD_141"]
    for f in ("CrimeCoverage_ComputerFraud_LimitAmount_A", "CrimeCoverage_EmployeeTheft_DeductibleAmount_A",
              "Employee_FullName_A", "Auditor_MailingAddress_LineOne_A", "EmployeeBenefitPlan_PlanName_A",
              "CrimeInformation_PropertyDescription_A", "SafeVault_ClassCode_A",
              "CrimeInformation_BusinessHoursStartTime_A", "MessengerProtection_ArmouredVehicleCount_A"):
        assert f in r141, f
    assert "Policy_EffectiveDate_A" not in r141
    assert set(refused["ACORD_127"]) == {f"Driver_MailingAddress_StateOrProvinceCode_{r}" for r in "CFI"}
    assert all(v.startswith(g.REASON_STATE_NOT_THIS_FORMS) for v in refused["ACORD_137_CO"].values())
    assert "Vehicle_NonOwned_StateOrProvinceCode_A" not in refused["ACORD_137_CO"]
    assert set(refused["ACORD_140"]) == {"BuildingImprovement_WiringYear_A"}
    assert {"FormEndorsement_CopyrightOwnerCode_A", "FormEndorsement_FormDate_A",
            "CommercialPropertyCoverage_NamedWindstorm_DeductibleAmount_A",
            "CommercialPropertyCoverage_BuildingOrdinanceOrLaw_UndamagedPortionBuildingDeductibleAmount_A",
            "EvidenceOfProperty_PriorEvidenceDate_A",
            "CommercialPropertyCoverage_BusinessIncomeOrRentalValue_ActualLossSustainedMonthCount_A",
            } == set(refused["ACORD_28"])
    # 25 Oct (live 85e51d02): a loss-run spreadsheet ROW as the 126's install /
    # service explanation is no explanation (ai_answer_guards.is_data_table_row).
    assert set(refused["ACORD_126"]) == {"GeneralLiabilityLineOfBusiness_ApplicantInstallServiceProductsExplanation_A"}
    for fid in ("ACORD_130", "ACORD_131", "ACORD_131__excess", "ACORD_101"):
        assert refused[fid] == {}, fid


# ── Tooltip example echoed (ACORD 125 contact type "Claims") ────────────────
_CONTACT = "NamedInsured_Contact_ContactDescription_A"
_CONTACT_TU = "Enter text: The type of contact being described (e.g. accounting, claims, etc.). "


def test_tooltip_example_printed_elsewhere_is_not_stated_for_the_contact():
    raw = "LOSS RUN\nClaims reported: 3\nClaims made coverage\n"
    folded = g._ps()._normalize_for_search(raw)
    assert g.unstated_tooltip_example("Claims", _CONTACT_TU, folded, _CONTACT, raw)
    raw2 = raw + "Claims Contact: Jane Doe 303-555-0100\n"
    folded2 = g._ps()._normalize_for_search(raw2)
    assert not g.unstated_tooltip_example("Claims", _CONTACT_TU, folded2, _CONTACT, raw2)
    # not an example -> not this rule
    assert not g.unstated_tooltip_example("Owner", _CONTACT_TU, folded, _CONTACT, raw)


def test_tooltip_example_on_the_live_snapshot():
    if not os.path.exists(_SNAP):
        pytest.skip("live snapshot not on this machine")
    d = pickle.load(open(_SNAP, "rb"))
    form = d["generated_forms"]["ACORD_125"]
    raw = "\n\n".join(x.get("text") or "" for x in d["docs"] if not x.get("excluded"))
    facts = dict({**d["facts"], **d["flags"]}, _form_id="ACORD_125")
    m = copy.deepcopy(form["mapped"])
    ai = {f for f, lab in form["confidence"].items()
          if lab in ("ai_verified", "low_confidence") and m.get(f) not in (None, "")}
    r = g.refuse_non_answers(m, form["schema"], facts, raw, set(ai), "ACORD_125")
    assert set(r) == {_CONTACT}
    assert r[_CONTACT].startswith(g.REASON_TOOLTIP_EXAMPLE)
