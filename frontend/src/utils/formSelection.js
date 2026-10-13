// Form selection defaults (Brent's Choice Electric #17; owner, 9 Oct 2026:
// "Tick the ACORD 125 by itself and do not change the order - order should be
// based on matching percentage"). ACORD 125, the master application, starts
// ticked when the producer reaches form selection; the list keeps the
// recommender's order. Pure: no React.

export const ANCHOR_FORM_ID = "ACORD_125";

// The ticks once the producer is on form selection: the anchor form added when
// the recommender offers it and the producer has not unticked it. Not when the
// producer uploaded their own filled ACORD 125: the recommender then says to
// "generate a clean copy only if needed" (`is_source_document`). The SAME Set
// comes back when nothing changes, so React does not re-render for it.
export function withAnchorForm(ticks, recommendations, declined) {
  const set = ticks instanceof Set ? ticks : new Set(ticks || []);
  if (declined || set.has(ANCHOR_FORM_ID)) return set;
  const rec = (recommendations || []).find((r) => r && r.form_id === ANCHOR_FORM_ID);
  if (!rec || rec.is_source_document) return set;
  return new Set(set).add(ANCHOR_FORM_ID);
}

// The forms the review page's "Before you generate" checks run on: the
// producer's ticks once they have changed one; until then none, which means
// "the recommended forms" - so the anchor tick alone never narrows the checks
// to ACORD 125.
export function checkedFormsForReview(ticks, touched) {
  return touched ? [...(ticks || [])] : [];
}
