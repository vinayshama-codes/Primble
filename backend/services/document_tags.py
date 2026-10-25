"""document_tags.py - what the Documents list says about each document
(owner, 14 Oct 2026, run `f83757cf`).

Two questions with two answers, never one pill:

1. WHAT the document is - its type label. A document that prints an ACORD
   form's own identity stamp ("ACORD 125 (2025/03)") is named by that form:
   "Commercial Insurance Application (ACORD 125)". The owner: "i added a filled
   acord form and it was picked not as a acord form but commercial insurance
   application, why?" The TYPE was right - an ACORD 125's printed title IS
   "COMMERCIAL INSURANCE APPLICATION", and the rules key on the type - but the
   label never said which form it was. The stamp is read by the recommender's
   own detector (`form_service._detect_uploaded_acord_forms`), never a second
   one, so the Documents list and "uploaded ACORD form detected by printed
   form-number stamp" can never disagree. `doc_type` is untouched.

2. WHOSE document it is - only when it names a DIFFERENT insured than the
   package's applicant. The owner: "i added another dec page that did not
   belong to this, it asked me to add or reject and then added and after
   adding the tag is showing 'strong match' even if they are from different
   insured, why". That pill measured how sure we are of the document's TYPE;
   beside another company's declarations it read as "matches this insured".
   The type pill now says what it measures, and this module answers the
   second question from the session's Submission Integrity record:

     * the package applicant is the Data Consistency CONFIRMED applicant (a
       person's decision) when there is one, else the integrity cluster with
       the most VERIFIED documents (21 Oct 2026 - two loss runs of another
       company never outvote the insured's own declarations), then the most
       documents (a tie goes to the cluster holding the earliest document - the
       package's own upload order);
     * names are compared through the one door, `normalization.
       same_entity_name`, on top of integrity's own clustering (a document
       the integrity check grouped with the applicant is the applicant's even
       when it drops the "LLC");
     * positive evidence only: a document that prints no insured is never
       judged ("none") - a loss run or narrative without letterhead is
       ordinary supporting paper, and tagging it would make every package
       look mixed;
     * "kept by you" when the producer's "continue anyway" / "they belong to
       this insured" acknowledged that insured.

The same answer decides whether the AI may write a newly added document's
values into the forms (`session_documents.run_new_document_fill`): another
insured's document only ever SUGGESTS. There the applicant is decided
WITHOUT the documents being added (`judge_without`), so two of another
company's documents added to a package holding one of its own cannot outvote
it.

3. Whether the document is a VERIFIED source (21 Oct 2026, Brent: "only
   trigger a hard stop when Primble has enough VERIFIED information to know the
   condition is true; otherwise flag it for confirmation instead of assuming").
   One definition, beside the type label it reads (`is_verified_source`, below),
   asked by the identity hard stop, the Data Consistency picker's blocking
   decision and Submission Integrity's "different insured" verdict - and by the
   applicant election above, where verified documents decide whose package it is.

Pure and deterministic: no LLM, no database, nothing stored.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# What `submission_integrity._verdict` prints for a document naming nobody.
NO_NAME_PLACEHOLDER = "(no applicant name detected)"

STATE_SAME = "same"
STATE_DIFFERENT = "different"
STATE_NONE = "none"


# ── 1. What the document is ──────────────────────────────────────────────────

def _form_sort_key(form_id: str):
    m = re.match(r"ACORD_(\d+)(.*)$", str(form_id or ""))
    return (int(m.group(1)), m.group(2)) if m else (10 ** 6, str(form_id or ""))


def _form_label(form_id: str) -> str:
    try:
        from services.form_instances import instance_label
        return instance_label(form_id)
    except Exception:                                          # noqa: BLE001
        return str(form_id or "").replace("_", " ")


def printed_acord_forms(text: Any) -> List[str]:
    """The ACORD forms (form ids, by number) whose own identity stamp the
    document prints - "ACORD 125 (2025/03)" - read by the recommender's own
    detector. A bare "ACORD 45" cross-reference in a form's body is not a
    stamp and is never counted. [] for no text or no stamp."""
    if not isinstance(text, str) or not text.strip():
        return []
    try:
        from services.form_service import _detect_uploaded_acord_forms
        found = _detect_uploaded_acord_forms(text)
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("document tags: ACORD stamp check skipped: %s", ex)
        return []
    return sorted(found or (), key=_form_sort_key)


def document_type_label(doc: Optional[dict]) -> str:
    """The Documents list's type label: the canonical type's label, naming the
    printed ACORD form(s) when the document carries their stamp -
    "Commercial Insurance Application (ACORD 125)", "Certificate of Insurance
    (ACORD 25)". A document typed as the generic "ACORD Form" is named by its
    form alone ("ACORD 28")."""
    doc = doc if isinstance(doc, dict) else {}
    dt = str(doc.get("doc_type") or "unknown")
    try:
        from services.extraction_service import DOC_TYPE_LABELS
    except Exception:                                          # noqa: BLE001
        DOC_TYPE_LABELS = {}
    base = DOC_TYPE_LABELS.get(dt, dt.replace("_", " ").title())
    forms = printed_acord_forms(doc.get("text"))
    if not forms:
        return base
    names = ", ".join(_form_label(f) for f in forms)
    if dt == "acord_form":
        return names
    return f"{base} ({names})"


# ── 3. Is it a VERIFIED source? (21 Oct 2026) ────────────────────────────────
# Beside the type it reads, and ahead of section 2, which ranks by it.
#
# Brent, 20 Oct 2026: "only trigger a hard stop when Primble has enough VERIFIED
# information to know the condition is true; otherwise flag it for confirmation
# instead of assuming." His 17 Oct test shows the cost of not asking: the
# handwritten narrative - a document the Documents list itself labels "Unable to
# Classify" - raised "documents name different companies", a hard stop (60).
#
# A document is a VERIFIED source of a fact unless POSITIVE evidence says
# otherwise - an older record that never stored a signal is not called
# unverified for what it never recorded:
#   * TYPE - a document that formally names the insured: the paperwork of the
#     placement (declarations, policy, endorsement, binder, quote, application -
#     supplemental too - certificate, ACORD form: the primary-truth types
#     `select_primary_truth` prefers, the head of `extraction_service.
#     _DOC_TYPE_PRIORITY`, pinned by test) and the records a carrier or a rating
#     bureau issues about its insured (a loss run, an experience-mod worksheet).
#     Brent's unverified list never names a loss run, and the Beta Test 1 kit -
#     the package Submission Integrity was built for (a Women's Bar Association
#     dec, a Wake County narrative, a Company ABC loss run) - pauses on exactly
#     the dec against the loss run. What the insured or agent writes or compiles
#     as support (a narrative, a schedule or statement of values, a payroll /
#     sales / financial report, a COPE report, a handbook or safety manual) and
#     an Unknown are not (a type label Primble does not know is no evidence);
#   * TYPE CONFIDENCE - Primble is sure of that type ("Highly Confident"), or
#     the producer set it. "Needs Verification" (medium) and "Unable to
#     Classify" (low) are not - Brent's own labels (17 Oct item 2);
#   * ROLE - the producer did not keep it as a supporting document only;
#   * OCR - not a low-confidence reading: the value's own OCR tokens (its
#     envelope's `ai_low`, `manual_confirmation_required`), or a document the
#     OCR read poorly - flagged for manual review, or at least
#     `OCR_UNVERIFIED_SHARE` of its words low-confidence (an image or a scan:
#     measured 21 Oct over the 378 distinct documents of the 927 stored
#     packages - every PDF at or under 0.2%, every image at 5% or more, the
#     17 Oct handwritten narrative at 31%).
VERIFIED_SOURCE_TYPES: frozenset = frozenset({
    "dec_page", "policy", "endorsement", "binder", "quote",
    "application", "supplemental_application", "certificate", "acord_form",
    "loss_run", "emod_worksheet",
})
# Brent's pill words for an unsure type (frontend utils/addDocuments.js).
_UNSURE_TYPE_LABELS = {"medium": "Needs Verification", "low": "Unable to Classify"}
OCR_UNVERIFIED_SHARE = 0.02
# The sentinel `ocr_service` puts first when its own manual-review rule fires.
_OCR_REVIEW_SENTINEL = "needs_manual_review"

UNVERIFIED_TYPE = "type"
UNVERIFIED_TYPE_CONFIDENCE = "type_confidence"
UNVERIFIED_SUPPORTING = "supporting_only"
UNVERIFIED_OCR = "ocr"


def _known_supporting_type(doc_type: str) -> bool:
    """A document type Primble knows (`extraction_service.DOC_TYPE_LABELS`) that
    is not a verified source. A label it does not know is no evidence either way."""
    if not doc_type or doc_type in VERIFIED_SOURCE_TYPES:
        return False
    try:
        from services.extraction_service import DOC_TYPE_LABELS
    except Exception:                                          # noqa: BLE001
        return False
    return doc_type in DOC_TYPE_LABELS


def _type_confidence(doc: dict) -> str:
    conf = doc.get("doc_type_confidence")
    if not conf:
        cls = doc.get("classification")
        conf = cls.get("confidence") if isinstance(cls, dict) else None
    return str(conf or "").strip().lower()


def _type_set_by_producer(doc: dict) -> bool:
    if doc.get("doc_type_overridden"):
        return True
    if str(doc.get("doc_type_source") or "").strip().lower() == "manual":
        return True
    cls = doc.get("classification")
    return isinstance(cls, dict) and str(cls.get("source") or "").strip().lower() == "manual"


def _read_poorly(doc: dict) -> bool:
    """The document's OCR was unsure of it as a whole (see the note above)."""
    tokens = doc.get("low_confidence_tokens")
    if not isinstance(tokens, (list, tuple)) or not tokens:
        return False
    if _OCR_REVIEW_SENTINEL in tokens:
        return True
    text = doc.get("text")
    if not isinstance(text, str) or not text.strip():
        return False
    shaky = sum(1 for t in tokens if t != _OCR_REVIEW_SENTINEL)
    # A word and its space rarely pass 20 characters: a text that long holds too
    # many words for `shaky` to reach the share, so a long PDF is never counted.
    if len(text) / 20.0 * OCR_UNVERIFIED_SHARE > shaky:
        return False
    words = len(re.findall(r"\w+", text))
    return words > 0 and shaky / words >= OCR_UNVERIFIED_SHARE


def _reading_is_low_ocr(doc: dict, fact_key: str) -> bool:
    facts = doc.get("facts")
    raw = facts.get(fact_key) if isinstance(facts, dict) else None
    if isinstance(raw, dict) and str(raw.get("confidence") or "").strip().lower() == "ai_low":
        return True
    manual = doc.get("manual_confirmation_required")
    return isinstance(manual, (list, tuple)) and fact_key in manual


def unverified_reasons(doc: Any, fact_key: Optional[str] = None) -> List[str]:
    """Why `doc` - its reading of `fact_key`, when given - is NOT a verified
    source: any of UNVERIFIED_TYPE, UNVERIFIED_TYPE_CONFIDENCE,
    UNVERIFIED_SUPPORTING, UNVERIFIED_OCR, in that order. [] when it is one."""
    if not isinstance(doc, dict):
        return []
    reasons: List[str] = []
    doc_type = str(doc.get("doc_type") or "").strip().lower()
    if _known_supporting_type(doc_type):
        reasons.append(UNVERIFIED_TYPE)
    if not _type_set_by_producer(doc) and _type_confidence(doc) in _UNSURE_TYPE_LABELS:
        reasons.append(UNVERIFIED_TYPE_CONFIDENCE)
    if doc.get("supporting_only"):
        reasons.append(UNVERIFIED_SUPPORTING)
    if _read_poorly(doc) or (fact_key and _reading_is_low_ocr(doc, fact_key)):
        reasons.append(UNVERIFIED_OCR)
    return reasons


def is_verified_source(doc: Any, fact_key: Optional[str] = None) -> bool:
    """The ONE definition (see the note above). Never raises."""
    try:
        return not unverified_reasons(doc, fact_key)
    except Exception:                                          # noqa: BLE001
        return True


def describe_unverified(doc: Any, fact_key: Optional[str] = None) -> str:
    """"<file> (<why>)" in the Documents list's own words - "Choice Electric
    Narrative .jpeg (Underwriting Narrative, Unable to Classify, supporting
    document, low OCR confidence)" - or "" for a verified source."""
    try:
        reasons = unverified_reasons(doc, fact_key)
    except Exception:                                          # noqa: BLE001
        return ""
    if not reasons:
        return ""
    words: List[str] = []
    for reason in reasons:
        if reason == UNVERIFIED_TYPE:
            words.append(document_type_label({"doc_type": doc.get("doc_type")}))
        elif reason == UNVERIFIED_TYPE_CONFIDENCE:
            words.append(_UNSURE_TYPE_LABELS[_type_confidence(doc)])
        elif reason == UNVERIFIED_SUPPORTING:
            words.append("supporting document")
        elif reason == UNVERIFIED_OCR:
            words.append("low OCR confidence")
    name = str(doc.get("filename") or "").strip() or "an uploaded document"
    return f"{name} ({', '.join(words)})"


def unverified_note(descriptions: Iterable[str]) -> str:
    """The note an identity warning carries after its sentence -
    " Unverified source: a.jpeg (Underwriting Narrative)." - or "" for none."""
    descs = [d for d in dict.fromkeys(descriptions or ()) if d]
    if not descs:
        return ""
    return f" Unverified source{'s' if len(descs) > 1 else ''}: {'; '.join(descs)}."


def conflict_sources_verified(values: Any, docs: Any,
                              fact_key: Optional[str] = None) -> Tuple[bool, List[str]]:
    """(verified, descriptions) for a Data Consistency field in conflict:
    verified when at least TWO of its rival values are each stated by a verified
    source - a document (`is_verified_source` for `fact_key`) or a person's
    answer (the client questionnaire). Otherwise the descriptions of the
    documents behind the values no verified source states - every document,
    when none does. A value whose sources cannot be judged (none recorded, a
    document no longer in `docs`) counts as verified: absence is not evidence."""
    by_id = {str(d.get("doc_id")): d for d in (docs or ())
             if isinstance(d, dict) and d.get("doc_id") is not None}
    verified_groups = 0
    unverified_docs: List[dict] = []
    for group in values or ():
        if not isinstance(group, dict):
            continue
        sources = [s for s in (group.get("sources") or []) if isinstance(s, dict)]
        group_docs: List[dict] = []
        verified = not sources
        for src in sources:
            if src.get("source_method") == "client_answer" \
                    or str(src.get("doc_id")) == "client_questionnaire":
                verified = True                      # a person's answer
                continue
            doc = by_id.get(str(src.get("doc_id")))
            if doc is None or is_verified_source(doc, fact_key):
                verified = True
            else:
                group_docs.append(doc)
        if verified:
            verified_groups += 1
        else:
            unverified_docs.extend(group_docs)
    if verified_groups >= 2:
        return True, []
    descs = [describe_unverified(d, fact_key) for d in unverified_docs]
    return False, [d for d in dict.fromkeys(descs) if d]


# ── 2. Whose document it is ──────────────────────────────────────────────────

def _same(a: Any, b: Any) -> bool:
    sa, sb = str(a or "").strip(), str(b or "").strip()
    if not sa or not sb:
        return False
    try:
        from services.normalization import same_entity_name
        return bool(same_entity_name(sa, sb))
    except Exception:                                          # noqa: BLE001
        return False


def _as_list(value: Any) -> list:
    """A stored list, or [] - a string or a mapping is never iterated as one
    (a malformed record must not read "MERIDIAN" as eight one-letter names)."""
    return list(value) if isinstance(value, (list, tuple)) else []


def _ids(values: Any) -> List[str]:
    return [str(v).strip() for v in _as_list(values) if str(v or "").strip()]


def _entries(integrity: Any) -> List[dict]:
    """The documents the integrity record assessed - each with its own id (a
    row without one cannot be matched to a document and is skipped)."""
    integrity = integrity if isinstance(integrity, dict) else {}
    return [e for e in _as_list(integrity.get("documents"))
            if isinstance(e, dict) and str(e.get("doc_id") or "").strip()]


def printed_insured(entry: Optional[dict]) -> str:
    """The insured an integrity `documents[]` entry says the document names -
    "" for none (the verdict's placeholder, a heading or a role)."""
    name = str((entry if isinstance(entry, dict) else {}).get("applicant") or "").strip()
    if not name or name.casefold() == NO_NAME_PLACEHOLDER or (name.startswith("(") and name.endswith(")")):
        return ""
    try:
        from services.normalization import is_not_a_party_name
        if is_not_a_party_name(name):
            return ""
    except Exception:                                          # noqa: BLE001
        pass
    return name


def confirmed_applicant(confirmations: Optional[dict] = None,
                        consistency: Optional[dict] = None) -> str:
    """The applicant a person confirmed in Data Consistency, or "". Read
    through `usable_confirmations`, the one door for stored confirmations;
    the assessed card's confirmed value when the map is not to hand."""
    conf: dict = {}
    if isinstance(confirmations, dict) and confirmations:
        try:
            from services.underwriting_consistency import usable_confirmations
            conf = usable_confirmations(confirmations) or {}
        except Exception:                                      # noqa: BLE001
            conf = dict(confirmations)
    value = conf.get("applicant_name") if isinstance(conf, dict) else None
    if isinstance(value, dict):
        value = value.get("value")
    value = str(value or "").strip() if isinstance(value, (str, int, float)) else ""
    if value:
        return value
    fields = (consistency or {}).get("fields") if isinstance(consistency, dict) else None
    for field in _as_list(fields):
        if isinstance(field, dict) and field.get("fact_key") == "applicant_name" \
                and field.get("status") == "confirmed":
            value = field.get("confirmed_value")
            value = str(value or "").strip() if isinstance(value, (str, int, float)) else ""
            if value:
                return value
    return ""


def _groups(integrity: dict, named: Dict[str, str], order: List[str]) -> List[List[str]]:
    """The integrity check's insured groups that name somebody: its clusters
    (document ids, every member - a document grouped by FEIN is the group's
    too), then any named document no cluster holds (a one-document package
    has no clusters)."""
    groups: List[List[str]] = []
    placed: set = set()
    for cluster in _as_list(integrity.get("clusters")):
        if not isinstance(cluster, dict):
            continue
        ids = [i for i in _ids(cluster.get("doc_ids")) if i not in placed]
        if any(i in named for i in ids):
            groups.append(ids)
            placed.update(ids)
    for did in order:
        if did in named and did not in placed:
            groups.append([did])
            placed.add(did)
    return groups


def package_applicant(integrity: Optional[dict], confirmations: Optional[dict] = None,
                      consistency: Optional[dict] = None, *,
                      judge_without: Iterable[str] = ()) -> Optional[dict]:
    """{"name", "doc_ids", "source": "confirmed" | "documents"} - the package's
    applicant as the Documents list judges it (see the module note) - or None
    when no document names an insured.

    `judge_without` (document ids): the applicant is decided as if those
    documents were not in the package yet - how the AI reading of a newly
    added document asks "is this the applicant's?" (two documents of another
    company added to a package with ONE document of its own must not outvote
    it). Their own group still counts as the applicant's when it is one."""
    integrity = integrity if isinstance(integrity, dict) else {}
    entries = _entries(integrity)
    order = [str(e.get("doc_id")).strip() for e in entries]
    named = {str(e.get("doc_id")).strip(): printed_insured(e) for e in entries}
    named = {k: v for k, v in named.items() if v}
    if not named:
        return None
    groups = _groups(integrity, named, order)
    confirmed = confirmed_applicant(confirmations, consistency)
    if confirmed:
        hits = [g for g in groups if any(_same(named.get(i), confirmed) for i in g)]
        if hits:
            return {"name": confirmed, "doc_ids": [i for g in hits for i in g], "source": "confirmed"}
    without = {str(i).strip() for i in (judge_without or ()) if str(i or "").strip()}
    position = {did: n for n, did in enumerate(order)}
    # Whether each document is a verified source of the insured's identity
    # (section 3; Submission Integrity records it). A record written before
    # 21 Oct 2026 carries no mark: every document then counts, as before.
    verified = {str(e.get("doc_id")).strip(): e.get("identity_verified") is not False
                for e in entries}
    # A group speaks for the package only through its documents that are not
    # being judged: its VERIFIED ones rank it first (21 Oct 2026), then all of
    # them, and the earliest breaks a tie.
    voters = [(g, [i for i in g if i not in without]) for g in groups]
    voters = [(g, v) for g, v in voters if any(i in named for i in v)]
    if not voters:
        return None

    def _rank(pair):
        _g, v = pair
        return (-sum(1 for i in v if verified.get(i, True)), -len(v),
                min(position.get(i, 10 ** 6) for i in v))

    best, best_voters = sorted(voters, key=_rank)[0]
    # The name a verified document prints, when the group has one.
    in_order = sorted((i for i in best_voters if i in named), key=lambda i: position.get(i, 10 ** 6))
    name = named[next((i for i in in_order if verified.get(i, True)), in_order[0])]
    return {"name": name, "doc_ids": list(best), "source": "documents"}


def document_insured_statuses(integrity: Optional[dict], confirmations: Optional[dict] = None,
                              consistency: Optional[dict] = None, *,
                              judge_without: Iterable[str] = ()) -> Dict[str, dict]:
    """{doc_id: status} for every document the integrity record assessed:
      {"state": "none"}       - it prints no insured (never judged), or no
                                applicant can be told;
      {"state": "same"}       - it names the package's applicant;
      {"state": "different", "name": <its insured>, "kept_by_you": bool}
    {} when there is no integrity record. `judge_without`: see
    `package_applicant`."""
    integrity = integrity if isinstance(integrity, dict) else {}
    entries = _entries(integrity)
    if not entries:
        return {}
    applicant = package_applicant(integrity, confirmations, consistency, judge_without=judge_without)
    named = {str(e.get("doc_id")).strip(): printed_insured(e) for e in entries}
    label_of: Dict[str, str] = {}
    for cluster in _as_list(integrity.get("clusters")):
        if isinstance(cluster, dict):
            for i in _ids(cluster.get("doc_ids")):
                label_of.setdefault(i, str(cluster.get("label") or ""))
    override = integrity.get("override") if integrity.get("overridden") else None
    acknowledged = [str(a).strip() for a in _as_list((override if isinstance(override, dict) else {})
                                                     .get("acknowledged_entities"))
                    if isinstance(a, str) and a.strip()]
    applicant_ids = set((applicant or {}).get("doc_ids") or [])
    applicant_names = [(applicant or {}).get("name")] + [named.get(i) for i in applicant_ids]
    out: Dict[str, dict] = {}
    for entry in entries:
        did = str(entry.get("doc_id")).strip()
        name = named.get(did) or ""
        if not name or applicant is None:
            out[did] = {"state": STATE_NONE}
        elif did in applicant_ids or any(_same(name, n) for n in applicant_names if n):
            out[did] = {"state": STATE_SAME}
        else:
            kept = any(_same(name, a) or _same(label_of.get(did), a) for a in acknowledged)
            out[did] = {"state": STATE_DIFFERENT, "name": name, "kept_by_you": bool(kept)}
    return out


def session_insured_statuses(session: Optional[dict], *,
                             judge_without: Iterable[str] = ()) -> Dict[str, dict]:
    """`document_insured_statuses` for a stored session row."""
    session = session if isinstance(session, dict) else {}
    return document_insured_statuses(session.get("integrity"),
                                     session.get("underwriting_confirmations"),
                                     session.get("underwriting_consistency"),
                                     judge_without=judge_without)


def different_insured_ids(statuses: Dict[str, dict], doc_ids: Iterable[str]) -> List[str]:
    """The ids among `doc_ids` whose document names a different insured."""
    out: List[str] = []
    for did in doc_ids or ():
        did = str(did or "").strip()
        st = (statuses or {}).get(did) if isinstance(statuses, dict) else None
        if isinstance(st, dict) and st.get("state") == STATE_DIFFERENT and st.get("name") and did not in out:
            out.append(did)
    return out


def other_insured_of(statuses: Dict[str, dict], doc_ids: Iterable[str]) -> Optional[str]:
    """The different insured(s) `doc_ids` name - their names, joined when
    several - or None when every one of them is the applicant's or names
    nobody."""
    names: List[str] = []
    for did in different_insured_ids(statuses, doc_ids):
        name = str(statuses[did]["name"])
        if not any(_same(name, n) for n in names):
            names.append(name)
    return ", ".join(names) or None
