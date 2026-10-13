// "Confirm" on Please verify rows (13 Oct 2026, owner + Brent: the SQS reaches
// 100 after forms once everything is answered or checked). A Please verify row
// keeps its value and becomes the producer's - sent through the producer-edit
// door (update-pdf), which labels a sent value "producer" without changing it.
//
// Pure functions, no React and no import.meta: the backend suite runs them
// under node.

export const rowKey = (r) => `${r?.form_id || ""}:${r?.field || ""}`;

// The rows a Confirm may send: Please verify rows that carry their value.
export function confirmableRows(rows) {
  const seen = new Set();
  return (Array.isArray(rows) ? rows : []).filter((r) => {
    if (!r || r.status !== "verify" || !r.field || r.value === null || r.value === undefined) return false;
    if (!String(r.value).trim() || seen.has(rowKey(r))) return false;
    seen.add(rowKey(r));
    return true;
  });
}

// The update-pdf body for confirming `rows` on ONE form - every row's own value,
// unchanged. Rows of another form are left out (the door saves one form).
export function confirmFieldUpdates(formId, rows) {
  if (!formId) return null;
  const picked = confirmableRows(rows).filter((r) => r.form_id === formId);
  if (!picked.length) return null;
  const updates = { __form_id__: formId };
  for (const r of picked) updates[r.field] = String(r.value);
  return updates;
}

