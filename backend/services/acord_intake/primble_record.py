"""The Primble record inside every ACORD form we generate (27 Oct 2026, owner).

WHY. A form only holds what its boxes hold. A producer's answer no ACORD box
prints (occupancy type, a hard stop answered on the review page) would be asked
AGAIN when our own forms come back in a package (Brent's round trip). And a
re-read box cannot tell an AI guess from a typed value. So each generated PDF
carries, in its document information, ONE encrypted record:
  {"v": 1, "form": form id,
   "answers":  {fact: envelope}  - every fact a PERSON put in the package,
   "ai_boxes": [box, ...]}       - the boxes the AI filled.
Encrypted with the server key (`utils.crypto`): a carrier opening the PDF sees
an opaque string. The local and Render keys differ, so a form downloaded from
primble.ai restores on primble.ai only - elsewhere it reads like anyone's form.

`attach(pdf_bytes, session, form_id)` -> bytes (unchanged on any failure).
`read(pdf_path)` -> dict | None. PRIMBLE_FORM_RECORD=0 turns both off.
"""
import io
import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)
KEY = "/PrimbleRecord"
# v2 (review, 27 Oct 2026) names the package's insured; a v1 record (written by
# the 27 Oct localhost build only - nothing was deployed with it) names nobody
# and restores as it did.
VERSION = 2
_READABLE = (1, 2)
# A record is a few KB; anything this large is not one of ours.
_MAX_BLOB_CHARS = 1_000_000


def _on() -> bool:
    return os.getenv("PRIMBLE_FORM_RECORD", "1") != "0"


def _is_answer(v: Any) -> bool:
    """A person's answer the record carries: a value, or an answer that there is
    NONE - "None" / "N/A", stored as an empty value with its state
    (`answer_semantics.build_fact_envelope`). Without the second, every "None"
    the producer gave on the way to 100 came back asked again (review, 27 Oct
    2026)."""
    if not isinstance(v, dict):
        return False
    if v.get("value") not in (None, ""):
        return True
    try:
        from services.fact_state import EXPLICIT_NO, NOT_APPLICABLE
    except Exception:                                          # noqa: BLE001
        return False
    return str(v.get("value_state") or "") in (EXPLICIT_NO, NOT_APPLICABLE)


def _person_answers(facts: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    try:
        from services.fact_state import put_by_person
    except Exception:                                          # noqa: BLE001
        return out
    for k, v in (facts or {}).items():
        if isinstance(v, dict) and "value" in v and put_by_person(v) and _is_answer(v):
            out[k] = {kk: v[kk] for kk in ("value", "source", "confidence", "value_state", "evidence_state",
                                           "answer_text", "typed_parts")
                      if kk in v}
    return out


def _person_tables(facts: Dict[str, Any]) -> Dict[str, Any]:
    """{list key: {"rows", "source"}} for every table a PERSON saved whose rows
    still match what they saved (`schedule_capture.human_rows`) - a GL class
    table prints only on the 126, which a re-upload may not include."""
    out: Dict[str, Any] = {}
    try:
        from services.schedule_capture import HUMAN_SCHEDULES_KEY, human_rows
        for key in (facts.get(HUMAN_SCHEDULES_KEY) or {}):
            rows, source = human_rows(facts, key)
            if rows:
                out[key] = {"rows": rows, "saved_by": source or "producer"}
    except Exception:                                          # noqa: BLE001
        pass
    return out


def _person_stores(facts: Dict[str, Any]) -> Dict[str, Any]:
    """The decisions a person made that are not answers but STORES the pipeline
    re-applies over the documents (27 Oct 2026, owner): the Policies table's
    edits / added lines / prior-carrier "Other" pick (`policy_lines.STORE_KEY`).
    A warning cleared by an explanation needs nothing here - its mark
    (`_explained_issue_codes`) is a producer answer and rides `answers`."""
    out: Dict[str, Any] = {}
    try:
        import copy
        from services.policy_lines import STORE_KEY, read_store, store_has_content
        held = (facts or {}).get(STORE_KEY)
        if isinstance(held, dict) and store_has_content(read_store(facts)):
            out[STORE_KEY] = copy.deepcopy(held)
    except Exception:                                          # noqa: BLE001
        pass
    # The narrative's stored READING (27 Oct 2026, the Choice Electric round
    # trip: the restored narrative was word for word the same but scored 89
    # against 100 - its reading, which credited three topics a paraphrase
    # covers, stayed behind). Keyed by the text's own hash, so it counts only
    # while the narrative is unchanged; with it rides `typed_parts` (answers).
    try:
        from services.narrative_reader import READING_KEY
        reading = (facts or {}).get(READING_KEY)
        if isinstance(reading, dict) and reading:
            import copy as _copy
            out[READING_KEY] = _copy.deepcopy(reading)
    except Exception:                                          # noqa: BLE001
        pass
    return out


# WHAT THE BUSINESS IS, as the package's documents and answers said it (28 Oct
# 2026, review): a forms-only re-upload carries no declarations, so every flag
# the declarations set (`is_contractor`, `auto_has_hired_nonowned`, ...) was
# gone - and with it every charge those flags gate ("Percent of work
# subcontracted" -8 on a contractor). The re-upload scored ABOVE the package
# that printed the forms for knowing less. The record carries the TRUE flags; a
# flag any uploaded document states (true or false) wins (`merge_rules.
# apply_restored_flags`). Never a flag that describes the DOCUMENTS or what they
# say about losses and the narrative - evidence that is not in the re-upload
# must not be credited (a "has_loss_run_doc" without loss runs).
_EVIDENCE_FLAG_WORDS = ("loss", "narrative", "doc", "certificate", "claim")


def restorable_flag(key: str) -> bool:
    """Nor a LINE flag (`has_umbrella`, `has_auto_coverage`): which lines this
    submission applies for is what the uploaded forms state (`intake.
    _flags_from` - a section form, the 125's ticks); restored from a cover
    alone, the umbrella flag raised "no underlying limits" over a package
    whose policies were not uploaded."""
    k = str(key or "")
    if not k or k.startswith("_") or k.startswith("asserts_") or any(w in k for w in _EVIDENCE_FLAG_WORDS):
        return False
    if k.startswith("has_"):
        try:
            from services.lob_canon import canon_line
            if canon_line(k[4:].replace("_", " ")):
                return False
        except Exception:                                      # noqa: BLE001
            return False
    return True


def _package_flags(session: dict) -> Dict[str, bool]:
    return {k: True for k, v in ((session or {}).get("flags") or {}).items()
            if v is True and restorable_flag(k)}


def _proposed_term(facts: Dict[str, Any]) -> Dict[str, Any]:
    """The package's proposed term, so a record from last year's package is
    known as last year's (`summary_payload`) without a form to read it off."""
    out = {}
    for k in ("effective_date", "expiration_date"):
        v = (facts or {}).get(k)
        v = v.get("value") if isinstance(v, dict) else v
        if v not in (None, ""):
            out[k] = str(v)
    return out


# The box labels that mean "the AI placed this value" (`sqs_service.
# CONFIDENCE_SCORE`: "ai_verified" found in the documents, "low_confidence" an
# unverified guess). "low_confidence" is ALSO the label of a value WE calculated
# (`pdf_service.prints_a_calculated_value` - the next policy term): a guess of
# ours either way, never the form's statement. The first build kept only labels
# starting "ai", so every unverified AI guess read back as an exact reading
# (review, 28 Oct 2026).
_AI_LABELS = ("ai_verified", "low_confidence", "ai_high", "ai_low", "ai")


def _label_of(c: Any) -> str:
    return str((c.get("label") if isinstance(c, dict) else c) or "")


def _is_ai_label(label: str) -> bool:
    return label in _AI_LABELS or label.startswith("ai")


def _fact_backed(form_id: str, box: str, value: Any, facts: Dict[str, Any]) -> bool:
    """A "low_confidence" box that prints a FACT's value: a value we calculated
    (the next policy term, the 127's maximum exposure - `pdf_service.
    prints_a_calculated_value`) or a fact a deterministic rule stamped. Both are
    the package's facts and read back as the form's statement."""
    try:
        from services import pdf_service as ps
        base = str(form_id or "").split("__", 1)[0]
        if ps.prints_a_calculated_value(base, box, value, facts):
            return True
        # What the stamper's own deterministic door prints in this box with no
        # model call (an address part comes from a composed resolver, a
        # producer box from the login account - not a fact of its own).
        ruled = ps._deterministic_map(box, {**(facts or {}), "_form_id": base})
        if isinstance(ruled, str) and ruled not in ("UNMATCHED",) and ps._box_prints_fact_value(value, ruled):
            return True
        key = ps.source_fact_for_field(box, facts, base)
        held = (facts or {}).get(key) if key else None
        if held is None:
            return False
        whole = held.get("value") if isinstance(held, dict) else held
        if ps._box_prints_fact_value(value, whole):
            return True
        # A PART of the fact (an address's postal code, labelled "verify" by a
        # shape check - an Indian PIN in a US ZIP box): still the fact's value.
        import re as _re
        part = _re.sub(r"[^a-z0-9]", "", str(value).lower())
        return len(part) >= 2 and part in _re.sub(r"[^a-z0-9]", "", str(whole or "").lower())
    except Exception:                                          # noqa: BLE001
        return True                      # cannot tell: never call a fact's box an AI guess


def _ai_boxes(generated_form: dict, facts: Optional[Dict[str, Any]] = None, form_id: str = "") -> list:
    conf = (generated_form or {}).get("confidence") or {}
    mapped = (generated_form or {}).get("mapped") or {}
    out = []
    for box, c in conf.items():
        label, value = _label_of(c), mapped.get(box)
        if not _is_ai_label(label):
            continue
        if label == "low_confidence" and (value in (None, "", "Off")
                                          or _fact_backed(form_id, box, value, facts or {})):
            continue                     # an empty box's default label, or a fact's value
        out.append(box)
    return sorted(out)


def _ai_labels(generated_form: dict, boxes: list) -> Dict[str, str]:
    conf = (generated_form or {}).get("confidence") or {}
    return {b: _label_of(conf.get(b)) for b in boxes}


def _printed_values(pdf, boxes: list) -> Dict[str, str]:
    """{box: fingerprint of what the PDF itself prints} for the AI text boxes -
    a box the person types over after download is then their statement
    (`read._strip_ai_boxes`)."""
    want = set(boxes)
    out: Dict[str, str] = {}
    try:
        from utils import form_field_text as fft
        from services.acord_intake.read import value_fingerprint
        for order, g in enumerate(fft._scan_widgets(pdf).values()):
            e = fft._field_entry(g, order)
            if e is not None and e.name in want and e.kind not in ("check", "radio"):
                out[e.name] = value_fingerprint(e.value)
    except Exception as ex:                                    # noqa: BLE001
        logger.info("primble record: AI box values not fingerprinted: %s", ex)
    return out


# Certificates (ACORD 25 / 28) go to certificate holders and other third
# parties - they never carry the package's answers, encrypted or not.
_NO_RECORD_FORMS = ("ACORD_25", "ACORD_28")
# The record on the package's SQS summary (the cover page in every download,
# 27 Oct 2026, owner): the same answers, tables and stores, no form of its own -
# re-uploaded with the declarations alone it restores everything.
SUMMARY_FORM = "PRIMBLE_SUMMARY"


# VALUES ONLY THE LOSS RUNS STATED (27 Oct 2026, live: the Orbin round trip). The
# declarations print no FEIN; the loss runs do, so the package's FEIN - printed on
# ACORD 125 - was the loss runs' own. Re-uploaded, the 125's FEIN read as the
# APPLICATION's, the loss runs then "matched" it, and Loss History rose 85 -> 100
# with no one confirming the runs are this insured's: the loss runs vouched for
# themselves (`loss_run_identity._package_identity` excludes them for exactly
# this - M3). The record names such facts; their box readings are marked
# (`apply`) and the matcher leaves them out.
def _loss_run_only_facts(session: dict) -> Dict[str, str]:
    facts = (session or {}).get("facts") or {}
    out: Dict[str, str] = {}
    try:
        from services.fact_state import put_by_person
    except Exception:                                          # noqa: BLE001
        put_by_person = lambda _v: False                       # noqa: E731
    docs = [d for d in (session or {}).get("docs") or [] if isinstance(d, dict) and not d.get("excluded")]
    for key in ("fein", "dba_name", "mailing_address", "physical_address", "policy_number"):
        held = facts.get(key)
        val = held.get("value") if isinstance(held, dict) else held
        if not val or put_by_person(held):
            continue
        stating = [d for d in docs if (lambda v: (v.get("value") if isinstance(v, dict) else v))(
            (d.get("facts") or {}).get(key))]
        # A form of OURS re-uploaded that printed the loss runs' value back is
        # still the loss runs speaking (`apply` marked it): without this, the
        # second round trip - a package rebuilt from our forms and the loss
        # runs, downloaded and re-uploaded again - let the loss runs verify
        # themselves through two hops (review, 28 Oct 2026).
        def _loss_runs_say(d):
            held = (d.get("facts") or {}).get(key)
            return d.get("doc_type") == "loss_run" or (isinstance(held, dict) and held.get("echo_of") == "loss_run")
        if stating and all(_loss_runs_say(d) for d in stating):
            out[key] = str(val)
    return out


# VALUES THE DOCUMENTS STATED (28 Oct 2026, live: CH125 forms + decs read 85
# against the original 100). Our form prints the package's reading of the
# declarations; re-uploaded beside those same declarations, extraction (not
# repeatable) read the dec's comp deductible as $500 this time, and our 127's
# $1,000 - nothing but the earlier reading printed back - became a second
# "document" disagreeing with it: three Data Consistency cards no original
# package had. The record names every value no person put, so `apply` marks a
# box printing it as an echo of the documents, and Data Consistency hears the
# documents themselves whenever one of them is uploaded too. A box changed
# after download no longer prints the value and stays the form's own word.
_ECHO_VALUE_MAX = 300


def _document_read_facts(facts: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        from services.fact_state import put_by_person
    except Exception:                                          # noqa: BLE001
        return out
    for k, held in (facts or {}).items():
        if str(k).startswith("_") or put_by_person(held):
            continue
        val = held.get("value") if isinstance(held, dict) else held
        if isinstance(val, bool) or not isinstance(val, (str, int, float)):
            continue
        val = str(val).strip()
        if val and len(val) <= _ECHO_VALUE_MAX:
            out[k] = val
    return out


def attach(pdf_bytes: bytes, session: dict, form_id: str) -> bytes:
    if not _on() or not pdf_bytes or str(form_id or "").split("__", 1)[0] in _NO_RECORD_FORMS:
        return pdf_bytes
    try:
        import pikepdf
        from utils.crypto import encrypt_field
        g = ((session or {}).get("generated_forms") or {}).get(form_id) or {}
        facts = (session or {}).get("facts") or {}
        applicant = facts.get("applicant_name")
        applicant = applicant.get("value") if isinstance(applicant, dict) else applicant
        record = {"v": VERSION, "form": form_id,
                  # whose package these answers are: restored only into a form
                  # that still names the same insured (`apply`)
                  "applicant": str(applicant or "").strip(),
                  # whose ACCOUNT wrote them (29 Oct 2026): another agency uploading
                  # the same company's form gets none of this agency's answers
                  "account": account_key((session or {}).get("user_id")),
                  "answers": _person_answers(facts),
                  "tables": _person_tables(facts),
                  "stores": _person_stores(facts),
                  "term": _proposed_term(facts),
                  "ai_boxes": _ai_boxes(g, facts, form_id),
                  "loss_run_only": _loss_run_only_facts(session),
                  "document_read": _document_read_facts(facts),
                  "flags": _package_flags(session),
                  # the Data Consistency picks (`underwriting_consistency`) -
                  # a person's choice between the documents, re-applied over
                  # them on every run of the pipeline
                  "confirmations": dict((session or {}).get("underwriting_confirmations") or {})}
        record["ai_labels"] = _ai_labels(g, record["ai_boxes"])
        with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
            record["ai_values"] = _printed_values(pdf, record["ai_boxes"])
            blob = encrypt_field(json.dumps(record, separators=(",", ":"), default=str))
            pdf.docinfo[KEY] = pikepdf.String(blob)
            out = io.BytesIO()
            pdf.save(out)
            return out.getvalue()
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("primble record not attached to %s: %s", form_id, ex)
        return pdf_bytes


def carries_record(pdf_path: str) -> bool:
    """Does the file carry a Primble record at all - decryptable or not? A form of
    ours re-uploaded on a server with another key still is ours: it is never sent
    to ASG Transcriber (29 Oct 2026), whatever the record restores."""
    try:
        import pikepdf
        with pikepdf.open(pdf_path) as pdf:
            blob = pdf.docinfo.get(KEY)
            # A STRING under the size cap (we write an "enc:" token; one sealed
            # with another server's key is still ours): a stray /PrimbleRecord
            # integer or dictionary on an outside PDF is not, and must not keep
            # it from Transcriber (production review, 29 Oct 2026).
            if not isinstance(blob, pikepdf.String):
                return False
            text = str(blob).strip()
            return bool(text) and len(text) <= _MAX_BLOB_CHARS
    except Exception:                                          # noqa: BLE001
        return False


# ── the restored payload at rest (production review, 29 Oct 2026) ────────────
# `apply` returns the PERSON's answers (FEIN, revenue, typed narratives), tables
# and Data Consistency picks. They ride the document's ACORD record, and the
# session row stores `docs` as plain JSON (only `facts` is field-encrypted) - so
# the decrypted payload sat in the database in the clear. It is sealed with the
# same field key as the facts; `restored_of` is the ONE reader (a legacy row
# still holding a plain dict is read as it is).
def seal_restored(payload: Optional[dict]) -> Any:
    if not payload:
        return payload
    try:
        from utils.crypto import encrypt_field
        return encrypt_field(json.dumps(payload, separators=(",", ":"), default=str)) or payload
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("primble record: restored payload not sealed: %s", ex)
        return payload


def restored_of(holder: Any) -> dict:
    """The restored payload of a document (`doc["acord"]["restored"]`) or of an
    intake record (`record["restored"]`), opened. {} when absent or unreadable."""
    if not isinstance(holder, dict):
        return {}
    got = holder.get("restored")
    if got is None and isinstance(holder.get("acord"), dict):
        got = holder["acord"].get("restored")
    if isinstance(got, dict):
        return got
    if isinstance(got, str) and got:
        try:
            from utils.crypto import decrypt_field_soft
            data = json.loads(decrypt_field_soft(got) or "{}")
            return data if isinstance(data, dict) else {}
        except Exception:                                      # noqa: BLE001
            return {}
    return {}


def read(pdf_path: str) -> Optional[dict]:
    if not _on():
        return None
    try:
        import pikepdf
        from utils.crypto import decrypt_field_soft
        with pikepdf.open(pdf_path) as pdf:
            blob = pdf.docinfo.get(KEY)
            if blob is None:
                return None
            blob = str(blob)
        # Only an AUTHENTICATED record is ours: `decrypt_field` hands a value
        # without the "enc:" prefix back as legacy plaintext, so a hand-written
        # JSON in the PDF's document info read as producer answers (review,
        # 27 Oct 2026). Fernet's token is signed - a tampered or foreign-key blob
        # fails to decrypt and is ignored.
        if not blob.startswith("enc:") or len(blob) > _MAX_BLOB_CHARS:
            return None
        # soft: a record sealed with ANOTHER server's key (UAT form on production) is
        # simply not ours to read - no ERROR line per upload (review, 29 Oct 2026)
        plain = decrypt_field_soft(blob)
        if not plain or plain == blob:
            return None
        data = json.loads(plain)
        return data if isinstance(data, dict) and data.get("v") in _READABLE else None
    except Exception as ex:                                    # noqa: BLE001
        logger.info("primble record unreadable in %s: %s", pdf_path, ex)
        return None


def _same_value(key: str, a: Any, b: Any) -> bool:
    """The one comparison door (`fact_comparison.values_agree`); equal text if
    it is unavailable."""
    try:
        from services.fact_comparison import values_agree
        return bool(values_agree(key, a, b))
    except Exception:                                          # noqa: BLE001
        return str(a or "").strip().lower() == str(b or "").strip().lower()


# ── ACCOUNT BINDING (owner, 29 Oct 2026) ─────────────────────────────────────
# A record is bound to the insured's NAME and to the ACCOUNT that wrote it. The
# same company's Primble form uploaded by another agency restores none of the
# first agency's answers, tables or Data Consistency picks: it is read as an
# outside form (its boxes are its statements). The uploader is set per upload by
# `extraction_pipeline.extract_document` (`uploading_account`); a record written
# before 29 Oct carries no account and keeps today's behaviour, and a read with
# no uploader known (offline replays, tests) is not judged.
import contextvars as _contextvars
import hashlib as _hashlib

_UPLOADER: "_contextvars.ContextVar[Optional[str]]" = _contextvars.ContextVar("primble_uploader", default=None)


def account_key(user_id: Any) -> str:
    """A one-way key for an account id (the record never carries the raw id)."""
    raw = str(user_id or "").strip()
    return _hashlib.sha256(f"primble-account|{raw}".encode()).hexdigest()[:24] if raw else ""


def uploading_account(user_id: Any):
    """Set the uploader for the reads that follow (returns the reset token)."""
    return _UPLOADER.set(account_key(user_id) or None)


def same_account(record: Optional[dict]) -> bool:
    if not isinstance(record, dict):
        return False
    written_by = str(record.get("account") or "")
    reader = _UPLOADER.get()
    if not written_by or not reader:
        return True
    return written_by == reader


def _same_insured(record: dict, facts: Dict[str, Any]) -> bool:
    """Does the form still name the insured whose package wrote the record? An
    agent who re-uses Primble's filled 125 for client X as the starting point for
    client Y uploads Y's boxes with X's record: X's answers must not become Y's
    (they would arrive as a PERSON's answers, which beat documents and which
    `insured_scope` never scopes). Positive evidence only - a record or a form
    naming nobody restores nothing."""
    if record.get("v") == 1:
        return True                      # written before records named their insured
    theirs = str(record.get("applicant") or "").strip()
    ours = facts.get("applicant_name")
    ours = str((ours.get("value") if isinstance(ours, dict) else ours) or "").strip()
    if not theirs or not ours:
        return False
    try:
        from services.insured_scope import _same_entity
        return _same_entity(theirs, ours) is True
    except Exception:                                          # noqa: BLE001
        return theirs.lower() == ours.lower()


def apply(record: Optional[dict], facts: Dict[str, Any], prior_application: bool = False) -> Optional[dict]:
    """A Primble record on a re-uploaded form: AI boxes read back stay AI values
    (on the document - they are its box readings), and the person's answers and
    tables the record holds are RETURNED, never written into the document's
    facts: {"answers": {fact: envelope}, "tables": {list: {"rows", "saved_by"}}},
    or None. Returned only when the form still names the record's insured and
    is not last year's application (its answers were for that term: a typed
    revenue or term must not outvote this year's declarations).

    Why not the document's facts (round trip, 27 Oct 2026): every per-document
    reader takes a document's facts as what that DOCUMENT prints. The Data
    Consistency picker then read the producer's 50% wind deductible as eleven
    forms printing 50% against the dec's 2% - a conflict card holding the
    package at 85, where on the original package the same answer was a person's
    settled value. A person's answer is the package's (`merge_rules.
    apply_restored_answers` puts it there), exactly where it lived before."""
    if not isinstance(record, dict) or not _same_insured(record, facts):
        return None                      # another insured's form: the record says nothing about it
    ai = set(record.get("ai_boxes") or [])
    for k, v in list(facts.items()):
        if isinstance(v, dict) and v.get("box") in ai:
            facts[k] = dict(v, source="ai", confidence="ai_high", restored_from="primble_record")
    for k, val in (record.get("loss_run_only") or {}).items():
        held = facts.get(k)
        if isinstance(held, dict) and _same_value(k, held.get("value"), val):
            facts[k] = dict(held, echo_of="loss_run")     # the loss runs' own value, printed back
    for k, val in (record.get("document_read") or {}).items():
        held = facts.get(k)
        if (isinstance(held, dict) and not held.get("echo_of") and held.get("source") == "acord_form"
                and _same_value(k, held.get("value"), val)):
            facts[k] = dict(held, echo_of="documents")    # the package's own reading, printed back
    if prior_application:
        return None
    if not same_account(record):
        # Another agency's form (29 Oct 2026): its AI boxes stay marked AI and its
        # echoes stay echoes (above - facts about the PDF, whoever reads it), but
        # none of that agency's answers, tables or picks is restored.
        logger.info("primble record: written by another account - nothing restored")
        return None
    answers = {}
    edited = []
    for k, v in (record.get("answers") or {}).items():
        if not _is_answer(v):
            continue
        # A box printing the person's OWN answer is that answer, not this form's
        # evidence: read back as the document's printing, the ACORD 28's wind box
        # (the producer's 50%) became a Data Consistency conflict with the dec's
        # 2% that the original package had settled by the answer (round trip,
        # 27 Oct 2026). A box CHANGED after download is the form's new statement:
        # it stays, and the old answer is not restored over it - by ANY form's
        # record (29 Oct 2026, review: the 125's hand-edited NAICS was overridden
        # by the 126's record restoring the old answer as a person's), so the
        # key is named in `edited` and the merge restores it from no record.
        held = facts.get(k)
        if isinstance(held, dict) and held.get("source") == "acord_form":
            if not _same_value(k, held.get("value"), v.get("value")):
                edited.append(k)
                continue
            facts.pop(k, None)
        answers[k] = dict(v, restored_from="primble_record")
    return _payload(answers, record, edited=edited)


def _payload(answers: Dict[str, Any], record: dict, edited: Optional[list] = None) -> Optional[dict]:
    tables = {k: {"rows": t["rows"], "saved_by": t.get("saved_by") or "producer"}
              for k, t in (record.get("tables") or {}).items()
              if isinstance(t, dict) and isinstance(t.get("rows"), list) and t["rows"]}
    stores = {k: v for k, v in (record.get("stores") or {}).items() if isinstance(v, dict) and v}
    out = {"answers": answers, "tables": tables, "stores": stores}
    flags = {k: True for k, v in (record.get("flags") or {}).items() if v is True and restorable_flag(k)}
    if flags:
        out["flags"] = flags
    picks = {str(k): v for k, v in (record.get("confirmations") or {}).items() if v is not None}
    if picks:
        out["confirmations"] = picks
    if edited:
        out["edited"] = sorted(set(edited))     # answers this form's boxes now contradict
    return out if (answers or tables or stores or flags or picks or edited) else None


def summary_payload(record: Optional[dict]) -> Optional[dict]:
    """The SQS summary's record as the package's restored answers / tables /
    stores, plus the insured it names - or None (not a summary record, last
    year's package, or nothing in it). The summary prints no box, so nothing
    here is a box reading; WHOSE package it is the merge decides against the
    other documents (`merge_rules.restoring_docs`)."""
    if not isinstance(record, dict) or record.get("form") != SUMMARY_FORM:
        return None
    if not same_account(record):
        return None                      # another agency's cover page
    try:
        from services.acord_intake.merge_rules import is_prior_application
        if is_prior_application({"facts": dict(record.get("term") or {})}, own_record=True):
            return None                  # last year's package: its answers were for that term
    except Exception:                                          # noqa: BLE001
        pass
    answers = {k: dict(v, restored_from="primble_record")
               for k, v in (record.get("answers") or {}).items() if _is_answer(v)}
    out = _payload(answers, record)
    if out is not None:
        out["applicant"] = str(record.get("applicant") or "").strip()
        # ...and the package's proposed term (27 Oct 2026): a cover uploaded
        # alone named its insured and term in its record and restored neither,
        # so "no proposed term" held it at 60. Gaps only (`merge_rules.
        # apply_restored_answers`): a document that states them wins.
        out["term"] = {k: v for k, v in (record.get("term") or {}).items() if v}
    return out
