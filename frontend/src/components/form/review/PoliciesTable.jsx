import { useEffect, useMemo, useState } from "react";
import { API_BASE } from "../../../config/constants";
import "./PoliciesTable.css";

// "Policies in this submission" (Brent, Choice Electric #9, 7 Oct 2026):
// correct a policy's carrier / NAIC / policy number / term / premium, add a
// policy the documents do not show, remove one you added. Used by BOTH review
// layouts (rail and classic) - each draws its own frame around this body.
//
// The server decides everything (services/policy_lines.py): what a field may
// hold, which rows a correction reaches, what a change re-stamps. This
// component only collects the values and shows the server's field errors.
// `rows` is `underwriting_consistency.policy_lines`; an older payload without
// it passes `legacyRecs` and gets the read-only table it always had.

const FIELDS = [
  { key: "carrier_name", label: "Carrier", placeholder: "Insurance company" },
  { key: "carrier_naic", label: "NAIC", placeholder: "5 digits" },
  { key: "policy_number", label: "Policy number", placeholder: "Policy number" },
  { key: "effective_date", label: "Effective", placeholder: "MM/DD/YYYY" },
  { key: "expiration_date", label: "Expiration", placeholder: "MM/DD/YYYY" },
  { key: "premium", label: "Premium", placeholder: "$0" },
];

// An umbrella / excess policy the PRODUCER adds carries its own limits and SIR
// (its ACORD 131 copy prints nothing without them). A document's policy takes
// its limits from the documents, so these boxes never appear for one.
const LIMIT_FIELDS = [
  { key: "limit_each_occurrence", label: "Each occurrence limit", placeholder: "$0" },
  { key: "limit_aggregate", label: "Aggregate limit", placeholder: "$0" },
  { key: "sir", label: "SIR", placeholder: "$0" },
];
const UMBRELLA_LINE_KEYS = new Set(["umbrella", "excess"]);
const limitsFor = (r) => !!r?.producer_added && r?.line === "umbrella";

const EMPTY_DRAFT = Object.fromEntries([...FIELDS, ...LIMIT_FIELDS].map((f) => [f.key, ""]));

// Brent #10 (7 Oct 2026): the "N policies, M values - not a conflict" blocks
// under this table are gone; what they showed lives here instead - each
// policy's OWN limit (`limit_parts`, read by the server from that policy's own
// line / layer, display only) and "Group by carrier". A producer-added umbrella
// or excess layer's limits stay editable through its Edit form (the only limits
// the server accepts from a person); every other limit comes from the documents.
function LimitCell({ r }) {
  const parts = Array.isArray(r.limit_parts) ? r.limit_parts.filter((p) => p && p.amount) : [];
  if (!parts.length) return "-";
  return parts.map((p, i) => (
    <div key={i} className="pt-limit">
      <span className="pt-limit__amount">{p.amount}</span>{p.label ? <span className="pt-muted"> {p.label}</span> : null}
    </div>
  ));
}

// A stated premium as a number ("$16,818" -> 16818), else null.
function premiumAmount(text) {
  const s = String(text || "").replace(/[^0-9.]/g, "");
  if (!s || (s.match(/\./g) || []).length > 1) return null;
  const n = Number(s);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function money(n) {
  const cents = Math.round(n * 100) % 100 !== 0;
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: cents ? 2 : 0, maximumFractionDigits: 2 })}`;
}

// One group per company - the server's comparison key, else the printed name.
const carrierKeyOf = (r) => r.carrier_key
  || String(r.carrier_name || "").trim().toLowerCase().replace(/[^a-z0-9&]/g, "");

const SORT_COLUMNS = { line: "Line", carrier: "Carrier", premium: "Premium" };

function SortHeader({ col, sort, onSort }) {
  const active = sort.key === col;
  const mark = active ? (sort.dir === "asc" ? "\u25B2" : "\u25BC") : "\u21C5";
  return (
    <th aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}>
      <button type="button" className={`pt-sort-btn${active ? " is-active" : ""}`}
        title={`Sort by ${SORT_COLUMNS[col].toLowerCase()}`}
        onClick={() => onSort(col)}>
        {SORT_COLUMNS[col]}<span className="pt-sort-mark" aria-hidden="true">{mark}</span>
      </button>
    </th>
  );
}

function normaliseDate(s) {
  const t = String(s || "").trim();
  let m = /^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2}|\d{4})$/.exec(t);
  if (m) {
    const y = m[3].length === 2 ? `${Number(m[3]) > 69 ? "19" : "20"}${m[3]}` : m[3];
    return `${m[1].padStart(2, "0")}/${m[2].padStart(2, "0")}/${y}`;
  }
  m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(t);
  return m ? `${m[2]}/${m[3]}/${m[1]}` : t;
}

function term(r) {
  if (!r.effective_date && !r.expiration_date) return "-";
  return `${normaliseDate(r.effective_date) || "?"} - ${normaliseDate(r.expiration_date) || "?"}`;
}

function PencilIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" />
    </svg>
  );
}

async function readJson(res) {
  try { return await res.json(); } catch { return {}; }
}

// A field input with its own inline error.
function FieldInput({ field, value, error, disabled, onChange }) {
  return (
    <label className={`pt-field${error ? " has-error" : ""}`}>
      <span className="pt-field__label">{field.label}</span>
      <input
        type="text"
        className="pt-input"
        value={value}
        disabled={disabled}
        placeholder={field.placeholder}
        aria-invalid={error ? "true" : "false"}
        onChange={(e) => onChange(field.key, e.target.value)}
      />
      {error && <span className="pt-field__error">{error}</span>}
    </label>
  );
}

export default function PoliciesTable({
  rows, legacyRecs = [], unmatched = [], sessionId, lockText = null, afterForms = false,
  onBeforeChange, onApplied, lineLabel,
}) {
  const hasRows = Array.isArray(rows);
  // A package whose stored assessment predates the editable table (and, once
  // forms exist, is never re-assessed) carries no `policy_lines`: the rows are
  // read from the server instead, so every package gets the editable table.
  const [fetched, setFetched] = useState(null);
  const [fetchedUnmatched, setFetchedUnmatched] = useState([]);
  const editable = hasRows || Array.isArray(fetched);
  const [editingKey, setEditingKey] = useState(null);
  const [draft, setDraft] = useState(EMPTY_DRAFT);
  const [errors, setErrors] = useState({});
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(null);
  const [adding, setAdding] = useState(false);
  const [addDraft, setAddDraft] = useState({ line: "", ...EMPTY_DRAFT });
  const [options, setOptions] = useState([]);
  const [offers, setOffers] = useState([]);
  const [addingForm, setAddingForm] = useState(null);
  // Default order = the server's order; a click sorts asc, then desc, then back.
  const [sort, setSort] = useState({ key: null, dir: "asc" });
  const [grouped, setGrouped] = useState(false);

  const locked = !!lockText;
  const anyBusy = busy !== null || addingForm !== null;

  // The rows when the payload has none, and - after forms - the server's offer
  // of a form a line the producer added needs (never added on its own).
  useEffect(() => {
    if (!sessionId || (hasRows && !afterForms)) { setOffers([]); return undefined; }
    let alive = true;
    fetch(`${API_BASE}/api/policy-lines/${sessionId}`, { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!alive || !d) return;
        if (!hasRows && Array.isArray(d.policy_lines)) {
          setFetched(d.policy_lines);
          setFetchedUnmatched(Array.isArray(d.unmatched_policy_edits) ? d.unmatched_policy_edits : []);
        }
        setOffers(afterForms && Array.isArray(d.add_form_offers) ? d.add_form_offers : []);
      })
      .catch(() => { if (alive) setOffers([]); });
    return () => { alive = false; };
  }, [hasRows, afterForms, sessionId]);

  const shownRows = useMemo(
    () => (hasRows ? rows : (Array.isArray(fetched) ? fetched : (legacyRecs || []))),
    [hasRows, rows, fetched, legacyRecs]);
  const shownUnmatched = hasRows ? (unmatched || []) : fetchedUnmatched;

  const cycleSort = (col) => setSort((s) => {
    if (s.key !== col) return { key: col, dir: "asc" };
    if (s.dir === "asc") return { key: col, dir: "desc" };
    return { key: null, dir: "asc" };
  });

  // The rows in display order: as the server sent them, or sorted (a blank
  // value always last), then - "Group by carrier" - one heading row per
  // company with its policies and the subtotal of the premiums they state.
  const bodyRows = useMemo(() => {
    const list = (shownRows || []).map((r, idx) => ({ r, idx }));
    const labelText = (r) => String(r.line_label || r.line_printed || r.line || "").toLowerCase();
    const sortValue = (r) => (sort.key === "line" ? labelText(r)
      : sort.key === "carrier" ? String(r.carrier_name || "").toLowerCase()
        : premiumAmount(r.premium));
    if (sort.key) {
      list.sort((a, b) => {
        const va = sortValue(a.r);
        const vb = sortValue(b.r);
        const blankA = va === null || va === "";
        const blankB = vb === null || vb === "";
        if (blankA || blankB) return blankA === blankB ? a.idx - b.idx : (blankA ? 1 : -1);
        const c = typeof va === "number" ? va - vb : va.localeCompare(vb);
        return (sort.dir === "asc" ? c : -c) || a.idx - b.idx;
      });
    }
    if (!grouped) return list.map(({ r }) => ({ row: r }));
    const groups = new Map();
    for (const { r } of list) {
      const key = carrierKeyOf(r);
      if (!groups.has(key)) groups.set(key, { key, name: String(r.carrier_name || "").trim(), rows: [] });
      groups.get(key).rows.push(r);
    }
    const ordered = [...groups.values()];
    if (sort.key !== "line" && sort.key !== "premium") {
      ordered.sort((a, b) => {
        if (!a.key || !b.key) return (!a.key) - (!b.key);
        const c = a.name.toLowerCase().localeCompare(b.name.toLowerCase());
        return sort.key === "carrier" && sort.dir === "desc" ? -c : c;
      });
    }
    return ordered.flatMap((g) => {
      const amounts = g.rows.map((r) => premiumAmount(r.premium)).filter((n) => n !== null);
      const group = {
        key: g.key, name: g.name || "No carrier", count: g.rows.length,
        stated: amounts.length, subtotal: amounts.reduce((t, n) => t + n, 0),
      };
      return [{ group }, ...g.rows.map((r) => ({ row: r }))];
    });
  }, [shownRows, sort, grouped]);

  const startEdit = (r) => {
    setAdding(false);
    setEditingKey(r.edit_key);
    setDraft({
      ...EMPTY_DRAFT,
      ...Object.fromEntries([...FIELDS, ...(limitsFor(r) ? LIMIT_FIELDS : [])]
        .map((f) => [f.key, f.key.endsWith("_date") ? normaliseDate(r[f.key]) : (r[f.key] || "")])),
    });
    setErrors({});
    setMessage("");
  };
  const cancelEdit = () => { setEditingKey(null); setErrors({}); setMessage(""); };

  const loadOptions = async () => {
    if (options.length) return;
    try {
      const res = await fetch(`${API_BASE}/api/policy-lines/options`, { credentials: "include" });
      const d = await readJson(res);
      if (Array.isArray(d.lines)) setOptions(d.lines);
    } catch { /* the select stays empty; Save explains */ }
  };

  const startAdd = () => {
    setEditingKey(null);
    setAdding(true);
    setAddDraft({ line: "", ...EMPTY_DRAFT });
    setErrors({});
    setMessage("");
    loadOptions();
  };

  // One request; field errors come back as {errors: {field: message}}.
  const send = async (url, method, body, key) => {
    if (onBeforeChange && !(await onBeforeChange())) return false;
    setBusy(key); setErrors({}); setMessage("");
    try {
      const res = await fetch(url, {
        method, credentials: "include",
        headers: { "Content-Type": "application/json" },
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
      const data = await readJson(res);
      if (!res.ok || data.success === false) {
        if (data.errors && typeof data.errors === "object") setErrors(data.errors);
        setMessage(data.message || data.detail || "That change could not be saved.");
        return false;
      }
      if (Array.isArray(data.add_form_offers)) setOffers(data.add_form_offers);
      onApplied?.(data);
      return true;
    } catch (e) {
      setMessage(`That change could not be saved: ${e?.message || "network error"}`);
      return false;
    } finally {
      setBusy(null);
    }
  };

  const saveEdit = async (r) => {
    const changed = {};
    for (const f of [...FIELDS, ...(limitsFor(r) ? LIMIT_FIELDS : [])]) {
      const before = f.key.endsWith("_date") ? normaliseDate(r[f.key]) : (r[f.key] || "");
      if ((draft[f.key] || "").trim() !== String(before).trim()) changed[f.key] = draft[f.key];
    }
    if (!Object.keys(changed).length) { cancelEdit(); return; }
    const ok = await send(`${API_BASE}/api/policy-lines/${sessionId}/edit`, "POST",
      { edit_key: r.edit_key, fields: changed }, r.edit_key);
    if (ok) cancelEdit();
  };

  const saveAdd = async () => {
    if (!addDraft.line) { setErrors({ line: "Choose a line of business." }); return; }
    const fields = {};
    const keys = [...FIELDS, ...(UMBRELLA_LINE_KEYS.has(addDraft.line) ? LIMIT_FIELDS : [])];
    for (const f of keys) if ((addDraft[f.key] || "").trim()) fields[f.key] = addDraft[f.key];
    const ok = await send(`${API_BASE}/api/policy-lines/${sessionId}/add`, "POST",
      { line: addDraft.line, fields }, "__add__");
    if (ok) { setAdding(false); setAddDraft({ line: "", ...EMPTY_DRAFT }); }
  };

  const remove = async (r) => {
    if (!window.confirm(`Remove the ${r.line_label || "policy"} you added?`)) return;
    const id = String(r.edit_key || "").replace(/^added:/, "");
    await send(`${API_BASE}/api/policy-lines/${sessionId}/added/${encodeURIComponent(id)}`, "DELETE", null, r.edit_key);
  };

  const addForm = async (offer) => {
    if (!offer?.form_id || addingForm) return;
    if (onBeforeChange && !(await onBeforeChange())) return;
    setAddingForm(offer.form_id); setMessage("");
    try {
      const res = await fetch(`${API_BASE}/api/policy-lines/${sessionId}/add-form`, {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ form_id: offer.form_id }),
      });
      const data = await readJson(res);
      if (!res.ok || data.success === false) {
        setMessage(data.message || data.detail || "The form could not be added.");
        if (data.outcome === "already_present" || data.outcome === "not_requested") {
          setOffers((prev) => prev.filter((o) => o.form_id !== offer.form_id));
        }
        return;
      }
      setOffers(Array.isArray(data.add_form_offers) ? data.add_form_offers : []);
      onApplied?.(data);
    } catch (e) {
      setMessage(`The form could not be added: ${e?.message || "network error"}`);
    } finally {
      setAddingForm(null);
    }
  };

  if (!editable && (shownRows || []).length < 2) return null;

  const labelOf = (r) => r.line_label || r.line_printed || (lineLabel ? lineLabel(r.line) : r.line);
  // Line, Carrier, NAIC, Policy number, Term, Source (+ Premium, Limit, actions).
  const colCount = editable ? 9 : 6;
  const canArrange = (shownRows || []).length > 1;

  return (
    <div className="pt">
      {locked && editable && <div className="pt-note pt-note--blue">{lockText}</div>}
      {canArrange && (
        <div className="pt-toolbar">
          <button type="button" className={`pt-toggle${grouped ? " is-on" : ""}`} aria-pressed={grouped}
            onClick={() => setGrouped((g) => !g)}>
            <span className="pt-toggle__box" aria-hidden="true">{grouped ? "\u2713" : ""}</span>Group by carrier
          </button>
          {sort.key && (
            <button type="button" className="pt-link-btn pt-link-btn--plain"
              onClick={() => setSort({ key: null, dir: "asc" })}>Original order</button>
          )}
        </div>
      )}
      <div className="pt-table-wrap">
        <table className="pt-table">
          <thead>
            <tr>
              {canArrange ? <SortHeader col="line" sort={sort} onSort={cycleSort} /> : <th>Line</th>}
              {canArrange ? <SortHeader col="carrier" sort={sort} onSort={cycleSort} /> : <th>Carrier</th>}
              <th>NAIC</th><th>Policy number</th><th>Term</th>
              {editable && (canArrange ? <SortHeader col="premium" sort={sort} onSort={cycleSort} /> : <th>Premium</th>)}
              {editable && <th>Limit</th>}
              <th>Source</th>
              {editable && <th aria-label="Actions" />}
            </tr>
          </thead>
          <tbody>
            {bodyRows.map((item, i) => {
              if (item.group) {
                const g = item.group;
                return (
                  <tr key={`group:${g.key || "none"}`} className="pt-group">
                    <th scope="colgroup" colSpan={colCount}>
                      <span className="pt-group__name">{g.name}</span>
                      <span className="pt-group__meta">
                        {`${g.count} ${g.count === 1 ? "policy" : "policies"}`}
                        {editable && (g.stated > 0
                          ? ` - Premium subtotal ${money(g.subtotal)}${g.stated < g.count ? ` (stated on ${g.stated} of ${g.count})` : ""}`
                          : " - No premium stated")}
                      </span>
                    </th>
                  </tr>
                );
              }
              const r = item.row;
              const key = r.edit_key || r.id || i;
              const isEditing = editable && editingKey === r.edit_key;
              const edited = Array.isArray(r.edited_fields) && r.edited_fields.length > 0;
              if (isEditing) {
                return (
                  <tr key={key} className="pt-row is-editing">
                    <td colSpan={colCount}>
                      <div className="pt-edit">
                        <div className="pt-edit__title">{labelOf(r)}</div>
                        <div className="pt-edit__grid">
                          {[...FIELDS, ...(limitsFor(r) ? LIMIT_FIELDS : [])].map((f) => (
                            <FieldInput key={f.key} field={f} value={draft[f.key]} error={errors[f.key]}
                              disabled={busy !== null || locked}
                              onChange={(k, v) => setDraft((d) => ({ ...d, [k]: v }))} />
                          ))}
                        </div>
                        <div className="pt-edit__hint">Leave a box empty to clear it. The carrier is always required.</div>
                        {message && <div className="pt-error">{message}</div>}
                        <div className="pt-edit__actions">
                          <button type="button" className="pt-btn pt-btn--primary" disabled={busy !== null || locked}
                            onClick={() => saveEdit(r)}>{busy === r.edit_key ? "Saving..." : "Save"}</button>
                          <button type="button" className="pt-btn" disabled={busy !== null} onClick={cancelEdit}>Cancel</button>
                        </div>
                      </div>
                    </td>
                  </tr>
                );
              }
              return (
                <tr key={key} className={`pt-row${r.producer_added ? " is-added" : ""}`}>
                  <td className="pt-wrap">
                    {labelOf(r)}
                    {r.producer_added && <span className="pt-tag">Added by you</span>}
                    {!r.producer_added && edited && <span className="pt-tag pt-tag--edited">Corrected by you</span>}
                  </td>
                  <td className="pt-wrap">{r.carrier_name || "-"}</td>
                  <td>{r.carrier_naic || "-"}</td>
                  <td className="pt-wrap">{r.policy_number || "-"}</td>
                  <td>{term(r)}</td>
                  {editable && <td>{r.premium || "-"}</td>}
                  {editable && <td className="pt-wrap pt-limit-cell"><LimitCell r={r} /></td>}
                  <td className="pt-wrap pt-muted">
                    {r.producer_added ? "You" : ([...new Set(r.sources || [])].join(", ") || "-")}
                  </td>
                  {editable && (
                    <td className="pt-actions">
                      <button type="button" className="pt-icon-btn" title={locked ? lockText : "Edit this policy"}
                        aria-label={`Edit ${labelOf(r)}`} disabled={locked || anyBusy || adding}
                        onClick={() => startEdit(r)}><PencilIcon /></button>
                      {r.producer_added && (
                        <button type="button" className="pt-link-btn" disabled={locked || anyBusy}
                          onClick={() => remove(r)}>{busy === r.edit_key ? "Removing..." : "Remove"}</button>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
            {editable && adding && (
              <tr className="pt-row is-editing">
                <td colSpan={colCount}>
                  <div className="pt-edit">
                    <div className="pt-edit__title">Add a policy</div>
                    <div className="pt-edit__grid">
                      <label className={`pt-field${errors.line ? " has-error" : ""}`}>
                        <span className="pt-field__label">Line of business</span>
                        <select className="pt-input" value={addDraft.line} disabled={busy !== null || locked}
                          onChange={(e) => setAddDraft((d) => ({ ...d, line: e.target.value }))}>
                          <option value="">Choose a line</option>
                          {options.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
                        </select>
                        {errors.line && <span className="pt-field__error">{errors.line}</span>}
                      </label>
                      {[...FIELDS, ...(UMBRELLA_LINE_KEYS.has(addDraft.line) ? LIMIT_FIELDS : [])].map((f) => (
                        <FieldInput key={f.key} field={f} value={addDraft[f.key]} error={errors[f.key]}
                          disabled={busy !== null || locked}
                          onChange={(k, v) => setAddDraft((d) => ({ ...d, [k]: v }))} />
                      ))}
                    </div>
                    <div className="pt-edit__hint">
                      {UMBRELLA_LINE_KEYS.has(addDraft.line)
                        ? "The carrier is required. Add the policy number, term, premium, limits and SIR if you have them."
                        : "The carrier is required. Add the policy number, term and premium if you have them."}
                    </div>
                    {message && <div className="pt-error">{message}</div>}
                    <div className="pt-edit__actions">
                      <button type="button" className="pt-btn pt-btn--primary" disabled={busy !== null || locked}
                        onClick={saveAdd}>{busy === "__add__" ? "Saving..." : "Save"}</button>
                      <button type="button" className="pt-btn" disabled={busy !== null}
                        onClick={() => { setAdding(false); setErrors({}); setMessage(""); }}>Cancel</button>
                    </div>
                  </div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {editable && (
        <div className="pt-foot">
          {!adding && (
            <button type="button" className="pt-add-btn" disabled={locked || anyBusy || editingKey !== null}
              title={locked ? lockText : undefined} onClick={startAdd}>+ Add a policy</button>
          )}
          {!adding && editingKey === null && message && <div className="pt-error">{message}</div>}
          {shownUnmatched.length > 0 && (
            <div className="pt-note">
              {shownUnmatched.map((u) => (
                <div key={u.edit_key}>A correction you made to {u.line_label || "a policy"} is not applied - that policy is no longer in the documents.</div>
              ))}
            </div>
          )}
          {afterForms && offers.length > 0 && (
            <div className="pt-offers">
              {offers.map((o) => (
                <div key={o.form_id} className="pt-offer">
                  <span>A policy you added needs {o.label || o.form_id}, which is not in this package.</span>
                  <button type="button" className="pt-btn pt-btn--primary" disabled={locked || anyBusy}
                    onClick={() => addForm(o)}>
                    {addingForm === o.form_id ? `Adding ${o.label || o.form_id}... this can take a few minutes` : `Add ${o.label || o.form_id}`}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
