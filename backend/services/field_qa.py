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
from services.fact_registry import FACT_REGISTRY, SCHEDULE_ROW_RULES, validate_schedule_rows
from services.field_mapping_integrity import is_high_impact_field
from services.placeholder_detector import is_placeholder_value

logger = logging.getLogger(__name__)

FIELD_QA_MODEL_VERSION = "1.0.0"

# Confidence label (from pdf_service.map_facts_to_form) -> QA verdict.
#   filled / client_arq -> deterministic rule, verbatim-from-doc, or user
#                          confirmed              -> pass
#   low_confidence       -> AI-inferred, not verbatim -> review
#   missing_required     -> required + fillable + empty -> fail (soft; advisory only)
#   missing_required_gate -> form-specific completeness gate (currently just ACORD
#                          140 COPE fields, see pdf_service.
#                          apply_acord140_missing_field_highlights) -> fail (HARD;
#                          see _HARD_BLOCK_REASON_CODES / check_hard_block below)
_CONF_VERDICT = {
    "filled": "pass",
    "client_arq": "pass",
    "ai_verified": "pass",       # AI value confirmed present in the documents
    "low_confidence": "review",
    "missing_required": "fail",
    "missing_required_gate": "fail",
}

# reason_codes a download gate MUST treat as blocking (see check_hard_block()).
# Deliberately a narrow, explicit allowlist: pre-existing "missing_required" /
# "low_confidence" fails remain exactly as advisory as they always were - only a
# genuine placeholder value, or the new form-specific completeness gate (ACORD
# 140 COPE fields today), blocks a download. This is what keeps the hard-block
# purely additive and non-breaking for every field/form that isn't part of it.
_HARD_BLOCK_REASON_CODES = frozenset({"placeholder_value", "missing_required_gate"})


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
        from services.pdf_service import (
            fact_to_form_fields,
            expected_value_for_field,
            _is_nonfillable_field,
        )
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
        schema = fr.get("schema") or {}
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
            # so a loosely-inferred value here is never buried. The schema
            # tooltip is passed too: several of these questions' Yes/No ANSWER
            # fields carry an opaque ACORD code as their field name (the
            # descriptive text exists only in the tooltip) - the tooltip is what
            # lets the answer itself, not just its free-text explanation, be
            # recognized as high-impact.
            _tu = (schema.get(field) or {}).get("tu") if isinstance(schema.get(field), dict) else None
            high_impact = is_high_impact_field(field, _tu)

            # (0) Placeholder check: a stamped value that is leaked instruction text
            # or a template placeholder (e.g. "1st distinct value") is always wrong,
            # regardless of its confidence label or whether it happens to also
            # satisfy the value-vs-source check below. Checked first and highest
            # priority for that reason.
            if has_val:
                _is_ph, _ph_reason = is_placeholder_value(val)
                if _is_ph:
                    checked += 1
                    fail += 1
                    results.append({
                        "form_id":     form_id,
                        "field":       field,
                        "field_label": _humanize_field(field),
                        "fact_key":    None,
                        "verdict":     "fail",
                        "reason_code": "placeholder_value",
                        "high_impact": high_impact,
                        "message": (
                            f"{_humanize_field(field)} on {form_id.replace('ACORD_', 'ACORD ')} "
                            f"contains a placeholder value (\"{val}\"), not real data. "
                            "Fix: Re-generate the form or enter the correct value manually - "
                            "this blocks a clean download."
                        ),
                        "stamped":  str(val),
                        "expected": None,
                    })
                    continue

            # (1) Value-vs-source: a stamped value that materially disagrees with
            # its source fact is a fail regardless of confidence label. Address
            # sub-fields (LineOne/City/State/Zip) only ever hold ONE piece of the
            # full address - expected_value_for_field() extracts the matching
            # piece so e.g. a stamped city isn't compared against the whole
            # street+city+state+zip fact string (which would never match).
            fact_key = field_fact.get((form_id, field))
            if has_val and fact_key and fact_key in fact_expected:
                expected = expected_value_for_field(field, fact_key, fact_expected[fact_key])
                if not expected:
                    pass  # this field's piece has no signal - fall through to (2)
                elif not _value_matches(fact_key, val, expected):
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
                _is_gate = conf == "missing_required_gate"
                results.append({
                    "form_id":     form_id,
                    "field":       field,
                    "field_label": _humanize_field(field),
                    "fact_key":    None,
                    "verdict":     "fail",
                    "reason_code": "missing_required_gate" if _is_gate else "missing_required",
                    "high_impact": high_impact,
                    "message": (
                        f"{_humanize_field(field)} on {form_id.replace('ACORD_', 'ACORD ')} "
                        + (
                            "is required for this section (a related field was already "
                            "filled) but empty. Fix: Provide a value before sending - this "
                            "blocks a clean download."
                            if _is_gate else
                            "is required but empty. Fix: Provide a value before sending."
                        )
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
            elif verdict == "review" and not has_val and not _is_nonfillable_field(field):
                # NOT-ANSWERED: the field was a fillable gap-fill candidate (no
                # deterministic rule) that the AI returned null/omitted for. It is
                # not required, so it produces NO signal anywhere else: pink needs
                # a value (pdf_service:944), yellow needs `required` (pdf_service:942),
                # and the low_confidence review branch above needs a value. Without
                # this branch, an AI silently skipping a standard question (e.g. an
                # ACORD 125 compliance Y/N code) is a fully invisible failure mode.
                # Surface it as an advisory review item so the non-answer is visible.
                checked += 1
                review += 1
                results.append({
                    "form_id":     form_id,
                    "field":       field,
                    "field_label": _humanize_field(field),
                    "fact_key":    None,
                    "verdict":     "review",
                    "reason_code": "not_answered",
                    "high_impact": high_impact,
                    "message": (
                        f"{_humanize_field(field)} on {form_id.replace('ACORD_', 'ACORD ')} "
                        + (
                            "is a high-impact question the AI left blank (no value found "
                            "in the documents). Fix: Answer it manually if it applies."
                            if high_impact else
                            "was left blank by the AI (no value found in the documents). "
                            "Fix: Answer it manually if it applies."
                        )
                    ),
                    "stamped":  None,
                    "expected": None,
                })
            elif verdict == "pass" and has_val:
                checked += 1
                passed += 1
            # (pass with no value -> nothing to report)

    # ── Schedule row QA (Figure 32 driver-schedule client feedback) ─────────
    # Validates ROWS inside a list fact (e.g. one driver inside auto_drivers)
    # against fact_registry.SCHEDULE_ROW_RULES. Only surfaced when a form that
    # actually consumes the list fact was generated, so e.g. driver-row issues
    # never appear when ACORD 127 wasn't selected.
    generated_form_ids = set(generated_forms.keys())
    for list_key in SCHEDULE_ROW_RULES:
        entry = FACT_REGISTRY.get(list_key) or {}
        if not (entry.get("forms") or set()) & generated_form_ids:
            continue
        rows_val = confirmations.get(list_key)
        if rows_val is None:
            rows_val = _fv(merged_facts, list_key)
        if not isinstance(rows_val, list) or not rows_val:
            continue
        target_form = next(iter(entry.get("forms") or [""]), "")
        for issue in validate_schedule_rows(list_key, rows_val):
            checked += 1
            row_label = f"{_humanize_field(list_key)} row {issue['row_index'] + 1}"
            sub_label = issue["sub_key"].replace("_", " ")
            if issue["issue"] == "missing":
                fail += 1
                verdict, reason = "fail", "schedule_row_missing"
                message = (
                    f"{row_label}: {sub_label} is required but missing. "
                    "Fix: Provide a value or remove the row."
                )
                stamped = None
            else:
                review += 1
                verdict, reason = "review", "schedule_row_invalid"
                message = (
                    f"{row_label}: {sub_label} value \"{issue.get('value')}\" "
                    "does not look valid. Fix: Verify against the source document."
                )
                stamped = issue.get("value")
            results.append({
                "form_id":     target_form,
                "field":       f"{list_key}[{issue['row_index']}].{issue['sub_key']}",
                "field_label": f"{row_label} - {sub_label}",
                "fact_key":    list_key,
                "verdict":     verdict,
                "reason_code": reason,
                "high_impact": False,
                "message":     message,
                "stamped":     stamped,
                "expected":    None,
            })

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


# A trailing single- or double-letter row suffix (_A, _B, ... _AA, _AB, ...) -
# ACORD's repeating-schedule convention (see pdf_service._ROW_LETTER_TO_IDX).
# Used ONLY to GROUP high-impact recommendation rows for display; never
# affects which field is actually checked or highlighted.
_ROW_SUFFIX_STRIP_RE = re.compile(r"_[A-Z]{1,2}$")


def _base_field_for_grouping(field: str) -> str:
    return _ROW_SUFFIX_STRIP_RE.sub("", field or "")


def to_recommendation_rows(qa_result: Optional[dict]) -> List[dict]:
    """Translate a run_field_qa() result into rows for the existing pre-download
    review (sqs_recommendation_audit / DownloadPreflightModal).

    Deliberately NON-flooding: value-vs-source MISMATCHES are surfaced
    individually (these are the new, high-signal "stamped value disagrees with
    the source" items), while empty-required and AI-inferred fields - which are
    ALREADY shown by the existing yellow/pink highlights and the N Required /
    N Review badges - are rolled up into a SINGLE summary row so the review
    stays readable. All rows use recommendation_type 'suggestion' (soft; the
    producer can still Download Anyway) - identifiable as field-QA via the
    "fieldqa_" rec_id prefix (see _rec_id / sync_field_qa_findings).

    High-impact rows (Figure 33) are surfaced individually so a loosely-
    inferred or empty high-impact field is never buried - but a form with many
    repeating schedule slots (e.g. ACORD 137_CA's Vehicle_NonOwned_
    StateOrProvinceCode_A/_B/.../_AA/_AB/...) previously produced ONE row PER
    slot, all with near-identical wording (client feedback 2026-07-15: "mostly
    repeating or mostly similar"). Rows sharing the same form + underlying
    field (row suffix stripped) + reason are now merged into a single row with
    a count - still individually visible, no longer duplicated per slot.

    A SECOND merge tier (client feedback 2026-08-12: "repeated values are
    there a lot") rolls DISTINCT high-impact questions that share one form and
    one reason into a single row naming each question (first 3 labels, then
    "+N more"), instead of one near-identical row per question. Value
    mismatches and schedule-row defects stay individual - each is a distinct,
    differently-actioned finding.
    """
    if not qa_result:
        return []
    rows: List[dict] = []
    n_missing = 0
    n_review = 0
    n_blank = 0
    high_impact_groups: Dict[tuple, dict] = {}

    for item in qa_result.get("results") or []:
        code = item.get("reason_code")
        if code in _HARD_BLOCK_REASON_CODES:
            # Surfaced individually (never rolled into the summary) and tagged with
            # a "hardblock_" marker inside the rec_id so the frontend preflight
            # modal can identify these specifically: this is what requires an
            # explicit "Generate Draft Anyway" override + reason instead of the
            # ordinary, always-available "Download Anyway". Still writes
            # recommendation_type 'suggestion' - the sqs_recommendation_audit CHECK
            # constraint is unchanged; the actual block is enforced independently,
            # fresh, at download time (see check_hard_block below), never trusting
            # this DB snapshot.
            rows.append({
                "rec_id":       _rec_id("hardblock", item.get("form_id"), item.get("field"), code),
                "message":      item.get("message"),
                "type":         "suggestion",
                "field":        item.get("field"),
                "component":    item.get("form_id"),
                "score_impact": None,
            })
        elif code == "value_mismatch":
            rows.append({
                "rec_id":       _rec_id(item.get("form_id"), item.get("field"), "mismatch"),
                "message":      item.get("message"),
                # sqs_recommendation_audit.recommendation_type has a fixed CHECK
                # constraint ('hard_stop','soft_warning','missing_field',
                # 'suggestion') - reuse the existing generic 'suggestion' type
                # (the same default log_recommendations_presented() already uses)
                # rather than adding a new allowed value / migration. Rows stay
                # identifiable as field-QA via the "fieldqa_" rec_id prefix.
                "type":         "suggestion",
                "field":        item.get("field"),
                "component":    item.get("form_id"),
                "score_impact": None,
            })
        elif item.get("high_impact"):
            form_id = item.get("form_id")
            field = item.get("field") or ""
            key = (form_id, _base_field_for_grouping(field), code)
            grp = high_impact_groups.setdefault(key, {"fields": [], "message": item.get("message")})
            grp["fields"].append(field)
        elif code in ("schedule_row_missing", "schedule_row_invalid"):
            # Individual driver-schedule row issues (Figure 32) - surfaced like
            # value_mismatch rather than rolled into the summary count, since
            # each is a distinct, actionable row/sub-field.
            rows.append({
                "rec_id":       _rec_id(item.get("form_id"), item.get("field"), code),
                "message":      item.get("message"),
                "type":         "suggestion",
                "field":        item.get("field"),
                "component":    item.get("form_id"),
                "score_impact": None,
            })
        elif code == "missing_required":
            n_missing += 1
        elif code == "low_confidence":
            n_review += 1
        elif code == "not_answered":
            # Non-high-impact blanks roll into the summary count (high-impact ones
            # were surfaced individually by the high_impact branch above).
            n_blank += 1

    # Second-tier merge (client feedback 2026-08-12: "repeated values are there
    # a lot, is there a way we can reduce it"): the 2026-07-15 merge above only
    # collapses row-letter repeats of the SAME question, so a form with many
    # DISTINCT high-impact gaps still rendered one near-identical row per
    # question (~20 on the client's 125/126/127 run). Distinct questions
    # sharing one form + one reason now roll up to ONE row that NAMES them -
    # nothing is buried (Figure 33: every question is still listed by name),
    # nothing repeats. A form+reason with a single underlying question keeps
    # today's wording (including the "N high-impact repeating rows" message),
    # so the common case is byte-identical.
    by_form_reason: Dict[tuple, list] = {}
    for (form_id, base_field, code), grp in high_impact_groups.items():
        by_form_reason.setdefault((form_id, code), []).append((base_field, grp))

    for (form_id, code), groups in by_form_reason.items():
        form_label = (form_id or "").replace("ACORD_", "ACORD ")
        if len(groups) == 1:
            base_field, grp = groups[0]
            fields = grp["fields"]
            n = len(fields)
            if n == 1:
                message = grp["message"]
            else:
                label = _humanize_field(base_field)
                if code == "low_confidence":
                    verb = "were AI-inferred (not copied verbatim from a document)"
                    action = "Confirm each against the source before sending."
                elif code == "not_answered":
                    verb = "were left blank by the AI (no value found in the documents)"
                    action = "Answer manually if they apply."
                else:  # missing_required
                    verb = "are required but empty"
                    action = "Provide values before sending."
                message = (
                    f"{label} on {form_label}: {n} high-impact repeating rows {verb}. Fix: {action}"
                )
            rows.append({
                "rec_id":       _rec_id(form_id, base_field, code, "grp"),
                "message":      message,
                "type":         "suggestion",
                "field":        fields[0] if n == 1 else None,
                "component":    form_id,
                "score_impact": None,
            })
            continue

        # >= 2 distinct questions on one form for one reason -> one named row.
        labels = [_humanize_field(base_field) for base_field, _ in groups]
        shown = ", ".join(labels[:3]) + (
            f", +{len(labels) - 3} more" if len(labels) > 3 else ""
        )
        if code == "low_confidence":
            what = "high-impact answers were AI-inferred (not copied verbatim from a document)"
            action = "Confirm each against the source before sending."
        elif code == "not_answered":
            what = "high-impact questions were left blank by the AI (no value found in the documents)"
            action = "Answer them manually if they apply."
        else:  # missing_required
            what = "high-impact required fields are empty"
            action = "Provide values before sending."
        rows.append({
            "rec_id":       _rec_id(form_id, code, "form_group"),
            "message":      f"{form_label}: {len(labels)} {what}: {shown}. Fix: {action}",
            "type":         "suggestion",
            "field":        None,
            "component":    form_id,
            "score_impact": None,
        })

    if n_missing or n_review or n_blank:
        parts = []
        if n_missing:
            parts.append(f"{n_missing} required field{'s' if n_missing != 1 else ''} still empty")
        if n_review:
            parts.append(f"{n_review} AI-inferred field{'s' if n_review != 1 else ''} to verify")
        if n_blank:
            # Copy matters here (client, PART 18: "73 unresolved items - that
            # seems like a lot"): most of these are fields the documents simply
            # never address, which is the blank-over-wrong design working as
            # intended - the count must not read as a failure tally.
            parts.append(
                f"{n_blank} optional field{'s' if n_blank != 1 else ''} "
                "not covered by the documents (left blank by design)"
            )
        rows.append({
            "rec_id":       "fieldqa_summary",
            "message": (
                "Field QA: " + " and ".join(parts)
                + ". Review the highlighted fields before a clean download."
            ),
            "type":         "suggestion",
            "field":        None,
            "component":    None,
            "score_impact": None,
        })
    return rows


# ── Download-time hard-block gate ───────────────────────────────────────────

def check_hard_block(
    generated_forms: Optional[dict],
    form_ids: Optional[List[str]] = None,
    merged_facts: Optional[dict] = None,
    confirmations: Optional[dict] = None,
) -> List[dict]:
    """Return the list of field_qa findings that MUST block a clean download:
    placeholder values (any form) and form-specific completeness-gate fails
    (currently ACORD 140 COPE fields). Empty list means nothing blocks.

    This is DELIBERATELY independent of the DB-backed recommendation snapshot
    (sqs_recommendation_audit / to_recommendation_rows) that only feeds the
    frontend's advisory preflight display - a download-time gate must never
    trust a possibly-stale DB row, so this recomputes fresh from the actual
    generated-forms state on every call. Callers (routes/download_routes.py)
    are expected to call this directly at request time, not read it from a
    table.

    ``form_ids``, if given, restricts the check to that subset of
    ``generated_forms`` (e.g. a single-form download only needs to gate that
    one form, not the whole package).
    """
    generated_forms = generated_forms or {}
    if form_ids is not None:
        generated_forms = {fid: fr for fid, fr in generated_forms.items() if fid in form_ids}
    qa = run_field_qa(generated_forms, merged_facts=merged_facts, confirmations=confirmations)
    return [r for r in (qa.get("results") or []) if r.get("reason_code") in _HARD_BLOCK_REASON_CODES]
