"""premises_interest.py - the ONE premises' insured interest, and the landlord
behind a tenant (Orbin client feedback of 22 Sep 2026, item 12 and G2).

THE CLIENT: *"The dec notes a tenant policy, not owner; as tenant, revenue should
be $0 by default."* And G2: *"If there is a landlord, the client must give the
landlord's full name and address for certificates."*

THE OWNER'S RULING (29 Sep 2026), which is what this module implements:

  * TENANT IS NEVER SILENTLY INFERRED. Nothing here writes an interest into the
    facts or ticks a box on its own. The evidence (a unit number on the address,
    no building insured) becomes a one-click CONFIRM card for the producer, and
    the card shows its evidence. A suggestion needs BOTH tenant signals and no
    owner signal (a building value, a mortgagee); one signal shows the evidence
    without pre-selecting anything.
  * LOCATION REVENUE IS NEVER $0 BY DEFAULT. With exactly one location whose own
    revenue is blank, ACORD 125's ANNUAL REVENUES box is that location's revenue
    - the business's `total_revenue` (ACORD's box instruction: "The annual
    revenue amount for this location"). That copy lives in `pdf_service`
    (`premises_twin_fact`); this module only answers the interest questions.
  * A TENANT IS ASKED FOR THE LANDLORD'S FULL NAME AND ADDRESS. Recorded for
    certificates, printed nowhere yet (the ACORD 125 additional-interest row and
    the ACORD 25 holder are Brent's call).

Two locations or more: no copy, no card, no landlord ask - each row keeps its own
document value, exactly as before.

Pure: no I/O and no module-level import of the heavy services. Every reader
here fails closed to "unknown", which the callers read as "change nothing".
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

PREMISES_INTEREST_FACT = "premises_interest"
LANDLORD_NAME_FACT = "landlord_name"
LANDLORD_ADDRESS_FACT = "landlord_address"

OWNER, TENANT, OTHER = "owner", "tenant", "other"

# The three interest columns of a `property_locations` row, as the location
# consolidation writes them and `_SCHEDULE_REGISTRY` binds them.
ROW_INTEREST_KEYS = ("is_owner", "is_tenant", "is_other_interest")
_KIND_OF_ROW_KEY = {"is_owner": OWNER, "is_tenant": TENANT, "is_other_interest": OTHER}

# ACORD 125's row-A interest boxes (the form prints the row letter per premises).
FORM_INTEREST_BOXES = (
    "CommercialStructure_InsuredInterest_OwnerIndicator_A",
    "CommercialStructure_InsuredInterest_TenantIndicator_A",
    "CommercialStructure_InsuredInterest_OtherIndicator_A",
)


# ── A document's ownership WORDING (moved from the location consolidation) ────
# Behaviour byte-identical to the block `_consolidate_property_locations` held
# until 29 Sep 2026 - it now calls this, and so does the answer reader below, so
# a document and a person are read by ONE rule.
_INTEREST_WORDS = ("own", "rent", "occup", "tenant", "lease", "licens")


def interest_from_wording(text: Any) -> Optional[Tuple[str, Optional[str]]]:
    """(kind, Other description) a piece of ownership wording determines, or None.

    A sentence naming SEVERAL interests is not a determination of one. Live
    25-page run: the dec says "This location is owned, rented or occupied by the
    named insured" - deliberately non-committal - and that whole phrase was
    written into the ACORD "Other" interest box with the sentence as its
    description. Owner, tenant and other are mutually exclusive; a phrase that
    lists two of them tells us the document did not say which, so the interest
    stays unknown and the question goes to a person.
    The tell is the document offering ALTERNATIVES ("owned, rented OR
    occupied"), not the length of the phrase: "Tenant (leased office space)" and
    "Licensee under a shared-use agreement" are single, determinate answers and
    must still resolve.

    Returns ("owner", None), ("tenant", None), ("other", <the wording>) or None.
    """
    ownership = str(text or "").strip()
    ownership_l = ownership.lower()
    _interest_words = len({w for w in _INTEREST_WORDS if w in ownership_l})
    if _interest_words > 1 and re.search(r"\bor\b", ownership_l):
        logger.info(
            "consolidate_locations: ambiguous ownership %r - left unknown",
            ownership[:60],
        )
        return None
    if ownership_l.startswith("owner"):
        return OWNER, None
    if ownership_l.startswith("tenant"):
        return TENANT, None
    if ownership_l:
        # A real signal that is neither "owner" nor "tenant" - a genuine "Other"
        # interest (e.g. licensee, easement holder).
        return OTHER, ownership
    return None


# ── A PERSON's answer ─────────────────────────────────────────────────────────

def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def _option_kinds() -> Dict[str, str]:
    """{normalised option label: kind} from the ONE option list
    (`answer_options.PREMISES_INTEREST_OPTIONS`), read by its leading word."""
    try:
        from services.answer_options import OTHER as _OTHER_LABEL, PREMISES_INTEREST_OPTIONS
    except Exception:                                         # noqa: BLE001
        return {}
    out: Dict[str, str] = {}
    for label in PREMISES_INTEREST_OPTIONS:
        if label == _OTHER_LABEL:
            out[_norm(label)] = OTHER
            continue
        head = _norm(str(label).split(" ", 1)[0])
        if head in (OWNER, TENANT):
            out[_norm(label)] = head
    return out


def _unwrap(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def kind_of_answer(value: Any) -> Optional[Tuple[str, Optional[str]]]:
    """(kind, Other description) a stored `premises_interest` answer names, or None.

    Exact option label first - the option TEXT is the stored value - then the
    document wording rule above, so a typed "Tenant" or "Licensee under a
    shared-use agreement" reads exactly as it would on a declarations page. A bare
    Yes / No names no interest, and an ambiguous phrase is unknown.
    """
    text = str(_unwrap(value) or "").strip()
    if not text:
        return None
    kinds = _option_kinds()
    kind = kinds.get(_norm(text))
    if kind is not None:
        return kind, None
    m = re.match(r"^other\s*(?::|\s-\s)\s*(.+)$", text, re.I | re.S)
    if m and m.group(1).strip():
        return OTHER, m.group(1).strip()          # "Other: licensee" - chosen, then typed
    try:
        from services.normalization import canonical_yes_no
        if canonical_yes_no(text) is not None:
            return None                           # "Yes" answers "own or rent?" with nothing
    except Exception:                                         # noqa: BLE001
        pass
    return interest_from_wording(text)


# ── The ONE premises ──────────────────────────────────────────────────────────

def _fact_value(facts: Any, key: str) -> Any:
    return _unwrap((facts or {}).get(key)) if isinstance(facts, dict) else None


def one_premises_row(facts: Any) -> Optional[dict]:
    """The single `property_locations` row, or None when there are 0 or 2+.

    The same list, read the same way, as the schedule resolver that stamps the
    premises grid (`pdf_service._resolve_schedule_row`)."""
    rows = _fact_value(facts, "property_locations")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        return None
    return rows[0]


def _ticked(value: Any) -> bool:
    if value is True:
        return True
    if value in (None, False, ""):
        return False
    try:
        from services.normalization import canonical_yes_no
        return canonical_yes_no(value) == "Yes"
    except Exception:                                         # noqa: BLE001
        return str(value).strip().lower() in ("yes", "y", "true", "x", "1")


def row_interest_blank(row: Any) -> bool:
    """The row states NO interest of its own - none of its three columns is
    ticked (the consolidation writes None for all three when the document does
    not say)."""
    return isinstance(row, dict) and row_interest(row) is None


def row_interest(row: Any) -> Optional[Tuple[str, Optional[str]]]:
    """(kind, Other description) the row's own columns state, or None."""
    if not isinstance(row, dict):
        return None
    for key in ROW_INTEREST_KEYS:
        if _ticked(row.get(key)):
            kind = _KIND_OF_ROW_KEY[key]
            desc = str(row.get("other_interest_description") or "").strip() or None
            return kind, (desc if kind == OTHER else None)
    return None


def single_premises_interest(facts: Any) -> Optional[str]:
    """"owner" / "tenant" / "other" for the ONE premises, or None.

    The row's own columns first - a document that states the interest is never
    second-guessed - then the `premises_interest` answer a person gave. Two or
    more locations: None, whatever either says."""
    row = one_premises_row(facts)
    if row is None:
        return None
    got = row_interest(row) or kind_of_answer((facts or {}).get(PREMISES_INTEREST_FACT))
    return got[0] if got else None


def fact_is_answered(facts: Any, key: str) -> bool:
    """Did a person or a document answer `key`? An explicit "none" / "N/A"
    counts (Brent 2026-08-24) - the same test the questionnaire uses."""
    raw = (facts or {}).get(key) if isinstance(facts, dict) else None
    try:
        from services.answer_semantics import fact_answered
        return fact_answered(raw)
    except Exception:                                         # noqa: BLE001
        v = _unwrap(raw)
        return v is not None and str(v).strip().lower() not in ("", "none", "null")


def form_shows_interest(field_state: Any) -> bool:
    """The generated ACORD 125 already shows a ticked interest box on row A."""
    if not isinstance(field_state, dict):
        return False
    return any(_ticked(field_state.get(box)) for box in FORM_INTEREST_BOXES)


# ── The evidence, for the producer's card ────────────────────────────────────

def _amount(value: Any) -> Optional[int]:
    """Whole dollars in a printed amount, or None when it states no number."""
    digits = re.sub(r"[^\d]", "", str(value or "").split(".")[0])
    return int(digits) if digits else None


def _names_something(value: Any) -> bool:
    s = str(_unwrap(value) or "").strip().lower()
    return bool(s) and s not in ("none", "n/a", "na", "no", "null", "-", "not applicable")


def _street_part(line1: str) -> str:
    """The street line only - never a city / state / ZIP tail, where "FL 33101"
    would read as a FLoor number."""
    street = str(line1 or "").split(",")[0]
    return re.sub(r"\s+[A-Z]{2}\s+\d{5}(?:-\d{4})?\s*$", "", street).strip()


# A unit is a designator followed by a SHORT identifier - a number, a number
# with a letter, or one letter ("# D13", "Suite 210", "Unit B", "Fl 2"). Stricter
# than `extraction_service._HAS_UNIT_RE` on purpose (review, 29 Sep): that one
# also reads street NAMES - "500 Ste Genevieve Ave", "8 Apt Ln", "55 Unit Dr" -
# and here a false unit pre-selects Tenant.
_UNIT_RE = re.compile(
    r"(?:\b(?:suite|ste|unit|apt|apartment|room|rm|floor|fl)\b\.?\s*#?\s*"
    r"|#\s*)(?:[A-Z]{0,2}\d+[A-Z]?|[A-Z])\b", re.I)


def _unit_designator(row: dict) -> Optional[str]:
    """The unit the ONE premises' address prints ("# D13", "Suite 210"), or None."""
    line2 = str(row.get("address_line2") or "").strip()
    if line2 and _UNIT_RE.search(line2):
        return line2
    street = _street_part(row.get("address_line1") or "")
    m = _UNIT_RE.search(street) if street else None
    if m:
        return street[m.start():].strip() or None
    return None


def _building_value_state(row: dict, facts: Any) -> str:
    """"insured" (a positive amount), "none" (nothing, or $0) or "unclear"."""
    seen_text = False
    for v in (row.get("building_value"), _fact_value(facts, "property_building_value")):
        if v in (None, "") or isinstance(v, (list, dict)):
            continue
        n = _amount(v)
        if n is None:
            if _names_something(v):
                seen_text = True              # "Included" - neither answer
            continue
        if n > 0:
            return "insured"
    return "unclear" if seen_text else "none"


def tenant_evidence(facts: Any, flags: Any = None) -> Dict[str, List[str]]:
    """{"tenant": [reasons], "owner": [reasons]} for the ONE premises.

    Tenant signals: the address prints a unit designator; the package carries
    no property line (positive evidence of absence, `lob_canon.line_is_carried`
    is False) and insures no building. Owner signals: a building value is
    insured (on the row or `property_building_value`), a mortgagee is named.
    Both lists are empty when there is not exactly one location."""
    out: Dict[str, List[str]] = {"tenant": [], "owner": []}
    row = one_premises_row(facts)
    if row is None:
        return out
    unit = _unit_designator(row)
    if unit:
        out["tenant"].append(f"unit number on the address ({unit})")
    building = _building_value_state(row, facts)
    if building == "insured":
        out["owner"].append("a building value is insured")
    if _names_something(_fact_value(facts, "mortgagee_name")):
        out["owner"].append("a mortgagee is named")
    if building == "none":
        try:
            from services.lob_canon import line_is_carried
            if line_is_carried("property", facts, flags) is False:
                out["tenant"].append("no building insured (no property coverage)")
        except Exception:                                     # noqa: BLE001
            pass
    return out


def suggested_kind(evidence: Dict[str, List[str]]) -> Optional[str]:
    """TENANT only when BOTH tenant signals agree and no owner signal exists."""
    if evidence.get("owner"):
        return None
    return TENANT if len(evidence.get("tenant") or []) >= 2 else None


def option_for_kind(kind: str) -> Optional[str]:
    """The option label a kind is offered as, or None."""
    try:
        from services.answer_options import PREMISES_INTEREST_OPTIONS
    except Exception:                                         # noqa: BLE001
        return None
    for label in PREMISES_INTEREST_OPTIONS:
        if _norm(str(label).split(" ", 1)[0]) == kind:
            return label
    return None


def premises_address(row: Any) -> str:
    """The premises as one line, from its parsed parts where it has them."""
    if not isinstance(row, dict):
        return ""
    street = " ".join(str(row.get(k) or "").strip()
                      for k in ("address_line1", "address_line2") if str(row.get(k) or "").strip())
    city = str(row.get("address_city") or "").strip()
    tail = " ".join(p for p in (str(row.get("address_state") or "").strip(),
                                str(row.get("address_zip") or "").strip()) if p)
    parts = [p for p in (street, city, tail) if p]
    if street and len(parts) > 1:
        return ", ".join(parts)
    return str(row.get("address") or street).strip()


# ── The producer's cards (ACORD 125's per-form SQS) ──────────────────────────

def premises_recommendations(facts: Any, flags: Any = None,
                             mapped_data: Any = None) -> List[dict]:
    """The unscored asks for the ONE premises: its interest, then - for a tenant
    - the landlord's full name and address.

    Every card is worth zero points and says so (`unscored`), so no score moves.
    The interest card is suppressed when the form already shows a ticked
    interest box, when the interest is known, or when there are 2+ locations.
    `suggested_answer` pre-selects an option and `suggestion_evidence` says why;
    both are generic rec keys the card reads, never a value written anywhere."""
    row = one_premises_row(facts)
    if row is None:
        return []
    recs: List[dict] = []
    kind = single_premises_interest(facts)
    address = premises_address(row) or "this location"
    if (kind is None and not fact_is_answered(facts, PREMISES_INTEREST_FACT)
            and not form_shows_interest(mapped_data)):
        rec = {
            "rec_id": "rec_premises_interest",
            "field": PREMISES_INTEREST_FACT,
            "component": "structural_completeness",
            "message": f"ACORD 125 premises: does the insured own or rent {address}?",
            "type": "missing_field",
            "score_impact": 0,
            "priority": 3,
            "unscored": True,
        }
        evidence = tenant_evidence(facts, flags)
        if evidence["tenant"] and not evidence["owner"]:
            rec["suggestion_evidence"] = (
                "Evidence for tenant: " + "; ".join(evidence["tenant"]) + ".")
            suggested = suggested_kind(evidence)
            label = option_for_kind(suggested) if suggested else None
            if label:
                rec["suggested_answer"] = label
        recs.append(rec)
    if kind == TENANT:
        for fact, what in ((LANDLORD_NAME_FACT, "full name"),
                           (LANDLORD_ADDRESS_FACT, "full mailing address")):
            if fact_is_answered(facts, fact):
                continue
            recs.append({
                "rec_id": f"rec_{fact}",
                "field": fact,
                "component": "structural_completeness",
                "message": (f"ACORD 125 premises: the insured rents {address}. "
                            f"What is the landlord's {what}? Kept for certificates."),
                "type": "missing_field",
                "score_impact": 0,
                "priority": 3,
                "unscored": True,
            })
    return recs
