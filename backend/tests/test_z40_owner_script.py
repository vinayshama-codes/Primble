"""Z40 (25 Oct 2026): the owner's script run in memory on package c5dc03ec found
two defects - Brent's Attachment C spreadsheet (snake_case column names) was not
typed as a loss run, and the loss-run coverage strip named the wrong years."""
from datetime import date

from services.extraction_service import classify_document, spreadsheet_claims_listing
from services.loss_history_state import loss_run_coverage

SHEET = (
    "Sheet: Primble_Choice_Electric_Synthet\n"
    "dataset | insured | line | carrier_reference | synthetic_claim_id | loss_date | first_made_date | "
    "reported_date | status | description_asset | paid_usd | reserve_usd | expense_usd | incurred_usd | is_simulated\n"
    "CONTROL | CHOICE ELECTRIC LLC | Business Auto | Amerisure Insurance Company | SIM-AUTO-001 | 03/13/2025 | | "
    "03/15/2025 | Closed | \"V009 | Collision\" | 12000 | 0 | 0 | 12000 | YES\n"
)


def test_snake_case_claims_header_is_a_loss_run():
    assert spreadsheet_claims_listing(SHEET)
    c = classify_document(SHEET, filename="Primble Choice Electric Synthetic Claims.xlsx")
    assert c["doc_type"] == "loss_run" and c["source"] == "spreadsheet_columns"


def test_snake_case_vehicle_schedule_is_still_not_a_loss_run():
    sheet = ("Sheet: Vehicles\nunit_id | vin | make | model | claim_count | paid_usd\n"
             "V1 | 1FT | Ford | F150 | 0 | 0\n")
    assert not spreadsheet_claims_listing(sheet)


def _run(doc_id, start, end):
    return {"doc_id": doc_id, "filename": doc_id + ".csv", "doc_type": "loss_run",
            "facts": {"loss_run_period_start": start, "loss_run_period_end": end,
                      "loss_run_valuation_date": "10/15/2026"}}


def test_coverage_names_the_latest_years_the_runs_reach():
    facts = {"effective_date": "01/01/2027", "years_in_business": "15"}
    one = loss_run_coverage([_run("a", "01/01/2021", "01/01/2025")], facts)
    if one["covered"]:
        assert one["years"][-1] == 2024
        assert one["years"] == list(range(2024 - one["covered"] + 1, 2025))
    both = loss_run_coverage([_run("a", "01/01/2021", "01/01/2025"),
                              _run("b", "01/01/2025", "01/01/2026")], facts)
    assert both["years"][-1] == 2025
    assert len(both["years"]) == both["covered"]


def test_the_loss_window_counts_back_from_the_latest_ended_documented_term():
    """Live c5dc03ec, 25 Oct 2026: the decs' 2025-26 term ended 01/01/2026, the
    proposed term rolled to 2027; runs reaching 01/01/2026 cover all 5 years."""
    from datetime import date
    from services.loss_history_state import loss_window_start as w
    today = date(2026, 10, 25)
    rolled = {"effective_date": "01/01/2027", "expiration_date": "01/01/2028",
              "prior_expiration_date": "01/01/2026"}
    assert w(rolled, today) <= date(2021, 1, 1)
    # A term in force today keeps today's anchor (or its own start).
    in_force = {"effective_date": "11/01/2025", "expiration_date": "11/01/2026",
                "prior_expiration_date": "11/01/2025"}
    assert w(in_force, today) >= date(2020, 8, 1)
    # Nothing ended within two years: today stands.
    assert w({}, today) == w({"prior_expiration_date": "01/01/2023"}, today)


def test_an_insurer_address_printed_on_two_lines_or_under_its_logo_is_the_insurers():
    """Live f575160b, 25 Oct 2026: Amerisure's head office printed street / city on
    two lines under its name; Travelers' under its OCR'd logo "TRAVELERSJ"."""
    from services.insured_scope import address_is_a_party_office as office
    dec = ("COMMON POLICY DECLARATIONS\nAMERISURE INSURANCE COMPANY\n26777 HALSTED ROAD\n"
           "FARMINGTON HILLS, MI 48331-3586\nNAMEDINSURED:\n")
    assert office("26777 HALSTED ROAD FARMINGTON HILLS, MI 48331-3586", [dec])
    logo = "[Embedded image text - page 1]\nTRAVELERSJ\nOne Tower Square, Hartford, Connecticut 06183\n"
    carriers = ["TRAVELERS PROPERTY CASUALTY COMPANY OF AMERICA"]
    assert office("One Tower Square, Hartford, Connecticut 06183", [logo], party_names=carriers)
    # The insured's own two-line address is never an office.
    own = "NAMED INSURED:\nCHOICE ELECTRIC LLC\n1234 W COLFAX AVE\nDENVER, CO 80204\n"
    assert not office("1234 W COLFAX AVE DENVER, CO 80204", [own], party_names=carriers)
    # A carrier name that is not the one above does not count.
    other = "ZEBRA LOGISTICS\nOne Tower Square, Hartford, Connecticut 06183\n"
    assert not office("One Tower Square, Hartford, Connecticut 06183", [other], party_names=carriers)


def test_a_loss_run_period_total_is_not_a_claim_and_money_is_counted_once():
    """Live f575160b, 25 Oct 2026: the test CSVs' year lines ("2025-2026 | All lines |
    12 | ... | 322650") were counted as claims (14, not 12), and each claim's paid,
    reserve, incurred and amount were all added ($625,050 for a $322,650 file)."""
    from services.loss_history_state import asserted_claims, claim_rows
    claims = [{"claim_number": f"SIM-{i}", "date": "03/13/2025", "line_of_business": "Auto",
               "paid": "100", "reserved_amount": "50", "amount": "150"} for i in range(3)]
    total = {"line_of_business": "All lines", "paid": "300", "reserved_amount": "150", "amount": "450",
             "description": "2025-2026 | All lines | 3 | 300 | 150 | 0 | 450"}
    facts = {"loss_history": {"value": claims + [total], "source": "ai"}}
    assert asserted_claims(facts) == (3, 450.0)
    assert len(claim_rows(claims + [total])) == 3
    # A real claim on "All lines" with its own number stays a claim.
    assert claim_rows([{"claim_number": "X1", "line_of_business": "All lines", "amount": "10"}])


def test_a_spreadsheet_loss_runs_claim_cells_are_read_off_the_sheet():
    """Live f575160b, 25 Oct 2026: extraction dropped the expense column and blanked
    a printed "NOT PROVIDED" first-made date, so two planted mistakes went unseen."""
    from services.extraction_service import fill_claim_rows_from_spreadsheet as fill
    text = ("Sheet: Claims\n"
            "synthetic_claim_id | loss_date | first_made_date | reported_date | paid_usd | reserve_usd | expense_usd | incurred_usd\n"
            'SIM-PKG-005 | 10/02/2025 |  | 10/05/2025 | 8900 | 0 | 400 | 9200\n'
            "SIM-EPL-001 | 04/10/2025 | NOT PROVIDED | 07/04/2025 | 10000 | 52000 | 8000 | 70000\n")
    rows = [{"claim_number": "SIM-PKG-005", "paid": "8900", "amount": "9200"},
            {"claim_number": "SIM-EPL-001", "paid": "10000", "first_made_date": None}]
    doc = {"filename": "claims.xlsx", "doc_type": "loss_run", "text": text,
           "facts": {"loss_history": {"value": rows, "source": "ai"}}}
    assert fill(doc)
    assert rows[0]["expense"] == "400" and rows[0]["incurred"] == "9200"
    assert rows[1]["first_made_date"] == "NOT PROVIDED"
    # A person's table and a non-spreadsheet document are never touched.
    doc2 = {**doc, "facts": {"loss_history": {"value": [dict(rows[0])], "source": "producer"}}}
    assert fill(doc2) == []
    assert fill({**doc, "filename": "run.pdf", "text": "Policy page 1"}) == []


def test_an_empty_sheet_cell_clears_a_value_the_reading_invented():
    """SIM-WC-001: the sheet's reserve cell is empty (open, no reserve); the reading
    had put a reserve there, so the "open with no reserve" check could not fire."""
    from services.extraction_service import fill_claim_rows_from_spreadsheet as fill
    text = ("claim_number | loss_date | reported_date | paid | reserve | incurred\n"
            "SIM-WC-001 | 02/19/2025 | 02/20/2025 | 18000 |  | 27400\n")
    rows = [{"claim_number": "SIM-WC-001", "paid": "18000", "reserved_amount": "9400"}]
    doc = {"filename": "c.csv", "doc_type": "loss_run", "text": text,
           "facts": {"loss_history": {"value": rows, "source": "ai"}}}
    fill(doc)
    assert rows[0]["reserved_amount"] is None and rows[0]["paid"] == "18000"


def test_an_empty_sheet_cell_clears_the_word_null_too():
    from services.extraction_service import fill_claim_rows_from_spreadsheet as fill
    text = ("claim_number | loss_date | paid | reserve | incurred\n"
            "SIM-WC-001 | 02/19/2025 | 18000 |  | 27400\n")
    rows = [{"claim_number": "SIM-WC-001", "paid": "18000", "reserved_amount": "null"}]
    fill({"filename": "c.csv", "doc_type": "loss_run", "text": text,
          "facts": {"loss_history": {"value": rows, "source": "ai"}}})
    assert rows[0]["reserved_amount"] is None


def test_a_name_without_its_legal_form_is_the_same_insured():
    """Michelle's note "Choice Electric" vs "CHOICE ELECTRIC LLC" dropped her
    payroll / staff / revenue as another insured's (live f575160b)."""
    from services.insured_scope import _same_entity as same
    assert same("Choice Electric", "CHOICE ELECTRIC LLC") is True
    assert same("Choice Electric, L.L.C.", "Choice Electric") is True
    assert same("Choice Electric LLC", "Choice Electric Inc") is False
    assert same("Harborline Plumbing", "CHOICE ELECTRIC LLC") is False


def test_an_ai_no_on_a_topic_the_document_never_mentions_is_dropped():
    from services.extraction_service import drop_unmentioned_ai_yes_no as drop
    doc = {"text": "Met with Eric. Hired and non-ownership liability included. Agreed value applies.",
           "facts": {"cyber_controls_mfa": {"value": "False", "source": "ai"},
                     "agreed_value_endorsement": {"value": "False", "source": "ai"},
                     "non_owned_auto_indicator": {"value": "Yes", "source": "ai"},
                     "cyber_controls_backups": {"value": "False", "source": "producer"}}}
    assert drop(doc) == ["cyber_controls_mfa"]
    assert "agreed_value_endorsement" in doc["facts"] and "non_owned_auto_indicator" in doc["facts"]
    assert "cyber_controls_backups" in doc["facts"]               # a person's answer stays


def test_an_ownership_change_is_read_into_the_questionnaire_fact():
    from services.extraction_service import read_ownership_change as read
    doc = {"facts": {}, "text": "HE PURCHASED THE COMPAY TATUAG OF 2024 IM A SBA LOAM."}
    assert read(doc) == "Business purchased by the current owner in 2024 (SBA loan)"
    assert read({"facts": {}, "text": "If you acquire a company, coverage applies."}) is None
    kept = {"facts": {"qn_ownership_changes": {"value": "No", "source": "producer"}},
            "text": "He bought the business in 2019."}
    assert read(kept) is None


def test_a_loss_run_is_never_a_source_of_a_policy_record():
    """Live f575160b: claims files naming "Business Auto" became sources of the
    redacted auto policy, which lost its own-declarations standing and dropped
    out of the policies table."""
    from services.extraction_service import _record_sources
    dec = {"filename": "Auto Dec.pdf", "doc_type": "dec_page",
           "facts": {"coverage_lines": {"value": [{"line": "Commercial Automobile Coverage Part",
                                                   "carrier": "Amerisure"}], "source": "ai"}}}
    run = {"filename": "claims.csv", "doc_type": "loss_run",
           "facts": {"coverage_lines": {"value": [{"line": "Business Auto", "carrier": "Amerisure"}],
                                        "source": "ai"}}}
    assert _record_sources("auto", set(), [dec, run], carriers=["Amerisure"]) == ["Auto Dec.pdf"]


def test_a_zero_amount_is_never_an_invented_no():
    from services.extraction_service import drop_unmentioned_ai_yes_no as drop
    doc = {"text": "SELF-INSURED RETENTION: $0", "facts": {"umbrella_sir": {"value": "0", "source": "ai"}}}
    assert drop(doc) == [] and doc["facts"]["umbrella_sir"]["value"] == "0"
