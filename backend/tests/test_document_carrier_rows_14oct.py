"""A document's own carrier for its own unnamed coverage rows (14 Oct 2026).

Choice Electric live run f83757cf: the redacted "25-26 Package Policy.pdf"
prints AMERISURE INSURANCE COMPANY at the head of its common declarations and
no policy number anywhere. Run b117f010 read the carrier onto all five coverage
rows; f83757cf, the SAME PDF, returned the same rows with carrier None while the
document's own `carrier_name` and its index entry "CARRIER NAME" still named the
company. `_bind_carriers_to_contracts` joins a header carrier to a row only
through a policy number, so nothing bound it: the GL and Property line records
had no insurer and ACORD 125's PRIOR CARRIER grid printed only the Auto row.

`extraction_service.assign_document_carrier_to_rows` (called per document in
`merge_facts`) gives the document's carrier to its own unnamed rows - only for a
single-carrier document of the policy's own paperwork, corroborated by a
carrier-labelled index entry. Every refusal below is a case where writing the
carrier could be wrong.
"""
from __future__ import annotations

import copy

import pytest

import services.extraction_service as es

CARRIER = "AMERISURE INSURANCE COMPANY"

# The live document's first page as OCR printed it: the carrier is an
# UNLABELLED header line - "CARRIER NAME" is printed nowhere.
_PKG_TEXT = """[Document page 1]
POLICYNUMBER: IL DS 71 05 02 08
ACCOUNT NUMBER: 3
COMMON POLICY DECLARATIONS
AMERISURE INSURANCE COMPANY
26777 HALSTED ROAD
FARMINGTON HILLS, MI 48331-3586
NAMEDINSURED:
POLICYPERIOD: FROM 01/01/2025 TO 01/01/2026 AT12:01A.M.STANDARD
PREMIUM
COMMERCIALAUTOMOBILECOVERAGEPART $
COMMERCIALGENERALLIABILITYCOVERAGEPART $ 16,818.00
COMMERCIALINLANDMARINECOVERAGEPART $ 2,431.00
COMMERCIALPROPERTY COVERAGEPART $ 6,275.00
CRIMEANDFIDELITY COVERAGEPART $ 500.00
EMPLOYEE BENEFIT LIABILITY COVERAGE PART $ 425.00
TOTAL: $ 26,449.00
[Document page 2]
COMMERCIALPROPERTY
CP DS 70 00 09 06
COMMERCIAL PROPERTY COVERAGE PART
DECLARATIONS PAGE
EFFECTIVEDATE 01/01/2025 EXPIRATION DATE 01/01/2026
"""

_LIVE_ROWS = (("Commercial General Liability", "$ 16,818.00"),
              ("Commercial Inland Marine", "$ 2,431.00"),
              ("Commercial Property", "$ 6,275.00"),
              ("Crime and Fidelity", "$ 500.00"),
              ("Employee Benefit Liability", "$ 425.00"))


def _row(line, premium=None, carrier=None, naic=None, eff="01/01/2025", exp="01/01/2026",
         number=None):
    return {"line": line, "naic": naic, "carrier": carrier, "premium": premium,
            "policy_number": number, "effective_date": eff, "expiration_date": exp}


def _pkg(rows=None, entries=None, text=_PKG_TEXT, doc_type="dec_page", carrier=CARRIER,
         **facts):
    """The f83757cf Package Policy document, per-document shape."""
    f = {
        "carrier_name": {"value": carrier, "source": "ai", "confidence": "ai_high",
                         "verified_in_text": True},
        "coverage_lines": [_row(n, p) for n, p in _LIVE_ROWS] if rows is None else rows,
        "dec_page_entries": ([{"label": "CARRIER NAME", "owner": "carrier", "value": carrier,
                               "section": "COMMON POLICY DECLARATIONS", "policy_number": None,
                               "line_of_business": None},
                              {"label": "CARRIER ADDRESS", "owner": "carrier",
                               "value": "26777 HALSTED ROAD, FARMINGTON HILLS, MI 48331-3586",
                               "section": "COMMON POLICY DECLARATIONS", "policy_number": None,
                               "line_of_business": None}]
                             if entries is None else entries),
    }
    f.update(facts)
    return {"doc_id": "pkg", "filename": "25-26 Package Policy.pdf", "doc_type": doc_type,
            "text": text, "facts": f, "flags": {}}


def _carriers(doc):
    return [r.get("carrier") for r in doc["facts"]["coverage_lines"]]


# ── the live shape ───────────────────────────────────────────────────────────

def test_live_shape_rows_take_the_documents_carrier():
    doc = _pkg()
    written = es.assign_document_carrier_to_rows(doc)
    assert len(written) == 5
    assert _carriers(doc) == [CARRIER] * 5
    # the carrier only - no NAIC is invented, nothing else on the row moves
    for row, (line, premium) in zip(doc["facts"]["coverage_lines"], _LIVE_ROWS):
        assert row["naic"] is None and row["policy_number"] is None
        assert (row["line"], row["premium"]) == (line, premium)
        assert (row["effective_date"], row["expiration_date"]) == ("01/01/2025", "01/01/2026")


def test_a_printed_carrier_label_corroborates_without_a_page_header():
    """A plain-text declarations with "Carrier: X" printed (the H7A package):
    the entry is verified label AND value, no page structure needed."""
    text = ("COMMERCIAL PACKAGE POLICY\nPolicy Number: CPP-70255-26\n"
            "Carrier: Continental Basin Insurance Company\nNAIC Code: 24112\n"
            "PREMIUM SUMMARY\nGeneral Liability $18,430\nCommercial Property $9,145\n")
    name = "Continental Basin Insurance Company"
    doc = _pkg(rows=[_row("General Liability", "$18,430", carrier=name, naic="24112"),
                     _row("Commercial Property", "$9,145", eff=None, exp=None)],
               entries=[{"label": "Carrier", "owner": "carrier", "value": name}],
               text=text, carrier=name, carrier_naic={"value": "24112"})
    assert es.assign_document_carrier_to_rows(doc) == [f"Commercial Property={name}"]
    assert _carriers(doc) == [name, name]


def test_the_company_is_written_as_the_entry_prints_it():
    """`carrier_name` read in ordinary case; the page and its entry print
    capitals - the rows take the printing the entry verified."""
    doc = _pkg(carrier="Amerisure Insurance Company",
               entries=[{"label": "CARRIER NAME", "owner": "carrier", "value": CARRIER}])
    assert len(es.assign_document_carrier_to_rows(doc)) == 5
    assert set(_carriers(doc)) == {CARRIER}


def test_merge_facts_runs_the_step_per_document():
    """Wired into the per-document pre-pass: the merged line records and the
    persisted per-document copy both carry the carrier."""
    wc = {"doc_id": "wc", "filename": "25-26 Workers Compensation Policy.pdf",
          "doc_type": "dec_page", "flags": {},
          "text": "[Document page 1]\nAMERISURE INSURANCE COMPANY\nWORKERS COMPENSATION\n",
          "facts": {"carrier_name": {"value": CARRIER},
                    "coverage_lines": [_row("Workers' Compensation and Employers' Liability",
                                            "29,278.00", carrier=CARRIER)]}}
    docs = [_pkg(), wc]
    mf, _flags = es.merge_facts(docs, docs[0])
    merged = {r["line"]: r.get("carrier") for r in es._fv(mf, "coverage_lines")}
    for line, _p in _LIVE_ROWS:
        assert merged[line] == CARRIER, line
    assert _carriers(docs[0]) == [CARRIER] * 5, "the per-document copy is written too"
    records = {r.get("line"): r.get("carrier_name") for r in es._fv(mf, "_line_records") or []}
    assert records.get("general_liab") == CARRIER
    assert records.get("property") == CARRIER


# ── two carriers in one document: nothing ───────────────────────────────────

_EMC_PC = "EMC Property & Casualty Company"


@pytest.mark.parametrize("variant", ["row", "entry_value", "entry_label", "page_header"])
def test_two_carriers_in_one_document_assign_nothing(variant):
    rows = [_row(n, p) for n, p in _LIVE_ROWS]
    entries = None
    text = _PKG_TEXT
    if variant == "row":
        rows.append(_row("General Liability", "$3,954", carrier=_EMC_PC))
    elif variant == "entry_value":
        entries = [{"label": "CARRIER NAME", "owner": "carrier", "value": CARRIER},
                   {"label": "Company", "owner": "carrier", "value": _EMC_PC}]
    elif variant == "entry_label":
        entries = [{"label": "CARRIER NAME", "owner": "carrier", "value": CARRIER},
                   {"label": _EMC_PC, "owner": "carrier", "value": "NAIC No. 21415"}]
    else:
        text = _PKG_TEXT + ("[Document page 3]\nEMC PROPERTY & CASUALTY COMPANY\n"
                            "COMMERCIAL GENERAL LIABILITY DECLARATIONS\n")
    doc = _pkg(rows=rows, entries=entries, text=text)
    before = copy.deepcopy(doc)
    assert es.assign_document_carrier_to_rows(doc) == []
    assert doc == before


def test_the_umbrella_listing_its_underlying_carrier_is_two_companies():
    """The umbrella dec names its own company AND the underlying policies'
    ("Carrier: AMERISURE INSURANCE COMPANY" in its schedule) - not one carrier."""
    doc = _pkg(carrier="AMERISURE MUTUAL INSURANCE COMPANY",
               rows=[_row("Commercial Liability Umbrella", "$ 17,082.00")],
               entries=[{"label": "Company", "owner": "carrier",
                         "value": "AMERISURE MUTUAL INSURANCE COMPANY"},
                        {"label": "Carrier", "owner": "carrier", "value": CARRIER}],
               text="Company: AMERISURE MUTUAL INSURANCE COMPANY\n"
                    "SCHEDULE OF UNDERLYING INSURANCE\nCarrier: AMERISURE INSURANCE COMPANY\n")
    assert es.assign_document_carrier_to_rows(doc) == []
    assert _carriers(doc) == [None]


def test_an_agency_or_a_contact_entry_is_not_a_second_carrier():
    """Only carrier-scoped entries count, and only names that read as an
    insurer: the producer's agency and the carrier's own address do not
    block the document's carrier."""
    entries = [{"label": "CARRIER NAME", "owner": "carrier", "value": CARRIER},
               {"label": "CARRIER ADDRESS", "owner": "carrier",
                "value": "26777 HALSTED ROAD, FARMINGTON HILLS, MI 48331-3586"},
               {"label": "Agent", "owner": "producer", "value": "Summit Insurance Agency, Inc."},
               {"label": "Claim Reporting", "owner": "carrier", "value": "888-362-2255"}]
    doc = _pkg(entries=entries)
    assert len(es.assign_document_carrier_to_rows(doc)) == 5


# ── not the policy's own paperwork: nothing ─────────────────────────────────

@pytest.mark.parametrize("doc_type", ["certificate", "acord_form", "loss_run", "application",
                                      "supplemental_application", "narrative", "unknown", ""])
def test_a_document_that_is_not_the_policys_own_paperwork_assigns_nothing(doc_type):
    doc = _pkg(doc_type=doc_type)
    assert es.assign_document_carrier_to_rows(doc) == []
    assert _carriers(doc) == [None] * 5


@pytest.mark.parametrize("doc_type", ["dec_page", "policy", "binder", "quote", "endorsement"])
def test_the_policys_own_paperwork_roles(doc_type):
    doc = _pkg(doc_type=doc_type)
    assert len(es.assign_document_carrier_to_rows(doc)) == 5


# ── rows that name an insurer keep what they have ───────────────────────────

def test_a_row_with_a_naic_is_untouched():
    rows = [_row("Commercial General Liability", "$ 16,818.00"),
            _row("Commercial Property", "$ 6,275.00", naic="12345")]
    doc = _pkg(rows=rows, carrier_naic={"value": "12345"})
    assert es.assign_document_carrier_to_rows(doc) == [
        f"Commercial General Liability={CARRIER}"]
    prop = doc["facts"]["coverage_lines"][1]
    assert prop["carrier"] is None and prop["naic"] == "12345"


def test_a_naic_the_document_does_not_give_its_carrier_assigns_nothing():
    """A NAIC alone names SOME insurer; with no NAIC of the document's own to
    match it, it may be another company - the document is not one carrier's."""
    rows = [_row("Commercial General Liability", "$ 16,818.00"),
            _row("Commercial Property", "$ 6,275.00", naic="21415")]
    doc = _pkg(rows=rows)
    before = copy.deepcopy(doc)
    assert es.assign_document_carrier_to_rows(doc) == []
    assert doc == before


def test_a_row_with_its_own_carrier_is_untouched():
    own = "Amerisure Insurance Company"            # the same company, printed its own way
    rows = [_row("Commercial General Liability", "$ 16,818.00", carrier=own),
            _row("Commercial Property", "$ 6,275.00")]
    doc = _pkg(rows=rows)
    assert es.assign_document_carrier_to_rows(doc) == [f"Commercial Property={CARRIER}"]
    assert _carriers(doc) == [own, CARRIER]


def test_menu_denial_and_person_rows_are_untouched():
    rows = [_row("Commercial General Liability", "$ 16,818.00"),
            _row("Commercial Automobile Coverage Part", None, eff=None, exp=None),  # "$" menu row
            _row("Liquor Liability", "No Coverage"),
            dict(_row("Commercial Property", "$ 6,275.00"), _producer_fields=["premium"]),
            dict(_row("Crime and Fidelity", "$ 500.00"), _producer_added="added:x1")]
    doc = _pkg(rows=rows)
    assert es.assign_document_carrier_to_rows(doc) == [f"Commercial General Liability={CARRIER}"]
    assert _carriers(doc) == [CARRIER, None, None, None, None]


# ── no corroboration: nothing ───────────────────────────────────────────────

@pytest.mark.parametrize("variant", ["no_entries", "address_label", "sentence_label",
                                     "servicing_label", "value_not_printed",
                                     "unprinted_label_no_header"])
def test_no_corroborating_entry_assigns_nothing(variant):
    text = _PKG_TEXT
    entries = []
    if variant == "address_label":
        entries = [{"label": "CARRIER ADDRESS", "owner": "carrier", "value": CARRIER}]
    elif variant == "sentence_label":
        entries = [{"label": "This policy is issued by the company named below", "owner": "carrier",
                    "value": CARRIER}]
    elif variant == "servicing_label":
        entries = [{"label": "SERVICING CARRIER", "owner": "carrier", "value": CARRIER}]
    elif variant == "value_not_printed":
        entries = [{"label": "CARRIER NAME", "owner": "carrier", "value": CARRIER}]
        text = _PKG_TEXT.replace("AMERISURE INSURANCE COMPANY", "AMERISURE")
    elif variant == "unprinted_label_no_header":
        # The model's "CARRIER NAME" over a name printed mid-page, never as a
        # page header and never beside a carrier label: its say-so alone.
        entries = [{"label": "CARRIER NAME", "owner": "carrier", "value": CARRIER}]
        text = ("COMMON POLICY DECLARATIONS\nPREMIUM\nTHIS POLICY IS WRITTEN BY "
                "AMERISURE INSURANCE COMPANY\nCOMMERCIALPROPERTY COVERAGEPART $ 6,275.00\n")
    doc = _pkg(entries=entries, text=text)
    before = copy.deepcopy(doc)
    assert es.assign_document_carrier_to_rows(doc) == []
    assert doc == before


# ── a person's word and malformed input ─────────────────────────────────────

@pytest.mark.parametrize("key", ["carrier_name", "coverage_lines"])
def test_a_person_sourced_fact_stops_the_step(key):
    doc = _pkg()
    doc["facts"][key] = {"value": es._fv(doc["facts"], key), "source": "producer"}
    assert es.assign_document_carrier_to_rows(doc) == []


@pytest.mark.parametrize("doc", [
    None, {}, {"facts": None}, {"doc_type": "dec_page", "facts": {}},
    {"doc_type": "dec_page", "facts": {"coverage_lines": "x", "carrier_name": CARRIER}},
    {"doc_type": "dec_page", "facts": {"coverage_lines": [None, 3, "row"], "carrier_name": CARRIER}},
    {"doc_type": "dec_page", "facts": {"coverage_lines": [_row("General Liability", "$1")],
                                       "carrier_name": ["A", "B"]}},
    {"doc_type": "dec_page", "text": None,
     "facts": {"coverage_lines": [_row("General Liability", "$1")], "carrier_name": CARRIER,
               "dec_page_entries": [None, "x", {"label": None, "value": None}]}},
])
def test_malformed_input_never_raises_and_writes_nothing(doc):
    before = copy.deepcopy(doc)
    assert es.assign_document_carrier_to_rows(doc) == []
    assert doc == before


def test_an_excluded_document_is_left_alone():
    doc = dict(_pkg(), excluded=True)
    assert es.assign_document_carrier_to_rows(doc) == []


def test_a_second_run_changes_nothing():
    doc = _pkg()
    assert len(es.assign_document_carrier_to_rows(doc)) == 5
    once = copy.deepcopy(doc)
    assert es.assign_document_carrier_to_rows(doc) == []
    assert doc == once
