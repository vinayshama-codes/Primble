"""Brent's Choice Electric items 16, 17 and 19 (owner's answers, 9 Oct 2026).

16 - "Remove this highlighted part about the SQS. Or change to '- fulfill to increase
     your Submission Quality Score (SQS)™.'" Owner: exactly that, on the SCREEN only, on
     every similar message, and the cap wording appears on no other message either.
     The stored message is untouched (issue ids, statuses and the legacy rule table key
     on it); `frontend/src/utils/positiveWording.js` rewrites what a person reads.
17 - ACORD 125 starts ticked on form selection; the list keeps its match-percentage
     order (`frontend/src/utils/formSelection.js`).
19 - A "Cancel" in the form editor: leaves edit mode without saving; "Done editing -
     save" waits for something to save.
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
_FRONT = _BACKEND.parent / "frontend" / "src"
_WORDING = _FRONT / "utils" / "positiveWording.js"
_SELECTION = _FRONT / "utils" / "formSelection.js"
_REVIEWED = _FRONT / "utils" / "reviewedStops.js"
_MODAL = _FRONT / "components" / "form" / "AcordModal.jsx"
_RAIL = _FRONT / "components" / "form" / "review" / "ReviewRailLayout.jsx"
_RECS = _FRONT / "components" / "form" / "review" / "Recommendations.jsx"
_FIX = _FRONT / "components" / "form" / "ResolutionModal.jsx"
_VIEWER = _FRONT / "components" / "form" / "PDFJsViewer.jsx"
_VIEWER_CSS = _FRONT / "components" / "form" / "PDFJsViewer.css"

POSITIVE = "fulfill to increase your Submission Quality Score (SQS)™"


def _node(tmp_path, imports, body):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    script = tmp_path / "check.mjs"
    script.write_text("".join(f"import * as {name} from {json.dumps(path.as_uri())};\n"
                              for name, path in imports.items()) + body + "\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


# ══ 16. Positive score wording, on screen only ═══════════════════════════════
# Every message the backend sends with a cap clause, as the screen receives it.
_MESSAGES = {
    "Carrier-Grade COPE incomplete - Submission Quality Score (SQS) capped at 85. Missing: year built, "
    "roof year, sprinkler system, fire protection class Fix: Review and correct this before proceeding.":
        f"Carrier-Grade COPE incomplete - {POSITIVE}. Missing: year built, roof year, sprinkler system, "
        "fire protection class Fix: Review and correct this before proceeding.",
    # An older stored session's shorter wording.
    "Carrier-Grade COPE incomplete - SQS capped at 85. Missing: year built":
        f"Carrier-Grade COPE incomplete - {POSITIVE}. Missing: year built",
    "FEIN differs across uploaded documents. Submission Quality Score (SQS) is capped at 60 until this is "
    "confirmed. (Fix: Confirm the correct value in Data Consistency.)":
        f"FEIN differs across uploaded documents - {POSITIVE}. (Fix: Confirm the correct value in Data Consistency.)",
    "Policy date mismatch across documents. Submission Quality Score (SQS) is capped at 60 unless the difference "
    "is explained. (Fix: Confirm the correct value in Data Consistency.)":
        f"Policy date mismatch across documents - {POSITIVE}. (Fix: Confirm the correct value in Data Consistency.)",
    "Policy expiration date mismatch across documents. Submission Quality Score (SQS) is capped at 60 unless "
    "the difference is explained.":
        f"Policy expiration date mismatch across documents - {POSITIVE}.",
    "Carrier-Grade COPE detail incomplete - missing: year built, roof year. Submission can proceed but your "
    "Submission Quality Score (SQS) will be capped.":
        f"Carrier-Grade COPE detail incomplete - missing: year built, roof year. Submission can proceed - {POSITIVE}.",
    "Data consistency: a No Known Losses attestation conflicts with claims found in the uploaded loss runs. "
    "Loss History is held at 45 until the discrepancy is resolved - confirm with the insured which is correct.":
        "Data consistency: a No Known Losses attestation conflicts with claims found in the uploaded loss runs - "
        f"{POSITIVE}. Confirm with the insured which is correct.",
    "Loss runs match the insured (name + FEIN/policy) but claim years are not readable - pinned at 60. Confirm "
    "claim years to unlock the year-based score.":
        f"Loss runs match the insured (name + FEIN/policy) but claim years are not readable - {POSITIVE}. "
        "Confirm claim years to unlock the year-based score.",
    # Older sessions' stored wordings (git history): "Score is capped ...", and a
    # COPE message written with an em dash.
    "FEIN differs across uploaded documents. Score is capped at 60 until this is confirmed.":
        f"FEIN differs across uploaded documents - {POSITIVE}.",
    "Policy date mismatch across documents. Score is capped at 60 unless the difference is explained.":
        f"Policy date mismatch across documents - {POSITIVE}.",
    "Carrier-Grade COPE incomplete \u2014 SQS capped at 85. Missing: roof year":
        f"Carrier-Grade COPE incomplete - {POSITIVE}. Missing: roof year",
    # Nothing to change: passes through word for word.
    "Driver schedule not provided": "Driver schedule not provided",
    "Hired auto symbol missing - Fix: add symbol 8": "Hired auto symbol missing - Fix: add symbol 8",
}

_CAP_WORDS = re.compile(r"(?i)(capped|held at \d|pinned at \d|caps? (?:your|the|this)|will cap)")


def test_every_capped_message_reads_brents_words(tmp_path):
    out = _node(tmp_path, {"W": _WORDING}, f"""
const msgs = {json.dumps(list(_MESSAGES))};
console.log(JSON.stringify({{
  once: msgs.map(W.positiveScoreWording),
  twice: msgs.map((m) => W.positiveScoreWording(W.positiveScoreWording(m))),
  odd: [W.positiveScoreWording(null), W.positiveScoreWording(undefined), W.positiveScoreWording(""),
        W.positiveScoreWording(7)],
  phrase: W.SQS_POSITIVE,
}}));
""")
    assert out["once"] == list(_MESSAGES.values())
    assert out["twice"] == out["once"]                 # idempotent: a re-render changes nothing
    assert out["odd"] == [None, None, "", 7]
    assert out["phrase"] == POSITIVE
    for text in out["once"]:
        assert not _CAP_WORDS.search(text), text


def _backend_cap_strings():
    """Every non-docstring string in the backend that tells the user a score is capped."""
    pattern = re.compile(r"(?i)(capped at \d|is capped|will be capped|\bheld at \d|pinned at \d|"
                         r"caps? (?:your|the|this) (?:sqs|score|submission)|still capped)")
    found = set()
    for folder in ("services", "routes", "utils"):
        for path in sorted((_BACKEND / folder).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    body = getattr(node, "body", [])
                    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                        docstrings.add(id(body[0].value))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and id(node) not in docstrings and pattern.search(node.value)):
                    found.add(node.value)
    return found


def test_no_new_capped_message_can_reach_the_screen_unrewritten():
    # The backend's cap-worded strings, harvested from the source. A NEW one fails
    # here until positiveWording.js rewrites it and a case is added above.
    assert _backend_cap_strings() == {
        "Carrier-Grade COPE incomplete - Submission Quality Score (SQS) capped at 85. Missing: ",
        # 21 Oct (Z30, b-identity-verified-only): the sentence is built once and
        # prefixed by severity at the call, so the harvested literal is bare.
        "FEIN differs across uploaded documents. Submission Quality Score (SQS) is capped at 60 until this is confirmed.",
        " Submission Quality Score (SQS) is capped at 60 unless the difference is explained.",
        ". Submission can proceed but your Submission Quality Score (SQS) will be capped.",
        "Data consistency: a No Known Losses attestation conflicts with claims found in the uploaded loss runs. "
        "Loss History is held at 45 until the discrepancy is resolved - confirm with the insured which is correct.",
        "Loss runs match the insured (name + FEIN/policy) but claim years are not readable - pinned at 60. "
        "Confirm claim years to unlock the year-based score.",
    }


def test_the_stored_message_is_never_rewritten():
    # Screen only: no backend file imports or mirrors the display wording.
    for folder in ("services", "routes"):
        for path in (_BACKEND / folder).rglob("*.py"):
            assert "fulfill to increase your" not in path.read_text(encoding="utf-8"), path


def test_every_place_a_message_is_printed_uses_the_wording():
    modal = _MODAL.read_text(encoding="utf-8")
    # IssueLine draws every review card (both layouts) and every bare stop row.
    assert "function IssueLine({ message: stored, className }) {" in modal
    assert "const message = positiveScoreWording(stored);" in modal
    assert "{positiveScoreWording(issue?.message)}" in _FIX.read_text(encoding="utf-8")
    assert "{positiveScoreWording(it.detail)}" in _RECS.read_text(encoding="utf-8")
    # No raw message render is left behind in the screens that list stops.
    # A prop handed on (message={it.message}) is IssueLine's to word, and ${r.message}
    # is the downloadable audit report (a file, not the screen); text drawn as-is is not.
    raw = re.compile(r"(?<![=$])\{(?:r|g|d|iss|it|issue\?|rec)\.message\}|>\{msg\}<|• \{s\}<|<span>\{s\}</span>|- \{s\}<")
    for path in (_MODAL, _RAIL, _FIX, _RECS):
        assert not raw.search(path.read_text(encoding="utf-8")), path
    assert modal.count("positiveScoreWording(") >= 16


def _screen_text(path):
    """A frontend file with its comments taken out (approximately - enough to scan copy)."""
    src = path.read_text(encoding="utf-8")
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return "\n".join(re.sub(r"(^|\s)//.*$", r"\1", line) for line in src.splitlines())


def test_no_heading_or_note_on_screen_says_the_score_is_capped():
    banned = re.compile(r"(?i)(capped at|still capped|caps your|caps the (?:package|score)|caps this form|"
                        r"will cap|still caps|still holds the score|holding your score)")
    offenders = []
    for path in list(_FRONT.rglob("*.jsx")) + list(_FRONT.rglob("*.js")):
        if path == _WORDING:
            continue                                   # the rewriter names what it rewrites
        for i, line in enumerate(_screen_text(path).splitlines(), 1):
            if banned.search(line):
                offenders.append(f"{path.relative_to(_FRONT)}:{i}: {line.strip()[:120]}")
    assert offenders == []


def test_the_reviewed_notes_say_what_raises_the_score(tmp_path):
    out = _node(tmp_path, {"R": _REVIEWED}, """
console.log(JSON.stringify({
  hard: R.railCapNote({ cap_applied: 60, raw_sqs_score: 80, package_sqs_score: 60 }, { hardTotal: 1, hardOpen: 0 }),
  warn: R.railCapNote({ cap_applied: 85, raw_sqs_score: 90, package_sqs_score: 85 }, { warnTotal: 2, warnOpen: 0 }),
  ready: R.railCapNote({ ready_blockers: ["x"], cap_applied: 60, raw_sqs_score: 80, package_sqs_score: 60 },
                       { hardTotal: 1, hardOpen: 0 }),
  readyOpen: R.railCapNote({ ready_blockers: ["x"], cap_applied: 60, raw_sqs_score: 80, package_sqs_score: 60 },
                           { hardTotal: 1, hardOpen: 1 }),
  readyNone: R.railCapNote({ ready_blockers: [], cap_applied: 85, raw_sqs_score: 90, package_sqs_score: 85 },
                           { warnTotal: 2, warnOpen: 0 }),
  uncapped: R.railCapNote({ ready_blockers: ["x"], package_sqs_score: 95 }, { hardTotal: 1, hardOpen: 0 }),
  one: R.stillCappedNote([{ status: "dismissed" }], "package"),
  many: R.stillCappedNote([{ status: "resolved" }, { status: "dismissed" }], "form"),
}));
""")
    assert out["hard"] == ("Fix the value of the hard stop you marked to increase your Submission Quality Score "
                           "(SQS)™ - marking it records your review only.")
    assert out["warn"] == ("Fix the value of the warning you marked to increase your Submission Quality Score "
                           "(SQS)™ - marking it records your review only.")
    # (20 Oct 2026, the cap is back) - the note follows the cap alone, as before 19 Oct: the
    # readiness fields riding along change nothing (a marked warning holds the 85 again), an
    # open stop prints in the red block instead, and no cap means no note.
    assert out["ready"] == out["hard"] and out["readyNone"] == out["warn"]
    assert out["readyOpen"] is None and out["uncapped"] is None
    assert out["one"] == ("Fix the value of an item you marked dismissed to increase the package's Submission "
                          "Quality Score (SQS)™, or reopen it under Reviewed.")
    assert out["many"] == ("Fix the value of 2 items you marked resolved or dismissed to increase this form's "
                           "Submission Quality Score (SQS)™, or reopen them under Reviewed.")


def test_the_headings_use_brents_words():
    modal, rail = _MODAL.read_text(encoding="utf-8"), _RAIL.read_text(encoding="utf-8")
    assert modal.count("Required before submission - fulfill to increase your Submission Quality Score (SQS)™") == 1
    assert rail.count("Required before submission - fulfill to increase your Submission Quality Score (SQS)™") == 1
    assert 'description="Fulfill to increase your Submission Quality Score (SQS)™"' in rail
    assert "Fulfill to increase the package's Submission Quality Score (SQS)™" in modal
    assert "Fulfill to increase this form's Submission Quality Score (SQS)™" in modal
    # (20 Oct 2026, the cap is back) - the 19 Oct readiness copy is gone again: the
    # editor's package block and the review rail say what raises the score.
    assert "Block Submission Ready until fixed" not in modal
    assert "blocks Submission Ready until it is fixed." not in rail
    assert "block Submission Ready until they are fixed." not in rail
    # No em-dashes in UI text: the new files whole, and every new line elsewhere
    # (older code comments in the modal carry some; they are not on screen).
    for text in (rail, _WORDING.read_text(encoding="utf-8"), _SELECTION.read_text(encoding="utf-8")):
        assert "—" not in text
    for line in (modal + _REVIEWED.read_text(encoding="utf-8")).splitlines():
        if re.search(r"(?i)fulfill to increase|fix its value|fix the value of|clear of (?:hard stops|warnings)", line):
            assert "—" not in line, line


# ══ 17. ACORD 125 starts ticked; the order is the recommender's ══════════════
def test_acord_125_is_ticked_on_arrival_unless_the_producer_unticked_it(tmp_path):
    out = _node(tmp_path, {"F": _SELECTION}, """
const recs = [{ form_id: "ACORD_131" }, { form_id: "ACORD_127" }, { form_id: "ACORD_125" }];
const empty = new Set();
const same = new Set(["ACORD_125", "ACORD_126"]);
const show = (s) => [...s].sort();
console.log(JSON.stringify({
  arrive: show(F.withAnchorForm(empty, recs, false)),
  keepsPicks: show(F.withAnchorForm(new Set(["ACORD_127"]), recs, false)),
  declined: show(F.withAnchorForm(empty, recs, true)),
  notOffered: show(F.withAnchorForm(empty, [{ form_id: "ACORD_25" }], false)),
  noRecs: show(F.withAnchorForm(empty, null, false)),
  uploaded: show(F.withAnchorForm(empty, [{ form_id: "ACORD_125", is_source_document: true }], false)),
  sameSet: F.withAnchorForm(same, recs, false) === same,
  untouchedReview: F.checkedFormsForReview(new Set(["ACORD_125"]), false),
  touchedReview: F.checkedFormsForReview(new Set(["ACORD_125", "ACORD_126"]), true),
  id: F.ANCHOR_FORM_ID,
}));
""")
    assert out["arrive"] == ["ACORD_125"]
    assert out["keepsPicks"] == ["ACORD_125", "ACORD_127"]
    assert out["declined"] == []                       # unticked by the producer: stays unticked
    assert out["notOffered"] == [] and out["noRecs"] == []
    # The producer uploaded their own filled ACORD 125: the recommender says "generate
    # a clean copy only if needed", so it is not ticked for them.
    assert out["uploaded"] == []
    assert out["sameSet"] is True                      # nothing to add: no re-render
    # The review page's checks still cover the recommended forms until the
    # producer changes a tick - the anchor tick alone never narrows them.
    assert out["untouchedReview"] == [] and out["touchedReview"] == ["ACORD_125", "ACORD_126"]
    assert out["id"] == "ACORD_125"


def test_the_modal_ticks_125_on_form_selection_and_keeps_the_order():
    modal = _MODAL.read_text(encoding="utf-8")
    effect = modal[modal.index("  useLayoutEffect(() => {\n    if (step !== \"form_selection\") return;"):]
    effect = effect[:effect.index("}, [step, recommendations, declined125]);")]
    assert "setCheckedFormIds(prev => withAnchorForm(prev, recommendations, declined125));" in effect
    # Every reset of the ticks also forgets the untick and the "touched" mark.
    assert modal.count("setCheckedFormIds(new Set())") == 1          # only inside resetFormTicks
    assert "const resetFormTicks = () => { setCheckedFormIds(new Set()); setDeclined125(false); setFormTicksTouched(false); };" in modal
    assert modal.count("resetFormTicks();") == 5
    # The producer's own changes: an untick of 125 sticks; the checks follow the ticks.
    toggle = modal[modal.index("const toggleForm = formId => {"):modal.index("useLayoutEffect(() => {\n    if (step !== \"form_selection\")")]
    assert "setFormTicksTouched(true);" in toggle
    assert "if (formId === ANCHOR_FORM_ID) setDeclined125(checkedFormIds.has(formId));" in toggle
    add = modal[modal.index("const addFormBeforeGeneration = (formId) => {"):]
    assert "setFormTicksTouched(true);" in add[:add.index("};")]
    assert modal.count("checkedFormsForReview(checkedFormIds, formTicksTouched)") == 2
    assert "[...checkedFormIds]" not in modal
    # Order: still the backend's confidence order within each tier, no re-sort.
    assert "Order within a\n  // tier is preserved from the backend (confidence-sorted)." in modal
    assert "ANCHOR_FORM_ID)" not in modal[modal.index("const groupedRecs = TIER_ORDER"):][:400]


# ══ 19. Cancel in the form editor ════════════════════════════════════════════
def test_cancel_leaves_edit_mode_without_saving():
    src = _VIEWER.read_text(encoding="utf-8")
    body = src[src.index("const handleCancelEdits = () => {"):]
    body = body[:body.index("\n  };\n")]
    assert 'if (hasUnsavedEdits() && !window.confirm("Discard your changes to this form?")) return;' in body
    assert "const saved = { ...originalFieldValuesRef.current };" in body
    assert "fieldValuesRef.current = saved;" in body
    assert "clearedSigFieldsRef.current = new Set();" in body       # a removed signature comes back
    assert "_syncPending();" in body and "setEditMode(false);" in body
    for never in ("fetch(", "saveEdits(", "_saveOnExit(", "_loadPdfInBackground("):
        assert never not in body, never                              # nothing sent, nothing redrawn
    # After a save that failed HERE (it may still have reached the server), the
    # form is read back rather than trusting the last values known locally, and
    # the "Save failed - edits kept" note goes.
    # The discarded edits leave the boxes FIRST (so a failed read-back can never
    # resend them), then the form is read back and "Save failed" goes.
    failed = body[body.index('if (saveStatus === "error") {'):]
    assert body.index("fieldValuesRef.current = saved;") < body.index('if (saveStatus === "error") {')
    assert 'setSaveStatus("idle");' in failed and "fetchFields().catch(() => {});" in failed
    # Two blanks are one value: a blank checkbox ticked and unticked is no edit.
    edits = src[src.index("const hasUnsavedEdits = () =>"):src.index("const _syncPending = () =>")]
    assert "!(isBlankBoxValue(now) && isBlankBoxValue(saved))" in edits


def test_the_toolbar_has_cancel_and_the_save_waits_for_an_edit():
    src = _VIEWER.read_text(encoding="utf-8")
    assert "{editMode && (\n            <button type=\"button\" onClick={handleCancelEdits} disabled={editBusy}" in src
    assert 'className="pdfviewer-cancel-btn"' in src
    cancel = src.index("onClick={handleCancelEdits}")
    save = src.index("<button onClick={handleToggleEditMode}")
    assert cancel < save                                              # Cancel sits left of the save
    assert "const [pendingEdits,  setPendingEdits]  = useState(false);" in src
    assert "const nothingToSave = editMode && !pendingEdits;" in src
    assert "<button onClick={handleToggleEditMode} disabled={editBusy || nothingToSave}" in src
    # A removed signature counts as an edit before the pending signal is read.
    assert "clearedSigFieldsRef.current.add(field.name); triggerSave(field.name, \"\");" in src
    assert '"Done editing - save" saves all changes, "Cancel" discards them' in src
    css = _VIEWER_CSS.read_text(encoding="utf-8")
    assert ".pdfviewer-cancel-btn {" in css
    # App.css shrinks every toolbar button; Cancel keeps the save button's size.
    assert css.count(".pdfviewer-toolbar-actions .pdfviewer-cancel-btn {") == 2
    for line in src.splitlines():                     # no em-dashes in the new UI text
        if "Cancel" in line or "Discard your changes" in line or "Nothing to save yet" in line:
            assert "—" not in line, line


def test_wide_screens_keep_the_edit_toolbar_on_one_row():
    # Measured (headless Chrome, 9 Oct): at 1440 the toolbar had 1px to spare
    # before Cancel and wrapped with it. In edit mode, over 1366px, the buttons
    # stay on the row and the form name truncates; the counts keep their size,
    # and nothing clips the "?" colour legend that opens below them.
    src = _VIEWER.read_text(encoding="utf-8")
    assert 'className={`pdfviewer-toolbar-top${editMode ? " is-editing" : ""}`}' in src
    css = _VIEWER_CSS.read_text(encoding="utf-8")
    wide = css[css.index("@media (min-width: 1367px) {\n  .pdfviewer-toolbar-top.is-editing"):]
    wide = wide[:wide.index("\n}\n")]
    assert ".pdfviewer-toolbar-top.is-editing { flex-wrap: nowrap !important; }" in wide
    assert ".pdfviewer-toolbar-top.is-editing .pdfviewer-toolbar-actions {\n    flex-shrink: 0;\n    flex-wrap: nowrap !important;" in wide
    assert "span:not(:first-child) {\n    flex-shrink: 0;\n    white-space: nowrap;" in wide
    assert "overflow: hidden" not in wide


def test_a_narrow_toolbar_puts_its_buttons_on_a_second_row():
    # Measured (headless Chrome, 9 Oct): with the editor sidebar open on a 1024px
    # screen the edit-mode counts ran into the buttons and the name disappeared.
    # Under 900px of toolbar the buttons take a second row; the name keeps 120px.
    src = _VIEWER.read_text(encoding="utf-8")
    assert '<div className="pdfviewer-toolbar-shell">' in src
    css = _VIEWER_CSS.read_text(encoding="utf-8")
    assert ".pdfviewer-toolbar-shell { container-type: inline-size; flex-shrink: 0; }" in css
    narrow = css[css.index("@container (max-width: 900px) {"):]
    narrow = narrow[:narrow.index("\n}\n")]
    assert ".pdfviewer-toolbar-shell .pdfviewer-toolbar-top { flex-wrap: wrap !important;" in narrow
    assert ".pdfviewer-toolbar-shell .pdfviewer-toolbar-top > div:first-child { flex: 1 1 100% !important; }" in narrow


def test_screen_changing_buttons_ignore_a_double_clicks_second_click():
    # On a narrow screen the review's footer button sits where form selection's
    # Generate does; the second click of a double-click started a generation.
    modal = _MODAL.read_text(encoding="utf-8")
    assert 'onClick={(e) => { if (e.detail > 1) return; setStep("review"); }}' in modal
    assert "onClick={(e) => { if (e.detail > 1) return; handleGenerateAll(); }}" in modal
    assert "onClick={(e) => { if (e.detail > 1) return; handleContinueFromPackage(); }}" in modal
    # ...and a review-page error does not follow the producer onto form selection.
    assert 'if (pkgGen.state !== GEN_RUNNING || !sessionId) { setError(null); setStep("form_selection"); return; }' in modal


def test_the_resolved_list_keeps_a_row_while_it_reopens():
    modal = _MODAL.read_text(encoding="utf-8")
    reopen = modal[modal.index("const handleReopenIssue = async"):modal.index("const reopenFromResolved")]
    assert "{ optimistic = true, legacyClear = false } = {}" in reopen and "if (optimistic) markOpen();" in reopen
    # Only the editor's Cross-Form panel asks for the old field clear (9 Oct review).
    assert "legacy_clear: !!legacyClear," in reopen
    assert "if (!optimistic) markOpen(); _applyCrossIssuePanelUpdate(data); return;" in reopen
    frm = modal[modal.index("const reopenFromResolved"):modal.index("const openKeyDetailFix")]
    assert 'handleReopenIssue(row.iid, "open", meta, { optimistic: false });' in frm
    assert 'if (kind === "none") return;' in frm and '"settle"' not in frm


def test_the_score_tooltip_names_the_right_kind_of_stop():
    modal = _MODAL.read_text(encoding="utf-8")
    assert 'applies while ${Number(ceiling) === 60 ? "hard stops" : "warnings"} are open' in modal
    rail = _RAIL.read_text(encoding="utf-8")
    assert 'if (warnTab !== "all" && !warnTabIds.split(",").includes(warnTab)) setWarnTab("all");' in rail
