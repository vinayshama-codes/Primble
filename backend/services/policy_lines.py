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

import asyncio
import copy
import hashlib
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
# The policy the agent chose for ACORD 125's prior-carrier OTHER column (Brent,
# 19 Oct 2026: "the primary excess / umbrella policy, unless the agent specifies
# otherwise"): {"edit_key", "anchor", "at", "by"} - re-found like an edit.
PRIOR_OTHER_KEY = "prior_other"
# WHO supplied a field of an edit (22 Oct 2026): a value the CLIENT gave in the
# questionnaire is recorded as theirs in `edits[key]["sources"]`
# ({field: CLIENT_SOURCE}); a field with no entry is the producer's, which is
# what every edit stored before this build means.
CLIENT_SOURCE = "client_arq"
PRODUCER_SOURCE = "producer"

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
            originals = e.get("originals")
            if isinstance(originals, dict):
                kept = {f: ("" if originals.get(f) is None else str(originals.get(f)))
                        for f in FIELDS if f in originals}
                if kept:
                    out["edits"][key]["originals"] = kept
            sources = e.get("sources")
            if isinstance(sources, dict):
                theirs = {f: CLIENT_SOURCE for f, s in sources.items()
                          if f in clean and s == CLIENT_SOURCE}
                if theirs:
                    out["edits"][key]["sources"] = theirs
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
    choice = held.get(PRIOR_OTHER_KEY)
    if isinstance(choice, dict) and str(choice.get("edit_key") or "").strip():
        out[PRIOR_OTHER_KEY] = {
            "edit_key": str(choice.get("edit_key")).strip(),
            "anchor": dict(choice.get("anchor") or {}) if isinstance(choice.get("anchor"), dict) else {},
            "at": str(choice.get("at") or ""),
            "by": str(choice.get("by") or ""),
        }
    return out


def store_has_content(store: Any) -> bool:
    return isinstance(store, dict) and bool(store.get("edits") or store.get("added"))


def _entry_fields(family: Any) -> Tuple[str, ...]:
    """The facts an ADDED line of ``family`` holds: the six policy facts, plus
    the umbrella family's limits and SIR."""
    return FIELDS + (UMBRELLA_LIMIT_FIELDS if family == UMBRELLA_FAMILY else ())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fields_back_to_documents(facts: dict, store: dict, key: str, changed: Dict[str, str]) -> set:
    """The fields of ``changed`` whose new value is what the record shows with
    no person's edit at all - the documents' own value. Never raises."""
    try:
        if key not in (store.get("edits") or {}):
            return set()
        # The documents' value as it stood when the field was FIRST edited
        # (recorded with the edit): before forms the re-merge writes an edit
        # into the facts themselves, so removing it from the store no longer
        # shows the documents' value (live e66d68d7, 25 Oct).
        originals = ((store["edits"].get(key) or {}).get("originals") or {})
        if originals:
            return {f for f, v in changed.items()
                    if f in originals and _clean_text(originals[f]) == v and v != ""}
        bare = copy.deepcopy(store)
        bare["edits"].pop(key, None)
        f2 = dict(facts or {})
        f2[STORE_KEY] = bare
        doc_row = find_row(f2, key) or {}
        return {f for f, v in changed.items() if _clean_text(doc_row.get(f)) == v and v != ""}
    except Exception:                                          # noqa: BLE001
        return set()


def store_with_edit(store: dict, edit_key: str, fields: Dict[str, str],
                    anchor: Optional[dict] = None, user: Any = None,
                    source: Optional[str] = None) -> dict:
    """The store with ``fields`` merged into the edit of ``edit_key``. The
    anchor of the FIRST edit of a record is kept: it describes the record as
    the documents print it, which is what can re-find it later.

    ``source`` - CLIENT_SOURCE when the values are a client's questionnaire
    answers; anything else is the producer's, and a producer's later edit of a
    field makes that field theirs again."""
    out = copy.deepcopy(store)
    cur = out["edits"].get(edit_key) or {"fields": {}, "anchor": dict(anchor or {})}
    cur["fields"] = {**(cur.get("fields") or {}), **{f: ("" if v is None else str(v))
                                                    for f, v in fields.items() if f in FIELDS}}
    sources = dict(cur.get("sources") or {})
    for f in fields:
        if f not in FIELDS:
            continue
        if source == CLIENT_SOURCE:
            sources[f] = CLIENT_SOURCE
        else:
            sources.pop(f, None)
    if sources:
        cur["sources"] = sources
    else:
        cur.pop("sources", None)
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


def table_rows(facts: Any, docs: Any = None) -> List[dict]:
    """One row per policy for "Policies in this submission": the document
    records first (in record order), then the lines the producer added.

    ``docs`` (the package's documents): each row then also names the PAGE of
    each source document that prints it, and each limit the page that prints
    it (`_with_pages` - Brent, 19 Oct 2026: "keep the source and page
    reference for every extracted coverage and limit")."""
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
    clients = client_fields_by_key(facts)
    # Where each policy prints in ACORD 125's PRIOR CARRIER INFORMATION (Brent,
    # 19 Oct 2026) - a grid column, or ACORD 101 when the grid has no box for
    # it - and whether its premium is missing there. {} unless the policies are
    # the expiring term the proposal renews.
    try:
        from services.pdf_service import prior_grid_placements
        placements = prior_grid_placements(facts) if isinstance(facts, dict) else {}
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("policy_lines: prior-carrier placement skipped - %s", exc)
        placements = {}
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
            # A person's values on a document's policy: the producer's own
            # corrections, and the ones a client gave in the questionnaire
            # (22 Oct 2026 - kept apart, so a client's answer never reads as
            # "Corrected by you").
            "edited_fields":   sorted(f for f in (rec.get("producer_fields") or [])
                                      if f in FIELDS and f not in clients.get(edit_key, ()))
                               if not added else [],
            "client_fields":   sorted(f for f in (rec.get("producer_fields") or [])
                                      if f in FIELDS and f in clients.get(edit_key, ()))
                               if not added else [],
            # Brent #10: the policy's OWN limit (display only - `record_limits`)
            # and the key "Group by carrier" groups the rows by.
            "limit_parts":     limits.get(str(rec.get("id")), []),
            "carrier_key":     _carrier_group_key(rec.get("carrier_name")),
        }
        row["limit"] = "; ".join(f"{p['amount']} {p['label']}" for p in row["limit_parts"])
        placed = placements.get(str(rec.get("id"))) or {}
        row["prior_grid"] = placed.get("where")
        row["premium_missing"] = bool(placed) and not placed.get("premium")
        row["prior_other_line"] = bool(placed.get("other_line"))
        row["prior_other_candidate"] = bool(placed.get("other_candidate"))
        if added and rec.get("line") == UMBRELLA_FAMILY:
            # An added umbrella / excess layer carries its own limits and SIR.
            for f in UMBRELLA_LIMIT_FIELDS:
                row[f] = _money_display(rec.get(f))
        if docs:
            _with_pages(row, rec, docs)
        out.append(row)
    return out


def _with_pages(row: dict, rec: dict, docs: Any) -> None:
    """Add ``source_refs`` ([{"file", "page"}] - the page of each source
    document printing this policy: its line name beside its premium, else
    its number, else the name alone) and a ``page`` on each limit part (the
    first source page printing the amount beside the line's name). A value
    no page prints gets no page - never a guess (`fact_lineage.locate_page`)."""
    try:
        from services.fact_lineage import locate_page
    except Exception:                                         # noqa: BLE001
        return
    by_name: Dict[str, dict] = {}
    for d in docs if isinstance(docs, list) else []:
        if isinstance(d, dict) and not d.get("excluded"):
            by_name.setdefault(str(d.get("filename") or d.get("doc_id") or "").strip(), d)
    name = _clean_text(rec.get("line_printed"))
    premium = rec.get("premium")
    value = (f"{float(premium):,.2f}" if isinstance(premium, (int, float))
             and not isinstance(premium, bool) and premium > 0 else
             _clean_text(rec.get("policy_number")) or name)
    near = [name] if value != name else []
    texts: List[Tuple[str, str]] = []
    refs: List[dict] = []
    for src in row.get("sources") or []:
        doc = by_name.get(str(src).strip())
        if not doc:
            continue
        text = str(doc.get("text") or "")
        texts.append((str(src), text))
        refs.append({"file": str(src), "page": locate_page(text, value, near) if value else None})
    if refs:
        row["source_refs"] = refs
    # A limit is cited where it is printed beside its line's own name - the
    # policy's own documents first, then the others (the GL limits a package
    # dec does not print come from the umbrella's schedule of underlying).
    own = {src for src, _t in texts}
    texts += [(n, str(d.get("text") or "")) for n, d in by_name.items() if n and n not in own]
    names = [n for n in dict.fromkeys([name, _family_label(rec)]) if n]
    for part in row.get("limit_parts") or []:
        if not isinstance(part, dict) or not part.get("amount"):
            continue
        for src, text in texts:
            page = locate_page(text, part["amount"], names)
            if page is not None:
                part["page"], part["file"] = page, src
                break


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


def prior_other_record(facts: Any) -> Optional[dict]:
    """The policy record the agent chose for ACORD 125's prior-carrier OTHER
    column, re-found by its edit key or, after a re-run renamed it, by its
    anchor; None when no choice is stored or the policy is gone (the default
    rule then decides - `pdf_service._prior_other_line_key`)."""
    held = (facts or {}).get(STORE_KEY) if isinstance(facts, dict) else None
    choice = held.get(PRIOR_OTHER_KEY) if isinstance(held, dict) else None
    if not isinstance(choice, dict):
        return None
    key = _clean_text(choice.get("edit_key"))
    rec = record_for_key(facts, key) if key else None
    if rec is None and isinstance(choice.get("anchor"), dict):
        try:
            from services.extraction_service import policy_line_records
            recs = policy_line_records(facts.get("_line_records")
                                       if isinstance(facts.get("_line_records"), list) else [])
        except Exception:                                     # noqa: BLE001
            recs = []
        rec = _find_by_anchor(choice["anchor"], recs)
    return rec


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


def client_fields_by_key(facts: Any) -> Dict[str, set]:
    """{edit key: the fields of that policy a CLIENT supplied} (22 Oct 2026)."""
    return {k: set(e.get("sources") or {}) for k, e in read_store(facts)["edits"].items()
            if e.get("sources")}


def producer_values(facts: Any) -> set:
    """Comparable keys of every value the PRODUCER supplied in this table (a
    value a client gave in the questionnaire is the client's, not theirs)."""
    out = set()
    rows = _fv(facts, "coverage_lines")
    clients = client_fields_by_key(facts)
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        theirs = clients.get(str(r.get(ROW_KEY) or ""), set())
        for f in (r.get(ROW_FIELDS) or []):
            if f in theirs:
                continue
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
                         facts_after: dict, *, label: str = PRODUCER_SOURCE,
                         values: Optional[set] = None) -> List[str]:
    """A box this change MOVED that now prints a value the producer typed in
    the table is the producer's ("producer" label - green, full fill weight);
    every other moved box keeps the engine's label. Returns forms relabelled.

    ``label`` / ``values`` (22 Oct 2026): a client's questionnaire answer
    labels the boxes printing ITS values (``values``, `_value_keys` of each)
    "client_arq" and lists them as client-filled, as every other client
    answer does."""
    mine = set(values) if values is not None else producer_values(facts_after)
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
                conf[box] = label
                relabelled.add(box)
                changed = True
        if changed:
            form["confidence"] = conf
            kept = [b for b in (form.get("client_filled_fields") or []) if b not in relabelled]
            if label == CLIENT_SOURCE:
                # The client's own answer is on these boxes now.
                kept += sorted(relabelled)
            # (A producer's value replaced whatever the client had in the box.)
            form["client_filled_fields"] = kept
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
                user: Any = None, source: Optional[str] = None) -> Tuple[dict, List[dict]]:
    """The store after one producer action, and the audit rows describing it.
    Raises PolicyLineError on a refused change, KeyError on an unknown row.
    Pure: nothing is written. ``source`` - CLIENT_SOURCE for a questionnaire
    answer about a document's policy (`apply_policy_answers`)."""
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
        # A value typed back to what the DOCUMENTS say is no edit (live
        # bcfd175b, 25 Oct: a premium changed and typed back to its own $4,162
        # became a person-typed premium and printed on ACORD 125 page one).
        _edited = set(((store.get("edits") or {}).get(key) or {}).get("fields") or {})
        reverted = _fields_back_to_documents(facts, store, key,
                                             {f: v for f, v in clean.items() if f in _edited})
        changed = {f: v for f, v in clean.items()
                   if _clean_text(row.get(f)) != v or f in reverted}
        if not changed:
            return store, []
        _prior = ((store.get("edits") or {}).get(key) or {})
        _orig = dict(_prior.get("originals") or {})
        for f in changed:
            if f not in (_prior.get("fields") or {}) and f not in _orig:
                _orig[f] = _clean_text(row.get(f))   # the documents' value, before this edit
        new_store = store_with_edit(store, key, {f: v for f, v in changed.items() if f not in reverted},
                                    anchor_for(facts, key), user, source=source) \
            if len(reverted) < len(changed) else copy.deepcopy(store)
        if key in new_store["edits"]:
            new_store["edits"][key]["originals"] = {f: o for f, o in _orig.items()
                                                    if f in (new_store["edits"][key].get("fields") or {})}
        if reverted:
            _e = new_store["edits"].get(key) or {}
            for f in reverted:
                (_e.get("fields") or {}).pop(f, None)
                (_e.get("sources") or {}).pop(f, None)
            if _e and not (_e.get("fields") or {}):
                new_store["edits"].pop(key, None)
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
    if action == "prior_other":
        # The agent's pick for ACORD 125's prior-carrier OTHER column (19 Oct
        # 2026); an empty key goes back to the rule (umbrella first).
        key = str(edit_key or "").strip()
        current = store.get(PRIOR_OTHER_KEY) or {}
        rows_now = {r.get("edit_key"): r for r in table_rows(facts)}
        if key:
            row = rows_now.get(key)
            if row is None:
                raise KeyError(key)
            if not (row.get("prior_other_candidate") or row.get("prior_other_line")):
                raise PolicyLineError(message="ACORD 125's prior-carrier Other column cannot "
                                              "hold this policy - its line has a column of its own.")
        if key == str(current.get("edit_key") or "") or (not key and not current):
            return store, []

        def _named(k: str) -> str:
            r = rows_now.get(k) if k else None
            return f"{r.get('line_label')} - {r.get('carrier_name')}" if r else (k or "")

        new_store = copy.deepcopy(store)
        if key:
            new_store[PRIOR_OTHER_KEY] = {"edit_key": key, "anchor": anchor_for(facts, key),
                                          "at": _now(), "by": str(user or "")}
        else:
            new_store.pop(PRIOR_OTHER_KEY, None)
        audit.append({"field": "policy::prior_other",
                      "previous": _named(str(current.get("edit_key") or "")) or "the default policy",
                      "new": _named(key) or "the default policy (umbrella first)"})
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
                                *, upd=None, provenance: str = PRODUCER_SOURCE,
                                own_values: Optional[set] = None) -> dict:
    """The change AFTER forms exist: the stored facts are rebuilt in place (the
    documents' rows, the Data Consistency confirmations, then the producer's
    lines), the Data Consistency assessment is redone, and every generated box
    the change moves is re-stamped - person-typed boxes kept. The caller
    re-scores (`recalculate_session_scores`). Returns the pieces the route
    answers with.

    ``provenance`` / ``own_values`` - who supplied THIS change's values and
    their comparable keys (`label_producer_boxes`): the questionnaire door
    passes the client's (`apply_policy_answers`); the table, the producer's."""
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
    label_producer_boxes(generated, states_before, facts, label=provenance, values=own_values)
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


# One change at a time per package in this process: two quick saves (the table
# and a questionnaire answer) would otherwise each read the store before the
# other wrote it. The table's routes and the questionnaire door share it.
_LOCKS: Dict[str, asyncio.Lock] = {}


def session_lock(session_id: str) -> asyncio.Lock:
    lock = _LOCKS.get(session_id)
    if lock is None:
        lock = _LOCKS[session_id] = asyncio.Lock()
    return lock


# ── Questionnaire answers by policy (22 Oct 2026) ─────────────────────────────
# Open since 17 Sep: "the questionnaire's policy number / carrier answers still
# land on no per-line box". A package holds one RECORD per policy (this table);
# every SECTION form's header (126 GL, 127 auto, 130 WC, 131 each umbrella
# layer, 140 property ...) prints ITS policy's record
# (`pdf_service._resolve_section_policy_identity`), and the 125 prior-carrier
# grid and question 4 read the records. A questionnaire answer to
# `policy_number` / `carrier_name` / `carrier_naic` wrote only the package-level
# fact - which no section header reads once the package has records - and the
# client's raw answer went into the header box of EVERY form carrying it, so one
# policy's number could print on another line's header. One door now:
#   * QUESTIONS: a section form's blank header box is asked PER POLICY - one
#     question per record of that form's line lacking the value
#     (`questions_by_policy`). A package with ONE policy keeps its one package
#     question: there is no other policy the answer could be.
#   * ANSWERS: a per-policy answer - and a package answer on a one-policy
#     package - writes its record through THIS table's door (`plan_change` ->
#     `apply_post_generation`: every form re-stamped, person-typed boxes kept).
#   * A value that DISAGREES with what the package already states for that
#     policy (a document, or a person) never replaces it: a CLIENT's answer is
#     held for the producer (`client_answer_review`, "Needs your decision"); a
#     PRODUCER's answer is their decision, exactly as in the table.
#   * The package-level fact keeps its meaning: a package answer still writes
#     it; a per-policy answer never does (SYS-06, as every edit here).
ANSWER_FACTS: Tuple[str, ...] = ("policy_number", "carrier_name", "carrier_naic")
# The answer key: "insurer_policy::<fact>::<line[~excess]>::<digest>". The
# "insurer" word is deliberate - `question_classifier` routes a question by its
# FIELD NAME, and "insurer" is the agency word the header boxes' own names
# (`Insurer_FullName_A`) are routed by, so a policy's question reaches the same
# audience its box did. The record's edit key is DIGESTED, never embedded: a
# carrier's name inside a field name ("...@FAXON...") could match a routing
# word. The digest names the record; the line is only there to read.
ANSWER_PREFIX = "insurer_policy::"
_ANSWER_KEY_RE = re.compile(
    "^" + re.escape(ANSWER_PREFIX) + "(" + "|".join(ANSWER_FACTS) + r")::"
    r"([a-z_]+(?:~excess)?)::([0-9a-f]{10})$")
# The header box each fact prints in on a section form - pinned by test against
# `pdf_service._SECTION_IDENTITY_RE` and the rule table.
HEADER_BOXES: Dict[str, str] = {
    "policy_number": "Policy_PolicyNumberIdentifier_A",
    "carrier_name":  "Insurer_FullName_A",
    "carrier_naic":  "Insurer_NAICCode_A",
}
WRITE, SAME, HOLD, SKIP, REFUSE = "write", "same", "hold", "skip", "refuse"
_ANSWER_LABEL: Dict[str, str] = {"policy_number": "Policy number",
                                 "carrier_name": "Insurance company",
                                 "carrier_naic": "NAIC code"}
_ANSWER_QUESTION: Dict[str, Tuple[str, str]] = {
    "policy_number": ("Policy number for {name}",
                      "Enter just the policy number this policy's declarations page prints, "
                      "e.g. 'GL-123456'."),
    "carrier_name":  ("Insurance company for {name}",
                      "Enter the insurance company's full name as the policy prints it."),
    "carrier_naic":  ("NAIC code for {name}",
                      "The insurance company's 5-digit NAIC code, printed on the declarations "
                      "page, e.g. '25186'."),
}
_HELD_MISMATCH = ("The client's answer does not match what the package already states for "
                  "this policy.")
_HELD_GONE = ("The policy this answer was asked about is no longer in the package as it was "
              "when the questionnaire was sent.")
_SECTION_FAMILIES: Dict[str, frozenset] = {}


def _digest(edit_key: Any) -> str:
    return hashlib.sha256(str(edit_key or "").encode("utf-8")).hexdigest()[:10]


def _scope(row: dict) -> str:
    line = re.sub(r"[^a-z_]", "", str((row or {}).get("line") or "").lower()) or "line"
    if line == UMBRELLA_FAMILY and (row or {}).get("layer") == "excess":
        return f"{line}~excess"
    return line


def answer_key(fact: str, row: dict) -> str:
    """The questionnaire field name of ``fact`` for one policy (a table row)."""
    return f"{ANSWER_PREFIX}{fact}::{_scope(row)}::{_digest(row.get('edit_key'))}"


def parse_answer_key(key: Any) -> Optional[Tuple[str, str, str]]:
    """(fact, line scope, record digest) of a policy answer key, else None."""
    m = _ANSWER_KEY_RE.match(str(key or "").strip())
    return (m.group(1), m.group(2), m.group(3)) if m else None


def is_answer_key(key: Any) -> bool:
    return parse_answer_key(key) is not None


def answer_fact(key: Any) -> Optional[str]:
    """The fact a policy answer key asks for ("policy_number" ...), else None."""
    parsed = parse_answer_key(key)
    return parsed[0] if parsed else None


def section_families(form_id: Any) -> frozenset:
    """The line families a SECTION form's header describes (`pdf_service.
    _SECTION_FORM_LINE_PHRASES`, read by the header resolver itself); empty for
    a package-level form (125, 101, 25) - its header is the package's."""
    try:
        from services.form_instances import base_form_id
        base = base_form_id(str(form_id or ""))
    except Exception:                                         # noqa: BLE001
        base = str(form_id or "")
    held = _SECTION_FAMILIES.get(base)
    if held is None:
        try:
            from services.pdf_service import _SECTION_FORM_LINE_PHRASES
            from services.lob_canon import canon_line
            phrases = _SECTION_FORM_LINE_PHRASES.get(base) or ()
            held = frozenset(f for f in (canon_line(p) for p in phrases) if f)
        except Exception:                                     # noqa: BLE001
            return frozenset()
        _SECTION_FAMILIES[base] = held
    return held


def is_section_form(form_id: Any) -> bool:
    return bool(section_families(form_id))


def section_form_ids(generated: Any) -> set:
    """The generated forms (instance ids) whose header is ONE policy's."""
    return {str(fid) for fid in (generated or {}) if is_section_form(fid)}


def question_rows(facts: Any) -> List[dict]:
    """The policies the package holds, as "Policies in this submission" shows
    them; [] for a package with none (every rule here then stands down)."""
    try:
        return [r for r in table_rows(facts) if isinstance(r, dict) and r.get("edit_key")]
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("policy_lines: policy rows unavailable - %s", exc)
        return []


def form_policy_rows(facts: Any, form_id: Any, rows: List[dict]) -> List[dict]:
    """The policies a section form's header describes: its line's rows - for
    ACORD 131, the rows of the LAYER that copy is stamped for (the plain 131 is
    the lowest layer of a tower, `umbrella_layers`)."""
    families = section_families(form_id)
    if not families:
        return []
    mine = [r for r in rows if r.get("line") in families]
    if UMBRELLA_FAMILY not in families:
        return mine
    try:
        from services import umbrella_layers as ul
        from services.form_instances import instance_key
        slots, assign = ul._assign(facts)
        key = str(instance_key(form_id) or "")
    except Exception:                                         # noqa: BLE001
        return mine
    if len(slots) < 2 and not key:
        return mine                     # one layer (or rivals on it): the plain 131's
    idx = assign.get(key)
    if idx is None or idx >= len(slots):
        return [r for r in mine if r.get("line") != UMBRELLA_FAMILY]
    ids = {str(r.get("id")) for r in (slots[idx].get("records") or []) if isinstance(r, dict)}
    return [r for r in mine if r.get("line") != UMBRELLA_FAMILY or str(r.get("id")) in ids]


def _row_name(row: dict, fact: str) -> str:
    """How a question names one policy: its line and company - or, asking FOR
    the company, its line and number."""
    line = _clean_text(row.get("line_label")) or _family_label(row)
    if fact == "carrier_name":
        number = _clean_text(row.get("policy_number"))
        return f"{line} (policy {number})" if number else line
    carrier = _clean_text(row.get("carrier_name"))
    return f"{line} ({carrier})" if carrier else line


def _forms_label(form_ids: Iterable[Any]) -> str:
    return ", ".join(sorted({str(f).replace("ACORD_", "").replace("ACORD ", "")
                             for f in form_ids if f}))


def _blank_header_facts(form_id: str, form: dict) -> List[str]:
    """The identity facts a section form's header asks for: its box blank and
    asked by the form scan's own rule (`arq_service._scan_asks_box`)."""
    from services.arq_service import _scan_asks_box
    conf = form.get("confidence") or {}
    state = form.get("field_state") or form.get("mapped") or {}
    typed = set(form.get("client_filled_fields") or [])
    return [fact for fact, box in HEADER_BOXES.items()
            if box in conf and box not in typed
            and _scan_asks_box(form_id, conf.get(box), state.get(box))]


def identity_gaps(facts: Any, generated: Any, rows: List[dict]) -> Dict[Tuple[str, str], dict]:
    """{(fact, edit key): {"row", "forms": base form ids}} - every policy whose
    own section header asks for ``fact`` and that does not state it."""
    out: Dict[Tuple[str, str], dict] = {}
    try:
        from services.form_instances import base_form_id
    except Exception:                                         # noqa: BLE001
        base_form_id = str                                    # type: ignore
    for fid, form in (generated or {}).items():
        if not isinstance(form, dict) or not is_section_form(fid):
            continue
        asked = _blank_header_facts(str(fid), form)
        if not asked:
            continue
        mine = form_policy_rows(facts, fid, rows)
        for fact in asked:
            for r in mine:
                if _clean_text(r.get(fact)):
                    continue
                slot = out.setdefault((fact, r["edit_key"]), {"row": r, "forms": set()})
                slot["forms"].add(base_form_id(str(fid)))
    return out


def company_rows(rows: List[dict], row: dict) -> List[dict]:
    """``row`` and every other policy of the SAME company, in table order - [row]
    when it names no company. "Same company" is the key the NAIC question was
    asked under (`_carrier_group_key`, `_naic_by_company`), never the looser
    comparison door: "Travelers Indemnity Company" and "... Company of America"
    agree as printings yet are two companies with two NAICs (review, 22 Oct)."""
    company = _carrier_group_key((row or {}).get("carrier_name"))
    if not company:
        return [row]
    return [r for r in rows if r is row or (r.get("edit_key") != row.get("edit_key")
                                            and _carrier_group_key(r.get("carrier_name")) == company)]


def _naic_by_company(gaps: Dict[Tuple[str, str], dict],
                     rows: List[dict]) -> Dict[Tuple[str, str], dict]:
    """A NAIC is the COMPANY's identifier - the header resolver pairs a company
    with the NAIC printed for it on any of its lines (`pdf_service.
    _section_carrier_pair`) - so it is asked ONCE per company: the NAIC gaps of
    one company fold into the first of them (its forms joined, its other
    policies named). A policy naming no company keeps its own question."""
    out: Dict[Tuple[str, str], dict] = {}
    held: Dict[str, Tuple[str, str]] = {}
    order = {r["edit_key"]: i for i, r in enumerate(rows)}
    for k in sorted(gaps, key=lambda k: order.get(k[1], len(order))):
        slot = gaps[k]
        if k[0] != "carrier_naic":
            out[k] = slot
            continue
        company = _carrier_group_key(slot["row"].get("carrier_name"))
        first = held.get(company) if company else None
        if first is None:
            out[k] = {"row": slot["row"], "forms": set(slot["forms"]), "also": []}
            if company:
                held[company] = k
            continue
        out[first]["forms"] |= set(slot["forms"])
        out[first]["also"].append(slot["row"])
    return out


def _policy_questions(gaps: Dict[Tuple[str, str], dict], rows: List[dict],
                      generated: Any) -> List[dict]:
    """One question per (fact, policy) gap - one per COMPANY for a NAIC - named
    so no two read the same."""
    gaps = _naic_by_company(gaps, rows)
    order = {r["edit_key"]: i for i, r in enumerate(rows)}
    items = sorted(gaps.items(), key=lambda kv: (order.get(kv[0][1], len(order)),
                                                 ANSWER_FACTS.index(kv[0][0])))
    names: Dict[Tuple[str, str], str] = {}
    for k, v in items:
        if k[0] == "carrier_naic" and v.get("also"):
            carrier = _clean_text(v["row"].get("carrier_name"))
            lines = [_clean_text(r.get("line_label")) or _family_label(r)
                     for r in [v["row"]] + list(v["also"])]
            names[k] = f"{carrier} ({', '.join(dict.fromkeys(lines))})"
        else:
            names[k] = _row_name(v["row"], k[0])
    for fact in ANSWER_FACTS:
        same: Dict[str, List[Tuple[str, str]]] = {}
        for k in names:
            if k[0] == fact:
                same.setdefault(names[k], []).append(k)
        for name, keys in same.items():
            if len(keys) < 2:
                continue
            for k in keys:                       # the term tells two policies apart
                r = gaps[k]["row"]
                term = " to ".join(t for t in (_clean_text(r.get("effective_date")),
                                               _clean_text(r.get("expiration_date"))) if t)
                names[k] = f"{name}, {term}" if term else name
            again: Dict[str, List[Tuple[str, str]]] = {}
            for k in keys:
                again.setdefault(names[k], []).append(k)
            for n2, ks in again.items():
                if len(ks) > 1:
                    for i, k in enumerate(ks, 1):
                        names[k] = f"{n2}, policy {i}"
    try:
        from services.form_instances import base_form_id
        present = {base_form_id(str(f)) for f in (generated or {})}
    except Exception:                                         # noqa: BLE001
        present = {str(f) for f in (generated or {})}
    out: List[dict] = []
    for (fact, _key), slot in items:
        row = slot["row"]
        forms = set(slot["forms"])
        where = str(row.get("prior_grid") or "")
        if fact in ("policy_number", "carrier_name") and where:
            # ACORD 125's prior-carrier grid prints the expiring policies (or
            # ACORD 101, past the grid) - the answer reaches them too.
            target = "ACORD_101" if where == "ACORD_101" else "ACORD_125"
            if target in present:
                forms.add(target)
        text, hint = _ANSWER_QUESTION[fact]
        out.append({
            "field_name":         answer_key(fact, row),
            "question":           text.format(name=names[(fact, _key)]),
            "hint":               hint,
            "forms":              _forms_label(forms),
            "form_ids":           sorted(forms),
            "field_type":         "text",
            "current_value":      "",
            "_group_label":       None,
            "_is_curated_client": False,
            "_canonical_key":     None,
        })
    return out


def questions_by_policy(questions: List[dict], facts: Any, generated: Any) -> List[dict]:
    """The questionnaire with its policy-number / insurer / NAIC questions asked
    of the policy each box belongs to. See the block comment above.

    * No policy records: returned unchanged.
    * A package question for one of the three facts keeps only the forms its
      answer can reach: the package-level forms (125, 101, 25), plus - with ONE
      policy - that policy's own section forms where it lacks the value. A
      question left with no form is dropped (its boxes are asked per policy, or
      are blank by the header resolver's own rule: no policy of that line).
    * Two or more policies: one question per policy lacking the value on its
      own section form (`identity_gaps`).
    Never raises (the questions come back as they were)."""
    try:
        rows = question_rows(facts)
        if not rows:
            return questions
        gaps = identity_gaps(facts, generated, rows)
        one = rows[0] if len(rows) == 1 else None
        kept: List[dict] = []
        dropped: List[str] = []
        for q in questions or []:
            canon = q.get("_canonical_key") if isinstance(q, dict) else None
            if canon not in ANSWER_FACTS or is_answer_key(q.get("field_name")):
                kept.append(q)
                continue
            forms = [str(f) for f in (q.get("form_ids") or []) if f]
            if not any(is_section_form(f) for f in forms):
                kept.append(q)                    # asked on no section form: untouched
                continue
            reach = set((gaps.get((canon, one["edit_key"])) or {}).get("forms") or ()) if one else set()
            still = [f for f in forms if not is_section_form(f) or f in reach]
            if not still:
                dropped.append(str(q.get("field_name") or canon))
                continue
            if still != forms:
                q = dict(q, form_ids=still, forms=_forms_label(still))
            kept.append(q)
        added = _policy_questions(gaps, rows, generated) if one is None else []
        if dropped or added:
            logger.info("policy_lines: identity questions asked by policy - %d package "
                        "question(s) dropped (%s), %d per-policy question(s) added",
                        len(dropped), ", ".join(dropped[:6]), len(added))
        return kept + added
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("policy_lines: questions by policy skipped - %s", exc, exc_info=True)
        return questions


# ── Judging and applying an answer ───────────────────────────────────────────

def answer_context(session: Any) -> Optional[dict]:
    """What judging an answer needs - the package's policies, its verified
    declarations entries and its documents' text - or None when the package
    has no generated forms or no policy records (nothing here applies)."""
    if not isinstance(session, dict) or not session.get("generated_forms"):
        return None
    facts = session.get("facts") if isinstance(session.get("facts"), dict) else {}
    rows = question_rows(facts)
    if not rows:
        return None
    try:
        entries, text = _entries_and_text(session)
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("policy_lines: declarations entries unavailable - %s", exc)
        entries, text = None, ""
    return {"facts": facts, "rows": rows, "entries": entries, "text": text}


def answer_row(ctx: Optional[dict], key: Any) -> Optional[dict]:
    """The policy (table row) an answer key names - by its record digest, and
    only while that record is still the one the key was made for. Never a
    guess: a record that changed or left gives None."""
    parsed = parse_answer_key(key)
    if not parsed or not ctx:
        return None
    _fact, scope, digest = parsed
    hits = [r for r in ctx.get("rows") or []
            if _digest(r.get("edit_key")) == digest and _scope(r) == scope]
    return hits[0] if len(hits) == 1 else None


def package_target(ctx: Optional[dict], fact: str, form_ids: Iterable[Any] = ()) -> Optional[str]:
    """The ONE policy a PACKAGE-level answer about ``fact`` belongs to, as an
    answer key: the package's only policy; else the one policy the question's
    own section forms describe (a questionnaire sent before this build asked
    the 126's blank header as a package question). None when several could be
    meant - the answer then stays the package's."""
    if not ctx or fact not in ANSWER_FACTS:
        return None
    rows = ctx.get("rows") or []
    if len(rows) == 1:
        return answer_key(fact, rows[0])
    found: Dict[str, dict] = {}
    for f in form_ids or ():
        if is_section_form(f):
            for r in form_policy_rows(ctx.get("facts") or {}, f, rows):
                found[r["edit_key"]] = r
    return answer_key(fact, next(iter(found.values()))) if len(found) == 1 else None


def _answer_text(fact: str, value: Any) -> str:
    s = _clean_text(value)
    if fact == "carrier_naic":
        m = re.fullmatch(r"(?i)(?:naic\b\.?\s*(?:code|number|no\.?|#)?\s*[:#\-]?\s*)?(\d{5})", s)
        if m:
            return m.group(1)
    return s


def _same_value(fact: str, a: Any, b: Any) -> bool:
    if fact == "policy_number":
        return _same_contract(a, b)
    if fact == "carrier_name":
        return _same_company(a, b)
    da, db = re.sub(r"\D", "", str(a or "")), re.sub(r"\D", "", str(b or ""))
    return bool(da) and da == db


def _documents_say_otherwise(ctx: dict, row: dict, fact: str, value: str) -> Tuple[str, str]:
    """For a policy that does NOT state ``fact``: (what the documents print
    instead, why it matters) - ("", "") when nothing - for another policy's
    number, a prior term's number, or another NAIC for this policy's own
    company. A number two policies share can be one package policy's, so it is
    the producer's to confirm, never ours to assume either way."""
    facts = ctx.get("facts") or {}
    if fact == "policy_number":
        for other in ctx.get("rows") or []:
            if other is row or other.get("edit_key") == row.get("edit_key"):
                continue
            if _same_contract(other.get("policy_number"), value):
                name = _row_name(other, fact)
                return (f"{_clean_text(other.get('policy_number'))} ({name})",
                        f"The documents print this number for {name} - check it is this "
                        "policy's too (one package policy can cover several lines).")
        try:
            from services.extraction_service import _norm_policy_number, prior_term_policy_numbers
            if _norm_policy_number(value) in prior_term_policy_numbers(facts):
                return (f"{value} (a prior term)",
                        "The documents print this number for an earlier policy term.")
        except Exception:                                     # noqa: BLE001
            pass
        return "", ""
    if fact == "carrier_naic" and _carrier_group_key(row.get("carrier_name")):
        rows = _fv(facts, "coverage_lines")
        carrier = _clean_text(row.get("carrier_name"))
        company = _carrier_group_key(carrier)
        # The NAICs printed for THIS company - the key its question was asked
        # under (`company_rows`), never a sister company that reads alike.
        found = {re.sub(r"\D", "", str(r.get("naic") or ""))
                 for r in (rows if isinstance(rows, list) else [])
                 if isinstance(r, dict) and not r.get(ROW_ADDED)
                 and _carrier_group_key(r.get("carrier")) == company}
        found = {n for n in found if len(n) == 5}
        printed = next(iter(found)) if len(found) == 1 else ""
        if printed and not _same_value(fact, printed, value):
            return (f"{printed} ({carrier})",
                    f"The documents print NAIC {printed} for {carrier}.")
    return "", ""


def judge(ctx: Optional[dict], key: Any, value: Any, *, person: str) -> dict:
    """`_judge`, never raising: an unexpected failure HOLDS a client's answer
    (it is never lost) and refuses a producer's."""
    try:
        return _judge(ctx, key, value, person=person)
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("policy_lines: answer %s not judged - %s", key, exc, exc_info=True)
        return {"action": HOLD if person == CLIENT_SOURCE else REFUSE,
                "fact": answer_fact(key) or "", "edit_key": "", "value": _clean_text(value),
                "label": _ANSWER_LABEL.get(answer_fact(key) or "", ""),
                "reason": "This answer could not be checked against the package.",
                "source_value": ""}


def _judge(ctx: Optional[dict], key: Any, value: Any, *, person: str) -> dict:
    """What one answer about one policy does: {"action": write | same | hold |
    skip | refuse, "fact", "edit_key", "value" (clean), "label", "reason",
    "source_value"}.

    * not a value ("None", "N/A", "don't know"): skip - an answer never clears a
      policy's value, and a policy lacking it simply stays so;
    * a value the table's own validator refuses (a form number, "NAIC 12"):
      a client's is held with the reason, a producer's refused;
    * the policy states the same value: same (nothing to write);
    * the policy states ANOTHER value (a document's or a person's), or the
      documents print the answer as another policy's: a client's is HELD, a
      producer's written (their decision);
    * otherwise: write."""
    parsed = parse_answer_key(key)
    fact = parsed[0] if parsed else ""
    verdict = {"action": SKIP, "fact": fact, "edit_key": "", "value": "",
               "label": _ANSWER_LABEL.get(fact, ""), "reason": "", "source_value": ""}
    if not parsed:
        return verdict
    on_hold = HOLD if person == CLIENT_SOURCE else REFUSE
    row = answer_row(ctx, key)
    if row is None:
        verdict.update(action=on_hold, value=_clean_text(value), reason=_HELD_GONE)
        return verdict
    verdict["edit_key"] = row["edit_key"]
    carrier = _clean_text(row.get("carrier_name"))
    # A NAIC is its company's (asked once per company, `_naic_by_company`).
    verdict["label"] = (f"{_ANSWER_LABEL[fact]} - {carrier}" if fact == "carrier_naic" and carrier
                        else f"{_ANSWER_LABEL[fact]} - {_row_name(row, fact)}")
    text = _answer_text(fact, value)
    if not text:
        return verdict
    try:
        from services.answer_semantics import VALUE, interpret_answer
        if interpret_answer(fact, text).intent != VALUE:
            verdict["reason"] = "not a value"
            return verdict
    except Exception:                                         # noqa: BLE001
        pass
    try:
        clean = validate_fields({fact: text}, current=row, entries=ctx.get("entries"),
                                text=ctx.get("text"),
                                document_record=not row.get("producer_added"))
    except PolicyLineError as exc:
        verdict.update(action=on_hold, value=text,
                       reason=exc.errors.get(fact) or exc.message)
        return verdict
    new = _clean_text(clean.get(fact))
    if not new:
        return verdict
    verdict["value"] = new
    current = _clean_text(row.get(fact))
    if current:
        if _same_value(fact, current, new):
            verdict["action"] = SAME
            return verdict
        verdict["source_value"] = current
        if person == CLIENT_SOURCE:
            verdict.update(action=HOLD, reason=_HELD_MISMATCH)
            return verdict
        verdict["action"] = WRITE
        return verdict
    clash, why = _documents_say_otherwise(ctx, row, fact, new)
    if clash and person == CLIENT_SOURCE:
        verdict.update(action=HOLD, source_value=clash, reason=why)
        return verdict
    verdict["action"] = WRITE
    return verdict


def hold_entry(verdict: dict, value: Any, field_name: str, arq_id: Any = None) -> dict:
    """A held answer, in the shape `client_answer_review` lists ("Needs your
    decision"): the client's words, what the package states, and which policy."""
    return {"client_value": _clean_text(value)[:500],
            "source_value": verdict.get("source_value") or "(not stated)",
            "field_name": field_name,
            "arq_id": arq_id,
            "held_at": _now(),
            "label": verdict.get("label") or "",
            "reason": verdict.get("reason") or ""}


async def apply_policy_answers(session_id: str, answers: Iterable[Tuple[Any, Any]], *,
                               person: str = PRODUCER_SOURCE, arq_id: Any = None,
                               upd=None) -> dict:
    """THE DOOR for questionnaire answers about one policy: each (answer key,
    value) is judged against the package as it is now (`judge`), the ones to
    write go through `plan_change` (the table's own validation and store, the
    source recorded) and ONE `apply_post_generation` re-stamps every generated
    form - section headers, the 125 prior-carrier grid and question 4 - with
    the boxes labelled for whoever supplied the value. A client's held answers
    join the session's held list. Returns {"written", "unchanged", "held",
    "refused", "skipped", "forms_updated", "changes"}; never writes before
    forms exist."""
    report: dict = {"written": [], "unchanged": [], "held": {}, "refused": {}, "skipped": [],
                    "forms_updated": [], "changes": []}
    items = [(str(k), v) for k, v in (answers or []) if is_answer_key(k)]
    if not items:
        return report
    from repositories.session_repository import get_processing_session
    if upd is None:
        from repositories.session_repository import upd_processing_session as upd
    async with session_lock(session_id):
        session = await get_processing_session(session_id)
        ctx = answer_context(session)
        work = dict(session) if isinstance(session, dict) else {}
        work["facts"] = copy.deepcopy(work.get("facts") or {})
        store = read_store(work["facts"])
        own: set = set()
        for key, value in items:
            if ctx is None:
                verdict = {"action": HOLD if person == CLIENT_SOURCE else REFUSE,
                           "label": _ANSWER_LABEL.get(answer_fact(key) or "", ""),
                           "reason": _HELD_GONE, "source_value": ""}
            else:
                verdict = judge(ctx, key, value, person=person)
            act = verdict["action"]
            if act == WRITE:
                # A NAIC is its company's: every policy of that company still
                # lacking one takes it (`_naic_by_company` asked it once).
                targets = [verdict["edit_key"]]
                mine = answer_row(ctx, key) if ctx is not None else None
                if verdict["fact"] == "carrier_naic" and mine is not None:
                    targets += [r["edit_key"] for r in company_rows(ctx["rows"], mine)
                                if r is not mine and not _clean_text(r.get("carrier_naic"))]
                audit: List[dict] = []
                why = ""
                for edit_key in targets:
                    try:
                        store, rows_ = plan_change(work, "edit", edit_key=edit_key,
                                                   fields={verdict["fact"]: verdict["value"]},
                                                   user=person, source=person)
                    except (PolicyLineError, KeyError) as exc:
                        if edit_key == verdict["edit_key"]:
                            why = exc.message if isinstance(exc, PolicyLineError) else _HELD_GONE
                            break
                        continue                  # a sibling that cannot take it keeps its own
                    work["facts"][STORE_KEY] = store
                    audit += rows_
                if why:
                    if person == CLIENT_SOURCE:
                        report["held"][key] = hold_entry({**verdict, "reason": why}, value, key, arq_id)
                    else:
                        report["refused"][key] = why
                    continue
                if not audit:
                    report["unchanged"].append(key)
                    continue
                report["written"].append(key)
                own |= _value_keys(verdict["value"])
                for row in audit:
                    report["changes"].append({"field": key, "fact_key": str(row.get("field") or ""),
                                              "previous": row.get("previous") or None,
                                              "new": str(row.get("new") or "")})
            elif act == SAME:
                report["unchanged"].append(key)
            elif act == HOLD:
                report["held"][key] = hold_entry(verdict, value, key, arq_id)
            elif act == REFUSE:
                report["refused"][key] = verdict.get("reason") or _HELD_GONE
            else:
                report["skipped"].append(key)
        if report["written"]:
            out = await apply_post_generation(
                session, session_id, store, upd=upd, provenance=person,
                own_values=own if person == CLIENT_SOURCE else None)
            report["forms_updated"] = sorted(out.get("forms_updated") or [])
        if report["held"]:
            held = dict((session or {}).get("client_answer_conflicts") or {})
            held.update(report["held"])
            await upd(session_id, {"client_answer_conflicts": held,
                                   "facts": {"_client_answer_conflicts": held}})
        logger.info("policy_lines: questionnaire answers by policy (%s) - written %s, "
                    "unchanged %d, held %s, refused %s, skipped %d, forms %s", person,
                    report["written"][:6], len(report["unchanged"]), sorted(report["held"])[:6],
                    sorted(report["refused"])[:6], len(report["skipped"]),
                    report["forms_updated"][:8])
    return report
