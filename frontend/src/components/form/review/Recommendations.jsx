// Recommendations.jsx - the package page's Recommendations section (Choice
// Electric #22 / #27, 7 Oct 2026). Brent: "All of these Recommendation items
// should be addressable prior to (and independently of) the forms" and "get
// these earlier in the workflow and ensure they are accurate requests".
//
// Two groups (rules and data: utils/recommendations.js):
//   "Raise your score"     - the package scorer's Best Solutions rows a person
//                            can answer, each opening the page's fix window.
//   "Your forms will need" - before forms, the "Before you generate" dry run
//                            (BeforeYouGenerate, unchanged behaviour: polling,
//                            cache, re-check on ticks); after forms, each
//                            form's needs-attention Missing rows with "Open in
//                            editor".
// Anything already on a Hard Stop / Warning card or a key-details link is not
// repeated. Presentation only: every fix goes through the page's handlers.
// Used by the rail layout (its own section) and the classic layout.

import { useState } from "react";
import BeforeYouGenerate from "./BeforeYouGenerate";
import useAttentionList from "./useAttentionList";
import {
  buildRecommendations, pointsText, recommendationResolvedRows, liveRecommendationIds,
} from "../../../utils/recommendations";
import { itemsText } from "../../../utils/dryRun";
import { formLabel } from "../../../utils/formInstances";
import { positiveScoreWording } from "../../../utils/positiveWording";
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

// Before forms: a check whose only fix is choosing a form (13 Oct 2026). Not in
// the score - "Add" ticks the form in Select forms; a ticked one says so, or -
// where the page keeps a Resolved list - moves there as "Added".
function FormChoices({ choices, onAddForm }) {
  if (!choices.length) return null;
  return (
    <div className="rec-list" data-rec-group="form-choices">
      {choices.map((c) => (
        <div key={c.id} className="rec-row" data-rec-id={c.id}>
          <div className="rec-row__main">
            <div className="rec-row__title">Add {c.asked.map(formLabel).join(" and ")}</div>
            {c.message && <div className="rec-row__detail">{c.message}</div>}
            {c.done && <div className="rec-row__also">Ticked in Select forms.</div>}
          </div>
          {!c.done && typeof onAddForm === "function" && c.forms.map((f) => (
            <button key={f} type="button" className="rec-link" onClick={() => onAddForm(f)}>Add {formLabel(f)}</button>
          ))}
        </div>
      ))}
    </div>
  );
}

// A turn-back arrow for "Open again" (the row returns to its list) - the Hard
// Stops / Warnings Resolved lists' icon.
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
// back, or unticks an added form (rules: utils/recommendations).
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
            const busy = !!reopeningIds?.has?.(r.iid);
            const note = reopenNotices?.get?.(r.iid);
            const title = r.kind === "choice"
              ? `Add ${(r.asked || []).map(formLabel).join(" and ")}`
              : positiveScoreWording(r.title);
            return (
              <div key={r.iid} className="rec-row" data-rec-id={r.iid}>
                <div className="rec-row__main">
                  <div className="rec-row__title">{title}</div>
                  {r.kind === "choice" && r.message && <div className="rec-row__detail">{positiveScoreWording(r.message)}</div>}
                  <div className="rec-resolved__actions">
                    <span className={`rec-resolved__label rec-resolved__label--${r.status}`}>
                      {r.status === "added" ? "Added" : "Resolved"}
                    </span>
                    {typeof onReopen === "function" && (
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
  attention, refreshKey = "", heading = false, onAddForm,
  // The Resolved list (13 Oct 2026): the stored statuses, "Open again" and its
  // in-flight state - the same ones the Hard Stops / Warnings lists use.
  issueStatuses = null, onReopenResolved, reopeningIds, reopenNotices,
}) {
  // The classic layout passes no list: this section reads it itself.
  const ownAttention = useAttentionList(sessionId, formsExist && attention === undefined && !model, refreshKey);
  const att = attention !== undefined ? attention : ownAttention;
  const rec = model || buildRecommendations({ packageSqs, groupedIssues, keyDetails, dryRun, attention: att, formsExist, tickedFormIds });
  const allChoices = Array.isArray(rec.formChoices) ? rec.formChoices : [];
  // With a Resolved list, a ticked form choice moves there as "Added".
  const keepsResolved = typeof onReopenResolved === "function";
  const choices = keepsResolved ? allChoices.filter((c) => !c.done) : allChoices;
  const resolved = keepsResolved
    ? recommendationResolvedRows({
      statusEntries: issueStatuses?.entries ? Array.from(issueStatuses.entries()) : [],
      liveIds: liveRecommendationIds({ packageSqs, dryRun: formsExist ? null : dryRun }),
      formChoices: allChoices,
    })
    : [];
  // Before forms the group counts its dry-run items and the form choices not yet ticked.
  const formsBadge = rec.forms.count + (formsExist ? 0 : (rec.choicesOpen || 0));
  // The "Your forms will need" group folds like the others (13 Oct 2026), open
  // to start.
  const [formsOpen, setFormsOpen] = useState(true);
  const formsQuiet = formsExist
    ? rec.formsReady && rec.forms.count === 0
    : (dryRun?.status === "ready" && rec.forms.count === 0 && !(rec.choicesOpen > 0));
  const allGood = rec.score.length === 0 && formsQuiet && !generating;

  return (
    <div className="rec" data-testid="recommendations">
      {heading && (
        <div>
          <h3 className="rec-heading">Recommendations</h3>
          <p className="rec-heading-sub">Optional to-dos that raise your score or complete your forms. None of them stops you.</p>
        </div>
      )}
      {allGood && <div className="rec-empty--good">Nothing to add - your package is in good shape.</div>}
      {/* Hidden, not unmounted, when there is nothing to list: the dry run
          still re-checks when the ticked forms change. */}
      <div className="rec" hidden={allGood}>
      <ScoreGroup items={rec.score} onOpenFix={onOpenScoreFix} />
      {formsExist ? (
        <AfterFormsGroup forms={rec.forms.forms} ready={att === undefined ? undefined : (att ? true : null)} onOpenForm={onOpenForm} />
      ) : generating ? (
        <section className="rec-group" aria-label="Your forms will need">
          <FoldHead open={formsOpen} onToggle={() => setFormsOpen((o) => !o)} title="Your forms will need" />
          {formsOpen && <div className="rec-empty">Your forms are being generated. What they need appears here when they are ready.</div>}
        </section>
      ) : (
        <section className="rec-group" aria-label="Your forms will need" data-rec-group="forms">
          <FoldHead open={formsOpen} onToggle={() => setFormsOpen((o) => !o)} title="Your forms will need">
            {/* Its count beside its title, like "Raise your score" (owner, 13 Oct
                2026: "2 to consider" with one card on screen - the other count
                sat beside "Check again" and read as that button's). */}
            {formsBadge > 0 && <span className="rec-count">{formsBadge}</span>}
          </FoldHead>
          {/* Closed is hidden, not unmounted: the form check keeps polling and
              re-checking on the ticks while the group is folded. */}
          <div hidden={!formsOpen}>
          <div className="rec-group__sub">Checked on the forms before they are generated.</div>
          <FormChoices choices={choices} onAddForm={onAddForm} />
          {dryRun ? (
            <BeforeYouGenerate dryRun={dryRun} sessionId={sessionId} tickedFormIds={tickedFormIds}
              onUpdate={onDryRunUpdate} onOpenFix={onOpenDryRunFix}
              title={null} bare hiddenIds={rec.forms.hiddenIds} />
          ) : (
            <div className="rec-empty">The forms are checked once the package has recommended forms.</div>
          )}
          </div>
        </section>
      )}
      </div>
      {/* Outside the hidden block: what was handled stays reachable when
          nothing is left to add. */}
      <ResolvedGroup rows={resolved} onReopen={onReopenResolved}
        reopeningIds={reopeningIds} reopenNotices={reopenNotices} />
    </div>
  );
}
