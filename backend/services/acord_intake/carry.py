"""Boxes an uploaded ACORD form filled that no fact sits behind (Y/N answers,
form-only details) are CARRIED onto the same form when we generate it.

Rule: a carried value prints in its own box on its own form (instance) when the
engine printed nothing there or only an AI guess. A value the engine printed
from a fact is never replaced - the fact is the package's truth. Two uploaded
copies of one form with different values for a box: the box is not carried
(blank over wrong). Label "filled": the value is stated by an uploaded document.
Never raises.
"""
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)
LABEL = "filled"


def carried_for(docs: List[dict], form_id: str) -> Dict[str, str]:
    """{box: value} the active uploaded ACORD documents carry for `form_id`."""
    seen: Dict[str, set] = {}
    for d in docs or []:
        if not isinstance(d, dict) or d.get("excluded"):
            continue
        for key, boxes in ((d.get("acord") or {}).get("carried") or {}).items():
            if key != form_id or not isinstance(boxes, dict):
                continue
            for box, v in boxes.items():
                if str(v or "").strip():
                    seen.setdefault(box, set()).add(str(v).strip())
    return {box: next(iter(vals)) for box, vals in seen.items() if len(vals) == 1}


# The labels an AI box keeps when it is carried back (28 Oct 2026): the label it
# had on the package that printed it - "Please verify" stays "Please verify".
# Carried as "filled", our own guess came back as a document's value: full
# fill-rate credit and no Confirm row.
_AI_CARRY_LABELS = ("ai_verified", "low_confidence")


def carried_ai_labels(docs: List[dict], form_id: str) -> Dict[str, str]:
    """{box: label} for the carried boxes that are AI fills on EVERY active
    uploaded copy carrying them (a box an outside form states too is that
    form's statement)."""
    ai: Dict[str, str] = {}
    stated: set = set()
    for d in docs or []:
        if not isinstance(d, dict) or d.get("excluded"):
            continue
        rec = d.get("acord") or {}
        mine = set((rec.get("carried_ai") or {}).get(form_id) or [])
        labels = rec.get("ai_labels") or {}
        for box, v in ((rec.get("carried") or {}).get(form_id) or {}).items():
            if not str(v or "").strip():
                continue
            if box in mine:
                lab = str(labels.get(box) or "")
                ai.setdefault(box, lab if lab in _AI_CARRY_LABELS else "low_confidence")
            else:
                stated.add(box)
    return {b: lab for b, lab in ai.items() if b not in stated}


TRANSCRIBER_LABEL = "ai_verified"


def carried_transcriber_boxes(docs: List[dict], form_id: str) -> set:
    """The carried boxes ONLY an ASG Transcriber reading states (an exact box
    read of another uploaded copy stating it too makes it that form's
    statement) - printed "please verify", never "filled" (29 Oct 2026)."""
    ocr: set = set()
    stated: set = set()
    for d in docs or []:
        if not isinstance(d, dict) or d.get("excluded"):
            continue
        rec = d.get("acord") or {}
        mine = set((rec.get("carried_transcriber") or {}).get(form_id) or [])
        for box, v in ((rec.get("carried") or {}).get(form_id) or {}).items():
            if str(v or "").strip():
                (ocr if box in mine else stated).add(box)
    return ocr - stated


def _package_contexts(facts: dict) -> List[dict]:
    """The stamp facts under the form alone and under every form - built once
    per form, so the stamper's per-facts memo (the prior grid) is reused."""
    try:
        from services.acord_intake.recognize import schema_names
        every = sorted(schema_names())
    except Exception:                                          # noqa: BLE001
        every = []
    form = str(facts.get("_form_id") or "")
    return [{**facts, "_package_form_ids": pkg} for pkg in ([form] if form else [], every) if pkg]


def _blank_by_package_rule(box: str, facts: dict, contexts: List[dict], owned_blank) -> bool:
    """Does an owner leave this box blank BECAUSE of which forms this package
    holds (ACORD 186's "* do not answer if attached to ACORD 126")? Asked by the
    owner's own answer under the package as it is, the form alone and every
    form: blank now and not blank under one of the others = a package rule,
    which beats the uploaded form's value. An owner that is blank for want of a
    FACT is not a rule against the uploaded form's own typed value - blocking
    those lost the excess 131's underlying schedule, the 125's audit code, the
    126's EBL count and the 137's symbol rows on the Choice Electric round trip
    (re-review, 27 Oct 2026)."""
    if not owned_blank(box, facts):
        return False
    return any(not owned_blank(box, ctx) for ctx in contexts)


def apply_carried(mapped: dict, confidence: dict, docs: List[dict], form_id: str,
                  facts: dict = None) -> List[str]:
    try:
        from services.pdf_service import _with_grid_memo
    except Exception:                                          # noqa: BLE001
        return _apply_carried(mapped, confidence, docs, form_id, facts)
    return _with_grid_memo(_apply_carried)(mapped, confidence, docs, form_id, facts)


def _apply_carried(mapped: dict, confidence: dict, docs: List[dict], form_id: str,
                   facts: dict = None) -> List[str]:
    """`facts` (the form's stamp facts, with `_form_id` / `_package_form_ids`):
    a box an owner leaves blank by a PACKAGE rule (ACORD 186's starred questions
    beside a 126) is never filled (`_blank_by_package_rule`)."""
    out: List[str] = []
    try:
        carried = carried_for(docs, form_id)
        if not carried:
            return out
        ai_labels = carried_ai_labels(docs, form_id)
        ocr_boxes = carried_transcriber_boxes(docs, form_id)
        owned_blank, contexts = None, []
        if facts is not None:
            try:
                from services.pdf_service import _owned_blank_claim as owned_blank
                contexts = _package_contexts(facts)
            except Exception:                                  # noqa: BLE001
                owned_blank = None
        for box, value in carried.items():
            held = mapped.get(box)
            label = (confidence or {}).get(box)
            label = label.get("label") if isinstance(label, dict) else label
            if not (held in (None, "", "Off") or str(label or "").startswith("ai")):
                continue                     # a fact's value: never replaced, nothing to ask
            if owned_blank is not None:
                try:
                    if _blank_by_package_rule(box, facts, contexts, owned_blank):
                        continue
                except Exception:                              # noqa: BLE001
                    pass
            mapped[box] = value
            label, source = ((ai_labels[box], "ai") if box in ai_labels else
                             (TRANSCRIBER_LABEL, "acord_transcriber") if box in ocr_boxes else
                             (LABEL, "acord_form"))
            if isinstance((confidence or {}).get(box), dict):
                confidence[box] = dict(confidence[box], label=label, source=source)
            elif box in ai_labels or box in ocr_boxes:
                confidence[box] = label          # the AI path's own shape: a bare label
            else:
                confidence[box] = {"label": LABEL, "source": "acord_form"}
            out.append(box)
        if out:
            logger.info("acord carry: %s - %d box(es) from the uploaded form", form_id, len(out))
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("acord carry skipped for %s: %s", form_id, ex)
    return out
