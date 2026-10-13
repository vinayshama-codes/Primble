// "Before you generate" (Choice Electric #27, 7 Oct 2026).
//
// The download review's form checks - the hard blocks that make a download a
// DRAFT, the required boxes still empty - run on the forms that WILL be
// generated, before they are (backend services/form_dry_run.py). Every
// pre-form response carries the result as `dry_run`; this module is the small
// shared vocabulary the package page reads it with.

import { API_BASE } from "../config/constants";
import { recDryIssueId } from "./resolvedIssues";

export const DRY_RUN_READY = "ready";
export const DRY_RUN_PENDING = "pending";
export const DRY_RUN_SKIPPED = "skipped";

// GET the dry run - the poll while a run is still going, and the re-check
// against the forms the producer ticked. Resolves to the payload or null.
export async function fetchDryRun(sessionId, formIds = [], wait = 8) {
  if (!sessionId) return null;
  const params = new URLSearchParams();
  const ids = (Array.isArray(formIds) ? formIds : []).filter(Boolean);
  if (ids.length) params.set("form_ids", ids.join(","));
  params.set("wait", String(wait));
  try {
    const res = await fetch(`${API_BASE}/api/session/${encodeURIComponent(sessionId)}/dry-run?${params}`,
      { credentials: "include" });
    if (!res.ok) return null;
    const data = await res.json();
    return data?.dry_run ?? null;
  } catch {
    return null;
  }
}

// The forms a payload was checked against, as ids.
export function dryRunFormIds(dryRun) {
  return (dryRun?.checked_forms || []).map((f) => f.form_id).filter(Boolean);
}

// Does this payload answer for exactly these ticked forms? (An empty tick list
// means "the recommended forms", which every pre-form response checks.)
export function dryRunMatchesTicks(dryRun, tickedIds) {
  const ticks = (tickedIds || []).filter(Boolean);
  if (!ticks.length) return dryRun?.form_source !== "selected" || !dryRun;
  const have = new Set(dryRunFormIds(dryRun));
  return dryRun?.form_source === "selected" && ticks.length === have.size && ticks.every((id) => have.has(id));
}

// The issue-shaped object the existing ResolutionModal opens for an item. Its
// `issue_id` is the item's own (13 Oct 2026): the server files what the fix
// changes under it, so "Open again" in the Recommendations page's Resolved list
// can take it back.
export function dryRunFixIssue(item) {
  const where = item?.form_label ? `${item.form_label}: ` : "";
  const why = item?.blocks_download
    ? "Without it the download is a draft."
    : "The form needs it.";
  return {
    message: `${where}${item?.label || "This box"}. ${why} ${item?.what_to_do || ""}`.trim(),
    code: null,
    issue_id: recDryIssueId(item?.id),
    forms: item?.form_id ? [item.form_id] : [],
    resolution: item?.resolution || null,
    __dryRun: true,
    __recKind: "dry",
    __recItemId: item?.id || null,
    __recTitle: `${where}${item?.label || "This box"}`,
  };
}

// "N items" / "1 item".
export function itemsText(n) {
  return `${n} item${n === 1 ? "" : "s"}`;
}
