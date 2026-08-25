"""loss_history_state.py - the ONE owner of every loss-history state decision.

V1 plan C2 (client section 2, implemented 2026-08-24). Loss History spans
document recognition, insured matching, questionnaire responses, scoring and
Data Consistency - and before this module each surface re-derived "what loss
evidence do we have?" from raw facts/flags on its own, so a problem that
appeared in the questionnaire could originate in scoring because the two
disagreed about the STATE. Same defect class C1 fixed for value comparisons
with ``fact_comparison``; this is the same cure one workstream over: every
consumer (``calculate_p4_loss_history``, ``_get_loss_history_state``, the ARQ
injectors/gate and the pipeline's conflict routing) asks THIS module, never
the raw facts.

Client 2.9 states (a data model, not free text) - "at minimum", so the
narrative-only shading is kept as an explicit extra state rather than being
collapsed into missing:

    new_venture / loss_runs_uploaded / loss_runs_pending /
    no_loss_runs_available / no_known_losses_attested /
    no_loss_narrative_only / prior_claims_exist / missing_unanswered

RULES OWNED HERE
- ``attested_true()``: the one attestation parser (moved verbatim from
  sqs_service, which now imports it back under its old private name so every
  existing import keeps working; the ``_NO_LOSS_OPTIONS`` wording contract in
  arq_service keeps a single owner).
- New Venture (client 2.2): "confirmed by the producer" means the
  ``new_venture_confirmed`` flag or an affirmative ``new_venture_indicator``
  fact - never inferred from documents. A confirmation contradicted by
  POSITIVE evidence of prior operations (a loss-run document, a named prior
  carrier, recorded claims/incurred, loss-history years, or a renewal) does
  NOT make the pillar Not Applicable; the scorer keeps scoring and flags the
  contradiction (client 2.10: "unless contradictory source information
  suggests prior operations actually existed").
- Prior-carrier applicability (client 2.3/2.7): expected context whenever the
  business is NOT a confirmed new venture. Never a bonus for presence.
- Questionnaire gating (client 2.10): which loss questions each state
  suppresses lives in ``suppressed_question_fields`` so both ARQ generators
  apply one rule.

The tiny value coercers below are deliberate local copies: they are TYPE
coercion, not sameness decisions, so they do not create a second comparison
door (the rule ``fact_comparison`` owns is "are these the same fact?").
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

NEW_VENTURE_FIELD = "new_venture_indicator"
LOSS_RUN_STATUS_FIELD = "loss_run_status"

# Client 2.9 canonical states.
STATE_NEW_VENTURE = "new_venture"
STATE_LOSS_RUNS_UPLOADED = "loss_runs_uploaded"
STATE_LOSS_RUNS_PENDING = "loss_runs_pending"
STATE_NO_LOSS_RUNS_AVAILABLE = "no_loss_runs_available"
STATE_NO_KNOWN_LOSSES_ATTESTED = "no_known_losses_attested"
STATE_NO_LOSS_NARRATIVE_ONLY = "no_loss_narrative_only"
STATE_PRIOR_CLAIMS_EXIST = "prior_claims_exist"
STATE_MISSING_UNANSWERED = "missing_unanswered"

CANONICAL_STATES = (
    STATE_NEW_VENTURE, STATE_LOSS_RUNS_UPLOADED, STATE_LOSS_RUNS_PENDING,
    STATE_NO_LOSS_RUNS_AVAILABLE, STATE_NO_KNOWN_LOSSES_ATTESTED,
    STATE_NO_LOSS_NARRATIVE_ONLY, STATE_PRIOR_CLAIMS_EXIST,
    STATE_MISSING_UNANSWERED,
)

# The producer's New Venture confirmation control. The chosen option TEXT is
# what gets stored (same no-inversion design as arq_service._NO_LOSS_OPTIONS -
# see test_the_client_wording_needs_no_inversion for why): option one parses
# True, option two parses False, and a bare legacy "Yes"/"No" keeps its
# meaning. CHANGING THIS WORDING CHANGES WHAT IS STORED.
NEW_VENTURE_OPTIONS = (
    "Yes - new venture, no prior operations",
    "No - the business has prior operations",
)

# Client 2.10 (Prior Claims Exist / Loss Runs Pending): the loss-run status
# select. Stored as option text; ``parse_loss_run_status`` reads these AND the
# extraction-written "pending"/"requested" scalars with one rule.
LOSS_RUN_STATUS_OPTIONS = (
    "Loss runs have been requested and are pending",
    "Loss runs are available and will be uploaded",
    "No loss runs are available",
)


# ── Small local coercers (type coercion only - see module docstring) ─────────

def _fv(facts: Any, key: str) -> Any:
    if not isinstance(facts, dict):
        return None
    raw = facts.get(key)
    if isinstance(raw, dict) and "value" in raw:
        return raw["value"]
    return raw


def _to_int(v: Any) -> Optional[int]:
    try:
        return int(float(str(v).strip().replace(",", "").replace("$", "")))
    except (TypeError, ValueError):
        return None


def _to_float(v: Any) -> Optional[float]:
    try:
        return float(str(v).strip().replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None


# ── Attestation parsing (moved verbatim from sqs_service, single owner) ──────

_TRUTHY_TOKENS = {"yes", "true", "1", "y", "no prior losses", "no losses", "no claims"}
_FALSY_TOKENS = {"no", "false", "0", "n", ""}

# Short answers that unambiguously mean "nothing to report" on a loss question.
# Exact match only: as a SUBSTRING several of these appear inside sentences that
# mean the opposite ("nothing was closed without payment").
_NOTHING_ANSWERS = frozenset({
    "none", "nil", "nothing", "zero", "none known", "none reported",
    "nothing to report", "none to report", "no losses to report",
    "no claims to report", "n/a - none", "none at all",
})

# The applicant stating they DID have losses. Checked only AFTER the no-loss
# detector, so a negated form ("we have had no claims") is never caught here.
_HAD_LOSSES_RE = re.compile(
    r"\b(have had|has had|we had|there (?:have been|were|was)|"
    r"filed (?:a|an|\d)|open claim)", re.I)

# "zero claims" / "0 losses" - a count of nothing, written out.
_ZERO_COUNT_RE = re.compile(r"\b(?:zero|0)\s+(?:prior\s+)?(?:claims?|losses|loss)\b", re.I)

# THRESHOLD statements: "no losses exceed $10,000" means losses EXIST but none
# cross a cap - the opposite of an attestation. `detect_no_loss_assertion`
# already refuses these, but the loose legacy fallback below ("no " + "loss")
# would happily re-admit them, so the same guard has to apply there. This word
# list mirrors normalization._NO_LOSS_QUALIFIERS.
_THRESHOLD_RE = re.compile(
    r"\b(exceed|exceeding|over|above|in excess|greater than|more than)\b", re.I)


def attested_true(value) -> bool:
    """Safely interpret an attestation value as a boolean.

    Avoids the bug where bool("No") / bool("false") / bool("0") evaluate True
    (any non-empty string is truthy in Python). For an evidence field - where a
    stored "No" must mean *not* attested - we parse the token explicitly and only
    fall back to Python truthiness for non-string values (e.g. a real bool/int).

    FREE TEXT (2026-08-24): the questionnaire offers a two-option select, but the
    producer's recommendation card is a plain text box, so real answers arrive as
    "None", "Zero claims", "loss free", "clean loss history". Those are routed
    through ``normalization.detect_no_loss_assertion`` - the SAME detector the
    ACORD checkbox and the narrative scan already use, so the three surfaces can
    never disagree, and its threshold guard ("no losses exceed $10,000") comes
    along for free. A bare "No" is deliberately NOT attested: on this fact it
    carries the legacy meaning "no, we have had losses", and inverting it would
    silently re-label every stored answer.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    s = str(value).strip().lower()
    if s in _FALSY_TOKENS:
        return False
    if s in _TRUTHY_TOKENS:
        return True
    stripped = s.strip(" .!,;:-")
    # 1. The canonical no-loss phrase detector (handles loss-free, claims-free,
    #    clean loss history, no known/reported losses, and negated sentences).
    try:
        from services.normalization import detect_no_loss_assertion
        if detect_no_loss_assertion(s):
            return True
    except Exception:                                         # noqa: BLE001
        pass
    # 2. Short "nothing to report" answers and written-out zero counts.
    if stripped in _NOTHING_ANSWERS or _ZERO_COUNT_RE.search(s):
        return True
    # 3. An explicit statement that losses DID occur, or a threshold statement
    #    ("no losses exceed $10,000" - losses exist, none above a cap), is
    #    never an attestation.
    if _HAD_LOSSES_RE.search(s) or _THRESHOLD_RE.search(s):
        return False
    # 4. Legacy fallback: a phrase mentioning "no" loss/claim counts as attested;
    #    anything else is treated as not-attested (conservative).
    return ("no " in s and ("loss" in s or "claim" in s))


def user_attested_no_losses(facts: dict, flags: dict) -> bool:
    """An affirmative no-loss ATTESTATION by the insured/producer (client 2.5
    'Insured No-Loss Attestation') - never the narrative-only mention."""
    facts, flags = facts or {}, flags or {}
    return (
        bool(flags.get("no_prior_losses"))
        or attested_true(_fv(facts, "no_prior_losses"))
        or attested_true(_fv(facts, "loss_history_no_prior_losses_indicator"))
    )


def narrative_states_no_losses(facts: dict, flags: dict) -> bool:
    return bool((flags or {}).get("narrative_states_no_losses"))


def no_loss_attested_any(facts: dict, flags: dict) -> bool:
    """Attestation OR narrative mention - the historical combined predicate."""
    return user_attested_no_losses(facts, flags) or narrative_states_no_losses(facts, flags)


# ── New Venture (client 2.2 / 2.10) ──────────────────────────────────────────

def new_venture_answer(value) -> Optional[bool]:
    """Parse a stored New Venture answer. None = no usable answer (blank is
    never a 'No' - the client's standing principle). ``startswith('no')``
    deliberately wins over the 'no prior operations' phrase so a bare typed
    'no' and option two both read False; a producer typing the fragment
    'no prior operations' alone therefore reads False too, which fails toward
    SCORING the pillar (the safe direction), never toward N/A."""
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    if s.startswith("yes") or s == "y":
        return True
    if s.startswith("no") or s == "n":
        return False
    # DELIBERATELY NOT LISTED: a bare "new business". On an ACORD submission
    # that is the TRANSACTION TYPE (new business vs renewal), and a 20-year-old
    # company moving carriers is "new business" too - reading it as a new
    # VENTURE would wrongly remove the pillar for an established insured.
    # Unrecognised text returns None, which scores the pillar normally: the
    # safe direction, since only a positive answer can reach Not Applicable.
    if any(p in s for p in (
            "new venture", "no prior operations", "brand new", "newly formed",
            "newly established", "just started", "just opened", "start-up",
            "startup", "first year of operation", "no operating history",
            "recently started", "recently formed", "no prior business")):
        return True
    return None


def new_venture_confirmed(facts: dict, flags: dict) -> bool:
    """Producer-confirmed New Venture (client 2.2: 'If the producer confirms').

    The flag (written by the producer-answer apply path) is authoritative when
    present; the stored fact is the durable fallback. Documents can never set
    this - confirmation is a human act."""
    facts, flags = facts or {}, flags or {}
    if "new_venture_confirmed" in flags:
        return bool(flags.get("new_venture_confirmed"))
    return new_venture_answer(_fv(facts, NEW_VENTURE_FIELD)) is True


def prior_operations_evidence(facts: dict, flags: dict,
                              has_loss_run_doc: bool = False) -> List[str]:
    """POSITIVE evidence that prior operations existed (client 2.10's
    'contradictory source information'). Returns the evidence names found so a
    producer message can say exactly why the N/A was withheld; empty list =
    nothing contradicts the confirmation. Absence of evidence is never treated
    as evidence - only these affirmative signals count."""
    facts, flags = facts or {}, flags or {}
    out: List[str] = []
    if has_loss_run_doc:
        out.append("loss runs uploaded")
    if _fv(facts, "prior_carrier"):
        out.append("a prior carrier is named")
    if (_to_int(_fv(facts, "num_claims")) or 0) > 0:
        out.append("prior claims recorded")
    if (_to_float(_fv(facts, "total_incurred")) or 0.0) > 0:
        out.append("incurred losses recorded")
    if (_to_int(_fv(facts, "loss_history_years")) or 0) > 0:
        out.append("loss-history years recorded")
    _renewal = str(_fv(facts, "is_renewal") or "").strip().lower()
    if _renewal in ("yes", "true", "renewal", "1", "y"):
        out.append("submission marked as a renewal")
    return out


def new_venture_contradicted(facts: dict, flags: dict,
                             has_loss_run_doc: bool = False) -> bool:
    return bool(prior_operations_evidence(facts, flags, has_loss_run_doc))


def new_venture_applicable(facts: dict, flags: dict,
                           has_loss_run_doc: bool = False) -> bool:
    """True only when the Loss History pillar should be Not Applicable:
    producer-confirmed New Venture with NO positive evidence of prior
    operations. This is the single gate the scorer, the display state and the
    questionnaire all consult (client 2.2)."""
    return (
        new_venture_confirmed(facts, flags)
        and not new_venture_contradicted(facts, flags, has_loss_run_doc)
    )


def loss_history_not_applicable(facts: dict, flags: dict,
                                has_loss_run_doc: bool = False) -> bool:
    """Every route to "there is no loss history to evaluate" - the ONE gate the
    scorer, the display state and the questionnaire consult.

    Two routes, both requiring the same contradiction guard:
      * the producer confirms New Venture (client 2.2), or
      * the business is 0-1 years old and says it has no known losses
        (Brent 2026-08-24: *"0-1 years will not have loss runs because the
        business is too young"*). A no-loss ANSWER is required - silence still
        scores as no information, so a blank questionnaire can never buy its
        way out of the pillar.
    """
    facts, flags = facts or {}, flags or {}
    if new_venture_applicable(facts, flags, has_loss_run_doc):
        return True
    return (
        too_young_for_loss_runs(facts, flags, has_loss_run_doc)
        and (no_loss_attested_any(facts, flags) or no_runs_available_stated(facts)
             or loss_runs_pending_stated(facts, flags))
    )


# Whole-answer forms of "there was no prior carrier". Exact match, because as
# substrings these are too easy to hit inside a real carrier's name.
_UNINSURED_ANSWERS = frozenset({
    "none", "n/a", "na", "nil", "nothing", "no carrier", "first time",
    "new coverage", "not insured", "uninsured",
})
# Phrases that carry the meaning wherever they appear in a longer answer
# ("No prior coverage - this is their first policy").
_UNINSURED_PHRASES = (
    "no prior carrier", "no prior coverage", "no previous carrier",
    "no previous coverage", "never insured", "never been insured",
    "never carried", "never had insurance", "never had coverage",
    "previously uninsured", "not previously insured", "first time buying",
    "first policy", "first-time buyer", "new to insurance", "no expiring",
)


def previously_uninsured(facts: dict) -> bool:
    """The applicant has affirmatively said they carried no prior coverage.

    BRENT RULING 2026-08-24 (Q13): *"the applicant would be 'previously
    uninsured', which is very different from 'missing prior carrier'."* The
    curated question already invites the answer ("If none, write 'None'"), but
    the producer's card is free text, so both the one-word answer and the
    written-out one have to land - "None", "never insured", "No prior coverage
    - new to insurance". Anything unrecognised reads as a real carrier name,
    which is the safe direction: it keeps today's deduction rather than
    silently waiving it.
    """
    raw = (facts or {}).get("prior_carrier")
    # VALUE STATE FIRST (fix 2026-08-25, found on the S9 live run). Since
    # `answer_semantics` shipped, an answer of "None" is stored as an EMPTY
    # value carrying `value_state: explicit_no` - so reading the value text
    # alone found "" and reported False, the -10 stayed, and the producer's
    # answer visibly did nothing. The two mechanisms have to agree, and the
    # state is the authoritative one.
    if isinstance(raw, dict) and raw.get("value_state") in ("explicit_no", "not_applicable"):
        return True
    v = str(_fv(facts or {}, "prior_carrier") or "").strip().lower()
    v = v.strip(" .!,;:-")
    if not v:
        return False
    if v in _UNINSURED_ANSWERS:
        return True
    return any(p in v for p in _UNINSURED_PHRASES)


def prior_coverage_evidence(facts: dict, flags: dict,
                            has_loss_run_doc: bool = False) -> bool:
    """POSITIVE evidence that prior coverage actually existed - the only state
    in which a missing prior carrier is a GAP rather than a non-question."""
    facts, flags = facts or {}, flags or {}
    if has_loss_run_doc:
        return True                     # runs exist, so a policy existed
    if str(_fv(facts, "is_renewal") or "").strip().lower() in ("yes", "true", "renewal", "1", "y"):
        return True                     # a renewal has an expiring policy by definition
    if flags.get("is_renewal"):
        return True
    for key in ("prior_policy_number", "prior_effective_date", "prior_expiration_date",
                "prior_carrier_naic"):
        if _fv(facts, key):
            return True
    return False


def prior_carrier_applicable(facts: dict, flags: dict,
                             has_loss_run_doc: bool = False) -> bool:
    """Client 2.3 "missing WHEN APPLICABLE", as refined by Brent 2026-08-24.

    Three states, not two:
      * confirmed new venture      -> never applicable (client 2.3)
      * previously uninsured       -> never applicable. Brent's example: a
        solo owner adding Workers Comp for the first time has no prior WC
        carrier to name, and *"they wouldn't deserve a deduction"*.
      * no evidence prior coverage existed -> not applicable either. *"To be
        safe, there probably shouldn't be a deduction here for now."* The -10
        survives only where the package itself shows a prior policy existed
        (a renewal, prior-policy facts, or uploaded loss runs) and the carrier
        is still absent - which is the literal meaning of MISSING.
    """
    if new_venture_confirmed(facts, flags):
        return False
    if previously_uninsured(facts):
        return False
    return prior_coverage_evidence(facts, flags, has_loss_run_doc)


# ── Years in business -> what loss evidence is reasonable to expect ──────────
# BRENT RULING 2026-08-24 (Q11 answered, and a correction to what shipped):
# *"we can't treat 'N/A' as '0'. These are not the same. 'No known losses' is a
# legitimate answer ... If 'no known losses', check against the number of years
# in business."*
#   0-1 years  "will not have loss runs because the business is too young"
#   1-5 years  "a satisfactory answer would be 'no known losses' (or 'loss runs
#              pending' ...) to get through a submission, though the submission
#              would likely not bind without them, especially 3-5 years"
#   5+ years   "loss runs are pretty much required"
BAND_YOUNG = "young"            # <= 1 year: no operating history to run
BAND_ESTABLISHING = "establishing"   # > 1 and < 5 years
BAND_ESTABLISHED = "established"     # >= 5 years
BAND_UNKNOWN = "unknown"        # no usable years figure - never assume one


def years_in_business_band(facts: dict) -> str:
    """The applicant's operating-history band, or BAND_UNKNOWN.

    Unknown is a real answer, not a default to the strictest band: a missing
    years figure must never manufacture a penalty (the blank-over-wrong rule).
    """
    raw = _fv(facts or {}, "years_in_business")
    try:
        years = float(str(raw).strip().replace(",", ""))
    except (TypeError, ValueError):
        return BAND_UNKNOWN
    if years < 0:
        return BAND_UNKNOWN
    if years <= 1:
        return BAND_YOUNG
    if years < 5:
        return BAND_ESTABLISHING
    return BAND_ESTABLISHED


def too_young_for_loss_runs(facts: dict, flags: dict,
                            has_loss_run_doc: bool = False) -> bool:
    """A business too young to have any loss history AND nothing in the package
    contradicting that. Same contradiction guard as the producer-confirmed new
    venture, because the claim being made is the same one: no operating history
    exists, so there is no loss evidence to withhold."""
    return (
        years_in_business_band(facts) == BAND_YOUNG
        and not new_venture_contradicted(facts, flags, has_loss_run_doc)
    )


# ── Loss-run status (pending / no runs available) ────────────────────────────

def parse_loss_run_status(value) -> Optional[str]:
    """One reader for every shape ``loss_run_status`` can hold: the extraction
    scalars ("pending" / "requested"), the questionnaire option texts above,
    and reasonable producer free text. Returns "pending",
    "no_runs_available", or None (no usable statement)."""
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    # "No runs" FIRST: "no loss runs have been requested" is an availability
    # answer, and testing "request" first would misread it as pending.
    if any(p in s for p in (
            "no loss run", "no runs", "none available", "not available",
            "unavailable", "cannot provide", "can't provide", "unable to provide",
            "do not exist", "don't exist", "none exist", "no records",
            "will not be provided", "cannot obtain")):
        return "no_runs_available"
    if any(p in s for p in (
            "pending", "request", "order", "await", "in progress", "in process",
            "will be uploaded", "will provide", "to follow", "on the way",
            "chasing", "follow up", "expected")):
        return "pending"
    return None


def loss_runs_pending_stated(facts: dict, flags: dict) -> bool:
    facts, flags = facts or {}, flags or {}
    if flags.get("loss_run_pending"):
        return True
    return parse_loss_run_status(_fv(facts, LOSS_RUN_STATUS_FIELD)) == "pending"


def no_runs_available_stated(facts: dict) -> bool:
    return parse_loss_run_status(_fv(facts or {}, LOSS_RUN_STATUS_FIELD)) == "no_runs_available"


# ── Prior claims exist (client 2.9) ──────────────────────────────────────────

def had_claims_answer(facts: dict) -> bool:
    """The insured explicitly answered that they HAVE had claims (the second
    ``_NO_LOSS_OPTIONS`` option, or equivalent wording). A bare legacy "No"
    stored on the indicator also meant 'we had losses' and is preserved."""
    v = _fv(facts or {}, "loss_history_no_prior_losses_indicator")
    if v is None:
        return False
    s = str(v).strip().lower()
    if not s:
        return False
    if attested_true(v):
        return False
    # "Yes - we have had claims or losses" / free text naming claims had.
    if "have had" in s or "had claims" in s or "had losses" in s:
        return True
    # Legacy bare "No" answer to "no prior losses?" = they had losses.
    return s in ("no", "n", "false")


def prior_claims_exist(facts: dict, flags: dict) -> bool:
    facts = facts or {}
    return (
        (_to_int(_fv(facts, "num_claims")) or 0) > 0
        or (_to_float(_fv(facts, "total_incurred")) or 0.0) > 0
        or had_claims_answer(facts)
    )


# ── The canonical state (client 2.9) ─────────────────────────────────────────

def resolve_loss_history_state(facts: dict, flags: dict,
                               has_loss_run_doc: bool = False) -> str:
    """The one canonical loss-history state. Decision order mirrors the
    scoring paths (2.3-2.5) so the state and the number can never disagree:
    N/A first, then documents in hand, then the attestation (which outranks
    pending - client 2.5: attestation + runs pending scores as the
    attestation), then pending, then known claims, then availability, then
    the narrative shading, then nothing."""
    facts, flags = facts or {}, flags or {}
    # The client's own state name is "New Venture / NO PRIOR OPERATIONS", so a
    # 0-1 year business reporting no known losses belongs to this same state -
    # it is the second route to "there is no loss history to evaluate", and it
    # must suppress the same questions.
    if loss_history_not_applicable(facts, flags, has_loss_run_doc):
        return STATE_NEW_VENTURE
    if has_loss_run_doc:
        # A doc classified loss_run that only SAYS runs are pending (no years,
        # no claims) is a cover letter - honour the pending state (mirrors the
        # scorer's shortcut).
        if (
            parse_loss_run_status(_fv(facts, LOSS_RUN_STATUS_FIELD)) == "pending"
            and (_to_int(_fv(facts, "loss_history_years")) or 0) == 0
            and (_to_int(_fv(facts, "num_claims")) or 0) == 0
            and (_to_float(_fv(facts, "total_incurred")) or 0.0) == 0.0
        ):
            return STATE_LOSS_RUNS_PENDING
        return STATE_LOSS_RUNS_UPLOADED
    if user_attested_no_losses(facts, flags):
        return STATE_NO_KNOWN_LOSSES_ATTESTED
    if loss_runs_pending_stated(facts, flags):
        return STATE_LOSS_RUNS_PENDING
    if prior_claims_exist(facts, flags):
        return STATE_PRIOR_CLAIMS_EXIST
    if no_runs_available_stated(facts):
        return STATE_NO_LOSS_RUNS_AVAILABLE
    if narrative_states_no_losses(facts, flags):
        return STATE_NO_LOSS_NARRATIVE_ONLY
    return STATE_MISSING_UNANSWERED


# ── Questionnaire gating (client 2.10) ───────────────────────────────────────

# Questions that presume prior operations. Suppressed for a verified new
# venture. The prior-policy trio rides with prior_carrier - asking for a prior
# policy number is asking about the same nonexistent history.
_NEW_VENTURE_SUPPRESSED = frozenset({
    "prior_carrier", "prior_carrier_naic", "num_claims", "loss_history_years",
    "total_incurred", "total_paid", "open_claims_count",
    "prior_policy_number", "prior_effective_date", "prior_expiration_date",
    "loss_history_no_prior_losses_indicator", LOSS_RUN_STATUS_FIELD,
})

# Client 2.10 Loss Runs Uploaded: "Do not ask whether loss runs are available.
# Validate what is already present." The availability-class questions go; a
# claim COUNT stays askable because unreadable runs leave it genuinely useful.
_UPLOADED_SUPPRESSED = frozenset({
    "loss_history_years", "loss_history_no_prior_losses_indicator",
    LOSS_RUN_STATUS_FIELD,
})


def suppressed_question_fields(facts: dict, flags: dict,
                               has_loss_run_doc: bool = False) -> frozenset:
    """Fields the questionnaire must NOT ask in the current loss-history state.

    Fail-open by construction: an unknown/missing state suppresses nothing.
    The contradiction clause (2.10) is honoured through new_venture_applicable
    - a contradicted New Venture confirmation suppresses nothing, so the
    questions come back exactly when the evidence says they matter."""
    state = resolve_loss_history_state(facts, flags, has_loss_run_doc)
    if state == STATE_NEW_VENTURE:
        return _NEW_VENTURE_SUPPRESSED
    if state == STATE_LOSS_RUNS_UPLOADED:
        return _UPLOADED_SUPPRESSED
    return frozenset()
