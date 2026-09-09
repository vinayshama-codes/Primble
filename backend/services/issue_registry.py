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
import re
from typing import Any, Dict, List, Optional, Set, Tuple

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
    # Some (not all) locations lack construction type / values - a completeness
    # gap in the same family as the package-level COPE check above.
    "per_location_cope_incomplete": "Property COPE completeness",
    # Property deductibles
    "peril_deductible_referenced_but_undefined": "Property deductible completeness",
    "property_aop_deductible_missing": "Property deductible completeness",
    "property_peril_deductible_incomplete": "Property deductible completeness",
    "property_deductible_basis_missing": "Property deductible completeness",
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
    # Class codes. SYS-04 (2026-09-05): a GL-only finding must NOT render under a
    # heading naming Workers Comp - the client's criterion is that a line not in
    # the submission generates no WC language, and a cluster TITLE is language.
    # Live run: a GL+Property contractor with no WC saw "WC / GL class code
    # alignment" over a single item reading "GL coverage detected but no class
    # codes found". `wc_gl_class_code_mismatch` genuinely compares the two and
    # keeps naming both.
    "wc_gl_class_code_mismatch": "WC / GL class code alignment",
    "gl_codes_no_operations": "GL class code alignment",
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
    "umbrella_missing_employers_liability": "Umbrella Employers Liability",
    "umbrella_el_below_minimum": "Umbrella Employers Liability",
    # Claims-made
    "claims_made_missing_retro_date": "Claims-made continuity",
    "claims_made_missing_prior_acts": "Claims-made continuity",
    # Auto
    "auto_split_limits_incomplete": "Auto liability structure",
    "auto_hired_nonowned_symbols_missing": "Auto symbols / coverage alignment",
    "auto_physical_damage_symbols_missing": "Auto symbols / coverage alignment",
    "auto_symbols_not_captured": "Auto symbols / coverage alignment",
    "auto_owned_fleet_not_covered_by_symbol": "Auto symbols / coverage alignment",
    "auto_doc_symbol_missing": "Auto symbols / coverage alignment",
    # Re-clustered 2026-08-26 (V1 H1): it is about the vehicle SCHEDULE, and
    # it is the coded twin of the new legacy "Vehicle schedule not provided"
    # warning (see _LEGACY_SUPERSEDED_BY_CODE), so both land in one cluster.
    "auto_agreed_value_requires_schedule": "Auto completeness",
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
    # Coverage terminology / data consistency (2026-09-03). Both were falling
    # into DEFAULT_CLUSTER, which put an advice-only terminology note and a
    # pillar-capping loss conflict in ONE cluster headed "Other validations" -
    # so neither read as what it is, and the cluster could not carry the
    # "does not affect your score" note because its members disagreed.
    "unmapped_coverage_line": "Coverage terminology not recognised",
    "loss_history_attestation_conflict": "Loss history conflict",
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
    "claims_made_missing_retro_date": "recommended",
    "claims_made_missing_prior_acts": "recommended",
    "property_aop_deductible_missing": "recommended",
    "property_peril_deductible_incomplete": "recommended",
    "property_deductible_basis_missing": "recommended",
    "per_location_cope_incomplete": "recommended",
    "property_coinsurance_missing": "recommended",
    "property_coinsurance_unreasonable": "recommended",
    "bi_coverage_no_limit": "recommended",
    "property_valuation_method_missing": "recommended",
    "auto_hired_nonowned_symbols_missing": "recommended",
    "auto_physical_damage_symbols_missing": "recommended",
    "auto_symbols_not_captured": "recommended",
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
    # Advice only, and nothing can be typed to clear it - the lowest tier is
    # where it belongs, so it stops displacing a real Required/Recommended item
    # from the IMPORTANT band (that promotion skips binder_followup by design).
    "unmapped_coverage_line": "binder_followup",
}

# ── Inline resolution (SQS panel: "Open" a validation and fix it in place) ────
#
# code -> how the producer can resolve this issue directly from the Cross-Form
# Validation panel, instead of hunting for the field on a form. Four modes:
#
#   field    - the issue clears by entering one or more scalar values. `facts`
#              are canonical fact keys; EVERY one must resolve through
#              arq_service._canonical_key (i.e. be writable via the producer
#              answer path) or the guard test test_issue_resolution fails the
#              build. The modal renders one input per fact.
#   schedule - the issue clears by editing a repeating table. `schedule_key`
#              MUST be a live schedule in schedule_capture.SCHEDULE_DEFS (guard
#              test enforces). The modal renders the shared ScheduleTable.
#   narrative- the issue is resolved by an ACORD 101 explanation. The modal
#              renders a textarea whose text is appended to the
#              `additional_remarks_text` fact (which several rules here read to
#              downgrade a hard stop to a warning).
#   none     - no single value/table/narrative fixes it (a coverage decision, an
#              advisory). The modal shows the detail read-only with the existing
#              Resolve / Dismiss work-tracking controls.
#
# ── `add_forms`: a FIFTH capability, orthogonal to the four modes (UX-05) ─────
#
# A resolution may ALSO carry `add_forms` - the ACORD form(s) this issue's own
# message tells the producer to add, minus any already in the package. It is not
# a mode, because it composes with every one of them: `acord101_required` needs
# BOTH the narrative textarea and the offer to add ACORD 101, and
# `contractor_missing_acord186` is `none` mode whose only fix IS the form.
# Making it a fifth mode would have forced a false either/or.
#
# It is NOT declared in this map, because it is not a property of the CODE - it
# is a property of the ISSUE against THIS package. `cross_form_validator._issue`
# declares which form the sentence names, `_filter_add_forms` drops the ones
# already selected, `make_issue` carries it across the mirror into the grouped
# view, and `services/form_addition` re-derives it server-side on the write so a
# stale tab can never add a form nothing is asking for.
#
# This map is the SINGLE source of truth for the feature. It attaches to every
# issue and cluster centrally (make_issue / build_grouped_view / _make_clusters
# below and cross_form_validator._issue), so no rule body changes and no route
# has to thread it through. Adding a new rule code means adding one row here;
# the guard test fails the build if a live cross-form code is left unmapped.


def _r_field(*facts: str) -> dict:
    return {"mode": "field", "facts": list(facts)}


def _copy_resolution(res: dict) -> dict:
    """Independent copy of a resolution descriptor.

    `dict(res)` alone is NOT enough: it duplicates the mapping but leaves the
    `facts` LIST shared with the template, so a caller appending to
    resolution["facts"] silently corrupts every future issue with that code.
    Latent since the feature shipped - test_resolution_for_returns_a_copy only
    reassigned a scalar key, which a shallow copy does isolate. Found by the
    legacy-rule guard tests (2026-08-08) and fixed here, for every mode."""
    out = {k: (list(v) if isinstance(v, list) else v) for k, v in res.items()}
    # Owner 2026-08-24: a hard stop or warning resolved inline must offer the
    # same choices a recommendation card does - the ResolutionModal used to
    # render a bare "Type the correct value..." box for every fact. Attached
    # HERE because every resolution (RESOLUTION_MAP, tier-1, legacy fallback)
    # is copied through this one function, so no render path can be missed.
    if out.get("mode") == "field" and out.get("facts") and "controls" not in out:
        try:
            from services.answer_options import (
                control_for, is_multi_select, options_for,
            )
            controls = {}
            for fact in out["facts"]:
                entry = {"control": control_for(fact)}
                opts = options_for(fact)
                if opts:
                    entry["options"] = opts
                    entry["multi"] = is_multi_select(fact)
                controls[fact] = entry
            out["controls"] = controls
        except Exception:                                     # noqa: BLE001
            pass
    return out


def _r_schedule(schedule_key: str) -> dict:
    return {"mode": "schedule", "schedule_key": schedule_key}


_R_NARRATIVE = {"mode": "narrative"}
_R_NONE = {"mode": "none"}


def _r_review(note: str) -> dict:
    """A 'none'-mode resolution carrying a CONTEXT-SPECIFIC review note. mode
    'none' renders no functional value input (nothing is auto-applied) - the
    `note` just replaces the generic "needs a coverage/form change" hint with
    wording that fits WHY this particular item can't be typed (client #4: a
    cross-document conflict on a nested sub-field is reconciled on the form, not
    by a picker/typed value, so it must say that instead of looking skipped)."""
    return {"mode": "none", "note": note}

RESOLUTION_MAP: Dict[str, dict] = {
    # ── Property COPE ──
    "minimum_viable_cope_missing": _r_field(
        "occupancy_type", "construction_type",
        "property_building_value", "property_bpp_value",
    ),
    # Six facts, not the four this rule's own MESSAGE names, because its legacy
    # twin is suppressed below and the twin's modal was the only place the
    # producer could type `coinsurance_percentage` at all. Measured 2026-09-08:
    # with coinsurance the sole missing COPE item, `evaluate_stops` emits ONLY
    # "Carrier-Grade COPE incomplete" - there is no dedicated coinsurance card
    # the way there is for valuation method - so suppressing the twin without
    # widening this first would have deleted that fix path outright.
    # A resolution descriptor is UI only (the modal reads it, and audit_routes'
    # trade-off note reads it for wording); no scorer reads it, so offering two
    # extra boxes moves nothing. The modal already prints "Provide the correct
    # value for whichever applies - you don't have to fill every field."
    "carrier_grade_cope_incomplete": _r_field(
        "year_built", "roof_year", "sprinkler_system", "fire_protection_class",
        "valuation_method", "coinsurance_percentage",
    ),
    "per_location_cope_incomplete": _r_schedule("property_locations"),
    # ── Property deductibles ──
    "peril_deductible_referenced_but_undefined": _r_field(
        "property_deductible_wind", "property_deductible_earthquake", "property_deductible_flood",
    ),
    "property_aop_deductible_missing": _r_field("property_deductible_aop"),
    "property_peril_deductible_incomplete": _r_field(
        "property_deductible_wind", "property_deductible_earthquake", "property_deductible_flood",
    ),
    # `deductible_basis` IS a writable canonical fact (FACT_REGISTRY, extraction
    # schema). The rule used to read the phantom `property_deductible_basis`
    # - a key nothing writes - so it fired on every property policy with a
    # deductible and this row said it could only be cleared by a note. Fixed
    # 2026-08-26 (H1 audit): the rule reads the real key and the fix is to
    # type the basis.
    "property_deductible_basis_missing": _r_field("deductible_basis"),
    # ── Property valuation ──
    "property_valuation_method_missing": _r_field("valuation_method"),
    "acv_high_value_building": _R_NONE,   # advisory: consider RCV (coverage choice)
    "rcv_old_building": _R_NONE,          # advisory: verify reconstruction cost
    # ── Property coinsurance ──
    "property_coinsurance_missing": _r_field("coinsurance_percentage", "agreed_value_endorsement"),
    "property_coinsurance_unreasonable": _r_field("coinsurance_percentage"),
    # ── Business Income ──
    "bi_missing_period_of_restoration": _r_field("period_of_restoration"),
    "bi_coverage_no_limit": _r_field("business_income_limit", "period_of_restoration"),
    # ── Location / address ──
    "location_count_mismatch": _r_schedule("property_locations"),
    "location_count_mismatch_minor": _r_schedule("property_locations"),
    "location_address_mismatch": _r_schedule("property_locations"),
    "physical_vs_mailing_address_unclear": _r_field("physical_address"),
    # ── Builders Risk ──
    "builders_risk_project_value_missing": _r_field("builders_risk_project_cost"),
    "builders_risk_property_duplication": _R_NARRATIVE,   # explain disjoint coverage via 101
    "inland_marine_property_overlap": _R_NARRATIVE,       # confirm no double-count via 101
    # ── WC payroll reconciliation ──
    "wc_payroll_mismatch": _r_field("wc_payroll", "total_payroll"),
    "wc_payroll_vs_revenue": _r_field("wc_payroll", "total_revenue"),
    "wc_subcontracting_payroll_conflict": _r_field("percent_subcontracted", "wc_payroll"),
    # per-state payroll has no live capture schedule / writable scalar - explain
    # V1 H3 (2026-08-27): the breakdown by state and class IS the employee-group
    # table - Resolve opens it instead of asking for a note.
    "wc_multi_state_no_breakdown": _r_schedule("wc_class_codes"),
    "wc_state_payroll_total_mismatch": _r_field("total_payroll"),
    # ── WC / GL class code alignment ──
    "wc_gl_class_code_mismatch": _R_NARRATIVE,            # explain exposure mismatch via 101
    "gl_codes_no_operations": _r_field("operations_description"),
    # ── Contractor / subcontracting ──
    # `none` + `add_forms=["ACORD_186"]` (declared at the emit site). No typed
    # value closes it; the form itself is the fix.
    "contractor_missing_acord186": _R_NONE,
    "acord186_high_sub_high_wc_payroll": _r_field("percent_subcontracted", "wc_payroll"),
    "high_subcontracting_no_wc_payroll": _r_field("wc_payroll"),
    # ── Umbrella ──
    # The rule clears as soon as ANY underlying limit is on record, and all three
    # are writable canonical facts - so this is typed, not "add a form". It was
    # _R_NONE until 2026-08-08, which meant a HARD STOP capping the package at 60
    # rendered a dead button. Its legacy twin is typed the same way.
    "umbrella_no_underlying_coverage": _r_field(
        "gl_each_occurrence", "gl_limits", "auto_liability_limit"),
    "umbrella_sir_below_gl_deductible": _r_field("umbrella_sir", "gl_deductible"),
    "umbrella_gl_period_misaligned": _r_field("umbrella_effective_date", "effective_date"),
    "umbrella_gl_expiration_misaligned": _r_field("umbrella_expiration_date", "expiration_date"),
    # underlying auto/wc date facts are not writable; resolved via 101 note
    # (these rules already downgrade a hard stop when additional_remarks_text is set)
    "umbrella_auto_period_misaligned": _R_NARRATIVE,
    "umbrella_auto_expiration_misaligned": _R_NARRATIVE,
    "umbrella_wc_period_misaligned": _R_NARRATIVE,
    "umbrella_gl_attachment_failure": _r_field("gl_each_occurrence", "gl_limits"),
    "umbrella_gl_limits_not_found": _r_field("gl_each_occurrence", "gl_limits"),
    "umbrella_auto_attachment_failure": _r_field("auto_liability_limit"),
    "umbrella_auto_limits_not_found": _r_field("auto_liability_limit"),
    "umbrella_missing_employers_liability": _r_field("employers_liability_limits"),
    "umbrella_el_below_minimum": _r_field("employers_liability_limits"),
    # ── Claims-made continuity ──
    "claims_made_missing_retro_date": _r_field("retro_date"),
    # `prior_acts_confirmation` is not a writable canonical fact - explain via 101
    "claims_made_missing_prior_acts": _R_NARRATIVE,
    # ── Auto ──
    # Split-limit components are not writable canonical facts; that one stays
    # read-only. The three symbol rules below used to be _R_NONE on the stated
    # grounds that "coverage symbols are not writable canonical facts" - which
    # was never true: `auto_covered_symbols` has been in FACT_REGISTRY all
    # along. That comment is why the client saw a Resolve button that could not
    # resolve anything. Corrected 2026-08-07: the carrier has already made and
    # documented the coverage decision, so the fix is a TRANSFER of an existing
    # value, which is precisely what a field resolution is for.
    # The three split components ARE writable canonical facts
    # (`auto_bi_per_person` / `auto_bi_per_accident` / `auto_pd_per_accident`
    # - schema, registry, stamped by pdf_service). Both engines read the
    # unprefixed phantom names until 2026-08-26 (H1 audit), which is why this
    # was marked unresolvable and why the hard stop could never be satisfied.
    "auto_split_limits_incomplete": _r_field(
        "auto_bi_per_person", "auto_bi_per_accident", "auto_pd_per_accident"),
    "auto_symbols_not_captured": _r_field("auto_covered_symbols"),
    "auto_hired_nonowned_symbols_missing": _r_field("auto_covered_symbols"),
    "auto_physical_damage_symbols_missing": _r_field("auto_covered_symbols"),
    "auto_owned_fleet_not_covered_by_symbol": _r_field("auto_covered_symbols"),
    # Drive Other Car is an endorsement naming individual insureds, recorded per
    # driver on ACORD 127 - so it clears by editing the driver schedule.
    "auto_doc_symbol_missing": _r_schedule("auto_drivers"),
    "auto_agreed_value_requires_schedule": _r_schedule("auto_vin_schedule"),
    # `auto_um_uim_limit` IS a writable canonical fact - the previous comment
    # here claimed otherwise and was wrong (verified against _canonical_key),
    # which left a typeable advisory rendering a dead button.
    "auto_um_uim_not_specified": _r_field("auto_um_uim_limit"),
    "auto_pip_medpay_not_specified": _r_field("auto_med_pay_limit"),
    "auto_drive_other_car_not_specified": _R_NONE,        # advisory (DOC symbol not writable)
    # ── Silent exposure (coverage decisions - handled on their own forms) ──
    "crime_silent_exposure": _R_NONE,
    "cyber_silent_exposure": _R_NONE,
    # ── Certificates / evidence ──
    # `none` MODE, but no longer a dead end (UX-05, 2026-09-08): the emitting
    # rule declares `add_forms`, so the modal draws an "Add ACORD 25 / 28"
    # action over these. Decision_Tree.txt L501 asked for exactly that -
    # "Prompt user to generate ACORD 25/28 post-bind" - and only the warning
    # half was ever built.
    "certificate_requested_but_acord25_missing": _R_NONE,
    "property_evidence_requested_but_acord28_missing": _R_NONE,
    # ── Baseline / identity ──
    "acord125_missing": _R_NONE,                          # + add_forms ACORD 125
    "legal_name_equals_dba": _r_field("dba_name"),
    # ── Narrative requirement ──
    "acord101_required": _R_NARRATIVE,
    # ── Coverage terminology we could not place (client 1.7 / SYS-05) ──
    # NO typed fix exists and pretending otherwise is the defect this replaces:
    # the message said "Confirm which line it belongs to" over a button that
    # opened nothing, because the code was absent from this map entirely.
    # Clearing it would need a canonical "this part belongs to line X" fact,
    # a writer for it and a re-canonicalisation path - none of which exist, so
    # the honest answer is a note, not a dead input (owner, 2026-09-03).
    "unmapped_coverage_line": _r_review(
        "Primble can't tell which line this belongs to. Check the source "
        "document, then mark it resolved."
    ),
    # ── Loss history attestation vs the uploaded loss runs (client C2 2.6) ──
    # Owner 2026-09-03: this one is a PROPER warning, because the condition
    # behind it caps the Loss History pillar at 45 (`_LOSS_CONFLICT_CAP`). It
    # needed an entry the moment it earned its own cluster - the guard test
    # `test_every_cross_form_cluster_code_has_a_resolution` caught that, doing
    # exactly its job.
    #
    # It IS typeable, unlike the row above: the conflict is between an
    # attestation and a claim count, and the message already asks the producer
    # to "confirm with the insured which is correct". These three are the facts
    # that decide it, all writable through the producer-answer path, so stating
    # the truth retires the conflict on the next pipeline run - no extra wiring,
    # and the 45 cap lifts with it. `no_prior_losses` is deliberately absent: it
    # is a FLAG, not a writable canonical fact, and the guard test would fail.
    "loss_history_attestation_conflict": _r_field(
        "loss_history_no_prior_losses_indicator", "num_claims", "total_incurred",
    ),
}


def resolution_for(code: Optional[str]) -> Optional[dict]:
    """Inline-resolution descriptor for a rule code, or None.

    Returns a COPY so callers can attach it to an issue dict without any risk of
    mutating the shared template. None for codes with no inline resolution
    (legacy field-level stops, doc/source conflicts, OCR) - those keep their
    existing Resolve / Dismiss work-tracking controls unchanged.

    Tier-1 baseline fields (client review #4: "if we can provide it manually,
    why doesn't it have Open to fix?") are the one dynamically-coded family that
    DOES get a resolution here, via _tier1_resolution() below - each missing
    field/label is a genuine single scalar fact (producer/applicant name,
    mailing address, effective date, LOB, entity type, or one of the 3
    contact_* facts), the same shape RESOLUTION_MAP already handles for every
    other _r_field() rule. There was never a real "can't be typed" reason for
    these to be work-tracking-only; the "Fix:" text on the tier1 message itself
    already tells the producer to "provide this value manually" - this makes
    that literally clickable instead of a dead-end instruction.
    """
    if not code:
        return None
    res = RESOLUTION_MAP.get(code) or _LEGACY_CODE_RESOLUTIONS.get(code)
    if res:
        return _copy_resolution(res)
    if code.startswith("tier1_missing_"):
        return _tier1_resolution(code[len("tier1_missing_"):])
    if code.startswith("source_conflict_"):
        return _source_conflict_resolution(code)
    return None


_CONFLICT_REVIEW_NOTE = (
    "Documents disagree on this value. Confirm the correct one on the relevant "
    "form, then mark it resolved - it can't be applied automatically."
)


# ── "This one does not affect your score" - DECLARED, never inferred ─────────
#
# Owner, 2026-09-03: an item that cannot move the score should say so, and one
# that CAN must be treated as a proper warning.
#
# THE OBVIOUS IMPLEMENTATION IS WRONG, and it is worth saying why. Deriving the
# note from `severity == "advisory"` looks equivalent and is not:
# `loss_history_attestation_conflict` was emitted as an advisory while the
# condition behind it caps the Loss History pillar at 45
# (`sqs_service._LOSS_CONFLICT_CAP`). A blanket severity rule would have printed
# "does not affect your score" on a row that demonstrably does - a lie about a
# number, which is the one thing this codebase treats as unrecoverable. That
# issue is now emitted as a real `soft_warning` and is deliberately absent here.
#
# So membership is an EXPLICIT per-code claim. A new advisory gets no note until
# somebody has checked what its condition costs, which is the correct default:
# silence is not a promise, and the promise is what has to be earned.
# MEASURED 2026-09-03, and the result is why this list is one entry long. Of
# the ten advisory-typed issues, the underlying CONDITION of nearly every one
# already costs something somewhere else:
#
#   loss_history_attestation_conflict -> caps the Loss History pillar at 45
#                                        (`_LOSS_CONFLICT_CAP`)
#   auto_um_uim_not_specified         -> `auto_um_uim_limit` drives ACORD 137's
#                                        structural score AND an 8-point rec
#   auto_pip_medpay_not_specified     -> same, via `auto_med_pay_limit`
#   acv_high_value_building           -> `valuation_method` appears 18 times in
#   rcv_old_building                     the scorer
#   acord101_required                 -> `additional_remarks_text` downgrades
#                                        hard stops
#
# "Advisory" in this codebase is a DISPLAY ROUTING choice, not a promise about
# the score. Anything added below needs its own trace first.
SCORE_NEUTRAL_CODES: frozenset = frozenset({
    # Client 1.7 / SYS-05. Verified end to end: emitted to `structured_issues`
    # only (never hard_stops / soft_stops, pinned by
    # test_unmapped_coverage_line), and there is no FACT behind it to deduct
    # against - it is raw terminology we could not place. Principle 7 states the
    # rule outright: "give it no new scoring effect until a rule is explicitly
    # defined."
    "unmapped_coverage_line",
})

SCORE_NEUTRAL_NOTE = "Advice only - this does not affect your score."


def is_score_neutral(code: Any) -> bool:
    """True when this issue provably cannot move any score.

    Read by `make_issue` so every emitter gets it for free, and re-derived per
    CLUSTER in `_make_clusters` - a cluster only earns the note when EVERY
    member does, because one scoring member makes the sentence false.
    """
    return bool(code) and code in SCORE_NEUTRAL_CODES


def _writable_fact(fact: str) -> bool:
    """True when `fact` is a canonical scalar the producer-answer path can write
    (arq_service._canonical_key). Lazy import to keep this module cycle-agnostic
    (same pattern as _tier1_label_to_facts / cross_form_validator._to_int)."""
    if not fact:
        return False
    try:
        from services.arq_service import _canonical_key
        return bool(_canonical_key(fact))
    except Exception:                                  # pragma: no cover
        return False


def _source_conflict_resolution(code: str) -> Optional[dict]:
    """Resolution for a cross-document `source_conflict_<field>` /
    `source_conflict_carrier_<field>` issue (client #4).

    A conflict on a plain writable scalar (carrier name, prior carrier, employee
    count, ...) becomes a typed 'Open to fix' - the producer picks the correct
    value, which applies as a producer-provenance fact exactly like every other
    field resolution. A conflict on a NESTED structured-dict sub-field (a dotted
    key like 'risk_transfer.additional_insured_names') has no scalar apply path
    and is not held by the Data-Consistency picker, so it gets an honest review
    NOTE instead of a dead button - never left as a bare Resolve/Dismiss row that
    looks like the fix feature skipped it."""
    field = code[len("source_conflict_"):]
    # The carrier-conflict variant prefixes an EXTRA "carrier_" (so a carrier_name
    # conflict is `source_conflict_carrier_carrier_name`). Strip it only when what
    # remains is itself a real field - otherwise a field legitimately named
    # `carrier_*` (e.g. carrier_name) would be wrongly truncated to `name`.
    if field.startswith("carrier_"):
        stripped = field[len("carrier_"):]
        if "." in stripped or _writable_fact(stripped):
            field = stripped
    if not field:
        return None
    # Nested sub-field (dotted) or anything not writable as a scalar -> review note.
    if "." in field or not _writable_fact(field):
        return _r_review(_CONFLICT_REVIEW_NOTE)
    return _r_field(field)


_tier1_label_to_facts_cache: Optional[Dict[str, tuple]] = None


def _tier1_label_to_facts() -> Dict[str, tuple]:
    """label (as emitted by check_tier1()) -> the canonical fact key(s) that
    satisfy it. Lazy + cached: sqs_service doesn't import this module, so a
    module-level import here would be safe today, but every other cross-service
    reach-in in this file (see cross_form_validator._to_int) uses a lazy import
    specifically to keep this file import-cycle-agnostic as the pipeline grows -
    matched here for the same reason, not because a cycle currently exists."""
    global _tier1_label_to_facts_cache
    if _tier1_label_to_facts_cache is None:
        from services.sqs_service import TIER1_FIELDS, TIER1_CONTACT
        mapping: Dict[str, tuple] = {label: (field,) for field, label in TIER1_FIELDS.items()}
        # "Contact information" isn't one field - check_tier1() accepts ANY of
        # the three. Offer all three as alternatives; the producer only needs
        # to fill one (ResolutionModal already renders one input per fact and
        # applies whichever the producer actually types, same as every other
        # multi-fact _r_field() rule such as minimum_viable_cope_missing).
        mapping["Contact information"] = TIER1_CONTACT
        _tier1_label_to_facts_cache = mapping
    return _tier1_label_to_facts_cache


def _tier1_resolution(label: str) -> Optional[dict]:
    facts = _tier1_label_to_facts().get(label)
    # Through _copy_resolution so a tier-1 fix gets the same answer choices
    # every other field-mode resolution does (controls are attached there, the
    # one function every resolution passes through).
    return _copy_resolution(_r_field(*facts)) if facts else None


# Prefix rules for the dynamically-generated codes (one per fact/field, so
# they can't be listed individually above). Checked in order; first match
# wins. These cover the warning sources that sit outside cross_form_validator
# (doc-consistency conflicts, source conflicts, underwriting reconciliation,
# low-OCR-confidence fields, Tier-1 missing fields).
_PREFIX_RULES: List[tuple] = [
    ("doc_conflict_hard_", "Document identity & date conflicts", "required"),
    ("doc_conflict_warn_", "Document identity & date conflicts", "required"),
    # NOTE: `underwriting_reconciliation_` is handled BEFORE this table by
    # `_reconciliation_cluster` - the right bucket depends on what KIND of value
    # the fact holds, not on the prefix. Kept here as the fallback for a fact
    # whose kind cannot be resolved.
    ("underwriting_reconciliation_", "Financial figure conflicts", "required"),
    ("source_conflict_carrier_", "Carrier name conflicts", "required"),
    ("source_conflict_", "Cross-document data conflicts", "required"),
    ("ocr_low_confidence_", "Low OCR confidence", "required"),
    ("tier1_missing_", "Missing baseline ACORD 125 fields", "required"),
]


# The Data Consistency picker emits one code per FACT
# (`underwriting_reconciliation_<fact_key>`), and every one of them was landing
# in "Financial figure conflicts". A policy DATE is not a financial figure, and
# neither is a remarks paragraph - the owner's 2026-08-17 run showed
# "Policy Effective Date: documents disagree" filed under money. The bucket
# follows the value's KIND, which `fact_equivalence` already derives from the
# tables we maintain, so this needs no list of its own and a new fact is
# classified the day it is added.
_KIND_CLUSTER = {
    "money":      "Financial figure conflicts",
    "count":      "Financial figure conflicts",
    "percent":    "Financial figure conflicts",
    "date":       "Document identity & date conflicts",
    "name":       "Document identity & date conflicts",
    "address":    "Document identity & date conflicts",
    "identifier": "Document identity & date conflicts",
    "fein":       "Document identity & date conflicts",
    "state":      "Document identity & date conflicts",
    "phone":      "Cross-document data conflicts",
    "email":      "Cross-document data conflicts",
    "url":        "Cross-document data conflicts",
    "narrative":  "Cross-document data conflicts",
    # Free text and the small closed-set kinds. Without these,
    # `contractor_type` ("Commercial roofing contractor" vs "Contracting") fell
    # through to the prefix rule and was filed as a financial figure too.
    "text":       "Cross-document data conflicts",
    "code":       "Cross-document data conflicts",
    "yesno":      "Cross-document data conflicts",
}
_RECONCILIATION_PREFIX = "underwriting_reconciliation_"


def _reconciliation_cluster(code: str) -> Optional[str]:
    """Cluster for a Data Consistency code, chosen by the fact's value kind.

    None when the code is not a reconciliation code, or when the kind cannot be
    resolved - the caller then falls through to the prefix table, so behaviour
    is unchanged for anything this cannot classify.
    """
    if not code.startswith(_RECONCILIATION_PREFIX):
        return None
    try:
        from services.fact_equivalence import value_kind
        return _KIND_CLUSTER.get(value_kind(code[len(_RECONCILIATION_PREFIX):]))
    except Exception:                                         # pragma: no cover
        return None


def _lookup(code: str) -> tuple:
    """Return (cluster_label, default_tier) for a rule code."""
    if code in CLUSTER_MAP:
        return CLUSTER_MAP[code], TIER_MAP.get(code, DEFAULT_TIER)
    _rc = _reconciliation_cluster(code)
    if _rc:
        return _rc, "required"
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
# real-world stops, including the exact "Carrier-Grade COPE incomplete" warning
# the client screenshotted - so unlike the smaller sources above, this one is
# classified by matching known substrings against the message text itself
# (there is no code on the wire). Checked in order, most specific phrase first,
# so a specific rule is never shadowed by a generic one later in the list
# (e.g. "Umbrella SIR" before a generic "limit" match).
#
# COLUMNS: (phrase, cluster, tier, code, resolution)
#
# `code` (added 2026-08-08) is the fix for the client report "Resolve opens
# nothing". Until now these stops were tagged with a THROWAWAY index code
# (`legacy_soft_0`, `legacy_soft_1`, ...) generated at the call site, so
# resolution_for() had nothing to look up and every one of them rendered a
# work-tracking-only Resolve/Dismiss row - even when the fix was literally
# "type the number". Each rule now carries a stable, semantic code, and the
# `resolution` column states how it is fixed, using the SAME four modes and the
# same _r_field/_r_schedule/_R_NARRATIVE/_R_NONE helpers as RESOLUTION_MAP.
#
# Keeping code+resolution in THIS table rather than in RESOLUTION_MAP is
# deliberate: RESOLUTION_MAP is keyed by cross-form rule code and is guarded by
# test_no_orphan_resolution_codes (every entry must be a live CLUSTER_MAP code).
# Legacy stops have no CLUSTER_MAP entry - their cluster lives in this row - so
# they own their resolution here and resolution_for() consults both. One
# authored source per rule, no parallel table to drift.
#
# The `legacy_` code prefix is also load-bearing: it namespaces these away from
# the cross-form codes so _LEGACY_SUPERSEDED_BY_CODE's duplicate-suppression
# (which hides the legacy twin when the CODED twin is present) keeps working
# exactly as before. Never reuse a cross-form code here or a rule will suppress
# itself and both twins will render.
#
# Adding a rule to evaluate_stops()/run_field_validations() means adding a row
# here. test_legacy_rules.py fails the build if a message the engine can emit
# matches no row, matches the WRONG row, or carries a resolution naming a fact
# the producer-answer path cannot write.
_LEGACY_MESSAGE_RULES: List[tuple] = [
    # ── Property COPE / deductibles / valuation / BI ─────────────────────────
    ("Minimum Viable COPE incomplete", "Property COPE completeness", "required",
     "legacy_minimum_viable_cope", _r_field(
         "occupancy_type", "construction_type",
         "property_building_value", "property_bpp_value")),
    # The client's screenshot. evaluate_stops() checks SIX facts here (two more
    # than the cross-form twin), so all six are offered.
    ("Carrier-Grade COPE incomplete", "Property COPE quality", "binder_followup",
     "legacy_carrier_grade_cope", _r_field(
         "year_built", "roof_year", "sprinkler_system",
         "fire_protection_class", "valuation_method", "coinsurance_percentage")),
    ("Peril-specific deductibles referenced but not defined", "Property deductible completeness", "required",
     "legacy_peril_deductibles_undefined", _r_field(
         "property_deductible_wind", "property_deductible_earthquake",
         "property_deductible_flood")),
    ("Property valuation method not specified", "Property valuation method", "recommended",
     "legacy_valuation_method_missing", _r_field("valuation_method")),
    # The property-integrity gate's LAST-RESORT sentence, for a future branch
    # that raises the gate without naming its own cause. Unreachable from
    # today's code - every branch calls `_prop_hard_because` /
    # `_prop_soft_because`, pinned by
    # `test_legacy_rules.test_the_property_gate_always_names_its_cause` - but a
    # 60-cap must never be able to print without a fix, so it carries the four
    # facts the four property gates are actually about.
    ("Property details are incomplete", "Property COPE completeness", "required",
     "legacy_property_integrity_gate", _r_field(
         "valuation_method", "coinsurance_percentage",
         "period_of_restoration", "property_deductible_wind")),
    ("Valuation basis conflict", "Property valuation advisories", "binder_followup",
     "legacy_valuation_basis_conflict", _r_field("valuation_method")),
    ("Business Income coverage detected", "Business Income coverage", "recommended",
     "legacy_bi_no_limit", _r_field("business_income_limit", "period_of_restoration")),
    # The PROPERTY-INTEGRITY GATE's own sentence (sqs_service `_prop_hard_because`).
    # It must sit above the generic "Business income limit" FORMAT row at the
    # bottom of this table: first match wins on substring, and that row would
    # otherwise claim it and offer only `business_income_limit` - the one fact
    # that is already present. The missing fact is the period of restoration.
    ("Business income limit present but period of restoration not specified",
     "Business Income coverage", "required",
     "legacy_bi_period_of_restoration_missing", _r_field("period_of_restoration")),
    ("Coinsurance percentage", "Property coinsurance", "recommended",
     "legacy_coinsurance_percentage", _r_field("coinsurance_percentage")),
    # ── Umbrella (specific phrases before the generic "Umbrella ..." ones) ───
    # THE TWO ADEQUACY-GATE SENTENCES. `calculate_sqs` caps a form at 60 through
    # `extra_hard_reason` when the umbrella pillar reaches 0, and those two
    # sentences are what the producer reads. Neither matched a row until
    # 2026-09-08, so both rendered under "Other validations" with no fix control
    # at all - a red blocker, a held score, and nothing to click.
    #
    # They are NOT harvested by the legacy-message guard (it walks
    # `evaluate_stops`' append sites, and these are passed to `_resolve_cap`
    # instead), which is exactly why they went unnoticed. That blind spot is now
    # closed by `test_legacy_rules._harvest_cap_gate_reasons`.
    ("Umbrella present with no underlying GL or Auto limits",
     "Umbrella underlying coverage", "required",
     "legacy_umbrella_gate_no_underlying", _r_field(
         "gl_each_occurrence", "gl_limits", "auto_liability_limit")),
    ("Umbrella coverage is present but its supporting detail is incomplete",
     "Umbrella underlying coverage", "required",
     "legacy_umbrella_gate_detail_incomplete", _r_field(
         "umbrella_limit", "gl_each_occurrence", "gl_aggregate",
         "auto_liability_limit", "employers_liability_limits",
         "schedule_of_underlying_insurance", "umbrella_follow_form")),
    ("Umbrella detected but no underlying", "Umbrella underlying coverage", "required",
     "legacy_umbrella_no_underlying", _r_field(
         "gl_each_occurrence", "gl_limits", "auto_liability_limit")),
    ("Umbrella SIR", "Umbrella underlying coverage", "required",
     "legacy_umbrella_sir_below_gl_deductible", _r_field("umbrella_sir", "gl_deductible")),
    ("Umbrella attaches over WC but Employers Liability", "Umbrella Employers Liability", "binder_followup",
     "legacy_umbrella_missing_el", _r_field("employers_liability_limits")),
    ("Employers Liability limit (", "Umbrella Employers Liability", "binder_followup",
     "legacy_umbrella_el_below_minimum", _r_field("employers_liability_limits")),
    ("Claims-made GL policy requires retro date for umbrella", "Claims-made continuity", "recommended",
     "legacy_umbrella_retro_date_required", _r_field("retro_date")),
    # BEFORE the misalignment rows: first-match-wins on substring, and this
    # message contains neither of their phrases, but keeping the renewal item
    # adjacent to them documents that it REPLACED their false positive on a
    # renewal rather than being an extra warning stacked on top.
    ("Renewal: the umbrella's proposed policy term is not stated",
     "Umbrella policy period alignment", "recommended",
     "legacy_umbrella_renewal_term_unknown",
     _r_field("umbrella_effective_date", "umbrella_expiration_date")),
    ("Umbrella and GL policy periods misaligned", "Umbrella policy period alignment", "required",
     "legacy_umbrella_gl_period_misaligned", _r_field("umbrella_effective_date", "effective_date")),
    ("Umbrella and GL expiration dates misaligned", "Umbrella policy period alignment", "required",
     "legacy_umbrella_gl_expiration_misaligned", _r_field("umbrella_expiration_date", "expiration_date")),
    ("Underlying limits may not meet umbrella requirements", "Umbrella attachment limits", "recommended",
     "legacy_umbrella_underlying_below_minimum", _r_field("auto_liability_limit")),
    ("Umbrella limit", "Umbrella attachment limits", "recommended",
     "legacy_umbrella_limit", _r_field("umbrella_limit")),
    # ── GL / claims-made ─────────────────────────────────────────────────────
    ("GL policy is claims-made - retro date is required", "Claims-made continuity", "recommended",
     "legacy_gl_claims_made_retro_date", _r_field("retro_date")),
    # GL class codes are a per-location SCHEDULE with no live capture table
    # (schedule_capture.SCHEDULE_DEFS has none), so there is nothing to type
    # into and nothing to open - an honest note beats a dead button.
    ("GL coverage detected but no class codes found", "GL class code alignment", "recommended",
     "legacy_gl_no_class_codes", _r_review(
         "GL class codes are captured per location on ACORD 126. Add them there, "
         "then mark this resolved - there is no single value to enter here.")),
    ("GL coverage detected but no revenue or payroll found", "GL exposure basis", "recommended",
     "legacy_gl_no_exposure_basis", _r_field("total_revenue", "total_payroll")),
    ("GL each occurrence limit", "GL exposure basis", "recommended",
     "legacy_gl_each_occurrence", _r_field("gl_each_occurrence")),
    ("GL aggregate limit", "GL exposure basis", "recommended",
     "legacy_gl_aggregate", _r_field("gl_aggregate")),
    # ── Workers Comp ─────────────────────────────────────────────────────────
    ("Monopolistic WC state detected but wc_monopolistic_payroll", "Monopolistic WC state requirements", "required",
     "legacy_wc_monopolistic_payroll_missing", _r_field("wc_monopolistic_payroll")),
    ("Monopolistic WC state (ND/OH/WA/WY) requires the state fund", "Monopolistic WC state requirements", "required",
     "legacy_wc_monopolistic_private_carrier", _r_review(
         "This clears by changing the WC placement - remove the private-carrier "
         "request or acknowledge state-fund handling. No value can be typed here.")),
    ("Monopolistic WC state detected", "Monopolistic WC state requirements", "recommended",
     "legacy_wc_monopolistic_state", _r_review(
         "Advisory: WC in ND/OH/WA/WY must be placed with the state fund. "
         "Confirm the placement, then mark this resolved.")),
    # Per-state payroll has no live capture schedule and no writable scalar -
    # same call as the cross-form twin wc_multi_state_no_breakdown.
    ("Multi-state WC", "WC payroll reconciliation", "required",
     "legacy_wc_multi_state_no_breakdown", _r_schedule("wc_class_codes")),
    ("Workers Comp detected but payroll is missing", "WC payroll reconciliation", "recommended",
     "legacy_wc_payroll_missing", _r_field("wc_payroll", "total_payroll")),
    ("Revenue-to-payroll ratio", "WC payroll reconciliation", "recommended",
     "legacy_revenue_payroll_ratio", _r_field("total_revenue", "total_payroll")),
    ("WC payroll", "WC payroll reconciliation", "recommended",
     "legacy_wc_payroll_format", _r_field("wc_payroll")),
    # ── Auto ─────────────────────────────────────────────────────────────────
    # The three components are the canonical facts auto_bi_per_person /
    # auto_bi_per_accident / auto_pd_per_accident (the old note here named the
    # unprefixed phantoms both engines were reading - fixed 2026-08-26, H1
    # audit). Same resolution as the cross-form twin: type the three limits.
    ("Split liability limits incomplete", "Auto liability structure", "required",
     "legacy_auto_split_limits_incomplete", _r_field(
         "auto_bi_per_person", "auto_bi_per_accident", "auto_pd_per_accident")),
    ("Physical damage coverage present but deductibles not specified", "Auto symbols / coverage alignment", "recommended",
     "legacy_auto_physical_damage_deductibles", _r_field(
         "auto_deductible_comp", "auto_deductible_collision")),
    ("Auto liability limit", "Auto symbols / coverage alignment", "recommended",
     "legacy_auto_liability_limit", _r_field("auto_liability_limit")),
    # V1 H1 6.3 (2026-08-26): the two Auto Completeness items that also warn.
    # Both clear by editing the schedule the message names - the same
    # resolution shape as the cross-form agreed-value rule. Phrases chosen so
    # neither is a substring of any other row and neither contains "Auto
    # liability limit" (the row above is matched by substring).
    ("Vehicle schedule not provided", "Auto completeness", "recommended",
     "legacy_auto_vehicle_schedule_missing", _r_schedule("auto_vin_schedule")),
    ("Driver schedule not provided", "Auto completeness", "recommended",
     "legacy_auto_driver_schedule_missing", _r_schedule("auto_drivers")),
    # ── Prior carrier / narrative ────────────────────────────────────────────
    # This rule is gated on _narrative_remarks_text(facts) being empty, so an
    # ACORD 101 note is LITERALLY what clears it - narrative, not a typed value.
    ("Carrier adverse action indicated", "Prior carrier / marketing context", "recommended",
     "legacy_carrier_adverse_action", _R_NARRATIVE),
    # ── Format / range validation (utils/validators.py + sqs_service's two
    #    standalone validators) - data-quality issues, not domain-coverage gaps,
    #    so they get their own clusters rather than a domain bucket above.
    # MUST precede the "Effective date" row: first match wins, and this
    # message names both dates. Added 2026-08-14 with
    # `validate_policy_term_not_expired` - the one date check nothing was
    # doing, found by asking what a dec-page package can be checked for that
    # nothing checks. Every other rule here looks at the EFFECTIVE date;
    # nothing compared the EXPIRATION date to today, so a package whose term
    # ended last month printed both dates under "PROPOSED EFF/EXP DATE" and
    # raised nothing.
    # `umbrella_expiration_date` is the THIRD, optional input on both term rows
    # (2026-08-14). Typing a new expiration to clear an expired term silently
    # created an umbrella misalignment - the umbrella carries its own printed
    # period (07/15/2026 on the live package) and nothing on this modal showed
    # it, so the producer traded one issue for another and looped. The modal
    # pre-fills every fact it renders and submits only the ones actually
    # touched, so the umbrella date is now VISIBLE next to the date being
    # changed, and leaving it blank behaves exactly as it did before.
    ("Policy term already expired", "Date format & range", "required",
     "legacy_policy_term_expired",
     _r_field("effective_date", "expiration_date", "umbrella_expiration_date")),
    ("Policy term expires within", "Date format & range", "recommended",
     "legacy_policy_term_expiring",
     _r_field("effective_date", "expiration_date", "umbrella_expiration_date")),
    ("Effective date", "Date format & range", "recommended",
     "legacy_effective_date_format", _r_field("effective_date")),
    ("Expiration date", "Date format & range", "recommended",
     "legacy_expiration_date_format", _r_field("expiration_date")),
    # sqs_service.validate_effective_date_window(), a THIRD message source beyond
    # the two named at the top of this block. Its messages use the RAW FACT KEY
    # ("effective_date is more than 2 years in the past", "effective_date format
    # unrecognized"). This row read "effective date" with a SPACE and therefore
    # matched none of them - the warning had been falling into the "Other
    # validations" default bucket unnoticed. Found by
    # test_every_emittable_message_matches_a_rule_row; fixed 2026-08-08.
    ("effective_date", "Date format & range", "recommended",
     "legacy_effective_date_window", _r_field("effective_date")),
    # sqs_service.validate_naics_code(). Had NO row here until 2026-08-08, so it
    # silently fell through to the "Other validations" default bucket - found by
    # the coverage test below, which is exactly what that test exists to catch.
    ("NAICS code", "Contact & identity field format", "recommended",
     "legacy_naics_code_format", _r_field("naics_code")),
    ("NAICS prefix", "Contact & identity field format", "recommended",
     "legacy_naics_prefix_invalid", _r_field("naics_code")),
    ("FEIN", "Contact & identity field format", "recommended",
     "legacy_fein_format", _r_field("fein")),
    ("Address missing", "Contact & identity field format", "recommended",
     "legacy_address_missing", _r_field("mailing_address")),
    ("Phone", "Contact & identity field format", "recommended",
     "legacy_phone_format", _r_field("contact_phone")),
    ("Email", "Contact & identity field format", "recommended",
     "legacy_email_format", _r_field("contact_email")),
    ("Subcontracted work percentage", "Monetary & percentage field format", "recommended",
     "legacy_percent_subcontracted_format", _r_field("percent_subcontracted")),
    ("Building ITV percentage", "Monetary & percentage field format", "recommended",
     "legacy_building_itv_format", _r_field("building_ITV_percentage")),
    ("Total revenue", "Monetary & percentage field format", "recommended",
     "legacy_total_revenue_format", _r_field("total_revenue")),
    ("Total payroll", "Monetary & percentage field format", "recommended",
     "legacy_total_payroll_format", _r_field("total_payroll")),
    ("Building value", "Monetary & percentage field format", "recommended",
     "legacy_building_value_format", _r_field("property_building_value")),
    ("BPP value", "Monetary & percentage field format", "recommended",
     "legacy_bpp_value_format", _r_field("property_bpp_value")),
    ("Business income limit", "Monetary & percentage field format", "recommended",
     "legacy_business_income_limit_format", _r_field("business_income_limit")),
]

# code -> resolution, derived from the single authored table above. Built once
# at import; never edited by hand (that is what would let it drift).
_LEGACY_CODE_RESOLUTIONS: Dict[str, dict] = {
    _code: _res for _phrase, _cluster, _tier, _code, _res in _LEGACY_MESSAGE_RULES
}


# ── Cross-engine twin registry (client review #4) ────────────────────────────
# A handful of rules are computed by BOTH engines: the legacy field-level engine
# (sqs_service.evaluate_stops / utils.run_field_validations), which emits plain
# UNCODED strings, AND cross_form_validator, which emits the SAME rule with a
# real code and a resolution descriptor ("Open to fix"). When both fire they land
# in the identical cluster (the legacy phrase and the coded code are mapped to one
# cluster label in _LEGACY_MESSAGE_RULES / CLUSTER_MAP above) and render as two
# near-duplicate bullets - only one of which is resolvable. This maps each such
# coded key to the substring that identifies its legacy twin, so build_grouped_view
# can hide the legacy twin whenever its coded counterpart is present in the same
# view. Verified pairs: every entry's coded code and legacy phrase resolve to the
# same cluster above, which is the codebase's own signal that they are one rule.
#
# Suppression is display-only and conditional: the legacy twin is hidden ONLY when
# the coded twin is actually present, so no blocker is ever lost - if the coded
# rule did not fire (e.g. its extra form-trigger gate was not met, which the legacy
# rule does not require), the legacy row still shows exactly as before. The raw
# hard_stops list that caps SQS is never altered by this.
_LEGACY_SUPERSEDED_BY_CODE: Dict[str, str] = {
    "minimum_viable_cope_missing":               "Minimum Viable COPE incomplete",
    "peril_deductible_referenced_but_undefined": "Peril-specific deductibles referenced but not defined",
    "property_valuation_method_missing":         "Property valuation method not specified",
    "umbrella_no_underlying_coverage":           "Umbrella detected but no underlying",
    # REMOVED 2026-08-14: `umbrella_sir_below_gl_deductible` was deleted from
    # BOTH engines by C46 (an Umbrella SIR and a GL deductible protect
    # different exposures - the rule was never correct), so this row keyed on a
    # code nothing can emit and could never suppress anything. Found by
    # test_every_suppression_entry_names_a_code_that_can_actually_be_emitted,
    # which now fails the build on any such dead row.
    # Reported live 2026-08-14: the SAME umbrella/GL period problem rendered
    # TWICE - the coded rule as a hard stop naming both dates ("Umbrella
    # expiration date (07/15/2026) does not match GL/policy expiration date
    # (08/15/26)") and the legacy string as a separate warning ("Umbrella and
    # GL expiration dates misaligned"). Resolving the hard stop left its twin
    # sitting in the warnings column, which is what made warnings look like
    # they only appear AFTER hard stops are cleared. The coded twin is the one
    # to keep: it names the two dates and carries a typed resolution.
    # Codes taken from the live session, not from the rule names: the coded
    # issue on the wire is `umbrella_gl_EXPIRATION_misaligned` (the effective-
    # date twin is `..._period_misaligned`), and guessing the wrong one is a
    # silent no-op - suppression is keyed on the code actually present.
    "umbrella_gl_expiration_misaligned":         "Umbrella and GL expiration dates misaligned",
    # V1 H1 6.3 (2026-08-26). "Vehicle schedule not provided" (legacy, the
    # -15 + Warning) and "Agreed-value auto coverage with no vehicle schedule"
    # (coded) are ONE gap when both fire - the same schedule closes both. The
    # coded twin is kept: it carries the stricter condition and the same
    # schedule resolution. Scoring is untouched on both sides (the legacy
    # string still caps at 85; the coded issue still feeds the cross bucket as
    # spec section 7 defines) - this only stops two cards for one gap.
    "auto_agreed_value_requires_schedule":       "Vehicle schedule not provided",
    # CORRECTED 2026-09-08. The phrase read "Umbrella and GL effective dates
    # misaligned", which no engine emits - `sqs_service.evaluate_stops` says
    # "Umbrella and GL policy periods misaligned." (:1415). So this row matched
    # nothing and the GL-period twins had been rendering TWICE the whole time,
    # exactly like the Carrier-Grade COPE pair the owner reported. Found by
    # test_every_suppression_entry_still_names_a_real_legacy_message, which now
    # fails the build on a phrase no legacy rule can produce - the phrase-side
    # counterpart of the existing code-side guard.
    # No fix path is lost: both twins resolve the identical pair of facts
    # (umbrella_effective_date, effective_date).
    "umbrella_gl_period_misaligned":             "Umbrella and GL policy periods misaligned",
    # REMOVED 2026-09-08: `umbrella_auto_expiration_misaligned`,
    # `umbrella_auto_period_misaligned` and `umbrella_wc_period_misaligned`.
    # The legacy engine has NEVER emitted an Auto or WC misalignment string -
    # only the two GL ones above exist in evaluate_stops - so these three rows
    # named phrases nothing can produce and suppressed nothing. Same dead-row
    # class as the `umbrella_sir_below_gl_deductible` entry removed 2026-08-14,
    # and worse than useless: they made the map look like it covered the Auto
    # and WC twins. The coded rules themselves are untouched and still render.
    "auto_split_limits_incomplete":              "Split liability limits incomplete",
    "bi_coverage_no_limit":                      "Business Income coverage detected",
    # Reported live by the owner 2026-09-08: the Property COPE quality cluster
    # rendered BOTH twins - "Carrier-Grade COPE incomplete - SQS capped at 85.
    # Missing: ..." (legacy) above "Carrier-Grade COPE detail incomplete -
    # missing: ..." (coded) - each with its own Open to fix. Both already mapped
    # to the same cluster, which this map's docstring calls the codebase's own
    # signal that they are one rule; only the row was missing.
    # The phrase is a substring of the LEGACY message only: the coded message
    # reads "Carrier-Grade COPE detail incomplete", and "detail" breaks the
    # match, so this can never suppress its own keeper.
    # SAFE ONLY BECAUSE the coded resolution above was widened to the legacy
    # six first - see the note there. Do not narrow it back.
    "carrier_grade_cope_incomplete":             "Carrier-Grade COPE incomplete",
}


# ── WHICH CANONICAL FACT AN ISSUE CODE IS ABOUT ─────────────────────────────
# Both cross-document engines emit an issue per fact, under different code
# shapes. Resolving both to the same fact key is what lets build_grouped_view
# hide the weaker duplicate (see the supersession block there).
#
# `check_doc_consistency` tags most of its issues `field=<fact_key>`, which
# needs no remap. Four predate that convention and carry a rule name instead;
# they are listed here and NOWHERE else. `tests/test_doc_conflict_supersession.py`
# harvests every token that function can actually emit and fails the build when
# one has no mapping - the same anti-rot device as `_LEGACY_MESSAGE_RULES`, and
# the reason a fifth token cannot be added without a decision about its fact.
_DOC_CONFLICT_CODE_TO_FACT: Dict[str, str] = {
    "name_conflict":       "applicant_name",
    "fein_conflict":       "fein",
    "date_conflict":       "effective_date",
    "expiration_conflict": "expiration_date",
}

_DOC_CONFLICT_CODE_RE = re.compile(r"^doc_conflict_(?:hard|warn)_(.+)$")
_PICKER_CODE_RE = re.compile(r"^underwriting_reconciliation_(.+)$")


def doc_conflict_fact_key(code: Any) -> Optional[str]:
    """The canonical fact a ``doc_conflict_(hard|warn)_*`` issue is about.

    None for any other code, so a caller can test every issue without first
    filtering. An UNMAPPED token falls through as itself, which is correct for
    the `field=<fact_key>` majority and harmless for anything else - the worst
    case is that no duplicate is found.
    """
    m = _DOC_CONFLICT_CODE_RE.match(str(code or ""))
    if not m:
        return None
    token = m.group(1)
    return _DOC_CONFLICT_CODE_TO_FACT.get(token, token)


def picker_fact_key(code: Any) -> Optional[str]:
    """The canonical fact an ``underwriting_reconciliation_*`` issue is about."""
    m = _PICKER_CODE_RE.match(str(code or ""))
    return m.group(1) if m else None


def classify_legacy(message: str, severity: str) -> tuple:
    """(code, cluster, tier) for a plain-string message from evaluate_stops()/
    run_field_validations() (these predate cross_form_validator.py and carry no
    code on the wire). First matching phrase wins - the table is ordered most
    specific first. Falls through to the same default bucket as an unrecognized
    code, with code None, so nothing is ever dropped.

    Callers pass the returned code straight to make_issue(), which is what lets
    resolution_for() find the rule's fix mode and render "Open to fix". Before
    2026-08-08 they passed a throwaway `legacy_soft_<index>` instead and every
    legacy stop rendered as a dead Resolve/Dismiss row."""
    for phrase, cluster, tier, code, _res in _LEGACY_MESSAGE_RULES:
        if phrase in (message or ""):
            return code, cluster, (tier if severity != "hard_stop" else "required")
    return None, DEFAULT_CLUSTER, DEFAULT_TIER


def classify_legacy_message(message: str, severity: str) -> tuple:
    """(cluster, tier) only - the pre-existing signature, kept so any caller that
    does not need the code is unaffected."""
    _code, cluster, tier = classify_legacy(message, severity)
    return cluster, tier


# ── Message-derived resolution for legacy stops ──────────────────────────────
# A legacy stop that reached make_issue() through the normal path now carries a
# real `legacy_*` code, so resolution_for(code) answers directly. This MESSAGE
# route is the backstop for the two places where no code is available:
#   * build_grouped_view()'s "uncovered_hard_stop"/"uncovered_soft_stop" safety
#     net, which represents any final-list message that never went through
#     make_issue() at all;
#   * sqs_service.cross_validate()'s uncoded {type, message} dicts.
# It reads the SAME single table, so there is no second list to keep in sync.


def _legacy_message_resolution(message: str) -> Optional[dict]:
    """Resolution derived from a legacy stop's MESSAGE, for the paths that have
    no code. First matching phrase wins; None when nothing matches."""
    if not message:
        return None
    code, _cluster, _tier = classify_legacy(message, "soft_warning")
    res = _LEGACY_CODE_RESOLUTIONS.get(code) if code else None
    return _copy_resolution(res) if res else None


def _fallback_resolution(code: Optional[str], message: str) -> Optional[dict]:
    """Message-derived resolution, but ONLY for issues that are actually legacy
    field-level stops.

    Deliberately narrow. Before the legacy rules carried codes, the phrase table
    held 6 entries and a message fallback was harmless for every other source.
    It now holds every legacy rule, including short phrases like "FEIN" and
    "Effective date" - which appear verbatim inside cross-document conflict and
    low-OCR-confidence messages. Those families are resolved through the Data
    Consistency picker (see _CONFLICT_REVIEW_NOTE) and must NOT be handed a
    typed-value box by an accidental substring hit. Gating on the code keeps
    their behaviour byte-identical to before this change."""
    if code and not (
        code.startswith("legacy_")
        or code.startswith("uncovered_")
        or code == "cross_form_legacy"
    ):
        return None
    return _legacy_message_resolution(message)


def make_issue(
    code: str, severity: str, message: str, forms: Optional[List[str]] = None,
    cluster: Optional[str] = None, tier: Optional[str] = None,
    add_forms: Optional[List[str]] = None,
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
    # Prefer a code-keyed resolution (which now covers legacy stops too, since
    # they carry a real `legacy_*` code). The MESSAGE fallback only fires for
    # legacy/uncovered codes - see _fallback_resolution for why that gate is
    # load-bearing - so it can never override or collide with a cross-form,
    # tier-1 or source-conflict resolution.
    resolution = resolution_for(code) or _fallback_resolution(code, message)
    # UX-05: `add_forms` is decided per ISSUE (which forms are missing from THIS
    # package), never per code, so it cannot come from the registry lookup above
    # and MUST be threaded through by the caller mirroring a cross-form issue.
    # This is the layer that used to drop it: `build_structured_from_sources`
    # rebuilds every cross-form issue through here, so a resolution assembled in
    # `cross_form_validator._issue` reached the flat list and was silently lost
    # on the grouped one - the exact "fix the layer the screen reads" trap.
    if add_forms:
        resolution = dict(resolution or {"mode": "none"})
        resolution["add_forms"] = list(add_forms)
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "forms": list(forms or []),
        "cluster": cluster,
        "tier": tier,
        "resolution": resolution,
        # Owner 2026-09-03: an item that cannot move the score says so. Attached
        # here so every emitter gets it without changing a single rule body.
        "score_neutral": is_score_neutral(code),
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
        # Cluster-level resolution: the first member that carries one. Members of
        # a cluster share a domain (same cluster label), so their resolutions are
        # the same family; the cluster surfaces one so the panel can "Open" the
        # whole cluster, and each item still carries its own for per-row Open.
        _cluster_res = next(
            (m.get("resolution") for m in members if m.get("resolution")), None,
        )
        # ...but `add_forms` does NOT survive that borrow (UX-05). The borrowed
        # resolution can come from a member OTHER than the one whose message is
        # `primary_message`, which is harmless for a mode (the family is the
        # same) and actively wrong for a form: the cluster would print one
        # sentence and offer to generate a form a DIFFERENT sentence asked for.
        # Stripped rather than re-derived, so nothing that works today changes -
        # the per-row control below still carries each member's own.
        if _cluster_res and _cluster_res.get("add_forms") and (
            _cluster_res is not members[0].get("resolution")
        ):
            _cluster_res = {k: v for k, v in _cluster_res.items() if k != "add_forms"}
        clusters.append({
            "cluster": key,
            "issue_id": members[0].get("issue_id") or issue_id_for(members[0]["message"], forms),
            "primary_message": members[0]["message"],
            "count": len(members),
            "forms": forms,
            "items": members,
            "resolution": _cluster_res,
            # EVERY member, not any: a cluster carrying one scoring item cannot
            # tell the producer its score is untouched. A member that predates
            # the flag has no key and is read as scoring, which fails safe.
            "score_neutral": all(m.get("score_neutral") for m in members),
        })
    clusters.sort(key=_cluster_rank_key)
    return clusters


def build_grouped_view(
    structured_issues: List[dict],
    hard_stops: List[str],
    soft_stops: List[str],
    cross_issues: Optional[List[dict]] = None,
    promote_codes: Optional[List[str]] = None,
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

    `cross_issues` is the session's cross_form_validator output
    (``cross_issues_last``). Nothing ever copies those into the persisted
    ``structured_issues``, so pass them here or every cross-form issue falls
    into the uncoded safety net below and collapses into one "Other
    validations" bucket. Injecting them here rather than persisting them keeps
    a single source of truth and makes double-counting structurally impossible.

    `promote_codes` names issues that are HOLDING A SCORE AT 60 even though the
    engine that emitted them called them a warning. Owner rule, 2026-08-31: the
    card must match the cap. The package scorer can cap on a stop the display
    engines classify as a soft warning - the manufactured
    `property_building_value` conflict is the live case, since
    `extraction_pipeline` draws it as a warning when the package has no property
    coverage while `calculate_package_sqs` caps at 60 regardless - so the
    producer read "warning" while the score read "blocker".

    PROMOTES the existing card rather than adding a second one, deliberately:
    that row already carries the right wording, the right cluster and, crucially,
    the Resolve control that opens Data Consistency - the ONLY place a
    cross-document conflict can actually be cleared. A freshly-minted row would
    carry none of it. Nothing here changes a score; the caller's stop arrays are
    untouched.
    """
    hard_stops = hard_stops or []
    soft_stops = soft_stops or []
    _promote = {c for c in (promote_codes or []) if c}

    if cross_issues:
        _seen_msgs = {
            (i.get("message") or "").strip() for i in (structured_issues or [])
        }
        structured_issues = list(structured_issues or []) + [
            i for i in build_structured_from_sources(cross_issues=cross_issues)
            if (i.get("message") or "").strip() not in _seen_msgs
        ]

    # ── Cross-engine de-duplication (client review #4) ───────────────────────
    # Several rules are emitted by BOTH the legacy field-level engine (uncoded
    # strings) and cross_form_validator (coded, resolvable). When both are present
    # they cluster together and show as two near-identical bullets - only the
    # coded one carries "Open to fix". Hide the legacy twin so the problem shows
    # once, on the resolvable row. This only ever removes the legacy STRING from
    # the display: the coded issue is kept, and the raw hard_stops/soft_stops
    # lists that drive SQS capping (owned by the caller) are unaffected. Because
    # suppression is gated on the coded twin actually being present, a scenario
    # where only the legacy rule fired (its coded counterpart has a stricter
    # form-trigger gate) still shows the legacy row exactly as before - no blocker
    # is ever dropped.
    _present_codes = {(i.get("code") or "") for i in (structured_issues or [])} \
        | {(i.get("code") or "") for i in (cross_issues or [])}
    _suppress_phrases = tuple(
        phrase for code, phrase in _LEGACY_SUPERSEDED_BY_CODE.items()
        if code in _present_codes
    )
    if _suppress_phrases:
        _superseding_codes = set(_LEGACY_SUPERSEDED_BY_CODE.keys())

        def _is_suppressed_legacy(issue: dict) -> bool:
            # Never drop the coded keeper itself (its wording differs from the
            # legacy phrase anyway - this is belt-and-suspenders).
            if (issue.get("code") or "") in _superseding_codes:
                return False
            msg = issue.get("message") or ""
            return any(p in msg for p in _suppress_phrases)

        structured_issues = [
            i for i in (structured_issues or []) if not _is_suppressed_legacy(i)
        ]
        # Also drop the suppressed legacy strings from the local final-list copies
        # so the "uncovered" safety net below does not re-add them under the
        # default "Other validations" cluster. The coded twin's message uses
        # different wording and is NOT matched, so it survives here and stays
        # covered by its own structured issue.
        hard_stops = [m for m in hard_stops if not any(p in m for p in _suppress_phrases)]
        soft_stops = [m for m in soft_stops if not any(p in m for p in _suppress_phrases)]

    # ── THE PICKER SUPERSEDES check_doc_consistency's COPY (2026-08-23) ──────
    # Two engines compare the same eight identity/date fields, and both render.
    # LIVE RUN B: "DBA / trade name differs across documents: Orbin Roofing,
    # Orbin Electrical Services" sat directly above "DBA / Trade Name: documents
    # disagree (Orbin Roofing, Orbin Electrical Services)" in ONE cluster. Same
    # for Mailing Address - and the legacy copy printed all THREE address
    # spellings including the two the picker had correctly folded, so the older
    # row read exactly like the bug the folding fixed.
    #
    # The picker's row is strictly better: folded value groups, per-document
    # attribution, a conflict reason, a suggestion, and a control that actually
    # resolves it. So when it is present, its legacy twin is hidden.
    #
    # SAME CONTRACT AS THE BLOCK ABOVE: display only, gated on the superseding
    # issue actually being present, and the CALLER's hard_stops / soft_stops
    # lists are never mutated (only the local copies, so the "uncovered" safety
    # net below does not re-add a row we just hid). SQS caps, dismiss credit and
    # issue_id hashing all key off those arrays and are untouched.
    #
    # AND A BLOCKER CAN NEVER BE HIDDEN: a hard-stop twin is suppressed only
    # when the surviving picker issue is ALSO a hard stop. Today the two sets
    # agree exactly (underwriting_consistency.HARD_STOP_RECONCILABLE_KEYS is
    # {applicant_name, fein, effective_date, expiration_date}, which is precisely
    # the four fields check_doc_consistency hard-stops on), and both engines
    # downgrade the two date rules on a multi-contract package. This guard means
    # that if they ever drift, the failure is a duplicate row - not a 60 cap with
    # nothing on screen explaining it.
    _picker_severity: Dict[str, str] = {}
    for _i in list(structured_issues or []) + list(cross_issues or []):
        _fk = picker_fact_key(_i.get("code"))
        if _fk:
            _sev = _i.get("severity") or _i.get("type") or "soft_warning"
            # hard_stop wins if the same fact somehow carries two rows
            if _picker_severity.get(_fk) != "hard_stop":
                _picker_severity[_fk] = _sev
    if _picker_severity:
        def _superseded_by_picker(issue: dict) -> bool:
            fk = doc_conflict_fact_key(issue.get("code"))
            if not fk or fk not in _picker_severity:
                return False
            own = issue.get("severity") or issue.get("type") or "soft_warning"
            if own == "hard_stop" and _picker_severity[fk] != "hard_stop":
                return False          # never hide a blocker behind a warning
            return True

        _dup_msgs = {
            (i.get("message") or "").strip()
            for i in (structured_issues or []) if _superseded_by_picker(i)
        }
        # Never trim a string a SURVIVING issue also carries. The two engines
        # word their messages differently, so this cannot bite today - but if
        # they ever coincided, removing the shared string from the stop arrays
        # would make the survivor fail the `_present_in` severity lookup below
        # and silently downgrade a hard stop to a warning.
        _dup_msgs -= {
            (i.get("message") or "").strip()
            for i in (structured_issues or []) if not _superseded_by_picker(i)
        }
        if _dup_msgs:
            structured_issues = [
                i for i in (structured_issues or []) if not _superseded_by_picker(i)
            ]
            hard_stops = [m for m in hard_stops if m.strip() not in _dup_msgs]
            soft_stops = [m for m in soft_stops if m.strip() not in _dup_msgs]

    def _present_in(message: str, final_list: List[str]) -> bool:
        # Exact match covers the common case. Prefix match covers callers that
        # append a suffix to the original message (e.g. an "(Affects: ... Fix:
        # ...)" annotation added after this issue's message was captured) -
        # the original text is still the start of the final string, so a
        # downgrade/presence check must not require byte-for-byte equality.
        if message in final_list:
            return True
        return any(s.startswith(message) for s in final_list if message)

    # ── THE PICKER'S OWN ROW DOES NOT ALSO PRINT AS A WARNING (UI-13) ───────
    # Owner, 2026-09-09, on the client's UI-13: the same conflict was on the
    # review screen TWICE. Once in Data Consistency - each document's value,
    # the conflict reason, a suggestion and a Confirm that applies the value
    # across every form - and again, lower down, as a warning whose only
    # affordance ("Fix in Data Consistency") scrolled back up to that picker.
    # The picker is where it gets fixed, so the warning is removed.
    #
    # Suppressed by CODE, not by field name: `underwriting_reconciliation_*` IS
    # a picker row by construction (extraction_pipeline emits exactly one per
    # picker field carrying `review_required`), so a fact added to
    # RECONCILABLE_FIELDS is covered the day it ships and nothing here needs a
    # list to maintain. The doc-consistency twins of these rows are already
    # hidden by the supersession block above, so a conflict now prints in one
    # place instead of three.
    #
    # WARNINGS ONLY, and the call is made on the severity THIS view resolved
    # (promotion + the classify_stops downgrade), never on the severity the
    # emitter claimed:
    #   * a hard stop keeps its red row - the four HARD_STOP_RECONCILABLE_KEYS
    #     (applicant name, FEIN, both policy dates) block submission, and a
    #     blocker is never hidden behind a section the producer may have
    #     collapsed;
    #   * a `promote_codes` row keeps its card - it is what is holding a score
    #     at 60, and that card carries the only control that clears it.
    #
    # Display only. The caller's hard_stops / soft_stops are the SQS capping
    # inputs and are not mutated, so no cap, no dismiss credit and no issue_id
    # moves. `counts`, the tier badges and the "Important" preview are all
    # summed from what this function RENDERS, so they follow automatically.
    _picker_hidden_msgs: Set[str] = set()

    enriched: List[dict] = []
    for issue in structured_issues or []:
        code = issue.get("code") or "uncategorized"
        message = issue.get("message") or ""
        orig_severity = issue.get("severity") or issue.get("type") or "soft_warning"

        if code in _promote:
            # This issue is what is holding the score at 60. Whatever the
            # emitting engine called it, it renders as the blocker it is.
            severity = "hard_stop"
        elif orig_severity == "hard_stop":
            if _present_in(message, hard_stops):
                severity = "hard_stop"
            elif _present_in(message, soft_stops):
                severity = "soft_warning"  # downgraded by classify_stops
            else:
                severity = "hard_stop"
        else:
            severity = orig_severity

        # UI-13 (full reasoning in the note above `enriched`): this row is a
        # Data Consistency row and it is rendering as a warning - drop it, the
        # picker above already shows it with a control that fixes it.
        if severity != "hard_stop" and picker_fact_key(code):
            _picker_hidden_msgs.add(message.strip())
            continue

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
            "resolution": issue.get("resolution") or resolution_for(code)
                          or _fallback_resolution(code, message),
            # Re-derived from the CODE, never carried from the incoming dict.
            # Issues reach this view from several sources (persisted sessions,
            # the legacy string arrays, the cross-form mirror) and only some of
            # them went through `make_issue`, so trusting the inbound key would
            # make the note depend on which door an issue happened to arrive
            # through. The code is the same in every one of them.
            "score_neutral": is_score_neutral(code),
        })

    # A hidden picker row's sentence is still in the caller's soft_stops, and the
    # safety net below re-adds any message it cannot find in `enriched` - which
    # would reprint the row we just hid under "Other validations". Drop it from
    # the LOCAL copy only, exactly as the two supersession blocks above do.
    _picker_hidden_msgs -= {(i["message"] or "").strip() for i in enriched}
    if _picker_hidden_msgs:
        def _is_hidden_picker_message(s: str) -> bool:
            # Bidirectional prefix, mirroring `_covered_by` below: a caller may
            # append an "(Affects: ... Fix: ...)" annotation to the sentence
            # this issue was created with, so equality is not enough.
            t = (s or "").strip()
            if not t:
                return False
            return any(t == m or t.startswith(m) or m.startswith(t)
                       for m in _picker_hidden_msgs)

        # hard_stops is deliberately NOT filtered: a picker sentence sitting in
        # the blocking array while this view called it a warning would mean the
        # two disagree, and the right failure there is a visible row, not a
        # silent one.
        soft_stops = [m for m in soft_stops if not _is_hidden_picker_message(m)]

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
                "resolution": _legacy_message_resolution(_msg),
            })
    for _msg in soft_stops:
        if not _covered_by(_msg):
            enriched.append({
                "code": "uncovered_soft_stop", "issue_id": issue_id_for(_msg, []),
                "message": _msg, "forms": [], "field": None, "source_fact": None,
                "severity": "soft_warning", "cluster": DEFAULT_CLUSTER, "tier": DEFAULT_TIER,
                "resolution": _legacy_message_resolution(_msg),
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

    # ── Headline counts (Workstream 6 §9.1) ──────────────────────────────────
    # THE number of issues for the completion notification and the next-step
    # banner. Derived from what this function actually RENDERED, never from the
    # raw hard_stops/soft_stops the caller passed in. Those arrays are the SQS
    # capping inputs, and three separate things make len() on them the wrong
    # headline - two of which under-report and one of which over-reports:
    #
    #   * ADVISORY cross-form issues reach the display through structured_issues
    #     (extraction_pipeline mirrors EVERY cross-form issue into it, whatever
    #     its type) but split_cross_form_issues routes advisories to a third
    #     list that nothing merges into soft_stops. Reported by the client: the
    #     toast read "1 warning found" beneath three rendered warning cards.
    #   * `cross_issues` injected above (the /extraction-result reload path) are
    #     rendered here and are likewise absent from the caller's arrays.
    #   * the legacy duplicate suppression above HIDES a message the arrays
    #     still carry, so len() counts one problem twice.
    #
    # Counted in the same unit the screen prints - cluster["count"], i.e. items,
    # which is exactly what each tier header badge sums. `important` is
    # deliberately NOT counted: it is an echo of the top 3 clusters that are
    # already counted in `warnings` below, so adding it would double-count.
    counts = {
        "hard_stops": sum(c["count"] for c in hard_clusters),
        "warnings":   sum(c["count"] for tier_clusters in warnings.values()
                          for c in tier_clusters),
    }

    return {
        "important": important,
        "hard_stops": hard_clusters,
        "warnings": warnings,
        "tier_labels": TIER_LABELS,
        "counts": counts,
    }


def normalize_issue_type(issue_type: Optional[str]) -> str:
    """Canonicalize an issue's severity string.

    Two producers disagree on the spelling of a non-blocking issue:
    cross_form_validator emits "soft_warning", while the older
    sqs_service.cross_validate() emits "warning". Anything that filters on
    severity must treat them as the same thing - a mismatch here silently drops
    every legacy issue on the floor rather than failing loudly.
    """
    t = (issue_type or "soft_warning").strip()
    return "soft_warning" if t == "warning" else t


def build_structured_from_sources(
    legacy_hard: Optional[List[str]] = None,
    legacy_soft: Optional[List[str]] = None,
    cross_issues: Optional[List[dict]] = None,
    include_advisories: bool = False,
) -> List[dict]:
    """Build structured issues from the two RAW stop sources, keeping each one
    tagged the way its own source allows.

    Mirrors what extraction_pipeline._finalize_pipeline does inline, with one
    addition: cross_form_validator issues are included here. They carry a real
    ``code``, so they cluster through CLUSTER_MAP instead of falling into
    build_grouped_view's uncoded safety net (which would collapse every one of
    them into the single "Other validations" bucket).

    Pass the sources SEPARATELY - i.e. ``legacy_hard`` must be evaluate_stops()'
    own output, NOT the combined ``evaluate_stops + cross_form`` list. Passing
    the combined list would classify each cross-form message twice (once by
    code, once by legacy phrase match).

    Advisory-severity cross-form issues are skipped by default: they are never
    added to hard_stops/soft_stops, so counting them would report problems the
    caller is not actually surfacing. Set `include_advisories` when building a
    view that DISPLAYS the raw cross-form list, which does carry them - the
    editor's Cross-Form Validation panel shows advisories such as
    `auto_um_uim_not_specified` and `acord101_required`, and dropping them would
    silently lose rows the flat list used to show.
    """
    structured: List[dict] = []
    _allowed = ("hard_stop", "soft_warning", "advisory") if include_advisories \
        else ("hard_stop", "soft_warning")

    # Coded cross-form issues first, so a cluster that also collects a legacy
    # message uses the coded entry as its primary_message.
    for iss in cross_issues or []:
        if not isinstance(iss, dict):
            continue
        itype = normalize_issue_type(iss.get("type"))
        if itype not in _allowed:
            continue
        message = iss.get("message") or ""
        code = iss.get("code")
        if code:
            structured.append(make_issue(
                code, itype, message, forms=iss.get("forms") or [],
                # UX-05: carry the per-issue "which form is missing" decision
                # made in cross_form_validator. make_issue re-derives the
                # resolution from `code`, which knows nothing about THIS
                # package, so without this the grouped view loses the Add-form
                # affordance the flat list has.
                add_forms=(iss.get("resolution") or {}).get("add_forms"),
            ))
        else:
            # sqs_service.cross_validate() predates rule codes and returns bare
            # {type, message} dicts. Classify by message text, exactly like the
            # legacy field-level stops below, so an uncoded issue can still reach
            # a real cluster instead of defaulting into "Other validations".
            _cluster, _tier = classify_legacy_message(message, itype)
            structured.append(make_issue(
                "cross_form_legacy", itype, message,
                forms=iss.get("forms") or [], cluster=_cluster, tier=_tier,
            ))

    # Real rule codes, not the old throwaway index (`legacy_hard_<i>`), so
    # resolution_for() can find each rule's fix mode. The index form is kept only
    # as the fallback for a message no rule matches - it must stay unique per
    # message so two unclassified stops never collapse into one code.
    for _i, _msg in enumerate(legacy_hard or []):
        _code, _cluster, _tier = classify_legacy(_msg, "hard_stop")
        structured.append(make_issue(
            _code or f"legacy_hard_{_i}", "hard_stop", _msg, cluster=_cluster, tier=_tier,
        ))
    for _i, _msg in enumerate(legacy_soft or []):
        _code, _cluster, _tier = classify_legacy(_msg, "soft_warning")
        structured.append(make_issue(
            _code or f"legacy_soft_{_i}", "soft_warning", _msg, cluster=_cluster, tier=_tier,
        ))
    return structured


def count_distinct_issues(
    hard_stops: List[str],
    soft_stops: List[str],
    legacy_hard: Optional[List[str]] = None,
    legacy_soft: Optional[List[str]] = None,
    cross_issues: Optional[List[dict]] = None,
) -> Dict[str, int]:
    """Count DISTINCT remaining problems rather than raw message strings.

    Two engines routinely report the SAME underlying deficiency in different
    words - e.g. a property submission with incomplete COPE produces both
    "Property Minimum Viable COPE incomplete - missing: ..." (sqs_service
    .evaluate_stops) and "Property submission missing Minimum Viable COPE: ..."
    (cross_form_validator). ``len(hard_stops)`` counts that one problem twice.
    Both classify into the same cluster, so counting clusters reports it once,
    which is also what the producer sees on screen (one card per cluster).

    Read-only and purely additive: it never mutates or re-orders the stop
    lists, and nothing about scoring, capping or dismiss-credit consults it.
    """
    structured = build_structured_from_sources(legacy_hard, legacy_soft, cross_issues)
    grouped = build_grouped_view(structured, hard_stops or [], soft_stops or [])
    return {
        "hard": len(grouped["hard_stops"]),
        "soft": sum(len(clusters) for clusters in grouped["warnings"].values()),
    }


# ── Post-remediation diff (Figure 24) ────────────────────────────────────────
#
# The diff runs at CLUSTER level, deliberately, not per raw message. Legacy
# stop strings embed their own dynamic detail ("...missing: locations,
# occupancy type"), so a client fixing ONE of several missing fields rewrites
# the message, which at message level reads as "one issue resolved + one brand
# new issue" when the truth is "same issue, still open, now smaller". The
# cluster label is stable across that, and it is also exactly what the producer
# sees on screen (one card per cluster), so a "3 resolved" badge always agrees
# with the cards printed beneath it.

# Structured-issue codes that a recalculation regenerates from scratch. Issues
# from any OTHER source (doc conflicts, source conflicts, OCR confidence,
# Tier-1 gaps) are preserved untouched, because recalculate_session_scores does
# not re-run those detectors and therefore cannot know whether they cleared.
#
# Must stay in sync with what evaluate_stops()-sourced issues are actually coded
# as. It was ("legacy_hard_", "legacy_soft_") - the throwaway INDEX codes - and
# had to widen to the shared "legacy_" prefix when those stops gained real rule
# codes (2026-08-08). Left un-widened, a resolved stop would never be swapped
# out and the producer would keep seeing a blocker that is already gone, which
# is the exact failure this function exists to prevent. The wider prefix still
# matches the old index codes, so sessions persisted before that change keep
# recalculating correctly. No cross-form / doc-conflict / OCR / tier-1 code
# begins with "legacy_" (guarded by test_legacy_rules.py).
_RECOMPUTED_CODE_PREFIXES = ("legacy_",)


def replace_recomputed_issues(
    persisted: Optional[List[dict]], fresh: Optional[List[dict]],
) -> List[dict]:
    """Swap the structured issues a recalculation regenerates, keep the rest.

    Without this, ``structured_issues`` keeps its extraction-time contents
    forever: a hard stop the client actually resolved stays in the list, and
    build_grouped_view's "not in either final list" branch keeps it at
    hard_stop severity, so the producer goes on seeing a blocker that is gone.
    """
    kept = [
        i for i in (persisted or [])
        if not str(i.get("code") or "").startswith(_RECOMPUTED_CODE_PREFIXES)
    ]
    return kept + list(fresh or [])


# extraction_pipeline emits one of these per critical field the OCR read with
# low confidence, coded ocr_low_confidence_<fact_key> (the suffix is a canonical
# fact key - see extraction_service._annotate_facts, which appends `k` itself).
_OCR_ISSUE_PREFIX = "ocr_low_confidence_"


def _is_human_supplied(fact: Any) -> bool:
    """True when a person, not the extractor, is the source of this value.

    Same test recalculate_session_scores uses to decide whether a field was
    user-provided, kept identical on purpose so the two never disagree about
    what counts as human input.
    """
    if not isinstance(fact, dict):
        return False
    return (
        fact.get("source") in ("client_arq", "producer")
        or fact.get("confidence") == "client_arq"
    )


def drop_confirmed_ocr_issues(
    issues: Optional[List[dict]],
    facts: Optional[dict] = None,
    confirmed_keys=None,
) -> List[dict]:
    """Drop "confirm this field" OCR warnings for fields a human has since given.

    These issues are preserved across a recalculation because nothing re-runs
    OCR. But unlike the other preserved sources (doc/source conflicts, which
    describe two DOCUMENTS disagreeing and cannot be settled by an answer), an
    OCR-confidence warning asks for exactly one thing: a human to confirm the
    value. The questionnaire asks the client for precisely these fields, so once
    they answer, the warning is satisfied and must stop being reported as open.

    Fail-safe by construction: an issue is dropped ONLY when its code resolves
    to a fact key that is now human-supplied (or explicitly confirmed via the
    Data Consistency picker). Anything unrecognised is kept, so the worst case
    is the previous behaviour.
    """
    facts = facts or {}
    confirmed = set(confirmed_keys or ())
    out: List[dict] = []
    for issue in issues or []:
        code = str(issue.get("code") or "")
        if code.startswith(_OCR_ISSUE_PREFIX):
            field = code[len(_OCR_ISSUE_PREFIX):]
            if field and (field in confirmed or _is_human_supplied(facts.get(field))):
                continue
        out.append(issue)
    return out


def index_clusters(grouped: dict) -> Dict[str, dict]:
    """Flatten a grouped view to {cluster_label: cluster}, hard stops winning.

    A cluster can hold both a hard stop and a warning (two engines reporting
    the same area at different severities); the hard stop is the one that
    governs, so it must not be overwritten by the warning entry.
    """
    index: Dict[str, dict] = {}
    for c in grouped.get("hard_stops") or []:
        index[c["cluster"]] = {**c, "severity": "hard_stop", "tier": "required"}
    for tier, clusters in (grouped.get("warnings") or {}).items():
        for c in clusters:
            if c["cluster"] in index:
                continue
            index[c["cluster"]] = {**c, "severity": "soft_warning", "tier": tier}
    return index


def _slim_cluster(c: dict) -> dict:
    """Trim a cluster to what the producer UI renders (drops `items`)."""
    return {
        "cluster":  c.get("cluster"),
        "issue_id": c.get("issue_id"),
        "message":  c.get("primary_message"),
        "severity": c.get("severity"),
        "tier":     c.get("tier"),
        "forms":    c.get("forms") or [],
        "count":    c.get("count", 1),
    }


def _cluster_issue_ids(cluster: dict) -> set:
    """The durable ids of the individual issues inside a cluster.

    issue_id is derived from the message text, so when a client fills in SOME of
    a rule's missing fields the rule re-emits a shorter message and its id
    changes. That id change is the only machine-readable trace that partial
    progress happened.
    """
    return {
        it.get("issue_id") for it in (cluster.get("items") or [])
        if isinstance(it, dict) and it.get("issue_id")
    }


def diff_grouped_views(prior: dict, current: dict) -> dict:
    """Compare two grouped views: what the client's answers fixed, broke, and left.

    `worsened` is the "which got worse" signal: an area that was only a warning
    before and is a hard stop now (e.g. answering "yes, we have prior losses"
    turns an advisory into a blocker). An area that stays a hard stop is NOT
    worsened, it is simply still open.

    `updated` is partial progress: the cluster is still open, but what it
    contains changed - typically a rule that listed three missing fields now
    lists one. Without it a client who answered several questions but did not
    fully clear any single rule shows up as "0 resolved", which reads as "the
    questionnaire achieved nothing" when the opposite is true. It is
    deliberately labelled "updated" and not "improved": a message can change
    because a gap shrank OR because a new problem joined the same cluster, and
    the two are not distinguishable from the text alone. Claiming improvement we
    cannot prove is exactly the kind of overstatement this codebase avoids.

    `worsened` and `updated` are disjoint, and both are subsets of `still_open`.
    """
    prior_idx   = index_clusters(prior or {})
    current_idx = index_clusters(current or {})

    resolved, newly, updated, worsened, still_open = [], [], [], [], []

    def _entry(cluster: dict, changed: int) -> dict:
        # `changed` is how many individual issues moved, which is NOT the
        # cluster's total size. Showing the total next to "updated" implies more
        # changed than actually did.
        return {**_slim_cluster(cluster), "changed": changed}

    def _size(cluster: dict) -> int:
        return len(_cluster_issue_ids(cluster)) or int(cluster.get("count") or 1)

    # A cluster that vanished entirely: every issue in it was cleared.
    for k in prior_idx:
        if k not in current_idx:
            resolved.append(_entry(prior_idx[k], _size(prior_idx[k])))

    for k in current_idx:
        cur = current_idx[k]
        if k not in prior_idx:
            newly.append(_entry(cur, _size(cur)))
            continue

        pri = prior_idx[k]
        still_open.append(_slim_cluster(cur))

        # Escalation is the headline for this cluster; do not also describe the
        # underlying text churn that came with it.
        if pri["severity"] != "hard_stop" and cur["severity"] == "hard_stop":
            worsened.append(_slim_cluster(cur))
            continue

        gone     = _cluster_issue_ids(pri) - _cluster_issue_ids(cur)
        appeared = _cluster_issue_ids(cur) - _cluster_issue_ids(pri)

        if gone and appeared:
            # Churn: a rule re-emitted with different text (typically because
            # the client filled in some, not all, of its missing fields). This
            # is the case that must NOT read as "resolved + new".
            updated.append(_entry(cur, max(len(gone), len(appeared))))
        elif gone:
            # Issues genuinely cleared, even though other issues keep the
            # cluster open. The producer can see these disappear, so calling
            # them anything other than resolved contradicts the screen.
            resolved.append(_entry(pri, len(gone)))
        elif appeared:
            newly.append(_entry(cur, len(appeared)))

    return {
        "resolved":         resolved,
        "new":              newly,
        "worsened":         worsened,
        "updated":          updated,
        "still_open":       still_open,
        # resolved / new / updated count ISSUES (what the producer sees appear
        # and disappear); still_open counts AREAS, which is why the UI labels it
        # differently.
        "resolved_count":   sum(e["changed"] for e in resolved),
        "new_count":        sum(e["changed"] for e in newly),
        "updated_count":    sum(e["changed"] for e in updated),
        "worsened_count":   len(worsened),
        "still_open_count": len(still_open),
    }
