"""
Alias-based deterministic form-field stamping (Pass 1.5).

This module loads the per-form alias maps from ``forms_aliases/`` once at
import time and exposes ``stamp_form_fields`` — a pure-Python lookup that
takes ACORD form field names, resolves their canonical fact name from the
alias map, then resolves that canonical to a key in the extraction facts
dict via the bridge table, and returns whatever values it finds.

Design constraints:
  - **No LLM call.** This module is deterministic dictionary lookup.
  - **No side effects on the existing pipeline.** It is called from
    ``map_facts_to_form`` *between* Pass 1 (`_ACORD_FIELD_RULES`) and
    Pass 2 (`_fill_unmatched_with_gpt`) and only on fields Pass 1 missed.
  - **Gated by ``settings.ENABLE_ALIAS_STAMPING``.** When disabled, the
    caller never imports this module's stamping path, so behavior is
    identical to the prior pipeline.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from config.settings import FORMS_ALIASES_DIR
from services.extraction_service import _fv

logger = logging.getLogger(__name__)


# ── Bridge: canonical fact name (from alias maps) → extraction fact key ──────
#
# The extraction service produces facts with snake_case keys defined in
# ``extraction_service._EXTRACT_SCHEMA`` (e.g. ``producer_name``, ``fein``).
# The alias maps map ACORD form fields to canonical fact names derived from
# the ACORD field name itself (e.g. ``producer_full_name``,
# ``named_insured_naics_code``). This bridge connects the two.
#
# Adding entries here expands the deterministic stamping coverage. Each entry
# is conservative: it must reflect the same semantic mapping the existing
# ``_ACORD_FIELD_RULES`` would use for the equivalent field. When in doubt,
# leave it out — unbridged canonicals fall through to GPT as before.
CANONICAL_TO_EXTRACTION: Dict[str, str] = {
    # ── Producer ────────────────────────────────────────────────────────────
    "producer_full_name":                         "producer_name",
    # producer_customer_identifier intentionally omitted — it is an agency-assigned
    # account NUMBER, not the agency name; mapping it to producer_name produces
    # hallucinated-looking output (e.g. "RSG Specialty Atlanta Binding").
    #
    # These three MUST point at the PRODUCER-scoped facts, mirroring the Pass-1
    # rules for the same fields. They previously pointed at contact_* — the
    # APPLICANT's contact person — so whenever the producer facts were absent
    # (the common case) this pass stamped the applicant's name/phone/email into
    # the Producer block as a trusted value: the exact entity-mixing defect
    # Pass 1 was fixed for on 2026-08-09, resurrected one pass later. When the
    # producer fact is absent the field now falls through to gap fill, which
    # reads the producer's own labelled block from the document.
    "producer_contact_person_full_name":          "producer_contact_name",
    "producer_contact_person_phone_number":       "producer_contact_phone",
    "producer_contact_person_email_address":      "producer_contact_email",

    # ── Insurer / carrier ──────────────────────────────────────────────────
    "insurer_full_name":                          "carrier_name",
    "insurer_naic_code":                          "carrier_naic",

    # ── Named insured ──────────────────────────────────────────────────────
    "named_insured_full_name":                    "applicant_name",
    "named_insured_contact_full_name":            "contact_name",
    "named_insured_contact_primary_phone_number": "contact_phone",
    "named_insured_contact_primary_email_address": "contact_email",
    # A DATE box ("Enter date: The date the applicant began in business").
    # Previously bridged to years_in_business — a COUNT — so when the date fact
    # was absent this pass stamped a bare duration ("15") into a date field.
    # Same reasoning as the Pass-1 rule for NamedInsured_BusinessStartDate.
    "named_insured_business_start_date":          "business_start_date",
    "named_insured_naics_code":                   "naics_code",
    "named_insured_sic_code":                     "sic_code",

    # ── Policy ─────────────────────────────────────────────────────────────
    "policy_number_identifier":                   "policy_number",
    "policy_effective_date":                      "effective_date",
    "policy_expiration_date":                     "expiration_date",

    # ── Business information ───────────────────────────────────────────────
    "business_information_naics_code":            "naics_code",
    "business_information_sic_code":              "sic_code",
    "business_information_employee_count":        "num_employees",
    "business_information_full_time_employee_count": "num_employees",
    "business_information_total_payroll_amount":  "total_payroll",
    "business_information_annual_gross_receipts_amount": "total_revenue",
    "business_information_operations_description": "operations_description",

    # ── Per-line policy identifiers / dates ────────────────────────────────
    # ACORD 25 (Certificate of Liability) repeats policy_number / effective /
    # expiration once per line of coverage. When the document only exposes a
    # single policy, the same value applies to every line — substring-only
    # Pass 1 can't bridge these because the field name buries "PolicyNumber"
    # under a coverage-line prefix.
    "policy_general_liability_policy_number_identifier":   "policy_number",
    "policy_general_liability_effective_date":             "effective_date",
    "policy_general_liability_expiration_date":            "expiration_date",
    "policy_automobile_liability_policy_number_identifier": "policy_number",
    "policy_automobile_liability_effective_date":          "effective_date",
    "policy_automobile_liability_expiration_date":         "expiration_date",
    # policy_excess_liability_policy_number_identifier is DELIBERATELY absent
    # here (unlike its GL/Auto siblings above): a real ACORD 25 certificate
    # commonly lists the excess/umbrella line with its OWN distinct policy
    # number (confirmed on a live multi-carrier test certificate - GL, Auto,
    # WC, and Excess each had their own policy number), so the "single policy
    # -> same value on every line" assumption this block otherwise makes does
    # NOT hold for Excess. Bridging it here silently duplicated the GL policy
    # number onto the Excess row (confirmed live: same 'GL-4471029-25' on
    # both). Left OUT of the bridge -> falls through to gap-fill, which
    # already reads the real, distinct excess/umbrella policy number from raw
    # text (same mechanism proven for the excess/umbrella policy PERIOD via
    # pdf_service._fetch_umbrella_period and the Policy_ExcessLiability_
    # EffectiveDate_A/ExpirationDate_A override).
    "policy_excess_liability_effective_date":              "effective_date",
    "policy_excess_liability_expiration_date":             "expiration_date",

    # ── General Liability limits ───────────────────────────────────────────
    # Each of these has a matching extraction fact key, but Pass 1's substring
    # rules don't recognise the ACORD canonical form. Bridging eliminates the
    # GPT round-trip for these high-volume CGL fields.
    "general_liability_each_occurrence_limit_amount":                          "gl_each_occurrence",
    "general_liability_general_aggregate_limit_amount":                        "gl_aggregate",
    "general_liability_products_and_completed_operations_aggregate_limit_amount": "gl_products_aggregate",
    "general_liability_personal_and_advertising_injury_limit_amount":          "gl_personal_advertising_injury",
    "general_liability_fire_damage_rented_premises_each_occurrence_limit_amount": "gl_fire_damage_limit",
    "general_liability_medical_expense_each_person_limit_amount":              "gl_medical_expense",
    "general_liability_claims_made_retroactive_date":                          "retro_date",

    # ── Workers Compensation — Employers' Liability limits ─────────────────
    "workers_compensation_employers_liability_employers_liability_each_accident_limit_amount":       "wc_el_each_accident",
    "workers_compensation_employers_liability_employers_liability_disease_each_employee_limit_amount": "wc_el_disease_each_employee",
    "workers_compensation_employers_liability_employers_liability_disease_policy_limit_amount":      "wc_el_disease_policy_limit",

    # ── Umbrella / Excess ──────────────────────────────────────────────────
    # FACT_REGISTRY has a single umbrella_limit fact; both each-occurrence and
    # aggregate ACORD fields receive it. If the carrier splits the two on the
    # document, extraction picks one; the same value flows to both ACORD slots
    # (matches typical carrier issuance where the two are equal).
    "excess_umbrella_umbrella_each_occurrence_amount":  "umbrella_limit",
    "excess_umbrella_umbrella_aggregate_amount":        "umbrella_limit",
}


# ── Per-form alias maps (loaded once at import) ──────────────────────────────

_ALIAS_MAPS: Dict[str, Dict[str, str]] = {}
_LOADED = False


def _load_all_alias_maps() -> None:
    """
    Load every ``ACORD_*_alias.json`` from ``FORMS_ALIASES_DIR`` exactly once.
    Idempotent and safe to call multiple times.
    """
    global _LOADED
    if _LOADED:
        return

    aliases_dir = Path(FORMS_ALIASES_DIR)
    if not aliases_dir.is_dir():
        logger.warning(
            "alias_stamper: forms_aliases dir not found at %s — stamping disabled",
            aliases_dir,
        )
        _LOADED = True
        return

    count = 0
    for path in sorted(aliases_dir.glob("ACORD_*_alias.json")):
        form_id = path.stem.replace("_alias", "")
        try:
            _ALIAS_MAPS[form_id] = json.loads(path.read_text(encoding="utf-8"))
            count += 1
        except Exception as exc:                # noqa: BLE001 — log & continue
            logger.warning("alias_stamper: failed to load %s — %s", path.name, exc)

    _LOADED = True
    logger.info("alias_stamper: loaded %d alias maps from %s", count, aliases_dir)


# Eagerly load at import so the first request doesn't pay disk I/O.
_load_all_alias_maps()


# ── Value-shape helper ───────────────────────────────────────────────────────

def _coerce_value(raw) -> Optional[str]:
    """
    Normalise a fact value into a string suitable for the ``mapped`` dict.
    Mirrors the shape produced by ``_deterministic_map`` so downstream code
    (confidence assignment, fill_pdf) sees the same value shape it always has.
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        # Boolean facts are not stamped by this module — they belong in the
        # indicator-derivation path. Returning None keeps them on Pass 2.
        return None
    if isinstance(raw, list):
        if not raw:
            return None
        first = raw[0]
        return str(first).strip() if first is not None else None
    if isinstance(raw, dict):
        # Already unwrapped by _fv, but defensive: a dict with no "value"
        # is structured data we shouldn't flatten.
        inner = raw.get("value")
        return str(inner).strip() if inner is not None else None
    s = str(raw).strip()
    return s or None


# ── Public API ───────────────────────────────────────────────────────────────

def stamp_form_fields(
    form_id: str,
    facts: dict,
    target_fields: Iterable[str],
) -> Dict[str, str]:
    """
    Return ``{field_name: value}`` for any ``target_fields`` that can be
    deterministically filled by the alias map + extraction-key bridge.

    Fields whose canonical name has no bridge entry, or whose bridged
    extraction key is absent / empty in ``facts``, are simply omitted from
    the result — the caller leaves them in the unmatched set for Pass 2.

    Parameters
    ----------
    form_id : str
        ACORD form identifier, e.g. ``"ACORD_125"``.
    facts : dict
        The extracted-facts dictionary, same shape ``_deterministic_map`` sees.
    target_fields : Iterable[str]
        ACORD field names that Pass 1 left unfilled.

    Returns
    -------
    Dict[str, str]
        Subset of ``target_fields`` that were filled by alias lookup.
    """
    alias_map = _ALIAS_MAPS.get(form_id)
    if not alias_map:
        return {}

    filled: Dict[str, str] = {}
    for field in target_fields:
        canonical = alias_map.get(field)
        if not canonical:
            continue

        extraction_key = CANONICAL_TO_EXTRACTION.get(canonical)
        if not extraction_key:
            continue

        raw = _fv(facts, extraction_key)
        value = _coerce_value(raw)
        if value is None:
            continue

        filled[field] = value

    return filled


def alias_maps_loaded() -> int:
    """Diagnostic: number of forms with a loaded alias map."""
    return len(_ALIAS_MAPS)


def bridge_size() -> int:
    """Diagnostic: number of canonical→extraction bridge entries."""
    return len(CANONICAL_TO_EXTRACTION)
