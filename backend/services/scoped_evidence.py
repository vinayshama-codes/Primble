"""services/scoped_evidence.py - an AI value belongs to the policy its box describes
(7 Oct 2026, round 5).

The owner's live Choice Electric run (session b248c194: seven separate
declarations - a package, auto, WC, an umbrella, an excess layer above it, cyber
and EPLI) put three kinds of value on the forms that no deterministic replay had
ever contradicted, because they come from the AI gap fill (and one from a rule):

  1. A BOX OF ONE POLICY FILLED FROM ANOTHER POLICY'S DOCUMENT. The excess
     layer's ACORD 131 printed a retention of 10,000 - a figure only the cyber
     and EPLI declarations print. The excess states no retention.
  2. A COVERAGE SECTION FILLED FOR COVERAGE THE DOCUMENTS DO NOT CARRY. ACORD
     140's Spoilage and Blanket summary carried the buildings' own limits (no
     document says "spoilage" or names a property blanket); ACORD 131 (Excess)
     printed an Employee Benefits program the umbrella's schedule lists as
     "EXCLUDED Employee Benefits".
  3. THE 131's UNDERLYING "OTHER" ROWS LISTED CYBER AND EBL. Brent (#4): "Layer 1
     is Umbrella, with an underlying schedule focus to GL, Auto, and WC. Layer 2
     is Excess, which gets mapped to the underlying umbrella policy."

One door for each, all deterministic, no LLM, no prompt change:

  (a) `foreign_policy_values` - PER-POLICY EVIDENCE. An AI value in a box that
      states a TERM OF ONE POLICY (a limit, deductible / retention, premium,
      policy number, NAIC, a policy date - read off ACORD's own tooltip; on ACORD
      131 the C102 own-policy classification, `umbrella_layers.field_rule`) is
      kept only when a document that can speak for that policy prints it: a
      document of that line, or one with no line of its own (an application, a
      narrative, a schedule, a loss run with no line), or a multi-line package
      covering it. A copy of one umbrella LAYER reads its own layer's documents
      only. A value printed nowhere is not judged here (that is a different
      question); a value printed ONLY in other policies' documents is dropped.
  (b) `absent_section_fields` / `uncarried_section_values` - SECTION PRESENCE.
      The optional-coverage sections of every form are derived from the field
      names in `forms_schemas` (read-only): a name segment made of a coverage's
      own words plus ACORD's generic element words ("CommercialProperty_Spoilage_
      LimitAmount_A", "CommercialProperty_Summary_BlanketLimitAmount_A",
      "ExcessUmbrella_EmployeeBenefits_ProgramName_A"). A section is CARRIED only
      when a document that speaks for the section's policy names the coverage
      outside policy wording, outside an unpriced menu row, and not as excluded /
      not covered / N/A. Not carried -> the model is not asked (cheaper: C104)
      and a stored AI value is blank. A negative answer ("does spoilage apply? N")
      stands where the documents say the coverage is excluded.
  (c) `scheduled_underlying_leftovers` - THE 131's UNDERLYING OTHER ROWS come from
      the umbrella's own schedule of underlying insurance (the layer's
      `underlying_policies`): a carried line it does not list is not underlying,
      an excluded line never is, and with no schedule known a line the umbrella
      form excludes by default (cyber, EPLI, D&O, EBL, professional, pollution)
      is never underlying - GL, Auto and Employers Liability have the grid's
      NAMED rows; a liquor policy may still take an OTHER row.

THE DOCUMENTS (a) and (b) read are attached to the stamping facts by the caller
(`attach_documents`, under the private key `DOCS_KEY`): `form_service.
process_single_form` and `form_service.shared_gap_fill` do it. The key is never
persisted and never shown to the model (`pdf_service._GAP_FILL_FACTS_EXCLUDE`).
Without it - every other caller, every stored session read back - nothing here
changes a box. Every rule fails open: a document it cannot read, a value it
cannot place, a box it cannot classify is left exactly as it was.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, FrozenSet, Iterable, List, NamedTuple, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# The stamping facts' private key holding the documents (see the module note).
DOCS_KEY = "_scoped_documents"

# ── Reason codes (guard rows) and what the producer reads for each ───────────
REASON_OTHER_POLICY = "VALUE_FROM_ANOTHER_POLICY"
REASON_OTHER_LAYER = "VALUE_FROM_ANOTHER_LAYER"
REASON_SECTION_ABSENT = "COVERAGE_NOT_IN_DOCUMENTS"
REASON_SECTION_EXCLUDED = "COVERAGE_EXCLUDED_IN_DOCUMENTS"
REASON_UNSCHEDULED = "UNDERLYING_NOT_SCHEDULED"          # (c): a rule's row, logged only
REASON_TRIGGER_NOT_STATED = "COVERAGE_TRIGGER_NOT_STATED"  # (d)
REASON_RETENTION_NOT_STATED = "RETENTION_NOT_STATED"       # (e)

HELD_BACK_TEXT: Dict[str, str] = {
    REASON_RETENTION_NOT_STATED: ("This policy's documents do not print this amount as a "
                                  "retention or deductible, so the AI's value was left blank."),
    REASON_OTHER_POLICY: ("The AI used a value your documents print only for another "
                          "policy, so it was left blank."),
    REASON_OTHER_LAYER: ("The AI used a value printed only in another layer's "
                         "documents, so it was left blank."),
    REASON_SECTION_ABSENT: ("Your documents do not show this coverage, so the AI's "
                            "value was left blank."),
    REASON_SECTION_EXCLUDED: ("Your documents show this coverage as excluded or not "
                              "covered, so the AI's value was left blank."),
    REASON_TRIGGER_NOT_STATED: ("This policy's documents do not say it is claims-made or print "
                                "this retroactive date, so the AI's answer was left blank."),
}


def held_back_text(reason: Any) -> Optional[str]:
    """The producer's sentence for one of this module's reason codes, else None."""
    return HELD_BACK_TEXT.get(str(reason or ""))


# Forms the owner froze (14 Sep 2026: ACORD 141 / 160) and the 138 pair, whose
# form-level line the repo itself records as unsure (`pdf_service.
# _SECTION_FORM_LINE_PHRASES`: "contractors equipment" on the Garage and Dealers
# section). No rule here acts on them.
_NOT_JUDGED_FORMS = frozenset({"ACORD_141", "ACORD_160", "ACORD_138_CA", "ACORD_138_CO"})

_UMBRELLA = "umbrella"
_LAYER_MARKER_KEY = "_umbrella_layer"


def _val(held: Any) -> Any:
    return held.get("value") if isinstance(held, dict) and "value" in held else held


def _base(form_id: Any) -> str:
    try:
        from services.form_instances import base_form_id
        return base_form_id(form_id)
    except Exception:                                         # noqa: BLE001
        return str(form_id or "").partition("__")[0]


# ══ The documents ════════════════════════════════════════════════════════════

class Doc(NamedTuple):
    name: str
    lines: Optional[FrozenSet[str]]     # None: the document names no line of its own
    text: str
    # The lines its OWN coverage rows evidence (a premium, a limit, its own
    # policy number) - never a flag. None: no row evidences any line.
    own: Optional[FrozenSet[str]] = None


def _canon(text: Any) -> Optional[str]:
    try:
        from services.lob_canon import canon_line
        return canon_line(text)
    except Exception:                                         # noqa: BLE001
        return None


def document_lines(doc: Any) -> Optional[FrozenSet[str]]:
    """The lines of business ONE document speaks for, from its own extraction:
    the families its own coverage rows evidence (a premium, a limit, its own
    policy number - `lob_canon.evidenced_line_families`, the cover page's
    reading) and its own true `has_<line>` flags; failing that, the families its
    rows NAME (a row denying coverage names nothing). None when the document
    names no line at all - an application, a narrative, a schedule - which then
    speaks for every line."""
    if not isinstance(doc, dict):
        return None
    facts = doc.get("facts") if isinstance(doc.get("facts"), dict) else {}
    flags = doc.get("flags") if isinstance(doc.get("flags"), dict) else {}
    out: Set[str] = set()
    try:
        from services.lob_canon import denies_coverage, evidenced_line_families
        evidenced, _rows = evidenced_line_families(facts, flags)
        out |= {f for f in evidenced if f}
        if not out:
            rows = _val(facts.get("coverage_lines"))
            for r in rows if isinstance(rows, list) else []:
                if isinstance(r, dict) and not denies_coverage(r):
                    fam = _canon(r.get("line"))
                    if fam:
                        out.add(fam)
    except Exception:                                         # noqa: BLE001
        return None
    return frozenset(out) or None


def document_own_lines(doc: Any) -> Optional[FrozenSet[str]]:
    """The lines ONE document's own coverage rows evidence - `document_lines`
    without the `has_<line>` flags. An umbrella's schedule of underlying
    insurance sets the underlying lines' flags; its rows are the umbrella's."""
    if not isinstance(doc, dict):
        return None
    facts = doc.get("facts") if isinstance(doc.get("facts"), dict) else {}
    try:
        from services.lob_canon import evidenced_line_families
        evidenced, _rows = evidenced_line_families(facts, {})
    except Exception:                                         # noqa: BLE001
        return None
    return frozenset(f for f in evidenced if f) or None


def _doc_name(doc: dict) -> str:
    return str(doc.get("filename") or doc.get("doc_id") or "").strip()


def attach_documents(facts: Any, docs: Any) -> Any:
    """Put the ACTIVE documents (excluded ones left out, as every reader does;
    all of them when every one is excluded) on the stamping facts under
    `DOCS_KEY`, each with the lines it speaks for. In place; returns `facts`.
    Never raises."""
    try:
        if not isinstance(facts, dict) or not isinstance(docs, (list, tuple)):
            return facts
        all_docs = [d for d in docs if isinstance(d, dict)]
        active = [d for d in all_docs if not d.get("excluded")] or all_docs
        recs = []
        for i, d in enumerate(active):
            text = str(d.get("text") or "")
            if not text.strip():
                continue
            recs.append(Doc(_doc_name(d) or f"document-{i + 1}", document_lines(d), text,
                            document_own_lines(d)))
        if recs:
            facts[DOCS_KEY] = tuple(recs)
        else:
            facts.pop(DOCS_KEY, None)
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("scoped_evidence: documents not attached: %s", exc)
    return facts


def _documents(facts: Any) -> Tuple[Doc, ...]:
    held = facts.get(DOCS_KEY) if isinstance(facts, dict) else None
    if not isinstance(held, (list, tuple)):
        return ()
    return tuple(d for d in held if isinstance(d, Doc))


# ══ Which policy a box describes ═════════════════════════════════════════════

def _field_words(field: str) -> str:
    base = re.sub(r"_[A-Z]{1,2}$", "", str(field or ""))
    s = re.sub(r"[_\s]+", " ", base)
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)


def form_line(form_id: Any) -> Optional[str]:
    """The line of business a section form is about (`pdf_service.
    _SECTION_FORM_LINE_PHRASES`, the header identity's own table); None for a
    package-wide form (125, 101, 25)."""
    try:
        from services.pdf_service import _SECTION_FORM_LINE_PHRASES
        phrases = _SECTION_FORM_LINE_PHRASES.get(_base(form_id))
    except Exception:                                         # noqa: BLE001
        return None
    return _canon(phrases[0]) if phrases else None


def box_line(form_id: Any, field: str, drop_words: Iterable[str] = ()) -> Optional[str]:
    """The line of business a box speaks about: its own name first
    ("UnderlyingPolicy_Automobile_..." on ACORD 131 is the underlying AUTO;
    "GeneralLiability_EachOccurrence_..." is GL), the form's line otherwise.
    `drop_words`: words removed from the name first (a section's own coverage
    words, so "GeneralLiability_EmployeeBenefits_..." is a GL box)."""
    words = _field_words(field)
    for w in drop_words:
        words = re.sub(rf"(?i)\b{re.escape(w)}\b", " ", words)
    return _canon(words) or form_line(form_id)


# Phrases in ACORD's tooltip that make an amount / date / identifier box a TERM
# OF A POLICY, and the ones that make it a fact about the insured (an exposure,
# a loss) whatever else the tooltip says.
_POLICY_TERM_RE = re.compile(
    r"\b(?:polic(?:y|ies)|coverages?|limits?|deductibles?|retentions?|retroactive|"
    r"premiums?|insurer|carrier|naic|coinsurance|self[- ]insured|sublimit|underlying)\b", re.I)
_INSURED_FACT_RE = re.compile(
    r"\b(?:sales|receipts|payroll|remuneration|revenue|employees?|loss(?:es)?|claims?|paid|"
    r"reserve[ds]?|cost\s+new|stated\s+amount|square|area|values?|budget|subcontract\w*|"
    r"exposure|vehicles?|drivers?|units?|members?|birth|hire[ds]?|licen[cs]e\w*|occurred|"
    r"reported|incurred|inspection|built|construct\w*)\b", re.I)


def _declared_type(meta: Any) -> Optional[str]:
    tu = str((meta or {}).get("tu") or "") if isinstance(meta, dict) else ""
    m = re.match(r"^\s*enter\s+([a-z]+)\s*:", tu, re.I)
    return m.group(1).lower() if m else None


def is_policy_box(form_id: Any, field: str, meta: Any) -> bool:
    """True for a box whose value is a term of ONE policy (see the module note).
    ACORD 131: the C102 own-policy rule (`umbrella_layers.field_rule`), which
    already separates the policy's boxes from the insured's."""
    base = _base(form_id)
    if base == "ACORD_131":
        try:
            from services.umbrella_layers import field_rule
            return field_rule(field) == "private"
        except Exception:                                     # noqa: BLE001
            return False
    kind = _declared_type(meta)
    if kind in ("limit", "deductible"):
        return True
    if kind not in ("amount", "date", "identifier", "percentage"):
        return False
    tu = str((meta or {}).get("tu") or "")
    return bool(_POLICY_TERM_RE.search(tu)) and not _INSURED_FACT_RE.search(tu)


# ══ Which documents may speak for a box ══════════════════════════════════════

def _layer_marker(facts: Any) -> Optional[dict]:
    held = facts.get(_LAYER_MARKER_KEY) if isinstance(facts, dict) else None
    return held if isinstance(held, dict) else None


def _is_shared_131_box(form_id: Any, field: str) -> bool:
    """An ACORD 131 box about the INSURED (C102 `umbrella_layers.field_rule`
    "shared"): one answer for every copy, any document may speak for it."""
    if _base(form_id) != "ACORD_131":
        return False
    try:
        from services.umbrella_layers import field_rule
        return field_rule(field) == "shared"
    except Exception:                                         # noqa: BLE001
        return False


def witness_documents(facts: Any, form_id: Any, line: Optional[str],
                      docs: Optional[Tuple[Doc, ...]] = None,
                      shared: bool = False) -> Optional[List[Doc]]:
    """The documents that may speak for a box of `line` on this form, or None
    when that cannot be told (no documents, no line).

    A document speaks for a line when it names no line of its own or names that
    line. On ACORD 131 a box about an UNDERLYING line also reads the umbrella's
    own documents (its schedule of underlying insurance prints those limits).
    One LAYER of an umbrella tower reads its own layer: an upper layer only its
    own declarations, the lowest layer everything but the upper layers' own.
    `shared`: a box about the insured (ACORD 131's shared boxes) - every
    document speaks for it, on every copy alike."""
    docs = _documents(facts) if docs is None else docs
    if not docs:
        return None
    if shared:
        return list(docs)
    if not line:
        return None
    base = _base(form_id)
    marker = _layer_marker(facts) if base == "ACORD_131" else None
    if marker is not None and not marker.get("missing") and marker.get("index") is not None:
        own = set(marker.get("own_documents") or ())
        others = set(marker.get("other_layer_documents") or ())
        if (marker.get("index") or 0) >= 1:
            return [d for d in docs if d.name in own]
        docs = tuple(d for d in docs if d.name not in others)
    lines = {line}
    if base == "ACORD_131" and line != _UMBRELLA:
        lines.add(_UMBRELLA)
    return [d for d in docs if d.lines is None or (d.lines & lines)]


# A document that only REFERENCES a line - an umbrella whose schedule of
# underlying insurance lists the Workers Compensation policy - speaks for that
# line's limits, dates and identifiers (what such a schedule prints), never for
# its deductibles, premiums, rates or descriptions (8 Oct 2026, run 15f43bba:
# ACORD 130's WC deductible "$1,000" was the umbrella's Minimum Policy Charge,
# and the WC policy states no deductible amount). Only when a document whose
# own rows ARE that line is present; otherwise the reference is all there is.
_SCHEDULE_SPEAKS_FOR = frozenset({"limit", "date", "identifier"})


def _drop_reference_only(witnesses: List[Doc], line: Optional[str], kind: Optional[str],
                         form_id: Any) -> List[Doc]:
    if not witnesses or not line or kind in _SCHEDULE_SPEAKS_FOR or _base(form_id) == "ACORD_131":
        return witnesses
    own = [d for d in witnesses if d.own and line in d.own]
    if not own:
        return witnesses
    return [d for d in witnesses if not (d.lines and line in d.lines and d.own
                                          and line not in d.own)]


# ══ (a) Is a value printed in a document? ════════════════════════════════════

_FOLD_CACHE: Dict[Tuple[str, int, str, str], str] = {}
_FOLD_CACHE_MAX = 96


def _cache_key(doc: Doc) -> Tuple[str, int, str, str]:
    return (doc.name, len(doc.text), doc.text[:48], doc.text[-48:])


def _folded(doc: Doc) -> str:
    key = _cache_key(doc)
    hit = _FOLD_CACHE.get(key)
    if hit is None:
        from services.pdf_service import _normalize_for_search
        hit = _normalize_for_search(doc.text)
        if len(_FOLD_CACHE) >= _FOLD_CACHE_MAX:
            _FOLD_CACHE.clear()
        _FOLD_CACHE[key] = hit
    return hit


_MONTHS = {m: i + 1 for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}
_DATE_NUM_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4}|\d{2})(?!\d)")
_DATE_ISO_RE = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
_DATE_WORD_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b", re.I)
_SPACED_DIGITS_RE = re.compile(r"(?<=\d) (?=[\d/])|(?<=/) (?=\d)")


def _year(y: str) -> int:
    n = int(y)
    return n + 2000 if n < 100 else n


def _date_keys(text: str) -> Set[Tuple[int, int, int]]:
    out: Set[Tuple[int, int, int]] = set()
    s = str(text or "")
    for t in (s, _SPACED_DIGITS_RE.sub("", s)):
        for m in _DATE_NUM_RE.finditer(t):
            out.add((_year(m.group(3)), int(m.group(1)), int(m.group(2))))
        for m in _DATE_ISO_RE.finditer(t):
            out.add((int(m.group(1)), int(m.group(2)), int(m.group(3))))
        for m in _DATE_WORD_RE.finditer(t):
            out.add((int(m.group(3)), _MONTHS[m.group(1).lower()[:3]], int(m.group(2))))
    return out


_DATE_CACHE: Dict[Tuple[str, int, str, str], Set[Tuple[int, int, int]]] = {}


def _doc_dates(doc: Doc) -> Set[Tuple[int, int, int]]:
    key = _cache_key(doc)
    hit = _DATE_CACHE.get(key)
    if hit is None:
        hit = _date_keys(doc.text)
        if len(_DATE_CACHE) >= _FOLD_CACHE_MAX:
            _DATE_CACHE.clear()
        _DATE_CACHE[key] = hit
    return hit


_ONE_AMOUNT_RE = re.compile(r"^\s*\$?\s*\d[\d,]*(?:\.\d+)?\s*$")
_PERCENT_RE = re.compile(r"^\s*(\d{1,3}(?:\.\d+)?)\s*%?\s*$")
# Every number a document prints, as a number: "$75,000", "75000", "75,000.00"
# are one amount (the Choice Electric auto dec prints its hired-auto limit
# "75000"). An OCR-split thousands group ("1,0 0 0") is mended first.
_NUMBER_TOKEN_RE = re.compile(r"(?<![\w.])\$?\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![\w])")
_SPLIT_GROUP_RE = re.compile(r"(?<=\d,)(\d)\s(\d)\s(\d)(?!\d)")


def _number_key(int_part: str, frac: Optional[str]) -> str:
    whole = int_part.replace(",", "").lstrip("0") or "0"
    frac = (frac or "").rstrip("0")
    return f"{whole}.{frac}" if frac else whole


def _numbers_in(text: str) -> Set[str]:
    out: Set[str] = set()
    s = str(text or "")
    for t in (s, _SPLIT_GROUP_RE.sub(r"\1\2\3", s)):
        for m in _NUMBER_TOKEN_RE.finditer(t):
            out.add(_number_key(m.group(1), m.group(2)))
    return out


_NUMBER_CACHE: Dict[Tuple[str, int, str, str], Set[str]] = {}


def _doc_numbers(doc: Doc) -> Set[str]:
    key = _cache_key(doc)
    hit = _NUMBER_CACHE.get(key)
    if hit is None:
        hit = _numbers_in(doc.text)
        if len(_NUMBER_CACHE) >= _FOLD_CACHE_MAX:
            _NUMBER_CACHE.clear()
        _NUMBER_CACHE[key] = hit
    return hit


def _value_number(value: Any) -> Optional[str]:
    m = re.match(r"^\s*\$?\s*(\d[\d,]*)(?:\.(\d+))?\s*$", str(value or ""))
    return _number_key(m.group(1), m.group(2)) if m else None


def _value_shape(value: Any, kind: Optional[str]) -> Optional[str]:
    """"amount" / "percent" / "date" / "identifier", or None (not judged): a
    value this module can find in a document only as itself."""
    s = str(value if value is not None else "").strip()
    if not s:
        return None
    if kind == "date":
        return "date" if _date_keys(s) else None
    if kind == "percentage":
        return "percent" if _PERCENT_RE.match(s) and re.sub(r"\D", "", s).strip("0") else None
    if kind in ("limit", "deductible", "amount"):
        if not _ONE_AMOUNT_RE.match(s):
            return None                     # "Included", "1,000,000 / 2,000,000", "See schedule"
        digits = re.sub(r"\D", "", s.split(".")[0])
        return "amount" if len(digits.lstrip("0")) >= 3 else None
    if kind in ("identifier", "code"):
        compact = re.sub(r"[^A-Za-z0-9]", "", s)
        return "identifier" if len(compact) >= 4 and re.search(r"\d", compact) else None
    return None


def _printed_in(value: Any, shape: str, doc: Doc) -> bool:
    s = str(value).strip()
    if shape == "date":
        return bool(_date_keys(s) & _doc_dates(doc))
    if shape == "percent":
        num = _PERCENT_RE.match(s).group(1)
        return bool(re.search(rf"(?<![\d.,]){re.escape(num)}\s*(?:%|percent)", doc.text, re.I))
    if shape == "identifier":
        compact = re.sub(r"[^a-z0-9]", "", s.lower())
        return compact in re.sub(" ", "", _folded(doc))
    number = _value_number(s)
    return bool(number) and number in _doc_numbers(doc)


def foreign_policy_values(mapped: dict, schema: dict, facts: dict, form_id: Any,
                          ai_fields: Iterable[str]) -> Dict[str, str]:
    """{field: reason} for every AI value in a policy box that only another
    policy's documents print (rule (a), see the module note). Never raises."""
    out: Dict[str, str] = {}
    try:
        base = _base(form_id)
        docs = _documents(facts)
        if not docs or base in _NOT_JUDGED_FORMS:
            return out
        marker = _layer_marker(facts) if base == "ACORD_131" else None
        other_layer = set((marker or {}).get("other_layer_documents") or ())
        for field in sorted(set(ai_fields or ())):
            value = (mapped or {}).get(field)
            meta = (schema or {}).get(field)
            if value is None or not str(value).strip() or not isinstance(meta, dict):
                continue
            if not is_policy_box(form_id, field, meta):
                continue
            shape = _value_shape(value, _declared_type(meta))
            if shape is None:
                continue
            line = box_line(form_id, field)
            witnesses = _drop_reference_only(witness_documents(facts, form_id, line, docs),
                                             line, _declared_type(meta), form_id)
            if not witnesses:
                continue                    # nothing can speak for it: not judged
            if any(_printed_in(value, shape, d) for d in witnesses):
                continue
            printers = [d for d in docs if _printed_in(value, shape, d)]
            if not printers:
                continue                    # printed nowhere: another rule's question
            layer = bool(other_layer) and all(d.name in other_layer for d in printers)
            out[field] = REASON_OTHER_LAYER if layer else REASON_OTHER_POLICY
            logger.info("scoped_evidence %s form=%s field=%s value=%r line=%s printed_in=%s",
                        out[field], form_id, field, str(value)[:40], line,
                        [d.name for d in printers][:3])
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("scoped_evidence: per-policy check skipped (form=%s): %s", form_id, exc)
        return {}
    return out


# ══ (b) The optional-coverage SECTIONS of a form ═════════════════════════════
# A coverage, the CamelCase word sequence(s) ACORD names its section with, the
# phrases a document prints it as, and whether its one word is a MODIFIER that
# names the coverage only at the head of a coverage phrase ("blanket limit",
# never "blanket additional insured" / "blanket waiver of subrogation").
class _Coverage(NamedTuple):
    key: str
    segments: Tuple[Tuple[str, ...], ...]
    phrases: Tuple[str, ...]
    modifier: bool = False


OPTIONAL_COVERAGES: Tuple[_Coverage, ...] = (
    _Coverage("spoilage", (("spoilage",),), ("spoilage",)),
    _Coverage("blanket", (("blanket",),), ("blanket",), modifier=True),
    _Coverage("employee_benefits", (("employee", "benefits"),), ("employee benefit",)),
    _Coverage("earthquake", (("earthquake",), ("earth", "movement")),
              ("earthquake", "earth movement")),
    _Coverage("flood", (("flood",),), ("flood",)),
    _Coverage("watercraft", (("watercraft",),), ("watercraft",)),
    _Coverage("aircraft", (("aircraft",),), ("aircraft",)),
    _Coverage("garagekeepers", (("garage", "keepers"), ("garagekeepers",)),
              ("garagekeeper", "garage keeper")),
    _Coverage("liquor", (("liquor",),), ("liquor",)),
    _Coverage("sinkhole", (("sink", "hole"),), ("sinkhole", "sink hole")),
    _Coverage("mine_subsidence", (("mine", "subsidence"),), ("mine subsidence",)),
    _Coverage("equipment_breakdown", (("equipment", "breakdown"),),
              ("equipment breakdown", "boiler and machinery", "boiler & machinery")),
    _Coverage("fungus", (("limited", "fungus"), ("fungus",)), ("fungus", "fungi")),
)
_COVERAGE_BY_KEY = {c.key: c for c in OPTIONAL_COVERAGES}

# ACORD's own element words: a segment is a coverage's section when what is left
# of it, after the coverage's words, is only these ("SpoilageLimitAmount" yes;
# "WatercraftDocksFloatsOwnedHiredLeasedExplanation" - a question - no).
_ELEMENT_WORDS = frozenset({
    "indicator", "amount", "code", "description", "limit", "limits", "deductible", "count",
    "date", "name", "identifier", "option", "yes", "no", "not", "applicable", "included",
    "accept", "reject", "percent", "number", "type", "liability", "coverage", "program",
    "retention", "retroactive", "each", "aggregate", "per", "claim", "other", "form", "edition",
    "level", "policy", "premises", "subject", "provisions", "collapse", "building", "contents",
    "valuation", "or", "and", "the", "of", "full",
})
# Boxes another owner already decides (ACORD 125's lines of business and
# sections-attached ticks): never a section here.
_SECTION_EXEMPT_PREFIXES = ("Policy_SectionAttached_", "Policy_LineOfBusiness_")


def _camel_words(segment: str) -> List[str]:
    return [w.lower() for w in re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|\d+", segment)]


def coverage_section(field: Any) -> Optional[str]:
    """The optional-coverage section a field belongs to (a key of
    `OPTIONAL_COVERAGES`), read off the field's own name; else None."""
    name = str(field or "")
    if not name or name.startswith(_SECTION_EXEMPT_PREFIXES):
        return None
    base = re.sub(r"_[A-Z]{1,2}$", "", name)
    for segment in base.split("_"):
        words = _camel_words(segment)
        for cov in OPTIONAL_COVERAGES:
            for seq in cov.segments:
                n = len(seq)
                for i in range(len(words) - n + 1):
                    if tuple(words[i:i + n]) != seq:
                        continue
                    rest = words[:i] + words[i + n:]
                    if all(w in _ELEMENT_WORDS for w in rest):
                        return cov.key
    return None


def coverage_sections(schema: Any) -> Dict[str, str]:
    """{field: section} over one form's schema (the derivation the tests pin)."""
    return {f: s for f in (schema or {}) if (s := coverage_section(f))}


# ── Reading one mention of a coverage in a document ─────────────────────────
NAMED, EXCLUDED, NEUTRAL = "named", "excluded", "neutral"

# A denial just BEFORE the coverage on its line: "EXCLUDED Employee Benefits",
# "EXCLUSION - UNMANNED AIRCRAFT", "No known sink hole", "NO FLOOD COVERAGE".
# At most two words between them, and never a status word - in a tabular row
# "Earthquake Coverage NOT COVERED Flood Coverage COVERED" the NOT belongs to
# the row before.
_NEG_BEFORE_RE = re.compile(
    r"\b(?P<neg>excluded|exclusions?|excluding|excludes?|except|without|no|not|nor|never)\b"
    r"(?P<between>(?:[\s:\-–—|,\"'(]+[A-Za-z]+){0,4})[\s:\-–—|,\"'(]*$", re.I)
_STATUS_WORDS = frozenset({"covered", "included", "applicable", "applies", "provided", "written"})
_COORDINATORS = frozenset({"or", "and", "nor"})
# ...or just AFTER it, past the coverage's own label words: "Flood Coverage NOT
# COVERED", "SPOILAGE: N/A", "Employee Benefits Liability: Not requested",
# "FLOOD "AGGREGATE" LIMIT NOT COVERED", "MINE SUBSIDENCE COVERAGE (IL, IN): N/A".
_LABEL_FILLER = (r"(?:[\s\"'(),:;|\-–—.=]|liability|liab|coverages?|coveragepart|part|limits?|"
                 r"insurance|aggregate|occurrence|catastrophe|deductible|each|per|any|one|"
                 r"sublimit|amount|[A-Za-z]{1,3}\b|\d{1,3}\b)*?")
_NEG_AFTER_RE = re.compile(
    r"^" + _LABEL_FILLER + r"(?:excluded|exclusion|not\s+covered|no\s+coverage|n\s*/\s*a\b|"
    r"none\b|declined|rejected|not\s+(?:included|written|purchased|provided|requested|"
    r"applicable|carried|scheduled|offered|available|elected|quoted))", re.I)
# ...or a sentence saying so: "... coverage is not being purchased", "... is not
# scheduled as underlying insurance", "... is not written".
_NEG_CLAUSE_RE = re.compile(
    r"\b(?:is|are|was|were)\s+(?:not|never)\s+(?:being\s+)?(?:covered|included|written|"
    r"purchased|provided|requested|scheduled|carried|offered|elected|quoted|marketed|"
    r"underlying)\b", re.I)
# A forms-schedule row ("CP 04 40 10 12 SPOILAGE COVERAGE", "*CU7460 ...",
# "PF-55505 ..."): an attached form's title names the coverage.
_FORM_ROW_RE = re.compile(r"^\s*[*|]?\s*[A-Z]{1,4}[ -]?\d{2}[ -]?\d{2}", re.I)
_HEAD_WORD_RE = re.compile(
    r"(?:coverage|limit|insurance|deductible|retention|endorsement|sublimit|liability|"
    r"aggregate|occurrence|building|contents|property|bpp|stock|#|^no\.?$|number)", re.I)
_AFFIRMATIVE_AFTER_SEP_RE = re.compile(
    r"^[\s.]*[:|\-–—=][\s.]*(?:\$\s*\d|\d{1,3}(?:,\d{3})+|included|covered|yes\b|x\b|applies)",
    re.I)


def _line_bounds(text: str, start: int, end: int) -> Tuple[int, int]:
    a = text.rfind("\n", 0, start) + 1
    b = text.find("\n", end)
    return a, (len(text) if b < 0 else b)


def _denied_before(before: str) -> bool:
    m = _NEG_BEFORE_RE.search(before)
    if not m:
        return False
    words = [w.lower() for w in re.findall(r"[A-Za-z]+", m.group("between") or "")]
    if set(words) & _STATUS_WORDS:
        return False
    # Two words at most - more only through a coordination the denial spans
    # ("No known sink hole or mine subsidence").
    return len(words) <= 2 or bool(set(words) & _COORDINATORS)


def _mention_state(text: str, start: int, end: int, modifier: bool) -> str:
    """NAMED / EXCLUDED / NEUTRAL for the coverage printed at text[start:end]."""
    a, b = _line_bounds(text, start, end)
    before = text[max(a, start - 48):start]
    after = text[end:min(b, end + 96)]
    # The clause the mention sits in (to the next sentence end on its line).
    clause = re.split(r"[.;?!]\s", after + " ", maxsplit=1)[0]
    if _denied_before(before) or _NEG_AFTER_RE.match(after) \
            or _NEG_CLAUSE_RE.search(clause[:90]):
        return EXCLUDED
    form_row = bool(_FORM_ROW_RE.match(text[a:start]))
    if form_row and re.search(r"\bexcl(?:usions?|uded|\.)?(?=\W|$)", text[end:b], re.I):
        return EXCLUDED                      # "CU 21 27 FUNGI OR BACTERIA EXCLUSION"
    if "?" in after[:80] and not re.search(r"\?\s*(?:yes|y)\b", after, re.I):
        return NEUTRAL                       # a question about it is not the coverage
    # An unpriced row of the common declarations' coverage-part MENU
    # ("LIQUOR LIABILITY COVERAGE PART $" and nothing after the sign).
    if re.search(r"\$\s*$", text[end:b]):
        return NEUTRAL
    if not form_row:
        try:
            from services.pdf_service import _policy_wording_marks
            lo, hi = max(0, start - 400), min(len(text), end + 400)
            if _policy_wording_marks(text[lo:hi]) >= 2:
                return NEUTRAL               # the policy's own drafting, not the declarations
        except Exception:                                     # noqa: BLE001
            pass
    if modifier:
        if _AFFIRMATIVE_AFTER_SEP_RE.match(after):
            return NAMED
        nxt = re.findall(r"[A-Za-z#]+\.?|\$\s*\d[\d,]*|\d[\d,]*", after)[:3]
        if not any(_HEAD_WORD_RE.search(t) for t in nxt):
            return NEUTRAL                   # "blanket additional insured", "blanket waiver"
    return NAMED


def _phrase_regex(phrase: str) -> "re.Pattern":
    # Word-boundaried on the left; any spacing between the words ("employee
    # benefit", "EMPLOYEEBENEFIT" glued by OCR); a plural or a suffix allowed.
    parts = [re.escape(p) for p in re.split(r"\s+", phrase.strip()) if p]
    return re.compile(r"(?<![A-Za-z])" + r"\s*".join(parts), re.I)


_PHRASE_RES: Dict[str, "re.Pattern"] = {}


def _mentions(doc: Doc, cov: _Coverage) -> List[str]:
    states: List[str] = []
    for phrase in cov.phrases:
        rx = _PHRASE_RES.get(phrase)
        if rx is None:
            rx = _PHRASE_RES[phrase] = _phrase_regex(phrase)
        for m in rx.finditer(doc.text):
            states.append(_mention_state(doc.text, m.start(), m.end(), cov.modifier))
            if len(states) > 400:
                return states
    return states


_STATE_CACHE: Dict[Tuple[Tuple[str, int, str, str], str], str] = {}


def _doc_section_state(doc: Doc, cov: _Coverage) -> Optional[str]:
    """NAMED / EXCLUDED for one document, None when it does not name the
    coverage at all (a neutral mention says nothing)."""
    key = (_cache_key(doc), cov.key)
    if key in _STATE_CACHE:
        return _STATE_CACHE[key] or None
    states = _mentions(doc, cov)
    state = NAMED if NAMED in states else (EXCLUDED if EXCLUDED in states else "")
    if len(_STATE_CACHE) >= 4096:
        _STATE_CACHE.clear()
    _STATE_CACHE[key] = state
    return state or None


def section_state(facts: Any, form_id: Any, field: str) -> Optional[str]:
    """For the section `field` belongs to, on this form: NAMED (a document that
    speaks for the section's policy names the coverage), EXCLUDED (named only
    as excluded / not covered), "absent" (never named) - or None when it
    cannot be told (no section, no documents, a form not judged)."""
    sec = coverage_section(field)
    if not sec or _base(form_id) in _NOT_JUDGED_FORMS:
        return None
    cov = _COVERAGE_BY_KEY[sec]
    words = [w for seq in cov.segments for w in seq]
    line = box_line(form_id, field, drop_words=words)
    witnesses = witness_documents(facts, form_id, line,
                                  shared=_is_shared_131_box(form_id, field))
    if not witnesses:
        return None
    states = {_doc_section_state(d, cov) for d in witnesses}
    if NAMED in states:
        return NAMED
    return EXCLUDED if EXCLUDED in states else "absent"


def absent_section_fields(form_id: Any, fields: Iterable[str], facts: Any) -> Dict[str, str]:
    """{field: reason} of the gap-fill questions about a coverage the documents
    do not carry - removed from the shared gap fill before the model is asked.
    The guard (`uncarried_section_values`) holds the same line for a stored
    answer. Never raises."""
    out: Dict[str, str] = {}
    try:
        if not _documents(facts):
            return out
        for f in fields or ():
            st = section_state(facts, form_id, f)
            if st == "absent":
                out[f] = REASON_SECTION_ABSENT
            elif st == EXCLUDED and not _YES_NO_BOX_RE.search(str(f)):
                # Still asked: "does it apply?" has a grounded "No" here.
                out[f] = REASON_SECTION_EXCLUDED
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("scoped_evidence: section check skipped (form=%s): %s", form_id, exc)
        return {}
    return out


_NEGATIVE_ANSWERS = frozenset({"n", "no", "false", "off", "0"})
_YES_NO_BOX_RE = re.compile(r"(?:YesNoCode|YesIndicator|NoIndicator|NotApplicableIndicator)_[A-Z]$")


def _negative_answer(field: str, value: Any, meta: Any) -> bool:
    """A NEGATIVE answer about the coverage: "N" in a Y/N box, or a ticked box
    whose own words say the coverage is rejected / does not apply."""
    v = str(value or "").strip().lower()
    tu = str((meta or {}).get("tu") or "").lower() if isinstance(meta, dict) else ""
    if v in _NEGATIVE_ANSWERS:
        return True
    if re.search(r"(?:NoIndicator|NotApplicableIndicator)_[A-Z]$", field) or "rejected" in tu:
        return v in ("y", "yes", "true", "on", "x", "1")
    return False


def uncarried_section_values(mapped: dict, schema: dict, facts: dict, form_id: Any,
                             ai_fields: Iterable[str]) -> Dict[str, str]:
    """{field: reason} for every AI value in a coverage section the documents do
    not carry (rule (b)). Where the documents name the coverage as excluded, a
    negative answer about it stands - it is what they say. Never raises."""
    out: Dict[str, str] = {}
    try:
        if not _documents(facts):
            return out
        for field in sorted(set(ai_fields or ())):
            value = (mapped or {}).get(field)
            if value is None or not str(value).strip():
                continue
            st = section_state(facts, form_id, field)
            if st == "absent":
                out[field] = REASON_SECTION_ABSENT
            elif st == EXCLUDED and not _negative_answer(field, value, (schema or {}).get(field)):
                out[field] = REASON_SECTION_EXCLUDED
            if field in out:
                logger.info("scoped_evidence %s form=%s field=%s value=%r section=%s",
                            out[field], form_id, field, str(value)[:40],
                            coverage_section(field))
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("scoped_evidence: section guard skipped (form=%s): %s", form_id, exc)
        return {}
    return out


# ══ (a2) A DESCRIPTION printed only by another line's documents (8 Oct 2026) ═
# Rule (a) judges amounts, dates and identifiers. Text went unjudged, and on
# Choice Electric it carried the same borrow: ACORD 126 GL OTHER COVERAGE
# "claims-made coverage" (Chubb's EPL / cyber notice) and ACORD 140 BUILDING
# IMPROVEMENT / GUARD "Certified Risk Management Program" (the WC policy's
# premium credit). Refused only when the exact text IS printed somewhere and
# every printing is in a document that does not speak for the box's line. Not
# the package-wide forms (no line), not ACORD 131 (its underlying sections are
# ABOUT other policies, by design), never a description of the insured's own
# business - that can come from any of the insured's documents.
_TEXT_NOT_JUDGED_FORMS = frozenset({"ACORD_125", "ACORD_101", "ACORD_25", "ACORD_131", "ACORD_186"})
_INSURED_TEXT_RE = re.compile(
    r"\b(?:operations?|business|nature|occupation|occupancy|duties|products?|"
    r"services?|work\s+performed|applicant|named\s+insured|description\s+of\s+(?:the\s+)?"
    r"(?:risk|premises|location))\b", re.I)


def _folded_text(value: Any) -> str:
    try:
        from services.pdf_service import _normalize_for_search
        return _normalize_for_search(str(value or ""))
    except Exception:                                         # noqa: BLE001
        return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def foreign_policy_text(mapped: dict, schema: dict, facts: dict, form_id: Any,
                        ai_fields: Iterable[str]) -> Dict[str, str]:
    """{field: reason} for every AI DESCRIPTION on a line form that only another
    line's documents print. Never raises."""
    out: Dict[str, str] = {}
    try:
        base = _base(form_id)
        docs = _documents(facts)
        if not docs or base in _NOT_JUDGED_FORMS or base in _TEXT_NOT_JUDGED_FORMS:
            return out
        for field in sorted(set(ai_fields or ())):
            value = (mapped or {}).get(field)
            meta = (schema or {}).get(field)
            text = str(value or "").strip()
            if not text or not isinstance(meta, dict) or str(meta.get("ft") or "") == "/Btn":
                continue
            if _declared_type(meta) not in (None, "text", "description"):
                continue
            if len(re.findall(r"[A-Za-z]{2,}", text)) < 2 or re.fullmatch(r"[\d\W]+", text):
                continue
            if _INSURED_TEXT_RE.search(str(meta.get("tu") or "")) or _INSURED_TEXT_RE.search(field):
                continue
            line = box_line(form_id, field)
            witnesses = _drop_reference_only(witness_documents(facts, form_id, line, docs),
                                             line, _declared_type(meta), form_id)
            if not witnesses:
                continue
            needle = _folded_text(text)
            if len(needle) < 6:
                continue
            if any(needle in _folded(d) for d in witnesses):
                continue
            printers = [d for d in docs if needle in _folded(d)]
            if not printers:
                continue                    # printed nowhere: another rule's question
            out[field] = REASON_OTHER_POLICY
            logger.info("scoped_evidence %s (text) form=%s field=%s value=%r line=%s printed_in=%s",
                        REASON_OTHER_POLICY, form_id, field, text[:40], line,
                        [d.name for d in printers][:3])
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("scoped_evidence: per-policy text check skipped (form=%s): %s", form_id, exc)
    return out


# ══ (d) A policy's coverage TRIGGER is its own documents' ═══════════════════
# 8 Oct 2026, run 2076fe35: the EXCESS policy's ACORD 131 ticked claims-made
# Yes with current and proposed retroactive dates of 01/01/2025 (its own
# effective date) - the only claims-made wording in the package is the EPL
# policy's notice, and the excess dec prints "$4,000,000 any one occurrence".
# An AI claims-made tick needs claims-made wording in a document that speaks
# for that policy; an AI retroactive date must be printed beside a "retro"
# label there (an Employee Benefits retro date on a GL dec stands). A "No" is
# never judged here.
_TRIGGER_BOX_RE = re.compile(r"ClaimsMade|Retroactive|RetroDate", re.I)
_RETRO_BOX_RE = re.compile(r"Retroactive|RetroDate", re.I)
_CLAIMS_MADE_TEXT_RE = re.compile(r"claims?[\s-]*made", re.I)
_RETRO_LABEL_RE = re.compile(r"\bretro(?:active)?\b", re.I)
_TRIGGER_YES = frozenset({"y", "yes", "x", "on", "true", "1"})


def _prints_retro_date(doc: Doc, keys: Set[Tuple[int, int, int]]) -> bool:
    return any(_date_keys(doc.text[m.start():m.end() + 80]) & keys
               for m in _RETRO_LABEL_RE.finditer(doc.text))


def trigger_values(mapped: dict, schema: dict, facts: dict, form_id: Any,
                   ai_fields: Iterable[str]) -> Dict[str, str]:
    """{field: reason} for an AI claims-made tick or retroactive date that the
    policy's own documents do not state (rule (d)). Never raises."""
    out: Dict[str, str] = {}
    try:
        docs = _documents(facts)
        if not docs or _base(form_id) in _NOT_JUDGED_FORMS:
            return out
        for field in sorted(set(ai_fields or ())):
            if not _TRIGGER_BOX_RE.search(field or ""):
                continue
            text = str((mapped or {}).get(field) or "").strip()
            if not text:
                continue
            if _RETRO_BOX_RE.search(field):
                keys = _date_keys(text)
                if not keys:
                    continue                       # not a date: another rule's question
                states = lambda d, _k=keys: _prints_retro_date(d, _k)          # noqa: E731
            elif text.lower() in _TRIGGER_YES:
                states = lambda d: bool(_CLAIMS_MADE_TEXT_RE.search(d.text))  # noqa: E731
            else:
                continue
            witnesses = witness_documents(facts, form_id, box_line(form_id, field), docs)
            if not witnesses or any(states(d) for d in witnesses):
                continue
            out[field] = (REASON_OTHER_POLICY if any(states(d) for d in docs)
                          else REASON_TRIGGER_NOT_STATED)
            logger.info("scoped_evidence %s (trigger) form=%s field=%s value=%r",
                        out[field], form_id, field, text[:20])
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("scoped_evidence: trigger check skipped (form=%s): %s", form_id, exc)
    return out


# ══ (e) An umbrella / excess RETENTION is printed as one ═════════════════════
# Owner's run `18ecbfa8` (12 Oct 2026): the Excess 131 printed a $5,000
# retention. The Excess declarations print "POLICY LIMITS (000 OMITTED) ...
# 5,000 EACH OCCURRENCE" - the UMBRELLA's $5,000,000 limit in thousands - and no
# retention at all. Rule (a) let it through because "5,000" IS printed in that
# policy's own document; what it does not prove is the MEANING. Same shape as
# (d)'s retro date: the AI's amount must sit beside a retention / SIR /
# self-insured / retained / deductible label in the policy's own documents.
# Only the umbrella / excess retention box (ACORD 131 and its copies, ACORD 25).
_RETENTION_BOX_RE = re.compile(r"^ExcessUmbrella_Umbrella_DeductibleOrRetentionAmount_[A-Z]$")
_RETENTION_LABEL_RE = re.compile(
    r"\b(?:self[\s-]*insured|retentions?|retained|s\.\s?i\.\s?r\.?|sir|deductibles?)\b", re.I)
_RETENTION_BEFORE = 40       # "$10,000 Self-Insured Retention"
_RETENTION_AFTER = 160       # "Self-Insured Retention ... $10,000 each occurrence"


def _prints_as_retention(doc: Doc, number: str) -> bool:
    text = doc.text or ""
    return any(number in _numbers_in(text[max(0, m.start() - _RETENTION_BEFORE):
                                          m.end() + _RETENTION_AFTER])
               for m in _RETENTION_LABEL_RE.finditer(text))


def retention_values(mapped: dict, schema: dict, facts: dict, form_id: Any,
                     ai_fields: Iterable[str]) -> Dict[str, str]:
    """{field: reason} for an AI umbrella / excess retention the policy's own
    documents do not print as a retention (rule (e)). Never raises."""
    out: Dict[str, str] = {}
    try:
        docs = _documents(facts)
        if not docs or _base(form_id) in _NOT_JUDGED_FORMS:
            return out
        for field in sorted(set(ai_fields or ())):
            if not _RETENTION_BOX_RE.match(field or ""):
                continue
            number = _value_number((mapped or {}).get(field))
            if number is None:
                continue                  # "Included", "None", a range - another rule's question
            witnesses = witness_documents(facts, form_id, box_line(form_id, field), docs)
            if not witnesses or any(_prints_as_retention(d, number) for d in witnesses):
                continue
            out[field] = (REASON_OTHER_POLICY if any(_prints_as_retention(d, number) for d in docs)
                          else REASON_RETENTION_NOT_STATED)
            logger.info("scoped_evidence %s (retention) form=%s field=%s value=%r",
                        out[field], form_id, field, str((mapped or {}).get(field))[:20])
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("scoped_evidence: retention check skipped (form=%s): %s", form_id, exc)
    return out


def out_of_scope_values(mapped: dict, schema: dict, facts: dict, form_id: Any,
                        ai_fields: Iterable[str]) -> Dict[str, str]:
    """The guard's one call: rules (b) then (a) over the AI values of one form.
    {field: reason code}. Nothing without attached documents."""
    ai = set(ai_fields or ())
    if not ai or not _documents(facts):
        return {}
    out = uncarried_section_values(mapped, schema, facts, form_id, ai)
    rest = ai - set(out)
    out.update(foreign_policy_values(mapped, schema, facts, form_id, rest))
    rest = rest - set(out)
    out.update(foreign_policy_text(mapped, schema, facts, form_id, rest))
    rest = rest - set(out)
    out.update(trigger_values(mapped, schema, facts, form_id, rest))
    rest = rest - set(out)
    out.update(retention_values(mapped, schema, facts, form_id, rest))
    return out


# ══ (c) The 131's underlying OTHER rows ══════════════════════════════════════

def _schedule_rows(facts: Any) -> List[dict]:
    rows = _val(facts.get("underlying_policies")) if isinstance(facts, dict) else None
    return [r for r in rows if isinstance(r, dict) and str(r.get("line") or "").strip()] \
        if isinstance(rows, list) else []


_ROW_EXCLUDED_RE = re.compile(r"\bexclu(?:ded|sion)\b|\bnot\s+covered\b|\bno\s+coverage\b", re.I)


def _row_excluded(row: dict) -> bool:
    return any(_ROW_EXCLUDED_RE.search(str(v)) for v in row.values()
               if isinstance(v, str) and v.strip())


def _name_tokens(text: Any) -> Set[str]:
    try:
        from services.lob_canon import GL_GENERIC_TOKENS
    except Exception:                                         # noqa: BLE001
        GL_GENERIC_TOKENS = frozenset()
    return {t for t in re.findall(r"[a-z]+", str(text or "").lower())
            if len(t) > 2 and t not in GL_GENERIC_TOKENS}


# Liability lines an umbrella does NOT sit over unless its own schedule says so:
# the ISO commercial umbrella form (CU 00 01) excludes employment-related
# practices, professional services, pollution, access to or disclosure of
# confidential information / electronic data and ERISA-type employee benefit
# claims, and management (D&O) liability is no part of it. Liquor liability is
# not excluded - an umbrella follows it like the GL.
_NOT_UNDERLYING_UNLESS_SCHEDULED = frozenset({
    "cyber", "epli", "directors_officers", "employee_benefits", "professional", "pollution",
})


def scheduled_underlying_leftovers(leftovers: List[dict], facts: Any) -> List[dict]:
    """The leftover liability lines (`pdf_service._specialty_leftover_lines`)
    the umbrella's own schedule of underlying insurance lists - rule (c).

    The schedule is the stamping facts' `underlying_policies` (on one layer of a
    tower, that layer's own rows - `umbrella_layers` scopes it). A leftover is
    underlying when a schedule row names its line (same family, or - for a line
    the families cannot place - its own words) and that row does not say the
    line is excluded. With no schedule known (no row beyond the umbrella
    itself), a line the umbrella form excludes by default
    (`_NOT_UNDERLYING_UNLESS_SCHEDULED`: cyber, EPLI, D&O, EBL, professional,
    pollution) is never underlying; the grid's NAMED rows (GL, Auto, Employers
    Liability) are the standard ones and stay theirs."""
    if not leftovers:
        return leftovers
    try:
        rows = [r for r in _schedule_rows(facts) if _canon(r.get("line")) != _UMBRELLA]
        kept: List[dict] = []
        if not rows:
            kept = [e for e in leftovers
                    if _canon(e.get("line")) not in _NOT_UNDERLYING_UNLESS_SCHEDULED]
        else:
            fams: Set[str] = set()
            excluded: Set[str] = set()
            names: List[Set[str]] = []
            for r in rows:
                fam = _canon(r.get("line"))
                if _row_excluded(r):
                    if fam:
                        excluded.add(fam)
                    continue
                if fam:
                    fams.add(fam)
                names.append(_name_tokens(r.get("line")))
            for e in leftovers:
                fam = _canon(e.get("line"))
                if fam and fam in excluded:
                    continue
                if fam and fam in fams and fam != "general_liab":
                    kept.append(e)
                    continue
                toks = _name_tokens(e.get("line"))
                if toks and any(len(toks & n) >= min(2, len(toks)) for n in names):
                    kept.append(e)
        dropped = [str(e.get("line") or "") for e in leftovers if e not in kept]
        if dropped:
            logger.info("scoped_evidence %s: %s - %s", REASON_UNSCHEDULED,
                        "the umbrella's schedule of underlying insurance does not list "
                        "them" if rows else "no schedule is known and the umbrella form "
                        "excludes them by default", dropped[:4])
        return kept
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("scoped_evidence: underlying schedule check skipped: %s", exc)
        return leftovers
