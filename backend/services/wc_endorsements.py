"""wc_endorsements.py - the workers compensation policy's ENDORSEMENT SCHEDULE as
data (Brent, 19 Oct 2026: "Extract WC class codes, payroll, rates, experience mod
and endorsements from the supporting schedules ... keep the source and page
reference").

Read at merge, while the documents are in hand, into the private fact
``_wc_endorsements``: one row per scheduled form - {"state", "number", "title",
"edition", "source", "page"} - from the WC policy's own documents only (a
document whose coverage rows name the workers compensation line and no other,
`wc_premiums._wc_documents`). Transcribed, never inferred:

  * only a page that prints an endorsement-schedule heading is read;
  * a row is a schedule TABLE row (the OCR layer's "|" table) carrying a form
    number, a title and an EDITION - the edition is what every endorsement
    schedule prints and what a page footer or a heading never does;
  * with no table on the page, only lines whose number is an NCCI form number
    ("WC 00 03 13", "WC000414A") are read - a carrier's own numbering is too
    loose to split from its title without the table's columns.

ACORD 130 has no box per endorsement: its one-line "SPECIFY ADDITIONAL COVERAGES /
ENDORSEMENTS (Attach ACORD 101 ... if more space is required)" box points to the
ACORD 101 block that lists the whole schedule (`box_text`, `schedule_block`).
Nothing here is scored.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

KEY = "_wc_endorsements"
BOX = "WorkersCompensation_AdditionalCoverageEndorsementDescription_A"
BLOCK_HEADING = "WORKERS COMPENSATION ENDORSEMENT SCHEDULE (continued from ACORD 130)"

_SCHEDULE_HEADING_RE = re.compile(
    r"\bendorsement\s+schedule\b|\bschedule\s+of\s+(?:forms\s+and\s+)?endorsements\b|"
    r"\bforms\s+and\s+endorsements\b", re.I)
_TABLE_START_RE = re.compile(r"^\[Table\b")
_TABLE_END_RE = re.compile(r"^\[End table\]")
_EDITION_RE = re.compile(r"^\(?\d{2}[\s_/.-]?\d{2}(?:\d{2})?\)?$")
_STATE_RE = re.compile(r"^[A-Z]{2}$")
_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
_NCCI_LINE_RE = re.compile(
    r"^(?:(?P<state>[A-Z]{2})\s+)?(?P<number>WC\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-Z]?)\s+"
    r"(?P<title>[A-Za-z].*?)\s+(?P<edition>\(?\d{2}[\s_/.-]\d{2}(?:\d{2})?\)?)\s*$")


def _fv(facts: Any, key: str):
    v = (facts or {}).get(key) if isinstance(facts, dict) else None
    return v.get("value") if isinstance(v, dict) and "value" in v else v


def _title_ok(text: str) -> bool:
    words = re.findall(r"[A-Za-z]{2,}", text or "")
    return len(words) >= 2


def _number_ok(text: str) -> bool:
    t = (text or "").strip()
    return (bool(t) and any(c.isdigit() for c in t) and len(t) <= 24
            and len(t.split()) <= 3 and not _DATE_RE.search(t))


def _table_row(cells: List[str]) -> Optional[dict]:
    cells = [c.strip() for c in cells]
    while cells and not cells[-1]:
        cells.pop()
    if len(cells) < 3 or not _EDITION_RE.match(cells[-1]):
        return None
    edition, rest = cells[-1], cells[:-1]
    state = ""
    if len(rest) >= 3 and _STATE_RE.match(rest[0]):
        state, rest = rest[0], rest[1:]
    if len(rest) != 2:
        return None
    number, title = rest
    if not _number_ok(number) or not _title_ok(title):
        return None
    return {"state": state, "number": number, "title": title, "edition": edition.strip("()")}


def _page_rows(body: str) -> List[dict]:
    """The schedule rows one page prints: its "|" table rows, else NCCI lines."""
    rows: List[dict] = []
    in_table = False
    for line in body.splitlines():
        s = line.strip()
        if _TABLE_START_RE.match(s):
            in_table = True
            continue
        if _TABLE_END_RE.match(s):
            in_table = False
            continue
        if in_table and "|" in s:
            row = _table_row(s.split("|"))
            if row:
                rows.append(row)
    if rows:
        return rows
    for line in body.splitlines():
        m = _NCCI_LINE_RE.match(line.strip())
        if m and _title_ok(m.group("title")):
            rows.append({"state": m.group("state") or "", "number": m.group("number"),
                         "title": m.group("title").strip(), "edition": m.group("edition").strip("()")})
    return rows


def read_endorsement_schedule(docs: Any) -> List[dict]:
    """Every endorsement the WC policy's own documents schedule, in printed
    order, one per form number. [] when none prints. Never raises."""
    try:
        from services.extraction_service import _page_blocks
        from services.wc_premiums import _wc_documents
    except Exception as exc:                                  # noqa: BLE001
        logger.debug("wc_endorsements: readers unavailable (%s)", exc)
        return []
    active = [d for d in docs if isinstance(d, dict) and not d.get("excluded")] \
        if isinstance(docs, list) else []
    out: List[dict] = []
    seen: set = set()
    for doc in _wc_documents(active):
        name = str(doc.get("filename") or doc.get("name") or "").strip()
        for page, body in _page_blocks(doc.get("text")):
            if not _SCHEDULE_HEADING_RE.search(body or ""):
                continue
            for row in _page_rows(body):
                key = re.sub(r"[^A-Z0-9]", "", row["number"].upper())
                if not key or key in seen:
                    continue
                seen.add(key)
                out.append({**row, "source": name, "page": page})
    return out


def derive_wc_endorsements(mf: Any, docs: Any) -> Optional[List[dict]]:
    """Write ``mf["_wc_endorsements"]`` from the documents, or drop it when they
    schedule none (idempotent - every merge re-reads it). Returns what was
    stored."""
    if not isinstance(mf, dict):
        return None
    mf.pop(KEY, None)
    rows = read_endorsement_schedule(docs)
    if rows:
        mf[KEY] = rows
        logger.info("wc_endorsements: %d scheduled forms read from %s", len(rows),
                    sorted({r["source"] for r in rows}))
        return rows
    return None


def schedule(facts: Any) -> List[dict]:
    rows = _fv(facts, KEY)
    return [r for r in rows if isinstance(r, dict) and r.get("number")] \
        if isinstance(rows, list) else []


def _where(rows: List[dict]) -> str:
    """"25-26 Workers Compensation Policy.pdf pages 5-6" - each source and its pages."""
    by_source: Dict[str, List[int]] = {}
    for r in rows:
        if isinstance(r.get("page"), int):
            by_source.setdefault(str(r.get("source") or "the policy"), []).append(r["page"])
    parts = []
    for source, pages in by_source.items():
        p = sorted(set(pages))
        span = (f"page {p[0]}" if len(p) == 1 else
                f"pages {p[0]}-{p[-1]}" if p == list(range(p[0], p[-1] + 1)) else
                "pages " + ", ".join(str(x) for x in p))
        parts.append(f"{source} {span}")
    return "; ".join(parts)


def schedule_block(facts: Any) -> Optional[str]:
    """The ACORD 101 block listing the whole schedule, with its source and page."""
    rows = schedule(facts)
    if not rows:
        return None
    where = _where(rows)
    head = f"{BLOCK_HEADING} - {len(rows)} forms" + (f", {where}" if where else "") + ":"
    items = []
    for r in rows:
        bits = [r.get("state") or "", r["number"], r.get("title") or ""]
        item = " ".join(b for b in bits if b)
        if r.get("edition"):
            item += f" ({r['edition']})"
        items.append(item)
    return head + "\n" + "; ".join(items)


def box_text(facts: Any) -> Optional[str]:
    """ACORD 130's one-line endorsements box: where the schedule is listed."""
    rows = schedule(facts)
    if not rows:
        return None
    where = _where(rows)
    return (f"Endorsement schedule ({len(rows)} forms) - see ACORD 101"
            + (f"; source: {where}" if where else ""))
