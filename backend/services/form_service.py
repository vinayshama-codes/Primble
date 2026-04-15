import json
import logging
import os
from typing import List, Optional

from config.settings import TEMPLATE_DIR, FORMS_DB_DIR, FORMS_INDEX, groq_client
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
    return [f for f in forms if os.path.exists(os.path.join(TEMPLATE_DIR, f.get("template_file", "")))]


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


def stage2_ai_match(facts: dict, flags: dict, candidates: List[dict]) -> List[dict]:
    slim   = [{"form_id": f["form_id"], "form_name": f["form_name"], "description": f.get("description", ""),
               "matching_keywords": f.get("matching_keywords", [])} for f in candidates]
    prompt = (
        "You are a carrier-grade insurance submission expert.\n"
        "Rank these candidate ACORD forms by relevance. Only use forms from the list.\n\n"
        "Rules:\n- ACORD_125 always required first\n- ACORD_126 if GL present\n"
        "- ACORD_140 if property present\n- ACORD_25 only if certificate holder explicitly requested\n\n"
        f"Facts: {json.dumps(facts, indent=2)}\nFlags: {json.dumps(flags, indent=2)}\n"
        f"Candidates: {json.dumps(slim, indent=2)}\n\n"
        'Return ONLY a raw JSON array sorted by confidence descending.\n'
        '[{"form_id":"ACORD_XXX","form_name":"...","confidence":0.95,"reason":"one sentence"}]'
    )
    try:
        r   = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = (r.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = raw.replace("```json", "").replace("```", "").strip()
        s, e = raw.find("["), raw.rfind("]")
        recs = json.loads(raw[s : e + 1]) if s != -1 and e != -1 else []
        if not isinstance(recs, list):
            recs = []
        valid_ids    = {f["form_id"] for f in candidates}
        recs         = [r for r in recs if r.get("form_id") in valid_ids]
        is_cert_only = flags.get("is_certificate_doc") and not flags.get("is_commercial_policy")
        if not is_cert_only and not any(r.get("form_id") == "ACORD_125" for r in recs):
            a125 = next((f for f in candidates if f["form_id"] == "ACORD_125"), None)
            if a125:
                recs.insert(0, {"form_id": "ACORD_125", "form_name": a125["form_name"], "confidence": 0.99, "reason": "Always required"})
        recs.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        return recs
    except Exception as ex:
        logger.error(f"Stage 2 error: {ex}")
        return [{"form_id": "ACORD_125", "form_name": "ACORD 125 - Commercial Insurance Application", "confidence": 0.99, "reason": "Default"}]


def match_forms_deterministic(facts: dict, flags: dict) -> List[dict]:
    """
    Deterministic rule-based form matching based on the Acordly ACORD Form Decision Tree.

    Replaces stage1_filter() + stage2_ai_match() for both Assembly and Clarity pipelines.
    Zero LLM calls. Pure flag and keyword logic.

    Return shape is identical to stage2_ai_match() so nothing downstream breaks:
      [{"form_id": ..., "form_name": ..., "confidence": ..., "trigger_reason": ...}]

    Confidence tiers:
      1.0  — always required (ACORD 125)
      0.95 — flag-based match
      0.85 — keyword-based match

    Note: ACORD 186, 137, 138 are included in matching output but do not yet have
    PDF templates in /templates. Pipeline must guard against missing template_file.
    """
    matches: List[dict] = []

    # Build a single searchable text from operations + lines of business
    ops      = (_fv(facts, "operations_description") or "").lower()
    lobs     = " ".join(facts.get("lines_of_business") or []).lower()
    cert_h   = (_fv(facts, "certificate_holder") or "").lower()
    search   = f"{ops} {lobs} {cert_h}"

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

    # ACORD 25 — Certificate of Liability Insurance
    if flags.get("has_certificate_request") or flags.get("is_certificate_doc"):
        matches.append({
            "form_id":        "ACORD_25",
            "form_name":      "ACORD 25 - Certificate of Liability Insurance",
            "confidence":     0.95,
            "trigger_reason": "has_certificate_request or is_certificate_doc flag detected",
        })

    # ACORD 186 — Contractors Supplement
    if flags.get("is_contractor"):
        matches.append({
            "form_id":        "ACORD_186",
            "form_name":      "ACORD 186 - Contractors Supplement",
            "confidence":     0.95,
            "trigger_reason": "is_contractor flag detected",
        })

    # ── Keyword-based (0.85) ───────────────────────────────────────────────────

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

    # ── Sort: confidence descending, ACORD_125 is always first (1.0) ──────────
    matches.sort(key=lambda x: x["confidence"], reverse=True)
    return matches


def match_forms(facts: dict, flags: dict, all_forms: List[dict]) -> List[dict]:
    return match_forms_deterministic(facts, flags)


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