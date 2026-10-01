import { splitMissingDetails } from "../../../utils/keyDetailCards";

// "Key details missing" on the pre-form Review screen, as ACTIONS (Orbin 22 Sep
// item 9; owner, 30 Sep 2026: "do the action, not just mention it on the
// screen"). Each missing detail the server says a person can answer is a link
// that opens the same "Open to fix" window the warnings use - one save path,
// one score refresh. A detail nobody can type stays plain text, never a dead
// button. Old payloads without `missing_items` print the plain list as before.
//
// Item 3 (1 Oct 2026): a detail that already has its own card under Warnings or
// Hard Stops (`keyDetails.on_cards`, utils/keyDetailCards) is shown there only -
// the card names the cap and carries the same fix. This line just counts them,
// with a jump to that section where the layout has one (`onShowSection`).

const linkStyle = {
  background: "none", border: "none", padding: 0, margin: 0,
  color: "#E61B84", fontWeight: 600, textDecoration: "underline",
  textUnderlineOffset: 2, cursor: "pointer", font: "inherit",
};

const SECTION_NAMES = { hardstops: "Hard Stops", warnings: "Warnings" };

function Elsewhere({ elsewhere, more, onShowSection }) {
  if (!elsewhere.length) return null;
  return (
    <span data-testid="key-details-on-cards">
      {elsewhere.map((x, i) => (
        <span key={x.section}>
          {i > 0 ? " and " : ""}
          {x.count}{more ? " more" : ""} under{" "}
          {typeof onShowSection === "function" ? (
            <button type="button" style={linkStyle} onClick={() => onShowSection(x.section)}
              title={`Show ${SECTION_NAMES[x.section]}`}>
              {SECTION_NAMES[x.section]}
            </button>
          ) : SECTION_NAMES[x.section]}
        </span>
      ))}
      .
    </span>
  );
}

export default function KeyDetailsMissing({ keyDetails, onFix, onShowSection, className = "tier2-missing" }) {
  const { labels, listed, items, elsewhere } = splitMissingDetails(keyDetails);
  if (!labels.length) return null;
  if (!listed.length) {
    return (
      <div className={className} data-testid="key-details-missing">
        Key details missing:{" "}
        <Elsewhere elsewhere={elsewhere} more={false} onShowSection={onShowSection} />
      </div>
    );
  }
  const tail = elsewhere.length
    ? <> <Elsewhere elsewhere={elsewhere} more onShowSection={onShowSection} /></>
    : null;
  // No usable action list (an old payload, or the server could not build one):
  // the plain labels, never an empty "Key details missing:".
  if (!items || !items.length || typeof onFix !== "function") {
    return <div className={className}>Key details missing: {listed.join(" · ")}{tail ? "." : ""}{tail}</div>;
  }
  const answerable = items.some(it => it && it.resolution);
  return (
    <div className={className} data-testid="key-details-missing">
      Key details missing:{" "}
      {items.map((it, i) => (
        <span key={`${it.label}-${i}`}>
          {i > 0 ? " · " : ""}
          {it.resolution ? (
            <button type="button" style={linkStyle} onClick={() => onFix(it)}
              title={`Enter ${it.label} now`} aria-label={`Enter ${it.label} now`}>
              {it.label}
            </button>
          ) : <span>{it.label}</span>}
        </span>
      ))}
      {answerable ? <span style={{ fontWeight: 400 }}> - click one to enter it now.</span> : (tail ? "." : null)}
      {tail}
    </div>
  );
}
