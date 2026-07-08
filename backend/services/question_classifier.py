"""
Client-Questionnaire Controls — question taxonomy classifier (Beta Report §8).

Pure, config-driven, NO LLM. Given a remediation question (its `field_name`,
the forms it touches, and a little context) this module assigns:

  * audience        — who the question is for
  * priority        — how important it is
  * topic_group     — which section it belongs to (for grouping in the UI)
  * score_impact    — which scores it materially improves
  * suppressed      — whether it should be kept out of the default client set
  * default_selected/suggested — the curated default-selection policy

Design notes
------------
The questionnaire previously turned *every* empty field on *every* recommended
ACORD form into a client question (~1,790 in Beta Test 2), pre-selected all of
them, and leaked raw form plumbing (producer fax, NAIC, national identifier,
internal coverage codes) straight to the client.

This classifier is the curation layer. It is purely **additive** — it never
drops a question; it only labels it. Anything that isn't a clean,
client-answerable business fact is routed to the `internal` / `producer` /
`do_not_send` audiences so the producer UI can separate it into a collapsible
"Internal / Producer Review" panel that is never auto-sent to the client.

The workhorse rule is rule 7 in `classify_question`: any raw form field that is
NOT a curated, client-answerable fact is classed `internal` + `suppressed`.
That single rule collapses the long tail of obscure PDF fields without needing
an exhaustive pattern list, while the explicit patterns (fax / producer / NAIC /
codes) give the well-known cases precise, human-readable labels.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional

# ── Audience taxonomy (Beta Report §8.2 item 1) ───────────────────────────────
AUDIENCE_CLIENT       = "client"        # client-answerable business facts
AUDIENCE_PRODUCER     = "producer"      # producer/agency-side (broker fills)
AUDIENCE_INTERNAL     = "internal"      # system identifiers / form plumbing
AUDIENCE_CARRIER      = "carrier"       # carrier / underwriter review
AUDIENCE_DO_NOT_SEND  = "do_not_send"   # never appropriate for a client (fax…)

# ── Bucket taxonomy (client clarification 2026-07) ────────────────────────────
# The producer UI groups questions into exactly THREE actionable buckets plus a
# non-selectable "Never send" row. Buckets are DERIVED from the finer-grained
# audience above (kept for routing precision), so nothing that works today
# regresses — the buckets are just a coarse view on top of the existing routing:
#   client      -> Client        (the insured can reasonably answer)
#   producer    -> Agency        (producer / CSR / account manager answers)
#   carrier     -> Underwriting  (carrier's OWN underwriter / uw conditions)
#   internal    -> Underwriting  (cross-form flags, system / internal review)
#   do_not_send -> Never send    (fax etc. — never appropriate to send)
BUCKET_CLIENT       = "client"
BUCKET_AGENCY       = "agency"
BUCKET_UNDERWRITING = "underwriting"
BUCKET_DO_NOT_SEND  = "do_not_send"

_AUDIENCE_TO_BUCKET = {
    AUDIENCE_CLIENT:      BUCKET_CLIENT,
    AUDIENCE_PRODUCER:    BUCKET_AGENCY,
    AUDIENCE_CARRIER:     BUCKET_UNDERWRITING,
    AUDIENCE_INTERNAL:    BUCKET_UNDERWRITING,
    AUDIENCE_DO_NOT_SEND: BUCKET_DO_NOT_SEND,
}

BUCKET_LABELS = {
    BUCKET_CLIENT:       "Client",
    BUCKET_AGENCY:       "Agency",
    BUCKET_UNDERWRITING: "Underwriting / Internal Review",
    BUCKET_DO_NOT_SEND:  "Never send",
}

BUCKET_ORDER = [BUCKET_CLIENT, BUCKET_AGENCY, BUCKET_UNDERWRITING, BUCKET_DO_NOT_SEND]

# ── Priority taxonomy (Beta Report §8.2 item 2) ───────────────────────────────
PRIORITY_CRITICAL   = "critical"
PRIORITY_IMPORTANT  = "important"
PRIORITY_OPTIONAL   = "optional"
PRIORITY_INTERNAL   = "internal"
PRIORITY_SUPPRESSED = "suppressed"

# ── Topic groups (Beta Report §8.2 item 5) ────────────────────────────────────
TOPIC_APPLICANT  = "applicant_information"
TOPIC_OPERATIONS = "operations"
TOPIC_LOCATIONS  = "locations"
TOPIC_PROPERTY   = "property"
TOPIC_GL         = "general_liability"
TOPIC_AUTO       = "auto"
TOPIC_WC         = "workers_compensation"
TOPIC_UMBRELLA   = "umbrella"
TOPIC_LOSS       = "loss_history"
TOPIC_PRODUCER   = "producer_review"
TOPIC_OTHER      = "other"

TOPIC_LABELS = {
    TOPIC_APPLICANT:  "Applicant Information",
    TOPIC_OPERATIONS: "Operations",
    TOPIC_LOCATIONS:  "Locations",
    TOPIC_PROPERTY:   "Property",
    TOPIC_GL:         "General Liability",
    TOPIC_AUTO:       "Auto",
    TOPIC_WC:         "Workers Compensation",
    TOPIC_UMBRELLA:   "Umbrella",
    TOPIC_LOSS:       "Loss History",
    TOPIC_PRODUCER:   "Producer Review",
    TOPIC_OTHER:      "Other",
}

# Display order so grouped UIs render sections predictably.
TOPIC_ORDER = [
    TOPIC_APPLICANT, TOPIC_OPERATIONS, TOPIC_LOCATIONS, TOPIC_PROPERTY,
    TOPIC_GL, TOPIC_AUTO, TOPIC_WC, TOPIC_UMBRELLA, TOPIC_LOSS,
    TOPIC_PRODUCER, TOPIC_OTHER,
]

# Soft cap on how many questions are PRE-SELECTED by default (Beta Report §11
# #20 — "what is the maximum reasonable number of default client questions").
# Critical client-answerable questions are selected up to this cap; the producer
# can always add more manually.
DEFAULT_SELECT_CAP = 28

# ── Critical / important field sets — sourced from the SQS tiers so the
# questionnaire's notion of "important" never drifts from the scorer's. ────────
try:  # pragma: no cover - exercised at import in the running app
    from services.sqs_service import TIER1_FIELDS, TIER1_CONTACT, TIER2_FIELDS
    _TIER1 = set(TIER1_FIELDS.keys())
    _TIER1_CONTACT = set(TIER1_CONTACT)
    _TIER2 = set(TIER2_FIELDS.keys())
except Exception:  # pragma: no cover - safety fallback if import graph changes
    _TIER1 = {"producer_name", "applicant_name", "mailing_address",
              "effective_date", "lines_of_business"}
    _TIER1_CONTACT = {"contact_name", "contact_phone", "contact_email"}
    _TIER2 = {"fein", "entity_type", "operations_description", "total_revenue",
              "prior_carrier", "num_employees", "years_in_business",
              "naics_code", "num_claims", "total_payroll"}

# Critical = SQS tier-1 essentials a client can answer. `producer_name` is a
# tier-1 SCORING field but it is the agency's own name — a producer-side item,
# not a client question — so it is deliberately excluded here and re-routed to
# the producer audience by the producer-pattern rule below.
CRITICAL_FIELDS = (_TIER1 | _TIER1_CONTACT) - {"producer_name"}

# Important = SQS tier-2 fields + the core coverage limits/exposures that move
# the per-line and package scores even though they aren't structural tier-1.
IMPORTANT_FIELDS = _TIER2 | {
    "gl_limits", "gl_each_occurrence", "gl_aggregate", "gl_deductible",
    "umbrella_limit", "umbrella_sir", "auto_liability_limit",
    "wc_payroll", "wc_class_codes", "wc_xmod",
    "property_building_value", "property_bpp_value", "locations",
    "construction_type", "occupancy_type", "loss_history_years",
    "loss_history_no_prior_losses_indicator",
    "employers_liability_limits", "period_of_restoration",
    "carrier_marketing_reason", "submission_urgency",
}

# Raw-form / system fields that should NEVER default to the client. Matched as
# case-insensitive substrings against the field name (works on both canonical
# snake_case keys and raw ACORD CamelCase schema field names).
_DO_NOT_SEND_PATTERNS = ("fax",)

_PRODUCER_PATTERNS = (
    "producer",          # Producer_FullName, producer_name, producer_phone…
    "subproducer", "sub_producer",
    "agency",            # agency_customer_id, AgencyCustomerIdentifier
    "agent_",
    # National identifier fields — client requirement "National identifier fields
    # unless contextually necessary": never a default client question, but routed
    # to the PRODUCER (who supplies them when the form context requires) instead of
    # being hidden as internal. naics_code / sic_code remain client questions via
    # _CLIENT_WHITELIST (they are industry classifications a business can provide).
    "naic",
    "nationalproducer", "national_producer", "nationalproducernumber",
    "national_identifier", "nationalid",
)

# Carrier / underwriter-review fields (client audience "Carrier/underwriter
# review"). These identify the CARRIER's own underwriter or carry cancellation /
# non-renewal underwriting conditions — never a client question and not generic
# plumbing. Matched on precise tokens so contractor operations sections such as
# `ContractorsUnderwriting_ResidentialWorkPercent` (genuinely client-answerable)
# are NOT swept in.
_CARRIER_PATTERNS = (
    "insurer_underwriter",          # Insurer_Underwriter_FullName / _OfficeIdentifier
    "cancelnonrenew_underwriting",  # cancellation / non-renewal underwriting conditions
    "underwritingcondition", "underwriting_condition",
    "underwritingindicator",
)

# System identifiers / internal codes / form metadata. These are the report's
# named offenders (internal coverage codes, policy coverage code, system
# identifiers) plus generic plumbing. National identifiers moved to the producer
# audience above (contextually necessary → producer-side, not hidden).
_INTERNAL_PATTERNS = (
    "customeridentifier", "customer_identifier", "customerid",
    "coveragecode", "coverage_code", "policycoverage", "coverageidentifier",
    "categorycode", "category_code",
    "form_number", "formnumber", "formidentifier", "form_identifier",
    "revisionnumber", "revision_number", "revisiondate",
    "sequence", "transactiontype", "transaction_type", "transactionstatus",
    "remark_code", "remarkcode",
    "_indicator_code", "lobcode", "lob_code", "linecode", "line_code",
    "recordtype", "record_type",
    # System identifiers / internal codes (client examples: "System identifiers",
    # "Internal coverage codes"). Precise tokens that never appear in a
    # client-answerable business field.
    "control_number", "controlnumber", "barcode", "checksum",
    "systemidentifier", "system_identifier",
    "uniqueidentifier", "globalidentifier",
    "internalcode", "internal_code", "processingid", "processing_id",
)

# Carrier INFORMATION the AGENCY supplies (client clarification: "Carrier
# information, Policy numbers, Prior carrier information, ACORD form edition,
# Submission goal, Market selection, Coverage intent" are AGENCY questions — the
# producer / CSR / account manager answers them, never a default client question).
# This is DISTINCT from _CARRIER_PATTERNS below (the carrier's OWN underwriter /
# underwriting conditions, which stay Underwriting review). Matched AFTER the
# carrier patterns so `insurer_underwriter*` still routes to carrier review, and
# BEFORE the critical/important/curated client branches so these never fall
# through to the client. "Coverage intent" here means producer STRATEGY (which
# markets, submission goal, why marketing) — the insured's desired coverage LIMITS
# (gl_limits, umbrella_limit, property values) are deliberately NOT in this list;
# they stay Client and keep driving SQS.
_AGENCY_PATTERNS = (
    "prior_carrier", "priorcarrier",
    "prior_policy", "priorpolicy",
    "policy_number", "policynumber", "policy_no",
    "insurer",                       # insurer name / policy / phone / address
    "carrier_marketing", "carriermarketing",
    "submission_urgency", "submission_goal",
    "market_selection", "coverage_intent",
    "acord_edition", "form_edition", "formedition", "edition_",
    # Umbrella underlying-schedule / follow-form evidence — the producer supplies
    # these (they know what is in the submission). Kept out of the default client
    # set per the client's "underlying umbrella support" -> internal/agency note.
    "schedule_of_underlying", "underlying_insurance",
    "follow_form", "followform",
)

# Canonical fields that ARE client-answerable but happen to contain a word that
# could trip a pattern — protect them explicitly. (policy_number / prior policy
# numbers were removed here: the client re-classified all policy numbers as an
# AGENCY question, so they must NOT be whitelisted back to the client.)
_CLIENT_WHITELIST = {
    "naics_code", "sic_code",
    "gl_class_codes", "gl_class_codes_by_location", "wc_class_codes",
    # contact_name / contact_email are client-critical facts even when the raw
    # ACORD field that surfaces them is in the Producer section of the form
    # (Producer_ContactPerson_FullName / Producer_ContactPerson_Email). Without
    # this the producer pattern fires on the raw field name and routes the
    # question to the producer panel instead of the client questionnaire.
    "contact_name", "contact_email",
}

# ── Narrative-supported answers (§6.3 item 2) — all 12 components evaluated ────
# Every §6.3 narrative-quality component (see sqs_service.NARRATIVE_COMPONENT_
# LABELS) is evaluated against the client questionnaire and assigned ONE of three
# policies, so the client's broad goal ("if the narrative answers it, don't make
# the client redo it") is honoured across the whole taxonomy rather than a slice:
#
# Bucket A — SUPPRESS: the free-text narrative IS the answer. The matching
#   question is dropped from the default client set (labelled "stated in
#   narrative"); the producer can still send it from the review panel.
#     • operations        → operations_description : prose IS the answer.
#     • years_in_business → years_in_business       : "founded in 2008" answers it.
#     • carrier_market    → prior_carrier           : a narrative naming the
#         prior/incumbent carrier substitutes for asking who it was.
#
# Bucket B — CONTEXT (KEEP + LABEL + DE-PRIORITISE): the narrative discusses the
#   topic but the FORM still needs the exact figure. The question is NOT
#   suppressed; it is labelled "stated in narrative" and de-prioritised so it is
#   not pre-selected (the client just confirms the precise number). This honours
#   the intent without ever withholding a question only the client can answer.
#     • loss_history        → claim counts / loss-history attestation
#     • coverage_discussion → limits (GL / umbrella / auto / EL)
#     • location_exposure   → locations / addresses
#     • employee_practices  → headcount / payroll
#
# Bucket C — no curated client question exists for these topics.
#   (account_overview, management, risk_controls, growth_trends, target_markets).
#   arq_service._maybe_inject_narrative_enrichment_questions() asks the client
#   when the narrative is missing them and stays silent when it covers them.

# Bucket A — narrative fully answers these: suppress the ARQ question entirely.
NARRATIVE_SUPPRESS_QUESTION_KEYS = {
    "operations":        ("operations_description",),
    "years_in_business": ("years_in_business",),
    "carrier_market":    ("prior_carrier",),
}

# Bucket B — narrative covers these topics: suppress the ARQ question entirely.
# Previously these were kept with a "stated in narrative - confirm value" label,
# but if the narrative already answers the question there is no reason to ask
# the client again. Unified with Bucket A: covered = suppressed, missing = asked.
NARRATIVE_CONTEXT_QUESTION_KEYS = {
    "loss_history": (
        "num_claims", "loss_history_no_prior_losses_indicator", "loss_history_years",
    ),
    "coverage_discussion": (
        "gl_limits", "gl_each_occurrence", "gl_aggregate", "gl_deductible",
        "umbrella_limit", "umbrella_sir", "auto_liability_limit",
        "employers_liability_limits",
    ),
    "location_exposure":  ("locations",),
    "employee_practices": ("num_employees", "total_payroll", "wc_payroll"),
}
# Back-compat alias (was the Bucket-A-only map before §6.3 was widened).
NARRATIVE_COMPONENT_QUESTION_KEYS = NARRATIVE_SUPPRESS_QUESTION_KEYS
# ── Topic detection — ordered (first match wins) substring rules ──────────────
_TOPIC_FIELD_RULES: List[tuple] = [
    (TOPIC_PRODUCER,  ("producer", "subproducer", "agency", "agent_")),
    (TOPIC_WC,        ("wc_", "workers_comp", "workerscomp", "_xmod", "officer_exclusion")),
    (TOPIC_AUTO,      ("auto_", "vehicle", "driver", "garage", "_vin", "motorist")),
    (TOPIC_UMBRELLA,  ("umbrella", "excess")),
    (TOPIC_GL,        ("gl_", "general_liability", "generalliability", "additional_insured",
                       "additional_interest", "retro_date", "claims_made", "prior_acts")),
    (TOPIC_LOSS,      ("claim", "loss", "prior_carrier", "previouscarrier", "priorcoverage",
                       "previouspolicy", "num_claims", "carrier_marketing")),
    (TOPIC_PROPERTY,  ("property", "building", "bpp", "construction", "occupancy", "roof",
                       "sprinkler", "fire_protection", "valuation", "coinsurance",
                       "business_income", "period_of_restoration", "mortgagee", "cope",
                       "scheduled_item", "inland_marine")),
    (TOPIC_LOCATIONS, ("location", "physical_address", "premises")),
    (TOPIC_OPERATIONS,("operations", "class_codes", "subcontract", "contractor",
                       "residential_commercial", "high_hazard", "licensing")),
    (TOPIC_APPLICANT, ("applicant", "named_insured", "namedinsured", "dba", "mailing_address",
                       "contact_", "fein", "tax", "entity", "years_in_business",
                       "naics", "sic", "num_employees", "annual_revenue", "total_revenue",
                       "total_payroll", "businessinformation", "businessstart")),
]

# Fallback topic by form id when the field name alone is ambiguous.
_FORM_TOPIC = {
    "ACORD_125": TOPIC_APPLICANT,
    "ACORD_126": TOPIC_GL,
    "ACORD_127": TOPIC_AUTO,
    "ACORD_130": TOPIC_WC,
    "ACORD_131": TOPIC_UMBRELLA,
    "ACORD_140": TOPIC_PROPERTY,
    "ACORD_141": TOPIC_PROPERTY,
    "ACORD_133": TOPIC_PROPERTY,
    "ACORD_160": TOPIC_PROPERTY,
    "ACORD_137_CA": TOPIC_AUTO,
    "ACORD_137_CO": TOPIC_AUTO,
    "ACORD_138_CA": TOPIC_AUTO,
    "ACORD_138_CO": TOPIC_AUTO,
    "ACORD_186": TOPIC_OPERATIONS,
    "ACORD_101": TOPIC_OPERATIONS,
    "ACORD_25":  TOPIC_APPLICANT,
    "ACORD_28":  TOPIC_PROPERTY,
}

_SCORE_POINTS = {
    PRIORITY_CRITICAL:  15,
    PRIORITY_IMPORTANT: 8,
    PRIORITY_OPTIONAL:  3,
    PRIORITY_INTERNAL:  0,
    PRIORITY_SUPPRESSED: 0,
}

# Words that, when present in an active hard-stop message, indicate which fact
# would resolve it. Used to flag "Resolves hard stop" on the right question.
_HARDSTOP_KEYWORDS = {
    "retro_date":               ("retro",),
    "operations_description":   ("operations", "class code"),
    "gl_class_codes":           ("class code",),
    "total_revenue":            ("revenue",),
    "total_payroll":            ("payroll",),
    "wc_payroll":               ("workers comp", "wc payroll"),
    "locations":                ("location", "cope"),
    "occupancy_type":           ("cope", "occupancy"),
    "construction_type":        ("cope", "construction"),
    "property_building_value":  ("cope", "building"),
    "umbrella_sir":             ("umbrella", "sir"),
    "employers_liability_limits": ("employers liability",),
}


def _base_key(field_name: str) -> str:
    """Strip a trailing one-letter or numeric instance suffix (e.g. location_2)."""
    base = re.sub(r"[_\s]+[a-zA-Z]$", "", field_name or "")
    base = re.sub(r"[_\s]+\d+$", "", base)
    return base


def _matches_any(haystack: str, needles: Iterable[str]) -> bool:
    return any(n in haystack for n in needles)


def derive_topic(field_name: str, form_ids: Optional[Iterable[str]] = None) -> str:
    fn = (field_name or "").lower()
    for topic, needles in _TOPIC_FIELD_RULES:
        if _matches_any(fn, needles):
            return topic
    for fid in (form_ids or []):
        t = _FORM_TOPIC.get(fid)
        if t:
            return t
    return TOPIC_OTHER


def _hard_stop_resolves(field_name: str, base: str, hard_stop_text: str) -> bool:
    if not hard_stop_text:
        return False
    text = hard_stop_text.lower()
    # Direct: the field's readable name appears in a hard-stop message.
    readable = base.replace("_", " ")
    if len(readable) >= 4 and readable in text:
        return True
    for key in (field_name, base):
        for kw in _HARDSTOP_KEYWORDS.get(key, ()):  # type: ignore[arg-type]
            if kw in text:
                return True
    return False


def classify_question(
    field_name: str,
    form_ids: Optional[Iterable[str]] = None,
    *,
    is_cross_form: bool = False,
    severity: Optional[str] = None,
    is_curated_client: bool = False,
    canonical_key: Optional[str] = None,
    hard_stop_text: str = "",
) -> dict:
    """Return the taxonomy for a single question (audience/priority/topic/impact).

    `is_curated_client` should be True when the field resolves to a known
    plain-language client question (i.e. it is in the curated question/prefix
    maps or is a canonical fact key). Raw, uncurated form fields default to the
    `internal` audience so they never reach the client by default.

    `canonical_key` is the field's resolved canonical fact key (when known). It
    is what audience/priority/topic are judged on, so a client fact arriving
    under its raw ACORD field name is still scored as the fact it represents.
    """
    fn = (field_name or "").lower()
    base = _base_key(field_name or "")
    base_l = base.lower()
    # Identity is judged on the canonical fact key first: the producer forms key
    # every field by its raw ACORD name, so a client fact such as `gl_aggregate`
    # arrives as `CommercialGeneralLiability_GeneralAggregateLimit_Amount` and
    # would otherwise never match the canonical CRITICAL/IMPORTANT/whitelist sets.
    # Falls back to the raw field name and its instance-stripped base.
    identity_keys = {field_name, base}
    if canonical_key:
        identity_keys.add(canonical_key)
    whitelisted = bool(identity_keys & _CLIENT_WHITELIST)

    topic = derive_topic(canonical_key or field_name, form_ids)

    # ── Audience + priority decision tree (first match wins) ──────────────────
    if not whitelisted and _matches_any(fn, _DO_NOT_SEND_PATTERNS):
        audience, priority = AUDIENCE_DO_NOT_SEND, PRIORITY_SUPPRESSED
        topic = TOPIC_PRODUCER if "producer" in fn else topic
    elif not whitelisted and _matches_any(fn, _PRODUCER_PATTERNS):
        audience, priority = AUDIENCE_PRODUCER, PRIORITY_INTERNAL
        topic = TOPIC_PRODUCER
    elif not whitelisted and _matches_any(fn, _INTERNAL_PATTERNS):
        audience, priority = AUDIENCE_INTERNAL, PRIORITY_SUPPRESSED
    elif not whitelisted and _matches_any(fn, _CARRIER_PATTERNS):
        # Carrier / underwriter-review audience — visible in the producer review
        # panel, never auto-sent to the client.
        audience, priority = AUDIENCE_CARRIER, PRIORITY_INTERNAL
        topic = TOPIC_PRODUCER
    elif not whitelisted and _matches_any(fn, _AGENCY_PATTERNS):
        # Agency bucket: producer / CSR / account manager answers these (carrier
        # info, policy numbers, prior carrier, submission strategy, ACORD edition,
        # umbrella underlying evidence). Never a default client question, but the
        # producer can manually add them to the send list.
        audience, priority = AUDIENCE_PRODUCER, PRIORITY_INTERNAL
    elif is_cross_form:
        # Client clarification (2026-07): cross-form conflicts are Underwriting /
        # Internal Review flags by DEFAULT — never auto-sent to the client. We keep
        # generating the resolution question (priority still reflects severity) so
        # the producer can one-click escalate the ones whose fix is a clean
        # client-answerable fact (see `escalatable_to_client` below).
        audience = AUDIENCE_INTERNAL
        priority = PRIORITY_CRITICAL if severity == "hard_stop" else PRIORITY_IMPORTANT
    elif identity_keys & CRITICAL_FIELDS:
        audience, priority = AUDIENCE_CLIENT, PRIORITY_CRITICAL
    elif identity_keys & IMPORTANT_FIELDS:
        audience, priority = AUDIENCE_CLIENT, PRIORITY_IMPORTANT
    elif is_curated_client:
        audience, priority = AUDIENCE_CLIENT, PRIORITY_OPTIONAL
    else:
        # Rule 7 — the workhorse. An uncurated raw form field is internal.
        audience, priority = AUDIENCE_INTERNAL, PRIORITY_SUPPRESSED

    suppressed = priority in (PRIORITY_SUPPRESSED, PRIORITY_INTERNAL) or audience in (
        AUDIENCE_INTERNAL, AUDIENCE_PRODUCER, AUDIENCE_DO_NOT_SEND,
    )
    suppressed_reason = ""
    if suppressed:
        suppressed_reason = {
            AUDIENCE_DO_NOT_SEND: "not_suitable_for_client",
            AUDIENCE_PRODUCER:    "producer_side_item",
            AUDIENCE_INTERNAL:    "system_or_internal_field",
            AUDIENCE_CARRIER:     "carrier_underwriter_review",
        }.get(audience, "internal")

    # ── Score impact (Beta Report §8.2 item 6) ────────────────────────────────
    is_client_scoring = audience == AUDIENCE_CLIENT and priority in (
        PRIORITY_CRITICAL, PRIORITY_IMPORTANT,
    )
    hard_stop_resolution = bool(
        (is_cross_form and severity == "hard_stop")
        or _hard_stop_resolves(field_name, base_l, hard_stop_text)
    )
    score_impact = {
        "sqs":                  is_client_scoring,
        "form_completion":      audience == AUDIENCE_CLIENT,
        "submission_readiness": priority == PRIORITY_CRITICAL,
        "hard_stop_resolution": hard_stop_resolution,
        "points":               _SCORE_POINTS.get(priority, 0),
    }
    labels = []
    if score_impact["hard_stop_resolution"]:
        labels.append("Resolves hard stop")
    if score_impact["sqs"]:
        labels.append("SQS")
    if score_impact["submission_readiness"]:
        labels.append("Submission readiness")
    if score_impact["form_completion"] and not is_client_scoring:
        labels.append("Form completion")
    score_impact["labels"] = labels

    # ── Coarse bucket for the 3-bucket producer UI (client clarification) ─────
    bucket = _AUDIENCE_TO_BUCKET.get(audience, BUCKET_UNDERWRITING)

    # A cross-form conflict is escalatable to the client only when its fix is a
    # clean client-answerable fact (payroll, EL limits, locations, operations,
    # retro date, SIR, period of restoration, lines of business …). Judgment-only
    # conflicts (ACV/RCV, conflicting insureds/addresses) have no client-answerable
    # field and are never escalatable — they stay pure internal flags.
    escalatable_to_client = bool(
        is_cross_form
        and not _matches_any(fn, _DO_NOT_SEND_PATTERNS)
        and not _matches_any(fn, _PRODUCER_PATTERNS)
        and not _matches_any(fn, _AGENCY_PATTERNS)
        and not _matches_any(fn, _CARRIER_PATTERNS)
        and (
            bool(identity_keys & (CRITICAL_FIELDS | IMPORTANT_FIELDS))
            or is_curated_client
            or whitelisted
        )
    )

    return {
        "audience":              audience,
        "priority":              priority,
        "bucket":                bucket,
        "bucket_label":          BUCKET_LABELS.get(bucket, "Underwriting / Internal Review"),
        "escalatable_to_client": escalatable_to_client,
        "topic_group":           topic,
        "topic_label":           TOPIC_LABELS.get(topic, "Other"),
        "score_impact":          score_impact,
        "suppressed":            suppressed,
        "suppressed_reason":     suppressed_reason,
    }


def decorate_questions(
    questions: List[dict],
    *,
    present_fact_keys: Optional[set] = None,
    narrative_components: Optional[dict] = None,
    hard_stop_text: str = "",
) -> None:
    """Attach taxonomy fields to every question in-place.

    `present_fact_keys` is the set of canonical fact keys already filled in the
    package (so a question whose fact is already answered in the uploaded
    documents is suppressed — Beta Report §8.2 item 4). Each question may carry
    `_is_curated_client`, `_canonical_key`, `_is_cross_form`, `severity` hints
    set by the generator.

    `narrative_components` is the §6.3 per-component present/absent map for the
    uploaded narrative. When a component is present, the curated question it
    answers (per `NARRATIVE_COMPONENT_QUESTION_KEYS`) is suppressed from the
    default client set and labelled "stated in narrative" instead of being
    re-asked (§6.3 item 2).
    """
    present = present_fact_keys or set()

    # Canonical keys the narrative covers (§6.3 item 2), split by policy bucket.
    narrative_suppress: set = set()  # Bucket A — drop from default client set
    narrative_context:  set = set()  # Bucket B — keep, label, de-prioritise
    for comp, is_present in (narrative_components or {}).items():
        if not is_present:
            continue
        narrative_suppress.update(NARRATIVE_SUPPRESS_QUESTION_KEYS.get(comp, ()))
        narrative_context.update(NARRATIVE_CONTEXT_QUESTION_KEYS.get(comp, ()))

    for q in questions:
        tax = classify_question(
            q.get("field_name", ""),
            q.get("form_ids") or [],
            is_cross_form=bool(q.get("_is_cross_form") or q.get("source") == "cross_form_conflict"),
            severity=q.get("severity"),
            is_curated_client=bool(q.get("_is_curated_client")),
            canonical_key=q.get("_canonical_key"),
            hard_stop_text=hard_stop_text,
        )
        q.update(tax)

        # Overlay: already answered in the uploaded documents / facts.
        canon = q.get("_canonical_key")
        if canon and canon in present and not q.get("suppressed"):
            q["suppressed"] = True
            q["suppressed_reason"] = "already_provided"
            q["priority"] = PRIORITY_SUPPRESSED
        # Overlay (Bucket A): the narrative fully answers it → suppress from the
        # default client set. Gated on `not suppressed` and placed after the facts
        # overlay, so an explicit extracted fact ("already provided") takes
        # precedence.
        if canon and canon in narrative_suppress and not q.get("suppressed"):
            q["suppressed"] = True
            q["suppressed_reason"] = "stated_in_narrative"
            q["priority"] = PRIORITY_SUPPRESSED
        # Bucket B — deliberately removed.
        # "coverage_discussion detected → suppress all GL/umbrella/auto fields"
        # caused over-suppression: a single mention of "coverage" in the narrative
        # was suppressing gl_aggregate, gl_deductible, umbrella_limit etc. even
        # though the narrative never stated those specific values. The correct
        # suppressor for field-level values is "already_provided" above: if the
        # LLM extracted the value from the narrative doc, the field is suppressed;
        # if it didn't, the client still needs to answer it. NARRATIVE_CONTEXT_QUESTION_KEYS
        # is retained so the topic→field mapping remains available for future use,
        # but no overlay is applied here.


def apply_default_selection(questions: List[dict], cap: int = DEFAULT_SELECT_CAP) -> dict:
    """Set `default_selected` / `suggested` per the curated-default policy.

    Policy (Beta Report §8.2 item 3):
      * Critical client-answerable questions  -> selected (up to `cap`)
      * Important client-answerable questions -> suggested (not pre-selected)
      * Producer / internal / suppressed      -> neither (separated, not sent)

    Returns a summary count dict for the UI header.
    """
    selected = 0
    counts = {
        "total": len(questions),
        "client": 0, "producer": 0, "internal": 0, "do_not_send": 0, "carrier": 0,
        # Coarse 3-bucket counts for the client's ARQ metric (Client / Agency /
        # Underwriting counts). `bucket_do_not_send` is the "Never send" row.
        "bucket_client": 0, "bucket_agency": 0,
        "bucket_underwriting": 0, "bucket_do_not_send": 0,
        "critical": 0, "important": 0, "optional": 0,
        "default_selected": 0, "suggested": 0, "suppressed": 0,
    }

    for q in questions:
        audience  = q.get("audience", AUDIENCE_CLIENT)
        priority  = q.get("priority", PRIORITY_OPTIONAL)
        suppressed = bool(q.get("suppressed"))

        counts[audience] = counts.get(audience, 0) + 1
        bucket = q.get("bucket") or _AUDIENCE_TO_BUCKET.get(audience, BUCKET_UNDERWRITING)
        counts[f"bucket_{bucket}"] = counts.get(f"bucket_{bucket}", 0) + 1
        if priority in ("critical", "important", "optional"):
            counts[priority] += 1
        if suppressed:
            counts["suppressed"] += 1

        is_client = audience == AUDIENCE_CLIENT and not suppressed
        if is_client and priority == PRIORITY_CRITICAL and selected < cap:
            q["default_selected"] = True
            q["suggested"] = False
            selected += 1
            counts["default_selected"] += 1
        elif is_client and priority == PRIORITY_IMPORTANT:
            q["default_selected"] = False
            q["suggested"] = True
            counts["suggested"] += 1
        else:
            q["default_selected"] = False
            q["suggested"] = False

    counts["cap"] = cap
    return counts
