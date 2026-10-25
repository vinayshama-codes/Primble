"""Z42 review B (25 Oct 2026): adversarial review of the Z41 lane 3 rules - the
edge cases that would have blanked a CORRECT value. See 25sepChanges.md
"Z42 review B"."""
from services import scoped_evidence as se
from services import ai_answer_guards as g


def _doc(name, text, own=None):
    return se.Doc(name, None, text, frozenset(own) if own else None)


PKG = ("COMMERCIALPROPERTY COVERAGEPART $ 6,275.00\n"
       "CRIMEANDFIDELITY COVERAGEPART $ 500.00\n"
       "EMPLOYMENT-RELATEDPRACTICESLIABILITYCOVERAGEPART $\n")
CRIME_ROW = [{"line": "Crime and Fidelity", "premium": "$ 500.00", "_policy_key": "crime#unnumbered"}]


def _crime(extra=""):
    return {"coverage_lines": CRIME_ROW,
            se.DOCS_KEY: (_doc("pkg", PKG + extra, {"property", "crime"}),)}


# ── (g) premium-only: a stated crime detail anywhere keeps the section ──────
def test_crime_schedule_on_a_later_page_is_stated():
    sched = ("\n[Document page 3]\nCRIME AND FIDELITY COVERAGE PART DECLARATIONS\n"
             "INSURING AGREEMENT    LIMIT OF INSURANCE   DEDUCTIBLE\n"
             "Employee Theft   $25,000   $500\n")
    assert se.premium_only_line(_crime(sched), "ACORD_141") is None


def test_crime_limit_in_a_note_or_narrative_is_stated():
    assert se.premium_only_line(_crime("\nNote from Mitchell: employee theft 25k\n"), "ACORD_141") is None
    assert se.premium_only_line(_crime("The crime limit is $50,000.\n"), "ACORD_141") is None


def test_a_menu_listing_or_another_terms_menu_states_nothing():
    epl = ("Fiduciary Liability Coverage Part\nCrime Coverage Part\n"
           "Kidnap, Ransom & Extortion Coverage Part\n[Document page 2]\n"
           "EMPLOYMENT PRACTICES LIABILITY COVERAGE PART\n(A) Aggregate Limit of Liability: $1,000,000\n")
    assert se.premium_only_line(_crime(epl), "ACORD_141") == "crime"
    assert se.premium_only_line(_crime("CRIMEANDFIDELITY COVERAGEPART $ 475.00\n"), "ACORD_141") == "crime"


def test_main_lines_are_never_premium_only():
    """A GL / auto / WC / property line whose limits extraction missed on one
    run keeps its section questions - ACORD 186 above all (it is about the
    contractor's operations, and form_line calls it GL)."""
    for fam, line, fid in (("general_liab", "COMMERCIAL GENERAL LIABILITY", "ACORD_126"),
                           ("general_liab", "COMMERCIAL GENERAL LIABILITY", "ACORD_186"),
                           ("auto", "BUSINESS AUTO", "ACORD_127"),
                           ("workers_comp", "WORKERS COMPENSATION", "ACORD_130"),
                           ("property", "COMMERCIAL PROPERTY", "ACORD_140")):
        facts = {"coverage_lines": [{"line": line, "premium": "$9,000", "_policy_key": f"{fam}#x"}],
                 se.DOCS_KEY: (_doc("pkg", f"{line} COVERAGE PART $ 9,000.00\n"),)}
        assert se.premium_only_line(facts, fid) is None, fid
        assert se.premium_only_fields(fid, ["Some_Box_A"], facts) == {}, fid


def test_a_person_typed_value_is_never_judged():
    facts = _crime()
    mapped = {"CrimeCoverage_EmployeeTheft_LimitAmount_A": "$25,000"}
    assert se.out_of_scope_values(mapped, {}, facts, "ACORD_141", set()) == {}


# ── AI_BOX_LABEL_AS_VALUE: an ACORD example answer is an answer ──────────────
def test_tooltip_example_answer_is_not_the_label():
    tu = ("Enter text: The type of blanket coverage (e.g., combined building and contents, "
          "building only, contents only).")
    assert not g.box_label_as_value("Combined Building and Contents", tu)
    assert g.box_label_as_value("The type of blanket coverage", tu)


# ── AI_PERSON_FROM_ANOTHER_SCHEDULE ─────────────────────────────────────────
_DRIVERS = {"auto_drivers": [{"name": "Daniel Mercer"}, {"name": "Alicia Bennett"}]}
_DRV_RAW = "Driver Name DOB\nDaniel Mercer 04/17/1982\nAlicia Bennett 01/02/1990\n"


def test_an_officer_who_drives_is_kept_when_printed_as_officer():
    raw = _DRV_RAW + "OFFICERS: Daniel Mercer, President\n"
    assert not g.person_from_another_schedule("WorkersCompensation_Individual_FullName_A",
                                              "Daniel Mercer", _DRIVERS, raw)
    # no role printed anywhere -> still refused
    assert g.person_from_another_schedule("WorkersCompensation_Individual_FullName_A",
                                          "Daniel Mercer", _DRIVERS, _DRV_RAW)


def test_a_contact_who_drives_is_kept_when_printed_as_contact():
    raw = _DRV_RAW + "Inspection Contact: Alicia Bennett 303-555-0100\n"
    assert not g.person_from_another_schedule("NamedInsured_InspectionContact_FullName_A",
                                              "Alicia Bennett", _DRIVERS, raw)


def test_a_sole_proprietor_who_drives_is_the_applicant():
    facts = dict(_DRIVERS, applicant_name="Daniel Mercer")
    assert not g.person_from_another_schedule("NamedInsured_FullName_A", "Daniel Mercer",
                                              facts, _DRV_RAW)


def test_drivers_in_the_crime_employee_boxes_are_still_refused():
    assert g.person_from_another_schedule("Employee_FullName_A", "Daniel Mercer", _DRIVERS, _DRV_RAW)


# ── Office addresses ────────────────────────────────────────────────────────
def test_a_lender_that_is_an_insurer_keeps_its_address():
    facts = {"carrier_name": "Amerisure Insurance Company"}
    mapped = {"AdditionalInterest_FullName_A": "Northwestern Mutual Life Insurance Company"}
    assert g._row_party_is_an_outside_insurer("AdditionalInterest_MailingAddress_LineOne_A",
                                              mapped, facts)
    # the package's own carrier as the interest: its address is still an office's
    mapped2 = {"AdditionalInterest_FullName_A": "Amerisure Insurance Company"}
    assert not g._row_party_is_an_outside_insurer("AdditionalInterest_MailingAddress_LineOne_A",
                                                  mapped2, facts)
    # no name on the row / not an insurer -> judged as before
    assert not g._row_party_is_an_outside_insurer("Auditor_MailingAddress_LineOne_A", {}, facts)
    assert not g._row_party_is_an_outside_insurer(
        "AdditionalInterest_MailingAddress_LineOne_A",
        {"AdditionalInterest_FullName_A": "FirstBank Colorado"}, facts)


def test_insurer_box_and_acord28_insurer_address_never_judged():
    assert not g._OTHER_PARTY_ADDRESS_BOX_RE.match("Insurer_MailingAddress_AddressLineOne_A")
    assert not g._OTHER_PARTY_ADDRESS_BOX_RE.match("Insurer_MailingAddress_CityName_A")


# ── AI_STATE_NOT_THIS_FORMS reads the base form ─────────────────────────────
def test_state_form_reads_the_base_form_id():
    assert g.state_not_this_forms("Vehicle_NonOwned_StateOrProvinceCode_C", "WY", "ACORD_137_CO__b")
    assert not g.state_not_this_forms("Vehicle_NonOwned_StateOrProvinceCode_C", "WY", "ACORD_131__UM")


# ── AI_PERSON_ANSWER_FOR_ANOTHER_QUESTION ───────────────────────────────────
def test_a_document_stating_the_same_year_keeps_it():
    said = {"year_built"}
    # "Roof replaced 2018" states the ROOFING year (stem, not the whole word)
    assert not g.person_answer_for_another_question(
        "BuildingImprovement_RoofingYear_A", "2018", said, "Enter year:", "Roof replaced 2018\n")
    # a column table: the header row names it
    raw = "Bldg  Roofing  Wiring  Plumbing\n1  2018  2015  2010\n"
    assert not g.person_answer_for_another_question(
        "BuildingImprovement_RoofingYear_A", "2018", said, "Enter year:", raw)
    # printed nowhere with the box's words -> refused
    assert g.person_answer_for_another_question(
        "BuildingImprovement_WiringYear_A", "2018", {"roof_year"}, "Enter year:",
        "Year built 2018\n")


def test_a_generic_header_word_does_not_rescue_a_borrowed_count():
    """ALS months 12 = the typed period of restoration; a loss-run table with
    "loss" in its header and a 12 claims count is not its statement."""
    raw = "Years of loss history | 5\nPolicy Year | Line | Claims\n2025 | All lines | 12\n"
    assert g.person_answer_for_another_question(
        "CommercialPropertyCoverage_BusinessIncomeOrRentalValue_ActualLossSustainedMonthCount_A",
        "12", {"period_of_restoration"}, "Enter count:", raw)


# ── AI_ANOTHER_LINES_FORM ───────────────────────────────────────────────────
def test_property_evidence_may_list_an_inland_marine_form():
    assert not g.form_from_another_line("FormEndorsement_CopyrightOwnerCode_A",
                                        {"FormEndorsement_CopyrightOwnerCode_A": "CM"}, "ACORD_28")
    # the form number alone ("CA 71 65") names the auto line
    assert g.form_from_another_line("FormEndorsement_FormIdentifier_A",
                                    {"FormEndorsement_FormIdentifier_A": "CA 71 65"}, "ACORD_28")


# ── AI_TOOLTIP_EXAMPLE scoped by subject: description boxes only ────────────
def test_a_name_boxs_example_printed_as_itself_stands():
    raw = "VEH  YEAR  MAKE  MODEL\n1  2019  FORD  F-250  1FTBF2B6XKEC12345\n"
    folded = g._ps()._normalize_for_search(raw)
    tu = "Enter text: The manufacturer of the vehicle (e.g. Ford, Chevy)."
    assert not g.unstated_tooltip_example("Ford", tu, folded, "Vehicle_ManufacturersName_A", raw)
    raw2 = "2023 | Property | Theft of tools | $4,000\n"
    folded2 = g._ps()._normalize_for_search(raw2)
    tu2 = "Enter text: The line of business (e.g., automobile liability, property, general liability)."
    assert not g.unstated_tooltip_example("Property", tu2, folded2, "LossHistory_LineOfBusiness_A", raw2)


def test_contact_type_claims_is_still_refused():
    raw = "LOSS RUN\nClaims reported: 3\n"
    folded = g._ps()._normalize_for_search(raw)
    tu = "Enter text: The type of contact being described (e.g. accounting, claims, etc.). "
    assert g.unstated_tooltip_example("Claims", tu, folded, "NamedInsured_Contact_ContactDescription_A", raw)


# ── AI_AMOUNT_NOT_STATED_FOR_THIS_COVERAGE ──────────────────────────────────
def test_named_windstorm_printed_as_windstorm_or_hail_stands():
    f = "CommercialPropertyCoverage_NamedWindstorm_DeductibleAmount_A"
    assert not g.amount_not_for_this_coverage(f, "$5,000", "WINDSTORM OR HAIL DEDUCTIBLE $5,000\n")
    assert not g.amount_not_for_this_coverage(f, "$5,000", "WIND/HAIL DEDUCTIBLE: $5,000\n")


def test_a_premium_only_line_still_asks_the_insureds_gross_receipts():
    """Owner, 25 Oct 2026: the 141's annual gross receipts is the insured's
    revenue, not a crime detail - kept when the crime section is premium-only."""
    import services.scoped_evidence as se
    orig = se.premium_only_line
    se.premium_only_line = lambda facts, form_id: "crime"
    try:
        out = se.premium_only_fields("ACORD_141", ["CrimeInformation_AnnualGrossReceiptsAmount_A",
                                                   "CrimeCoverage_EmployeeTheft_LimitAmount_A"], {})
    finally:
        se.premium_only_line = orig
    assert "CrimeInformation_AnnualGrossReceiptsAmount_A" not in out
    assert "CrimeCoverage_EmployeeTheft_LimitAmount_A" in out
