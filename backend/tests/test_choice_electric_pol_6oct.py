"""Choice Electric (Brent + Michelle, 5 Oct 2026) - policy identity and Data
Consistency fixes (POL area, 6 Oct 2026).

Replays the client's stored per-document facts (session ca93ed8f, VINs masked,
`tests/fixtures/choice_electric_pol_6oct.json`) through the real merge and the
real Data Consistency engine, plus unit cases for every rule's edges.
"""
import copy
import json
import os
import random
import string

import pytest

from services import extraction_service as es
from services import normalization as norm
from services import underwriting_consistency as uc
from services.lob_canon import canon_line, umbrella_layer

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "choice_electric_pol_6oct.json")


def _docs(order="stored"):
    docs = copy.deepcopy(json.load(open(_FIXTURE))["docs"])
    return list(reversed(docs)) if order == "reversed" else docs


def _merge(order="stored"):
    docs = _docs(order)
    primary = es.select_primary_truth(docs)
    mf, flags = es.merge_facts(docs, primary)
    return mf, flags, docs


@pytest.fixture(scope="module")
def merged():
    return _merge()


def _v(mf, key):
    return es._fv(mf, key)


# =============================================================================
# 1. A policy number carries a digit, and a form number is never one
# =============================================================================
@pytest.mark.parametrize("value", ["COMMERCIAL AUTO", "SEE SCHEDULE", "N/A", "TBD", "PENDING"])
def test_a_value_with_no_digit_is_never_a_policy_number(value):
    assert norm.is_not_a_policy_number(value)
    # ...and no label rescues it
    assert norm.is_not_a_policy_number(value, [{"label": "POLICY NUMBER", "value": value}])


@pytest.mark.parametrize("form", ["IL DS 71 05 02 08", "CP DS 70 00 09 06", "CU DS 71 02 04 14",
                                  "CG T0 96 04 17", "IL T8 01 01 01", "CG D0 31 10 91",
                                  "IL N 020 09 03", "PN T4 54 01 08"])
def test_a_form_number_with_a_series_designator_is_a_form_number(form):
    assert norm.looks_like_a_form_number(form)
    assert norm.is_not_a_policy_number(form)
    assert es._not_a_contract_number(form)


@pytest.mark.parametrize("policy", ["BBC7263 - 26", "6E7-40-02---26", "CPP1234567", "POL123",
                                    "BOP 7654321 01 26", "AB 12345678", "SIM-7730418", "0482854"])
def test_real_policy_numbers_survive(policy):
    assert not norm.looks_like_a_form_number(policy)
    assert not norm.is_not_a_policy_number(policy)


def test_twenty_thousand_policy_shapes_never_read_as_a_designator_form():
    rng = random.Random(6)
    shapes = ["LLLddddddd", "LLL-dddddd-dd", "dLd-dd-dd---dd", "LLLdddd-dd", "LL dddddddd",
              "LLLdddddd", "LL-ddd-ddd", "dd-LL-dddddd-d", "LL L ddddddd", "LLL dddd dd"]
    for _ in range(20000):
        v = "".join(rng.choice(string.ascii_uppercase) if c == "L"
                    else rng.choice(string.digits) if c == "d" else c
                    for c in rng.choice(shapes))
        assert not norm._DESIGNATOR_FORM_NUMBER_RE.match(v), v


def test_a_labelled_form_number_is_a_contract_unless_it_is_the_page_footer():
    entries = [{"label": "POLICYNUMBER", "value": "IL DS 71 05 02 08"}]
    text = ("POLICYNUMBER: IL DS 71 05 02 08\nCOMMON POLICY DECLARATIONS\n"
            "IL DS 71 05 02 08 INSURED COPY Page 1of2 o\nPage2of2 IL DS 71 05 02 08 o\n")
    assert not norm.is_not_a_policy_number("IL DS 71 05 02 08", entries)       # no text: label wins
    assert norm.is_not_a_policy_number("IL DS 71 05 02 08", entries, text)     # footer: form
    # a printed contract that is not form-shaped is never refused by the footer
    entries2 = [{"label": "Policy Number", "value": "BBC7263-26"}]
    assert not norm.is_not_a_policy_number("BBC7263-26", entries2, "BBC7263-26 Page 1 of 3")


def test_a_label_reading_its_neighbour_is_not_a_contract():
    contracts, _ = norm.labelled_identifiers([
        {"label": "POLICY NUMBER", "value": "EFFECTIVE DATE 01/01/2025"},
        {"label": "POLICY NO.", "value": "X If Supplemental Declarations Is Attached"},
        {"label": "Policy Number", "value": "6E7-40-02---26"}])
    assert contracts == {"6E7400226"}


def test_the_per_document_scrub_clears_scalars_and_rows():
    facts = {"policy_number": {"value": "COMMERCIAL AUTO", "source": "ai"},
             "coverage_lines": [{"line": "Commercial Auto", "policy_number": "COMMERCIAL AUTO"}],
             "dec_page_entries": [{"label": "POLICYNUMBER", "value": "IL DS 71 05 02 08",
                                   "policy_number": "IL DS 71 05 02 08"}],
             "prior_policy_number": "IL DS 71 05 02 08"}
    text = "POLICYNUMBER: IL DS 71 05 02 08\nIL DS 71 05 02 08 INSURED COPY Page 1of2\n"
    es._scrub_non_contract_identifiers(facts, text)
    assert facts["policy_number"]["value"] == ""
    assert facts["policy_number"]["source"] == "ai"
    assert facts["coverage_lines"][0]["policy_number"] is None
    assert facts["dec_page_entries"][0]["policy_number"] is None
    assert facts["prior_policy_number"] == ""


def test_the_replay_keeps_no_redaction_label_or_form_number_as_a_policy(merged):
    mf, _flags, docs = merged
    assert not _v(mf, "policy_number")
    for rec in mf["_line_records"]:
        assert rec.get("policy_number") in (None, "")
    for d in docs:
        for row in es._fv(d["facts"], "coverage_lines") or []:
            assert row.get("policy_number") in (None, "")


# =============================================================================
# 2. The excess layer is its own policy; unnumbered lines split by insurer
# =============================================================================
def test_the_umbrella_layer_reading():
    assert umbrella_layer("Excess (Following Form) Liability") == "excess"
    assert umbrella_layer("Commercial Excess Liability") == "excess"
    assert umbrella_layer("Commercial Liability Umbrella") == "umbrella"
    assert umbrella_layer("Excess Umbrella") == "umbrella"
    assert umbrella_layer("General Liability") is None
    assert canon_line("Excess (Following Form) Liability") == "umbrella"   # family unchanged


def test_ten_policies_plus_the_package_ebl_part(merged):
    mf, _flags, _docs = merged
    recs = {r["id"]: r for r in mf["_line_records"]}
    assert len(recs) == 11
    umb = [r for r in recs.values() if r["line"] == "umbrella"]
    by_layer = {r["layer"]: r for r in umb}
    assert set(by_layer) == {"umbrella", "excess"}
    assert by_layer["umbrella"]["carrier_name"] == "AMERISURE MUTUAL INSURANCE COMPANY"
    assert by_layer["umbrella"]["sources"] == ["25-26 Umbrella Policy.pdf"]
    assert by_layer["excess"]["carrier_name"] == "TRAVELERS PROPERTY CASUALTY COMPANY OF AMERICA"
    assert by_layer["excess"]["sources"] == ["25-26 Excess Umbrella Policy.pdf"]
    assert by_layer["excess"]["premium"] == 10692.0
    assert by_layer["umbrella"]["premium"] == 17082.0
    # the redacted Business Auto dec is still a policy (its own declarations)
    assert any(r["line"] == "auto" for r in recs.values())
    assert any(r["line"] == "employee_benefits" for r in recs.values())


def test_records_do_not_depend_on_upload_order():
    a = sorted(r["id"] for r in _merge("stored")[0]["_line_records"])
    b = sorted(r["id"] for r in _merge("reversed")[0]["_line_records"])
    assert a == b


def _row(line, carrier=None, premium=None, number=None):
    return {"line": line, "carrier": carrier, "premium": premium, "policy_number": number,
            "effective_date": "01/01/2025", "expiration_date": "01/01/2026"}


def test_a_menu_row_of_another_company_is_a_mention():
    recs = es._build_line_records({"coverage_lines": [
        _row("Commercial Liability Umbrella", "AMERISURE MUTUAL INSURANCE COMPANY", "$17,082"),
        _row("Commercial Liability Umbrella", "AMERISURE INSURANCE COMPANY")]})
    assert [r["carrier_name"] for r in recs] == ["AMERISURE MUTUAL INSURANCE COMPANY"]


def test_two_unnumbered_insurers_on_one_line_are_two_records():
    recs = es._build_line_records({"coverage_lines": [
        _row("General Liability", "Alpha Casualty Company", "$1,000"),
        _row("General Liability", "Beta Indemnity Company", "$2,000")]})
    assert len(recs) == 2 and len({r["id"] for r in recs}) == 2


def test_one_insurer_printed_two_ways_is_one_record():
    recs = es._build_line_records({"coverage_lines": [
        _row("General Liability", "EMPLOYERS MUTUAL CASUALTY COMPANY", "$1,000"),
        _row("Commercial General Liability", "Employers Mutual Casualty Co")]})
    assert len(recs) == 1


def test_a_contract_printed_in_both_layers_is_one_policy():
    recs = es._build_line_records({"coverage_lines": [
        _row("Excess Liability", "Quillon Specialty", "$5,000", "XS-4410982"),
        _row("Umbrella Liab", "Quillon Specialty", None, "XS-4410982")]})
    assert len(recs) == 1


def test_a_single_umbrella_keeps_its_id():
    recs = es._build_line_records({"coverage_lines": [
        _row("Commercial Umbrella", "EMC", "$3,000", "6J7-40-02---26")]})
    assert [r["id"] for r in recs] == ["umbrella#6J7400226"]


def _store_and_values(rows, groups):
    mf = {"coverage_lines": rows}
    es._build_scoped_fact_store(mf)
    values = [{"display": g, "normalized": g.lower(), "sources": [{"raw": g, "doc_id": str(i)}]}
              for i, g in enumerate(groups)]
    return mf, values


def test_two_layers_are_scoped_not_two_policies_on_one_line():
    mf, values = _store_and_values(
        [_row("Commercial Liability Umbrella", "AMERISURE MUTUAL INSURANCE COMPANY", "$17,082"),
         _row("Excess (Following Form) Liability", "TRAVELERS PROPERTY CASUALTY COMPANY OF AMERICA", "$10,692")],
        ["AMERISURE MUTUAL INSURANCE COMPANY", "TRAVELERS PROPERTY CASUALTY COMPANY OF AMERICA"])
    scoped, reason, collided = uc._scope_from_store("carrier_name", values, mf)
    assert scoped and reason is None and not collided


def test_two_carriers_in_ONE_layer_still_conflict():
    mf, values = _store_and_values(
        [_row("Commercial Umbrella", "Alpha Casualty Company", "$1,000", "UMB-11111"),
         _row("Commercial Umbrella", "Beta Indemnity Company", "$2,000", "UMB-22222")],
        ["Alpha Casualty Company", "Beta Indemnity Company"])
    scoped, reason, collided = uc._scope_from_store("carrier_name", values, mf)
    assert not scoped and "two policies on the same coverage line" in reason
    assert collided == {"umbrella"}


def test_a_confirmation_for_one_layer_never_sets_the_other_aside():
    out = {"coverage_lines": [
        _row("Commercial Liability Umbrella", "AMERISURE MUTUAL INSURANCE COMPANY", "$17,082"),
        _row("Excess (Following Form) Liability", "TRAVELERS PROPERTY CASUALTY COMPANY OF AMERICA", "$10,692")]}
    assert uc._apply_scoped_confirmations(out, [("carrier_name", "umbrella", "Amerisure Mutual Insurance Company")])
    rows = {r["line"]: r for r in out["coverage_lines"]}
    assert rows["Excess (Following Form) Liability"]["carrier"] == "TRAVELERS PROPERTY CASUALTY COMPANY OF AMERICA"
    assert "_set_aside" not in rows["Excess (Following Form) Liability"]
    out2 = {"coverage_lines": copy.deepcopy(out["coverage_lines"])}
    assert uc._apply_scoped_confirmations(out2, [("policy_number", "umbrella~excess", "XS-123456")])
    rows2 = {r["line"]: r for r in out2["coverage_lines"]}
    assert rows2["Excess (Following Form) Liability"]["policy_number"] == "XS-123456"
    assert rows2["Commercial Liability Umbrella"].get("policy_number") is None


@pytest.mark.parametrize("scope,ok", [("umbrella", True), ("umbrella~excess", True),
                                      ("umbrella~umbrella", True), ("general_liab~excess", False),
                                      ("umbrella~bogus", False), ("nonsense", False)])
def test_a_layer_qualified_scope_is_a_known_scope(scope, ok):
    assert uc.known_line_scope(scope) is ok


# =============================================================================
# 3. Package scalars are not the first-uploaded document's
# =============================================================================
@pytest.mark.parametrize("order", ["stored", "reversed"])
def test_policy_facts_do_not_follow_upload_order(order):
    mf, _flags, _docs = _merge(order)
    assert _v(mf, "umbrella_limit") == "$5,000,000"       # the umbrella layer, not the excess
    assert _v(mf, "carrier_name") == "AMERISURE INSURANCE COMPANY"
    assert not _v(mf, "total_policy_premium")              # five policies, five totals: none is the package's
    assert "total_policy_premium" in (mf.get("_rejected_facts") or {})


def test_a_single_policy_package_is_untouched():
    doc = {"filename": "a.pdf", "doc_type": "dec_page", "text": "",
           "facts": {"umbrella_limit": "$4,000,000", "total_policy_premium": "$10,692",
                     "coverage_lines": [_row("Excess Liability", "Travelers", "$10,692")]}}
    other = {"filename": "b.pdf", "doc_type": "certificate", "text": "",
             "facts": {"umbrella_limit": "$4,000,000"}}
    mf, _ = es.merge_facts([doc, other], doc)
    assert _v(mf, "umbrella_limit") == "$4,000,000"
    assert _v(mf, "total_policy_premium") == "$10,692"


def test_two_documents_of_ONE_policy_that_disagree_are_left_to_the_picker():
    rows = [_row("Commercial Umbrella", "EMC", "$3,000", "6J7-40-02---26")]
    dec = {"filename": "dec.pdf", "doc_type": "dec_page", "text": "",
           "facts": {"umbrella_limit": "$3,000,000", "coverage_lines": copy.deepcopy(rows)}}
    coi = {"filename": "coi.pdf", "doc_type": "certificate", "text": "",
           "facts": {"umbrella_limit": "$1,000,000", "coverage_lines": copy.deepcopy(rows)}}
    auto = {"filename": "auto.pdf", "doc_type": "dec_page", "text": "",
            "facts": {"coverage_lines": [_row("Business Auto", "EMC", "$2,000", "6E7-40-02---26")]}}
    mf = {"umbrella_limit": "$3,000,000"}
    assert es._settle_policy_level_scalars(mf, [dec, coi, auto]) == []
    assert mf["umbrella_limit"] == "$3,000,000"


# =============================================================================
# 4. Data Consistency compares a policy's fact within that policy only
# =============================================================================
def test_no_premium_audit_website_or_schedule_card(merged):
    mf, flags, docs = merged
    res = uc.assess_underwriting_consistency(docs, mf, {}, flags=flags)
    cards = {f["fact_key"]: f["status"] for f in res["fields"]}
    for key in ("total_policy_premium", "audit_period", "carrier_website",
                "schedule_of_underlying_insurance", "policy_number"):
        assert cards.get(key) not in ("conflict",), (key, cards.get(key))
    assert cards["umbrella_limit"] == "scoped"
    assert cards["carrier_name"] == "scoped"
    carriers = {v["display"] for f in res["fields"] if f["fact_key"] == "carrier_name"
                for v in f["values"]}
    assert "AMERISURE MUTUAL INSURANCE COMPANY" in carriers
    assert res["conflict_count"] == 0


@pytest.mark.parametrize("key,expected", [
    ("total_policy_premium", True), ("audit_period", True), ("carrier_website", True),
    ("umbrella_limit", True), ("schedule_of_underlying_insurance", True), ("payment_plan", True),
    ("applicant_name", False), ("fein", False), ("total_revenue", False), ("mailing_address", False),
    ("policy_number", False), ("carrier_name", False), ("num_employees", False)])
def test_which_facts_belong_to_one_policy(key, expected):
    assert uc.is_policy_level_fact(key) is expected


def test_two_printings_on_ONE_policy_still_conflict():
    mf = {"_line_records": [{"id": "umbrella#6J74002026", "line": "umbrella", "policy_number": "6J7",
                             "sources": ["dec.pdf", "coi.pdf"], "granted": True}]}
    values = [{"display": "$3,000,000", "normalized": "3000000", "sources": [{"filename": "dec.pdf"}]},
              {"display": "$1,000,000", "normalized": "1000000", "sources": [{"filename": "coi.pdf"}]}]
    assert not uc._scope_by_policy_record("umbrella_limit", values, mf)


def test_an_unplaceable_source_decides_nothing():
    mf = {"_line_records": [{"id": "cyber#unnumbered", "line": "cyber", "carrier_name": "ACE",
                             "sources": ["cyber.pdf"], "granted": True}]}
    values = [{"display": "$4,162", "normalized": "4162", "sources": [{"filename": "cyber.pdf"}]},
              {"display": "$9,999", "normalized": "9999", "sources": [{"filename": "Client questionnaire"}]}]
    assert not uc._scope_by_policy_record("total_policy_premium", values, mf)


def test_an_insured_fact_is_never_scoped_by_policy():
    mf = {"_line_records": [
        {"id": "a#1", "line": "auto", "carrier_name": "X", "sources": ["a.pdf"], "granted": True},
        {"id": "b#2", "line": "cyber", "carrier_name": "Y", "sources": ["b.pdf"], "granted": True}]}
    values = [{"display": "ACME LLC", "sources": [{"filename": "a.pdf"}]},
              {"display": "ACME HOLDINGS INC", "sources": [{"filename": "b.pdf"}]}]
    assert not uc._scope_by_policy_record("applicant_name", values, mf)


def test_money_values_print_one_way_on_the_card():
    values = [{"display": "$ 10,692.00", "normalized": "10692"},
              {"display": "29,278.00", "normalized": "29278"},
              {"display": "Included", "normalized": "included"}]
    uc._display_money("total_policy_premium", "identity", values)
    assert [v["display"] for v in values] == ["$10,692", "$29,278", "Included"]
    names = [{"display": "Travelers"}]
    uc._display_money("carrier_name", "identity", names)
    assert names[0]["display"] == "Travelers"


def test_a_currency_conflict_card_shows_canonical_money():
    docs = [{"doc_id": "1", "filename": "a.pdf", "doc_type": "dec_page",
             "facts": {"total_revenue": "$ 1,200,000.00"}},
            {"doc_id": "2", "filename": "b.pdf", "doc_type": "dec_page",
             "facts": {"total_revenue": "950000"}}]
    res = uc.assess_underwriting_consistency(docs, {}, {})
    f = next(f for f in res["fields"] if f["fact_key"] == "total_revenue")
    assert f["status"] == "conflict"
    assert sorted(v["display"] for v in f["values"]) == ["$1,200,000", "$950,000"]
    assert sorted(s["raw"] for v in f["values"] for s in v["sources"]) == ["$ 1,200,000.00", "950000"]


# =============================================================================
# 5. Audit: an options row states nothing; a bare letter is not decoded
# =============================================================================
@pytest.mark.parametrize("text,period", [
    ("AUDIT PERIOD (IF APPLICABLE) ANNUALLY SEMI-ANNUALLY QUARTERLY MONTHLY", None),
    ("AuditPeriod (IfApplicable): Annually Semi-Annually Quarterly Monthly", None),
    ("Audit Period: [X] Monthly [ ] Annually", "Monthly"),
    ("ADJUSTMENTS OF PREMIUM SHALL BE MADE ANNUALLY", "Annual"),
    ("Premium audit .... Annual (audit period code A)", "Annual"),
    ("audit period code Q", "Quarterly"),
    ("Semi-annual", "Semi-annual"), ("semiannual", "Semi-annual"), ("bi-annual", "Semi-annual"),
    ("A", None), ("Auditable", None), ("old audit", None), ("12 months", None)])
def test_the_audit_period_reader(text, period):
    assert es._audit_period_of(text) == period


def test_the_merge_states_no_audit_period_from_an_options_row(merged):
    mf, _flags, _docs = merged
    # The package's and the auto dec's unticked rows state nothing; only the WC
    # page's "ADJUSTMENTS OF PREMIUM SHALL BE MADE ANNUALLY" is a statement.
    assert _v(mf, "audit_period") == "Annual"
    assert _v(mf, "audit_period") != "Semi-annual"


def test_the_fr125_prose_statement_still_reads():
    facts = {}
    es._prefer_submission_terms(facts, "Billing preference Direct bill\n"
                                       "Premium audit .... Annual (audit period code A)\n")
    assert es._fv(facts, "audit_period") == "Annual"


# =============================================================================
# 6. Extraction misreads, corrected per document
# =============================================================================
def _doc(facts, text=""):
    return {"filename": "d.pdf", "doc_type": "dec_page", "facts": facts, "text": text}


def test_a_street_address_is_not_a_website():
    d = _doc({"carrier_website": "One Tower Square, Hartford, Connecticut 06183",
              "applicant_website": "www.acme.com"})
    es._validate_document_fact_shapes(d)
    assert "carrier_website" not in d["facts"]
    assert d["facts"]["applicant_website"] == "www.acme.com"


@pytest.mark.parametrize("plan,kept", [("Blue I (B1) Dividend Plan", False),
                                        ("Retrospective Rating Plan", False),
                                        ("Monthly installments", True), ("10 pay", True),
                                        ("Annual - paid in full", True)])
def test_a_dividend_plan_is_not_a_payment_plan(plan, kept):
    d = _doc({"payment_plan": plan})
    es._validate_document_fact_shapes(d)
    assert ("payment_plan" in d["facts"]) is kept


def test_an_ncci_code_is_not_a_naic():
    d = _doc({"carrier_naic": "11525",
              "coverage_lines": [{"line": "Workers Compensation", "naic": "11525"}],
              "dec_page_entries": [{"label": "NCCI Code No.", "value": "11525"}]},
             "AMERISURE INSURANCE COMPANY NCCI Code No.11525\n")
    es._validate_document_fact_shapes(d)
    assert "carrier_naic" not in d["facts"]
    assert d["facts"]["coverage_lines"][0]["naic"] is None


def test_a_real_naic_is_kept():
    d = _doc({"carrier_naic": "25186"}, "EMC Property & Casualty Company NAIC # 25186\n")
    es._validate_document_fact_shapes(d)
    assert d["facts"]["carrier_naic"] == "25186"
    d2 = _doc({"carrier_naic": "25186"}, "")                     # no evidence: no opinion
    es._validate_document_fact_shapes(d2)
    assert d2["facts"]["carrier_naic"] == "25186"


def test_a_pending_or_prior_date_is_not_a_retro_date():
    d = _doc({"retro_date": "March 1, 2022",
              "dec_page_entries": [{"label": "Pending or Prior Proceedings Date",
                                    "value": "March 1, 2022"}]})
    es._validate_document_fact_shapes(d)
    assert "retro_date" not in d["facts"]
    d2 = _doc({"retro_date": "03/01/2022",
               "dec_page_entries": [{"label": "Retroactive Date", "value": "03/01/2022"},
                                    {"label": "Pending or Prior Litigation Date", "value": "03/01/2022"}]})
    es._validate_document_fact_shapes(d2)
    assert d2["facts"]["retro_date"] == "03/01/2022"


def test_an_extended_period_of_indemnity_is_not_the_restoration_period():
    d = _doc({"period_of_restoration": "540 DAYS"}, "EXTENDED PERIOD OF INDEMNITY 540 DAYS\n")
    es._validate_document_fact_shapes(d)
    assert "period_of_restoration" not in d["facts"]
    d2 = _doc({"period_of_restoration": "12 months"}, "Period of Restoration: 12 months\n")
    es._validate_document_fact_shapes(d2)
    assert d2["facts"]["period_of_restoration"] == "12 months"


def test_a_carrier_office_state_is_not_the_state_of_operations():
    docs = [_doc({"state_of_operations": "AZ"}),
            dict(_doc({"state_of_operations": "CO", "auto_garaging_addresses": ["DENVER, CO 80221"]}),
                 filename="auto.pdf"),
            dict(_doc({"state_of_operations": "CO, MI", "wc_payroll_by_state": {"CO": "$1"}}),
                 filename="wc.pdf")]
    es._drop_non_insured_states(docs)
    assert "state_of_operations" not in docs[0]["facts"]
    assert docs[1]["facts"]["state_of_operations"] == "CO"
    assert docs[2]["facts"]["state_of_operations"] == "CO"


def test_no_insured_evidence_leaves_the_state_unverified():
    # Was `test_no_insured_evidence_judges_nothing` (AZ kept). Brent, 23 Oct
    # 2026: "If we cannot verify the correct state from insured-specific
    # information, leave it unverified and ask" - the 805049a7 run settled on a
    # claims office's PA exactly here. The TEST pinned the hole.
    docs = [_doc({"state_of_operations": "AZ"})]
    es._drop_non_insured_states(docs)
    assert "state_of_operations" not in docs[0]["facts"]


def test_the_replay_corrects_every_misread(merged):
    mf, _flags, _docs = merged
    assert _v(mf, "carrier_naic") in (None, "")
    assert _v(mf, "payment_plan") in (None, "")
    assert _v(mf, "carrier_website") != "One Tower Square, Hartford, Connecticut 06183"
    assert _v(mf, "state_of_operations") == "CO"
    assert not _v(mf, "retro_date")
    assert not _v(mf, "period_of_restoration")


# =============================================================================
# 7. WC class codes are not the GL schedule
# =============================================================================
_WC_ROWS = [{"location": "CO 001", "class_code": "5190", "classification": "State Act - Electrical"},
            {"location": "CO 001", "class_code": "8810", "classification": "State Act - Clerical"}]


def test_a_wc_documents_class_rows_are_not_a_gl_schedule():
    d = _doc({"gl_class_code_schedule": copy.deepcopy(_WC_ROWS),
              "coverage_lines": [{"line": "Workers' Compensation and Employers' Liability"}]})
    assert es._drop_line_schedules_the_document_does_not_carry(d)
    assert d["facts"]["gl_class_code_schedule"] == []


def test_a_gl_document_and_a_gl_shaped_code_are_kept():
    d = _doc({"gl_class_code_schedule": copy.deepcopy(_WC_ROWS),
              "coverage_lines": [{"line": "Commercial General Liability"}]})
    assert es._drop_line_schedules_the_document_does_not_carry(d) == []
    d2 = _doc({"gl_class_code_schedule": [{"class_code": "91580"}],
               "coverage_lines": [{"line": "Workers Compensation"}]})
    assert es._drop_line_schedules_the_document_does_not_carry(d2) == []
    d3 = _doc({"gl_class_code_schedule": copy.deepcopy(_WC_ROWS)})       # names no line: not judged
    assert es._drop_line_schedules_the_document_does_not_carry(d3) == []


def test_the_replay_has_no_wc_code_in_gl_facts(merged):
    mf, _flags, _docs = merged
    for row in _v(mf, "gl_class_code_schedule") or []:
        assert str(row.get("class_code")) not in ("5190", "8742", "8810")


# =============================================================================
# 8. GL limits from the umbrella's schedule of underlying insurance
# =============================================================================
_SCHEDULE = """SCHEDULE OF UNDERLYING INSURANCE
AMERISURE INSURANCE COMPANY Standard Workers Employers Liability
Compensation and $1,000,000 Bodily Injury by Accident - each accident
AMERISURE INSURANCE COMPANY General Liability Each Occurrence
$1,000,000
Personal & Advertising Injury (Any one person or organization)
$1,000,000
Aggregates
$2,000,000 General Aggregate
$2,000,000 Products - completed operations
AMERISURE INSURANCE COMPANY Automobile Liability
Each Accident
$1,000,000
[Document page 5]
"""


def test_the_gl_block_is_read_and_nothing_else():
    got, carriers = es._gl_limits_in_underlying_schedule(_SCHEDULE)
    assert got == {"gl_each_occurrence": {"$1,000,000"}, "gl_personal_advertising_injury": {"$1,000,000"},
                   "gl_aggregate": {"$2,000,000"}, "gl_products_aggregate": {"$2,000,000"}}
    assert carriers


def test_gl_limits_fill_only_empty_facts_and_only_the_gl_policys():
    docs = [{"filename": "u.pdf", "text": _SCHEDULE}]
    mf = {"gl_aggregate": "$3,000,000",
          "_line_records": [{"line": "general_liab", "carrier_name": "AMERISURE INSURANCE COMPANY"}]}
    es._recover_gl_limits_from_underlying_schedules(mf, docs)
    assert mf["gl_aggregate"] == "$3,000,000"                      # a stated value stands
    assert es._fv(mf, "gl_products_aggregate") == "$2,000,000"
    other = {"_line_records": [{"line": "general_liab", "carrier_name": "Hartford Fire Insurance Company"}]}
    assert es._recover_gl_limits_from_underlying_schedules(other, docs) == []


def test_the_replay_recovers_the_gl_aggregate(merged):
    mf, _flags, _docs = merged
    assert _v(mf, "gl_aggregate") == "$2,000,000"
    assert _v(mf, "gl_products_aggregate") == "$2,000,000"
    assert _v(mf, "gl_each_occurrence") == "$1,000,000"


# =============================================================================
# 9. "Employee Benefit Liability" is a known line
# =============================================================================
@pytest.mark.parametrize("text,family", [
    ("Employee Benefit Liability Coverage Part", "employee_benefits"),
    ("EMPLOYEE BENEFIT LIABILITY", "employee_benefits"),
    ("Employee Benefits Liability", "employee_benefits"),
    ("Employee Benefit Plan", None)])
def test_employee_benefit_liability(text, family):
    assert canon_line(text) == family


# 25 Oct 2026, live run f3e4c225: the Cyber dec had NO line record, so its
# premium made five policies' premiums one "documents disagree" card (held 85).
_MF_NO_CYBER_RECORD = {"_line_records": [
    {"id": "umbrella#u", "line": "umbrella", "carrier_name": "A", "sources": ["umb.pdf"], "granted": True},
    {"id": "workers_comp#w", "line": "workers_comp", "carrier_name": "B", "sources": ["wc.pdf"], "granted": True}]}
_PREMIUMS = [{"display": "$4,162", "normalized": "4162", "sources": [{"filename": "cyber.pdf"}]},
             {"display": "$17,082", "normalized": "17082", "sources": [{"filename": "umb.pdf"}]},
             {"display": "$29,278", "normalized": "29278", "sources": [{"filename": "wc.pdf"}]}]


def test_a_dec_with_no_line_record_is_its_own_policy():
    docs = [{"filename": n, "doc_type": "dec_page"} for n in ("cyber.pdf", "umb.pdf", "wc.pdf")]
    values = [dict(v) for v in _PREMIUMS]
    assert uc._scope_by_policy_record("total_policy_premium", values, _MF_NO_CYBER_RECORD, docs)
    assert values[0]["scope"] == ["doc:cyber.pdf"]


def test_an_unplaced_document_that_is_not_a_policy_still_decides_nothing():
    docs = [{"filename": "cyber.pdf", "doc_type": "certificate"},
            {"filename": "umb.pdf", "doc_type": "dec_page"}, {"filename": "wc.pdf", "doc_type": "dec_page"}]
    assert not uc._scope_by_policy_record("total_policy_premium", [dict(v) for v in _PREMIUMS],
                                          _MF_NO_CYBER_RECORD, docs)
    # and without the documents the old rule stands
    assert not uc._scope_by_policy_record("total_policy_premium", [dict(v) for v in _PREMIUMS],
                                          _MF_NO_CYBER_RECORD)


def test_two_values_from_one_unplaced_dec_still_conflict():
    docs = [{"filename": "cyber.pdf", "doc_type": "dec_page"}]
    values = [{"display": "$4,162", "sources": [{"filename": "cyber.pdf"}]},
              {"display": "$5,000", "sources": [{"filename": "cyber.pdf"}]}]
    assert not uc._scope_by_policy_record("total_policy_premium", values, _MF_NO_CYBER_RECORD, docs)
