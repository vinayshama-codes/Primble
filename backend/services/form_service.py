#form_service.py

import json
import logging
import os
import re
from typing import Dict, FrozenSet, List, Optional, Tuple

from config.settings import TEMPLATE_DIR, FORMS_DB_DIR, FORMS_INDEX
from services.extraction_service import _fv, _is_empty
from services.pdf_service import extract_form_schema, map_facts_to_form, fill_pdf
from services.sqs_service import cross_validate, calculate_sqs

logger = logging.getLogger(__name__)

# ── Form required-keys index (built once at import time) ──────────────────────
#
# Maps form_id → frozenset of fact-keys that the form needs.
# Sources (in priority order):
#   1. Fieldmap JSON  — ACORD_<form_id>_fieldmap.json  (non-null values only)
#   2. form JSON      — required_fields / tier1_minimum_fields lists
#
# Internal pseudo-keys that start with "_" (address helpers like _addr_line1)
# are excluded — they are always synthesised from mailing_address and cannot
# be checked directly against the facts dict.
#
# The index is intentionally a module-level constant so every request shares
# the same object without any lock or lazy-init logic.

def _build_form_required_keys() -> Dict[str, FrozenSet[str]]:
    """
    Walk every form in forms_index.json and build the set of fact-keys that
    form requires, drawing from fieldmaps first, then form-level field lists.
    Returns {form_id: frozenset(fact_keys)}.
    """
    index: Dict[str, FrozenSet[str]] = {}

    if not os.path.exists(FORMS_INDEX):
        return index

    try:
        with open(FORMS_INDEX) as f:
            forms_list = json.load(f).get("forms", [])
    except Exception as exc:
        logger.error("form_service: failed to read forms_index.json: %s", exc)
        return index

    for ref in forms_list:
        form_id = ref.get("form_id", "")
        if not form_id:
            continue

        keys: set = set()

        # ── Source 1: fieldmap JSON ────────────────────────────────────────
        # Naming convention used by pdf_service._load_fieldmap:
        #   ACORD_{form_id}_fieldmap.json  where form_id is WITHOUT the ACORD_ prefix
        # But the forms_index stores form_id as e.g. "ACORD_126".
        # The fieldmap files on disk are named  ACORD_ACORD_126_fieldmap.json
        # (i.e. "ACORD_" + form_id + "_fieldmap.json").
        fieldmap_path = os.path.join(FORMS_DB_DIR, f"ACORD_{form_id}_fieldmap.json")
        if os.path.exists(fieldmap_path):
            try:
                with open(fieldmap_path) as f:
                    fieldmap = json.load(f)
                for fact_key in fieldmap.values():
                    if fact_key and not str(fact_key).startswith("_"):
                        keys.add(fact_key)
            except Exception as exc:
                logger.warning("form_service: could not read fieldmap %s: %s", fieldmap_path, exc)

        # ── Source 2: form JSON field lists ────────────────────────────────
        form_json_path = os.path.join(FORMS_DB_DIR, f"{form_id}.json")
        if os.path.exists(form_json_path):
            try:
                with open(form_json_path) as f:
                    form_meta = json.load(f)
                for list_key in ("required_fields", "tier1_minimum_fields",
                                 "tier1_cope_fields", "tier2_carrier_grade_cope_fields"):
                    for fk in form_meta.get(list_key) or []:
                        if fk and not str(fk).startswith("_"):
                            keys.add(fk)
            except Exception as exc:
                logger.warning("form_service: could not read form JSON %s: %s", form_json_path, exc)

        index[form_id] = frozenset(keys)
        logger.debug("form_service: %s → %d required keys", form_id, len(keys))

    return index


# Module-level cache — built once, shared across all requests.
_FORM_REQUIRED_KEYS: Dict[str, FrozenSet[str]] = _build_form_required_keys()


def _score_field_coverage(form_id: str, facts: dict) -> Tuple[float, int, int]:
    """
    Return (coverage_ratio, filled_count, total_count) for the given form
    against the extracted facts dict.

    coverage_ratio is in [0.0, 1.0].  If the form has no required keys the
    ratio is 0.0 (caller handles this edge-case by falling back to trigger tier).

    A fact-key is considered "filled" if:
      - it exists in facts AND
      - its value (unwrapped from OCR-confidence envelope if present) is
        non-empty (not None / "" / "null" / "none" / "n/a").

    Facts stored as annotated dicts {value, confidence} are handled via _fv/_is_empty.
    List-type facts (e.g. lines_of_business) count as filled when non-empty.
    """
    required = _FORM_REQUIRED_KEYS.get(form_id, frozenset())
    total    = len(required)
    if total == 0:
        return 0.0, 0, 0

    filled = 0
    for key in required:
        raw = facts.get(key)
        if raw is None:
            continue
        # _is_empty handles: None, "", "null"/"none"/"n/a", empty list/dict,
        # and annotated envelopes {"value": ..., "confidence": ...}
        if not _is_empty(raw):
            filled += 1

    ratio = filled / total
    return ratio, filled, total


def _compute_confidence(
    form_id: str,
    facts: dict,
    trigger_weight: float,
    triggered: bool,
) -> Tuple[float, str]:
    """
    Compute the blended confidence score and a human-readable reason string.

    Formula (when the form has required keys):
        blended = 0.6 * field_coverage + 0.4 * trigger_weight

    Floor guarantee for triggered forms:
        blended ≥ trigger_weight * 0.55
        (a triggered form can never score below ~55% of its trigger tier)

    When the form has no required keys (no fieldmap + no field lists), we
    return trigger_weight directly so the score is at least the tier signal.

    Parameters
    ----------
    trigger_weight : float
        1.0 for always-required, 0.95 for flag-based, 0.85 for keyword-based,
        0.0 for non-triggered forms scored for the "add more forms" list.
    triggered : bool
        True when the form was matched by rule/flag/keyword logic.
    """
    coverage, filled, total = _score_field_coverage(form_id, facts)

    if total == 0:
        # No schema data to compute coverage — honour trigger tier as-is.
        # Non-triggered forms with no schema get 0.
        score = trigger_weight
        if triggered and trigger_weight > 0:
            reason = "Form triggered by document signals; no field schema available for detailed scoring"
        elif not triggered:
            reason = "No field schema available"
        else:
            reason = "Always required"
        return round(score, 4), reason

    blended = 0.6 * coverage + 0.4 * trigger_weight

    if triggered and trigger_weight > 0:
        floor   = trigger_weight * 0.55
        blended = max(blended, floor)

    blended = min(blended, 1.0)

    pct = round(coverage * 100)
    reason = f"{filled} of {total} required fields found in document ({pct}%)"
    return round(blended, 4), reason


# ─────────────────────────────────────────────────────────────────────────────


def load_index() -> dict:
    if not os.path.exists(FORMS_INDEX):
        return {"forms": []}
    with open(FORMS_INDEX) as f:
        return json.load(f)


def load_form_detail(form_id: str) -> Optional[dict]:
    p = os.path.join(FORMS_DB_DIR, f"{form_id}.json")
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def load_all_forms() -> List[dict]:
    idx = load_index()
    return [d for ref in idx.get("forms", []) if (d := load_form_detail(ref["form_id"])) is not None]


def filter_available_forms(forms: List[dict]) -> List[dict]:
    # Exclude forms with no template_file: an empty string resolves to TEMPLATE_DIR
    # itself (which always exists), so we must gate on truthiness first.
    return [
        f for f in forms
        if f.get("template_file")
        and os.path.exists(os.path.join(TEMPLATE_DIR, f["template_file"]))
    ]


def stage1_filter(flags: dict, all_forms: List[dict]) -> List[dict]:
    active     = {k for k, v in flags.items() if v}
    candidates = []
    seen       = set()
    for form in all_forms:
        fid     = form["form_id"]
        if fid in seen:
            continue
        include = False
        if form.get("always_include"):
            include = True
        elif set(form.get("matching_flags", [])) & active:
            include = True
        elif fid == "ACORD_126" and (flags.get("has_general_liability") or flags.get("is_contractor")):
            include = True
        elif fid == "ACORD_140" and flags.get("has_property_coverage"):
            include = True
        elif fid == "ACORD_25" and (flags.get("has_certificate_request") or flags.get("is_certificate_doc")):
            include = True
        if include:
            candidates.append(form)
            seen.add(fid)
    return candidates



def match_forms_deterministic(facts: dict, flags: dict, text: str = "") -> List[dict]:
    """
    Rule-based form matching combined with live document field-coverage scoring.

    Trigger logic is unchanged (flag/keyword rules decide WHICH forms to recommend).
    Confidence is now a live blended score:
        confidence = 0.6 * field_coverage + 0.4 * trigger_weight
    where field_coverage = (fact-keys present in extracted facts) / (total required keys
    for this form, derived from its fieldmap + form JSON).

    Floor for triggered forms: confidence ≥ trigger_weight × 0.55 so that a strongly
    triggered form is never buried by a sparse document.

    Forms without any schema data (no fieldmap, no field lists) fall back to their
    raw trigger weight so the score is still meaningful.

    Return shape per item:
        {
          "form_id":          str,
          "form_name":        str,
          "confidence":       float,   # blended [0.0, 1.0]
          "reason":           str,     # human-readable — shown in UI
          "trigger_reason":   str,     # what fired the rule (kept for audit / E&O log)
          "fields_filled":    int,
          "fields_total":     int,
          "template_pending": bool,    # only present when True
        }
    """
    matches: List[dict] = []

    # Build a single searchable text from operations + lines of business + raw OCR.
    ops    = (_fv(facts, "operations_description") or "").lower()
    lobs   = " ".join(facts.get("lines_of_business") or []).lower()
    cert_h = (_fv(facts, "certificate_holder") or "").lower()
    text   = (text or "").lower()
    search = f"{ops} {lobs} {cert_h} {text}"

    def _already_matched(form_id: str) -> bool:
        return any(m["form_id"] == form_id for m in matches)

    def _add(form_id: str, form_name: str, trigger_weight: float,
             trigger_reason: str, template_pending: bool = False) -> None:
        confidence, reason = _compute_confidence(form_id, facts, trigger_weight, triggered=True)
        entry: dict = {
            "form_id":        form_id,
            "form_name":      form_name,
            "confidence":     confidence,
            "reason":         reason,
            "trigger_reason": trigger_reason,
        }
        # Expose raw counts so the frontend can render "12 of 18 fields"
        _, filled, total = _score_field_coverage(form_id, facts)
        entry["fields_filled"] = filled
        entry["fields_total"]  = total
        if template_pending:
            entry["template_pending"] = True
        matches.append(entry)

    # ── Always required ────────────────────────────────────────────────────────
    _add("ACORD_125",
         "ACORD 125 - Commercial Insurance Application",
         trigger_weight=1.0,
         trigger_reason="Always required for any commercial submission")

    # ── Flag-based (trigger_weight 0.95) ──────────────────────────────────────

    if flags.get("has_general_liability") or flags.get("is_contractor"):
        _add("ACORD_126",
             "ACORD 126 - Commercial General Liability Section",
             trigger_weight=0.95,
             trigger_reason="has_general_liability or is_contractor flag detected")

    if flags.get("has_workers_comp"):
        _add("ACORD_130",
             "ACORD 130 - Workers Compensation Application",
             trigger_weight=0.95,
             trigger_reason="has_workers_comp flag detected",
             template_pending=True)

    if flags.get("has_auto_coverage"):
        _add("ACORD_127",
             "ACORD 127 - Business Auto Section",
             trigger_weight=0.95,
             trigger_reason="has_auto_coverage flag detected",
             template_pending=True)

    if flags.get("has_umbrella"):
        _add("ACORD_131",
             "ACORD 131 - Umbrella / Excess Liability",
             trigger_weight=0.95,
             trigger_reason="has_umbrella flag detected",
             template_pending=True)

    if flags.get("has_property_coverage"):
        _add("ACORD_140",
             "ACORD 140 - Commercial Property Section",
             trigger_weight=0.95,
             trigger_reason="has_property_coverage flag detected")

    if flags.get("has_property_coverage") and flags.get("has_multiple_locations"):
        _add("ACORD_141",
             "ACORD 141 - Property Schedule",
             trigger_weight=0.95,
             trigger_reason="has_property_coverage and has_multiple_locations flags detected",
             template_pending=True)

    if flags.get("has_certificate_request") or flags.get("is_certificate_doc"):
        _add("ACORD_25",
             "ACORD 25 - Certificate of Liability Insurance",
             trigger_weight=0.95,
             trigger_reason="has_certificate_request or is_certificate_doc flag detected")

    if flags.get("is_contractor"):
        _add("ACORD_186",
             "ACORD 186 - Contractors Supplemental Application",
             trigger_weight=0.95,
             trigger_reason="is_contractor flag detected")

    # ── Keyword / rule-based (trigger_weight 0.85) ────────────────────────────

    _crime_kw = {
        "crime", "employee dishonesty", "money and securities",
        "forgery", "theft", "fidelity", "erisa", "employee theft",
    }
    if any(kw in search for kw in _crime_kw):
        _add("ACORD_137",
             "ACORD 137 - Commercial Crime Application",
             trigger_weight=0.85,
             trigger_reason="crime / dishonesty keywords detected in operations or lines of business")

    _cyber_kw = {
        "cyber", "data breach", "network security", "phi", "pci",
        "ransomware", "privacy liability", "e-commerce", "cloud",
        "personally identifiable", "hipaa",
    }
    if any(kw in search for kw in _cyber_kw):
        _add("ACORD_138",
             "ACORD 138 - Cyber / Network Security Application",
             trigger_weight=0.85,
             trigger_reason="cyber / data breach keywords detected in operations or lines of business")

    # ACORD 101 — Additional Remarks (complex trigger logic unchanged)
    _101_reasons: List[str] = []
    if _fv(facts, "gl_class_codes_by_location") and len(ops) < 30:
        _101_reasons.append("GL class codes present but operations description is vague (<30 chars)")
    _payroll_str = _fv(facts, "total_payroll") or _fv(facts, "wc_payroll")
    _revenue_str = _fv(facts, "total_revenue")
    if _payroll_str and _revenue_str:
        try:
            _pr = float(re.sub(r"[^\d.]", "", str(_payroll_str)))
            _rv = float(re.sub(r"[^\d.]", "", str(_revenue_str)))
            if _rv > 0 and _pr / _rv > 0.85:
                _101_reasons.append("payroll/revenue ratio exceeds 85%")
        except ValueError:
            pass
    _subpct_str = _fv(facts, "percent_subcontracted")
    if _subpct_str:
        try:
            if float(re.sub(r"[^\d.]", "", str(_subpct_str))) > 30 and not _fv(facts, "wc_payroll"):
                _101_reasons.append("subcontract percentage >30% with no WC payroll on file")
        except ValueError:
            pass
    if flags.get("has_loss_history") and not _fv(facts, "num_claims") and not _fv(facts, "total_incurred"):
        _101_reasons.append("loss history flagged but no claim count or incurred amount found")
    _cross_issues = cross_validate(facts, flags, [])
    if _cross_issues:
        _101_reasons.append(
            f"cross-validation flagged {len(_cross_issues)} issue(s) requiring additional remarks"
        )
    if _101_reasons:
        _add("ACORD_101",
             "ACORD 101 - Additional Remarks",
             trigger_weight=0.85,
             trigger_reason="; ".join(_101_reasons),
             template_pending=True)

    _133_kw = {"builder", "builders risk", "under construction", "renovation", "project value", "completion date"}
    if flags.get("has_builders_risk") or any(kw in text for kw in _133_kw):
        _add("ACORD_133",
             "ACORD 133 - Builders Risk Application",
             trigger_weight=0.85,
             trigger_reason="builders risk / construction keywords detected in document text",
             template_pending=True)

    _160_kw = {"floater", "inland marine", "contractor's equipment", "cargo", "motor truck", "transit"}
    if flags.get("has_inland_marine") or any(kw in text for kw in _160_kw):
        _add("ACORD_160",
             "ACORD 160 - Inland Marine Application",
             trigger_weight=0.85,
             trigger_reason="inland marine / equipment / cargo keywords detected in document text",
             template_pending=True)

    # ACORD 186 keyword path — only if not already flag-matched above
    _186_kw = {"contractor", "subcontract", "roofing", "demolition", "scaffolding", "blasting"}
    if (not _already_matched("ACORD_186")
            and flags.get("has_general_liability")
            and any(kw in ops for kw in _186_kw)):
        _add("ACORD_186",
             "ACORD 186 - Contractors Supplemental Application",
             trigger_weight=0.85,
             trigger_reason="GL coverage with contractor-type operations keywords detected")

    # ACORD 25 keyword path — only if not already flag-matched above
    _25_kw = {"certificate holder", "certificate of liability", "coi"}
    if not _already_matched("ACORD_25") and any(kw in text for kw in _25_kw):
        _add("ACORD_25",
             "ACORD 25 - Certificate of Liability Insurance",
             trigger_weight=0.85,
             trigger_reason="certificate keywords detected in document text")

    _28_kw = {"mortgagee", "evidence of insurance", "loss payee"}
    if flags.get("has_property_coverage") and any(kw in text for kw in _28_kw):
        _add("ACORD_28",
             "ACORD 28 - Evidence of Commercial Property Insurance",
             trigger_weight=0.85,
             trigger_reason="mortgagee / loss payee keywords detected with property coverage",
             template_pending=True)

    # ── Sort: blended confidence descending (ACORD_125 naturally stays first) ──
    matches.sort(key=lambda x: x["confidence"], reverse=True)
    return matches


def score_extra_forms(facts: dict, triggered_ids: set, all_forms: List[dict]) -> List[dict]:
    """
    Score every form that was NOT triggered by match_forms_deterministic, so the
    'Add more ACORD forms' section can also show a live field-coverage percentage.

    Returns the same shape as match_forms_deterministic items but with
    trigger_weight=0 (no rule fired) — confidence is pure field_coverage × 0.6.
    Items with confidence=0 (no schema + not triggered) are still returned so
    the UI can list them; they will show 0%.

    Sorted by confidence descending.
    """
    scored: List[dict] = []
    for form in all_forms:
        fid = form["form_id"]
        if fid in triggered_ids:
            continue
        confidence, reason = _compute_confidence(fid, facts, trigger_weight=0.0, triggered=False)
        _, filled, total = _score_field_coverage(fid, facts)
        scored.append({
            "form_id":       fid,
            "form_name":     form.get("form_name", fid),
            "description":   form.get("description", ""),
            "confidence":    confidence,
            "reason":        reason,
            "fields_filled": filled,
            "fields_total":  total,
        })
    scored.sort(key=lambda x: x["confidence"], reverse=True)
    return scored


def match_forms(facts: dict, flags: dict, all_forms: List[dict], text: str = "") -> List[dict]:
    return match_forms_deterministic(facts, flags, text=text)


def process_single_form(form_meta: dict, session: dict) -> dict:
    tpl              = os.path.join(TEMPLATE_DIR, form_meta["template_file"])
    schema           = extract_form_schema(tpl, form_id=form_meta["form_id"])
    mapped, confidence = map_facts_to_form(session["facts"], schema, form_id=form_meta["form_id"])
    selected_ids     = session.get("selected_form_ids", []) + [form_meta["form_id"]]
    cross            = cross_validate(session["facts"], session["flags"], selected_ids)
    sqs              = calculate_sqs(
        facts=session["facts"], flags=session["flags"],
        mapped_data=mapped, form_schema=schema,
        selected_form_ids=[form_meta["form_id"]],
        hard_stops=session.get("hard_stops", []),
        soft_stops=session.get("soft_stops", []),
        tier2_score=session.get("tier2_score", 50),
        form_id=form_meta["form_id"],
        schema_size=len(schema),
        fields_mapped=sum(1 for v in mapped.values() if v is not None and str(v).strip() not in ("", "null", "None")),
    )
    pdf_bytes = fill_pdf(tpl, mapped, confidence)
    return {
        "form_id":    form_meta["form_id"],
        "form_name":  form_meta["form_name"],
        "form":       form_meta,
        "schema":     schema,
        "mapped":     mapped,
        "confidence": confidence,
        "sqs":        sqs,
        "cross":      cross,
        "pdf_bytes":  pdf_bytes,
    }