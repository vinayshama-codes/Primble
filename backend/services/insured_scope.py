"""insured_scope.py - ONE door for: whose company does this value describe?

THE DEFECT THIS CLOSES (8 Oct 2026, the owner's Choice Electric run `b4d18e8e`).
A Harborline Plumbing & Mechanical declarations package was added to a Choice
Electric submission. Submission Integrity warned at the upload ("These
documents name a different insured"), the producer answered "they belong to
this insured", and the merge then took Harborline's identity wholesale:

    dba_name          HARBORLINE MECHANICAL
    mailing_address   P.O. BOX 11820, TACOMA, WA 98411
    physical_address  2210 Port of Tacoma Rd Ste 4B
    fein              91-4478123
    contact_*         Dale Okafor, (253) 555-0187, dokafor@harborline-mech...
    total_revenue     $6,650,000
    naics_code        238220  (plumbing / HVAC - Choice Electric is electrical)
    occupancy_type, year_built, operations_description ...

The package SQS went 38 -> 60 (raw 38 -> 80) on another company's data, and
ACORD 186 printed a Washington contractor licence and Harborline's own policy
number under the name "Choice Electric LLC".

The guards that existed did their job and were not enough: the upload WARNED
and the integrity check CAPPED the score at 60. A cap is not a scope. Nothing
stopped the second company's identity becoming the applicant's.

WHY THE RULE IS SHAPED LIKE THIS
--------------------------------
A document carries its own `facts["applicant_name"]` - what THAT paper says it
insures. The package carries the merged `applicant_name`. So "is this document
about the applicant?" is already answerable from evidence we hold; nothing new
is read and no text is interpreted here.

Four properties, each deliberate:

* **Positive evidence only.** A document that names no insured is never judged
  and contributes exactly as it did before. Absence is not a verdict.
* **Zero blast radius on the ordinary package.** When no document names a
  DIFFERENT insured - every normal submission - this module returns nothing and
  changes nothing. It can only act on a package that already tripped Submission
  Integrity.
* **A value is dropped only when EVERY document stating it belongs to another
  insured.** One applicant document stating the same fact keeps it. So a shared
  value (the same broker, the same term) survives, and only what is uniquely
  the other company's is removed.
* **A person's answer is never touched.** Producer / client provenance is a
  decision, not a document read; the F7 hold and the picker own those.

`applicant_name` itself is deliberately NOT in the scoped set: the merge and
the Data Consistency picker already own that conflict, and blanking it would
remove the very evidence this module reasons from.

NO LLM. Deterministic, and cheap: one entity comparison per document.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── The facts that describe the INSURED ITSELF ───────────────────────────────
# Identity, where it is, how to reach it, how big it is, what it does. These
# are the facts that are wrong - not merely unsupported - when they come off
# another company's paper.
#
# Coverage facts (limits, deductibles, premiums, schedules) are deliberately
# NOT here. They are already line- and policy-scoped by `coverage_lines` /
# `lob_canon` / the per-line records, and a second scoping rule over them would
# be a second owner of a question those doors already answer.
APPLICANT_SCOPED_FACTS: Tuple[str, ...] = (
    # Identity
    "dba_name", "fein", "entity_type", "business_start_date", "years_in_business",
    # Where it is
    "mailing_address", "physical_address",
    # Who to reach
    "contact_name", "contact_phone", "contact_email",
    "contact_secondary_phone", "contact_title",
    # What it does and how big it is
    "operations_description", "naics_code", "sic_code",
    "total_revenue", "total_payroll", "num_employees",
    "num_employees_full_time", "num_employees_part_time",
    "annual_gross_sales", "foreign_sales",
    # The premises it occupies
    "occupancy_type", "year_built", "construction_type",
    "building_area", "num_stories", "num_buildings",
)

_EMPTY = frozenset({"", "null", "none", "n/a", "na", "unknown"})


def _value(raw: Any) -> Any:
    """The value inside a fact envelope, or the bare value."""
    if isinstance(raw, dict) and "value" in raw:
        return raw.get("value")
    return raw


def _is_blank(raw: Any) -> bool:
    val = _value(raw)
    if val is None:
        return True
    if isinstance(val, (list, dict, tuple, set)):
        return not val
    return str(val).strip().lower() in _EMPTY


def _is_human(raw: Any) -> bool:
    """A producer's or client's answer - never scoped away by this module.

    The one door's third question (`fact_state.put_by_person`, 27 Oct 2026):
    a value a person typed or picked. This module kept its own set (with
    "client", "user", "manual" - sources no code writes) and also read the
    CONFIDENCE, which every writer of a person's confidence pairs with the
    same person's source - so the answer is unchanged on every written shape."""
    from services.fact_state import put_by_person
    return put_by_person(raw)


def _same_entity(a: Any, b: Any) -> Optional[bool]:
    """True / False / None (cannot say) for "are these the same company?".

    One door: `normalization.same_entity_name`, which already folds a glued
    OCR name ("CHOICEELECTRICLLC") and canonicalises the legal form. No second
    opinion is formed here.
    """
    sa, sb = str(a or "").strip(), str(b or "").strip()
    if not sa or not sb:
        return None
    try:
        from services.normalization import same_entity_name
    except Exception:                                          # noqa: BLE001
        return None                                # no door, no opinion
    try:
        if same_entity_name(sa, sb):
            return True
        # A name printed WITHOUT its legal form is not decisively another
        # company (live f575160b, 25 Oct 2026: Michelle's handwritten "Choice
        # Electric" against "CHOICE ELECTRIC LLC" dropped her payroll, staff and
        # revenue as another insured's). Two DIFFERENT legal forms still differ.
        ba, fa = _base_and_form(sa)
        bb, fb = _base_and_form(sb)
        if ba and ba == bb and (not fa or not fb):
            return True
        return False
    except Exception:                                          # noqa: BLE001
        return None


_LEGAL_FORM_WORDS = {"LLC", "LLP", "LP", "INC", "INCORPORATED", "CORP", "CORPORATION",
                     "CO", "COMPANY", "LTD", "LIMITED", "PLLC", "PC", "PA", "LC"}


def _base_and_form(name: str) -> tuple:
    """("CHOICEELECTRIC", "LLC") for "Choice Electric, L.L.C." - the name's
    words without trailing legal-form words, and that form ("" when none)."""
    words = re.findall(r"[A-Z0-9]+", re.sub(r"(?<=\b[A-Z])\.(?=[A-Z]\b)", "", name.upper()))
    form = []
    while words and words[-1] in _LEGAL_FORM_WORDS:
        form.insert(0, words.pop())
    return "".join(words), " ".join(form)


def other_insured_documents(facts: Optional[dict],
                            docs: Optional[Iterable[dict]]) -> List[dict]:
    """The documents whose OWN named insured is decisively a different company
    from the package applicant.

    Empty whenever we cannot say - no applicant, no documents, a document that
    names no insured, or an entity comparison that cannot decide.
    """
    try:
        from services.normalization import is_not_a_party_name as _not_a_name
    except Exception:                                         # noqa: BLE001
        _not_a_name = lambda _v: False                        # noqa: E731
    applicant = _value((facts or {}).get("applicant_name"))
    # A heading or a role names nobody (8 Oct 2026: "S.B. MO." won the merge
    # as the applicant on b38a4367). Compared against a non-name, the one
    # document that DID name Choice Electric would have read as another
    # company's - so neither side may be a non-name.
    if not str(applicant or "").strip() or _not_a_name(str(applicant)):
        return []
    out: List[dict] = []
    for doc in (docs or ()):
        if not isinstance(doc, dict) or doc.get("excluded"):
            continue
        own = _value((doc.get("facts") or {}).get("applicant_name"))
        if own is not None and _not_a_name(str(own)):
            continue
        if _same_entity(own, applicant) is False:
            out.append(doc)
    return out


def _documents_stating(key: str, docs: Iterable[dict]) -> List[dict]:
    """Every document whose own facts state a non-blank value for `key`."""
    return [d for d in docs
            if isinstance(d, dict) and not d.get("excluded")
            and not _is_blank((d.get("facts") or {}).get(key))]


def facts_only_another_insured_states(
    facts: Optional[dict],
    docs: Optional[Iterable[dict]],
) -> Dict[str, str]:
    """{fact_key: the other insured's name} for every applicant-scoped fact
    whose ONLY documentary support is a document naming a different company.

    Read-only. Returns {} on any package where no document names a different
    insured, which is every ordinary submission.
    """
    others = other_insured_documents(facts, docs)
    if not others or not isinstance(facts, dict):
        return {}
    other_ids = {id(d) for d in others}
    all_docs = [d for d in (docs or ()) if isinstance(d, dict) and not d.get("excluded")]

    out: Dict[str, str] = {}
    for key in APPLICANT_SCOPED_FACTS:
        raw = facts.get(key)
        if _is_blank(raw) or _is_human(raw):
            continue
        stating = _documents_stating(key, all_docs)
        if not stating:
            continue                      # nothing documentary to attribute
        if any(id(d) not in other_ids for d in stating):
            continue                      # an applicant document states it too
        owner = _value((stating[0].get("facts") or {}).get("applicant_name"))
        out[key] = str(owner or "another insured")
    return out


def drop_other_insured_identity(facts: Optional[dict],
                                docs: Optional[Iterable[dict]]) -> List[str]:
    """Remove the applicant-scoped facts that only another insured's documents
    state. Mutates `facts`; returns the keys removed, for the caller to log.

    The removal is a DELETE, not a blank envelope: a `None` left behind would
    read as "answered, with nothing", and these facts were never the
    applicant's to answer. Never raises - a failure here must not take a merge
    down with it.
    """
    try:
        offending = facts_only_another_insured_states(facts, docs)
        if not offending:
            return []
        for key in offending:
            facts.pop(key, None)
        logger.info(
            "insured_scope: %d applicant fact(s) dropped - only another "
            "insured's documents state them: %s",
            len(offending),
            ", ".join(f"{k} (from {v})" for k, v in sorted(offending.items())),
        )
        return sorted(offending)
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("insured_scope: scoping skipped: %s", exc)
        return []


# ── An office line is not the insured's address (Z37, 24 Oct 2026) ──────────
# Fourth / fifth sighting of one class on Choice Electric (8 and 13 Oct): a
# carrier's details read as someone else's. Travelers' "OFFICE: PHOENIX AZ"
# became the applicant's mailing state AZ and the producer's address; the
# Amerisure dec header "AMERISURE INSURANCE COMPANY / 26777 HALSTED RD /
# FARMINGTON HILLS MI" became the producer's mailing address. An address the
# documents print ONLY under an insurer's name, or on an office / branch line,
# is that office's - never the applicant's, never the submitting agency's.
_OFFICE_LINE_RE = re.compile(
    r"^\s*(?:(?:servicing|service|branch|regional|claims?|underwriting|issuing|"
    r"company|insurer'?s?|carrier'?s?)\s+)?office\s*[:#-]|"
    r"^\s*branch\s*[:#-]", re.I)
# Z38: "HOME OFFICE" is an office label only beside an insurer-shaped name -
# an insured prints its own head office as "Home Office: 123 Main St" too.
_HOME_OFFICE_RE = re.compile(r"\bhome\s+office\b", re.I)
_OFFICE_LABEL_PREFIX_RE = re.compile(
    r"^\s*(?:(?:servicing|service|branch|regional|home|claims?|underwriting|issuing)\s+)?"
    r"(?:office|branch)\s*[:#-]\s*", re.I)


def _compact(text: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


_CARE_OF_RE = re.compile(r"(?:^|[\s,;(])(?:c\s*/\s*o|care\s+of)\b[\s:.,-]*", re.I)


def _care_of_party(line: Any) -> str:
    """The party a "c/o" / "care of" marker names on `line` (the text after
    the last marker), or "". Whose address is printed below it: a care-of
    party's - and it is judged like any other name (`_names_an_insurer`), so
    an accountant or an agency kept as the mailing "c/o" is never an insurer."""
    s = str(line or "")
    marks = list(_CARE_OF_RE.finditer(s))
    return s[marks[-1].end():].strip() if marks else ""


def _address_needle(address: Any) -> str:
    """The part of an address that identifies where it is printed: its street
    line when it has one, else the whole (city / state) text."""
    s = _OFFICE_LABEL_PREFIX_RE.sub("", str(_value(address) or "").strip())
    parts = [p for p in re.split(r"[,\n]", s) if p.strip()]
    street = next((p for p in parts if re.search(r"\d", p) and re.search(r"[A-Za-z]{2}", p)), None)
    needle = _compact(street if street else s)
    return needle if len(needle) >= 5 else ""


def _cell_above(above: str, start: int, end: int) -> str:
    """The part of the line above that sits over columns [start, end). A dec
    page printing the insured's block beside the company's ("CHOICE ELECTRIC
    LLC      TRAVELERS CASUALTY COMPANY" over "123 MAIN ST      ONE TOWER
    SQUARE") puts the insurer above the OTHER column's address, not this one.
    Cells are runs separated by 2+ spaces or a tab; a line with no such gap is
    one cell."""
    cells = [c for c in re.finditer(r"\S+(?:[ ]\S+)*", str(above or ""))]
    hit = [c.group(0) for c in cells if c.start() < end and c.end() > start]
    return " ".join(hit)


def _names_an_insurer(text: Any, own_names: Iterable[Any] = ()) -> bool:
    """Is `text` insurer-shaped once the insured's OWN name is taken out? An
    applicant named "Mutual Plumbing LLC" / "Farmers Mutual Grain Co-op" is
    insurer-shaped by spelling (Z38); its own block is never an insurer's."""
    from services.fact_comparison import looks_like_an_insurer
    text = str(text or "")
    if not looks_like_an_insurer(text):
        return False
    own = [str(n).strip() for n in (own_names or ()) if str(n or "").strip()]
    if not own:
        return True
    try:
        from services.normalization import same_entity_name, entity_compact_key
    except Exception:                                          # noqa: BLE001
        return True
    own_keys = [k for k in (entity_compact_key(n) for n in own) if k and len(k) >= 4]
    kept = []
    for cell in re.findall(r"\S+(?:[ ]\S+)*", text):
        # One cell may print the insured AND another party ("Mutual Plumbing
        # LLC c/o Grange Mutual Insurance Company"): take out only the
        # insured's own name and judge what is left (25 Oct 2026).
        rest = cell
        for n in own:
            pat = r"\s+".join(re.escape(w) for w in n.split())
            rest = re.sub(pat, " ", rest, flags=re.I)
        rest = re.sub(r"^[\W_]*(?:c/o|care of|attn:?|dba)?[\W_]*", "", rest.strip(), flags=re.I).strip()
        if rest != cell.strip():
            if rest and looks_like_an_insurer(rest):
                kept.append(rest)
            continue
        if any(same_entity_name(cell, n) for n in own):
            continue
        ck = entity_compact_key(cell)
        if ck and any(k in ck or (len(ck) >= 6 and ck in k) for k in own_keys):
            continue
        kept.append(cell)
    return looks_like_an_insurer(" ".join(kept))


def _own_names(facts: Any) -> List[str]:
    """The insured's own names on a facts dict (applicant / DBA)."""
    out: List[str] = []
    if isinstance(facts, dict):
        for key in ("applicant_name", "dba_name", "named_insured"):
            v = _value(facts.get(key))
            if isinstance(v, str) and v.strip():
                out.append(v.strip())
    return out


def is_the_insureds_own_name(value: Any, facts: Any = None,
                             own_names: Iterable[Any] = ()) -> bool:
    """Is `value` the insured's OWN name (applicant / DBA / named insured, or
    `own_names`)? THE ONE DOOR every "is this an insurer?" reading asks first
    (27 Oct 2026, Lane B item 4c): an applicant named "Mutual Plumbing
    Company" or "Farmers Mutual Grain Co-op" reads carrier-shaped by spelling,
    and was refused as "an insurance company" on its own interest / owner
    boxes and read as its declarations' page-header INSURER. Same entity,
    never a substring: "Grange Mutual" is not "Mutual Plumbing LLC"."""
    v = str(_value(value) or "").strip()
    if not v:
        return False
    names = [str(n).strip() for n in list(own_names or ()) + _own_names(facts) if str(n or "").strip()]
    if not names:
        return False
    try:
        from services.normalization import same_entity_name
    except Exception:                                          # noqa: BLE001
        return False
    return any(same_entity_name(v, n) for n in names)


_INSURED_LABEL_RE = re.compile(r"\b(?:named\s+)?insured\b|\bapplicant\b", re.I)


def _names_the_insured(text: Any, own_names: Iterable[Any] = ()) -> bool:
    """Does this line NAME the insured - one of its own names in a cell
    ("Named Insured: X LLC", "X LLC"), or, with no own name known, an insured
    label carrying a party's name? A bare label names nobody."""
    s = str(text or "")
    if not s.strip():
        return False
    own = [n for n in (own_names or ()) if str(n or "").strip()]
    cells = re.findall(r"\S+(?:[ ]\S+)*", s)
    # The line must NAME the insured, not merely use the word (Lane B review
    # R3, 27 Oct 2026): "Insured: see schedule" or an "Applicant Information"
    # heading between a carrier's letterhead and "Home Office:" names nobody,
    # and the carrier's home office stays the carrier's.
    if own:
        for c in cells:
            c2 = _INSURED_LABEL_RE.sub(" ", c).strip(" :.-,")
            if is_the_insureds_own_name(c, own_names=own) or (
                    c2 and is_the_insureds_own_name(c2, own_names=own)):
                return True
        return False
    # No own name known: an insured LABEL carrying a value that reads as a
    # party's name (not a placeholder, a role, or an insurer).
    m = re.search(r"\b(?:named\s+)?insured\b|\bapplicant\b", s, re.I)
    if not m:
        return False
    rest = s[m.end():]
    if not rest.lstrip().startswith((":", "-")):
        return False
    val = rest.lstrip()[1:].strip()
    val = re.split(r"\s{2,}", val)[0].strip(" .,")
    if not val:
        return False
    try:
        from services.normalization import is_not_a_party_name
        from services.field_mapping_integrity import names_a_party
        if is_not_a_party_name(val) or _names_an_insurer(val) or not names_a_party(val):
            return False
    except Exception:                                          # noqa: BLE001
        return False
    return bool(re.search(r"[A-Za-z]{2}", val))


def _names_a_known_party(text: Any, party_names: Iterable[Any]) -> bool:
    """The cell names one of the package's own carriers (`party_names`): its
    first distinctive word (5+ letters, not a generic insurance word) opens the
    cell, an OCR'd logo's trailing stray letter allowed ("TRAVELERSJ")."""
    cell = re.sub(r"[^A-Z]", "", str(text or "").upper())
    if len(cell) < 5:
        return False
    generic = {"INSURANCE", "COMPANY", "MUTUAL", "AMERICAN", "NATIONAL", "GENERAL",
               "PROPERTY", "CASUALTY", "FEDERAL", "AMERICA", "THE"}
    for name in party_names or ():
        words = [w for w in re.findall(r"[A-Z]+", str(name or "").upper())
                 if len(w) >= 5 and w not in generic]
        if words and cell.startswith(words[0]) and len(cell) - len(words[0]) <= 2:
            return True
    return False


def address_is_a_party_office(address: Any, texts: Iterable[Any],
                              own_names: Iterable[Any] = (),
                              party_names: Iterable[Any] = ()) -> bool:
    """True when every printing of `address` in `texts` is an insurer's or an
    office's: on an OFFICE / BRANCH line, or under (or beside) an insurer-shaped
    name (`fact_comparison.looks_like_an_insurer`). A short value (a state code,
    a city, a ZIP) is matched as a whole word. False when it is printed nowhere
    (nothing to judge) or anywhere else. Never raises.

    `own_names` (Z38) are the insured's own names: a name that is the
    applicant's is never an insurer here ("Mutual Plumbing LLC"). A HOME OFFICE
    line is an office only with an insurer-shaped name on that line or in the
    cell one or two lines above - an insured's own "Home Office:" is its own."""
    try:
        own_names = [n for n in (own_names or ())]
        party_names = [n for n in (party_names or ()) if n]
        _ins = lambda t: (_names_an_insurer(t, own_names)        # noqa: E731
                          or _names_a_known_party(t, party_names))
        needle = _address_needle(address)
        if needle:
            spread = re.compile(r"[^A-Z0-9]*".join(map(re.escape, needle)))
        else:
            words = re.findall(r"[A-Z0-9]+", _OFFICE_LABEL_PREFIX_RE.sub(
                "", str(_value(address) or "")).upper())
            if not words:
                return False
            spread = re.compile(r"(?<![A-Z0-9])" + r"[^A-Z0-9]+".join(map(re.escape, words))
                                + r"(?![A-Z0-9])")
        printings = 0
        for text in texts or ():
            lines = str(text or "").splitlines()
            for i, line in enumerate(lines):
                m = spread.search(line.upper())
                # A street and its city are often printed on two lines ("26777
                # HALSTED ROAD" / "FARMINGTON HILLS, MI" under an insurer's
                # name, live f575160b 25 Oct 2026): a printing STARTS on this
                # line when the address reads across it and the next two, and
                # not from the next line on.
                if needle and needle not in _compact(line) and not (
                        needle in _compact(" ".join(lines[i:i + 3]))
                        and needle not in _compact(" ".join(lines[i + 1:i + 3]))):
                    continue
                if not needle and not m:
                    continue
                printings += 1
                head = line[:m.start()] if m else ""
                a0, a1 = (m.start(), m.end()) if m else (0, len(line))
                _prev = lines[i - 1] if i > 0 else ""
                above = _cell_above(_prev, a0, a1)
                # A short one-cell line above (a logo: "TRAVELERSJ" over "One
                # Tower Square, Hartford ...") is the whole cell above, even when
                # the match starts past its end (live f575160b, 25 Oct 2026).
                # SHORT: a logo / a name (up to 4 words, 40 characters) - never a
                # sentence that happens to name an insurer (Z42 review A).
                if (not str(above or "").strip() and _prev.strip()
                        and not re.search(r"\S\s{2,}\S", _prev.strip())
                        and len(_prev.strip()) <= 40 and len(_prev.split()) <= 4):
                    above = _prev.strip()
                if _OFFICE_LINE_RE.search(line) or _ins(head) or _ins(above):
                    continue
                # "<insured>   C/O   <insurer>" over the address (27 Oct 2026,
                # Lane B item 4a): a care-of marker names WHOSE address follows,
                # in whichever column of the line above it sits - the cell
                # directly above the street is only the insured's own name.
                if _ins(_care_of_party(_prev)):
                    continue
                if _HOME_OFFICE_RE.search(line):
                    above2 = _cell_above(lines[i - 2] if i > 1 else "", a0, a1)
                    # Two lines up counts only when the line between does not
                    # name the INSURED (27 Oct 2026, Lane B item 4d): a carrier's
                    # letterhead over "Named Insured: X" / "X LLC" over "Home
                    # Office: ..." is the insured's own home office.
                    if _ins(_HOME_OFFICE_RE.sub(" ", line)) or (
                            _ins(above2) and not _names_the_insured(above or _prev, own_names)):
                        continue
                return False
        return printings > 0
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("insured_scope: office-address check skipped: %s", exc)
        return False


_INSURED_ADDRESS_KEYS = ("mailing_address", "physical_address")


def drop_office_addresses(doc: Any) -> List[str]:
    """Per document: an applicant address it prints only as an insurer's /
    office's address leaves its facts (a person's answer never). Mutates the
    document's facts; returns the keys removed."""
    if not isinstance(doc, dict) or not isinstance(doc.get("facts"), dict):
        return []
    facts, text = doc["facts"], doc.get("text") or ""
    own = _own_names(facts)
    out: List[str] = []
    for key in _INSURED_ADDRESS_KEYS:
        raw = facts.get(key)
        if _is_blank(raw) or _is_human(raw):
            continue
        if address_is_a_party_office(raw, [text], own_names=own):
            facts.pop(key, None)
            out.append(key)
    return out
