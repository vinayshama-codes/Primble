import { DOCUMENTS_UPDATE_FORMS_TEXT } from "../../../utils/packageGeneration";

// The short confirm before a document change once forms exist (Choice Electric
// #25, 7 Oct 2026): changing a document's type, excluding it or keeping it as
// supporting only re-reads the package and re-stamps the generated forms.
// `pending.sameInsured` is the second question the server can ask - the
// document names another insured - and confirming it sends the change again
// with that answer.

const PINK = "#E61B84";

const ACTION_WORDS = {
  set_type: "Change the type of",
  exclude: "Exclude",
  include: "Include",
  supporting_only: "Keep as supporting only:",
};

export default function DocumentChangeConfirm({ pending, onConfirm, onCancel }) {
  if (!pending) return null;
  const verb = ACTION_WORDS[pending.action] || "Change";
  const title = pending.sameInsured ? "This document names a different insured" : DOCUMENTS_UPDATE_FORMS_TEXT;
  const body = pending.sameInsured
    ? (pending.message || "Include it only if it belongs to this insured.")
    : `${verb} ${pending.filename || "this document"}? Your generated forms are updated from the change; boxes you typed are kept.`;
  return (
    <div role="dialog" aria-modal="true" aria-label={title}
      style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,0.45)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1300, padding: 16 }}
      onClick={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
      <div style={{ background: "#fff", borderRadius: 10, maxWidth: 440, width: "100%", padding: "18px 20px", boxShadow: "0 20px 50px rgba(15,23,42,0.25)" }}>
        <div style={{ fontWeight: 700, fontSize: 15, color: "#1e293b", marginBottom: 8 }}>{title}</div>
        <div style={{ fontSize: 13, color: "#334155", lineHeight: 1.5 }}>{body}</div>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 16 }}>
          <button type="button" onClick={onCancel}
            style={{ fontSize: 13, fontWeight: 600, padding: "6px 14px", borderRadius: 6, border: "1px solid #cbd5e1", background: "#fff", color: "#334155", cursor: "pointer" }}>
            Cancel
          </button>
          <button type="button" onClick={onConfirm} autoFocus
            style={{ fontSize: 13, fontWeight: 600, padding: "6px 14px", borderRadius: 6, border: `1px solid ${PINK}`, background: PINK, color: "#fff", cursor: "pointer" }}>
            {pending.sameInsured ? "It belongs to this insured" : "Update forms"}
          </button>
        </div>
      </div>
    </div>
  );
}
