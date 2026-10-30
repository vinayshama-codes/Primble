"""Which pages of an uploaded PDF are ACORD forms, which form, and in what shape.

Two signals, strongest first:
  1. BOX NAMES (a fillable PDF). Every fillable ACORD carries ACORD's own box
     names; a page whose names are >= 90% one of our schemas' is that form.
     Exact - nothing else carries those names.
  2. THE PRINTED FOOTER ("ACORD 125 (2025/03)", "ACORD 137 CO (2015/12)").
     Every ACORD page prints it. It also tells the CA / CO variants apart,
     which share box names, and names an ACORD form we hold no template for.
A page with neither is not an ACORD form and keeps today's path.

Kinds: "fillable" (box names present), "flattened" (text layer + footer, no
boxes), "scanned" (an ACORD footer read by OCR off an image page). Never raises.
"""
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set

logger = logging.getLogger(__name__)

_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCHEMA_DIR = os.path.join(_BACKEND, "forms_schemas")
_FOOTER_RE = re.compile(r"\bACORD\s+(?P<num>\d{2,3})(?:\s+(?P<var>[A-Z]{2}))?\s*\((?P<ed>\d{4}/\d{2})\)")
_MIN_NAME_SHARE = 0.9
_MIN_NAMES = 5
_SCHEMA_NAMES: Optional[Dict[str, Set[str]]] = None


@dataclass
class PageForm:
    page: int                               # 0-based
    kind: Optional[str] = None              # fillable | flattened | scanned | None (not ACORD)
    form_id: Optional[str] = None           # one of ours ("ACORD_137_CO"), or None
    acord_number: Optional[str] = None      # as printed ("137 CO"), ours or not
    edition: Optional[str] = None           # "2015/12"
    names: Set[str] = field(default_factory=set)
    text: str = ""                          # the page's native text (re-used by the field read)


def schema_names() -> Dict[str, Set[str]]:
    global _SCHEMA_NAMES
    if _SCHEMA_NAMES is None:
        out: Dict[str, Set[str]] = {}
        for fn in os.listdir(_SCHEMA_DIR):
            if fn.endswith("_schema.json"):
                try:
                    with open(os.path.join(_SCHEMA_DIR, fn)) as fh:
                        out[fn[:-len("_schema.json")]] = set(json.load(fh))
                except Exception as ex:                        # noqa: BLE001
                    logger.warning("acord_intake: schema %s unreadable: %s", fn, ex)
        _SCHEMA_NAMES = out
    return _SCHEMA_NAMES


def form_id_for_footer(num: str, variant: Optional[str] = None) -> Optional[str]:
    """Our form id for a printed number ("137", "CO") - None when we hold no template."""
    ids = schema_names()
    if variant:
        fid = f"ACORD_{num}_{variant}"
        return fid if fid in ids else None
    fid = f"ACORD_{num}"
    return fid if fid in ids else None


# The footer is the page's OWN identity only where a footer is printed: the
# bottom of the page (every one of our 17 templates prints it in the last 6%).
# A form number with its edition further up is a REFERENCE to a form - a dec
# page's "application on file: ACORD 125 (2025/03)" - never the page's identity
# (review, 27 Oct 2026). With no geometry (OCR text, given texts) the footer
# must be among the last characters of the page's text instead.
_FOOTER_BAND = 0.85
_FOOTER_TAIL_CHARS = 400


def footer_of(text: str, tail: bool = False) -> Optional[re.Match]:
    hits = list(_FOOTER_RE.finditer(text or ""))
    if not hits:
        return None
    last = hits[-1]                            # the page's own footer sits last
    if tail and len((text or "")[last.end():].strip()) > _FOOTER_TAIL_CHARS:
        return None
    return last


def _bottom_text(page) -> str:
    """The words printed in the page's footer band, in reading order."""
    try:
        h = float(page.height)
        words = [w for w in page.extract_words() if float(w["top"]) >= _FOOTER_BAND * h]
        words.sort(key=lambda w: (round(float(w["top"]) / 3), float(w["x0"])))
        return " ".join(w["text"] for w in words)
    except Exception:                                          # noqa: BLE001
        return ""


_XFA_INDEX_RE = re.compile(r"\[\d+\]")
_ALL_NAMES: Optional[Set[str]] = None


def box_name(qualified: str, schema: Optional[Set[str]] = None) -> str:
    """The ACORD box a field's qualified name is. A form re-saved by a designer
    tool prefixes and indexes the names ("form1[0].Page1[0].NamedInsured_FullName_A[0]");
    its last segment without the index is ACORD's box name when that is a box of
    the schema (any of ours when `schema` is None). "" when it is no box of ours."""
    global _ALL_NAMES
    names = schema
    if names is None:
        if _ALL_NAMES is None:
            _ALL_NAMES = set().union(*schema_names().values()) if schema_names() else set()
        names = _ALL_NAMES
    q = str(qualified or "")
    if q in names:
        return q
    leaf = _XFA_INDEX_RE.sub("", q).split(".")[-1]
    return leaf if leaf in names else ""


def _names_by_page(pdf_path: str) -> Dict[int, Set[str]]:
    """Every box name each page shows (filled or not), via the field reader's own
    widget scan (inheritance, hidden widgets, cycle guards)."""
    try:
        import pikepdf
        from utils import form_field_text as fft
        with pikepdf.open(pdf_path) as pdf:
            # The pages' widgets, with or without a document /AcroForm (a PDF
            # combined by a tool that copies pages and not the form dictionary).
            out: Dict[int, Set[str]] = {}
            for group in fft._scan_widgets(pdf).values():
                qualified = fft._qualified_name(group["field"])
                name = box_name(qualified) or qualified
                for (page_idx, _w, _r, _b) in group["widgets"]:
                    out.setdefault(page_idx, set()).add(name)
            return out
    except Exception as ex:                                    # noqa: BLE001
        logger.info("acord_intake: no form fields read (%s)", ex)
        return {}


def _form_by_names(names: Set[str], footer_fid: Optional[str]) -> Optional[str]:
    # A page with few boxes (ACORD 131's page 5) is its footer's form when every
    # box it has belongs to that form.
    if footer_fid and names and names <= schema_names().get(footer_fid, set()):
        return footer_fid
    if len(names) < _MIN_NAMES:
        return None
    best = []
    for fid, schema in schema_names().items():
        hit = len(names & schema)
        if hit >= _MIN_NAMES and hit / len(names) >= _MIN_NAME_SHARE:
            best.append((hit, fid))
    if not best:
        return None
    # CA / CO variants share their names: the footer decides; else most names.
    if footer_fid and any(fid == footer_fid for _h, fid in best):
        return footer_fid
    best.sort(key=lambda x: (-x[0], x[1]))
    return best[0][1]


def recognize(pdf_path: str, page_texts: Optional[Sequence[str]] = None,
              ocr_texts: Optional[Dict[int, str]] = None) -> List[PageForm]:
    """One PageForm per page. `page_texts` (native text per page) saves a re-read.
    `ocr_texts` ({1-based page: text}) is the OCR read of the pages that have no
    text layer - an image page's footer is found there, so a SCANNED ACORD form
    is recognised (and flagged for verification) instead of passing unnoticed."""
    out: List[PageForm] = []
    try:
        texts = list(page_texts) if page_texts is not None else None
        native_chars: List[int] = []
        bottoms: List[Optional[str]] = []
        if texts is None:
            import pdfplumber
            texts = []
            with pdfplumber.open(pdf_path) as pdf:
                for p in pdf.pages:
                    t = p.extract_text() or ""
                    texts.append(t)
                    native_chars.append(len(p.chars))
                    bottoms.append(_bottom_text(p) if p.chars else None)
        names = _names_by_page(pdf_path)
        for i, text in enumerate(texts):
            pf = PageForm(page=i, names=names.get(i, set()), text=text or "")
            image_page = bool(native_chars) and i < len(native_chars) and native_chars[i] == 0
            if image_page:
                foot = footer_of((ocr_texts or {}).get(i + 1) or "", tail=True)
            elif i < len(bottoms) and bottoms[i] is not None:
                foot = footer_of(bottoms[i])
            else:
                foot = footer_of(text, tail=True)
            if foot:
                pf.acord_number = (f"{foot.group('num')} {foot.group('var')}" if foot.group("var")
                                   else foot.group("num"))
                pf.edition = foot.group("ed")
            footer_fid = form_id_for_footer(foot.group("num"), foot.group("var")) if foot else None
            by_names = _form_by_names(pf.names, footer_fid)
            if by_names:
                pf.kind, pf.form_id = "fillable", by_names
            elif foot:
                pf.kind = "scanned" if image_page else "flattened"
                pf.form_id = footer_fid
            out.append(pf)
        # A page of a FILLABLE form that shows no box at all is still that form
        # (nothing on it to read), never a "flattened" copy of it.
        fillable_forms = {p.form_id for p in out if p.kind == "fillable"}
        for p in out:
            if p.kind == "flattened" and not p.names and p.form_id in fillable_forms:
                p.kind = "fillable"
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("acord_intake: recognition failed for %s: %s", pdf_path, ex)
        return []
    return out
