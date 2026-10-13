// Round 5 #15 (7 Oct 2026). Brent #18: "There were no Hard Stops in the
// initial SQS prior to form selection, but there's Hard Stops now. Why? This
// should all be addressable prior to forms."
//
// Before forms, a cross-form hard stop is shown as a warning (C75 - a form we
// merely suggested may not block; Brent's call, unchanged) and generation makes
// it a hard stop again. The server now tags each such warning row
// (`becomes_hard_tag`, e.g. "Becomes a hard stop when ACORD 140 is generated")
// and counts the rows it tagged (`grouped_issues.becomes_hard`). These helpers
// word that count for the Review screens - both layouts read them.
//
// Pure functions, no React: the backend suite runs them under node
// (tests/test_round5_stops_7oct.py). UI copy: no em-dashes.

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

const count = (x) => {
  const n = Number(x);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0;
};

// How many warnings on screen generation will make hard stops (0 when none,
// after forms, or on a payload that predates the count).
export const becomesHardCount = (groupedIssues) => count(groupedIssues && groupedIssues.becomes_hard);

// "1 hard stop now, 1 more when forms are generated" / "No hard stops now,
// 2 when forms are generated". Null when nothing becomes a hard stop.
export function hardStopsNowAndLaterText(nowCount, laterCount) {
  const later = count(laterCount);
  if (!later) return null;
  const now = count(nowCount);
  return now
    ? `${plural(now, "hard stop")} now, ${later} more when forms are generated`
    : `No hard stops now, ${later} when forms are generated`;
}

// The Hard Stops section's line: "1 warning becomes a hard stop when forms are
// generated." Null when none.
export function laterHardStopsNote(laterCount) {
  const later = count(laterCount);
  if (!later) return null;
  return later === 1
    ? "1 warning becomes a hard stop when forms are generated."
    : `${later} warnings become hard stops when forms are generated.`;
}
