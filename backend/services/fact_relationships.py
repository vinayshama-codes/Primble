"""Does each extracted value still belong to the entity it was read from?

THE MISSING METRIC, one layer up from `score_gap_fill.py`. That harness exists
because "nothing in the repo measured whether the right value landed in the
right box". Nothing measures whether the right value landed on the right
ENTITY, which is the defect one step earlier and the one that cannot be seen on
the form at all: a website stamped in the right-looking box, spelled correctly,
belonging to a different company, is indistinguishable from a correct fill.

Measured on a live ACORD 125 (A125 kit, test 2, 21 Sep 2026) BEFORE the v22
facts existed:
  * `applicant_website` held the SECOND named insured's website, and the form
    printed it on the FIRST insured's row.
  * the SECOND contact's phone was stamped in the FIRST contact's SECONDARY box.
Both values were real, correctly shaped, and literally present in the document.
Every guard in the pipeline passed them.

WHY THIS NEEDS NO ANSWER KEY
----------------------------
It checks the facts against EACH OTHER, not against a truth file - so it runs on
a real client package where no key exists, which is the only place it matters.
An answer-key grader (`scripts/score_a125_extraction.py`) is the complementary
instrument and only works on the kit.

CONTRACT: pure, stdlib-only, read-only. It never mutates facts and never
decides anything. It reports. A caller may log it, surface it for review, or
fail a test on it.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

# ── severity ────────────────────────────────────────────────────────────────
# ERROR   a relationship the documents cannot support - two entities sharing a
#         legally unique identifier, a detail row for a party nobody names.
# WARN    a strong mis-attribution signal that has a legitimate explanation
#         often enough that it must not block anything (affiliates share a
#         switchboard; a holding company uses the operating company's domain).
ERROR, WARN, INFO = "error", "warn", "info"

_DISCLOSURE_TOPICS = frozenset({
    "subsidiary_of_another", "has_subsidiaries", "formal_safety_program",
    "flammables_explosives_chemicals", "other_insurance_with_carrier",
    "coverage_declined_cancelled_nonrenewed",
    "abuse_molestation_discrimination_claims", "fraud_arson_conviction",
    "uncorrected_fire_safety_violations", "foreclosure_repossession_bankruptcy",
    "judgement_or_lien", "business_in_trust", "foreign_operations",
    "other_business_ventures", "owns_leases_operates_drones",
    "hires_drone_operators",
})
_SAFETY_ELEMENTS = frozenset({"safety manual", "safety position",
                              "monthly meetings", "osha"})
_ORG_ROLES = frozenset({"parent", "subsidiary"})

# Words that say what KIND of company something is, not WHICH company it is.
# Two firms sharing "Insurance Company" are not the same firm.
_ORG_STOPWORDS = frozenset({
    "inc", "incorporated", "llc", "llp", "lp", "ltd", "limited", "co",
    "company", "corp", "corporation", "the", "and", "of", "group", "holdings",
    "services", "service", "enterprises", "partners", "associates", "assoc",
    "mutual", "insurance", "agency", "brokerage", "trust", "plc", "pllc", "pc",
})


def _val(v: Any) -> Any:
    """Unwrap a fact envelope. The merge stores {"value": ..., ...} for some
    facts and a bare scalar for others; every consumer has to cope with both."""
    if isinstance(v, dict) and "value" in v:
        return v.get("value")
    return v


def _text(v: Any) -> str:
    v = _val(v)
    return "" if v is None else str(v).strip()


def _org_tokens(name: Any) -> set:
    """The words that IDENTIFY an organisation, legal form stripped."""
    return {w for w in re.findall(r"[a-z0-9]+", _text(name).lower())
            if w not in _ORG_STOPWORDS and len(w) > 2}


def _domain_text(value: Any) -> str:
    """The identifying part of a website or email, as ONE string.

    NOT split into tokens, and that is the whole point: a real domain welds the
    name together - "cedarbluffsteel" - so a token-set intersection against
    {"cedar","bluff","steel"} is EMPTY and the check silently never fires. It
    did exactly that on its first run against the live defect it was written
    for. Match by substring instead."""
    s = _text(value).lower()
    s = re.sub(r"^\w+://", "", s)
    if "@" in s:
        s = s.split("@", 1)[1]
    s = s.split("/", 1)[0]
    parts = [p for p in s.split(".") if p not in ("www", "com", "net", "org",
                                                  "co", "uk", "us", "biz", "io")]
    return re.sub(r"[^a-z0-9]+", "", "".join(parts))


def _domain_affinity(domain: str, name: Any) -> int:
    """How many of an organisation's identifying words the domain contains."""
    return sum(1 for w in _org_tokens(name) if w in domain)


def _digits(v: Any) -> str:
    return re.sub(r"\D", "", _text(v))


def _rows(facts: dict, key: str) -> List[dict]:
    v = _val((facts or {}).get(key))
    return [r for r in v if isinstance(r, dict)] if isinstance(v, list) else []


def _finding(code, severity, message, **extra) -> dict:
    d = {"code": code, "severity": severity, "message": message}
    d.update(extra)
    return d


# ═══════════════════════════════════════════════════════════════════════════
# The checks
# ═══════════════════════════════════════════════════════════════════════════

def _known_party_names(facts: dict) -> List[str]:
    names = [_text(facts.get("applicant_name")), _text(facts.get("dba_name"))]
    roster = _val((facts or {}).get("additional_named_insureds"))
    if isinstance(roster, list):
        names += [_text(n) for n in roster if not isinstance(n, dict)]
        names += [_text(n.get("name")) for n in roster if isinstance(n, dict)]
    for key in ("named_insured_details", "organization_relationships",
                "additional_interests"):
        names += [_text(r.get("name")) for r in _rows(facts, key)]
    return [n for n in names if n]


def check_detail_rows_name_a_known_party(facts: dict) -> List[dict]:
    """R1 - a detail row describing a party nobody names.

    `named_insured_details` describes the SAME parties as
    `additional_named_insureds`. A row naming someone absent from the roster is
    either an invention or a party promoted out of a different interest
    column - the exact confusion the extraction prompt warns about, where an
    ADDITIONAL INSURED is written up as a NAMED insured."""
    roster = _val((facts or {}).get("additional_named_insureds"))
    if not isinstance(roster, list) or not roster:
        return []
    known = {frozenset(_org_tokens(n)) for n in roster if _org_tokens(n)}
    known |= {frozenset(_org_tokens(facts.get("applicant_name")))}
    out = []
    for i, row in enumerate(_rows(facts, "named_insured_details")):
        toks = frozenset(_org_tokens(row.get("name")))
        if not toks:
            continue
        if not any(toks & k for k in known if k):
            out.append(_finding(
                "ORPHAN_DETAIL_ROW", ERROR,
                f"named_insured_details[{i}] describes {_text(row.get('name'))!r}, "
                f"who is not in additional_named_insureds",
                fact="named_insured_details", index=i,
                value=_text(row.get("name"))))
    return out


_UNIQUE_IDENTITY_COLUMNS = (("fein", "FEIN"), ("tax_identifier", "FEIN"))


def check_no_two_entities_share_a_unique_identifier(facts: dict) -> List[dict]:
    """R2 - two parties carrying one legally unique identifier.

    A FEIN identifies exactly one entity. Two named insureds holding the same
    one is a cross-row copy, and it is the single highest-confidence signal
    that a table's rows have been mixed - it needs no answer key and has no
    legitimate explanation.

    Phones, websites and addresses are DELIBERATELY NOT here: affiliates
    genuinely share a switchboard and a holding company genuinely uses the
    operating company's domain. Those are handled as WARN by R3, on a test that
    can tell mis-attribution from sharing."""
    seen: Dict[str, List[str]] = {}
    scalar_fein = _digits(facts.get("fein"))
    if len(scalar_fein) == 9:
        seen[scalar_fein] = [_text(facts.get("applicant_name")) or "the applicant"]
    for row in _rows(facts, "named_insured_details"):
        for col, _label in _UNIQUE_IDENTITY_COLUMNS:
            d = _digits(row.get(col))
            if len(d) != 9:
                continue
            seen.setdefault(d, []).append(_text(row.get("name")) or "(unnamed row)")
    out = []
    for value, holders in seen.items():
        distinct = {h for h in holders if h}
        if len(holders) > 1 and len(distinct) > 1:
            out.append(_finding(
                "SHARED_FEIN", ERROR,
                f"FEIN {value} is filed under {len(distinct)} different parties: "
                f"{', '.join(sorted(distinct))}",
                fact="named_insured_details", value=value,
                holders=sorted(distinct)))
    return out


def check_identity_values_match_the_party_they_are_filed_under(facts: dict) -> List[dict]:
    """R3 - a website or email whose own domain names a DIFFERENT party.

    THE LIVE DEFECT, key-free. `applicant_website` held
    "www.cedarbluffsteel.com" on a package whose applicant is Meridian
    Ironworks & Mechanical - and Cedar Bluff Steel Fabricators is sitting right
    there in the same roster. The domain's identifying words overlap the OTHER
    party's name and not the one it is filed under.

    WARN, not ERROR, and the asymmetry is the point: a group genuinely can run
    every company off one domain. The check only fires when the domain matches
    some OTHER known party BETTER than the party it is attached to - sharing
    alone is silent."""
    out = []
    candidates: List[tuple] = []
    applicant = _text(facts.get("applicant_name"))
    for key in ("applicant_website", "applicant_email", "contact_email"):
        v = _text(facts.get(key))
        if v:
            candidates.append((key, None, applicant, v))
    for i, row in enumerate(_rows(facts, "named_insured_details")):
        for col in ("website", "email"):
            v = _text(row.get(col))
            if v:
                candidates.append(("named_insured_details", i,
                                   _text(row.get("name")), v))
    parties = [p for p in _known_party_names(facts) if _org_tokens(p)]
    for fact_key, idx, owner, value in candidates:
        dom = _domain_text(value)
        if len(dom) < 4:
            continue
        own = _domain_affinity(dom, owner)
        better = [p for p in parties
                  if p != owner and _domain_affinity(dom, p) > own]
        if better:
            out.append(_finding(
                "IDENTITY_FILED_UNDER_THE_WRONG_PARTY", WARN,
                f"{value!r} is filed under {owner or '(unnamed)'} but its domain "
                f"names {better[0]!r}",
                fact=fact_key, index=idx, value=value,
                filed_under=owner, matches=better[0]))
    return out


def check_declared_vocabularies(facts: dict) -> List[dict]:
    """R4 - a value outside the enum the extraction schema declares.

    An unrecognised `topic` is not harmless: no resolver can place it, so the
    disclosure it describes silently does not reach the form."""
    out = []
    for i, row in enumerate(_rows(facts, "disclosure_answers")):
        topic = _text(row.get("topic")).lower()
        if topic and topic not in _DISCLOSURE_TOPICS:
            out.append(_finding("UNKNOWN_DISCLOSURE_TOPIC", ERROR,
                                f"disclosure_answers[{i}].topic={topic!r} is not a "
                                f"declared topic - no box can receive it",
                                fact="disclosure_answers", index=i, value=topic))
        ans = _text(row.get("answer")).upper()
        if ans and ans not in ("Y", "N"):
            out.append(_finding("BAD_DISCLOSURE_ANSWER", ERROR,
                                f"disclosure_answers[{i}].answer={ans!r} is not Y or N",
                                fact="disclosure_answers", index=i, value=ans))
    for i, row in enumerate(_rows(facts, "organization_relationships")):
        role = _text(row.get("role")).lower()
        if role and role not in _ORG_ROLES:
            out.append(_finding("UNKNOWN_ORG_ROLE", ERROR,
                                f"organization_relationships[{i}].role={role!r}",
                                fact="organization_relationships", index=i, value=role))
    els = _val((facts or {}).get("safety_program_elements"))
    if isinstance(els, list):
        for e in els:
            if _text(e).lower() not in _SAFETY_ELEMENTS:
                out.append(_finding("UNKNOWN_SAFETY_ELEMENT", WARN,
                                    f"safety_program_elements carries {_text(e)!r}, "
                                    f"which ticks no ACORD box",
                                    fact="safety_program_elements", value=_text(e)))
    return out


def check_disclosures_agree_with_the_structured_facts(facts: dict) -> List[dict]:
    """R5 - the answer and the detail contradict each other.

    "Does the applicant have any subsidiaries?" answered N while
    `organization_relationships` carries a subsidiary row means one of the two
    was read off the wrong part of the document. Either way the form cannot be
    right, and the contradiction is visible without any key."""
    out = []
    answers = {_text(r.get("topic")).lower(): _text(r.get("answer")).upper()
               for r in _rows(facts, "disclosure_answers")}
    roles = {_text(r.get("role")).lower() for r in _rows(facts, "organization_relationships")}
    for topic, role, label in (("has_subsidiaries", "subsidiary", "a subsidiary"),
                               ("subsidiary_of_another", "parent", "a parent")):
        if answers.get(topic) == "N" and role in roles:
            out.append(_finding(
                "DISCLOSURE_CONTRADICTS_DETAIL", ERROR,
                f"disclosure_answers says {topic}=N but organization_relationships "
                f"carries {label}",
                fact="disclosure_answers", value=topic))
    els = _val((facts or {}).get("safety_program_elements")) or []
    if answers.get("formal_safety_program") == "N" and isinstance(els, list) and els:
        out.append(_finding(
            "DISCLOSURE_CONTRADICTS_DETAIL", ERROR,
            "disclosure_answers says formal_safety_program=N but "
            "safety_program_elements is not empty",
            fact="disclosure_answers", value="formal_safety_program"))
    return out


def _normalise_for_search(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def check_evidence_quotes_are_in_the_document(facts: dict, raw_text: str = "") -> List[dict]:
    """R6 - a grounding quote the document does not contain.

    `disclosure_answers` carries `evidence_quote` precisely so a deterministic
    answer can be trusted. A quote that is not in the document is a fabricated
    warrant for an assertion on a legal form, and it is checkable exactly once -
    here, while the raw text is still in hand.

    Silent with no raw text: absence of the document is not evidence against
    the quote."""
    if not raw_text:
        return []
    hay = _normalise_for_search(raw_text)
    if not hay:
        return []
    out = []
    for i, row in enumerate(_rows(facts, "disclosure_answers")):
        quote = _text(row.get("evidence_quote"))
        needle = _normalise_for_search(quote)
        if len(needle) < 12:
            continue
        if needle not in hay:
            out.append(_finding(
                "EVIDENCE_QUOTE_NOT_IN_DOCUMENT", ERROR,
                f"disclosure_answers[{i}] ({_text(row.get('topic'))}) cites a "
                f"sentence the document does not contain",
                fact="disclosure_answers", index=i, value=quote[:90]))
    return out


_SHAPES = (
    ("fein", re.compile(r"^\d{9}$"), _digits, "a FEIN is 9 digits"),
    ("postal_code", re.compile(r"^\d{5}(\d{4})?$"), _digits, "a ZIP is 5 or 9 digits"),
)


def check_column_shapes(facts: dict) -> List[dict]:
    """R7 - a cell whose shape its own column forbids.

    The cheapest cross-row-contamination detector there is: a 7-digit account
    number in a 9-digit FEIN column is the kit's own shape trap, and it is the
    same signature as a value copied out of the neighbouring box."""
    out = []
    for key in ("named_insured_details", "additional_interests"):
        for i, row in enumerate(_rows(facts, key)):
            for col, pattern, prep, why in _SHAPES:
                raw = _text(row.get(col))
                if not raw:
                    continue
                if not pattern.match(prep(raw)):
                    out.append(_finding(
                        "COLUMN_SHAPE", WARN,
                        f"{key}[{i}].{col}={raw!r} - {why}",
                        fact=key, index=i, value=raw))
    return out


_CHECKS = (
    check_detail_rows_name_a_known_party,
    check_no_two_entities_share_a_unique_identifier,
    check_identity_values_match_the_party_they_are_filed_under,
    check_declared_vocabularies,
    check_disclosures_agree_with_the_structured_facts,
    check_column_shapes,
)


def check_fact_relationships(facts: Optional[dict],
                             raw_text: str = "") -> List[dict]:
    """Every relationship finding for one merged fact set, most severe first.

    Never raises: a diagnostic that can break a pipeline is worse than no
    diagnostic, and this one is meant to run on every package."""
    facts = facts if isinstance(facts, dict) else {}
    out: List[dict] = []
    for check in _CHECKS:
        try:
            out.extend(check(facts) or [])
        except Exception:                                  # noqa: BLE001
            continue
    try:
        out.extend(check_evidence_quotes_are_in_the_document(facts, raw_text) or [])
    except Exception:                                      # noqa: BLE001
        pass
    order = {ERROR: 0, WARN: 1, INFO: 2}
    return sorted(out, key=lambda f: order.get(f.get("severity"), 3))


def summarise(findings: Iterable[dict]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for f in findings or []:
        counts[f.get("severity", "?")] = counts.get(f.get("severity", "?"), 0) + 1
        counts[f.get("code", "?")] = counts.get(f.get("code", "?"), 0) + 1
    return counts
