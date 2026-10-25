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

// The sentences the package HARD STOPS block prints: every open hard stop
// holding the package at 60, one per conflict (`ready_blockers`, 19 Oct 2026).
// A score saved before then: the rule that block has always used - the
// scorer's own `cap_hard_stops` when it has any, else the one `cap_reason`, and
// nothing at all unless the package is capped at 60.
export function packageCapReasons(pkg) {
  if (!pkg) return [];
  if (Array.isArray(pkg.ready_blockers)) return pkg.ready_blockers;
  if (pkg.cap_applied !== 60) return [];
  if (Array.isArray(pkg.cap_hard_stops) && pkg.cap_hard_stops.length) return pkg.cap_hard_stops;
  return pkg.cap_reason ? [pkg.cap_reason] : [];
}

// The clickable rows for those sentences (rule code + resolution).
export function packageCapItems(pkg) {
  if (!pkg) return [];
  if (Array.isArray(pkg.ready_blocker_items)) return pkg.ready_blocker_items;
  return Array.isArray(pkg.cap_hard_stop_items) ? pkg.cap_hard_stop_items : [];
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

// The Review page's readiness card (5 Oct 2026, CH125 b601fad1): the producer
// dismissed every hard stop and warning and the number did not move, with
// nothing on the card saying why. A cap is held by the VALUE, and Dismiss /
// Resolve record a review - they never change a value. Null when the score is
// not capped, or when an open item is still listed (the list says why).
// `cap_applied` is the ceiling IN FORCE, not proof that it holds the score:
// 27 of 30 scored packages sit below theirs (audit G7, 5 Oct 2026), and the
// note then blamed a marked item for a number that is low for other reasons.
// It speaks only when the cap BINDS - the raw score is above it - and, for an
// 85, never when a hidden Data Consistency row may be what holds it.
export function railCapNote(pkg, { hardOpen = 0, hardTotal = 0, warnOpen = 0, warnTotal = 0,
                                   hiddenWarnings = 0 } = {}) {
  const cap = pkg && Number(pkg.cap_applied);
  if (!cap) return null;
  const raw = Number(pkg.raw_sqs_score);
  const score = Number(pkg.package_sqs_score ?? pkg.sqs_score);
  const binds = Number.isFinite(raw) ? raw > cap : score === cap;
  if (!binds) return null;
  // Positive wording (Choice Electric #16, 9 Oct 2026): what fixes it, not the cap.
  if (cap === 60 && hardTotal > 0 && hardOpen === 0) {
    return "Fix the value of the hard stop you marked to increase your Submission Quality Score (SQS)™ - marking it records your review only.";
  }
  const hidden = Number(hiddenWarnings || pkg.hidden_warnings || 0);
  if (cap === 85 && hardOpen === 0 && warnTotal > 0 && warnOpen === 0 && !hidden) {
    return "Fix the value of the warning you marked to increase your Submission Quality Score (SQS)™ - marking it records your review only.";
  }
  return null;
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
  const whose = scope === "form" ? "this form's" : "the package's";
  const what = n === 1 ? "an item" : `${n} items`;
  return `Fix the value of ${what} you marked ${verb} to increase ${whose} Submission Quality Score (SQS)™, or reopen ${n === 1 ? "it" : "them"} under Reviewed.`;
}
