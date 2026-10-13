"""policy_lines.py - the producer's own corrections to, and additions of, the
policies in a package ("Policies in this submission", 7 Oct 2026).

Brent (Choice Electric #9): "can we add a way to inline edit missing or
incorrect fields and/or add a missing policy line altogether?" The table lists
one row per LINE RECORD (`extraction_service._build_line_records`): line,
carrier, NAIC, policy number, term. Until now it was read-only, and the only
way to change a policy's identity was a Data Consistency card - which exists
only where two documents disagree.

THE STORE - one private fact, encrypted with the facts, carried through every
pipeline re-run (`carry_and_apply`, called by `_finalize_pipeline`):

    facts["_producer_policy_lines"] = {
        "v": 1,
        "edits": {<edit key>: {"fields": {fact: value or ""}, "anchor": {...},
                               "at": iso, "by": user}},
        "added": [{"id", "family", "layer", "line_printed", <fields>, "at", "by"}],
        "flags_set": {flag: the value it had before an added line set it},
    }

* An EDIT is keyed by the record's PRE-EDIT id - the id it has when built from
  the documents' rows and the Data Consistency confirmations. Two layers of the
  umbrella family ("umbrella#unnumbered" / "umbrella~excess#unnumbered") and two
  carriers on one line ("...@A" / "...@B") are two keys. The table hands each
  record's `edit_key` to the frontend; it is stable across edits because every
  document row carries the key of the record it belongs to (`_policy_key`).
* The `anchor` (line, layer, the document's carrier and number) re-finds the
  record when its id no longer matches (a document added or excluded). Nothing
  found: the edit is DORMANT - kept, not applied, and listed.
* A field set to "" is CLEARED. The carrier can never be cleared.
* A package scalar is never touched: a corrected auto policy number is the auto
  policy's, not the submission's (the client's SYS-06 rule).

THE ONE DOOR that applies the store is `apply_producer_policy_lines`. It runs
after the line-scoped Data Consistency confirmations, so a producer's statement
in this table outranks both the documents and an earlier card answer for the
same record, and a card's contract choice never sets a producer's row aside.
No store -> nothing runs, and every existing package is byte-identical.
"""
from __future__ import annotations

import copy
import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

STORE_KEY = "_producer_policy_lines"
# Markers on `coverage_lines` rows (private keys; every row reader ignores them).
ROW_ADDED = "_producer_added"         # a row the producer added: its line id
ROW_FIELDS = "_producer_fields"       # the facts the producer supplied on this row
ROW_KEY = "_policy_key"               # the record key a document row belongs to
ROW_DOC_VALUES = "_document_values"   # the document's own values an edit replaced

ADDED_PREFIX = "added:"
STORE_VERSION = 1

FIELDS: Tuple[str, ...] = ("carrier_name", "carrier_naic", "policy_number",
                           "effective_date", "expiration_date", "premium")
IDENTITY_FIELDS: Tuple[str, ...] = FIELDS[:-1]
# fact -> the `coverage_lines` column it lives in (extraction's RULE 16 names).
COLUMN: Dict[str, str] = {
    "carrier_name":    "carrier",
    "carrier_naic":    "naic",
    "policy_number":   "policy_number",
    "effective_date":  "effective_date",
    "expiration_date": "expiration_date",
    "premium":         "premium",
}
FIELD_LABELS: Dict[str, str] = {
    "carrier_name": "Carrier", "carrier_naic": "NAIC", "policy_number": "Policy number",
    "effective_date": "Effective date", "expiration_date": "Expiration date",
    "premium": "Premium",
    "limit_each_occurrence": "Each occurrence limit", "limit_aggregate": "Aggregate limit",
    "sir": "SIR",
}

# The limits of an umbrella-family policy the PRODUCER added (7 Oct 2026): its
# ACORD 131 copy prints nothing without them. ONLY on an added umbrella / excess
# line - a document's policy takes its limits from the documents and the Data
# Consistency picker. Kept under exactly these names on the producer's row and
# on its line record (LAYERS reads them for that layer's 131 view), and never
# under the generic `limit` column, so no umbrella-limit reader can mistake an
# excess layer's limit for the umbrella's (the C23 lesson). Values are canonical
# money text ("$5,000,000"); an SIR may be "$0".
UMBRELLA_LIMIT_FIELDS: Tuple[str, ...] = ("limit_each_occurrence", "limit_aggregate", "sir")
UMBRELLA_FAMILY = "umbrella"

# The lines a producer may add: (key, family, layer, label, the name the row
# prints). Every name canonicalises to its family (`lob_canon.canon_line`) and
# the excess one reads as the excess LAYER of the umbrella family
# (`lob_canon.umbrella_layer`) - pinned by test.
LINE_OPTIONS: Tuple[Tuple[str, str, Optional[str], str, str], ...] = (
    ("general_liab",       "general_liab",       None,       "General Liability",            "Commercial General Liability"),
    ("auto",               "auto",               None,       "Commercial Auto",              "Business Auto"),
    ("umbrella",           "umbrella",           "umbrella", "Umbrella",                     "Commercial Umbrella"),
    ("excess",             "umbrella",           "excess",   "Excess Liability",             "Excess Liability"),
    ("workers_comp",       "workers_comp",       None,       "Workers Compensation",         "Workers Compensation"),
    ("property",           "property",           None,       "Commercial Property",          "Commercial Property"),
    ("inland_marine",      "inland_marine",      None,       "Inland Marine",                "Commercial Inland Marine"),
    ("crime",              "crime",              None,       "Crime",                        "Crime"),
    ("cyber",              "cyber",              None,       "Cyber",                        "Cyber and Privacy"),
    ("professional",       "professional",       None,       "Professional Liability",       "Professional Liability"),
    ("epli",               "epli",               None,       "Employment Practices Liability", "Employment Practices Liability"),
    ("pollution",          "pollution",          None,       "Pollution Liability",          "Pollution Liability"),
    ("directors_officers", "directors_officers", None,       "Directors and Officers",       "Directors and Officers Liability"),
    ("employee_benefits",  "employee_benefits",  None,       "Employee Benefits Liability",  "Employee Benefits Liability"),
    ("liquor",             "liquor",             None,       "Liquor Liability",             "Liquor Liability"),
)
_OPTION_BY_KEY = {o[0]: o for o in LINE_OPTIONS}

# The coverage flag the form recommender reads for a family (an added line of
# that family is positive evidence the line is carried). Families with no
# flag (EPLI, cyber has one, D&O ...) have no ACORD section form of ours.
FAMILY_FLAGS: Dict[str, str] = {
    "general_liab":  "has_general_liability",
    "auto":          "has_auto_coverage",
    "umbrella":      "has_umbrella",
    "workers_comp":  "has_workers_comp",
    "property":      "has_property_coverage",
    "inland_marine": "has_inland_marine",
    "crime":         "has_crime",
    "cyber":         "has_cyber",
}

# The SECTION forms that describe a family's own policy - what a post-
# generation add-form offer may name for an added line. A form keeps its
# instances ("ACORD_131__excess"). Pinned against `pdf_service.
# _SECTION_FORM_LINE_PHRASES` by test so the two can never drift.
SECTION_FORMS: Dict[str, Tuple[str, ...]] = {
    "general_liab": ("ACORD_126",),
    "auto":         ("ACORD_127", "ACORD_137_CA", "ACORD_137_CO"),
    "umbrella":     ("ACORD_131",),
    "workers_comp": ("ACORD_130",),
    "property":     ("ACORD_140",),
    "crime":        ("ACORD_141",),
}

_MAX_TEXT = 160
_MAX_ADDED = 40


class PolicyLineError(ValueError):
    """A refused change: {field: message} for the row the producer is typing
    in, plus an optional general message."""

    def __init__(self, errors: Optional[Dict[str, str]] = None, message: str = ""):
        self.errors = dict(errors or {})
        self.message = message or (next(iter(self.errors.values())) if self.errors else
                                   "That change could not be saved.")
        super().__init__(self.message)


# ── Small readers ─────────────────────────────────────────────────────────────

def _fv(facts: Any, key: str):
    try:
        from services.extraction_service import _fv as _efv
        return _efv(facts or {}, key)
    except Exception:                                         # noqa: BLE001
        v = (facts or {}).get(key) if isinstance(facts, dict) else None
        return v.get("value") if isinstance(v, dict) and "value" in v else v


def _clean_text(value: Any) -> str:
    s = re.sub(r"[\x00-\x1f\x7f]", " ", str(value if value is not None else ""))
    return re.sub(r"\s+", " ", s).strip()


def _us_date(value: Any) -> str:
    """A date as MM/DD/YYYY when it reads as one, else the text as stored."""
    s = _clean_text(value)
    if not s:
        return ""
    try:
        from services.normalization import normalize_date
        iso = normalize_date(s)
    except Exception:                                         # noqa: BLE001
        iso = None
    if iso and re.match(r"^\d{4}-\d{2}-\d{2}$", iso):
        return f"{iso[5:7]}/{iso[8:10]}/{iso[0:4]}"
    return s


def _money_display(value: Any) -> str:
    """"$29,278" for 29278.0, "29,278.00" or "$29,278"; text that is not one
    amount is returned as written."""
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        text = f"{float(value):.2f}"
    else:
        text = _clean_text(value)
    try:
        from services.display_canonicalizer import canonicalize_currency
        return canonicalize_currency(text) or text
    except Exception:                                         # noqa: BLE001
        return text


def _same_company(a: Any, b: Any) -> bool:
    """Two carrier printings name one company - the comparison door (D3)."""
    if not _clean_text(a) or not _clean_text(b):
        return False
    try:
        from services.fact_comparison import values_agree
        return bool(values_agree("carrier_name", a, b))
    except Exception:                                         # noqa: BLE001
        return _clean_text(a).lower() == _clean_text(b).lower()


def _same_contract(a: Any, b: Any) -> bool:
    if not _clean_text(a) or not _clean_text(b):
        return False
    try:
        from services.fact_comparison import same_policy_contract
        return bool(same_policy_contract(a, b))
    except Exception:                                         # noqa: BLE001
        k = lambda v: re.sub(r"[^A-Za-z0-9]", "", str(v or "")).upper()  # noqa: E731
        return k(a) == k(b)


def _confirmed_list(row: dict) -> set:
    held = row.get("_confirmed")
    return set(held) if isinstance(held, (list, tuple, set)) else set()


def line_option(key: Any) -> Optional[Tuple[str, str, Optional[str], str, str]]:
    return _OPTION_BY_KEY.get(str(key or "").strip())


def line_options() -> List[dict]:
    """The lines a producer may add, for the "+ Add a policy" select."""
    return [{"key": k, "label": label} for k, _f, _l, label, _p in LINE_OPTIONS]


# ── The store ─────────────────────────────────────────────────────────────────

def empty_store() -> dict:
    return {"v": STORE_VERSION, "edits": {}, "added": [], "flags_set": {}}


def read_store(facts: Any) -> dict:
    """A clean COPY of the stored producer policy lines; malformed parts are
    dropped (never raises)."""
    out = empty_store()
    held = (facts or {}).get(STORE_KEY) if isinstance(facts, dict) else None
    if not isinstance(held, dict):
        return out
    edits = held.get("edits")
    if isinstance(edits, dict):
        for key, e in edits.items():
            if not isinstance(key, str) or not key.strip() or not isinstance(e, dict):
                continue
            fields = e.get("fields")
            if not isinstance(fields, dict):
                continue
            clean = {f: ("" if fields.get(f) is None else str(fields.get(f)))
                     for f in FIELDS if f in fields}
            if not clean:
                continue
            out["edits"][key] = {
                "fields": clean,
                "anchor": dict(e.get("anchor") or {}) if isinstance(e.get("anchor"), dict) else {},
                "at": str(e.get("at") or ""),
                "by": str(e.get("by") or ""),
            }
    added = held.get("added")
    if isinstance(added, list):
        seen = set()
        for a in added:
            if not isinstance(a, dict):
                continue
            aid = str(a.get("id") or "").strip()
            opt = line_option(a.get("line_key"))
            if not aid or aid in seen or not opt or not _clean_text(a.get("carrier_name")):
                continue
            seen.add(aid)
            entry = {"id": aid, "line_key": opt[0], "family": opt[1], "layer": opt[2],
                     "line_printed": opt[4],
                     "at": str(a.get("at") or ""), "by": str(a.get("by") or "")}
            for f in _entry_fields(opt[1]):
                entry[f] = _clean_text(a.get(f))
            out["added"].append(entry)
    flags_set = held.get("flags_set")
    if isinstance(flags_set, dict):
        out["flags_set"] = {str(k): v for k, v in flags_set.items()
                            if isinstance(k, str) and k.startswith("has_")}
    return out


def store_has_content(store: Any) -> bool:
    return isinstance(store, dict) and bool(store.get("edits") or store.get("added"))


def _entry_fields(family: Any) -> Tuple[str, ...]:
    """The facts an ADDED line of ``family`` holds: the six policy facts, plus
    the umbrella family's limits and SIR."""
    return FIELDS + (UMBRELLA_LIMIT_FIELDS if family == UMBRELLA_FAMILY else ())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def store_with_edit(store: dict, edit_key: str, fields: Dict[str, str],
                    anchor: Optional[dict] = None, user: Any = None) -> dict:
    """The store with ``fields`` merged into the edit of ``edit_key``. The
    anchor of the FIRST edit of a record is kept: it describes the record as
    the documents print it, which is what can re-find it later."""
    out = copy.deepcopy(store)
    cur = out["edits"].get(edit_key) or {"fields": {}, "anchor": dict(anchor or {})}
    cur["fields"] = {**(cur.get("fields") or {}), **{f: ("" if v is None else str(v))
                                                    for f, v in fields.items() if f in FIELDS}}
    if not cur.get("anchor"):
        cur["anchor"] = dict(anchor or {})
    cur["at"] = _now()
    cur["by"] = str(user or "")
    out["edits"][edit_key] = cur
    return out


def store_with_added(store: dict, line_key: str, fields: Dict[str, str],
                     user: Any = None) -> Tuple[dict, str]:
    opt = line_option(line_key)
    if not opt:
        raise PolicyLineError({"line": "Choose a line of business."})
    if len(store.get("added") or []) >= _MAX_ADDED:
        raise PolicyLineError(message="This package already holds the most policies "
                                      "that can be added by hand.")
    out = copy.deepcopy(store)
    existing = {a.get("id") for a in out.get("added") or []}
    new_id = secrets.token_hex(4)
    while new_id in existing:
        new_id = secrets.token_hex(4)
    entry = {"id": new_id, "line_key": opt[0], "family": opt[1], "layer": opt[2],
             "line_printed": opt[4], "at": _now(), "by": str(user or "")}
    for f in _entry_fields(opt[1]):
        entry[f] = _clean_text(fields.get(f))
    out["added"].append(entry)
    return out, new_id


def store_with_added_update(store: dict, line_id: str, fields: Dict[str, str],
                            user: Any = None) -> dict:
    out = copy.deepcopy(store)
    for a in out.get("added") or []:
        if a.get("id") == line_id:
            allowed = _entry_fields(a.get("family"))
            for f, v in fields.items():
                if f in allowed:
                    a[f] = _clean_text(v)
            a["at"] = _now()
            a["by"] = str(user or "")
            return out
    raise KeyError(line_id)


def store_without_added(store: dict, line_id: str) -> dict:
    out = copy.deepcopy(store)
    kept = [a for a in out.get("added") or [] if a.get("id") != line_id]
    if len(kept) == len(out.get("added") or []):
        raise KeyError(line_id)
    out["added"] = kept
    return out


def added_entry(store: dict, line_id: str) -> Optional[dict]:
    return next((a for a in (store or {}).get("added") or [] if a.get("id") == line_id), None)


# ── Validation ────────────────────────────────────────────────────────────────

_SEMANTIC_KEY = {"premium": "total_policy_premium", "limit_each_occurrence": "umbrella_limit",
                 "limit_aggregate": "umbrella_limit", "sir": "umbrella_sir"}
_TYPED_FIELDS = frozenset({"carrier_naic", "effective_date", "expiration_date", "premium",
                           *UMBRELLA_LIMIT_FIELDS})
_LIMITS_NOT_HERE_MSG = "Limits can be entered here only for an umbrella or excess policy."
_LIMITS_FROM_DOCUMENTS_MSG = ("The limits of a policy from your documents come from the documents "
                              "- confirm a different value in Data Consistency.")
_NON_ANSWER_MSG = "Type the value, or leave the box empty to clear it (not N/A, TBD or unknown)."
_MONEY_FILLER_RE = re.compile(r"(?i)\b(?:usd|us)\b|[$\s,]")


def _is_a_value(fact: str, text: str) -> bool:
    try:
        from services.answer_semantics import VALUE, interpret_answer
        return interpret_answer(_SEMANTIC_KEY.get(fact, fact), text).intent == VALUE
    except Exception:                                         # noqa: BLE001
        return True


def parse_money(text: Any) -> Optional[Tuple[float, str]]:
    """(amount, "$12,500") when ``text`` is ONE money amount and nothing else
    (a "$", "USD" or a scale word may surround it); None otherwise."""
    s = _clean_text(text)
    if not s:
        return None
    try:
        from services.display_canonicalizer import _CURRENCY_TOKEN_RE, canonicalize_currency
    except Exception:                                         # noqa: BLE001
        return None
    tokens = list(_CURRENCY_TOKEN_RE.finditer(s))
    if len(tokens) != 1:
        return None
    rest = (s[:tokens[0].start()] + " " + s[tokens[0].end():])
    if _MONEY_FILLER_RE.sub("", rest).strip("-+. ") or "-" in s[:tokens[0].start()]:
        return None
    canon = canonicalize_currency(s)
    if not canon.startswith("$"):
        return None
    try:
        amount = float(re.sub(r"[^\d.]", "", canon))
    except ValueError:
        return None
    return amount, canon


def _date_iso(text: str) -> Optional[str]:
    try:
        from services.normalization import normalize_date
        iso = normalize_date(text)
    except Exception:                                         # noqa: BLE001
        return None
    if not iso or not re.match(r"^\d{4}-\d{2}-\d{2}$", iso):
        return None
    if not (1950 <= int(iso[:4]) <= 2150):
        return None
    return iso


def validate_fields(raw: Any, *, adding: bool = False, current: Optional[dict] = None,
                    entries: Any = None, text: Any = None,
                    umbrella_family: bool = False,
                    document_record: bool = False) -> Dict[str, str]:
    """The producer's typed fields, clean, or PolicyLineError({field: message}).

    ``current`` - the record as the table shows it (its other date decides the
    order check). ``entries`` / ``text`` - the package's verified declarations
    entries and its documents' text, for the policy-number door (a number the
    documents print as a FORM or ACCOUNT number is refused).
    ``umbrella_family`` - the line is an umbrella / excess policy the producer
    ADDED, the only kind that takes `UMBRELLA_LIMIT_FIELDS`; anywhere else
    they are refused.
    Only the six policy facts (and those three) are read; anything else in
    ``raw`` is ignored. A key present with an empty value means "clear it"
    (never the carrier)."""
    if not isinstance(raw, dict):
        raise PolicyLineError(message="Nothing to save.")
    errors: Dict[str, str] = {}
    out: Dict[str, str] = {}
    for f in FIELDS + UMBRELLA_LIMIT_FIELDS:
        if f not in raw:
            continue
        val = _clean_text(raw.get(f))
        if f in UMBRELLA_LIMIT_FIELDS and (document_record or not umbrella_family):
            if val:
                errors[f] = _LIMITS_FROM_DOCUMENTS_MSG if document_record else _LIMITS_NOT_HERE_MSG
            continue
        if len(val) > _MAX_TEXT:
            errors[f] = "That is too long for this box."
            continue
        if not val:
            if f == "carrier_name":
                errors[f] = "Enter the insurance company's name."
            else:
                out[f] = ""                                   # cleared
            continue
        if not _is_a_value(f, val) and not (f in _TYPED_FIELDS and re.search(r"\d", val)):
            # "N/A", "TBD", "unknown", "None": a non-answer is never stored. A
            # typed box holding digits goes on to its own parser, whose message
            # says what shape it wants ("USD 2,400" is money; "13/45" is not a date).
            errors[f] = _NON_ANSWER_MSG
            continue
        if f == "carrier_name":
            try:
                from services.normalization import is_insurance_bureau, is_party_role_label
                bad = is_insurance_bureau(val) or is_party_role_label(val)
            except Exception:                                 # noqa: BLE001
                bad = False
            if bad or len(re.findall(r"[A-Za-z]", val)) < 2:
                errors[f] = "Enter the insurance company's name (not a rating bureau or a role)."
                continue
            out[f] = val
        elif f == "carrier_naic":
            digits = re.sub(r"\s", "", val)
            if not re.fullmatch(r"\d{5}", digits):
                errors[f] = "A NAIC code is 5 digits."
                continue
            out[f] = digits
        elif f == "policy_number":
            try:
                from services.normalization import is_not_a_policy_number, strip_leading_label
                val = _clean_text(strip_leading_label(val))
                refused = is_not_a_policy_number(
                    val, entries if isinstance(entries, list) else None, text or None)
            except Exception:                                 # noqa: BLE001
                refused = not re.search(r"\d", val)
            if refused or len(re.sub(r"[^A-Za-z0-9]", "", val)) < 3 or len(val) > 40:
                errors[f] = ("A policy number has at least one digit and is not a form "
                             "or account number.")
                continue
            out[f] = val
        elif f in ("effective_date", "expiration_date"):
            iso = _date_iso(val)
            if not iso:
                errors[f] = "Enter a real date (MM/DD/YYYY)."
                continue
            out[f] = f"{iso[5:7]}/{iso[8:10]}/{iso[0:4]}"
        elif f == "premium":
            parsed = parse_money(val)
            if parsed is None:
                errors[f] = "Enter one dollar amount (for example $12,500)."
                continue
            if parsed[0] <= 0:
                errors[f] = "A premium must be more than $0 - leave the box empty if there is none."
                continue
            out[f] = parsed[1]
        elif f in UMBRELLA_LIMIT_FIELDS:
            parsed = parse_money(val)
            if parsed is None:
                errors[f] = "Enter one dollar amount (for example $5,000,000)."
                continue
            # A self-insured retention of $0 is the ordinary umbrella (no SIR);
            # a limit of $0 is no limit at all.
            if parsed[0] < 0 or (parsed[0] == 0 and f != "sir"):
                errors[f] = ("A limit must be more than $0 - leave the box empty if it is "
                             "not known.")
                continue
            out[f] = parsed[1]
    if adding and "carrier_name" not in out and "carrier_name" not in errors:
        errors["carrier_name"] = "Enter the insurance company's name."
    # An aggregate is never smaller than the each-occurrence limit it caps (the
    # line's other limit counts when only one is typed).
    if umbrella_family and ("limit_each_occurrence" in out or "limit_aggregate" in out) \
            and "limit_each_occurrence" not in errors and "limit_aggregate" not in errors:
        cur_ = current or {}
        occ = parse_money(out["limit_each_occurrence"] if "limit_each_occurrence" in out
                          else cur_.get("limit_each_occurrence"))
        agg = parse_money(out["limit_aggregate"] if "limit_aggregate" in out
                          else cur_.get("limit_aggregate"))
        if occ and agg and agg[0] < occ[0]:
            errors["limit_aggregate"] = ("The aggregate limit cannot be less than the each "
                                         "occurrence limit.")
    # The term, with the record's other date when only one is typed.
    cur = current or {}
    eff = out.get("effective_date") if "effective_date" in out else _us_date(cur.get("effective_date"))
    exp = out.get("expiration_date") if "expiration_date" in out else _us_date(cur.get("expiration_date"))
    if ("effective_date" in out or "expiration_date" in out) and eff and exp \
            and "effective_date" not in errors and "expiration_date" not in errors:
        e_iso, x_iso = _date_iso(eff), _date_iso(exp)
        if e_iso and x_iso and x_iso <= e_iso:
            errors["expiration_date"] = "The expiration date must be after the effective date."
    if errors:
        raise PolicyLineError(errors)
    return out


# ── Applying the store ────────────────────────────────────────────────────────

def _row_premium(value: Any) -> Optional[float]:
    text = re.sub(r"[^\d.]", "", str(value or ""))
    if not text or text.count(".") > 1:
        return None
    try:
        amount = float(text)
    except ValueError:
        return None
    return amount if amount > 0 else None


def _premium_rows(rows: List[dict]) -> List[dict]:
    """The row(s) printing the POLICY's own premium in a record's bucket: the
    rows that name an ACORD line (not a coverage part), the priced ones among
    them with the largest premium; else the first such row."""
    try:
        from services.pdf_service import _names_a_standard_line
    except Exception:                                         # noqa: BLE001
        _names_a_standard_line = lambda _n: False             # noqa: E731
    named = [r for r in rows if _names_a_standard_line(str(r.get("line") or ""))] or list(rows)
    priced = [(p, r) for r in named for p in [_row_premium(r.get("premium"))] if p is not None]
    if priced:
        top = max(p for p, _r in priced)
        return [r for p, r in priced if p == top]
    return named[:1]


def _documents_naic(company: str, rows: Iterable[dict]) -> str:
    """The ONE NAIC the documents print for ``company``, or "" (matched pair)."""
    found = set()
    for r in rows or []:
        if not isinstance(r, dict) or r.get(ROW_ADDED):
            continue
        if _same_company(r.get("carrier"), company):
            n = re.sub(r"\D", "", str(r.get("naic") or ""))
            if len(n) == 5:
                found.add(n)
    return next(iter(found)) if len(found) == 1 else ""


def _record_layer(rec: dict) -> Optional[str]:
    if rec.get("line") != "umbrella":
        return None
    return rec.get("layer") or "umbrella"


def _anchor_of(rec: dict) -> dict:
    """What re-finds a record later: its line and layer and the DOCUMENT's own
    carrier and number (a record already edited keeps its document values in
    `document_printings`)."""
    doc = rec.get("document_printings") or {}
    carrier = (doc.get("carrier_name") or [None])[0] or rec.get("carrier_name")
    number = (doc.get("policy_number") or [None])[0] or rec.get("policy_number")
    return {"line": rec.get("line"), "layer": _record_layer(rec),
            "carrier": carrier or "", "policy_number": number or "",
            "line_printed": rec.get("line_printed") or ""}


def _find_by_anchor(anchor: dict, records: List[dict]) -> Optional[dict]:
    if not isinstance(anchor, dict) or not anchor.get("line"):
        return None
    pool = [r for r in records if r.get("line") == anchor.get("line")
            and _record_layer(r) == anchor.get("layer") and not r.get("producer_added")]
    if not pool:
        return None
    number = _clean_text(anchor.get("policy_number"))
    if number:
        hits = [r for r in pool if any(_same_contract(number, p) for p in
                                       ((r.get("printings") or {}).get("policy_number") or []))]
        if len(hits) == 1:
            return hits[0]
        if hits:
            pool = hits
    carrier = _clean_text(anchor.get("carrier"))
    if carrier:
        hits = [r for r in pool if any(_same_company(carrier, c) for c in
                                       ((r.get("printings") or {}).get("carrier_name") or []))]
        if len(hits) == 1:
            return hits[0]
        if hits:
            pool = hits
    return pool[0] if len(pool) == 1 else None


def _added_row(entry: dict) -> dict:
    row = {"line": entry.get("line_printed")}
    supplied = []
    for f in FIELDS:
        v = _clean_text(entry.get(f))
        row[COLUMN[f]] = v or None
        if v:
            supplied.append(f)
    if entry.get("family") == UMBRELLA_FAMILY:
        # Its own keys, never the generic `limit` column (see UMBRELLA_LIMIT_FIELDS).
        for f in UMBRELLA_LIMIT_FIELDS:
            v = _clean_text(entry.get(f))
            if v:
                row[f] = v
                supplied.append(f)
    row[ROW_ADDED] = entry.get("id")
    row[ROW_FIELDS] = sorted(supplied)
    row["_confirmed"] = sorted(f for f in supplied if f in IDENTITY_FIELDS)
    return row


def apply_producer_policy_lines(facts: Any, flags: Optional[dict] = None,
                                docs: Any = None, *, restore_flags: bool = False,
                                force: bool = False) -> dict:
    """Apply the stored producer policy lines to ``facts`` IN PLACE (and the
    coverage flags of added lines to ``flags`` when given). Returns a report:
    {"applied": [edit keys], "unmatched": [edit keys], "added": [line ids],
     "flags_on": [flags turned on], "changed": bool}. Never raises.

    The rows the edits rewrite are the rows of each record as built from the
    documents' rows (plus the confirmations already applied), so the caller
    passes facts whose `coverage_lines` are the documents' own; an earlier
    application's added rows are stripped first (idempotent).

    ``restore_flags`` - the flags are the session's STORED ones (after forms):
    a family whose last added line is gone gets back the value it had before.
    A pipeline re-run passes False: its flags are fresh from the documents.
    ``force`` - rebuild the records even with nothing to apply (the caller
    reset the rows, e.g. after the last added line was removed)."""
    report = {"applied": [], "unmatched": [], "added": [], "flags_on": [], "changed": False}
    if not isinstance(facts, dict):
        return report
    store = read_store(facts)
    held = facts.get("coverage_lines")
    rows_in = held.get("value") if isinstance(held, dict) and "value" in held else held
    rows_in = rows_in if isinstance(rows_in, list) else []
    had_markers = any(isinstance(r, dict) and (r.get(ROW_ADDED) or r.get(ROW_KEY))
                      for r in rows_in)
    if not store_has_content(store) and not had_markers and not force \
            and not (restore_flags and store.get("flags_set")):
        return report                                     # nothing of ours: byte-identical
    try:
        from services.extraction_service import _build_line_records, _build_scoped_fact_store
    except Exception as exc:                              # noqa: BLE001
        logger.warning("policy_lines: extraction door unavailable - %s", exc)
        return report
    try:
        old_key_rows: Dict[str, List[int]] = {}
        rows: List[Any] = []
        for r in rows_in:
            if isinstance(r, dict):
                if r.get(ROW_ADDED):
                    continue                              # re-added below
                r = dict(r)
                k = r.pop(ROW_KEY, None)
                if k:
                    old_key_rows.setdefault(str(k), []).append(len(rows))
            rows.append(r)
        doc_list = docs if isinstance(docs, list) else None
        members: Dict[str, List[dict]] = {}
        view = dict(facts)
        view["coverage_lines"] = rows
        records = _build_line_records(view, doc_list, members=members)
        index_of = {id(r): i for i, r in enumerate(rows) if isinstance(r, dict)}
        for rid, entries in members.items():
            for e in entries:
                i = index_of.get(id(e))
                if i is not None:
                    rows[i][ROW_KEY] = rid
        by_id = {r.get("id"): r for r in records if isinstance(r, dict)}
        pristine_rows = [r for r in rows if isinstance(r, dict)]

        for key, edit in sorted(store["edits"].items(), key=lambda kv: (kv[1].get("at") or "", kv[0])):
            rec = by_id.get(key)
            idxs: List[int] = []
            if rec is not None:
                idxs = [index_of[id(e)] for e in members.get(key) or [] if id(e) in index_of]
            if not idxs and key in old_key_rows:
                idxs = list(old_key_rows[key])
                rec = rec or next((by_id.get(rows[i].get(ROW_KEY)) for i in idxs
                                   if isinstance(rows[i], dict)), None)
            if not idxs:
                rec = _find_by_anchor(edit.get("anchor") or {}, list(by_id.values()))
                if rec is not None:
                    idxs = [index_of[id(e)] for e in members.get(rec.get("id")) or []
                            if id(e) in index_of]
            if not idxs:
                report["unmatched"].append(key)
                continue
            _apply_edit(rows, idxs, key, edit.get("fields") or {}, rec or {}, pristine_rows)
            report["applied"].append(key)

        for entry in store["added"]:
            rows.append(_added_row(entry))
            report["added"].append(entry["id"])

        if isinstance(held, dict) and "value" in held:
            facts["coverage_lines"] = dict(held, value=rows)
        else:
            facts["coverage_lines"] = rows
        _build_scoped_fact_store(facts, doc_list)
        report["changed"] = True

        if isinstance(flags, dict):
            report["flags_on"] = _set_line_flags(store, flags, restore=restore_flags)
            if STORE_KEY in facts:
                facts[STORE_KEY] = _store_for_facts(facts.get(STORE_KEY), store)
        if doc_list is not None and (store_has_content(store) or had_markers or force):
            # Page one names the companies writing the programme; a producer's
            # line is one of them (`_current_policy_writers`), and removing it
            # takes its company off again.
            try:
                from services.extraction_service import _mark_page_one_current_policy
                _mark_page_one_current_policy(facts, doc_list)
            except Exception as exc:                      # noqa: BLE001
                logger.warning("policy_lines: page-one re-check skipped - %s", exc)
        if report["applied"] or report["added"] or report["unmatched"]:
            logger.info("policy_lines: producer policy lines applied - edits %s, added %s, "
                        "dormant %s", report["applied"][:6], report["added"][:6],
                        report["unmatched"][:6])
    except Exception as exc:                              # noqa: BLE001
        logger.warning("policy_lines: application failed - %s", exc, exc_info=True)
    return report


def _store_for_facts(held: Any, store: dict) -> dict:
    """The stored dict with the (possibly updated) `flags_set` bookkeeping."""
    base = held if isinstance(held, dict) else {}
    out = dict(base) if base else {"v": STORE_VERSION, "edits": {}, "added": []}
    out["flags_set"] = dict(store.get("flags_set") or {})
    return out


def _apply_edit(rows: List[Any], idxs: List[int], key: str, fields: Dict[str, str],
                rec: dict, pristine_rows: List[dict]) -> None:
    """Write one record's edit onto its rows: identity on every row (one policy,
    one printing), the premium on the policy's own row."""
    ident = {f: v for f, v in fields.items() if f in IDENTITY_FIELDS}
    supplied = {f for f in fields if f in FIELDS}
    # THE MATCHED PAIR (the client's rule): a carrier changed to ANOTHER company
    # takes the NAIC the documents print for that company, or none - never the
    # old company's. A respelling of the same company keeps its NAIC; a NAIC the
    # producer typed in the same save is theirs.
    if "carrier_name" in ident and "carrier_naic" not in fields:
        old = rec.get("carrier_name") or next(
            (rows[i].get("carrier") for i in idxs if isinstance(rows[i], dict)
             and rows[i].get("carrier")), "")
        if ident["carrier_name"] and old and not _same_company(old, ident["carrier_name"]):
            ident["carrier_naic"] = _documents_naic(ident["carrier_name"], pristine_rows)
    targets = [rows[i] for i in idxs if isinstance(rows[i], dict)]
    for r in targets:
        _write(r, ident, supplied & set(IDENTITY_FIELDS))
        r[ROW_KEY] = key
    if "premium" in fields:
        for r in _premium_rows(targets):
            _write(r, {"premium": fields["premium"]}, {"premium"})


def _write(row: dict, values: Dict[str, str], supplied: set) -> None:
    doc_vals = dict(row.get(ROW_DOC_VALUES) or {})
    for f, v in values.items():
        col = COLUMN[f]
        old = row.get(col)
        if col not in doc_vals and old not in (None, "") and not row.get(ROW_ADDED):
            doc_vals[col] = old
        row[col] = (v or None)
    if doc_vals:
        row[ROW_DOC_VALUES] = doc_vals
    mine = set(row.get(ROW_FIELDS) or []) | set(supplied)
    if mine:
        row[ROW_FIELDS] = sorted(mine)
    confirmed = _confirmed_list(row) | {f for f, v in values.items()
                                        if v and f in IDENTITY_FIELDS and f in supplied}
    confirmed -= {f for f, v in values.items() if not v}
    if confirmed:
        row["_confirmed"] = sorted(confirmed)
    elif isinstance(row.get("_confirmed"), list):
        row.pop("_confirmed", None)


def _set_line_flags(store: dict, flags: dict, restore: bool = False) -> List[str]:
    """Coverage flags follow the added lines: an added line turns its family's
    flag on (recording what it was), and - on STORED flags (``restore``) -
    removing the family's last added line gives the flag back its old value.
    Fresh document flags (a re-run) are never touched for a family with no
    added line. Returns the flags turned on now."""
    turned: List[str] = []
    bookkeeping = dict(store.get("flags_set") or {})
    families = {a.get("family") for a in store.get("added") or []}
    for fam, flag in FAMILY_FLAGS.items():
        if fam in families:
            if flags.get(flag) is not True:
                if flag not in bookkeeping:
                    bookkeeping[flag] = flags.get(flag)
                flags[flag] = True
                turned.append(flag)
        elif flag in bookkeeping:
            prior = bookkeeping.pop(flag)
            if restore:
                if prior is None:
                    flags.pop(flag, None)
                else:
                    flags[flag] = prior
    store["flags_set"] = bookkeeping
    return turned


def carry_and_apply(merged: Any, flags: Optional[dict], docs: Any,
                    prior_facts: Any) -> dict:
    """The pipeline re-run's half: carry the store from the session's previous
    facts (the documents never state it), then apply it. No store anywhere ->
    no-op."""
    if not isinstance(merged, dict):
        return {}
    if STORE_KEY not in merged and isinstance(prior_facts, dict) \
            and isinstance(prior_facts.get(STORE_KEY), dict):
        merged[STORE_KEY] = copy.deepcopy(prior_facts[STORE_KEY])
    if not store_has_content(read_store(merged)):
        return {}
    return apply_producer_policy_lines(merged, flags, docs, restore_flags=False)


# ── What the table shows ──────────────────────────────────────────────────────

# Words a line's own NAME uses: every family phrase the line canon knows, its
# generic GL words, and this table's own labels. Read once.
_LINE_NAME_WORDS: Optional[frozenset] = None
_LINE_NAME_FILLER = frozenset({"commercial", "business", "coverage", "coverages", "part",
                               "form", "policy", "insurance", "liability", "liab", "and",
                               "of", "the", "or", "following", "follow"})


def _line_name_words() -> frozenset:
    global _LINE_NAME_WORDS
    if _LINE_NAME_WORDS is None:
        words: set = set()
        try:
            from services import lob_canon as _lc
            for _fam, phrases in tuple(_lc._SPECIFIC) + tuple(_lc._SPECIALTY):
                for p in phrases:
                    words.update(re.sub(r"[^a-z ]", " ", p.lower()).split())
            for p in _lc._GL_PHRASES:
                words.update(re.sub(r"[^a-z ]", " ", p.lower()).split())
            words.update(_lc.GL_GENERIC_TOKENS)
        except Exception:                                     # noqa: BLE001
            pass
        for _k, _f, _layer, label, acord in LINE_OPTIONS:
            words.update(re.sub(r"[^a-z ]", " ", f"{label} {acord}".lower()).split())
        _LINE_NAME_WORDS = frozenset(words)
    return _LINE_NAME_WORDS


def _names_a_section(printed: str, family: str) -> bool:
    """A printed name that is one SECTION of the policy, not the policy's line:
    its own line's word first, then words no line name uses (12 Oct 2026, the
    owner's run `18ecbfa8`: Chubb's cyber policy was named after its first
    insuring agreement, "Cyber Incident Response Team"). Measured over the 65
    names in 1,137 stored packages: it is the only one. A name that starts any
    other way ("Covered Autos Liability", "Hired and Non-Owned Auto Liability")
    is left as printed."""
    core = [t for t in re.sub(r"[^a-z ]", " ", str(printed or "").lower()).split()
            if t not in _LINE_NAME_FILLER]
    if len(core) < 2:
        return False
    try:
        from services.lob_canon import canon_line
        if canon_line(core[0]) != family:
            return False
    except Exception:                                         # noqa: BLE001
        return False
    words = _line_name_words()
    return core[0] in words and any(t not in words for t in core[1:])


def _family_label(rec: dict) -> str:
    fam = str(rec.get("line") or "")
    for _k, f, layer, label, _p in LINE_OPTIONS:
        if f == fam and (layer is None or layer == _record_layer(rec)):
            return label
    return fam.replace("_", " ").title()


def _line_label(rec: dict) -> str:
    printed = _clean_text(rec.get("line_printed"))
    if printed and not _names_a_section(printed, str(rec.get("line") or "")):
        return printed
    return _family_label(rec)


# ── Each policy's OWN limit (Brent, Choice Electric #10, 7 Oct 2026) ─────────
# "Let's just hide/remove these two blocks [the "N policies, M values - not a
# conflict" rows] because they are redundant to the table above." The umbrella
# block was the only place the two umbrella-family layers' limits ($5,000,000
# umbrella, $4,000,000 excess) were visible side by side, so the table gained a
# Limit column. Each record's limit is read ONLY from facts of its own line
# family (`lob_canon.fact_line_family`, pinned by test) and, for the umbrella
# family, from that LAYER's own view (`umbrella_layers.layer_view` - what its
# ACORD 131 copy prints). A line-family fact belongs to a record only when the
# family has exactly ONE document policy; two policies on one line (or a line
# the producer added beside a document's) cannot say whose the fact is, so the
# cell is blank. A line the producer added carries only the limits they stated
# (umbrella / excess). Display only: nothing here writes a fact, and the value
# is whatever the merge settled - never patched here.
_LINE_LIMIT_PARTS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "general_liab": (("gl_each_occurrence", "each occurrence"), ("gl_aggregate", "aggregate")),
    "workers_comp": (("wc_el_each_accident", "EL each accident"),
                     ("wc_el_disease_each_employee", "EL disease each employee"),
                     ("wc_el_disease_policy_limit", "EL disease policy limit")),
    "cyber":        (("cyber_limit", "limit"),),
    "crime":        (("crime_limit", "limit"),),
}
_AUTO_CSL_FACT = "auto_liability_limit"
_AUTO_SPLIT_PARTS: Tuple[Tuple[str, str], ...] = (
    ("auto_bi_per_person", "BI each person"), ("auto_bi_per_accident", "BI each accident"),
    ("auto_pd_per_accident", "PD each accident"))
# The WC employers liability composite ("$1,000,000 Bodily Injury by Accident -
# each accident; ...") fills a part the three dedicated facts leave blank.
_WC_EL_COMPOSITE = "employers_liability_limits"
_WC_EL_WORDS: Tuple[Tuple[str, str], ...] = (("accident", "wc_el_each_accident"),
                                             ("employee", "wc_el_disease_each_employee"),
                                             ("policy", "wc_el_disease_policy_limit"))
_UMBRELLA_PARTS: Tuple[Tuple[str, str], ...] = (("umbrella_limit", "each occurrence"),
                                                ("umbrella_sir", "SIR"))
_ADDED_UMBRELLA_PARTS: Tuple[Tuple[str, str], ...] = (
    ("limit_each_occurrence", "each occurrence"), ("limit_aggregate", "aggregate"), ("sir", "SIR"))
_MONEY_IN_TEXT_RE = re.compile(r"\$?\s?\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\$\s?\d+(?:\.\d{2})?")


def limit_facts() -> Dict[str, Tuple[str, ...]]:
    """{line family: every fact the Limit column may read for it} - pinned by
    test against `lob_canon.fact_line_family` (no other line's fact)."""
    out = {fam: tuple(k for k, _l in parts) for fam, parts in _LINE_LIMIT_PARTS.items()}
    out["workers_comp"] = out["workers_comp"] + (_WC_EL_COMPOSITE,)
    out["auto"] = (_AUTO_CSL_FACT,) + tuple(k for k, _l in _AUTO_SPLIT_PARTS)
    out[UMBRELLA_FAMILY] = tuple(k for k, _l in _UMBRELLA_PARTS)
    return out


def _amount_text(value: Any, *, zero_ok: bool = False) -> str:
    """"$1,000,000" for a value that is ONE money amount, else "" (a limit of
    $0 is no limit; an SIR of $0 is a stated SIR)."""
    if isinstance(value, dict) and "value" in value:
        value = value.get("value")
    if value is None or isinstance(value, (bool, list, dict)):
        return ""
    parsed = parse_money(value)
    if not parsed or (parsed[0] <= 0 and not zero_ok):
        return ""
    return parsed[1]


def _parts_from(facts: Any, parts: Iterable[Tuple[str, str]]) -> List[dict]:
    out = []
    for key, label in parts:
        amount = _amount_text(_fv(facts, key), zero_ok=key in ("umbrella_sir", "sir"))
        if amount:
            out.append({"label": label, "amount": amount})
    return out


def _wc_parts(facts: Any) -> List[dict]:
    have = {k: _amount_text(_fv(facts, k)) for k, _l in _LINE_LIMIT_PARTS["workers_comp"]}
    if not all(have.values()):
        composite = _fv(facts, _WC_EL_COMPOSITE)
        if isinstance(composite, str):
            for seg in re.split(r"[;\n]", composite):
                low = seg.lower()
                fact = next((f for word, f in _WC_EL_WORDS if word in low), None)
                found = _MONEY_IN_TEXT_RE.findall(seg)
                if fact and not have.get(fact) and len(found) == 1:
                    have[fact] = _amount_text(found[0])
    return [{"label": label, "amount": have[k]}
            for k, label in _LINE_LIMIT_PARTS["workers_comp"] if have.get(k)]


def _auto_parts(facts: Any) -> List[dict]:
    try:
        from services.coverage_evidence import auto_csl_stated, auto_limits_are_split
        split = auto_limits_are_split(facts)
        csl = (not split) and auto_csl_stated(facts)
    except Exception:                                         # noqa: BLE001
        split, csl = False, False
    if split:
        return _parts_from(facts, _AUTO_SPLIT_PARTS)
    return _parts_from(facts, ((_AUTO_CSL_FACT, "CSL" if csl else "liability"),))


def _umbrella_layer_parts(facts: Any, recs: List[dict]) -> Dict[str, List[dict]]:
    """{record id: its layer's own limit and SIR} for the umbrella-family
    DOCUMENT records - read off the layer's ACORD 131 view. Two rival
    policies on one umbrella layer (the picker's question) get nothing."""
    out: Dict[str, List[dict]] = {}
    doc_recs = [r for r in recs if r.get("line") == UMBRELLA_FAMILY and not r.get("producer_added")]
    if not doc_recs:
        return out
    try:
        from services import umbrella_layers as ul
        slots, assign = ul._assign(facts)
        keys = ul._keys_by_index(assign)
    except Exception:                                         # noqa: BLE001
        slots, keys = [], {}
    if not slots:
        # Records built for display only (a session stored before `_line_records`):
        # the package's umbrella facts are the one document policy's, or nobody's.
        if len(doc_recs) == 1:
            out[str(doc_recs[0].get("id"))] = _parts_from(facts, _UMBRELLA_PARTS)
        return out
    for idx, slot in enumerate(slots):
        rec = slot.get("record")
        if not isinstance(rec, dict) or rec.get("producer_added") or idx not in keys:
            continue
        try:
            view = ul.layer_view(facts, keys[idx])
        except Exception:                                     # noqa: BLE001
            continue
        if isinstance(view, dict) and (view.get(ul.MARKER_KEY) or {}).get("missing"):
            continue
        out[str(rec.get("id"))] = _parts_from(view, _UMBRELLA_PARTS)
    return out


def record_limits(facts: Any, recs: List[dict]) -> Dict[str, List[dict]]:
    """{record id: [{"label", "amount"}]} - each policy's own limit, [] when
    unknown. See the block comment above. Never raises."""
    out: Dict[str, List[dict]] = {}
    try:
        recs = [r for r in recs if isinstance(r, dict)]
        by_family: Dict[str, List[dict]] = {}
        for r in recs:
            by_family.setdefault(str(r.get("line") or ""), []).append(r)
        for fam, members in by_family.items():
            if fam == UMBRELLA_FAMILY:
                continue
            if len(members) != 1 or members[0].get("producer_added"):
                continue                      # whose is the line's fact? nobody can say
            if fam == "auto":
                parts = _auto_parts(facts)
            elif fam == "workers_comp":
                parts = _wc_parts(facts)
            elif fam in _LINE_LIMIT_PARTS:
                parts = _parts_from(facts, _LINE_LIMIT_PARTS[fam])
            else:
                parts = []
            out[str(members[0].get("id"))] = parts
        out.update(_umbrella_layer_parts(facts, recs))
        for r in recs:
            if r.get("producer_added") and r.get("line") == UMBRELLA_FAMILY:
                out[str(r.get("id"))] = _parts_from(r, _ADDED_UMBRELLA_PARTS)
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("policy_lines: limit column skipped - %s", exc)
    return out


def _carrier_group_key(name: Any) -> str:
    """One group per company for "Group by carrier": the comparison door's
    spacing-proof key (a glued printing groups with the spaced one)."""
    text = _clean_text(name)
    if not text:
        return ""
    try:
        from services.normalization import entity_compact_key
        return entity_compact_key(text) or text.lower()
    except Exception:                                         # noqa: BLE001
        return re.sub(r"[^a-z0-9&]", "", text.lower())


def table_rows(facts: Any) -> List[dict]:
    """One row per policy for "Policies in this submission": the document
    records first (in record order), then the lines the producer added."""
    try:
        from services.extraction_service import _build_line_records, policy_line_records
    except Exception:                                         # noqa: BLE001
        return []
    held = (facts or {}).get("_line_records") if isinstance(facts, dict) else None
    if not isinstance(held, list) and isinstance(facts, dict) and facts.get("coverage_lines"):
        # A session stored before the records existed: build them from its rows.
        try:
            held = _build_line_records(facts)
        except Exception:                                     # noqa: BLE001
            held = []
    recs = policy_line_records(held if isinstance(held, list) else [])
    limits = record_limits(facts, recs)
    out: List[dict] = []
    for rec in recs:
        added = rec.get("producer_added")
        edit_key = (ADDED_PREFIX + str(added)) if added else (rec.get("edit_key") or rec.get("id"))
        row = {
            "id":              rec.get("id"),
            "edit_key":        edit_key,
            "line":            rec.get("line"),
            "layer":           _record_layer(rec),
            "line_label":      _line_label(rec),
            "carrier_name":    _clean_text(rec.get("carrier_name")),
            "carrier_naic":    _clean_text(rec.get("carrier_naic")),
            "policy_number":   _clean_text(rec.get("policy_number")),
            "effective_date":  _us_date(rec.get("effective_date")),
            "expiration_date": _us_date(rec.get("expiration_date")),
            "premium":         _money_display(rec.get("premium")),
            "sources":         [s for s in dict.fromkeys(rec.get("sources") or []) if s],
            "producer_added":  bool(added),
            "edited_fields":   sorted(f for f in (rec.get("producer_fields") or []) if f in FIELDS)
                               if not added else [],
            # Brent #10: the policy's OWN limit (display only - `record_limits`)
            # and the key "Group by carrier" groups the rows by.
            "limit_parts":     limits.get(str(rec.get("id")), []),
            "carrier_key":     _carrier_group_key(rec.get("carrier_name")),
        }
        row["limit"] = "; ".join(f"{p['amount']} {p['label']}" for p in row["limit_parts"])
        if added and rec.get("line") == UMBRELLA_FAMILY:
            # An added umbrella / excess layer carries its own limits and SIR.
            for f in UMBRELLA_LIMIT_FIELDS:
                row[f] = _money_display(rec.get(f))
        out.append(row)
    return out


def unmatched_edits(facts: Any) -> List[dict]:
    """Edits that match no policy the documents now show (dormant)."""
    store = read_store(facts)
    if not store["edits"]:
        return []
    # An applied edit leaves its key on the rows it rewrote (`_apply_edit`),
    # whether its record was found by id, by an earlier key or by its anchor.
    rows = _fv(facts, "coverage_lines")
    applied = {str(r.get(ROW_KEY)) for r in rows if isinstance(r, dict) and r.get(ROW_KEY)} \
        if isinstance(rows, list) else set()
    out = []
    for key, e in store["edits"].items():
        if key in applied:
            continue
        anchor = e.get("anchor") or {}
        out.append({"edit_key": key,
                    "line_label": _clean_text(anchor.get("line_printed"))
                    or str(anchor.get("line") or "").replace("_", " ").title(),
                    "fields": dict(e.get("fields") or {})})
    return out


def find_row(facts: Any, edit_key: str) -> Optional[dict]:
    return next((r for r in table_rows(facts) if r.get("edit_key") == edit_key), None)


def record_for_key(facts: Any, edit_key: str) -> Optional[dict]:
    """The line record a table row's edit key names."""
    try:
        from services.extraction_service import _build_line_records, policy_line_records
    except Exception:                                         # noqa: BLE001
        return None
    held = (facts or {}).get("_line_records") if isinstance(facts, dict) else None
    if not isinstance(held, list) and isinstance(facts, dict) and facts.get("coverage_lines"):
        try:
            held = _build_line_records(facts)
        except Exception:                                     # noqa: BLE001
            held = []
    for rec in policy_line_records(held if isinstance(held, list) else []):
        key = (ADDED_PREFIX + str(rec["producer_added"])) if rec.get("producer_added") \
            else (rec.get("edit_key") or rec.get("id"))
        if key == edit_key:
            return rec
    return None


def anchor_for(facts: Any, edit_key: str) -> dict:
    rec = record_for_key(facts, edit_key)
    return _anchor_of(rec) if rec else {}


def producer_premium_amounts(facts: Any) -> set:
    """Whole-dollar keys of every premium a PERSON stated on a coverage row -
    exempt from the documents' presence backstop (a typed premium is in no
    document)."""
    out = set()
    rows = _fv(facts, "coverage_lines")
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or "premium" not in (r.get(ROW_FIELDS) or []):
            continue
        amt = _row_premium(r.get("premium"))
        if amt is not None:
            out.add(str(int(round(amt))))
    return out


# ── Post-generation: which form an added line needs ───────────────────────────

def form_offers(session: Any, facts: Optional[dict] = None,
                flags: Optional[dict] = None) -> List[dict]:
    """Forms an ADDED line needs that the package does not hold: the section
    forms of its family (and their instances) the recommender recommends.
    Offered, never added. Server-derived on every call - the add-form route
    re-asks this before it adds anything."""
    session = session if isinstance(session, dict) else {}
    facts = facts if isinstance(facts, dict) else (session.get("facts") or {})
    flags = flags if isinstance(flags, dict) else (session.get("flags") or {})
    store = read_store(facts)
    families = {a.get("family") for a in store.get("added") or []}
    wanted = {f for fam in families for f in SECTION_FORMS.get(fam, ())}
    if not wanted:
        return []
    try:
        from services.form_service import match_forms, filter_available_forms, load_all_forms
        from services.form_instances import base_form_id, instance_label
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("policy_lines: recommender unavailable - %s", exc)
        return []
    try:
        docs = [d for d in (session.get("docs") or []) if isinstance(d, dict) and not d.get("excluded")] \
            or [d for d in (session.get("docs") or []) if isinstance(d, dict)]
        text = " ".join(str(d.get("text") or "") for d in docs)
        available = session.get("all_forms") or filter_available_forms(load_all_forms())
        recs = match_forms(facts, flags, available, text=text)
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("policy_lines: recommendation for the add-form offer failed - %s", exc)
        return []
    present = set(session.get("selected_form_ids") or []) | set((session.get("generated_forms") or {}).keys())
    known = {str(f.get("form_id")) for f in (session.get("all_forms") or []) if isinstance(f, dict)}
    out: List[dict] = []
    for r in recs or []:
        fid = str((r or {}).get("form_id") or "")
        if not fid or fid in present or base_form_id(fid) not in wanted:
            continue
        if known and base_form_id(fid) not in known:
            continue                                          # no template for this session
        if any(o["form_id"] == fid for o in out):
            continue
        out.append({"form_id": fid, "label": instance_label(fid)})
    return out


# ── Post-generation re-stamp of the boxes the shared re-stamp cannot reach ───

def _box_norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _value_keys(value: Any) -> set:
    """Comparable keys for a value a box may print: its letters and digits,
    and for an amount its whole dollars."""
    s = _clean_text(value)
    if not s:
        return set()
    keys = {_box_norm(s)}
    money = parse_money(s)
    if money:
        keys.add("$" + str(int(round(money[0]))))
    iso = _date_iso(s) if re.search(r"\d", s) else None
    if iso:
        keys.add("d" + iso)
    return keys - {""}


def producer_values(facts: Any) -> set:
    """Comparable keys of every value a person supplied in this table."""
    out = set()
    rows = _fv(facts, "coverage_lines")
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        for f in (r.get(ROW_FIELDS) or []):
            col = COLUMN.get(f)
            if col and r.get(col):
                out |= _value_keys(r.get(col))
    return out


def restamp_nonfillable_boxes(generated: dict, before: dict, after: dict,
                              raw_text: Optional[str] = None, *,
                              raw_text_before: Optional[str] = None) -> List[str]:
    """Re-stamp every NON-FILLABLE box (premiums: the 125 line and OTHER rows,
    the prior-carrier grid, the 130's WC premium) whose generation value a
    change moved - through the one door `pdf_service.nonfillable_box_value`,
    the same chain generation runs. `_restamp_changed_boxes` skips these boxes
    by design (a premium is never a question). A box a person typed keeps its
    value; a box edited since generation keeps it. Returns forms changed.

    ``raw_text`` is the documents' text AFTER the change (the presence backstop
    reads it); ``raw_text_before`` the text the forms were generated from,
    which differs when documents were added or removed (the documents door,
    `session_documents.restamp_forms`). Default: the same text - a policy-line
    change does not touch the documents. Reading the OLD value against the new
    text could make a box generation left blank look edited and skip a real
    move."""
    if raw_text_before is None:
        raw_text_before = raw_text
    try:
        from services.pdf_service import (
            _is_nonfillable_field, _schema_context, display_value_for_box, nonfillable_box_value,
        )
        from services.form_instances import base_form_id, facts_for_form
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("policy_lines: non-fillable re-stamp unavailable - %s", exc)
        return []
    people = ("producer", "client_arq")
    touched: List[str] = []
    for fid, form in (generated or {}).items():
        if not isinstance(form, dict):
            continue
        schema = form.get("schema") or {}
        if not schema:
            continue
        base = base_form_id(fid)
        state = form.get("field_state") or dict(form.get("mapped") or {})
        conf = form.get("confidence") or {}
        moved = False
        f_before = {**facts_for_form(before, fid), "_form_id": base}
        f_after = {**facts_for_form(after, fid), "_form_id": base}
        hay_b: list = [None]
        hay_a: list = [None]
        with _schema_context(schema):
            for box in schema.keys():
                if not _is_nonfillable_field(box):
                    continue
                try:
                    new_raw = nonfillable_box_value(box, f_after, schema, raw_text, hay_a)
                    old_raw = nonfillable_box_value(box, f_before, schema, raw_text_before, hay_b)
                except Exception as exc:                      # noqa: BLE001
                    logger.debug("policy_lines: %s/%s skipped (%s)", fid, box, exc)
                    continue
                if _box_norm(new_raw) == _box_norm(old_raw):
                    continue
                try:
                    new = str(display_value_for_box(base, box, new_raw, facts=f_after) or "").strip() \
                        if new_raw not in (None, "") else ""
                    old = str(display_value_for_box(base, box, old_raw, facts=f_before) or "").strip() \
                        if old_raw not in (None, "") else ""
                except Exception:                             # noqa: BLE001
                    new = str(new_raw or "").strip()
                    old = str(old_raw or "").strip()
                cur = str(state.get(box) or "").strip()
                if _box_norm(cur) == _box_norm(new):
                    continue
                if conf.get(box) in people:
                    continue                                  # a person's value stands
                if cur and _box_norm(cur) != _box_norm(old):
                    continue                                  # edited since generation
                state[box] = new
                if new:
                    conf[box] = "filled"
                else:
                    conf.pop(box, None)
                moved = True
        if moved:
            form["field_state"] = state
            form["confidence"] = conf
            form["_pdf_cache_hash"] = ""
            form["pdf_bytes"] = None
            touched.append(fid)
    return touched


def label_producer_boxes(generated: dict, states_before: Dict[str, dict],
                         facts_after: dict) -> List[str]:
    """A box this change MOVED that now prints a value the producer typed in
    the table is the producer's ("producer" label - green, full fill weight);
    every other moved box keeps the engine's label. Returns forms relabelled."""
    mine = producer_values(facts_after)
    if not mine:
        return []
    touched: List[str] = []
    for fid, form in (generated or {}).items():
        if not isinstance(form, dict):
            continue
        before = states_before.get(fid) or {}
        state = form.get("field_state") or {}
        conf = form.get("confidence") or {}
        relabelled: set = set()
        changed = False
        for box, val in state.items():
            if _box_norm(val) == _box_norm(before.get(box)) or not str(val or "").strip():
                continue
            if conf.get(box) in ("producer", "client_arq"):
                continue
            if _value_keys(val) & mine:
                conf[box] = "producer"
                relabelled.add(box)
                changed = True
        if changed:
            form["confidence"] = conf
            # A producer's value replaced whatever the client had in the box.
            form["client_filled_fields"] = [b for b in (form.get("client_filled_fields") or [])
                                            if b not in relabelled]
            touched.append(fid)
    return touched


# ── The change itself (routes call this) ──────────────────────────────────────

def _active_docs(session: dict) -> List[dict]:
    docs = [d for d in (session.get("docs") or []) if isinstance(d, dict)]
    return [d for d in docs if not d.get("excluded")] or docs


def _entries_and_text(session: dict) -> Tuple[Optional[list], str]:
    facts = session.get("facts") or {}
    entries = _fv(facts, "dec_page_entries")
    if not isinstance(entries, list) or not entries:
        entries = [e for d in _active_docs(session)
                   for e in (_fv(d.get("facts") or {}, "dec_page_entries") or [])
                   if isinstance(e, dict)] or None
    text = "\n".join(str(d.get("text") or "") for d in _active_docs(session))
    return entries, text


def plan_change(session: dict, action: str, *, edit_key: str = "", line_key: str = "",
                fields: Optional[dict] = None, line_id: str = "",
                user: Any = None) -> Tuple[dict, List[dict]]:
    """The store after one producer action, and the audit rows describing it.
    Raises PolicyLineError on a refused change, KeyError on an unknown row.
    Pure: nothing is written."""
    facts = session.get("facts") or {}
    store = read_store(facts)
    entries, text = _entries_and_text(session)
    audit: List[dict] = []
    if action == "edit":
        key = str(edit_key or "").strip()
        if not key:
            raise KeyError("edit_key")
        row = find_row(facts, key)
        if key.startswith(ADDED_PREFIX):
            line_id_ = key[len(ADDED_PREFIX):]
            entry = added_entry(store, line_id_)
            if entry is None:
                raise KeyError(key)
            clean = validate_fields(fields, current=entry, entries=entries, text=text,
                                    umbrella_family=entry.get("family") == UMBRELLA_FAMILY)
            changed = {f: v for f, v in clean.items() if _clean_text(entry.get(f)) != v}
            if not changed:
                return store, []
            new_store = store_with_added_update(store, line_id_, changed, user)
            for f, v in changed.items():
                audit.append({"field": f"policy::{key}::{f}", "previous": _clean_text(entry.get(f)),
                              "new": v})
            return new_store, audit
        if row is None:
            raise KeyError(key)
        clean = validate_fields(fields, current=row, entries=entries, text=text,
                                document_record=True)
        changed = {f: v for f, v in clean.items() if _clean_text(row.get(f)) != v}
        if not changed:
            return store, []
        new_store = store_with_edit(store, key, changed, anchor_for(facts, key), user)
        for f, v in changed.items():
            audit.append({"field": f"policy::{key}::{f}", "previous": _clean_text(row.get(f)),
                          "new": v})
        return new_store, audit
    if action == "add":
        opt = line_option(line_key)
        if not opt:
            raise PolicyLineError({"line": "Choose a line of business."})
        clean = validate_fields(fields, adding=True, entries=entries, text=text,
                                umbrella_family=opt[1] == UMBRELLA_FAMILY)
        new_store, new_id = store_with_added(store, opt[0], clean, user)
        summary = "; ".join(f"{FIELD_LABELS[f]} {v}" for f, v in clean.items() if v)
        audit.append({"field": f"policy::{ADDED_PREFIX}{new_id}", "previous": "not in package",
                      "new": f"{opt[3]} - {summary}"[:2000]})
        return new_store, audit
    if action == "remove":
        lid = str(line_id or "").strip()
        if lid.startswith(ADDED_PREFIX):
            lid = lid[len(ADDED_PREFIX):]
        entry = added_entry(store, lid)
        if entry is None:
            if find_row(facts, str(line_id or "").strip()) is not None:
                raise PolicyLineError(message="A policy from your documents cannot be "
                                              "removed - correct its values instead.")
            raise KeyError(lid)
        new_store = store_without_added(store, lid)
        opt = line_option(entry.get("line_key"))
        audit.append({"field": f"policy::{ADDED_PREFIX}{lid}",
                      "previous": f"{opt[3] if opt else entry.get('family')} - "
                                  f"{entry.get('carrier_name') or ''}",
                      "new": "removed"})
        return new_store, audit
    raise PolicyLineError(message="Unknown action.")


_DERIVED_KEYS = ("coverage_lines", "_line_records", "_scoped", "_programme_writers",
                 "carrier_is_current_policy", "premium_is_current_policy",
                 "current_term_rows_ok", "renews_current_programme")


def stale_keys(stored: Any, now: Any) -> List[str]:
    """Derived keys the stored facts hold and the new facts do not - the
    additive facts write would otherwise keep them (an emptied coverage list
    keeps the removed line)."""
    if not isinstance(stored, dict) or not isinstance(now, dict):
        return []
    return [k for k in _DERIVED_KEYS if k in stored and (k not in now or now.get(k) in (None, [], {}))]


async def apply_post_generation(session: dict, session_id: str, new_store: dict,
                                *, upd=None) -> dict:
    """The change AFTER forms exist: the stored facts are rebuilt in place (the
    documents' rows, the Data Consistency confirmations, then the producer's
    lines), the Data Consistency assessment is redone, and every generated box
    the change moves is re-stamped - person-typed boxes kept. The caller
    re-scores (`recalculate_session_scores`). Returns the pieces the route
    answers with."""
    from services.extraction_pipeline import UNCONFIRMED_COVERAGE_LINES_KEY
    from services.underwriting_consistency import (
        apply_confirmations, assess_underwriting_consistency,
    )
    from services.extraction_pipeline import unresolved_withheld_keys, unresolved_conflict_keys
    from services.arq_service import _restamp_changed_boxes
    if upd is None:
        from repositories.session_repository import upd_processing_session as upd

    generated = copy.deepcopy(session.get("generated_forms") or {})
    docs = _active_docs(session)
    facts_before = copy.deepcopy(session.get("facts") or {})
    flags_before = dict(session.get("flags") or {})
    facts = copy.deepcopy(facts_before)
    flags = dict(flags_before)
    facts[STORE_KEY] = copy.deepcopy(new_store)
    pristine = facts.get(UNCONFIRMED_COVERAGE_LINES_KEY)
    if isinstance(pristine, list):
        facts["coverage_lines"] = copy.deepcopy(pristine)
    confirmations = dict(session.get("underwriting_confirmations") or {})
    if confirmations:
        facts = apply_confirmations(facts, confirmations, docs=docs)
    report = apply_producer_policy_lines(facts, flags, docs, restore_flags=True, force=True)

    underwriting = assess_underwriting_consistency(docs, facts, confirmations, flags=flags)
    delete: List[str] = list(stale_keys(facts_before, facts))
    _confirmed = set(confirmations.keys())
    _withheld = set(unresolved_withheld_keys(underwriting, confirmations))
    _withheld |= {k for k in (facts.get("_uw_conflicted_keys") or []) if k not in _confirmed}
    _conflicts = set(unresolved_conflict_keys(underwriting, confirmations)) | _withheld
    for _key, _vals in (("_uw_conflicted_keys", _withheld), ("_uw_conflict_keys", _conflicts)):
        if _vals:
            facts[_key] = sorted(_vals)
        elif facts.pop(_key, None) is not None or _key in facts_before:
            delete.append(_key)
    open_now = {f.get("fact_key") for f in underwriting.get("fields") or [] if f.get("review_required")}
    structured = session.get("structured_issues") or []
    try:
        from services.issue_registry import doc_conflict_fact_key, picker_fact_key
        prior_open = {f.get("fact_key") for f in ((session.get("underwriting_consistency") or {})
                                                  .get("fields") or []) if f.get("review_required")}
        gone = prior_open - open_now
        if gone:
            structured = [i for i in structured if not (isinstance(i, dict) and (
                picker_fact_key(i.get("code")) in gone or doc_conflict_fact_key(i.get("code")) in gone))]
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("policy_lines: stale picker issues kept - %s", exc)

    # Every box the change moves, from the engine generation used: facts AND
    # flags (generation stamps `{**facts, **flags}`) and the package's forms.
    try:
        from services.form_service import package_form_ids
        pkg = package_form_ids(session) or list(generated.keys())
    except Exception:                                         # noqa: BLE001
        pkg = list(generated.keys())
    view_before = {**facts_before, **flags_before, "_package_form_ids": pkg}
    view_after = {**facts, **flags, "_package_form_ids": pkg}
    states_before = {fid: dict((f or {}).get("field_state") or (f or {}).get("mapped") or {})
                     for fid, f in generated.items() if isinstance(f, dict)}
    stamped = set(_restamp_changed_boxes(generated, view_before, view_after, own_keys=set(),
                                         own_value=None, provenance="producer", scope=None) or [])
    raw_text = "\n".join(str(d.get("text") or "") for d in docs)
    stamped |= set(restamp_nonfillable_boxes(generated, view_before, view_after, raw_text) or [])
    label_producer_boxes(generated, states_before, facts)
    for fid in stamped:
        form = generated.get(fid)
        if isinstance(form, dict):
            form["_pdf_cache_hash"] = ""
            form["pdf_bytes"] = None

    updates = {"facts": facts, "flags": flags, "generated_forms": generated,
               "underwriting_consistency": underwriting, "structured_issues": structured}
    await upd(session_id, updates, delete_facts=sorted(set(delete)) or None)
    return {"forms_updated": sorted(stamped), "underwriting_consistency": underwriting,
            "report": report, "facts": facts, "flags": flags}
