// The review screen's "Resolved" section (owner, 8 Oct 2026 - Brent's Choice
// Electric notes: a handled item must not vanish, it tucks away; and "Resolve"
// is only a status tag, so it goes).
//
// A hard stop or warning a person DISMISSED, or fixed through "Open to fix" (the
// fix window marks it "resolved"), leaves its list and is listed under a
// collapsed "Resolved (n)" at the bottom of its page, with a small "Resolved" or
// "Dismissed" label and "Open again" - the same tuck the editor's SQS panel does
// with its "Reviewed" section. The rules:
//   * a dismissed item moves there whether or not it still fires;
//   * a resolved item moves there once it no longer fires - an answer that did
//     not clear it leaves it in its list, where it still needs attention;
//   * a fixed item the server no longer sends is rebuilt from its stored status
//     (message, form, rule) and filed under the page it was on (`severity`); an
//     older status that never recorded its page is filed under Warnings.
// Pure functions, no React: the backend suite runs them under node.

export const RESOLVED_LABELS = { resolved: "Resolved", dismissed: "Dismissed" };

const HANDLED = new Set(["resolved", "dismissed"]);

// The items a cluster stands for - its own list, or the one issue a
// single-item cluster carries on itself (the shape the review renders).
export function clusterItems(c) {
  if (!c) return [];
  if (Array.isArray(c.items) && c.items.length) return c.items;
  return [{ issue_id: c.issue_id, message: c.primary_message, forms: c.forms }];
}

// Every issue id the screen currently lists, over any number of cluster lists.
export function liveIdsOf(clusterLists, idOf) {
  const ids = new Set();
  for (const list of clusterLists || []) {
    for (const c of list || []) {
      for (const it of clusterItems(c)) ids.add(idOf(it));
    }
  }
  return ids;
}

// One page's clusters split into what still needs attention and what was
// dismissed. { open: clusters (count and items trimmed, empty ones dropped),
// handled: [{ iid, item, status, forms }] }. A resolved item that still fires
// stays open: its answer did not clear it.
export function splitClusters(clusters, { idOf, statusOf }) {
  const open = [];
  const handled = [];
  for (const c of clusters || []) {
    const items = clusterItems(c);
    const keep = [];
    for (const it of items) {
      const iid = idOf(it);
      const st = statusOf(iid);
      if (st === "dismissed") handled.push({ iid, item: it, status: st, forms: c.forms || [], live: true });
      else keep.push(it);
    }
    if (!keep.length) continue;
    if (keep.length === items.length) { open.push(c); continue; }
    open.push({
      ...c,
      items: keep,
      count: keep.length,
      primary_message: keep.length === 1 ? keep[0].message : c.primary_message,
    });
  }
  return { open, handled };
}

// ── Recommendations (owner, 13 Oct 2026) ────────────────────────────────────
// A "Raise your score" or "Your forms will need" row fixed through its own
// "Open to fix" gets a Resolved list too. Its fix travels with an id the server
// files the changes under (services/issue_fix_undo.py), so "Open again" takes
// the fix - and its points - back through the one reopen door. The ids never
// collide with an issue's ("iss_..."): score rows "rec:score:<pillar>:<asks>",
// form-check rows "rec:dry:<item id>", ticked form choices "rec:choice:<id>".
export const REC_PAGE = "recommendation";
export const REC_ID_PREFIX = "rec:";
export const recScoreIssueId = (itemId) => (itemId ? `${REC_ID_PREFIX}${itemId}` : null);   // itemId: "score:..."
export const recDryIssueId = (itemId) => (itemId ? `${REC_ID_PREFIX}dry:${itemId}` : null);
export const recChoiceIssueId = (choiceId) => (choiceId ? `${REC_ID_PREFIX}choice:${choiceId}` : null);
export const isRecommendationId = (iid) => String(iid || "").startsWith(REC_ID_PREFIX);

// A row ANOTHER fix answered (14 Oct 2026, run 91c865a5: rows that left the
// list "didnt go into resolved"). Its status is "resolved" like a row fixed in
// its own window, and says which fix it was: the status `reason` is the
// sentence the row shows ("Cleared by your answer to <row>"), and `rule_code`
// carries the id that fix was filed under ("" when it has none - a key detail).
// A recommendation has no rule code of its own, and the reason - unlike the
// rule code, which the store keeps when a later write sends none - is rewritten
// by every status change: a row later fixed in its own window, or reopened, is
// never read as cleared by the old fix.
export const CLEARED_BY_PREFIX = "Cleared by your answer to ";

export function clearedByReason(title) {
  const t = String(title ?? "").trim().replace(/[.\s]+$/, "");
  return t ? `${CLEARED_BY_PREFIX}${t}.` : "";
}

// { iid, title } of the fix that cleared a row, from its stored status; null
// when the row was not cleared by another fix.
export function clearedByOf(st) {
  const reason = String((st && st.reason) || "");
  if (!reason.startsWith(CLEARED_BY_PREFIX)) return null;
  const iid = String((st && st.rule_code) || "").trim();
  return { iid: iid || null, title: reason.slice(CLEARED_BY_PREFIX.length).replace(/\.$/, "").trim() };
}

// The rows a fix cleared that are still filed "resolved" under it.
// `entries`: [[issue_id, status], ...].
export function rowsClearedBy(entries, clearingIid) {
  if (!clearingIid) return [];
  const out = [];
  for (const [iid, st] of entries || []) {
    if (!st || st.status !== "resolved") continue;
    const by = clearedByOf(st);
    if (by && by.iid === clearingIid) out.push(iid);
  }
  return out;
}

// The page a stored status belongs to: "hard", "warning" or "recommendation"
// (unknown -> warning). A recommendation is known by its page or its id - an
// older status never recorded a page, and one must never land under Warnings.
export function pageOfStatus(st, iid = null) {
  if ((st && st.severity === REC_PAGE) || isRecommendationId(iid)) return REC_PAGE;
  return st && st.severity === "hard" ? "hard" : "warning";
}

// Handled items the screen no longer lists (fixed - the check stopped firing),
// rebuilt from their stored statuses, for ONE page. `entries` is
// [[issue_id, {status, message, form_id, rule_code, severity}], ...].
export function storedHandledRows(entries, { liveIds, page }) {
  const out = [];
  for (const [iid, st] of entries || []) {
    if (!st || !HANDLED.has(st.status) || !st.message) continue;
    if (liveIds && liveIds.has(iid)) continue;
    if (pageOfStatus(st, iid) !== page) continue;
    out.push({
      iid,
      item: { issue_id: iid, message: st.message, forms: st.form_id ? [st.form_id] : [], code: st.rule_code || null },
      status: st.status,
      forms: st.form_id ? [st.form_id] : [],
      live: false,
    });
  }
  return out;
}

// One page's Resolved rows: the dismissed items still listed, then the stored
// ones no longer listed. Each id once.
export function resolvedRows(handled, stored) {
  const seen = new Set();
  const out = [];
  for (const r of [...(handled || []), ...(stored || [])]) {
    if (!r || seen.has(r.iid)) continue;
    seen.add(r.iid);
    out.push(r);
  }
  return out;
}

// ── Progress: "x of y handled" (owner, 13 Oct 2026) ─────────────────────────
// y is every blocker the package has had - the ones still listed AND the ones
// already handled - and x is how many are handled. Counting only what is still
// listed printed "0 of 0 handled" once every warning was fixed (a fixed item
// stops firing and leaves its list) and "0 of 1" with one hard stop left.
// `openClusters`: the page's clusters still needing attention (splitClusters
// `.open`); `resolved`: the page's Resolved rows (resolvedRows).
export function pageProgress(openClusters, resolved) {
  const open = (openClusters || []).reduce(
    (n, c) => n + (Number(c?.count) || clusterItems(c).length), 0);
  const done = Array.isArray(resolved) ? resolved.length : 0;
  return { open, done, total: open + done };
}

// The hard stops and warnings a view lists, each with the page it is on.
export function blockerItems(grouped, idOf) {
  const out = [];
  const g = grouped && typeof grouped === "object" ? grouped : {};
  const add = (clusters, page) => {
    for (const c of Array.isArray(clusters) ? clusters : []) {
      for (const it of clusterItems(c)) {
        if (it && it.message) out.push({ iid: idOf(it), item: { ...it, cluster: it.cluster || c.cluster }, page });
      }
    }
  };
  add(g.hard_stops, "hard");
  for (const list of Object.values(g.warnings && typeof g.warnings === "object" ? g.warnings : {})) add(list, "warning");
  return out;
}

// The blockers a save CLEARED (owner, 13 Oct 2026): listed before it, not left
// open by it. A key-detail link, a "Raise your score" row or one card's fix can
// clear another card's warning without that card ever being opened - it must
// still count as handled, so the caller records it "resolved" (and it moves to
// the Resolved section). "Left open" is `fixLeftOpen`'s rule - the same item
// still listed, or its rule / cluster firing under new words (a part-fixed
// card) - so a half-fixed item is never marked. `skipIds`: the item the save
// itself was for (its own status is set by the fix window's rule).
export function clearedBlockers(beforeGrouped, afterGrouped, idOf, leftOpen, skipIds = new Set()) {
  if (!afterGrouped || typeof afterGrouped !== "object") return [];   // no new view: nothing is known
  const before = blockerItems(beforeGrouped, idOf);
  const after = blockerItems(afterGrouped, idOf);
  const beforeItems = before.map((b) => b.item);
  const afterItems = after.map((a) => a.item);
  return before.filter((b) => b.iid && !skipIds.has(b.iid)
    && !leftOpen(b.item, beforeItems, afterItems, idOf));
}

// What "Open again" does: a dismissed item still firing just goes back to its
// list ("status"); a fixed one is reopened the way the editor's panel reopens
// it - the fix (and its points) is taken back and the item returns to its list
// ("reopen"). A dismissed item that has STOPPED firing has nothing to reopen -
// its value was fixed after the dismissal - so it offers no "Open again"
// ("none"): reopening it would only make it vanish, and relabelling it as a
// fix would send its next reopen down the fix path for values it never wrote.
export const NO_LONGER_APPLIES = "No longer applies";
export function reopenKind(row) {
  if (!row || row.status !== "dismissed") return "reopen";
  return row.live === false ? "none" : "status";
}
