// THE DOWNLOAD SCREENS' NUMBERS ARE THE SIDE PANEL'S (29 Oct 2026). Before, the
// download review and the post-download checklist printed each card's own
// stored `score_impact`, while the editor's side panel printed the review
// plan's number (`packageSqs.review_plan`, services/review_plan.py) - the same
// item could read "+7 pts" on one screen and "+2 pts" on the other, and the
// stored numbers did not add up to 100 minus the score.
//
// Now a download row shows the plan's number for the plan item it is, found
// the way the side panel finds it (utils/editorPlanList.js): a hard stop /
// warning by its issue id, then its rule code; a card row by its fact (the
// plan's Recommendations row for that fact, read with `pointsFor` like the
// panel, else the first plan item whose fix writes that fact). A row the plan
// does not list shows no number - never the stale one. A plan item (or the
// item it mirrors) is counted once on the screen, and the numbers shown never
// add up past 100 minus the score. No plan (not read yet, or failed) = no
// numbers. Pure: node-testable.
import { planAfterForms } from "./editorPlanList.js";
import { screenPointsText } from "./screenPoints.js";
import { pointsFor } from "./recommendations.js";

const clean = (v) => String(v ?? "").trim();

// The key a download row is known by (its numbers are looked up by it).
export const downloadRowKey = (r) => clean(r?.rec_id);

// The plan's own reading of an item, as the review page reads it
// (`screenPoints.fromPlan`): a mirror carries its first place's number.
function planEntry(it, first) {
  const mirror = first ? Number(first.points) || 0 : 0;
  return {
    points: (Number(it.points) || 0) + mirror,
    exact: it.exact !== false && !(first && first.exact === false),
    held: it.held_by ? String(it.held_by) : null,
    under: it.under === true,
    withOthers: (it.with_others || (first && first.with_others)) ? String(it.with_others || first.with_others) : null,
  };
}

// The plan item a download row is, or null.
function planItemFor(r, items) {
  const iid = clean(r?.issue_id);
  const code = clean(r?.code);
  if (iid || code || r?.review_issue) {
    const cards = items.filter((it) => it.kind === "card");
    return (iid && cards.find((it) => clean(it.issue_id) === iid))
      || (code && (cards.find((it) => clean(it.code) === code && it.first_of_code !== false)
        || cards.find((it) => clean(it.code) === code)))
      || null;
  }
  const field = clean(r?.field);
  if (!field) return null;
  return items.find((it) => it.kind === "rec" && clean(it.field) === field)
    || items.find((it) => Array.isArray(it.keys) && it.keys.includes(`fact:${field}`))
    || null;
}

// Map(row key -> "+N pts" / "up to +N pts" / "Counts once X is fixed" /
// "under 1 pt") for the rows in the order the screen draws them. Rows without
// a number are absent.
export function downloadPlanPoints(packageSqs, rows) {
  const out = new Map();
  if (!planAfterForms(packageSqs)) return out;
  const items = packageSqs.review_plan.items.filter((it) => it && typeof it === "object");
  const byId = new Map(items.map((it) => [clean(it.id), it]));
  const recs = Array.isArray(packageSqs.top_recommendations) ? packageSqs.top_recommendations : [];
  const score = Number(packageSqs.package_sqs_score);
  let room = Number.isFinite(score) ? Math.max(0, 100 - Math.floor(score)) : 0;
  const used = new Set();
  for (const r of Array.isArray(rows) ? rows : []) {
    const key = downloadRowKey(r);
    if (!key || out.has(key)) continue;
    const it = planItemFor(r, items);
    if (!it) continue;
    const first = it.mirror_of ? byId.get(clean(it.mirror_of)) || null : null;
    const ids = [clean(it.id), first ? clean(first.id) : ""].filter(Boolean);
    if (ids.some((id) => used.has(id))) continue;          // counted once
    let p;
    if (it.kind === "rec" && !first && recs[Number(it.row_index)]
        && typeof recs[Number(it.row_index)] === "object") {
      p = pointsFor(recs[Number(it.row_index)]);           // the side panel's reading
    } else {
      p = planEntry(it, first);
    }
    if (!p) continue;
    let points = p.held ? 0 : Math.max(0, Math.round(Number(p.points) || 0));
    let exact = p.exact !== false;
    if (points > room) {                                   // never past 100 - score
      if (room < 1) continue;
      points = room;
      exact = false;
    }
    const text = screenPointsText({ ...p, points, exact });
    if (!text) continue;
    ids.forEach((id) => used.add(id));
    room -= points;
    out.set(key, text);
  }
  return out;
}

// The rows with their plan number on them (`plan_points`, "" = none), for the
// screens that draw them. `orderedRows`: the rows in the order they are drawn
// (the download steps, one after another).
export function withDownloadPlanPoints(recs, orderedRows, packageSqs) {
  const list = Array.isArray(recs) ? recs : [];
  const pts = downloadPlanPoints(packageSqs, Array.isArray(orderedRows) ? orderedRows : list);
  return list.map((r) => (r && typeof r === "object"
    ? { ...r, plan_points: pts.get(downloadRowKey(r)) || "" } : r));
}
