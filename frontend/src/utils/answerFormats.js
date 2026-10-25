// Answer formats the client questionnaire normalizes on blur and checks on
// submit. Each mirrors its SERVER twin one-for-one, so what the client sees is
// exactly what gets stored - a backend test runs both over the same values:
//
//   percentStatement          -> services/normalization.stated_percentage
//   mentionsPercentage        -> services/normalization.mentions_a_percentage
//   normalizeCurrency         -> services/arq_service._normalize_currency
//   normalizeAmountOrPercent  -> services/arq_service._normalize_amount_or_percent
//   isAmountBoxConvention     -> services/answer_semantics.is_amount_box_convention
//
// Every one is forgiving: an unreadable value returns null and the caller keeps
// what was typed (the page shows the error, nothing is cleared).

// A percent unit right after a figure: "%", "percent", "per cent", "pct".
const PERCENT_UNIT = '\\s*(?:%|percent(?![A-Za-z0-9_])|per\\s*cent(?![A-Za-z0-9_])|pct(?![A-Za-z0-9_])\\.?)';
const PERCENT_UNIT_RE = new RegExp(`^${PERCENT_UNIT}`, 'i');
// A fraction is one figure: a whole number with a proper fraction ("1-1/2",
// "1 1/2"), a fraction glyph ("1½", "½") or a plain fraction ("1/2"), read
// only when its decimal is exact in six places (see `figureValue`).
const FRACTION_GLYPHS = {
  '½': [1, 2], '¼': [1, 4], '¾': [3, 4], '⅕': [1, 5], '⅖': [2, 5], '⅗': [3, 5],
  '⅘': [4, 5], '⅛': [1, 8], '⅜': [3, 8], '⅝': [5, 8], '⅞': [7, 8], '⅒': [1, 10],
};
// A figure's last character, then a percent unit, anywhere in the value.
const MENTIONS_PERCENT_RE = new RegExp(`[0-9${Object.keys(FRACTION_GLYPHS).join('')}]${PERCENT_UNIT}`, 'i');
// A figure: a fraction (above), thousands groups of three, a plain run, or a
// leading decimal - the server's alternatives in the server's order.
const FIGURE_RE = new RegExp(
  '\\d+(?:-| +)\\d+\\/\\d+'
  + `|(?:\\d+ ?)?[${Object.keys(FRACTION_GLYPHS).join('')}]`
  + '|\\d+\\/\\d+'
  + '|\\d{1,3}(?:,\\d{3})+(?:\\.\\d+)?|\\d+(?:\\.\\d+)?|\\.\\d+', 'g');
// A character that glues a figure to the token before it ("A2%", "1.2", "1,2").
const GLUE_RE = /[A-Za-z0-9_.,]/;
const SIGNS = '-−–';

function figureText(n) {
  return Number.isInteger(n) ? String(n) : n.toFixed(6).replace(/0+$/, '').replace(/\.$/, '');
}

// The number one figure states, or null for a fraction that is not proper with
// an exact six-place decimal (a date's "12/31", "80/90", "1/3").
function figureValue(num) {
  const glyph = FRACTION_GLYPHS[num.slice(-1)];
  let wholeText = '';
  let n;
  let d;
  if (glyph) {
    wholeText = num.slice(0, -1).trim();
    [n, d] = glyph;
  } else if (num.includes('/')) {
    const cut = num.lastIndexOf('/');
    const parts = num.slice(0, cut).split(/[- ]+/);
    if (parts.length === 2) [wholeText] = parts;
    n = parseInt(parts[parts.length - 1], 10);
    d = parseInt(num.slice(cut + 1), 10);
  } else {
    const v = parseFloat(num.replace(/,/g, ''));
    return Number.isFinite(v) ? v : null;
  }
  if (!(n > 0 && n < d) || 1000000 % d !== 0) return null;
  return parseFloat(((wholeText ? parseInt(wholeText, 10) : 0) + n / d).toFixed(6));
}

// Every figure not glued to the token before it, left to right, as the server's
// regex search finds them: { start (its sign, if any), end, sign, num }.
// Written without regex lookbehind (older Safari cannot parse one): a glued
// figure is looked for again one character on, which is what a lookbehind does.
function scanFigures(s) {
  const out = [];
  FIGURE_RE.lastIndex = 0;
  let m;
  while ((m = FIGURE_RE.exec(s)) !== null) {
    let start = m.index;
    let sign = false;
    if (start > 0 && SIGNS.includes(s[start - 1])) {
      if (start > 1 && GLUE_RE.test(s[start - 2])) {
        // "a-2%": the sign is glued to a word, so it is not a sign; the
        // figure itself is preceded by "-", which does not glue it.
      } else {
        sign = true;
        start -= 1;
      }
    } else if (start > 0 && GLUE_RE.test(s[start - 1])) {
      FIGURE_RE.lastIndex = m.index + 1;          // glued to the token before it
      continue;
    }
    out.push({ start, end: m.index + m[0].length, sign, num: m[0] });
  }
  return out;
}

// The value's FIRST figure, when it is printed as a percentage:
// { number, figure, text, plain, before, after }, else null. `text` writes that
// figure "<n>%" and keeps everything around it; a minus sign counts only when it
// touches the figure; a "$" straight before it is dropped ("$2 %" is 2%).
export function percentStatement(raw) {
  const s = String(raw ?? '').trim();
  const first = scanFigures(s)[0];
  if (!first) return null;
  const unit = PERCENT_UNIT_RE.exec(s.slice(first.end));
  if (!unit) return null;                         // the first figure decides
  let number = figureValue(first.num);
  if (number === null) return null;
  if (first.sign) number = -number;
  const figure = figureText(number);
  // A minus sign or currency letters straight before the "$" ("-$2%",
  // "US$2%"): refused, never reshaped into "-2%" / "US2%" (the server's rule).
  if (/(?:[-−–]|[A-Za-z])\$\s*$/.test(s.slice(0, first.start))) return null;
  const before = s.slice(0, first.start).replace(/\$\s*$/, '');
  const after = s.slice(first.end + unit[0].length);
  const text = `${before}${figure}%${after}`.replace(/\s+/g, ' ').trim();
  return { number, figure, text, plain: !before.trim() && !after.trim(), before, after };
}

// True when any figure is followed by a percent unit, read as a percentage or
// not: "$25,000 or 2%" (whose FIRST figure is a dollar amount), "2,5 percent".
export function mentionsPercentage(raw) {
  return MENTIONS_PERCENT_RE.test(String(raw ?? ''));
}

// "$1,234,567", keeping a trailing qualifier ("$20,000 per month"); null for a
// compound answer ("$1,000,000 / $2,000,000") and for a percentage - "2%" is
// never "$2 %".
export function normalizeCurrency(raw) {
  const s = (raw || '').trim();
  if (!s) return null;
  if (percentStatement(s)) return null;
  const m = s.match(/^\$?\s*([\d,]*\.?\d+)\s*([kKmM])?\b(.*)$/);
  if (!m) return null;
  let amount = parseFloat(m[1].replace(/,/g, ''));
  if (!isFinite(amount)) return null;
  const suffix = (m[2] || '').toLowerCase();
  if (suffix === 'k') amount *= 1000;
  if (suffix === 'm') amount *= 1000000;
  // Spaces, commas and semicolons off both edges - the server twin's rule.
  const rest = (m[3] || '').replace(/^[\s,;]+|[\s,;]+$/g, '');
  if (rest && /^[/-]?\s*\$?[\d,]/.test(rest)) return null;
  // A percent unit straight after the amount: a decimal comma ("2,5%") is not
  // the amount 25 with the qualifier "%". Nor is a fraction glyph ("1½").
  if (rest && (PERCENT_UNIT_RE.test(rest) || /^[¼-¾⅐-⅟↉]/.test(rest))) return null;
  const body = amount % 1
    ? `$${amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`.replace('.00', '')
    : `$${amount.toLocaleString('en-US')}`;
  return rest ? `${body} ${rest}` : body;
}

// A fact that takes a dollar amount OR a percentage (the wind / hail and
// earthquake deductibles): a percentage from 0 to 100 as "2%" with the words
// around it kept ("2% of TIV"), else a dollar amount; null for neither, and for
// a percentage that is not the first figure ("$25,000 or 2%" - write the
// percentage first: "2% / $25,000 minimum").
// A bare plain figure ("2", "1.5", ".5") under the deductible basis check's
// line is a percentage: "2" is "2%"; 100 or more stays dollars; anything with a
// "$" is not bare; a fraction reads as before.
// Twin: services/normalization.bare_figure_as_percentage.
export const PERCENT_DEDUCTIBLE_CEILING = 100;
const BARE_FIGURE_RE = /^(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)$/;

export function bareFigurePercent(raw) {
  const s = String(raw ?? '').trim();
  if (!s || !BARE_FIGURE_RE.test(s)) return null;
  const got = percentStatement(`${s}%`);
  if (!got || !got.plain || !(got.number >= 0 && got.number < PERCENT_DEDUCTIBLE_CEILING)) return null;
  return got;
}

export function normalizeAmountOrPercent(raw) {
  const s = (raw || '').trim();
  const pct = percentStatement(s);
  if (pct) return pct.number >= 0 && pct.number <= 100 ? pct.text : null;
  const bare = bareFigurePercent(s);
  if (bare) return bare.text;
  if (mentionsPercentage(s)) return null;
  return normalizeCurrency(raw);
}

// What an amount box holds instead of a figure: "None", "N/A", "No deductible",
// "Not covered", "Excluded", "Waived", "Same as AOP", "See schedule" - never
// "lots". Every word must be the box's own vocabulary, and one of them must say
// which convention it is: a word alone, a negation of a state ("Not covered"),
// or a pointer at a document ("See schedule"). The server's submit check takes
// exactly these, so the page never sends what the server would refuse.
const BOX_WORD_ALONE = new Set([
  'none', 'nil', 'nothing', 'nada', 'zero', 'no', 'n', 'na', 'never', 'irrelevant',
  'excluded', 'exclude', 'excludes', 'exclusion', 'exclusions',
  'waived', 'waive', 'waives', 'waiver', 'declined', 'rejected', 'uninsured',
  'included', 'include', 'includes', 'inclusive', 'same', 'aop',
]);
const BOX_NEGATORS = new Set([
  'not', 'non', 'dont', 'doesnt', 'didnt', 'isnt', 'arent', 'wasnt', 'werent',
  'havent', 'hasnt', 'hadnt', 'without',
]);
const BOX_NEGATED = new Set([
  'covered', 'cover', 'included', 'purchased', 'purchase', 'carried', 'carry',
  'carries', 'insured', 'elected', 'selected', 'written', 'offered',
  // Not 'available': the server reads "Not available" as uncertainty.
  'applicable', 'apply', 'applies', 'relevant', 'required',
  'taken', 'bought', 'buy', 'have', 'has', 'had', 'need', 'needed', 'chosen',
]);
const BOX_POINTERS = new Set(['see', 'per', 'refer', 'refers', 'as']);
const BOX_DOCUMENTS = new Set([
  'schedule', 'scheduled', 'attached', 'attachment', 'policy', 'policies',
  'dec', 'decs', 'declaration', 'declarations', 'page', 'endorsement', 'form',
  'forms', 'quote',
]);
const BOX_FILLER = new Set([
  'deductible', 'deductibles', 'coverage', 'coverages', 'insurance',
  'earthquake', 'earthquakes', 'eq', 'quake', 'earth', 'movement', 'wind',
  'windstorm', 'hail', 'named', 'storm', 'storms', 'hurricane', 'peril',
  'perils', 'all', 'other', 'the', 'a', 'an', 'any', 'for', 'on', 'of', 'in',
  'to', 'as', 'at', 'is', 'are', 'was', 'were', 'be', 'been', 'it', 'its',
  'this', 'that', 'there', 'under', 'with', 'by', 'from', 'building',
  'buildings', 'property', 'location', 'locations', 'do', 'does', 'did', 'we',
  'i', 'our', 'us', 'they', 'amount', 'separate', 'specific', 'longer',
  'known', 'reported', 'report', 'percentage', 'percent', 'shown', 'stated',
  'listed',
]);
const BOX_SETS = [BOX_WORD_ALONE, BOX_NEGATORS, BOX_NEGATED, BOX_POINTERS, BOX_DOCUMENTS, BOX_FILLER];

export function isAmountBoxConvention(raw) {
  const s = String(raw ?? '').toLowerCase();
  if (/[0-9]/.test(s)) return false;
  const words = s.replace(/[’‘'`]/g, '').split(/[^a-z]+/).filter(Boolean);
  if (!words.length || words.some((w) => !BOX_SETS.some((set) => set.has(w)))) return false;
  const has = (set) => words.some((w) => set.has(w));
  return has(BOX_WORD_ALONE)
    || (has(BOX_NEGATORS) && has(BOX_NEGATED))
    || (has(BOX_POINTERS) && has(BOX_DOCUMENTS));
}
