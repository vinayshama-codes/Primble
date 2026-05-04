"""Single source of truth for the OCR → extraction → form-matching pipeline.

Called by both form_routes.py (inline route handler) and worker.py
(background job). Returns a plain dict so callers can use the results
without importing any extra types.

Return keys
-----------
session_id          : str
processed_docs      : list[dict]
primary             : dict
merged_facts        : dict
mflags              : dict
tier1_ok            : bool
tier1_missing       : list
tier2_score         : float | int
tier2_missing       : list
hard_stops          : list
soft_stops          : list
doc_conflicts       : list[dict]  — structured conflicts parsed from consistency issues
recommendations     : list[dict]
extra_forms_scored  : list[dict]
unique_low_conf     : list
available_forms     : list[dict]
"""
import logging
import os
from typing import Any

from services.ocr_service import extract_text
from services.extraction_service import (
    extract_facts_long, identify_doc_type, merge_facts, select_primary_truth,
)
from services.form_service import (
    filter_available_forms, load_all_forms, match_forms, score_extra_forms,
)
from services.sqs_service import (
    check_tier1, check_tier2, evaluate_stops, check_doc_consistency,
)
from repositories.session_repository import new_processing_session

logger = logging.getLogger(__name__)


async def run_extraction_pipeline(file_paths: list[str], user_id: Any) -> dict:
    """Run OCR, extraction, validation, and form-matching for *file_paths*.

    Raises ``ValueError`` when no readable text is found (callers translate
    this into an appropriate error response or job failure).
    """
    processed_docs: list[dict] = []
    all_low_conf:   list       = []

    for path in file_paths:
        text, low_conf = await extract_text(path)
        if len(text) < 30:
            continue
        all_low_conf += low_conf
        doc_type       = identify_doc_type(text)
        extracted      = await extract_facts_long(text, doc_type, low_confidence_tokens=low_conf)
        processed_docs.append({
            "filename":              os.path.basename(path),
            "path":                  path,
            "doc_type":              doc_type,
            "text":                  text,
            "facts":                 extracted.get("facts", {}),
            "flags":                 extracted.get("flags", {}),
            "low_confidence_tokens": low_conf,
            "truncation_warning":    extracted.get("truncation_warning"),
        })

    if not processed_docs:
        raise ValueError("no_readable_text")

    primary              = select_primary_truth(processed_docs)
    merged_facts, mflags = merge_facts(processed_docs, primary)
    mflags["_doc_type"]  = primary.get("doc_type", "unknown")

    tier1_ok, tier1_missing = check_tier1(merged_facts, mflags)

    tier2_score, tier2_missing = check_tier2(merged_facts)
    hard_stops, soft_stops     = evaluate_stops(merged_facts, mflags)

    consistency_issues = check_doc_consistency(processed_docs)
    doc_conflicts: list[dict] = []
    if consistency_issues:
        logger.warning("Doc consistency issues: %s", consistency_issues)
        for issue in consistency_issues:
            if issue.startswith("[hard_stop]"):
                rest      = issue[len("[hard_stop]"):].strip()
                code_part, _, msg = rest.partition(" ")
                code      = code_part.split("=", 1)[1] if "=" in code_part else "conflict"
                doc_conflicts.append({"code": code, "message": msg, "hard_stop": True})
                hard_stops = list(hard_stops) + [msg]
            else:
                hard_stops = list(hard_stops) + [issue]

    all_forms       = load_all_forms()
    available_forms = filter_available_forms(all_forms)
    combined_text   = " ".join(d.get("text", "") for d in processed_docs)
    recommendations = match_forms(merged_facts, mflags, available_forms, text=combined_text)

    triggered_ids      = {r["form_id"] for r in recommendations}
    extra_forms_scored = score_extra_forms(merged_facts, triggered_ids, available_forms)
    unique_low_conf    = list(dict.fromkeys(all_low_conf))

    sid = await new_processing_session({
        "user_id":              user_id,
        "docs":                 processed_docs,
        "primary_doc":          primary["filename"],
        "facts":                merged_facts,
        "flags":                mflags,
        "tier2_score":          tier2_score,
        "tier2_missing":        tier2_missing,
        "hard_stops":           hard_stops,
        "soft_stops":           soft_stops,
        "all_forms":            available_forms,
        "recommendations":      recommendations,
        "selected_form_ids":    [],
        "generated_forms":      {},
        "low_confidence_tokens": unique_low_conf,
    })

    return {
        "session_id":        sid,
        "processed_docs":    processed_docs,
        "primary":           primary,
        "merged_facts":      merged_facts,
        "mflags":            mflags,
        "tier1_ok":          tier1_ok,
        "tier1_missing":     tier1_missing,
        "tier2_score":       tier2_score,
        "tier2_missing":     tier2_missing,
        "hard_stops":        hard_stops,
        "soft_stops":        soft_stops,
        "doc_conflicts":     doc_conflicts,
        "recommendations":   recommendations,
        "extra_forms_scored": extra_forms_scored,
        "unique_low_conf":   unique_low_conf,
        "available_forms":   available_forms,
    }
