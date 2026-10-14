"""What a person TYPED into a fillable PDF, as text the pipeline can read.

THE DEFECT THIS CLOSES (owner's package f83757cf, 14 Oct). pdfplumber reads a
page's CONTENT STREAM. A fillable PDF keeps every typed value in its form
field's /V entry and draws it, if at all, from the widget's own appearance
stream (with /NeedAppearances set, a viewer draws it on the fly). Neither is
content stream, so the text layer of a filled ACORD 125 is the BLANK
template: the owner's "ACORD_125_FILLED 2.pdf" carries 234 filled values
(named insured, insurer, proposed dates, ticked lines of business ...) and its
extracted text held none of them. Extraction then found no applicant (the
Submission Integrity check listed it as "(no applicant name detected)", so
another insured's form slipped in with no warning) and read the blank
template's printed menus as facts.

WHAT THIS MODULE DOES. For every page, the filled form fields that page SHOWS,
one per line as "label: value", under one heading line. ocr_service appends the
block after the page's own content, whichever route the page took (native text,
column reflow, Google Vision, embedded-image OCR), exactly once.

  * value - a text field's text, a choice field's chosen option(s), "ticked"
    for a checked box, the chosen option of a radio group. Empty, "Off", hidden
    (/F Hidden or NoView) and zero-area widgets are skipped: a page cannot show
    them, and the blank ACORD templates' one pre-set field (the hidden,
    zero-size form edition identifier) is exactly that - so a blank template
    stays byte-identical. A value still equal to the author's own default (/DV)
    is skipped too: a blank template carries it, so nobody typed it.
  * label - a Y/N question's tooltip gives the question itself; a field NAME
    that names the box gives its words and row tag ("Named Insured Full Name
    (A)"; a dotted name keeps its parents, "Applicant Name" vs "Producer Name")
    plus ACORD's "As used here, ..." clause from the tooltip (what tells the
    PROPOSED date from a prior one); an opaque name ("Text1", "f1_01") gives the
    tooltip's first sentence without its "Enter text:" / "Check the box (if
    applicable):" prefix. Capped at 120 characters. Why the name before the
    tooltip: see `field_label` - ACORD tooltips define a box in words that name
    OTHER documents, and as labels they turned the owner's filled ACORD 125s
    into "Dec Page" for the document classifier.
  * caps - one value at 8,000 characters (cut at a word, "..."; a value stream
    is never decoded past that, so a small file cannot inflate a compressed
    "bomb" into memory), one page's block at 100,000 (later fields are counted,
    not shown), the document at 2,000,000. Real forms reach none of them - the
    fullest template page, ACORD 160 page 4, is ~42,000 with every box filled.
  * order - the form's own (/Annots, tab) order, so one contact's or one
    premises' boxes stay together.
  * inheritance - /T, /TU, /V, /FT, /Ff are read up the /Parent chain (cycle
    guarded), so a field with several widgets (the "Agency Customer ID" printed
    on every ACORD page is ONE field) is emitted once, on the first page that
    shows it.
  * never twice - a value already DRAWN in the page's own text layer inside its
    widget's box (a partly flattened PDF that kept its fields) is skipped. The
    test is geometric on purpose: a page-wide "is this string anywhere on the
    page" test drops typed values the template happens to print elsewhere -
    measured, it dropped "Prior Coverage Policy Year (A): 2025" on all three of
    the owner's filled ACORD 125s (the template's edition footer prints 2025).
    On a page whose text came from OCR (PyMuPDF's render draws the widget
    values, so Vision reads them) a value the OCR already read verbatim is
    skipped instead. A value under 4 characters ("Y", "WA") is never "already
    there": it means nothing without the label that names its question.

Read-only. Never raises: any failure leaves the document exactly as the old
text extraction produced it. OCR_FORM_FIELDS=0 turns it off.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

FORM_FIELDS_HEADING = "[Filled form fields - page {page}]"

_ON = os.getenv("OCR_FORM_FIELDS", "1").strip().lower() not in ("0", "false", "no", "off")


def _env_int(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.getenv(name, "").strip() or default))
    except (TypeError, ValueError):
        return default


# The caps exist for a hostile or broken PDF (megabytes of typed text), never for
# a real form. Sized from the templates: the fullest page, ACORD 160 page 4, has
# 392 boxes - every one holding a 40-character value is ~42,000 characters.
# Hitting a cap is logged at WARNING and the page's block says how many were left out.
_PAGE_MAX_CHARS = _env_int("OCR_FORM_FIELDS_PAGE_MAX_CHARS", 100_000, 2_000)
# The whole document (roughly 500k tokens, where extraction refuses a document
# anyway). Fields past it are not read; the rest of the document is unaffected.
_DOC_MAX_CHARS = _env_int("OCR_FORM_FIELDS_DOC_MAX_CHARS", 2_000_000, 10_000)
# One field's value. A typed narrative (ACORD 101 remarks) fits easily; a longer
# value is CUT, not dropped, so its head still reaches extraction and one runaway
# field cannot take the whole page cap from the boxes after it.
_VALUE_MAX_CHARS = _env_int("OCR_FORM_FIELDS_VALUE_MAX_CHARS", 8_000, 200)
# Bounds the scan itself (ACORD 160, the largest template, has 1,144 widgets).
_MAX_WIDGETS = _env_int("OCR_FORM_FIELDS_MAX_WIDGETS", 20_000, 100)
_LABEL_MAX = 120
_PARENT_DEPTH = 32
# A value this short ("Y", "N", "WA", "1") proves nothing by appearing in a page's
# text - the printed form says "Y / N" - so on either route it is never treated as
# already there (see `_drawable_variants`).
_MIN_PRESENT_CHARS = 4

_FF_RADIO = 1 << 15
_FF_PUSHBUTTON = 1 << 16
_F_HIDDEN = 1 << 1
_F_NOVIEW = 1 << 5


@dataclass
class FilledField:
    """One filled field as its page shows it."""
    page_idx: int
    label: str
    value: str
    kind: str                                   # "text" | "choice" | "check" | "radio"
    bbox: Optional[Tuple[float, float, float, float]]   # pdfplumber frame: x0, top, x1, bottom
    order: int                                  # discovery order, the tie-break
    drawn: bool = False                         # already in the page's own text layer, in its box

    @property
    def line(self) -> str:
        return f"{self.label}: {self.value}"


# ── Reading PDF objects ──────────────────────────────────────────────────────

def _inherited(node, key: str):
    """`key` from `node` or the nearest /Parent that has it (cycle guarded)."""
    seen = set()
    cur = node
    for _ in range(_PARENT_DEPTH):
        if cur is None:
            return None
        try:
            if key in cur:
                return cur[key]
            og = cur.objgen
            if og != (0, 0):
                if og in seen:
                    return None
                seen.add(og)
            cur = cur.get("/Parent")
        except Exception:                                    # noqa: BLE001 - malformed node
            return None
    return None


def _int(obj) -> int:
    try:
        return int(obj)
    except Exception:                                        # noqa: BLE001
        return 0


def _name_text(obj) -> str:
    """A PDF name without its slash, #xx escapes decoded."""
    s = str(obj)
    if s.startswith("/"):
        s = s[1:]
    return re.sub(r"#([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), s)


def _bounded_stream_bytes(stream, limit: int) -> bytes:
    """At most `limit` DECODED bytes of a value stream, never the whole stream: a
    200 KB file can hold a Flate stream that inflates to gigabytes, and a field's
    /V is decoded nowhere else in the pipeline. A text value stream is
    unfiltered or FlateDecode; anything else (or a predictor) reads as empty."""
    import zlib
    import pikepdf

    filters = stream.get("/Filter")
    if isinstance(filters, pikepdf.Array):
        filters = filters[0] if len(filters) == 1 else "multiple"
    params = stream.get("/DecodeParms")
    if isinstance(params, pikepdf.Array):
        params = params[0] if len(params) == 1 else None
    if isinstance(params, pikepdf.Dictionary) and _int(params.get("/Predictor", 1)) > 1:
        return b""
    raw = stream.read_raw_bytes()
    if filters is None:
        return raw[:limit]
    if str(filters) in ("/FlateDecode", "/Fl"):
        try:
            return zlib.decompressobj().decompress(raw, limit)
        except zlib.error:
            return b""
    return b""


def _pdf_text(obj) -> str:
    """Decode a PDF text value: string, name, stream, or an array of them."""
    import pikepdf

    if obj is None:
        return ""
    try:
        if isinstance(obj, pikepdf.String):
            return str(obj)
        if isinstance(obj, pikepdf.Name):
            return _name_text(obj)
        if isinstance(obj, pikepdf.Stream):
            raw = _bounded_stream_bytes(obj, _VALUE_MAX_CHARS * 4)
            if raw[:2] in (b"\xfe\xff", b"\xff\xfe"):
                return raw.decode("utf-16", errors="replace")
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError as ex:
                if ex.start >= len(raw) - 3:                  # a character cut by the bound
                    return raw[:ex.start].decode("utf-8", errors="replace")
                return raw.decode("latin-1")
        if isinstance(obj, pikepdf.Array):
            return "; ".join(t for t in (_pdf_text(x) for x in obj) if t)
        if isinstance(obj, (int, float)):
            return str(obj)
    except Exception:                                        # noqa: BLE001
        return ""
    return ""


def _qualified_name(field) -> str:
    parts: List[str] = []
    seen = set()
    cur = field
    for _ in range(_PARENT_DEPTH):
        if cur is None:
            break
        try:
            t = cur.get("/T")
            if t is not None:
                parts.append(_pdf_text(t))
            og = cur.objgen
            if og != (0, 0):
                if og in seen:
                    break
                seen.add(og)
            cur = cur.get("/Parent")
        except Exception:                                    # noqa: BLE001
            break
    return ".".join(p for p in reversed(parts) if p)


def _rect(widget) -> Optional[Tuple[float, float, float, float]]:
    import pikepdf

    try:
        # pikepdf.Rectangle reads the four numbers in one call - float() on each
        # element costs ~10x more, and a form has hundreds of widgets.
        r = pikepdf.Rectangle(widget.get("/Rect"))
        x0, x1 = sorted((float(r.llx), float(r.urx)))
        y0, y1 = sorted((float(r.lly), float(r.ury)))
        return x0, y0, x1, y1
    except Exception:                                        # noqa: BLE001
        return None


def _on_states(widget) -> List[str]:
    """The non-Off appearance state names a checkbox / radio widget offers."""
    try:
        normal = widget.get("/AP").get("/N")
        return [_name_text(k) for k in normal.keys() if _name_text(k) != "Off"]
    except Exception:                                        # noqa: BLE001
        return []


# ── Labels and values ────────────────────────────────────────────────────────

_WS_RE = re.compile(r"\s+")
# ACORD's instruction prefix: "Enter text:", "Enter date:", "Enter code:",
# "Enter amount:", "Check the box (if applicable):" ... A colon within 40
# characters and no sentence end before it, so a real sentence is never eaten.
_PREFIX_RE = re.compile(
    r"^\s*(?:enter|input|select|choose|type|check|sign|initial)\b[^:.!?]{0,40}:\s*", re.I)
# A checkbox PAIR ("..._Question_ADCYesIndicator_A" / "...NoIndicator_A"): the
# tick IS the answer, so the line reads "<question>: Yes", never "ticked" on two
# lines that would look identical.
_YES_NO_BOX_RE = re.compile(
    r"indicates\s+an?\s+[\"\u201c\u2018']?(yes|no)[\"\u201d\u2019']?\s+response\s+to\s+the\s+question",
    re.I)
# "... Indicates the response to the question, "Any area leased to others?"."
_QUESTION_RE = re.compile(
    r"response to the question,?\s*[\"“‘']\s*(.+?)(?:\?|[\"”’](?=\s*[.,;]?\s*$)|$)",
    re.I | re.S)
_AS_USED_RE = re.compile(r"\bAs used here,\s*(.+?)(?:\.(?:\s|$)|$)", re.I | re.S)
# ACORD's Y/N-code instruction ("Enter Y for a "Yes" response. Input N for "No"
# response.") says how to fill the box, not what it is - the sentence after it does.
_YES_NO_INSTRUCTION_RE = re.compile(
    r"^\s*(?:enter|input|type)\s+y\b[^.]*\.\s*(?:(?:enter|input|type)\s+n\b[^.]*\.\s*)?",
    re.I)
# A candidate sentence end: a full stop before a capital / bracket / quote, or
# at the very end. `_first_sentence` then refuses the abbreviation dots.
_SENTENCE_END_RE = re.compile(r"\.(?=\s+[A-Z(\[\"\u201c])|\.\s*$")
_ABBREVIATIONS = frozenset({
    "e.g", "i.e", "etc", "vs", "no", "nos", "inc", "co", "corp", "ltd", "st", "jr",
    "sr", "dr", "mr", "mrs", "ms", "approx", "est", "dept", "ave", "blvd", "fig",
    "u.s", "u.s.a", "a.m", "p.m", "max", "min", "yr", "yrs", "mo", "ft", "sq",
})
_OPAQUE_CHOICE_RE = re.compile(
    r"^(?:\d+|on|choice\s*\d*|option\s*\d*|button\s*\d*|radio\s*\d*|item\s*\d*|value\s*\d*)$",
    re.I)


def _collapse(s: str) -> str:
    return _WS_RE.sub(" ", (s or "").replace("\x00", "")).strip()


def _cap(s: str, limit: int = _LABEL_MAX) -> str:
    s = s.strip()
    if len(s) <= limit:
        return s
    cut = s[:limit - 3].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return (cut or s[:limit - 3]) + "..."


# Words a PDF authoring tool puts in a field name that say nothing about the
# box ("Text1", "Check Box 3", "fill_12", "topmostSubform[0].Page1[0].f1_01[0]").
_GENERIC_NAME_WORDS = frozenset({
    "text", "txt", "field", "fill", "check", "box", "checkbox", "chk", "radio",
    "button", "btn", "group", "combo", "list", "dropdown", "choice", "undefined",
    "untitled", "form", "page", "subform", "topmostsubform", "row", "cell", "item",
    "value", "entry", "input", "data", "the", "and", "for", "of",
})


# A name segment that only says where the box sits in the authoring tool's tree
# ("topmostSubform[0].Page1[0]..." from LiveCycle / Designer), never what it holds.
_TREE_SEGMENT_RE = re.compile(
    r"^#?(?:topmost\s*subform|subform|area|form\d*|page\s*\d*|pg\s*\d*|p\d+|root|fields?)$", re.I)


def _split_words(segment: str) -> str:
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", segment)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", s)
    return _collapse(re.sub(r"[_\-]+", " ", s))


def _humanize_name(name: str) -> Tuple[str, str]:
    """A field name as words plus its row tag:
    "NamedInsured_FullName_A" -> ("Named Insured Full Name", "A"). A dotted
    (hierarchical) name keeps its parent segments - "Applicant.Name" and
    "Producer.Name" are different boxes - minus the authoring tool's tree
    ("topmostSubform[0].Page1[0]")."""
    segments = [re.sub(r"\[\d+\]", "", s).strip() for s in (name or "").split(".")]
    segments = [s for s in segments if s]
    if not segments:
        return "", ""
    last = segments[-1]
    row = ""
    m = re.search(r"[_\-\s]([A-Z]|\d{1,3})$", last)
    if m:
        row, last = m.group(1), last[:m.start()]
    parents = [s for s in segments[:-1]
               if re.search(r"[A-Za-z]{2}", s) and not _TREE_SEGMENT_RE.match(s)]
    words = " ".join(w for w in (_split_words(s) for s in parents + [last]) if w)
    return _collapse(words), row


def _descriptive(words: str) -> bool:
    """Does a humanized field name actually name the box (two real words)?"""
    real = [w for w in re.findall(r"[A-Za-z]+", words)
            if len(w) >= 3 and w.lower() not in _GENERIC_NAME_WORDS]
    return len(real) >= 2


def _first_sentence(text: str) -> str:
    """Text up to its first real full stop - never the dot of "e.g." / "i.e." /
    "No." / an initial."""
    for m in _SENTENCE_END_RE.finditer(text):
        word = re.search(r"([A-Za-z.]*)$", text[:m.start()]).group(1).lower().strip(".")
        if word in _ABBREVIATIONS or len(word) == 1 or "." in word:
            continue
        return text[:m.start()]
    return text


# The box holds the ANSWER to a question (not, say, an explanation that quotes
# it): ACORD's Y/N-code instruction, a "Yes"/"No" checkbox of a pair, or a
# tooltip that says the box is "the response to the question".
_ANSWER_BOX_RE = re.compile(
    r"(?:^|[.:]\s+)(?:indicates\s+)?the\s+response\s+to\s+the\s+question", re.I)


def _question_of(tu: str) -> str:
    """The question an answer box answers, from its tooltip - "" when none."""
    if not tu or not (_YES_NO_INSTRUCTION_RE.match(tu) or _YES_NO_BOX_RE.search(tu)
                      or _ANSWER_BOX_RE.search(tu)):
        return ""
    q = _QUESTION_RE.search(tu)
    if not q:
        return ""
    return q.group(1).strip().strip("\"'\u201c\u201d ")


def field_label(tooltip: str, name: str) -> str:
    """The label a field's line carries.

    1. A Y/N question's tooltip -> the question itself ("Any area leased to
       others?") - the field name is a code (..._Question_ABBCode_A).
    2. A field name that names the box -> its words plus the row tag, plus
       ACORD's "As used here, ..." clause when the tooltip has one ("Named
       Insured Full Name (A)", "Additional Interest Full Name (B) - this is the
       name of the trust"). The NAME, not the tooltip, because an ACORD tooltip
       DEFINES the box in words that name other documents: "The named insured(s)
       as it / they will appear on the policy declarations page", "requires a
       Certificate of Insurance". Measured on the owner's three filled ACORD 125s:
       tooltip labels moved the document classifier from Commercial Insurance
       Application to Dec Page (dec_page 1.5 -> 12.5, tie broken toward dec_page).
    3. Otherwise (an opaque "Text1" / "f1_01" name) -> the tooltip's first
       sentence without its "Enter text:" style prefix.
    4. Nothing better -> the field name as it is."""
    # The longest ACORD tooltip is ~570 characters; the bound only keeps a hostile
    # one from feeding megabytes to the regexes below.
    tu = _collapse((tooltip or "")[:4_000])
    words, row = _humanize_name((name or "")[:1_000])
    question = _question_of(tu)
    if question:
        # The row tag keeps one question asked per premises apart.
        tag = f" ({row})" if row else ""
        return _cap(question.rstrip("?") + "?", _LABEL_MAX - len(tag)) + tag
    if words and _descriptive(words):
        label = f"{words} ({row})" if row else words
        used = _AS_USED_RE.search(tu) if tu else None
        if used and used.group(1).strip():
            label = f"{label} - {used.group(1).strip().rstrip('.')}"
        return _cap(label)
    if tu:
        body = _PREFIX_RE.sub("", tu, count=1).strip()
        body = _YES_NO_INSTRUCTION_RE.sub("", body, count=1).strip()
        first = _first_sentence(body).strip().rstrip(".").strip() if body else ""
        if first:
            return _cap(first)
    fallback = f"{words} ({row})" if words and row else (words or name or "")
    return _cap(fallback) if fallback else "Form field"


def _value_text(s: str) -> str:
    """One line: typed line breaks become " / ", whitespace collapses, and a value
    longer than _VALUE_MAX_CHARS is cut at a word with "..."."""
    s = (s or "")[:_VALUE_MAX_CHARS * 4].replace("\x00", "")   # bounds the work on a runaway value
    s = re.sub(r"\s*(?:\r\n|\r|\n)+\s*", " / ", s.strip())
    s = _collapse(s)
    return _cap(s, _VALUE_MAX_CHARS) if len(s) > _VALUE_MAX_CHARS else s


def _choice_display(field, value_obj) -> str:
    """A choice field's value through its /Opt export -> display pairs."""
    import pikepdf

    exports: Dict[str, str] = {}
    try:
        opt = _inherited(field, "/Opt")
        if isinstance(opt, pikepdf.Array):
            for o in opt:
                if isinstance(o, pikepdf.Array) and len(o) >= 2:
                    exports[_pdf_text(o[0])] = _pdf_text(o[1])
    except Exception:                                        # noqa: BLE001
        exports = {}
    picked = list(value_obj) if isinstance(value_obj, pikepdf.Array) else [value_obj]
    shown = [exports.get(t, t) for t in (_pdf_text(v) for v in picked)]
    return "; ".join(_value_text(t) for t in shown if _value_text(t))


# ── Geometry: a widget's box in pdfplumber's frame ──────────────────────────

def _page_attr(page_obj, key: str):
    return _inherited(page_obj, key)


def _plumber_bbox(rect, mediabox, rotation: int) -> Optional[Tuple[float, float, float, float]]:
    """A widget /Rect (PDF user space) in the frame pdfplumber gives its chars.

    pdfminer lays a page out through a CTM built from the MediaBox and /Rotate
    (PDFPageInterpreter.process_page); pdfplumber then measures `top` from the
    page's top edge and adds the MediaBox origin back (Page.process_object).
    Mirrored here so a widget's box and the characters drawn inside it compare
    in one coordinate system on rotated and offset pages too."""
    try:
        mx0, my0, mx1, my1 = (float(v) for v in mediabox)
    except Exception:                                        # noqa: BLE001
        return None
    rotation = int(rotation or 0) % 360
    if rotation == 90:
        a, b, c, d, e, f = 0, -1, 1, 0, -my0, mx1
    elif rotation == 180:
        a, b, c, d, e, f = -1, 0, 0, -1, mx1, my1
    elif rotation == 270:
        a, b, c, d, e, f = 0, 1, -1, 0, my1, -mx0
    else:
        a, b, c, d, e, f = 1, 0, 0, 1, -mx0, -my0
    rx0, ry0, rx1, ry1 = rect
    pts = [(x, y) for x in (rx0, rx1) for y in (ry0, ry1)]
    xs = [a * x + c * y + e for x, y in pts]
    ys = [b * x + d * y + f for x, y in pts]
    # pdfplumber's own MediaBox normalisation (Page.__init__).
    nx0, nx1 = sorted((mx0, mx1))
    ny0, ny1 = sorted((my0, my1))
    if rotation in (90, 270):
        nx0, ny0, nx1, ny1 = ny0, nx0, ny1, nx1
    height = ny1 - ny0
    mb_x0, mb_top = nx0, height - ny1
    x_shift = mb_x0 if mb_x0 != 0 else 0.0
    return (min(xs) + x_shift, (height - max(ys)) + mb_top,
            max(xs) + x_shift, (height - min(ys)) + mb_top)


# ── The reader ───────────────────────────────────────────────────────────────

def _is_author_default(field, value_obj) -> bool:
    """Is /V still the form author's own default (/DV)? Then nobody typed it: a
    BLANK template carries that value too, so it is never appended as if typed.
    The 17 ACORD templates' one pre-set field is also hidden and zero-size; this
    is the rule for a template whose default shows on the page."""
    if value_obj is None:
        return False
    default = _inherited(field, "/DV")
    if default is None:
        return False
    shown = _pdf_text(value_obj)
    return bool(shown) and shown == _pdf_text(default)


def _field_entry(group: dict, order: int) -> Optional[FilledField]:
    """Turn one field (all its widgets) into the line its page shows, or None."""
    import pikepdf

    field = group["field"]
    widgets = group["widgets"]                    # [(page_idx, widget, rect, bbox)]
    ft = _inherited(field, "/FT")
    ft = str(ft) if ft is not None else ""
    if ft == "/Sig":
        return None
    value_obj = _inherited(field, "/V")
    if value_obj is None and ft != "/Btn":
        return None                               # nothing typed: most boxes of any form
    ff = _int(_inherited(field, "/Ff"))
    if _is_author_default(field, value_obj):
        return None
    chosen = widgets[0]
    kind = "text"
    tooltip = None                                # decoded only for a box that holds a value

    if ft == "/Btn":
        if ff & _FF_PUSHBUTTON:
            return None
        on = _name_text(value_obj) if isinstance(value_obj, pikepdf.Name) else _pdf_text(value_obj)
        if value_obj is None:
            # Some writers set only the widget's appearance state.
            for w in widgets:
                state = w[1].get("/AS")
                if state is not None and _name_text(state) not in ("", "Off"):
                    on = _name_text(state)
                    break
        on = (on or "").strip()
        if not on or on == "Off":
            return None
        tooltip = _pdf_text(_inherited(field, "/TU"))
        states = {s for w in widgets for s in _on_states(w[1])}
        for w in widgets:
            st = w[1].get("/AS")
            if on in _on_states(w[1]) or (st is not None and _name_text(st) == on):
                chosen = w
                break
        if (ff & _FF_RADIO) or len(states) > 1:
            kind = "radio"
            if _OPAQUE_CHOICE_RE.match(on):
                own = _collapse(_pdf_text(chosen[1].get("/TU")))
                own = _PREFIX_RE.sub("", own, count=1).strip()
                value = _cap(own.rstrip("."), 80) if own and own != _collapse(tooltip) else f"option {on}"
            else:
                value = _value_text(on)
        else:
            kind = "check"
            answer = _YES_NO_BOX_RE.search(_collapse(tooltip))
            value = answer.group(1).capitalize() if answer else "ticked"
    elif ft == "/Ch":
        kind = "choice"
        value = _choice_display(field, value_obj) if value_obj is not None else ""
    elif ft == "/Tx" or (not ft and isinstance(value_obj, (pikepdf.String, pikepdf.Stream))):
        value = _value_text(_pdf_text(value_obj))
    else:
        return None
    if not value or value == "Off":
        return None
    if tooltip is None:
        tooltip = _pdf_text(_inherited(field, "/TU"))
    page_idx, _w, _rect_, bbox = chosen
    return FilledField(page_idx=page_idx, label=field_label(tooltip, _qualified_name(field)),
                       value=value, kind=kind, bbox=bbox, order=order)


def _scan_widgets(pdf) -> Dict[object, dict]:
    """Every visible widget on every page, grouped by the field it belongs to."""
    import pikepdf

    groups: Dict[object, dict] = {}
    scanned = 0
    for idx, page in enumerate(pdf.pages):
        pobj = page.obj
        annots = pobj.get("/Annots")
        if not isinstance(annots, pikepdf.Array) or len(annots) == 0:
            continue
        frame = None
        for pos, a in enumerate(annots):
            if not isinstance(a, pikepdf.Dictionary):
                continue
            if a.get("/Subtype") != "/Widget":
                continue
            scanned += 1
            if scanned > _MAX_WIDGETS:
                logger.warning("form_field_text: more than %d widgets - the rest are not read",
                               _MAX_WIDGETS)
                return groups
            if _int(a.get("/F", 0)) & (_F_HIDDEN | _F_NOVIEW):
                continue
            rect = _rect(a)
            if rect is None or (rect[2] - rect[0]) < 1.0 or (rect[3] - rect[1]) < 1.0:
                continue                            # zero-area: the page cannot show it
            field = a if ("/T" in a or "/Parent" not in a) else a.get("/Parent")
            if field is None:
                continue
            og = field.objgen
            key = og if og != (0, 0) else ("direct", idx, pos)
            if frame is None:
                try:
                    mediabox = [float(v) for v in _page_attr(pobj, "/MediaBox")]
                except Exception:                            # noqa: BLE001 - missing / malformed
                    mediabox = [0.0, 0.0, 612.0, 792.0]
                frame = (mediabox, _int(_page_attr(pobj, "/Rotate")))
            bbox = _plumber_bbox(rect, frame[0], frame[1])
            groups.setdefault(key, {"field": field, "widgets": []})["widgets"].append(
                (idx, a, rect, bbox))
    return groups


def _compact_variants(value: str) -> Tuple[str, ...]:
    """The value as a text layer would carry it, whitespace removed - as shown, and
    with the " / " that `_value_text` puts between typed lines taken out (the page
    draws those as separate lines). Both, because a typed value can hold a literal
    " / " of its own ("Inspection / Loss Control") and the page then draws the slash."""
    variants = (re.sub(r"\s+", "", value or ""),
                re.sub(r"\s+", "", (value or "").replace(" / ", "")))
    return tuple(dict.fromkeys(v for v in variants if v))


def _drawable_variants(value: str) -> Tuple[str, ...]:
    """The variants long enough to prove anything. A value under _MIN_PRESENT_CHARS
    ("Y", "N", "A", "WA") is never treated as already on the page, on either route:
    every page "contains" an "N", and a drawn "Y" says nothing without the question
    it answers - its labelled line is the only place that question is attached."""
    return tuple(v for v in _compact_variants(value) if len(v) >= _MIN_PRESENT_CHARS)


def _value_drawn(field: FilledField, chars: Sequence[dict]) -> bool:
    """Is this value already drawn in the page's own text layer, inside its box?"""
    if field.bbox is None:
        return False
    x0, top, x1, bottom = field.bbox
    inside = [c for c in chars
              if x0 - 1 <= (c["x0"] + c["x1"]) / 2 <= x1 + 1
              and top - 1 <= (c["top"] + c["bottom"]) / 2 <= bottom + 1]
    if not inside:
        return False
    inside.sort(key=lambda c: (round(c["top"]), c["x0"]))
    drawn = re.sub(r"\s+", "", "".join(c.get("text", "") for c in inside))
    return any(want in drawn for want in _drawable_variants(field.value))


def _mark_drawn(pdf_path: str, by_page: Dict[int, List[FilledField]],
                page_texts: Optional[Sequence[str]]) -> None:
    """Set `drawn` on values the page's text layer already carries in their box.

    Pre-filtered on the page's extracted text so a normal filled form (values
    live only in the fields) never opens the PDF a second time."""
    todo: Dict[int, List[FilledField]] = {}
    for idx, fields in by_page.items():
        native = page_texts[idx] if page_texts is not None and idx < len(page_texts) else None
        compact = re.sub(r"\s+", "", native) if native is not None else None
        for f in fields:
            if f.kind in ("check", "radio"):
                continue                            # "ticked" is never in a text layer
            wants = _drawable_variants(f.value)
            if not wants:
                continue                            # a "Y" / "WA" means nothing without its label
            if compact is not None and not any(w in compact for w in wants):
                continue
            todo.setdefault(idx, []).append(f)
    if not todo:
        return
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        for idx, fields in todo.items():
            if idx >= len(pdf.pages):
                continue
            try:
                chars = pdf.pages[idx].chars
            except Exception as ex:                          # noqa: BLE001
                logger.debug("form_field_text: chars unavailable on page %d: %s", idx + 1, ex)
                continue
            for f in fields:
                f.drawn = _value_drawn(f, chars)


def read_filled_fields(pdf_path: str,
                       page_texts: Optional[Sequence[str]] = None) -> Dict[int, List[FilledField]]:
    """Every filled, visible form field, by 0-based page index, in the form's own order.

    {} for a PDF without an AcroForm, without filled fields, or on any error -
    the caller then produces exactly the text it always did. `page_texts`, when
    given, is the page's native text; it lets the drawn-value check skip the
    second PDF open on the normal case."""
    if not _ON:
        return {}
    try:
        import pikepdf
    except Exception:                                        # noqa: BLE001
        return {}
    try:
        with pikepdf.open(pdf_path) as pdf:
            acro = pdf.Root.get("/AcroForm")
            if not isinstance(acro, pikepdf.Dictionary):
                return {}
            fields = acro.get("/Fields")
            if not isinstance(fields, pikepdf.Array) or len(fields) == 0:
                return {}
            groups = _scan_widgets(pdf)
            by_page: Dict[int, List[FilledField]] = {}
            for order, group in enumerate(groups.values()):
                try:
                    entry = _field_entry(group, order)
                except Exception as ex:                      # noqa: BLE001 - one bad field
                    logger.debug("form_field_text: field skipped: %s", ex)
                    entry = None
                if entry is not None:
                    by_page.setdefault(entry.page_idx, []).append(entry)
    except Exception as ex:                                  # noqa: BLE001
        logger.warning("form_field_text: form fields not read from %s: %s",
                       os.path.basename(pdf_path), ex)
        return {}
    if not by_page:
        return {}
    try:
        _mark_drawn(pdf_path, by_page, page_texts)
    except Exception as ex:                                  # noqa: BLE001
        logger.debug("form_field_text: drawn-value check failed: %s", ex)
    # Kept in the form's own order (/Annots, the tab order its author set): on
    # ACORD 125 that keeps each contact's / premises' boxes together where a
    # top-to-bottom sort interleaved two side-by-side contacts line by line.
    for fields in by_page.values():
        fields.sort(key=lambda f: f.order)
    _apply_document_cap(by_page, os.path.basename(pdf_path))
    logger.info("form_field_text: %s - %d filled field(s) on %d page(s)",
                os.path.basename(pdf_path), sum(len(v) for v in by_page.values()), len(by_page))
    return by_page


def _apply_document_cap(by_page: Dict[int, List[FilledField]], name: str) -> None:
    """Keep fields, in page order, while their lines fit _DOC_MAX_CHARS."""
    used = dropped = 0
    for idx in sorted(by_page):
        kept = []
        for f in by_page[idx]:
            used += len(f.line) + 1
            if used > _DOC_MAX_CHARS:
                dropped += 1
            else:
                kept.append(f)
        by_page[idx] = kept
    for idx in [i for i, v in by_page.items() if not v]:
        del by_page[idx]
    if dropped:
        logger.warning("form_field_text: %s - %d filled field(s) past the %d-char document "
                       "cap were not read", name, dropped, _DOC_MAX_CHARS)


# ── The block ────────────────────────────────────────────────────────────────

def _already_in_text(value: str, text_ws: str) -> bool:
    """Did OCR already read this value, word-bounded? Checked as shown and with the
    " / " that joins typed lines read as the line break OCR saw (see `_compact_variants`)."""
    for v in dict.fromkeys((_collapse(value), _collapse((value or "").replace(" / ", " ")))):
        if len(v.replace(" ", "")) < _MIN_PRESENT_CHARS:
            continue
        if re.search(r"(?<![0-9A-Za-z])" + re.escape(v) + r"(?![0-9A-Za-z])", text_ws):
            return True
    return False


def form_field_block(fields: Optional[Iterable[FilledField]], page_no: int,
                     page_text: str = "", *, ocr_text: bool = False) -> str:
    """The page's "label: value" block under its heading, or "" when none is left.

    `ocr_text` says the page's text came from OCR of the rendered page (which
    draws the widgets): a value that OCR already read verbatim is not repeated.
    On a native-text page, `FilledField.drawn` (the in-box geometric test)
    decides instead."""
    if not fields:
        return ""
    text_ws = _collapse(page_text) if ocr_text else ""
    lines: List[str] = []
    used = 0
    left_out = 0
    for f in fields:
        if ocr_text:
            if f.kind not in ("check", "radio") and _already_in_text(f.value, text_ws):
                continue
        elif f.drawn:
            continue
        line = f.line
        if used + len(line) + 1 > _PAGE_MAX_CHARS:
            left_out += 1
            continue
        lines.append(line)
        used += len(line) + 1
    if not lines and not left_out:
        return ""
    if left_out:
        logger.warning("form_field_text: page %d - %d filled field(s) over the %d-char "
                       "page cap were left out", page_no, left_out, _PAGE_MAX_CHARS)
        lines.append(f"[{left_out} more filled form field(s) on this page not shown]")
    return FORM_FIELDS_HEADING.format(page=page_no) + "\n" + "\n".join(lines)
