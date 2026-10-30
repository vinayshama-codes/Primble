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
import {
  REC_ID_PREFIX, REC_PAGE, isRecommendationId, recChoiceIssueId, recDryIssueId, recScoreIssueId,
  clearedByOf,
} from "./resolvedIssues.js";

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
    // The submission facts a per-building table answers (21 Oct 2026, Brent's
    // item 8 - premises_cope `derives`): its cells ARE that fact's answer, so a
    // form box or another row asking the same fact is the same to-do.
    (Array.isArray(res.derives) ? res.derives : []).map(clean).filter(Boolean)
      .forEach((f) => keys.push(`fact:${f}`));
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
//
// A MEASURED 0 ON A ROW WORTH LESS THAN A POINT IS THE FLOOR, NOT "NOTHING"
// (owner, 14 Oct 2026, run 91c865a5: "2 of the recommendations disappeared").
// The package score is its weighted sum rounded DOWN (spec section 2), and the
// gain is measured on that whole number. The hydrant row lifted 70.90 to 71.65
// (+1); the no-loss answer took Loss History out, the others re-weighted, the
// sum landed on 79.00 and the same row lifted it to 79.88 (+0). Both COPE rows
// measured 0 and left the list - their boxes still empty, Property Integrity
// still 90 - and came back the moment "Open again" moved the sum to 70.90.
// Such a row adds up to one point whenever it is answered (both together lift
// 79.00 to 80.76), so it stays listed as "up to +1 pts".
// A pillar at 0 is the exception: there a 0 is real (the COPE minimum is
// missing - nothing in that pillar counts yet), and the row stays out. A row
// worth a point or more that measures 0 adds nothing now, and one that
// measures LESS than 0 costs points (the floor never turns a gain negative) -
// both stay out, as before.
function belowOnePoint(row) {
  const avail = num(row?.points_available);
  const pillar = num(row?.score);
  return avail !== null && avail > 0 && avail < 1 && (pillar === null || pillar > 0);
}

//
// ONE TOTAL, SHARED OUT (owner, 15 Oct 2026, run 5eb5b23c: at 94 the rows read
// +3 / +2 / +2 - "that will take my score to 101"). Each number was its answer
// measured ALONE, and lone gains never add up: the score is rounded down, and
// every lone answer collected the same leftover fraction. A row the scorer
// marks `answer_gain_share` carries its SHARE of what answering every row makes
// (sqs_service._share_out_gains): the shares add up to that score, never past
// 100. A share of 0 is a row whose fraction of a point is already counted in
// the rows above it - still listed while it adds anything on its own
// (`answer_gain_alone`) or is worth under a point, with no number.
export function pointsFor(row) {
  // THE REVIEW PAGE'S PLAN (24 Oct 2026, services/review_plan.py): a row carrying
  // `plan_id` shows exactly the plan's number - what it adds after every item
  // above it on the page. A hold that withholds it says so; a fraction of a
  // point says "under 1 pt"; a step that adds nothing is not listed.
  if (row && row.plan_id) {
    const withOthers = clean(row.answer_gain_with_others) || null;
    const leadsTo = Array.isArray(row.answer_gain_leads_to) ? row.answer_gain_leads_to.map(clean).filter(Boolean) : [];
    const cost = Math.round(num(row.answer_gain_cost) ?? 0);
    const wo = { ...(withOthers ? { withOthers } : {}), ...(leadsTo.length ? { leadsTo } : {}), ...(cost > 0 ? { cost } : {}) };
    const p = Math.round(num(row.answer_gain) ?? 0);
    if (p >= 1) return { points: p, exact: row.answer_gain_is_exact === true || !!withOthers, share: true, ...wo };
    if (row.answer_gain_under === true && !row.answer_gain_mirror_of) return { points: 0, exact: false, share: true, under: true, ...wo };
    if (row.answer_gain_held_by) return { points: 0, exact: true, share: true, held: clean(row.answer_gain_held_by) };
    // A fix an earlier item on the page offers first (a card, a key detail):
    // its number, as a mirror - the page lists the row only where nothing
    // already offers it, and a mirror is never added to the total.
    const m = Math.round(num(row.answer_gain_mirror) ?? 0);
    if (row.answer_gain_mirror_of && m >= 1) return { points: m, exact: true, share: true, mirror: true, ...wo };
    // A question the plan lists although it adds nothing itself (the claims
    // question when the narrative already says claims - the request / upload
    // rows after it carry the points): listed, with no number.
    // The claims question asked alone (option A): "up to" what its follow-ups
    // unlock once it is answered.
    const unlocks = Math.round(num(row.unlocks_points) ?? 0);
    if (unlocks >= 1) return { points: unlocks, exact: false, share: true };
    return row.listed_at_zero === true ? { points: 0, exact: true, share: true } : null;
  }
  const gain = num(row?.answer_gain);
  if (gain !== null) {
    const n = Math.round(gain);
    if (row?.answer_gain_share === true) {
      if (n >= 1) return { points: n, exact: row.answer_gain_is_exact === true, share: true };
      const alone = num(row?.answer_gain_alone);
      // Listed with no number while it still adds something on its own, is worth
      // under a point, or belongs to a pillar held at 0 - a pillar no single answer
      // lifts (the COPE minimum: occupancy AND construction AND a value), where the
      // last row takes the whole unlock and the ones before it are its prerequisites.
      return (alone !== null && alone > 0) || belowOnePoint(row) || num(row?.score) === 0
        ? { points: 0, exact: true, share: true } : null;
    }
    if (n <= 0) return n === 0 && belowOnePoint(row) ? { points: 1, exact: false } : null;
    return { points: n, exact: row.answer_gain_is_exact === true };
  }
  // An unmeasured row worth under half a point is still a gap (15 Oct 2026, owner:
  // a package must not sit at 99 with "Nothing to add here"): listed "up to +1",
  // and `withinHundred` keeps the list inside 100.
  const avail = num(row?.points_available);
  if (avail === null || !(avail > 0)) return null;
  return { points: Math.max(1, Math.round(avail)), exact: false };
}

// A listed row with no points to its name prints nothing; one a hold withholds
// says what it waits on; a fraction of a point says "under 1 pt".
// What answering an item raises next (rule G2) and a dip it causes first
// (G13) - short, after the number (services/review_plan leads_to / cost).
export const followUpText = (p) => {
  if (!p) return "";
  const leads = Array.isArray(p.leadsTo) ? p.leadsTo.filter(Boolean) : [];
  if (!leads.length) return "";
  const first = String(leads[0]).split(" Fix:")[0].replace(/\s+/g, " ").trim().slice(0, 70);
  const more = leads.length > 1 ? ` (+${leads.length - 1} more)` : "";
  return p.cost > 0 ? ` · score dips until you also answer: ${first}${more}` : ` · then asks: ${first}${more}`;
};

export const pointsText = (p) => {
  if (!p) return "";
  if (p.points > 0) return `${p.exact ? "" : "up to "}+${p.points} pts${p.withOthers ? ` (${p.withOthers})` : ""}${followUpText(p)}`;
  if (p.under) return `under 1 pt${p.withOthers ? ` (${p.withOthers})` : ""}${followUpText(p)}`;
  if (p.held) return `Counts once ${p.held} is fixed`;
  return "";
};

// What a row's answer adds ON ITS OWN: the scorer's lone measurement when the
// row carries a share, else the number it carries.
const aloneGain = (row) => num(row?.answer_gain_alone) ?? num(row?.answer_gain);

// A pillar HELD AT 0 by one missing value (owner, 14 Oct 2026, run 823d58a0:
// Property Integrity is 0 until occupancy is entered - the COPE minimum - while
// its parts score 28 / 60). Its other rows add nothing until that value is in,
// so they measure +0 or nothing, and the list showed some ("up to +1") and hid
// others. The gate is the row of that pillar whose answer is MEASURED to raise
// the score; every other row of the pillar is held by it: listed, with the line
// "Adds points once <gate> is answered", never hidden and never promising points
// it cannot give yet. {pillar: gate label}.
export function pillarGates(rows) {
  const gates = {};
  for (const row of Array.isArray(rows) ? rows : []) {
    if (!row || typeof row !== "object" || row.pillar === HARD_STOPS_ROW) continue;
    if (num(row.score) !== 0 || !(aloneGain(row) > 0)) continue;
    if (!gates[row.pillar]) gates[row.pillar] = clean(row.action) || pillarLabel(row.pillar);
  }
  return gates;
}

export function scoreItems(packageSqs, covered = new Set()) {
  const rows = Array.isArray(packageSqs?.top_recommendations) ? packageSqs.top_recommendations : [];
  const out = [];
  const seen = new Set();
  const gates = pillarGates(rows);
  for (const [rowIndex, row] of rows.entries()) {
    if (!row || typeof row !== "object" || row.pillar === HARD_STOPS_ROW) continue;
    let resolution = row.resolution && row.resolution.mode && row.resolution.mode !== "none"
      ? row.resolution : fallbackResolution(row);
    if (!resolution) continue;                       // no fix route: not listed
    // The narrative window lists what is still missing as options (13 Oct 2026).
    if (resolution.mode === "narrative" && Array.isArray(row.narrative_gaps) && row.narrative_gaps.length) {
      resolution = { ...resolution, gaps: row.narrative_gaps };
    }
    const gate = gates[row.pillar];
    // A plan row already carries what it adds in page order (holds included).
    const heldBy = !row.plan_id && gate && !(aloneGain(row) > 0) && num(row.score) === 0 ? gate : null;
    const avail = num(row.points_available);
    // A held row carrying a share shows what it adds once the rows before it -
    // the gate among them - are in; with no share left it is listed, unnumbered.
    const points = heldBy
      ? (row.answer_gain_share === true
          ? (pointsFor(row) || { points: 0, exact: true, share: true })
          : (avail !== null && avail > 0 ? { points: Math.max(1, Math.round(avail)), exact: false } : null))
      : pointsFor(row);
    if (!points) continue;                           // answering adds nothing
    const keys = fixKeys(resolution);
    if (!keys.length || allCovered(keys, covered)) continue;   // a card already asks
    // A row whose fix an earlier item on the page offers first is listed there,
    // not here (one fix, one number) - it stays "asked" for the Resolved rules,
    // which read the rows with nothing covered.
    if (points.mirror && covered.size) continue;
    // A per-building table row is keyed on the submission fact it answers, not
    // its cells (21 Oct 2026): it keeps its id - and its Resolved status - when
    // the package gains or loses a building and the row turns table <-> box.
    const derived = Array.isArray(resolution.derives) && resolution.derives.length && clean(row.field);
    const id = `score:${row.pillar || ""}:${derived ? `fact:${clean(row.field)}` : keys.join("|")}`;
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
      heldBy,
      // The Loss History plan's step order (23 Oct 2026): the page lists the
      // pillar's answer and document rows in this order (`scoreSequence`).
      planOrder: num(row.plan_order),
      // The row's place in `top_recommendations` (the plan's `row_index`; the
      // editor's side panel after forms, utils/editorPlanList.js).
      rowIndex,
    });
  }
  return out;
}

// The "Raise your score" list in the order it is drawn (23 Oct 2026): each
// pillar's rows in turn. A pillar whose rows carry a plan order (Loss History,
// `sqs_service.loss_history_plan`) lists its answer rows and its document rows
// (`screen_unanswerable` with the Documents action) interleaved in that order,
// at the place of its first row. Any other document row follows the last
// answer row of its pillar; one whose pillar has no answer row comes last.
// [{ kind: "item", item } | { kind: "doc", doc }]
export function scoreSequence(items, docRows) {
  const list = Array.isArray(items) ? items.filter(Boolean) : [];
  const docs = Array.isArray(docRows) ? docRows.filter(Boolean) : [];
  const titleOf = (t) => clean(t).split(":")[0].trim();
  const docTitle = (u) => titleOf(u.title || "Needs documents");
  const orderOf = (n) => (num(n) === null ? Number.POSITIVE_INFINITY : n);
  const planned = new Set([
    ...list.filter((it) => num(it.planOrder) !== null).map((it) => titleOf(it.title)),
    ...docs.filter((u) => num(u.plan_order) !== null).map(docTitle),
  ]);
  const out = [];
  const placed = new Set();
  const done = new Set();
  list.forEach((it, idx) => {
    const title = titleOf(it.title);
    if (planned.has(title)) {
      if (done.has(title)) return;
      done.add(title);
      const group = [
        ...list.filter((x) => titleOf(x.title) === title)
          .map((x) => ({ kind: "item", item: x, order: orderOf(x.planOrder) })),
        ...docs.map((u, k) => ({ u, k })).filter(({ u }) => docTitle(u) === title)
          .map(({ u, k }) => { placed.add(k); return { kind: "doc", doc: u, order: orderOf(u.plan_order) }; }),
      ];
      group.sort((a, b) => a.order - b.order);
      group.forEach(({ kind, item, doc }) => out.push(kind === "item" ? { kind, item } : { kind, doc }));
      return;
    }
    out.push({ kind: "item", item: it });
    const next = idx + 1 < list.length ? titleOf(list[idx + 1].title) : null;
    if (next === title) return;
    docs.forEach((u, k) => {
      if (!placed.has(k) && docTitle(u) === title) { placed.add(k); out.push({ kind: "doc", doc: u }); }
    });
  });
  docs.map((u, k) => ({ u, k })).filter(({ k }) => !placed.has(k))
    .sort((a, b) => orderOf(a.u.plan_order) - orderOf(b.u.plan_order))
    .forEach(({ u }) => out.push({ kind: "doc", doc: u }));
  return out;
}

// The issue-shaped object the page's fix window opens for a score item. Its
// `issue_id` is the row's own (13 Oct 2026): the server files what the fix
// changes under it, so "Open again" in the page's Resolved list takes the fix -
// and its points - back.
export function scoreFixIssue(item) {
  // A narrative row's detail is a status line ("... but does not include ...")
  // that is wrong once the narrative is written - its Resolved row keeps the
  // section name only (owner, 24 Oct 2026).
  const narrative = item?.resolution?.mode === "narrative";
  const what = [item?.title, narrative ? null : item?.detail].filter(Boolean).join(": ");
  const adds = pointsText(item?.points);
  const gain = adds ? ` Answering adds ${adds} to your score.` : "";
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
    const toCheck = rows.filter((r) => r && r.status === "verify").length;
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

// THE FILL RATE IS NOT IN THE SCORE (Brent, 23 Oct 2026, Z34-1 #1). The 14 Oct
// "Form Fill Rate" row ("Confirm the Please verify values ...") and the Overview's
// "your last points are on the forms" notice are gone: the package score is the
// same number before and after forms, and what the forms still need is the
// "Forms ready" meter (utils/scoreWithForms.formsReady). "Confirm all" moves the
// meter, never this list.

// THE LIST NEVER ADDS UP PAST 100 (owner, 15 Oct 2026: "score should be
// distributed in such a manner that it should not go past 100 ... for all the
// packages"). The scorer's shares already add up to what answering every row
// makes. This is the guarantee for everything else the list prints - a payload
// scored before the shares, a bound the page works out itself ("up to"): the
// shares first, then the rest, each in the order
// listed, every number takes at most what is still left below 100. A number
// cut down becomes "up to"; a row left with nothing stays listed, unnumbered.
// Mutates and returns `items` (each is built fresh by this module).
export function withinHundred(items, score) {
  const list = Array.isArray(items) ? items : [];
  const s = num(score);
  if (s === null) return list;
  let room = Math.max(0, 100 - Math.floor(s));
  const take = (it) => {
    const p = it && it.points;
    if (!p || !(p.points > 0)) return;
    const kept = Math.min(p.points, room);
    room -= kept;
    if (kept !== p.points) it.points = { ...p, points: kept, exact: false };
  };
  list.filter((it) => it?.points?.share).forEach(take);
  list.filter((it) => !it?.points?.share).forEach(take);
  return list;
}

export function buildRecommendations({ packageSqs, groupedIssues, keyDetails, attention, formsExist, formOffers } = {}) {
  const covered = onScreenFixKeys(groupedIssues, keyDetails);
  const score = scoreItems(packageSqs, covered);
  withinHundred(score, packageSqs?.package_sqs_score);
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
// (ids and page: utils/resolvedIssues). The server holds a fix's changes under
// the id it was made with, so "Open again" can take it back. A row another fix
// answered (14 Oct 2026) is listed too, "Cleared by your answer to <row>": it
// has nothing of its own to take back, so its "Open again" reopens the fix that
// cleared it (`recommendationReopenTarget`).

// Did a save fix its row? "fixed" | "open" | "unknown".
//   score - fixed once the package scorer no longer asks for it, read with
//           NOTHING covered: a row now hidden behind a Hard Stop / Warning card
//           asking for the same value is still open, never fixed.
//   dry   - fixed once a FINISHED check of its form no longer lists it; a check
//           still running, or one that did not look at that form, is "unknown"
//           (the caller judges it on the next one).
// The fix keys a score row's id carries ("score:<pillar>:<key>|<key>...").
function scoreIdKeys(itemId) {
  const m = /^score:[^:]*:(.+)$/.exec(String(itemId || ""));
  return new Set(m ? m[1].split("|").filter(Boolean) : []);
}

export function recommendationFixState(kind, itemId, { packageSqs, dryRun, formId } = {}) {
  if (!itemId) return "unknown";
  if (kind === "score") {
    if (!packageSqs || typeof packageSqs !== "object") return "unknown";
    // A merged row (same-pillar sub-point rows, services/review_plan.py, 24 Oct
    // 2026) saved with one box left blank leaves its other question listed as a
    // row of its own, under a NEW id - still open, never "fixed" (Save progress).
    const own = scoreIdKeys(itemId);
    return scoreItems(packageSqs, new Set()).some((s) => s.id === itemId
      || (own.size && (s.keys || []).some((k) => own.has(k)))) ? "open" : "fixed";
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

// ── Rows another fix cleared (owner, 14 Oct 2026, run 91c865a5: "2 of the
// recommendations disappeared from there and they didnt go into resolved") ──
// One save can answer more than its own row: "No known losses" takes Loss
// History out of the score, and every other row of that pillar goes with it; a
// card's table can fill a value a row asked for. Such a row left the list
// because the fix answered it, so it must land in Resolved - "Cleared by your
// answer to <row>" - never vanish. The hard stop / warning pages already file
// the blockers a save clears (`resolvedIssues.clearedBlockers`); this is the
// same rule for this page. A page reload never files anything: only a save
// does, against the list that was on screen when it was made.

// Every fix target the scorer still asks for - any row with a fix route,
// whatever its points and whether or not a card covers it.
export function askedScoreKeys(packageSqs) {
  const keys = new Set();
  const rows = Array.isArray(packageSqs?.top_recommendations) ? packageSqs.top_recommendations : [];
  for (const row of rows) {
    if (!row || typeof row !== "object" || row.pillar === HARD_STOPS_ROW) continue;
    const res = row.resolution && row.resolution.mode && row.resolution.mode !== "none"
      ? row.resolution : fallbackResolution(row);
    fixKeys(res).forEach((k) => keys.add(k));
  }
  return keys;
}

// The items a pillar still names as missing - its rows' `missing` lists and its
// score breakdown's. A pillar's one row shows its FIRST gap; a fix that puts a
// new gap ahead of it changes the row without answering the old one.
function stillMissingLabels(packageSqs, pillar) {
  const out = new Set();
  const rows = Array.isArray(packageSqs?.top_recommendations) ? packageSqs.top_recommendations : [];
  for (const row of rows) {
    if (!row || row.pillar !== pillar) continue;
    (Array.isArray(row.missing) ? row.missing : []).forEach((m) => out.add(clean(m)));
  }
  const parts = packageSqs?.category_breakdown?.[pillar];
  for (const part of Object.values(parts && typeof parts === "object" ? parts : {})) {
    (Array.isArray(part?.missing) ? part.missing : []).forEach((m) => out.add(clean(m)));
  }
  out.delete("");
  return out;
}

// Is a row's target still asked for? A table is asked while any row asks for
// it or for one of its cells; a cell, while a row asks for it or for its whole
// table (errs toward "still asked": a row wrongly kept open is still on screen,
// one wrongly filed as Resolved hides a gap that still costs points).
function stillAsked(key, asked) {
  if (asked.has(key)) return true;
  if (key.startsWith("table:")) {
    const sk = key.slice(6);
    for (const a of asked) if (a.startsWith(`col:${sk}:`)) return true;
  }
  if (key.startsWith("col:")) {
    const sk = key.split(":")[1];
    if (asked.has(`table:${sk}`)) return true;
  }
  return false;
}

const SCORER_TARGET = /^(fact|col|table):/;

// The "Raise your score" rows a save CLEARED besides its own: listed before it
// (`listed`, the page's score items), and now asked for nowhere - no row of the
// new score carries any of their targets, and their pillar no longer names
// them missing. A row still asked for is not cleared, whether it now sits
// behind a card (it is on screen there), was part-fixed (a new row carries
// what is left), or stopped being worth points (`pointsFor`). `skipIds`: the
// save's own row (its status is the fix window's rule). No new score: nothing
// is known, nothing is filed.
export function clearedScoreItems(listed, packageSqsAfter, skipIds = new Set()) {
  if (!packageSqsAfter || typeof packageSqsAfter !== "object") return [];
  const asked = askedScoreKeys(packageSqsAfter);
  const out = [];
  for (const it of (Array.isArray(listed) ? listed : [])) {
    if (!it || it.kind !== "score" || !it.id || skipIds.has(it.id)) continue;
    const keys = Array.isArray(it.keys) ? it.keys : [];
    // Only a scorer row (a row whose fix keys are not scorer targets is never filed here).
    if (!keys.length || !keys.every((k) => SCORER_TARGET.test(k))) continue;
    if (keys.some((k) => stillAsked(k, asked))) continue;
    if (clean(it.detail) && stillMissingLabels(packageSqsAfter, it.pillar).has(clean(it.detail))) continue;
    out.push(it);
  }
  return out;
}

// The fix that cleared them, as the cleared rows name it and as "Open again"
// reopens it: { iid, title }. `iid` is the id the server filed the fix under
// (its undo receipt) - null for a fix with no record (a key detail, which is
// not an issue), whose rows say what cleared them and offer no "Open again".
// A card's message without the "Fix: ..." advice it carries ("... occupancy
// type Fix: Review and correct this before proceeding.", "... address (Fix:
// Provide this value ...)") - the row names the item, not the instructions.
const withoutFixAdvice = (text) => clean(text).replace(/\s*\(?\s*Fix:[\s\S]*$/, "").replace(/[\s.]+$/, "");

export function clearingFixOf(issue, idOf) {
  if (!issue || typeof issue !== "object") return { iid: null, title: "" };
  if (issue.__keyDetail) return { iid: null, title: clean(issue.__keyDetailLabel) || withoutFixAdvice(issue.message) };
  if (issue.__scoreItem || issue.__dryRun) {
    return { iid: clean(issue.issue_id) || null, title: clean(issue.__recTitle) || withoutFixAdvice(issue.message) };
  }
  const iid = typeof idOf === "function" ? clean(idOf(issue)) : clean(issue.issue_id);
  return { iid: iid || null, title: withoutFixAdvice(issue.message ?? issue.primary_message) };
}

// The sentence a cleared row shows under its title.
export function clearedByText(by) {
  if (!by) return "";
  if (by.documents) return "Answered by your documents - nothing to do here.";
  const what = clean(by.title).replace(/[.\s]+$/, "") || "another item";
  return `Cleared by your answer to ${what}.${by.iid ? " Open again takes that answer back." : ""}`;
}

// What "Open again" on a Resolved row reopens: the row's own fix, or - for a
// row another fix cleared - THAT fix (its values come off, and every row it
// cleared comes back with the row that asked for it). Null when there is
// nothing to take back (cleared by a key detail) or the row is an added form.
// `statusOf(iid)`: the stored status of an id ({form_id, rule_code, message,
// severity}) or null.
export function recommendationReopenTarget(row, statusOf = () => null) {
  if (!row || !row.iid || row.kind === "choice") return null;
  const by = row.clearedBy;
  if (by) {
    if (!by.iid) return null;
    const st = (typeof statusOf === "function" && statusOf(by.iid)) || {};
    const rec = isRecommendationId(by.iid);
    return {
      iid: by.iid,
      meta: {
        form_id: st.form_id || null,
        rule_code: rec ? null : (clean(st.rule_code) || null),
        message: clean(st.message) || clean(by.title) || null,
        severity: rec ? REC_PAGE : (st.severity ?? null),
      },
    };
  }
  return {
    iid: row.iid,
    meta: { form_id: (row.forms || [])[0] || null, rule_code: null, message: row.title || null, severity: REC_PAGE },
  };
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
//    title, forms, clearedBy?: { iid, title } | null, asked?, message? }]
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
      // Another fix answered it: { iid, title } of that fix (resolvedIssues).
      clearedBy: clearedByOf(st),
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
  const score = (Array.isArray(model?.score) ? model.score.length : 0) + (Number(model?.docRows) || 0);
  const forms = (Number(model?.forms?.count) || 0) + (Number(model?.choicesOpen) || 0);
  const offers = Array.isArray(model?.offers) ? model.offers.length : 0;
  const parts = [];
  if (score) parts.push(`${score} to raise your score`);
  if (offers) parts.push(`${offers} form${offers === 1 ? "" : "s"} to add`);
  if (forms) parts.push(`${forms} your forms need`);
  return parts.length ? parts.join(" · ") : `${Number(model?.count) || 0} to consider`;
}
