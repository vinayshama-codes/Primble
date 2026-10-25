"""Build of 21 Oct 2026, lane B, item b-rows-and-restamp (25sepChanges.md Z29-6,
Z30-B). Brent's 17 Oct Choice Electric test:

1. Item 9 - ACORD 130 with one officer listed "Full name of the partner or
   executive officer ..." for rows 1, 2 and 3 as "Missing - a high-impact box
   the AI left blank". An entirely empty row AFTER the last row its section uses
   is not a gap (`needs_attention.unused_trailing_row`), on every repeating
   section of every form, read by the side panel, field QA's record and the E&O
   rows alike.
2. Item 10's two "appears inconsistently" warnings:
   (a) the re-stamp read its own box map (`arq_service._canonical_keys_for`),
       which could not see 38 of the stamper's 329 fact -> box links; the 131
       printed the first revenue answer after forms and froze on it. One map now
       (`pdf_service.facts_stamping_box`, the reverse of `fact_to_form_fields`).
   (b) the warning said the forms disagreed with each other; they disagreed with
       the submission's figure. It says so now.
   (c) the AI's $3,200,000 / $2,626,500 sat in the 131's company row B, a
       company nobody named (`pdf_service._company_row_columns`, reason
       ROW_HAS_NO_IDENTITY).

Offline: real schemas and templates, no database, no model.
"""
import asyncio
import copy
import json
import os
import re
from unittest.mock import patch

import pytest

import services.arq_service as arq
import services.field_qa as fq
import services.needs_attention as na
import services.pdf_service as ps
from services.underwriting_consistency import stamp_mismatch_issues

HERE = os.path.dirname(os.path.abspath(__file__))


def _schema(form_id):
    with open(os.path.join(HERE, "..", "forms_schemas", f"{form_id}_schema.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


# ═══════════════════════════════════════════════════════════════════════════
# PART 1 - a row the form does not use is not a gap (item 9)
# ═══════════════════════════════════════════════════════════════════════════

S130 = _schema("ACORD_130")
OFFICER = [f for f in S130 if f.startswith("WorkersCompensation_Individual_")]
NAME = "WorkersCompensation_Individual_FullName_{}"


def _form130(officers=(), rate_rows="ABC", extra_state=None, extra_conf=None):
    """An ACORD 130 as generation leaves it: every officer box the AI was asked
    about empty and labelled low_confidence; `officers` = {row: name}."""
    state = {f: "" for f in S130}
    conf = {f: "low_confidence" for f in OFFICER}
    for letter in rate_rows:                          # the rating classes, used
        state[f"WorkersCompensation_RateClass_ClassificationCode_{letter}"] = "5190"
        state[f"WorkersCompensation_RateClass_RemunerationAmount_{letter}"] = "875500"
        conf[f"WorkersCompensation_RateClass_ClassificationCode_{letter}"] = "filled"
    for letter, name in dict(officers).items():
        state[NAME.format(letter)] = name
        conf[NAME.format(letter)] = "producer"
    state.update(extra_state or {})
    conf.update(extra_conf or {})
    return {"schema": S130, "field_state": state, "mapped": dict(state), "confidence": conf}


def _panel(fr, form_id="ACORD_130"):
    return na.needs_attention(fr, {}, form_id, findings={"high_impact_boxes": True, "values": []})


def _officer_rows(rows):
    return sorted(r["field"] for r in rows if r["field"].startswith("WorkersCompensation_Individual_"))


def test_no_officer_lists_one_row_not_four():
    """The 17 Oct state at generation: no officer. Row 1 asks for one entry;
    rows 2-4 are rows the form does not use."""
    rows = _panel(_form130())
    assert _officer_rows(rows) == [NAME.format("A")]
    row = next(r for r in rows if r["field"] == NAME.format("A"))
    assert row["status"] == na.STATUS_MISSING and row["reason"] == na.HIGH_IMPACT_BLANK_REASON
    assert "wc_officers" in row["fold_keys"]          # still folds onto the officer card


def test_before_the_rule_all_four_were_listed():
    """The defect reproduced: with the rule switched off, rows 1-4 are listed."""
    with patch.object(na, "unused_trailing_row", lambda *a, **k: False):
        rows = _panel(_form130())
    assert _officer_rows(rows) == [NAME.format(L) for L in "ABCD"]


def test_one_officer_lists_nothing_and_three_rating_rows_do_not_keep_officer_rows_open():
    """Eric Berger in row 1; the WC rating table uses rows A-C under the same
    name root - a different table (rows A-N), so it keeps no officer row open."""
    for rate_rows in ("", "ABC", "ABCDEFGHIJKLMN"):
        rows = _panel(_form130(officers={"A": "Eric Berger"}, rate_rows=rate_rows))
        assert _officer_rows(rows) == [], rate_rows


def test_two_officers_keep_a_missing_box_inside_a_used_row():
    """Rows A and B used: a required box empty INSIDE row B stays Missing; the
    same box in the unused rows C and D does not."""
    state_col = "WorkersCompensation_Individual_StateOrProvinceCode_{}"
    fr = _form130(officers={"A": "Eric Berger", "B": "Dana Berger"},
                  extra_conf={state_col.format(L): "missing_required" for L in "ABCD"})
    listed = _officer_rows(_panel(fr))
    assert state_col.format("A") in listed and state_col.format("B") in listed
    assert state_col.format("C") not in listed and state_col.format("D") not in listed


def test_an_empty_row_before_a_used_row_stays():
    """Row A empty, row B used (an officer typed into row 2): row A is inside the
    used range and stays; C and D go."""
    rows = _panel(_form130(officers={"B": "Dana Berger"}))
    assert _officer_rows(rows) == [NAME.format("A")]


def test_an_unticked_box_does_not_use_a_row_but_typed_text_does():
    sec = "WorkersCompensation_Individual_{}_{}"
    m = {sec.format("FullName", "A"): "Eric Berger"}
    assert na.unused_trailing_row(NAME.format("C"), m, "ACORD_130")
    m2 = dict(m, **{sec.format("OwnershipPercent", "C"): "0"})
    assert not na.unused_trailing_row(NAME.format("C"), m2, "ACORD_130")   # "0" is typed text
    assert na.unused_trailing_row(NAME.format("D"), m2, "ACORD_130")       # D still after C


def test_127_three_of_thirteen_driver_rows():
    """Drivers in rows A-C of 13; a required licence box is listed for the
    three drivers (inside used rows) and for none of the ten empty rows."""
    s = _schema("ACORD_127")
    lic = "Driver_LicenseNumberIdentifier_{}"
    letters = "ABCDEFGHIJKLM"
    assert all(lic.format(L) in s for L in letters)
    state = {f: "" for f in s}
    conf = {lic.format(L): "missing_required" for L in letters}
    for L, (given, sur) in zip("ABC", [("Ann", "Lee"), ("Bo", "Kim"), ("Cy", "Ray")]):
        state[f"Driver_GivenName_{L}"], state[f"Driver_Surname_{L}"] = given, sur
        conf[f"Driver_GivenName_{L}"] = conf[f"Driver_Surname_{L}"] = "filled"
    fr = {"schema": s, "field_state": state, "mapped": dict(state), "confidence": conf}
    listed = sorted(r["field"] for r in na.needs_attention(fr, {}, "ACORD_127")
                    if r["field"].startswith("Driver_LicenseNumberIdentifier_"))
    assert listed == [lic.format(L) for L in "ABC"]


def test_a_section_with_every_row_empty_keeps_its_first_row_only():
    s = _schema("ACORD_127")
    lic = "Driver_LicenseNumberIdentifier_{}"
    state = {f: "" for f in s}
    conf = {lic.format(L): "missing_required" for L in "ABCDEFGHIJKLM"}
    fr = {"schema": s, "field_state": state, "mapped": dict(state), "confidence": conf}
    listed = sorted(r["field"] for r in na.needs_attention(fr, {}, "ACORD_127")
                    if r["field"].startswith("Driver_LicenseNumberIdentifier_"))
    assert listed == [lic.format("A")]


def test_boxes_acord_numbers_per_row_with_their_own_words_are_never_judged():
    """ACORD 25's insurer letters ("As used here, this is Insurer B") are not a
    column; nothing about them changes."""
    assert not na.unused_trailing_row("Insurer_FullName_C", {}, "ACORD_25")
    assert not na.unused_trailing_row("Insurer_FullName_F", {}, "ACORD_25")


def test_signing_steps_and_rows_printed_on_different_pages_are_never_judged():
    """ACORD 130's second applicant signature is a signing step, not a list
    row; ACORD 137's hired-cost boxes A / B / C are one per coverage section,
    a page each - not three rows of one list."""
    assert not na.unused_trailing_row("NamedInsured_Signature_B", {}, "ACORD_130")
    m = {"Vehicle_HiredBorrowed_HiredCostAmount_A": "5000"}
    for row in "BC":
        assert not na.unused_trailing_row(f"Vehicle_HiredBorrowed_HiredCostAmount_{row}", m, "ACORD_137_CA")
    where, _cells, _btn = na._repeating_sections("ACORD_137_CA")
    assert not any(f.startswith("Vehicle_HiredBorrowed_HiredCostAmount_") for f in where)


@pytest.mark.parametrize("form_id", ["", "ACORD_999", None])
def test_an_unreadable_form_judges_nothing(form_id):
    assert not na.unused_trailing_row(NAME.format("C"), {}, form_id)


def test_a_first_row_and_a_non_row_box_are_never_judged():
    assert not na.unused_trailing_row(NAME.format("A"), {}, "ACORD_130")
    assert not na.unused_trailing_row("Policy_EffectiveDate_A", {}, "ACORD_130")
    assert not na.unused_trailing_row("NoSuchBox_B", {}, "ACORD_130")


def test_a_second_copy_reads_its_forms_sections():
    m = {"CommercialStructure_Location_FullName_A": "Choice Electric LLC"}
    assert na.unused_trailing_row("CommercialStructure_Location_FullName_C", m, "ACORD_131__excess")
    assert na.unused_trailing_row("CommercialStructure_Location_FullName_C", m, "ACORD_131")


def test_the_131_company_table_is_one_section_across_its_two_name_roots():
    """A payroll typed in row B (BusinessInformation) uses the row whose NAME
    sits in CommercialStructure: row B's name box is inside a used row."""
    m = {"BusinessInformation_TotalPayrollAmount_B": "300000"}
    assert not na.unused_trailing_row("CommercialStructure_Location_FullName_B", m, "ACORD_131")
    assert na.unused_trailing_row("CommercialStructure_Location_FullName_C", m, "ACORD_131")


def test_the_130_officer_and_rating_tables_are_separate_sections():
    where, cells, _btn = na._repeating_sections("ACORD_130")
    officer = where[NAME.format("B")][0]
    rating = where["WorkersCompensation_RateClass_ClassificationCode_B"][0]
    assert officer != rating
    assert officer[1] == "ABCD" and rating[1] == "ABCDEFGHIJKLMN"


def test_field_qa_record_and_e_and_o_rows_agree_with_the_panel():
    """The download review's stored rows and the E&O record are written from
    field QA and the same door: one officer row, not four."""
    fr = _form130()
    qa = fq.run_field_qa({"ACORD_130": fr}, merged_facts={})
    blank = sorted(r["field"] for r in qa["results"]
                   if r.get("reason_code") == "not_answered" and r["field"].startswith(
                       "WorkersCompensation_Individual_FullName_"))
    assert blank == [NAME.format("A")]
    att = na.needs_attention_for_session({"ACORD_130": fr}, {}, findings=True)
    eo = na.attention_recommendation_rows(att)
    officer_lines = [r["message"] for r in eo if "partner or executive officer" in r["message"].lower()]
    assert officer_lines and all("(row 2)" not in m and "(row 3)" not in m for m in officer_lines)


def test_stored_orbin_125s_are_unchanged():
    """Measured on the two stored ACORD 125 generations: no row moves."""
    with open(os.path.join(HERE, "fixtures", "needs_attention_live_30sep.json"), encoding="utf-8") as fh:
        data = json.load(fh)
    for key in ("b8d6", "8992"):
        sess = data[key]
        fr = sess["generated_forms"]["ACORD_125"]
        new = na.needs_attention(fr, sess["facts"], "ACORD_125", flags=sess.get("flags"),
                                 findings={"high_impact_boxes": True, "values": []})
        with patch.object(na, "unused_trailing_row", lambda *a, **k: False):
            old = na.needs_attention(fr, sess["facts"], "ACORD_125", flags=sess.get("flags"),
                                     findings={"high_impact_boxes": True, "values": []})
        assert [(r["field"], r["status"]) for r in new] == [(r["field"], r["status"]) for r in old]


# ═══════════════════════════════════════════════════════════════════════════
# PART 2(a) - one box map for the re-stamp
# ═══════════════════════════════════════════════════════════════════════════

def _real_facts():
    return sorted(f for f in ps._fact_form_links()
                  if isinstance(f, str) and f and not f.startswith("_"))


def test_every_stamper_link_is_visible_to_the_restamp_map():
    """The invariant: a fact -> box link of `fact_to_form_fields` that
    `_canonical_keys_for` cannot see is a box the re-stamp freezes."""
    missing = []
    links = 0
    for fact in _real_facts():
        for fid, fields in ps.fact_to_form_fields(fact).items():
            for box in fields:
                links += 1
                if fact not in arq._canonical_keys_for(box):
                    missing.append((fact, fid, box))
    assert links >= 329
    assert missing == []


def test_the_38_links_of_z29_6_are_visible():
    expected = {
        "mailing_address": ("ACORD_125", "ACORD_130", "ACORD_25", "ACORD_28"),
        "physical_address": ("ACORD_125", "ACORD_131", "ACORD_140"),
        "total_payroll": ("ACORD_131", "ACORD_160", "ACORD_186"),
        "total_revenue": ("ACORD_131", "ACORD_160", "ACORD_186"),
        "num_employees": ("ACORD_131",),
        "retro_date": ("ACORD_131",),
    }
    count = 0
    for fact, forms in expected.items():
        mapping = ps.fact_to_form_fields(fact)
        for fid in forms:
            for box in mapping[fid]:
                assert fact in arq._canonical_keys_for(box), (fact, fid, box)
        count += sum(len(mapping[fid]) for fid in forms)
    assert arq._canonical_keys_for("BusinessInformation_AnnualGrossReceiptsAmount_A") >= {"total_revenue"}
    assert arq._canonical_keys_for("GeneralLiability_ClaimsMade_RetroactiveDate_A") >= {"retro_date"}
    assert count >= 38


def test_a_field_name_means_the_same_facts_on_every_form():
    """`facts_stamping_box` is keyed by name: no box name may map to different
    facts on two forms that print it (else the index needs the form id)."""
    per_form = {}
    for fact in _real_facts():
        for fid, fields in ps.fact_to_form_fields(fact).items():
            for box in fields:
                per_form.setdefault((fid, box), set()).add(fact)
    by_name = {}
    for (fid, box), facts in per_form.items():
        by_name.setdefault(box, {})[fid] = frozenset(facts)
    for box, forms in by_name.items():
        printing = [fid for fid, sch in ps._all_form_schemas().items() if box in sch]
        assert len({forms.get(fid, frozenset()) for fid in printing}) == 1, box
        assert ps.facts_stamping_box(box) == next(iter(forms.values())), box


def test_pseudo_keys_and_secondary_rows_are_never_facts_of_a_box():
    assert not any(k.startswith("_") for box in ("NamedInsured_MailingAddress_LineOne_A",
                                                  "Form_CompletionDate_A")
                   for k in ps.facts_stamping_box(box))
    assert ps.facts_stamping_box("NamedInsured_FullName_B") == frozenset()
    assert ps.facts_stamping_box("") == frozenset() and ps.facts_stamping_box(None) == frozenset()


def test_fact_to_form_fields_is_unchanged_and_hands_out_fresh_objects():
    """Sample of the old answers, which the one-pass index must keep: the
    producer's address is never the named insured's mailing address, a measured
    fact never maps to a checkbox, and an unknown key maps to nothing."""
    mailing = ps.fact_to_form_fields("mailing_address")
    assert sorted(mailing) == ["ACORD_125", "ACORD_130", "ACORD_25", "ACORD_28"]
    assert all(b.startswith("NamedInsured_") for fields in mailing.values() for b in fields)
    assert sum(len(v) for v in mailing.values()) == 20
    for fid, fields in ps.fact_to_form_fields("gl_aggregate").items():
        assert not any(ps._is_checkbox_field(fid, f) for f in fields)
    assert ps.fact_to_form_fields("no_such_fact") == {}
    a = ps.fact_to_form_fields("total_revenue")
    a["ACORD_131"] = ("tampered",)
    assert ps.fact_to_form_fields("total_revenue")["ACORD_131"] == (
        "BusinessInformation_AnnualGrossReceiptsAmount_A",)


def test_a_stub_reader_is_never_cached():
    """A test that swaps in a reader (every box fillable) must not leave its
    links behind for everything after it; the reverse view then answers
    nothing new rather than rebuilding for every box."""
    saved = dict(ps._FACT_LINKS_CACHE)
    try:
        ps._FACT_LINKS_CACHE.clear()
        with patch.object(ps, "_is_nonfillable_field", lambda _b: False):
            ps.fact_to_form_fields("total_revenue")
            assert "links" not in ps._FACT_LINKS_CACHE
            assert ps.facts_stamping_box(GROSS) == frozenset()
            assert "by_box" not in ps._FACT_LINKS_CACHE
        assert ps.facts_stamping_box(GROSS) == frozenset({"total_revenue"})
        assert "links" in ps._FACT_LINKS_CACHE and "by_box" in ps._FACT_LINKS_CACHE
    finally:
        if "links" not in ps._FACT_LINKS_CACHE:
            ps._FACT_LINKS_CACHE.update(saved)


def _generated(facts, form_ids, schema_of=None):
    out = {}
    for fid in form_ids:
        sch = _schema((schema_of or {}).get(fid, fid))
        m, c = ps.map_facts_to_form(dict(facts), sch, fid, "", allow_llm=False)
        out[fid] = {"schema": sch, "field_state": m, "mapped": dict(m), "confidence": c}
    return out


def _answer(row, field, value):
    async def _get(_sid):
        return copy.deepcopy(row)

    async def _upd(_sid, payload, **_kw):
        row.update(payload)

    with patch("repositories.session_repository.get_processing_session", _get), \
         patch("repositories.session_repository.upd_processing_session", _upd):
        return asyncio.run(arq.apply_producer_answer_to_session("s1", field, value))


GROSS = "BusinessInformation_AnnualGrossReceiptsAmount_A"
COPIES = ("ACORD_131", "ACORD_131__excess")


def _row131():
    facts = {"applicant_name": "Choice Electric LLC", "has_umbrella": True}
    gen = _generated(facts, COPIES, schema_of={"ACORD_131__excess": "ACORD_131"})
    return {"facts": facts, "flags": {}, "generated_forms": gen}


def _printed(row, fid, box=GROSS):
    fr = row["generated_forms"][fid]
    return fr["field_state"].get(box), fr["confidence"].get(box)


def test_the_17_oct_sequence_both_131_copies_follow_every_answer():
    """Blank at generation -> revenue answered 3,000,000 after forms -> the box
    prints it as the producer's -> answered 6,000,000 -> both copies print it."""
    row = _row131()
    for fid in COPIES:
        assert not _printed(row, fid)[0]
    ok, _ = _answer(row, "total_revenue", "3000000")
    assert ok
    for fid in COPIES:
        assert _printed(row, fid) == ("$3,000,000", "producer")
    ok, _ = _answer(row, "total_revenue", "6000000")
    assert ok
    for fid in COPIES:
        assert _printed(row, fid) == ("$6,000,000", "producer")


def test_the_old_map_froze_the_131_on_the_second_answer():
    """The defect, reproduced with the stamper's links hidden from the re-stamp."""
    row = _row131()
    with patch.object(ps, "facts_stamping_box", lambda _f: frozenset()):
        _answer(row, "total_revenue", "3000000")
        _answer(row, "total_revenue", "6000000")
    for fid in COPIES:
        assert _printed(row, fid) == ("$3,000,000", "producer")


def test_another_facts_typed_box_stands_when_revenue_is_answered():
    """A person's value on a box that is NOT the answered fact's own stands."""
    row = _row131()
    payroll = "BusinessInformation_TotalPayrollAmount_A"
    for fid in COPIES:
        fr = row["generated_forms"][fid]
        fr["field_state"][payroll] = "$1,700,000"
        fr["confidence"][payroll] = "producer"
    _answer(row, "total_revenue", "6000000")
    for fid in COPIES:
        assert _printed(row, fid, payroll) == ("$1,700,000", "producer")
        assert _printed(row, fid)[0] == "$6,000,000"


def test_a_derived_box_a_person_typed_stands():
    """ACORD 125: answering the effective date moves the expiration the engine
    derives - not one a person typed."""
    facts = {"applicant_name": "Choice Electric LLC", "effective_date": "01/01/2027",
             "expiration_date": "01/01/2028"}
    row = {"facts": facts, "flags": {}, "generated_forms": _generated(facts, ("ACORD_125",))}
    fr = row["generated_forms"]["ACORD_125"]
    fr["field_state"]["Policy_ExpirationDate_A"] = "03/03/2028"
    fr["confidence"]["Policy_ExpirationDate_A"] = "producer"
    _answer(row, "effective_date", "02/01/2027")
    fr = row["generated_forms"]["ACORD_125"]
    assert fr["field_state"]["Policy_ExpirationDate_A"] == "03/03/2028"


def test_an_edit_of_the_mailing_address_reaches_the_130_and_a_typed_130_box_stands():
    before = {"applicant_name": "Choice Electric LLC",
              "mailing_address": "100 Main St, Denver, CO 80202"}
    gen = _generated(before, ("ACORD_125", "ACORD_130"))
    city = "NamedInsured_MailingAddress_CityName_A"
    line1 = "NamedInsured_MailingAddress_LineOne_A"
    assert gen["ACORD_130"]["field_state"][city] == "Denver"
    gen["ACORD_130"]["field_state"][line1] = "PO Box 9"           # a person typed it
    gen["ACORD_130"]["confidence"][line1] = "producer"
    after = dict(before, mailing_address={"value": "2080 W 60th Ave, Aurora, CO 80011",
                                          "source": "producer"})
    moved = arq.propagate_fact_edits(gen, "ACORD_125", before, after, {"mailing_address"})
    assert "ACORD_130" in moved
    assert gen["ACORD_130"]["field_state"][city] == "Aurora"
    assert gen["ACORD_130"]["confidence"][city] == "producer"
    assert gen["ACORD_130"]["field_state"][line1] == "PO Box 9"


def test_reopening_the_answer_clears_the_131_box_it_wrote():
    row = _row131()
    _answer(row, "total_revenue", "6000000")
    touched = arq._clear_canonical_from_forms(row["generated_forms"], "total_revenue", row["facts"])
    assert set(touched) == set(COPIES)
    for fid in COPIES:
        assert not _printed(row, fid)[0]


def test_the_questionnaire_backfill_reaches_the_newly_visible_boxes():
    """A fact known with its boxes still blank is late-stamped through the
    form's own door (the questionnaire's "known fact, blank box" pass)."""
    known = {"applicant_name": "Choice Electric LLC", "total_revenue": "3000000"}
    gen = _generated({"applicant_name": "Choice Electric LLC"}, ("ACORD_131",))
    assert not gen["ACORD_131"]["field_state"].get(GROSS)
    present, changed = arq._backfill_and_resolve_present(gen, known)
    assert changed and "total_revenue" in present
    assert gen["ACORD_131"]["field_state"][GROSS] in ("3000000", "$3,000,000", "3,000,000")


# ═══════════════════════════════════════════════════════════════════════════
# PART 2(b) - the warning says what disagrees with what
# ═══════════════════════════════════════════════════════════════════════════

def _mm(fact, label, fid, stamped, expected):
    return {"fact_key": fact, "label": label, "form_id": fid, "field": "x",
            "stamped": stamped, "expected": expected}


REV, PAY = "Gross Sales / Annual Revenue", "Total Annual Payroll"


def test_the_17_oct_check_reads_forms_against_the_submission():
    check = {"ok": False, "checked": 9, "mismatches": [
        _mm("total_revenue", REV, "ACORD_131", "$3,000,000", "6000000"),
        _mm("total_revenue", REV, "ACORD_131__excess", "$3,000,000", "6000000"),
        _mm("total_payroll", PAY, "ACORD_131", "$1,700,000", "2626500"),
        _mm("total_payroll", PAY, "ACORD_131__excess", "$1,700,000", "2626500"),
    ]}
    issues = stamp_mismatch_issues(check)
    assert [i["message"] for i in issues] == [
        "Gross Sales / Annual Revenue: ACORD 131 and ACORD 131 (Excess) print $3,000,000, "
        "but the submission says $6,000,000. Confirm the figure so every form prints the same.",
        "Total Annual Payroll: ACORD 131 and ACORD 131 (Excess) print $1,700,000, "
        "but the submission says $2,626,500. Confirm the figure so every form prints the same.",
    ]
    assert all(i["code"] == "underwriting_stamp_mismatch" and i["type"] == "soft_warning"
               and i["forms"] == ["ACORD_131", "ACORD_131__excess"] for i in issues)


def test_forms_printing_different_figures_are_named_figure_by_figure():
    check = {"ok": False, "mismatches": [
        _mm("total_revenue", REV, "ACORD_160", "2500000", "6000000"),
        _mm("total_revenue", REV, "ACORD_131", "$3,000,000", "6000000"),
        _mm("total_revenue", REV, "ACORD_186", "3000000.00", "6000000"),
    ]}
    (issue,) = stamp_mismatch_issues(check)
    assert issue["message"] == (
        "Gross Sales / Annual Revenue: ACORD 131 and ACORD 186 print $3,000,000 and "
        "ACORD 160 prints $2,500,000, but the submission says $6,000,000. "
        "Confirm the figure so every form prints the same.")
    assert issue["forms"] == ["ACORD_131", "ACORD_160", "ACORD_186"]


def test_a_count_is_printed_as_a_count_and_one_form_reads_singular():
    check = {"ok": False, "mismatches": [
        _mm("num_employees", "Employee Count", "ACORD_125", "1200", "22")]}
    (issue,) = stamp_mismatch_issues(check)
    assert issue["message"] == ("Employee Count: ACORD 125 prints 1,200, but the submission "
                                "says 22. Confirm the figure so every form prints the same.")


def test_a_copy_with_its_own_figure_is_named():
    check = {"ok": False, "mismatches": [
        _mm("total_revenue", REV, "ACORD_131", "$3,000,000", "6000000"),
        _mm("total_revenue", REV, "ACORD_131__excess", "$3,000,000", "5000000")]}
    (issue,) = stamp_mismatch_issues(check)
    assert "but the submission says $6,000,000 for ACORD 131 and $5,000,000 for " \
           "ACORD 131 (Excess)." in issue["message"]


@pytest.mark.parametrize("check", [None, {}, {"ok": True, "mismatches": []},
                                   {"ok": False, "mismatches": []},
                                   {"ok": False, "mismatches": [None, "junk"]}])
def test_nothing_to_say(check):
    assert stamp_mismatch_issues(check) == []


def test_the_words_carry_no_em_dash_and_never_the_old_sentence():
    check = {"ok": False, "mismatches": [
        _mm("total_revenue", None, "ACORD_131", "$3,000,000", "6000000")]}
    (issue,) = stamp_mismatch_issues(check)
    assert "—" not in issue["message"] and "inconsistently" not in issue["message"]
    assert issue["message"].startswith("total_revenue: ACORD 131 prints $3,000,000")


# ═══════════════════════════════════════════════════════════════════════════
# PART 2(c) - a company row whose company is not named carries no AI figure
# ═══════════════════════════════════════════════════════════════════════════

S131 = _schema("ACORD_131")
TWO_BUILDINGS = {
    "applicant_name": "Choice Electric LLC", "has_umbrella": True,
    "property_locations": [
        {"location_number": "1", "building_number": "1", "address_line1": "2080 W 60th Ave",
         "address_city": "Denver", "address_state": "CO", "address_zip": "80221"},
        {"location_number": "1", "building_number": "2", "address_line1": "2080 W 60th Ave",
         "address_city": "Denver", "address_state": "CO", "address_zip": "80221"}]}


def _fill131(gap, form_id="ACORD_131"):
    report = []
    m, c = ps.map_facts_to_form(dict(TWO_BUILDINGS), S131, form_id, "",
                                pre_filled_gpt={"filled_values": dict(gap)},
                                guard_report=report, allow_llm=False)
    return m, {r.get("field"): r.get("reason") for r in report}


def test_the_ai_figures_in_an_unnamed_company_row_are_refused():
    """The 17 Oct row B: building 2's location printed by the stamper, the
    company name blank, the narrative's revenue and the WC payroll from the AI."""
    for form_id in COPIES:
        m, why = _fill131({"BusinessInformation_AnnualGrossReceiptsAmount_B": "$3,200,000",
                           "BusinessInformation_TotalPayrollAmount_B": "$2,626,500",
                           "BusinessInformation_EmployeeCount_B": "23"}, form_id)
        # Z41 (25 Oct 2026): one premises with two buildings is ONE location on
        # the 131 - row B, naming no company of its own, folds into row A.
        assert not m.get("CommercialStructure_PhysicalAddress_LineOne_B")
        for f in ("BusinessInformation_AnnualGrossReceiptsAmount_B",
                  "BusinessInformation_TotalPayrollAmount_B"):
            assert not m.get(f), (form_id, f)
            assert why.get(f) == "ROW_HAS_NO_IDENTITY", (form_id, f)
        # the employee count of row B is an owned blank already (another rule)
        assert not m.get("BusinessInformation_EmployeeCount_B")


def test_a_named_company_keeps_its_figures_and_row_a_is_never_judged():
    m, why = _fill131({"CommercialStructure_Location_FullName_B": "Choice Electric Services Inc",
                       "BusinessInformation_AnnualGrossReceiptsAmount_B": "$800,000",
                       "BusinessInformation_TotalPayrollAmount_B": "$300,000",
                       "BusinessInformation_OperationsDescription_A": "Commercial electrical contractor"})
    assert m["BusinessInformation_AnnualGrossReceiptsAmount_B"] == "$800,000"
    assert m["BusinessInformation_TotalPayrollAmount_B"] == "$300,000"
    assert m["BusinessInformation_OperationsDescription_A"]
    assert "ROW_HAS_NO_IDENTITY" not in why.values()


def test_only_ai_values_are_judged():
    """A person's or a rule's value is never in the gap-fill set, so never refused."""
    mapped = {"CommercialStructure_Location_ProducerIdentifier_B": "1",      # the stamper's
              "CommercialStructure_PhysicalAddress_LineOne_B": "2080 W 60th Ave",  # building 2
              "BusinessInformation_TotalPayrollAmount_B": "$300,000",
              "BusinessInformation_AnnualGrossReceiptsAmount_B": "$800,000"}
    ai = {"BusinessInformation_AnnualGrossReceiptsAmount_B"}
    out = ps._unanchored_schedule_row_fields(mapped, S131, ai, form_id="ACORD_131")
    assert out == {"BusinessInformation_AnnualGrossReceiptsAmount_B"}
    assert ps._unanchored_schedule_row_fields(mapped, S131, set(), form_id="ACORD_131") == set()
    # without a form id the old net is exactly as before: the location anchors it
    assert ps._unanchored_schedule_row_fields(mapped, S131, ai) == set()
    # and a row with neither a name nor a location was already refused by it
    bare = {k: v for k, v in mapped.items() if k.startswith("BusinessInformation_")}
    assert ps._unanchored_schedule_row_fields(bare, S131, ai) == ai


def test_the_governed_columns_are_the_131_company_table_only():
    """Measured on all 17 schemas - a new binding that widens it must be seen."""
    governed = {fid: ps._company_row_columns(fid) for fid in ps._all_form_schemas()}
    governed = {fid: cols for fid, cols in governed.items() if cols}
    assert governed == {"ACORD_131": {
        "BusinessInformation_OperationsDescription": "CommercialStructure_Location_FullName",
        "BusinessInformation_TotalPayrollAmount": "CommercialStructure_Location_FullName",
        "BusinessInformation_AnnualGrossReceiptsAmount": "CommercialStructure_Location_FullName",
        "BusinessInformation_EmployeeCount": "CommercialStructure_Location_FullName",
    }}


def test_the_126_products_row_without_a_product_keeps_no_ai_figure():
    """ACORD 126 products row A ($3,200,000 from the narrative on 17 Oct): the
    existing door (`_product_rows_to_refuse`) refuses it when the row names no
    product; a named product or service keeps its figure."""
    s = _schema("ACORD_126")
    facts = {"applicant_name": "Choice Electric LLC", "has_general_liability": True}
    sales = "ProductAndCompletedOperations_AnnualGrossSalesAmount_A"
    m, _c = ps.map_facts_to_form(dict(facts), s, "ACORD_126", "",
                                 pre_filled_gpt={"filled_values": {sales: "$3,200,000"}}, allow_llm=False)
    assert not m.get(sales)
    m, _c = ps.map_facts_to_form(dict(facts), s, "ACORD_126", "", pre_filled_gpt={"filled_values": {
        sales: "$3,200,000", "ProductAndCompletedOperations_ProductName_A": "Electrical panels"}},
        allow_llm=False)
    assert m.get(sales) == "$3,200,000"


def test_no_fixture_row_is_touched():
    """No stored fixture holds a 131 company row B..F."""
    pat = re.compile(r'"BusinessInformation_(OperationsDescription|TotalPayrollAmount|'
                     r'AnnualGrossReceiptsAmount|EmployeeCount)_[B-F]"')
    fixtures = os.path.join(HERE, "fixtures")
    for name in os.listdir(fixtures):
        if name.endswith(".json"):
            with open(os.path.join(fixtures, name), encoding="utf-8") as fh:
                assert not pat.search(fh.read()), name
