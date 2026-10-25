// QuestionnairePage.jsx - the review's Questionnaire page (owner, 23 Oct 2026).
//
// The last review page before form selection. It shows the sections the
// backend sends (GET /api/questionnaire/{session_id}), each question
// prefilled from the documents with its state, its source and its actions:
// answer, "Looks right", Unknown, Pending, Not applicable. A save goes through
// POST .../answer; its reply replaces the question and the counts here, and
// AcordModal merges its score and issue lists the way every fix window does
// (`onApplied`). Selected questions go to the client through
// POST .../send-to-client; the carrier narrative is drafted and approved for
// ACORD 101 at the bottom. It never blocks generation.
//
// Rules and copy: utils/questionnaire.js. Used by the rail layout (its own
// page) and the classic layout (`heading`).

import { useEffect, useRef, useState } from "react";
import { API_BASE } from "../../../config/constants";
import ScheduleTable from "../../arq/ScheduleTable";
import {
  QUESTIONNAIRE_TITLE, QUESTIONNAIRE_DESC, SHOW_ONLY_NEEDS, LOOKS_RIGHT, SEND_TO_CLIENT,
  CREATE_NARRATIVE, APPROVE_NARRATIVE,
  stateTag, sectionsOf, visibleQuestions, countsOf, countLine, sourceLines, conflictGroups, optionsOf,
  draftOf, canConfirm, answerBody, insuredConfirmable, questionDomId, narrativeOf, approvedText, replyError,
  isSecureQuestion, isComputed, reloadsPage, clientContact,
} from "../../../utils/questionnaire";
import "./ReviewRailLayout.css";
import "./QuestionnairePage.css";

const OTHER = "Other";

async function postJson(url, body) {
  const res = await fetch(url, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  let data = null;
  try { data = await res.json(); } catch { data = null; }
  return { res, data: data || {} };
}

// The answer box for one question, by its answer_type.
function AnswerInput({ q, draft, setDraft, other, setOther, busy, onSave }) {
  const type = q.answer_type;
  const enter = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSave(); } };
  if (type === "yes_no") {
    return (
      <div className="qn-choices" role="group" aria-label="Yes or No">
        {["Yes", "No"].map((v) => (
          <button key={v} type="button" className={`rr-mini-btn rr-mini-btn--wide${String(draft) === v ? " is-on" : ""}`}
            disabled={busy} onClick={() => onSave(v)}>{v}</button>
        ))}
      </div>
    );
  }
  if (type === "choice") {
    const opts = optionsOf(q);
    const hasOther = opts.some((o) => o.value === OTHER);
    const onList = opts.some((o) => o.value === draft);
    const showOther = other || (hasOther && draft && !onList);
    return (
      <div className="qn-input-row">
        <select className="rr-select qn-select" value={showOther ? OTHER : (onList ? draft : "")} disabled={busy}
          onChange={(e) => {
            const v = e.target.value;
            setOther(v === OTHER);
            setDraft(v === OTHER ? "" : v);
          }}>
          <option value="">Select an answer...</option>
          {draft && !onList && !showOther && <option value={draft}>{draft} (current value)</option>}
          {opts.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        {showOther && (
          <input className="rr-conf__input" value={draft} disabled={busy} placeholder="Type the answer..."
            onChange={(e) => setDraft(e.target.value)} onKeyDown={enter} />
        )}
      </div>
    );
  }
  if (type === "long_text") {
    return (
      <textarea className="rr-conf__input qn-textarea" rows={4} value={draft} disabled={busy}
        placeholder="Type the answer..." onChange={(e) => setDraft(e.target.value)} />
    );
  }
  const placeholder = type === "date" ? "MM/DD/YYYY" : type === "currency" ? "$0" : type === "number" ? "0" : "Type the answer...";
  const inputMode = type === "number" ? "numeric" : type === "currency" ? "decimal" : undefined;
  return (
    <input className="rr-conf__input" value={draft} disabled={busy} placeholder={placeholder} inputMode={inputMode}
      onChange={(e) => setDraft(e.target.value)} onKeyDown={enter} />
  );
}

// `card`: the explanation card a deep link opened this row from ({ code,
// issue_id }), sent with its answer; null otherwise.
function QuestionRow({ q, sessionId, lockedText, highlighted, selected, onSelect, onSaved, card = null }) {
  const [draft, setDraft] = useState(() => draftOf(q));
  const [other, setOther] = useState(false);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(null);       // the action being saved
  const [err, setErr] = useState("");
  // The table's rows when its editor opened: a save is refused once the server
  // holds other rows (another view of the same table was saved since).
  const tableBase = useRef(null);
  const tag = stateTag(q.state);
  const sources = sourceLines(q);
  const conflicts = q.state === "conflicting" ? conflictGroups(q) : [];
  const secure = isSecureQuestion(q);
  const computed = isComputed(q);
  const isTable = q.answer_type === "table";
  const hasValue = String(q.display_value ?? "").trim() !== "";
  // A question with nothing on file opens on its box; one with a value opens on
  // the value, with "Change" to type over it. A computed one is read-only.
  const open = !computed && (editing || (!hasValue && q.needs_input === true && !isTable));
  const locked = !!lockedText;

  const startEdit = () => {
    const rows = draftOf(q);
    tableBase.current = isTable ? JSON.stringify(rows) : null;
    setDraft(rows);
    setEditing(true);
    setErr("");
  };

  const save = async (action, value, choice = null) => {
    if (busy || locked) return;
    if (isTable && action === "answer" && tableBase.current !== null
        && JSON.stringify(draftOf(q)) !== tableBase.current) {
      tableBase.current = JSON.stringify(draftOf(q));
      setDraft(draftOf(q));
      setErr("This table was changed by another answer. Here are its current rows - check them and save again.");
      return;
    }
    const body = answerBody(q, action, value, { card, choice });
    if (!body) { setErr("Type an answer first."); return; }
    setBusy(action);
    setErr("");
    try {
      const { res, data } = await postJson(`${API_BASE}/api/questionnaire/${sessionId}/answer`, body);
      if (!res.ok || data.ok === false || !data.question) {
        setErr(replyError(data));
        return;
      }
      setEditing(false);
      setOther(false);
      tableBase.current = null;
      setDraft(draftOf(data.question));
      onSaved(data, data.question, card && (body.code || body.issue_id) ? card : null);
    } catch {
      setErr("Could not reach the server. Try again.");
    } finally {
      setBusy(null);
    }
  };

  const saveTyped = (v) => save("answer", v === undefined ? draft : v);

  return (
    <div id={questionDomId(q.id)} className={`qn-row${highlighted ? " is-highlight" : ""}`} data-question-id={q.id}
      data-fact={q.fact || undefined}>
      <div className="qn-row__head">
        <div className="qn-row__text">
          {q.text}
          {q.critical && <span className="qn-critical">Key detail</span>}
        </div>
        {tag && (
          <span className={`qn-tag qn-tag--${tag.tone}`}>{tag.text}{tag.by ? ` ${tag.by}` : ""}</span>
        )}
      </div>
      {q.help && <div className="qn-row__help">{q.help}</div>}

      {conflicts.length > 0 ? (
        <div className="qn-conflicts">
          {conflicts.map((c) => (
            <div key={`${c.choice}|${c.value}`} className="qn-conflict">
              <span className="qn-value">{c.value}</span>
              {c.documents.length > 0 && <span className="qn-source">{c.documents.join("; ")}</span>}
              {!computed && (
                <button type="button" className="rr-mini-btn" disabled={!!busy || locked}
                  onClick={() => (secure ? save("answer", undefined, c.choice) : save("answer", c.value))}>
                  Use this
                </button>
              )}
            </div>
          ))}
        </div>
      ) : hasValue ? (
        <div className="qn-value">{q.display_value}</div>
      ) : null}
      {sources.length > 0 && <div className="qn-source">From {sources.join("; ")}</div>}

      {open && !isTable && (
        <div className="qn-edit">
          <AnswerInput q={q} draft={draft} setDraft={setDraft} other={other} setOther={setOther}
            busy={!!busy || locked} onSave={saveTyped} />
          {q.answer_type !== "yes_no" && (
            <button type="button" className="rr-conf__btn" disabled={!!busy || locked || !String(draft).trim()}
              onClick={() => saveTyped()}>
              {busy === "answer" ? "Saving..." : "Save"}
            </button>
          )}
          {editing && (
            <button type="button" className="rr-mini-btn" disabled={!!busy}
              onClick={() => { setEditing(false); setOther(false); setDraft(draftOf(q)); setErr(""); }}>
              Cancel
            </button>
          )}
        </div>
      )}
      {isTable && editing && (
        <div className="qn-table">
          <ScheduleTable
            columns={Array.isArray(q.table?.columns) ? q.table.columns : []}
            rows={Array.isArray(draft) ? draft : []}
            onChange={setDraft}
            label={q.table?.schedule_label || q.table?.label || "Table"}
            singular={q.table?.schedule_singular || q.table?.singular || "row"}
            dedupKeys={q.table?.dedup_keys || []}
            vinDecode={!!q.table?.vin_decode}
            rowCapacity={q.table?.row_capacity || 0}
            compact
            followUp={q.table?.follow_up === true}
          />
          <div className="qn-edit">
            <button type="button" className="rr-conf__btn" disabled={!!busy || locked} onClick={() => save("answer", draft)}>
              {busy === "answer" ? "Saving..." : "Save table"}
            </button>
            <button type="button" className="rr-mini-btn" disabled={!!busy}
              onClick={() => { setEditing(false); tableBase.current = null; setDraft(draftOf(q)); setErr(""); }}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {!computed && (
      <div className="qn-actions">
        {!open && !(isTable && editing) && (
          <button type="button" className="rr-mini-btn" disabled={!!busy || locked} onClick={startEdit}>
            {isTable ? "Edit table" : hasValue ? "Change" : "Answer"}
          </button>
        )}
        {canConfirm(q) && (
          <button type="button" className="rr-mini-btn" disabled={!!busy || locked} onClick={() => save("confirm")}>
            {busy === "confirm" ? "Saving..." : LOOKS_RIGHT}
          </button>
        )}
        {q.state !== "unknown" && (
          <button type="button" className="rr-mini-btn" disabled={!!busy || locked} onClick={() => save("unknown")}>
            {busy === "unknown" ? "Saving..." : "Unknown"}
          </button>
        )}
        {q.state !== "pending" && (
          <button type="button" className="rr-mini-btn" disabled={!!busy || locked} onClick={() => save("pending")}>
            {busy === "pending" ? "Saving..." : "Pending"}
          </button>
        )}
        {q.state !== "not_applicable" && (
          <button type="button" className="rr-mini-btn" disabled={!!busy || locked} onClick={() => save("not_applicable")}>
            {busy === "not_applicable" ? "Saving..." : "Not applicable"}
          </button>
        )}
        {q.insured_confirmable === true && (
          <label className="qn-ask">
            <input type="checkbox" checked={!!selected} onChange={(e) => onSelect(q.id, e.target.checked)} />
            Ask the client
          </label>
        )}
        {busy && <span className="rr-busy">Saving...</span>}
      </div>
      )}
      {err && <div className="qn-error" role="alert">{err}</div>}
    </div>
  );
}

function SendToClient({ sessionId, model, selected, setSelected, lockedText }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);   // { link } | { error }
  const [copied, setCopied] = useState(false);
  // Typed over the contact on file (A.1f / A.1d); null = the one on file.
  const [email, setEmail] = useState(null);
  const [name, setName] = useState(null);
  const askable = insuredConfirmable(model);
  if (!askable.length) return null;
  const ids = askable.map((q) => q.id).filter((id) => selected.has(id));
  const onFile = clientContact(model);
  const toEmail = (email ?? onFile.email).trim();
  const toName = (name ?? onFile.name).trim();

  const send = async () => {
    if (busy || !ids.length || !toEmail) return;
    setBusy(true);
    setResult(null);
    setCopied(false);
    try {
      const { res, data } = await postJson(`${API_BASE}/api/questionnaire/${sessionId}/send-to-client`,
        { question_ids: ids, client_email: toEmail, client_name: toName });
      if (!res.ok || data.ok === false) setResult({ error: replyError(data, "Could not send. Try again.") });
      else setResult({ link: data.link || "" });
    } catch {
      setResult({ error: "Could not reach the server. Try again." });
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    try { await navigator.clipboard.writeText(result.link); setCopied(true); } catch { setCopied(false); }
  };

  return (
    <section className="rr-panel">
      <div className="rr-panel__body qn-send">
        <div className="qn-send__text">
          <div className="rr-panel__title">{SEND_TO_CLIENT}</div>
          <div className="rr-panel__meta">
            {ids.length ? `${ids.length} of ${askable.length} selected. The client gets a link to confirm them.`
              : `Tick "Ask the client" on the questions the client should confirm (${askable.length} can be asked).`}
          </div>
        </div>
        <div className="qn-send__to">
          <input className="rr-conf__input" type="email" value={email ?? onFile.email} disabled={busy}
            placeholder="Client e-mail" aria-label="Client e-mail" onChange={(e) => setEmail(e.target.value)} />
          <input className="rr-conf__input" value={name ?? onFile.name} disabled={busy}
            placeholder="Client name" aria-label="Client name" onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="qn-send__actions">
          <button type="button" className="rr-mini-btn" disabled={busy}
            onClick={() => setSelected(ids.length === askable.length ? new Set() : new Set(askable.map((q) => q.id)))}>
            {ids.length === askable.length ? "Clear all" : "Select all"}
          </button>
          <button type="button" className="rr-conf__btn" disabled={busy || !ids.length || !toEmail || !!lockedText}
            onClick={send}>
            {busy ? "Sending..." : SEND_TO_CLIENT}
          </button>
        </div>
        {result?.error && <div className="qn-error" role="alert">{result.error}</div>}
        {result && !result.error && (
          <div className="qn-sent">
            <span>Sent.</span>
            {result.link && <a href={result.link} target="_blank" rel="noreferrer" className="qn-link">{result.link}</a>}
            {result.link && (
              <button type="button" className="rr-mini-btn" onClick={copy}>{copied ? "Copied" : "Copy link"}</button>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

function NarrativeBox({ sessionId, model, onNarrative, lockedText }) {
  const stored = narrativeOf(model);
  const [text, setText] = useState(stored.text);
  const [busy, setBusy] = useState(null);       // "draft" | "approve"
  const [err, setErr] = useState("");
  // A reload that brings a different stored text takes it, unless one is being typed.
  const lastStored = useRef(stored.text);
  useEffect(() => {
    if (stored.text !== lastStored.current) {
      const typedOver = text !== lastStored.current;
      lastStored.current = stored.text;
      if (!typedOver) setTimeout(() => setText(stored.text), 0);
    }
  }, [stored.text, text]);

  const draft = async () => {
    if (busy) return;
    setBusy("draft");
    setErr("");
    try {
      const { res, data } = await postJson(`${API_BASE}/api/questionnaire/${sessionId}/narrative/draft`, {});
      if (!res.ok || data.ok === false) { setErr(replyError(data, "Could not create the narrative. Try again.")); return; }
      const t = typeof data.text === "string" ? data.text : "";
      lastStored.current = t;
      setText(t);
      onNarrative({ state: "draft", text: t, approved_at: null });
    } catch {
      setErr("Could not reach the server. Try again.");
    } finally {
      setBusy(null);
    }
  };

  const approve = async () => {
    if (busy || !text.trim()) return;
    setBusy("approve");
    setErr("");
    try {
      const { res, data } = await postJson(`${API_BASE}/api/questionnaire/${sessionId}/narrative/approve`, { text });
      if (!res.ok || data.ok === false) { setErr(replyError(data, "Could not approve. Try again.")); return; }
      const n = data.narrative && typeof data.narrative === "object"
        ? data.narrative : { state: "approved", text, approved_at: new Date().toISOString() };
      const approved = typeof n.text === "string" ? n.text : text;
      lastStored.current = approved;
      setText(approved);
      onNarrative({ ...n, text: approved });
    } catch {
      setErr("Could not reach the server. Try again.");
    } finally {
      setBusy(null);
    }
  };

  const approvedNow = stored.state === "approved" && text.trim() === stored.text.trim();
  const hasText = stored.state !== "none" || text.trim() !== "";
  return (
    <section className="rr-panel" data-testid="carrier-narrative">
      <div className="rr-panel__head">
        <div className="rr-panel__head-text">
          <div className="rr-panel__title">Carrier narrative</div>
          <div className="rr-panel__meta">Written from your answers and documents. Edit it, then approve it for ACORD 101.</div>
        </div>
        {approvedNow && <span className="rr-badge rr-badge--green">{approvedText(stored.approved_at)}</span>}
      </div>
      <div className="rr-panel__body">
        {hasText && (
          <textarea className="rr-conf__input qn-textarea qn-narrative" rows={8} value={text} disabled={!!busy}
            onChange={(e) => setText(e.target.value)} aria-label="Carrier narrative" />
        )}
        <div className="qn-edit">
          <button type="button" className={hasText ? "rr-mini-btn" : "rr-conf__btn"} disabled={!!busy || !!lockedText} onClick={draft}>
            {busy === "draft" ? "Creating..." : hasText ? "Create again" : CREATE_NARRATIVE}
          </button>
          {hasText && (
            <button type="button" className="rr-conf__btn" disabled={!!busy || !!lockedText || !text.trim() || approvedNow}
              onClick={approve}>
              {busy === "approve" ? "Approving..." : approvedNow ? "Approved" : APPROVE_NARRATIVE}
            </button>
          )}
          {stored.state === "approved" && !approvedNow && (
            <span className="qn-source">Edited since it was approved. Approve again to use this text.</span>
          )}
        </div>
        {err && <div className="qn-error" role="alert">{err}</div>}
      </div>
    </section>
  );
}

export default function QuestionnairePage({
  sessionId, model, error, onReload, active = true, focus = null,
  onAnswered, onApplied, onNarrative, lockedText = null, heading = false,
}) {
  const [onlyNeeds, setOnlyNeeds] = useState(true);
  const [folds, setFolds] = useState({});
  const [keep, setKeep] = useState(() => new Set());     // rows kept on screen under the filter
  const [highlight, setHighlight] = useState(null);
  const [selected, setSelected] = useState(() => new Set());
  const [spentFocus, setSpentFocus] = useState(null);
  const handledFocus = useRef(null);

  // A deep link (a narrative card's "Open to fix"): open its section, keep its
  // row on screen under the filter, scroll to it and mark it for a moment.
  const focusNonce = focus?.nonce ?? null;
  const focusQid = focus?.questionId || null;
  const focusSid = focus?.sectionId || null;
  // The explanation card the deep link came from: its code and id ride on the
  // focused question's answer.
  const focusCard = focus && (focus.code || focus.issue_id) ? { code: focus.code || null, issue_id: focus.issue_id || null } : null;
  const loaded = !!model;
  useEffect(() => {
    if (!active || !loaded || !focusQid || handledFocus.current === focusNonce) return undefined;
    handledFocus.current = focusNonce;
    const qid = focusQid;
    const sid = focusSid;
    const t0 = setTimeout(() => {
      if (sid) setFolds((f) => ({ ...f, [sid]: true }));
      setKeep((k) => new Set(k).add(qid));
      setHighlight(qid);
    }, 0);
    const t1 = setTimeout(() => {
      const el = document.getElementById(questionDomId(qid));
      if (el && el.scrollIntoView) el.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 90);
    const t2 = setTimeout(() => setHighlight((h) => (h === qid ? null : h)), 2600);
    return () => { clearTimeout(t0); clearTimeout(t1); clearTimeout(t2); };
  }, [active, loaded, focusNonce, focusQid, focusSid]);

  const head = heading && (
    <div className="qn-heading">
      <h3 className="rec-heading">{QUESTIONNAIRE_TITLE}</h3>
      <p className="rec-heading-sub">{QUESTIONNAIRE_DESC}</p>
    </div>
  );

  if (!model) {
    return (
      <div className="rr-stack">
        {head}
        <section className="rr-panel">
          <div className="rr-doc-empty">
            {error ? (
              <>Could not load the questionnaire. <button type="button" className="rec-link" onClick={onReload}>Try again</button></>
            ) : "Loading the questionnaire..."}
          </div>
        </section>
      </div>
    );
  }

  const sections = sectionsOf(model);
  const counts = countsOf(model);
  const shown = sections.reduce((n, s) => n + visibleQuestions(s, onlyNeeds, keep).length, 0);
  const onSaved = (data, question, card) => {
    // A saved row stays on screen until the page is left, even once it no
    // longer needs input.
    setKeep((k) => new Set(k).add(question.id));
    onAnswered(question, data.counts);
    // A table answer re-reads the page: the other views of that table change too.
    if (reloadsPage(question) && onReload) onReload();
    // The card's code and id go with one answer only.
    if (card) setSpentFocus(focusNonce);
    if (onApplied) onApplied(data, question, card);
  };
  const select = (id, on) => setSelected((s) => {
    const n = new Set(s);
    if (on) n.add(id); else n.delete(id);
    return n;
  });

  return (
    <div className="rr-stack">
      {head}
      <div className="qn-filter">
        <label className="qn-toggle">
          <input type="checkbox" checked={onlyNeeds} onChange={(e) => setOnlyNeeds(e.target.checked)} />
          {SHOW_ONLY_NEEDS}
        </label>
        <span className="qn-count">{countLine(counts)}</span>
      </div>
      {lockedText && <div className="rr-note rr-note--amber">{lockedText}</div>}

      {sections.length === 0 && (
        <section className="rr-panel"><div className="rr-doc-empty">No questions for this package.</div></section>
      )}
      {sections.map((s) => {
        const rows = visibleQuestions(s, onlyNeeds, keep);
        const needs = s.questions.filter((q) => q.needs_input === true).length;
        if (onlyNeeds && !rows.length) return null;
        const open = Object.prototype.hasOwnProperty.call(folds, s.id) ? folds[s.id] : true;
        return (
          <section key={s.id} className="rr-panel" data-section-id={s.id}>
            <button type="button" className="rr-panel__head rr-panel__head--button" aria-expanded={open}
              onClick={() => setFolds((f) => ({ ...f, [s.id]: !open }))}>
              <span className="rr-tri" aria-hidden="true">▶</span>
              <span className="rr-panel__head-text">
                <span className="rr-panel__title">{s.title}</span>
                <span className="rr-panel__meta">
                  {needs > 0 ? `${needs} of ${s.questions.length} need${needs === 1 ? "s" : ""} you` : `${s.questions.length} answered or confirmed`}
                </span>
              </span>
              {needs > 0 && <span className="rr-count">{needs}</span>}
            </button>
            {open && (
              <div className="rr-rows">
                {rows.map((q) => (
                  <QuestionRow key={q.id} q={q} sessionId={sessionId} lockedText={lockedText}
                    highlighted={highlight === q.id} selected={selected.has(q.id)} onSelect={select}
                    onSaved={onSaved} card={q.id === focusQid && focusNonce !== spentFocus ? focusCard : null} />
                ))}
                {!rows.length && <div className="rr-doc-empty">Nothing here needs you.</div>}
              </div>
            )}
          </section>
        );
      })}
      {onlyNeeds && counts.total > 0 && shown === 0 && (
        <section className="rr-panel">
          <div className="rr-doc-empty">Nothing needs you. Untick the filter to see every answer.</div>
        </section>
      )}

      <SendToClient sessionId={sessionId} model={model} selected={selected} setSelected={setSelected} lockedText={lockedText} />
      <NarrativeBox sessionId={sessionId} model={model} onNarrative={onNarrative} lockedText={lockedText} />
    </div>
  );
}
