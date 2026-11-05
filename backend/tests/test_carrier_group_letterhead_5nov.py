"""A group's letterhead names no writing company (live run a726512b, primble.ai, 5 Nov 2026).

The dec page was headed "EMC INSURANCE COMPANIES"; the header binder read "EMC INSURANCE" (a company that does not
exist) and replaced the Inland Marine row's correct "Employers Mutual Casualty Company", printed on the same page
under that contract. Built from the live page's shape."""
import pytest

from services import extraction_service as es

IM, UMB = "6C7-40-02---26", "6J7-40-02---26"
EMCC = "Employers Mutual Casualty Company"


def _page(*lines):
    return "[Document page 2]\n" + "\n".join(lines) + "\n"


def _mf():
    return {"coverage_lines": [
        {"line": "Commercial Inland Marine", "carrier": EMCC, "naic": "21415", "premium": "$300",
         "policy_number": IM, "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
        {"line": "Commercial Umbrella", "carrier": EMCC, "naic": None, "premium": "$3,418",
         "policy_number": UMB, "effective_date": "07/15/2025", "expiration_date": "07/15/2026"}]}


LIVE_PAGE = _page("EMC INSURANCE COMPANIES", "DECLARATIONS (CONTINUED)", "Page 2 of 2",
                  f"COMMERCIAL INLAND MARINE - POLICY NUMBER {IM}", f"Company: {EMCC}",
                  "Contractors equipment - scheduled tools and equipment Limit $25,000 Deductible $500")


def test_the_live_page_keeps_the_rows_own_company_and_naic():
    mf = _mf()
    assert es._bind_carriers_to_contracts(mf, [{"text": LIVE_PAGE}]) == []
    im = mf["coverage_lines"][0]
    assert (im["carrier"], im["naic"]) == (EMCC, "21415")


@pytest.mark.parametrize("head", [
    ["EMC INSURANCE COMPANIES"], ["EMC Insurance Companies"], ["QUILLON INSURANCE GROUP"],
    ["Quillon Insurance Group, Inc."], ["ACME INSURANCE COS."], ["  ** ACME Insurance Companies **"],
    # the hard review's variants (5 Nov 2026): punctuation / marks after the plural, a possessive, the logo split
    # over two OCR lines, a bare brand, a group's holding company
    ["EMC INSURANCE COMPANIES."], ["EMC INSURANCE COMPANIES\u00ae"], ["EMC Insurance Companies\u2122"],
    ["EMC INSURANCE COMPANIES:"], ["EMC INSURANCE COMPANIES|"], ["EMC INSURANCE COMPANIES-DES MOINES IA"],
    ["EMC INSURANCE", "COMPANIES"], ["EMC INSURANCE"], ["EMC INSURANCE GROUP INC."],
    ["The Cincinnati Insurance Companies"], ["EMC INSURANCE COMPANY'S"], ["EMC INSURANCE CO'S"]])
def test_no_brand_or_group_letterhead_binds_a_contract(head):
    text = _page(*head, f"POLICY NUMBER {IM}", f"Company: {EMCC}")
    mf = _mf()
    assert es._bind_carriers_to_contracts(mf, [{"text": text}]) == [], head
    assert (mf["coverage_lines"][0]["carrier"], mf["coverage_lines"][0]["naic"]) == (EMCC, "21415")


def test_the_legal_name_below_a_group_letterhead_still_binds():
    text = _page("EMC INSURANCE COMPANIES", "EMPLOYERS MUTUAL CASUALTY COMPANY", f"POLICY NUMBER {IM}")
    got = es._contract_carriers_from_page_headers([{"text": text}], _mf())
    assert set(got.values()) == {"EMPLOYERS MUTUAL CASUALTY COMPANY"}


@pytest.mark.parametrize("line,expected", [
    ("EMPLOYERS MUTUAL CASUALTY COMPANY POLICY NUMBER 6C7-40-02---26", "EMPLOYERS MUTUAL CASUALTY COMPANY"),
    ("ACME LIFE INSURANCE COMPANY GROUP POLICY NO 6C7-40-02---26", "ACME LIFE INSURANCE COMPANY"),  # legal form first
    ("ERIE INSURANCE EXCHANGE POLICY 6C7-40-02---26", "ERIE INSURANCE EXCHANGE"),
    ("ACME INSURANCE CO., INC. POLICY NUMBER 6C7-40-02---26", "ACME INSURANCE CO., INC."),
    ("XYZ GROUP INSURANCE COMPANY POLICY NUMBER 6C7-40-02---26", "XYZ GROUP INSURANCE COMPANY"),
    ("Insurance Company of the West POLICY 6C7-40-02---26", "Insurance Company of the West"),
    ("SELECTIVE INSURANCE COMPANY OF AMERICA 6C7-40-02---26", "SELECTIVE INSURANCE COMPANY OF AMERICA"),
])
def test_a_legal_company_name_still_binds(line, expected):
    got = es._contract_carriers_from_page_headers([{"text": _page(line)}], _mf())
    assert set(got.values()) == {expected}


@pytest.mark.parametrize("name,legal", [
    ("EMC INSURANCE", False), ("Quillon Insurance", False), ("", False), (None, False),
    ("EMPLOYERS MUTUAL CASUALTY COMPANY", True), ("ACME INSURANCE CO.", True), ("ERIE INSURANCE EXCHANGE", True),
    ("Insurance Company of North America", True), ("Acme Holdings LLC", True), ("ACME COMPANYS", False)])
def test_what_counts_as_a_legal_company_name(name, legal):
    assert es._is_legal_carrier_name(name) is legal
