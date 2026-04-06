import json
import logging
import os
from typing import List, Optional

from config.settings import TEMPLATE_DIR, FORMS_DB_DIR, FORMS_INDEX, groq_client
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


def match_forms(facts: dict, flags: dict, all_forms: List[dict]) -> List[dict]:
    candidates = stage1_filter(flags, all_forms) or all_forms
    return stage2_ai_match(facts, flags, candidates)


def process_single_form(form_meta: dict, session: dict) -> dict:
    tpl              = os.path.join(TEMPLATE_DIR, form_meta["template_file"])
    schema           = extract_form_schema(tpl)
    mapped, confidence = map_facts_to_form(session["facts"], schema)
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