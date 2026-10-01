"""signature_boxes.py - ONE door for "whose signature, date or initials go in
this box" (1 Oct 2026, owner's live run before the client demo).

THE DEFECT. The viewer's Sign button painted the producer's saved signature
into EVERY signature box, because the painter
(`pdf_service.inject_signature_into_pdf`) asks one question -
`_is_signature_field(name)` - and `NamedInsured_Signature_A` answers yes. So
on ACORD 125 / 126 / 127 / 131 / 137 the APPLICANT's signature line carried
the producer's signature: a document the applicant never signed, presented as
signed by them.

ACORD says whose box it is, in its own words. Every signature-block box in the
17 schemas carries one of these tooltips (enumerated 1 Oct 2026):

* "Sign here: Accommodates the signature of the authorized representative
  (e.g., producer, agent, broker, etc.) ..."            - the producer
* "Sign here: Accommodates the signature of the applicant or named insured."
                                                        - the applicant
* "Enter date: The date the form was signed by the applicant or named insured"
  / "... signed by the producer, agent, broker, etc."   - that party's date
* "Initial here: The named insured's initials."         - the applicant
* "Enter text: The name of the authorized representative of the producer ...
  that signed the form."                                - the producer's name

and the field's leading name segment agrees (`Producer_...`,
`NamedInsured_...`). The party is read from the tooltip first; the name is
the fallback and the cross-check - when the two disagree the box belongs to
nobody we can prove, and nothing is painted there (blank over wrong).

The Sign button signs for the PRODUCER only. Nothing here fills a date: the
Sign button never did.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

SIGNER_PRODUCER = "producer"
SIGNER_APPLICANT = "applicant"

KIND_SIGNATURE = "signature"
KIND_DATE = "date"
KIND_INITIALS = "initials"
KIND_PRINTED_NAME = "printed_name"

# Stored on a generated form when the Sign button painted the producer's boxes
# only. A signed form WITHOUT it was signed before 1 Oct 2026, when every box
# got the producer's signature - its cached PDF is never served again.
SIGNATURE_SCOPE = SIGNER_PRODUCER

_SIGN_TIP = re.compile(r"^\s*sign here\s*:", re.IGNORECASE)
_INITIAL_TIP = re.compile(r"^\s*initial here\s*:", re.IGNORECASE)
# "The date the form was signed by ..." - the date beside a signature.
_SIGNED_DATE_TIP = re.compile(r"\bdate\b[^.]{0,40}\bsigned\b", re.IGNORECASE)
# "The name of the authorized representative ... that signed the form."
_SIGNER_NAME_TIP = re.compile(r"\bname\b[^.]*\b(?:that|who) signed\b", re.IGNORECASE)
_AS_USED = re.compile(r"\bas used here\b", re.IGNORECASE)

_APPLICANT_WORDS = re.compile(r"\b(?:applicant|named insured|insured)\b", re.IGNORECASE)
_PRODUCER_WORDS = re.compile(
    r"\b(?:producer|agent|broker|agency|authorized representative)\b", re.IGNORECASE)

# ACORD's leading entity segment of a field name.
_APPLICANT_SEGMENTS = frozenset({"namedinsured", "applicant", "insured"})
_PRODUCER_SEGMENTS = frozenset({"producer", "agent", "broker", "agency"})


def _party_in_text(text: str) -> Optional[str]:
    """The party the tooltip names FIRST - the signer. ACORD 133's applicant
    tooltip later says "signed by an officer, owner or partner"; the producer's
    names "the company(ies) listed" - neither changes who the first words say."""
    text = _AS_USED.split(text or "", 1)[0]
    a = _APPLICANT_WORDS.search(text)
    p = _PRODUCER_WORDS.search(text)
    if a and (not p or a.start() < p.start()):
        return SIGNER_APPLICANT
    if p:
        return SIGNER_PRODUCER
    return None


def _party_in_name(field: str) -> Optional[str]:
    seg = (field or "").split("_", 1)[0].lower()
    if seg in _APPLICANT_SEGMENTS:
        return SIGNER_APPLICANT
    if seg in _PRODUCER_SEGMENTS:
        return SIGNER_PRODUCER
    return None


def _kind(field: str, tooltip: str, field_type: str) -> Optional[str]:
    tip = tooltip or ""
    if _SIGN_TIP.match(tip):
        return KIND_SIGNATURE
    if _INITIAL_TIP.match(tip):
        return KIND_INITIALS
    if _SIGNED_DATE_TIP.search(tip):
        return KIND_DATE
    if _SIGNER_NAME_TIP.search(tip):
        return KIND_PRINTED_NAME
    low = (field or "").lower()
    if "signaturedate" in low or "signeddate" in low or "datesigned" in low:
        return KIND_DATE
    if "initials" in low:
        return KIND_INITIALS
    try:
        from services.pdf_service import _is_signature_field
        if _is_signature_field(field or "", field_type or ""):
            return KIND_SIGNATURE
    except Exception:                                      # pragma: no cover
        pass
    return None


def signature_box(field: str, tooltip: str = "", field_type: str = "") -> Optional[Tuple[str, Optional[str]]]:
    """(kind, signer) for a signature-block box, or None for any other box.

    kind: signature / date / initials / printed_name. signer: "producer",
    "applicant", or None when it cannot be proven - no party word and no
    party name segment, or the tooltip and the name disagree."""
    kind = _kind(field, tooltip, field_type)
    if kind is None:
        return None
    by_tip = _party_in_text(tooltip)
    by_name = _party_in_name(field)
    if by_tip and by_name and by_tip != by_name:
        return kind, None
    return kind, (by_tip or by_name)


def signer_of(field: str, tooltip: str = "", field_type: str = "") -> Optional[str]:
    box = signature_box(field, tooltip, field_type)
    return box[1] if box else None


def is_producer_signature(field: str, tooltip: str = "", field_type: str = "") -> bool:
    """The boxes the Sign button paints: a SIGNATURE box whose signer is the
    producer."""
    return signature_box(field, tooltip, field_type) == (KIND_SIGNATURE, SIGNER_PRODUCER)


def is_applicant_step(field: str, tooltip: str = "") -> bool:
    """A box the applicant completes when signing: their signature, its date,
    their initials. Never the producer's to fill in."""
    box = signature_box(field, tooltip)
    return bool(box) and box[1] == SIGNER_APPLICANT and box[0] in (
        KIND_SIGNATURE, KIND_DATE, KIND_INITIALS)


def _tooltip(schema: Optional[dict], field: str) -> str:
    meta = (schema or {}).get(field)
    return str((meta or {}).get("tu") or "") if isinstance(meta, dict) else ""


def _field_type(schema: Optional[dict], field: str) -> str:
    meta = (schema or {}).get(field)
    return str((meta or {}).get("ft") or "") if isinstance(meta, dict) else ""


def producer_signature_fields(fields: Iterable[str], schema: Optional[dict]) -> List[str]:
    """The producer signature boxes among `fields`, read against the form's
    schema (its tooltips)."""
    return [f for f in (fields or [])
            if is_producer_signature(f, _tooltip(schema, f), _field_type(schema, f))]


def _schema_for(form_id: str, stored: Optional[dict]) -> dict:
    if isinstance(stored, dict) and stored:
        return stored
    try:
        from services.needs_attention import _schema_from_disk
        return _schema_from_disk(form_id) or {}
    except Exception:                                      # pragma: no cover
        return {}


def mark_producer_boxes_signed(form_id: str, generated_form: dict,
                               field_data: dict, confidence: dict,
                               skip: Iterable[str] = ()) -> List[str]:
    """What apply-signature has always done to a signed box - store it blank
    (the image is painted, not typed) and label it "filled" - for the
    PRODUCER's signature boxes only. The applicant's boxes keep their value
    and label. Returns the boxes marked."""
    schema = _schema_for(form_id, (generated_form or {}).get("schema"))
    skip = set(skip or ())
    marked = []
    for fn in producer_signature_fields(list(field_data.keys()), schema):
        if fn in skip:
            continue
        field_data[fn] = ""
        confidence[fn] = "filled"
        marked.append(fn)
    return marked


# ── Painting the producer's signature, and only there ─────────────────────────

_HOLD_PREFIX = "__primble_hold_"


def _walk_fields(arr) -> Iterable[Any]:
    for item in list(arr or []):
        yield item
        try:
            kids = item.get("/Kids")
        except Exception:                                  # noqa: BLE001
            kids = None
        if kids:
            yield from _walk_fields(kids)


def _hide_other_signature_boxes(pdf_bytes: bytes) -> Tuple[bytes, Dict[str, Tuple[str, Optional[str]]]]:
    """Rename every signature box that is NOT the producer's, so the painter
    (which decides by name) passes it by and keeps it in the AcroForm. A /Sig
    box is shown to it as /Tx for the same reason. Returns the new bytes and
    {placeholder: (original name, original /FT or None)}."""
    import pikepdf
    from services.pdf_service import _is_signature_field
    held: Dict[str, Tuple[str, Optional[str]]] = {}
    pdf = pikepdf.open(io.BytesIO(pdf_bytes))
    try:
        acro = pdf.Root.get("/AcroForm")
        fields = acro.get("/Fields") if acro is not None else None
        if not fields:
            return pdf_bytes, held
        taken = set()
        for item in _walk_fields(fields):
            t = item.get("/T")
            if t is not None:
                taken.add(str(t))
        n = 0
        for item in _walk_fields(fields):
            t = item.get("/T")
            if t is None:
                continue
            name = str(t)
            ft_obj = item.get("/FT")
            ft = str(ft_obj) if ft_obj is not None else ""
            if not _is_signature_field(name, ft):
                continue
            tu = str(item.get("/TU") or "")
            if is_producer_signature(name, tu, ft):
                continue
            while f"{_HOLD_PREFIX}{n}" in taken:
                n += 1
            ph = f"{_HOLD_PREFIX}{n}"
            taken.add(ph)
            held[ph] = (name, ft if "/Sig" in ft else None)
            item["/T"] = pikepdf.String(ph)
            if "/Sig" in ft:
                item["/FT"] = pikepdf.Name("/Tx")
        if not held:
            return pdf_bytes, held
        out = io.BytesIO()
        pdf.save(out)
        return out.getvalue(), held
    finally:
        pdf.close()


def _restore_held_boxes(pdf_bytes: bytes, held: Dict[str, Tuple[str, Optional[str]]]) -> bytes:
    import pikepdf
    pdf = pikepdf.open(io.BytesIO(pdf_bytes))
    try:
        acro = pdf.Root.get("/AcroForm")
        fields = acro.get("/Fields") if acro is not None else None
        restored = 0
        for item in _walk_fields(fields or []):
            t = item.get("/T")
            if t is None or str(t) not in held:
                continue
            name, ft = held[str(t)]
            item["/T"] = pikepdf.String(name)
            if ft:
                item["/FT"] = pikepdf.Name(ft)
            restored += 1
        if restored != len(held):
            # A box we hid did not come back: the painter changed the form in a
            # way this door does not know. Never ship a renamed box.
            raise RuntimeError(f"signature boxes: restored {restored} of {len(held)}")
        out = io.BytesIO()
        pdf.save(out)
        return out.getvalue()
    finally:
        pdf.close()


def inject_producer_signature(template_path: str, field_data: dict, confidence: dict,
                              signature_b64: str, existing_pdf_bytes: Optional[bytes] = None) -> bytes:
    """`pdf_service.inject_signature_into_pdf`, painting the producer's
    signature boxes only. The applicant's signature, date and initials boxes
    stay fillable form fields, exactly as an unsigned form has them."""
    from services.pdf_service import fill_pdf, inject_signature_into_pdf
    filled = existing_pdf_bytes if existing_pdf_bytes is not None \
        else fill_pdf(template_path, field_data, confidence)
    hidden, held = _hide_other_signature_boxes(filled)
    painted = inject_signature_into_pdf(template_path, field_data, confidence,
                                        signature_b64, hidden)
    if not held:
        return painted
    return _restore_held_boxes(painted, held)


def regenerate_pdf_for_form(proc_session: dict, form_id: str, force: bool = False,
                            user_signature: Optional[str] = None) -> bytes:
    """`pdf_service.regenerate_pdf_for_form` for every caller that serves or
    downloads a form: a signed form is re-painted on the producer's boxes only.
    An unsigned form goes through the original untouched. A signed form's
    cached PDF is reused only when this door made it (`SIGNATURE_SCOPE`)."""
    from services.pdf_service import regenerate_pdf_for_form as _regenerate
    generated = (proc_session or {}).get("generated_forms") or {}
    r = generated.get(form_id)
    if not isinstance(r, dict) or not r.get("signature_applied"):
        return _regenerate(proc_session, form_id, force, user_signature)
    sig_b64 = r.get("signature_b64") or user_signature
    if not sig_b64:
        return _regenerate(proc_session, form_id, force, user_signature)
    if (not force and r.get("pdf_bytes") and r.get("_pdf_cache_hash")
            and r.get("signature_scope") == SIGNATURE_SCOPE):
        cached = r["pdf_bytes"]
        return cached if isinstance(cached, bytes) else bytes(cached)
    from config.settings import TEMPLATE_DIR
    tpl = os.path.join(TEMPLATE_DIR, r["form"]["template_file"])
    field_data = r.get("field_state") or r.get("mapped", {})
    confidence = r.get("confidence", {})
    pdf_bytes = inject_producer_signature(tpl, field_data, confidence, sig_b64)
    r["pdf_bytes"] = pdf_bytes
    r["_pdf_cache_hash"] = hashlib.md5(json.dumps(field_data, sort_keys=True).encode()).hexdigest()
    r["signature_scope"] = SIGNATURE_SCOPE
    return pdf_bytes
