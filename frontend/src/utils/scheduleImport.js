// Spreadsheet import + row validation for bulk schedule capture (Figure 15).
//
// Parsing runs entirely in the browser: the user drops a CSV/XLSX, sees a
// validated preview, fixes what is wrong, and only then are the parsed ROWS
// sent to the server through the existing questionnaire answer channel. No file
// ever leaves the browser, so this needs no upload endpoint, no storage, and no
// virus-scan path.
//
// XLSX is read with `jszip` (already a project dependency) rather than adding a
// spreadsheet library: an .xlsx IS a zip of XML, and we only need the cell text
// of the first sheet.

import JSZip from 'jszip';

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

  switch (col.type) {
    case 'vin':
      if (!isValidVin(val)) return 'VIN must be 17 characters (no I, O or Q)';
      break;
    case 'year':
      if (!YEAR_RE.test(val)) return `${col.label} must be a 4-digit year`;
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

function xmlText(node) {
  return (node?.textContent ?? '').toString();
}

/** Convert an A1-style ref to a zero-based column index ("C" -> 2, "AA" -> 26). */
function colIndexFromRef(ref) {
  const letters = String(ref || '').replace(/[^A-Z]/g, '');
  let n = 0;
  for (let i = 0; i < letters.length; i += 1) n = n * 26 + (letters.charCodeAt(i) - 64);
  return n - 1;
}

export async function parseXLSX(file) {
  const zip = await JSZip.loadAsync(file);

  // Shared strings: most text cells are stored by index into this table.
  const shared = [];
  const sharedFile = zip.file('xl/sharedStrings.xml');
  if (sharedFile) {
    const doc = new DOMParser().parseFromString(await sharedFile.async('string'), 'application/xml');
    doc.querySelectorAll('si').forEach((si) => {
      // <si> may hold one <t> or several <r><t> runs; concatenate all of them.
      const parts = [];
      si.querySelectorAll('t').forEach((t) => parts.push(xmlText(t)));
      shared.push(parts.join(''));
    });
  }

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

  const doc = new DOMParser().parseFromString(
    await zip.file(sheetNames[0]).async('string'), 'application/xml',
  );

  const rows = [];
  doc.querySelectorAll('sheetData > row').forEach((rowEl) => {
    const cells = [];
    rowEl.querySelectorAll('c').forEach((c) => {
      const type = c.getAttribute('t');
      let value;
      if (type === 's') {
        value = shared[parseInt(xmlText(c.querySelector('v')) || '0', 10)] ?? '';
      } else if (type === 'inlineStr') {
        value = xmlText(c.querySelector('is t'));
      } else {
        value = xmlText(c.querySelector('v'));
      }
      const idx = colIndexFromRef(c.getAttribute('r'));
      // Empty cells are omitted from the XML entirely; pad so columns align.
      while (cells.length < idx) cells.push('');
      cells[idx] = String(value ?? '');
    });
    rows.push(cells);
  });

  return rows.filter((r) => r.some((c) => String(c).trim() !== ''));
}

// ---------------------------------------------------------------------------
// Header mapping
// ---------------------------------------------------------------------------

function normalizeHeader(h) {
  return String(h || '').toLowerCase().replace(/[^a-z0-9]/g, '');
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
  license_number: ['licensenumber', 'license', 'licenseno', 'dl', 'dlnumber', 'driverslicense', 'licensenumberidentifier'],
  license_state: ['licensestate', 'state', 'dlstate', 'licensedstate'],
  hire_date: ['hiredate', 'datehired', 'hired'],
  experience_years: ['experienceyears', 'yearsexperience', 'experience', 'yrsexp'],
  address_line1: ['addressline1', 'address', 'streetaddress', 'street', 'addr', 'location'],
  address_city: ['city', 'addresscity', 'town'],
  address_state: ['state', 'addressstate', 'province'],
  address_zip: ['zip', 'zipcode', 'postalcode', 'addresszip', 'postcode'],
  operations_description: ['operations', 'operationsdescription', 'description', 'use', 'occupancy'],
  date: ['date', 'dateofloss', 'lossdate', 'occurrencedate', 'dol'],
  line_of_business: ['line', 'lineofbusiness', 'lob', 'coverage', 'policytype'],
  paid: ['paid', 'amountpaid', 'paidamount', 'losspaid'],
  reserved_amount: ['reserved', 'reserves', 'reservedamount', 'reserve'],
  description: ['description', 'whathappened', 'lossdescription', 'details', 'cause'],
};

/**
 * Map a header row to column keys.
 * Returns { mapping: {colKey: sourceIndex}, unmatched: [headerText] }.
 */
export function mapHeaders(headerRow, columns) {
  const normalized = headerRow.map(normalizeHeader);
  const mapping = {};
  const used = new Set();

  columns.forEach((col) => {
    const candidates = [normalizeHeader(col.key), normalizeHeader(col.label), ...(HEADER_ALIASES[col.key] || [])];
    for (const cand of candidates) {
      const idx = normalized.findIndex((h, i) => h === cand && !used.has(i));
      if (idx !== -1) { mapping[col.key] = idx; used.add(idx); return; }
    }
  });

  const unmatched = headerRow.filter((_, i) => !used.has(i) && String(headerRow[i] || '').trim());
  return { mapping, unmatched };
}

/** True when the first row looks like headers rather than data. */
function looksLikeHeader(row, columns) {
  const { mapping } = mapHeaders(row, columns);
  return Object.keys(mapping).length >= Math.min(2, columns.length);
}

/**
 * Turn parsed spreadsheet cells into schedule rows.
 * Falls back to positional column order when no header row is recognised, so a
 * bare list with no headers still imports.
 */
export function rowsFromMatrix(matrix, columns) {
  if (!matrix.length) return { rows: [], usedHeader: false, unmatched: [] };

  const hasHeader = looksLikeHeader(matrix[0], columns);
  let mapping = {};
  let unmatched = [];

  if (hasHeader) {
    ({ mapping, unmatched } = mapHeaders(matrix[0], columns));
  } else {
    columns.forEach((col, i) => { mapping[col.key] = i; });
  }

  const dataRows = hasHeader ? matrix.slice(1) : matrix;
  const rows = dataRows.slice(0, MAX_ROWS).map((cells) => {
    const row = {};
    columns.forEach((col) => {
      const idx = mapping[col.key];
      let val = idx === undefined ? '' : String(cells[idx] ?? '').trim();
      if (col.type === 'vin' && val) val = normalizeVin(val);
      row[col.key] = val;
    });
    return row;
  });

  return {
    rows: rows.filter((r) => !isBlankRow(r, columns)),
    usedHeader: hasHeader,
    unmatched,
  };
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
export function downloadTemplate(columns, label) {
  const header = columns.map((c) => c.label).join(',');
  const example = columns.map((c) => c.placeholder || '').join(',');
  const blob = new Blob([`${header}\n${example}\n`], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${String(label || 'schedule').toLowerCase().replace(/[^a-z0-9]+/g, '-')}-template.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
