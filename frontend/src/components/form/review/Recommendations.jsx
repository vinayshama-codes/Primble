// Recommendations.jsx - the package page's Recommendations section (Choice
// Electric #22 / #27, 7 Oct 2026). Brent: "All of these Recommendation items
// should be addressable prior to (and independently of) the forms" and "get
// these earlier in the workflow and ensure they are accurate requests".
//
// Two groups (rules and data: utils/recommendations.js):
//   "Raise your score"     - the package scorer's Best Solutions rows a person
//                            can answer, each opening the page's fix window.
//   "Your forms will need" - after forms only: each form's needs-attention
//                            Missing rows with "Open in editor". Before forms
//                            the section is the score only (owner, 14 Oct 2026:
//                            the SQS is independent of the forms).
// Anything already on a Hard Stop / Warning card or a key-details link is not
// repeated. Presentation only: every fix goes through the page's handlers.
// Used by the rail layout (its own section) and the classic layout.

import { useState } from "react";
import useAttentionList from "./useAttentionList";
import {
  buildRecommendations, pointsText, recommendationResolvedRows, liveRecommendationIds, clearedByText,
} from "../../../utils/recommendations";
import { itemsText } from "../../../utils/dryRun";
import { formLabel } from "../../../utils/formInstances";
import { positiveScoreWording } from "../../../utils/positiveWording";
import { screenPoints } from "../../../utils/screenPoints";
import "./Recommendations.css";

const ROWS_SHOWN = 6;

// A group's heading opens and closes it, with the small triangle the Hard Stops
// and Warnings pages use (owner, 13 Oct 2026: "a little drop down icon like
// warnings and hard stops"). `children` is the group's count badge.
function FoldHead({ open, onToggle, title, children }) {
  return (
    <button type="button" className="rec-group__head rec-fold" aria-expanded={open} onClick={onToggle}>
      <span className="rec-tri" aria-hidden="true">▶</span>
      <span className="rec-group__title">{title}</span>
      {children}
    </button>
  );
}

function ScoreGroup({ items, onOpenFix }) {
  const [open, setOpen] = useState(true);
  return (
    <section className="rec-group" aria-label="Raise your score" data-rec-group="score">
      <FoldHead open={open} onToggle={() => setOpen((o) => !o)} title="Raise your score">
        {items.length > 0 && <span className="rec-count">{items.length}</span>}
      </FoldHead>
      {open && (
      <>
      <div className="rec-group__sub">Optional. Each answer adds to your Submission Quality Score.</div>
      {items.length === 0 ? (
        <div className="rec-empty">Nothing to add here. Anything else that moves the score is under Hard Stops or Warnings.</div>
      ) : (
        <div className="rec-list">
          {items.map((it) => (
            <div key={it.id} className="rec-row" data-rec-id={it.id}>
              <div className="rec-row__main">
                <div className="rec-row__title">{it.title}</div>
                {it.detail && <div className="rec-row__detail">{positiveScoreWording(it.detail)}</div>}
                {it.alsoOnForms.length > 0 && (
                  <div className="rec-row__also">Also needed on {it.alsoOnForms.join(", ")}.</div>
                )}
                {it.closesWith === "document" && (
                  <div className="rec-row__also">A supporting document also closes this.</div>
                )}
                {it.heldBy && (
                  <div className="rec-row__also" data-held-by="gate">Adds points once {it.heldBy} is answered.</div>
                )}
              </div>
              <span className="rec-pts">{pointsText(it.points)}</span>
              {typeof onOpenFix === "function" && (
                <button type="button" className="rec-link" onClick={() => onOpenFix(it)}>Open to fix</button>
              )}
            </div>
          ))}
        </div>
      )}
      </>
      )}
    </section>
  );
}
function ReopenIcon() {
  return (
    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 12a9 9 0 1 0 3-6.7" />
      <path d="M3 3v6h6" />
    </svg>
  );
}

// The page's Resolved list (owner, 13 Oct 2026): closed by default, like the
// Hard Stops and Warnings ones. "Open again" takes a fix - and its points -
// back, or unticks an added form (rules: utils/recommendations). A row another
// fix answered says which (14 Oct 2026); its "Open again" takes THAT answer
// back, which brings back every row it cleared. One a key detail cleared has
// no fix on file to take back, so it offers none.
function ResolvedGroup({ rows, onReopen, reopeningIds, reopenNotices }) {
  const [open, setOpen] = useState(false);
  if (!rows.length) return null;
  return (
    <section className="rec-group rec-resolved" aria-label="Resolved" data-rec-group="resolved">
      <FoldHead open={open} onToggle={() => setOpen((o) => !o)} title="Resolved">
        <span className="rec-count rec-count--muted">{rows.length}</span>
      </FoldHead>
      {open && (
        <div className="rec-list">
          {rows.map((r) => {
            const by = r.clearedBy || null;
            const busy = !!reopeningIds?.has?.(r.iid) || !!(by?.iid && reopeningIds?.has?.(by.iid));
            const note = reopenNotices?.get?.(r.iid) || (by?.iid ? reopenNotices?.get?.(by.iid) : null);
            const canReopen = typeof onReopen === "function" && (!by || !!by.iid);
            const title = r.kind === "choice"
              ? `Add ${(r.asked || []).map(formLabel).join(" and ")}`
              : positiveScoreWording(r.title);
            return (
              <div key={r.iid} className="rec-row" data-rec-id={r.iid}>
                <div className="rec-row__main">
                  <div className="rec-row__title">{title}</div>
                  {r.kind === "choice" && r.message && <div className="rec-row__detail">{positiveScoreWording(r.message)}</div>}
                  {by && (
                    <div className="rec-row__detail" data-rec-cleared-by={by.iid || ""}>
                      {positiveScoreWording(clearedByText(by))}
                    </div>
                  )}
                  <div className="rec-resolved__actions">
                    <span className={`rec-resolved__label rec-resolved__label--${r.status}`}>
                      {r.status === "added" ? "Added" : "Resolved"}
                    </span>
                    {canReopen && (
                      <button type="button" className="issue-status-btn rec-resolved__open"
                        disabled={busy} onClick={() => onReopen(r)}>
                        {!busy && <ReopenIcon />}
                        {busy ? "Opening..." : "Open again"}
                      </button>
                    )}
                  </div>
                  {note && <div className="rec-resolved__note">{note}</div>}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

// A form the documents call for that is not in the package ("Your documents now
// show Commercial Auto. ACORD 127 is not in this package.") - the add-document
// answer's offers (`document_form_offers`), listed here too (owner, 14 Oct 2026).
function OffersGroup({ offers, onAddOffer }) {
  const [open, setOpen] = useState(true);
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState("");
  if (!offers.length) return null;
  return (
    <section className="rec-group" aria-label="Forms to add" data-rec-group="offers" data-testid="rec-form-offers">
      <FoldHead open={open} onToggle={() => setOpen((o) => !o)} title="Forms to add">
        <span className="rec-count">{offers.length}</span>
      </FoldHead>
      {open && (
      <>
      <div className="rec-group__sub">Your documents call for these forms. Adding one generates it and re-runs the checks.</div>
      <div className="rec-list">
        {offers.map((o) => (
          <div key={o.form_id} className="rec-row">
            <div className="rec-row__main">
              <div className="rec-row__title">{o.line_label ? `Your documents show ${o.line_label}. ` : ""}{o.label || formLabel(o.form_id)} is not in this package.</div>
              {o.reason && <div className="rec-row__detail">{positiveScoreWording(o.reason)}</div>}
            </div>
            {typeof onAddOffer === "function" && (
              <button type="button" className="rec-link" disabled={!!busy}
                onClick={async () => {
                  setBusy(o.form_id); setErr("");
                  try { await onAddOffer(o); } catch (e) { setErr(e?.message || "The form could not be added."); } finally { setBusy(null); }
                }}>
                {busy === o.form_id ? "Adding..." : `Add ${o.label || formLabel(o.form_id)}`}
              </button>
            )}
          </div>
        ))}
      </div>
      {err && <div className="rec-row__detail" role="alert" style={{ color: "#b91c1c" }}>{err}</div>}
      </>
      )}
    </section>
  );
}

function AfterFormsGroup({ forms, ready, onOpenForm }) {
  const [open, setOpen] = useState({});
  const [groupOpen, setGroupOpen] = useState(true);
  const count = forms.reduce((n, f) => n + f.items.length, 0);
  return (
    <section className="rec-group" aria-label="Your forms will need" data-rec-group="forms">
      <FoldHead open={groupOpen} onToggle={() => setGroupOpen((o) => !o)} title="Your forms will need">
        {count > 0 && <span className="rec-count">{count}</span>}
      </FoldHead>
      {groupOpen && (
      <>
      <div className="rec-group__sub">Boxes still empty on your generated forms. Fill them in the editor.</div>
      {ready === undefined && <div className="rec-empty">Checking your forms...</div>}
      {ready === null && <div className="rec-empty">Your forms could not be checked just now. Open a form to see what it needs.</div>}
      {ready && count === 0 && <div className="rec-empty">Nothing to add - your forms have what they need from you.</div>}
      {ready && forms.map((f) => {
        const all = open[f.form_id];
        const shown = all ? f.items : f.items.slice(0, ROWS_SHOWN);
        return (
          <div key={f.form_id} className="rec-form">
            <div className="rec-form__head">
              <span className="rec-form__name">{f.form_label} {f.items.length > 0 && <small>({itemsText(f.items.length)})</small>}</span>
              {typeof onOpenForm === "function" && (
                <button type="button" className="rec-link" onClick={() => onOpenForm(f.form_id)}>Open in editor</button>
              )}
            </div>
            {shown.map((it) => (
              <div key={it.id} className="rec-row">
                <div className="rec-row__main">
                  <div className="rec-row__title">{it.label}</div>
                  {it.what_to_do && <div className="rec-row__detail">{it.what_to_do}</div>}
                </div>
                {typeof onOpenForm === "function" && (
                  <button type="button" className="rec-link rec-link--muted" onClick={() => onOpenForm(f.form_id, it.field)}>Show on form</button>
                )}
              </div>
            ))}
            {f.items.length > ROWS_SHOWN && (
              <button type="button" className="rec-link rec-link--muted"
                onClick={() => setOpen((o) => ({ ...o, [f.form_id]: !all }))}>
                {all ? "Show fewer" : `Show all ${f.items.length}`}
              </button>
            )}
            {f.toCheck > 0 && (
              <div className="rec-form__check">
                {itemsText(f.toCheck)} to check (AI held back or please verify) - see the form&apos;s side panel.
              </div>
            )}
          </div>
        );
      })}
      </>
      )}
    </section>
  );
}

export default function Recommendations({
  model = null, packageSqs, groupedIssues, keyDetails,
  dryRun, sessionId, tickedFormIds = [], onDryRunUpdate, onOpenDryRunFix,
  onOpenScoreFix, onOpenForm, formsExist = false, generating = false,
  attention, refreshKey = "", heading = false, onAddForm, formOffers = [], onAddOffer,
  // The Resolved list (13 Oct 2026): the stored statuses, "Open again" and its
  // in-flight state - the same ones the Hard Stops / Warnings lists use.
  issueStatuses = null, onReopenResolved, reopeningIds, reopenNotices,
  // What no box on the page can answer, with its points (screenPoints).
  screenUnanswerable = null,
}) {
  // The classic layout passes no list: this section reads it itself.
  const ownAttention = useAttentionList(sessionId, formsExist && attention === undefined && !model, refreshKey);
  const att = attention !== undefined ? attention : ownAttention;
  const rec = model || buildRecommendations({ packageSqs, groupedIssues, keyDetails, dryRun, attention: att, formsExist, tickedFormIds, formOffers });
  const allChoices = Array.isArray(rec.formChoices) ? rec.formChoices : [];
  const keepsResolved = typeof onReopenResolved === "function";
  const resolved = keepsResolved
    ? recommendationResolvedRows({
      statusEntries: issueStatuses?.entries ? Array.from(issueStatuses.entries()) : [],
      liveIds: liveRecommendationIds({ packageSqs, dryRun: formsExist ? null : dryRun }),
      formChoices: allChoices,
    })
    : [];
  // Before forms there is no forms group (owner, 14 Oct 2026): nothing to wait for.
  const offers = Array.isArray(rec.offers) ? rec.offers : [];
  const formsQuiet = formsExist ? rec.formsReady && rec.forms.count === 0 && offers.length === 0 : true;
  // What no box on this page can answer, with its points (15 Oct 2026): the
  // numbers on the page add up to 100 minus the score, this included.
  const unanswerable = formsExist ? [] : (Array.isArray(screenUnanswerable)
    ? screenUnanswerable : screenPoints(packageSqs, groupedIssues, keyDetails).unanswerable);
  const allGood = rec.score.length === 0 && formsQuiet && !generating && unanswerable.length === 0;

  return (
    <div className="rec" data-testid="recommendations">
      {heading && (
        <div>
          <h3 className="rec-heading">Recommendations</h3>
          <p className="rec-heading-sub">{formsExist
            ? "Optional to-dos that raise your score or complete your forms. None of them stops you."
            : "Optional to-dos that raise your score. None of them stops you."}</p>
        </div>
      )}
      {allGood && <div className="rec-empty--good">Nothing to add - your package is in good shape.</div>}
      <div className="rec" hidden={allGood}>
      <ScoreGroup items={rec.score} onOpenFix={onOpenScoreFix} />
      {unanswerable.length > 0 && (
        <div className="rec-group__sub" data-rec-group="unanswerable" style={{ marginTop: 6 }}>
          Not answerable on this page:{" "}
          {unanswerable.map((u) => `${u.label} (${u.points} pts)`).join("; ")}.
        </div>
      )}
      {formsExist && <OffersGroup offers={offers} onAddOffer={onAddOffer} />}
      {formsExist && (
        <AfterFormsGroup forms={rec.forms.forms} ready={att === undefined ? undefined : (att ? true : null)} onOpenForm={onOpenForm} />
      )}
      </div>
      {/* Outside the hidden block: what was handled stays reachable when
          nothing is left to add. */}
      <ResolvedGroup rows={resolved} onReopen={onReopenResolved}
        reopeningIds={reopeningIds} reopenNotices={reopenNotices} />
    </div>
  );
}
