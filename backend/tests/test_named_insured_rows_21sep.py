"""A row's OWN value is not an echo of row A - A125 kit, 21 Sep 2026.

Three defects, measured on the live kit, all in the same family: the form
prints a TABLE of parties and the pipeline treated a repeat as a duplicate,
a package scalar as the applicant's, and an empty box as free space.

1. Guard 2 (repeating-row de-dup) deleted row B's state ("OR") and row C's
   SIC (1711) / NAICS (238220) because row A carries the same values. Three
   companies in one state are all "OR"; two mechanical contractors share a
   class code. Equality is not duplication when the row's OWN fact says so.
2. `applicant_website` held the SECOND insured's site, so row A printed the
   wrong party's website while that party's own row was blank.
3. The loss-overflow sentence REPLACED the applicant's own stated remark,
   which is the one failure mode this file calls worse than a wrong value:
   a missing value nobody can see.
"""
import json
import pathlib

import pytest

from services.pdf_service import (
    _resolve_applicant_website,
    _website_belongs_to_another_named_insured,
    map_facts_to_form,
)

_SCHEMA = json.loads(
    (pathlib.Path(__file__).resolve().parents[1] /
     "forms_schemas" / "ACORD_125_schema.json").read_text(encoding="utf-8"))

# Two OTHER named insureds. Row C's codes are deliberately IDENTICAL to the
# applicant's - that is the live shape, not a contrivance.
_DETAILS = [
    {"name": "Cedar Bluff Steel Fabricators, Inc.", "sic": "3441",
     "naics": "332312", "website": "www.cedarbluffsteel.com", "state": "OR"},
    {"name": "Tualatin Valley Mechanical Services, LLC", "sic": "1711",
     "naics": "238220", "state": "OR"},
]


def _facts(**over):
    f = {"applicant_name": "Meridian Ironworks & Mechanical, LLC",
         "sic_code": "1711", "naics_code": "238220",
         "applicant_state": "OR",
         "additional_named_insureds": [d["name"] for d in _DETAILS],
         "named_insured_details": _DETAILS}
    f.update(over)
    return f


def _stamp(facts):
    mapped, _ = map_facts_to_form(facts, _SCHEMA, form_id="ACORD_125", raw_text="")
    return mapped


# ── 1. A grounded row keeps its own value ────────────────────────────────────

@pytest.mark.parametrize("field,expected", [
    ("NamedInsured_SICCode_C", "1711"),      # == row A's SIC, and correct
    ("NamedInsured_NAICSCode_C", "238220"),  # == row A's NAICS, and correct
    ("NamedInsured_SICCode_B", "3441"),      # differs from A, never at risk
])
def test_a_grounded_row_value_survives_guard_2(field, expected):
    assert _stamp(_facts())[field] == expected


def test_row_b_state_survives_when_every_party_is_in_one_state():
    """The live deletion: three Oregon companies, and B and C went blank."""
    m = _stamp(_facts())
    assert m["NamedInsured_MailingAddress_StateOrProvinceCode_B"] == "OR"
    assert m["NamedInsured_MailingAddress_StateOrProvinceCode_C"] == "OR"


def test_an_ungrounded_duplicate_is_still_blanked():
    """The exemption is GROUNDED-only. With no detail fact, a value equal to
    row A is still a gap-fill echo and Guard 2 must still delete it - the
    behaviour this guard exists for."""
    facts = _facts()
    facts.pop("named_insured_details")
    mapped, _ = map_facts_to_form(
        facts, _SCHEMA, form_id="ACORD_125", raw_text="",
        pre_filled_gpt={"NamedInsured_SICCode_C": "1711"})
    assert not mapped.get("NamedInsured_SICCode_C")


def test_a_row_value_that_contradicts_its_own_fact_is_not_exempt():
    """The exemption matches the fact's value, never merely its presence."""
    facts = _facts()
    mapped, _ = map_facts_to_form(
        facts, _SCHEMA, form_id="ACORD_125", raw_text="",
        pre_filled_gpt={"NamedInsured_SICCode_C": "1711"})
    # stamped from the fact either way, never from the guess
    assert mapped["NamedInsured_SICCode_C"] == "1711"


# ── 2. A scalar that names another party does not print on row A ─────────────

def test_row_a_website_is_blank_when_another_insured_owns_it():
    facts = _facts(applicant_website="www.cedarbluffsteel.com")
    m = _stamp(facts)
    assert m["NamedInsured_Primary_WebsiteAddress_A"] is None
    assert m["NamedInsured_Primary_WebsiteAddress_B"] == "www.cedarbluffsteel.com"


def test_the_applicants_own_website_still_prints():
    facts = _facts(applicant_website="www.meridianiw.com")
    assert _stamp(facts)["NamedInsured_Primary_WebsiteAddress_A"] == "www.meridianiw.com"


def test_without_the_detail_fact_the_website_behaves_exactly_as_before():
    facts = _facts(applicant_website="www.cedarbluffsteel.com")
    facts.pop("named_insured_details")
    assert _resolve_applicant_website(
        "NamedInsured_Primary_WebsiteAddress_A", facts) == "www.cedarbluffsteel.com"


@pytest.mark.parametrize("site,claimed,hit", [
    ("www.cedarbluffsteel.com", "www.cedarbluffsteel.com", True),
    ("WWW.CedarBluffSteel.com/", "www.cedarbluffsteel.com", True),   # formatting
    ("www.meridianiw.com", "www.cedarbluffsteel.com", False),
    ("", "www.cedarbluffsteel.com", False),
])
def test_website_ownership_is_decided_by_the_fact(site, claimed, hit):
    facts = {"named_insured_details": [{"name": "Other", "website": claimed}]}
    assert _website_belongs_to_another_named_insured(site, facts) is hit


@pytest.mark.parametrize("bad", [None, [], "not a list", [None], [{}]])
def test_website_ownership_never_raises_on_a_malformed_fact(bad):
    assert _website_belongs_to_another_named_insured("www.x.com",
                                                     {"named_insured_details": bad}) is False


# ── 3. The remarks box carries BOTH the remark and the overflow ──────────────

_LOSSES = [{"date": f"0{i}/01/2024", "claim_number": f"C-{i}",
            "line_of_business": "General Liability",
            "description": f"claim {i}", "paid": "$1,000"} for i in range(1, 6)]


def test_the_stated_remark_survives_a_loss_overflow():
    facts = _facts(loss_history=_LOSSES,
                   additional_remarks_text="Location 005 is a seasonal lease.")
    box = _stamp(facts)["CommercialPolicy_RemarkText_A"]
    assert "Location 005 is a seasonal lease." in box, "the applicant's remark was deleted"
    assert "ADDITIONAL LOSSES NOT SHOWN" in box, "the overflow notice was lost"
    assert box.index("Location 005") < box.index("ADDITIONAL LOSSES")


def test_the_overflow_alone_is_unchanged_without_a_stated_remark():
    facts = _facts(loss_history=_LOSSES)
    box = _stamp(facts)["CommercialPolicy_RemarkText_A"]
    assert box.startswith("ADDITIONAL LOSSES NOT SHOWN")


def test_the_remark_is_never_printed_twice():
    facts = _facts(loss_history=_LOSSES,
                   additional_remarks_text="ADDITIONAL LOSSES NOT SHOWN IN THE LOSS "
                                           "HISTORY GRID ABOVE (1 of 5 total): x.")
    box = _stamp(facts)["CommercialPolicy_RemarkText_A"]
    assert box.count("ADDITIONAL LOSSES NOT SHOWN") == 1


# ── 4. Page one is addressed to somebody - the carrier RECEIVING it ──────────
#
# `_resolve_page_one_receiving_carrier` correctly REFUSED the expiring
# carrier (15 Sep) and nothing ever supplied the right one, so CARRIER and NAIC
# shipped empty on a package that names the addressee twice. The same gap made
# STATUS tick RENEW: the programme IS a renewal, but it is being sent to a
# DIFFERENT market, and ACORD's RENEW asks the receiving carrier to renew its
# OWN policy. Brent's key: QUOTE ticked, RENEW blank.

from services.pdf_service import _receiving_carrier_from_entries

_COVER = "COMMERCIAL LINES SUBMISSION - COVER SHEET"
_DECS = "COMMON POLICY DECLARATIONS"


def _entries(*rows):
    return [{"label": l, "value": v, "section": s, "owner": o} for l, v, s, o in rows]


_SUBMISSION = _entries(
    ("Submitted by", "Priscilla Vandermeer", _COVER, "producer"),
    ("SUBMITTED TO", "Northbridge Atlantic Insurance Company", _COVER, "carrier"),
    ("NAIC", "41394", _COVER, "carrier"),
    ("ISSUED BY", "Cascadia Harbor Mutual", _DECS, "carrier"),
    ("NAIC", "26251", _DECS, "carrier"),
)


def _page_one_facts(**over):
    f = {"_form_id": "ACORD_125",
         "carrier_name": "Cascadia Harbor Mutual Insurance Company",
         "carrier_naic": "26251",
         "carrier_is_current_policy": True,
         "is_renewal": "Y",
         "dec_page_entries": _SUBMISSION}
    f.update(over)
    return f


def test_the_receiving_carrier_and_its_naic_are_read_as_a_pair():
    got = _receiving_carrier_from_entries(_page_one_facts())
    assert got == {"name": "Northbridge Atlantic Insurance Company", "naic": "41394"}


def test_the_naic_never_pairs_across_sections():
    """The kit prints four carriers and five NAIC numbers. A name from one
    section must never take a number from another."""
    facts = _page_one_facts(dec_page_entries=_entries(
        ("SUBMITTED TO", "Northbridge Atlantic Insurance Company", _COVER, "carrier"),
        ("NAIC", "26251", _DECS, "carrier")))
    assert _receiving_carrier_from_entries(facts) == {
        "name": "Northbridge Atlantic Insurance Company", "naic": None}


def test_two_addressees_in_one_section_yield_nothing():
    facts = _page_one_facts(dec_page_entries=_entries(
        ("SUBMITTED TO", "Northbridge Atlantic Insurance Company", _COVER, "carrier"),
        ("CARRIER RECEIVING SUBMISSION", "Harborview Mutual", _COVER, "carrier")))
    assert _receiving_carrier_from_entries(facts) is None


def test_the_producer_who_submitted_it_is_not_the_carrier():
    facts = _page_one_facts(dec_page_entries=_entries(
        ("Submitted by", "Willamette Bay Risk", _COVER, "producer")))
    assert _receiving_carrier_from_entries(facts) is None


@pytest.mark.parametrize("entries", [None, [], "nonsense", [None], [{"label": "SUBMITTED TO"}]])
def test_the_reader_never_raises_on_a_malformed_index(entries):
    assert _receiving_carrier_from_entries({"dec_page_entries": entries}) is None


def test_page_one_prints_the_receiving_carrier_and_naic():
    m = _stamp(_page_one_facts())
    assert m["Insurer_FullName_A"] == "Northbridge Atlantic Insurance Company"
    assert m["Insurer_NAICCode_A"] == "41394", "the pair guard blanked an attested NAIC"


def test_the_expiring_carrier_never_reaches_page_one():
    m = _stamp(_page_one_facts())
    assert "Cascadia" not in str(m.get("Insurer_FullName_A"))


def test_without_a_stated_addressee_the_box_stays_the_blank_it_was():
    """No dec index, no opinion - the 15 Sep behaviour, unchanged."""
    facts = _page_one_facts()
    facts.pop("dec_page_entries")
    m = _stamp(facts)
    assert m.get("Insurer_FullName_A") is None
    assert m.get("Insurer_NAICCode_A") is None


def test_a_renewal_sent_to_another_market_is_a_quote():
    m = _stamp(_page_one_facts())
    assert m["Policy_Status_QuoteIndicator_A"] == "Yes"
    assert m.get("Policy_Status_RenewIndicator_A") is None


def test_a_renewal_going_back_to_its_own_carrier_still_ticks_renew():
    """The distinction the fix turns on - not "is it a renewal" but "whose"."""
    facts = _page_one_facts(dec_page_entries=_entries(
        ("SUBMITTED TO", "Cascadia Harbor Mutual Insurance Company", _COVER, "carrier"),
        ("NAIC", "26251", _COVER, "carrier")))
    m = _stamp(facts)
    assert m["Policy_Status_RenewIndicator_A"] == "Yes"
    assert m.get("Policy_Status_QuoteIndicator_A") is None


def test_a_package_with_no_addressee_keeps_the_old_renewal_answer():
    facts = _page_one_facts()
    facts.pop("dec_page_entries")
    assert _stamp(facts)["Policy_Status_RenewIndicator_A"] == "Yes"


# ── 5. "FOR THE LAST __ YEARS" was extracted and bound to nothing ────────────

def test_the_stated_loss_history_years_prints():
    facts = _facts(loss_history=[{"date": "01/01/2024", "description": "x"}],
                   loss_history_years="5")
    assert _stamp(facts)["LossHistory_InformationYearCount_A"] == "5"


@pytest.mark.parametrize("stated,expected", [
    ("5", "5"), ("5 years", "5"), (" 3 ", "3"), ("10", "10"),
    (None, None), ("", None), ("unknown", None), ("0", None), ("120", None),
])
def test_only_a_usable_stated_year_count_prints(stated, expected):
    """Silence stays blank; a number outside 1-99 is not a year count."""
    facts = _facts(loss_history=[{"date": "01/01/2024", "description": "x"}],
                   loss_history_years=stated)
    got = _stamp(facts).get("LossHistory_InformationYearCount_A")
    assert (got == expected) if expected else not got


def test_the_year_count_is_never_counted_from_the_rows():
    """A five-year history with one claim still says five - the box is a
    STATED period, and deriving it from the dates would assert a shorter one."""
    facts = _facts(loss_history=[{"date": "01/01/2024", "description": "x"}])
    assert not _stamp(facts).get("LossHistory_InformationYearCount_A")


# ── 6. Guard 2 must respect EVERY per-row fact, not just the insured rows ────
#
# The first cut of the exemption named `_resolve_named_insured_detail` alone.
# Live A125 run (22 Sep): all four premises carry BLD # "001", so Guard 2
# deleted rows B, C and D as echoes of row A. The leased-to-others column
# beside them survived only because a Yes/No value was already exempt.

_LOCS = [
    {"address_line1": "2250 NW Vaughn St", "address_city": "Portland",
     "building_number": "001", "any_area_leased_to_others": "N"},
    {"address_line1": "811 SE Ironwood Ct", "address_city": "Gresham",
     "building_number": "001", "any_area_leased_to_others": "Y"},
    {"address_line1": "15980 SW Upper Boones Ferry Rd", "address_city": "Tigard",
     "building_number": "001", "any_area_leased_to_others": "N"},
]


def test_every_premises_keeps_its_own_building_number():
    m = _stamp(_facts(property_locations=_LOCS))
    got = [m.get(f"CommercialStructure_Building_ProducerIdentifier_{r}") for r in "ABC"]
    assert got == ["001", "001", "001"], f"Guard 2 deleted a grounded row: {got}"


def test_an_ungrounded_premises_repeat_is_still_blanked():
    locs = [dict(r) for r in _LOCS]
    for r in locs:
        r.pop("building_number")
    mapped, _ = map_facts_to_form(
        _facts(property_locations=locs), _SCHEMA, form_id="ACORD_125", raw_text="",
        pre_filled_gpt={"CommercialStructure_Building_ProducerIdentifier_A": "001",
                        "CommercialStructure_Building_ProducerIdentifier_B": "001"})
    assert not mapped.get("CommercialStructure_Building_ProducerIdentifier_B")


# ── 7. One sentence cannot answer two questions ─────────────────────────────

from services.pdf_service import _quote_is_shared_across_topics

_TRUST_SENTENCE = "The business has not been placed in a trust."


def _disclosures(**over):
    rows = [
        {"topic": "business_in_trust", "answer": "N", "evidence_quote": _TRUST_SENTENCE},
        {"topic": "foreclosure_repossession_bankruptcy", "answer": "N",
         "evidence_quote": _TRUST_SENTENCE},          # BORROWED - the live defect
        {"topic": "judgement_or_lien", "answer": "Y",
         "evidence_quote": "A mechanics lien was recorded on 08/14/2023.",
         "explanation": "A mechanics lien was recorded on 08/14/2023.",
         "occurrence_date": "08/14/2023"},
    ]
    rows and over and rows.extend(over.get("extra", []))
    return rows


def test_a_borrowed_quote_is_refused():
    rows = _disclosures()
    assert _quote_is_shared_across_topics(rows, _TRUST_SENTENCE,
                                          "foreclosure_repossession_bankruptcy")
    assert _quote_is_shared_across_topics(rows, _TRUST_SENTENCE, "business_in_trust")


def test_a_topic_with_its_own_sentence_is_untouched():
    rows = _disclosures()
    assert not _quote_is_shared_across_topics(
        rows, "A mechanics lien was recorded on 08/14/2023.", "judgement_or_lien")


@pytest.mark.parametrize("variant", [
    "the business has not been placed in a trust.",          # case
    "The  business   has not been placed in a trust.",       # spacing
])
def test_a_reformatted_copy_is_the_same_sentence(variant):
    assert _quote_is_shared_across_topics(_disclosures(), variant,
                                          "foreclosure_repossession_bankruptcy")


@pytest.mark.parametrize("rows", [None, [], [None], [{}], "nonsense"])
def test_the_share_check_never_raises(rows):
    assert _quote_is_shared_across_topics(rows, "x", "t") is False


def test_a_shared_quote_answers_neither_question_deterministically():
    """Blank over wrong: with one sentence cited twice, neither topic is
    trusted here - both fall to the gated LLM path, which is what this
    resolver already does for a topic with no quote at all."""
    facts = _facts(disclosure_answers=_disclosures())
    m = _stamp(facts)
    answered = [f for f in m
                if f.startswith("CommercialPolicy_Question_") and m.get(f) in ("Y", "N")]
    for f in answered:
        assert m[f] in ("Y", "N")      # whatever survives is a real answer
    # the lien question, which owns its own sentence, is still answered
    assert any(m.get(f) == "Y" for f in m if f.startswith("CommercialPolicy_Question_"))


# ── 8. ANTI-ROT: the guard chain must stay INSIDE the guard function ────────
#
# 22 Sep 2026: a helper added for §6 was inserted as a top-level `def` in the
# MIDDLE of `_enforce_post_fill_guards`. Python accepted it - Guards 2 to 8
# (1,234 lines) became the body of the helper and the guard chain ended after
# Guard 1. The module imported, the new tests passed, the ACORD score did not
# move; only the full suite caught it, going from 2 failures to 89. Every
# post-fill protection was dead: row de-dup, wrong-type rejection, boilerplate
# bleed, explanation-without-a-Yes.
#
# A line-count pin would rot. This asserts each guard's own log marker is
# lexically inside the function that is supposed to run it.

_GUARD_MARKERS = (
    "row_dedup",                 # Guard 2
    "boilerplate_bleed",         # Guard 4
    "tooltip_echo",              # Guard 8
    "naic_pair",                 # NAIC pairing
)


def _guard_function_span():
    import ast
    root = pathlib.Path(__file__).resolve().parents[1]
    src = (root / "services" / "pdf_service.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_enforce_post_fill_guards":
            return src, node
    raise AssertionError("_enforce_post_fill_guards not found")


@pytest.mark.parametrize("marker", _GUARD_MARKERS)
def test_every_guard_still_lives_inside_the_guard_function(marker):
    src, fn = _guard_function_span()
    body = "\n".join(src.splitlines()[fn.lineno - 1:fn.end_lineno])
    assert marker in body, (
        f"guard {marker!r} is no longer inside _enforce_post_fill_guards - "
        "a top-level def inserted mid-function silently truncates the chain")


def test_no_helper_has_swallowed_the_guard_chain():
    """The chain is long. A helper that has absorbed it would be longer."""
    _, fn = _guard_function_span()
    assert (fn.end_lineno - fn.lineno) > 500, (
        "_enforce_post_fill_guards is suspiciously short - the guards after the "
        "first are probably inside a helper defined mid-function")
