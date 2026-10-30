"""Read a recognised ACORD form's boxes and turn them into facts - no model call.

`read_acord(pdf_path)` -> AcordRead | None:
  * forms   - [{form_id, copy, pages, kind, edition, boxes: {name: value}}]
  * facts   - per-document facts, the SAME envelope the AI path produces
              ({"value", "source", "confidence"}; tables as plain row lists),
              source "acord_form", confidence "acord_exact"
  * carried - {form_id: {box: value}} for boxes no fact sits behind; printed
              back on the same box when that form is generated
  * acord_pages / other_pages - which pages took which path

Only FILLABLE pages are read here (exact, by box name). Flattened pages go to
`overlay.py`; scanned pages and ACORD forms we hold no template for take today's
path (the caller flags them). Never raises.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from services.acord_intake.recognize import PageForm, box_name, recognize, schema_names
from services.acord_intake.reverse_map import box_targets

logger = logging.getLogger(__name__)

from services.fact_state import ACORD_BOX_SOURCE as SOURCE  # noqa: E402 - one spelling
CONFIDENCE = "acord_exact"
# Boxes that describe the FORM, never the insured (completion date, edition).
_FORM_META_RE = re.compile(r"^(Form_|.*SignatureDate|.*Signature_)")
# Values our own stamper prints that are pointers or derived text, never statements.
_OWN_POINTERS_RE = re.compile(
    r"^\s*(see (the )?attached|see acord|see schedule|refer to|as per attached)\b", re.I)
_TICK_KINDS = ("check", "radio")


@dataclass
class AcordRead:
    pages: List[PageForm]
    forms: List[dict] = field(default_factory=list)
    facts: Dict[str, Any] = field(default_factory=dict)
    carried: Dict[str, Dict[str, str]] = field(default_factory=dict)
    acord_pages: List[int] = field(default_factory=list)
    other_pages: List[int] = field(default_factory=list)
    primble_record: bool = False
    # The person's answers / tables a Primble record restores - the PACKAGE's,
    # never this document's facts (`primble_record.apply`).
    restored: Dict[str, Any] = field(default_factory=dict)
    # Primble's OWN form for this insured (its record authenticated and names
    # the form's insured): its words are our output, never evidence (28 Oct 2026).
    own_form: bool = False
    # The form carries OUR authenticated record, whoever its boxes now name
    # (29 Oct 2026, review): a record that decrypts was written by this server,
    # so the form's text is Primble's output and never evidence - a typo made in
    # the insured's name after download had turned our printed narrative and AI
    # answers back into a document's statement.
    carries_record: bool = False
    # The record's prior-term ruling (boxes + the record's own term), so the
    # document's `prior_application` says what the restore decided.
    prior_own: Optional[bool] = None
    # {carried form key: [boxes]} the record names as AI fills - carried back
    # onto their own box with an AI label, never as a reading (28 Oct 2026).
    carried_ai: Dict[str, List[str]] = field(default_factory=dict)
    ai_labels: Dict[str, str] = field(default_factory=dict)
    # Pages of a form naming ANOTHER insured than the document's first form
    # (`_one_insured`): never read into this document, flagged for review.
    other_insured_pages: List[int] = field(default_factory=list)
    # {carried form key: [boxes]} a Transcriber copy carried - OCR, printed
    # "please verify", never as a document's exact value (`carry`).
    carried_transcriber: Dict[str, List[str]] = field(default_factory=dict)


def _is_value(v: Any) -> bool:
    s = str(v or "").strip()
    if not s or s in ("Off", "None", "null"):
        return False
    try:
        from services.answer_semantics import is_placeholder_text
        if is_placeholder_text(s):
            return False
    except Exception:                                          # noqa: BLE001
        pass
    return not _OWN_POINTERS_RE.match(s)


def fits_fact(key: str, value: str) -> bool:
    """Does a box's text fit the fact it would become? The ONE check a PERSON's
    typed answer passes (`fact_registry.answer_refusal` - an amount box keeps
    its "Statutory" / "Included"), because a typed ACORD box is exactly that. A
    redacted "XX-XXXXXXX" in the FEIN box became the package FEIN over the dec's
    real one, silently, on every form (review, 27 Oct 2026). A fact the registry
    does not declare is not judged here."""
    try:
        from services.fact_registry import FACT_REGISTRY, answer_refusal
    except Exception:                                          # noqa: BLE001
        return True
    entry = FACT_REGISTRY.get(key)
    return not entry or not answer_refusal(entry, value)


def _env(value: str, form_id: str, box: str, page: int) -> dict:
    return {"value": value, "source": SOURCE, "confidence": CONFIDENCE,
            "acord_form": form_id, "box": box, "page": page + 1}


def _ticked(kind: str, value: str) -> bool:
    # A CHECKBOX the field reader returns is ON (an off box is not returned); its
    # value is what the box MEANS - "No" for the No box of ACORD 133's Yes / No
    # pairs, ticked (review, 27 Oct 2026). A radio group's value is the option.
    if kind == "check":
        return str(value).strip().lower() not in ("off", "")
    if kind in _TICK_KINDS:
        return str(value).strip().lower() not in ("no", "off", "")
    return str(value).strip().lower() in ("y", "yes", "x", "true", "1", "on")


def _template_page_of(names, idx_map: Dict[str, frozenset]) -> Optional[int]:
    """The template page a PDF page is, voted by the boxes it shows that sit on
    ONE template page. A box every page repeats (the AGENCY CUSTOMER ID header)
    says nothing about which page this is - reading its first page made every
    page after the first "page 1" and so a new copy (review, 27 Oct 2026)."""
    votes: Dict[int, int] = {}
    for n in names:
        pages = idx_map.get(n)
        if pages and len(pages) == 1:
            (pg,) = pages
            votes[pg] = votes.get(pg, 0) + 1
    if not votes:
        return None
    return max(votes.items(), key=lambda kv: (kv[1], -kv[0]))[0]


def _split_copies(pages: List[PageForm], tpl_page: Dict[str, Dict[str, frozenset]]) -> List[dict]:
    """Group a document's fillable pages into form copies. A page starts a new
    copy of its form only when the current copy ALREADY holds that template
    page - so pages out of order stay one copy, and two copies stay two. A page
    that shows no page-specific box belongs to the current copy."""
    copies: List[dict] = []
    seen: Dict[str, set] = {}          # form id -> template pages the current copy holds
    count: Dict[str, int] = {}
    for pf in pages:
        if pf.kind != "fillable" or not pf.form_id:
            continue
        fid = pf.form_id
        tp = _template_page_of(pf.names, tpl_page.get(fid) or {})
        current = next((c for c in reversed(copies) if c["form_id"] == fid), None)
        if current is not None and (tp is None or tp not in seen[fid]):
            current["pages"].append(pf.page)
            if tp is not None:
                seen[fid].add(tp)
            continue
        count[fid] = count.get(fid, 0) + 1
        copies.append({"form_id": fid, "copy": count[fid], "pages": [pf.page], "kind": "fillable",
                       "edition": pf.edition, "boxes": {}, "kinds": {}, "box_page": {}})
        seen[fid] = {tp} if tp is not None else set()
    return copies


_TPL_PAGES: Dict[str, Dict[str, frozenset]] = {}


def template_pages(form_id: str) -> Dict[str, frozenset]:
    """{box: the template pages it sits on} - read once from our template. Most
    boxes sit on one page; the page header boxes sit on every page."""
    if form_id not in _TPL_PAGES:
        try:
            import os
            import pikepdf
            from config.settings import TEMPLATE_DIR
            from utils import form_field_text as fft
            with pikepdf.open(os.path.join(TEMPLATE_DIR, f"{form_id}.pdf")) as pdf:
                m: Dict[str, set] = {}
                for g in fft._scan_widgets(pdf).values():
                    n = fft._qualified_name(g["field"])
                    for (pi, _w, _r, _b) in g["widgets"]:
                        m.setdefault(n, set()).add(pi)
            _TPL_PAGES[form_id] = {n: frozenset(s) for n, s in m.items()}
        except Exception as ex:                                # noqa: BLE001
            logger.info("acord_intake: template pages for %s unavailable: %s", form_id, ex)
            _TPL_PAGES[form_id] = {}
    return _TPL_PAGES[form_id]


def read_acord(pdf_path: str, page_texts: Optional[List[str]] = None,
               ocr_texts: Optional[Dict[int, str]] = None,
               transcriber_copies: Optional[List[dict]] = None) -> Optional[AcordRead]:
    """`transcriber_copies`: ASG Transcriber's reading of this document's ACORD pages
    (`transcriber_intake.copies_from`), folded in by `merge_transcriber_copies` - one
    document, one reading."""
    pages = recognize(pdf_path, page_texts, ocr_texts)
    if not any(p.kind for p in pages) and not transcriber_copies:
        return None
    out = AcordRead(pages=pages)
    fillable = [p for p in pages if p.kind == "fillable"]
    copies: List[dict] = []
    if fillable:
        try:
            from utils.form_field_text import read_filled_fields
            # The pages' text is already read: the field reader's "drawn" check
            # then opens the PDF again only for values the text layer carries.
            by_page = read_filled_fields(pdf_path, page_texts=[p.text for p in pages],
                                         require_acroform=False)
        except Exception as ex:                                # noqa: BLE001
            logger.warning("acord_intake: fields unreadable in %s: %s", pdf_path, ex)
            by_page = {}
        tpl = {p.form_id: template_pages(p.form_id) for p in fillable if p.form_id}
        copies = _split_copies(fillable, tpl)
        page_copy = {pg: c for c in copies for pg in c["pages"]}
        schemas = schema_names()
        for pg, fields in (by_page or {}).items():
            c = page_copy.get(pg)
            if not c:
                continue
            for ff in fields:
                name = box_name(getattr(ff, "name", "") or "", schemas.get(c["form_id"], ()))
                if not name:
                    continue
                if name not in c["boxes"]:
                    c["boxes"][name] = ff.value
                    c["kinds"][name] = ff.kind
                    c["box_page"][name] = pg
                    c.setdefault("raw", {})[name] = getattr(ff, "raw", "") or ""
    # Flattened pages of a form we hold a template for: the template overlay.
    try:
        from services.acord_intake.overlay import read_flattened
        copies.extend(read_flattened(pdf_path, pages))
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("acord_intake: overlay skipped for %s: %s", pdf_path, ex)
    # A copy that read NO box was not read: its pages go to today's path (the
    # model) instead of vanishing - a page whose values the reader cannot see
    # is not an empty form (review, 27 Oct 2026).
    copies = [c for c in copies if c["boxes"]]
    if transcriber_copies:
        copies = merge_transcriber_copies(copies, transcriber_copies)
    copies, out.other_insured_pages = _one_insured(copies)
    read_pages = {pg for c in copies for pg in c["pages"]}
    out.acord_pages = sorted(read_pages)
    out.other_pages = [p.page for p in pages if p.page not in read_pages]
    if copies:
        out.forms = copies
        out.facts, out.carried = boxes_to_facts(copies)
        relabel_transcriber_facts(out.facts, copies)
        out.carried_transcriber = transcriber_carried(copies, out.carried)
        # Primble's own form: its encrypted record restores the answers no box
        # prints and keeps AI boxes AI (`primble_record`).
        rec = None
        try:
            from services.acord_intake import primble_record
            rec = primble_record.read(pdf_path)
            out.carries_record = bool(rec)
            if rec and primble_record._same_insured(rec, out.facts):
                out.own_form = True
                ai_boxes = _strip_ai_boxes(copies, rec)
                if ai_boxes:
                    # Read again without them: an AI box is never a reading, in a
                    # table cell, a tick or an address part either (28 Oct 2026).
                    out.facts, out.carried = boxes_to_facts(copies)
                    for key, boxes in ai_boxes.items():
                        slot = out.carried.setdefault(key, {})
                        for box, value in boxes.items():
                            slot.setdefault(box, value)
                    out.carried_ai = {k: sorted(v) for k, v in ai_boxes.items()}
                    out.ai_labels = {str(b): str(lab) for b, lab in (rec.get("ai_labels") or {}).items()}
        except Exception as ex:                                # noqa: BLE001
            logger.info("acord_intake: primble record AI boxes skipped: %s", ex)
        _excess_layer(copies, out.facts, out.carried, out.carried_ai)
        try:
            if rec:
                # Judged on the BOXES' own term, before any answer is restored.
                from services.acord_intake.merge_rules import is_prior_application
                prior = is_prior_application({"facts": _with_record_term(out.facts, rec)}, own_record=True)
                out.prior_own = bool(prior)
                out.restored = primble_record.apply(rec, out.facts, prior_application=prior) or {}
                out.primble_record = bool(out.restored)
                _carry_ai_boxes(out.facts, out.carried)
        except Exception as ex:                                # noqa: BLE001
            logger.info("acord_intake: primble record skipped: %s", ex)
    return out


def _one_insured(copies: List[dict]):
    """(copies of the document's insured, pages of another insured's forms).

    One document is one insured's reading. A PDF binding two insureds' filled
    forms (two applications scanned into one file) was read as ONE application:
    the first insured's name with the second's FEIN, entity type and term, every
    value labelled exact, and both insureds' locations and vehicles in one
    schedule (production fuzz, 29 Oct 2026). The FIRST form naming an insured
    names the document's; a form naming a DIFFERENT insured (by the merge's own
    test - `merge_rules.names_this_insured`: name, DBA, FEIN, a glued or
    abbreviated spelling is the same company) is set aside UNREAD and its pages
    are flagged for review, never read into this insured. A form naming nobody
    (most section forms print only a header) stays."""
    if len(copies) < 2:
        return copies, []
    try:
        from services.acord_intake.merge_rules import names_this_insured
    except Exception:                                          # noqa: BLE001
        return copies, []
    named = []
    for c in copies:
        try:
            f, _carried = boxes_to_facts([c])
        except Exception:                                      # noqa: BLE001
            f = {}
        who = {k: f[k] for k in ("applicant_name", "dba_name", "fein") if k in f}
        named.append(who)
    # An APPLICATION names the document's insured before a certificate does: a
    # subcontractor's ACORD 25 bound ahead of the 125 must not set the 125 aside.
    try:
        from services.acord_intake.reverse_map import CERTIFICATE_FORMS
    except Exception:                                          # noqa: BLE001
        CERTIFICATE_FORMS = frozenset({"ACORD_25", "ACORD_28"})
    first = next((w for c, w in zip(copies, named) if w and _base_form(c.get("form_id")) not in CERTIFICATE_FORMS),
                 None) or next((w for w in named if w), None)
    if first is None:
        return copies, []
    kept, aside = [], []
    for c, who in zip(copies, named):
        if who and who is not first and not names_this_insured({"facts": who}, [{"facts": first}]):
            aside.append(c)
        else:
            kept.append(c)
    if not aside:
        return copies, []
    logger.info("acord_intake: %d form(s) name another insured - not read into this document", len(aside))
    return kept, sorted({pg for c in aside for pg in c["pages"]})


def _with_record_term(facts: Dict[str, Any], rec: Optional[dict]) -> Dict[str, Any]:
    """The boxes' term, a date the boxes do not give readably taken from the
    record's own `term` (the package's proposed term at download): a blanked or
    mistyped date box must not make last term's form look current (production
    review, 29 Oct 2026)."""
    try:
        from services.normalization import normalize_date
    except Exception:                                          # noqa: BLE001
        return facts
    term = (rec or {}).get("term") if isinstance(rec, dict) else None
    if not isinstance(term, dict):
        return facts
    out = dict(facts)
    for k in ("effective_date", "expiration_date"):
        v = facts.get(k)
        v = v.get("value") if isinstance(v, dict) else v
        if not normalize_date(str(v or "")) and term.get(k):
            out[k] = {"value": str(term[k])}
    return out


# ── ASG Transcriber (29 Oct 2026, ASG_TRANSCRIBER.md 7.6 rule 1) ─────────────
TRANSCRIBER_CONFIDENCE = "acord_transcriber"


def _base_form(form_id: Any) -> str:
    return str(form_id or "").split("__", 1)[0]


def merge_transcriber_copies(copies: List[dict], t_copies: List[dict]) -> List[dict]:
    """ONE DOCUMENT, ONE READING. A Transcriber copy whose pages our FILLABLE read
    already covers adds only its confidence scores (the exact box read is the
    value - two readings of one form must never become two witnesses). Our
    overlay read of a FLATTENED page folds INTO the Transcriber copy (its boxes
    first, ours only where it read none). A copy with no overlap is added as is.
    Copies are renumbered in page order so a second 125 stays copy 2."""
    out = [dict(c) for c in copies]
    for t in t_copies:
        tp = set(t.get("pages") or [])
        overlapping = [c for c in out if set(c.get("pages") or []) & tp]
        if any(_base_form(c.get("form_id")) != _base_form(t.get("form_id")) for c in overlapping):
            # Our reader and Transcriber name DIFFERENT forms for the same pages (our
            # footer 126, ASG 125): folding would map one form's boxes through the
            # other's reverse map. Our own read of the page stands (review, 29 Oct).
            logger.info("transcriber copy %s on pages %s overlaps another form's read - not folded",
                        t.get("form_id"), sorted(tp))
            continue
        fillable = [c for c in overlapping if c.get("kind") == "fillable"]
        if fillable:
            # A page the fillable copies do not cover (one page of the form
            # flattened, say) is Transcriber's alone: those boxes come in as their
            # own copy. On covered pages the exact read stands.
            covered = {pg for c in fillable for pg in (c.get("pages") or [])}
            rest = sorted(tp - covered)
            if rest:
                keep = {b for b, pg in t["box_page"].items() if pg in rest}
                if keep:
                    out.append(dict(t, pages=rest, boxes={b: t["boxes"][b] for b in keep},
                                    kinds={b: t["kinds"][b] for b in keep},
                                    box_page={b: t["box_page"][b] for b in keep},
                                    raw={b: v for b, v in (t.get("raw") or {}).items() if b in keep},
                                    confidence={b: v for b, v in (t.get("confidence") or {}).items() if b in keep}))
            for c in fillable:
                agreed = 0
                conf = c.setdefault("confidence", {})
                for b, score in (t.get("confidence") or {}).items():
                    if b in c["boxes"]:
                        conf.setdefault(b, score)
                        agreed += 1
                c["transcriber"] = {"accuracy": t.get("accuracy"), "request_id": t.get("request_id"),
                                    "boxes_scored": agreed}
            continue
        merged = dict(t, boxes=dict(t["boxes"]), kinds=dict(t["kinds"]), box_page=dict(t["box_page"]),
                      raw=dict(t.get("raw") or {}), confidence=dict(t.get("confidence") or {}))
        for c in overlapping:
            for b, v in c["boxes"].items():
                if b not in merged["boxes"]:
                    merged["boxes"][b] = v
                    merged["kinds"][b] = c["kinds"].get(b, "text")
                    merged["box_page"][b] = c["box_page"].get(b, merged["pages"][0])
                    if (c.get("raw") or {}).get(b):
                        merged["raw"][b] = c["raw"][b]
            merged["pages"] = sorted(set(merged["pages"]) | set(c.get("pages") or []))
            merged["overlay_folded"] = True
            out.remove(c)
        out.append(merged)
    out.sort(key=lambda c: min(c["pages"]) if c.get("pages") else 0)
    counts: Dict[str, int] = {}
    for c in out:
        counts[c["form_id"]] = counts.get(c["form_id"], 0) + 1
        c["copy"] = counts[c["form_id"]]
    return out


def transcriber_carried(copies: List[dict], carried: Dict[str, Dict[str, str]]) -> Dict[str, List[str]]:
    """{carried form key: [boxes]} that came from a Transcriber copy's boxes (a
    Y/N answer, a form-only detail ASG OCR'd off a scan). Carried as "filled"
    they printed as an uploaded document's exact value with no Confirm row
    (production fuzz, 29 Oct 2026)."""
    out: Dict[str, List[str]] = {}
    for c in copies:
        if c.get("kind") != "transcriber":
            continue
        key = c["form_id"] if c.get("copy", 1) == 1 else f"{c['form_id']}#{c['copy']}"
        boxes = sorted(b for b in (carried.get(key) or {}) if b in (c.get("boxes") or {}))
        if boxes:
            out[key] = boxes
    return out


def relabel_transcriber_facts(facts: Dict[str, Any], copies: List[dict]) -> int:
    """Every envelope a Transcriber copy's box produced carries the Transcriber
    label (0.85 - found, please verify) and the box's own confidence score; the
    source stays `acord_form` (the owner table keys on it). Returns the count."""
    scored: Dict[tuple, Optional[float]] = {}
    for c in copies:
        if c.get("kind") != "transcriber":
            continue
        for b in c["boxes"]:
            scored[(c["form_id"], b)] = (c.get("confidence") or {}).get(b)
    if not scored:
        return 0
    # A reading with NO exact (fillable) copy is Transcriber's alone: an envelope
    # derived from several boxes (a tick group -> entity_type) carries no box and
    # is Transcriber's too (review, 29 Oct 2026).
    all_transcriber = all(c.get("kind") == "transcriber" for c in copies)
    n = 0

    def walk(v: Any) -> None:
        nonlocal n
        if isinstance(v, dict):
            key = (v.get("acord_form"), v.get("box"))
            own = key in scored or (all_transcriber and v.get("source") == "acord_form")
            if "value" in v and own and v.get("confidence") == CONFIDENCE:
                v["confidence"] = TRANSCRIBER_CONFIDENCE
                v["reader"] = "transcriber"
                if scored.get(key) is not None:
                    v["confidence_score"] = scored[key]
                n += 1
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(facts)
    return n


def value_fingerprint(value: Any) -> str:
    """A text box's value as the record remembers an AI fill (`primble_record.
    attach`): a box changed after download no longer matches it."""
    import hashlib
    norm = re.sub(r"[^a-z0-9]", "", str(value or "").lower())
    return hashlib.sha256(norm.encode()).hexdigest()[:16]


def _carry_key(c: dict) -> str:
    return c["form_id"] if c.get("copy", 1) == 1 else f"{c['form_id']}#{c['copy']}"


def _strip_ai_boxes(copies: List[dict], rec: dict) -> Dict[str, Dict[str, str]]:
    """Take the boxes the record names as AI fills out of the copies' readings:
    {carried form key: {box: value as the stamper prints it}}.

    WHY (28 Oct 2026, review). Only a WHOLE-fact box was recognised as an AI
    fill (`primble_record.apply` matches a fact's own box). An AI value in a
    schedule cell (a vehicle's cost new, a building's year built or construction
    on the 140), a tick (entity type, a line of business) or an address part
    became an exact reading - so a re-upload held a COPE value, a vehicle value
    or a line nobody stated on the original package and scored above it. The
    record covers only the form it rides on, so the keys are per copy."""
    ai = set(rec.get("ai_boxes") or [])
    printed = rec.get("ai_values") or {}
    out: Dict[str, Dict[str, str]] = {}
    if not ai:
        return out
    for c in copies:
        for box in [b for b in c.get("boxes") or {} if b in ai]:
            kind = (c.get("kinds") or {}).get(box, "text")
            if (kind not in _TICK_KINDS and box in printed
                    and value_fingerprint(c["boxes"][box]) != printed[box]):
                continue                 # typed over after download: the form's own statement
            value = c["boxes"].pop(box)
            (c.get("raw") or {}).pop(box, None)
            if kind in _TICK_KINDS:
                if kind == "check" and _ticked(kind, value):
                    out.setdefault(_carry_key(c), {})[box] = "Yes"
            elif _is_value(value):
                out.setdefault(_carry_key(c), {})[box] = str(value)
    return out


def _carry_ai_boxes(facts: Dict[str, Any], carried: Dict[str, Dict[str, str]]) -> None:
    """A box the AI filled on our own form (its record says so) comes back onto
    THAT box only (27 Oct 2026, the Orbin round trip). Read as a fact, the 126's
    AI-written property damage deductible ($1,000 - no fact behind it on the
    original package) became the GL deductible and printed in the bodily injury
    and "other" deductible boxes too: an AI guess spread past where it stood.
    The original package held it as that box's value, never a fact - so does
    the round trip."""
    for key, env in list(facts.items()):
        if not (isinstance(env, dict) and env.get("restored_from") == "primble_record"
                and env.get("source") == "ai" and env.get("box") and env.get("acord_form")):
            continue
        facts.pop(key, None)
        slot = carried.setdefault(str(env["acord_form"]), {})
        slot.setdefault(str(env["box"]), str(env.get("value")))


_OWN_BLOCK_RE: Optional["re.Pattern"] = None


def _own_block_re():
    """The headings Primble's own stamper composes into a remarks box - read off
    the stamper's own constants where it has them, so a renamed heading moves
    here with it. Every continuation block it writes says "(continued from
    ACORD nnn"."""
    global _OWN_BLOCK_RE
    if _OWN_BLOCK_RE is None:
        heads = ["SUBMISSION NARRATIVE", "Operations (continued):"]
        try:
            from services import pdf_service as _ps
            heads += [_ps._LOSS_OVERFLOW_MARKER, _ps.PRIOR_CARRIER_CONTINUED_HEADING]
        except Exception:                                      # noqa: BLE001
            pass
        try:
            from services.wc_endorsements import BLOCK_HEADING
            heads.append(BLOCK_HEADING)
        except Exception:                                      # noqa: BLE001
            pass
        alts = [re.escape(h) for h in heads if h]
        alts.append(r"[A-Z][A-Z0-9 &/,'-]{2,}\(continued from ACORD \d+")
        _OWN_BLOCK_RE = re.compile("|".join(alts))
    return _OWN_BLOCK_RE


def own_blocks_removed(text: str) -> str:
    """A remarks box's text without the blocks Primble composed into it (a 4th
    loss row, the prior-carrier continuation, the approved narrative, the vehicle
    and endorsement schedules) - those are other facts, read elsewhere or not at
    all. Each paragraph is cut at the first own heading; what stands before it
    is the remarks a person or another system wrote."""
    out = []
    for para in re.split(r"\n\s*\n", str(text or "")):
        m = _own_block_re().search(para)
        kept = (para[:m.start()] if m else para).strip()
        if kept:
            out.append(kept)
    return "\n\n".join(out).strip()


def _compose_address(parts: Dict[str, str]) -> str:
    # A street box holding the WHOLE block (the newest 125 prints name, street,
    # suite, city, state and ZIP in one box) is read ONCE into its parts; the
    # separate boxes never append a part again (item 9, 29 Oct 2026).
    if "\n" in str(parts.get("line1") or ""):
        from services.acord_intake.document_settle import parse_address_block, merge_address_parts
        block = parse_address_block(parts.get("line1"))
        if block:
            parts = merge_address_parts(block, {k: v for k, v in parts.items() if k != "line1"})
    line = ", ".join(x for x in (parts.get("line1"), parts.get("line2")) if x)
    tail = " ".join(x for x in (parts.get("state"), parts.get("zip")) if x)
    city = parts.get("city") or ""
    rest = ", ".join(x for x in (city, tail) if x)
    return ", ".join(x for x in (line, rest) if x)


# Primble's own continuation of the ACORD 127 vehicle schedule on ACORD 101
# (`pdf_service`): "Vehicle 5 | 2004 CHEVROLET EXPRESS G2500 | Cost new 24,500 |
# Class 01483". Read back into the schedule rows the 127 had no room for.
_VEHICLE_CONT_RE = re.compile(
    r"Vehicle\s+(?P<n>\d+)\s*\|\s*(?P<year>(?:19|20)\d{2})\s+(?P<desc>[^|/]+?)\s*"
    r"(?:\|\s*Cost new\s+(?P<cost>[\d,]+))?\s*(?:\|\s*Class\s+(?P<cls>[A-Za-z0-9]+))?"
    r"\s*(?=/|Vehicle\s+\d|[A-Z][A-Z ]{6,}\(continued|$)")


def _continued_vehicles(text: str, lists: Dict[str, Dict[int, dict]]) -> None:
    if "VEHICLE SCHEDULE (continued" not in text:
        return
    block = text.split("VEHICLE SCHEDULE (continued", 1)[1]
    rows = lists.setdefault("auto_vin_schedule", {})
    for m in _VEHICLE_CONT_RE.finditer(block):
        idx = int(m.group("n")) - 1
        make, _sp, model = m.group("desc").strip().partition(" ")
        row = rows.setdefault(idx, {})
        # The printed vehicle number keeps two identical vans two rows through the
        # merge's own duplicate-row pass.
        row.setdefault("vehicle_number", m.group("n"))
        row.setdefault("year", m.group("year"))
        row.setdefault("make", make)
        if model:
            row.setdefault("model", model.strip())
        if m.group("cost"):
            row.setdefault("cost_new", m.group("cost"))
        if m.group("cls"):
            row.setdefault("class_code", m.group("cls"))


_EXCESS_ONLY_SCALARS = ("umbrella_limit", "umbrella_aggregate", "umbrella_sir", "umbrella_retention",
                        "umbrella_effective_date", "umbrella_expiration_date", "umbrella_carrier",
                        "umbrella_policy_number", "umbrella_premium")


def _excess_layer(copies: List[dict], facts: Dict[str, Any], carried: Optional[dict] = None,
                  carried_ai: Optional[dict] = None) -> None:
    """An ACORD 131 that ticks EXCESS (and not Umbrella) describes the excess
    layer: its umbrella-named facts and its umbrella line row become the Excess
    Liability line record (`lob_canon` files it as the umbrella family's excess
    layer). Otherwise the two layers' limits read as one fact in disagreement."""
    c131 = [c for c in copies if c["form_id"] == "ACORD_131"]
    if not c131:
        return
    def ticked(c, box):
        return _ticked(c["kinds"].get(box, "check"), c["boxes"].get(box, ""))
    if not (any(ticked(c, "Policy_PolicyType_ExcessIndicator_A") for c in c131)
            and not any(ticked(c, "Policy_PolicyType_UmbrellaIndicator_A") for c in c131)):
        return
    row = None
    for r in facts.get("coverage_lines") or []:
        if isinstance(r, dict) and str(r.get("line") or "").lower() in ("commercial umbrella", "umbrella"):
            row = r
            break
    if row is None:
        row = {}
        facts.setdefault("coverage_lines", []).append(row)
    row["line"] = "Excess Liability"
    # Its carried boxes belong to the package's EXCESS copy of the form.
    if carried is not None and "ACORD_131" in carried:
        carried["ACORD_131__excess"] = carried.pop("ACORD_131")
    if carried_ai is not None and "ACORD_131" in carried_ai:
        carried_ai["ACORD_131__excess"] = carried_ai.pop("ACORD_131")
    for key in _EXCESS_ONLY_SCALARS:
        held = facts.pop(key, None)
        if held is None:
            continue
        col = {"umbrella_limit": "limit", "umbrella_carrier": "carrier", "umbrella_policy_number": "policy_number",
               "umbrella_effective_date": "effective_date", "umbrella_expiration_date": "expiration_date",
               "umbrella_premium": "premium"}.get(key, key.replace("umbrella_", "excess_"))
        row.setdefault(col, held.get("value") if isinstance(held, dict) else held)


def _drop_summary_echoes(rows: List[dict]) -> List[dict]:
    """A row holding ONE value of a column the real rows share or lack is a
    summary the form prints beside the table (ACORD 130's Part 1 states list the
    class rows' distinct states) - its value goes onto the rows that lack it and
    the echo row goes. A one-value row whose value the real rows contradict is
    kept: it may be a real row."""
    stated = lambda r: {k: v for k, v in r.items() if _is_value(v)}
    real = [r for r in rows if len(stated(r)) > 1]
    if not real:
        return rows
    out = []
    for r in rows:
        st = stated(r)
        if len(st) != 1 or r in real:
            out.append(r)
            continue
        (col, val), = st.items()
        held = {str(x.get(col)).strip().lower() for x in real if _is_value(x.get(col))}
        if held and str(val).strip().lower() not in held:
            out.append(r)
            continue
        for x in real:
            if not _is_value(x.get(col)):
                x[col] = val
    return out


# ── ACORD 140's SUBJECT OF INSURANCE grid is a coverage schedule ─────────────
# Per premises the 140 prints up to five subject rows, each with its own amount,
# coinsurance, valuation, deductible (`pdf_service._PREMISES_GRID_CELL_RE`; six
# letters a premises, the sixth unused). Read back POSITIONALLY - row A as the
# building, row A's deductible as the package's AOP deductible - the round trip
# (27 Oct 2026) turned the schedule's per-coverage $5,000 into the policy
# deductible beside the dec's "$500, exceptions: see schedule" (a Data
# Consistency card holding 85), and the Business Income rows into nothing. So
# the grid is read the way the dec's schedule is (`property_coverages`): one
# section per premises, its coverages in the form's order, each with only the
# terms its row prints; the building / BPP values by the row's SUBJECT.
_GRID_COLS = ("subject", "limit", "coinsurance", "valuation", "causes", "inflation_guard",
              "deductible", "deductible_type", "blanket", "conditions")


def _premises_grid(copies: List[dict]) -> Dict[int, List[dict]]:
    """{premises row index: [coverage rows]} from every ACORD 140 copy."""
    try:
        from services.pdf_service import (_PREMISES_GRID_CELL_RE, _PREMISES_GRID_COLUMN_KEYS,
                                          _ROW_LETTER_TO_IDX)
        from services.property_coverages import subject_kind
    except Exception:                                          # noqa: BLE001
        return {}
    cells: Dict[int, Dict[int, Dict[str, str]]] = {}
    for c in copies:
        if c.get("form_id") != "ACORD_140":
            continue
        base = 100 * (c.get("copy", 1) - 1)
        for box, value in (c.get("boxes") or {}).items():
            m = _PREMISES_GRID_CELL_RE.match(box)
            idx = _ROW_LETTER_TO_IDX.get(m.group("row")) if m else None
            if idx is None:
                continue
            loc, slot = divmod(idx, 6)
            if slot == 5 or not _is_value(value):
                continue
            col = _PREMISES_GRID_COLUMN_KEYS[m.group("col")]
            cells.setdefault(base + loc, {}).setdefault(slot, {})[col] = str(value).strip()
    out: Dict[int, List[dict]] = {}
    for loc, slots in cells.items():
        covs = []
        for slot in sorted(slots):
            cell = slots[slot]
            subj = cell.get("subject") or ""
            if not subj:
                continue                 # an amount with no subject says what it is nowhere
            covs.append({"coverage": subj, "kind": subject_kind(subj), "options": [],
                         "columns": sorted(cell), **{k: cell.get(k, "") for k in _GRID_COLS}})
        if covs:
            out[loc] = covs
    return out


def _apply_premises_grid(grid: Dict[int, List[dict]], lists: Dict[str, Dict[int, dict]],
                         facts: Dict[str, Any]) -> None:
    """The grid as `_property_coverages` sections, the location rows' building /
    BPP values by subject, and no package AOP deductible read off a grid row."""
    if not grid:
        return
    try:
        from services.property_coverages import KEY, _label_number
    except Exception:                                          # noqa: BLE001
        return
    rows = lists.get("property_locations") or {}
    sections = []
    for loc, covs in sorted(grid.items()):
        row = rows.get(loc) or {}
        prem = _label_number(row.get("premises_number") or row.get("location_number")) or str(loc % 100 + 1)
        sections.append({"premises": prem, "building": _label_number(row.get("building_number")),
                         "coverages": covs, "complete": True})
        for kind, col in (("building", "building_value"), ("bpp", "bpp_value")):
            hit = next((cv for cv in covs if cv.get("kind") == kind and cv.get("limit")), None)
            if hit is not None:
                rows.setdefault(loc, {})[col] = hit["limit"]
            elif loc in rows:
                rows[loc].pop(col, None)     # the positional reading named another subject
    facts[KEY] = {"sections": sections, "source": SOURCE}
    held = facts.get("property_deductible_aop")
    if isinstance(held, dict) and str(held.get("box") or "").startswith("CommercialProperty_Premises_"):
        facts.pop("property_deductible_aop", None)


# ── ACORD 131's UNDERLYING INSURANCE section is a schedule of underlying ─────
# insurance: the applicant's own list of the policies the umbrella sits over -
# carrier, number, term and limits per line. Read only into each line's own
# boxes (coverage_lines, gl_each_occurrence, ...), a forms-only package had no
# schedule at all and was charged "Schedule of underlying insurance" (round
# trip, 27 Oct 2026). One row per line the section STATES (a carrier, number or
# limit), in `underlying_policies`' own shape.
_UNDERLYING_BLOCKS = (
    ("General Liability", "UnderlyingPolicy_GeneralLiability_", (
        ("each occurrence", "GeneralLiability_EachOccurrence_LimitAmount_A"),
        ("general aggregate", "GeneralLiability_GeneralAggregate_LimitAmount_A"),
        ("products / completed operations aggregate", "GeneralLiability_ProductsAndCompletedOperations_AggregateLimitAmount_A"),
        ("personal & advertising injury", "GeneralLiability_PersonalAndAdvertisingInjury_LimitAmount_A"))),
    ("Automobile Liability", "UnderlyingPolicy_Automobile_", (
        ("combined single limit", "Vehicle_CombinedSingleLimit_EachAccidentAmount_A"),
        ("bodily injury each person", "Vehicle_BodilyInjury_PerPersonLimitAmount_A"),
        ("bodily injury each accident", "Vehicle_BodilyInjury_PerAccidentLimitAmount_A"),
        ("property damage each accident", "Vehicle_PropertyDamage_PerAccidentLimitAmount_A"))),
    ("Employers Liability", "UnderlyingPolicy_EmployersLiability_", (
        ("each accident", "WorkersCompensationEmployersLiability_EmployersLiability_EachAccidentLimitAmount_A"),
        ("disease - each employee", "WorkersCompensationEmployersLiability_EmployersLiability_DiseaseEachEmployeeLimitAmount_A"),
        ("disease - policy limit", "WorkersCompensationEmployersLiability_EmployersLiability_DiseasePolicyLimitAmount_A"))),
    (None, "UnderlyingPolicy_OtherPolicy_", (
        ("limit", "UnderlyingPolicy_OtherPolicy_CombinedSingleLimitAmount_A"),)),
)


def _underlying_schedule(copies: List[dict]) -> List[dict]:
    rows: List[dict] = []
    for c in copies:
        if c.get("form_id") != "ACORD_131":
            continue
        b = c.get("boxes") or {}

        def _v(name):
            v = b.get(name)
            return str(v).strip() if _is_value(v) else ""
        for line, prefix, limits in _UNDERLYING_BLOCKS:
            name = line or _v(prefix + "PolicyTypeDescription_A") or _v(prefix + "CoverageDescription_A")
            row = {"line": name, "carrier": _v(prefix + "InsurerFullName_A"),
                   "policy_no": _v(prefix + "PolicyNumberIdentifier_A"),
                   "limit": "; ".join(f"{label} {_v(box)}" for label, box in limits if _v(box))}
            eff, exp = _v(prefix + "PolicyEffectiveDate_A"), _v(prefix + "PolicyExpirationDate_A")
            if eff:
                row["effective_date"] = eff
            if exp:
                row["expiration_date"] = exp
            if name and (row["carrier"] or row["policy_no"] or row["limit"]):
                if row not in rows:
                    rows.append(row)
    return rows


# ACORD 125 QUESTION 4 - "other insurance with this company" (27 Oct 2026, the
# Orbin round trip). Each row prints a line and its policy number; on a forms-only
# re-upload it is the ONLY record of a line with no section form of its own (the
# inland marine policy): unread, the line left the policy list, its 125 tick and
# its row. Read back as coverage line records - the pair together, never one box
# alone - and joined to a line the section forms already state.
_Q4_LINE_RE = re.compile(r"^OtherPolicy_LineOfBusinessCode_([A-N])$")


def _other_insurance_rows(copies: List[dict]) -> List[dict]:
    rows: List[dict] = []
    for c in copies:
        if c.get("form_id") != "ACORD_125":
            continue
        b = c.get("boxes") or {}
        for box, value in sorted(b.items()):
            m = _Q4_LINE_RE.match(box)
            if not m or not _is_value(value):
                continue
            number = b.get(f"OtherPolicy_PolicyNumberIdentifier_{m.group(1)}")
            if not _is_value(number):
                continue
            row = {"line": str(value).strip(), "policy_number": str(number).strip()}
            if row not in rows:
                rows.append(row)
    return rows


def _join_line_rows(lines: Dict[str, dict], rows: List[dict]) -> None:
    try:
        from services.lob_canon import canon_line
    except Exception:                                          # noqa: BLE001
        canon_line = lambda _t: None                           # noqa: E731
    for row in rows:
        fam = canon_line(row["line"])
        held = next((r for r in lines.values()
                     if fam and canon_line(str(r.get("line") or "")) == fam), None)
        if held is None:
            lines.setdefault(f"q4:{row['line']}", dict(row))
        elif not held.get("policy_number"):
            held["policy_number"] = row["policy_number"]


# ACORD 125's APPLICANT CONTACT block is TWO rows the stamper prints from the
# contacts schedule (`pdf_service._resolve_contact_detail`, `applicant_contacts`:
# row A is the schedule's FIRST contact - an inspection contact, say), and only
# with no schedule from the package's one contact (`contact_name` /
# `contact_phone` / `contact_email`). Read back, row A always became the
# package's contact: CH125's 125 printed the inspection contact in row A and the
# package contact (accounting) in row B, so the re-upload named another person
# and phone than the declarations - a Data Consistency card holding forms +
# declarations at 85 against the package's 100 (review, 28 Oct 2026). A block
# that prints a schedule - a second row, or a contact ROLE - does not say which
# row is the package's contact: its scalars are not read (blank over wrong); the
# rows are carried back onto the form as printed.
_CONTACT_BOX_RE = re.compile(r"^NamedInsured_Contact_(?P<col>[A-Za-z]+)_(?P<row>[A-N])$")
_CONTACT_SCALARS = ("contact_name", "contact_phone", "contact_email")


def _contact_schedule_rule(copies: List[dict], facts: Dict[str, Any],
                           carried: Dict[str, Dict[str, str]]) -> None:
    for c in copies:
        rows, roles = set(), False
        for box, value in (c.get("boxes") or {}).items():
            m = _CONTACT_BOX_RE.match(box)
            if not m or not _is_value(value) or (c.get("kinds") or {}).get(box, "text") in _TICK_KINDS:
                continue
            rows.add(m.group("row"))
            roles = roles or m.group("col") == "ContactDescription"
        if len(rows) < 2 and not roles:
            continue
        for key in _CONTACT_SCALARS:
            held = facts.get(key)
            box = str(held.get("box") or "") if isinstance(held, dict) else ""
            if _CONTACT_BOX_RE.match(box) and box in (c.get("boxes") or {}):
                facts.pop(key, None)
                carried.setdefault(_carry_key(c), {})[box] = (
                    (c.get("raw") or {}).get(box) or str(c["boxes"][box]))


# A box the stamper fills from ONE OF SEVERAL facts by the value's own
# vocabulary: ACORD 125's PAYMENT METHOD prints the payment METHOD when a fact
# states one in the stamper's closed vocabulary (ACH, EFT, credit card ...) and
# the billing plan otherwise (`pdf_service._resolve_payment_method_description`).
# The probe's marker is no method word, so the map learned "billing plan" - and
# CH125's "ACH" came back as the billing plan, a Data Consistency card against
# the declarations' "Direct bill" (review, 28 Oct 2026). The same vocabulary
# decides the reading.
def _vocabulary_fact(box: str, fact: str, value: str) -> str:
    try:
        from services.pdf_service import _PAYMENT_METHOD_RE, _PAYMENT_METHOD_WORDS
    except Exception:                                          # noqa: BLE001
        return fact
    if fact in ("billing_plan", "payment_plan") and _PAYMENT_METHOD_RE.match(box or "") \
            and _PAYMENT_METHOD_WORDS.search(str(value or "")):
        return "payment_method"
    return fact


def _copies_agree(key: str, values: List[str]) -> bool:
    """Do the copies state one value? The merge's one comparison door, then a
    loose spelling match ("Alpha Roofing LLC" / "ALPHA ROOFING, L.L.C.")."""
    first = values[0]
    try:
        from services.acord_intake.merge_rules import _agrees, _norm
    except Exception:                                          # noqa: BLE001
        return all(v == first for v in values)
    return all(_agrees(key, first, v) or _norm(first) == _norm(v) for v in values[1:])


def boxes_to_facts(copies: List[dict]):
    """Every copy's boxes -> (facts, carried). Rules in the module docstring."""
    facts: Dict[str, Any] = {}
    carried: Dict[str, Dict[str, str]] = {}
    addr: Dict[str, Dict[str, str]] = {}
    addr_meta: Dict[str, tuple] = {}
    lists: Dict[str, Dict[int, dict]] = {}
    lines: Dict[str, dict] = {}
    prior: Dict[tuple, dict] = {}
    prior_year: Dict[str, str] = {}
    ticks: Dict[str, List[str]] = {}
    lob_other: Dict[str, str] = {}
    lob_other_ticked: set = set()
    spread: Dict[tuple, str] = {}
    symbols: Dict[str, List[int]] = {}
    roster: Dict[str, Dict[str, str]] = {}
    roster_refs: List[tuple] = []
    item_lists: Dict[str, Dict[int, str]] = {}       # "additional_named_insureds#1" -> list item 1
    row_said: Dict[str, set] = {}                     # a package value read off every grid row
    # {fact: {copy: value}} - a scalar each COPY states (production fuzz, 29 Oct
    # 2026): the first copy's box won and a later copy filled only the facts the
    # first left blank, so two copies of one form (an old and a revised 125, or
    # two insureds' 125s in one PDF) came back as ONE application - the first
    # insured's name with the second's FEIN, entity type and expiration date, all
    # labelled exact. Copies that disagree give no reading (blank over wrong).
    copy_said: Dict[str, Dict[tuple, str]] = {}
    tick_readers: Dict[str, set] = {}                 # fact -> the copy kinds whose ticks chose it
    addr_copies: Dict[str, Dict[tuple, Dict[str, str]]] = {}
    for c in copies:
        fid = c["form_id"]
        copy_id = (fid, c.get("copy", 1), c.get("kind") or "")
        row_base = 0
        if c.get("copy", 1) > 1:
            # A second copy continues the first one's tables (rows E.. of a
            # 4-row schedule) - rows are offset so they never collide.
            row_base = 100 * (c["copy"] - 1)
        raw_of = c.get("raw") or {}
        for box, value in c["boxes"].items():
            kind = c["kinds"].get(box, "text")
            page = c["box_page"].get(box, 0)
            # The text as typed (line breaks kept, never cut) where the field
            # reader has it; the flattened overlay reads only the one-line text.
            typed = (raw_of.get(box) or str(value or "")) if kind not in _TICK_KINDS else value
            if _FORM_META_RE.match(box):
                continue
            tg = box_targets(fid, box)
            if any(t.get("t") == "package" for t in tg):
                continue                     # the package's own fact (attachments)
            tg = [t for t in tg if t.get("t") != "carry"]
            is_tick = kind in _TICK_KINDS
            if fid == "ACORD_101" and box.startswith("AdditionalRemark_RemarkText") and _is_value(value):
                _continued_vehicles(str(value), lists)
            if not tg:
                if is_tick:
                    # A ticked box is carried as the stamper writes a tick ("Yes");
                    # an unticked one is not carried at all.
                    if kind == "check" and _ticked(kind, value):
                        carried.setdefault(fid if c.get("copy", 1) == 1 else f"{fid}#{c['copy']}", {})[box] = "Yes"
                elif _is_value(value):
                    carried.setdefault(fid if c.get("copy", 1) == 1 else f"{fid}#{c['copy']}", {})[box] = typed
                continue
            refused = 0                      # whole-fact targets that refused the value
            # A tick the map gives SEVERAL options of one fact (the 126's GL
            # coverage box: Occurrence AND Claims-made) chooses none of them:
            # it is carried as the tick it is (round trip, 27 Oct 2026).
            _opts = [(t["fact"], t.get("value")) for t in tg if t.get("t") == "tick"]
            if len(_opts) >= 2 and len({f for f, _v in _opts}) == 1 and len({v for _f, v in _opts}) >= 2:
                tg = [t for t in tg if t.get("t") != "tick"]
                if kind == "check" and _ticked(kind, value):
                    carried.setdefault(fid if c.get("copy", 1) == 1 else f"{fid}#{c['copy']}", {})[box] = "Yes"
            for t in tg:
                kind_t = t.get("t")
                if kind_t == "tick":
                    if _ticked(kind, value):
                        tick_readers.setdefault(t["fact"], set()).add(c.get("kind") or "")
                        ticks.setdefault(t["fact"], [])
                        if t["value"] not in ticks[t["fact"]]:
                            ticks[t["fact"]].append(t["value"])
                    continue
                if kind_t == "symbol":
                    if _ticked(kind, value):
                        symbols.setdefault(t["coverage"], [])
                        if t["symbol"] not in symbols[t["coverage"]]:
                            symbols[t["coverage"]].append(t["symbol"])
                    continue
                if kind_t == "lob_other_tick":
                    if _ticked(kind, value):
                        lob_other_ticked.add(t["row"])
                        # The application's own OTHER line rows print back on it:
                        # with no declarations no coverage line record prints
                        # them (forms-only round trip, 27 Oct 2026). The carry
                        # fills only a box the engine leaves empty.
                        carried.setdefault(fid if c.get("copy", 1) == 1 else f"{fid}#{c['copy']}", {})[box] = "Yes"
                    continue
                if is_tick or not _is_value(value):
                    continue
                v = str(value).strip()
                if kind_t == "by_tick":
                    def _on(name):
                        return bool(name) and name in c["boxes"] and _ticked(c["kinds"].get(name, "check"),
                                                                             c["boxes"][name])
                    csl_on, each_on = _on(t["csl_box"]), _on(t["each_box"])
                    key = t["csl_fact"] if csl_on and not each_on else t["each_fact"] if each_on and not csl_on else None
                    if key and fits_fact(key, v):
                        facts.setdefault(key, _env(v, fid, box, page))
                    elif len(tg) == 1:
                        # No tick names its fact (an interest that is not a loss
                        # payee - CH125's landlord, 27 Oct 2026): the box comes
                        # back as printed, never dropped.
                        carried.setdefault(fid if c.get("copy", 1) == 1 else f"{fid}#{c['copy']}", {})[box] = typed
                    continue
                if kind_t == "roster":
                    roster.setdefault(t["letter"], {}).setdefault(t["col"], v)
                    continue
                if kind_t == "roster_ref":
                    roster_refs.append((t["line"], v.strip().upper()[:1]))
                    continue
                if kind_t == "fact" and t.get("prose"):
                    v = own_blocks_removed(typed)
                    if not v or not _is_value(v):
                        continue
                if kind_t == "fact" and "#" in str(t["fact"]) and (t.get("part") or "whole") == "whole":
                    base, _h, idx = str(t["fact"]).partition("#")
                    if idx.isdigit():
                        item_lists.setdefault(base, {}).setdefault(int(idx), v)
                    continue
                if kind_t == "fact":
                    key, part = _vocabulary_fact(box, t["fact"], v), t.get("part") or "whole"
                    if t.get("from_rows"):
                        row_said.setdefault(key, set()).add(re.sub(r"[^a-z0-9.]", "", v.lower()))
                    if part == "whole":
                        if fits_fact(key, v):
                            facts.setdefault(key, _env(v, fid, box, page))
                            copy_said.setdefault(key, {}).setdefault(copy_id, v)
                        else:
                            refused += 1
                    else:
                        addr.setdefault(key, {}).setdefault(part, v)
                        addr_meta.setdefault(key, (fid, box, page))
                        addr_copies.setdefault(key, {}).setdefault(copy_id, {}).setdefault(part, v)
                elif kind_t == "cell":
                    if t.get("list") == "coverage_lines" and t.get("line"):
                        row = lines.setdefault(t["line"], {"line": t["line"]})
                        row.setdefault(t["col"], v)
                    elif t.get("row") is not None:
                        rows = lists.setdefault(t["list"], {})
                        rows.setdefault(row_base + int(t["row"]), {}).setdefault(t["col"], v)
                    else:
                        facts.setdefault(t["list"], _env(v, fid, box, page))
                elif kind_t == "prior":
                    if t["col"] == "year":
                        prior_year[t["row"]] = v
                    else:
                        k = (t["row"], t["line_token"])
                        rec = prior.setdefault(k, {"line": t.get("line") or ""})
                        if t["col"] == "line":
                            rec["line"] = rec.get("line") or v
                        else:
                            rec.setdefault(t["col"], v)
                elif kind_t == "cell_all":
                    spread.setdefault((t["list"], t["col"]), v)
                elif kind_t == "lob_other":
                    lob_other[t["row"]] = v
                    carried.setdefault(fid if c.get("copy", 1) == 1 else f"{fid}#{c['copy']}", {})[box] = typed
                elif kind_t == "code":
                    from services.acord_intake.reverse_map import decode
                    decoded = decode(t.get("table") or "", v)
                    if t.get("from_rows"):
                        row_said.setdefault(t["fact"], set()).add(str(decoded or v).lower())
                    if decoded:
                        facts.setdefault(t["fact"], _env(decoded, fid, box, page))
                        copy_said.setdefault(t["fact"], {}).setdefault(copy_id, str(decoded))
            # Every target refused the value (a bare year "2011" in a start DATE
            # box): no fact holds it, so the box is CARRIED onto its own form
            # rather than lost (round trip, 27 Oct 2026).
            if refused and refused == len(tg) and not is_tick and _is_value(value):
                carried.setdefault(fid if c.get("copy", 1) == 1 else f"{fid}#{c['copy']}", {})[box] = typed
    for key, by_copy in addr_copies.items():
        # An address is ONE copy's parts, never one copy's street with another's
        # city / ZIP (production fuzz, 29 Oct 2026).
        if len(by_copy) > 1:
            first = next(iter(by_copy))
            addr[key] = dict(by_copy[first])
            for cid, parts in by_copy.items():
                composed = _compose_address(parts)
                if composed:
                    copy_said.setdefault(key, {}).setdefault(cid, composed)
    for key, said in copy_said.items():
        if len(said) > 1 and not _copies_agree(key, list(said.values())):
            facts.pop(key, None)
            addr.pop(key, None)
            logger.info("acord_intake: %s - %d copies disagree, no reading", key, len(said))
    for key, parts in addr.items():
        if key not in facts:
            fid, box, page = addr_meta[key]
            composed = _compose_address(parts)
            base, _h, idx = key.partition("#")
            if composed and idx.isdigit():
                item_lists.setdefault(base, {}).setdefault(int(idx), composed)
            elif composed and fits_fact(key, composed):
                facts[key] = _env(composed, fid, box, page)
    # One package value read off a grid's rows (ACORD 140's coinsurance per
    # premises): rows that disagree give no package value (blank over wrong).
    for key, said in row_said.items():
        if len(said) > 1:
            facts.pop(key, None)
    for base, items in item_lists.items():
        if base not in facts:
            facts[base] = [items[i] for i in sorted(items)]
    # ACORD 25's roster: a coverage row's carrier is the insurer its INSR LTR
    # names. With ONE insurer listed it affords every row the form shows.
    if roster:
        named = {k: r for k, r in roster.items() if r.get("carrier")}
        for line, letter in roster_refs:
            ins = roster.get(letter)
            if ins:
                row = lines.setdefault(line, {"line": line})
                for col in ("carrier", "naic"):
                    if ins.get(col):
                        row.setdefault(col, ins[col])
        if len(named) == 1:
            (only,) = named.values()
            lettered = {line for line, _l in roster_refs}
            for line, row in lines.items():
                if line not in lettered:
                    for col in ("carrier", "naic"):
                        if only.get(col):
                            row.setdefault(col, only[col])
    for (key, col), v in spread.items():
        for r in (lists.get(key) or {}).values():
            if any(_is_value(x) for x in r.values()):
                r.setdefault(col, v)
    _contact_schedule_rule(copies, facts, carried)
    _apply_premises_grid(_premises_grid(copies), lists, facts)
    _und = _underlying_schedule(copies)
    if _und and "underlying_policies" not in facts:
        facts["underlying_policies"] = _und
    for key, rows in lists.items():
        if key in facts:
            continue
        built = []
        for _i, r in sorted(rows.items()):
            given, surname = r.pop("_given", None), r.pop("_surname", None)
            if (given or surname) and not r.get("name"):
                r["name"] = " ".join(x for x in (given, surname) if x)
            if any(_is_value(x) for x in r.values()):
                built.append(r)
        facts[key] = _drop_summary_echoes(built)
    _join_line_rows(lines, _other_insurance_rows(copies))
    if lines:
        facts.setdefault("coverage_lines", list(lines.values()))
    if prior:
        rows = []
        for (row, _tok), rec in sorted(prior.items()):
            if not any(rec.get(k) for k in ("carrier", "policy_no", "premium", "effective", "expiration")):
                continue
            if prior_year.get(row):
                rec["year"] = prior_year[row]
            rows.append(rec)
        if rows:
            facts.setdefault("prior_coverage_by_line", rows)
    for row in sorted(lob_other_ticked):
        name = lob_other.get(row)
        if name:
            ticks.setdefault("lines_of_business", [])
            if name not in ticks["lines_of_business"]:
                ticks["lines_of_business"].append(name)
    # A tick naming a covered-auto SYMBOL (the 131's "Any auto" box - ACORD's
    # tooltip says "symbol 1") is a liability symbol, never a scalar: written as
    # one, the merge read the envelope's own keys as the symbol list and the
    # round trip lost symbol 1 (27 Oct 2026, the Orbin round trip).
    for picked in ticks.pop("auto_covered_symbols", []) or []:
        for num in re.findall(r"\b(\d{1,2})\b", str(picked)):
            symbols.setdefault("liability", [])
            if int(num) not in symbols["liability"]:
                symbols["liability"].append(int(num))
    if symbols:
        facts.setdefault("auto_covered_symbols",
                         [{"coverage": cov, "symbols": sorted(nums)} for cov, nums in symbols.items()])
    for key, chosen in ticks.items():
        if key == "lines_of_business":
            facts.setdefault(key, list(chosen))
        elif len(chosen) == 1 and key not in facts:
            facts[key] = {"value": chosen[0], "source": SOURCE, "confidence": CONFIDENCE}
            if "transcriber" in tick_readers.get(key, ()):
                # A tick ASG Transcriber read off an image is its reading, in a
                # mixed document too - it was left "exact" there because the
                # envelope names no box (production fuzz, 29 Oct 2026).
                facts[key].update(confidence=TRANSCRIBER_CONFIDENCE, reader="transcriber")
        # Two different options ticked for one choice: no reading (blank over wrong).
    return facts, carried
