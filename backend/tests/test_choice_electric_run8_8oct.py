"""Choice Electric, the owner's runs 505bf394 (+ the Business Auto Policy added
after generation), 8 Oct 2026 night. Read 25sepChanges.md part S before
changing anything pinned here. Each section is one defect, pinned on the shape
that broke, with the near-miss that must keep working beside it.
"""
from __future__ import annotations

import copy
import os

import pytest

import services.ai_answer_guards as g
import services.extraction_service as es
import services.pdf_service as ps
import services.scoped_evidence as se
from services.fact_equivalence import same_fact
from services.lob_canon import canon_line

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)


def _src(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


def _doc(name, rows=None, flags=None, text="", **facts):
    f = dict(facts)
    if rows is not None:
        f["coverage_lines"] = rows
    return {"filename": name, "doc_type": "dec_page", "text": text, "facts": f, "flags": dict(flags or {})}


# ── 1. the add-document fill stamps with the package's documents ─────────────

def test_the_new_document_stamp_attaches_documents_like_generation():
    src = _src(BACKEND, "services", "session_documents.py")
    body = src[src.index("def _stamp_with_answers("):src.index("def _new_document_answers(")]
    assert "attach_documents(facts, session.get(\"docs\") or [])" in body
    assert body.index("attach_documents(") < body.index("map_facts_to_form(")


# ── 2. a line's attribute only from a document carrying that line ────────────

_EPL_ROWS = [{"line": "Employment Practices Liability Coverage Part", "carrier": "Federal Insurance Company",
              "premium": "$2,000"}]
_GL_ROWS = [{"line": "Commercial General Liability Coverage Part", "carrier": "Amerisure Insurance Company",
             "premium": "$16,818"}]


def test_an_epl_notice_never_makes_gl_claims_made():
    d = _doc("epl.pdf", _EPL_ROWS, {"gl_is_claims_made": True})
    assert es.drop_flags_of_lines_not_carried(d) == ["gl_is_claims_made"]
    assert d["flags"]["gl_is_claims_made"] is False


def test_a_gl_document_keeps_its_own_basis():
    d = _doc("gl.pdf", _GL_ROWS, {"gl_is_claims_made": True})
    assert es.drop_flags_of_lines_not_carried(d) == []
    assert d["flags"]["gl_is_claims_made"] is True


def test_a_document_naming_no_line_keeps_its_flags():
    d = _doc("narrative.pdf", [], {"gl_is_claims_made": True})
    assert es.drop_flags_of_lines_not_carried(d) == []


# ── 3. the policy premium a single-policy dec states ────────────────────────

_CYBER_ROWS = [{"line": "Cyber Incident Response Team", "carrier": "ACE American Insurance Company"},
               {"line": "Network Extortion", "carrier": "ACE American Insurance Company"},
               {"line": "Electronic, Social And Printed Media Liability", "carrier": "ACE American Insurance Company"}]
_CYBER_ENTRIES = [
    {"label": "Item 7. Extended Reporting Period A. Additional Premium", "value": "100% of Annual Premium"},
    {"label": "Item 8. Policy Premium", "value": "$4,162.00"},
    {"label": "Policy Premium Plus applicable taxes and fees (if any)", "value": "$4,162.00"},
]


def test_the_cyber_dec_premium_lands_on_its_line():
    d = _doc("cyber.pdf", copy.deepcopy(_CYBER_ROWS), dec_page_entries=_CYBER_ENTRIES)
    assert es.assign_declared_policy_premium(d) == "$4,162.00"
    rows = d["facts"]["coverage_lines"]
    assert rows[0]["premium"] == "$4,162.00"            # the line the canon calls cyber
    assert not rows[1].get("premium") and not rows[2].get("premium")


@pytest.mark.parametrize("rows,entries", [
    (_GL_ROWS + _EPL_ROWS, _CYBER_ENTRIES),                                          # priced / two lines
    ([dict(r, premium=None) for r in _GL_ROWS] + [dict(r, premium=None) for r in _EPL_ROWS],
     _CYBER_ENTRIES),                                                               # two families
    (copy.deepcopy(_CYBER_ROWS), [{"label": "Policy Premium", "value": "$4,162"},
                                  {"label": "Total Premium", "value": "$4,500"}]),   # two amounts
    (copy.deepcopy(_CYBER_ROWS), [{"label": "Minimum Premium", "value": "$500"}]),   # not the policy's
])
def test_nothing_is_guessed(rows, entries):
    d = _doc("x.pdf", rows, dec_page_entries=entries)
    assert es.assign_declared_policy_premium(d) is None


# ── 4. a pointer is not an amount ───────────────────────────────────────────

def test_see_schedule_is_not_a_limit_but_sentences_stay():
    f = {"auto_med_pay_limit": {"value": "$SEE SCHEDULE"}, "auto_um_uim_limit": "See attached schedule",
         "wc_el_each_accident": "Statutory", "deductible_application": "Applies per the policy schedule",
         "auto_liability_limit": "1,000,000"}
    assert sorted(es.drop_reference_amounts(f)) == ["auto_med_pay_limit", "auto_um_uim_limit"]
    assert set(f) == {"wc_el_each_accident", "deductible_application", "auto_liability_limit"}


# ── 5. one auto liability structure in two wordings ──────────────────────────

@pytest.mark.parametrize("a,b,want", [
    ("Each Accident", "combined single limit", "same"),
    ("$1,000,000 each accident", "CSL", "same"),
    ("CSL", "Split limits", "different"),
    ("BI $100k each person / $300k each accident", "combined single limit", "different"),
])
def test_auto_structure_is_read_not_spelled(a, b, want):
    assert same_fact("auto_liability_structure", a, b) == want


# ── 6. a building year must be printed as a building's year ─────────────────

_DECS = ("Policy Period From: 01/01/2025 To: 01/01/2026\nCHOICE ELECTRIC LLC 01/01/2025\n"
         "001 2001CHEVROLET EXPRESS G2500\nCopyright, Insurance Services Office, Inc., 1999\n")


@pytest.mark.parametrize("year,text,refuse", [
    ("2025", _DECS, True), ("2001", _DECS, True), ("1999", _DECS, True), ("1998", _DECS, True),
    ("1998", "Year Built: 1998", False), ("2018", "Roof replaced 06/15/2018.", False),
    ("2015", "Wiring updated in 2015", False),
])
def test_building_years(year, text, refuse):
    assert g.year_not_printed_as_a_building_year(year, text) is refuse


def test_the_issue_date_is_not_a_business_start_date():
    text = "TOTAL: $ 26,449.00\n01/16/2025\nIssue Date: _____________\n"
    assert g.policy_date_as_business_start("01/16/2025", text) is True
    assert g.policy_date_as_business_start("01/16/2010", "Date business started: 01/16/2010") is False


# ── 7. a building attribute / coverage amount stated as itself ───────────────

def test_roof_material_needs_a_roof_mention():
    tu = "Enter code: Roof material. Examples: Composition (fiberglass, asphalt, etc.); Metal; Tile"
    f = "Construction_RoofMaterialCode_A"
    assert g.cope_answer_without_evidence(f, "Composition", "LIMITATIONS ON COVERAGE FOR ROOF SURFACING", tu)
    assert not g.cope_answer_without_evidence(f, "Composition", "Roof: asphalt shingle, 2012", tu)
    assert not g.cope_answer_without_evidence(f, "Metal", "Construction: frame. Roof: Metal", tu)


def test_a_garaging_address_is_not_a_building_exposure():
    f = "BuildingExposure_FrontDescription_A"
    assert g.cope_answer_without_evidence(f, "DENVER, CO 80221", "111 DENVER, CO 80221 21,210", "")
    assert not g.cope_answer_without_evidence(f, "Vacant lot", "Front exposure: vacant lot, 60 ft", "")


def test_a_coverage_amount_must_follow_its_own_heading():
    sched = ("010 1,000,000 1,776 5,000 13 | -----UNINSURED MOTORISTS----- | ***SEE ***SEE ***SEE")
    f = "Vehicle_UninsuredMotorists_BodilyInjuryPerPersonLimitAmount_A"
    assert g.cope_answer_without_evidence(f, "1,000,000", sched, "")
    assert not g.cope_answer_without_evidence(f, "1,000,000", "Uninsured Motorists Limit $1,000,000", "")


# ── 8. a carrier's code is not the insured's identifier ─────────────────────

def test_the_carriers_ncci_code_is_not_the_risk_id():
    text = "AMERISURE INSURANCE COMPANY NCCI Code No.11525\nWORKERS' COMPENSATION INFORMATION PAGE"
    assert g.carrier_code_as_insured_id("11525", text) is True
    assert g.carrier_code_as_insured_id("123456789", "NCCI Risk ID: 123456789") is False


# ── 9. an OTHER row is not a coverage the form prints itself ─────────────────

_137_SCHEMA = {f: {"ft": "/Tx", "tu": "Enter text:"} for f in (
    "Vehicle_MedicalPayments_PerPersonLimitAmount_A", "Vehicle_OtherCoverageDescription_C",
    "Vehicle_OtherCoverage_LimitAmount_C", "Vehicle_OtherCoverage_SymbolDescription_C")}


def test_med_pay_is_not_an_other_coverage_on_137():
    mapped = {"Vehicle_OtherCoverageDescription_C": "Medical Payments",
              "Vehicle_OtherCoverage_LimitAmount_C": "$1,000,000"}
    assert g.other_row_names_a_coverage_with_its_own_boxes("Vehicle_OtherCoverageDescription_C", _137_SCHEMA, mapped)
    assert g.other_row_names_a_coverage_with_its_own_boxes("Vehicle_OtherCoverage_LimitAmount_C", _137_SCHEMA, mapped)
    mapped["Vehicle_OtherCoverageDescription_C"] = "Rental Reimbursement"
    assert not g.other_row_names_a_coverage_with_its_own_boxes("Vehicle_OtherCoverageDescription_C", _137_SCHEMA, mapped)


@pytest.mark.parametrize("value,refuse", [
    ("CO", True), ("Denver", True), ("DENVER, CO 80221", True),
    ("4800 Dahlia St", False), ("PO Box 12", False), ("Suite 400", False),
])
def test_a_street_line_holds_a_street(value, refuse):
    assert g.not_a_street_line(value) is refuse


def test_a_rating_row_is_not_an_explanation():
    ctx = g._Context({}, {"wc_class_codes": [{"code": "8742", "description":
                                               "State Act - Salespersons or Collectors-Outside"}]}, "", "ACORD_130")
    f = "WorkersCompensationLineOfBusiness_EmployeesTravelOutOfStateExplanation_A"
    assert g._judge(f, "CO 001 8742 State Act - Salespersons or Collectors-Outside", ctx)
    assert g._judge(f, "Outside salespersons travel to Wyoming jobs", ctx) is None


# ── 10. a description printed only by another line's documents ─────────────

def test_an_epl_sentence_is_not_a_gl_coverage_description():
    gl = _doc("pkg.pdf", _GL_ROWS, text="COMMERCIAL GENERAL LIABILITY COVERAGE PART $16,818")
    epl = _doc("epl.pdf", _EPL_ROWS, text="NOTICE: THE LIABILITY COVERAGE PARTS PROVIDE CLAIMS-MADE COVERAGE")
    facts = se.attach_documents({}, [gl, epl])
    schema = {"GeneralLiability_OtherCoverageDescription_A": {"ft": "/Tx", "tu": "Enter text: other coverage"}}
    mapped = {"GeneralLiability_OtherCoverageDescription_A": "claims-made coverage"}
    out = se.foreign_policy_text(mapped, schema, facts, "ACORD_126", set(mapped))
    assert out == {"GeneralLiability_OtherCoverageDescription_A": se.REASON_OTHER_POLICY}
    gl["text"] += "\nLiability coverage is written on a claims-made coverage basis"
    facts = se.attach_documents({}, [gl, epl])
    assert se.foreign_policy_text(mapped, schema, facts, "ACORD_126", set(mapped)) == {}


# ── 11. the vehicle schedule table's own columns ────────────────────────────

_TABLE = ("[Table - page 12]\n"
          "Veh # | Description:Year,Make,Model | Vehicle Identification | Territory and Garaging Location | "
          "Zip Code | Cost New | Stated Amount\n"
          "001 | 2001CHEVROLET EXPRESS G2500 | | 111 DENVER, CO | 80221 | 21,210 | \n"
          "002 | 1999GMC SAFARI XT | | 111 DENVER, CO | 80221 | 23,316 | \n"
          "003 | 2017CHEVROLET EXPRESS G2500 | | 111 DENVER, CO | 80221 | 31,940 | \n"
          "004 | 2017CHEVROLET EXPRESS G2500 | | 111 DENVER, CO | 80221 | 29,000 | \n")


def test_cost_new_comes_from_its_own_column():
    mf = {"auto_vin_schedule": [{"year": "2001", "make": "CHEVROLET", "model": "EXPRESS G2500"},
                                {"year": "1999", "make": "GMC", "model": "SAFARI XT"},
                                {"year": "2017", "make": "CHEVROLET", "model": "EXPRESS G2500"}]}
    es._read_vehicle_schedule_tables(mf, [{"text": _TABLE}])
    rows = mf["auto_vin_schedule"]
    assert rows[0]["cost_new"] == "21,210" and rows[0]["stated_amount"] == ""
    assert rows[1]["cost_new"] == "23,316"
    assert "cost_new" not in rows[2], "two 2017 Express rows with different figures are never guessed"
    facts = {"auto_vin_schedule": rows}
    assert ps._resolve_vehicle_cost_new("Vehicle_CostNewAmount_A", facts) == "21,210"
    assert ps._resolve_vehicle_stated_amount("Vehicle_Coverage_AgreedOrStatedAmount_A", facts) is None
    assert ps._resolve_vehicle_stated_amount("Vehicle_Coverage_AgreedOrStatedAmount_C", facts) is ps._SCHED_SKIP


def test_a_vehicle_value_box_refuses_a_deductible():
    facts = {"dec_page_entries": [{"label": "Comprehensive Deductible", "value": "$1,000"}]}
    mapped = {"Vehicle_CostNewAmount_B": "1,000"}
    schema = {"Vehicle_CostNewAmount_B": {"ft": "/Tx", "tu": "Enter amount: the cost new of the vehicle"}}
    ps._enforce_numeric_meaning_gate(mapped, schema, facts, {"Vehicle_CostNewAmount_B"})
    assert mapped["Vehicle_CostNewAmount_B"] is None


# ── 12. the auto dec's bare "Liability" row is the auto line (item 9) ────────

def test_a_bare_liability_row_joins_its_documents_line():
    rows = [{"line": "Liability"}, {"line": "Auto Medical Payments"},
            {"line": "Property Protection Insurance (Michigan Only)"}, {"line": "Uninsured Motorists"}]
    d = _doc("auto.pdf", rows)
    assert es.attach_generic_rows_to_document_line(d) == ["'Liability'->'Auto Liability'"]
    assert canon_line(d["facts"]["coverage_lines"][0]["line"]) == "auto"
    assert canon_line("Property Protection Insurance (Michigan Only)") is None


@pytest.mark.parametrize("rows", [
    [{"line": "General Liability"}, {"line": "Commercial Property"}],
    [{"line": "Commercial General Liability"}, {"line": "Auto Medical Payments"}],
    [{"line": "Liability"}, {"line": "Commercial General Liability Coverage Part"}],
])
def test_named_lines_are_never_moved(rows):
    d = _doc("x.pdf", copy.deepcopy(rows))
    assert es.attach_generic_rows_to_document_line(d) == []
    assert [r["line"] for r in d["facts"]["coverage_lines"]] == [r["line"] for r in rows]


def test_the_property_line_is_still_read():
    assert canon_line("Business Personal Property") == "property"
    assert canon_line("Commercial Property Coverage Part") == "property"


# ── 13. the producer, the audit period ──────────────────────────────────────

def test_an_office_line_is_not_the_login_agencys_address():
    docs = [_doc("excess.pdf", [], text="OFFICE: PHOENIX AZ", producer_address={"value": "OFFICE: PHOENIX AZ",
                                                                               "source": "ai"})]
    mf = {"producer_address": {"value": "OFFICE: PHOENIX AZ", "source": "ai"}}
    acct = {"organization_name": "Astrea It services", "full_name": "A B", "address": ""}
    es._route_producer_party(mf, docs, acct)
    assert "producer_address" not in mf
    mf = {"producer_address": {"value": "OFFICE: PHOENIX AZ", "source": "ai"}}
    es._route_producer_party(mf, docs, dict(acct, address="1200 17th St, Denver, CO 80202"))
    assert es._producer_text(mf.get("producer_address")) == "1200 17th St, Denver, CO 80202"


def test_the_ncci_adjustment_sentence_states_the_audit():
    f = {}
    es._prefer_submission_terms(f, "Item 4. ...\nADJUSTMENTS OF PREMIUM SHALL BE MADE ANNUALLY\n")
    assert (f.get("audit_period") or {}).get("value") == "Annual"
    f = {}
    es._prefer_submission_terms(f, "AUDIT PERIOD (IF APPLICABLE) ANNUALLY SEMI-ANNUALLY QUARTERLY MONTHLY")
    assert "audit_period" not in f


# ── 14. a person's answer is evidence for the round-9 rules ─────────────────

def test_a_value_a_person_stated_is_never_refused():
    facts = {"year_built": {"value": "2001", "source": "producer"},
             "fire_protection_class": {"value": "3", "source": "producer"}}
    ctx = g._Context({}, facts, "Policy Period 01/01/2001", "ACORD_140")
    ctx.person_values = g.person_values(facts)
    assert g._judge("CommercialStructure_BuiltYear_B", "2001", ctx) is None
    assert g._judge("BuildingFireProtection_ProtectionClassCode_B", "3", ctx) is None
    assert g._judge("Construction_RoofMaterialCode_A", "Composition", ctx)   # nobody stated it


def test_a_real_cost_new_survives_and_a_borrowed_one_does_not():
    facts = {"dec_page_entries": [{"label": "COST NEW", "value": "26680"},
                                  {"label": "Comprehensive Deductible", "value": "$1,000"}]}
    schema = {f: {"ft": "/Tx", "tu": "Enter amount: the cost new of the vehicle"}
              for f in ("Vehicle_CostNewAmount_A", "Vehicle_CostNewAmount_B")}
    mapped = {"Vehicle_CostNewAmount_A": "26680", "Vehicle_CostNewAmount_B": "1,000"}
    ps._enforce_numeric_meaning_gate(mapped, schema, facts, set(mapped))
    assert mapped == {"Vehicle_CostNewAmount_A": "26680", "Vehicle_CostNewAmount_B": None}
