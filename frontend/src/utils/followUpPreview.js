// followUpPreview.js - the follow-up questions an answer raises, shown inside
// the fix window as soon as the answer is chosen (owner, 24 Oct 2026).
//
// The server decides what follows (POST /api/review/preview-answer,
// backend services/answer_preview.py: the review page read on an in-memory copy
// with the answer written). This file only asks it, keeps the latest reply, and
// names the id each follow-up is saved under so its Resolved / Open again work
// like the row's own window.

import { fixKeys } from "./recommendations.js";
import { keyDetailIssueId, recScoreIssueId } from "./resolvedIssues.js";
import { isAmountBoxConvention, normalizeAmountOrPercent, normalizeCurrency, percentStatement } from "./answerFormats.js";

const clean = (s) => String(s ?? "").trim();

// The answers worth previewing: filled, distinct, in a stable order.
export function previewAnswers(values, facts) {
  const out = [];
  for (const f of facts || []) {
    const v = clean((values || {})[f]);
    if (f && v && v !== "Other") out.push({ field: f, value: v });
  }
  return out;
}

// TYPED ANSWERS (Z39 lane G): a typed box is previewed only once its value
// reads as a whole answer of the box's kind (`control`, the server's
// answer_options.control_for) - never a half-typed date or amount. The window
// asks on every change; the previewer's 350 ms debounce and "same answer,
// nothing to ask" mean a pause on a complete value asks once.
const DATE_US = /^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$/;
const DATE_ISO = /^(\d{4})-(\d{1,2})-(\d{1,2})$/;
const validDay = (y, m, d) => {
  if (!(m >= 1 && m <= 12 && d >= 1 && y >= 1900 && y <= 2100)) return false;
  return d <= new Date(Date.UTC(y, m, 0)).getUTCDate();
};
// An amount still being typed: "1," / "$1." / "$2,5" (a thousands group not yet three digits).
const halfTypedAmount = (s) => /[,.]$/.test(s) || /\d,\d{1,2}(?!\d)/.test(s);
export function typedAnswerComplete(value, control, left = false) {
  const s = clean(value);
  if (!s || s === "Other") return false;
  // Leaving the box ends the answer: a one-letter code or word ("A", "Y") is
  // whole then, though while typing it cannot be told from a word in progress.
  if (left && (!control || control === "text" || control === "code")) return true;
  switch (control) {
    case "date": {
      let m = DATE_US.exec(s);
      if (m) return validDay(+m[3], +m[1], +m[2]);
      m = DATE_ISO.exec(s);
      return !!m && validDay(+m[1], +m[2], +m[3]);
    }
    case "number":
      return /^(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$/.test(s) || isAmountBoxConvention(s);
    case "percent": {
      const p = percentStatement(/%|percent/i.test(s) ? s : `${s}%`);
      return !!p && p.plain;
    }
    case "currency":
      return (!halfTypedAmount(s) && !!normalizeCurrency(s)) || isAmountBoxConvention(s);
    case "amount_or_percent":
      return (!halfTypedAmount(s) && !!normalizeAmountOrPercent(s)) || isAmountBoxConvention(s);
    case "code":
      // Phones and policy numbers carry spaces / parentheses: "(303) 555-1212".
      return /^[A-Za-z0-9(][A-Za-z0-9 ().\/-]*[A-Za-z0-9)]$/.test(s);
    default:
      return s.length >= 2;
  }
}

// The answers to preview: chosen values as they are, typed ones only when
// complete. `typed(fact)` -> true when the fact's box is typed (no list, or
// "Other" chosen); `controls` the window's resolution.controls.
export function previewableAnswers(values, facts, controls, typed, left = false) {
  const ok = (facts || []).filter((f) => !typed || !typed(f)
    || typedAnswerComplete((values || {})[f], (((controls || {})[f]) || {}).control
      || ((((controls || {})[f]) || {}).options ? "text" : undefined), left));
  return previewAnswers(values, ok);
}

export const answersKey = (answers) => JSON.stringify((answers || []).map((a) => [a.field, a.value]));

// The id the page files this follow-up's fix under - the same id its own row
// uses (recommendations.scoreItems / resolvedIssues), so the row it becomes on
// the page shows the save as Resolved, with Open again.
export function followUpIssueId(fu) {
  if (!fu) return null;
  if (fu.source === "rec") {
    const res = fu.resolution || {};
    const keys = Array.isArray(fu.keys) && fu.keys.length ? fu.keys : fixKeys(res);
    const derived = Array.isArray(res.derives) && res.derives.length && clean(fu.field);
    return recScoreIssueId(`score:${fu.pillar || ""}:${derived ? `fact:${clean(fu.field)}` : keys.join("|")}`);
  }
  if (fu.source === "detail") return keyDetailIssueId(fu.label);
  if (fu.source === "card") return fu.issue_id || null;
  return null;
}

// Follow-ups by kind, each once.
export function splitFollowUps(list) {
  const seen = new Set();
  const out = { field: [], open: [], document: [], warning: [] };
  for (const fu of Array.isArray(list) ? list : []) {
    if (!fu || !fu.id || seen.has(fu.id)) continue;
    seen.add(fu.id);
    if (fu.kind === "field") out.field.push(fu);
    else if (fu.kind === "document") out.document.push(fu);
    else if (fu.kind === "schedule" || fu.kind === "narrative") out.open.push(fu);
    // A warning this answer raises, fixed in this window (24 Oct 2026) - shown, never asked.
    else if (fu.kind === "warning") out.warning.push(fu);
  }
  return out;
}

// The typed follow-up answers to save: [{ fu, field, value }], blanks left out.
export function followUpSaves(fieldFollowUps, values) {
  const out = [];
  for (const fu of fieldFollowUps || []) {
    for (const f of (fu.resolution && fu.resolution.facts) || []) {
      const v = clean((values || {})[f]);
      if (v && v !== "Other") out.push({ fu, field: f, value: v });
    }
  }
  return out;
}

// A debounced asker that keeps only the LATEST request's reply: a slower reply
// to an earlier answer never replaces the follow-ups of the answer now chosen.
// `fetchFn(answers, { signal }) -> Promise<follow_ups[]>`; `onResult(list)`.
// Z38 lane F (speed): a superseded request is aborted; `prefetch(list)` reads
// the follow-ups of each likely answer ahead, one at a time, so picking one is
// instant; a pick whose reply is already on its way waits for it, never asks twice.
export function createPreviewer(fetchFn, onResult, { delay = 350, timer = { set: setTimeout, clear: clearTimeout } } = {}) {
  let seq = 0;
  let pending = null;
  let lastKey = null;
  let ctrl = null;                                     // the live (non-prefetch) request
  // A cancel ends what is in flight, never the previewer: React StrictMode runs
  // the unmount cleanup once on a live window (dev), and a permanent stop left
  // every later pick showing no follow-ups.
  let gen = 0;
  const cache = new Map();
  const inflight = new Map();                          // key -> Promise<list>
  const makeCtrl = () => (typeof AbortController === 'function' ? new AbortController() : null);
  const ask = (key, answers, c) => {
    if (inflight.has(key)) return inflight.get(key);
    const p = (async () => {
      let list = [];
      try { list = (await fetchFn(answers, { signal: c ? c.signal : undefined })) || []; }
      catch { inflight.delete(key); return null; }     // aborted / failed: nothing cached
      cache.set(key, list);
      inflight.delete(key);
      return list;
    })();
    inflight.set(key, p);
    return p;
  };
  const deliver = (my, list) => { if (my === seq && list) onResult(list); };
  return {
    request(answers) {
      const key = answersKey(answers);
      if (key === lastKey) return;                    // same answer again: nothing to ask
      lastKey = key;
      const my = ++seq;
      if (pending) timer.clear(pending);
      pending = null;
      if (ctrl) { try { ctrl.abort(); } catch { /* already done */ } ctrl = null; }
      if (!answers || !answers.length) { onResult([]); return; }
      if (cache.has(key)) { onResult(cache.get(key)); return; }
      onResult([]);                                    // the old answer's follow-ups go at once
      if (inflight.has(key)) { inflight.get(key).then((list) => deliver(my, list || [])); return; }
      pending = timer.set(() => {
        pending = null;
        const c = makeCtrl();
        ctrl = c;
        ask(key, answers, c).then((list) => { if (ctrl === c) ctrl = null; deliver(my, list || []); });
      }, delay);
    },
    async prefetch(answerLists) {
      const g = gen;
      for (const answers of answerLists || []) {
        if (g !== gen) return;
        if (!answers || !answers.length) continue;
        const key = answersKey(answers);
        if (cache.has(key)) continue;
        await ask(key, answers, null);
      }
    },
    cancel() {
      seq += 1; gen += 1; lastKey = null;
      if (pending) timer.clear(pending);
      pending = null;
      if (ctrl) { try { ctrl.abort(); } catch { /* already done */ } ctrl = null; }
    },
  };
}

// The answers worth reading ahead when the window opens: a ONE-question window
// whose question offers a short choice list (Z38 lane F) - each choice as the
// pick would send it. Longer lists and free text are read when chosen.
export const PREFETCH_MAX_CHOICES = 4;
export function prefetchAnswerLists(fieldFacts, controls) {
  const facts = (fieldFacts || []).filter(Boolean);
  if (facts.length !== 1) return [];
  const fact = facts[0];
  const opts = ((controls || {})[fact] || {}).options;
  if (!Array.isArray(opts)) return [];
  const choices = [...new Set(opts.map(clean).filter((o) => o && o !== 'Other'))];
  if (!choices.length || choices.length > PREFETCH_MAX_CHOICES) return [];
  return choices.map((v) => previewAnswers({ [fact]: v }, [fact]));
}

export async function fetchFollowUps(apiBase, sessionId, answers, shownFields, { signal } = {}) {
  const res = await fetch(`${apiBase}/api/review/preview-answer`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, answers, shown_fields: shownFields || [] }),
    signal,
  });
  if (!res.ok) return [];
  const data = await res.json().catch(() => null);
  return Array.isArray(data?.follow_ups) ? data.follow_ups : [];
}

// The window opening: the server reads the page as it stands now, so the first
// pick reads only the page WITH the answer. Never throws.
export async function warmFollowUps(apiBase, sessionId) {
  try {
    await fetch(`${apiBase}/api/review/preview-answer`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, warm: true }),
    });
  } catch { /* a warm-up only */ }
}

// The fix-window issue a schedule / narrative follow-up opens - the same shape
// its own row's "Open to fix" builds, so the save is filed under the row's id.
export function followUpIssue(fu) {
  const iid = followUpIssueId(fu);
  const base = { message: clean(fu?.message || fu?.label), code: fu?.code ?? null, issue_id: iid,
                 forms: [], resolution: fu?.resolution || null };
  if (fu?.source === "rec") {
    return { ...base, __scoreItem: true, __recKind: "score",
             __recItemId: iid ? iid.slice("rec:".length) : null, __recTitle: clean(fu.label) };
  }
  if (fu?.source === "detail") return { ...base, __keyDetail: true, __keyDetailLabel: fu.label || null };
  return base;
}
