// "Save progress" (owner, 13 Oct 2026). A fix window that holds more than one
// value - several boxes, a table, a table plus boxes above it - can be saved
// before every value is in. That save is PROGRESS, not a fix: the item stays
// in its list with "Open to fix", no "Resolved" tag, never counted as handled,
// never in the Resolved section. "Open to fix" shows what was saved.
//
// Whether a save fixed the item is read off the issue lists the server sends
// back after it - never assumed from the click. The owner's run 18f6914f: the
// location table was filled, occupancy type was not, and the COPE hard stop was
// marked Resolved ("All 1 handled") while it still fired.
// Pure functions, no React: the backend suite runs them under node.

const TEXT = (v) => String(v ?? "").trim();

// The items a cluster stands for - its own list, or the one issue a
// single-item cluster carries on itself.
function clusterItems(c) {
  if (!c || typeof c !== "object") return [];
  if (Array.isArray(c.items) && c.items.length) {
    return c.items.map((it) => (it && !it.cluster && c.cluster ? { ...it, cluster: c.cluster } : it));
  }
  return [{ issue_id: c.issue_id, message: c.primary_message, forms: c.forms, code: c.code, cluster: c.cluster }];
}

// Every issue a response - or the screen before it - lists: the review's
// grouped hard stops and warnings, the cross-form issues, and stops that came
// as bare sentences when no grouped view travelled with them.
export function listedIssues({ grouped, cross, hardStops, softStops } = {}) {
  const out = [];
  const g = grouped && typeof grouped === "object" ? grouped : {};
  for (const c of (Array.isArray(g.hard_stops) ? g.hard_stops : [])) out.push(...clusterItems(c));
  const w = g.warnings && typeof g.warnings === "object" ? g.warnings : {};
  for (const list of Object.values(w)) {
    for (const c of (Array.isArray(list) ? list : [])) out.push(...clusterItems(c));
  }
  for (const i of (Array.isArray(cross) ? cross : [])) if (i && typeof i === "object") out.push(i);
  if (!Array.isArray(g.hard_stops)) {
    for (const m of (Array.isArray(hardStops) ? hardStops : [])) if (typeof m === "string") out.push({ message: m, forms: [] });
  }
  if (!g.warnings) {
    for (const m of (Array.isArray(softStops) ? softStops : [])) if (typeof m === "string") out.push({ message: m, forms: [] });
  }
  return out;
}

const messageOf = (i) => TEXT(i && (i.message ?? i.primary_message));

// Did the save leave this item firing? True when the same item is still listed
// (by id or by its words), or when its rule now fires under NEW words - a partly
// fixed card renames what is still missing ("missing: occupancy type,
// construction type" becomes "missing: occupancy type"), a new id for the same
// unfinished item. A listing of the same rule that was already there before the
// save is a different item (a second location), not this one. Errs toward
// "still open": an item wrongly left open is still on screen to fix; one wrongly
// marked Resolved hides a stop that still holds the score.
export function fixLeftOpen(issue, before, after, idOf) {
  const afterList = Array.isArray(after) ? after : [];
  const beforeList = Array.isArray(before) ? before : [];
  const iid = typeof idOf === "function" ? idOf(issue) : null;
  const msg = messageOf(issue);
  const same = (i) => (iid && typeof idOf === "function" && idOf(i) === iid) || (msg && messageOf(i) === msg);
  if (afterList.some(same)) return true;
  const beforeMessages = new Set(beforeList.map(messageOf));
  const fresh = afterList.filter((i) => i && !beforeMessages.has(messageOf(i)));
  const code = issue && issue.code;
  if (code && fresh.some((i) => i.code === code)) return true;
  // Its TWIN took over (review, 13 Oct 2026): a COPE card's legacy sibling is
  // hidden while the coded card fires and appears - under another code, in the
  // SAME cluster - once it stops ("Missing: roof year" still capping the score
  // at 85). A new item in the card's own cluster is the same unfinished item.
  const own = beforeList.find(same);
  const cluster = (issue && issue.cluster) || (own && own.cluster);
  return !!cluster && fresh.some((i) => i.cluster === cluster);
}

// Each building row's missing COPE column groups (13 Oct 2026): `rowNeeds` is
// the server's declaration for the location table (premises_cope `row_needs`)
// - every non-blank row needs ONE value per group ("Building value or BPP
// value on rows 1 and 2"). Blank rows are not buildings.
// `buildingColumns` (21 Oct 2026, review M1): the server's own "is this row a
// building?" (premises_cope `building_columns` - a value in one of the table's
// columns, never a bare id or LOC #), so Save progress counts exactly the rows
// the submission's value is derived from. Without it, any stated cell counts.
export function rowNeedsSummary(rows, rowNeeds, columns, buildingColumns) {
  const list = Array.isArray(rows) ? rows : [];
  const cols = Array.isArray(columns) ? columns : [];
  const labelOf = (k) => ((cols.find((c) => c && c.key === k) || {}).label) || k;
  const building = Array.isArray(buildingColumns) && buildingColumns.length ? buildingColumns : null;
  const parts = [];
  for (const group of (Array.isArray(rowNeeds) ? rowNeeds : [])) {
    const keys = (Array.isArray(group) ? group : [group]).filter(Boolean);
    if (!keys.length) continue;
    const missing = [];
    list.forEach((row, idx) => {
      const filled = building
        ? building.some((k) => TEXT((row || {})[k]))
        : Object.entries(row || {}).some(([k, v]) => !k.startsWith("_") && TEXT(v));
      if (filled && !keys.some((k) => TEXT(row[k]))) missing.push(idx + 1);
    });
    if (!missing.length) continue;
    const where = missing.length === 1
      ? `row ${missing[0]}`
      : `rows ${missing.slice(0, -1).join(", ")} and ${missing[missing.length - 1]}`;
    parts.push(`${keys.map(labelOf).join(" or ")} on ${where}`);
  }
  return parts.join("; ");
}

// The box groups a field window's rule still needs (13 Oct 2026). `needs` is
// the server's declaration (issue_registry._r_field): every group needs ONE
// value - [["a"], ["b", "c"]] is "a and (b or c)". A group with no value is
// named ("B or C" for an either-or group). Only a card that declares `needs`
// can be partial: without it the boxes are "whichever applies".
export function unmetNeeds(needs, values, labelOf = (f) => f) {
  if (!Array.isArray(needs)) return "";
  const vals = values || {};
  const out = [];
  for (const group of needs) {
    const facts = (Array.isArray(group) ? group : [group]).filter(Boolean);
    if (!facts.length || facts.some((f) => TEXT(vals[f]))) continue;
    out.push(facts.map((f) => labelOf(f)).join(" or "));
  }
  return out.join("; ");
}

// What a multi-value fix window still lacks, in the window's own words - ""
// when nothing it can see is missing. A window with ONE box and no table has no
// partial state (it either applies or it does not), so it is never "progress".
//   boxes    - [[label, value], ...] the inputs (field mode, or the
//              whole-submission inputs above a table)
//   hasTable - the window shows a table
//   table    - the table's own "still missing" sentence (required cells), or ""
// A blank box counts even where the rule would accept either of two values:
// the label then says "Save progress", and the server's answer still marks the
// item Resolved if that one value cleared it.
export function stillMissing({ boxes = [], hasTable = false, table = "" } = {}) {
  const list = Array.isArray(boxes) ? boxes : [];
  if (!hasTable && list.length < 2) return "";
  const blank = list.filter(([, v]) => !TEXT(v)).map(([label]) => TEXT(label)).filter(Boolean);
  const tableGap = hasTable ? TEXT(table) : "";
  return [...blank, ...(tableGap ? [tableGap] : [])].join("; ");
}

// Ticked starters left unfinished (13 Oct 2026): a line that is only the starter,
// or the starter plus a placeholder ("TBD"), says nothing - the window asks for
// the sentence to be finished or the option unticked. The server strips them too
// (services/narrative_reader.strip_unfinished_starters).
const PLACEHOLDER_RE = /^(tbd|tba|tbc|n\/?a|none|unknown|later|pending|x+|\?+|-+|\.+)$/i;
const lineIsUnfinishedStarter = (line, starter) => {
  if (!line.toLowerCase().startsWith(starter.toLowerCase())) return false;
  const rest = line.slice(starter.length).replace(/^[\s:.,;-]+|[\s:.,;-]+$/g, "");
  return !rest || PLACEHOLDER_RE.test(rest);
};

export function unfinishedStarters(text, gaps) {
  const lines = String(text || "").split("\n").map((l) => l.trim());
  const out = [];
  for (const g of Array.isArray(gaps) ? gaps : []) {
    const st = String((g && g.starter) || "").trim();
    if (!st) continue;
    if (lines.some((line) => lineIsUnfinishedStarter(line, st))) out.push(g);
  }
  return out;
}

// What the typed text already covers, read the way the score reads it (owner,
// 13 Oct 2026: a pasted paragraph that covered every item ticked only the one
// option whose starter it repeated word for word). Each option carries the
// phrases its own check looks for (`phrases`, sqs_service.narrative_gap_options);
// one of them anywhere in the text covers it - the score's single-mention rule
// for the remarks. Unfinished starter lines are left out first: a ticked starter
// nobody finished says nothing, and the server strips it before scoring.
export function textForCoverage(text, gaps) {
  const starters = (Array.isArray(gaps) ? gaps : [])
    .map((g) => String((g && g.starter) || "").trim()).filter(Boolean);
  return String(text || "").split("\n")
    .filter((line) => !starters.some((st) => lineIsUnfinishedStarter(line.trim(), st)))
    .join("\n").toLowerCase();
}

export function gapCovered(coverageText, gap) {
  const t = String(coverageText || "").toLowerCase();
  const phrases = Array.isArray(gap?.phrases) ? gap.phrases : [];
  return phrases.some((p) => {
    const s = String(p || "").trim().toLowerCase();
    return !!s && t.includes(s);
  });
}
