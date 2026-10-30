"""One uploaded ACORD document's readings, settled before the merge (29 Oct 2026).

Three repairs, each on the document's OWN facts (the stored per-document copy),
idempotent, never raising:

  * ADDRESS BLOCKS (item 9). The newest ACORD 125 prints the insured's name,
    street, suite, city, state and ZIP in ONE block box; the ASG Transcriber
    returns the block AND the separate parts, and the reader appended the parts
    again ("4150 S Kalamath St\\nSuite 210\\nDenver CO 80223, Suite 210, Denver,
    CO 80223"). An address fact holding a block is parsed ONCE into its parts
    (`parse_address_block`) and recomposed; a part already in the block is never
    re-appended. `read._compose_address` uses the same parser for new readings.
  * THE APPLICANT'S ROW-A BOXES (item 8). The 125's BUSINESS PHONE # box (and the
    other row-A applicant boxes - the stamper's own table `pdf_service.
    _APPLICANT_ROW_A_FACTS`) had no reverse mapping, so an outside 125's phone was
    only carried box-to-box and no comparison saw it. New readings map it
    (`reverse_map.applicant_row_a_targets`); a document read before that keeps it
    under `acord.carried` and is promoted here.
  * THE BUSINESS TOTALS ON THE PREMISES ROWS (item 8). The newest 125 prints
    revenue and full / part-time staff PER LOCATION. With one location that row
    IS the business; with several, the business is their SUM (a premises' value
    is counted once, however many buildings repeat it). The document's
    `total_revenue` / `num_employees_full_time` / `num_employees_part_time` /
    `num_employees` are derived from them when the document does not state them
    itself, marked `derived_from: "location_rows"`, so the Data Consistency
    comparison sees the ACORD's figure beside the declarations'. A derived sum
    never outvotes a stated total (`merge_rules.apply_owner_rules`).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DERIVED_FROM_LOCATIONS = "location_rows"
_ADDRESS_FACTS = ("mailing_address", "physical_address", "producer_address")
_STREET_RE = re.compile(
    r"^\s*(\d|p\.?\s*o\.?\s*box\b|po box\b|one |two |rural route|r\.?r\.?\s*\d|route\b|rte\b|"
    r"highway|hwy\b|c/o\b)", re.I)
_CITY_LINE_RE = re.compile(
    r"^(?P<city>[A-Za-z][A-Za-z .'\-]*?)[,\s]+(?P<state>[A-Z]{2})\.?[,\s]+(?P<zip>\d{5}(?:-\d{4})?)\s*$")


def _fv(v: Any) -> Any:
    return v.get("value") if isinstance(v, dict) and "value" in v else v


def _empty(v: Any) -> bool:
    v = _fv(v)
    return v is None or (isinstance(v, str) and not v.strip()) or v in ([], {})


# ── Address blocks ───────────────────────────────────────────────────────────
def parse_address_block(block: Any) -> Dict[str, str]:
    """{line1, line2, city, state, zip} of a multi-line address block, read ONCE.

    Lines before the first street line are a name / attention line (a producer
    block prints the agency's name first) and are not part of the address. The
    last line is "City ST ZIP" when it reads so; otherwise the lines are joined
    and read by the one comma-address parser (`utils.helpers._parse_address`).
    {} when `block` is not a multi-line block."""
    text = str(_fv(block) or "")
    if "\n" not in text:
        return {}
    lines = [ln.strip(" ,") for ln in text.split("\n") if ln.strip(" ,")]
    if not lines:
        return {}
    start = next((i for i, ln in enumerate(lines) if _STREET_RE.match(ln)), 0)
    lines = lines[start:]
    m = _CITY_LINE_RE.match(lines[-1]) if len(lines) >= 2 else None
    if m:
        out = {"line1": lines[0], "city": m.group("city").strip(" ,"), "state": m.group("state"),
               "zip": m.group("zip")}
        if len(lines) > 2:
            out["line2"] = ", ".join(lines[1:-1])
        return out
    try:
        from utils.helpers import _parse_address
        return {k: v for k, v in (_parse_address(", ".join(lines)) or {}).items() if v}
    except Exception:                                          # noqa: BLE001
        return {"line1": lines[0]}


def _norm(v: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(v or "").lower())


def merge_address_parts(block_parts: Dict[str, str], parts: Dict[str, str]) -> Dict[str, str]:
    """The block's street line, with the form's SEPARATE boxes (suite, city,
    state, ZIP - each cleanly delimited) over the block's own reading of them;
    a part neither states stays out. Each part once."""
    out = dict(block_parts)
    for k, v in (parts or {}).items():
        if v and (k != "line1" or not out.get("line1")):
            out[k] = v
    return out


def compose_address(parts: Dict[str, str]) -> str:
    """"line1, line2, City, ST ZIP" (the shape `_parse_address` reads back)."""
    line = ", ".join(x for x in (parts.get("line1"), parts.get("line2")) if x)
    tail = " ".join(x for x in (parts.get("state"), parts.get("zip")) if x)
    rest = ", ".join(x for x in (parts.get("city") or "", tail) if x)
    return ", ".join(x for x in (line, rest) if x)


def repair_block_address(value: Any) -> Optional[str]:
    """A stored address holding a block plus its re-appended parts, as ONE clean
    address; None when `value` holds no block. The text after the block's last
    line (", Suite 210, Denver, CO 80223") is the separate parts the reader
    appended - used only for a part the block does not state."""
    text = str(_fv(value) or "")
    if "\n" not in text:
        return None
    head, _, last = text.rpartition("\n")
    # The block's last line ends where its "City ST ZIP" ends ("Denver CO 80223"
    # or "Denver, CO 80223"); what follows is what the reader appended.
    pieces = last.split(", ")
    cut = next((i for i in range(1, len(pieces) + 1) if _CITY_LINE_RE.match(", ".join(pieces[:i]))), 1)
    last_line, appended = ", ".join(pieces[:cut]), ", ".join(pieces[cut:])
    block_parts = parse_address_block(head + "\n" + last_line)
    if not block_parts:
        return None
    extra: Dict[str, str] = {}
    if appended:
        try:
            from utils.helpers import _parse_address
            tail = _parse_address("x, " + appended) or {}
            extra = {k: v for k, v in tail.items() if k != "line1" and v}
        except Exception:                                      # noqa: BLE001
            extra = {}
    return compose_address(merge_address_parts(block_parts, extra)) or None


# ── Business totals off the premises rows ────────────────────────────────────
def _amount(v: Any) -> Optional[float]:
    m = re.search(r"\d[\d,]*(?:\.\d+)?", str(_fv(v) or ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _premises_key(row: dict) -> str:
    loc = _norm(_fv(row.get("location_number")) or _fv(row.get("premises_number"))).lstrip("0")
    if loc:
        return "loc:" + loc
    street = _norm(_fv(row.get("address_line1")) or str(_fv(row.get("address")) or "").split(",")[0])
    return "addr:" + street if street else ""


def location_totals(rows: Any) -> Dict[str, float]:
    """{revenue, full_time, part_time}: the business totals the premises rows
    state - each premises counted once (the first building that states it)."""
    cols = {"revenue": "annual_revenue", "full_time": "full_time_employees",
            "part_time": "part_time_employees"}
    per: Dict[str, Dict[str, float]] = {}
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        key = _premises_key(r) or f"row:{id(r)}"
        for name, col in cols.items():
            amt = _amount(r.get(col))
            if amt is not None and name not in per.setdefault(key, {}):
                per[key][name] = amt
    out: Dict[str, float] = {}
    for vals in per.values():
        for name, amt in vals.items():
            out[name] = out.get(name, 0.0) + amt
    return out


def _derived_env(value: str, like: Optional[dict]) -> dict:
    env = {k: v for k, v in (like or {}).items() if k in ("source", "confidence", "acord_form", "page")}
    env.setdefault("source", "acord_form")
    env.update({"value": value, "derived_from": DERIVED_FROM_LOCATIONS})
    return env


def _is_derived(v: Any) -> bool:
    return isinstance(v, dict) and v.get("derived_from") == DERIVED_FROM_LOCATIONS


def _derive_totals(facts: dict) -> List[str]:
    rows = _fv(facts.get("property_locations"))
    totals = location_totals(rows)
    if not totals:
        return []
    like = facts.get("property_locations") if isinstance(facts.get("property_locations"), dict) else None
    if like is None:
        like = next((v for v in facts.values() if isinstance(v, dict) and v.get("source")), None)
    moved: List[str] = []
    want: Dict[str, str] = {}
    if "revenue" in totals:
        want["total_revenue"] = f"${totals['revenue']:,.0f}"
    ft, pt = totals.get("full_time"), totals.get("part_time")
    if ft is not None:
        want["num_employees_full_time"] = f"{ft:,.0f}"
    if pt is not None:
        want["num_employees_part_time"] = f"{pt:,.0f}"
    if ft is not None or pt is not None:
        want["num_employees"] = f"{(ft or 0) + (pt or 0):,.0f}"
    for key, val in want.items():
        held = facts.get(key)
        if not _empty(held) and not _is_derived(held):
            continue                          # the document states it itself
        if _is_derived(held) and _fv(held) == val:
            continue
        facts[key] = _derived_env(val, like)
        moved.append(key)
    return moved


# ── The applicant's row-A boxes read before they were mapped ─────────────────
def _promote_row_a_carried(doc: dict) -> List[str]:
    try:
        from services.acord_intake.reverse_map import applicant_row_a_targets
        from services.acord_intake.read import fits_fact
    except Exception:                                          # noqa: BLE001
        return []
    facts = doc.get("facts")
    moved: List[str] = []
    for form_key, boxes in ((doc.get("acord") or {}).get("carried") or {}).items():
        if not isinstance(boxes, dict) or "#" in str(form_key):
            continue
        for box, val in boxes.items():
            for t in applicant_row_a_targets(box):
                key = t.get("fact")
                v = str(val or "").strip()
                if key and v and _empty(facts.get(key)) and fits_fact(key, v):
                    facts[key] = {"value": v, "source": "acord_form", "confidence": "ai_high",
                                  "acord_form": form_key, "box": box}
                    moved.append(key)
    return moved


def settle_acord_document(doc: dict) -> List[str]:
    """Settle one ACORD document's own facts (see the module docstring). Returns
    the keys changed. Never raises."""
    moved: List[str] = []
    try:
        facts = doc.get("facts") if isinstance(doc, dict) else None
        if not isinstance(facts, dict):
            return moved
        for key in _ADDRESS_FACTS:
            held = facts.get(key)
            fixed = repair_block_address(held)
            if fixed and fixed != _fv(held):
                facts[key] = dict(held, value=fixed) if isinstance(held, dict) else fixed
                moved.append(key)
        moved.extend(_promote_row_a_carried(doc))
        moved.extend(_derive_totals(facts))
        if moved:
            logger.info("acord settle: %s - %s", doc.get("filename"), sorted(set(moved)))
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("acord settle skipped for %s: %s", (doc or {}).get("filename"), exc)
    return moved
