import { useEffect, useState } from "react";
import { ATTENTION_TAG_STYLE, attentionGroups, fetchNeedsAttention, isApplicantStep } from "../../utils/needsAttention";

// Orbin 22 Sep items 9 and 19 (30 Sep 2026): ONE list of the boxes that still
// need a human, read from the backend door `services/needs_attention.py`
// (GET /api/needs-attention). Every box has exactly one tag, and every count
// is the number of rows, so the side panel and the pre-download review can
// never disagree. Display only - nothing here changes a value or a score.

const scoreColor = (row) => (row?.score_effect > 0 ? "#b45309" : "#94a3b8");

function Tag({ status }) {
  const t = ATTENTION_TAG_STYLE[status] || ATTENTION_TAG_STYLE.missing;
  return (
    <span title={t.hint} style={{ background: t.bg, color: t.fg, fontSize: 9.5, fontWeight: 700, padding: "1px 6px", borderRadius: 9, whiteSpace: "nowrap" }}>
      {t.label}
    </span>
  );
}

function AttentionRow({ row, onJump }) {
  const clickable = typeof onJump === "function";
  const body = (
    <>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 6 }}>
        <span style={{ flex: 1, minWidth: 0, fontSize: 11, fontWeight: 600, color: "#0f172a", lineHeight: 1.35 }}>{row.label}</span>
        <Tag status={isApplicantStep(row) ? "applicant" : row.status} />
      </div>
      {row.status !== "missing" && row.reason && (
        <div style={{ fontSize: 10.5, color: "#475569", marginTop: 2, lineHeight: 1.4 }}>{row.reason}</div>
      )}
      {row.status === "ai_held_back" && row.required && (
        <div style={{ fontSize: 10, color: "#92400e", marginTop: 2 }}>Required on this form.</div>
      )}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 3, fontSize: 10.5 }}>
        <span style={{ color: "#334155" }}><b>What to do:</b> {row.what_to_do}</span>
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 2, fontSize: 10 }}>
        <span style={{ color: scoreColor(row), fontWeight: row.score_effect > 0 ? 700 : 500 }}>{row.score_text || "No score effect"}</span>
        {row.page ? <span style={{ color: "#64748b" }}>Page {row.page}</span> : null}
        {clickable && row.page ? <span style={{ color: "#E61B84", fontWeight: 600 }}>Show on form</span> : null}
      </div>
    </>
  );
  const style = { display: "block", width: "100%", textAlign: "left", background: "#fff", border: "1px solid #e2e8f0", borderRadius: 7, padding: "6px 8px", marginBottom: 4, fontFamily: "inherit" };
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
// `hideHeading`: a section that holds one status only (AI held back) does not
// repeat that status as a sub-heading under its own title.
function StatusGroups({ rows, onJump, showAll = false, hideHeading = false }) {
  const [expanded, setExpanded] = useState({});
  return attentionGroups(rows).map(g => {
    const mine = g.rows;
    const open = showAll || !!expanded[g.key];
    const shown = open ? mine : mine.slice(0, GROUP_PREVIEW);
    return (
      <div key={g.key} style={{ marginTop: 6 }}>
        {!hideHeading && (
          <div style={{ fontSize: 9.5, fontWeight: 700, color: g.fg, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 3 }}>
            {g.label} ({mine.length})
          </div>
        )}
        {shown.map(r => <AttentionRow key={`${r.form_id}:${r.field}`} row={r} onJump={onJump} />)}
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

// The two side-panel sections' (i) tips - short, like the other sections'.
export const NEEDS_ATTENTION_TIP = "Boxes on this form to fill in or check. Click one to see it on the form.";
export const AI_HELD_BACK_TIP = "The AI found a value that did not fit these boxes, so it left them blank. Check your documents and fill them in.";

// Side panel sections for the ACTIVE form (owner, 30 Sep 2026): "Needs
// attention" (Missing, the applicant's steps, Please verify) and "AI held
// back", drawn with the SAME collapsible section the Recommendations and
// Cross-Form Validation panels use (passed in as `Section`), every row listed.
// CLOSED by default like every other section (owner, 1 Oct 2026 retest); a
// section is only drawn when it has rows.
// Re-reads the list whenever the panel's own score state is replaced (Done
// Editing, a card answer, a questionnaire refresh, a re-stamp).
export default function NeedsAttentionPanel({ sessionId, formId, formSqs, packageSqs, refreshTick, onJump, Section }) {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);

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
  const rows = form.rows || [];
  const need = rows.filter(r => r.status !== "ai_held_back");
  const held = rows.filter(r => r.status === "ai_held_back");
  if (!need.length && !held.length) return null;

  return (
    <div data-testid="needs-attention-panel">
      {need.length > 0 && (
        <Section resetKey={formId} title={`Needs attention (${need.length})`} tooltip={NEEDS_ATTENTION_TIP}>
          <StatusGroups rows={need} onJump={onJump} showAll />
        </Section>
      )}
      {held.length > 0 && (
        <Section resetKey={formId} title={`AI held back (${held.length})`} tooltip={AI_HELD_BACK_TIP}>
          <StatusGroups rows={held} onJump={onJump} showAll hideHeading />
        </Section>
      )}
    </div>
  );
}

// Pre-download review and post-download checklist: the same rows, every form,
// named by form and by the box as the form prints it. Not clickable - the
// review is a last look, and the side panel is where boxes are fixed.
export function NeedsAttentionSummary({ attention }) {
  const forms = (attention?.forms || []).filter(f => (f.rows || []).length > 0);
  if (!forms.length) return null;
  const total = attention?.counts?.total ?? forms.reduce((s, f) => s + (f.rows || []).length, 0);
  return (
    <div data-testid="needs-attention-summary" style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 8, padding: "10px 12px", marginBottom: 10 }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: "#0f172a", marginBottom: 2 }}>Needs attention on the forms ({total})</div>
      <div style={{ fontSize: 10.5, color: "#64748b" }}>The same list as each form's side panel.</div>
      {forms.map(f => (
        <div key={f.form_id} style={{ marginTop: 8 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#334155" }}>
            {f.form_label}
            <span style={{ fontWeight: 500, color: "#64748b" }}>
              {" - "}{attentionGroups(f.rows).map(g => `${g.label} ${g.rows.length}`).join(", ")}
            </span>
          </div>
          <StatusGroups rows={f.rows} />
        </div>
      ))}
    </div>
  );
}
