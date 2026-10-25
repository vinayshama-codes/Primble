"""`services.declined_lines` - which lines the submission says it is NOT
requesting - and the doors that act on it (5 Oct 2026, rebuilt after the G6
adversarial audit).

The first reader declined lines from "Workers comp loss runs: not needed", a
premium-table row above an unrelated sentence and "The garage at the rear of
the lot is not part of this submission" (43 of 66 should-not-act probes), and
read nothing from the colon-less headings both other decline-bearing kits in
the database print. These cases are the audit's own, plus the real layouts of
CH125, FR125 (both versions), Meridian and harborline.
"""
import pytest

import services.declined_lines as dl
import services.extraction_service as es
import services.form_service as fs
import services.sqs_service as sq
from services.line_presence import (
    ABSENT, declined_by_submission, line_carried, line_in_submission, reconcile_line_flags,
)


# ── Should act ───────────────────────────────────────────────────────────────

_FR125 = ("LINES REQUESTED\nCommercial General Liability Commercial Property Business Auto Umbrella\n"
          "LINES NOT REQUESTED\nWorkers Compensation and Inland Marine (already with you) Cyber Crime "
          "Liquor Professional\nBILLING AND PAYMENT\nBilling preference Direct bill\n"
          "Premium indication not requested at this stage\nREMARKS FOR THE APPLICATION\n"
          "Please quote General Liability at $1,000,000 / $2,000,000 and the umbrella at $2,000,000.\n")
_FR125_ALL = ["crime", "cyber", "inland_marine", "liquor", "professional", "workers_comp"]
_MERIDIAN = ("COVERAGES REQUESTED\n[X] Commercial General Liability\n[X] Commercial Property\n"
             "[X] Business Auto\n[X] Commercial Umbrella\n[X] Commercial Inland Marine\n"
             "COVERAGES NOT REQUESTED / NOT IN FORCE\n[ ] Crime and Fidelity NO COVERAGE\n"
             "[ ] Workers Compensation Not covered under this programme\n"
             "[ ] Liquor Liability Not applicable to this risk\n"
             "[ ] Boiler and Machinery NO COVERAGE\n-----\nATTACHMENTS SUBMITTED\n- Contractors Supplement\n")
_CH125_COVER = ("LINES REQUESTED: Commercial General Liability, Commercial Property, Business Auto "
                "and a Commercial Umbrella ($5,000,000 each occurrence / aggregate).\n"
                "NOT REQUESTED: workers compensation (stays with Tennessee Employers Mutual, policy "
                "TEM-WC-0558213); commercial inland marine (the installation floater\nIMF-3318207 is "
                "already written by Ridgeline and runs to 06/2027); crime (the insured declined it); "
                "cyber (discussed, not requested at this time). Equipment breakdown is wanted.\n")


@pytest.mark.parametrize("text,expected", [
    ("NOT REQUESTED: Workers Compensation\n", ["workers_comp"]),
    ("Lines Not Requested - Workers' Comp, Crime\n", ["crime", "workers_comp"]),
    ("COVERAGES NOT BEING MARKETED: Inland Marine; Cyber Liability\n", ["cyber", "inland_marine"]),
    ("Coverages not requested: Commercial Auto\n", ["auto"]),
    ("• NOT REQUESTED: WC\n", ["workers_comp"]),
    ("LINES NOT REQUESTED: WORKERS COMPENSATION, EMPLOYMENT PRACTICES LIABILITY\n", ["epli", "workers_comp"]),
    ("Lines not requested:\nWorkers Compensation\nInland Marine\nEffective Date: 01/01/2027\n",
     ["inland_marine", "workers_comp"]),
    ("Lines of Business Not Requested: Workers Compensation (monopolistic - Ohio BWC)\n", ["workers_comp"]),
    ("NOTREQUESTED:WorkersCompensation\n", ["workers_comp"]),
    ("| NOT REQUESTED: | Workers Compensation |\n", ["workers_comp"]),
    ("Not Requested: Directors and Officers, Errors and Omissions\n", ["directors_officers", "professional"]),
    ("NOT BEING QUOTED: Umbrella\n", ["umbrella"]),
    ("Coverages declined by insured: Workers Compensation\n", ["workers_comp"]),
    ("Lines not requested: workers compensation and employers liability; inland marine.\n",
     ["inland_marine", "workers_comp"]),
    ("Coverages requested: GL, Property; Coverages not requested: Auto\n", ["auto"]),
    ("    Lines not requested: Workers Compensation\n", ["workers_comp"]),
    ("Workers Compensation\nNot requested -\nGeneral Liability\nRequested\n", ["workers_comp"]),
    ("Workers compensation is not requested.", ["workers_comp"]),
    ("WC is not being quoted at this time.", ["workers_comp"]),
    ("The workers compensation coverage is not part of this submission.", ["workers_comp"]),
    ("Please note that workers compensation is not requested.", ["workers_comp"]),
    ("Inland marine is not being marketed; it renews with Travelers.", ["inland_marine"]),
    ("We are not requesting workers compensation.", ["workers_comp"]),
    ("Workers' Compensation: Not requested\n", ["workers_comp"]),
    ("Excluding workers compensation, please quote all lines.", ["workers_comp"]),
    ("Workers compensation and inland marine are not requested.", ["inland_marine", "workers_comp"]),
    ("Workers comp is written through the Ohio BWC (monopolistic) and is not requested.", ["workers_comp"]),
    ("Workers compensation remains with the incumbent and is not being marketed at this renewal.",
     ["workers_comp"]),
    ("WORKERS COMPENSATION IS NOT REQUESTED.", ["workers_comp"]),
    ("| Workers Compensation | is not requested |", ["workers_comp"]),
    ("The insured is not requesting workers compensation.", ["workers_comp"]),
    ("Workers comp - not requested", ["workers_comp"]),
    ("Commercial auto (2 vehicles) is not requested.", ["auto"]),
    ("Workers compensation (66 employees, 4 locations) is not part of this submission.", ["workers_comp"]),
    ("General liability, property and auto are requested. Workers compensation is not requested.",
     ["workers_comp"]),
    ("Lines requested: GL, Property and Auto\nWorkers compensation is not requested; it stays with "
     "the state fund.\n", ["workers_comp"]),
    ("The contractors equipment floater is not being marketed.", ["inland_marine"]),
    ("The umbrella is not being quoted at this time.", ["umbrella"]),
    ("Coverages to be quoted: GL, Auto, Umbrella\nCoverages not requested: Workers Compensation\n",
     ["workers_comp"]),
    ("Line | Status\nWorkers Compensation | Not Requested\nInland Marine | Not Requested\n",
     ["inland_marine", "workers_comp"]),
    ("Workers Compensation .......... NOT REQUESTED\n", ["workers_comp"]),
    ("Inland Marine: Not requested at this time", ["inland_marine"]),
    ("Workers Compensation - declined by insured\n", ["workers_comp"]),
    ("We are no longer asking you to quote the umbrella.", ["umbrella"]),
    ("Excluded from this submission: Workers Compensation\n", ["workers_comp"]),
    ("Lines: GL - yes; Auto - yes; WC - not needed\n", ["workers_comp"]),
    ("We are not marketing the inland marine coverage this year.", ["inland_marine"]),
    ("Coverages not requested:\n- Workers Compensation\n- Inland Marine\n- Cyber\n\nPlease call.",
     ["cyber", "inland_marine", "workers_comp"]),
    ("NOT REQUESTED: workers compensation; inland marine\nPlease quote the general liability at "
     "$1M / $2M and the umbrella at $5M.\n", ["inland_marine", "workers_comp"]),
    ("NOT REQUESTED: workers compensation; crime. property is wanted on a replacement cost basis.\n",
     ["crime", "workers_comp"]),
    ("Workers\ncompensation stays with Tennessee Employers Mutual and is NOT being marketed.", ["workers_comp"]),
    ("AUTO SCHEDULE ATTACHED\nWorkers compensation stays with Tennessee Employers Mutual and is NOT "
     "being marketed.", ["workers_comp"]),
    ("9519 Household appliance installation / repair $1,284,600 3.88\nWorkers compensation stays "
     "with Tennessee Employers Mutual and is NOT being marketed.", ["workers_comp"]),
    ("Umbrella limit $5M requested again; the GC requires $5M. Please quote the\nInland Marine policy "
     "separately - it is not part of this submission.", ["inland_marine"]),
    ("Please quote the Inland\nMarine policy separately - it is not part of this submission.", ["inland_marine"]),
    ("Workers compensation is not being marketed to other carriers.", ["workers_comp"]),
    ("Property is not requested.", ["property"]),
    ("NOT REQUESTED: Employee Dishonesty", ["crime"]),
    ("Lines not requested: Truckers", ["auto"]),
    ("Lines not requested:\n[X] Workers Compensation\n[ ] Inland Marine\n", ["workers_comp"]),
    (_FR125, _FR125_ALL),
    (_FR125.replace("LINES NOT REQUESTED\n", "LINES NOT REQUESTED:\n"), _FR125_ALL),
    (_MERIDIAN, ["crime", "liquor", "workers_comp"]),
    (_CH125_COVER, ["crime", "cyber", "inland_marine", "workers_comp"]),
])
def test_a_stated_decline_is_read(text, expected):
    assert dl.lines_not_requested(text) == expected


# ── Must not act ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "NOT REQUESTED: None\n",
    "Coverages Not Requested: N/A\nCoverages Requested: GL, Auto\n",
    "Coverages not requested:\n\nSCHEDULE OF COVERAGES\nCommercial General Liability   $1,000,000 / "
    "$2,000,000\nBusiness Auto   $1,000,000 CSL\nWorkers Compensation   Statutory\n",
    "Lines not requested:\nBilling Plan: Direct\n",
    "Lines not requested:\nWorkers Compensation Carrier: Liberty Mutual\nWorkers Compensation Policy #: WC-1234\n",
    "NOT REQUESTED: Products and Completed Operations\n",
    "NOT REQUESTED: Hired and Non-Owned Auto\n",
    "NOT REQUESTED: Earthquake, Flood, Terrorism\n",
    "NOT REQUESTED: Stop Gap Employers Liability\n",
    "NOT REQUESTED: Auto Physical Damage\n",
    "NOT REQUESTED: Garagekeepers Legal Liability\n",
    "NOT REQUESTED: Building Coverage at Location 3\n",
    "NOT REQUESTED: Excess Liability above $5,000,000\n",
    "The claim is not part of this submission.",
    "Workers compensation loss runs are not part of this submission; they will follow under separate cover.",
    "Auto loss runs are not part of this submission.",
    "The property at 12 Main St (sold in 2025) is not part of this submission.",
    "The garage at the rear of the lot is not part of this submission.",
    "The installation at the customer's home is not part of this submission.",
    "Workers Compensation   WC-55102   $12,300\nThe subsidiary, Acme Leasing LLC, is not part of this submission.",
    "Inland Marine - Contractors Equipment   IM-8812   $2,400\nThe leased crane is not part of this submission.",
    "Hired and non-owned auto is not requested.",
    "Excess liability above $5M is not being requested.",
    "13. DOES APPLICANT HAVE OTHER BUSINESS VENTURES FOR WHICH COVERAGE IS NOT REQUESTED?",
    "EXPLANATION: AUTO REPAIR SHOP OWNED BY PRINCIPAL\nDOES APPLICANT HAVE OTHER BUSINESS VENTURES FOR "
    "WHICH COVERAGE IS NOT REQUESTED?",
    "WORKERS COMPENSATION POLICY WC-889 WITH STATE FUND\nDOES APPLICANT HAVE OTHER BUSINESS VENTURES FOR "
    "WHICH COVERAGE IS NOT REQUESTED? N",
    "Workers comp audit is not requested at this time.",
    "The umbrella quote is not requested until the primary is bound.",
    "Employers liability increased limits are not requested.",
    "Workers compensation is not requested for the Ohio employees; Ohio is monopolistic.",
    "Workers compensation was not requested last year.",
    "Property coverage is requested; flood is not requested.",
    "Garage door installation is not part of this submission.",
    "Auto dealer operations are not part of this submission.",
    "The 2019 Ford F-250 is not part of this submission.",
    "The workers compensation certificate for the subcontractor is not part of this submission.",
    "Lines requested: GL, Workers Compensation\nNOT REQUESTED: workers compensation\n",
    "13. Other business ventures for which coverage is not requested?\nANSWER: Y\n"
    "Smith Auto Body LLC is owned by the principal and is not part of this submission.",
    "Acme Property Management LLC is a separate venture and is not part of this submission.",
    "The managing member owns Summit Solar Services LLC, a residential solar\ninstallation company "
    "that is not part of this submission.",
    "Garage Door Installers Inc. (owned by the CEO) is not part of this submission.",
    "Excess Risk Partners LLC, owned by the CFO, is not part of this submission.",
    "The principal's trucking company, Volunteer Freight LLC, is not part of this submission.",
    "Workers compensation is not requested unless the umbrella carrier requires it.",
    "The umbrella is not being quoted until the primary terms are bound.",
    "Inland marine is not requested if the contractor's equipment is under $50,000.",
    "Workers Comp Loss Runs: Not needed\n",
    "Loss runs - Workers Comp: not requested\n",
    "Workers Comp X-Mod worksheet: not needed\n",
    "Auto MVRs: not requested\n",
    "Property SOV: not needed\n",
    "Inland marine equipment schedule: not needed\n",
    "Auto-pay: declined\n",
    "EFT/Auto debit: Declined\n",
    "Excess flood: declined\n",
    "Auto ID cards: not needed\n",
    "Property inspection: not needed\n",
    "The incumbent is no longer quoting commercial auto for this class, so we need a quote.",
    "Markets approached: Travelers is not quoting workers comp for roofers in Florida.",
    "Our current carrier is not quoting property in coastal counties.",
    "We are not quoting auto liability below $1M.",
    "We are not requesting any changes to the auto.",
    "We are not requesting higher umbrella limits.",
    "Auto physical damage on vehicle 5 is not requested.",
    "If workers compensation is not requested, say so.",
    "The kitchen design work is covered by a professional liability policy that is NOT part of "
    "this submission.",
    "Coverage for the joint venture is not requested.",
    "We are not marketing the account to other carriers.",
    "Physical damage: not requested",
    "Workers Comp - declined",
    "Status: declined by the carrier",
    "The garage is not part of this submission.",
    "The property is not part of this submission.",
    "The auto is not part of this submission.",
    "Workers compensation is not requested as respects the Ohio location.",
    "WC runs are attached and are not part of this submission.",
    "Is workers compensation not requested?",
    ("x" * 2000) + " auto is not part of this submission.",
    "13 | Does applicant have other business ventures for which coverage is not requested? | X |",
    "it is insured separately and coverage is not \n requested.",
    "POL|LOB=WORK|CARRIER=Tennessee Employers Mutual|NO=TEM-WC-0558213|STATUS=ACTIVE-NOT MARKETED",
    "", "   \n  ",
])
def test_these_decline_nothing(text):
    assert dl.lines_not_requested(text) == []


def test_none_and_repetition_are_safe():
    assert dl.lines_not_requested(None) == []
    assert dl.lines_not_requested("\n".join(["Workers compensation is not requested."] * 200)) == ["workers_comp"]


def test_a_prior_year_decline_is_contested_by_this_years_request():
    text = ("2027 RENEWAL SUBMISSION. Please quote general liability, auto and workers compensation "
            "effective 07/01/2027.\n\nPRIOR YEAR SUBMISSION (07/01/2026, for reference only)\n"
            "NOT REQUESTED: workers compensation (no employees at that time)\n")
    assert dl.lines_not_requested(text) == []


def test_an_inline_checkbox_row_requests_only_its_ticked_boxes():
    # CH125's application: several boxes on one line, the last box's label
    # wrapped onto the next line. An unticked "Workers Comp" is not a request -
    # it must not contest the cover letter's decline.
    app = ("LINES OF BUSINESS REQUESTED\n[X] Commercial General Liability [X] Commercial Property "
           "[X] Business Auto [X] Umbrella [ ] Inland Marine [ ] Crime [ ] Cyber [ ]\nWorkers Comp\n"
           "NATURE OF BUSINESS\n")
    assert dl.lines_requested(app) == ["auto", "general_liab", "property", "umbrella"]
    assert dl.lines_not_requested(app + _CH125_COVER) == ["crime", "cyber", "inland_marine", "workers_comp"]


def test_every_vocabulary_phrase_is_a_lob_canon_line_name():
    # One line-name vocabulary: the reader adds no phrase of its own (D9) and
    # holds no coverage PART.
    from services.lob_canon import canon_line
    for phrase in dl._PHRASES:
        assert canon_line(" ".join(phrase)), phrase
        assert " ".join(phrase) not in dl._PART_PHRASES


# ── Carried elsewhere ────────────────────────────────────────────────────────

def test_the_decline_statement_decides_carried_elsewhere():
    assert dl.lines_carried_elsewhere(_CH125_COVER, ["workers_comp", "inland_marine", "crime", "cyber"]) \
        == ["inland_marine", "workers_comp"]
    assert dl.lines_carried_elsewhere(_FR125, _FR125_ALL) == ["inland_marine", "workers_comp"]
    text = ("Workers Compensation for Oregon operations is written separately\nthrough the state "
            "accident insurance fund and is not part of this\nprogramme or of this submission.")
    assert dl.lines_carried_elsewhere(text, ["workers_comp"]) == ["workers_comp"]
    assert dl.lines_carried_elsewhere("NOT REQUESTED: workers compensation (no employees)\n",
                                      ["workers_comp"]) == []
    assert dl.lines_carried_elsewhere(_CH125_COVER, []) == []


# ── The doors that act on a decline ──────────────────────────────────────────

def test_the_recommender_and_the_flag_door_agree_on_a_persons_answer():
    flags = {"has_workers_comp": True, "has_inland_marine": True}
    text = "workers compensation declarations class code 8810 payroll inland marine floater"
    facts = {"_lines_not_requested": ["workers_comp"],
             "wc_payroll": {"value": "$900,000", "source": "producer"}}
    assert not declined_by_submission("workers_comp", facts)
    recs = {m["form_id"] for m in fs.match_forms_deterministic(facts, dict(flags), text=text)}
    assert "ACORD_130" in recs


def test_the_recommender_reads_an_envelope_decline():
    flags = {"has_workers_comp": True}
    text = "workers compensation declarations class code 8810 payroll"
    facts = {"_lines_not_requested": {"value": ["workers_comp"]}}
    recs = {m["form_id"] for m in fs.match_forms_deterministic(facts, dict(flags), text=text)}
    assert "ACORD_130" not in recs


def test_wc_and_im_recommendations_carry_their_line():
    flags = {"has_workers_comp": True, "has_inland_marine": True}
    text = "workers compensation declarations class code 8810 payroll inland marine floater"
    by_id = {m["form_id"]: m for m in fs.match_forms_deterministic({}, flags, text=text)}
    assert by_id["ACORD_130"]["for_line"] == "workers_comp"
    # Z37 (24 Oct 2026): ACORD 160 is Business Owners - inland marine offers no form.
    assert "ACORD_160" not in by_id
    assert all("for_line" not in m for f, m in by_id.items() if f not in ("ACORD_130", "ACORD_133"))


def test_a_string_false_flag_is_not_carried():
    for value in ("false", "N", {"value": False}, False, None, 0):
        assert not line_carried("workers_comp", {}, {"has_workers_comp": value})
    assert line_carried("workers_comp", {}, {"has_workers_comp": "true"})
    assert line_carried("workers_comp", {}, {"has_workers_comp": False, "workers_comp_in_force": True})


def test_a_merge_of_the_real_cover_letter_records_both_facts():
    mf = {}
    es._mark_lines_not_requested(mf, _CH125_COVER)
    assert mf["_lines_not_requested"] == ["crime", "cyber", "inland_marine", "workers_comp"]
    assert mf["_lines_carried_elsewhere"] == ["inland_marine", "workers_comp"]
    flags = {"has_workers_comp": True, "has_inland_marine": True}
    reconcile_line_flags(flags, mf)
    assert flags["has_workers_comp"] is False and flags["workers_comp_in_force"] is True
    assert line_in_submission("workers_comp", mf, flags) == ABSENT
    assert sq._wc_carried(flags)
    es._mark_lines_not_requested(mf, "nothing declined here")
    assert "_lines_not_requested" not in mf and "_lines_carried_elsewhere" not in mf
