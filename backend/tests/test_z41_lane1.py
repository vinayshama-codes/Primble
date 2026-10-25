"""Z41 lane 1 (25 Oct 2026, Choice Electric package f575160b).

R1 a priced coverage part the declarations print run together is a line row;
R2 a loss run states no policy term / prior carrier;
R3 an underlying schedule's limit-name rows fold into their policy and the
   column-split carrier name is repaired;
R4 a non-US address with a printed country parses city / postal correctly.
Each fixture is the live shape (OCR text and extraction rows as stored).
"""
import copy

import services.extraction_service as E
from utils.helpers import _parse_address


# ── R1 ──────────────────────────────────────────────────────────────────────
_PACKAGE_TEXT = """THIS POLICY CONSISTS OFTHE FOLLOWING COVERAGEPARTS FOR WHICHAPREMIUMIS
INDICATED. THIS PREMIUMMAYBESUBJECT TOADJUSTMENT.
PREMIUM
CAPITALASSETS PROGRAM(OUTPUT POLICY) COVERAGEPART $
COMMERCIALAUTOMOBILECOVERAGEPART $
COMMERCIALGENERALLIABILITYCOVERAGEPART $ 16,818.00
COMMERCIALINLANDMARINECOVERAGEPART $ 2,431.00
COMMERCIALLIABILITYUMBRELLA $
COMMERCIALPROPERTY COVERAGEPART $ 6,275.00
CRIMEANDFIDELITY COVERAGEPART $ 500.00
EMPLOYMENT-RELATEDPRACTICESLIABILITYCOVERAGEPART $
EMPLOYEE BENEFIT LIABILITY COVERAGE PART $ 425.00
TOTAL: $ 26,449.00
"""


def _row(line, premium):
    return {"line": line, "naic": None, "carrier": "AMERISURE INSURANCE COMPANY",
            "premium": premium, "policy_number": None,
            "effective_date": "01/01/2025", "expiration_date": "01/01/2026"}


def _package_doc(doc_type="dec_page"):
    return {"filename": "25-26 Package Policy.pdf", "doc_type": doc_type, "text": _PACKAGE_TEXT,
            "facts": {"carrier_name": {"value": "AMERISURE INSURANCE COMPANY"},
                      "effective_date": {"value": "01/01/2025"},
                      "expiration_date": {"value": "01/01/2026"},
                      "lines_of_business": ["Commercial Property", "Commercial Inland Marine",
                                            "Crime and Fidelity", "Employee Benefit Liability"],
                      "coverage_lines": [_row("Commercial Property", "$ 6,275.00"),
                                         _row("Commercial Inland Marine", "$ 2,431.00"),
                                         _row("Crime and Fidelity", "$ 500.00"),
                                         _row("Employee Benefit Liability", "$ 425.00")]}}


def test_r1_the_glued_gl_coverage_part_becomes_its_row():
    doc = _package_doc()
    added = E.add_priced_coverage_part_rows(doc)
    assert added == ["general_liab=$16,818.00"]
    gl = [r for r in doc["facts"]["coverage_lines"] if "General" in r["line"]]
    assert gl == [{"line": "Commercial General Liability Coverage Part", "naic": None,
                   "carrier": "AMERISURE INSURANCE COMPANY", "premium": "$16,818.00",
                   "policy_number": None, "effective_date": "01/01/2025",
                   "expiration_date": "01/01/2026"}]
    assert "Commercial General Liability Coverage Part" in doc["facts"]["lines_of_business"]


def test_r1_never_duplicates_and_never_adds_an_unpriced_part():
    doc = _package_doc()
    E.add_priced_coverage_part_rows(doc)
    assert E.add_priced_coverage_part_rows(doc) == []          # idempotent
    lines = [r["line"] for r in doc["facts"]["coverage_lines"]]
    assert len(lines) == 5                                     # no auto / umbrella / EPLI ($ alone)
    assert not any("Auto" in l or "Umbrella" in l or "Employment" in l for l in lines)


def test_r1_only_on_a_declarations_document():
    for dt in ("loss_run", "certificate", "application", None):
        doc = _package_doc(dt)
        assert E.add_priced_coverage_part_rows(doc) == []
        assert len(doc["facts"]["coverage_lines"]) == 4


def test_r1_rows_disagreeing_on_carrier_fall_back_to_the_documents_carrier():
    doc = _package_doc()
    doc["facts"]["coverage_lines"][0]["carrier"] = "Other Insurer Co"
    E.add_priced_coverage_part_rows(doc)
    gl = [r for r in doc["facts"]["coverage_lines"] if "General" in r["line"]][0]
    assert gl["carrier"] == "AMERISURE INSURANCE COMPANY"


def test_r1_a_person_typed_line_list_is_left_alone():
    doc = _package_doc()
    doc["facts"]["coverage_lines"] = {"value": doc["facts"]["coverage_lines"], "source": "producer"}
    assert E.add_priced_coverage_part_rows(doc) == []


# ── R2 ──────────────────────────────────────────────────────────────────────
def _loss_run():
    return {"filename": "Loss_Runs_2021-2024.csv", "doc_type": "loss_run", "text": "",
            "facts": {"carrier_name": {"value": "Amerisure Insurance Company"},
                      "policy_number": {"value": "CPP 1234"},
                      "prior_carrier": {"value": "Amerisure Insurance Company"},
                      "prior_effective_date": {"value": "01/01/2021"},
                      "prior_expiration_date": {"value": "01/01/2025"},
                      "effective_date": {"value": "01/01/2021"},
                      "loss_run_period_start": {"value": "01/01/2021"},
                      "loss_run_valuation_date": {"value": "10/15/2026"},
                      "total_incurred": {"value": "322650"}}}


def test_r2_a_loss_run_states_no_policy_term_or_prior_carrier():
    doc = _loss_run()
    removed = E.drop_loss_run_policy_terms(doc)
    assert set(removed) == {"prior_carrier", "prior_effective_date", "prior_expiration_date",
                            "effective_date"}
    f = doc["facts"]
    for k in removed:
        assert f[k] is None
    # its own facts stay, and identity matching keeps carrier / number
    assert f["loss_run_period_start"]["value"] == "01/01/2021"
    assert f["loss_run_valuation_date"]["value"] == "10/15/2026"
    assert f["total_incurred"]["value"] == "322650"
    assert f["carrier_name"]["value"] == "Amerisure Insurance Company"
    assert f["policy_number"]["value"] == "CPP 1234"


def test_r2_other_documents_and_typed_values_are_untouched():
    dec = _loss_run()
    dec["doc_type"] = "dec_page"
    assert E.drop_loss_run_policy_terms(dec) == []
    lr = _loss_run()
    lr["facts"]["prior_carrier"] = {"value": "Typed Co", "source": "producer"}
    assert "prior_carrier" not in E.drop_loss_run_policy_terms(lr)
    assert lr["facts"]["prior_carrier"]["value"] == "Typed Co"


def test_r2_merge_takes_no_prior_term_from_a_loss_run():
    pkg = _package_doc()
    docs = [pkg, _loss_run()]
    mf, _ = E.merge_facts(copy.deepcopy(docs), copy.deepcopy(pkg))
    pe = mf.get("prior_effective_date")
    pe = pe.get("value") if isinstance(pe, dict) else pe
    assert pe != "01/01/2021"
    pex = mf.get("prior_expiration_date")
    pex = pex.get("value") if isinstance(pex, dict) else pex
    assert pex != "01/01/2025"


# ── R3 ──────────────────────────────────────────────────────────────────────
def _excess_docs():
    excess = {"filename": "25-26 Excess Umbrella Policy.pdf", "doc_type": "dec_page", "text": "",
              "facts": {"carrier_name": {"value": "Travelers Property Casualty Company of America"},
                        "underlying_policies": [
                            {"line": "Umbrella Liability", "limit": "5,000 EACH OCCURRENCE",
                             "carrier": "AMERISURE", "policy_no": None},
                            {"line": "Pers/Adv Injury", "limit": "5,000",
                             "carrier": "MUTUAL INS URANCE COM PANY", "policy_no": None},
                            {"line": "General Aggregate", "limit": "5,000",
                             "carrier": "MUTUAL INS URANCE COM PANY", "policy_no": None},
                            {"line": "Prod/Comp Ops Agg", "limit": "5,000",
                             "carrier": "MUTUAL INS URANCE COM PANY", "policy_no": None}]}}
    umbrella = {"filename": "25-26 Umbrella Policy.pdf", "doc_type": "dec_page", "text": "",
                "facts": {"carrier_name": {"value": "AMERISURE MUTUAL INSURANCE COMPANY"},
                          "underlying_policies": [
                              {"line": "General Liability", "limit": "$1,000,000",
                               "carrier": "AMERISURE INSURANCE COMPANY", "policy_no": None},
                              {"line": "Automobile Liability", "limit": "$1,000,000",
                               "carrier": "AMERISURE INSURANCE COMPANY", "policy_no": None}]}}
    pkg = {"filename": "pkg.pdf", "doc_type": "dec_page", "text": "",
           "facts": {"carrier_name": {"value": "AMERISURE INSURANCE COMPANY"}}}
    return [excess, umbrella, pkg]


def test_r3_limit_rows_fold_into_their_policy_and_the_carrier_is_repaired():
    docs = _excess_docs()
    E.repair_underlying_schedules(docs)
    rows = docs[0]["facts"]["underlying_policies"]
    assert rows == [{"line": "Umbrella Liability",
                     "limit": "5,000 EACH OCCURRENCE; 5,000 PERS/ADV INJURY; "
                              "5,000 GENERAL AGGREGATE; 5,000 PROD/COMP OPS AGG",
                     "carrier": "AMERISURE MUTUAL INSURANCE COMPANY", "policy_no": None}]
    # real line rows are never folded
    assert len(docs[1]["facts"]["underlying_policies"]) == 2


def test_r3_a_different_complete_carrier_is_a_different_policy():
    docs = _excess_docs()
    docs[0]["facts"]["underlying_policies"][1]["carrier"] = "Zurich American Insurance Company"
    E.repair_underlying_schedules(docs)
    rows = docs[0]["facts"]["underlying_policies"]
    assert any(r["carrier"] == "Zurich American Insurance Company" for r in rows)


def test_r3_a_limit_row_of_another_policy_number_is_not_folded():
    docs = _excess_docs()
    up = docs[0]["facts"]["underlying_policies"]
    up[0]["policy_no"] = "UMB 1"
    for r in up[1:]:
        r["policy_no"] = "UMB 2"
        r["carrier"] = "AMERISURE"
    E.repair_underlying_schedules(docs)
    rows = docs[0]["facts"]["underlying_policies"]
    assert rows[0]["limit"] == "5,000 EACH OCCURRENCE"         # UMB 1 takes none of UMB 2's
    assert all(r["policy_no"] == "UMB 2" for r in rows[1:]) and len(rows) >= 2


def test_r3_split_words_reglue_and_complete_only_when_unambiguous():
    assert E._reglue_split_words("MUTUAL INS URANCE COM PANY") == "MUTUAL INSURANCE COMPANY"
    assert E._reglue_split_words("EMC Property & Casualty Company") == "EMC Property & Casualty Company"
    known = ["AMERISURE MUTUAL INSURANCE COMPANY", "AMERISURE INSURANCE COMPANY"]
    # Z42 review A: a tail of generic company words names no company - never
    # completed (the fold path re-joins "AMERISURE" + the column's pieces).
    assert E._complete_carrier_name("MUTUAL INSURANCE COMPANY", known) == "MUTUAL INSURANCE COMPANY"
    hsb = ["HARTFORD STEAM BOILER INSPECTION AND INSURANCE COMPANY"]
    assert E._complete_carrier_name("STEAM BOILER INSPECTION AND INSURANCE COMPANY", hsb) == hsb[0]
    # "INSURANCE COMPANY" is the tail of both - no guess
    assert E._complete_carrier_name("INSURANCE COMPANY", known) == "INSURANCE COMPANY"


def test_r3_limit_label_reader():
    for s in ("Pers/Adv Injury", "General Aggregate", "Prod/Comp Ops Agg", "EACH OCCURRENCE",
              "Products-Completed Operations Aggregate", "Disease - Policy Limit", "CSL"):
        assert E._is_limit_label(s), s
    for s in ("Umbrella Liability", "General Liability", "Automobile Liability",
              "Workers Compensation and Employers Liability", ""):
        assert not E._is_limit_label(s), s


# ── R4 ──────────────────────────────────────────────────────────────────────
def test_r4_the_account_address_reads_city_and_pin():
    assert _parse_address("C-52, Astrea It services, sector 65, Noida, India, 201301") == {
        "line1": "C-52", "line2": "Astrea It services, sector 65", "city": "Noida", "zip": "201301"}
    assert _parse_address("C-52, Astrea It services, sector 65, Noida, 201301, India")["city"] == "Noida"
    assert _parse_address("C-52, sector 65, Noida, India 201301")["zip"] == "201301"


def test_r4_canada_and_uk():
    assert _parse_address("12 King St W, Toronto, ON M5H 1A1, Canada") == {
        "line1": "12 King St W", "city": "Toronto", "state": "ON", "zip": "M5H 1A1"}
    assert _parse_address("10 Downing St, London SW1A 2AA, United Kingdom") == {
        "line1": "10 Downing St", "city": "London", "zip": "SW1A 2AA"}


def test_r4_us_and_region_shapes_unchanged():
    assert _parse_address("1234 W Colfax Ave, Denver, CO 80204") == {
        "line1": "1234 W Colfax Ave", "city": "Denver", "state": "CO", "zip": "80204"}
    assert _parse_address("1234 Elm Street, Suite 500, Dallas, TX 75201, USA") == {
        "line1": "1234 Elm Street", "line2": "Suite 500", "city": "Dallas", "state": "TX", "zip": "75201"}
    assert _parse_address("B-12 Connaught Place, New Delhi, Delhi 110001, India") == {
        "line1": "B-12 Connaught Place", "city": "New Delhi", "state": "Delhi", "zip": "110001"}
