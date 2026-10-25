// questionnaire.js - the review's Questionnaire page (owner, 23 Oct 2026).
//
// The page is the LAST review page before form selection: every question the
// backend sends (GET /api/questionnaire/{session_id}), prefilled from the
// documents, with its state, its source and its actions. This file holds the
// page's rules - the state tag a row prints, the "Show only what needs me"
// filter, the count line, the deep link from a narrative card to its question
// and the body of an answer - so the page, the rail badge and AcordModal's
// deep link read one answer. The backend decides every state; nothing here
// infers one.
//
// Pure: no React, no fetch.

// The remarks box every "Explain via ACORD 101" window writes to. A narrative
// card that names no fact of its own matches a question on this fact.
export const NARRATIVE_FACT = "additional_remarks_text";

// The page's copy, in one place (no em-dashes: CLAUDE.md UI rule).
export const QUESTIONNAIRE_TITLE = "Questionnaire";
export const QUESTIONNAIRE_DESC = "Check what we found in your documents and answer what is missing. None of it stops you.";
export const SHOW_ONLY_NEEDS = "Show only what needs me";
export const LOOKS_RIGHT = "Looks right";
export const SEND_TO_CLIENT = "Send to client";
export const CREATE_NARRATIVE = "Create carrier narrative";
export const APPROVE_NARRATIVE = "Approve for ACORD 101";

// state -> { text, tone }. tone picks the tag colour on the page.
export const STATE_TAGS = {
  extracted: { text: "From your documents", tone: "blue" },
  producer_confirmed: { text: "Confirmed", tone: "green" },
  insured_confirmed: { text: "Confirmed", tone: "green" },
  unverified: { text: "Needs confirmation", tone: "amber" },
  conflicting: { text: "Conflicting", tone: "red" },
  not_applicable: { text: "Not applicable", tone: "gray" },
  missing: { text: "Missing", tone: "pink" },
  unknown: { text: "Unknown", tone: "gray" },
  pending: { text: "Pending", tone: "gray" },
};

// Who confirmed it, beside "Confirmed".
const CONFIRMED_BY = { producer_confirmed: "by you", insured_confirmed: "by the client" };

export function stateTag(state) {
  const tag = STATE_TAGS[state];
  if (!tag) return null;
  return { ...tag, by: CONFIRMED_BY[state] || null };
}

const clean = (x) => String(x ?? "").trim();
const list = (x) => (Array.isArray(x) ? x : []);

// The sections the payload carries, each with its question list (a section
// with no list gets an empty one; anything not an object is dropped).
export function sectionsOf(model) {
  return list(model?.sections)
    .filter((s) => s && typeof s === "object" && clean(s.id))
    .map((s) => ({ ...s, questions: list(s.questions).filter((q) => q && typeof q === "object" && clean(q.id)) }));
}

// The rows a section shows: every question, or only what needs the producer.
// A question being saved, or the one a deep link opened, stays on screen even
// once it no longer needs input, so it never vanishes under the cursor.
export function visibleQuestions(section, onlyNeeds, keep = new Set()) {
  const qs = list(section?.questions);
  if (!onlyNeeds) return qs;
  return qs.filter((q) => q.needs_input === true || keep.has(q.id));
}

// The counts: the payload's own when it sends them, else counted from the rows.
export function countsOf(model) {
  const c = model?.counts;
  if (c && Number.isFinite(Number(c.needs_input)) && Number.isFinite(Number(c.total))) {
    return { needs_input: Math.max(0, Number(c.needs_input)), total: Math.max(0, Number(c.total)) };
  }
  let total = 0;
  let needs = 0;
  for (const s of sectionsOf(model)) {
    for (const q of s.questions) {
      total += 1;
      if (q.needs_input === true) needs += 1;
    }
  }
  return { needs_input: needs, total };
}

const qWord = (n) => `${n} question${n === 1 ? "" : "s"}`;

// The line under the filter: what is left and what is there.
export function countLine(counts) {
  const n = Number(counts?.needs_input) || 0;
  const t = Number(counts?.total) || 0;
  if (!t) return "No questions for this package.";
  if (!n) return `All ${qWord(t)} answered or confirmed.`;
  return `${n} of ${qWord(t)} need${n === 1 ? "s" : ""} you.`;
}

// The rail's line under "Questionnaire", and its badge (a number, "done" for
// the green tick, or null while nothing is known).
export function railSub(model, error = false) {
  if (!model) return error ? "Not available" : "Loading...";
  const { needs_input: n, total: t } = countsOf(model);
  if (!t) return "No questions";
  if (!n) return "All answered";
  return `${n} need${n === 1 ? "s" : ""} you`;
}

export function railBadge(model) {
  if (!model) return null;
  const { needs_input: n, total: t } = countsOf(model);
  if (n > 0) return n;
  return t > 0 ? "done" : null;
}

// One source as the page prints it: "Package Policy.pdf, page 3".
export function sourceText(src) {
  if (!src || typeof src !== "object") return "";
  const doc = clean(src.document);
  const page = src.page === 0 || src.page ? clean(src.page) : "";
  if (doc && page) return `${doc}, page ${page}`;
  if (doc) return doc;
  return page ? `Page ${page}` : "";
}

// Every distinct source line of a question, in the payload's order.
export function sourceLines(q) {
  const out = [];
  for (const s of list(q?.sources)) {
    const t = sourceText(s);
    if (t && !out.includes(t)) out.push(t);
  }
  return out;
}

// The values a conflicting question offers, one per conflict GROUP (the Data
// Consistency picker's groups: one value, every document printing it), each
// with its group index - the `choice` a "Use this" posts. A payload's own
// `choice` index wins; without one, an entry repeating the value before it
// is the same group.
export function conflictGroups(q) {
  const out = [];
  let prev = null;
  for (const c of list(q?.conflict_values)) {
    if (!c || typeof c !== "object") continue;
    const value = clean(c.value);
    const doc = clean(c.document);
    const own = Number.isInteger(c.choice) ? c.choice : null;
    const same = prev && (own !== null ? prev.choice === own : prev.value === value);
    if (same) {
      if (doc && !prev.documents.includes(doc)) prev.documents.push(doc);
      continue;
    }
    prev = { value, documents: doc ? [doc] : [], choice: own !== null ? own : out.length };
    out.push(prev);
  }
  return out.filter((g) => g.value);
}

// A secure question (the FEIN): its values arrive masked, so a "Use this"
// names the group, never the masked text.
const MASKED_RE = /^(\*\*-\*\*\*\d{4}|\*{4})$/;
export function isSecureQuestion(q) {
  if (!q) return false;
  if (q.secure === true) return true;
  const vals = list(q.conflict_values).map((c) => clean(c?.value)).filter(Boolean);
  return vals.length > 0 && vals.every((v) => MASKED_RE.test(v));
}

// A question the page builds itself (open items, the umbrella's underlying
// list): read-only, no answer and no status buttons.
export function isComputed(q) {
  return !!q && (q.computed === true || (typeof q.computed === "string" && clean(q.computed) !== ""));
}

// A TABLE answer reloads the whole page: several questions are views of one
// table, and a view still on screen must never post its old rows.
export function reloadsPage(question) {
  return !!question && (question.answer_type === "table" || clean(question.table_key) !== "");
}

// Who "Send to client" writes to, prefilled from the contact questions
// (A.1f e-mail, A.1d name; by fact when the ids move).
export function clientContact(model) {
  const all = sectionsOf(model).flatMap((s) => s.questions);
  const pick = (id, fact) => {
    const q = all.find((x) => x.id === id) || all.find((x) => clean(x.fact) === fact);
    if (!q) return "";
    const shown = clean(q.display_value);
    if (shown) return shown;
    return q.value !== null && typeof q.value !== "object" ? clean(q.value) : "";
  };
  return { email: pick("A.1f", "contact_email"), name: pick("A.1d", "contact_name") };
}

// A choice list as [{ value, label }] - strings or objects alike.
export function optionsOf(q) {
  return list(q?.options)
    .map((o) => (o && typeof o === "object"
      ? { value: clean(o.value ?? o.label), label: clean(o.label ?? o.value) }
      : { value: clean(o), label: clean(o) }))
    .filter((o) => o.value);
}

// The value an answer box starts from: the prefilled value as text.
export function draftOf(q) {
  if (!q) return "";
  if (q.answer_type === "table") return list(q.value).length ? q.value : list(q?.table?.rows);
  const v = q.value;
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return clean(q.display_value);
  return String(v);
}

// The value a "Looks right" can confirm: something must be on file.
export function canConfirm(q) {
  if (!q) return false;
  if (isComputed(q) || ["producer_confirmed", "insured_confirmed", "conflicting"].includes(q.state)) return false;
  if (q.answer_type === "table") return list(q.value).length > 0 || list(q?.table?.rows).length > 0;
  return clean(q.display_value) !== "" || (q.value !== null && q.value !== undefined && clean(q.value) !== "");
}

// The POST body of one action. `answer` sends the typed value - or, for a
// secure question's conflict, the group `choice`; the others send no value.
// `card`: the explanation card a deep link opened this question from
// ({ code, issue_id }) - its answer and "Looks right" carry them, so the card's
// warning clears and the fix's undo receipt is filed under its id. Null when
// an answer has nothing in it.
export const ACTIONS = ["answer", "confirm", "unknown", "pending", "not_applicable"];

export function answerBody(q, action, value, { card = null, choice = null } = {}) {
  if (!q || !clean(q.id) || !ACTIONS.includes(action)) return null;
  const ids = (action === "answer" || action === "confirm") && card ? {
    ...(clean(card.code) ? { code: clean(card.code) } : {}),
    ...(clean(card.issue_id) ? { issue_id: clean(card.issue_id) } : {}),
  } : {};
  if (action !== "answer") return { question_id: q.id, action, ...ids };
  if (Number.isInteger(choice) && choice >= 0) return { question_id: q.id, action, choice, ...ids };
  if (q.answer_type === "table") {
    const rows = list(value);
    return { question_id: q.id, action, value: rows, ...ids };
  }
  const v = clean(value);
  if (!v) return null;
  return { question_id: q.id, action, value: v, ...ids };
}

// The page after one saved answer: the question replaced where it stands and
// the counts taken from the reply (else re-counted).
export function withQuestion(model, question, counts) {
  if (!model || !question || !clean(question.id)) return model;
  const sections = sectionsOf(model).map((s) => ({
    ...s,
    questions: s.questions.map((q) => (q.id === question.id ? question : q)),
  }));
  const next = { ...model, sections };
  const c = counts && Number.isFinite(Number(counts.needs_input)) && Number.isFinite(Number(counts.total))
    ? { needs_input: Number(counts.needs_input), total: Number(counts.total) }
    : null;
  next.counts = c || countsOf({ sections });
  return next;
}

// The questions the client can confirm, in page order.
export function insuredConfirmable(model) {
  const out = [];
  for (const s of sectionsOf(model)) for (const q of s.questions) if (q.insured_confirmable === true) out.push(q);
  return out;
}

// ── The deep link from a narrative card ──────────────────────────────────────
// The facts a narrative card (a fix window in mode "narrative") is about, most
// specific first: the card's own fact, the facts its window names, the topics
// its window lists (a gap key "topic:operations" and its bare "operations"),
// then - for a card with no rule code only - the remarks box itself. A coded
// explanation card is never sent to the generic remarks question: only a
// question on its own fact takes it (else its window opens, as before).
export function narrativeFactsOf(issue) {
  const res = issue?.resolution;
  if (!res || res.mode !== "narrative") return [];
  const out = [];
  const add = (f) => { const v = clean(f); if (v && !out.includes(v)) out.push(v); };
  add(issue.fact);
  add(issue.fact_key);
  add(res.fact);
  list(res.facts).forEach(add);
  add(issue.field);
  // A window asking for ONE topic leads to that topic's question. A window
  // asking for one narrative that covers SEVERAL topics (the Narrative Quality
  // row) keeps its own window, which ticks each topic the text covers: no one
  // question - and never the first topic's ("Years in business", 23 Oct) -
  // stands for it.
  const gaps = list(res.gaps).map((g) => clean(g?.key)).filter(Boolean);
  if (gaps.length > 1) return [];
  for (const key of gaps) {
    add(key);
    if (key.includes(":")) add(key.slice(key.indexOf(":") + 1));
  }
  if (!clean(issue.code)) add(NARRATIVE_FACT);
  return out;
}

// The question a list of facts leads to: { sectionId, questionId, fact } for
// the first fact some question asks, or null.
export function questionForFacts(model, facts) {
  const want = list(facts).map(clean).filter(Boolean);
  if (!want.length) return null;
  const sections = sectionsOf(model);
  for (const f of want) {
    for (const s of sections) {
      const q = s.questions.find((x) => clean(x.fact) === f);
      if (q) return { sectionId: s.id, questionId: q.id, fact: f };
    }
  }
  return null;
}

// The deep link for one fix window, or null to keep today's window: only a
// narrative window, and never one that also offers to add a form (ACORD 101's
// "Add ACORD 101") or was opened to add one. The link carries the card's rule
// code and issue id for the answer (`answerBody`'s `card`).
export function questionnaireLinkFor(model, issue) {
  if (!issue || issue.__addForm) return null;
  if (list(issue.resolution?.add_forms).some((f) => clean(f))) return null;
  const hit = questionForFacts(model, narrativeFactsOf(issue));
  if (!hit) return null;
  return { ...hit, code: clean(issue.code) || null, issue_id: clean(issue.issue_id) || null };
}

// A DOM id for a question row (ids may hold any character).
export function questionDomId(id) {
  return `qn-q-${clean(id).replace(/[^A-Za-z0-9_-]/g, "_")}`;
}

// ── The narrative ────────────────────────────────────────────────────────────
export function narrativeOf(model) {
  const n = model?.narrative;
  const state = ["none", "draft", "approved"].includes(n?.state) ? n.state : "none";
  return { state, text: typeof n?.text === "string" ? n.text : "", approved_at: n?.approved_at || null };
}

// "Approved for ACORD 101 on 23 Oct 2026, 10:42" (local time); without a time,
// "Approved for ACORD 101".
export function approvedText(approvedAt) {
  const base = "Approved for ACORD 101";
  if (!approvedAt) return base;
  const d = new Date(approvedAt);
  if (Number.isNaN(d.getTime())) return base;
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${base} on ${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()}, ${hh}:${mm}`;
}

// The error a reply carries, as one short sentence.
export function replyError(data, fallback = "Could not save. Try again.") {
  const e = data && (data.error || data.detail);
  if (typeof e === "string" && e.trim()) return e.trim();
  if (e && typeof e === "object" && typeof e.message === "string") return e.message;
  return fallback;
}
