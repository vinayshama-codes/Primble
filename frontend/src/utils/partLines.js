// "Which line is this coverage part?" (owner, 14 Oct 2026). Pure: no React.
//
// The server lists the parts and the lines to pick from - the card's
// `resolution.controls[fact]` with `control: "part_lines"`, built by
// `issue_registry.unmapped_line_issue` - and decides what an answer means
// (`lob_canon.parse_part_lines`). The window only turns the picks into the one
// stored text, "<part key>=<line>; ...", sorted so one set of picks has one
// text. Answers for parts the card no longer lists (`keep`) ride along, so a
// save never drops an earlier answer.

const clean = (v) => String(v ?? "").trim();

// { partKey: line } read from a stored / composed text.
export function parsePartLines(text) {
  const out = {};
  for (const chunk of clean(text).split(";")) {
    const at = chunk.indexOf("=");
    if (at <= 0) continue;
    const key = clean(chunk.slice(0, at)).toLowerCase();
    const line = clean(chunk.slice(at + 1)).toLowerCase();
    if (key && line) out[key] = line;
  }
  return out;
}

// The current pick for each listed part: the window's text once it has one
// (`composed` is a string), otherwise what the server says is saved.
export function partPicks(ctl, composed) {
  const parts = Array.isArray(ctl?.parts) ? ctl.parts : [];
  const typed = typeof composed === "string" ? parsePartLines(composed) : null;
  const out = {};
  for (const p of parts) {
    if (!p || !p.key) continue;
    out[p.key] = typed ? (typed[p.key] || "") : clean(p.value);
  }
  return out;
}

// The text to save: every listed part's pick plus the kept answers.
export function composePartLines(ctl, picks) {
  const map = {};
  const keep = ctl && typeof ctl.keep === "object" && ctl.keep ? ctl.keep : {};
  for (const [k, v] of Object.entries(keep)) {
    if (clean(k) && clean(v)) map[clean(k)] = clean(v);
  }
  const parts = Array.isArray(ctl?.parts) ? ctl.parts : [];
  for (const p of parts) {
    if (!p || !p.key) continue;
    const v = clean((picks || {})[p.key]);
    if (v) map[p.key] = v;
    else delete map[p.key];
  }
  return Object.keys(map).sort().map((k) => `${k}=${map[k]}`).join("; ");
}

// How many listed parts still have no line picked.
export function partsLeft(ctl, picks) {
  const parts = Array.isArray(ctl?.parts) ? ctl.parts : [];
  return parts.filter((p) => p && p.key && !clean((picks || {})[p.key])).length;
}
