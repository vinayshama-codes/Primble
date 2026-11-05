// AcordFormSearch.jsx - search ACORD's full form library on the form selection screen (3 Nov 2026,
// Accommodate800forms.md section 10). The recommended forms stay as they are; while the user searches,
// only the matching forms show, in the same card style. Ticked results are added with "Done" and then
// sit at the bottom of the list under their own heading (the parent renders that section).
//
// Searching never calls ACORD Solutions: the backend searches its own list. The form itself is fetched
// from ACORD Solutions only when the package is generated.
//
// Ticks are kept across searches (search "27", tick, search "137 tx", tick, Done adds BOTH) and also when the
// box is cleared (final review: clearing used to drop them silently) - they wait, listed, until Done or until
// the user unticks them. A tick counts only once Done is pressed; the parent keeps Generate off meanwhile.
import { useEffect, useRef, useState } from "react";
import { API_BASE } from "../../config/constants";

export default function AcordFormSearch({
  query, onQueryChange, onPendingChange, maxForms, maxTotal = 15, addedForms, checkedFormIds, onDone,
  companionsOf = () => [],
}) {
  const [results, setResults] = useState([]);
  const [total, setTotal] = useState(0);             // how many matched (the list shows the first 25)
  const [widened, setWidened] = useState("");        // the server widened the search ("No Texas version found ...")
  const [shownFor, setShownFor] = useState("");      // the search the results on screen answer
  const [failed, setFailed] = useState(false);       // that search could not be run (not "no match")
  const [attempt, setAttempt] = useState(0);         // "Try again" re-runs the same search
  const [picks, setPicks] = useState(() => new Map()); // form id -> result row, across searches
  const [note, setNote] = useState("");
  const seq = useRef(0);
  const q = query.trim();
  const active = q.length > 0;
  const searching = active && shownFor !== q;

  useEffect(() => {
    if (!active) {
      seq.current += 1;                                 // a reply still on its way is ignored
      setResults([]); setTotal(0); setWidened(""); setShownFor(""); setFailed(false); setNote("");
      return undefined;
    }
    const mine = ++seq.current;
    const t = setTimeout(async () => {
      let rows = [];
      let count = 0;
      let said = "";
      let ok = true;
      try {
        const res = await fetch(`${API_BASE}/api/asg-forms/search?q=${encodeURIComponent(q)}`,
                                { credentials: "include" });
        ok = res.ok;
        const data = res.ok ? await res.json() : { results: [] };
        rows = data.results || [];
        count = Number(data.total) || rows.length;
        said = typeof data.note === "string" ? data.note : "";
      } catch {
        ok = false;
        rows = [];
      }
      if (mine === seq.current) { setResults(rows); setTotal(count); setWidened(said); setFailed(!ok); setShownFor(q); }
    }, 250);
    return () => clearTimeout(t);
  }, [q, active, attempt]);

  // ASG forms already on the package's list (ticked or not) plus the ones ticked here count against the cap;
  // "Remove" on an added form frees its place.
  const asgListed = addedForms.filter(f => f.source === "asg").length;
  // A pick that is already on the list (added, then unticked) takes no second place.
  const listedIds = new Set(addedForms.map(f => f.form_id));
  const asgPicked = [...picks.values()].filter(r => r.source === "asg" && !listedIds.has(r.form_id)).length;

  useEffect(() => { if (onPendingChange) onPendingChange(picks.size); }, [picks, onPendingChange]);

  const togglePick = (r) => {
    if (r.available === false) return;                // ACORD Solutions refused it before: never asked again
    if (picks.has(r.form_id)) {
      const next = new Map(picks); next.delete(r.form_id); setPicks(next); setNote("");
      return;
    }
    if (r.source === "asg" && !listedIds.has(r.form_id) && asgListed + asgPicked >= maxForms) {
      setNote(`You can add up to ${maxForms} extra ACORD forms to one package - remove one to add another.`);
      return;
    }
    // Every form in one package, ours and ACORD Solutions' together (Brent, 4 Nov 2026).
    // Forms a pick brings with it (ACORD 127's state auto forms) count too (review pass 4).
    const inPackage = new Set([...(checkedFormIds || []), ...picks.keys(),
      ...[...picks.values()].flatMap(p => companionsOf(p))]);
    const adds = [r.form_id, ...companionsOf(r)].filter(id => !inPackage.has(id));
    if (adds.length && inPackage.size + adds.length > maxTotal) {
      setNote(`A package can hold up to ${maxTotal} forms. Untick one, or contact support@primble.com to upgrade your account.`);
      return;
    }
    const next = new Map(picks); next.set(r.form_id, r); setPicks(next); setNote("");
  };

  const done = () => {
    onDone([...picks.values()]);
    setPicks(new Map());
    setNote("");
    onQueryChange("");
  };

  return (
    <div className="acord-form-search">
      <div className="acord-form-search-notice">
        <strong>Need another ACORD form?</strong> Search ACORD's full form library by form number or name
        (for example "27" or "binder") and add it to this package. It is filled from your submission just
        like the forms below.
      </div>
      <div className="acord-form-search-bar">
        {/* Our own X, always shown while something is typed (the browser's own clear button shows only on hover in
            Chrome and not at all in Firefox): it clears the search and brings back the forms and the buttons (owner,
            live test 3 Nov 2026). Esc does the same. Ticks not yet added with Done stay listed below. */}
        <div className="acord-form-search-field">
          <input
            type="search"
            className="acord-form-search-input"
            placeholder="Search ACORD forms by number or name"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Escape" && query) { e.preventDefault(); onQueryChange(""); } }}
            aria-label="Search ACORD forms by number or name"
            maxLength={80}
          />
          {query && (
            <button type="button" className="acord-form-search-clear" onClick={() => onQueryChange("")}
                    aria-label="Clear the search and go back to your forms" title="Clear the search">
              ×
            </button>
          )}
        </div>
        {(active || picks.size > 0) && (
          <button type="button" className="btn btn-modal-primary acord-form-search-done" onClick={done}>
            Done{picks.size > 0 ? ` (${picks.size})` : ""}
          </button>
        )}
      </div>
      <div className="acord-form-search-note" aria-live="polite">{note}</div>
      {!active && picks.size > 0 && (
        <div className="acord-form-search-pending" aria-live="polite">
          Ticked, not added yet: {[...picks.values()].map(r => r.label).join(", ")}. Press Done to add {picks.size === 1 ? "it" : "them"}.{" "}
          <button type="button" className="acord-search-retry" onClick={() => { setPicks(new Map()); setNote(""); }}>
            Untick all
          </button>
        </div>
      )}
      {active && (
        <div className="form-selection-list acord-form-search-results">
          <div className="form-selection-header">
            <span className="form-selection-title">Search results</span>
            {!(failed && !searching) && (
              <span className="form-selection-hint" aria-live="polite">
                {searching ? "Searching..." : total > results.length
                  ? `Showing ${results.length} of ${total} - add a state or more words to narrow it`
                  : `${results.length} found`}
              </span>
            )}
          </div>
          {!searching && failed && (
            <div className="acord-form-search-empty">
              Search is not available right now.{" "}
              <button type="button" className="acord-search-retry"
                      onClick={() => { setShownFor(""); setAttempt(n => n + 1); }}>
                Try again
              </button>
            </div>
          )}
          {!searching && !failed && results.length === 0 && (
            <div className="acord-form-search-empty">No ACORD form matches "{q}". Try the form number.</div>
          )}
          {!searching && !failed && results.length > 0 && widened && (
            <div className="acord-form-search-empty">{widened}</div>
          )}
          {!searching && results.map(r => {
            const selected = checkedFormIds.has(r.form_id);
            const ticked = selected || picks.has(r.form_id);
            const unavailable = r.available === false && !selected;
            return (
              <div key={r.form_id} className={`form-select-row ${ticked ? "form-row-checked" : ""} ${unavailable ? "form-row-unavailable" : ""}`}>
                <label className="form-select-checkbox-label">
                  <input
                    type="checkbox"
                    className="form-select-checkbox"
                    checked={ticked}
                    disabled={selected || unavailable}
                    onChange={() => togglePick(r)}
                  />
                  <div className="form-select-info">
                    <div className="form-select-name">{r.form_name}</div>
                    <div className="form-select-meta">
                      {r.ours
                        ? <span className="form-select-reason">Primble form</span>
                        : <span className="form-select-reason">From ACORD Solutions - fetched when you generate</span>}
                      {!r.ours && r.listed_edition && <span className="form-select-reason">Edition {r.listed_edition}</span>}
                      {r.variant && <span className="form-select-reason">Variant "{r.variant}"</span>}
                      {!r.pc && <span className="form-select-reason">Life / health / annuity form</span>}
                      {selected && <span className="form-select-reason">Already selected</span>}
                      {unavailable && <span className="form-select-reason form-select-unavailable">{r.unavailable_reason || "Not available from ACORD Solutions - choose another form."}</span>}
                    </div>
                  </div>
                </label>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
