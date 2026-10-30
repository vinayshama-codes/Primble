"""Schedule rows two documents state differently (item 4, 29 Oct 2026).

A schedule row - a vehicle, a driver, a building, a claim - is often printed by
two documents: the declarations (or the carrier's loss run) and an ACORD form
an agency filled. The merge keeps ONE row per thing (`acord_intake.merge_rules.
fold_rows`). When the two documents state a CELL of that row differently (a
VIN character, a driver's birth date, a building's area, a claim's paid
amount), the merge used to keep one value silently - or, worse, two rows.

This module, for every merged row:
  * finds the row each document prints for the same thing (`_match_rows`:
    VIN, truncated or one-character-off VIN; licence, else a name listed once;
    location + building, else street + building; claim number, else date of
    loss + line);
  * keeps the AUTHORITATIVE value in the cell - the owner table: the
    declarations / the carrier's loss run for current-policy and claim facts,
    over an ACORD form or application; a person's table beats both (a table a
    person saved is never judged here);
  * records the other documents' values on the row:
        row["_rivals"][col] = {"kept":   {"value", "documents": [...]},
                               "others": [{"value", "documents": [...]}]}
  * turns each into a ROW-LEVEL Data Consistency card
    ("<schedule> row <n> (<row label>): <column>") whose pick writes that one
    cell (`row_fields`, `apply_row_confirmations`). The card holds 85 like any
    Data Consistency card and carries its points through the plan's "dc" item
    (`stops_now.underwriting_conflict_stops` reads it like any picker row).

Never raises: every entry point logs and returns what it has.
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ROW_KEY_PREFIX = "row:"
RIVALS_KEY = "_rivals"

# list -> (columns compared, {column: kind}). Only cells that are FACTS about the
# row's thing: a description ("Cargo Van" vs "Van") or a construction class
# ("JM" vs "Joisted Masonry") is wording, not a disagreement.
_COMPARED: Dict[str, Dict[str, str]] = {
    "auto_vin_schedule": {"vin": "vin", "year": "year", "cost_new": "money"},
    "auto_drivers": {"dob": "date", "license_number": "id", "license_state": "id", "hire_date": "date"},
    "property_locations": {"total_building_area": "count", "year_built": "year", "roof_year": "year"},
    "loss_history": {"paid": "money", "reserved_amount": "money"},
}
_EXTRA_LABELS = {"cost_new": "Cost new", "total_building_area": "Building area"}
_LIST_FORMS = {"auto_vin_schedule": ["ACORD_127"], "auto_drivers": ["ACORD_127"],
               "property_locations": ["ACORD_125", "ACORD_140"], "loss_history": ["ACORD_125"]}


def _fv(v: Any) -> Any:
    return v.get("value") if isinstance(v, dict) and "value" in v else v


def _empty(v: Any) -> bool:
    v = _fv(v)
    return v is None or (isinstance(v, str) and not v.strip()) or v in ([], {})


def _norm(v: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(_fv(v) or "").lower())


def _norm_cell(kind: str, v: Any) -> str:
    """The comparable form of one cell; "" = nothing stated."""
    if _empty(v):
        return ""
    raw = str(_fv(v)).strip()
    if kind in ("money", "count"):
        m = re.search(r"\d[\d,]*(?:\.\d+)?", raw)
        if not m:
            return ""
        n = m.group(0).replace(",", "")
        n = re.sub(r"\.0+$", "", n)
        return n.lstrip("0") or "0"
    if kind == "date":
        try:
            from services.normalization import normalize_date
            return normalize_date(raw) or _norm(raw)
        except Exception:                                      # noqa: BLE001
            return _norm(raw)
    if kind == "vin":
        return _norm(raw).upper()
    if kind == "year":
        m = re.search(r"(?:19|20)\d{2}", raw)
        return m.group(0) if m else _norm(raw)
    return _norm(raw)


def _shown_cell(kind: str, v: Any) -> str:
    """One printing per kind on the card (end-user review, 29 Oct 2026): the
    claim read "Loss Runs: $18,420; Commercial Insurance Application: 14,820" -
    the same amount column shown two ways. A money cell that is one plain
    number prints "$n,nnn"; anything else prints as the document has it."""
    raw = str(_fv(v) if _fv(v) is not None else "").strip()
    if kind != "money" or not re.fullmatch(r"\$?\s*\d[\d,]*(?:\.\d+)?", raw):
        return raw
    n = _norm_cell("money", raw)
    try:
        whole, _, cents = n.partition(".")
        out = f"${int(whole):,}"
        return out + (f".{cents}" if cents else "")
    except ValueError:
        return raw


def _same_cell(kind: str, a: str, b: str) -> bool:
    if a == b:
        return True
    if kind == "vin" and a and b:
        # A VIN printed short (a narrow column dropped characters) is the same
        # VIN when it is the start of the other - truncation, not a rival.
        short, long_ = sorted((a, b), key=len)
        return len(short) >= 11 and long_.startswith(short)
    return False


# ── Which documents may say what ─────────────────────────────────────────────
def _tier(doc: dict, list_key: str) -> int:
    """Authority of a document's row (owner table): the carrier's loss run for a
    claim, the declarations for a current-policy schedule, then everything that
    is not an ACORD form / application, then the ACORD form."""
    try:
        from services.acord_intake.merge_rules import is_acord_doc, is_application_doc
        acord = is_acord_doc(doc) or is_application_doc(doc)
    except Exception:                                          # noqa: BLE001
        acord = False
    dt = str(doc.get("doc_type") or "").lower()
    if acord:
        return 1
    if list_key == "loss_history" and dt == "loss_run":
        return 4
    if dt in ("dec_page", "policy", "binder", "endorsement", "schedule"):
        return 3
    return 2


def _doc_rows(doc: dict, list_key: str) -> List[dict]:
    held = _fv((doc.get("facts") or {}).get(list_key))
    return [r for r in held if isinstance(r, dict)] if isinstance(held, list) else []


# ── Is this document's row the merged row's thing? ───────────────────────────
def _street(row: dict) -> str:
    line1 = row.get("address_line1")
    if _empty(line1) and not _empty(row.get("address")):
        try:
            from utils.helpers import _parse_address
            line1 = (_parse_address(str(_fv(row.get("address")))) or {}).get("line1")
        except Exception:                                      # noqa: BLE001
            line1 = str(_fv(row.get("address"))).split(",")[0]
    return _norm(line1)


def _num(v: Any) -> str:
    n = _norm(v).lstrip("0")
    return n or ("0" if _norm(v) else "")


def _tiers_of_match(list_key: str, m: dict, r: dict) -> int:
    """0 = not the same thing; otherwise how strong the match is (higher first)."""
    from services.acord_intake import merge_rules as MR
    if list_key == "auto_vin_schedule":
        vm, vr = MR._vin_key(m.get("vin")), MR._vin_key(r.get("vin"))
        if vm and vr:
            if vm == vr:
                return 3
            if MR._truncated_vin_of(m, r):
                return 2
            return 1 if MR.near_vin_same_vehicle(m, r) else 0
        return 1 if MR._describes_same_vehicle(m, r) else 0
    if list_key == "auto_drivers":
        lm, lr = _norm(m.get("license_number")), _norm(r.get("license_number"))
        if lm and lr:
            return 3 if lm == lr else 0
        nm = MR._name_tokens(m.get("name"))
        if not (len(nm) >= 2 and nm == MR._name_tokens(r.get("name"))):
            return 0
        # Without a licence on both, a birth date that differs is another person.
        if not _empty(m.get("dob")) and not _empty(r.get("dob")) and not MR._same_day(m.get("dob"), r.get("dob")):
            return 0
        return 1
    if list_key == "property_locations":
        lm, lr = _num(m.get("location_number")), _num(r.get("location_number"))
        bm, br = _num(m.get("building_number")) or "1", _num(r.get("building_number")) or "1"
        if bm != br:
            return 0
        sm, sr = _street(m), _street(r)
        if sm and sr:
            if sm != sr:
                return 0
            return 3 if (lm and lr and lm == lr) else 2
        return 1 if (lm and lr and lm == lr) else 0
    if list_key == "loss_history":
        nm, nr = _norm(m.get("claim_number")), _norm(r.get("claim_number"))
        if nm and nr:
            return 3 if nm == nr else 0
        return 1 if MR.same_claim_event(m, r) else 0
    return 0


def _match_rows(list_key: str, merged_row: dict, rows: List[dict]) -> Optional[dict]:
    """The ONE row of `rows` (one document's list) describing `merged_row`; None
    when none, or when two rows tie at the strongest match (blank over wrong)."""
    best, hits = 0, []
    for r in rows:
        t = _tiers_of_match(list_key, merged_row, r)
        if t > best:
            best, hits = t, [r]
        elif t and t == best:
            hits.append(r)
    if len(hits) > 1 and list_key == "loss_history":
        from services.acord_intake.merge_rules import _describes_same_claim
        hits = [r for r in hits if _describes_same_claim(merged_row, r)]
    if len(hits) > 1 and list_key == "auto_drivers":
        return None
    return hits[0] if len(hits) == 1 else None


# ── Recording the rivals at the merge ────────────────────────────────────────
def _doc_ref(doc: dict) -> dict:
    return {"doc_id": doc.get("doc_id"), "filename": doc.get("filename"),
            "doc_type": doc.get("doc_type")}


def attach_row_rivals(merged: Dict[str, Any], docs: List[dict]) -> List[str]:
    """Record, on every merged schedule row, the cells another document states
    differently, and keep the authoritative value in the cell. Returns
    "<list>#<n>.<col>" for every cell with a rival. A table a person saved is not
    judged (a person beats both). Never raises."""
    out: List[str] = []
    try:
        active = [d for d in docs or [] if isinstance(d, dict) and not d.get("excluded")]
        if len(active) < 2:
            return out
        for list_key, cols in _COMPARED.items():
            held = merged.get(list_key)
            rows = _fv(held)
            if not isinstance(rows, list) or not rows:
                continue
            try:
                from services.schedule_capture import human_rows
                if human_rows(merged, list_key)[0] is not None:
                    continue
            except Exception:                                  # noqa: BLE001
                pass
            per_doc = [(d, _doc_rows(d, list_key)) for d in active]
            per_doc = [(d, rs) for d, rs in per_doc if rs]
            if len(per_doc) < 2:
                for r in rows:
                    if isinstance(r, dict):
                        r.pop(RIVALS_KEY, None)
                continue
            for n, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                row.pop(RIVALS_KEY, None)
                matched = []
                for d, rs in per_doc:
                    hit = _match_rows(list_key, row, rs)
                    if hit is not None:
                        matched.append((d, hit))
                if len(matched) < 2:
                    continue
                rivals: Dict[str, dict] = {}
                for col, kind in cols.items():
                    said: Dict[str, dict] = {}
                    for d, r in matched:
                        nv = _norm_cell(kind, r.get(col))
                        if not nv:
                            continue
                        slot = next((k for k in said if _same_cell(kind, k, nv)), None)
                        if slot is None:
                            said[nv] = {"value": str(_fv(r.get(col))).strip(), "documents": [],
                                        "tier": 0}
                            slot = nv
                        elif kind == "vin" and len(nv) > len(slot):
                            # the full VIN stands for its truncated printing
                            said[nv] = dict(said.pop(slot), value=str(_fv(r.get(col))).strip())
                            slot = nv
                        said[slot]["documents"].append(_doc_ref(d))
                        said[slot]["tier"] = max(said[slot]["tier"], _tier(d, list_key))
                    if len(said) < 2:
                        continue
                    # The kept value: the most authoritative document's. A tie in
                    # authority keeps what the merge already holds.
                    cur = _norm_cell(kind, row.get(col))
                    top = max(v["tier"] for v in said.values())
                    best = [k for k, v in said.items() if v["tier"] == top]
                    keep = next((k for k in best if cur and _same_cell(kind, k, cur)), best[0])
                    if not (cur and _same_cell(kind, keep, cur)):
                        row[col] = said[keep]["value"]
                    rivals[col] = {
                        "kept": {"value": said[keep]["value"], "documents": said[keep]["documents"]},
                        "others": [{"value": v["value"], "documents": v["documents"]}
                                   for k, v in said.items() if k != keep],
                    }
                    out.append(f"{list_key}#{n + 1}.{col}")
                if rivals:
                    row[RIVALS_KEY] = rivals
        if out:
            logger.info("row rivals: %d cell(s) two documents state differently: %s", len(out), out[:12])
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("row rivals: skipped (%s)", exc)
    return out


# ── The Data Consistency card ────────────────────────────────────────────────
def is_row_key(key: Any) -> bool:
    return str(key or "").startswith(ROW_KEY_PREFIX)


def _card_hash(list_key: str, col: str, rival: dict) -> str:
    kind = _COMPARED.get(list_key, {}).get(col, "id")
    vals = sorted({_norm_cell(kind, rival["kept"]["value"])}
                  | {_norm_cell(kind, o["value"]) for o in rival.get("others") or []})
    return hashlib.sha256("|".join([list_key, col] + vals).encode()).hexdigest()[:10]


def row_key(list_key: str, col: str, rival: dict) -> str:
    """The card's key: stable across re-merges (the schedule, the column and the
    values the documents disagree between - never a row POSITION)."""
    return f"{ROW_KEY_PREFIX}{list_key}:{col}:{_card_hash(list_key, col, rival)}"


def parse_row_key(key: Any) -> Optional[Tuple[str, str, str]]:
    s = str(key or "")
    if not is_row_key(s):
        return None
    parts = s[len(ROW_KEY_PREFIX):].split(":")
    if len(parts) != 3 or parts[0] not in _COMPARED or parts[1] not in _COMPARED[parts[0]]:
        return None
    return parts[0], parts[1], parts[2]


def _schedule_label(list_key: str) -> str:
    try:
        from services.schedule_capture import SCHEDULE_DEFS
        return str(SCHEDULE_DEFS[list_key]["label"])
    except Exception:                                          # noqa: BLE001
        return list_key.replace("_", " ").capitalize()


def _column_label(list_key: str, col: str) -> str:
    try:
        from services.schedule_capture import SCHEDULE_DEFS
        for c in SCHEDULE_DEFS[list_key]["columns"]:
            if c["key"] == col:
                return str(c["label"])
    except Exception:                                          # noqa: BLE001
        pass
    return _EXTRA_LABELS.get(col) or col.replace("_", " ").capitalize()


def row_label(list_key: str, row: dict) -> str:
    """How a person recognises the row: a vehicle's year / make / model, a
    driver's name, a building's LOC / BLDG and street, a claim's date and line."""
    g = lambda k: str(_fv(row.get(k)) or "").strip()             # noqa: E731
    if list_key == "auto_vin_schedule":
        return " ".join(x for x in (g("year"), g("make"), g("model")) if x) or "vehicle"
    if list_key == "auto_drivers":
        return g("name") or "driver"
    if list_key == "property_locations":
        street = g("address_line1") or g("address").split(",")[0]
        # LOC # is the premises' number (buildings at one premises share it -
        # `extraction_service.assign_location_numbers`), BLDG # the building.
        num = " ".join(x for x in (f"Loc {g('location_number')}" if g("location_number") else "",
                                   f"Bldg {g('building_number')}" if g("building_number") else "") if x)
        return " - ".join(x for x in (num, street) if x) or "location"
    if list_key == "loss_history":
        return " ".join(x for x in (g("date"), g("line_of_business"), "claim",
                                    g("claim_number")) if x)
    return "row"


def _doc_type_label(dt: Any) -> str:
    try:
        from services.extraction_service import DOC_TYPE_LABELS
        return DOC_TYPE_LABELS.get(str(dt or ""), str(dt or "").replace("_", " ").title())
    except Exception:                                          # noqa: BLE001
        return str(dt or "")


def _source(ref: dict, value: str) -> dict:
    return {"doc_id": ref.get("doc_id"), "filename": ref.get("filename"),
            "doc_type": ref.get("doc_type"), "doc_type_label": _doc_type_label(ref.get("doc_type")),
            "raw": value, "source_method": "schedule_row"}


def row_fields(merged: Optional[dict], confirmations: Optional[dict] = None) -> List[dict]:
    """The row-level Data Consistency rows for `merged`'s schedules, in the
    picker's own field shape (`underwriting_consistency` fields)."""
    out: List[dict] = []
    merged = merged or {}
    conf = confirmations or {}
    try:
        from services.schedule_capture import human_rows
    except Exception:                                          # noqa: BLE001
        human_rows = None
    for list_key in _COMPARED:
        rows = _fv(merged.get(list_key))
        if not isinstance(rows, list):
            continue
        if human_rows is not None:
            try:
                if human_rows(merged, list_key)[0] is not None:
                    continue                        # a person's table beats both
            except Exception:                                  # noqa: BLE001
                pass
        for n, row in enumerate(rows):
            rivals = row.get(RIVALS_KEY) if isinstance(row, dict) else None
            if not isinstance(rivals, dict):
                continue
            for col, rv in rivals.items():
                if not isinstance(rv, dict) or not rv.get("others") or col not in _COMPARED[list_key]:
                    continue
                key = row_key(list_key, col, rv)
                picked = conf.get(key)
                picked = _fv(picked) if picked is not None else None
                choices = [rv["kept"]] + list(rv["others"])
                _kind = _COMPARED[list_key][col]
                values = [{"normalized": _norm_cell(_kind, c["value"]),
                           "display": _shown_cell(_kind, c["value"]),
                           "sources": [_source(ref, c["value"]) for ref in c.get("documents") or []]}
                          for c in choices]
                said = "; ".join(
                    f"{', '.join(_doc_type_label(r.get('doc_type')) or str(r.get('filename')) for r in c.get('documents') or [])}: {_shown_cell(_kind, c['value'])}"
                    for c in choices)
                label = (f"{_schedule_label(list_key)} row {n + 1} ({row_label(list_key, row)}): "
                         f"{_column_label(list_key, col)}")
                confirmed = picked is not None and str(picked).strip() != ""
                out.append({
                    "fact_key": key, "label": label, "kind": "row", "row_level": True,
                    "list_key": list_key, "row_number": n + 1, "column": col,
                    "forms": list(_LIST_FORMS.get(list_key, [])),
                    "status": "confirmed" if confirmed else "conflict",
                    "conflict_reason": None if confirmed else f"Documents disagree ({said})",
                    "review_required": not confirmed,
                    "merged_value": str(_fv(row.get(col)) or "") or None,
                    "confirmed_value": str(picked) if confirmed else None,
                    "values": values,
                    "suggested_value": rv["kept"]["value"],
                    "suggested_normalized": values[0]["normalized"],
                    "confidence": "medium", "preselect": False,
                    "change": None, "conflict_scope": [], "confirmed_scopes": {},
                    "line_records": [], "narrative_note": None, "blocking_downgraded": False,
                    "linked_fields": [],
                })
    return out


def add_row_fields(result: dict, merged: Optional[dict], confirmations: Optional[dict]) -> dict:
    """Append the row-level rows to an assessment result in place (the ONE call
    site in `underwriting_consistency.assess_underwriting_consistency`)."""
    try:
        rows = row_fields(merged, confirmations)
        if not rows:
            return result
        result.setdefault("fields", []).extend(rows)
        open_rows = [r for r in rows if r["review_required"]]
        result["conflict_count"] = int(result.get("conflict_count") or 0) + len(open_rows)
        result["review_required"] = bool(result.get("review_required")) or bool(open_rows)
        result["assessed_keys"] = sorted(set(result.get("assessed_keys") or []) | {r["fact_key"] for r in rows})
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("row rivals: cards skipped (%s)", exc)
    return result


# ── A pick writes ONE cell of ONE row ────────────────────────────────────────
def _find_row(merged: dict, list_key: str, col: str, h: str) -> Optional[dict]:
    rows = _fv(merged.get(list_key))
    for row in rows if isinstance(rows, list) else []:
        rv = (row.get(RIVALS_KEY) or {}).get(col) if isinstance(row, dict) else None
        if isinstance(rv, dict) and _card_hash(list_key, col, rv) == h:
            return row
    return None


def validate_row_confirmation(key: str, value: Any, merged: Optional[dict] = None) -> str:
    """A pick's value, cleaned; raises ValueError(code) like the picker's own
    `validate_confirmation`."""
    parsed = parse_row_key(key)
    if parsed is None:
        raise ValueError("underwriting_unknown_field")
    raw = str(_fv(value) if value is not None else "").strip()
    if not raw:
        raise ValueError("underwriting_empty_value")
    try:
        from services.answer_semantics import is_placeholder_text
        placeholder = is_placeholder_text(raw)
    except Exception:                                          # noqa: BLE001
        placeholder = False
    if placeholder:                      # "N/A" / "TBD" / "unknown" is no value
        raise ValueError("underwriting_invalid_value")
    list_key, col, h = parsed
    if not _norm_cell(_COMPARED[list_key][col], raw):
        raise ValueError("underwriting_invalid_value")
    if merged is not None and _find_row(merged, list_key, col, h) is None:
        raise ValueError("underwriting_unknown_field")
    return raw


def apply_row_confirmations(merged: Dict[str, Any], confirmations: Optional[dict]) -> List[str]:
    """Write every row-level pick onto its row's cell (in place). Returns the
    keys applied. A pick whose row is gone (the documents changed) does nothing."""
    done: List[str] = []
    for key, raw in (confirmations or {}).items():
        parsed = parse_row_key(key)
        if parsed is None or raw is None:
            continue
        list_key, col, h = parsed
        row = _find_row(merged, list_key, col, h)
        val = str(_fv(raw) or "").strip()
        if row is None or not val:
            continue
        # Copy-on-write: the caller's facts (and their lists) are not touched.
        held = merged.get(list_key)
        rows = list(_fv(held))
        i = next(n for n, r in enumerate(rows) if r is row)
        rows[i] = dict(row, **{col: val})
        merged[list_key] = dict(held, value=rows) if isinstance(held, dict) and "value" in held else rows
        done.append(key)
    return done


# ── A part above its whole (item 8, Michelle, 29 Oct 2026) ───────────────────
def location_revenue_over_total(facts: Optional[dict]) -> Optional[Tuple[str, str, str]]:
    """(location label, its revenue, the business total) when ONE premises'
    stated revenue is more than the business's whole revenue - a part above its
    whole, which no correct pair of figures can be. Each premises once (the first
    building stating it). None when either figure is missing or nothing is above
    the total. Never raises."""
    try:
        from services.acord_intake.document_settle import _amount, _premises_key
        facts = facts or {}
        total = _amount(facts.get("total_revenue"))
        if not total:
            return None
        rows = _fv(facts.get("property_locations"))
        seen: set = set()
        worst = None
        for r in rows if isinstance(rows, list) else []:
            if not isinstance(r, dict):
                continue
            key = _premises_key(r) or f"row:{id(r)}"
            amt = _amount(r.get("annual_revenue"))
            if amt is None or key in seen:
                continue
            seen.add(key)
            if amt > total + 1 and (worst is None or amt > worst[1]):
                street = str(_fv(r.get("address_line1")) or str(_fv(r.get("address")) or "").split(",")[0]).strip()
                worst = (street or "a location", amt)
        if worst is None:
            return None
        return worst[0], f"${worst[1]:,.0f}", f"${total:,.0f}"
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("row rivals: location revenue check skipped (%s)", exc)
        return None
