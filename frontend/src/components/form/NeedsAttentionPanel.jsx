import { useEffect, useState } from "react";
import { API_BASE } from "../../config/constants";
import { ATTENTION_TAG_STYLE, DOWNLOAD_GROUPS, attentionGroups, downloadReviewParts, fetchNeedsAttention, groupLineText, isApplicantStep } from "../../utils/needsAttention";
import { positiveScoreWording } from "../../utils/positiveWording";
import { formLabel } from "../../utils/formInstances";
import { confirmableRows, rowKey } from "../../utils/confirmValues";

// C103 (7 Oct 2026): a document added after forms that answers a box the AI
// filled at generation DIFFERENTLY never overwrites it - the backend stores a
// suggestion (services/session_documents.py) and this panel lists it as its
// own group, "New document", with "Use this value" (an ordinary box edit, run
// by the parent through the producer-edit door) and "Keep current".
async function fetchDocumentSuggestions(sessionId, formId, signal) {
  if (!sessionId || !formId) return [];
  const res = await fetch(`${API_BASE}/api/session/${sessionId}/documents/ai-fill?form_id=${encodeURIComponent(formId)}`,
    { credentials: "include", signal });
  if (!res.ok) return [];
  const data = await res.json();
  return data?.success && Array.isArray(data.suggestions) ? data.suggestions : [];
}

async function keepDocumentSuggestion(sessionId, id) {
  const res = await fetch(`${API_BASE}/api/session/${sessionId}/documents/suggestions/keep`, {
    method: "POST", credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ suggestion_id: id }),
  });
  return res.ok || res.status === 404;      // 404: already gone
}

export const DOCUMENT_SUGGESTIONS_TIP = "A document you added gives a different value for these boxes. Choose which one the form keeps.";

// Every action in this panel looks like "Open to fix" (owner, 14 Oct 2026: "the
// button should be same" - Show on form, Confirm, the New document choices): the
// same small pink outline button with the same chevron. A page number is a
// plain label, never a button.
export const FIX_LOOK = {
  display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 4,
  fontSize: 10, fontWeight: 700, lineHeight: 1.4, padding: "2px 9px", borderRadius: 6,
  border: "1px solid #f9a8d4", background: "#fdf2f8", color: "#be185d",
  fontFamily: "inherit", whiteSpace: "nowrap",
};
const smallBtn = (_primary, disabled) => ({
  ...FIX_LOOK, cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.6 : 1,
});
const PAGE_TEXT = { fontSize: 10, fontWeight: 600, color: "#64748b", whiteSpace: "nowrap" };
const Chevron = () => (
  <svg width="9" height="9" viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <path d="M3 2l4 4-4 4" stroke="#be185d" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

function SuggestionRow({ row, busy, onJump, onUse, onKeep }) {
  return (
    <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 7, padding: "6px 8px", marginBottom: 4 }}
      data-testid="document-suggestion">
      <div style={{ display: "flex", alignItems: "flex-start", gap: 6 }}>
        <button type="button" onClick={() => onJump && onJump(row)} title="Show this box on the form"
          style={{ flex: 1, minWidth: 0, textAlign: "left", background: "none", border: "none", padding: 0, cursor: onJump ? "pointer" : "default", fontFamily: "inherit", fontSize: 11, fontWeight: 600, color: "#0f172a", lineHeight: 1.35 }}>
          {row.label}
        </button>
        <span style={{ background: "#ede9fe", color: "#5b21b6", fontSize: 9.5, fontWeight: 700, padding: "1px 6px", borderRadius: 9, whiteSpace: "nowrap" }}>{row.tag || "New document"}</span>
      </div>
      <div style={{ fontSize: 10.5, color: "#475569", marginTop: 2, lineHeight: 1.4 }}>{row.reason}</div>
      {Array.isArray(row.documents) && row.documents.length > 0 && (
        <div style={{ fontSize: 10, color: "#64748b", marginTop: 1 }}>From {row.documents.join(", ")}</div>
      )}
      <div style={{ display: "flex", gap: 6, marginTop: 5, alignItems: "center" }}>
        <button type="button" style={smallBtn(true, busy)} disabled={busy} onClick={() => onUse(row)}>Use this value</button>
        <button type="button" style={smallBtn(false, busy)} disabled={busy} onClick={() => onKeep(row)}>Keep current</button>
        {row.page ? <span style={{ fontSize: 10, color: "#64748b" }}>Page {row.page}</span> : null}
      </div>
    </div>
  );
}

function DocumentSuggestions({ sessionId, formId, refreshTick, onJump, onApplySuggestion, Section }) {
  const [rows, setRows] = useState([]);
  const [busy, setBusy] = useState(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!sessionId || !formId) return undefined;
    const ctrl = new AbortController();
    fetchDocumentSuggestions(sessionId, formId, ctrl.signal)
      .then(list => { if (!ctrl.signal.aborted) setRows(list); })
      .catch(() => { /* the group is advisory - a failed read shows nothing */ });
    return () => ctrl.abort();
  }, [sessionId, formId, refreshTick, tick]);

  if (!rows.length || !Section) return null;
  const act = async (row, fn) => {
    setBusy(row.id);
    try { if (await fn(row)) setRows(prev => prev.filter(r => r.id !== row.id)); }
    finally { setBusy(null); setTick(t => t + 1); }
  };
  return (
    <Section resetKey={formId} title={`New document (${rows.length})`} tooltip={DOCUMENT_SUGGESTIONS_TIP}>
      {rows.map(r => (
        <SuggestionRow key={r.id || `${r.form_id}:${r.field}`} row={r} busy={busy === r.id} onJump={onJump}
          onUse={(row) => act(row, async (x) => (typeof onApplySuggestion === "function" ? !!(await onApplySuggestion(x)) : false))}
          onKeep={(row) => act(row, (x) => keepDocumentSuggestion(sessionId, x.id))} />
      ))}
    </Section>
  );
}

// Orbin 22 Sep items 9 and 19 (30 Sep 2026): ONE list of the boxes that still
// need a human, read from the backend door `services/needs_attention.py`
// (GET /api/needs-attention). Every box has exactly one tag, and every count
// is the number of rows, so the side panel and the pre-download review can
// never disagree. Display only - nothing here changes a value or a score.

const scoreColor = (row) => (row?.score_effect > 0 ? "#b45309" : "#94a3b8");

// The line a row of the download gate carries (backend `blocks_download`).
export const BLOCKS_DOWNLOAD_TEXT = "Blocks a clean download until it is fixed.";

function Tag({ status }) {
  const t = ATTENTION_TAG_STYLE[status] || ATTENTION_TAG_STYLE.missing;
  return (
    <span title={t.hint} style={{ background: t.bg, color: t.fg, fontSize: 9.5, fontWeight: 700, padding: "1px 6px", borderRadius: 9, whiteSpace: "nowrap" }}>
      {t.label}
    </span>
  );
}

// "Confirm" on a Please verify row (13 Oct 2026, owner + Brent: the SQS reaches
// 100 after forms once everything is answered or checked). Keeps the value and
// marks it checked by the producer - the same producer-edit door a typed value
// takes - so it stops counting as unconfirmed.
export const CONFIRM_TIP = "Keep this value. It is marked as checked by you.";
export const CONFIRM_ALL_TIP = "Keep every value in this list. Each is marked as checked by you.";

// "Page 3" above "Show on form" at the row's right, each on one line (owner, 13 Oct
// 2026), never wrapped to "Page / 3"; the page is a plain label and the button is
// the panel's one button look (owner, 14 Oct 2026). The row itself is the click.

// `busy`: THIS row's confirm is being saved. `locked`: another confirm is in
// flight - the button waits (two saves of one form must not race) but keeps its
// own label (owner, 13 Oct 2026: one click showed "Confirming..." on every row).
function AttentionRow({ row, onJump, onConfirm, busy = false, locked = false }) {
  const clickable = typeof onJump === "function";
  const confirmable = typeof onConfirm === "function" && row.status === "verify";
  const body = (
    <>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 6 }}>
        <span style={{ flex: 1, minWidth: 0, fontSize: 11, fontWeight: 600, color: "#0f172a", lineHeight: 1.35 }}>{row.label}</span>
        <Tag status={isApplicantStep(row) ? "applicant" : row.status} />
      </div>
      {/* A Missing row's reason is the same sentence every time - except a
          download-gate box and a Figure 33 finding, which say why. */}
      {(row.status !== "missing" || row.blocks_download || row.finding) && row.reason && (
        <div style={{ fontSize: 10.5, color: "#475569", marginTop: 2, lineHeight: 1.4 }}>{row.reason}</div>
      )}
      {/* A box the download gate holds (14 Oct 2026): said here, before the
          download review lists it as a hard stop. */}
      {row.blocks_download && (
        <div data-testid="blocks-download" style={{ fontSize: 10, fontWeight: 700, color: "#b91c1c", marginTop: 2 }}>{BLOCKS_DOWNLOAD_TEXT}</div>
      )}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 3, fontSize: 10.5 }}>
        <span style={{ color: "#334155" }}><b>What to do:</b> {row.what_to_do}</span>
      </div>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 8, marginTop: 3, fontSize: 10 }}>
        <span style={{ flex: "1 1 auto", minWidth: 0, color: scoreColor(row), fontWeight: row.score_effect > 0 ? 700 : 500 }}>{row.score_text || "No score effect"}</span>
        {row.page ? (
          <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 3, flexShrink: 0 }}>
            <span style={PAGE_TEXT}>Page {row.page}</span>
            {clickable ? <span style={FIX_LOOK}>Show on form <Chevron /></span> : null}
          </span>
        ) : null}
      </div>
    </>
  );
  const style = { display: "block", width: "100%", textAlign: "left", background: "#fff", border: "1px solid #e2e8f0", borderRadius: 7, padding: "6px 8px", marginBottom: 4, fontFamily: "inherit" };
  if (confirmable) {
    // Two actions on one row: its text shows the box, the button confirms it
    // (a button never sits inside another button).
    return (
      <div style={style} data-testid="verify-row">
        {clickable ? (
          <button type="button" onClick={() => onJump(row)} title="Show this box on the form"
            style={{ display: "block", width: "100%", textAlign: "left", background: "none", border: "none", padding: 0, cursor: "pointer", fontFamily: "inherit" }}>
            {body}
          </button>
        ) : body}
        <div style={{ display: "flex", gap: 6, marginTop: 5 }}>
          <button type="button" style={smallBtn(true, busy || locked)} disabled={busy || locked} title={CONFIRM_TIP}
            onClick={() => onConfirm([row])}>{busy ? "Confirming..." : "Confirm"}</button>
        </div>
      </div>
    );
  }
  if (!clickable) return <div style={style}>{body}</div>;
  return (
    <button type="button" onClick={() => onJump(row)} style={{ ...style, cursor: "pointer" }}
      aria-label={`${row.label}: ${ATTENTION_TAG_STYLE[isApplicantStep(row) ? "applicant" : row.status]?.label || ""}. Show this box on the form.`}>
      {body}
    </button>
  );
}

const GROUP_PREVIEW = 6;

// `showAll`: the side panel's sections list every row once opened (owner,
// 30 Sep 2026); the pre-download review keeps its short preview.
// `hideHeading`: a list that holds one status only does not repeat that status
// as a sub-heading under its own title.
// `confirmingKeys`: the rows whose confirm is being saved (`rowKey`), so only
// those say "Confirming..." - and "Confirm all" only when it is the one saving.
function StatusGroups({ rows, onJump, showAll = false, hideHeading = false, onConfirm = null, confirmingKeys = null }) {
  const [expanded, setExpanded] = useState({});
  const saving = confirmingKeys instanceof Set ? confirmingKeys : new Set();
  const locked = saving.size > 0;
  return attentionGroups(rows).map(g => {
    const mine = g.rows;
    const open = showAll || !!expanded[g.key];
    const shown = open ? mine : mine.slice(0, GROUP_PREVIEW);
    const confirmAll = typeof onConfirm === "function" && g.key === "verify" && mine.length > 1;
    const allSaving = locked && confirmableRows(mine).length > 1
      && confirmableRows(mine).every(r => saving.has(rowKey(r)));
    return (
      <div key={g.key} style={{ marginTop: 6 }}>
        {!hideHeading && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3 }}>
            <div style={{ flex: "1 1 auto", fontSize: 9.5, fontWeight: 700, color: g.fg, textTransform: "uppercase", letterSpacing: "0.05em" }}>
              {g.label} ({mine.length})
            </div>
            {confirmAll && (
              <button type="button" style={smallBtn(false, locked)} disabled={locked} title={CONFIRM_ALL_TIP}
                onClick={() => onConfirm(mine)} data-testid="confirm-all">
                {allSaving ? "Confirming..." : `Confirm all ${mine.length}`}
              </button>
            )}
          </div>
        )}
        {shown.map(r => (
          <AttentionRow key={`${r.form_id}:${r.field}`} row={r} onJump={onJump} onConfirm={onConfirm}
            busy={saving.has(rowKey(r))} locked={locked} />
        ))}
        {!showAll && mine.length > GROUP_PREVIEW && (
          <button type="button" onClick={() => setExpanded(e => ({ ...e, [g.key]: !open }))}
            style={{ background: "none", border: "none", color: "#E61B84", fontSize: 10.5, fontWeight: 600, cursor: "pointer", padding: "2px 0" }}>
            {open ? "Show fewer" : `Show all ${mine.length}`}
          </button>
        )}
      </div>
    );
  });
}

// The side-panel section's (i) tip - short, like the other sections'.
export const NEEDS_ATTENTION_TIP = "Boxes on this form to fill in or check. Click one to see it on the form.";

// The side panel section for the ACTIVE form (owner, 30 Sep 2026): "Needs
// attention" (Missing, the applicant's steps, Please verify), drawn with the
// SAME collapsible section the Recommendations and Cross-Form Validation panels
// use (passed in as `Section`), every row listed. CLOSED by default like every
// other section (owner, 1 Oct 2026 retest); drawn only when it has rows. The
// "AI held back" section is gone (Brent, 23 Oct 2026: "Users only need to see
// relevant information. The audit record is fine.") - refused AI values are
// the audit record's; a refused question or detail comes as Missing.
// Re-reads the list whenever the panel's own score state is replaced (Done
// Editing, a card answer, a questionnaire refresh, a re-stamp).
export default function NeedsAttentionPanel({ sessionId, formId, formSqs, packageSqs, refreshTick, onJump, Section, onApplySuggestion, onConfirmValues }) {
  const suggestions = (
    <DocumentSuggestions sessionId={sessionId} formId={formId} refreshTick={refreshTick}
      onJump={onJump} onApplySuggestion={onApplySuggestion} Section={Section} />
  );
  return (
    <>
      {suggestions}
      <NeedsAttentionSections sessionId={sessionId} formId={formId} formSqs={formSqs} packageSqs={packageSqs}
        refreshTick={refreshTick} onJump={onJump} Section={Section} onConfirmValues={onConfirmValues} />
    </>
  );
}

function NeedsAttentionSections({ sessionId, formId, formSqs, packageSqs, refreshTick, onJump, Section, onConfirmValues }) {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  // The rows being saved right now (`rowKey`s) - only they say "Confirming..."
  // (owner, 13 Oct 2026). One save at a time: the others wait.
  const [confirmingKeys, setConfirmingKeys] = useState(() => new Set());
  // Confirmed rows leave the list at once; the next read (the score moved)
  // replaces it with the server's own list.
  const confirm = typeof onConfirmValues === "function" ? async (list) => {
    const picked = confirmableRows(list);
    if (!picked.length || confirmingKeys.size > 0) return;
    const keys = new Set(picked.map(rowKey));
    setConfirmingKeys(keys);
    try {
      if (await onConfirmValues(picked)) {
        setData(d => (d ? { ...d, forms: (d.forms || []).map(f => ({ ...f, rows: (f.rows || []).filter(r => !keys.has(rowKey(r))) })) } : d));
      }
    } finally {
      setConfirmingKeys(new Set());
    }
  } : null;

  useEffect(() => {
    if (!sessionId || !formId) return undefined;
    const ctrl = new AbortController();
    fetchNeedsAttention(sessionId, formId, ctrl.signal)
      .then(d => { if (!ctrl.signal.aborted) { setData(d); setFailed(!d); } })
      .catch(err => { if (err?.name !== "AbortError") setFailed(true); });
    return () => ctrl.abort();
  }, [sessionId, formId, formSqs, packageSqs, refreshTick]);

  if (!formId || !Section || (failed && !data)) return null;
  const form = (data?.forms || []).find(f => f.form_id === formId);
  if (!form) return null;
  // The rows the groups draw - one split (`attentionGroups`), so the count is
  // what is listed and a stale row of a retired status is never counted.
  const need = attentionGroups(form.rows).flatMap(g => g.rows);
  if (!need.length) return null;

  return (
    <div data-testid="needs-attention-panel">
      <Section resetKey={formId} title={`Needs attention (${need.length})`} tooltip={NEEDS_ATTENTION_TIP}>
        <StatusGroups rows={need} onJump={onJump} showAll onConfirm={confirm} confirmingKeys={confirmingKeys} />
      </Section>
    </div>
  );
}

// THE DOWNLOAD REVIEW'S LIST - both download screens (the pre-download review
// and the post-download checklist) draw exactly this (owner, 14 Oct 2026). One
// by one: the items to fix - Hard Stops (the download gate's boxes included),
// Warnings, Missing boxes, Recommendations. Then "Please verify", the
// applicant's steps and new-document choices as ONE line each, with
// its count and Show, which opens the group in place. Not clickable - the
// review is a last look, and the side panel is where boxes are fixed.
const pts = (r) => (typeof r?.score_impact === "number" && r.score_impact > 0 ? r.score_impact : 0);
const plusPoints = (r) => (pts(r) ? (r.impact_is_exact === true ? `+${pts(r)} pts` : `up to +${pts(r)} pts`) : "");
const formsOf = (r) => (Array.isArray(r?.forms) && r.forms.length ? r.forms : []);

function RecBox({ title, rows, tone, testId }) {
  if (!rows.length) return null;
  const t = {
    hard: { bg: "#fef2f2", border: "#fca5a5", head: "#991b1b", text: "#7f1d1d", pts: "#dc2626" },
    warn: { bg: "#fffbeb", border: "#fde68a", head: "#92400e", text: "#78350f", pts: "#d97706" },
    rec:  { bg: "#f8fafc", border: "#e2e8f0", head: "#334155", text: "#334155", pts: "#d97706" },
  }[tone];
  return (
    <div data-testid={testId} style={{ background: t.bg, border: `1px solid ${t.border}`, borderRadius: 8, padding: "10px 12px", marginBottom: 10 }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: t.head, marginBottom: 6 }}>{title} ({rows.length})</div>
      {rows.map((r, i) => (
        <div key={`${r.rec_id || ""}:${i}`} style={{ fontSize: 12, color: t.text, padding: "2px 0", lineHeight: 1.45 }}>
          {"• "}
          {formsOf(r).length > 0 && <span style={{ fontWeight: 700, color: "#E61B84" }}>{formsOf(r).map(formLabel).join(", ")}: </span>}
          {positiveScoreWording(r.message)}
          {tone === "hard"
            ? (pts(r) ? <span style={{ color: t.pts, fontWeight: 700 }}> (-{pts(r)} pts)</span> : null)
            : (plusPoints(r) ? <span style={{ color: t.pts, fontWeight: 600 }}> ({plusPoints(r)})</span> : null)}
        </div>
      ))}
    </div>
  );
}

function SuggestionLines({ rows }) {
  return (
    <div data-testid="document-suggestions-summary">
      <div style={{ fontSize: 10.5, color: "#64748b", marginTop: 4 }}>A document you added says something different. Choose in the form's side panel.</div>
      {rows.map((s) => (
        <div key={s.id || `${s.form_id}:${s.field}`} style={{ fontSize: 11.5, color: "#334155", marginTop: 6, lineHeight: 1.45 }}>
          <strong>{s.form_label}</strong>{" - "}{s.label}: the document says {s.suggested_display || s.suggested}, the form says {s.current_display || s.current || "nothing"}
        </div>
      ))}
    </div>
  );
}

function FormRows({ groups, heading = false }) {
  return groups.map((f) => (
    <div key={f.form_id} style={{ marginTop: 8 }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: "#334155" }}>{f.form_label}</div>
      <StatusGroups rows={f.rows} showAll hideHeading={!heading} />
    </div>
  ));
}

export function DownloadReviewList({ openRecs, attention }) {
  const [open, setOpen] = useState({});
  const p = downloadReviewParts(openRecs, attention);
  const missingCount = p.missing.reduce((n, f) => n + f.rows.length, 0);
  const groupRows = { verify: p.verify, applicant: p.applicant, choices: p.choices };
  const groupCount = (key) => (key === "choices" ? p.choices.length
    : groupRows[key].reduce((n, f) => n + f.rows.length, 0));
  const lines = DOWNLOAD_GROUPS.filter((g) => groupCount(g.key) > 0);
  return (
    <div data-testid="download-review-list">
      <RecBox title="Hard Stops" rows={p.hard} tone="hard" testId="download-hard-stops" />
      <RecBox title="Warnings" rows={p.warnings} tone="warn" testId="download-warnings" />
      {missingCount > 0 && (
        <div data-testid="download-missing" style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 8, padding: "10px 12px", marginBottom: 10 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#92400e" }}>Missing on the forms ({missingCount})</div>
          <FormRows groups={p.missing} />
        </div>
      )}
      <RecBox title="Recommendations" rows={p.recommendations} tone="rec" testId="download-recommendations" />
      {lines.length > 0 && (
        <div data-testid="download-groups" style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 8, padding: "8px 12px", marginBottom: 10 }}>
          {lines.map((g) => (
            <div key={g.key} data-testid={`download-group-${g.key}`} style={{ padding: "4px 0" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ flex: 1, fontSize: 12, fontWeight: 600, color: "#334155" }}>{groupLineText(g.key, groupCount(g.key))}</span>
                <button type="button" onClick={() => setOpen((o) => ({ ...o, [g.key]: !o[g.key] }))}
                  aria-expanded={!!open[g.key]}
                  style={{ ...FIX_LOOK, cursor: "pointer" }}>
                  {open[g.key] ? "Hide" : "Show"}
                </button>
              </div>
              {open[g.key] && (g.key === "choices"
                ? <SuggestionLines rows={p.choices} />
                : <FormRows groups={groupRows[g.key]} />)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
