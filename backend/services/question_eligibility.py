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

    # ── Policy period and policy administration - V1 H4 (section 9), 2026-08-27
    # Section 9.1's Proposed Effective Date row carries the key rule *"Client
    # does not need to interpret policy period"*, and 4.4 lists policy
    # interpretation as producer-only. `effective_date` was already here; its
    # three siblings were not, and all three reached the CLIENT:
    #   expiration_date - asked as "What date would you like your insurance
    #     coverage to end?", which invites the insured to invent a policy term.
    #     It is a yellow REQUIRED box on ACORD 125
    #     (`pdf_service._ACORD125_REQUIRED_ALWAYS`), it drives the
    #     effective-before-expiration HARD STOP, and on a renewal
    #     `_route_renewal_dates` reassigns it - none of which an insured can
    #     reason about.
    #   audit_period / billing_plan - pure policy administration. The client's
    #     own ACORD 125 walkthrough names the payment plan among the boxes to
    #     populate "only from a verified source".
    # D32 STILL HOLDS: all three keep their questions and their ACORD 125
    # inventory entries - they move to the Agency bucket, they do not stop being
    # asked. Removing a field from the CLIENT is not removing it from the
    # questionnaire.
    "expiration_date",
    "audit_period",
    "billing_plan",

    # `gl_form_type` - "Is your GL policy written on an 'occurrence' or
    # 'claims-made' basis?" reached the CLIENT. That is the definition of policy
    # interpretation (core principle 5), it decides whether a retro date is even
    # meaningful, and an insured guessing it wrong silently changes how the GL
    # section is read. 4.7 puts General Liability form/trigger with the producer.
    "gl_form_type",

    # Classification (4.4 "Classification" + core principle 5)
    "gl_class_codes_by_location",
    "wc_class_codes",
    # V1 BETA EXIT (2026-08-28) - the beta-exit criterion "GL/WC class codes
    # never reach the client" was FALSE on this one key. `gl_class_code_schedule`
    # is a registry fact whose question reads verbatim: "Provide the GL rating
    # schedule per class code (class code, premium/exposure basis, exposure
    # amount i.e. payroll or gross sales, territory, and subcontracted %)" -
    # five insurance classifications in one box, routed to the CLIENT.
    #
    # It escaped every existing guard for a reason worth keeping: it is NOT in
    # `SCHEDULE_DEFS` (so D44's table-level audience split never applied - that
    # rule protects `wc_class_codes` by stripping its producer-only `code`
    # column, and there is no table here to strip), and its key contains
    # "schedule" rather than the `_codes` suffix the sibling entries share.
    # A hand-maintained list cannot see that; `test_no_classification_question
    # _ever_reaches_the_client` (tests/test_question_eligibility.py) now DERIVES
    # the check from every registry question's own text, so a 51st cannot slip
    # in the way this one did.
    "gl_class_code_schedule",

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

    # New Venture status - V1 H4-B, 2026-08-27, found on the owner's live run.
    # The registry entry for `new_venture_indicator` sets `question: None` and
    # `forms: set()` and its own comment reads *"Producer confirmation (client
    # 2.2: 'if the producer confirms') - it is answered from the Loss History
    # card, NEVER ASKED TO THE CLIENT."* It was being asked to the client
    # anyway: `arq_service._FIELD_QUESTION_MAP` carries curated wording for it,
    # which makes `is_curated_client` true, which routes it CLIENT / optional.
    # Observed live on two of the three H4 test packages, including a 12-year-old
    # business with a stated prior carrier.
    #
    # It is not a cosmetic mis-route. `apply_arq_answers_to_session` sets
    # `flags["new_venture_confirmed"]` from this answer exactly as the producer
    # path does, and a confirmed New Venture takes the whole Loss History pillar
    # to Not Applicable (C2 2.2) and now also marks Years in Business Not
    # Applicable (H4-A). That is a scoring-material determination about the
    # ACCOUNT, and client 2.2 gives it to the producer in terms.
    #
    # The producer keeps answering it exactly where C2 put it - the Loss History
    # recommendation card - which is a different surface from the questionnaire
    # and is untouched by this entry.
    "new_venture_indicator",

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
    # THE SAME DEFECT, ONE SLOT OVER - found on the H3 live run (2026-08-27),
    # after C4-S found the first one and did not sweep for siblings.
    # `narrative_growth_trends` has been repurposed to ask
    #   "Provide your WC payroll breakdown by class code - list each class
    #    code, its description, and the associated payroll amount.
    #    (For example: 5183 Plumbing - $320,000; 5190 Electrical - $180,000)"
    # It is a CLASSIFICATION question wearing a narrative key, so `wc_class_codes`
    # in the table above never matched it and it reached the CLIENT bucket -
    # asking the insured to supply NCCI codes, with worked examples. That is
    # core principle 5 and client 8.3 breached in one question.
    # The employee-group TABLE (`wc_class_codes`) is how this is asked now: the
    # client describes the group and its payroll, the producer owns the code.
    # `tests/test_h3_wc_data_capture.py::test_no_client_question_asks_for_a_
    # classification_code` sweeps the whole question map so a third slot cannot
    # ship.
    "narrative_growth_trends",
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
REASON_CONTACT_SATISFIED = "contact_already_provided"
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


def _contact_requirement_already_met(facts: Optional[dict],
                                     canonical_key: Optional[str]) -> bool:
    """Is this a Tier 1 contact question whose requirement ANOTHER contact
    method has already satisfied?

    Client section 9.1, Contact Name / Phone / Email, key rule verbatim:
    *"Any one contact method satisfies Tier 1"* - and `sqs_service._tier1_items`
    implements exactly that, crediting the whole requirement on
    `any(_answered(facts, f) for f in TIER1_CONTACT)`. The QUESTIONNAIRE never
    learned it: all three are in `question_classifier.CRITICAL_FIELDS`, so with
    a phone already known the client was still asked for the name and the email
    as CRITICAL questions, and both were pre-ticked into the send list -
    spending two of the 28 `DEFAULT_SELECT_CAP` slots on a requirement that was
    already met.

    THE FIELD SET AND THE ANSWERED TEST ARE BOTH BORROWED, NEVER RETYPED.
    `TIER1_CONTACT` comes from the scorer, and "answered" is
    `answer_semantics.fact_answered` - the same predicate `sqs_service._answered`
    uses. That matters more than it looks: `fact_answered` is asymmetric on
    absence strings (measured: "N/A" -> True, "None" -> False), so a locally
    written "is it filled" test would disagree with Tier 1 on exactly those
    values and the card would contradict the score again.

    Fail-closed: anything unreadable returns False and the question stays
    exactly as critical as it is today.
    """
    if not canonical_key:
        return False
    try:
        from services.answer_semantics import fact_answered
        from services.sqs_service import TIER1_CONTACT
    except Exception as exc:                                  # noqa: BLE001
        logger.debug("question_eligibility: contact rule unavailable - %s", exc)
        return False
    if canonical_key not in TIER1_CONTACT or not isinstance(facts, dict):
        return False
    # Another METHOD, not this one. A question whose own fact is answered is
    # already handled by the existing "already_provided" suppression, and this
    # rule must never be the thing that retires it.
    return any(fact_answered(facts.get(f))
               for f in TIER1_CONTACT if f != canonical_key)


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
        AUDIENCE_CLIENT, AUDIENCE_PRODUCER, PRIORITY_CRITICAL,
        PRIORITY_IMPORTANT, PRIORITY_INTERNAL, _SCORE_POINTS,
    )

    # V1 H3 (2026-08-27): a TABLE question owns its own audience split - a
    # producer-only column (WC class code, covered-auto symbol) is stripped
    # from the client's copy by `arq_routes.client_view`, and a producer-only
    # TABLE is routed by `arq_service._finalize_schedule_taxonomy`. Judging the
    # whole table by its canonical key (`wc_class_codes` IS an
    # insurance-judgment fact) would flag the client's payroll table
    # "producer review" for the one column the client never sees.
    if question.get("field_type") == "schedule":
        return {}

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
        # THE AUDIENCE STILL HAS TO MOVE (V1 H4, 2026-08-27). This module's
        # docstring promises every overlay does one of three things, the first
        # being "moves a question's audience from CLIENT to PRODUCER" - but
        # this branch set only suppression, so an INSURANCE-JUDGMENT fact that
        # happened to be Not Applicable was still reported `audience: client`,
        # `bucket: client`. `test_overlay_never_widens_client_exposure` cannot
        # see it because that test only drives facts which STARTED non-client.
        # Harmless while the question is suppressed, and wrong the moment
        # anything reads the audience - which is exactly what
        # `test_vehicle_use_is_a_client_question_and_payroll_period_is_the_
        # producers` does, and why it caught this.
        # Core principle 5 is unconditional: a classification / policy-
        # interpretation fact is the producer's in EVERY state, not only the
        # states we happened to enumerate.
        if judgment and audience == AUDIENCE_CLIENT:
            out["audience"] = AUDIENCE_PRODUCER
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

    # ── Tier 1 contact - one requirement, three questions (V1 H4, 2026-08-27) ─
    # DEMOTED, NEVER SUPPRESSED, and the difference is the whole design.
    # `apply_default_selection` sends PRIORITY_OPTIONAL to its final
    # `else: default_selected = False; suggested = False`, so demoting that far
    # would leave `NamedInsured_Contact_FullName_A` and
    # `..._PrimaryEmailAddress_A` blank AND unasked - the exact "blank box,
    # nobody asked" outcome the coverage-guarantee injector was rewritten to
    # stop. A filled contact_phone stamps neither of those boxes (measured
    # through `pdf_service.fact_to_form_fields`), and all three are separate
    # entries in the ACORD 125 fill-rate inventory.
    #
    # PRIORITY_IMPORTANT is the whole fix: the cards stay client-facing, stay
    # visible and stay `suggested`, and only stop consuming a CRITICAL
    # pre-ticked slot - which was the entire measured cost.
    if (not question.get("suppressed")
            and audience == AUDIENCE_CLIENT
            and question.get("priority") == PRIORITY_CRITICAL
            and _contact_requirement_already_met(facts, canon)):
        out["priority"] = PRIORITY_IMPORTANT
        out["eligibility_reason"] = REASON_CONTACT_SATISFIED
        # The score badge is computed by `classify_question` FROM the priority,
        # so a demotion that leaves it alone keeps advertising "Submission
        # readiness" and 15 points on a question that no longer carries either.
        # `apply_eligibility` only ever recomputes the bucket, and only when the
        # audience moves - so the correction has to happen here.
        _impact = dict(question.get("score_impact") or {})
        if _impact:
            _impact["submission_readiness"] = False
            _impact["points"] = _SCORE_POINTS.get(PRIORITY_IMPORTANT,
                                                  _impact.get("points", 0))
            _impact["labels"] = [lbl for lbl in (_impact.get("labels") or [])
                                 if lbl != "Submission readiness"]
            out["score_impact"] = _impact
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
