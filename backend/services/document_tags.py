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
       the most documents (a tie goes to the cluster holding the earliest
       document - the package's own upload order);
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

Pure and deterministic: no LLM, no database, nothing stored.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Optional

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
    # A group speaks for the package only through its documents that are not
    # being judged: their count ranks it, the earliest of them breaks a tie.
    voters = [(g, [i for i in g if i not in without]) for g in groups]
    voters = [(g, v) for g, v in voters if any(i in named for i in v)]
    if not voters:
        return None

    def _rank(pair):
        _g, v = pair
        return (-len(v), min(position.get(i, 10 ** 6) for i in v))

    best, best_voters = sorted(voters, key=_rank)[0]
    name = next(named[i] for i in sorted(best_voters, key=lambda i: position.get(i, 10 ** 6))
                if i in named)
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
