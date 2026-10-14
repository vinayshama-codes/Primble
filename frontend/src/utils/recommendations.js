// The package page's Recommendations section (Choice Electric #22 / #27,
// 7 Oct 2026).
//
// Brent #22: "All of these Recommendation items should be addressable prior to
// (and independently of) the forms." #27: to-dos "earlier in the workflow" and
// "accurate requests" - 176 items was too many.
//
// Two groups, each read off a list the product already computes - never a
// second engine:
//   1. "Raise your score" - the package scorer's own Best Solutions rows
//      (`packageSqs.top_recommendations`, the rows the editor's SQS panel
//      lists), each with the fix window the server attached
//      (`resolution`, services/review_recommendations.py). No percentages
//      (owner, 1 Oct 2026).
//   2. "Your forms will need" - after forms only: the editor's needs-attention
//      Missing rows (GET /api/needs-attention). Before forms nothing about the
//      forms is listed (owner, 14 Oct 2026 - see buildRecommendations).
//
// ONE TO-DO, ONE PLACE. An item whose whole fix is already offered by a Hard
// Stop or Warning card on this screen, or by a "Key details missing" link, is
// not repeated here; a form box the "Raise your score" group already asks for
// is listed there once (with the forms that need it). "Already offered" is
// read off the fix each one opens - the same facts, the same table cells -
// never off message wording.
//
// Pure functions, no React and no DOM, so a node test runs them.

import { renderedCardRows } from "./keyDetailCards.js";
import { REC_ID_PREFIX, REC_PAGE, isRecommendationId, recChoiceIssueId, recDryIssueId, recScoreIssueId } from "./resolvedIssues.js";

export const HARD_STOPS_ROW = "hard_stops_present";

// The package pillars (calculate_package_sqs), as the editor's panel names them.
export const PILLAR_LABELS = {
  structural_completeness: "Structural Completeness",
  exposure_consistency: "Exposure Consistency",
  property_integrity: "Property Integrity",
  loss_history_alignment: "Loss History",
  umbrella_limit_adequacy: "Umbrella Adequacy",
  narrative_quality: "Narrative Quality",
};

export const pillarLabel = (key) => PILLAR_LABELS[key]
  || (key ? String(key).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "");

const NARRATIVE_FACT = "additional_remarks_text";
const clean = (x) => String(x ?? "").trim();
const num = (x) => (typeof x === "number" && Number.isFinite(x) ? x : null);

// ── What a fix asks for ──────────────────────────────────────────────────────
// A fix window's targets, as keys: `fact:<fact>` for a typed fact (and the
// remarks box), `col:<table>:<column>` for named cells of a capture table,
// `table:<table>` for a whole table.
export function fixKeys(resolution) {
  const res = resolution && typeof resolution === "object" ? resolution : null;
  if (!res) return [];
  const keys = [];
  const facts = Array.isArray(res.facts) ? res.facts.map(clean).filter(Boolean) : [];
  if (res.mode === "field") facts.forEach((f) => keys.push(`fact:${f}`));
  else if (res.mode === "narrative") keys.push(`fact:${NARRATIVE_FACT}`);
  else if (res.mode === "schedule" && clean(res.schedule_key)) {
    const sk = clean(res.schedule_key);
    const cols = Array.isArray(res.columns) ? res.columns.map(clean).filter(Boolean) : [];
    if (cols.length) cols.forEach((c) => keys.push(`col:${sk}:${c}`));
    else keys.push(`table:${sk}`);
    facts.forEach((f) => keys.push(`fact:${f}`));
  }
  return [...new Set(keys)];
}

// Is a target already offered by one of `covered`? A whole-table target is
// offered by any fix that opens that table; a named cell only by a fix naming
// that cell (a vague "complete the table" card never hides which cells the
// forms need).
function keyCovered(key, covered) {
  if (covered.has(key)) return true;
  if (key.startsWith("table:")) {
    const sk = key.slice(6);
    for (const k of covered) if (k.startsWith(`col:${sk}:`)) return true;
  }
  return false;
}

// Every target of `keys` is already offered (an empty list never is).
export function allCovered(keys, covered) {
  return keys.length > 0 && keys.every((k) => keyCovered(k, covered));
}

// What the screen already offers to fix: every Hard Stop / Warning card the
// grouped view renders, and every "Key details missing" link.
export function onScreenFixKeys(groupedIssues, keyDetails) {
  const covered = new Set();
  for (const row of renderedCardRows(groupedIssues)) fixKeys(row.resolution).forEach((k) => covered.add(k));
  const items = Array.isArray(keyDetails?.missing_items) ? keyDetails.missing_items : [];
  for (const it of items) fixKeys(it?.resolution).forEach((k) => covered.add(k));
  return covered;
}

// ── 1. Raise your score ──────────────────────────────────────────────────────
// The fix window for a row from a payload with no `resolution` (the editor's
// own score responses): the row's answer mode, without the choice list.
function fallbackResolution(row) {
  const field = clean(row?.field);
  if (!field) return null;
  if (row.answer_mode === "schedule" && clean(row.schedule_key)) return { mode: "schedule", schedule_key: clean(row.schedule_key) };
  if (row.answer_mode === "narrative") return field === NARRATIVE_FACT ? { mode: "narrative" } : { mode: "field", facts: [field] };
  if (row.answer_mode === "field") return { mode: "field", facts: [field] };
  return null;
}

// "+3 pts" / "up to +5 pts": what answering adds to the package score - the
// measured gain of the answer the row asks for when there is one, else the
// pillar's gap as a bound. Null = it adds nothing.
export function pointsFor(row) {
  const gain = num(row?.answer_gain);
  if (gain !== null) {
    const n = Math.round(gain);
    if (n <= 0) return null;
    return { points: n, exact: row.answer_gain_is_exact === true };
  }
  const avail = num(row?.points_available);
  if (avail === null || Math.round(avail) <= 0) return null;
  return { points: Math.round(avail), exact: false };
}

export const pointsText = (p) => (p ? `${p.exact ? "" : "up to "}+${p.points} pts` : "");

export function scoreItems(packageSqs, covered = new Set()) {
  const rows = Array.isArray(packageSqs?.top_recommendations) ? packageSqs.top_recommendations : [];
  const out = [];
  const seen = new Set();
  for (const row of rows) {
    if (!row || typeof row !== "object" || row.pillar === HARD_STOPS_ROW) continue;
    let resolution = row.resolution && row.resolution.mode && row.resolution.mode !== "none"
      ? row.resolution : fallbackResolution(row);
    if (!resolution) continue;                       // no fix route: not listed
    // The narrative window lists what is still missing as options (13 Oct 2026).
    if (resolution.mode === "narrative" && Array.isArray(row.narrative_gaps) && row.narrative_gaps.length) {
      resolution = { ...resolution, gaps: row.narrative_gaps };
    }
    const points = pointsFor(row);
    if (!points) continue;                           // answering adds nothing
    const keys = fixKeys(resolution);
    if (!keys.length || allCovered(keys, covered)) continue;   // a card already asks
    const id = `score:${row.pillar || ""}:${keys.join("|")}`;
    if (keys.every((k) => seen.has(k))) continue;    // two rows, one answer
    keys.forEach((k) => seen.add(k));
    out.push({
      id,
      kind: "score",
      pillar: row.pillar || "",
      title: pillarLabel(row.pillar),
      detail: clean(row.action),
      points,
      closesWith: row.closes_with || null,
      resolution,
      keys,
      alsoOnForms: [],
    });
  }
  return out;
}

// The issue-shaped object the page's fix window opens for a score item. Its
// `issue_id` is the row's own (13 Oct 2026): the server files what the fix
// changes under it, so "Open again" in the page's Resolved list takes the fix -
// and its points - back.
export function scoreFixIssue(item) {
  const what = [item?.title, item?.detail].filter(Boolean).join(": ");
  const gain = item?.points ? ` Answering adds ${pointsText(item.points)} to your score.` : "";
  return {
    message: `${what}.${gain}`.replace(/\.\./g, ".").trim(),
    code: null,
    issue_id: recScoreIssueId(item?.id),
    forms: [],
    resolution: item?.resolution || null,
    __scoreItem: true,
    __recKind: "score",
    __recItemId: item?.id || null,
    __recTitle: what,
  };
}

// ── 2. Your forms will need ──────────────────────────────────────────────────
// Before forms: the dry run's items, minus what the screen or group 1 already
// asks for. A box group 1 asks for adds its form to that row instead.
export function formItemsBeforeForms(dryRun, covered, score) {
  const forms = Array.isArray(dryRun?.forms) ? dryRun.forms : [];
  const scoreKeys = new Set((score || []).flatMap((s) => s.keys));
  const hiddenIds = new Set();
  const out = [];
  for (const form of forms) {
    const items = [];
    for (const it of (Array.isArray(form?.items) ? form.items : [])) {
      const keys = fixKeys(it?.resolution);
      if (allCovered(keys, covered)) { hiddenIds.add(it.id); continue; }
      if (allCovered(keys, scoreKeys)) {
        hiddenIds.add(it.id);
        for (const s of score || []) {
          if (keys.every((k) => s.keys.includes(k)) && form.form_label && !s.alsoOnForms.includes(form.form_label)) {
            s.alsoOnForms.push(form.form_label);
          }
        }
        continue;
      }
      items.push(it);
    }
    if (items.length) out.push({ form_id: form.form_id, form_label: form.form_label, items });
  }
  return { forms: out, hiddenIds, count: out.reduce((n, f) => n + f.items.length, 0) };
}

// After forms: each form's Missing rows from the needs-attention list (the
// producer's boxes - never the applicant's signature steps), minus what the
// screen or group 1 already asks for. The other tags are counted, not listed:
// a value to check is not a value to supply.
export function formItemsAfterForms(attention, covered, score) {
  const scoreKeys = new Set((score || []).flatMap((s) => s.keys));
  const out = [];
  for (const form of (Array.isArray(attention?.forms) ? attention.forms : [])) {
    const rows = Array.isArray(form?.rows) ? form.rows : [];
    const items = [];
    for (const r of rows) {
      if (!r || r.status !== "missing" || r.applicant_step) continue;
      const fact = clean(r.fact_key);
      if (fact) {
        const keys = [`fact:${fact}`];
        if (allCovered(keys, covered)) continue;
        if (allCovered(keys, scoreKeys)) {
          for (const s of score || []) {
            if (s.keys.includes(keys[0]) && form.form_label && !s.alsoOnForms.includes(form.form_label)) s.alsoOnForms.push(form.form_label);
          }
          continue;
        }
      }
      items.push({
        id: `${form.form_id}:${r.field}`,
        field: r.field,
        label: clean(r.label) || clean(r.field),
        what_to_do: clean(r.what_to_do),
        page: r.page ?? null,
      });
    }
    const toCheck = rows.filter((r) => r && (r.status === "verify" || r.status === "ai_held_back")).length;
    if (items.length || toCheck) out.push({ form_id: form.form_id, form_label: form.form_label, items, toCheck });
  }
  return { forms: out, count: out.reduce((n, f) => n + f.items.length, 0) };
}

// ── Form choices (before forms, 13 Oct 2026) ────────────────────────────────
// A check whose only fix is choosing a form ("a certificate holder was found
// but ACORD 25 is not in the selected forms") is not a gap in the submission:
// the score leaves it out before forms and the review lists it here, where
// forms are chosen (`grouped_issues.form_choices`). `forms` are the forms it
// asks for that are NOT ticked yet; a choice whose forms are all ticked stays
// listed as done and is not counted.
export function formChoiceItems(groupedIssues, tickedFormIds = []) {
  const ticked = new Set((tickedFormIds || []).filter(Boolean));
  const out = [];
  const seen = new Set();
  for (const c of (Array.isArray(groupedIssues?.form_choices) ? groupedIssues.form_choices : [])) {
    if (!c || typeof c !== "object") continue;
    const asked = (Array.isArray(c.resolution?.add_forms) ? c.resolution.add_forms : []).map(clean).filter(Boolean);
    const id = clean(c.issue_id) || `${clean(c.code)}:${clean(c.message)}`;
    if (!asked.length || seen.has(id)) continue;
    seen.add(id);
    out.push({ id, code: clean(c.code), message: clean(c.message), asked,
               forms: asked.filter((f) => !ticked.has(f)), done: asked.every((f) => ticked.has(f)) });
  }
  return out;
}

// ── The whole section ────────────────────────────────────────────────────────
// `formsExist`: forms are generated (group 2 reads `attention`); otherwise
// group 2 reads `dryRun`. `count` = the unique items the section lists - the
// number the Overview's link prints.
// A form the documents call for that is not in the package (the documents
// door's `document_form_offers`: "Your documents now show Commercial Auto.
// ACORD 127 is not in this package."), one per form, after forms only (owner,
// 14 Oct 2026: "i need the Add form thing in recommendations").
export function offerItems(formOffers) {
  const out = [];
  const seen = new Set();
  for (const o of (Array.isArray(formOffers) ? formOffers : [])) {
    const id = clean(o && o.form_id);
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push({ ...o, form_id: id });
  }
  return out;
}

// The last points after forms are the Form Fill Rate (14 Oct 2026, owner: "package
// score is 99/100 and I can't see anything to make it 100"): AI values on the
// forms nobody confirmed (0.85 / 0.50 against a confirmed 1.00). The scorer's row
// for it has no fix window, so `scoreItems` never listed it. Its fix is each
// form's "Confirm all"; this row opens the form with the most Please verify
// values. Listed only while the needs-attention list has some - a fill rate held
// by anything else is not a promise this row can keep.
function verifyCounts(attention) {
  const out = [];
  for (const f of (Array.isArray(attention?.forms) ? attention.forms : [])) {
    const n = (Array.isArray(f?.rows) ? f.rows : []).filter((r) => r && r.status === "verify").length;
    if (n && f.form_id) out.push({ form_id: f.form_id, n });
  }
  return out.sort((a, b) => b.n - a.n);
}

function fillPoints(packageSqs, fill) {
  const rows = Array.isArray(packageSqs?.top_recommendations) ? packageSqs.top_recommendations : [];
  const own = rows.find((r) => r && r.pillar === "structural_completeness" && !clean(r.field)
    && !(r.resolution && r.resolution.mode && r.resolution.mode !== "none"));
  if (own) return pointsFor(own);
  // No scorer row (a Tier 1 / Tier 2 gap took it): the fill slice's own bound.
  const w = packageSqs?.weights_used || {};
  const pillars = packageSqs?.pillars || {};
  let total = 0;
  for (const [k, v] of Object.entries(pillars)) {
    const sc = v && typeof v === "object" ? num(v.score) : num(v);
    if (sc !== null && num(w[k]) !== null) total += w[k];
  }
  const fw = num(packageSqs?.category_breakdown?.structural_completeness?.fill?.weight);
  const sw = num(w.structural_completeness);
  if (!total || fw === null || sw === null) return null;
  return pointsFor({ points_available: ((100 - fill) * fw * sw) / total });
}

export function fillRateItem(packageSqs, attention) {
  const fill = num(packageSqs?.category_breakdown?.structural_completeness?.fill?.score);
  if (fill === null || fill >= 100) return null;
  const forms = verifyCounts(attention);
  if (!forms.length) return null;
  const points = fillPoints(packageSqs, fill);
  if (!points) return null;
  const n = forms.length;
  return {
    id: "score:fill", kind: "score", pillar: "structural_completeness",
    title: pillarLabel("structural_completeness"),
    detail: `Confirm the Please verify values on ${n} form${n === 1 ? "" : "s"} (Form Fill Rate ${Math.round(fill)}%). Each form's side panel has "Confirm all".`,
    points,
    closesWith: null,
    resolution: { mode: "forms", form_id: forms[0].form_id, forms: forms.map((f) => f.form_id) },
    keys: ["forms:verify"], alsoOnForms: [],
  };
}

// The Overview's "last points are on your forms" notice (owner, 14 Oct 2026): after
// forms, the review page can be finished - nothing open on it, no cap, no "Raise
// your score" row it can fix itself - while the score is under 100 because AI
// values on the forms wait to be confirmed. Null whenever the review page itself
// can still raise the score, or the forms cannot (no Please verify values).
// `openOnPage`: what the page still lists (documents, values to confirm, hard
// stops, warnings, key details).
export function scoreLeftOnForms({ packageSqs, model, openOnPage = 0 } = {}) {
  const score = num(packageSqs?.package_sqs_score);
  if (score === null || score >= 100 || Number(openOnPage) > 0) return null;
  if (packageSqs?.cap_applied || packageSqs?.cap_reason) return null;
  const items = Array.isArray(model?.score) ? model.score : [];
  if (items.some((s) => s?.resolution?.mode !== "forms")) return null;
  const row = items.find((s) => s?.resolution?.mode === "forms");
  if (!row) return null;
  const forms = Array.isArray(row.resolution.forms) ? row.resolution.forms : [];
  // "To reach 100" only when everything but the forms is already full marks.
  const reaches100 = (num(packageSqs?.without_forms?.score) ?? 0) >= 100;
  return { score, points: row.points || null, formId: row.resolution.form_id || null, formCount: forms.length, reaches100, item: row };
}

export function buildRecommendations({ packageSqs, groupedIssues, keyDetails, attention, formsExist, formOffers } = {}) {
  const covered = onScreenFixKeys(groupedIssues, keyDetails);
  const score = scoreItems(packageSqs, covered);
  const fillRow = formsExist ? fillRateItem(packageSqs, attention) : null;
  if (fillRow) score.push(fillRow);
  // BEFORE FORMS THIS SECTION IS THE SCORE ONLY (owner, 14 Oct 2026: "we are
  // trying to make SQS independent of forms ... this section does not increase
  // score so why show it before even generating the forms"). What a form will
  // need - the dry run's boxes, the per-form cards, a form to add - moves no
  // score; it is listed after generation as each form's Missing rows. Reverses
  // the 7 Oct pre-form group (Brent #22's per-form cards now wait for the forms).
  const forms = formsExist
    ? { ...formItemsAfterForms(attention, covered, score), source: "attention", hiddenIds: new Set() }
    : { forms: [], count: 0, hiddenIds: new Set(), source: "none" };
  const formsReady = formsExist ? !!attention : true;
  const formsCount = formsExist && formsReady ? forms.count : 0;
  const offers = formsExist ? offerItems(formOffers) : [];
  return { score, forms, formsReady, offers, formChoices: [], choicesOpen: 0,
           count: score.length + formsCount + offers.length };
}

export const recommendationsText = (n) => `${n} recommendation${n === 1 ? "" : "s"}`;

// ── Resolved (owner, 13 Oct 2026) ───────────────────────────────────────────
// "a resolved section similar to hard stops and warnings ... they can be
// reopened and score goes back". A row fixed through its own "Open to fix"
// leaves its list and sits under a collapsed "Resolved (n)" with "Open again"
// (ids and page: utils/resolvedIssues). Only a fix made from the row's own
// window is listed - the server holds that fix's changes under the row's id, so
// "Open again" can always take it back. A row that vanished because another
// fix answered it has nothing of its own to take back.

// Did a save fix its row? "fixed" | "open" | "unknown".
//   score - fixed once the package scorer no longer asks for it, read with
//           NOTHING covered: a row now hidden behind a Hard Stop / Warning card
//           asking for the same value is still open, never fixed.
//   dry   - fixed once a FINISHED check of its form no longer lists it; a check
//           still running, or one that did not look at that form, is "unknown"
//           (the caller judges it on the next one).
export function recommendationFixState(kind, itemId, { packageSqs, dryRun, formId } = {}) {
  if (!itemId) return "unknown";
  if (kind === "score") {
    if (!packageSqs || typeof packageSqs !== "object") return "unknown";
    return scoreItems(packageSqs, new Set()).some((s) => s.id === itemId) ? "open" : "fixed";
  }
  if (kind === "dry") {
    if (!dryRun || dryRun.status !== "ready") return "unknown";
    const forms = Array.isArray(dryRun.forms) ? dryRun.forms : [];
    if (forms.some((f) => (Array.isArray(f?.items) ? f.items : []).some((it) => it && it.id === itemId))) return "open";
    const checked = (Array.isArray(dryRun.checked_forms) ? dryRun.checked_forms : []).map((f) => f && f.form_id);
    return formId && checked.includes(formId) ? "fixed" : "unknown";
  }
  return "unknown";
}

// Every row the scorer and the form check still raise, by its fix id - listed,
// or hidden behind a card that asks for the same value. A stored "resolved"
// row whose id is live again is open, not Resolved.
export function liveRecommendationIds({ packageSqs, dryRun } = {}) {
  const ids = new Set();
  for (const s of scoreItems(packageSqs, new Set())) ids.add(recScoreIssueId(s.id));
  for (const f of (Array.isArray(dryRun?.forms) ? dryRun.forms : [])) {
    for (const it of (Array.isArray(f?.items) ? f.items : [])) if (it && it.id) ids.add(recDryIssueId(it.id));
  }
  return ids;
}

// The page's Resolved rows: fixed rows the scorer and the form check no longer
// raise (rebuilt from their stored status, oldest first), then the form choices
// already ticked ("Added" - "Open again" unticks them).
// [{ iid, kind: "score" | "dry" | "choice", status: "resolved" | "added",
//    title, forms, asked?, message? }]
export function recommendationResolvedRows({ statusEntries = [], liveIds = new Set(), formChoices = [] } = {}) {
  const out = [];
  const seen = new Set();
  for (const [iid, st] of (Array.isArray(statusEntries) ? statusEntries : [])) {
    if (!isRecommendationId(iid) || !st || st.status !== "resolved" || !clean(st.message)) continue;
    if (liveIds.has(iid) || seen.has(iid)) continue;
    seen.add(iid);
    out.push({
      iid,
      kind: String(iid).startsWith(`${REC_ID_PREFIX}dry:`) ? "dry" : "score",
      status: "resolved",
      title: clean(st.message),
      forms: st.form_id ? [st.form_id] : [],
    });
  }
  for (const c of (Array.isArray(formChoices) ? formChoices : [])) {
    if (!c || !c.done) continue;
    const iid = recChoiceIssueId(c.id);
    if (!iid || seen.has(iid)) continue;
    seen.add(iid);
    out.push({ iid, kind: "choice", status: "added", title: "", forms: [...(c.asked || [])], asked: [...(c.asked || [])], message: c.message || "" });
  }
  return out;
}

export { REC_PAGE };

// What the "to consider" count is made of (owner, 13 Oct 2026: "2 to consider" with
// one card in view). One group: its own words; both: both, named.
export function considerText(model) {
  const score = Array.isArray(model?.score) ? model.score.length : 0;
  const forms = (Number(model?.forms?.count) || 0) + (Number(model?.choicesOpen) || 0);
  const offers = Array.isArray(model?.offers) ? model.offers.length : 0;
  const parts = [];
  if (score) parts.push(`${score} to raise your score`);
  if (offers) parts.push(`${offers} form${offers === 1 ? "" : "s"} to add`);
  if (forms) parts.push(`${forms} your forms need`);
  return parts.length ? parts.join(" · ") : `${Number(model?.count) || 0} to consider`;
}
