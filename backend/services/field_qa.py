"""field_qa.py

Form-level field QA (Figure 26 client feedback).

After forms are generated, this checks EVERY mapped ACORD field against two
things the client asked for:

  1. A confidence threshold - was the value deterministically filled / user
     confirmed (trustworthy), AI-inferred (needs review), or is a required field
     empty (fail)?
  2. Its source fact - does the value actually STAMPED on the form still agree
     (after normalization) with the extracted/confirmed source value it came
     from? A disagreement (e.g. one form edited so it drifts from the others, or
     from the merged fact) is a fail.

The result is a list of per-field verdicts + a rollup. It is ADVISORY: this
module never mutates a form, never changes a value, and never blocks anything.
Callers surface the fail/review items in the existing pre-download review so the
producer sees them before a clean download.

Design notes
------------
* Generalizes ``underwriting_consistency.verify_stamped_consistency`` (which only
  checked the 4 numeric reconcilable fields) to EVERY field, and adds the
  confidence-threshold dimension.
* Comparison uses the SHARED normalizer (services.normalization.normalize_value),
  so a formatting-only difference (07/15/25 vs 07/15/2025, "St" vs "Street",
  "$1,000,000" vs "1000000") is NOT a mismatch - only a material one is. This
  also makes it safe under display canonicalization: the clean stamped value and
  the raw source fact normalize to the same key.
* PURE apart from a lazy import of pdf_service's field<->fact mapping. No DB, no
  network. Easy to unit-test.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from services.normalization import normalize_value
from services.field_mapping_integrity import is_high_impact_field

logger = logging.getLogger(__name__)

FIELD_QA_MODEL_VERSION = "1.0.0"

# Confidence label (from pdf_service.map_facts_to_form) -> QA verdict.
#   filled / client_arq -> deterministic rule, verbatim-from-doc, or user
#                          confirmed              -> pass
#   low_confidence       -> AI-inferred, not verbatim -> review
#   missing_required     -> required + fillable + empty -> fail
_CONF_VERDICT = {
    "filled": "pass",
    "client_arq": "pass",
    "low_confidence": "review",
    "missing_required": "fail",
}


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


def _value_matches(fact_key: str, stamped: Any, expected: Any) -> bool:
    """True when the stamped value agrees with the expected source value after
    normalization. Empty/no-signal on either side is treated as "no assertion"
    (returns True) so a blank never manufactures a mismatch."""
    sv = normalize_value(fact_key, stamped)
    ev = normalize_value(fact_key, expected)
    if not sv or not ev:
        return True
    return sv == ev


def _humanize_field(field: str) -> str:
    """Light humanization of an ACORD field name for a review message."""
    base = field
    # Drop a trailing row letter (_A/_B/...) for readability.
    if len(base) > 2 and base[-2] == "_" and base[-1].isalpha():
        base = base[:-2]
    return base.replace("_", " ").strip()


# ── Public API ────────────────────────────────────────────────────────────────

def run_field_qa(
    generated_forms: Optional[dict],
    merged_facts: Optional[dict] = None,
    confirmations: Optional[dict] = None,
) -> dict:
    """Run field QA across all generated forms.

    Parameters
    ----------
    generated_forms : {form_id: {"mapped"/"field_state", "confidence", "schema"}}
                      the generation result stored on the session.
    merged_facts    : the merged fact dict (source of truth for value checks).
    confirmations   : {fact_key: confirmed_value} - user-confirmed values take
                      precedence over merged facts as the expected value.

    Returns
    -------
    {
      "checked": int,          # fields evaluated (excluding empty-optional)
      "fail_count": int,
      "review_count": int,
      "pass_count": int,
      "ok": bool,              # no fails
      "results": [ {form_id, field, field_label, fact_key, verdict,
                    reason_code, message, stamped, expected}, ... ],
                              # ONLY actionable items (fail / review); passes are
                              # counted but not listed, to keep the payload lean.
      "model_version": str,
    }
    """
    generated_forms = generated_forms or {}
    merged_facts = merged_facts or {}
    confirmations = confirmations or {}

    results: List[dict] = []
    fail = review = passed = checked = 0

    try:
        from services.pdf_service import fact_to_form_fields
    except Exception as exc:                              # pragma: no cover
        logger.warning("field_qa: pdf_service unavailable - %s", exc)
        return {
            "checked": 0, "fail_count": 0, "review_count": 0, "pass_count": 0,
            "ok": True, "results": [], "model_version": FIELD_QA_MODEL_VERSION,
        }

    # ── Build the field -> source-fact map + expected value per fact ──────────
    # For every fact that deterministically stamps into one or more form fields,
    # record which (form_id, field) it feeds and the expected value (confirmed
    # value wins, else the merged fact). This is what powers the value-vs-source
    # check; fields with no deterministic source fact (e.g. gap-fill) simply skip
    # that check and are judged on confidence alone.
    field_fact: Dict[tuple, str] = {}
    fact_expected: Dict[str, Any] = {}
    for fact_key in set(merged_facts.keys()) | set(confirmations.keys()):
        expected = confirmations.get(fact_key)
        if expected is None:
            expected = _fv(merged_facts, fact_key)
        if expected is None:
            continue
        try:
            mapping = fact_to_form_fields(fact_key)
        except Exception:                                 # pragma: no cover
            mapping = {}
        if not mapping:
            continue
        fact_expected[fact_key] = expected
        for fid, fields in mapping.items():
            for f in fields:
                field_fact[(fid, f)] = fact_key

    # ── Per-field verdicts ───────────────────────────────────────────────────
    for form_id, fr in generated_forms.items():
        fr = fr or {}
        mapped = fr.get("field_state") or fr.get("mapped") or {}
        confidence = fr.get("confidence") or {}
        # Every schema field carries a confidence label; the mapped dict holds the
        # values. Union so empty required fields (missing_required) are included.
        all_fields = set(confidence.keys()) | set(mapped.keys())

        for field in all_fields:
            val = mapped.get(field)
            has_val = _has_value(val)
            conf = confidence.get(field)
            # High-impact fields (Figure 33: insured/owner identity, auto
            # ownership, HNOA, leasing, hazardous materials, maintenance) are
            # surfaced individually rather than rolled into the generic summary,
            # so a loosely-inferred value here is never buried.
            high_impact = is_high_impact_field(field)

            # (1) Value-vs-source: a stamped value that materially disagrees with
            # its source fact is a fail regardless of confidence label.
            fact_key = field_fact.get((form_id, field))
            if has_val and fact_key and fact_key in fact_expected:
                expected = fact_expected[fact_key]
                if not _value_matches(fact_key, val, expected):
                    checked += 1
                    fail += 1
                    results.append({
                        "form_id":     form_id,
                        "field":       field,
                        "field_label": _humanize_field(field),
                        "fact_key":    fact_key,
                        "verdict":     "fail",
                        "reason_code": "value_mismatch",
                        "high_impact": high_impact,
                        "message": (
                            f"{_humanize_field(field)} on {form_id.replace('ACORD_', 'ACORD ')} "
                            f"shows \"{val}\" but the source value is \"{expected}\". "
                            "Fix: Re-confirm the correct value so it applies uniformly."
                        ),
                        "stamped":  str(val),
                        "expected": str(expected),
                    })
                    continue

            # (2) Confidence-threshold verdict.
            verdict = _CONF_VERDICT.get(conf)
            # An empty, non-required field (optional + blank) is not a QA item.
            if verdict is None:
                continue
            if verdict == "fail":
                checked += 1
                fail += 1
                results.append({
                    "form_id":     form_id,
                    "field":       field,
                    "field_label": _humanize_field(field),
                    "fact_key":    None,
                    "verdict":     "fail",
                    "reason_code": "missing_required",
                    "high_impact": high_impact,
                    "message": (
                        f"{_humanize_field(field)} on {form_id.replace('ACORD_', 'ACORD ')} "
                        "is required but empty. Fix: Provide a value before sending."
                    ),
                    "stamped":  None,
                    "expected": None,
                })
            elif verdict == "review" and has_val:
                checked += 1
                review += 1
                results.append({
                    "form_id":     form_id,
                    "field":       field,
                    "field_label": _humanize_field(field),
                    "fact_key":    None,
                    "verdict":     "review",
                    "reason_code": "low_confidence",
                    "high_impact": high_impact,
                    "message": (
                        f"{_humanize_field(field)} on {form_id.replace('ACORD_', 'ACORD ')} "
                        + (
                            "is a high-impact question that was AI-inferred (not copied "
                            "verbatim from a document). Fix: Confirm this value against the "
                            "source before sending."
                            if high_impact else
                            "was AI-inferred (not copied verbatim from a document). "
                            "Fix: Verify the value against the source."
                        )
                    ),
                    "stamped":  str(val),
                    "expected": None,
                })
            elif verdict == "pass" and has_val:
                checked += 1
                passed += 1
            # (review with no value / pass with no value -> nothing to report)

    if fail or review:
        logger.info(
            "field_qa: %d field(s) checked - %d fail, %d review, %d pass across %d form(s)",
            checked, fail, review, passed, len(generated_forms),
        )

    return {
        "checked":       checked,
        "fail_count":    fail,
        "review_count":  review,
        "pass_count":    passed,
        "ok":            fail == 0,
        "results":       results,
        "model_version": FIELD_QA_MODEL_VERSION,
    }


# ── Presentation: QA findings -> pre-download recommendation rows ──────────────

def _rec_id(*parts: str) -> str:
    """Stable, collision-safe rec id from its parts (so re-runs dedupe)."""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", "_".join(str(p) for p in parts if p))
    return f"fieldqa_{slug.strip('_')[:80]}"


def to_recommendation_rows(qa_result: Optional[dict]) -> List[dict]:
    """Translate a run_field_qa() result into rows for the existing pre-download
    review (sqs_recommendation_audit / DownloadPreflightModal).

    Deliberately NON-flooding: value-vs-source MISMATCHES are surfaced
    individually (these are the new, high-signal "stamped value disagrees with
    the source" items), while empty-required and AI-inferred fields - which are
    ALREADY shown by the existing yellow/pink highlights and the N Required /
    N Review badges - are rolled up into a SINGLE summary row so the review
    stays readable. All rows are recommendation_type 'field_qa' (soft; the
    producer can still Download Anyway).
    """
    if not qa_result:
        return []
    rows: List[dict] = []
    n_missing = 0
    n_review = 0
    for item in qa_result.get("results") or []:
        code = item.get("reason_code")
        if code == "value_mismatch":
            rows.append({
                "rec_id":       _rec_id(item.get("form_id"), item.get("field"), "mismatch"),
                "message":      item.get("message"),
                "type":         "field_qa",
                "field":        item.get("field"),
                "component":    item.get("form_id"),
                "score_impact": None,
            })
        elif item.get("high_impact"):
            # High-impact fields (Figure 33) are surfaced INDIVIDUALLY so a
            # loosely-inferred or empty high-impact field is never buried in the
            # rollup. Still soft ('field_qa') - advisory, never blocks.
            rows.append({
                "rec_id":       _rec_id(item.get("form_id"), item.get("field"), code or "high_impact"),
                "message":      item.get("message"),
                "type":         "field_qa",
                "field":        item.get("field"),
                "component":    item.get("form_id"),
                "score_impact": None,
            })
        elif code == "missing_required":
            n_missing += 1
        elif code == "low_confidence":
            n_review += 1

    if n_missing or n_review:
        parts = []
        if n_missing:
            parts.append(f"{n_missing} required field{'s' if n_missing != 1 else ''} still empty")
        if n_review:
            parts.append(f"{n_review} AI-inferred field{'s' if n_review != 1 else ''} to verify")
        rows.append({
            "rec_id":       "fieldqa_summary",
            "message": (
                "Field QA: " + " and ".join(parts)
                + ". Review the highlighted fields before a clean download."
            ),
            "type":         "field_qa",
            "field":        None,
            "component":    None,
            "score_impact": None,
        })
    return rows
