"""issue_registry.py

Presentation-layer clustering and tiering for hard stops / warnings
(Figures 4 & 5: issue clustering, dedup, "fix this first", and the
Required-before-submission / Recommended-before-quoting / Binder-placement
follow-up hierarchy).

This module is purely ADDITIVE and read-only with respect to scoring: it
never changes hard_stops / soft_stops content, order, or length, and it is
never consulted by SQS capping or dismiss-credit logic. Those keep reading
the plain string lists exactly as before. This module only decides how an
already-final set of issues should be grouped for display.

Every issue arrives already carrying a `code` (either one of the ~45 codes
emitted by cross_form_validator.py, or one of the small set of codes
generated inline in extraction_pipeline.py / form_routes.py for the other
warning sources: doc-consistency conflicts, source conflicts, underwriting
reconciliation, low-OCR-confidence fields, and Tier-1 missing fields).

Hard stops are always tier "required" (a hard stop blocks submission now by
definition - confirmed with the client, no other tier applies to them).
Warnings/advisories are tiered required / recommended / binder_followup.
"""

import hashlib
from typing import Any, Dict, List, Optional

DEFAULT_CLUSTER = "Other validations"
DEFAULT_TIER = "recommended"


def issue_id_for(message: str, forms: Optional[List[str]] = None) -> str:
    """Deterministic, durable ID for one issue.

    Keyed off the (normalized) message text plus the sorted set of forms it
    affects - NOT off the emit-time `code`, because several code sources are
    list-index based (e.g. ``legacy_hard_0``) and would produce a different ID
    if list order shifts between runs. The same problem on the same submission
    therefore always resolves to the same barcode, even after a re-run, which
    is what lets a stored resolution status re-attach to it. Purely additive:
    this ID is never consulted by scoring or capping.
    """
    base = (message or "").strip() + "|" + ",".join(sorted(forms or []))
    return "iss_" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]

TIER_LABELS = {
    "required": "Required before submission",
    "recommended": "Recommended before quoting",
    "binder_followup": "Binder / placement follow-up",
}

# code -> cluster label. Severity-agnostic: a code that can dynamically be
# either hard_stop or soft_warning (e.g. the umbrella period-alignment rules,
# which downgrade to soft when an ACORD 101 explanation is present) only
# needs one entry here - the cluster is the same regardless of severity.
CLUSTER_MAP: Dict[str, str] = {
    # Property COPE
    "minimum_viable_cope_missing": "Property COPE completeness",
    "carrier_grade_cope_incomplete": "Property COPE quality",
    # Property deductibles
    "peril_deductible_referenced_but_undefined": "Property deductible completeness",
    "property_aop_deductible_missing": "Property deductible completeness",
    "property_peril_deductible_incomplete": "Property deductible completeness",
    # Property valuation
    "property_valuation_method_missing": "Property valuation method",
    "acv_high_value_building": "Property valuation advisories",
    "rcv_old_building": "Property valuation advisories",
    # Property coinsurance
    "property_coinsurance_missing": "Property coinsurance",
    "property_coinsurance_unreasonable": "Property coinsurance",
    # Business Income
    "bi_missing_period_of_restoration": "Business Income coverage",
    "bi_coverage_no_limit": "Business Income coverage",
    # Location / address
    "location_count_mismatch": "Location & address data",
    "location_count_mismatch_minor": "Location & address data",
    "location_address_mismatch": "Location & address data",
    "physical_vs_mailing_address_unclear": "Location & address data",
    # Builders Risk
    "builders_risk_project_value_missing": "Builders Risk project value",
    "builders_risk_property_duplication": "Property / Builders Risk duplication",
    "inland_marine_property_overlap": "Property / Builders Risk duplication",
    # WC payroll
    "wc_payroll_mismatch": "WC payroll reconciliation",
    "wc_payroll_vs_revenue": "WC payroll reconciliation",
    "wc_subcontracting_payroll_conflict": "WC payroll reconciliation",
    "wc_multi_state_no_breakdown": "WC payroll reconciliation",
    "wc_state_payroll_total_mismatch": "WC payroll reconciliation",
    # WC/GL class codes
    "wc_gl_class_code_mismatch": "WC / GL class code alignment",
    "gl_codes_no_operations": "WC / GL class code alignment",
    # Contractor / subcontracting
    "contractor_missing_acord186": "Contractor exposure (ACORD 186)",
    "acord186_high_sub_high_wc_payroll": "Contractor exposure (ACORD 186)",
    "high_subcontracting_no_wc_payroll": "Subcontracting vs. WC payroll",
    # Umbrella
    "umbrella_no_underlying_coverage": "Umbrella underlying coverage",
    "umbrella_sir_below_gl_deductible": "Umbrella underlying coverage",
    "umbrella_gl_period_misaligned": "Umbrella policy period alignment",
    "umbrella_gl_expiration_misaligned": "Umbrella policy period alignment",
    "umbrella_auto_period_misaligned": "Umbrella policy period alignment",
    "umbrella_auto_expiration_misaligned": "Umbrella policy period alignment",
    "umbrella_wc_period_misaligned": "Umbrella policy period alignment",
    "umbrella_gl_attachment_failure": "Umbrella attachment limits",
    "umbrella_gl_limits_not_found": "Umbrella attachment limits",
    "umbrella_auto_attachment_failure": "Umbrella attachment limits",
    "umbrella_auto_limits_not_found": "Umbrella attachment limits",
    "umbrella_sir_below_auto_deductible": "Umbrella attachment limits",
    "umbrella_missing_employers_liability": "Umbrella Employers Liability",
    "umbrella_el_below_minimum": "Umbrella Employers Liability",
    # Claims-made
    "claims_made_missing_retro_date": "Claims-made continuity",
    "claims_made_missing_prior_acts": "Claims-made continuity",
    # Auto
    "auto_split_limits_incomplete": "Auto liability structure",
    "auto_hired_nonowned_symbols_missing": "Auto symbols / coverage alignment",
    "auto_physical_damage_symbols_missing": "Auto symbols / coverage alignment",
    "auto_doc_symbol_missing": "Auto symbols / coverage alignment",
    "auto_agreed_value_requires_schedule": "Auto symbols / coverage alignment",
    "auto_um_uim_not_specified": "Auto optional coverage gaps",
    "auto_pip_medpay_not_specified": "Auto optional coverage gaps",
    "auto_drive_other_car_not_specified": "Auto optional coverage gaps",
    # Silent exposure
    "crime_silent_exposure": "Silent exposure gaps",
    "cyber_silent_exposure": "Silent exposure gaps",
    # Certificates / evidence
    "certificate_requested_but_acord25_missing": "Certificate / evidence requests",
    "property_evidence_requested_but_acord28_missing": "Certificate / evidence requests",
    # Baseline / identity
    "acord125_missing": "Missing baseline form",
    "legal_name_equals_dba": "Identity data quality",
    # Narrative
    "acord101_required": "Narrative requirement (ACORD 101)",
}

# code -> tier, consulted ONLY when the issue's effective severity is not
# hard_stop (hard stops are always tier "required" regardless of this map).
TIER_MAP: Dict[str, str] = {
    "acord125_missing": "required",
    "location_count_mismatch_minor": "required",
    "location_address_mismatch": "required",
    "physical_vs_mailing_address_unclear": "required",
    "builders_risk_project_value_missing": "required",
    "umbrella_gl_period_misaligned": "required",
    "umbrella_gl_expiration_misaligned": "required",
    "umbrella_auto_period_misaligned": "required",
    "umbrella_auto_expiration_misaligned": "required",
    "umbrella_wc_period_misaligned": "required",

    "wc_gl_class_code_mismatch": "recommended",
    "gl_codes_no_operations": "recommended",
    "wc_payroll_vs_revenue": "recommended",
    "wc_subcontracting_payroll_conflict": "recommended",
    "contractor_missing_acord186": "recommended",
    "acord186_high_sub_high_wc_payroll": "recommended",
    "umbrella_gl_attachment_failure": "recommended",
    "umbrella_gl_limits_not_found": "recommended",
    "umbrella_auto_attachment_failure": "recommended",
    "umbrella_auto_limits_not_found": "recommended",
    "umbrella_sir_below_auto_deductible": "recommended",
    "claims_made_missing_retro_date": "recommended",
    "claims_made_missing_prior_acts": "recommended",
    "property_aop_deductible_missing": "recommended",
    "property_peril_deductible_incomplete": "recommended",
    "property_coinsurance_missing": "recommended",
    "property_coinsurance_unreasonable": "recommended",
    "bi_coverage_no_limit": "recommended",
    "property_valuation_method_missing": "recommended",
    "auto_hired_nonowned_symbols_missing": "recommended",
    "auto_physical_damage_symbols_missing": "recommended",
    "auto_doc_symbol_missing": "recommended",
    "auto_agreed_value_requires_schedule": "recommended",
    "crime_silent_exposure": "recommended",
    "cyber_silent_exposure": "recommended",
    "certificate_requested_but_acord25_missing": "recommended",
    "property_evidence_requested_but_acord28_missing": "recommended",
    "acord101_required": "recommended",

    "builders_risk_property_duplication": "binder_followup",
    "inland_marine_property_overlap": "binder_followup",
    "carrier_grade_cope_incomplete": "binder_followup",
    "umbrella_missing_employers_liability": "binder_followup",
    "umbrella_el_below_minimum": "binder_followup",
    "auto_um_uim_not_specified": "binder_followup",
    "auto_pip_medpay_not_specified": "binder_followup",
    "auto_drive_other_car_not_specified": "binder_followup",
    "acv_high_value_building": "binder_followup",
    "rcv_old_building": "binder_followup",
    "legal_name_equals_dba": "binder_followup",
}

# Prefix rules for the dynamically-generated codes (one per fact/field, so
# they can't be listed individually above). Checked in order; first match
# wins. These cover the warning sources that sit outside cross_form_validator
# (doc-consistency conflicts, source conflicts, underwriting reconciliation,
# low-OCR-confidence fields, Tier-1 missing fields).
_PREFIX_RULES: List[tuple] = [
    ("doc_conflict_hard_", "Document identity & date conflicts", "required"),
    ("doc_conflict_warn_", "Document identity & date conflicts", "required"),
    ("underwriting_reconciliation_", "Financial figure conflicts", "required"),
    ("source_conflict_carrier_", "Carrier name conflicts", "required"),
    ("source_conflict_", "Cross-document data conflicts", "required"),
    ("ocr_low_confidence_", "Low OCR confidence", "required"),
    ("tier1_missing_", "Missing baseline ACORD 125 fields", "required"),
]


def _lookup(code: str) -> tuple:
    """Return (cluster_label, default_tier) for a rule code."""
    if code in CLUSTER_MAP:
        return CLUSTER_MAP[code], TIER_MAP.get(code, DEFAULT_TIER)
    for prefix, cluster, tier in _PREFIX_RULES:
        if code.startswith(prefix):
            return cluster, tier
    return DEFAULT_CLUSTER, DEFAULT_TIER


# ── Legacy message classification (sqs_service.evaluate_stops / utils/validators
#    .run_field_validations) ─────────────────────────────────────────────────
#
# These two functions predate cross_form_validator.py and still return plain,
# uncoded strings - this is the ORIGINAL field-level hard/soft stop source
# (COPE completeness, WC/umbrella/auto domain checks, and format/range
# validation), called first inside extraction_pipeline._finalize_pipeline
# (``hard_stops, soft_stops = evaluate_stops(...)``). It produces the bulk of
# real-world stops, including the exact "Property Minimum Viable COPE
# incomplete" message the client screenshotted - so unlike the smaller sources
# above, this one is classified by matching known substrings against the
# message text itself (there is no code to key off). Checked in order, most
# specific phrase first, so a specific rule is never shadowed by a generic one
# later in the list (e.g. "Umbrella SIR" before a generic "limit" match).
_LEGACY_MESSAGE_RULES: List[tuple] = [
    # Property COPE / deductibles / valuation / BI
    ("Minimum Viable COPE incomplete", "Property COPE completeness", "required"),
    ("Carrier-Grade COPE incomplete", "Property COPE quality", "binder_followup"),
    ("Peril-specific deductibles referenced but not defined", "Property deductible completeness", "required"),
    ("Property valuation method not specified", "Property valuation method", "recommended"),
    ("Valuation basis conflict", "Property valuation advisories", "binder_followup"),
    ("Business Income coverage detected", "Business Income coverage", "recommended"),
    ("Coinsurance percentage", "Property coinsurance", "recommended"),
    # Umbrella (specific phrases before the generic "Umbrella ..." ones below)
    ("Umbrella detected but no underlying", "Umbrella underlying coverage", "required"),
    ("Umbrella SIR", "Umbrella underlying coverage", "required"),
    ("Umbrella attaches over WC but Employers Liability", "Umbrella Employers Liability", "binder_followup"),
    ("Employers Liability limit (", "Umbrella Employers Liability", "binder_followup"),
    ("Claims-made GL policy requires retro date for umbrella", "Claims-made continuity", "recommended"),
    ("Umbrella and GL policy periods misaligned", "Umbrella policy period alignment", "required"),
    ("Umbrella and GL expiration dates misaligned", "Umbrella policy period alignment", "required"),
    ("Underlying limits may not meet umbrella requirements", "Umbrella attachment limits", "recommended"),
    ("Umbrella limit", "Umbrella attachment limits", "recommended"),
    # GL / claims-made
    ("GL policy is claims-made - retro date is required", "Claims-made continuity", "recommended"),
    ("GL coverage detected but no class codes found", "WC / GL class code alignment", "recommended"),
    ("GL coverage detected but no revenue or payroll found", "GL exposure basis", "recommended"),
    ("GL each occurrence limit", "GL exposure basis", "recommended"),
    ("GL aggregate limit", "GL exposure basis", "recommended"),
    # Workers Comp
    ("Monopolistic WC state detected but wc_monopolistic_payroll", "Monopolistic WC state requirements", "required"),
    ("Monopolistic WC state (ND/OH/WA/WY) requires the state fund", "Monopolistic WC state requirements", "required"),
    ("Monopolistic WC state detected", "Monopolistic WC state requirements", "recommended"),
    ("Multi-state WC", "WC payroll reconciliation", "required"),
    ("Workers Comp detected but payroll is missing", "WC payroll reconciliation", "recommended"),
    ("Revenue-to-payroll ratio", "WC payroll reconciliation", "recommended"),
    ("WC payroll", "WC payroll reconciliation", "recommended"),
    # Auto
    ("Split liability limits incomplete", "Auto liability structure", "required"),
    ("Physical damage coverage present but deductibles not specified", "Auto symbols / coverage alignment", "recommended"),
    ("Auto liability limit", "Auto symbols / coverage alignment", "recommended"),
    # Prior carrier / narrative
    ("Carrier adverse action indicated", "Prior carrier / marketing context", "recommended"),
    # Format / range validation (utils/validators.py) - data-quality issues, not
    # domain-coverage gaps, so they get their own two clusters rather than being
    # forced into a domain bucket above.
    ("Effective date", "Date format & range", "recommended"),
    ("Expiration date", "Date format & range", "recommended"),
    ("effective date", "Date format & range", "recommended"),
    ("FEIN", "Contact & identity field format", "recommended"),
    ("Address missing", "Contact & identity field format", "recommended"),
    ("Phone", "Contact & identity field format", "recommended"),
    ("Email", "Contact & identity field format", "recommended"),
    ("Subcontracted work percentage", "Monetary & percentage field format", "recommended"),
    ("Building ITV percentage", "Monetary & percentage field format", "recommended"),
    ("Total revenue", "Monetary & percentage field format", "recommended"),
    ("Total payroll", "Monetary & percentage field format", "recommended"),
    ("Building value", "Monetary & percentage field format", "recommended"),
    ("BPP value", "Monetary & percentage field format", "recommended"),
    ("Business income limit", "Monetary & percentage field format", "recommended"),
]


def classify_legacy_message(message: str, severity: str) -> tuple:
    """Cluster/tier a plain-string message from evaluate_stops()/
    run_field_validations() by matching known substrings (these two functions
    predate cross_form_validator.py and carry no code). Falls through to the
    same default bucket as an unrecognized code so nothing is ever dropped."""
    for phrase, cluster, tier in _LEGACY_MESSAGE_RULES:
        if phrase in message:
            return cluster, (tier if severity != "hard_stop" else "required")
    return DEFAULT_CLUSTER, DEFAULT_TIER


def make_issue(
    code: str, severity: str, message: str, forms: Optional[List[str]] = None,
    cluster: Optional[str] = None, tier: Optional[str] = None,
) -> dict:
    """Build one structured issue dict. `severity` is the issue's OWN
    classification at emit time ("hard_stop" / "soft_warning" / "advisory") -
    the effective severity used for display is re-derived later in
    build_grouped_view() against whatever hard_stops/soft_stops the caller
    ends up returning (which may have downgraded a hard stop via
    classify_stops).

    `cluster`/`tier` are optional pre-computed overrides for callers that
    classified the message themselves (e.g. via classify_legacy_message(),
    which has no `code` to key a registry lookup off of). When omitted,
    build_grouped_view() derives them from `code` via the registry as usual.
    """
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "forms": list(forms or []),
        "cluster": cluster,
        "tier": tier,
    }


def _cluster_rank_key(cluster: dict) -> tuple:
    # More forms affected, then more merged issues, then stable alpha order.
    return (-len(cluster["forms"]), -cluster["count"], cluster["cluster"])


def _make_clusters(items: List[dict]) -> List[dict]:
    by_cluster: Dict[str, List[dict]] = {}
    order: List[str] = []
    for it in items:
        key = it["cluster"]
        if key not in by_cluster:
            by_cluster[key] = []
            order.append(key)
        by_cluster[key].append(it)

    clusters = []
    for key in order:
        members = by_cluster[key]
        forms = sorted({f for m in members for f in m["forms"]})
        clusters.append({
            "cluster": key,
            "issue_id": members[0].get("issue_id") or issue_id_for(members[0]["message"], forms),
            "primary_message": members[0]["message"],
            "count": len(members),
            "forms": forms,
            "items": members,
        })
    clusters.sort(key=_cluster_rank_key)
    return clusters


def build_grouped_view(
    structured_issues: List[dict],
    hard_stops: List[str],
    soft_stops: List[str],
) -> dict:
    """Group structured issues into clustered Hard Stop / tiered Warning
    sections plus a top-3 "fix this first" list.

    `hard_stops` / `soft_stops` are the FINAL string lists the caller is
    about to return to the client (i.e. already passed through
    classify_stops()), so an issue originally emitted as a hard stop but
    downgraded for a non-property submission is correctly reclassified here
    as a warning. Issues whose message isn't found in either list (this
    only happens for `advisory`-severity issues, which are never added to
    hard_stops/soft_stops in the first place) keep their original severity.
    """
    hard_stops = hard_stops or []
    soft_stops = soft_stops or []

    def _present_in(message: str, final_list: List[str]) -> bool:
        # Exact match covers the common case. Prefix match covers callers that
        # append a suffix to the original message (e.g. an "(Affects: ... Fix:
        # ...)" annotation added after this issue's message was captured) -
        # the original text is still the start of the final string, so a
        # downgrade/presence check must not require byte-for-byte equality.
        if message in final_list:
            return True
        return any(s.startswith(message) for s in final_list if message)

    enriched: List[dict] = []
    for issue in structured_issues or []:
        code = issue.get("code") or "uncategorized"
        message = issue.get("message") or ""
        orig_severity = issue.get("severity") or issue.get("type") or "soft_warning"

        if orig_severity == "hard_stop":
            if _present_in(message, hard_stops):
                severity = "hard_stop"
            elif _present_in(message, soft_stops):
                severity = "soft_warning"  # downgraded by classify_stops
            else:
                severity = "hard_stop"
        else:
            severity = orig_severity

        # Prefer an explicit cluster/tier the caller already computed (e.g.
        # classify_legacy_message(), which has no code to key a lookup off of)
        # over the code-keyed registry lookup.
        if issue.get("cluster"):
            cluster = issue["cluster"]
            default_tier = issue.get("tier") or DEFAULT_TIER
        else:
            cluster, default_tier = _lookup(code)
        tier = "required" if severity == "hard_stop" else default_tier

        _forms = issue.get("forms") or []
        enriched.append({
            "code": code,
            "issue_id": issue.get("issue_id") or issue_id_for(message, _forms),
            "message": message,
            "forms": _forms,
            "field": issue.get("field"),
            "source_fact": issue.get("source_fact"),
            "severity": severity,
            "cluster": cluster,
            "tier": tier,
        })

    # Safety net: guarantee every message the caller is actually about to show
    # (the final hard_stops/soft_stops lists) is represented SOMEWHERE in this
    # grouped view, even if it came from a source this registry doesn't yet
    # tag. Without this, a future untagged source would silently vanish from
    # the clustered/tiered display instead of just landing in "Other
    # validations" - completeness here must never depend on every producer
    # remembering to call make_issue().
    _covered = [i["message"] for i in enriched]
    def _covered_by(msg: str) -> bool:
        return any(msg == m or _present_in(msg, [m]) or _present_in(m, [msg]) for m in _covered)

    for _msg in hard_stops:
        if not _covered_by(_msg):
            enriched.append({
                "code": "uncovered_hard_stop", "issue_id": issue_id_for(_msg, []),
                "message": _msg, "forms": [], "field": None, "source_fact": None,
                "severity": "hard_stop", "cluster": DEFAULT_CLUSTER, "tier": "required",
            })
    for _msg in soft_stops:
        if not _covered_by(_msg):
            enriched.append({
                "code": "uncovered_soft_stop", "issue_id": issue_id_for(_msg, []),
                "message": _msg, "forms": [], "field": None, "source_fact": None,
                "severity": "soft_warning", "cluster": DEFAULT_CLUSTER, "tier": DEFAULT_TIER,
            })

    hard_items = [i for i in enriched if i["severity"] == "hard_stop"]
    hard_clusters = _make_clusters(hard_items)

    warning_buckets: Dict[str, List[dict]] = {"required": [], "recommended": [], "binder_followup": []}
    for i in enriched:
        if i["severity"] != "hard_stop":
            warning_buckets[i["tier"]].append(i)
    warnings = {tier: _make_clusters(items) for tier, items in warning_buckets.items()}

    # "Important" preview (warnings-only): the top 3 warning clusters, Required
    # before submission first then Recommended before quoting. Hard stops are
    # deliberately excluded - they already have their own always-visible
    # banner, so a preview would just duplicate them. Binder-followup is
    # deliberately excluded too - it's the lowest-priority tier by definition,
    # so it should never displace a Required/Recommended item from "Important".
    important: List[dict] = []
    for c in warnings["required"]:
        if len(important) >= 3:
            break
        important.append({**c, "severity": "soft_warning", "tier": "required"})
    if len(important) < 3:
        for c in warnings["recommended"]:
            if len(important) >= 3:
                break
            important.append({**c, "severity": "soft_warning", "tier": "recommended"})

    return {
        "important": important,
        "hard_stops": hard_clusters,
        "warnings": warnings,
        "tier_labels": TIER_LABELS,
    }
