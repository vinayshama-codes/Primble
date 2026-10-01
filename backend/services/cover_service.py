#cover_service.py

import hashlib
import io
import json
import re
import logging
import textwrap
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from config.settings import groq_chat, LLM_MODEL
from services.extraction_service import _fv, _cache_get, _cache_set

logger = logging.getLogger(__name__)


# ── The cover page must report COVERAGE, not mentions ────────────────────────
# Client 2026-09-11 item 2: the cover listed Property, Crime, WC, Farm, Liquor,
# EPLI and OCP on a package whose declarations deny the first three and never
# mention the rest except inside an ISO endorsement's "modifies insurance
# provided under the following" menu. `lines_of_business` is a MENTION list
# with no definition in the extraction prompt; `carried_lines_of_business` is
# the evidenced inventory. Fails open to the raw list, i.e. today's behaviour.
def _cover_lines_of_business(facts, flags=None) -> list:
    # An empty result is a REAL answer - "nothing here is evidenced" - and the
    # cover prints "---" rather than a list of coverages the applicant does not
    # hold. The door itself returns the raw list untouched when the package
    # carries no per-line evidence either way, so a legacy session is unchanged.
    #
    # THE FLAGS ARE PASSED IN (14 Sep). This read `facts.get("flags")`, a key a
    # session's facts never carry - flags live beside facts - so the cover
    # never saw them, while the scorer, reading the same door, did. The cover
    # and the score could then disagree about which lines the package carries.
    if flags is None:
        flags = (facts or {}).get("flags") if isinstance(facts, dict) else None
    try:
        from services.lob_canon import carried_lines_of_business
        return list(carried_lines_of_business(facts, flags))
    except Exception:                                         # noqa: BLE001
        return list((facts or {}).get("lines_of_business") or [])


# ── The SQS paragraph must agree with the table it sits above (15 Sep 2026) ──
# Live Orbin cover page: "The overall average SQS of 63/100 ..." above five form
# scores that average 70 - 63 is the PACKAGE score, and the prompt itself
# labelled it "Overall Average SQS". The same paragraph said "ACORD 126
# performed best at 74" with ACORD 131 at 77 in its own input. The prompt now
# names the score and hands over the ranking; `_checked_sqs_reasoning` refuses a
# paragraph that still contradicts either and prints the deterministic sentence
# instead. Structural only: the word "average" on a package score, and a best /
# worst claim about a form that is not at that end of the ranking.
_COVER_FORM_RE = re.compile(r"ACORD[\s_]*(\d{2,3})(?:[\s_]*(CA|CO)\b)?", re.I)
_COVER_HIGH_RE = re.compile(r"\b(?:best|highest|strongest|top)\b", re.I)
_COVER_LOW_RE = re.compile(r"\b(?:worst|lowest|weakest)\b", re.I)


def _cover_form_label(form_id) -> str:
    return str(form_id or "").replace("ACORD_", "ACORD ").replace("_", " ").strip()


def _agent_name(user: Optional[dict]) -> str:
    """The producer's name exactly as ACORD 125 prints it in its producer
    CONTACT box - an account name saved in lower case printed that way on the
    cover beside the formatted name on every form (owner's retest, 1 Oct 2026).
    One rule for both: `pdf_service.display_value_for_box` (a name typed with
    a capital prints as typed; all-lowercase typing is formatted)."""
    name = re.sub(r"\s+", " ", str((user or {}).get("full_name") or "")).strip()
    if not name:
        return ""
    try:
        from services.pdf_service import display_value_for_box
        shown = display_value_for_box("ACORD_125", "Producer_ContactPerson_FullName_A",
                                      name, provenance="account")
        return str(shown or "").strip() or name
    except Exception:                                      # noqa: BLE001
        return name


def _cover_form_key(text) -> str:
    m = _COVER_FORM_RE.search(str(text or "").replace("_", " "))
    return f"{m.group(1)}{(m.group(2) or '').upper()}" if m else ""


def _ranked_form_scores(sqs_results) -> list:
    """[(form_id, score)] highest first; a form without a numeric score is left out."""
    ranked = []
    for fid, sqs in (sqs_results or {}).items():
        sc = sqs.get("sqs_score") if isinstance(sqs, dict) else None
        if isinstance(sc, (int, float)) and not isinstance(sc, bool):
            ranked.append((fid, int(sc)))
    return sorted(ranked, key=lambda t: (-t[1], str(t[0])))


def _deterministic_sqs_reasoning(ranked, score, is_package: bool) -> str:
    label = "package SQS" if is_package else "average form SQS"
    if not ranked:
        return f"The {label} is {score}/100. Scores below 75 indicate fields requiring manual review."
    hi, lo = ranked[0], ranked[-1]
    if len(ranked) == 1:
        spread = f"{_cover_form_label(hi[0])} scored {hi[1]}"
    elif hi[1] == lo[1]:
        spread = f"Every form scored {hi[1]}"
    else:
        spread = (f"Form scores run from {lo[1]} ({_cover_form_label(lo[0])}) "
                  f"to {hi[1]} ({_cover_form_label(hi[0])})")
    return (f"The {label} is {score}/100. {spread}. "
            f"Scores below 75 indicate fields requiring manual review.")


def _tier_claim_res() -> List[Tuple[str, "re.Pattern"]]:
    """(tier, pattern) for every tier on the score ladder - read off the ladder,
    never listed here. A tier is a claim when written as the tier's own name
    ("Needs Work") or followed by "tier"; ordinary prose ("the narrative needs
    work") is not one."""
    out = []
    for tier in sorted({grade_and_tier(n)[1] for n in range(0, 101)} - {_COVER_UNKNOWN}):
        words = r"\s+".join(map(re.escape, tier.split()))
        out.append((tier, re.compile(rf"\b{words}\b|(?i:\b{words}\s+tier\b)")))
    return out


def _routing_claim_res() -> List[Tuple[str, "re.Pattern"]]:
    """(routing words, pattern) for every routing the app prints. A one-word
    routing ("Hold") is a claim only beside the word "routing"."""
    out = []
    for words_ in sorted(set(_ROUTING_WORDS.values())):
        parts = re.split(r"[\s-]+", words_.strip())
        body = r"[\s-]+".join(map(re.escape, parts))
        pat = (rf"(?i:\b{body}\b)" if len(parts) > 1
               else rf"(?i:\b{body}\s+routing\b|\brouting\s+(?:of|to)\s+{body}\b)")
        out.append((words_, re.compile(pat)))
    return out


def _routing_key(words_: Any) -> str:
    return re.sub(r"[\s-]+", " ", str(words_ or "").strip().lower())


def _checked_sqs_reasoning(text, ranked, score, is_package: bool, package_routing=None) -> str:
    """The model's paragraph, or the deterministic one when it contradicts the
    scores it was handed.

    A sentence about the SUBMISSION (it names no form) may state only the
    package's own tier and routing - the cover prints both in the table above
    the paragraph (Orbin, 1 Oct 2026: "drives the package into a Needs Work tier
    with priority review routing" under a table reading Major Gaps / Standard
    review - the ACORD 126's tier and routing, pinned on the package). A routing
    the caller could not supply is never stated for the package."""
    t = str(text or "").strip()
    if not t:
        return _deterministic_sqs_reasoning(ranked, score, is_package)
    if is_package and re.search(r"\baverage\b", t, re.I):
        return _deterministic_sqs_reasoning(ranked, score, is_package)
    if is_package:
        own_tier = grade_and_tier(score)[1]
        own_routing = _routing_key(routing_label(package_routing)) if package_routing else None
        for sentence in re.split(r"(?<=[.!?])\s+", t):
            if _COVER_FORM_RE.search(sentence.replace("_", " ")):
                continue                    # about a form - its own tier is its own
            for tier, rx in _tier_claim_res():
                if rx.search(sentence) and tier != own_tier:
                    return _deterministic_sqs_reasoning(ranked, score, is_package)
            for words_, rx in _routing_claim_res():
                if rx.search(sentence) and _routing_key(words_) != own_routing:
                    return _deterministic_sqs_reasoning(ranked, score, is_package)
    if ranked:
        top = {_cover_form_key(f) for f, sc in ranked if sc == ranked[0][1]}
        bottom = {_cover_form_key(f) for f, sc in ranked if sc == ranked[-1][1]}
        for sentence in re.split(r"(?<=[.!?])\s+", t):
            named = {f"{n}{(st or '').upper()}"
                     for n, st in _COVER_FORM_RE.findall(sentence.replace("_", " "))}
            if len(named) != 1:
                continue
            form = next(iter(named))
            if _COVER_HIGH_RE.search(sentence) and form not in top:
                return _deterministic_sqs_reasoning(ranked, score, is_package)
            if _COVER_LOW_RE.search(sentence) and form not in bottom:
                return _deterministic_sqs_reasoning(ranked, score, is_package)
    return t


def _moved_current_term(facts: dict) -> Optional[str]:
    """The current policy's own term, once the merge moved it out of the
    proposed dates (`routed_from: current_term`, 15 Sep 2026) - or None."""
    held = (facts or {}).get("prior_expiration_date")
    if not (isinstance(held, dict) and held.get("routed_from") == "current_term"):
        return None
    eff = _fv(facts, "prior_effective_date")
    exp = _fv(facts, "prior_expiration_date")
    return f"{eff} - {exp}" if eff else f"ending {exp}"


_COVER_UNKNOWN = "Not provided"


def _moved_term_ended(facts: dict) -> bool:
    """Has the term `_moved_current_term` names already ended? (24 Sep 2026:
    the cover called 07/15/25 - 07/15/26 the "current term" in September 2026
    and its summary said the account "is currently in force".)"""
    from datetime import date as _date, datetime as _dt
    exp = str(_fv(facts, "prior_expiration_date") or "").strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return _dt.strptime(exp, fmt).date() < _date.today()
        except ValueError:
            continue
    return False


# ── What a cover prints about a score, and how it prints values (1 Oct 2026) ─
# The Submission Brief printed "77/100 B" beside "Needs Work": the PACKAGE score
# with the FIRST FORM's grade (81 -> B), because the brief laid the package's
# number over that form's result. It printed the scorer's routing CODE,
# "priority_review", which no label table knew, and revenue as "300000". A
# grade and a tier are read off the score by the one ladder the app uses
# (`sqs_service.tier_for_score`); a routing code is always printed as words.
_ROUTING_WORDS = {
    "auto_quote":      "Auto-quote",
    "priority_review": "Priority review",
    "standard_review": "Standard review",
    "review":          "Light review",
    "full_review":     "Full review",
    "hold":            "Hold",
}


def routing_label(code) -> str:
    """A routing decision in words - never a raw code."""
    c = str(code or "").strip()
    if not c:
        return _COVER_UNKNOWN
    words = _ROUTING_WORDS.get(c.lower())
    if words:
        return words
    text = c.replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def grade_and_tier(score) -> tuple:
    """(grade, tier) for a score - the one ladder, so a cover can never print a
    grade the app does not show for the same number."""
    try:
        from services.sqs_service import tier_for_score
        grade, tier, _color = tier_for_score(int(score or 0))
        return grade, tier
    except Exception:                                         # noqa: BLE001
        return _COVER_UNKNOWN, _COVER_UNKNOWN


def _money(value) -> str:
    """A plain amount as the forms print money ("300000" -> "$300,000"); text
    that is not a plain amount prints as it came."""
    s = str(value or "").strip()
    m = re.fullmatch(r"\$?\s*(\d[\d,]*)(\.\d{1,2})?", s)
    if not m:
        return s
    whole = m.group(1).replace(",", "")
    cents = m.group(2) or ""
    if cents.strip(".0") == "":
        cents = ""
    elif len(cents) == 2:
        cents += "0"                                          # ".5" -> ".50"
    return f"${int(whole):,}{cents}"


def _as_the_forms_print(names, facts) -> str:
    """A company list with each company spelled as the forms print it: an
    all-capitals printing gives way to an ordinary-case printing of the SAME
    company that the documents also carry (ACORD 125 CARRIER's rule, 1 Oct 2026).
    Nothing is added, dropped or reordered."""
    text = str(names or "").strip()
    if not text:
        return text
    try:
        from services.normalization import strict_entity_key as _ek
    except Exception:                                         # noqa: BLE001
        return text
    best: Dict[str, str] = {}
    for row in (_fv(facts, "coverage_lines") or []):
        if not isinstance(row, dict):
            continue
        name = str(row.get("carrier") or "").strip()
        key = _ek(name) if name else None
        if key and (key not in best or (best[key].isupper() and not name.isupper())):
            best[key] = name
    pieces = re.split(r"(\s*[/;]\s*)", text)
    out = []
    for piece in pieces:
        if re.fullmatch(r"\s*[/;]\s*", piece or ""):
            out.append(piece)
            continue
        key = _ek(piece) if piece.strip() else None
        out.append(best.get(key, piece) if key else piece)
    return "".join(out)


def _true_flags(flags) -> List[str]:
    """The risk flags that are TRUE, by name. A false flag only says a document
    did not state something - `asserts_no_subcontractors: False` was read by the
    model as "none are asserted" on a package that rates subcontracted work - so
    it is not handed to the model at all."""
    return sorted(str(k) for k, v in (flags or {}).items()
                  if v is True and not str(k).startswith("_"))


def _gl_classifications(facts) -> str:
    """The GL class schedule the declarations print, one line per class."""
    rows = _fv(facts, "gl_class_code_schedule")
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        code = str(r.get("class_code") or "").strip()
        what = str(r.get("classification") or "").strip()
        basis = str(r.get("premium_basis") or "").strip()
        amount = str(r.get("exposure_amount") or "").strip()
        if not (code or what):
            continue
        tail = ", ".join(p for p in (basis, amount) if p)
        out.append(f"{code} {what}".strip() + (f" ({tail})" if tail else ""))
    return "; ".join(out[:10]) or "Not provided"


def a2a_block(facts: dict, flags: dict, *, org_name: str, user: Optional[dict],
              scores: List[dict], form_ids: List[str], hard_stops=None, soft_stops=None,
              report_type: Optional[str] = None) -> dict:
    """The hidden carrier-AI (A2A) block - built from the package's OWN records,
    never written by the model (1 Oct 2026: the model wrote it, so it repeated a
    wrong grade and was asked for a FEIN and a NAICS code it was never given).
    Every value is one the package holds; a missing one is null, never guessed."""
    def _v(key):
        v = _fv(facts, key)
        return v if v not in (None, "") else None
    block = {
        "generated_at":       datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "agent_name":         _agent_name(user) or None,
        "org_name":           org_name or None,
        "applicant_name":     _v("applicant_name"),
        "lines_of_business":  _cover_lines_of_business(facts, flags),
        "effective_date":     _v("effective_date"),
        "expiration_date":    _v("expiration_date"),
        "total_revenue":      _money(_v("total_revenue")) if _v("total_revenue") else None,
        "entity_type":        _v("entity_type"),
        "prior_carrier":      _as_the_forms_print(_v("prior_carrier"), facts) if _v("prior_carrier") else None,
        "forms_included":     list(form_ids or []),
        "sqs_scores":         scores,
        "hard_stops":         [str(s) for s in (hard_stops or []) if s],
        "soft_stops":         [str(s) for s in (soft_stops or []) if s],
        "risk_flags":         _true_flags(flags),
        "primble_version":    "12.4.0",
        "a2a_schema_version": "1.0",
    }
    if report_type:
        block["report_type"] = report_type
    return block


def _score_entry(name: str, sqs: Optional[dict]) -> dict:
    score = (sqs or {}).get("sqs_score", 0) or 0
    grade, tier = grade_and_tier(score)
    return {"form": name, "score": score, "grade": grade, "tier": tier,
            "routing": routing_label((sqs or {}).get("routing_decision"))}


def _cover_info_values(facts: dict, flags: dict, user: Optional[dict], org_name: str) -> Dict[str, str]:
    """The cover's submission table, as printed (live run 10, 15 Sep 2026).
    POLICY PERIOD printed "\u2014 - \u2014" once the proposed term became
    unknown; it now says the term is to be confirmed and names the current
    one. Every unknown reads "Not provided" - no em dash in client copy."""
    def _v(key: str) -> str:
        v = _fv(facts, key)
        return str(v) if v else _COVER_UNKNOWN

    eff, exp = _fv(facts, "effective_date"), _fv(facts, "expiration_date")
    if eff:
        period = f"{eff} - {exp}" if exp else f"{eff} - to be confirmed"
    else:
        moved = _moved_current_term(facts)
        _which = "expired term" if _moved_term_ended(facts) else "current term"
        period = f"To be confirmed ({_which} {moved})" if moved else "To be confirmed"
    lobs = _cover_lines_of_business(facts, flags)
    return {
        "agent":           _agent_name(user) or _COVER_UNKNOWN,
        "org":             org_name or _COVER_UNKNOWN,
        "period":          period,
        "entity_type":     _v("entity_type"),
        "applicant":       _v("applicant_name"),
        "revenue":         _money(_v("total_revenue")) if _fv(facts, "total_revenue") else _COVER_UNKNOWN,
        "lines":           ", ".join(lobs) if lobs else _COVER_UNKNOWN,
        "employees":       _v("num_employees"),
        "prior_carrier":   (_as_the_forms_print(_v("prior_carrier"), facts)
                            if _fv(facts, "prior_carrier") else _COVER_UNKNOWN),
        "mailing_address": _v("mailing_address"),
    }


async def generate_ai_cover_narrative(
    facts: dict,
    flags: dict,
    sqs_results: dict,
    form_ids: List[str],
    org_name: str,
    user: dict = None,
    package_score: int = None,
    package_routing: Optional[str] = None,
) -> dict:
    """Cover-page narrative.

    `package_score` is the submission's real SQS, computed independently by
    calculate_package_sqs. Pass it whenever it is available: this function used
    to AVERAGE the per-form scores and print that as the submission score, which
    disagreed with the score shown everywhere else in the app (2026-08-16 audit).
    The average survives only as a fallback for callers that have no package
    score - it is never the preferred number.
    """
    # Grade and tier from the one ladder, routing in words (1 Oct 2026) - a
    # routing CODE handed to the model came back in the client's summary.
    # A card worth zero points by its own declaration (`unscored` - the landlord
    # "kept for certificates") explains nothing about the score, so the model is
    # never handed one: it called the landlord a "major gap" (Orbin, 1 Oct 2026).
    sqs_summary = [
        {**_score_entry(fid, sqs),
         "breakdown": sqs.get("breakdown", {}), "issues": sqs.get("issues", []),
         "recommendations": [r for r in (sqs.get("recommendations") or [])
                             if not (isinstance(r, dict) and r.get("unscored"))]}
        for fid, sqs in sqs_results.items()
    ]
    # The submission's own score. Falls back to a per-form average ONLY when no
    # package score was supplied (legacy callers); see the docstring above.
    if package_score is not None:
        avg_sqs = int(package_score)
    else:
        avg_sqs = int(sum(s.get("sqs_score", 0) for s in sqs_results.values()) / max(len(sqs_results), 1)) if sqs_results else 0
    # The score's real name and the ranking, handed to the model and used by
    # the check below - see `_checked_sqs_reasoning`.
    _ranked = _ranked_form_scores(sqs_results)
    _ranked_line = ", ".join(f"{_cover_form_label(fid)} {sc}" for fid, sc in _ranked) or "none"
    _is_package = package_score is not None
    _score_label = "Package SQS" if _is_package else "Average form SQS"
    _score_note = ("the submission's own score, computed independently - NOT an "
                   "average of the form scores" if _is_package
                   else "the average of the form scores")
    # The package's own grade, tier and routing, as the cover's table prints
    # them (1 Oct 2026): the model had only each FORM's, and gave the package
    # the ACORD 126's "Needs Work / priority review" under a Major Gaps /
    # Standard review row. `_checked_sqs_reasoning` holds it to them.
    if _is_package:
        _pg, _pt = grade_and_tier(avg_sqs)
        _pkg_rank_line = (f"\nPackage grade / tier / routing: {_pg} / {_pt} / "
                          f"{routing_label(package_routing)}")
        _pkg_rank_rule = ("A tier or routing you give the submission must be the package's own, "
                          "from the line above; a form's tier and routing describe that form only.")
    else:
        _pkg_rank_line, _pkg_rank_rule = "", ""
    applicant = _fv(facts, 'applicant_name') or 'Unknown'
    _moved_term = _moved_current_term(facts)
    if _moved_term and _moved_term_ended(facts):
        _term_line = (f"\nLast Policy Term (EXPIRED - not in force): {_moved_term}")
    else:
        _term_line = f"\nCurrent Policy Term: {_moved_term}" if _moved_term else ""
    prompt  = f"""You are an expert commercial insurance underwriting analyst.
Generate a professional cover page summary for this ACORD submission package.

SUBMISSION DATA:
Agent/User: {_agent_name(user)}
Agency/Org: {org_name}
Applicant: {_fv(facts, 'applicant_name') or 'Unknown'}
Lines of Business: {_cover_lines_of_business(facts, flags)}
Proposed Effective Date: {_fv(facts, 'effective_date') or 'To be confirmed'}{_term_line}
Prior Carrier: {_as_the_forms_print(_fv(facts, 'prior_carrier'), facts) or 'Not provided'}
Operations: {_fv(facts, 'operations_description') or 'Not provided'}
Revenue: {_money(_fv(facts, 'total_revenue')) or 'Not provided'}
Forms Generated: {', '.join(_cover_form_label(f) for f in form_ids)}
{_score_label}: {avg_sqs}/100 ({_score_note}){_pkg_rank_line}
Form scores, highest first: {_ranked_line}
SQS Results: {json.dumps(sqs_summary)}

Respond with ONLY a valid JSON object with exactly two keys:
"narrative": A 3-4 paragraph professional narrative (plain text, no markdown)
"sqs_reasoning": A single paragraph explaining the SQS score. Call the submission's score the "{_score_label}" and never an average unless it is one. If you name the strongest or weakest form, it must be the first or last form in the "Form scores, highest first" list. {_pkg_rank_rule}

Return ONLY the JSON object."""
    # Cached on the PROMPT ITSELF (live run 10, 15 Sep 2026). The key held only
    # applicant / forms / score / org / ranking, so a paragraph written from
    # other data - no prior carrier, the old term - was served back after the
    # data changed. Anything the model reads is now part of the key.
    _cover_cache_key = "cover_ai:" + hashlib.md5(prompt.encode()).hexdigest()
    # The A2A block is built from the records, never by the model, and never
    # cached - it carries its own timestamp (1 Oct 2026, see `a2a_block`).
    _stops = lambda k: [m for s_ in sqs_results.values() for m in ((s_ or {}).get(k) or [])]
    _block = a2a_block(facts, flags, org_name=org_name, user=user,
                       scores=[_score_entry(fid, sq) for fid, sq in sqs_results.items()],
                       form_ids=form_ids,
                       hard_stops=list(dict.fromkeys(_stops("hard_stops"))),
                       soft_stops=list(dict.fromkeys(_stops("soft_stops"))))
    _block["package_sqs"] = ({"score": avg_sqs, "grade": grade_and_tier(avg_sqs)[0],
                              "tier": grade_and_tier(avg_sqs)[1]} if _is_package else None)
    _cached_cover = await _cache_get(_cover_cache_key)
    if _cached_cover:
        return {**_cached_cover, "ai_block": _block}
    try:
        raw = await groq_chat(LLM_MODEL, [{"role": "user", "content": prompt}], max_tokens=4096)
        if raw.startswith("```"):
            raw = raw.replace("```json", "").replace("```", "").strip()
        s, e = raw.find("{"), raw.rfind("}")
        if s != -1 and e != -1:
            result = json.loads(raw[s : e + 1])
            result = {
                "narrative":     result.get("narrative", ""),
                "sqs_reasoning": _checked_sqs_reasoning(
                    result.get("sqs_reasoning", ""), _ranked, avg_sqs, _is_package,
                    package_routing),
            }
            await _cache_set(_cover_cache_key, result)
            return {**result, "ai_block": _block}
    except Exception as ex:
        logger.error(f"Cover page AI generation failed: {ex}")

    applicant = _fv(facts, 'applicant_name') or 'Unknown'
    _lobs_ev  = _cover_lines_of_business(facts, flags)
    lobs      = ", ".join(_lobs_ev) if _lobs_ev else "commercial insurance"
    return {
        "narrative": (
            f"This ACORD submission package was prepared by {org_name} on behalf of {applicant}. "
            f"The package covers {lobs} with a proposed effective date of {_fv(facts, 'effective_date') or 'TBD'}. "
            f"All forms have been populated using AI-extracted data from the uploaded source documents. "
            f"The submission has been reviewed for completeness and quality using the Submission Quality Score (SQS) system."
        ),
        "sqs_reasoning": _deterministic_sqs_reasoning(_ranked, avg_sqs, _is_package),
        "ai_block": _block,
    }


async def generate_lite_cover_narrative(
    facts: dict,
    flags: dict,
    sqs: dict,
    hard_stops: list,
    soft_stops: list,
    org_name: str,
    user: dict = None,
) -> dict:
    score   = sqs.get("sqs_score", 0)
    # The ladder's grade and the routing in words (1 Oct 2026) - the brief used
    # to pass the FIRST FORM's grade and the raw code "priority_review", and the
    # summary repeated both.
    grade, tier = grade_and_tier(score)
    routing = routing_label(sqs.get("routing_decision"))
    _revenue = _money(_fv(facts, "total_revenue")) if _fv(facts, "total_revenue") else "Not provided"
    prompt  = f"""You are an expert commercial insurance underwriting analyst.
Generate a professional pre-submission SQS summary for a producer who has uploaded their package for analysis.
This is NOT a full ACORD package — no forms have been generated. The purpose is to flag issues before the producer
proceeds with their platform of choice.

SUBMISSION DATA:
Agent/User: {_agent_name(user)}
Agency/Org: {org_name}
Applicant: {_fv(facts, 'applicant_name') or 'Unknown'}
Lines of Business: {_cover_lines_of_business(facts, flags)}
Effective Date: {_fv(facts, 'effective_date') or 'Not specified'}
Operations: {_fv(facts, 'operations_description') or 'Not provided'}
GL Classifications (as the declarations print them): {_gl_classifications(facts)}
Revenue: {_revenue}
SQS Score: {score}/100 (Grade: {grade}, Tier: {tier}, Routing: {routing})
Hard Stops (critical blockers): {hard_stops}
Soft Stops (warnings): {soft_stops}
Risk Flags that are TRUE (a flag not listed is simply not established): {_true_flags(flags)}

Respond with ONLY a valid JSON object with exactly two keys:
"narrative": 2-3 paragraphs focused on what the producer should watch out for, what information is missing,
  and how to strengthen this submission before proceeding. Plain text, no markdown.
"sqs_reasoning": One paragraph explaining the SQS score in context of the hard/soft stops found.

Return ONLY the JSON object."""
    # Cached on the PROMPT ITSELF (C93's rule): anything the model reads is part
    # of the key. The A2A block is never cached - it carries its own timestamp.
    _lite_cache_key = "cover_lite:" + hashlib.md5(prompt.encode()).hexdigest()
    _block = a2a_block(facts, flags, org_name=org_name, user=user,
                       scores=[_score_entry("Pre-Submission Analysis", sqs)], form_ids=[],
                       hard_stops=hard_stops, soft_stops=soft_stops,
                       report_type="lite_pre_submission")
    _cached_lite = await _cache_get(_lite_cache_key)
    if _cached_lite:
        return {**_cached_lite, "ai_block": _block}
    try:
        raw = await groq_chat(LLM_MODEL, [{"role": "user", "content": prompt}], max_tokens=4096)
        if raw.startswith("```"):
            raw = raw.replace("```json", "").replace("```", "").strip()
        s, e = raw.find("{"), raw.rfind("}")
        if s != -1 and e != -1:
            result = json.loads(raw[s : e + 1])
            result = {
                "narrative":     result.get("narrative", ""),
                "sqs_reasoning": result.get("sqs_reasoning", ""),
            }
            await _cache_set(_lite_cache_key, result)
            return {**result, "ai_block": _block}
    except Exception as ex:
        logger.error(f"Lite cover narrative generation failed: {ex}")

    applicant = _fv(facts, 'applicant_name') or 'Unknown'
    _lobs_ev  = _cover_lines_of_business(facts, flags)
    lobs      = ", ".join(_lobs_ev) if _lobs_ev else "commercial insurance"
    return {
        "narrative": (
            f"This pre-submission SQS analysis was prepared by {org_name} for {applicant} covering {lobs}. "
            f"The submission received an SQS score of {score}/100 (Grade {grade}). "
            f"{'The following critical issues must be resolved before submission: ' + '; '.join(hard_stops) + '. ' if hard_stops else ''}"
            f"{'The following warnings may impact the submission quality: ' + '; '.join(soft_stops) + '.' if soft_stops else ''}"
        ),
        "sqs_reasoning": (
            f"The SQS score of {score}/100 reflects the quality of the submission based on the uploaded documents. "
            f"{'Hard stops were identified that will block this submission. ' if hard_stops else ''}"
            f"Scores below 75 indicate fields or conditions requiring attention before proceeding."
        ),
        "ai_block": _block,
    }


def build_cover_page_pdf(
    facts: dict,
    flags: dict,
    sqs_results: dict,
    form_ids: List[str],
    org_name: str,
    narrative: str,
    ai_block: dict,
    sqs_reasoning: str = "",
    user: dict = None,
    hard_stops: list = None,
    soft_stops: list = None,
    file_manifest: list = None,
    package_checksum: str = None,
    package_sqs: Optional[dict] = None,
    package_label: str = "Total Package Score",
) -> bytes:
    generated_at = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")

    if not narrative or not narrative.strip():
        narrative = (
            f"This ACORD submission package was prepared by {org_name} for applicant "
            f"{_fv(facts, 'applicant_name') or 'Unknown'}. All forms have been populated using "
            f"AI-extracted data from the uploaded source documents."
        )

    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib import colors
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        )
        from reportlab.lib.enums import TA_RIGHT, TA_JUSTIFY, TA_CENTER, TA_LEFT

        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=letter,
            leftMargin=0.65*inch, rightMargin=0.65*inch,
            topMargin=0.65*inch, bottomMargin=0.65*inch,
        )

        NAVY       = colors.HexColor("#0f172a")
        PINK       = colors.HexColor("#e6007a")
        PINK_LIGHT = colors.HexColor("#fdf2f8")
        LIGHT      = colors.HexColor("#f8fafc")
        LIGHTER    = colors.HexColor("#f1f5f9")
        WHITE      = colors.white
        GREEN      = colors.HexColor("#10b981")
        YELLOW     = colors.HexColor("#f59e0b")
        RED        = colors.HexColor("#ef4444")
        BORDER     = colors.HexColor("#e2e8f0")
        TEXT_MAIN  = colors.HexColor("#1e293b")
        TEXT_MUTE  = colors.HexColor("#64748b")
        TEXT_HINT  = colors.HexColor("#94a3b8")
        SLATE      = colors.HexColor("#64748b")
        LOGO_BG    = colors.HexColor("#0f172a")

        def sqs_color(score):
            if score is None:
                return SLATE
            if score >= 90:
                return GREEN
            if score >= 75:
                return YELLOW
            return RED

        styles = getSampleStyleSheet()

        def S(name, **kw):
            return ParagraphStyle(name, parent=styles["Normal"], **kw)

        h1_style     = S("H1",   fontSize=14, textColor=NAVY,      fontName="Helvetica-Bold", leading=20, spaceAfter=4)
        h2_style     = S("H2",   fontSize=11, textColor=NAVY,      fontName="Helvetica-Bold", leading=16, spaceAfter=3)
        body_style   = S("Body", fontSize=9,  textColor=TEXT_MAIN,  fontName="Helvetica",      leading=14, spaceAfter=3, alignment=TA_JUSTIFY)
        label_s      = S("Lbl",  fontSize=8,  textColor=SLATE,     fontName="Helvetica-Bold")
        val_s        = S("Val",  fontSize=8,  textColor=NAVY,      fontName="Helvetica")
        small_s      = S("Sm",   fontSize=7,  textColor=TEXT_HINT,  fontName="Helvetica",      leading=10)
        reasoning_s  = S("Rsn",  fontSize=9,  textColor=TEXT_MAIN,  fontName="Helvetica-Oblique", leading=14, spaceAfter=3)
        disclaimer_s = S("Disc", fontSize=7,  textColor=TEXT_MUTE,  fontName="Helvetica-BoldOblique", leading=10)
        hidden_style = S("Hid",  fontSize=0.001, textColor=colors.white, fontName="Courier", leading=0.001, backColor=colors.white)
        logo_style   = S("Logo", fontSize=26, textColor=PINK, fontName="Helvetica-Bold", leading=32)
        powered_style = S("Pwr", fontSize=9,  textColor=PINK, fontName="Helvetica-Bold", alignment=TA_RIGHT)
        powered_date_style = S("PwrDt", fontSize=7, textColor=TEXT_HINT, fontName="Helvetica", alignment=TA_RIGHT)

        story = []

        # ── HEADER ──────────────────────────────────────────────────────────
        # Left: agency logo placeholder + agency name
        # Right: "Powered by primble.com" (small, pink) + date
       # Primble logo (lowercase "primble" in pink, bold, large)
        primble_logo = Paragraph(
            '<font color="#e6007a"><b>primble</b></font>',
            S("PrimbleLogo", fontSize=28, fontName="Helvetica-Bold", leading=34),
        )

        powered_cell = Paragraph(
            f'<font color="#e6007a"><b>Powered by primble.com</b></font><br/>'
            f'<font color="#94a3b8" size="7">{generated_at}</font>',
            S("Pwr2", fontSize=9, fontName="Helvetica", alignment=TA_RIGHT),
        )

        header_tbl = Table([[primble_logo, powered_cell]], colWidths=[3.5*inch, 3.5*inch])
        header_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), NAVY),
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
            ("LEFTPADDING",   (0,0), (-1,-1), 14),
            ("RIGHTPADDING",  (0,0), (-1,-1), 14),
            ("TOPPADDING",    (0,0), (-1,-1), 16),
            ("BOTTOMPADDING", (0,0), (-1,-1), 16),
        ]))
        story.append(header_tbl)
        story.append(Spacer(1, 0.14*inch))

        # ── SUBMISSION INFO TABLE ────────────────────────────────────────────
        _info      = _cover_info_values(facts, flags, user, org_name)
        forms_list = (", ".join(_cover_form_label(f) for f in form_ids) if form_ids
                      else "Pre-Submission SQS Analysis (Lite)")

        info_rows = [
            [Paragraph("AGENT / USER",      label_s), Paragraph(_info["agent"],           val_s),
             Paragraph("POLICY PERIOD",     label_s), Paragraph(_info["period"],          val_s)],
            [Paragraph("AGENCY",            label_s), Paragraph(_info["org"],             val_s),
             Paragraph("ENTITY TYPE",       label_s), Paragraph(_info["entity_type"],     val_s)],
            [Paragraph("APPLICANT",         label_s), Paragraph(_info["applicant"],       val_s),
             Paragraph("ANNUAL REVENUE",    label_s), Paragraph(_info["revenue"],         val_s)],
            [Paragraph("LINES OF BUSINESS", label_s), Paragraph(_info["lines"],           val_s),
             Paragraph("EMPLOYEES",         label_s), Paragraph(_info["employees"],       val_s)],
            [Paragraph("FORMS INCLUDED",    label_s), Paragraph(forms_list,               val_s),
             Paragraph("PRIOR CARRIER",     label_s), Paragraph(_info["prior_carrier"],   val_s)],
            [Paragraph("MAILING ADDRESS",   label_s), Paragraph(_info["mailing_address"], val_s),
             Paragraph("PREPARED BY",       label_s), Paragraph(f"primble.com · {generated_at}", small_s)],
        ]
        info_tbl = Table(info_rows, colWidths=[1.2*inch, 2.25*inch, 1.3*inch, 2.25*inch])
        info_tbl.setStyle(TableStyle([
            ("ROWBACKGROUNDS", (0,0), (-1,-1), [LIGHT, WHITE]),
            ("LEFTPADDING",    (0,0), (-1,-1), 8),
            ("RIGHTPADDING",   (0,0), (-1,-1), 8),
            ("TOPPADDING",     (0,0), (-1,-1), 5),
            ("BOTTOMPADDING",  (0,0), (-1,-1), 5),
            ("GRID",           (0,0), (-1,-1), 0.25, BORDER),
        ]))
        story.append(info_tbl)
        story.append(Spacer(1, 0.14*inch))

        # ── SQS TABLE ────────────────────────────────────────────────────────
        story.append(Paragraph("Submission Quality Scores (SQS)", h2_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
        story.append(Spacer(1, 0.06*inch))

        # Plain words only: a routing CODE never prints, and the grade and tier
        # are read off the score by the one ladder (see `grade_and_tier`).
        sqs_header = [
            Paragraph(f"<b>{h}</b>", S("TH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold"))
            for h in ["Form", "Score", "Grade", "Tier", "Routing"]
        ]
        sqs_rows = [sqs_header]

        if sqs_results:
            for fid, sqs in sqs_results.items():
                score   = sqs.get("sqs_score", 0) if sqs else 0
                sc      = sqs_color(score)
                routing = routing_label(sqs.get("routing_decision") if sqs else None)
                grade, tier = grade_and_tier(score)
                sqs_rows.append([
                    Paragraph(fid.replace("_", " "),  S("Cell", fontSize=8,  fontName="Helvetica")),
                    Paragraph(f"<b>{score}/100</b>",   S("Cell", fontSize=9,  fontName="Helvetica-Bold", textColor=sc)),
                    Paragraph(grade,                    S("Cell", fontSize=8,  fontName="Helvetica-Bold", textColor=sc)),
                    Paragraph(tier,                     S("Cell", fontSize=7,  fontName="Helvetica")),
                    Paragraph(routing,                  S("Cell", fontSize=7,  fontName="Helvetica")),
                ])
        # THE SCORE THE APP SHOWS (1 Oct 2026, owner: "score during download should
        # be exactly same on the cover page of individual form or whole package as
        # of the sqs section"). The table listed each form's score, and the TOTAL
        # PACKAGE SCORE the SQS panel headlines appeared only inside the model's
        # paragraph. The same stored number now prints as its own row, labelled
        # as the panel labels it, on every cover that has one.
        _pkg_score = (package_sqs or {}).get("package_sqs_score")
        if _pkg_score is not None and package_label not in (sqs_results or {}):
            sc = sqs_color(_pkg_score)
            grade, tier = grade_and_tier(_pkg_score)
            sqs_rows.append([
                Paragraph(f"<b>{package_label}</b>", S("Cell", fontSize=8,  fontName="Helvetica-Bold")),
                Paragraph(f"<b>{_pkg_score}/100</b>", S("Cell", fontSize=9,  fontName="Helvetica-Bold", textColor=sc)),
                Paragraph(grade,                       S("Cell", fontSize=8,  fontName="Helvetica-Bold", textColor=sc)),
                Paragraph(tier,                        S("Cell", fontSize=7,  fontName="Helvetica")),
                Paragraph(routing_label((package_sqs or {}).get("routing_decision")),
                          S("Cell", fontSize=7,  fontName="Helvetica")),
            ])
        if len(sqs_rows) == 1:
            sqs_rows.append([
                Paragraph("No SQS data", S("Cell", fontSize=8, fontName="Helvetica")),
                Paragraph("—", S("Cell", fontSize=8, fontName="Helvetica")),
                Paragraph("—", S("Cell", fontSize=8, fontName="Helvetica")),
                Paragraph("—", S("Cell", fontSize=8, fontName="Helvetica")),
                Paragraph("—", S("Cell", fontSize=8, fontName="Helvetica")),
            ])

        sqs_tbl = Table(sqs_rows, colWidths=[1.6*inch, 0.75*inch, 0.65*inch, 1.4*inch, 2.6*inch])
        sqs_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,0),  NAVY),
            ("ROWBACKGROUNDS",(0,1), (-1,-1), [WHITE, LIGHTER]),
            ("LEFTPADDING",   (0,0), (-1,-1), 7),
            ("RIGHTPADDING",  (0,0), (-1,-1), 7),
            ("TOPPADDING",    (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
            ("GRID",          (0,0), (-1,-1), 0.25, BORDER),
        ]))
        story.append(sqs_tbl)
        story.append(Spacer(1, 0.10*inch))

        # ── RED FLAGS (Lite only — when hard/soft stops are provided) ─────────
        if hard_stops or soft_stops:
            story.append(Paragraph("Red Flags & Warnings", h2_style))
            story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
            story.append(Spacer(1, 0.06*inch))
            if hard_stops:
                flag_rows = [[
                    Paragraph("<b>CRITICAL - Hard Stops</b>",
                              S("FlagHdr", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")),
                ]]
                for stop in hard_stops:
                    flag_rows.append([Paragraph(f"• {stop}", S("FlagRow", fontSize=8, textColor=colors.HexColor("#7f1d1d"), fontName="Helvetica"))])
                flag_tbl = Table(flag_rows, colWidths=[7.0*inch])
                flag_tbl.setStyle(TableStyle([
                    ("BACKGROUND",    (0,0), (-1,0),  colors.HexColor("#ef4444")),
                    ("ROWBACKGROUNDS",(0,1), (-1,-1), [colors.HexColor("#fef2f2"), WHITE]),
                    ("LEFTPADDING",   (0,0), (-1,-1), 8),
                    ("RIGHTPADDING",  (0,0), (-1,-1), 8),
                    ("TOPPADDING",    (0,0), (-1,-1), 5),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 5),
                    ("GRID",          (0,0), (-1,-1), 0.25, BORDER),
                ]))
                story.append(flag_tbl)
                story.append(Spacer(1, 0.07*inch))
            if soft_stops:
                warn_rows = [[
                    Paragraph("<b>WARNINGS - Soft Stops</b>",
                              S("WarnHdr", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")),
                ]]
                for stop in soft_stops:
                    warn_rows.append([Paragraph(f"• {stop}", S("WarnRow", fontSize=8, textColor=colors.HexColor("#78350f"), fontName="Helvetica"))])
                warn_tbl = Table(warn_rows, colWidths=[7.0*inch])
                warn_tbl.setStyle(TableStyle([
                    ("BACKGROUND",    (0,0), (-1,0),  colors.HexColor("#f59e0b")),
                    ("ROWBACKGROUNDS",(0,1), (-1,-1), [colors.HexColor("#fffbeb"), WHITE]),
                    ("LEFTPADDING",   (0,0), (-1,-1), 8),
                    ("RIGHTPADDING",  (0,0), (-1,-1), 8),
                    ("TOPPADDING",    (0,0), (-1,-1), 5),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 5),
                    ("GRID",          (0,0), (-1,-1), 0.25, BORDER),
                ]))
                story.append(warn_tbl)
                story.append(Spacer(1, 0.10*inch))

        # ── SQS REASONING ────────────────────────────────────────────────────
        if sqs_reasoning and sqs_reasoning.strip():
            story.append(Paragraph("SQS Score Explanation", h2_style))
            story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
            story.append(Spacer(1, 0.05*inch))
            story.append(Paragraph(sqs_reasoning.strip(), reasoning_s))
            story.append(Spacer(1, 0.10*inch))

        # ── NARRATIVE ────────────────────────────────────────────────────────
        story.append(Paragraph("Package Summary", h2_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
        story.append(Spacer(1, 0.05*inch))
        for para_text in narrative.split("\n"):
            para_text = para_text.strip()
            if para_text:
                story.append(Paragraph(para_text, body_style))
                story.append(Spacer(1, 0.04*inch))
        story.append(Spacer(1, 0.10*inch))

        # ── PACKAGE INTEGRITY (file checksums) ───────────────────────────────
        # SHA-256 fingerprint of each generated form so a recipient can confirm the
        # file was not altered after Primble produced it. The cover cannot hash the
        # zip it lives inside, so the checksums cover the filled form PDFs only.
        if file_manifest:
            hash_style = S("Hash", fontSize=6.5, textColor=TEXT_MAIN, fontName="Courier", leading=9)
            story.append(Paragraph("Package Integrity", h2_style))
            story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
            story.append(Spacer(1, 0.05*inch))
            story.append(Paragraph(
                "SHA-256 fingerprint of each generated file. Recompute the hash of a file "
                "to verify it has not been altered since generation.",
                small_s,
            ))
            story.append(Spacer(1, 0.05*inch))
            integ_rows = [[
                Paragraph("<b>File</b>",    S("IH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")),
                Paragraph("<b>SHA-256</b>", S("IH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")),
            ]]
            for item in file_manifest:
                integ_rows.append([
                    Paragraph(str(item.get("filename", "")), S("IFile", fontSize=7.5, fontName="Helvetica")),
                    Paragraph(str(item.get("sha256", "")),   hash_style),
                ])
            integ_tbl = Table(integ_rows, colWidths=[2.2*inch, 4.8*inch])
            integ_tbl.setStyle(TableStyle([
                ("BACKGROUND",    (0,0), (-1,0),  NAVY),
                ("ROWBACKGROUNDS",(0,1), (-1,-1), [WHITE, LIGHTER]),
                ("LEFTPADDING",   (0,0), (-1,-1), 7),
                ("RIGHTPADDING",  (0,0), (-1,-1), 7),
                ("TOPPADDING",    (0,0), (-1,-1), 4),
                ("BOTTOMPADDING", (0,0), (-1,-1), 4),
                ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
                ("GRID",          (0,0), (-1,-1), 0.25, BORDER),
            ]))
            story.append(integ_tbl)
            if package_checksum:
                story.append(Spacer(1, 0.04*inch))
                story.append(Paragraph(
                    f'<b>Package checksum (SHA-256):</b> <font face="Courier">{package_checksum}</font>',
                    small_s,
                ))
            story.append(Spacer(1, 0.10*inch))

        # ── A2A DISCLAIMER ───────────────────────────────────────────────────
        # Plain text only — no emoji, safe for all ReportLab font encodings
        disclaimer_text = (
            "IMPORTANT - Hidden within this page is carrier-grade AI-to-AI (A2A) data "
            "that is invisible to human readers but interpretable by next-generation carrier "
            "AI ingestion engines. Please include this page in your underwriting submission "
            "package for a faster and more robust submission experience."
        )
        disclaimer_label = Paragraph(
            "<b>[A2A]</b>",
            S("DLbl", fontSize=8, textColor=PINK, fontName="Helvetica-Bold"),
        )
        disclaimer_body = Paragraph(disclaimer_text, disclaimer_s)

        disclaimer_data = [[disclaimer_label, disclaimer_body]]
        disclaimer_tbl = Table(disclaimer_data, colWidths=[0.45*inch, 6.55*inch])
        disclaimer_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), PINK_LIGHT),
            ("LEFTPADDING",   (0,0), (-1,-1), 8),
            ("RIGHTPADDING",  (0,0), (-1,-1), 8),
            ("TOPPADDING",    (0,0), (-1,-1), 7),
            ("BOTTOMPADDING", (0,0), (-1,-1), 7),
            ("VALIGN",        (0,0), (-1,-1), "TOP"),
            ("LINEABOVE",     (0,0), (-1,-1), 1, PINK),
            ("LINEBELOW",     (0,0), (-1,-1), 1, PINK),
        ]))
        story.append(disclaimer_tbl)
        story.append(Spacer(1, 0.10*inch))

        # ── HIDDEN A2A JSON BLOCK ─────────────────────────────────────────────
        if ai_block:
            ai_json_str   = json.dumps(ai_block, indent=2, default=str)
            wrapped_lines = []
            for line in ai_json_str.split("\n"):
                wrapped_lines.extend(
                    textwrap.wrap(line, width=110, subsequent_indent="    ")
                    if len(line) > 110 else [line]
                )
            hidden_text = (
                "\n".join(wrapped_lines)
                .replace("\n", "<br/>")
                .replace(" ", "&nbsp;")
            )
            story.append(Paragraph(hidden_text, hidden_style))
            story.append(Spacer(1, 0.06*inch))

        # ── FOOTER ───────────────────────────────────────────────────────────
        footer_data = [[
            Paragraph(
                'Generated by <font color="#e6007a"><b>primble.com</b></font> - AI-powered ACORD form automation',
                S("Ft", fontSize=7, textColor=TEXT_HINT, fontName="Helvetica"),
            ),
            Paragraph(
                f"Confidential - {generated_at}",
                S("FtR", fontSize=7, textColor=TEXT_HINT, fontName="Helvetica", alignment=TA_RIGHT),
            ),
        ]]
        footer_tbl = Table(footer_data, colWidths=[3.5*inch, 3.5*inch])
        footer_tbl.setStyle(TableStyle([
            ("TOPPADDING",  (0,0), (-1,-1), 6),
            ("LINEABOVE",   (0,0), (-1,-1), 0.5, BORDER),
        ]))
        story.append(footer_tbl)

        doc.build(story)
        buf.seek(0)
        result = buf.getvalue()
        if not result or len(result) < 100:
            raise ValueError("build produced empty PDF")
        return result

    except ImportError as ie:
        logger.error(f"ReportLab not installed: {ie}")
        return _build_cover_page_fallback(facts, sqs_results, form_ids, org_name, narrative, ai_block, generated_at, flags=flags)
    except Exception as ex:
        logger.error(f"Cover page build error: {ex}", exc_info=True)
        return _build_cover_page_fallback(facts, sqs_results, form_ids, org_name, narrative, ai_block, generated_at, flags=flags)


def _build_cover_page_fallback(facts, sqs_results, form_ids, org_name, narrative, ai_block, generated_at, flags=None) -> bytes:
    """Plain-text PDF fallback when ReportLab fails."""
    try:
        lines = [
            "PRIMBLE SUBMISSION PACKAGE COVER PAGE",
            f"Generated: {generated_at}",
            f"Prepared by: {org_name}",
            f"Applicant: {_fv(facts, 'applicant_name') or 'Unknown'}",
            f"Agency: {org_name}",
            f"Effective Date: {_fv(facts, 'effective_date') or '---'}",
            f"Lines of Business: {', '.join(_cover_lines_of_business(facts, flags)) or '---'}",
            f"Forms: {', '.join(_cover_form_label(f) for f in form_ids)}",
            "",
            "SQS SCORES:",
        ]
        for fid, sqs in (sqs_results or {}).items():
            score = sqs.get("sqs_score", 0) if sqs else 0
            grade = grade_and_tier(score)[0]
            lines.append(f"  {fid}: {score}/100 ({grade})")
        lines += ["", "SUMMARY:", (narrative or "No narrative available.")[:800]]

        page_content = "BT /F1 10 Tf 40 750 Td 14 TL\n"
        for line in lines[:60]:
            safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            page_content += f"({safe}) Tj T*\n"
        page_content += "ET"

        page_content_bytes = page_content.encode("latin-1", errors="replace")
        content_len = len(page_content_bytes)

        pdf = (
            b"%PDF-1.4\n"
            b"1 0 obj\n<</Type /Catalog /Pages 2 0 R>>\nendobj\n"
            b"2 0 obj\n<</Type /Pages /Kids [3 0 R] /Count 1>>\nendobj\n"
            b"3 0 obj\n<</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources <</Font <</F1 5 0 R>>>>>>\nendobj\n"
            + f"4 0 obj\n<</Length {content_len}>>\nstream\n".encode()
            + page_content_bytes
            + b"\nendstream\nendobj\n"
            b"5 0 obj\n<</Type /Font /Subtype /Type1 /BaseFont /Helvetica>>\nendobj\n"
            b"xref\n0 6\n0000000000 65535 f \n"
            b"trailer\n<</Size 6 /Root 1 0 R>>\n"
            b"%%EOF"
        )
        return pdf
    except Exception as ex:
        logger.error(f"Fallback cover page error: {ex}")
        return (
            b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
            b"xref\n0 4\ntrailer<</Size 4/Root 1 0 R>>\n%%EOF"
        )