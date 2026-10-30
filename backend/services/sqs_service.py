# sqs_service.py

import json
import logging
import re
from datetime import datetime, timezone
from typing import List, Tuple, Dict, Optional, Any

from utils.validators import run_field_validations
from services.extraction_service import _fv, _focr, _narrative_remarks_text
from services.normalization import normalize_general, normalize_date
from services.fact_comparison import (
    conflict as _fact_conflict, build_context as _build_pkg_context,
    document_witnesses as _doc_witnesses,
)
from services.lob_canon import canon_line as _canon_line_leaf
from services.lob_canon import canon_part as _canon_part_leaf
from services import term_match

logger = logging.getLogger(__name__)

# ── SQS Version Control ───────────────────────────────────────────────────────
SQS_MODEL_VERSION = "2.4.0"

# ── Client-approved underwriting thresholds (Beta Report §6 Q1/Q2/Q3 answers) ─
_UMB_GL_OCC_MIN    = 1_000_000  # GL each occurrence min for umbrella attachment
_UMB_GL_AGG_MIN    = 2_000_000  # GL aggregate min for umbrella attachment (client Q1)
_UMB_AUTO_CSL_MIN  = 1_000_000  # Auto CSL min for umbrella attachment
_UMB_EL_FULL       = 1_000_000  # EL for full umbrella-over-WC credit
_UMB_EL_OK         = 500_000    # EL for acceptable credit (slight reduction)
_LOSS_YEARS_FULL   = 5          # Years for full loss-history credit
_LOSS_YEARS_PART   = 3          # Years for partial credit
_LOSS_RECENCY_DAYS = 90         # Grace window for current-valued loss runs
_LOSS_CONFLICT_CAP = 45         # Loss-history score ceiling while a no-loss
                                # attestation is contradicted by actual loss-run claims
_LOSS_NO_MATCH_CAP = 25         # Loss-history ceiling when loss runs do NOT match the
                                # insured - unmatched runs are not creditable evidence
                                # for this submission (client §6.4: match before crediting)
_LOSS_RECENCY_MAX_PEN = 25      # Single cap for the ">90 days" reduction. The client
                                # described ONE recency rule, so the same maximum applies
                                # whether or not claim years were parsed (no split caps).
_LOSS_RECENCY_UNKNOWN_PEN = 15  # Fixed penalty when the valuation date cannot be
                                # determined at all. Client requires "currently valued"
                                # for full credit; an unverifiable date cannot satisfy
                                # that bar, so full credit is not awarded.

# ── Narrative component taxonomy (§6.3 item 1) ────────────────────────────────
NARRATIVE_COMPONENT_LABELS: Dict[str, str] = {
    "account_overview":    "Account Overview",
    "operations":          "Operations Description",
    "years_in_business":   "Years in Business",
    "management":          "Management Experience",
    "risk_controls":       "Risk Controls",
    "loss_history":        "Loss History Discussion",
    "coverage_discussion": "Coverage Discussion",
    "carrier_market":      "Prior Carrier / Marketing Reason",
    "location_exposure":   "Location Details",
    "employee_practices":  "Employee / Payroll Context",
    "growth_trends":       "WC Payroll / Class Code Context",
    "target_markets":      "EMOD / XMOD Information",
}

# SYS-04 - the coverage line each component belongs to. A component with NO
# entry here is GENERAL and always applies.
#
# `employee_practices` is deliberately absent: payroll and headcount are GL and
# exposure facts too, so "Employee / Payroll Context" is not a WC-only ask and
# removing it would be the fixture-shaped fix rather than the class fix.
#
# Keyed by component so a future Auto-only or Property-only component inherits
# the gate for free - nothing here is WC-special-cased. The line names are the
# `lob_canon.canon_line` vocabulary and must be described in
# `line_presence._LINE_PROFILES`; an undescribed line answers UNKNOWN, which
# keeps the component (see `applicable_narrative_components`).
NARRATIVE_COMPONENT_LINES: Dict[str, str] = {
    "growth_trends":  "workers_comp",   # WC Payroll / Class Code Context
    "target_markets": "workers_comp",   # EMOD / XMOD Information
}


def _wc_carried(flags: Optional[dict]) -> bool:
    """The insured CARRIES Workers Compensation: the line is in the submission,
    or in force and declined by it (5 Oct 2026, `line_presence.line_carried`).
    For the readers about the insured's coverage - employees without WC, the
    umbrella's Employers Liability - never for the WC rules of this submission,
    which keep reading `has_workers_comp`."""
    try:
        from services.line_presence import line_carried
        return line_carried("workers_comp", None, flags)
    except Exception:                                          # noqa: BLE001
        return bool((flags or {}).get("has_workers_comp"))


def session_form_ids(session_data: Optional[dict],
                     form_results: Optional[list] = None) -> list:
    """Every ACORD form id this submission has selected, generated or been
    recommended - tolerant of every shape the session row uses.

    Only ever ADDS evidence for `line_presence` ("intentionally requested"), so
    a session shape this misses can never cause a component to be dropped that
    would otherwise be kept. Never raises.
    """
    out: list = []
    try:
        sd = session_data if isinstance(session_data, dict) else {}
        for key in ("generated_forms", "selected_forms", "selected_form_ids",
                    "form_ids"):
            value = sd.get(key)
            if isinstance(value, dict):
                out.extend(str(k) for k in value)
            elif isinstance(value, (list, tuple, set)):
                out.extend(str(v) for v in value if isinstance(v, str))
        for rec in (sd.get("recommendations") or []):
            if isinstance(rec, dict) and rec.get("form_id"):
                out.append(str(rec["form_id"]))
        for res in (form_results or []):
            if isinstance(res, dict) and res.get("form_id"):
                out.append(str(res["form_id"]))
    except Exception:                                          # noqa: BLE001
        return []
    return sorted({f for f in out if f})


def applicable_narrative_components(
    facts: Optional[dict] = None,
    flags: Optional[dict] = None,
    form_ids=None,
) -> Dict[str, str]:
    """The narrative label map minus components whose line is NOT in the
    submission (SYS-04).

    *"Gate line-specific recommendations and loss requirements on evidence that
    the line is actually active or intentionally requested. If Workers'
    Compensation is not part of the submission, it should not generate Workers'
    Comp loss requirements, warnings, or remediation tasks."*

    A component is dropped ONLY on a decisive ABSENT from `line_presence`. Every
    other answer - PRESENT, UNKNOWN, an undescribed line, an import failure -
    keeps it, so an unrecognised document shape leaves behaviour exactly as it
    is today. The gate can only ever remove an ask on positive evidence; it can
    never add one, and it can never return more keys than the label map has.

    THE RETURNED MAP IS THE DENOMINATOR. `_calculate_narrative_quality` derives
    `component_pct` from `len(components)`, so dropping a key both stops the
    deduction and removes the label from the "does not include ..." sentence and
    the producer recommendation card - one edit, all three symptoms.
    """
    if not NARRATIVE_COMPONENT_LINES:
        return dict(NARRATIVE_COMPONENT_LABELS)
    try:
        from services.line_presence import line_is_absent
    except Exception:                                          # noqa: BLE001
        # No door, no opinion - the full map is the pre-SYS-04 behaviour.
        return dict(NARRATIVE_COMPONENT_LABELS)

    # One presence answer per LINE, not per component, so two components of the
    # same line can never disagree and the doors are not re-walked per key.
    absent_lines = set()
    for line in set(NARRATIVE_COMPONENT_LINES.values()):
        try:
            if line_is_absent(line, facts, flags, form_ids):
                absent_lines.add(line)
        except Exception:                                      # noqa: BLE001
            continue                                # no opinion -> keep
    if not absent_lines:
        return dict(NARRATIVE_COMPONENT_LABELS)
    return {
        k: v for k, v in NARRATIVE_COMPONENT_LABELS.items()
        if NARRATIVE_COMPONENT_LINES.get(k) not in absent_lines
    }

# §6.3 item 2/4: the five narrative-quality components that have NO structured
# ACORD field behind them (Bucket C). When the narrative does not cover one of
# these, the ARQ asks the client to supply it; when the narrative covers it, no
# question is asked. Each maps to a dedicated free-text fact key the client
# answer lands in - a filled key credits that component (so the score moves and
# the topic is not re-asked) and joins the narrative scan text.
NARRATIVE_ENRICHMENT_FIELDS: Dict[str, str] = {
    "account_overview": "narrative_account_overview",
    "management":       "narrative_management",
    "risk_controls":    "narrative_risk_controls",
    "growth_trends":    "narrative_growth_trends",
    "target_markets":   "narrative_target_markets",
}


def _narrative_enrichment_present(facts: dict) -> Dict[str, bool]:
    """Components the client supplied directly via the narrative-enrichment ARQ.

    A component is credited when its dedicated free-text fact key holds a
    non-empty value, independent of keyword matching - the client explicitly
    answered the topic, so it is covered (§6.3 item 2).
    """
    out: Dict[str, bool] = {}
    for comp, key in NARRATIVE_ENRICHMENT_FIELDS.items():
        val = _fv(facts or {}, key)
        out[comp] = bool(val and str(val).strip() and str(val).strip().lower() not in ("null", "none"))
    return out


def _narrative_enrichment_text(facts: dict) -> str:
    """Concatenated client narrative-enrichment answers, for the scan text."""
    vals = [str(_fv(facts or {}, key) or "").strip()
            for key in NARRATIVE_ENRICHMENT_FIELDS.values()]
    return " ".join(v for v in vals if v and v.lower() not in ("null", "none"))

_NARRATIVE_SCORE_SIGNALS: Dict[str, Tuple[str, ...]] = {
    "account_overview": (
        "account overview", "company overview", "background", "about the", "company profile",
        "operates as", "specializes in", "family-owned", "family owned",
        "owner-operated", "locally owned", "independently owned",
    ),
    "operations": (
        "operations", "scope of work", "nature of business", "services provided",
        "business operations", "type of work", "work includes", "primary business",
        "contractor", "manufacturer", "retailer", "distributor", "operator",
    ),
    "years_in_business": (
        "years in business", "established in", "founded in", "incorporated in",
        "years of experience", "in business since", "years ago", "since 19", "since 20",
    ),
    "management": (
        "management experience", "ownership", "principals", "owner has", "management team",
        "leadership", "professionally managed", "managed by", "owner-operated",
        "experienced management", "experienced ownership", "management background",
        "owner brings", "management brings",
    ),
    "risk_controls": (
        "risk control", "safety practices", "safety program", "loss control",
        "risk management", "written safety", "safety training", "background check",
        "annual inspection", "inspections", "maintenance program", "preventive maintenance",
        "preventative maintenance", "safety manual", "safety procedures",
        "drug testing", "driver training", "fleet management",
    ),
    "loss_history": (
        "no prior losses", "no losses", "loss history", "claims history", "prior claims",
        "no claims", "no reported losses", "no known losses", "clean loss history",
        "favorable loss", "loss free", "reported losses", "claims experience",
        "prior incidents",
    ),
    "coverage_discussion": (
        "coverage", "limits of liability", "general liability", "umbrella",
        "workers compensation", "deductible", "limits requested", "coverage requested",
        "seeking limits", "insurance program", "current coverage",
    ),
    "carrier_market": (
        "prior carrier", "current carrier", "expiring carrier", "incumbent",
        "carrier", "renewal", "seeking competitive", "marketing account",
        "non-renewal", "non renewal", "leaving", "prior insurer", "previous insurer",
        # §6.3: component now also covers the marketing reason for seeking coverage
        "marketing", "why marketing", "reason for marketing", "shopping",
        "seeking coverage", "coverage needed", "remarketing",
    ),
    "location_exposure": (
        "location", "premises", "exposure", "square footage", "address",
        "number of locations", "number of units", "properties", "sites",
        "spread of risk", "geographic",
    ),
    "employee_practices": (
        "employee handbook", "employer handbook", "hiring", "training", "onboarding",
        "employees", "workforce", "staffing", "full-time", "part-time",
        "seasonal workers", "number of employees",
    ),
    "growth_trends": (
        "wc class code", "class code", "payroll by class", "payroll breakdown",
        "payroll allocation", "workers comp payroll", "wc payroll", "payroll schedule",
        "ncci class", "labor classification", "classification code", "job classification",
        "payroll by classification", "employee classification", "class codes",
    ),
    "target_markets": (
        "experience modifier", "experience modification", "e-mod", "emod",
        "x-mod", "xmod", "mod factor", "modification factor", "experience rating",
        "experience mod", "merit rating", "debit mod", "credit mod",
        "workers comp mod", "experience modification rate", "rating bureau", "ncci mod",
    ),
}

# Generic single words from the signal table above that also appear routinely in
# non-narrative boilerplate (certificate / dec-page / application headers, footers,
# letterhead). When scanning a long raw-OCR narrative body (strict mode), one of
# these on its own must NOT credit a component - it needs a strong companion signal
# or a second distinct match. Strong multi-word phrases ("no prior losses",
# "general liability", "number of locations", "employee handbook", "years of
# experience"...) are deliberately NOT listed, so they still credit on first mention.
_NARRATIVE_GENERIC_SIGNALS: frozenset = frozenset({
    "coverage",
    "carrier", "renewal",
    "location", "address", "exposure", "premises", "properties", "sites", "geographic",
    "employees", "training",
    "background", "about the",
})

# ── Narrative underwriting substance signals (40% quality component) ──────────
# Rewards narratives that provide meaningful underwriting context rather than
# rewarding character count or vocabulary diversity (client V1 approval).
# Eight distinct categories — each present adds 12.5 pts to the quality score.
_NARRATIVE_SUBSTANCE_SIGNALS: Dict[str, Tuple[str, ...]] = {
    "ownership_or_experience": (
        "years of experience", "family-owned", "family owned", "founded",
        "established", "in business since", "years in business",
        "owner has", "principals have", "management has", "ownership has",
        "under the same ownership", "owner-operated",
    ),
    "loss_context": (
        "no reported losses", "no prior losses", "no losses", "loss free",
        "clean loss", "no claims", "favorable loss", "prior losses include",
        "loss history shows", "no known losses", "claims history",
    ),
    "risk_controls": (
        "safety program", "safety practices", "written safety",
        "annual inspection", "maintenance program", "preventive maintenance",
        "preventative maintenance", "loss control", "training program",
        "background check", "risk management", "safety manual",
        "safety procedures", "risk controls",
    ),
    "prior_carrier_or_renewal": (
        "renewal", "seeking competitive", "marketing account",
        "prior carrier", "incumbent", "expiring", "previous carrier",
        "reason for seeking", "leaving", "non-renewing", "non renewal",
        "market due to", "shopping coverage",
    ),
    "specific_operations_detail": (
        "percent residential", "percent commercial", "square footage",
        "number of units", "type of work", "operations include",
        "scope of work", "nature of operations", "primarily",
        "work consists", "services include", "specialized in",
        "focus on", "type of business",
    ),
    "coverage_or_limit_discussion": (
        "limits requested", "coverage requested", "per occurrence",
        "umbrella", "excess liability", "additional insured",
        "waiver of subrogation", "coverage includes", "endorsement",
        "coverage needs", "seeking limits",
    ),
    "financial_or_workforce_context": (
        "annual revenue", "gross receipts", "total payroll", "revenue of",
        "full-time", "part-time", "seasonal", "number of employees",
        "workforce", "headcount", "payroll of",
    ),
    "management_or_oversight_quality": (
        "professionally managed", "experienced management",
        "experienced ownership", "licensed", "certified",
        "professional staff", "qualified", "credentialed",
        "background in", "expertise in", "specializes in",
    ),
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _token_diversity(text: str) -> float:
    """Type-token ratio (unique words / total words). Returns 0.0 for empty input."""
    words = str(text).lower().split()
    if not words:
        return 0.0
    return len(set(words)) / len(words)


# Magnitude suffixes a limit may be written with ("$1M", "1.5mm", "500k",
# "$1 million"). Longer tokens MUST precede their prefixes in the regex
# alternation below so "million"/"thousand"/"billion" win over "m"/"b".
_MAGNITUDE_SUFFIXES = {
    "mm": 1_000_000, "m": 1_000_000, "million": 1_000_000, "mil": 1_000_000, "mn": 1_000_000,
    "k": 1_000, "thousand": 1_000,
    "b": 1_000_000_000, "billion": 1_000_000_000, "bn": 1_000_000_000,
}


def _to_int(v) -> int | None:
    """Parse a monetary/limit string to int. Returns None on failure.

    Handles plain scalars ("1000000", "$1,000,000"), magnitude shorthand
    ("$1M", "1.5mm", "500k", "$1 million"), AND combined-limit strings that the
    ARQ hint map tells clients to enter, e.g.:
        "$1,000,000 per occurrence / $2,000,000 aggregate"
        "$1,000,000 combined single limit"
        "1,000,000/1,000,000/1,000,000"
    Strategy: strip formatting; expand a leading magnitude suffix when present
    (so "1M" reads as 1,000,000 and never as the literal 1); otherwise try a
    direct parse, then fall back to the first numeric token (the each-occurrence
    / CSL figure, which is always first).
    """
    if v is None:
        return None
    s = str(v).replace(",", "").replace("$", "").strip().lower()
    # Magnitude shorthand: a leading number immediately followed by a unit suffix.
    _mag = re.match(r"([\d.]+)\s*(million|thousand|billion|mm|m|k|b)\b", s)
    if _mag:
        try:
            return int(float(_mag.group(1)) * _MAGNITUDE_SUFFIXES[_mag.group(2)])
        except Exception:
            pass
    try:
        return int(float(s))
    except Exception:
        tokens = re.findall(r"\d+(?:\.\d+)?", s)
        try:
            return int(float(tokens[0])) if tokens else None
        except Exception:
            return None


# Forms other than ACORD 140 / 141 that print a Business Income limit.
_BI_PRINTING_FORMS = frozenset({"ACORD_160", "ACORD_28"})

_MAGNITUDE_WORD = r"(millions?|mil|mn|thousands?|billions?|bn|mm|m|k|b)"
_MAGNITUDE_AFTER_RE = re.compile(r"\s*" + _MAGNITUDE_WORD + r"(?![a-z])", re.I)
_CURRENCY_BEFORE_RE = re.compile(r"(?:us\s*\$|[$€£]|\b(?:usd|cad|eur|gbp)\b)\s*$", re.I)
_PLAIN_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_FISCAL_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
# A figure stated in thousands: "$18,600 (000s)", "18,600 (in thousands)",
# "Revenue ($000): 18,600".
_THOUSANDS_NOTE_RE = re.compile(
    r"\(\s*(?:in\s+)?\$?\s*000'?s?\s*\)|\bin\s+(?:\$\s*)?thousands\b|\bin\s+000'?s\b"
    r"|\(\s*thousands\s*\)", re.I)
# A number that COUNTS something, not money: "2 locations", "5 years".
_COUNT_AFTER_RE = re.compile(
    r"\s*(?:locations?|sites?|stores?|years?|yrs?|employees?|vehicles?|units?|claims?|losses"
    r"|drivers?|buildings?|months?|days?|people|persons?|staff|ft|pt)\b", re.I)
# Two numbers joined as a RANGE - the magnitude printed once on the upper
# bound belongs to both ("$1.2-1.5M", "$12 to 15 million").
_RANGE_JOIN_RE = re.compile(
    r"^\s*(?:-|–|—|to|/)\s*(?:us\s*\$|[$€£]|usd|cad|eur|gbp)?\s*$", re.I)


def _to_float(v) -> float | None:
    """Parse a money string to float. Returns None on failure.

    READ THE AMOUNT, never the digits (5 Oct 2026, generality audit G2 and its
    skeptic). A digit-strip turned "Revenue: $18.6MM" into 18.6, "66 FT / 7 PT"
    into 667 and a range into 1.0e13; the first rewrite then read "$1.2-1.5M"
    as 1.2 (an absurd 53,333,333% payroll warning and an 85 cap), "$18,600
    (000s)" as 18,600 and "8810: 250,000" as 8,810. Now:
      * every number is read with what stands beside it - a currency mark, a
        magnitude (K / M / MM / million(s) / mil / mn / bn), a "%", a count word
        ("2 locations", "5 years"), a label colon ("8810:"), a fiscal year;
      * a range takes its upper bound's magnitude onto the lower bound, and the
        LOWER bound is the reading;
      * a stated unit of thousands ("(000s)", "in thousands", "($000)")
        multiplies a figure that carries no magnitude of its own;
      * the reading is the first money-like number (currency, magnitude or
        four or more digits) that is not a percentage, a count, a label or a
        year; else the first number that is none of those.
    An OCR "O" inside a digit group is a zero ("18,6O0,000").
    """
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().lower()
    s = re.sub(r"(?<=[\d,])o(?=[\d,o])", "0", s)
    s = re.sub(r"(?<=[\d,])l(?=[\d,])", "1", s)
    in_thousands = bool(_THOUSANDS_NOTE_RE.search(s))
    s = _THOUSANDS_NOTE_RE.sub(" ", s)
    s = re.sub(r"(?<=\d)[,\s](?=\d{3}(?!\d))", "", s)          # thousands separators
    toks = []
    for m in _PLAIN_NUMBER_RE.finditer(s):
        try:
            val = float(m.group(0))
        except ValueError:
            continue
        mm = _MAGNITUDE_AFTER_RE.match(s, m.end())
        word = (mm.group(1).lower() if mm else "")
        if word.endswith("s") and word not in ("ms",):
            word = word[:-1]
        mag = _MAGNITUDE_SUFFIXES.get(word, 1)
        end = mm.end() if mm else m.end()
        currency = bool(_CURRENCY_BEFORE_RE.search(s[max(0, m.start() - 6):m.start()]))
        after = s[end:end + 12]
        toks.append({
            "start": m.start(), "end": end, "val": val, "mag": mag, "currency": currency,
            "pct": bool(re.match(r"\s*(?:%|percent\b|per\s*cent\b|pct\b)", after)),
            "count": bool(_COUNT_AFTER_RE.match(s, end)) and not currency and mag == 1,
            "label": bool(re.match(r"\s*:", after)) and not currency and mag == 1,
            "year": bool(_FISCAL_YEAR_RE.fullmatch(m.group(0))) and not currency and mag == 1,
        })
    if not toks:
        return None
    for i in range(len(toks) - 1):
        lo, hi = toks[i], toks[i + 1]
        if (lo["mag"] == 1 and hi["mag"] > 1 and lo["val"] <= hi["val"]
                and _RANGE_JOIN_RE.match(s[lo["end"]:hi["start"]])):
            lo["mag"] = hi["mag"]
    usable = [t for t in toks if not (t["pct"] or t["count"] or t["label"] or t["year"])]
    money = [t for t in usable if t["currency"] or t["mag"] > 1 or t["val"] >= 1000]
    # A PERCENTAGE IS NEVER MONEY (22 Oct 2026, Z33-PERCENT): a value whose
    # only figures are percentages ("2%", "1.5 percent" - a wind deductible)
    # has no amount, where it used to read as 2 dollars.
    rest = [t for t in toks if not t["pct"]]
    if not (money or usable or rest):
        return None
    best = (money or usable or rest)[0]
    value = best["val"] * best["mag"]
    if in_thousands and best["mag"] == 1:
        value *= 1_000
    return value


_PERCENT_STATED_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|percent\b|per\s*cent\b|pct\b)", re.I)
_MONEY_SHAPED_RE = re.compile(r"[$€£]|\b(?:usd|cad|eur)\b|\d\s*(?:k|m|mm|million)\b", re.I)


def _to_percent(v) -> Optional[float]:
    """A PERCENTAGE, never a money amount (5 Oct 2026, generality audit G2).

    `percent_subcontracted` is free text, and once `_to_float` learned money
    shorthand, "$1.5M (35%)" read as 1,500,000 percent and raised a false hard
    stop. A stated "%" / "percent" wins; otherwise one bare number from 0 to
    100 is the percentage; anything money-shaped, or several numbers, has no
    reading (None) - silence, never a guess. The ONE percent reader -
    `cross_form_validator` delegates here.
    """
    if isinstance(v, dict) and "value" in v:
        v = v.get("value")
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if 0 <= v <= 100 else None
    s = str(v)
    m = _PERCENT_STATED_RE.search(s)
    if m:
        return float(m.group(1))
    if _MONEY_SHAPED_RE.search(s):
        return None
    nums = re.findall(r"\d+(?:\.\d+)?", s)
    if len(nums) == 1:
        val = float(nums[0])
        return val if 0 <= val <= 100 else None
    return None


# C2 (2026-08-24): the attestation parser moved to services/loss_history_state
# - the ONE owner of every loss-history state decision - and is imported back
# under its historical private name so every existing consumer (this module,
# arq_service, tests importing sq._attested_true) keeps working unchanged.
from services.loss_history_state import (  # noqa: E402
    _FALSY_TOKENS,
    _TRUTHY_TOKENS,
    attested_true as _attested_true,
)


def _score_narrative_components(text: str, strict: bool = False) -> Dict[str, bool]:
    """Return per-component presence dict for the §6.3 narrative quality model.

    strict=False (default) credits a component on a SINGLE matched signal phrase -
    identical to the previous `any(...)` behaviour, so every existing caller is
    unchanged. It suits the short, curated narrative fields (account_description /
    acord101_remarks / operations) where one clear mention is meaningful.

    strict=True is for scanning long raw-OCR narrative bodies, which contain
    incidental boilerplate words. There a component is credited only when it matches
    at least one STRONG (specific) signal, OR at least two DISTINCT signals overall.
    A lone generic word (a stray "coverage" / "location" / "carrier" in a header)
    therefore cannot falsely credit a component, while a strong phrase such as
    "no prior losses" or "general liability" still credits on first mention.
    """
    if not text:
        return {k: False for k in NARRATIVE_COMPONENT_LABELS}
    t = text.lower()
    out: Dict[str, bool] = {}
    for key, phrases in _NARRATIVE_SCORE_SIGNALS.items():
        matched = [p for p in phrases if p in t]
        if not strict:
            out[key] = bool(matched)
        else:
            strong = [p for p in matched if p not in _NARRATIVE_GENERIC_SIGNALS]
            out[key] = bool(strong) or len(matched) >= 2
    return out


# What each depth category asks for, in the card's words (13 Oct 2026).
NARRATIVE_SUBSTANCE_ASKS: Dict[str, str] = {
    "ownership_or_experience":      "how long the owners have run the business",
    "loss_context":                 "a sentence on the loss history",
    "risk_controls":                "the safety or loss-control program",
    "prior_carrier_or_renewal":     "why the account is being marketed",
    "specific_operations_detail":   "the scope of work (what the work primarily consists of)",
    "coverage_or_limit_discussion": "the coverage or limits being sought",
    "financial_or_workforce_context": "revenue, payroll or headcount",
    "management_or_oversight_quality": "management's licences or expertise",
}


# A sentence starter per depth category - it carries the phrase the check reads,
# the person finishes the sentence (owner, 13 Oct 2026: "use options").
NARRATIVE_SUBSTANCE_STARTERS: Dict[str, str] = {
    "ownership_or_experience":         "Ownership: in business since ",
    "loss_context":                    "Loss history shows ",
    "risk_controls":                   "Risk controls: written safety program ",
    "prior_carrier_or_renewal":        "Reason for seeking coverage: renewal - ",
    "specific_operations_detail":      "Scope of work: primarily ",
    "coverage_or_limit_discussion":    "Coverage requested: ",
    "financial_or_workforce_context":  "Workforce: number of employees ",
    "management_or_oversight_quality": "Management: experienced management, licensed ",
}


def narrative_gap_options(components: Dict[str, bool], text: str, credited=frozenset()) -> List[dict]:
    """Everything the narrative card still lacks, as tickable options for the
    window: each missing topic and each missing depth category, with a sentence
    starter to finish. Empty when nothing is missing.

    Each option carries the `phrases` its own check reads (owner, 13 Oct 2026:
    a pasted paragraph that covered every item ticked only the one option whose
    starter it repeated word for word). The window shows an option covered as
    soon as the typed text holds one of them - the same single-mention test the
    score applies to the remarks (`_score_narrative_components`, non-strict, and
    `_score_narrative_substance`)."""
    out: List[dict] = []
    for k, ok in (components or {}).items():
        if not ok and k in NARRATIVE_COMPONENT_LABELS:
            out.append({"key": f"topic:{k}", "label": NARRATIVE_COMPONENT_LABELS[k],
                        "starter": f"{NARRATIVE_COMPONENT_LABELS[k]}: ",
                        "phrases": list(_NARRATIVE_SCORE_SIGNALS.get(k, ()))})
    t = (text or "").lower()
    for k, phrases in _NARRATIVE_SUBSTANCE_SIGNALS.items():
        if k not in (credited or ()) and not any(p in t for p in phrases):
            out.append({"key": f"depth:{k}", "label": NARRATIVE_SUBSTANCE_ASKS.get(k, k).capitalize(),
                        "starter": NARRATIVE_SUBSTANCE_STARTERS.get(k, ""),
                        "phrases": list(phrases)})
    return out


def narrative_substance_gaps(text: str, credited=frozenset()) -> List[str]:
    """The depth categories `_score_narrative_substance` finds no phrase for."""
    t = (text or "").lower()
    if not t:
        return []
    return [NARRATIVE_SUBSTANCE_ASKS.get(k, k.replace("_", " "))
            for k, phrases in _NARRATIVE_SUBSTANCE_SIGNALS.items()
            if k not in (credited or ()) and not any(p in t for p in phrases)]


def _score_narrative_substance(text: str, credited=frozenset()) -> int:
    """Score narrative text for underwriting substance (0-100).

    Replaces character-count / vocabulary-diversity as the 40% quality component
    (client V1 approval). Rewards narratives that provide specific underwriting
    context rather than rewarding length alone. Each of the 8 substance categories
    contributes 12.5 pts when at least one of its phrases is detected.

    Examples:
      "Apartment complex. Looking for quote." → ~0 (no substance signals)
      "Family-owned operator, 14 yrs experience. No prior losses. Annual inspections." → ~50
    """
    if not text:
        return 0
    t = text.lower()
    present = sum(
        1 for k, phrases in _NARRATIVE_SUBSTANCE_SIGNALS.items()
        if k in (credited or ()) or any(p in t for p in phrases)
    )
    return int(present / len(_NARRATIVE_SUBSTANCE_SIGNALS) * 100)


_NARRATIVE_LLM_MAX_CHARS = 16000  # bound the fallback doc-body scan in _extract_narrative_doc_text

# Component → canonical fact keys for which the narrative PROSE is itself a
# legitimate basis for the stored value. Lets evidence labels ("Stated in
# narrative") be attributed from the profile WITHOUT depending on a document
# being classified as "narrative" (closes the §6.3 classification-dependency
# gap). Deliberately conservative: it excludes precise figures (claim counts,
# payroll, headcount, addresses) that the narrative only gives CONTEXT for - the
# exact value still comes from a structured source, so those are not labelled as
# narrative-sourced. Components with no curated fact key map to ().
NARRATIVE_COMPONENT_FACT_KEYS: Dict[str, Tuple[str, ...]] = {
    "account_overview":    (),
    "operations":          ("operations_description",),
    "years_in_business":   ("years_in_business",),
    "management":          (),
    "risk_controls":       (),
    "loss_history":        ("loss_history_no_prior_losses_indicator",),
    "coverage_discussion": (),
    "carrier_market":      ("prior_carrier",),
    "location_exposure":   (),
    "employee_practices":  (),
    "growth_trends":       (),
    "target_markets":      (),
}


def narrative_profile_present_map(profile: Optional[dict]) -> Dict[str, bool]:
    """Reduce a detection profile to {component: present_bool}, evidence-gated.

    A component is counted present only when the model flagged it present AND
    returned a non-empty evidence quote - this stops a hallucinated "present"
    (no supporting text) from crediting a component, keeping the score and the
    "includes X but not Y" recommendations honest in both directions.
    """
    out = {k: False for k in NARRATIVE_COMPONENT_LABELS}
    if not isinstance(profile, dict):
        return out
    for k in NARRATIVE_COMPONENT_LABELS:
        v = profile.get(k)
        if isinstance(v, dict):
            out[k] = bool(v.get("present")) and bool(str(v.get("evidence") or "").strip())
    return out


def narrative_profile_fact_keys(profile: Optional[dict]) -> set:
    """Canonical fact keys evidenced by present components in the profile.

    Used by the pipeline to attribute "stated_in_narrative" labels from the
    profile rather than from doc classification alone.
    """
    present = narrative_profile_present_map(profile)
    keys: set = set()
    for comp, ok in present.items():
        if ok:
            keys.update(NARRATIVE_COMPONENT_FACT_KEYS.get(comp, ()))
    return keys


# ── Tier field definitions ────────────────────────────────────────────────────

TIER1_FIELDS = {
    "producer_name":     "Producer / Agency name",
    "applicant_name":    "Applicant legal name",
    "mailing_address":   "Applicant mailing address",
    "effective_date":    "Proposed effective date",
    "lines_of_business": "Lines of business requested",
    "entity_type":       "Business entity type",
}
TIER1_CONTACT = ("contact_name", "contact_phone", "contact_email")

# Client C3 3.5 (2026-08-25): Tier 2 is GENERAL business / submission
# information only - "not Loss History or WC-specific information". Six fields,
# exactly as the client lists them.
#
# REMOVED, and where each one's scoring now lives:
#   prior_carrier, num_claims  - C2 2.7 / 2.8 (2026-08-24) -> Loss History
#       (calculate_p4_loss_history), which understands applicability and
#       new-venture status; keeping them here docked a legitimate new venture
#       for history it cannot have.
#   total_payroll, wc_xmod, wc_payroll_period, wc_officer_exclusions - C3 3.14
#       -> the WC / Exposure rules. Payroll is scored by
#       _calculate_exposure_consistency's "WC coverage with no payroll" bucket;
#       X-mod, payroll period and officer exclusions are scored by the ACORD 130
#       per-form checklist in calculate_sqs, which is exactly the client's own
#       reasoning: "places the requirements closer to the exposure they
#       describe". A GL-only submission is no longer marked down for Workers
#       Comp data it can never have.
#
# THESE FIELDS ARE STILL ASKED FOR. Removal from the SCORE is not removal from
# the questionnaire - question_classifier pins them by name in IMPORTANT_FIELDS
# precisely so this change cannot silently stop us collecting them. See
# tests/test_c3_sqs_integrity.py::test_tier2_removals_are_still_asked_for.
TIER2_FIELDS = {
    "fein":                   "FEIN / Tax ID",
    "operations_description": "Operations description",
    "total_revenue":          "Annual revenue",
    "num_employees":          "Number of employees",
    "years_in_business":      "Years in business",
    "naics_code":             "NAICS / industry code",
}


# ── Tier checks ───────────────────────────────────────────────────────────────

def producer_fields_exempt(flags: dict | None) -> bool:
    """True when PRODUCER NAME must not be scored as a missing Tier 1 field.

    A declarations page is issued by the CARRIER, so it does not print the
    producing agency's name. Counting it as a gap marks a submission down for
    something its document type can never carry.

    ONE definition, because there were two. `check_tier1` (which the PACKAGE
    score uses) applied this exemption; `calculate_sqs`'s ACORD 125 checklist
    kept its own copy of the same six checks and did not. Measured on a live
    dec-page session 2026-08-17: answering `contact_name` moved ACORD 125 from
    63 to 68 while the package sat unmoved at 68, because the two scorers
    disagreed about what a submission owed. The recommendation is still RAISED
    either way - we still want the details - it just stops being a penalty.

    ── C3 3.3, 2026-08-25: TWO corrections, both narrowing this exemption ──
    Client 3.3 and `SQS_Scoring_Specification` section 3.1 use the identical
    sentence: *"Producer name is not required when the ONLY source document is
    a declarations page."* Two ways this function was wider than either
    document allowed, worth up to 40 Tier 1 points on a dec-page-led package:

    1. It keyed on `_doc_type`, which `extraction_pipeline` sets from the
       PRIMARY document. A package of dec page + application + loss run was
       exempted even though the application carries the producer's name.
       It now requires `_only_dec_page`, set only when EVERY active document in
       the package is a declarations page.
    2. It also waived CONTACT INFORMATION. Neither document grants that -
       producer name is the only Tier 1 exemption either one lists. The contact
       waiver was engineering-added. `check_tier1` and the ACORD 125 checklist
       both stop applying it (see their call sites).

    Legacy sessions written before `_only_dec_page` existed have no such key and
    therefore stop being exempt on their next recalculation. That is the
    conforming behaviour and it lowers those scores - see v1-20AUG.md C3-C /
    D6, the scores-move-before-Brent-sees-it rule.
    """
    return (flags or {}).get("_only_dec_page") is True


def certificate_only_package(flags: dict | None) -> bool:
    """True when EVERY active document in the package is a certificate.

    The gate on Tier 1's two-item checklist. A submission that is only a COI
    cannot be asked for an application's details - the document type does not
    carry them, and scoring it down for that marks a submission for what it can
    never state. But `is_certificate_doc` is a PER-DOCUMENT flag ("this document
    IS an ACORD 25/28") and flags merge across the package, so a supporting
    certificate dragged a full declarations package onto the same short list.

    MEASURED, SYS-05 live run 2 (2026-09-04): "Key details in place" went from
    12 items to 8 the moment a certificate was added beside the dec page -
    mailing address, lines of business, entity type and contact information all
    left the list, while the generated ACORD 125 printed every one of them
    correctly. The data was right; only this checklist was wrong.

    EXACTLY the defect `producer_fields_exempt` above documents in its own
    correction #1 - a per-document signal answering a package-level question -
    so it takes the same remedy: a composition flag set by the pipeline only
    when every ACTIVE document is that type.

    Legacy sessions written before `_only_certificate` existed have no such key,
    so a genuine certificate-only package stops being exempt on its next
    recalculation and is asked for the full checklist. That is the conforming
    direction (it can only ADD items to a checklist, never hide one), and it
    matches how `_only_dec_page` handled the same migration.
    """
    return (flags or {}).get("_only_certificate") is True


# ── Core requirement entries: ONE rule, TWO views ─────────────────────────────
# `_tier1_entries` / `_tier2_entries` are the single definition of what a
# submission OWES. Everything downstream is a projection of them:
#
#   * `_tier1_items` / `_tier2_items`  -> the LABEL view. Feeds `check_tier1` /
#     `check_tier2` (the Structural score) and `key_details` (the pre-form
#     "Key details in place / missing" card).
#   * `core_missing_fact_keys`         -> the KEY view. Feeds the
#     questionnaire's Critical rule (SYS-01).
#
# SYS-01 existed because there was no key view: `question_classifier` kept its
# own hardcoded idea of "core" (Tier 1 only), so the pre-form card could print
# four missing Tier 2 details while the Send-to-Client modal reported
# "0 Critical" and told the producer everything critical was already answered.
# Two lists, one submission, opposite verdicts. A projection cannot disagree
# with the thing it projects.
#
# An entry is `(fact_keys, label)`. Most items name ONE key; exactly two name
# more, and both are satisfied by ANY of their keys:
#   * Contact information  - client 9.1, "any one contact method satisfies Tier 1"
#   * NAICS or SIC         - client 3.13, the two codes are interchangeable
# Carrying the whole tuple is what stops the questionnaire marking a `naics_code`
# question Critical on a submission that already states a SIC code - which a
# per-key rule would have done, re-opening the very disagreement this closes.


def _tier1_entries(facts: dict, flags: dict) -> Tuple[
        List[Tuple[Tuple[str, ...], str]], List[Tuple[Tuple[str, ...], str]]]:
    """Tier 1 as (applicable entries, missing entries), in checklist order.

    The ONE place the Tier 1 rules live. `_tier1_items` is its label
    projection, `check_tier1` its historical (ok, missing) projection and
    `key_details` reads both sides, so the "in place" list on the pre-form
    screen can never disagree with the score (V1 H2, 2026-08-27). Missing is a
    subset of applicable, always.
    """
    flags = flags or {}
    # The short checklist belongs to a submission that IS a certificate, not to
    # any package that happens to involve one. BOTH signals are gated on the
    # package, because both answer a different question than the one asked here:
    #
    #   is_certificate_doc     - per-document, "THIS DOCUMENT is an ACORD 25/28".
    #                            Flags merge across the package, so one
    #                            supporting COI spoke for the whole submission.
    #   has_certificate_request - package-level, but it means "a certificate is
    #                            REQUESTED" - the prompt sets it when a document
    #                            "lists a certificate holder". A full commercial
    #                            package routinely needs a COI for a landlord or
    #                            a terminal. Needing one is not being one.
    #
    # Both were measured on the SYS-05 live kit (2026-09-04): the certificate
    # names Cascade Terminal Authority as its holder, so gating only the first
    # signal left the checklist collapsed and "Key details in place" still read
    # 8 items instead of 12. Fixing one and assuming the other was safe is the
    # same mistake in miniature as the bug itself - a flag that answers question
    # A deciding question B.
    #
    # A package carrying ANY application-grade document (a dec page, an
    # application, a policy) can be asked for the full checklist, whatever the
    # reason a certificate is involved.
    if certificate_only_package(flags) and (
        flags.get("is_certificate_doc") or flags.get("has_certificate_request")
    ):
        applicable = [(("applicant_name",), "Applicant legal name"),
                      (("effective_date",), "Proposed effective date")]
        missing = []
        if not _fv(facts, "applicant_name"):
            missing.append((("applicant_name",), "Applicant legal name"))
        if not _fv(facts, "effective_date"):
            missing.append((("effective_date",), "Proposed effective date"))
        return applicable, missing
    applicable: List[Tuple[Tuple[str, ...], str]] = []
    missing: List[Tuple[Tuple[str, ...], str]] = []
    skip_producer_name = producer_fields_exempt(flags)
    for field, label in TIER1_FIELDS.items():
        if skip_producer_name and field == "producer_name":
            continue
        applicable.append(((field,), label))
        # C3 3.4: "Not Applicable fields are removed rather than treated as
        # missing." `_answered` already returns True for a not_applicable state,
        # so an N/A requirement contributes no -20 - which is the same score a
        # removal produces, because Tier 1 deducts per MISSING item rather than
        # dividing by a denominator. Verified equivalent; no change needed here.
        #
        # ANSWERED, not "has a value": a human answering "there is none" has
        # answered (Brent 2026-08-24) and must not be counted as a gap.
        if not _answered(facts, field):
            missing.append(((field,), label))
    # C3 3.3 (2026-08-25): contact information is required on EVERY submission.
    # It used to be waived alongside producer name on a dec page; neither the
    # client's 3.3 nor spec section 3.1 grants that. See producer_fields_exempt.
    #
    # ONE item, THREE keys - client 9.1: "any one contact method satisfies
    # Tier 1". `question_eligibility._contact_requirement_already_met` reads the
    # same rule from the other side, so the questionnaire and the score agree.
    applicable.append((tuple(TIER1_CONTACT), "Contact information"))
    if not any(_answered(facts, f) for f in TIER1_CONTACT):
        missing.append((tuple(TIER1_CONTACT), "Contact information"))
    return applicable, missing


def _tier1_items(facts: dict, flags: dict) -> Tuple[List[str], List[str]]:
    """The LABEL view of `_tier1_entries` - the historical signature."""
    applicable, missing = _tier1_entries(facts, flags)
    return [lbl for _keys, lbl in applicable], [lbl for _keys, lbl in missing]


def check_tier1(facts: dict, flags: dict) -> Tuple[bool, List[str]]:
    _, missing = _tier1_items(facts, flags)
    return len(missing) == 0, missing


def _tier2_not_applicable(facts: dict, field: str) -> bool:
    """Is this Tier 2 field Not Applicable to THIS submission?

    C3 3.6: *"Not Applicable fields are removed from the denominator."* Removal
    and "counted as answered" are NOT the same arithmetic, which is why this
    exists rather than leaning on `_answered`. With six fields, one N/A and one
    genuinely missing: counted-as-answered gives 100 - 1x(100/6) = 83; removed
    from the denominator gives 100 - 1x(100/5) = 80. The client asked for 80.

    Reads the fact's own `value_state` through `fact_state`, the one owner of
    that axis - never a second local table of "which fields can be N/A".
    Fail-open: if the state cannot be read the field stays in the denominator,
    so a fact we cannot classify is never silently excused.
    """
    try:
        # A typed N/A on a fact every business has is a gap, never out of
        # the denominator (29 Oct 2026); a derived one (a new venture) stands.
        from services.answer_semantics import typed_absence_on_always_existing
        if typed_absence_on_always_existing(field, (facts or {}).get(field), facts):
            return False
        from services.fact_state import is_not_applicable
        return is_not_applicable(facts, field)
    except Exception:                                          # noqa: BLE001
        return False


def _tier2_entries(facts: dict) -> Tuple[
        List[Tuple[Tuple[str, ...], str]], List[Tuple[Tuple[str, ...], str]]]:
    """Tier 2 as (applicable entries, missing entries), in checklist order.

    The ONE place the Tier 2 rules live - `check_tier2` scores from its label
    projection, `key_details` lists from it (V1 H2, 2026-08-27) and
    `core_missing_fact_keys` reads its keys (SYS-01). A Not Applicable fact is
    in NEITHER list: 3.6 removes it from the denominator, so it is neither
    owed nor satisfied - and, because the questionnaire reads the same
    entries, an N/A fact can never be raised as a Critical question either.
    """
    # The industry-classification requirement is satisfied by EITHER a NAICS or a
    # SIC code (client 3.13: "NAICS or SIC"; spec section 3.1 lists them as
    # interchangeable). A submission carrying a SIC code but no NAICS is
    # credited, and when both are absent the gap is surfaced as one combined
    # "NAICS or SIC" item rather than ignoring SIC.
    applicable: List[Tuple[Tuple[str, ...], str]] = []
    missing: List[Tuple[Tuple[str, ...], str]] = []
    for field, label in TIER2_FIELDS.items():
        if field == "naics_code":
            # N/A only when BOTH keys are N/A - either one satisfies the
            # requirement, so either one being merely absent is not N/A.
            if (_tier2_not_applicable(facts, "naics_code")
                    and _tier2_not_applicable(facts, "sic_code")):
                continue
            entry = (("naics_code", "sic_code"), "NAICS or SIC industry code")
            applicable.append(entry)
            if not (_answered(facts, "naics_code") or _answered(facts, "sic_code")):
                missing.append(entry)
            continue
        if _tier2_not_applicable(facts, field):
            continue                       # 3.6: removed from the denominator
        applicable.append(((field,), label))
        # ANSWERED, not "has a value" - see check_tier1.
        if not _answered(facts, field) or _describes_a_vehicle_not_the_business(facts, field):
            missing.append(((field,), label))
    return applicable, missing


def _describes_a_vehicle_not_the_business(facts: dict, field: str) -> bool:
    """An operations description that only restates the vehicles' use class
    ("LOCAL SERVICE" over `auto_vehicle_use` "service" - owner's run 18f6914f,
    13 Oct 2026) is not an answer: the review screen lists it as missing, with
    its fix, instead of "in place". The ruling is `normalization.
    vehicle_use_as_operations` - the stamper, the fix window's pre-fill and the
    questionnaire read the same one; a person's own or confirmed words stand."""
    if field != "operations_description":
        return False
    try:
        from services.normalization import vehicle_use_as_operations
        return vehicle_use_as_operations(facts)
    except Exception:                                          # noqa: BLE001
        return False


def _tier2_items(facts: dict) -> Tuple[List[str], List[str]]:
    """The LABEL view of `_tier2_entries` - the historical signature."""
    applicable, missing = _tier2_entries(facts)
    return [lbl for _keys, lbl in applicable], [lbl for _keys, lbl in missing]


# Tier 1 scores the producing agency's own name, but it is never a QUESTION for
# anybody: `question_classifier.CRITICAL_FIELDS` has excluded it since the
# taxonomy shipped ("it is the agency's own name - a producer-side item, not a
# client question"), and the producer-pattern rule routes it away. Excluding it
# here keeps this door from silently reversing that decision. It is the ONLY
# exclusion, and it mirrors an existing one rather than inventing a second list.
_CORE_CRITICAL_EXCLUDED_KEYS = frozenset({"producer_name"})


def core_missing_fact_keys(facts: dict, flags: dict | None = None) -> set:
    """Canonical fact keys this submission still OWES (SYS-01).

    The KEY view of the same Tier 1 + Tier 2 entries `key_details` prints as
    "Key details missing". The questionnaire promotes a question to CRITICAL
    when its fact is in here, so the two screens are projections of one
    calculation and cannot contradict each other again.

    Three properties fall out of reading the entries rather than a second list,
    and each closes a way this could have gone wrong:

      * ANSWERED facts are absent, so a satisfied requirement can never be
        Critical - the client's own acceptance criterion, guaranteed by
        construction rather than by a check somebody could forget.
      * NOT APPLICABLE facts are absent, because 3.6 already removes them.
      * A paired requirement contributes BOTH its keys or NEITHER, so a
        submission stating a SIC code is not asked for NAICS as Critical.

    Fail-closed: anything unreadable yields an empty set, which leaves every
    priority exactly as the static classifier assigned it.
    """
    keys: set = set()
    try:
        _t1_missing = _tier1_entries(facts or {}, flags or {})[1]
        _t2_missing = _tier2_entries(facts or {})[1]
    except Exception:                                          # noqa: BLE001
        logger.warning("core_missing_fact_keys: unreadable facts", exc_info=True)
        return set()
    for fact_keys, _label in list(_t1_missing) + list(_t2_missing):
        keys.update(fact_keys)
    return keys - _CORE_CRITICAL_EXCLUDED_KEYS


def check_tier2(facts: dict, flags: dict | None = None) -> Tuple[int, List[str]]:
    """C3 3.5 / 3.6 - Tier 2 = six general business facts, equally weighted.

    `flags` is retained in the signature (five call sites pass it) but is no
    longer read: it used to gate the three WC fields on `has_workers_comp`, and
    C3 3.14 removed those fields from Tier 2 outright, so the gate has nothing
    left to gate. Kept rather than removed so no caller has to change.
    """
    applicable_labels, missing = _tier2_items(facts)
    applicable = len(applicable_labels)
    if applicable <= 0:
        # Every field N/A. Nothing is owed, so nothing is missing: 100, not a
        # division by zero and not a 0 that would read as a total failure.
        return 100, []
    score = max(0, round(100 - len(missing) * (100 / applicable)))
    return score, missing


def key_details(facts: dict, flags: dict | None = None) -> dict:
    """V1 H2 (client section 7, 2026-08-27): the Core Application (Tier 1) and
    Underwriting Profile (Tier 2) facts, split into what the submission already
    has and what it still lacks - for the pre-form screen, which no longer
    prints a percentage.

    Read from the SAME two item lists the score is built from, so "in place"
    and "missing" can never disagree with the Structural pillar. Labels are the
    checklist labels the score trace already prints. A Not Applicable fact
    appears in neither list (3.6); a producer-exempt field (dec-page-only
    package) appears in neither list (3.3).
    """
    t1_applicable, t1_missing = _tier1_items(facts or {}, flags or {})
    t2_applicable, t2_missing = _tier2_items(facts or {})
    missing = list(t1_missing) + list(t2_missing)
    satisfied = [lbl for lbl in list(t1_applicable) + list(t2_applicable)
                 if lbl not in missing]
    return {"satisfied": satisfied, "missing": missing,
            "missing_items": _key_detail_actions(facts or {}, flags or {})}


_TERM_PAIR = ("effective_date", "expiration_date")


def _key_detail_actions(facts: dict, flags: dict) -> List[dict]:
    """Each missing key detail with the fix the pre-form screen can open for it
    (Orbin 22 Sep item 9, owner 30 Sep 2026: "do the action, not just mention
    it on the screen").

    Read from the SAME entries as `missing`, in the same order, so the list and
    the action can never disagree. The fix is `answer_routing`'s declaration -
    the one door for "can a human answer this?" - shaped as the resolution the
    pre-form screen's existing "Open to fix" window already speaks: typed facts
    share one window (a NAICS-or-SIC pair asks both), a table opens its editor.
    A detail no person can type (mode none) carries no `resolution`: it is
    listed, never offered as a dead button. Additive: `missing` is unchanged."""
    try:
        from services.answer_routing import answer_mode, MODE_FIELD, MODE_NARRATIVE, MODE_SCHEDULE
    except Exception:                                          # noqa: BLE001
        return []
    try:
        entries = (list(_tier1_entries(facts, flags)[1])
                   + list(_tier2_entries(facts)[1]))
    except Exception:                                          # noqa: BLE001
        return []
    out: List[dict] = []
    for keys, label in entries:
        typed: List[str] = []
        schedule_key = None
        for key in keys:
            try:
                mode = answer_mode(key, facts) or {}
            except Exception:                                  # noqa: BLE001
                continue
            if mode.get("mode") == MODE_FIELD and mode.get("fact"):
                typed.append(str(mode["fact"]))
            # A prose fact of its own - the operations description - is typed
            # in the same window (owner's run 18f6914f, 13 Oct 2026: it had no
            # link, so a wrong one could not be replaced before generation).
            # The ACORD 101 remarks stay the Narrative card's.
            elif mode.get("mode") == MODE_NARRATIVE and mode.get("fact") \
                    and mode.get("fact") not in ("additional_remarks_text", "acord101_remarks"):
                typed.append(str(mode["fact"]))
            elif mode.get("mode") == MODE_SCHEDULE and mode.get("schedule_key") and not schedule_key:
                schedule_key = str(mode["schedule_key"])
        # A proposed-term date is typed with its partner (28 Oct 2026 review):
        # a save that leaves the term backwards or ended is refused
        # (`validators.term_save_refusal`), so a window holding only the
        # effective date, beside a document's ended expiration, could never be
        # saved - the item stood with nothing a person could do in it.
        if any(t in _TERM_PAIR for t in typed):
            typed += [t for t in _TERM_PAIR if t not in typed]
        if typed:
            resolution = {"mode": MODE_FIELD, "facts": list(dict.fromkeys(typed))}
        elif schedule_key:
            resolution = {"mode": MODE_SCHEDULE, "schedule_key": schedule_key}
        else:
            resolution = None
        # Who normally answers it - the questionnaire's own taxonomy: a client
        # fact can also be left for "Send to Client"; NAICS / SIC are the
        # producer's or the underwriter's (client test PART 13, 12 Aug 2026).
        audience = "client"
        try:
            from services.question_classifier import classify_question
            if keys and (classify_question(keys[0], canonical_key=keys[0]) or {}).get("bucket") != "client":
                audience = "agency"
        except Exception:                                      # noqa: BLE001
            pass
        out.append({"label": label, "facts": list(keys), "resolution": resolution,
                    "audience": audience})
    return out


def validate_effective_date_window(facts: dict) -> tuple | None:
    from datetime import datetime, timedelta
    from services.normalization import normalize_date
    eff = _fv(facts, "effective_date")
    if not eff:
        return None
    # Delegate to the shared normalization layer (normalization.py) which handles
    # all common formats: MM/DD/YYYY, MM/DD/YY, YYYY-MM-DD, written months, etc.
    # The old private 3-format list was missing %m/%d/%y (two-digit year) which
    # caused a false "format unrecognized" warning on dates like "07/15/25".
    iso = normalize_date(eff)
    if iso is None:
        return ("soft", "effective_date format unrecognized")
    try:
        d = datetime.strptime(iso, "%Y-%m-%d")
        now = datetime.now()
        if d < now - timedelta(days=730):
            return ("soft", "effective_date is more than 2 years in the past")
        if d > now + timedelta(days=730):
            return ("soft", "effective_date is more than 2 years in the future")
    except ValueError:
        return ("soft", "effective_date format unrecognized")
    return None


def _is_renewal_submission(facts: dict) -> bool:
    """The extracted `is_renewal` fact, read affirmatively.

    Mirrors how the stamping layer reads the same fact (pdf_service's Policy
    Status family ticks RENEW on these tokens). Kept local - importing from
    pdf_service here would be a circular import.
    """
    return str(_fv(facts, "is_renewal") or "").strip().lower() in (
        "yes", "y", "true", "1", "renewal", "renew",
    )


def _dates_are_producer_asserted(facts: dict) -> bool:
    """True when a HUMAN stated the policy term, rather than the pipeline having
    read it off an uploaded carrier document.

    THE DISTINCTION THIS WHOLE CHECK TURNS ON (client 2026-08-15). A broker's
    normal workflow is to upload the CURRENT policy - a carrier declarations
    page whose term is, by definition, the term now ending - and build the next
    submission from it. `effective_date` / `expiration_date` are then a COPY of
    the source document, carrying `source: "ai"`. Treating that copy as "the
    period the applicant is proposing" is what produced a hard stop on an
    ordinary submission, capped the package at 60, and made every other
    remediation look dead.

    A producer answer or client questionnaire answer is different in kind: a
    person typed those dates as the term being applied for, so a term that has
    already ended really is an application for a period that does not exist.
    Provenance is recorded on the fact envelope itself (`source`), so this is a
    read, not an inference - through the one door, `fact_state.typed_by_person`.

    At least one date (kept for its callers). The two date rules ask the
    per-date door below about the dates they JUDGE (21 Oct 2026 review, M2).
    """
    return any(_date_is_person_supplied(facts, key)
               for key in ("effective_date", "expiration_date"))


def _date_is_person_supplied(facts: dict, key: str) -> bool:
    """Did a PERSON type this one date (a producer typed it, the client
    answered it)? The one door, `fact_state.typed_by_person` (21 Oct 2026,
    review L1). A document's date, one picked between documents - or typed
    into - Data Consistency (the picker stores both alike), a client's "this
    is correct" in confirm-or-correct, or one Primble calculated is not; and a
    confidence is never provenance (`filled` / `deterministic` are written by
    document readers and our derivations too, so they no longer count). The
    one per-date door for the term rules (21 Oct 2026 review, M2): a hard stop
    needs a person to have supplied every date its condition reads - the
    expired-term stop reads the expiration date, the backwards-term stop reads
    both."""
    from services.fact_state import typed_by_person
    return typed_by_person((facts or {}).get(key))


def _term_dates_both_person_supplied(facts: dict) -> bool:
    """Both proposed-term dates supplied by a person (the backwards-term door)."""
    return all(_date_is_person_supplied(facts, key)
               for key in ("effective_date", "expiration_date"))


def validate_policy_term_not_expired(facts: dict) -> tuple | None:
    """The proposed term has already ended.

    THE ONE GENUINELY MISSING STOP, found 2026-08-14 by asking honestly what a
    dec-page package can be checked for that nothing checks. Every other date
    rule looks at the EFFECTIVE date - format, more than two years past, more
    than two years future - and `validate_date_range` only asks whether
    effective precedes expiration. Nothing looks at the EXPIRATION date against
    today.

    So a package whose term is 07/15/2025-07/15/2026 sails through on 2026-08-14
    and prints both dates in boxes ACORD labels PROPOSED EFF DATE and PROPOSED
    EXP DATE. An application proposing a period that ended last month cannot be
    submitted, and no amount of correct field-filling makes it submittable -
    which is what a hard stop is for.

    Deliberately HARD, unlike every other date rule here: an expired term is not
    a quality problem the underwriter can weigh, it is an application for a period
    that does not exist. A 30-day grace is allowed so a renewal being prepared
    right at expiry is a warning rather than a block.
    """
    from datetime import datetime, timedelta
    from services.normalization import normalize_date
    exp = _fv(facts, "expiration_date")
    if not exp:
        return None
    iso = normalize_date(exp)
    if iso is None:
        return None                      # format is validate_date_format's job
    try:
        d = datetime.strptime(iso, "%Y-%m-%d")
    except ValueError:
        return None
    now = datetime.now()
    if d < now - timedelta(days=30):
        # WHOSE DATES ARE THESE? (client 2026-08-15) A hard stop here asserts
        # "the applicant is proposing a period that already ended". That is only
        # true if a PERSON proposed it. When the dates were read off an uploaded
        # carrier declarations page - the ordinary case, and the only case on a
        # dec-page-only submission - they are a copy of the EXPIRING policy's
        # term, and the honest answer is "confirm the term you are applying
        # for", not a submission-blocking defect that caps the score at 60.
        #
        # Renewal wording makes it certain; producer-typed dates make the hard
        # stop legitimate again. Both are checked, so this behaves correctly
        # whether or not the package happens to say the word "renewal" - the
        # Orbin package does NOT say it anywhere in 271 pages, which is exactly
        # why gating this on `is_renewal` alone would have fixed nothing.
        #
        # THE EXPIRATION DATE IS THE ONE JUDGED (21 Oct 2026 review, M2): a
        # person retyping only the effective date never made a document's
        # past expiration verified - it used to turn this warning hard too.
        if _is_renewal_submission(facts) or not _date_is_person_supplied(facts, "expiration_date"):
            _why = ("on a Renewal submission" if _is_renewal_submission(facts)
                    else "read from an uploaded policy document")
            return ("soft", (
                f"Policy term already expired ({exp}) {_why} - these dates are "
                "the existing/expiring policy's term, not the term being "
                "applied for. Fix: Confirm the proposed effective and "
                "expiration dates for the new term."))
        return ("hard", (
            f"Policy term already expired ({exp}) - the application proposes a "
            "period that ended. Fix: Update the proposed effective and "
            "expiration dates to the term being applied for."))
    if d < now:
        return ("soft", (
            f"Policy term expires within the last 30 days ({exp}) - confirm "
            "the proposed dates are the renewal term, not the expiring one."))
    return None


# ONE list, shared with the answer box (15 Oct 2026, fact_registry._is_naics).
from services.fact_registry import VALID_NAICS_SECTORS as _VALID_NAICS_PREFIXES  # noqa: E402

def validate_naics_code(facts: dict) -> tuple | None:
    code = str(_fv(facts, "naics_code") or "").strip()
    if not code or code.lower() in {"null","none","n/a",""}:
        return None
    if not code.isdigit() or not (2 <= len(code) <= 6):
        return ("soft", f"NAICS code '{code}' is not 2-6 digits")
    if code[:2] not in _VALID_NAICS_PREFIXES:
        return ("soft", f"NAICS prefix '{code[:2]}' is not a valid industry sector")
    return None


# ── Stop evaluation ───────────────────────────────────────────────────────────

def _dates_differ(a: Any, b: Any) -> bool:
    """True only when two dates resolve to DIFFERENT calendar dates.

    Format-only differences (07/15/25 vs 7/15/2025) normalize to the same ISO
    date and are NOT a difference (Beta Report §5.2); falls back to a trimmed
    raw-string compare when either side is not a parseable date so two genuinely
    different non-date strings still differ. Kept local (mirrors the helper in
    cross_form_validator) to avoid a circular import.
    """
    na, nb = normalize_date(a), normalize_date(b)
    if na is not None and nb is not None:
        return na != nb
    return str(a).strip() != str(b).strip()


def _dec_entries_state_payroll(facts: dict) -> bool:
    """The verified dec index states a payroll exposure, whatever its shape.

    WHY (live 2026-08-14): the GL schedule prints "Prem Basis: Payroll /
    Exposure: $39,300", and "GL coverage detected but no revenue or payroll
    found" fired anyway - the payroll FACT merges empty because no single
    label:value pair carries both the word and the figure once the index
    records table cells individually. The warning's own question is "did the
    document state a GL exposure basis?", and the verified index answers it
    deterministically (see extraction_service._entries_state_payroll for the
    two recognised shapes).

    PURGE-SAFE: `dec_states_payroll_basis` is derived by merge_facts while the
    entries still exist and survives the C57 purge, so a post-generation
    recalc reaches the same answer as the pre-generation one - the live
    entries check is the fallback for sessions predating the derived fact.
    Presence check only - nothing is written to any fact or any form.
    """
    if (facts or {}).get("dec_states_payroll_basis"):
        return True
    # THE CLASS SCHEDULE IS THE AUTHORITATIVE HOME for this question and is
    # checked FIRST among the live sources (client run 2026-08-16: the warning
    # fired again on a package whose GL schedule states "Prem Basis: Payroll /
    # Exposure: $39,300"). `gl_class_code_schedule` carries the basis and the
    # amount as ONE row - the client's own "exposure amount + exposure basis"
    # relationship - so it answers "did the document state a GL exposure
    # basis?" without depending on the dec index surviving, on which label
    # shape the recorder chose, or on the derived flag having been written.
    rows = _fv(facts, "gl_class_code_schedule")
    if isinstance(rows, list):
        # ONLY THE GL ROWS (21 Oct 2026, Brent 17 Oct item 6 - the GL window):
        # the rows the 126 prints, the window shows and the class-code reader
        # counts (`pdf_service.gl_own_row_indices`) - a Workers Compensation
        # class filed under GL is not a GL exposure ("do not substitute WC class
        # codes for GL codes"). A basis that says nothing ("N/A", "unknown") is
        # no basis: an unknown stays a gap, never an answer.
        try:
            from services.pdf_service import gl_own_row_indices
            own = gl_own_row_indices(rows, facts)
        except Exception:                                  # noqa: BLE001
            own = list(range(len(rows)))
        try:
            from services.answer_semantics import is_placeholder_text
        except Exception:                                  # noqa: BLE001
            def is_placeholder_text(_v):                   # noqa: E306
                return False
        for i in own:
            r = rows[i]
            if not isinstance(r, dict):
                continue
            basis = str(r.get("premium_basis") or "").strip()
            if basis and not is_placeholder_text(basis) and re.search(
                    r"\d", str(r.get("exposure_amount") or "")):
                return True
    try:
        from services.extraction_service import _entries_state_payroll
    except Exception:                                      # noqa: BLE001
        return False
    return _entries_state_payroll((facts or {}).get("dec_page_entries"))


# ── ONE READER: "does this package hold GL class codes?" (6 Oct 2026) ────────
# Choice Electric #26. The question had two copies with two answers: the
# legacy stop (`evaluate_stops`, fixed 5 Sep to read both homes) and the
# Exposure "Operations" -20 (`_calculate_exposure_consistency`, which read only
# `gl_class_codes_by_location`). Live ca93ed8f: the score said "no GL class
# codes" while ACORD 126 printed three - and the three were the WORKERS
# COMPENSATION rows (5190 / 8742 / 8810) that extraction had also filed under
# the GL schedule. One reader now, both homes, minus every code the documents
# give only to another line's rating (`pdf_service._line_code_witnesses`,
# read WITHOUT the GL homes themselves, so a WC row copied into the GL
# schedule cannot vouch for itself).
GL_CLASS_CODE_HOMES: Tuple[str, ...] = ("gl_class_codes_by_location", "gl_class_code_schedule")
_GL_CODE_SUBKEY_RE = re.compile(r"^(?:(?:gl_)?class_?codes?|codes?)$", re.I)
_GL_CODE_TOKEN_RE = re.compile(r"\b\d{4,6}\b")

# ── A GL class code read out of TEXT (14 Oct 2026, review of run b117f010) ────
# The "no class codes" card is a free-text box, and the producer questionnaire
# asks this fact as "What type of work does your business perform at each
# location?". Every 4-6 digit token used to count, so "Electrical contracting
# at 4800 Pecos St, Denver CO 80221" printed 80221 (the ZIP) as ACORD 125's
# GL CODE and 4800 / 80221 on the 126 grid, and "since 2015", an SIC, a WC or
# a NAICS code printed as GL class codes. This reader decides what PRINTS
# (`pdf_service._gl_code_only_rows`, the 125 and the 126); whether the card is
# ANSWERED stays `_gl_code_tokens` (any number, a description counts) - no
# score moves by it. An ISO GL class code is five digits
# (ACORD 125's own rule, `pdf_service._ISO_GL_CLASS_CODE_RE`), and a number
# counts only where it STANDS as a code: an item (split on , ; : / |, new lines,
# "and", "&") that starts with it once a location label ("Loc 1") and a code label
# ("GL class code") are read past - "92478 electrical", "92478 & 91580" - or
# an item whose one number it is ("Electrical work 92478"), never a ZIP after
# a state, an amount after a money word or "$", or a street number.
_TEXT_ITEM_SPLIT_RE = re.compile(r"[;,:/|\n]+|\s+(?:and|&)\s+", re.I)
_TEXT_LOC_LABEL_RE = re.compile(
    r"^\s*(?:loc(?:ation)?|bldg|building|prem(?:ise)?s?|site)\.?\s*(?:#|no\.?)?\s*\d{1,4}\b\s*[.)\-–]?\s*",
    re.I)
_TEXT_CODE_LABEL_RE = re.compile(
    r"^\s*(?:(?:iso|cgl|gl|general\s+liability)\s+)?(?:class(?:ification)?\s*)?"
    r"(?:codes?|#|no\.?)?\s*[#\-–]?\s*", re.I)
_TEXT_ISO_CODE_RE = re.compile(r"(?<![\d$.,])\d{5}(?![\d,]|\.\d|-\d)")
_TEXT_CODE_RUN_RE = re.compile(r"\s*(?:&|\+|and\b)?\s*(\d{5})(?![\d,]|\.\d|-\d)", re.I)
_TEXT_STREET_AFTER_RE = re.compile(
    r"^\s+(?:[NSEW]\.?\s+)?[A-Za-z0-9.']+(?:\s+[A-Za-z0-9.']+)?\s+"
    r"(?:st|street|ave|avenue|rd|road|blvd|boulevard|dr|drive|ln|lane|way|ct|court|pl|place"
    r"|pkwy|parkway|hwy|highway|cir|circle|ter|terrace|trl|trail)\b", re.I)
_TEXT_NOT_A_CODE_BEFORE_RE = re.compile(
    r"(?:\$\s*|\b(?:payroll|sales|revenues?|receipts|cost|premiums?|limits?|deductibles?|amounts?"
    r"|area|sq|ft|feet|zip|postal|phone|fax|policy|years?|since|employees|units|miles)\b"
    r"[\s:#]*(?:\S+\s+){0,2})$", re.I)


def _text_state_before(before: str) -> bool:
    """Does `before` END with a US state (code or name)? - a ZIP follows one.
    A two-letter code that is also an English word ("in", "or", "me") counts
    only in capitals ("IN 46204"); "work in 92478" is a code."""
    words = re.sub(r"[^A-Za-z ]", " ", before).split()
    if not words:
        return False
    try:
        from services.normalization import _US_STATE_NAME_PHRASES
    except Exception:                                         # noqa: BLE001
        return False
    last = words[-1]
    if len(last) == 2 and last.lower() in {a for _p, a in _US_STATE_NAME_PHRASES}:
        return last.isupper() or last.lower() not in _STATE_CODE_WORDS
    tail = " ".join(w.lower() for w in words[-2:])
    return any(tail == p or tail.endswith(" " + p) for p, _a in _US_STATE_NAME_PHRASES)


_STATE_CODE_WORDS = frozenset({"in", "or", "me", "oh", "ok", "hi", "de", "id", "la", "pa",
                               "ma", "mo", "al", "ne", "ms"})


def gl_code_tokens_in_text(text: Any) -> List[str]:
    """The ISO GL class codes a piece of TEXT gives as codes, in order (see
    above). [] when none stands as a code."""
    out: List[str] = []
    for item in _TEXT_ITEM_SPLIT_RE.split(str(text or "")):
        rest = _TEXT_LOC_LABEL_RE.sub("", item, count=1)
        rest = _TEXT_CODE_LABEL_RE.sub("", rest, count=1)
        lead = re.match(r"(\d{5})(?![\d,]|\.\d|-\d)", rest)
        if lead and not _TEXT_STREET_AFTER_RE.match(rest[lead.end():]):
            pos, found = 0, []
            while True:
                m = _TEXT_CODE_RUN_RE.match(rest, pos)
                if not m or _TEXT_STREET_AFTER_RE.match(rest[m.end():]):
                    break
                found.append(m.group(1))
                pos = m.end()
            out += [c for c in found if c not in out]
            continue
        # One number in the item, and it is a code by where it sits.
        if len(re.findall(r"\d+", item)) != 1:
            continue
        m = _TEXT_ISO_CODE_RE.search(item)
        if not m:
            continue
        before, after = item[:m.start()], item[m.end():]
        if (_TEXT_NOT_A_CODE_BEFORE_RE.search(before) or _text_state_before(before)
                or _TEXT_STREET_AFTER_RE.match(after)):
            continue
        if m.group(0) not in out:
            out.append(m.group(0))
    return out


def _gl_code_tokens(raw: Any) -> Tuple[List[str], bool]:
    """(code tokens, shape understood) for one GL home. A shape this reader
    cannot parse (an opaque string, an unexpected row) is reported so the
    caller keeps today's verdict for it - never a deduction on a guess."""
    if isinstance(raw, dict) and "value" in raw:
        raw = raw.get("value")
    if raw is None or raw == "" or raw == [] or raw == {}:
        return [], True
    tokens: List[str] = []
    understood = True
    items = raw if isinstance(raw, list) else [raw]
    for item in items:
        if isinstance(item, dict):
            # A row counts only through its code cell (HEAD's rule): a row with
            # no code column holds no class code. Only an opaque STRING home is
            # "not understood" below.
            for k, v in item.items():
                if not _GL_CODE_SUBKEY_RE.search(str(k)):
                    continue
                vals = v if isinstance(v, list) else [v]
                for one in vals:
                    s = str(one or "").strip()
                    if not s:
                        continue
                    hits = _GL_CODE_TOKEN_RE.findall(s)
                    # A code cell is a code even when it is not all digits.
                    tokens += hits if hits else [s]
        elif isinstance(item, (str, int)):
            # PRESENCE reads any number, on purpose: the questionnaire asks this
            # fact as "what type of work at each location?", so a description
            # answers it. What PRINTS reads `gl_code_tokens_in_text` (below).
            hits = _GL_CODE_TOKEN_RE.findall(str(item))
            if hits:
                tokens += hits
            elif str(item).strip():
                understood = False
        elif item is not None:
            understood = False
    return tokens, understood


def person_gl_class_codes(facts: Optional[dict]) -> List[str]:
    """The GL class codes of the GL classification window a PERSON saved, in
    order - [] when no person saved it, when the stored table is no longer
    exactly what they saved (`schedule_capture.human_rows`), or when their rows
    state no code (an "Unknown" code is a gap, never an answer).

    THE PERSON'S ANSWER OUTRANKS (21 Oct 2026, review of Brent 17 Oct item 6):
    every card on GL class codes opens the window, and the window writes
    `gl_class_code_schedule` only - so a code the documents left in
    `gl_class_codes_by_location` (or the old card's answer) stayed beside the
    person's correction, and the "class codes that match the operations" -15
    read that stale home alone: a row the person fixed could never clear it.
    Every reader of "which GL codes?" asks this first (`gl_class_codes`,
    `_is_ops_class_code_mismatch`, `pdf_service._person_gl_codes`). Only GL's
    own rows (`pdf_service.gl_own_row_indices` - another line's code is refused
    at the save, `schedule_capture.refused_rows`)."""
    if not isinstance(facts, dict):
        return []
    try:
        from services.schedule_capture import human_rows
        from services.pdf_service import gl_own_row_indices
        table, _src = human_rows(facts, "gl_class_code_schedule")
        own = gl_own_row_indices(table, facts) if table else []
    except Exception:                                         # noqa: BLE001
        return []
    toks, _ok = _gl_code_tokens([table[i] for i in own if isinstance(table[i], dict)])
    return list(dict.fromkeys(toks))


def gl_class_codes(facts: Optional[dict]) -> List[str]:
    """The GL class codes the facts hold (both homes), in order, without the
    codes another line's rating owns. Empty when there are none. A person's
    saved window speaks for itself (`person_gl_class_codes`): its codes are the
    answer, never dropped as another line's because a WC table repeats a
    five-digit GL code (the Z14 misfile).

    "Another line's" is the stamper's own rule, ONE door (22 Oct 2026, the Z14
    open end): `pdf_service._gl_row_is_another_lines` - witnessed only by
    another line's rating (`_gl_codes_owned_elsewhere`) AND not an ISO GL class
    code's five digits. The score read the first half alone, so on the kits
    whose GL hazard rows extraction also copied into `wc_class_codes` ("91580
    Heating and Air Conditioning Systems", payroll beside it) the 126 printed
    the GL row while the score said "GL coverage detected but no class codes
    found" - and held the package at 85 - beside it. A four-digit WC class
    filed under GL (5190 / 8742 / 8810) is still another line's."""
    facts = facts if isinstance(facts, dict) else {}
    person = person_gl_class_codes(facts)
    if person:
        return person
    codes: List[str] = []
    for home in GL_CLASS_CODE_HOMES:
        toks, _ok = _gl_code_tokens(facts.get(home))
        for t in toks:
            if t not in codes:
                codes.append(t)
    if not codes:
        return []
    try:
        from services.pdf_service import _gl_codes_owned_elsewhere, _gl_row_is_another_lines
        elsewhere = _gl_codes_owned_elsewhere(facts)
    except Exception:                                         # noqa: BLE001
        return codes                       # cannot judge -> today's behaviour
    return [c for c in codes if not _gl_row_is_another_lines(c, elsewhere)]


def gl_class_codes_present(facts: Optional[dict]) -> bool:
    """Does the package hold GL class codes? The ONE reader every "GL coverage
    with no class codes" rule asks. A home whose shape cannot be parsed still
    counts as present (today's verdict), so a format change can never invent
    a -20 or a warning."""
    facts = facts if isinstance(facts, dict) else {}
    if gl_class_codes(facts):
        return True
    for home in GL_CLASS_CODE_HOMES:
        raw = facts.get(home)
        toks, ok = _gl_code_tokens(raw)
        if not ok and not toks:
            return True
        # HEAD's per-home rule, kept: any entry in the by-location home counted
        # as present whatever its shape; a SCHEDULE row counts only through its
        # code cell (a classification-only row holds no class code).
        if home == "gl_class_codes_by_location" and not toks:
            val = raw.get("value") if isinstance(raw, dict) and "value" in raw else raw
            if isinstance(val, list) and any(
                    isinstance(r, dict) and not any(_GL_CODE_SUBKEY_RE.search(str(k)) for k in r)
                    for r in val):
                return True
    return False


_GL_WORDS_SUBKEY_RE = re.compile(r"classification|description|operations?|duties", re.I)


def gl_classification_text(facts: Optional[dict]) -> str:
    """The WORDS of the GL classifications the package holds - what each GL
    row says the work is - lower-cased and joined, "" when there are none.

    THE ONE DOOR for "what kind of work do the GL classes describe?" (27 Oct
    2026, Lane B item 1), beside `gl_class_codes` (which codes) and
    `gl_class_codes_present` (any at all). Same homes and the same precedence:
    a person's saved GL window speaks for itself; otherwise both homes, the
    schedule through GL's own rows only (`pdf_service.gl_own_row_indices` -
    a WC class filed under GL is not a GL classification). A row's LOCATION is
    never its classification ("Home office: 456 Oak Ave" is an address, and a
    blob read once took its "office" for clerical work), and the code digits
    are taken off so a payroll or ZIP can never read as a word."""
    facts = facts if isinstance(facts, dict) else {}
    texts: List[str] = []

    def _take(v: Any) -> None:
        for one in (v if isinstance(v, list) else [v]):
            s = re.sub(r"\d+", " ", str(one or "")).strip(" -:;,.")
            if s and not re.fullmatch(r"[\W_]*", s):
                texts.append(re.sub(r"\s+", " ", s).lower())

    def _rows_of(home: str, rows: Any) -> None:
        if not isinstance(rows, list):
            if isinstance(rows, str):
                _take(rows)
            return
        idx = list(range(len(rows)))
        if home == "gl_class_code_schedule":
            try:
                from services.pdf_service import gl_own_row_indices
                idx = gl_own_row_indices(rows, facts)
            except Exception:                                 # noqa: BLE001
                pass
        for i in idx:
            row = rows[i]
            if isinstance(row, dict):
                for k, v in row.items():
                    if _GL_WORDS_SUBKEY_RE.search(str(k)) or _GL_CODE_SUBKEY_RE.search(str(k)):
                        _take(v)
            else:
                _take(row)

    try:
        from services.schedule_capture import human_rows
        person_rows, _src = human_rows(facts, "gl_class_code_schedule")
    except Exception:                                         # noqa: BLE001
        person_rows = None
    if person_rows:
        _rows_of("gl_class_code_schedule", person_rows)
    else:
        for home in GL_CLASS_CODE_HOMES:
            raw = facts.get(home)
            _rows_of(home, raw.get("value") if isinstance(raw, dict) and "value" in raw else raw)
    return " ; ".join(dict.fromkeys(texts))


def _term_not_ended(value: Any) -> bool:
    """True when `value` reads as a date today or later (a term still to run)."""
    iso = normalize_date(str(value)) if value not in (None, "") else ""
    if not iso:
        return False
    try:
        from datetime import datetime as _dt
        return _dt.strptime(iso, "%Y-%m-%d").date() >= _dt.now().date()
    except (TypeError, ValueError):
        return False


def vehicles_with_bad_vin(facts: dict) -> List[str]:
    """The vehicle numbers (1-based, schedule order) whose document-read VIN is
    not a 17-character VIN, on a vehicle from model year 1981 on (or of unknown
    year). Delegates to the one identifier door (`identifier_checks`). Never raises."""
    try:
        from services.identifier_checks import VIN_RULE, impossible_identifiers
        return list(impossible_identifiers(facts).get(VIN_RULE.code) or [])
    except Exception:                                          # noqa: BLE001
        return []


def evaluate_stops(facts: dict, flags: dict) -> Tuple[List[str], List[str]]:
    """
    Evaluate hard and soft stops from facts/flags.
    Cross-doc hard stops appended by caller after check_doc_consistency().
    """
    hard, soft = run_field_validations(facts)
    # FIXED-FORMAT IDENTIFIERS (30 Oct 2026, owner: "fix these globally"): a
    # VIN, NAIC, ZIP, phone or term read off the documents whose format is
    # impossible - one warning per rule, from the one door. Started as the VIN
    # warning (live 8aa8f3ad: a wrapped table cell dropped a VIN's last
    # character); "Vehicle VIN incomplete - " is that rule's sentence.
    try:
        from services.identifier_checks import warning_messages as _id_warnings
        soft.extend(_id_warnings(facts))
    except Exception as _idx:                                  # noqa: BLE001
        logger.warning("identifier checks skipped: %s", _idx)

    # ── ACORD 125 BASELINE (Tier 1) - EMITTED HERE, NOT IN A ROUTE ───────────
    # These warnings lived in `form_routes` on the UPLOAD response only
    # (2026-09-23). Three things followed from that, all reported live:
    #
    #   1. They were appended to a LOCAL `soft_stops` and never persisted, so
    #      they were absent from the array `_resolve_cap` reads - they sat under
    #      a banner reading "Caps your SQS at 85" while capping nothing.
    #   2. `evaluate_stops` never emitted them, so the FIRST recompute (any
    #      Resolve, Dismiss, answer or field edit rebuilds the stop lists from
    #      this function) dropped every one of them - the ones that had been
    #      fixed and the ones that had not, identically. Measured on a live
    #      session: the producer resolved "Proposed effective date", both rows
    #      vanished, and `contact_name` / `contact_phone` / `contact_email` were
    #      all still None with `check_tier1` still reporting the gap.
    #   3. Nothing else re-raised them, so the gap then went silent while still
    #      costing 20 points of the Tier 1 component inside Structural.
    #
    # Emitting from the engine every recompute path already runs makes the
    # warning behave like every other rule: persisted, re-derived from the
    # facts, and gone only when the fact is actually answered. `_answered`
    # (inside check_tier1) means a human saying "there is none" also clears it.
    #
    # SCORES MOVE DOWN on packages missing a Tier 1 field, because an 85 ceiling
    # now applies where the display had merely claimed one. D6 - Brent sees the
    # numbers. The pillar deduction and the ceiling coexist here exactly as they
    # do for the V1 H1 auto-completeness items: the legacy soft stop sets the
    # ceiling, the pillar carries the points.
    _t1_ok, _t1_missing = check_tier1(facts, flags)
    if not _t1_ok:
        for _t1_item in _t1_missing:
            # NO PROPOSED TERM IS A HARD STOP (Brent, 19 Oct 2026: a hard stop
            # only for what is essential to the submission - there is no quote
            # without a term). The same sentence, so its card, code and fix are
            # the ones it always had; it blocks Submission Ready now. Every other
            # Tier 1 gap stays a warning and costs only its Structural points.
            if _t1_item == TIER1_FIELDS["effective_date"]:
                hard.append(
                    f"ACORD 125 minimum field missing: {_t1_item} "
                    "(Fix: Provide this value manually, or upload a document that states it.)"
                )
            else:
                soft.append(
                    f"ACORD 125 minimum field missing: {_t1_item} "
                    "(Fix: Provide this value manually, or upload a document that states it.)"
                )

    date_issue = validate_effective_date_window(facts)
    if date_issue:
        soft.append(date_issue[1])

    naics_issue = validate_naics_code(facts)
    if naics_issue:
        soft.append(naics_issue[1])

    # Plain `hard.append` / `soft.append`, NOT a conditional-expression append:
    # tests/test_legacy_rules.py harvests this function's append sites by
    # walking its AST, and a `(hard if x else soft).append(...)` is invisible to
    # it - the message would then reach users with no cluster and no code, which
    # is exactly what that harness exists to prevent.
    term_issue = validate_policy_term_not_expired(facts)
    if term_issue and term_issue[0] == "hard":
        hard.append(term_issue[1])
    elif term_issue:
        soft.append(term_issue[1])

    # ── Prior carrier adverse action ──────────────────────────────────────────
    if flags.get("prior_carrier_adverse_action") and not _narrative_remarks_text(facts):
        soft.append(
            "Carrier adverse action indicated (nonrenewal / cancellation / declined) - "
            "narrative explanation recommended to give underwriter account context"
        )

    # ── GL ────────────────────────────────────────────────────────────────────
    # ONE DOOR (11 Sep 2026, finding F4). The raw flag let one narrative
    # sentence declare a package claims-made against a declarations page
    # that says OCCURRENCE, and this rule then demanded a retroactive date
    # the policy cannot have. See coverage_evidence.gl_is_claims_made.
    from services.coverage_evidence import gl_is_claims_made as _gl_cm
    if _gl_cm(facts, flags) and not _fv(facts, "retro_date"):
        soft.append("GL policy is claims-made - retro date is required")
    if (flags.get("has_general_liability") and not _answered(facts, "total_revenue")
            and not _answered(facts, "total_payroll")
            and not _dec_entries_state_payroll(facts)):
        soft.append("GL coverage detected but no revenue or payroll found")
    if flags.get("has_general_liability"):
        # ONE DOOR for "do we have GL class codes?". LLM call 1 records them in
        # TWO shapes - `gl_class_codes_by_location` (location + codes) and
        # `gl_class_code_schedule` (the full rating rows) - and which one it
        # fills depends on how the document prints them. This check read only
        # the first, so a package whose codes arrived as the RICHER schedule was
        # told none were found. Live 5 Sep 2026: class 11288 stamped onto ACORD
        # 125's GL CODE box and ACORD 126's hazard row A while this warning said
        # it did not exist. Same one-rule-two-copies shape as the H1-C phantom
        # keys - the fact was there, the checker looked in one of its two homes.
        # 6 Oct 2026: through `gl_class_codes_present`, the one reader the
        # Exposure bucket asks too - both homes, minus another line's codes.
        if not gl_class_codes_present(facts):
            soft.append("GL coverage detected but no class codes found")

    # ── Property ──────────────────────────────────────────────────────────────
    if flags.get("has_property_coverage"):
        min_cope = {
            "locations":             bool(_fv(facts, "locations")),
            "occupancy_type":        bool(_fv(facts, "occupancy_type")),
            "construction_type":     bool(_fv(facts, "construction_type")),
            "building_or_bpp_value": bool(
                _fv(facts, "property_building_value") or _fv(facts, "property_bpp_value")
            ),
        }
        missing_min = [k.replace("_", " ") for k, v in min_cope.items() if not v]
        if missing_min:
            hard.append("Property Minimum Viable COPE incomplete - missing: " + ", ".join(missing_min))
        # Raised from the start (owner, 24 Oct 2026: "every step visible from
        # the start"): it used to wait until the Minimum Viable COPE above was
        # complete, so fixing that hard stop made a new warning APPEAR and took
        # the COPE rows' points with it. While the hard stop fires its 60 still
        # governs, so no score moves.
        carrier_cope = {k: bool(_fv(facts, k)) for k in [
            "year_built", "roof_year", "sprinkler_system",
            "fire_protection_class", "valuation_method", "coinsurance_percentage",
        ]}
        missing_c = [k.replace("_", " ") for k, v in carrier_cope.items() if not v]
        if missing_c:
            soft.append("Carrier-Grade COPE incomplete - Submission Quality Score (SQS) capped at 85. Missing: " + ", ".join(missing_c))

        if flags.get("property_has_bi_coverage"):
            # BI limit + POR ownership moved to cross_form_validator as hard stop.
            # Keep only the "no BI limit at all" soft advisory here to avoid duplication.
            # A BI row the property schedule prints is a stated limit - the ONE
            # door the Property pillar asks (`property_coverages.
            # business_income_limit_stated`, 27 Oct 2026).
            if not _bi_limit_stated(facts):
                soft.append("Business Income coverage detected - BI limit and Period of Restoration should be provided")

        # ── ONE PERIL IS WHAT THE FLAG MEANS (2026-09-23) ───────────────────
        # `property_has_peril_deductibles` is set by extraction when the
        # document shows a wind/hail **or** earthquake **or** flood deductible -
        # ONE is enough (extraction_service.py, and the prompt says so in
        # terms). This rule then HARD STOPPED unless all THREE were defined, so
        # an ordinary policy carrying a wind/hail deductible and no earthquake
        # or flood coverage at all was capped at 60 and told to "specify
        # amounts" for perils it does not buy. A false positive by
        # construction, on the single most common property shape there is, and
        # measured as the live report's actual capper (80 earned, held at 60).
        #
        # There is no per-peril coverage evidence anywhere in the fact set, so
        # "carries flood but did not state the deductible" and "has no flood
        # coverage" are indistinguishable. Asking for a number that does not
        # exist is the failure this project's blank-over-wrong rule exists to
        # prevent, so the only genuine, SATISFIABLE gap is the one below: the
        # document referenced peril deductibles and we captured no amount at
        # all. Filling any one of the three clears it.
        #
        # WARNING, not a hard stop: `sqs_service` records the client's ruling
        # three times over for this family - carrier practice varies, so we
        # flag and never block.
        #
        # TWO DUPLICATE COPIES WERE DELETED WITH THIS EDIT, both in
        # `cross_form_validator` - an identical hard stop
        # (`_check_peril_specific_deductibles_referenced`) and a soft twin
        # gated on `0 < present_count < 3`, which is exactly the ordinary
        # wind-only policy. One rule, one owner; duplication at two severities
        # is what let the Umbrella SIR and auto-symbol defects survive their
        # first fixes.
        if flags.get("property_has_peril_deductibles") and not any(
            _fv(facts, k) for k in (
                "property_deductible_wind",
                "property_deductible_earthquake",
                "property_deductible_flood",
            )
        ):
            soft.append(
                "Peril-specific deductibles referenced but not defined - state the "
                "deductible for each peril this policy actually carries"
            )

        if not _fv(facts, "valuation_method"):
            soft.append("Property valuation method not specified - select RCV or ACV")

        # ACV vs RCV conflict (client Property Integrity): flag for review when the
        # source documents and generated forms disagree on the valuation basis.
        if _acv_rcv_conflict(facts):
            soft.append(
                "Valuation basis conflict - ACV and RCV both appear across the source "
                "documents and generated forms. Flag for underwriter review."
            )

    # ── Revenue-to-payroll outlier (named warning per client Exposure spec) ───
    _rev_stop = _to_float(_fv(facts, "total_revenue"))
    _pay_stop = _to_float(_fv(facts, "total_payroll") or _fv(facts, "wc_payroll"))
    if _rev_stop and _pay_stop and _rev_stop > 0 and _pay_stop > 0:
        _ratio_stop = _pay_stop / _rev_stop
        if _ratio_stop > 2.0:
            soft.append(
                f"Revenue-to-payroll ratio is {_ratio_stop:.1f}x - payroll exceeds 200% of revenue; "
                "verify figures with underwriter before submission"
            )
        elif _ratio_stop < 0.01:
            soft.append(
                f"Revenue-to-payroll ratio is {_ratio_stop:.2%} - payroll under 1% of revenue; "
                "unusually low - verify revenue and payroll figures"
            )

    # ── Workers Comp ──────────────────────────────────────────────────────────
    if flags.get("has_workers_comp"):
        if not _fv(facts, "wc_payroll") and not _fv(facts, "total_payroll"):
            soft.append("Workers Comp detected but payroll is missing")
        if flags.get("wc_has_monopolistic_state"):
            # Spec: Monopolistic WC (ND/OH/WA/WY) - soft if state-fund is acknowledged;
            # HARD STOP if private-carrier WC is being requested for those states.
            # The placement answer (15 Oct 2026): "Yes - ... state fund" confirms
            # what the warning asks and clears it; "No - private carrier ..." is
            # a private-carrier request, which those states do not allow.
            #
            # ONE INPUT (21 Oct 2026; Brent 20 Oct: hard stop only on VERIFIED
            # information). That answer is a person's, and it is the only
            # input anything writes. Four more were read here and written by
            # nothing - no schema key, registry fact, stamper, route or
            # questionnaire: the fact `wc_carrier_type`, the flags
            # `wc_private_carrier_requested` / `wc_requested_private_carrier`,
            # and the FLAG form of `wc_state_fund_acknowledged` (the fact of
            # that name is the answer, kept). Removed; no real package carried
            # them. tests/test_build21oct_b-small-rules.py fails the build if
            # one is read again.
            #
            # READ AS AN OPTION, NEVER BY PREFIX (21 Oct 2026 review, M1):
            # "North Dakota WSI" / "Nothing - ..." / "Now with the ND state
            # fund" began with "no" and raised the HARD stop. Free "Other" text
            # is unverified - it keeps the warning asking to confirm.
            from services.answer_options import wc_placement as _wc_placement
            _placement = _wc_placement(_fv(facts, "wc_state_fund_acknowledged"))
            private_wc_requested = _placement == "private_carrier"
            state_fund_ack = _placement == "state_fund"
            # THE DOCUMENTS ALREADY ANSWER IT (Michelle review, 29 Oct 2026):
            # a WC declarations whose class row for the monopolistic state reads
            # "stop-gap Employers Liability only (WY state fund)" places that
            # state with the state fund - asking the producer to confirm what
            # the policy prints is a false alarm. Every monopolistic state on
            # the package must be so placed; a person's answer still decides.
            if not _placement and documented_state_fund_placement(facts):
                state_fund_ack = True
            if private_wc_requested and not state_fund_ack:
                hard.append(
                    "Monopolistic WC state (ND/OH/WA/WY) requires the state fund - "
                    "private-carrier WC cannot be quoted. Remove private-carrier "
                    "request or acknowledge state-fund handling."
                )
            elif not state_fund_ack:
                # Asked until the placement is confirmed; once it is, there is
                # nothing left to warn about (it used to fire either way).
                soft.append("Monopolistic WC state detected (ND/OH/WA/WY) - must use state fund")
            # A WARNING since 19 Oct 2026 (Brent: hard stops only for what is
            # essential) - the breakdown is fixable later without stopping the
            # work; a private carrier in a monopolistic state stays hard above.
            if not _fv(facts, "wc_monopolistic_payroll"):
                soft.append("Monopolistic WC state detected but wc_monopolistic_payroll breakdown is missing")
        if flags.get("wc_multi_state") and not _fv(facts, "wc_payroll_by_state"):
            soft.append("Multi-state WC - payroll breakdown by state and class code required")

    # ── Umbrella ──────────────────────────────────────────────────────────────
    # GL presence MUST mirror the scorer / state machine, which prefer the clean
    # per-occurrence scalar and fall back to the combined string
    # (gl_each_occurrence or gl_limits). Checking gl_limits alone here would fire a
    # false "no underlying" hard stop - capping the package at 60 - for a
    # submission whose GL landed only in gl_each_occurrence, while the umbrella
    # pillar simultaneously scores it normally. Reading both keeps the headline cap
    # and the pillar score from contradicting each other (§6.5 acceptance criterion).
    #
    # THE APPLICABLE UNDERLYING (21 Oct 2026, Brent's 20 Oct rule 2 - "do not
    # require both GL and Auto; look at the account's actual underlying
    # coverage"). One door, `umbrella_underlying`: an employers liability limit
    # or the umbrella's own schedule of underlying insurance identifies the
    # underlying too, so an umbrella over EL only is no longer hard-stopped. A
    # line the umbrella's OWN schedule lists with no limit found anywhere is a
    # hard stop of its own (verified - the umbrella says it sits over that
    # line); when the schedule also prints amounts it does not tie to one line,
    # that line is a warning to confirm instead. A line the package merely
    # carries keeps its existing warnings (the EL one below, the cross-form GL /
    # auto "limit could not be determined").
    _umb_under: Optional[dict] = None
    if flags.get("has_umbrella"):
        try:
            _umb_under = umbrella_underlying(facts, flags)
        except Exception as _uux:                              # noqa: BLE001
            logger.warning("umbrella_underlying failed in evaluate_stops: %s", _uux, exc_info=True)
            _umb_under = {
                "identified": _umbrella_underlying_stated(facts),
                "missing_scheduled": [], "scheduled_to_confirm": [],
                "missing_carried": (["workers_comp"] if _wc_carried(flags)
                                    and not _fv(facts, "employers_liability_limits") else []),
            }
    if _umb_under is not None and not _umb_under["identified"]:
        hard.append("Umbrella detected but no underlying GL or Auto limits found")
    for _umb_fam in (_umb_under or {}).get("missing_scheduled") or ():
        _umb_lbl = UMB_UNDERLYING_LABELS.get(_umb_fam, _umb_fam)
        hard.append(f"Umbrella's own schedule of underlying insurance lists {_umb_lbl}, "
                    f"but no underlying {_umb_lbl} limit was found")
    for _umb_fam in (_umb_under or {}).get("scheduled_to_confirm") or ():
        _umb_lbl = UMB_UNDERLYING_LABELS.get(_umb_fam, _umb_fam)
        soft.append(f"Umbrella's own schedule of underlying insurance lists {_umb_lbl} - "
                    f"confirm the underlying {_umb_lbl} limit (the schedule's amounts "
                    f"could not be tied to it)")

    # ── ACORD 127: Auto coverage integrity ────────────────────────────────────
    if flags.get("has_auto_coverage"):
        # THE REAL KEYS (H1 audit, 2026-08-26). This read `bi_per_person` /
        # `bi_per_accident` / `pd_per_accident` - three names nothing has ever
        # written. The extractor, the registry and the ACORD 127 stamper all
        # use `auto_bi_per_person` / `auto_bi_per_accident` /
        # `auto_pd_per_accident`, so on every split-limit policy all three read
        # None, the "incomplete" HARD STOP fired, and the package was held at
        # 60 with no way to satisfy it. The legacy names are still read last
        # so a session that somehow carries them is not made worse.
        bi_pp = _fv(facts, "auto_bi_per_person") or _fv(facts, "bi_per_person")
        bi_pa = _fv(facts, "auto_bi_per_accident") or _fv(facts, "bi_per_accident")
        pd_pa = _fv(facts, "auto_pd_per_accident") or _fv(facts, "pd_per_accident")

        # ── V1 H1 6.3: the two Auto Completeness items that also WARN ──────
        # "No vehicle schedule = -15 + Warning", "No driver schedule = -10 +
        # Warning". Emitted HERE (the legacy engine) and deliberately NOT as a
        # cross-form issue: a cross-form soft warning lands in soft_stops AND
        # in the Exposure cross-document bucket (extraction_pipeline merges
        # both), so the same gap would be charged twice inside one pillar. A
        # legacy soft stop only sets the 85 ceiling, which is what "+ Warning"
        # means. Gated on the same door as the deduction, so an HNOA-only
        # account never sees either message.
        try:
            from services.coverage_evidence import auto_completeness_gaps
            _auto_gap_keys = {k for k, _p, _l in auto_completeness_gaps(facts, flags)}
        except Exception as _agx:                              # noqa: BLE001
            logger.warning("auto completeness warnings skipped: %s", _agx, exc_info=True)
            _auto_gap_keys = set()
        if "auto_vin_schedule" in _auto_gap_keys:
            soft.append(
                "Vehicle schedule not provided - a Business Auto submission with "
                "owned vehicles needs the schedule (year, make, model, VIN)"
            )
        if "auto_drivers" in _auto_gap_keys:
            soft.append(
                "Driver schedule not provided - list the drivers of the scheduled "
                "vehicles (name, licence, date of birth)"
            )
        # Spec L185: "Incomplete liability structure → hard stop". Detect a
        # split-limit attempt even when auto_liability_structure / auto_split_limits
        # weren't extracted: if ANY of the three components is present, treat
        # this as split and require all three.
        # V1 H1 (2026-08-26): `any(parts)` used to be dead - it read three
        # phantom keys nothing wrote. Now that it reads the real facts, a CSL
        # policy carrying ONE stray split figure (a merge or gap-fill artefact)
        # would flip to "split", fire this hard stop and cap the package at 60
        # on a policy that states its combined limit perfectly. A stated CSL
        # means the policy is not split.
        # 5 Oct 2026: a CSL STATED IN WORDS also outranks the AI split flag and
        # an AI split structure - the flag OR-merges across chunks, so one chunk
        # misreading a GL "$1,000,000 / $2,000,000" made a CSL policy "split"
        # and capped it at 60. One door: coverage_evidence.auto_limits_are_split.
        from services.coverage_evidence import auto_limits_are_split
        _split_indicated = auto_limits_are_split(facts, flags)
        if _split_indicated:
            # A WARNING since 19 Oct 2026 (Brent: hard stops only for what is
            # essential) - one stated split part already counts as a stated
            # auto limit; the other two are asked for, never a block.
            if not all([bi_pp, bi_pa, pd_pa]):
                soft.append(
                    "Split liability limits incomplete - all three components required "
                    "(BI per person, BI per accident, PD per accident)."
                )

        if flags.get("auto_has_physical_damage"):
            comp_ded = _fv(facts, "auto_deductible_comp")
            coll_ded = _fv(facts, "auto_deductible_collision")
            if not comp_ded or not coll_ded:
                soft.append("Physical damage coverage present but deductibles not specified.")

        if flags.get("has_umbrella"):
            umb_val  = _to_int(_fv(facts, "umbrella_limit"))
            auto_val = _to_int(_fv(facts, "auto_liability_limit"))
            # Client Q1: underlying limits below the umbrella baseline must be a
            # WARNING + score reduction (handled in _calculate_umbrella_adequacy),
            # NOT a hard stop. Carrier attachment points vary, so we never block.
            if umb_val and auto_val and auto_val < _UMB_AUTO_CSL_MIN:
                soft.append("Underlying limits may not meet umbrella requirements.")

    # ── ACORD 131: Umbrella stack integrity ───────────────────────────────────
    if flags.get("has_umbrella"):
        from services.coverage_evidence import gl_is_claims_made as _gl_cm2
        if _gl_cm2(facts, flags) and not _fv(facts, "retro_date"):
            if "GL policy is claims-made - retro date is required" not in soft:
                soft.append("Claims-made GL policy requires retro date for umbrella attachment.")

        # Employers liability, the door's reading (21 Oct 2026): the missing-EL
        # warning is the CARRIED line's warning to confirm (WC carried, the
        # umbrella's schedule neither lists nor excludes EL, no limit anywhere -
        # that schedule's own rows included). A schedule that LISTS EL with no
        # limit is the hard stop above instead; one that leaves EL out asks
        # nothing - the umbrella does not sit over it.
        _umb_el = ((_umb_under or {}).get("lines") or {}).get("workers_comp")
        if "workers_comp" in ((_umb_under or {}).get("missing_carried") or ()):
            soft.append("Umbrella attaches over WC but Employers Liability limits not provided.")
        elif (_umb_el["applicable"] if _umb_el else _wc_carried(flags)):
            el_limit = _fv(facts, "employers_liability_limits")
            if el_limit:
                # Client Q2: umbrella markets expect at least $500K EL (often $1M).
                # Warn across the whole sub-$500K band; score tiers live in
                # _calculate_umbrella_adequacy ($1M full / $500K acceptable / <$500K cut).
                el_val = _to_int(el_limit)
                if el_val and el_val < _UMB_EL_OK:
                    soft.append(
                        f"Employers Liability limit ({el_val:,}) is below the ${_UMB_EL_OK:,} "
                        "minimum preferred by umbrella markets."
                    )

        # ── ONE IMPLEMENTATION, NOT TWO ─────────────────────────────────────
        # This was a SECOND, INDEPENDENT COPY of the cross-form umbrella-period
        # check, comparing `umbrella_effective_date` (read off the umbrella's
        # own dec page - on a renewal, the EXPIRING term) against
        # `effective_date` (after `_route_renewal_dates`, the DERIVED PROPOSED
        # term). Expiring versus proposed: neither date wrong, the comparison
        # meaningless. C64 fixed the cross-form copy and the producer's screen
        # STILL showed "Umbrella and GL policy periods misaligned" - this
        # copy's own wording - because the legacy engine is the one that drives
        # the 60/85 caps.
        #
        # That is the third time this exact duplication has cost a fix (see the
        # Auto hired/non-owned symbols and the Umbrella SIR entries in
        # CLAUDE.md). So this no longer re-implements the comparison: it asks
        # the same helper which package term shares the umbrella's footing, and
        # a blank pair means no comparable term and no message - never a
        # fall-back to the proposed one.
        try:
            from services.cross_form_validator import (
                _package_period_on_umbrella_footing as _umb_footing)
            gl_eff, gl_exp, _ = _umb_footing(facts)
        except Exception:                                  # noqa: BLE001
            gl_eff, gl_exp = _fv(facts, "effective_date"), _fv(facts, "expiration_date")

        # ...and the same COMPARISON: by policy anniversary, every printing
        # read alike (`umbrella_term_misalignment` - this copy's strict date
        # compare still capped "Dec. 1, 2025" and "12:01 AM EST" at 85).
        umb_eff = _fv(facts, "umbrella_effective_date")
        umb_exp = _fv(facts, "umbrella_expiration_date")
        try:
            from services.cross_form_validator import umbrella_term_misalignment as _umb_mis
            _eff_bad, _exp_bad, _note = _umb_mis(umb_eff, umb_exp, gl_eff, gl_exp)
        except Exception:                                  # noqa: BLE001
            _eff_bad = bool(umb_eff and gl_eff and _dates_differ(umb_eff, gl_eff))
            _exp_bad = bool(umb_exp and gl_exp and _dates_differ(umb_exp, gl_exp))
        if _eff_bad:
            soft.append("Umbrella and GL policy periods misaligned.")
        if _exp_bad:
            soft.append("Umbrella and GL expiration dates misaligned.")

        # ── THE REAL UNKNOWN, WHICH SILENCE WAS HIDING ──────────────────────
        # Removing the false misalignment left nothing at all in its place, and
        # there IS something to say: on a renewal the umbrella's stated term is
        # its EXPIRING one, and no document states the term being applied for.
        # That is a genuine gap in the submission - recommended, not a hard
        # stop (it caps nothing), and resolvable by typing the two dates.
        # The mark is the merge's reading of the DOCUMENTS; its fix window asks
        # for the umbrella's two dates. A typed term that has not ended answers
        # it (15 Oct 2026: typing the proposed term left this warning - and its
        # 85 cap - in place, because only a re-merge recomputes the mark, from
        # the documents alone). And it is a RENEWAL's question: once the package
        # no longer says renewal (the application that said "Renew" excluded, or
        # a person's "not a renewal"), a stored mark asks nothing.
        try:
            from services.extraction_service import renewal_is_stated as _says_renewal
        except Exception:                                  # noqa: BLE001
            _says_renewal = lambda _f: True                # noqa: E731
        if "Umbrella" in (_fv(facts, "renewal_lines_expiring") or []) \
                and _says_renewal(facts) \
                and not _term_not_ended(_fv(facts, "umbrella_expiration_date")):
            soft.append(
                "Renewal: the umbrella's proposed policy term is not stated in "
                "the documents - confirm the proposed effective and expiration "
                "dates."
            )

        # REMOVED 2026-08-12 - "Umbrella SIR is lower than GL deductible", a
        # HARD STOP that fired on the ordinary structure and therefore capped
        # the package at 60 on essentially every GL+Umbrella submission with a
        # $0 SIR (the most favourable retention there is).
        #
        # An Umbrella SIR applies only where the umbrella drops down and the
        # underlying does not respond; a GL deductible applies to claims the GL
        # DOES cover, above which the umbrella attaches at the GL LIMIT. The two
        # never meet, so their ordering carries no underwriting meaning. Full
        # reasoning in `cross_form_validator._check_umbrella_attachment_stack`.
        #
        # THIS WAS THE SECOND, INDEPENDENT COPY of that rule - the same
        # duplication that let `umbrella_sir_below_auto_deductible` survive its
        # first fix on 2026-08-07, and the copy that actually drove the score
        # cap (the coded engine's issues are a display mirror; these hard/soft
        # stops are what feed the 60/85 caps). Both copies are now gone.
        #
        # The genuine attachment check - umbrella against the underlying GL
        # LIMIT - is untouched in `_check_umbrella_gl_minimum_limits`.

    # ── THE NARRATIVE AND THE CLAIMS ANSWER DISAGREE (24 Oct 2026) ──────────
    # Package 73284179: "12 claims in the past five years, 4 still open" in the
    # producer's narrative beside the answer "No claims" scored 100, Submission
    # Ready. Both are the person's own words and ACORD 101 prints the
    # narrative, so one of them is wrong on the submission. A WARNING (85 like
    # any open warning), never a hard stop: the producer decides which is
    # right. Only text a person typed is read and only a person's answer
    # counts (`loss_history_state.narrative_answer_mismatch`); either fix -
    # the answer changed, or the narrative corrected - clears it.
    try:
        from services.loss_history_state import narrative_answer_mismatch
        _narr_stance = narrative_answer_mismatch(facts)
    except Exception:                                          # noqa: BLE001
        _narr_stance = None
    if _narr_stance == "claims":
        soft.append(
            "Loss History: your narrative says there were claims, but your answer to "
            "\"Any claims in the last 5 years?\" says no claims. Change whichever is wrong."
        )
    elif _narr_stance == "no_claims":
        soft.append(
            "Loss History: your narrative says there were no claims, but your answer to "
            "\"Any claims in the last 5 years?\" says there were claims. Change whichever "
            "is wrong."
        )

    # A warning that only asks to verify figures stands down once a person
    # verified them (27 Oct 2026, `issue_registry.figures_verified`).
    try:
        from services.issue_registry import drop_verified_figure_stops
        soft = drop_verified_figure_stops(soft, facts, "soft")
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("evaluate_stops: verified-figure filter skipped: %s", exc)
    return hard, soft


_MONOPOLISTIC_WC_STATES = frozenset({"ND", "OH", "WA", "WY"})
_STATE_FUND_WORDS_RE = re.compile(
    r"stop[\s-]*gap|state[\s-]+fund|monopolistic\s+fund|"
    r"workers'?\s*compensation\s+(?:division|bureau|fund)", re.IGNORECASE)


def documented_state_fund_placement(facts: Any) -> bool:
    """True when the package's own WC rows place EVERY monopolistic state it
    carries with the state fund: each such state has a WC class row whose
    description reads stop-gap / state fund (the private policy then gives
    only Employers Liability there). False when no monopolistic state can be
    named from the rows / payroll, or any one of them is not so placed."""
    facts = facts if isinstance(facts, dict) else {}
    rows = _fv(facts, "wc_class_codes")
    rows = rows if isinstance(rows, list) else []
    states: set = set()
    for key in ("wc_payroll_by_state", "wc_monopolistic_payroll"):
        held = _fv(facts, key)
        if isinstance(held, dict):
            states |= {str(k).strip().upper() for k in held}
    states |= {str((r or {}).get("state") or "").strip().upper()
               for r in rows if isinstance(r, dict)}
    mono = states & _MONOPOLISTIC_WC_STATES
    if not mono:
        return False
    placed = {str(r.get("state") or "").strip().upper() for r in rows
              if isinstance(r, dict) and _STATE_FUND_WORDS_RE.search(
                  " ".join(str(r.get(c) or "") for c in ("description", "classification", "code")))}
    return mono <= placed


# ── Hard-stop classification for non-property submissions ─────────────────────

# Hard stops that MUST remain hard regardless of coverage type.
# Per Decision_Tree.txt §46 (Identity & Dates Integrity), §137-142 (Monopolistic WC),
# §185 (Auto split limits), §218 (Umbrella attachment), §381 (Peril deductibles),
# §415 (Builders Risk required fields), and §527 (Named insured missing).
_ALWAYS_HARD_PATTERNS: Tuple[str, ...] = (
    "fein_conflict",
    "FEIN mismatch",          # legacy phrasing (kept for any cached/older messages)
    "FEIN differs",           # current humanized phrasing from check_doc_consistency
    "name_conflict",
    "Named insured missing",
    "Inconsistent applicant_name",   # legacy phrasing
    "Applicant name differs",        # current humanized phrasing
    "date_conflict",
    "expiration_conflict",
    "Policy date mismatch",
    "Policy expiration date mismatch",
    "Umbrella detected but no underlying",
    # A line the umbrella's own schedule lists with no limit found (21 Oct 2026,
    # Brent's rule 2) - the same hard-stop kind, on every package: an umbrella
    # package is rarely a property one, and this list is what keeps a hard stop
    # hard there (`classify_stops`). Only hard lists are read here, so the
    # warning sharing these opening words is never promoted.
    "Umbrella's own schedule of underlying insurance lists",
    # NOTE: "auto_umbrella_attachment_failure" intentionally removed - client Q1
    # requires underlying-limit shortfalls to be a warning, not a hard stop.
    "auto_split_limits_incomplete",     # legacy code token (kept for safety)
    "Split liability limits incomplete",  # current humanized phrasing
    "Umbrella SIR",
    "WC payroll differs from total payroll",
    "Location count mismatch",
    "Monopolistic WC state detected but wc_monopolistic_payroll",
    "Monopolistic WC state (ND/OH/WA/WY) requires the state fund",
    "Peril-specific deductibles referenced but not defined",
    "Peril-specific",
    "Builders Risk missing required field",
    # No proposed term (Brent, 19 Oct 2026: no quote without one) - a hard stop
    # on every package, property or not.
    "ACORD 125 minimum field missing: Proposed effective date",
    "policy period is invalid",
    "Policy term already expired",
    # The Data Consistency picker's own sentence (`stops_now.
    # underwriting_conflict_stops`, "<label>: documents disagree (...)"). Only a
    # BLOCKING row reaches a hard list - documents naming different companies
    # (name / FEIN) - so it stays hard on every package. Before, a GL-only
    # package demoted it, and the proceed banner listed a name conflict as
    # "information typically required for property coverage".
    ": documents disagree (",
    # The date, split-limit, monopolistic-breakdown and "Named insured missing"
    # patterns above are warnings since 19 Oct 2026; they stay for hard lists
    # stored before then (the recalculation's prior view classifies those).
)


def classify_stops(
    hard_stops: List[str],
    flags: dict,
) -> Tuple[bool, List[str], List[str]]:
    """Classify hard stops for the submission type.

    For non-property submissions (no has_property_coverage flag), property-related
    hard stops are downgraded to soft warnings and the caller may allow the user
    to proceed with a confirmation.

    Returns:
        can_proceed_with_warning : True if all remaining hard stops are soft-downgraded
        remaining_hard_stops     : stops that are still truly blocking
        downgraded_to_warnings   : stops moved from hard → soft for this path
    """
    has_property = bool(flags.get("has_property_coverage"))

    if has_property or not hard_stops:
        # Property submissions: all hard stops remain hard.
        return False, list(hard_stops), []

    remaining_hard: List[str] = []
    downgraded:     List[str] = []

    for stop in hard_stops:
        is_always_hard = any(pat in stop for pat in _ALWAYS_HARD_PATTERNS)
        if is_always_hard:
            remaining_hard.append(stop)
        else:
            downgraded.append(stop)

    can_proceed = len(remaining_hard) == 0
    return can_proceed, remaining_hard, downgraded


# ── Risk transfer compliance checklist ───────────────────────────────────────

def risk_transfer_check(facts: dict, flags: dict, selected_form_ids: List[str]) -> List[dict]:
    """Advisory-only compliance checklist for risk transfer requirements."""
    checklist: List[dict] = []

    rt = facts.get("risk_transfer")
    if isinstance(rt, dict) and "value" in rt:
        rt = rt["value"]
    if isinstance(rt, str):
        try:
            rt = json.loads(rt)
        except Exception:
            rt = {}
    if not isinstance(rt, dict):
        rt = {}

    if rt.get("additional_insured_required") is True or flags.get("has_additional_insured_requirement"):
        item: dict = {
            "check":   "additional_insured",
            "label":   "Additional Insured Endorsement",
            "status":  "required",
            "message": "Additional insured requirement detected.",
        }
        if "ACORD_25" not in selected_form_ids:
            item["advisory"] = (
                "ACORD 25 not included - consider adding it to document "
                "additional insured status."
            )
        checklist.append(item)

    ai_names = rt.get("additional_insured_names") or []
    if isinstance(ai_names, list) and ai_names:
        checklist.append({
            "check":   "additional_insured_names",
            "label":   "Additional Insured Names",
            "status":  "info",
            "message": "Additional insured(s) identified: " + ", ".join(str(n) for n in ai_names),
        })

    if rt.get("waiver_of_subrogation_required") is True or flags.get("has_waiver_of_subrogation"):
        checklist.append({
            "check":   "waiver_of_subrogation",
            "label":   "Waiver of Subrogation",
            "status":  "required",
            "message": "WOS endorsement needed - waiver of subrogation requirement detected.",
        })

    if rt.get("primary_noncontributory_required") is True or flags.get("has_primary_noncontributory"):
        checklist.append({
            "check":   "primary_noncontributory",
            "label":   "Primary & Non-Contributory",
            "status":  "required",
            "message": "PNC endorsement needed - primary and non-contributory requirement detected.",
        })

    wording = rt.get("specific_wording_requirements")
    if wording:
        checklist.append({
            "check":   "specific_wording",
            "label":   "Specific Wording Requirements",
            "status":  "advisory",
            "message": f"Specific endorsement wording required: {wording}",
        })

    # Enhanced: Certificate holder / mortgagee / loss payee detection
    if flags.get("has_mortgagee_requirement") or rt.get("mortgagee_names"):
        mortgagee = rt.get("mortgagee_names") or []
        mortgagee_str = ", ".join(str(m) for m in mortgagee) if isinstance(mortgagee, list) else str(mortgagee)
        checklist.append({
            "check":   "mortgagee_clause",
            "label":   "Mortgagee/Lender Clause",
            "status":  "required",
            "message": f"Mortgagee clause required for lender: {mortgagee_str}" if mortgagee_str else "Mortgagee clause required",
        })

    if flags.get("has_loss_payee_requirement") or rt.get("loss_payee_names"):
        loss_payee = rt.get("loss_payee_names") or []
        payee_str = ", ".join(str(p) for p in loss_payee) if isinstance(loss_payee, list) else str(loss_payee)
        checklist.append({
            "check":   "loss_payee_clause",
            "label":   "Loss Payee Clause",
            "status":  "required",
            "message": f"Loss payee clause required for: {payee_str}" if payee_str else "Loss payee clause required",
        })

    # This read `has_certificate_holder_requirement`, which nothing ever wrote,
    # so the item never appeared. A NAMED holder is the requirement - after the
    # merge's party check `certificate_holder` only ever holds a real party.
    cert_holder = _fv(facts, "certificate_holder")
    if cert_holder:
        checklist.append({
            "check":   "certificate_of_insurance",
            "label":   "Certificate of Insurance",
            "status":  "required",
            "message": f"Certificate of Insurance required for: {cert_holder}",
        })

    return checklist


def generate_risk_transfer_enforcement_report(
    checklist: List[dict],
    forms_selected: List[str],
) -> dict:
    """
    Generate enforcement report showing compliance status.
    Shows which risk transfer requirements are satisfied vs pending.

    Returns dict with:
    - satisfied: List of requirements marked as satisfied
    - pending: List of requirements still pending (have status='required')
    - advisory: List of advisory items
    - enforcement_score: Percentage of required items satisfied (0-100)
    """
    satisfied = []
    pending = []
    advisory = []

    for item in checklist:
        status = item.get("status", "advisory")
        if status == "required":
            # Check if this is an ACORD 25 requirement
            if item.get("check") == "additional_insured" and "ACORD_25" in forms_selected:
                satisfied.append(item)
            elif item.get("check") in ("mortgagee_clause", "loss_payee_clause", "certificate_of_insurance"):
                # These require ACORD 25 or 28
                if "ACORD_25" in forms_selected or "ACORD_28" in forms_selected:
                    satisfied.append(item)
                else:
                    pending.append(item)
            else:
                pending.append(item)
        else:
            advisory.append(item)

    enforcement_score = 0
    if satisfied or pending:
        enforcement_score = int((len(satisfied) / (len(satisfied) + len(pending))) * 100)

    return {
        "satisfied_requirements": satisfied,
        "pending_requirements": pending,
        "advisory_items": advisory,
        "enforcement_score": enforcement_score,
        "total_required": len(satisfied) + len(pending),
        "total_satisfied": len(satisfied),
        "summary": (
            f"{len(satisfied)} of {len(satisfied) + len(pending)} required risk transfer requirements satisfied. "
            f"{len(advisory)} advisory items." if (satisfied or pending) else "No risk transfer requirements detected."
        )
    }


# ── Cross-validation ──────────────────────────────────────────────────────────

def cross_validate(facts: dict, flags: dict, selected_form_ids: List[str]) -> List[dict]:
    """Form-specific cross-validation checks."""
    issues: List[dict] = []
    # Rules are keyed by FORM: a form's second copy counts as its form (7 Oct 2026).
    from services.form_instances import base_form_ids as _base_form_ids
    selected_form_ids = _base_form_ids(selected_form_ids or [])

    # Hard only for what Brent's 19 Oct 2026 rule keeps hard (property without
    # its premises, below); a missing name or GL limit is a warning. The two
    # that were hard keep `escalates_acord101`: the form recommender
    # (`form_service`) raises ACORD 101 to Recommended on a hard issue, and a
    # scoring rule must not move the recommender (owner, 8 Oct 2026).
    if not _fv(facts, "applicant_name"):
        issues.append({"type": "warning", "message": "Named insured missing - required on all forms",
                       "escalates_acord101": True})

    fein = _fv(facts, "fein", "")
    if fein and len(str(fein).replace("-", "").replace(" ", "")) not in (9, 0):
        issues.append({"type": "warning", "message": f"FEIN format appears invalid: '{fein}'"})

    if not _fv(facts, "effective_date"):
        issues.append({"type": "warning", "message": "Policy effective date missing"})

    if "ACORD_140" in selected_form_ids and not _fv(facts, "locations"):
        issues.append({"type": "hard_stop", "message": "ACORD 140 selected but no property locations found"})

    if flags.get("has_general_liability"):
        if "ACORD_126" not in selected_form_ids:
            issues.append({"type": "warning", "message": "GL coverage detected - ACORD 126 should be included"})
        _locs = _fv(facts, "gl_class_codes_by_location") or []
        if isinstance(_locs, list) and _locs and not _fv(facts, "operations_description"):
            issues.append({"type": "warning", "message": "GL class codes present but no operations description"})
        if flags.get("is_contractor"):
            pct = _to_percent(_fv(facts, "percent_subcontracted"))
            wc  = _to_float(_fv(facts, "wc_payroll") or _fv(facts, "total_payroll"))
            if pct and pct > 30 and not wc:
                issues.append({"type": "warning", "message": f"High subcontracting ({pct:.0f}%) with no WC payroll"})

    wc_pay  = _to_float(_fv(facts, "wc_payroll"))
    tot_pay = _to_float(_fv(facts, "total_payroll"))
    # NOTE: WC payroll reconciliation is owned by cross_form_validator._check_wc_payroll_reconciliation
    # (gates on ACORD_130 trigger + handles ACORD 186 subcontracting reconciliation).
    # Commented out here to avoid duplicate hard_stops in the soft/hard stop streams.
    # if wc_pay and tot_pay and tot_pay > 0:
    #     diff_pct = abs(wc_pay - tot_pay) / tot_pay
    #     if diff_pct > 0.20:
    #         # Spec: hard stop - WC payroll must reconcile with total payroll
    #         issues.append({"type": "hard_stop", "message": f"WC payroll differs from total payroll by {diff_pct * 100:.0f}% - reconcile or add ACORD 101 explanation"})

    rev = _to_float(_fv(facts, "total_revenue"))
    if rev and tot_pay and tot_pay > 0 and rev > 0:
        ratio = tot_pay / rev
        if ratio > 0.85:
            issues.append({"type": "warning", "message": f"Payroll is {ratio * 100:.0f}% of revenue - unusually high"})
        elif ratio < 0.01:
            issues.append({"type": "warning", "message": f"Payroll is only {ratio * 100:.1f}% of revenue - unusually low; verify revenue and payroll figures"})

    if "ACORD_140" in selected_form_ids:
        if flags.get("property_has_bi_coverage") and not _bi_limit_stated(facts):
            issues.append({"type": "warning", "message": "Business Income coverage detected - BI limit required"})
        if not _fv(facts, "valuation_method"):
            issues.append({"type": "warning", "message": "Property valuation method not specified on ACORD 140"})

    # GL presence mirrors the scorer / state machine (gl_each_occurrence or
    # gl_limits) so a GL limit captured only as the clean per-occurrence scalar is
    # not falsely reported as "GL limits missing" for ACORD 131.
    if "ACORD_131" in selected_form_ids and not _fv(facts, "gl_each_occurrence") and not _fv(facts, "gl_limits"):
        issues.append({"type": "warning", "message": "Umbrella selected but GL limits missing",
                       "escalates_acord101": True})

    # Covered-auto symbols: delegate to the SINGLE implementation in
    # cross_form_validator (2026-08-07). This used to be a second, independent
    # copy of the hired/non-owned symbol rule reading `hired_auto_symbol` /
    # `non_owned_symbol` - two fact keys nothing has ever written - so it fired
    # a warning on EVERY submission with hired/non-owned exposure and docked the
    # Auto pillar for it. Having two copies of one rule is why the defect
    # survived; there is now one.
    if flags.get("has_auto_coverage") and flags.get("auto_has_hired_nonowned"):
        from services.cross_form_validator import _check_auto_hired_nonowned_symbols
        for _iss in _check_auto_hired_nonowned_symbols(facts, flags, {"ACORD_127"}):
            issues.append({"type": "warning", "message": _iss["message"]})

    # NOTE: Location-count reconciliation is owned by cross_form_validator._check_location_address_reconciliation
    # (gates on ACORD_140 trigger which matches the spec wording "ACORD 125 ↔ ACORD 140").
    # Commented out here to avoid duplicate stops in the hard/soft stream.
    # locs_125 = _fv(facts, "locations") or []
    # locs_140 = (_fv(facts, "property_locations") or []) if flags.get("has_property_coverage") else []
    # if isinstance(locs_125, list) and isinstance(locs_140, list):
    #     n, m = len(locs_125), len(locs_140)
    #     if n > 0 and m > 0:
    #         diff = abs(n - m)
    #         if diff == 1:
    #             issues.append({
    #                 "type":      "warning",
    #                 "field":     "location_count",
    #                 "125_count": n,
    #                 "140_count": m,
    #                 "severity":  "warning",
    #                 "message":   "Location count mismatch between application and property schedule (off by 1 - verify)",
    #             })
    #         elif diff > 1:
    #             # Spec: hard stop for > 1 location mismatch
    #             issues.append({
    #                 "type":      "hard_stop",
    #                 "field":     "location_count",
    #                 "125_count": n,
    #                 "140_count": m,
    #                 "severity":  "hard_stop",
    #                 "message":   "Location count mismatch between application and property schedule - must reconcile or add ACORD 101",
    #             })

    # Stamp a durable, content-derived issue_id on every issue so the rail's
    # resolution-status layer can persist a status against it (issue_registry
    # .issue_id_for). Purely additive: keyed off the message text, never consulted
    # by scoring, and never changes the type/message the rest of the pipeline reads.
    from services.issue_registry import issue_id_for
    for _it in issues:
        if isinstance(_it, dict) and not _it.get("issue_id"):
            _it["issue_id"] = issue_id_for(_it.get("message", ""), _it.get("forms"))

    return issues


# Separator between the raw printings inside an [info] equivalence notice.
# `parse_normalization_notice` splits on it, so the two must move together.
# A comma cannot be used: the values contain commas (see `_show_values`).
_INFO_VALUE_SEP = " | "


# ── Cross-document consistency ────────────────────────────────────────────────

def check_doc_consistency(docs: List[dict], confirmed_keys=None) -> List[str]:
    """Check identity field consistency across documents.

    Beta Report §5 (Workstream 2): comparison is NORMALIZATION-AWARE. Values are
    compared by their normalized form so formatting/terminology differences
    (case, punctuation, entity-suffix, date format, address abbreviations) do NOT
    generate hard stops or warnings. Only values that MATERIALLY differ after
    normalization produce an issue. Raw values are preserved in the message so
    they remain visible to the user (§5.1: "Preserve raw values for display").

    ``confirmed_keys`` is the set of fact keys the user has already RESOLVED via
    the Data Consistency picker (underwriting_consistency confirmations). A
    confirmed field is skipped here so its conflict no longer blocks the
    submission — the picker is the resolution path for these fields: the
    applicant_name / fein conflicts are hard stops (60) when two VERIFIED
    documents disagree, warnings (85) when only an unverified source makes the
    difference (21 Oct 2026, `document_tags.is_verified_source`), and the
    effective_date / expiration_date ones are warnings (85) since 19 Oct 2026.
    """
    confirmed_keys = confirmed_keys or set()
    issues: List[str] = []

    # Package context for the equivalence filter, built ONCE and BEFORE the
    # first check that uses it. (Built lower down in the first cut, which meant
    # the identity checks called it before it existed - the exception was
    # swallowed by the fail-open guard and the filter silently never fired. A
    # fix that looks applied and is not is worse than no fix.)
    _pkg_ctx = _build_pkg_context(None, docs)

    # Entity type is read the way every other reader reads it (15 Oct 2026, run
    # 9acec031): `normalization.settle_document_entity_type`, through Submission
    # Integrity's own door - a menu value only as its ticked option, a legal-form
    # designator in the insured's own name over an incompatible reading. The
    # merge settles each stored document in place, but a package stored before
    # that rule (7 Oct) still holds the raw reading, and this warning then read
    # "Corporation, LLC" for an insured named "... LLC" - pointing at a Data
    # Consistency picker that saw agreement and offered nothing to confirm, so
    # the score sat at 85 with no fix anywhere on the screen.
    _entity_type_of = None
    try:
        from services.submission_integrity import _document_entity_type, package_identity_names
        _names = package_identity_names(docs)
        _entity_type_of = lambda d: _document_entity_type(d, _names)  # noqa: E731
    except Exception:                                         # noqa: BLE001
        _entity_type_of = None

    # A heading, a role or a PERSON IN A ROLE names no insured (21 Oct 2026,
    # Brent 17 Oct item 4: "Berger Owner of Choice Electric"). The insured-name
    # door drops it from each document at extraction; it is read here as well,
    # because a document stored before that rule still carries it.
    try:
        from services.normalization import (
            INSURED_NAME_KEYS as _INSURED_KEYS, is_not_a_party_name as _not_insured,
        )
    except Exception:                                         # noqa: BLE001
        _INSURED_KEYS, _not_insured = (), (lambda _v: False)  # noqa: E731
    # VERIFIED SOURCES ONLY (21 Oct 2026, Brent 20 Oct: "only trigger a hard stop
    # when Primble has enough VERIFIED information to know the condition is
    # true"). The ONE definition of a verified source is `document_tags.
    # is_verified_source`; the name / FEIN stop below is hard only when the
    # verified documents disagree among themselves.
    try:
        from services.document_tags import (
            describe_unverified as _describe_unverified,
            is_verified_source as _verified_source, unverified_note as _unverified_note,
        )
    except Exception:                                         # noqa: BLE001
        _verified_source = lambda _d, _k=None: True           # noqa: E731
        _describe_unverified = lambda _d, _k=None: ""         # noqa: E731
        _unverified_note = lambda _descs: ""                  # noqa: E731

    def _names_no_insured(key: str, value: Any) -> bool:
        return key in _INSURED_KEYS and isinstance(value, str) and _not_insured(value)

    def _echo(d: dict, key: str) -> bool:
        held = (d.get("facts") or {}).get(key)
        return isinstance(held, dict) and held.get("echo_of") in ("documents", "loss_run")

    def _stated(key: str) -> List[dict]:
        # Role scope (client 1.2): a document is only read as stating a fact its
        # ROLE covers. See fact_comparison.document_witnesses.
        out = [d for d in docs
               if _fv(d["facts"], key) and _doc_witnesses(d.get("doc_type"), key)
               and not _names_no_insured(key, _fv(d["facts"], key))]
        # A form of OURS printing what the documents stated is those documents
        # speaking again (`echo_of`, the Data Consistency picker's rule since 28
        # Oct 2026) - no second witness while a document that is no echo states
        # the fact. Michelle review, 29 Oct: our own re-uploaded ACORD 126 (its
        # effective date the next term we had calculated) raised "Policy date
        # mismatch" against the outside ACORD 125, with no picker row to fix it.
        if any(not _echo(d, key) for d in out):
            out = [d for d in out if not _echo(d, key)]
        return out

    def _raw(key: str, verified_only: bool = False) -> List:
        stated = [d for d in _stated(key)
                  if not verified_only or _verified_source(d, key)]
        if key == "entity_type" and _entity_type_of is not None:
            return [v for v in (_entity_type_of(d) for d in stated) if v]
        return [_fv(d["facts"], key) for d in stated]

    def _unverified_note_for(key: str, candidates: List) -> str:
        """The note an identity WARNING carries after its sentence: the
        unverified documents behind the difference - each one disagreeing with
        every verified value, or all of them when no verified document states
        the fact. Only values still among `candidates` count."""
        verified_vals = [v for v in _raw(key, verified_only=True) if v in candidates]
        descs = []
        for d in _stated(key):
            v = _fv(d["facts"], key)
            if _verified_source(d, key) or v not in candidates:
                continue
            if verified_vals and not _conflicts(key, list(verified_vals) + [v]):
                continue
            descs.append(_describe_unverified(d, key))
        return _unverified_note(descs)

    def _conflicts(key: str, raw_values: List) -> bool:
        """True when the documents genuinely disagree about ``key``.

        ONE DOOR (V1 plan C1, decision D3): this is `fact_comparison.conflict`,
        the same call the Data Consistency picker makes, so the two surfaces
        cannot disagree - they did, reproduced on the client's literal
        address trio (picker: 0 conflicts; this function: a warning and an 85
        cap), because this function fed RAW strings to a filter the picker fed
        normalised groups. Formatting, containment, code descriptions, prose,
        two printings of one contract and three printings of one address are
        all NOT a conflict; two different entities, amounts, dates or
        identifiers ARE. Applied to EVERY field below, the hard stops included
        - applicant_name used to hard-stop (cap 60) on a mid-word truncation.
        """
        return _fact_conflict(key, raw_values, _pkg_ctx)

    # ── Attribution brackets (client feedback: "which document created the
    # issue... and how to fix it") ────────────────────────────────────────────
    # Appended only to actionable [hard_stop]/[warning] messages - never to
    # [info] (those are already-resolved formatting differences; there is
    # nothing to fix). Every field this function checks is ALSO a Data
    # Consistency reconcilable field except lines_of_business, so the fix path
    # is almost always "confirm it there" - the one real remediation choice is
    # per-field, not per-document, so it is a small fixed lookup rather than a
    # form list: these are core identity fields present on nearly every
    # generated form, and RECONCILABLE_FIELDS itself declares an empty forms
    # list for identity fields for exactly that reason (too universal to name
    # specific ones - see underwriting_consistency.py).
    _DATA_CONSISTENCY_FIX = "Confirm the correct value in the Data Consistency section below."

    def _docs_for(key: str) -> List[str]:
        seen, out = set(), []
        for d in docs:
            if _fv(d["facts"], key) and d.get("filename") not in seen \
                    and not _names_no_insured(key, _fv(d["facts"], key)):
                seen.add(d.get("filename"))
                out.append(d.get("filename") or "an uploaded document")
        return out

    def _bracket(key: str, remediation: str) -> str:
        fns = _docs_for(key)
        src = ", ".join(fns) if fns else "the uploaded documents"
        return f" (Source: {src}. Fix: {remediation})"

    def _show(raw: List) -> str:
        """De-duplicated, human-readable join of the raw values for display.

        Replaces the previous Python set/list repr (e.g. ['Orbin', 'Smith'])
        with a clean comma-separated string so the user-facing message never
        leaks bracket/quote syntax (Beta Report §8.2.7 / P2 #28).
        """
        return ", ".join(_dedup_display(raw))

    def _dedup_display(raw: List) -> List[str]:
        """The de-duplication both display joins share. One copy, on purpose."""
        seen, out = set(), []
        for v in raw:
            s = str(v).strip()
            if s and s.lower() not in seen:
                seen.add(s.lower())
                out.append(s)
        return out

    def _show_values(raw: List) -> str:
        """`_show`, but for the [info] equivalence notices only.

        Same de-duplication; the separator is `_INFO_VALUE_SEP` (" | ").

        A comma cannot separate these: the values themselves contain commas
        ("Orbin Contracting, LLC", and every address), so the client's own
        screenshot reads "Orbin Contracting, LLC, ORBIN CONTRACTING LLC" -
        three commas, two values, and no way to see where one ends. That is
        half of why UI-04 was raised: an equivalence you cannot read is an
        equivalence you cannot check.

        Deliberately NOT applied to the [hard_stop] / [warning] messages. Those
        are hashed into issue_ids, matched by `classify_legacy` and carry stored
        resolution status, so their text must stay byte-identical. An [info] row
        is never an issue, never hashed and never scored, so its display text is
        free to be legible.
        """
        return _INFO_VALUE_SEP.join(_dedup_display(raw))

    # Human labels for the soft-divergence fields so the message reads in plain
    # business language instead of the raw snake_case fact key.
    _FIELD_LABELS = {
        "entity_type":      "Entity type",
        "mailing_address":  "Mailing address",
        "physical_address": "Physical address",
    }

    def _raw_differ(raw_vals: List) -> bool:
        """True when raw values are not all the same string (case-insensitive)."""
        unique = {str(v).strip().lower() for v in raw_vals if v is not None}
        return len(unique) > 1

    applicant_raw = _raw("applicant_name")
    # BRENT RULING 2026-08-24 (Q3a), enforced here too - found on the S6 live
    # run 2026-08-25. A loss run issued to the insured's DECLARED trade name is
    # the same insured, and the loss-run matcher already scores it as a
    # verified match. This checker did not know that, so the same package
    # simultaneously read "Matched on: dba name, fein, policy number" AND
    # "Applicant name differs across documents" - a HARD STOP capping the whole
    # submission at 60 for a name the applicant declared themselves.
    #
    # Drop only values that match a DBA the package's OWN documents state, and
    # only while some other value survives to compare - so a genuinely
    # different third party still conflicts, and a package whose ONLY name is
    # a trade name is left exactly as it was.
    # A value is a TRADE NAME (and so not a rival identity) only when some
    # document declares it as a DBA *and* that same document gives a different
    # legal name for the insured. Both halves are required: a DBA is very often
    # a prefix of the legal name ("Orbin" for "Orbin Contracting LLC"), so
    # matching the DBA alone would drop the legal name itself and silence a
    # genuine conflict - caught by
    # test_doc_consistency_messages_have_no_code_or_list_leak.
    try:
        from services.fact_comparison import is_declared_trade_name
        if len(applicant_raw) > 1:
            _kept = [v for v in applicant_raw
                     if not is_declared_trade_name(v, docs, _pkg_ctx)]
            if _kept:
                applicant_raw = _kept
    except Exception:                                         # noqa: BLE001
        pass
    if "applicant_name" in confirmed_keys:
        pass  # resolved via the Data Consistency picker — no longer a hard stop
    elif _conflicts("applicant_name", applicant_raw):
        _name_sentence = (f"Applicant name differs across documents: {_show(applicant_raw)}"
                          + _bracket("applicant_name", _DATA_CONSISTENCY_FIX))
        # The verified readings, through the same trade-name filter.
        _name_verified = [v for v in _raw("applicant_name", verified_only=True)
                          if v in applicant_raw]
        if _conflicts("applicant_name", _name_verified):
            # Two VERIFIED documents name different companies: a hard stop,
            # byte-identical to before (its card, id and status key off it).
            issues.append("[hard_stop] code=name_conflict " + _name_sentence)
        else:
            # Only an unverified source makes the difference (a narrative, a
            # supporting or unsure-type document, a poor OCR reading): a WARNING
            # to confirm (85). The hard sentence leads, so a card stored as the
            # hard stop renders at this severity (`issue_registry._listed_in`);
            # the note names the unverified document(s).
            issues.append("[warning] code=name_conflict " + _name_sentence
                          + _unverified_note_for("applicant_name", applicant_raw))
    elif len(applicant_raw) >= 2 and _raw_differ(applicant_raw):
        issues.append(
            f"[info] code=name_normalized "
            f"Applicant name: {_show_values(applicant_raw)}"
        )

    # DBA consistency - spec: "DBAs must be consistently represented or explicitly explained"
    dba_raw = _raw("dba_name")
    if "dba_name" not in confirmed_keys and _conflicts("dba_name", dba_raw):
        issues.append(
            "[warning] field=dba_name "
            f"DBA / trade name differs across documents: {_show(dba_raw)}. "
            "Verify or add an ACORD 101 explanation."
            + _bracket("dba_name", _DATA_CONSISTENCY_FIX)
        )

    # Spec: address mapping - compare physical_address across docs too,
    # not just mailing_address, so the distinction between the two is preserved.
    _ADDR_LABELS = {
        "entity_type":      "Entity type",
        "mailing_address":  "Mailing address",
        "physical_address": "Physical address",
    }
    for key in ("entity_type", "mailing_address", "physical_address"):
        if key in confirmed_keys:
            continue  # resolved via the Data Consistency picker
        vals_raw = _raw(key)
        # A COMPONENT is not a competitor. Probe run B: the dec page printed the
        # full street address and the certificate printed "Denver, Colorado" -
        # one is inside the other, and this warning fired alongside the Data
        # Consistency row for the same non-problem (client 2026-08-17 item 1).
        if _conflicts(key, vals_raw):
            issues.append(
                f"[warning] field={key} "
                f"{_FIELD_LABELS[key]} differs across documents: {_show(vals_raw)}"
                + _bracket(key, _DATA_CONSISTENCY_FIX)
            )
        elif len(vals_raw) >= 2 and _raw_differ(vals_raw):
            issues.append(
                f"[info] code={key}_normalized "
                f"{_ADDR_LABELS[key]}: {_show_values(vals_raw)}"
            )

    fein_raw = _raw("fein")
    if "fein" not in confirmed_keys and _conflicts("fein", fein_raw):
        _fein_sentence = (
            "FEIN differs across uploaded documents. Submission Quality Score (SQS) is capped at 60 until this is confirmed."
            + _bracket("fein", _DATA_CONSISTENCY_FIX))
        if _conflicts("fein", _raw("fein", verified_only=True)):
            issues.append("[hard_stop] code=fein_conflict " + _fein_sentence)
        else:
            # Verified sources only (see the applicant name above). The hard
            # sentence leads for the same reason; its "capped at 60" clause is
            # never shown - the screen rewrites it (frontend positiveWording) -
            # and the score holds at 85, a warning's ceiling.
            issues.append("[warning] code=fein_conflict " + _fein_sentence
                          + _unverified_note_for("fein", fein_raw))

    # Spec (L67): misaligned dates → hard stop UNLESS explained.
    # The explanation must specifically address the policy period - a generic
    # ACORD 101 remark about unrelated topics (e.g. loss history, ops) must
    # NOT cancel the date-conflict hard stop. Require a dedicated explanation
    # field, or a remark that explicitly mentions the policy term.
    def _has_date_explanation(d):
        if _fv(d["facts"], "policy_period_explanation"):
            return True
        remarks_lower = _narrative_remarks_text(d["facts"]).lower()
        if not remarks_lower:
            return False
        return any(kw in remarks_lower for kw in (
            "policy period", "policy term", "effective date", "expiration date",
            "renewal date", "extension", "endorsement period",
        ))

    _dates_explained = any(_has_date_explanation(d) for d in docs)

    # ── A multi-policy account has no single policy term (client 2026-08-17) ─
    # "Multiple policy numbers or carriers on a multi-line account should only
    # be treated as conflicting if Primble establishes that they belong to the
    # same policy and coverage context." Dates are the same class and the more
    # damaging one: measured on probe run C (PROBE2 package dec + PROBE4 auto
    # dec, both correct, both with their OWN term), the mismatch fired TWO hard
    # stops and capped a perfectly ordinary two-policy account at 60.
    #
    # This does NOT silence the difference - it DOWNGRADES it to the warning it
    # actually is. The producer still sees it and the picker still resolves it;
    # what stops is calling an ordinary multi-policy structure a blocking error.
    # Gated on POSITIVE evidence of two or more contracts in the verified dec
    # index; a single-contract package is untouched, and so is a package with no
    # index at all.
    _multi_contract = bool(_pkg_ctx and _pkg_ctx.is_multi_contract)
    if _multi_contract and not _dates_explained:
        logger.info(
            "check_doc_consistency: %d contracts evidenced in this package - a "
            "policy-date difference carries the multi-policy note "
            "(each contract carries its own term)", len(_pkg_ctx.contracts))
    # A WARNING since 19 Oct 2026 (Brent: a hard stop only for what is
    # essential; our call - policy dates that differ across documents are
    # confirmed in Data Consistency without stopping the work). Its sentence
    # is unchanged, so its card, code and fix are the ones it always had.
    _date_prefix = "[warning]"
    _date_multi_note = (
        " This package evidences more than one policy, and each policy carries "
        "its own term - confirm which term applies to the submission."
        if _multi_contract and not _dates_explained else "")

    # ── ONE TERM PER COMPARISON (24 Sep 2026) ────────────────────────────────
    # Client 11 Sep item 10: compare "only when they represent the same field,
    # same LOB/policy and applicable time period". Declarations, certificates,
    # binders and endorsements state the CURRENT (expiring) policy's term; an
    # application, supplemental, quote or narrative states the term being
    # APPLIED FOR. Two different periods are not a contradiction - an expiring
    # dec against a new application hard-stopped the package at 60 (v1-20AUG
    # Q33: "Engineering did NOT fix it"). A difference INSIDE either family is
    # still compared exactly as before.
    _PROPOSED_TERM_ROLES = frozenset({
        "application", "supplemental", "quote", "narrative", "acord_form",
        "submission", "proposal"})

    def _conflicts_within_one_term(key: str) -> bool:
        cur, prop = [], []
        for d in _stated(key):
            v = _fv(d["facts"], key)
            if not v:
                continue
            role = str(d.get("doc_type") or "").strip().lower()
            (prop if role in _PROPOSED_TERM_ROLES else cur).append(v)
        return any(len(fam) >= 2 and _conflicts(key, fam) for fam in (cur, prop))

    def _dates_owned_separately(key: str) -> bool:
        """PROOF that the differing dates belong to DIFFERENT contracts.

        Only fires when the index positively attributes both printings to
        disjoint owners; an unattributed value keeps the issue, which is the
        safe direction.
        """
        if not _pkg_ctx:
            return False
        vals = [str(v) for v in _raw(key)]
        return any(_pkg_ctx.different_owners(vals[i], vals[j])
                   for i in range(len(vals)) for j in range(i + 1, len(vals)))

    # Dates are normalized to ISO before comparison so "07/15/25" and
    # "7/15/2025" do NOT trigger a false hard stop (Beta Report §5.2).
    eff_raw = _raw("effective_date")
    if "effective_date" in confirmed_keys:
        pass  # resolved via the Data Consistency picker
    elif _dates_owned_separately("effective_date"):
        pass  # PROVEN to be two contracts' own terms - not a disagreement
    elif _conflicts("effective_date", eff_raw) and _conflicts_within_one_term("effective_date"):
        issues.append(
            f"{_date_prefix} code=date_conflict "
            "Policy date mismatch across documents." + (
                _date_multi_note or
                " Submission Quality Score (SQS) is capped at 60 unless the difference is explained.")
            + _bracket("effective_date", _DATA_CONSISTENCY_FIX + " Or add an ACORD 101 explanation of the date difference.")
        )
    elif len(eff_raw) >= 2 and _raw_differ(eff_raw):
        issues.append(f"[info] code=effective_date_normalized Effective date: {_show_values(eff_raw)}")

    exp_raw = _raw("expiration_date")
    if "expiration_date" in confirmed_keys:
        pass  # resolved via the Data Consistency picker
    elif _dates_owned_separately("expiration_date"):
        pass  # PROVEN to be two contracts' own terms - not a disagreement
    elif _conflicts("expiration_date", exp_raw) and _conflicts_within_one_term("expiration_date"):
        issues.append(
            f"{_date_prefix} code=expiration_conflict "
            "Policy expiration date mismatch across documents." + (
                _date_multi_note or
                " Submission Quality Score (SQS) is capped at 60 unless the difference is explained.")
            + _bracket("expiration_date", _DATA_CONSISTENCY_FIX + " Or add an ACORD 101 explanation of the date difference.")
        )
    elif len(exp_raw) >= 2 and _raw_differ(exp_raw):
        issues.append(f"[info] code=expiration_date_normalized Expiration date: {_show_values(exp_raw)}")

    # Beta Report §5.2: compare lines of business by their NORMALIZED form so
    # terminology differences (CGL vs Commercial General Liability, GL vs General
    # Liability, WC vs Workers Compensation) are treated as equivalent and do not
    # manufacture a warning. Raw values are preserved for the user-facing message.
    lob_norm_sets = []     # normalized tokens — used for comparison
    lob_raw_display = []   # raw tokens — used for display
    lob_doc_names = []     # filenames — used for the attribution bracket
    # Canonicalise each line before comparing. "Commercial Auto" and "Business
    # Auto" are ONE line of business printed two ways; comparing the raw
    # normalized strings made probe run C report them as differing coverage.
    # A line `_canon_line` cannot place keeps its own normalized text as its
    # key, so an unrecognised line is never silently dropped from the compare.
    _cl = _canon_line_leaf

    # SYS-05 (client, 2026-09-01): *"Map these terms into the Commercial
    # Auto/Automobile coverage family BEFORE cross-document comparison."* A
    # coverage PART carries its parent line's identity here, so a dec page
    # listing "Business Auto, Comprehensive, Collision, Uninsured Motorists"
    # and a COI listing "Automobile Liability" are ONE line of business printed
    # at two levels of detail, not two different sets. Placement only - it can
    # never make a document GRANT or DENY a line (that stays `canon_line`), so
    # this can only ever REMOVE a false difference, never manufacture one.
    def _fold(values):
        present = {c for x in values if (c := _cl(x))}
        present |= {c for x in values if (c := _canon_part_leaf(x))}
        out = set()
        for x in values:
            if not (n := normalize_general(x)):
                continue
            out.add(_cl(x) or _canon_part_leaf(x, present) or n)
        return frozenset(out)

    # Each document's CARRIED lines, not its raw mention list (24 Sep 2026).
    # The raw list is every line a document MENTIONS - on the Orbin policy that
    # is the ISO endorsement menus (Farm, Liquor, EPLI, OCP, Pollution ...), so
    # this row expanded to exactly the phantom list the client reported, and a
    # certificate's empty preprinted WC row could turn it into an 85-cap
    # warning. `carried_lines_of_business` is the cover page's own evidence
    # door; a document with no per-line rows (a narrative) keeps its list.
    try:
        from services.lob_canon import carried_lines_of_business as _carried_lines
    except Exception:                                         # noqa: BLE001
        _carried_lines = None
    for d in docs:
        lob = _fv(d["facts"], "lines_of_business")
        if _carried_lines is not None and isinstance(lob, list) and lob:
            try:
                lob = _carried_lines(d["facts"], d.get("flags") or None)
            except Exception:                                 # noqa: BLE001
                pass
        if lob and isinstance(lob, list) and lob:
            norm = _fold(lob)
            if norm:
                lob_norm_sets.append(norm)
                lob_raw_display.append(", ".join(str(x).strip() for x in lob if str(x).strip()))
                lob_doc_names.append(d.get("filename") or "an uploaded document")
    # ── A LOB conflict needs a DENIAL, not just a different list ────────────
    # Client 1.7 acceptance: create a conflict only when two applicable sources
    # "materially disagree about whether coverage exists". Two positive lists
    # can never establish that - a COI certifies selected coverages, a narrative
    # names only relevant lines, an application may name a line placed
    # elsewhere. SILENCE IS NOT DENIAL (Principle 3).
    #
    # The old rule ("each set carries a line the other lacks") called the
    # 2026-08-21 live package a conflict because one document named Professional
    # Liability - a REAL extra policy written by a different carrier, which the
    # package dec has no reason to list. That is more information, not a
    # contradiction.
    #
    # So a conflict now requires POSITIVE EVIDENCE ON BOTH SIDES: one document
    # DENIES a line ("PROPERTY - NO COVERAGE" on its own coverage_lines) while
    # another lists that same line as active. No denial anywhere -> the
    # difference renders as [info], which is exactly what the acceptance
    # criteria ask for.
    # TWO denial witnesses per document, because one alone is too easy to miss:
    #   1. STRUCTURED - a `coverage_lines` entry that does not GRANT the line
    #      (no premium/limit, or a detail that is itself a denial).
    #   2. RAW TEXT - the same scanner `apply_declared_absent_downgrades` uses
    #      (`_lines_declared_absent`), which reads "PROPERTY - NO COVERAGE" off
    #      the page. Without this the check could only fire on packages whose
    #      extraction happened to build a denial entry, which is exactly the
    #      "looks like coverage, never fires" trap.
    _denied_by_doc = []
    for d in docs:
        _denied = set()
        try:
            # EXPLICIT denial only. `not _line_entry_grants_coverage(...)` is
            # NOT a denial - a certificate never prints premiums, so most COI
            # rows fail the grant test while saying nothing about absence. That
            # mistake manufactured this very warning on the live package.
            from services.extraction_service import _line_entry_denies_coverage
            for _e in (_fv(d["facts"], "coverage_lines") or []):
                if not isinstance(_e, dict):
                    continue
                _c = _cl(_e.get("line"))
                if _c and _line_entry_denies_coverage(_e):
                    _denied.add(_c)
        except Exception:                                     # noqa: BLE001
            pass
        try:
            from services.extraction_service import (
                _lines_declared_absent, _FLAG_LINE_WORDS,
            )
            for _flag in _lines_declared_absent(str(d.get("text") or "")):
                for _w in _FLAG_LINE_WORDS.get(_flag, ()):
                    _c = _cl(_w)
                    if _c:
                        _denied.add(_c)
                        break
        except Exception:                                     # noqa: BLE001
            pass
        _denied_by_doc.append(_denied)
    # CROSS-document, and that word is load-bearing (bug in the first cut of
    # this rule, found on the 2026-08-21 live run). A dec page routinely BOTH
    # prints "COMMERCIAL PROPERTY - NO COVERAGE" and lists Commercial Property
    # in the coverage table its own extraction reads - so unioning the denials
    # and the actives matched the document AGAINST ITSELF and the false warning
    # survived the fix meant to remove it. A document contradicting itself is an
    # extraction artefact that `apply_declared_absent_downgrades` already
    # settles; it is not two sources disagreeing.
    #
    # `lob_doc_names` is built alongside lob_norm_sets, so index i of one is the
    # same document as index i of the other. `_denied_by_doc` is keyed by the
    # FULL docs list, so it is re-indexed onto the same footing first.
    _denied_for_lob = []
    _seen_names = []
    for _d, _den in zip(docs, _denied_by_doc):
        _seen_names.append(_d.get("filename") or "an uploaded document")
        _denied_for_lob.append(_den)
    _contradicted = set()
    for _i, _active in enumerate(lob_norm_sets):
        _name_i = lob_doc_names[_i]
        for _j, _den in enumerate(_denied_for_lob):
            if _seen_names[_j] == _name_i:
                continue                      # same document - not a disagreement
            _contradicted |= (_den & _active)
    _lob_disagree = bool(_contradicted)
    if _contradicted:
        logger.info(
            "lines_of_business: %s is DENIED by one document and listed as "
            "active by another - a real coverage contradiction",
            ", ".join(sorted(_contradicted)))
    if ("lines_of_business" not in confirmed_keys and len(lob_norm_sets) >= 2
            and len(set(lob_norm_sets)) > 1 and _lob_disagree):
        _lob_display = "; ".join(lob_raw_display)
        # Not a Data Consistency reconcilable field (no picker exists for it) -
        # the only real fix is checking the source documents directly.
        issues.append(
            "[warning] field=lines_of_business "
            f"Lines of business differ across documents: {_lob_display}"
            f" (Source: {', '.join(dict.fromkeys(lob_doc_names))}. "
            "Fix: Review the source documents and confirm the correct coverage lines.)"
        )
    elif len(lob_raw_display) >= 2 and len({d.strip().lower() for d in lob_raw_display}) > 1:
        issues.append(
            f"[info] code=lob_normalized Coverage terms: {_INFO_VALUE_SEP.join(lob_raw_display)}"
        )

    # NOTE: total_revenue (Gross Sales) cross-doc consistency is now owned by the
    # normalization-aware Core Underwriting Data reconciler
    # (services/underwriting_consistency.py, Beta Report §4.3). The old >10%
    # float-variance heuristic here was superseded - it had no source attribution
    # and no user-confirmation path - so it is intentionally not duplicated.

    return issues


# ── Cross-document issue parsing (single source of truth) ─────────────────────
# check_doc_consistency() returns tagged strings ("[hard_stop] code=x <msg>").
# extraction_pipeline used to parse them inline; the two rescore paths did not
# re-run the detector at all, so its hard stops silently vanished from the cap
# list on every recalculation while their cards stayed on screen. The parser now
# lives here, next to its producer, and every caller uses it - a second copy is
# exactly what let that divergence exist.

_DOC_ISSUE_TOKEN_RE = re.compile(r"^(?:field|code)=(\S+)\s*")


# ── The [info] equivalence notice: ONE parser (client UI-04) ─────────────────
# `check_doc_consistency` tags every equivalence with the rule that produced it
# (`code=effective_date_normalized`). TWO separate parsers then stripped that
# token - the inline one in `extraction_pipeline` and the door below - so the
# category was computed and thrown away one layer before the screen, and the
# Submission Integrity card could only say "treated as equivalent" with no
# reason. Both call this now, so a future change to the wire format cannot fix
# one path and leave the other reading a bare sentence.
#
# The door keeps returning the message STRING - that is its contract, pinned by
# `test_sqs_scoring_fixes_20260816` and consumed as text by `doc_consistency_
# stops`. `extraction_pipeline` takes the whole row, because it is the only
# producer of `normalized_differences`.

# The two [info] codes that are not simply "<fact_key>_normalized". Deliberately
# aliased here rather than renamed at the emitter: the codes are harvested by
# `test_doc_conflict_supersession` and one of them is a literal fixture in
# `test_sqs_scoring_fixes_20260816`, so a rename buys nothing and costs two
# tests.
_INFO_CODE_FACT_ALIASES = {
    "name": "applicant_name",
    "lob":  "lines_of_business",
}


def parse_normalization_notice(issue: str) -> Optional[dict]:
    """Parse one ``[info]`` equivalence line into a structured row.

    ``"[info] code=effective_date_normalized Effective date: 09/23/26 | 9/23/2026"``
    becomes::

        {"code":     "effective_date_normalized",
         "field":    "effective_date",
         "label":    "Effective date",
         "values":   ["09/23/26", "9/23/2026"],
         "category": "Date format",
         "message":  "Effective date: 09/23/26 | 9/23/2026"}

    ``message`` is byte-identical to what this line has always rendered, so a
    caller that only wants the sentence is unaffected.

    Returns None for anything that is not an ``[info]`` line. Fails soft on a
    malformed one: an unrecognised code still yields a row with the generic
    category and the raw text as its label, because a missing row on screen is
    worse than a vaguely-labelled one.
    """
    if not isinstance(issue, str) or not issue.startswith("[info]"):
        return None

    rest = issue[len("[info]"):].strip()
    m = _DOC_ISSUE_TOKEN_RE.match(rest)
    code = m.group(1) if m else ""
    message = _DOC_ISSUE_TOKEN_RE.sub("", rest)

    # code -> fact key. "effective_date_normalized" -> "effective_date".
    stem = code[:-len("_normalized")] if code.endswith("_normalized") else code
    field = _INFO_CODE_FACT_ALIASES.get(stem, stem)

    # "Label: value | value" -> label + values. Split on the FIRST colon only:
    # a value can contain one (a time, a ratio), a label never does.
    label, sep, tail = message.partition(":")
    if not sep:
        label, tail = "", message
    values = [v.strip() for v in tail.split(_INFO_VALUE_SEP) if v.strip()]

    try:
        from services.normalization import equivalence_category
        category = equivalence_category(field)
    except Exception:                                          # noqa: BLE001
        # Never let a labelling failure cost the user the row itself.
        logger.warning("equivalence_category failed for %r", field, exc_info=True)
        category = ""

    return {
        "code":     code,
        "field":    field,
        "label":    label.strip(),
        "values":   values,
        "category": category,
        "message":  message,
    }


def split_doc_consistency_issues(
    issues: List[str],
) -> Tuple[List[str], List[str], List[str], List[dict]]:
    """Split check_doc_consistency() output into its four severities.

    Returns (hard_msgs, soft_msgs, info_msgs, doc_conflicts) where the message
    strings have had their machine token stripped exactly as extraction_pipeline
    has always stripped it - the text must stay byte-identical or issue_id
    hashing, dedupe and stored resolution status all stop matching.
    """
    hard: List[str] = []
    soft: List[str] = []
    info: List[str] = []
    conflicts: List[dict] = []

    for issue in issues or []:
        if issue.startswith("[hard_stop]"):
            rest = issue[len("[hard_stop]"):].strip()
            code_part, _, msg = rest.partition(" ")
            code = code_part.split("=", 1)[1] if "=" in code_part else "conflict"
            conflicts.append({"code": code, "message": msg, "hard_stop": True})
            hard.append(msg)
        elif issue.startswith("[warning]"):
            rest = issue[len("[warning]"):].strip()
            _m = _DOC_ISSUE_TOKEN_RE.match(rest)
            code = _m.group(1) if _m else "conflict"
            soft.append(_DOC_ISSUE_TOKEN_RE.sub("", rest))
            conflicts.append({"code": code, "message": soft[-1], "hard_stop": False})
        elif issue.startswith("[info]"):
            # One parser (see parse_normalization_notice). This door's contract
            # is the message string, so it takes only that half of the row.
            _row = parse_normalization_notice(issue)
            if _row is not None:
                info.append(_row["message"])
        else:
            # Unknown prefix - treat as a warning so it can never silently cap at 60.
            soft.append(issue)

    return hard, soft, info, conflicts


def doc_consistency_stops(session_data: dict, with_conflicts: bool = False):
    """Re-run the cross-document identity checks against a STORED session.

    The rescore paths rebuild `hard_stops` from scratch; without this they drop
    the applicant-name / FEIN / effective-date / expiration-date conflicts while
    the submission is still in conflict (name / FEIN block Submission Ready; the
    dates are warnings since 19 Oct 2026). Values already confirmed in the Data
    Consistency picker are excluded, matching the extraction path.

    Fails open (returns empty lists) - a rescore must never break because a
    legacy session stored its documents in an older shape.

    `with_conflicts`: also the run's conflicts (`[{code, message, hard_stop}]`)
    - the review screen finds each one's Data Consistency row by them.
    """
    try:
        docs = [
            d for d in ((session_data or {}).get("docs") or [])
            if isinstance(d, dict) and not d.get("excluded") and isinstance(d.get("facts"), dict)
        ]
        if len(docs) < 2:
            return ([], [], []) if with_conflicts else ([], [])   # nothing to compare against
        # The extraction path passes the BASE key of every confirmation
        # (`parse_confirmation_key`), so a line-scoped answer ("effective_date
        # @auto") settles its comparison there. This path read the raw keys, and
        # the same confirmation stopped counting on the first rescore (5 Oct).
        from services.underwriting_consistency import confirmed_fact_keys
        from services.issue_registry import person_settled_keys
        confirmed = set(confirmed_fact_keys(
            (session_data or {}).get("underwriting_confirmations") or {}))
        # A warning field a person typed is settled (15 Oct 2026).
        confirmed |= person_settled_keys((session_data or {}).get("facts"))
        hard, soft, _info, _conf = split_doc_consistency_issues(
            check_doc_consistency(docs, confirmed)
        )
        # A difference a saved explanation answered no longer counts (15 Oct 2026).
        from services.issue_registry import explained_doc_conflict_codes
        _explained = explained_doc_conflict_codes((session_data or {}).get("facts"))
        if _explained:
            # Either severity's card answers it: an explanation saved while the
            # conflict was a hard stop still counts now it is a warning (19 Oct).
            _gone = {c["message"] for c in _conf
                     if any(f"doc_conflict_{sev}_{c.get('code')}" in _explained
                            for sev in ("hard", "warn"))}
            hard = [m for m in hard if m not in _gone]
            soft = [m for m in soft if m not in _gone]
            _conf = [c for c in _conf if c["message"] not in _gone]
        return (hard, soft, _conf) if with_conflicts else (hard, soft)
    except Exception as exc:                                   # pragma: no cover
        logger.error("doc_consistency_stops failed (non-fatal): %s", exc, exc_info=True)
        return ([], [], []) if with_conflicts else ([], [])


def doc_consistency_normalizations(session_data: dict) -> List[dict]:
    """The `[info]` equivalence rows, recomputed from a STORED session.

    `/extraction-result` restores a session after a browser refresh and its own
    docstring says it returns "the same shape as the synchronous upload
    response". It did not: `normalized_differences` was only ever built on the
    upload path, so pressing F5 emptied the Submission Integrity card's
    "Resolved formatting difference" block AND dropped its chip (the severity
    is derived from the list being non-empty). Nothing was wrong with the data
    - the server simply was never asked to work it out again.

    Deterministic and cheap: string comparison over facts we already hold. No
    LLM, no I/O, nothing persisted.

    Mirrors the UPLOAD path (`extraction_pipeline`), not its sibling
    `doc_consistency_stops`, because the contract being fixed is "a refresh
    shows what the upload showed":
      * `excluded` docs are dropped, falling back to all of them if that would
        leave nothing - `active_docs`' own rule;
      * confirmations are reduced with `parse_confirmation_key`, so a
        LINE-scoped resolution (`effective_date@auto`, SYS-06) still counts and
        a fact the producer already settled does not reappear as an
        equivalence row.

    Fails open to `[]`, which is exactly what this endpoint returned before, so
    the worst case of this function is the behaviour it replaces.
    """
    try:
        raw_docs = [d for d in ((session_data or {}).get("docs") or [])
                    if isinstance(d, dict)]
        # A doc with no facts dict cannot witness anything and would raise
        # inside check_doc_consistency; dropping it can only ever remove a
        # crash, never a row.
        raw_docs = [d for d in raw_docs if isinstance(d.get("facts"), dict)]
        docs = [d for d in raw_docs if not d.get("excluded")] or raw_docs
        if len(docs) < 2:
            return []                  # nothing to compare against
        try:
            from services.underwriting_consistency import confirmed_fact_keys
            confirmed = confirmed_fact_keys(
                (session_data or {}).get("underwriting_confirmations") or {})
        except Exception:                                      # noqa: BLE001
            confirmed = set(((session_data or {}).get("underwriting_confirmations") or {}).keys())

        rows = []
        for issue in check_doc_consistency(docs, confirmed):
            row = parse_normalization_notice(issue)   # None for non-[info]
            if row is not None:
                rows.append(row)
        return rows
    except Exception as exc:                                   # pragma: no cover
        logger.error("doc_consistency_normalizations failed (non-fatal): %s",
                     exc, exc_info=True)
        return []


# ── Confidence-weighted fill rate ────────────────────────────────────────────

CONFIDENCE_SCORE = {
    # ── THE WEIGHTS ARE OURS, NOT THE CLIENT'S ──────────────────────────────
    # The comment here used to read "per spec (producer=1.00, AI-high=0.85,
    # AI-low=0.50)". That attribution is FALSE, corrected 2026-08-24
    # (v1-20AUG.md C1-R / C1-S): `SQS_Scoring_Specification.docx.pdf` was
    # extracted in full and searched - "0.85" and "0.50" appear ZERO times. The
    # spec mandates only that the fill rate be "confidence-weighted" and never
    # sets a weight. These are engineering defaults awaiting Brent's ruling
    # (Q9). Do not defend them as a client decision.
    #
    # ── EVERY LABEL pdf_service / form_routes EMITS MUST BE A KEY HERE ──────
    # `confidence_fill_rate` does `CONFIDENCE_SCORE.get(label, 0.0)`, so a
    # label missing from this table silently scores ZERO. That is exactly what
    # happened to "ai_verified" from the day the raw-text verification shipped
    # until 2026-08-24: an AI value CONFIRMED present in the uploaded document
    # (painted pink "AI-OK" on the form) scored 0.00 while an UNVERIFIED guess
    # scored 0.50 - verification made the score worse. Measured: a form of ten
    # document-verified AI fields reported a 0% fill rate. Fill rate is 35% of
    # Structural Completeness (25% of the package), so every submission since
    # that label shipped has scored low. `tests/test_confidence_score_covers_
    # every_label.py` now harvests every assigned label from the source and
    # fails the build if one is missing here.
    #
    # Producer-entered / deterministic (Pass 1, alias stamp) fills.
    "deterministic":    1.00,    # not emitted per field today; kept for fact-level callers
    "filled":           1.00,    # the label pdf_service actually emits for deterministic fills
    "client_arq":       1.00,    # producer-/client-supplied via ARQ (form_routes)
    # A value the PRODUCER supplied: a schedule saved from the producer's table
    # (`save_session_schedule`) and, since 29 Sep, an answer typed on a card
    # (`apply_producer_answer_to_session`). It had no weight, so every such box
    # scored 0.00 in the fill rate - the ai_verified defect again, missed
    # because the anti-rot harvest did not read arq_service (it does now).
    "producer":         1.00,
    # AI-mapped fills. The verification split is pdf_service's own contract:
    #   found word-for-word in the documents -> "ai_verified"   (pink,   AI-OK)
    #   NOT found - a guess, or a claim we
    #   could not locate                     -> "low_confidence" (orange, verify)
    # "ai_verified" takes the AI-high slot: it is the highest confidence the
    # AI path can reach - the value is on the page - but it was still placed
    # by the model, not read deterministically, so it is not 1.00. BRENT
    # CONFIRMED 1.00 / 0.85 / 0.50 on 24 Aug 2026 ("Those assignments will do
    # for now"). A 13 Oct change to 1.00 was reverted the same day (owner: "we
    # need to go with Brent's one"). The package still reaches 100 after forms:
    # an "ai_verified" box is a Please verify row with Confirm
    # (`needs_attention.CONFIRMABLE_LABELS`), and a confirmed value is "producer".
    "ai_verified":      0.85,
    "ai_high":          0.85,    # fact-level label (extraction); never a field label today
    "ai_low":           0.50,    # fact-level label (extraction); never a field label today
    "low_confidence":   0.50,    # the field label pdf_service actually emits for unverified AI
    # ── C3 3.8 (2026-08-25). Written by pdf_service.apply_fact_state_
    # confidence_labels, which reads each box back to its SOURCE FACT. ───────
    # A recorded Explicit No is a COMPLETED response, not an empty box - the
    # client's own wording. It scores like any other answered fact.
    "explicit_no":      1.00,
    # A value the documents still disagree about STAMPS (Brent Q4 / D16) but
    # must not read as fully complete. Half credit: present and usable, not
    # settled. This number is OURS, like the 0.85 / 0.50 above - 3.8 says
    # "should not receive full completed-field credit" and sets no figure.
    "conflicted":       0.50,
    # Empty / required-but-missing fields contribute nothing. Both gate labels
    # are listed EXPLICITLY so that 0.00 is a decision, not a `.get` default.
    "missing_required":      0.00,
    "missing_required_gate": 0.00,   # ACORD 125/126 "started row" sibling gate
    None:                    0.00,
}

# C3 3.8: *"Not Applicable fields must not reduce fill rate."* Not a zero
# weight - an EXCLUSION. A zero would still sit in the denominator and drag the
# average down, which is the defect this closes rather than a fix for it.
# Deliberately NOT a key in CONFIDENCE_SCORE: the label never reaches the
# weighted sum, and giving it a weight there would invite someone to "simplify"
# the exclusion away.
FILL_RATE_EXCLUDED_LABELS = frozenset({"not_applicable"})


def confidence_fill_rate(mapped_data: dict, confidence_dict: dict) -> int:
    """Calculate confidence-weighted fill rate.

    The SPEC's requirement is only that this be "confidence-weighted"; the
    weights themselves (producer-edits=1.00, AI-high=0.85, AI-low=0.50) are an
    ENGINEERING DEFAULT, not a client decision - see the note on
    ``CONFIDENCE_SCORE``. Denominator is the count of *filled* fields so the
    score reflects the average confidence of what was filled, not how big the
    template happens to be. C3 3.8 keeps that design deliberately - *"Do not
    redesign the full confidence-weighting algorithm in this V1 pass"* - and
    changes only which fields COUNT:

      * Not Applicable  - excluded outright, numerator and denominator.
        Measured before this: one good field scored 100, and the same form plus
        one box holding the literal ``"N/A"`` scored 75.
      * Explicit No     - counted as filled. Measured before this: a box
        holding ``"None"`` scored 0, because the emptiness test below treats
        that string as empty. The LABEL is what rescues it, never the string,
        so a stringified Python ``None`` is still not credited.
      * Conflicting     - counted, at the reduced ``conflicted`` weight.
    """
    filled_items = []
    for field, val in mapped_data.items():
        label = confidence_dict.get(field)
        if label in FILL_RATE_EXCLUDED_LABELS:
            continue                       # 3.8: cannot reduce the fill rate
        if label == "explicit_no":
            filled_items.append(field)     # 3.8: a valid completed response
            continue
        # "Off" is an unticked checkbox's state - an empty box, not a value
        # (13 Oct 2026: four stored ACORD 125s counted it as a filled box at
        # zero weight, so the fill rate could never reach 100).
        if val is not None and str(val).strip() not in ("", "null", "None", "Off", "/Off"):
            filled_items.append(field)
    filled_count = len(filled_items)
    if filled_count == 0:
        return 0

    weighted = sum(
        CONFIDENCE_SCORE.get(confidence_dict.get(field), 0.0)
        for field in filled_items
    )
    # ── THE FLOOR IS DELIBERATE; THE FLOAT ERROR IS NOT (2026-09-23) ─────────
    # This was `int(... * 100)`. Truncating a genuine 86.4 to 86 is a defensible
    # choice and is preserved. Truncating a value whose EXACT arithmetic result
    # is 87 down to 86, because binary floating point represents it as
    # 86.99999999999999, is not - it is the same number arriving one lower for
    # no reason a broker could ever be shown.
    #
    # Measured over every label multiset up to n=12 (CONFIDENCE_SCORE has
    # twelve labels): 32,912 multisets have a whole-number exact value that
    # `int()` returned one below. CLAUDE.md's own example reproduces - three
    # `deterministic` plus `ai_high` plus `ai_low` is exactly 87 and returned 86.
    #
    # Rounding to nine places first collapses ONLY the representation error,
    # then the original floor runs unchanged. Deliberately NOT a bare `round()`:
    # that would also flip the 149,065 multisets whose exact value ends in .5
    # from floor to round-half-up, which is a semantic change to the metric
    # nobody has asked for and which moves far more scores than the defect does.
    #
    # `confidence_fill_rate` feeds the per-form Structural pillar, the package's
    # Form Fill Quality component and the questionnaire's fill-rate deltas, so
    # SCORES MOVE UP by one point wherever a submission lands on such a
    # boundary. Nothing moves down. D6 - Brent sees the numbers.
    return int(round((weighted / filled_count) * 100, 9))


# ── Loss history integrity coefficient ───────────────────────────────────────

def loss_integrity_coefficient(
    loss_history_years: int,
    report_age_days: int,
    required_window: int = 5
) -> float:
    """
    90-day grace period: reports < 90 days old score full recency.
    After 90 days, recency decays linearly to 0 at 365 days.
    """
    years_ratio   = min((loss_history_years or 0) / required_window, 1.0)
    recency_ratio = max(0.0, 1.0 - max(0, report_age_days - 90) / 275)
    return round(years_ratio * recency_ratio, 3)


# ── Deterministic loss-run dating & conflict (§6.4 Q3) ───────────────────────

def _parse_iso_date(value) -> Optional[datetime]:
    """Parse a loosely-formatted date via the shared normalizer; None if unparseable."""
    iso = normalize_date(value)
    if not iso:
        return None
    try:
        return datetime.strptime(iso, "%Y-%m-%d")
    except ValueError:
        return None


def _loss_run_age_days(facts: dict) -> Optional[int]:
    """Resolve loss-run age in days - deterministic and evidence-based:

      1. (today - 'valued as of' date) when a parseable valuation date was
         extracted from the loss run. This is the authoritative value.
      2. else an explicit, parseable loss_run_age_days the model stated.
      3. else None - age is UNVERIFIED. Callers must NOT assume a value. The old
         "default 365" punished every loss run whose date the model failed to
         state and printed a fabricated "365 days old" warning (§6.4 / Beta 2).
    """
    valued = _parse_iso_date(_fv(facts, "loss_run_valuation_date"))
    if valued is not None:
        age = (datetime.now(timezone.utc).date() - valued.date()).days
        return age if age >= 0 else None   # future date = mis-extraction; don't trust it
    stated = _to_int(_fv(facts, "loss_run_age_days"))
    if stated is not None and stated >= 0:
        return stated
    return None


def _resolve_loss_history_years(facts: dict) -> int:
    """Years of loss history. Deterministic from the loss-run experience period
    (start -> 'valued as of' / period end) when both dates were extracted, so the
    full/partial/incomplete tier no longer rests solely on a model-stated count
    that can miscount (§6.4 Q3 secondary). Clamped to [1, 10] so a single stray
    date cannot inflate the tier. Falls back to the model's count otherwise.
    """
    # One date reader with the coverage label (a bare year is that whole year -
    # live 85e51d02, 25 Oct): `loss_history_state.loss_period_date`.
    from datetime import datetime as _dt
    from services.loss_history_state import loss_period_date as _lpd
    _s = _lpd(facts.get("loss_run_period_start"))
    _e = (_lpd(facts.get("loss_run_period_end"), end=True)
          or _lpd(facts.get("loss_run_valuation_date")))
    start = _dt(_s.year, _s.month, _s.day) if _s else None
    end = _dt(_e.year, _e.month, _e.day) if _e else None
    if start is not None and end is not None and end >= start:
        # Only the years inside the last min(5, age) years count (owner,
        # 24 Oct 2026, Z38 lane E): a 2019-2021 run alone covers nothing now.
        try:
            from services.loss_history_state import years_inside_window
            inside = years_inside_window(start.date(), end.date(), facts)
        except Exception:                                      # noqa: BLE001
            inside = None
        if inside is not None:
            return inside
        return max(1, min(round((end - start).days / 365.25), 10))
    return _to_int(_fv(facts, "loss_history_years")) or 0


def _loss_history_conflict(facts: dict, flags: dict,
                           has_loss_run_doc: bool = False) -> bool:
    """True when a no-loss attestation (user or narrative) is contradicted by
    ACTUAL loss-run claims (§6.4 item 1 'conflicting').

    Single source of truth shared by the P4 score and the state label so the two
    can never disagree. Note: years of loss history alone do NOT contradict a
    no-loss attestation (a clean multi-year loss run CONFIRMS it) - only real
    claims / incurred amounts do.

    THE WORD "ACTUAL" IS NOW ENFORCED (2026-09-05). This docstring has said
    "loss-run claims" since it shipped, and the code never checked a loss run
    existed - so a claim count the extraction model INVENTED was enough. Live
    run, nine sessions of nine: every clean package printed *"Conflicting -
    attested no losses but loss runs show claims"* with no loss run anywhere and
    a narrative reading *"no prior losses or claims in the last five years"*.
    `num_claims` / `total_incurred` reach the extraction schema as bare
    `string or null` with no guiding rule, so the model can return a figure read
    off a premium or a limit.

    `loss_history_state.claims_are_corroborated` is the gate: a loss-run
    document, a typed claims row, or human provenance on the scalar. The V1
    BETA EXIT (2026-08-28) path - *"attested no losses + one TYPED claim row"*
    with no loss run uploaded - still raises the conflict, because a typed row
    IS corroboration.

    `has_loss_run_doc` defaults False so every existing caller keeps compiling;
    callers that know the answer pass it, and the typed-row / provenance routes
    cover the rest.

    A PERSON'S "WE HAVE HAD CLAIMS" SETTLES IT (23 Oct 2026, the Loss History
    plan): the answer agrees with the claims, so no no-loss statement anyone
    still stands behind is left to contradict them - a stale flag, or a
    narrative's sentence the answer cannot delete from its document. Without
    this a narrative-sourced conflict could never be answered away, and the
    plan's first step (the conflict card's own answer) would leave Loss
    History held at 45.
    """
    try:
        from services.loss_history_state import had_claims_answer
        if had_claims_answer(facts):
            return False
    except Exception:                                          # noqa: BLE001
        pass
    # V1 BETA EXIT (2026-08-28) - through the ONE door
    # (`loss_history_state.asserted_claims`), which also reads the client's own
    # `loss_history` claims TABLE. Reading the two scalars alone meant a claim
    # the insured or the producer TYPED contradicted nothing: measured, an
    # attestation plus one typed claim row scored 60 with no conflict, while the
    # same claim entered as `num_claims=1` scored 45 and raised one. Nothing
    # derives `num_claims` from those rows - extraction only counts claims out
    # of loss-run text - so the more explicit evidence was the invisible one.
    # SCORES GO DOWN where a typed claim contradicts an attestation - D6.
    try:
        from services.loss_history_state import asserted_claims
        claims, incurred = asserted_claims(facts)
    except Exception:                                   # noqa: BLE001
        # Fail to the PRIOR behaviour, never to silence: the conflict ceiling
        # is what keeps a contradicted attestation visible.
        claims   = _to_int(_fv(facts, "num_claims")) or 0
        incurred = _to_float(_fv(facts, "total_incurred")) or 0.0
    no_loss = (
        bool(flags.get("no_prior_losses"))
        or bool(flags.get("narrative_states_no_losses"))
        or _attested_true(_fv(facts, "no_prior_losses"))
        or _attested_true(_fv(facts, "loss_history_no_prior_losses_indicator"))
    )
    if not (no_loss and (claims > 0 or incurred > 0)):
        return False
    # The gate. Fails toward NO conflict: a warning that fires on every clean
    # submission is one producers learn to ignore, and nothing here deletes a
    # value - the claim count survives, it simply stops contradicting an
    # attestation it was never evidenced against.
    try:
        from services.loss_history_state import claims_are_corroborated
    except Exception:                                          # noqa: BLE001
        return True            # no door -> pre-2026-09-05 behaviour, never silence
    if claims_are_corroborated(facts, has_loss_run_doc):
        return True
    logger.info(
        "loss-history conflict suppressed: a no-loss attestation is "
        "contradicted only by an uncorroborated model-extracted claim figure "
        "(claims=%s incurred=%s, no loss-run document, no typed claim row)",
        claims, incurred,
    )
    return False


def _recency_penalty(age_days: int) -> int:
    """Loss-run recency reduction - client C2 2.3 stepped bands (2026-08-24).

    0-90 days = 0 | 91-180 = 10 | 181-365 = 20 flat | >365 = 25 (cap).
    The 181-365 band was previously a 15->20 ramp (older spec's "-15 rising to
    -20"); the C2 revision fixes it at -20. Shared by the doc-only and
    year-tier paths so the two can never diverge.
    """
    if age_days <= _LOSS_RECENCY_DAYS:            # <= 90: currently valued, no deduction
        return 0
    if age_days <= 180:                           # 91-180
        return 10
    if age_days <= 365:                           # 181-365: flat 20 (client C2 2.3)
        return 20
    return _LOSS_RECENCY_MAX_PEN                   # > 365: 25 cap


# Which fact a loss-history recommendation actually needs, per message.
#
# WHY THIS EXISTS: every loss recommendation used to be stamped with one
# hardcoded field, `loss_history_years`. So the card that asks the producer to
# CONFIRM No Known Losses posted the answer into "how many years of loss runs do
# you have". Measured on a live session 2026-08-17: the producer typed
# "no losses", it was stored as a year count, `_to_int` read it as 0, the pillar
# fell through to "No loss history provided" (25), the card came straight back
# and the score never moved. The answer was correct; it was delivered to the
# wrong field. `_attested_true("no losses")` is True - had it reached
# `loss_history_no_prior_losses_indicator` the pillar would have gone 45 -> 60.
#
# First match wins, tested against the LOWERCASED message. `None` means no
# single fact can answer it - the gap needs a document or a reconciliation - and
# the UI already falls back to dismiss-with-reason when a rec carries no field
# (`answerable = !!rec.field` in AcordModal), which is the honest affordance.
#
# Matched on the message TEMPLATE, the same identity `_loss_rec_id` already
# derives, so a varying number ("372 days old") cannot fork a row. Keep this
# table beside the messages it maps: `test_every_loss_message_maps_to_a_field`
# harvests every string `calculate_p4_loss_history` can emit and fails the build
# if one lands here unmapped.
_LOSS_RECOMMENDATION_FIELDS: Tuple[Tuple[str, Optional[str]], ...] = (
    # The attestation states. THIS is the pair the pillar actually reads.
    ("no known losses (stated in narrative)",           "loss_history_no_prior_losses_indicator"),
    ("no loss history provided",                        "loss_history_no_prior_losses_indicator"),
    # Already attested - only a document can raise it further. Still emitted
    # when the attestation is scored (a stale flag beside a "we have had
    # claims" answer, or corroborated claims under the 45 conflict ceiling).
    ("no known losses (attested by user)",              None),
    # Owner 29 Sep 2026 (Orbin item 15): the attestation took the pillar out of
    # the score. Informational - nothing to fill, nothing to earn. Worded
    # "Unable to Verify / Confirmation Required" since 23 Oct 2026 (Brent); the
    # old wording stays listed so a stored card still routes nowhere.
    ("no known losses attested - loss history is unable to verify", None),
    ("no known losses attested - loss history is not applicable", None),
    # Identity of the runs: whose are they, and do the identifiers line up.
    ("loss run insured name does not match",            "applicant_name"),
    # The producer's ownership answer (23 Oct 2026, fc04c74f): these used to
    # route to `fein` - the PACKAGE FEIN, already filled, while the RUN's own
    # tax ID cannot be typed - so the row measured 0 and nothing could lift it.
    ("loss run ownership partially verified",           "loss_run_ownership_confirmed"),
    ("loss run ownership could not be fully verified",  "loss_run_ownership_confirmed"),
    # The carrier is a fact the producer knows off the top of their head.
    ("prior carrier name missing",                      "prior_carrier"),
    # Genuinely about a count of years - the original field, correctly used.
    ("3 years of loss runs provided",                   "loss_history_years"),
    ("loss history incomplete",                         "loss_history_years"),
    ("loss runs uploaded",                              "loss_history_years"),
    # Waiting on paper, or contradicted by it. No typed value closes these.
    ("loss runs requested / pending",                   None),
    ("loss runs appear stale",                          None),
    ("loss run valuation date",                         None),   # not a writable canonical fact
    ("loss history conflict",                           None),
    # C2 (2026-08-24): new venture, availability and advisory rows.
    ("new venture status conflicts",                    None),
    ("new venture confirmed",                           None),
    ("confirm new venture status",                      "new_venture_indicator"),
    ("claim years are not readable",                    "loss_history_years"),
    ("prior claims are known",                          "loss_run_status"),
    ("no loss runs are available",                      None),
    ("underwriting advisory",                           None),
)


# ── Answer routing for recommendation cards ──────────────────────────────────
def _cap_stop_items(messages, coded_issues=None, facts=None):
    """Turn cap-gate sentences into rows the panel can act on.

    Same shape `issue_registry` builds for every other stop - message, rule
    code, resolution descriptor - so the frontend renders one control, not two.

    TWO SOURCES OF IDENTITY, in order, because a cap reason can come from either
    engine and only one of them is a plain string:

      1. An ALREADY-CODED issue carrying the same sentence. The cross-form
         validator emits `bi_missing_period_of_restoration` etc. with its code
         attached; `classify_legacy` has no row for those wordings and never
         will, since they are not legacy messages. Matching the sentence back to
         the issue that produced it inherits the real code - the same idea
         `cap_hard_stop_codes`' promote path already uses one layer up.
      2. `classify_legacy`, for the legacy-engine and cap-gate sentences.

    Best-effort: a classification failure must never cost the producer the
    sentence itself, so the row degrades to text rather than disappearing.
    """
    coded = []
    for issue in (coded_issues or []):
        if not isinstance(issue, dict):
            continue
        msg = str(issue.get("message") or "").strip()
        code = issue.get("code")
        if msg and code:
            coded.append((msg, code, issue.get("forms") or []))

    def _match(reason: str):
        """The coded issue this cap reason came from, or None.

        PREFIX, not equality. `cross_form_validator` appends an
        "(Affects: ACORD 140. Fix: ...)" annotation to some messages AFTER the
        issue itself was captured, so the stop list carries the long string
        while the issue carries the short one. Byte-exact matching found nothing
        and the red box lost its "Open to fix" - reported live 2026-09-08.
        `issue_registry._present_in` has handled this since it was written; this
        follows the same rule rather than inventing a second one.
        """
        reason = str(reason or "").strip()
        for msg, code, forms in coded:
            if reason == msg or reason.startswith(msg) or msg.startswith(reason):
                return code, forms
        return None

    out = []
    for msg in (messages or []):
        code, forms, resolution = None, [], None
        try:
            from services.issue_registry import classify_legacy, resolution_for
            hit = _match(msg)
            if hit:
                code, forms = hit
            else:
                code, _cluster, _tier = classify_legacy(msg, "hard_stop")
            resolution = resolution_for(code)
            # A COPE card on a 2+ building package opens the location table, as
            # on the pre-form banners (`premises_cope`, Choice Electric #18).
            if isinstance(facts, dict) and facts:
                from services.premises_cope import route_cope_resolution
                resolution = route_cope_resolution(code, resolution, facts)
        except Exception as _cx:                               # noqa: BLE001
            logger.warning(f"cap stop not classified: {_cx}")
        out.append({"message": msg, "code": code, "resolution": resolution,
                    "severity": "hard_stop", "forms": list(forms)})
    return out


def _gap_rows(pillar: str, score: float, items: List[dict], eff_weight: float) -> List[dict]:
    """Best Solutions rows for one pillar's gap items (13 Oct 2026): a row per
    item a box answers - its label, its fact, what it is worth in package
    points - largest first, then ONE row for the items no box answers (a
    coverage decision, or the cross-form checks, whose cards carry the fix).
    The rows' `points_available` add up to the pillar's gap."""
    rows: List[dict] = []
    seen: Dict[str, dict] = {}
    for it in sorted((i for i in items if i.get("fact")), key=lambda i: -int(i.get("points") or 0)):
        fact = str(it["fact"])
        pts = int(it.get("points") or 0)
        if fact in seen:                    # two deductions, one box: one row
            seen[fact]["points_available"] = round(seen[fact]["points_available"] + pts * eff_weight, 1)
            seen[fact]["missing"].append(it.get("label") or fact)
            continue
        # `row_action`: the words for a row whose items share one box and are
        # better named together (the claims - one loss table, every claim).
        row = {"pillar": pillar, "score": score,
               "action": it.get("row_action") or it.get("label") or fact,
               "missing": [it.get("label") or fact], "field": fact,
               "points_available": round(pts * eff_weight, 1), "closes_with": "type"}
        if it.get("also_facts"):
            row["also_facts"] = list(it["also_facts"])
        seen[fact] = row
        rows.append(row)
    rest = [i for i in items if not i.get("fact")]
    if rest:
        pts = sum(int(i.get("points") or 0) for i in rest)
        labels = [str(i.get("label") or "") for i in rest if i.get("label")]
        rows.append({"pillar": pillar, "score": score, "action": "; ".join(labels),
                     "missing": labels[:3], "field": None,
                     "points_available": round(pts * eff_weight, 1), "closes_with": "review"})
    return rows


def _pillar_rec_field(pillar: str, action: str, facts: Optional[dict] = None) -> Optional[str]:
    """The canonical fact that would answer a PACKAGE top-recommendation.

    WHY THIS EXISTS (2026-09-23). `top_recs` entries are built from pillar
    rankings and carry `pillar` / `score` / `action` / `missing` - and no
    `field`. `_route_recommendations` routes through
    `answer_routing.stamp_recommendations`, which reads `rec["field"]`, so every
    package recommendation came back `answer_mode: "none"` with the note "This
    one has no single value to fill - attach a supporting document or dismiss it
    with a note."

    That was false for all three a live package produced, and visibly so: the
    numbered package list said "no single value to fill" for Loss History and
    Narrative while the FORM cards directly beneath it offered working controls
    for the same two problems, and the third row ("FEIN / Tax ID") offered
    nothing at all even though `fein` is an ordinary writable Tier 2 fact. One
    screen, two doors, opposite answers - the BUG-05 class at package level.

    DERIVED, never a new table: the loss messages go through the existing
    `loss_recommendation_field`, the structural labels are looked up in the
    Tier 1 / Tier 2 tables that DEFINE those labels, and narrative uses the same
    writable fact the form card uses (`additional_remarks_text` - NOT
    `acord101_remarks`, which is a read-only alias the producer-answer door
    refuses). Returning None leaves the old `none` behaviour untouched, so a
    pillar we cannot route is never given a box that would be refused.
    """
    if not action:
        return None
    if pillar == "loss_history_alignment":
        return loss_recommendation_field(action, facts)
    if pillar == "narrative_quality":
        # The literal, matching `rec_narrative_components` a few hundred lines
        # below in this same file. Importing arq_service.NARRATIVE_ANSWER_FIELD
        # here would be a new sqs_service -> arq_service edge for one string.
        return "additional_remarks_text"
    if pillar == "structural_completeness":
        # `action` is a LABEL from check_tier1 / check_tier2. Both tables are
        # the authority for their own labels, so this cannot drift from them.
        label = action.strip()
        for _fact, _label in TIER2_FIELDS.items():
            if _label == label:
                return _fact
        for _fact, _label in TIER1_FIELDS.items():
            if _label == label:
                return _fact
        if label == "Contact information":
            # Any one satisfies Tier 1 (client 9.1); offer the first, exactly as
            # the Tier 1 resolution does.
            return TIER1_CONTACT[0]
        if label == "NAICS or SIC industry code":
            return "naics_code"
    return None


def _premises_recommendations(facts, flags, mapped_data) -> List[dict]:
    """ACORD 125's one-premises asks - its interest, then a tenant's landlord -
    built by `services.premises_interest` (the one owner of those rules). Every
    card is unscored and worth 0 points. Fails to no card, never to a broken
    score."""
    try:
        from services.premises_interest import premises_recommendations
        return premises_recommendations(facts, flags, mapped_data)
    except Exception as _pi_ex:                               # noqa: BLE001
        logger.warning("premises interest cards skipped: %s", _pi_ex)
        return []


def _route_recommendations(recs, facts=None):
    """Stamp every recommendation with the ONE answer mode the UI must render.

    The card used to decide for itself, with `!!rec.field` - so a rec naming a
    field the producer-answer door cannot write offered a typed box the server
    then refused ("This item can't be answered directly"), and a rec naming a
    LIVE CAPTURE SCHEDULE offered a single-line box whose value replaced the
    whole extracted table. Both reported/reproduced 2026-09-08.

    The server decides now, from the fact's own declarations
    (`services/answer_routing`), and the card draws what it is told. Purely
    ADDITIVE - `field`, `rec_id`, `message` and `score_impact` are untouched, so
    dismiss credit, auto-resolve and rec_id dedupe are unaffected, and a session
    stored before this change simply has no `answer_mode` and keeps the old
    rendering.
    """
    try:
        from services.answer_routing import stamp_recommendations
        return stamp_recommendations(recs, facts)
    except Exception as _ar_ex:                                # noqa: BLE001
        logger.warning(f"answer routing skipped: {_ar_ex}")
        return recs


def loss_recommendation_field(message: str, facts: Optional[dict] = None) -> Optional[str]:
    """The canonical fact that would actually answer this loss recommendation.

    `None` = no single fact closes it (needs a document or a reconciliation).
    Unknown messages also return None rather than guessing: offering a waiver on
    a rec we cannot route is recoverable, silently writing an answer into the
    wrong fact is the defect this function exists to fix.
    """
    m = (message or "").lower()
    for phrase, field in _LOSS_RECOMMENDATION_FIELDS:
        if phrase in m:
            # A typed years-covered answer counts ONLY when the runs on file show
            # no readable claim period (`calculate_p4_loss_history`'s option B);
            # with a readable period the gap is closed by uploading runs, never
            # by typing a number - a box that moves nothing is a dead card (live
            # Choice Electric e36183e8, 30 Oct 2026: "5" typed three times, +0).
            if field == "loss_history_years" and isinstance(facts, dict) and (
                    _fv(facts, "loss_run_period_start") or _fv(facts, "loss_run_period_end")):
                return None
            return field
    return None


# Asked on every match path when the runs' claim years cannot be read.
LOSS_YEARS_UNREADABLE_REC = ("Loss runs uploaded - confirm how many years of claims "
                             "they cover")

_NEW_VENTURE_CONFIRM_REC = (
    "If this business is a new venture with no prior operations, confirm New "
    "Venture status - Loss History will then be marked Not Applicable instead "
    "of counting against the score."
)

# The notice an attested "No Known Losses" leaves when it takes Loss History
# out of the score (owner decision 29 Sep 2026, Orbin item 15). Informational:
# the per-form loop gives it impact 0 / priority 3, and its wording must stay
# clear of `_loss_doc_phrases` so it never reads as "needs a document".
# Brent, 23 Oct 2026 (Z34-1 #2): the logic is sound, but the state reads
# "Unable to Verify / Confirmation Required", never "Not Applicable".
ATTESTED_LOSS_STATUS_TEXT = "Unable to Verify / Confirmation Required"
_ATTESTED_NOT_APPLICABLE_REC = (
    "No Known Losses attested - Loss History is Unable to Verify / "
    "Confirmation Required, so it is left out of the score (remaining pillars "
    "rescale proportionally). A carrier may still ask for a signed "
    "no-known-loss letter before binding."
)
# The other two routes to the same Not Applicable pillar (C2 2.2 and Brent's
# 2026-08-24 under-a-year ruling) leave notices of the same kind.
_NEW_VENTURE_NOT_APPLICABLE_REC = (
    "New Venture confirmed - no prior operations, so Loss History is "
    "Not Applicable and removed from the score (remaining pillars "
    "rescale proportionally)."
)
_UNDER_A_YEAR_NOT_APPLICABLE_REC = (
    "Business has under a year of operating history and reports no "
    "known losses - there are no loss runs to obtain, so Loss History "
    "is Not Applicable and removed from the score (remaining pillars "
    "rescale proportionally)."
)
# 1 Oct 2026 (Orbin, cover review): these three say what the SCORE did - the
# pillar left it - not what the submission lacks. Each is a status note, so its
# card is `unscored`: the underwriter cover and the cover paragraph leave it out
# (download_routes._unscored_card_ids, cover_service) while the producer's
# review keeps it. The underwriting advisories and the New Venture CONFLICT
# notice are real underwriting information and are deliberately NOT here.
_LOSS_NOT_APPLICABLE_NOTICES = frozenset({
    _ATTESTED_NOT_APPLICABLE_REC,
    _NEW_VENTURE_NOT_APPLICABLE_REC,
    _UNDER_A_YEAR_NOT_APPLICABLE_REC,
})


def _new_venture_prompt(facts: dict, flags: dict) -> list:
    """The New Venture confirm prompt, ONLY while it is still unanswered.

    LIVE RUN 2026-08-27 (H7 S1): this rec was appended unconditionally whenever
    loss history was absent. Answering "Yes" makes the pillar Not Applicable, so
    the rec stops being generated and the card closes. Answering "No" - the
    honest answer on most accounts - changes nothing this function reads, so the
    rec came back identical, the auto-resolve pass had nothing to stamp, and the
    card reappeared as Open with an empty dropdown. The answer was saved
    correctly at every layer; only the card lied, and the owner answered it
    three times before reporting it.

    A confirm-X prompt must stop asking once X is confirmed EITHER way. The real
    remaining gap (no loss history on file) keeps its own recommendation in the
    same list - that one SHOULD stay open, and it does.
    """
    # Imported here, not at module scope: loss_history_state imports back into
    # this module's helpers, and the existing readers in calculate_p4_loss_history
    # take the same local-import route for that reason.
    #
    # Nor is it offered when the documents show a policy term that has already
    # ENDED (29 Sep 2026): a business insured through a whole term had prior
    # operations, so the card's own premise is false (Orbin: 07/15/2025 -
    # 07/15/2026). The real gap - no loss history - keeps its own rec.
    from services.loss_history_state import completed_policy_term, new_venture_answered
    if new_venture_answered(facts, flags) or completed_policy_term(facts):
        return []
    return [_NEW_VENTURE_CONFIRM_REC]


def calculate_p4_loss_history(
    facts: dict,
    flags: dict,
    has_loss_run_doc: bool = False,
    loss_run_match: str = "no_loss_run",
    *,
    _years_answer_checked: bool = False,
) -> Tuple[Optional[int], List[str]]:
    """Loss History pillar - client C2 revised scoring (2026-08-24).

    SQS PRINCIPLE (client 2.1): this measures the QUALITY AND COMPLETENESS of
    the loss information, never how desirable the losses are. The old
    claim-frequency / loss-ratio deductions are now underwriting ADVISORIES
    with no score effect.

    Path A - runs uploaded, readable claim years: 5+ fully valued = 100,
      3-4 = 85, 1-2 = 70. Recency 0 / -10 / -20 / -25, unknown valuation date
      -15. Insured match 0 / -8 / -15; no credible match caps the pillar at 25.
      Prior carrier: present = 0, missing WHEN APPLICABLE = -10 (the +10 bonus
      is removed - expected context is not bonus-quality information).
    Path B - runs uploaded, claim years NOT readable: strong match (name +
      FEIN/policy) = 60 PINNED AND TERMINAL - no recency, carrier or
      unknown-date deduction ever moves it (only the contradiction CEILING
      can). Moderate 42 / possible 35 / no match 15, with recency applied only
      when a valuation date exists and -10 for a missing applicable carrier.
    Path C - no runs: an attested No Known Losses is NOT APPLICABLE (owner,
      29 Sep 2026 - see below); requested/pending 50, narrative-only 40,
      nothing 25. Known claims + pending = 50; attestation + pending = the
      attestation (N/A); known claims with no runs and nothing pending = 25.
      An attestation still SCORES (60, or 85 for a 1-5 year business) only
      where it cannot stand: beside a "we have had claims" answer, or against
      corroborated claims, where the 45 conflict ceiling then applies.
    New venture (client 2.2): producer-confirmed and uncontradicted -> returns
      None (Not Applicable); the caller's _weighted_pillar_sum rescales the
      remaining pillars proportionally.
    No Known Losses (owner decision 29 Sep 2026, Orbin item 15): the same
      mechanism. Michelle: "We've confirmed No Known Losses. It should not
      calculate against the score." An attestation nothing contradicts
      (`loss_history_state.attested_no_losses_not_applicable`) returns None in
      EVERY years band. Documents still outrank it: a loss-run document takes
      the Path A / B branches before the attestation is ever read.
    Ceilings (client 2.6 + spec): no-match caps at 25; a no-loss attestation
      contradicted by actual loss-run claims caps at 45 AND at what the pillar
      scores once the claims are confirmed (owner, 23 Oct 2026 - never above
      the honest answer, so confirming the claims never lowers it). Ceilings,
      never floors - a score already below stays its own value.
    """
    from services.loss_history_state import (
        BAND_ESTABLISHING, BAND_YOUNG, attested_no_losses_not_applicable,
        loss_history_not_applicable, loss_years_required,
        loss_runs_pending_stated, new_venture_applicable, new_venture_confirmed,
        no_runs_available_stated, parse_loss_run_status, previously_uninsured,
        prior_carrier_applicable, prior_claims_exist, prior_operations_evidence,
        stored_pending_counts, years_in_business_band, years_in_business_value,
    )
    # THE NARRATIVE SAYS CLAIMS, THE ANSWER SAYS NONE (24 Oct 2026,
    # `legacy_loss_narrative_mismatch`): the person's own narrative contradicts
    # the "no claims" that would take this pillar out, so the pillar is what it
    # scores with the narrative's answer - the honest value, the same rule as
    # the conflict's below. The warning holds the package at 85; changing the
    # answer to the truthful one then releases it and never lowers anything.
    try:
        from services.loss_history_state import (
            claims_question_answers as _cqa, narrative_answer_mismatch as _nam,
            with_claims_answer as _wca,
        )
        if _nam(facts) == "claims":
            _nf, _nfl = _wca(facts, flags, _cqa()[1])
            return calculate_p4_loss_history(_nf, _nfl, has_loss_run_doc, loss_run_match,
                                             _years_answer_checked=_years_answer_checked)
    except Exception as _nx:                                   # noqa: BLE001
        logger.debug("narrative claims stance not read: %s", _nx)
    years    = _resolve_loss_history_years(facts)
    # RUNS WHOLLY BEFORE THE WINDOW DO NOT COUNT (owner, 24 Oct 2026, Z38 lane
    # E): a dated run whose years all fall before the last min(5, age) years
    # (2019-2021 alone, read in 2026) covers nothing, so Loss History scores as
    # if no loss run were on file - never the "claim years are not readable"
    # 60, which is for runs whose years cannot be read.
    _outside_window_rec = None
    if has_loss_run_doc and years == 0 and _parse_iso_date(_fv(facts, "loss_run_period_start")) \
            and (_parse_iso_date(_fv(facts, "loss_run_period_end"))
                 or _parse_iso_date(_fv(facts, "loss_run_valuation_date"))):
        has_loss_run_doc = False
        try:
            from services.loss_history_state import loss_years_required as _lyr
            _n = int(_lyr(facts) or _LOSS_YEARS_FULL)
        except Exception:                                      # noqa: BLE001
            _n = _LOSS_YEARS_FULL
        _outside_window_rec = (f"The loss runs on file cover only years before the last {_n} "
                               f"year{'' if _n == 1 else 's'} - upload loss runs for the last "
                               f"{_n} year{'' if _n == 1 else 's'}")
    # AN ANSWER NEVER COSTS POINTS (owner, 23 Oct 2026, option B - fc04c74f): a
    # PERSON's years-covered answer can only help. The year-based path charges
    # the unknown valuation date -15, so "1 year" on a strong run scored 55
    # against the 60 the same runs score with years unreadable. When the years
    # come from that answer (no readable run period), Loss History takes the
    # higher of the two; the valuation date is part of the plan's one upload
    # row (`loss_history_plan`).
    if not _years_answer_checked and has_loss_run_doc and years > 0 and not (
            _fv(facts, "loss_run_period_start") or _fv(facts, "loss_run_period_end")):
        try:
            from services.fact_state import typed_by_person
            _typed_years = typed_by_person((facts or {}).get("loss_history_years"))
        except Exception:                                  # noqa: BLE001
            _typed_years = False
        if _typed_years:
            _unread = dict(facts)
            _unread.pop("loss_history_years", None)
            # The keyword flag makes this rule run once (no fake fact source).
            _a = calculate_p4_loss_history(facts, flags, has_loss_run_doc, loss_run_match,
                                           _years_answer_checked=True)
            _b = calculate_p4_loss_history(_unread, flags, has_loss_run_doc, loss_run_match,
                                           _years_answer_checked=True)
            if _a[0] is not None and _b[0] is not None and _b[0] > _a[0]:
                return _b[0], _a[1]
            return _a
    age_days = _loss_run_age_days(facts)          # None when recency is UNVERIFIED
    has_carrier = bool(_fv(facts, "prior_carrier")) and not previously_uninsured(facts)
    carrier_applicable = prior_carrier_applicable(facts, flags, has_loss_run_doc)
    # BRENT RULING 2026-08-24: what loss evidence is reasonable depends on how
    # long the business has operated. `_band_score` picks the row for the
    # current band; the 5+ / unknown column is the client's own 2.5 table,
    # unchanged, so nothing moves on a package whose years we cannot read.
    _band = years_in_business_band(facts)

    def _band_score(establishing: int, established: int) -> int:
        return establishing if _band == BAND_ESTABLISHING else established

    # Fix: also read the actual canonical alias key (fixes dead-key bug §6.4).
    # Use _attested_true so a stored "No"/"false"/"0" is NOT misread as attested.
    # Beside claims a person has confirmed ("we have had claims" + corroborated
    # claims, 23 Oct 2026) no no-loss statement is credited: the honest state is
    # "prior claims exist", and it is what the conflict ceiling below falls to.
    try:
        from services.loss_history_state import claims_confirmed_by_person
        _claims_confirmed = claims_confirmed_by_person(facts, has_loss_run_doc)
    except Exception:                                          # noqa: BLE001
        _claims_confirmed = False
    no_loss_attested = not _claims_confirmed and (
        bool(flags.get("no_prior_losses"))
        or bool(flags.get("narrative_states_no_losses"))
        or _attested_true(_fv(facts, "no_prior_losses"))
        or _attested_true(_fv(facts, "loss_history_no_prior_losses_indicator"))
    )

    recs: List[str] = []
    if _outside_window_rec:
        recs.append(_outside_window_rec)

    # §6.4 item 1: a no-loss attestation contradicted by ACTUAL loss-run claims
    # cannot earn full credit. Cap every return path so the number matches the
    # 'conflicting' state label (single source: _loss_history_conflict).
    _conflict = _loss_history_conflict(facts, flags, has_loss_run_doc)
    # NEVER ABOVE THE HONEST ANSWER (owner, 23 Oct 2026, 5472449a: answering the
    # conflict truthfully - "Yes, we had claims" - took Loss History 45 -> 25 and
    # the package 91 -> 88). While the attestation conflicts with the claims the
    # pillar is the lower of the 45 ceiling and what it scores once the claims
    # are confirmed, so the truthful answer can never lower it. That answer
    # settles the conflict (`_loss_history_conflict`), so this runs once.
    _honest: Optional[int] = None
    if _conflict:
        try:
            from services.loss_history_state import claims_question_answers, with_claims_answer
            _hf, _hfl = with_claims_answer(facts, flags, claims_question_answers()[1])
            _honest = calculate_p4_loss_history(_hf, _hfl, has_loss_run_doc, loss_run_match)[0]
        except Exception as _hx:                               # noqa: BLE001
            logger.debug("honest loss-history value not measured: %s", _hx)
            _honest = None
    # Client §6.4 item 2: loss runs must be matched to the insured BEFORE they can
    # be credited. An insured-name mismatch means the runs are not creditable
    # evidence for THIS submission, so the score cannot exceed the no-information
    # baseline regardless of how many years they contain - otherwise the year-tier
    # path could award 70+ for loss runs that do not belong to the insured.
    _no_match = (loss_run_match == "no_match")

    def _result(score: int, msgs: List[str]) -> Tuple[int, List[str]]:
        capped = score
        # Recs accumulated BEFORE a terminal branch (e.g. the contradicted
        # new-venture notice) must survive it - a literal msgs list used to
        # silently drop them. Deduped so `_result(x, recs)` callers don't double.
        out_msgs = [m for m in recs if m not in msgs] + list(msgs)
        if _no_match:
            capped = min(capped, _LOSS_NO_MATCH_CAP)
        if _conflict:
            capped = min(capped, _LOSS_CONFLICT_CAP)
            if _honest is not None:
                capped = min(capped, int(_honest))
            out_msgs.append(
                "Loss history conflict: a no-loss attestation contradicts the "
                "uploaded loss run claims - reconcile before submission."
            )
        return capped, out_msgs

    # ── No loss history to evaluate -> the pillar is Not Applicable ──────────
    # Client 2.2 (producer-confirmed New Venture) OR Brent's 2026-08-24 ruling
    # that a 0-1 year business "will not have loss runs because the business is
    # too young" - the correction to treating a legitimate "none exist" as
    # nothing provided. Both need an affirmative answer AND no evidence of
    # prior operations. Returns None; every weighted sum goes through
    # _weighted_pillar_sum, which removes the pillar and rescales the rest.
    if loss_history_not_applicable(facts, flags, has_loss_run_doc):
        if new_venture_applicable(facts, flags, has_loss_run_doc):
            return None, [_NEW_VENTURE_NOT_APPLICABLE_REC]
        return None, [_UNDER_A_YEAR_NOT_APPLICABLE_REC]
    if new_venture_confirmed(facts, flags):
        # Confirmed but contradicted (client 2.10's "unless contradictory
        # source information"): keep scoring normally and tell the producer
        # exactly which evidence blocked the N/A.
        _evidence = prior_operations_evidence(facts, flags, has_loss_run_doc)
        recs.append(
            "New Venture status conflicts with evidence of prior operations "
            f"({', '.join(_evidence)}) - confirm with the insured before "
            "relying on the new-venture answer."
        )

    # ── Base score by year tier (client C2 2.3: 100 / 85 / 70) ──────────────
    # The old 1-2 year base of 40 was too punitive for actual loss evidence -
    # it made real loss runs score worse than some no-loss-run states.
    # Bug fix (2026-07-11, found via loss-history test suite): `years` is a raw
    # extracted number with no document backing required. A Yes/No question's
    # lookback window ("...in the past five (5) years?") or the ACORD form's own
    # "FOR THE LAST ___ YEARS" boilerplate blank can populate loss_history_years
    # with zero loss-run evidence attached, and this tier previously credited
    # that the same as an actual multi-year loss run. Require has_loss_run_doc
    # so a bare number can never outscore real documentation - an undocumented
    # years value falls through to the attestation/no-info tiers below instead.
    # THE YEARS THE BUSINESS HAS EXISTED (Brent, 23 Oct 2026, Z34-1 #2): full
    # credit needs min(5, the business's age rounded up) years of runs, so runs
    # covering the whole life of a 1-4 year business are complete. An older
    # business keeps the shortfall as incomplete (the same 85 / 70 tiers), and
    # "5 years preferred" is said only to a business 5+ years old. Unknown age
    # keeps the 5-year rule.
    _required = loss_years_required(facts)
    _age = years_in_business_value(facts)
    _full_years = _required if _required is not None else _LOSS_YEARS_FULL
    _short_of_age = (_age is not None and _age < _LOSS_YEARS_FULL)

    def _age_shortfall() -> str:
        _age_txt = f"{_age:g}"
        return (f"Loss history incomplete - loss runs cover {years} of the {_age_txt} "
                f"year{'' if _age_txt == '1' else 's'} the business has operated")

    if has_loss_run_doc and years >= _full_years:
        base_score = 100
    elif has_loss_run_doc and years >= _LOSS_YEARS_PART:
        base_score = 85
        recs.append(_age_shortfall() if _short_of_age
                    else "3 years of loss runs provided - 5 years preferred for full credit")
    elif has_loss_run_doc and years > 0:
        base_score = 70
        recs.append(_age_shortfall() if _short_of_age
                    else "Loss history incomplete - fewer than 3 years provided")
    elif has_loss_run_doc:
        # §6.4 pending-status shortcut: a document classified as a loss_run that only
        # MENTIONS runs are pending/requested (loss_run_status extracted as "pending" or
        # "requested", no claim years and no claim amounts found) is a cover letter or
        # narrative, not an actual loss run. Honour the pending state instead of treating
        # it as an uploaded-but-unconfirmed run. Must be checked FIRST so it takes
        # priority over the rest of the has_loss_run_doc credit logic below.
        _has_claims = (
            (_to_int(_fv(facts, "num_claims")) or 0) > 0
            or (_to_float(_fv(facts, "total_incurred")) or 0.0) > 0.0
        )
        # A PERSON's earlier "requested / pending" is out of date once runs are
        # on file (23 Oct 2026) - `stored_pending_counts` is the one door.
        if stored_pending_counts(facts, flags, True, years) and not _has_claims:
            return _result(50, ["Loss runs requested / pending - update score when received"])
        # ── Path B (client 2.4): runs uploaded, claim years NOT readable ────
        # Strong (name + FEIN/policy) = 60 FIXED AND TERMINAL. The 60 already
        # prices in "the details are unreadable"; deducting recency or the
        # unknown-valuation -15 on top charged the same unreadability twice
        # (a strong run with no readable valuation date used to fall 60 -> 45).
        # Only the _result ceilings (contradiction 45) may move it.
        if loss_run_match == "strong":
            return _result(60, [
                "Loss runs match the insured (name + FEIN/policy) but claim "
                "years are not readable - pinned at 60. Confirm claim years "
                "to unlock the year-based score."
            ])
        # Moderate / possible / no-match tiers (client 2.4 base scores).
        match_credit = {"moderate": 42, "possible": 35, "no_match": 15, "no_loss_run": 50}
        credit = match_credit.get(loss_run_match, 50)
        if loss_run_match == "moderate":
            # Deliberately does NOT name which identifiers matched: `moderate`
            # now has TWO causes (name+address, and Brent's Q3b tax-ID-matches-
            # but-name-differs), and the old wording asserted the first one on
            # both - factually backwards on the S7 live run. The precise reason
            # is already on the Loss History panel as a match note.
            recs.append("Loss run ownership partially verified - confirm the run belongs to this insured (see the note on the Loss History panel)")
        elif loss_run_match == "possible":
            recs.append("Loss run ownership could not be fully verified - name matches but FEIN/policy number not confirmed")
        elif loss_run_match == "no_match":
            recs.append("Loss run insured name does not match - verify these runs belong to this submission")
        else:
            recs.append("Loss runs uploaded - confirm claim years and recency to finalize loss-history score")
        if loss_run_match in ("moderate", "possible", "no_match"):
            # Item 2 (23 Oct 2026, fc04c74f): the years are asked on EVERY match
            # path, not only the strong one - a possible run whose years nobody
            # could type sat on a dead end.
            recs.append(LOSS_YEARS_UNREADABLE_REC)
        # Prior carrier (client 2.4): -10 when applicable and missing; the +10
        # bonus is removed on every tier.
        if carrier_applicable and not has_carrier:
            credit = max(0, credit - 10)
            recs.append("Prior carrier name missing - add carrier details to strengthen the loss history record")
        # Recency (client 2.4): "apply available recency deductions when a
        # valuation date exists" - so ONLY when the age is known. The
        # unknown-valuation -15 does NOT apply on this path (unreadable is
        # already priced into the tier).
        if age_days is not None:
            recency_pen = _recency_penalty(age_days)
            if recency_pen:
                credit = max(0, credit - recency_pen)
                recs.append(f"Loss runs appear stale ({age_days} days old). Updated loss runs may be required before bind.")
        return _result(credit, recs)
    elif no_loss_attested:
        # Client 2.5: the two no-loss evidence sources score differently -
        #   - user attestation    -> 60 (an affirmative statement by the insured)
        #   - stated in narrative -> 40 (weaker: a passing mention in prose, not
        #                                an attestation; below the attested 60
        #                                and above no-information 25)
        # They also stay distinguished by the loss-history STATE, the evidence
        # label, and the recommendation wording below. Checked BEFORE pending so
        # attestation + runs pending = 60 (client 2.5).
        _user_attested = (
            bool(flags.get("no_prior_losses"))
            or _attested_true(_fv(facts, "no_prior_losses"))
            or _attested_true(_fv(facts, "loss_history_no_prior_losses_indicator"))
        )
        # BRENT 2026-08-24: for a business of 1-5 years "a satisfactory answer
        # would be 'no known losses' ... to get through a submission, though
        # the submission would likely not bind without them"; at 5+ years
        # "loss runs are pretty much required", which is the client's own 2.5
        # value (60 / 40) left untouched. Ordering inside every band still
        # holds 2.5's rule that attestation > pending > narrative mention.
        if _user_attested:
            # OWNER DECISION 29 Sep 2026 (Orbin item 15): an attestation that
            # nothing contradicts is NOT APPLICABLE, not 60 - in every band,
            # including 1-5 years (85 before), because "not calculated" is
            # what the client asked for. Returned BEFORE the band split and
            # outside `_result`: the only ceilings `_result` applies (no-match,
            # conflict) are exactly the cases the predicate refuses. `recs`
            # carries the contradicted-New-Venture notice when there is one.
            if attested_no_losses_not_applicable(facts, flags, has_loss_run_doc):
                return None, list(recs) + [_ATTESTED_NOT_APPLICABLE_REC]
            if _band == BAND_ESTABLISHING:
                return _result(85, [
                    "No Known Losses (attested by user) - satisfactory for a "
                    "business of this age, though a carrier will usually ask "
                    "for loss runs before binding."
                ])
            return _result(60, ["No Known Losses (attested by user) - attach loss runs or a signed no-known-loss letter to fully confirm"])
        return _result(_band_score(60, 40), ["No Known Losses (stated in narrative) - confirm with the insured, or attach loss runs or a signed no-known-loss letter to corroborate the statement"])
    elif loss_runs_pending_stated(facts, flags):
        # Client 2.5: pending evidence is useful workflow context but is NOT
        # stronger than an actual attestation. BRENT 2026-08-24: for a 1-5 year
        # business, runs ordered through a loss-run service are a satisfactory
        # answer too - so the band lifts it toward, but never to, the
        # attestation's 85. Known prior claims + runs pending also lands here.
        return _result(_band_score(70, 50), ["Loss runs requested / pending - update score when received"])
    elif prior_claims_exist(facts, flags):
        # Client 2.5: known prior claims + no runs and no pending evidence = 25
        # until meaningful loss evidence or status is provided. Checked before
        # the availability statement (same order as the state resolver) so the
        # actionable "get the runs" message wins when both are true.
        return _result(25, [
            "Prior claims are known but no loss runs or pending request is on "
            "file - request loss runs from the prior carrier, or record that "
            "they have been requested."
        ])
    elif no_runs_available_stated(facts):
        # Client 2.9 state; 2.5 gives it no number. BRENT 2026-08-24 corrected
        # the shipped default: *"we can't treat 'N/A' as '0'"*. A business of
        # 1-5 years reporting that no runs exist is a workflow answer, not an
        # absence of evidence, so it scores with the other paperwork-status
        # answers rather than at the Nothing Provided floor. At 5+ years runs
        # are required, so the floor still applies. Under a year it never
        # reaches here - the Not Applicable gate above takes it.
        return _result(_band_score(50, 25), [
            "No loss runs are available for this account - ask the insured to "
            "attest No Known Losses, or record known claims, to firm up the "
            "loss history.",
            *_new_venture_prompt(facts, flags),
        ])
    else:
        return _result(25, [
            "No loss history provided - required for carrier submission",
            *_new_venture_prompt(facts, flags),
        ])

    # ── Prior-carrier adjustment (client C2 2.3: present 0 / missing -10) ────
    # The +10 presence bonus is REMOVED - prior carrier is expected context
    # when applicable, not bonus-quality information. The -10 applies only when
    # applicable (never to a confirmed new venture).
    if carrier_applicable and not has_carrier:
        base_score = max(0, base_score - 10)
        recs.append("Prior carrier name missing - add carrier details to complete the underwriting picture")

    # ── Recency adjustment (Q3: 90-day grace, then gradual reduction) ────────
    # Only when the age is KNOWN (deterministic from a valuation date, or a stated
    # age). Never assume an age - the old "default 365" punished loss runs whose
    # date the model failed to state and printed a fabricated age (Beta 2).
    if age_days is not None:
        recency_pen = _recency_penalty(age_days)
        if recency_pen:
            base_score = max(0, base_score - recency_pen)
            recs.append(f"Loss runs appear stale ({age_days} days old). Updated loss runs may be required before bind.")
    elif age_days is None and has_loss_run_doc:
        base_score = max(0, base_score - _LOSS_RECENCY_UNKNOWN_PEN)
        recs.append("Loss run valuation date not detected - recency unverified. Updated loss runs may be required.")

    # ── Insured match adjustment (for docs where years were already parsed) ──
    # Three distinct tiers (sqs-pillars spec): strong = no deduction; moderate
    # (name + address) = partial deduction; possible (name only) = larger deduction.
    if loss_run_match == "moderate":
        base_score = max(0, base_score - 8)
        # Same wording as the Path B copy below, and for the same reason:
        # `moderate` has TWO causes since Brent's Q3b ruling, so the message
        # must not assert either one. The S7 live run showed this THIRD copy
        # still printing "name and address match" on a run whose FEIN matched
        # and whose name did not - backwards.
        recs.append("Loss run ownership partially verified - confirm the run belongs to this insured (see the note on the Loss History panel)")
    elif loss_run_match == "possible":
        base_score = max(0, base_score - 15)
        recs.append("Loss run ownership could not be fully verified - name matches but FEIN/policy number not confirmed")
    elif loss_run_match == "no_match":
        base_score = max(0, base_score - 30)
        recs.append("Loss run insured name does not match this submission - verify ownership before crediting")

    # ── Claim frequency / loss ratio - ADVISORY ONLY (client C2 2.1) ────────
    # "SQS measures submission quality, not risk desirability." These
    # conditions no longer deduct a single point - they surface as
    # underwriting advisories so the broker still sees them. This also retires
    # the undefined generic "$1M of exposure" denominator as a scoring input.
    num_claims     = _to_int(_fv(facts, "num_claims"))
    total_incurred = _to_float(_fv(facts, "total_incurred"))
    exposure = _to_float(_fv(facts, "total_revenue")) or _to_float(_fv(facts, "total_payroll"))
    if num_claims is not None and num_claims > 0 and exposure and exposure > 0:
        claims_per_m = num_claims / (exposure / 1_000_000.0)
        if claims_per_m > 2.0:
            recs.append(f"Underwriting advisory (no score effect): high loss frequency - {num_claims} claims on ${exposure:,.0f} exposure (~{claims_per_m:.1f}/$1M)")
        elif claims_per_m > 1.0:
            recs.append(f"Underwriting advisory (no score effect): elevated loss frequency relative to exposure ({claims_per_m:.1f} claims/$1M)")
    if total_incurred and exposure and exposure > 0:
        loss_ratio = total_incurred / exposure
        if loss_ratio > 0.10:
            recs.append(f"Underwriting advisory (no score effect): loss ratio {loss_ratio*100:.1f}% exceeds 10% of exposure")

    return _result(base_score, recs)


# ── THE LOSS HISTORY PLAN (owner, 23 Oct 2026, package 5472449a) ─────────────
# Spot fixes kept producing rows that changed under the producer: a "Mark as Loss
# runs +12" that added 2, four NEW rows after it, a truthful "Yes, we had claims"
# that lowered the score. ONE model now holds for every Loss History state: an
# ordered list of the steps that take the pillar from where it is to its
# maximum, each worth exactly what it adds after the steps above it.
LOSS_PLAN_CONFLICT_CODE = "loss_history_attestation_conflict"   # the warning card
LOSS_PLAN_NARRATIVE_CODE = "legacy_loss_narrative_mismatch"      # narrative vs the answer
LOSS_PLAN_CLAIMS_FACT = "loss_history_no_prior_losses_indicator"
LOSS_PLAN_LABELS = {
    "conflict": ("The No Known Losses answer conflicts with the claims on file - confirm with "
                 "the insured whether they have had claims"),
    "claims": "Any claims in the last 5 years?",
    "ownership": "Confirm these loss runs belong to this insured",
    "pending": "Record that loss runs have been requested",
    "carrier": "Add the prior carrier's name",
    "upload": ("Upload carrier loss runs covering the last 5 years (or the business's age), "
               "valued within 90 days, showing this insured's FEIN or policy number"),
}
_LOSS_PLAN_CARRIER_PROBE = "Prior carrier"


def loss_history_plan(facts: dict, flags: dict, docs: Optional[List[dict]],
                      pillars: Optional[Dict[str, Any]]) -> Optional[List[dict]]:
    """WHAT TAKES LOSS HISTORY TO ITS MAXIMUM, STEP BY STEP (owner, 23 Oct 2026).

    The steps, in this order, each only when it applies:
      conflict  - the No Known Losses answer conflicts with the claims
                  (`_loss_history_conflict`): ALWAYS first, applied first, the
                  warning card's own answer ("Yes - we have had claims or
                  losses"). Under min(45, the honest value) it usually adds 0,
                  so the card shows no number; it is positive only once the 45
                  binds, i.e. when it was skipped.
      mark      - each uploaded document not typed a loss run whose classifier
                  scored `loss_run` best: "Mark '<file>' as Loss runs"
                  (probe: that document's type set to loss_run in the copy).
      carrier   - the prior carrier's name where the scorer deducts for it.
                  Asked BEFORE ownership: its -10 exists only while the runs
                  are not pinned at 60, so later it would add nothing and the
                  upload row would promise its points. When it adds nothing
                  until complete runs arrive, it goes after the upload row.
      ownership - runs on file (or after the marks), the match not strong, and
                  a "Yes" makes it strong (`loss_run_ownership_confirmed`).
      years     - years covered, only when the TRUE value (the runs' own claim
                  years, `loss_run_years_suggestion`) raises the score under
                  option B.
      pending   - "Loss runs have been requested", only with no loss-run
                  document and none to mark.
      upload    - ONE row for everything only new documents supply: carrier
                  loss runs for the required years (min(5, the business's
                  age)), valued within 90 days, matched strong. It takes
                  whatever is left.
      claims    - LAST, and only when nothing is known (no answer, no
                  corroborated claims, no runs and nothing to mark): "Any
                  claims in the last 5 years?". What it adds depends on which
                  answer is true, so it is weighed after the steps that hold
                  whatever the truth - where it adds nothing and is not
                  listed. A "no claims" answer still takes the pillar out of
                  the score at once (24 Oct 2026, the page-wide plan).

    The numbers here decide which steps exist; the review page re-weighs them
    in its own order with every other item (`services/review_plan`).

    Every number is SEQUENTIAL and TRUE: the steps are simulated one after
    another on a copy with the real pillar scorer (`calculate_p4_loss_history`
    through the one match door) and the scorer's own weighted sum, each the
    package-score increase it adds after the steps above it - so doing them in
    order lands each number exactly and they add up to what the pillar can
    still give. A step that adds 0 (other than the conflict card's answer) is
    returned with `points` 0, not applied and never listed; a step that would
    lower the score is never offered. `pillars`: the package's six pillar
    scores now. None when Loss History is Not Applicable or already 100.

    Each step: key, kind ("answer" | "document"), fact, probe, label, points,
    exact, action (None | "add_documents"), applied, plan_order; mark steps also
    doc_id / filename, document steps `step`, the conflict step `card`."""
    try:
        from services.loss_history_state import (
            LOSS_RUN_OWNERSHIP_FIELD, LOSS_RUN_OWNERSHIP_OPTIONS, LOSS_RUN_STATUS_FIELD,
            LOSS_RUN_STATUS_OPTIONS, asserted_claims, claims_are_corroborated,
            claims_question_answers, had_claims_answer, loss_run_ownership_answer,
            ownership_question_open, loss_run_years_suggestion, loss_runs_pending_stated, loss_years_required,
            markable_loss_run_documents, package_has_loss_runs, parse_loss_run_status,
            previously_uninsured, prior_carrier_applicable, user_attested_no_losses,
            with_claims_answer,
        )
        from services.loss_run_identity import match_loss_run_identity
    except Exception:                                          # noqa: BLE001
        return None
    facts = facts if isinstance(facts, dict) else {}
    flags = flags if isinstance(flags, dict) else {}
    docs = [d for d in (docs or []) if isinstance(d, dict)]
    base = {k: (v.get("score") if isinstance(v, dict) else v) for k, v in (pillars or {}).items()}
    # The narrative says claims, the answer says none (24 Oct 2026,
    # `legacy_loss_narrative_mismatch`): the warning card's answer that agrees
    # with the narrative - "we have had claims" - goes in first, like the
    # conflict card's, so the steps after it (requested, upload) exist and are
    # weighed from there. Applied whatever the pillar does: "no claims" takes
    # the pillar out, so the answer that brings it back reads as a loss here,
    # while on the page it releases the 85. Its number is the review page's.
    try:
        from services.loss_history_state import narrative_answer_mismatch
        narrative_claims = narrative_answer_mismatch(facts) == "claims"
    except Exception:                                          # noqa: BLE001
        narrative_claims = False
    if "loss_history_alignment" not in base:
        if not narrative_claims:
            return None
        base["loss_history_alignment"] = None
    applicant = _fv(facts, "applicant_name")
    no_claims, had_claims = claims_question_answers()
    narrative_step: Optional[dict] = None
    if narrative_claims:
        facts, flags = with_claims_answer(facts, flags, had_claims)
        narrative_step = {"key": "narrative", "kind": "answer", "fact": LOSS_PLAN_CLAIMS_FACT,
                          "probe": had_claims, "label": LOSS_PLAN_LABELS["claims"], "points": 0,
                          "exact": True, "action": None, "applied": True,
                          "card": LOSS_PLAN_NARRATIVE_CODE}

    def _env(value: Any) -> dict:
        return {"value": value, "source": "producer", "confidence": "producer"}

    def _value(s: dict) -> Optional[int]:
        if s["upload"]:
            has, tier = True, "strong"
        else:
            has = package_has_loss_runs(s["docs"], s["facts"])
            tier = match_loss_run_identity(s["docs"], applicant, s["facts"])["tier"]
        return calculate_p4_loss_history(s["facts"], s["flags"], has_loss_run_doc=has,
                                         loss_run_match=tier)[0]

    def _package(v: Optional[int]) -> int:
        return max(0, min(100, int(_weighted_pillar_sum(
            {**base, "loss_history_alignment": v}, SPEC_PILLAR_WEIGHTS))))

    st = {"facts": dict(facts), "flags": dict(flags), "docs": list(docs), "upload": False}
    v0 = _value(st)
    if v0 is None or v0 >= 100:
        return [dict(narrative_step, plan_order=1)] if narrative_step else None
    cur = {"v": v0, "score": _package(v0)}
    steps: List[dict] = [narrative_step] if narrative_step else []

    def _step(key: str, new: dict, label: str, *, fact: Optional[str] = None,
              probe: Any = None, exact: bool = True, always: bool = False, **extra) -> bool:
        nv = _value(new)
        score = _package(nv)
        gain = score - cur["score"]
        lowers = gain < 0 or (nv is not None and cur["v"] is not None and nv < cur["v"])
        applied = not lowers and (gain > 0 or always)
        steps.append({"key": key, "kind": "answer" if fact else "document", "fact": fact,
                      "probe": probe, "label": label, "points": int(gain) if applied else 0,
                      "exact": bool(exact), "action": None if fact else "add_documents",
                      "applied": applied, **extra})
        if applied:
            st.clear()
            st.update(new)
            cur["v"], cur["score"] = nv, score
        return applied

    has_now = package_has_loss_runs(docs, facts)
    markable_now = markable_loss_run_documents(docs)
    conflict_now = _loss_history_conflict(facts, flags, has_now)
    if conflict_now:
        f2, fl2 = with_claims_answer(st["facts"], st["flags"], had_claims)
        _step("conflict", {**st, "facts": f2, "flags": fl2}, LOSS_PLAN_LABELS["conflict"],
              fact=LOSS_PLAN_CLAIMS_FACT, probe=had_claims, always=True,
              card=LOSS_PLAN_CONFLICT_CODE)

    def _live() -> bool:
        return cur["v"] is not None and cur["v"] < 100

    # The claims question FIRST when nothing is known (owner, 24 Oct 2026: a
    # business with no losses must reach 100 by answering). Weighed with "no
    # claims", which takes the pillar out at once; an honest "we have had
    # claims" brings the request / upload rows - new information, not a
    # surprise row.
    claims, incurred = asserted_claims(facts)
    claims_known = bool(claims or incurred) and claims_are_corroborated(facts, has_now)
    if (_live() and not conflict_now and not has_now and not markable_now and not claims_known
            and not user_attested_no_losses(facts, flags) and not had_claims_answer(facts)):
        # The narrative's own answer when it states one (24 Oct 2026): the
        # other would raise `legacy_loss_narrative_mismatch`.
        try:
            from services.loss_history_state import claims_answer_for_narrative
            claims_probe = claims_answer_for_narrative(facts) or no_claims
        except Exception:                                      # noqa: BLE001
            claims_probe = no_claims
        f2, fl2 = with_claims_answer(st["facts"], st["flags"], claims_probe)
        if claims_probe == had_claims:
            # Owner, 25 Oct 2026 (option A): the claims question comes FIRST and
            # ALONE even when the narrative already says claims - "up to" what
            # Loss History can still give; its follow-ups (requested, upload)
            # appear once it is answered (in the window under "Then:", then on
            # the page). Listing all three at once read as asking twice.
            gain = max(0, _package(100) - cur["score"])
            steps.append({"key": "claims", "kind": "answer", "fact": LOSS_PLAN_CLAIMS_FACT,
                          "probe": claims_probe, "label": LOSS_PLAN_LABELS["claims"],
                          "points": int(gain), "exact": False, "action": None,
                          "applied": True})
            for n, s_ in enumerate(steps, 1):
                s_["plan_order"] = n
            return steps
        _step("claims", {**st, "facts": f2, "flags": fl2}, LOSS_PLAN_LABELS["claims"],
              fact=LOSS_PLAN_CLAIMS_FACT, probe=claims_probe, exact=False)

    if _live():
        for n in markable_loss_run_documents(st["docs"]):
            d = st["docs"][n]
            name = str(d.get("filename") or "the uploaded document")
            marked = list(st["docs"])
            marked[n] = {**d, "doc_type": "loss_run"}
            _step("mark", {**st, "docs": marked}, f"Mark '{name}' as Loss runs",
                  step="mark", doc_id=d.get("doc_id"), filename=name)

    def _carrier_missing() -> bool:
        has = True if st["upload"] else package_has_loss_runs(st["docs"], st["facts"])
        f = st["facts"]
        return (not (bool(_fv(f, "prior_carrier")) and not previously_uninsured(f))
                and prior_carrier_applicable(f, st["flags"], has))

    def _carrier_step() -> bool:
        return _step("carrier", {**st, "facts": {**st["facts"],
                                                 "prior_carrier": _env(_LOSS_PLAN_CARRIER_PROBE)}},
                     LOSS_PLAN_LABELS["carrier"], fact="prior_carrier",
                     probe=_LOSS_PLAN_CARRIER_PROBE)

    carrier_after_upload = False
    if _live() and _carrier_missing():
        if not _carrier_step():
            steps.pop()                     # re-weighed after the upload row
            carrier_after_upload = True

    if _live() and package_has_loss_runs(st["docs"], st["facts"]) \
            and ownership_question_open(st["facts"], st["docs"]) \
            and match_loss_run_identity(st["docs"], applicant, st["facts"])["tier"] != "strong":
        yes = LOSS_RUN_OWNERSHIP_OPTIONS[0]
        confirmed = {**st["facts"], LOSS_RUN_OWNERSHIP_FIELD: _env(yes)}
        if match_loss_run_identity(st["docs"], applicant, confirmed)["tier"] == "strong":
            _step("ownership", {**st, "facts": confirmed}, LOSS_PLAN_LABELS["ownership"],
                  fact=LOSS_RUN_OWNERSHIP_FIELD, probe=yes)

    if _live() and package_has_loss_runs(st["docs"], st["facts"]) \
            and _resolve_loss_history_years(st["facts"]) == 0 \
            and not (_parse_iso_date(_fv(st["facts"], "loss_run_period_start"))
                     and (_parse_iso_date(_fv(st["facts"], "loss_run_period_end"))
                          or _parse_iso_date(_fv(st["facts"], "loss_run_valuation_date")))):
        # (A dated run wholly outside the window also reads 0 years - Z38 lane E;
        # a typed years count cannot move it, so the step is not offered.)
        sug = loss_run_years_suggestion(st["facts"])
        if sug:
            n_years = len(sug)
            shown = ", ".join(str(y) for y in sug[:6]) + (" ..." if len(sug) > 6 else "")
            _step("years", {**st, "facts": {**st["facts"], "loss_history_years": _env(str(n_years))}},
                  (f"Confirm how many years of claims the loss runs cover - their claim rows "
                   f"fall in {shown} ({n_years} year{'' if n_years == 1 else 's'})"),
                  fact="loss_history_years", probe=str(n_years))

    if (_live() and not has_now and not markable_now
            and parse_loss_run_status(_fv(facts, LOSS_RUN_STATUS_FIELD)) is None
            and not loss_runs_pending_stated(facts, flags)):
        requested = LOSS_RUN_STATUS_OPTIONS[0]
        _step("pending", {**st, "facts": {**st["facts"], LOSS_RUN_STATUS_FIELD: _env(requested)}},
              LOSS_PLAN_LABELS["pending"], fact=LOSS_RUN_STATUS_FIELD, probe=requested)

    if _live():
        full = loss_years_required(st["facts"]) or _LOSS_YEARS_FULL
        today = datetime.now(timezone.utc).date()
        try:
            start = today.replace(year=today.year - full)
        except ValueError:                                     # 29 February
            start = today.replace(year=today.year - full, day=28)
        complete = dict(st["facts"])
        for key, value in (("loss_run_period_start", start.isoformat()),
                           ("loss_run_period_end", today.isoformat()),
                           ("loss_run_valuation_date", today.isoformat())):
            complete[key] = {"value": value, "source": "policy_doc_text", "confidence": "high"}
        complete.pop("loss_run_age_days", None)
        _step("upload", {**st, "facts": complete, "upload": True}, LOSS_PLAN_LABELS["upload"],
              step="upload")

    if carrier_after_upload and _live() and _carrier_missing():
        _carrier_step()

    # What the steps leave (nothing, as far as the scorer's rules go): the
    # upload row is "everything only new documents supply", so it takes it.
    if _live():
        left = _package(100) - cur["score"]
        if left > 0:
            up = next((s for s in steps if s["key"] == "upload"), None)
            if up is None:
                up = {"key": "upload", "kind": "document", "fact": None, "probe": None,
                      "label": LOSS_PLAN_LABELS["upload"], "points": 0, "exact": True,
                      "action": "add_documents", "applied": True, "step": "upload"}
                steps.append(up)
            up["points"] += int(left)
            up["applied"] = True
    for n, s in enumerate(steps, 1):
        s["plan_order"] = n
    return steps


def loss_plan_probes(plan: Optional[List[dict]]) -> Dict[str, str]:
    """{fact: the answer the plan weighs it with} - the conflict card's "we have
    had claims", the runs' own claim years, "Yes" to ownership. Every share-out
    of a row or card asking one of these facts probes it with this value, never
    a generic one (a "3" for the years, an attestation for the conflict)."""
    out: Dict[str, str] = {}
    for s in plan or []:
        if isinstance(s, dict) and s.get("fact") and s.get("probe") is not None:
            out.setdefault(str(s["fact"]), str(s["probe"]))
    return out


# ── LOB inference ─────────────────────────────────────────────────────────────

NAICS_TO_LOB = {
    "236": "contractor", "237": "contractor", "238": "contractor",
    # 722 is Food Services and Drinking Places - restaurants. 311 (Food
    # Manufacturing) and 312 (Beverage Manufacturing) USED to map here too and
    # were removed 2026-09-05: a cannery is not a restaurant, and this file's
    # own `_NAICS_SECTOR_INDUSTRY` already says so ("31"/"32"/"33" ->
    # manufacturing). They now fall through to the ops classifier and land on
    # `generic`, which asks for LESS - never a harsher rule set on a guess.
    "722": "restaurant",
    "511": "technology", "518": "technology", "519": "technology",
    # NOTE, not fixed here: 541 is Professional / Scientific / TECHNICAL
    # Services, which is law firms and accountants as well as software. The
    # label is wrong for most of that sector and it is DISPLAYED beside the
    # package score. Left alone deliberately - it moves scores across a large
    # sector and was not the reported defect. Flag it, do not improvise it.
    "541": "technology",
    "321": "manufacturing","331": "manufacturing","332": "manufacturing",
    "484": "transportation","485": "transportation","492": "transportation",
}

# Operations phrases that identify a scoring bucket, matched on WORD BOUNDARIES.
#
# WHY THIS EXISTS IN THIS SHAPE (live 2026-09-05). The previous version tested
# bare substrings - `any(w in desc for w in ["restaurant","food",...])` - so a
# refrigerated warehouse whose operations read "cold storage of packaged FOOD
# products" was scored as a RESTAURANT, and `LOB_RULES["restaurant"]` then
# charged it for `occupancy_type`, a field a warehouse can never have. The same
# defect sat in every list: "app" matched apparel, "tech" matched technician
# and geotechnical, "platform" matched platform trailer, "delivery" matched the
# delivery of janitorial services.
#
# Two structural conditions, and both are load-bearing:
#   1. WORD BOUNDARIES - a phrase must stand as its own word(s), so "food
#      products" no longer answers a question about restaurants.
#   2. UNAMBIGUOUS EVIDENCE ONLY - if phrases from more than one bucket appear,
#      the answer is `generic`. That is what disposes of "restaurant
#      construction contractor" and of the janitorial company that serves
#      "grocery, restaurant and retail accounts" - the client's own reported
#      shape of this mistake, one door over in `cross_form_validator`.
#
# Every failure resolves to `generic`, whose rule set is the least demanding, so
# a classification this function gets WRONG can never score an account harder
# than making no claim at all.
#
# NOT routed through `_ops_to_industry` below, deliberately. That table answers
# a different question with a different tolerance for error: its verdict is
# cross-checked against the policy's class codes before it can move a score, so
# it can afford to be greedy. This one selects the scoring rule alone, with no
# second signal. Routing through it was tried and rejected - it maps "electrical
# equipment manufacturing" to construction, which would have handed a
# manufacturer the CONTRACTOR rule set, a HARSHER one, on a wrong guess.
_LOB_OPS_PHRASES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("restaurant", ("restaurant", "cafe", "coffee shop", "catering", "caterer",
                    "food service", "fine dining", "tavern", "bar and grill",
                    "diner", "pizzeria", "delicatessen", "food truck")),
    ("contractor", ("contractor", "contracting", "construction", "roofing",
                    "roofer", "plumbing", "plumber", "electrician", "carpentry",
                    "masonry", "excavation", "hvac", "drywall", "paving",
                    "framing", "siding")),
    # "logistics" is deliberately ABSENT. Every token here has to imply the
    # thing this bucket's rule set then demands - a vehicle schedule, drivers
    # and a radius of operation. A freight broker or a 3PL arranges transport
    # without owning a truck, so "logistics" would charge an account for a fleet
    # it does not have. It cost a fuzzed case ("cold chain logistics") and was
    # removed rather than argued with.
    ("transportation", ("trucking", "freight", "hauling", "courier",
                        "motor carrier", "long haul", "delivery service")),
    ("technology", ("software", "saas", "technology company", "cloud platform",
                    "information technology", "software development",
                    "web development")),
)


def _lob_from_operations(ops: str) -> str:
    """The bucket this operations text unambiguously names, else 'generic'.

    THROUGH THE SHARED DOOR since 2026-09-06. This carried its own word-boundary
    matcher and its own `_phrase_describes_the_applicant` for one day, and in
    that day the sweep found 32 more sites with the same need - including
    `_ops_to_industry`, 78 lines above. Both now ask `term_match`.

    Two behaviours the local copy had are deliberately preserved and are pinned
    by test:
      * plurals. The local matcher hardcoded `s?`; the door defaults plurals OFF
        because `_has_explicit_follow_form` breaks the instant "following form"
        matches "following forms". This bucket list is nouns a business is
        called ("restaurants", "contractors"), so it opts IN.
      * the deleted `except: return True` in the old ownership helper. That was
        a FAIL-OPEN fallback - an import blip silently restored the plain
        substring match, i.e. the bug. The door is stdlib-only with no import to
        fail, so the fallback has nothing left to guard and is gone.
    """
    return term_match.sole_bucket(
        _LOB_OPS_PHRASES, ops, plural=True, require_subject=True) or "generic"


def infer_lob(facts: dict, flags: dict) -> str:
    """Infer line of business from NAICS, flags, or operations description.

    Returns one of the `LOB_RULES` keys. `generic` is the answer whenever the
    evidence does not single out a bucket - see `_LOB_OPS_PHRASES`.
    """
    naics = str(_fv(facts, "naics_code") or "")[:3]
    if naics and naics in NAICS_TO_LOB:
        return NAICS_TO_LOB[naics]

    if (flags or {}).get("is_contractor"):
        return "contractor"

    # COERCED, not assumed to be a string. This function is called from inside
    # both score computations, and `.lower()` on a fact that arrived as a list,
    # an int or bytes raises - which is the shape of H1-G, the live run that
    # lost its Total Package Score with no reproducible trigger. A malformed
    # fact must classify as `generic`, never take a score down with it.
    ops = _fv(facts, "operations_description")
    return _lob_from_operations("" if ops is None else str(ops).lower())


# ── LOB-specific rules ────────────────────────────────────────────────────────

LOB_RULES = {
    "contractor": {
        # Use fields that extraction reliably produces for GL-contractor submissions.
        # percent_subcontracted and years_in_business (ACORD 186 specialty fields)
        # are almost never in extraction → they always dragged P2 to 33%.
        "required": ["operations_description", "total_payroll", "gl_class_codes_by_location"],
    },
    "restaurant": {
        "required": ["occupancy_type", "operations_description", "total_revenue"],
    },
    "technology": {
        "required": ["operations_description", "total_revenue", "num_employees"],
    },
    "transportation": {
        "required": ["auto_vin_schedule", "auto_drivers", "auto_radius_of_operation"],
    },
    "generic": {
        "required": ["operations_description", "total_revenue"],
    },
}


# ── Operations ↔ class-code industry consistency (client Exposure -15) ────────
# Deterministic, conservative buckets. A mismatch fires ONLY when operations map
# to one industry and the class codes clearly map to a DIFFERENT, mutually
# exclusive industry. Unmapped / ambiguous signals never fire, so a valid but
# unusual submission is never penalised by accident.
_OPS_INDUSTRY_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "construction":   ("roofing", "roofer", "contractor", "construction", "carpentry",
                       "plumbing", "plumber", "electrical", "electrician", "concrete",
                       "masonry", "framing", "excavation", "hvac", "drywall", "paving",
                       "siding", "general contractor", "subcontractor"),
    "office":         ("software", "technology company", "saas", "consulting", "consultant",
                       "professional services", "accounting", "accountant", "bookkeeping",
                       "law firm", "attorney", "legal services", "insurance agency",
                       "financial services", "clerical", "administrative office"),
    "restaurant":     ("restaurant", "cafe", "catering", "food service", "tavern",
                       "bakery", "fine dining", "coffee shop", "bar and grill"),
    "retail":         ("retail store", "retail shop", "boutique", "storefront", "retailer"),
    "transportation": ("trucking", "freight", "hauling", "courier", "long haul",
                       "motor carrier", "trucker"),
    "manufacturing":  ("manufacturing", "fabrication", "machining", "assembly plant",
                       "production plant", "factory"),
}

# First two NAICS digits → industry (corroborates or substitutes for ops keywords).
_NAICS_SECTOR_INDUSTRY: Dict[str, str] = {
    "23": "construction",
    "51": "office", "52": "office", "54": "office", "55": "office",
    "44": "retail", "45": "retail",
    "72": "restaurant",
    "48": "transportation", "49": "transportation",
    "31": "manufacturing", "32": "manufacturing", "33": "manufacturing",
}

# Authoritative NCCI WC class-code → industry (conservative subset). Construction
# trades (50xx/52xx/54xx/56xx/62xx), clerical/office (88xx), restaurant (90xx),
# retail (80xx), trucking (72xx/73xx), and selected manufacturing codes.
_CLASS_CODE_INDUSTRY: Dict[str, str] = {
    "8810": "office", "8742": "office", "8820": "office", "8803": "office", "8871": "office",
    "5403": "construction", "5183": "construction", "5190": "construction",
    "5213": "construction", "5022": "construction", "5551": "construction",
    "5645": "construction", "5437": "construction", "5474": "construction",
    "5606": "construction", "6217": "construction", "5478": "construction",
    "9079": "restaurant", "9082": "restaurant", "9083": "restaurant", "9058": "restaurant",
    "8017": "retail", "8008": "retail", "8006": "retail", "8018": "retail",
    "7380": "transportation", "7228": "transportation", "7229": "transportation", "7219": "transportation",
    "3632": "manufacturing", "3629": "manufacturing", "2812": "manufacturing", "3076": "manufacturing",
}


def _ops_to_industry(ops: str, naics2: str) -> Optional[str]:
    """Best-effort industry bucket from operations text, falling back to NAICS sector.

    THROUGH THE SHARED DOOR since 2026-09-06, and this function is the reason
    the door exists. It was `any(k in ops for k in kws)` - a bare substring -
    sitting 78 lines ABOVE `_lob_from_operations`, which had been given word
    boundaries, a single-bucket rule and an ownership test the day before. Same
    file, same question, one fixed and one not: two copies is how this class
    keeps coming back.

    Measured, with controls: "Apartment building owner; 62 units with long-term
    tenants RESIDING on site" -> construction (via "siding"); "satisfactory" ->
    manufacturing (via "factory"); "overhauling" -> transportation (via
    "hauling"); "cafeteria" -> restaurant (via "cafe"); and "Insurance agency
    serving CONTRACTORS and building trades" -> construction, which is somebody
    else's trade. Each fed a -15 ops/class-code mismatch at :3363 and :3411.

    Ambiguity now returns None, which falls through to the NAICS sector exactly
    as an unrecognised description always has - a path that already exists and
    already means "no verdict", never a guess.
    """
    bucket = term_match.sole_bucket(
        tuple(_OPS_INDUSTRY_KEYWORDS.items()), ops, plural=True,
        require_subject=True)
    if bucket:
        return bucket
    return _NAICS_SECTOR_INDUSTRY.get(naics2)


# NCCI STANDARD EXCEPTION classes - clerical (8810), outside sales (8742),
# clerical telecommuter (8871) and drivers (7380). They sit BESIDE the
# governing class on nearly every workers comp policy and say nothing about
# what the business does.
#
# LIVE RUN 2026-08-26 (P2 printing company, P4 bakery): each printed its
# governing class (4299 / 2003, neither in the table below) PLUS 8810. Only
# 8810 mapped, so the account read as "office", disagreed with its own
# operations, and Exposure charged -15 for a class/operations mismatch on two
# clean submissions.
#
# THE EXCLUSION IS CONDITIONAL, and the distinction matters: a policy whose
# ONLY class is 8810 has no governing class, so for a roofing contractor that
# IS the mismatch the client asked us to catch (his own example, pinned by
# tests/test_workstream3_closure.py::test_wi5_roofing_ops_with_office_code_is_
# mismatch). A standard exception is discounted only when a real class sits
# beside it.
_WC_STANDARD_EXCEPTION_CODES: frozenset = frozenset({"8810", "8742", "8871", "7380"})

# A class code as printed: 4 digits (WC / NCCI) or 5 (GL / ISO), standing on
# its own. The word boundaries matter: a payroll of "540300" must NOT yield the
# roofing code 5403, which is exactly the blob-substring defect rule 2 exists
# to close.
_CLASS_CODE_TOKEN_RE = re.compile(r"\b\d{4,5}\b")


def _class_code_tokens(codes: Any) -> set:
    """Every class code in a `wc_class_codes` / `gl_class_codes_by_location`
    fact, read from the STRUCTURE rather than a stringified blob.

    A cell often carries the description alongside the number ("2003 Bakeries"),
    which is why this scans each cell for code-shaped tokens rather than
    demanding the whole cell be one. Returns an empty set when the shape is
    unrecognised, which the caller treats as "cannot tell".
    """
    out: set = set()

    def _take(val: Any) -> None:
        for tok in _CLASS_CODE_TOKEN_RE.findall(str(val or "")):
            out.add(tok)

    if isinstance(codes, str):
        _take(codes)
        return out
    if isinstance(codes, dict):
        # A state-keyed map ({"OR": [rows...]}) - recurse ONE level onto the
        # rows so a legitimate shape is not silently unreadable.
        for _v in codes.values():
            out |= _class_code_tokens(_v)
        return out
    if not isinstance(codes, list):
        return out
    for row in codes:
        if isinstance(row, dict):
            # NAMED keys only. Deliberately NOT a scan of every cell: a
            # description ("2026 remodel") or a payroll (540300) would then
            # vote, which is the blob defect this function exists to prevent.
            for _k in ("code", "class_code", "wc_class_code", "governing_class"):
                _take(row.get(_k))
            inner = row.get("codes")
            if isinstance(inner, list):
                for c in inner:
                    _take(c)
            elif inner is not None:
                _take(inner)
        else:
            _take(row)
    return out


def _codes_to_industry(code_str: str, tokens: Optional[set] = None) -> Optional[str]:
    """Industry bucket from class codes - only when the GOVERNING classes agree
    on ONE industry and every one of them is mapped.

    Three rules, and the third is the one that keeps this honest:

    1. Standard exceptions do not vote when a governing class sits beside them
       (they sit on nearly every WC policy and describe nobody's business). A
       LONE exception IS the governing class and does vote.
    2. The vote is taken over the TOKENS, never `code in code_str`. The blob
       carries payroll, rates, ZIPs and descriptions, so a table code could be
       matched inside a payroll figure - "5403" lives inside "540300".
    3. **An unmapped governing class means NO VERDICT.** The table is a
       deliberately conservative subset, so an unmapped primary class means we
       do not know what this business does - and guessing from whatever
       secondary class happens to be mapped is how a clean wholesale bakery
       with a retail shop (2003 unmapped + 8017 retail + 8810) would be charged
       -15 for "not a retailer". Silence is the only defensible answer, and it
       makes the table monotone: adding a correct code can only ever ADD a
       verdict, never move one sideways.
    """
    if not tokens:
        # NO VERDICT. This branch used to keep "the legacy blob read, unchanged,
        # so a fact we cannot parse behaves exactly as it did before this
        # function existed" - which preserved the very defect rules 2 and 3
        # exist to close, for precisely the inputs we understand least.
        #
        # LIVE RUN 2026-08-27: two clean packages (a bakery and a printer) were
        # each charged -15 for a class/operations mismatch, because on this path
        # NCCI 8810 "Clerical" was the only substring that matched and the
        # account was declared an office. `{"class_code":"2003",
        # "payroll":"540300"}` came back "construction" - class 5403 matched
        # INSIDE the payroll figure, the exact H1-F defect.
        #
        # `_class_code_tokens`' docstring already promised the caller treats an
        # empty set as "cannot tell"; the caller simply did not. A shape we
        # cannot PARSE is strictly less knowable than an unmapped code, so
        # rule 3 applies with more force here, not less.
        return None

    governing = {t for t in tokens if t not in _WC_STANDARD_EXCEPTION_CODES}
    pool = governing or set(tokens)          # a lone exception is the governing class
    if any(t not in _CLASS_CODE_INDUSTRY for t in pool):
        return None                          # rule 3: unmapped primary -> no verdict
    industries = {_CLASS_CODE_INDUSTRY[t] for t in pool}
    return next(iter(industries)) if len(industries) == 1 else None


def _is_ops_class_code_mismatch(facts: dict, flags: dict, coverage_type: str = "gl") -> bool:
    """Detect a material mismatch between operations description and class codes.

    Fires only when the operations clearly indicate one industry and the class
    codes clearly indicate a different, mutually exclusive industry (client
    Exposure Consistency: "GL/WC Class Code Does Not Match Operations -15").
    Conservative by design: requires BOTH an operations description AND the
    relevant class codes to be present and individually classifiable, so an
    unmapped value never manufactures a false deduction.
    """
    ops = str(_fv(facts, "operations_description") or "").lower()
    if not ops:
        return False
    naics2  = str(_fv(facts, "naics_code") or "")[:2]
    ops_ind = _ops_to_industry(ops, naics2)
    if not ops_ind:
        return False

    # The GL codes are the ONE door's (`gl_class_codes`, 27 Oct 2026, Lane B
    # item 1): a person's saved GL window first (`person_gl_class_codes`, 21
    # Oct), then BOTH homes, minus another line's codes. This read
    # `gl_class_codes_by_location` alone, so a package whose codes live in the
    # schedule (the declarations' class table, the GL window) was never judged.
    codes = (gl_class_codes(facts) if coverage_type == "gl"
             else _fv(facts, "wc_class_codes"))
    if not codes or (isinstance(codes, list) and not codes):
        return False
    code_ind = _codes_to_industry(str(codes), _class_code_tokens(codes))
    if not code_ind:
        return False

    return code_ind != ops_ind


# Two producers spell a non-blocking cross-form issue differently:
# cross_form_validator.py emits "soft_warning"; the older cross_validate() in
# this module emits "warning". Anything that filters cross issues by severity
# MUST accept both - matching only one silently drops that producer's warnings
# on the floor, which is how the P2 exposure penalty came to ignore every
# cross-form warning on the paths already using cross_form_validator.
# "advisory" is deliberately NOT included: advisories (UM/UIM not specified,
# ACORD 101 recommended) are informational and have never carried a penalty.
_CROSS_WARNING_TYPES = ("warning", "soft_warning")
_CROSS_ISSUE_TYPES   = ("hard_stop",) + _CROSS_WARNING_TYPES


def _auto_liability_stated(facts: dict) -> bool:
    """CSL or split limits - one door (`coverage_evidence`), falls back to the
    CSL-only read if the door is unavailable."""
    try:
        from services.coverage_evidence import auto_liability_stated
        return auto_liability_stated(facts)
    except Exception:                                          # noqa: BLE001
        return bool(_fv(facts, "auto_liability_limit"))


def _owned_vehicle_items_not_applicable(facts: dict, flags: Optional[dict] = None) -> bool:
    """Is this a hired/non-owned-only auto account, so the owned-vehicle
    checklist items do not apply? One door; fails toward "they apply", which
    keeps today's scoring on anything the door cannot classify."""
    try:
        from services.coverage_evidence import AUTO_HNOA_ONLY, auto_exposure_kind
        return auto_exposure_kind(facts, flags) == AUTO_HNOA_ONLY
    except Exception:                                          # noqa: BLE001
        return False


def _umbrella_schedule_present(facts: dict) -> bool:
    """A schedule of underlying insurance that is actually there - a stored
    sentence saying "was not supplied" is an ABSENCE (live P1, Principle 3)."""
    try:
        from services.coverage_evidence import umbrella_schedule_present
        return umbrella_schedule_present(facts)
    except Exception:                                          # noqa: BLE001
        return bool(_fv(facts, "schedule_of_underlying_insurance"))


# The Exposure Consistency buckets in plain words - the client-approved names
# the SQS panel prints on each sub-row. ONE table (1 Oct 2026, Orbin item 19):
# the panel's sub-rows and the Best Solutions action that names a weak bucket
# both read it, so the action never shows an internal key ("auto completeness,
# operations description") the panel calls something else.
#
# A label names what the bucket CHARGES FOR (Choice Electric #26, 10 Oct 2026).
# Brent's Exposure read "Operations -20" on a package whose operations
# description was fine - the -20 was "no GL class codes" - and "Cross-Document
# Consistency -20" on a package whose documents agreed - the -20 was two
# cross-form hard stops (Minimum Viable COPE, Period of Restoration), which are
# required-value rules, not disagreements. So:
#   * `operations_description` charges GL / WC class codes (missing, or not
#     matching the operations described) and a contractor's subcontracting %;
#   * `cross_document_consistency` charges every cross-form check the
#     validator raised (-15 a hard stop, -5 a warning, capped at 20) -
#     a disagreement between documents is one kind of those, not the only one.
# The KEYS stay: stored payloads, the C3 trace and the tests key on them.
EXPOSURE_BUCKET_LABELS: Dict[str, str] = {
    "operations_description":       "Class Codes & Operations",
    "coverage_information":         "Coverage Info",
    "payroll_employee_information": "Payroll/Employee",
    "revenue_sales_information":    "Revenue/Sales",
    "cross_document_consistency":   "Cross-Form Checks",
    "auto_completeness":            "Auto Completeness",
    "wc_supplemental":              "WC Supplemental",
    "cross_form_details":           "Cross-Form Details",
}

# What a payload scored before a rename printed, so a stored run reads today's
# words without a recalculation (`with_current_bucket_labels`). History only -
# add a line here whenever a label above changes.
_RENAMED_EXPOSURE_LABELS: Dict[str, str] = {
    "Operations":                 "operations_description",
    "Cross-Document Consistency": "cross_document_consistency",
}


def _words_list(items: List[str]) -> str:
    """"a", "a and b", "a, b, and c" - a list a person reads in one sentence."""
    items = [str(i) for i in items if str(i or "").strip()]
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + ", and " + items[-1]


def exposure_bucket_label(key: str) -> str:
    """The plain name of one Exposure bucket. A bucket missing from the table
    still reads as words, never as its snake_case key."""
    return EXPOSURE_BUCKET_LABELS.get(key) or str(key).replace("_", " ").title()


def with_current_bucket_labels(package: Optional[dict]) -> Optional[dict]:
    """A STORED package score with its Exposure rows named by today's table.

    Labels are display. A payload scored before a rename keeps the old words in
    `category_breakdown` and in the Best Solutions "Incomplete: ..." action
    until its next recalculation, so a reopened run would print "Operations"
    beside the new "-20 pts". This rewrites only those words, on a copy - the
    caller's dict, every score, every key and every other string are untouched.
    """
    if not isinstance(package, dict):
        return package
    out = package
    cb = package.get("category_breakdown")
    cats = cb.get("exposure_consistency") if isinstance(cb, dict) else None
    if isinstance(cats, dict):
        fresh = {
            k: ({**v, "label": EXPOSURE_BUCKET_LABELS[k]}
                if isinstance(v, dict) and k in EXPOSURE_BUCKET_LABELS
                and v.get("label") != EXPOSURE_BUCKET_LABELS[k] else v)
            for k, v in cats.items()
        }
        if any(fresh[k] is not cats[k] for k in cats):
            out = dict(out)
            out["category_breakdown"] = {**cb, "exposure_consistency": fresh}
    recs = package.get("top_recommendations")
    if isinstance(recs, list):
        prefix = "Incomplete: "
        changed = False
        new_recs = []
        for r in recs:
            act = r.get("action") if isinstance(r, dict) else None
            if (isinstance(act, str) and act.startswith(prefix)
                    and r.get("pillar") == "exposure_consistency"):
                names = [n.strip() for n in act[len(prefix):].split(",")]
                renamed = [exposure_bucket_label(_RENAMED_EXPOSURE_LABELS[n])
                           if n in _RENAMED_EXPOSURE_LABELS else n for n in names]
                if renamed != names:
                    r = {**r, "action": prefix + ", ".join(renamed)}
                    changed = True
            new_recs.append(r)
        if changed:
            out = dict(out) if out is package else out
            out["top_recommendations"] = new_recs
    return out


def _calculate_exposure_consistency(
    facts: dict,
    flags: dict,
    hard_cross: list,
    warn_cross: list,
) -> Tuple[int, Dict[str, int]]:
    """P2 - Exposure Consistency (25%), spec-compliant field-level scoring.

    Per Decision_Tree.txt L533, L90-95, L121-122, L143-150, L458, L539:
    deterministic negative/positive deltas per check rather than a single
    pooled penalty. Each underwriting-relevant alignment is evaluated
    independently so the user can see *which* gap drives the score down.

    Returns (score, subscores) where subscores carries a per-CLIENT-SUB-CATEGORY
    score (Operations / Coverage / Payroll-Employee / Revenue-Sales /
    Cross-Document). The expandable SQS breakdown renders these so the detail the
    user sees is the SAME input that produced the headline (client directive:
    "make the subcategories reflect the actual scoring inputs"). The headline is
    100 minus the sum of all buckets - identical to the prior flat computation.
    """
    items = exposure_deduction_items(facts, flags, hard_cross, warn_cross)
    ded = {k: 0 for k in _EXPOSURE_BUCKETS}
    for it in items:
        # A bucket outside the fixed list (the claims - `claim_checks`, 21 Oct
        # 2026) is a row of its own, only when it charges something.
        ded[it["bucket"]] = ded.get(it["bucket"], 0) + it["points"]
    # Headline = 100 minus all buckets (identical to the prior flat computation).
    score = max(0, min(100, 100 - sum(ded.values())))
    subscores = {k: max(0, 100 - v) for k, v in ded.items()}
    return score, subscores


# The Exposure buckets, in the order the breakdown lists them.
_EXPOSURE_BUCKETS: Tuple[str, ...] = (
    "operations_description",
    "coverage_information",
    "payroll_employee_information",
    "revenue_sales_information",
    "cross_document_consistency",
    # 19 Oct 2026: "auto_completeness" (6.3, capped at 25) and
    # "wc_supplemental" (6.4, capped at 10) hold only MISSING details - they
    # are Completeness buckets now (`completeness_deduction_items`).
)


# Cross-form checks that compare two DOCUMENTED exposures (19 Oct 2026). Brent:
# "Exposure Consistency deducts only for independently identified conflicts
# between documented exposures - missing information alone is not an exposure
# inconsistency." These keep their Exposure points; every other cross-form
# check asks for a missing detail (or a decision) and is charged under
# Completeness - unless a pillar already charges the same fact, which would be
# the same missing information penalised twice (`coverage_deduction_items`).
# Pinned against `cross_form_validator.rule_codes()` by test.
_CROSS_FORM_CONFLICT_CODES: frozenset = frozenset({
    "wc_payroll_mismatch", "wc_payroll_vs_revenue", "wc_subcontracting_payroll_conflict",
    "location_count_mismatch_minor", "location_count_mismatch", "location_address_mismatch",
    "umbrella_gl_period_misaligned", "umbrella_gl_expiration_misaligned",
    "umbrella_auto_period_misaligned", "umbrella_auto_expiration_misaligned",
    "umbrella_wc_period_misaligned", "builders_risk_property_duplication",
    "wc_state_payroll_total_mismatch", "auto_owned_fleet_not_covered_by_symbol",
    "acord186_high_sub_high_wc_payroll", "wc_gl_class_code_mismatch",
})
# The package's own building-value cross item (a value the documents disagree
# on - an exposure) has no rule code; it is known by its field.
_CROSS_CONFLICT_FIELDS: frozenset = frozenset({"property_building_value"})


def _cross_is_conflict(issue: Any) -> bool:
    if not isinstance(issue, dict):
        return False
    code = str(issue.get("code") or "")
    return code in _CROSS_FORM_CONFLICT_CODES or (
        not code and str(issue.get("field") or "") in _CROSS_CONFLICT_FIELDS)


def _facts_other_pillars_charge(facts: dict, flags: dict) -> set:
    """The facts Property, Umbrella and the Tier 1 / Tier 2 checklist already
    deduct for - a cross-form check asking for one of them adds nothing."""
    out: set = set()
    for builder in (property_gap_items, umbrella_gap_items):
        try:
            out |= {str(i["fact"]) for i in builder(facts, flags) or [] if i.get("fact")}
        except Exception:                                      # noqa: BLE001
            pass
    try:
        for keys, _label in (_tier1_entries(facts, flags)[1] + _tier2_entries(facts)[1]):
            out |= {str(k) for k in (keys or ())}
    except Exception:                                          # noqa: BLE001
        pass
    return out


def _cross_issue_facts(issue: dict) -> set:
    res = issue.get("resolution") if isinstance(issue, dict) else None
    if not isinstance(res, dict):
        try:
            from services.issue_registry import resolution_for
            res = resolution_for(str(issue.get("code") or "")) or {}
        except Exception:                                      # noqa: BLE001
            res = {}
    out = {str(f) for f in (res.get("facts") or []) if f}
    # A check whose fix is a TABLE asks for that table's fact (19 Oct 2026):
    # the WC by-state breakdown IS the class table a coverage item already
    # charges, the agreed-value vehicle schedule the vehicle table.
    if res.get("schedule_key"):
        out.add(str(res["schedule_key"]))
    return out


# ── THE SAFETY NET: NO POINT IS LOST THAT THE PAGE CANNOT GIVE BACK (27 Oct 2026) ──
# Owner's rule: answering everything the pre-form screen asks reaches exactly 100.
# The first line of defence is that every deduction and every warning carries an
# answer that clears it (the reach-100 solver, `tests/test_reach_100_every_package`).
# This is the backstop for the case that slips through: a pillar deduction naming
# no box a person can answer, or a warning hold whose card offers no answer, is NOT
# charged. Decided here, inside the scorer, so the first number the page shows is
# already right - nothing jumps later. Each one is logged loudly (SQS_NOT_SCORED,
# with its rule) so the missing question gets built, and listed on the package's
# `not_scored` for the underwriter's cover. Hard stops are never released: each of
# the five kinds keeps a real answer.
import contextvars as _contextvars
_NOT_SCORED = _contextvars.ContextVar("sqs_not_scored", default=None)
_CARD_FIXED_BUCKETS = ("cross_document_consistency", "cross_form_details")
_ANSWER_MODES = ("field", "schedule", "narrative")


def _record_not_scored(entry: dict) -> None:
    logger.warning("SQS_NOT_SCORED: %s", entry)
    sink = _NOT_SCORED.get()
    if isinstance(sink, list) and entry not in sink:
        sink.append(entry)


def _item_is_answerable(item: dict) -> bool:
    if item.get("bucket") in _CARD_FIXED_BUCKETS:
        return True                       # the cross-form cards carry their own fixes
    fact = item.get("fact")
    if not fact:
        return False
    try:
        from services.answer_routing import answer_mode
        return (answer_mode(str(fact)) or {}).get("mode") in _ANSWER_MODES
    except Exception:                                          # noqa: BLE001
        return True                       # cannot tell: charge it, as before


def charge_only_answerable(items: List[dict], pillar: str) -> List[dict]:
    """`items` less the deductions no box on the page can answer (each recorded)."""
    kept: List[dict] = []
    for item in items or []:
        if not isinstance(item, dict) or _item_is_answerable(item):
            kept.append(item)
            continue
        _record_not_scored({"pillar": pillar, "points": int(item.get("points") or 0),
                            "label": str(item.get("label") or ""), "fact": item.get("fact"),
                            "rule": item.get("bucket") or pillar})
    return kept


def release_unanswerable_holds(messages: List[str], cross_issues: Optional[List[dict]]) -> List[str]:
    """The warning messages that may hold the 85: those whose card offers no answer
    (a known rule whose resolution is mode "none", never a form choice) are
    released and recorded. A message whose rule cannot be told keeps holding."""
    by_message = {str(i.get("message")): i for i in (cross_issues or [])
                  if isinstance(i, dict) and i.get("message")}
    try:
        from services.issue_registry import classify_legacy, resolution_for
    except Exception:                                          # noqa: BLE001
        return list(messages or [])
    out: List[str] = []
    for msg in messages or []:
        issue = by_message.get(str(msg))
        if issue is not None and issue.get("form_choice"):
            out.append(msg)
            continue
        code = (issue or {}).get("code")
        if not code:
            try:
                code = classify_legacy(str(msg), "soft")[0]
            except Exception:                                  # noqa: BLE001
                code = None
        res = resolution_for(code) if code else None
        if isinstance(res, dict) and res.get("mode") == "none":
            _record_not_scored({"pillar": "hold_85", "points": None, "label": str(msg)[:200],
                                "fact": None, "rule": code})
            continue
        out.append(msg)
    return out


def exposure_deduction_items(
    facts: dict,
    flags: dict,
    hard_cross: list,
    warn_cross: list,
) -> List[dict]:
    """Every Exposure Consistency deduction - since 19 Oct 2026 the CONFLICTS
    only (Brent: "Exposure Consistency deducts only for independently
    identified conflicts between documented exposures"): {bucket, points,
    fact, label, kind}. `_calculate_exposure_consistency` sums these."""
    return [i for i in coverage_deduction_items(facts, flags, hard_cross, warn_cross)
            if i.get("kind") == "conflict"]


def completeness_deduction_items(
    facts: dict,
    flags: dict,
    hard_cross: list,
    warn_cross: list,
) -> List[dict]:
    """The coverage details Completeness deducts for (19 Oct 2026): what used to
    be Exposure's MISSING items - the same points Brent approved, now under
    Structural Completeness ("Completeness deducts for missing applicable
    required information"). Both pillars weigh 25%, so the move moves no
    package point except where a pillar floors at 0."""
    return [i for i in coverage_deduction_items(facts, flags, hard_cross, warn_cross)
            if i.get("kind") == "missing"]


def coverage_deduction_items(
    facts: dict,
    flags: dict,
    hard_cross: list,
    warn_cross: list,
) -> List[dict]:
    """Every coverage-detail deduction, ONE item each: {bucket, points, fact,
    label, kind} (13 Oct 2026 - the SQS reaches 100 when everything is
    answered; `kind` since 19 Oct 2026). `kind` "conflict" items are Exposure
    Consistency (`exposure_deduction_items`), "missing" items Completeness
    (`completeness_deduction_items`) - the pillars sum them, so the score and
    the questions that close it cannot drift apart. `fact` is the box that
    answers the item (None: a coverage decision, or the cross-form cards, which
    carry their own fix); `label` names it in a person's words. A capped bucket
    lists its items in rule order until the cap is reached.
    """
    items: List[dict] = []

    def _add(bucket: str, points: int, fact: Optional[str], label: str,
             kind: str = "missing", also: Tuple[str, ...] = ()) -> None:
        if points:
            item = {"bucket": bucket, "points": int(points),
                    "fact": fact, "label": label, "kind": kind}
            if also:
                # The other side of a comparison (SCORING_RULES.md I1): the
                # row's window offers it too, so the person can correct
                # whichever side is wrong.
                item["also_facts"] = list(also)
            items.append(item)

    # A class-code mismatch compares the codes with the operations described
    # (the description, else the NAICS sector): both are the row's to correct.
    _OPS_SIDES = ("operations_description", "naics_code")

    def _add_capped(bucket: str, gaps, cap: int) -> None:
        # EVERY GAP IS LISTED (owner rule G2, 30 Oct 2026). The bucket used to
        # list its gaps in rule order until the cap was reached, so the gaps past
        # the cap (garaging, radius, vehicle use behind a missing vehicle and
        # driver schedule) appeared only once an earlier one was answered - a
        # correct answer raised a new item. Now each gap is an item; when they
        # add up to more than the cap, the cap is shared by their own points
        # (largest remainder, each at least 1 while the cap allows), so the
        # items still add up to exactly what the bucket charges.
        gaps = [(f, int(p), l) for f, p, l in (gaps or []) if int(p) > 0]
        if not gaps or int(cap) <= 0:
            return
        total = sum(p for _f, p, _l in gaps)
        cap_now = min(int(cap), total)
        if total <= cap_now:
            shares = [p for _f, p, _l in gaps]
        else:
            floor_each = 1 if cap_now >= len(gaps) else 0
            spread = cap_now - floor_each * len(gaps)
            quotas = [p * spread / total for _f, p, _l in gaps]
            shares = [floor_each + int(q) for q in quotas]
            for n in sorted(range(len(gaps)), key=lambda n: -(quotas[n] - int(quotas[n])))[
                    :cap_now - sum(shares)]:
                shares[n] += 1
        for (fact, _pts, label), take in zip(gaps, shares):
            # The rule tables word a gap as its absence ("No radius of
            # operation"); a row names what to answer ("Radius of operation").
            label = str(label or "")
            if label.startswith("No ") and len(label) > 3:
                label = label[3].upper() + label[4:]
            _add(bucket, take, fact, label)

    # ── GL: class codes vs operations (L90, L92) ─────────────────────────────
    #
    # C3 (owner ruling, 2026-08-25): the two "operations description is MISSING"
    # deductions that used to live here are GONE. `operations_description` is an
    # explicit C3 3.5 Tier 2 field, so its absence is already scored in
    # Structural Completeness; charging it again here punished one gap twice -
    # the exact thing the client's Current Problem list asks us to be able to
    # rule out ("whether a deduction is being counted more than once").
    #
    # What REMAINS here is not the same measurement, and must not be removed:
    #   * missing CLASS CODES (-20) is a different fact, scored nowhere else;
    #   * the MISMATCH (-15) requires operations_description to be PRESENT, so
    #     it can never fire on the same condition Tier 2 is charging for. It is
    #     a consistency check, which is what this pillar is for.
    if flags.get("has_general_liability"):
        # ONE reader (6 Oct 2026, Choice Electric #26): both homes, minus the
        # codes another line's rating owns - the same answer `evaluate_stops`
        # gives. This copy read `gl_class_codes_by_location` alone.
        codes_present = gl_class_codes_present(facts)
        if not codes_present:
            _add("operations_description", 20, "gl_class_codes_by_location", "GL class codes")
        elif _is_ops_class_code_mismatch(facts, flags, "gl"):
            # GL class code does not match operations description
            _add("operations_description", 15, "gl_class_codes_by_location",
                 "GL class codes that match the operations described", "conflict", _OPS_SIDES)
        if not _answered(facts, "gl_limits") and not _answered(facts, "gl_each_occurrence"):
            _add("coverage_information", 8, "gl_each_occurrence", "GL each occurrence limit")

    # ── Payroll / revenue exposure base (L41, L121) ──────────────────────────
    #
    # C3 (owner ruling, 2026-08-25): the flat -15 for "no payroll AND no
    # revenue anywhere" is GONE, and this is the more delicate of the two
    # de-duplications, so the reasoning is recorded in full.
    #
    # `total_revenue` is an explicit C3 3.5 Tier 2 field, so its absence is
    # already scored in Structural. The -15 charged it a second time. But the
    # same deduction was also the ONLY place PAYROLL was scored once C3 3.14
    # removed `total_payroll` from Tier 2 - so deleting it naively would have
    # left payroll scored nowhere at all, contradicting 3.14's own instruction
    # that these fields are *"handled through WC/Exposure rules instead"*.
    #
    # Resolved by giving each fact exactly one home, which is what the client's
    # own principle asks for:
    #   * revenue  -> Structural Tier 2, and only there;
    #   * payroll  -> the WC bucket immediately below ("WC coverage with no
    #     payroll", -12), plus the "GL coverage detected but no revenue or
    #     payroll found" warning in evaluate_stops, which is a CEILING and not a
    #     deduction (3.9 and spec section 7 both keep those separate).
    # A GL-only account is revenue-rated and a WC account is payroll-rated, so
    # neither loses a check that was ever meaningful for it.

    # ── Revenue-to-payroll outlier detection ─────────────────────────────────
    # Client examples that MUST flag: $10M revenue with $25K payroll (ratio
    # 0.0025) and $500K revenue with $4M payroll (ratio 8.0). The prior low-side
    # gate (ratio < 0.005 AND payroll < $25K) missed the first example because
    # $25K is not strictly < $25K. Payroll under 1% of revenue is the real signal.
    _rev  = _to_float(_fv(facts, "total_revenue"))
    _pay  = _to_float(_fv(facts, "total_payroll") or _fv(facts, "wc_payroll"))
    if _rev and _pay and _rev > 0 and _pay > 0:
        _ratio = _pay / _rev
        if _ratio > 2.0:
            # Payroll is 200%+ of revenue - very unusual
            _add("revenue_sales_information", 10, "total_payroll",
                 "Payroll is more than twice the revenue - check both figures", "conflict")
        elif _ratio < 0.01:
            # Payroll under 1% of revenue - suspiciously low
            _add("revenue_sales_information", 5, "total_payroll",
                 "Payroll is under 1% of revenue - check both figures", "conflict")

    # ── WC: payroll + class codes + multi-state (L121, L143-150) ─────────────
    if flags.get("has_workers_comp"):
        if not _answered(facts, "wc_payroll") and not _answered(facts, "total_payroll"):
            _add("payroll_employee_information", 12, "wc_payroll", "Workers comp payroll")
        if not _answered(facts, "wc_class_codes"):
            _add("operations_description", 10, "wc_class_codes", "Workers comp class codes")
        elif _is_ops_class_code_mismatch(facts, flags, "wc"):
            # WC class code does not match operations description
            _add("operations_description", 15, "wc_class_codes",
                 "Workers comp class codes that match the operations described", "conflict", _OPS_SIDES)
        if flags.get("wc_multi_state") and not _answered(facts, "wc_payroll_by_state"):
            # The breakdown by state IS the class table (V1 H3).
            _add("payroll_employee_information", 8, "wc_class_codes",
                 "Workers comp payroll by state")

    # ── Contractor: subcontracting % reconciliation (L91, L458) ──────────────
    if flags.get("is_contractor") or flags.get("has_subcontractors"):
        if not _answered(facts, "percent_subcontracted"):
            _add("operations_description", 8, "percent_subcontracted",
                 "Percent of work subcontracted")

    # ── Auto: liability structure + symbols (L184-191) ───────────────────────
    if flags.get("has_auto_coverage"):
        # STATED as a CSL or as split limits - a split policy has no CSL by
        # design and was charged -10 for "no liability limit" (live P5).
        if not _auto_liability_stated(facts):
            _add("coverage_information", 10, "auto_liability_limit", "Auto liability limit")
        if not _answered(facts, "auto_covered_symbols"):
            _add("coverage_information", 5, "auto_covered_symbols", "Covered auto symbols")

    # ── V1 H1 6.3 - Auto Completeness (owned / scheduled exposure only) ─────
    # Client: "an incomplete ACORD 127 can receive a poor individual form score
    # without necessarily reducing total submission quality enough." The five
    # items and their points are his table verbatim; the cap is his -25; the
    # owned-versus-HNOA gate and the "presumed owned" default are recorded in
    # `services.coverage_evidence` (the ONE door - evaluate_stops, the 127
    # checklist and the questionnaire read the same answer). "Existing Auto
    # deductions remain separately applicable" - the two above are untouched.
    # A genuinely hired/non-owned-only account deducts nothing here.
    try:
        from services.coverage_evidence import (
            AUTO_COMPLETENESS_CAP, auto_completeness_gaps,
        )
        _add_capped("auto_completeness", auto_completeness_gaps(facts, flags),
                    AUTO_COMPLETENESS_CAP)
    except Exception as _ace:                                  # noqa: BLE001
        logger.warning("auto completeness skipped: %s", _ace, exc_info=True)

    # ── V1 H1 6.4 - Supplemental WC (X-Mod, officer treatment, payroll period)
    # These left Structural Tier 2 under C3 3.14 and had NO package-level home
    # (only the ACORD 130 checklist). Client's rules: X-Mod -5 only when
    # applicability is INDICATED and the factor is missing (unknown -> producer,
    # New Venture / not rated / N/A -> nothing); owner/officer -5 when named
    # individuals exist and their treatment is unresolved; payroll period -3
    # when a stated figure's period cannot be interpreted. Combined cap -10.
    # "This cap does not replace existing WC payroll/class/multi-state
    # deductions" - those stay in the buckets above.
    try:
        from services.coverage_evidence import (
            WC_SUPPLEMENTAL_CAP, wc_supplemental_gaps,
        )
        _add_capped("wc_supplemental", wc_supplemental_gaps(facts, flags),
                    WC_SUPPLEMENTAL_CAP)
    except Exception as _wse:                                  # noqa: BLE001
        logger.warning("wc supplemental skipped: %s", _wse, exc_info=True)

    # ── Exposure-coverage gaps (employees without WC, vehicles without auto) ─
    _num_emp = _to_int(_fv(facts, "num_employees"))
    # A coverage decision the PRODUCER states (27 Oct 2026, owner: answering
    # everything reaches 100): "no box" left a package with 6 employees and no
    # WC policy at 97 whatever was answered. Any answer settles the question.
    if _num_emp and _num_emp > 5 and not _wc_carried(flags) \
            and not _answered(facts, "workers_comp_arrangement"):
        _add("payroll_employee_information", 8, "workers_comp_arrangement",
             "Employees are listed but no workers comp coverage is carried", "conflict")

    _has_vehicle_exposure = bool(
        _fv(facts, "auto_vin_schedule")
        or _fv(facts, "vehicle_schedule")
        or flags.get("auto_vehicles_detected")
    )
    if _has_vehicle_exposure and not flags.get("has_auto_coverage") \
            and not _answered(facts, "auto_coverage_arrangement"):
        _add("coverage_information", 8, "auto_coverage_arrangement",
             "Vehicles are listed but no auto coverage is carried", "conflict")

    # ── Claims (Brent 17 Oct attachment C, 21 Oct 2026) ─────────────────────
    # A claim that contradicts itself or the package's schedules is a conflict
    # (Exposure Consistency); a detail it leaves out is missing (Completeness);
    # one finding, one charge (`claim_checks`, the one reader of the claims).
    # Deductions only - never a stop or a warning (owner, 21 Oct).
    try:
        from services.claim_checks import claim_deduction_items
        items.extend(claim_deduction_items(facts, flags))
    except Exception as _cce:                                  # noqa: BLE001
        logger.warning("claim checks skipped: %s", _cce, exc_info=True)

    # ── THE SAME MISSING FACT NEVER TWICE (19 Oct 2026, Brent) ──────────────
    # A detail another pillar already charges for its own reason costs nothing
    # more here: on an umbrella package the Umbrella pillar charges the
    # underlying GL each-occurrence and auto liability limits (20 each), and
    # these items charged the same boxes again (8 / 10). One missing fact, one
    # pillar - the rule the cross-form detail checks follow (`_cross_split`).
    _elsewhere = _facts_other_pillars_charge(facts, flags)
    items[:] = [i for i in items if i.get("kind") != "missing" or not i.get("fact")
                or str(i["fact"]) not in _elsewhere]

    # ── Cross-form checks (-15 a hard stop, -5 a warning, at most 20 in all) ─
    # Each check has its own Hard Stop / Warning card - the card is the fix.
    # 19 Oct 2026: a check comparing two documented exposures stays in Exposure;
    # every other one asks for a detail and is charged under Completeness, ONLY
    # when no pillar already charges a fact it asks for (the same missing
    # information never twice). One shared 20, as before - conflicts first.
    conflicts, owed = _cross_split(facts, flags, hard_cross, warn_cross, items,
                                   charged_elsewhere=_elsewhere)
    exp_pen, miss_pen = _cross_points(conflicts, owed, hard_cross)
    if exp_pen:
        _add("cross_document_consistency", exp_pen, None,
             "Cross-form checks (see the hard stops and warnings)", "conflict")
    if miss_pen > 0:
        _add("cross_form_details", miss_pen, None,
             "Cross-form checks asking for details (see the warnings)", "missing")
    return charge_only_answerable(items, "coverage")


def _cross_points(conflicts: List[dict], owed: List[dict], hard_cross: list) -> Tuple[int, int]:
    """(Exposure's cross points, Completeness's cross-form-detail points): -15 a
    hard stop, -5 a warning, ONE shared 20 - conflicts first (19 Oct 2026)."""
    _hard_ids = {id(i) for i in (hard_cross or [])}

    def _pts(i) -> int:
        return 15 if id(i) in _hard_ids else 5

    exp_pen = min(sum(_pts(i) for i in conflicts), 20)
    miss_pen = max(0, min(sum(_pts(i) for i in owed), 20 - exp_pen))
    return exp_pen, miss_pen


def _cross_split(facts: dict, flags: dict, hard_cross: list, warn_cross: list,
                 items: List[dict], charged_elsewhere: set,
                 ) -> Tuple[List[dict], List[dict]]:
    """(the cross-form conflicts Exposure charges, the detail checks
    Completeness charges) - a detail check whose facts a pillar or one of
    `items` already charges is in neither (19 Oct 2026). `charged_elsewhere` =
    `_facts_other_pillars_charge` (the one caller computes it once)."""
    _all = [i for i in list(hard_cross or []) + list(warn_cross or []) if isinstance(i, dict)]
    conflicts = [i for i in _all if _cross_is_conflict(i)]
    others = [i for i in _all if not _cross_is_conflict(i)]
    if not others:
        return conflicts, []
    charged = {str(i["fact"]) for i in items or [] if i.get("fact")} | set(charged_elsewhere or ())
    return conflicts, [i for i in others if not (_cross_issue_facts(i) & charged)]


# ── Follow-form detection (Option B, client Q3) ──────────────────────────────
# Follow-form is coverage-critical and "should never be guessed" (client Q3).
# It is confirmed ONLY when documentation explicitly and AFFIRMATIVELY states it.
# A naive substring match would mis-read negations ("does not follow form") and
# interrogative / uncertain mentions ("unable to determine whether the umbrella
# follows form") as confirmations - so any match whose own clause carries a
# negation or uncertainty cue is rejected.
_FF_TERMS: Tuple[str, ...] = (
    "follow form", "follows form", "follow the form",
    "following form", "follows the underlying",
    "follow-form", "follows-form",
)
_FF_NEGATION_WORDS: frozenset = frozenset({
    "not", "never", "unable", "unclear", "unknown",
    "whether", "cannot", "except", "rather",
})


def _has_explicit_follow_form(text) -> bool:
    """True only when *text* affirmatively, explicitly states follow-form.

    Option B (client Q3): never infer follow-form. Any occurrence preceded -
    within its own clause - by a negation or uncertainty cue ("does not", "n't",
    "unable", "whether"...) is rejected so a coverage-critical status is never
    guessed from a negated or hypothetical mention.
    """
    if not text:
        return False
    t = str(text).lower()
    for term in _FF_TERMS:
        start = 0
        while True:
            idx = t.find(term, start)
            if idx == -1:
                break
            window = t[max(0, idx - 60):idx]
            # Restrict to the current clause so a negation in a PRIOR sentence
            # ("GL is not claims-made. Umbrella follows form.") never false-rejects.
            clause_cut = max(window.rfind(s) for s in (".", ";", "\n"))
            if clause_cut != -1:
                window = window[clause_cut + 1:]
            negated = ("n't" in window) or bool(
                set(re.findall(r"[a-z]+", window)) & _FF_NEGATION_WORDS
            )
            if not negated:
                return True
            start = idx + len(term)
    return False


# ── Umbrella evidence state (§6.5 item 1) ────────────────────────────────────

def _get_umbrella_state(facts: dict, flags: dict) -> str:
    """Return umbrella evidence state string per §6.5 item 1.

    6 states (client-approved; §6.5 retired "umbrella_information_provided"):
      not_applicable               – no umbrella in this submission
      insufficient_information     – has_umbrella flag but no umbrella_limit found
      unknown                      – limit present but no underlying GL/auto value found
      umbrella_coverage_needs_review – underlying limits below thresholds
      umbrella_coverage_present    – limits meet thresholds; zero or one supporting
                                     document present (schedule OR follow-form missing)
      adequately_supported         – limits, EL, schedule, and follow-form all confirmed
    """
    if not flags.get("has_umbrella"):
        return "not_applicable"
    umb_limit = _fv(facts, "umbrella_limit")
    if not umb_limit:
        return "insufficient_information"

    gl_val   = _to_int(_fv(facts, "gl_each_occurrence") or _fv(facts, "gl_limits"))
    auto_val = _to_int(_fv(facts, "auto_liability_limit"))
    # V1 H1 (2026-08-26): split limits state the underlying auto without a CSL
    # figure. The scorer and `evaluate_stops` were both updated to see that;
    # this state machine was not, so a split policy read "unknown - underlying
    # limits not found" while the score said 75 and no hard stop fired. This
    # docstring's own promise is that the state stays consistent with the score.
    _auto_split_stated = auto_val is None and _auto_liability_stated(facts)

    # Umbrella present but NO underlying GL/Auto value extracted. For this exact
    # input the scorer returns 0 and evaluate_stops raises a hard stop, so the
    # evidence state must read as a problem - never a benign "information provided"
    # label (§6.5: missing underlying must surface an Unknown / Insufficient
    # Information state, not a reassuring or perfect one). Both the no-flags and
    # flags-present variants score identically (0), so both map to "unknown"
    # ("underlying limits not found") to stay consistent with the score and stop.
    # The pillar's own door (21 Oct 2026): employers liability, the umbrella's
    # own schedule and the layer below count as underlying too.
    if not _umbrella_has_underlying(facts):
        return "unknown"
    _ul = _umb_lines(facts, flags)

    def _absent_required(fam: str) -> bool:
        # An EL limit in any of its own parts (`wc_el_*`) is not absent.
        return bool(_ul[fam]["applicable"]) and not _ul[fam]["schedule_numeric"] and not (
            fam == "workers_comp" and _ul[fam]["fact_numeric"])

    # Required-but-absent underlying coverage (mirror the score's -20 deduction):
    # a present coverage flag with no extracted limit cannot be validated against
    # the umbrella, so the evidence "needs review" rather than reading as complete.
    # Without this the state could report umbrella_coverage_present / adequately_
    # supported while the score is penalising the same missing limit (state/score
    # contradiction). Handled symmetrically for GL and Auto.
    # `_auto_split_stated` exempts the auto half: the scorer no longer takes
    # that -20 (the limit is stated, just not as a CSL), so mirroring it here
    # would recreate the contradiction this branch exists to prevent.
    if (gl_val is None and _absent_required("general_liab")) or \
       (auto_val is None and _absent_required("auto") and not _auto_split_stated):
        return "umbrella_coverage_needs_review"

    # GL must satisfy BOTH halves of the client baseline (occurrence $1M /
    # aggregate $2M); a below-baseline aggregate demotes the state so it cannot
    # contradict the matching score reduction.
    gl_agg  = _to_int(_fv(facts, "gl_aggregate"))
    gl_ok   = (gl_val is None or gl_val >= _UMB_GL_OCC_MIN) and \
              (gl_agg is None or gl_agg >= _UMB_GL_AGG_MIN)
    auto_ok = auto_val is None or auto_val >= _UMB_AUTO_CSL_MIN
    if not gl_ok or not auto_ok:
        return "umbrella_coverage_needs_review"

    if _ul["workers_comp"]["applicable"]:
        el_val = _to_int(_fv(facts, "employers_liability_limits"))
        if (el_val is None and _absent_required("workers_comp")) or \
                (el_val is not None and el_val < _UMB_EL_OK):
            return "umbrella_coverage_needs_review"

    # Underlying limits meet thresholds. Grade by how much supporting evidence
    # (schedule of underlying insurance + follow-form) corroborates the coverage:
    #   neither present → umbrella_coverage_present (client §6.5: limits meet thresholds
    #                       -> Coverage Present, even when schedule AND follow-form are
    #                       both missing; the old "Information Provided" state is retired)
    #   one present     → umbrella_coverage_present     (partially corroborated)
    #   both present    → adequately_supported
    _has_schedule = _umbrella_schedule_present(facts)
    _ff_combined = " ".join([
        _narrative_remarks_text(facts),
        str(_fv(facts, "umbrella_follow_form") or ""),
        str(_fv(facts, "policy_notes") or ""),
    ])
    _has_ff = _has_explicit_follow_form(_ff_combined)

    _support = (1 if _has_schedule else 0) + (1 if _has_ff else 0)
    if _support <= 1:
        # §6.5: "Umbrella Information Provided" is retired. Once underlying limits
        # meet thresholds, zero or one supporting document both read as Coverage
        # Present (schedule OR follow-form still missing).
        return "umbrella_coverage_present"
    return "adequately_supported"


def _get_follow_form_status(facts: dict) -> dict:
    """Option B (client Q4): only confirm follow-form when docs explicitly state it (§6.5 item 4)."""
    combined = " ".join([
        _narrative_remarks_text(facts),
        str(_fv(facts, "umbrella_follow_form") or ""),
        str(_fv(facts, "policy_notes") or ""),
    ])
    if _has_explicit_follow_form(combined):
        return {
            "status": "follow_form_confirmed",
            "message": "Follow form confirmed by submitted documents.",
        }
    return {
        "status": "unable_to_determine",
        "message": "Unable to determine whether umbrella follows form. Recommend underwriter review.",
    }


# ── Evidence label derivation (§6.1 item 3) ──────────────────────────────────

EVIDENCE_LABEL_DISPLAY: Dict[str, str] = {
    "extracted_from_source":   "Extracted from uploaded source document",
    "confirmed_by_user":       "Confirmed by user",
    "stated_in_narrative":     "Stated in narrative",
    "inferred":                "Inferred from business class",
    "not_found":               "Not found",
    "conflicting":             "Conflicting",
    "not_applicable":          "Not applicable",
    "requires_supporting_doc": "Requires supporting documentation",
}

_EVIDENCE_SOURCE_MAP: Dict[Optional[str], str] = {
    "deterministic": "extracted_from_source",
    "filled":        "extracted_from_source",
    "ai_high":       "extracted_from_source",
    "ai_low":        "inferred",
    "client_arq":    "confirmed_by_user",
    None:            "not_found",
}

# Fields that must NEVER be labelled "stated_in_narrative" even when the value
# physically appears inside a narrative-classified document. Three categories:
#   1. Identity / structural — always deterministic, never prose
#   2. Technical form fields — ISO symbols, VIN lists, class codes, WC mechanics;
#      these require exact structured sources, not narrative inference
#   3. Loss-run analytical fields — derived values, not prose-stated
_NEVER_NARRATIVE_KEYS: frozenset = frozenset({
    # Identity / structural
    "applicant_name", "mailing_address", "physical_address",
    "effective_date", "expiration_date",
    "fein", "entity_type", "producer_name",
    "naics_code", "sic_code", "lines_of_business",
    "contact_name", "contact_phone", "contact_email",
    # Technical / actuarial form fields — cannot be prose-stated
    "wc_class_codes", "gl_class_codes_by_location",
    "wc_xmod", "wc_payroll_period", "wc_officer_exclusions",
    "auto_covered_symbols", "auto_vin_schedule", "auto_drivers",
    "schedule_of_underlying_insurance", "umbrella_follow_form",
    # Loss-run analytical fields (derived, not prose-stated)
    "loss_run_age_days", "loss_history_years",
})

_SCORED_FACT_KEYS: Tuple[str, ...] = (
    # Tier 1 - Applicant Information
    "applicant_name", "mailing_address", "effective_date", "expiration_date",
    "lines_of_business", "entity_type", "producer_name",
    "contact_name", "contact_phone", "contact_email",
    # Tier 2 - Underwriting Information
    "fein", "operations_description",
    "total_revenue", "total_payroll", "num_employees", "years_in_business",
    "prior_carrier", "naics_code",
    "wc_xmod", "wc_class_codes", "wc_payroll", "wc_officer_exclusions", "wc_payroll_period",
    # Coverage limits
    "gl_limits", "gl_each_occurrence", "gl_aggregate",
    "auto_liability_limit", "auto_covered_symbols", "auto_vin_schedule",
    "umbrella_limit", "employers_liability_limits",
    # Property COPE
    "locations", "property_building_value", "property_bpp_value",
    "occupancy_type", "construction_type",
    "year_built", "roof_year", "sprinkler_system", "fire_protection_class",
    "valuation_method", "distance_to_hydrant", "fire_department_type",
    "business_income_limit",
    # Loss history
    "loss_history_years", "loss_run_age_days",
    "no_prior_losses", "loss_history_no_prior_losses_indicator", "num_claims",
    # Umbrella evidence
    "schedule_of_underlying_insurance", "umbrella_follow_form",
    # Narrative (read under either key - see _narrative_remarks_text)
    "acord101_remarks", "additional_remarks_text",
)


# §6.1 item 3 — evidence-basis gating for ABSENT facts. A coverage-specific fact
# that is absent reads as "not applicable" (not merely "not found") when its line
# of business is not in the submission. The umbrella underlying-schedule /
# follow-form and the loss-run years read as "requires supporting documentation"
# when they are absent and the document that would substantiate them is needed but
# not on file. Everything else stays "not found".
_COVERAGE_GATED_FACT_FLAGS: Dict[str, str] = {
    "gl_limits":                        "has_general_liability",
    "gl_each_occurrence":               "has_general_liability",
    "gl_aggregate":                     "has_general_liability",
    "auto_liability_limit":             "has_auto_coverage",
    "auto_covered_symbols":             "has_auto_coverage",
    "auto_vin_schedule":                "has_auto_coverage",
    "umbrella_limit":                   "has_umbrella",
    "schedule_of_underlying_insurance": "has_umbrella",
    "umbrella_follow_form":             "has_umbrella",
    "employers_liability_limits":       "has_workers_comp",
    "wc_xmod":                          "has_workers_comp",
    "wc_class_codes":                   "has_workers_comp",
    "wc_payroll":                       "has_workers_comp",
    "wc_officer_exclusions":            "has_workers_comp",
    "wc_payroll_period":                "has_workers_comp",
    "property_building_value":          "has_property_coverage",
    "property_bpp_value":               "has_property_coverage",
    "occupancy_type":                   "has_property_coverage",
    "construction_type":                "has_property_coverage",
    "year_built":                       "has_property_coverage",
    "roof_year":                        "has_property_coverage",
    "sprinkler_system":                 "has_property_coverage",
    "fire_protection_class":            "has_property_coverage",
    "valuation_method":                 "has_property_coverage",
    "distance_to_hydrant":              "has_property_coverage",
    "fire_department_type":             "has_property_coverage",
    "business_income_limit":            "has_property_coverage",
}
# Absent + the substantiating document is needed but not on file → requires_supporting_doc.
_UMBRELLA_DOC_FACT_KEYS: frozenset = frozenset({
    "schedule_of_underlying_insurance", "umbrella_follow_form",
})
_LOSS_DOC_FACT_KEYS: frozenset = frozenset({"loss_history_years"})


def _derive_evidence_labels(
    facts: dict,
    cross_issues: Optional[List[dict]] = None,
    flags: Optional[dict] = None,
    has_loss_run_doc: bool = False,
) -> Dict[str, str]:
    """Return per-fact evidence basis label for key scored facts (§6.1 item 3).

    M5 fix: 'stated_in_narrative' now actually fires. The pipeline stores which
    fact keys were contributed by narrative docs in flags['_narrative_fact_keys'].
    A fact that came from a narrative doc (and was not subsequently confirmed or
    overridden by another source) is labelled stated_in_narrative.

    Absent facts are differentiated (§6.1 item 3): a coverage-specific fact whose
    line of business is not present is 'not_applicable'; an umbrella underlying
    schedule / follow-form, or loss-run years with no loss run on file and no
    no-loss attestation, is 'requires_supporting_doc'; everything else 'not_found'.
    """
    _flags = flags or {}
    conflicting = {
        i.get("field", "")
        for i in (cross_issues or [])
        if isinstance(i, dict) and i.get("field") and i.get("type") in _CROSS_ISSUE_TYPES
    }
    narrative_keys: set = set(_flags.get("_narrative_fact_keys") or [])

    # Loss-run years require a supporting document only when no loss run is on file
    # AND the insured has not attested no-known-losses AND loss runs are not already
    # flagged pending - otherwise the gap is covered by other evidence.
    _no_loss_attested = (
        bool(_flags.get("no_prior_losses"))
        or bool(_flags.get("narrative_states_no_losses"))
        or _attested_true(_fv(facts, "no_prior_losses"))
        or _attested_true(_fv(facts, "loss_history_no_prior_losses_indicator"))
    )
    _loss_pending = (
        bool(_flags.get("loss_run_pending"))
        or str(_fv(facts, "loss_run_status") or "").lower() in ("pending", "requested")
    )
    _loss_needs_doc = not (has_loss_run_doc or _no_loss_attested or _loss_pending)

    def _absent_label(key: str) -> str:
        gate = _COVERAGE_GATED_FACT_FLAGS.get(key)
        if gate and not _flags.get(gate):
            return "not_applicable"
        if key in _UMBRELLA_DOC_FACT_KEYS and _flags.get("has_umbrella"):
            return "requires_supporting_doc"
        if key in _LOSS_DOC_FACT_KEYS and _loss_needs_doc:
            return "requires_supporting_doc"
        return "not_found"

    labels: Dict[str, str] = {}
    for key in _SCORED_FACT_KEYS:
        if key in conflicting:
            labels[key] = "conflicting"
            continue
        raw = facts.get(key)
        # V1 H1 (2026-08-26): a schedule fact holding a sentence that says the
        # schedule was NOT supplied is absent. Without this the same payload
        # carried a -15 for "no Schedule of Underlying Insurance" AND an
        # evidence label of "extracted_from_source" for that fact - two doors
        # contradicting each other on the traceability surface C3 exists to
        # guarantee.
        if key == "schedule_of_underlying_insurance" and raw is not None:
            try:
                from services.coverage_evidence import value_states_absence
                _sv = raw.get("value") if isinstance(raw, dict) else raw
                if value_states_absence(_sv):
                    raw = None
            except Exception:                                  # noqa: BLE001
                pass
        if raw is None:
            labels[key] = _absent_label(key)
            continue
        if isinstance(raw, dict):
            conf   = raw.get("confidence")
            source = str(raw.get("source", "")).lower()
            if key in _NEVER_NARRATIVE_KEYS:
                # Identity/structural fields are always labelled as extracted
                # regardless of which document they were found in. A FEIN or
                # effective date that appears inside a narrative doc is still
                # a structured fact, not a narrative statement.
                labels[key] = _EVIDENCE_SOURCE_MAP.get(conf, "extracted_from_source")
            elif "narrative" in source:
                # Explicit narrative source — always label as stated_in_narrative.
                labels[key] = "stated_in_narrative"
            elif source == "client_arq":
                # The client explicitly confirmed this — strongest provenance.
                labels[key] = _EVIDENCE_SOURCE_MAP.get(conf, "confirmed_by_user")
            elif source in ("", "ai") and key in narrative_keys:
                # Generic LLM provenance ("ai" = extracted from *some* document)
                # AND the narrative is evidence for this fact (profile-backed, so
                # it does NOT depend on the doc being classified "narrative").
                # Attribute to the narrative. A SPECIFIC non-narrative source
                # (e.g. dec_page, policy_doc, loss_run) is handled below and wins.
                labels[key] = "stated_in_narrative"
            elif source and source not in ("",):
                # Explicit specific non-narrative source means a source document
                # provided this value. Respect it so we don't mislabel post-merge
                # facts (a dec page that overwrote a narrative-derived value).
                labels[key] = _EVIDENCE_SOURCE_MAP.get(conf, "extracted_from_source")
            elif key in narrative_keys:
                # No source metadata — fall back to narrative_keys attribution.
                labels[key] = "stated_in_narrative"
            else:
                labels[key] = _EVIDENCE_SOURCE_MAP.get(conf, "extracted_from_source")
        else:
            # Plain-string fact has no source metadata — narrative_keys is authoritative,
            # except for identity fields which are never attributed to the narrative.
            if key in _NEVER_NARRATIVE_KEYS:
                labels[key] = "extracted_from_source"
            else:
                labels[key] = "stated_in_narrative" if key in narrative_keys else "extracted_from_source"
    return labels


# ── Positive scoring signals (§6.1 item 4) ───────────────────────────────────

def _compute_positive_signals(
    facts: dict,
    flags: dict,
    has_narrative_doc: bool = False,
    has_loss_run_doc:  bool = False,
) -> List[dict]:
    """Return list of credited positive-evidence signals (§6.1 item 4)."""
    signals: List[dict] = []

    def _sig(key: str, label: str, present: bool) -> None:
        if present:
            signals.append({"key": key, "label": label, "credited": True})

    _no_losses = (
        _attested_true(_fv(facts, "no_prior_losses"))
        or _attested_true(_fv(facts, "loss_history_no_prior_losses_indicator"))
        or bool(flags.get("no_prior_losses"))
        or bool(flags.get("narrative_states_no_losses"))
    )

    _sig("narrative_attached",      "Narrative attached",
         has_narrative_doc or bool(_narrative_remarks_text(facts)))
    _sig("operations_description",  "Clear operations description",
         bool(_fv(facts, "operations_description"))
         and len(str(_fv(facts, "operations_description") or "")) > 30)
    _sig("no_losses_stated",        "No losses stated",       _no_losses)
    _sig("loss_runs_attached",      "Loss runs attached",     has_loss_run_doc)
    _sig("years_in_business",       "Years in business stated", bool(_fv(facts, "years_in_business")))
    _sig("prior_carrier",           "Prior carrier identified", bool(_fv(facts, "prior_carrier")))
    _sig("coverage_limits",         "Coverage limits identified",
         bool(_fv(facts, "gl_limits") or _fv(facts, "gl_each_occurrence")))
    _sig("locations_identified",    "Locations identified",   bool(_fv(facts, "locations")))
    _sig("emod_xmod",               "EMOD/XMOD provided",     bool(_fv(facts, "wc_xmod")))
    _sig("wc_payroll_breakdown",    "Payroll breakdown by WC class code provided",
         bool(_fv(facts, "total_payroll") and _fv(facts, "wc_class_codes")))
    _sig("contractor_coverages",    "Contractor-specific coverages discussed",
         bool(flags.get("is_contractor")
              and (_fv(facts, "percent_subcontracted") or _fv(facts, "contractor_type"))))
    _sig("existing_program",        "Existing insurance program described",
         bool(_fv(facts, "prior_carrier") and _fv(facts, "effective_date")))
    _sig("submission_urgency",      "Upcoming deadline / urgency provided",
         bool(_fv(facts, "submission_urgency")))

    # §6.1 item 4 - narrative-derived positive signals (management, risk controls,
    # employer handbook / safety manual). Detected from the narrative text, which
    # is also where they earn Narrative-Quality component credit.
    _narr_text  = _narrative_remarks_text(facts) or str(_fv(facts, "operations_description") or "")
    _narr_comps = _score_narrative_components(_narr_text) if _narr_text else {}
    _narr_lower = _narr_text.lower()
    _sig("experienced_management",  "Experienced management",
         bool(_narr_comps.get("management")))
    _sig("risk_controls_described", "Risk controls described",
         bool(_narr_comps.get("risk_controls")))
    _sig("safety_manual",           "Employer handbook or safety manual provided",
         ("handbook" in _narr_lower or "safety manual" in _narr_lower or "safety program" in _narr_lower))
    return signals


# ── Loss-run insured match (§6.4 item 2, Q3 answer) ──────────────────────────

def _check_loss_run_insured_match(docs: List[dict], applicant_name: Optional[str],
                                  merged_facts: Optional[dict] = None) -> str:
    """Loss-run ownership tier: strong / moderate / possible / no_match / no_loss_run.

    Delegates to ``services.loss_run_identity`` (V1 plan C1 F4). The body that
    lived here compared FEIN and policy number as RAW strings and took the
    first policy number from any document - on a three-policy package a
    formatting difference cost up to 35 Loss History points. Every identifier
    now goes through the one comparison door; the tier rules are the client's
    1.8 tiers unchanged. ``_check_loss_run_insured_match_detail`` returns the
    full explainable verdict for the review screen.
    """
    from services.loss_run_identity import loss_run_match_tier
    return loss_run_match_tier(docs, applicant_name, merged_facts)


def _check_loss_run_insured_match_detail(docs: List[dict], applicant_name: Optional[str],
                                         merged_facts: Optional[dict] = None) -> dict:
    from services.loss_run_identity import match_loss_run_identity
    return match_loss_run_identity(docs, applicant_name, merged_facts)


# ── Loss-history evidence state (§6.4 item 1) ────────────────────────────────

LOSS_HISTORY_STATE_LABELS: Dict[str, str] = {
    "no_information":                  "No loss information provided",
    "user_states_no_losses":           "User states No Known Losses",
    "narrative_states_no_losses":      "Narrative states no losses",
    "loss_runs_pending":               "Loss runs requested / pending",
    "loss_runs_uploaded":              "Loss runs uploaded - years not yet confirmed",
    "loss_runs_parsed":                "Loss runs parsed - claim years extracted",
    "loss_runs_match_insured":         "Loss runs match insured",
    "loss_runs_do_not_match":          "Loss runs do not match insured",
    "loss_data_reconciled":            "Loss data reconciled",
    "loss_history_conflicting":        "Loss history conflicting",
    "loss_history_pending_validation": "Loss history pending validation",
    # C2 (2026-08-24) states.
    "new_venture_not_applicable":      "Not applicable - new venture, no prior operations",
    "no_operating_history_not_applicable": "Not applicable - under a year in business, no losses to report",
    # Owner 29 Sep 2026 (Orbin item 15): the attestation removes the pillar.
    # Brent, 23 Oct 2026: it reads "Unable to Verify / Confirmation Required".
    "no_known_losses_not_applicable":  "Unable to Verify / Confirmation Required - No Known Losses attested",
    "no_loss_runs_available":          "No loss runs available",
    "prior_claims_exist":              "Prior claims known - loss runs not provided",
}

# ── Client-facing 5-bucket loss-history vocabulary (Image 28 item 3) ──────────
# The engine tracks the 11 fine-grained evidence states above; the client asked
# for their exact 5-word vocabulary: none stated / none corroborated / loss runs
# attached / losses extracted / unknown. This is a DERIVED view (same pattern as
# the ARQ 3-bucket model) — every internal state maps to exactly one client
# bucket, so the scorer and all existing consumers are untouched and the finer
# states remain available. The narrative-vs-attestation split (none_stated vs
# none_corroborated) is the one judgment call; it preserves the P4 score ordering
# (narrative 45 < attestation 60) and is a single-line change if the client wants
# a state re-bucketed.
CLIENT_LOSS_STATE_LABELS: Dict[str, str] = {
    "none_stated":        "None stated",
    "none_corroborated":  "None corroborated",
    "loss_runs_attached": "Loss runs attached",
    "losses_extracted":   "Losses extracted",
    "unknown":            "Unknown",
    # C2 (2026-08-24): a verified new venture is a sixth, honest bucket - none
    # of the five evidence buckets can truthfully describe "no history exists".
    "not_applicable":     "Not applicable",
    # SYS-02 (2026-09-05). The client's own words: *"a narrative stating no
    # losses, a client confirming no losses, and carrier loss runs not being
    # provided are different evidence states and should not be collapsed into
    # the same result."* The first two already had distinct buckets. The third
    # did not - it fell into "unknown" alongside "we know nothing", and the
    # panel printed the internal label and the bucket on consecutive lines, so
    # it read:
    #
    #     No loss runs available          <- the internal label, correct
    #     Unknown                         <- the bucket, contradicting it
    #
    # Two more states had the identical defect and are corrected with it: a
    # requested loss run and a known prior claim are both stated ANSWERS, not
    # absences of information. Only `no_information` is genuinely unknown.
    #
    # This does not invent a scoring rule - no score moves, and the states
    # themselves are unchanged. It stops a label asserting we know nothing
    # about something the same panel has just described. The precedent for
    # widening the client's five words is `not_applicable` directly above.
    "runs_requested":       "Loss runs requested",
    "runs_not_provided":    "Loss runs not provided",
    "claims_known_no_runs": "Claims known - loss runs not provided",
    # 1 Oct 2026 (Orbin item 15): the attestation that took the pillar out of
    # the score. "None corroborated" under "No Known Losses attested" read as
    # "nothing was checked"; this bucket says what happened - it was attested.
    "attested":             "Attested - no known losses",
}

_LOSS_STATE_TO_CLIENT: Dict[str, str] = {
    # No usable loss information yet (nothing on file, or runs merely requested).
    "no_information":                  "unknown",
    # A REQUESTED loss run is a workflow answer, not an absence of information.
    "loss_runs_pending":               "runs_requested",
    # A "no losses" position mentioned in narrative prose, nothing more.
    "narrative_states_no_losses":      "none_stated",
    # A formal no-loss attestation that no loss-run document yet corroborates.
    "user_states_no_losses":           "none_corroborated",
    # The same attestation once it takes the pillar out of the score (29 Sep
    # 2026). It reads as ATTESTED (1 Oct 2026, Orbin item 15): beside "No Known
    # Losses attested" the old "None corroborated" looked like nothing had been
    # checked, when the insured had answered.
    "no_known_losses_not_applicable":  "attested",
    # Loss-run documents are attached (ownership confirmed, unconfirmed, or a
    # mismatch) but claim data has not been extracted from them yet.
    "loss_runs_uploaded":              "loss_runs_attached",
    "loss_runs_match_insured":         "loss_runs_attached",
    "loss_runs_do_not_match":          "loss_runs_attached",
    "loss_history_pending_validation": "loss_runs_attached",
    # Actual claim data has been extracted / reconciled (incl. a detected conflict
    # between an attestation and the runs — the losses themselves were extracted).
    "loss_runs_parsed":                "losses_extracted",
    "loss_data_reconciled":            "losses_extracted",
    "loss_history_conflicting":        "losses_extracted",
    # C2 (2026-08-24) states.
    "new_venture_not_applicable":      "not_applicable",
    "no_operating_history_not_applicable": "not_applicable",
    # SYS-02: the client's third named evidence state. Never "unknown".
    "no_loss_runs_available":          "runs_not_provided",
    # We KNOW claims exist; only the runs are missing. Also never "unknown".
    "prior_claims_exist":              "claims_known_no_runs",
}


def _client_loss_state(internal_state: str) -> str:
    """Map an internal 11-state loss-history state to the client's 5-bucket
    vocabulary (Image 28 item 3). Any unmapped state falls back to 'unknown' so
    the output is always one of the five client-approved values."""
    return _LOSS_STATE_TO_CLIENT.get(internal_state, "unknown")


def _get_loss_history_state(
    facts: dict,
    flags: dict,
    has_loss_run_doc: bool = False,
    loss_run_match: str = "no_loss_run",
) -> str:
    """Return the loss-history evidence state (§6.4 item 1).

    Additive transparency layer mirroring _get_umbrella_state. Does NOT change the
    P4 score - it only names which evidence the score rests on, and surfaces the
    conflict the report asked for (user/narrative attest no losses while loss runs
    actually show claims).
    """
    # The scorer's narrative rule (calculate_p4_loss_history): when the
    # person's narrative says claims and the answer says none, the pillar is
    # scored on the narrative's answer - so the label is too (live ff2ba3e5,
    # 25 Oct: "No Known Losses attested - left out of the score" beside 25).
    try:
        from services.loss_history_state import (
            claims_question_answers as _cqa, narrative_answer_mismatch as _nam,
            with_claims_answer as _wca,
        )
        if _nam(facts) == "claims":
            _nf, _nfl = _wca(facts, flags, _cqa()[1])
            if _nam(_nf) != "claims":
                return _get_loss_history_state(_nf, _nfl, has_loss_run_doc, loss_run_match)
    except Exception as _nx:                                   # noqa: BLE001
        logger.debug("narrative claims stance not read for the label: %s", _nx)
    years = _resolve_loss_history_years(facts)
    no_loss_attested = (
        bool(flags.get("no_prior_losses"))
        or _attested_true(_fv(facts, "no_prior_losses"))
        or _attested_true(_fv(facts, "loss_history_no_prior_losses_indicator"))
    )
    narrative_no_loss = bool(flags.get("narrative_states_no_losses"))
    # The scorer's own rule (23 Oct 2026): beside claims a person confirmed, no
    # no-loss statement is credited, so the label never names one either.
    try:
        from services.loss_history_state import claims_confirmed_by_person
        if claims_confirmed_by_person(facts, has_loss_run_doc):
            no_loss_attested = narrative_no_loss = False
    except Exception:                                          # noqa: BLE001
        pass

    # C2 2.2: a verified new venture has no loss history to evaluate - the
    # pillar is Not Applicable (same gate the scorer consults, so state and
    # score can never disagree).
    from services.loss_history_state import (
        attested_no_losses_not_applicable,
        loss_history_not_applicable, new_venture_applicable,
        no_runs_available_stated, parse_loss_run_status, prior_claims_exist,
    )
    if loss_history_not_applicable(facts, flags, has_loss_run_doc):
        # Both N/A routes share one label family so the pillar row and the
        # score can never disagree about why the pillar is absent.
        return ("new_venture_not_applicable"
                if new_venture_applicable(facts, flags, has_loss_run_doc)
                else "no_operating_history_not_applicable")

    # Conflict (single source of truth shared with the P4 score): a no-loss
    # attestation contradicted by ACTUAL loss-run claims.
    if _loss_history_conflict(facts, flags, has_loss_run_doc):
        return "loss_history_conflicting"

    if has_loss_run_doc:
        # Mirror the pending-status shortcut from calculate_p4_loss_history: a doc
        # classified as a loss_run that only mentions runs are pending with no actual
        # years or claims extracted should show the pending state, not "uploaded".
        _has_claims = (
            (_to_int(_fv(facts, "num_claims")) or 0) > 0
            or (_to_float(_fv(facts, "total_incurred")) or 0.0) > 0.0
        )
        from services.loss_history_state import stored_pending_counts
        if stored_pending_counts(facts, flags, True, years) and not _has_claims:
            return "loss_runs_pending"
        if loss_run_match == "no_match":
            return "loss_runs_do_not_match"
        if years > 0:
            # Claim years parsed — map state by ownership match strength.
            if loss_run_match == "strong":
                return "loss_data_reconciled"
            if loss_run_match in ("moderate", "possible"):
                # Weak ownership (name only, or name+address - address is not a
                # client-sanctioned identifier): years are parsed but ownership is
                # NOT fully confirmed, so validation is still pending. moderate is
                # treated exactly like possible here so the label never understates
                # ownership uncertainty (§6.4 item 2).
                return "loss_history_pending_validation"
            # Years parsed with no strong/weak/mismatch ownership verdict: the bare
            # parsing milestone itself (§6.4 'Loss Runs Parsed').
            return "loss_runs_parsed"
        if loss_run_match == "strong":
            return "loss_runs_match_insured"
        return "loss_runs_uploaded"

    # Bug fix (2026-07-11): every branch inside `if has_loss_run_doc:` above
    # returns, so this was only ever reached with has_loss_run_doc=False - i.e.
    # a "years" value with no loss-run document behind it (mirrors the
    # calculate_p4_loss_history fix). Falling through to "loss_data_reconciled"
    # let an undocumented years figure outrank a genuine no-loss attestation.
    # Removed; an undocumented years value now falls through to the
    # attestation/no-info checks below like it should.
    if no_loss_attested:
        # Owner 29 Sep 2026 (Orbin item 15): the scorer's own gate, so the
        # label can never say "User states No Known Losses" beside a pillar
        # the same attestation has removed. A document or a conflict returned
        # above, so only the had-claims answer can keep the scored state here.
        if attested_no_losses_not_applicable(facts, flags, has_loss_run_doc):
            return "no_known_losses_not_applicable"
        return "user_states_no_losses"
    if narrative_no_loss:
        return "narrative_states_no_losses"
    if flags.get("loss_run_pending") or parse_loss_run_status(_fv(facts, "loss_run_status")) == "pending":
        return "loss_runs_pending"
    # C2 2.9: known claims with no runs, and an explicit "no runs available",
    # are their own states (claims first - 2.5's ordering).
    if prior_claims_exist(facts, flags):
        return "prior_claims_exist"
    if no_runs_available_stated(facts):
        return "no_loss_runs_available"
    return "no_information"


# ── 15-category sub-breakdown (§6.1 item 2, client Q5 answer) ────────────────

def _compute_category_breakdown(
    facts: dict,
    flags: dict,
    cross_issues: Optional[List[dict]] = None,
    # Actual scoring component scores passed from calculate_package_sqs so sub-rows
    # reflect what actually produced the headline number (Option A - client approved).
    tier1_score: Optional[int] = None,
    tier2_score: Optional[int] = None,
    conf_rate:   Optional[int] = None,
    exposure_subscores: Optional[Dict[str, int]] = None,
    doc_types: Optional[set] = None,
    structural_parts: Optional[List[dict]] = None,
) -> Dict[str, Dict[str, dict]]:
    """
    Display breakdown nested under the 6 SQS pillars.
    Returns {pillar_key: {category_key: {score, status, label}}}

    Sub-row structure (client-approved, updated to reflect actual scoring inputs):
      Structural Completeness  - Applicant Info (tier1), Underwriting Profile (tier2),
                                 Form Fill Quality (conf_rate) — these ARE the P1 formula
      Exposure Consistency     - EXPOSURE_BUCKET_LABELS (Class Codes & Operations,
                                 Coverage Info, Payroll/Employee, Revenue/Sales,
                                 Cross-Form Checks, Auto Completeness, WC Supplemental)
      Property Integrity       - Minimum COPE (hard-stop gate), Carrier-Grade Required (Tier1),
                                 Carrier-Grade Preferred (Tier2) — mirrors _calculate_cope_score
      Loss History             - Loss History
      Umbrella Adequacy        - Umbrella Limits
      Narrative Quality        - Narrative Quality, Prior Carrier / Marketing Reason
    """
    ci = cross_issues or []

    def _ok(key: str) -> bool:
        # ANSWERED, not "has a value": an explicit "there is none" is an
        # answer and must not read as an incomplete category.
        #
        # `lines_of_business` is the one key where "has a value" was never the
        # same question (client 2026-09-11 item 2). It is a MENTION list with
        # no definition in the extraction prompt, so an ISO endorsement's
        # "modifies insurance provided under the following" menu filled it -
        # and a package carrying NO coverage at all still scored this category
        # as answered. Read the evidenced inventory instead; a package with
        # real lines is unaffected, because a real line corroborates itself.
        if key == "lines_of_business":
            try:
                from services.lob_canon import carried_lines_of_business
                return bool(carried_lines_of_business(facts, flags))
            except Exception:                                 # noqa: BLE001
                pass
        return _answered(facts, key)

    def _conflict_in(field: str) -> bool:
        return any(
            field in str(i.get("field", "")) or field in str(i.get("message", ""))
            for i in ci if isinstance(i, dict)
        )

    def _cat(score, status: str, label: str) -> dict:
        return {"score": score, "status": status, "label": label}

    def _sc_status(s: int) -> str:
        return "ok" if s >= 90 else ("partial" if s >= 50 else "insufficient")

    # ── Structural Completeness — 5 client-approved sub-rows ─────────────────
    # Each sub-row is computed directly from the relevant facts so the expanded
    # detail reflects the actual submission data for that category.

    # 1. Applicant Info: producer identity + applicant identity + contact
    _app_fields  = ["applicant_name", "mailing_address", "producer_name", "lines_of_business"]
    _app_ok      = sum(1 for f in _app_fields if _ok(f))
    _app_ok     += 1 if any(_ok(f) for f in ("contact_name", "contact_phone", "contact_email")) else 0
    app_score    = int(_app_ok / 5 * 100)

    # 2. Entity Info: business classification (entity type, FEIN, vintage, industry)
    _entity_fields = ["entity_type", "fein", "years_in_business"]
    _entity_ok     = sum(1 for f in _entity_fields if _ok(f))
    _entity_ok    += 1 if (_ok("naics_code") or _ok("sic_code")) else 0
    entity_score   = int(_entity_ok / 4 * 100)

    # 3. Effective Date Consistency: effective date present and not in conflict
    _eff_present  = _ok("effective_date")
    _eff_conflict = _conflict_in("effective_date")
    if not _eff_present:
        eff_score, eff_st = 0, "missing"
    elif _eff_conflict:
        eff_score, eff_st = 60, "review_recommended"
    else:
        eff_score, eff_st = 100, "ok"

    # 4. Policy Term Consistency: expiration date and policy number present, no conflict
    _pol_fields   = ["expiration_date", "policy_number"]
    _pol_ok       = sum(1 for f in _pol_fields if _ok(f))
    _pol_conflict = _conflict_in("expiration_date") or _conflict_in("policy_number")
    pol_score     = int(_pol_ok / len(_pol_fields) * 100)
    if _pol_conflict:
        pol_score = max(0, pol_score - 25)
    pol_st = _sc_status(pol_score)

    # 5. Supporting Documentation: AI fill confidence across generated forms,
    # or doc-type presence as a proxy when form data is unavailable.
    _KEY_SUPP_DOC_WEIGHTS: Dict[str, int] = {
        "dec_page": 40, "loss_run": 30, "sov": 20, "schedule_of_values": 20,
        "prior_policy": 15, "policy_doc": 20, "supplemental": 10,
    }
    if conf_rate is not None:
        supp_doc_score = conf_rate
    elif doc_types is not None:
        supp_doc_score = min(100, sum(w for t, w in _KEY_SUPP_DOC_WEIGHTS.items() if t in doc_types))
    else:
        # prior_carrier removed 2026-08-24 (client C2 2.7): it must not act as
        # a structural-completeness proxy; its scoring home is Loss History.
        _supp_proxy = [
            _ok("policy_number"), _ok("producer_name"),
            _ok("contact_name") or _ok("contact_phone"),
        ]
        supp_doc_score = int(sum(_supp_proxy) / len(_supp_proxy) * 100)

    # ── Exposure Consistency fallback scores (used when subscores not passed) ─
    ops_txt = str(_fv(facts, "operations_description") or "")
    ops_s   = 100 if len(ops_txt) > 30 else (40 if ops_txt else 0)
    ops_st  = "ok" if ops_s == 100 else ("partial" if ops_s > 0 else "missing")

    cov_s  = 100 if (_ok("gl_limits") or _ok("gl_each_occurrence") or _ok("lines_of_business")) else 0

    pay_f = [_ok("total_payroll") or _ok("wc_payroll"), _ok("num_employees")]
    pay_s = int(sum(pay_f) / len(pay_f) * 100)

    rev_f = [_ok("total_revenue"), _ok("naics_code") or _ok("sic_code")]
    rev_s = int(sum(rev_f) / len(rev_f) * 100)

    hard_ci = [i for i in ci if isinstance(i, dict) and i.get("type") == "hard_stop"]
    warn_ci = [i for i in ci if isinstance(i, dict) and i.get("type") == "warning"]
    if hard_ci:
        xd_s, xd_st = 0, "conflict_found"
    elif warn_ci:
        xd_s, xd_st = 60, "review_recommended"
    else:
        xd_s, xd_st = 100, "consistent"

    # ── Property Integrity — 2 client-approved sub-rows ──────────────────────
    if flags.get("has_property_coverage"):
        # 1. COPE Info: structural and physical characteristics of the building.
        # Covers minimum-viable fields (occupancy, construction) plus carrier-grade
        # fields (year_built, roof_year, sprinkler, fire protection, valuation method).
        _cope_fields = [
            "occupancy_type", "construction_type",
            "year_built", "roof_year", "sprinkler_system",
            "fire_protection_class", "valuation_method",
        ]
        _cope_ok        = sum(1 for f in _cope_fields if _ok(f))
        cope_info_score = int(_cope_ok / len(_cope_fields) * 100)
        if _acv_rcv_conflict(facts):
            cope_info_score = max(0, cope_info_score - 10)
        cope_info_st = "ok" if cope_info_score >= 90 else ("partial" if cope_info_score >= 50 else "insufficient")

        # 2. Location Info: where the property is and its insurable value.
        # Required: property address (locations) + building or BPP value.
        # Quality: distance to hydrant, fire department type, business income limit.
        _loc_quality  = ["distance_to_hydrant", "fire_department_type", "business_income_limit"]
        _loc_ok       = (1 if _ok("locations") else 0)
        _loc_ok      += 1 if (_ok("property_building_value") or _ok("property_bpp_value")) else 0
        _loc_ok      += sum(1 for f in _loc_quality if _ok(f))
        _loc_total    = 2 + len(_loc_quality)   # locations + value + 3 quality fields = 5
        loc_info_score = int(_loc_ok / _loc_total * 100)
        loc_info_st   = "ok" if loc_info_score >= 90 else ("partial" if loc_info_score >= 50 else "insufficient")
    else:
        cope_info_score, cope_info_st = None, "not_applicable"
        loc_info_score,  loc_info_st  = None, "not_applicable"

    # ── Prior Carrier: REMOVED from the Narrative Quality breakdown ──────────
    # V1 H4 (client section 9), 2026-08-27. Section 9.1's Prior Carrier row
    # gives it exactly one Scoring Home - **"Loss History only"** - and C2 2.7
    # already moved the SCORE there on 2026-08-24. The DISPLAY row under
    # Narrative Quality was left behind, so the one panel built to make the
    # arithmetic traceable (C3's Desired Outcome) still showed prior carrier
    # sitting in a second pillar, contradicting the ledger beside it.
    # Display-only and verified to change no number: `carrier_s` / `carrier_st`
    # had exactly one reader, the row itself, and no test or frontend code
    # references `prior_carrier_context`. Narrative Quality keeps its other row,
    # so the panel's own "has categories" guard is unaffected. Sessions scored
    # before today keep the row, because the breakdown is served back out of the
    # stored `package_sqs` - display drift on old data, no score anywhere.

    # ── Exposure Consistency sub-rows ────────────────────────────────────────
    # When the package scorer passes the real per-bucket scores, render THOSE so
    # the expandable detail equals the inputs that produced the pillar headline.
    # Labels match client-approved naming exactly.
    # C3 Desired Outcome: the Exposure buckets DO reconstruct their pillar
    # exactly - the headline is 100 minus the sum of what each bucket deducted -
    # so each row carries `deducted` and the panel can show the arithmetic
    # instead of a completeness word. Without it the only visible difference
    # between "this fact was charged here" and "it was not" is one adjective:
    # the S4 double-count fix moved the Payroll/Employee bucket from 77 to 92,
    # which reads as "Strong" versus "Complete" and proves nothing to anyone.
    def _exp_cat(key: str, label: str) -> dict:
        _s = int((exposure_subscores or {}).get(key, 0))
        return {"score": _s, "status": _sc_status(_s), "label": label,
                "deducted": max(0, 100 - _s)}

    if exposure_subscores:
        # EVERY bucket the scorer emitted, labelled from this table - a key
        # missing from the table is still rendered (under its raw key) rather
        # than silently dropped. Measured 2026-08-26 (H1 audit): the previous
        # hardcoded five-tuple would have hidden the two new buckets from the
        # panel while the trace and the headline both charged for them, making
        # the "100 minus every bucket" tooltip untrue.
        _exp_labels = EXPOSURE_BUCKET_LABELS
        # ONLY the keys the scorer actually emitted, in the table's order - a
        # payload written before a bucket existed (a stored five-bucket
        # session) must not render the missing bucket as "0%, deducted 100".
        _ordered = [k for k in _exp_labels if k in exposure_subscores] + \
                   [k for k in exposure_subscores if k not in _exp_labels]
        _exp_cats = {
            k: _exp_cat(k, exposure_bucket_label(k))
            for k in _ordered
        }
    else:
        # Same label table as the scored rows (Choice Electric #26) - a second
        # copy of the names here is how "Operations" outlived its meaning.
        _exp_cats = {
            "operations_description":       _cat(ops_s, ops_st,                                                          exposure_bucket_label("operations_description")),
            "coverage_information":         _cat(cov_s, "ok" if cov_s == 100 else "missing",                            exposure_bucket_label("coverage_information")),
            "payroll_employee_information": _cat(pay_s, "ok" if pay_s == 100 else ("partial" if pay_s else "missing"),  exposure_bucket_label("payroll_employee_information")),
            "revenue_sales_information":    _cat(rev_s, "ok" if rev_s == 100 else ("partial" if rev_s else "missing"),  exposure_bucket_label("revenue_sales_information")),
            "cross_document_consistency":   _cat(xd_s,  xd_st,                                                          exposure_bucket_label("cross_document_consistency")),
        }

    # ── Structural Completeness sub-rows - C3, 2026-08-25 ───────────────────
    # These ARE the pillar's formula now: multiply each row's score by its
    # weight and the rows sum to Structural Completeness exactly.
    #
    # They replace five rows (Applicant Info, Entity Info, Effective Date
    # Consistency, Policy Term Consistency, Supporting Documentation) that were
    # computed from a DIFFERENT set of facts than the pillar and could never
    # reconstruct it - while this function's own docstring claimed they "ARE the
    # P1 formula" and took `tier1_score` / `tier2_score` as arguments it never
    # read. The frontend had already worked around it, rendering status words
    # instead of numbers with a note conceding the rows do not add up. That
    # workaround is what C3's Current Problem list is describing.
    #
    # Nothing is lost: WHICH Tier 1 / Tier 2 fact is missing rides on each row's
    # `missing` list and on the structural_completeness recommendations.
    if structural_parts:
        _structural_cats = {
            p["key"]: {
                "score":   p["score"],
                "status":  _sc_status(p["score"]),
                "label":   p["label"],
                "weight":  p["weight"],
                "contribution": p["contribution"],
                "missing": p.get("missing") or [],
                # The coverage details print "-N pts" like an Exposure row.
                **({"deducted": p["deducted"]} if "deducted" in p else {}),
            }
            for p in structural_parts
        }
    else:
        # Legacy callers that pass no parts (and stored payloads) keep a
        # meaningful, if coarser, Structural detail rather than an empty panel.
        _structural_cats = {
            "applicant_information":      _cat(app_score,       _sc_status(app_score),       "Applicant Info"),
            "entity_information":         _cat(entity_score,    _sc_status(entity_score),    "Entity Info"),
            "effective_date_consistency": _cat(eff_score,       eff_st,                      "Effective Date Consistency"),
            "policy_term_consistency":    _cat(pol_score,       pol_st,                      "Policy Term Consistency"),
            "supporting_documentation":   _cat(supp_doc_score,  _sc_status(supp_doc_score),  "Supporting Documentation"),
        }

    return {
        "structural_completeness": _structural_cats,
        "exposure_consistency": _exp_cats,
        "property_integrity": {
            "cope_info":     _cat(cope_info_score, cope_info_st, "COPE Info"),
            "location_info": _cat(loc_info_score,  loc_info_st,  "Location Info"),
        },
        "loss_history_alignment": {
            "loss_history": _cat(None, "computed_separately", "Loss History"),
        },
        "umbrella_limit_adequacy": {
            "umbrella_limits": _cat(None, "computed_separately", "Umbrella Limits"),
        },
        "narrative_quality": {
            "narrative_quality":     _cat(None, "computed_separately", "Narrative Quality"),
        },
    }


# ── ONE DOOR: the umbrella's APPLICABLE underlying limits (21 Oct 2026) ──────
# Brent, 20 Oct rule 2: "hard stop when umbrella / excess is selected and
# Primble cannot identify the applicable underlying liability limits needed to
# support it. Do not require both GL and Auto; look at the account's actual
# underlying coverage." Until 21 Oct every reader counted only GL and Auto
# limits, so an umbrella over Employers Liability only - or one whose limits sit
# only in its OWN schedule of underlying insurance - was hard-stopped at 60, its
# pillar scored 0, and the ACORD 131 asked for a GL and an auto limit the
# account cannot have.
#
# One verdict, read by every reader: the package hard stops and the EL warnings
# (`evaluate_stops`), the per-form gate and its card (`calculate_sqs`), the
# Umbrella pillar (`_calculate_umbrella_adequacy`, `umbrella_deduction_items`,
# `umbrella_gap_items`), the evidence state, the ACORD 131 checklists and the
# cross-form umbrella checks.
#   identified - ANY underlying liability limit can be found: general
#                liability, auto (CSL or split), employers liability, a row of
#                the umbrella's own schedule (any liability line), an amount its
#                schedule text prints, or - on an upper layer's copy of the
#                ACORD 131 - the limit of the layer it sits on. None -> the one
#                "no underlying" hard stop, as before.
#   per line   - the three lines with a limit box (the 131's named underlying
#                rows): LISTED by a row of the umbrella's own schedule (verified:
#                the umbrella says it sits over that line) with no limit found
#                anywhere -> a hard stop for that line; CARRIED by the package
#                (its flag), not listed, no limit -> the existing warnings to
#                confirm it (not verified). A line the schedule excludes / does
#                not schedule is not applicable.
UMB_UNDERLYING_LINES: Tuple[Tuple[str, str], ...] = (
    ("general_liab", "general liability"),
    ("auto", "auto liability"),
    ("workers_comp", "employers liability"),
)
UMB_UNDERLYING_LABELS: Dict[str, str] = dict(UMB_UNDERLYING_LINES)
# The box a missing line's limit is typed into (cards, gap rows, fix windows).
UMB_UNDERLYING_FACT: Dict[str, str] = {
    "general_liab": "gl_each_occurrence",
    "auto": "auto_liability_limit",
    "workers_comp": "employers_liability_limits",
}
# Each line's own limit facts - read from the ONE table of a line's limit
# facts (`policy_lines.limit_facts`, the policies table's Limit column), plus
# the GL composite: GL each occurrence / aggregate / composite; the auto CSL box
# (its split parts are read beside it); the three employers liability parts
# extraction writes (`wc_el_*`) and their composite. Fallback below if that
# table cannot be read.
_UMB_LINE_FACT_KEYS: Dict[str, Tuple[str, ...]] = {
    "general_liab": ("gl_each_occurrence", "gl_aggregate", "gl_limits"),
    "auto": ("auto_liability_limit",),
    "workers_comp": ("wc_el_each_accident", "wc_el_disease_each_employee",
                     "wc_el_disease_policy_limit", "employers_liability_limits"),
}
_AUTO_SPLIT_PART_KEYS = ("auto_bi_per_person", "auto_bi_per_accident", "auto_pd_per_accident")


def _umb_line_fact_keys(fam: str) -> Tuple[str, ...]:
    try:
        from services.policy_lines import limit_facts
        keys = tuple(limit_facts().get(fam) or ())
    except Exception:                                          # noqa: BLE001
        keys = ()
    if fam == "auto":
        keys = tuple(k for k in keys if k not in _AUTO_SPLIT_PART_KEYS) or ("auto_liability_limit",)
    extra = ("gl_limits",) if fam == "general_liab" else ()
    out = tuple(dict.fromkeys(keys + extra + _UMB_LINE_FACT_KEYS[fam]))
    return out


def _umb_coverage_line_limit(facts: dict, fam: str) -> Tuple[bool, bool]:
    """(stated, numeric): a limit a `coverage_lines` row of this line prints
    (a row that does not deny the line; physical damage / deductibles are not
    liability limits)."""
    from services.coverage_evidence import (
        LIMIT_AMOUNT, limit_is_positive_amount, limit_printing_state)
    rows = _fv(facts, "coverage_lines")
    if not isinstance(rows, list):
        return False, False
    try:
        from services.lob_canon import canon_line, denies_coverage
    except Exception:                                          # noqa: BLE001
        return False, False
    stated = numeric = False
    for r in rows:
        if not isinstance(r, dict) or canon_line(r.get("line")) != fam or denies_coverage(r):
            continue
        if re.search(r"physical\s+damage|comprehensive|collision|deductible",
                     str(r.get("line") or ""), re.I):
            continue
        for k in ("limit", "limits", "limit_each_occurrence"):
            if limit_printing_state(r.get(k)) == LIMIT_AMOUNT:
                stated = True
                numeric = numeric or limit_is_positive_amount(r.get(k))
    return stated, numeric


def _umb_line_carried(flags: Optional[dict], fam: str) -> bool:
    """The package carries the line - the flags the Umbrella pillar has always
    read for its "required but absent" deductions."""
    flags = flags if isinstance(flags, dict) else {}
    if fam == "general_liab":
        return bool(flags.get("has_general_liability"))
    if fam == "auto":
        return bool(flags.get("has_auto_coverage"))
    return _wc_carried(flags)


def _umb_layer_below(facts: dict) -> Tuple[bool, bool]:
    """(stated, numeric) - the limit of the layer an upper layer's ACORD 131
    copy sits on (`umbrella_layers`: "Layer 2 is Excess, which gets mapped to
    the underlying umbrella policy"). (False, False) on every other view."""
    try:
        from services.umbrella_layers import MARKER_KEY
    except Exception:                                          # noqa: BLE001
        MARKER_KEY = "_umbrella_layer"
    marker = facts.get(MARKER_KEY) if isinstance(facts, dict) else None
    if not isinstance(marker, dict) or not isinstance(marker.get("index"), int) \
            or marker["index"] < 1 or not isinstance(marker.get("below"), dict):
        return False, False
    limit = marker["below"].get("limit")
    from services.coverage_evidence import (
        LIMIT_AMOUNT, LIMIT_WORDS, limit_printing_state)
    stated = limit_printing_state(limit) in (LIMIT_AMOUNT, LIMIT_WORDS)
    return stated, bool(stated and _to_int(limit))


def umbrella_underlying(facts: Optional[dict], flags: Optional[dict] = None) -> dict:
    """THE verdict on an umbrella's applicable underlying limits (see the note
    above). `flags` only decide which lines the package CARRIES; `identified`
    and `numeric` read the facts alone.

    Returns {
      "identified": an underlying liability limit can be found (presence -
                    "Included", "Statutory", "See schedule", "$0" count);
      "numeric":    ... and one reads as an amount above zero (the pillar's
                    arithmetic needs one);
      "lines": {family: {label, carried, listed, excluded, applicable,
                         fact_stated, fact_numeric, schedule_stated,
                         schedule_numeric, stated, numeric}},
      "missing_scheduled":    lines the umbrella's own schedule lists with no
                              limit found anywhere (hard stops);
      "scheduled_to_confirm": the same, when the schedule also prints an amount
                              it does not tie to one line (warnings - not
                              verified);
      "missing_carried":      carried lines, not listed or excluded, with no
                              limit (the warnings to confirm),
    } - the per-line lists only when `identified` (otherwise the one "no
    underlying" stop says it), except `missing_carried`, which keeps the
    long-standing EL warning beside that stop."""
    from services.coverage_evidence import (
        LIMIT_AMOUNT, LIMIT_WORDS, limit_printing_state, umbrella_schedule_lines)
    facts = facts if isinstance(facts, dict) else {}
    sched = umbrella_schedule_lines(facts)
    lines: Dict[str, dict] = {}
    for fam, label in UMB_UNDERLYING_LINES:
        stated = numeric = False
        for key in _umb_line_fact_keys(fam):
            raw = _fv(facts, key)
            state = limit_printing_state(raw)
            # Employers liability is a money limit: "Statutory" is the WC
            # part's, and states no EL limit.
            if state == LIMIT_AMOUNT or (state == LIMIT_WORDS and fam != "workers_comp"):
                stated = True
                num = _to_int(raw)
                # Auto keeps the reading it has always had: a CSL box holding
                # words ("Included") is read like split parts - stated, and the
                # below-$1M comparison is not attempted (no opinion).
                numeric = numeric or bool(num) or (fam == "auto" and num is None)
        if fam == "auto" and not stated and any(
                limit_printing_state(_fv(facts, k)) in (LIMIT_AMOUNT, LIMIT_WORDS)
                for k in _AUTO_SPLIT_PART_KEYS):
            stated = numeric = True                     # split limits state it
        if not stated:
            stated, numeric = _umb_coverage_line_limit(facts, fam)
        s = sched["lines"].get(fam) or {}
        carried = _umb_line_carried(flags, fam)
        listed, excluded = bool(s.get("listed")), bool(s.get("excluded"))
        lines[fam] = {
            "label": label,
            "carried": carried,
            "listed": listed,
            "excluded": excluded,
            "applicable": listed or (carried and not excluded),
            "fact_stated": stated,
            "fact_numeric": numeric,
            "schedule_stated": bool(s.get("stated")),
            "schedule_numeric": bool(s.get("numeric")),
            "stated": stated or bool(s.get("stated")),
            "numeric": numeric or bool(s.get("numeric")),
        }
    below_stated, below_numeric = _umb_layer_below(facts)
    identified = (any(ln["stated"] for ln in lines.values())
                  or bool(sched["stated"]) or below_stated)
    numeric = (any(ln["numeric"] for ln in lines.values())
               or bool(sched["numeric"]) or below_numeric)
    order = [fam for fam, _label in UMB_UNDERLYING_LINES]
    unlisted_gap = [fam for fam in order
                    if lines[fam]["listed"] and not lines[fam]["stated"]] if identified else []
    unplaced = bool(sched["unplaced"])
    return {
        "identified": identified,
        "numeric": numeric,
        "lines": lines,
        "missing_scheduled": [] if unplaced else unlisted_gap,
        "scheduled_to_confirm": unlisted_gap if unplaced else [],
        "missing_carried": [fam for fam in order
                            if lines[fam]["carried"] and not lines[fam]["listed"]
                            and not lines[fam]["excluded"] and not lines[fam]["stated"]],
    }


def umbrella_underlying_box(facts: Optional[dict], flags: Optional[dict] = None) -> str:
    """The box that answers "no underlying limit at all": the first line of
    general liability, auto, employers liability the package carries or the
    umbrella's schedule lists, else general liability - so the one answer the
    card asks for is one that lifts the pillar."""
    lines = _umb_lines(facts, flags)
    for fam, _label in UMB_UNDERLYING_LINES:
        if lines[fam]["applicable"]:
            return UMB_UNDERLYING_FACT[fam]
    return UMB_UNDERLYING_FACT["general_liab"]


def _umb_lines(facts: Optional[dict], flags: Optional[dict]) -> Dict[str, dict]:
    """`umbrella_underlying(...)["lines"]`, or - if the door ever fails - the
    reading before 21 Oct (a line applies when the package carries it, nothing
    is read from the schedule), so a failure never moves a score further."""
    try:
        return umbrella_underlying(facts, flags)["lines"]
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("umbrella_underlying failed (lines): %s", exc, exc_info=True)
    out: Dict[str, dict] = {}
    for fam, label in UMB_UNDERLYING_LINES:
        carried = _umb_line_carried(flags, fam)
        stated = any(str(_fv(facts or {}, k) or "").strip() for k in _UMB_LINE_FACT_KEYS[fam])
        out[fam] = {"label": label, "carried": carried, "listed": False, "excluded": False,
                    "applicable": carried, "fact_stated": stated, "fact_numeric": stated,
                    "schedule_stated": False, "schedule_numeric": False,
                    "stated": stated, "numeric": stated}
    return out


UMB_RETENTION_STATED = "stated"            # an SIR or an attachment point is stated
UMB_RETENTION_ESTABLISHED = "established"  # an excess layer's attachment, from its underlying
UMB_RETENTION_REVIEW = "review"            # an excess layer, attachment not established
UMB_RETENTION_MISSING = "missing"          # a primary umbrella with neither (unchanged)


def _umbrella_is_excess_layer(facts: Optional[dict]) -> bool:
    """The 131 being read is an EXCESS layer's: an upper layer's copy (the
    `umbrella_layers` marker), or a package whose lowest umbrella-family layer
    is an excess policy (no umbrella beneath it)."""
    if not isinstance(facts, dict):
        return False
    try:
        from services import umbrella_layers as _ul
    except Exception:                                          # noqa: BLE001
        return False
    marker = facts.get(_ul.MARKER_KEY)
    if isinstance(marker, dict) and marker.get("layer") in (_ul.UMBRELLA_LAYER, _ul.EXCESS_LAYER):
        return marker.get("layer") == _ul.EXCESS_LAYER
    try:
        slots = _ul._all_slots(facts)              # one layer too (`ordered_layers` is towers only)
    except Exception:                                          # noqa: BLE001
        return False
    return bool(slots) and slots[0].get("layer") == _ul.EXCESS_LAYER


def umbrella_retention_state(facts: Optional[dict], flags: Optional[dict] = None) -> str:
    """THE ACORD 131 "Self-Insured Retention (SIR) or attachment point" item -
    Brent, 23 Oct 2026 (Z34-1 #3): "For follow-form excess, if we can establish
    the attachment point/underlying structure, do not deduct points just
    because there is no separate retention/SIR. But if we cannot establish the
    attachment point or underlying structure, flag it for review."

      stated      - an SIR or an attachment point is stated (either satisfies);
      established - an EXCESS layer states neither, but its attachment is
                    established by what it sits on: the layer below's limit
                    (an upper layer's copy) or a stated underlying limit
                    (`umbrella_underlying`'s `identified`);
      review      - an excess layer, attachment not established: a review
                    flag, never a deduction;
      missing     - a PRIMARY umbrella with neither: the checklist item it has
                    always been."""
    facts = facts if isinstance(facts, dict) else {}
    if _fv(facts, "umbrella_sir") or _fv(facts, "umbrella_attachment_point"):
        return UMB_RETENTION_STATED
    if not _umbrella_is_excess_layer(facts):
        return UMB_RETENTION_MISSING
    try:
        identified = bool(umbrella_underlying(facts, flags)["identified"])
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("umbrella_underlying failed (retention): %s", exc, exc_info=True)
        identified = _umb_layer_below(facts)[0]
    return UMB_RETENTION_ESTABLISHED if identified else UMB_RETENTION_REVIEW


def _umbrella_retention_checks(facts: dict, flags: Optional[dict]) -> List[bool]:
    """The 131 checklists' SIR-or-attachment item: met when stated or (an
    excess layer) established; no item at all when an excess layer's
    attachment cannot be established (the review flag carries it instead);
    an unmet item for a primary umbrella with neither - unchanged."""
    state = umbrella_retention_state(facts, flags)
    if state == UMB_RETENTION_REVIEW:
        return []
    return [state != UMB_RETENTION_MISSING]


def umbrella_sir_not_needed(facts: Optional[dict], flags: Optional[dict] = None) -> bool:
    """The SIR is not asked: the attachment point is stated, or an excess
    layer's attachment is established by what it sits on (Brent, 23 Oct 2026:
    "a separate SIR should not be mandatory when the attachment point can be
    established"). False when the SIR itself is stated - that question is
    already answered - and on anything unreadable.

    On a TOWER the question is the lowest layer's (the plain 131's - the copy
    every package question answers), so it is judged on that layer's view: an
    attachment point only an upper layer's documents print never retires the
    umbrella's SIR question (review of Z35, 23 Oct 2026)."""
    try:
        facts = facts if isinstance(facts, dict) else {}
        from services import umbrella_layers as _ul
        if _ul.MARKER_KEY not in facts and _ul.ordered_layers(facts):
            facts = _ul.layer_view(facts, "")
        if _fv(facts, "umbrella_sir"):
            return False
        return bool(_fv(facts, "umbrella_attachment_point")) or \
            umbrella_retention_state(facts, flags) == UMB_RETENTION_ESTABLISHED
    except Exception:                                          # noqa: BLE001
        return False


def _umbrella_underlying_checks(facts: dict, flags: Optional[dict], *,
                                split_counts: bool,
                                families: Tuple[str, ...] = ("general_liab", "auto",
                                                             "workers_comp")) -> List[bool]:
    """The ACORD 131 checklists' underlying items (21 Oct 2026): one per line
    of `families` the umbrella sits over (`umbrella_underlying`'s
    `applicable`) or whose limit is stated anyway - Brent: "do not require both
    GL and Auto". This is the 15 Sep employers liability rule ("a no-WC package
    lost a fifth of this score for a limit it cannot have") for every line.

    An item is met when the door says the line's limit is STATED - its own box
    or the umbrella's own schedule; a blank, "N/A", "none" or "excluded" is not
    a limit. `split_counts`: the calling checklist's own auto reading - split
    limits count (Exposure) or only the CSL box (Structural).

    No line of `families` applies: an underlying limit identified elsewhere (an
    EL limit, the umbrella's schedule, the layer below) leaves nothing to ask
    here; with nothing identified at all the two items the checklist has
    always had (GL, auto) stay, so a package telling us nothing about its
    underlying still shows the gap."""
    from services.coverage_evidence import LIMIT_AMOUNT, LIMIT_WORDS, limit_printing_state
    lines = _umb_lines(facts, flags)
    values: Dict[str, bool] = {}
    for fam, _label in UMB_UNDERLYING_LINES:
        own = bool(lines[fam]["fact_stated"])
        if fam == "auto" and not split_counts:
            own = limit_printing_state(_fv(facts, "auto_liability_limit")) in (LIMIT_AMOUNT, LIMIT_WORDS)
        values[fam] = own or bool(lines[fam]["schedule_stated"])
    checks: List[bool] = []
    for fam, _label in UMB_UNDERLYING_LINES:
        if fam in families and (lines[fam]["applicable"] or values[fam]):
            checks.append(values[fam])
    if checks or _umbrella_underlying_stated(facts):
        return checks
    return [values["general_liab"], values["auto"]]


def _umbrella_has_underlying(facts: dict) -> bool:
    """True when the package states an underlying liability limit as an AMOUNT
    - general liability, auto, employers liability, the umbrella's own schedule
    or (on an upper layer's copy) the layer below (`umbrella_underlying`'s
    `numeric`, 21 Oct 2026; GL or Auto only before).

    ONE DOOR, deliberately. `_calculate_umbrella_adequacy` returns 0 for two
    completely different reasons - genuinely no underlying limits, or ordinary
    deductions stacking to zero - and `calculate_sqs`'s 60 cap could not tell
    them apart, so it printed "no underlying GL or Auto limits" on packages
    that plainly had both. A second local copy of this test is how that class
    of defect survives, so both callers read this one.

    NUMERIC, and that matters. This answers "can an underlying limit be read as
    an AMOUNT" - which is what `_calculate_umbrella_adequacy` needs, because it
    returns 0 outright when the answer is no and otherwise compares against the
    client-approved thresholds. Do NOT loosen it to mean "is anything stated":
    that is a different question, it is answered by
    `_umbrella_underlying_stated` below, and widening this one moves every
    umbrella score on a package whose limit is printed in words.
    """
    try:
        return bool(umbrella_underlying(facts)["numeric"])
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("umbrella_underlying failed (numeric): %s", exc, exc_info=True)
    gl_val   = _to_int(_fv(facts, "gl_each_occurrence") or _fv(facts, "gl_limits"))
    auto_val = _to_int(_fv(facts, "auto_liability_limit"))
    _auto_split = auto_val is None and _auto_liability_stated(facts)
    return bool(gl_val or auto_val or _auto_split)


def _umbrella_underlying_stated(facts: dict) -> bool:
    """True when the documents MENTION an underlying liability limit - general
    liability, auto, employers liability, the umbrella's own schedule or the
    layer below (`umbrella_underlying`'s `identified`, 21 Oct 2026; GL or Auto
    only before). A blank, "N/A", "none" or "excluded" is not a mention.

    PRESENCE, not adequacy - and a separate question from
    `_umbrella_has_underlying` above, which asks whether that limit can be read
    as a number.

    Both questions were being answered by whichever test happened to be nearest,
    and a THIRD hand-written copy in `evaluate_stops` proved the cost: that one
    tested the raw string while the numeric door parsed it, so on the four
    conventions an ACORD document really uses for a limit it cannot print as
    digits - "Included", "Statutory", "See schedule", "$0" - they disagreed.
    Measured, all four: the package engine raised no hard stop while the form
    printed "Umbrella present with no underlying GL or Auto limits" beside it.

    Every site that WORDS something about underlying limits reads this one; only
    the pillar arithmetic reads the numeric door. No score moves - the sentences
    just stop contradicting the maths.
    """
    try:
        return bool(umbrella_underlying(facts)["identified"])
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("umbrella_underlying failed (identified): %s", exc, exc_info=True)
    if _umbrella_has_underlying(facts):
        return True
    gl_raw   = _fv(facts, "gl_each_occurrence") or _fv(facts, "gl_limits")
    auto_raw = _fv(facts, "auto_liability_limit")
    return bool(str(gl_raw or "").strip() or str(auto_raw or "").strip())


def umbrella_deduction_items(facts: dict, flags: dict) -> List[dict]:
    """Every Umbrella & Limit Adequacy deduction, ONE item each: {points, fact,
    label} (15 Oct 2026). The pillar is 100 minus their sum, floored at 0
    (`_calculate_umbrella_adequacy`) - the same items the Best Solutions rows are
    built from (`umbrella_gap_items`), so a row can never name a deduction the
    pillar does not take, or miss one it does.

    Client-approved thresholds (Q1/Q2 answers):
      GL:   $1M each occurrence - reduce score if below, do NOT hard-stop
      Auto: $1M CSL             - reduce score if below, do NOT hard-stop
      EL:   $1M = full credit | $500K = acceptable | <$500K = reduction
    Empty when there is no umbrella, or no underlying limit at all (the pillar
    is then N/A or 0 - see `_calculate_umbrella_adequacy`)."""
    if not flags.get("has_umbrella") or not _umbrella_has_underlying(facts):
        return []
    # Prefer the clean per-occurrence scalar; fall back to the combined field.
    # This matches validator.py precedence and avoids feeding the combined-limit
    # string ($1M/$2M) directly to _to_int when the clean field is available.
    gl_val   = _to_int(_fv(facts, "gl_each_occurrence") or _fv(facts, "gl_limits"))
    auto_val = _to_int(_fv(facts, "auto_liability_limit"))
    # Split limits STATE the auto limit without a CSL figure (live P5). They
    # satisfy "underlying auto exists" and the "required but absent" -20; the
    # below-$1M comparison is CSL-only and is not attempted on split parts -
    # no opinion, never a guess.
    _auto_split = auto_val is None and _auto_liability_stated(facts)
    # Which lines must carry a limit, and which the umbrella's own schedule
    # already prices (21 Oct 2026, `umbrella_underlying`): a line it does not
    # sit over is never "required but absent", one its schedule states an
    # amount for is not absent - the GL / auto / EL readings below.
    _ul = _umb_lines(facts, flags)

    def _absent_required(fam: str) -> bool:
        # An EL limit in any of its own parts (`wc_el_*`) is not absent.
        return bool(_ul[fam]["applicable"]) and not _ul[fam]["schedule_numeric"] and not (
            fam == "workers_comp" and _ul[fam]["fact_numeric"])

    items: List[dict] = []

    # AC#4 (§6.5): an umbrella whose OWN limit is missing is "Insufficient
    # Information" evidence - the §6.5 finding requires that case to surface a
    # state rather than a perfect score, and item 2 reserves full credit for when
    # "umbrella details are present and complete". The evidence-state machine
    # (_get_umbrella_state) already returns "insufficient_information" here; this
    # keeps the headline number from contradicting that state by removing the
    # "complete" credit. Underlying adequacy is still scored below.
    #
    # IMPORTANT - this -25 is a DISPLAY-CONSISTENCY adjustment, NOT a client-listed
    # underwriting deduction. It exists only so the headline score cannot read as
    # near-ready (e.g. 85) while the evidence-state label simultaneously reports
    # "insufficient_information" for the same submission - the two outputs would
    # otherwise contradict each other on the same screen. It is intentionally
    # retained by owner decision even though the client's approved deduction table
    # does not enumerate it; do not remove without re-checking the state/score
    # agreement in _get_umbrella_state.
    if not _answered(facts, "umbrella_limit"):
        items.append({"points": 25, "fact": "umbrella_limit", "label": "Umbrella limit"})

    # GL - penalise both "present but below minimum" AND "required but absent".
    # A submission with GL exposure (has_general_liability) but no GL limits
    # is a gap; umbrella spec §218 requires underlying GL (client Q1 / M4 fix).
    if gl_val is not None and gl_val < _UMB_GL_OCC_MIN:
        # Present but below $1M - warn, don't block (Q1)
        items.append({"points": 20, "fact": "gl_each_occurrence",
                      "label": f"Underlying general liability each occurrence limit is below ${_UMB_GL_OCC_MIN:,}"})
    elif gl_val is None and _absent_required("general_liab"):
        # Required underlying GL missing (M4)
        items.append({"points": 20, "fact": "gl_each_occurrence",
                      "label": "Underlying general liability each occurrence limit"})

    # GL aggregate (client Q1 baseline: $2M / occurrence $1M). The aggregate is the
    # other half of the client's stated GL baseline, so an extracted aggregate below
    # $2M reduces score (warn, never block - Q1). A merely-unextracted aggregate is
    # NOT penalised, to avoid a false warning when only the occurrence was captured.
    gl_agg = _to_int(_fv(facts, "gl_aggregate"))
    if gl_agg is not None and gl_agg < _UMB_GL_AGG_MIN:
        items.append({"points": 20, "fact": "gl_aggregate",
                      "label": f"Underlying general liability aggregate is below ${_UMB_GL_AGG_MIN:,}"})

    # Auto - same logic: present-and-low OR required-but-absent.
    if auto_val is not None and auto_val < _UMB_AUTO_CSL_MIN:
        # Present but below $1M CSL - warn, don't block (Q1)
        items.append({"points": 20, "fact": "auto_liability_limit",
                      "label": f"Underlying auto liability limit is below ${_UMB_AUTO_CSL_MIN:,}"})
    elif auto_val is None and _absent_required("auto") and not _auto_split:
        # Required underlying Auto missing (M4)
        items.append({"points": 20, "fact": "auto_liability_limit",
                      "label": "Underlying auto liability limit"})

    # EL tiers (client Q2: $1M full, $500K acceptable, <$500K reduction) - on
    # an umbrella that sits over employers liability (WC carried, or its own
    # schedule lists it; not where that schedule leaves EL out).
    if _ul["workers_comp"]["applicable"]:
        el_val = _to_int(_fv(facts, "employers_liability_limits"))
        if el_val is None:
            if _absent_required("workers_comp"):
                items.append({"points": 25, "fact": "employers_liability_limits",
                              "label": "Underlying employers liability limit"})
        elif el_val >= _UMB_EL_FULL:
            pass                 # Full credit ($1M+)
        elif el_val >= _UMB_EL_OK:
            items.append({"points": 10, "fact": "employers_liability_limits",
                          "label": f"Underlying employers liability limit is below ${_UMB_EL_FULL:,}"})
        else:
            items.append({"points": 25, "fact": "employers_liability_limits",
                          "label": f"Underlying employers liability limit is below ${_UMB_EL_OK:,}"})

    # Schedule of Underlying Insurance: -15 when absent (client V1 requirement)
    if not _umbrella_schedule_present(facts):
        items.append({"points": 15, "fact": "schedule_of_underlying_insurance",
                      "label": "Schedule of underlying insurance"})

    # Follow-form evidence: -10 when unable to confirm (Option B per client Q4)
    _ff_combined = " ".join([
        _narrative_remarks_text(facts),
        str(_fv(facts, "umbrella_follow_form") or ""),
        str(_fv(facts, "policy_notes") or ""),
    ])
    if not _has_explicit_follow_form(_ff_combined):
        items.append({"points": 10, "fact": "umbrella_follow_form",
                      "label": "Does the umbrella follow form over the underlying policies?"})
    return charge_only_answerable(items, "umbrella")


def umbrella_gap_items(facts: dict, flags: dict) -> List[dict]:
    """The Umbrella pillar's gap as Best Solutions items (15 Oct 2026, owner: the
    score must reach 100 from the review page - the 13 Oct decision built this
    for Exposure and Property; the Umbrella pillar still showed ONE row with no
    box, "Improve umbrella limit adequacy", so an umbrella package could never
    reach 100 before forms).

    The deductions of `umbrella_deduction_items`, each with its box. When they
    add up to more than the pillar can lose (it floors at 0), each keeps its
    share of the 100 points the pillar has to give (largest remainder), so the
    items still add up to the gap. No underlying limit at all: the pillar is 0
    and the one thing that lifts it is an underlying liability limit."""
    if not flags.get("has_umbrella"):
        return []
    if not _umbrella_has_underlying(facts):
        # The box of the first line the umbrella sits over (21 Oct 2026: an
        # employers liability limit lifts it too - `umbrella_underlying_box`).
        box = umbrella_underlying_box(facts, flags)
        first = {"points": 100, "fact": box,
                 "label": "Underlying liability limit (general liability, auto or "
                          "employers liability)"}
        # EVERYTHING THE PILLAR WILL ASK, UP FRONT (owner rule G2, 30 Oct 2026):
        # the deductions read once that limit is stated (at the threshold the
        # answer is probed with) are listed now too - before, answering the one
        # row revealed the umbrella limit, the schedule, follow form and the
        # employers liability limit as new items. The first row keeps what the
        # rest cannot give (at least 1); the rest share the other points.
        try:
            probe = dict(facts or {})
            probe[box] = {"value": str(int(_THRESHOLD_PROBE_FACTS.get(box, 1_000_000))),
                          "source": "producer", "confidence": "producer"}
            rest = [i for i in umbrella_deduction_items(probe, flags)
                    if i.get("fact") != box and int(i.get("points") or 0) > 0]
        except Exception as exc:                               # noqa: BLE001
            logger.debug("umbrella gap items: later items not read: %s", exc)
            rest = []
        if not rest:
            return [first]
        give = 99
        total = sum(int(i["points"]) for i in rest)
        quotas = [int(i["points"]) * min(total, give) / total for i in rest]
        shares = [int(q) for q in quotas]
        left = min(total, give) - sum(shares)
        for n in sorted(range(len(rest)), key=lambda n: -(quotas[n] - shares[n]))[:left]:
            shares[n] += 1
        first["points"] = 100 - sum(shares)
        return [first] + [{**i, "points": shares[n]} for n, i in enumerate(rest) if shares[n] > 0]
    items = umbrella_deduction_items(facts, flags)
    total = sum(int(i["points"]) for i in items)
    if total <= 100:
        return items
    quotas = [int(i["points"]) * 100 / total for i in items]
    shares = [int(q) for q in quotas]
    left = 100 - sum(shares)
    for n in sorted(range(len(items)), key=lambda n: -(quotas[n] - shares[n]))[:left]:
        shares[n] += 1
    return [{**i, "points": shares[n]} for n, i in enumerate(items)]


def _calculate_umbrella_adequacy(facts: dict, flags: dict) -> Optional[int]:
    """P5 - Umbrella & Limit Adequacy (10% of SQS): 100 minus every deduction
    of `umbrella_deduction_items`, floored at 0.

    Returns None when not applicable (no umbrella in submission). Callers must
    exclude this pillar from the weighted sum and re-normalise weights.
    """
    if not flags.get("has_umbrella"):
        return None  # Not Applicable - fixes the confirmed 100% bug (§6.5)
    if not _umbrella_has_underlying(facts):
        return 0  # hard-stop scenario per evaluate_stops()
    return max(0, 100 - sum(int(i["points"]) for i in umbrella_deduction_items(facts, flags)))


def _calculate_narrative_quality(
    facts: dict,
    has_narrative_doc: bool = False,
    flags: Optional[dict] = None,
    narrative_doc_text: str = "",
    form_ids=None,
) -> Tuple[int, Dict[str, bool], int]:
    """P6 - Narrative Quality (10% of SQS) with §6.3 component model.

    Returns (score, component_breakdown, substance_pct) where component_breakdown
    is a per-component present/absent dict keyed by the APPLICABLE components and
    substance_pct is the 0-100 underwriting-substance half of the score.

    SYS-04: the component set is no longer the fixed twelve. Components whose
    coverage line the submission demonstrably does not carry are dropped from
    the breakdown AND from the denominator, so a non-WC package is not marked
    down - and not asked - for WC payroll / class code / EMOD context. Dropping
    requires positive evidence of absence; anything unknown keeps the component.
    `form_ids` is optional and only ever ADDS evidence (selecting ACORD 130 is
    "intentionally requested"), so omitting it can never drop a component that
    passing it would keep.

    Scoring: 60% component coverage + 40% text quality, blended.
    Floor of 40 when a narrative document is classified in the package.

    narrative_doc_text: concatenated full OCR text of all narrative docs
    (from _extract_narrative_doc_text). When non-empty it is unioned with the
    structured-field text so that body sections of a standalone narrative
    (risk controls, carrier context, etc.) reach the component model even
    when RULE 10 only put the executive summary into account_description.
    Defaults to "" so all existing callers remain unaffected.
    """
    remarks = _narrative_remarks_text(facts).strip()
    ops     = str(_fv(facts, "operations_description") or "").strip()

    # SYS-04. Resolved ONCE and used at every construction site below. The
    # function has four return paths and three union comprehensions that used to
    # re-key over the full label map, so a single filter at the top would have
    # been silently re-expanded to twelve on three of the four paths - a change
    # that passes review and does nothing. `_applicable` is the denominator.
    _applicable = applicable_narrative_components(facts, flags, form_ids)
    empty_components = {k: False for k in _applicable}

    def _only_applicable(mapping: Dict[str, bool]) -> Dict[str, bool]:
        """Restrict any component dict to the applicable keys.

        Every producer of a component map (`_score_narrative_components`,
        `narrative_profile_present_map`, `_narrative_enrichment_present`) emits
        the full taxonomy, so each one is funnelled through here rather than
        trusted to already be gated.
        """
        return {k: bool(mapping.get(k)) for k in _applicable}

    # §6.3 item 2: client-supplied narrative-enrichment answers (Bucket-C topics
    # the narrative lacked and the ARQ asked the client to provide). A filled
    # answer credits its component directly and joins the structured scan text so
    # both the component breakdown and the substance half reflect it.
    # The meaning-based reading of exactly these remarks (13 Oct 2026,
    # services/narrative_reader): it only ADDS to the keyword pass.
    try:
        from services.narrative_reader import credited as _credited_reading
        _read_topics, _read_depth = _credited_reading(facts, remarks)
    except Exception:                                          # noqa: BLE001
        _read_topics, _read_depth = set(), set()
    _enrich_present = _only_applicable(_narrative_enrichment_present(facts))
    _enrich_text    = _narrative_enrichment_text(facts)
    if _enrich_text:
        remarks = " ".join(filter(None, [remarks, _enrich_text])).strip()

    # Small underwriter-context credit when the producer/client provided upcoming
    # deadline / urgency via the questionnaire (Brent feedback). Bounded + gated:
    # applies only when submission_urgency is present, so it never changes a score
    # where the field is absent (every existing submission / test is unaffected).
    _urgency_bonus = 8 if _fv(facts, "submission_urgency") else 0

    # Build the component-scan text by unioning every available source.
    # Priority: narrative_doc_text (full body) is always included when present.
    # remarks (account_description / acord101_remarks / additional_remarks_text)
    # is included alongside it. ops falls back when nothing richer is available.
    # The source_factor penalises submissions where only operations_description
    # is available (no real narrative), but never penalises when a real narrative
    # doc exists alongside the structured fields.
    if narrative_doc_text:
        # Full narrative body available - union with any structured remarks.
        # Never penalise: a real doc was uploaded, source_factor = 1.0.
        text          = " ".join(filter(None, [narrative_doc_text, remarks])) or ops
        source_factor = 1.0
    elif remarks:
        text          = remarks
        source_factor = 1.0
    elif ops:
        text          = ops
        source_factor = 0.75  # ops is a weaker substitute for a real narrative
    else:
        # No structured narrative text reached the scorer. The stored LLM profile
        # may still have detected components (e.g. a mis-classified narrative whose
        # body never became narrative_doc_text), so honour it before giving up.
        _prof_present = _only_applicable(
            narrative_profile_present_map((flags or {}).get("narrative_profile")))
        if any(_prof_present.values()):
            components = dict(_prof_present)
            if _fv(facts, "carrier_marketing_reason"):
                components["carrier_market"] = True
            present_count = sum(1 for v in components.values() if v)
            component_pct = int(present_count / len(components) * 100) if components else 0
            # No readable text for the 40% substance half; floor at 40 because a
            # real (if mis-classified) narrative exists.
            raw = max(int(component_pct * 0.6), 40)
            raw = min(100, raw + _urgency_bonus)
            return raw, components, 0
        # Still credit carrier_market if the producer answered the marketing-reason
        # questionnaire (provides underwriter context even without a narrative).
        score = min(100, (40 if has_narrative_doc else 0) + _urgency_bonus)
        if _fv(facts, "carrier_marketing_reason"):
            carrier_components = dict(empty_components)
            carrier_components["carrier_market"] = True
            return score, carrier_components, 0
        return score, empty_components, 0

    # §6.3 component model. The short, curated fields (account_description /
    # acord101_remarks / operations) credit a component on a single mention. The
    # full raw-OCR narrative body is noisier, so it must hit >=2 DISTINCT signal
    # phrases before crediting a component - this stops incidental words (a stray
    # "coverage" / "location" / "carrier" in letterhead or boilerplate) from
    # marking components present, keeping the per-component breakdown and the
    # targeted "includes X but not Y" gaps honest. The two are OR-ed so a genuine
    # single-mention in the curated field is never lost.
    components = _only_applicable(_score_narrative_components(remarks or ops))
    if narrative_doc_text:
        _body_components = _score_narrative_components(narrative_doc_text, strict=True)
        components = {
            k: bool(components.get(k) or _body_components.get(k))
            for k in _applicable
        }
    # Credit carrier_market when carrier_marketing_reason is supplied via ARQ
    # (the questionnaire answer provides the underwriter context even when the
    # submitted documents don't explicitly discuss the carrier situation).
    if _fv(facts, "carrier_marketing_reason"):
        components["carrier_market"] = True
    # §6.3 robustness: union the meaning-based LLM profile over the keyword scan
    # so a paraphrased component the fixed phrases missed is still credited.
    # Evidence-gated in narrative_profile_present_map (cannot over-credit); a
    # no-op when the flag is off or detection failed (empty profile).
    _prof_present = _only_applicable(
        narrative_profile_present_map((flags or {}).get("narrative_profile")))
    if any(_prof_present.values()):
        components = {
            k: bool(components.get(k) or _prof_present.get(k))
            for k in _applicable
        }
    # §6.3 item 2: credit any Bucket-C component the client supplied via the
    # narrative-enrichment ARQ (so an answered topic counts and is not re-asked).
    if any(_enrich_present.values()):
        components = {
            k: bool(components.get(k) or _enrich_present.get(k))
            for k in _applicable
        }
    if _read_topics:
        components = {k: bool(components.get(k) or k in _read_topics) for k in _applicable}
    present_count = sum(1 for v in components.values() if v)
    total_count   = len(components)
    component_pct = int(present_count / total_count * 100) if total_count else 0

    # Underwriting substance quality for the 40% quality half. Per client
    # (DOUBTS-Workstream3, Narrative Quality): "score whether the narrative
    # provides meaningful underwriting context ... reward underwriting usefulness,
    # not writing length." This deliberately replaces the old character-count /
    # vocabulary-diversity measure with substance-signal detection - the client's
    # stated V1 preference, not a deviation from it.
    substance_pct = _score_narrative_substance(text, credited=_read_depth)

    # Blend: 60% component coverage, 40% underwriting substance
    raw = int((component_pct * 0.6 + substance_pct * 0.4) * source_factor)
    raw = min(100, raw)
    # Floor of 40 for a real narrative - credited from classification OR from the
    # evidence-backed LLM profile, so a mis-classified narrative still earns it.
    if has_narrative_doc or any(_prof_present.values()):
        raw = max(raw, 40)
    raw = min(100, raw + _urgency_bonus)
    return raw, components, substance_pct


def _narrative_gap_message(components: Dict[str, bool]) -> str:
    """§6.3 AC#4: a targeted narrative recommendation that names both what the
    narrative already covers AND what it is missing - the client-requested
    format, e.g. "Narrative includes Operations Description and Loss History
    Discussion, but does not include Years in Business, Management Experience."

    Returns "" when nothing is missing (caller decides whether to emit anything),
    and falls back to a missing-only message when no component is present.
    """
    present = [NARRATIVE_COMPONENT_LABELS[k] for k, ok in components.items() if ok]
    absent  = [NARRATIVE_COMPONENT_LABELS[k] for k, ok in components.items() if not ok]
    if not absent:
        return ""

    def _join(items: List[str]) -> str:
        head = ", ".join(items[:4])
        return head + (f" (+{len(items) - 4} more)" if len(items) > 4 else "")

    if present:
        return f"Narrative includes {_join(present)}, but does not include {_join(absent)}"
    return f"Narrative is missing: {_join(absent)}"


def _acv_rcv_conflict(facts: dict) -> bool:
    """True when ACV and RCV valuation bases both appear across the submission.

    Client Property Integrity validation: "If ACV appears on the source documents
    and RCV appears on the generated ACORD forms (or vice versa), flag as a
    conflict for review." Every valuation signal is bucketed into ACV / RCV, so a
    synonym ('RCV' vs 'Replacement Cost Value', 'ACV' vs 'Actual Cash Value')
    collapses to one basis and never reads as a self-conflict - only a genuine
    ACV-vs-RCV disagreement returns True.
    """
    bases = set()
    raw_val = str(_fv(facts, "valuation_method") or "").lower()
    if "acv" in raw_val or "actual cash" in raw_val:
        bases.add("ACV")
    if "rcv" in raw_val or "replacement" in raw_val:
        bases.add("RCV")
    if _fv(facts, "property_actual_cash_value"):
        bases.add("ACV")
    if _fv(facts, "property_replacement_cost"):
        bases.add("RCV")
    return "ACV" in bases and "RCV" in bases


def _calculate_cope_score(facts: dict, flags: dict) -> int:
    """Calculate COPE score for Property Integrity pillar.

    Three-tier COPE model (client V1 approved + Decision_Tree L319/398/407):
      • Missing Minimum Viable COPE  → 0  (hard stop)
      • Minimum Viable COPE present  → 60 floor (never ~30)
      • Tier 1 Required fields       → drive score from 60 to ~80
      • Tier 2 Preferred fields      → drive score from ~80 to 100

    Tier 1 Required (4 fields): year_built, roof_year, sprinkler_system, protection_class
    Tier 2 Preferred (4 fields, client-approved): distance_to_hydrant, fire_department_type,
                                  business_income_limit, period_of_restoration
    valuation_method is NOT a Tier 2 credit field - the client placed it under a
    separate "Additional Validation" rule (the ACV/RCV conflict check below), so
    counting it here permanently capped a fully carrier-grade submission at 96.
    ACV/RCV conflict: -10 if both cost-valuation signals detected simultaneously.
    """
    if not flags.get("has_property_coverage"):
        return 100
    # 100 minus every gap (`property_gap_items` - the one list the score and
    # the questions that close it are both read from, 13 Oct 2026).
    return min(100, max(0, 100 - sum(i["points"] for i in property_gap_items(facts, flags))))


# The COPE fields the Property pillar credits, as a person names them.
_COPE_TIER1 = (("year_built", "Year built"), ("roof_year", "Roof year"),
               ("sprinkler_system", "Sprinkler system"),
               ("fire_protection_class", "Fire protection class"))
_COPE_TIER2 = (("distance_to_hydrant", "Distance to the nearest fire hydrant"),
               ("fire_department_type", "Fire department type"),
               ("business_income_limit", "Business income limit"),
               ("period_of_restoration", "Period of restoration"))
_COPE_MINIMUM = (("locations", "Premises address"), ("occupancy_type", "Occupancy type"),
                 ("construction_type", "Construction type"),
                 ("property_building_value", "Building or contents value"))


def property_gap_items(facts: dict, flags: dict) -> List[dict]:
    """Every Property Integrity deduction, ONE item each: {points, fact, label}
    (13 Oct 2026). The three-tier COPE model of `_calculate_cope_score`:

      * Minimum Viable COPE missing -> the pillar is 0. Its missing parts
        carry the 60 base plus the tier fields already present (what answering
        them returns); every missing tier field carries its own 5.
      * Minimum Viable present -> 60 + 5 per Tier 1 / Tier 2 field present, so
        each missing field is a 5-point item; an ACV / RCV conflict is a
        10-point item on the valuation method.
    The items always sum to the pillar's gap (100 - score).
    """
    if not flags.get("has_property_coverage"):
        return []
    # PRESENCE = ANSWERED (15 Oct 2026): a person's "none" / "not applicable"
    # is stored as an empty value with its state, and a bare-value test kept
    # charging it as missing - the correct answer could never reach 100.
    present = {
        "locations": _answered(facts, "locations"),
        "occupancy_type": _answered(facts, "occupancy_type"),
        "construction_type": _answered(facts, "construction_type"),
        "property_building_value": (_answered(facts, "property_building_value")
                                    or _answered(facts, "property_bpp_value")),
    }
    # A Business Income limit the property SCHEDULE prints per premises is a
    # stated BI limit (27 Oct 2026, the round trip's ACORD 140: two premises,
    # $1,000,000 and $25,000, no one package value - and charged "missing").
    try:
        from services.property_coverages import schedule_states_limit
        _bi_scheduled = schedule_states_limit(facts, "bi")
    except Exception:                                          # noqa: BLE001
        _bi_scheduled = False
    tier_missing = [(k, label) for k, label in _COPE_TIER1 + _COPE_TIER2
                    if not _answered(facts, k)
                    and not (k == "business_income_limit" and _bi_scheduled)
                    # Actual Loss Sustained: no period to state, and its basis
                    # is the BI limit's statement (Michelle review item 6).
                    and not (k in ("period_of_restoration", "business_income_limit")
                             and not _por_needed(facts))]
    tier_filled = len(_COPE_TIER1) + len(_COPE_TIER2) - len(tier_missing)
    items: List[dict] = []
    min_missing = [(k, label) for k, label in _COPE_MINIMUM if not present[k]]
    if min_missing:
        share = 60 + tier_filled * 5
        base, extra = divmod(share, len(min_missing))
        for n, (k, label) in enumerate(min_missing):
            items.append({"points": base + (1 if n < extra else 0), "fact": k,
                          "label": label, "minimum_viable": True})
    for k, label in tier_missing:
        items.append({"points": 5, "fact": k, "label": label})
    # ACV vs RCV conflict: -10 when the source documents and the generated-form
    # valuation basis disagree (client Property Integrity validation). Detection
    # is synonym-safe via _acv_rcv_conflict; the matching review flag is raised in
    # evaluate_stops so the conflict is surfaced, not silently deducted. Below
    # Minimum Viable COPE the pillar is already 0 and it costs nothing more.
    if not min_missing and _acv_rcv_conflict(facts):
        items.append({"points": 10, "fact": "valuation_method",
                      "label": "Valuation method - the documents disagree (replacement cost or actual cash value)"})
    return charge_only_answerable(items, "property")



def _por_needed(facts: dict) -> bool:
    """`property_coverages.period_of_restoration_needed` - False when the BI
    coverage is Actual Loss Sustained (no period to state; Michelle review item
    6, 29 Oct 2026). True when that module is unavailable (today's rule)."""
    try:
        from services.property_coverages import period_of_restoration_needed
        return period_of_restoration_needed(facts)
    except Exception:                                          # noqa: BLE001
        return True


def _cope_tier_ok(facts: dict, key: str) -> bool:
    """A Tier 2 COPE field present - or, for the Period of Restoration, not
    applicable on an Actual Loss Sustained BI coverage."""
    if key in ("period_of_restoration", "business_income_limit") and not _por_needed(facts):
        return True
    return bool(_fv(facts, key))


def _bi_limit_stated(facts: dict) -> bool:
    """`property_coverages.business_income_limit_stated` - the package BI limit
    or a scheduled BI row; the bare fact when that module is unavailable."""
    try:
        from services.property_coverages import business_income_limit_stated
        return business_income_limit_stated(facts)
    except Exception:                                          # noqa: BLE001
        return bool(_fv(facts, "business_income_limit"))

# ── Package-level SQS ─────────────────────────────────────────────────────────

# SPEC-COMPLIANT WEIGHTS (matches decision tree specification v2.1.0+)
SPEC_PILLAR_WEIGHTS = {
    "structural_completeness": 0.25,    # ACORD 125 + required line forms
    "exposure_consistency":    0.25,    # Class codes, payroll alignment
    "property_integrity":      0.15,    # COPE completeness
    "loss_history_alignment":  0.15,    # Claims vs exposures
    "umbrella_limit_adequacy": 0.10,    # Underlying limits vs umbrella
    "narrative_quality":       0.10,    # ACORD 101 clarity
}

# ── Structural Completeness blend - SUBMISSION SCORE ONLY ────────────────────
# Client C3 3.2 (2026-08-25), superseding the spec's 35 / 30 / 35:
#
#     Structural = Tier 1 x 40% + Tier 2 x 35% + Form Fill Rate x 25%
#
# His reason, verbatim: *"The existing Structural formula gives 35% of the
# Structural pillar to ACORD form fill rate. That makes the submission score
# more dependent on form completion than we want long term."*
#
# THIS IS THE SUBMISSION FORMULA AND NOTHING ELSE. `SQS_Scoring_Specification`
# states both formulas side by side twice - section 3.1 (*"Submission level:
# Structural = ..."* then *"Individual form scores use that form's own
# checklist"*) and section 10's scope table - and 3.2 modifies only the
# submission line. Under the precedence rule an unmodified rule stays
# authoritative, so per-form Structural REMAINS that form's own ACORD checklist
# minus the OCR penalty. Do not "unify" the two: they are deliberately different,
# which is also why `calculate_sqs`'s `tier2_score` parameter is unread.
_W_TIER1 = 0.40
_W_TIER2 = 0.35
_W_FILL  = 0.25

# C3 3.7 - no ACORD forms generated: drop Form Fill Rate and rescale the other
# two, "preserving the 40:35 relationship". The client states the results
# himself (53.3% / 46.7%); they are DERIVED here rather than typed so the two
# can never disagree if the ratio above ever moves.
_W_NOFORM_TIER1 = round(_W_TIER1 / (_W_TIER1 + _W_TIER2), 3)   # 0.533
_W_NOFORM_TIER2 = round(_W_TIER2 / (_W_TIER1 + _W_TIER2), 3)   # 0.467

# Labels carry no percentage: the WEIGHT is a field on the row, because 3.7's
# no-form case rescales it and a label baked with "40%" would then be a lie.
_STRUCTURAL_PART_LABELS = {
    "tier1": "Core Application (Tier 1)",
    "tier2": "Underwriting Profile (Tier 2)",
    "fill":  "Form Fill Rate",
    "coverage_details": "Coverage Details",
}


def _structural_parts(tier1_score: int, tier2_score: int,
                      fill_rate: Optional[int],
                      tier1_missing: Optional[List[str]] = None,
                      tier2_missing: Optional[List[str]] = None,
                      coverage_points: int = 0,
                      coverage_missing: Optional[List[str]] = None) -> List[dict]:
    """The three components behind Structural Completeness, with real weights.

    THE SCORER'S OWN INPUTS, not a display-side reconstruction. Multiply each
    row's score by its weight and the three sum to the pillar - which is what
    C3's Desired Outcome asks for and what the previous five sub-rows could
    never do, because they were computed from a different set of facts.

    `fill_rate=None` is C3 3.7's no-forms case: the row is dropped and the
    other two carry the rescaled 53.3 / 46.7 weights.
    """
    if fill_rate is None:
        w1, w2, wf = _W_NOFORM_TIER1, _W_NOFORM_TIER2, 0.0
    else:
        w1, w2, wf = _W_TIER1, _W_TIER2, _W_FILL
    parts = [
        {"key": "tier1", "label": _STRUCTURAL_PART_LABELS["tier1"],
         "score": int(tier1_score), "weight": w1,
         "contribution": round(int(tier1_score) * w1, 2),
         "missing": list(tier1_missing or [])},
        {"key": "tier2", "label": _STRUCTURAL_PART_LABELS["tier2"],
         "score": int(tier2_score), "weight": w2,
         "contribution": round(int(tier2_score) * w2, 2),
         "missing": list(tier2_missing or [])},
    ]
    if fill_rate is not None:
        parts.append({
            "key": "fill", "label": _STRUCTURAL_PART_LABELS["fill"],
            "score": int(fill_rate), "weight": wf,
            "contribution": round(int(fill_rate) * wf, 2),
            "missing": [],
        })
    # The coverage details (19 Oct 2026, `completeness_deduction_items`) come
    # off the WHOLE pillar - the same points they cost in Exposure - and never
    # past 0: the rows still sum to the pillar.
    if coverage_points:
        _blend = int(sum(p["contribution"] for p in parts))
        _taken = min(int(coverage_points), max(0, _blend))
        parts.append({
            "key": "coverage_details", "label": _STRUCTURAL_PART_LABELS["coverage_details"],
            "score": max(0, 100 - int(coverage_points)), "weight": None,
            "contribution": -float(_taken), "deducted": _taken,
            "missing": list(coverage_missing or []),
        })
    return parts

def _weighted_pillar_sum(pillars: Dict[str, Optional[float]],
                         weights: Dict[str, float]) -> int:
    """Weighted pillar sum with GENERIC Not-Applicable rescaling (client C2
    2.2, 2026-08-24): any pillar valued None is removed from the calculation
    and the remaining pillars' ORIGINAL weights are scaled proportionally to
    total 100%. One mechanism serves umbrella N/A, Loss History N/A (verified
    new venture), and both at once - replacing three hand-inlined
    umbrella-only copies that could drift (the second-independent-copy defect
    class this codebase keeps paying for). With nothing N/A the scale is 1.0
    and the arithmetic is byte-identical to the previous inline sums.
    """
    active = {k: v for k, v in pillars.items() if v is not None and k in weights}
    total_w = sum(weights[k] for k in active)
    if not active or total_w <= 0:
        return 0
    scale = 1.0 / total_w
    # ── FLOOR THE SCORE, NOT THE FLOAT ERROR (2026-09-23) ───────────────────
    # Spec section 2 mandates "rounded down to a whole number", so flooring a
    # genuine 90.84 is correct. Flooring an EXACT 100 to 99 is not, and that is
    # what `int()` did here: with two pillars Not Applicable (umbrella absent
    # plus a confirmed New Venture) the rescale lands 100 on
    # 99.99999999999999, so a flawless submission could not print 100.
    # Measured: all six at 100 -> 100; umbrella N/A -> 100; umbrella AND loss
    # N/A -> 99.
    #
    # Identical defect, identical treatment, to the one fixed in
    # `confidence_fill_rate` earlier the same day: round to nine places to
    # collapse the representation error, then floor exactly as before. Nothing
    # else moves - a real fraction still rounds DOWN.
    return int(round(sum(v * weights[k] * scale for k, v in active.items()), 9))


def effective_pillar_weights(pillars: Dict[str, Optional[float]],
                             weights: Dict[str, float]) -> Dict[str, float]:
    """The weight each pillar ACTUALLY carried, after Not-Applicable rescaling.

    A pillar's nominal weight is only its real weight when nothing is N/A. With
    Umbrella removed, Structural is not 25% of the score - it is 25/90 = 27.8%.
    Anything that PRINTS a weight has to print this one, or it tells the user a
    number that does not reconcile with the arithmetic in front of them.

    Derived from the same two lines `_weighted_pillar_sum` uses, so the two can
    never disagree.
    """
    active = {k: v for k, v in pillars.items() if v is not None and k in weights}
    total_w = sum(weights[k] for k in active)
    if not active or total_w <= 0:
        return {}
    return {k: round(weights[k] / total_w, 5) for k in active}


def build_score_trace(
    pillars: Dict[str, Optional[float]],
    weights: Dict[str, float],
    raw_uncapped: int,
    cap_applied: Optional[int],
    cap_reason: Optional[str],
    displayed: int,
    credits_applied: int = 0,
    structural_parts: Optional[List[dict]] = None,
    exposure_subscores: Optional[Dict[str, int]] = None,
) -> dict:
    """The audit ledger behind one score. C3's Desired Outcome, made a value.

    The client's ask, verbatim: *"Every material score should be traceable
    through: Canonical Fact -> Validation Rule -> Pillar -> Raw SQS -> Ceiling
    -> Displayed SQS."* Before this, three of those five arrows existed only in
    somebody's head - `_compute_category_breakdown` rendered five Structural
    sub-rows that were computed from a different set of facts than the pillar
    itself, took `tier1_score` and `tier2_score` as arguments and read NEITHER,
    and the frontend hid the sub-row numbers with a note admitting they do not
    add up.

    THIS OBJECT IS EMITTED BY THE SCORER, NOT RECONSTRUCTED FOR DISPLAY. That
    is the whole point: a second computation "for the panel" is how the panel
    and the score drift apart again, which is the defect being closed. The
    build asserts `reconciles` in tests/test_c3_sqs_integrity.py, so if any
    pillar ever stops adding up, the build fails rather than the producer
    finding out.

    Shape:
      pillars[]        one row per pillar: score, nominal and EFFECTIVE weight,
                       and the points it actually contributed
      structural[]     the Tier 1 / Tier 2 / Form Fill Rate split behind P1
      exposure[]       the five Exposure buckets and what each deducted
      arithmetic       raw -> credits -> ceiling -> displayed, in that order
      reconciles       do the contributions sum to the raw score?
    """
    eff = effective_pillar_weights(pillars, weights)
    rows: List[dict] = []
    for key, score in pillars.items():
        if key not in weights:
            continue
        if score is None:
            rows.append({
                "pillar": key, "score": None,
                "nominal_weight": weights[key], "effective_weight": 0.0,
                "contribution": 0.0, "not_applicable": True,
            })
            continue
        _eff = eff.get(key, 0.0)
        rows.append({
            "pillar": key, "score": int(score),
            "nominal_weight": weights[key],
            "effective_weight": _eff,
            "contribution": round(float(score) * _eff, 2),
            "not_applicable": False,
        })

    _sum = sum(r["contribution"] for r in rows)
    exposure_rows = [
        {"bucket": k, "score": v, "deducted": max(0, 100 - int(v))}
        for k, v in sorted((exposure_subscores or {}).items())
    ]
    return {
        "pillars": rows,
        "structural": list(structural_parts or []),
        "exposure": exposure_rows,
        "arithmetic": {
            "weighted_sum":   round(_sum, 2),
            "raw":            int(raw_uncapped),
            "credits":        int(credits_applied or 0),
            "ceiling":        cap_applied,
            "ceiling_reason": cap_reason,
            "displayed":      int(displayed),
        },
        # `int()` truncation in _weighted_pillar_sum means the float sum sits
        # within 1 point above the integer raw - never below, never further.
        "reconciles": abs(_sum - int(raw_uncapped)) < 1.0,
        "weights_version": "c3_40_35_25",
    }


# ── Score caps and credits ───────────────────────────────────────────────────
# Behaviour is UNCHANGED from the three inline copies this replaces: a cap is a
# CEILING, never a floor (a submission already below it keeps its own value - 42
# with a hard stop stays 42 and is never raised to 60), hard takes absolute
# precedence over soft, and stops never stack, so one hard stop and fifteen
# produce the identical ceiling. The only additions are a single source of truth
# and a recorded REASON, so a capped score can be audited without reading code.
#
# WORDING: hard stops and warnings do NOT block anything a producer does.
# Nothing in the product gates generation or download on them. Their effects
# are the ceiling below, the card rendered on screen, and the readiness STATUS
# (since 19 Oct a hard stop also keeps "Submission Ready" and auto-quote off,
# which its 60 already makes unreachable). Do not reintroduce "blocked"
# language for a producer's actions.
#
# THE CAPS ARE BACK (owner, 20 Oct 2026, reversing the 19 Oct "no cap" build):
# an open hard stop holds the score at 60, an open warning at 85, exactly as
# before. What 19 Oct changed and still stands is WHICH items are hard stops -
# Brent's short list (documents naming different companies, no proposed term,
# property without Minimum Viable COPE, a monopolistic state with a private
# carrier, an umbrella with no underlying limits); everything else is a warning.
# The readiness fields (`readiness_fields`) ride along: under the caps a 90+ can
# only be reached with nothing open, so they always agree with the number.

HARD_STOP_CAP = 60
SOFT_STOP_CAP = 85


def _resolve_cap(
    hard_stops: Optional[List[str]],
    soft_stops: Optional[List[str]],
    hard_cross: Optional[List[str]] = None,
    extra_hard_reason: Optional[str] = None,
    extra_soft_reason: Optional[str] = None,
) -> Tuple[Optional[int], Optional[str]]:
    """Return (cap, reason) for the current stop set, or (None, None) if uncapped.

    `reason` names the specific condition that caused the cap so a score reads as
    one sentence - "88 raw, held at 60 by <reason>". `extra_*_reason` carries the
    per-form gates that live outside either list (since 19 Oct 2026: COPE=0
    hard; the umbrella hard with no underlying limit stated, soft when one is
    stated in words only; the property gate soft).
    """
    _hard = [str(m) for m in (hard_stops or []) if m]
    _hard += [str(m) for m in (hard_cross or []) if m]
    if extra_hard_reason:
        _hard.append(extra_hard_reason)
    if _hard:
        return HARD_STOP_CAP, _hard[0]

    _soft = [str(m) for m in (soft_stops or []) if m]
    if extra_soft_reason:
        _soft.append(extra_soft_reason)
    if _soft:
        return SOFT_STOP_CAP, _soft[0]

    return None, None


READY_TIER = "Submission Ready"


def tier_for_score(score: int, open_hard_stops: int = 0) -> Tuple[str, str, str]:
    """Return (grade, tier, tier_color) - the single tier ladder.

    A score of 90 or above is "Submission Ready" (owner decision, 2026-08-16) -
    unless a hard stop is open (Brent, 19 Oct 2026: a hard stop "blocks Ready to
    Submit until resolved"), when the tier is the rung below, "Almost There".
    The grade is the score's own letter either way. Under the caps (restored
    20 Oct 2026) an open hard stop already holds the number at 60, so this is
    the belt to their braces: a path that ever forgets the cap still cannot
    print "Submission Ready" beside an open hard stop.

    This boundary previously disagreed with itself in three places: both scorers
    used `> 90` while audit_routes._grade_from_score and BOTH frontend readiness
    surfaces ("Quote Ready" on the session list, "Ready to Send Submission" on
    the banner) used `>= 90`. Everything now resolves through this function at
    `>= 90`, which is also where the "A" grade already sat.
    """
    score = int(score or 0)
    grade = "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 60 else "F"
    if score >= 90:
        if int(open_hard_stops or 0) > 0:
            return grade, "Almost There", "yellow"
        return grade, READY_TIER, "green"
    if score >= 80:
        return grade, "Almost There", "yellow"
    if score >= 70:
        return grade, "Needs Work", "orange"
    if score >= 60:
        return grade, "Major Gaps", "red"
    return grade, "Not Ready", "red"


def routing_for_score(score: int, open_hard_stops: int = 0) -> str:
    """The cover's routing word for a score: auto-quote above 85 only with no
    open hard stop (the 60 cap already makes it unreachable with one open; the
    count guards a path that forgets the cap - same reason as `tier_for_score`)."""
    score = int(score or 0)
    if score > 85 and not int(open_hard_stops or 0):
        return "auto_quote"
    if score >= 70:
        return "priority_review"
    if score >= 50:
        return "standard_review"
    return "hold"


def readiness_fields(score: Optional[int], blockers: List[str], coded_issues=None,
                     facts=None) -> dict:
    """The readiness half of every score payload (19 Oct 2026): the open hard
    stops - each holds the score at 60 and blocks "Submission Ready" - as
    sentences and as clickable rows (`_cap_stop_items` - the same classification
    every stop uses), their count, and whether the score is Submission Ready.
    The cap fields themselves (`cap_applied`, `cap_hard_stops`, ...) are each
    scorer's own, written beside these."""
    blockers = [str(m) for m in dict.fromkeys(blockers or []) if m]
    return {
        "ready_blockers":      blockers,
        "ready_blocker_items": _cap_stop_items(blockers, coded_issues=coded_issues, facts=facts),
        "open_hard_stops":     len(blockers),
        "submission_ready":    bool(score is not None and int(score) >= 90 and not blockers),
    }


def one_blocker_per_conflict(blockers: List[str], session_data: Optional[dict]):
    """(blockers, the conflict cards): ONE blocker per conflicted fact (19 Oct 2026).

    The document check and the Data Consistency picker both state each
    applicant-name / FEIN disagreement - four sentences for two problems on a
    package naming two companies (D6: 33 / 22 stored packages). The review
    screen draws one card per fact - the picker's, hiding its document twin
    (`issue_registry`'s supersession) - so what blocks Submission Ready counts
    the same way: the picker's sentence, else the first. The cards come back
    too: each blocker row takes its own card's code (`underwriting_
    reconciliation_*` / `doc_conflict_*`), which is what offers "Fix in Data
    Consistency" - by its words alone the FEIN sentence classified as the FEIN
    FORMAT rule and opened a box to type a FEIN. Never raises; nothing to
    match changes nothing."""
    if not blockers or not isinstance(session_data, dict):
        return list(blockers or []), []
    try:
        from services.stops_now import conflict_stop_issues
        cards = conflict_stop_issues(session_data)
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("blocker conflicts not matched: %s", exc)
        return list(blockers), []
    if not cards:
        return list(blockers), []

    def _card(msg: str):
        return (next((c for c in cards if msg == c["message"]), None)
                or next((c for c in cards if msg.startswith(c["message"])), None))

    hits = [_card(m) for m in blockers]
    stated_by_picker = {h["fact"] for h in hits if h and h["picker"]}
    out: List[str] = []
    seen: set = set()
    for msg, hit in zip(blockers, hits):
        if hit is None:
            out.append(msg)
            continue
        if (hit["fact"] in stated_by_picker and not hit["picker"]) or hit["fact"] in seen:
            continue
        seen.add(hit["fact"])
        out.append(msg)
    return out, cards


def final_score_with_credits(
    raw_uncapped: int,
    credits_total: int = 0,
    cap: Optional[int] = None,
) -> int:
    """The number shown to the user: raw + earned credits, then capped.

    Credits are added to the RAW score, never to an already-capped one, so
    clearing the stops releases the full value the submission actually earned
    (owner's worked example: raw 65 capped to 60, +10 credited, stops then
    cleared -> 75, not 70). The cap still binds while a stop is open.
    """
    total = int(raw_uncapped or 0) + int(credits_total or 0)
    total = max(0, min(100, total))
    return total if cap is None else min(total, int(cap))


def apply_credits_to_score(sqs: Optional[dict], credits_total: int,
                           cap: Optional[int], score_key: str) -> Optional[dict]:
    """THE ONE DOOR for putting earned credits onto an already-computed score.

    A credit changes a score WITHOUT re-running the scorer, so nothing forces
    the score's own trace to keep up. Four call sites each patched
    `<score_key>` and `credits_applied` and left `score_trace.arithmetic`
    holding the scorer's original `credits: 0` - so the How line rendered
    **"81 earned = 85"**, a sum that does not add up, in the one panel built
    specifically to make the arithmetic reconcile.

    Measured live 2026-08-26: dismissing produced a correct
    *"81 earned + 6 credited, held at 85 = 85"*, and then editing any field put
    it straight back to "81 earned = 85" - because the edit path rebuilds the
    score (fresh trace, credits 0) and re-applies the credit afterwards.

    Every path that credits a score calls this, so the headline and the trace
    can never again disagree. Returns `sqs` for chaining; a dict with no
    `raw_sqs_score` (a legacy payload) is returned untouched rather than
    guessed at.
    """
    if not isinstance(sqs, dict) or sqs.get("raw_sqs_score") is None:
        return sqs
    credits_total = int(credits_total or 0)
    # A credit never lifts a score past the ceiling its own scorer applied
    # (20 Oct 2026). Every caller rebuilds `cap` from the stop LISTS, which miss
    # a form's own gates (COPE, the umbrella, the property gate) and the
    # package's own reclassified items, so the first credit released a gate's
    # 60 / 85 (open since 2026-08-31) - and, with the labels below following the
    # number, a released 99 read "Submission Ready" beside its open warning.
    # Every caller re-scores in the same request, so the payload's cap is fresh.
    _own = sqs.get("cap_applied")
    if _own is not None:
        try:
            cap = int(_own) if cap is None else min(int(cap), int(_own))
        except (TypeError, ValueError):
            pass
    displayed = final_score_with_credits(sqs["raw_sqs_score"], credits_total, cap)
    sqs[score_key] = displayed
    sqs["credits_applied"] = credits_total
    trace = sqs.get("score_trace")
    if isinstance(trace, dict) and isinstance(trace.get("arithmetic"), dict):
        trace["arithmetic"]["credits"] = credits_total
        trace["arithmetic"]["displayed"] = displayed
        trace["arithmetic"]["ceiling"] = cap
    # The labels follow the credited number (19 Oct 2026): a credit that lifts
    # a score to 90 makes it Submission Ready - unless its own hard stops are
    # open. They used to keep the scorer's pre-credit tier.
    if "open_hard_stops" in sqs:
        _open = int(sqs.get("open_hard_stops") or 0)
        _grade, _tier, _color = tier_for_score(displayed, _open)
        sqs["tier"] = _tier
        if "grade" in sqs:
            sqs["grade"] = _grade
        if "tier_color" in sqs:
            sqs["tier_color"] = _color
        if "routing_decision" in sqs:
            sqs["routing_decision"] = routing_for_score(displayed, _open)
        sqs["submission_ready"] = bool(displayed >= 90 and not _open)
    return sqs


def _present_doc_types(session_data: dict) -> set:
    """Set of canonical doc_types present in the session (Beta Report §4.2).

    Lets the SQS pillars credit classified supporting evidence - a narrative or
    loss-run document - even when the structured facts under-captured it. Reads
    the per-document classification stored on the session by the extraction
    pipeline; returns an empty set when docs are unavailable (e.g. unit tests),
    which leaves scoring at its evidence-from-facts behaviour.
    """
    docs = (session_data or {}).get("docs") or []
    return {
        str(d.get("doc_type") or "").strip()
        for d in docs
        if isinstance(d, dict) and not d.get("excluded")
    }


def _extract_narrative_doc_text(session_docs: list) -> str:
    """Return text for keyword-based narrative component scoring.

    Primary: concatenated full OCR text of all docs classified as 'narrative'.
    RULE 10 puts only the executive-summary block into account_description; the
    body (risk controls, carrier context, loss discussion) lives in doc["text"].

    Fallback: when no doc is classified as 'narrative', scan the bodies of all
    non-excluded docs. This closes the mis-classification gap: an uploaded
    narrative tagged "unknown" or "supplemental_application" still reaches the
    keyword component detector. The LLM profile (RULE 11 in extraction) already
    handles paraphrases; this fallback extends the keyword scan to the same set.
    Bounded to _NARRATIVE_LLM_MAX_CHARS to avoid unbounded text in the scanner.
    """
    parts = [
        str(d.get("text") or "")
        for d in (session_docs or [])
        if isinstance(d, dict)
        and not d.get("excluded")
        and str(d.get("doc_type") or "").strip() == "narrative"
        and d.get("text")
    ]
    if parts:
        return " ".join(parts)
    # No classified narrative — scan all non-excluded doc bodies as fallback
    fallback = [
        str(d.get("text") or "").strip()
        for d in (session_docs or [])
        if isinstance(d, dict) and not d.get("excluded") and d.get("text")
    ]
    return "\n\n".join(f for f in fallback if f)[:_NARRATIVE_LLM_MAX_CHARS]


def _build_narrative_scan_text(session_docs: list, facts: dict) -> str:
    """Union the text the LLM narrative detector should read.

    Deliberately NOT limited to docs classified as "narrative": it unions the
    classified-narrative bodies with the structured remarks/account-description
    and operations fields, and - when classification found no narrative at all -
    falls back to the bodies of the other (non-excluded) uploaded documents so a
    genuine narrative that was mis-classified is still considered (§6.3
    classification-dependency gap). Bounded to _NARRATIVE_LLM_MAX_CHARS.
    """
    facts = facts or {}
    parts: List[str] = []
    narr = _extract_narrative_doc_text(session_docs)
    if narr:
        parts.append(narr)
    remarks = _narrative_remarks_text(facts).strip()
    if remarks:
        parts.append(remarks)
    ops = str(_fv(facts, "operations_description") or "").strip()
    if ops:
        parts.append(ops)
    if not narr:
        # No classified narrative — scan the other document bodies as a safety
        # net so a mis-classified narrative still reaches the detector.
        for d in (session_docs or []):
            if not isinstance(d, dict) or d.get("excluded"):
                continue
            t = str(d.get("text") or "").strip()
            if t:
                parts.append(t)
    return "\n\n".join(p for p in parts if p)[:_NARRATIVE_LLM_MAX_CHARS]


# ── Umbrella enrichment (§6.5) - single source of truth for BOTH package scorers ─
# Shared so calculate_package_sqs and calculate_package_sqs_spec_compliant can
# never diverge on the umbrella warnings / review items (audit: spec-compliant
# variant must emit the same §6.5 enrichment if it is ever re-wired).

def _build_umbrella_warnings(facts: dict, flags: dict, p5: Optional[int]) -> List[str]:
    """Underlying-limit warning messages (client Q1/Q2). Empty unless an umbrella
    is present and its adequacy score is below full credit."""
    warnings: List[str] = []
    if not (flags.get("has_umbrella") and p5 is not None and p5 < 100):
        return warnings

    _gl_val  = _to_int(_fv(facts, "gl_limits") or _fv(facts, "gl_each_occurrence"))
    _gl_agg  = _to_int(_fv(facts, "gl_aggregate"))
    _auto_val = _to_int(_fv(facts, "auto_liability_limit"))
    if _gl_val is not None and _gl_val < _UMB_GL_OCC_MIN:
        warnings.append(
            f"Underlying GL limits may not meet umbrella requirements "
            f"(found ${_gl_val:,}, expected ${_UMB_GL_OCC_MIN:,}+)."
        )
    if _gl_agg is not None and _gl_agg < _UMB_GL_AGG_MIN:
        warnings.append(
            f"Underlying GL aggregate limit may not meet umbrella requirements "
            f"(found ${_gl_agg:,}, expected ${_UMB_GL_AGG_MIN:,}+)."
        )
    if _auto_val is not None and _auto_val < _UMB_AUTO_CSL_MIN:
        warnings.append(
            f"Underlying Auto limits may not meet umbrella requirements "
            f"(found ${_auto_val:,}, expected ${_UMB_AUTO_CSL_MIN:,}+)."
        )
    # Client Q2: surface a low/missing Employers Liability when umbrella is over
    # WC - the pillar's own reading (21 Oct 2026, `umbrella_underlying`): not
    # where the umbrella's schedule leaves EL out, nor when it prices EL itself.
    _el_line = _umb_lines(facts, flags)["workers_comp"]
    if _el_line["applicable"]:
        _el_val = _to_int(_fv(facts, "employers_liability_limits"))
        if _el_val is None:
            if not (_el_line["schedule_numeric"] or _el_line["fact_numeric"]):
                warnings.append(
                    "Employers Liability limit not provided for umbrella over Workers Comp "
                    f"(${_UMB_EL_OK:,} minimum, ${_UMB_EL_FULL:,} preferred)."
                )
        elif _el_val < _UMB_EL_OK:
            warnings.append(
                f"Employers Liability limit (${_el_val:,}) is below the ${_UMB_EL_OK:,} "
                "minimum preferred by umbrella markets."
            )
    # Client (DOUBTS-Workstream3): "No Schedule of Underlying Insurance -15" must
    # generate a warning. Mirror _calculate_umbrella_adequacy's detection so the
    # deduction is explained rather than silently applied.
    if not _umbrella_schedule_present(facts):
        warnings.append(
            "No Schedule of Underlying Insurance provided - umbrella adequacy "
            "reduced. Add the schedule of underlying GL / Auto / EL policies."
        )
    return warnings


def _build_umbrella_review_items(
    flags: dict, follow_form: dict, p5: Optional[int],
    facts: Optional[dict] = None,
) -> List[dict]:
    """Persistent review items that must never be dropped by the top_recs cap
    (§6.5 item 5): the follow-form gap, and an underlying auto whose limits
    cannot be compared to the CSL baseline."""
    items: List[dict] = []
    # V1 H1 (2026-08-26). A SPLIT-limit underlying auto states its limits but
    # not a combined single limit, so the $1M baseline comparison cannot run.
    # It carries NO deduction - comparing a per-person figure to a combined
    # baseline is a rule neither the client's document nor the spec defines,
    # and Principle 7 forbids inventing one - but it must not pass silently
    # either, or an inadequate $100k/$300k/$50k policy would score exactly like
    # an adequate one. It lives HERE rather than in `_build_umbrella_warnings`
    # because that list is suppressed at full credit, which is precisely the
    # case that needs saying.
    if flags.get("has_umbrella") and flags.get("has_auto_coverage") and facts is not None:
        try:
            from services.coverage_evidence import auto_split_limits_stated
            if auto_split_limits_stated(facts):
                items.append({
                    "pillar":  "umbrella_limit_adequacy",
                    "score":   p5 if p5 is not None else 0,
                    "action":  (
                        "Underlying Auto is written on SPLIT limits, so it cannot be "
                        f"compared to the ${_UMB_AUTO_CSL_MIN:,} combined-single-limit "
                        "baseline - confirm the umbrella attaches over them."
                    ),
                    "missing": ["underlying auto combined single limit"],
                    "review_item": True,
                })
        except Exception:                                      # noqa: BLE001
            pass
    if flags.get("has_umbrella") and follow_form.get("status") == "unable_to_determine":
        items.append({
            "pillar":  "umbrella_limit_adequacy",
            "score":   p5 if p5 is not None else 0,
            "action":  "Unable to determine whether umbrella follows form. Recommend underwriter review.",
            "missing": ["umbrella follow-form confirmation"],
            "review_item": True,
        })
    return items


BUILDING_VALUE_CONFLICT_MSG = ("Building value differs across submitted documents - confirm "
                               "the correct value before generating forms")


def building_value_cross_items(flags: Optional[dict], session_data: Optional[dict]) -> List[dict]:
    """The package's own cross item for a building value the documents disagree
    on - a conflict between documented EXPOSURES (the property's value): a
    warning costing its Exposure points until confirmed in Data Consistency
    (19 Oct 2026: it was a hard cross issue holding the package at 60; Brent -
    a hard stop only for what is essential, our call: fixed later without
    stopping the work). One builder for the scorer and the screen's points.

    RELEVANCE IS A PRECONDITION (C75, 2026-09-23): no property coverage, no
    item - the pipeline's ruling on the same fact ("cannot block anything on a
    package that has no property coverage"), measured on the live Orbin
    session. [] when nothing disagrees."""
    _uw = (session_data or {}).get("underwriting_consistency") or {}
    if not (flags or {}).get("has_property_coverage"):
        return []
    # A confirmed pick retires it, whatever the stored assessment says (29 Oct
    # 2026 - the one test `stops_now` applies to every picker row).
    try:
        from services.stops_now import _settled_by_confirmation as _settled
    except Exception:                                         # noqa: BLE001
        _settled = lambda _f, _c: False                       # noqa: E731
    _conf = (session_data or {}).get("underwriting_confirmations")
    if not any(isinstance(f, dict) and f.get("fact_key") == "property_building_value"
               and f.get("review_required") and not _settled(f, _conf)
               for f in (_uw.get("fields") or [])):
        return []
    return [{"type": "soft_warning", "field": "property_building_value",
             "message": BUILDING_VALUE_CONFLICT_MSG}]


def calculate_package_sqs(
    facts: dict,
    flags: dict,
    form_results: List[dict],
    cross_issues: List[dict],
    hard_stops: List[str],
    soft_stops: List[str],
    session_data: dict,
    mapped_data: Optional[dict] = None,
    confidence_dict: Optional[dict] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    calculation_stage: str = "initial_extract",
    _probe: bool = False,
    form_fill: bool = False,
) -> dict:
    """
    Calculate package-level SQS with 6 spec-compliant pillars (Decision Tree v2.1.0+).
    Pillars: structural_completeness (25%) + exposure_consistency (25%) +
             property_integrity (15%) + loss_history_alignment (15%) +
             umbrella_limit_adequacy (10%) + narrative_quality (10%)

    THE PACKAGE SCORE IS INDEPENDENT OF THE FORMS (Brent, 23 Oct 2026, Z34-1
    #1: "Yes, this is acceptable"). Structural is the C3 3.7 no-forms formula
    (Tier 1 53.3 / Tier 2 46.7) at EVERY stage - before forms, at generation,
    on a save, a recalculation, the worker - even when `form_results` or
    `mapped_data` are given. The fill rate is the "Forms ready" meter (the
    needs-attention verify / missing counts), never a slice of this number;
    each form keeps its own fill rate in its own score (Brent's Q4 is TBD).
    `form_fill=True` restores the old Form Fill Rate slice (13 Oct 2026 - 23 Oct
    2026) for a reversal only ("Subject to change"); no production caller
    passes it (`tests/test_build25_score.py` fails the build if one does).
    """
    # Normalize mutable args - callers occasionally pass None when the session
    # field exists but is stored as null in the DB.
    hard_stops  = hard_stops  or []
    soft_stops  = soft_stops  or []
    cross_issues = cross_issues or []
    _not_scored: List[dict] = []
    _not_scored_token = _NOT_SCORED.set(_not_scored)

    # Classified supporting-evidence presence feeds the narrative & loss-history
    # pillars so reclassifying a document measurably moves the score (§4.2).
    _present_types = _present_doc_types(session_data)
    _has_narrative = "narrative" in _present_types
    from services.loss_history_state import package_has_loss_runs
    _has_loss_run  = package_has_loss_runs((session_data or {}).get("docs"), facts)
    _session_docs  = (session_data or {}).get("docs") or []

    lob = infer_lob(facts, flags)

    # The cross-form issues first (19 Oct 2026): Completeness and Exposure both
    # read them - a check asking for a detail is Completeness's, a conflict
    # between documented exposures Exposure's (`coverage_deduction_items`).
    _cross = list(cross_issues or [])
    # A building value the documents disagree on (19 Oct 2026: a warning that
    # costs its Exposure points) - `building_value_cross_items`.
    _cross = _cross + building_value_cross_items(flags, session_data)
    hard_cross = [i for i in _cross if isinstance(i, dict) and i.get("type") == "hard_stop"]
    warn_cross = [i for i in _cross if isinstance(i, dict) and i.get("type") in _CROSS_WARNING_TYPES]

    # P1 - Structural Completeness: Tier 1 / Tier 2 (/ Form Fill Rate), less the
    # coverage details it now owns (19 Oct 2026, Brent: "Completeness deducts
    # for missing applicable required information" - the items that were
    # Exposure's, with the same points; `completeness_deduction_items`).
    _cov_items = completeness_deduction_items(facts, flags, hard_cross, warn_cross)
    _cov_points = sum(int(i.get("points") or 0) for i in _cov_items)
    _cov_labels = [str(i.get("label") or "") for i in _cov_items if i.get("label")]
    tier1_ok, tier1_missing = check_tier1(facts, flags)
    tier2_score, tier2_missing = check_tier2(facts, flags)
    tier1_score = 100 if tier1_ok else max(0, 100 - len(tier1_missing) * 20)
    # "Form Fill Quality" = average confidence_fill_rate across generated forms.
    # confidence_fill_rate is the % of ALL ACORD form fields that received a value
    # (weighted by AI confidence), which is a genuinely different signal from the
    # per-form structural_completeness checklist (which only tests 4-6 key binary
    # fields). Using structural_completeness here caused package P1 to shadow the
    # form P1 whenever those checklist fields were all present, driving convergence
    # of package and form headline scores for single-form submissions.
    _form_fill_rates = [
        r.get("confidence_fill_rate")
        for r in (form_results or [])
        if isinstance(r, dict) and isinstance(r.get("confidence_fill_rate"), (int, float))
    ] if form_fill else []
    if not form_fill:
        mapped_data = None          # the fill is the Forms ready meter, not this number
    if _form_fill_rates:
        _fill_avg = int(sum(_form_fill_rates) / len(_form_fill_rates))
        p1 = max(0, int(tier1_score * _W_TIER1 + tier2_score * _W_TIER2
                        + _fill_avg * _W_FILL) - _cov_points)
        _p1_parts = _structural_parts(tier1_score, tier2_score, _fill_avg,
                                      tier1_missing, tier2_missing, _cov_points, _cov_labels)
    elif mapped_data:
        # Forms WERE generated (mapped_data only exists after form fill), we just
        # have no per-form result rows - so the fill component still applies and
        # the confidence fill rate IS it.
        conf_rate = confidence_fill_rate(mapped_data, confidence_dict or {})
        p1 = max(0, int(tier1_score * _W_TIER1 + tier2_score * _W_TIER2
                        + conf_rate * _W_FILL) - _cov_points)
        _p1_parts = _structural_parts(tier1_score, tier2_score, conf_rate,
                                      tier1_missing, tier2_missing, _cov_points, _cov_labels)
    else:
        # C3 3.7 - no ACORD forms generated: drop the Form Fill Rate component
        # and rescale the other two proportionally, preserving the 40:35 ratio.
        p1 = max(0, int(tier1_score * _W_NOFORM_TIER1 + tier2_score * _W_NOFORM_TIER2)
                 - _cov_points)
        _p1_parts = _structural_parts(tier1_score, tier2_score, None,
                                      tier1_missing, tier2_missing, _cov_points, _cov_labels)

    # P2 - Exposure Consistency (the conflicts - 19 Oct 2026)
    p2, _exposure_subscores = _calculate_exposure_consistency(facts, flags, hard_cross, warn_cross)

    # P3 - Property Integrity
    p3 = _calculate_cope_score(facts, flags)

    # P4 - Loss History Alignment (with insured-match check, Q3)
    _loss_run_detail = _check_loss_run_insured_match_detail(
        _session_docs, _fv(facts, "applicant_name"), facts)
    _loss_run_match = _loss_run_detail["tier"]
    p4, p4_recs = calculate_p4_loss_history(
        facts, flags,
        has_loss_run_doc=_has_loss_run,
        loss_run_match=_loss_run_match,
    )

    # P5 - Umbrella & Limit Adequacy (None = N/A, weights re-normalised below)
    p5 = _calculate_umbrella_adequacy(facts, flags)

    # P6 - Narrative Quality with component model (§6.3)
    _narr_doc_text = _extract_narrative_doc_text(_session_docs)
    p6, _narrative_components, _narr_substance = _calculate_narrative_quality(
        facts, has_narrative_doc=_has_narrative, flags=flags,
        narrative_doc_text=_narr_doc_text,
        form_ids=session_form_ids(session_data, form_results),
    )
    # The text the depth check read - the card names what it still lacks.
    _narrative_text_for_card = " ".join(filter(None, [
        _narr_doc_text, _narrative_remarks_text(facts)])) or str(_fv(facts, "operations_description") or "")
    try:
        from services.narrative_reader import credited as _credited_reading
        _card_read_depth = _credited_reading(facts, _narrative_remarks_text(facts).strip())[1]
    except Exception:                                          # noqa: BLE001
        _card_read_depth = set()

    # ── Package pillars = the package's OWN independent calculation ───────────
    # The package SQS is computed independently from the per-form scores. Each of
    # the six pillars (p1-p6 above) is derived directly from the merged facts /
    # flags / session evidence by the package-level calculators, and the headline
    # below is the WEIGHTED SUM of those six pillars. It is NOT an average of the
    # per-form headlines and NOT an average of the per-form pillars (the prior
    # model). This is the client-approved design: the package carries its own
    # structural blend (P1 = tier1/tier2/form-fill), its own exposure / COPE /
    # loss / umbrella / narrative reads, plus the cross-form caps applied below -
    # factors no single form can see. Consequently the package score genuinely
    # differs from any individual form, even when only one form is in the
    # submission (different P1 formula, and none of the per-form structural cap
    # gates), which is exactly what the "Form vs Package can differ" UI note
    # explains. p1-p6 are already set from facts above; nothing overrides them.
    # form_results is still consumed (P1's form-fill grounding above), but never
    # to copy or average a per-form headline into the package score.

    # Package SQS headline = weighted sum of the package's own six pillars
    # (re-normalised when the umbrella pillar is N/A so it counts as excluded, not
    # zero). Computed independently of the per-form scores. Hard stops cap at 60,
    # soft stops at 85.
    # Generic N/A rescaling (client C2 2.2): p5 is None with no umbrella, p4 is
    # None for a verified new venture - _weighted_pillar_sum drops any None
    # pillar and rescales the remaining original weights proportionally.
    raw = _weighted_pillar_sum(
        {
            "structural_completeness": p1,
            "exposure_consistency":    p2,
            "property_integrity":      p3,
            "loss_history_alignment":  p4,
            "umbrella_limit_adequacy": p5,
            "narrative_quality":       p6,
        },
        SPEC_PILLAR_WEIGHTS,
    )
    # The UNCAPPED weighted sum is preserved before capping. It used to be
    # overwritten here, which made a capped score impossible to audit (an 88 held
    # at 60 was indistinguishable from a genuine 60) and meant later gains had to
    # compound off the capped value instead of the real one. Owner's rule: keep
    # the raw score, cap only what is DISPLAYED, and add any later gain to the
    # raw - so raw 65 capped to 60, then +10 earned, must read 75 and not 70.
    raw_uncapped = max(0, min(100, raw))
    # THE ITEMS 19 OCT RECLASSIFIED HOLD THEIR CAP ON EVERY PATH (20 Oct 2026).
    # At HEAD the scorer's own building-value item and the two Lite checks that
    # were hard stops reached the cap through `hard_cross`, whatever lists the
    # caller passed, so a post-form recalculation or a field edit (whose lists
    # never carry the Data Consistency row) still held them at 60. They are
    # warnings now (Brent's short list) and hold the 85 the same way: the
    # scorer's own building-value item, and every cross item marked
    # `escalates_acord101` (a hard stop before 19 Oct). Ordinary cross warnings
    # keep HEAD's rule - the stops door puts them in `soft_stops`. Appended
    # after the caller's list, so a listed warning still names the 85.
    _held_soft = [str(i.get("message")) for i in warn_cross
                  if isinstance(i, dict) and i.get("message")
                  and (i.get("message") == BUILDING_VALUE_CONFLICT_MSG or i.get("escalates_acord101"))]
    cap_applied, cap_reason = _resolve_cap(
        hard_stops,
        release_unanswerable_holds(
            list(soft_stops or []) + [m for m in _held_soft if m not in (soft_stops or [])],
            cross_issues),
        hard_cross=[i.get("message") for i in hard_cross if isinstance(i, dict)],
    )
    raw = raw_uncapped if cap_applied is None else min(raw_uncapped, cap_applied)
    raw = max(0, min(100, raw))

    # ── THE CARD MUST MATCH THE CAP (owner, 2026-08-31) ─────────────────────
    # A 60 held by anything other than `hard_stops` had no card: a `hard_cross`
    # entry on a route that does not inject cross issues survived only as
    # `cap_reason` - a sentence the pre-form Review screen never prints. Since
    # 19 Oct 2026 the building value the documents disagree on is a warning
    # (`building_value_cross_items`, Brent's short hard-stop list), so it no
    # longer reaches this list - it holds the 85 (`_held_soft` above).
    #
    # `_resolve_cap` reads `hard_stops` FIRST, so `cap_reason not in hard_stops`
    # proves no existing card carries this message. Display only: the caller's
    # arrays are untouched and no score moves.
    cap_hard_stops: List[str] = []
    cap_hard_stop_codes: List[str] = []
    if (cap_applied == HARD_STOP_CAP and cap_reason
            and cap_reason not in (hard_stops or [])):
        cap_hard_stops.append(cap_reason)

    # The open hard stops - each holds the 60 and blocks "Submission Ready": the
    # package's list and a hard cross-form issue (`readiness_fields`).
    _blockers = list(dict.fromkeys(
        [str(m) for m in hard_stops if m]
        + [str(i.get("message")) for i in hard_cross if isinstance(i, dict) and i.get("message")]))
    # One conflict, one blocker - and its row opens Data Consistency. Not in a
    # probe: a probe reads the number only.
    _blocker_cards: List[dict] = []
    if not _probe:
        _blockers, _blocker_cards = one_blocker_per_conflict(_blockers, session_data)
    tier = tier_for_score(raw, len(_blockers))[1]

    history   = list(session_data.get("sqs_history", []))
    stage     = calculation_stage
    timestamp = datetime.utcnow().isoformat() + "Z"

    # §6.2: track avg confidence fill rate per stage so the frontend can show
    # "Quality Fill Rate: X% → Y% after client questionnaire."
    _form_fill_rates = [
        r.get("confidence_fill_rate") for r in (form_results or [])
        if isinstance(r, dict) and r.get("confidence_fill_rate") is not None
    ] if form_fill else []
    _avg_fill = int(sum(_form_fill_rates) / len(_form_fill_rates)) if _form_fill_rates else None

    new_entry = {
        "at": timestamp, "score": raw, "stage": stage,
        "model_version": SQS_MODEL_VERSION, "weights_version": "spec_compliant_v2.3.0",
        "avg_fill_rate": _avg_fill,
    }
    if not history or (history[-1].get("score") != raw or history[-1].get("stage") != stage):
        history.append(new_entry)

    _baseline = next(
        (h for h in history if h.get("stage") == "initial_extract"),
        history[0] if history else None,
    )
    delta = (raw - _baseline["score"]) if (_baseline and len(history) > 1) else 0

    # Top recommendations (ranked by score, hard-stops surfaced first)
    _pillar_scores = {
        "structural_completeness": p1,
        "exposure_consistency":    p2,
        "property_integrity":      p3,
        "loss_history_alignment":  p4,
        "umbrella_limit_adequacy": p5,  # None when N/A — excluded from ranking
        "narrative_quality":       p6,
    }
    # ── EVERY GAP, RANKED BY WHAT IT IS WORTH (2026-09-23) ──────────────────
    # This used to be `sorted by score ascending, keep those under 90, take the
    # first three`. Three things were wrong with that, and together they are why
    # a producer with ZERO open warnings and a score of 78 had nothing to act on:
    #
    #   1. THE [:3] CAP HID REAL POINTS. A package with four weak pillars showed
    #      three. On the live session Exposure sat at 82 and was worth 5.3
    #      points, and because three lower-scoring pillars existed it got no row
    #      anywhere in the product.
    #   2. THE `< 90` FILTER HID MORE. A pillar at 92 still costs points; at the
    #      .25 weights that is over a point, and it was never mentioned.
    #   3. RANKING BY SCORE IS THE WRONG ORDER. Pillars carry different weights,
    #      so a low score on a light pillar can rank above a mild gap on a heavy
    #      one. Measured on the live package: narrative 40 (worth 7.1) sorted
    #      ABOVE structural 70 (worth 8.8), so the panel's "Best Solutions"
    #      recommended the smaller win first.
    #
    # Now: every applicable pillar that is short of 100, ordered by the points
    # it would actually return, using the SAME effective weights the score used
    # (so a Not Applicable pillar's weight is already redistributed and the
    # numbers add up to the real gap). N/A pillars stay excluded - they are not
    # a gap, they are removed from the calculation entirely.
    _na_pillars = [k for k, v in _pillar_scores.items() if v is None]
    _live_weight = sum(w for k, w in SPEC_PILLAR_WEIGHTS.items()
                       if k not in _na_pillars) or 1.0

    def _points_available(pillar: str, score: float) -> float:
        eff = SPEC_PILLAR_WEIGHTS.get(pillar, 0.0) / _live_weight
        return round((100 - score) * eff, 1)

    _ranked_pillars = sorted(
        ((k, v) for k, v in _pillar_scores.items() if v is not None and v < 100),
        key=lambda x: -_points_available(x[0], x[1]),
    )
    # §6.3 AC#4: build per-component narrative gap list so top_recs can emit a
    # targeted message instead of the generic "Improve narrative quality" fallback.
    _absent_narrative_comps = [
        NARRATIVE_COMPONENT_LABELS[k]
        for k, present in _narrative_components.items()
        if not present
    ] if _narrative_components else []
    _miss_by_pillar = {
        "structural_completeness": list(tier1_missing) + list(tier2_missing),
        "loss_history_alignment":  list(p4_recs),
        "narrative_quality":       _absent_narrative_comps,
    }
    top_recs: List[dict] = []
    if _blockers:
        top_recs.append({"pillar": "hard_stops_present", "score": 0,
                          "action": _blockers[0],
                          "missing": _blockers[:3]})
    # THE LOSS HISTORY PLAN (owner, 23 Oct 2026): one ordered list of what takes
    # the pillar to its maximum, each step worth what it adds after the ones
    # above it (`loss_history_plan`). Not in a probe: a probe reads the number.
    _loss_plan: Optional[List[dict]] = None
    try:
        from services.loss_history_state import narrative_answer_mismatch as _narr_mm
        _narr_claims = _narr_mm(facts) == "claims"
    except Exception:                                          # noqa: BLE001
        _narr_claims = False
    if not _probe and ((p4 is not None and p4 < 100) or _narr_claims):
        try:
            _loss_plan = loss_history_plan(facts, flags, _session_docs, _pillar_scores)
        except Exception as _lpx:                              # noqa: BLE001
            logger.warning("loss history plan skipped: %s", _lpx)
            _loss_plan = None
    for pillar, score in _ranked_pillars:
        # NO `[:3]` - see the ranking note above. The producer is shown every
        # gap that is worth points, because a gap nobody renders is a gap nobody
        # can close, and that is exactly how a package with no open warnings sat
        # 22 points short with nothing on screen to act on.
        miss_list = _miss_by_pillar.get(pillar, [])
        # ONE ROW PER QUESTION (13 Oct 2026, owner + Brent: the SQS reaches 100
        # when everything is answered). Exposure and Property used to give one
        # row per PILLAR - "Incomplete: Auto Completeness", "Improve property
        # integrity" - with no box behind it, so the Recommendations section
        # listed nothing and the last points (a radius of operation, the
        # distance to a hydrant) could not be answered anywhere. Each deduction
        # is now its own row naming the box that closes it, read off the SAME
        # items the pillar is scored from.
        # LOSS HISTORY: the plan's steps, in plan order - an answer row per step
        # a person types, a document row per step a document closes (mark,
        # upload). Each carries `plan_order` and its true sequential number; a
        # step worth 0 is not listed.
        if pillar == "loss_history_alignment" and _probe:
            continue
        if pillar == "loss_history_alignment" and _loss_plan is not None:
            for _st in _loss_plan:
                # The claims question stays listed at 0 when it is applied
                # (a narrative-agreeing "we have had claims" - the rows after
                # it carry the points; 24 Oct 2026).
                if int(_st.get("points") or 0) <= 0 and not (
                        _st.get("key") == "claims" and _st.get("applied")):
                    continue
                _row = {"pillar": pillar, "score": score, "action": _st["label"],
                        "missing": [_st["label"]], "field": _st.get("fact"),
                        "points_available": float(_st["points"]),
                        "closes_with": "type" if _st.get("fact") else "document",
                        "plan_order": _st["plan_order"], "plan_step": _st["key"]}
                if _st.get("fact"):
                    _row.update(answer_gain=int(_st["points"]),
                                answer_gain_is_exact=bool(_st.get("exact", True)),
                                answer_gain_share=True, answer_gain_alone=int(_st["points"]))
                if _st.get("doc_id"):
                    _row["doc_id"] = _st["doc_id"]
                if _st.get("key") == "claims" and int(_st.get("points") or 0) <= 0:
                    # Listed with no number (the rows after it carry the points):
                    # the page shows it instead of dropping a 0 (25 Oct 2026).
                    _row["listed_at_zero"] = True
                elif _st.get("key") == "claims" and _st.get("exact") is False:
                    # Option A (owner, 25 Oct 2026): the question alone, "up to"
                    # what its follow-ups unlock - the page's plan would credit
                    # those points to rows not listed yet.
                    _row["listed_at_zero"] = True
                    _row["unlocks_points"] = int(_st.get("points") or 0)
                top_recs.append(_row)
            # `points_available` is the PILLAR's weighted gap (it ranks the rows and
            # sums to points_remaining); the plan's whole-point numbers ride as
            # answer_gain. What whole points leave goes on the last listed step.
            _lh_rows = [r for r in top_recs if r.get("pillar") == pillar]
            if _lh_rows:
                _gap = round((100 - int(score)) * SPEC_PILLAR_WEIGHTS.get(pillar, 0.0)
                             / _live_weight, 1)
                _sum = sum(float(r["points_available"]) for r in _lh_rows)
                if _gap > _sum:
                    _lh_rows[-1]["points_available"] = round(
                        float(_lh_rows[-1]["points_available"]) + _gap - _sum, 1)
            continue
        if pillar in ("exposure_consistency", "property_integrity", "umbrella_limit_adequacy"):
            try:
                _items = (exposure_deduction_items(facts, flags, hard_cross, warn_cross)
                          if pillar == "exposure_consistency"
                          else property_gap_items(facts, flags)
                          if pillar == "property_integrity"
                          else umbrella_gap_items(facts, flags))
            except Exception as _gx:                           # noqa: BLE001
                logger.warning("gap rows skipped for %s: %s", pillar, _gx)
                _items = []
            if _items:
                top_recs.extend(_gap_rows(pillar, score, _items,
                                          SPEC_PILLAR_WEIGHTS.get(pillar, 0.0) / _live_weight))
                continue
        # STRUCTURAL'S COVERAGE DETAILS (19 Oct 2026): one row per detail, worth
        # its own points; the Tier 1 / Tier 2 / Fill row below keeps the rest of
        # the pillar's gap.
        _struct_rest = None
        if pillar == "structural_completeness" and _cov_points:
            _taken = next((int(p.get("deducted") or 0) for p in _p1_parts
                           if p.get("key") == "coverage_details"), 0)
            _eff_sc = SPEC_PILLAR_WEIGHTS.get(pillar, 0.0) / _live_weight
            if _taken:
                top_recs.extend(_gap_rows(pillar, score, _cov_items,
                                          _eff_sc * _taken / _cov_points))
            _struct_rest = max(0, 100 - int(score) - _taken)
            if not _struct_rest:
                continue
        if pillar == "narrative_quality" and _narrative_components:
            # §6.3 AC#4: state what the narrative covers alongside what it lacks.
            _action = _narrative_gap_message(_narrative_components)
            if not _action:
                # All components present but substance quality is thin
                if _narr_substance < 30:
                    _action = (
                        "Narrative covers all required topics but lacks underwriting depth - "
                        "add specific risk details, loss context, and market considerations"
                    )
                else:
                    # Name what the depth check still misses (owner, 13 Oct 2026:
                    # the bare "Improve narrative quality" left a producer who had
                    # covered every topic with nothing to act on).
                    _thin = narrative_substance_gaps(_narrative_text_for_card, _card_read_depth)
                    _action = (miss_list[0] if miss_list else
                               ("Narrative covers every topic - add " + _words_list(_thin)
                                if _thin else "Improve narrative quality"))
        elif pillar == "exposure_consistency" and not miss_list and _exposure_subscores:
            # NAME THE BUCKET, don't say "improve exposure consistency" - that
            # sentence tells a producer nothing they can act on, and this pillar
            # is frequently the largest remaining gap once the obvious ones are
            # closed. The sub-scores are already computed by
            # `_calculate_exposure_consistency`; this only reads them.
            _weak = sorted(
                ((k, v) for k, v in (_exposure_subscores or {}).items()
                 if isinstance(v, (int, float)) and v < 100),
                key=lambda x: x[1],
            )
            if _weak:
                _action = "Incomplete: " + ", ".join(
                    exposure_bucket_label(k) for k, _v in _weak[:3])
            else:
                _action = "Improve exposure consistency"
        elif pillar == "structural_completeness" and not miss_list and _form_fill_rates:
            # Tier 1 and Tier 2 are complete: what is left is the form boxes'
            # Fill Rate (13 Oct 2026) - values the AI placed that nobody has
            # checked. Each one is a Please verify row with a Confirm.
            _action = ("Confirm the Please verify values on each form "
                       f"(Form Fill Rate {int(sum(_form_fill_rates) / len(_form_fill_rates))}%)")
        else:
            _action = miss_list[0] if miss_list else f"Improve {pillar.replace('_', ' ')}"
        # EVERY MISSING KEY DETAIL IS ITS OWN ROW (owner rule G2, 30 Oct 2026).
        # One row naming only `miss_list[0]` meant answering it revealed the next
        # ("Proposed effective date" appeared after "Producer / Agency name" was
        # answered) - a correct answer raised an item that was not listed before.
        # Each Tier 1 / Tier 2 label now gets its own row from the start, the way
        # `_gap_rows` lists the Exposure / Property / Umbrella items; the pillar's
        # points are shared by what each label costs (Tier 1 20 each, Tier 2 its
        # equal share), so the rows still add up to the pillar's gap.
        if pillar == "structural_completeness" and len(miss_list) > 1:
            _total = (_points_available(pillar, score) if _struct_rest is None
                      else _points_available(pillar, 100 - _struct_rest))
            _w = {p.get("key"): float(p.get("weight") or 0.0) for p in _p1_parts}
            _t1 = [m for m in miss_list if m in tier1_missing]
            _t2 = [m for m in miss_list if m not in tier1_missing]
            _cost: List[float] = []
            for _m in miss_list:
                if _m in _t1:
                    _cost.append(min(20.0, (100 - int(tier1_score)) / max(1, len(_t1)))
                                 * _w.get("tier1", 0.0))
                else:
                    _cost.append((100 - int(tier2_score)) / max(1, len(_t2)) * _w.get("tier2", 0.0))
            _sum_cost = sum(_cost)
            # Tenths shared by largest remainder, so the rows add up to exactly
            # the pillar's (rounded) gap.
            _tenths_total = int(round(_total * 10))
            _quota = [(_tenths_total * _c / _sum_cost) if _sum_cost else
                      (_tenths_total / len(miss_list)) for _c in _cost]
            _tenths = [int(q) for q in _quota]
            for _n in sorted(range(len(_quota)), key=lambda n: -(_quota[n] - _tenths[n]))[
                    :_tenths_total - sum(_tenths)]:
                _tenths[_n] += 1
            for _m, _t in zip(miss_list, _tenths):
                _f = _pillar_rec_field(pillar, _m, facts)
                top_recs.append({"pillar": pillar, "score": score, "action": _m,
                                 "missing": [_m], "field": _f,
                                 "points_available": _t / 10.0,
                                 "closes_with": "type" if _f else "review"})
            continue
        _field = _pillar_rec_field(pillar, _action, facts)
        # WHAT WOULD ACTUALLY CLOSE THIS. A producer needs to know whether a gap
        # is theirs to type or waits on the insured to send something - without
        # it, a package whose last points need a loss run reads exactly like one
        # that is a keystroke away.
        # An attestation the producer can select closes the loss gap too (29 Sep
        # 2026, item 15: an uncontradicted "no known losses" makes the pillar
        # Not Applicable), so that gap is typed, not waiting on a document.
        if (pillar == "loss_history_alignment" and not _has_loss_run
                and _field != "loss_history_no_prior_losses_indicator"):
            _closes = "document"
        elif pillar == "narrative_quality" and not _has_narrative and not _field:
            _closes = "document"
        elif _field:
            _closes = "type"
        else:
            _closes = "review"
        top_recs.append({"pillar": pillar, "score": score,
                          "action": _action,
                          "missing": miss_list[:3],
                          # The narrative window's tickable "still missing" list.
                          **({"narrative_gaps": narrative_gap_options(
                                _narrative_components, _narrative_text_for_card, _card_read_depth)}
                             if pillar == "narrative_quality" and _narrative_components else {}),
                          # So `_route_recommendations` can ask the ONE DOOR
                          # whether this is answerable, instead of defaulting
                          # every package recommendation to "none".
                          "field": _field,
                          # The whole point of the change: what this gap is
                          # WORTH, in the same points the headline is in, and
                          # how it gets closed.
                          "points_available": (_points_available(pillar, score)
                                               if _struct_rest is None else
                                               _points_available(pillar, 100 - _struct_rest)),
                          "closes_with": _closes})

    # Enrichment - new fields added in §6 (additive, never breaks existing callers)
    _umbrella_state    = _get_umbrella_state(facts, flags)
    _loss_history_state = _get_loss_history_state(facts, flags, _has_loss_run, _loss_run_match)
    _follow_form       = _get_follow_form_status(facts)
    _evidence_labels   = _derive_evidence_labels(facts, cross_issues=_cross, flags=flags, has_loss_run_doc=_has_loss_run)
    _positive_signals  = _compute_positive_signals(facts, flags, _has_narrative, _has_loss_run)
    # Extraction Confidence: AI fill quality reported separately from SQS (client spec).
    _conf_rate_breakdown = (
        int(sum(_form_fill_rates) / len(_form_fill_rates)) if _form_fill_rates
        else (confidence_fill_rate(mapped_data, confidence_dict or {}) if mapped_data else None)
    )
    _extraction_confidence = _conf_rate_breakdown
    _category_breakdown = _compute_category_breakdown(
        facts, flags,
        cross_issues=_cross,
        tier1_score=tier1_score,
        tier2_score=tier2_score,
        conf_rate=_conf_rate_breakdown,
        exposure_subscores=_exposure_subscores,
        doc_types=_present_types,
        structural_parts=_p1_parts,
    )
    # C3 Desired Outcome - the ledger behind this number, emitted by the scorer
    # that produced it. `credits_applied` is 0 here by design: credits are added
    # by the caller (audit_routes / recalculate_session_scores / update_pdf),
    # which rewrites `arithmetic.credits` and `arithmetic.displayed` when it
    # does. See build_score_trace.
    _score_trace = build_score_trace(
        pillars={
            "structural_completeness": p1,
            "exposure_consistency":    p2,
            "property_integrity":      p3,
            "loss_history_alignment":  p4,
            "umbrella_limit_adequacy": p5,
            "narrative_quality":       p6,
        },
        weights=SPEC_PILLAR_WEIGHTS,
        raw_uncapped=raw_uncapped,
        cap_applied=cap_applied,
        cap_reason=cap_reason,
        displayed=raw,
        structural_parts=_p1_parts,
        exposure_subscores=_exposure_subscores,
    )
    # Inject computed P4/P5/P6 into the loss/umbrella/narrative sub-rows
    _category_breakdown["loss_history_alignment"]["loss_history"]["score"] = p4
    _category_breakdown["loss_history_alignment"]["loss_history"]["status"] = (
        "not_applicable" if p4 is None
        else ("ok" if p4 >= 80 else ("partial" if p4 >= 40 else "insufficient"))
    )
    _category_breakdown["umbrella_limit_adequacy"]["umbrella_limits"]["score"] = p5
    _category_breakdown["umbrella_limit_adequacy"]["umbrella_limits"]["status"] = (
        "not_applicable" if p5 is None else ("ok" if p5 >= 80 else "needs_review")
    )
    _category_breakdown["narrative_quality"]["narrative_quality"]["score"] = p6
    _category_breakdown["narrative_quality"]["narrative_quality"]["status"] = (
        "ok" if p6 >= 70 else ("partial" if p6 >= 40 else "insufficient")
    )

    # L7 fix: emit follow-form gap as a tracked top-recommendation when umbrella is
    # present but follow-form status cannot be confirmed (§6.5 item 5).
    # The follow-form review item is ALSO carried in a dedicated review_items array
    # (outside the 3-item top_recs cap) so a coverage-critical follow-form gap is
    # never silently dropped when higher-priority hard stops already fill top_recs.
    review_items = _build_umbrella_review_items(flags, _follow_form, p5, facts)
    # Surface the follow-form review item in top_recs too when there is still room
    # (max 3). It is never lost regardless - review_items carries it unconditionally.
    # The follow-form one is not added when the umbrella rows already ask for the
    # answer itself (15 Oct 2026, `umbrella_gap_items`): a second, box-less row
    # for the same question is the one that could never be answered.
    _asked = {r.get("field") for r in top_recs if isinstance(r, dict)}
    _review_rows = [r for r in review_items
                    if not ("umbrella follow-form confirmation" in (r.get("missing") or [])
                            and "umbrella_follow_form" in _asked)]
    if _review_rows and len(top_recs) < 3:
        top_recs.append(_review_rows[0])

    # Umbrella warning messages for low underlying limits (client Q1/Q2: warn, not block)
    _umbrella_warnings = _build_umbrella_warnings(facts, flags, p5)

    _screen_shares = None
    # ONE NUMBER PER CARD (1 Oct 2026, Orbin item 19) - see `_unify_card_points`.
    # Never inside a probe run: a probe asks only for the number.
    if not _probe:
        def _headroom(component: Optional[str]) -> Optional[float]:
            if component not in _pillar_scores:
                return None
            score = _pillar_scores[component]
            return 0.0 if score is None else _points_available(component, score)

        def _rescore(probed_facts: dict) -> Optional[int]:
            # The scorer itself, never whatever the public name is wrapped in
            # (a caller's spy or stub): a probe is part of ONE scoring.
            return _PACKAGE_SCORER(
                facts=probed_facts, flags=flags, form_results=form_results,
                cross_issues=cross_issues, hard_stops=hard_stops,
                soft_stops=soft_stops, session_data=session_data,
                mapped_data=mapped_data, confidence_dict=confidence_dict,
                calculation_stage=calculation_stage, _probe=True,
                form_fill=form_fill,
            ).get("raw_sqs_score")

        try:
            if not SKIP_SHARE_OUT.get():
                _screen_shares = _unify_card_points(
                    form_results, top_recs, facts, raw_uncapped, cap_applied, _headroom, _rescore,
                    screen=screen_fields(facts, flags, hard_stops, soft_stops, cross_issues),
                    pillar_remaining=lambda _p: _pillar_remaining_points(_pillar_scores, _p, raw_uncapped),
                    # The Loss History plan's own answers are the probes for
                    # its facts (the conflict's truthful answer, the runs' years).
                    probe_values=loss_plan_probes(_loss_plan))
        except Exception as _unify_ex:                       # noqa: BLE001
            # Never break scoring: the cards keep each form's own number.
            logger.warning("card points not unified: %s", _unify_ex)

    _NOT_SCORED.reset(_not_scored_token)
    return {
        "package_sqs_score": raw,
        # The safety net (27 Oct 2026): deductions and holds no item on the page
        # can answer, not charged - for the cover and the logs, never the page.
        "not_scored":        list(_not_scored),
        # Every fact on the review screen -> [points, exact, alone] (15 Oct 2026,
        # `screen_fields` / `_unify_card_points`); completed by the review screen.
        "screen_shares":     _screen_shares or {},
        # Audit trail for the cap (2026-08-16). `package_sqs_score` is what the
        # user sees; these three say what it would have been and why it was held.
        # raw_sqs_score is also the base every later credit is added to, so a
        # released cap returns the full value the submission actually earned.
        "raw_sqs_score":     raw_uncapped,
        "cap_applied":       cap_applied,
        "cap_reason":        cap_reason,
        # A 60 cap with no card of its own - rendered as a hard stop by every
        # display surface so the card can never disagree with the maths.
        # `cap_hard_stop_codes` names an EXISTING card for the same fact, which
        # the display promotes instead of drawing a duplicate row.
        "cap_hard_stops":       cap_hard_stops,
        "cap_hard_stop_codes":  cap_hard_stop_codes,
        # ...and CLICKABLE (2026-09-08). The editor's package HARD STOPS block
        # falls back to `cap_reason` when `cap_hard_stops` is empty - which is
        # the COMMON case, because a cap whose reason is already a hard stop
        # deliberately produces no extra entry. Classified through the same
        # table every other stop uses (and a conflict's own card - 19 Oct 2026,
        # `one_blocker_per_conflict`), so the row carries the identical "Open
        # to fix".
        "cap_hard_stop_items": _cap_stop_items(
            cap_hard_stops
            or ([cap_reason] if cap_applied == HARD_STOP_CAP and cap_reason else []),
            coded_issues=list(_blocker_cards) + list(cross_issues or []), facts=facts),
        # The open hard stops (each holds the 60 and blocks "Submission
        # Ready"), one per conflict - `readiness_fields`.
        **readiness_fields(raw, _blockers, coded_issues=list(_blocker_cards) + list(cross_issues or []),
                           facts=facts),
        "tier": tier,
        "lob": lob,
        "pillars": {
            "structural_completeness": p1,
            "exposure_consistency":    p2,
            "property_integrity":      p3,
            "loss_history_alignment":  p4,
            "umbrella_limit_adequacy": p5,   # None when not applicable
            "narrative_quality":       p6,
        },
        "weights_used":        SPEC_PILLAR_WEIGHTS,
        "weights_version":     "spec_compliant_v2.3.0",
        "top_recommendations": _route_recommendations(top_recs, facts),
        # The Loss History plan (owner, 23 Oct 2026): every step weighed, in
        # order, with its sequential number - the screen splits its points
        # from this list (`complete_screen_shares`). None when not scored.
        "loss_plan":           _loss_plan,
        # THE HEADLINE THE PANEL COULD NEVER STATE (2026-09-23). The sum of what
        # every open gap is worth - i.e. how far this package is from 100, in
        # the same points as the score. Derived from the same effective weights
        # the score used, so `raw + points_remaining` lands on 100 by
        # construction rather than by a second calculation that can drift.
        "points_remaining": round(
            sum(r.get("points_available") or 0
                for r in top_recs if r.get("pillar") != "hard_stops_present"), 1),
        "sqs_history":         history,
        "delta_this_session":  delta,
        "routing_decision": routing_for_score(raw, len(_blockers)),
        "narrative": "",   # Filled by generate_sqs_narrative at download
        "timestamp":      timestamp,
        "model_version":  SQS_MODEL_VERSION,
        "session_id":     session_id,
        "user_id":        user_id,
        "calculation_stage": stage,
        # §6 enrichment (additive)
        "umbrella_state":        _umbrella_state,
        "loss_history_state":    _loss_history_state,
        # Client 5-bucket view (Image 28 item 3) — derived, additive.
        "loss_history_state_client":       _client_loss_state(_loss_history_state),
        "loss_history_state_client_label": CLIENT_LOSS_STATE_LABELS.get(
            _client_loss_state(_loss_history_state), "Unknown"),
        "follow_form":           _follow_form,
        "umbrella_warnings":     _umbrella_warnings,
        "review_items":          review_items,
        "evidence_labels":       _evidence_labels,
        "positive_signals":      _positive_signals,
        "category_breakdown":    _category_breakdown,
        "narrative_components":  _narrative_components,
        "loss_run_match":        _loss_run_match,
        # C3 Desired Outcome: Canonical Fact -> Validation Rule -> Pillar ->
        # Raw SQS -> Ceiling -> Displayed SQS, as data rather than as folklore.
        "score_trace":           _score_trace,
        # Why the tier is what it is - which identifiers matched, which did
        # not, and any producer-facing note (DBA, FEIN-with-different-name).
        "loss_run_match_detail": _loss_run_detail,
        # Extraction Confidence: AI fill quality metric, reported separately from SQS (client spec).
        "extraction_confidence": _extraction_confidence,
        # THE SAME PACKAGE WITHOUT ITS FORMS (13 Oct 2026, owner + Brent: the
        # SQS exists without forms and recalculates with them). Only on a score
        # that counted generated forms; None otherwise. See
        # `package_sqs_without_forms`.
        "without_forms": (_without_forms_summary(facts, flags, session_data)
                          if (form_fill and not _probe and (_form_fill_rates or mapped_data))
                          else None),
    }


# The package scorer as defined here - what its own probes call (see
# `_unify_card_points`), so a probe never runs through a caller's wrapper.
_PACKAGE_SCORER = calculate_package_sqs


# ── SPEC-COMPLIANT SQS CALCULATION (v2.1.0+) ──────────────────────────────

# ── V1 H2 (client section 7, 2026-08-27): the package score BEFORE forms ────
# The pre-form Review screen used to print `tier2_score` as "Submission
# Readiness NN%". That number is the Tier 2 completeness ratio - one CATEGORY
# of one pillar - not the SQS, and the client's complaint was exactly that the
# screen blurred the SQS, the submission status and information-gathering
# progress into one figure. From 27 Aug the screen printed only the STATUS
# LABEL of the package SQS as it stands at that moment, and the label has to
# come from the one scorer - never from a relabelled Tier 2 ratio (a 100% Tier
# 2 beside 12 warnings is "Almost There" at best, never "Submission Ready").
#
# REVERSED IN PART, 29 Sep 2026 (Orbin 22 Sep, item 2; owner-approved). The
# client: "Do not require forms to get the score." The Review screen now prints
# the NUMBER as well, labelled "so far" because it can still move at
# generation (C75 re-promotion, form fill rate). It is still this door's number
# - the real, capped package SQS - never `tier2_score`.
#
# Before generation the package is scored the way the reclassify path (§4.2
# item #5) always has: the per-form facts scorer over the RECOMMENDED forms,
# then `calculate_package_sqs`. STATELESS by design - nothing is persisted, no
# `sqs_history` entry is written and no 5.12 snapshot is taken, so the session
# list, the score-delta baseline and the E&O record are untouched. The two
# callers that DO persist - the reclassify path and, since 29 Sep, the
# pre-form case of `arq_service.recalculate_session_scores` (every pre-form
# Apply / Reopen / answer) - keep their own persist + snapshot and call this,
# so there is ONE recipe before forms exist. The recalc used to run the 3.7
# no-form path instead, and a shown number moved a point or two after an
# unrelated Apply and moved back on reload (Orbin 60 vs 61).
_PRE_GENERATION_STAGE = "initial_extract"


def _pre_generation_cross_issues(session: dict) -> List[dict]:
    """The pipeline's own cross-form issues for the recommended forms, de-
    duplicated by message, with every hard stop DEMOTED to a warning.

    C75 (owner): a form we merely SUGGESTED may not become a blocker. The
    pipeline already demotes these in `hard_stops` / `soft_stops` and on the
    structured cards before a form is selected; feeding the raw list to the
    package scorer would cap the score at 60 through `hard_cross` while the
    screen calls the same item a warning - the display/score mismatch C75
    exists to prevent. They return to full force at generation, which
    re-validates against the SELECTED ids.
    """
    seen, out = set(), []
    for issue in (session or {}).get("cross_form_issues") or []:
        if not isinstance(issue, dict):
            continue
        msg = str(issue.get("message") or "").strip()
        if not msg or msg in seen:
            continue
        seen.add(msg)
        if issue.get("type") == "hard_stop":
            issue = {**issue, "type": "soft_warning"}
        out.append(issue)
    return out


def score_package_pre_generation(
    session: dict,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    calculation_stage: str = _PRE_GENERATION_STAGE,
) -> dict:
    """Package SQS from the facts as they stand, with no generated forms.

    Pure: reads the session ROW (facts, flags, stops, recommendations,
    cross_form_issues, docs, underwriting) and returns the scorer's dict.
    Raises on scorer failure - the caller decides what a failure means
    (`current_package_sqs` turns it into None and names the session).

    `calculation_stage` only LABELS the result (and its `sqs_history` entry);
    it never moves the number. The default is the stage every pre-form
    response has always shown; the pre-form recalc passes "arq_remediated".
    """
    session = session or {}
    calculation_stage = calculation_stage or _PRE_GENERATION_STAGE
    facts = session.get("facts") or {}
    flags = session.get("flags") or {}
    form_ids = [
        r.get("form_id") for r in (session.get("recommendations") or [])
        if isinstance(r, dict) and r.get("form_id")
    ]
    # THE STOPS AS THEY STAND (6 Oct 2026, Choice Electric #18): rebuilt from
    # the stored facts by the one door, never read back from the stored
    # `hard_stops` / `soft_stops` - those are a display cache written by
    # whichever run last touched the row, and can describe facts the row no
    # longer holds. Cross-form rules are scoped to the recommended forms and
    # demoted pre-form (C75), exactly as `_pre_generation_cross_issues` did.
    from services.stops_now import stops_now
    _stops = stops_now(session, form_ids, pre_form=True, facts=facts, flags=flags)
    hard_stops = _stops["hard"]
    soft_stops = _stops["soft"]
    cross = _stops["cross_issues"]
    tier2_score, _ = check_tier2(facts, flags)
    per_form: List[dict] = []
    for fid in form_ids:
        try:
            per_form.append(calculate_sqs_from_facts(
                facts=facts, flags=flags, selected_form_ids=form_ids,
                # One form is scored with field-level stops only (spec 10).
                hard_stops=_stops["form_hard"], soft_stops=_stops["form_soft"],
                tier2_score=tier2_score, form_id=fid,
                session_id=session_id, user_id=user_id,
                calculation_stage=calculation_stage,
                session_data=session, cross_issues_full=cross,
            ))
        except Exception as ex:                                  # noqa: BLE001
            logger.warning(
                "pre-generation per-form SQS failed [session=%s form=%s]: %s",
                session_id, fid, ex,
            )
    # THE SQS WITHOUT FORMS (owner + Brent, 13 Oct 2026): Structural is the
    # 3.7 no-form formula before any form is generated - the per-form results
    # above score forms nobody has generated, so their fill rate is not the
    # submission's. They still carry the cards (one number per card).
    pkg = calculate_package_sqs(
        facts=facts, flags=flags, form_results=per_form,
        cross_issues=cross, hard_stops=hard_stops, soft_stops=soft_stops,
        session_data=session, session_id=session_id, user_id=user_id,
        calculation_stage=calculation_stage, form_fill=False,
    )
    # ...and a check whose only fix is choosing a form ("ACORD 25 is not in the
    # selected forms") is a form choice, not a gap in the submission: listed
    # for form selection, never in the number (stops_now defers it).
    choices = [i for i in cross if isinstance(i, dict) and i.get("form_choice")]
    if isinstance(pkg, dict) and choices:
        pkg["form_choices"] = [
            {"code": i.get("code"), "message": i.get("message") or "",
             "forms": list(i.get("forms") or []),
             "add_forms": list((i.get("resolution") or {}).get("add_forms") or [])}
            for i in choices]
    return pkg


def package_sqs_without_forms(session: Optional[dict],
                              session_id: Optional[str] = None,
                              user_id: Optional[str] = None) -> Optional[dict]:
    """The package score as it would read with NO forms - the pre-form recipe
    (`score_package_pre_generation`) on the same facts, nothing persisted
    (13 Oct 2026, owner + Brent: "SQS can exist without the forms; after forms
    are generated we recalculate"). Light: no per-form scoring and no card
    points, which never move the number. None when it cannot be scored."""
    session = dict(session or {})
    session["generated_forms"] = {}
    session["selected_form_ids"] = []
    try:
        facts = session.get("facts") or {}
        flags = session.get("flags") or {}
        from services.stops_now import stops_now
        st = stops_now(session, None, pre_form=True, facts=facts, flags=flags)
        # The scorer as defined, never the public name: like a probe, this is
        # part of ONE scoring, so a caller's spy or stub sees one call.
        return _PACKAGE_SCORER(
            facts=facts, flags=flags, form_results=[],
            cross_issues=st["cross_issues"], hard_stops=st["hard"], soft_stops=st["soft"],
            session_data=session, session_id=session_id, user_id=user_id,
            calculation_stage=_PRE_GENERATION_STAGE, _probe=True, form_fill=False,
        )
    except Exception as ex:                                      # noqa: BLE001
        logger.warning("package score without forms skipped [session=%s]: %s", session_id, ex)
        return None


def _without_forms_summary(facts: dict, flags: dict, session_data: Optional[dict]) -> Optional[dict]:
    """{score, raw, tier, cap} of `package_sqs_without_forms` on these facts -
    what a post-generation score prints beside itself ("Without forms 100 ·
    With forms 97")."""
    if not isinstance(session_data, dict):
        return None
    pkg = package_sqs_without_forms({**session_data, "facts": facts, "flags": flags})
    if not isinstance(pkg, dict):
        return None
    return {"score": pkg.get("package_sqs_score"), "raw": pkg.get("raw_sqs_score"),
            "tier": pkg.get("tier"), "cap": pkg.get("cap_applied")}


def is_pre_form_session(session: Optional[dict]) -> bool:
    """True for the pre-form Review screen: no form generated AND none selected.

    The one predicate for "the package is scored by `score_package_pre_generation`
    and the Review card prints that number". The Clarity / Lite path (selected
    ids, no generated forms) is NOT this - it keeps its own recipe and its own
    screen - and neither is anything after generation, where the persisted,
    credit-bearing `package_sqs` is the score. A row that is not a dict is
    not known to be pre-form, so nothing pre-form-only is done for it.
    """
    if not isinstance(session, dict):
        return False
    return not session.get("generated_forms") and not session.get("selected_form_ids")


def current_package_sqs(
    session: dict,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Optional[dict]:
    """The package SQS as it stands RIGHT NOW - the one door for every
    pre-form response. The Review screen prints its NUMBER, labelled "so far"
    (29 Sep 2026, Orbin item 2), and its tier.

    * Forms generated -> the persisted `package_sqs`. Every post-generation
      path (generate, edit, ARQ recalc, dismiss credit) maintains that key and
      applies credits to it; recomputing here would drop the credits and be a
      second score (D33).
    * Integrity review pending -> None. Same withholding as `tier2_score`:
      nothing derived from a possibly-mixed package is shown.
    * Otherwise -> a fresh, unpersisted pre-generation score. A pre-form
      recalc persists this same recipe (`score_package_pre_generation`), so
      the number a Resolve reports is the number a reload recomputes. No
      dismissal credit is applied before forms exist: the cards that earn
      one are shown only in the editor, and the first post-generation
      recalculation or edit re-applies any credit still outstanding.
    * Scorer failure -> None, and the log NAMES the session (H1-G: the only
      evidence of a vanished score is this line). The screen shows no score
      rather than a stale or invented one.
    """
    session = session or {}
    if session.get("generated_forms"):
        stored = session.get("package_sqs")
        return with_current_bucket_labels(stored) if isinstance(stored, dict) and stored else None
    if (session.get("integrity") or {}).get("review_required"):
        return None
    try:
        return score_package_pre_generation(session, session_id, user_id)
    except Exception as ex:                                      # noqa: BLE001
        logger.error(
            "pre-generation package SQS failed [session=%s]: %s",
            session_id, ex, exc_info=True,
        )
        return None


def calculate_package_sqs_spec_compliant(
    facts: dict,
    flags: dict,
    form_results: List[dict],
    cross_issues: List[dict],
    hard_stops: List[str],
    soft_stops: List[str],
    session_data: dict,
    mapped_data: Optional[dict] = None,
    confidence_dict: Optional[dict] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    calculation_stage: str = "initial_extract",
) -> dict:
    """
    Calculate package-level SQS using SPEC-COMPLIANT weights (Decision Tree v2.1.0+).
    Pillars: structural_completeness (25%) + exposure_consistency (25%) + property_integrity (15%) +
             loss_history_alignment (15%) + umbrella_limit_adequacy (10%) + narrative_quality (10%)

    NOTE: `calculate_package_sqs` is the live package scorer wired into the routes.
    This variant is retained for backwards-compatible imports only; keep its pillar
    handling (None umbrella, narrative tuple) in sync if it is ever re-wired.
    """
    _present_types = _present_doc_types(session_data)
    _has_narrative = "narrative" in _present_types
    from services.loss_history_state import package_has_loss_runs
    _has_loss_run  = package_has_loss_runs((session_data or {}).get("docs"), facts)

    lob = infer_lob(facts, flags)

    # P1: Structural Completeness (ACORD 125 + required forms)
    tier1_ok, tier1_missing = check_tier1(facts, flags)
    tier2_score, tier2_missing = check_tier2(facts, flags)
    conf_rate = confidence_fill_rate(mapped_data or {}, confidence_dict or {})
    # C3 3.2 40/35/25: Core Application / Underwriting Profile / Form Fill Rate.
    # Reads the same three constants as calculate_package_sqs - this function is
    # retained for imports only (see tests/test_sqs_scoring_fixes_20260816.py),
    # and a second hand-typed copy of the blend is exactly how the two would
    # drift the day someone did start calling it again.
    p1 = int((
        (100 if tier1_ok else max(0, 100 - len(tier1_missing) * 20)) * _W_TIER1 +
        tier2_score * _W_TIER2 +
        conf_rate * _W_FILL
    ))

    # P2: Exposure Consistency (class codes, payroll alignment)
    lob_rules = LOB_RULES.get(lob, LOB_RULES["generic"])
    req_present = sum(1 for f in lob_rules["required"] if _fv(facts, f))
    req_total = len(lob_rules["required"])
    lob_score = int((req_present / req_total) * 100) if req_total else 100
    p2 = lob_score

    # P3: Property Integrity (COPE completeness)
    p3 = _calculate_cope_score(facts, flags)

    # P4: Loss History Alignment
    p4, _ = calculate_p4_loss_history(facts, flags, has_loss_run_doc=_has_loss_run)

    # P5: Umbrella & Limit Adequacy (None = N/A - excluded + weights re-normalised).
    p5 = _calculate_umbrella_adequacy(facts, flags)

    # P6: Narrative Quality (returns (score, components) - unpack the score).
    _spec_session_docs = (session_data or {}).get("docs") or []
    p6, _, _ = _calculate_narrative_quality(
        facts, has_narrative_doc=_has_narrative, flags=flags,
        narrative_doc_text=_extract_narrative_doc_text(_spec_session_docs),
        form_ids=session_form_ids(session_data, form_results),
    )

    # Weighted score with the generic N/A rescaling (client C2 2.2): any None
    # pillar (umbrella without an umbrella, loss history for a verified new
    # venture) drops out and the remaining original weights rescale.
    raw = _weighted_pillar_sum(
        {
            "structural_completeness": p1,
            "exposure_consistency":    p2,
            "property_integrity":      p3,
            "loss_history_alignment":  p4,
            "umbrella_limit_adequacy": p5,
            "narrative_quality":       p6,
        },
        SPEC_PILLAR_WEIGHTS,
    )

    # Hard/soft stop penalties. Uses the SHARED cap resolver and tier ladder so
    # this retained-for-imports variant cannot drift from the live scorer - it
    # previously carried its own copy of both, including a tier ladder that
    # returned "Submission Ready" at exactly 90 where the live scorer requires
    # ABOVE 90 (2026-08-16 audit).
    hard_cross = [i for i in cross_issues if i.get("type") == "hard_stop"]
    raw_uncapped = max(0, min(100, raw))
    cap_applied, cap_reason = _resolve_cap(
        hard_stops, soft_stops,
        hard_cross=[i.get("message") for i in hard_cross if isinstance(i, dict)],
    )
    raw = raw_uncapped if cap_applied is None else min(raw_uncapped, cap_applied)
    raw = max(0, raw)
    _open = len([m for m in (hard_stops or []) if m]) + len(hard_cross)
    tier = tier_for_score(raw, _open)[1]

    # SQS history - copy the list so we don't mutate the caller's session_data
    # by reference (concurrent callers would otherwise share the same list).
    history = list(session_data.get("sqs_history", []))
    timestamp = datetime.utcnow().isoformat() + "Z"
    new_entry = {
        "at": timestamp,
        "score": raw,
        "stage": calculation_stage,
        "model_version": SQS_MODEL_VERSION,
        "weights_version": "spec_compliant_v2.1.0"
    }
    # Dedup: skip if the last entry has the same stage AND same score (prevents
    # idempotent re-calls from polluting history).
    if not history or (history[-1].get("score") != raw or history[-1].get("stage") != calculation_stage):
        history.append(new_entry)

    # Delta - prefer the genuine initial_extract baseline.
    _baseline = next(
        (h for h in history if h.get("stage") == "initial_extract"),
        history[0] if history else None,
    )
    delta = (raw - _baseline["score"]) if (_baseline and len(history) > 1) else 0
    all_recs = list(tier1_missing) + list(tier2_missing)[:3]

    # §6.5 umbrella enrichment - emitted via the SAME shared helpers as the live
    # scorer so this variant never silently drops the coverage-gap signals if it is
    # ever re-wired into a route (audit finding: spec-compliant divergence).
    _umbrella_state    = _get_umbrella_state(facts, flags)
    _follow_form       = _get_follow_form_status(facts)
    _umbrella_warnings = _build_umbrella_warnings(facts, flags, p5)
    _review_items      = _build_umbrella_review_items(flags, _follow_form, p5, facts)

    return {
        "package_sqs_score": raw,
        "package_sqs_score_spec_compliant": raw,
        "tier": tier,
        "lob": lob,
        "pillars": {
            "structural_completeness": p1,
            "exposure_consistency": p2,
            "property_integrity": p3,
            "loss_history_alignment": p4,
            "umbrella_limit_adequacy": p5,
            "narrative_quality": p6,
        },
        "weights_used": SPEC_PILLAR_WEIGHTS,
        "weights_version": "spec_compliant_v2.1.0",
        "top_recommendations": _route_recommendations(all_recs, facts),
        "sqs_history": history,
        "delta_this_session": delta,
        "routing_decision": routing_for_score(raw, _open),
        "timestamp": timestamp,
        "model_version": SQS_MODEL_VERSION,
        "session_id": session_id,
        "user_id": user_id,
        "calculation_stage": calculation_stage,
        # §6.5 enrichment (parity with calculate_package_sqs via shared helpers)
        "umbrella_state":    _umbrella_state,
        "follow_form":       _follow_form,
        "umbrella_warnings": _umbrella_warnings,
        "review_items":      _review_items,
    }


# ── Recommendation impact estimation ──────────────────────────────────────────

def _estimate_score_impact(
    field: str,
    component: str,
    current_breakdown: dict,
    weights: dict
) -> int:
    """Estimate SQS gain if field were filled."""
    # Simplified heuristic: tier-1 fields worth more
    tier1_fields = set(TIER1_FIELDS.keys())
    tier2_fields = set(TIER2_FIELDS.keys())
    
    if field in tier1_fields:
        base_impact = 15
    elif field in tier2_fields:
        base_impact = 8
    else:
        base_impact = 5
    
    # Weight by component importance
    component_weight = weights.get(component, 0.10)
    return int(base_impact * (component_weight / 0.25))


# ── Per-form SQS (enhanced with metadata) ─────────────────────────────────────

def _loss_rec_id(message: str) -> str:
    """Stable identity for a loss-history recommendation row.

    Derived from the message TEMPLATE (digits stripped, so a varying age like
    "372 days old" cannot fork the id) - never from the recommendation's
    position in the list. Positional ids (`rec_loss_3`) made the identical
    warning, emitted by two forms' scorers at different list indexes, insert
    twice into sqs_recommendation_audit (its dedupe is ON CONFLICT
    (session_id, rec_id)), and let a dismissed row resurface when a
    recalculation renumbered it - the same throwaway-index defect as the
    2026-08-08 legacy_soft_* fix. Display/audit identity only; no effect on
    any score.
    """
    slug = re.sub(r"\d+", "", (message or "").lower())
    slug = re.sub(r"[^a-z]+", "_", slug).strip("_")
    return f"rec_loss_{slug[:60]}"


# Bound on how many counterfactual scorer runs one form may make. Each is pure
# Python with no I/O, but a schedule-heavy form can raise dozens of cards and an
# unbounded loop is how a cheap correctness win becomes a latency complaint.
# Distinct FIELDS are simulated, not cards, so several cards naming one field
# cost one run. 40 covers every real form measured.
_MAX_IMPACT_SIMULATIONS = 40

# The value a field is filled with to ask "what if this were answered?".
# Deliberately "Yes": it satisfies both a plain presence test (`bool(_fv(...))`,
# which is what nearly every pillar check does) and `_attested_true`, which is
# what the loss-history pillar needs. A field wanting a NUMBER will show no gain
# from it - handled by falling back, never by inventing or deleting a number.
_IMPACT_PROBE_VALUE = "Yes"

# Fields where the probe IS the answer the card asks for, so a flat or falling
# measurement is the truth rather than a probe of the wrong shape (29 Sep 2026).
# "Yes" on the no-loss indicator is an attestation (`attested_true("Yes")`), and
# an attestation now takes Loss History OUT of the score: the remaining pillars
# rescale, so on a package whose other pillars average below the loss pillar's
# current score, attesting cannot raise the number - it can lower it. The
# fallback below would have kept the card's typed +8 and promised points that
# attesting no longer earns.
_IMPACT_PROBE_IS_THE_ANSWER = frozenset({"loss_history_no_prior_losses_indicator"})


def _pillar_headroom(component: str, breakdown: dict, weights: dict) -> float:
    """The most this pillar can still add to the total score, in real points."""
    current = (breakdown or {}).get(component)
    weight  = (weights or {}).get(component)
    if current is None or weight is None:
        return 0.0
    return max(0.0, (100.0 - float(current)) * float(weight))


def _measure_recommendation_impacts(
    recommendations: List[dict],
    baseline: Optional[int],
    breakdown: dict,
    weights: dict,
    rescore,
    facts: dict,
    measured_out: Optional[dict] = None,
) -> dict:
    """{id(rec): (points, is_exact)} - what each card is really worth.

    MEASURED, NOT DECLARED. Every `score_impact` in this module is a literal a
    developer typed, and the loss cards all share one (8) regardless of where the
    pillar currently sits - so the same card is worth +2.25 from the
    narrative-stated state and +5.25 from no-information and promised 8 in both.
    The client reconciled that against the published formula on 2026-08-17 and
    was right. The fix is not a better literal; it is to stop declaring and start
    asking. This scorer is pure - no I/O, no DB - so it can answer its own
    counterfactual, which keeps the number correct when a pillar's numbers change
    and for cards that do not exist yet.

    The delta is taken against the UNCAPPED baseline, because the owner's
    standing rule is that a gain adds to the raw score and a cap limits only what
    is DISPLAYED.

    Three deliberate refusals:

    * **Never delete a card's value.** A simulation showing no movement falls
      back to the declared literal (bounded, below). The probe value cannot
      satisfy a field that wants a number, and zeroing a real card because our
      probe was the wrong shape would be worse than the imprecision being fixed.
      The one exception is a field in `_IMPACT_PROBE_IS_THE_ANSWER`, where the
      probe is exactly the answer the card asks for: there a flat or falling
      measurement is reported as 0, exactly (29 Sep 2026).
    * **Never promise more than exists.** Measured or fallback, the number is
      capped at the pillar's remaining headroom, so no card can offer points the
      pillar has already earned.
    * **Never let this break scoring.** Every simulation is wrapped; a failure
      leaves that card exactly as it is today.

    `is_exact` tells the UI whether it may drop the "up to" hedge. True only when
    the number came from a measurement.

    `measured_out`, when given, receives {field: gain} for every field this
    call simulated (None = could not tell). `calculate_package_sqs` reads it
    to tell "the probe moved this form" from "the probe is the wrong shape"
    (1 Oct 2026, item 19).
    """
    out: dict = {}
    if baseline is None:
        return out

    measured_by_field: dict = {}
    simulations = 0

    for rec in recommendations:
        field     = rec.get("field")
        component = rec.get("component")
        declared  = rec.get("score_impact")

        if not isinstance(declared, (int, float)) or isinstance(declared, bool):
            continue

        # A card the scorer has already declared UNSCORED is worth zero, exactly,
        # and no fallback may raise it. The three refusals below are built around
        # "a simulation showing no movement might mean our probe was the wrong
        # shape" - true in general, and wrong here, because the emitter knows the
        # check was excluded from the pillar in the first place.
        if rec.get("unscored"):
            out[id(rec)] = (0, True)
            continue

        # A card with no single answerable field cannot be simulated - nothing to
        # fill - but it must STILL be bounded. Measured on a live session
        # 2026-08-17: once the producer attested, the follow-up card ("attach
        # loss runs to fully confirm") kept its typed 8 while the pillar sat at
        # 60 with only 6 points left to give. A card that needs a DOCUMENT is
        # exactly the kind most likely to overstate itself, because the literal
        # was written for the empty case.
        if not field:
            _hr = _pillar_headroom(component, breakdown, weights)
            if declared > 0 and _hr > 0:
                out[id(rec)] = (int(round(min(float(declared), _hr))), False)
            elif declared > 0:
                out[id(rec)] = (0, True)
            continue

        if field in measured_by_field:
            gain = measured_by_field[field]
        elif simulations >= _MAX_IMPACT_SIMULATIONS:
            gain = None
        else:
            simulations += 1
            try:
                probed = dict(facts or {})
                probed[field] = _IMPACT_PROBE_VALUE
                after = rescore(probed)
                gain  = None if after is None else float(after) - float(baseline)
            except Exception as ex:                        # pragma: no cover
                logger.debug("impact simulation failed for %s: %s", field, ex)
                gain = None
            measured_by_field[field] = gain

        headroom = _pillar_headroom(component, breakdown, weights)

        if gain is not None and gain > 0:
            points = min(gain, headroom) if headroom > 0 else gain
            out[id(rec)] = (int(round(points)), True)
        elif gain is not None and field in _IMPACT_PROBE_IS_THE_ANSWER:
            # Measured, and the measurement is the answer: exactly zero, never
            # the typed literal. See `_IMPACT_PROBE_IS_THE_ANSWER`.
            out[id(rec)] = (0, True)
        elif declared > 0 and headroom > 0:
            out[id(rec)] = (int(round(min(float(declared), headroom))), False)
        elif declared > 0:
            # The pillar is already full: this card cannot move the score, even
            # though it is still worth asking for. Saying so is the honest answer.
            out[id(rec)] = (0, True)

    if measured_out is not None:
        measured_out.update(measured_by_field)
    return out


# ── ONE NUMBER PER CARD (1 Oct 2026, Orbin 22 Sep item 19) ──────────────────
# A card several forms show carried each FORM's measured gain: the Orbin loss
# card read +6 / +7 / +8 / +10 depending on the form, and the Best Solutions row
# for its pillar read +11.2 - while answering it moved the package, the score
# the panel headline and every cover print, by +7. A card now says one thing
# everywhere: what answering it does to the PACKAGE score, found the way
# `_measure_recommendation_impacts` finds a form's - by asking the scorer.
#
# The probe is an answer a person could really give. "Yes" cannot answer a
# percentage, an amount or a date, so a typed field is probed with the first of
# `_PROBE_ANSWERS` its own registry validator accepts. Only then is a flat
# measurement the truth (a card for a fact no score reads is worth nothing, and
# says so). A table, a narrative - scored on what it SAYS - or a field whose
# validator takes none of them cannot be stood in for, so a flat measurement
# there keeps the bounded fallback ("up to"), as on a form.
_PROBE_ANSWERS = ("Yes", "50", "100000", "123456789", "Answered by the producer.",
                  "01/01/2030",
                  # A year and a class (15 Oct 2026): year built, roof year and
                  # protection class took none of the above, so their rows could
                  # never be measured - only bounded. Last, so no field that
                  # accepted an earlier answer is probed differently.
                  "2015", "3")
_CONTENT_SCORED_COMPONENTS = frozenset({"narrative_quality"})
_MAX_PACKAGE_PROBES = 40
import contextvars as _contextvars  # noqa: E402
# Set while the review screen measures where answering EVERYTHING lands
# (`form_routes._pre_form_status`, 15 Oct 2026): that one rescore needs the
# score only, never another share-out.
SKIP_SHARE_OUT = _contextvars.ContextVar("sqs_skip_share_out", default=False)
# Limits the scorer compares with a threshold are probed AT that threshold (15
# Oct 2026): the first value their check accepts ("50") is below every one, so a
# row for a MISSING limit swapped "missing" for "below the minimum" and measured
# nothing; and the free-text employers liability limit has no check at all, so
# its "Yes" probe stated no amount. The values are the scorer's own constants.
_THRESHOLD_PROBE_FACTS = {
    "gl_each_occurrence": _UMB_GL_OCC_MIN,
    "gl_aggregate": _UMB_GL_AGG_MIN,
    "auto_liability_limit": _UMB_AUTO_CSL_MIN,
    "employers_liability_limits": _UMB_EL_FULL,
}


def _package_probe_answer(field: str, stated: bool = False) -> Tuple[str, bool]:
    """(the value a package probe fills `field` with, whether a person could
    really answer the field with it). `stated`: the package already holds a
    value for it - a limit is then probed with the ordinary answer, never raised
    to the threshold (a TRUE limit below the minimum is a coverage finding, and
    a row must not promise points for typing a bigger one)."""
    try:
        from services.answer_routing import MODE_FIELD, answer_mode
        if (answer_mode(field) or {}).get("mode") != MODE_FIELD:
            return _IMPACT_PROBE_VALUE, False
    except Exception:                                      # noqa: BLE001
        return _IMPACT_PROBE_VALUE, False
    try:
        from services.fact_registry import FACT_REGISTRY, answer_check
        validate = answer_check(FACT_REGISTRY.get(field))
    except Exception:                                      # noqa: BLE001
        validate = None
    # A question with a choice list is probed with a CHOICE (13 Oct 2026): a
    # radius of operation answered "Yes" states no radius, so the row read
    # "adds nothing" and was never listed - though "Local (up to 50 miles)"
    # closes it.
    try:
        from services.answer_options import OTHER, options_for
        for option in options_for(field) or []:
            if option == OTHER:
                continue
            try:
                if not callable(validate) or validate(option):
                    return option, True
            except Exception:                              # noqa: BLE001
                continue
    except Exception:                                      # noqa: BLE001
        pass
    if field in _THRESHOLD_PROBE_FACTS and not stated:
        return str(int(_THRESHOLD_PROBE_FACTS[field])), True
    if not callable(validate):
        return _IMPACT_PROBE_VALUE, True
    for answer in _PROBE_ANSWERS:
        try:
            if validate(answer):
                return answer, True
        except Exception:                                  # noqa: BLE001
            continue
    return _IMPACT_PROBE_VALUE, False


def _card_points(gain: Optional[float], valid: bool, declared: Optional[float],
                 headroom: Optional[float], raw_uncapped: int,
                 cap_applied: Optional[int]) -> Optional[Tuple[int, bool]]:
    """(points, is_exact) for one card on the package, or None to leave it.

    The refusals of a form's card (`_measure_recommendation_impacts`): a flat
    probe of the wrong shape never zeroes a card, a FALLBACK never offers more
    than its pillar has left, and a measured gain is exact only when no ceiling
    holds part of it back from the score on screen. A measured gain is not cut
    to one pillar's headroom: it is what the package score really does, and an
    answer can move more than one pillar (an attestation that takes Loss
    History out re-weights all the others)."""
    if gain is not None and gain > 0:
        points = int(round(gain))
        exact = cap_applied is None or raw_uncapped + points <= cap_applied
        return points, bool(exact)
    if gain is not None and valid:
        return 0, True
    if not isinstance(declared, (int, float)) or isinstance(declared, bool):
        return None
    if declared <= 0 or (headroom is not None and headroom <= 0):
        return 0, True
    bound = float(declared) if headroom is None else min(float(declared), headroom)
    return int(round(bound)), False


def screen_fields(facts: dict, flags: dict, hard_stops, soft_stops, cross_issues,
                  with_key_details: bool = True) -> List[str]:
    """Every fact an item on the pre-form review screen asks for, in the order
    the screen shows them - hard stops, warnings, key details (15 Oct 2026, owner:
    "every score adds up to 100, not more and not less"). Each card's typed
    facts come from its own fix window (`issue_registry.resolution_for`), a key
    detail's from its own (`_key_detail_actions`, "whichever applies" - its first
    box). They join the share-out so every number on the screen is a share of
    one total."""
    out: List[str] = []

    def _add(res) -> None:
        if isinstance(res, dict) and res.get("mode") == "field":
            for f in res.get("facts") or []:
                if f and str(f) not in out:
                    out.append(str(f))
    try:
        from services.issue_registry import classify_legacy, resolution_for
    except Exception:                                          # noqa: BLE001
        return out
    for sev, stops, kind in (("hard_stop", hard_stops, "hard_stop"), ("soft_warning", soft_stops, "soft_warning")):
        for msg in stops or []:
            try:
                _add(resolution_for(classify_legacy(str(msg), sev)[0]))
            except Exception:                                  # noqa: BLE001
                continue
        for issue in cross_issues or []:
            if isinstance(issue, dict) and issue.get("type") == kind and not issue.get("form_choice"):
                try:
                    _add(resolution_for(issue.get("code")))
                except Exception:                              # noqa: BLE001
                    continue
    if not with_key_details:
        return out
    try:
        for item in _key_detail_actions(facts or {}, flags or {}):
            res = item.get("resolution") or {}
            if res.get("mode") == "field" and res.get("facts"):
                f = str(res["facts"][0])
                if f not in out:
                    out.append(f)
    except Exception:                                          # noqa: BLE001
        pass
    return out


def complete_screen_shares(row: dict, session_id: str, user_id: str,
                           pkg: Optional[dict], kd: Optional[dict],
                           credit_rows: Optional[List[dict]] = None) -> Tuple[Optional[dict], Optional[dict]]:
    """The review page's numbers (`_complete_screen_shares_plan`), plus the
    years the included loss runs cover as `loss_coverage` (display only, 24 Oct
    2026 - `loss_history_state.loss_run_coverage`; left out with no loss runs).
    `credit_rows`: after forms, the dismissal rows behind the stored score's
    credits (the plan retires each one where its field is answered)."""
    pkg, kd = _complete_screen_shares_plan(row, session_id, user_id, pkg, kd, credit_rows)
    try:
        if isinstance(pkg, dict) and isinstance(row, dict):
            from services.loss_history_state import loss_run_coverage
            cov = loss_run_coverage(row.get("docs") or [], row.get("facts") or {})
            if cov:   # absent with no loss runs - the screen reads a missing key as none
                pkg = dict(pkg)
                pkg["loss_coverage"] = cov
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("loss-run coverage not read: %s", exc)
    return pkg, kd


def _complete_screen_shares_plan(row: dict, session_id: str, user_id: str,
                                 pkg: Optional[dict], kd: Optional[dict],
                                 credit_rows: Optional[List[dict]] = None) -> Tuple[Optional[dict], Optional[dict]]:
    """THE REVIEW PAGE'S NUMBERS, FROM ITS ONE ORDERED PLAN (owner, 24 Oct 2026).

    Every item the pre-form page offers - the key details, a file to mark, a
    Data Consistency pick, the hard stops, the warnings, the Recommendations
    rows, the upload row - in rail order, each worth what the package score
    gains when it is done after every item above it (`services.review_plan`,
    simulated with the stops as they would stand and the scorer itself). The
    numbers add up to exactly 100 minus the score; a hold's withheld points
    show on the hold; a fix offered twice counts at its first place.

    Written for every surface the page reads: `review_plan` (the items, by id -
    the page reads its numbers from here), and for older readers the same
    numbers as `screen_shares` / `screen_card_points` / `screen_dc_points` /
    `screen_unanswerable`, each row's `answer_gain` and each key detail's
    `points`. Never raises.

    AFTER FORMS TOO (owner, 29 Oct 2026, Orbin 432c8594: 79 after forms with
    the side panel's rows at +2 +1 +1 +2 +6 +3 = 94 - six points on no item,
    while the same facts before forms listed ten items adding to exactly 100).
    Once forms exist the plan is weighed with the post-generation stops (the
    selected + generated forms, `stops_now(pre_form=False)`) and the stored,
    credit-bearing score (`credit_rows`), and its items are the ones the editor's
    side panel lists (`after_forms` on the plan)."""
    try:
        if not isinstance(pkg, dict) or not isinstance(row, dict):
            return pkg, kd
        # Only a scored package has a plan (a payload with no pillars passes through).
        if pkg.get("package_sqs_score") is None or pkg.get("raw_sqs_score") is None \
                or not pkg.get("pillars"):
            return pkg, kd
        from services.review_plan import build_review_plan
        _after = bool(row.get("generated_forms"))
        grouped = review_page_grouped_view(row, pkg, after_forms=_after)
        _cr = credit_rows if _after else None
        plan = build_review_plan(row, pkg, kd, grouped, _cr, declare_alone=False)
        # Same-pillar rows each under a point are one row; the plan is weighed
        # again on it so its number is what doing them together moves.
        # Rows that must be answered together (an answer raising a check another
        # row answers) are ONE row first; the plan is weighed again on it.
        from services.review_plan import join_codependent_rows
        try:
            _joined = join_codependent_rows(pkg, plan)
            if _joined is not None:
                _plan_j = build_review_plan(row, _joined, kd, grouped, _cr, declare_alone=False)
                if _plan_j:
                    pkg, plan = _joined, _plan_j
        except Exception as _jx:                               # noqa: BLE001
            logger.debug("co-dependent rows not joined: %s", _jx)
        from services.review_plan import merge_subpoint_rows, saved_merged_groups
        try:
            from services.issue_fix_undo import load_receipts
            _saved = saved_merged_groups(load_receipts(row or {}).keys())
        except Exception:                                      # noqa: BLE001
            _saved = {}
        merged = merge_subpoint_rows(pkg, plan, _saved)
        if merged is not None:
            plan2 = build_review_plan(row, merged, kd, grouped, _cr, declare_alone=False)
            if plan2:
                pkg, plan = merged, plan2
        if not plan:
            return pkg, kd
        # The final plan: what each item raises in any order (names only).
        from services.review_plan import declare_follow_ups
        plan = declare_follow_ups(row, plan)
        return apply_review_plan(pkg, kd, plan)
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("screen shares not completed: %s", exc)
        return pkg, kd


def review_page_grouped_view(row: dict, pkg: Optional[dict],
                             after_forms: bool = False) -> Optional[dict]:
    """The hard-stop and warning cards the pre-form review page draws, from the
    stops AS THEY STAND (`stops_now`) - the view every pre-form route returns
    (`issue_registry.grouped_with_package_caps`). `after_forms` (29 Oct 2026):
    the cards as they stand once forms exist - the post-generation stops,
    scoped to the selected + generated forms (the review plan after forms)."""
    try:
        from services.issue_registry import grouped_with_package_caps
        from services.stops_now import stops_now
        from services.issue_registry import refresh_requested_coverage_notes
        st = stops_now(row, pre_form=not after_forms)
        # The information notes are redrawn from the stored assessment (item 3).
        _structured = refresh_requested_coverage_notes(
            row.get("structured_issues") or [], row.get("underwriting_consistency"))
        from services.issue_registry import structured_as_they_stand
        _structured = structured_as_they_stand(_structured, row, st.get("hard"), st.get("soft"),
                                               st.get("cross_issues"))
        return grouped_with_package_caps(
            _structured, st.get("hard") or [], st.get("soft") or [],
            pkg, cross_issues=st.get("cross_issues") or [], facts=row.get("facts") or {},
            pre_form=not after_forms)
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("review page cards not read: %s", exc)
        return None


def apply_review_plan(pkg: dict, kd: Optional[dict], plan: dict) -> Tuple[dict, Optional[dict]]:
    """The plan's numbers on every surface that prints one (see
    `complete_screen_shares`)."""
    if isinstance(plan, dict) and "_ctx" in plan:
        plan = {k: v for k, v in plan.items() if k != "_ctx"}
    items = [i for i in (plan.get("items") or []) if isinstance(i, dict)]
    pkg = dict(pkg)
    pkg["review_plan"] = plan
    shares: Dict[str, List] = {}
    card_points: Dict[str, List] = {}
    dc_points: Dict[str, List] = {}
    unanswerable: List[dict] = []
    by_row: Dict[int, dict] = {}
    by_label: Dict[str, dict] = {}
    for it in items:
        pts, exact = int(it.get("points") or 0), bool(it.get("exact", True))
        if it.get("kind") == "rec":
            by_row[int(it.get("row_index", -1))] = it
            if it.get("field"):
                shares.setdefault(str(it["field"]), [pts, exact, pts])
        elif it.get("kind") == "detail":
            by_label[str(it.get("label"))] = it
            facts_ = [f for f in ((it.get("keys") or [])) if str(f).startswith("fact:")]
            if facts_:
                shares.setdefault(str(facts_[0])[5:], [pts, exact, pts])
        elif it.get("kind") == "card" and it.get("code"):
            # One code can draw several cards (`review_plan.page_items`): the
            # code's entry is their sum (what the code's cards add together);
            # the page reads each card by its plan item (`issue_id`).
            _prev = card_points.get(str(it["code"]))
            card_points[str(it["code"])] = ([_prev[0] + pts, bool(_prev[1]) and exact]
                                            if _prev else [pts, exact])
        elif it.get("kind") == "dc" and it.get("fact"):
            dc_points[str(it["fact"])] = [pts, False]
        elif it.get("kind") == "doc" and (pts > 0 or it.get("under") or it.get("hold")):
            # (P1: a document step whole points cannot reach is listed "under 1 pt".)
            doc = {"label": str(it.get("label") or ""), "points": pts, "action": "add_documents",
                   "title": "Loss History", "plan_order": it.get("plan_order"),
                   "plan_id": it.get("id"), "step": it.get("step"),
                   "under": bool(it.get("under")) and pts <= 0, "with_others": it.get("with_others"),
                   "hold": it.get("hold")}
            for extra in ("doc_id", "filename"):
                if it.get(extra):
                    doc[extra] = it[extra]
            unanswerable.append(doc)
    if int(plan.get("left") or 0) > 0:
        unanswerable.append({"label": "Points no item on this page can add yet",
                             "points": int(plan["left"])})
    pkg["screen_shares"] = shares
    pkg["screen_card_points"] = card_points
    pkg["screen_dc_points"] = dc_points
    pkg["screen_unanswerable"] = unanswerable
    pkg["screen_total"] = int(plan.get("total") or 0)
    # The real score beside the shown one while a cap holds (R5, 30 Oct 2026).
    if plan.get("real") is not None:
        pkg["real_sqs_score"] = int(plan["real"])
    out_rows = []
    for n, r in enumerate(pkg.get("top_recommendations") or []):
        it = by_row.get(n)
        if isinstance(r, dict) and it is not None:
            pts = int(it.get("points") or 0)
            r = dict(r, answer_gain=pts, answer_gain_is_exact=bool(it.get("exact", True)),
                     answer_gain_share=True, answer_gain_alone=pts, plan_id=it.get("id"),
                     answer_gain_under=bool(it.get("under")),
                     answer_gain_held_by=it.get("held_by"),
                     # A cap-only row (R5): no points, "Holds the score at 85 until fixed".
                     answer_gain_hold=it.get("hold"),
                     # Answered by an item above it on the page (named, never "No effect").
                     answer_gain_covered_by=it.get("covered_by"),
                     # Cap shares (`review_plan._share_group_releases`).
                     answer_gain_with_others=it.get("with_others"),
                     answer_gain_score_item=it.get("score_item", True),
                     # Offered first by an earlier item (a card, a key detail):
                     # that item's number, never added twice.
                     answer_gain_mirror_of=it.get("mirror_of"),
                     answer_gain_mirror=int(it.get("mirror") or 0),
                     # What answering it raises next, and a dip it causes first
                     # (rule G2 / G13: named on the row, never a surprise).
                     answer_gain_leads_to=list(it.get("leads_to") or [])[:3],
                     answer_gain_cost=int(it.get("cost") or 0))
        out_rows.append(r)
    pkg["top_recommendations"] = out_rows
    if isinstance(kd, dict) and isinstance(kd.get("missing_items"), list):
        kd = dict(kd)
        out_items = []
        for it in kd["missing_items"]:
            p = by_label.get(str((it or {}).get("label")))
            if isinstance(it, dict) and p is not None:
                it = dict(it, points=int(p.get("points") or 0), points_exact=bool(p.get("exact", True)),
                          points_under=bool(p.get("under")), points_held_by=p.get("held_by"),
                          points_with_others=p.get("with_others"),
                          plan_id=p.get("id"))
            out_items.append(it)
        kd["missing_items"] = out_items
    return pkg, kd

def _pillar_remaining_points(pillar_scores: Dict[str, Optional[float]], pillar: str,
                            raw_now: Optional[int]) -> Optional[int]:
    """What the package score gains when `pillar` reaches 100 (23 Oct 2026, live
    fc04c74f: at 98 with only the narrative left the row read "up to +1" while
    answering both topics made 100). The pillar's shortfall in package points,
    rounded the way the score rounds - the scorer's own `_weighted_pillar_sum`
    with that pillar at 100 - never past 100. None when the pillar is N/A."""
    if raw_now is None or not isinstance(pillar_scores, dict) or pillar_scores.get(pillar) is None:
        return None
    full = _weighted_pillar_sum({**pillar_scores, pillar: 100.0}, SPEC_PILLAR_WEIGHTS)
    return max(0, min(100, int(full)) - int(raw_now))


def _unify_card_points(form_results, top_recs, facts: dict, raw_uncapped: int,
                       cap_applied: Optional[int], headroom_for, rescore,
                       screen: Optional[List[str]] = None,
                       pillar_remaining=None,
                       probe_values: Optional[Dict[str, str]] = None) -> Optional[Dict[str, List]]:
    """Write ONE package-measured number onto every copy of every card in
    `form_results` (in place - the per-form results are what every caller
    persists and every surface reads), and on each Best Solutions row the gain
    of the answer it asks for (`answer_gain`). See the block above.

    `probe_values`: {fact: value} a fact is probed with instead of the generic probe -
    the Loss History plan's own answers (`loss_plan_probes`, 23 Oct 2026).

    Each copy keeps `declared_impact` (the typed literal, which a later call
    reads instead of a number this call wrote) and records `impact_scope`."""
    if raw_uncapped is None:
        return None
    probe_values = {str(k): str(v) for k, v in (probe_values or {}).items()}
    copies: Dict[str, List[dict]] = {}
    for result in form_results or []:
        if not isinstance(result, dict):
            continue
        for rec in result.get("recommendations") or []:
            if isinstance(rec, dict) and rec.get("rec_id"):
                copies.setdefault(str(rec["rec_id"]), []).append(rec)

    gains: Dict[str, Tuple[Optional[float], bool]] = {}
    probed_with: Dict[str, Any] = {}
    probes = 0

    def _gain(field: str) -> Tuple[Optional[float], bool]:
        nonlocal probes
        if field in gains:
            return gains[field]
        answer, valid = _package_probe_answer(field, stated=bool(_fv(facts or {}, field)))
        if field in _IMPACT_PROBE_IS_THE_ANSWER:
            answer, valid = _IMPACT_PROBE_VALUE, True
        if field in probe_values:
            answer, valid = probe_values[field], True
        try:
            # The claims rows' table (21 Oct 2026): probed with the same claims
            # marked answered (`claim_checks.probe_answer`), never a placeholder
            # that deletes them - that moved Loss History too (+10 for +6).
            from services.claim_checks import DEDUCTION_FACT as _CLAIMS_FACT, probe_answer
            if field == _CLAIMS_FACT:
                answer, valid = probe_answer(facts or {}), True
        except Exception:                                  # noqa: BLE001
            pass
        probed_with[field] = answer
        gain = None
        if probes < _MAX_PACKAGE_PROBES:
            probes += 1
            try:
                after = rescore({**(facts or {}), field: answer})
                gain = None if after is None else float(after) - float(raw_uncapped)
            except Exception as ex:                        # noqa: BLE001
                logger.debug("package probe failed for %s: %s", field, ex)
        gains[field] = (gain, valid)
        return gains[field]

    # Every card's lone gain first, in the order they always ran (the probe
    # budget is theirs first), then every row's.
    groups = []
    for _rid, recs in copies.items():
        for rec in recs:
            if "declared_impact" not in rec:
                rec["declared_impact"] = rec.get("score_impact")
        field = next((r.get("field") for r in recs if r.get("field")), None)
        unscored = any(r.get("unscored") for r in recs)
        if field and not unscored:
            _gain(str(field))
        groups.append((recs, field, unscored))
    row_fields: List[str] = []
    row_valid: Dict[str, bool] = {}
    for row in top_recs or []:
        field = row.get("field") if isinstance(row, dict) else None
        if not field:
            continue
        _g, valid = _gain(str(field))
        valid = valid and row.get("pillar") not in _CONTENT_SCORED_COMPONENTS
        if field in _IMPACT_PROBE_IS_THE_ANSWER:
            valid = True
        if str(field) not in row_valid:
            row_fields.append(str(field))
        row_valid[str(field)] = row_valid.get(str(field), False) or valid
    # The facts the review screen's cards and key details ask for share the
    # same total (15 Oct 2026, `screen_fields`).
    for field in screen or []:
        if str(field) in row_valid:
            continue
        _g, valid = _gain(str(field))
        row_fields.append(str(field))
        row_valid[str(field)] = bool(valid)

    share, share_base, room, _applied = _share_out_gains(
        row_fields, [str(f) for _r, f, u in groups if f and not u],
        gains, probed_with, row_valid, facts, int(raw_uncapped), rescore)

    def _share_points(field: str) -> Tuple[int, bool]:
        points = share[field]
        if points <= 0:
            return 0, True
        alone = gains[field][0] or 0
        exact = points <= alone and (cap_applied is None
                                     or share_base[field] + points <= cap_applied)
        return points, bool(exact)

    # A number not shared out takes what is left below 100 - once per field:
    # another copy asking the same thing takes no more room than the first did.
    room_taken: Dict[str, int] = {}

    def _within_room(field: Optional[str],
                     points: Optional[Tuple[int, bool]]) -> Optional[Tuple[int, bool]]:
        nonlocal room
        if points is None or points[0] <= 0:
            return points
        key = str(field) if field else None
        if key is not None and key in room_taken:
            kept = min(points[0], room_taken[key])
        else:
            kept = min(points[0], room)
            room -= kept
            if key is not None:
                room_taken[key] = kept
        return kept, bool(points[1]) and kept == points[0]

    for recs, field, unscored in groups:
        component = next((r.get("component") for r in recs if r.get("component")), None)
        if unscored:
            points = (0, True)
        elif field and str(field) in share:
            points = _share_points(str(field))
        else:
            declared = [r.get("declared_impact") for r in recs
                        if isinstance(r.get("declared_impact"), (int, float))
                        and not isinstance(r.get("declared_impact"), bool)]
            gain, valid = _gain(str(field)) if field else (None, False)
            moved_a_form = any(r.get("impact_measured") for r in recs)
            valid = (valid or moved_a_form) and component not in _CONTENT_SCORED_COMPONENTS
            if field in _IMPACT_PROBE_IS_THE_ANSWER:
                valid = True
            points = _within_room(field, _card_points(
                gain, valid, max(declared) if declared else None,
                headroom_for(component), raw_uncapped, cap_applied))
        if points is None:
            continue
        for rec in recs:
            rec["score_impact"], rec["impact_is_exact"] = points
            rec["impact_scope"] = "package"

    for result in form_results or []:
        recs = result.get("recommendations") if isinstance(result, dict) else None
        if isinstance(recs, list) and recs and all(isinstance(r, dict) for r in recs):
            recs.sort(key=lambda r: (r.get("priority", 99), -(r.get("score_impact") or 0)))

    # A Best Solutions row is a pillar's whole gap (`points_available`); the
    # answer it asks for can be worth less - "No known losses" takes Loss
    # History out of the score and moves the package +7 of the row's 11.2.
    # `answer_gain` is the row's share of the one total; `answer_gain_alone`
    # what the answer adds on its own (a row held by another pillar's gate adds
    # nothing alone, and says so - frontend `pillarGates`).
    for row in top_recs or []:
        field = row.get("field") if isinstance(row, dict) else None
        if not field:
            continue
        if str(field) in share:
            points = _share_points(str(field))
            row["answer_gain_share"] = True
            row["answer_gain_alone"] = int(gains[str(field)][0] or 0)
        else:
            gain, valid = _gain(str(field))
            valid = valid and row.get("pillar") not in _CONTENT_SCORED_COMPONENTS
            if field in _IMPACT_PROBE_IS_THE_ANSWER:
                valid = True
            points = _within_room(field, _card_points(
                gain, valid, None, headroom_for(row.get("pillar")),
                raw_uncapped, cap_applied))
        if points is not None:
            row["answer_gain"], row["answer_gain_is_exact"] = points
        # A prose row (the narrative): a placeholder probe cannot write the text
        # the reader scores, so its measured number under-states what the real
        # answer adds. It shows the pillar's whole remaining share, "up to"
        # (23 Oct 2026). Not a share: the page keeps it inside 100 - score.
        if callable(pillar_remaining) and row.get("pillar") in _CONTENT_SCORED_COMPONENTS:
            whole = pillar_remaining(row.get("pillar"))
            if isinstance(whole, int) and whole > int(row.get("answer_gain") or 0):
                row["answer_gain"], row["answer_gain_is_exact"] = whole, False
                row["answer_gain_share"] = False
    return {f: list(_share_points(f)) + [int(gains[f][0] or 0)] for f in share}


# ── ONE TOTAL, SHARED OUT (15 Oct 2026, live `5eb5b23c`; owner: "it should not
# go past 100 ... correct for all the packages") ───────────────────────────────
# Every number was each answer measured ALONE, so at 94 three rows read
# +3 / +2 / +2 - "101" - while answering all three makes exactly 100: the score
# is rounded DOWN, and every lone probe collected the same leftover fraction of
# a point. Lone gains do not add up, ever - two answers can share one rounded
# point, clear one deduction between them, or (a pillar held at 0 until its
# gate is answered) be worth nothing alone and a lot together.
#
# So the numbers are SHARES of one measured total. The answers are applied one
# after another and each takes what the score - rounded down, as the screen
# shows it - moved when it went in. The steps add up exactly to answering them
# all, and a score is never above 100, so neither is the list. They go in in
# the order they are LISTED (owner, 24 Oct 2026: the person works down the
# page; "biggest lone gain first" made every number hold only in an order
# nobody follows), a row worth nothing alone in its place, taking what the
# answers before it unlocked. An answer that LOWERS the score after the others
# takes no share, and what it costs comes off the smallest shares before it, so
# the list still adds up to answering all of it. One number per field: every
# card and row asking the same thing shows the same share. The review page's
# own plan (`services/review_plan`) is the same rule over every item the page
# offers, holds included.
#
# Rows go before cards. Card fields join only when worth something
# alone (a card worth nothing shows nothing; a row is listed by its points).
# A row's 0 joins only when its probe is trusted (`row_valid`): a probe of the
# wrong shape never zeroes a row. Bounded by `_MAX_SHARE_PROBES`; anything not
# shared out (no probe, a broken chain, a card's typed bound) is cut to the
# `room` the shares leave below 100 by the caller.
_MAX_SHARE_PROBES = 24


def _share_out_gains(row_fields, card_fields, gains, probed_with, row_valid,
                     facts, raw_now: int, rescore):
    """(share, share_base, room, applied): each field's whole points of the one
    total, the score its step started from, the points left below 100, and the
    answers that went into the total."""
    listed: List[str] = []
    for f in list(row_fields) + list(card_fields):
        if f not in listed:
            listed.append(f)
    alone = {f: (gains.get(f) or (None, False))[0] for f in listed}
    positive = {f for f in listed if f in probed_with and alone[f] is not None and alone[f] > 0}
    # PAGE ORDER (owner, 24 Oct 2026): the answers go in in the order they are
    # listed - the order a person works down the page - never "biggest lone
    # gain first", which held only in an order nobody follows. A row worth
    # nothing alone joins in its place when its probe is trusted.
    in_order = [f for f in listed if f in positive
                or (f in row_fields and f in probed_with and alone.get(f) == 0 and row_valid.get(f))]
    share: Dict[str, int] = {}
    share_base: Dict[str, int] = {}
    applied: Dict[str, Any] = {}
    now = int(raw_now)
    owed = 0
    probes = 0
    for f in in_order:
        if not applied and f in positive:
            after = now + int(alone[f])              # its lone probe, reused
        else:
            if probes >= _MAX_SHARE_PROBES:
                break
            probes += 1
            try:
                after = rescore({**(facts or {}), **applied, f: probed_with[f]})
            except Exception as ex:                  # noqa: BLE001
                logger.debug("share probe failed at %s: %s", f, ex)
                break
            if after is None:
                break
            after = int(after)
        step = after - now
        share_base[f] = now
        share[f] = max(0, step)
        if step < 0 and f not in positive:
            continue            # worth nothing alone, less after the others: left out
        # An answer listed for its own points goes in even when, after the
        # others, it costs points - answering the list answers it too - and
        # what it costs comes off the shares before it (below).
        owed += max(0, -step)
        applied[f] = probed_with[f]
        now = after
    # What a step cost comes off the smallest shares first - the last ones in
    # (the rows worth nothing alone, then the smaller lone gains) - so the
    # biggest answers keep their full value and the shares add up exactly.
    for f in reversed(list(share)):
        if owed <= 0:
            break
        taken = min(share[f], owed)
        share[f] -= taken
        owed -= taken
    # A chain that ends BELOW where it started (answers that, together, cost
    # points) leaves no more room than the start did.
    return share, share_base, max(0, 100 - max(now, int(raw_now))), applied


def _page_one_carrier_printed(facts: dict, mapped_data: Optional[dict]) -> bool:
    """Is ACORD 125 page one's CARRIER box filled? (29 Sep 2026, client item 8)

    After generation the stamped box decides. Before it (no stamped form) the
    stamper's own resolver chain decides - `pdf_service.authoritative_expected_
    value`, the one door for "what should this box hold?" - so the card and the
    form cannot disagree. Fails OPEN (True: no card) on any error: a missing
    card is recoverable, a card asking for a value already printed is noise.
    """
    box = "Insurer_FullName_A"
    # Only a STAMPED form holds the box. The facts-only scorer passes a mapping
    # keyed by fact names (never this box), which must not read as "blank"
    # (review, 29 Sep: the card then fired on every pre-form ACORD 125).
    if isinstance(mapped_data, dict) and box in mapped_data:
        return bool(str(mapped_data.get(box) or "").strip())
    try:
        from services import pdf_service as _ps
        owned = _ps.authoritative_expected_value("ACORD_125", box, facts or {})
        if owned is _ps._AUTH_UNOWNED:
            return bool(str(_fv(facts, "carrier_name") or "").strip())
        return bool(str(owned or "").strip())
    except Exception:                                            # noqa: BLE001
        return True


def _form_open_warning(form_id: Any, mapped_data: Optional[dict], confidence_dict: Optional[dict],
                       form_schema: Optional[dict], facts: Optional[dict], flags: Optional[dict],
                       cross_issues: Optional[List[dict]]) -> Optional[str]:
    """What holds ONE FORM at 85 after forms (owner, 30 Oct 2026: "only form
    specific hard stops / warnings / required things / cross-form validation /
    anything important as per our rules should lower or hold the score of forms,
    not just any random value missing on the form"). Two things, both already
    shown on that form's screens:
      - a cross-form check that names this form and is not advisory (a warning -
        cross-form checks keep one status, Brent 14 Oct 2026);
      - a box the form REQUIRES that the side panel lists as Missing - on a row
        the form actually uses, never the applicant's signature / date (the
        client signs later) and never a box our rules leave blank on purpose
        (the side panel's own rule, `needs_attention.needs_attention`).
    Optional empty boxes and "Please verify" values never hold a form.
    None when nothing holds. Never raises."""
    try:
        from services.form_instances import base_form_id
        base = base_form_id(str(form_id or ""))
        for i in cross_issues or []:
            if not isinstance(i, dict):
                continue
            # A FORM-scope check (owner, 30 Oct 2026) is deferred off the
            # package - an advisory `form_choice` - but holds the forms it names
            # at its own severity (`deferred_type`).
            _t = str((i.get("deferred_type") if i.get("form_choice") else None)
                     or i.get("type") or "")
            if _t == "advisory":
                continue
            if base in {base_form_id(str(f)) for f in (i.get("forms") or [])}:
                return str(i.get("message") or "A cross-form check on this form is open")
        mapped = mapped_data if isinstance(mapped_data, dict) else {}
        schema = form_schema if isinstance(form_schema, dict) else {}
        if not mapped or not schema:
            return None
        from services.needs_attention import needs_attention, unused_trailing_row
        from services.signature_boxes import is_applicant_step
        gen = {"mapped": mapped, "field_state": mapped, "confidence": confidence_dict or {},
               "schema": schema}
        rows = needs_attention(gen, facts or {}, str(form_id or ""), flags=flags or {})

        def _row_in_use(field: str) -> bool:
            m = re.match(r"^([^_]+)_.*_([B-Z])$", field or "")
            if not m:
                return True
            root, suffix = m.group(1), m.group(2)
            # ACORD names a contact list under its party's root ("NamedInsured_
            # Contact_*"): a contact on row B is not a second named insured.
            own_contact = field.startswith(root + "_Contact_")
            return any(k != field and k.startswith(root + "_") and k.endswith("_" + suffix)
                       and k.startswith(root + "_Contact_") == own_contact
                       and str(v or "").strip() not in ("", "None", "null", "Off", "No", "False")
                       for k, v in mapped.items())

        open_req = []
        for r in rows or []:
            f = str(r.get("field") or "")
            if r.get("status") != "missing" or not r.get("required"):
                continue
            tu = (schema.get(f) or {}).get("tu") if isinstance(schema.get(f), dict) else ""
            if is_applicant_step(f, tu or ""):
                continue
            if unused_trailing_row(f, mapped, str(form_id or "")) or not _row_in_use(f):
                continue
            open_req.append(r)
        if not open_req:
            return None
        name = str(form_id or "").replace("ACORD_", "ACORD ")
        first = str(open_req[0].get("label") or open_req[0].get("field"))
        more = f" (+{len(open_req) - 1} more)" if len(open_req) > 1 else ""
        return f"{name}: required box still empty - {first}{more}"
    except Exception:                                          # noqa: BLE001
        return None


# The forms whose Structural / Exposure pillars score their OWN checklist (the
# `fid ==` branches of `calculate_sqs`; the rest score the fill rate). Their
# checklist facts are `FORM_FIELD_INVENTORY`.
_CHECKLIST_FORMS = frozenset({
    "ACORD_25", "ACORD_125", "ACORD_126", "ACORD_127", "ACORD_130", "ACORD_131",
    "ACORD_133", "ACORD_140", "ACORD_141", "ACORD_160", "ACORD_186", "ACORD_28", "ACORD_101",
})
# Either fact satisfies the check that reads them.
_EITHER_OR_FACTS = (
    ("additional_remarks_text", "remarks_text", "explanation_of_yes_answers"),
    ("auto_vin_schedule", "vehicle_schedule"),
    ("wc_payroll", "total_payroll"),
    ("umbrella_sir", "umbrella_attachment_point"),
    ("property_building_value", "property_bpp_value"),
    ("mortgagee_name", "certificate_holder"),
    ("total_revenue", "total_payroll"),
    ("gl_limits", "gl_aggregate", "gl_each_occurrence"),
)
_HEADER_BOX_OF = {"policy_number": "Policy_PolicyNumberIdentifier_A",
                  "carrier_name": "Insurer_FullName_A", "carrier_naic": "Insurer_NAICCode_A"}


_FORM_CHECK_FACTS_CACHE: Dict[str, List[str]] = {}
# A check that reads its fact through a helper: the facts that helper reads.
_CHECK_HELPER_FACTS: Dict[str, Tuple[str, ...]] = {
    "_prints_policy_number": ("policy_number",),
    "_auto_liability_stated": ("auto_liability_limit",),
    "gl_class_codes_present": ("gl_class_codes_by_location",),
    "_radius_known": ("auto_radius_of_operation",),
    "_narrative_remarks_text": ("additional_remarks_text",),
    "_umbrella_retention_checks": ("umbrella_sir", "umbrella_attachment_point"),
    "_umbrella_underlying_checks": ("gl_each_occurrence", "auto_liability_limit",
                                    "employers_liability_limits", "schedule_of_underlying_insurance"),
}


def _form_check_facts(base: str) -> List[str]:
    """The facts THIS form's own checks read - every `_fv(facts, "x")` inside its
    `fid == "<form>"` branches of `calculate_sqs`, in order (parsed once from the
    scorer itself, so a card is offered only for what the score counts). A form
    with no branch of its own (it scores its fill) - its inventory."""
    if not _FORM_CHECK_FACTS_CACHE:
        import ast as _ast
        import inspect as _inspect
        try:
            tree = _ast.parse(_inspect.getsource(calculate_sqs).lstrip())
        except Exception:                                      # noqa: BLE001
            tree = None
        found: Dict[str, List[str]] = {}
        for n in (_ast.walk(tree) if tree is not None else ()):
            if (isinstance(n, _ast.If) and isinstance(n.test, _ast.Compare)
                    and isinstance(n.test.left, _ast.Name) and n.test.left.id == "fid"
                    and n.test.comparators and isinstance(n.test.comparators[0], _ast.Constant)):
                lst = found.setdefault(str(n.test.comparators[0].value), [])
                for b in n.body:
                    for m in _ast.walk(b):
                        if not isinstance(m, _ast.Call):
                            continue
                        name = getattr(m.func, "id", None)
                        if (name == "_fv" and len(m.args) >= 2 and isinstance(m.args[1], _ast.Constant)
                                and m.args[1].value not in lst):
                            lst.append(m.args[1].value)
                        for hf in _CHECK_HELPER_FACTS.get(str(name or ""), ()):
                            if hf not in lst:
                                lst.append(hf)
        _FORM_CHECK_FACTS_CACHE.update(found or {"_": []})
    got = _FORM_CHECK_FACTS_CACHE.get(base)
    return list(got) if got else list(FORM_FIELD_INVENTORY.get(base) or [])


def _cards_for_uncarded_pillars(form_id: Any, breakdown: dict, recommendations: List[dict],
                                facts: dict, flags: dict, mapped_data: Optional[dict]) -> List[dict]:
    """Cards for a pillar the form charges with no card of its own (a deduction
    with nothing to answer is a dead end): the umbrella pillar's own deduction
    items; for a checklist form, its empty checklist facts - never one the form
    prints, one whose either-or partner is answered, or one no box can take."""
    from services.form_instances import base_form_id
    from services.answer_routing import answer_mode
    base = base_form_id(str(form_id or ""))
    recs = [r for r in (recommendations or []) if isinstance(r, dict)]
    have = {str(r.get("field") or "") for r in recs}
    comps = {str(r.get("component") or "") for r in recs}
    mapped = mapped_data if isinstance(mapped_data, dict) else {}
    out: List[dict] = []

    def low(comp: str) -> bool:
        v = (breakdown or {}).get(comp)
        return isinstance(v, (int, float)) and v < 100 and comp not in comps

    def card(f: str, comp: str, label: str, pts: int) -> dict:
        have.add(f)
        return {"rec_id": f"rec_{f}", "field": f, "component": comp, "message": label,
                "type": "missing_field", "score_impact": int(pts or 0), "priority": 2}

    # The umbrella pillar's items are the umbrella's own form's (ACORD 131) - on
    # any other form they are the package's (its Best Solutions), never this
    # form's side panel.
    if base == "ACORD_131" and low("umbrella_limit_adequacy"):
        for it in umbrella_deduction_items(facts, flags) or []:
            f = str((it or {}).get("fact") or "")
            if f and f not in have and answer_mode(f, facts).get("mode") == "field":
                out.append(card(f, "umbrella_limit_adequacy", str(it.get("label") or f),
                                int(it.get("points") or 0)))
    # Every form: a checklist form's facts are its checks', a fill-scored one's
    # are the boxes its fill counts (`FORM_FIELD_INVENTORY`, pinned to the checks
    # by tests/test_every_form_reaches_100_30oct.py).
    if base in FORM_FIELD_INVENTORY:
        try:
            from services.fact_registry import FACT_REGISTRY
        except Exception:                                      # noqa: BLE001
            FACT_REGISTRY = {}
        for comp in ("structural_completeness", "exposure_consistency"):
            if not low(comp):
                continue
            for f in _form_check_facts(base):
                if f in have or _answered(facts, f):
                    continue
                box = _HEADER_BOX_OF.get(f)
                if box and str(mapped.get(box) or "").strip() not in ("", "None", "null"):
                    continue
                if any(f in g and any(_answered(facts, x) or x in have for x in g if x != f)
                       for g in _EITHER_OR_FACTS):
                    continue
                if answer_mode(f, facts).get("mode") not in ("field", "narrative", "schedule"):
                    continue
                label = str((FACT_REGISTRY.get(f) or {}).get("label") or f.replace("_", " ").capitalize())
                out.append(card(f, comp, label, 0))
    # The same choices / control every other card carries (added after the
    # form's own cards got theirs).
    try:
        from services.answer_options import attach_answer_controls
        attach_answer_controls(out)
    except Exception:                                          # noqa: BLE001
        pass
    return out


def _prints_policy_number(facts: dict, mapped_data: Optional[dict]) -> bool:
    """A section form names its policy: the number its own header box prints
    (`Policy_PolicyNumberIdentifier_A`, its line's - `policy_lines.HEADER_BOXES`),
    else the package fact (the no-forms path's synthetic boxes are the facts)."""
    m = mapped_data if isinstance(mapped_data, dict) else {}
    box = m.get("Policy_PolicyNumberIdentifier_A")
    if isinstance(box, dict):
        box = box.get("value")
    if str(box or "").strip() not in ("", "None", "null"):
        return True
    return bool(_fv(facts, "policy_number"))


def _acord101_names_its_form(facts: dict) -> bool:
    """ACORD 101 names the form it continues - what its FORM NUMBER / TITLE boxes
    print (`pdf_service.acord101_attached_forms`, the stamper's own answer). The
    check read a `form_reference` fact nothing writes, so every ACORD 101 stopped at
    87 with nothing to answer (live c5675766, 30 Oct 2026). A person's or an
    uploaded form's value still counts."""
    if _fv(facts, "form_reference"):
        return True
    try:
        from services.pdf_service import acord101_attached_forms
        return bool(acord101_attached_forms(facts))
    except Exception:                                          # noqa: BLE001
        return False


_STOP_SUBJECT_FORM_RE = re.compile(r"^\s*ACORD[\s_]+(\d{2,3})(?:[\s_]+(CA|CO))?\b", re.I)


def stops_for_form(stops: Optional[List[str]], form_id: Any) -> List[str]:
    """The package's field-level stops that may hold ONE form (owner, 30 Oct
    2026: "only form specific hard stops / warnings ... should lower or hold the
    score of forms"). A stop whose SUBJECT is another ACORD form - its sentence
    starts "ACORD <n> ..." ("ACORD 125 minimum field missing: Producer / Agency
    name") - is that form's, never this one's: it held ACORD 126 and 127 at 85
    (and at 60 for a missing proposed term) with nothing on those forms to fix
    (shape fuzz, 30 Oct 2026). A stop naming no form, or naming this form,
    stays. The package score still takes every stop. No form id: unchanged."""
    out = [m for m in (stops or []) if m]
    if not form_id:
        return out
    try:
        from services.form_instances import base_form_id
        base = base_form_id(str(form_id))
    except Exception:                                          # noqa: BLE001
        base = str(form_id)
    m_self = re.match(r"^ACORD_(\d{2,3})", base)
    if not m_self:
        return out
    lines_here = _FORM_LINES.get(m_self.group(1))
    kept = []
    for msg in out:
        m = _STOP_SUBJECT_FORM_RE.match(str(msg))
        if m and m.group(1) != m_self.group(1):
            continue
        # A LINE's stop holds only that line's forms (30 Oct 2026, shape fuzz:
        # "GL coverage detected but no class codes" held ACORD 127 at 85). The
        # line is read off the stop's own rule group (`classify_legacy`'s
        # cluster) - one table, no wording match. The application (125), the
        # remarks (101) and any form not in `_FORM_LINES` take every stop.
        if lines_here is not None and not m:
            try:
                from services.issue_registry import classify_legacy
                _code, cluster, _tier = classify_legacy(str(msg), "soft_warning")
            except Exception:                                  # noqa: BLE001
                cluster = None
            line = _cluster_line(cluster)
            if line and line not in lines_here:
                continue
        kept.append(msg)
    return kept


# The rule group (`issue_registry` cluster) -> its line, read from the group's own
# line words. A group naming no line (identity, dates, formats, loss history,
# carrier context) is the package's and holds every form.
_CLUSTER_LINE_WORDS = (
    ("umbrella", "umbrella"), ("excess", "umbrella"),
    ("workers", "wc"), ("wc ", "wc"), ("employers liability", "wc"),
    ("general liability", "gl"), ("gl ", "gl"),
    ("auto", "auto"), ("vehicle", "auto"), ("driver", "auto"),
    ("property", "property"), ("cope", "property"), ("business income", "property"),
)


def _cluster_line(cluster: Any) -> Optional[str]:
    c = " " + str(cluster or "").lower() + " "
    for word, line in _CLUSTER_LINE_WORDS:
        if word in c:
            return line
    return None


# Each section form's lines. 125 (the application) and 101 (remarks) are absent:
# they speak for every line, so every stop may hold them.
_FORM_LINES = {
    "126": {"gl"}, "186": {"gl"},
    "127": {"auto"}, "137": {"auto"}, "138": {"auto"},
    "130": {"wc"}, "133": {"wc"},
    "131": {"umbrella"},
    "140": {"property"}, "28": {"property"}, "160": {"property", "gl"},
    "141": set(),
    "25": {"gl", "auto", "wc", "umbrella"},
}


def _form_download_blocker(form_id: Any, mapped_data: Optional[dict],
                           confidence_dict: Optional[dict]) -> Optional[str]:
    """A FORM's own hard stop (owner, 30 Oct 2026: "forms score is 100 but there
    are stops"). The download screen lists a box that blocks a clean download -
    a required-gate box left empty (today ACORD 140's construction type) or a
    leaked placeholder value - as a hard stop. The form's score now holds at 60
    while one is open, like every other hard stop. The same rule the download
    gate enforces (`field_qa._gate_still_blocks`, `is_placeholder_value`), read
    from this form's own boxes - no QA run. None when nothing blocks."""
    try:
        from services.field_qa import _gate_still_blocks
        from services.placeholder_detector import is_placeholder_value
        mapped = mapped_data if isinstance(mapped_data, dict) else {}
        conf = confidence_dict if isinstance(confidence_dict, dict) else {}
        blocked = []
        for field, label in conf.items():
            lab = label.get("label") if isinstance(label, dict) else label
            if lab != "missing_required_gate" or not _gate_still_blocks(form_id, field):
                continue
            if str(mapped.get(field) or "").strip() in ("", "None", "null"):
                blocked.append(field)
        for field, val in mapped.items():
            if isinstance(val, str) and val.strip() and is_placeholder_value(val)[0]:
                blocked.append(field)
        if not blocked:
            return None
        try:
            from services.needs_attention import form_box_label
            words = form_box_label(form_id, blocked[0], None) or blocked[0]
        except Exception:                                      # noqa: BLE001
            words = blocked[0]
        more = f" (+{len(blocked) - 1} more)" if len(blocked) > 1 else ""
        name = str(form_id or "").replace("ACORD_", "ACORD ")
        return f"{name}: \"{words}\" is required before download{more}"
    except Exception:                                          # noqa: BLE001
        return None


def calculate_sqs(
    facts: dict,
    flags: dict,
    mapped_data: dict,
    form_schema: dict,
    selected_form_ids: List[str],
    hard_stops: List[str],
    soft_stops: List[str],
    tier2_score: int,
    form_id: Optional[str] = None,
    schema_size: Optional[int] = None,
    fields_mapped: Optional[int] = None,
    confidence_dict: Optional[dict] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    calculation_stage: str = "initial_extract",
    # §6 additions - default False so existing call sites are unaffected
    has_narrative_doc: bool = False,
    has_loss_run_doc:  bool = False,
    loss_run_match:    str  = "no_loss_run",
    cross_issues_full: Optional[List[dict]] = None,
    # §6.3: full narrative doc text for component scoring (default "" = no-op)
    narrative_doc_text: str = "",
    # Internal. True only inside a counterfactual run started by
    # _measure_recommendation_impacts, where it stops the scorer measuring
    # impacts again - i.e. it is what makes the recursion terminate. Never set
    # it from production code.
    _simulate: bool = False,
    # False on the no-forms path (`calculate_sqs_from_facts`): its boxes are a
    # synthetic copy of the facts, so no form box can hold it (30 Oct 2026 -
    # the side panel pass on that copy cost 0.37 s a form for nothing).
    _form_boxes: bool = True,
) -> dict:
    """Per-form SQS calculation with full metadata and structured recommendations."""
    # ONE RULE for a form's second copy (7 Oct 2026, Choice Electric #4): the
    # copy ("ACORD_131__excess") is scored by its form's rule set on its own
    # view of the facts, and the result keeps the copy's id. Every plain id is
    # unchanged (`form_instances.facts_for_form` returns the same object).
    _scored_form_id = form_id
    if form_id:
        from services.form_instances import (
            base_form_id as _base_form_id, base_form_ids as _base_form_ids,
            facts_for_form as _facts_for_form, is_instance as _is_instance,
        )
        facts = _facts_for_form(facts, form_id)
        form_id = _base_form_id(form_id)
        if any(_is_instance(f) for f in (selected_form_ids or [])):
            selected_form_ids = _base_form_ids(selected_form_ids)
        # Only this form's stops hold it (`stops_for_form`, 30 Oct 2026).
        hard_stops = stops_for_form(hard_stops, form_id)
        soft_stops = stops_for_form(soft_stops, form_id)
    extraction_quality = facts.get("_extraction_quality", 1.0)
    if isinstance(extraction_quality, float) and extraction_quality < 0.60:
        return {
            "sqs_score": None,
            "needs_reextraction": True,
            "tier": "Incomplete",
            "routing_decision": "hold",
            "issues": [f"Only {int(extraction_quality*100)}% of document was processed. Re-upload or reprocess."],
            "recommendations": [],
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "model_version": SQS_MODEL_VERSION,
            "session_id": session_id,
            "user_id": user_id,
            "calculation_stage": calculation_stage,
        }

    breakdown: dict = {}
    issues: List[str] = []
    recommendations: List[dict] = []
    fraud_penalty = 0

    fid = form_id or (selected_form_ids[0] if selected_form_ids else "UNKNOWN")
    # THIRD SITE OF THE SAME DEFECT (2026-09-04). `is_certificate_doc` is a
    # PER-DOCUMENT flag and flags merge across the package, so ANY uploaded COI
    # made this true - and an ACORD 125 was then scored against the CERTIFICATE
    # checklist (applicant / effective date / policy number) instead of its own
    # application checklist. Scoring a full commercial application as if it were
    # a certificate is not a near-miss; it grades the wrong form.
    #
    # `fid == "ACORD_25"` is correct and stays: when the form BEING SCORED is
    # the certificate, the certificate checklist is the right one. The package
    # signal now has to say the SUBMISSION is certificate-only, through the same
    # door `_tier1_items` and `producer_fields_exempt` use.
    #
    # SCORES MOVE (D6) on any package that carries a COI alongside other
    # documents - those forms are now graded against their own checklist.
    is_cert_only = fid == "ACORD_25" or (
        flags.get("is_certificate_doc", False) and certificate_only_package(flags)
    )
    total_fields = schema_size if schema_size is not None else len(form_schema)
    filled_fields = fields_mapped if fields_mapped is not None else sum(
        1 for v in mapped_data.values()
        if v is not None and str(v).strip() not in ("", "null", "None")
    )
    fill_rate = int((filled_fields / total_fields) * 100) if total_fields > 0 else 0

    # Use confidence-weighted fill rate if available
    if confidence_dict:
        conf_rate = confidence_fill_rate(mapped_data, confidence_dict)
    else:
        conf_rate = fill_rate

    # ── Structural completeness ───────────────────────────────────────────────
    if is_cert_only:
        chks = [
            bool(_fv(facts, "applicant_name") or _fv(facts, "certificate_holder")),
            bool(_fv(facts, "effective_date")),
            bool(_fv(facts, "policy_number")),
            bool(_fv(facts, "gl_limits") or _fv(facts, "gl_aggregate")),
        ]
        struct = int(sum(chks) / len(chks) * 100)

    elif fid == "ACORD_125":
        # `scored` mirrors check_tier1's dec-page exemption so the per-form and
        # package scorers cannot disagree about what a submission owes (see
        # producer_fields_exempt). An exempt check is still REPORTED as missing -
        # we still want the detail - it just stops docking the pillar.
        #
        # C3 3.3 (2026-08-25): CONTACT INFORMATION is no longer exempt on either
        # scorer. Client 3.3 and spec section 3.1 both waive producer name only,
        # and only when the ONLY source document is a declarations page. This
        # line and `check_tier1` must always move together - they are the two
        # copies of one rule, and the 2026-08-17 defect was exactly them
        # disagreeing.
        _prod_exempt = producer_fields_exempt(flags)
        _checks = [
            # (label, fact key for the card, present?, counts toward the score?)
            ("applicant name",    "applicant_name",
             bool(_fv(facts, "applicant_name")),    True),
            ("mailing address",   "mailing_address",
             bool(_fv(facts, "mailing_address")),   True),
            ("effective date",    "effective_date",
             bool(_fv(facts, "effective_date")),    True),
            ("lines of business", "lines_of_business",
             bool(_fv(facts, "lines_of_business")), True),
            ("contact info",      "contact_name",
             bool(_fv(facts, "contact_name") or _fv(facts, "contact_phone")
                  or _fv(facts, "contact_email")), True),
            ("producer name",     "producer_name",
             bool(_fv(facts, "producer_name")),     not _prod_exempt),
            # 29 Sep 2026 (client item 8, "no prompt to supply them"): page
            # one's CARRIER is left blank when no company can be named (the
            # current policies of a quote whose market is not stated) - and,
            # since Brent's 8 Oct answer, when SEVERAL companies write the
            # renewed programme (the 30 Sep join is gone). Ask for it - worth
            # zero points, because carrier_name is not a Tier 1 / Tier 2 fact.
            # The answer is the ADDRESSEE (`submission_carrier_name`), never
            # `carrier_name`: the documents own that one, and a typed market
            # written there was overwritten or held as a conflict by the next
            # re-merge (review finding, 29 Sep).
            ("carrier receiving this submission", "submission_carrier_name",
             _page_one_carrier_printed(facts, mapped_data), False),
            # NOTE: the 4th element is `scored`. An UNSCORED check still raises
            # its card (we want the detail) but must advertise ZERO points - see
            # `unscored` on the recommendation below.
        ]
        chks = [ok for _l, _f, ok, scored in _checks if scored]
        struct = int(sum(chks) / len(chks) * 100) if chks else 100
        missing = [(l, f, sc) for l, f, ok, sc in _checks if not ok]
        for label, field_name, _scored in missing:
            recommendations.append({
                "rec_id": f"rec_{field_name}",
                "field": field_name,
                "component": "structural_completeness",
                "message": f"ACORD 125 missing: {label}",
                # No proposed term is a hard stop since 19 Oct 2026 (D71: it
                # holds 60), so its card says so - the cover files it under
                # "CRITICAL - Hard Stops" and the download review counts it as
                # one (`recommendation_type`, retyped on the next card sync).
                "type": "hard_stop" if field_name == "effective_date" else "missing_field",
                "score_impact": 0 if not _scored else (
                    15 if field_name in TIER1_FIELDS else 8),
                "priority": 1 if field_name in TIER1_FIELDS else 2,
                # An exempt check is still ASKED FOR and worth exactly ZERO. Say
                # so, so `_measure_recommendation_impacts` cannot fall back to a
                # typed literal: its "no movement measured" branch cannot tell a
                # genuine zero from a probe of the wrong shape, so on a
                # dec-page-only submission the exempt producer-name card
                # advertised "up to +5 pts" while the pillar it belongs to could
                # not move at all. Live on S1, 2026-08-25.
                "unscored": not _scored,
            })
        # Orbin 22 Sep item 12 / G2 (29 Sep 2026): the ONE premises' interest
        # (a confirm card that shows its evidence - never an inference) and a
        # tenant's landlord. Unscored, 0 points; nothing here moves a score.
        recommendations.extend(_premises_recommendations(facts, flags, mapped_data))

    elif fid == "ACORD_126":
        # GL class-code data may arrive in either the legacy location→codes fact
        # or the richer schedule-of-hazards fact (class code + premium/exposure
        # basis + exposure amount + subcontractor %). Either satisfies the gap -
        # through the ONE reader (21 Oct 2026, the GL window): a row with no code
        # (a classification read without its code, a row a person marked
        # "Unknown - follow up") is not a class code, and the package's own
        # "no class codes found" warning said so while this card was satisfied.
        _gl_class_present = gl_class_codes_present(facts)
        chks = [
            bool(_fv(facts, "gl_limits") or _fv(facts, "gl_aggregate") or _fv(facts, "gl_each_occurrence")),
            _gl_class_present,
            bool(_fv(facts, "operations_description")),
            bool(_fv(facts, "total_payroll") or _fv(facts, "total_revenue")),
            bool(_fv(facts, "gl_form_type")),
        ]
        struct = int(sum(chks) / len(chks) * 100)
        if not _gl_class_present:
            issues.append("GL class codes missing")
            recommendations.append({
                "rec_id": "rec_gl_class_codes",
                "field": "gl_class_codes_by_location",
                "component": "exposure_consistency",
                "message": "Provide GL class codes",
                "type": "missing_field",
                "score_impact": 12,
                "priority": 1,
            })
        if not _fv(facts, "gl_form_type"):
            recommendations.append({
                "rec_id": "rec_gl_form_type",
                "field": "gl_form_type",
                "component": "exposure_consistency",
                "message": "Specify GL form type: occurrence or claims-made",
                "type": "missing_field",
                "score_impact": 5,
                "priority": 2,
            })

    elif fid == "ACORD_141":
        # ACORD 141 is the CRIME section (its template's title; Z37, 24 Oct
        # 2026 - it was scored as a property schedule). Its own facts decide.
        _crime_parts = [
            ("crime_limit",          "crime limit",          True),
            ("crime_deductible",     "crime deductible",     False),
            ("crime_employee_count", "employees covered",    False),
        ]
        struct = int(sum(1 for fk, _l, _r in _crime_parts if _fv(facts, fk))
                     / len(_crime_parts) * 100)
        for fk, lbl, required in _crime_parts:
            if not _fv(facts, fk):
                if required:
                    issues.append(f"Crime section missing: {lbl}")
                recommendations.append({
                    "rec_id": f"rec_{fk}",
                    "field": fk,
                    "component": "structural_completeness",
                    "message": f"ACORD 141 needs the {lbl}",
                    "type": "missing_field" if required else "suggestion",
                    "score_impact": 15 if required else 5,
                    "priority": 1 if required else 2,
                })

    elif fid == "ACORD_140":
        # Each part names itself, so the card asks only for what is missing
        # (owner's run `18ecbfa8`, 12 Oct 2026: it listed all four while
        # construction and both building values were already stated). With all
        # four missing the sentence is word for word the old one.
        _min_cope_parts = [
            ("street address",        bool(_fv(facts, "locations"))),
            ("occupancy",             bool(_fv(facts, "occupancy_type"))),
            ("construction type",     bool(_fv(facts, "construction_type"))),
            ("building or BPP value", bool(_fv(facts, "property_building_value")
                                           or _fv(facts, "property_bpp_value"))),
        ]
        min_cope = [ok for _label, ok in _min_cope_parts]
        if not all(min_cope):
            struct = 0
            issues.append("Minimum Viable COPE incomplete - hard stop")
            recommendations.append({
                "rec_id": "rec_min_cope",
                "field": "locations",
                "component": "property_integrity",
                "message": "Required: " + _words_list([label for label, ok in _min_cope_parts if not ok]),
                "type": "hard_stop",
                "score_impact": 0,
                "priority": 1,
            })
        else:
            _cope_t1 = [
                ("year_built",            "year built"),
                ("roof_year",             "roof year"),
                ("sprinkler_system",      "sprinkler system"),
                ("fire_protection_class", "fire protection class"),
            ]
            _cope_t2 = [
                ("distance_to_hydrant",   "distance to hydrant"),
                ("fire_department_type",  "fire department type"),
                ("business_income_limit", "business income limit"),
                ("period_of_restoration", "period of restoration"),
            ]
            _t1_ok = [bool(_fv(facts, k)) for k, _ in _cope_t1]
            _t2_ok = [_cope_tier_ok(facts, k) for k, _ in _cope_t2]
            struct = 60 + sum(_t1_ok) * 5 + sum(_t2_ok) * 5
            carrier_cope_fields = _cope_t1 + _cope_t2
            carrier_cope = _t1_ok + _t2_ok
            mc = [(lbl, fk) for (fk, lbl), ok in zip(carrier_cope_fields, carrier_cope) if not ok]
            for label, field_name in mc:
                recommendations.append({
                    "rec_id": f"rec_{field_name}",
                    "field": field_name,
                    "component": "property_integrity",
                    "message": f"For Carrier-Grade COPE provide: {label}",
                    "type": "suggestion",
                    "score_impact": 5,
                    "priority": 2,
                })
    elif fid == "ACORD_133":
        # ACORD 133 is the Workers Compensation Insurance Plan / Assigned Risk
        # section (its template's title, 2026-09-05; Z37 24 Oct 2026 - it was
        # still scored as Builders Risk). It reads the WC exposure facts.
        _wc_parts = [
            ("wc_class_codes", "WC class codes",       bool(_fv(facts, "wc_class_codes"))),
            ("wc_payroll",     "WC payroll",           bool(_fv(facts, "wc_payroll")
                                                            or _fv(facts, "total_payroll"))),
            ("num_employees",  "number of employees",  bool(_fv(facts, "num_employees"))),
        ]
        struct = int(sum(1 for _k, _l, ok in _wc_parts if ok) / len(_wc_parts) * 100)
        for fk, lbl, ok in _wc_parts:
            if not ok:
                issues.append(f"Workers Compensation section missing: {lbl}")
                recommendations.append({
                    "rec_id": f"rec_{fk}",
                    "field": fk,
                    "component": "structural_completeness",
                    "message": f"ACORD 133 needs the {lbl}",
                    "type": "missing_field",
                    "score_impact": 10,
                    "priority": 1,
                })

    elif fid in ("ACORD_137_CA", "ACORD_137_CO"):
        # State commercial auto supplement: auto symbols and limits drive completeness.
        auto_chks = [
            _auto_liability_stated(facts),
            bool(_fv(facts, "auto_covered_symbols")),
            bool(_fv(facts, "auto_um_uim_limit")),
            bool(_fv(facts, "auto_deductible_comp") or _fv(facts, "auto_deductible_collision")),
        ]
        struct = int(sum(auto_chks) / len(auto_chks) * 100)
        if not _auto_liability_stated(facts):
            issues.append("Commercial auto liability limit not specified")
            recommendations.append({
                "rec_id": "rec_auto_liability_limit",
                "field": "auto_liability_limit",
                "component": "structural_completeness",
                "message": "Provide commercial auto liability limit",
                "type": "missing_field",
                "score_impact": 20,
                "priority": 1,
            })
        if not _fv(facts, "auto_covered_symbols"):
            recommendations.append({
                "rec_id": "rec_auto_covered_symbols",
                "field": "auto_covered_symbols",
                "component": "exposure_consistency",
                "message": "Provide covered auto symbols for the selected coverage",
                "type": "missing_field",
                "score_impact": 12,
                "priority": 1,
            })
        for fk, lbl in [
            ("auto_um_uim_limit", "uninsured/underinsured motorist limit"),
            ("auto_hired_nonowned", "hired/non-owned auto selection"),
        ]:
            if not _fv(facts, fk):
                recommendations.append({
                    "rec_id": f"rec_{fk}",
                    "field": fk,
                    "component": "exposure_consistency",
                    "message": f"Commercial auto supplement missing: {lbl}",
                    "type": "suggestion",
                    "score_impact": 8,
                    "priority": 2,
                })

    elif fid in ("ACORD_138_CA", "ACORD_138_CO"):
        # State garage/dealers supplement: garage limits and operations drive completeness.
        garage_chks = [
            bool(_fv(facts, "garage_operations_type")),
            bool(_fv(facts, "garage_liability_limit")),
            bool(_fv(facts, "garagekeeper_liability_limit")),
            bool(_fv(facts, "auto_dealers_inventory_value")),
        ]
        struct = int(sum(garage_chks) / len(garage_chks) * 100)
        if not _fv(facts, "garage_liability_limit"):
            issues.append("Garage liability limit not specified")
            recommendations.append({
                "rec_id": "rec_garage_liability_limit",
                "field": "garage_liability_limit",
                "component": "structural_completeness",
                "message": "Provide garage/dealers liability limit",
                "type": "missing_field",
                "score_impact": 20,
                "priority": 1,
            })
        for fk, lbl in [
            ("garage_operations_type", "garage/dealer operations type"),
            ("garagekeeper_liability_limit", "garagekeepers liability limit"),
            ("auto_dealers_inventory_value", "dealer inventory value"),
        ]:
            if not _fv(facts, fk):
                recommendations.append({
                    "rec_id": f"rec_{fk}",
                    "field": fk,
                    "component": "exposure_consistency",
                    "message": f"Garage/dealers supplement missing: {lbl}",
                    "type": "suggestion",
                    "score_impact": 8,
                    "priority": 2,
                })

    elif fid == "ACORD_160":
        # ACORD 160 is the BUSINESS OWNERS section (its template's title; Z37,
        # 24 Oct 2026 - it was scored as an inland marine schedule). A BOP
        # states a property limit, a liability limit and a deductible.
        _bop_parts = [
            ("bop_property_limit",  "BOP property limit"),
            ("bop_liability_limit", "BOP liability limit"),
            ("bop_deductible",      "BOP deductible"),
        ]
        struct = int(sum(1 for fk, _l in _bop_parts if _fv(facts, fk))
                     / len(_bop_parts) * 100)
        for fk, lbl in _bop_parts:
            if not _fv(facts, fk):
                issues.append(f"Business Owners section missing: {lbl}")
                recommendations.append({
                    "rec_id": f"rec_{fk}",
                    "field": fk,
                    "component": "structural_completeness",
                    "message": f"ACORD 160 needs the {lbl}",
                    "type": "missing_field",
                    "score_impact": 10,
                    "priority": 1,
                })

    elif fid == "ACORD_186":
        # Contractors Supplemental: type and subcontract % are required
        contr_chks = [
            bool(_fv(facts, "contractor_type")),
            bool(_fv(facts, "percent_subcontracted")),
        ]
        struct = int(sum(contr_chks) / len(contr_chks) * 100)
        for fk, lbl in [
            ("contractor_type",          "contractor type"),
            ("percent_subcontracted",    "% work subcontracted"),
        ]:
            if not _fv(facts, fk):
                issues.append(f"Contractors Supplement missing: {lbl}")
                recommendations.append({
                    "rec_id": f"rec_{fk}",
                    "field": fk,
                    "component": "structural_completeness",
                    "message": f"ACORD 186 requires {lbl}",
                    "type": "missing_field",
                    "score_impact": 15,
                    "priority": 1,
                })
        for fk, lbl in [
            ("contractor_residential_pct", "residential/commercial work split"),
            ("contractor_high_hazard_ops", "high-hazard operations list"),
            ("contractor_license_number",  "contractor license number"),
        ]:
            if not _fv(facts, fk):
                recommendations.append({
                    "rec_id": f"rec_{fk}",
                    "field": fk,
                    "component": "exposure_consistency",
                    "message": f"Contractors Supplement: add {lbl}",
                    "type": "suggestion",
                    "score_impact": 6,
                    "priority": 2,
                })

    elif fid == "ACORD_127":
        # Business Auto: vehicle schedule + liability limit + garaging + drivers + symbols.
        # Two phantom reads fixed 2026-08-26 (H1 audit): `auto_garaging_address`
        # (singular) is a key nothing writes - the fact is the PLURAL
        # `auto_garaging_addresses` - so a package with garaging extracted
        # still lost this check unless a location schedule happened to exist.
        # And the radius is read through `coverage_evidence.auto_radius_known`,
        # the same three sources the 127 stamper prints from, so a radius that
        # is sitting on the generated form can never count as missing here.
        try:
            from services.coverage_evidence import auto_radius_known as _radius_known
            _has_radius = _radius_known(facts)
        except Exception:                                      # noqa: BLE001
            _has_radius = bool(_fv(facts, "auto_radius_of_operation"))
        # V1 H1 (2026-08-26): the owned-vehicle items leave the DENOMINATOR on a
        # hired/non-owned-only account (C3 3.6's rule, applied to a per-form
        # checklist). The questionnaire marks those five facts Not Applicable
        # and refuses to ask for them, so counting them as gaps docked the form
        # for data nobody can supply and nobody is asked for - the
        # "blank and unaskable" defect this codebase has now fixed three times.
        _owned_na = _owned_vehicle_items_not_applicable(facts, flags)
        chks = [c for c, owned in (
            (bool(_fv(facts, "auto_vin_schedule") or _fv(facts, "vehicle_schedule")), True),
            (_auto_liability_stated(facts), False),
            (bool(_fv(facts, "auto_garaging_addresses") or _fv(facts, "locations")), True),
            (bool(_fv(facts, "auto_drivers")), True),
            (bool(_fv(facts, "auto_covered_symbols")), False),
            (_has_radius, True),
        ) if not (owned and _owned_na)]
        struct = int(sum(chks) / len(chks) * 100) if chks else 100
        if not _fv(facts, "auto_vin_schedule") and not _fv(facts, "vehicle_schedule"):
            recommendations.append({
                "rec_id":      "rec_auto_vin_schedule",
                "field":       "auto_vin_schedule",
                "component":   "structural_completeness",
                "message":     "Provide a vehicle schedule (VIN, year, make/model)",
                "type":        "missing_field",
                "score_impact": 15,
                "priority":    1,
            })

    elif fid == "ACORD_130":
        # Workers Comp: payroll, class codes, X-mod, officer inclusions, count.
        # prior_carrier removed 2026-08-24 (client C2 2.7): a structural
        # checklist cannot see new-venture applicability, so its deduction
        # lives in Loss History only. The spec's 130 checklist listed it; the
        # C2 document takes precedence (see v1-20AUG.md C2-A).
        chks = [
            bool(_fv(facts, "wc_payroll") or _fv(facts, "total_payroll")),
            bool(_fv(facts, "wc_class_codes")),
            bool(_fv(facts, "wc_xmod")),
            bool(_fv(facts, "wc_officer_exclusions")),
            bool(_fv(facts, "num_employees")),
        ]
        struct = int(sum(chks) / len(chks) * 100)
        for fk, lbl in [
            ("wc_payroll",            "WC payroll by class/state"),
            ("wc_class_codes",        "WC class codes"),
            ("wc_xmod",               "experience modification factor (X-mod)"),
            ("wc_officer_exclusions", "owner/officer inclusion/exclusion"),
        ]:
            if not _fv(facts, fk):
                recommendations.append({
                    "rec_id":      f"rec_{fk}",
                    "field":       fk,
                    "component":   "structural_completeness",
                    "message":     f"ACORD 130 requires {lbl}",
                    "type":        "missing_field",
                    "score_impact": 12,
                    "priority":    1,
                })

    elif fid == "ACORD_131":
        # Umbrella / Excess Liability: limit, SIR, underlying limits, EL.
        # "SIR or attachment point" is ONE item, and an excess layer's
        # attachment established by what it sits on meets it (Brent, 23 Oct
        # 2026 - `umbrella_retention_state`); not established = a review flag.
        chks = [
            bool(_fv(facts, "umbrella_limit")),
            *_umbrella_retention_checks(facts, flags),
        ]
        if umbrella_retention_state(facts, flags) == UMB_RETENTION_REVIEW:
            recommendations.append({
                "rec_id":      "rec_umbrella_attachment_review",
                "field":       "umbrella_attachment_point",
                "component":   "structural_completeness",
                "message":     ("Confirm the excess layer's attachment point or underlying "
                                "structure - no separate SIR is needed once it is known"),
                "type":        "suggestion",
                "score_impact": 0,
                "priority":    3,
                "unscored":    True,
            })
        # Employers Liability sits under an umbrella only where Workers
        # Compensation is carried (15 Sep 2026, held since 14 Sep): a no-WC
        # package lost a fifth of this score for a limit it cannot have. A
        # stated EL limit still counts wherever it appears. Since 21 Oct 2026
        # the same rule for GL and auto too, and the umbrella's own schedule
        # decides as well (`_umbrella_underlying_checks`).
        chks += _umbrella_underlying_checks(facts, flags, split_counts=False)
        struct = int(sum(chks) / len(chks) * 100)
        if not _fv(facts, "umbrella_limit"):
            recommendations.append({
                "rec_id":      "rec_umbrella_limit",
                "field":       "umbrella_limit",
                "component":   "structural_completeness",
                "message":     "Provide umbrella/excess limit",
                "type":        "missing_field",
                "score_impact": 20,
                "priority":    1,
            })

    elif fid == "ACORD_28":
        # Evidence of Property: policy number + dates + values + mortgagee.
        # The policy number is the one the form PRINTS (its line's header - a
        # multi-carrier package has no package-level number, 30 Oct 2026).
        chks = [
            bool(_fv(facts, "applicant_name")),
            bool(_fv(facts, "effective_date") and _fv(facts, "expiration_date")),
            _prints_policy_number(facts, mapped_data),
            bool(_fv(facts, "property_building_value") or _fv(facts, "property_bpp_value")),
            bool(_fv(facts, "mortgagee_name") or _fv(facts, "certificate_holder")),
        ]
        struct = int(sum(chks) / len(chks) * 100)

    elif fid == "ACORD_101":
        # Additional Remarks: free-text narrative is the primary value.
        remarks_text = _narrative_remarks_text(facts) or str(_fv(facts, "remarks_text") or "")
        chks = [
            bool(_fv(facts, "applicant_name")),
            bool(_fv(facts, "effective_date")),
            _acord101_names_its_form(facts),
            len(remarks_text) >= 50,
        ]
        struct = int(sum(chks) / len(chks) * 100)
        if len(remarks_text) >= 200:
            struct = min(100, struct + 10)

    else:
        struct = conf_rate

    # OCR confidence penalty
    _ocr_tier1 = list(TIER1_FIELDS.keys()) + list(TIER1_CONTACT)
    ocr_low_count = sum(1 for k in _ocr_tier1 if not _focr(facts, k))
    ocr_penalty = min(30, ocr_low_count * 6)
    struct = max(0, struct - ocr_penalty)
    breakdown["structural_completeness"] = struct

    # ── Exposure consistency ──────────────────────────────────────────────────
    if is_cert_only:
        chks = [
            bool(_fv(facts, "gl_limits") or _fv(facts, "gl_aggregate") or _fv(facts, "gl_each_occurrence")),
            bool(_fv(facts, "policy_number")),
            bool(_fv(facts, "effective_date") and _fv(facts, "expiration_date")),
            bool(_fv(facts, "applicant_name") or _fv(facts, "certificate_holder")),
        ]
        exp_score = int(sum(chks) / len(chks) * 100)

    elif fid == "ACORD_125":
        chks = [
            bool(_fv(facts, "total_revenue") or _fv(facts, "total_payroll")),
            bool(_fv(facts, "operations_description")),
            bool(_fv(facts, "num_employees")),
            bool(_fv(facts, "fein")),
            bool(_fv(facts, "entity_type")),
        ]
        exp_score = int(sum(chks) / len(chks) * 100)
        if _fv(facts, "naics_code") or _fv(facts, "sic_code"):
            exp_score = min(100, exp_score + 5)

    elif fid == "ACORD_126":
        # One reader for each (14 Oct 2026, live run f83757cf: 126 Exposure 60 on a
        # package printing $1,000,000 / $2,000,000 and the code the producer typed).
        # GL class codes through `gl_class_codes_present` (both homes, any shape - a
        # rating schedule or a typed answer counted as "no codes" here, -15), and
        # the GL limits as the 126's own structural check reads them (the composite
        # OR each occurrence OR aggregate - the composite alone is often absent).
        _gl_codes_here = gl_class_codes_present(facts)
        chks = [
            _gl_codes_here,
            bool(_fv(facts, "total_payroll") or _fv(facts, "total_revenue")),
            bool(_fv(facts, "operations_description")),
            bool(_fv(facts, "gl_limits") or _fv(facts, "gl_each_occurrence") or _fv(facts, "gl_aggregate")),
        ]
        exp_score = int(sum(chks) / len(chks) * 100)
        if _gl_codes_here:
            exp_score = min(100, exp_score + 10)
        else:
            exp_score = max(0, exp_score - 15)

    elif fid == "ACORD_140":
        chks = [
            bool(_fv(facts, "valuation_method")),
            bool(_fv(facts, "coinsurance_percentage") or _fv(facts, "property_deductible_aop")),
            bool(_fv(facts, "property_building_value") or _fv(facts, "property_bpp_value")),
            bool(_fv(facts, "occupancy_type")),
        ]
        exp_score = int(sum(chks) / len(chks) * 100)
        if not _fv(facts, "valuation_method"):
            exp_score = max(0, exp_score - 15)
            recommendations.append({
                "rec_id": "rec_valuation_method",
                "field": "valuation_method",
                "component": "exposure_consistency",
                "message": "Specify RCV or ACV valuation method",
                "type": "missing_field",
                "score_impact": 10,
                "priority": 1,
            })

    elif fid == "ACORD_127":
        # The radius through the one reader the 127's structural check uses
        # (`coverage_evidence.auto_radius_known` - a stated radius OR the rating
        # table's radius class, "LOCAL"); the bare fact docked 20 points on a
        # package whose radius the documents state (14 Oct 2026, f83757cf).
        try:
            from services.coverage_evidence import auto_radius_known as _radius_known
            _radius_here = _radius_known(facts)
        except Exception:                                      # noqa: BLE001
            _radius_here = bool(_fv(facts, "auto_radius_of_operation"))
        chks = [
            _auto_liability_stated(facts),
            bool(_fv(facts, "auto_liability_structure")),
            bool(_fv(facts, "auto_covered_symbols")),
            _radius_here,
            bool(_fv(facts, "auto_vin_schedule") or _fv(facts, "vehicle_schedule")),
        ]
        exp_score = int(sum(chks) / len(chks) * 100)

    elif fid == "ACORD_130":
        chks = [
            bool(_fv(facts, "wc_payroll") or _fv(facts, "total_payroll")),
            bool(_fv(facts, "wc_class_codes")),
            bool(_fv(facts, "operations_description")),
            bool(_fv(facts, "num_employees")),
            bool(_fv(facts, "wc_xmod")),
        ]
        exp_score = int(sum(chks) / len(chks) * 100)

    elif fid == "ACORD_131":
        # The GL and auto items only where the umbrella sits over that line or
        # its limit is stated (21 Oct 2026, `_umbrella_underlying_checks`).
        chks = [
            bool(_fv(facts, "umbrella_limit")),
            *_umbrella_underlying_checks(facts, flags, split_counts=True,
                                         families=("general_liab", "auto")),
            *_umbrella_retention_checks(facts, flags),       # Brent, 23 Oct 2026
        ]
        exp_score = int(sum(chks) / len(chks) * 100)

    elif fid == "ACORD_28":
        chks = [
            bool(_fv(facts, "property_building_value") or _fv(facts, "property_bpp_value")),
            _prints_policy_number(facts, mapped_data),
            bool(_fv(facts, "mortgagee_name") or _fv(facts, "certificate_holder")),
            bool(_fv(facts, "effective_date") and _fv(facts, "expiration_date")),
        ]
        exp_score = int(sum(chks) / len(chks) * 100)

    elif fid == "ACORD_101":
        remarks_text = _narrative_remarks_text(facts) or str(_fv(facts, "remarks_text") or "")
        chks = [
            _acord101_names_its_form(facts),
            bool(_fv(facts, "explanation_of_yes_answers") or remarks_text),
            len(remarks_text) >= 100,
        ]
        exp_score = int(sum(chks) / len(chks) * 100)

    else:
        chks = [
            bool(_fv(facts, "total_revenue") or _fv(facts, "total_payroll")),
            bool(_fv(facts, "operations_description")),
        ]
        exp_score = int(sum(chks) / len(chks) * 100)

    breakdown["exposure_consistency"] = exp_score

    # ── Property integrity ────────────────────────────────────────────────────
    _prop_soft = False
    # WHY the property gate fired, in the producer's language.
    #
    # The gate used to surface as the literal strings "Property integrity gate"
    # and "Property integrity warning" - our internal names for a rule, printed
    # to a broker on the pre-form Hard Stops list with no fix control, because
    # `classify_legacy` has no row for either (it cannot: they name nothing).
    # The score sat at 60 with a dead end beside it.
    #
    # Every branch below already KNOWS its own cause, so the gate now carries
    # it. The wording deliberately reuses the phrases `_LEGACY_MESSAGE_RULES`
    # already matches, which is what gives these rows a real "Open to fix"
    # button pointing at the right facts - no new vocabulary, no second table
    # to keep in step. First cause wins, so the sentence is stable across a
    # recompute rather than churning with dict order.
    #
    # Since 19 Oct 2026 the gate is a WARNING only (85): its one hard cause, a
    # missing Period of Restoration, is a warning on Brent's short hard-stop
    # list. Minimum Viable COPE keeps its own 60 (`cope_hard`, below).
    _prop_soft_reason: Optional[str] = None

    def _prop_soft_because(reason: str) -> None:
        nonlocal _prop_soft, _prop_soft_reason
        _prop_soft = True
        if not _prop_soft_reason:
            _prop_soft_reason = reason

    if fid == "ACORD_140":
        prop = struct
        # BI coverage: BI limit present but period of restoration missing - a
        # WARNING since 19 Oct 2026 (Brent: no substitute, blank + flagged; only
        # what is essential to the coverage is a hard stop), so it holds 85.
        if _fv(facts, "business_income_limit") and not _fv(facts, "period_of_restoration") \
                and _por_needed(facts):
            _prop_soft_because(
                "Business income limit present but period of restoration not specified")
            issues.append("Business income limit present but period of restoration not specified")
            recommendations.append({
                "rec_id": "rec_period_of_restoration",
                "field": "period_of_restoration",
                "component": "property_integrity",
                "message": "Provide Period of Restoration for Business Income coverage",
                "type": "soft_warning",
                "score_impact": 0,
                "priority": 1,
            })
        # Valuation method soft block
        if not _fv(facts, "valuation_method"):
            # The gate sentence uses the LEGACY RULE's phrasing ("... not
            # specified", no "(RCV/ACV)" between) so `classify_legacy` matches
            # it and the row gets its valuation-method fix. `issues` keeps its
            # own long-standing wording - that list is display-only.
            _prop_soft_because("Property valuation method not specified")
            issues.append("Property valuation method (RCV/ACV) not specified")
            recommendations.append({
                "rec_id": "rec_valuation_method_prop",
                "field": "valuation_method",
                "component": "property_integrity",
                "message": "Select valuation method: Replacement Cost Value (RCV) or Actual Cash Value (ACV)",
                "type": "soft_warning",
                "score_impact": 8,
                "priority": 1,
            })
        # ── SAME ONE RULE AS evaluate_stops (2026-09-23) ────────────────
        # `property_has_peril_deductibles` means the document showed a wind/hail
        # OR earthquake OR flood deductible - ONE is enough. Demanding all three
        # capped an ordinary wind-only policy at 60 and asked for amounts for
        # perils it does not carry. This was the FOURTH and FIFTH copy of that
        # rule (evaluate_stops and two in cross_form_validator were the others);
        # they were found by the anti-rot test written for the first three,
        # which is the only reason they did not survive the fix.
        # Fires only on the satisfiable gap - referenced, nothing captured - and
        # WARNS rather than blocking, per the client ruling this file records
        # three times for the property family.
        if flags.get("property_has_peril_deductibles") and not any(
            _fv(facts, k) for k in (
                "property_deductible_wind",
                "property_deductible_earthquake",
                "property_deductible_flood",
            )
        ):
            _prop_soft_because(
                "Peril-specific deductibles referenced but not defined")
            issues.append(
                "Peril-specific deductibles referenced but not defined")
            recommendations.append({
                "rec_id": "rec_peril_deductibles",
                "field": "property_deductible_wind",
                "component": "property_integrity",
                "message": ("State the deductible for each peril this policy "
                            "actually carries"),
                "type": "soft_warning",
                "score_impact": 5,
                "priority": 2,
            })
        # Coinsurance: if value present but coinsurance missing → soft block
        from services.coverage_evidence import agreed_value_affirmed as _agreed_value_affirmed
        if (_fv(facts, "property_building_value") or _fv(facts, "property_bpp_value")) and \
                not _fv(facts, "coinsurance_percentage") and not _agreed_value_affirmed(facts):
            _prop_soft_because("Coinsurance percentage not specified for insured property")
            issues.append("Coinsurance percentage not specified for insured property")
            recommendations.append({
                "rec_id": "rec_coinsurance",
                "field": "coinsurance_percentage",
                "component": "property_integrity",
                "message": "Provide coinsurance percentage or confirm agreed value endorsement",
                "type": "soft_warning",
                "score_impact": 6,
                "priority": 2,
            })

    elif fid != "ACORD_140" and flags.get("has_property_coverage"):
        min_ok = all([
            bool(_fv(facts, "locations")),
            bool(_fv(facts, "occupancy_type")),
            bool(_fv(facts, "construction_type")),
            bool(_fv(facts, "property_building_value") or _fv(facts, "property_bpp_value")),
        ])
        if not min_ok:
            prop = 0
            issues.append("Minimum Viable COPE incomplete")
        else:
            _p_t1 = ["year_built", "roof_year", "sprinkler_system", "fire_protection_class"]
            _p_t2 = ["distance_to_hydrant", "fire_department_type", "business_income_limit", "period_of_restoration"]
            prop = 60 + sum(bool(_fv(facts, k)) for k in _p_t1) * 5 + sum(_cope_tier_ok(facts, k) for k in _p_t2) * 5
    else:
        prop = 100

    # Property delta penalties (non-140/141 forms that have property exposure)
    if fid != "ACORD_140" and flags.get("has_property_coverage"):
        from services.coverage_evidence import agreed_value_affirmed as _agreed_value_affirmed_any
        if not _fv(facts, "valuation_method"):
            prop = max(0, prop - 5)

        # Only on a form that PRINTS Business Income (the BOP section, the
        # evidence of property) - 5 Oct 2026, generality audit G2: CH125's 125 /
        # 126 / 127 were each capped at 85 for a period-of-restoration box none
        # of them has.
        if fid in _BI_PRINTING_FORMS and _fv(facts, "business_income_limit") \
                and not _fv(facts, "period_of_restoration") and _por_needed(facts):
            _prop_soft_because(
                "Business income limit present but period of restoration not specified")
            issues.append("BI coverage present but period of restoration not specified")

        # ── SAME ONE RULE AS evaluate_stops (2026-09-23) ────────────────
        # `property_has_peril_deductibles` means the document showed a wind/hail
        # OR earthquake OR flood deductible - ONE is enough. Demanding all three
        # capped an ordinary wind-only policy at 60 and asked for amounts for
        # perils it does not carry. This was the FOURTH and FIFTH copy of that
        # rule (evaluate_stops and two in cross_form_validator were the others);
        # they were found by the anti-rot test written for the first three,
        # which is the only reason they did not survive the fix.
        # Fires only on the satisfiable gap - referenced, nothing captured - and
        # WARNS rather than blocking, per the client ruling this file records
        # three times for the property family.
        if flags.get("property_has_peril_deductibles") and not any(
            _fv(facts, k) for k in (
                "property_deductible_wind",
                "property_deductible_earthquake",
                "property_deductible_flood",
            )
        ):
            _prop_soft_because(
                "Peril-specific deductibles referenced but not defined")
            issues.append(
                "Peril-specific deductibles referenced but not defined")

        if (
            (_fv(facts, "property_building_value") or _fv(facts, "property_bpp_value"))
            and not _fv(facts, "coinsurance_percentage")
            and not _agreed_value_affirmed_any(facts)
        ):
            prop = max(0, prop - 5)
            issues.append("Coinsurance percentage not specified for insured property")

    breakdown["property_integrity"] = max(0, prop)

    # ── Loss history alignment (with new tiers, recency, insured-match) ────────
    loss_score, loss_recs = calculate_p4_loss_history(
        facts, flags,
        has_loss_run_doc=has_loss_run_doc,
        loss_run_match=loss_run_match,
    )
    _loss_doc_phrases = ("no loss history provided", "loss runs", "required for carrier")
    for rec_msg in loss_recs:
        # A STATUS NOTICE IS NOT A CARD (owner, 14 Oct 2026, run 0353c36b): "No
        # Known Losses attested - Loss History is Not Applicable ..." sat on all
        # ten forms' side panels and in the download screen's "items to fix" -
        # the producer's own answer read back to him ten times. The score panel
        # already says it on the Loss History row ("Not applicable - No Known
        # Losses attested"). The three notices stay in `loss_recs` (the pillar's
        # own record); they are never a card.
        if rec_msg in _LOSS_NOT_APPLICABLE_NOTICES:
            continue
        # C2 2.1 (found on the 2026-08-24 live run): an "Underwriting advisory
        # (no score effect)" card - and the informational New Venture notices -
        # must not carry the typed +8 literal. The chip ("up to +8 pts") would
        # contradict the card's own text, and dismissing it with a reason would
        # CREDIT points an advisory can never earn back (impact measurement
        # skips field-less recs, so the literal survived un-corrected).
        # The attested-N/A notice (29 Sep 2026) joins them: it describes a
        # pillar removed from the score, so there is nothing to earn.
        # The under-a-year notice was missing from this list and carried the
        # typed +8 at priority 2 (found 1 Oct 2026) - matched by identity now.
        _status_note = rec_msg in _LOSS_NOT_APPLICABLE_NOTICES
        _no_impact = _status_note or rec_msg.lower().startswith(
            ("underwriting advisory", "new venture status conflicts"))
        recommendations.append({
            "rec_id": _loss_rec_id(rec_msg),
            # Was hardcoded "loss_history_years" for EVERY loss message, so the
            # "confirm No Known Losses" card wrote the attestation into a year
            # count and the score could never move. See
            # _LOSS_RECOMMENDATION_FIELDS.
            "field": loss_recommendation_field(rec_msg, facts),
            "component": "loss_history_alignment",
            "message": rec_msg,
            "type": "suggestion",
            "score_impact": 0 if _no_impact else 8,
            "priority": 3 if _no_impact else 2,
            # A status notice, not a gap: its card says so instead of asking
            # for a document (answer_routing.NOTE_INFORMATIONAL).
            "informational": bool(_no_impact) and not loss_recommendation_field(rec_msg, facts),
            # A status note about the score, not a gap (1 Oct 2026): kept off
            # the underwriter cover. See _LOSS_NOT_APPLICABLE_NOTICES.
            **({"unscored": True} if _status_note else {}),
            # Structured flag so requires_supporting_document detection in arq_service
            # doesn't rely on keyword scanning of message strings.
            "requires_doc": any(p in rec_msg.lower() for p in _loss_doc_phrases),
        })
    breakdown["loss_history_alignment"] = loss_score

    # ── Umbrella / limit adequacy (None = N/A, weights re-normalised) ────────
    umbrella_score = _calculate_umbrella_adequacy(facts, flags)
    if flags.get("has_umbrella") and umbrella_score is not None and umbrella_score == 0:
        # THE PILLAR REACHES 0 TWO WAYS, AND THIS BLOCK USED TO CLAIM ONLY ONE.
        # `_calculate_umbrella_adequacy` returns 0 either because there genuinely
        # are no underlying limits, or because ordinary deductions stacked past
        # 100 on a package whose underlying limits are all stated. The 60-cap
        # gate was corrected for exactly this on 2026-08-31 via the shared
        # `_umbrella_has_underlying` door; this sibling was left behind, so a
        # LIVE RUN (2026-09-08) printed both on one screen:
        #     HARD STOPS: "...its supporting detail is incomplete..."   (true)
        #     Key Issues: "Umbrella detected but no underlying GL/Auto limits"
        # on a package plainly stating $300,000 GL each occurrence and $300,000
        # auto CSL. The card was worse than the sentence: it asked the producer
        # to "Provide underlying limits" - values already on file - while the
        # actually-missing figure, the umbrella limit itself, went unasked.
        #
        # Reads the SAME door, never a second copy of the test.
        _has_underlying = _umbrella_underlying_stated(facts)
        if not _has_underlying:
            issues.append("Umbrella detected but no underlying GL/Auto limits")
            # The box of the first line the umbrella sits over (21 Oct 2026): an
            # umbrella over employers liability only asks for the EL limit.
            _umb_box = umbrella_underlying_box(facts, flags)
            recommendations.append({
                "rec_id": "rec_underlying_limits",
                "field": ("gl_limits" if _umb_box == UMB_UNDERLYING_FACT["general_liab"]
                          else _umb_box),
                "component": "umbrella_limit_adequacy",
                "message": "Provide underlying limits",
                "type": "hard_stop",
                "score_impact": 0,
                "priority": 1,
            })
        else:
            # Underlying IS stated. Say what is actually missing, and ask for
            # the fact whose absence is the largest single deduction.
            issues.append(
                "Umbrella supporting detail is incomplete - umbrella limit, "
                "schedule of underlying insurance and follow-form status"
            )
            recommendations.append({
                "rec_id": "rec_umbrella_supporting_detail",
                "field": "umbrella_limit",
                "component": "umbrella_limit_adequacy",
                "message": "Provide the umbrella limit and confirm the schedule "
                           "of underlying insurance and follow-form status",
                "type": "soft_warning",
                "score_impact": 0,
                "priority": 1,
            })
            # The remaining shortfalls still deserve their own warnings - the
            # `< 100` branch below is skipped on this path, and without this the
            # producer would be told about the umbrella limit and nothing else.
            for w in _build_umbrella_warnings(facts, flags, umbrella_score):
                issues.append(w)
    elif flags.get("has_umbrella") and umbrella_score is not None and umbrella_score < 100:
        # Use the SAME shared builder as the package scorers so the per-form path
        # can never drift from the package warning set. This adds the Employers
        # Liability and missing-Schedule-of-Underlying warnings the inline block
        # previously omitted (per-form/package parity fix).
        for w in _build_umbrella_warnings(facts, flags, umbrella_score):
            issues.append(w)
    breakdown["umbrella_limit_adequacy"] = umbrella_score  # None for N/A

    # ── Narrative quality with §6.3 component model ───────────────────────────
    narrative_score, _narrative_components, _narr_substance = _calculate_narrative_quality(
        facts, has_narrative_doc=has_narrative_doc, flags=flags,
        narrative_doc_text=narrative_doc_text,
        form_ids=selected_form_ids,
    )
    breakdown["narrative_quality"] = narrative_score

    # §6.3 AC#4: per-component gap as a targeted recommendation - whenever the
    # pillar deducts (G18, 30 Oct 2026: it waited for < 80, so ACORD 130 sat at
    # 98 with a narrative at 89 and nothing to answer).
    if _narrative_components and narrative_score < 100:
        _absent_comps = [
            NARRATIVE_COMPONENT_LABELS[k]
            for k, present in _narrative_components.items()
            if not present
        ]
        if _absent_comps:
            _comp_msg = _narrative_gap_message(_narrative_components)
            recommendations.append({
                # `additional_remarks_text`, NOT `acord101_remarks`. Both feed
                # `_calculate_narrative_quality`, but only the first is a
                # WRITABLE canonical fact - `acord101_remarks` is a legacy
                # read-only alias, so `_canonical_key` returns None for it and
                # the producer-answer door refused every submission with "This
                # item can't be answered directly" while the card kept offering
                # the box (reported live 2026-09-08). `answer_routing` now
                # classifies this as `narrative`, so the typed text is APPENDED
                # to the ACORD 101 remarks instead of overwriting them.
                "rec_id":       "rec_narrative_components",
                "field":        "additional_remarks_text",
                "component":    "narrative_quality",
                "message":      _comp_msg,
                "type":         "missing_field",
                "score_impact": max(5, min(20, len(_absent_comps) * 3)),
                "priority":     2,
            })
        elif _narr_substance < 30:
            # All components present but narrative is shallow - flag thin content
            recommendations.append({
                "rec_id":       "rec_narrative_substance",
                # Same correction as rec_narrative_components above.
                "field":        "additional_remarks_text",
                "component":    "narrative_quality",
                "message":      (
                    "Narrative covers all required topics but lacks underwriting depth - "
                    "add specific risk details, loss context, and market considerations"
                ),
                "type":         "quality",
                "score_impact": 10,
                "priority":     3,
            })

    # ── Weighted score (re-normalise if umbrella is N/A) ──────────────────────
    weights = {
        "structural_completeness": 0.25,
        "exposure_consistency":    0.25,
        "property_integrity":      0.15,
        "loss_history_alignment":  0.15,
        "umbrella_limit_adequacy": 0.10,
        "narrative_quality":       0.10,
    }
    # Generic N/A rescaling (client C2 2.2): umbrella_limit_adequacy is None
    # with no umbrella and loss_history_alignment is None for a verified new
    # venture - any None pillar drops out and the rest rescale proportionally.
    raw_score = _weighted_pillar_sum(breakdown, weights)

    # ── Cap gates ─────────────────────────────────────────────────────────────
    # On 140 the property pillar is 0 exactly when Minimum Viable COPE is
    # missing (`struct = 0`; otherwise it starts at a 60 floor) - one of Brent's
    # hard-stop kinds. 133 (WC) and 141 (Crime) are not COPE forms (Z37).
    cope_hard = fid == "ACORD_140" and breakdown["property_integrity"] == 0
    # ── THE UMBRELLA GATE BLOCKS ONLY THE BROKEN TOWER (2026-09-23) ─────────
    # This was `umbrella_score == 0` alone, which caps the FORM at 60. But the
    # umbrella pillar starts at 100 and subtracts up to 135 points across seven
    # deductions (-25 missing umbrella limit, -20 GL occurrence, -20 GL
    # aggregate, -20 auto CSL, -25 EL, -15 no schedule of underlying, -10
    # follow-form unconfirmed), so it reaches 0 by ACCUMULATION on packages
    # whose underlying limits are all present and stated. Two of those seven
    # fire on nearly every submission.
    #
    # That contradicted a ruling recorded three times in this very file -
    # "underlying limits below the umbrella baseline must be a WARNING + score
    # reduction, NOT a hard stop. Carrier attachment points vary, so we never
    # block" (client Q1/Q2, and an entry was DELETED from
    # `_ALWAYS_HARD_PATTERNS` for exactly this reason). The ruling was honoured
    # inside the pillar and undone by the gate that reads it. Brent sanctioned
    # the REDUCTIONS; nobody sanctioned the 60 cap.
    #
    # `_umbrella_has_underlying` is the existing ONE DOOR that separates the two
    # ways the pillar reaches 0, and the cap's own reason sentence already reads
    # from it. Now the cap does too: a genuinely broken tower (umbrella with no
    # underlying GL or Auto limit) still caps at 60 - and that case additionally
    # has its own hard stop in `evaluate_stops`, so it is never silent -
    # while accumulated deductions stay what the client asked for, a pillar
    # reduction. SCORES GO UP on umbrella packages with real underlying limits.
    # D6 - Brent sees the numbers.
    #
    # 19 Oct 2026 (Brent's short hard-stop list): of the two sentences this gate
    # can print, only "no underlying limits" is a hard stop (60). An underlying
    # limit stated in words ("Included", "See schedule") with the pillar at 0 is
    # "supporting detail incomplete" - its card is a warning, so it holds 85.
    umb_fail = (
        flags.get("has_umbrella")
        and umbrella_score is not None
        and umbrella_score == 0
        and not _umbrella_has_underlying(facts)
    )
    _umb_unstated = bool(umb_fail) and not _umbrella_underlying_stated(facts)

    # Preserve the UNCAPPED score before the ceiling is applied (2026-08-16).
    # It used to be overwritten, so a capped form score could not be told apart
    # from a genuinely low one, and later credits had to compound off the capped
    # value instead of the real one.
    raw_uncapped = max(0, min(100, raw_score))
    # ── A 60 CAP IS A HARD STOP, AND IT MUST SAY SO ──────────────────────────
    # These gates live OUTSIDE hard_stops/soft_stops, so they capped the form
    # at 60 while the Hard Stops list stayed empty and nothing on screen
    # explained the number (reported live 2026-08-31: three forms pinned at 60,
    # zero hard stops, warnings only). The reason is returned in
    # `cap_hard_stops` / `cap_soft_stops` below so the UI can render it as the
    # stop it already is.
    #
    # The umbrella wording used to be a single string claiming "no underlying
    # GL or Auto limits". `_calculate_umbrella_adequacy` reaches 0 two ways -
    # genuinely no underlying, or ordinary deductions stacking past 100 - so on
    # a package carrying both limits the printed reason was simply false. It now
    # names the real cause via the shared `_umbrella_underlying_stated` door.
    _gate_hard_reason = (
        "Minimum Viable COPE incomplete" if cope_hard else
        "Umbrella present with no underlying GL or Auto limits" if _umb_unstated else
        _form_download_blocker(_scored_form_id or fid, mapped_data, confidence_dict)
    )
    _gate_soft_reason = (
        "Umbrella coverage is present but its supporting detail is incomplete - "
        "umbrella limit, underlying limits, schedule of underlying insurance "
        "and follow-form status"
        if umb_fail and not _umb_unstated else
        # Was the literal "Property integrity warning" - our internal rule name,
        # printed to a broker. Every branch that raises this gate supplies its
        # own cause (`_prop_soft_because`), phrased so `classify_legacy` matches
        # it and the row gets a real fix control. The fallback only fires if a
        # future branch sets the flag without a reason, and it still says
        # something a broker can act on.
        (_prop_soft_reason
         or "Property details are incomplete - review the property section")
        if _prop_soft else None)
    if not _gate_soft_reason and not _simulate:
        _gate_soft_reason = _form_open_warning(
            _scored_form_id or fid, mapped_data if _form_boxes else None, confidence_dict,
            form_schema if _form_boxes else None, facts, flags, cross_issues_full)
    cap_applied, cap_reason = _resolve_cap(
        hard_stops, soft_stops,
        extra_hard_reason=_gate_hard_reason,
        extra_soft_reason=_gate_soft_reason,
    )
    if cap_applied is not None:
        raw_score = min(raw_score, cap_applied)

    # Surface the gate ONLY when it is what actually bound the score and no
    # existing hard stop already says it. `_resolve_cap` appends the gate LAST,
    # so `cap_reason == _gate_hard_reason` means hard_stops was empty - i.e.
    # there is no card on screen for this cap. Display only: nothing here
    # re-scores, and hard_stops/soft_stops (which drive every other cap, the
    # dismiss credit and issue_id hashing) are never mutated.
    cap_hard_stops: List[str] = []
    if (cap_applied == HARD_STOP_CAP and _gate_hard_reason
            and cap_reason == _gate_hard_reason
            and _gate_hard_reason not in (hard_stops or [])):
        cap_hard_stops.append(_gate_hard_reason)
        if _gate_hard_reason not in issues:
            issues.append(_gate_hard_reason)

    # ── AND AN 85 MUST NAME ITSELF TOO (2026-09-23) ─────────────────────────
    # `_resolve_cap`'s `extra_soft_reason` lives OUTSIDE `soft_stops` exactly as
    # `extra_hard_reason` lives outside `hard_stops`, so a form held at 85 by a
    # soft gate carried its reason only in `cap_reason` - a field no surface
    # prints. Same contract as the hard half, deliberately: populated ONLY when
    # this gate is what actually bound the score (`cap_reason ==
    # _gate_soft_reason` proves `soft_stops` was empty, because `_resolve_cap`
    # appends the gate last) and only when no existing card already carries
    # the sentence. DISPLAY ONLY - no score moves.
    cap_soft_stops: List[str] = []
    if (cap_applied == SOFT_STOP_CAP and _gate_soft_reason
            and cap_reason == _gate_soft_reason
            and _gate_soft_reason not in (soft_stops or [])):
        cap_soft_stops.append(_gate_soft_reason)
        if _gate_soft_reason not in issues:
            issues.append(_gate_soft_reason)

    # fraud_penalty is applied AFTER the cap, exactly as before. It is currently
    # always 0 (never assigned anywhere), so this ordering is behaviour-neutral -
    # it is preserved rather than "improved" so nothing shifts silently.
    raw_score = max(0, raw_score - fraud_penalty)

    # ── Tier and routing ──────────────────────────────────────────────────────
    # Single tier ladder (tier_for_score), shared with the package scorer and
    # audit_routes, so the form chip and the package chip can never disagree. An
    # open hard stop of this form - its list and a hard gate with no card of its
    # own - blocks its "Submission Ready" (19 Oct 2026) as well as holding 60.
    _blockers = [str(m) for m in (hard_stops or []) if m] + list(cap_hard_stops)
    _grade_label, tier, tc = tier_for_score(raw_score, len(_blockers))
    routing = routing_for_score(raw_score, len(_blockers))

    # ── What each recommendation is ACTUALLY worth ────────────────────────────
    # Replaces the hand-typed score_impact literals with a measurement. See
    # _measure_recommendation_impacts for why, and for the three things it
    # refuses to do. Runs before the sort so the ordering uses the real numbers -
    # the biggest genuine win leads, which the typed literals could not deliver.
    if not _simulate:
        _rec_gains: dict = {}
        _rec_impacts = _measure_recommendation_impacts(
            recommendations, raw_uncapped, breakdown, weights,
            lambda _probed_facts: calculate_sqs(
                facts=_probed_facts, flags=flags, mapped_data=mapped_data,
                form_schema=form_schema, selected_form_ids=selected_form_ids,
                hard_stops=hard_stops, soft_stops=soft_stops,
                tier2_score=tier2_score, form_id=form_id,
                schema_size=schema_size, fields_mapped=fields_mapped,
                confidence_dict=confidence_dict,
                has_narrative_doc=has_narrative_doc,
                has_loss_run_doc=has_loss_run_doc,
                loss_run_match=loss_run_match,
                cross_issues_full=cross_issues_full,
                narrative_doc_text=narrative_doc_text,
                _simulate=True,
            ).get("raw_sqs_score"),
            facts,
            measured_out=_rec_gains,
        )
        for _rec in recommendations:
            _measured = _rec_impacts.get(id(_rec))
            if _measured is None:
                continue
            # What the package needs to put ONE number on this card (1 Oct
            # 2026, item 19): the typed literal, and whether the probe moved
            # THIS form - proof the probe has the right shape for the field.
            _rec["declared_impact"] = _rec.get("score_impact")
            _g = _rec_gains.get(_rec.get("field")) if _rec.get("field") else None
            _rec["impact_measured"] = bool(_g is not None and _g > 0)
            _rec["score_impact"], _rec["impact_is_exact"] = _measured
            # A ceiling means the points are EARNED but may not be DISPLAYED
            # until the stop clears, so the card must keep hedging.
            if cap_applied is not None:
                _rec["impact_is_exact"] = False

    # Priority 1 = most urgent (hard stops, tier-1 gaps). Sort ASCENDING on
    # priority so critical items lead; within a priority, higher score_impact
    # first. The previous "-priority" inverted this and sorted priority-2 items
    # ABOVE priority-1 (critical recommendations sank to the bottom).
    recommendations.sort(key=lambda r: (r.get("priority", 99), -r.get("score_impact", 0)))
    # Give every answerable card the same choices the questionnaire offers -
    # a closed question must never be a bare text box (owner 2026-08-24).
    try:
        from services.answer_options import attach_answer_controls
        attach_answer_controls(recommendations)
    except Exception as _aoe:                                 # noqa: BLE001
        logger.warning("answer controls not attached to recommendations: %s", _aoe)
    risk_drivers = [
        {"component": k.replace("_", " ").title(), "score": v}
        for k, v in sorted(
            {k: v for k, v in breakdown.items() if v is not None and v < 90}.items(),
            key=lambda x: x[1]
        )[:3]
    ]

    # §6 enrichment (additive - never breaks existing callers)
    _umbrella_state = _get_umbrella_state(facts, flags)
    _loss_state     = _get_loss_history_state(facts, flags, has_loss_run_doc, loss_run_match)
    _follow_form    = _get_follow_form_status(facts)
    _ev_labels      = _derive_evidence_labels(facts, cross_issues=cross_issues_full, flags=flags, has_loss_run_doc=has_loss_run_doc)
    _pos_signals    = _compute_positive_signals(facts, flags, has_narrative_doc, has_loss_run_doc)
    # Per-form breakdown is display-only and currently not rendered (the UI shows
    # the package-level breakdown from calculate_package_sqs). Forward the one real
    # scoring input this scope actually has (conf_rate) so the Supporting-Docs sub-row
    # is accurate if ever surfaced. exposure_subscores/doc_types are deliberately NOT
    # passed: the per-form scorer uses a form-type-specific structural/exposure model
    # and never computes them, so those sub-rows remain facts-derived proxies here.
    _cat_breakdown  = _compute_category_breakdown(
        facts, flags, cross_issues=cross_issues_full, conf_rate=conf_rate,
    )
    _cat_breakdown["loss_history_alignment"]["loss_history"]["score"]  = loss_score
    _cat_breakdown["loss_history_alignment"]["loss_history"]["status"] = (
        "not_applicable" if loss_score is None
        else ("ok" if loss_score >= 80 else ("partial" if loss_score >= 40 else "insufficient"))
    )
    _cat_breakdown["umbrella_limit_adequacy"]["umbrella_limits"]["score"] = umbrella_score
    _cat_breakdown["umbrella_limit_adequacy"]["umbrella_limits"]["status"] = (
        "not_applicable" if umbrella_score is None else ("ok" if umbrella_score >= 80 else "needs_review")
    )
    _cat_breakdown["narrative_quality"]["narrative_quality"]["score"]  = narrative_score
    _cat_breakdown["narrative_quality"]["narrative_quality"]["status"] = (
        "ok" if narrative_score >= 70 else ("partial" if narrative_score >= 40 else "insufficient")
    )

    # C3 Desired Outcome, per FORM as well as per submission (owner ruling
    # 2026-08-25: "for both per form score as well as package wherever
    # applicable"). `structural_parts` is deliberately absent here: per-form
    # Structural is that form's own ACORD checklist, not the Tier 1 / Tier 2 /
    # fill blend - spec sections 3.1 and 10 both state the two formulas side by
    # side, and C3 3.2 modifies only the submission one.
    # EVERY DEDUCTION HAS ITS CARD (30 Oct 2026, Choice Electric live 6823e106:
    # ACORD 28 at 73 and the excess 131 at 98 with nothing to answer).
    try:
        recommendations = list(recommendations) + _cards_for_uncarded_pillars(
            fid, breakdown, recommendations, facts, flags, mapped_data)
    except Exception as _ucx:                                  # noqa: BLE001
        logger.debug("uncarded pillar cards skipped: %s", _ucx)
    _score_trace = build_score_trace(
        pillars=breakdown,
        weights=weights,
        raw_uncapped=raw_uncapped,
        cap_applied=cap_applied,
        cap_reason=cap_reason,
        displayed=raw_score,
    )

    return {
        "sqs_score":           raw_score,
        # Cap audit trail (2026-08-16) - see calculate_package_sqs for the rule.
        "raw_sqs_score":       raw_uncapped,
        "cap_applied":         cap_applied,
        "cap_reason":          cap_reason,
        # Gate-only 60 caps that have no entry in hard_stops - rendered by the
        # UI as hard stops so a held score is never unexplained (2026-08-31).
        "cap_hard_stops":      cap_hard_stops,
        # ...and CLICKABLE (2026-09-08). Naming the cause is half the job; a
        # blocker holding the score at 60 with nothing to click is the other
        # half of the same defect. Each sentence is classified through the SAME
        # table every other legacy stop uses, so the row carries the identical
        # "Open to fix" the pre-form banners do.
        "cap_hard_stop_items": _cap_stop_items(cap_hard_stops,
                                               coded_issues=cross_issues_full, facts=facts),
        # The 85 half of the same contract (2026-09-23). Same shape, so a
        # display surface renders it with the code it already has for the 60.
        "cap_soft_stops":      cap_soft_stops,
        "cap_soft_stop_items": _cap_stop_items(cap_soft_stops,
                                               coded_issues=cross_issues_full, facts=facts),
        # The form's open hard stops (each holds the 60 and blocks its
        # "Submission Ready") - `readiness_fields`.
        **readiness_fields(raw_score, _blockers, coded_issues=cross_issues_full, facts=facts),
        "score_trace":         _score_trace,
        "tier":                tier,
        "tier_color":          tc,
        "grade":               _grade_label,   # from the shared tier ladder
        "routing_decision":    routing,
        "breakdown":           breakdown,   # umbrella_limit_adequacy may be None
        "risk_drivers":        risk_drivers,
        "issues":              issues,
        "recommendations":     _route_recommendations(recommendations, facts),
        "fraud_penalty":       fraud_penalty,
        "fill_rate":           fill_rate,
        "match_score":         fill_rate,   # §6.1 AC#1: raw field coverage — distinct from SQS and confidence_fill_rate
        "confidence_fill_rate": conf_rate,
        "extraction_confidence": conf_rate,  # AI fill quality - same value, distinct label per client spec
        # The copy that was scored (a form's second copy keeps its own id).
        "form_id":             _scored_form_id or fid,
        "compliance_checklist": risk_transfer_check(facts, flags, selected_form_ids),
        "timestamp":           datetime.utcnow().isoformat() + "Z",
        "model_version":       SQS_MODEL_VERSION,
        "session_id":          session_id,
        "user_id":             user_id,
        "calculation_stage":   calculation_stage,
        # §6 additions
        "umbrella_state":      _umbrella_state,
        "loss_history_state":  _loss_state,
        # Client 5-bucket view (Image 28 item 3) — derived, additive.
        "loss_history_state_client":       _client_loss_state(_loss_state),
        "loss_history_state_client_label": CLIENT_LOSS_STATE_LABELS.get(
            _client_loss_state(_loss_state), "Unknown"),
        "follow_form":         _follow_form,
        "evidence_labels":     _ev_labels,
        "positive_signals":    _pos_signals,
        "category_breakdown":  _cat_breakdown,
        "narrative_components": _narrative_components,
        "loss_run_match":      loss_run_match,
    }


# ── Narrative generation ──────────────────────────────────────────────────────

async def generate_sqs_narrative(
    sqs_result: dict,
    delta_this_session: int,
    resolved_recs: List[str],
    ignored_recs: List[str],
    advisories: Optional[List[str]] = None,
) -> str:
    """
    Generate narrative prose explaining SQS score.
    Called at download only. Uses llama-3.3-70b-versatile.
    """
    score = sqs_result.get("sqs_score") or sqs_result.get("package_sqs_score")
    tier  = sqs_result.get("tier")
    try:
        from config.settings import groq_chat, LLM_MODEL

        breakdown    = sqs_result.get("breakdown", {})
        risk_drivers = sqs_result.get("risk_drivers", [])
        if not risk_drivers:
            # Package results carry top_recommendations (dicts) instead of the
            # per-form risk_drivers list - surface their messages as drivers so
            # the prose still knows what the main gaps are. Never let a raw
            # dict repr leak into the prompt.
            risk_drivers = [
                (r.get("message") if isinstance(r, dict) else str(r))
                for r in (sqs_result.get("top_recommendations") or [])
                if (r.get("message") if isinstance(r, dict) else str(r))
            ]

        # The score/tier line is CONTEXT for the model, not content to repeat:
        # the UI renders the live number itself ("Score at download"), and prose
        # that restates a number can only ever agree by luck - the 66-vs-63
        # contradiction the client screenshotted was exactly that. The prose is
        # therefore forbidden from stating score, tier, or point totals.
        prompt = f"""Summarize this insurance submission quality in one concise paragraph (60-80 words). Be direct and professional.

Score: {score}/100 ({tier}) | Change this session: {'+' if delta_this_session >= 0 else ''}{delta_this_session} pts
Top risk drivers: {', '.join(str(r) for r in risk_drivers[:3]) if risk_drivers else 'none'}
Resolved: {', '.join(resolved_recs) if resolved_recs else 'none'} | Ignored: {', '.join(ignored_recs) if ignored_recs else 'none'}
Underwriting advisories (no score effect, the underwriter will see them): {'; '.join(advisories[:3]) if advisories else 'none'}

One paragraph only. If any underwriting advisory is listed, name the most important one; never say there are no risk drivers, no issues or nothing outstanding while an advisory is listed. State the main gap and the single most impactful next action. Do NOT repeat the numeric score, the tier name, or any point totals in your answer - the interface displays those separately, and a restated number that drifts from the displayed one reads as a contradiction."""

        raw = await groq_chat(
            LLM_MODEL,
            [{"role": "user", "content": prompt}],
            max_tokens=1024,
        )
        return raw.strip()

    except Exception as ex:
        logger.error(f"generate_sqs_narrative failed: {ex}")
        return f"SQS Score: {score}/100 ({tier}). Session improvement: {'+' if delta_this_session >= 0 else ''}{delta_this_session} points."


# ── Clarity pipeline (facts-only SQS) ────────────────────────────────────────

FORM_FIELD_INVENTORY: Dict[str, List[str]] = {
    "ACORD_125": [
        "applicant_name", "dba_name", "mailing_address", "physical_address",
        "fein", "entity_type", "effective_date", "expiration_date",
        "lines_of_business", "contact_name", "contact_phone", "contact_email",
        "producer_name", "total_revenue", "total_payroll", "num_employees",
        "operations_description", "years_in_business", "naics_code", "sic_code",
        "prior_carrier", "policy_number",
    ],
    "ACORD_126": [
        "gl_limits", "gl_each_occurrence", "gl_aggregate", "gl_deductible",
        "gl_class_codes_by_location", "gl_form_type", "retro_date",
        "operations_description", "total_revenue", "total_payroll",
        "additional_named_insureds",
    ],
    # ADDED 2026-08-26 - ACORD 127 was the ONLY form with no inventory at all.
    # Measured live (C4 test S3): a Business Auto package asked the client for
    # vehicles and drivers but asked NOBODY for the auto liability limit, the
    # comprehensive / collision deductibles, the physical-damage valuation or
    # the covered-auto symbols. The coverage-guarantee injector walks this
    # table, so an empty entry meant no auto question could ever be generated.
    # The four structural entries are producer-only under master-plan 4.9 and
    # route to Agency through `question_eligibility.INSURANCE_JUDGMENT_FACTS`.
    "ACORD_127": [
        "auto_vin_schedule", "auto_drivers", "auto_garaging_addresses",
        "auto_radius_of_operation",
        # V1 H1 6.3 (2026-08-26): the fifth Auto Completeness item.
        "auto_vehicle_use",
        # V1 H1 6.3: "Questionnaire behavior should instead focus on the
        # applicable HNOA exposure." The two facts behind ACORD 127's own
        # Hired / Non-Owned boxes (Vehicle_HiredIndicator /
        # Vehicle_NonOwnedIndicator) were in NO inventory, so once the
        # vehicle questions are suppressed on an HNOA-only account nothing
        # asked about the exposure that IS there. Both are factual client
        # questions with registry wording; both stamp deterministically.
        "hired_auto_indicator", "non_owned_auto_indicator",
        "auto_liability_limit", "auto_covered_symbols",
        "auto_deductible_comp", "auto_deductible_collision",
        "auto_physical_damage_valuation",
        # Read by this form's own checks (G18, 30 Oct 2026 - the card net needs them).
        "auto_liability_structure", "locations",
    ],
    "ACORD_140": [
        "locations", "occupancy_type", "construction_type", "year_built",
        "roof_year", "sprinkler_system", "fire_protection_class",
        "valuation_method", "coinsurance_percentage",
        "property_building_value", "property_bpp_value",
        "business_income_limit", "period_of_restoration",
        "property_deductible_aop", "property_deductible_wind",
        "mortgagee_name",
    ],
    "ACORD_25": [
        "applicant_name", "effective_date", "expiration_date",
        "policy_number", "gl_limits", "gl_aggregate", "certificate_holder",
    ],
    "ACORD_131": [
        "umbrella_limit", "umbrella_sir", "gl_limits", "auto_liability_limit",
        "effective_date", "applicant_name",
        # ADDED 2026-08-26 - master-plan 4.11's own list. The C4 live run (S4)
        # showed the umbrella asking for a limit and an SIR and nothing else:
        # attachment point, follow-form status, the Schedule of Underlying
        # Insurance and the Employers Liability limits all surfaced NO question,
        # because the injector walks this table. All four are producer-facing.
        "umbrella_attachment_point", "umbrella_follow_form",
        "underlying_policies", "employers_liability_limits",
    ],
    "ACORD_130": [
        "wc_payroll", "wc_class_codes", "wc_xmod", "wc_officer_exclusions",
        # V1 H1 6.4 (2026-08-26): the payroll period is scored at package
        # level now, so it must be ASKABLE - it was extracted and scored on the
        # 130 checklist but absent from this inventory, i.e. asked of nobody.
        "wc_payroll_period",
        "total_payroll", "num_employees", "applicant_name", "effective_date",
        # Read by this form's own checks (G18, 30 Oct 2026 - the card net needs them).
        "operations_description",
    ],
    "ACORD_137_CA": [
        "auto_liability_limit", "auto_liability_structure", "auto_covered_symbols",
        "auto_um_uim_limit", "auto_med_pay_limit", "auto_hired_nonowned",
        "auto_deductible_comp", "auto_deductible_collision",
    ],
    "ACORD_137_CO": [
        "auto_liability_limit", "auto_liability_structure", "auto_covered_symbols",
        "auto_um_uim_limit", "auto_med_pay_limit", "auto_hired_nonowned",
        "auto_deductible_comp", "auto_deductible_collision",
    ],
    "ACORD_138_CA": [
        "garage_operations_type", "garage_liability_limit", "garage_deductible",
        "garagekeeper_liability_limit", "garagekeeper_comp_deductible",
        "garagekeeper_coll_deductible", "auto_dealers_inventory_value",
    ],
    "ACORD_138_CO": [
        "garage_operations_type", "garage_liability_limit", "garage_deductible",
        "garagekeeper_liability_limit", "garagekeeper_comp_deductible",
        "garagekeeper_coll_deductible", "auto_dealers_inventory_value",
    ],
    "ACORD_101": [
        "operations_description", "applicant_name", "effective_date",
        "additional_remarks_text",
    ],
    "ACORD_133": [   # WC Assigned Risk section (Z37) - never builders risk
        "wc_class_codes", "wc_payroll", "num_employees", "wc_xmod",
        "applicant_name", "effective_date",
        # Read by this form's own checks (G18, 30 Oct 2026 - the card net needs them).
        "total_payroll",
    ],
    # Z37 (24 Oct 2026): 141 is the Crime section, 160 the Business Owners
    # section (their templates' own titles).
    "ACORD_141": [
        "crime_limit", "crime_deductible", "crime_employee_count",
        "crime_locations_count", "applicant_name", "effective_date",
    ],
    "ACORD_160": [
        "bop_property_limit", "bop_liability_limit", "bop_deductible",
        "property_deductible_earthquake",       # the 160's own $ / % pair (Z33)
        "locations", "construction_type", "occupancy_type",
        "applicant_name", "effective_date",
    ],
    "ACORD_186": [
        "contractor_type", "percent_subcontracted", "contractor_residential_pct",
        "contractor_high_hazard_ops", "contractor_license_number",
        "applicant_name", "effective_date",
    ],
    "ACORD_28": [
        "applicant_name", "effective_date", "expiration_date",
        "policy_number", "property_building_value", "property_bpp_value",
        "certificate_holder", "mortgagee_name",
    ],
}

_EMPTY_VALUES = {"", "null", "none", "[]", "{}"}


def _fact_is_filled(val) -> bool:
    """DID THEY ANSWER? - not "is there a value".

    Delegates to `answer_semantics.fact_answered`, so a human answer of "there
    is none" / "not applicable" counts as ANSWERED and is never scored as a
    gap (Brent 2026-08-24: *"we can't treat 'N/A' as '0'"*), while a
    non-answer never reaches the facts at all. Falls back to the original
    emptiness test if the module is unavailable.
    """
    try:
        from services.answer_semantics import fact_answered
        return fact_answered(val)
    except Exception:                                         # noqa: BLE001
        if isinstance(val, dict) and "value" in val:
            val = val["value"]
        if val is None:
            return False
        if isinstance(val, list):
            return len(val) > 0
        return str(val).strip().lower() not in _EMPTY_VALUES


def _answered(facts: dict, key: str) -> bool:
    """Completeness predicate: did this fact get an answer, from a document or
    a person? Reads the RAW envelope (not `_fv`) so `value_state` survives.
    An absence on a fact every operating business has (FEIN, revenue, NAICS /
    SIC, years / start date) is never an answer (`answer_semantics.answered_for`,
    strict review 29 Oct 2026)."""
    raw = (facts or {}).get(key)
    try:
        from services.answer_semantics import answered_for
        return answered_for(key, raw, facts)
    except Exception:                                         # noqa: BLE001
        return _fact_is_filled(raw)


def calculate_sqs_from_facts(
    facts: dict,
    flags: dict,
    selected_form_ids: List[str],
    hard_stops: List[str],
    soft_stops: List[str],
    tier2_score: int,
    form_id: str = None,
    confidence_dict: Optional[dict] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    calculation_stage: str = "initial_extract",
    # §6.3/§6.4 (Finding 6): pass the session so the narrative/loss-run floors
    # apply here too - otherwise download/reload SQS drops below the in-flow score.
    session_data: Optional[dict] = None,
    cross_issues_full: Optional[List[dict]] = None,
) -> dict:
    """
    Calculate SQS for Clarity pipeline without form generation.
    Uses FORM_FIELD_INVENTORY to derive fill_rate.
    """
    fid = form_id or (selected_form_ids[0] if selected_form_ids else "ACORD_125")
    # A form's second copy: its form's inventory, its own view (7 Oct 2026).
    from services.form_instances import base_form_id as _base_form_id, facts_for_form
    facts = facts_for_form(facts, fid)
    inventory = FORM_FIELD_INVENTORY.get(_base_form_id(fid), list(facts.keys()))

    synthetic_mapped = {k: _fv(facts, k) for k in inventory}
    filled = sum(1 for k in inventory if _fact_is_filled(_fv(facts, k)))
    schema_size = len(inventory)

    # Derive classified-doc presence + loss-run insured match from the session so
    # this path credits the same evidence the in-flow per-form path does.
    _docs       = (session_data or {}).get("docs") or []
    _present    = {str(d.get("doc_type") or "").strip() for d in _docs if isinstance(d, dict) and not d.get("excluded")}
    _has_narr   = "narrative" in _present
    from services.loss_history_state import package_has_loss_runs
    _has_loss   = package_has_loss_runs(_docs, facts)
    _loss_match = _check_loss_run_insured_match(_docs, _fv(facts, "applicant_name"), facts)

    return calculate_sqs(
        facts=facts,
        flags=flags,
        mapped_data=synthetic_mapped,
        form_schema={k: {} for k in inventory},
        selected_form_ids=selected_form_ids,
        hard_stops=hard_stops,
        soft_stops=soft_stops,
        tier2_score=tier2_score,
        form_id=fid,
        schema_size=schema_size,
        fields_mapped=filled,
        confidence_dict=confidence_dict,
        session_id=session_id,
        user_id=user_id,
        calculation_stage=calculation_stage,
        has_narrative_doc=_has_narr,
        has_loss_run_doc=_has_loss,
        loss_run_match=_loss_match,
        cross_issues_full=cross_issues_full,
        narrative_doc_text=_extract_narrative_doc_text(_docs),
        _form_boxes=False,
    )
