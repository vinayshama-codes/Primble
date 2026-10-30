"""Second insurance-expert review, 30 Oct 2026 (Michelle).

1. ACORD 133's Notice of Assignment lists the insurers that REFUSED the risk;
   the stamper printed the current carrier there, and the reader took it back
   as the package carrier.
2. A form outside our 17 (ACORD 807 D&O) states the SUBMISSION's terms only for
   its own line: its renewal tick, payment plan and remarks are not the package's.
3. "Monthly Limit of Indemnity" printed as a column heading (blank / N/A) is not
   an Actual Loss Sustained BI basis; "Actual Loss Sustained: Not Covered" is not
   either.
"""
import json

import pytest

from services.acord_intake.read import boxes_to_facts
from services.acord_intake.reverse_map import box_targets


# ── 1. ACORD 133 rejecting insurer ───────────────────────────────────────────
def test_133_rejecting_insurer_never_prints_the_current_carrier():
    from services.pdf_service import map_facts_to_form
    schema = json.load(open("forms_schemas/ACORD_133_schema.json"))
    facts = {"carrier_name": "Pinnacol Assurance", "carrier_naic": "41190",
             "applicant_name": "Ridgeline Mechanical Services LLC", "has_workers_comp": True}
    mapped, _ = map_facts_to_form(facts, schema, form_id="ACORD_133", allow_llm=False)
    for row in "ABCD":
        v = mapped.get(f"WorkersCompensationNoticeOfAssignment_RejectingInsurer_FullName_{row}")
        assert v in (None, "", "UNMATCHED"), (row, v)


def test_133_rejecting_insurer_is_not_read_back_as_the_carrier():
    for row in "AB":
        tg = box_targets("ACORD_133", f"WorkersCompensationNoticeOfAssignment_RejectingInsurer_FullName_{row}")
        assert not any(t.get("fact") == "carrier_name" for t in tg), tg


# ── 2. outside form: the submission's terms stay with its own line ───────────
def _copy(form_id, boxes):
    return {"form_id": form_id, "copy": 1, "pages": [0], "kind": "transcriber",
            "boxes": dict(boxes), "kinds": {k: ("check" if "Indicator" in k else "text") for k in boxes},
            "box_page": {k: 1 for k in boxes}, "raw": {}, "confidence": {}, "source": "transcriber"}


@pytest.mark.parametrize("box", ["Policy_Status_RenewIndicator_A", "CommercialPolicy_RemarkText_A",
                                 "Policy_PaymentMethod_MethodDescription_A", "AdditionalRemark_RemarkText_A"])
def test_outside_form_never_states_the_submissions_terms(box):
    assert not any(t.get("fact") in ("is_renewal", "additional_remarks_text", "billing_plan")
                   for t in box_targets("ACORD_807", box)), box


def test_our_125_still_reads_its_renewal_tick_and_payment_plan():
    assert box_targets("ACORD_125", "Policy_Status_RenewIndicator_A")[0]["fact"] == "is_renewal"
    assert box_targets("ACORD_125", "Policy_PaymentMethod_MethodDescription_A")[0]["fact"] == "billing_plan"


def test_807_renewal_tick_and_remarks_feed_no_package_fact():
    facts, _ = boxes_to_facts([_copy("ACORD_807", {
        "NamedInsured_FullName_A": "Ridgeline Mechanical Services LLC",
        "Policy_Status_RenewIndicator_A": "X",
        "CommercialPolicy_RemarkText_A": "D&O / EPL / Fiduciary marketed with the 12/2026 package renewal",
        "Policy_PaymentMethod_MethodDescription_A": "Annual",
    })])
    assert not facts.get("is_renewal")
    assert not facts.get("additional_remarks_text")
    assert not facts.get("billing_plan")
    assert facts["applicant_name"]["value"] == "Ridgeline Mechanical Services LLC"


def test_807_kit_boxes_feed_only_the_insured_and_producer_name():
    boxes = ["NamedInsured_FullName_A", "NamedInsured_FullName_B", "Policy_EffectiveDate_A",
             "Insurer_FullName_A", "Shareholder_FullName_A", "Subsidiary_OrganizationName_A",
             "BusinessInformation_DirectorOrOfficer_FullName_A",
             "FinancialStatement_CurrentYear_TotalRevenueAmount_A", "DirectorsAndOfficersLineOfBusiness_RemarkText_A"]
    facts = {t.get("fact") for b in boxes for t in box_targets("ACORD_807", b) if t.get("fact")}
    assert facts <= {"applicant_name"}, facts


# ── 3. ALS vs a monthly-limitation heading ───────────────────────────────────
@pytest.mark.parametrize("text", [
    "BUSINESS INCOME Coinsurance 80% Limit $250,000\nMonthly Limit of Indemnity (Fraction):",
    "Business Income $250,000 Monthly Limit of Indemnity: N/A",
    "Business Income Actual Loss Sustained: Not Covered",
    "Business Income with Extra Expense $500,000  ALS - N/A",
])
def test_an_unelected_option_is_not_an_als_basis(text):
    from services.property_coverages import als_statement
    assert als_statement(text) is None


@pytest.mark.parametrize("text", [
    "Business Income Monthly Limit of Indemnity (Fraction): 1/3",
    "Business Income - Actual Loss Sustained, 12 months",
    "BUSINESS INCOME: 12 MONTHS ALS",
])
def test_an_elected_als_or_monthly_fraction_still_reads(text):
    from services.property_coverages import als_statement
    assert als_statement(text)


# ── 4. "Used in this package" only for a reading the merge kept ──────────────
def _807_doc(monkeypatch):
    from services.acord_intake import transcriber_intake as TI
    boxes = [{"name": n, "value": v, "page": 1, "confidence": 0.98} for n, v in [
        ("NamedInsured_FullName_A", "Ridgeline Mechanical Services LLC"),
        ("Producer_FullName_A", "Bluestem Risk Advisors LLC"),
        ("Policy_EffectiveDate_A", "01/15/2027"),
        ("FinancialStatement_CurrentYear_TotalRevenueAmount_A", "8,975,000"),
        ("BusinessInformation_DirectorOrOfficer_FullName_A", "Laura Kesler"),
        ("Policy_Status_RenewIndicator_A", "X"),
    ]]
    payload = {"forms": [{"form_id": "ACORD_807", "form_number": "807", "boxes": boxes}]}
    monkeypatch.setattr(TI, "read_elabels", lambda _d: payload)
    doc = {"facts": {"applicant_name": {"value": "Ridgeline Mechanical Services LLC"},
                     "producer_name": {"value": "Bluestem Risk Advisors LLC"}}}
    return TI, doc


def test_only_boxes_the_merge_kept_are_listed_as_used(monkeypatch):
    TI, doc = _807_doc(monkeypatch)
    pkg = {"applicant_name": {"value": "Ridgeline Mechanical Services LLC"},
           "producer_name": {"value": "Peak & Prairie Insurance Group"},     # the login outranks the form
           "effective_date": {"value": "12/01/2026"}, "total_revenue": {"value": "$8,450,000"}}
    vals = TI.form_values(doc, pkg)
    used = {u["box"] for u in vals["used"]}
    read = {r["box"] for r in vals["read"]}
    assert used == {"NamedInsured_FullName_A"}, used
    assert {"Producer_FullName_A", "Policy_EffectiveDate_A", "Policy_Status_RenewIndicator_A",
            "FinancialStatement_CurrentYear_TotalRevenueAmount_A",
            "BusinessInformation_DirectorOrOfficer_FullName_A"} <= read


def test_without_package_facts_the_documents_own_facts_decide(monkeypatch):
    TI, doc = _807_doc(monkeypatch)
    used = {u["box"] for u in TI.form_values(doc)["used"]}
    assert used == {"NamedInsured_FullName_A", "Producer_FullName_A"}
