"""Live run 10 (session ed191e49, policy only, 15 Sep 2026) - five fixes.

1. The cover summary said "no prior carrier detail was included" while the same
   cover listed the prior carrier: the cover AI was never given it, and its cache
   ignored the data it was written from.
2. ACORD 125 Q4 "Any other insurance with this company?" listed four EMC
   policies under a CARRIER left blank on purpose (the receiving carrier).
3. ACORD 126's OTHER limit row printed "Commercial General Liability / Commercial
   Auto Liability $1,000" - nothing owned it; runs 4, 8 and 9 each printed a
   different wrong pair.
4. The cover's POLICY PERIOD printed an em-dash pair once the proposed term was
   unknown.
5. The cover warnings listed the OTHER named insured rows as "left blank by the
   AI", reading as if the applicant were missing.
"""
import asyncio
import copy
import io
import json
import os
import re

import pdfplumber
import pytest

import services.cover_service as cs
import services.pdf_service as ps
from services.field_qa import _spare_row_of_an_answered_group, run_field_qa

HERE = os.path.dirname(os.path.abspath(__file__))
EMCC = "EMPLOYERS MUTUAL CASUALTY COMPANY"
EMCPC = "EMC Property & Casualty Company"
PRIOR = f"{EMCC} / {EMCPC}"
EMPTY = (None, "", "UNMATCHED")


def _schema(fid):
    with open(os.path.join(HERE, "..", "forms_schemas", f"{fid}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _mapped(res):
    return res[0] if isinstance(res, tuple) else res


# The live facts' own shape after the merge moved the ended term (run 10).
_ROUTED = {
    "applicant_name": "ORBIN CONTRACTING LLC",
    "renewal_dates_routed": True,
    "prior_effective_date": {"value": "07/15/25", "routed_from": "current_term"},
    "prior_expiration_date": {"value": "07/15/26", "routed_from": "current_term"},
    "prior_carrier": {"value": PRIOR, "source": "derived"},
}


# ── 1. The cover AI is told what the cover prints ────────────────────────────
def _cover_call(monkeypatch, facts):
    seen = {"prompts": [], "keys": []}

    async def _chat(model, messages, **kw):
        seen["prompts"].append(messages[0]["content"])
        return "{}"

    async def _get(key):
        seen["keys"].append(key)
        return None

    async def _set(*a, **k):
        return None

    monkeypatch.setattr(cs, "groq_chat", _chat)
    monkeypatch.setattr(cs, "_cache_get", _get)
    monkeypatch.setattr(cs, "_cache_set", _set)
    asyncio.run(cs.generate_ai_cover_narrative(
        facts, {}, {"ACORD_125": {"sqs_score": 57}, "ACORD_131": {"sqs_score": 82}},
        ["ACORD_125", "ACORD_131"], "Astrea It services", {"full_name": "Vinay Sharma"},
        package_score=61))
    return seen


def test_the_cover_ai_is_told_the_prior_carrier_and_the_current_term(monkeypatch):
    prompt = _cover_call(monkeypatch, _ROUTED)["prompts"][0]
    assert f"Prior Carrier: {PRIOR}" in prompt
    assert "Current Policy Term: 07/15/25 - 07/15/26" in prompt
    assert "Proposed Effective Date: To be confirmed" in prompt


def test_a_term_that_was_not_moved_adds_no_current_term_line(monkeypatch):
    facts = {"applicant_name": "X LLC", "effective_date": "10/01/2026", "expiration_date": "10/01/2027"}
    prompt = _cover_call(monkeypatch, facts)["prompts"][0]
    assert "Current Policy Term" not in prompt
    assert "Proposed Effective Date: 10/01/2026" in prompt
    assert "Prior Carrier: Not provided" in prompt


def test_the_cache_key_follows_the_data_the_ai_reads(monkeypatch):
    a = _cover_call(monkeypatch, _ROUTED)["keys"][0]
    b = _cover_call(monkeypatch, dict(_ROUTED, prior_carrier="Travelers"))["keys"][0]
    c = _cover_call(monkeypatch, copy.deepcopy(_ROUTED))["keys"][0]
    assert a != b          # other data, other paragraph
    assert a == c          # the same data still hits the cache


# ── 4. The cover's submission table ──────────────────────────────────────────
def test_the_policy_period_says_what_is_known():
    v = cs._cover_info_values(_ROUTED, {}, {"full_name": "Vinay Sharma"}, "Astrea It services")
    assert v["period"] == "To be confirmed (current term 07/15/25 - 07/15/26)"
    assert v["prior_carrier"] == PRIOR
    assert v["revenue"] == "Not provided" and v["employees"] == "Not provided"
    assert not [k for k, x in v.items() if "—" in str(x)]


@pytest.mark.parametrize("facts,period", [
    ({"effective_date": "10/01/2026", "expiration_date": "10/01/2027"}, "10/01/2026 - 10/01/2027"),
    ({"effective_date": "10/01/2026"}, "10/01/2026 - to be confirmed"),
    ({}, "To be confirmed"),
    ({"prior_expiration_date": "07/15/26"}, "To be confirmed"),        # an older prior term we did not move
    ({"prior_expiration_date": {"value": "07/15/26", "routed_from": "current_term"}},
     "To be confirmed (current term ending 07/15/26)"),
])
def test_every_period_shape(facts, period):
    v = cs._cover_info_values(facts, {}, None, "")
    assert v["period"] == period
    assert v["agent"] == "Not provided" and v["org"] == "Not provided"


def test_the_rendered_cover_prints_it():
    pdf_bytes = cs.build_cover_page_pdf(
        dict(_ROUTED, mailing_address="4800 DAHLIA ST # D13, DENVER CO 80216-3121"), {},
        {"ACORD_125": {"sqs_score": 57}}, ["ACORD_125"], "Astrea It services", "Narrative.", {},
        user={"full_name": "Vinay Sharma"})
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = re.sub(r"\s+", " ", " ".join(p.extract_text() or "" for p in pdf.pages[:1]))
    # The table cell wraps, and text extraction reads a wrapped cell's second
    # line after the row beside it - so the two halves are checked, not the join.
    assert "To be confirmed (current term 07/15/25 -" in text
    assert "07/15/26)" in text
    assert "— - —" not in text and "ANNUAL REVENUE Not provided" in text


# ── 2. Q4 follows the receiving carrier ──────────────────────────────────────
_LINES = [
    {"line": "General Liability", "carrier": EMCPC, "policy_number": "BBC7263 - 26", "premium": "$3,954.00"},
    {"line": "Commercial Auto", "carrier": EMCC, "policy_number": "6E7-40-02---26", "premium": "$2,991.00"},
    {"line": "Inland Marine", "carrier": EMCC, "policy_number": "6C7-40-02---26", "premium": "$300.00"},
    {"line": "Umbrella", "carrier": EMCC, "policy_number": "6J7-40-02---26", "premium": "$3,418.00"},
]
_Q4 = [f"OtherPolicy_{a}_{r}" for a in ("LineOfBusinessCode", "PolicyNumberIdentifier") for r in "ABCD"]


def _q4_facts(**over):
    f = {"_form_id": "ACORD_125", "coverage_lines": copy.deepcopy(_LINES),
         "carrier_name": {"value": EMCC, "source": "ai"}}
    f.update(over)
    return f


def _q4_numbers(f):
    return {ps._resolve_other_policy_cell(f"OtherPolicy_PolicyNumberIdentifier_{r}", f) for r in "ABCD"} - {None}


@pytest.mark.parametrize("box", _Q4)
def test_q4_is_blank_until_the_receiving_carrier_is_known(box):
    f = _q4_facts(carrier_is_current_policy=True)
    assert ps._resolve_other_policy_cell(box, f) is None
    assert ps._is_authoritative_blank_field(box, f)


def test_q4_yes_no_is_not_asked_either():
    marked = _q4_facts(carrier_is_current_policy=True)
    assert ps._resolve_page_one_receiving_carrier("CommercialPolicy_Question_AAHCode_A", marked) is None
    assert ps._resolve_page_one_receiving_carrier("CommercialPolicy_Question_AAHCode_A", _q4_facts()) \
        is ps._SCHED_SKIP


def test_without_the_mark_q4_lists_every_policy_as_before():
    assert len(_q4_numbers(_q4_facts())) == 4


def test_a_person_named_carrier_lists_only_that_companys_policies():
    named = _q4_facts(carrier_is_current_policy=True,
                      carrier_name={"value": "Employers Mutual Casualty Co.", "source": "producer"})
    # EMC Property & Casualty is another company - its GL is not "with this company"
    assert _q4_numbers(named) == {"6E7-40-02---26", "6C7-40-02---26", "6J7-40-02---26"}
    other = _q4_facts(carrier_name={"value": "Travelers", "source": "producer"})
    assert _q4_numbers(other) == set()


def test_other_forms_are_untouched():
    f = _q4_facts(carrier_is_current_policy=True, _form_id="ACORD_25")
    assert ps._resolve_page_one_receiving_carrier("CommercialPolicy_Question_AAHCode_A", f) is ps._SCHED_SKIP


def test_q4_through_the_stamper_and_gap_fill():
    schema = _schema("ACORD_125")
    f = _q4_facts(carrier_is_current_policy=True)
    m = _mapped(ps.map_facts_to_form(dict(f), schema, "ACORD_125"))
    assert not [k for k in _Q4 if m.get(k) not in EMPTY]
    unmatched = set(ps.compute_form_gaps("ACORD_125", schema, f)[1])
    assert "CommercialPolicy_Question_AAHCode_A" not in unmatched
    assert not [k for k in unmatched if k.startswith("OtherPolicy_")]


# ── 3. The 126 OTHER limit row has an owner ──────────────────────────────────
AMT = "GeneralLiability_OtherCoverageLimitAmount_A"
DESC = "GeneralLiability_OtherCoverageLimitDescription_A"
_GL_DEC = "General Liability Declarations"


def _gl(label, value, section=_GL_DEC):
    return {"label": label, "value": value, "line_of_business": "Commercial General Liability",
            "section": section, "owner": "policy", "policy_number": "BBC7263 - 26"}


# Orbin's own GL declarations entries (live run 10): every printed limit has a box.
_ORBIN_GL = [
    _gl("Each Occurrence Limit", "$1,000,000"),
    _gl("Damage To Premises Rented To You Limit", "$500,000(any one premises)"),
    _gl("Medical Expense Limit", "$10,000(any one person)"),
    _gl("Personal and Advertising Injury Limit", "$1,000,000(any one person or organization)"),
    _gl("General Aggregate Limit", "$2,000,000"),
    _gl("Products/Completed Operations Aggregate Limit", "$2,000,000"),
    _gl("Limited Pollution Coverage - Work Sites", "$150", "General Liability Schedule"),
    _gl("Limit of Insurance", "$500", "General Liability Schedule"),
]


def _gl_facts(entries, **over):
    f = {"_form_id": "ACORD_126", "dec_page_entries": copy.deepcopy(entries),
         "gl_deductible": {"value": "$1,000 Each Pollution Incidents", "source": "ai"}}
    f.update(over)
    return f


def test_orbin_prints_nothing_in_the_other_limit_row():
    f = _gl_facts(_ORBIN_GL)
    for box in (AMT, DESC):
        assert ps._resolve_gl_other_limit(box, f) is None
        assert ps._is_authoritative_blank_field(box, f)
    schema = _schema("ACORD_126")
    unmatched = set(ps.compute_form_gaps("ACORD_126", schema, f)[1])
    assert AMT not in unmatched and DESC not in unmatched          # the AI is never asked
    # ...and the model's live answer, marked found in the text, cannot land either
    live = {"filled_values": {AMT: "$1,000", DESC: "Commercial General Liability / Commercial Auto Liability"},
            "raw_text_fields": {AMT, DESC}, "question_grounding": {}}
    m = _mapped(ps.map_facts_to_form(dict(f), schema, "ACORD_126", pre_filled_gpt=live))
    assert m.get(AMT) in EMPTY and m.get(DESC) in EMPTY


def test_one_extra_declared_limit_prints_as_a_pair():
    f = _gl_facts(_ORBIN_GL + [_gl("Hired and Non-Owned Auto Liability Limit", "$1,000,000")])
    assert ps._resolve_gl_other_limit(DESC, f) == "Hired and Non-Owned Auto Liability"
    assert ps._resolve_gl_other_limit(AMT, f) == "$1,000,000"


def test_two_extra_limits_cannot_share_one_row():
    f = _gl_facts(_ORBIN_GL + [_gl("Hired and Non-Owned Auto Liability Limit", "$1,000,000"),
                               _gl("Liquor Liability Limit", "$1,000,000")])
    assert ps._resolve_gl_other_limit(AMT, f) is None
    assert ps._resolve_gl_other_limit(DESC, f) is None


@pytest.mark.parametrize("section", ["Schedule of Underlying Insurance", "General Liability Schedule",
                                     "Umbrella Declarations - Underlying"])
def test_only_the_gl_declarations_decide(section):
    f = _gl_facts(_ORBIN_GL + [_gl("Hired and Non-Owned Auto Liability Limit", "$1,000,000", section)])
    assert ps._resolve_gl_other_limit(AMT, f) is None


def test_a_deductible_is_never_a_limit():
    f = _gl_facts(_ORBIN_GL + [_gl("Property Damage Deductible Limit", "$1,000")])
    assert ps._resolve_gl_other_limit(AMT, f) is None


def test_acord_25_keeps_its_rule():
    assert ps._resolve_gl_other_limit(AMT, dict(_gl_facts(_ORBIN_GL), _form_id="ACORD_25")) is ps._SCHED_SKIP


@pytest.mark.parametrize("entries", [None, "junk", [None, 3], [{"label": None, "value": None}]])
def test_junk_never_raises(entries):
    ps._resolve_gl_other_limit(AMT, _gl_facts([], dec_page_entries=entries))


# ── 5. An empty spare row is not an unanswered question ──────────────────────
def _not_answered(mapped, confidence, fid="ACORD_125"):
    res = run_field_qa({fid: {"mapped": mapped, "confidence": confidence, "schema": _schema(fid)}},
                       merged_facts={}, flags={})
    return {r["field"] for r in res.get("results") or [] if r.get("reason_code") == "not_answered"}


def test_an_empty_other_named_insured_row_is_not_listed():
    conf = {"NamedInsured_FullName_A": "filled", "NamedInsured_FullName_B": "low_confidence",
            "NamedInsured_FullName_C": "low_confidence"}
    listed = _not_answered({"NamedInsured_FullName_A": "Orbin Contracting LLC"}, conf)
    assert "NamedInsured_FullName_B" not in listed and "NamedInsured_FullName_C" not in listed
    # the control: with row A empty, the same box IS listed - the rule, not an owner, removed it
    assert "NamedInsured_FullName_B" in _not_answered({}, conf)


@pytest.mark.parametrize("field,mapped,expected", [
    ("NamedInsured_FullName_B", {"NamedInsured_FullName_A": "X"}, True),
    ("NamedInsured_FullName_N", {"NamedInsured_FullName_A": "X"}, True),
    ("NamedInsured_FullName_B", {}, False),
    ("NamedInsured_FullName_B", {"NamedInsured_FullName_A": "  "}, False),
    ("NamedInsured_FullName_A", {"NamedInsured_FullName_A": "X"}, False),
    ("CommercialPolicy_Question_AAHCode_A", {}, False),
    ("", {}, False),
    (None, None, False),
])
def test_the_spare_row_rule(field, mapped, expected):
    assert _spare_row_of_an_answered_group(field, mapped) is expected
