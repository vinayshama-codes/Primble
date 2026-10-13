// addDocuments.js - the words the package page prints after documents are
// added to, or changed on, an existing package (Choice Electric #25, 7 Oct 2026).
//
// The server (POST /api/session/{id}/documents, and a document change after
// forms) re-reads the package and re-stamps the generated forms; its answer
// carries what moved. This file turns that answer into the result lines, so the
// rail and the classic layout print the same sentences.
//
// Pure: no React, no fetch.

import { formLabel } from "./formInstances.js";

export const ACCEPT_UPLOAD = ".pdf,.zip,.txt,.jpg,.jpeg,.png,.bmp,.tif,.tiff,.webp";

const plural = (n, word, many) => `${n} ${n === 1 ? word : (many || `${word}s`)}`;

const labelOf = (row) => (row && (row.label || formLabel(row.form_id))) || "";

const joinNames = (names) => {
  const list = names.filter(Boolean);
  if (list.length <= 1) return list.join("");
  return `${list.slice(0, -1).join(", ")} and ${list[list.length - 1]}`;
};

// [{kind, text}] - kind: "done" | "info" | "warn". Empty for no result.
export function documentsResultLines(result) {
  if (!result || typeof result !== "object") return [];
  const lines = [];
  const added = Array.isArray(result.documents_added) ? result.documents_added.length : 0;
  const head = added > 0 ? `${plural(added, "document")} added.` : "Document updated.";
  if (result.after_forms) {
    const boxes = Number(result.boxes_updated) || 0;
    const forms = Array.isArray(result.forms_updated) ? result.forms_updated.length : 0;
    lines.push({
      kind: "done",
      text: boxes > 0
        ? `${head} ${plural(boxes, "box", "boxes")} updated on ${plural(forms, "form")}.`
        : `${head} No form boxes changed.`,
    });
  } else {
    lines.push({ kind: "done", text: head });
  }
  const stale = (Array.isArray(result.stale_signatures) ? result.stale_signatures : []).map(labelOf);
  if (stale.length) {
    lines.push({
      kind: "warn",
      text: `The applicant's signature on ${joinNames(stale)} no longer matches - send for signature again.`,
    });
  }
  const dupes = (Array.isArray(result.duplicates_skipped) ? result.duplicates_skipped : []).filter(Boolean);
  if (dupes.length) {
    lines.push({ kind: "info", text: `Already in this package, not added again: ${joinNames(dupes)}.` });
  }
  for (const row of Array.isArray(result.forms_without_line) ? result.forms_without_line : []) {
    lines.push({
      kind: "info",
      text: row.reason === "policy"
        ? `${labelOf(row)}: no document shows its policy any more.`
        : `${labelOf(row)}: no document shows ${row.line_label || "its line"} any more.`,
    });
  }
  if (result.integrity_review_required) {
    lines.push({ kind: "warn", text: "The documents may belong to more than one insured - review them before continuing." });
  }
  return lines;
}

// ── After forms: the note, the result box, the AI reading (C103, 7 Oct 2026) ──

// The one-line note above "Add documents" once forms exist.
export const AFTER_FORMS_ADD_NOTE =
  "Your forms will be updated with this document. New warnings may appear on the review page.";

const formsWithBoxes = (byForm) => Object.entries(byForm || {})
  .filter(([, n]) => Number(n) > 0)
  .map(([fid, n]) => `${formLabel(fid)} (${plural(Number(n), "box", "boxes")})`);

// Boxes changed per form: the documents door's re-stamp plus, once the AI
// reading is done, the boxes it filled.
export function boxesByForm(result, fill) {
  const out = { ...((result && result.boxes_by_form) || {}) };
  if (fill && fill.state === "done") {
    for (const [fid, n] of Object.entries(fill.filled_by_form || {})) {
      out[fid] = (Number(out[fid]) || 0) + (Number(n) || 0);
    }
  }
  return out;
}

// The AI reading's own lines: running, finished (boxes filled, suggestions),
// or did not finish. [] when it never ran.
export function fillStatusLines(fill) {
  if (!fill || typeof fill !== "object" || !fill.state || fill.state === "off") return [];
  const docs = joinNames(Array.isArray(fill.documents) ? fill.documents : []) || "your document";
  if (fill.state === "running") return [{ kind: "info", text: `Reading ${docs} into your forms...` }];
  if (fill.state === "done") {
    const filled = Number(fill.boxes_filled) || 0;
    const sugg = Number(fill.suggestions) || 0;
    const parts = [filled > 0 ? `the AI filled ${plural(filled, "box", "boxes")}` : "the AI found nothing new to fill"];
    if (sugg > 0) parts.push(`${plural(sugg, "value")} to review where it differs from the form`);
    const lines = [{ kind: "done", text: `Read ${docs} into your forms: ${parts.join(", ")}.` }];
    if (sugg > 0) lines.push({ kind: "info", text: "Open the form to choose: its side panel lists them under New document." });
    const stale = (Array.isArray(fill.stale_signatures) ? fill.stale_signatures : []).map(labelOf);
    if (stale.length) {
      lines.push({ kind: "warn", text: `The applicant's signature on ${joinNames(stale)} no longer matches - send for signature again.` });
    }
    return lines;
  }
  return [{ kind: "warn", text: fill.message || `Reading ${docs} into your forms did not finish. Your forms keep the values its facts gave them.` }];
}

// The result box after an add once forms exist: "Added a.pdf. Forms updated:
// ACORD 125 (12 boxes), ..." then the documents door's other lines.
export function addResultLines(result, fill) {
  if (!result || typeof result !== "object") return [];
  const names = (Array.isArray(result.documents_added) ? result.documents_added : [])
    .map((d) => (d && d.filename) || "").filter(Boolean);
  const head = names.length ? `Added ${joinNames(names)}.` : documentsResultLines(result)[0]?.text || "";
  const forms = formsWithBoxes(boxesByForm(result, fill));
  const first = forms.length ? `${head} Forms updated: ${forms.join(", ")}.` : `${head} No form boxes changed yet.`;
  return [{ kind: "done", text: first }, ...documentsResultLines(result).slice(1)];
}

const NEW_KINDS = [
  ["hard_stops", "hard stop", "hardstops"],
  ["warnings", "warning", "warnings"],
  ["data_consistency", "Data Consistency item", "consistency"],
];

// "New on the review page: 1 hard stop, 2 warnings" / "No new issues" / ""
// (unknown). Counts are the server's: after minus before.
export function newOnReviewText(counts) {
  if (!counts || typeof counts !== "object") return "";
  const parts = NEW_KINDS.filter(([k]) => Number(counts[k]) > 0)
    .map(([k, word]) => plural(Number(counts[k]), word));
  return parts.length ? `New on the review page: ${parts.join(", ")}.` : "No new issues on the review page.";
}

// The review section the "Review them" button opens: the first kind with new items.
export function firstNewSection(counts) {
  const hit = NEW_KINDS.find(([k]) => counts && Number(counts[k]) > 0);
  return hit ? hit[2] : null;
}

// Open items on the review page, for the editor's "Back to review" button:
// hard stops and warnings still open (the grouped view's clusters, minus the
// ones marked handled - the same tally the review rail prints) plus the Data
// Consistency values that need confirming. `section` is the first section
// with work: Hard Stops, else Warnings, else Data Consistency, else Overview.
export function reviewOpenItems({ groupedIssues, hardStops, softStops, isHandled, consistencyFields } = {}) {
  const handled = typeof isHandled === "function" ? isHandled : () => false;
  const tally = (clusters, bare) => {
    if (Array.isArray(clusters)) {
      let total = 0; let done = 0;
      for (const c of clusters) {
        const items = Array.isArray(c && c.items) ? c.items : [];
        total += Number(c && c.count) || items.length;
        done += items.filter((it) => handled(it)).length;
      }
      return Math.max(0, total - done);
    }
    const list = Array.isArray(bare) ? bare : [];
    return list.filter((m) => !handled({ message: m, forms: [] })).length;
  };
  const g = groupedIssues && typeof groupedIssues === "object" ? groupedIssues : null;
  const warnClusters = g && g.warnings && typeof g.warnings === "object"
    ? Object.values(g.warnings).flat() : null;
  const hard = tally(g ? g.hard_stops : null, hardStops);
  const warn = tally(warnClusters, softStops);
  const dc = (Array.isArray(consistencyFields) ? consistencyFields : []).filter((f) => f && f.status === "conflict").length;
  const section = hard > 0 ? "hardstops" : warn > 0 ? "warnings" : dc > 0 ? "consistency" : "overview";
  return { hardStops: hard, warnings: warn, dataConsistency: dc, total: hard + warn + dc, section };
}

// The offer line for one form the documents call for (never added on its own).
export function offerText(offer) {
  if (!offer) return "";
  const line = offer.line_label ? `Your documents now show ${offer.line_label}. ` : "";
  return `${line}${labelOf(offer)} is not in this package.`;
}

// Offers from the latest answer first, then any still pending on the package
// (a reload), one per form.
export function mergedOffers(latest, pending) {
  const out = [];
  const seen = new Set();
  for (const o of [...(Array.isArray(latest) ? latest : []), ...(Array.isArray(pending) ? pending : [])]) {
    if (!o || !o.form_id || seen.has(o.form_id)) continue;
    seen.add(o.form_id);
    out.push(o);
  }
  return out;
}

// The server's refusal for documents naming another insured (409).
export function integrityRefusal(status, body) {
  const detail = body && typeof body.detail === "object" ? body.detail : null;
  if (status !== 409 || !detail || detail.error !== "submission_integrity_review_required") return null;
  return {
    message: detail.message || "These documents name a different insured.",
    entities: (detail.integrity && detail.integrity.detected_entities) || [],
    canConfirm: !!detail.can_confirm,
  };
}

// A readable error from any other refusal.
export function errorText(body, fallback) {
  if (body && typeof body.detail === "string" && body.detail) return body.detail;
  if (body && body.detail && typeof body.detail.message === "string") return body.detail.message;
  if (body && typeof body.message === "string" && body.message) return body.message;
  return fallback;
}
