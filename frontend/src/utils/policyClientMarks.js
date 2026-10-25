// The policies table's "Client" mark (Z37 lane C, 24 Oct 2026).
//
// A client's questionnaire answer about ONE policy (policy number, insurer,
// NAIC - `policy_lines.apply_policy_answers`) is written into that policy's
// record and listed by the server in the row's `client_fields`. The cell
// shows the value with a small "Client" mark. A held answer that disagrees
// with the documents is never written, so it is never in `client_fields` and
// the cell keeps the documents' value.

// Table column -> the record fields it shows.
const COLUMN_FIELDS = {
  carrier: ["carrier_name"],
  naic: ["carrier_naic"],
  policy: ["policy_number"],
  term: ["effective_date", "expiration_date"],
  premium: ["premium"],
};

/** True when the client supplied this column's value on this row and the
 *  cell has a value to mark. */
export function clientMarked(row, column) {
  if (!row || row.producer_added) return false;
  const fields = COLUMN_FIELDS[column];
  const theirs = Array.isArray(row.client_fields) ? row.client_fields : [];
  if (!fields || !theirs.length) return false;
  const supplied = fields.some((f) => theirs.includes(f));
  const shown = fields.some((f) => String(row[f] ?? "").trim() !== "");
  return supplied && shown;
}

export const CLIENT_MARK_TEXT = "Client";
export const CLIENT_MARK_TITLE = "Answered by your client in the questionnaire";
