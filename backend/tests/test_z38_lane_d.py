"""Z38 lane D (24 Oct 2026): the three rare cases left by the Z37 review, the
second officer's missed title, and "Included" beside an amount in Data
Consistency."""
import logging

import pytest

from services import lob_canon as L
from services.insured_scope import address_is_a_party_office, drop_office_addresses
from services.extraction_service import read_officer_titles
from services.underwriting_consistency import (
    assess_underwriting_consistency, is_reference_amount_word,
)

logging.disable(logging.WARNING)


# ── 1a. An applicant named "... Mutual ..." keeps its own address ─────────────
@pytest.mark.parametrize("name", ["Mutual Plumbing LLC", "Farmers Mutual Grain Co-op"])
def test_an_applicant_named_mutual_keeps_its_address(name):
    text = f"NAMED INSURED\n{name.upper()}\n123 Main St, Denver CO 80202\n"
    addr = "123 Main St, Denver CO 80202"
    assert address_is_a_party_office(addr, [text]) is True          # the old reading
    assert address_is_a_party_office(addr, [text], own_names=[name]) is False
    doc = {"facts": {"applicant_name": {"value": name}, "mailing_address": {"value": addr}},
           "text": text}
    assert drop_office_addresses(doc) == []
    assert doc["facts"]["mailing_address"]["value"] == addr


def test_same_line_mutual_applicant_is_not_an_insurer():
    text = "Named Insured: Farmers Mutual Grain Co-op 55 Elevator Rd, Ames IA"
    assert address_is_a_party_office("55 Elevator Rd, Ames IA", [text],
                                     own_names=["Farmers Mutual Grain Co-op"]) is False


def test_a_real_mutual_insurer_still_drops_beside_a_mutual_applicant():
    text = "AMERISURE MUTUAL INSURANCE COMPANY\n26777 Halsted Rd, Farmington Hills MI\n"
    assert address_is_a_party_office("26777 Halsted Rd, Farmington Hills MI", [text],
                                     own_names=["Mutual Plumbing LLC"]) is True


# ── 1b. "Home Office:" is the insured's own unless an insurer stands by it ────
def test_insured_home_office_line_is_the_insureds_address():
    text = "Named Insured: Choice Electric LLC\nHome Office: 456 Oak Ave, Denver CO\n"
    assert address_is_a_party_office("456 Oak Ave, Denver CO", [text]) is False


@pytest.mark.parametrize("text", [
    "AMERISURE MUTUAL INSURANCE COMPANY\nHome Office: 26777 Halsted Rd, Farmington Hills MI\n",
    "AMERISURE INSURANCE COMPANY\nA stock company\nHome Office: 26777 Halsted Rd, Farmington Hills MI\n",
    "Home Office: 26777 Halsted Rd, Farmington Hills MI   Amerisure Insurance Company\n",
])
def test_insurer_home_office_still_drops(text):
    assert address_is_a_party_office("26777 Halsted Rd, Farmington Hills MI", [text]) is True


def test_other_office_labels_unchanged():
    assert address_is_a_party_office("Phoenix AZ", ["OFFICE: PHOENIX AZ"]) is True
    assert address_is_a_party_office("Phoenix AZ", ["Branch Office: Phoenix AZ"]) is True


# ── 1c. WORK is WC only as the whole label ────────────────────────────────────
@pytest.mark.parametrize("label", ["WORK - Completed Ops", "WORK - Products",
                                   "Products - Work Completed", "Completed Work"])
def test_work_beside_a_coverage_part_is_not_wc(label):
    assert L.canon_line(label) != L.WORKERS_COMP


@pytest.mark.parametrize("label", ["WORK", "WORK (Expiring)", "WORK - Expiring",
                                   "WORK - Magnolia Underwriters", "Work Comp",
                                   "work comp/EL", "Workers Compensation",
                                   "WORK - Workers Compensation"])
def test_work_as_the_whole_label_is_still_wc(label):
    assert L.canon_line(label) == L.WORKERS_COMP


# ── 2. The second officer's title from the document's officer table ──────────
_PLAIN = ("OFFICERS AND OWNERS\nNAME TITLE OWNERSHIP % INCLUDED / EXCLUDED\n"
          "Dana Whitfield President 60% Included\nMarcus Ruiz Vice President 40% Excluded\n")
_PIPES = ("NAME | TITLE | OWNERSHIP % | INCLUDED / EXCLUDED\n"
          "Dana Whitfield | President | 60% | Included\n"
          "Marcus Ruiz | Vice President | 40% | Excluded\n")


@pytest.mark.parametrize("text", [_PLAIN, _PIPES, "Marcus Ruiz      Vice President      40%"])
def test_second_officer_title_read_from_the_table(text):
    mf = {"wc_officers": [{"name": "Dana Whitfield", "title": "President"},
                          {"name": "Marcus Ruiz", "title": None}]}
    assert read_officer_titles(mf, [{"text": text}])
    assert mf["wc_officers"][1]["title"] == "Vice President"
    assert mf["wc_officers"][0]["title"] == "President"


def test_wrapped_fact_keeps_its_shape():
    mf = {"wc_officers": {"value": [{"name": "Marcus Ruiz"}], "source": "ai"}}
    read_officer_titles(mf, [{"text": _PIPES}])
    assert mf["wc_officers"]["value"][0]["title"] == "Vice President"
    assert mf["wc_officers"]["source"] == "ai"


@pytest.mark.parametrize("text", [
    "Marcus Ruiz Roofing installation 40%",          # duties, not a title
    "Marcus Ruiz signed this letter",                 # no table, no tail
    _PLAIN + "\nMarcus Ruiz Secretary 40% Excluded",  # two different titles
])
def test_no_title_without_a_clean_single_reading(text):
    mf = {"wc_officers": [{"name": "Marcus Ruiz"}]}
    assert read_officer_titles(mf, [{"text": text}]) == []
    assert not mf["wc_officers"][0].get("title")


def test_a_persons_table_and_an_excluded_document_are_never_touched():
    mf = {"wc_officers": {"value": [{"name": "Marcus Ruiz"}], "source": "producer"}}
    assert read_officer_titles(mf, [{"text": _PIPES}]) == []
    mf = {"wc_officers": [{"name": "Marcus Ruiz"}]}
    assert read_officer_titles(mf, [{"text": _PIPES, "excluded": True}]) == []


# ── 3. "Included" beside an amount is not a Data Consistency conflict ────────
def _field(v1, v2, key="extra_expense_limit"):
    docs = [{"doc_id": f"d{i}", "filename": f"{i}.pdf", "doc_type": "policy",
             "facts": {key: v, "applicant_name": "X LLC"}} for i, v in enumerate((v1, v2))]
    out = assess_underwriting_consistency(docs, {key: v1, "applicant_name": "X LLC"})
    return next((f for f in out["fields"] if f["fact_key"] == key), None)


def _is_conflict(f):
    return bool(f and f.get("review_required"))


@pytest.mark.parametrize("pair", [("Included", "$1,000,000"), ("$1,000,000", "Included"),
                                  ("Incl.", "$1,000,000"), ("Included in BPP limit", "$1,000,000"),
                                  ("See Schedule", "$1,000,000")])
def test_reference_word_beside_an_amount_is_not_a_conflict(pair):
    assert not _is_conflict(_field(*pair))
    assert not _is_conflict(_field(*pair, key="gl_each_occurrence"))


@pytest.mark.parametrize("pair", [("$500,000", "$1,000,000"), ("Included", "Excluded"),
                                  ("Excluded", "$1,000,000")])
def test_real_disagreements_still_conflict(pair):
    assert _is_conflict(_field(*pair))


@pytest.mark.parametrize("value,expected", [
    ("Included", True), ("INCL.", True), ("Included in Building limit", True),
    ("See schedule", True), ("As scheduled", True), ("Statutory", True),
    ("Excluded", False), ("Not included", False), ("None", False), ("N/A", False),
    ("$1,000,000", False), ("Incidental", False)])
def test_reference_word_reader(value, expected):
    assert is_reference_amount_word(value) is expected


def test_ai_guard_reads_the_applicants_own_name_on_named_insured_boxes():
    from services.ai_answer_guards import _insured_own_names, _office_address
    text = "MUTUAL PLUMBING LLC\n123 Main St, Denver CO 80202\n"
    own = _insured_own_names({"applicant_name": {"value": "Mutual Plumbing LLC"}})
    assert own == ["Mutual Plumbing LLC"]
    assert _office_address("123 Main St", text, own_names=own) is False
    assert _office_address("123 Main St", text) is True


@pytest.mark.parametrize("pair", [("Included $250,000", "$1,000,000"), ("Incl. $250,000", "$1,000,000"),
                                  ("Included - 250,000", "$1,000,000"),
                                  ("See schedule - $250,000", "$1,000,000")])
def test_a_reference_word_that_states_an_amount_still_conflicts(pair):
    """Review fix (24 Oct): "Included $250,000" states an amount - beside
    $1,000,000 it is a real two-amount conflict, never a reference."""
    assert not is_reference_amount_word(pair[0])
    assert _is_conflict(_field(*pair))
    assert _is_conflict(_field(*pair, key="gl_each_occurrence"))


# ── 25 Oct follow-ups: c/o cell, officer table running into the next, reference words only ──

def test_a_cell_naming_the_insured_and_an_insurer_still_reads_the_insurer():
    from services.insured_scope import _names_an_insurer
    own = ["Mutual Plumbing LLC"]
    assert _names_an_insurer("Mutual Plumbing LLC c/o Grange Mutual Insurance Company", own)
    assert _names_an_insurer("Mutual Plumbing LLC   Grange Mutual Insurance Company", own)
    assert not _names_an_insurer("Mutual Plumbing LLC", own)
    assert not _names_an_insurer("MUTUAL PLUMBING LLC", own)
    assert not _names_an_insurer("Mutual Plumbing, LLC", own)


def test_an_officer_table_running_into_the_next_table_stops_at_it():
    from services.extraction_service import _titles_printed_for
    text = ("NAME | TITLE | OWNERSHIP\n"
            "Jane Roe | President | 60%\n"
            "NAME | STATE | CLASS | PAYROLL\n"
            "John Doe | CO | 5190 | 50000\n")
    assert _titles_printed_for("John Doe", [{"text": text}]) == set()
    assert _titles_printed_for("Jane Roe", [{"text": text}]) == {"President"}
    other = ("NAME | TITLE | OWNERSHIP\nJane Roe | President | 60%\n"
             "DRIVER | LICENSE\nJohn Doe | Secretary\n")
    assert _titles_printed_for("John Doe", [{"text": other}]) == set()


def test_reference_words_with_no_amount_are_one_candidate():
    from services.underwriting_consistency import _drop_reference_words_beside_amounts as f
    a = {"display": "Included", "sources": [{"raw": "Included", "doc": 1}]}
    b = {"display": "See schedule", "sources": [{"raw": "See schedule", "doc": 2}]}
    out = f("extra_expense_limit", [a, b])
    assert len(out) == 1 and len(out[0]["sources"]) == 2
    c = {"display": "Excluded", "sources": [{"raw": "Excluded", "doc": 3}]}
    assert len(f("extra_expense_limit", [a, c])) == 2          # Included vs Excluded still conflicts
