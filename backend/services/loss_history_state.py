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


def attested_true(value) -> bool:
    """Safely interpret an attestation value as a boolean.

    Avoids the bug where bool("No") / bool("false") / bool("0") evaluate True
    (any non-empty string is truthy in Python). For an evidence field - where a
    stored "No" must mean *not* attested - we parse the token explicitly and only
    fall back to Python truthiness for non-string values (e.g. a real bool/int).
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
    # Unknown free text on a no-loss indicator: a phrase that mentions "no" loss
    # counts as attested; anything else is treated as not-attested (conservative).
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
    if "new venture" in s or "no prior operations" in s:
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


def prior_carrier_applicable(facts: dict, flags: dict) -> bool:
    """Client 2.3: prior carrier is expected context WHEN APPLICABLE; a
    confirmed new venture has no prior carrier to name, so the missing -10
    never applies to it (even while the confirmation is contradicted - the
    contradiction is flagged separately and deducting too would double-punish
    one uncertainty)."""
    return not new_venture_confirmed(facts, flags)


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
    if "no loss runs" in s or s in ("unavailable", "none available", "not available"):
        return "no_runs_available"
    if "pending" in s or "request" in s or "will be uploaded" in s:
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
    if new_venture_applicable(facts, flags, has_loss_run_doc):
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
