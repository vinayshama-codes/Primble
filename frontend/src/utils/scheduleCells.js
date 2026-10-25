// What a schedule table's cells need beyond a plain box (21 Oct 2026, Brent's
// 17 Oct item 6 - the General Liability Classification & Exposure Details
// window). Every rule is read off the column spec the server sends
// (services/schedule_capture.py), so a table that declares none of it renders
// exactly as before.
//
//   * options    - choices offered in a searchable list; free text stays
//                  allowed (the "Other" a person types). The GL window's
//                  locations and operations are the package's own
//                  (`schedule_capture.columns_for`).
//   * units_by   - the unit an amount is in, read off another cell of the same
//                  row (an exposure is dollars on a payroll basis, square feet
//                  on an area basis). Shown beside the cell only.
//   * follow_up  - a table-level declaration: each row can be marked "Unknown -
//                  follow up" (`schedule_capture.FOLLOW_UP_KEY`). The row is
//                  saved; what it does not state stays open.
//
// Pure functions, no React and no DOM, so a node test runs them.

export const FOLLOW_UP_KEY = "follow_up";
export const FOLLOW_UP_LABEL = "Unknown - follow up";
export const FOLLOW_UP_HINT =
  "Tick when a value on this row is not known yet - leave that cell blank. The row is saved and stays open for follow-up.";

const clean = (v) => String(v ?? "").trim();

// The choices a column offers, de-duplicated, in the server's order.
export function cellOptions(col) {
  const list = Array.isArray(col?.options) ? col.options : [];
  const seen = new Set();
  const out = [];
  for (const o of list) {
    const text = clean(o);
    if (!text || seen.has(text.toLowerCase())) continue;
    seen.add(text.toLowerCase());
    out.push(text);
  }
  return out;
}

// The unit `row`'s value in `col` is counted in ("$", "sq ft", "units"...),
// or "" when the column declares none or the row's basis names no unit yet.
export function unitFor(col, row) {
  const spec = col && typeof col.units_by === "object" ? col.units_by : null;
  if (!spec || !spec.column) return "";
  const basis = clean(row?.[spec.column]).toLowerCase().replace(/[^a-z ]/g, " ").replace(/\s+/g, " ").trim();
  if (!basis) return "";
  const units = spec.units && typeof spec.units === "object" ? spec.units : {};
  return clean(units[basis]);
}

// Is the row marked "Unknown - follow up"?
export function isFollowUp(row) {
  const v = row?.[FOLLOW_UP_KEY];
  if (typeof v === "boolean") return v;
  return ["true", "yes", "y", "1", "on"].includes(clean(v).toLowerCase());
}

// The row with its follow-up mark set or cleared (a new object).
export function withFollowUp(row, on) {
  const next = { ...(row || {}) };
  if (on) next[FOLLOW_UP_KEY] = true;
  else delete next[FOLLOW_UP_KEY];
  return next;
}
