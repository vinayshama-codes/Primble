"""15 Sep 2026 - the items left after the Brent-prep round, fixed before the next run.

Owner decisions (15 Sep): follow Brent's own ACORD 125 answer key on page 1;
fix the four score-moving items (testing phase, no real users); leave the 126
borrowed-N residual; no extraction prompt change.

1. Signed PDFs: every value was invisible in Acrobat (NeedAppearances=false
   after fill_pdf removed each text box's appearance).
2. ACORD 125 page 1 is the policy being APPLIED FOR: the receiving carrier's
   CARRIER / NAIC / POLICY NUMBER, proposed dates = the next term (asked once
   the current term has ended), premiums blank unless known, QUOTE ticked; the
   current policies fill the prior-carrier grid.
3. auto_vehicle_use follows the declarations' own USE cell ("USE: NA").
4. One GL class's payroll exposure never becomes the total_payroll FACT.
5. ACORD 131 no longer docks Employers Liability on a no-WC package.
6. "Specified Causes of Loss" has its own covered-auto symbol key.
7. test_production_guards no longer leaves ReportLab stubbed for later tests.

Fixtures are the Orbin package's own shapes (live run 9, session 07bb6d10).
"""
import base64
import copy
import io
import json
import os
from datetime import datetime, timedelta

import pikepdf
import pytest
from PIL import Image

import services.extraction_service as es
import services.pdf_service as ps
from config.settings import TEMPLATE_DIR

HERE = os.path.dirname(os.path.abspath(__file__))
EMCC = "EMPLOYERS MUTUAL CASUALTY COMPANY"
EMCPC = "EMC Property & Casualty Company"


def _v(x):
    return x.get("value") if isinstance(x, dict) and "value" in x else x


def _schema(fid):
    with open(os.path.join(HERE, "..", "forms_schemas", f"{fid}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _d(days):
    return (datetime.now() + timedelta(days=days)).strftime("%m/%d/%Y")


# ── 1. A signed form still draws its values ──────────────────────────────────
def test_a_signed_form_lets_the_viewer_draw_its_values():
    path = os.path.join(TEMPLATE_DIR, "ACORD_125.pdf")
    data = {"NamedInsured_FullName_A": "ORBIN CONTRACTING LLC"}
    filled = ps.fill_pdf(path, data)
    buf = io.BytesIO()
    Image.new("RGB", (60, 20), "black").save(buf, "PNG")
    sig = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    signed = ps.inject_signature_into_pdf(path, data, {}, sig, existing_pdf_bytes=filled)
    pdf = pikepdf.open(io.BytesIO(signed))
    acro = pdf.Root["/AcroForm"]
    # fill_pdf removes every text appearance so the viewer draws the value at
    # the box's own font size - the signed copy must still let it.
    assert acro.get("/NeedAppearances") == True        # noqa: E712
    names = []

    def _walk(arr):
        for it in arr:
            names.append((str(it.get("/T", "")), str(it.get("/V", ""))))
            if "/Kids" in it:
                _walk(it["/Kids"])
    _walk(acro.get("/Fields", []))
    assert ("NamedInsured_FullName_A", "ORBIN CONTRACTING LLC") in names


# ── 2a. The proposed term ────────────────────────────────────────────────────
def _term_facts(eff, exp, renewal=None):
    mf = {"effective_date": {"value": eff, "confidence": "ai_high", "source": "ai"},
          "expiration_date": {"value": exp, "confidence": "ai_high", "source": "ai"}}
    if renewal:
        mf["is_renewal"] = renewal
    return mf


def _term_docs(eff, exp, role="dec_page"):
    return [{"doc_type": role, "facts": {"effective_date": eff, "expiration_date": exp}}]


class TestProposedTerm:
    def test_the_orbin_term_ended_so_it_is_prior_and_the_proposal_is_asked(self):
        mf = _term_facts("07/15/25", "07/15/26")          # the live facts' own printing
        es._route_renewal_dates(mf, _term_docs("07/15/25", "07/15/26"))
        assert "effective_date" not in mf and "expiration_date" not in mf
        assert _v(mf["prior_effective_date"]) == "07/15/25"
        assert _v(mf["prior_expiration_date"]) == "07/15/26"
        assert mf["prior_expiration_date"]["routed_from"] == "current_term"
        assert mf["renewal_dates_routed"] is True
        assert "effective_date" in mf[es.REJECTED_FACTS_KEY]
        assert "renewal_lines_expiring" not in mf       # never a "Renewal:" warning here

    def test_an_in_force_current_term_proposes_the_next_one(self):
        eff, exp = _d(-60), _d(305)
        mf = _term_facts(eff, exp)
        es._route_renewal_dates(mf, _term_docs(eff, exp))
        assert _v(mf["prior_effective_date"]) == eff and _v(mf["prior_expiration_date"]) == exp
        assert _v(mf["effective_date"]) == exp
        assert mf["effective_date"]["source"] == "derived"
        assert mf["effective_date"]["confidence"] == "low_confidence"
        assert mf["effective_date"]["derivation"]["rule"] == "next_term_after_current_policy"
        # A calendar-year term renews for a calendar year (17 Sep 2026). This
        # used to expect `exp + 365 days`, which is one day short whenever the
        # next term crosses 29 Feb - exactly the 07/31/2028 the live kit printed
        # for an 08/01/2027 renewal. A term that is not whole calendar months
        # keeps the day count.
        exp_d = datetime.strptime(exp, "%m/%d/%Y")
        eff_d = datetime.strptime(eff, "%m/%d/%Y")
        if eff_d.day == exp_d.day:
            try:
                nxt = exp_d.replace(year=exp_d.year + 1).strftime("%m/%d/%Y")
            except ValueError:                         # 29 Feb -> 28 Feb
                nxt = exp_d.replace(year=exp_d.year + 1, day=28).strftime("%m/%d/%Y")
        else:
            nxt = (exp_d + timedelta(days=365)).strftime("%m/%d/%Y")
        assert _v(mf["expiration_date"]) == nxt

    @pytest.mark.parametrize("role", ["quote", "application", "acord_form", "supplemental_application"])
    @pytest.mark.parametrize("span", [(-60, 305), (-500, -135)])
    def test_a_proposal_documents_term_is_the_proposal(self, role, span):
        eff, exp = _d(span[0]), _d(span[1])
        mf = _term_facts(eff, exp)
        before = copy.deepcopy(mf)
        es._route_renewal_dates(mf, _term_docs(eff, exp, role))
        assert mf == before

    def test_a_dec_and_a_quote_printing_one_term_is_the_proposal(self):
        eff, exp = _d(-60), _d(305)
        mf = _term_facts(eff, exp)
        before = copy.deepcopy(mf)
        es._route_renewal_dates(mf, _term_docs(eff, exp) + _term_docs(eff, exp, "quote"))
        assert mf == before

    def test_a_term_not_yet_begun_is_left(self):
        eff, exp = _d(30), _d(395)
        mf = _term_facts(eff, exp)
        before = copy.deepcopy(mf)
        es._route_renewal_dates(mf, _term_docs(eff, exp))
        assert mf == before

    def test_without_documents_only_the_renewal_rule_runs(self):
        eff, exp = _d(-500), _d(-135)
        mf = _term_facts(eff, exp)
        before = copy.deepcopy(mf)
        es._route_renewal_dates(mf)
        assert mf == before
        eff, exp = _d(-60), _d(305)
        mf = _term_facts(eff, exp, renewal="yes")
        before = copy.deepcopy(mf)
        es._route_renewal_dates(mf)
        assert mf == before

    def test_a_renewal_whose_term_ended_keeps_its_derived_proposal(self):
        eff, exp = _d(-500), _d(-135)
        mf = _term_facts(eff, exp, renewal="yes")
        es._route_renewal_dates(mf, _term_docs(eff, exp))
        assert _v(mf["effective_date"]) == exp
        assert mf["effective_date"]["derivation"]["rule"] == "renewal_routing_prior_expiration"

    def test_a_renewal_dec_in_force_now_proposes_the_next_term(self):
        eff, exp = _d(-60), _d(305)
        mf = _term_facts(eff, exp, renewal="yes")
        es._route_renewal_dates(mf, _term_docs(eff, exp))
        assert _v(mf["effective_date"]) == exp
        assert _v(mf["prior_expiration_date"]) == exp

    def test_a_stated_prior_term_is_never_overwritten(self):
        eff, exp = _d(-500), _d(-135)
        mf = _term_facts(eff, exp)
        mf["prior_effective_date"], mf["prior_expiration_date"] = "01/01/2020", "01/01/2021"
        es._route_renewal_dates(mf, _term_docs(eff, exp))
        assert mf["prior_effective_date"] == "01/01/2020"
        assert mf["prior_expiration_date"] == "01/01/2021"
        assert "effective_date" not in mf

    @pytest.mark.parametrize("junk", [None, "", "not a date", {"value": None}, 7, ["x"]])
    def test_junk_dates_never_raise(self, junk):
        mf = {"effective_date": junk, "expiration_date": junk}
        es._route_renewal_dates(mf, [{"doc_type": "dec_page", "facts": {"expiration_date": junk}}])
        es._route_renewal_dates(mf, "not a list")


# ── 2b. Page-one marking and the boxes it owns ───────────────────────────────
_LINES = [
    {"line": "General Liability", "carrier": EMCPC, "policy_number": "BBC7263 - 26", "premium": "$3,954.00"},
    {"line": "Automobile", "carrier": EMCC, "policy_number": "6E7-40-02---26", "premium": "$2,991.00"},
    {"line": "COVERED AUTOS LIABILITY", "carrier": EMCC, "policy_number": "6E7-40-02---26",
     "premium": "$ 1,496.00"},
    {"line": "Inland Marine", "carrier": EMCC, "policy_number": "6C7-40-02---26", "premium": "$300.00"},
    {"line": "Umbrella", "carrier": EMCC, "policy_number": "6J7-40-02---26", "premium": "$3,418.00"},
    {"line": "Property"},
]


def _dec_doc(**facts):
    base = {"carrier_name": EMCC, "total_policy_premium": "$10,663", "coverage_lines": copy.deepcopy(_LINES)}
    base.update(facts)
    return {"doc_type": "dec_page", "facts": base}


class TestPageOneMarking:
    def _mf(self, **over):
        mf = {"carrier_name": {"value": EMCC, "source": "ai"}, "total_policy_premium": "$10,663",
              "coverage_lines": copy.deepcopy(_LINES)}
        mf.update(over)
        return mf

    def test_a_policy_only_package_marks_all_three(self):
        mf = self._mf()
        assert es._mark_page_one_current_policy(mf, [_dec_doc()]) == ["carrier", "premium"]
        assert mf["carrier_is_current_policy"] is True
        assert mf["premium_is_current_policy"] is True
        assert mf["current_term_rows_ok"] is True

    def test_a_quote_names_the_receiving_carrier_and_its_premium(self):
        mf = self._mf()
        quote = {"doc_type": "quote", "facts": {"carrier_name": "Employers Mutual Casualty Co.",
                                                "total_policy_premium": "$11,200"}}
        assert es._mark_page_one_current_policy(mf, [_dec_doc(), quote]) == []
        assert "carrier_is_current_policy" not in mf and "premium_is_current_policy" not in mf
        assert mf["current_term_rows_ok"] is True           # the quote added no policies

    def test_a_quote_with_its_own_policies_keeps_the_grid_off(self):
        mf = self._mf()
        quote = {"doc_type": "quote", "facts": {"coverage_lines": [
            {"line": "General Liability", "carrier": "Travelers", "policy_number": "Q-100"}]}}
        es._mark_page_one_current_policy(mf, [_dec_doc(), quote])
        assert "current_term_rows_ok" not in mf

    def test_a_one_carrier_renewal_goes_back_to_that_carrier(self):
        rows = [dict(r, carrier=EMCC) for r in _LINES if r.get("carrier")]
        mf = self._mf(is_renewal="yes", coverage_lines=rows)
        es._mark_page_one_current_policy(mf, [_dec_doc()])
        assert "carrier_is_current_policy" not in mf

    def test_a_two_carrier_renewal_has_no_one_receiving_carrier(self):
        mf = self._mf(is_renewal="yes")
        es._mark_page_one_current_policy(mf, [_dec_doc()])
        assert mf["carrier_is_current_policy"] is True

    def test_a_person_entered_value_is_never_marked(self):
        mf = self._mf(carrier_name={"value": "Travelers", "source": "producer"},
                      total_policy_premium={"value": "$9,000", "source": "producer"})
        es._mark_page_one_current_policy(mf, [_dec_doc()])
        assert "carrier_is_current_policy" not in mf and "premium_is_current_policy" not in mf

    @pytest.mark.parametrize("mf,docs", [(None, None), ({}, "x"), ({"coverage_lines": "junk"}, [None, 3]),
                                         ({"carrier_name": EMCC}, [{"doc_type": "quote", "facts": None}])])
    def test_junk_never_raises(self, mf, docs):
        es._mark_page_one_current_policy(mf, docs)


class TestPageOneBoxes:
    def _facts(self, **over):
        f = {"_form_id": "ACORD_125", "carrier_name": {"value": EMCC, "source": "ai"},
             "carrier_naic": "21415", "policy_number": "6E7-40-02---26",
             "total_policy_premium": "$10,663", "coverage_lines": copy.deepcopy(_LINES)}
        f.update(over)
        return f

    @pytest.mark.parametrize("box", ["Insurer_FullName_A", "Insurer_NAICCode_A",
                                     "Policy_PolicyNumberIdentifier_A"])
    def test_the_current_carrier_is_not_the_receiving_one(self, box):
        f = self._facts(carrier_is_current_policy=True)
        assert ps._resolve_page_one_receiving_carrier(box, f) is None
        assert ps._is_authoritative_blank_field(box, f)

    def test_a_person_named_carrier_prints(self):
        f = self._facts(carrier_is_current_policy=True,
                        carrier_name={"value": "Travelers", "source": "producer"})
        assert ps._resolve_page_one_receiving_carrier("Insurer_FullName_A", f) is ps._SCHED_SKIP

    def test_unmarked_packages_and_other_forms_are_untouched(self):
        assert ps._resolve_page_one_receiving_carrier("Insurer_FullName_A", self._facts()) is ps._SCHED_SKIP
        for form in ("ACORD_25", "ACORD_126", "ACORD_131", "ACORD_101"):
            f = self._facts(carrier_is_current_policy=True, _form_id=form)
            assert ps._resolve_page_one_receiving_carrier("Insurer_FullName_A", f) is ps._SCHED_SKIP

    def test_page_one_through_the_stamper(self):
        schema = _schema("ACORD_125")
        marked = self._facts(carrier_is_current_policy=True, premium_is_current_policy=True)
        res = ps.map_facts_to_form(marked, schema, "ACORD_125")
        m = res[0] if isinstance(res, tuple) else res
        for box in ("Insurer_FullName_A", "Insurer_NAICCode_A", "Policy_Payment_EstimatedTotalAmount_A",
                    "CommercialVehicleLineOfBusiness_PremiumAmount_A",
                    "GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A"):
            assert m.get(box) in (None, "", "UNMATCHED"), (box, m.get(box))
        gaps = ps.compute_form_gaps("ACORD_125", schema, marked)
        assert "Insurer_FullName_A" not in set(gaps[1])      # never handed to the AI
        # ...and without the marks the current policy prints as before
        res = ps.map_facts_to_form(self._facts(), schema, "ACORD_125")
        m = res[0] if isinstance(res, tuple) else res
        assert m.get("Insurer_FullName_A") == EMCC
        assert ps._currency_to_int(m.get("CommercialVehicleLineOfBusiness_PremiumAmount_A")) == 2991

    def test_the_premium_box_prints_a_persons_figure(self):
        f = self._facts(premium_is_current_policy=True,
                        total_policy_premium={"value": "$9,000", "source": "producer"})
        assert ps._resolve_estimated_total("Policy_Payment_EstimatedTotalAmount_A", f) not in (None, ps._SCHED_SKIP)

    def test_status_is_quote_on_the_125_only(self):
        assert ps._resolve_policy_status("Policy_Status_QuoteIndicator_A", {"_form_id": "ACORD_125"}) == "Yes"
        assert ps._resolve_policy_status("Policy_Status_QuoteIndicator_A",
                                         {"_form_id": "ACORD_125", "is_renewal": "yes"}) is None
        assert ps._resolve_policy_status("Policy_Status_RenewIndicator_A",
                                         {"_form_id": "ACORD_125", "is_renewal": "yes"}) == "Yes"
        assert ps._resolve_policy_status("Policy_Status_IssueIndicator_A", {"_form_id": "ACORD_125"}) is None
        assert ps._resolve_policy_status("Policy_Status_QuoteIndicator_A", {"_form_id": "ACORD_131"}) is None
        assert ps._resolve_policy_status("Policy_Status_QuoteIndicator_A", {}) is None


# ── 2c. The prior-carrier grid: year one is the current programme ────────────
_RECORDS = [
    {"line": "auto", "carrier_name": EMCC, "policy_number": "6E7-40-02---26",
     "effective_date": "07/15/25", "expiration_date": "07/15/26", "granted": True},
    {"line": "general_liab", "carrier_name": EMCPC, "policy_number": "BBC7263 - 26",
     "effective_date": "07/15/2025", "expiration_date": "07/15/2026", "granted": True},
    {"line": "inland_marine", "carrier_name": EMCC, "policy_number": "6C7-40-02---26",
     "effective_date": "07/15/2025", "expiration_date": "07/15/2026", "granted": True},
    {"line": "umbrella", "carrier_name": EMCC, "policy_number": "6J7-40-02---26",
     "effective_date": "07/15/25", "expiration_date": "07/15/26", "granted": True},
]


def _grid_facts(records=None, **over):
    f = {"_form_id": "ACORD_125", "renewal_dates_routed": True, "current_term_rows_ok": True,
         "prior_effective_date": {"value": "07/15/25", "routed_from": "current_term"},
         "prior_expiration_date": {"value": "07/15/26", "routed_from": "current_term"},
         "_line_records": copy.deepcopy(records if records is not None else _RECORDS),
         "coverage_lines": copy.deepcopy(_LINES)}
    f.update(over)
    return f


def _cell(f, name):
    return ps._resolve_prior_coverage_cell(name, f)


class TestPriorCarrierGrid:
    def test_year_one_is_the_current_policies(self):
        f = _grid_facts()
        assert _cell(f, "PriorCoverage_PolicyYear_A") == "2025"
        assert _cell(f, "PriorCoverage_GeneralLiability_InsurerFullName_A") == EMCPC
        assert ps._norm_policy_no(_cell(f, "PriorCoverage_GeneralLiability_PolicyNumberIdentifier_A")) \
            == ps._norm_policy_no("BBC7263 - 26")
        assert _cell(f, "PriorCoverage_GeneralLiability_TotalPremiumAmount_A") == "$3,954.00"
        assert _cell(f, "PriorCoverage_GeneralLiability_EffectiveDate_A") == "07/15/2025"
        assert _cell(f, "PriorCoverage_GeneralLiability_ExpirationDate_A") == "07/15/2026"
        assert _cell(f, "PriorCoverage_Automobile_InsurerFullName_A") == EMCC
        # the auto LINE's premium, never its $1,496 liability part
        assert _cell(f, "PriorCoverage_Automobile_TotalPremiumAmount_A") == "$2,991.00"
        assert _cell(f, "PriorCoverage_Automobile_EffectiveDate_A") == "07/15/2025"
        # inland marine AND umbrella both belong to OTHER - one box cannot name both
        assert _cell(f, "PriorCoverage_OtherLine_InsurerFullName_A") is None
        assert _cell(f, "PriorCoverage_OtherLine_LineOfBusinessCode_A") is None
        assert _cell(f, "PriorCoverage_Property_InsurerFullName_A") is None
        assert _cell(f, "PriorCoverage_GeneralLiability_InsurerFullName_B") is None
        assert _cell(f, "PriorCoverage_PolicyYear_B") is None

    def test_one_other_line_names_itself(self):
        f = _grid_facts([r for r in _RECORDS if r["line"] != "inland_marine"])
        assert _cell(f, "PriorCoverage_OtherLine_LineOfBusinessCode_A") == "Umbrella"
        assert _cell(f, "PriorCoverage_OtherLine_InsurerFullName_A") == EMCC
        assert _cell(f, "PriorCoverage_OtherLine_TotalPremiumAmount_A") == "$3,418.00"

    @pytest.mark.parametrize("over", [
        {"renewal_dates_routed": False},                      # the term was not moved
        {"current_term_rows_ok": False},                      # a quote added policies
        {"prior_expiration_date": "07/15/26"},                # a prior term we did not move
        {"prior_expiration_date": {"value": "07/15/26"}},
    ])
    def test_the_current_policy_is_never_prior_otherwise(self, over):
        f = _grid_facts(**over)
        assert _cell(f, "PriorCoverage_GeneralLiability_InsurerFullName_A") is None
        assert _cell(f, "PriorCoverage_PolicyYear_A") is None

    def test_a_form_number_is_never_a_policy(self):
        recs = [dict(_RECORDS[1], policy_number="IM 7100 06 04")]
        assert _cell(_grid_facts(recs), "PriorCoverage_GeneralLiability_InsurerFullName_A") is None

    def test_a_stated_prior_coverage_schedule_still_wins(self):
        f = _grid_facts(prior_coverage_by_line=[
            {"line": "General Liability", "carrier": "Travelers", "policy_no": "TR-1",
             "effective": "07/15/2024", "expiration": "07/15/2025"}])
        assert _cell(f, "PriorCoverage_GeneralLiability_InsurerFullName_A") == "Travelers"

    def test_two_policies_in_one_box_leave_it_blank(self):
        f = _grid_facts(prior_coverage_by_line=[
            {"line": "General Liability", "carrier": "Travelers", "policy_no": "TR-1",
             "effective": "07/15/2024", "expiration": "07/15/2025"},
            {"line": "General Liability", "carrier": "Hartford", "policy_no": "HF-9",
             "effective": "07/15/2024", "expiration": "07/15/2025"}])
        assert _cell(f, "PriorCoverage_GeneralLiability_InsurerFullName_A") is None

    def test_one_policy_printed_twice_is_one_policy(self):
        f = _grid_facts(prior_coverage_by_line=[
            {"line": "General Liability", "carrier": "Travelers", "policy_no": "TR-1",
             "effective": "07/15/2024", "expiration": "07/15/2025"},
            {"line": "Commercial General Liability", "carrier": "Travelers", "policy_no": "TR-1",
             "effective": "07/15/2024", "expiration": "07/15/2025"}])
        assert _cell(f, "PriorCoverage_GeneralLiability_InsurerFullName_A") == "Travelers"

    @pytest.mark.parametrize("records", [None, "junk", [None, 3, {}], [{"line": None}]])
    def test_junk_records_never_raise(self, records):
        f = _grid_facts()
        f["_line_records"] = records
        _cell(f, "PriorCoverage_GeneralLiability_InsurerFullName_A")


# ── 2d. Through the merge: the live Orbin package's shape ────────────────────
def test_through_the_merge_the_orbin_package_asks_for_its_proposed_term():
    doc = {"doc_type": "dec_page", "filename": "orbin_policy.pdf", "text": "",
           "facts": {"applicant_name": "ORBIN CONTRACTING LLC",
                     "effective_date": "07/15/25", "expiration_date": "07/15/26",
                     "carrier_name": EMCC, "total_policy_premium": "$10,663",
                     "coverage_lines": copy.deepcopy(_LINES)},
           "flags": {}}
    mf, _flags = es.merge_facts([doc], doc)
    assert not _v(mf.get("effective_date")) and not _v(mf.get("expiration_date"))
    assert _v(mf["prior_expiration_date"]) == "07/15/26"
    assert mf.get("renewal_dates_routed") is True
    assert mf.get("carrier_is_current_policy") is True
    assert mf.get("premium_is_current_policy") is True


# ── 2e. A certificate documents the EXISTING policy (own-diff review) ────────
def _in_force_routed(**over):
    f = {"renewal_dates_routed": True,
         "effective_date": {"value": "10/01/2026", "source": "derived", "confidence": "low_confidence"},
         "expiration_date": {"value": "10/01/2027", "source": "derived", "confidence": "low_confidence"},
         "prior_effective_date": {"value": "10/01/2025", "routed_from": "current_term"},
         "prior_expiration_date": {"value": "10/01/2026", "routed_from": "current_term"},
         "policy_number": "GL-123456", "carrier_name": "Example Mutual",
         "coverage_lines": [{"line": "General Liability", "carrier": "Example Mutual",
                             "policy_number": "GL-123456", "premium": "$18,450"}]}
    f.update(over)
    return f


@pytest.mark.parametrize("form_id", ["ACORD_25", "ACORD_28"])
def test_a_certificate_never_prints_the_derived_proposal(form_id):
    schema = _schema(form_id)
    f = dict(_in_force_routed(), _form_id=form_id)
    res = ps.map_facts_to_form(f, schema, form_id)
    m = res[0] if isinstance(res, tuple) else res
    dates = {k: v for k, v in m.items() if ("EffectiveDate" in k or "ExpirationDate" in k) and v}
    assert not [k for k, v in dates.items() if "2027" in str(v)], dates
    if form_id == "ACORD_28":
        assert m.get("Policy_EffectiveDate_A") == "10/01/2025"
        assert m.get("Policy_ExpirationDate_A") == "10/01/2026"
    else:
        assert m.get("Policy_GeneralLiability_EffectiveDate_A") == "10/01/2025"
        assert m.get("Policy_GeneralLiability_ExpirationDate_A") == "10/01/2026"


def test_an_application_form_prints_the_proposal():
    schema = _schema("ACORD_126")
    f = dict(_in_force_routed(), _form_id="ACORD_126")
    res = ps.map_facts_to_form(f, schema, "ACORD_126")
    m = res[0] if isinstance(res, tuple) else res
    assert m.get("Policy_EffectiveDate_A") == "10/01/2026"


def test_an_in_force_umbrella_on_the_moved_term_is_not_the_proposal():
    schema = _schema("ACORD_131")
    f = dict(_in_force_routed(umbrella_effective_date="10/01/2025",
                              umbrella_expiration_date=(datetime.now() + timedelta(days=200)).strftime("%m/%d/%Y")),
             _form_id="ACORD_131")
    res = ps.map_facts_to_form(f, schema, "ACORD_131")
    m = res[0] if isinstance(res, tuple) else res
    assert m.get("Policy_EffectiveDate_A") == "10/01/2026"


def test_a_renewal_umbrella_dec_for_the_new_term_still_overrides():
    schema = _schema("ACORD_131")
    new_start = (datetime.now() + timedelta(days=20)).strftime("%m/%d/%Y")
    new_end = (datetime.now() + timedelta(days=385)).strftime("%m/%d/%Y")
    f = dict(_in_force_routed(umbrella_effective_date=new_start, umbrella_expiration_date=new_end),
             _form_id="ACORD_131")
    res = ps.map_facts_to_form(f, schema, "ACORD_131")
    m = res[0] if isinstance(res, tuple) else res
    assert m.get("Policy_EffectiveDate_A") == new_start


# ── 3. The vehicle use follows the dec's USE cell ────────────────────────────
def _use_facts(use, cells, source="ai"):
    return {"auto_vehicle_use": ({"value": use, "source": source, "confidence": "ai_high"}
                                 if use is not None else None),
            "dec_page_entries": [{"label": "USE", "value": c, "line_of_business": "Commercial Auto",
                                  "owner": "policy"} for c in cells]}


class TestVehicleUse:
    def test_use_na_drops_an_inferred_use(self):
        mf = _use_facts("service", ["NA"])
        assert es._gate_inferred_vehicle_use(mf) == "dropped"
        assert mf["auto_vehicle_use"] is None
        assert "auto_vehicle_use" in mf[es.REJECTED_FACTS_KEY]

    @pytest.mark.parametrize("cell", ["N/A.", "None", "-", "NA"])
    def test_every_printing_of_a_non_answer(self, cell):
        mf = _use_facts("commercial", [cell])
        es._gate_inferred_vehicle_use(mf)
        assert mf["auto_vehicle_use"] is None

    def test_a_named_use_becomes_the_cells_own_printing(self):
        mf = _use_facts("service", ["COMMERCIAL"])
        assert es._gate_inferred_vehicle_use(mf) == "replaced"
        assert mf["auto_vehicle_use"]["value"] == "COMMERCIAL"
        assert mf["auto_vehicle_use"]["source"] == "dec_entry"

    def test_an_agreeing_cell_changes_nothing(self):
        mf = _use_facts("commercial", ["Commercial"])
        before = copy.deepcopy(mf)
        assert es._gate_inferred_vehicle_use(mf) is None
        assert mf == before

    @pytest.mark.parametrize("source", ["producer", "client_arq", "derived"])
    def test_a_person_or_derived_value_is_never_touched(self, source):
        mf = _use_facts("service", ["NA"], source=source)
        es._gate_inferred_vehicle_use(mf)
        assert mf["auto_vehicle_use"]["value"] == "service"

    @pytest.mark.parametrize("cells", [[], ["NA", "COMMERCIAL"], ["SEE SCHEDULE"], ["7383"]])
    def test_no_single_reading_leaves_the_fact(self, cells):
        mf = _use_facts("service", cells)
        es._gate_inferred_vehicle_use(mf)
        assert mf["auto_vehicle_use"]["value"] == "service"

    @pytest.mark.parametrize("mf", [None, {}, {"auto_vehicle_use": ""}, {"auto_vehicle_use": 5},
                                    {"auto_vehicle_use": "x", "dec_page_entries": "junk"}])
    def test_junk_never_raises(self, mf):
        es._gate_inferred_vehicle_use(mf)


# ── 4. One GL class's payroll is not the business's total ────────────────────
class TestPayrollBackfill:
    _GL = [{"class_code": "91580", "exposure_amount": "$39,300", "basis": "Payroll"},
           {"class_code": "91585", "exposure_amount": "$350,000", "basis": "Total Cost"}]

    @pytest.mark.parametrize("printed", ["$39,300", "$350,000", "39,300.00"])
    def test_a_class_exposure_is_refused(self, printed):
        facts = {"gl_class_code_schedule": copy.deepcopy(self._GL)}
        es._backfill_empty_facts_from_entries(facts, [{"label": "Payroll", "value": printed, "owner": "policy"}])
        assert not _v(facts.get("total_payroll"))
        assert "total_payroll" in facts[es.REJECTED_FACTS_KEY]

    def test_a_real_total_still_backfills(self):
        facts = {"gl_class_code_schedule": copy.deepcopy(self._GL)}
        es._backfill_empty_facts_from_entries(facts, [{"label": "Payroll", "value": "$410,000", "owner": "policy"}])
        assert _v(facts["total_payroll"]) == "$410,000"

    def test_revenue_follows_the_same_rule(self):
        facts = {"gl_class_code_schedule": [{"class_code": "11288", "exposure_amount": "$9,300,000",
                                             "basis": "Sales"}]}
        es._backfill_empty_facts_from_entries(
            facts, [{"label": "Annual Revenue", "value": "$9,300,000", "owner": "applicant"}])
        assert not _v(facts.get("total_revenue"))

    def test_no_schedule_is_no_opinion(self):
        facts = {}
        es._backfill_empty_facts_from_entries(facts, [{"label": "Payroll", "value": "$39,300", "owner": "policy"}])
        assert _v(facts["total_payroll"]) == "$39,300"


# ── 5. ACORD 131: Employers Liability only where WC is carried ───────────────
class TestUmbrellaEmployersLiability:
    FACTS = {"umbrella_limit": "$1,000,000", "umbrella_sir": "$0",
             "gl_each_occurrence": "$1,000,000", "auto_liability_limit": "$1,000,000"}

    def _structural(self, flags, facts):
        from services.sqs_service import calculate_sqs
        f = dict(facts, _form_id="ACORD_131")
        r = calculate_sqs(f, flags, {}, _schema("ACORD_131"), ["ACORD_131"], [], [], 0, form_id="ACORD_131")
        return (r.get("breakdown") or {}).get("structural_completeness")

    def test_a_no_wc_package_is_not_docked_for_an_el_limit(self):
        no_wc = self._structural({"has_workers_comp": False}, self.FACTS)
        wc = self._structural({"has_workers_comp": True}, self.FACTS)
        assert no_wc is not None and wc is not None
        assert no_wc > wc

    def test_a_stated_el_limit_counts_either_way(self):
        with_el = dict(self.FACTS, employers_liability_limits="$500,000/$500,000/$500,000")
        assert self._structural({"has_workers_comp": False}, with_el) == \
            self._structural({"has_workers_comp": True}, with_el)


# ── 6. Specified Causes of Loss is its own coverage ──────────────────────────
class TestSpecifiedCausesOfLoss:
    def test_the_label_is_read_as_named_perils(self):
        from services import auto_symbols as sym
        assert sym.normalize_coverages("Physical Damage Specified Causes of Loss") == [sym.SPECIFIED_CAUSES]
        assert sym.normalize_coverage("SPEC C OF L") == sym.SPECIFIED_CAUSES
        assert sym.normalize_coverages("Physical Damage (Comprehensive and Collision)") == \
            [sym.COMPREHENSIVE, sym.COLLISION]
        assert sym.normalize_coverages("Physical Damage") == [sym.PHYSICAL_DAMAGE]

    def test_its_symbol_ticks_its_own_row_only(self):
        from services import auto_symbols as sym, state_auto_grid as sag
        facts = {"auto_covered_symbols": [{"coverage": "Liability", "symbols": [1]},
                                          {"coverage": "Physical Damage Specified Causes of Loss",
                                           "symbols": [7]}]}
        assert sag._designated(facts, sym.COMPREHENSIVE) == []
        assert sag._designated(facts, sym.COLLISION) == []
        assert sag._designated(facts, sag.SPECIFIED_CAUSES) == [7]
        generic = {"auto_covered_symbols": [{"coverage": "Physical Damage", "symbols": [7]}]}
        assert sag._designated(generic, sym.COMPREHENSIVE) == [7]
        assert sag._designated(generic, sym.COLLISION) == [7]

    def _pd_issue(self, rows):
        from services import cross_form_validator as cfv
        issues = cfv._check_auto_symbol_to_exposure_alignment(
            {"auto_covered_symbols": rows}, {"has_auto_coverage": True, "auto_has_physical_damage": True},
            {"ACORD_127"})
        return [str(i) for i in issues if "physical_damage_symbols_missing" in str(i)]

    def test_named_perils_answer_the_comprehensive_half(self):
        rows = [{"coverage": "Liability", "symbols": [1]},
                {"coverage": "Specified Causes of Loss", "symbols": [7]},
                {"coverage": "Collision", "symbols": [7]}]
        assert self._pd_issue(rows) == []

    def test_named_perils_never_answer_collision(self):
        rows = [{"coverage": "Liability", "symbols": [1]},
                {"coverage": "Specified Causes of Loss", "symbols": [7]}]
        found = self._pd_issue(rows)
        assert found and "collision" in found[0].split("found for:")[1]
        assert "comprehensive" not in found[0].split("found for:")[1].split(".")[0]


# ── 7. A stub never outlives the test module that needed it ──────────────────
def test_reportlab_is_the_real_library_for_every_later_test():
    import reportlab.platypus as platypus
    assert hasattr(platypus, "SimpleDocTemplate")
    src = open(os.path.join(HERE, "test_production_guards.py"), encoding="utf-8").read()
    assert "not _importable(_pkg)" in src
