#form_service.py

import json
import logging
import os
import re
from typing import List, Optional

from config.settings import TEMPLATE_DIR, FORMS_DB_DIR, FORMS_INDEX
from services.extraction_service import _fv
from services.pdf_service import extract_form_schema, map_facts_to_form, fill_pdf
from services.sqs_service import cross_validate, calculate_sqs

logger = logging.getLogger(__name__)


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
    Deterministic rule-based form matching based on the Acordly ACORD Form Decision Tree.

    Replaces the former two-stage (filter + AI) matching for both Assembly and Clarity pipelines.
    Zero LLM calls. Pure flag and keyword logic.

    Parameters
    ----------
    facts : merged fact dict (OCR-confidence envelopes intact)
    flags : boolean flag dict from extraction
    text  : combined lowercased raw OCR text from all uploaded docs; used for
            keyword-based triggers that need to see the full document body
            (builders risk, inland marine, certificate, evidence of property).

    Return shape:
      [{"form_id": ..., "form_name": ..., "confidence": ..., "trigger_reason": ...}]

    Confidence tiers:
      1.0  — always required (ACORD 125)
      0.95 — flag-based match
      0.85 — keyword / rule-based match

    Note: forms without PDF templates in /templates are recommended but cannot be
    generated. They carry "template_pending": True in their match dict so the
    pipeline can surface them as advisory recommendations only.
    """
    matches: List[dict] = []

    # Build a single searchable text from operations + lines of business + raw OCR.
    # `text` is the full lowercased OCR body; `search` is the facts-derived subset.
    ops    = (_fv(facts, "operations_description") or "").lower()
    lobs   = " ".join(facts.get("lines_of_business") or []).lower()
    cert_h = (_fv(facts, "certificate_holder") or "").lower()
    search = f"{ops} {lobs} {cert_h}"
    text   = text.lower()   # normalise; harmless if already lower or empty

    def _already_matched(form_id: str) -> bool:
        return any(m["form_id"] == form_id for m in matches)

    # ── Always required ────────────────────────────────────────────────────────
    matches.append({
        "form_id":        "ACORD_125",
        "form_name":      "ACORD 125 - Commercial Insurance Application",
        "confidence":     1.0,
        "trigger_reason": "Always required for any commercial submission",
    })

    # ── Flag-based (0.95) ──────────────────────────────────────────────────────

    # ACORD 126 — General Liability
    if flags.get("has_general_liability") or flags.get("is_contractor"):
        matches.append({
            "form_id":        "ACORD_126",
            "form_name":      "ACORD 126 - Commercial General Liability Section",
            "confidence":     0.95,
            "trigger_reason": "has_general_liability or is_contractor flag detected",
        })

    # ACORD 130 — Workers Compensation
    if flags.get("has_workers_comp"):
        matches.append({
            "form_id":        "ACORD_130",
            "form_name":      "ACORD 130 - Workers Compensation Application",
            "confidence":     0.95,
            "trigger_reason": "has_workers_comp flag detected",
        })

    # ACORD 127 — Business Auto
    if flags.get("has_auto_coverage"):
        matches.append({
            "form_id":        "ACORD_127",
            "form_name":      "ACORD 127 - Business Auto Section",
            "confidence":     0.95,
            "trigger_reason": "has_auto_coverage flag detected",
        })

    # ACORD 131 — Umbrella / Excess Liability
    if flags.get("has_umbrella"):
        matches.append({
            "form_id":        "ACORD_131",
            "form_name":      "ACORD 131 - Umbrella / Excess Liability",
            "confidence":     0.95,
            "trigger_reason": "has_umbrella flag detected",
        })

    # ACORD 140 — Commercial Property
    if flags.get("has_property_coverage"):
        matches.append({
            "form_id":        "ACORD_140",
            "form_name":      "ACORD 140 - Commercial Property Section",
            "confidence":     0.95,
            "trigger_reason": "has_property_coverage flag detected",
        })

    # ACORD 141 — Property Schedule (only when multiple locations)
    if flags.get("has_property_coverage") and flags.get("has_multiple_locations"):
        matches.append({
            "form_id":        "ACORD_141",
            "form_name":      "ACORD 141 - Property Schedule",
            "confidence":     0.95,
            "trigger_reason": "has_property_coverage and has_multiple_locations flags detected",
        })

    # ACORD 25 — Certificate of Liability Insurance (flag path)
    if flags.get("has_certificate_request") or flags.get("is_certificate_doc"):
        matches.append({
            "form_id":        "ACORD_25",
            "form_name":      "ACORD 25 - Certificate of Liability Insurance",
            "confidence":     0.95,
            "trigger_reason": "has_certificate_request or is_certificate_doc flag detected",
        })

    # ACORD 186 — Contractors Supplement (flag path)
    if flags.get("is_contractor"):
        matches.append({
            "form_id":        "ACORD_186",
            "form_name":      "ACORD 186 - Contractors Supplemental Application",
            "confidence":     0.95,
            "trigger_reason": "is_contractor flag detected",
        })

    # ── Keyword / rule-based (0.85) ────────────────────────────────────────────

    # ACORD 137 — Crime
    _crime_kw = {
        "crime", "employee dishonesty", "money and securities",
        "forgery", "theft", "fidelity", "erisa", "employee theft",
    }
    if any(kw in search for kw in _crime_kw):
        matches.append({
            "form_id":        "ACORD_137",
            "form_name":      "ACORD 137 - Commercial Crime Application",
            "confidence":     0.85,
            "trigger_reason": "crime / dishonesty keywords detected in operations or lines of business",
        })

    # ACORD 138 — Cyber / Network Security
    _cyber_kw = {
        "cyber", "data breach", "network security", "phi", "pci",
        "ransomware", "privacy liability", "e-commerce", "cloud",
        "personally identifiable", "hipaa",
    }
    if any(kw in search for kw in _cyber_kw):
        matches.append({
            "form_id":        "ACORD_138",
            "form_name":      "ACORD 138 - Cyber / Network Security Application",
            "confidence":     0.85,
            "trigger_reason": "cyber / data breach keywords detected in operations or lines of business",
        })

    # ACORD 101 — Additional Remarks
    # Triggered when the submission has unusual complexity that needs a narrative page.
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
    # cross_validate with no form selection catches general submission anomalies
    # (FEIN format errors, missing applicant name, payroll-to-revenue outliers, etc.)
    # that need a remarks page but aren't covered by the fact-level checks above.
    _cross_issues = cross_validate(facts, flags, [])
    if _cross_issues:
        _101_reasons.append(
            f"cross-validation flagged {len(_cross_issues)} issue(s) requiring additional remarks"
        )
    if _101_reasons:
        matches.append({
            "form_id":          "ACORD_101",
            "form_name":        "ACORD 101 - Additional Remarks",
            "confidence":       0.85,
            "trigger_reason":   "; ".join(_101_reasons),
            "template_pending": True,
        })

    # ACORD 133 — Builders Risk
    _133_kw = {
        "builder", "builders risk", "under construction",
        "renovation", "project value", "completion date",
    }
    if flags.get("has_builders_risk") or any(kw in text for kw in _133_kw):
        matches.append({
            "form_id":          "ACORD_133",
            "form_name":        "ACORD 133 - Builders Risk Application",
            "confidence":       0.85,
            "trigger_reason":   "builders risk / construction keywords detected in document text",
            "template_pending": True,
        })

    # ACORD 160 — Inland Marine
    _160_kw = {
        "floater", "inland marine", "contractor's equipment",
        "cargo", "motor truck", "transit",
    }
    if flags.get("has_inland_marine") or any(kw in text for kw in _160_kw):
        matches.append({
            "form_id":          "ACORD_160",
            "form_name":        "ACORD 160 - Inland Marine Application",
            "confidence":       0.85,
            "trigger_reason":   "inland marine / equipment / cargo keywords detected in document text",
            "template_pending": True,
        })

    # ACORD 186 — Contractors Supplemental (keyword path, only if not already flag-matched)
    # Catches GL submissions where the insured uses contractor language without the
    # is_contractor flag being set (e.g., extracted from a dec page that omits it).
    _186_kw = {"contractor", "subcontract", "roofing", "demolition", "scaffolding", "blasting"}
    if (not _already_matched("ACORD_186")
            and flags.get("has_general_liability")
            and any(kw in ops for kw in _186_kw)):
        matches.append({
            "form_id":        "ACORD_186",
            "form_name":      "ACORD 186 - Contractors Supplemental Application",
            "confidence":     0.85,
            "trigger_reason": "GL coverage with contractor-type operations keywords detected",
        })

    # ACORD 25 — Certificate of Liability Insurance (keyword path, only if not already flag-matched)
    _25_kw = {"certificate holder", "certificate of liability", "coi"}
    if not _already_matched("ACORD_25") and any(kw in text for kw in _25_kw):
        matches.append({
            "form_id":        "ACORD_25",
            "form_name":      "ACORD 25 - Certificate of Liability Insurance",
            "confidence":     0.85,
            "trigger_reason": "certificate keywords detected in document text",
        })

    # ACORD 28 — Evidence of Commercial Property Insurance
    _28_kw = {"mortgagee", "evidence of insurance", "loss payee"}
    if flags.get("has_property_coverage") and any(kw in text for kw in _28_kw):
        matches.append({
            "form_id":          "ACORD_28",
            "form_name":        "ACORD 28 - Evidence of Commercial Property Insurance",
            "confidence":       0.85,
            "trigger_reason":   "mortgagee / loss payee keywords detected with property coverage",
            "template_pending": True,
        })

    # ── Sort: confidence descending, ACORD_125 is always first (1.0) ──────────
    matches.sort(key=lambda x: x["confidence"], reverse=True)
    return matches


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