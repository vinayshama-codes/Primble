// Excel number formats: a cell's stored value as the sheet shows it.
//
// THE SAME ALGORITHM AS backend/utils/excel_number_format.py, function for
// function (read that module's note first). The schedule tables' import
// (scheduleImport.js) reads a workbook here; the Excel-as-document reader
// (backend/utils/spreadsheet_text.py) reads it there. One shared file of test
// vectors (backend/tests/fixtures/excel_number_format_vectors.json) is replayed
// through both (backend/tests/test_build22_excel-formats.py), so the two can
// never disagree. Change one, change the other in the same commit.
//
// In short: built-in ids 0-49 (and the locale ids Excel maps onto them);
// General as a cell shows it (11 characters, 1.23457E+11, never
// 0.30000000000000004); up to four sections and conditions ([<=99999]); a
// currency tag's symbol; literals, _x (a space), *x (nothing), @ (the text);
// 0 # ? . , % E+ and fractions; dates and times with Excel's 1900 leap-year
// bug and the 1904 system. A section with a day of the month, a month and a
// year prints MM/DD/YYYY (plus the time it shows); everything else prints as
// the sheet shows it. A value no format can show, or a malformed code, prints
// as General - never a made-up date, never an exception. Numbers round on
// their 15 significant digits, half away from zero, in exact BigInt decimal
// arithmetic, so both languages get the same digits.

// ── Built-in formats ──────────────────────────────────────────────────────
export const BUILTIN_FORMATS = {
  0: 'General', 1: '0', 2: '0.00', 3: '#,##0', 4: '#,##0.00', 9: '0%', 10: '0.00%', 11: '0.00E+00',
  12: '# ?/?', 13: '# ??/??', 14: 'm/d/yyyy', 15: 'd-mmm-yy', 16: 'd-mmm', 17: 'mmm-yy', 18: 'h:mm AM/PM',
  19: 'h:mm:ss AM/PM', 20: 'h:mm', 21: 'h:mm:ss', 22: 'm/d/yyyy h:mm', 37: '#,##0 ;(#,##0)',
  38: '#,##0 ;[Red](#,##0)', 39: '#,##0.00;(#,##0.00)', 40: '#,##0.00;[Red](#,##0.00)',
  41: '_(* #,##0_);_(* \\(#,##0\\);_(* "-"_);_(@_)',
  42: '_("$"* #,##0_);_("$"* \\(#,##0\\);_("$"* "-"_);_(@_)',
  43: '_(* #,##0.00_);_(* \\(#,##0.00\\);_(* "-"??_);_(@_)',
  44: '_("$"* #,##0.00_);_("$"* \\(#,##0.00\\);_("$"* "-"??_);_(@_)',
  45: 'mm:ss', 46: '[h]:mm:ss', 47: 'mm:ss.0', 48: '##0.0E+0', 49: '@',
  63: '"$"#,##0_);\\("$"#,##0\\)', 64: '"$"#,##0_);[Red]\\("$"#,##0\\)',
  65: '"$"#,##0.00_);\\("$"#,##0.00\\)', 66: '"$"#,##0.00_);[Red]\\("$"#,##0.00\\)',
};
// The locale ids (Asian and Thai workbooks) as en-US Excel shows them: 27-31
// and 50-58 as m/d/yyyy - Brent's claims sheet, written by WPS Sheets, dates
// every cell with 58 - and 71-81 as their Western twins. Unknown = General.
export const BUILTIN_FORMAT_ALIASES = {
  5: 37, 6: 38, 7: 39, 8: 40, 23: 0, 24: 0, 25: 0, 26: 0, 27: 14, 28: 14, 29: 14, 30: 14, 31: 14,
  50: 14, 51: 14, 52: 14, 53: 14, 54: 14, 55: 14, 56: 14, 57: 14, 58: 14, 59: 1, 60: 2, 61: 3, 62: 4,
  67: 9, 68: 10, 69: 12, 70: 13, 71: 14, 72: 14, 73: 15, 74: 16, 75: 17, 76: 20, 77: 21, 78: 22,
  79: 45, 80: 46, 81: 47, 82: 0,
};

const has = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);

/** The format code of a built-in number format id ("General" when unknown). */
export function builtinFormatCode(id) {
  let n;
  if (typeof id === 'number' && Number.isInteger(id)) n = id;
  else if (typeof id === 'string' && /^[ \t]*[+-]?[0-9]+[ \t]*$/.test(id)) n = parseInt(id, 10);
  else return 'General';
  if (has(BUILTIN_FORMATS, n)) return BUILTIN_FORMATS[n];
  if (has(BUILTIN_FORMAT_ALIASES, n)) return BUILTIN_FORMATS[BUILTIN_FORMAT_ALIASES[n]];
  return 'General';
}

// ── Exact decimal arithmetic: a value is [D, X], the BigInt D times 10**X ─────
const B0 = BigInt(0);
const B1 = BigInt(1);
const B2 = BigInt(2);
const B10 = BigInt(10);
const POW10 = [B1];

function p10(n) {
  while (POW10.length <= n) POW10.push(POW10[POW10.length - 1] * B10);
  return POW10[n];
}

const ndigits = (d) => d.toString().length;

/** a (> 0, finite) as [D, X] from its shortest round-trip digits (String()). */
function shortest(a) {
  const r = String(a);
  const ei = r.indexOf('e');
  const mant = ei === -1 ? r : r.slice(0, ei);
  let x = ei === -1 ? 0 : parseInt(r.slice(ei + 1), 10);
  let digits = mant;
  const dot = mant.indexOf('.');
  if (dot !== -1) {
    digits = mant.slice(0, dot) + mant.slice(dot + 1);
    x -= mant.length - dot - 1;
  }
  digits = digits.replace(/^0+/, '');
  if (!digits) return [B0, 0];
  const core = digits.replace(/0+$/, '');
  return [BigInt(core), x + digits.length - core.length];
}

/** [d, x] rounded half away from zero to p significant digits, trailing zeros dropped. */
function roundSig(d, x, p) {
  const n = ndigits(d);
  if (d !== B0 && n > p) {
    const q = p10(n - p);
    d = (B2 * d + q) / (B2 * q);
    x += n - p;
    if (ndigits(d) > p) { d /= B10; x += 1; }
  }
  while (d !== B0 && d % B10 === B0) { d /= B10; x += 1; }
  return [d, x];
}

/** a (>= 0) on Excel's 15 significant digits. */
function sig15(a) {
  if (a === 0) return [B0, 0];
  const [d, x] = shortest(a);
  return roundSig(d, x, 15);
}

/** d * 10**x * 10**k rounded half away from zero to a BigInt. */
function scaled(d, x, k) {
  const s = x + k;
  if (s >= 0) return d * p10(s);
  const q = p10(-s);
  return (B2 * d + q) / (B2 * q);
}

// ── General ──────────────────────────────────────────────────────────────
const finite = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);

function fixed(d, x, k) {
  const n = scaled(d, x, k);
  if (k <= 0) return n.toString();
  const s = n.toString().padStart(k + 1, '0');
  const whole = s.slice(0, -k);
  const frac = s.slice(-k).replace(/0+$/, '');
  return whole + (frac ? `.${frac}` : '');
}

function expo(d0, x0, p) {
  const [d, x] = roundSig(d0, x0, p);
  const m = d.toString();
  const e = m.length - 1 + x;
  const mant = m[0] + (m.length > 1 ? `.${m.slice(1)}` : '');
  return `${mant}E${e < 0 ? '-' : '+'}${String(Math.abs(e)).padStart(2, '0')}`;
}

/** A number as Excel's General format shows it in a cell (at most 11 characters). */
export function generalText(value) {
  const v = finite(value);
  if (v === null) return '';
  if (v === 0) return '0';
  if (Number.isInteger(v) && Math.abs(v) < 1e11) return String(v); // fits in 11 digits (fast path)
  const neg = v < 0;
  const [d, x] = sig15(neg ? -v : v);
  const e = ndigits(d) - 1 + x;
  let o;
  if (e >= -4 && e <= -1) {
    o = fixed(d, x, 9);
  } else if (e >= -9 && e <= 9) {
    o = fixed(d, x, 12);
    if (o.length > 11) o = e >= 0 ? fixed(d, x, 9 - e) : expo(d, x, 6);
  } else if (e === 10) {
    o = fixed(d, x, 0);
    if (o.length > 11) o = expo(d, x, 6);
  } else {
    o = expo(d, x, 6);
  }
  return (neg ? '-' : '') + o;
}

/** value on its 15 significant digits (every digit Excel stores), times
 *  10**shift: plain decimal while the leading digit sits at 10**-9 .. 10**14,
 *  scientific with every digit beyond. Nothing rounded away, nothing invented. */
export function fullNumberText(value, shift = 0) {
  const v = finite(value);
  if (v === null) return '';
  if (v === 0) return '0';
  const neg = v < 0;
  const [d, x0] = sig15(neg ? -v : v);
  const x = x0 + Math.trunc(Number(shift) || 0);
  const e = ndigits(d) - 1 + x;
  const o = e >= -9 && e <= 14 ? fixed(d, x, Math.max(0, -x)) : expo(d, x, 15);
  return (neg ? '-' : '') + o;
}

/** General for the READERS (Z31-X review): Excel's cell text, unless it is
 *  another number than the cell stores (a 12- to 15-digit ID shown
 *  1.23457E+11, a decimal cut at 11 characters) - then every stored digit. */
function generalDigits(v) {
  const shown = generalText(v);
  if (Number.isInteger(v) && Math.abs(v) < 1e11) return shown; // nothing to lose (fast path)
  const full = fullNumberText(v);
  return Number(shown) === Number(full) ? shown : full;
}

// ── Parsing a format code ──────────────────────────────────────────────────
// A token is [kind, value, extra, raw] (the Python module's tuples).
const COND_RE = /^ *(<=|>=|<>|=<|=>|<|>|=) *([+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?) *$/;
const ELAPSED_RE = /^(?:h+|m+|s+)$/i;
const DATE_LETTERS = 'ymdhseb';
const EMPTY_FILL = { 0: '0', '#': '', '?': ' ' };
const DEN_FILL = { 0: ' ', '#': '', '?': ' ' };
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September',
  'October', 'November', 'December'];
const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const SERIAL_EPSILON = 1e-9;
const LAST_SERIAL_1900 = 2958465;
const LAST_SERIAL_1904 = 2957003;
const MAX_CODE_LENGTH = 1024; // no real format comes near it; bounds the arithmetic
const AMPM_ZH = '上午/下午';

/** positive;negative;zero;text, split outside quotes, escapes, _x / *x and [...]. */
function splitSections(code) {
  const out = [];
  let cur = '';
  let quoted = false;
  let i = 0;
  const n = code.length;
  while (i < n) {
    const ch = code[i];
    if (quoted) {
      cur += ch;
      quoted = ch !== '"';
      i += 1;
    } else if (ch === '"') {
      quoted = true;
      cur += ch;
      i += 1;
    } else if (ch === '\\' || ch === '_' || ch === '*') {
      cur += code.slice(i, i + 2);
      i += 2;
    } else if (ch === '[') {
      const j = code.indexOf(']', i + 1);
      if (j === -1) { cur += code.slice(i); break; }
      cur += code.slice(i, j + 1);
      i = j + 1;
    } else if (ch === ';') {
      out.push(cur);
      cur = '';
      i += 1;
    } else {
      cur += ch;
      i += 1;
    }
  }
  out.push(cur);
  return out;
}

/** One section as {toks, cond, bad}. */
function tokenize(s) {
  const toks = [];
  let cond = null;
  let bad = false;
  let i = 0;
  const n = s.length;
  while (i < n) {
    const ch = s[i];
    const low = ch.toLowerCase();
    if (ch === '"') {
      const j = s.indexOf('"', i + 1);
      if (j === -1) { toks.push(['lit', s.slice(i + 1), null, s.slice(i)]); bad = true; break; }
      toks.push(['lit', s.slice(i + 1, j), null, s.slice(i, j + 1)]);
      i = j + 1;
    } else if (ch === '\\') {
      toks.push(['lit', s.slice(i + 1, i + 2), null, s.slice(i, i + 2)]);
      i += 2;
    } else if (ch === '_') {
      toks.push(['lit', i + 1 < n ? ' ' : '', null, s.slice(i, i + 2)]);
      i += 2;
    } else if (ch === '*') {
      toks.push(['lit', '', null, s.slice(i, i + 2)]);
      i += 2;
    } else if (ch === '[') {
      const j = s.indexOf(']', i + 1);
      if (j === -1) { toks.push(['lit', s.slice(i), null, s.slice(i)]); bad = true; break; }
      const inner = s.slice(i + 1, j);
      const raw = s.slice(i, j + 1);
      i = j + 1;
      if (ELAPSED_RE.test(inner)) {
        toks.push(['el', inner[0].toLowerCase(), inner.length, raw]);
        continue;
      }
      const m = inner.match(COND_RE);
      if (m) {
        if (cond === null) {
          const op = m[1] === '=<' ? '<=' : m[1] === '=>' ? '>=' : m[1];
          cond = [op, Number(m[2])];
        }
        continue;
      }
      if (inner.startsWith('$')) {
        const symbol = inner.slice(1).split('-', 1)[0];
        if (symbol) toks.push(['lit', symbol, null, raw]);
      }
      // a colour, [ColorN], a locale / calendar / DBNum tag: shows nothing
    } else if (s.slice(i, i + 5).toLowerCase() === 'am/pm') {
      toks.push(['ampm', 'AM', 'PM', s.slice(i, i + 5)]);
      i += 5;
    } else if (s.slice(i, i + 3).toLowerCase() === 'a/p') {
      toks.push(['ampm', s[i], s[i + 2], s.slice(i, i + 3)]);
      i += 3;
    } else if (s.slice(i, i + 5) === AMPM_ZH) {
      toks.push(['ampm', AMPM_ZH.slice(0, 2), AMPM_ZH.slice(3), s.slice(i, i + 5)]);
      i += 5;
    } else if (s.slice(i, i + 7).toLowerCase() === 'general') {
      toks.push(['gen', null, null, s.slice(i, i + 7)]);
      i += 7;
    } else if ((ch === 'E' || ch === 'e') && i + 1 < n && (s[i + 1] === '+' || s[i + 1] === '-')) {
      toks.push(['exp', ch, s[i + 1], s.slice(i, i + 2)]);
      i += 2;
    } else if (low.length === 1 && DATE_LETTERS.includes(low)) {
      let j = i;
      while (j < n && s[j].toLowerCase() === low) j += 1;
      toks.push(['dt', low, j - i, s.slice(i, j)]);
      i = j;
    } else if (ch === '0' || ch === '#' || ch === '?') {
      toks.push(['ph', ch, null, ch]);
      i += 1;
    } else if (ch === '.') {
      toks.push(['dot', null, null, ch]);
      i += 1;
    } else if (ch === ',') {
      toks.push(['comma', null, null, ch]);
      i += 1;
    } else if (ch === '%') {
      toks.push(['pct', null, null, ch]);
      i += 1;
    } else if (ch === '@') {
      toks.push(['at', null, null, ch]);
      i += 1;
    } else if (ch === '/') {
      let j = i + 1;
      if (j < n && '123456789'.includes(s[j])) {
        while (j < n && '0123456789'.includes(s[j])) j += 1;
      }
      toks.push(['slash', s.slice(i + 1, j), null, s.slice(i, j)]);
      i = j;
    } else {
      toks.push(['lit', ch, null, ch]);
      i += 1;
    }
  }
  return { toks, cond, bad };
}

const asLit = (t) => ['lit', t[3], null, t[3]];

function compileDate(sec) {
  let toks = sec.toks.slice();
  // "m" / "mm" right after an hour is minutes; so is one right before a second.
  let prev = null;
  toks.forEach((t, k) => {
    if (t[0] === 'dt') {
      if (t[1] === 'm' && t[2] <= 2 && prev === 'h') toks[k] = ['dt', 'M', t[2], t[3]];
      prev = toks[k][1];
    } else if (t[0] === 'el') {
      prev = t[1];
    } else if (t[0] === 'ampm') {
      prev = 'a';
    }
  });
  let nxt = null;
  for (let k = toks.length - 1; k >= 0; k -= 1) {
    const t = toks[k];
    if (t[0] === 'dt') {
      if (t[1] === 'm') {
        if (t[2] <= 2 && nxt === 's') toks[k] = ['dt', 'M', t[2], t[3]];
      } else {
        nxt = t[1];
      }
    } else if (t[0] === 'el') {
      nxt = t[1];
    }
  }
  // fractional seconds: a point right after s / ss / [ss], then zeros
  const out = [];
  let k = 0;
  while (k < toks.length) {
    const t = toks[k];
    const last = out[out.length - 1];
    if (t[0] === 'dot' && last && ((last[0] === 'dt' && last[1] === 's') || (last[0] === 'el' && last[1] === 's'))) {
      let j = k + 1;
      while (j < toks.length && toks[j][0] === 'ph' && toks[j][1] === '0') j += 1;
      if (j > k + 1) {
        out.push(['fs', j - k - 1, null, toks.slice(k, j).map((x) => x[3]).join('')]);
        k = j;
        continue;
      }
    }
    out.push(t);
    k += 1;
  }
  toks = [];
  out.forEach((t) => {
    if (t[0] === 'ph' || t[0] === 'exp' || t[0] === 'gen' || t[0] === 'at') {
      sec.bad = true; // a number placeholder inside a date
      toks.push(asLit(t));
    } else if (t[0] === 'dot' || t[0] === 'comma' || t[0] === 'pct' || t[0] === 'slash') {
      toks.push(asLit(t));
    } else {
      toks.push(t);
    }
  });
  sec.toks = toks;
  const units = toks.filter((t) => t[0] === 'dt').map((t) => t[1]);
  sec.ampm = toks.some((t) => t[0] === 'ampm');
  sec.fsMax = Math.max(0, ...toks.filter((t) => t[0] === 'fs').map((t) => t[1]));
  sec.showsDate = units.some((u) => 'ymdeb'.includes(u));
  const dayOfMonth = toks.some((t) => t[0] === 'dt' && t[1] === 'd' && t[2] <= 2);
  sec.fullDate = dayOfMonth && units.includes('m') && units.some((u) => 'yeb'.includes(u));
  const timed = [];
  toks.forEach((t, idx) => {
    if (t[0] === 'ampm' || t[0] === 'el' || t[0] === 'fs' || (t[0] === 'dt' && 'hMs'.includes(t[1]))) timed.push(idx);
  });
  sec.hasTime = timed.length > 0;
  if (timed.length) sec.timeSpan = [timed[0], timed[timed.length - 1]];
}

function compileNumber(sec) {
  const { toks } = sec;
  const n = toks.length;
  const roles = new Array(n).fill(null);
  const expAt = toks.findIndex((t) => t[0] === 'exp');
  let slashAt = -1;
  if (expAt === -1) {
    for (let k = 0; k < n; k += 1) {
      const t = toks[k];
      if (t[0] === 'slash' && k > 0 && toks[k - 1][0] === 'ph' && (t[1] || (k + 1 < n && toks[k + 1][0] === 'ph'))) {
        slashAt = k;
        break;
      }
    }
  }
  sec.pct = toks.filter((t) => t[0] === 'pct').length;
  toks.forEach((t, k) => {
    if (t[0] === 'pct') roles[k] = ['lit', '%'];
    else if (t[0] === 'lit') roles[k] = ['lit', t[1]];
    else if (!['slash', 'exp', 'dot', 'comma', 'ph'].includes(t[0])) roles[k] = ['lit', t[3]];
  });
  if (expAt !== -1) {
    sec.mode = 'sci';
    const dotAt = toks.findIndex((t, k) => t[0] === 'dot' && k < expAt);
    toks.forEach((t, k) => {
      if (roles[k] !== null) return;
      if (t[0] === 'ph') {
        if (k > expAt) { roles[k] = ['eph']; sec.expPh.push(t[1]); }
        else if (dotAt !== -1 && k > dotAt) { roles[k] = ['frac', sec.fracPh.length]; sec.fracPh.push(t[1]); }
        else { roles[k] = ['int', sec.intPh.length]; sec.intPh.push(t[1]); }
      } else if (k === expAt) {
        roles[k] = ['exp', t[1], t[2]];
      } else if (k === dotAt) {
        roles[k] = ['dot'];
      } else if (t[0] === 'comma') {
        roles[k] = ['skip'];
      } else {
        roles[k] = ['lit', t[3]];
      }
    });
  } else if (slashAt !== -1) {
    sec.mode = 'frac';
    let start = slashAt - 1;
    while (start > 0 && toks[start - 1][0] === 'ph') start -= 1;
    const fixedDen = toks[slashAt][1];
    let denEnd = slashAt;
    if (!fixedDen) {
      while (denEnd + 1 < n && toks[denEnd + 1][0] === 'ph') denEnd += 1;
    } else {
      sec.denFixed = parseInt(fixedDen, 10);
    }
    let lastInt = -1;
    for (let k = 0; k < start; k += 1) if (toks[k][0] === 'ph') lastInt = k;
    toks.forEach((t, k) => {
      if (roles[k] !== null) return;
      if (t[0] === 'ph') {
        if (k < start) { roles[k] = ['int', sec.intPh.length]; sec.intPh.push(t[1]); }
        else if (k < slashAt) { roles[k] = ['num', sec.numPh.length]; sec.numPh.push(t[1]); }
        else if (k <= denEnd) { roles[k] = ['den', sec.denPh.length]; sec.denPh.push(t[1]); }
        else roles[k] = ['lit', t[3]];
      } else if (k === slashAt) {
        roles[k] = ['slash'];
      } else if (t[0] === 'comma' && k < lastInt && toks.slice(0, k).some((q) => q[0] === 'ph')) {
        roles[k] = ['skip'];
        sec.grouping = true;
      } else {
        roles[k] = ['lit', t[3]];
      }
    });
  } else {
    sec.mode = 'dec';
    const dotAt = toks.findIndex((t) => t[0] === 'dot');
    const endInt = dotAt !== -1 ? dotAt : n;
    const intIdx = [];
    for (let k = 0; k < endInt; k += 1) if (toks[k][0] === 'ph') intIdx.push(k);
    toks.forEach((t, k) => {
      if (roles[k] !== null) return;
      if (t[0] === 'ph') {
        if (k < endInt) { roles[k] = ['int', sec.intPh.length]; sec.intPh.push(t[1]); }
        else { roles[k] = ['frac', sec.fracPh.length]; sec.fracPh.push(t[1]); }
      } else if (k === dotAt) {
        roles[k] = ['dot'];
      } else if (t[0] === 'comma') {
        let q = k - 1;
        while (q >= 0 && toks[q][0] === 'comma') q -= 1;
        const afterPh = q >= 0 && toks[q][0] === 'ph';
        if (k < endInt && intIdx.length && intIdx[0] < k && k < intIdx[intIdx.length - 1]) {
          roles[k] = ['skip'];
          sec.grouping = true; // a comma between digits: the thousands separator
        } else if (afterPh) {
          roles[k] = ['skip'];
          sec.scale += 1; // a comma after the digits: / 1,000
        } else {
          roles[k] = ['lit', ','];
        }
      } else {
        roles[k] = ['lit', t[3]]; // a second point, a lone slash
      }
    });
  }
  sec.roles = roles;
}

function compileSection(text) {
  const { toks: raw, cond, bad } = tokenize(text);
  const hasAt = raw.some((t) => t[0] === 'at');
  const core = raw.some((t) => t[0] === 'ampm' || t[0] === 'el' || (t[0] === 'dt' && 'ymdhs'.includes(t[1])));
  // e (year) and b (Buddhist year) are date parts only beside others.
  const toks = core ? raw : raw.map((t) => (t[0] === 'dt' ? asLit(t) : t));
  const sec = {
    cond, toks, bad, hasAt, roles: [], grouping: false, scale: 0, pct: 0,
    intPh: [], fracPh: [], numPh: [], denPh: [], expPh: [], denFixed: 0, mode: 'dec',
    fullDate: false, showsDate: false, hasTime: false, ampm: false, timeSpan: [0, -1], fsMax: 0, kind: 'number',
  };
  if (core) {
    sec.kind = 'date';
    compileDate(sec);
  } else if (toks.some((t) => t[0] === 'gen')) {
    sec.kind = 'general';
  } else if (hasAt) {
    sec.kind = 'text';
  } else {
    compileNumber(sec);
  }
  sec.showsNumber = !!(sec.intPh.length || sec.fracPh.length || sec.numPh.length || sec.denPh.length || sec.denFixed);
  return sec;
}

function compileFormatUncached(code0) {
  const code = code0 || 'General'; // a style with an empty formatCode shows General
  const parts = splitSections(code.slice(0, MAX_CODE_LENGTH + 1));
  const sections = parts.map(compileSection);
  const fmt = {
    sections,
    bad: code.length > MAX_CODE_LENGTH || parts.length > 4 || sections.some((s) => s.bad),
    numeric: sections,
    text: null,
  };
  const last = sections[sections.length - 1];
  if (sections.length === 4) {
    fmt.text = last;
    fmt.numeric = sections.slice(0, 3);
  } else if (last.hasAt) {
    fmt.text = last;
    fmt.numeric = sections.slice(0, -1);
  }
  return fmt;
}

const COMPILED = new Map();

function compileFormat(code) {
  let fmt = COMPILED.get(code);
  if (!fmt) {
    fmt = compileFormatUncached(code);
    if (COMPILED.size >= 4096) COMPILED.clear();
    COMPILED.set(code, fmt);
  }
  return fmt;
}

// ── Rendering ──────────────────────────────────────────────────────────────
function testCond(cond, v) {
  const [op, t] = cond;
  switch (op) {
    case '<': return v < t;
    case '>': return v > t;
    case '=': return v === t;
    case '<=': return v <= t;
    case '>=': return v >= t;
    default: return v !== t; // <>
  }
}

/** [section, its index] for the number v, or [null, -1]. */
function pick(fmt, v) {
  const secs = fmt.numeric;
  const n = secs.length;
  if (!n) return [null, -1];
  const s0 = secs[0];
  if (s0.cond !== null) {
    if (testCond(s0.cond, v)) return [s0, 0];
  } else if (n === 1 || (n === 2 && v >= 0) || (n >= 3 && v > 0)) {
    return [s0, 0];
  }
  if (n < 2) return [null, -1];
  const s1 = secs[1];
  if (s1.cond !== null) {
    if (testCond(s1.cond, v)) return [s1, 1];
  } else if (v < 0 || (n === 2 && s0.cond !== null)) {
    return [s1, 1];
  }
  if (n < 3) return [null, -1];
  return [secs[2], 2];
}

function fillInt(digits, phs) {
  const pieces = new Array(phs.length).fill('');
  let left = digits.length;
  for (let j = phs.length - 1; j >= 0; j -= 1) {
    if (j === 0 && left) {
      pieces[0] = digits.slice(0, left);
    } else if (left) {
      pieces[j] = digits[left - 1];
      left -= 1;
    } else {
      pieces[j] = EMPTY_FILL[phs[j]];
    }
  }
  return pieces;
}

function fillFrac(digits, phs) {
  const pieces = digits.split('');
  for (let j = phs.length - 1; j >= 0; j -= 1) {
    if (phs[j] === '0' || digits[j] !== '0') break;
    pieces[j] = EMPTY_FILL[phs[j]];
  }
  return pieces;
}

function group(text) {
  let body = text.replace(/^ +/, '');
  const lead = text.slice(0, text.length - body.length);
  const groups = [];
  while (body.length > 3) {
    groups.unshift(body.slice(-3));
    body = body.slice(0, -3);
  }
  if (body) groups.unshift(body);
  return lead + groups.join(',');
}

function intPieces(sec, digits) {
  const pieces = fillInt(digits, sec.intPh);
  if (sec.grouping && pieces.length) return [group(pieces.join('')), ...new Array(pieces.length - 1).fill('')];
  return pieces;
}

function divmod(a, b) {
  return [a / b, a % b];
}

function renderDec(sec, a) {
  const [d, x0] = sig15(a);
  const x = x0 + 2 * sec.pct - 3 * sec.scale;
  const f = sec.fracPh.length;
  const [whole, frac] = divmod(scaled(d, x, f), p10(f));
  const digits = whole !== B0 ? whole.toString() : '';
  const ipieces = intPieces(sec, digits);
  const fpieces = f ? fillFrac(frac.toString().padStart(f, '0'), sec.fracPh) : [];
  let out = '';
  sec.roles.forEach((r) => {
    if (r[0] === 'lit') out += r[1];
    else if (r[0] === 'int') out += ipieces[r[1]];
    else if (r[0] === 'frac') out += fpieces[r[1]];
    else if (r[0] === 'dot') out += `${sec.intPh.length ? '' : digits}.`;
  });
  return out;
}

function renderSci(sec, a) {
  const step = sec.intPh.length || 1;
  const f = sec.fracPh.length;
  let ex = 0;
  let mant = B0;
  if (a) {
    const [d, x0] = sig15(a);
    const xd = x0 + 2 * sec.pct;
    const e10 = ndigits(d) - 1 + xd;
    ex = Math.floor(e10 / step) * step;
    mant = scaled(d, xd - ex, f);
    if (mant >= p10(step + f)) {
      ex += step;
      mant = scaled(d, xd - ex, f);
    }
  }
  const [whole, frac] = divmod(mant, p10(f));
  const digits = whole !== B0 ? whole.toString() : '';
  const ipieces = fillInt(digits, sec.intPh);
  const fpieces = f ? fillFrac(frac.toString().padStart(f, '0'), sec.fracPh) : [];
  const width = sec.expPh.filter((p) => p === '0').length;
  let out = '';
  sec.roles.forEach((r) => {
    if (r[0] === 'lit') out += r[1];
    else if (r[0] === 'int') out += ipieces[r[1]];
    else if (r[0] === 'frac') out += fpieces[r[1]];
    else if (r[0] === 'dot') out += `${sec.intPh.length ? '' : digits}.`;
    else if (r[0] === 'exp') {
      const sign = ex < 0 ? '-' : (r[2] === '+' ? '+' : '');
      out += r[1] + sign + String(Math.abs(ex)).padStart(width, '0');
    }
  });
  return out;
}

function gcd(a, b) {
  let x = a;
  let y = b;
  while (y !== B0) [x, y] = [y, x % y];
  return x;
}

/** The fraction p/q closest to n/d with q <= maxDen (Fraction.limit_denominator). */
function closestFraction(n0, d0, maxDen) {
  const g = gcd(n0, d0);
  const n = n0 / g;
  const d = d0 / g;
  if (d <= maxDen) return [n, d];
  let [p0, q0, p1, q1] = [B0, B1, B1, B0];
  let nn = n;
  let dd = d;
  for (;;) {
    const a = nn / dd;
    const q2 = q0 + a * q1;
    if (q2 > maxDen) break;
    [p0, q0, p1, q1] = [p1, q1, p0 + a * p1, q2];
    [nn, dd] = [dd, nn - a * dd];
  }
  const k = (maxDen - q0) / q1;
  if (B2 * dd * (q0 + k * q1) <= d) return [p1, q1];
  return [p0 + k * p1, q0 + k * q1];
}

function renderFrac(sec, a) {
  const [d, x0] = sig15(a);
  const x = x0 + 2 * sec.pct;
  const num = x >= 0 ? d * p10(x) : d;
  const den = x >= 0 ? B1 : p10(-x);
  const mixed = sec.intPh.length > 0;
  let [whole, rem] = mixed ? divmod(num, den) : [B0, num];
  let p;
  let q;
  if (sec.denFixed) {
    q = BigInt(sec.denFixed);
    p = (B2 * rem * q + den) / (B2 * den);
  } else {
    [p, q] = closestFraction(rem, den, p10(Math.min(sec.denPh.length, 7)) - B1);
  }
  if (mixed && q !== B0 && p >= q) {
    whole += p / q;
    p %= q;
  }
  const blank = mixed && p === B0;
  const digits = whole !== B0 ? whole.toString() : (blank ? '0' : '');
  const ipieces = intPieces(sec, digits);
  const npieces = fillInt(p.toString(), sec.numPh);
  const qd = q.toString();
  const dpieces = sec.denPh.map((ph, j) => {
    if (j < qd.length) return j === sec.denPh.length - 1 ? qd.slice(j) : qd[j];
    return DEN_FILL[ph];
  });
  const width = sec.numPh.length + 1 + (sec.denFixed ? String(sec.denFixed).length : sec.denPh.length);
  let out = '';
  sec.roles.forEach((r) => {
    if (r[0] === 'lit') out += r[1];
    else if (r[0] === 'int') out += ipieces[r[1]];
    else if (r[0] === 'num') out += blank && r[1] === 0 ? ' '.repeat(width) : (blank ? '' : npieces[r[1]]);
    else if (r[0] === 'slash') out += blank ? '' : `/${sec.denFixed ? String(sec.denFixed) : ''}`;
    else if (r[0] === 'den') out += blank ? '' : dpieces[r[1]];
  });
  return out;
}

const DAY_MS = 86400000;

/** A day count as [year, month, day]; null for no real calendar day. */
function serialYmd(days, date1904) {
  if (days < 0) return null;
  let base;
  if (date1904) {
    if (days > LAST_SERIAL_1904) return null;
    base = Date.UTC(1904, 0, 1);
  } else {
    if (days === 0 || days === 60 || days > LAST_SERIAL_1900) return null;
    base = days < 60 ? Date.UTC(1899, 11, 31) : Date.UTC(1899, 11, 30);
  }
  const dt = new Date(base + days * DAY_MS);
  return [dt.getUTCFullYear(), dt.getUTCMonth() + 1, dt.getUTCDate()];
}

const pad = (v, n) => String(v).padStart(n, '0');

function renderDate(sec, v, date1904) {
  if (v < 0) return null;
  let days;
  let secs = 0;
  let sub = 0;
  if (sec.hasTime) {
    const unit = p10(sec.fsMax);
    const [d, x] = sig15(v);
    const total = scaled(d * BigInt(86400), x, sec.fsMax);
    const perDay = BigInt(86400) * unit;
    const daysBig = total / perDay;
    const rem = total % perDay;
    if (daysBig > BigInt(LAST_SERIAL_1900)) return null;
    days = Number(daysBig);
    secs = Number(rem / unit);
    sub = Number(rem % unit);
  } else {
    days = Math.floor(v + SERIAL_EPSILON);
  }
  if (days > (date1904 ? LAST_SERIAL_1904 : LAST_SERIAL_1900)) return null;
  const ymd = serialYmd(days, date1904);
  if (ymd === null && sec.showsDate) return null;
  const [y, mo, dom] = ymd || [0, 0, 0];
  const wd = (days + (date1904 ? 5 : 6)) % 7;
  const hh = Math.floor(secs / 3600);
  const mi = Math.floor((secs % 3600) / 60);
  const ss = secs % 60;
  const elapsed = days * 86400 + secs;

  const part = (t) => {
    const kind = t[0];
    if (kind === 'lit') return t[1];
    if (kind === 'ampm') return hh < 12 ? t[1] : t[2];
    if (kind === 'fs') return `.${pad(sub, sec.fsMax).slice(0, t[1])}`;
    if (kind === 'el') {
      const value = t[1] === 'h' ? Math.floor(elapsed / 3600) : (t[1] === 'm' ? Math.floor(elapsed / 60) : elapsed);
      return pad(value, t[2]);
    }
    const [, unit, run] = t;
    if (unit === 'y') return run <= 2 ? pad(y % 100, 2) : String(y);
    if (unit === 'e') return String(y);
    if (unit === 'b') return run <= 2 ? pad((y + 543) % 100, 2) : String(y + 543);
    if (unit === 'm') {
      if (run <= 2) return pad(mo, run);
      if (run === 3) return MONTHS[mo - 1].slice(0, 3);
      return run === 5 ? MONTHS[mo - 1][0] : MONTHS[mo - 1];
    }
    if (unit === 'd') {
      if (run <= 2) return pad(dom, run);
      return run === 3 ? DAYS[wd].slice(0, 3) : DAYS[wd];
    }
    if (unit === 'h') return pad(sec.ampm ? (hh % 12 || 12) : hh, Math.min(run, 2));
    if (unit === 'M') return pad(mi, Math.min(run, 2));
    return pad(ss, Math.min(run, 2)); // s
  };

  if (sec.fullDate) {
    let text = `${pad(mo, 2)}/${pad(dom, 2)}/${y}`;
    if (sec.hasTime) {
      const [a, b] = sec.timeSpan;
      text += ` ${sec.toks.slice(a, b + 1).map(part).join('')}`;
    }
    return text;
  }
  return sec.toks.map(part).join('');
}

function render(fmt, v, date1904, keepDigits = false) {
  const general = keepDigits ? generalDigits : generalText;
  if (fmt.bad) return general(v);
  const [sec, idx] = pick(fmt, v);
  if (sec === null) return general(v);
  let a = idx === 1 || (idx === 0 && sec.cond !== null) ? Math.abs(v) : v;
  if (sec.kind === 'date') {
    const text = renderDate(sec, a, date1904);
    return text === null ? general(v) : text;
  }
  const neg = a < 0;
  a = Math.abs(a);
  if (sec.kind === 'general' || sec.kind === 'text') {
    const body = sec.toks.map((t) => {
      if (t[0] === 'gen' || t[0] === 'at') return general(a);
      return t[0] === 'lit' ? t[1] : t[3];
    }).join('');
    return (neg ? '-' : '') + body;
  }
  let body;
  if (sec.mode === 'sci') body = renderSci(sec, a);
  else if (sec.mode === 'frac') body = renderFrac(sec, a);
  else body = renderDec(sec, a);
  return (neg && sec.showsNumber ? '-' : '') + body;
}

// ── The doors the readers use ────────────────────────────────────────────────
const NUMBER_RE = /^[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/;
const asciiTrim = (s) => s.replace(/^[ \t\n\r\f\v]+|[ \t\n\r\f\v]+$/g, '');

function codeOf(fmt) {
  let code = fmt;
  if (code !== null && typeof code === 'object') code = code.code ?? 'General';
  return code === null || code === undefined ? 'General' : String(code);
}

/** A number as the format code shows it ("" for a value that is not a finite number).
 *  keepDigits (the two readers pass it): a General text that is another number
 *  than the stored one is replaced by every stored digit (generalDigits). */
export function formatNumber(value, code = 'General', date1904 = false, keepDigits = false) {
  const v = finite(value);
  if (v === null) return '';
  try {
    return render(compileFormat(codeOf(code)), v, !!date1904, !!keepDigits);
  } catch {
    return keepDigits ? generalDigits(v) : generalText(v); // never throw on a cell
  }
}

/** A numeric cell's stored text (its <v>) as its number format shows it. Text
 *  that is not a plain decimal number stays exactly as written. */
export function formatCellNumber(raw, code = 'General', date1904 = false, keepDigits = false) {
  const text = raw === null || raw === undefined ? '' : asciiTrim(String(raw));
  if (!text) return '';
  if (!NUMBER_RE.test(text)) return text;
  const v = Number(text);
  if (!Number.isFinite(v)) return text;
  return formatNumber(v, codeOf(code), date1904, keepDigits);
}

/** A text cell as the format's text section shows it (@ is the text). */
export function formatText(text, code = 'General') {
  const s = text === null || text === undefined ? '' : String(text);
  let fmt;
  try {
    fmt = compileFormat(codeOf(code));
  } catch {
    return s;
  }
  if (fmt.bad || fmt.text === null) return s;
  return fmt.text.toks.map((t) => {
    if (t[0] === 'at') return s;
    return t[0] === 'lit' ? t[1] : t[3];
  }).join('');
}

const ISO_RE = /^([0-9]{4})-([0-9]{2})-([0-9]{2})(?:[T ]([0-9]{2}):([0-9]{2})(?::([0-9]{2})(\.[0-9]+)?)?)?(?:Z|[+-][0-9]{2}:?[0-9]{2})?$/;
const ISO_LOOSE_RE = /^([0-9]{4})-([0-9]{2})-([0-9]{2})(?:[T ][0-9:.]+(?:Z|[+-][0-9]{2}:?[0-9]{2})?)?$/;

/** An ISO date cell as MM/DD/YYYY (the 21 Oct 2026 rule); anything else as written. */
function isoDateText(text) {
  const m = text.match(ISO_LOOSE_RE);
  if (!m || +m[2] < 1 || +m[2] > 12 || +m[3] < 1 || +m[3] > 31) return text;
  return `${m[2]}/${m[3]}/${m[1]}`;
}

/** A strict-OOXML ISO date cell (t="d") as the serial Excel would store. */
export function isoToSerial(text, date1904 = false) {
  const m = asciiTrim(String(text ?? '')).match(ISO_RE);
  if (!m) return null;
  const y = +m[1];
  const mo = +m[2];
  const dd = +m[3];
  if (y < 1) return null;
  const day = new Date(Date.UTC(2000, 0, 1));
  day.setUTCFullYear(y, mo - 1, dd);
  if (day.getUTCFullYear() !== y || day.getUTCMonth() !== mo - 1 || day.getUTCDate() !== dd) return null;
  const hh = +(m[4] || 0);
  const mi = +(m[5] || 0);
  const ss = +(m[6] || 0);
  if (hh > 23 || mi > 59 || ss > 59) return null;
  let serial;
  if (date1904) {
    serial = Math.round((day.getTime() - Date.UTC(1904, 0, 1)) / DAY_MS);
  } else {
    const ref = new Date(Date.UTC(2000, 0, 1));
    ref.setUTCFullYear(1899, 11, 30);
    const n = Math.round((day.getTime() - ref.getTime()) / DAY_MS);
    serial = n >= 61 ? n : n - 1;
  }
  if (serial < 0) return null;
  const frac = m[7] ? Number(m[7]) : 0;
  return serial + (hh * 3600 + mi * 60 + ss + frac) / 86400;
}

/** A t="d" cell: through its format when that format shows a date or a time;
 *  otherwise MM/DD/YYYY (its date part), as before. */
export function formatIsoDateCell(raw, code = 'General', date1904 = false) {
  const text = raw === null || raw === undefined ? '' : asciiTrim(String(raw));
  let dated = false;
  try {
    const fmt = compileFormat(codeOf(code));
    dated = !fmt.bad && fmt.numeric.length > 0 && fmt.numeric[0].kind === 'date';
  } catch {
    dated = false;
  }
  if (dated) {
    const serial = isoToSerial(text, date1904);
    if (serial !== null) return formatNumber(serial, code, date1904);
  }
  return isoDateText(text);
}

// ── What a format is (the 21 Oct reader's classification, kept for callers) ──
export function numberFormatKind(fmt) {
  const code = codeOf(fmt);
  let sec;
  try {
    sec = compileSection(splitSections(code)[0]);
  } catch {
    return { kind: 'number', code };
  }
  const { toks } = sec;
  let kind;
  if (sec.kind === 'date') {
    if (toks.some((t) => t[0] === 'el')) kind = 'time';
    else kind = sec.showsDate ? 'date' : 'time';
  } else if (toks.some((t) => t[0] === 'pct')) {
    kind = 'percent';
  } else {
    const phs = toks.filter((t) => t[0] === 'ph');
    const plain = !toks.some((t) => ['dot', 'comma', 'slash', 'exp', 'at', 'gen'].includes(t[0]));
    kind = phs.length >= 2 && phs.every((t) => t[1] === '0') && plain ? 'zeros' : 'number';
  }
  return { kind, code };
}

/**
 * An Excel day count as MM/DD/YYYY, or "" when it is no real calendar day.
 * 1900 system: day 1 is 01/01/1900 and Excel counts a 29 Feb 1900 that never
 * was, so days 1-59 sit one day later than 61 and up, and day 60 (the phantom
 * 02/29/1900) and day 0 (01/00/1900) are no day at all. 1904 system: day 0 is
 * 01/01/1904. A time of day is dropped (only float noise a hair under midnight
 * counts as that midnight).
 */
export function excelSerialToDate(serial, date1904 = false) {
  let n = null;
  if (typeof serial === 'string') {
    const text = asciiTrim(serial);
    n = NUMBER_RE.test(text) ? Number(text) : null;
  } else {
    n = finite(serial);
  }
  if (n === null || !Number.isFinite(n) || n < 0) return '';
  const ymd = serialYmd(Math.floor(n + SERIAL_EPSILON), !!date1904);
  return ymd === null ? '' : `${pad(ymd[1], 2)}/${pad(ymd[2], 2)}/${ymd[0]}`;
}
