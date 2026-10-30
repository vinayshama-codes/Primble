// EVERY NUMBER ON THE REVIEW SCREEN ADDS UP (owner, 15 Oct 2026: "every score
// adds up to 100, not more and not less").
//
// The server shares out ONE total over every fact the pre-form screen asks for -
// the hard stop and warning cards, the key details and the Recommendations rows -
// and gives the cards the caps their answers lift (`packageSqs.screen_shares`,
// sqs_service.complete_screen_shares). This gives each fact's share to the item
// on the page that offers its fix, by the SAME rule the Recommendations list uses
// to leave a row out (`fixKeys` / `allCovered`): a row a card or key detail
// already offers is not listed, so its points sit on that card or key detail.
// Every other fact keeps its points on its own Recommendations row.
//
// A document disagreement is settled on its Data Consistency row ("Values to
// confirm"), so its share (`screen_dc_points`, by fact) prints on that row
// (`dc`); a card whose "Fix in Data Consistency" button leads there prints the
// SAME number (`mirror` - the same to-do, counted once in the total).
import { renderedCardRows, splitMissingDetails } from "./keyDetailCards.js";
import { fixKeys, allCovered, followUpText } from "./recommendations.js";
import { issueFactKey } from "./dcFacts.js";

const clean = (v) => String(v ?? "").trim();
const pointsOf = (v) => (Array.isArray(v) ? Number(v[0]) || 0 : Number(v) || 0);

// The key a card is found by on the page: its rule code.
export const cardKey = (it) => clean(it?.code);

// A card's points (28 Oct 2026): one code can draw several cards, each with its
// own fix (a catch-all code such as `uncovered_soft_stop`), so a card is found
// by its issue id first, then by its code.
export const cardPoints = (cards, it) => {
  if (!cards || !it) return undefined;
  const iid = clean(it.issue_id);
  return (iid && cards.get(`issue:${iid}`)) || cards.get(cardKey(it));
};

// What each fact's own Recommendations row would open (its fix keys).
function rowTargets(packageSqs) {
  const out = {};
  for (const r of (packageSqs && packageSqs.top_recommendations) || []) {
    const f = clean(r && r.field);
    if (!f || out[f]) continue;
    let res = r.resolution && r.resolution.mode && r.resolution.mode !== "none" ? r.resolution : null;
    if (!res && r.answer_mode === "schedule" && clean(r.schedule_key)) res = { mode: "schedule", schedule_key: clean(r.schedule_key) };
    if (!res) res = { mode: "field", facts: [f] };
    const keys = fixKeys(res);
    out[f] = keys.length ? keys : [`fact:${f}`];
  }
  return out;
}

// THE PAGE'S ONE PLAN (owner, 24 Oct 2026): when the server sends
// `review_plan`, every number comes from it, by item - each item is worth what
// the score gains when it is done after every item above it on the page
// (services/review_plan.py). A card or key detail offering a fix an earlier item
// already offers shows that item's number as `mirror` (never added twice); a step
// a hold withholds says so (`held`), and a step under a point says that
// (`under`). Older payloads keep the share-out below.
// CAP SHARES (owner, 29 Oct 2026, services/review_plan._share_group_releases):
// a share that lands only when a group is done says so - "+1 pts (counts when
// all 6 warnings are fixed)". A mirror reads its first place's condition.
export const withOthersOf = (it, first = null) => {
  const w = (it && it.with_others) || (first && first.with_others) || "";
  return String(w || "").trim() || null;
};
// A cap-only item (SCORING_RULES.md R5 / P1, 30 Oct 2026): no points of its own,
// it only holds the score - "Holds the score at 85 until fixed".
export const holdOf = (it, first = null) => {
  const h = (it && it.hold) || (first && first.hold) || "";
  return String(h || "").trim() || null;
};
const withOthersText = (p) => (p && p.withOthers ? ` (${p.withOthers})` : "");

function fromPlan(plan, packageSqs) {
  const items = plan.items.filter((it) => it && typeof it === "object");
  const byId = new Map(items.map((it) => [it.id, it]));
  const entry = (it) => {
    const first = it.mirror_of && byId.has(it.mirror_of) ? byId.get(it.mirror_of) : null;
    const mirror = first ? Number(first.points) || 0 : 0;
    return {
      points: (Number(it.points) || 0) + mirror, exact: it.exact !== false && !(first && first.exact === false),
      mirror, held: it.held_by ? String(it.held_by) : null, under: it.under === true, id: it.id,
      withOthers: withOthersOf(it, first), scoreItem: it.score_item !== false || !!first,
      leadsTo: Array.isArray(it.leads_to) ? it.leads_to : [], cost: Number(it.cost) || 0,
      hold: holdOf(it, first),
      coveredBy: it.covered_by ? String(it.covered_by) : null,
    };
  };
  const cards = new Map();
  const details = new Map();
  const dc = new Map();
  for (const it of items) {
    if (it.kind === "card" && clean(it.code)) {
      const e = entry(it);
      if (clean(it.issue_id)) cards.set(`issue:${clean(it.issue_id)}`, e);
      if (!cards.has(clean(it.code))) cards.set(clean(it.code), e);
    }
    else if (it.kind === "detail" && clean(it.label)) details.set(clean(it.label), entry(it));
    else if (it.kind === "dc" && clean(it.fact)) dc.set(clean(it.fact), entry(it));
  }
  const unanswerable = Array.isArray(packageSqs && packageSqs.screen_unanswerable)
    ? packageSqs.screen_unanswerable.filter((u) => u && (Number(u.points) > 0 || u.under === true || !!u.hold)) : [];
  return { cards, details, dc, unanswerable };
}

// `openConflicts`: the facts the Data Consistency panel lists as open conflicts
// (utils/dcFacts.openConflictFacts). Without it, every fact the server shares a
// conflict's points to is taken to have its row.
export function screenPoints(packageSqs, groupedIssues, keyDetails, openConflicts = null) {
  const plan = packageSqs && packageSqs.review_plan;
  if (plan && Array.isArray(plan.items)) return fromPlan(plan, packageSqs);
  const shares = (packageSqs && packageSqs.screen_shares) || {};
  const targets = rowTargets(packageSqs);
  const targetsOf = (f) => targets[f] || [`fact:${f}`];
  const dcShares = (packageSqs && packageSqs.screen_dc_points) || {};
  const dcOpen = openConflicts instanceof Set ? openConflicts : new Set(Object.keys(dcShares));

  // The items in page order: the cards (one per rule code), then the key details
  // still listed.
  const slots = [];
  for (const row of renderedCardRows(groupedIssues)) {
    const key = cardKey(row);
    if (!key) continue;
    const have = slots.find((s) => s.kind === "card" && s.key === key);
    const dcFact = issueFactKey(row);
    if (have) {
      fixKeys(row.resolution).forEach((k) => have.keys.add(k));
      if (!have.dcFact && dcFact && dcOpen.has(dcFact)) have.dcFact = dcFact;
    } else {
      slots.push({ kind: "card", key, keys: new Set(fixKeys(row.resolution)), points: 0, exact: true, any: false,
        dcFact: dcFact && dcOpen.has(dcFact) ? dcFact : null });
    }
  }
  const { items } = splitMissingDetails(keyDetails);
  for (const it of Array.isArray(items) ? items : []) {
    if (!it || !it.label) continue;
    slots.push({ kind: "detail", key: it.label, keys: new Set(fixKeys(it.resolution)), points: 0, exact: true, any: false });
  }

  const used = new Set();
  const give = (slot, f) => {
    const s = shares[f];
    used.add(f);
    slot.points += Number(s[0]) || 0;
    slot.exact = slot.exact && s[1] === true;
    slot.any = true;
  };
  const facts = Object.keys(shares).filter((f) => Array.isArray(shares[f]));
  // 1. The first item whose fix opens everything the fact's row would.
  for (const f of facts) {
    const slot = slots.find((s) => allCovered(targetsOf(f), s.keys));
    if (slot) give(slot, f);
  }
  // 2. A row the page hides because several items together offer it: the first
  //    item that offers any part of it.
  const union = new Set();
  slots.forEach((s) => s.keys.forEach((k) => union.add(k)));
  for (const f of facts) {
    if (used.has(f) || !allCovered(targetsOf(f), union)) continue;
    const slot = slots.find((s) => targetsOf(f).some((k) => allCovered([k], s.keys)));
    if (slot) give(slot, f);
  }

  // A card also carries its share of the cap the hard stops / warnings hold and
  // of the cross-form deduction (`screen_card_points`, by rule code). A code the
  // page does not draw as a card gives its points to the cards it does draw.
  const cardSlots = slots.filter((s) => s.kind === "card");
  const capFor = new Map();
  let orphan = 0;
  for (const [k, v] of Object.entries((packageSqs && packageSqs.screen_card_points) || {})) {
    const n = pointsOf(v);
    if (!n) continue;
    const code = clean(String(k).split("|")[0]);
    if (cardSlots.some((s) => s.key === code)) capFor.set(code, (capFor.get(code) || 0) + n);
    else orphan += n;
  }
  // A document disagreement: on its row; the card whose "Fix in Data
  // Consistency" button leads there mirrors it. With no row on the page, like
  // any other code the page does not draw.
  const dc = new Map();
  for (const [fact, v] of Object.entries(dcShares)) {
    const n = pointsOf(v);
    if (!n) continue;
    if (!dcOpen.has(fact)) {
      orphan += n;
      continue;
    }
    dc.set(fact, { points: (dc.get(fact)?.points || 0) + n, exact: false });
    const card = cardSlots.find((s) => s.dcFact === fact);
    if (card) card.mirror = (card.mirror || 0) + n;
  }
  if (orphan && cardSlots.length) {
    const holders = cardSlots.filter((s) => capFor.has(s.key));
    const to = holders.length ? holders : cardSlots;
    const base = Math.floor(orphan / to.length);
    let left = orphan - base * to.length;
    for (const s of to) {
      capFor.set(s.key, (capFor.get(s.key) || 0) + base + (left > 0 ? 1 : 0));
      if (left > 0) left -= 1;
    }
    orphan = 0;
  }

  const cards = new Map();
  const details = new Map();
  for (const s of slots) {
    const cap = s.kind === "card" ? capFor.get(s.key) || 0 : 0;
    const mirror = s.kind === "card" ? s.mirror || 0 : 0;
    if (!s.any && !cap && !mirror) continue;
    // `mirror`: the part that is its Data Consistency row's number (not added twice).
    const entry = { points: s.points + cap + mirror, exact: s.exact && !cap && !mirror, mirror };
    (s.kind === "card" ? cards : details).set(s.key, entry);
  }
  // What no box on this page can answer (a coverage decision, a loss run to send):
  // listed with its points, so the numbers still add up and the gap is named.
  const unanswerable = Array.isArray(packageSqs && packageSqs.screen_unanswerable)
    ? packageSqs.screen_unanswerable.filter((u) => u && Number(u.points) > 0) : [];
  if (orphan) unanswerable.push({ label: "the cap held by the hard stops and warnings", points: orphan });
  return { cards, details, dc, unanswerable };
}

// "+3 pts" / "up to +2 pts"; "under 1 pt" for a score item whole points
// cannot reach (SCORING_RULES.md P1 - the plan's `under`, set by
// review_plan.enforce_contract), with its condition when it shares a hold;
// "Counts once <hold> is fixed" only on an old payload; nothing for a 0.
export const underText = (p) => `under 1 pt${withOthersText(p)}`;
export const screenPointsText = (p) => {
  if (!p) return "";
  if (p.points > 0) return `${p.exact || p.withOthers ? "" : "up to "}+${p.points} pts${withOthersText(p)}${followUpText(p)}`;
  if (p.under) return `${underText(p)}${followUpText(p)}`;
  if (p.hold) return p.hold;
  if (p.coveredBy) return `Answered with: ${p.coveredBy}`;
  if (p.held) return `Counts once ${p.held} is fixed`;
  if (p.scoreItem === false) return "No effect on the score";
  return "";
};

// A DISMISSED card that still fires keeps its points on the review page (strict
// review, 29 Oct 2026). Before forms a dismissal never moves the score - the
// card still holds what it held - so the plan still counts its number. The page
// tucked it under "Resolved" with no number, and the numbers it printed added up
// to less than 100 minus the score (P2), with nothing saying where the rest was.
// The Resolved row now prints the plan's number for it ("Open again" fixes it).
// "" for a fixed item, an item the server no longer sends, or no plan number.
export const dismissedRowPointsText = (row, cards) => {
  if (!row || row.status !== "dismissed" || row.live !== true) return "";
  return screenPointsText(cardPoints(cards, row.item));
};

