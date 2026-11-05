"""Any ACORD form through ASG (3 Nov 2026) - read Accommodate800forms.md section 10 first.

The user searches ASG's forms list, picks a form, and Primble downloads that form from ASG's Download API at
generation, reads its boxes in memory and fills it exactly like its own 17 forms. Primble never keeps a library of
ASG forms: the package keeps its filled form plus a VALUES-ONLY copy (D-ASG-3), from which every later render
gets the clean form back in memory.

One module, one door each:
- `is_asg_form(form_id)`      - an ASG form id (in the search list, not one of our 17).
- `search(query)`             - the search list (text only; never calls ASG).
- `meta_for(form_id)`         - the form's metadata row, shaped like `forms_database/<id>.json`.
- `fetch_blank(meta)`         - THE ONLY network call: ASG's Download API (stub in tests; RAM copy per run).
- `schema_from_pdf(bytes)`    - the box list (key, type, ACORD's description), like `forms_schemas/*.json`.
- `values_only_copy` / `cleared_template` - the stored base and the clean form rebuilt from it.
- `template_source(record)`   - the template for any re-render of a generated ASG form.

ASG CALLS: only `fetch_blank`, and never while `ASG_FORMS_STUB_DIR` is set (the test suite). A person running
anything by hand must have the owner's yes for each call (memory `transcriber-calls-need-permission`).
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import threading
import time
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.normpath(os.path.join(_HERE, "..", "forms_catalog", "asg_forms_index.json"))
BASE_ROW_SUFFIX = "::asg_base"            # session_pdf_bytes row holding the values-only copy (D-ASG-3)
_ORIG_KEY = "/PrimbleBlankState"          # on a box the values-only copy wrote: its blank /V and /AS
SOURCE = "asg"
# On a generated ASG form's record (`generated_forms[id]`):
NEW_BASE_KEY = "asg_base_pdf"             # a values-only copy made by THIS run - saved as the `::asg_base` row
STORED_BASE_KEY = "_asg_base_stored"      # the copy read back from the database - never written again
ORDER_KEY = "asg_box_order"               # the form's boxes in printed order (a JSON list keeps its order;
                                          # the stored `schema` object comes back key-sorted from JSONB)

_FORM_ID_RE = re.compile(r"^ACORD_(\d{1,4})(?:_([A-Z]{2}))?(?:_([A-Z]{1,4}))?$")
_NON_PC_TITLE_RE = re.compile(r"\b(life(?!\s+circumstances)|annuit\w*|health|disability income|long[- ]term care|beneficiar\w*|"
                              r"sickness|medical examiner|medical history|1035)\b", re.I)
# ACORD's own numbering puts Life, Annuity & Health forms at 650-799 and 950-999 (life applications, examiner reports,
# replacement notices, group-benefit proposals, annuity disclosures - checked form by form on ASG's list, 4 Nov 2026).
_LIFE_HEALTH_NUMBERS = ((650, 799), (950, 999))
_RAM_TTL_SECONDS = 60 * 60          # one generation run, long packages included
_RAM_MAX_BYTES = 48 * 1024 * 1024   # bounded by SIZE (review round 3: a count let other users push a run's
                                    # forms out between its pre-download and its fill)
_FAIL_TTL = {"not_available": 6 * 60 * 60, "asg_error": 3 * 60, "auth": 3 * 60,
             "bad_file": 3 * 60,   # remembered failures (6 h only for ASG's own "no fillable version")
             "wrong_form": 6 * 60 * 60}   # ASG sent another form for this request - the same answer for hours
PREFETCH_DEADLINE_SECONDS = 120.0   # the whole pre-download of one generate request (one wave of 8 cold
                                    # downloads ~22 s each, with room for other users' downloads - round 4)
NOT_SET_UP = ("Adding ACORD forms from ACORD Solutions is not set up on this server yet. "
              "Please contact support.")
_HTTP_TIMEOUT = 60.0
_CONNECT_TIMEOUT = 10.0                   # ASG not answering at all fails fast (review round 2)
_DOWNLOAD_BUDGET_SECONDS = 45.0           # no new attempt starts after this - a hung ASG frees the thread (round 5)

# What a user is told (review round 2: never "your answers are saved" when an edit was refused).
CANNOT_SHOW = ("This form cannot be shown right now - its stored copy could not be read. "
               "Please contact support.")
EDIT_NOT_SAVED = ("Your edit was not saved - this form's stored copy could not be read. "
                  "Please contact support.")
NOT_SIGNED = ("The form was not signed - its stored copy could not be read. Please contact support.")


class AsgFormUnavailable(Exception):
    """ASG could not give this form (not offered, no fillable version, ASG down, no credentials)."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


# ── switch, allow-list, cap (D-ASG-7) ─────────────────────────────────────────

def _flag(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in ("1", "true", "yes", "on")


def feature_on() -> bool:
    return _flag("ASG_FORMS", "0")


def _uat_in_production() -> bool:
    env = (os.getenv("TRANSCRIBER_ENV") or "uat").strip().lower()
    app_env = (os.getenv("ENVIRONMENT") or "development").strip().lower()
    return env != "prod" and app_env == "production"


def ready() -> bool:
    """The download can work at all: the stub (tests) or credentials, and not UAT keys refused in production."""
    if _stub_dir():
        return True
    try:
        return _network_allowed(_config())[0]
    except Exception:                                        # noqa: BLE001
        return False


def enabled_for(user: Optional[dict]) -> bool:
    """ASG forms are on, can work, and this user may use them (`ASG_FORMS_ALLOWED_EMAILS`).

    FAIL CLOSED (final review, 3 Nov 2026): on a production server still using ASG's UAT (test) credentials,
    every download is a "Sample" form - so there the allow-list is REQUIRED, and an empty one lets nobody in.
    Open to every user only with PROD credentials (or off production)."""
    if not feature_on() or not ready():
        return False
    allowed = {e.strip().lower() for e in (os.getenv("ASG_FORMS_ALLOWED_EMAILS") or "").split(",") if e.strip()}
    if not allowed:
        return not _uat_in_production()
    email = str((user or {}).get("email") or "").strip().lower()
    return bool(email) and email in allowed


def max_per_package() -> int:
    """How many ACORD Solutions forms one package may hold. No separate limit by default (owner, 4 Nov 2026: "do not
    cap it at 8") - the package's 15-form total is the only cap, ours and ASG's mixed any way. `ASG_FORMS_MAX` can
    still set a lower ASG-only limit."""
    total = max_forms_per_package()
    try:
        own = int(os.getenv("ASG_FORMS_MAX", "0") or 0)
    except ValueError:
        own = 0
    return min(own, total) if own > 0 else total


# ── the search list (D-ASG-2) ─────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _index() -> Dict[str, dict]:
    try:
        with open(INDEX_PATH) as f:
            data = json.load(f)
    except Exception as ex:                                  # noqa: BLE001
        logger.warning("asg_forms: search list unavailable (%s): %s", INDEX_PATH, ex)
        return {}
    return {str(e["form_id"]): e for e in data.get("forms") or [] if isinstance(e, dict) and e.get("form_id")}


@lru_cache(maxsize=1)
def our_form_ids() -> frozenset:
    """Primble's own forms (`forms_database/forms_index.json`) - they always stay ours."""
    try:
        from services.form_service import load_index
        idx = load_index() or {}
        forms = idx.get("forms") or []
        ids = {str(f.get("form_id") if isinstance(f, dict) else f) for f in forms}
        if ids:
            return frozenset(ids)
    except Exception as ex:                                  # noqa: BLE001
        logger.warning("asg_forms: our form list unavailable: %s", ex)
    from config.settings import FORMS_DB_DIR
    return frozenset(n[:-5] for n in os.listdir(FORMS_DB_DIR)
                     if n.startswith("ACORD_") and n.endswith(".json"))


def is_asg_form(form_id: Any) -> bool:
    fid = str(form_id or "").strip()
    return bool(_FORM_ID_RE.match(fid)) and fid in _index() and fid not in our_form_ids()


def asg_form_ids(form_ids: Any) -> List[str]:
    return [str(f) for f in (form_ids or []) if is_asg_form(f)]


def clean_form_ids(form_ids: Any) -> List[str]:
    """Requested form ids in ONE spelling: trimmed, empty ones dropped, each once, order kept - so a padded or
    repeated id can neither slip past the cap nor be generated twice (review 3 Nov 2026)."""
    return list(dict.fromkeys(s for s in (str(f or "").strip() for f in (form_ids or [])) if s))


def asg_count_in_package(requested: Any, generated: Any) -> int:
    """ASG forms the package would hold: those requested plus those it already has."""
    return len(set(asg_form_ids(requested)) | set(asg_form_ids(list(generated or {}))))


def is_asg_meta(meta: Any) -> bool:
    return isinstance(meta, dict) and meta.get("source") == SOURCE


def is_asg_record(record: Any) -> bool:
    """A generated form (`generated_forms[id]`) made from an ASG form."""
    return isinstance(record, dict) and is_asg_meta(record.get("form"))


_CERTIFICATE_TITLE_RE = re.compile(
    r"\b(certificate|evidence of|insurance identification|identification card|id card|proof of insurance|"
    r"insurance card|information card|coverage card|security verification|verification form|"
    r"financial responsibility)\b", re.I)   # + Oklahoma's ID card, financial-responsibility forms (review C)
_NOT_CERTIFICATE_RE = re.compile(r"\bfloodproofing\b", re.I)   # certifies a BUILDING, not coverage (307 / 308)   # + the state cards (review, 4 Nov 2026: 50 TX ...)


def is_certificate_form(form_id: Any) -> bool:
    """An ASG form that DOCUMENTS an existing policy (a certificate, an evidence of insurance, an ID card) - the
    family of our ACORD 25 / 28: it prints the current policy's term, never the proposed one, and never carries
    the package's record (final review, 3 Nov 2026). Decided from the form's title in ASG's list."""
    fid = str(form_id or "")
    title = str(_index()[fid].get("title") or "") if is_asg_form(fid) else ""
    return bool(title) and bool(_CERTIFICATE_TITLE_RE.search(title)) and not _NOT_CERTIFICATE_RE.search(title)


def _label(entry: dict) -> str:
    parts = [f"ACORD {entry['number']}", entry.get("state") or "", entry.get("suffix") or ""]
    return " ".join(p for p in parts if p)


def _is_pc(entry: dict) -> bool:
    """A Property & Casualty form. Brent, 4 Nov 2026: "Please show only the P&C forms, not the others." """
    try:
        n = int(str(entry.get("number") or "0"))
    except ValueError:
        n = 0
    if any(lo <= n <= hi for lo, hi in _LIFE_HEALTH_NUMBERS):
        return False
    return not _NON_PC_TITLE_RE.search(str(entry.get("title") or ""))


def is_pc_form(form_id: Any) -> bool:
    """An ASG form id that may be offered and generated: a P&C form on the list. Our own 17 always are."""
    e = _index().get(str(form_id or "").strip())
    return bool(e) and _is_pc(e)


def max_forms_per_package() -> int:
    """Every form in one package - ours and ACORD Solutions' together (Brent, 4 Nov 2026: 15; more = an account
    upgrade). `PACKAGE_FORMS_MAX` changes it."""
    try:
        return max(1, int(os.getenv("PACKAGE_FORMS_MAX", "15") or 15))
    except ValueError:
        return 15


def package_form_count(requested: Any, generated: Any) -> int:
    """How many forms a package holds once `requested` is added: every distinct form printed, ours and ASG's
    together - an umbrella layer's own copy ("ACORD_131__excess") is a form of its own, as the screen counts it
    (review pass 4)."""
    ids = set(clean_form_ids(requested))
    ids |= set(clean_form_ids(list(generated.keys()) if isinstance(generated, dict) else (generated or [])))
    return len(ids)


PACKAGE_FULL_MESSAGE = ("A package can hold up to {max} forms. Remove some, or contact support@primble.com to upgrade "
                        "your account for more forms in one package.")


_STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
    "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC", "puerto rico": "PR",
}
# Insurance shorthand -> the words ACORD's own titles use (search sweep, owner's live test 3 Nov 2026).
_SEARCH_SYNONYMS = {"coi": "certificate", "eoi": "evidence", "wc": "workers compensation", "gl": "general liability",
                    "cgl": "general liability", "bop": "business owners|businessowners",
                    "businessowners": "business owners|businessowners", "tria": "terrorism",
                    "boiler": "boiler|equipment breakdown", "epli": "employment practices",
                    "epl": "employment practices", "dno": "directors officers", "do": "directors officers",
                    "eo": "errors omissions", "pc": "property casualty", "trucking": "truck",
                    "id": "identification|insurance card", "ins": "insurance",
                    "workmans": "workers", "workman": "workers", "workmens": "workers", "workmen": "workers"}
# Shorthand written with "&" (or "and") between single letters is one word, as titles print it ("D&O", "E&O") -
# read before punctuation is dropped; `_SEARCH_SYNONYMS` then also lets it match the spelled-out words.
_AMPERSAND_PHRASES = ((re.compile(r"\bd\s*(?:&|and|n)\s*o\b"), " do "),
                      (re.compile(r"\be\s*(?:&|and|n)\s*o\b"), " eo "),
                      (re.compile(r"\bp\s*(?:&|and)\s*c\b"), " pc "))
_TITLE_AMPERSAND = re.compile(r"\b([a-z])\s*&\s*([a-z])\b")
_IGNORED_WORDS = frozenset({"acord", "accord", "acords", "accords", "form", "forms", "no", "number"})
# Small words carry no meaning in a title search and must not block one ("auto for texas", "directors and officers"
# against a title that prints "&"). Typed ALONE, "in" / "or" are still the states.
_STOP_WORDS = frozenset({"a", "an", "and", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to", "with"})
_STATE_CODES = frozenset(_STATE_NAMES.values()) | {"VI", "GU", "AS", "MP"}
_CODE_NAME_WORDS = {code: name.split() for name, code in _STATE_NAMES.items()}
_STATE_ALIASES = {"washington dc": "DC", "washington d c": "DC", "d c": "DC"}   # typed names no title spells
_CODE_PENALTY_WORD_READING = 5          # "ny auto" read as the WORD "ny" ranks below "ny" read as New York
_NOT_OURS = 8                           # our 17 come first: more than a state (2) + a variant (4) penalty


def _effective_codes(codes: List[str]) -> List[str]:
    """Two-letter codes that filter: a stop word that is also a code ("in", "or", "me") filters only when it is the
    ONLY code typed - "137 in tx" is Texas, never Indiana (second review, 3 Nov 2026)."""
    real = [c for c in codes if c.lower() not in _STOP_WORDS]
    return real or list(codes)


def _title_names_state(title: str, code: str) -> bool:
    """The title names the state as a phrase - and not as part of a longer state's name ("Virginia" in "West
    Virginia", second review)."""
    name = " ".join(_CODE_NAME_WORDS.get(code, []))
    if not name:
        return False
    low = " ".join(str(title or "").lower().split())
    for other in _STATE_NAMES:
        if other != name and name in other:
            low = re.sub(rf"\b{re.escape(other)}\b", " ", low)
    for m in re.finditer(rf"\b{re.escape(name)}\b", low):
        before = low[max(0, m.start() - 20):m.start()]
        if not re.search(r"\b(?:except|excluding|excludes|other than|outside|not)\s*(?:for\s+|in\s+)?\W*$", before):
            return True                     # "(except California)" names the state it is NOT for (review pass 3)
    return False


@lru_cache(maxsize=4096)
def _title_tokens(title: str) -> Tuple[str, ...]:
    """A title's words, as the search compares them (letters and digits; every other mark separates)."""
    low = title.lower()
    return tuple(re.findall(r"[a-z0-9]+", low)) + tuple(a + b for a, b in _TITLE_AMPERSAND.findall(low))


def _stem(word: str) -> str:
    """A plural typed is read as its stem, so it still prefix-matches the singular title ("binders", "claims",
    "certificates", "policies")."""
    if len(word) >= 5 and word.endswith("ies"):
        return word[:-3]
    if len(word) >= 4 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _parse_query(query: str) -> Tuple[Optional[str], List[str], List[str], List[str]]:
    """(form number, states typed by NAME, two-letter state codes, other words) from what a person types:
    "ACORD 137 Texas", "137tx", "137-TX", "form #0027", "coi", "workers' compensation", "d&o", "ny auto",
    "ACORD 25 (2016/03)". Every mark that is not a letter or a digit separates words, as in the titles."""
    q = " ".join(str(query or "").lower().split())
    for pattern, words in _AMPERSAND_PHRASES:
        q = pattern.sub(words, q)
    q = re.sub(r"(\d)['’]?s\b", r"\1", q)       # "25s", "25's": a plural - only "25 s" / "25-s" names the S form
    q = q.replace("'", "").replace("’", "")          # "workers' compensation", "employer's"
    q = " ".join(re.sub(r"[.,;:/()\[\]-]+", " ", q).split())    # "washington, d.c." -> "washington d c"
    named: List[str] = []
    for name, code in sorted(list(_STATE_NAMES.items()) + list(_STATE_ALIASES.items()), key=lambda kv: -len(kv[0])):
        for spelled in dict.fromkeys((name, name.replace(" ", ""))):     # "new york", "newyork"
            if re.search(rf"\b{spelled}\b", q):
                q = re.sub(rf"\b{spelled}\b", " ", q)
                if code not in named:
                    named.append(code)
    q = re.sub(r"[^a-z0-9]+", " ", q)
    q = re.sub(r"(\d)([a-z])", r"\1 \2", q)              # "137tx" -> "137 tx"
    q = re.sub(r"([a-z])(\d)", r"\1 \2", q)              # "acord25" -> "acord 25"
    number: Optional[str] = None
    codes: List[str] = []
    rest: List[str] = []
    after_year = False
    for w in q.split():
        if w in _IGNORED_WORDS:
            continue
        if w.isdigit():
            if number is None:
                number = str(int(w))                      # "0027" -> "27"
            elif len(w) == 4 and w[:2] in ("19", "20"):
                after_year = True                         # an edition typed after the number: "25 2016/03"
            elif not (after_year and len(w) <= 2):        # ... and its month
                rest.append(w)
            continue
        if len(w) == 2 and w.upper() in _STATE_CODES:
            if w.upper() not in codes:
                codes.append(w.upper())
            continue
        rest.append(w)                                    # a shorthand stays itself: see `_term_in_title`
    return number, named, codes, rest


def _split_codes(named: List[str], codes: List[str]) -> Tuple[List[str], List[str]]:
    """(codes that are states, codes that are words). A code is a WORD when it is everyday shorthand ("id" card) or
    a small word ("in", "or") and a real state is typed beside it - by name or by another code; a code that repeats a
    state typed by name ("texas tx") is dropped (review pass 2, 3 Nov 2026)."""
    real = [c for c in codes if c.lower() not in _STOP_WORDS and c.lower() not in _SEARCH_SYNONYMS]
    shorthand = [c for c in codes if c.lower() in _SEARCH_SYNONYMS]
    if named or real:
        return [c for c in real if c not in named], [c for c in shorthand if c not in named]
    return list(codes), []


def _search_readings(number: Optional[str], named: List[str], codes: List[str],
                     words: List[str]) -> List[Tuple[Optional[set], List[str], bool, int]]:
    """The ways a query can be read: (states it filters by or None, the words a title must hold, by-name).
    - A state typed by its full NAME is never ambiguous: it filters (and a form whose title names it matches);
      two-letter words beside it are words ("auto in texas").
    - A two-letter state code alone or beside a number filters ("tx", "137 tx").
    - A two-letter code beside other words is EITHER a state or a word ("ny auto" vs "id card"): both readings."""
    words = [w for w in words if w not in _STOP_WORDS]
    # A code read as a WORD matches a title word exactly ("=al"), never as a beginning - "al" is not "Alaska", "co"
    # is not "commercial" (second review, 3 Nov 2026). A code that is also shorthand ("id") keeps its synonym.
    code_words = [(c.lower() if c.lower() in _SEARCH_SYNONYMS else "=" + c.lower())
                  for c in codes if c.lower() not in _STOP_WORDS]
    states, as_words = _split_codes(named, codes)
    shorthand_words = [c.lower() for c in as_words]
    if named:
        # A name is never ambiguous; another state's code beside it adds that state ("texas ca").
        return [(set(named) | set(states), shorthand_words + words, True, 0)]
    if not codes:
        return [(None, words, False, 0)]
    filters = set(_effective_codes(states))
    if not words and not shorthand_words:
        return [(filters, [], False, 0)]
    if as_words:
        # A real state code is typed beside the shorthand ("tx id card"): the state filters, "id" is the word.
        return [(filters, shorthand_words + words, False, 0),
                (None, code_words + words, False, _CODE_PENALTY_WORD_READING)]
    if not code_words:
        # Only a small word that is also a state. Beside a word or two ("wc in", "or auto", "130 in") it is the
        # state - read as a word it would constrain nothing and list every state's forms (review pass 3); no state
        # version -> the general forms, with a note. Inside a longer phrase ("partnership or sole proprietorship")
        # it is the word.
        if len(words) >= 3:
            return [(None, words, False, 0)]
        return [(filters, words, False, 0)]
    # A code that is also everyday shorthand ("id" card) is first read as the word; any other code ("ny" auto)
    # first as the state.
    word_first = any(c.lower() in _SEARCH_SYNONYMS for c in codes if c.lower() not in _STOP_WORDS)
    state_pen, word_pen = ((_CODE_PENALTY_WORD_READING, 0) if word_first else (0, _CODE_PENALTY_WORD_READING))
    return [(filters, words, False, state_pen), (None, code_words + words, False, word_pen)]


def _phrase_in(words: List[str], title_words: Tuple[str, ...]) -> bool:
    """The words in that ORDER, side by side (small words between them ignored): "insurance card" is not "Credit
    Card Payment ... Insurance" (review C, 4 Nov 2026); "directors officers" is "Directors and Officers"."""
    tokens = [t for t in title_words if t not in _STOP_WORDS]
    stems = [_stem(w) for w in words]
    if not stems:
        return False
    for i, t in enumerate(tokens):
        if not t.startswith(stems[0]):
            continue
        at, ok = i, True
        for st in stems[1:]:          # each next word within one word of the last ("Employment Related Practices")
            nxt = next((k for k in (at + 1, at + 2) if k < len(tokens) and tokens[k].startswith(st)), None)
            if nxt is None:
                ok = False
                break
            at = nxt
        if ok:
            return True
    return False


def _term_in_title(word: str, title_words: Tuple[str, ...], suffix: str) -> bool:
    """A typed word is in a title when the title holds it as a word's beginning (plural or not), when it names the
    form's variant ("ins"), or - for a shorthand - when the title holds the shorthand itself as a word ("K-WC",
    "E&O") or every word it stands for ("wc" -> workers compensation). A shorthand matches itself exactly, never as
    a beginning ("gl" is not "glass")."""
    if word.startswith("="):                           # a two-letter code read as a word: exactly that word
        return word[1:] in title_words
    if suffix and word == suffix.lower():
        return True
    spelled = _SEARCH_SYNONYMS.get(word)
    if spelled:                                        # "a|b c": either spelling (ACORD's state cards say both)
        return word in title_words or any(_phrase_in(alt.split(), title_words) for alt in spelled.split("|"))
    stem = _stem(word)
    return any(t.startswith(stem) for t in title_words)


def _matching_forms(number: Optional[str], readings: List[Tuple[Optional[set], List[str], bool, int]],
                    ours: set, closest: bool = False) -> Dict[str, tuple]:
    """Every list entry one of the readings matches, with its rank (lower is better). `closest`: an entry needs
    only SOME of the words, and the more it holds the better it ranks (the last widening of `search_full`)."""
    best: Dict[str, tuple] = {}
    for fid, e in _index().items():
        if not _is_pc(e):
            continue                          # P&C only (Brent, 4 Nov 2026)
        num, st, sx = e["number"], e.get("state") or "", e.get("suffix") or ""
        # Searched: the title, its older longer titles (a dropped subtitle - "... Notice of Terrorism Insurance
        # Coverage"), and for our own forms the names Primble shows them by ("Commercial Property Section") - review C.
        title_words = _title_tokens(" ".join([str(e.get("title") or "")] + list(e.get("aka") or [])
                                              + ([_our_names().get(fid, "")] if fid in ours else [])))
        if number is not None:
            if num == number:
                rank = 0
            elif num.startswith(number):
                rank = 2
            else:
                continue
        else:
            rank = 1
        for states, words, by_name, penalty in readings:
            # A form matched only by its TITLE naming the state must be a form for no state - never another state's
            # version whose title happens to name this one (ASG's 63 OK is titled "Ohio", review pass 4).
            if states is not None and st not in states and not (
                    by_name and not st and any(_title_names_state(e.get("title") or "", s) for s in states)):
                continue
            held = sum(1 for w in words if _term_in_title(w, title_words, sx))
            if held < len(words) and not (closest and held):
                continue
            if closest and any(w.startswith("=") and not _term_in_title(w, title_words, sx) for w in words):
                continue        # "tx" read as a word must be printed - never every state's form (review pass 2)
            names_variant = bool(sx) and sx.lower() in words
            # A variant code beside a form NUMBER ("25 ins") asks for that variant: it outranks everything. Without
            # a number "ins" is the word insurance, and the variant takes no lead (second review, 3 Nov 2026).
            variant = (-(_NOT_OURS + 2) if number is not None else 0) if names_variant else (4 if sx else 0)
            # A form with no state that matched only because its TITLE names the state ranks after that state's own
            # versions ("877 california": ACORD 877 CA before ACORD 877 - review pass 3).
            title_only = 5 if (by_name and states is not None and st not in states) else 0
            # the typed words side by side in the title outrank the same words scattered ("insurance card" is not
            # "... Insurance Program - Credit Card Payment Form" - review C)
            phrase = -1 if len(words) > 1 and held == len(words) and _phrase_in(
                [w for w in words if not w.startswith("=")], title_words) else 0
            score = (rank * 10 + (0 if fid in ours else _NOT_OURS) + (0 if not st else 2) + title_only
                     + variant + (0 if _is_pc(e) else 100) + (40 if e.get("region") == "AU" else 0) + phrase
                     + (len(words) - held) * 1000 + penalty)
            if fid not in best or score < best[fid][0]:
                best[fid] = (score, int(num), st, sx, fid, e)
    return best


_SUBJECT_STOP = frozenset({"ACORD", "FORM", "AND", "OF", "THE", "FOR", "TO", "IN", "ON", "OR", "SECTION", "INSURANCE"})


@lru_cache(maxsize=64)
def _our_form_name(form_id: str) -> str:
    try:
        from services.form_service import load_form_detail
        return str((load_form_detail(form_id) or {}).get("form_name") or "") if form_id in our_form_ids() else ""
    except Exception:                                        # noqa: BLE001
        return ""


def same_subject_as_ours(form_id: Any) -> bool:
    """An ASG form that shares its NUMBER with one of our 17 is about the same subject when its title shares a word
    with our form's name (137 TX "Commercial Auto Coverages" ~ our 137). ASG's 186 SC is a South Carolina auto UM
    form, not our 186 Contractors Supplement - it must not inherit our 186's scoring lines (review C, 4 Nov 2026).
    True for anything that is not an ASG form."""
    fid = str(form_id or "")
    if not is_asg_form(fid):
        return True
    e = _index().get(fid) or {}
    ours = _our_form_name(f"ACORD_{e.get('number')}")      # the form's own name - not the search text
    if not ours:
        return True
    states = {w for name in _STATE_NAMES for w in name.upper().split()}
    words = lambda t: {w for w in re.findall(r"[A-Z]+", str(t).upper())   # noqa: E731
                       if len(w) > 2 and w not in _SUBJECT_STOP and w not in states}
    return bool(words(e.get("title")) & words(ours))


@lru_cache(maxsize=1)
def _our_names() -> Dict[str, str]:
    """Our 17 forms' own names and descriptions (`forms_database/<id>.json`) - what the recommended-forms list calls
    them, so a search by that name finds them ("commercial auto", "assigned risk" - review C, 4 Nov 2026)."""
    out: Dict[str, str] = {}
    try:
        from services.form_service import load_form_detail
        for fid in our_form_ids():
            d = load_form_detail(fid) or {}
            # all 17 are commercial-lines forms: "commercial umbrella" finds 131, "commercial auto" finds 127
            out[fid] = (" ".join(str(d.get(k) or "") for k in ("form_name", "description"))[:400] + " commercial")
    except Exception as ex:                                  # noqa: BLE001
        logger.warning("asg_forms: our form names unavailable: %s", ex)
    return out


def _state_display(code: str) -> str:
    name = " ".join(_CODE_NAME_WORDS.get(code, []))
    return name.title().replace(" Of ", " of ") if name else code


def search_with_total(query: str, limit: int = 25) -> Tuple[List[dict], int]:
    """(the first `limit` matches, how many matched) - see `search_full`."""
    rows, total, _note = search_full(query, limit)
    return rows, total


def search_full(query: str, limit: int = 25) -> Tuple[List[dict], int, str]:
    """(the first `limit` matches, how many matched). Our own 17 first, then the plain form before its state and
    other variants (a variant the person names - "137 tx ins" - comes first), business insurance (P&C) before
    Life / Health / Annuity. Text only - never calls ASG."""
    number, named, codes, raw_words = _parse_query(query)
    readings = _search_readings(number, named, codes, raw_words)
    if number is None and not any(states or words for states, words, _by_name, _p in readings):
        return [], 0, ""
    ours = our_form_ids()
    extra_numbers = [w for w in raw_words if w.isdigit()] if number is not None else []
    if extra_numbers and not [w for w in raw_words if not w.isdigit() and w not in _STOP_WORDS]:
        # Only form numbers typed ("125 126"): each number's forms, in the order typed (second review, 3 Nov 2026).
        # "25 or 28": a small word between numbers is the word, not Oregon (review pass 3).
        codes = [c for c in codes if c.lower() not in _STOP_WORDS]
        readings_n = _search_readings(None, named, codes, [])
        best = {}
        note = ""
        for n in [number] + [str(int(w)) for w in extra_numbers]:
            found = _matching_forms(n, readings_n if (named or codes) else [(None, [], False, 0)], ours)
            if (named or codes) and not any(v[1] == int(n) for v in found.values()):
                general, general_note = _general_versions([n], named, codes, ours)
                found.update(general)
                note = note or general_note
            for fid, v in found.items():
                if fid not in best or v[0] < best[fid][0]:
                    best[fid] = v
        if best:
            scored = sorted(best.values(), key=lambda x: x[:5])
            return _rows(scored, ours, limit), len(scored), note
    best = _matching_forms(number, readings, ours)
    note = ""
    typed_states = _state_filter(named, codes) if (named or codes) else set()
    if (typed_states and number is not None and not raw_words
            and not any(v[1] == int(number) for v in best.values())):
        # "28 ny": no New York 28 - ACORD 28 itself, and the screen says so; never only a longer number's NY form
        # (ACORD 283 NY) that hides the form typed (review pass 3).
        general, general_note = _general_versions([number], named, codes, ours)
        if general:
            best = {**best, **general}
            note = general_note
    if not best and number is not None and (raw_words or named or codes):
        # The number is part of a TITLE, not the form's own number: "ho 4", or a whole title that quotes another
        # form ("... Homeowners Application ACORD 60 MA") - search sweep, 3 Nov 2026. A typed state still filters.
        best = _matching_forms(None, _search_readings(None, named, codes, raw_words + [number]), ours)
        if typed_states:
            best = {fid: v for fid, v in best.items() if v[2] in typed_states}
    if not best and number is None and (named or codes) and any(w not in _STOP_WORDS for w in raw_words):
        # No version of that form for the state ("gl ca", "notice of cancellation georgia"): the GENERAL forms
        # (no state), and the screen says so - never another state's version.
        found = _matching_forms(None, [(None, [w for w in raw_words if w not in _STOP_WORDS], False, 0)], ours)
        best = {fid: v for fid, v in found.items() if not v[2]}
        if best:
            states = " or ".join(dict.fromkeys(_state_display(c) for c in (named or sorted(_state_filter(named, codes)))))
            note = f"No {states} version found - showing the general forms."
    if not best and sum(1 for w in raw_words if w not in _STOP_WORDS) + len(named) + len(codes) >= 2:
        # Nothing holds EVERY word ("texas auto id card" - the Texas card's title says "TEXAS LIABILITY INSURANCE
        # CARD"): the forms holding the most of them, and the screen says so. Exact searches never come here.
        best = _matching_forms(number, readings, ours, closest=True)
        if best:
            note = "No form matches every word - showing the closest matches."
    if not best and number is not None and (raw_words or named or codes):
        # A form number plus words no title holds ("137 xx", "acord 25 zzz"): that number's forms - only the typed
        # state's ("137 tx zzz"), else its general forms, never another state's (review pass 2, 3 Nov 2026).
        states = _state_filter(named, codes)
        if states:
            best = {fid: v for fid, v in _matching_forms(number, [(None, [], False, 0)], ours).items()
                    if v[2] in states}
            if best:
                note = "No form matches every word - showing the closest matches."
            else:
                best, note = _general_versions([number], named, codes, ours)
        else:
            best = _matching_forms(number, [(None, [], False, 0)], ours)
            if best:
                note = "No form matches every word - showing the closest matches."
    scored = sorted(best.values(), key=lambda x: x[:5])
    return _rows(scored, ours, limit), len(scored), note


def _state_filter(named: List[str], codes: List[str]) -> set:
    states, _words = _split_codes(named, codes)
    return set(named) | set(_effective_codes(states))


def _general_versions(numbers: List[str], named: List[str], codes: List[str], ours: set) -> Tuple[dict, str]:
    """No version of these numbers for the typed state ("125 tx"): their general forms (no state), and the note
    saying so - never another state's version."""
    best: dict = {}
    for n in numbers:
        for fid, v in _matching_forms(n, [(None, [], False, 0)], ours).items():
            if not v[2] and (fid not in best or v[0] < best[fid][0]):
                best[fid] = v
    if not best:
        return {}, ""
    states = " or ".join(dict.fromkeys(_state_display(c) for c in sorted(_state_filter(named, codes))))
    return best, f"No {states} version found - showing the general forms."


def _rows(scored: List[tuple], ours: set, limit: int) -> List[dict]:
    out = []
    for _r, _n, _s, _x, fid, e in scored[: max(1, int(limit))]:
        out.append({
            "form_id": fid,
            "number": e["number"],
            "state": e.get("state") or "",
            "variant": e.get("suffix") or "",
            "title": e.get("title") or "",
            "label": _label(e),
            "form_name": f"{_label(e)} - {e.get('title') or ''}".strip(" -"),
            "listed_edition": e.get("edition") or "",
            "ours": fid in ours,
            "source": "primble" if fid in ours else SOURCE,
            "pc": _is_pc(e),
        })
    return out


def search(query: str, limit: int = 25) -> List[dict]:
    return search_with_total(query, limit)[0]


def meta_for(form_id: Any) -> Optional[dict]:
    """The metadata row an ASG form is generated from - shaped like `forms_database/<id>.json`,
    with no template file: the template comes from ASG (or the package's own base copy)."""
    fid = str(form_id or "").strip()
    if not is_asg_form(fid):
        return None
    e = _index()[fid]
    return {
        "form_id": fid,
        "form_name": f"{_label(e)} - {e.get('title') or ''}".strip(" -"),
        "form_type": "asg",
        "description": e.get("title") or "",
        "template_file": "",
        "source": SOURCE,
        "asg_number": e["number"],
        "asg_state": e.get("state") or "",
        "asg_suffix": e.get("suffix") or "",
        "listed_edition": e.get("edition") or "",
        "ask_edition": bool(e.get("ask_edition")),
        # exactly what ASG's own portal sends for this form's row (the list builder records it - 4 Nov 2026)
        "asg_request": dict(e.get("request") or {}),
        # no other fillable row of this number has this edition (the builder counts them) - only then can an
        # unprinted state / ASG code be proven by the edition alone (review A, 4 Nov 2026)
        "asg_unique_edition": bool(e.get("unique_edition")),
        # editions of the OTHER form of this number whose footer prints no code either (plain <-> INS)
        "asg_twin_editions": list(e.get("twin_editions") or []),
    }


# ── the download (D-ASG-4, D-ASG-8, D-ASG-9) ─────────────────────────────────

_ram: Dict[tuple, tuple] = {}
_ram_lock = threading.Lock()
_token: Dict[str, Any] = {"value": "", "expiry": 0.0, "bearer": None, "failed_until": 0.0,
                          "failed_reason": "asg_error", "failed_message": ""}
_TOKEN_FAILURE_SECONDS = 60.0     # a sign-in that just failed is not retried by every waiting thread (round 6)
_token_lock = threading.Lock()


def _ram_key(meta: dict, edition: Optional[str]) -> tuple:
    return (meta.get("asg_number"), meta.get("asg_state") or "", meta.get("asg_suffix") or "", edition or "latest")


_failed: Dict[tuple, tuple] = {}            # key -> (monotonic time, reason, message)


def _ram_get(key: tuple) -> Optional[tuple]:
    with _ram_lock:
        hit = _ram.get(key)
        if hit and time.monotonic() - hit[0] < _RAM_TTL_SECONDS:
            _ram[key] = _ram.pop(key)               # most recently used last
            return hit
        _ram.pop(key, None)
        return None


def _ram_put(keys: List[tuple], value: tuple) -> None:
    """One download under one or more keys ("latest" and its edition) - its bytes counted ONCE; the least
    recently used downloads go first when the total passes `_RAM_MAX_BYTES`."""
    with _ram_lock:
        for k in keys:
            _ram.pop(k, None)
            _ram[k] = value
        seen, total = set(), 0
        for v in _ram.values():
            if id(v[1]) not in seen:
                seen.add(id(v[1]))
                total += len(v[1])
        while _ram and total > _RAM_MAX_BYTES:
            oldest_key = next(iter(_ram))
            gone = _ram.pop(oldest_key)
            if all(v[1] is not gone[1] for v in _ram.values()):
                total -= len(gone[1])


def _failure_get(key: tuple) -> Optional[tuple]:
    with _ram_lock:
        hit = _failed.get(key)
        if hit and time.monotonic() - hit[0] < _FAIL_TTL.get(hit[1], 0):
            return hit
        _failed.pop(key, None)
        return None


def _failure_put(key: tuple, reason: str, message: str) -> None:
    if reason in _FAIL_TTL:
        with _ram_lock:
            _failed[key] = (time.monotonic(), reason, message)


# ── forms ASG refused: remembered for weeks, shared by every server (owner, 4 Nov 2026) ─────────────────────
# A form ASG answered with ANOTHER form ("wrong_form") or with no fillable version ("not_available") is not asked for
# again: users would press Generate again and again and spend our ASG allowance on the same refusal. The memory lives
# in Redis (every worker, survives restarts) for ASG_REFUSED_DAYS (30) and in this process as a fallback. Passing
# problems (ASG busy, a timeout) are NOT kept here - they clear in minutes as before.
REFUSED_REASONS = ("wrong_form", "not_available")
UNAVAILABLE_TEXT = "Not available from ACORD Solutions - choose another form."
# "v2" (4 Nov 2026): the request now names each form's own row and the footer check accepts a variant that prints no
# code (ASG's INS forms) - refusals remembered under the old rules are not carried over; each form gets one fresh try.
_REFUSED_PREFIX = "asg:refused:v4:"     # v4 (proof round 2, 4 Nov 2026): BUMP whenever `identity_check` changes, so a
                                        # refusal made by an older check never outlives the fix
_refused_ram: Dict[str, tuple] = {}          # refused request (`_refused_key`) -> (expires at, reason, message)
_refused_redis: Dict[str, Any] = {"client": None, "down_until": 0.0}


def _refused_seconds() -> int:
    """How long a refusal is remembered; 0 when `ASG_REFUSED_DAYS` is 0 or less (the memory is off)."""
    try:
        days = float(os.getenv("ASG_REFUSED_DAYS", "30") or 30)
    except ValueError:
        days = 30.0
    return int(days * 86400) if days > 0 else 0


def _refused_store():
    """A small synchronous Redis client (the download runs in threads), or None - no REDIS_URL, or Redis failed in
    the last minute (then the in-process memory carries it)."""
    url = (os.getenv("REDIS_URL") or "").strip()
    if not url or time.time() < _refused_redis["down_until"]:
        return None
    if _refused_redis["client"] is None:
        try:
            import redis
            _refused_redis["client"] = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1,
                                                            decode_responses=True)
        except Exception:                                   # noqa: BLE001
            _refused_redis["down_until"] = time.time() + 60
            return None
    return _refused_redis["client"]


def _refused_store_failed(ex: Exception) -> None:
    _refused_redis["down_until"] = time.time() + 60
    logger.warning("ASG_REFUSED_STORE_UNAVAILABLE %s - using this server's memory for a minute", type(ex).__name__)


def _refused_key(form_id: str) -> str:
    """A refusal belongs to the REQUEST that was refused (proof calls, 4 Nov 2026): the form id plus the row the list
    asks for. When a list rebuild changes a form's row (137 LA: asked without its code, refused; now asked as its
    coded 2024/10 row), the new request gets a fresh try instead of inheriting the old refusal."""
    req = ((_index().get(str(form_id)) or {}).get("request") or {}) if form_id else {}
    fp = "latest" if req.get("latest") else str(req.get("edition") or "")
    return (f"{form_id}|{fp}|{str(req.get('geoCode') or '').upper()}|{str(req.get('geoCodeSuffix') or '').upper()}"
            if req else str(form_id))


def remember_refused(form_id: str, reason: str, message: str) -> None:
    """Keep a refusal so nobody asks ASG for this form again for weeks."""
    ttl = _refused_seconds()
    if reason not in REFUSED_REASONS or not form_id or ttl <= 0:
        return
    key = _refused_key(form_id)
    with _ram_lock:
        _refused_ram[key] = (time.time() + ttl, reason, message)
    client = _refused_store()
    if client is not None:
        try:
            client.setex(_REFUSED_PREFIX + key, ttl, json.dumps({"reason": reason, "message": message}))
        except Exception as ex:                             # noqa: BLE001
            _refused_store_failed(ex)
    logger.warning("ASG_FORM_REFUSED_REMEMBERED form=%s reason=%s days=%d - not asked again", form_id, reason,
                   ttl // 86400)


def refused_forms(form_ids: List[str]) -> Dict[str, tuple]:
    """{form id: (reason, message)} for the forms ASG refused (and we still remember)."""
    out: Dict[str, tuple] = {}
    if _refused_seconds() <= 0:
        return out                                   # the memory is off
    ids = [str(f) for f in (form_ids or []) if f]
    keys = {fid: _refused_key(fid) for fid in ids}
    now = time.time()
    with _ram_lock:
        for fid in ids:
            hit = _refused_ram.get(keys[fid])
            if hit and hit[0] > now:
                out[fid] = (hit[1], hit[2])
            elif hit:
                _refused_ram.pop(keys[fid], None)
    rest = [f for f in ids if f not in out]
    client = _refused_store() if rest else None
    if client is not None:
        try:
            for fid, raw in zip(rest, client.mget([_REFUSED_PREFIX + keys[f] for f in rest])):
                if raw:
                    got = json.loads(raw)
                    out[fid] = (got.get("reason") or "wrong_form", got.get("message") or UNAVAILABLE_TEXT)
        except Exception as ex:                             # noqa: BLE001
            _refused_store_failed(ex)
    return out


def mark_unavailable(rows: List[dict]) -> List[dict]:
    """Search rows of forms ASG refused carry `available: False` + the reason, so the screen will not let them be
    ticked (and nobody spends an ASG call finding out again)."""
    bad = refused_forms([r.get("form_id") for r in rows if r.get("source") == SOURCE])
    for r in rows:
        if r.get("form_id") in bad:
            r["available"] = False
            r["unavailable_reason"] = UNAVAILABLE_TEXT
    return rows


def search_for_screen(query: str, limit: int = 25) -> Tuple[List[dict], int, str]:
    rows, total, note = search_full(query, limit)
    return mark_unavailable(rows), total, note


def clear_ram() -> None:
    with _ram_lock:
        _ram.clear()
        _failed.clear()
        _refused_ram.clear()


def _stub_dir() -> str:
    return (os.getenv("ASG_FORMS_STUB_DIR") or "").strip()


def _stub_fetch(meta: dict) -> bytes:
    """Tests: `<dir>/<number>[_<STATE>[_<SUFFIX>]].pdf`. Missing file = ASG's "Invalid Form"."""
    from services.form_instances import base_form_id
    name = base_form_id(str(meta.get("form_id") or ""))[len("ACORD_"):]     # "ACORD_137_TX" -> "137_TX"
    path = os.path.join(_stub_dir(), f"{name}.pdf")
    if not os.path.exists(path):
        raise AsgFormUnavailable("not_available", "This form has no acroform PDF for download.")
    with open(path, "rb") as f:
        return f.read()


def _config():
    from services.asg_transcriber import load_config
    return load_config()


def _network_allowed(cfg) -> Tuple[bool, str]:
    if not (cfg.client_id and cfg.client_secret and cfg.api_key):
        return False, "ASG credentials are not configured"
    app_env = (os.getenv("ENVIRONMENT") or "development").strip().lower()
    if cfg.env == "uat" and app_env == "production" and not _flag("TRANSCRIBER_ALLOW_UAT_IN_PROD"):
        return False, "UAT credentials are not allowed in production"
    return True, ""


def _get_token(cfg, http) -> str:
    import base64
    with _token_lock:
        if _token["value"] and time.time() < _token["expiry"] - 60:
            return _token["value"]
        if time.time() < float(_token.get("failed_until") or 0):
            # The sign-in failed moments ago: every thread waiting on this lock fails at once instead of each
            # trying again (a hung sign-in service would otherwise hold the download threads in turn).
            # The SAME reason as the failure (a refused login stays "auth" -> "not set up"; round 7).
            blocked = AsgFormUnavailable(_token.get("failed_reason") or "asg_error",
                                         _token.get("failed_message") or "ACORD Solutions sign-in failed")
            blocked.sign_in = True
            raise blocked
        try:
            basic = base64.b64encode(f"{cfg.client_id}:{cfg.client_secret}".encode()).decode()
            data = {"grant_type": "client_credentials"}
            if cfg.scope:
                data["scope"] = cfg.scope
            r = http.post(cfg.token_url, data=data, headers={
                "Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"})
            if r.status_code != 200:
                raise AsgFormUnavailable("auth", f"ASG token endpoint answered {r.status_code}")
            body = r.json()
            tok = str(body.get("access_token") or "")
            if not tok:
                raise AsgFormUnavailable("auth", "ASG token reply carried no access token")
            _token.update(value=tok, expiry=time.time() + float(body.get("expires_in") or 3600), failed_until=0.0)
            return tok
        except Exception as ex:
            _token["failed_until"] = time.time() + _TOKEN_FAILURE_SECONDS
            _token["failed_reason"] = ex.reason if isinstance(ex, AsgFormUnavailable) else "asg_error"
            _token["failed_message"] = str(ex) if isinstance(ex, AsgFormUnavailable) else "ACORD Solutions sign-in failed"
            failure = AsgFormUnavailable(_token["failed_reason"], _token["failed_message"])
            failure.sign_in = True       # a SIGN-IN failure: remembered here for 60 s, never against a form
            raise failure from None


_EDITION_RE = re.compile(r"^\d{4}/\d{2}$")


def requested_edition(meta: dict) -> Optional[str]:
    """The edition to ask ASG for when no edition was named: the form's OWN row's edition, exactly as ASG's portal
    asks (owner's DevTools capture, 4 Nov 2026: `formNumber=84&edition=2013/09&geoCodeSuffix=INS`). "Latest" landed on a
    flat, unfillable edition for 5 forms and on nothing for 2 (deep check, 4 Nov 2026). None (= latest) only for a form
    whose recorded request says so - 125 CIS, served by ASG but not in its catalogue, proven with "latest" - and for a
    list built before the request was recorded (the old `ask_edition` rule then still applies)."""
    req = (meta or {}).get("asg_request")
    if isinstance(req, dict) and req:
        if req.get("latest"):
            return None
        edition = str(req.get("edition") or "").strip()
        return edition or None
    if not (meta or {}).get("ask_edition"):
        return None
    listed = str(meta.get("listed_edition") or "").strip()
    return listed if _EDITION_RE.match(listed) else None


def _network_fetch(meta: dict, edition: Optional[str]) -> bytes:
    import httpx
    cfg = _config()
    ok, why = _network_allowed(cfg)
    if not ok:
        raise AsgFormUnavailable("not_configured", why)
    params = {"formNumber": meta["asg_number"]}
    asked = edition or requested_edition(meta)
    if asked:
        params["edition"] = asked
    else:
        params["latestEdition"] = "true"
    req = meta.get("asg_request") if isinstance(meta.get("asg_request"), dict) else {}
    # The row's OWN codes, as ASG's portal sends them: a state form ASG filed with its state only in the row's name
    # (61 VA, 137 LA 2026/02) is asked WITHOUT a geoCode; ASG's other codes (829 LOB, 25 FR) go as the geoCode they
    # are. A list built before the request was recorded falls back to the form's state / variant.
    geo = req["geoCode"] if "geoCode" in req else meta.get("asg_state")
    sfx = req["geoCodeSuffix"] if "geoCodeSuffix" in req else meta.get("asg_suffix")
    if geo:
        params["geoCode"] = geo
    if sfx:
        params["geoCodeSuffix"] = sfx
    url = f"{cfg.base_url}/forms/download"
    started = time.monotonic()
    with _token_lock:
        bearer = bool(cfg.bearer) if _token["bearer"] is None else bool(_token["bearer"])
    try:
        return _download(httpx, cfg, url, params, bearer, meta, edition, started)
    except AsgFormUnavailable:
        raise
    except Exception as ex:                                  # noqa: BLE001
        # A timeout, a refused connection, an HTML page or a JSON value of the wrong shape where the token
        # was expected: ASG is unavailable - the same friendly answer as any other failure, never a raw
        # exception (review rounds 1 and 2).
        logger.warning("ASG_FORM_DOWNLOAD_FAILED form=%s state=%s error=%s",
                       meta.get("asg_number"), meta.get("asg_state") or "-", type(ex).__name__)
        raise AsgFormUnavailable("asg_error", "ACORD Solutions could not be reached") from None


def _pdf_from_reply(body: bytes) -> Optional[bytes]:
    """The PDF in a download reply. UAT sent the raw PDF; PRODUCTION sends it base64-encoded as text, still labelled
    application/pdf (first live production call, 4 Nov 2026: the body began "JVBERi0", base64 for "%PDF-"). Both are
    accepted; anything else is not a PDF."""
    body = body or b""
    if body[:5] == b"%PDF-":
        return body
    text = body.strip().strip(b'"')
    if text[:7] == b"JVBERi0":
        import base64
        import binascii
        try:
            pdf = base64.b64decode(text, validate=False)
        except (binascii.Error, ValueError):
            return None
        return pdf if pdf[:5] == b"%PDF-" else None
    return None


def _download(httpx, cfg, url: str, params: dict, bearer: bool, meta: dict, edition: Optional[str],
              started: float) -> bytes:
    r = None
    with httpx.Client(timeout=httpx.Timeout(_HTTP_TIMEOUT, connect=_CONNECT_TIMEOUT)) as http:
        for attempt in range(3):
            if attempt and time.monotonic() - started > _DOWNLOAD_BUDGET_SECONDS:
                break                                # out of time: report the failure, free the thread
            tok = _get_token(cfg, http)
            r = http.get(url, params=params, headers={
                "x-api-key": cfg.api_key,
                "Authorization": f"Bearer {tok}" if bearer else tok,
                "Accept": "application/pdf"})
            pdf = _pdf_from_reply(r.content) if r.status_code == 200 else None
            if pdf is not None:
                with _token_lock:
                    _token["bearer"] = bearer
                # What was ASKED, not only the caller's edition: a variant asks for its listed edition (4 Nov 2026 -
                # the log read "latest" while the request carried edition=2014/01).
                logger.info("ASG_FORM_DOWNLOAD form=%s geo=%s suffix=%s asked_edition=%s bytes=%d seconds=%.1f",
                            meta["asg_number"], params.get("geoCode") or "-", params.get("geoCodeSuffix") or "-",
                            params.get("edition") or "latest", len(pdf), time.monotonic() - started)
                return pdf
            if r.status_code == 400 and "acroform" in (r.text or "").lower():
                raise AsgFormUnavailable("not_available", "This form has no acroform PDF for download.")
            if r.status_code == 401 and attempt == 0:
                with _token_lock:
                    _token["value"] = ""
                bearer = not bearer                  # the docs show the bare token; Bearer is the fallback
                continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            break
    status = r.status_code if r is not None else "none"
    logger.warning("ASG_FORM_DOWNLOAD_FAILED form=%s state=%s status=%s",
                   meta["asg_number"], meta.get("asg_state") or "-", status)
    raise AsgFormUnavailable("asg_error", f"ACORD Solutions answered {status}")


def has_sample_watermark(pdf_bytes: bytes) -> bool:
    """ASG's UAT "Sample" stamp: a large page-wide image with a transparency mask (Accommodate800forms.md 8.17).
    ACORD's own forms carry only the small ACORD logo image."""
    try:
        import pikepdf
        with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in list(pdf.pages)[:1]:
                xo = (page.get("/Resources") or {}).get("/XObject") or {}
                for _k, v in xo.items():
                    if (v.get("/Subtype") == "/Image" and v.get("/SMask") is not None
                            and int(v.get("/Width", 0)) >= 600 and int(v.get("/Height", 0)) >= 400):
                        return True
    except Exception as ex:                                  # noqa: BLE001
        logger.debug("asg_forms: sample check skipped: %s", ex)
    return False


def edition_from_pdf(pdf_bytes: bytes, number: str) -> Optional[str]:
    """The edition ACORD prints in the form's footer: "ACORD 27 (2016/03)", "ACORD 829 LOB (2009/05)",
    "APPLIED 125CIS (2009/08)" - read by the same footer reader as the identity check (4 Nov 2026: the old pattern
    missed a code longer than two letters)."""
    want = str(number or "").lstrip("0")
    for toks, edition in printed_footers(pdf_bytes):
        if toks[0].lstrip("0") == want and edition:
            return edition
    return None


# ── Is it the form we asked for? (owner, 3 Nov 2026: "are you sure it is always correct?") ────────────────
# Every ACORD form prints its identity in its footer: "ACORD 137 CA (2023/01)", "ACORD 27 (2016/03)". A download is
# used only when that footer is the form we asked for:
#   - the NUMBER matches;
#   - no code we did NOT ask for is printed (another state's version, or a variant on the plain form);
#   - the EDITION printed is the edition we asked for (every request names its row's edition - 4 Nov 2026);
#   - the codes we asked for are printed - OR, when they are not, the edition proved it. ASG's INS forms print NO
#     "INS" ("ACORD 84 (2013/09)", owner's portal download, 4 Nov 2026): requiring the code refused all six while ASG
#     sent the right file. The edition is what separates 84 INS (2013/09) from the plain 84 (2026/03).
# "ACORD 137 CA (2023/01)", the older "ACORD 50 NY (1/98)", and ASG's Applied Systems variants "APPLIED 125CIS (2009/08)"
# (first production downloads, 4 Nov 2026 - both were the right forms but went unread).
_FOOTER_IDENTITY_RE = re.compile(r"(?:ACORD|APPLIED)\s+(\d+[^()\n]{0,24}?)\s*\(\s*(\d{1,4}\s*/\s*\d{2,4})\s*\)")
_MONTHS = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV",
                                       "DEC"), start=1)}


def normalize_edition(text: Any) -> Optional[str]:
    """An edition as YYYY/MM, from the shapes ACORD and ASG write it: "2013/09", the older footer "1/98" / "10/05",
    ASG's catalogue "Oct-97". None when it is none of them ("20003/06") - then the edition proves nothing."""
    t = str(text or "").strip().upper().replace(" ", "")
    m = re.fullmatch(r"(\d{4})/(\d{2})", t)
    if m and 1 <= int(m.group(2)) <= 12:
        return t
    m = re.fullmatch(r"(\d{1,2})/(\d{2})", t)
    if m and 1 <= int(m.group(1)) <= 12:
        yy = int(m.group(2))
        return f"{1900 + yy if yy > 30 else 2000 + yy}/{int(m.group(1)):02d}"
    m = re.fullmatch(r"([A-Z]{3})-(\d{2})", t)
    if m and m.group(1) in _MONTHS:
        yy = int(m.group(2))
        return f"{1900 + yy if yy > 30 else 2000 + yy}/{_MONTHS[m.group(1)]:02d}"
    return None


def printed_footers(pdf_bytes: bytes) -> List[Tuple[Tuple[str, ...], Optional[str]]]:
    """The footers a PDF prints, first and last page: "ACORD 137 CA (2023/01)" -> (("137", "CA"), "2023/01");
    "ACORD 84 (2013/09)" -> (("84",), "2013/09"). Empty when none can be read."""
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = list(pdf.pages)
            text = " ".join((p.extract_text() or "") for p in (pages[:1] + pages[-1:]))
    except Exception:                                        # noqa: BLE001
        return []
    out: List[Tuple[Tuple[str, ...], Optional[str]]] = []
    for m in _FOOTER_IDENTITY_RE.finditer(text):
        toks = tuple(re.findall(r"\d+|[A-Z]+", m.group(1).upper()))
        item = (toks, normalize_edition(m.group(2)))
        if toks and toks[0].isdigit() and item not in out:
            out.append(item)
    return out


def printed_identities(pdf_bytes: bytes) -> List[Tuple[str, ...]]:
    """The form identities a PDF prints in its footer: "ACORD 137 CA (2023/01)" -> ("137", "CA")."""
    out: List[Tuple[str, ...]] = []
    for toks, _edition in printed_footers(pdf_bytes):
        if toks not in out:
            out.append(toks)
    return out


def _variant_codes() -> frozenset:
    """Every variant code a form can print after its number: ASG's suffixes and its non-state codes, read from the
    list (INS, CIS, FR, US, LOB, S ...) - so a plain request that comes back as any variant is refused."""
    return frozenset({"INS", "CIS"} | {str(e.get("suffix") or "").upper() for e in _index().values() if e.get("suffix")})


def _first_page_text(pdf_bytes: bytes) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return (pdf.pages[0].extract_text() or "") if pdf.pages else ""
    except Exception:                                        # noqa: BLE001
        return ""


def identity_check(pdf_bytes: bytes, meta: dict, asked_edition: Optional[str] = None) -> Tuple[Optional[str], bool]:
    """(what the PDF prints INSTEAD of the requested form - "ACORD 84 (2026/03)" - or None, whether a footer was read).
    Nothing is refused when no footer can be read: the caller logs that the form could not be verified.

    Accepted when the footer carries our NUMBER and, on no page, a state or variant code we did not ask for; its
    edition is the one we asked for (or the one ASG's own file name carries - 61 NY); and our own codes are printed -
    or, when they are not, something else proves them:
      - a SUFFIX variant (INS): ASG's suffix files print no suffix (84 INS, proven 4 Nov 2026) - the edition proves it;
      - the edition belongs to this form alone among the number's fillable rows (`asg_unique_edition`);
      - a STATE form whose first page names its state ("Florida Commercial Insurance Application").
    Otherwise refused: the plain 125 at 2016/03 is never accepted as 125 FL at 2016/03 (review A, 4 Nov 2026)."""
    footers = printed_footers(pdf_bytes)
    if not footers:
        return None, False
    number = str(meta.get("asg_number") or "").lstrip("0")
    state = str(meta.get("asg_state") or "").upper()
    suffix = str(meta.get("asg_suffix") or "").upper()
    own = {c for c in (state, suffix) if c}
    req = meta.get("asg_request") if isinstance(meta.get("asg_request"), dict) else {}
    editions = {e for e in (normalize_edition(asked_edition), normalize_edition(req.get("file_edition"))) if e}
    variants = _variant_codes()

    def described(toks, edition):
        return "ACORD " + " ".join(toks) + (f" ({edition})" if edition else "")

    ours = [(toks, edition) for toks, edition in footers if toks[0].lstrip("0") == number]
    for toks, edition in ours:
        rest = set(toks[1:])
        if (rest & _STATE_CODES) - own or (rest & variants) - own:
            return described(toks, edition), True   # another state's version or a variant, on ANY page (review A)
    for toks, edition in ours:
        rest = set(toks[1:])
        if editions and edition and edition not in editions:
            if own and own <= rest:
                # Every code we asked for is printed: the form is ours. ASG's catalogue labels some editions a month
                # off its own file (61 VA: listed 2023/08, prints 2023/07; 61 NY) - second proof round, 4 Nov 2026.
                logger.info("ASG_FORM_EDITION_DIFFERS form=%s asked=%s printed=%s - its codes are printed, used",
                            meta.get("form_id"), sorted(editions), edition)
                return None, True
            # A form whose footer prints NO code (a plain form, ASG's INS variants): a differing edition is the OTHER form
            # of the number only when it is that form's edition (84 INS 2013/09 vs plain 84 2026/03); otherwise it is
            # ASG's label being off (61 VA printed 2023/07 for 2023/08), and the right form is used, logged (4 Nov).
            prints_no_code = not own or (own == {suffix} and str(req.get("geoCodeSuffix") or "").upper() == suffix)
            if prints_no_code and not (rest & own) and edition not in set(meta.get("asg_twin_editions") or []):
                logger.info("ASG_FORM_EDITION_DIFFERS form=%s asked=%s printed=%s - not another form's edition, used",
                            meta.get("form_id"), sorted(editions), edition)
                return None, True
            continue        # another form's edition (84 INS 2013/09 is not 84 2026/03)
        if own <= rest:
            return None, True
        if not (editions and edition):
            continue        # nothing proves the unprinted code
        is_suffix_variant = bool(suffix) and str(req.get("geoCodeSuffix") or "").upper() == suffix
        if is_suffix_variant or meta.get("asg_unique_edition"):
            return None, True
        if state and not suffix and _title_names_state(_first_page_text(pdf_bytes), state):
            return None, True
    toks, edition = (ours or footers)[0]
    return described(toks, edition), True


def fetch_blank(meta: dict, edition: Optional[str] = None) -> Tuple[bytes, Optional[str], bool]:
    """(the blank fillable PDF, its edition, whether it carries ASG's "Sample" stamp).

    THE ONLY ASG CALL in this feature. `edition=None` asks for the latest. A RAM copy serves the rest of the
    generation run (never disk, never the database). Raises AsgFormUnavailable."""
    if not is_asg_meta(meta):
        raise AsgFormUnavailable("not_asg", f"{meta.get('form_id') if isinstance(meta, dict) else meta} is not an ASG form")
    key = _ram_key(meta, edition)
    hit = _ram_get(key)
    if hit:
        return hit[1], hit[2], hit[3]
    if not _stub_dir():
        refused = refused_forms([str(meta.get("form_id") or "")]).get(str(meta.get("form_id") or ""))
        if refused:
            # ASG already refused this form (any server, the last weeks): no call (owner, 4 Nov 2026)
            raise AsgFormUnavailable(refused[0], refused[1])
    known_failure = _failure_get(key)
    if known_failure:
        # Remembered for a while (hours for "no fillable version", minutes for an outage): a user pressing
        # Generate again does not spend ASG calls on a form that just failed (review round 3).
        raise AsgFormUnavailable(known_failure[1], known_failure[2])
    try:
        if _stub_dir():
            data = _stub_fetch(meta)
        else:
            data = _network_fetch(meta, edition)
        # A reply that starts like a PDF but is not a readable fillable form is no form (review round 3).
        try:
            boxes = schema_from_pdf(data)
        except Exception:                                    # noqa: BLE001
            boxes = {}
        if not boxes:
            # Its own reason, remembered for minutes: one bad reply must not block the form for hours (round 4).
            raise AsgFormUnavailable("bad_file", "ACORD Solutions sent a file that is not a fillable form.")
        if not _stub_dir():                                  # the test stubs stand our own forms in for ASG's
            wrong, read = identity_check(data, meta, edition or requested_edition(meta))
            if wrong:
                logger.warning("ASG_FORM_MISMATCH form=%s printed=%r - not used", meta.get("form_id"), wrong)
                raise AsgFormUnavailable(
                    "wrong_form", f"ACORD Solutions sent {wrong} instead of {label_of(meta.get('form_id'))}.")
            if not read:
                logger.warning("ASG_FORM_IDENTITY_UNREAD form=%s - its footer could not be read, so it was not "
                               "checked", meta.get("form_id"))
    except AsgFormUnavailable as ex:
        if not getattr(ex, "sign_in", False):
            _failure_put(key, ex.reason, str(ex))   # a sign-in failure is not the form's: the token memory holds it
            if ex.reason in REFUSED_REASONS and not _stub_dir():
                remember_refused(str(meta.get("form_id") or ""), ex.reason, str(ex))
        raise
    got = edition or edition_from_pdf(data, meta["asg_number"]) or requested_edition(meta)
    sample = has_sample_watermark(data)
    if sample:
        logger.warning("ASG_SAMPLE_FORM form=%s edition=%s - ASG served a 'Sample' watermarked form "
                       "(UAT credentials); it is never removed", meta.get("form_id"), got or "?")
    keys = [key] + ([_ram_key(meta, got)] if got and not edition else [])
    _ram_put(keys, (time.monotonic(), data, got, sample))
    return data, got, sample


_download_pool = None
_download_pool_lock = threading.Lock()


def download_pool():
    """A small pool of its own for ASG downloads, so a slow ACORD Solutions never ties up the threads the
    rest of the app shares (review round 3)."""
    global _download_pool
    with _download_pool_lock:
        if _download_pool is None:
            from concurrent.futures import ThreadPoolExecutor
            # 8 at a time (a 15-form selection downloads in two quick waves); never the app's shared pool.
            _download_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="asg-download")
        return _download_pool


def prefetch_failure_message(failures: List[dict]) -> str:
    """What the generate route says when the pre-download fails: a setup problem is not "try again"."""
    if any(f.get("reason") in ("not_configured", "auth") for f in failures):
        return NOT_SET_UP
    never = [f for f in failures if f.get("reason") == "not_available"]
    wrong = [f for f in failures if f.get("reason") == "wrong_form"]
    now = [f for f in failures if f.get("reason") not in ("not_available", "wrong_form")]
    parts = []

    def _names(fs):                                   # "A", "A and B", "A, B and C"
        labels = [label_of(f.get("form_id")) for f in fs]
        return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]

    def _it(fs, one, many):
        return one if len(fs) == 1 else many
    if never:
        parts.append(f"ACORD Solutions has no fillable version of {_names(never)}, so "
                     f"{_it(never, 'it cannot', 'they cannot')} be generated - remove {_it(never, 'it', 'them')} "
                     f"from your selection.")
    if wrong:
        parts.append(f"ACORD Solutions sent a different form than {_names(wrong)}, so "
                     f"{_it(wrong, 'it was', 'they were')} not used - remove {_it(wrong, 'it', 'them')} "
                     f"from your selection.")
    if now:
        parts.append(f"ACORD Solutions could not provide {_names(now)} right now - remove "
                     f"{_it(now, 'it', 'them')} from your selection, or try again in a few minutes.")
    return "Nothing was generated. " + " ".join(parts)


def try_fetch(meta: dict) -> Optional[dict]:
    """Download one ASG form ahead of generation (the RAM copy then serves the run). None when it worked;
    else {form_id, reason} - never raises. The generate route runs these in parallel, off the event loop,
    BEFORE anything is generated, so a form ACORD Solutions cannot give stops the run while the package can
    still be generated (review round 2)."""
    try:
        fetch_blank(meta)
        return None
    except AsgFormUnavailable as ex:
        return {"form_id": meta.get("form_id"), "reason": ex.reason}
    except Exception as ex:                                  # noqa: BLE001
        logger.warning("asg_forms: %s could not be fetched: %s", meta.get("form_id"), type(ex).__name__)
        return {"form_id": meta.get("form_id"), "reason": "asg_error"}


def label_of(form_id: Any) -> str:
    """"ACORD_137_TX" -> "ACORD 137 TX" (the frontend's `formLabel`)."""
    return str(form_id or "").replace("_", " ").strip()


def with_download(meta: dict, edition: Optional[str], sample: bool) -> dict:
    """The form's record after a download: the edition ASG gave and whether it was a sample."""
    out = dict(meta)
    out["edition"] = edition or ""
    out["asg_sample"] = bool(sample)
    return out


# ── the box list, the stored base, the clean form (D-ASG-3) ──────────────────

def schema_from_pdf(pdf_bytes: bytes) -> dict:
    """{box name: {ft, tu, required}} - the same reader and shape as `forms_schemas/*.json`."""
    import pikepdf
    from services.pdf_service import _collect_fields_pikepdf
    schema: dict = {}
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        if "/AcroForm" in pdf.Root:
            _collect_fields_pikepdf(pdf.Root["/AcroForm"].get("/Fields", []), schema)
    return schema


def _walk_fields(arr, visit) -> None:
    """Every field with a name, in the order `pdf_service._fill_and_highlight` visits them."""
    for item in arr:
        try:
            if item.get("/T") is not None:
                visit(item, str(item.get("/T")))
            kids = item.get("/Kids")
            if kids:
                _walk_fields(kids, visit)
        except Exception:                                    # noqa: BLE001
            continue


def values_only_copy(blank: bytes, values: Optional[dict]) -> bytes:
    """The ASG form with each box's value written (`/V`, a tick's state) and NOTHING else: no fitted font sizes,
    no appearance streams, no highlight colours, no signature - so `cleared_template` gives back the exact blank."""
    import pikepdf
    from services.pdf_service import _get_checkbox_on_state, _yes_no_token
    values = values or {}
    with pikepdf.open(io.BytesIO(blank)) as pdf:
        if "/AcroForm" in pdf.Root:
            def visit(item, name):
                val = values.get(name)
                if val is None or str(val).strip() in ("", "null", "None"):
                    return
                # The box's own state before the value, kept on the box so `cleared_template` puts back EXACTLY
                # what the blank had (no value, "Off", or ACORD's printed default such as the 140's edition box).
                # A box listed twice (a malformed form) keeps the state from its FIRST visit - the second would
                # record the value just written as "blank" (review 3 Nov).
                if _ORIG_KEY not in item:
                    item[_ORIG_KEY] = pikepdf.Dictionary({k: item[k] for k in ("/V", "/AS") if k in item})
                if "/Btn" in str(item.get("/FT", "")):
                    state = _get_checkbox_on_state(item) if _yes_no_token(str(val).strip()) == "Y" else "/Off"
                    item["/V"] = pikepdf.Name(state)
                    item["/AS"] = pikepdf.Name(state)
                else:
                    item["/V"] = pikepdf.String(str(val))
            _walk_fields(pdf.Root["/AcroForm"].get("/Fields", []), visit)
        buf = io.BytesIO()
        # Object streams: the same content in about half the bytes (it is stored with the package).
        pdf.save(buf, object_stream_mode=pikepdf.ObjectStreamMode.generate)
        return buf.getvalue()


def cleared_template(base: bytes) -> bytes:
    """The clean ASG form, rebuilt IN MEMORY from the package's values-only copy: every value cleared."""
    import pikepdf
    with pikepdf.open(io.BytesIO(base)) as pdf:
        if "/AcroForm" in pdf.Root:
            def visit(item, _name):
                if _ORIG_KEY not in item:
                    return                       # a box the copy never wrote is the blank's own
                orig = item[_ORIG_KEY]
                for k in ("/V", "/AS"):
                    if k in orig:
                        item[k] = orig[k]
                    elif k in item:
                        del item[k]
                del item[_ORIG_KEY]
            _walk_fields(pdf.Root["/AcroForm"].get("/Fields", []), visit)
        buf = io.BytesIO()
        pdf.save(buf)
        return buf.getvalue()


def base_copy(record: Any) -> Optional[bytes]:
    """The package's values-only copy of a generated ASG form: made by this run, or read back with the package."""
    if not is_asg_record(record):
        return None
    src = record.get(NEW_BASE_KEY) or record.get(STORED_BASE_KEY)
    return bytes(src) if src else None


def template_source(record: Any) -> Optional[bytes]:
    """The clean template for re-rendering a generated ASG form (edit, sign, download).

    ONLY from the package's own values-only copy. NEVER an ASG call: after generation a package never goes back
    to ASG (D-ASG-3) - a read or an edit must not depend on ASG being up, nor spend ASG usage. None when the copy
    is missing or unreadable; the caller answers "temporarily unavailable" and changes nothing."""
    base = base_copy(record)
    if base is None:
        if is_asg_record(record):
            logger.error("asg_forms: %s has no stored copy - it cannot be rendered",
                         (record.get("form") or {}).get("form_id"))
        return None
    try:
        return cleared_template(base)
    except Exception as ex:                                  # noqa: BLE001
        logger.error("asg_forms: stored copy of %s unreadable: %s", (record.get("form") or {}).get("form_id"), ex)
        return None


def layout_source(record: Any) -> Optional[bytes]:
    """Bytes to read an ASG form's box POSITIONS and page sizes from - the package's values-only copy, else its
    rendered form. Positions never depend on values, so nothing is cleared and ASG is never called."""
    if not is_asg_record(record):
        return None
    src = base_copy(record) or record.get("pdf_bytes")
    return bytes(src) if src else None


def ordered_schema(schema: Any, order: Any) -> Any:
    """`schema` in the form's printed box order (`order`, the list kept at generation). The stored `schema`
    comes back key-sorted from JSONB, and the Y/N -> explanation pairing reads POSITIONS - our 17 forms get
    their order back from `forms_schemas/` (`pdf_service._in_layout_order`); an ASG form from this list."""
    if not isinstance(schema, dict) or not isinstance(order, list) or not order:
        return schema
    out = {k: schema[k] for k in order if k in schema}
    out.update({k: v for k, v in schema.items() if k not in out})
    return out


def prepare_loaded_session(data: dict, base_rows: Optional[Dict[str, bytes]] = None) -> dict:
    """A package just read from the database: each ASG form gets its stored copy (`base_rows`, keyed by form id)
    and its schema back in printed order. Packages without ASG forms are untouched."""
    for fid, rec in ((data or {}).get("generated_forms") or {}).items():
        if not is_asg_record(rec):
            continue
        if base_rows and base_rows.get(fid) is not None:
            rec[STORED_BASE_KEY] = base_rows[fid]
        if isinstance(rec.get("schema"), dict):
            rec["schema"] = ordered_schema(rec["schema"], rec.get(ORDER_KEY))
    return data


# The stored copies never change once a package is generated (only a generation run writes one), so a
# process keeps the ones it has read: the editor and its polls do not pull them from the database again.
_COPY_CACHE_MAX_BYTES = 32 * 1024 * 1024
_COPY_CACHE_TTL_SECONDS = 6 * 60 * 60    # a copy leaves memory after 6 h even if nothing deletes it (fresh review)
_copy_cache: "Dict[Tuple[str, str], bytes]" = {}
_copy_cache_at: "Dict[Tuple[str, str], float]" = {}
_copy_cache_lock = threading.Lock()


def cached_copies(session_id: str, form_ids: List[str]) -> Optional[Dict[str, bytes]]:
    """{form id: copy} when EVERY one is cached for this package, else None (read them all)."""
    with _copy_cache_lock:
        out = {}
        for fid in form_ids:
            key = (str(session_id), str(fid))
            if time.monotonic() - _copy_cache_at.get(key, 0.0) > _COPY_CACHE_TTL_SECONDS:
                _copy_cache.pop(key, None)
                _copy_cache_at.pop(key, None)
            hit = _copy_cache.get(key)
            if hit is None:
                return None
            _copy_cache[(str(session_id), str(fid))] = _copy_cache.pop((str(session_id), str(fid)))  # recent
            out[fid] = hit
        return out


def remember_copies(session_id: str, copies: Dict[str, bytes]) -> None:
    with _copy_cache_lock:
        for fid, data in (copies or {}).items():
            if data:
                _copy_cache.pop((str(session_id), str(fid)), None)
                _copy_cache[(str(session_id), str(fid))] = bytes(data)
                _copy_cache_at[(str(session_id), str(fid))] = time.monotonic()
        total = sum(len(v) for v in _copy_cache.values())
        while _copy_cache and total > _COPY_CACHE_MAX_BYTES:
            oldest = next(iter(_copy_cache))
            total -= len(_copy_cache.pop(oldest))
            _copy_cache_at.pop(oldest, None)


def clear_copy_cache() -> None:
    with _copy_cache_lock:
        _copy_cache.clear()
        _copy_cache_at.clear()


def asg_form_ids_of(data: Any) -> List[str]:
    return [fid for fid, r in (((data or {}).get("generated_forms") or {}).items())
            if isinstance(r, dict) and is_asg_record(r)]


def forget_package(session_id: str) -> None:
    """A deleted package's stored copies leave this process's memory at once (final review)."""
    with _copy_cache_lock:
        for key in [k for k in _copy_cache if k[0] == str(session_id)]:
            _copy_cache.pop(key, None)
            _copy_cache_at.pop(key, None)


def base_row_id(form_id: str) -> str:
    return f"{form_id}{BASE_ROW_SUFFIX}"


def form_id_of_base_row(row_id: str) -> Optional[str]:
    s = str(row_id or "")
    return s[: -len(BASE_ROW_SUFFIX)] if s.endswith(BASE_ROW_SUFFIX) else None
