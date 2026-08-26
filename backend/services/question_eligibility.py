"""question_eligibility.py - THE ONE DOOR for "should we ask this, and who?"

Client master plan section 4 (Contextual Questionnaire Logic), 2026-08-26.
Read `v1-20AUG.md` entry C4 before changing anything here.

WHY THIS MODULE EXISTS
----------------------
`question_classifier.classify_question` decides who answers a question by
matching SUBSTRINGS AGAINST THE FIELD NAME and by membership in the SQS scoring
tiers. It takes no `facts` argument and never reads a fact's state. The client's
4.1 decision flow is entirely about state:

    Step 1  not applicable            -> no question
    Step 2  already canonically known -> do not ask again
    Step 3  merely Suggested          -> may ask; insurance judgment -> producer
    Step 4  not stated / unable to determine -> ask the right respondent
    Step 5  conflicting               -> producer, NEVER the client

`fact_state.py` already writes exactly that vocabulary onto every envelope
(`value_state` / `evidence_state`) and the questionnaire has never read either
axis. This module is the bridge, and it is the ONLY place the five steps live.

THE SAFETY PROPERTY, AND WHY IT IS STRUCTURAL RATHER THAN CAREFUL
-----------------------------------------------------------------
Every overlay this module can emit does one of exactly three things:

  1. moves a question's audience from CLIENT to PRODUCER;
  2. suppresses a question from the default client set;
  3. re-surfaces a CONFLICTING fact to the PRODUCER.

There is NO code path that moves a question TO the client, and none that widens
what the client is asked. So the change is one-directional: it cannot invent a
client question, and the failure mode of a bug here is "the producer sees one
item too many", never "the insured was asked something they cannot answer".
`tests/test_question_eligibility.py::test_overlay_never_widens_client_exposure`
fails the build if that stops being true.

WHY STEP 3 IS NOT IMPLEMENTED LITERALLY - MEASURED, NOT ASSUMED
---------------------------------------------------------------
Step 3 reads "is the value merely Suggested? ... the client MAY be asked". Taken
literally that would re-ask nearly every fact in the package, because of how the
extractor labels its output. Measured 2026-08-26 against the real writers:

  * `extraction_service._annotate_facts` (~line 1566) writes
    `confidence: "ai_high" | "ai_low"`, `source: "ai"` on EVERY extracted fact.
  * `fact_state.derive_evidence_state` treats a value as SOURCE_VERIFIED only for
    `verified_in_text is True`, `source in {dec_entry, policy_doc_text}` or
    `confidence in {deterministic, filled}`.
  * `verified_in_text` has exactly ONE writer in the whole backend
    (`extraction_service.py:7096`, the dec-entry backfill).

So virtually every LLM-extracted fact is `evidence_state == "suggested"`.
Un-suppressing all of them would turn the questionnaire back into the full
insurance application the client's own "Desired Outcome" and 4.12 forbid.

The reading actually implemented is the one Step 3's own second sentence asks
for: a Suggested value changes ROUTING, not whether we ask. A Suggested value on
an INSURANCE-JUDGMENT fact is surfaced to the PRODUCER to confirm; a Suggested
value on an ordinary business fact stays suppressed exactly as it is today.
That is low volume, matches the clause, and cannot flood anybody.

THE ROUTING TABLE IS AN INPUT, NOT A REPLACEMENT
------------------------------------------------
`INSURANCE_JUDGMENT_FACTS` below is the client's own 4.4 list plus core
principle 5, resolved to real `fact_registry.FACT_REGISTRY` keys (every key was
verified to exist on 2026-08-26 - `gl_class_codes` and `prior_acts_confirmation`
are deliberately absent because no such registry fact exists; see the notes on
those entries). `question_classifier`'s existing pattern tuples still run first
and are untouched, so nothing that routes correctly today changes.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Client 4.4 + core principle 5, resolved to real FACT_REGISTRY keys ────────
# Grouped exactly as the client's document groups them so a future reader can
# diff this against his text line by line.
#
# NOT INCLUDED, deliberately, with the reason:
#   * naics_code / sic_code            - already reach the producer through
#     `question_classifier._PRODUCER_PATTERNS` ("naic" / "sic_code"). Listing
#     them again would be a second copy of one rule.
#   * umbrella_follow_form / underlying_policies - already reach the producer
#     through `_AGENCY_PATTERNS` ("follow_form" / "underlying_insurance").
#   * gl_class_codes                   - NOT a registry fact. The only real key
#     is `gl_class_codes_by_location`, which IS listed.
#   * prior_acts_confirmation          - NOT a registry fact; it exists only as a
#     cross-form question field (`arq_service._CROSS_FORM_QUESTION_MAP`) and is
#     handled by the cross-form branch, which is already producer-side.
INSURANCE_JUDGMENT_FACTS = frozenset({
    # Submission / coverage selection (4.4 "Submission / Coverage")
    "lines_of_business",          # "Lines of insurance requested"
    "effective_date",             # "Final proposed effective date when unresolved"

    # Classification (4.4 "Classification" + core principle 5)
    "gl_class_codes_by_location",
    "wc_class_codes",

    # Commercial Auto (4.4 "Commercial Auto")
    "auto_covered_symbols",
    "auto_liability_limit",
    "auto_deductible_comp",
    "auto_deductible_collision",
    "auto_physical_damage_valuation",
    "garage_liability_limit",
    "garagekeeper_liability_limit",
    "garage_deductible",
    "garagekeeper_comp_deductible",
    "garagekeeper_coll_deductible",

    # General Liability (4.4 "General Liability" + "Coverage limits")
    "gl_limits",
    "gl_each_occurrence",
    "gl_aggregate",
    "gl_products_aggregate",
    "gl_personal_advertising_injury",
    "gl_deductible",
    "retro_date",                 # "Retroactive date interpretation"

    # Property (4.4 "Property")
    "valuation_method",
    "coinsurance_percentage",
    "period_of_restoration",
    "business_income_limit",
    "property_deductible_aop",
    "property_deductible_wind",
    "property_deductible_earthquake",
    "property_deductible_flood",
    "deductible_basis",
    "deductible_application",
    "bop_deductible",
    "crime_deductible",

    # Workers Compensation (4.4 "Workers Compensation")
    "wc_xmod",
    "wc_xmod_effective_date",
    "wc_officer_exclusions",
    "wc_officers",
    "wc_payroll_period",

    # Umbrella / Excess (4.4 "Umbrella" + 4.11)
    "umbrella_limit",
    "umbrella_sir",
    "umbrella_attachment_point",
    "employers_liability_limits",

    # Classification (4.4 + principle 5). ADDED 2026-08-26 after live test S2.
    # These were left out on the assumption that
    # `question_classifier._PRODUCER_PATTERNS` already caught them by name. It
    # does not: ACORD 130 names the field `NamedInsured_SICCode_A`, which
    # lowercases to `namedinsured_siccode_a` and does NOT contain the pattern
    # "sic_code" (the pattern has an underscore, the ACORD name does not). The
    # question reached the CLIENT bucket on the live run. Routing by the
    # canonical fact key is immune to how any given form spells the field, which
    # is the entire reason this table exists.
    "naics_code",
    "sic_code",

    # Umbrella structure (4.11). ADDED 2026-08-26 alongside their new questions
    # and ACORD 131 inventory entries. `umbrella_follow_form` is NOT listed - it
    # already reaches the producer through `_AGENCY_PATTERNS` ("follow_form") -
    # but `underlying_policies` does NOT match that tuple's "underlying_insurance"
    # entry, so it needs naming here.
    "underlying_policies",
})

# Question keys that ask for insurance judgment but are NOT canonical facts, so
# they cannot live in the table above (the anti-rot test requires every entry
# there to exist in FACT_REGISTRY).
#
# `narrative_target_markets` is the live example, found by test S4 on
# 2026-08-26: the narrative "target markets" slot has been repurposed to ask
# *"What is your workers comp experience modifier (EMOD / XMOD)?"*
# (`arq_service._FIELD_QUESTION_MAP`). It is an X-Mod question wearing a
# narrative key, so `wc_xmod` in the table above never matched it and it
# reached the CLIENT bucket. X-Mod is producer-only under 4.4 and 4.10.
INSURANCE_JUDGMENT_QUESTION_KEYS = frozenset({
    "narrative_target_markets",
})

# Facts the client's 4.3 keeps CLIENT-ELIGIBLE even though they sit next to an
# insurance-judgment sibling. Listed explicitly so a future "tidy up" cannot
# sweep them into the table above by pattern:
#   property_building_value / property_bpp_value  - "Building/BPP values when known"
#   construction_type / occupancy_type            - "Construction characteristics"
#   year_built / roof_year / sprinkler_system / fire_protection_class
#   total_payroll / wc_payroll / wc_payroll_by_state - "Payroll by group / by state"
#   percent_subcontracted                          - "Percentage subcontracted"
#   auto_radius_of_operation                       - "Radius of operation"
CLIENT_ELIGIBLE_DESPITE_TOPIC = frozenset({
    "property_building_value", "property_bpp_value",
    "construction_type", "occupancy_type",
    "year_built", "roof_year", "sprinkler_system", "fire_protection_class",
    "total_payroll", "wc_payroll", "wc_payroll_by_state",
    "percent_subcontracted", "auto_radius_of_operation",
})

# Reasons, so the producer UI and the audit trail can say WHY, in the client's
# own vocabulary rather than an engineering one.
REASON_NOT_APPLICABLE = "not_applicable"
REASON_ALREADY_KNOWN = "already_provided"
REASON_INSURANCE_JUDGMENT = "insurance_judgment_producer"
REASON_CONFLICTING = "conflicting_route_to_producer"
REASON_UNABLE = "unable_to_determine"


def is_insurance_judgment(*keys: Optional[str]) -> bool:
    """True when ANY of the supplied identity keys is a producer-only fact.

    Several keys are passed because a question can arrive under its canonical
    fact key, its raw ACORD field name, or an instance-stripped base - the same
    `identity_keys` idea `question_classifier.classify_question` already uses.
    """
    for key in keys:
        if key and (key in INSURANCE_JUDGMENT_FACTS
                    or key in INSURANCE_JUDGMENT_QUESTION_KEYS):
            return True
    return False


def _states(facts: Optional[dict], canonical_key: Optional[str]) -> tuple:
    """(value_state, evidence_state) for a fact, or (None, None) when unknowable.

    Fails soft on purpose: if `fact_state` cannot be imported or the fact is not
    a dict envelope, this module must make NO decision rather than a wrong one.
    """
    if not canonical_key or not isinstance(facts, dict):
        return None, None
    try:
        from services.fact_state import derive_evidence_state, value_state_of
        vs = value_state_of(facts, canonical_key)
        raw = facts.get(canonical_key)
        es = derive_evidence_state(raw)[0] if raw is not None else None
        return vs, es
    except Exception as exc:                                  # noqa: BLE001
        logger.debug("question_eligibility: state unavailable for %s - %s",
                     canonical_key, exc)
        return None, None


def overlay_for(
    question: dict,
    facts: Optional[dict] = None,
) -> Dict[str, Any]:
    """The client's 4.1 flow for ONE already-classified question.

    Returns a (possibly empty) dict of keys to merge onto the question. Never
    mutates its input. The caller applies it, so this stays a pure decision.

    Ordering is the client's, exactly: applicability, then known-value, then
    Suggested, then unknown, then conflicting. Conflicting is evaluated LAST in
    his list but FIRST here for a reason recorded in v1-20AUG.md C4: a
    conflicting fact carries a VALUE, so the already-known branch would swallow
    it before Step 5 could ever route it to the producer.
    """
    from services.question_classifier import (
        AUDIENCE_CLIENT, AUDIENCE_PRODUCER, PRIORITY_INTERNAL,
    )

    canon = question.get("_canonical_key") or question.get("canonical_key")
    field = question.get("field_name") or ""
    audience = question.get("audience")

    identity = (canon, field)
    judgment = is_insurance_judgment(*identity)

    # A fact the client's own 4.3 keeps client-eligible is never re-routed here,
    # whatever its topic neighbours do.
    if canon in CLIENT_ELIGIBLE_DESPITE_TOPIC:
        judgment = False

    vs, es = _states(facts, canon)

    out: Dict[str, Any] = {}

    # ── STEP 5 (evaluated first - see docstring) - CONFLICTING -> PRODUCER ────
    # A conflicting fact HAS a value, so `_fact_is_filled` marks it
    # "already provided" and the question disappears. The client's rule is the
    # opposite: it must reach the producer, and must never reach the client.
    if vs == "conflicting":
        out["audience"] = AUDIENCE_PRODUCER
        out["suppressed"] = True          # suppressed from the CLIENT set...
        out["suppressed_reason"] = REASON_CONFLICTING
        out["priority"] = PRIORITY_INTERNAL
        out["eligibility_step"] = 5
        out["eligibility_reason"] = REASON_CONFLICTING
        # ...but it must still be VISIBLE to the producer, so it is explicitly
        # un-hidden from the producer review list even though the client set
        # drops it. `_drop_not_applicable_questions` and the send guard both
        # honour `suppressed`, and the Agency bucket renders regardless.
        out["producer_review"] = True
        return out

    # ── STEP 1 - NOT APPLICABLE -> no question at all ────────────────────────
    if vs == "not_applicable":
        out["suppressed"] = True
        out["suppressed_reason"] = REASON_NOT_APPLICABLE
        out["priority"] = PRIORITY_INTERNAL
        out["eligibility_step"] = 1
        out["eligibility_reason"] = REASON_NOT_APPLICABLE
        return out

    # ── STEPS 2/3/4 - routing for anything still askable ─────────────────────
    # The single behavioural rule: an insurance-judgment fact is the producer's,
    # whatever its state and whatever the name-pattern classifier concluded.
    # This is core principle 5 ("Do Not Ask the Client to Perform Insurance
    # Classification") and principle 7 ("Unknown Edge Cases Default to Producer
    # Review") expressed once, in one place.
    if judgment and audience == AUDIENCE_CLIENT:
        out["audience"] = AUDIENCE_PRODUCER
        out["suppressed"] = True
        out["suppressed_reason"] = REASON_INSURANCE_JUDGMENT
        out["priority"] = PRIORITY_INTERNAL
        out["producer_review"] = True
        # Step 3 vs Step 4, recorded for the audit trail only - the routing is
        # the same either way, which is the point of principle 7.
        if es == "suggested" and vs == "present":
            out["eligibility_step"] = 3
        elif vs in ("not_stated", "unable_to_determine"):
            out["eligibility_step"] = 4
        else:
            out["eligibility_step"] = 3
        out["eligibility_reason"] = REASON_INSURANCE_JUDGMENT
        return out

    # ── STEP 4 - UNABLE TO DETERMINE, recorded but NOT suppressed ────────────
    # A guard rejected a value for this fact. The question is still asked (the
    # answer is genuinely unknown); this only labels WHY so the producer can see
    # the difference between "the documents were silent" and "we found something
    # and refused it".
    if vs == "unable_to_determine" and not question.get("suppressed"):
        out["eligibility_step"] = 4
        out["eligibility_reason"] = REASON_UNABLE
        return out

    return out


def apply_eligibility(
    questions: List[dict],
    facts: Optional[dict] = None,
) -> Dict[str, int]:
    """Apply the 4.1 flow to every question in-place. Returns a counts summary.

    Fail-open by construction: any exception leaves the question list exactly as
    the existing classifier left it. A questionnaire that asks one question too
    many is recoverable; one that silently stops asking is not.
    """
    counts = {"routed_to_producer": 0, "suppressed_not_applicable": 0,
              "conflicting_to_producer": 0, "unchanged": 0}
    if not questions:
        return counts
    for q in questions:
        try:
            overlay = overlay_for(q, facts)
        except Exception as exc:                              # noqa: BLE001
            logger.warning("question_eligibility: skipped %s - %s",
                           q.get("field_name"), exc)
            continue
        if not overlay:
            counts["unchanged"] += 1
            continue
        reason = overlay.get("eligibility_reason")
        if reason == REASON_CONFLICTING:
            counts["conflicting_to_producer"] += 1
        elif reason == REASON_NOT_APPLICABLE:
            counts["suppressed_not_applicable"] += 1
        elif reason == REASON_INSURANCE_JUDGMENT:
            counts["routed_to_producer"] += 1
        q.update(overlay)
        # The coarse producer-UI bucket is derived from the audience, so it has
        # to be recomputed whenever the audience moves - otherwise a re-routed
        # question keeps rendering in the Client bucket it just left.
        if "audience" in overlay:
            try:
                from services.question_classifier import (
                    BUCKET_LABELS, _AUDIENCE_TO_BUCKET, BUCKET_UNDERWRITING,
                )
                bucket = _AUDIENCE_TO_BUCKET.get(overlay["audience"],
                                                 BUCKET_UNDERWRITING)
                q["bucket"] = bucket
                q["bucket_label"] = BUCKET_LABELS.get(bucket, "")
            except Exception:                                 # noqa: BLE001
                pass
    if counts["routed_to_producer"] or counts["conflicting_to_producer"]:
        logger.info(
            "question_eligibility: %d insurance-judgment question(s) routed to "
            "the producer, %d conflicting fact(s) held for producer resolution",
            counts["routed_to_producer"], counts["conflicting_to_producer"],
        )
    return counts
