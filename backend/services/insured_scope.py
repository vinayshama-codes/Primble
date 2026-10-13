"""insured_scope.py - ONE door for: whose company does this value describe?

THE DEFECT THIS CLOSES (8 Oct 2026, the owner's Choice Electric run `b4d18e8e`).
A Harborline Plumbing & Mechanical declarations package was added to a Choice
Electric submission. Submission Integrity warned at the upload ("These
documents name a different insured"), the producer answered "they belong to
this insured", and the merge then took Harborline's identity wholesale:

    dba_name          HARBORLINE MECHANICAL
    mailing_address   P.O. BOX 11820, TACOMA, WA 98411
    physical_address  2210 Port of Tacoma Rd Ste 4B
    fein              91-4478123
    contact_*         Dale Okafor, (253) 555-0187, dokafor@harborline-mech...
    total_revenue     $6,650,000
    naics_code        238220  (plumbing / HVAC - Choice Electric is electrical)
    occupancy_type, year_built, operations_description ...

The package SQS went 38 -> 60 (raw 38 -> 80) on another company's data, and
ACORD 186 printed a Washington contractor licence and Harborline's own policy
number under the name "Choice Electric LLC".

The guards that existed did their job and were not enough: the upload WARNED
and the integrity check CAPPED the score at 60. A cap is not a scope. Nothing
stopped the second company's identity becoming the applicant's.

WHY THE RULE IS SHAPED LIKE THIS
--------------------------------
A document carries its own `facts["applicant_name"]` - what THAT paper says it
insures. The package carries the merged `applicant_name`. So "is this document
about the applicant?" is already answerable from evidence we hold; nothing new
is read and no text is interpreted here.

Four properties, each deliberate:

* **Positive evidence only.** A document that names no insured is never judged
  and contributes exactly as it did before. Absence is not a verdict.
* **Zero blast radius on the ordinary package.** When no document names a
  DIFFERENT insured - every normal submission - this module returns nothing and
  changes nothing. It can only act on a package that already tripped Submission
  Integrity.
* **A value is dropped only when EVERY document stating it belongs to another
  insured.** One applicant document stating the same fact keeps it. So a shared
  value (the same broker, the same term) survives, and only what is uniquely
  the other company's is removed.
* **A person's answer is never touched.** Producer / client provenance is a
  decision, not a document read; the F7 hold and the picker own those.

`applicant_name` itself is deliberately NOT in the scoped set: the merge and
the Data Consistency picker already own that conflict, and blanking it would
remove the very evidence this module reasons from.

NO LLM. Deterministic, and cheap: one entity comparison per document.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── The facts that describe the INSURED ITSELF ───────────────────────────────
# Identity, where it is, how to reach it, how big it is, what it does. These
# are the facts that are wrong - not merely unsupported - when they come off
# another company's paper.
#
# Coverage facts (limits, deductibles, premiums, schedules) are deliberately
# NOT here. They are already line- and policy-scoped by `coverage_lines` /
# `lob_canon` / the per-line records, and a second scoping rule over them would
# be a second owner of a question those doors already answer.
APPLICANT_SCOPED_FACTS: Tuple[str, ...] = (
    # Identity
    "dba_name", "fein", "entity_type", "business_start_date", "years_in_business",
    # Where it is
    "mailing_address", "physical_address",
    # Who to reach
    "contact_name", "contact_phone", "contact_email",
    "contact_secondary_phone", "contact_title",
    # What it does and how big it is
    "operations_description", "naics_code", "sic_code",
    "total_revenue", "total_payroll", "num_employees",
    "num_employees_full_time", "num_employees_part_time",
    "annual_gross_sales", "foreign_sales",
    # The premises it occupies
    "occupancy_type", "year_built", "construction_type",
    "building_area", "num_stories", "num_buildings",
)

# Provenance that means A PERSON decided this, not a document stated it.
_HUMAN_SOURCES = frozenset({
    "producer", "client", "client_arq", "user", "user_confirmed", "manual",
})

_EMPTY = frozenset({"", "null", "none", "n/a", "na", "unknown"})


def _value(raw: Any) -> Any:
    """The value inside a fact envelope, or the bare value."""
    if isinstance(raw, dict) and "value" in raw:
        return raw.get("value")
    return raw


def _is_blank(raw: Any) -> bool:
    val = _value(raw)
    if val is None:
        return True
    if isinstance(val, (list, dict, tuple, set)):
        return not val
    return str(val).strip().lower() in _EMPTY


def _is_human(raw: Any) -> bool:
    """A producer's or client's answer - never scoped away by this module."""
    if not isinstance(raw, dict):
        return False
    if str(raw.get("source") or "").strip().lower() in _HUMAN_SOURCES:
        return True
    return str(raw.get("confidence") or "").strip().lower() in _HUMAN_SOURCES


def _same_entity(a: Any, b: Any) -> Optional[bool]:
    """True / False / None (cannot say) for "are these the same company?".

    One door: `normalization.same_entity_name`, which already folds a glued
    OCR name ("CHOICEELECTRICLLC") and canonicalises the legal form. No second
    opinion is formed here.
    """
    sa, sb = str(a or "").strip(), str(b or "").strip()
    if not sa or not sb:
        return None
    try:
        from services.normalization import same_entity_name
    except Exception:                                          # noqa: BLE001
        return None                                # no door, no opinion
    try:
        return bool(same_entity_name(sa, sb))
    except Exception:                                          # noqa: BLE001
        return None


def other_insured_documents(facts: Optional[dict],
                            docs: Optional[Iterable[dict]]) -> List[dict]:
    """The documents whose OWN named insured is decisively a different company
    from the package applicant.

    Empty whenever we cannot say - no applicant, no documents, a document that
    names no insured, or an entity comparison that cannot decide.
    """
    try:
        from services.normalization import is_not_a_party_name as _not_a_name
    except Exception:                                         # noqa: BLE001
        _not_a_name = lambda _v: False                        # noqa: E731
    applicant = _value((facts or {}).get("applicant_name"))
    # A heading or a role names nobody (8 Oct 2026: "S.B. MO." won the merge
    # as the applicant on b38a4367). Compared against a non-name, the one
    # document that DID name Choice Electric would have read as another
    # company's - so neither side may be a non-name.
    if not str(applicant or "").strip() or _not_a_name(str(applicant)):
        return []
    out: List[dict] = []
    for doc in (docs or ()):
        if not isinstance(doc, dict) or doc.get("excluded"):
            continue
        own = _value((doc.get("facts") or {}).get("applicant_name"))
        if own is not None and _not_a_name(str(own)):
            continue
        if _same_entity(own, applicant) is False:
            out.append(doc)
    return out


def _documents_stating(key: str, docs: Iterable[dict]) -> List[dict]:
    """Every document whose own facts state a non-blank value for `key`."""
    return [d for d in docs
            if isinstance(d, dict) and not d.get("excluded")
            and not _is_blank((d.get("facts") or {}).get(key))]


def facts_only_another_insured_states(
    facts: Optional[dict],
    docs: Optional[Iterable[dict]],
) -> Dict[str, str]:
    """{fact_key: the other insured's name} for every applicant-scoped fact
    whose ONLY documentary support is a document naming a different company.

    Read-only. Returns {} on any package where no document names a different
    insured, which is every ordinary submission.
    """
    others = other_insured_documents(facts, docs)
    if not others or not isinstance(facts, dict):
        return {}
    other_ids = {id(d) for d in others}
    all_docs = [d for d in (docs or ()) if isinstance(d, dict) and not d.get("excluded")]

    out: Dict[str, str] = {}
    for key in APPLICANT_SCOPED_FACTS:
        raw = facts.get(key)
        if _is_blank(raw) or _is_human(raw):
            continue
        stating = _documents_stating(key, all_docs)
        if not stating:
            continue                      # nothing documentary to attribute
        if any(id(d) not in other_ids for d in stating):
            continue                      # an applicant document states it too
        owner = _value((stating[0].get("facts") or {}).get("applicant_name"))
        out[key] = str(owner or "another insured")
    return out


def drop_other_insured_identity(facts: Optional[dict],
                                docs: Optional[Iterable[dict]]) -> List[str]:
    """Remove the applicant-scoped facts that only another insured's documents
    state. Mutates `facts`; returns the keys removed, for the caller to log.

    The removal is a DELETE, not a blank envelope: a `None` left behind would
    read as "answered, with nothing", and these facts were never the
    applicant's to answer. Never raises - a failure here must not take a merge
    down with it.
    """
    try:
        offending = facts_only_another_insured_states(facts, docs)
        if not offending:
            return []
        for key in offending:
            facts.pop(key, None)
        logger.info(
            "insured_scope: %d applicant fact(s) dropped - only another "
            "insured's documents state them: %s",
            len(offending),
            ", ".join(f"{k} (from {v})" for k, v in sorted(offending.items())),
        )
        return sorted(offending)
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("insured_scope: scoping skipped: %s", exc)
        return []
