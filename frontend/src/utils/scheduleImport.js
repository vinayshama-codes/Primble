// Spreadsheet import + row validation for bulk schedule capture (Figure 15).
//
// Parsing runs entirely in the browser: the user drops a CSV/XLSX, sees a
// validated preview, fixes what is wrong, and only then are the parsed ROWS
// sent to the server through the existing questionnaire answer channel. No file
// ever leaves the browser, so this needs no upload endpoint, no storage, and no
// virus-scan path.
//
// XLSX is read with `jszip` (already a project dependency) rather than adding a
// spreadsheet library: an .xlsx IS a zip of XML, and we only need the first
// sheet's cells - shown the way the workbook's own number formats show them
// (a date cell as MM/DD/YYYY, not as the day count Excel stores).

import JSZip from 'jszip';
import {
  builtinFormatCode, formatCellNumber, formatIsoDateCell, formatText, fullNumberText,
} from './excelNumberFormat.js';

// Validation mirrors backend/services/schedule_capture.py. The server always
// re-validates - this copy exists so the user gets instant per-cell feedback.
const VIN_RE = /^[A-HJ-NPR-Z0-9]{17}$/;
const YEAR_RE = /^(19|20)\d{2}$/;
const DATE_RE = /^\d{1,2}\/\d{1,2}\/\d{4}$|^\d{4}-\d{2}-\d{2}$/;
const STATE_RE = /^[A-Za-z]{2}$/;
const NUMERIC_RE = /^\d+(\.\d+)?$/;

export const MAX_ROWS = 500;

export function normalizeVin(raw) {
  return String(raw || '').replace(/[\s-]/g, '').toUpperCase();
}

export function isValidVin(raw) {
  return VIN_RE.test(normalizeVin(raw));
}

/** Error message for one cell, or "" when acceptable. */
export function validateCell(col, value) {
  const val = String(value || '').trim();
  if (!val) return col.required ? `${col.label} is required` : '';

  // A code the server says belongs to another line's rating in these documents
  // (the GL window, 21 Oct 2026: "do not substitute WC class codes for GL
  // codes" - schedule_capture.columns_for `refused`, normalised like the
  // server's own codes).
  if (Array.isArray(col.refused) && col.refused.length) {
    const norm = val.toLowerCase().replace(/[^a-z0-9]/g, '');
    if (col.refused.includes(norm)) return col.refused_message || `${col.label} is another line's code`;
  }

  switch (col.type) {
    case 'code':
      // A rating class code is its digits ("91580"), never a word - the same
      // rule as schedule_capture.validate_cell.
      if (!/\d{3,}/.test(val)) return `${col.label} must be the class code's number`;
      break;
    case 'vin':
      if (!isValidVin(val)) return 'VIN must be 17 characters (no I, O or Q)';
      break;
    case 'year':
      // Says the rule that is actually enforced. "4-digit year" rejected
      // 2122 while calling it not-four-digits, which reads as a bug.
      if (!YEAR_RE.test(val)) return `${col.label} must be between 1900 and 2099`;
      break;
    case 'date':
      if (!DATE_RE.test(val)) return `${col.label} must be MM/DD/YYYY`;
      break;
    case 'state':
      if (!STATE_RE.test(val)) return `${col.label} must be a 2-letter state`;
      break;
    case 'currency':
    case 'percent':
    case 'number': {
      const stripped = val.replace(/[$,%\s]/g, '');
      if (!NUMERIC_RE.test(stripped)) return `${col.label} must be a number`;
      break;
    }
    default:
      break;
  }
  return '';
}

/** True when every cell in the row is empty (trailing spreadsheet rows). */
export function isBlankRow(row, columns) {
  return columns.every((c) => !String(row?.[c.key] || '').trim());
}

// The column's example as a hint inside an empty box ("e.g. 789 Commerce Dr").
// A bare "789 Commerce Dr" in grey read as a filled box (owner's run 18ecbfa8,
// 12 Oct 2026: the street address looked entered while it was empty).
export function exampleHint(col) {
  const ph = String(col?.placeholder || '').trim();
  return ph ? `e.g. ${ph}` : '';
}

const _norm = (v) => String(v ?? '').trim().toLowerCase();

/**
 * The example row an older template carried under its header (every column's
 * own placeholder): an untouched copy is an example, never a row to import -
 * it would put a fake "789 Commerce Dr, Houston" building (or "Jane Smith"
 * driver) on the forms. Only the WHOLE example matches: a row the person
 * changed anywhere is theirs.
 */
export function isTemplateExampleRow(row, columns) {
  const cols = Array.isArray(columns) ? columns : [];
  const withExample = cols.filter((c) => String(c?.placeholder || '').trim());
  if (withExample.length < 2) return false;
  return cols.every((c) => {
    const cell = _norm(row?.[c.key]);
    const ph = _norm(c?.placeholder);
    if (!ph) return !cell;
    return cell === ph || cell === `e.g. ${ph}`;
  });
}

/**
 * "Street address on rows 1 and 2" - the required cells the rows still miss
 * (blank rows ignored), "" when none. Said after a save, so the person knows
 * what is left (a save never waits for every cell).
 */
export function missingRequiredSummary(rows, columns) {
  const list = Array.isArray(rows) ? rows : [];
  const parts = [];
  (Array.isArray(columns) ? columns : []).filter((c) => c?.required).forEach((c) => {
    const missing = [];
    list.forEach((row, idx) => {
      if (!isBlankRow(row, columns) && !String(row?.[c.key] ?? '').trim()) missing.push(idx + 1);
    });
    if (!missing.length) return;
    const nums = missing.length === 1
      ? `row ${missing[0]}`
      : `rows ${missing.slice(0, -1).join(', ')} and ${missing[missing.length - 1]}`;
    parts.push(`${c.label} on ${nums}`);
  });
  return parts.join('; ');
}

/**
 * Validate a whole schedule.
 * Returns { errors: {rowIndex: {colKey: msg}}, duplicates: Set<rowIndex> }.
 * Duplicates use the composite of `dedupKeys`, matching the server: a false
 * positive (calling two different vehicles the same) is worse than a miss.
 */
export function validateRows(rows, columns, dedupKeys = []) {
  const errors = {};
  const duplicates = new Set();
  const seen = new Map();

  rows.forEach((row, idx) => {
    if (isBlankRow(row, columns)) return;

    const rowErrors = {};
    columns.forEach((col) => {
      const msg = validateCell(col, row[col.key]);
      if (msg) rowErrors[col.key] = msg;
    });
    if (Object.keys(rowErrors).length) errors[idx] = rowErrors;

    if (dedupKeys.length) {
      let populated = false;
      const sig = dedupKeys
        .map((k) => {
          const raw = String(row[k] || '').trim();
          if (raw) populated = true;
          const norm = k === 'vin' ? normalizeVin(raw) : raw.replace(/\s+/g, ' ').toUpperCase();
          return `${k}=${norm}`;
        })
        .join('|');
      if (populated) {
        if (seen.has(sig)) duplicates.add(idx);
        else seen.set(sig, idx);
      }
    }
  });

  return { errors, duplicates };
}

// ---------------------------------------------------------------------------
// CSV
// ---------------------------------------------------------------------------

/**
 * RFC 4180-ish CSV parser: handles quoted fields, embedded commas/newlines and
 * doubled quotes. Written inline (rather than adding a dependency) because this
 * is the whole requirement - a few hundred bytes of state machine.
 */
export function parseCSV(text) {
  const rows = [];
  let row = [];
  let field = '';
  let inQuotes = false;

  const src = String(text || '').replace(/^\uFEFF/, ''); // strip BOM

  for (let i = 0; i < src.length; i += 1) {
    const ch = src[i];

    if (inQuotes) {
      if (ch === '"') {
        if (src[i + 1] === '"') { field += '"'; i += 1; } else { inQuotes = false; }
      } else {
        field += ch;
      }
      continue;
    }

    if (ch === '"') { inQuotes = true; continue; }
    if (ch === ',') { row.push(field); field = ''; continue; }
    if (ch === '\r') continue;
    if (ch === '\n') { row.push(field); rows.push(row); row = []; field = ''; continue; }
    field += ch;
  }
  if (field !== '' || row.length) { row.push(field); rows.push(row); }

  return rows.filter((r) => r.some((c) => String(c).trim() !== ''));
}

// ---------------------------------------------------------------------------
// XLSX (via jszip - an .xlsx is a zip of XML)
// ---------------------------------------------------------------------------
//
// THE CELLS ARE READ AS THE WORKBOOK SHOWS THEM (21 Oct 2026, Brent's driver
// schedule of 17 Oct). Excel stores a date as a day count and shows it through
// the cell's number format (xl/styles.xml); reading the stored value alone put
// 30058 in "Date of birth" where the sheet shows 04/17/1982, and every date cell
// failed "must be MM/DD/YYYY". The same blindness had two quieter faces: a
// percent cell (stored 1, shown 100%) imported as "1", and a ZIP kept by a
// "00000" format (stored 8540, shown 08540) lost its zero - both pass the
// table's checks as wrong values. So every cell goes through its format -
// EVERY format, every section (Z31-X, 21 Oct 2026: a conditional ZIP format
// read only its first section, a year-only "yyyy" became a whole date) - by
// ONE renderer, excelNumberFormat.js, shared line for line with the document
// reader (backend/utils/excel_number_format.py) and pinned by one set of test
// vectors. A full date (day, month and year) is MM/DD/YYYY, which the tables
// validate; everything else as the sheet shows it ("2020", "08540-1234",
// "$1,234.50", "1:30 PM"). Text goes through the format's text section, a
// boolean reads TRUE / FALSE, an error cell its code ("#N/A").
//
// The XML is read with a small string reader, not the browser's XML DOM, so
// the same code runs under node and is tested on real workbooks. The parts read
// are machine-written SpreadsheetML: none of the elements read below ever nests
// inside one of its own name, so each one ends at its own closing tag. A
// namespace prefix (`<x:c>`, written by some libraries) is accepted.

const XML_PREFIX = '(?:[A-Za-z_][\\w.-]*:)?';
// An element's attributes: quoted values may hold ">" ("[>=100]0").
const XML_ATTRS = '((?:[^>"\']|"[^"]*"|\'[^\']*\')*?)';
const XML_ENTITIES = { lt: '<', gt: '>', amp: '&', quot: '"', apos: "'" };

function decodeXml(text) {
  return String(text ?? '').replace(/&(#[xX][0-9a-fA-F]+|#\d+|lt|gt|amp|quot|apos);/g, (whole, ent) => {
    if (ent[0] !== '#') return XML_ENTITIES[ent];
    const code = ent[1] === 'x' || ent[1] === 'X' ? parseInt(ent.slice(2), 16) : parseInt(ent.slice(1), 10);
    try { return String.fromCodePoint(code); } catch { return whole; }
  });
}

function xmlAttrs(src) {
  const out = {};
  const re = /([\w:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g;
  let m;
  while ((m = re.exec(String(src || '')))) out[m[1]] = decodeXml(m[2] !== undefined ? m[2] : m[3]);
  return out;
}

/** Every `<name>` element (any namespace prefix): [{attrs, inner}], in order. */
function xmlElements(xml, name) {
  const src = String(xml || '');
  const open = new RegExp(`<${XML_PREFIX}${name}(?=[\\s/>])${XML_ATTRS}(/?)>`, 'g');
  const close = new RegExp(`</${XML_PREFIX}${name}\\s*>`, 'g');
  const out = [];
  let m;
  while ((m = open.exec(src))) {
    const attrs = xmlAttrs(m[1]);
    if (m[2] === '/') { out.push({ attrs, inner: '' }); continue; }
    close.lastIndex = open.lastIndex;
    const end = close.exec(src);
    if (!end) { out.push({ attrs, inner: src.slice(open.lastIndex) }); break; }
    out.push({ attrs, inner: src.slice(open.lastIndex, end.index) });
    open.lastIndex = close.lastIndex;
  }
  return out;
}

/** An element's text: entities decoded, CDATA kept as written. */
function xmlText(inner) {
  return String(inner || '').split(/(<!\[CDATA\[[\s\S]*?\]\]>)/).map((part) => (
    part.startsWith('<![CDATA[') ? part.slice(9, -3) : decodeXml(part.replace(/<[^>]*>/g, ''))
  )).join('');
}

// A phonetic guide (<rPh>, East Asian sheets) is not part of the cell's text.
const PHONETIC_RE = new RegExp(`<${XML_PREFIX}rPh(?=[\\s/>])(?:${XML_ATTRS}/>|[\\s\\S]*?</${XML_PREFIX}rPh\\s*>)`, 'g');

/** A shared or inline string: one <t>, or several <r><t> runs joined. */
function richText(inner) {
  return xmlElements(String(inner || '').replace(PHONETIC_RE, ''), 't').map((t) => xmlText(t.inner)).join('');
}

// Excel's last column is XFD (16,384 columns). A reference past it is ignored
// rather than padding a row out to millions of empty cells.
const MAX_SHEET_COLUMNS = 16384;

/** Convert an A1-style ref to a zero-based column index ("C" -> 2, "AA" -> 26). */
function colIndexFromRef(ref) {
  const letters = String(ref || '').toUpperCase().replace(/[^A-Z]/g, '');
  let n = 0;
  for (let i = 0; i < letters.length && n <= MAX_SHEET_COLUMNS; i += 1) n = n * 26 + (letters.charCodeAt(i) - 64);
  return n - 1;
}

// ── Number formats ────────────────────────────────────────────────────────
// One renderer for every number format: excelNumberFormat.js (the document
// reader's twin). A style may name a built-in id with no <numFmt> entry of its
// own; a <numFmt> in the file always wins, whatever its id (Brent's driver
// file redefines 42 and 44 as accounting formats). The names below stay
// exported here for this module's callers and tests.
export {
  builtinFormatCode, excelSerialToDate, formatCellNumber, numberFormatKind,
} from './excelNumberFormat.js';

// Excel's _xHHHH_ escape (ECMA-376 ST_Xstring) in a string part: its line break
// inside a cell is "_x000D_"; a literal "_x0041_" is written "_x005F_x0041_".
// One left-to-right pass, as the document reader decodes it.
function unescapeOoxml(text) {
  const s = String(text ?? '');
  return s.includes('_x') ? s.replace(/_x([0-9A-Fa-f]{4})_/g, (_m, hex) => String.fromCharCode(parseInt(hex, 16))) : s;
}

// A numeric cell's stored value (its <v>), when it is a plain decimal number.
const STORED_NUMBER_RE = /^[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/;

// A shared-string index is its ASCII digits alone - the document reader's rule
// (spreadsheet_text._SHARED_INDEX_RE): "1.5", "2abc", "+1", "-1" are no index.
const SHARED_INDEX_RE = /^[ \t\n\r\f\v]*([0-9]+)[ \t\n\r\f\v]*$/;

// The MM/DD/YYYY a full-date format shows, ahead of the time it may show too.
const SHOWN_FULL_DATE_RE = /^(\d{2}\/\d{2}\/\d{4})(?: |$)/;

// A boolean cell stores 1 / 0 and the sheet shows TRUE / FALSE (anything else as written).
function booleanText(raw) {
  const b = String(raw ?? '').trim();
  if (b === '1') return 'TRUE';
  return b === '0' ? 'FALSE' : raw;
}

export async function parseXLSX(file) {
  const zip = await JSZip.loadAsync(file);
  const read = async (path) => (zip.file(path) ? zip.file(path).async('string') : '');

  // Shared strings: most text cells are stored by index into this table.
  const shared = xmlElements(await read('xl/sharedStrings.xml'), 'si').map((si) => unescapeOoxml(richText(si.inner)));

  // Styles: a cell's s="N" is the Nth <xf> of <cellXfs> (never <cellStyleXfs>),
  // whose numFmtId is a <numFmt> of <numFmts> (never one inside <dxfs>) or a
  // built-in.
  const styles = await read('xl/styles.xml');
  const numFmts = new Map();
  xmlElements(xmlElements(styles, 'numFmts')[0]?.inner, 'numFmt').forEach((nf) => {
    const id = parseInt(nf.attrs.numFmtId, 10);
    if (Number.isInteger(id)) numFmts.set(id, nf.attrs.formatCode || '');
  });
  const styleFormatIds = xmlElements(xmlElements(styles, 'cellXfs')[0]?.inner, 'xf')
    .map((xf) => parseInt(xf.attrs.numFmtId, 10) || 0);
  const codeByStyle = new Map();
  const formatOf = (s) => {
    const idx = s === undefined || s === '' ? 0 : parseInt(s, 10);
    if (!codeByStyle.has(idx)) {
      const id = Number.isInteger(idx) && idx >= 0 && idx < styleFormatIds.length ? styleFormatIds[idx] : 0;
      codeByStyle.set(idx, numFmts.has(id) ? numFmts.get(id) : builtinFormatCode(id));
    }
    return codeByStyle.get(idx);
  };

  // The workbook's date system: days counted from 1900 (Windows Excel) or 1904.
  const workbookPr = xmlElements(await read('xl/workbook.xml'), 'workbookPr')[0];
  const date1904 = /^(1|true)$/i.test(String(workbookPr?.attrs?.date1904 || '').trim());

  // First worksheet by document order. Workbooks name sheets arbitrarily, so
  // pick the lowest-numbered sheetN.xml rather than assuming "sheet1".
  const sheetNames = Object.keys(zip.files)
    .filter((n) => /^xl\/worksheets\/sheet\d+\.xml$/.test(n))
    .sort((a, b) => {
      const na = parseInt(a.match(/(\d+)\.xml$/)[1], 10);
      const nb = parseInt(b.match(/(\d+)\.xml$/)[1], 10);
      return na - nb;
    });
  if (!sheetNames.length) throw new Error('No worksheet found in this file.');

  const rows = [];
  xmlElements(await read(sheetNames[0]), 'row').forEach((rowEl) => {
    const cells = [];
    const stored = {};
    const dates = {};
    xmlElements(rowEl.inner, 'c').forEach((c) => {
      const type = c.attrs.t || 'n';
      const vEl = xmlElements(c.inner, 'v')[0];
      const raw = vEl ? xmlText(vEl.inner) : '';
      // Every value as the sheet shows it, through the cell's number format:
      // text through the format's text section, a number through its section.
      const code = formatOf(c.attrs.s);
      let storedNumber;
      let shownDate;
      let value;
      if (type === 's') {
        const m = SHARED_INDEX_RE.exec(raw);
        const text = m ? shared[Number(m[1])] : undefined;
        value = text === undefined ? '' : formatText(text, code); // no index, or one past the table: no text
      } else if (type === 'inlineStr') {
        const is = xmlElements(c.inner, 'is')[0];
        value = formatText(unescapeOoxml(is ? richText(is.inner) : raw), code);
      } else if (type === 'd') {
        value = formatIsoDateCell(raw, code, date1904);
        const m = SHOWN_FULL_DATE_RE.exec(value);
        if (m) shownDate = m[1];
      } else if (type === 'b') {
        value = booleanText(raw);                      // TRUE / FALSE, as the sheet shows it
      } else if (type === 'str') {
        value = formatText(unescapeOoxml(raw), code);  // a formula's text result
      } else if (type === 'e') {
        value = raw;                                   // an error ("#N/A"): its code, whatever the format
      } else {
        // keepDigits: a General number Excel would cut (a 12-digit claim
        // number shown 1.23457E+11) reads with every digit it stores - the
        // document reader's rule.
        value = formatCellNumber(raw, code, date1904, true);
        if (STORED_NUMBER_RE.test(raw.trim())) {
          storedNumber = raw.trim();
          const m = SHOWN_FULL_DATE_RE.exec(value);
          if (m) shownDate = m[1];
        }
      }
      // A cell with no reference is the next column (allowed by the format).
      const idx = c.attrs.r ? colIndexFromRef(c.attrs.r) : cells.length;
      if (idx < 0 || idx >= MAX_SHEET_COLUMNS) return;
      // Empty cells are omitted from the XML entirely; pad so columns align.
      while (cells.length < idx) cells.push('');
      cells[idx] = String(value ?? '');
      if (storedNumber !== undefined) stored[idx] = storedNumber;
      if (shownDate !== undefined) dates[idx] = shownDate;
    });
    // The numbers the cells hold, and the date a full-date cell shows ahead of
    // its time, beside the text the sheet shows (not part of the row's cells -
    // JSON and every reader of the row see only the text): a numeric or date
    // table column reads them (tableCellValue below).
    Object.defineProperty(cells, 'stored', { value: stored });
    Object.defineProperty(cells, 'dates', { value: dates });
    rows.push(cells);
  });

  return rows.filter((r) => r.some((c) => String(c).trim() !== ''));
}

// ---------------------------------------------------------------------------
// Header mapping
// ---------------------------------------------------------------------------

// British "licence" reads as "license", so every licence header below matches
// either spelling ("Licence Number", "State Licenced In").
function normalizeHeader(h) {
  return String(h || '').toLowerCase().replace(/[^a-z0-9]/g, '').replace(/licenc/g, 'licens');
}

// Common spreadsheet header spellings a broker's existing fleet list may use.
const HEADER_ALIASES = {
  year: ['year', 'modelyear', 'yr', 'vehicleyear'],
  make: ['make', 'manufacturer', 'manufacturersname', 'brand', 'vehiclemake'],
  model: ['model', 'modelname', 'vehiclemodel'],
  vin: ['vin', 'vinnumber', 'vinno', 'vehicleidentificationnumber', 'vinidentifier', 'serialvin'],
  body_type: ['bodytype', 'bodystyle', 'body', 'bodycode'],
  gvw: ['gvw', 'grossvehicleweight', 'gvwr', 'weight'],
  name: ['name', 'fullname', 'drivername', 'driver', 'employeename'],
  dob: ['dob', 'dateofbirth', 'birthdate', 'birthday'],
  license_number: ['licensenumber', 'license', 'licenseno', 'dl', 'dlnumber', 'driverslicense', 'licensenumberidentifier',
    'driverslicensenumber', 'driverslicenseno'],
  // "State Licensed In" (Brent's driver schedule, 17 Oct 2026) and its plain
  // variants - the STATE that issued the licence, never its number.
  license_state: ['licensestate', 'state', 'dlstate', 'licensedstate', 'statelicensed', 'statelicensedin',
    'licensedin', 'stateoflicense', 'stateoflicensure', 'licensingstate', 'issuingstate', 'licenseissuingstate',
    'driverslicensestate', 'licstate'],
  hire_date: ['hiredate', 'datehired', 'hired', 'dateofhire'],
  // A count of years, and only ever this count column (ACORD 127's own
  // ExperienceYearCount box). Never a "year first licensed" or any other date:
  // the import estimates nothing (Brent, 17 Oct 2026). "Years Licensed" is not
  // here either - years since licensing is not the same fact.
  experience_years: ['experienceyears', 'yearsexperience', 'experience', 'yrsexp', 'yearsofexperience',
    'yrsofexperience', 'yrsexperience', 'yearsexp', 'drivingexperience', 'yearsofdrivingexperience',
    'yearsdrivingexperience', 'yearsdriving'],
  address_line1: ['addressline1', 'address', 'streetaddress', 'street', 'addr', 'location'],
  address_city: ['city', 'addresscity', 'town'],
  address_state: ['state', 'addressstate', 'province'],
  address_zip: ['zip', 'zipcode', 'postalcode', 'addresszip', 'postcode'],
  operations_description: ['operations', 'operationsdescription', 'description', 'use', 'occupancy'],
  // Location table premises numbering and COPE columns (6 Oct 2026). A bare
  // "Location" header stays the street's (address_line1 above), never LOC #.
  location_number: ['loc', 'locno', 'locnum', 'locnumber', 'locationno', 'locationnum', 'locationnumber',
    'prem', 'premno', 'premnumber', 'premises', 'premisesno', 'premisesnumber'],
  building_number: ['bldg', 'bldgno', 'bldgnum', 'bldgnumber', 'bld', 'bldno', 'building', 'buildingno',
    'buildingnumber'],
  construction_type: ['construction', 'constructiontype', 'constructionclass', 'constructioncode', 'const',
    'isoconstruction', 'constr'],
  year_built: ['yearbuilt', 'yrbuilt', 'built', 'yearconstructed', 'buildyear', 'originalyear'],
  building_value: ['buildingvalue', 'buildinglimit', 'buildingamount', 'bldgvalue', 'bldglimit',
    'buildingcoverage', 'buildingreplacementcost'],
  bpp_value: ['bpp', 'bppvalue', 'bpplimit', 'businesspersonalproperty', 'personalproperty', 'contents',
    'contentsvalue', 'contentslimit'],
  // Per-building COPE columns (7 Oct 2026).
  roof_material: ['roof', 'rooftype', 'roofmaterial', 'roofing', 'roofcovering', 'roofconstruction'],
  roof_year: ['roofyear', 'roofupdated', 'roofreplaced', 'roofingyear', 'yearroofreplaced'],
  protection_class: ['protectionclass', 'pc', 'ppc', 'protclass', 'fireprotectionclass', 'protectionclasscode',
    'isoprotectionclass', 'firepc'],
  sprinkler: ['sprinkler', 'sprinklers', 'sprinklered', 'sprinklerpercent', 'sprinklerpct', 'percentsprinklered'],
  date: ['date', 'dateofloss', 'lossdate', 'occurrencedate', 'dol', 'dateofoccurrence', 'accidentdate',
    'dateofaccident', 'incidentdate'],
  line_of_business: ['line', 'lineofbusiness', 'lob', 'coverage', 'policytype', 'lineofcoverage'],
  // Loss-run spellings, Brent's claims file among them (17 Oct 2026, attachment
  // C: paid_usd, reserve_usd, reported_date, status, description_asset). A
  // claims file's incurred / expense / first-made / claim-number columns have
  // no loss-table column (no ACORD 125 box) and are named as ignored.
  paid: ['paid', 'amountpaid', 'paidamount', 'losspaid', 'paidusd', 'paidtodate', 'totalpaid'],
  reserved_amount: ['reserved', 'reserves', 'reservedamount', 'reserve', 'reserveusd', 'reservesusd',
    'reserveamount', 'lossreserve', 'outstandingreserve', 'outstandingreserves', 'openreserve'],
  description: ['description', 'whathappened', 'lossdescription', 'details', 'cause', 'descriptionasset',
    'claimdescription', 'descriptionofloss', 'lossdetails'],
  claim_date: ['claimdate', 'datereported', 'reporteddate', 'reportdate', 'datereport', 'reportedon', 'dateofclaim',
    'claimreporteddate', 'datefiled', 'claimfileddate', 'noticedate', 'dateofnotice'],
  // Never a bare "open" / "outstanding": those are a status CELL's own words,
  // and a data row must never read as a header.
  open_code: ['status', 'claimstatus', 'openclosed', 'openorclosed', 'opencode', 'claimopen', 'openyn',
    'claimopenyn'],
};

/** Every header (normalised) a column answers to: its key, its label, its aliases. */
export function headerCandidates(col) {
  return [normalizeHeader(col?.key), normalizeHeader(col?.label), ...(HEADER_ALIASES[col?.key] || [])]
    .filter(Boolean);
}

/**
 * Map a header row to column keys.
 * Returns { mapping: {colKey: sourceIndex}, unmatched: [headerText] }.
 */
export function mapHeaders(headerRow, columns) {
  const normalized = headerRow.map(normalizeHeader);
  const mapping = {};
  const used = new Set();

  columns.forEach((col) => {
    for (const cand of headerCandidates(col)) {
      const idx = normalized.findIndex((h, i) => h === cand && !used.has(i));
      if (idx !== -1) { mapping[col.key] = idx; used.add(idx); return; }
    }
  });

  const unmatched = headerRow.filter((_, i) => !used.has(i) && String(headerRow[i] || '').trim());
  return { mapping, unmatched };
}

// THE HEADER ROW IS FOUND, NOT ASSUMED TO BE ROW 1 (Brent, 17 Oct 2026 item 5).
// His driver schedule has two title rows and a blank row above its header; the
// old check looked at row 1 only, found no header, and mapped every column by
// position - the titles and the header itself came in as "drivers" (15 rows
// for 12) and the licence STATE landed in the licence NUMBER column. Now each
// of the first rows is scored by how many of the table's columns it names (the
// same names `mapHeaders` reads); the header must name at least two. The best
// row is the header. On a tie the row filling more cells wins - a header labels
// every column, while a "Name: | ACME | State: | CO" preamble or a group row
// above the real header does not - and then the earliest, so a data row that
// happens to name as many columns never displaces the header above it. No such
// row = no header, and the old positional import runs (a bare list still
// imports).
//
// THE FIRST HEADER WINS ONCE DATA STARTS (review of 21 Oct, H1). A header-like
// row further down - a "Trailers" block with its own header and one more
// column, an "Excluded drivers" block, a page header repeated with "Page 2 of
// 2" in an extra cell - used to win the score and every row above it, real
// data included, was dropped without a word. The scan now stops at the first
// data row under a header: below that point nothing can become the header, so
// the only rows ever left above the header are the preamble above the FIRST
// one (counted in `skippedAbove`, which the table names to the person).
export const HEADER_SCAN_ROWS = 15;

function _filledCount(cells) {
  return (Array.isArray(cells) ? cells : []).filter((c) => String(c ?? '').trim()).length;
}

/** Index of the header row among the first HEADER_SCAN_ROWS rows, or -1. */
export function findHeaderRow(matrix, columns) {
  const need = Math.min(2, columns.length);
  let best = -1;
  let bestScore = 0;
  let bestFilled = 0;
  const rows = Array.isArray(matrix) ? matrix : [];
  for (let i = 0; i < Math.min(rows.length, HEADER_SCAN_ROWS); i += 1) {
    const cells = Array.isArray(rows[i]) ? rows[i] : [];
    const score = Object.keys(mapHeaders(cells, columns).mapping).length;
    const filled = _filledCount(cells);
    if (score >= need) {
      if (score > bestScore || (score === bestScore && filled > bestFilled)) {
        best = i;
        bestScore = score;
        bestFilled = filled;
      }
    } else if (best !== -1 && filled) {
      // A data row under the header: the header is settled.
      break;
    }
  }
  return best;
}

// A copy of the header further down (a report that prints it again on every
// page) is not a row: every filled cell repeats the header's own cell.
function repeatsHeader(cells, header) {
  let same = 0;
  for (let i = 0; i < Math.max(cells.length, header.length); i += 1) {
    const cell = normalizeHeader(cells[i]);
    if (!cell) continue;
    if (cell !== normalizeHeader(header[i])) return false;
    same += 1;
  }
  return same >= 2;
}

// A header printed again further down with an extra cell ("Page 2 of 2") or
// one more column ("Trailer type") is a header too, not a row: it names at
// least two of the table's columns and every column it names sits where the
// chosen header has it. A data row that merely contains column words ("City |
// State" under "Street address | City") names them in OTHER places and stays
// a row.
function repeatsHeaderLayout(cells, headerMapping, columns) {
  const need = Math.min(2, columns.length);
  const { mapping } = mapHeaders(cells, columns);
  const named = Object.keys(mapping);
  if (named.length < need) return false;
  return named.every((key) => headerMapping[key] === mapping[key]);
}

// What a workbook cell imports into a table column (Z31-X, 21 Oct 2026, and its
// review). Every cell reads as the sheet shows it; a column that needs a NUMBER
// or a DATE reads the value the cell holds wherever the shown text is not it.
//
// A NUMERIC column (currency, count, percent) keeps the shown text only when it
// reads as exactly the number the cell holds ("$1,234.50", "1,200,000", "12.5%"
// over 0.125). Otherwise it takes that number: an accounting zero "$ -", a
// negative "$(1,234.50)", "1.23E+05", "1 1/4" - and a format that rounds or
// scales the number it shows ("#,##0," shows 1250000 as "1,250", "$#,##0"
// shows 1234.56 as "$1,235"), which would otherwise import silently wrong.
// A shown "%" means the cell may hold the fraction (0.125 shown "13%" is 12.5
// percent; a quoted "%" scales nothing): of the number held and that number x
// 100, the one nearer the shown text is the column's number.
//
// A DATE column takes the MM/DD/YYYY a full-date-and-time cell shows, never its
// time ("03/14/2025 1:30 PM" imports 03/14/2025): no table column takes a time.
// A partial date ("Jun-18") stays as shown and is flagged.
//
// A year or text column, and a CSV (no cell values beside its text), are
// unchanged.
const NUMERIC_COLUMN_TYPES = new Set(['currency', 'number', 'percent']);
const ownKey = (obj, key) => !!obj && Object.prototype.hasOwnProperty.call(obj, key);

export function tableCellValue(col, val, cells, idx) {
  if (!val || idx === undefined) return val;
  if (col?.type === 'date') return ownKey(cells?.dates, idx) ? cells.dates[idx] : val;
  if (!NUMERIC_COLUMN_TYPES.has(col?.type) || !ownKey(cells?.stored, idx)) return val;
  const held = Number(cells.stored[idx]);
  if (!Number.isFinite(held)) return val;
  const shown = String(val).replace(/[$,%\s]/g, '');
  const read = NUMERIC_RE.test(shown) ? Number(shown) : null;
  const options = [fullNumberText(held)];
  if (String(val).includes('%')) options.push(fullNumberText(held, 2));
  if (read !== null && options.some((o) => Number(o) === read)) return val;
  if (read === null) return options[options.length - 1];
  return options.reduce((best, o) => (Math.abs(Number(o) - read) < Math.abs(Number(best) - read) ? o : best));
}

// A TOTALS ROW IS NOT A ROW (22 Oct 2026, open since the 21 Oct import work).
// A sheet's "Total" / "Totals" / "Grand total" / "Subtotal" / "Sum" line adds up
// the rows above it; imported, it became a claim, a building or a driver of its
// own in every table. Two conditions, both needed:
//   1. the row's first filled cell (in the sheet, mapped or not) is exactly one
//      of those labels, a colon or full stop allowed - "Total loss of vehicle",
//      "Sum Street" and "Total Cost" are never labels;
//   2. apart from that cell, nothing the row would import names or dates it:
//      every column that is not an amount or a count (currency, number,
//      percent) is empty, or holds no letter or digit ("-"). A driver named
//      "Total" with a date of birth, a licence or a state is a driver.
// A row whose only values beside a lone "Total" are amounts is read as the
// sheet's total - the one shape the two cannot tell apart.
const SUMMARY_LABEL_RE = /^(?:grand\s*totals?|sub[\s-]*totals?|totals?|sum)\s*[:.]?$/i;
const NAMES_SOMETHING_RE = /[\p{L}\p{N}]/u;

export function isSummaryRow(cells, mapping, columns) {
  const list = Array.isArray(cells) ? cells : [];
  const at = list.findIndex((c) => String(c ?? '').trim());
  if (at === -1 || !SUMMARY_LABEL_RE.test(String(list[at]).trim())) return false;
  return (Array.isArray(columns) ? columns : []).every((col) => {
    const idx = mapping ? mapping[col.key] : undefined;
    if (idx === undefined || idx === at || NUMERIC_COLUMN_TYPES.has(col.type)) return true;
    return !NAMES_SOMETHING_RE.test(String(list[idx] ?? ''));
  });
}

/**
 * Turn parsed spreadsheet cells into schedule rows.
 * Falls back to positional column order when no header row is recognised, so a
 * bare list with no headers still imports.
 */
export function rowsFromMatrix(matrix, columns) {
  if (!matrix.length) {
    return {
      rows: [], usedHeader: false, unmatched: [], headerRow: -1, skippedAbove: 0, skippedInside: 0, skippedTotals: 0,
    };
  }

  const headerRow = findHeaderRow(matrix, columns);
  const hasHeader = headerRow !== -1;
  let mapping = {};
  let unmatched = [];

  if (hasHeader) {
    ({ mapping, unmatched } = mapHeaders(matrix[headerRow], columns));
  } else {
    columns.forEach((col, i) => { mapping[col.key] = i; });
  }

  // Rows above the header are its preamble (titles, notes); they are counted so
  // the table can say so - never dropped without a word.
  const skippedAbove = hasHeader
    ? matrix.slice(0, headerRow).filter((cells) => _filledCount(cells)).length
    : 0;

  let skippedInside = 0;
  let dataRows = matrix;
  if (hasHeader) {
    const below = matrix.slice(headerRow + 1);
    const isHeaderAgain = (cells) => repeatsHeader(cells || [], matrix[headerRow])
      || repeatsHeaderLayout(cells || [], mapping, columns);
    const skip = new Set();
    below.forEach((cells, i) => {
      if (!isHeaderAgain(cells)) return;
      skip.add(i);
      // A one-cell row just above a repeated header ("Trailers", "Excluded
      // drivers") is that block's title, not a row.
      let j = i - 1;
      while (j >= 0 && !_filledCount(below[j]) && !skip.has(j)) j -= 1;
      if (j >= 0 && !skip.has(j) && _filledCount(below[j]) === 1) skip.add(j);
    });
    skippedInside = skip.size;
    dataRows = below.filter((_, i) => !skip.has(i));
  }
  // Totals rows (see isSummaryRow), with or without a header: set aside and
  // counted with the rows above (skippedInside), so the message names them.
  const notTotals = dataRows.filter((cells) => !isSummaryRow(cells, mapping, columns));
  const skippedTotals = dataRows.length - notTotals.length;
  skippedInside += skippedTotals;
  dataRows = notTotals;
  const rows = dataRows.slice(0, MAX_ROWS).map((cells) => {
    const row = {};
    columns.forEach((col) => {
      const idx = mapping[col.key];
      let val = idx === undefined ? '' : String(cells[idx] ?? '').trim();
      if (col.type === 'vin' && val) val = normalizeVin(val);
      row[col.key] = tableCellValue(col, val, cells, idx);
    });
    return row;
  });

  return {
    rows: rows.filter((r) => !isBlankRow(r, columns) && !isTemplateExampleRow(r, columns)),
    usedHeader: hasHeader,
    unmatched,
    headerRow,
    skippedAbove,
    skippedInside,
    skippedTotals,
  };
}

/**
 * The import message's note on rows set aside (21 Oct review, H1): the rows
 * above the column headings, headings / block titles printed again further
 * down, and rows of totals (22 Oct 2026 - `skippedTotals`, already counted in
 * `skippedInside`). Empty when nothing was set aside. Starts with a space.
 */
export function skippedRowsText({ skippedAbove = 0, skippedInside = 0, skippedTotals = 0 } = {}) {
  let text = '';
  const totals = Math.max(0, Number(skippedTotals) || 0);
  const headings = Math.max(0, (Number(skippedInside) || 0) - totals);
  if (skippedAbove) {
    text += ` Skipped ${skippedAbove} ${skippedAbove === 1 ? 'row' : 'rows'} above the column headings (titles or notes).`;
  }
  if (headings) {
    text += ` Skipped ${headings} ${headings === 1 ? 'row' : 'rows'} further down that repeat the headings or title a block.`;
  }
  if (totals) {
    text += ` Skipped ${totals} ${totals === 1 ? 'row' : 'rows'} of totals (Total, Subtotal or Sum).`;
  }
  return text;
}

/** Parse any supported file into schedule rows. */
export async function parseScheduleFile(file, columns) {
  const name = (file?.name || '').toLowerCase();
  let matrix;

  if (name.endsWith('.xlsx')) {
    matrix = await parseXLSX(file);
  } else if (name.endsWith('.csv') || name.endsWith('.txt')) {
    matrix = parseCSV(await file.text());
  } else if (name.endsWith('.xls')) {
    // Legacy binary .xls is a different (OLE2) format that jszip cannot read.
    // Say so plainly instead of failing with a confusing zip error.
    throw new Error(
      'This looks like an older .xls file. Please open it and use "Save As" to '
      + 'save it as .xlsx or .csv, then upload again.',
    );
  } else {
    throw new Error('Please upload a .csv or .xlsx file.');
  }

  return rowsFromMatrix(matrix, columns);
}

/** Download a template so an agent's spreadsheet lands in the right columns. */
// The template is the column names only. Its old second line was an example
// row ("789 Commerce Dr, Houston, ...") that an upload imported as a real
// building when nobody deleted it (12 Oct 2026); the hints stay in the table.
export function templateCsv(columns) {
  return `${(columns || []).map((c) => c.label).join(',')}\n`;
}

export function downloadTemplate(columns, label) {
  const blob = new Blob([templateCsv(columns)], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${String(label || 'schedule').toLowerCase().replace(/[^a-z0-9]+/g, '-')}-template.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
