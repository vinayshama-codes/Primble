// A conflict-family issue (documents disagree on a value) is reconciled in the
// Data Consistency picker, keyed by its canonical fact. Its issue `code` encodes
// that fact; derive it so a banner issue can be matched to its Data Consistency
// row. Purely a display-routing hint - returns null when the code isn't a
// conflict-family code, so non-conflict issues fall through untouched. Kept in
// sync with the code prefixes emitted in extraction_pipeline.py (and with
// issue_registry._DOC_CONFLICT_CODE_TO_FACT on the server).
export const DOC_CONFLICT_CODE_TO_FACT = {
  name_conflict:       "applicant_name",
  fein_conflict:       "fein",
  date_conflict:       "effective_date",
  expiration_conflict: "expiration_date",
  // dba_name / lines_of_business / revenue arrive as `field=<fact>`, already the
  // fact key, so they need no remap.
};

export function issueFactKey(it) {
  const code = (it && it.code) || "";
  let m;
  if ((m = code.match(/^underwriting_reconciliation_(.+)$/))) return m[1];
  if ((m = code.match(/^source_conflict_(?:carrier_)?(.+)$/)))  return m[1];
  if ((m = code.match(/^doc_conflict_(?:hard|warn)_(.+)$/))) {
    const c = m[1];
    return DOC_CONFLICT_CODE_TO_FACT[c] || c;
  }
  return null;
}

// The facts the Data Consistency panel lists as open conflicts ("Values to
// confirm") - the rows a "Fix in Data Consistency" button leads to.
export function openConflictFacts(underwriting) {
  return new Set(((underwriting && underwriting.fields) || [])
    .filter((f) => f && f.status === "conflict" && f.fact_key)
    .map((f) => String(f.fact_key)));
}
