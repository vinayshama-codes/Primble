// Orbin 22 Sep, item 16 (30 Sep 2026): "Stylistically, this should tuck under
// 'reviewed' or 'recommendations' after it's been addressed."
//
// The editor's side panel printed a hard stop the producer had already handled
// inside the red HARD STOPS block, with a green "Resolved" chip beside it. These
// helpers decide, from the same per-issue statuses the chips read, which cap
// stops are still OPEN (they stay in the red block) and which were HANDLED
// (resolved or dismissed - they move to Reviewed, keeping their Reopen).
//
// ONE THING NEVER CHANGES: a score held at 60 is always explained on screen.
// "Resolved" and "Dismissed" are work-tracking marks - `/api/issues/status`
// never runs the scorer - so a stop marked resolved WITHOUT fixing its value
// still caps the score. When every stop still in the cap list is handled, the
// red block gives way to `stillCappedNote`, never to silence.
//
// Pure functions, no React: the panel imports them and the backend suite runs
// them under node (tests/test_item16_reviewed_30sep.py).

export const isHandledStatus = (status) => status === "resolved" || status === "dismissed";

// The sentences the package HARD STOPS block prints - the rule that block has
// always used: the scorer's own `cap_hard_stops` when it has any, else the one
// `cap_reason`, and nothing at all unless the package is capped at 60.
export function packageCapReasons(pkg) {
  if (!pkg || pkg.cap_applied !== 60) return [];
  if (Array.isArray(pkg.cap_hard_stops) && pkg.cap_hard_stops.length) return pkg.cap_hard_stops;
  return pkg.cap_reason ? [pkg.cap_reason] : [];
}

// Split cap-stop sentences into { open, handled }. Each row is
// { message, item, iid, status }:
//   item   - the server-classified row for the sentence (rule code, resolution),
//            or null on a session scored before those rows existed;
//   iid    - the id the row's status control keys, from `idOf(item)`;
//   status - `statusOf(iid)`.
// `fallbackForms` gives an item with no forms of its own the forms the block
// passes (the per-form block names its form), so the id matches the control.
// A sentence with no item has no status control, so it can never be marked and
// always stays open.
export function splitCapStops(messages, items, { idOf, statusOf, fallbackForms } = {}) {
  const open = [];
  const handled = [];
  const rows = Array.isArray(items) ? items : [];
  for (const message of (Array.isArray(messages) ? messages : [])) {
    const found = rows.find((x) => x && x.message === message) || null;
    const item = found && Array.isArray(fallbackForms)
      ? { ...found, forms: (Array.isArray(found.forms) && found.forms.length) ? found.forms : fallbackForms }
      : found;
    const iid = item && typeof idOf === "function" ? idOf(item) : null;
    const status = iid && typeof statusOf === "function" ? statusOf(iid) : undefined;
    (item && iid && isHandledStatus(status) ? handled : open).push({ message, item, iid, status });
  }
  return { open, handled };
}

// Rows from several lists, each issue once (first wins).
export function uniqueRows(rows) {
  const seen = new Set();
  const out = [];
  for (const r of (Array.isArray(rows) ? rows : [])) {
    if (!r || !r.iid || seen.has(r.iid)) continue;
    seen.add(r.iid);
    out.push(r);
  }
  return out;
}

// The code namespaces of the legacy stop engine - every code
// `issue_registry.classify_legacy` can return (`legacy_*` rows, per-label
// `tier1_missing_*`). The backend keeps them apart from cross-form codes on
// purpose; tests/test_item16_reviewed_30sep.py fails the build if either side
// drifts.
export const LEGACY_ENGINE_CODE_PREFIXES = ["legacy_", "tier1_missing_"];

export const isLegacyEngineCode = (code) =>
  LEGACY_ENGINE_CODE_PREFIXES.some((p) => String(code || "").startsWith(p));

// Resolved issues that no longer compute as live ("ghosts"), sent to the
// section they belong to. A legacy-engine stop or warning is not a cross-form
// validation, so once fixed it is listed under Reviewed - where it went the
// moment it was marked. Everything else stays in the Cross-Form Validation
// panel's Resolved list, exactly as before. Anything Reviewed already lists
// (`reviewedIds`) is dropped from both, so each row renders once.
export function routeGhostIssues(ghosts, reviewedIds) {
  const seen = reviewedIds instanceof Set ? reviewedIds : new Set(reviewedIds || []);
  const reviewed = [];
  const crossForm = [];
  for (const g of (Array.isArray(ghosts) ? ghosts : [])) {
    if (!g || seen.has(g.issue_id)) continue;
    (isLegacyEngineCode(g.code) ? reviewed : crossForm).push(g);
  }
  return { reviewed, crossForm };
}

// The line that replaces the red block when every stop still holding the score
// is one the producer marked. Short, and it says what to do.
export function stillCappedNote(handled, scope) {
  const list = Array.isArray(handled) ? handled : [];
  const n = list.length;
  if (!n) return "";
  const statuses = new Set(list.map((r) => r && r.status));
  const verb = !statuses.has("dismissed") ? "resolved"
    : statuses.has("resolved") ? "resolved or dismissed" : "dismissed";
  const who = scope === "form" ? "This form" : "The package";
  const what = n === 1 ? "an item" : `${n} items`;
  return `${who} is still capped at 60 by ${what} you marked ${verb} - reopen ${n === 1 ? "it" : "them"} under Reviewed, or fix the value.`;
}
