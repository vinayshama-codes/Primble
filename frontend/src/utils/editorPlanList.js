// THE EDITOR'S SIDE PANEL AFTER FORMS: EVERY ITEM'S POINTS ADD UP (owner,
// 29 Oct 2026: "the points shown on items always add up to exactly 100 - score,
// AFTER forms are generated too, exactly as they already do on the pre-form
// review page; solving everything the panel shows must reach exactly 100").
//
// Before 29 Oct the side panel's Best Solutions rows printed the score's own
// row shares (`answer_gain`) and each pillar's whole gap, and listed no key
// detail, no hard stop / warning card and no document row - on Orbin 432c8594
// the rows read +2 +1 +1 +2 +6 +3 = 15 at 79, six points on no item. Once forms
// exist the server now weighs the review page's ONE ordered plan on the stored
// score (`packageSqs.review_plan`, `after_forms: true`, services/review_plan.py)
// and the panel lists the plan's items in its order, each with the plan's own
// number - the same numbers the review page prints, read the same way
// (`screenPoints` / `pointsFor`). A fix offered twice counts at its first place
// only (`mirror_of`), so the list adds up to exactly 100 minus the score.
//
// Pure: the rows, their words and their numbers. AcordModal opens each row's
// fix window with its own handlers (key detail, card, score row, Data
// Consistency, documents).
import { screenPointsText } from "./screenPoints.js";
import { pointsFor, pointsText, scoreItems, pillarLabel } from "./recommendations.js";

const clean = (v) => String(v ?? "").trim();
const RENDERED_WARNING_TIERS = ["required", "recommended", "binder_followup"];

// The post-generation plan, when the payload carries one.
export const planAfterForms = (packageSqs) => !!(packageSqs && packageSqs.review_plan
  && packageSqs.review_plan.after_forms === true && Array.isArray(packageSqs.review_plan.items));

// A partial score update (a dismiss, a reopen, a headline-only reply) merged
// into the score on screen. The plan was weighed on the OLD score: kept, its
// items still summed to 100 minus the old score beside the new headline
// ("21 points remaining" at 82 = 103 - production review, 29 Oct 2026). A
// changed headline drops the plan (and the cached plan screen key) so the panel
// asks for the new score's plan.
//
// After forms the plan is dropped on EVERY patch (end-user review, 30 Oct
// 2026): a patch is an answer, a dismissal or a reopen, and each changes the
// items even when the headline does not move (one of six warnings that share
// a cap, an "under 1 pt" answer). Kept, the panel still listed the answered
// item with its points. `_plan_epoch` moves with each patch so the panel asks
// again although the score and its timestamp are unchanged.
export function patchPackageScore(prev, patch) {
  if (!prev) return prev;
  const next = { ...prev, ...(patch || {}) };
  if (planAfterForms(prev)) {
    delete next.review_plan;
    next._plan_epoch = (Number(prev._plan_epoch) || 0) + 1;
  } else if (prev.review_plan && patch && patch.package_sqs_score != null
      && patch.package_sqs_score !== prev.package_sqs_score) {
    delete next.review_plan;
  }
  return next;
}

// The key a plan read is tied to: the score, its timestamp and the patch epoch.
export const planScoreKey = (packageSqs) => (packageSqs
  ? `${packageSqs.package_sqs_score}|${packageSqs.timestamp ?? ""}|${Number(packageSqs._plan_epoch) || 0}`
  : "");

// Every card the plan was weighed on, as an issue the fix window opens
// ({ code, message, issue_id, resolution, forms }) - hard stops, then the
// warning tiers, like `review_plan.rendered_cards`.
export function planCards(groupedIssues) {
  const out = [];
  const take = (clusters) => {
    for (const c of (Array.isArray(clusters) ? clusters : [])) {
      if (!c || typeof c !== "object") continue;
      const items = Array.isArray(c.items) && c.items.length ? c.items : [c];
      for (const it of items) {
        if (!it || typeof it !== "object") continue;
        out.push({
          code: it.code || c.code || null,
          message: it.message || c.message || c.primary_message || "",
          issue_id: it.issue_id || null,
          resolution: it.resolution || c.resolution || null,
          forms: Array.isArray(it.forms) ? it.forms : (Array.isArray(c.forms) ? c.forms : []),
        });
      }
    }
  };
  take(groupedIssues?.hard_stops);
  for (const tier of RENDERED_WARNING_TIERS) take(groupedIssues?.warnings?.[tier]);
  return out;
}

// An item's own number, as the review page reads it (`screenPoints.fromPlan`).
const entryOf = (it) => ({
  points: Number(it.points) || 0, exact: it.exact !== false,
  held: it.held_by ? String(it.held_by) : null, under: it.under === true,
  withOthers: it.with_others ? String(it.with_others) : null, scoreItem: it.score_item !== false,
  hold: it.hold ? String(it.hold) : null,
  coveredBy: it.covered_by ? String(it.covered_by) : null,
});

// [{ id, kind, label, title, points, text, ...the fix's payload }] in the plan's
// order. A mirror is left out (its first place carries the number); a score
// row is listed exactly when the review page lists it (`pointsFor`); a card, a
// Data Consistency pick or a document row is listed when it shows a number.
export function editorPlanRows(packageSqs, keyDetails, groupedIssues) {
  if (!planAfterForms(packageSqs)) return null;
  const plan = packageSqs.review_plan;
  const recs = Array.isArray(packageSqs.top_recommendations) ? packageSqs.top_recommendations : [];
  const missing = Array.isArray(keyDetails?.missing_items) ? keyDetails.missing_items : [];
  const cards = planCards(groupedIssues);
  const scoreByRow = new Map(scoreItems(packageSqs, new Set()).map((s) => [s.rowIndex, s]));
  const rows = [];
  for (const it of plan.items) {
    if (!it || typeof it !== "object" || it.mirror_of) continue;
    const entry = entryOf(it);
    const text = screenPointsText(entry);
    // `planPoints`: what the step adds in the plan's order (the total's part).
    const base = { id: String(it.id || ""), kind: it.kind, points: entry, text,
      planPoints: Number(it.points) || 0, leadsTo: Array.isArray(it.leads_to) ? it.leads_to : [] };
    if (it.kind === "detail") {
      const item = missing.find((m) => m && clean(m.label) === clean(it.label)) || null;
      rows.push({ ...base, title: "Key detail", label: clean(it.label), item });
    } else if (it.kind === "card") {
      if (!text) continue;
      const iid = clean(it.issue_id);
      const issue = (iid && cards.find((c) => clean(c.issue_id) === iid))
        || cards.find((c) => clean(c.code) === clean(it.code)) || null;
      rows.push({ ...base, title: "", label: clean(issue?.message || it.label || it.message), issue });
    } else if (it.kind === "rec") {
      const row = recs[Number(it.row_index)];
      if (!row || typeof row !== "object") continue;
      const p = pointsFor(row);
      if (!p) continue;
      const scoreItem = scoreByRow.get(Number(it.row_index)) || null;
      rows.push({ ...base, points: p, text: pointsText(p), title: pillarLabel(row.pillar),
        label: clean(row.action || it.label), scoreItem });
    } else if (it.kind === "dc") {
      if (!text) continue;
      rows.push({ ...base, title: "Data Consistency", label: clean(it.label || it.fact), fact: clean(it.fact) });
    } else if (it.kind === "doc") {
      if (!(entry.points > 0) && !entry.under && !entry.hold) continue;      // P1: "under 1 pt" / a hold is listed too
      rows.push({ ...base, title: it.step === "mark" ? "Documents" : "Loss History", label: clean(it.label), step: it.step || null });
    }
  }
  return { rows, total: Number(plan.total) || 0, left: Number(plan.left) || 0 };
}

// What the listed rows add up to in the plan's order - with `left`, exactly
// 100 minus the score (the side panel's own check of the owner's rule).
export const editorPlanTotal = (list) => (list && Array.isArray(list.rows)
  ? list.rows.reduce((n, r) => n + (Number(r.planPoints) || 0), 0)
  : 0);
