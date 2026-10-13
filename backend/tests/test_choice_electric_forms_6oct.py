"""Choice Electric (Brent + Michelle, 5 Oct 2026) - the stamped values on ACORD
125 / 126 / 127 / 130 / 131 / 137 (6 Oct 2026, FORMS round).

Every case is the CLASS the client's package exposed, written so the shape of
the defect - not the client's strings - is what is pinned, plus a negative
control for each rule (the value that must keep printing).
"""
import copy
import json
import os

import pytest

import services.extraction_service as es
import services.pdf_service as ps

_SCHEMAS = os.path.join(os.path.dirname(__file__), "..", "forms_schemas")


def _schema(form_id):
    with open(os.path.join(_SCHEMAS, f"{form_id}_schema.json")) as fh:
        return json.load(fh)


# The client's package, as its coverage rows read (redacted: no numbers).
_LINES = [
    {"line": "Excess (Following Form) Liability", "carrier": "TRAVELERS PROPERTY CASUALTY COMPANY OF AMERICA",
     "premium": "$ 10,692", "policy_number": None, "effective_date": "01/01/2025", "expiration_date": "01/01/2026"},
    {"line": "Employment Practices Liability Coverage Part", "carrier": "Federal Insurance Company",
     "premium": None, "policy_number": None, "effective_date": "January 1, 2025",
     "expiration_date": "January 1, 2026"},
    {"line": "Cyber", "carrier": "ACE American Insurance Company", "premium": "$4,162.00",
     "policy_number": None, "effective_date": "01-01-2025", "expiration_date": "01-01-2026"},
    {"line": "Commercial Auto", "carrier": "AMERISURE INSURANCE COMPANY", "premium": None,
     "policy_number": None, "effective_date": "01/01/2025", "expiration_date": "01/01/2026"},
    {"line": "Commercial Liability Umbrella", "carrier": "AMERISURE MUTUAL INSURANCE COMPANY",
     "premium": "$ 17,082.00", "policy_number": None, "effective_date": "01/01/2025",
     "expiration_date": "01/01/2026"},
    {"line": "Commercial General Liability Coverage Part", "carrier": "AMERISURE INSURANCE COMPANY",
     "premium": "$ 16,818.00", "policy_number": None, "effective_date": "01/01/2025",
     "expiration_date": "01/01/2026"},
    {"line": "Commercial Inland Marine Coverage Part", "carrier": "AMERISURE INSURANCE COMPANY",
     "premium": "$ 2,431.00", "policy_number": None, "effective_date": "01/01/2025",
     "expiration_date": "01/01/2026"},
    {"line": "Commercial Property Coverage Part", "carrier": "AMERISURE INSURANCE COMPANY",
     "premium": "$ 6,275.00", "policy_number": None, "effective_date": "01/01/2025",
     "expiration_date": "01/01/2026"},
    {"line": "Crime and Fidelity Coverage Part", "carrier": "AMERISURE INSURANCE COMPANY",
     "premium": "$ 500.00", "policy_number": None, "effective_date": "01/01/2025",
     "expiration_date": "01/01/2026"},
    {"line": "Workers' Compensation and Employers' Liability", "carrier": "AMERISURE INSURANCE COMPANY",
     "premium": "29,278.00", "policy_number": None, "naic": "11525", "effective_date": "01/01/2025",
     "expiration_date": "01/01/2026"},
    {"line": "Employee Benefit Liability Coverage Part", "carrier": "AMERISURE INSURANCE COMPANY",
     "premium": "$ 425.00", "policy_number": None, "effective_date": "01/01/2025",
     "expiration_date": "01/01/2026"},
]


def _facts(**over):
    f = {"coverage_lines": copy.deepcopy(_LINES)}
    f.update(over)
    return f


# ══ 1. 125 CARRIER: a writer is a carrier whose own declarations state it ════

class TestWriters:
    def test_a_policy_with_its_own_term_and_no_premium_or_number_writes(self):
        names = es.current_policy_writer_names(_LINES)
        assert "Federal Insurance Company" in names
        assert names == sorted(names, key=lambda n: n.lower().replace(" ", ""))
        assert len(names) == 5

    def test_a_carrier_with_nothing_of_its_own_still_writes_nothing(self):
        assert es._current_policy_writers([{"carrier": "X Co"}]) == []
        assert es._current_policy_writers([{"carrier": "X Co", "effective_date": "01/01/2025"}]) == []
        # an inverted or unreadable term is not a term
        assert es._current_policy_writers([{"carrier": "X Co", "effective_date": "01/01/2026",
                                            "expiration_date": "01/01/2025"}]) == []
        assert es._current_policy_writers([{"carrier": "X Co", "effective_date": "SEE SCHEDULE",
                                            "expiration_date": "N/A"}]) == []

    def test_a_carrier_only_a_certificate_names_never_writes(self):
        rows = [{"carrier": "Dec Carrier Co", "policy_number": "A-1", "premium": "$100"},
                {"carrier": "Cert Only Insurance Company", "policy_number": "Z-9",
                 "effective_date": "01/01/2025", "expiration_date": "01/01/2026"}]
        docs = [{"doc_type": "dec_page", "facts": {"carrier_name": "Dec Carrier Co", "coverage_lines": rows[:1]}},
                {"doc_type": "certificate", "facts": {"coverage_lines": rows[1:]}},
                {"doc_type": "loss_run", "facts": {"carrier_name": "Cert Only Insurance Company"}}]
        assert es.current_policy_writer_names(rows, docs) == ["Dec Carrier Co"]
        # without the documents the row test alone decides, as before
        assert len(es.current_policy_writer_names(rows)) == 2

    @pytest.mark.parametrize("docs", [None, [], "junk", [None, 3], [{"doc_type": "dec_page", "facts": "{'x': 1}"}],
                                      [{"doc_type": "dec_page", "facts": {}}]])
    def test_no_document_opinion_keeps_the_row_rule(self, docs):
        assert es.current_policy_writer_names(_LINES, docs) == es.current_policy_writer_names(_LINES)

    def test_the_merge_records_the_names_and_the_stamper_prints_them(self):
        mf = {"carrier_name": {"value": "AMERISURE INSURANCE COMPANY", "source": "ai"},
              "coverage_lines": copy.deepcopy(_LINES),
              "effective_date": {"value": "01/01/2026", "source": "derived",
                                 "derivation": {"rule": "next_term_after_current_policy"}}}
        docs = [{"doc_type": "dec_page", "facts": {"carrier_name": r["carrier"], "coverage_lines": [r]}}
                for r in _LINES]
        es._mark_page_one_current_policy(mf, docs)
        assert mf["renews_current_programme"] is True
        assert "Federal Insurance Company" in mf["_programme_writers"]
        facts = {**mf, "_form_id": "ACORD_125"}
        # The merge still records every writing company, but the top Carrier box
        # lists none of them (Brent, 8 Oct 2026: "That field is for the carrier
        # tied to the application") - blank, and the card asks.
        assert ps._resolve_page_one_receiving_carrier("Insurer_FullName_A", facts) is None
        # several writers: NAIC and POLICY NUMBER stay blank
        assert ps._resolve_page_one_receiving_carrier("Insurer_NAICCode_A", facts) is None
        assert ps._resolve_page_one_receiving_carrier("Policy_PolicyNumberIdentifier_A", facts) is None

    def test_the_stored_names_are_recomputed_not_sticky(self):
        mf = {"_programme_writers": ["Stale Co"], "coverage_lines": []}
        es._mark_page_one_current_policy(mf, [])
        assert "_programme_writers" not in mf


# ══ 2/3. 125 LINES OF BUSINESS: one row per POLICY ══════════════════════════

class TestLinesOfBusiness:
    def test_the_excess_layer_gets_its_own_row_and_the_umbrella_keeps_its_box(self):
        f = _facts()
        assert ps._resolve_lob_premium("CommercialUmbrellaLineOfBusiness_PremiumAmount_A", f) == "$ 17,082.00"
        rows = ps._other_lob_rows(f)
        assert [r["name"] for r in rows] == ["Employee Benefit Liability Coverage Part",
                                             "Excess (Following Form) Liability"]
        assert [r["premium"] for r in rows] == ["$ 425.00", "$ 10,692"]
        assert ps._resolve_other_lob_row("Policy_LineOfBusiness_OtherLineOfBusinessDescription_B", f) \
            == "Excess (Following Form) Liability"
        assert ps._resolve_other_lob_row("Policy_LineOfBusiness_OtherIndicator_B", f) == "Yes"
        assert ps._resolve_other_lob_row("Policy_LineOfBusiness_OtherIndicator_C", f) is None

    def test_the_other_premium_boxes_are_found_by_their_own_tooltip(self):
        boxes = ps._other_lob_premium_boxes(_schema("ACORD_125"))
        assert sorted(boxes.values()) == list("ABCDEF")
        assert all("PremiumAmount" in b for b in boxes)
        assert ps._other_lob_premium_boxes({}) == {} and ps._other_lob_premium_boxes(None) == {}

    def test_the_other_rows_print_their_premiums(self):
        f = _facts()
        s = _schema("ACORD_125")
        box = {v: k for k, v in ps._other_lob_premium_boxes(s).items()}
        assert ps._resolve_other_lob_premium(box["A"], f, s) == "$ 425.00"
        assert ps._resolve_other_lob_premium(box["B"], f, s) == "$ 10,692"
        assert ps._resolve_other_lob_premium(box["C"], f, s) is None
        # no per-line data: the box keeps its old (blank, never asked) behaviour
        assert ps._resolve_other_lob_premium(box["A"], {}, s) is ps._SCHED_SKIP
        # not an OTHER premium box at all
        assert ps._resolve_other_lob_premium("Policy_Payment_EstimatedTotalAmount_A", f, s) is ps._SCHED_SKIP

    def test_a_coverage_part_of_the_same_policy_never_splits(self):
        lines = [{"line": "Automobile", "carrier": "EMCC", "premium": "$2,991", "policy_number": "6E7-1"},
                 {"line": "Covered Autos Liability", "carrier": "EMCC", "premium": "$1,496",
                  "policy_number": "6E7-1"},
                 {"line": "Commercial General Liability", "carrier": "EMC P&C", "premium": "$3,954",
                  "policy_number": "BBC7263"}]
        assert ps._second_policy_rows({"coverage_lines": lines}) == {}
        assert ps._resolve_lob_premium("CommercialVehicleLineOfBusiness_PremiumAmount_A",
                                       {"coverage_lines": lines}) == "$2,991"

    def test_two_exactly_named_policies_cannot_be_told_apart(self):
        lines = [{"line": "Commercial Liability Umbrella", "carrier": "A Insurance Company", "premium": "$1,000"},
                 {"line": "Commercial Liability Umbrella", "carrier": "B Insurance Company", "premium": "$2,000"}]
        f = {"coverage_lines": lines}
        assert ps._second_policy_rows(f) == {}
        assert ps._resolve_lob_premium("CommercialUmbrellaLineOfBusiness_PremiumAmount_A", f) is None
        assert ps._other_lob_rows(f) == []

    def test_one_policy_printed_under_two_carrier_spellings_is_one_policy(self):
        lines = [{"line": "Commercial Liability Umbrella", "carrier": "Amerisure Mutual", "premium": "$17,082"},
                 {"line": "Excess Liability", "carrier": "Amerisure Mutual Ins Co", "premium": "$17,082"}]
        assert ps._second_policy_rows({"coverage_lines": lines}) == {}

    def test_a_row_naming_no_carrier_is_never_moved(self):
        lines = [{"line": "Commercial Liability Umbrella", "carrier": "A Insurance Company", "premium": "$1,000"},
                 {"line": "Excess Liability", "carrier": "", "premium": "$700"}]
        assert ps._second_policy_rows({"coverage_lines": lines}) == {}

    def test_epli_with_no_premium_gets_no_row_yet(self):
        names = [r["name"] for r in ps._other_lob_rows(_facts())]
        assert not any("Employment Practices" in n for n in names)

    def test_recognising_ebl_as_its_own_family_breaks_no_gl_box(self):
        from services.lob_canon import canon_line
        assert canon_line("Employee Benefit Liability Coverage Part") in (None, "employee_benefits")
        assert ps._resolve_lob_premium("GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A", _facts()) \
            == "$ 16,818.00"

    @pytest.mark.parametrize("junk", [None, "x", [None, 3, "row"], [{"line": None, "premium": "$5"}]])
    def test_junk_lines_never_raise(self, junk):
        f = {"coverage_lines": junk}
        ps._second_policy_rows(f)
        ps._other_lob_rows(f)
        ps._printed_lob_premiums(f)


class TestEstimatedTotal:
    _BOX = "Policy_Payment_EstimatedTotalAmount_A"

    def test_the_total_is_the_sum_of_the_premiums_the_grid_prints(self):
        f = _facts(total_policy_premium="$ 10,692.00")     # one policy's own total
        printed = ps._printed_lob_premiums(f)
        assert sum(printed) == 58385
        assert 29278 not in printed                         # WC: no row on ACORD 125
        assert ps._resolve_estimated_total(self._BOX, f) == "$58,385"

    def test_one_policys_own_total_is_not_the_pages(self):
        # the package dec's $26,449 is larger than any row but totals ONE of
        # the five carriers' policies the grid prints
        f = _facts(total_policy_premium="$ 26,449.00")
        assert ps._resolve_estimated_total(self._BOX, f) == "$58,385"

    def test_a_one_carrier_page_keeps_its_stated_total(self):
        lines = [dict(r, carrier="One Carrier Co") for r in _LINES]
        f = {"coverage_lines": lines, "total_policy_premium": "$40,000"}
        assert ps._resolve_estimated_total(self._BOX, f) == "$40,000"

    def test_a_line_the_grid_shows_without_a_figure_blanks_the_fallback(self):
        lines = copy.deepcopy(_LINES) + [{"line": "Business Auto", "carrier": "AMERISURE INSURANCE COMPANY",
                                          "premium": None, "limit": "$1,000,000"}]
        f = {"coverage_lines": lines, "total_policy_premium": "$ 10,692.00"}
        assert ps._resolve_estimated_total(self._BOX, f) is None

    def test_a_stated_total_at_least_the_printed_rows_stands(self):
        f = _facts(total_policy_premium="$60,000.00")
        assert ps._resolve_estimated_total(self._BOX, f) == "$60,000.00"

    def test_no_stated_total_prints_the_printed_sum(self):
        assert ps._resolve_estimated_total(self._BOX, _facts()) == "$58,385"

    def test_no_per_line_data_keeps_the_legacy_path(self):
        assert ps._resolve_estimated_total(self._BOX, {}) is ps._SCHED_SKIP
        assert ps._resolve_estimated_total(self._BOX, {"total_policy_premium": "$5,000"}) == "$5,000"

    def test_nothing_priced_on_the_grid_and_an_impossible_stated_total_is_blank(self):
        f = {"coverage_lines": [{"line": "Workers Compensation", "carrier": "X", "premium": "$29,278"}],
             "total_policy_premium": "$1,000"}
        assert ps._resolve_estimated_total(self._BOX, f) is None


# ══ 2. 125 PRIOR CARRIER grid ════════════════════════════════════════════════

def _records(**over):
    rec = {"line": "general_liab", "carrier_name": "AMERISURE INSURANCE COMPANY", "policy_number": None,
           "effective_date": "01/01/2025", "expiration_date": "01/01/2026", "granted": True,
           "printings": {"carrier_name": ["AMERISURE INSURANCE COMPANY"]}, "sources": []}
    rec.update(over)
    return rec


class TestPriorCarrierGrid:
    def test_a_row_stands_on_carrier_term_and_premium_without_a_number(self):
        f = _facts(_line_records=[_records(),
                                  _records(line="property"),
                                  _records(line="epli", carrier_name="Federal Insurance Company", granted=False)])
        rows = ps._current_policy_grid_rows(f, (None, None))
        by_line = {r["line"]: r for r in rows}
        assert set(by_line) == {"General Liability", "Property"}       # EPLI: no number, no premium
        assert by_line["General Liability"]["premium"] == "$ 16,818.00"
        assert by_line["General Liability"]["policy_no"] is None
        assert by_line["Property"]["premium"] == "$ 6,275.00"

    def test_a_label_or_form_number_is_never_the_number(self):
        f = _facts(_line_records=[_records(line="auto", policy_number="CG 00 01 04 13", granted=False)])
        assert ps._current_policy_grid_rows(f, (None, None)) == []

    def test_a_renewal_presumed_from_the_declarations_reaches_the_underlying_rows(self):
        f = {"renews_current_programme": True,
             "prior_effective_date": "01/01/2025", "prior_expiration_date": "01/01/2026",
             "underlying_policies": [{"line": "Automobile Liability", "carrier": "AMERISURE INSURANCE COMPANY"}]}
        rows = ps._prior_rows_from_underlying_policies(f)
        assert rows and rows[0]["carrier"] == "AMERISURE INSURANCE COMPANY"
        assert ps._prior_rows_from_underlying_policies(dict(f, renews_current_programme=False)) == []


# ══ 4. Payment plan: code or blank; the dividend plan has its own box ═══════

class TestPaymentPlan:
    @pytest.mark.parametrize("form", ["ACORD_125", "ACORD_130"])
    def test_a_dividend_plan_is_never_a_payment_plan(self, form):
        f = {"payment_plan": "Blue I (B1) Dividend Plan", "_form_id": form}
        assert ps._resolve_payment_schedule("Policy_Payment_PaymentScheduleCode_A", f) is None

    @pytest.mark.parametrize("val,code", [("Monthly", "MO"), ("monthly EFT", "MO"), ("AN", "AN"),
                                          ("Quarterly installments", "QT")])
    def test_a_stated_plan_prints_its_code(self, val, code):
        f = {"payment_plan": val, "_form_id": "ACORD_125"}
        assert ps._resolve_payment_schedule("Policy_Payment_PaymentScheduleCode_A", f) == code

    def test_the_dividend_plan_box_takes_the_declared_plan(self):
        f = {"dec_page_entries": [{"label": "Dividend Plan", "value": "Blue I (B1) Dividend Plan",
                                   "owner": "policy", "line_of_business": "Workers Compensation"}]}
        assert ps._resolve_dividend_plan_box("WorkersCompensation_DividendOrSafetyPlan_A", f) \
            == "Blue I (B1) Dividend Plan"
        assert ps._resolve_dividend_plan_box("WorkersCompensation_DividendOrSafetyPlan_A", {}) is ps._SCHED_SKIP
        two = {"dec_page_entries": f["dec_page_entries"] + [
            {"label": "Safety Group", "value": "Group 9", "owner": "policy"}]}
        assert ps._resolve_dividend_plan_box("WorkersCompensation_DividendOrSafetyPlan_A", two) is None


# ══ 6. ACORD 130 counts the documents must state ════════════════════════════

class TestStatedCounts:
    def test_no_loss_data_no_claim_count(self):
        assert ps._resolve_claim_count("LossHistory_ClaimCount_A", {"no_prior_losses": True}) is None
        assert ps._resolve_claim_count("LossHistory_ClaimCount_A", {"num_claims": "2"}) is ps._SCHED_SKIP
        assert ps._resolve_claim_count("LossHistory_ClaimCount_A",
                                       {"loss_history": [{"date": "01/02/2024", "paid": "$500"}]}) is ps._SCHED_SKIP
        assert ps._resolve_claim_count("LossHistory_PaidAmount_A", {}) is ps._SCHED_SKIP

    def test_a_list_enumerator_is_not_a_count(self):
        toks = ps._document_number_tokens("(C) Retentions: (1) Each Employment Claim (other than) 3) item")
        assert (1, "1") not in toks
        assert (3, "3") not in toks
        schema = _schema("ACORD_130")
        mapped = {"LossHistory_ClaimCount_A": "1"}
        out = ps._drop_unstated_counts(mapped, schema, {}, "(1) Each Employment Claim", {"LossHistory_ClaimCount_A"})
        assert "LossHistory_ClaimCount_A" in out
        kept = {"LossHistory_ClaimCount_A": "2"}
        assert ps._drop_unstated_counts(kept, schema, {}, "2 claims were reported in 2024",
                                        {"LossHistory_ClaimCount_A"}) == {}

    def test_years_in_business_is_stated_or_blank(self):
        box = "NamedInsured_InBusinessYearCount_A"
        assert ps._resolve_years_in_business_count(box, {}) is None
        assert ps._resolve_years_in_business_count(box, {"years_in_business": "26"}) == "26"


# ══ 5/6/7. An AI value must belong in its box ═══════════════════════════════

_ENTRIES = [
    {"label": "Aggregate Limit of Liability", "value": "$1,000,000", "owner": "policy",
     "section": "EMPLOYMENT PRACTICES LIABILITY COVERAGE PART", "line_of_business": "Employment Practices Liability"},
    {"label": "Retentions Each Employment Claim", "value": "$10,000", "owner": "policy",
     "section": "EMPLOYMENT PRACTICES LIABILITY COVERAGE PART", "line_of_business": "Employment Practices Liability"},
    {"label": "Pending or Prior Proceedings Date", "value": "March 1, 2022", "owner": "policy",
     "section": "EMPLOYMENT PRACTICES LIABILITY COVERAGE PART", "line_of_business": "Employment Practices Liability"},
    {"label": "Coverage(s) Applicable to this Policy", "value": "Employment Practices Liability Coverage Part",
     "owner": "policy", "section": "EMPLOYMENT PRACTICES LIABILITY COVERAGE PART",
     "line_of_business": "Employment Practices Liability"},
    {"label": "EMPLOYEE BENEFIT LIABILITY COVERAGE PART", "value": "$ 425.00", "owner": "policy",
     "section": "COMMON POLICY DECLARATIONS", "line_of_business": None},
    {"label": "Prem #: 001 Bldg #: 001", "value": "GRP I 0.053 $533.00", "owner": "policy",
     "section": "COMMERCIAL PROPERTY COVERAGE SCHEDULE", "line_of_business": "Property"},
    {"label": "Prem #: 001 Bldg #: 001", "value": "WINDSTORM OR HAIL DEDUCTIBLE: 2%", "owner": "policy",
     "section": "COMMERCIAL PROPERTY COVERAGE SCHEDULE", "line_of_business": "Property"},
    {"label": "NCCI Code No.", "value": "11525", "owner": "carrier",
     "section": "WORKERS' COMPENSATION AND EMPLOYERS' LIABILITY INFORMATION PAGE",
     "line_of_business": "Workers Compensation"},
]
_RAW = ("CO 9664 Small Deductible 6.5000 -2,495.00\nAUTO MEDICAL PAYMENTS Limit 5,000\n"
        "001 2001CHEVROLET EXPRESS G2500 111 DENVER, CO 80221 21,210\nDeductible $1,000\n")


def _guard(form, mapped, **facts_over):
    facts = {"dec_page_entries": copy.deepcopy(_ENTRIES), "coverage_lines": copy.deepcopy(_LINES),
             "property_deductible_wind": "2%", "auto_liability_limit": "1,000,000",
             "auto_vin_schedule": [{"territory": "111", "make": "CHEVROLET"}]}
    facts.update(facts_over)
    m = dict(mapped)
    out = ps._drop_misplaced_values(m, _schema(form), facts, _RAW, set(mapped), form)
    return out, m


class TestMisplacedValues:
    def test_the_employee_benefits_section_takes_only_ebl_evidence(self):
        out, m = _guard("ACORD_131", {
            "ExcessUmbrella_EmployeeBenefits_EachEmployeeLimitAmount_A": "1,000,000",
            "ExcessUmbrella_EmployeeBenefits_DeductibleOrRetentionAmount_A": "10,000",
            "ExcessUmbrella_EmployeeBenefits_RetroactiveDate_A": "03/01/2022",
            "ExcessUmbrella_EmployeeBenefits_ProgramName_A": "Employment Practices Liability Coverage Part"})
        assert len(out) == 4 and all(v.startswith("NOT_THIS_COVERAGES_EVIDENCE") for v in out.values())
        assert not any(m.values())

    def test_an_ebl_figure_the_documents_give_ebl_stays(self):
        out, m = _guard("ACORD_131", {"ExcessUmbrella_EmployeeBenefits_AggregateLimitAmount_A": "$425"})
        assert out == {} and m["ExcessUmbrella_EmployeeBenefits_AggregateLimitAmount_A"] == "$425"

    def test_another_lines_schedule_text_never_describes_an_auto_symbol(self):
        out, _ = _guard("ACORD_137_CO", {"Vehicle_OtherCoverage_SymbolDescription_C": "GRP I 0.053 $533.00",
                                         "Vehicle_OtherCoverage_SymbolDescription_D": "Prem. #: 001 Bldg #: 001"})
        assert set(out) == {"Vehicle_OtherCoverage_SymbolDescription_C",
                            "Vehicle_OtherCoverage_SymbolDescription_D"}
        assert all(v.startswith("VALUE_FROM_ANOTHER_LINE") for v in out.values())

    def test_a_value_no_entry_places_is_kept(self):
        out, _ = _guard("ACORD_137_CO", {"Vehicle_OtherCoverage_SymbolDescription_C": "Hired autos only"})
        assert out == {}

    def test_a_property_peril_deductible_is_never_a_gl_deductible(self):
        out, _ = _guard("ACORD_126", {"GeneralLiability_OtherDeductibleAmount_A": "2",
                                      "GeneralLiability_OtherDeductibleDescription_A": "WINDSTORM OR HAIL DEDUCTIBLE"})
        assert set(out) == {"GeneralLiability_OtherDeductibleAmount_A",
                            "GeneralLiability_OtherDeductibleDescription_A"}

    def test_a_gl_deductible_the_facts_state_stays(self):
        out, _ = _guard("ACORD_126", {"GeneralLiability_PropertyDamage_DeductibleAmount_A": "2"},
                        gl_deductible="$2")
        assert out == {}

    def test_a_rate_is_never_an_amount(self):
        out, _ = _guard("ACORD_130", {"WorkersCompensation_DeductibleAmount_A": "$6.50"})
        assert list(out.values())[0].startswith("RATE_NOT_AN_AMOUNT")
        out, _ = _guard("ACORD_130", {"WorkersCompensation_DeductibleAmount_A": "$1,000"})
        assert out == {}

    def test_a_carrier_code_is_never_the_insureds_risk_id(self):
        out, _ = _guard("ACORD_130", {"NamedInsured_NCCIRiskIdentifier_A": "11525"})
        assert list(out.values())[0].startswith("CARRIER_CODE_IN_APPLICANT_BOX")
        out, _ = _guard("ACORD_130", {"NamedInsured_NCCIRiskIdentifier_A": "123456789"})
        assert out == {}

    def test_a_building_number_is_never_a_floor_count(self):
        out, _ = _guard("ACORD_130", {"Location_HighestFloorCount_A": "001",
                                      "Location_HighestFloorCount_B": "2"})
        assert set(out) == {"Location_HighestFloorCount_A"}

    def test_a_territory_code_is_never_a_street_number(self):
        out, _ = _guard("ACORD_127", {"Vehicle_PhysicalAddress_LineOne_A": "111 Denver",
                                      "Vehicle_PhysicalAddress_LineOne_B": "4800 Main St"})
        assert set(out) == {"Vehicle_PhysicalAddress_LineOne_A"}

    def test_a_page_of_ocr_is_not_an_explanation(self):
        dump = ("Vehicle Schedule of Coverages\nInsured Name: Effective Date: Policy Number:\n"
                "CHOICE ELECTRIC LLC 01/01/2025\n\nVeh # Description:Year,Make,Model")
        out, _ = _guard("ACORD_127", {
            "CommercialVehicleLineOfBusiness_AnyVehiclesOwnedNotScheduledExplanation_A": dump})
        assert list(out.values())[0].startswith("RAW_TEXT_BLOCK")
        out, _ = _guard("ACORD_127", {
            "CommercialVehicleLineOfBusiness_AnyVehiclesOwnedNotScheduledExplanation_A":
                "Two trailers are owned and listed on the schedule."})
        assert out == {}

    def test_a_liability_limit_is_never_med_pay(self):
        out, _ = _guard("ACORD_137_CO", {"Vehicle_MedicalPayments_PerPersonLimitAmount_A": "1,000,000"})
        assert list(out.values())[0].startswith("LIABILITY_LIMIT_IN_MED_PAY")
        out, _ = _guard("ACORD_137_CO", {"Vehicle_MedicalPayments_PerPersonLimitAmount_A": "5,000"})
        assert out == {}

    def test_a_prior_wc_carrier_writes_workers_comp(self):
        out, _ = _guard("ACORD_130", {"PriorCoverage_InsurerFullName_C": "TRAVELERS PROPERTY CASUALTY COMPANY OF AMERICA",
                                      "PriorCoverage_InsurerFullName_D": "ACE American Insurance Company",
                                      "PriorCoverage_InsurerFullName_A": "AMERISURE INSURANCE COMPANY",
                                      "PriorCoverage_InsurerFullName_B": "Unknown Mutual"})
        assert set(out) == {"PriorCoverage_InsurerFullName_C", "PriorCoverage_InsurerFullName_D"}

    def test_deterministic_values_are_never_judged(self):
        facts = {"dec_page_entries": copy.deepcopy(_ENTRIES)}
        m = {"ExcessUmbrella_EmployeeBenefits_EachEmployeeLimitAmount_A": "1,000,000"}
        assert ps._drop_misplaced_values(m, _schema("ACORD_131"), facts, _RAW, set(), "ACORD_131") == {}

    @pytest.mark.parametrize("facts", [None, {}, {"dec_page_entries": "x", "coverage_lines": 3}])
    def test_junk_never_raises(self, facts):
        ps._drop_misplaced_values({"X_A": "1"}, {}, facts, "", {"X_A"}, "")


class TestPriorMods:
    def _facts(self):
        return {"wc_xmod": "1.0800", "coverage_lines": copy.deepcopy(_LINES)}

    def test_a_mod_nothing_states_is_refused(self):
        m = {"PriorCoverage_ModificationFactor_A": "100%", "PriorCoverage_EffectiveYear_A": "2025"}
        out = ps._drop_unstated_prior_mods(m, self._facts(), {"PriorCoverage_ModificationFactor_A"})
        assert out and m["PriorCoverage_ModificationFactor_A"] is None

    def test_the_stated_mod_prints_for_its_own_term_only(self):
        m = {"PriorCoverage_ModificationFactor_A": "1.08", "PriorCoverage_EffectiveYear_A": "2025",
             "PriorCoverage_ModificationFactor_B": "1.08", "PriorCoverage_EffectiveYear_B": "2023"}
        out = ps._drop_unstated_prior_mods(m, self._facts(), {"PriorCoverage_ModificationFactor_A",
                                                              "PriorCoverage_ModificationFactor_B"})
        assert set(out) == {"PriorCoverage_ModificationFactor_B"}
        assert m["PriorCoverage_ModificationFactor_A"] == "1.08"

    def test_factor_reading(self):
        assert ps._stated_factor("1.0800") == 1.08
        assert ps._stated_factor("108%") == 1.08
        assert ps._stated_factor("100%") == 1.0
        assert ps._stated_factor("n/a") is None
