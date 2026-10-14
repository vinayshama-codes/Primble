"""needs_attention.py - ONE door for "which boxes on this form still need a
human, and why" (Orbin 22 Sep items 9 and 19, 30 Sep 2026).

The client: *"We know what's missing / required / verify. Why can't we put
them in the side panel?"* and *"I'd like each item to tell me what needs
attention, what to do next, and how it could affect the score. It should also
be clear whether information is missing, the AI withheld a value, or an
inferred value needs verification ... the Field QA summary says 4 required
fields are empty and 7 AI-inferred fields need verification, but I can't tell
which forms or questions it's referring to."*

Before this module the three states lived in three places, and the
pre-download review re-derived them with its own rules:

* **Missing** - the viewer's yellow "Required" boxes: the stored confidence
  label `missing_required` / `extraction_error`, re-derived on read by
  `apply_acord125/126_missing_field_highlights` (the fields endpoint), plus
  the viewer's always-required signature boxes (`YELLOW_REQUIRED` in
  PDFJsViewer.jsx).
* **AI held back** - `generated_forms[fid]["guard_blanks"]`: a value was found
  and a post-fill guard removed it (blank over wrong).
* **Please verify** - `low_confidence` with a value: AI-filled and not found in
  the documents (the orange "Verify" boxes).

`field_qa.to_recommendation_rows` counted BOXES in one sentence and listed
NAMES in the next ("19 fields ... +7 more"), printed internal field names
("AdditionalInterest FullName"), and let the same box appear both as "a value
was found but removed" and "no value found", because its guard branch and its
not-answered branch never looked at each other. This door gives every box
exactly ONE status, and every surface (side panel, pre-download review, the
E&O rows) reads it, so their counts cannot disagree.

PRECEDENCE (one box, one status, decided here and nowhere else):

1. A box that has a value is never Missing and never Held back. It is
   "Please verify" only when its label is `low_confidence`.
2. An empty box a guard emptied is "AI held back" - it outranks Missing,
   because "we found X and refused it, here is why" is the more useful
   sentence (the row still carries `required: True`). Not held back, because
   nothing was lost:
   * a refused value the SAME form already prints in another box (a copy);
   * a spare row of a repeating section the form does not use (row B..N of a
     section whose row has no value in any box);
   * an explanation / date / option box of a Yes/No question the evidence gate
     refused - the QUESTION is the finding, and it is listed once.
3. Otherwise an empty required box is Missing.

Display only. Nothing here changes a value, a label or a score (D6).
"""

from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

STATUS_MISSING = "missing"
STATUS_HELD_BACK = "ai_held_back"
STATUS_VERIFY = "verify"
STATUS_ORDER: Tuple[str, ...] = (STATUS_MISSING, STATUS_HELD_BACK, STATUS_VERIFY)
STATUS_TAG: Dict[str, str] = {
    STATUS_MISSING: "Missing",
    STATUS_HELD_BACK: "AI held back",
    STATUS_VERIFY: "Please verify",
}

# The labels the viewer paints yellow ("Required"). `missing_required_gate`
# (ACORD 140 COPE) is NOT listed here (review, 30 Sep): its own hard-block row
# already names it in the download review and the Hard Stops, and listing it
# again made one box appear twice. The viewer's legend has no colour for it.
_REQUIRED_LABELS = frozenset({"missing_required", "extraction_error"})

# ACORD 125 "tick one (or more) of these" groups: when none is ticked, every box
# of the group carries the Required label, so a nearly empty form listed 21
# line-of-business boxes, 9 entity boxes and 11 business-type boxes as 41
# separate Missing rows (review, 30 Sep). One row per group instead, on the
# group's first box, with the box count kept for the viewer-badge arithmetic.
_ACORD125_TICK_GROUPS = (
    ("_ACORD125_LOB_FIELDS", "Lines of business applied for",
     "Tick every line of business this application covers."),
    ("_ACORD125_ENTITY_FIELDS", "Business entity type",
     "Tick the one that applies."),
    ("_ACORD125_BUSINESS_TYPE_FIELDS", "Nature of business",
     "Tick the one that applies."),
)

# ACORD 125 premises CHOICES (owner, 30 Sep 2026). The 125 rule flags ONE box
# per choice - OWNER, INSIDE - when no box of that choice is ticked
# (`pdf_service.apply_acord125_missing_field_highlights`), so the row names the
# choice, not that box: "...interest in the building is as its owner - tick it
# if it applies" nudged a TENANT towards the OWNER box.
_ACORD125_CHOICE_ROWS = {
    "CommercialStructure_InsuredInterest_OwnerIndicator":
        "Named insured's interest in the building (owner, tenant or other)",
    "CommercialStructure_RiskLocation_InsideCityLimitsIndicator":
        "Building inside or outside the city limits",
}

# Mirrors `YELLOW_REQUIRED` in frontend/src/components/form/PDFJsViewer.jsx:
# the signature boxes the viewer counts as Required whenever they are empty.
# Pinned against the .jsx by tests/test_needs_attention_30sep.py.
VIEWER_ALWAYS_REQUIRED = frozenset({"NamedInsured_Signature_A", "NamedInsured_SignatureDate_A"})

_ROW_RE = re.compile(r"^(?P<base>.+)_(?P<row>[A-Z])$")


def _has_value(v: Any) -> bool:
    return v is not None and str(v).strip() not in ("", "null", "None")


# A FILLED box whose label weighs less than a confirmed value in the fill rate
# and that nothing else settles (13 Oct 2026 - the SQS reaches 100 after forms
# once everything is answered): an AI value not found in the documents
# ("low_confidence"), an AI value found in them ("ai_verified" - 0.85 by Brent's
# 24 Aug weights, so it counts in full only once a person confirms it), and a
# value sitting under a stale "required and empty" label. Each is "Please
# verify" with a Confirm, which relabels it the producer's without changing it.
# A "conflicted" box is settled in Data Consistency, not here.
CONFIRMABLE_LABELS = frozenset({"low_confidence", "ai_verified",
                                "missing_required", "missing_required_gate"})
_UNTICKED = frozenset({"Off", "/Off"})        # a checkbox's empty state


def form_label(form_id: str) -> str:
    # "ACORD 131", and a form's second copy "ACORD 131 (Excess)" (7 Oct 2026).
    from services.form_instances import instance_label
    return instance_label(form_id or "")


# ── Where each box sits on the printed form ──────────────────────────────────

def _template_path(form_id: str, generated_form: Optional[dict]) -> Optional[str]:
    try:
        from config.settings import TEMPLATE_DIR
    except Exception:                                      # pragma: no cover
        return None
    from services.form_instances import base_form_id
    tpl = ((generated_form or {}).get("form") or {}).get("template_file") \
        or f"{base_form_id(form_id)}.pdf"
    tpl = os.path.basename(str(tpl))                       # never a path from the row
    path = os.path.join(TEMPLATE_DIR, tpl)
    return path if os.path.exists(path) else None


@lru_cache(maxsize=64)
def _widget_positions_cached(path: str, mtime: float) -> Dict[str, Tuple[int, float, float]]:
    """{field: (page 1-based, top, x)} for the FIRST widget of each field - the
    page the viewer opens and the printed reading order. Templates do not
    change, so this is cached per file."""
    from services.pdf_service import extract_form_fields_with_positions
    out: Dict[str, Tuple[int, float, float]] = {}
    for f in extract_form_fields_with_positions(path) or []:
        name = f.get("name")
        if not name or name in out:
            continue
        r = f.get("rect") or {}
        top = float(r.get("y", 0.0)) + float(r.get("height", 0.0))
        out[name] = (int(f.get("page", 0)) + 1, top, float(r.get("x", 0.0)))
    return out


def widget_positions(form_id: str, generated_form: Optional[dict] = None) -> Dict[str, Tuple[int, float, float]]:
    path = _template_path(form_id, generated_form)
    if not path:
        return {}
    try:
        return _widget_positions_cached(path, os.path.getmtime(path))
    except Exception as exc:                               # noqa: BLE001
        logger.warning("needs_attention: widget positions unavailable for %s - %s", form_id, exc)
        return {}


@lru_cache(maxsize=32)
def _schema_from_disk(form_id: str) -> dict:
    try:
        from config.settings import FORMS_SCHEMAS_DIR
        from services.form_instances import base_form_id
        with open(os.path.join(FORMS_SCHEMAS_DIR,
                               f"{os.path.basename(base_form_id(form_id))}_schema.json")) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:                                      # noqa: BLE001
        return {}


# ── The question as the form prints it ───────────────────────────────────────

_TU_PREFIX_RE = re.compile(
    r"^\s*(?:enter [a-z ]{2,20}|check the box \(if applicable\)|sign here|initial here)\s*:\s*",
    re.IGNORECASE,
)
_LEAD_RE = re.compile(r"^(?:indicates that |indicates |accommodates |enter (?=the )|the )", re.IGNORECASE)
_AS_USED_RE = re.compile(r"as used here,\s*(?:this is\s+)?(?P<q>[^.]+)", re.IGNORECASE)
_LABEL_MAX = 140


def _strip_lead(text: str) -> str:
    """"Indicates the building is ..." -> "building is ..." (every leading
    connective, not just the first)."""
    prev = None
    text = (text or "").strip()
    while prev != text:
        prev, text = text, _LEAD_RE.sub("", text).strip()
    return text


def _tooltip(schema: dict, field: str) -> str:
    meta = (schema or {}).get(field)
    return str((meta or {}).get("tu") or "") if isinstance(meta, dict) else ""


def _field_type(schema: dict, field: str) -> str:
    meta = (schema or {}).get(field)
    return str((meta or {}).get("ft") or "") if isinstance(meta, dict) else ""


def is_question_box(schema: dict, field: str) -> bool:
    """A Yes/No QUESTION box: ACORD's own tooltip convention "... response to
    the question, "<Q>"". Explanation, date, description and option boxes
    beside a question never carry it - so they are never listed as questions."""
    return "the question," in _tooltip(schema, field).lower()


def _question_text(tooltip: str) -> str:
    try:
        from services.pdf_service import _compliance_question_text
        return _compliance_question_text(tooltip)
    except Exception:                                      # pragma: no cover
        return tooltip


def _words_from_name(field: str) -> str:
    """Last resort when a box has no tooltip: words, never the internal name."""
    m = _ROW_RE.match(field or "")
    base = m.group("base") if m else (field or "")
    parts = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", base.replace("_", " ")).split()
    text = " ".join(parts).lower()
    return text[:1].upper() + text[1:] if text else "This box"


def _trim(text: str, limit: int = _LABEL_MAX) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:")
    return cut + "..."


def _first_sentence(body: str) -> str:
    """The text up to the first sentence end - never one inside a quotation
    or an ellipsis. ACORD 127 quotes its own question: 'The number of years
    associated with "... an accident... or convicted of a moving violation"
    question.' was cut to 'Number of years associated with "... an accident'
    (owner's live run, 30 Sep 2026)."""
    quoted = False
    n = len(body)
    for i, ch in enumerate(body):
        if ch == '"':
            quoted = not quoted
        elif ch == "\u201c":
            quoted = True
        elif ch == "\u201d":
            quoted = False
        elif ch in ".?!" and not quoted:
            if ch == "." and ((i + 1 < n and body[i + 1] == ".") or (i > 0 and body[i - 1] == ".")):
                continue                                   # an ellipsis
            if i + 1 >= n or body[i + 1].isspace():
                return body[:i + 1]
    return body


def box_label(schema: dict, field: str) -> str:
    """The box as the form prints it, from ACORD's own tooltip."""
    tu = _tooltip(schema, field)
    if not tu.strip():
        return _words_from_name(field)
    if is_question_box(schema, field):
        q = _question_text(tu).strip().strip('"“”').strip()
        # ACORD closes its quotation before the question mark: '...applicant"?'
        q = re.sub(r'["“”]+\s*\?$', "?", q)
        return _trim(q or tu)
    qualifier = ""
    m_used = _AS_USED_RE.search(tu)
    if m_used:
        qualifier = _strip_lead(m_used.group("q").strip())
    body, prev = tu.strip(), None
    while prev != body:                    # ACORD sometimes prints the prefix twice
        prev, body = body, _TU_PREFIX_RE.sub("", body).strip()
    if body.lower().startswith("enter y for a"):
        # "...Yes/No code" boxes with no "the question," clause: keep the part
        # after the two preamble sentences (the description ACORD prints).
        body = _question_text(tu)
    # Split at a sentence end only: ACORD's tooltips also carry runs of double
    # spaces MID-sentence, which cut labels to "The" / "That" (review, 30 Sep).
    body = re.sub(r"\s+", " ", body).strip()
    first = _first_sentence(body).strip()
    first = _strip_lead(first).rstrip(".").strip()
    if not first:
        return _words_from_name(field)
    first = first[:1].upper() + first[1:]
    if qualifier and qualifier.lower() not in first.lower():
        return _trim(f"{first} ({qualifier})")
    return _trim(first)


def form_box_label(form_id: str, field: str, schema: Optional[dict] = None) -> str:
    """`box_label` for a box of `form_id`, reading the stored schema when it
    has one and the form's own schema file otherwise. The ONE way a review row
    names a box (field QA, field mapping, this list - Michelle's item 19)."""
    sch = schema if isinstance(schema, dict) and schema else _schema_from_disk(form_id)
    return box_label(sch, field)


def _row_suffix(schema: dict, field: str) -> str:
    """" (row 2)" for a second or later row of a repeating section. Row one
    is the box the reader meets first, so it carries no suffix."""
    m = _ROW_RE.match(field or "")
    if not m or m.group("row") == "A" or "as used here" in _tooltip(schema, field).lower():
        return ""
    return f" (row {ord(m.group('row')) - ord('A') + 1})"


# ── Which fact a box feeds, and what closing it is worth ─────────────────────

def box_fold_keys(field: str) -> List[str]:
    """What a box ANSWERS, so the download screen can fold it into the card or
    issue that asks the same thing (owner, 14 Oct 2026, run 0353c36b - "own or
    rent?" and the 130 officers each printed twice): the fact an edit writes
    (`box_fact_key`), the schedule table its row belongs to (the stamper's own
    binding), and the premises interest for the ACORD 125 interest ticks the
    own-or-rent card itself checks (`premises_interest.FORM_INTEREST_BOXES`).
    Display only - nothing is written or scored from it."""
    keys: List[str] = []
    fk = box_fact_key(field)
    if fk:
        keys.append(fk)
    try:
        from services.pdf_service import _SCHED_ROW_RE, _schedule_def_for_base
        m = _SCHED_ROW_RE.match(str(field or ""))
        d = _schedule_def_for_base(m.group(1)) if m else None
        if d is not None and d.list_key and d.list_key not in keys:
            keys.append(d.list_key)
    except Exception:                                      # pragma: no cover
        pass
    try:
        from services.premises_interest import FORM_INTEREST_BOXES, PREMISES_INTEREST_FACT
        if field in FORM_INTEREST_BOXES and PREMISES_INTEREST_FACT not in keys:
            keys.append(PREMISES_INTEREST_FACT)
    except Exception:                                      # pragma: no cover
        pass
    return keys


def box_fact_key(field: str) -> Optional[str]:
    """The fact a producer's edit of this box writes - exactly the loop
    `form_routes.update_pdf` runs (first `_ACORD_FIELD_RULES` pattern with a
    real fact key, else the write-back table). None when an edit writes none."""
    try:
        from services.pdf_service import _ACORD_FIELD_RULES, writeback_fact_for_field
    except Exception:                                      # pragma: no cover
        return None
    for pattern, fact_key in _ACORD_FIELD_RULES:
        if fact_key and not str(fact_key).startswith("_") and pattern in (field or ""):
            return fact_key
    try:
        return writeback_fact_for_field(field)
    except Exception:                                      # pragma: no cover
        return None


def _recs_by_fact(*rec_lists: Iterable[dict]) -> Dict[str, dict]:
    """First recommendation per fact key, in the order the lists are given.
    Only recommendations the scorer MEASURED or declared with points count."""
    out: Dict[str, dict] = {}
    for recs in rec_lists:
        for r in recs or []:
            if not isinstance(r, dict):
                continue
            fk = r.get("field")
            if not fk or fk in out:
                continue
            out[str(fk)] = r
    return out


def _points(rec: Optional[dict]) -> Tuple[int, bool]:
    if not rec:
        return 0, True
    try:
        pts = float(rec.get("score_impact") or 0)
    except (TypeError, ValueError):
        return 0, True
    if pts <= 0:
        return 0, True
    exact = rec.get("impact_is_exact")
    exact = exact is True or str(exact).lower() == "true"
    return int(round(pts)), exact


# A Please verify value counts at half weight in the package's Form Fill Rate
# until a person confirms or corrects it (13 Oct 2026). One row moves the score
# by a fraction of a point, so no number is printed - but it is not "no effect".
VERIFY_SCORE_TEXT = "Counts in full once you confirm it"


def score_text(points: int, exact: bool) -> str:
    if not points:
        return "No score effect"
    return f"+{points} pts" if exact else f"Up to +{points} pts"


def _answer_mode(fact_key: Optional[str], facts: dict) -> str:
    if not fact_key:
        return "none"
    try:
        from services.answer_routing import answer_mode
        return str((answer_mode(fact_key, facts) or {}).get("mode") or "none")
    except Exception:                                      # pragma: no cover
        return "none"


# ── Why a value was held back, in plain words ────────────────────────────────

_INSURER_WORDS = re.compile(
    r"\b(?:insurance|mutual|casualty|assurance|indemnity|underwriters|reinsurance)\b",
    re.IGNORECASE,
)
_PARTY_FACTS: Tuple[Tuple[str, str], ...] = (
    ("applicant_name", "the applicant's name"),
    ("dba_name", "the applicant's trade name"),
    ("producer_name", "your agency's name"),
    ("carrier_name", "the insurance company's name"),
    # Your own agency contact, from your login (Orbin live run, 30 Sep 2026:
    # the AI put the producer's e-mail into the insured's contact boxes).
    ("producer_contact_email", "your agency's contact e-mail"),
    ("producer_contact_phone", "your agency's contact phone"),
    ("producer_contact_name", "your agency's contact"),
)
# A date in any shape a document prints - numbers ("03/01/2022", "2022-03-01")
# or words ("March 1, 2022", "1 Mar 2022"). Only the "which is not a date"
# sentence reads it: on the owner's run `18ecbfa8` (12 Oct 2026) a held-back
# "March 1, 2022" was explained to the producer as "not a date".
_MONTH_WORD = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|"
               r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?")
_DATE_SHAPE = re.compile(
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b"
    rf"|\b{_MONTH_WORD}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b"
    rf"|\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH_WORD},?\s+\d{{4}}\b",
    re.I)
_NORM = re.compile(r"[^a-z0-9]")


def _fact_text(facts: dict, key: str) -> str:
    v = (facts or {}).get(key)
    if isinstance(v, dict):
        v = v.get("value")
    return "" if v is None or isinstance(v, (list, dict)) else str(v)


_ACRONYMS = {"gl": "GL", "naics": "NAICS", "sic": "SIC", "fein": "FEIN", "naic": "NAIC",
              "wc": "WC", "dba": "DBA", "llc": "LLC", "um": "UM", "uim": "UIM"}


def _humanize_fact(fact_key: str) -> str:
    """A fact's name in the producer's words. A capture table has its own
    label ("Vehicle schedule"); the raw key read as "auto vin schedule" in the
    review (owner, 30 Sep 2026)."""
    try:
        from services.schedule_capture import get_def
        sched = get_def(str(fact_key))
        if sched and sched.get("label"):
            return str(sched["label"]).strip().lower()
    except Exception:                                      # pragma: no cover
        pass
    return " ".join(_ACRONYMS.get(t, t) for t in str(fact_key).split("_") if t)


_DEC_LABEL_MAX = 50


def _dec_label_for(key: str, facts: dict) -> Optional[str]:
    """The label the declarations print beside this exact value, if any."""
    for e in (facts or {}).get("dec_page_entries") or []:
        if not isinstance(e, dict) or not e.get("label"):
            continue
        # A LABEL, not a sentence: an entry whose "label" is a whole clause
        # ("A $100 MINIMUM POLICY PREMIUM APPLIES IF ...") names nothing.
        if len(str(e["label"]).strip()) > _DEC_LABEL_MAX:
            continue
        if _NORM.sub("", str(e.get("value") or "").lower()) == key:
            where = str(e.get("section") or "").strip()
            label = f'"{str(e["label"]).strip()}"'
            return f"{label} ({where})" if where else label
    return None


def _fact_holding(key: str, facts: dict, exclude: Optional[str] = None) -> Optional[str]:
    """The first other fact whose value (or one of whose rows) is exactly this
    value - the thing the refused value actually was."""
    def _hit(v: Any) -> bool:
        if isinstance(v, dict):
            if "value" in v and not isinstance(v.get("value"), (dict, list)):
                return _NORM.sub("", str(v.get("value") or "").lower()) == key
            return any(_hit(x) for x in v.values())
        if isinstance(v, list):
            return any(_hit(x) for x in v)
        return v is not None and _NORM.sub("", str(v).lower()) == key
    for fk, v in (facts or {}).items():
        if fk.startswith("_") or fk == exclude or fk == "dec_page_entries":
            continue
        if _hit(v):
            return _humanize_fact(fk)
    return None


def _snippet(value: Any, limit: int = 60) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


_NOT_IN_DOCUMENTS = ("The AI filled this box, but that value is not in your documents, "
                     "so it was left blank.")
_NOT_MATCHED = ("The AI filled this box, but its value could not be matched to your "
                "documents, so it was left blank.")
# A Yes/No question the documents do not answer (1 Oct 2026, Michelle's item 9).
# The refused answer is never repeated: 'The AI answered "Yes"' on sexual-abuse
# claims or radioactive materials, read aloud to a client, says the AI invented a
# damaging answer - and the answer was refused precisely because nothing says so.
_QUESTION_UNANSWERED = ("Your documents do not answer this question, so it was "
                        "left for you to answer.")
_QUESTION_PART_UNANSWERED = ("Your documents do not answer the question this box "
                             "belongs to, so it was left blank.")
_TICK_UNANSWERED = ("Your documents do not say whether this applies, so it was "
                    "left for you to tick.")
_YES_NO_IN_A_TEXT_BOX = ("The AI gave a Yes/No answer here, but this box asks for "
                         "something else, so it was left blank.")
_POLICY_WORDING = ("The AI put policy wording here, not an answer for this box, "
                   "so it was left blank.")
_AN_INSURER = ("The AI put an insurance company's name here, which does not belong "
               "in this box, so it was left blank.")


def _is_identifier_box(schema: dict, field: str) -> bool:
    """A box whose value is an identifier or a code (FEIN, SIC, NAICS, a policy
    or licence number): a value the AI invented for it must never be shown as
    if it were real - it invites a producer to copy a fake FEIN onto the form."""
    return _tooltip(schema, field).lower().startswith(("enter identifier", "enter code"))


def held_back(schema: dict, field: str, removed: Any, facts: dict,
              kind: Optional[str] = None,
              in_documents: Optional[bool] = None,
              reason: Optional[str] = None) -> Tuple[str, bool]:
    """(reason, quotable): one plain sentence, and whether the refused value
    may be shown beside it. Guards do not record WHICH rule fired, so this
    reads the refused value against the box and never claims more than it can
    see; the fallback says exactly what is known.

    Two rules decide what is QUOTED (1 Oct 2026, Michelle's item 9):

    * A refused Yes/No answer is never repeated. The documents do not answer
      the question, so it is left for the producer - that is the whole finding.
    * A value that belongs to a DIFFERENT item (another party's name, a value
      the declarations print under another label, a value our records hold as
      another fact, policy wording, an insurer's name) is described, never
      quoted: 'Found "7383". Your documents print it as "PRIV PASSENGER - COMM
      CLASS"' read as "we found your SIC code and hid it".

    Only a value that may really be this box's - one that just could not be
    confirmed - is quoted, as the documents' printing when they hold it
    (`in_documents`, the guard report's own check) and as the AI's suggestion
    otherwise. An identifier or code with no such check is never quoted (an
    invented FEIN invites a producer to copy it)."""
    try:
        from services.normalization import canonical_yes_no
    except Exception:                                      # pragma: no cover
        canonical_yes_no = lambda _v: None                 # noqa: E731
    text = str(removed or "").strip()
    # A bare number is a count, not a Yes/No ("1" read as "Yes" on a years box).
    yn = None if text.replace(".", "", 1).isdigit() else canonical_yes_no(text)
    if is_question_box(schema, field):
        return _QUESTION_UNANSWERED, False
    if kind == "unanswered":
        return _QUESTION_PART_UNANSWERED, False
    if _field_type(schema, field) == "/Btn":
        return _TICK_UNANSWERED, False
    if yn is not None:
        return _YES_NO_IN_A_TEXT_BOX, False
    # A guard that NAMED its rule says why in its own words (round 5, 7 Oct
    # 2026: a cross-reference, a party's name, an echo, a form title, the
    # tooltip's option list - `reason` is the guard report's own code). The
    # refused value is never quoted: it is not this box's value at all.
    if reason:
        try:
            from services.ai_answer_guards import held_back_sentence
            own = held_back_sentence(reason)
        except Exception:                                  # pragma: no cover
            own = None
        if not own:
            # Another policy's value, a coverage the documents do not carry
            # (services/scoped_evidence, round 5).
            try:
                from services.scoped_evidence import held_back_text
                own = held_back_text(reason)
            except Exception:                              # pragma: no cover
                own = None
        if own:
            return own, False
    key = _NORM.sub("", text.lower())
    # Our own records first: a value that IS another party's (the applicant's
    # name, your agency's e-mail) is named as that, wherever it came from.
    if key:
        for fact_key, who in _PARTY_FACTS:
            fv = _NORM.sub("", _fact_text(facts, fact_key).lower())
            if fv and fv == key:
                return (f"The AI put {who} here, which does not belong in this box, "
                        "so it was left blank."), False
    printed_as = _dec_label_for(key, facts) if len(key) >= 3 else None
    if printed_as:
        return (f"The AI tried a value your documents print as {printed_as}, a different "
                "item, so it was left blank."), False
    # A value our own records hold (a GL class code refused from the SIC box)
    # is real, whatever the text check says: name what it really is.
    other = (_fact_holding(key, facts, exclude=box_fact_key(field))
             if key and len(key) >= 3 else None)
    if other:
        return (f"The AI tried a value from the {other}, a different item, so it was "
                "left blank."), False
    if in_documents is False:
        return _NOT_IN_DOCUMENTS, False
    if not in_documents and _is_identifier_box(schema, field):
        return _NOT_MATCHED, False
    if len(text) >= 90 or len(text.split()) >= 14:
        return _POLICY_WORDING, False
    if _INSURER_WORDS.search(text):
        return _AN_INSURER, False
    said = (f'Your documents print "{_snippet(text)}"' if in_documents
            else f'The AI suggested "{_snippet(text)}"')
    declared = _tooltip(schema, field).lower()
    if declared.startswith("enter date") and not _DATE_SHAPE.search(text):
        return f"{said}, which is not a date, so it was left for you to enter.", True
    if declared.startswith(("enter number", "enter amount", "enter limit", "enter percentage",
                            "enter year", "enter deductible", "enter rate")) \
            and not re.search(r"\d", text):
        return f"{said}, which is not a number, so it was left for you to enter.", True
    return (f"{said}, but it could not be confirmed for this box, so it was left blank "
            "rather than print a possibly wrong value."), True


def held_back_reason(schema: dict, field: str, removed: Any, facts: dict,
                     kind: Optional[str] = None,
                     in_documents: Optional[bool] = None,
                     reason: Optional[str] = None) -> str:
    """The sentence of `held_back` (the E&O / field-QA rows use it)."""
    return held_back(schema, field, removed, facts, kind, in_documents, reason=reason)[0]


# ── "Please verify": a reason that is true ───────────────────────────────────

def document_haystack(docs: Any) -> Optional[str]:
    """The uploaded documents' text folded for presence checks, exactly as the
    stamper folds it (`pdf_service._normalize_for_search`), padded with a space
    each side. `docs` is the session's document list or one text. None when
    there is no text."""
    if isinstance(docs, str):
        text = docs
    elif isinstance(docs, (list, tuple)):
        text = "\n".join(str((d or {}).get("text") or "") for d in docs if isinstance(d, dict))
    else:
        return None
    if not text.strip():
        return None
    try:
        from services.pdf_service import _normalize_for_search
        # Padded once, so a whole-word check needs no copy per box.
        return f" {_normalize_for_search(text)} "
    except Exception:                                      # pragma: no cover
        return None


_VERIFY_ANSWER = "Answered by the AI. Confirm it against your documents."
_VERIFY_NO_TEXT = "Filled by the AI. Check it against your documents."
_VERIFY_NOT_PRINTED = "Filled by the AI, but not found word for word in your documents."
_VERIFY_PRINTED = ("Your documents print this value, but the AI could not confirm it "
                   "belongs in this box.")
_VERIFY_WRONG_PARTY = ("Your documents print this name, but it reads like an insurance "
                       "company or policy, which this box does not usually hold.")
# A value Primble CALCULATED (the next policy term after an ended declarations
# term, an expiration one term after a typed effective date) - never the AI's,
# and never "not found" as if something had gone wrong (1 Oct 2026, item 4).
_VERIFY_CALCULATED = "Calculated, not read from your documents. Confirm it before sending."
# An AI value the stamper FOUND in the documents ("ai_verified", 13 Oct 2026):
# printed there, but placed in this box by the AI - a person confirms the fit.
_VERIFY_FOUND = "Filled by the AI from your documents. Confirm it belongs in this box."


def _documents_print(value: Any, haystack: Optional[str]) -> Optional[bool]:
    """True / False when the documents do / do not print `value` word for word;
    None when it cannot be told - no text, or a value too short to mean
    anything by its presence ("CO", "20", "Y")."""
    if haystack is None:
        return None
    try:
        from services.pdf_service import _VERIFY_SKIP_TOKENS, _normalize_for_search
    except Exception:                                      # pragma: no cover
        return None
    raw = str(value or "").strip()
    if not raw or raw.lower() in _VERIFY_SKIP_TOKENS:
        return None
    needle = _normalize_for_search(raw)
    if len(needle.replace(" ", "")) < 4:
        return None
    return f" {needle} " in haystack


def verify_reason(schema: dict, field: str, value: Any, facts: Optional[dict],
                  haystack: Optional[str], form_id: Optional[str] = None) -> str:
    """Why a filled box is "Please verify", in words that are TRUE of it
    (1 Oct 2026). Every such row read "not found word for word in your
    documents", also beside a co-owner name the documents print 21 times. The
    label means the stamper could not confirm the value for the box - it was
    not found, or it was found and reads like the wrong kind of value, or it is
    an answer, which presence cannot confirm."""
    try:
        from services.normalization import canonical_yes_no
    except Exception:                                      # pragma: no cover
        canonical_yes_no = lambda _v: None                 # noqa: E731
    text = str(value or "").strip()
    if (is_question_box(schema, field) or _field_type(schema, field) == "/Btn"
            or (not text.replace(".", "", 1).isdigit() and canonical_yes_no(text) is not None)):
        return _VERIFY_ANSWER
    try:
        from services.pdf_service import prints_a_calculated_value
        if prints_a_calculated_value(form_id or "", field, text, facts or {}):
            return _VERIFY_CALCULATED
    except Exception:                                      # pragma: no cover
        pass
    printed = _documents_print(text, haystack)
    if printed is None:
        return _VERIFY_NO_TEXT
    if not printed:
        return _VERIFY_NOT_PRINTED
    try:
        from services.field_mapping_integrity import is_value_contaminated
        if is_value_contaminated(field, text, facts or {}):
            return _VERIFY_WRONG_PARTY
    except Exception:                                      # pragma: no cover
        pass
    return _VERIFY_PRINTED


# ── The applicant's own boxes ────────────────────────────────────────────────

def _is_producer_signature(field: str, tooltip: str, field_type: str = "") -> bool:
    try:
        from services.signature_boxes import is_producer_signature
        return is_producer_signature(field, tooltip, field_type)
    except Exception:                                      # pragma: no cover
        return False


def _is_applicant_step(field: str, tooltip: str) -> bool:
    try:
        from services.signature_boxes import is_applicant_step
        return is_applicant_step(field, tooltip)
    except Exception:                                      # pragma: no cover
        return False


def _signature_kind(field: str, tooltip: str) -> Optional[str]:
    try:
        from services.signature_boxes import signature_box
        box = signature_box(field, tooltip)
        return box[0] if box else None
    except Exception:                                      # pragma: no cover
        return None


# The form changed after the applicant signed it (Orbin item 14).
APPLICANT_SIGNATURE_STALE = "Signature no longer matches - send for signature again."

_APPLICANT_WHAT: Dict[Optional[str], str] = {
    "signature": "The applicant signs here before the form is sent.",
    "date": "The applicant dates this when signing.",
    "initials": "The applicant initials here when signing, if it applies.",
    None: "The applicant completes this when signing.",
}


# ── The door ──────────────────────────────────────────────────────────────────

def effective_labels(form_id: str, generated_form: dict, facts: dict) -> Dict[str, str]:
    """The labels the viewer paints - the same re-derivation the fields
    endpoint (`form_routes.get_form_fields`) runs on read."""
    fr = generated_form or {}
    mapped = fr.get("field_state") or fr.get("mapped") or {}
    labels = dict(fr.get("confidence") or {})
    try:
        from services.pdf_service import (
            apply_acord125_missing_field_highlights,
            apply_acord126_missing_field_highlights,
        )
        labels = apply_acord125_missing_field_highlights(form_id, facts or {}, mapped, labels)
        labels = apply_acord126_missing_field_highlights(form_id, facts or {}, mapped, labels)
    except Exception as exc:                               # noqa: BLE001
        logger.warning("needs_attention: highlight re-derivation skipped (%s) - %s", form_id, exc)
    return labels


def _row_is_unused(field: str, mapped: dict) -> bool:
    """Row B..N of a repeating section with nothing in ANY box of that row
    (same leading name segment, same row letter): a second named insured or
    a fourth premises the form does not have. A value refused there is not a
    thing to look up - the row does not exist."""
    m = _ROW_RE.match(field or "")
    if not m or m.group("row") == "A":
        return False
    root = field.split("_", 1)[0] + "_"
    suffix = "_" + m.group("row")
    for f, v in (mapped or {}).items():
        if f.startswith(root) and f.endswith(suffix) and _has_value(v):
            return False
    return True


def _unanswered_high_impact_question_test(form_id: str, schema: dict, mapped: dict,
                                          labels: dict, facts: Optional[dict],
                                          flags: Optional[dict]):
    """A predicate: is this empty box a high-impact QUESTION the AI was asked
    and left unanswered? Built once per form. Fails closed (never lists)."""
    try:
        from services.field_mapping_integrity import is_high_impact_field
        from services.field_qa import _spare_row_of_an_answered_group
        from services.pdf_service import _is_nonfillable_field, _owned_blank_claim, _schema_context
    except Exception:                                      # pragma: no cover
        return lambda _f: False
    owned_facts = {**(facts or {}), **(flags or {}), "_form_id": form_id}

    def test(field: str) -> bool:
        try:
            if labels.get(field) != "low_confidence" or _has_value(mapped.get(field)):
                return False
            if not is_question_box(schema, field) or _is_nonfillable_field(field):
                return False
            if not is_high_impact_field(field, _tooltip(schema, field) or None):
                return False
            if _spare_row_of_an_answered_group(field, mapped):
                return False
            with _schema_context(schema):
                return not bool(_owned_blank_claim(field, owned_facts))
        except Exception:                                  # noqa: BLE001
            return False
    return test


def _unanswered_high_impact_box_test(form_id: str, schema: dict, mapped: dict,
                                     labels: dict, facts: Optional[dict],
                                     flags: Optional[dict]):
    """A predicate: is this empty box a high-impact BOX (not a question) the AI
    was asked and left blank - the `field_qa` "high-impact box the AI left
    blank" finding (Figure 33), read with field QA's own tests: an empty box
    labelled low_confidence, high-impact by `is_high_impact_field`, not an
    explanation box (it follows its question), not an unticked option, not a
    spare row of an answered section, no resolver owns the blank. Built once
    per form. Fails closed (never lists)."""
    try:
        from services.field_mapping_integrity import is_high_impact_field
        from services.field_qa import _is_explanation_box, _spare_row_of_an_answered_group
        from services.pdf_service import _is_nonfillable_field, _owned_blank_claim, _schema_context
    except Exception:                                      # pragma: no cover
        return lambda _f: False
    owned_facts = {**(facts or {}), **(flags or {}), "_form_id": form_id}

    def test(field: str) -> bool:
        try:
            if labels.get(field) != "low_confidence" or _has_value(mapped.get(field)):
                return False
            if is_question_box(schema, field) or _is_nonfillable_field(field):
                return False
            if _field_type(schema, field) == "/Btn":
                return False                               # an unticked option
            tip = _tooltip(schema, field) or None
            if not is_high_impact_field(field, tip) or _is_explanation_box(field, tip):
                return False
            if _spare_row_of_an_answered_group(field, mapped):
                return False
            with _schema_context(schema):
                return not bool(_owned_blank_claim(field, owned_facts))
        except Exception:                                  # noqa: BLE001
            return False
    return test


# The side panel's words for the findings that used to surface only at
# download (Figure 33; owner, 14 Oct 2026: shown here first, then the review).
HIGH_IMPACT_BLANK_REASON = "A high-impact box the AI left blank: no value was found in your documents."
HIGH_IMPACT_BLANK_WHAT = "Enter it on the form if it applies."
FINDING_WHAT = "Check it against your documents and correct it on the form if it is wrong."
FINDING_HIGH_IMPACT_BLANK = "high_impact_blank"
FINDING_VALUE_MISMATCH = "value_mismatch"
FINDING_NOT_THE_INSURED = "not_the_insured"


def needs_attention(generated_form: Optional[dict], facts: Optional[dict], form_id: str,
                    *, flags: Optional[dict] = None,
                    package_sqs: Optional[dict] = None,
                    doc_haystack: Optional[str] = None,
                    hard_blocks: Optional[List[dict]] = None,
                    findings: Optional[dict] = None) -> List[dict]:
    """Rows for ONE generated form, in the order the form prints its boxes.

    Each row: form_id, form_label, field, page (1-based, None if the template
    has no widget for it), label, status, tag, required, reason, what_to_do,
    value / found_value, score_effect, score_effect_exact, score_text,
    fact_key, answer_mode, applicant_step (and `blocks_download` on a box the
    download gate holds).

    `doc_haystack`: the uploaded documents' text, folded by
    `document_haystack` - lets a "Please verify" reason say whether the
    documents print the value. Without it the reason claims nothing about them.

    `hard_blocks`: this form's download-gate findings (`hard_block_findings`).
    Each box is listed so the side panel shows it BEFORE the download review
    does (owner, 14 Oct 2026: the download screen lists only what the producer
    has already seen). None = not asked for (every caller but the
    needs-attention route) - the rows are exactly as before.

    `findings`: the Figure 33 findings the review used to show first, for this
    form (`review_findings_for_form`) - {"high_impact_boxes": bool, "values":
    [{field, finding, reason}]}. A box already listed keeps its one row (its
    reason becomes the finding's); None = not asked for, rows as before.
    """
    fr = generated_form or {}
    # A form's second copy (ACORD 131 for the excess layer, 7 Oct 2026) is
    # judged on its own view of the facts by its form's rules; rows keep its id.
    from services.form_instances import base_form_id, facts_for_form
    _base = base_form_id(form_id)
    facts = facts_for_form(facts or {}, form_id)
    mapped = fr.get("field_state") or fr.get("mapped") or {}
    schema = fr.get("schema") if isinstance(fr.get("schema"), dict) and fr.get("schema") \
        else _schema_from_disk(form_id)
    labels = effective_labels(_base, fr, facts)
    positions = widget_positions(form_id, fr)
    client_filled = set(fr.get("client_filled_fields") or [])
    # What generation stamped. An edit is saved into `field_state` and keeps the
    # box's old label on purpose (its highlight persists), so a box whose value
    # now differs from generation's was typed by a person: never "the AI filled
    # it" and never "held back" (review, 30 Sep).
    generated_values = fr.get("mapped") if isinstance(fr.get("field_state"), dict) else None

    def _edited(field: str) -> bool:
        if not isinstance(generated_values, dict):
            return False
        return str(mapped.get(field) or "").strip() != str(generated_values.get(field) or "").strip()

    # A signed form no longer needs the PRODUCER's signature boxes
    # (apply-signature stores them blank and sets `signature_applied`).
    signed = bool(fr.get("signature_applied"))
    # The applicant's signature (Orbin item 14): "signed" while the form still
    # holds what they signed - their signature and date are done; "stale" once a
    # value changed - the rows stay and say to send for signature again.
    try:
        from services.signature_boxes import applicant_signature_state
        applicant_state = applicant_signature_state(fr, mapped)
    except Exception:                                      # pragma: no cover
        applicant_state = None

    try:
        from services.field_qa import _printed_value_keys, _is_printed_copy
        printed = _printed_value_keys(fr)
    except Exception:                                      # pragma: no cover
        printed, _is_printed_copy = {}, (lambda *_a: False)

    guard: Dict[str, dict] = {}
    for gb in fr.get("guard_blanks") or []:
        if isinstance(gb, dict) and gb.get("field") and gb["field"] not in guard:
            guard[str(gb["field"])] = gb

    # High-impact QUESTIONS the documents do not answer (Figure 33; Michelle's
    # item 19: they surfaced only at download, under internal names). The same
    # tests the download review uses (`field_qa.run_field_qa` "not_answered"):
    # the AI was asked (an empty box labelled low_confidence), no resolver owns
    # the blank, it is not a spare row, and no guard refused an answer.
    _unanswered_question = _unanswered_high_impact_question_test(_base, schema, mapped, labels,
                                                                facts, flags)
    # ...and, asked for by the side panel only, high-impact BOXES (Figure 33).
    _unanswered_box = (_unanswered_high_impact_box_test(_base, schema, mapped, labels, facts, flags)
                       if (findings or {}).get("high_impact_boxes") else None)

    sqs = fr.get("sqs") or {}
    recs = _recs_by_fact(sqs.get("recommendations"),
                         (package_sqs or {}).get("recommendations"),
                         (package_sqs or {}).get("top_recommendations"))

    universe = set(labels) | set(mapped) | set(guard)
    universe |= {f for f in VIEWER_ALWAYS_REQUIRED if f in schema or f in positions}

    def _print_order(f: str):
        pos = positions.get(f)
        return ((pos[0], -pos[1], pos[2]) if pos else (9999, 0.0, 0.0), f)

    rows: List[dict] = []
    seen_questions: set = set()
    # Print order, so the FIRST box of a Yes/No pair is the one kept and jumped to.
    for field in sorted(universe, key=_print_order):
        value = mapped.get(field)
        label = labels.get(field)
        if field in client_filled or label == "client_arq":
            continue                                       # the client answered it
        tip = _tooltip(schema, field)
        if signed and _is_producer_signature(field, tip, _field_type(schema, field)):
            continue                                       # the producer signed it
        # The applicant's signature, its date, their initials (1 Oct 2026): the
        # applicant's step before the form is sent - never a value the AI held
        # back, never the producer's to fill in. The Sign button signs for the
        # producer only, so a signed form still lists them.
        applicant_step = _is_applicant_step(field, tip)
        if (applicant_step and applicant_state == "signed"
                and _signature_kind(field, tip) in ("signature", "date")):
            continue                                       # the applicant signed it
        status = reason = None
        found = None
        required = label in _REQUIRED_LABELS or field in VIEWER_ALWAYS_REQUIRED
        if _has_value(value):
            if label in CONFIRMABLE_LABELS and not _edited(field) \
                    and str(value).strip() not in _UNTICKED:
                status = STATUS_VERIFY
        else:
            gb = None if applicant_step else guard.get(field)
            held = False
            if gb is not None:
                kind = gb.get("kind")
                removed = gb.get("removed_value")
                if kind == "unanswered":
                    held = is_question_box(schema, field)
                else:
                    held = not _is_printed_copy(removed, field, printed)
                if held and _row_is_unused(field, mapped):
                    held = False
                if held:
                    status = STATUS_HELD_BACK
                    reason, quotable = held_back(schema, field, removed, facts, kind,
                                                 gb.get("in_documents"),
                                                 reason=gb.get("reason"))
                    # A value the reason does not repeat is not shipped either.
                    found = str(removed or "") if quotable else None
            if status is None and required:
                status = STATUS_MISSING
            if status is None and gb is None and _unanswered_question(field):
                status = STATUS_MISSING
                reason = "UNANSWERED"
            elif (status is None and gb is None and not applicant_step
                  and _unanswered_box is not None and _unanswered_box(field)):
                status = STATUS_MISSING
                reason = "UNANSWERED_BOX"
        if status is None:
            continue

        text = box_label(schema, field)
        unanswered_q = status == STATUS_MISSING and reason == "UNANSWERED"
        if (status == STATUS_HELD_BACK or unanswered_q) and is_question_box(schema, field):
            # A Yes/No checkbox PAIR is one question: list it once.
            m = _ROW_RE.match(field)
            qkey = (text.lower(), m.group("row") if m else "")
            if qkey in seen_questions:
                continue
            seen_questions.add(qkey)
        text = _trim(text + _row_suffix(schema, field), _LABEL_MAX + 10)

        is_box = _field_type(schema, field) == "/Btn"
        unanswered_box = status == STATUS_MISSING and reason == "UNANSWERED_BOX"
        if unanswered_q:
            what = "Answer it on the form if it applies."
            reason = "An underwriting question your documents do not answer."
        elif unanswered_box:
            what = HIGH_IMPACT_BLANK_WHAT
            reason = HIGH_IMPACT_BLANK_REASON
        elif status == STATUS_MISSING:
            if applicant_step and applicant_state == "stale" and _signature_kind(field, tip) in ("signature", "date"):
                what = APPLICANT_SIGNATURE_STALE
            elif applicant_step:
                what = _APPLICANT_WHAT.get(_signature_kind(field, tip), _APPLICANT_WHAT[None])
            elif is_box:
                what = "Tick it on the form if it applies."
            else:
                what = "Enter it on the form."
            reason = "Required on this form and still empty."
            _m = _ROW_RE.match(field)
            _choice = _ACORD125_CHOICE_ROWS.get(_m.group("base")) if (_m and _base == "ACORD_125") else None
            if _choice:
                text = _trim(_choice + _row_suffix(schema, field), _LABEL_MAX + 10)
                what = "Tick the one that applies."
                reason = "Required on this form and none is ticked yet."
        elif status == STATUS_HELD_BACK:
            what = ("Answer it on the form if it applies." if is_question_box(schema, field)
                    else "Check your documents and enter the right value if there is one.")
        else:
            what = "Check it against your documents and correct it on the form if it is wrong."
            reason = (_VERIFY_FOUND if label == "ai_verified"
                      else verify_reason(schema, field, value, facts, doc_haystack, _base))

        fact_key = box_fact_key(field)
        pts, exact = (0, True) if status == STATUS_VERIFY else _points(recs.get(fact_key or ""))
        pos = positions.get(field)
        rows.append({
            "form_id": form_id,
            "form_label": form_label(form_id),
            "field": field,
            "page": pos[0] if pos else None,
            "label": text,
            "status": status,
            "tag": STATUS_TAG[status],
            "required": bool(required),
            "reason": reason,
            "what_to_do": what,
            "value": str(value) if status == STATUS_VERIFY else None,
            "found_value": _snippet(found, 160) if found is not None else None,
            "score_effect": pts,
            "score_effect_exact": bool(exact),
            "score_text": VERIFY_SCORE_TEXT if status == STATUS_VERIFY else score_text(pts, exact),
            "fact_key": fact_key,
            "fold_keys": box_fold_keys(field),
            "answer_mode": _answer_mode(fact_key, facts),
            "applicant_step": bool(applicant_step and status == STATUS_MISSING),
            **({"finding": FINDING_HIGH_IMPACT_BLANK} if unanswered_box else {}),
            "_sort": _print_order(field),
        })

    # ── Items 8 / 11 (30 Sep 2026): a TICKED line with no premium ────────────
    # Michelle: "premiums did not attach. Nor was there a prompt to fulfill the
    # missing data." A premium the documents state is printed; one they do not
    # is the producer's to enter, and nothing said so. Each line of business
    # the form ticks whose own premium box is blank - and the POLICY PREMIUM
    # total beside them - is listed here, where the producer already looks,
    # with the jump to the box. Nothing is filled or guessed. A to-do for the
    # producer, never a gap the underwriter's cover page reports: a quote's
    # premium is blank until it is quoted.
    # A dec renewal's page-1 premiums are blank BY RULE (Brent, 8 Oct 2026:
    # "Leave the page 1 premium blank unless the appropriate premium is
    # provided") - not a producer's to-do. The owner's run `18ecbfa8` (12 Oct)
    # counted 8 of them into "49 items to fix". Same test the stamper uses.
    listed = {r["field"] for r in rows}
    for field, why in ([] if _page_one_premiums_withheld(facts) else
                       _blank_premium_boxes(schema, mapped)):
        if field in listed or field in client_filled:
            continue
        pos = positions.get(field)
        rows.append({
            "form_id": form_id,
            "form_label": form_label(form_id),
            "field": field,
            "page": pos[0] if pos else None,
            "label": _trim(box_label(schema, field), _LABEL_MAX + 10),
            "status": STATUS_MISSING,
            "tag": STATUS_TAG[STATUS_MISSING],
            "required": False,
            "reason": why,
            "what_to_do": "Enter it on the form if you know it.",
            "value": None,
            "found_value": None,
            "score_effect": 0,
            "score_effect_exact": True,
            "score_text": score_text(0, True),
            "fact_key": None,
            "answer_mode": "none",
            "producer_todo": True,
            "_sort": _print_order(field),
        })

    # MORE THAN ONE LANDLORD (Brent, 8 Oct 2026): "The first can go under
    # Additional Interest on the 125. Additional landlords go on ACORD 45." The
    # 125 prints the first location's landlord; the rest are a producer to-do -
    # Primble does not produce ACORD 45.
    if _base == "ACORD_125":
        extra = _landlords_for_acord45(facts)
        anchor = "AdditionalInterest_FullName_A"
        if extra and anchor not in listed:
            pos = positions.get(anchor)
            rows.append({
                "form_id": form_id,
                "form_label": form_label(form_id),
                "field": anchor,
                "page": pos[0] if pos else None,
                "label": "Additional landlords (ACORD 45)",
                "status": STATUS_MISSING,
                "tag": STATUS_TAG[STATUS_MISSING],
                "required": False,
                "reason": ("ACORD 125 has room for one landlord, so the first is printed here. "
                           + "; ".join(extra) + " - list them on an ACORD 45, which Primble "
                           "does not produce."),
                "what_to_do": "Attach an ACORD 45 for these landlords.",
                "value": None,
                "found_value": None,
                "score_effect": 0,
                "score_effect_exact": True,
                "score_text": score_text(0, True),
                "fact_key": None,
                "answer_mode": "none",
                "producer_todo": True,
                "_sort": _print_order(anchor),
            })

    if (findings or {}).get("values"):
        rows = _with_value_findings(rows, findings["values"], schema=schema, form_id=form_id,
                                    positions=positions, print_order=_print_order,
                                    labels=labels, mapped=mapped, client_filled=client_filled,
                                    facts=facts)

    if hard_blocks:
        rows = _with_hard_block_rows(rows, hard_blocks, schema=schema, form_id=form_id,
                                     positions=positions, print_order=_print_order,
                                     recs=recs, facts=facts)

    if _base == "ACORD_125":
        rows = _collapse_tick_groups(rows)
    rows.sort(key=lambda r: (STATUS_ORDER.index(r["status"]), r["_sort"]))
    for r in rows:
        r.pop("_sort", None)
    return rows


# ACORD 125's POLICY PREMIUM box (the package total beside the line premiums).
_TOTAL_PREMIUM_BOX = "Policy_Payment_EstimatedTotalAmount_A"


def _is_ticked(value: Any) -> bool:
    if value is True:
        return True
    return str(value or "").strip().lower() in ("yes", "y", "true", "1", "x", "on", "/1", "/yes")


def _page_one_premiums_withheld(facts: Optional[dict]) -> bool:
    """ACORD 125's page-1 premiums are left blank on purpose - the stamper's own
    test (`pdf_service._page_one_current_policy`: a dec renewal's expiring
    premiums, unless a person entered one). Fails toward listing them."""
    try:
        from services.pdf_service import _page_one_current_policy
        return bool(_page_one_current_policy({**(facts or {}), "_form_id": "ACORD_125"},
                                             "premium_is_current_policy", "total_policy_premium"))
    except Exception:                                      # noqa: BLE001
        return False


def _blank_premium_boxes(schema: dict, mapped: dict) -> List[Tuple[str, str]]:
    """(box, why) for each premium the form should show and does not: a TICKED
    line of business's own premium box, then the total beside them. Forms with
    no line-of-business premiums (everything but ACORD 125) give nothing."""
    try:
        from services.pdf_service import lob_premium_box_pairs
        pairs = lob_premium_box_pairs(schema)
    except Exception:                                      # noqa: BLE001
        return []
    ticked = [box for box in pairs if _is_ticked((mapped or {}).get(box))]
    if not ticked:
        return []
    out = [(pairs[box], "A line of business ticked on this form has no premium.")
           for box in ticked if not _has_value((mapped or {}).get(pairs[box]))]
    if _TOTAL_PREMIUM_BOX in (schema or {}) and not _has_value((mapped or {}).get(_TOTAL_PREMIUM_BOX)):
        out.append((_TOTAL_PREMIUM_BOX,
                    "Lines of business are ticked, but the total premium is blank."))
    return out


def _landlords_for_acord45(facts: Optional[dict]) -> List[str]:
    """Every rented location's landlord AFTER the first (which ACORD 125 prints),
    as "<name> (location N)". [] with one landlord or none. Fails open."""
    try:
        from services.premises_interest import ROW_LANDLORD_NAME_KEY, located_landlords
        landlords = located_landlords(facts or {})
    except Exception:                                      # noqa: BLE001
        return []
    out: List[str] = []
    for pos, row in landlords[1:]:
        name = str((row or {}).get(ROW_LANDLORD_NAME_KEY) or "").strip()
        if name:
            loc = str((row or {}).get("location_number") or pos).strip()
            out.append(f"{name} (location {loc})")
    return out


def _collapse_tick_groups(rows: List[dict]) -> List[dict]:
    """One Missing row per ACORD 125 "tick one of these" group (see
    `_ACORD125_TICK_GROUPS`). The kept row is the group's first box in print
    order (the jump target); `box_count` records how many boxes it stands for,
    so the viewer's per-box Required badge still adds up. Fails open: an
    unreadable group set leaves the rows as they are."""
    try:
        import services.pdf_service as _ps
    except Exception:                                      # pragma: no cover
        return rows
    out = list(rows)
    for set_name, label, what in _ACORD125_TICK_GROUPS:
        members = getattr(_ps, set_name, None)
        if not members:
            continue
        grp = [r for r in out if r.get("status") == STATUS_MISSING and r.get("field") in members]
        if len(grp) < 2:
            continue
        grp.sort(key=lambda r: r["_sort"])
        keep = dict(grp[0], label=label, what_to_do=what, box_count=len(grp),
                    reason="Required on this form and none is ticked yet.")
        if any(r.get("blocks_download") for r in grp):
            keep["blocks_download"] = True
        keep["fold_keys"] = sorted({k for r in grp for k in (r.get("fold_keys") or [])})
        drop = {id(r) for r in grp}
        out = [r for r in out if id(r) not in drop] + [keep]
    return out


# ── The download gate's boxes, in the side panel (owner, 14 Oct 2026) ─────────
# The download review lists only what an earlier screen showed and is still
# open. The ONE exception to dropping is the download gate itself
# (`field_qa.check_hard_block`: a placeholder value, or an ACORD 140 COPE box a
# filled sibling makes required) - it cannot be dropped, because the server
# refuses a clean download over it. Until now the side panel never listed those
# boxes (`missing_required_gate` is deliberately not a Required label, and a
# placeholder is a value), so they surfaced for the first time at download.
# Now each is a side-panel row flagged `blocks_download`; the download review
# lists it once, under Hard Stops (frontend `withoutHardStopBoxes`).

# The row's own line says it blocks the download (`blocks_download`, drawn by
# the side panel), so what to do is only what to do.
HARD_BLOCK_WHAT_TO_DO = "Enter it on the form."
_PLACEHOLDER_WHAT_TO_DO = "Enter the correct value on the form."


def _could_block(fr: Optional[dict]) -> bool:
    """True when this form can hold a download-gate finding at all - a box
    labelled `missing_required_gate` or a value that reads as a placeholder.
    A cheap superset of `field_qa.check_hard_block`, so the full check runs only
    on forms that can block (most packages: none)."""
    if not isinstance(fr, dict):
        return False
    if any(v == "missing_required_gate" for v in (fr.get("confidence") or {}).values()):
        return True
    try:
        from services.field_qa import _has_value as _qa_has_value
        from services.placeholder_detector import is_placeholder_value
    except Exception:                                      # pragma: no cover
        return True
    mapped = fr.get("field_state") or fr.get("mapped") or {}
    return any(_qa_has_value(v) and is_placeholder_value(v)[0] for v in mapped.values())


def hard_block_findings(generated_forms: Optional[dict], facts: Optional[dict],
                        form_ids: Optional[Iterable[str]] = None) -> List[dict]:
    """The findings `field_qa.check_hard_block` (the download gate) returns for
    these forms, computed the same way - read fresh from the stored forms, never
    from a stored review row.

    Cost: the gate's value-vs-source pass maps every fact onto every schema
    (`pdf_service.fact_to_form_fields`, 4-13 s on one ACORD 140). It can only
    move a finding for a gate box that HOLDS a value (an empty box is never a
    mismatch; a placeholder is judged before it), so it runs only when such a
    box exists - and then it is the gate itself, on that form. Measured equal to
    `check_hard_block` on the stored packages (tests pin it)."""
    from services.field_qa import (_HARD_BLOCK_REASON_CODES, _has_value as _qa_has_value,
                                   check_hard_block, run_field_qa)
    gen = generated_forms or {}
    wanted = set(form_ids) if form_ids is not None else None
    cand = [fid for fid, fr in gen.items()
            if (wanted is None or fid in wanted) and _could_block(fr)]
    if not cand:
        return []
    qa = run_field_qa({fid: gen[fid] for fid in cand}, merged_facts=facts or {},
                      confirmations=None, unanswered=False, mismatches=False)
    found = [r for r in (qa.get("results") or []) if r.get("reason_code") in _HARD_BLOCK_REASON_CODES]

    def _holds_value(r: dict) -> bool:
        fr = gen.get(r.get("form_id")) or {}
        mapped = fr.get("field_state") or fr.get("mapped") or {}
        return _qa_has_value(mapped.get(r.get("field")))

    exact = sorted({r.get("form_id") for r in found
                    if r.get("reason_code") == "missing_required_gate" and _holds_value(r)})
    if exact:
        found = [r for r in found if r.get("form_id") not in exact] + list(
            check_hard_block(gen, form_ids=exact, merged_facts=facts or {}))
    return found


# ── Figure 33's findings, in the side panel first (owner, 14 Oct 2026) ───────
# Field QA's value-vs-source mismatch and the field-mapping check's "a carrier
# or policy value in an insured / owner box" were listed ONLY by the download
# review. Each is now a row of the box it names, in the form's words, with its
# reason - so the producer sees it where it is fixed, and the review lists it
# through this door like every other row. A value a person typed or confirmed
# is their decision and is never flagged here.

_MISMATCH_RE = re.compile(r'shows "(?P<stamped>.*?)" but the source value is "(?P<expected>.*)"\.\s*Fix:',
                          re.DOTALL)


def _not_the_insured_reason(finding: dict) -> str:
    value = _snippet(finding.get("value"), 60)
    policy = str(finding.get("reason_code") or "").startswith("policy")
    if finding.get("matched_fact_key"):
        return (f'Shows "{value}", which matches your {"policy" if policy else "carrier"} '
                "information, not the insured or owner.")
    if policy:
        return f'Shows "{value}", which reads like a policy number, not an insured or owner name.'
    return f'Shows "{value}", which reads like an insurance company\'s name, not the insured or owner.'


def review_findings_for_form(form_id: str, generated_form: Optional[dict], facts: Optional[dict], *,
                             mismatch_rows: Optional[Iterable[dict]] = None,
                             confirmations: Optional[dict] = None) -> dict:
    """The Figure 33 findings for ONE form, as `needs_attention(findings=)`
    takes them: high-impact blank boxes (judged in the loop), carrier / policy
    values in insured or owner boxes (`field_mapping_integrity`, read live - it
    is cheap), and value-vs-source mismatches - the STORED field-QA rows of this
    form (the live check maps every fact onto every schema, 4-13 s per form),
    each kept only while its box still shows the value it was measured on."""
    fr = generated_form or {}
    mapped = fr.get("field_state") or fr.get("mapped") or {}
    values: List[dict] = []
    try:
        from services.field_mapping_integrity import detect_field_mapping_contamination
        res = detect_field_mapping_contamination({form_id: fr}, merged_facts=facts or {},
                                                 confirmations=confirmations or {})
        for f in res.get("findings") or []:
            if isinstance(f, dict) and f.get("field"):
                values.append({"field": str(f["field"]), "finding": FINDING_NOT_THE_INSURED,
                               "reason": _not_the_insured_reason(f)})
    except Exception as exc:                               # noqa: BLE001
        logger.warning("needs_attention: owner-box check skipped (%s) - %s", form_id, exc)
    for r in mismatch_rows or ():
        if not isinstance(r, dict) or not r.get("field"):
            continue
        if (r.get("component") or r.get("form_id")) != form_id:
            continue
        m = _MISMATCH_RE.search(str(r.get("message") or ""))
        if not m:
            continue
        stamped, expected = m.group("stamped"), m.group("expected")
        if _NORM.sub("", str(mapped.get(r["field"]) or "").lower()) != _NORM.sub("", stamped.lower()):
            continue                                       # the box changed since it was measured
        values.append({"field": str(r["field"]), "finding": FINDING_VALUE_MISMATCH,
                       "reason": f'Shows "{_snippet(stamped, 60)}" but the source value is '
                                 f'"{_snippet(expected, 60)}".'})
    return {"high_impact_boxes": True, "values": values}


def _with_value_findings(rows: List[dict], values: List[dict], *, schema: dict, form_id: str,
                         positions: dict, print_order, labels: dict, mapped: dict,
                         client_filled: set, facts: dict) -> List[dict]:
    """`rows` with each finding on the box it names: a box already listed keeps
    its ONE row and takes the finding's reason; otherwise the box is a "Please
    verify" row (it holds a value - Confirm keeps it as the producer's)."""
    by_field = {r["field"]: r for r in rows}
    for v in values or []:
        field = str(v.get("field") or "")
        if not field or field in client_filled or labels.get(field) in ("producer", "client_arq"):
            continue                                       # a person's own value
        value = mapped.get(field)
        if not _has_value(value) or str(value).strip() in _UNTICKED:
            continue
        row = by_field.get(field)
        if row is not None:
            if not row.get("finding"):
                row["finding"] = v.get("finding")
                row["reason"] = v.get("reason")
            continue
        label = labels.get(field)
        fact_key = box_fact_key(field)
        pos = positions.get(field)
        new = {
            "form_id": form_id,
            "form_label": form_label(form_id),
            "field": field,
            "page": pos[0] if pos else None,
            "label": _trim(box_label(schema, field) + _row_suffix(schema, field), _LABEL_MAX + 10),
            "status": STATUS_VERIFY,
            "tag": STATUS_TAG[STATUS_VERIFY],
            "required": bool(label in _REQUIRED_LABELS),
            "reason": v.get("reason"),
            "what_to_do": FINDING_WHAT,
            "value": str(value),
            "found_value": None,
            "score_effect": 0,
            "score_effect_exact": True,
            "score_text": VERIFY_SCORE_TEXT if label in CONFIRMABLE_LABELS else score_text(0, True),
            "fact_key": fact_key,
            "fold_keys": box_fold_keys(field),
            "answer_mode": _answer_mode(fact_key, facts),
            "applicant_step": False,
            "finding": v.get("finding"),
            "_sort": print_order(field),
        }
        rows.append(new)
        by_field[field] = new
    return rows


def _with_hard_block_rows(rows: List[dict], findings: List[dict], *, schema: dict, form_id: str,
                          positions: dict, print_order, recs: dict, facts: dict) -> List[dict]:
    """`rows` with every download-gate box of this form listed ONCE, flagged
    `blocks_download`. A placeholder is Missing whatever row the box had (a
    Confirm would keep the placeholder, and the gate still holds); a gate box
    already listed (a value under the gate label is "Please verify" - Confirm
    clears the gate) keeps its row and gains the flag; otherwise a Missing row
    is added."""
    by_field = {r["field"]: r for r in rows}
    for item in findings or []:
        field = str(item.get("field") or "")
        if not field or (item.get("form_id") and item.get("form_id") != form_id):
            continue
        placeholder = item.get("reason_code") == "placeholder_value"
        row = by_field.get(field)
        if row is not None and not placeholder:
            row["blocks_download"] = True
            row["required"] = True
            continue
        is_box = _field_type(schema, field) == "/Btn"
        fact_key = box_fact_key(field)
        pts, exact = _points(recs.get(fact_key or ""))
        pos = positions.get(field)
        stamped = item.get("stamped")
        new = {
            "form_id": form_id,
            "form_label": form_label(form_id),
            "field": field,
            "page": pos[0] if pos else None,
            "label": _trim(box_label(schema, field) + _row_suffix(schema, field), _LABEL_MAX + 10),
            "status": STATUS_MISSING,
            "tag": STATUS_TAG[STATUS_MISSING],
            "required": True,
            "reason": (f'Holds a placeholder ("{_snippet(stamped, 40)}"), not real data.'
                       if placeholder else
                       "Required here because another box in this section is filled."),
            "what_to_do": (_PLACEHOLDER_WHAT_TO_DO if placeholder else
                           ("Answer it on the form." if is_box else HARD_BLOCK_WHAT_TO_DO)),
            "value": None,
            "found_value": None,
            "score_effect": pts,
            "score_effect_exact": bool(exact),
            "score_text": score_text(pts, exact),
            "fact_key": fact_key,
            "fold_keys": box_fold_keys(field),
            "answer_mode": _answer_mode(fact_key, facts),
            "applicant_step": False,
            "blocks_download": True,
            "_sort": print_order(field),
        }
        if row is not None:
            rows = [r for r in rows if r is not row]
        rows.append(new)
        by_field[field] = new
    return rows


def count_rows(rows: List[dict]) -> Dict[str, int]:
    counts = {s: 0 for s in STATUS_ORDER}
    for r in rows or []:
        if r.get("status") in counts:
            counts[r["status"]] += 1
    counts["total"] = sum(counts[s] for s in STATUS_ORDER)
    return counts


def needs_attention_for_session(generated_forms: Optional[dict], facts: Optional[dict],
                                *, flags: Optional[dict] = None,
                                package_sqs: Optional[dict] = None,
                                form_ids: Optional[Iterable[str]] = None,
                                docs: Any = None,
                                hard_blocks: bool = False,
                                findings: bool = False,
                                mismatch_rows: Optional[Iterable[dict]] = None,
                                confirmations: Optional[dict] = None) -> dict:
    """{"forms": [{form_id, form_label, rows, counts}], "counts": {...}} for
    every generated form (or `form_ids`), in the order the session holds them.
    Every count is summed from the rows - never computed beside them.
    `docs`: the session's documents (or their text), read once for every form.
    `hard_blocks`: also list the download gate's boxes (`hard_block_findings`) -
    the side panel and the download review ask for them (the needs-attention
    route); the stored E&O rows, the cover and the dry run keep their own.
    `findings`: also list Figure 33's findings (`review_findings_for_form`):
    high-impact blank boxes, carrier / policy values in owner boxes, and the
    stored value mismatches in `mismatch_rows` - same callers, same reason."""
    wanted = set(form_ids) if form_ids else None
    haystack = document_haystack(docs)
    mismatch_rows = [r for r in (mismatch_rows or []) if isinstance(r, dict)]
    blocking: Dict[str, List[dict]] = {}
    if hard_blocks:
        try:
            for item in hard_block_findings(generated_forms, facts, form_ids=wanted):
                blocking.setdefault(str(item.get("form_id") or ""), []).append(item)
        except Exception as exc:                           # noqa: BLE001
            # Fails open: the download review still lists the gate's own rows.
            logger.warning("needs_attention: download-gate boxes skipped - %s", exc)
    out_forms: List[dict] = []
    total = {s: 0 for s in STATUS_ORDER}
    for fid, fr in (generated_forms or {}).items():
        if wanted is not None and fid not in wanted:
            continue
        ok = True
        try:
            found = (review_findings_for_form(fid, fr, facts, mismatch_rows=mismatch_rows,
                                              confirmations=confirmations)
                     if findings else None)
            rows = needs_attention(fr, facts, fid, flags=flags, package_sqs=package_sqs,
                                   doc_haystack=haystack, hard_blocks=blocking.get(fid),
                                   findings=found)
        except Exception as exc:                           # noqa: BLE001
            logger.warning("needs_attention: %s skipped - %s", fid, exc)
            rows, ok = [], False
        counts = count_rows(rows)
        for s in STATUS_ORDER:
            total[s] += counts[s]
        # `ok` False = this form could not be read; callers keep their own
        # findings for it rather than reporting "nothing needs attention".
        out_forms.append({"form_id": fid, "form_label": form_label(fid),
                          "rows": rows, "counts": counts, "ok": ok})
    total["total"] = sum(total[s] for s in STATUS_ORDER)
    return {"forms": out_forms, "counts": total}


# ── The pre-download record (sqs_recommendation_audit rows) ───────────────────

ATTENTION_REC_PREFIX = "fieldqa_attn_"
_WHAT_BY_STATUS = {
    STATUS_MISSING: "Fill these in on the form.",
    STATUS_HELD_BACK: "Check these against your documents and enter the right value where there is one.",
    STATUS_VERIFY: "Check each value against your documents.",
}


def is_producer_todo_row(rec_id: Optional[str]) -> bool:
    """A stored review row that is a step BEFORE SENDING, not a gap in the
    submission: "AI held back", "Please verify", the producer's own Missing
    to-dos, the applicant's signature step, and the field-mapping warnings
    ("correct it before sending the package to a carrier"). The cover page goes
    to the underwriter and lists real gaps only (owner, 30 Sep 2026; the last
    two 1 Oct 2026); these rows stay in the producer's review, checklist and
    E&O record."""
    rid = str(rec_id or "")
    try:
        from services.field_mapping_integrity import FIELD_MAPPING_REC_PREFIX
        if rid.startswith(FIELD_MAPPING_REC_PREFIX):
            return True
    except Exception:                                      # pragma: no cover
        pass
    return rid.startswith(ATTENTION_REC_PREFIX) and rid.endswith(
        ("_" + STATUS_HELD_BACK, "_" + STATUS_VERIFY, "_" + STATUS_MISSING + _TODO_SUFFIX,
         "_" + STATUS_MISSING + _APPLICANT_SUFFIX))


# Missing rows that are the producer's to enter, not a gap in the submission (a
# ticked line's blank premium - items 8 / 11) ride their own review row, so the
# cover page can leave them out.
_TODO_SUFFIX = "_producer"
# The applicant's signature, date and initials ride theirs (1 Oct 2026): they
# read "ACORD 127 - Missing (3): ... Signature of the applicant or named insured
# ... Fix: Fill these in on the form." - telling the producer, on the
# underwriter's cover, to sign for the applicant.
_APPLICANT_SUFFIX = "_applicant"
_APPLICANT_ROW_TITLE = "To be signed by the applicant"
_APPLICANT_ROW_NEXT = "The applicant signs and dates the form before it is sent."


def attention_recommendation_rows(attention: Optional[dict], shown: int = 6) -> List[dict]:
    """One advisory row per form per status, naming the form and each box by
    what the form prints - the E&O record of what the review showed. Counts
    are row counts, so "3" always means three names."""
    out: List[dict] = []
    for form in (attention or {}).get("forms") or []:
        fid = form.get("form_id") or ""
        rows = form.get("rows") or []
        for status in STATUS_ORDER:
            mine_all = [r for r in rows if r.get("status") == status]
            applicant = [r for r in mine_all if r.get("applicant_step")]
            rest = [r for r in mine_all if not r.get("applicant_step")]
            groups = [([r for r in rest if not r.get("producer_todo")], ""),
                      ([r for r in rest if r.get("producer_todo")], _TODO_SUFFIX),
                      (applicant, _APPLICANT_SUFFIX)]
            for mine, suffix in groups:
                if not mine:
                    continue
                names = [f'{r["label"]}' + (f' (p. {r["page"]})' if r.get("page") else "") for r in mine]
                listed = "; ".join(names[:shown]) + (f"; +{len(names) - shown} more" if len(names) > shown else "")
                if suffix == _APPLICANT_SUFFIX:
                    message = (f"{form_label(fid)} - {_APPLICANT_ROW_TITLE} ({len(mine)}): "
                               f"{listed}. {_APPLICANT_ROW_NEXT}")
                else:
                    message = (f"{form_label(fid)} - {STATUS_TAG[status]} ({len(mine)}): {listed}. "
                               f"Fix: {_WHAT_BY_STATUS[status]}")
                out.append({
                    "rec_id": f"{ATTENTION_REC_PREFIX}{re.sub(r'[^A-Za-z0-9]+', '_', fid)}_{status}{suffix}",
                    "message": message,
                    "type": "suggestion",
                    "field": mine[0].get("field") if len(mine) == 1 else None,
                    "component": fid,
                    "score_impact": None,
                })
    return out


# ── The download review lists only what the producer has already seen ─────────
# Brent (14 Oct 2026): "Even after everything has seemingly been addressed on
# the forms, the download modal is flooded with what appears to be new flags and
# issues that were not present prior to form selection or during form
# fulfillment." Owner's rule: the download screen shows recommendations,
# warnings and hard stops only when an EARLIER screen showed them and they are
# still open. The review reads two lists:
#   * GET /api/needs-attention - the side panel's own rows (every form) and its
#     New document choices: shown earlier by construction (the same door).
#   * GET /api/audit/open - the stored rows, decided here:
#       - a recommendation card is listed while a form's side panel shows it (its
#         id is in that form's `sqs.recommendations`); a card no form shows any
#         more was never in front of the producer in that state;
#       - a download-gate row is the gate's LIVE finding (`hard_block_findings`),
#         which the side panel now lists too - never a stale stored copy;
#       - a stored needs-attention summary (`row_superseded_by_attention`) stays
#         as before: the review shows it only for a form the live list could not
#         read;
#       - every other field-QA / field-mapping row (a value-vs-source mismatch, a
#         high-impact box left blank, a schedule-row defect, a carrier name in an
#         owner box) is shown on no earlier screen, so it is not listed. A box it
#         names that the side panel lists is still listed - as that row.
# Display only: the download gate, the stored rows, the cover and the E&O
# record are untouched.

_FINDING_PREFIXES = ("fieldqa_", "fieldmap_")


def is_hard_block_row(rec_id: Optional[str]) -> bool:
    return "hardblock_" in str(rec_id or "")


# ── The review page's hard stops and warnings, on the download screen too ────
# (owner, 14 Oct 2026). A hard stop or warning the Review page or the editor's
# Cross-Form panel lists, still firing and not dismissed, is on the download
# screen - "Driver schedule not provided" was open on 18ecbfa8's Review page
# and absent at download. ONE PROBLEM, ONE LINE: an issue and a card (or a
# side-panel box) that ask for the same thing are one line - the issue's, with
# the card's points. "The same thing" is read off what each one FIXES, never
# off its words: the facts / schedule an issue's fix window writes
# (`resolution`), the fact a card answers (`field`, and the table it is derived
# from), the fact a side-panel box writes back (`fact_key`).

# A fact rebuilt from a schedule table: the table is how it is fixed.
# Mirrors `extraction_service.sync_location_list` (pinned by a test).
_FACT_DERIVED_FROM_SCHEDULE = {"locations": "property_locations"}

# A card whose `field` names only ONE of the facts its rule reads. The Minimum
# Viable COPE card (`sqs_service`, ACORD 140 / 141) is stored as `locations`
# but asks for whichever of its four parts is missing - so beside the Review
# page's COPE hard stop (whose fix writes occupancy, construction and the
# building / BPP value) it is the same problem. The parts are read off the
# scorer's own `_min_cope_parts` (pinned by a test, so they cannot drift).
_CARD_READS = {
    "rec_min_cope": ("locations", "occupancy_type", "construction_type",
                     "property_building_value", "property_bpp_value"),
    # ACORD 130's officer card asks for `wc_officer_exclusions`; the officer
    # TABLE (`wc_officers`, the 130's "partner or executive officer" rows)
    # answers the same question - `coverage_evidence.wc_officer_treatment_status`
    # is satisfied by either (owner, 14 Oct 2026: the card and three officer
    # boxes were two lines for one problem on the download screen).
    "rec_wc_officer_exclusions": ("wc_officer_exclusions", "wc_officers"),
}


def _flat_names(value: Any) -> List[str]:
    out: List[str] = []
    if isinstance(value, str):
        if value.strip():
            out.append(value.strip())
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            out.extend(_flat_names(v))
    return out


def issue_fix_keys(item: Optional[dict]) -> set:
    """What a hard stop / warning's own fix writes: its resolution's facts and
    `needs`, its schedule table, and the fact it names."""
    item = item or {}
    res = item.get("resolution") if isinstance(item.get("resolution"), dict) else {}
    keys = set(_flat_names(res.get("facts"))) | set(_flat_names(res.get("needs")))
    keys |= set(_flat_names(res.get("schedule_key")))
    keys |= set(_flat_names(item.get("source_fact")))
    return {k for k in keys if k}


def card_fix_keys(row: Optional[dict]) -> set:
    """What a recommendation card answers: its fact, the table that fact is
    derived from, and the table its answer opens (`answer_routing`)."""
    field = str((row or {}).get("field") or "").strip()
    if not field:
        return set()
    keys = {field} | set(_CARD_READS.get(str((row or {}).get("rec_id") or ""), ()))
    if field in _FACT_DERIVED_FROM_SCHEDULE:
        keys.add(_FACT_DERIVED_FROM_SCHEDULE[field])
    try:
        from services.answer_routing import answer_mode
        sk = (answer_mode(field, {}) or {}).get("schedule_key")
        if sk:
            keys.add(str(sk))
    except Exception:                                      # pragma: no cover
        pass
    return keys


def _view_items(view: Optional[dict]):
    """(severity, item) for every row a grouped view draws: its Hard Stops and
    every Warnings tier, the way the screen reads a cluster (its items, or the
    one issue a single-item cluster carries on itself)."""
    if not isinstance(view, dict):
        return
    sections = [("hard_stop", view.get("hard_stops") or [])]
    warn = view.get("warnings") or {}
    tiers = warn.values() if isinstance(warn, dict) else [warn]
    sections += [("soft_warning", t or []) for t in tiers]
    for severity, clusters in sections:
        for c in clusters or []:
            if not isinstance(c, dict):
                continue
            items = c.get("items") if isinstance(c.get("items"), list) and c.get("items") else [
                {"issue_id": c.get("issue_id"), "message": c.get("primary_message"),
                 "forms": c.get("forms"), "resolution": c.get("resolution"), "code": c.get("code")}]
            for it in items:
                if isinstance(it, dict):
                    yield severity, it


def review_issue_rows(views: Iterable[Optional[dict]], statuses: Optional[Iterable[dict]] = None) -> List[dict]:
    """The hard stops and warnings the given grouped views draw (the Review
    page's, then the Cross-Form panel's), each ONCE (by issue id), minus every
    one the producer dismissed - as download-review rows. A "resolved" status
    on an issue that still fires keeps it: the Review page lists it too (its
    answer did not clear it)."""
    dismissed = {str(s.get("issue_id")) for s in (statuses or [])
                 if isinstance(s, dict) and s.get("status") == "dismissed"}
    seen: set = set()
    out: List[dict] = []
    for view in views or []:
        for severity, it in _view_items(view):
            msg = str(it.get("message") or "").strip()
            iid = str(it.get("issue_id") or "") or ("issf:" + msg)
            if not msg or iid in seen or iid in dismissed:
                continue
            seen.add(iid)
            forms = [f for f in (it.get("forms") or []) if f]
            out.append({
                "rec_id": iid,
                "issue_id": iid,
                "recommendation_type": severity,
                "message": msg,
                "score_impact": None,
                "field": None,
                "component": forms[0] if len(forms) == 1 else None,
                "forms": forms,
                "code": it.get("code"),
                "fix_facts": sorted(issue_fix_keys(it)),
                "review_issue": True,
            })
    return out


def download_review_rows(stored_rows: Iterable[dict], generated_forms: Optional[dict],
                         live_hard_blocks: Optional[List[dict]] = None,
                         review_issues: Optional[List[dict]] = None) -> List[dict]:
    """The stored open rows the download review lists (see the note above),
    then the download gate's live rows, then the Review page's open hard stops
    and warnings (`review_issue_rows`). `live_hard_blocks`: the gate's rows now
    (`field_qa.to_recommendation_rows` over `hard_block_findings`); None = the
    live check failed, so the stored gate rows stay (a blocker is never hidden
    by a failure). A card whose fix an issue's fix covers is that issue's line
    (the issue keeps the card's points). Every card and issue carries
    `fix_facts`, so the review can leave out a side-panel box it already names.
    No generated forms = nothing to compare with: the rows are returned as they
    are."""
    rows = [r for r in (stored_rows or []) if isinstance(r, dict)]
    gen = generated_forms or {}
    if not gen:
        return rows
    from services.audit_service import live_card_ids
    from services.field_qa import row_superseded_by_attention
    shown_cards = live_card_ids([(fr or {}).get("sqs") for fr in gen.values() if isinstance(fr, dict)])
    issues = [dict(i) for i in (review_issues or []) if isinstance(i, dict) and i.get("rec_id")]
    out: List[dict] = []
    for r in rows:
        rid = str(r.get("rec_id") or "")
        if is_hard_block_row(rid):
            if live_hard_blocks is None:
                out.append(r)
            continue
        if rid.startswith(_FINDING_PREFIXES):
            if row_superseded_by_attention(r):
                out.append(r)
            continue
        if rid not in shown_cards:
            continue
        keys = card_fix_keys(r)
        owner = next((i for i in issues if keys & set(i.get("fix_facts") or [])), None)
        if owner is not None:
            # One problem, one line: the issue's words, the card's points.
            pts = r.get("score_impact")
            if isinstance(pts, (int, float)) and not isinstance(pts, bool) and pts > (owner.get("score_impact") or 0):
                owner["score_impact"] = pts
            if r.get("recommendation_type") == "hard_stop":
                owner["recommendation_type"] = "hard_stop"   # the stronger of the two
            owner["fix_facts"] = sorted(set(owner.get("fix_facts") or []) | keys)
            owner.setdefault("absorbed_cards", []).append(rid)
            continue
        out.append(dict(r, fix_facts=sorted(keys)))
    for h in live_hard_blocks or []:
        if not isinstance(h, dict) or not h.get("rec_id"):
            continue
        out.append({
            "rec_id": h["rec_id"],
            "field": h.get("field"),
            "recommendation_type": h.get("type") or "suggestion",
            "message": h.get("message"),
            "score_impact": h.get("score_impact"),
            # The box it names, so the review lists the box once (frontend
            # `withoutListedBoxes`).
            "component": h.get("component"),
            "form_id": h.get("component"),
        })
    return out + issues


# ── A document added after forms disagrees with the AI (C103, 7 Oct 2026) ─────
# `session_documents.run_new_document_fill` never overwrites a box the AI filled
# at generation: where a document added later answers it DIFFERENTLY it stores a
# suggestion, and the producer chooses. These rows are the side panel's own
# group - NOT a needs-attention status: nothing about the box is missing or
# unverified, and the counts, the download review and the E&O rows above stay
# exactly as they were. A suggestion is live only while its box still shows the
# value it was measured against and nobody has typed it - "Use this value" (an
# ordinary box edit) and any other edit retire it on the next read.

STATUS_DOCUMENT_SAYS = "document_says"
_DOCUMENT_SAYS_TAG = "New document"
_DOCUMENT_SAYS_WHAT = "Use the new document's value, or keep the one the form shows."


def _shown_value(schema: dict, field: str, value: Any) -> str:
    if _field_type(schema, field) == "/Btn":
        return "Ticked" if _is_ticked(value) else "Not ticked"
    return _snippet(value, 120)


def document_suggestion_rows(generated_forms: Optional[dict], suggestions: Iterable[dict],
                             form_id: Optional[str] = None,
                             docs: Optional[Iterable[dict]] = None) -> List[dict]:
    """One row per live suggestion (all forms, or `form_id`'s), in the order the
    forms print their boxes. Each row: id, form_id, form_label, field, page,
    label, status ("document_says"), tag, reason, what_to_do, current,
    suggested (the raw value "Use this value" writes), current_display,
    suggested_display, documents. `docs` (the package's documents): a
    suggestion whose documents have all left the package (excluded, evidence
    only) is not listed (15 Oct 2026 - `session_documents.
    suggestions_from_active_documents`)."""
    rows: List[dict] = []
    if docs is not None:
        from services.session_documents import suggestions_from_active_documents
        suggestions = suggestions_from_active_documents(suggestions, docs)
    for s in suggestions or ():
        if not isinstance(s, dict):
            continue
        fid, field = s.get("form_id"), s.get("field")
        if not fid or not field or (form_id and fid != form_id):
            continue
        fr = (generated_forms or {}).get(fid)
        if not isinstance(fr, dict):
            continue
        state = fr.get("field_state") if isinstance(fr.get("field_state"), dict) else (fr.get("mapped") or {})
        label = (fr.get("confidence") or {}).get(field)
        if label in ("producer", "client_arq") or field in set(fr.get("client_filled_fields") or []):
            continue
        if _NORM.sub("", str(state.get(field) or "").lower()) != _NORM.sub("", str(s.get("current") or "").lower()):
            continue
        schema = fr.get("schema") if isinstance(fr.get("schema"), dict) and fr.get("schema") \
            else _schema_from_disk(fid)
        try:
            pos = widget_positions(fid, fr).get(field)
        except Exception:                                  # noqa: BLE001
            pos = None
        order = (pos[0], -pos[1], pos[2]) if pos else (9999, 0.0, 0.0)
        current = _shown_value(schema, field, s.get("current"))
        suggested = _shown_value(schema, field, s.get("suggested"))
        docs = [str(d) for d in (s.get("documents") or []) if str(d or "").strip()]
        rows.append({
            "id": s.get("id"),
            "form_id": fid,
            "form_label": form_label(fid),
            "field": field,
            "page": pos[0] if pos else None,
            "label": _trim(box_label(schema, field), _LABEL_MAX + 10),
            "status": STATUS_DOCUMENT_SAYS,
            "tag": _DOCUMENT_SAYS_TAG,
            # A blank box reads as blank, not as an empty quote; a document that
            # names another insured says so (14 Oct 2026, `f83757cf`).
            "reason": (f'New document says "{suggested}" - '
                       + (f'the form says "{current}".' if str(current or "").strip() else "this box is empty.")
                       + (f' This document names a different insured ({str(s.get("other_insured")).strip()}).'
                          if str(s.get("other_insured") or "").strip() else "")),
            "other_insured": str(s.get("other_insured") or "").strip() or None,
            "what_to_do": _DOCUMENT_SAYS_WHAT,
            "current": s.get("current"),
            "suggested": s.get("suggested"),
            "current_display": current,
            "suggested_display": suggested,
            "documents": docs,
            "_sort": (order, field),
        })
    rows.sort(key=lambda r: (r["form_id"], r["_sort"]))
    for r in rows:
        r.pop("_sort", None)
    return rows
