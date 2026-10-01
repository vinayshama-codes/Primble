"""The owner's final localhost run, part 1 (30 Sep 2026, session 17351800) and
the fixes it asked for. Each test names the defect it pins.

  1. The viewer painted page 1 under page 2's boxes (render race).
  2. ACORD 125 CONTACT TYPE printed the contact's name; BLD # printed the suite.
  3. The review said 'Found "84-1234567"' for a FEIN the AI invented.
  4. Internal field names were back in the review and on the cover page.
  5. The AI tagged the Common Declarations entries with the inland marine
     policy number, so the GL line looked like policy 6C7 (question 4 read
     "Liability 6C7-40-02---26" and the page 4 GL column went blank).
  6. The owner's asks: pre-form key details are actions, a smaller save
     button, no "Unsaved" toolbar line, cover page shows real gaps only.
"""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.extraction_service as es                             # noqa: E402
import services.field_qa as fq                                       # noqa: E402
import services.needs_attention as na                                # noqa: E402
import services.pdf_service as ps                                    # noqa: E402

FRONTEND = BACKEND.parent / "frontend" / "src"
VIEWER = FRONTEND / "components" / "form" / "PDFJsViewer.jsx"
SCHEMAS = BACKEND / "forms_schemas"
S125 = json.loads((SCHEMAS / "ACORD_125_schema.json").read_text())
S127 = json.loads((SCHEMAS / "ACORD_127_schema.json").read_text())


def _src(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ── 5. A dec entry's policy-number TAG must be printed with its value ────────

_DEC_TEXT = (
    "[Document page 1]\nCommon Declarations\nAccount Number: 0482854\nCoverages and Premium\n"
    "Section Coverage Premium\n2 Liability $3,954.00\n4 Inland Marine $300.00\n"
    "The company affording coverage is designated by the name in the declarations for each section.\n"
    "[Document page 2]\nCOMMERCIAL INLAND MARINE DECLARATIONS\nPolicy Number 6C7-40-02---26\n"
    "Employers Mutual Casualty Company\nTotal Inland Marine Premium $ 300.00\n"
    "[Document page 3]\nGeneral Liability Declarations\nEMC Property & Casualty Company\n"
    "Policy: BBC7263 - 26\nTotal Estimated Policy Premium $3,954.00\n"
)


def _entry(label, value, section, pn, lob):
    return {"label": label, "value": value, "section": section, "owner": "policy",
            "policy_number": pn, "line_of_business": lob}


def _live_entries():
    return [
        _entry("Section 2 Liability", "$3,954.00", "Coverages and Premium", "6C7-40-02---26", "Liability"),
        _entry("Section 4 Inland Marine", "$300.00", "Coverages and Premium", "6C7-40-02---26", "Inland Marine"),
        _entry("Policy Number", "6C7-40-02---26", "COMMERCIAL INLAND MARINE DECLARATIONS",
               "6C7-40-02---26", "Inland Marine"),
        _entry("Total Inland Marine Premium", "$ 300.00", "COMMERCIAL INLAND MARINE DECLARATIONS",
               "6C7-40-02---26", "Inland Marine"),
        _entry("Policy", "BBC7263 - 26", "General Liability Declarations", "BBC7263 - 26", "General Liability"),
        _entry("Total Estimated Policy Premium", "$3,954.00", "General Liability Declarations",
               "BBC7263 - 26", "General Liability"),
    ]


def _live_lines():
    return [
        {"line": "Liability", "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY",
         "policy_number": "6C7-40-02---26", "premium": "$3,954.00", "naic": None},
        {"line": "Inland Marine", "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY",
         "policy_number": "6C7-40-02---26", "premium": "$300.00", "naic": None},
        {"line": "Commercial General Liability", "carrier": "EMC Property & Casualty Company",
         "policy_number": "BBC7263 - 26", "premium": "$3,954.00", "naic": None},
    ]


def test_a_tag_no_page_supports_is_dropped_and_the_entry_survives():
    tags = {e["label"]: e["policy_number"] for e in es._verify_dec_entries(_live_entries(), _DEC_TEXT)}
    # Page 1 prints NO policy number: its Liability line is not policy 6C7.
    assert "Section 2 Liability" in tags and tags["Section 2 Liability"] is None
    # ...while its inland marine line is: page 2 prints both 6C7 and $300.00.
    assert tags["Section 4 Inland Marine"] == "6C7-40-02---26"
    assert tags["Policy"] == "BBC7263 - 26"
    assert tags["Total Estimated Policy Premium"] == "BBC7263 - 26"


def test_a_number_printed_nowhere_gives_no_opinion():
    e = [_entry("Premium", "$3,954.00", "Coverages and Premium", "ZZ-99-12345", "Liability")]
    assert es._verify_dec_entries(e, _DEC_TEXT)[0]["policy_number"] == "ZZ-99-12345"


def test_a_document_without_page_markers_is_unchanged():
    text = _DEC_TEXT.replace("[Document page 1]\n", "").replace("[Document page 2]\n", "") \
                    .replace("[Document page 3]\n", "")
    tags = {e["label"]: e["policy_number"] for e in es._verify_dec_entries(_live_entries(), text)}
    assert tags["Section 2 Liability"] == "6C7-40-02---26"


def test_the_live_misread_is_now_self_contradictory_and_repaired():
    old = {"coverage_lines": _live_lines(), "dec_page_entries": _live_entries()}
    assert not es._coverage_lines_are_self_contradictory(old["coverage_lines"], old["dec_page_entries"], old)
    verified = es._verify_dec_entries(_live_entries(), _DEC_TEXT)
    mf = {"coverage_lines": _live_lines(), "dec_page_entries": verified}
    assert es._coverage_lines_are_self_contradictory(mf["coverage_lines"], verified, mf)
    es._repair_coverage_lines_from_entries(mf)
    rows = {r["line"]: r for r in mf["coverage_lines"]}
    assert rows["Liability"]["policy_number"] == "BBC7263 - 26"
    assert rows["Liability"]["carrier"] == "EMC Property & Casualty Company"     # one contract, one carrier
    assert rows["Inland Marine"]["policy_number"] == "6C7-40-02---26"
    assert rows["Commercial General Liability"]["policy_number"] == "BBC7263 - 26"


def test_one_contract_printed_two_ways_is_one_candidate():
    same = es._contract_matcher()
    assert es._one_contract_printing({"BBC7263", "BBC7263 - 26"}, same) == "BBC7263 - 26"
    assert es._one_contract_printing({"BBC7263 - 26", "6C7-40-02---26"}, same) is None
    assert es._one_contract_printing(set(), same) is None


# ── 2. A TYPE or NUMBER box never repeats its neighbour's name or address ────

def test_contact_type_repeating_the_contact_name_is_blanked():
    mapped = {"NamedInsured_Contact_ContactDescription_A": "Erin Royal",
              "NamedInsured_Contact_FullName_A": "Erin Royal"}
    out = ps._blank_neighbour_copies(mapped, S125, {"NamedInsured_Contact_ContactDescription_A"})
    assert out == ["NamedInsured_Contact_ContactDescription_A"]
    assert mapped["NamedInsured_Contact_ContactDescription_A"] is None
    assert mapped["NamedInsured_Contact_FullName_A"] == "Erin Royal"


def test_building_number_repeating_the_suite_is_blanked():
    mapped = {"CommercialStructure_Building_ProducerIdentifier_A": "# D13",
              "CommercialStructure_PhysicalAddress_LineTwo_A": "# D13"}
    assert ps._blank_neighbour_copies(mapped, S125, {"CommercialStructure_Building_ProducerIdentifier_A"}) \
        == ["CommercialStructure_Building_ProducerIdentifier_A"]


def test_a_real_contact_type_and_a_deterministic_value_are_untouched():
    mapped = {"NamedInsured_Contact_ContactDescription_A": "Accounting",
              "NamedInsured_Contact_FullName_A": "Erin Royal"}
    assert ps._blank_neighbour_copies(mapped, S125, {"NamedInsured_Contact_ContactDescription_A"}) == []
    mapped = {"NamedInsured_Contact_ContactDescription_A": "Erin Royal",
              "NamedInsured_Contact_FullName_A": "Erin Royal"}
    assert ps._blank_neighbour_copies(mapped, S125, set()) == []              # not AI: never judged
    assert mapped["NamedInsured_Contact_ContactDescription_A"] == "Erin Royal"


def test_a_short_value_and_another_row_prove_nothing():
    mapped = {"CommercialStructure_Building_ProducerIdentifier_A": "1",
              "CommercialStructure_PhysicalAddress_LineTwo_A": "1"}
    assert ps._blank_neighbour_copies(mapped, S125, {"CommercialStructure_Building_ProducerIdentifier_A"}) == []
    mapped = {"CommercialStructure_Building_ProducerIdentifier_B": "# D13",
              "CommercialStructure_PhysicalAddress_LineTwo_A": "# D13"}
    assert ps._blank_neighbour_copies(mapped, S125, {"CommercialStructure_Building_ProducerIdentifier_B"}) == []


def test_the_guard_runs_inside_the_post_fill_guards_and_logs_as_a_drop():
    src = _src(BACKEND / "services" / "pdf_service.py")
    guards = src[src.index("def _enforce_post_fill_guards"):src.index("def _blank_neighbour_copies")]
    assert "_blank_neighbour_copies(mapped, schema, gpt_filled_set or set())" in guards
    # the replay never restores a guard verdict it can read in the log
    assert "gpt_fill DROP_NEIGHBOUR_COPY: field=%s" in src


# ── 3. "Found" is said only of a value the documents or our records hold ─────

def test_an_invented_identifier_is_never_quoted():
    for in_docs in (False, None):
        r = na.held_back_reason(S125, "NamedInsured_TaxIdentifier_A", "84-1234567", {}, None, in_docs)
        assert "84-1234567" not in r and "Found" not in r, (in_docs, r)
    r = na.held_back_reason(S125, "NamedInsured_SICCode_A", "1521", {}, None, None)
    assert "1521" not in r and "Found" not in r


def test_a_value_not_in_the_documents_says_so():
    r = na.held_back_reason(S125, "CommercialStructure_InstallationRepairWorkPercent_A", "100%", {}, None, False)
    assert r == na._NOT_IN_DOCUMENTS


def test_a_value_our_records_hold_is_named_for_what_it_is():
    facts = {"gl_class_codes": {"value": ["91580"]}}
    r = na.held_back_reason(S125, "NamedInsured_SICCode_A", "91580", facts, None, None)
    # Named for what it is, never quoted (Michelle's item 9, 1 Oct): a quoted
    # GL code under the SIC box read as "we found your SIC code and hid it".
    assert "GL class codes" in r and "91580" not in r and "Found" not in r


def test_the_agencys_own_email_is_named_as_such():
    facts = {"producer_contact_email": {"value": "agent@agency.example"}}
    r = na.held_back_reason(S125, "NamedInsured_Contact_PrimaryEmailAddress_A",
                            "agent@agency.example", facts, None, False)
    assert "your agency's contact e-mail" in r


def test_a_schedule_is_named_in_the_producers_words():
    facts = {"auto_vin_schedule": {"value": [{"vehicle_type": "PRIV PASSENGER"}]}}
    r = na.held_back_reason(S127, "Vehicle_ModifiedEquipmentDescription_A", "PRIV PASSENGER", facts, None, None)
    assert "auto vin schedule" not in r
    assert na._humanize_fact("auto_vin_schedule") == "vehicle schedule"


def test_a_count_is_not_a_yes_no_answer():
    r = na.held_back_reason(S127, "AccidentConviction_ViolationYearCount_A", "1", {}, None, None)
    assert "Yes/No" not in r


def test_the_guard_report_records_whether_a_value_is_in_the_documents():
    src = _src(BACKEND / "services" / "pdf_service.py")
    block = src[src.index("_hay = None\n            for _f in _blanked:"):]
    block = block[:block.index("guard_report.append(_row)")]
    assert '_row["in_documents"] = _needle in _hay' in block and "len(_needle) >= 4" in block


def test_a_quotation_inside_a_tooltip_does_not_end_the_label():
    assert na.box_label(S127, "AccidentConviction_ViolationYearCount_A").endswith("moving violation\" question")
    assert na._first_sentence("A... b. C") == "A... b."
    assert na._first_sentence('Say "x. y" now. Next') == 'Say "x. y" now.'


# ── 3b. The premises choices are one row each ───────────────────────────────

def test_owner_tenant_and_city_limits_are_named_as_choices():
    fr = {"mapped": {"CommercialStructure_PhysicalAddress_LineOne_A": "4800 Dahlia St"},
          "confidence": {"CommercialStructure_InsuredInterest_OwnerIndicator_A": "missing_required",
                         "CommercialStructure_RiskLocation_InsideCityLimitsIndicator_A": "missing_required"},
          "schema": S125}
    rows = {r["field"]: r for r in na.needs_attention(fr, {}, "ACORD_125")}
    owner = rows["CommercialStructure_InsuredInterest_OwnerIndicator_A"]
    assert owner["label"].startswith("Named insured's interest in the building (owner, tenant or other)")
    assert owner["what_to_do"] == "Tick the one that applies."
    inside = rows["CommercialStructure_RiskLocation_InsideCityLimitsIndicator_A"]
    assert inside["label"].startswith("Building inside or outside the city limits")


# ── 4. Unanswered high-impact questions: in the list, with the form's words ──

def _q_form():
    q = "CommercialStructure_Question_ABBCode_A"
    assert na.is_question_box(S125, q)
    return q, {"mapped": {"NamedInsured_FullName_A": "Orbin Contracting LLC",
                          "CommercialStructure_PhysicalAddress_LineOne_A": "4800 Dahlia St"},
               "confidence": {q: "low_confidence"}, "schema": S125}


def test_an_unanswered_high_impact_question_is_listed_as_missing():
    q, fr = _q_form()
    if not __import__("services.field_mapping_integrity", fromlist=["x"]).is_high_impact_field(q, S125[q].get("tu")):
        pytest.skip("not a high-impact question on this template")
    rows = {r["field"]: r for r in na.needs_attention(fr, {}, "ACORD_125")}
    assert rows[q]["status"] == na.STATUS_MISSING
    assert rows[q]["reason"] == "An underwriting question your documents do not answer."
    assert rows[q]["label"] == na.box_label(S125, q)


def test_a_refused_answer_is_not_also_unanswered():
    q, fr = _q_form()
    fr["guard_blanks"] = [{"field": q, "removed_value": "N", "kind": "unanswered"}]
    rows = [r for r in na.needs_attention(fr, {}, "ACORD_125") if r["field"] == q]
    assert len(rows) <= 1 and all(r["status"] == na.STATUS_HELD_BACK for r in rows)


def test_field_qa_never_calls_a_refused_box_unanswered_and_uses_form_words():
    fr = {"mapped": {"NamedInsured_FullName_A": "Orbin Contracting LLC"},
          "confidence": {"AdditionalInterest_FullName_A": "low_confidence",
                         "CommercialPolicy_ApplicantOwnLeaseOperateDronesExplanation_A": "low_confidence"},
          "schema": S125,
          "guard_blanks": [{"field": "AdditionalInterest_FullName_A", "removed_value": "ORBIN CONTRACTING LLC"}]}
    qa = fq.run_field_qa({"ACORD_125": fr}, merged_facts={}, confirmations={}, flags={})
    na_rows = [r for r in qa["results"] if r["reason_code"] == "not_answered"]
    assert not any(r["field"] == "AdditionalInterest_FullName_A" for r in na_rows)
    for r in na_rows:
        assert "_" not in r["field_label"] and "Explanation " not in r["message"]
        if r["field"].endswith("Explanation_A"):
            assert not r["high_impact"]                 # an explanation follows its question


def test_the_review_row_names_boxes_as_the_form_prints_them():
    qa = {"results": [
        {"form_id": "ACORD_127", "field": "AdditionalInterest_FullName_A", "reason_code": "not_answered",
         "high_impact": True, "is_question": False, "field_label": "Additional interest's full name",
         "message": 'ACORD 127: "Additional interest\'s full name" is a high-impact box ...'},
        {"form_id": "ACORD_127", "field": "Vehicle_Question_XYZCode_A", "reason_code": "not_answered",
         "high_impact": True, "is_question": True, "field_label": "Any vehicles leased to others?",
         "message": "..."},
    ]}
    rows = fq.to_recommendation_rows(qa, {"forms": [{"form_id": "ACORD_127", "ok": True, "rows": []}]})
    msg = " ".join(r["message"] for r in rows)
    assert "Additional interest's full name" in msg and "Any vehicles leased to others?" in msg
    assert "AdditionalInterest FullName" not in msg
    assert "high-impact boxes" in msg                    # not all of them are questions


# ── 6. The owner's asks ──────────────────────────────────────────────────────

def test_key_details_carry_their_fix():
    kd = __import__("services.sqs_service", fromlist=["x"]).key_details({}, {})
    items = {it["label"]: it for it in kd["missing_items"]}
    assert [it["label"] for it in kd["missing_items"]] == kd["missing"]          # same list, same order
    pair = items.get("NAICS or SIC industry code")
    if pair:
        assert pair["resolution"] == {"mode": "field", "facts": ["naics_code", "sic_code"]}
    for it in kd["missing_items"]:
        assert it["resolution"] is None or it["resolution"]["mode"] in ("field", "schedule")


def test_the_cover_page_lists_real_gaps_not_the_producers_to_dos():
    from routes.download_routes import _split_open_recs
    recs = [{"rec_id": "fieldqa_attn_ACORD_125_missing", "message": "ACORD 125 - Missing (12): ..."},
            {"rec_id": "fieldqa_attn_ACORD_125_ai_held_back", "message": "held back"},
            {"rec_id": "fieldqa_attn_ACORD_137_CO_verify", "message": "verify"},
            {"rec_id": "rec_loss_x", "message": "No loss history", "score_impact": 8}]
    hard, soft = _split_open_recs(recs)
    assert hard == [] and soft == ["ACORD 125 - Missing (12): ...", "No loss history (up to +8 pts)"]
    assert na.is_producer_todo_row("fieldqa_attn_ACORD_125_ai_held_back")
    assert not na.is_producer_todo_row("fieldqa_attn_ACORD_125_missing")


# ── 1. The picture and its boxes show one page ──────────────────────────────

def test_only_the_newest_render_paints_and_it_paints_off_screen():
    src = _src(VIEWER)
    effect = src[src.index("// Render page to canvas."):src.index("// Rebuild overlay when state changes")]
    assert "const seq = ++renderSeqRef.current;" in effect
    assert effect.count("if (seq !== renderSeqRef.current) return;") == 2        # after getPage AND after paint
    assert "const off = _blankCanvas(vp);" in effect and "_showRenderedPage(off, pdfDoc, pageNum);" in effect
    assert "canvasContext: ctx" not in effect                                  # never the visible canvas


def test_the_overlay_is_built_for_the_page_the_canvas_shows():
    src = _src(VIEWER)
    assert "shownPageRef.current = { doc, page };" in src
    rebuild = src[src.index("const rebuildOverlay"):src.index("const buildOverlay")]
    assert "const page = shownPageRef.current.page;" in rebuild
    build = src[src.index("const buildOverlay"):src.index("// ── Unsaved-edit tracking")]
    # Orbin item 14 (1 Oct 2026 - the TEST changed): a box the client's signature
    # was painted into is skipped too; the page is still the one shown.
    assert "fieldsRef.current.filter(f => f.page === page - 1 && !f.painted)" in build
    assert "pageNum - 1" not in build


def test_the_save_and_sign_redraws_use_the_page_the_reader_is_on_now():
    src = _src(VIEWER)
    for start, end in (("const handleApplySignature", "const handleSignClick"),
                       ("const _loadPdfInBackground", "const goPage")):
        body = src[src.index(start):src.index(end)]
        assert "const seq" in body and "= ++renderSeqRef.current;" in body
        assert "pageNumRef.current" in body and "getPage(pageNum)" not in body
        assert "seq === renderSeqRef.current && pg === pageNumRef.current" in body


def test_double_click_puts_the_cursor_at_the_end_not_a_selection():
    src = _src(VIEWER)
    focus = src[src.index("const want = pendingFocusRef.current;"):]
    focus = focus[:focus.index("};\n")]
    assert "target.setSelectionRange(end, end);" in focus
    assert "!(wantField && wantField.yes_no)" in focus                          # Y/N keeps select-on-focus
    assert "target.select()" not in focus


# ── Retest findings (30 Sep, session 8739a72a) ───────────────────────────────

def test_answering_no_known_losses_ticks_the_forms_own_box():
    from services import arq_service as a
    assert a._canonical_keys_for("LossHistory_NoPriorLossesIndicator_A") == {"loss_history_no_prior_losses_indicator"}
    facts = {"loss_history_no_prior_losses_indicator": {
        "value": "No - no claims or losses in the past 5 years", "source": "producer", "confidence": "filled"}}
    gen = {"ACORD_125": {"schema": S125, "field_state": {}, "confidence": {}}}
    assert a._restamp_canonical_into_forms(gen, "loss_history_no_prior_losses_indicator", facts,
                                           provenance="producer") == ["ACORD_125"]
    fr = gen["ACORD_125"]
    assert fr["field_state"]["LossHistory_NoPriorLossesIndicator_A"] == "Yes"
    assert fr["confidence"]["LossHistory_NoPriorLossesIndicator_A"] == "producer"
    # ...and the list no longer asks for it (nor for the loss years it needed)
    rows = na.needs_attention(dict(fr, mapped={}), facts, "ACORD_125")
    assert not [r for r in rows if r["field"].startswith("LossHistory_")]


def test_a_policy_is_named_by_the_row_carrying_its_full_premium():
    rows = [{"line": "Automobile", "policy_number": "6E7-40-02---26", "premium": "$2,991.00",
             "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY"},
            {"line": "COVERED AUTOS LIABILITY", "policy_number": "6E7-40-02---26", "premium": "$ 1,496.00",
             "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY"}]
    mf = {"coverage_lines": rows}
    es._build_scoped_fact_store(mf, [])
    auto = [r for r in mf.get(es.LINE_RECORDS_KEY) or [] if r.get("line") == "auto"]
    assert auto and auto[0]["line_printed"] == "Automobile"
    # an ACORD line name still wins over any premium
    rows.append({"line": "Commercial Auto", "policy_number": "6E7-40-02---26", "premium": None})
    mf = {"coverage_lines": rows}
    es._build_scoped_fact_store(mf, [])
    auto = [r for r in mf.get(es.LINE_RECORDS_KEY) or [] if r.get("line") == "auto"]
    assert auto[0]["line_printed"] == "Commercial Auto"
    assert es._line_row_premium("$ 1,496.00") == 1496.0 and es._line_row_premium("None") is None


def test_every_review_row_uses_the_forms_words():
    fr = {"mapped": {"Producer_AuthorizedRepresentative_FullName_A": "Vinay Sharma"},
          "field_state": {"Producer_AuthorizedRepresentative_FullName_A": "Vinay Sharma"},
          "confidence": {"Producer_AuthorizedRepresentative_FullName_A": "filled"}, "schema": S125}
    qa = fq.run_field_qa({"ACORD_125": fr}, merged_facts={"producer_contact_name": {"value": "Vinay Sharmaa"}},
                         confirmations={}, flags={})
    for r in qa["results"]:
        assert "AuthorizedRepresentative" not in r["message"] and "_" not in r["field_label"], r["message"]
    src = _src(BACKEND / "services" / "field_qa.py")
    assert '"field_label": _humanize_field(field),' not in src


def test_key_details_say_who_normally_answers_them():
    from services.sqs_service import key_details
    items = {it["label"]: it for it in key_details({}, {})["missing_items"]}
    assert items["FEIN / Tax ID"]["audience"] == "client"
    assert items["NAICS or SIC industry code"]["audience"] == "agency"      # client PART 13
    modal = _src(FRONTEND / "components" / "form" / "AcordModal.jsx")
    assert "Send to Client asks the client." in modal and "the client is not asked for it." in modal
