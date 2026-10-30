"""The one seam between `extraction_pipeline.extract_document` and the ACORD reader.

read_for_document(path, text) -> None (not an ACORD document - today's path) or
  {"classification": {...} | None,   the document type an ACORD form gives it
   "other_text": str,                 the pages the model still reads ("" = none)
   "facts": {...},                    exact facts read by box name
   "flags": {...},                    coverage flags those facts state
   "record": {...}}                   stored on the document as doc["acord"]

overlay_facts(extracted, acord): the exact facts win over anything the model
read on the same document; flags are OR-ed in.
"""
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# The document type an ACORD form takes, so every role rule downstream (proposal
# roles, Data Consistency's proposed-term skip, the certificate's producer-only
# contact block) treats it as what it is.
_DOC_TYPE_FOR = {"ACORD_125": "application", "ACORD_25": "certificate", "ACORD_28": "certificate"}
_PAGE_MARK_RE = re.compile(r"\[Document page (\d+)\]")
# lob_canon family -> the coverage flags the rest of the system reads.
_FAMILY_FLAGS = {
    "general_liab": ("has_general_liability",),
    "auto": ("has_auto_coverage", "has_commercial_auto"),
    "workers_comp": ("has_workers_comp",),
    "umbrella": ("has_umbrella",),
    "property": ("has_property_coverage",),
    "inland_marine": ("has_inland_marine",),
    "crime": ("has_crime",),
    "cyber": ("has_cyber",),
}


def _pages_of(text: str) -> Dict[int, str]:
    """{1-based page: text}. A text with no marker is one page."""
    parts = _PAGE_MARK_RE.split(text or "")
    if len(parts) < 3:
        return {1: text or ""}
    out: Dict[int, str] = {}
    lead = parts[0]
    for i in range(1, len(parts) - 1, 2):
        out[int(parts[i])] = parts[i + 1]
    if lead.strip():
        out[1] = lead + out.get(1, "")
    return out


# A section form IS its line's application: an uploaded ACORD 126 applies for
# General Liability whatever else it states (ACORD's own form titles). One
# table, shared with the reverse map's header rule (`reverse_map.FORM_FAMILIES`).
from services.acord_intake.reverse_map import FORM_FAMILIES as _FORM_FAMILIES  # noqa: E402


def _flags_from(facts: Dict[str, Any], form_ids=()) -> Dict[str, bool]:
    flags: Dict[str, bool] = {}
    for fid in form_ids or ():
        for fam in _FORM_FAMILIES.get(fid, ()):
            for flag in _FAMILY_FLAGS.get(fam, ()):
                flags[flag] = True
    try:
        from services.lob_canon import canon_line
    except Exception:                                          # noqa: BLE001
        return flags
    names = []
    lob = facts.get("lines_of_business")
    names.extend(lob if isinstance(lob, list) else [])
    for row in facts.get("coverage_lines") or []:
        if isinstance(row, dict) and row.get("line"):
            names.append(row["line"])
    # Never the PRIOR CARRIER grid: a line's has_* flag means "part of THIS
    # submission" (CLAUDE.md), and a property policy that ended in 2023 set
    # has_property_coverage - and with it the COPE hard stop - on a GL-only
    # application (review, 27 Oct 2026).
    for name in names:
        fam = canon_line(str(name)) or ""
        for flag in _FAMILY_FLAGS.get(fam, ()):
            flags[flag] = True
    return flags


def _summary_result(path: str) -> Optional[dict]:
    """Primble's own SQS summary (the cover page of a download) carrying its
    record: no model reads it - its text is Primble's output, never evidence -
    and its record restores the package's answers / tables / stores at the merge
    (`merge_rules.restoring_docs` decides whose package it is)."""
    try:
        from services.acord_intake import primble_record
        rec = primble_record.read(path)
        if not (isinstance(rec, dict) and rec.get("form") == primble_record.SUMMARY_FORM):
            return None
        payload = primble_record.summary_payload(rec)
    except Exception as ex:                                    # noqa: BLE001
        logger.info("acord intake: summary record skipped for %s: %s", path, ex)
        return None
    record = {"forms": [], "pages": [], "carried": {}, "primble_record": bool(payload),
              "primble_summary": True}
    if payload:
        record["restored"] = primble_record.seal_restored(payload)
    return {"classification": {"doc_type": "primble_summary", "confidence": "high",
                               "source": "primble_record", "scores": {}, "narrative_categories": []},
            "other_text": "", "facts": {}, "flags": {}, "record": record}


def read_for_document(path: str, text: str, transcriber: Any = None) -> Optional[dict]:
    """`transcriber`: a `transcriber_intake.GroupResult` for this document (ASG
    Transcriber's reading of its ACORD pages, 29 Oct 2026) - folded into the same
    reading; an image upload is read from it alone."""
    is_pdf = str(path or "").lower().endswith(".pdf")
    t_copies: list = []
    if transcriber is not None and getattr(transcriber, "result", None) is not None:
        from services.acord_intake.transcriber_intake import copies_from
        t_copies = copies_from(transcriber.group, transcriber.result)
    if not is_pdf and not t_copies:
        return None
    if is_pdf:
        summary = _summary_result(path)
        if summary is not None:
            return summary
        from services.acord_intake.read import read_acord
        acord = read_acord(path, ocr_texts=_pages_of(text), transcriber_copies=t_copies or None)
    else:
        acord = _image_read(t_copies)
    if acord is None:
        return None
    recognised = [p for p in acord.pages if p.kind]
    record = {
        "pages": [{"page": p.page + 1, "kind": p.kind, "form_id": p.form_id,
                   "acord_number": p.acord_number, "edition": p.edition} for p in recognised],
        "forms": [{"form_id": c["form_id"], "copy": c["copy"], "pages": [x + 1 for x in c["pages"]],
                   "kind": c["kind"], "edition": c.get("edition"), "boxes_read": len(c["boxes"])}
                  for c in acord.forms],
        # Carried boxes print back on the SAME form at generation - only our 17
        # forms are ever generated. A form outside them (ACORD 807) keeps its
        # unmapped boxes ENCRYPTED in `transcriber.elabels_enc`, never in
        # plaintext here (29 Oct 2026, ASG_TRANSCRIBER.md "Keep everything").
        "carried": _regenerable_only(acord.carried),
        "primble_record": bool(getattr(acord, "primble_record", False)),
    }
    if getattr(acord, "restored", None):
        from services.acord_intake.primble_record import seal_restored
        record["restored"] = seal_restored(acord.restored)
    if getattr(acord, "own_form", False):
        record["own_form"] = True
    if getattr(acord, "carried_transcriber", None):
        record["carried_transcriber"] = acord.carried_transcriber
    if getattr(acord, "carried_ai", None):
        record["carried_ai"] = acord.carried_ai
        record["ai_labels"] = {b: lab for b, lab in (acord.ai_labels or {}).items()
                               if any(b in v for v in acord.carried_ai.values())}
    if transcriber is not None:
        from services.acord_intake.transcriber_intake import record_entry
        record["transcriber"] = record_entry(transcriber.group, transcriber,
                                             [c for c in acord.forms if c.get("kind") == "transcriber"])
    # Pages recognised as ACORD but not readable by name (flattened, scanned, or
    # a form we hold no template for) stay on today's path, flagged for review.
    read_pages = set(acord.acord_pages)
    # Another insured's forms bound into this file (`read._one_insured`): never
    # read into this document - by the boxes or by the model - only flagged.
    other_insured = set(getattr(acord, "other_insured_pages", None) or [])
    unread = [p for p in recognised if p.page not in read_pages]
    if unread:
        record["needs_verification"] = [
            {"page": p.page + 1, "acord_number": p.acord_number, "kind": p.kind,
             "reason": ("names another insured than this document's first form" if p.page in other_insured else
                        "no template for this ACORD form" if not p.form_id else
                        "scanned page" if p.kind == "scanned" else
                        "no box filled" if p.kind == "fillable" else "page could not be aligned")}
            for p in unread]
    if not acord.forms:
        return {"classification": None, "other_text": text, "facts": {}, "flags": {}, "record": record}
    try:
        from services.acord_intake.merge_rules import is_prior_application
        record["prior_application"] = is_prior_application(
            {"facts": acord.facts},
            own_record=bool(getattr(acord, "own_form", False) or getattr(acord, "carries_record", False)))
        if getattr(acord, "prior_own", None):
            record["prior_application"] = True
    except Exception:                                          # noqa: BLE001
        record["prior_application"] = False
    # The document's type is its forms' - not the FIRST form's: a certificate
    # printed ahead of an ACORD 125 typed the whole PDF "certificate", whose role
    # states no revenue or employee count, so the merge dropped the 125's
    # (review, 27 Oct 2026). Any application form makes it an application.
    # The facts the boxes gave: the merge lifts these out of the rules that
    # police the model's readings (`merge_rules.lift_box_readings`).
    # Only the EXACT box reads are lifted out of the merge's guards: a value ASG
    # Transcriber OCR'd off an outside form is policed like any reading (a label
    # read as a value, a heading as the insured) - 29 Oct 2026.
    record["read_keys"] = sorted(k for k, v in acord.facts.items()
                                 if not _has_transcriber_envelope(v) and k not in _transcriber_keys(acord.forms))
    read_ids = [c["form_id"] for c in acord.forms]
    if "ACORD_125" in read_ids:
        doc_type = "application"
    elif all(_DOC_TYPE_FOR.get(f) == "certificate" for f in read_ids):
        doc_type = "certificate"
    else:
        doc_type = "acord_form"
    classification = {
        "doc_type": doc_type, "confidence": "high", "source": "acord_form",
        "scores": {}, "narrative_categories": [],
        "acord_forms": sorted({c["form_id"] for c in acord.forms}),
    }
    if any(c.get("kind") == "transcriber" for c in acord.forms):
        classification["reader"] = "transcriber"
    if other_insured:
        # Two insureds in one file: the document's type is "Needs Verification"
        # (low confidence - the one signal the Documents list and the verified-
        # source door read) so the producer splits it.
        classification["confidence"] = "low"
    read_pages = {p + 1 for p in acord.acord_pages}
    pages = _pages_of(text)
    other = "\n".join(f"[Document page {n}]\n{t}" for n, t in sorted(pages.items())
                      if n not in read_pages and n - 1 not in other_insured and t.strip())
    model_reads_boxes = False
    if len(pages) == 1 and len(acord.pages) > 1 and acord.other_pages:
        # No page markers in the text (OCR_PAGE_MARKERS=0): the pages cannot be
        # told apart, so the unread ones are not dropped - the model reads it all
        # and the exact facts still overlay what it reads.
        other = text
        model_reads_boxes = True
    # PRIMBLE'S OWN FORM (its record authenticated, this insured): what it
    # prints is our output - the facts it read come back as readings, the
    # answers through the record, the AI boxes onto their own boxes - never as
    # document TEXT. As text it was evidence for itself: the narrative scan
    # (which reads every document's body) credited our own printed narrative and
    # AI answers, and the re-upload scored above the package that printed it
    # (Orbin forms + decs 81 against 79, review 28 Oct 2026). Our cover page is
    # stored with no text for the same reason. Only the pages read by box: a
    # page the boxes did not read keeps its text.
    # A form whose record DECRYPTS is ours whatever its insured box now says
    # (a name retyped after download): its text is still our output (29 Oct
    # 2026, review) - only the record's answers are withheld, not the rule.
    stored_text = None
    if (getattr(acord, "own_form", False) or getattr(acord, "carries_record", False)) and not model_reads_boxes:
        stored_text = other
    return {"classification": classification, "other_text": other, "stored_text": stored_text,
            "facts": acord.facts,
            "flags": _flags_from(acord.facts, [c["form_id"] for c in acord.forms]),
            "record": record, "model_reads_acord_pages": model_reads_boxes}


def _regenerable_only(carried: Any) -> Dict[str, Any]:
    """`carried` restricted to forms we generate (`reverse_map.is_known_form`;
    a second copy is keyed "ACORD_125#2")."""
    if not isinstance(carried, dict):
        return {}
    from services.acord_intake.reverse_map import is_known_form
    return {k: v for k, v in carried.items() if is_known_form(str(k).split("#", 1)[0])}


def _transcriber_keys(copies: list) -> set:
    """Every fact key a Transcriber copy's boxes produce - list facts (locations,
    claims, lines, prior policies) and tick-derived scalars carry no per-box
    envelope, so `_has_transcriber_envelope` cannot see them (review, 29 Oct 2026)."""
    t = [c for c in copies if isinstance(c, dict) and c.get("kind") == "transcriber"]
    if not t:
        return set()
    try:
        from services.acord_intake.read import boxes_to_facts
        facts, _carried = boxes_to_facts(t)
        return set(facts)
    except Exception:                                          # noqa: BLE001
        return set()


def _has_transcriber_envelope(v: Any) -> bool:
    from services.acord_intake.read import TRANSCRIBER_CONFIDENCE
    if isinstance(v, dict):
        if v.get("confidence") == TRANSCRIBER_CONFIDENCE:
            return True
        return any(_has_transcriber_envelope(x) for x in v.values())
    if isinstance(v, list):
        return any(_has_transcriber_envelope(x) for x in v)
    return False


def _image_read(t_copies: list):
    """An ACORD form uploaded as an image: no PDF to recognise, Transcriber's copies
    are the whole reading (the OCR text stays the document's text)."""
    from services.acord_intake.read import AcordRead, boxes_to_facts, relabel_transcriber_facts
    if not t_copies:
        return None
    out = AcordRead(pages=[])
    out.forms = list(t_copies)
    out.facts, out.carried = boxes_to_facts(out.forms)
    relabel_transcriber_facts(out.facts, out.forms)
    from services.acord_intake.read import transcriber_carried
    out.carried_transcriber = transcriber_carried(out.forms, out.carried)
    out.acord_pages = sorted({pg for c in out.forms for pg in c["pages"]})
    out.other_pages = []
    return out


def _row_list(v: Any) -> list:
    v = v.get("value") if isinstance(v, dict) and "value" in v else v
    return [r for r in v if isinstance(r, dict)] if isinstance(v, list) else []


def overlay_facts(extracted: dict, acord: dict) -> None:
    if not isinstance(extracted, dict) or not acord:
        return
    facts = extracted.setdefault("facts", {})
    keys = (acord.get("record") or {}).get("read_keys")
    for k, v in (acord.get("facts") or {}).items():
        mine, theirs = _row_list(v), _row_list(facts.get(k))
        if mine and theirs and not acord.get("model_reads_acord_pages"):
            # A MIXED document: the model read only its OTHER pages (a loss run
            # or a declaration bound in behind the application), and the rows it
            # read there are that document's too. Replaced by the boxes' rows,
            # an ACORD 125 with one loss row bound to an eight-claim loss run
            # kept one claim (review, 27 Oct 2026). One fold, the boxes' rows
            # first (`merge_rules.fold_rows`: a row joins a row of the same
            # identity); the joined list is no longer the boxes' reading alone,
            # so the merge polices it like any reading (`lift_box_readings`).
            from services.acord_intake.merge_rules import fold_rows
            facts[k] = fold_rows(k, [mine, theirs], [True, False])
            if isinstance(keys, list) and k in keys:
                keys.remove(k)
            continue
        facts[k] = v
    flags = extracted.setdefault("flags", {})
    for k, v in (acord.get("flags") or {}).items():
        flags[k] = bool(flags.get(k)) or bool(v)
