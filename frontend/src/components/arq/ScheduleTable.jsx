// ScheduleTable.jsx - one editable table for ANY repeating ACORD schedule.
//
// Replaces the per-field questionnaire cards that produced "(141th vehicle)"
// (Beta Report Figure 15). Entirely driven by the column spec the server sends
// with the question, so vehicles, drivers, locations and loss runs all render
// through this one component - adding a schedule server-side needs no frontend
// change.
//
// Used by BOTH the client questionnaire and the producer pre-load panel.

import { useCallback, useMemo, useRef, useState } from 'react';
import { API_BASE } from '../../config/constants';
import {
  MAX_ROWS,
  downloadTemplate,
  isBlankRow,
  parseScheduleFile,
  validateRows,
} from '../../utils/scheduleImport';

const PINK = '#E61B84';

function blankRow(columns) {
  const row = {};
  columns.forEach((c) => { row[c.key] = ''; });
  return row;
}

export default function ScheduleTable({
  columns = [],
  rows = [],
  onChange,
  label = 'Schedule',
  singular = 'row',
  dedupKeys = [],
  vinDecode = false,
  rowCapacity = 0,
  compact = false,
}) {
  const fileRef = useRef(null);
  const [importMsg, setImportMsg] = useState(null); // {type, text}
  const [decoding, setDecoding] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  const { errors, duplicates } = useMemo(
    () => validateRows(rows, columns, dedupKeys),
    [rows, columns, dedupKeys],
  );

  const filledCount = useMemo(
    () => rows.filter((r) => !isBlankRow(r, columns)).length,
    [rows, columns],
  );
  const errorCount = Object.keys(errors).length;

  const setRows = useCallback((next) => { onChange?.(next); }, [onChange]);

  const updateCell = (rowIdx, colKey, value) => {
    const next = rows.map((r, i) => (i === rowIdx ? { ...r, [colKey]: value } : r));
    setRows(next);
  };

  const addRow = () => {
    if (rows.length >= MAX_ROWS) return;
    setRows([...rows, blankRow(columns)]);
  };

  const removeRow = (idx) => setRows(rows.filter((_, i) => i !== idx));

  const removeDuplicates = () => {
    setRows(rows.filter((_, i) => !duplicates.has(i)));
    setImportMsg({ type: 'ok', text: `Removed ${duplicates.size} duplicate ${duplicates.size === 1 ? singular : `${singular}s`}.` });
  };

  // ── Spreadsheet import ────────────────────────────────────────────────────
  const handleFile = async (file) => {
    if (!file) return;
    setImportMsg(null);
    try {
      const { rows: parsed, usedHeader, unmatched } = await parseScheduleFile(file, columns);
      if (!parsed.length) {
        setImportMsg({ type: 'err', text: 'No rows found in that file.' });
        return;
      }
      // Append to whatever is already there rather than replacing, so an
      // agent pre-load plus a client addition can coexist. Existing blank
      // rows are dropped first so importing into a fresh table is clean.
      const existing = rows.filter((r) => !isBlankRow(r, columns));
      const merged = [...existing, ...parsed].slice(0, MAX_ROWS);
      setRows(merged);

      let text = `Imported ${parsed.length} ${parsed.length === 1 ? singular : `${singular}s`}.`;
      if (!usedHeader) text += ' No header row was recognised, so columns were matched in order - please check them.';
      if (unmatched.length) text += ` Ignored extra column(s): ${unmatched.slice(0, 4).join(', ')}.`;
      if (existing.length + parsed.length > MAX_ROWS) text += ` Only the first ${MAX_ROWS} were kept.`;
      setImportMsg({ type: usedHeader ? 'ok' : 'warn', text });
    } catch (ex) {
      setImportMsg({ type: 'err', text: ex?.message || 'Could not read that file.' });
    }
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    handleFile(e.dataTransfer?.files?.[0]);
  };

  // ── VIN decoding ──────────────────────────────────────────────────────────
  const decodeVins = async () => {
    const targets = rows
      .map((r, i) => ({ i, vin: String(r.vin || '').trim() }))
      .filter(({ i, vin }) => vin && !errors[i]?.vin);
    if (!targets.length) {
      setImportMsg({ type: 'warn', text: 'Enter at least one valid VIN first.' });
      return;
    }

    setDecoding(true);
    setImportMsg(null);
    try {
      // Chunked to match the server's per-call cap.
      const results = {};
      for (let i = 0; i < targets.length; i += 50) {
        const chunk = targets.slice(i, i + 50);
        const res = await fetch(`${API_BASE}/api/arq/decode-vin`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ vins: chunk.map((t) => t.vin) }),
        });
        const data = await res.json();
        Object.assign(results, data.results || {});
      }

      let filled = 0;
      const next = rows.map((r) => {
        const vin = String(r.vin || '').trim().toUpperCase();
        const d = results[vin];
        if (!d) return r;
        const updated = { ...r };
        // Only fill blanks - never overwrite what the user typed.
        ['year', 'make', 'model', 'body_type'].forEach((k) => {
          if (columns.some((c) => c.key === k) && !String(updated[k] || '').trim() && d[k]) {
            updated[k] = d[k];
            filled += 1;
          }
        });
        return updated;
      });
      setRows(next);
      setImportMsg(
        filled
          ? { type: 'ok', text: `Filled ${filled} detail(s) from ${Object.keys(results).length} VIN(s).` }
          : { type: 'warn', text: 'No new details found for those VINs.' },
      );
    } catch {
      setImportMsg({ type: 'err', text: 'VIN lookup is unavailable right now - you can type the details in.' });
    } finally {
      setDecoding(false);
    }
  };

  // ── Styles ────────────────────────────────────────────────────────────────
  const cellInput = (hasErr) => ({
    width: '100%',
    padding: compact ? '5px 7px' : '7px 9px',
    fontSize: compact ? 12 : 13,
    border: `1px solid ${hasErr ? '#fca5a5' : '#e2e8f0'}`,
    background: hasErr ? '#fff5f5' : '#fff',
    borderRadius: 6,
    outline: 'none',
    fontFamily: 'inherit',
    boxSizing: 'border-box',
  });

  const btn = (primary) => ({
    padding: '7px 13px',
    fontSize: 12,
    fontWeight: 600,
    borderRadius: 7,
    cursor: 'pointer',
    border: primary ? 'none' : '1px solid #cbd5e1',
    background: primary ? PINK : '#fff',
    color: primary ? '#fff' : '#475569',
  });

  const msgStyle = {
    ok:   { bg: '#ecfdf5', border: '#a7f3d0', color: '#065f46' },
    warn: { bg: '#fffbeb', border: '#fde68a', color: '#92400e' },
    err:  { bg: '#fef2f2', border: '#fecaca', color: '#991b1b' },
  };

  const overflow = rowCapacity > 0 && filledCount > rowCapacity;

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={onDrop}
      style={{
        border: `1px ${dragOver ? 'dashed' : 'solid'} ${dragOver ? PINK : '#e2e8f0'}`,
        borderRadius: 10,
        padding: compact ? 10 : 12,
        background: dragOver ? '#fdf2f8' : '#fbfcfe',
      }}
    >
      {/* Toolbar */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 10 }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: '#0f172a' }}>
          {filledCount} {filledCount === 1 ? singular : `${singular}s`}
        </span>
        {errorCount > 0 && (
          <span style={{ fontSize: 11, color: '#b91c1c', fontWeight: 600 }}>
            {errorCount} row{errorCount === 1 ? '' : 's'} need attention
          </span>
        )}
        {duplicates.size > 0 && (
          <button type="button" onClick={removeDuplicates} style={{ ...btn(false), borderColor: '#fbbf24', color: '#92400e' }}>
            Remove {duplicates.size} duplicate{duplicates.size === 1 ? '' : 's'}
          </button>
        )}

        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {vinDecode && (
            <button type="button" onClick={decodeVins} disabled={decoding} style={{ ...btn(false), opacity: decoding ? 0.6 : 1 }}>
              {decoding ? 'Looking up...' : 'Look up VINs'}
            </button>
          )}
          <button type="button" onClick={() => downloadTemplate(columns, label)} style={btn(false)}>
            Template
          </button>
          <button type="button" onClick={() => fileRef.current?.click()} style={btn(false)}>
            Upload CSV / Excel
          </button>
          <button type="button" onClick={addRow} style={btn(true)}>
            + Add {singular}
          </button>
        </div>

        <input
          ref={fileRef}
          type="file"
          accept=".csv,.xlsx,.txt,text/csv"
          onChange={(e) => { handleFile(e.target.files?.[0]); e.target.value = ''; }}
          style={{ display: 'none' }}
        />
      </div>

      {importMsg && (
        <div style={{
          marginBottom: 10, padding: '7px 10px', borderRadius: 6, fontSize: 11.5,
          background: msgStyle[importMsg.type].bg,
          border: `1px solid ${msgStyle[importMsg.type].border}`,
          color: msgStyle[importMsg.type].color,
        }}>
          {importMsg.text}
        </div>
      )}

      {overflow && (
        <div style={{
          marginBottom: 10, padding: '7px 10px', borderRadius: 6, fontSize: 11.5,
          background: '#eff6ff', border: '1px solid #bfdbfe', color: '#1e40af',
        }}>
          This form has room for {rowCapacity} {singular}s. All {filledCount} are saved and sent to
          the underwriter - the extra ones are attached as a separate schedule rather than printed
          on the form.
        </div>
      )}

      {/* Table */}
      {rows.length === 0 ? (
        <div style={{ padding: '18px 12px', textAlign: 'center', color: '#64748b', fontSize: 12.5 }}>
          No {singular}s added yet. Drop a CSV or Excel file here, or use
          {' '}<strong>+ Add {singular}</strong>.
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ borderCollapse: 'separate', borderSpacing: '0 4px', width: '100%', minWidth: 520 }}>
            <thead>
              <tr>
                <th style={{ width: 30, fontSize: 10.5, color: '#94a3b8', fontWeight: 600, textAlign: 'left', padding: '0 4px' }}>#</th>
                {columns.map((c) => (
                  <th key={c.key} style={{
                    fontSize: 10.5, color: '#475569', fontWeight: 700, textAlign: 'left',
                    padding: '0 4px', minWidth: c.width || 120, whiteSpace: 'nowrap',
                  }}>
                    {c.label}{c.required && <span style={{ color: PINK }}> *</span>}
                  </th>
                ))}
                <th style={{ width: 30 }} />
              </tr>
            </thead>
            <tbody>
              {rows.map((row, idx) => {
                const rowErr = errors[idx] || {};
                const isDup = duplicates.has(idx);
                return (
                  <tr key={idx} style={{ background: isDup ? '#fffbeb' : 'transparent' }}>
                    <td style={{ fontSize: 11, color: isDup ? '#b45309' : '#94a3b8', padding: '0 4px', verticalAlign: 'middle' }}>
                      {isDup ? '!' : idx + 1}
                    </td>
                    {columns.map((c) => (
                      <td key={c.key} style={{ padding: '0 4px', verticalAlign: 'top' }}>
                        <input
                          value={row[c.key] ?? ''}
                          onChange={(e) => updateCell(idx, c.key, e.target.value)}
                          placeholder={c.placeholder || ''}
                          title={rowErr[c.key] || ''}
                          style={cellInput(!!rowErr[c.key])}
                        />
                        {rowErr[c.key] && (
                          <div style={{ fontSize: 10, color: '#b91c1c', marginTop: 2 }}>{rowErr[c.key]}</div>
                        )}
                      </td>
                    ))}
                    <td style={{ padding: '0 4px', verticalAlign: 'middle' }}>
                      <button
                        type="button"
                        onClick={() => removeRow(idx)}
                        title={`Remove this ${singular}`}
                        style={{
                          border: 'none', background: 'none', cursor: 'pointer',
                          color: '#94a3b8', fontSize: 16, lineHeight: 1, padding: '2px 4px',
                        }}
                      >
                        ×
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {duplicates.size > 0 && (
        <p style={{ fontSize: 10.5, color: '#92400e', marginTop: 8 }}>
          Rows marked <strong>!</strong> look like duplicates of an earlier row.
        </p>
      )}
    </div>
  );
}
