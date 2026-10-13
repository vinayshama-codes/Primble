"""Round 5 (7 Oct 2026) - the owner's live run b248c194 (Choice Electric, real AI
fill), defects #13 and #14 - fixed as CLASSES:

  #13 ACORD 140 premises grid: every premises / building COVERAGE row of a
      printed property schedule prints as its own subject row with its own
      limit, coinsurance, deductible, valuation and conditions
      (`services.property_coverages`, read at merge into `_property_coverages`;
      `pdf_service._resolve_premises_coverage_cell` stamps it); a default
      deductible the documents qualify with exceptions is never a row's own;
      rows after a read schedule's last coverage are owned blanks; an AI row
      that is another premises' row, or the same subject twice, is cleared.
  #14 address parts: a CITY box prints the city (state / ZIP go to their own
      EMPTY boxes when the documents agree); a TAX CODE is never the state.

Fixture: the Choice Electric per-document extraction already pinned by
`test_choice_electric_loc_6oct.py` (the same seven redacted decs as b248c194).
The live run's own AI answers for the 140 grid are inlined below (amounts and
codes only).
"""
import json
import os
from functools import lru_cache

import pytest

from services import extraction_service as es
from services import pdf_service as ps
from services import property_coverages as pc
from services.display_canonicalizer import (
    canonicalize_city, canonicalize_currency, canonicalize_for_field, split_city_state_zip,
)

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIXTURE = os.path.join(_HERE, "fixtures", "choice_electric_loc_6oct.json")
_SCHEMAS = os.path.join(os.path.dirname(_HERE), "forms_schemas")
G = "CommercialProperty_Premises_"


@lru_cache(maxsize=1)
def _fixture() -> dict:
    with open(_FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=None)
def _schema(form_id: str) -> dict:
    with open(os.path.join(_SCHEMAS, f"{form_id}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _package_text() -> str:
    return next(d["text"] for d in _fixture()["docs"] if "Package" in d["filename"])


@lru_cache(maxsize=1)
def _merged():
    docs = [d for d in _fixture()["docs"] if not d.get("excluded")]
    return es.merge_facts(json.loads(json.dumps(docs)), es.select_primary_truth(docs))


# The live run's (b248c194) own gap-fill answers on the 140 grid.
_LIVE_AI = {
    G + "SubjectOfInsuranceCode_C": "BPP", G + "LimitAmount_C": "$73,008",
    G + "SubjectOfInsuranceCode_E": "B", G + "LimitAmount_E": "$421,714",
    G + "CauseOfLossCode_A": "Special", G + "DeductibleTypeCode_A": "$",
    G + "FormsAndConditions_A": "REPLACEMENT COST",
    G + "FormsAndConditions_B": "AGREED VALUE", G + "FormsAndConditions_H": "AGREED VALUE",
    "CommercialStructure_TaxCode_A": "CO",
}


@lru_cache(maxsize=1)
def _live_140():
    mf, flags = _merged()
    facts = {**dict(mf), **flags}
    raw = "\n".join(d.get("text") or "" for d in _fixture()["docs"])
    report: list = []
    mapped, conf = ps.map_facts_to_form(
        facts, _schema("ACORD_140"), form_id="ACORD_140", raw_text=raw,
        pre_filled_gpt={"filled_values": dict(_LIVE_AI), "raw_text_fields": set(),
                        "question_grounding": {}},
        guard_report=report, allow_llm=False)
    return mapped, conf, {r["field"]: r.get("reason") for r in report if r.get("field")}


# ── 1. The reader: ISO "COVERAGE:" blocks ────────────────────────────────────

def test_the_schedule_is_read_into_each_buildings_own_rows():
    secs = {(s["premises"], s["building"]): s for s in pc.read_schedule_text(_package_text())}
    assert set(secs) == {("1", "1"), ("1", "2")}
    b1 = [(c["subject"], c["limit"], c["coinsurance"], c["deductible"], c["valuation"])
          for c in secs[("1", "1")]["coverages"]]
    assert b1 == [("Building", "$798,556", "80%", "$5,000", "R"),
                  ("Business Personal Property", "$73,008", "80%", "$5,000", "R"),
                  ("Business Income with Extra Expense", "$1,000,000", "80%", "72 Hours", "")]
    b2 = [(c["subject"], c["limit"]) for c in secs[("1", "2")]["coverages"]]
    assert b2 == [("Building", "$421,714"), ("Business Personal Property", "$73,008"),
                  ("Stock", "$75,000"), ("Business Income with Extra Expense", "$25,000")]
    assert all(s["complete"] for s in secs.values())


def test_options_split_into_valuation_subject_and_conditions():
    secs = {(s["premises"], s["building"]): s for s in pc.read_schedule_text(_package_text())}
    bpp1, bi1 = secs[("1", "1")]["coverages"][1], secs[("1", "1")]["coverages"][2]
    # "AGREED VALUE / INCLUDING STOCK / REPLACEMENT COST": RC is the valuation,
    # "Including Stock" qualifies it, Agreed Value is the row's condition.
    assert bpp1["valuation"] == "R" and bpp1["conditions"] == "AGREED VALUE"
    # Business income: extra expense is in the subject, the period in conditions.
    assert bi1["conditions"] == "EXTENDED PERIOD OF INDEMNITY 540 DAYS"
    assert bi1["deductible_type"] == "Hours"
    # Building 2's business income prints "LIMIT DEDUCTIBLE": no coinsurance.
    bi2 = secs[("1", "2")]["coverages"][3]
    assert bi2["coinsurance"] == "" and "coinsurance" in bi2["columns"]


def test_an_included_extension_is_not_a_subject_row():
    text = """Prem #: 001 Bldg #: 001
COVERAGE: BUILDING
LIMIT COINSURANCE DEDUCTIBLE
$100,000 90% $1,000
COVERAGE: BUILDING-EQUIPMENT BREAKDOWN
LIMIT DEDUCTIBLE
INCLUDED $1,000
COVERAGE: BUSINESS INCOME
LIMIT
NOT COVERED
"""
    (sec,) = pc.read_schedule_text(text)
    assert [c["subject"] for c in sec["coverages"]] == ["Building"]
    assert sec["complete"]


def test_a_page_break_inside_the_options_is_skipped():
    text = """Prem #: 2 Bldg #: 1
COVERAGE: BUSINESS INCOME
Coverage Option(s):
INCLUDING EXTRA EXPENSE
XX DS 99 01 09 06 Page3 of 4
[Document page 8]
Property Coverage Schedule (continued)
INCLUDING RENTAL VALUE
LIMIT DEDUCTIBLE
$50,000 24 HOURS
"""
    (sec,) = pc.read_schedule_text(text)
    (cov,) = sec["coverages"]
    assert cov["subject"] == "Business Income with Extra Expense and Rental Value"
    assert (cov["limit"], cov["deductible"], cov["conditions"]) == ("$50,000", "24 Hours", "")


def test_an_unreadable_block_leaves_the_premises_incomplete():
    text = """Prem #: 1 Bldg #: 1
COVERAGE: BUILDING
LIMIT COINSURANCE DEDUCTIBLE
$250,000 80% $2,500
COVERAGE: PERSONAL PROPERTY-INSURED
LIMIT COINSURANCE DEDUCTIBLE
see attached
"""
    (sec,) = pc.read_schedule_text(text)
    assert [c["subject"] for c in sec["coverages"]] == ["Building"]
    assert sec["complete"] is False


def test_an_inland_marine_schedule_in_the_same_layout_is_not_a_premises():
    text = """Location 1
COVERAGE: CONTRACTORS EQUIPMENT
LIMIT DEDUCTIBLE
$50,000 $500
"""
    facts = {}
    pc.derive_property_coverages(facts, [{"text": text}])
    assert pc.KEY not in facts


# ── 2. The reader: a "Prem Bldg Coverage Limit" table ─────────────────────────

_TABLE = """COVERAGES PROVIDED
Prem Bldg Coverage Limit Of Insurance Causes Coinsurance Valuation Deductible
1 1 Your Business Personal Property $380,000 SPECIAL 90% RC $5,000
1 1 Tenants Improvements & Betterments 60,000 Special 90% RC 5,000
2 1 Building $620,000 Special 80% ACV 5000
OPTIONAL COVERAGES
"""


def test_a_coverage_table_is_read_row_by_row():
    secs = {(s["premises"], s["building"]): s for s in pc.read_schedule_text(_TABLE)}
    p1 = secs[("1", "1")]["coverages"]
    assert [(c["subject"], c["limit"], c["causes"], c["coinsurance"], c["valuation"], c["deductible"])
            for c in p1] == [
        ("Business Personal Property", "$380,000", "Special", "90%", "R", "$5,000"),
        ("Tenants Improvements and Betterments", "$60,000", "Special", "90%", "R", "$5,000")]
    p2 = secs[("2", "1")]["coverages"]
    assert (p2[0]["subject"], p2[0]["valuation"], p2[0]["deductible"]) == ("Building", "A", "$5,000")
    assert all(s["complete"] for s in secs.values())


def test_an_unreadable_table_row_makes_no_premises_complete():
    garbled = _TABLE.replace("2 1 Building", "1 2 1 1 B B u u s ild in in e g ss Income $ $ 5 1 0\n2 1 Building")
    secs = pc.read_schedule_text(garbled)
    assert secs and not any(s["complete"] for s in secs)


# ── 3. The reader: "Subject of Insurance:" label blocks ──────────────────────

_LABELS = """PROPERTY SCHEDULE - PREMISES INFORMATION

Location 1
Location Address: 100 Example Way, Springfield, IL 62701
Subject of Insurance: Building
Amount of Insurance: $3,150,000
Construction Type: Joisted Masonry
Coinsurance: 80%
Valuation: Replacement Cost
Causes of Loss: Special Form

Location 2
Location Address: 200 Sample Rd, Springfield, IL 62702
Subject of Insurance: Building
Amount of Insurance: $2,480,000
Coinsurance: 90%
Valuation: Actual Cash Value
Causes of Loss: Broad Form

ADDITIONAL PROPERTY INFORMATION
Business Personal Property Value (combined, both locations): $410,000
"""


def test_subject_label_blocks_keep_each_locations_own_terms():
    secs = {(s["premises"], s["building"]): s for s in pc.read_schedule_text(_LABELS)}
    assert set(secs) == {("1", ""), ("2", "")}
    l1, l2 = secs[("1", "")]["coverages"], secs[("2", "")]["coverages"]
    assert [(c["subject"], c["limit"], c["coinsurance"], c["valuation"], c["causes"]) for c in l1] == [
        ("Building", "$3,150,000", "80%", "R", "Special")]
    assert [(c["subject"], c["limit"], c["coinsurance"], c["valuation"], c["causes"]) for c in l2] == [
        ("Building", "$2,480,000", "90%", "A", "Broad")]


# ── 4. Subjects and the default deductible ───────────────────────────────────

@pytest.mark.parametrize("text, kind", [
    ("BUILDING", "building"), ("B", "building"), ("Building Value", "building"),
    ("PERSONAL PROPERTY-INSURED", "bpp"), ("BPP", "bpp"), ("Business Personal Property", "bpp"),
    ("Personal Property Including Stock", "bpp"), ("Contents", "bpp"),
    ("PERSONAL PROPERTY-STOCK", "stock"), ("STK", "stock"), ("Stock", "stock"),
    ("BUSINESS INCOME", "bi"), ("BUSIN", "bi"), ("Business Income w/ Extra Expense", "bi"),
    ("EXTRA EXPENSE", "ee"), ("Tenants Improvements & Betterments", "tib"),
    ("SIGNS", None), ("BUILDING-EQUIPMENT BREAKDOWN", None), ("", None),
])
def test_a_subject_is_known_by_what_it_is(text, kind):
    assert pc.subject_kind(text) == kind


@pytest.mark.parametrize("name, options, want", [
    ("BUSINESS INCOME", ["INCLUDING EXTRA EXPENSE"], "Business Income with Extra Expense"),
    ("BUSINESS INCOME", ["INCLUDING EXTRA EXPENSE", "VALUE TYPE OTHER THAN RENTAL VALUE"],
     "Business Income with Extra Expense"),
    ("BUSINESS INCOME & EXTRA EXPENSE", [], "Business Income with Extra Expense"),
    ("BUSINESS INCOME", ["WITHOUT EXTRA EXPENSE"], "Business Income without Extra Expense"),
    ("BUSINESS INCOME", [], "Business Income"),
])
def test_business_income_takes_its_acord_description(name, options, want):
    assert pc._bi_label(name, options) == want


@pytest.mark.parametrize("text, want", [
    ("COMMERCIAL PROPERTY DECLARATIONS\nDEDUCTIBLE\n$500. Exceptions: SEE SCHEDULE",
     {"amount": "$500", "exceptions": "SEE SCHEDULE"}),
    ("COMMERCIAL PROPERTY DECLARATIONS\nDEDUCTIBLE $1,000 except as shown in the schedule",
     {"amount": "$1,000", "exceptions": "except as shown in the schedule"}),
    ("COMMERCIAL PROPERTY DECLARATIONS\nDEDUCTIBLE $500. Exceptions: NONE", None),
    ("COMMERCIAL PROPERTY DECLARATIONS\nDEDUCTIBLE $500. Exceptions:", None),
    ("GENERAL LIABILITY DECLARATIONS\nDEDUCTIBLE $500. Exceptions: SEE SCHEDULE", None),
])
def test_a_default_deductible_is_recorded_only_with_its_exceptions(text, want):
    assert pc.qualified_default_deductible(text) == want


def test_two_documents_printing_different_rows_decide_nothing():
    a = "Prem #: 1 Bldg #: 1\nCOVERAGE: BUILDING\nLIMIT\n$100,000\n"
    b = "Prem #: 1 Bldg #: 1\nCOVERAGE: BUILDING\nLIMIT\n$150,000\n"
    facts = {}
    pc.derive_property_coverages(facts, [{"text": a}, {"text": b}])
    assert pc.KEY not in facts
    same = {}
    pc.derive_property_coverages(same, [{"text": a}, {"text": a}])
    assert len(same[pc.KEY]["sections"]) == 1


# ── 5. Joining a section to its premises row ─────────────────────────────────

def _blob(*sections, default=None):
    out = {"sections": list(sections)}
    if default:
        out["default_deductible"] = default
    return out


def _sec(prem, bldg, *covs, complete=True):
    return {"premises": prem, "building": bldg, "heading": "", "complete": complete,
            "coverages": [pc._coverage(n, limit=l, coinsurance="80%", deductible="$1,000",
                                       columns=["coinsurance", "deductible"]) for n, l in covs]}


def test_printed_numbers_join_a_section_to_its_building():
    facts = {"property_locations": [{"premises_number": "001", "building_number": "001"},
                                    {"premises_number": "001", "building_number": "002"}],
             pc.KEY: _blob(_sec("1", "2", ("BUILDING", "$2"), ("STOCK", "$3")),
                           _sec("1", "1", ("BUILDING", "$1")))}
    assert [c["limit"] for c in pc.premises_rows(facts, 0)["rows"]] == ["$1"]
    assert [c["limit"] for c in pc.premises_rows(facts, 1)["rows"]] == ["$2", "$3"]


def test_a_position_loc_number_joins_only_when_the_values_agree():
    sec1 = _sec("1", "", ("BUILDING", "$100,000"))
    sec2 = _sec("2", "", ("BUILDING", "$200,000"))
    rows = [{"location_number": "1", "building_value": "$100,000"},
            {"location_number": "2", "building_value": "$999,000"}]
    facts = {"property_locations": rows, pc.KEY: _blob(sec1, sec2)}
    assert pc.premises_rows(facts, 0) is not None
    assert pc.premises_rows(facts, 1) is None          # the row says another amount


def test_a_premises_wide_section_over_two_buildings_joins_neither():
    facts = {"property_locations": [{"premises_number": "1", "building_number": "1"},
                                    {"premises_number": "1", "building_number": "2"}],
             pc.KEY: _blob(_sec("1", "", ("BUILDING", "$1")))}
    assert pc.premises_rows(facts, 0) is None and pc.premises_rows(facts, 1) is None


def test_the_tables_own_building_value_prints_with_the_schedules_terms():
    facts = {"property_locations": [{"premises_number": "1", "building_number": "1",
                                     "building_value": "$900,000"}],
             pc.KEY: _blob(_sec("1", "1", ("BUILDING", "$798,556"), ("BUSINESS INCOME", "$5,000")))}
    rows = pc.premises_rows(facts, 0)["rows"]
    assert (rows[0]["limit"], rows[0]["coinsurance"], rows[0]["deductible"]) == ("$900,000", "80%", "$1,000")


# ── 6. The live package through the stamper ──────────────────────────────────

def test_merge_records_both_buildings_and_the_qualified_default():
    mf, _ = _merged()
    blob = mf[pc.KEY]
    assert [(s["premises"], s["building"], len(s["coverages"])) for s in blob["sections"]] == [
        ("1", "1", 3), ("1", "2", 4)]
    assert blob["default_deductible"] == {"amount": "$500", "exceptions": "SEE SCHEDULE"}


def test_live_140_prints_each_buildings_own_rows():
    mapped, conf, _ = _live_140()
    grid = {L: (mapped.get(G + f"SubjectOfInsuranceCode_{L}"), mapped.get(G + f"LimitAmount_{L}"),
                mapped.get(G + f"DeductibleAmount_{L}"))
            for L in "ABCDEGHIJK"}
    assert grid == {
        "A": ("Building", "$798,556", "$5,000"),
        "B": ("Business Personal Property", "$73,008", "$5,000"),
        "C": ("Business Income with Extra Expense", "$1,000,000", "72 Hours"),
        "D": (None, None, None), "E": (None, None, None),
        "G": ("Building", "$421,714", "$5,000"),
        "H": ("Business Personal Property", "$73,008", "$5,000"),
        "I": ("Stock", "$75,000", "$5,000"),
        "J": ("Business Income with Extra Expense", "$25,000", "72 Hours"),
        "K": (None, None, None)}
    assert conf[G + "LimitAmount_I"] == "filled" and conf[G + "SubjectOfInsuranceCode_I"] == "filled"


def test_live_140_terms_are_the_rows_own():
    mapped, _, _ = _live_140()
    for L in "ABGHI":
        assert mapped[G + f"CoinsurancePercent_{L}"] == "80%"
        assert mapped[G + f"ValuationCode_{L}"] == "R"
        assert mapped[G + f"DeductibleTypeCode_{L}"] == "Dollars"
    assert [mapped.get(G + f"FormsAndConditions_{L}") for L in "BHI"] == ["AGREED VALUE"] * 3
    assert mapped[G + "DeductibleTypeCode_C"] == "Hours"
    assert mapped.get(G + "CoinsurancePercent_J") is None      # printed "LIMIT DEDUCTIBLE"
    # Building rows list no condition beyond their valuation: owned blank.
    assert mapped.get(G + "FormsAndConditions_A") is None


def test_live_140_never_prints_the_qualified_default_as_a_rows_deductible():
    mapped, _, _ = _live_140()
    assert "$500" not in {mapped.get(G + f"DeductibleAmount_{L}") for L in "ABCDEGHIJK"}


def test_live_140_round2_location_work_still_holds():
    mapped, conf, _ = _live_140()
    assert mapped["Construction_ConstructionCode_B"] == "NON-COMBUSTIBLE - LIGHT STEEL"
    assert [mapped["CommercialStructure_Building_ProducerIdentifier_A"],
            mapped["CommercialStructure_Building_ProducerIdentifier_B"]] == ["001", "002"]
    assert [f for f, c in conf.items() if c == "missing_required_gate"
            and f.startswith(G)] == []


def test_rows_after_the_schedule_are_never_asked_of_gap_fill():
    mf, flags = _merged()
    _, unmatched, det = ps.compute_form_gaps("ACORD_140", _schema("ACORD_140"), {**mf, **flags})
    for L in "DEK":
        for col in ("SubjectOfInsuranceCode", "LimitAmount", "DeductibleAmount", "CauseOfLossCode"):
            assert G + f"{col}_{L}" not in unmatched
    assert G + "DeductibleAmount_A" not in unmatched and G + "LimitAmount_I" not in unmatched


def test_field_qa_expects_the_rows_own_deductible():
    mf, flags = _merged()
    facts = {**mf, **flags}
    schema = _schema("ACORD_140")
    assert ps.authoritative_expected_value("ACORD_140", G + "DeductibleAmount_A", facts, schema) == "$5,000"
    assert ps.authoritative_expected_value("ACORD_140", G + "LimitAmount_K", facts, schema) is None


# ── 7. A premises whose schedule was NOT read keeps the old grid ─────────────

def _fallback_facts(**extra):
    facts = {"_form_id": "ACORD_140",
             "property_locations": [{"location_number": "1", "building_value": "$100,000",
                                     "bpp_value": "$20,000"},
                                    {"location_number": "2", "building_value": "$300,000"}],
             "property_deductible_aop": "$500", "coinsurance_percentage": "80%",
             "valuation_method": "RCV"}
    facts.update(extra)
    return facts


def _map(facts, ai=None, form="ACORD_140"):
    report: list = []
    mapped, conf = ps.map_facts_to_form(
        facts, _schema(form), form_id=form, raw_text="",
        pre_filled_gpt={"filled_values": dict(ai or {}), "raw_text_fields": set(),
                        "question_grounding": {}}, guard_report=report, allow_llm=False)
    return mapped, conf, {r["field"]: r.get("reason") for r in report if r.get("field")}


def test_without_a_read_schedule_the_old_slots_and_scalars_stand():
    mapped, _, _ = _map(_fallback_facts())
    assert [mapped.get(G + f"LimitAmount_{L}") for L in "ABG"] == ["$100,000", "$20,000", "$300,000"]
    assert mapped[G + "DeductibleAmount_A"] == "$500"
    assert mapped[G + "CoinsurancePercent_A"] == "80%"


def test_an_unread_schedule_never_prints_its_qualified_default():
    facts = _fallback_facts(**{pc.KEY: {"sections": [],
                                        "default_deductible": {"amount": "$500",
                                                               "exceptions": "SEE SCHEDULE"}}})
    mapped, _, _ = _map(facts)
    assert mapped.get(G + "DeductibleAmount_A") is None
    # ...but a scalar that is NOT that default still prints.
    other = dict(facts, property_deductible_aop="$2,500")
    assert _map(other)[0][G + "DeductibleAmount_A"] == "$2,500"


def test_an_ai_row_copying_another_premises_row_is_cleared():
    ai = {G + "SubjectOfInsuranceCode_C": "B", G + "LimitAmount_C": "$300,000",
          G + "SubjectOfInsuranceCode_D": "BPP", G + "LimitAmount_D": "$20,000",
          G + "SubjectOfInsuranceCode_E": "Business Income", G + "LimitAmount_E": "$50,000"}
    mapped, _, reasons = _map(_fallback_facts(), ai)
    assert mapped.get(G + "LimitAmount_C") is None
    assert reasons[G + "LimitAmount_C"] == "OTHER_PREMISES_ROW_G"
    assert mapped.get(G + "LimitAmount_D") is None          # "BPP" == "Business Personal Property"
    assert reasons[G + "LimitAmount_D"] == "REPEATS_SUBJECT_ROW_B"
    assert mapped[G + "LimitAmount_E"] == "$50,000"         # a coverage of its own stays


def test_two_buildings_may_share_an_amount_the_documents_give_only_one():
    # Building 2 states no BPP of its own; an AI "BPP $20,000" there equals
    # building 1's but is not proven a copy - it stays.
    ai = {G + "SubjectOfInsuranceCode_H": "BPP", G + "LimitAmount_H": "$20,000"}
    mapped, _, _ = _map(_fallback_facts(), ai)
    assert mapped[G + "LimitAmount_H"] == "$20,000"


def test_the_160_premises_boxes_are_not_this_grid():
    facts = _fallback_facts(**{pc.KEY: {"sections": [],
                                        "default_deductible": {"amount": "$500",
                                                               "exceptions": "SEE SCHEDULE"}}})
    facts["_form_id"] = "ACORD_160"
    ps._set_schema_context(_schema("ACORD_160"))
    try:
        assert ps._resolve_premises_coverage_cell(G + "DeductibleAmount_A", facts) is ps._SCHED_SKIP
    finally:
        ps._set_schema_context(None)


# ── 8. Display: amounts in non-money units, ACORD's own listed answers ───────

@pytest.mark.parametrize("value, want", [
    ("72 Hours", "72 Hours"), ("2%", "2%"), ("12 months", "12 months"), ("10 percent", "10 percent"),
    ("$5,000", "$5,000"), ("5000", "$5,000"), ("$1M", "$1,000,000"),
])
def test_a_figure_in_a_non_money_unit_is_not_dollars(value, want):
    assert canonicalize_currency(value) == want


def test_acords_own_listed_subject_is_not_an_echo_of_the_box():
    meta = _schema("ACORD_140")[G + "SubjectOfInsuranceCode_C"]
    assert not ps._is_tooltip_echo("Business Income with Extra Expense", meta, G + "SubjectOfInsuranceCode_C")
    assert not ps._is_tooltip_echo("BUSIN", meta, G + "SubjectOfInsuranceCode_C")
    # The list itself copied in is still an echo.
    assert ps._is_tooltip_echo("Business Income with Extra Expense and Rental Value, Business Personal "
                               "Property, Furniture & Fixtures", meta, G + "SubjectOfInsuranceCode_C")


def test_a_one_line_code_list_is_not_a_list_of_answers():
    # "Examples are: S - Single; M - Married; ..." on ONE line names no item,
    # so the whole list pasted into the box is still judged as an echo.
    meta = _schema("ACORD_127")["Driver_MaritalStatusCode_A"]
    assert ps._tooltip_enumerated_answers(meta["tu"]) == frozenset()
    sub = ps._tooltip_enumerated_answers(_schema("ACORD_140")[G + "SubjectOfInsuranceCode_A"]["tu"])
    assert {"busin", "business income with extra expense", "stk", "stock"} <= sub


# ── 9. #14: a CITY box holds the city ────────────────────────────────────────

@pytest.mark.parametrize("value, want", [
    ("Denver, Co", ("Denver", "CO", "")), ("DENVER, CO 80221", ("DENVER", "CO", "80221")),
    ("Denver CO 80221", ("Denver", "CO", "80221")), ("Denver, Colorado", ("Denver", "CO", "")),
    ("St. Louis, MO 63101", ("St. Louis", "MO", "63101")), ("Washington, DC", ("Washington", "DC", "")),
    ("TX 75201", ("", "TX", "75201")), ("Denver 80221", ("Denver", "", "80221")), ("Co", ("", "CO", "")),
    ("Kansas City", None), ("New York", None), ("Indiana", None), ("Lake Ozark MO", None),
    ("Toronto, ON", None), ("Suite 500 Denver", None), ("State Of Colorado", None), ("", None),
])
def test_a_city_value_names_its_state_and_zip_by_structure(value, want):
    assert split_city_state_zip(value) == want


def test_the_city_box_prints_the_city():
    assert canonicalize_city("DENVER, CO") == "Denver"
    assert canonicalize_for_field("Vehicle_PhysicalAddress_CityName_A", "Denver, Co") == "Denver"
    assert canonicalize_city("Kansas City") == "Kansas City"


def _city_case(ai, raw, schema_extra=()):
    schema = {f: {"ft": "/Tx", "tu": "Enter text: x"} for f in (
        "Vehicle_PhysicalAddress_CityName_A", "Vehicle_PhysicalAddress_StateOrProvinceCode_A",
        "Vehicle_PhysicalAddress_PostalCode_A", *schema_extra)}
    report: list = []
    mapped, conf = ps.map_facts_to_form(
        {"_form_id": "ACORD_127"}, schema, form_id="ACORD_127", raw_text=raw,
        pre_filled_gpt={"filled_values": dict(ai), "raw_text_fields": set(), "question_grounding": {}},
        guard_report=report, allow_llm=False)
    return mapped, conf, {r["field"]: r.get("reason") for r in report if r.get("field")}


def test_a_state_and_zip_move_to_their_empty_boxes_when_the_documents_agree():
    mapped, conf, _ = _city_case({"Vehicle_PhysicalAddress_CityName_A": "DENVER, CO 80221"},
                                 "001 2001CHEVROLET EXPRESS 111 DENVER, CO 80221 21,210")
    assert mapped["Vehicle_PhysicalAddress_CityName_A"] == "Denver"
    assert mapped["Vehicle_PhysicalAddress_StateOrProvinceCode_A"] == "CO"
    assert mapped["Vehicle_PhysicalAddress_PostalCode_A"] == "80221"
    assert conf["Vehicle_PhysicalAddress_StateOrProvinceCode_A"] in ("ai_verified", "low_confidence")


def test_a_filled_or_unsupported_box_is_never_overwritten():
    mapped, _, _ = _city_case({"Vehicle_PhysicalAddress_CityName_A": "Denver, CO",
                               "Vehicle_PhysicalAddress_StateOrProvinceCode_A": "KS"}, "Denver, CO")
    assert mapped["Vehicle_PhysicalAddress_StateOrProvinceCode_A"] == "KS"
    assert mapped["Vehicle_PhysicalAddress_CityName_A"] == "Denver"
    # The documents never print that city with that state: no state is added.
    mapped2, _, _ = _city_case({"Vehicle_PhysicalAddress_CityName_A": "Denver, CO"}, "nothing here")
    assert mapped2["Vehicle_PhysicalAddress_CityName_A"] == "Denver"
    assert mapped2.get("Vehicle_PhysicalAddress_StateOrProvinceCode_A") is None


def test_a_state_code_alone_is_not_a_city_and_moves_nowhere():
    mapped, _, reasons = _city_case({"Vehicle_PhysicalAddress_CityName_A": "Co"}, "Denver, CO 80221")
    assert mapped.get("Vehicle_PhysicalAddress_CityName_A") is None
    assert reasons["Vehicle_PhysicalAddress_CityName_A"] == "STATE_IN_CITY_BOX"
    assert mapped.get("Vehicle_PhysicalAddress_StateOrProvinceCode_A") is None


@pytest.mark.parametrize("address, want", [
    ("1234 Elm Street, Suite 500, Dallas, TX 75201, USA",
     {"line1": "1234 Elm Street", "line2": "Suite 500", "city": "Dallas", "state": "TX", "zip": "75201"}),
    ("12 Main St, Springfield, IL 62701 U.S.A.",
     {"line1": "12 Main St", "city": "Springfield", "state": "IL", "zip": "62701"}),
    ("B-12 Connaught Place, New Delhi, Delhi 110001, India",
     {"line1": "B-12 Connaught Place", "city": "New Delhi", "state": "Delhi", "zip": "110001"}),
    ("100 Main St, Mexico, MO 65265",
     {"line1": "100 Main St", "city": "Mexico", "state": "MO", "zip": "65265"}),
])
def test_a_trailing_country_is_not_the_state(address, want):
    from utils.helpers import _parse_address
    assert _parse_address(address) == want


def test_a_state_and_zip_alone_are_not_a_city():
    mapped, _, reasons = _city_case({"Vehicle_PhysicalAddress_CityName_A": "TX 75201"}, "Dallas, TX 75201")
    assert mapped.get("Vehicle_PhysicalAddress_CityName_A") is None
    assert reasons["Vehicle_PhysicalAddress_CityName_A"] == "STATE_ZIP_IN_CITY_BOX"
    assert mapped["Vehicle_PhysicalAddress_StateOrProvinceCode_A"] == "TX"
    assert mapped["Vehicle_PhysicalAddress_PostalCode_A"] == "75201"


def test_the_garage_storage_description_keeps_its_location():
    # ACORD 127: "The description of the garage / storage location." - the
    # garaging location the auto dec prints for every vehicle is that
    # description; it is not a CITY box and is never split.
    mapped, _, _ = _city_case({"CommercialVehicleLineOfBusiness_GarageStorageDescription_A": "DENVER, CO 80221"},
                              "111 DENVER, CO 80221",
                              ("CommercialVehicleLineOfBusiness_GarageStorageDescription_A",))
    assert mapped["CommercialVehicleLineOfBusiness_GarageStorageDescription_A"] == "DENVER, CO 80221"


# ── 10. #14: a TAX CODE is not the state ─────────────────────────────────────

@pytest.mark.parametrize("form, field, value, kept", [
    ("ACORD_140", "CommercialStructure_TaxCode_A", "CO", False),
    ("ACORD_140", "CommercialStructure_TaxCode_A", "No", False),
    ("ACORD_140", "CommercialStructure_TaxCode_A", "Colorado", False),
    ("ACORD_160", "Location_TaxCode_A", "CO", False),
    ("ACORD_140", "CommercialStructure_TaxCode_A", "0230", True),
    ("ACORD_160", "Location_TaxCode_A", "KY-0145", True),
])
def test_a_state_or_a_yes_no_is_never_a_tax_code(form, field, value, kept):
    mapped, _, reasons = _map({"_form_id": form}, {field: value}, form=form)
    if kept:
        assert mapped[field] == value
    else:
        assert mapped.get(field) is None and reasons[field] == "NOT_A_TAX_CODE"


def test_live_140_tax_code_state_is_refused():
    mapped, _, reasons = _live_140()
    assert mapped.get("CommercialStructure_TaxCode_A") is None
    assert reasons["CommercialStructure_TaxCode_A"] == "NOT_A_TAX_CODE"
