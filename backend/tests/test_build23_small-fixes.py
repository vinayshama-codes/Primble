"""Build 23 (22 Oct 2026), lane SMALL - four small fixes (25sepChanges.md Z32).

1. "Needs Verification" documents count. The Documents list's count, Brent's
   "Some documents require review" sentence and the pink rows read ONE rule
   (`utils/addDocuments.documentNeedsTypeReview`): every type the pill does not
   call "Highly Confident" or "Set by you". A counted row can always be cleared:
   "Confirm type" sends the type the row already shows (the type list never fires
   for the type it shows), and a confirmation never re-reads the document with
   the LLM (`extraction_pipeline.apply_document_action`).
2. A totals row ("Total", "Totals", "Grand total", "Subtotal", "Sum") in an
   imported sheet is not a row in any schedule table (`scheduleImport.
   isSummaryRow`), and the import message names it.
3. The gap fill's DIAG_RESPONSE (improving-ll.md C16) and the reject lines in
   the same call path log at DEBUG with field names and counts only - no
   document value at any level.
4. The PURGE_DEC_INDEX_AFTER_GENERATION comment no longer claims nothing reads
   the facts after generation (comment only, no behaviour change).

The adversarial cases come first in each part. JS runs the real modules under
node; Python drives the real functions with no database, network or LLM call.
"""
from __future__ import annotations

import ast
import asyncio
import copy
import json
import logging
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

_BACKEND = Path(__file__).resolve().parents[1]
_ROOT = _BACKEND.parent
_FRONT = _ROOT / "frontend" / "src"
_EM = ("—", "–")

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _node(tmp_path, body, name="check.mjs"):
    script = tmp_path / name
    script.write_text(
        f"import * as A from {json.dumps((_FRONT / 'utils' / 'addDocuments.js').as_uri())};\n"
        f"import * as S from {json.dumps((_FRONT / 'utils' / 'scheduleImport.js').as_uri())};\n"
        "import fs from 'node:fs';\n"
        "const out = (v) => console.log(JSON.stringify(v));\n"
        + body + "\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _src(rel):
    return (_FRONT / rel).read_text(encoding="utf-8")


def _defs():
    from services.schedule_capture import SCHEDULE_DEFS
    return json.loads(json.dumps(SCHEDULE_DEFS))


def _available_doc_types():
    """What the server sends as `available_doc_types` (form_routes)."""
    from services.extraction_service import ALLOWED_DOC_TYPES, DOC_TYPE_LABELS
    return [{"value": t, "label": DOC_TYPE_LABELS[t]} for t in ALLOWED_DOC_TYPES]


def run(coro):
    return asyncio.run(coro)


# ══════════════════════════════════════════════════════════════════════════════
# PART 1 - "Needs Verification" documents count, and can always be cleared
# ══════════════════════════════════════════════════════════════════════════════

@needs_node
def test_the_rule_adversarial_rows_first(tmp_path):
    rows = {
        # never counted
        "high": {"doc_type": "dec_page", "doc_type_confidence": "high"},
        "set_by_you_medium": {"doc_type": "dec_page", "doc_type_confidence": "medium",
                              "doc_type_overridden": True},
        "set_by_you_low": {"doc_type": "loss_run", "doc_type_confidence": "low",
                           "doc_type_overridden": True, "doc_type_source": "manual"},
        "excluded_medium": {"doc_type": "dec_page", "doc_type_confidence": "medium", "excluded": True},
        "excluded_unknown": {"doc_type": "unknown", "doc_type_confidence": "low", "excluded": True},
        "no_confidence": {"doc_type": "dec_page"},
        "number_confidence": {"doc_type": "dec_page", "doc_type_confidence": 3},
        "null": None,
        "string": "dec_page",
        # counted
        "medium": {"doc_type": "dec_page", "doc_type_confidence": "medium"},
        "low": {"doc_type": "loss_run", "doc_type_confidence": "low"},
        "odd": {"doc_type": "quote", "doc_type_confidence": "odd"},
        "filename_only": {"doc_type": "loss_run", "doc_type_source": "filename"},
        "unknown": {"doc_type": "unknown", "doc_type_confidence": "low"},
        "unknown_set_by_you": {"doc_type": "unknown", "doc_type_confidence": "high", "doc_type_overridden": True},
        "missing_type": {"doc_type_confidence": "high"},
        "empty_type": {"doc_type": "", "doc_type_confidence": "high"},
        "supporting_medium": {"doc_type": "narrative", "doc_type_confidence": "medium", "supporting_only": True},
    }
    o = _node(tmp_path, f"""
const rows = {json.dumps(rows)};
const res = {{}};
for (const [k, r] of Object.entries(rows)) res[k] = A.documentNeedsTypeReview(r);
out(res);
""")
    never = ["high", "set_by_you_medium", "set_by_you_low", "excluded_medium", "excluded_unknown",
             "no_confidence", "number_confidence", "null", "string"]
    counted = ["medium", "low", "odd", "filename_only", "unknown", "unknown_set_by_you",
               "missing_type", "empty_type", "supporting_medium"]
    assert [k for k in never if o[k]] == []
    assert [k for k in counted if not o[k]] == []


@needs_node
def test_the_count_and_the_type_pill_never_disagree(tmp_path):
    """Every combination: a counted row is one whose pill reads "Needs
    Verification" / "Unable to Classify" (or has no type, or a filename-only
    type); a "Highly Confident" / "Set by you" row with a type is never counted."""
    o = _node(tmp_path, """
const res = [];
for (const doc_type of ['dec_page', 'unknown', '', undefined]) {
  for (const doc_type_confidence of ['high', 'medium', 'low', 'odd', '', undefined, 3]) {
    for (const doc_type_overridden of [true, false]) {
      for (const doc_type_source of ['content', 'filename', 'manual', undefined]) {
        for (const excluded of [true, false]) {
          const row = {doc_type, doc_type_confidence, doc_type_overridden, doc_type_source, excluded};
          const tag = A.documentTypeTag(row);
          res.push({row, label: tag && tag.label, needs: A.documentNeedsTypeReview(row)});
        }
      }
    }
  }
}
out(res);
""")
    assert len(o) == 4 * 7 * 2 * 4 * 2
    for r in o:
        row, label, needs = r["row"], r["label"], r["needs"]
        typed = (row.get("doc_type") or "unknown") != "unknown"
        if row.get("excluded"):
            assert needs is False, r
        elif not typed:
            assert needs is True, r
        elif label in ("Set by you", "Highly Confident"):
            assert needs is (label == "Highly Confident" and row.get("doc_type_source") == "filename"), r
        elif label in ("Needs Verification", "Unable to Classify"):
            assert needs is True, r
        else:                                           # no pill: no confidence at all
            assert label is None and needs is (row.get("doc_type_source") == "filename"), r


@needs_node
def test_a_counted_document_can_always_be_cleared(tmp_path):
    """Confirm type is offered for every counted row with a type the server
    accepts; an Unknown row is cleared by a type or Exclude. Never offered for
    a type the server's list does not carry (it would be refused - BUG-05)."""
    types = _available_doc_types()
    o = _node(tmp_path, f"""
const types = {json.dumps(types)};
const res = {{}};
for (const t of types.map((x) => x.value)) {{
  for (const conf of ['high', 'medium', 'low']) {{
    const row = {{doc_type: t, doc_type_confidence: conf}};
    res[t + '|' + conf] = [A.documentNeedsTypeReview(row), A.canConfirmDocumentType(row, types)];
  }}
}}
res.legacy = A.canConfirmDocumentType({{doc_type: 'declarations', doc_type_confidence: 'medium'}}, types);
res.legacy_counted = A.documentNeedsTypeReview({{doc_type: 'declarations', doc_type_confidence: 'medium'}});
res.no_list = A.canConfirmDocumentType({{doc_type: 'dec_page', doc_type_confidence: 'medium'}}, null);
res.bad_list = A.canConfirmDocumentType({{doc_type: 'dec_page', doc_type_confidence: 'medium'}}, [null, 'dec_page', {{}}]);
res.excluded = A.canConfirmDocumentType({{doc_type: 'dec_page', doc_type_confidence: 'medium', excluded: true}}, types);
res.overridden = A.canConfirmDocumentType({{doc_type: 'dec_page', doc_type_confidence: 'medium', doc_type_overridden: true}}, types);
res.unknown_excluded = A.documentNeedsTypeReview({{doc_type: 'unknown', excluded: true}});
out(res);
""")
    for t in (x["value"] for x in types):
        for conf in ("high", "medium", "low"):
            needs, can = o[f"{t}|{conf}"]
            if t == "unknown":
                assert needs is True and can is False          # pick a type, or Exclude
            else:
                assert needs is (conf != "high") and can is needs, (t, conf)
    assert o["legacy"] is False and o["legacy_counted"] is True   # counted, never a refused button
    assert o["no_list"] is False and o["bad_list"] is False
    assert o["excluded"] is False and o["overridden"] is False
    assert o["unknown_excluded"] is False


def _medium_doc(doc_type="dec_page", text="DECLARATIONS PAGE ..."):
    return {
        "doc_id": "d1", "filename": "dec.pdf", "doc_type": doc_type,
        "doc_type_confidence": "medium", "doc_type_source": "content", "doc_type_overridden": False,
        "classification": {"doc_type": doc_type, "confidence": "medium", "source": "content"},
        "text": text, "facts": {"applicant_name": "Orbin Contracting LLC"}, "flags": {},
    }


@pytest.fixture
def no_llm(monkeypatch):
    """`extract_facts_long` replaced by a recorder: a confirmation must never
    reach it; a real change to a re-read type still does (no LLM either way)."""
    import services.extraction_pipeline as ep
    calls = []

    async def _fake(text, doc_type, low_confidence_tokens=None, **_kw):
        calls.append(doc_type)
        return {"facts": {"applicant_name": "RE-READ"}, "flags": {}}

    monkeypatch.setattr(ep, "extract_facts_long", _fake)
    return calls


@needs_node
def test_the_confirm_request_clears_the_row_end_to_end(tmp_path, no_llm):
    """The row the server builds before and after the button's own request
    (`set_type` with the type shown), read by the frontend's one rule."""
    import routes.form_routes as fr
    from services.extraction_pipeline import apply_document_action
    docs = [_medium_doc()]
    before = fr._doc_summary_entry(copy.deepcopy(docs[0]))
    target, prev = run(apply_document_action(docs, "d1", "set_type", "dec_page"))
    after = fr._doc_summary_entry(target)
    types = _available_doc_types()
    o = _node(tmp_path, f"""
const types = {json.dumps(types)};
const b = {json.dumps(before)}, a = {json.dumps(after)};
out({{before: [A.documentNeedsTypeReview(b), A.canConfirmDocumentType(b, types), A.documentTypeTag(b).label],
      after: [A.documentNeedsTypeReview(a), A.canConfirmDocumentType(a, types), A.documentTypeTag(a).label]}});
""")
    assert o["before"] == [True, True, "Needs Verification"]
    assert o["after"] == [False, False, "Set by you"]
    assert prev == "dec_page" and target["doc_type"] == "dec_page"
    assert no_llm == []


def test_a_confirmed_type_is_never_read_again_and_a_real_change_still_is(no_llm):
    from services.extraction_pipeline import apply_document_action
    for t in ("loss_run", "schedule"):                       # the re-read types
        docs = [_medium_doc(t, text="LOSS RUN REPORT valued 01/01/2026 ...")]
        facts_before = copy.deepcopy(docs[0]["facts"])
        target, _ = run(apply_document_action(docs, "d1", "set_type", t))
        assert target["facts"] == facts_before, t            # nothing re-read, nothing moved
        assert target["doc_type_overridden"] is True and target["doc_type_confidence"] == "high"
    assert no_llm == []
    # a CHANGE to a re-read type still re-reads (the §4.2 item 5 behaviour)
    docs = [_medium_doc("dec_page", text="LOSS RUN REPORT valued 01/01/2026 ...")]
    target, prev = run(apply_document_action(docs, "d1", "set_type", "loss_run"))
    assert prev == "dec_page" and no_llm == ["loss_run"]
    assert target["facts"] == {"applicant_name": "RE-READ"}
    # loss_run -> schedule is a change too
    docs = [_medium_doc("loss_run", text="SCHEDULE ...")]
    run(apply_document_action(docs, "d1", "set_type", "schedule"))
    assert no_llm == ["loss_run", "schedule"]


def test_both_layouts_read_the_one_rule_and_offer_the_confirm():
    modal = _src("components/form/AcordModal.jsx")
    rail = _src("components/form/review/ReviewRailLayout.jsx")
    lib = _src("utils/addDocuments.js")
    # one list, built in the modal, handed to the rail (no second copy there)
    assert "const docsNeedingReview = docSummary.filter(documentNeedsTypeReview);" in modal
    assert "docsNeedingReview={docsNeedingReview}" in modal
    assert "docsNeedingReview.filter(" not in rail and "docSummary.filter(" not in rail
    assert "const docsOpen = preFormLocked ? 0 : docsNeedingReview.length;" in rail
    assert "const openItemCount = (lockedReason(pkgGen.state) ? 0 : docsNeedingReview.length)" in modal
    for text in (modal, rail):
        # the pink row is the counted row; no inline copy of the rule is left
        assert "const needsReview = documentNeedsTypeReview(d);" in text
        assert 'conf === "low"' not in text and 'd.doc_type_confidence === "low"' not in text
        assert 'd.doc_type_source === "filename"' not in text
        # the button: only where the rule offers it, sending the type shown
        assert "canConfirmDocumentType(d, availableDocTypes) && (" in text
        assert '"set_type", docType, "confirm")' in text
        assert "{CONFIRM_TYPE_LABEL}" in text and "text={CONFIRM_TYPE_TIP}" in text
        assert 'reclassBusyBtn === "confirm"' in text
        assert "docsNeedingReview.length > 0" in text           # Brent's sentence, same list
    # locked while a run is live, like the other three controls
    assert rail.count("disabled={anyReclassBusy || !!docLockText}") == 4
    assert modal.count("disabled={anyReclassBusy || reclassLocked}") == 4
    # after forms the confirm dialog says what happens
    dlg = _src("components/form/review/DocumentChangeConfirm.jsx")
    assert 'pending.busyBtn === "confirm" ? "Confirm the type of"' in dlg
    for text in (lib, rail, dlg):
        assert not any(d in text for d in _EM)


@needs_node
def test_the_button_words_are_short_and_plain(tmp_path):
    o = _node(tmp_path, "out([A.CONFIRM_TYPE_LABEL, A.CONFIRM_TYPE_TIP]);")
    assert o[0] == "Confirm type"
    assert len(o[1]) <= 80 and not any(d in o[1] for d in _EM)


def test_a_confirm_sends_a_request_the_server_accepts():
    """The route refuses only an unknown action or a type outside
    ALLOWED_DOC_TYPES; the button sends set_type with an offered type."""
    src = (_BACKEND / "routes" / "form_routes.py").read_text(encoding="utf-8")
    assert 'if req.action not in ("set_type", "exclude", "include", "supporting_only"):' in src
    pipe = (_BACKEND / "services" / "extraction_pipeline.py").read_text(encoding="utf-8")
    assert "if nt in _REEXTRACT_DOC_TYPES and nt != prev_type and target.get(\"text\"):" in pipe


# ══════════════════════════════════════════════════════════════════════════════
# PART 2 - a totals row is not a row
# ══════════════════════════════════════════════════════════════════════════════

_SAMPLE_JS = """
const sample = (col) => {
  switch (col.type) {
    case 'year': return '2019';
    case 'date': return '01/02/2020';
    case 'state': return 'TX';
    case 'vin': return '1FTFW1ET5DFC10312';
    case 'currency': return '1000';
    case 'number': return '3';
    case 'percent': return '50';
    case 'code': return '91580';
    default: return 'Real ' + col.label;
  }
};
const NUMERIC = new Set(['currency', 'number', 'percent']);
"""


@needs_node
def test_real_rows_named_like_a_total_still_import(tmp_path):
    """Adversarial first: a driver named "Total", a location on "Sum Street", a
    claim that was a "total loss", a GL basis of "Total Cost"."""
    d = _defs()
    o = _node(tmp_path, f"""
const d = {json.dumps(d)};
const imp = (key, m) => S.rowsFromMatrix(m, d[key].columns);
const drvHead = ['Full Name', 'Date of Birth', 'License #', 'License State'];
const res = {{}};
let r = imp('auto_drivers', [drvHead, ['Total', '05/14/1985', 'D1234567', 'CO'], ['Total', '', 'D7654321', ''],
                             ['Total', '', '', 'CO'], ['Sum', '02/02/1990', '', ''], ['TOTAL:', '', '1234', '']]);
res.drivers = [r.rows.map((x) => x.name + '|' + x.dob + '|' + x.license_number + '|' + x.license_state), r.skippedTotals];
const locHead = ['Street address', 'Suite / unit', 'City', 'State', 'ZIP'];
r = imp('property_locations', [locHead, ['Sum Street', '', 'Houston', 'TX', '77001'], ['Sum Street', '', '', '', ''],
                                ['12 Sum Street', '', 'Austin', 'TX', '78701'], ['Total Plaza', '', '', '', '']]);
res.locations = [r.rows.map((x) => x.address_line1), r.skippedTotals];
r = imp('property_locations', [['Sum Street', '', 'Houston', 'TX', '77001']]);       // no header
res.locations_positional = [r.rows.map((x) => x.address_line1), r.usedHeader];
const lossHead = ['Date of loss', 'Line', 'What happened', 'Amount paid'];
r = imp('loss_history', [lossHead, ['03/15/2022', 'Auto', 'Total loss of vehicle', '25000'],
                         ['', '', 'Total loss', '18000'], ['', '', 'Total loss of the trailer', ''],
                         ['04/01/2023', '', 'Total', '9000']]);
res.losses = [r.rows.map((x) => x.description), r.skippedTotals];
const glHead = ['Location', 'Classification description', 'GL class code', 'Rating basis', 'Annual exposure'];
r = imp('gl_class_code_schedule', [glHead, ['', '', '', 'Total Cost', '350000']]);
res.gl = [r.rows.map((x) => x.premium_basis + '|' + x.exposure_amount), r.skippedTotals];
out(res);
""")
    assert o["drivers"] == [["Total|05/14/1985|D1234567|CO", "Total||D7654321|", "Total|||CO",
                             "Sum|02/02/1990||", "TOTAL:||1234|"], 0]
    assert o["locations"] == [["Sum Street", "Sum Street", "12 Sum Street", "Total Plaza"], 0]
    assert o["locations_positional"] == [["Sum Street"], False]
    assert o["losses"] == [["Total loss of vehicle", "Total loss", "Total loss of the trailer", "Total"], 0]
    assert o["gl"] == [["Total Cost|350000"], 0]


@needs_node
def test_a_totals_row_is_skipped_in_every_schedule_table(tmp_path):
    """Every live table, every label: header, one real row, the totals row
    (its label in the first column, amounts under the amount columns) - one row
    imports, the totals row is counted. The same without a header row."""
    d = _defs()
    labels = ["Total", "TOTAL", "Totals", "Total:", "Totals.", "Grand total", "GRAND TOTALS",
              "Grand Total:", "Subtotal", "Sub-total", "Sub total", "SUBTOTALS:", "Sum", "sum:"]
    o = _node(tmp_path, f"""
const d = {json.dumps(d)};
const labels = {json.dumps(labels)};
{_SAMPLE_JS}
const res = {{}};
for (const [key, def] of Object.entries(d)) {{
  const cols = def.columns;
  const head = cols.map((c) => c.label);
  const data = cols.map(sample);
  for (const label of labels) {{
    const totals = cols.map((c, i) => (i === 0 ? label : NUMERIC.has(c.type) ? '9999' : ''));
    const dashed = cols.map((c, i) => (i === 0 ? label : NUMERIC.has(c.type) ? '9999' : '-'));
    const r = S.rowsFromMatrix([head, data, totals, dashed], cols);
    const p = S.rowsFromMatrix([data, totals], cols);
    res[key + '|' + label] = {{n: r.rows.length, totals: r.skippedTotals, inside: r.skippedInside,
      kept: JSON.stringify(r.rows[0]) === JSON.stringify(Object.fromEntries(cols.map((c, i) => [c.key, S.tableCellValue(c, data[i], data, i)]))),
      pn: p.rows.length, ptotals: p.skippedTotals, pheader: p.usedHeader}};
  }}
}}
out(res);
""")
    assert len(o) == len(d) * len(labels)
    for k, v in o.items():
        assert v["n"] == 1 and v["totals"] == 2 and v["inside"] == 2 and v["kept"], (k, v)
        assert v["pn"] == 1 and v["ptotals"] == 1 and v["pheader"] is False, (k, v)


@needs_node
def test_the_label_in_an_unmapped_column_and_totals_at_the_top(tmp_path):
    d = _defs()
    o = _node(tmp_path, f"""
const loss = {json.dumps(d["loss_history"]["columns"])};
// "Claim #" maps to the Claim # column (25 Oct 2026)
const head = ['Claim #', 'Date of loss', 'What happened', 'Amount paid', 'Amount reserved'];
let r = S.rowsFromMatrix([head, ['C-1', '03/15/2022', 'Slip and fall', '8500', '2000'],
                          ['C-2', '05/01/2023', 'Hail', '25000', '0'], ['Total', '', '', '33500', '2000']], loss);
const a = [r.rows.length, r.skippedTotals, r.unmatched];
// a totals row printed right under the header
r = S.rowsFromMatrix([head, ['Total', '', '', '33500', '2000'], ['C-1', '03/15/2022', 'Slip and fall', '8500', '2000']], loss);
out([a, [r.rows.length, r.skippedTotals, r.headerRow]]);
""")
    assert o[0] == [2, 1, []]
    assert o[1] == [1, 1, 0]


@needs_node
def test_what_stays_a_row_is_pinned(tmp_path):
    """Conservative by design: a label that is not the row's first filled cell,
    a label with any naming value beside it, or a label with words after it
    imports as before - visible in the table, the person deletes it."""
    d = _defs()
    o = _node(tmp_path, f"""
const loss = {json.dumps(d["loss_history"]["columns"])};
const head = ['Claim #', 'Date of loss', 'Line', 'What happened', 'Amount paid'];
const r = S.rowsFromMatrix([head,
  ['C-1', '03/15/2022', 'GL', 'Slip', '8500'],
  ['5', 'Total', '', '', '8500'],                 // a count first
  ['Total', '', 'All lines', '', '8500'],         // names a line
  ['Total claims', '', '', '', '8500'],           // words after the label
  ['Policy total', '', '', '', '8500'],
  ['Total', '12/31/2024', '', '', '8500']], loss);  // dated
out([r.rows.length, r.skippedTotals]);
""")
    assert o == [6, 0]


@needs_node
def test_the_import_message_names_the_totals_rows(tmp_path):
    o = _node(tmp_path, """
out([S.skippedRowsText({skippedAbove: 0, skippedInside: 1, skippedTotals: 1}),
     S.skippedRowsText({skippedAbove: 2, skippedInside: 3, skippedTotals: 2}),
     S.skippedRowsText({skippedAbove: 1, skippedInside: 3}),
     S.skippedRowsText({skippedTotals: 2}),
     S.skippedRowsText({skippedInside: 1, skippedTotals: 5}),
     S.skippedRowsText({}), S.skippedRowsText()]);
""")
    assert o[0] == " Skipped 1 row of totals (Total, Subtotal or Sum)."
    assert o[1] == (" Skipped 2 rows above the column headings (titles or notes)."
                    " Skipped 1 row further down that repeat the headings or title a block."
                    " Skipped 2 rows of totals (Total, Subtotal or Sum).")
    # an older caller (no totals count) reads exactly as before
    assert o[2] == (" Skipped 1 row above the column headings (titles or notes)."
                    " Skipped 3 rows further down that repeat the headings or title a block.")
    assert o[3] == " Skipped 2 rows of totals (Total, Subtotal or Sum)."
    assert o[4] == " Skipped 5 rows of totals (Total, Subtotal or Sum)."
    assert o[5] == "" and o[6] == ""
    assert not any(d in t for t in o for d in _EM)


def _claims_xlsx(path):
    """Header, two claims, a SUM formula row and a Grand total row."""
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

    def s(ref, text):
        return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'

    def n(ref, num, formula=None):
        f = f"<f>{formula}</f>" if formula else ""
        return f'<c r="{ref}">{f}<v>{num}</v></c>'

    rows = [
        [s("A1", "Date of loss"), s("B1", "Line"), s("C1", "What happened"), s("D1", "Amount paid")],
        [s("A2", "03/15/2022"), s("B2", "GL"), s("C2", "Slip and fall"), n("D2", 8500)],
        [s("A3", "05/01/2023"), s("B3", "Property"), s("C3", "Total loss of the shed"), n("D3", 25000)],
        [s("A4", "Total"), n("D4", 33500, "SUM(D2:D3)")],
        [s("A5", "Grand Total:"), s("B5", "-"), n("D5", 33500, "D4")],
    ]
    data = "".join(f'<row r="{i + 1}">{"".join(cells)}</row>' for i, cells in enumerate(rows))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        z.writestr("xl/workbook.xml", f'<?xml version="1.0"?><workbook xmlns="{ns}"><sheets>'
                                      '<sheet name="Claims" sheetId="1"/></sheets></workbook>')
        z.writestr("xl/worksheets/sheet1.xml",
                   f'<?xml version="1.0"?><worksheet xmlns="{ns}"><sheetData>{data}</sheetData></worksheet>')
    return path


@needs_node
def test_a_real_workbook_and_csv_import_without_their_totals(tmp_path):
    d = _defs()
    xlsx = _claims_xlsx(tmp_path / "claims.xlsx")
    csv = ("Date of loss,Line,What happened,Amount paid\n03/15/2022,GL,Slip and fall,8500\n"
           "05/01/2023,Property,Total loss of the shed,25000\nTotal,,,33500\nSubtotal:,,,33500\n")
    o = _node(tmp_path, f"""
const loss = {json.dumps(d["loss_history"]["columns"])};
const b = fs.readFileSync({json.dumps(str(xlsx))}); b.name = 'claims.xlsx';
const x = await S.parseScheduleFile(b, loss);
const c = await S.parseScheduleFile({{name: 'claims.csv', text: async () => {json.dumps(csv)}}}, loss);
out([x.rows.map((r) => r.description + '|' + r.paid), S.skippedRowsText(x),
     c.rows.map((r) => r.description + '|' + r.paid), S.skippedRowsText(c)]);
""")
    assert o[0] == ["Slip and fall|8500", "Total loss of the shed|25000"]
    assert o[1] == " Skipped 2 rows of totals (Total, Subtotal or Sum)."
    assert o[2] == o[0]
    assert o[3] == " Skipped 2 rows of totals (Total, Subtotal or Sum)."


@needs_node
def test_a_totals_row_does_not_cost_a_real_row_its_place_under_the_cap(tmp_path):
    d = _defs()
    o = _node(tmp_path, f"""
const drv = {json.dumps(d["auto_drivers"]["columns"])};
const m = [['Full Name', 'Date of Birth']];
for (let i = 0; i < S.MAX_ROWS; i += 1) {{
  m.push(['Driver ' + i, '01/02/1980']);
  if (i === 10) m.push(['Subtotal', '']);
}}
const r = S.rowsFromMatrix(m, drv);
out([r.rows.length, r.rows[r.rows.length - 1].name, r.skippedTotals, S.MAX_ROWS]);
""")
    assert o[0] == o[3] and o[1] == f"Driver {o[3] - 1}" and o[2] == 1


def test_the_schedule_table_prints_the_totals_note():
    src = _src("components/arq/ScheduleTable.jsx")
    assert "skippedTotals = 0," in src
    assert "skippedRowsText({ skippedAbove, skippedInside, skippedTotals })" in src
    lib = _src("utils/scheduleImport.js")
    assert not any(d in lib for d in _EM)


# ══════════════════════════════════════════════════════════════════════════════
# PART 3 - the gap fill logs field names and counts, never a document value
# ══════════════════════════════════════════════════════════════════════════════

_SECRET = "ZZPII4471"


class _ScriptedClient:
    """Stands in for the OpenAI sync client: returns a fixed reply, never calls out."""

    def __init__(self, payload):
        self._payload = json.dumps(payload)
        self.calls = 0
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.calls += 1
        payload = self._payload

        class _R:
            choices = [type("C", (), {"message": type("M", (), {"content": payload})()})()]
            usage = None
        return _R()


def _form_gaps(form_id="ACORD_125"):
    import services.pdf_service as ps
    path = os.path.join(ps.FORMS_SCHEMAS_DIR, f"{form_id}_schema.json")
    with open(path, encoding="utf-8") as fh:
        schema = json.load(fh)
    facts = {"applicant_name": "Ridgeline Roofing"}
    _mapped, unmatched, _ = ps.compute_form_gaps(form_id, schema, facts)
    return unmatched, facts


def _plain_text_fields(unmatched, n):
    out = []
    for f in sorted(unmatched):
        meta = unmatched[f] or {}
        tu = str(meta.get("tu") or meta.get("tooltip") or "")
        if meta.get("ft") not in (None, "/Tx") or "Indicator" in f or "Question" in f or "Code" in f:
            continue
        if tu.startswith("Enter Y") or "response to the question" in tu:
            continue
        out.append(f)
        if len(out) == n:
            break
    return out


def _all_messages(caplog):
    return [(r.levelno, r.getMessage()) for r in caplog.records]


def test_no_document_value_reaches_any_log_at_any_level(monkeypatch, caplog):
    import services.pdf_service as ps
    unmatched, facts = _form_gaps()
    fields = _plain_text_fields(unmatched, 4)
    assert len(fields) == 4, fields
    wanted = {f: unmatched[f] for f in fields}
    payload = {
        "values": {
            fields[0]: f"{_SECRET} Holdings LLC, 4800 Prospect Ave",     # accepted
            fields[1]: f"[{_SECRET} placeholder]",                       # rejected (template bracket)
            fields[2]: "N/A",                                            # rejected (sentinel)
            "Zz_Invented_Field_A": f"{_SECRET} invented",                # a key no form has
        },
        "raw_text_sourced": [fields[0]],
        "question_grounding": {fields[0]: f"The insured is {_SECRET} Holdings LLC"},
    }
    client = _ScriptedClient(payload)
    monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: client)
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger=ps.logger.name)
    out = ps._fill_unmatched_with_gpt(wanted, facts, "ACORD_125",
                                      raw_text=f"Named insured: {_SECRET} Holdings LLC\n" * 5)
    assert client.calls >= 1
    assert out["filled_values"].get(fields[0], "").startswith(_SECRET)   # the fill itself is unchanged
    msgs = _all_messages(caplog)
    assert msgs, "no log records captured"
    leaked = [m for _lvl, m in msgs if _SECRET in m]
    assert leaked == [], leaked[:3]
    # the diagnostic is still there for whoever turns DEBUG on - names and counts
    diag = [(lvl, m) for lvl, m in msgs if "DIAG_RESPONSE" in m]
    assert diag and all(lvl == logging.DEBUG for lvl, _ in diag)
    assert fields[0] in diag[0][1] and "total_returned=4" in diag[0][1]
    rejects = [(lvl, m) for lvl, m in msgs if "REJECT_SAMPLE" in m or "NON_NULL_REJECTED" in m]
    assert rejects and all(lvl == logging.DEBUG for lvl, _ in rejects)
    assert any(fields[1] in m for _lvl, m in rejects)
    # nothing about the reply's content is said above DEBUG except counts
    loud = [m for lvl, m in msgs if lvl >= logging.INFO and ("DIAG_RESPONSE" in m or "REJECT" in m)]
    assert loud == []


def test_the_slot_dedup_line_names_fields_only(monkeypatch, caplog):
    """The dedup is OFF by default; when someone turns it on, the line it logs
    names the two fields, never the repeated value."""
    import services.pdf_service as ps
    monkeypatch.setattr(ps, "_ENABLE_SLOT_VALUE_DEDUP", True)
    unmatched, facts = _form_gaps()
    by_base = {}
    for f in unmatched:
        m = re.match(r"^(.*)_([A-N])$", f)
        if m:
            by_base.setdefault(m.group(1), []).append(f)
    groups = sorted((v for v in by_base.values() if len(v) >= 3), key=len, reverse=True)
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger=ps.logger.name)
    for group in groups:
        slots = sorted(group)[:3]
        client = _ScriptedClient({"values": {s: f"{_SECRET} SAME" for s in slots},
                                  "raw_text_sourced": [], "question_grounding": {}})
        monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda c=client: c)
        caplog.clear()
        out = ps._fill_unmatched_with_gpt({s: unmatched[s] for s in slots}, facts, "ACORD_125",
                                          raw_text=f"{_SECRET} SAME\n" * 3)
        if sum(1 for s in slots if s in out["filled_values"]) == 1:
            msgs = _all_messages(caplog)
            dedup = [m for _lvl, m in msgs if "dedup cleared" in m]
            assert dedup and all(_SECRET not in m for m in dedup)
            assert [m for _lvl, m in msgs if _SECRET in m] == []
            return
    pytest.skip("every candidate group was table-classified on this schema")


def test_the_values_sample_is_gone_from_the_source():
    src = (_BACKEND / "services" / "pdf_service.py").read_text(encoding="utf-8")
    assert "DIAG_RESPONSE_VALUES" not in src and "_diag_sample" not in src
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_fill_unmatched_with_gpt")
    levels = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "logger" and node.args \
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            for tag in ("DIAG_RESPONSE", "REJECT_SAMPLE", "NON_NULL_REJECTED", "gpt_fill REJECT:", "dedup cleared"):
                if tag in node.args[0].value:
                    levels.setdefault(tag, set()).add(node.func.attr)
    assert levels == {t: {"debug"} for t in ("DIAG_RESPONSE", "REJECT_SAMPLE", "NON_NULL_REJECTED",
                                               "gpt_fill REJECT:", "dedup cleared")}, levels


# ══════════════════════════════════════════════════════════════════════════════
# PART 4 - the purge comment says what is true (no behaviour change)
# ══════════════════════════════════════════════════════════════════════════════

def test_the_purge_comment_names_the_post_generation_readers_and_the_measurement():
    src = (_BACKEND / "routes" / "form_routes.py").read_text(encoding="utf-8")
    assert "is already-stamped values, never the facts." not in src
    assert "the index has no consumer left" not in src
    site = src[src.index("Data minimisation: the index is deleted once forms exist"):
               src.index('delete_facts=["dec_page_entries"]')]
    for needle in ("_restamp_canonical_into_forms", "_deterministic_map", "services/form_addition",
                   "9 of 5,852", "none gets a wrong value"):
        assert needle in site, needle
    head = src[src.index("# Drop the declarations index from the session"):
               src.index("_PURGE_DEC_INDEX_AFTER_GENERATION = os.getenv(")]
    assert "9 of 5,852" in head and "single-shot" not in head
    # behaviour unchanged: default ON, purged inside select_forms_bulk only
    assert '"PURGE_DEC_INDEX_AFTER_GENERATION", "1"' in src
    assert "if _PURGE_DEC_INDEX_AFTER_GENERATION and results:" in src
    assert not any(d in site + head for d in _EM)


def test_the_readers_the_comment_names_exist_and_read_the_facts():
    """So the corrected comment cannot rot into the old one silently."""
    arq = (_BACKEND / "services" / "arq_service.py").read_text(encoding="utf-8")
    tree = ast.parse(arq)
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for name in ("_restamp_canonical_into_forms", "_restamp_changed_boxes"):
        assert name in fns, name
        calls = {c.func.id for c in ast.walk(fns[name]) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        assert "_deterministic_map" in calls, name
    assert (_BACKEND / "services" / "form_addition.py").exists()
