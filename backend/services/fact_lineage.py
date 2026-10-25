"""Document + page attribution for the E&O audit export (client section 5).

WHAT THIS ANSWERS. Client 5.3-5.6: a material fact's lineage must be
recoverable down to "Document + Page", every supporting document must be
retained (5.4, never just the first), and "AI extraction from document" /
"Source: unspecified" are not acceptable final answers (5.5, 5.6).

WHY IT IS COMPUTED, NOT STORED. Both halves of the join already exist on the
session: each document row keeps its OWN extracted facts (``docs[i]["facts"]``,
extraction_pipeline.py) and its OWN OCR text with ``[Document page N]``
markers (ocr_service._PAGE_MARKER). The merge is what drops the origin
(extraction_service merge_facts) - so attribution is recovered here by
re-joining the merged value against each document's own record. Deterministic,
zero LLM cost, and it cannot drift from the documents because it reads them.

TWO DOORS ARE REUSED, NEVER REIMPLEMENTED:
  * "are these the same fact?"      -> services.fact_comparison.values_agree
    (C1 / D3: one comparison owner; tests/test_comparison_has_one_owner.py)
  * "is this literally in the text?" -> services.fact_state._verify_norm with
    the same _TEXT_VERIFY_MIN_CHARS floor annotate_text_verification uses -
    "CO" or "8" match every document by accident, and a false page citation
    in an E&O record is worse than none.

RIGHT-OR-BLANK APPLIES TO LINEAGE TOO. A page is cited only when the value is
literally locatable under a page marker; a document is cited only when its own
extraction carries an agreeing value or its text literally contains this one.
Anything less specific stays at the method label ("AI extraction from
document") rather than inventing a citation.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Tuple

from services.fact_comparison import values_agree
from services.fact_state import _verify_norm, _TEXT_VERIFY_MIN_CHARS

logger = logging.getLogger(__name__)

# ocr_service._PAGE_MARKER renders "[Document page {page}]"; multi-page only.
_PAGE_MARKER_RE = re.compile(r"\[Document page (\d+)\]")

# How many supporting documents a single fact row lists at most. Every doc in
# a normal package fits; this only guards a pathological 50-file upload from
# bloating one line of the record.
_MAX_SOURCES_PER_FACT = 10


def envelope_value(raw: Any) -> Any:
    """The value inside a provenance envelope, or the bare value itself."""
    if isinstance(raw, dict) and "value" in raw:
        return raw.get("value")
    return raw


def _markers_enabled() -> bool:
    """Whether ocr_service emits page markers - ITS flag, read lazily so this
    module never pays ocr_service's import cost unless asked. Defaults True
    (the shipped default) if the import fails."""
    try:
        from services.ocr_service import _PAGE_MARKERS_ON
        return bool(_PAGE_MARKERS_ON)
    except Exception:                                          # noqa: BLE001
        return True


def build_doc_index(docs: Optional[list]) -> List[dict]:
    """Pre-normalize each document once so per-fact lookups are substring scans.

    Returns one entry per non-excluded document:
      {"doc_id", "filename", "facts", "segments": [(page|None, norm_text)],
       "full_norm": str, "has_markers": bool}

    ``segments`` splits the stored OCR text on the ``[Document page N]``
    markers ocr_service emits for multi-page documents. A markerless document
    is provably SINGLE-PAGE while markers are enabled (ocr_service stamps
    every multi-page document that has any content), so its one segment cites
    page 1 - the client's own 5.4 example prints "COI.pdf - Page 1". Only
    when markers are disabled (OCR_PAGE_MARKERS=0, never the shipped default)
    does a markerless text decline to name a page, because it could then be a
    40-page document and a false citation is worse than none.
    """
    index: List[dict] = []
    for d in docs or []:
        if not isinstance(d, dict) or d.get("excluded"):
            continue
        text = str(d.get("text") or "")
        segments: List[tuple] = []
        matches = list(_PAGE_MARKER_RE.finditer(text))
        if matches:
            # Text before the first marker is header noise with no page claim.
            preamble = text[: matches[0].start()]
            if preamble.strip():
                segments.append((None, _verify_norm(preamble)))
            for i, m in enumerate(matches):
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                seg = text[m.end(): end]
                if seg.strip():
                    segments.append((int(m.group(1)), _verify_norm(seg)))
        else:
            if text.strip():
                segments.append((1 if _markers_enabled() else None,
                                 _verify_norm(text)))
        index.append({
            "doc_id":      d.get("doc_id"),
            "filename":    d.get("filename") or "(unnamed)",
            "facts":       d.get("facts") if isinstance(d.get("facts"), dict) else {},
            "segments":    segments,
            "full_norm":   "".join(s for _, s in segments),
            "has_markers": bool(matches),
        })
    return index


def _locate_page(needle_norm: str, entry: dict) -> Optional[int]:
    """First page whose normalized segment contains the needle, else None."""
    if not needle_norm or len(needle_norm) < _TEXT_VERIFY_MIN_CHARS:
        return None
    for page, seg in entry["segments"]:
        if page is not None and needle_norm in seg:
            return page
    return None


def _literally_present(needle_norm: str, entry: dict) -> bool:
    if not needle_norm or len(needle_norm) < _TEXT_VERIFY_MIN_CHARS:
        return False
    return needle_norm in entry["full_norm"]


def scalar_sources(fact_key: str, value: Any, doc_index: List[dict]) -> List[dict]:
    """Every document that supports one scalar fact value (5.4: all of them).

    Two independent ways a document supports a value, tried in order:
      1. its OWN per-document extraction carries an agreeing value
         (fact_comparison decides "agreeing" - "$1,000,000" vs "1000000");
      2. the value is literally printed in its stored OCR text.
    The page is then located from whichever printing is actually findable -
    the document's own raw printing first, since the merged value may have
    been normalized away from what the page prints.
    """
    val_str = str(value if value is not None else "").strip()
    if not val_str:
        return []
    merged_norm = _verify_norm(val_str)
    out: List[dict] = []
    for entry in doc_index:
        own_raw = entry["facts"].get(fact_key)
        own_val = envelope_value(own_raw)
        own_scalar = (own_val is not None
                      and not isinstance(own_val, (list, dict, bool))
                      and str(own_val).strip())
        agrees = False
        if own_scalar:
            try:
                agrees = values_agree(fact_key, val_str, str(own_val))
            except Exception:                                  # noqa: BLE001
                agrees = False
        page = None
        if agrees:
            page = _locate_page(_verify_norm(str(own_val)), entry)
        if page is None:
            page = _locate_page(merged_norm, entry)
        if agrees:
            out.append({"doc_id": entry["doc_id"], "filename": entry["filename"],
                        "page": page, "method": "extracted"})
        elif page is not None or _literally_present(merged_norm, entry):
            out.append({"doc_id": entry["doc_id"], "filename": entry["filename"],
                        "page": page, "method": "text"})
        if len(out) >= _MAX_SOURCES_PER_FACT:
            break
    return out


def list_sources(fact_key: str, value: Any, doc_index: List[dict]) -> List[dict]:
    """Documents that contributed rows to a list/schedule fact (5.6).

    A list has no single literal printing to page-locate, and inventing per-row
    pages would be guesswork. What IS provable: which documents' own
    extractions carry rows for this key, and how many. That names the source
    document - the client's 5.6 ask for schedules, coverage lines, symbols.
    """
    out: List[dict] = []
    for entry in doc_index:
        own = envelope_value(entry["facts"].get(fact_key))
        if isinstance(own, list) and own:
            out.append({"doc_id": entry["doc_id"], "filename": entry["filename"],
                        "page": None, "method": "extracted",
                        "rows": len(own)})
        if len(out) >= _MAX_SOURCES_PER_FACT:
            break
    return out


def dict_sources(fact_key: str, doc_index: List[dict]) -> List[dict]:
    """Documents whose own extraction carries a non-empty structured value for
    this key (risk_transfer and friends). Same contribution logic as lists,
    minus the row count - a mapping has no meaningful row number."""
    out: List[dict] = []
    for entry in doc_index:
        own = envelope_value(entry["facts"].get(fact_key))
        if isinstance(own, dict) and own:
            out.append({"doc_id": entry["doc_id"], "filename": entry["filename"],
                        "page": None, "method": "extracted"})
        if len(out) >= _MAX_SOURCES_PER_FACT:
            break
    return out


def sources_for_fact(fact_key: str, raw: Any, doc_index: List[dict]) -> List[dict]:
    """Dispatch: scalar facts get value+page attribution, lists get row counts,
    structured dicts get contribution attribution."""
    try:
        value = envelope_value(raw)
        if isinstance(value, list):
            return list_sources(fact_key, value, doc_index)
        if isinstance(value, dict):
            return dict_sources(fact_key, doc_index)
        if isinstance(value, bool) or value is None:
            return []
        # A two-way boolean's "No" has no document behind it: each document's
        # own False is its silence (B8), so citing it as "extracted" support
        # is a false citation - and a person's No came from the person.
        # Right-or-blank (module docstring) - no citation.
        try:
            from services.extraction_service import unevidenced_boolean_negative
            if unevidenced_boolean_negative(fact_key, value):
                return []
        except Exception:                                      # noqa: BLE001
            pass
        return scalar_sources(fact_key, value, doc_index)
    except Exception as ex:                                    # noqa: BLE001
        # Lineage is additive evidence for the record - a failure here must
        # never break the export itself (D35: but say so, with the trace).
        logger.warning("fact_lineage failed for %s: %s", fact_key, ex,
                       exc_info=True)
        return []


# A money figure as printed: grouped ("1,425.00") or plain ("1425", "425.00"),
# never the middle of a longer number or a date.
_MONEY_TOKEN_RE = re.compile(r"(?<![\d,./])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?(?![\d,/]|\.\d)")
_AMOUNT_TEXT_RE = re.compile(r"^\$?\s?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{2})?$")


def _cents(whole: str, frac: Optional[str]) -> int:
    return int(whole.replace(",", "")) * 100 + int(frac or 0)


# 16 documents (19 Oct 2026): a stored text runs to ~700k characters and each
# entry keeps a normalized copy too; one package's table reads about seven.
@lru_cache(maxsize=16)
def _marked_pages(text: str) -> Tuple[Tuple[int, str, frozenset], ...]:
    """(printed page number, verify-normalized text, every money figure the page
    prints in cents) for every marked page of one document's stored text.
    Cached by the text itself: a request locates many values in the same few
    documents."""
    out: List[Tuple[int, str, frozenset]] = []
    matches = list(_PAGE_MARKER_RE.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        seg = text[m.end(): end]
        if seg.strip():
            amounts = frozenset(_cents(a, c) for a, c in _MONEY_TOKEN_RE.findall(seg))
            out.append((int(m.group(1)), _verify_norm(seg), amounts))
    return tuple(out)


def locate_page(text: Any, value: Any, near: Iterable[Any] = ()) -> Optional[int]:
    """The printed page of a document's stored text that prints ``value`` - an
    amount only as the SAME number, read as a whole printed figure ("425.00"
    is never the tail of "1,425.00", and "$1,000,000" is "1000000"), any other
    value literally (`_verify_norm`, the 4-character floor) - and, when
    ``near`` is given, also one of those words (the line's or the label's own
    name), so a figure printed beside another line is never cited (Brent,
    19 Oct 2026: "keep the source and page reference for every extracted
    coverage and limit").

    None when the text carries no page markers (a long .txt upload is not
    "page 1"), when nothing matches, or for a value too short to locate."""
    raw = str(text or "")
    val = str(value if value is not None else "").strip()
    if not raw or not val:
        return None
    pages = _marked_pages(raw)
    if not pages:
        return None
    nears = [n for n in (_verify_norm(str(x)) for x in (near or ()) if x)
             if len(n) >= _TEXT_VERIFY_MIN_CHARS]
    if _AMOUNT_TEXT_RE.match(val):
        m = _MONEY_TOKEN_RE.search(val.replace("$", "").replace(" ", ""))
        if not m:
            return None
        target = _cents(m.group(1), m.group(2))
        if target <= 0:
            return None                       # a zero is printed everywhere
        if target < 100_000 and not nears:
            return None                       # under $1,000: too common to cite alone

        def _has(p) -> bool:
            return target in p[2]
    else:
        needle = _verify_norm(val)
        if len(needle) < _TEXT_VERIFY_MIN_CHARS:
            return None

        def _has(p) -> bool:
            return needle in p[1]
    for p in pages:
        if _has(p) and (not nears or any(n in p[1] for n in nears)):
            return p[0]
    return None


def format_source(src: dict) -> str:
    """One human line: 'Package Policy.pdf - page 14' / 'COI.pdf'."""
    name = src.get("filename") or "(unnamed)"
    page = src.get("page")
    rows = src.get("rows")
    label = f"{name} - page {page}" if page else name
    if rows:
        label += f" ({rows} row(s))"
    return label
