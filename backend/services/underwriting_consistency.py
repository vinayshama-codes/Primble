"""underwriting_consistency.py

Core Underwriting Data Consistency (Beta Report §4.3).

Treats a small set of high-value underwriting fields — seeded with **Gross
Sales** (the ``total_revenue`` fact) — as *normalized data elements* that may
appear across multiple source documents (and, once stamped, across multiple
ACORD forms). For each such field this module:

  1. Extracts and NORMALIZES every value present across the uploaded documents.
  2. Groups the values by their normalized form and records WHICH document each
     raw value came from (source attribution).
  3. Flags a non-blocking review when two or more *materially different*
     (post-normalization) values are present.
  4. Lets the user confirm the correct value, which is then applied to the
     merged facts so it flows consistently into every relevant form and into
     SQS scoring.

Design notes
------------
* PURE module — takes already-extracted per-document facts + the merged facts
  and returns a verdict dict. No DB, no I/O, no network. Easy to unit-test.
  Mirrors ``submission_integrity.py``.
* REUSABLE ENGINE — every reconcilable field is one entry in
  ``RECONCILABLE_FIELDS``. Adding total_payroll / num_employees / FEIN later is
  a one-line config add, not new bespoke code (Beta Report §4.3:
  "Gross Sales and similar underwriting fields").
* EXACT MATCH AFTER NORMALIZATION — ``$1,000,000`` == ``1000000`` ==
  ``1,000,000.00`` (no conflict), but ``1,000,000`` vs ``1,200,000`` conflicts.
  No silent tolerance band that could hide a real underwriting difference.
* NON-BLOCKING — a discrepancy produces ``review_required`` on the field, NOT a
  hard stop. Consistent with §5 (avoid false hard stops); the §4.3 acceptance
  wording is "flagged for review".
"""

import logging
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

# Workstream-2 normalization layer (leaf module — no cycle). "identity" fields
# (name/date/entity/address/carrier/fein) compare via this so the picker uses
# the exact same equivalence rules as the cross-document conflict detectors.
from services.normalization import normalize_value

logger = logging.getLogger(__name__)

UNDERWRITING_CONSISTENCY_MODEL_VERSION = "1.1.0"

# Confidence/source labels for a user-confirmed value applied to merged facts.
# "client_arq" scores 1.00 in sqs_service.CONFIDENCE_SCORE — a value the broker
# explicitly confirmed is producer-verified truth.
_CONFIRMED_CONFIDENCE = "client_arq"
_CONFIRMED_SOURCE = "user_confirmed"

# ── Text-scan patterns for reconcilable fields ────────────────────────────────
# When the LLM produces the same value from two documents that actually contain
# different numbers (e.g. because it anchors to the dec page value), these
# patterns scan the raw OCR text directly to surface ALL revenue/payroll figures
# associated with revenue-like labels. Used as a cross-check layer on top of
# the LLM extraction — if the text scan finds a materially different figure in
# a doc that the LLM reported as agreeing, the text-scan value is surfaced for
# review alongside the LLM-extracted value.
#
# Pattern design: label keyword(s) + optional whitespace/colon/dash + currency.
# Captures the currency string only (group 1).
# Date token shared by the effective/expiration scanners (MM/DD/YY[YY],
# MM-DD-YY[YY], YYYY-MM-DD, with '.' separators too).
_DATE_RX = r"(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}|\d{4}[/.\-]\d{1,2}[/.\-]\d{1,2})"

_TEXT_SCAN_PATTERNS: Dict[str, List[str]] = {
    "total_revenue": [
        # Explicit "Annual Revenue" / "Gross Sales" / "Gross Revenue" labels
        r"(?:annual\s+(?:gross\s+)?(?:revenue|sales|receipts)|gross\s+(?:sales|revenue|receipts))"
        r"\s*[:\-–]?\s*(\$[\d,]+(?:\.\d{1,2})?|\d[\d,]+(?:\.\d{1,2})?)",
        # "Revenue: $X" / "Total Revenue: $X"
        r"(?:total\s+)?revenue\s*[:\-–]\s*(\$[\d,]+(?:\.\d{1,2})?|\d[\d,]+(?:\.\d{1,2})?)",
        # "Gross Sales: $X" / "Projected Gross Sales: $X" / "Current Year ... Sales: $X"
        r"(?:projected\s+|current\s+year\s+)?gross\s+sales\s*[:\-–]?\s*"
        r"(\$[\d,]+(?:\.\d{1,2})?|\d[\d,]+(?:\.\d{1,2})?)",
        # "Sales / Revenue: $X"
        r"sales\s*/\s*revenue\s*[:\-–]\s*(\$[\d,]+(?:\.\d{1,2})?|\d[\d,]+(?:\.\d{1,2})?)",
    ],
    # Payroll — "(Total/Estimated/Annual) Payroll: $X" and "Remuneration: $X".
    # Currency kind, so it uses the same min-amount-floored numeric path as
    # revenue. Employee Count is integer (not supported by this currency-oriented
    # scanner) and intentionally relies on LLM extraction only.
    "total_payroll": [
        r"(?:total\s+|estimated\s+|annual\s+){0,2}payroll\s*[:\-–]?\s*"
        r"(\$[\d,]+(?:\.\d{1,2})?|\d[\d,]+(?:\.\d{1,2})?)",
        r"(?:estimated\s+|annual\s+){0,2}remuneration\s*[:\-–]?\s*"
        r"(\$[\d,]+(?:\.\d{1,2})?|\d[\d,]+(?:\.\d{1,2})?)",
    ],
    # Building value — building-specific labels only (the word "building" must
    # precede the amount) so a contents/BPP figure can't masquerade as a conflict.
    "property_building_value": [
        r"building\s+(?:value|limit|coverage|replacement\s+cost|amount)\s*[:\-–]?\s*"
        r"(\$[\d,]+(?:\.\d{1,2})?|\d[\d,]+(?:\.\d{1,2})?)",
    ],
    # ── Identity / policy fields (label-anchored; first labelled match wins) ──
    # These recover the real per-document value when the LLM collapsed it. Each
    # capture is validated/deduped through the field's WS-2 normalizer, so a
    # formatting-only difference (07/15/25 vs 7/15/2025, LLC vs Limited Liability
    # Company, Travelers vs Travelers Insurance Company) never surfaces a conflict.
    "effective_date": [
        r"\b(?:policy\s+)?effective(?:\s+date)?\s*[:\-]?\s*" + _DATE_RX,
    ],
    "expiration_date": [
        r"\b(?:policy\s+)?expir\w*(?:\s+date)?\s*[:\-]?\s*" + _DATE_RX,
    ],
    "fein": [
        r"\b(?:fein|f\.e\.i\.n|ein|fed(?:eral)?\s*(?:employer\s*)?"
        r"(?:id|tax\s*id|identification)|tax\s*id(?:entification)?"
        r"(?:\s*(?:no|number|#))?)\b\s*[:#]?\s*(\d{2}-?\d{7})",
    ],
    "entity_type": [
        r"\b(?:legal\s+entity|entity|business|organization)\s+type\s*[:\-]?\s*"
        r"([A-Za-z][A-Za-z .'&/\-]{1,45}?)\s*(?:\r?\n|$|[,;])",
    ],
    "carrier_name": [
        r"\b(?:insurance\s+carrier|carrier\s+name|current\s+carrier|carrier|insurer)\s*[:\-]\s*"
        r"([A-Za-z][A-Za-z0-9 .,'&/\-]{2,60}?)\s*(?:\r?\n|$)",
    ],
}

# Minimum amount (as int after stripping formatting) to be a plausible business
# revenue figure — filters out stray small numbers like zip codes or page refs.
_TEXT_SCAN_MIN_AMOUNT = 10_000


def _text_scan_values(text: str, fact_key: str) -> List[str]:
    """Scan raw OCR text for values of ``fact_key`` directly.

    This is the safety net for the LLM COLLAPSING per-document values — it may
    extract the dec-page value for every document even when a document's own
    text clearly states a different one (observed for Gross Sales, and confirmed
    for the identity fields via the doc_consistency_input logs). Scanning each
    document's raw text recovers the real value regardless of what the LLM
    returned — so cross-document conflicts surface even when extraction (or its
    cache) flattened them.

    Currency fields return every distinct figure found (with a min-amount floor).
    Identity/date/fein fields return only the FIRST labelled match in the doc, so
    a prior/renewal date or a second mention can't manufacture an intra-document
    false conflict. Every value is validated/deduplicated through the field's
    Workstream-2 normalizer, so formatting-only differences never leak through.
    """
    patterns = _TEXT_SCAN_PATTERNS.get(fact_key)
    if not patterns or not text:
        return []
    is_currency = RECONCILABLE_FIELDS.get(fact_key, {}).get("kind") == "currency"
    found: Dict[str, str] = {}   # normalized -> first raw match (insertion order)
    for pattern in patterns:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            raw = (m.group(1) or "").strip()
            if not raw:
                continue
            if is_currency:
                norm = _normalize_currency(raw)
                if not norm:
                    continue
                try:
                    if int(norm.split(".")[0]) < _TEXT_SCAN_MIN_AMOUNT:
                        continue
                except (ValueError, IndexError):
                    continue
            else:
                # Identity/date/fein → validate + dedupe via the WS-2 normalizer.
                norm = normalize_value(fact_key, raw)
                if not norm:
                    continue
            found.setdefault(norm, raw)
            if not is_currency:
                # One labelled value per document for identity/date/fein fields.
                return [raw]
    return list(found.values())


# ── Reconcilable field registry (the reusable engine) ─────────────────────────
#
# kind:  "currency" → money amounts (Gross Sales, payroll, ...)
#        "integer"  → whole-number counts (employee count, ...)
#        "text"     → fallback exact-match on normalized text
# forms: ACORD form ids that consume this fact (for the "applied to N forms"
#        message). Gross Sales stamps into 125/126/131 via the alias bridge
#        (alias_stamper.CANONICAL_TO_EXTRACTION:
#         business_information_annual_gross_receipts_amount -> total_revenue).

RECONCILABLE_FIELDS: Dict[str, Dict[str, Any]] = {
    "total_revenue": {
        "label": "Gross Sales / Annual Revenue",
        "kind":  "currency",
        # Fallback only — the live "applied to" list is derived dynamically from
        # the real stamping paths (rules + alias bridge) via pdf_service.
        # forms_consuming_fact, which also covers ACORD 160/186. ACORD 125 is
        # intentionally absent: its sole revenue field is the location-level
        # CommercialStructure_AnnualRevenueAmount, which is never stamped with
        # the business-level Gross Sales figure.
        "forms": ["ACORD_126", "ACORD_131", "ACORD_160", "ACORD_186"],
    },
    # Building Value duplication/inflation/inconsistency across documents (client
    # Property Integrity directive). Reconciled exactly like Gross Sales: when two
    # documents report MATERIALLY different building values the field is flagged
    # for review before forms are generated, with source attribution and a
    # confirmation path. Formatting-only differences ($500,000 == 500000) do not.
    "property_building_value": {
        "label": "Building Value",
        "kind":  "currency",
        # Fallback only — live list derived dynamically (see total_revenue note).
        # Building Value is stamped deterministically into ACORD 140's premises
        # limit rows; ACORD 141/28 have no deterministic building-value field.
        "forms": ["ACORD_140"],
    },
    # ── Identity / policy fields (Beta Report §5 picker) ─────────────────────
    # kind "identity" routes through the Workstream-2 normalization layer
    # (services.normalization.normalize_value) so formatting/synonym/alias-only
    # variants ("ORBIN CONTRACTING LLC" vs "Orbin Contracting, LLC", 07/15/25 vs
    # 7/15/2025, LLC vs Limited Liability Company, ST vs Street, EMC vs Employers
    # Mutual Casualty) collapse to ONE value and never surface as a picker
    # conflict — only MATERIALLY different values do. The picker lets the broker
    # choose (or type) the correct value, which is then applied across forms.
    "applicant_name":   {"label": "Applicant / Named Insured", "kind": "identity", "forms": []},
    "dba_name":         {"label": "DBA / Trade Name",          "kind": "identity", "forms": []},
    "fein":             {"label": "FEIN",                      "kind": "identity", "forms": []},
    "entity_type":      {"label": "Entity Type",               "kind": "identity", "forms": []},
    "mailing_address":  {"label": "Mailing Address",           "kind": "identity", "forms": []},
    "physical_address": {"label": "Physical Address",          "kind": "identity", "forms": []},
    "effective_date":   {"label": "Policy Effective Date",     "kind": "identity", "forms": []},
    "expiration_date":  {"label": "Policy Expiration Date",    "kind": "identity", "forms": []},
    "carrier_name":     {"label": "Carrier",                   "kind": "identity", "forms": []},
    # ── Core underwriting numeric fields (Beta Report §4.3 "and similar fields") ─
    # Reconciled exactly like Gross Sales: cross-document conflicts are flagged
    # for review (non-blocking) with source attribution and a confirmation path,
    # and a confirmed value flows across forms + scoring. "forms" is a fallback
    # only — the live list is derived dynamically (see total_revenue note).
    "total_payroll": {
        "label": "Total Annual Payroll",
        "kind":  "currency",
        "forms": ["ACORD_131", "ACORD_160", "ACORD_186"],
    },
    "num_employees": {
        "label": "Employee Count",
        "kind":  "integer",
        "forms": ["ACORD_125", "ACORD_126", "ACORD_131", "ACORD_186"],
    },
    # ── Extend here (no other code change needed) ────────────────────────────
    # Add a one-line entry: {"label": ..., "kind": "currency"|"integer", "forms": [...]}.
}

# Fields whose conflict is a HARD STOP until the user resolves it (kept blocking
# in check_doc_consistency while unconfirmed; the picker is the resolution path).
# Informational only here — the gating still lives in sqs_service.check_doc_consistency.
HARD_STOP_RECONCILABLE_KEYS = frozenset({
    "applicant_name", "fein", "effective_date", "expiration_date",
})

# Fields whose unresolved conflict must BLOCK form generation until the user
# confirms the correct value (client Property Integrity directive: "Building Value
# Duplication ... generate a warning and require review before forms are
# generated."). This is a generation-time gate only — scoring, recommendations,
# and the questionnaire still run; the confirmation picker is the resolution path.
GENERATION_BLOCKING_RECONCILABLE_KEYS = frozenset({
    "property_building_value",
})

# Keys excluded from the crude cross-doc conflict detectors so this engine is
# the single source of truth for them (prevents un-normalized false positives).
RECONCILABLE_FIELD_KEYS = frozenset(RECONCILABLE_FIELDS.keys())


# ── Value extraction (handles the {value, confidence} envelope) ───────────────

def _fv(facts: dict, key: str, default=None):
    """Extract a scalar fact, unwrapping the annotated {value, confidence} envelope."""
    if not isinstance(facts, dict):
        return default
    v = facts.get(key, default)
    if isinstance(v, dict) and "value" in v:
        v = v["value"]
    if v is None or (isinstance(v, str) and v.strip().lower() in ("", "null", "none")):
        return default
    return v


# ── Normalization ─────────────────────────────────────────────────────────────

def _normalize_currency(value: Any) -> Optional[str]:
    """Canonical numeric string for a money amount, or None if not parseable.

    Strips currency symbols, commas, and whitespace; drops insignificant
    trailing zeros after the decimal point so 1000000, $1,000,000 and
    1,000,000.00 all collapse to '1000000'. Returns None when the value
    contains no parseable number (caller falls back to text comparison).
    """
    if value is None:
        return None
    s = str(value).strip()
    # Keep only digits and the decimal point (drop $, commas, spaces, etc.).
    cleaned = re.sub(r"[^\d.]", "", s)
    # Collapse accidental multiple dots ("1.000.000" -> first dot wins is risky;
    # treat as no-decimal thousands grouping → strip all dots if >1).
    if cleaned.count(".") > 1:
        cleaned = cleaned.replace(".", "")
    if not cleaned or cleaned == ".":
        return None
    try:
        dec = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None
    # Canonical string: plain integer when no fractional part; otherwise
    # fixed-point with trailing zeros stripped. Avoids Decimal.normalize()'s
    # scientific notation (1000000 -> '1E+6'), which would break equality.
    if dec == dec.to_integral_value():
        return str(int(dec))
    return format(dec, "f").rstrip("0").rstrip(".")


def _normalize_integer(value: Any) -> Optional[str]:
    if value is None:
        return None
    digits = re.sub(r"[^\d]", "", str(value))
    if not digits:
        return None
    return str(int(digits))


def _normalize_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = re.sub(r"[^a-z0-9]+", " ", str(value).lower())
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def _normalize(value: Any, kind: str, fact_key: Optional[str] = None) -> Optional[str]:
    # "identity" routes through the Workstream-2 normalization layer so the
    # picker uses the SAME equivalence rules as the cross-document conflict
    # detectors. normalize_value() dispatches by fact_key (name/date/entity/
    # address/carrier/fein) and returns '' for no-signal → treated as absent.
    if kind == "identity":
        norm = normalize_value(fact_key or "", value)
        return norm or None
    if kind == "currency":
        norm = _normalize_currency(value)
    elif kind == "integer":
        norm = _normalize_integer(value)
    else:
        norm = None
    # Fall back to text comparison when the numeric normalizer can't parse it
    # (e.g. "1.2 million") so we still detect genuinely different free-text.
    if norm is None and kind != "text":
        norm = _normalize_text(value)
    elif kind == "text":
        norm = _normalize_text(value)
    return norm


# ── Applied-to form list (derived dynamically) ───────────────────────────────

def _forms_for_field(fact_key: str, cfg: dict) -> List[str]:
    """The ACORD forms a confirmed value for this field flows into.

    For currency/integer fields the list is derived dynamically from the real
    stamping paths (deterministic rules + alias bridge) via
    ``pdf_service.forms_consuming_fact`` so the "applied to N forms" badge always
    names the true, complete set. Identity fields keep their declared list
    (empty) so their picker behaviour and UI stay unchanged. Any failure falls
    back to the static registry list — it never regresses.
    """
    static = list(cfg.get("forms") or [])
    if cfg.get("kind") not in ("currency", "integer"):
        return static
    try:
        from services.pdf_service import forms_consuming_fact
        dynamic = forms_consuming_fact(fact_key)
        return dynamic or static
    except Exception as exc:                              # pragma: no cover
        logger.warning("underwriting_consistency: dynamic form list failed for %s — %s", fact_key, exc)
        return static


# ── Public API ────────────────────────────────────────────────────────────────

def assess_underwriting_consistency(
    docs: List[dict],
    merged_facts: Optional[dict] = None,
    confirmations: Optional[dict] = None,
) -> dict:
    """Assess cross-document consistency of the reconcilable underwriting fields.

    Parameters
    ----------
    docs : active (non-excluded) processed-document dicts, each exposing
           ``facts`` and ideally ``doc_id`` / ``filename`` / ``doc_type``.
    merged_facts : the post-merge fact dict (used to surface the value that will
           actually be stamped into forms).
    confirmations : {fact_key: confirmed_raw_value} — values the user has already
           confirmed. A confirmed field is reported as resolved (status
           "confirmed", review_required False).

    Returns
    -------
    {
      "fields": [ {fact_key, label, status, review_required, kind, forms,
                   merged_value, confirmed_value, values:[{normalized, display,
                   sources:[{doc_id, filename, doc_type, doc_type_label, raw}]}]},
                  ... ],
      "review_required": bool,    # any field in unresolved conflict
      "conflict_count": int,
      "model_version": str, "assessed_at": str,
    }
    """
    # Local import avoids a circular dependency at module load
    # (extraction_service imports nothing from here).
    try:
        from services.extraction_service import DOC_TYPE_LABELS
    except Exception:                                  # pragma: no cover
        DOC_TYPE_LABELS = {}

    now = datetime.now(timezone.utc).isoformat()
    docs = docs or []
    merged_facts = merged_facts or {}
    confirmations = confirmations or {}

    # Beta Report §4.3 item 3: flag documents with no raw OCR text. For these the
    # raw-text safety-net scan cannot run, so their cross-document comparison is
    # AI-extraction only and may miss a value the LLM collapsed. Logged once per
    # assessment (only when there is more than one document to compare).
    if len(docs) > 1:
        _no_text = [
            (d.get("filename") or f"document_{i + 1}")
            for i, d in enumerate(docs)
            if not str(d.get("text") or "").strip()
        ]
        if _no_text:
            logger.warning(
                "underwriting_consistency: %d of %d document(s) have no raw text; "
                "their cross-document comparison is AI-extraction only and may be "
                "incomplete (text-scan skipped): %s",
                len(_no_text), len(docs), ", ".join(_no_text),
            )

    fields_out: List[dict] = []
    conflict_count = 0

    for fact_key, cfg in RECONCILABLE_FIELDS.items():
        kind = cfg["kind"]
        label = cfg["label"]

        # Group raw values by their normalized form, recording every source doc.
        # Two-pass approach:
        #   Pass 1 — LLM-extracted facts (primary, high signal).
        #   Pass 2 — Text-scan of raw OCR text (supplementary: catches cases where
        #            the LLM anchored to one doc's value and reported the same number
        #            from a doc that actually contains a different figure).
        # Text-scan values are marked with source "text_scan" so they are visually
        # distinct in the UI from confirmed LLM-extracted values.
        groups: Dict[str, dict] = {}

        for idx, d in enumerate(docs):
            dt = d.get("doc_type") or "unknown"
            doc_id   = str(d.get("doc_id") or idx)
            filename = d.get("filename") or f"document_{idx + 1}"
            dt_label = DOC_TYPE_LABELS.get(dt, dt.replace("_", " ").title())

            # Pass 1: LLM-extracted fact value.
            raw = _fv(d.get("facts") or {}, fact_key)
            llm_norm = None
            if raw is not None:
                llm_norm = _normalize(raw, kind, fact_key)
                if llm_norm:
                    src = {
                        "doc_id": doc_id, "filename": filename,
                        "doc_type": dt, "doc_type_label": dt_label,
                        "raw": str(raw), "source_method": "llm",
                    }
                    g = groups.setdefault(llm_norm, {"normalized": llm_norm, "display": str(raw), "sources": []})
                    g["sources"].append(src)

            # Pass 2: text-scan of raw OCR.
            # Only add a text-scan value if it is DIFFERENT from the LLM value,
            # so we don't double-report an agreed value.
            raw_text = d.get("text") or ""
            if raw_text:
                for scanned_raw in _text_scan_values(raw_text, fact_key):
                    scanned_norm = _normalize(scanned_raw, kind, fact_key)
                    if not scanned_norm or scanned_norm == llm_norm:
                        continue
                    # A genuinely different value found directly in the text.
                    src = {
                        "doc_id": doc_id, "filename": filename,
                        "doc_type": dt, "doc_type_label": dt_label,
                        "raw": scanned_raw, "source_method": "text_scan",
                    }
                    g = groups.setdefault(scanned_norm, {"normalized": scanned_norm, "display": scanned_raw, "sources": []})
                    # Only add this source once per doc (avoid duplicate entries
                    # when multiple patterns match the same figure).
                    already = any(s["doc_id"] == doc_id and s["source_method"] == "text_scan" for s in g["sources"])
                    if not already:
                        g["sources"].append(src)

        confirmed_raw = confirmations.get(fact_key)
        confirmed_value = str(confirmed_raw) if confirmed_raw is not None else None

        # Nothing extracted and nothing confirmed → field not present; skip it.
        if not groups and confirmed_value is None:
            continue

        values = list(groups.values())
        distinct = len(values)

        if confirmed_value is not None:
            status = "confirmed"
            review_required = False
        elif distinct >= 2:
            status = "conflict"
            review_required = True
            conflict_count += 1
        elif distinct == 1:
            status = "consistent"
            review_required = False
        else:
            status = "confirmed"   # confirmed-only handled above; unreachable
            review_required = False

        fields_out.append({
            "fact_key":        fact_key,
            "label":           label,
            "kind":            kind,
            "forms":           _forms_for_field(fact_key, cfg),
            "status":          status,
            "review_required": review_required,
            "merged_value":    _display(_fv(merged_facts, fact_key)),
            "confirmed_value": confirmed_value,
            "values":          values,
        })

    return {
        "fields":          fields_out,
        "review_required": any(f["review_required"] for f in fields_out),
        "conflict_count":  conflict_count,
        "model_version":   UNDERWRITING_CONSISTENCY_MODEL_VERSION,
        "assessed_at":     now,
    }


def _display(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def apply_confirmations(merged_facts: dict, confirmations: Optional[dict]) -> dict:
    """Return a copy of ``merged_facts`` with every confirmed value applied.

    A confirmed value is stamped as a producer-verified envelope so it (a) flows
    into every form that consumes the fact and (b) is credited at full
    confidence by SQS — while remaining labelled as user-provided (source
    "user_confirmed"), distinct from source-document evidence (§6 evidence
    labelling). Mutates a shallow copy; the caller's dict is untouched.
    """
    if not confirmations:
        return merged_facts
    out = dict(merged_facts or {})
    for fact_key, raw in confirmations.items():
        if fact_key not in RECONCILABLE_FIELDS or raw is None:
            continue
        envelope = {
            "value":      str(raw),
            "confidence": _CONFIRMED_CONFIDENCE,
            "source":     _CONFIRMED_SOURCE,
        }
        # Beta Report §4.3 item 5: store the normalized canonical alongside the
        # raw string as additive provenance, so any consumer that wants a clean
        # number has one without re-parsing. The raw ``value`` is preserved
        # unchanged — what gets stamped onto forms and read by scoring is
        # untouched (display fidelity); this key is metadata only.
        norm = _normalize(raw, RECONCILABLE_FIELDS[fact_key]["kind"], fact_key)
        if norm:
            envelope["normalized"] = norm
        out[fact_key] = envelope
    return out


def validate_confirmation(fact_key: str, value: Any) -> Optional[str]:
    """Validate a confirm request. Returns a canonicalized display value, or
    raises ValueError with a stable code the route can translate.
    """
    if fact_key not in RECONCILABLE_FIELDS:
        raise ValueError("underwriting_unknown_field")
    if value is None or str(value).strip() == "":
        raise ValueError("underwriting_empty_value")
    kind = RECONCILABLE_FIELDS[fact_key]["kind"]
    # A confirmed value must parse with the field's NATIVE normalizer (no text
    # fallback): confirming Gross Sales requires a real number, not free text;
    # confirming an identity field must carry usable signal after WS-2
    # normalization (e.g. a bare "LLC" as an applicant name normalizes to '').
    if kind == "currency":
        norm = _normalize_currency(value)
    elif kind == "integer":
        norm = _normalize_integer(value)
    elif kind == "identity":
        norm = normalize_value(fact_key, value)
    else:
        norm = _normalize_text(value)
    if not norm:
        raise ValueError("underwriting_invalid_value")
    return str(value).strip()


def verify_stamped_consistency(
    generated_forms: Optional[dict],
    merged_facts: Optional[dict] = None,
    confirmations: Optional[dict] = None,
) -> dict:
    """Post-generation cross-form assertion (Beta Report §4.3 action item 2).

    After all selected forms are generated, read the value ACTUALLY stamped into
    every form for each reconcilable currency/integer field and confirm they all
    agree (after normalization) with the expected figure — the user-confirmed
    value when one exists, otherwise the merged-facts value.

    A disagreement is logged as a warning and returned; this check NEVER mutates
    a form, changes a value, or blocks the response — it is a safety assertion
    that the deterministic stamping stayed consistent with the confirmed figure.

    Only genuinely numeric stamped values are compared (the field's native
    normalizer must parse them), so a field shared with another rule that holds a
    non-numeric value can never raise a false mismatch.

    Returns
    -------
    {"checked": int, "mismatches": [ {fact_key, label, form_id, field,
     expected, stamped} ], "ok": bool}
    """
    generated_forms = generated_forms or {}
    merged_facts    = merged_facts or {}
    confirmations   = confirmations or {}

    try:
        from services.pdf_service import fact_to_form_fields
    except Exception as exc:                              # pragma: no cover
        logger.warning("verify_stamped_consistency: pdf_service unavailable — %s", exc)
        return {"checked": 0, "mismatches": [], "ok": True}

    def _norm_native(value: Any, kind: str) -> Optional[str]:
        if kind == "currency":
            return _normalize_currency(value)
        if kind == "integer":
            return _normalize_integer(value)
        return None

    mismatches: List[dict] = []
    checked = 0

    for fact_key, cfg in RECONCILABLE_FIELDS.items():
        kind = cfg["kind"]
        if kind not in ("currency", "integer"):
            continue

        # Expected = confirmed value if present, else the merged-facts value.
        expected_raw = confirmations.get(fact_key)
        if expected_raw is None:
            expected_raw = _fv(merged_facts, fact_key)
        if expected_raw is None:
            continue
        expected_norm = _norm_native(expected_raw, kind)
        if not expected_norm:
            continue

        form_fields = fact_to_form_fields(fact_key)
        if not form_fields:
            continue

        for form_id, form_result in generated_forms.items():
            mapped = (form_result or {}).get("mapped") or {}
            for field in form_fields.get(form_id, ()):
                val = mapped.get(field)
                if val is None or str(val).strip() in ("", "null", "None"):
                    continue
                vnorm = _norm_native(val, kind)
                if not vnorm:
                    # Stamped value is not a number of this kind → not this
                    # fact's value; skip (no false mismatch).
                    continue
                checked += 1
                if vnorm != expected_norm:
                    mismatches.append({
                        "fact_key": fact_key, "label": cfg["label"],
                        "form_id":  form_id,   "field": field,
                        "expected": str(expected_raw), "stamped": str(val),
                    })

    if mismatches:
        logger.warning(
            "underwriting_consistency: post-generation stamp MISMATCH on %d field-value(s) — %s",
            len(mismatches),
            "; ".join(
                f"{m['label']} on {m['form_id']} stamped {m['stamped']!r} != expected {m['expected']!r}"
                for m in mismatches
            ),
        )
    else:
        logger.info(
            "underwriting_consistency: post-generation stamp check OK "
            "(%d field-value(s) verified across %d form(s))",
            checked, len(generated_forms),
        )

    return {"checked": checked, "mismatches": mismatches, "ok": not mismatches}


def stamp_mismatch_issues(stamp_check: Optional[dict]) -> List[dict]:
    """Translate a :func:`verify_stamped_consistency` result into cross-issue
    dicts (shape ``{type, code, message, forms}``) so a cross-form stamp
    discrepancy is surfaced to the user through the existing cross-issues channel
    on the generation screen (Beta Report §4.3 "…or forms").

    Returns ``[]`` when there are no mismatches, so the normal case adds nothing.
    One issue per field, listing the forms involved. Display only — callers must
    NOT feed these into SQS scoring.
    """
    if not stamp_check or stamp_check.get("ok", True):
        return []
    by_fact: Dict[tuple, set] = {}
    for m in stamp_check.get("mismatches") or []:
        by_fact.setdefault((m.get("fact_key"), m.get("label")), set()).add(m.get("form_id"))
    issues: List[dict] = []
    for (fact_key, label), forms in by_fact.items():
        flist = sorted(f for f in forms if f)
        pretty = ", ".join(f.replace("ACORD_", "ACORD ") for f in flist)
        issues.append({
            "type":    "soft_warning",
            "code":    "underwriting_stamp_mismatch",
            "message": (
                f"{label or fact_key} appears inconsistently across generated forms "
                f"({pretty}). Re-confirm the value so it applies uniformly."
            ),
            "forms":   flist,
        })
    return issues
