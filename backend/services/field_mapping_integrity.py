"""field_mapping_integrity.py

Field-mapping integrity guard (Figure 33 client feedback).

The client flagged a specific, high-risk mapping bug on the auto forms: carrier
names ("EMCASCO Insurance Company", "Employers Mutual Casualty Company") were
being pulled into vehicle OWNER-name boxes, and asked that auto ownership, HNOA,
leasing, hazardous-materials and vehicle-maintenance questions be treated as
HIGH-IMPACT and never "inferred loosely" - plus, most importantly:

    "Block download if carrier/policy data is mapped into insured/owner fields."

This module is the generic, form-agnostic engine behind both asks. It has two
PURE responsibilities (no DB, no I/O, no network - easy to unit-test):

1. CLASSIFY high-impact fields (:func:`is_high_impact_field`). ``field_qa`` uses
   this to surface a loosely-inferred high-impact field individually in the
   pre-download review instead of rolling it into the generic summary.

2. DETECT contamination (:func:`detect_field_mapping_contamination`) - a
   carrier/policy value stamped into an insured/owner field. The download route
   calls this and refuses to serve the package (HTTP 409) while any finding is
   unresolved. The producer resolves it by correcting the field (the existing
   field-edit flow), after which detection passes and the download proceeds.

Design notes
------------
* Comparison uses the SHARED normalizer (services.normalization.normalize_value /
  normalize_carrier / normalize_name), so a formatting-only difference is never a
  match - only a genuine one is. This is the same equivalence used everywhere
  else, so behaviour is consistent with the cross-document detectors.
* GENERIC - the field roles are inferred from the ACORD field-NAME shape, so the
  guard applies uniformly across all 17 forms, not just the ACORD 127 example.
* PRECISE - an insured field that correctly holds the applicant name is exempt
  even if that name happens to look carrier-ish, so a real insured is never
  flagged. A finding fires only when the value is carrier/policy data that does
  NOT belong in that slot.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from services.normalization import normalize_carrier, normalize_name

logger = logging.getLogger(__name__)

FIELD_MAPPING_INTEGRITY_MODEL_VERSION = "1.0.0"

# Extraction fact keys that hold CARRIER names. A value equal (after
# normalization) to one of these must never sit in an insured/owner field.
_CARRIER_FACT_KEYS = ("carrier_name", "prior_carrier", "current_carrier")

# Extraction fact keys that hold POLICY identifiers.
_POLICY_FACT_KEYS = ("policy_number", "prior_policy_number")

# A stamped value is treated as a plausible policy-number match only when it is
# reasonably distinctive, so a short coincidental token can never manufacture a
# false block.
_MIN_POLICY_TOKEN_LEN = 5

# Carrier-defining words + a company/entity token = a value SHAPED like a carrier
# name, caught even when no extracted carrier fact matches it (the Figure 33
# owner boxes held raw carrier strings the LLM read straight from the document).
_CARRIER_WORD_RX = re.compile(
    r"\b(insurance|casualty|mutual|indemnity|assurance|reinsurance|underwriters|surety)\b",
    re.IGNORECASE,
)
_COMPANY_WORD_RX = re.compile(
    r"\b(co|company|companies|corp|corporation|inc|incorporated|group|ins)\b",
    re.IGNORECASE,
)


# ── Value helpers ─────────────────────────────────────────────────────────────

def _fv(facts: dict, key: str):
    """Scalar fact value, unwrapping the {value, confidence} envelope."""
    if not isinstance(facts, dict):
        return None
    v = facts.get(key)
    if isinstance(v, dict) and "value" in v:
        v = v["value"]
    if v is None or (isinstance(v, str) and v.strip().lower() in ("", "null", "none")):
        return None
    return v


def _has_value(v: Any) -> bool:
    return v is not None and str(v).strip() not in ("", "null", "None")


def _policy_token(value: Any) -> str:
    """Comparison token for a policy identifier: alphanumeric, upper-cased."""
    return re.sub(r"[^A-Za-z0-9]+", "", str(value or "")).upper()


def _humanize_field(field: str) -> str:
    """Light humanization of an ACORD field name for a review message."""
    base = field or ""
    if len(base) > 2 and base[-2] == "_" and base[-1].isalpha():
        base = base[:-2]          # drop a trailing row letter (_A/_B/...)
    return base.replace("_", " ").strip()


def _form_label(form_id: str) -> str:
    return (form_id or "").replace("ACORD_", "ACORD ")


# ── Field-role classification (from the field NAME shape) ─────────────────────

# Name-bearing suffixes: the field holds the NAME of an entity (not an address,
# city, phone, code, ...). Used to keep address/city/contact sub-fields out of
# the insured/owner identity role even though they contain the word "name".
_NAME_SUFFIX_TOKENS = ("fullname", "dbaname", "tradename", "businessname")

# Address / contact / code markers that disqualify a field from being an
# insured/owner NAME field even if it contains "name" (e.g. CityName).
_NON_IDENTITY_MARKERS = (
    "address", "city", "state", "postal", "zip", "phone", "fax", "email",
    "website", "naic", "fein", "taxid", "code", "date", "indicator",
)


def _fl(field_name: Optional[str]) -> str:
    return (field_name or "").lower()


def is_insured_owner_field(field_name: Optional[str]) -> bool:
    """True when the field is meant to hold the INSURED or an OWNER's NAME.

    These are the slots the client said must never receive carrier/policy data.
    Recognized generically from the field-name shape so it covers every form:
      * the named insured / applicant / insured name,
      * an explicit vehicle/business OWNER name,
      * an additional-interest name (the ACORD 127 "Name of Other Owner" boxes).

    Address, city, contact and code sub-fields are excluded even when their name
    contains "name" (e.g. ``...MailingAddress_CityName``).
    """
    fl = _fl(field_name)
    if not fl:
        return False
    if any(m in fl for m in _NON_IDENTITY_MARKERS):
        return False
    if not any(tok in fl for tok in _NAME_SUFFIX_TOKENS):
        return False
    # "insurer" is the CARRIER field - never treat it as an insured/owner slot.
    if "insurer" in fl and "insured" not in fl:
        return False
    return (
        "namedinsured" in fl
        or "insured" in fl
        or "applicant" in fl
        or "owner" in fl
        or "additionalinterest" in fl
    )


def is_insured_identity_field(field_name: Optional[str]) -> bool:
    """True for the NAMED INSURED / applicant slot specifically (a subset of
    :func:`is_insured_owner_field`). Used to exempt a field that correctly holds
    the applicant name from the carrier-shape heuristic."""
    fl = _fl(field_name)
    if not is_insured_owner_field(field_name):
        return False
    return "namedinsured" in fl or "applicant" in fl or "insured" in fl


# High-impact auto / underwriting questions the client named (Figure 33): auto
# ownership, HNOA (hired & non-owned auto), leasing, hazardous materials, and
# vehicle-maintenance. Matched on the field-name shape, generic across forms.
_HIGH_IMPACT_AUTO_TOKENS = (
    "nonowned", "non_owned", "hirednonowned", "hiredautomobile", "hiredauto",
    "hazardousmaterial", "hazardous", "leasedtoothers", "leased", "lease",
    "maintenanceprogram", "vehiclemaintenance",
    "solelyowned", "notsolelyowned", "vehicleowner",
)


def is_high_impact_field(field_name: Optional[str]) -> bool:
    """True for a field the client asked be treated as HIGH-IMPACT (Figure 33):
    the insured/owner identity slots plus the auto ownership / HNOA / leasing /
    hazardous-materials / maintenance questions. ``field_qa`` uses this to
    surface a loosely-inferred value here individually rather than in a rollup.
    """
    if is_insured_owner_field(field_name):
        return True
    fl = _fl(field_name)
    return any(tok in fl for tok in _HIGH_IMPACT_AUTO_TOKENS)


# ── Carrier-shape heuristic ───────────────────────────────────────────────────

def looks_like_carrier(value: Any) -> bool:
    """Heuristic: does ``value`` READ like an insurance carrier's name?

    True when it carries a carrier-defining word (insurance / casualty / mutual /
    indemnity / ...) together with a company/entity token - the shape of
    "EMCASCO Insurance Company" or "Employers Mutual Casualty Company". Requiring
    BOTH keeps an ordinary business name ("Orbin Contracting LLC") from matching.
    """
    s = str(value or "").strip()
    if not s:
        return False
    return bool(_CARRIER_WORD_RX.search(s) and _COMPANY_WORD_RX.search(s))


# ── Detection ─────────────────────────────────────────────────────────────────

def _collect_forbidden(merged_facts: dict, confirmations: dict):
    """Build the sets of normalized carrier / policy values that must NOT appear
    in an insured/owner field. Confirmed values take precedence over extracted."""
    carriers: Dict[str, str] = {}   # normalized -> raw (for the message)
    policies: Dict[str, str] = {}
    for key in _CARRIER_FACT_KEYS:
        raw = confirmations.get(key)
        if raw is None:
            raw = _fv(merged_facts, key)
        if raw is None:
            continue
        norm = normalize_carrier(raw)
        if norm:
            carriers.setdefault(norm, str(raw))
    for key in _POLICY_FACT_KEYS:
        raw = confirmations.get(key)
        if raw is None:
            raw = _fv(merged_facts, key)
        if raw is None:
            continue
        tok = _policy_token(raw)
        if len(tok) >= _MIN_POLICY_TOKEN_LEN:
            policies.setdefault(tok, str(raw))
    return carriers, policies


def detect_field_mapping_contamination(
    generated_forms: Optional[dict],
    merged_facts: Optional[dict] = None,
    confirmations: Optional[dict] = None,
) -> dict:
    """Detect carrier/policy data stamped into an insured/owner field.

    Parameters mirror ``field_qa.run_field_qa`` so the same generation result and
    facts can be passed straight through.

    Returns
    -------
    {
      "review_required": bool,          # True -> the download gate blocks
      "checked": int,                   # insured/owner field-values inspected
      "findings": [ {form_id, field, field_label, value, reason_code, message,
                     matched_fact_key, matched_value}, ... ],
      "message": str,                   # one-line rollup for the 409 detail
      "model_version": str,
    }

    A finding fires ONLY when a value that does not belong in the slot is
    present: it equals an extracted/confirmed carrier or policy value, or it is
    SHAPED like a carrier name and is not the applicant's own name. Nothing is
    mutated; this is a read-only assertion.
    """
    generated_forms = generated_forms or {}
    merged_facts = merged_facts or {}
    confirmations = confirmations or {}

    carriers, policies = _collect_forbidden(merged_facts, confirmations)
    applicant_norm = normalize_name(
        confirmations.get("applicant_name") or _fv(merged_facts, "applicant_name") or ""
    )

    findings: List[dict] = []
    checked = 0

    for form_id, fr in generated_forms.items():
        fr = fr or {}
        # Prefer the CURRENT edited field_state over the original mapping, so a
        # field the producer fixed is re-evaluated and no longer blocks.
        mapped = fr.get("field_state") or fr.get("mapped") or {}

        for field, val in mapped.items():
            if not is_insured_owner_field(field) or not _has_value(val):
                continue
            checked += 1
            sv = str(val).strip()

            # A field that correctly holds the applicant's own name is fine, even
            # if the applicant name happens to look carrier-ish.
            if (
                applicant_norm
                and is_insured_identity_field(field)
                and normalize_name(sv) == applicant_norm
            ):
                continue

            reason_code = matched_fact_key = matched_value = None

            carrier_norm = normalize_carrier(sv)
            policy_tok = _policy_token(sv)

            if carrier_norm and carrier_norm in carriers:
                reason_code = "carrier_in_insured_owner_field"
                matched_fact_key = "carrier_name"
                matched_value = carriers[carrier_norm]
            elif policy_tok and policy_tok in policies:
                reason_code = "policy_in_insured_owner_field"
                matched_fact_key = "policy_number"
                matched_value = policies[policy_tok]
            elif looks_like_carrier(sv):
                reason_code = "carrier_shaped_value_in_insured_owner_field"

            if reason_code is None:
                continue

            label = _humanize_field(field)
            kind = "policy" if reason_code.startswith("policy") else "carrier"
            findings.append({
                "form_id":          form_id,
                "field":            field,
                "field_label":      label,
                "value":            sv,
                "reason_code":      reason_code,
                "matched_fact_key": matched_fact_key,
                "matched_value":    matched_value,
                "message": (
                    f"{label} on {_form_label(form_id)} shows \"{sv}\", which looks like "
                    f"{kind} data, not the insured/owner. Fix this field before downloading."
                ),
            })

    review_required = bool(findings)
    if review_required:
        logger.warning(
            "field_mapping_integrity: %d contamination finding(s) across %d form(s): %s",
            len(findings), len(generated_forms),
            "; ".join(f"{f['field']} on {f['form_id']} = {f['value']!r}" for f in findings),
        )

    if not findings:
        message = ""
    elif len(findings) == 1:
        message = findings[0]["message"]
    else:
        message = (
            f"{len(findings)} insured/owner field(s) appear to contain carrier or policy "
            "data. Correct them before downloading."
        )

    return {
        "review_required": review_required,
        "checked":         checked,
        "findings":        findings,
        "message":         message,
        "model_version":   FIELD_MAPPING_INTEGRITY_MODEL_VERSION,
    }
