// Loss-run coverage (24 Oct 2026): the years the included loss runs cover,
// read off `packageSqs.loss_coverage` (backend `loss_history_state.
// loss_run_coverage`). Display only - the score is the backend's.

// One chip per required year, ending at the covered end year (or this year).
export function lossCoverageChips(cov) {
  if (!cov || typeof cov !== "object") return [];
  const required = Math.max(1, Number(cov.required) || 5);
  // No year covered yet: end at the latest year any loss-run document (included
  // or not) covers, so the chips do not shift when it is included (24 Oct 2026).
  const docYears = (cov.documents || []).flatMap((d) => (d && d.years) || []).map(Number).filter(Boolean);
  const end = Number(cov.end_year) || (docYears.length ? Math.max(...docYears) : new Date().getFullYear());
  const have = new Set((cov.years || []).map(Number));
  const out = [];
  for (let y = end - required + 1; y <= end; y += 1) out.push({ year: y, covered: have.has(y) });
  return out;
}

// "Loss runs now cover <label> - score <new> (<+/-diff>)" when the covered
// years changed; without the old score, just "Loss runs now cover <label>".
export function lossCoverageChangeText(before, after, oldScore, newScore) {
  if (!after || typeof after !== "object") return "";
  const was = before && typeof before === "object" ? Number(before.covered) : null;
  if (was !== null && was === Number(after.covered)) return "";
  const label = String(after.label || "").split(" (")[0];
  let text = `Loss runs now cover ${label}`;
  const o = Number(oldScore), n = Number(newScore);
  // The FIRST loss run (no coverage before - marking a file as Loss runs) moves
  // the score too: the message says so whenever both scores are known (audit,
  // 24 Oct 2026 - it read "Loss runs now cover 1 of 5 years" beside a +3).
  if (oldScore != null && newScore != null && Number.isFinite(o) && Number.isFinite(n)) {
    const d = n - o;
    text += ` - score ${n} (${d >= 0 ? "+" : ""}${d})`;
  }
  return text;
}

// The change message after ANY document change - add, exclude, include,
// reclassify, before forms or after (Z38 lane F): read off the package payload
// the screen held before and the one the change returned. A package with no
// loss run left carries no `loss_coverage`; when it had some, that reads as
// none covered ("Loss runs now cover 0 of 5 years"). `beforeDocs` (the
// document list held before the change): a payload without `loss_coverage`
// beside an included loss-run document is a payload that never carried it (a
// stored score), not "none covered" - nothing is said rather than a false change.
export function lossCoverageNoteFor(beforePkg, afterPkg, beforeDocs = null) {
  const before = beforePkg && typeof beforePkg === "object" ? beforePkg.loss_coverage || null : null;
  if (!afterPkg || typeof afterPkg !== "object") return "";
  if (!before && Array.isArray(beforeDocs)
      && beforeDocs.some((d) => d && !d.excluded && d.doc_type === "loss_run")) return "";
  let after = afterPkg.loss_coverage || null;
  if (!after && before && Number(before.covered) > 0) {
    const req = Math.max(1, Number(before.required) || 5);
    after = { covered: 0, required: req, label: `0 of ${req} year${req !== 1 ? "s" : ""}` };
  }
  return lossCoverageChangeText(before, after,
    beforePkg?.package_sqs_score ?? null, afterPkg.package_sqs_score ?? null);
}

// The text beside a loss-run document's name on the Documents page.
export function lossRunDocNote(cov, docId) {
  if (!cov || !Array.isArray(cov.documents) || !docId) return "";
  const d = cov.documents.find((x) => String(x.doc_id) === String(docId));
  if (!d) return "";
  if (!d.excluded) return d.years_label || "";
  const have = new Set((cov.years || []).map(Number));
  const extra = (d.years || []).map(Number).filter((y) => !have.has(y));
  if (!extra.length) return "Excluded";
  const span = extra.length === 1 ? `${extra[0]}` : `${extra[0]}-${extra[extra.length - 1]}`;
  return `Excluded - including it adds ${span}`;
}

// Whether the strip means anything yet (owner, 24 Oct 2026: "0 of 5 years" shown
// beside an unanswered claims question). Shown when some year is covered, or when
// the page asks for loss-run work (an upload / mark / ownership / years step) -
// never when the only Loss History step is the claims question itself.
export function showLossCoverage(cov, lossEntries) {
  if (!cov || typeof cov !== "object") return false;
  if (Number(cov.covered) > 0) return true;
  return (lossEntries || []).some((e) => {
    if (!e) return false;
    if (e.kind === "doc") return true;
    const keys = (e.item && e.item.keys) || [];
    return !keys.includes("fact:loss_history_no_prior_losses_indicator");
  });
}
