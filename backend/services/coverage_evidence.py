"""coverage_evidence.py - THE ONE DOOR for "what does this package positively
evidence about a coverage line's exposure?"

Client master plan section 6 (Coverage-Specific SQS Gap Closure), H1,
2026-08-26. Read `v1-20AUG.md` entry H1 before changing anything here.

WHY THIS MODULE EXISTS
----------------------
Spec section 10 says the package score is computed independently of the
per-form scores, by design (D29). So any fact that is scored ONLY on a
per-form checklist has zero submission-level weight - which is exactly the
client's 6.3 / 6.4 complaint: an ACORD 127 with no vehicles, no drivers, no
garaging and no radius, or an ACORD 130 with no X-Mod / officer treatment /
payroll period, scores badly on its own form and barely moves the package.

Three questions used to be answered by whoever needed them, each with a
local guess. They are answered HERE, once, and read by the package scorer
(`sqs_service._calculate_exposure_consistency`), the ceiling engine
(`sqs_service.evaluate_stops`), the per-form ACORD 127 checklist, the fact
state axis (`fact_state.derive_value_state` -> the questionnaire) and the
coverage-flag recompute on the edit path (`routes/form_routes.update_pdf`):

  1. Is this an OWNED-vehicle auto account, an HNOA-only one, or can we not
     tell?                                        -> auto_exposure_kind()
  2. Which of the client's five Auto Completeness items are missing?
                                                   -> auto_completeness_gaps()
  3. What state is each of the three supplemental WC items in?
                                                   -> wc_xmod_status()
                                                      wc_officer_treatment_status()
                                                      wc_payroll_period_status()
  4. Is a coverage flag still supported by ANY positive evidence once the
     producer edits a field?                       -> coverage_flag_supported()

EVERY DECISION HERE IS FROM POSITIVE EVIDENCE (core principle 3). Silence is
never "no", never "N/A" and never "owned". The two places the client's own
document tells us to default are recorded as owner rulings:

  * an auto line with nothing saying owned OR hired/non-owned is PRESUMED
    OWNED (owner 2026-08-26, reading 6.3's "genuinely Hired/Non-Owned only"
    as positive evidence to exempt) - `AUTO_UNKNOWN` still comes back from
    `auto_exposure_kind` so the trace can say "presumed";
  * "clearly annual" payroll is satisfied by the MEANING of the label the
    figure was printed under, not one spelling of it (owner 2026-08-26).

NO LLM ANYWHERE IN THIS FILE, by the same ruling that governs
`answer_semantics` - determinism and latency, not cost.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Auto exposure kind ───────────────────────────────────────────────────────

AUTO_NONE      = "none"        # no auto line in the submission
AUTO_OWNED     = "owned"       # positive evidence of owned / scheduled autos
AUTO_HNOA_ONLY = "hnoa_only"   # positive evidence the line is hired/non-owned ONLY
AUTO_UNKNOWN   = "unknown"     # an auto line, and nothing says either way

# The five owned-vehicle facts the client's 6.3 deductions read. Also the set
# `fact_state` marks Not Applicable on an HNOA-only account, so the
# questionnaire stops asking for a vehicle list nobody has (6.3: "do not
# require an owned vehicle schedule ... do not penalize").
OWNED_VEHICLE_FACTS: Tuple[str, ...] = (
    "auto_vin_schedule",
    "auto_drivers",
    "auto_garaging_addresses",
    "auto_radius_of_operation",
    "auto_vehicle_use",
)

# 6.3 Deductions, verbatim from the client's table. The order is the order
# they render in.
AUTO_COMPLETENESS_RULES: Tuple[Tuple[str, int, str], ...] = (
    ("auto_vin_schedule",        15, "No vehicle schedule"),
    ("auto_drivers",             10, "No driver schedule"),
    ("auto_garaging_addresses",   5, "No garaging information"),
    ("auto_radius_of_operation",  5, "No radius of operation"),
    ("auto_vehicle_use",          5, "No vehicle-use information"),
)
AUTO_COMPLETENESS_CAP = 25          # 6.3 "Bucket Cap"

# 6.4 Supplemental WC. Cap is the client's; the three points values are his.
WC_XMOD_POINTS            = 5
WC_OFFICER_POINTS         = 5
WC_PAYROLL_PERIOD_POINTS  = 3
WC_SUPPLEMENTAL_CAP       = 10

# Status vocabulary shared by the three WC readers. `MISSING` is the only
# state that deducts; `UNKNOWN` routes to the producer with NO deduction
# (6.4: "if applicability is unknown -> route to producer before scoring it
# missing"; core principle 7).
STATUS_SATISFIED      = "satisfied"
STATUS_NOT_APPLICABLE = "not_applicable"
STATUS_MISSING        = "missing"
STATUS_UNKNOWN        = "unknown"


# ── Small readers (no other module's shape guessed) ──────────────────────────

_EMPTY_STRINGS = frozenset({"", "null", "none", "n/a", "na", "[]", "{}"})


def _unwrap(raw: Any) -> Tuple[Any, dict]:
    """(value, envelope) - the same split `fact_state._unwrap` makes."""
    if isinstance(raw, dict) and "value" in raw:
        return raw.get("value"), raw
    return raw, {}


def _fv(facts: Optional[dict], key: str) -> Any:
    """The bare value, or None when blank. Mirrors sqs_service._fv."""
    if not isinstance(facts, dict):
        return None
    value, _ = _unwrap(facts.get(key))
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return value if value else None
    if isinstance(value, bool):
        return value
    text = str(value).strip()
    if text.lower() in _EMPTY_STRINGS:
        return None
    return text


def _recorded_state(facts: Optional[dict], key: str) -> Optional[str]:
    """A value_state a HUMAN or the answer door recorded on the envelope.

    Read directly off the envelope - NEVER through `fact_state.value_state_of`
    - because `fact_state.derive_value_state` calls back into this module for
    the owned-vehicle facts, and the round trip would recurse.
    """
    if not isinstance(facts, dict):
        return None
    _, env = _unwrap(facts.get(key))
    state = env.get("value_state")
    return str(state) if state else None


def _human_recorded_state(facts: Optional[dict], key: str) -> Optional[str]:
    """`_recorded_state`, but ONLY when a person put it there.

    `_recorded_state`'s docstring says "a value_state a HUMAN or the answer door
    recorded", and that stopped being the whole truth once
    `fact_state.annotate_fact_states` began writing DERIVED states back onto the
    envelope it annotates. That closes a loop wherever a status function both
    feeds the Not Applicable axis and reads the recorded state back:

        h1 says Not Applicable -> annotate persists value_state=not_applicable
        -> the status function reads it as authoritative -> Not Applicable
        FOREVER, even after the evidence that produced it is edited away.

    Measured for `wc_payroll_period` (2026-08-27): once a package with no
    payroll figure had been annotated, adding a real bare payroll figure could
    never make the client's -3 fire again. Gating on provenance breaks the loop
    at the only place it can be broken - a human's "this does not apply" is a
    statement about the world and must persist; our own derivation is a
    conclusion and must be recomputed from the evidence every time.
    """
    if not isinstance(facts, dict):
        return None
    _, env = _unwrap(facts.get(key))
    state = env.get("value_state")
    if not state:
        return None
    try:
        from services.fact_state import _HUMAN_SOURCES
        human = _HUMAN_SOURCES
    except Exception:                                         # noqa: BLE001
        human = {"producer", "client_arq", "client"}
    return str(state) if str(env.get("source") or "").lower() in human else None


def _answered(facts: Optional[dict], key: str) -> bool:
    """Did anyone ANSWER this - a value, an explicit "none", or an N/A?

    Delegates to the one answer door so "None" is never a gap (Brent
    2026-08-24). Falls back to a value test if the door is unavailable.
    """
    if not isinstance(facts, dict):
        return False
    raw = facts.get(key)
    try:
        from services.answer_semantics import fact_answered
        return bool(fact_answered(raw))
    except Exception:                                         # noqa: BLE001
        return _fv(facts, key) is not None


def _flag(flags: Optional[dict], name: str) -> bool:
    return bool(isinstance(flags, dict) and flags.get(name) is True)


def _rows(facts: Optional[dict], key: str) -> List[Any]:
    """Non-empty rows of a list fact - a row is real when it carries at least
    one non-blank cell (a list of bare "" strings is not a schedule)."""
    val = _fv(facts, key)
    if not isinstance(val, list):
        return []
    out: List[Any] = []
    for row in val:
        if isinstance(row, dict):
            if any(str(v).strip() and str(v).strip().lower() not in _EMPTY_STRINGS
                   for v in row.values() if v is not None and not isinstance(v, bool)) \
                    or any(v is True for v in row.values()):
                out.append(row)
        elif row is not None and str(row).strip() \
                and str(row).strip().lower() not in _EMPTY_STRINGS:
            out.append(row)
    return out


_TRUE_WORDS = frozenset({"y", "yes", "true", "1", "on", "included", "include",
                         "excluded", "exclude", "x"})


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in _TRUE_WORDS


# ── 1. Owned versus hired/non-owned ───────────────────────────────────────────

_HNOA_LINE_RE = re.compile(r"\b(hired|non[\s-]?owned|hnoa)\b", re.I)


def _auto_lines(facts: Optional[dict]) -> Tuple[List[str], List[str]]:
    """(all granted auto line names, the subset that name only hired/non-owned).

    Reads `coverage_lines` through the extraction module's own grant predicate
    and `lob_canon`, so a "Hired and Non-Owned Auto" line is recognised by the
    same rule every other coverage decision uses. Fail-open: an unreadable
    list contributes nothing.
    """
    lines = _fv(facts, "coverage_lines")
    if not isinstance(lines, list):
        return [], []
    try:
        from services.extraction_service import _line_entry_grants_coverage
        from services.lob_canon import canon_line
    except Exception:                                         # noqa: BLE001
        return [], []
    granted: List[str] = []
    hnoa: List[str] = []
    for entry in lines:
        if not isinstance(entry, dict) or not entry.get("line"):
            continue
        try:
            if not _line_entry_grants_coverage(entry):
                continue
            if canon_line(str(entry["line"])) != "auto":
                continue
        except Exception:                                     # noqa: BLE001
            continue
        name = str(entry["line"]).strip()
        granted.append(name)
        if _HNOA_LINE_RE.search(name):
            hnoa.append(name)
    return granted, hnoa


def _owned_symbol_evidence(facts: Optional[dict]) -> Optional[bool]:
    """True = a captured symbol designates owned/scheduled autos; False = the
    captured symbols are known and reach only hired/non-owned; None = cannot
    say (nothing captured, or an unrecognised symbol)."""
    try:
        from services import auto_symbols as sym
    except Exception:                                         # noqa: BLE001
        return None
    nums = sym.liability_symbols(facts or {})
    if not nums:
        # No liability symbol - a physical-damage symbol still tells us the
        # account owns what it insures against damage.
        nums = sym.symbols_for(facts or {}, *sym.PHYSICAL_DAMAGE_KEYS)
        if not nums:
            return None
    owned = sym.covers(nums, sym.OWNED)
    scheduled = sym.covers(nums, sym.SCHEDULED)
    if owned is None or scheduled is None:
        return None
    if owned or scheduled:
        return True
    hired = sym.covers(nums, sym.HIRED)
    nonowned = sym.covers(nums, sym.NONOWNED)
    if hired or nonowned:
        return False
    return None


def auto_exposure_kind(facts: Optional[dict], flags: Optional[dict] = None) -> str:
    """OWNED / HNOA_ONLY / NONE / UNKNOWN - from positive evidence only.

    `flags=None` means "the caller has no flags" (e.g. the fact-state axis
    running on a bare facts dict): the NONE branch is skipped and the kind is
    judged from the facts alone.

    OWNED evidence (any one suffices):
      * a vehicle schedule with at least one real row;
      * a captured covered-auto symbol that designates owned or specifically
        described autos (1 / 2 / 3 / 4 / 7 and the truckers/motor-carrier
        equivalents - `auto_symbols` decides, never a local list);
      * comp/collision coverage on the policy (`auto_has_physical_damage`) or
        either physical-damage deductible - nobody insures a non-owned car
        against collision;
      * a garaging address - only an owned fleet is garaged.
    HNOA_ONLY evidence (checked only when nothing says owned):
      * the captured symbols are recognised and reach hired and/or non-owned
        autos and NOT owned ones (8 / 9 alone is the classic shape);
      * a human recorded "none / no owned vehicles" on the vehicle schedule;
      * every granted auto line in `coverage_lines` names hired/non-owned.
    """
    if flags is not None and not _flag(flags, "has_auto_coverage"):
        return AUTO_NONE

    if _rows(facts, "auto_vin_schedule") or _rows(facts, "vehicle_schedule"):
        return AUTO_OWNED
    sym_evidence = _owned_symbol_evidence(facts)
    if sym_evidence is True:
        return AUTO_OWNED
    if _flag(flags, "auto_has_physical_damage"):
        return AUTO_OWNED
    if _fv(facts, "auto_deductible_comp") or _fv(facts, "auto_deductible_collision"):
        return AUTO_OWNED
    if _rows(facts, "auto_garaging_addresses"):
        return AUTO_OWNED

    if sym_evidence is False:
        return AUTO_HNOA_ONLY
    if _recorded_state(facts, "auto_vin_schedule") in ("explicit_no", "not_applicable"):
        return AUTO_HNOA_ONLY
    granted, hnoa = _auto_lines(facts)
    if granted and len(hnoa) == len(granted):
        return AUTO_HNOA_ONLY

    return AUTO_UNKNOWN


def auto_completeness_applies(facts: Optional[dict], flags: Optional[dict]) -> bool:
    """6.3: "Only apply when the account has owned/scheduled Auto exposure."

    OWNER RULING 2026-08-26: an auto line that says neither owned nor
    hired/non-owned is presumed OWNED - the client's wording "genuinely
    Hired/Non-Owned Auto only" is positive evidence to exempt, and the
    submission with no vehicle information at all is precisely the one 6.3
    exists to catch. NONE and HNOA_ONLY never apply.
    """
    return auto_exposure_kind(facts, flags) in (AUTO_OWNED, AUTO_UNKNOWN)


# Facts that do not apply on a hired/non-owned-only line: the five owned-
# vehicle facts the 6.3 deductions read, PLUS the physical-damage facts (nobody
# insures a non-owned car against collision) and the return-to-yard question.
# LIVE RUN P3 (2026-08-26): the account with no vehicles was still asked for
# comp / collision deductibles, the physical-damage valuation and "do your
# vehicles return to the yard".
HNOA_INAPPLICABLE_FACTS: Tuple[str, ...] = OWNED_VEHICLE_FACTS + (
    "auto_deductible_comp",
    "auto_deductible_collision",
    "auto_physical_damage_valuation",
    "vehicles_return_to_premises",
)

# Questions that ask for the experience mod under a key that is NOT the fact.
# `narrative_target_markets` is the narrative slot repurposed to ask the EMOD
# (see question_eligibility.INSURANCE_JUDGMENT_QUESTION_KEYS); it inherits
# `wc_xmod`'s applicability so a confirmed New Venture is not asked twice.
_XMOD_QUESTION_ALIASES: Tuple[str, ...] = ("wc_xmod", "narrative_target_markets")


def auto_liability_stated(facts: Optional[dict]) -> bool:
    """Is the auto liability limit STATED - as a combined single limit OR as
    split limits? LIVE RUN P5 (2026-08-26): a split-limit policy ($250K /
    $500K / $100K printed) lost 10 Exposure points for "Auto coverage with no
    liability limit" and asked the producer for a CSL, because every reader
    looked only at `auto_liability_limit`, which is EMPTY by design on a split
    policy (the extractor is told never to copy a split part into the CSL
    box). Split parts stated = the limit is stated."""
    if _fv(facts, "auto_liability_limit"):
        return True
    return bool(_fv(facts, "auto_bi_per_person") or _fv(facts, "auto_bi_per_accident")
                or _fv(facts, "auto_pd_per_accident"))


def auto_split_limits_stated(facts: Optional[dict]) -> bool:
    """Split limits are on the policy (any part printed, or the structure says
    so) and no CSL is - so a CSL question / CSL-only deduction does not apply."""
    if _fv(facts, "auto_liability_limit"):
        return False
    if str(_fv(facts, "auto_liability_structure") or "").strip().lower() == "split":
        return True
    return bool(_fv(facts, "auto_bi_per_person") or _fv(facts, "auto_bi_per_accident")
                or _fv(facts, "auto_pd_per_accident"))


# ── "We do not have that document" versus a document that mentions a gap ─────
#
# LIVE RUN P1 (2026-08-26): the document's own sentence "the schedule of
# underlying insurance was not supplied" was extracted as the schedule's
# VALUE, so the -15 never fired and the umbrella pillar read 40 instead of 25.
# Principle 3: a negation is not data.
#
# THE FIRST CUT OF THIS WAS WORSE THAN THE DEFECT, and the reasoning is worth
# keeping. It scanned the whole value for any negation near a supply verb, so
# a REAL schedule reading "GL $1M/$2M; Auto $1M CSL; Employers Liability not
# included" was deleted and charged -15 - a wrong VALUE, which is the
# direction this codebase's blank-over-wrong rule exists to prevent. Measured:
# 13 of 14 realistic broker schedules were destroyed. It is the same mistake
# as the `_quote_restates_the_question` "not"-stopword defect (CLAUDE.md,
# 2026-08-12): a negation ABOUT ONE LINE inside a document is not a statement
# about the document.
#
# The rule now has a structural first condition, exactly as that fix did:
#
#   1. a value that CARRIES SCHEDULE DATA is a schedule, whatever else it says;
#   2. otherwise, absence only when the negation's own subject is the DOCUMENT
#      ("the schedule ... was not supplied"), or the whole value is a
#      no-we-do-not-have-it token ("none", "to follow", "-");
#   3. anything else is PRESENT - Principle 7, no new penalty on a phrase we
#      cannot read. `unreadable_absence_values()` records those for review.

# A limit, in any way a broker writes one: $1,000,000 / $1M / 1,000,000 / 2MM.
_SCHEDULE_DATA_RE = re.compile(
    r"\$\s*\d"
    r"|\b\d{1,3}(?:,\d{3})+\b"
    r"|\b\d+(?:\.\d+)?\s*(?:m|mm|million|k)\b",
    re.I)

# The WHOLE value is a "we do not have it" token. Anchored on purpose: a bare
# "pending" is an absence, "Umbrella pending renewal quote" is not.
_ABSENCE_WHOLE_RE = re.compile(
    r"^\s*(?:(?:it|this|that|the\s+\w+|schedule|soi)\s+)?"      # optional subject
    r"(?:(?:was|is|were|are|has|have)\s+(?:been\s+)?)?"          # optional copula
    r"(?:"
    r"-{1,3}|nil|unknown|n\.?\s*/?\s*a\.?|"
    r"none(?:\s+(?:at\s+this\s+time|provided|received|supplied|attached|on\s+file|yet))?|"
    r"not\s+applicable|missing|outstanding|requested|pending|tbd|t\.b\.d\.?|"
    r"to\s+follow.*|to\s+be\s+(?:supplied|provided|obtained|determined|advised|confirmed).*|"
    r"awaiting.*|will\s+(?:follow|be\s+(?:supplied|provided|obtained|furnished)).*|"
    r"not\s+(?:yet\s+)?(?:been\s+)?"
    r"(?:supplied|provided|received|attached|available|obtained|furnished|submitted|on\s+file)|"
    r"we\s+do\s+not\s+have\s+(?:it|one|this)|"
    r"no\s+(?:such\s+)?schedule.*"
    r")\s*[.;,]?\s*$", re.I)

# The negation's SUBJECT is the document itself. The document word must come
# BEFORE the negation and inside the same clause - that is precisely what
# separates "the schedule was not supplied" (absent) from "Employers Liability
# not included" and "WC is not included in the umbrella schedule" (a real
# schedule describing what it does not cover).
_ABSENCE_ABOUT_DOC_RE = re.compile(
    r"\b(?:schedule|soi|document|attachment|exhibit)\b[^.;:\n]{0,40}?"
    r"\b(?:not|never)\s+(?:yet\s+)?(?:been\s+)?"
    r"(?:supplied|provided|attached|included|available|received|furnished|submitted|on\s+file)\b"
    r"|\bno\s+(?:such\s+)?(?:schedule|soi)\b",
    re.I)

_UNREADABLE_ABSENCE: List[dict] = []


def value_states_absence(value: Any) -> bool:
    """True when the stored text says the DOCUMENT is not there.

    Never true for a value that carries schedule data - a schedule that lists
    limits is a schedule even when it names a line it does not cover.
    """
    text = str(value or "").strip()
    if not text:
        return True
    if _ABSENCE_ABOUT_DOC_RE.search(text):
        return True                       # explicitly about the document
    if _SCHEDULE_DATA_RE.search(text):
        return False                      # it carries limits - it IS the thing
    if _ABSENCE_WHOLE_RE.match(text):
        return True
    # Unrecognised prose with no data. Could be either; Principle 7 says do not
    # invent a penalty, so it reads as present and is recorded for review.
    if len(text) <= 120:
        _UNREADABLE_ABSENCE.append({"value": text[:120]})
        logger.info("coverage_evidence: could not read presence/absence from %r "
                    "- treating as PRESENT (no new penalty)", text[:80])
    return False


def unreadable_absence_values() -> List[dict]:
    """Every short value `value_states_absence` could not classify. In-memory,
    dies with the process - the same evidence base as
    `answer_semantics.unresolved_answers()`, and it must be WATCHED (grep the
    log line above) before anyone concludes the rules are complete."""
    return list(_UNREADABLE_ABSENCE)


# Sentence-ish split for scanning raw document text.
_SENTENCE_SPLIT_RE = re.compile(r"[.;\n]")
_SCHEDULE_PHRASES: Tuple[str, ...] = (
    "schedule of underlying", "underlying insurance schedule",
    "schedule of underlying insurance",
)


def text_references_schedule_as_present(text: Any) -> bool:
    """Does raw document text REFERENCE a schedule of underlying insurance
    affirmatively?

    A sentence that says the schedule was not supplied references it too - and
    is the opposite of evidence. `extraction_pipeline`'s raw-text backfill used
    a bare substring test, so the live P1 document's own "was not supplied"
    sentence made it WRITE a synthetic "Schedule of Underlying Insurance
    referenced in submitted documents" fact - manufacturing the evidence whose
    absence is the -15.
    """
    hay = str(text or "").lower()
    if not hay:
        return False
    for sentence in _SENTENCE_SPLIT_RE.split(hay):
        if any(p in sentence for p in _SCHEDULE_PHRASES) and not value_states_absence(sentence):
            return True
    return False


def umbrella_schedule_present(facts: Optional[dict]) -> bool:
    """A Schedule of Underlying Insurance that is actually THERE - a list of
    underlying policies, or a stated schedule whose text does not itself say
    it is missing."""
    rows = _rows(facts, "underlying_policies")
    if rows:
        return True
    for key in ("schedule_of_underlying_insurance", "underlying_schedule",
                "underlying_insurance_schedule"):
        val = _fv(facts, key)
        if val is None:
            continue
        if isinstance(val, (list, dict)):
            return bool(val)
        if not value_states_absence(val):
            return True
    return False


def _flags_of(facts: Optional[dict], flags: Optional[dict]) -> Optional[dict]:
    if flags is None and isinstance(facts, dict):
        _f = facts.get("_flags")
        return _f if isinstance(_f, dict) else None
    return flags


def owned_vehicle_fact_not_applicable(fact_key: str, facts: Optional[dict],
                                      flags: Optional[dict] = None) -> bool:
    """For `fact_state`: an owned-vehicle fact does not apply on an HNOA-only
    account. Positive evidence only - UNKNOWN and NONE return False here (NONE
    is handled by `denied_lines`, which owns line-level absence)."""
    if fact_key not in OWNED_VEHICLE_FACTS:
        return False
    return auto_exposure_kind(facts, _flags_of(facts, flags)) == AUTO_HNOA_ONLY


def h1_fact_not_applicable(fact_key: str, facts: Optional[dict],
                           flags: Optional[dict] = None) -> bool:
    """Every H1 "this fact does not apply here" decision, for `fact_state`:

      * the five owned-vehicle facts on an HNOA-only auto line (6.3);
      * `wc_xmod` when the documents say the account is not experience-rated
        (derived `wc_xmod_applicability: not_applicable`) or the producer
        confirmed New Venture (6.4: "no deduction" - and no question either,
        which the deduction rule alone did not stop: the producer was still
        asked for a mod the dec page said does not exist).
    Positive evidence only; a blank answer here means "ask as normal".
    """
    if owned_vehicle_fact_not_applicable(fact_key, facts, flags):
        return True
    if fact_key in HNOA_INAPPLICABLE_FACTS and \
            auto_exposure_kind(facts, _flags_of(facts, flags)) == AUTO_HNOA_ONLY:
        return True
    # DELIBERATELY NOT HERE: `auto_liability_limit` on a split-limit policy.
    # It was, for one revision, so the producer would not be asked for a CSL
    # the policy does not express. Adversarial review measured what the Not
    # Applicable axis actually reaches, and the cure was worse than the
    # cosmetic complaint:
    #   * `pdf_service.apply_fact_state_confidence_labels` resolves the three
    #     STAMPED split boxes back to this fact, so three boxes carrying real
    #     document-sourced values were relabelled `not_applicable` and dropped
    #     out of `confidence_fill_rate` entirely - numerator AND denominator;
    #   * `_derive_evidence_labels` and the per-form checklists disagreed with
    #     it, so the producer saw three different answers for one fact.
    # An unnecessary producer card is recoverable; silently deleting real data
    # from the fill rate is not. The card stays.
    if fact_key in _XMOD_QUESTION_ALIASES:
        if str(_fv(facts, "wc_xmod_applicability") or "").strip().lower() == STATUS_NOT_APPLICABLE:
            return True
        if _recorded_state(facts, "wc_xmod") in ("explicit_no", "not_applicable"):
            return True
        try:
            from services.loss_history_state import new_venture_confirmed
            if new_venture_confirmed(facts or {}, _flags_of(facts, flags) or {}):
                return True
        except Exception:                                     # noqa: BLE001
            return False
    # ── V1 H4 (client section 9), 2026-08-27: WC Payroll Period ──────────────
    # The client's own key rule is *"N/A if annual basis is clear"*, and 6.4's
    # four branches ALREADY decide that - `wc_payroll_period_status` returns
    # NOT_APPLICABLE when there is no WC line or no payroll figure at all, and
    # SATISFIED when the figure's own label, its source or a class-code row
    # means annual (D43). But that verdict only ever reached the SCORE. The
    # QUESTION is generated off the fact, which stayed `not_stated`, so the
    # producer was asked "what period does the stated payroll figure cover?"
    #   * on a package with NO payroll figure at all - a question about the
    #     period of a number that does not exist; and
    #   * on a package whose H3 employee-group table states annual payroll per
    #     row BY CONSTRUCTION, which is the very evidence that satisfied 6.4.
    # Same shape as the X-Mod branch above: the deduction rule alone never
    # stopped the asking.
    #
    # ONLY the MISSING branch still asks - that is the -3, and it must keep
    # asking, because the producer's answer is exactly what retires it.
    #
    # SAFE ON THE FILL RATE, unlike the split-limit case documented above:
    # NOTHING stamps `wc_payroll_period` onto any ACORD box (verified by grep
    # over pdf_service, 2026-08-27), so no stamped value can be relabelled
    # `not_applicable` and dropped out of `confidence_fill_rate`.
    #
    # NO RECURSION: `wc_payroll_period_status` reads the stored envelope via
    # `_recorded_state`, never `fact_state.value_state_of`, so the door cannot
    # call back into the axis that called it.
    if fact_key == "wc_payroll_period":
        return _payroll_period_already_settled(facts)
    return False


def _payroll_period_already_settled(facts: Optional[dict]) -> bool:
    """Is the WC payroll period a question nobody needs to answer - decided
    WITHOUT reading a single coverage flag?

    THE FLAG-INDEPENDENCE IS THE WHOLE POINT, and it is not a style choice.
    `fact_state._owned_vehicle_fact_not_applicable` calls
    `h1_fact_not_applicable(fact_key, facts)` with NO flags, and `_flags_of`
    then falls back to `facts["_flags"]` - a key `fact_state.annotate_fact_states`
    stashes for the duration of ONE pass and pops again in a `finally`. So at
    `overlay_for`, `_tier2_not_applicable` and `is_not_applicable_for` time,
    every flag is invisible.
    The first line of `wc_payroll_period_status` is
    `if not _flag(flags, "has_workers_comp"): return STATUS_NOT_APPLICABLE`, so
    routing this decision through the SCORER marked the fact Not Applicable on
    EVERY package - including WC packages that were simultaneously being charged
    the -3 for the very gap the question exists to close. A deduction with no
    route to remediation is worse than the original defect, and it is exactly
    what shipped in the first cut of this fix (caught by adversarial review,
    2026-08-27, before it reached the owner). The X-Mod branch above survives the
    same blindness only because it fails OPEN.
    So this reads FACTS ONLY, and it is POSITIVE EVIDENCE ONLY:
      * no payroll figure anywhere -> there is no period to state (the -12 "WC
        coverage with no payroll" bucket owns that gap, not this one);
      * the figure's own source or label already MEANS annual (D43) - a typed
        annual-payroll column, a producer/client answer to a question that asks
        for the ANNUAL figure by name, or a class-code row stating annual
        remuneration.
    Anything else - including "we cannot tell" - returns False and the producer
    is asked, which is the branch the client's -3 is attached to.

    THE SCORER AND THIS FUNCTION CANNOT DISAGREE, and that is checkable rather
    than hoped for: `wc_payroll_period_status` returns MISSING only when a
    payroll figure EXISTS and neither annual test passes - the exact complement
    of the two clauses below. So the -3 fires if and only if the question is
    still asked.
    """
    if _fv(facts, "wc_payroll_period"):
        return False                      # stated; ordinary `present` value
    if not (_fv(facts, "wc_payroll") or _fv(facts, "total_payroll")):
        return True
    if _payroll_source_is_annual(facts):
        return True
    return bool(payroll_label_states_annual(_fv(facts, "dec_page_entries")))


# ── 2. The five Auto Completeness items ──────────────────────────────────────

_RADIUS_RE = re.compile(r"^\d{1,4}(\.\d{1,3})?$")
_RADIUS_ROW_KEYS = ("radius", "radius_of_use", "radius_of_operation")


def auto_radius_known(facts: Optional[dict]) -> bool:
    """Is a radius of operation stated ANYWHERE the form stamper would read?

    Three sources, the same three `pdf_service._resolve_vehicle_rating_cell`
    prints from, so the package can never deduct for a radius that is sitting
    on the generated ACORD 127: the scalar fact, a vehicle-schedule row's own
    radius cell, or the auto declarations index entry labelled radius (a
    numeric value only - a dec that prints "RADIUS: NA" has not stated one).
    """
    if _answered(facts, "auto_radius_of_operation"):
        return True
    for row in _rows(facts, "auto_vin_schedule"):
        if isinstance(row, dict):
            for k in _RADIUS_ROW_KEYS:
                if _RADIUS_RE.match(str(row.get(k) or "").strip()):
                    return True
    return radius_from_dec_entries(_fv(facts, "dec_page_entries")) is not None


def radius_from_dec_entries(entries: Any) -> Optional[str]:
    """ONE numeric radius stated on an AUTO declarations entry, else None.

    Two distinct figures is ambiguity (a fleet rated on several radii) and
    stays None - the schedule rows carry the per-vehicle values then.
    """
    if not isinstance(entries, list):
        return None
    try:
        from services.extraction_service import _canon_line
    except Exception:                                         # noqa: BLE001
        return None
    found: set = set()
    for e in entries:
        if not isinstance(e, dict):
            continue
        try:
            if _canon_line(str(e.get("line_of_business") or "")) != "auto":
                continue
        except Exception:                                     # noqa: BLE001
            continue
        label_tokens = set(re.findall(r"[a-z]+", str(e.get("label") or "").lower()))
        if "radius" not in label_tokens:
            continue
        v = str(e.get("value") or "").strip()
        if _RADIUS_RE.match(v):
            found.add(v)
    return next(iter(found)) if len(found) == 1 else None


def _drivers_known(facts: Optional[dict]) -> bool:
    """A driver schedule exists when someone answered it, or the rows name at
    least one driver (a driver row with no name is not a driver)."""
    if _recorded_state(facts, "auto_drivers") in ("explicit_no", "not_applicable"):
        return True
    for row in _rows(facts, "auto_drivers"):
        if isinstance(row, dict):
            if str(row.get("name") or "").strip():
                return True
        elif str(row).strip():
            return True
    return False


def auto_completeness_gaps(facts: Optional[dict], flags: Optional[dict]) -> List[Tuple[str, int, str]]:
    """[(fact_key, points, label)] for every 6.3 item this package is missing.

    Empty when the deductions do not apply (no auto line, or a genuinely
    hired/non-owned-only account). Uncapped - the caller applies
    `AUTO_COMPLETENESS_CAP`, so the trace can list every gap while the score
    charges at most 25.
    """
    if not auto_completeness_applies(facts, flags):
        return []
    present = {
        "auto_vin_schedule":       bool(_rows(facts, "auto_vin_schedule")
                                        or _rows(facts, "vehicle_schedule")
                                        or _recorded_state(facts, "auto_vin_schedule")
                                        in ("explicit_no", "not_applicable")),
        "auto_drivers":            _drivers_known(facts),
        "auto_garaging_addresses": bool(_rows(facts, "auto_garaging_addresses")
                                        or _answered(facts, "auto_garaging_addresses")),
        "auto_radius_of_operation": auto_radius_known(facts),
        "auto_vehicle_use":        _answered(facts, "auto_vehicle_use"),
    }
    return [(key, pts, label) for key, pts, label in AUTO_COMPLETENESS_RULES
            if not present[key]]


def auto_completeness_deduction(facts: Optional[dict], flags: Optional[dict]) -> int:
    """The capped 6.3 deduction, 0 when it does not apply."""
    return min(AUTO_COMPLETENESS_CAP,
               sum(p for _, p, _ in auto_completeness_gaps(facts, flags)))


# ── 3. Supplemental Workers Compensation ─────────────────────────────────────

# An experience modification factor as printed: 0.75, 1.00, 1.23, 85 (%),
# ".95". Bounds are generous on purpose - a real mod outside 0.3-3.0 is
# vanishingly rare and a number like "2024" in this box is a year, not a mod.
_XMOD_NUM_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3})?|\.\d{1,3})(?![\d.])")


def parse_xmod(value: Any) -> Optional[float]:
    """The factor as a float, or None when the text does not state one."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    if re.search(r"\bunity\b", text, re.I):
        return 1.0                          # "unity" IS a stated mod of 1.00
    for m in _XMOD_NUM_RE.finditer(text):
        try:
            n = float(m.group(1))
        except ValueError:
            continue
        if n > 3.0 and n <= 300:          # printed as a percentage (e.g. "95%")
            n = n / 100.0
        if 0.3 <= n <= 3.0:
            return n
    return None


# Phrases that MEAN "no experience mod applies to this account". Whole
# clause, so "not experience rated" and "not subject to experience rating"
# both read; a bare "no" is handled by the answer door as an absence.
_XMOD_NOT_APPLICABLE_RE = re.compile(
    r"\b(not\s+(?:experience|exp\.?)\s*rat(?:ed|ing)|non[\s-]?rated|not\s+rated|"
    r"no\s+(?:experience\s+)?mod(?:ifier|ification)?\b|"
    r"not\s+subject\s+to\s+experience|does\s+not\s+apply|not\s+applicable|"
    r"new\s+venture|n/?a)\b", re.I)

# Phrases that MEAN "a mod applies but is not (yet) stated".
_XMOD_PENDING_RE = re.compile(
    r"\b(pending|to\s+follow|see\s+(?:attached\s+)?(?:worksheet|mod)|"
    r"tbd|to\s+be\s+(?:determined|supplied|provided)|"
    r"awaiting|on\s+order|forthcoming|will\s+(?:be\s+)?(?:supplied|provided|follow))\b",
    re.I)


def classify_xmod_text(value: Any) -> str:
    """SATISFIED / NOT_APPLICABLE / MISSING / UNKNOWN for one X-Mod string."""
    if parse_xmod(value) is not None:
        return STATUS_SATISFIED
    text = str(value or "").strip()
    if not text:
        return STATUS_UNKNOWN
    if _XMOD_NOT_APPLICABLE_RE.search(text):
        return STATUS_NOT_APPLICABLE
    if _XMOD_PENDING_RE.search(text):
        return STATUS_MISSING
    return STATUS_UNKNOWN


def wc_xmod_status(facts: Optional[dict], flags: Optional[dict]) -> str:
    """6.4 X-Mod / EMOD.

      * a factor is stated                              -> SATISFIED
      * New Venture confirmed, not experience-rated, or an explicit "none" /
        "N/A" from the producer or the document          -> NOT_APPLICABLE
      * applicability INDICATED (an effective date for the mod, the document
        saying the mod is pending / on a worksheet, or the derived
        `wc_xmod_applicability` fact) and no factor      -> MISSING (-5)
      * anything else                                   -> UNKNOWN (producer)
    The client's rule, in his order: "if source information or producer input
    indicates an X-Mod is applicable and the value remains missing -> -5; if
    applicability is unknown -> route to producer; if New Venture / not
    experience-rated / explicitly N/A -> no deduction".
    """
    if not _flag(flags, "has_workers_comp"):
        return STATUS_NOT_APPLICABLE

    recorded = _recorded_state(facts, "wc_xmod")
    if recorded in ("explicit_no", "not_applicable"):
        return STATUS_NOT_APPLICABLE
    text_state = classify_xmod_text(_fv(facts, "wc_xmod"))
    if text_state in (STATUS_SATISFIED, STATUS_NOT_APPLICABLE):
        return text_state

    try:
        from services.loss_history_state import new_venture_confirmed
        if new_venture_confirmed(facts or {}, flags or {}):
            return STATUS_NOT_APPLICABLE
    except Exception:                                         # noqa: BLE001
        pass

    derived = str(_fv(facts, "wc_xmod_applicability") or "").strip().lower()
    if derived == STATUS_NOT_APPLICABLE:
        return STATUS_NOT_APPLICABLE
    if text_state == STATUS_MISSING or derived == "applicable":
        return STATUS_MISSING
    if _fv(facts, "wc_xmod_effective_date"):
        return STATUS_MISSING
    return STATUS_UNKNOWN


_OFFICER_NONE_RE = re.compile(
    r"\b(no\s+(?:owners?|officers?|individuals?)\b|none\s+to\s+consider|"
    r"there\s+are\s+no\s+owners)", re.I)


def wc_officer_treatment_status(facts: Optional[dict], flags: Optional[dict]) -> str:
    """6.4 Owner / Officer inclusion or exclusion.

      * `wc_officer_exclusions` answered (a list, "all included", "none to
        consider", an explicit no)                       -> SATISFIED
      * named officers on file and every one of them carries an
        include / exclude code                           -> SATISFIED
      * named officers on file and at least one carries NEITHER code, and
        nothing else states the treatment                -> MISSING (-5)
      * no officers known at all                         -> UNKNOWN (producer)
    "Known to exist" is read narrowly (owner 2026-08-26): individuals named in
    the package or by a person - never inferred from the entity type.
    """
    if not _flag(flags, "has_workers_comp"):
        return STATUS_NOT_APPLICABLE
    if _answered(facts, "wc_officer_exclusions"):
        return STATUS_SATISFIED
    rows = _rows(facts, "wc_officers")
    if _recorded_state(facts, "wc_officers") in ("explicit_no", "not_applicable"):
        return STATUS_SATISFIED
    if not rows:
        return STATUS_UNKNOWN
    unresolved = 0
    named = 0
    for row in rows:
        if isinstance(row, dict):
            if not str(row.get("name") or "").strip():
                continue
            named += 1
            if officer_treatment_code(row):
                continue
            unresolved += 1
        else:
            named += 1
            unresolved += 1               # a bare name carries no treatment
    if named == 0:
        return STATUS_UNKNOWN
    return STATUS_MISSING if unresolved else STATUS_SATISFIED


# ── V1 H3 (client section 8) - the WC row vocabulary, read in ONE place ──────
# The employee-group table (`wc_class_codes` rows) and the officer table
# (`wc_officers` rows) are edited by people AND extracted from documents, so
# every reader below - the ACORD 130 stamper, the table renderer, the merge
# tail, the 6.4 officer check above - asks these helpers rather than
# re-parsing the row shape. Principle 1: one canonical fact, one reading.

_OFFICER_INCLUDE_WORDS = frozenset({"include", "included", "inc", "in", "yes", "y"})
_OFFICER_EXCLUDE_WORDS = frozenset({"exclude", "excluded", "exc", "ex", "out", "no", "n"})
OFFICER_INCLUDED = "INC"
OFFICER_EXCLUDED = "EXC"


def officer_treatment_code(row: Any) -> Optional[str]:
    """The ACORD 130 INC / EXC code for one officer row, or None.

    Reads the extractor's two booleans (`include` / `exclude`) and any text a
    person typed (`include_exclude`, `treatment`, `status`). A row that says
    BOTH, or says neither, or says something unrecognised, gets None - the box
    stays blank and the 6.4 check keeps counting the officer as unresolved.
    Right-or-blank; never a guess.
    """
    if not isinstance(row, dict):
        return None
    inc = _truthy(row.get("include"))
    exc = _truthy(row.get("exclude"))
    text = str(row.get("include_exclude") or row.get("treatment")
               or row.get("status") or "").strip().lower()
    if text:
        words = set(re.findall(r"[a-z]+", text))
        if words & _OFFICER_INCLUDE_WORDS and not words & _OFFICER_EXCLUDE_WORDS:
            inc, exc = True, False
        elif words & _OFFICER_EXCLUDE_WORDS and not words & _OFFICER_INCLUDE_WORDS:
            inc, exc = False, True
        elif not (inc or exc):
            return None
    if inc and not exc:
        return OFFICER_INCLUDED
    if exc and not inc:
        return OFFICER_EXCLUDED
    return None


def officer_treatment_label(row: Any) -> str:
    """The table-cell wording for one officer row ("Included" / "Excluded" / "")."""
    code = officer_treatment_code(row)
    return {OFFICER_INCLUDED: "Included", OFFICER_EXCLUDED: "Excluded"}.get(code or "", "")


_STATE_CODE_RE = re.compile(r"^[A-Za-z]{2}$")
# ONE reading of "what class code does this cell carry?", used by the
# normaliser AND by the chunk-union identity in `extraction_service`. They MUST
# agree: the identity is computed on the raw row, before the normaliser runs, so
# a code read two different ways is a row that never folds against itself.
# Live dry run 2026-08-27 caught exactly that - a premium summary printing
# "8810 Clerical" and a rating sheet printing "8810" survived as TWO rows, and
# the payroll-by-state derived from them DOUBLED.
_WC_CODE_HEAD_RE = re.compile(r"^\s*(\d{4}[A-Za-z0-9]{0,2})\s*(?:[-:.,]\s*|\s+)?(.*)$")


def wc_class_code_token(row: Any) -> str:
    """The bare class code a row (or a raw cell) carries - "8810" out of
    "8810 Clerical", "5551" out of "5551 - Roofing", "8810A" unchanged.
    Empty string when the cell names no code at all, which every caller must
    read as "cannot tell", never as a match."""
    cell = row.get("code") if isinstance(row, dict) else row
    m = _WC_CODE_HEAD_RE.match(str(cell or ""))
    return m.group(1) if m else ""


def _row_state(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    st = str(row.get("state") or "").strip().upper()
    return st if _STATE_CODE_RE.match(st) else ""


def _row_amount(row: Any) -> Optional[float]:
    if not isinstance(row, dict):
        return None
    raw = str(row.get("payroll") or "").strip()
    if not re.search(r"\d", raw):
        return None
    try:
        return float(re.sub(r"[^\d.]", "", raw) or "0")
    except ValueError:
        return None


def wc_class_row_states(rows: Any) -> List[str]:
    """The DISTINCT two-letter states the employee-group rows name, in row
    order. Rows without a real state code contribute nothing."""
    out: List[str] = []
    for row in (rows if isinstance(rows, list) else []):
        st = _row_state(row)
        if st and st not in out:
            out.append(st)
    return out


def wc_class_shared_state(rows: Any) -> Optional[str]:
    """The ONE state every stated row shares - what the single ACORD 130 rating
    sheet may be labelled with. Two states, or none, -> None (blank; the
    producer sees it)."""
    states = wc_class_row_states(rows)
    return states[0] if len(states) == 1 else None


def wc_payroll_by_state_from_rows(rows: Any) -> Optional[Dict[str, str]]:
    """{state: summed payroll} from the employee-group rows - ONLY when every
    real row carries both a state and a payroll figure (positive, complete
    evidence). A partial table yields None: a state total built from half the
    rows is a wrong value, not a derived one (H1-F class)."""
    real = [r for r in (rows if isinstance(rows, list) else [])
            if isinstance(r, dict) and any(str(v or "").strip() for v in r.values()
                                            if not isinstance(v, bool))]
    if not real:
        return None
    totals: Dict[str, float] = {}
    for row in real:
        st, amt = _row_state(row), _row_amount(row)
        if not st or amt is None:
            return None
        totals[st] = totals.get(st, 0.0) + amt
    return {st: f"${int(round(v)):,}" for st, v in totals.items()}


def normalize_wc_class_row(row: Any) -> Any:
    """Tidy ONE employee-group row's known formatting (client 8.3 "normalize
    known formatting"). Splits a compound code cell - "8810 Clerical",
    "5551 - Roofing" - into the code and its wording, filling `description`
    only when it is empty. Never invents, never alters a bare code, never
    touches a suffix ("8810A" stays "8810A"). Returns the same object."""
    if not isinstance(row, dict):
        return row
    m = _WC_CODE_HEAD_RE.match(str(row.get("code") or ""))
    if not m:
        return row                              # names no code - left alone
    row["code"] = m.group(1)
    rest = (m.group(2) or "").strip()
    if rest and not str(row.get("description") or "").strip():
        row["description"] = rest
    return row


# "Clearly annual" - by MEANING, not one spelling (owner 2026-08-26). Any of
# these on the label the payroll figure was printed under, or in the period
# answer itself, means the figure covers a year.
_ANNUAL_RE = re.compile(
    r"\b(annual(?:ly|ized|ised)?|per\s+annum|per\s+year|yearly|a\s+year|"
    r"each\s+year|12[\s-]?months?|twelve[\s-]?months?|calendar\s+year|"
    r"fiscal\s+year|policy\s+(?:year|period|term)|est(?:imated)?\.?\s+annual|"
    r"annual\s+remuneration|estimated\s+remuneration)\b", re.I)
# Any OTHER recognised period is also a resolved basis - the figure can be
# interpreted (annualised) because we know what it covers.
_OTHER_PERIOD_RE = re.compile(
    r"\b(quarter(?:ly)?|month(?:ly)?|semi[\s-]?annual|bi[\s-]?annual|"
    r"weekly|bi[\s-]?weekly|per\s+(?:quarter|month|week)|ytd|year[\s-]to[\s-]date|"
    r"\d{1,2}\s+months?)\b", re.I)


def payroll_period_meaning(text: Any) -> Optional[str]:
    """'annual' / 'other' / None for one period string, by meaning."""
    s = str(text or "").strip()
    if not s:
        return None
    if _ANNUAL_RE.search(s):
        return "annual"
    if _OTHER_PERIOD_RE.search(s):
        return "other"
    return None


# D43 corroboration. The period must QUALIFY the payroll word, in the same
# phrase - never merely sit near it. A declarations page prints
# "Policy Period  09/17/2026 to 09/17/2027" one row above "Payroll  $210,000",
# so any distance-window test corroborates "annual" on a document that never
# said it. `policy year/period/term` is deliberately absent from these
# alternations for the same reason (it stays in `_ANNUAL_RE`, which is only
# ever applied to a payroll-LABELLED entry).
_PAYROLL_WORD = r"(?:payroll|remuneration|wages)"
_ANNUAL_WORDS = (r"annual(?:ly|ized|ised)?|per\s+annum|per\s+year|yearly|a\s+year|"
                 r"each\s+year|12[\s-]?months?|twelve[\s-]?months?|calendar\s+year|"
                 r"fiscal\s+year")
_OTHER_WORDS = (r"quarter(?:ly)?|month(?:ly)?|semi[\s-]?annual|bi[\s-]?annual|weekly|"
                r"bi[\s-]?weekly|per\s+(?:quarter|month|week)|ytd|year[\s-]to[\s-]date")


def _qualifying_re(words):
    """<period> ... <payroll>, or <payroll> then <period> within 30 chars,
    crossing neither a sentence end nor a line break."""
    return re.compile(
        r"(?:" + words + r")[\s\-()]*(?:estimated\s+|total\s+|gross\s+)*" + _PAYROLL_WORD
        + r"|" + _PAYROLL_WORD + r"[^.\n;]{0,30}?(?:" + words + r")", re.I)


_ANNUAL_QUALIFIES = _qualifying_re(_ANNUAL_WORDS)
_OTHER_QUALIFIES = _qualifying_re(_OTHER_WORDS)


def payroll_period_corroborated(period, entries=None, text=""):
    """Does the DOCUMENT actually name the period this fact claims?

    D43: *"'clearly annual' ... a payroll figure is annual when its OWN label /
    source MEANS annual"* - never inferred from the category. LIVE RUN
    2026-08-27: the dec index printed the bare label `Payroll = $210,000` and
    the merged fact came back `wc_payroll_period = "annual"`. The 6.4 rule then
    read a stated period and satisfied the check, so the -3 the client
    specified could never fire. The rule was right; its INPUT was manufactured
    - the same shape as H1-F, where a raw-text backfill fabricated the evidence
    a rule tested for.

    Returns True when nothing interpretable is claimed: this gate exists to
    strip an invented period, not to judge free text the scoring rules already
    ignore.
    """
    meaning = payroll_period_meaning(period)
    if not meaning:
        return True
    if meaning == "annual" and payroll_label_states_annual(entries):
        return True
    rx = _ANNUAL_QUALIFIES if meaning == "annual" else _OTHER_QUALIFIES
    if isinstance(entries, list):
        for e in entries:
            if isinstance(e, dict) and rx.search(
                    str(e.get("label") or "") + " " + str(e.get("value") or "")):
                return True
    return bool(rx.search(str(text or "")))


def _payroll_source_is_annual(facts: Optional[dict]) -> bool:
    """The payroll figure came from a source whose own wording is annual:
    a human answer to the questionnaire (both payroll questions ask for the
    ANNUAL figure by name), or a rating-basis schedule row (a class-code
    schedule states annual remuneration by definition)."""
    for key in ("wc_payroll", "total_payroll"):
        _, env = _unwrap((facts or {}).get(key))
        if str(env.get("source") or "").lower() in ("producer", "client_arq", "client"):
            return True
        if str(env.get("period_basis") or "").lower() == "annual":
            return True
    for key in ("wc_class_codes", "gl_class_code_schedule"):
        for row in _rows(facts, key):
            if not isinstance(row, dict):
                continue
            basis = str(row.get("premium_basis") or row.get("basis") or "").lower()
            amount = row.get("payroll") or row.get("exposure_amount") or row.get("remuneration")
            if amount and (re.search(r"\d", str(amount))) and \
                    (key == "wc_class_codes" or "payroll" in basis or "remuneration" in basis):
                return True
    return False


def wc_payroll_period_status(facts: Optional[dict], flags: Optional[dict]) -> str:
    """6.4 WC Payroll Period.

      * no payroll figure at all            -> NOT_APPLICABLE here (the -12
                                               "WC coverage with no payroll"
                                               bucket owns that gap)
      * period stated, or the figure's own label / source means annual, or
        any recognised period is stated     -> SATISFIED
      * a figure whose period nobody stated -> MISSING (-3, producer)
    """
    if not _flag(flags, "has_workers_comp"):
        return STATUS_NOT_APPLICABLE
    if not (_fv(facts, "wc_payroll") or _fv(facts, "total_payroll")):
        return STATUS_NOT_APPLICABLE
    # HUMAN-recorded only (V1 H4, 2026-08-27). A derived not_applicable that
    # `annotate_fact_states` wrote back onto the envelope must never be read
    # here as authoritative - see `_human_recorded_state` for the loop that
    # closes and the measured case it silences.
    if _human_recorded_state(facts, "wc_payroll_period") in ("not_applicable",):
        return STATUS_NOT_APPLICABLE
    period = _fv(facts, "wc_payroll_period")
    if period is not None and payroll_period_meaning(period):
        return STATUS_SATISFIED
    if _payroll_source_is_annual(facts):
        return STATUS_SATISFIED
    if payroll_label_states_annual(_fv(facts, "dec_page_entries")):
        return STATUS_SATISFIED
    return STATUS_MISSING


def payroll_label_states_annual(entries: Any) -> bool:
    """A verified declarations entry that both names payroll / remuneration
    AND carries an annual meaning in its label (or value) - "Estimated Annual
    Payroll: $412,000", "Annual Remuneration", "Payroll (per year)"."""
    if not isinstance(entries, list):
        return False
    for e in entries:
        if not isinstance(e, dict):
            continue
        label = str(e.get("label") or "")
        value = str(e.get("value") or "")
        if not re.search(r"payroll|remuneration|wages", label, re.I):
            continue
        if _ANNUAL_RE.search(label) or _ANNUAL_RE.search(value):
            return True
    return False


_XMOD_LABEL_RE = re.compile(
    r"\b(experience|exp\.?)\s*(mod|modification|rating)|"
    r"\b(e|x)[\s-]?mod\b|mod(?:ification)?\s+factor", re.I)


def _xmod_entries(entries: Any) -> List[dict]:
    if not isinstance(entries, list):
        return []
    return [e for e in entries
            if isinstance(e, dict) and _XMOD_LABEL_RE.search(str(e.get("label") or ""))]


def xmod_from_entries(entries: Any) -> Optional[str]:
    """THE stated experience-mod factor printed on the declarations, as
    printed, or None. The generic entry backfill cannot reach `wc_xmod` -
    its label rule wants the KEY's tokens ("wc", "xmod") in the label, and a
    dec page prints "Experience Modification" - so the factor is read here by
    the label's MEANING. Two different factors is ambiguity and stays None."""
    found: Dict[float, str] = {}
    for e in _xmod_entries(entries):
        n = parse_xmod(e.get("value"))
        if n is not None:
            found.setdefault(n, str(e.get("value")).strip())
    return next(iter(found.values())) if len(found) == 1 else None


def xmod_applicability_from_entries(entries: Any) -> Optional[str]:
    """'applicable' / 'not_applicable' / None from the verified dec index.

    Only the entries that state NO factor speak here: a value meaning
    "none / not rated / N/A" says the account is not experience-rated; one
    meaning "pending / see worksheet" says a mod applies and is unstated. An
    entry that states a factor is the fact itself (`xmod_from_entries`) and
    makes applicability moot, so any stated factor returns None. Two entries
    that disagree are ambiguity and return None.
    """
    verdicts: set = set()
    for e in _xmod_entries(entries):
        state = classify_xmod_text(e.get("value"))
        if state == STATUS_SATISFIED:
            return None                    # the factor itself is stated
        if state == STATUS_NOT_APPLICABLE:
            verdicts.add(STATUS_NOT_APPLICABLE)
        elif state == STATUS_MISSING:
            verdicts.add("applicable")
    if len(verdicts) != 1:
        return None
    return next(iter(verdicts))


def wc_supplemental_gaps(facts: Optional[dict], flags: Optional[dict]) -> List[Tuple[str, int, str]]:
    """[(fact_key, points, label)] for every 6.4 supplemental item that is
    MISSING. UNKNOWN items are deliberately absent - they route to the
    producer with no deduction. Uncapped; callers apply
    `WC_SUPPLEMENTAL_CAP`."""
    out: List[Tuple[str, int, str]] = []
    if wc_xmod_status(facts, flags) == STATUS_MISSING:
        out.append(("wc_xmod", WC_XMOD_POINTS,
                    "Experience mod applies but is not stated"))
    if wc_officer_treatment_status(facts, flags) == STATUS_MISSING:
        out.append(("wc_officer_exclusions", WC_OFFICER_POINTS,
                    "Owner/officer inclusion or exclusion unresolved"))
    if wc_payroll_period_status(facts, flags) == STATUS_MISSING:
        out.append(("wc_payroll_period", WC_PAYROLL_PERIOD_POINTS,
                    "Payroll period / basis unresolved"))
    return out


def wc_supplemental_deduction(facts: Optional[dict], flags: Optional[dict]) -> int:
    return min(WC_SUPPLEMENTAL_CAP,
               sum(p for _, p, _ in wc_supplemental_gaps(facts, flags)))


def wc_supplemental_unknowns(facts: Optional[dict], flags: Optional[dict]) -> List[str]:
    """The 6.4 items whose applicability is UNKNOWN - the producer's list."""
    out: List[str] = []
    if wc_xmod_status(facts, flags) == STATUS_UNKNOWN:
        out.append("wc_xmod")
    if wc_officer_treatment_status(facts, flags) == STATUS_UNKNOWN:
        out.append("wc_officer_exclusions")
    return out


# ── 4. Is a coverage flag still supported once a field is edited? ─────────────

# Facts that evidence a line but are package-level in the registry (they also
# reach ACORD 125, so `fact_line` correctly gives them no line). Hand-listed
# ONLY for that reason; everything else is derived from the registry.
_EXTRA_LINE_EVIDENCE: Dict[str, Tuple[str, ...]] = {
    "auto":         ("auto_liability_limit",),
    "property":     ("locations", "property_locations", "physical_address"),
    "workers_comp": ("total_payroll", "num_employees"),
    "umbrella":     (),
    "general_liab": (),
}
# Family names are `lob_canon`'s - the SAME strings `fact_equivalence.fact_line`
# returns - resolved once from the line phrase so this table can never spell
# a family differently from the door that owns the vocabulary.
_FLAG_TO_LINE_PHRASE: Dict[str, str] = {
    "has_auto_coverage":     "business auto",
    "has_property_coverage": "property",
    "has_umbrella":          "umbrella",
    "has_workers_comp":      "workers compensation",
    "has_general_liability": "general liability",
}


def _family_for_flag(flag: str) -> Optional[str]:
    phrase = _FLAG_TO_LINE_PHRASE.get(flag)
    if not phrase:
        return None
    try:
        from services.lob_canon import canon_line
        return canon_line(phrase)
    except Exception:                                         # noqa: BLE001
        return None


def _line_evidence_keys(line: str) -> List[str]:
    """Every registry fact whose forms are all sections of this ONE line -
    derived through `fact_equivalence.fact_line`, never hand-listed."""
    out: List[str] = list(_EXTRA_LINE_EVIDENCE.get(line, ()))
    try:
        from services.fact_registry import FACT_REGISTRY
        from services.fact_equivalence import fact_line
        for key in FACT_REGISTRY:
            try:
                if fact_line(key) == line:
                    out.append(key)
            except Exception:                                 # noqa: BLE001
                continue
    except Exception:                                         # noqa: BLE001
        pass
    return out


def _coverage_lines_grant(facts: Optional[dict], line: str) -> bool:
    lines = _fv(facts, "coverage_lines")
    if not isinstance(lines, list):
        return False
    try:
        from services.extraction_service import _line_entry_grants_coverage
        from services.lob_canon import canon_line
    except Exception:                                         # noqa: BLE001
        return False
    for entry in lines:
        if not isinstance(entry, dict) or not entry.get("line"):
            continue
        try:
            if _line_entry_grants_coverage(entry) and canon_line(str(entry["line"])) == line:
                return True
        except Exception:                                     # noqa: BLE001
            continue
    return False


def coverage_flag_supported(flag: str, facts: Optional[dict],
                            selected_form_ids: Optional[Iterable[str]] = None) -> bool:
    """Is there still ANY positive evidence for this coverage flag?

    THE EDIT-PATH DEMOTION DEFECT (H1, 2026-08-26): `routes/form_routes.update_pdf`
    re-derived each coverage flag after a producer edit as "False unless the
    two or three facts the PENALTIES read are filled". So an auto line with no
    liability limit and no vehicle schedule - the MOST incomplete auto
    submission, the one 6.3 exists to catch - lost `has_auto_coverage` the
    moment any field was edited, and with it every auto deduction, warning and
    ceiling. The score went UP for being incomplete. Property, umbrella and WC
    had the identical shape: the flag keyed on the facts whose absence is the
    penalty.

    The rule here is the one `fact_state.is_not_applicable_for` already uses
    for the questionnaire: a coverage line is supported when
      * the producer SELECTED a section form for it (applying for it is the
        strongest evidence there is), or
      * `coverage_lines` grants it, or
      * ANY fact that belongs to that line carries an answer.
    Only when none of those hold may the caller drop the flag. Unknown flags
    are always supported (never demote what we cannot reason about).
    """
    line = _family_for_flag(flag)
    if not line:
        return True
    try:
        from services.fact_state import lines_applied_for
        if line in lines_applied_for(list(selected_form_ids or [])):
            return True
    except Exception:                                         # noqa: BLE001
        pass
    if _coverage_lines_grant(facts, line):
        return True
    for key in _line_evidence_keys(line):
        if _answered(facts, key):
            return True
    return False


__all__ = [
    "AUTO_NONE", "AUTO_OWNED", "AUTO_HNOA_ONLY", "AUTO_UNKNOWN",
    "OWNED_VEHICLE_FACTS", "HNOA_INAPPLICABLE_FACTS",
    "AUTO_COMPLETENESS_RULES", "AUTO_COMPLETENESS_CAP",
    "auto_liability_stated", "auto_split_limits_stated",
    "value_states_absence", "umbrella_schedule_present",
    "text_references_schedule_as_present", "unreadable_absence_values",
    "WC_SUPPLEMENTAL_CAP", "WC_XMOD_POINTS", "WC_OFFICER_POINTS",
    "WC_PAYROLL_PERIOD_POINTS",
    "STATUS_SATISFIED", "STATUS_NOT_APPLICABLE", "STATUS_MISSING", "STATUS_UNKNOWN",
    "auto_exposure_kind", "auto_completeness_applies",
    "owned_vehicle_fact_not_applicable", "h1_fact_not_applicable", "auto_radius_known",
    "radius_from_dec_entries", "auto_completeness_gaps",
    "auto_completeness_deduction",
    "parse_xmod", "classify_xmod_text", "wc_xmod_status",
    "wc_officer_treatment_status", "payroll_period_meaning",
    "wc_payroll_period_status", "payroll_label_states_annual",
    "xmod_from_entries", "xmod_applicability_from_entries", "wc_supplemental_gaps",
    "wc_supplemental_deduction", "wc_supplemental_unknowns",
    "coverage_flag_supported",
]
