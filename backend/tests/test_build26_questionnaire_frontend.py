"""Build 26 (23 Oct 2026): the review's Questionnaire page - frontend.

Owner's decisions: a new review page "Questionnaire", the LAST page before
form selection (after Recommendations, same group), its rail badge the number
of questions that need the producer; "Skip to form selection" still skips it
and it never blocks generation. Every card that opened the "Explain via ACORD
101" narrative window opens the page at the question whose fact matches, and
keeps the window when none does. The page lists the backend's sections with a
"Show only what needs me" filter (on), a state tag, the source, and the
actions answer / "Looks right" / Unknown / Pending / Not applicable; Send to
client; the carrier narrative drafted and approved for ACORD 101.

The pure rules live in frontend/src/utils/questionnaire.js and are driven
through node here; the wiring is pinned on the source.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_FRONT = Path(__file__).resolve().parents[2] / "frontend" / "src"
_UTIL = _FRONT / "utils" / "questionnaire.js"
_PAGE = _FRONT / "components" / "form" / "review" / "QuestionnairePage.jsx"
_HOOK = _FRONT / "components" / "form" / "review" / "useQuestionnaire.js"
_CSS = _FRONT / "components" / "form" / "review" / "QuestionnairePage.css"
_RAIL = _FRONT / "components" / "form" / "review" / "ReviewRailLayout.jsx"
_MODAL = _FRONT / "components" / "form" / "AcordModal.jsx"


def _node(tmp_path, body):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    script = tmp_path / "check.mjs"
    script.write_text(f"import * as Q from {json.dumps(_UTIL.as_uri())};\n{body}\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60,
                         env={**os.environ, "TZ": "UTC"})
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


_Q = lambda **kw: {"id": "q1", "text": "Q", "answer_type": "text", "state": "missing",  # noqa: E731
                   "needs_input": True, **kw}

_MODEL = {
    "sections": [
        {"id": "ops", "title": "Operations", "line": None, "questions": [
            _Q(id="ops1", fact="operations_description", state="extracted", needs_input=False,
               display_value="Electrical contractor"),
            _Q(id="ops2", fact="safety_program", state="missing"),
        ]},
        {"id": "loss", "title": "Losses", "line": "gl", "questions": [
            _Q(id="l1", fact="additional_remarks_text", state="unverified", display_value="None"),
        ]},
        "not a section",
        {"title": "no id"},
    ],
    "counts": {"needs_input": 2, "total": 3},
    "narrative": {"state": "approved", "text": "Story", "approved_at": "2026-10-23T10:42:00Z"},
}


# ── State tags ───────────────────────────────────────────────────────────────
def test_every_state_has_its_tag_in_plain_words(tmp_path):
    out = _node(tmp_path, """
const states = ["extracted", "producer_confirmed", "insured_confirmed", "unverified", "conflicting",
  "not_applicable", "missing", "unknown", "pending", "nonsense", null];
console.log(JSON.stringify(states.map((s) => Q.stateTag(s))));
""")
    texts = [o and o["text"] for o in out]
    assert texts == ["From your documents", "Confirmed", "Confirmed", "Needs confirmation", "Conflicting",
                     "Not applicable", "Missing", "Unknown", "Pending", None, None]
    assert out[1]["by"] == "by you" and out[2]["by"] == "by the client" and out[0]["by"] is None


# ── Filter, counts, rail ─────────────────────────────────────────────────────
def test_the_filter_shows_only_what_needs_the_producer_and_keeps_a_saved_row(tmp_path):
    out = _node(tmp_path, f"""
const m = {json.dumps(_MODEL)};
const secs = Q.sectionsOf(m);
console.log(JSON.stringify({{
  ids: secs.map((s) => s.id),
  on: secs.map((s) => Q.visibleQuestions(s, true).map((q) => q.id)),
  off: secs.map((s) => Q.visibleQuestions(s, false).map((q) => q.id)),
  kept: Q.visibleQuestions(secs[0], true, new Set(["ops1"])).map((q) => q.id),
}}));
""")
    assert out["ids"] == ["ops", "loss"]                      # junk sections dropped
    assert out["on"] == [["ops2"], ["l1"]]
    assert out["off"] == [["ops1", "ops2"], ["l1"]]
    assert out["kept"] == ["ops1", "ops2"]


def test_counts_line_and_rail_badge(tmp_path):
    out = _node(tmp_path, f"""
const m = {json.dumps(_MODEL)};
const noCounts = {{ ...m, counts: undefined }};
const done = {{ sections: [{{ id: "a", questions: [{{ id: "x", needs_input: false }}] }}] }};
const empty = {{ sections: [] }};
console.log(JSON.stringify({{
  counts: Q.countsOf(m), counted: Q.countsOf(noCounts),
  lines: [Q.countLine({{ needs_input: 2, total: 3 }}), Q.countLine({{ needs_input: 1, total: 1 }}),
          Q.countLine({{ needs_input: 0, total: 4 }}), Q.countLine({{ needs_input: 0, total: 0 }})],
  subs: [Q.railSub(m), Q.railSub(done), Q.railSub(empty), Q.railSub(null), Q.railSub(null, true)],
  badges: [Q.railBadge(m), Q.railBadge(done), Q.railBadge(empty), Q.railBadge(null)],
}}));
""")
    assert out["counts"] == {"needs_input": 2, "total": 3}
    assert out["counted"] == {"needs_input": 2, "total": 3}
    assert out["lines"] == ["2 of 3 questions need you.", "1 of 1 question needs you.",
                            "All 4 questions answered or confirmed.", "No questions for this package."]
    assert out["subs"] == ["2 need you", "All answered", "No questions", "Loading...", "Not available"]
    assert out["badges"] == [2, "done", None, None]


# ── Sources, conflicts, options ──────────────────────────────────────────────
def test_sources_conflicts_and_options(tmp_path):
    out = _node(tmp_path, """
const q = { sources: [{ document: "Package.pdf", page: 3 }, { document: "Package.pdf", page: 3 },
                      { document: "WC.pdf" }, { page: 0 }, null, {}],
            conflict_values: [{ value: "$1,000,000", document: "GL dec" }, { value: "$3,000,000" }, { value: "" }],
            options: ["Owner", { value: "Tenant", label: "Tenant (renter)" }, "", null, { label: "Other" }] };
console.log(JSON.stringify({ src: Q.sourceLines(q), con: Q.conflictGroups(q), opts: Q.optionsOf(q),
  one: Q.sourceText({ document: "A.pdf", page: "12" }) }));
""")
    assert out["src"] == ["Package.pdf, page 3", "WC.pdf", "Page 0"]
    assert out["one"] == "A.pdf, page 12"
    assert out["con"] == [{"value": "$1,000,000", "documents": ["GL dec"], "choice": 0},
                          {"value": "$3,000,000", "documents": [], "choice": 1}]
    assert out["opts"] == [{"value": "Owner", "label": "Owner"}, {"value": "Tenant", "label": "Tenant (renter)"},
                           {"value": "Other", "label": "Other"}]


# ── Answers ──────────────────────────────────────────────────────────────────
def test_the_answer_body_per_action(tmp_path):
    out = _node(tmp_path, """
const q = { id: "q1", answer_type: "text" };
const t = { id: "t1", answer_type: "table" };
console.log(JSON.stringify([
  Q.answerBody(q, "answer", "  Electrical  "), Q.answerBody(q, "answer", "   "),
  Q.answerBody(q, "confirm", "ignored"), Q.answerBody(q, "unknown"), Q.answerBody(q, "pending"),
  Q.answerBody(q, "not_applicable"), Q.answerBody(q, "delete"), Q.answerBody({}, "confirm"),
  Q.answerBody(t, "answer", [{ code: "8810" }]), Q.answerBody(t, "answer", "not rows"),
]));
""")
    assert out == [
        {"question_id": "q1", "action": "answer", "value": "Electrical"}, None,
        {"question_id": "q1", "action": "confirm"}, {"question_id": "q1", "action": "unknown"},
        {"question_id": "q1", "action": "pending"}, {"question_id": "q1", "action": "not_applicable"},
        None, None,
        {"question_id": "t1", "action": "answer", "value": [{"code": "8810"}]},
        {"question_id": "t1", "action": "answer", "value": []},
    ]


def test_looks_right_needs_a_value_and_is_never_offered_on_a_conflict(tmp_path):
    out = _node(tmp_path, """
console.log(JSON.stringify([
  Q.canConfirm({ state: "extracted", display_value: "X" }),
  Q.canConfirm({ state: "unverified", value: "5" }),
  Q.canConfirm({ state: "missing", display_value: "" }),
  Q.canConfirm({ state: "producer_confirmed", display_value: "X" }),
  Q.canConfirm({ state: "conflicting", display_value: "X" }),
  Q.canConfirm({ state: "extracted", answer_type: "table", value: [{ a: 1 }] }),
  Q.canConfirm({ state: "extracted", answer_type: "table", value: [] }),
  Q.canConfirm(null),
]));
""")
    assert out == [True, True, False, False, False, True, False, False]


def test_a_saved_question_replaces_its_row_and_the_counts(tmp_path):
    out = _node(tmp_path, f"""
const m = {json.dumps(_MODEL)};
const q = {{ id: "ops2", fact: "safety_program", state: "producer_confirmed", needs_input: false }};
const a = Q.withQuestion(m, q, {{ needs_input: 1, total: 3 }});
const b = Q.withQuestion(m, q, null);
console.log(JSON.stringify({{
  a: a.sections[0].questions.map((x) => x.state), ac: a.counts, bc: b.counts,
  untouched: m.sections[0].questions[1].state, same: Q.withQuestion(m, null) === m,
}}));
""")
    assert out["a"] == ["extracted", "producer_confirmed"]
    assert out["ac"] == {"needs_input": 1, "total": 3}
    assert out["bc"] == {"needs_input": 1, "total": 3}            # re-counted
    assert out["untouched"] == "missing" and out["same"] is True


# ── Deep link ────────────────────────────────────────────────────────────────
def test_a_narrative_card_links_to_its_question_most_specific_fact_first(tmp_path):
    out = _node(tmp_path, f"""
const m = {json.dumps(_MODEL)};
const gaps = {{ resolution: {{ mode: "narrative", gaps: [{{ key: "topic:safety_program" }}] }} }};
const manyGaps = {{ resolution: {{ mode: "narrative", gaps: [{{ key: "topic:years_in_business" }}, {{ key: "topic:safety_program" }}] }} }};
const bare = {{ resolution: {{ mode: "narrative" }} }};
const own = {{ fact: "operations_description", resolution: {{ mode: "narrative" }} }};
const dry = {{ resolution: {{ mode: "narrative", facts: ["additional_remarks_text"] }} }};
console.log(JSON.stringify({{
  facts: Q.narrativeFactsOf(gaps),
  gaps: Q.questionnaireLinkFor(m, gaps),
  manyGaps: Q.questionnaireLinkFor(m, manyGaps),
  bare: Q.questionnaireLinkFor(m, bare),
  own: Q.questionnaireLinkFor(m, own),
  dry: Q.questionnaireLinkFor(m, dry),
  field: Q.questionnaireLinkFor(m, {{ fact: "operations_description", resolution: {{ mode: "field", facts: ["operations_description"] }} }}),
  addForm: Q.questionnaireLinkFor(m, {{ ...bare, __addForm: true }}),
  noModel: Q.questionnaireLinkFor(null, bare),
  noMatch: Q.questionnaireLinkFor({{ sections: [{{ id: "s", questions: [{{ id: "z", fact: "other" }}] }}] }}, bare),
}}));
""")
    assert out["facts"] == ["topic:safety_program", "safety_program", "additional_remarks_text"]
    no_card = {"code": None, "issue_id": None}
    assert out["gaps"] == {"sectionId": "ops", "questionId": "ops2", "fact": "safety_program", **no_card}
    assert out["bare"] == {"sectionId": "loss", "questionId": "l1", "fact": "additional_remarks_text", **no_card}
    assert out["own"] == {"sectionId": "ops", "questionId": "ops1", "fact": "operations_description", **no_card}
    assert out["dry"]["questionId"] == "l1"
    # A one-narrative-many-topics window (Narrative Quality) keeps its own window (23 Oct:
    # it had opened "Years in business").
    assert out["manyGaps"] is None
    # Only a narrative window links; an add-form click, no data or no match keeps the window.
    assert out["field"] is None and out["addForm"] is None
    assert out["noModel"] is None and out["noMatch"] is None


def test_dom_ids_and_the_narrative(tmp_path):
    out = _node(tmp_path, f"""
const m = {json.dumps(_MODEL)};
console.log(JSON.stringify({{
  id: Q.questionDomId("gl:class code/1"),
  n: Q.narrativeOf(m), none: Q.narrativeOf({{}}), odd: Q.narrativeOf({{ narrative: {{ state: "x", text: 5 }} }}),
  at: Q.approvedText("2026-10-23T10:42:00Z"), noAt: Q.approvedText(null), bad: Q.approvedText("not a date"),
  err: [Q.replyError({{ error: "Refused." }}), Q.replyError({{ detail: {{ message: "No." }} }}), Q.replyError(null)],
}}));
""")
    assert out["id"] == "qn-q-gl_class_code_1"
    assert out["n"] == {"state": "approved", "text": "Story", "approved_at": "2026-10-23T10:42:00Z"}
    assert out["none"] == {"state": "none", "text": "", "approved_at": None}
    assert out["odd"] == {"state": "none", "text": "", "approved_at": None}
    assert out["at"] == "Approved for ACORD 101 on 23 Oct 2026, 10:42"
    assert out["noAt"] == out["bad"] == "Approved for ACORD 101"
    assert out["err"] == ["Refused.", "No.", "Could not save. Try again."]


# ── Wiring ───────────────────────────────────────────────────────────────────
def test_the_page_is_the_last_rail_page_in_the_fix_group_with_its_badge():
    rail = _RAIL.read_text(encoding="utf-8")
    block = rail[rail.index("const SECTIONS = ["):]
    block = block[:block.index("];")]
    ids = re.findall(r'\{ id: "([^"]+)", label: "[^"]+", group: ([A-Z_"a-z ]+) \}', block)
    assert ids[-2:] == [("recommendations", "FIX_GROUP"), ("questionnaire", "FIX_GROUP")]
    assert 'id: "questionnaire",\n      sub: railSub(questionnaire?.model, questionnaire?.error),\n' \
           '      badge: railBadge(questionnaire?.model),' in rail
    assert "questionnaire: questionnaireSection," in rail
    # The footer is untouched: nextReviewStep walks SECTIONS, so Recommendations
    # reads "Continue to Questionnaire" and the skip still skips.
    assert "const step = nextReviewStep(SECTIONS, section, genState);" in rail


def test_every_fix_window_opens_through_the_deep_link_door():
    modal = _MODAL.read_text(encoding="utf-8")
    for call in ("openFixWindow(dryRunFixIssue(item));", "openFixWindow(scoreFixIssue(item));",
                 "openFixWindow(issue);", "openFixWindow({\n      message: `Key detail missing:"):
        assert call in modal, call
    for old in ("setResolutionIssue(dryRunFixIssue(item))", "setResolutionIssue(scoreFixIssue(item))"):
        assert old not in modal
    door = modal[modal.index("const openQuestionnaireFor = (issue) => {"):]
    door = door[:door.index("const applyQuestionnaireAnswer")]
    assert "questionnaireLinkFor(questionnaire.model, issue)" in door
    assert 'goBackToReview("questionnaire")' in door                    # from the editor
    assert 'showReviewSection("questionnaire", { scrollToTop: false })' in door
    # The add-form button keeps the window (it adds the form there).
    assert "forms), __addForm: true })" in modal
    # "Back to review" takes the page to open; a click event is not one.
    assert 'typeof toSection === "string" && toSection ? toSection : reviewOpen.section' in modal


def test_a_saved_answer_merges_like_a_fix_window():
    modal = _MODAL.read_text(encoding="utf-8")
    body = modal[modal.index("const applyQuestionnaireAnswer = (data, question, card = null) => {"):]
    body = body[:body.index("\n  };\n")]
    for call in ("markClearedBlockers(data, by);", "markClearedRecommendations(data, card?.issue_id",
                 "_applyCrossIssuePanelUpdate(data);"):
        assert call in body
    assert "onQuestionnaireApplied={applyQuestionnaireAnswer}" in modal
    # The classic layout shows the page after Recommendations too.
    classic = modal[modal.index('{step === "review" && !reviewRail && ('):]
    assert classic.index("<Recommendations heading") < classic.index("<QuestionnairePage heading")


def test_the_page_speaks_the_contract():
    page = _PAGE.read_text(encoding="utf-8")
    hook = _HOOK.read_text(encoding="utf-8")
    assert "`${API_BASE}/api/questionnaire/${sessionId}`" in hook
    for path in ("/answer`", "/send-to-client`", "/narrative/draft`", "/narrative/approve`"):
        assert f"`${{API_BASE}}/api/questionnaire/${{sessionId}}{path}" in page, path
    assert "{ text }" in page
    # Saving shows on the row only, and the table answer reuses ScheduleTable.
    assert 'busy === "answer" ? "Saving..." : "Save"' in page
    assert "<ScheduleTable" in page
    # No info icons (SQS pillars only) and no em-dashes anywhere in the new UI.
    for path in (_UTIL, _PAGE, _HOOK, _CSS):
        text = path.read_text(encoding="utf-8")
        assert "—" not in text, path.name
    assert "HoverTip" not in page and "info-icon" not in page


# ══ The review of Z36 (23 Oct 2026) ═════════════════════════════════════════
def test_a_table_answer_reloads_the_whole_page_and_a_stale_view_never_posts(tmp_path):
    out = _node(tmp_path, """
console.log(JSON.stringify([
  Q.reloadsPage({ answer_type: "table" }), Q.reloadsPage({ answer_type: "text", table_key: "property_locations" }),
  Q.reloadsPage({ answer_type: "text" }), Q.reloadsPage(null),
]));
""")
    assert out == [True, True, False, False]
    page = _PAGE.read_text(encoding="utf-8")
    saved = page[page.index("const onSaved = (data, question, card) => {"):]
    saved = saved[:saved.index("\n  };\n")]
    assert "if (reloadsPage(question) && onReload) onReload();" in saved
    # a table editor remembers the rows it opened on and refuses a save over newer ones
    save = page[page.index("const save = async (action, value, choice = null) => {"):]
    save = save[:save.index("const body = answerBody(")]
    assert "JSON.stringify(draftOf(q)) !== tableBase.current" in save
    assert "setDraft(draftOf(q));" in save and "return;" in save


_CODED = ["umbrella_auto_period_misaligned", "wc_gl_class_code_mismatch", "legacy_carrier_adverse_action"]


def test_explanation_cards_link_only_on_their_own_fact_and_carry_code_and_id(tmp_path):
    model = {"sections": [{"id": "l", "title": "L", "questions": [
        {"id": "L.6", "fact": "additional_remarks_text", "needs_input": True},
        {"id": "A.3g", "fact": "carrier_marketing_reason", "needs_input": True}]}]}
    out = _node(tmp_path, f"""
const m = {json.dumps(model)};
const card = (code, extra = {{}}) => ({{ code, issue_id: "iid-" + code, message: "Explain", forms: [],
  resolution: {{ mode: "narrative", ...extra }} }});
console.log(JSON.stringify({{
  coded: {json.dumps(_CODED)}.map((c) => Q.questionnaireLinkFor(m, card(c))),
  acord101: Q.questionnaireLinkFor(m, card("acord101_required", {{ add_forms: ["ACORD_101"] }})),
  acord101NoForm: Q.questionnaireLinkFor(m, card("acord101_required")),
  ownFact: Q.questionnaireLinkFor(m, card("legacy_carrier_adverse_action", {{ facts: ["carrier_marketing_reason"] }})),
  noCode: Q.questionnaireLinkFor(m, {{ resolution: {{ mode: "narrative" }}, issue_id: "rec:score:x" }}),
  facts: Q.narrativeFactsOf(card("wc_gl_class_code_mismatch")),
}}));
""")
    # A coded card never falls back to the generic remarks question: today's window.
    assert out["coded"] == [None, None, None]
    assert out["acord101"] is None and out["acord101NoForm"] is None
    assert out["facts"] == []
    # On a question of its own fact it links, with its code and id for the answer.
    assert out["ownFact"] == {"sectionId": "l", "questionId": "A.3g", "fact": "carrier_marketing_reason",
                              "code": "legacy_carrier_adverse_action", "issue_id": "iid-legacy_carrier_adverse_action"}
    # A card with no code (a score row, a dry-run row) still falls back to the remarks.
    assert out["noCode"]["questionId"] == "L.6" and out["noCode"]["code"] is None


def test_the_card_rides_on_its_answer_and_a_secure_conflict_posts_its_group(tmp_path):
    out = _node(tmp_path, """
const q = { id: "L.6", answer_type: "long_text" };
const card = { code: "umbrella_auto_period_misaligned", issue_id: "iid-1" };
console.log(JSON.stringify([
  Q.answerBody(q, "answer", "Terms differ on purpose.", { card }),
  Q.answerBody(q, "confirm", undefined, { card }),
  Q.answerBody(q, "pending", undefined, { card }),
  Q.answerBody({ id: "B.1b" }, "answer", undefined, { choice: 1 }),
  Q.answerBody({ id: "B.1b" }, "answer", undefined, { choice: -1 }),
  Q.isSecureQuestion({ conflict_values: [{ value: "**-***6789" }, { value: "**-***1234" }] }),
  Q.isSecureQuestion({ secure: true }),
  Q.isSecureQuestion({ conflict_values: [{ value: "12-3456789" }] }),
  Q.conflictGroups({ conflict_values: [{ value: "**-***6789", document: "A", choice: 0 },
                                       { value: "**-***6789", document: "B", choice: 0 },
                                       { value: "**-***1234", document: "C", choice: 1 }] }),
]));
""")
    assert out[0] == {"question_id": "L.6", "action": "answer", "value": "Terms differ on purpose.",
                      "code": "umbrella_auto_period_misaligned", "issue_id": "iid-1"}
    assert out[1] == {"question_id": "L.6", "action": "confirm", "code": "umbrella_auto_period_misaligned",
                      "issue_id": "iid-1"}
    assert out[2] == {"question_id": "L.6", "action": "pending"}          # a status mark never clears the card
    assert out[3] == {"question_id": "B.1b", "action": "answer", "choice": 1}
    assert out[4] is None                                                   # no value, no valid choice
    assert out[5:8] == [True, True, False]
    assert out[8] == [{"value": "**-***6789", "documents": ["A", "B"], "choice": 0},
                      {"value": "**-***1234", "documents": ["C"], "choice": 1}]
    page = _PAGE.read_text(encoding="utf-8")
    assert 'secure ? save("answer", undefined, c.choice) : save("answer", c.value)' in page
    assert "answerBody(q, action, value, { card, choice })" in page
    modal = _MODAL.read_text(encoding="utf-8")
    merge = modal[modal.index("const applyQuestionnaireAnswer = (data, question, card = null) => {"):]
    merge = merge[:merge.index("\n  };\n")]
    assert "card?.issue_id" in merge                 # "Open again" on a cleared row reaches that fix


def test_send_to_client_takes_the_contact_on_file(tmp_path):
    model = {"sections": [{"id": "a", "title": "A", "questions": [
        {"id": "A.1d", "fact": "contact_name", "display_value": "Erin Royal"},
        {"id": "A.1f", "fact": "contact_email", "value": "erin@example.com", "display_value": ""}]}]}
    out = _node(tmp_path, f"""
console.log(JSON.stringify([Q.clientContact({json.dumps(model)}), Q.clientContact(null)]));
""")
    assert out == [{"email": "erin@example.com", "name": "Erin Royal"}, {"email": "", "name": ""}]
    page = _PAGE.read_text(encoding="utf-8")
    assert "{ question_ids: ids, client_email: toEmail, client_name: toName }" in page
    assert 'placeholder="Client e-mail"' in page and 'placeholder="Client name"' in page


def test_a_computed_question_is_read_only(tmp_path):
    out = _node(tmp_path, """
console.log(JSON.stringify([Q.isComputed({ computed: true }), Q.isComputed({ computed: "open_items" }),
  Q.isComputed({ computed: false }), Q.isComputed({}),
  Q.canConfirm({ computed: true, state: "extracted", display_value: "3 open items" })]));
""")
    assert out == [True, True, False, False, False]
    page = _PAGE.read_text(encoding="utf-8")
    assert "const open = !computed && (" in page
    actions = page[page.index("{!computed && (\n      <div className=\"qn-actions\">"):]
    assert actions.index("qn-actions") < actions.index("LOOKS_RIGHT") < actions.index('"Not applicable"')


def test_a_fresh_approval_never_reads_edited():
    page = _PAGE.read_text(encoding="utf-8")
    approve = page[page.index("const approve = async () => {"):]
    approve = approve[:approve.index("const approvedNow")]
    assert "setText(approved);" in approve
    assert "const approvedNow = stored.state === \"approved\" && text.trim() === stored.text.trim();" in page
