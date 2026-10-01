// Orbin 22 Sep, item 3 (1 Oct 2026): "Contact information" was printed twice on
// the pre-form Review screen - under "Key details missing" AND as the warning
// card "ACORD 125 minimum field missing: Contact information", the card that
// also holds the score at 85.
//
// A missing key detail that has its own card on the screen is now shown ONCE,
// on the card: the card names the cap, carries the same fix ("Open to fix") and
// is what every issue count is summed from. The key-details line then says only
// how many more are under Warnings / Hard Stops, never their names again.
//
// "Has its own card" is read off what the screen RENDERS - the grouped view's
// hard-stop clusters and its three warning tiers, the same lists both layouts
// draw - never off the raw stop arrays. So a detail can never be hidden from
// both places, and an old payload with no grouped view lists it as before.
// Two signals, either one enough, both derived from server declarations:
//   1. the card's rule code is the one the issue registry mints from this very
//      label (`tier1_missing_<label>`, from check_tier1's own labels);
//   2. the card's fix types exactly this detail's facts, nothing more and
//      nothing less (field mode, same fact set) - the same fix offered twice.
//
// Pure functions, no React and no DOM, so a node test runs them.

export const KEY_DETAIL_CODE_PREFIX = "tier1_missing_";

// The warning tiers both pre-form layouts render, in their order.
export const RENDERED_WARNING_TIERS = ["required", "recommended", "binder_followup"];

// Where a card lives on the Review screen (the rail's section ids).
export const CARD_SECTIONS = ["hardstops", "warnings"];

const factSet = (facts) => new Set(
  (Array.isArray(facts) ? facts : []).map((f) => String(f || "").trim()).filter(Boolean),
);

const sameSet = (a, b) => a.size > 0 && a.size === b.size && [...a].every((x) => b.has(x));

// Every rule row the screen draws as a card, with the section it is drawn in.
export function renderedCardRows(groupedIssues) {
  const rows = [];
  const take = (clusters, section) => {
    for (const c of (Array.isArray(clusters) ? clusters : [])) {
      if (!c || typeof c !== "object") continue;
      const items = Array.isArray(c.items) && c.items.length
        ? c.items
        : [{ code: c.code, resolution: c.resolution }];
      for (const it of items) {
        if (it && typeof it === "object") rows.push({ section, code: it.code, resolution: it.resolution });
      }
    }
  };
  take(groupedIssues?.hard_stops, "hardstops");
  for (const tier of RENDERED_WARNING_TIERS) take(groupedIssues?.warnings?.[tier], "warnings");
  return rows;
}

// The section whose card already asks for this key detail, or null.
// `detail` is a `missing_items` entry ({ label, facts }) or a bare label.
export function cardSectionFor(detail, rows) {
  const label = typeof detail === "string" ? detail : String(detail?.label || "");
  if (!label) return null;
  const facts = factSet(typeof detail === "string" ? [] : detail?.facts);
  const list = Array.isArray(rows) ? rows : [];
  // A blocker outranks a warning: when both name the detail, point at the red one.
  for (const section of CARD_SECTIONS) {
    const hit = list.some((r) => r && r.section === section && (
      r.code === `${KEY_DETAIL_CODE_PREFIX}${label}`
      || (r.resolution && r.resolution.mode === "field" && sameSet(facts, factSet(r.resolution.facts)))
    ));
    if (hit) return section;
  }
  return null;
}

// `keyDetails` as the server sent it, plus `on_cards`: { label: section } for
// each missing detail a rendered card already shows. Never mutates its input;
// `satisfied` / `missing` / `missing_items` are passed through untouched, so
// "N of M key details in place" keeps counting every detail.
export function withKeyDetailCards(keyDetails, groupedIssues) {
  if (!keyDetails || typeof keyDetails !== "object") return keyDetails;
  const rows = renderedCardRows(groupedIssues);
  const onCards = {};
  if (rows.length) {
    const items = Array.isArray(keyDetails.missing_items) ? keyDetails.missing_items : [];
    const byLabel = new Map(items.filter((it) => it && it.label).map((it) => [String(it.label), it]));
    for (const label of (Array.isArray(keyDetails.missing) ? keyDetails.missing : [])) {
      const section = cardSectionFor(byLabel.get(String(label)) || String(label), rows);
      if (section) onCards[label] = section;
    }
  }
  return { ...keyDetails, on_cards: onCards };
}

// The key-details line's split: what it still lists, and how many more each
// section shows instead.
export function splitMissingDetails(keyDetails) {
  const labels = Array.isArray(keyDetails?.missing) ? keyDetails.missing : [];
  const onCards = (keyDetails && keyDetails.on_cards) || {};
  const listed = labels.filter((l) => !onCards[l]);
  const elsewhere = CARD_SECTIONS
    .map((section) => ({ section, count: labels.filter((l) => onCards[l] === section).length }))
    .filter((x) => x.count > 0);
  const items = Array.isArray(keyDetails?.missing_items)
    ? keyDetails.missing_items.filter((it) => it && !onCards[it.label])
    : null;
  return { labels, listed, items, elsewhere };
}
