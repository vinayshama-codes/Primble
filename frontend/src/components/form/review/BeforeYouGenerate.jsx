// BeforeYouGenerate.jsx - the form checks the download review runs, shown
// BEFORE the forms are generated (Choice Electric #27, 7 Oct 2026).
//
// Brent: "We have already asked for these items to be addressed at the start
// of the packaging and not keep it at the end ... these are hard stops. This
// should all be brought up sooner ... ensure they are accurate requests to
// complete." The backend stamps the forms that will be generated (no AI, no
// document reading) and runs the download review's own checks on them
// (services/form_dry_run.py); this block lists only what a person must supply
// here, grouped by form, each with "Open to fix" in the page's usual fix
// window. What blocks a clean download is marked.
//
// Presentation only: the payload arrives with every pre-form response
// (`dry_run`); while a run is still going (`pending`) this block polls the
// dry-run route a few times, and re-checks when the producer's ticked forms
// change. Used by the rail layout (Overview) and the classic review step.

import { useEffect, useRef, useState } from "react";
import {
  DRY_RUN_PENDING, DRY_RUN_READY, DRY_RUN_SKIPPED,
  dryRunMatchesTicks, fetchDryRun, itemsText,
} from "../../../utils/dryRun";

const PINK = "#E61B84";
const MAX_POLLS = 12;
const POLL_MS = 2500;

const box = { background: "#fff", border: "1px solid #e2e8f0", borderRadius: 10, padding: "14px 16px", marginBottom: 14 };
const muted = { fontSize: 12, color: "#64748b", lineHeight: 1.5 };
const linkBtn = { font: "inherit", fontSize: 12, fontWeight: 600, background: "none", border: "none", padding: 0, color: PINK, textDecoration: "underline", textUnderlineOffset: 2, cursor: "pointer", whiteSpace: "nowrap" };
const blockTag = { fontSize: 10, fontWeight: 700, color: "#991b1b", background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 10, padding: "1px 7px", whiteSpace: "nowrap" };

// Composed by the Recommendations section (7 Oct 2026) as its "Your forms
// will need" group: `bare` drops the card frame, `title` names the block (null
// = none), and `hiddenIds` are items the page already asks for elsewhere (a
// Hard Stop / Warning card, a key detail, "Raise your score" - one to-do, one
// place). Counts are of what is listed.
export default function BeforeYouGenerate({
  dryRun, sessionId, tickedFormIds = [], onUpdate, onOpenFix, className = "",
  title = "Before you generate", bare = false, hiddenIds = null,
}) {
  const [tick, setTick] = useState(0);
  const [checking, setChecking] = useState(false);
  const polls = useRef({ key: null, n: 0 });
  const ticksKey = (tickedFormIds || []).filter(Boolean).join(",");
  const status = dryRun?.status;
  const fingerprint = dryRun?.fingerprint || "";

  // A run still going: ask again a few times, then stop (the producer can
  // press "Check again"). A new state (fingerprint) starts a fresh count.
  useEffect(() => {
    if (!sessionId || status !== DRY_RUN_PENDING) return undefined;
    if (polls.current.key !== fingerprint) polls.current = { key: fingerprint, n: 0 };
    if (polls.current.n >= MAX_POLLS) return undefined;
    let alive = true;
    const t = setTimeout(async () => {
      polls.current.n += 1;
      const next = await fetchDryRun(sessionId, tickedFormIds, 8);
      if (!alive) return;
      if (next) onUpdate?.(next);
      setTick((n) => n + 1);
    }, POLL_MS);
    return () => { alive = false; clearTimeout(t); };
  }, [sessionId, status, fingerprint, tick]);  // eslint-disable-line react-hooks/exhaustive-deps

  // The producer's ticked forms changed: check exactly those (no ticks again:
  // back to the recommended forms).
  useEffect(() => {
    if (!sessionId || !dryRun || dryRunMatchesTicks(dryRun, tickedFormIds)) return undefined;
    let alive = true;
    (async () => {
      const next = await fetchDryRun(sessionId, tickedFormIds, 6);
      if (alive && next) onUpdate?.(next);
    })();
    return () => { alive = false; };
  }, [sessionId, ticksKey]);  // eslint-disable-line react-hooks/exhaustive-deps

  if (!dryRun) return null;

  const checkAgain = async () => {
    setChecking(true);
    polls.current = { key: fingerprint, n: 0 };
    const next = await fetchDryRun(sessionId, tickedFormIds, 12);
    setChecking(false);
    if (next) onUpdate?.(next);
  };

  const allForms = Array.isArray(dryRun.forms) ? dryRun.forms : [];
  const isHidden = (it) => !!(hiddenIds && it && hiddenIds.has(it.id));
  const forms = hiddenIds
    ? allForms.map((f) => ({ ...f, items: (f.items || []).filter((it) => !isHidden(it)) }))
      .filter((f) => f.items.length > 0)
      .map((f) => ({ ...f, count: f.items.length }))
    : allForms;
  const count = hiddenIds ? forms.reduce((n, f) => n + f.items.length, 0) : (Number(dryRun.count) || 0);
  const blocking = hiddenIds
    ? forms.reduce((n, f) => n + f.items.filter((it) => it.blocks_download).length, 0)
    : (Number(dryRun.blocking_count) || 0);
  const elsewhere = hiddenIds ? allForms.reduce((n, f) => n + (f.items || []).filter(isHidden).length, 0) : 0;
  const checked = (dryRun.checked_forms || []).map((f) => f.form_label).filter(Boolean);
  // Nothing was checked (no recommended form yet): no promise to make.
  if (status === DRY_RUN_READY && checked.length === 0) return null;
  const droppedBlocking = Array.isArray(dryRun.dropped_blocking) ? dryRun.dropped_blocking : [];

  let summary;
  if (status === DRY_RUN_PENDING) summary = "Checking the forms you will generate...";
  else if (status === DRY_RUN_SKIPPED) summary = dryRun.reason || "The forms could not be checked yet.";
  else if (count === 0 && elsewhere > 0) summary = "Nothing more to add - what the forms need is already asked for above.";
  else if (count === 0) summary = "Nothing to complete - the forms checked have what they need from you.";
  else summary = `${itemsText(count)} to complete before you generate${blocking ? ` - ${blocking} block${blocking === 1 ? "s" : ""} a clean download` : ""}.`;

  return (
    <section className={className} style={bare ? undefined : box} aria-label={title || "Before you generate"} data-dry-run-status={status || ""}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: "#0f172a", flex: "1 1 auto" }}>{title || null}</div>
        {/* Inside the Recommendations group (`bare`) the group's title carries the count. */}
        {status === DRY_RUN_READY && count > 0 && !bare && (
          <span style={{ fontSize: 11, fontWeight: 700, color: "#fff", background: blocking ? "#dc2626" : PINK, borderRadius: 10, padding: "1px 8px" }}>{count}</span>
        )}
        {status !== DRY_RUN_PENDING && (
          <button type="button" style={linkBtn} disabled={checking} onClick={checkAgain}>
            {checking ? "Checking..." : "Check again"}
          </button>
        )}
      </div>
      <div style={{ ...muted, display: "flex", alignItems: "center", gap: 8 }}>
        {status === DRY_RUN_PENDING && (
          <span style={{ width: 12, height: 12, border: "2px solid #e2e8f0", borderTopColor: PINK, borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite", flexShrink: 0 }} />
        )}
        <span>{summary}</span>
      </div>
      {checked.length > 0 && (
        <div style={{ ...muted, fontSize: 11.5, marginTop: 4 }}>
          Checked against {dryRun.form_source === "selected" ? "the forms you ticked" : "the recommended forms"}: {checked.join(", ")}.
        </div>
      )}
      {status === DRY_RUN_READY && count > 0 && elsewhere > 0 && (
        <div style={{ ...muted, fontSize: 11.5, marginTop: 2 }}>
          {itemsText(elsewhere)} more {elsewhere === 1 ? "is" : "are"} already asked for above.
        </div>
      )}

      {status === DRY_RUN_READY && forms.map((form) => (
        <div key={form.form_id} style={{ marginTop: 12 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: "#334155", marginBottom: 4 }}>
            {form.form_label} <span style={{ fontWeight: 500, color: "#94a3b8" }}>({itemsText(form.count)})</span>
          </div>
          {(form.items || []).map((item) => (
            <div key={item.id} style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "7px 0", borderTop: "1px solid #f1f5f9" }}>
              <div style={{ flex: "1 1 auto", minWidth: 0 }}>
                <div style={{ fontSize: 12.5, color: "#1e293b", fontWeight: 600, lineHeight: 1.4 }}>{item.label}</div>
                <div style={{ ...muted, fontSize: 11.5 }}>{item.what_to_do}</div>
              </div>
              {item.blocks_download && <span style={blockTag}>Blocks a clean download</span>}
              {item.resolution && onOpenFix && (
                <button type="button" style={linkBtn} onClick={() => onOpenFix(item)}>Open to fix</button>
              )}
            </div>
          ))}
        </div>
      ))}

      {status === DRY_RUN_READY && droppedBlocking.length > 0 && (
        <div style={{ marginTop: 12, fontSize: 12, color: "#7f1d1d", background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 8, padding: "8px 10px", lineHeight: 1.5 }}>
          Also needed for a clean download, but only fillable on the form once it is generated:{" "}
          {droppedBlocking.map((b) => `${b.label} (${b.form_label})`).join("; ")}.
        </div>
      )}

      {/* No "Why other boxes are not listed" breakdown before generation (owner,
          13 Oct 2026): nothing in it can be acted on yet, it counts boxes nobody
          can see, and each line has a home after generation - the editor's AI held
          back / Please verify panels and its Missing list. The counts stay in the
          dry run's payload (`dropped`). */}
    </section>
  );
}
