"""The owner's live run of 12 Oct 2026 (package `18ecbfa8`, Choice Electric, Cyber added after forms).

Owner: "on the left SQS panel there is a resolved section - make it dropdown type so it remains
hidden and when the user wants to see it they can click and open it." The editor's Cross-Form
Validation panel listed its resolved items open under a green "RESOLVED (n)" heading; it is
now a closed dropdown, like every other section of that panel, closed again on a form switch.
"""
from __future__ import annotations

from pathlib import Path

_MODAL = Path(__file__).resolve().parents[2] / "frontend" / "src" / "components" / "form" / "AcordModal.jsx"


def _resolved_block() -> str:
    src = _MODAL.read_text(encoding="utf-8")
    start = src.index("{crossFormGhosts.length > 0 && (")
    return src[start:src.index("</CollapsibleSection>", start) + len("</CollapsibleSection>")]


def test_the_editor_resolved_list_is_a_closed_dropdown():
    block = _resolved_block()
    assert "<CollapsibleSection resetKey={activeFormId} title={`Resolved (${crossFormGhosts.length})`}" in block
    # closed until clicked: the section's default, never opened by the call
    assert "defaultOpen" not in block
    # the same rows, with their own controls, inside it
    assert "crossFormGhosts.map((g, gi) => row(g, `resolved-${gi}`" in block
    # the heading keeps its green colour and the panel's small heading size
    assert 'headerColor="#059669"' in block and "titleSize={9.5}" in block


# ══════════════════════════════════════════════════════════════════════════════
# The five problems the owner's run `18ecbfa8` showed (owner: "fix these 5
# problems and do not touch any other fixed things").
# ══════════════════════════════════════════════════════════════════════════════
import asyncio as _asyncio
import json as _json
import os as _os
import shutil as _shutil
import subprocess as _subprocess

import pytest

import services.audit_service as au
import services.needs_attention as na
import services.pdf_service as ps
import services.policy_lines as pl
import services.scoped_evidence as se
import services.session_documents as sd
import services.sqs_service as sqs

_BACKEND = Path(__file__).resolve().parents[1]
_FRONT = _BACKEND.parent / "frontend" / "src"


def _schema(fid):
    return _json.loads((_BACKEND / "forms_schemas" / f"{fid}_schema.json").read_text(encoding="utf-8"))


def _doc(name, rows=None, text=""):
    return {"filename": name, "doc_type": "dec_page", "text": text,
            "facts": {"coverage_lines": rows or []}, "flags": {}}


# ── 1. An umbrella / excess retention must be printed as one ──────────────────
_BOX = "ExcessUmbrella_Umbrella_DeductibleOrRetentionAmount_A"
# The Choice Electric Excess declarations, as OCR reads them: the UMBRELLA's
# limits "000 omitted" - 5,000 is $5,000,000, and the Excess prints no retention.
_EXCESS_TEXT = ("FOLLOWING FORM EXCESS LIABILITY DECLARATIONS\n"
                "POLICY LIMITS (000 OMITTED) COVERAGE COMPANY\n"
                "Policy Period: 5,000 EACH OCCURRENCE UMBRELLA LIABILITY AMERISURE\n"
                "From:01/01/2025 5,000 PERS/ADV INJURY MUTUAL INS\n"
                "To:01/01/2026 5,000 GENERAL AGGREGATE URANCE COM\n")
_EXCESS_ROWS = [{"line": "Excess (Following Form) Liability", "premium": "$10,692",
                 "carrier": "Travelers Property Casualty Company of America"}]
_UMB_ROWS = [{"line": "Commercial Liability Umbrella", "premium": "$17,082",
              "carrier": "Amerisure Mutual Insurance Company"}]
_PKG_ROWS = [{"line": "Commercial Property Coverage Part", "premium": "$6,275"}]
_PKG_TEXT = "COVERAGE: BUILDING\nLIMIT COINSURANCE DEDUCTIBLE\n$798,556 80% $5,000\n"
_EXCESS_LAYER = {"index": 1, "own_documents": ["excess.pdf"], "other_layer_documents": ["umbrella.pdf"]}


def _tower(umbrella_text="COMMERCIAL LIABILITY UMBRELLA EACH OCCURRENCE $5,000,000", package=True):
    docs = [_doc("excess.pdf", _EXCESS_ROWS, _EXCESS_TEXT), _doc("umbrella.pdf", _UMB_ROWS, umbrella_text)]
    return docs + ([_doc("package.pdf", _PKG_ROWS, _PKG_TEXT)] if package else [])


def test_the_excess_layers_limit_in_thousands_is_not_its_retention():
    facts = se.attach_documents({"_umbrella_layer": dict(_EXCESS_LAYER)}, _tower())
    out = se.retention_values({_BOX: "5,000"}, {}, facts, "ACORD_131__excess", {_BOX})
    # $5,000 IS printed as a deductible - in the package, another policy
    assert out == {_BOX: se.REASON_OTHER_POLICY}
    facts = se.attach_documents({"_umbrella_layer": dict(_EXCESS_LAYER)}, _tower(package=False))
    out = se.retention_values({_BOX: "5,000"}, {}, facts, "ACORD_131__excess", {_BOX})
    assert out == {_BOX: se.REASON_RETENTION_NOT_STATED}
    assert "retention or deductible" in se.held_back_text(se.REASON_RETENTION_NOT_STATED)
    # the guard's one call runs the rule
    facts = se.attach_documents({"_umbrella_layer": dict(_EXCESS_LAYER)}, _tower())
    assert se.out_of_scope_values({_BOX: "5,000"}, {}, facts, "ACORD_131__excess", {_BOX}) \
        == {_BOX: se.REASON_OTHER_POLICY}


@pytest.mark.parametrize("printed, value", [
    ("SELF-INSURED RETENTION: $10,000 EACH OCCURRENCE", "$10,000"),
    ("Retained Limit $25,000", "25,000"),
    ("EACH OCCURRENCE $5,000,000   $0 SIR", "0"),
    ("Self Insured Retention\n$10,000", "10,000"),
    ("$10,000 Self-Insured Retention applies", "10000"),
])
def test_a_retention_the_umbrella_prints_as_one_is_kept(printed, value):
    facts = se.attach_documents({}, _tower(umbrella_text=printed))
    assert se.retention_values({_BOX: value}, {}, facts, "ACORD_131", {_BOX}) == {}
    assert se.retention_values({_BOX: value}, {}, facts, "ACORD_25", {_BOX}) == {}


def test_only_an_ai_umbrella_retention_amount_is_judged():
    facts = se.attach_documents({}, _tower())
    # not an AI value, not an amount, not the umbrella retention box: untouched
    assert se.retention_values({_BOX: "5,000"}, {}, facts, "ACORD_131", set()) == {}
    assert se.retention_values({_BOX: "Included"}, {}, facts, "ACORD_131", {_BOX}) == {}
    ebl = "ExcessUmbrella_EmployeeBenefits_DeductibleOrRetentionAmount_A"
    assert se.retention_values({ebl: "5,000"}, {}, facts, "ACORD_131", {ebl}) == {}
    # no documents: nothing is judged
    assert se.retention_values({_BOX: "5,000"}, {}, {}, "ACORD_131", {_BOX}) == {}


# ── 2. Page-1 premiums Brent keeps blank are not "Missing" ────────────────────
_S125 = _schema("ACORD_125")
_PAIRS = ps.lob_premium_box_pairs(_S125)
_AUTO_TICK = next(t for t, p in _PAIRS.items() if "Vehicle" in p or "Auto" in p)
_TOTAL = "Policy_Payment_EstimatedTotalAmount_A"


def _form125(state):
    return {"schema": _S125, "field_state": dict(state), "mapped": dict(state),
            "confidence": {}, "client_filled_fields": []}


def _premium_todos(facts):
    rows = na.needs_attention(_form125({_AUTO_TICK: "Yes"}), facts, "ACORD_125")
    return {r["field"] for r in rows if r.get("producer_todo")}


def test_a_renewals_page_one_premiums_are_not_listed_as_missing():
    # Brent 8 Oct: a dec renewal's expiring premiums never print on page 1
    assert _premium_todos({"premium_is_current_policy": True}) == set()
    # a quote / anything without the mark keeps the 30 Sep to-do, unchanged
    assert _premium_todos({}) == {_PAIRS[_AUTO_TICK], _TOTAL}
    # a premium a PERSON entered lifts the rule: the to-dos come back
    typed = {"premium_is_current_policy": True,
             "total_policy_premium": {"value": "$58,000", "source": "producer"}}
    assert _premium_todos(typed) == {_PAIRS[_AUTO_TICK], _TOTAL}


# ── 4. A "New document" choice is what the NEW document says ─────────────────
def _stored(field, value):
    return {"field_state": {field: value}, "mapped": {field: value},
            "confidence": {field: "ai_verified"}, "client_filled_fields": []}


def _hay(text):
    return na.document_haystack(text)


def test_a_choice_must_be_printed_in_the_new_document():
    f = "CommercialStructure_SubLocationDescription_A"
    stored = _stored(f, "Prem. #: 001 Bldg #: 001")
    new = {f: "Prem #: 001 Bldg #: 001"}
    cyber = _hay("Chubb Cyber Enterprise Risk Management Policy Declarations Item 1. Named Insured")
    # only a dot differs - not a different answer
    plan = sd.plan_form_fill("ACORD_140", stored, new, {f: "ai_verified"}, {}, new_text=None)
    assert plan["suggestions"] == []
    # a real difference the new document does NOT print - not "the new document says"
    stored2 = _stored(f, "Main warehouse")
    plan = sd.plan_form_fill("ACORD_140", stored2, {f: "North shop building"}, {f: "ai_verified"},
                             {}, new_text=cyber)
    assert plan["suggestions"] == []
    # ...and one it does print is offered, as before
    doc = _hay("Location: North shop building, 4800 Washington St")
    plan = sd.plan_form_fill("ACORD_140", stored2, {f: "North shop building"}, {f: "ai_verified"},
                             {}, documents=["new.pdf"], new_text=doc)
    assert [s["suggested"] for s in plan["suggestions"]] == ["North shop building"]
    # a blank box is still filled (unchanged)
    plan = sd.plan_form_fill("ACORD_140", {"field_state": {}, "mapped": {}, "confidence": {}},
                             {f: "North shop building"}, {f: "ai_verified"}, {}, new_text=cyber)
    assert f in plan["fills"]


def test_the_fill_passes_the_new_documents_text():
    import inspect
    body = inspect.getsource(sd._fill_once)
    assert "new_text = document_haystack(new_docs)" in body
    assert "documents=names, new_text=new_text)" in body


# ── 5a. A written date is a date ──────────────────────────────────────────────
def test_march_1_2022_is_not_called_not_a_date():
    field = "ExcessUmbrella_CurrentRetroactiveDate_A"
    s131 = _schema("ACORD_131")
    text, _found = na.held_back(s131, field, "March 1, 2022", {}, None, True)
    assert "not a date" not in text and "March 1, 2022" in text
    for d in ("1 March 2022", "Mar. 1, 2022", "03/01/2022", "2022-03-01", "March 1st, 2022"):
        assert na._DATE_SHAPE.search(d), d
    for not_a_date in ("Annual", "See schedule", "March", "2022"):
        assert not na._DATE_SHAPE.search(not_a_date), not_a_date
    text, _found = na.held_back(s131, field, "See schedule", {}, None, True)
    assert "which is not a date" in text


# ── 5b. A blocking box says which row ─────────────────────────────────────────
def test_a_blocking_box_names_its_row():
    s140 = _schema("ACORD_140")
    a, b = "CommercialStructure_BuiltYear_A", "CommercialStructure_BuiltYear_B"
    fr = {"schema": s140, "mapped": {}, "field_state": {}, "confidence": {
        a: "missing_required_gate", b: "missing_required_gate"}}
    import services.field_qa as fq
    msgs = {}
    for item in (fq.run_field_qa({"ACORD_140": fr}, {}) or {}).get("results", []):
        if item.get("field") in (a, b) and item.get("reason_code") == "missing_required_gate":
            msgs[item["field"]] = item["message"]
    assert set(msgs) == {a, b}
    assert "(row 2) is required for this section" in msgs[b]
    assert "(row" not in msgs[a]
    assert msgs[a] != msgs[b]


# ── 5c. The building card names only what is missing ─────────────────────────
@pytest.mark.parametrize("facts, words", [
    ({}, "street address, occupancy, construction type, and building or BPP value"),
    ({"construction_type": "Frame", "property_building_value": "$798,556"}, "street address and occupancy"),
    ({"locations": ["1 Main St"], "construction_type": "Frame", "property_bpp_value": "$73,008"}, "occupancy"),
])
def test_the_building_card_asks_only_for_what_is_missing(facts, words):
    assert sqs._words_list([w for w in ("a", "b", "c")]) == "a, b, and c"
    src = Path(sqs.__file__).read_text(encoding="utf-8")
    assert '"message": "Required: " + _words_list(' in src
    parts = [("street address", bool(facts.get("locations"))), ("occupancy", bool(facts.get("occupancy_type"))),
             ("construction type", bool(facts.get("construction_type"))),
             ("building or BPP value", bool(facts.get("property_building_value") or facts.get("property_bpp_value")))]
    assert sqs._words_list([w for w, ok in parts if not ok]) == words


def test_an_open_cards_words_follow_the_live_card():
    rows = [{"rec_id": "rec_min_cope", "action": None, "producer_answer": None, "score_impact": 0,
             "message": "Required: street address, occupancy, construction type, and building or BPP value"},
            {"rec_id": "rec_dismissed", "action": "dismissed", "producer_answer": None, "message": "old"},
            {"rec_id": "rec_answered", "action": None, "producer_answer": "Office", "message": "old"}]
    live = {"rec_min_cope", "rec_dismissed", "rec_answered"}
    msgs = {"rec_min_cope": "Required: street address and occupancy", "rec_dismissed": "new",
            "rec_answered": "new"}
    plan = au.plan_card_sync(rows, live, {}, msgs)
    # only the open, unanswered card takes the new words
    assert plan["reword"] == ["rec_min_cope"]
    # rows read without their words (older callers) are never reworded
    assert au.plan_card_sync([{k: v for k, v in rows[0].items() if k != "message"}], live, {}, msgs)["reword"] == []
    assert au.live_card_messages([{"recommendations": [
        {"rec_id": "rec_min_cope", "message": "Required: occupancy"}, "a plain string card"]}]) \
        == {"rec_min_cope": "Required: occupancy"}
    import inspect
    src = inspect.getsource(au._reword_open_cards)
    assert "producer_answer IS NULL" in src and "action IS NULL" in src


# ── 5d. A policy named after one of its sections ─────────────────────────────
def test_the_cyber_policy_is_not_named_after_its_first_insuring_agreement():
    assert pl._line_label({"line": "cyber", "line_printed": "Cyber Incident Response Team"}) == "Cyber"
    # every name the owner confirmed on 12 Oct stays as printed
    for fam, name in [("auto", "Commercial Auto"), ("crime", "Crime and Fidelity Coverage Part"),
                      ("employee_benefits", "Employee Benefit Liability Coverage Part"),
                      ("epli", "Employment Practices Liability Coverage Part"),
                      ("general_liab", "Commercial General Liability Coverage Part"),
                      ("inland_marine", "Commercial Inland Marine Coverage Part"),
                      ("property", "Commercial Property Coverage Part"),
                      ("umbrella", "Commercial Liability Umbrella"),
                      ("umbrella", "Excess (Following Form) Liability"),
                      ("workers_comp", "Workers' Compensation and Employers' Liability"),
                      # names that start any other way are left alone
                      ("auto", "Covered Autos Liability"), ("auto", "Hired and Non-Owned Auto Liability"),
                      ("crime", "Comprehensive Dishonesty, Disappearance and Destruction"),
                      ("pollution", "Contractors Pollution Liability"), ("cyber", "Cyber Liability"),
                      ("inland_marine", "Inland Marine (Contractors Equipment)")]:
        assert pl._line_label({"line": fam, "line_printed": name}) == name, name


# ── 3. Example text is a hint, never data (frontend) ──────────────────────────
def _node(tmp_path, body):
    if _shutil.which("node") is None:
        pytest.skip("node is not installed")
    script = tmp_path / "check.mjs"
    script.write_text(f"import * as S from {_json.dumps((_FRONT / 'utils' / 'scheduleImport.js').as_uri())};\n"
                      + body + "\n", encoding="utf-8")
    run = _subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return _json.loads(run.stdout)


_COLS = [{"key": "address_line1", "label": "Street address", "required": True, "placeholder": "789 Commerce Dr"},
         {"key": "address_city", "label": "City", "placeholder": "Houston"},
         {"key": "address_state", "label": "State", "type": "state", "placeholder": "TX"},
         {"key": "year_built", "label": "Year built", "type": "year", "placeholder": "1998"},
         {"key": "county", "label": "County"}]


def test_the_template_and_the_upload_never_carry_the_example_building(tmp_path):
    out = _node(tmp_path, f"""
const cols = {_json.dumps(_COLS)};
const header = cols.map((c) => c.label);
const example = cols.map((c) => c.placeholder || '');
const mine = ['12 Oak St', 'Denver', 'CO', '1999', ''];
const edited = ['789 Commerce Dr', 'Houston', 'TX', '2004', ''];
console.log(JSON.stringify({{
  tpl: S.templateCsv(cols),
  rows: S.rowsFromMatrix([header, example, mine, edited], cols).rows.map((r) => r.address_line1 + '|' + r.year_built),
  hint: S.exampleHint(cols[0]), none: S.exampleHint(cols[4]),
  ex: S.isTemplateExampleRow({{address_line1: 'e.g. 789 Commerce Dr', address_city: 'Houston', address_state: 'tx', year_built: '1998'}}, cols),
}}));
""")
    assert out["tpl"] == "Street address,City,State,Year built,County\n"     # names only
    # the untouched example is skipped; a row the person changed is theirs
    assert out["rows"] == ["12 Oak St|1999", "789 Commerce Dr|2004"]
    assert out["hint"] == "e.g. 789 Commerce Dr" and out["none"] == ""
    assert out["ex"] is True


def test_apply_names_what_the_rows_still_miss(tmp_path):
    out = _node(tmp_path, f"""
const cols = {_json.dumps(_COLS)};
const rows = [{{address_line1: '', year_built: '1998'}}, {{address_line1: '', address_city: 'Denver'}}, {{}}, {{address_line1: '1 Main St'}}];
console.log(JSON.stringify([S.missingRequiredSummary(rows, cols), S.missingRequiredSummary([rows[0]], cols),
                            S.missingRequiredSummary([rows[3]], cols)]));
""")
    assert out == ["Street address on rows 1 and 2", "Street address on row 1", ""]


def test_the_table_shows_hints_and_the_window_says_what_is_left():
    table = (_FRONT / "components" / "arq" / "ScheduleTable.jsx").read_text(encoding="utf-8")
    assert "placeholder={exampleHint(c)}" in table and 'className="schedule-cell"' in table
    css = (_FRONT / "App.css").read_text(encoding="utf-8")
    assert ".schedule-cell::placeholder" in css and "font-style: italic" in css
    modal = (_FRONT / "components" / "form" / "ResolutionModal.jsx").read_text(encoding="utf-8")
    # 13 Oct 2026 (owner): what the table still misses is named BEFORE the save,
    # beside a "Save progress" button - no longer as a note after it with an
    # "Apply the fix" button over an unfinished fix. The TEST was outdated by the
    # owner's new rule, not the code wrong.
    assert "table: [missingRequiredSummary(rows, schedule.columns || [])," in modal   # + row_needs (13 Oct)
    assert "Still missing:</b> {progressGap}" in modal
    i = modal.index("const applySchedule = async")
    body = modal[i:modal.index("const addForm = async", i)]
    assert "setNoteSettleHere(true)" not in body and "Still missing" not in body
