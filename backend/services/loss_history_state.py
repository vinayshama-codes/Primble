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
- No Known Losses (owner, 29 Sep 2026, Orbin item 15): an attestation nothing
  contradicts makes the Loss History pillar Not Applicable in the SCORER
  (``attested_no_losses_not_applicable``). The canonical state stays
  ``no_known_losses_attested``, so questionnaire gating does not move.
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

import math
import re
from datetime import date
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

# The producer's answer to "do these loss runs belong to this insured?" (23 Oct
# 2026, package fc04c74f). A run whose insured NAME matches but carries no FEIN
# or policy number scored `possible` and its only row asked for the PACKAGE
# FEIN - already filled, so the row measured 0 and nothing could lift Loss
# History. The producer is the one who knows: a "Yes" here makes a name-matched
# run a person-confirmed STRONG match in the one match door
# (`loss_run_identity.match_loss_run_identity`); a "No" leaves it unmatched.
LOSS_RUN_OWNERSHIP_FIELD = "loss_run_ownership_confirmed"
LOSS_RUN_OWNERSHIP_OPTIONS = (
    "Yes - these loss runs belong to this insured",
    "No - they are another insured's loss runs",
)


OWNERSHIP_DOCS_KEY = "for_documents"


def _doc_key(d: Any) -> str:
    return str((d or {}).get("doc_id") or (d or {}).get("filename") or "") if isinstance(d, dict) else ""


def ownership_scope(docs: Any) -> List[str]:
    """The loss runs a person's ownership answer is about: those in the package
    (not excluded) when it was given, by document id (else file name)."""
    return sorted({_doc_key(d) for d in (docs or []) if isinstance(d, dict) and not d.get("excluded")
                   and str(d.get("doc_type") or "") == "loss_run" and _doc_key(d)})


def ownership_answer_covers(facts: Any, doc: Any) -> bool:
    """True when the recorded ownership answer was given for this loss run. An
    answer stored before 26 Oct 2026 carries no list and keeps its old,
    package-wide reach."""
    held = (facts or {}).get(LOSS_RUN_OWNERSHIP_FIELD) if isinstance(facts, dict) else None
    scope = held.get(OWNERSHIP_DOCS_KEY) if isinstance(held, dict) else None
    if not isinstance(scope, list):
        return True
    return _doc_key(doc) in scope


def ownership_question_open(facts: Any, docs: Any) -> bool:
    """Is the ownership question still to ask? Unanswered, or answered before a
    loss run now on file arrived (that run is not covered by the answer)."""
    if loss_run_ownership_answer(facts) is None:
        return True
    return any(not ownership_answer_covers(facts, d) for d in (docs or [])
               if isinstance(d, dict) and not d.get("excluded") and str(d.get("doc_type") or "") == "loss_run")


def loss_run_ownership_answer(facts: Any) -> Optional[bool]:
    """The producer's ownership answer: True / False, or None when unanswered.
    Same no-inversion reading as `new_venture_answer` (a bare Yes / No keeps
    its meaning; anything else is no answer)."""
    v = _fv(facts, LOSS_RUN_OWNERSHIP_FIELD)
    if v is None:
        return None
    s = str(v).strip().lower()
    if s.startswith("yes") or s in ("y", "true", "confirmed"):
        return True
    if s.startswith("no") or s in ("n", "false"):
        return False
    return None


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


# ── New-venture derivations (V1 H4, client section 9, 2026-08-27) ───────────
# Section 9.1's Years in Business row: Applies When = "Applicable business
# submission", Scoring Home = "Structural Tier 2 + Narrative context",
# Key Rule = **"New venture is valid state"**.
#
# It was not a valid state anywhere. Measured before this shipped: with the
# producer's New Venture confirmed, `value_state_of(facts,'years_in_business')`
# returned `not_stated`, `sqs_service._tier2_items` listed "Years in business"
# as MISSING - charging 1/6 of Tier 2 - and the questionnaire still asked "How
# many years has your business been open?" of a business the producer had just
# confirmed has no operating history. The state existed; the FACT never learned
# it (the same shape as H1's X-Mod and H3's payroll-by-state).
_NEW_VENTURE_DERIVED_KEYS = ("years_in_business",)
_NEW_VENTURE_DERIVATION_RULE = "not_applicable_on_confirmed_new_venture"


def _is_our_new_venture_derivation(raw: Any) -> bool:
    """Is this fact OUR conclusion rather than someone's evidence?

    Only a value this module wrote may be withdrawn by this module. A
    document-sourced or human-entered years figure is evidence and is never
    touched - if it disagrees with a New Venture confirmation that is a genuine
    conflict for the producer (principle 4), not something to overwrite.
    """
    if not isinstance(raw, dict):
        return False
    return ((raw.get("derivation") or {}).get("rule")
            == _NEW_VENTURE_DERIVATION_RULE)


def apply_new_venture_derivations(facts: dict, flags: dict,
                                  has_loss_run_doc: bool = False) -> List[str]:
    """Keep the derived new-venture facts in step with the confirmation.

    Mutates `facts` in place and returns the list of keys the caller must pass
    to `upd_processing_session(delete_facts=[...])`. Returning them rather than
    popping is deliberate: D18 - the facts merge is ADDITIVE, so a bare `pop`
    is a silent no-op and the stale value survives the write.

    NOT APPLICABLE, NOT ZERO. The first cut of this wrote `years_in_business =
    "0"` and adversarial review measured what that does: `years_in_business_band`
    returns BAND_YOUNG, `too_young_for_loss_runs` becomes True, and route 2 of
    `loss_history_not_applicable` fires ON THE BAND ALONE - so the moment the
    New Venture confirmation was withdrawn, `calculate_p4_loss_history` returned
    None (the Loss History pillar DELETED) where it had returned 60. The band
    also buys nothing while the confirmation stands, because route 1 already
    covers it. All risk, no benefit - and it argues with Brent's own ruling
    (2026-08-24): *"we can't treat 'N/A' as '0'. These are not the same."*
    An N/A envelope gives band=unknown, leaves the pillar at 60, still retires
    the Tier 2 charge (C3 3.6 removes a Not Applicable fact from the
    DENOMINATOR), still retires the question, and displays as "NOT APPLICABLE" -
    which is literally what the client calls this state.
    """
    facts = facts if isinstance(facts, dict) else {}
    delete: List[str] = []
    applicable = new_venture_applicable(facts, flags or {}, has_loss_run_doc)
    for key in _NEW_VENTURE_DERIVED_KEYS:
        raw = facts.get(key)
        if applicable:
            # Never over a stated value, whoever stated it. A real years figure
            # beside a New Venture confirmation is a CONFLICT for the producer.
            if _is_our_new_venture_derivation(raw):
                continue                     # already ours and still correct
            if raw is not None and not _is_blank_fact(raw):
                continue
            facts[key] = {
                "value": "",
                "confidence": "deterministic",
                "source": "derived",
                "evidence_state": "derived",
                "value_state": "not_applicable",
                # E&O 5.7: the rule and its inputs live on the envelope, so
                # "Source: derived" always explains itself.
                "derivation": {"rule": _NEW_VENTURE_DERIVATION_RULE,
                               "inputs": [NEW_VENTURE_FIELD]},
            }
        elif _is_our_new_venture_derivation(raw):
            # THE PREMISE WENT AWAY, SO THE CONCLUSION MUST TOO. A withdrawn or
            # contradicted confirmation has to take the derived N/A with it, or
            # Tier 2 keeps excusing a field the submission genuinely owes.
            delete.append(key)
    return delete


def _is_blank_fact(raw: Any) -> bool:
    value = raw.get("value") if isinstance(raw, dict) else raw
    if value is None:
        return True
    return str(value).strip().lower() in ("", "null", "none")


_CLAIM_ROW_MONEY_COLUMNS = ("paid", "reserved_amount", "incurred", "amount")
_CLAIM_ROW_DETAIL_COLUMNS = ("date", "description", "line_of_business")


# "Total" / "Summary" open a total line only as a LABEL - "Total loss of
# vehicle" and "Summary judgment defense" are claims (Z42 review A).
_TOTAL_LINE_RE = re.compile(
    r"^\s*(?:all\s+(?:lines?|coverages?|policies)\b|(?:grand\s+|sub\s*)?totals?\b"
    r"(?!\s+(?:loss\b|theft\b|destruction\b|collapse\b|burn))|summary\s*(?:$|[:|(\-]|"
    r"(?:for|of\s+(?:all|claims|losses))\b))", re.I)


# A POLICY PERIOD in a date column ("2023-2024", "2023 / 24") is the year a
# summary line totals, never the date a loss happened.
_YEAR_RANGE_RE = re.compile(r"^\s*(?:19|20)\d{2}\s*[-/\u2013]\s*(?:(?:19|20)\d{2}|\d{2})\s*$")


def _row_is_a_period_total(row: dict) -> bool:
    """A loss-run SUMMARY line, not a claim (live f575160b, 25 Oct 2026): "2025-2026 |
    All lines | 12 | 151700 | ... | 322650" - a policy year's claim COUNT and totals,
    extracted as one "claim" of $322,650 beside the 12 real claims. A row naming
    all lines / a total, with no claim number and no loss date, is a total. A date
    column holding only a policy period is no loss date (27 Oct 2026: a re-read of
    the same CSV put "2023-2024" in `date`, and the year's total printed on ACORD
    125 as a claim)."""
    if not _is_blank_fact(row.get("claim_number")):
        return False
    for c in ("claim_date", "date", "loss_date"):
        v = row.get(c)
        if not _is_blank_fact(v) and not _YEAR_RANGE_RE.match(str(v.get("value") if isinstance(v, dict) else v)):
            return False
    for col in ("line_of_business", "description", "line"):
        val = str(row.get(col) or "")
        if not val.strip():
            continue
        if _TOTAL_LINE_RE.search(val) or re.search(r"\|\s*all\s+lines?\s*\|", val, re.I):
            return True
    return False


def _row_states_a_claim(row: Any) -> bool:
    """Does this `loss_history` row assert an actual CLAIM?

    ONE DOOR for that question - `asserted_claims` and `claims_are_corroborated`
    both ask it, so a row can never count as a claim for one and not the other.

    THE ROW THAT IS NOT A CLAIM (live run 2026-09-05, found in the session data,
    identical on W1 / W3 / W4):

        {"date": null, "claim_date": null,
         "description": "no prior losses or claims in the last five years",
         "amount": null, ...}

    The extraction model wrote the NO-LOSS SENTENCE INTO THE CLAIMS TABLE as a
    row. `asserted_claims` counts a row on any non-blank detail column, so the
    sentence saying there are no claims was counted as a claim - which then
    contradicted the attestation it restates, and printed *"Conflicting -
    attested no losses but loss runs show claims"* on nine clean packages.

    `normalization.detect_no_loss_assertion` is the door that already decides
    this question everywhere else (`extraction_pipeline`'s flag, `pdf_service`'s
    "Check if none" box), so the three can never disagree. Measured against it:
    "Slip and fall at job site", "water damage to stockroom", "rear-end
    collision, no injuries" and "No injuries reported on this claim" all still
    count as claims; "no prior losses or claims in the last five years", "No
    Known Losses" and "loss-free" do not.

    Money always wins: a row carrying a real amount is a claim whatever its
    description says.
    """
    if not isinstance(row, dict):
        return False
    if _row_is_a_period_total(row):
        return False
    money = 0.0
    for column in _CLAIM_ROW_MONEY_COLUMNS:
        money += _to_float(row.get(column)) or 0.0
    if money > 0:
        return True
    try:
        from services.normalization import detect_no_loss_assertion
    except Exception:                                          # noqa: BLE001
        detect_no_loss_assertion = None                        # fail to prior behaviour
    for column in _CLAIM_ROW_DETAIL_COLUMNS:
        value = row.get(column)
        if _is_blank_fact(value):
            continue
        if detect_no_loss_assertion is not None:
            try:
                if detect_no_loss_assertion(str(value)):
                    continue        # the attestation restated, not a claim
            except Exception:                                  # noqa: BLE001
                pass
        return True
    return False


def claim_rows(rows: Any) -> list:
    """The rows of a `loss_history` list that actually state a CLAIM.

    The public face of ``_row_states_a_claim``, added 2026-09-08 so the form
    STAMPER can ask the same question the scorer already asks.

    WHY IT WAS NEEDED. The 2026-09-05 fix put the gate here, in the scoring
    module, and nothing else could reach it: the ACORD 125 stamper binds
    ``LossHistory_OccurrenceDescription`` straight to
    ``facts["loss_history"][i]["description"]`` through ``_SCHEDULE_REGISTRY``,
    with no filter of any kind. So the scorer correctly ignored the no-loss
    SENTENCE the extraction model writes into the claims table, and the printed
    form carried it anyway - live 2026-09-08, ACORD 125 claim row A read
    *"The applicant has had no known losses in the past five years."* with SUBRO
    N and CLAIM OPEN N beside it, on a package with no claims. A gate in the
    layer the SCREEN does not read is not a gate.

    Order is preserved and non-claim rows are DROPPED, not blanked, so a real
    claim sitting behind a sentence row moves up into row A where the form
    expects the first claim.

    A ROW MAY ALSO EARN ITS PLACE BY IDENTITY, and it must (found 2026-09-08).
    ``_row_states_a_claim`` looks only at money and at date / description /
    line_of_business. Extraction also emits rows keyed on ``claim_number`` and
    ``claim_date``, so

        {"claim_number": "88213", "claim_date": "03/14/2024", "open_code": "Y"}

    was dropped - a REAL extracted claim deleted off the printed form. Harmless
    in the scorer, where that gate was written; unacceptable in a stamper.

    THE SCORER'S GATE IS NOT WIDENED TO FIX IT, deliberately. The live phantom
    row carries ``open_code: "N"`` beside its no-loss sentence, so admitting
    status columns as identity would make the sentence a claim again and undo
    both the 2026-09-05 conflict fix and this one. A claim NUMBER and a claim
    DATE are hard identifiers a narrative sentence never produces; an open flag
    is not. That is the structural second condition, and it lives here - on the
    printing side - rather than in the shared definition of "is this a claim?".
    """
    if not isinstance(rows, list):
        return rows if rows is None else list(rows or [])
    return [row for row in rows
            if _row_states_a_claim(row) or _row_has_claim_identity(row)]


# Hard identifiers only. `open` / `open_code` / `subrogation_code` are STATUS
# columns - the phantom row has them - and are deliberately absent.
_CLAIM_IDENTITY_COLUMNS = ("claim_number", "claim_date")


def _row_has_claim_identity(row: Any) -> bool:
    """Does this row name a specific claim, whatever else it is missing?"""
    if not isinstance(row, dict):
        return False
    return any(not _is_blank_fact(row.get(col)) for col in _CLAIM_IDENTITY_COLUMNS)


_LOSS_RUN_DOC_TYPE = "loss_run"


def package_has_loss_runs(docs: Any, facts: Any) -> bool:
    """Does this submission carry LOSS RUNS? ONE door (5 Oct 2026).

    It was read off the document TYPE alone, at eight sites. One uploaded PDF
    has one type, so a submission package that bundles its loss runs with the
    application, the decs and the e-mails (CH125: 59 pages, typed "narrative")
    read as "no runs on file" - Loss History 25, "request loss runs" - beside
    16 extracted claims and a 09/15/2026 valuation.

    The loss-run FACTS are the evidence when the type is not: a valuation date
    plus either the run's own period or claim rows a carrier numbered. A
    narrative that only MENTIONS a valuation has neither, and a clean run
    (no claims) still prints its period.
    """
    for d in docs or []:
        if isinstance(d, dict) and not d.get("excluded") \
                and str(d.get("doc_type") or "").strip() == _LOSS_RUN_DOC_TYPE:
            return True
    if not isinstance(facts, dict) or not _fv(facts, "loss_run_valuation_date"):
        return False
    if _fv(facts, "loss_run_period_start") or _fv(facts, "loss_run_period_end"):
        return True
    rows = _fv(facts, "loss_history")
    return isinstance(rows, list) and any(
        isinstance(r, dict) and _row_states_a_claim(r)
        and str(r.get("claim_number") or "").strip()
        for r in rows)


def no_loss_statements_contradict(statements: Any, facts: Any) -> bool:
    """Does any no-loss STATEMENT the documents make contradict the claims?

    5 Oct 2026 (CH125 6eda3069). An account-level statement does whenever the
    package asserts a claim (today's rule). A statement scoped to ONE line does
    only when a claim on that line falls inside its window ("Umbrella - no
    known losses" beside Auto claims does not). A loss-run row about a policy
    year never does - it is part of the verified history. Unreadable input:
    True for any statement, i.e. today's behaviour.
    """
    try:
        from services.lob_canon import canon_line
        from services.normalization import normalize_date
    except Exception:                                          # noqa: BLE001
        return bool(statements)
    stmts = [s for s in (statements or []) if isinstance(s, dict)]
    if not stmts:
        return False
    claims, incurred = asserted_claims(facts)
    if not (claims or incurred):
        return False
    rows = _fv(facts, "loss_history")
    rows = [r for r in rows if _row_states_a_claim(r)] if isinstance(rows, list) else []
    anchor = (normalize_date(_fv(facts, "loss_run_valuation_date"))
              or date.today().isoformat())
    for st in stmts:
        scope = st.get("scope")
        if scope == "account":
            return True
        if scope != "line" or not st.get("line"):
            continue
        if not rows:
            return True                      # claims with no line to tell them apart
        for r in rows:
            fam = canon_line(r.get("line_of_business") or r.get("line") or r.get("description"))
            if fam != st.get("line"):
                continue
            years = st.get("years")
            if not years:
                return True
            when = normalize_date(r.get("date") or r.get("claim_date"))
            if not when:
                return True
            try:
                y, m, d = (int(x) for x in anchor.split("-"))
                start = date(y - int(years), m, min(d, 28)).isoformat()
            except Exception:                                  # noqa: BLE001
                return True
            if when >= start:
                return True
    return False


def asserted_claims(facts: Any) -> tuple:
    """How many claims does this package assert, and for how much?

    THE ONE DOOR for that question - V1 BETA EXIT (2026-08-28).

    The client's beta-exit criterion is *"contradictory no-loss evidence remains
    visible and appropriately capped"*, and it did not hold. Every consumer read
    the scalars `num_claims` / `total_incurred` and nothing read the
    `loss_history` TABLE - the client's own claims schedule
    (`schedule_capture.SCHEDULE_DEFS["loss_history"]`: date, line, description,
    paid, reserved). Nothing derives one from the other: extraction only counts
    claims out of loss-run TEXT, so a claim the insured or the producer TYPED
    was invisible. Measured before this fix, on the real scorer:

        attested "no prior losses" + one typed claim row  -> 60, no conflict
        the same claim as num_claims=1                    -> 45 + conflict

    - i.e. the more explicit the evidence, the less it counted. The same
    blindness sat in `prior_operations_evidence`, so a typed claim could not
    stop a New Venture confirmation from making Loss History Not Applicable.

    Returns `(claims, incurred)`. Both are a MAXIMUM, never a sum of the two
    sources: a loss run stating 3 claims and a table listing those same 3 rows
    is one set of facts printed twice, and adding them would manufacture 6.

    Counts a row only on POSITIVE content - a real date, description, line or
    money figure. A half-typed or empty row asserts nothing, and inventing a
    claim from one would be the mirror of the bug: a false conflict capping a
    clean submission at 45.
    """
    claims = _to_int(_fv(facts, "num_claims")) or 0
    incurred = _to_float(_fv(facts, "total_incurred")) or 0.0

    rows = _fv(facts, "loss_history")
    if isinstance(rows, list):
        row_count = 0
        row_incurred = 0.0
        for row in rows:
            if not _row_states_a_claim(row):
                continue
            row_count += 1
            # One figure per claim (25 Oct 2026): its incurred, else its amount,
            # else paid + reserve. Adding all four counted one claim's money two
            # or three times ($625,050 for Brent's $322,650 file).
            inc = _to_float(row.get("incurred")) or _to_float(row.get("amount"))
            if not inc:
                inc = (_to_float(row.get("paid")) or 0.0) + (_to_float(row.get("reserved_amount")) or 0.0)
            row_incurred += inc or 0.0
        claims = max(claims, row_count)
        incurred = max(incurred, row_incurred)

    return claims, incurred


# (A private `_HUMAN_SOURCES` set lived here - defined, never read. Removed 27
# Oct 2026; "did a person state this?" is `fact_state`'s one door.)


def claims_are_corroborated(facts: Any, has_loss_run_doc: bool = False) -> bool:
    """Is the claim evidence something OTHER than a bare model inference?

    THE FALSE POSITIVE THIS EXISTS FOR (live run 2026-09-05, nine sessions of
    nine): every clean package printed *"Conflicting - attested no losses but
    loss runs show claims"*, *"Losses extracted"* and a producer card worth up
    to +8 pts, on documents containing **no loss run at all** whose narrative
    plainly stated *"the applicant reports no prior losses or claims in the last
    five years."*

    `_loss_history_conflict`'s own docstring has always said the contradiction
    must come *"by ACTUAL loss-run claims"* - and it never checked one existed.
    `num_claims` and `total_incurred` reach the extraction schema as bare
    `string or null` entries with NO guiding rule (`extraction_service` ~:296 /
    :323), so the model is free to return a figure read off a premium, a limit
    or prose. A correct rule fed by an invented input - the same class as the
    `has_workers_comp` mention flag and D43's payroll period.

    THE GATE IS DELIBERATELY NARROW. It refuses ONLY the case it can PROVE:
    every claim figure present is explicitly `source: "ai"` and nothing else
    backs it. A bare scalar carries no provenance, so nothing can be asserted
    about who supplied it and the pre-2026-09-05 behaviour stands - the same
    reasoning `fact_state.human_provenance_facts` already applies to bare
    scalars. Positive evidence, never an inference about an inference.

    Corroborated when ANY of:

    1. a document was classified as a loss run;
    2. `loss_run_age_days` is stated - a valuation age is only derivable from an
       actual loss run, never from prose;
    3. the client's / producer's own claims TABLE carries a row with real
       content - the V1 BETA EXIT (2026-08-28) path, which must keep working:
       *"attested no losses + one TYPED claim row"* is a genuine conflict with
       no loss run uploaded anywhere;
    4. a claim figure that is NOT provably model-authored - human provenance, or
       a bare value whose origin is unknown.

    Suppressing a WARNING is the safe direction: nothing here deletes a value,
    and a rule that cries wolf on every clean submission is one producers learn
    to ignore.
    """
    facts = facts if isinstance(facts, dict) else {}
    if has_loss_run_doc:
        return True
    if not _is_blank_fact(_fv(facts, "loss_run_age_days")):
        return True

    rows = _fv(facts, "loss_history")
    if isinstance(rows, list):
        if any(_row_states_a_claim(row) for row in rows):
            return True

    for key in ("num_claims", "total_incurred"):
        raw = facts.get(key)
        value = raw.get("value") if isinstance(raw, dict) and "value" in raw else raw
        if _is_blank_fact(value):
            continue
        source = (raw.get("source") if isinstance(raw, dict) else None) or ""
        if str(source).strip().lower() != "ai":
            return True          # provenance unknown or human - do not second-guess
    # Every claim figure present is explicitly model-authored, or there is no
    # claim figure at all. Neither is corroboration. (Caught by the fuzz test:
    # an empty facts dict used to answer True, which reads as "corroborated" for
    # a package that asserts nothing.)
    return False


# The rule `extraction_service._derive_prior_carrier` labels its value with -
# one name, read by both sides (15 Sep 2026).
PRIOR_CARRIER_DERIVATION_RULE = "carrier_of_the_expiring_policies"


def _is_derived_prior_carrier(raw: Any) -> bool:
    """Is `prior_carrier` the carrier of the uploaded policy in force, which
    the merge filled in so the client is not asked it? That value is the
    CURRENT carrier, not a person naming a prior one, so it is no evidence
    against a New Venture confirmation."""
    return (isinstance(raw, dict)
            and (raw.get("derivation") or {}).get("rule") == PRIOR_CARRIER_DERIVATION_RULE)


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
    if _fv(facts, "prior_carrier") and not _is_derived_prior_carrier(facts.get("prior_carrier")):
        out.append("a prior carrier is named")
    # Through the one door (2026-08-28) so a claim TYPED into the client's own
    # claims table contradicts a New Venture confirmation exactly as a claim
    # counted out of a loss run does. Before this, a confirmed new venture with
    # a typed claim row still resolved to Not Applicable.
    _claims, _incurred = asserted_claims(facts)
    if _claims > 0:
        out.append("prior claims recorded")
    if _incurred > 0:
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


# Where the documents print a policy's term. Proposed dates (`effective_date` /
# `expiration_date` on a renewal) are deliberately absent: they are the term
# being APPLIED for, not one the business has lived through.
_PRINTED_TERM_SOURCES = ("_line_records", "coverage_lines",
                         "prior_coverage_by_line", "prior_coverage_lines")


def completed_policy_term(facts: dict, today: Optional[Any] = None) -> bool:
    """Do the documents show a policy term that has already ENDED?

    A business insured through a whole term operated through it, so it is not
    "a new venture with no prior operations" - the New Venture card's own
    words. Orbin (live, 28 Sep): its only policies ran 07/15/2025 - 07/15/2026
    and the card still asked the producer to consider New Venture status.

    Deliberately NOT part of `prior_operations_evidence`: that door judges a
    CONFIRMED New Venture, and an in-force first policy is exactly what a real
    new venture has. This only stops the card from being suggested; a
    producer's own confirmation is judged exactly as before.
    """
    from datetime import date as _date
    from services.normalization import normalize_date
    facts = facts or {}
    today_iso = (today or _date.today()).isoformat()
    ends: List[Any] = [_fv(facts, "prior_expiration_date")]
    for key in _PRINTED_TERM_SOURCES:
        rows = _fv(facts, key)
        for row in (rows if isinstance(rows, list) else []):
            if isinstance(row, dict):
                ends.append(row.get("expiration_date"))
    for raw in ends:
        iso = normalize_date(raw) if raw not in (None, "") else None
        if iso and iso <= today_iso:
            return True
    return False


def new_venture_answered(facts: dict, flags: dict) -> bool:
    """Has the producer ANSWERED the New Venture question - either way?

    Deliberately separate from `new_venture_confirmed`, which asks "is the
    answer YES". C2-G's whole point is that "what is the value?" and "did they
    answer?" are two different questions, and conflating them is what produced
    the defect this exists to fix:

    LIVE RUN 2026-08-27 (H7 S1). The "confirm New Venture status" recommendation
    was emitted whenever loss history was absent, with no reference to whether
    it had already been answered. Answering YES makes the pillar Not Applicable,
    the rec stops being generated and the card closes. Answering NO - the honest
    answer for most accounts - changes nothing the scorer looks at, so the rec
    was re-emitted identically, the auto-resolve pass never stamped it, and the
    card sprang straight back to Open with an empty dropdown. The producer's
    answer WAS saved (fact, envelope and audit row all correct); it just looked
    like it had not been, so the owner answered it three times.

    "Only one of the two answers can ever retire this card" is the class. A
    confirm-X prompt must stop asking once X has been confirmed EITHER way; the
    genuine underlying gap (no loss history) keeps its own separate rec, which
    is correct and still open.
    """
    facts, flags = facts or {}, flags or {}
    if "new_venture_confirmed" in flags:
        return True
    return new_venture_answer(_fv(facts, NEW_VENTURE_FIELD)) is not None


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


def attested_no_losses_not_applicable(facts: dict, flags: dict,
                                      has_loss_run_doc: bool = False) -> bool:
    """An attested "No Known Losses" takes Loss History out of the score.

    OWNER DECISION 29 Sep 2026 (Orbin item 15). Michelle: *"Why is Loss Runs
    still showing 60%? We've confirmed No Known Losses. It should not calculate
    against the score."* The same mechanism a confirmed New Venture uses: the
    pillar is Not Applicable and the remaining pillars rescale. In EVERY
    years band - an attested "none" is literally "not calculated".

    False, so the pillar is SCORED exactly as before, when:
      * a loss-run document is on file - documents outrank an attestation;
      * nobody attested - the narrative's passing mention is not one (40 stays);
      * the insured ALSO answered "we have had claims" - a stale flag beside a
        claims answer is not an attestation anyone still stands behind;
      * claims are asserted AND corroborated - the conflict door
        (`sqs_service._loss_history_conflict`) owns that case, and its 45
        ceiling keeps it visible. A model-only claim figure is not
        corroboration (the same rule the conflict door applies), so it cannot
        hold the pillar in the score either.

    Deliberately NOT folded into `loss_history_not_applicable`: that gate also
    drives the questionnaire state, and an established business attesting "no
    losses" is not a New Venture - it has a real prior carrier, so the
    prior-carrier / prior-policy questions must still be asked.

    Writes no derived fact. Withdrawing the attestation (or answering "we have
    had claims") restores the pillar on the next score, with nothing to clean up.
    """
    facts, flags = facts or {}, flags or {}
    if has_loss_run_doc:
        return False
    if not user_attested_no_losses(facts, flags):
        return False
    if had_claims_answer(facts):
        return False
    claims, incurred = asserted_claims(facts)
    if (claims > 0 or incurred > 0) and claims_are_corroborated(facts, has_loss_run_doc):
        return False
    return True


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


def years_in_business_value(facts: dict) -> Optional[float]:
    """The applicant's years in business as a number, or None when no usable
    figure is on file (blank, unreadable, negative). The one reader the band
    and the loss-run years requirement share."""
    raw = _fv(facts or {}, "years_in_business")
    try:
        years = float(str(raw).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    if years != years or years < 0:                  # NaN or negative
        return None
    return years


# LOSS-RUN YEARS ARE JUDGED AGAINST THE YEARS THE BUSINESS HAS EXISTED (Brent,
# 23 Oct 2026, Z34-1 #2): "if a business has only existed 1-5 years, evaluate
# the loss history against the years the business has actually existed. Do not
# penalize it for years before it existed. If the business has existed longer
# than the loss history provided, treat the missing period as incomplete."
LOSS_YEARS_WINDOW = 5     # the most years of runs ever asked for (client 2.3)


def loss_years_required(facts: dict) -> Optional[int]:
    """How many years of loss runs give full credit: min(5, the business's age
    rounded up), at least 1 - or None when the age is unknown (the caller keeps
    the 5-year rule; an unknown age never lowers the bar)."""
    age = years_in_business_value(facts)
    if age is None:
        return None
    return max(1, math.ceil(min(float(LOSS_YEARS_WINDOW), age)))


# ── Only the years inside the window count (owner, 24 Oct 2026, Z38 lane E) ──
# A loss run wholly before the last min(5, business age) years (2019-2021 alone,
# reviewed in 2026) says nothing about the risk being written and gave full
# Loss History years. The window ends at the earlier of today and the proposed
# effective date (a stale effective more than a year back is ignored), and opens
# `required` years before it, less a 90-day grace - carriers treat a run valued
# within 90 days as current, so a fresh 5-year run is never cut to 4 by its own
# valuation lag. A run partly inside counts only its inside part.
LOSS_WINDOW_GRACE_DAYS = 90


def loss_window_start(facts: Any, today: Optional[date] = None) -> date:
    """The first day a loss run's years count from. Never raises."""
    from datetime import timedelta
    anchor = today or date.today()
    try:
        from services.normalization import normalize_date
        iso = normalize_date(_fv(facts or {}, "effective_date"))
        if iso:
            y, m, d = (int(p) for p in str(iso).split("-")[:3])
            eff = date(y, m, d)
            if eff < anchor and (anchor - eff).days <= 366:
                anchor = eff
    except Exception:                                          # noqa: BLE001
        pass
    # The latest term the documents show, when it has ENDED (live c5dc03ec,
    # 25 Oct 2026): the decs' 2025-26 term ended 01/01/2026 and the proposed
    # term rolled to 2027, so runs reaching 01/01/2026 are as current as the
    # submission's own paperwork - counting back from today cut them to 4 of 5.
    # Never while a term is IN FORCE today (effective past, expiration future):
    # then today stands, and last year's end must not pull the window back.
    try:
        from services.normalization import normalize_date

        def _d(key):
            iso = normalize_date(_fv(facts or {}, key))
            if not iso:
                return None
            y, m, d = (int(p) for p in str(iso).split("-")[:3])
            return date(y, m, d)
        _today = today or date.today()
        eff, exp = _d("effective_date"), _d("expiration_date")
        in_force = bool(eff and exp and eff <= _today < exp)
        if not in_force:
            ended = [e for e in (_d("prior_expiration_date"), exp)
                     if e and e <= anchor and (anchor - e).days <= 731]
            if ended:
                anchor = max(ended)
    except Exception:                                          # noqa: BLE001
        pass
    required = loss_years_required(facts or {}) or LOSS_YEARS_WINDOW
    try:
        start = anchor.replace(year=anchor.year - required)
    except ValueError:                                         # 29 Feb
        start = anchor.replace(year=anchor.year - required, day=28)
    return start - timedelta(days=LOSS_WINDOW_GRACE_DAYS)


def years_inside_window(start: date, end: date, facts: Any,
                        today: Optional[date] = None) -> Optional[int]:
    """Years of the run start..end that fall inside the window, or None when the
    run lies wholly inside it (the caller keeps its own count, unchanged)."""
    ws = loss_window_start(facts, today)
    if start >= ws:
        return None
    if end <= ws:
        return 0
    return max(0, min(round((end - ws).days / 365.25), 10))


def years_in_business_band(facts: dict) -> str:
    """The applicant's operating-history band, or BAND_UNKNOWN.

    Unknown is a real answer, not a default to the strictest band: a missing
    years figure must never manufacture a penalty (the blank-over-wrong rule).
    """
    years = years_in_business_value(facts)
    if years is None:
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


def stored_pending_counts(facts: dict, flags: dict, has_loss_run_doc: bool,
                          years: int = 0) -> bool:
    """Does a stored "requested / pending" loss-run status still COUNT? ONE door
    for the scorer, the pillar's state label and the questionnaire state (23 Oct
    2026, package fc04c74f).

    With no loss-run document on file: whenever it is stated (unchanged).
    With one on file the runs are here, so a PERSON's earlier "requested and
    pending" answer is out of date and is ignored. The document's OWN statement
    still counts in the one case it always did - a file classified as a loss run
    that only SAYS the runs are pending (a cover letter): no claim years, no
    claim, no claim row."""
    facts, flags = facts or {}, flags or {}
    if not has_loss_run_doc:
        return loss_runs_pending_stated(facts, flags)
    if parse_loss_run_status(_fv(facts, LOSS_RUN_STATUS_FIELD)) != "pending":
        return False
    try:
        from services.fact_state import typed_by_person
        if typed_by_person(facts.get(LOSS_RUN_STATUS_FIELD)):
            return False
    except Exception:                                     # noqa: BLE001
        pass
    if years:
        return False
    claims, incurred = asserted_claims(facts)
    return not claims and not incurred


_YEAR_RE = re.compile(r"\b(19[5-9]\d|20\d\d)\b")
_SHORT_YEAR_DATE_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-](\d{2})\b")


def loss_run_years_suggestion(facts: Any) -> Optional[List[int]]:
    """The distinct years the loss runs' own claim rows fall in, oldest first -
    a SUGGESTION for "how many years do the runs cover", never a stored value.
    None when no row states a year."""
    rows = _fv(facts, "loss_history")
    if not isinstance(rows, list):
        return None
    years = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for col in ("date", "claim_date", "policy_year", "policy_period", "policy_effective_date"):
            text = str(row.get(col) or "")
            m = _YEAR_RE.search(text)
            if m:
                years.add(int(m.group(1)))
                break
            m = _SHORT_YEAR_DATE_RE.search(text)        # 03/15/25
            if m:
                years.add(2000 + int(m.group(1)))
                break
    return sorted(years) or None


def markable_loss_run_documents(docs: Any) -> List[int]:
    """The positions in `docs` of the uploaded documents NOT typed as loss runs
    whose classifier scored `loss_run` best (`classification.scores`) - the
    runs are on file, only the type is wrong (5472449a, 23 Oct 2026). Upload
    order. Reads the classification only; never changes it."""
    out: List[int] = []
    for n, d in enumerate(docs or []):
        if not isinstance(d, dict) or d.get("excluded") \
                or str(d.get("doc_type") or "").strip() == _LOSS_RUN_DOC_TYPE:
            continue
        scores = (d.get("classification") or {}).get("scores") if isinstance(d.get("classification"), dict) else None
        if not isinstance(scores, dict) or not scores:
            continue
        try:
            best = max(scores.items(), key=lambda kv: float(kv[1] or 0))
        except (TypeError, ValueError):
            continue
        if best[0] == _LOSS_RUN_DOC_TYPE and float(best[1] or 0) > 0:
            out.append(n)
    return out


def unmarked_loss_run_documents(docs: Any) -> List[str]:
    """The filenames of `markable_loss_run_documents`, upload order."""
    docs = list(docs or [])
    return [str(docs[n].get("filename") or "the uploaded document")
            for n in markable_loss_run_documents(docs)]


def no_runs_available_stated(facts: dict) -> bool:
    return parse_loss_run_status(_fv(facts or {}, LOSS_RUN_STATUS_FIELD)) == "no_runs_available"


# ── Prior claims exist (client 2.9) ──────────────────────────────────────────

def had_claims_answer(facts: dict) -> bool:
    """The insured explicitly answered that they HAVE had claims (the second
    ``_NO_LOSS_OPTIONS`` option, or equivalent wording naming claims had).

    A bare negative ("No", "n", "false", "0", "off") is NOT a claims answer
    (1 Oct 2026). It is what unticking ACORD 125 "Check if none" writes back
    (`pdf_service.normalize_writeback_value`), and an untick RETRACTS the
    attestation - it never says "we have had claims". It is also ambiguous on
    its own: the old card asked "no prior losses?" (No = had losses) while the
    question asked today is "Have you had any claims?" (No = none). Read as
    claims it put a retraction into "Prior claims known" and asked for loss
    runs; read as nothing it is "no information", the safe direction. Known
    claims still read through the words that name them here, and through
    `num_claims` / `total_incurred` / loss runs in `prior_claims_exist`."""
    v = _fv(facts or {}, "loss_history_no_prior_losses_indicator")
    if v is None:
        return False
    s = str(v).strip().lower()
    if not s:
        return False
    if attested_true(v):
        return False
    # "Yes - we have had claims or losses" / free text naming claims had.
    return "have had" in s or "had claims" in s or "had losses" in s


def claims_question_answers() -> tuple:
    """(no claims, had claims): the claims question's two answers as they are
    stored, from their one owner (`arq_service._NO_LOSS_OPTIONS`)."""
    try:
        from services.arq_service import _NO_LOSS_OPTIONS
        return tuple(_NO_LOSS_OPTIONS)
    except Exception:                                          # noqa: BLE001
        return ("No - no claims or losses in the past 5 years",
                "Yes - we have had claims or losses")


def with_claims_answer(facts: Any, flags: Any, answer: str) -> tuple:
    """(facts, flags) as a producer's answer to the claims question leaves them:
    the answer on `loss_history_no_prior_losses_indicator` and the
    `no_prior_losses` flag both of its writers mirror (`arq_service`). Copies;
    the inputs are never changed."""
    f = dict(facts or {})
    f["loss_history_no_prior_losses_indicator"] = {
        "value": answer, "source": "producer", "confidence": "producer"}
    fl = dict(flags or {})
    fl["no_prior_losses"] = bool(attested_true(answer))
    return f, fl


def claims_confirmed_by_person(facts: Any, has_loss_run_doc: bool = False) -> bool:
    """A person answered "we have had claims" and the package holds corroborated
    claims (23 Oct 2026, the Loss History plan): every no-loss statement beside
    them - an attestation, a narrative's sentence - is out of date, so none is
    credited and none raises a conflict. Without corroborated claims the answer
    changes nothing here (a narrative's statement keeps its credit)."""
    if not had_claims_answer(facts):
        return False
    claims, incurred = asserted_claims(facts)
    return bool(claims or incurred) and claims_are_corroborated(facts, has_loss_run_doc)


# ── The narrative's claims stance vs the claims answer (24 Oct 2026) ─────────
# Package 73284179: a producer's narrative reading "Loss history shows 12 claims
# in the past five years, 4 still open, $322,650 incurred" beside the answer
# "No claims" scored 100, Submission Ready, no card - and the reverse pair left
# ACORD 101 printing "no claims" under a "we have had claims" answer. Nothing
# compared the two things the same PERSON said. The reader below gives the
# narrative's stance; `claims_answer_stance` gives the answer's; the warning
# (`sqs_service.evaluate_stops`, `legacy_loss_narrative_mismatch`) fires only
# when both are known and disagree.
#
# ONLY TEXT A PERSON TYPED is read (`fact_state.typed_by_person`): a narrative
# a document supplied, or the model wrote, is not something the producer said,
# and a carrier's boilerplate inside it is no statement about this insured.
# The vocabulary is the module's own and `normalization`'s: the no-loss phrase
# scan (`no_loss_statements`, account scope only), `_ZERO_COUNT_RE`,
# `_NOTHING_ANSWERS`, `_HAD_LOSSES_RE`, the threshold and exception guards.
# Ambiguity is None, never a guess: a text stating both, a no-loss statement
# scoped to one line / one term / fewer than five years, or nothing at all.

NARRATIVE_REMARKS_FACTS = ("additional_remarks_text", "acord101_remarks")
_CLAIMS_WINDOW_YEARS = 5                       # "Any claims in the last 5 years?"

_LOSS_WORD_RE = re.compile(r"\b(?:claims?|loss(?:es)?|incidents?)\b", re.I)
_COUNT_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
                "twelve": 12, "a single": 1, "several": 2, "multiple": 2}
_CLAIM_COUNT_RE = re.compile(
    r"\b(\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"a single|several|multiple)\s+(?:(?:open|closed|prior|reported|paid|total|known|"
    r"pending|separate|small|minor|large|auto|gl|liability|property|workers'?|"
    r"compensation|general|still|insurance)\s+){0,2}(?:claims?|loss(?:es)?)\b"
    r"(?![\s-]*(?:payees?|control|runs?|ratios?|experience|history|record|prevention|"
    r"free|adjusters?|of use)\b)", re.I)
# "We have had excellent loss experience" is no loss: the had-phrase must reach
# the loss word itself, and a loss word naming a record / a role is not one.
_HAD_A_LOSS_RE = re.compile(
    r"\b(?:have had|has had|we had|there (?:have been|has been|were|was)|filed)\s+"
    r"(?:a|an|one|some|several|multiple|\d+)?\s*(?:[a-z$,\d']+\s+){0,4}?"
    r"(?:claims?|loss(?:es)?|incidents?)\b"
    r"(?![\s-]*(?:payees?|control|runs?|ratios?|experience|history|record|prevention|"
    r"free|adjusters?|of use)\b)|\bopen claim", re.I)
# Coverage wording, not a loss: "claims-made" / "claims made" policies.
_CLAIMS_MADE_RE = re.compile(r"\bclaims?[\s-]+made\b", re.I)
# A premium / fee paid is not a loss paid.
_NOT_A_LOSS_AMOUNT_RE = re.compile(r"\b(?:premiums?|deposits?|fees?|tax(?:es)?|dues)\b", re.I)
_LABEL_COUNT_RE = re.compile(
    r"\b(?:claims?|loss(?:es)?|loss count|number of claims)\s*[:=\-]\s*"
    r"(\d{1,4}|none(?:\s+(?:known|reported))?|nil|zero|nothing)\b", re.I)
_INCURRED_RE = re.compile(
    r"(?:\b(?:incurred|paid|reserved?|reserves)\b[^.;\n$]{0,20}[$£€]\s?(\d[\d,]*(?:\.\d+)?)"
    r"|[$£€]\s?(\d[\d,]*(?:\.\d+)?)\s*(?:k\b|m\b)?\s*(?:in\s+|of\s+)?"
    r"(?:total\s+)?(?:incurred|paid|reserved?))", re.I)
_NEGATED_HAD_RE = re.compile(
    r"\b(?:has|have|had|did|does)\s*(?:not|n't|never)\s+(?:had\s+|filed\s+|reported\s+|have\s+)?"
    r"(?:any\s+|a\s+)?(?:prior\s+|known\s+)?(?:claims?|loss(?:es)?)\b"
    r"|\bnever\s+(?:had|filed|reported)\s+(?:any\s+|a\s+)?(?:prior\s+)?(?:claims?|loss(?:es)?)\b"
    r"|\bwithout\s+(?:any\s+|a\s+single\s+)?(?:claims?|loss(?:es)?)\b", re.I)
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
_ANY_PERIOD_RE = re.compile(
    r"\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:full\s+)?years?\b", re.I)
_LONG_PERIOD_RE = re.compile(
    r"\b(?:past|last|prior|previous)\s+(\d{1,2}|six|seven|eight|nine|ten|twenty)\s+years?\b", re.I)
_TERM_TAIL_RE = re.compile(
    r"^[\s,]*(?:in|during|for|since|on)\s+(?:the\s+)?(?:(?:(?:19|20)\d{2}|current|expiring|"
    r"this)\s*(?:policy|term|year)?|(?:last|prior|previous)\s+(?:policy|term|year)\b)", re.I)
_OTHER_ENTITY_RE = re.compile(
    r"\b((?:[A-Z][\w&'.-]*\s+){0,4}[A-Z][\w&'.-]*\s+"
    r"(?:LLC|L\.L\.C\.|Inc\.?|Corp\.?|Corporation|Company|Co\.|Ltd\.?|LLP|LP))(?=\W|$)")
_CLAUSE_SPLIT_RE = re.compile(r"(?<!\d)[.;!?\n\r]+(?!\d)")


def _loss_narrative_question_facts() -> tuple:
    """The narrative questionnaire's free-text facts that ask about losses
    (`services/questionnaire.QUESTIONS`: a `qn_*` long text whose question or
    group names losses, loss control aside) - derived, never listed."""
    try:
        from services.questionnaire import QUESTIONS
    except Exception:                                          # noqa: BLE001
        return ()
    out = []
    for q in QUESTIONS.values():
        fact = getattr(q, "fact", None) or ""
        if not fact.startswith("qn_") or getattr(q, "answer_type", "") != "long_text":
            continue
        words = f"{getattr(q, 'text', '')} {getattr(q, 'group', '') or ''}".lower()
        # LOSSES, not "claims": the EPLI / professional questions ask about
        # employment or professional claims, not this account's loss history.
        if re.search(r"\bloss(?:es)?\b", words) and "loss-control" not in words \
                and "loss control" not in words:
            out.append(fact)
    return tuple(out)


# The words of a remarks envelope a PERSON typed (Z39 lane H, 25 Oct 2026):
# `arq_service.append_producer_narrative` saves the WHOLE remarks under
# "producer" when it appends, so the document's text it was appended to is
# stored as typed. The envelope keeps the person's own parts under this key
# (appended on each save; "Open again" puts the earlier envelope back through
# the fix's receipt; the questionnaire's L.6 replace sets the whole text).
TYPED_PARTS_KEY = "typed_parts"


def person_typed_parts(raw: Any) -> Optional[List[str]]:
    """The parts of a stored text a person typed, or None when the envelope
    does not record them (legacy rows, document text - the caller keeps its
    own reading). A recorded part no longer in the text is dropped (the text
    was edited since)."""
    if not isinstance(raw, dict) or TYPED_PARTS_KEY not in raw:
        return None
    parts = raw.get(TYPED_PARTS_KEY)
    if not isinstance(parts, list):
        return None
    whole = str(raw.get("value") or "")
    out: List[str] = []
    for p in parts:
        t = str(p or "").strip()
        if t and t in whole and t not in out:
            out.append(t)
    return out


def _wholly_typed(raw: Any) -> bool:
    """Every word of the stored text is one a person typed (no recorded
    parts = the legacy reading: the whole text)."""
    parts = person_typed_parts(raw)
    if parts is None:
        return True
    whole = re.sub(r"\s+", " ", str(raw.get("value") or "")).strip()
    return bool(whole) and re.sub(r"\s+", " ", " ".join(parts)).strip() == whole


def person_narrative_texts(facts: Any) -> List[str]:
    """The narrative text a PERSON typed: the producer's remarks
    (`arq_service.append_producer_narrative`) and the narrative questionnaire's
    loss answers - each only when `fact_state.typed_by_person` says so. Of the
    remarks only the parts the person typed when the envelope records them
    (`person_typed_parts`) - a document's sentence they were appended to is
    not the person's statement."""
    if not isinstance(facts, dict):
        return []
    try:
        from services.fact_state import typed_by_person
    except Exception:                                          # noqa: BLE001
        return []
    out: List[str] = []
    for key in NARRATIVE_REMARKS_FACTS + _loss_narrative_question_facts():
        raw = facts.get(key)
        if not typed_by_person(raw):
            continue
        parts = person_typed_parts(raw)
        texts = parts if parts is not None else [str(_fv(facts, key) or "").strip()]
        for text in texts:
            if text and text not in out:
                out.append(text)
    return out


def _count_value(token: str) -> Optional[int]:
    t = str(token or "").strip().lower()
    if t.isdigit():
        return int(t)
    if t in _COUNT_WORDS:
        return _COUNT_WORDS[t]
    if t in ("none", "nil", "zero", "nothing") or t.startswith("none "):
        return 0
    return None


def _clause_is_outside_window(clause: str, today: date) -> bool:
    """A clause whose losses sit wholly before the five-year window (every year
    it names older), or over a period longer than it ("12 claims in the past
    ten years"), cannot answer "Any claims in the last 5 years?"."""
    years = [int(y) for y in _YEAR_RE.findall(clause)]
    if years and max(years) < today.year - _CLAIMS_WINDOW_YEARS:
        return True
    m = _LONG_PERIOD_RE.search(clause)
    if m:
        raw = m.group(1).lower()
        n = int(raw) if raw.isdigit() else {"six": 6, "seven": 7, "eight": 8, "nine": 9,
                                            "ten": 10, "twenty": 20}.get(raw, 0)
        if n > _CLAIMS_WINDOW_YEARS:
            return True
    return False


def _names_another_company(clause: str, applicant: Any) -> bool:
    """The clause names a company that is not the applicant (a prior owner, a
    subcontractor, another insured) - its losses are not this insured's."""
    names = [m.group(1).strip() for m in _OTHER_ENTITY_RE.finditer(clause)]
    if not names:
        return False
    try:
        from services.normalization import same_entity_name
    except Exception:                                          # noqa: BLE001
        return False
    return not any(applicant and same_entity_name(n, applicant) for n in names)


def _clause_stance(clause: str, today: date) -> Optional[str]:
    """"claims" / "no_claims" / None for ONE clause."""
    clause = _CLAIMS_MADE_RE.sub(" ", clause)
    low = clause.lower()
    if not _LOSS_WORD_RE.search(low):
        return None
    try:
        from services.normalization import (
            _NO_LOSS_PHRASES, _tail_introduces_an_exception, _tail_is_a_threshold,
            no_loss_statements,
        )
    except Exception:                                          # noqa: BLE001
        return None
    # A no-loss phrase that carves an exception out of itself ("no claims except
    # one in 2022", "clean loss history apart from a fire") states a loss.
    for phrase in _NO_LOSS_PHRASES:
        idx = low.find(phrase)
        if idx < 0:
            continue
        after = low[idx + len(phrase):]
        if _tail_introduces_an_exception(after):
            return None if _clause_is_outside_window(clause, today) else "claims"
        if _tail_is_a_threshold(after[:24].lstrip()):
            return None                    # losses may exist, none counted
    for st in no_loss_statements(clause):
        after = low[st.get("at", 0) + len(st.get("phrase") or ""):]
        if st.get("scope") != "account" or _TERM_TAIL_RE.match(after):
            continue                       # one line / one term: not the account
        years = st.get("years")
        if years is None:                  # "no claims for 3 years"
            ym = _ANY_PERIOD_RE.search(after[:40])
            if ym:
                raw = ym.group(1).lower()
                years = int(raw) if raw.isdigit() else _COUNT_WORDS.get(raw)
        if years is not None and years < _CLAIMS_WINDOW_YEARS:
            continue                       # covers less than the question asks
        return "no_claims"
    if _NEGATED_HAD_RE.search(low) or _ZERO_COUNT_RE.search(low):
        return "no_claims"
    m = _LABEL_COUNT_RE.search(low)
    if m:
        n = _count_value(m.group(1))
        if n == 0:
            return "no_claims"
        if n:
            return None if _clause_is_outside_window(clause, today) else "claims"
    stated = False
    for m in _CLAIM_COUNT_RE.finditer(low):
        n = _count_value(m.group(1))
        if n and n > 0:
            stated = True
    for m in _INCURRED_RE.finditer(low):
        if _NOT_A_LOSS_AMOUNT_RE.search(low[max(0, m.start() - 20):m.end() + 20]):
            continue                       # "paid $12,000 in premium"
        amt = _to_float((m.group(1) or m.group(2) or "").replace(",", ""))
        if amt and amt > 0:
            stated = True
    if not stated and _HAD_A_LOSS_RE.search(low) and not re.search(r"\b(?:no|not|never|n't)\b", low):
        stated = True
    if stated:
        return None if _clause_is_outside_window(clause, today) else "claims"
    return None


def _rule_stances(texts: List[str], applicant: Any, today: date) -> set:
    found = set()
    for text in texts:
        for clause in _CLAUSE_SPLIT_RE.split(text):
            clause = clause.strip()
            if not clause or _names_another_company(clause, applicant):
                continue
            st = _clause_stance(clause, today)
            if st:
                found.add(st)
    return found


def text_claims_stance(text: Any, today: Optional[date] = None) -> Optional[str]:
    """The rules' stance of one piece of text (no provenance, no reader) - for
    a caller writing narrative words that must not contradict an answer."""
    found = _rule_stances([str(text or "")], None, today or date.today())
    return next(iter(found)) if len(found) == 1 else None


def narrative_claims_stance(facts: Any, today: Optional[date] = None) -> Optional[str]:
    """What the narrative a PERSON typed says about claims in the last five
    years: "claims", "no_claims", or None (says nothing, says both, or only a
    scoped no-loss statement). Clause by clause; a clause naming another
    company is not about this insured."""
    today = today or date.today()
    applicant = _fv(facts, "applicant_name") if isinstance(facts, dict) else None
    found = _rule_stances(person_narrative_texts(facts), applicant, today)
    # The narrative reader's stance (paraphrases: "our loss experience has
    # been spotless") - only when the rules found nothing; where both read a
    # stance and they differ, no stance (never a warning invented by a model).
    ai = _ai_remarks_stance(facts)
    if not found:
        return ai
    if len(found) == 1:
        rule = next(iter(found))
        return rule if ai in (None, rule) else None
    return None


def _ai_remarks_stance(facts: Any) -> Optional[str]:
    """The stored narrative reading's loss stance (`narrative_reader.
    loss_stance`, quote gated), for the remarks a PERSON typed, read for
    exactly the text they hold now - else None."""
    if not isinstance(facts, dict):
        return None
    try:
        from services.extraction_service import _narrative_remarks_text
        from services.fact_state import typed_by_person
        from services.narrative_reader import loss_stance
    except Exception:                                          # noqa: BLE001
        return None
    # The key `_narrative_remarks_text` reads FIRST (acord101_remarks before
    # additional_remarks_text) - else a typed key vouches for a document's text.
    owner = next((k for k in ("acord101_remarks", "additional_remarks_text")
                  if str(_fv(facts, k) or "").strip()), None)
    if owner is None or not typed_by_person(facts.get(owner)):
        return None
    # The reading is of the WHOLE remarks; when part of them is a document's
    # text (Z39 lane H) it is not the person's stance - the rules read the
    # person's own parts.
    if not _wholly_typed(facts.get(owner)):
        return None
    return loss_stance(facts, _narrative_remarks_text(facts))


def claims_answer_stance(facts: Any) -> Optional[str]:
    """What a PERSON answered to "Any claims in the last 5 years?" - the
    answer on `loss_history_no_prior_losses_indicator` only (never a flag, a
    document's checkbox or the narrative): "no_claims" / "claims" / None."""
    if not isinstance(facts, dict):
        return None
    raw = facts.get("loss_history_no_prior_losses_indicator")
    try:
        from services.fact_state import confirmed_by_person
        if not confirmed_by_person(raw):
            return None
    except Exception:                                          # noqa: BLE001
        return None
    if attested_true(_fv(facts, "loss_history_no_prior_losses_indicator")):
        return "no_claims"
    if had_claims_answer(facts):
        return "claims"
    return None


def narrative_answer_mismatch(facts: Any, today: Optional[date] = None) -> Optional[str]:
    """The narrative's stance when it disagrees with the claims answer, else
    None. One rule for the warning, its probe and the review page."""
    answer = claims_answer_stance(facts)
    if answer is None:
        return None
    narrative = narrative_claims_stance(facts, today)
    if narrative is None or narrative == answer:
        return None
    return narrative


def claims_answer_for_narrative(facts: Any, today: Optional[date] = None) -> Optional[str]:
    """The claims question's stored answer that agrees with the person's
    narrative, or None when the narrative takes no stance."""
    stance = narrative_claims_stance(facts, today)
    if stance is None:
        return None
    no_claims, had_claims = claims_question_answers()
    return had_claims if stance == "claims" else no_claims


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
        if stored_pending_counts(facts, flags, True,
                                 _to_int(_fv(facts, "loss_history_years")) or 0):
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


# ── Several loss-run documents cover the years TOGETHER (owner, 24 Oct 2026) ──
# The merge kept ONE document's experience period, so a second run for the
# earlier years (2021-2024 beside 2025-26) never added a year: the page asked
# for "the earlier years", the producer uploaded them, and the score stayed put.
# The package's period is now the contiguous coverage the included loss runs
# give together - the stretch that ends latest, joined across gaps of up to 45
# days - never a span with a hole in it. A person's typed period is kept.
_PERIOD_JOIN_GAP_DAYS = 45


def loss_period_date(v: Any, end: bool = False):
    """A loss-run period date as a `date`, or None. A bare year ("2021" ..
    "2025", read off "Years of loss history 5 (2021-2025)" - live 85e51d02,
    25 Oct) is that whole year: from 1 January, through 31 December. It used to
    read as no period at all, so the run counted no years."""
    from datetime import date as _date, datetime as _dt
    from services.normalization import normalize_date
    v = v.get("value") if isinstance(v, dict) else v
    m = re.fullmatch(r"\s*((?:19|20)\d{2})\s*", str(v if v is not None else ""))
    if m:
        y = int(m.group(1))
        return _date(y, 12, 31) if end else _date(y, 1, 1)
    s = normalize_date(v) if v not in (None, "") else None
    try:
        return _dt.strptime(s, "%Y-%m-%d").date() if s else None
    except (TypeError, ValueError):
        return None


def combine_loss_run_periods(facts: dict, docs) -> bool:
    """Widen facts["loss_run_period_start"/"_end"] to the included loss runs'
    joined coverage. True when it changed them. Never raises."""
    try:
        from datetime import datetime, timedelta
        from services.normalization import normalize_date

        _iso = loss_period_date

        from services.fact_state import typed_by_person as _person   # the one door

        if not isinstance(facts, dict) or _person(facts.get("loss_run_period_start")) \
                or _person(facts.get("loss_run_period_end")):
            return False
        spans = []
        for d in docs or []:
            if not isinstance(d, dict) or d.get("excluded") or d.get("doc_type") != "loss_run":
                continue
            f = d.get("facts") or {}
            a = _iso(f.get("loss_run_period_start"))
            b = _iso(f.get("loss_run_period_end"), end=True) or _iso(f.get("loss_run_valuation_date"))
            if a and b and b >= a:
                spans.append((a, b))
        if len(spans) < 2:
            return False
        spans.sort()
        joined = [list(spans[0])]
        for a, b in spans[1:]:
            if a <= joined[-1][1] + timedelta(days=_PERIOD_JOIN_GAP_DAYS):
                joined[-1][1] = max(joined[-1][1], b)
            else:
                joined.append([a, b])
        start, end = max(joined, key=lambda s: s[1])
        cur_a, cur_b = _iso(facts.get("loss_run_period_start")), _iso(facts.get("loss_run_period_end"), end=True)
        if cur_a == start and cur_b == end:
            return False
        if cur_a and cur_b and cur_a <= start and cur_b >= end:
            return False
        for key, day in (("loss_run_period_start", start), ("loss_run_period_end", end)):
            facts[key] = {"value": day.strftime("%m/%d/%Y"), "source": "derived",
                          "confidence": "deterministic", "value_state": "present"}
        return True
    except Exception:                                          # noqa: BLE001
        return False


def latest_loss_run_valuation(facts: dict, docs) -> bool:
    """The package's loss-run valuation date is the LATEST one among the included
    loss runs (30 Oct 2026). Older periods' runs are valued long ago by nature; the
    run covering the most recent period decides whether the history is current.
    Before this the merge kept whichever document's date won the vote, so adding a
    fresh run beside a 2024 one still read as stale. A person's typed date is kept.
    True when it changed the fact. Never raises."""
    try:
        from services.fact_state import typed_by_person as _person   # the one door
        if not isinstance(facts, dict) or _person(facts.get("loss_run_valuation_date")):
            return False
        best = None
        for d in docs or []:
            if not isinstance(d, dict) or d.get("excluded") or d.get("doc_type") != "loss_run":
                continue
            day = loss_period_date((d.get("facts") or {}).get("loss_run_valuation_date"))
            if day and (best is None or day > best):
                best = day
        if best is None:
            return False
        cur = loss_period_date(facts.get("loss_run_valuation_date"))
        if cur and cur >= best:
            return False
        facts["loss_run_valuation_date"] = {"value": best.strftime("%m/%d/%Y"), "source": "derived",
                                            "confidence": "deterministic", "value_state": "present"}
        return True
    except Exception:                                          # noqa: BLE001
        return False


# ── Loss-run coverage, shown on the review page (owner, 24 Oct 2026) ─────────
# Loss History scores by the TOTAL YEARS the included loss runs cover, so
# including or excluding one file moves the score by different amounts. This
# reader names those years. Display only: `covered` is the scorer's own count
# (`sqs_service._resolve_loss_history_years` on the facts as
# `combine_loss_run_periods` leaves them), never a second count.
def _years_label(years: List[int]) -> str:
    if not years:
        return ""
    return str(years[0]) if len(years) == 1 else f"{years[0]}-{years[-1]}"


def loss_run_coverage(docs: Any, facts: Any) -> Optional[dict]:
    """{"required", "years", "covered", "end_year", "label", "documents"} for the
    package's loss-run documents, or None when it has none. Never raises."""
    try:
        import copy
        from datetime import datetime
        from services.normalization import normalize_date

        _iso = loss_period_date

        def _n_years(a, b) -> int:
            return max(1, min(round((b - a).days / 365.25), 10))

        runs = [d for d in (docs or []) if isinstance(d, dict)
                and str(d.get("doc_type") or "").strip() == _LOSS_RUN_DOC_TYPE]
        if not runs:
            return None
        facts = facts if isinstance(facts, dict) else {}
        documents = []
        for d in runs:
            f = d.get("facts") or {}
            a = _iso(f.get("loss_run_period_start"))
            b = _iso(f.get("loss_run_period_end"), end=True) or _iso(f.get("loss_run_valuation_date"))
            yrs: List[int] = []
            label = ""
            if a and b and b >= a:
                n = _n_years(a, b)
                yrs = [a.year + i for i in range(n)]
                label = f"{_years_label(yrs)} - {n} year{'s' if n != 1 else ''}"
            outside = bool(a and b and b >= a and years_inside_window(a, b, facts) == 0)
            if outside:
                label = (label + " - " if label else "") + "outside the years that count"
            documents.append({"doc_id": str(d.get("doc_id") or ""),
                              "filename": str(d.get("filename") or ""),
                              "years": yrs, "years_label": label,
                              "outside_window": outside,
                              "excluded": bool(d.get("excluded"))})
        # The scorer's count, on the facts as the merge leaves them.
        from services.sqs_service import _resolve_loss_history_years
        f2 = copy.deepcopy(facts)
        combine_loss_run_periods(f2, runs)
        covered = int(_resolve_loss_history_years(f2) or 0)
        start = _iso(f2.get("loss_run_period_start"))
        end = _iso(f2.get("loss_run_period_end"), end=True) or _iso(f2.get("loss_run_valuation_date"))
        if covered and start and end and end >= start:
            # Only the years inside the window are named (Z38 lane E).
            # The LATEST covered years, ending with the last policy year the
            # runs reach, named by its start year (a run ending 01/01/2026 or
            # 07/15/2026 reaches the 2025 year) - counting up from the window's
            # start named 2021-2023 for a 2021-2024 run (Z40).
            # The policy year the period's LAST year starts in: 01/01/2026 and
            # 07/15/2026 reach 2025; a bare-year end, 12/31/2025, reaches 2025
            # too (it read 2024 - live 85e51d02, 25 Oct).
            from datetime import timedelta as _td
            last = max((end - _td(days=364)).year, start.year)
            years = list(range(last - covered + 1, last + 1))
        elif covered:
            last = max((y for doc in documents if not doc["excluded"] for y in doc["years"]),
                       default=datetime.now().year)
            years = list(range(last - covered + 1, last + 1))
        else:
            years = []
        required = loss_years_required(facts) or LOSS_YEARS_WINDOW
        end_year = years[-1] if years else datetime.now().year
        label = f"{min(covered, required) if covered > required else covered} of {required} year{'s' if required != 1 else ''}"
        if years:
            label += f" ({_years_label(years)})"
        return {"required": int(required), "years": years, "covered": covered,
                "end_year": end_year, "label": label, "documents": documents}
    except Exception:                                          # noqa: BLE001
        return None
