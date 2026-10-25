"""Z42 review A (25 Oct 2026) - edge cases found in the Z40 / Z41 lane 1 work.

Each test is a case the first cut got wrong; the "still" tests pin what the
fix must keep."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import extraction_service as es
from services import loss_history_state as lh
from services import schedule_capture as sc
from services.insured_scope import address_is_a_party_office
from utils.helpers import _parse_address


# 1. A claim described "Total loss of vehicle" is a claim, not a period total.
def test_total_loss_claim_is_a_claim():
    row = {"description": "Total loss of vehicle", "paid": "25000"}
    assert not lh._row_is_a_period_total(row)
    assert lh._row_states_a_claim(row)
    assert lh._row_states_a_claim({"description": "Summary judgment defense costs", "paid": "1000"})


def test_period_total_labels_still_totals():
    for label in ("All lines", "Total", "Totals", "Grand Total", "Subtotal 2025",
                  "Summary:", "Total All Lines", "TOTAL LOSSES 2025"):
        assert lh._row_is_a_period_total({"description": label}), label
    # a claim number still makes it a claim
    assert not lh._row_is_a_period_total({"description": "Total", "claim_number": "C1"})


# 2. A generic tail ("INSURANCE COMPANY") is never completed to a carrier.
def test_generic_carrier_tail_not_completed():
    known = ["AMERISURE MUTUAL INSURANCE COMPANY", "TRAVELERS PROPERTY CASUALTY COMPANY OF AMERICA"]
    for tail in ("INSURANCE COMPANY", "MUTUAL INSURANCE COMPANY", "COMPANY OF AMERICA",
                 "CASUALTY COMPANY OF AMERICA"):
        assert es._complete_carrier_name(tail, known) == tail
    # a distinctive word still completes
    hsb = ["HARTFORD STEAM BOILER INSPECTION AND INSURANCE COMPANY"]
    assert es._complete_carrier_name("STEAM BOILER INSPECTION AND INSURANCE COMPANY", hsb) == hsb[0]


def test_underlying_schedule_fold_still_rejoins_split_carrier():
    rows = [{"line": "UMBRELLA LIABILITY", "limit": "5,000 EACH OCCURRENCE", "carrier": "AMERISURE"},
            {"line": "PERS/ADV INJURY", "limit": "5,000", "carrier": "MUTUAL INS"},
            {"line": "GENERAL AGGREGATE", "limit": "5,000", "carrier": "URANCE COM"},
            {"line": "PROD/COMP OPS AGG", "limit": "5,000", "carrier": "PANY"}]
    docs = [{"filename": "x", "facts": {"underlying_policies": rows}},
            {"filename": "a", "facts": {"carrier_name": "AMERISURE MUTUAL INSURANCE COMPANY"}}]
    es.repair_underlying_schedules(docs)
    out = docs[0]["facts"]["underlying_policies"]
    assert len(out) == 1 and out[0]["carrier"] == "AMERISURE MUTUAL INSURANCE COMPANY"


# 3. One carrier printing "Umbrella / Excess" and "Umbrella" in two spellings is one policy.
def test_excess_layer_not_named_for_one_carrier_spelled_twice():
    docs = [{"filename": "a", "facts": {"coverage_lines": [
                {"line": "Umbrella / Excess Liability", "carrier": "AMERISURE MUTUAL INS CO"}]}},
            {"filename": "b", "facts": {"coverage_lines": [
                {"line": "Commercial Umbrella", "carrier": "Amerisure Mutual"}]}}]
    assert es.name_the_excess_layer(docs) == []
    assert docs[0]["facts"]["coverage_lines"][0]["line"] == "Umbrella / Excess Liability"


def test_excess_layer_still_named_for_another_carrier():
    docs = [{"filename": "a", "facts": {"coverage_lines": [
                {"line": "Umbrella / Excess Liability", "carrier": "Travelers Property Casualty"}]}},
            {"filename": "b", "facts": {"coverage_lines": [
                {"line": "Commercial Umbrella", "carrier": "Amerisure Mutual"}]}}]
    assert es.name_the_excess_layer(docs)
    assert docs[0]["facts"]["coverage_lines"][0]["line"] == "Excess Liability"


# 4. An ownership change is the business changing hands - not equipment, not a denial.
def test_ownership_change_false_positives():
    for text in ("We purchased the business equipment in 2019.",
                 "The insured has not purchased the business; founded 2010."):
        assert es.read_ownership_change({"text": text, "facts": {}}) is None, text
    v = es.read_ownership_change({"text": "He purchased the company in January of 2024 with an SBA loan.",
                                  "facts": {}})
    assert v == "Business purchased by the current owner in January 2024 (SBA loan)"


# 5. A sentence above the insured's address that names an insurer is no logo.
def test_prose_line_above_is_not_an_insurer_logo():
    text = ("This policy is issued by Travelers Indemnity Company\n"
            "                                                      4801 Lima St, Denver, CO 80239\n")
    assert not address_is_a_party_office("4801 Lima St, Denver, CO 80239", [text],
                                          own_names=["Choice Electric LLC"],
                                          party_names=["Travelers Property Casualty Company of America"])
    logo = "TRAVELERSJ\nOne Tower Square, Hartford, CT 06183\n"
    assert address_is_a_party_office("One Tower Square, Hartford, CT 06183", [logo],
                                      party_names=["Travelers Property Casualty Company of America"])


# 6. A postal code beside a country is a ZIP, never a street.
def test_pin_only_and_city_pin_addresses():
    assert _parse_address("201301, India") == {"zip": "201301"}
    assert _parse_address("Noida 201301, India") == {"city": "Noida", "zip": "201301"}
    assert _parse_address("123 India St, San Diego, CA 92101")["state"] == "CA"
    assert _parse_address("New Delhi, Delhi 110001, India")["zip"] == "110001"


# 7. The claims checks' evidence columns are the producer's, never the insured's.
def test_loss_table_evidence_columns_are_producer_only():
    cols = {c["key"]: c for c in sc.SCHEDULE_DEFS["loss_history"]["columns"]}
    for k in ("first_made_date", "expense", "incurred", "claim_number"):
        assert cols[k].get("producer_only") and cols[k].get("evidence_only"), k
    # the first seven stay where a header-less import puts them
    assert list(cols)[:7] == ["date", "line_of_business", "description", "paid",
                              "reserved_amount", "claim_date", "open_code"]
    rows = sc.client_rows("loss_history", [{"date": "01/01/2024", "claim_number": "C1", "expense": "5"}])
    assert "claim_number" not in rows[0] and "expense" not in rows[0]
