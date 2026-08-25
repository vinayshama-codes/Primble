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
    "mm": 1_000_000, "m": 1_000_000, "million": 1_000_000,
    "k": 1_000, "thousand": 1_000,
    "b": 1_000_000_000, "billion": 1_000_000_000,
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


def _to_float(v) -> float | None:
    """Parse a numeric string to float. Returns None on failure.

    Bug fix (2026-07-11, found via loss-history test suite): must expand
    magnitude shorthand ("$3.2M" -> 3,200,000) the same way _to_int does.
    Every caller of this function reads a currency fact (total_revenue,
    total_payroll, total_incurred, ...); a bare digit-strip on "$3.2M" was
    silently truncating at the decimal and dropping the "M", parsing an
    exposure of $3.2M as literally $3 - which then produced nonsense loss
    frequency/ratio figures ("2 claims on $3 exposure").
    """
    if v is None:
        return None
    s = str(v).replace(",", "").replace("$", "").strip().lower()
    _mag = re.match(r"([\d.]+)\s*(million|thousand|billion|mm|m|k|b)\b", s)
    if _mag:
        try:
            return float(_mag.group(1)) * _MAGNITUDE_SUFFIXES[_mag.group(2)]
        except Exception:
            pass
    try:
        return float(re.sub(r"[^\d.]", "", s))
    except Exception:
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


def _score_narrative_substance(text: str) -> int:
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
        1 for phrases in _NARRATIVE_SUBSTANCE_SIGNALS.values()
        if any(p in t for p in phrases)
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

TIER2_FIELDS = {
    "fein":                   "FEIN / Tax ID",
    "operations_description": "Operations description",
    "total_revenue":          "Annual revenue",
    "num_employees":          "Number of employees",
    "years_in_business":      "Years in business",
    "naics_code":             "NAICS / industry code",
    "total_payroll":          "Annual payroll",
    # Client C2 2.7 / 2.8 (2026-08-24): prior_carrier and num_claims are
    # REMOVED from Structural Completeness. Their scoring home is Loss History
    # (calculate_p4_loss_history), where applicability and new-venture status
    # are handled correctly; keeping them here double-counted one gap in two
    # pillars and docked a legitimate new venture for history it cannot have.
    # Spec ACORD 130: X-mod, payroll period, owner/officer exclusions are required for WC.
    "wc_xmod":                "WC experience modification factor (X-mod)",
    "wc_payroll_period":      "WC payroll period",
    "wc_officer_exclusions":  "WC owner/officer inclusion/exclusion",
}


# ── Tier checks ───────────────────────────────────────────────────────────────

def producer_fields_exempt(flags: dict | None) -> bool:
    """True when the producer's OWN details must not be scored as missing.

    A declarations page is issued by the CARRIER. It does not print the
    producing agency's name or the applicant's contact details, so counting
    them as gaps marks a submission down for something its document type can
    never carry.

    ONE definition, because there were two. `check_tier1` (which the PACKAGE
    score uses) applied this exemption; `calculate_sqs`'s ACORD 125 checklist
    kept its own copy of the same six checks and did not. Measured on a live
    dec-page session 2026-08-17: answering `contact_name` moved ACORD 125 from
    63 to 68 while the package sat unmoved at 68, because the two scorers
    disagreed about whether contact information was required at all. Same fact,
    same session, two rules. The recommendation is still RAISED either way - we
    still want the contact details - it just stops being a score penalty.
    """
    return (flags or {}).get("_doc_type") == "dec_page"


def check_tier1(facts: dict, flags: dict) -> Tuple[bool, List[str]]:
    if flags.get("is_certificate_doc") or flags.get("has_certificate_request"):
        missing = []
        if not _fv(facts, "applicant_name"):
            missing.append("Applicant legal name")
        if not _fv(facts, "effective_date"):
            missing.append("Proposed effective date")
        return len(missing) == 0, missing
    missing = []
    skip_producer_fields = producer_fields_exempt(flags)
    for field, label in TIER1_FIELDS.items():
        if skip_producer_fields and field == "producer_name":
            continue
        # ANSWERED, not "has a value": a human answering "there is none" has
        # answered (Brent 2026-08-24) and must not be counted as a gap.
        if not _answered(facts, field):
            missing.append(label)
    if not skip_producer_fields and not any(_answered(facts, f) for f in TIER1_CONTACT):
        missing.append("Contact information")
    return len(missing) == 0, missing


# WC-specific Tier 2 fields. These are mechanical ACORD 130 requirements, not
# part of the client's Underwriting Information spec (Revenue, Payroll, Employees,
# Years in Business, Operations Description, FEIN, NAICS). They must only count
# toward the Underwriting Profile denominator when WC coverage is actually present
# - otherwise every GL-only / non-WC submission takes a ~25-point structural
# penalty for fields that can never apply to it.
_TIER2_WC_FIELDS = ("wc_xmod", "wc_payroll_period", "wc_officer_exclusions")


def check_tier2(facts: dict, flags: dict | None = None) -> Tuple[int, List[str]]:
    # The industry-classification requirement is satisfied by EITHER a NAICS or a
    # SIC code (Beta Report §10 lists both as readiness items and notes they are
    # mapped flexibly). A submission carrying a SIC code but no NAICS is now
    # credited (previously it was penalised), and when both are absent the gap is
    # surfaced as one combined "NAICS or SIC" item rather than ignoring SIC.
    #
    # WC-specific fields are excluded from both the missing list AND the
    # denominator when the submission has no Workers Comp coverage, so a complete
    # non-WC submission can reach 100 (previously capped at ~75).
    has_wc = bool((flags or {}).get("has_workers_comp"))
    fields = {
        f: lbl for f, lbl in TIER2_FIELDS.items()
        if has_wc or f not in _TIER2_WC_FIELDS
    }
    missing: List[str] = []
    for field, label in fields.items():
        if field == "naics_code":
            if not (_answered(facts, "naics_code") or _answered(facts, "sic_code")):
                missing.append("NAICS or SIC industry code")
            continue
        # ANSWERED, not "has a value" - see check_tier1.
        if not _answered(facts, field):
            missing.append(label)
    score = max(0, round(100 - len(missing) * (100 / len(fields))))
    return score, missing


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
    read, not an inference.
    """
    _PRODUCER_SOURCES = {"producer", "client_arq", "user", "human"}
    for key in ("effective_date", "expiration_date"):
        raw = (facts or {}).get(key)
        if isinstance(raw, dict):
            if str(raw.get("source") or "").strip().lower() in _PRODUCER_SOURCES:
                return True
            if str(raw.get("confidence") or "").strip().lower() in ("filled", "deterministic"):
                return True
    return False


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
        if _is_renewal_submission(facts) or not _dates_are_producer_asserted(facts):
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


_VALID_NAICS_PREFIXES = {
    "11","21","22","23","31","32","33","42","44","45",
    "48","49","51","52","53","54","55","56","61","62",
    "71","72","81","92"
}

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
        for r in rows:
            if not isinstance(r, dict):
                continue
            if str(r.get("premium_basis") or "").strip() and re.search(
                    r"\d", str(r.get("exposure_amount") or "")):
                return True
    try:
        from services.extraction_service import _entries_state_payroll
    except Exception:                                      # noqa: BLE001
        return False
    return _entries_state_payroll((facts or {}).get("dec_page_entries"))


def evaluate_stops(facts: dict, flags: dict) -> Tuple[List[str], List[str]]:
    """
    Evaluate hard and soft stops from facts/flags.
    Cross-doc hard stops appended by caller after check_doc_consistency().
    """
    hard, soft = run_field_validations(facts)

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
    if flags.get("gl_is_claims_made") and not _fv(facts, "retro_date"):
        soft.append("GL policy is claims-made - retro date is required")
    if (flags.get("has_general_liability") and not _fv(facts, "total_revenue")
            and not _fv(facts, "total_payroll")
            and not _dec_entries_state_payroll(facts)):
        soft.append("GL coverage detected but no revenue or payroll found")
    if flags.get("has_general_liability"):
        codes = _fv(facts, "gl_class_codes_by_location") or []
        if isinstance(codes, list) and not codes:
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
        else:
            carrier_cope = {k: bool(_fv(facts, k)) for k in [
                "year_built", "roof_year", "sprinkler_system",
                "fire_protection_class", "valuation_method", "coinsurance_percentage",
            ]}
            missing_c = [k.replace("_", " ") for k, v in carrier_cope.items() if not v]
            if missing_c:
                soft.append("Carrier-Grade COPE incomplete - SQS capped at 85. Missing: " + ", ".join(missing_c))

        if flags.get("property_has_bi_coverage"):
            # BI limit + POR ownership moved to cross_form_validator as hard stop.
            # Keep only the "no BI limit at all" soft advisory here to avoid duplication.
            if not _fv(facts, "business_income_limit"):
                soft.append("Business Income coverage detected - BI limit and Period of Restoration should be provided")

        if flags.get("property_has_peril_deductibles"):
            missing_perils = [
                p for p, k in [
                    ("wind/hail",  "property_deductible_wind"),
                    ("earthquake", "property_deductible_earthquake"),
                    ("flood",      "property_deductible_flood"),
                ]
                if not _fv(facts, k)
            ]
            if missing_perils:
                # Spec: peril-specific deductible referenced but undefined → hard stop
                hard.append(
                    "Peril-specific deductibles referenced but not defined - specify amounts for: "
                    + ", ".join(missing_perils)
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
            private_wc_requested = bool(
                flags.get("wc_private_carrier_requested")
                or flags.get("wc_requested_private_carrier")
                or (_fv(facts, "wc_carrier_type") or "").lower() in ("private", "voluntary")
            )
            state_fund_ack = bool(
                flags.get("wc_state_fund_acknowledged")
                or _fv(facts, "wc_state_fund_acknowledged")
            )
            if private_wc_requested and not state_fund_ack:
                hard.append(
                    "Monopolistic WC state (ND/OH/WA/WY) requires the state fund - "
                    "private-carrier WC cannot be quoted. Remove private-carrier "
                    "request or acknowledge state-fund handling."
                )
            else:
                soft.append("Monopolistic WC state detected (ND/OH/WA/WY) - must use state fund")
            if not _fv(facts, "wc_monopolistic_payroll"):
                hard.append("Monopolistic WC state detected but wc_monopolistic_payroll breakdown is missing")
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
    if (flags.get("has_umbrella")
            and not _fv(facts, "gl_each_occurrence") and not _fv(facts, "gl_limits")
            and not _fv(facts, "auto_liability_limit")):
        hard.append("Umbrella detected but no underlying GL or Auto limits found")

    # ── ACORD 127: Auto coverage integrity ────────────────────────────────────
    if flags.get("has_auto_coverage"):
        auto_limit_structure = _fv(facts, "auto_liability_structure")
        bi_pp = _fv(facts, "bi_per_person")
        bi_pa = _fv(facts, "bi_per_accident")
        pd_pa = _fv(facts, "pd_per_accident")
        # Spec L185: "Incomplete liability structure → hard stop". Detect a
        # split-limit attempt even when auto_liability_structure / auto_split_limits
        # weren't extracted: if ANY of the three components is present, treat
        # this as split and require all three.
        _split_indicated = (
            flags.get("auto_split_limits")
            or auto_limit_structure == "split"
            or any([bi_pp, bi_pa, pd_pa])
        )
        if _split_indicated:
            if not all([bi_pp, bi_pa, pd_pa]):
                hard.append(
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
        if flags.get("gl_is_claims_made") and not _fv(facts, "retro_date"):
            if "GL policy is claims-made - retro date is required" not in soft:
                soft.append("Claims-made GL policy requires retro date for umbrella attachment.")

        if flags.get("has_workers_comp"):
            el_limit = _fv(facts, "employers_liability_limits")
            if not el_limit:
                soft.append("Umbrella attaches over WC but Employers Liability limits not provided.")
            else:
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

        umb_eff = _fv(facts, "umbrella_effective_date")
        if umb_eff and gl_eff and _dates_differ(umb_eff, gl_eff):
            soft.append("Umbrella and GL policy periods misaligned.")

        umb_exp = _fv(facts, "umbrella_expiration_date")
        if umb_exp and gl_exp and _dates_differ(umb_exp, gl_exp):
            soft.append("Umbrella and GL expiration dates misaligned.")

        # ── THE REAL UNKNOWN, WHICH SILENCE WAS HIDING ──────────────────────
        # Removing the false misalignment left nothing at all in its place, and
        # there IS something to say: on a renewal the umbrella's stated term is
        # its EXPIRING one, and no document states the term being applied for.
        # That is a genuine gap in the submission - recommended, not a hard
        # stop (it caps nothing), and resolvable by typing the two dates.
        if "Umbrella" in (_fv(facts, "renewal_lines_expiring") or []):
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

    return hard, soft


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

    if flags.get("has_certificate_holder_requirement"):
        cert_holder = _fv(facts, "certificate_holder")
        checklist.append({
            "check":   "certificate_of_insurance",
            "label":   "Certificate of Insurance",
            "status":  "required",
            "message": f"Certificate of Insurance required for: {cert_holder}" if cert_holder else "Certificate of Insurance required",
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

    if not _fv(facts, "applicant_name"):
        issues.append({"type": "hard_stop", "message": "Named insured missing - required on all forms"})

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
            pct = _to_float(_fv(facts, "percent_subcontracted"))
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
        if flags.get("property_has_bi_coverage") and not _fv(facts, "business_income_limit"):
            issues.append({"type": "warning", "message": "Business Income coverage detected - BI limit required"})
        if not _fv(facts, "valuation_method"):
            issues.append({"type": "warning", "message": "Property valuation method not specified on ACORD 140"})

    # GL presence mirrors the scorer / state machine (gl_each_occurrence or
    # gl_limits) so a GL limit captured only as the clean per-occurrence scalar is
    # not falsely reported as "GL limits missing" for ACORD 131.
    if "ACORD_131" in selected_form_ids and not _fv(facts, "gl_each_occurrence") and not _fv(facts, "gl_limits"):
        issues.append({"type": "hard_stop", "message": "Umbrella selected but GL limits missing"})

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
    submission — the picker is the resolution path for the currently-hard fields
    (applicant_name / fein / effective_date / expiration_date).
    """
    confirmed_keys = confirmed_keys or set()
    issues: List[str] = []

    # Package context for the equivalence filter, built ONCE and BEFORE the
    # first check that uses it. (Built lower down in the first cut, which meant
    # the identity checks called it before it existed - the exception was
    # swallowed by the fail-open guard and the filter silently never fired. A
    # fix that looks applied and is not is worse than no fix.)
    _pkg_ctx = _build_pkg_context(None, docs)

    def _raw(key: str) -> List:
        # Role scope (client 1.2): a document is only read as stating a fact its
        # ROLE covers. See fact_comparison.document_witnesses.
        return [_fv(d["facts"], key) for d in docs
                if _fv(d["facts"], key) and _doc_witnesses(d.get("doc_type"), key)]

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
            if _fv(d["facts"], key) and d.get("filename") not in seen:
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
        seen, out = set(), []
        for v in raw:
            s = str(v).strip()
            if s and s.lower() not in seen:
                seen.add(s.lower())
                out.append(s)
        return ", ".join(out)

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
        issues.append(
            "[hard_stop] code=name_conflict "
            f"Applicant name differs across documents: {_show(applicant_raw)}"
            + _bracket("applicant_name", _DATA_CONSISTENCY_FIX)
        )
    elif len(applicant_raw) >= 2 and _raw_differ(applicant_raw):
        issues.append(
            f"[info] code=name_normalized "
            f"Applicant name: {_show(applicant_raw)}"
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
                f"{_ADDR_LABELS[key]}: {_show(vals_raw)}"
            )

    fein_raw = _raw("fein")
    if "fein" not in confirmed_keys and _conflicts("fein", fein_raw):
        issues.append(
            "[hard_stop] code=fein_conflict "
            "FEIN differs across uploaded documents. Score is capped at 60 until this is confirmed."
            + _bracket("fein", _DATA_CONSISTENCY_FIX)
        )

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
            "policy-date difference is downgraded from hard stop to warning "
            "(each contract carries its own term)", len(_pkg_ctx.contracts))
    _date_prefix = ("[warning]" if (_dates_explained or _multi_contract)
                    else "[hard_stop]")
    _date_multi_note = (
        " This package evidences more than one policy, and each policy carries "
        "its own term - confirm which term applies to the submission."
        if _multi_contract and not _dates_explained else "")

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
    elif _conflicts("effective_date", eff_raw):
        issues.append(
            f"{_date_prefix} code=date_conflict "
            "Policy date mismatch across documents." + (
                _date_multi_note or
                " Score is capped at 60 unless the difference is explained.")
            + _bracket("effective_date", _DATA_CONSISTENCY_FIX + " Or add an ACORD 101 explanation of the date difference.")
        )
    elif len(eff_raw) >= 2 and _raw_differ(eff_raw):
        issues.append(f"[info] code=effective_date_normalized Effective date: {_show(eff_raw)}")

    exp_raw = _raw("expiration_date")
    if "expiration_date" in confirmed_keys:
        pass  # resolved via the Data Consistency picker
    elif _dates_owned_separately("expiration_date"):
        pass  # PROVEN to be two contracts' own terms - not a disagreement
    elif _conflicts("expiration_date", exp_raw):
        issues.append(
            f"{_date_prefix} code=expiration_conflict "
            "Policy expiration date mismatch across documents." + (
                _date_multi_note or
                " Score is capped at 60 unless the difference is explained.")
            + _bracket("expiration_date", _DATA_CONSISTENCY_FIX + " Or add an ACORD 101 explanation of the date difference.")
        )
    elif len(exp_raw) >= 2 and _raw_differ(exp_raw):
        issues.append(f"[info] code=expiration_date_normalized Expiration date: {_show(exp_raw)}")

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

    for d in docs:
        lob = _fv(d["facts"], "lines_of_business")
        if lob and isinstance(lob, list) and lob:
            norm = frozenset(
                (_cl(x) or n) for x in lob if (n := normalize_general(x)))
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
    if len(lob_norm_sets) >= 2 and len(set(lob_norm_sets)) > 1 and _lob_disagree:
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
            f"[info] code=lob_normalized Coverage terms: {'; '.join(lob_raw_display)}"
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
            info.append(_DOC_ISSUE_TOKEN_RE.sub("", issue[len("[info]"):].strip()))
        else:
            # Unknown prefix - treat as a warning so it can never silently cap at 60.
            soft.append(issue)

    return hard, soft, info, conflicts


def doc_consistency_stops(session_data: dict) -> Tuple[List[str], List[str]]:
    """Re-run the cross-document identity checks against a STORED session.

    The rescore paths rebuild `hard_stops` from scratch; without this they drop
    the applicant-name / FEIN / effective-date / expiration-date conflicts and
    stop capping a submission that is still in conflict. Values already confirmed
    in the Data Consistency picker are excluded, matching the extraction path.

    Fails open (returns empty lists) - a rescore must never break because a
    legacy session stored its documents in an older shape.
    """
    try:
        docs = [
            d for d in ((session_data or {}).get("docs") or [])
            if isinstance(d, dict) and not d.get("excluded") and isinstance(d.get("facts"), dict)
        ]
        if len(docs) < 2:
            return [], []          # nothing to compare against
        confirmed = set(((session_data or {}).get("underwriting_confirmations") or {}).keys())
        hard, soft, _info, _conf = split_doc_consistency_issues(
            check_doc_consistency(docs, confirmed)
        )
        return hard, soft
    except Exception as exc:                                   # pragma: no cover
        logger.error("doc_consistency_stops failed (non-fatal): %s", exc, exc_info=True)
        return [], []


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
    # AI-mapped fills. The verification split is pdf_service's own contract:
    #   found word-for-word in the documents -> "ai_verified"   (pink,   AI-OK)
    #   NOT found - a guess, or a claim we
    #   could not locate                     -> "low_confidence" (orange, verify)
    # "ai_verified" takes the AI-high slot: it is the highest confidence the
    # AI path can reach - the value is on the page - but it was still placed
    # by the model, not read deterministically, so it is not 1.00. Brent may
    # re-tune the number (Q9); its slot in the ladder is not in question.
    "ai_verified":      0.85,
    "ai_high":          0.85,    # fact-level label (extraction); never a field label today
    "ai_low":           0.50,    # fact-level label (extraction); never a field label today
    "low_confidence":   0.50,    # the field label pdf_service actually emits for unverified AI
    # Empty / required-but-missing fields contribute nothing. Both gate labels
    # are listed EXPLICITLY so that 0.00 is a decision, not a `.get` default.
    "missing_required":      0.00,
    "missing_required_gate": 0.00,   # ACORD 125/126 "started row" sibling gate
    None:                    0.00,
}


def confidence_fill_rate(mapped_data: dict, confidence_dict: dict) -> int:
    """Calculate confidence-weighted fill rate.

    The SPEC's requirement is only that this be "confidence-weighted"; the
    weights themselves (producer-edits=1.00, AI-high=0.85, AI-low=0.50) are an
    ENGINEERING DEFAULT, not a client decision - see the note on
    ``CONFIDENCE_SCORE``. Denominator is the count of *filled* fields so the
    score reflects the average confidence of what was filled, not how big the
    template happens to be.
    """
    filled_items = [
        field for field, val in mapped_data.items()
        if val is not None and str(val).strip() not in ("", "null", "None")
    ]
    filled_count = len(filled_items)
    if filled_count == 0:
        return 0

    weighted = sum(
        CONFIDENCE_SCORE.get(confidence_dict.get(field), 0.0)
        for field in filled_items
    )
    return int((weighted / filled_count) * 100)


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
    start = _parse_iso_date(_fv(facts, "loss_run_period_start"))
    end   = (_parse_iso_date(_fv(facts, "loss_run_period_end"))
             or _parse_iso_date(_fv(facts, "loss_run_valuation_date")))
    if start is not None and end is not None and end >= start:
        return max(1, min(round((end - start).days / 365.25), 10))
    return _to_int(_fv(facts, "loss_history_years")) or 0


def _loss_history_conflict(facts: dict, flags: dict) -> bool:
    """True when a no-loss attestation (user or narrative) is contradicted by
    ACTUAL loss-run claims (§6.4 item 1 'conflicting').

    Single source of truth shared by the P4 score and the state label so the two
    can never disagree. Note: years of loss history alone do NOT contradict a
    no-loss attestation (a clean multi-year loss run CONFIRMS it) - only real
    claims / incurred amounts do.
    """
    claims   = _to_int(_fv(facts, "num_claims")) or 0
    incurred = _to_float(_fv(facts, "total_incurred")) or 0.0
    no_loss = (
        bool(flags.get("no_prior_losses"))
        or bool(flags.get("narrative_states_no_losses"))
        or _attested_true(_fv(facts, "no_prior_losses"))
        or _attested_true(_fv(facts, "loss_history_no_prior_losses_indicator"))
    )
    return no_loss and (claims > 0 or incurred > 0)


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
    # Already attested - only a document can raise it further.
    ("no known losses (attested by user)",              None),
    # Identity of the runs: whose are they, and do the identifiers line up.
    ("loss run insured name does not match",            "applicant_name"),
    ("loss run ownership partially verified",           "fein"),
    ("loss run ownership could not be fully verified",  "fein"),
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


def loss_recommendation_field(message: str) -> Optional[str]:
    """The canonical fact that would actually answer this loss recommendation.

    `None` = no single fact closes it (needs a document or a reconciliation).
    Unknown messages also return None rather than guessing: offering a waiver on
    a rec we cannot route is recoverable, silently writing an answer into the
    wrong fact is the defect this function exists to fix.
    """
    m = (message or "").lower()
    for phrase, field in _LOSS_RECOMMENDATION_FIELDS:
        if phrase in m:
            return field
    return None


_NEW_VENTURE_CONFIRM_REC = (
    "If this business is a new venture with no prior operations, confirm New "
    "Venture status - Loss History will then be marked Not Applicable instead "
    "of counting against the score."
)


def calculate_p4_loss_history(
    facts: dict,
    flags: dict,
    has_loss_run_doc: bool = False,
    loss_run_match: str = "no_loss_run",
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
    Path C - no runs: attested no-loss 60, requested/pending 50,
      narrative-only 40, nothing 25. Known claims + pending = 50; attestation
      + pending = 60; known claims with no runs and nothing pending = 25.
    New venture (client 2.2): producer-confirmed and uncontradicted -> returns
      None (Not Applicable); the caller's _weighted_pillar_sum rescales the
      remaining pillars proportionally.
    Ceilings (client 2.6 + spec): no-match caps at 25; a no-loss attestation
      contradicted by actual loss-run claims caps at 45. Ceilings, never
      floors - a score already below stays its own value.
    """
    from services.loss_history_state import (
        BAND_ESTABLISHING, BAND_YOUNG, loss_history_not_applicable,
        loss_runs_pending_stated, new_venture_applicable, new_venture_confirmed,
        no_runs_available_stated, parse_loss_run_status, previously_uninsured,
        prior_carrier_applicable, prior_claims_exist, prior_operations_evidence,
        years_in_business_band,
    )
    years    = _resolve_loss_history_years(facts)
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
    no_loss_attested = (
        bool(flags.get("no_prior_losses"))
        or bool(flags.get("narrative_states_no_losses"))
        or _attested_true(_fv(facts, "no_prior_losses"))
        or _attested_true(_fv(facts, "loss_history_no_prior_losses_indicator"))
    )

    recs: List[str] = []

    # §6.4 item 1: a no-loss attestation contradicted by ACTUAL loss-run claims
    # cannot earn full credit. Cap every return path so the number matches the
    # 'conflicting' state label (single source: _loss_history_conflict).
    _conflict = _loss_history_conflict(facts, flags)
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
            return None, [
                "New Venture confirmed - no prior operations, so Loss History is "
                "Not Applicable and removed from the score (remaining pillars "
                "rescale proportionally)."
            ]
        return None, [
            "Business has under a year of operating history and reports no "
            "known losses - there are no loss runs to obtain, so Loss History "
            "is Not Applicable and removed from the score (remaining pillars "
            "rescale proportionally)."
        ]
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
    if has_loss_run_doc and years >= _LOSS_YEARS_FULL:
        base_score = 100
    elif has_loss_run_doc and years >= _LOSS_YEARS_PART:
        base_score = 85
        recs.append("3 years of loss runs provided - 5 years preferred for full credit")
    elif has_loss_run_doc and years > 0:
        base_score = 70
        recs.append("Loss history incomplete - fewer than 3 years provided")
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
        if (parse_loss_run_status(_fv(facts, "loss_run_status")) == "pending"
                and years == 0 and not _has_claims):
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
            _NEW_VENTURE_CONFIRM_REC,
        ])
    else:
        return _result(25, [
            "No loss history provided - required for carrier submission",
            _NEW_VENTURE_CONFIRM_REC,
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


# ── LOB inference ─────────────────────────────────────────────────────────────

NAICS_TO_LOB = {
    "236": "contractor", "237": "contractor", "238": "contractor",
    "722": "restaurant", "311": "restaurant", "312": "restaurant",
    "511": "technology", "518": "technology", "519": "technology",
    "541": "technology",
    "321": "manufacturing","331": "manufacturing","332": "manufacturing",
    "484": "transportation","485": "transportation","492": "transportation",
}


def infer_lob(facts: dict, flags: dict) -> str:
    """Infer line of business from NAICS, flags, or operations description."""
    naics = str(_fv(facts, "naics_code") or "")[:3]
    if naics and naics in NAICS_TO_LOB:
        return NAICS_TO_LOB[naics]
    
    if flags.get("is_contractor"):
        return "contractor"
    
    desc = (_fv(facts, "operations_description") or "").lower()
    if any(w in desc for w in ["restaurant","food","catering","kitchen","dining"]):
        return "restaurant"
    if any(w in desc for w in ["software","tech","saas","app","cloud","platform"]):
        return "technology"
    if any(w in desc for w in ["truck","freight","transport","delivery","fleet"]):
        return "transportation"
    
    return "generic"


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
    """Best-effort industry bucket from operations text, falling back to NAICS sector."""
    for industry, kws in _OPS_INDUSTRY_KEYWORDS.items():
        if any(k in ops for k in kws):
            return industry
    return _NAICS_SECTOR_INDUSTRY.get(naics2)


def _codes_to_industry(code_str: str) -> Optional[str]:
    """Industry bucket from class codes - only when the codes agree on ONE industry."""
    found = {ind for code, ind in _CLASS_CODE_INDUSTRY.items() if code in code_str}
    return next(iter(found)) if len(found) == 1 else None


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

    codes = (
        _fv(facts, "gl_class_codes_by_location") if coverage_type == "gl"
        else _fv(facts, "wc_class_codes")
    )
    if not codes or (isinstance(codes, list) and not codes):
        return False
    code_ind = _codes_to_industry(str(codes))
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
    ded = {
        "operations_description":       0,
        "coverage_information":         0,
        "payroll_employee_information": 0,
        "revenue_sales_information":    0,
        "cross_document_consistency":   0,
    }

    # ── GL: class codes vs operations (L90, L92) ─────────────────────────────
    if flags.get("has_general_liability"):
        gl_codes = _fv(facts, "gl_class_codes_by_location")
        codes_present = bool(gl_codes) and not (isinstance(gl_codes, list) and not gl_codes)
        if not codes_present:
            ded["operations_description"] += 20
        else:
            if not _fv(facts, "operations_description"):
                ded["operations_description"] += 10
            elif _is_ops_class_code_mismatch(facts, flags, "gl"):
                ded["operations_description"] += 15  # GL class code does not match operations description
        if not _fv(facts, "gl_limits") and not _fv(facts, "gl_each_occurrence"):
            ded["coverage_information"] += 8
    else:
        # No GL - standalone operations description missing deduction
        if not _fv(facts, "operations_description"):
            ded["operations_description"] += 10

    # ── Payroll / revenue exposure base (L41, L121) ──────────────────────────
    has_payroll = bool(_fv(facts, "total_payroll") or _fv(facts, "wc_payroll"))
    has_revenue = bool(_fv(facts, "total_revenue"))
    if not (has_payroll or has_revenue):
        ded["payroll_employee_information"] += 15

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
            ded["revenue_sales_information"] += 10  # Payroll is 200%+ of revenue - very unusual
        elif _ratio < 0.01:
            ded["revenue_sales_information"] += 5    # Payroll under 1% of revenue - suspiciously low

    # ── WC: payroll + class codes + multi-state (L121, L143-150) ─────────────
    if flags.get("has_workers_comp"):
        if not _fv(facts, "wc_payroll") and not _fv(facts, "total_payroll"):
            ded["payroll_employee_information"] += 12
        if not _fv(facts, "wc_class_codes"):
            ded["operations_description"] += 10
        elif _is_ops_class_code_mismatch(facts, flags, "wc"):
            ded["operations_description"] += 15  # WC class code does not match operations description
        if flags.get("wc_multi_state") and not _fv(facts, "wc_payroll_by_state"):
            ded["payroll_employee_information"] += 8

    # ── Contractor: subcontracting % reconciliation (L91, L458) ──────────────
    if flags.get("is_contractor") or flags.get("has_subcontractors"):
        if not _fv(facts, "percent_subcontracted"):
            ded["operations_description"] += 8

    # ── Auto: liability structure + symbols (L184-191) ───────────────────────
    if flags.get("has_auto_coverage"):
        if not _fv(facts, "auto_liability_limit"):
            ded["coverage_information"] += 10
        if not _fv(facts, "auto_covered_symbols"):
            ded["coverage_information"] += 5

    # ── Exposure-coverage gaps (employees without WC, vehicles without auto) ─
    _num_emp = _to_int(_fv(facts, "num_employees"))
    if _num_emp and _num_emp > 5 and not flags.get("has_workers_comp"):
        ded["payroll_employee_information"] += 8   # Employees detected but no WC coverage

    _has_vehicle_exposure = bool(
        _fv(facts, "auto_vin_schedule")
        or _fv(facts, "vehicle_schedule")
        or flags.get("auto_vehicles_detected")
    )
    if _has_vehicle_exposure and not flags.get("has_auto_coverage"):
        ded["coverage_information"] += 8   # Vehicles detected but no auto coverage

    # ── Residual cross-form penalty (smaller now that checks are explicit) ──
    cross_penalty = min(len(hard_cross) * 15 + len(warn_cross) * 5, 20)
    ded["cross_document_consistency"] += cross_penalty

    # Headline = 100 minus all buckets (identical to the prior flat computation).
    score = max(0, min(100, 100 - sum(ded.values())))
    subscores = {k: max(0, 100 - v) for k, v in ded.items()}
    return score, subscores


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

    # Umbrella present but NO underlying GL/Auto value extracted. For this exact
    # input the scorer returns 0 and evaluate_stops raises a hard stop, so the
    # evidence state must read as a problem - never a benign "information provided"
    # label (§6.5: missing underlying must surface an Unknown / Insufficient
    # Information state, not a reassuring or perfect one). Both the no-flags and
    # flags-present variants score identically (0), so both map to "unknown"
    # ("underlying limits not found") to stay consistent with the score and stop.
    if not gl_val and not auto_val:
        return "unknown"

    # Required-but-absent underlying coverage (mirror the score's -20 deduction):
    # a present coverage flag with no extracted limit cannot be validated against
    # the umbrella, so the evidence "needs review" rather than reading as complete.
    # Without this the state could report umbrella_coverage_present / adequately_
    # supported while the score is penalising the same missing limit (state/score
    # contradiction). Handled symmetrically for GL and Auto.
    if (gl_val is None and flags.get("has_general_liability")) or \
       (auto_val is None and flags.get("has_auto_coverage")):
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

    if flags.get("has_workers_comp"):
        el_val = _to_int(_fv(facts, "employers_liability_limits"))
        if el_val is None or el_val < _UMB_EL_OK:
            return "umbrella_coverage_needs_review"

    # Underlying limits meet thresholds. Grade by how much supporting evidence
    # (schedule of underlying insurance + follow-form) corroborates the coverage:
    #   neither present → umbrella_coverage_present (client §6.5: limits meet thresholds
    #                       -> Coverage Present, even when schedule AND follow-form are
    #                       both missing; the old "Information Provided" state is retired)
    #   one present     → umbrella_coverage_present     (partially corroborated)
    #   both present    → adequately_supported
    _has_schedule = bool(
        _fv(facts, "schedule_of_underlying_insurance")
        or _fv(facts, "underlying_schedule")
        or _fv(facts, "underlying_insurance_schedule")
    )
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
}

_LOSS_STATE_TO_CLIENT: Dict[str, str] = {
    # No usable loss information yet (nothing on file, or runs merely requested).
    "no_information":                  "unknown",
    "loss_runs_pending":               "unknown",
    # A "no losses" position mentioned in narrative prose, nothing more.
    "narrative_states_no_losses":      "none_stated",
    # A formal no-loss attestation that no loss-run document yet corroborates.
    "user_states_no_losses":           "none_corroborated",
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
    "no_loss_runs_available":          "unknown",
    "prior_claims_exist":              "unknown",
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
    years = _resolve_loss_history_years(facts)
    no_loss_attested = (
        bool(flags.get("no_prior_losses"))
        or _attested_true(_fv(facts, "no_prior_losses"))
        or _attested_true(_fv(facts, "loss_history_no_prior_losses_indicator"))
    )
    narrative_no_loss = bool(flags.get("narrative_states_no_losses"))

    # C2 2.2: a verified new venture has no loss history to evaluate - the
    # pillar is Not Applicable (same gate the scorer consults, so state and
    # score can never disagree).
    from services.loss_history_state import (
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
    if _loss_history_conflict(facts, flags):
        return "loss_history_conflicting"

    if has_loss_run_doc:
        # Mirror the pending-status shortcut from calculate_p4_loss_history: a doc
        # classified as a loss_run that only mentions runs are pending with no actual
        # years or claims extracted should show the pending state, not "uploaded".
        _has_claims = (
            (_to_int(_fv(facts, "num_claims")) or 0) > 0
            or (_to_float(_fv(facts, "total_incurred")) or 0.0) > 0.0
        )
        if (parse_loss_run_status(_fv(facts, "loss_run_status")) == "pending"
                and years == 0 and not _has_claims):
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
) -> Dict[str, Dict[str, dict]]:
    """
    Display breakdown nested under the 6 SQS pillars.
    Returns {pillar_key: {category_key: {score, status, label}}}

    Sub-row structure (client-approved, updated to reflect actual scoring inputs):
      Structural Completeness  - Applicant Info (tier1), Underwriting Profile (tier2),
                                 Form Fill Quality (conf_rate) — these ARE the P1 formula
      Exposure Consistency     - Operations, Coverage Info, Payroll/Employee,
                                 Revenue/Sales, Cross-Document Consistency
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

    # ── Prior Carrier (under Narrative Quality per client mapping) ───────────
    carrier_s  = 100 if _ok("prior_carrier") else 0
    carrier_st = "ok" if carrier_s == 100 else "missing"

    # ── Exposure Consistency sub-rows ────────────────────────────────────────
    # When the package scorer passes the real per-bucket scores, render THOSE so
    # the expandable detail equals the inputs that produced the pillar headline.
    # Labels match client-approved naming exactly.
    if exposure_subscores:
        _exp_cats = {
            "operations_description":       _cat(exposure_subscores.get("operations_description", 0),      _sc_status(exposure_subscores.get("operations_description", 0)),      "Operations"),
            "coverage_information":         _cat(exposure_subscores.get("coverage_information", 0),         _sc_status(exposure_subscores.get("coverage_information", 0)),         "Coverage Info"),
            "payroll_employee_information": _cat(exposure_subscores.get("payroll_employee_information", 0), _sc_status(exposure_subscores.get("payroll_employee_information", 0)), "Payroll/Employee"),
            "revenue_sales_information":    _cat(exposure_subscores.get("revenue_sales_information", 0),    _sc_status(exposure_subscores.get("revenue_sales_information", 0)),    "Revenue/Sales"),
            "cross_document_consistency":   _cat(exposure_subscores.get("cross_document_consistency", 0),   _sc_status(exposure_subscores.get("cross_document_consistency", 0)),   "Cross-Document Consistency"),
        }
    else:
        _exp_cats = {
            "operations_description":       _cat(ops_s, ops_st,                                                          "Operations"),
            "coverage_information":         _cat(cov_s, "ok" if cov_s == 100 else "missing",                            "Coverage Info"),
            "payroll_employee_information": _cat(pay_s, "ok" if pay_s == 100 else ("partial" if pay_s else "missing"),  "Payroll/Employee"),
            "revenue_sales_information":    _cat(rev_s, "ok" if rev_s == 100 else ("partial" if rev_s else "missing"),  "Revenue/Sales"),
            "cross_document_consistency":   _cat(xd_s,  xd_st,                                                          "Cross-Document Consistency"),
        }

    return {
        "structural_completeness": {
            "applicant_information":      _cat(app_score,       _sc_status(app_score),       "Applicant Info"),
            "entity_information":         _cat(entity_score,    _sc_status(entity_score),    "Entity Info"),
            "effective_date_consistency": _cat(eff_score,       eff_st,                      "Effective Date Consistency"),
            "policy_term_consistency":    _cat(pol_score,       pol_st,                      "Policy Term Consistency"),
            "supporting_documentation":   _cat(supp_doc_score,  _sc_status(supp_doc_score),  "Supporting Documentation"),
        },
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
            "prior_carrier_context": _cat(carrier_s, carrier_st,       "Prior Carrier / Marketing Reason"),
        },
    }


def _calculate_umbrella_adequacy(facts: dict, flags: dict) -> Optional[int]:
    """P5 - Umbrella & Limit Adequacy (10% of SQS).

    Returns None when not applicable (no umbrella in submission). Callers must
    exclude this pillar from the weighted sum and re-normalise weights.

    Client-approved thresholds (Q1/Q2 answers):
      GL:   $1M each occurrence - reduce score if below, do NOT hard-stop
      Auto: $1M CSL             - reduce score if below, do NOT hard-stop
      EL:   $1M = full credit | $500K = acceptable | <$500K = reduction
    """
    if not flags.get("has_umbrella"):
        return None  # Not Applicable - fixes the confirmed 100% bug (§6.5)

    # Prefer the clean per-occurrence scalar; fall back to the combined field.
    # This matches validator.py precedence and avoids feeding the combined-limit
    # string ($1M/$2M) directly to _to_int when the clean field is available.
    gl_val   = _to_int(_fv(facts, "gl_each_occurrence") or _fv(facts, "gl_limits"))
    auto_val = _to_int(_fv(facts, "auto_liability_limit"))
    has_underlying = bool(gl_val or auto_val)

    if not has_underlying:
        return 0  # hard-stop scenario per evaluate_stops()

    score = 100

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
    if not _fv(facts, "umbrella_limit"):
        score -= 25

    # GL - penalise both "present but below minimum" AND "required but absent".
    # A submission with GL exposure (has_general_liability) but no GL limits
    # is a gap; umbrella spec §218 requires underlying GL (client Q1 / M4 fix).
    if gl_val is not None and gl_val < _UMB_GL_OCC_MIN:
        score -= 20              # Present but below $1M - warn, don't block (Q1)
    elif gl_val is None and flags.get("has_general_liability"):
        score -= 20              # Required underlying GL missing (M4)

    # GL aggregate (client Q1 baseline: $2M / occurrence $1M). The aggregate is the
    # other half of the client's stated GL baseline, so an extracted aggregate below
    # $2M reduces score (warn, never block - Q1). A merely-unextracted aggregate is
    # NOT penalised, to avoid a false warning when only the occurrence was captured.
    gl_agg = _to_int(_fv(facts, "gl_aggregate"))
    if gl_agg is not None and gl_agg < _UMB_GL_AGG_MIN:
        score -= 20

    # Auto - same logic: present-and-low OR required-but-absent.
    if auto_val is not None and auto_val < _UMB_AUTO_CSL_MIN:
        score -= 20              # Present but below $1M CSL - warn, don't block (Q1)
    elif auto_val is None and flags.get("has_auto_coverage"):
        score -= 20              # Required underlying Auto missing (M4)

    # EL tiers (client Q2: $1M full, $500K acceptable, <$500K reduction)
    if flags.get("has_workers_comp"):
        el_val = _to_int(_fv(facts, "employers_liability_limits"))
        if el_val is None:
            score -= 25          # Missing EL
        elif el_val >= _UMB_EL_FULL:
            pass                 # Full credit ($1M+)
        elif el_val >= _UMB_EL_OK:
            score -= 10          # Acceptable ($500K–$999K)
        else:
            score -= 25          # Below minimum (<$500K)

    # Schedule of Underlying Insurance: -15 when absent (client V1 requirement)
    _has_schedule = bool(
        _fv(facts, "schedule_of_underlying_insurance")
        or _fv(facts, "underlying_schedule")
        or _fv(facts, "underlying_insurance_schedule")
    )
    if not _has_schedule:
        score -= 15

    # Follow-form evidence: -10 when unable to confirm (Option B per client Q4)
    _ff_combined = " ".join([
        _narrative_remarks_text(facts),
        str(_fv(facts, "umbrella_follow_form") or ""),
        str(_fv(facts, "policy_notes") or ""),
    ])
    if not _has_explicit_follow_form(_ff_combined):
        score -= 10  # Follow-form status unable to determine

    return max(0, score)


def _calculate_narrative_quality(
    facts: dict,
    has_narrative_doc: bool = False,
    flags: Optional[dict] = None,
    narrative_doc_text: str = "",
) -> Tuple[int, Dict[str, bool], int]:
    """P6 - Narrative Quality (10% of SQS) with §6.3 component model.

    Returns (score, component_breakdown, substance_pct) where component_breakdown
    is a per-component present/absent dict keyed by NARRATIVE_COMPONENT_LABELS and
    substance_pct is the 0-100 underwriting-substance half of the score.

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
    empty_components = {k: False for k in NARRATIVE_COMPONENT_LABELS}

    # §6.3 item 2: client-supplied narrative-enrichment answers (Bucket-C topics
    # the narrative lacked and the ARQ asked the client to provide). A filled
    # answer credits its component directly and joins the structured scan text so
    # both the component breakdown and the substance half reflect it.
    _enrich_present = _narrative_enrichment_present(facts)
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
        _prof_present = narrative_profile_present_map((flags or {}).get("narrative_profile"))
        if any(_prof_present.values()):
            components = dict(_prof_present)
            if _fv(facts, "carrier_marketing_reason"):
                components["carrier_market"] = True
            present_count = sum(1 for v in components.values() if v)
            component_pct = int(present_count / len(components) * 100)
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
    components = _score_narrative_components(remarks or ops)
    if narrative_doc_text:
        _body_components = _score_narrative_components(narrative_doc_text, strict=True)
        components = {
            k: bool(components.get(k) or _body_components.get(k))
            for k in NARRATIVE_COMPONENT_LABELS
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
    _prof_present = narrative_profile_present_map((flags or {}).get("narrative_profile"))
    if any(_prof_present.values()):
        components = {
            k: bool(components.get(k) or _prof_present.get(k))
            for k in NARRATIVE_COMPONENT_LABELS
        }
    # §6.3 item 2: credit any Bucket-C component the client supplied via the
    # narrative-enrichment ARQ (so an answered topic counts and is not re-asked).
    if any(_enrich_present.values()):
        components = {
            k: bool(components.get(k) or _enrich_present.get(k))
            for k in NARRATIVE_COMPONENT_LABELS
        }
    present_count = sum(1 for v in components.values() if v)
    total_count   = len(components)
    component_pct = int(present_count / total_count * 100) if total_count else 0

    # Underwriting substance quality for the 40% quality half. Per client
    # (DOUBTS-Workstream3, Narrative Quality): "score whether the narrative
    # provides meaningful underwriting context ... reward underwriting usefulness,
    # not writing length." This deliberately replaces the old character-count /
    # vocabulary-diversity measure with substance-signal detection - the client's
    # stated V1 preference, not a deviation from it.
    substance_pct = _score_narrative_substance(text)

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

    min_ok = all([
        bool(_fv(facts, "locations")),
        bool(_fv(facts, "occupancy_type")),
        bool(_fv(facts, "construction_type")),
        bool(_fv(facts, "property_building_value") or _fv(facts, "property_bpp_value")),
    ])

    if not min_ok:
        return 0

    # Tier 1 Required: 4 fields → drive Minimum-Viable 60 up toward ~80.
    _tier1 = ["year_built", "roof_year", "sprinkler_system", "fire_protection_class"]
    tier1_filled = [bool(_fv(facts, k)) for k in _tier1]
    tier1_count  = sum(tier1_filled)

    # Tier 2 Preferred: 4 client-approved fields → drive ~80 up to 100.
    # Each Tier 2 field is worth 5 pts so the four client-approved fields reach a
    # clean 100 (60 + 4×5 + 4×5) without relying on a special-case promotion.
    _tier2 = [
        "distance_to_hydrant", "fire_department_type",
        "business_income_limit", "period_of_restoration",
    ]
    tier2_filled = [bool(_fv(facts, k)) for k in _tier2]
    tier2_count  = sum(tier2_filled)

    # Decision_Tree.txt (L319/L398/L407): Minimum-Viable COPE floors Property
    # Integrity at ~60-70, NOT 30, and Carrier-Grade reaches 100. Base 60 also
    # keeps this in step with the per-form COPE path in calculate_sqs (also 60-
    # floored) - the two diverging (30 vs 60) was a real scoring bug.
    score = 60 + tier1_count * 5 + tier2_count * 5  # 60 + 0-20 + 0-20 = 60-100

    # ACV vs RCV conflict: -10 when the source documents and the generated-form
    # valuation basis disagree (client Property Integrity validation). Detection
    # is synonym-safe via _acv_rcv_conflict; the matching review flag is raised in
    # evaluate_stops so the conflict is surfaced, not silently deducted.
    if _acv_rcv_conflict(facts):
        score = max(0, score - 10)  # Valuation basis conflict (ACV vs RCV)

    return min(100, max(0, score))


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
    return int(sum(v * weights[k] * scale for k, v in active.items()))


# ── Score caps and credits ───────────────────────────────────────────────────
# Behaviour is UNCHANGED from the three inline copies this replaces: a cap is a
# CEILING, never a floor (a submission already below it keeps its own value - 42
# with a hard stop stays 42 and is never raised to 60), hard takes absolute
# precedence over soft, and stops never stack, so one hard stop and fifteen
# produce the identical ceiling. The only additions are a single source of truth
# and a recorded REASON, so a capped score can be audited without reading code.
#
# WORDING: hard stops and warnings do NOT block anything. Nothing in the product
# gates generation or download on them. Their only effect is the ceiling below
# plus the card rendered on screen. Do not reintroduce "blocked" language.

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
    per-form gates (COPE=0, umbrella=0, property hard/soft) that live outside
    either list.
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


def tier_for_score(score: int) -> Tuple[str, str, str]:
    """Return (grade, tier, tier_color) - the single tier ladder.

    A score of 90 or above is "Submission Ready" (owner decision, 2026-08-16).

    This boundary previously disagreed with itself in three places: both scorers
    used `> 90` while audit_routes._grade_from_score and BOTH frontend readiness
    surfaces ("Quote Ready" on the session list, "Ready to Send Submission" on
    the banner) used `>= 90`. A submission scoring exactly 90 therefore showed
    "Almost There" on its tier chip and "Ready to Send Submission" on the banner
    beside it. Everything now resolves through this function at `>= 90`, which
    is also where the "A" grade already sat, so the letter and the label agree.
    """
    score = int(score or 0)
    grade = "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 60 else "F"
    if score >= 90:
        return grade, "Submission Ready", "green"
    if score >= 80:
        return grade, "Almost There", "yellow"
    if score >= 70:
        return grade, "Needs Work", "orange"
    if score >= 60:
        return grade, "Major Gaps", "red"
    return grade, "Not Ready", "red"


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
    # Client Q2: surface a low/missing Employers Liability when umbrella is over WC.
    if flags.get("has_workers_comp"):
        _el_val = _to_int(_fv(facts, "employers_liability_limits"))
        if _el_val is None:
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
    _has_schedule = bool(
        _fv(facts, "schedule_of_underlying_insurance")
        or _fv(facts, "underlying_schedule")
        or _fv(facts, "underlying_insurance_schedule")
    )
    if not _has_schedule:
        warnings.append(
            "No Schedule of Underlying Insurance provided - umbrella adequacy "
            "reduced. Add the schedule of underlying GL / Auto / EL policies."
        )
    return warnings


def _build_umbrella_review_items(
    flags: dict, follow_form: dict, p5: Optional[int]
) -> List[dict]:
    """Persistent review items that must never be dropped by the top_recs cap
    (§6.5 item 5). Currently the follow-form gap when it cannot be confirmed."""
    items: List[dict] = []
    if flags.get("has_umbrella") and follow_form.get("status") == "unable_to_determine":
        items.append({
            "pillar":  "umbrella_limit_adequacy",
            "score":   p5 if p5 is not None else 0,
            "action":  "Unable to determine whether umbrella follows form. Recommend underwriter review.",
            "missing": ["umbrella follow-form confirmation"],
            "review_item": True,
        })
    return items


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
) -> dict:
    """
    Calculate package-level SQS with 6 spec-compliant pillars (Decision Tree v2.1.0+).
    Pillars: structural_completeness (25%) + exposure_consistency (25%) +
             property_integrity (15%) + loss_history_alignment (15%) +
             umbrella_limit_adequacy (10%) + narrative_quality (10%)
    """
    # Normalize mutable args - callers occasionally pass None when the session
    # field exists but is stored as null in the DB.
    hard_stops  = hard_stops  or []
    soft_stops  = soft_stops  or []
    cross_issues = cross_issues or []

    # Classified supporting-evidence presence feeds the narrative & loss-history
    # pillars so reclassifying a document measurably moves the score (§4.2).
    _present_types = _present_doc_types(session_data)
    _has_narrative = "narrative" in _present_types
    _has_loss_run  = "loss_run"  in _present_types
    _session_docs  = (session_data or {}).get("docs") or []

    lob = infer_lob(facts, flags)

    # P1 - Structural Completeness
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
    ]
    if _form_fill_rates:
        _fill_avg = int(sum(_form_fill_rates) / len(_form_fill_rates))
        p1 = int(tier1_score * 0.35 + tier2_score * 0.30 + _fill_avg * 0.35)
    elif mapped_data:
        # Spec 35/30/35: with no per-form structural score, the confidence fill rate
        # IS the Form Fill Quality component, carried at the same 35% weight.
        conf_rate = confidence_fill_rate(mapped_data, confidence_dict or {})
        p1 = int(tier1_score * 0.35 + tier2_score * 0.30 + conf_rate * 0.35)
    else:
        # No Form Fill Quality signal at all (lite path, no mapped data): drop that
        # 35% component and keep the remaining two in their spec 35:30 ratio
        # (0.35/0.65 and 0.30/0.65) so the proportion stays client-approved.
        p1 = int(tier1_score * 0.538 + tier2_score * 0.462)

    # P2 - Exposure Consistency
    _cross = list(cross_issues or [])
    # Building value conflict is a Hard Warning: if underwriting_consistency has flagged
    # property_building_value as review_required, surface it as a hard cross-issue so it
    # shows in the "Hard Stops" section and caps SQS at 60 until resolved (client spec).
    _uw_data = (session_data or {}).get("underwriting_consistency") or {}
    if any(
        f.get("fact_key") == "property_building_value" and f.get("review_required")
        for f in (_uw_data.get("fields") or [])
    ):
        _cross = _cross + [{
            "type": "hard_stop",
            "field": "property_building_value",
            "message": "Building value differs across submitted documents - confirm the correct value before generating forms",
        }]
    hard_cross = [i for i in _cross if isinstance(i, dict) and i.get("type") == "hard_stop"]
    warn_cross = [i for i in _cross if isinstance(i, dict) and i.get("type") in _CROSS_WARNING_TYPES]
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
    )

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
    cap_applied, cap_reason = _resolve_cap(
        hard_stops, soft_stops,
        hard_cross=[i.get("message") for i in hard_cross if isinstance(i, dict)],
    )
    raw = raw_uncapped if cap_applied is None else min(raw_uncapped, cap_applied)
    raw = max(0, min(100, raw))

    # Single tier ladder (tier_for_score). 90+ is "Submission Ready", matching
    # the frontend readiness surfaces and the "A" grade boundary.
    tier = tier_for_score(raw)[1]

    history   = list(session_data.get("sqs_history", []))
    stage     = calculation_stage
    timestamp = datetime.utcnow().isoformat() + "Z"

    # §6.2: track avg confidence fill rate per stage so the frontend can show
    # "Quality Fill Rate: X% → Y% after client questionnaire."
    _form_fill_rates = [
        r.get("confidence_fill_rate") for r in (form_results or [])
        if isinstance(r, dict) and r.get("confidence_fill_rate") is not None
    ]
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
    # N/A pillars (None) are excluded from recommendations entirely rather than
    # being given a fictitious 100, which would make the dict unsortable with mixed
    # types and could silently misrank other pillars when p5 is missing.
    _ranked_pillars = [
        (k, v) for k, v in sorted(
            ((k, v) for k, v in _pillar_scores.items() if v is not None),
            key=lambda x: x[1],
        ) if v < 90
    ][:3]
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
    if hard_stops or any(hard_cross):
        _hs_list = list(hard_stops) + [i.get("message", "") for i in hard_cross if i.get("message")]
        top_recs.append({"pillar": "hard_stops_present", "score": 0,
                          "action": _hs_list[0] if _hs_list else "Resolve hard stops to lift the SQS cap",
                          "missing": _hs_list[:3]})
    for pillar, score in _ranked_pillars:
        if len(top_recs) >= 3:
            break
        miss_list = _miss_by_pillar.get(pillar, [])
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
                    _action = miss_list[0] if miss_list else "Improve narrative quality"
        else:
            _action = miss_list[0] if miss_list else f"Improve {pillar.replace('_', ' ')}"
        top_recs.append({"pillar": pillar, "score": score,
                          "action": _action,
                          "missing": miss_list[:3]})

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
    review_items = _build_umbrella_review_items(flags, _follow_form, p5)
    # Surface the follow-form review item in top_recs too when there is still room
    # (max 3). It is never lost regardless - review_items carries it unconditionally.
    if review_items and len(top_recs) < 3:
        top_recs.append(review_items[0])

    # Umbrella warning messages for low underlying limits (client Q1/Q2: warn, not block)
    _umbrella_warnings = _build_umbrella_warnings(facts, flags, p5)

    return {
        "package_sqs_score": raw,
        # Audit trail for the cap (2026-08-16). `package_sqs_score` is what the
        # user sees; these three say what it would have been and why it was held.
        # raw_sqs_score is also the base every later credit is added to, so a
        # released cap returns the full value the submission actually earned.
        "raw_sqs_score":     raw_uncapped,
        "cap_applied":       cap_applied,
        "cap_reason":        cap_reason,
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
        "top_recommendations": top_recs,
        "sqs_history":         history,
        "delta_this_session":  delta,
        "routing_decision": (
            "auto_quote"      if raw > 85 else
            "priority_review" if raw >= 70 else
            "standard_review" if raw >= 50 else
            "hold"
        ),
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
        # Why the tier is what it is - which identifiers matched, which did
        # not, and any producer-facing note (DBA, FEIN-with-different-name).
        "loss_run_match_detail": _loss_run_detail,
        # Extraction Confidence: AI fill quality metric, reported separately from SQS (client spec).
        "extraction_confidence": _extraction_confidence,
    }


# ── SPEC-COMPLIANT SQS CALCULATION (v2.1.0+) ──────────────────────────────

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
    _has_loss_run  = "loss_run" in _present_types

    lob = infer_lob(facts, flags)

    # P1: Structural Completeness (ACORD 125 + required forms)
    tier1_ok, tier1_missing = check_tier1(facts, flags)
    tier2_score, tier2_missing = check_tier2(facts, flags)
    conf_rate = confidence_fill_rate(mapped_data or {}, confidence_dict or {})
    # Spec 35/30/35: Core Application / Underwriting Profile / Form Fill Quality.
    p1 = int((
        (100 if tier1_ok else max(0, 100 - len(tier1_missing) * 20)) * 0.35 +
        tier2_score * 0.30 +
        conf_rate * 0.35
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

    tier = tier_for_score(raw)[1]

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
    _review_items      = _build_umbrella_review_items(flags, _follow_form, p5)

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
        "top_recommendations": all_recs,
        "sqs_history": history,
        "delta_this_session": delta,
        "routing_decision": (
            "auto_quote" if raw >= 85 else
            "priority_review" if raw >= 70 else
            "standard_review" if raw >= 50 else
            "hold"
        ),
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
    * **Never promise more than exists.** Measured or fallback, the number is
      capped at the pillar's remaining headroom, so no card can offer points the
      pillar has already earned.
    * **Never let this break scoring.** Every simulation is wrapped; a failure
      leaves that card exactly as it is today.

    `is_exact` tells the UI whether it may drop the "up to" hedge. True only when
    the number came from a measurement.
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
        elif declared > 0 and headroom > 0:
            out[id(rec)] = (int(round(min(float(declared), headroom))), False)
        elif declared > 0:
            # The pillar is already full: this card cannot move the score, even
            # though it is still worth asking for. Saying so is the honest answer.
            out[id(rec)] = (0, True)

    return out


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
) -> dict:
    """Per-form SQS calculation with full metadata and structured recommendations."""
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
    is_cert_only = fid == "ACORD_25" or flags.get("is_certificate_doc", False)
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
                  or _fv(facts, "contact_email")), not _prod_exempt),
            ("producer name",     "producer_name",
             bool(_fv(facts, "producer_name")),     not _prod_exempt),
        ]
        chks = [ok for _l, _f, ok, scored in _checks if scored]
        struct = int(sum(chks) / len(chks) * 100) if chks else 100
        missing = [(l, f) for l, f, ok, _scored in _checks if not ok]
        for label, field_name in missing:
            recommendations.append({
                "rec_id": f"rec_{field_name}",
                "field": field_name,
                "component": "structural_completeness",
                "message": f"ACORD 125 missing: {label}",
                "type": "missing_field",
                "score_impact": 15 if field_name in TIER1_FIELDS else 8,
                "priority": 1 if field_name in TIER1_FIELDS else 2,
            })

    elif fid == "ACORD_126":
        # GL class-code data may arrive in either the legacy location→codes fact
        # or the richer schedule-of-hazards fact (class code + premium/exposure
        # basis + exposure amount + subcontractor %). Either satisfies the gap.
        _gl_class_present = bool(
            _fv(facts, "gl_class_codes_by_location") or _fv(facts, "gl_class_code_schedule")
        )
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

    elif fid in ("ACORD_140", "ACORD_141"):
        min_cope = [
            bool(_fv(facts, "locations")),
            bool(_fv(facts, "occupancy_type")),
            bool(_fv(facts, "construction_type")),
            bool(_fv(facts, "property_building_value") or _fv(facts, "property_bpp_value")),
        ]
        if not all(min_cope):
            struct = 0
            issues.append("Minimum Viable COPE incomplete - hard stop")
            recommendations.append({
                "rec_id": "rec_min_cope",
                "field": "locations",
                "component": "property_integrity",
                "message": "Required: street address, occupancy, construction type, and building or BPP value",
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
            _t2_ok = [bool(_fv(facts, k)) for k, _ in _cope_t2]
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
        # Builders Risk: project address + project cost + completion date are hard gates
        br_required = [
            ("builders_risk_project_address", "project address"),
            ("builders_risk_project_cost",    "project cost / contract value"),
            ("builders_risk_completion_date", "anticipated completion date"),
        ]
        br_chks = [bool(_fv(facts, k)) for k, _ in br_required]
        if not all(br_chks):
            struct = 0
            for (fk, lbl), ok in zip(br_required, br_chks):
                if not ok:
                    issues.append(f"Builders Risk missing required field: {lbl}")
                    recommendations.append({
                        "rec_id": f"rec_{fk}",
                        "field": fk,
                        "component": "structural_completeness",
                        "message": f"Builders Risk requires {lbl}",
                        "type": "hard_stop",
                        "score_impact": 0,
                        "priority": 1,
                    })
        else:
            br_optional = [bool(_fv(facts, k)) for k in [
                "builders_risk_construction_type",
                "builders_risk_owner_name",
                "builders_risk_contractor_name",
                "builders_risk_insured_interest",
            ]]
            struct = int(70 + (sum(br_optional) / len(br_optional)) * 30)

    elif fid in ("ACORD_137_CA", "ACORD_137_CO"):
        # State commercial auto supplement: auto symbols and limits drive completeness.
        auto_chks = [
            bool(_fv(facts, "auto_liability_limit")),
            bool(_fv(facts, "auto_covered_symbols")),
            bool(_fv(facts, "auto_um_uim_limit")),
            bool(_fv(facts, "auto_deductible_comp") or _fv(facts, "auto_deductible_collision")),
        ]
        struct = int(sum(auto_chks) / len(auto_chks) * 100)
        if not _fv(facts, "auto_liability_limit"):
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
        # Inland Marine: item schedule or total value required
        im_has_value = bool(_fv(facts, "inland_marine_total_value"))
        im_has_items = bool(_fv(facts, "inland_marine_items"))
        if not im_has_value and not im_has_items:
            struct = 0
            issues.append("Inland Marine missing item schedule and total value")
            recommendations.append({
                "rec_id": "rec_im_schedule",
                "field": "inland_marine_items",
                "component": "structural_completeness",
                "message": "Provide inland marine item schedule or total insured value",
                "type": "hard_stop",
                "score_impact": 0,
                "priority": 1,
            })
        else:
            struct = 60 if (im_has_value or im_has_items) else 0
            if im_has_value and im_has_items:
                struct = 90
            if _fv(facts, "inland_marine_transit_limit"):
                struct = min(100, struct + 10)

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
        chks = [
            bool(_fv(facts, "auto_vin_schedule") or _fv(facts, "vehicle_schedule")),
            bool(_fv(facts, "auto_liability_limit")),
            bool(_fv(facts, "auto_garaging_address") or _fv(facts, "locations")),
            bool(_fv(facts, "auto_drivers")),
            bool(_fv(facts, "auto_covered_symbols")),
            bool(_fv(facts, "auto_radius_of_operation")),
        ]
        struct = int(sum(chks) / len(chks) * 100)
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
        chks = [
            bool(_fv(facts, "umbrella_limit")),
            bool(_fv(facts, "umbrella_sir") or _fv(facts, "umbrella_attachment_point")),
            bool(_fv(facts, "gl_limits") or _fv(facts, "gl_each_occurrence")),
            bool(_fv(facts, "auto_liability_limit")),
            bool(_fv(facts, "employers_liability_limits")),
        ]
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
        chks = [
            bool(_fv(facts, "applicant_name")),
            bool(_fv(facts, "effective_date") and _fv(facts, "expiration_date")),
            bool(_fv(facts, "policy_number")),
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
            bool(_fv(facts, "form_reference")),
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
        chks = [
            bool(_fv(facts, "gl_class_codes_by_location")),
            bool(_fv(facts, "total_payroll") or _fv(facts, "total_revenue")),
            bool(_fv(facts, "operations_description")),
            bool(_fv(facts, "gl_limits")),
        ]
        exp_score = int(sum(chks) / len(chks) * 100)
        _gl_codes = _fv(facts, "gl_class_codes_by_location")
        if isinstance(_gl_codes, list) and _gl_codes:
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
        chks = [
            bool(_fv(facts, "auto_liability_limit")),
            bool(_fv(facts, "auto_liability_structure")),
            bool(_fv(facts, "auto_covered_symbols")),
            bool(_fv(facts, "auto_radius_of_operation")),
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
        chks = [
            bool(_fv(facts, "umbrella_limit")),
            bool(_fv(facts, "gl_limits") or _fv(facts, "gl_each_occurrence")),
            bool(_fv(facts, "auto_liability_limit")),
            bool(_fv(facts, "umbrella_sir") or _fv(facts, "umbrella_attachment_point")),
        ]
        exp_score = int(sum(chks) / len(chks) * 100)

    elif fid == "ACORD_28":
        chks = [
            bool(_fv(facts, "property_building_value") or _fv(facts, "property_bpp_value")),
            bool(_fv(facts, "policy_number")),
            bool(_fv(facts, "mortgagee_name") or _fv(facts, "certificate_holder")),
            bool(_fv(facts, "effective_date") and _fv(facts, "expiration_date")),
        ]
        exp_score = int(sum(chks) / len(chks) * 100)

    elif fid == "ACORD_101":
        remarks_text = _narrative_remarks_text(facts) or str(_fv(facts, "remarks_text") or "")
        chks = [
            bool(_fv(facts, "form_reference")),
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
    _prop_hard = False
    _prop_soft = False

    if fid in ("ACORD_140", "ACORD_141"):
        prop = struct
        # BI coverage: BI limit present but period of restoration missing → hard stop per document
        if _fv(facts, "business_income_limit") and not _fv(facts, "period_of_restoration"):
            _prop_hard = True
            issues.append("Business income limit present but period of restoration not specified")
            recommendations.append({
                "rec_id": "rec_period_of_restoration",
                "field": "period_of_restoration",
                "component": "property_integrity",
                "message": "Provide Period of Restoration for Business Income coverage",
                "type": "hard_stop",
                "score_impact": 0,
                "priority": 1,
            })
        # Valuation method soft block
        if not _fv(facts, "valuation_method"):
            _prop_soft = True
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
        if flags.get("property_has_peril_deductibles"):
            missing_perils = [
                (f, lbl) for f, lbl in [
                    ("property_deductible_wind",       "wind/hail"),
                    ("property_deductible_earthquake", "earthquake"),
                    ("property_deductible_flood",      "flood"),
                ]
                if not _fv(facts, f)
            ]
            if missing_perils:
                _prop_hard = True
                for fk, lbl in missing_perils:
                    issues.append(f"Peril-specific {lbl} deductible referenced but not defined")
                recommendations.append({
                    "rec_id": "rec_peril_deductibles",
                    "field": "property_deductible_wind",
                    "component": "property_integrity",
                    "message": "Define peril deductibles: " + ", ".join(l for _, l in missing_perils),
                    "type": "hard_stop",
                    "score_impact": 0,
                    "priority": 1,
                })
        # Coinsurance: if value present but coinsurance missing → soft block
        if (_fv(facts, "property_building_value") or _fv(facts, "property_bpp_value")) and \
                not _fv(facts, "coinsurance_percentage") and not _fv(facts, "agreed_value_endorsement"):
            _prop_soft = True
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

    elif fid not in ("ACORD_140", "ACORD_141") and flags.get("has_property_coverage"):
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
            prop = 60 + sum(bool(_fv(facts, k)) for k in _p_t1) * 5 + sum(bool(_fv(facts, k)) for k in _p_t2) * 5
    else:
        prop = 100

    # Property delta penalties (non-140/141 forms that have property exposure)
    if fid not in ("ACORD_140", "ACORD_141") and flags.get("has_property_coverage"):
        if not _fv(facts, "valuation_method"):
            prop = max(0, prop - 5)

        if _fv(facts, "business_income_limit") and not _fv(facts, "period_of_restoration"):
            _prop_soft = True
            issues.append("BI coverage present but period of restoration not specified")

        if flags.get("property_has_peril_deductibles"):
            _missing_perils = [
                label for label, key in [
                    ("wind/hail", "property_deductible_wind"),
                    ("earthquake", "property_deductible_earthquake"),
                    ("flood", "property_deductible_flood"),
                ]
                if not _fv(facts, key)
            ]
            if _missing_perils:
                _prop_hard = True
                issues.append(
                    "Peril-specific deductible referenced but not defined: "
                    + ", ".join(_missing_perils)
                )

        if (
            (_fv(facts, "property_building_value") or _fv(facts, "property_bpp_value"))
            and not _fv(facts, "coinsurance_percentage")
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
        # C2 2.1 (found on the 2026-08-24 live run): an "Underwriting advisory
        # (no score effect)" card - and the informational New Venture notices -
        # must not carry the typed +8 literal. The chip ("up to +8 pts") would
        # contradict the card's own text, and dismissing it with a reason would
        # CREDIT points an advisory can never earn back (impact measurement
        # skips field-less recs, so the literal survived un-corrected).
        _no_impact = rec_msg.lower().startswith(
            ("underwriting advisory", "new venture confirmed",
             "new venture status conflicts"))
        recommendations.append({
            "rec_id": _loss_rec_id(rec_msg),
            # Was hardcoded "loss_history_years" for EVERY loss message, so the
            # "confirm No Known Losses" card wrote the attestation into a year
            # count and the score could never move. See
            # _LOSS_RECOMMENDATION_FIELDS.
            "field": loss_recommendation_field(rec_msg),
            "component": "loss_history_alignment",
            "message": rec_msg,
            "type": "suggestion",
            "score_impact": 0 if _no_impact else 8,
            "priority": 3 if _no_impact else 2,
            # Structured flag so requires_supporting_document detection in arq_service
            # doesn't rely on keyword scanning of message strings.
            "requires_doc": any(p in rec_msg.lower() for p in _loss_doc_phrases),
        })
    breakdown["loss_history_alignment"] = loss_score

    # ── Umbrella / limit adequacy (None = N/A, weights re-normalised) ────────
    umbrella_score = _calculate_umbrella_adequacy(facts, flags)
    if flags.get("has_umbrella") and umbrella_score is not None and umbrella_score == 0:
        issues.append("Umbrella detected but no underlying GL/Auto limits")
        recommendations.append({
            "rec_id": "rec_underlying_limits",
            "field": "gl_limits",
            "component": "umbrella_limit_adequacy",
            "message": "Provide underlying limits",
            "type": "hard_stop",
            "score_impact": 0,
            "priority": 1,
        })
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
    )
    breakdown["narrative_quality"] = narrative_score

    # §6.3 AC#4: per-component gap as a targeted recommendation.
    if _narrative_components and narrative_score < 80:
        _absent_comps = [
            NARRATIVE_COMPONENT_LABELS[k]
            for k, present in _narrative_components.items()
            if not present
        ]
        if _absent_comps:
            _comp_msg = _narrative_gap_message(_narrative_components)
            recommendations.append({
                "rec_id":       "rec_narrative_components",
                "field":        "acord101_remarks",
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
                "field":        "acord101_remarks",
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
    cope_hard = fid in ("ACORD_140", "ACORD_141", "ACORD_133") and breakdown["property_integrity"] == 0
    umb_fail  = flags.get("has_umbrella") and umbrella_score is not None and umbrella_score == 0

    # Preserve the UNCAPPED score before the ceiling is applied (2026-08-16).
    # It used to be overwritten, so a capped form score could not be told apart
    # from a genuinely low one, and later credits had to compound off the capped
    # value instead of the real one.
    raw_uncapped = max(0, min(100, raw_score))
    cap_applied, cap_reason = _resolve_cap(
        hard_stops, soft_stops,
        extra_hard_reason=(
            "Minimum Viable COPE incomplete" if cope_hard else
            "Umbrella present with no underlying GL or Auto limits" if umb_fail else
            "Property integrity gate" if _prop_hard else None
        ),
        extra_soft_reason="Property integrity warning" if _prop_soft else None,
    )
    if cap_applied is not None:
        raw_score = min(raw_score, cap_applied)

    # fraud_penalty is applied AFTER the cap, exactly as before. It is currently
    # always 0 (never assigned anywhere), so this ordering is behaviour-neutral -
    # it is preserved rather than "improved" so nothing shifts silently.
    raw_score = max(0, raw_score - fraud_penalty)

    # ── Tier and routing ──────────────────────────────────────────────────────
    # Single tier ladder (tier_for_score), shared with the package scorer and
    # audit_routes, so the form chip and the package chip can never disagree.
    _grade_label, tier, tc = tier_for_score(raw_score)
    routing = (
        "auto_quote"      if raw_score > 85 else
        "priority_review" if raw_score >= 70 else
        "standard_review" if raw_score >= 50 else
        "hold"
    )

    # ── What each recommendation is ACTUALLY worth ────────────────────────────
    # Replaces the hand-typed score_impact literals with a measurement. See
    # _measure_recommendation_impacts for why, and for the three things it
    # refuses to do. Runs before the sort so the ordering uses the real numbers -
    # the biggest genuine win leads, which the typed literals could not deliver.
    if not _simulate:
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
        )
        for _rec in recommendations:
            _measured = _rec_impacts.get(id(_rec))
            if _measured is None:
                continue
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

    return {
        "sqs_score":           raw_score,
        # Cap audit trail (2026-08-16) - see calculate_package_sqs for the rule.
        "raw_sqs_score":       raw_uncapped,
        "cap_applied":         cap_applied,
        "cap_reason":          cap_reason,
        "tier":                tier,
        "tier_color":          tc,
        "grade":               _grade_label,   # from the shared tier ladder
        "routing_decision":    routing,
        "breakdown":           breakdown,   # umbrella_limit_adequacy may be None
        "risk_drivers":        risk_drivers,
        "issues":              issues,
        "recommendations":     recommendations,
        "fraud_penalty":       fraud_penalty,
        "fill_rate":           fill_rate,
        "match_score":         fill_rate,   # §6.1 AC#1: raw field coverage — distinct from SQS and confidence_fill_rate
        "confidence_fill_rate": conf_rate,
        "extraction_confidence": conf_rate,  # AI fill quality - same value, distinct label per client spec
        "form_id":             fid,
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
    ignored_recs: List[str]
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

One paragraph only. State the main gap and the single most impactful next action. Do NOT repeat the numeric score, the tier name, or any point totals in your answer - the interface displays those separately, and a restated number that drifts from the displayed one reads as a contradiction."""

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
    ],
    "ACORD_130": [
        "wc_payroll", "wc_class_codes", "wc_xmod", "wc_officer_exclusions",
        "total_payroll", "num_employees", "applicant_name", "effective_date",
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
        "remarks_text", "form_reference", "explanation_of_yes_answers",
    ],
    "ACORD_133": [
        "project_address", "project_cost", "completion_date",
        "construction_type", "owner_name", "contractor_name",
        "insured_interest", "applicant_name", "effective_date",
    ],
    "ACORD_141": [
        "locations", "scheduled_item_description", "scheduled_item_value",
        "valuation_method", "deductible_aop", "deductible_wind",
        "deductible_earthquake", "deductible_flood",
        "coinsurance_percentage", "applicant_name", "effective_date",
    ],
    "ACORD_160": [
        "inland_marine_item_description", "inland_marine_item_value",
        "transit_exposure", "schedule_duration",
        "applicant_name", "effective_date",
    ],
    "ACORD_186": [
        "contractor_type", "subcontracted_percentage", "residential_commercial_split",
        "high_hazard_operations", "licensing_details",
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
    a person? Reads the RAW envelope (not `_fv`) so `value_state` survives."""
    return _fact_is_filled((facts or {}).get(key))


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
    inventory = FORM_FIELD_INVENTORY.get(fid, list(facts.keys()))

    synthetic_mapped = {k: _fv(facts, k) for k in inventory}
    filled = sum(1 for k in inventory if _fact_is_filled(_fv(facts, k)))
    schema_size = len(inventory)

    # Derive classified-doc presence + loss-run insured match from the session so
    # this path credits the same evidence the in-flow per-form path does.
    _docs       = (session_data or {}).get("docs") or []
    _present    = {str(d.get("doc_type") or "").strip() for d in _docs if isinstance(d, dict) and not d.get("excluded")}
    _has_narr   = "narrative" in _present
    _has_loss   = "loss_run" in _present
    _loss_match = _check_loss_run_insured_match(_docs, _fv(facts, "applicant_name"))

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
    )
