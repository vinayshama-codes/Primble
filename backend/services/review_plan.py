"""review_plan.py - THE REVIEW PAGE'S POINTS, ONE ORDERED PLAN (owner, 23-24 Oct 2026).

THE CONFUSION THIS ENDS. The pre-form review page printed a number on every item -
a key detail, a hard stop, a warning, a Recommendations row, a document row - and
the numbers changed under the person as they worked: a key detail showed 0 and
moved +3, a warning showed 11 and moved +3, a row showed 1 and then 0, and an item
appeared only after another was fixed. The numbers were shares of the right total
handed out "biggest lone gain first", while a person works DOWN THE PAGE; pillar
floors and the 60 / 85 holds make each answer's worth depend on what was done
before it, so the numbers only held in an order nobody follows.

THE MODEL (one door):

  1. ONE ordered plan of every step the page offers, in RAIL ORDER:
       Overview (the missing key details, as listed) -> Documents (the "Mark as
       Loss runs" rows) -> Data Consistency (a pick that releases a hold) ->
       Hard Stops -> Warnings -> Recommendations (`top_recommendations`, Loss
       History's steps in their own plan order) -> the document upload row.
  2. Each step's number is what the package score gains when it is done after
     every step above it - simulated on a copy with the stops as they would
     stand (`stops_now`) and the package scorer itself, with the page's own
     answers as probes (`probe_value`, a table probe, a narrative probe, a type
     flip, the complete loss runs). The numbers add up to exactly 100 minus the
     score: the floats are rounded together (largest remainder, every step that
     adds something shows at least a point while the total allows it), and what
     no step adds goes to the upload row - or, with none, is listed as a gap no
     item on the page can close.
  3. Holds: a step whose gain a 60 / 85 hold withholds at its position shows
     what it adds THERE; with nothing it says "Counts once <the hold> is fixed".
     The hold's own card shows the release.
  4. One fix, one number: a fix offered in two places counts once, at its first
     place in page order; the later place mirrors that number (`mirror_of`) and
     adds nothing to the total.
  5. Every step is visible from the start (the stops raise them; the Loss History
     plan lists every step it will take).

Pure: reads the session ROW and the fresh package score, never writes, never
calls a model.

AFTER FORMS TOO (owner, 29 Oct 2026: "the points shown on items always add up
to exactly 100 - score, after forms are generated too"). Once forms exist the
stops are the post-generation ones (`stops_now(pre_form=False)`, scoped to the
selected + generated forms, as `arq_service.recalculate_session_scores` scores
them) and the number on screen is the stored, credit-bearing package score: a
dismissal credit still in force is added on every copy and retires on the copy
the moment its field is answered (`audit_service.credits_in_force`), exactly as
the recalculation does. Before forms nothing changes.
"""

from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

RENDERED_WARNING_TIERS = ("required", "recommended", "binder_followup")
NARRATIVE_FACT = "additional_remarks_text"
HARD_STOPS_ROW = "hard_stops_present"
_EPS = 1e-6

# The probe values a person's answer is stood in by, by the shape the fact's name
# says it holds. A value the fact's own answer check refuses is never used.
_SHAPE_PROBES: Tuple[Tuple[str, str], ...] = (
    ("email", "probe@example.com"),
    ("website", "www.example.com"),
    ("phone", "303-555-0100"),
    ("fax", "303-555-0101"),
    ("fein", "12-3456789"),
    ("address", "100 Probe Street, Denver, CO 80202"),
    ("date", "01/15/2027"),
    ("year", "2005"),
    ("state", "CO"),
)
# A neutral description: names no industry, so no operations / class-code check
# can read a verdict into it that the person's real words would not.
_NEUTRAL_TEXT = "Answered by the producer."
# A GL class code no industry table maps - "no verdict" by the scorer's own rule
# (`sqs_service._codes_to_industry`, rule 3).
_NEUTRAL_CLASS_CODE = "99999"
_COLUMN_PROBES: Dict[str, str] = {
    "date": "01/15/2015", "year": "2005", "state": "CO", "number": "10",
    "currency": "100000", "percent": "100", "vin": "1FTFW1ET5DFC10312", "code": _NEUTRAL_CLASS_CODE,
}
_COLUMN_NAME_PROBES: Dict[str, str] = {
    "name": "Probe Person", "description": _NEUTRAL_TEXT, "classification": _NEUTRAL_TEXT,
    "location": "001", "line_of_business": "General Liability", "zip": "80202",
}


# ── What a fix opens (the page's own rule, `recommendations.js` fixKeys) ─────
def fix_keys(resolution: Any) -> List[str]:
    """A fix window's targets as keys: `fact:<fact>` for a typed fact (and the
    remarks box), `col:<table>:<column>` for named cells, `table:<table>` for a
    whole table - the same keys the page compares (`fixKeys`)."""
    res = resolution if isinstance(resolution, dict) else None
    if not res:
        return []
    keys: List[str] = []
    facts = [str(f).strip() for f in (res.get("facts") or []) if str(f or "").strip()]
    mode = res.get("mode")
    if mode == "field":
        keys += [f"fact:{f}" for f in facts]
    elif mode == "narrative":
        keys.append(f"fact:{NARRATIVE_FACT}")
    elif mode == "schedule" and str(res.get("schedule_key") or "").strip():
        sk = str(res["schedule_key"]).strip()
        cols = [str(c).strip() for c in (res.get("columns") or []) if str(c or "").strip()]
        keys += [f"col:{sk}:{c}" for c in cols] if cols else [f"table:{sk}"]
        keys += [f"fact:{f}" for f in facts]
        keys += [f"fact:{str(f).strip()}" for f in (res.get("derives") or []) if str(f or "").strip()]
    return list(dict.fromkeys(keys))


def _key_covered(key: str, covered: set) -> bool:
    if key in covered:
        return True
    if key.startswith("table:"):
        sk = key[6:]
        return any(k.startswith(f"col:{sk}:") for k in covered)
    return False


def all_covered(keys: Iterable[str], covered: set) -> bool:
    keys = list(keys)
    return bool(keys) and all(_key_covered(k, covered) for k in keys)


def rendered_cards(grouped: Any) -> List[dict]:
    """Every card the review page draws, in its order (`keyDetailCards.
    renderedCardRows`): the hard-stop clusters, then the warning tiers."""
    out: List[dict] = []

    def take(clusters: Any, page: str) -> None:
        for c in clusters if isinstance(clusters, list) else []:
            if not isinstance(c, dict):
                continue
            items = c.get("items") if isinstance(c.get("items"), list) and c.get("items") else [c]
            for it in items:
                if isinstance(it, dict):
                    out.append({"page": page, "code": it.get("code") or c.get("code"),
                                "message": it.get("message") or c.get("message") or "",
                                "issue_id": it.get("issue_id"),
                                "resolution": it.get("resolution") or c.get("resolution")})

    g = grouped if isinstance(grouped, dict) else {}
    take(g.get("hard_stops"), "hardstops")
    warnings = g.get("warnings") if isinstance(g.get("warnings"), dict) else {}
    for tier in RENDERED_WARNING_TIERS:
        take(warnings.get(tier), "warnings")
    return out


# ── Probes ───────────────────────────────────────────────────────────────────
def _fv(facts: Any, key: str) -> Any:
    raw = (facts or {}).get(key) if isinstance(facts, dict) else None
    return raw.get("value") if isinstance(raw, dict) and "value" in raw else raw


def _accepts(fact: str, value: Any) -> bool:
    try:
        from services.fact_registry import FACT_REGISTRY, answer_check
        check = answer_check(FACT_REGISTRY.get(fact))
        return not callable(check) or bool(check(value))
    except Exception:                                          # noqa: BLE001
        return True


# DATES ARE PROBED AS A PERSON WOULD ANSWER THEM (27 Oct 2026, random-package
# solver): every date box took "01/15/2027", so a card holding the term's two
# dates answered itself with a term that ends the day it starts - the
# backwards-term hard stop held 60 - and a business start date, a retro date or
# a prior term read as a date still to come. The proposed term starts on the
# first of the month two months out (or one year before a stated expiration
# still to come) and runs one year; an umbrella term follows the proposed one;
# the prior term ends where the proposed one starts; every other date is in the
# past. Each probe still passes the fact's own answer check.
_PAST_DATE_PROBE = "01/15/2015"


def _date_probe(fact: str, facts: dict) -> Optional[str]:
    if "date" not in str(fact or "").lower():
        return None
    from datetime import date
    from services.normalization import normalize_date

    def held(key: str):
        iso = normalize_date(str(_fv(facts, key) or "")) if _fv(facts, key) else None
        try:
            return date.fromisoformat(iso) if iso else None
        except ValueError:
            return None

    def years_on(d, n: int):
        try:
            return d.replace(year=d.year + n)
        except ValueError:                                     # 29 Feb
            return d.replace(year=d.year + n, day=28)

    def text(d) -> str:
        return d.strftime("%m/%d/%Y")

    today = date.today()
    first = date(today.year + (today.month + 1) // 12, (today.month + 1) % 12 + 1, 1)
    eff, exp = held("effective_date"), held("expiration_date")
    start = eff if eff and (not exp or eff < exp) else None
    if fact == "effective_date":
        # A renewal starts the day the prior term ends (30 Oct 2026, CH125: with
        # the pair backwards, "a year before the expiration" was a past date).
        p_end = held("prior_expiration_date")
        if p_end and (p_end - today).days >= -30:
            value = p_end
        else:
            value = years_on(exp, -1) if exp and exp > today and (not eff or eff < exp) else first
    elif fact == "expiration_date":
        # (strict review, 29 Oct 2026) One year on from an effective date that
        # is long past is an ENDED term: the route refuses that save
        # (`validators.term_save_refusal`), so the plan's step did nothing and
        # its card's points sat on no item (an unreadable expiration "2027"
        # beside a 03/15/2024 start: P2 short by 15). A person types an
        # expiration still to come - the next term's.
        value = years_on(eff or first, 1)
        if value < today:
            value = years_on(first, 1)
    elif fact == "umbrella_effective_date":
        value = start or first
    elif fact == "umbrella_expiration_date":
        u_eff = held("umbrella_effective_date")
        value = years_on(u_eff, 1) if u_eff else (exp if start and exp else years_on(first, 1))
    elif fact == "prior_expiration_date":
        value = start or first
    elif fact == "prior_effective_date":
        p_exp = held("prior_expiration_date")
        value = years_on(p_exp or start or first, -1)
    elif fact == "builders_risk_completion_date":
        value = years_on(start or first, 1)
    elif fact == "wc_xmod_effective_date":
        value = start or first
    else:
        return _PAST_DATE_PROBE if _accepts(fact, _PAST_DATE_PROBE) else None
    return text(value) if _accepts(fact, text(value)) else None


def _neutral_naics() -> str:
    """A valid NAICS code whose sector no industry table maps (no verdict)."""
    try:
        from services import sqs_service as S
        mapped = set(getattr(S, "_NAICS_SECTOR_INDUSTRY", {}) or {})
        for prefix in sorted(getattr(S, "_VALID_NAICS_PREFIXES", ()) or ()):
            if prefix not in mapped:
                return f"{prefix}1110"[:6]
    except Exception:                                          # noqa: BLE001
        pass
    return "561110"


# A box the documents print one value for is answered with that value (27 Oct
# 2026): a person types the truth, and the truth is what the documents say - a
# made-up applicant name or FEIN started a Data Consistency conflict the person's
# real answer never would. Only a merged gap, only one value across the active
# documents, never another insured's.
def _documents_value(fact: str, facts: dict, session: Optional[dict]) -> Optional[str]:
    if not session or _fv(facts, fact):
        return None
    seen: Dict[str, str] = {}
    for doc in session.get("docs") or []:
        if not isinstance(doc, dict) or doc.get("excluded") or doc.get("supporting_only"):
            continue
        value = _fv(doc.get("facts") or {}, fact)
        if isinstance(value, (str, int, float)) and str(value).strip():
            seen.setdefault(" ".join(str(value).lower().split()), str(value).strip())
    if len(seen) != 1:
        return None
    value = next(iter(seen.values()))
    return value if _accepts(fact, value) else None


# A person whose package holds claims writes and answers as someone who had
# claims (27 Oct 2026, random-package solver): the narrative window's first
# loss phrase is "no reported losses", and writing it beside claims on file
# raised the narrative / claims-answer warning, whose answer then conflicted
# with the claims - round after round. "claims" when the package asserts one
# (`loss_history_state.asserted_claims`), else None.
def _claims_on_file(facts: dict) -> Optional[str]:
    try:
        from services.loss_history_state import asserted_claims
        return "claims" if (asserted_claims(facts or {})[0] or 0) > 0 else None
    except Exception:                                          # noqa: BLE001
        return None


def _payroll_within_revenue(payroll: float, revenue: Optional[float]) -> float:
    """A sample payroll the package's own checks accept beside the stated one:
    within 10% of it (`wc_state_payroll_total_mismatch` - 20% for
    `wc_payroll_mismatch`) and no more than 85% of revenue
    (`wc_payroll_vs_revenue`). When the stated figures leave no such value the
    stated payroll is kept - the documents disagree, not the sample."""
    if not revenue or revenue <= 0:
        return payroll
    cap = int(revenue * 0.85)
    if payroll <= cap:
        return payroll
    return float(cap) if cap >= payroll * 0.9 else payroll


def probe_value(fact: str, facts: Optional[dict] = None, session: Optional[dict] = None) -> str:
    """The value a person's answer to `fact` is stood in by - what a producer
    would really type (27 Oct 2026): a choice the fact offers, a limit at the
    scorer's own threshold (also over a stated limit below it - the limit
    applied for), the one value the documents print for it, a revenue /
    payroll the package's own ratio check accepts, a date that keeps the term
    whole, the fact's declared example (`fact_registry.example_answer`), a
    value of the shape its name says, else the scorer's own probe
    (`sqs_service._package_probe_answer`)."""
    from services import sqs_service as S
    facts = facts or {}
    low = str(fact or "").lower()
    # The claims question is stood in by the answer the person's own narrative
    # gives (24 Oct 2026): the other one raises `legacy_loss_narrative_mismatch`.
    if fact == "loss_history_no_prior_losses_indicator":
        try:
            from services.loss_history_state import claims_answer_for_narrative, claims_question_answers
            agreed = claims_answer_for_narrative(facts)
            if agreed:
                return agreed
            if _claims_on_file(facts):
                return claims_question_answers()[1]
        except Exception:                                      # noqa: BLE001
            pass
    try:
        from services.answer_options import OTHER, options_for
        for opt in options_for(fact) or []:
            if opt != OTHER and _accepts(fact, opt):
                return opt
    except Exception:                                          # noqa: BLE001
        pass
    thresholds = getattr(S, "_THRESHOLD_PROBE_FACTS", {}) or {}
    if fact in thresholds:
        held = S._to_float(_fv(facts, fact))
        if not held or held < thresholds[fact]:
            return str(int(thresholds[fact]))
        return str(_fv(facts, fact))                 # a limit that meets it is confirmed
    printed = _documents_value(fact, facts, session)
    if printed:
        return printed
    if fact == "naics_code":
        return _neutral_naics()
    if fact == "sic_code":
        return "8999"
    if fact in ("operations_description", "description_of_operations"):
        return _NEUTRAL_TEXT
    if fact == "total_revenue":
        pay = S._to_float(_fv(facts, "total_payroll") or _fv(facts, "wc_payroll"))
        return str(int(pay * 1.25)) if pay and pay > 0 else "1000000"
    if fact == "num_employees":
        # A package that carries no workers comp stands in a head count its
        # coverage agrees with (30 Oct 2026, rule G2): the sample "25" beside no
        # WC policy raised "Employees are listed but no workers comp coverage is
        # carried" - an item the sample made. A person with more employees and
        # no WC still gets that question; the plan's own answer does not.
        try:
            flags_now = (session or {}).get("flags") or {}
            if not S._wc_carried(flags_now):
                return "5"
        except Exception:                                      # noqa: BLE001
            pass
    if fact in ("total_payroll", "wc_payroll"):
        # The payroll the package already states is the person's answer (30 Oct
        # 2026, rule G2): a total payroll typed beside a WC payroll / per-state
        # payroll it disagrees with raised `wc_payroll_mismatch` /
        # `wc_state_payroll_total_mismatch` - an item the sample made, not the
        # package. The other payroll first, then the per-state total.
        other = S._to_float(_fv(facts, "wc_payroll" if fact == "total_payroll" else "total_payroll"))
        if not other or other <= 0:
            by_state = _fv(facts, "wc_payroll_by_state")
            vals = (list(by_state.values()) if isinstance(by_state, dict)
                    else by_state if isinstance(by_state, list) else [])
            other = sum((S._to_float(v.get("payroll") if isinstance(v, dict) else v) or 0)
                        for v in vals)
        rev_now = S._to_float(_fv(facts, "total_revenue"))
        if other and other > 0:
            fitted = _payroll_within_revenue(other, rev_now)
            # A stated payroll the revenue cannot carry is the documents' own
            # disagreement: the sample does not repeat it (a card asking to
            # correct the payroll must be answerable).
            # A WC payroll follows the stated total either way (the revenue box
            # beside it on the ratio card carries the rest); a TOTAL payroll
            # follows the WC payroll only where the revenue can carry it.
            if fact == "wc_payroll" or not rev_now or fitted <= rev_now * 0.85:
                return str(int(fitted))
        rev = S._to_float(_fv(facts, "total_revenue"))
        return str(int(rev * 0.5)) if rev and rev > 0 else "500000"
    dated = _date_probe(fact, facts)
    if dated:
        return dated
    try:
        from services.fact_registry import example_answer
        example = example_answer(fact)
        if example:
            return example
    except Exception:                                          # noqa: BLE001
        pass
    for needle, value in _SHAPE_PROBES:
        if needle in low and _accepts(fact, value):
            return value
    value, _valid = S._package_probe_answer(fact, stated=bool(_fv(facts, fact)))
    return str(value)


def _column_probe(col: dict) -> str:
    opts = [o for o in (col.get("options") or []) if o and o != "Other"]
    if opts:
        return str(opts[0])
    key = str(col.get("key") or "")
    for needle, value in _COLUMN_NAME_PROBES.items():
        if needle in key:
            return value
    return _COLUMN_PROBES.get(str(col.get("type") or "text"), "Probe value")


# ── The simulation ───────────────────────────────────────────────────────────
class _Sim:
    """A copy of the session the steps are done on, one after another."""

    def __init__(self, row: dict, credit_rows: Optional[List[dict]] = None):
        self.session = dict(row or {})
        self.session["facts"] = dict((row or {}).get("facts") or {})
        self.session["flags"] = dict((row or {}).get("flags") or {})
        self.session["docs"] = [dict(d) if isinstance(d, dict) else d
                                for d in ((row or {}).get("docs") or [])]
        # The page's own facts, for the recommender's "did the answer move it?"
        self._base_facts = dict((row or {}).get("facts") or {})
        self._base_flags = dict((row or {}).get("flags") or {})
        self.suppressed: set = set()
        # The boxes this pass has answered: a later item naming the same box
        # leaves the person's answer as it is (27 Oct 2026).
        self.answered: set = set()
        # The plan's sample choice (`_best_sample`): boxes this step sampled
        # that may take another answer, and a forced answer while retrying.
        self.step_samples: List[Tuple[str, List[str]]] = []
        self.forced: Dict[str, str] = {}
        self.form_ids = [r.get("form_id") for r in ((row or {}).get("recommendations") or [])
                         if isinstance(r, dict) and r.get("form_id")]
        # After forms (29 Oct 2026): the recalculation's recipe - the stops
        # scoped to the selected + generated forms, the forms' own scores
        # passed through, and the dismissal credits still in force.
        generated = (row or {}).get("generated_forms") or {}
        self.pre_form = not generated
        self.form_results: List[dict] = []
        self.credit_rows: List[dict] = [r for r in (credit_rows or []) if isinstance(r, dict)]
        if not self.pre_form:
            selected = [str(f) for f in ((row or {}).get("selected_form_ids") or []) if f]
            self.form_ids = sorted(set(selected) | {str(f) for f in generated})
            self.form_results = [f.get("sqs") for f in generated.values()
                                 if isinstance(f, dict) and isinstance(f.get("sqs"), dict)]

    # The displayed score as a FLOAT (the weighted sum before it is rounded
    # down, held at the cap) and the hold that binds it.
    def _fingerprint(self) -> str:
        import json
        docs = [(d.get("doc_type"), d.get("excluded"), d.get("supporting_only"), d.get("doc_id"),
                 d.get("filename")) if isinstance(d, dict) else None
                for d in (self.session.get("docs") or [])]
        return json.dumps([self.session.get("facts"), self.session.get("flags"), docs,
                           sorted(self.suppressed), self.session.get("underwriting_confirmations")],
                          sort_keys=True, default=str)

    def measure(self) -> Tuple[float, float, Optional[int], Optional[str]]:
        # The same copy measured twice in a row is scored once (a sample answer
        # tried by `_best_sample` and then kept is not scored again).
        fp = self._fingerprint()
        cached = getattr(self, "_measured", None)
        if cached and cached[0] == fp:
            self.last_pkg, self.last_stops = cached[2], cached[3]
            return cached[1]
        from services import sqs_service as S
        from services.stops_now import stops_now
        facts, flags = self.session["facts"], self.session["flags"]
        if self.pre_form:
            self._refresh_recommended_forms()
        st = stops_now(self.session, self.form_ids, pre_form=self.pre_form, facts=facts, flags=flags)
        # The scorer takes its stops from the one door, unfiltered.
        pkg = S._PACKAGE_SCORER(
            facts=facts, flags=flags, form_results=self.form_results, cross_issues=st["cross_issues"],
            hard_stops=st["hard"], soft_stops=st["soft"], session_data=self.session,
            _probe=True, form_fill=False)
        self.last_pkg, self.last_stops = pkg, st
        raw = weighted_float(pkg.get("pillars") or {})
        # A dismissal credit is added to the raw score, then held at the cap
        # (`sqs_service.final_score_with_credits`) - after forms only.
        if self.credit_rows:
            raw = min(100.0, raw + float(self._credits()))
        cap, reason = _released_cap(pkg, st, self.suppressed)
        shown = min(raw, float(cap)) if cap is not None else raw
        out = (shown, raw, cap, reason)
        self._measured = (fp, out, pkg, st)
        return out

    def _refresh_recommended_forms(self) -> None:
        """THE FORM RECOMMENDER RE-RUNS ON THE COPY LIKE IT DOES ON THE ROW
        (strict review, 29 Oct 2026). Before forms, an answer the recommender
        reads changes the recommended forms (`arq_service.
        refreshed_pre_form_recommendations`, run by every answer door's
        recalculation), and the stops are scoped to those forms. The copy kept
        the page's list: "% subcontracted 25" added ACORD 186 and 126 for real,
        their checks took a point, and the row read +2 where the save moved +1.
        Same rule as the door: the recommender on the copy's facts against the
        page's own facts; only a change replaces the page's list. Never raises."""
        try:
            import json
            from services.arq_service import _recommended_forms_key
            from services.form_service import active_document_text, match_forms_deterministic
            facts, flags = self.session["facts"], self.session["flags"]
            fp = json.dumps([facts, flags], sort_keys=True, default=str)
            if getattr(self, "_recs_fp", None) == fp:
                return
            self._recs_fp = fp
            if getattr(self, "_recs_base", None) is None:
                self._recs_text = active_document_text(self.session)
                self._recs_base = (_recommended_forms_key(match_forms_deterministic(
                    self._base_facts, dict(self._base_flags), text=self._recs_text)),
                    list(self.session.get("recommendations") or []), list(self.form_ids))
            base_key, base_recs, base_ids = self._recs_base
            now = match_forms_deterministic(facts, dict(flags), text=self._recs_text)
            if _recommended_forms_key(now) == base_key:
                self.session["recommendations"], self.form_ids = base_recs, list(base_ids)
            else:
                self.session["recommendations"] = now
                self.form_ids = [r.get("form_id") for r in now if isinstance(r, dict) and r.get("form_id")]
        except Exception as exc:                               # noqa: BLE001
            logger.debug("review plan: recommended forms not refreshed: %s", exc)

    def _credits(self) -> int:
        """The dismissal credit still in force on this copy."""
        try:
            from services.audit_service import credits_in_force
            return int(credits_in_force(self.credit_rows, self.session["facts"], quiet=True)[0] or 0)
        except Exception:                                      # noqa: BLE001
            return 0

    # ── the writes, as the page's doors make them ──
    def answer(self, fact: str, value: str) -> bool:
        """A producer's typed answer (`arq_service.apply_producer_answer_to_session`):
        the envelope the answer means, the flags its writers mirror, the facts
        an answer re-derives. False when the copy already holds that answer."""
        from services import arq_service as A
        from services.answer_semantics import build_fact_envelope, interpret_answer
        facts, flags = self.session["facts"], self.session["flags"]
        canon = A._canonical_key(fact) or fact
        envelope = build_fact_envelope(canon, interpret_answer(canon, value), "producer", "filled")
        held = facts.get(canon)
        if (isinstance(held, dict) and held.get("value") == envelope.get("value")
                and held.get("value_state") == envelope.get("value_state")
                and held.get("source") == envelope.get("source")):
            return False
        facts[canon] = envelope
        self.answered.update({fact, canon})
        if canon == A.NO_LOSS_INDICATOR_FIELD:
            from services.sqs_service import _attested_true
            if _attested_true(value):
                flags["no_prior_losses"] = True
            elif flags.get("no_prior_losses"):
                flags["no_prior_losses"] = False
        elif canon == A.NEW_VENTURE_FIELD:
            from services.loss_history_state import new_venture_answer
            flags["new_venture_confirmed"] = new_venture_answer(value) is True
            A._apply_new_venture_derivations(facts, flags)
        A._rederive_answer_dependent_facts(facts)
        return True

    def table(self, key: str, res: dict) -> bool:
        """A saved table (`arq_service._write_schedule_rows`): the probe fills the
        columns the fix names on every row, or adds one complete row to an
        empty table. False when the copy's table is unchanged."""
        import json
        from services import arq_service as A, schedule_capture as SC
        facts = self.session["facts"]
        before = json.dumps(_fv(facts, key), sort_keys=True, default=str)
        if key == "loss_history":
            from services.claim_checks import probe_answer
            facts[key] = probe_answer(facts)
            return json.dumps(_fv(facts, key), sort_keys=True, default=str) != before
        spec = SC.get_def(key)
        cols = list(spec.get("columns") or []) if isinstance(spec, dict) else \
            list(getattr(spec, "columns", []) or [])
        cols = [c if isinstance(c, dict) else vars(c) for c in cols]
        shown = SC.rows_from_facts(key, facts)
        named = [str(c) for c in (res.get("columns") or [])]
        rows = [dict(r) for r in shown] if isinstance(shown, list) else []
        if named:
            for r in rows:
                for c in cols:
                    if c.get("key") in named and r.get(c["key"]) in (None, ""):
                        r[c["key"]] = _column_probe(c)
        elif rows:
            for r in rows:
                for c in cols:
                    if c.get("required") and r.get(c.get("key")) in (None, ""):
                        r[c["key"]] = _column_probe(c)
        else:
            rows = [{c["key"]: _column_probe(c) for c in cols if c.get("key")}]
        # A cell the identifier door calls impossible (`identifier_checks.
        # cell_is_impossible` - a VIN not 17 characters, a US ZIP not 5 / 9
        # digits) is what the person corrects in this window, so the probe
        # corrects it too - generically, by the door's own readers (30 Oct
        # 2026, live 8aa8f3ad: the plan could not clear the VIN warning and put
        # its points on another item).
        from services.identifier_checks import cell_is_impossible
        for r in rows:
            for c in cols:
                if r.get(c.get("key")) not in (None, "") and cell_is_impossible(key, c.get("key"), r):
                    r[c["key"]] = _column_probe(c)
        # A PAYROLL cell the probe fills adds up to the payroll the package
        # already states (30 Oct 2026, rule G2): a fixed sample beside a stated
        # total payroll raised `wc_payroll_mismatch` / `wc_state_payroll_total_
        # mismatch` - items the sample made, not the package. The cells the
        # probe filled share what the stated total leaves after the cells a
        # document or person already filled.
        self._fit_payroll_cells(cols, rows, shown)
        clean, _report = SC.validate_rows(key, rows, shown=shown)
        # Cells every building already states (`confirm_columns`): the real
        # window SAVES the table anyway (frontend `tableIsSaved`), and only that
        # save carries them to the package (`derive_package_cope`) - an
        # unchanged table is still a save here (live c5dc03ec, 25 Oct 2026).
        # The same holds for every table whose save DERIVES facts (28 Oct 2026
        # review: a complete WC class table re-derives `wc_payroll_by_state`,
        # which the multi-state check reads - an unchanged table was "nothing to
        # do" here, so the plan listed the card at 0 and the solver stalled at
        # 85, while the person's real save cleared it). So the save is tried on
        # a copy: it counts when it moves ANY fact (the rows, the person's mark
        # on them, a derived fact), and is then made for real.
        trial = copy.deepcopy(facts)
        A._write_schedule_rows(trial, key, clean, "producer")
        if json.dumps(trial, sort_keys=True, default=str) == json.dumps(facts, sort_keys=True, default=str):
            return False
        A._write_schedule_rows(facts, key, clean, "producer")
        return True

    def _fit_payroll_cells(self, cols: List[dict], rows: List[dict], shown: Any) -> None:
        from services import sqs_service as S
        pay_cols = [c.get("key") for c in cols if "payroll" in str(c.get("key") or "").lower()]
        if not pay_cols or not rows:
            return
        facts = self.session["facts"]
        target = S._to_float(_fv(facts, "wc_payroll") or _fv(facts, "total_payroll"))
        if not target or target <= 0:
            return
        _rev = S._to_float(_fv(facts, "total_revenue"))
        target = _payroll_within_revenue(target, _rev)
        if _rev and target > _rev * 0.85:
            return              # the documents' own disagreement - not repeated
        before = [dict(r) for r in (shown if isinstance(shown, list) else [])]
        filled, stated = [], 0.0
        for n, r in enumerate(rows):
            for k in pay_cols:
                was = before[n].get(k) if n < len(before) and isinstance(before[n], dict) else None
                if was in (None, "") and r.get(k) not in (None, ""):
                    filled.append((r, k))
                elif r.get(k) not in (None, ""):
                    stated += S._to_float(r.get(k)) or 0.0
        left = target - stated
        if not filled or left <= 0:
            return
        each = int(left // len(filled))
        for i, (r, k) in enumerate(filled):
            r[k] = str(each if i < len(filled) - 1 else int(left - each * (len(filled) - 1)))

    def narrative(self, gaps: List[dict]) -> bool:
        """The remarks a person writes in the narrative window, one sentence per
        topic it lists (`arq_service.append_producer_narrative`)."""
        from services.arq_service import compose_narrative_answer
        # Never words that contradict the claims answer (24 Oct 2026): "No
        # prior losses: ..." beside "we have had claims" is its own warning.
        try:
            from services.loss_history_state import claims_answer_stance, text_claims_stance
            answer = claims_answer_stance(self.session["facts"]) or _claims_on_file(self.session["facts"])
        except Exception:                                      # noqa: BLE001
            answer, text_claims_stance = None, (lambda _t: None)
        lines = []
        for g in gaps or []:
            phrases = [p for p in (g.get("phrases") or []) if p] if isinstance(g, dict) else []
            if answer:
                phrases = [p for p in phrases if text_claims_stance(p) in (None, answer)]
            words = phrases[0] if phrases else str((g or {}).get("label") or "")
            if words:
                lines.append(f"{words[:1].upper()}{words[1:]}: covered as described.")
        text = " ".join(lines) or _NEUTRAL_TEXT
        existing = self.session["facts"].get(NARRATIVE_FACT)
        combined = compose_narrative_answer(existing, text)
        if not self.answer(NARRATIVE_FACT, combined):
            return False
        # Like the real append (Z39 lane H): only the words the person typed are
        # theirs - a document's remarks it was appended to stay the document's.
        try:
            from services.arq_service import appended_typed_parts
            from services.loss_history_state import TYPED_PARTS_KEY
            env = self.session["facts"].get(NARRATIVE_FACT)
            if isinstance(env, dict):
                env[TYPED_PARTS_KEY] = appended_typed_parts(existing, text)
        except Exception:                                      # noqa: BLE001
            pass
        return True

    def explain(self, code: str) -> bool:
        """The card's code kept with the explanation (`audit_routes.resolve_issue`)."""
        from services.issue_registry import explained_issue_codes
        facts = self.session["facts"]
        codes = explained_issue_codes(facts)
        if not code or code in codes:
            return False
        facts["_explained_issue_codes"] = {"value": sorted(codes | {code}), "source": "producer",
                                           "confidence": "producer"}
        return True

    def mark(self, doc_index: int) -> bool:
        docs = self.session["docs"]
        if 0 <= doc_index < len(docs) and isinstance(docs[doc_index], dict) \
                and docs[doc_index].get("doc_type") != "loss_run":
            docs[doc_index] = {**docs[doc_index], "doc_type": "loss_run"}
            return True
        return False

    def upload_complete_runs(self, years: int) -> bool:
        """Carrier loss runs for `years` years, valued today, naming the insured
        and its FEIN - what the upload row asks for."""
        facts = self.session["facts"]
        today = datetime.now(timezone.utc).date()
        try:
            start = today.replace(year=today.year - years)
        except ValueError:                                     # 29 February
            start = today.replace(year=today.year - years, day=28)
        for key, value in (("loss_run_period_start", start.isoformat()),
                           ("loss_run_period_end", today.isoformat()),
                           ("loss_run_valuation_date", today.isoformat())):
            facts[key] = {"value": value, "source": "policy_doc_text", "confidence": "high"}
        facts.pop("loss_run_age_days", None)
        # The carrier's runs name the insured as the documents print it (rule
        # G2, 30 Oct 2026): copying the merged value onto them - a placeholder
        # FEIN "00-0000000", or a value no document prints, beside documents
        # printing 93-3688205 - raised a FEIN conflict the upload made, not the
        # package. A person's own (valid) value stands; else the one valid value
        # the active documents print; else the package's valid value; else none.
        run_facts = {}
        for k in ("applicant_name", "fein"):
            value = _fv(facts, k)
            ok = bool(value) and _accepts(k, value)
            try:
                from services.fact_state import put_by_person
                by_person = put_by_person(facts.get(k))
            except Exception:                                  # noqa: BLE001
                by_person = False
            if not (ok and by_person):
                printed = {" ".join(str(_fv((d or {}).get("facts") or {}, k)).lower().split()):
                           str(_fv((d or {}).get("facts") or {}, k)).strip()
                           for d in self.session.get("docs") or []
                           if isinstance(d, dict) and not d.get("excluded")
                           and not d.get("supporting_only")
                           and str(_fv(d.get("facts") or {}, k) or "").strip()}
                printed = {n: v for n, v in printed.items() if _accepts(k, v)}
                value = (next(iter(printed.values())) if len(printed) == 1
                         else value if ok else None)
            if value:
                run_facts[k] = {"value": value, "source": "policy_doc_text"}
        self.session["docs"] = list(self.session["docs"]) + [
            {"doc_type": "loss_run", "filename": "complete loss runs (probe)",
             "doc_id": "_probe_loss_runs", "facts": run_facts}]
        return True


def weighted_float(pillars: Dict[str, Any]) -> float:
    """The package score before it is rounded down: the six pillars' weighted
    sum, a Not Applicable pillar's weight spread over the rest
    (`sqs_service._weighted_pillar_sum` without the floor)."""
    from services.sqs_service import SPEC_PILLAR_WEIGHTS
    active = {k: (v.get("score") if isinstance(v, dict) else v) for k, v in (pillars or {}).items()}
    active = {k: float(v) for k, v in active.items() if v is not None and k in SPEC_PILLAR_WEIGHTS}
    total_w = sum(SPEC_PILLAR_WEIGHTS[k] for k in active)
    if total_w <= 0:
        return 0.0
    return max(0.0, min(100.0, round(sum(SPEC_PILLAR_WEIGHTS[k] * v for k, v in active.items())
                                     / total_w, 9)))


def _hold_label(reason: Optional[str]) -> str:
    text = str(reason or "").strip()
    for cut in (" - ", " (", ". ", ":"):
        if cut in text:
            text = text.split(cut, 1)[0]
    return text.strip(" .") or "the hard stop"


# ── The plan ─────────────────────────────────────────────────────────────────
def _loss_plan_probes(pkg: dict) -> Dict[str, str]:
    """{fact: probe} the Loss History plan answers with (`loss_history_plan`)."""
    out: Dict[str, str] = {}
    for s in (pkg or {}).get("loss_plan") or []:
        if isinstance(s, dict) and s.get("fact") and s.get("probe") is not None:
            out.setdefault(str(s["fact"]), str(s["probe"]))
    return out


def page_items(row: dict, pkg: dict, kd: Optional[dict], grouped: Optional[dict]) -> List[dict]:
    """Every step the review page offers, in rail order, with the fix it opens.
    Not yet weighed (`build_review_plan` does that)."""
    from services.review_recommendations import fix_route_for_row
    facts = (row or {}).get("facts") or {}
    docs = (row or {}).get("docs") or []
    items: List[dict] = []
    loss_plan = [s for s in ((pkg or {}).get("loss_plan") or []) if isinstance(s, dict)]

    # 1. Overview: the missing key details, as listed.
    for it in ((kd or {}).get("missing_items") or []):
        if isinstance(it, dict) and it.get("label") and isinstance(it.get("resolution"), dict):
            items.append({"id": f"kd:{it['label']}", "kind": "detail", "page": "overview",
                          "label": str(it["label"]), "resolution": it["resolution"]})
    # 2. Documents: a file to mark as Loss runs (the Loss History plan's mark steps).
    for s in loss_plan:
        if s.get("key") != "mark" or not s.get("applied"):
            continue
        idx = next((n for n, d in enumerate(docs) if isinstance(d, dict)
                    and ((s.get("doc_id") and d.get("doc_id") == s.get("doc_id"))
                         or (not s.get("doc_id") and d.get("filename") == s.get("filename")))), None)
        if idx is None:
            continue
        items.append({"id": f"mark:{s.get('doc_id') or s.get('filename')}", "kind": "doc",
                      "page": "documents", "label": s.get("label") or "", "step": "mark",
                      "doc_index": idx, "doc_id": s.get("doc_id"), "filename": s.get("filename"),
                      "plan_order": s.get("plan_order")})
    # 3. Data Consistency: a pick that releases a hold.
    try:
        from services.stops_now import conflict_stop_facts
        by_fact: Dict[str, List[str]] = {}
        for msg, fact in conflict_stop_facts(row).items():
            by_fact.setdefault(str(fact), []).append(str(msg))
        for fact, msgs in by_fact.items():
            items.append({"id": f"dc:{fact}", "kind": "dc", "page": "data_consistency",
                          "label": fact, "fact": fact, "messages": msgs,
                          "resolution": {"mode": "field", "facts": [fact]}})
    except Exception as exc:                                   # noqa: BLE001
        logger.debug("review plan: data consistency rows skipped: %s", exc)
    # 4 + 5. Hard stops, then warnings - one item per rule code AND fix. A
    # catch-all code (`uncovered_soft_stop`, `uncovered_hard_stop`) draws several
    # cards, each with its own window (28 Oct 2026 review: "Lines of business",
    # "Policy term already expired", "Driver schedule" and "Split liability
    # limits" were all `uncovered_soft_stop`; only the first was weighed, so the
    # others' points showed nowhere - "15 pts no item adds" - and every one of
    # those cards printed the first card's number). The first card of a code
    # keeps the id `card:<code>`; a later one with a different fix is its own
    # item, `card:<code>#<issue_id>`, and carries its `issue_id` for the page.
    seen_cards: set = set()
    seen_codes: set = set()
    _dc_facts = {str(x.get("fact")) for x in items if x.get("kind") == "dc"}
    for card in rendered_cards(grouped):
        code = str(card.get("code") or "")
        try:
            from services.issue_registry import doc_conflict_fact_key, picker_fact_key
            _cf = doc_conflict_fact_key(code) or picker_fact_key(code)
        except Exception:                                      # noqa: BLE001
            _cf = None
        _dc_owner = (f"dc:{_cf}" if _cf and str(_cf) in _dc_facts else None)
        if not code:
            continue
        sig_keys = tuple(sorted(fix_keys(card.get("resolution"))))
        sig = (code, sig_keys) if sig_keys else (code, str(card.get("message") or ""))
        if sig in seen_cards:
            continue
        seen_cards.add(sig)
        first_of_code = code not in seen_codes
        seen_codes.add(code)
        iid = str(card.get("issue_id") or "")
        items.append({"id": f"card:{code}" if first_of_code else f"card:{code}#{iid or len(items)}",
                      "kind": "card", "page": card["page"], "code": code,
                      "issue_id": card.get("issue_id"), "first_of_code": first_of_code,
                      "label": card.get("message") or code, "resolution": card.get("resolution"),
                      "message": card.get("message") or ""})
        if _dc_owner:
            # The screen still draws this card (no Data Consistency row for the
            # fact): it is the Data Consistency entry's other face - counted once
            # there, fixed there, and it reads that entry's number / hold (P4).
            items[-1]["mirror_of"] = _dc_owner
            items[-1]["dc_fact"] = str(_cf)
    # 6. Recommendations rows, in the order they are listed.
    for n, r in enumerate((pkg or {}).get("top_recommendations") or []):
        if not isinstance(r, dict) or r.get("pillar") == HARD_STOPS_ROW:
            continue
        if r.get("field"):
            res = r.get("resolution") if isinstance(r.get("resolution"), dict) else None
            if not res or res.get("mode") in (None, "none"):
                try:
                    res = fix_route_for_row(r, facts)
                except Exception:                              # noqa: BLE001
                    res = None
            if not res:
                continue
            if res.get("mode") == "narrative" and isinstance(r.get("narrative_gaps"), list):
                res = {**res, "gaps": r["narrative_gaps"]}
            items.append({"id": f"rec:{n}", "kind": "rec", "page": "recommendations",
                          "label": str(r.get("action") or ""), "row_index": n, "pillar": r.get("pillar"),
                          "field": r.get("field"), "resolution": res, "plan_order": r.get("plan_order"),
                          "prose": r.get("pillar") == "narrative_quality",
                          # A Loss History step weighed with one possible answer
                          # (the claims question) is "up to", never a promise.
                          "hedged": any(s.get("key") == r.get("plan_step") and s.get("exact") is False
                                        for s in loss_plan if r.get("plan_step"))})
    # 7. The upload row (the Loss History plan's), which takes the residual.
    up = next((s for s in loss_plan if s.get("key") == "upload" and s.get("applied")), None)
    if up is not None:
        items.append({"id": "doc:upload", "kind": "doc", "page": "recommendations",
                      "label": up.get("label") or "", "step": "upload",
                      "plan_order": up.get("plan_order")})
    for n, it in enumerate(items, 1):
        it["order"] = n
        it["keys"] = fix_keys(it.get("resolution")) if it.get("resolution") else (
            [f"doc:{it.get('step')}:{it.get('doc_id') or it.get('filename') or ''}"]
            if it["kind"] == "doc" else [])
    return items


_TERM_KEYS = ("effective_date", "expiration_date")


def _term_refused(stored: dict, sim: "_Sim", names: List[str]) -> bool:
    """Would the route refuse this save of the proposed term (the dates the save
    gives over the ones on file - `validators.term_save_refusal`)?"""
    supplied = {f: _fv(sim.session["facts"], f) for f in names if f in _TERM_KEYS}
    supplied = {k: str(v) for k, v in supplied.items() if v not in (None, "")}
    if not supplied:
        return False
    try:
        from utils.validators import term_save_refusal
        return bool(term_save_refusal(stored, supplied))
    except Exception:                                          # noqa: BLE001
        return False


def _verifies_figures(item: dict) -> bool:
    """True for a card whose only ask is to verify the figures its window shows."""
    if item.get("kind") != "card":
        return False
    try:
        from services.issue_registry import VERIFY_FIGURE_CODES
        return str(item.get("code") or "") in VERIFY_FIGURE_CODES
    except Exception:                                          # noqa: BLE001
        return False


# THE SAMPLE ANSWER THAT RAISES NOTHING NEW (28 Oct 2026 review). The plan's
# number for an item is what its sample answer moves; a sample that is true of
# some businesses and raises a NEW item on this one (25 employees on a package
# carrying no workers comp: "Employees are listed but no workers comp coverage
# is carried", -8) left points no item on the page added. Where the fact has
# other answers a person may truly give - its other choices, or a zero for a
# count (`answer_semantics` kind "integer": no employees, no vehicles; never a
# zero amount) - the plan does the step again with the first that raises
# nothing new and scores no lower; else the step stands as first done. Only the
# review page's own plan chooses (`choose_samples`), and only on a step that
# raised something - a rare case, so the plan costs no more on the others.
def _alternative_samples(fact: str) -> List[str]:
    out: List[str] = []
    try:
        from services.answer_options import OTHER, options_for
        out += [str(o) for o in (options_for(fact) or []) if o != OTHER]
    except Exception:                                          # noqa: BLE001
        pass
    try:
        from services.answer_semantics import _declared_kind, _registry_entry
        if _declared_kind(fact, _registry_entry(fact)) == "integer":
            out.append("0")
    except Exception:                                          # noqa: BLE001
        pass
    return out


_FIGURES_RE = None


def _shape(text: Any) -> str:
    """A sentence with its figures taken out: a stop that only restates a new
    value ("WC payroll ($750,000) is ...") is the same item."""
    global _FIGURES_RE
    if _FIGURES_RE is None:
        import re
        _FIGURES_RE = re.compile(r"[\d$][\d$,./%-]*")
    return _FIGURES_RE.sub("#", str(text or ""))


def _raised(sim: "_Sim") -> set:
    """What the copy holds against the score as it stands: every stop sentence
    and every Recommendations row (by pillar and what it asks), figures aside."""
    sim.measure()
    st = getattr(sim, "last_stops", None) or {}
    pkg = getattr(sim, "last_pkg", None) or {}
    out = {("stop", _shape(m)) for m in (st.get("hard") or []) + (st.get("soft") or [])}
    out |= {("stop", _shape(i.get("message"))) for i in (st.get("cross_issues") or []) if isinstance(i, dict)}
    out |= {("row", str(r.get("pillar")), _shape(r.get("field") or r.get("action") or ""))
            for r in (pkg.get("top_recommendations") or []) if isinstance(r, dict)}
    out |= set(_loss_plan_rows(sim, pkg))
    return out


def _loss_plan_rows(sim: "_Sim", pkg: dict) -> Dict[tuple, str]:
    """The Loss History plan's listed rows on the copy, {signature: label}
    (seed 5024, 30 Oct 2026). The copy is scored as a probe, and a probe leaves
    the plan's rows out (`calculate_package_sqs`), so a loss row a step raises -
    the No Known Losses conflict once the runs' years bring claims into the
    window - was invisible to the plan and never declared as that step's
    follow-up. Read here with the scorer's own listing rule."""
    from services import sqs_service as S
    pillars = (pkg or {}).get("pillars") or {}
    lh = pillars.get("loss_history_alignment")
    lh = lh.get("score") if isinstance(lh, dict) else lh
    if lh is None or (isinstance(lh, (int, float)) and lh >= 100):
        return {}
    try:
        steps = S.loss_history_plan(sim.session["facts"], sim.session["flags"],
                                    sim.session.get("docs") or [], pillars) or []
    except Exception:                                          # noqa: BLE001
        return {}
    out: Dict[tuple, str] = {}
    for st in steps:
        if not isinstance(st, dict) or st.get("key") == "upload":
            continue
        if int(st.get("points") or 0) <= 0 and not (st.get("key") == "claims" and st.get("applied")):
            continue
        label = str(st.get("label") or "")
        out[("row", "loss_history_alignment", _shape(st.get("fact") or label))] = label
    return out


def _best_sample(sim: "_Sim", fact: str) -> str:
    """The sample answer typed for `fact`: the first (`probe_value`), unless the
    plan is retrying the step with another one (`sim.forced`). The plan's own
    reading records which sampled facts have other answers (`sim.step_samples`)."""
    facts = sim.session["facts"]
    forced = getattr(sim, "forced", None) or {}
    if fact in forced:
        return forced[fact]
    first = probe_value(fact, facts, sim.session)
    if getattr(sim, "choose_samples", False):
        alts = [c for c in dict.fromkeys(str(c) for c in _alternative_samples(fact))
                if c != first and _accepts(fact, c)][:3]
        if alts:
            sim.step_samples.append((fact, alts))
    return first


def _snap(sim: "_Sim") -> tuple:
    return (copy.deepcopy(sim.session.get("facts")), copy.deepcopy(sim.session.get("flags")),
            copy.copy(getattr(sim, "answered", set())))


def _restore(sim: "_Sim", snap: tuple) -> None:
    sim.session["facts"] = copy.deepcopy(snap[0])
    if snap[1] is not None:
        sim.session["flags"] = copy.deepcopy(snap[1])
    sim.answered = copy.copy(snap[2])


def _retry_with_other_samples(sim: "_Sim", item: dict, probes: Dict[str, str], full_years: int,
                              snapshot: tuple, seen_raised: set, first_shown: float,
                              first_raw: Optional[float] = None):
    """The step raised something new: try the other answers its sampled boxes
    may truly take, one box at a time; keep the first that raises nothing new
    and scores no lower (else the step as first done). Returns the measure."""
    tried = list(sim.step_samples)
    for fact, alts in tried:
        for alt in alts:
            _restore(sim, snapshot)
            sim.forced = {fact: alt}
            sim.step_samples = []
            try:
                did = _apply(sim, item, probes, full_years)
            finally:
                sim.forced = {}
            if not did:
                continue
            m = sim.measure()
            # "No lower" on the RAW score too (29 Oct 2026, scoring contract):
            # under a 60 / 85 hold every answer shows the same number, so an
            # alternative that costs points (the umbrella "does not follow
            # form", -1.2) looked as good as the first - and the plan ended
            # under 100 with those points on no item.
            if (m[0] >= first_shown - _EPS and (first_raw is None or m[1] >= first_raw - _EPS)
                    and not (_raised(sim) - seen_raised)):
                return m
    _restore(sim, snapshot)
    sim.step_samples = []
    _apply(sim, item, probes, full_years)
    return sim.measure()


def _card_still_raised(sim: "_Sim", item: dict) -> bool:
    """Does the card's own sentence still stand on the copy (the stops as they
    would stand, `stops_now`)?"""
    msg = str(item.get("message") or "")
    if not msg:
        return False
    try:
        from services.stops_now import stops_now
        st = stops_now(sim.session, sim.form_ids, pre_form=getattr(sim, "pre_form", True),
                       facts=sim.session["facts"], flags=sim.session["flags"])
    except Exception:                                          # noqa: BLE001
        return False
    raised = set(st.get("hard") or []) | set(st.get("soft") or [])
    raised |= {str(i.get("message")) for i in (st.get("cross_issues") or []) if isinstance(i, dict)}
    return msg in raised


def _row_still_raised(sim: "_Sim", item: dict) -> bool:
    """Does the Recommendations row `item` still stand on the copy?"""
    sig = _signature(item)
    try:
        return bool(sig) and sig in _raised(sim)
    except Exception:                                          # noqa: BLE001
        return False


def _apply(sim: _Sim, item: dict, probes: Dict[str, str], full_years: int) -> bool:
    """Do one step on the copy. True when the copy changed (False when it cannot
    be done here, or an item above already did exactly this)."""
    kind = item["kind"]
    if kind == "doc":
        if item.get("step") == "mark":
            return sim.mark(int(item["doc_index"]))
        if item.get("step") == "upload":
            return sim.upload_complete_runs(full_years)
        return False
    if kind == "dc":
        new = set(item.get("messages") or []) - sim.suppressed
        sim.suppressed.update(new)
        return bool(new)
    res = item.get("resolution") if isinstance(item.get("resolution"), dict) else {}
    mode = res.get("mode")
    if mode == "field":
        facts = [str(f) for f in (res.get("facts") or []) if f]
        all_card_facts = list(facts)
        # A PERSON TYPES ONLY THE EMPTY BOXES (Z38 lane E, live 3e835b53): the
        # window shows a stated value in its box and a save leaves it as it is.
        # Probing every box overwrote the stated coinsurance (80% -> a probe the
        # range check refuses) and building values, raising a new warning in the
        # copy that a person's save never raises - so the Carrier-Grade COPE card
        # showed +1 and moved +3, and the rows after it (hydrant, fire
        # department) read as held / nothing until it was done. Only when every
        # box is stated (a card about a WRONG value) are they all probed.
        try:
            from services.sqs_service import _answered
            _sf = sim.session["facts"]
            # (A fact the plan has its own answer for - the Loss History plan's
            # truthful claims answer, the runs' years - is always that answer.)
            empty = [f for f in facts if f in probes or not _answered(_sf, f)]
            # ...and a box an item above already answered is the PERSON's
            # answer now (27 Oct 2026, random-package solver): the umbrella
            # card typed the auto limit $1,000,000, then the Recommendations
            # row for the same box re-typed it with its own stand-in.
            facts = empty or [f for f in facts if f not in sim.answered]
            # A WRONG-VALUE card (a relationship: a term running backwards, an
            # ended term, a limit that fails to attach) is corrected in the boxes
            # that hold the wrong value; an empty box beside them is left alone
            # (seed 5036, 30 Oct 2026: the backwards-term card typed an umbrella
            # expiration and raised the umbrella / GL misalignment).
            if item.get("kind") == "card" and not _verifies_figures(item):
                from services.issue_registry import is_relationship_card
                if is_relationship_card({"code": item.get("code"), "message": item.get("message")}):
                    # (A box the plan has the true answer for - the Loss History
                    # plan's claims answer - is that answer, and is the fix.)
                    known = [f for f in all_card_facts if f in probes]
                    stated = [f for f in all_card_facts if _answered(_sf, f)]
                    if known or stated:
                        facts = known or stated
        except Exception:                                      # noqa: BLE001
            pass
        # A "verify this figure" card (`issue_registry.VERIFY_FIGURE_CODES`) is
        # answered by CONFIRMING the figures its window shows - the window
        # confirms the shown values when nothing is typed (`utils/fixWindow.js`),
        # and that is the answer that stands the card down (28 Oct 2026 review:
        # the plan typed stand-ins over the payroll AND the revenue, which raised
        # the payroll-to-revenue checks the true figures never raise, so the
        # page listed points no item added - 15 on one package).
        verify = _verifies_figures(item)
        all_facts = [str(f) for f in (res.get("facts") or []) if f]

        def type_boxes(names: List[str]) -> bool:
            did = False
            for f in names:
                shown = _fv(sim.session["facts"], f) if verify else None
                if verify and isinstance(shown, (str, int, float)) and str(shown).strip() \
                        and f not in probes and _accepts(f, str(shown)):
                    value = str(shown)
                elif f in probes:
                    value = probes[f]
                else:
                    value = _best_sample(sim, f)
                did = sim.answer(f, value) or did
            return did

        # THE WINDOW'S SAVE IS JUDGED LIKE THE ROUTE JUDGES IT (28 Oct 2026
        # review, real doors): a save that leaves the proposed term backwards
        # or ended is REFUSED (`validators.term_save_refusal`). The plan typed a
        # proposed effective date beside a document's ended expiration, credited
        # the points, and the real save refused it. A refused save types the
        # window's other term date with it (the person moves both); when the
        # window has none, nothing is saved and the step adds nothing here.
        snapshot = _snap(sim)
        changed = type_boxes(facts)
        refused = _term_refused(snapshot[0], sim, facts)
        if refused:
            partners = [f for f in all_facts if f in _TERM_KEYS and f not in facts]
            if partners:
                changed = type_boxes(partners) or changed
                refused = _term_refused(snapshot[0], sim, facts + partners)
            if refused:
                _restore(sim, snapshot)
                return False
            facts = facts + partners
        # A CARD ABOUT A WRONG STATED VALUE that also lists an empty box (28 Oct
        # 2026 review: the backwards-term card names the effective, expiration
        # AND umbrella expiration dates - typing only the empty umbrella date
        # left the term backwards, the card standing and its 85 counted
        # nowhere). When typing the empty boxes leaves the card raised, the
        # person corrects the stated ones too - as a person does when the save
        # does not clear it.
        rest = [f for f in all_facts if f not in facts and f not in sim.answered]
        if kind == "card" and rest and _card_still_raised(sim, item):
            changed = type_boxes(rest) or changed
        return changed
    if mode == "schedule" and res.get("schedule_key"):
        # The boxes ABOVE the table (a 2+ building COPE card's occupancy - the
        # window's `facts`) are saved with it, like the real window does
        # (live c5dc03ec, 25 Oct 2026: the hard stop showed 0 and moved +13).
        # Only the empty ones, like the field windows above.
        changed = False
        try:
            from services.sqs_service import _answered
            _sf = sim.session["facts"]
            for f in [str(x) for x in (res.get("facts") or []) if x]:
                if f in probes or not _answered(_sf, f):
                    changed = sim.answer(f, probes.get(f) or probe_value(f, _sf, sim.session)) or changed
        except Exception:                                      # noqa: BLE001
            pass
        changed = sim.table(str(res["schedule_key"]), res) or changed
        # A ROW ABOUT A WRONG STATED VALUE (29 Oct 2026, scoring contract): a
        # class-code mismatch whose codes and description are both on file is
        # cleared by correcting a side, not by saving the table unchanged - the
        # same rule as a card about a wrong value below. When the save leaves
        # the row raised, the person corrects the boxes the window shows
        # above the table (`also_facts`: the description / NAICS sector).
        above = [str(x) for x in (res.get("facts") or []) if x and str(x) not in sim.answered]
        if kind == "rec" and above and _row_still_raised(sim, item):
            for f in above:
                changed = sim.answer(f, probes.get(f) or _best_sample(sim, f)) or changed
        return changed
    if mode == "narrative":
        gaps = res.get("gaps")
        if not isinstance(gaps, list):
            gaps = _narrative_gaps(sim)
        else:
            # The window lists the topics as the page stands WHEN it is opened
            # (every save re-reads the page): the answers above can add a topic
            # the page-start list did not have (28 Oct 2026 review: growth and
            # target markets, 89 left on the narrative after everything).
            have = {str((g or {}).get("label") or "") for g in gaps if isinstance(g, dict)}
            gaps = list(gaps) + [g for g in _narrative_gaps(sim)
                                 if isinstance(g, dict) and str(g.get("label") or "") not in have]
        changed = sim.narrative(gaps)
        # A CARD answered by an explanation is recorded as explained, like the
        # real door does (`audit_routes.resolve_issue` mode=narrative keeps the
        # card's code in `_explained_issue_codes`, and a rule whose only fix is
        # an explanation stops counting it) - 28 Oct 2026 review: the copy left
        # the card standing, so its points showed nowhere.
        if kind == "card" and item.get("code"):
            changed = sim.explain(str(item["code"])) or changed
        return changed
    if kind == "card" and item.get("message") and item["message"] not in sim.suppressed:
        # A card no box on the page can answer: what releasing its hold adds.
        sim.suppressed.add(item["message"])
        return True
    return False


def _released_cap(pkg: dict, st: dict, suppressed: set) -> Tuple[Optional[int], Optional[str]]:
    """The hold left once the page's action-less cards are released: a level
    (60 / 85) is released only when it had listed items and every one of them
    is released. A hold the scorer raises itself (no listed item) stays."""
    cap, reason = pkg.get("cap_applied"), pkg.get("cap_reason")
    if not suppressed or cap is None:
        return cap, reason
    hard, soft = list(st.get("hard") or []), list(st.get("soft") or [])
    # Only the cross-form issues that HOLD a score (27 Oct 2026, random-package
    # solver): an advisory (UM/UIM not specified, ACORD 101 recommended) or a
    # form choice holds nothing - the scorer leaves them out of both lists -
    # and counting one here kept a released 60 at 85 in the copy.
    from services.sqs_service import _CROSS_ISSUE_TYPES
    for i in st.get("cross_issues") or []:
        if (isinstance(i, dict) and i.get("message") and i.get("type") in _CROSS_ISSUE_TYPES
                and not i.get("form_choice")):
            (hard if i.get("type") == "hard_stop" else soft).append(i["message"])
    open_hard = [m for m in hard if m not in suppressed]
    open_soft = [m for m in soft if m not in suppressed]
    if int(cap) <= 60 and hard and not open_hard:
        cap, reason = (85, open_soft[0]) if open_soft else (None, None)
    if cap is not None and int(cap) == 85 and soft and not open_soft and not open_hard:
        cap, reason = None, None
    return cap, reason


def _holding_stops(sim: "_Sim") -> Tuple[set, set]:
    """(hard, soft): the stop sentences holding the score on the copy as it
    stands (shapes, figures aside) - the ones `_released_cap` counts."""
    sim.measure()
    st = getattr(sim, "last_stops", None) or {}
    hard = {_shape(m) for m in (st.get("hard") or []) if m not in sim.suppressed}
    soft = {_shape(m) for m in (st.get("soft") or []) if m not in sim.suppressed}
    try:
        from services.sqs_service import _CROSS_ISSUE_TYPES
    except Exception:                                          # noqa: BLE001
        _CROSS_ISSUE_TYPES = ()
    for i in st.get("cross_issues") or []:
        if (isinstance(i, dict) and i.get("message") and i.get("type") in _CROSS_ISSUE_TYPES
                and not i.get("form_choice") and i["message"] not in sim.suppressed):
            (hard if i.get("type") == "hard_stop" else soft).add(_shape(i["message"]))
    return hard, soft


def _largest_remainder(weights: List[float], total: int) -> List[int]:
    """Whole numbers in proportion to `weights` adding up to exactly `total`."""
    import math
    n = len(weights)
    if n == 0 or total <= 0:
        return [0] * n
    w = [max(0.0, float(x)) for x in weights]
    s = sum(w)
    if s <= _EPS:
        w, s = [1.0] * n, float(n)
    raw = [x * total / s for x in w]
    out = [int(math.floor(r + 1e-9)) for r in raw]
    order = sorted(range(n), key=lambda k: (-(raw[k] - out[k]), k))
    for k in order[: total - sum(out)]:
        out[k] += 1
    return out


def _share_group_releases(items: List[dict], total_points: int,
                           hold_counts: Optional[Dict[str, int]] = None) -> None:
    """CAP SHARES (owner, 29 Oct 2026: every item a person must solve to reach
    100 shows a number, and they add up to exactly 100 - score).

    Done in page order, a 60 / 85 hold gives its whole release to the LAST
    item that held it and "Counts once <it> is fixed" on the others. Now:
      1. each item keeps its own measured gain (what its answer moves);
      2. what is released only when a group is done - a hold's release, the
         gains it withheld - is paid back to the held items their own gain and
         the rest split EVENLY across every item holding that hold;
      3. an item a person must solve still at 0 takes a point from the pool it
         is blocked behind (its group, else the largest number on the page) -
         never an invented point: the total stays exactly what it was;
      4. an item whose answer moves nothing and holds nothing is not a score
         item (`score_item: False`; the page lists no number for it).
    Whole points by largest remainder within the group, so totals stay exact.
    Wording: `with_others` ("counts when all 6 warnings are fixed")."""
    live = [it for it in items if not it.get("mirror_of")]
    # 2. Pay back and share each release step's surplus.
    f: Dict[str, float] = {}
    unpaid: List[Tuple[dict, float]] = []
    group_of: Dict[str, int] = {}
    groups: List[dict] = []
    for it in live:
        own = float(it.get("_own") or 0.0)
        gain = float(it.get("gain") or 0.0)
        if it.get("held_by") is not None or (own > gain + _EPS and gain <= _EPS):
            # (`get`: a holder listed BELOW the step that released its hold
            # already carries its share - never wipe it.)
            f[it["id"]] = f.get(it["id"], 0.0)
            unpaid.append((it, own))
            continue
        kept = min(gain, own)
        f[it["id"]] = f.get(it["id"], 0.0) + kept
        surplus = gain - kept
        if surplus <= _EPS:
            continue
        # The withheld gains come back to their items first.
        g = {"members": [], "holders": [], "levels": set(it.get("_released") or [])}
        while unpaid and surplus > _EPS:
            x, owed = unpaid[0]
            pay = min(owed, surplus)
            f[x["id"]] += pay
            surplus -= pay
            g["members"].append(x)
            if owed - pay > _EPS:
                unpaid[0] = (x, owed - pay)
            else:
                unpaid.pop(0)
        g["members"] += [x for x, _o in unpaid]     # still held: share the pool
        g["members"].append(it)
        lv = g["levels"] or {"soft"}
        holders = [x for x in live if set(x.get("_cleared") or []) & lv]
        if it not in holders:
            holders.append(it)
        g["holders"] = holders
        if surplus > _EPS:
            share = surplus / len(holders)
            for h in holders:
                f[h["id"]] = f.get(h["id"], 0.0) + share
        for x in g["members"] + holders:
            group_of.setdefault(x["id"], len(groups))
        groups.append(g)
    for x, owed in unpaid:      # never released here: nothing shared to it
        f.setdefault(x["id"], 0.0)
    if not groups:
        return
    # Groups that share an item are one pool: an item holding two holds (a
    # hard stop whose answer also clears a warning) takes a share of BOTH
    # releases, so both releases must be split in one place - else its second
    # share stays with the other group's items and the split is not even.
    parent = list(range(len(groups)))

    def _root(k: int) -> int:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    first_of: Dict[str, int] = {}
    for gi, g in enumerate(groups):
        for x in g["members"] + g["holders"]:
            if x["id"] in first_of:
                parent[_root(gi)] = _root(first_of[x["id"]])
            else:
                first_of[x["id"]] = gi
    merged: Dict[int, dict] = {}
    for gi, g in enumerate(groups):
        m = merged.setdefault(_root(gi), {"holders": [], "levels": set()})
        m["levels"] |= set(g["levels"] or {"soft"})
        for h in g["holders"]:
            if all(h is not y for y in m["holders"]):
                m["holders"].append(h)
    group_of = {iid: _root(gi) for iid, gi in first_of.items()}
    groups = [merged.get(k) for k in range(len(groups))]
    # Whole points per group: its pool (the numbers its members carry now)
    # re-split by the floats above.
    for gi, g in enumerate(groups):
        if g is None:
            continue
        mem = [x for x in live if group_of.get(x["id"]) == gi]
        pool = sum(int(x.get("points") or 0) for x in mem)
        extra = [float(x.get("_follow") or 0) for x in mem]
        base = [f.get(x["id"], 0.0) for x in mem]
        new = _largest_remainder([b + e for b, e in zip(base, extra)], pool)
        for x, n in zip(mem, new):
            x["points"] = int(n)
        nh = len(g["holders"])
        kinds = g["levels"] or {"soft"}
        word = ("hard stops" if kinds == {"hard"} else
                "warnings" if kinds == {"soft"} else "hard stops and warnings")
        # The holders are counted where the page draws them (end-user review,
        # 29 Oct 2026): a Data Consistency pick is a row on that page, not a
        # warning card, so "all 15 warnings" beside 2 warning cards and 13 picks
        # sent the producer looking for 13 warnings that are not there.
        _dc = sum(1 for h in g["holders"] if h.get("kind") == "dc")
        if _dc and _dc == nh:
            word = "Data Consistency picks"
        elif _dc:
            word = f"{word} and Data Consistency picks"
        count = nh
        for x in mem:
            if len(mem) > 1:
                x["with_others"] = (f"counts when all {count} {word} are fixed" if count > 1
                                    else f"counts when the {word[:-1]} is fixed"
                                    if word.endswith("s") and " and " not in word
                                    else f"counts when the {word} are fixed")
            x["held_by"] = None
            x["cap_share"] = True
            x["exact"] = False


def _no_listed_zero(items: List[dict], up_index: Optional[int]) -> None:
    """Rules 3 and 4 of `_share_group_releases`: a score item still at 0 takes
    one point from the largest number in its group, else on the page (the
    total never moves); an item that moves nothing, clears no hold and adds
    nothing is `score_item: False`."""
    live = [it for it in items if not it.get("mirror_of")]
    for n, it in enumerate(items):
        if it.get("mirror_of"):
            continue
        scored = (int(it.get("points") or 0) > 0 or float(it.get("_own") or 0) > _EPS
                  or float(it.get("gain") or 0) > _EPS or bool(it.get("_cleared"))
                  or float(it.get("_follow") or 0) > 0 or it.get("held_by") is not None)
        it["score_item"] = bool(scored)
    # A score item whole points cannot reach says "under 1 pt" (P1, owner 29
    # Oct 2026). It no longer BORROWS a point from another item: a borrow
    # broke P3 (each item keeps its own measured gain) whenever the holders
    # of a hold outnumbered its release (11 warnings sharing 4 points).
    for it in live:
        if it["score_item"] and int(it.get("points") or 0) <= 0:
            it["under"] = True
            it["exact"] = False
            if it.get("held_by") is not None:
                it["with_others"] = f"counts when {it['held_by']} is fixed"
                it["held_by"] = None


def enforce_contract(items: List[dict], now: int, left: int = 0) -> Tuple[int, List[str]]:
    """THE SCORING CONTRACT'S LAST CHECK ON THE PLAN (owner, 29 Oct 2026 -
    SCORING_RULES.md P1 / P2 / P4 / P5). Run after every share is made, on the
    items as the screens will print them; it REPAIRS a breach rather than show
    it, logs `SCORING_CONTRACT_REPAIRED` naming the rule and the item ids (never
    a value), and returns the rules it repaired (the plan's `contract_repaired`)
    so the random-package proof fails on a repair the root code should never
    have needed.

      P4  a mirror adds nothing: its own points go to the item it mirrors (a
          mirror of a mirror points at the first place; a mirror of nothing
          is an item of its own); no number is negative.
      P5  an item that is not a score item carries no number; one that does
          carry points IS a score item.
      P2  the items' points add up to exactly 100 - score: a surplus comes off
          the largest numbers ("up to" from then on); a shortfall - or points
          the plan could give to no item (`left`) - goes to the score items
          whole points could not reach ("under 1 pt"), else the largest.
      P1  a score item still at 0 below 100 says "under 1 pt" (`under`), never
          only "counts once X is fixed"; at 100 nothing carries a number.
    Returns (the points still on no item - 0 unless the page has no score item
    at all, the repairs). Never raises."""
    repairs: List[str] = []
    try:
        total = max(0, 100 - int(now))
        by_id = {it.get("id"): it for it in items}

        def root_of(it: dict) -> Optional[dict]:
            seen = set()
            cur = it
            while cur.get("mirror_of") and cur.get("id") not in seen:
                seen.add(cur.get("id"))
                nxt = by_id.get(cur["mirror_of"])
                if nxt is None:
                    return None
                cur = nxt
            return None if cur.get("mirror_of") else cur

        # P4 - negatives, then mirrors.
        for it in items:
            if int(it.get("points") or 0) < 0:
                it["points"] = 0
                repairs.append(f"P4 negative: {it.get('id')}")
        for it in items:
            if not it.get("mirror_of"):
                continue
            first = root_of(it)
            if first is None or first is it:
                it.pop("mirror_of", None)
                repairs.append(f"P4 mirror of nothing: {it.get('id')}")
                continue
            if first.get("id") != it["mirror_of"]:
                it["mirror_of"] = first.get("id")
            own = int(it.get("points") or 0)
            if own:
                first["points"] = int(first.get("points") or 0) + own
                first["exact"] = False
                it["points"] = 0
                repairs.append(f"P4 mirror counted twice: {it.get('id')}")
            it["under"] = False
        live = [it for it in items if not it.get("mirror_of")]
        # P5 - a number makes a score item; no score item carries a fraction.
        for it in live:
            if int(it.get("points") or 0) > 0 and it.get("score_item") is False:
                it["score_item"] = True
                repairs.append(f"P5 number on a non-score item: {it.get('id')}")
            if it.get("score_item") is False and it.get("under"):
                it["under"] = False
        # P2 - exactly 100 - score.
        shown = sum(int(it.get("points") or 0) for it in live)
        if total == 0:
            for it in live:
                if int(it.get("points") or 0) or it.get("under"):
                    repairs.append(f"R4 a number at 100: {it.get('id')}")
                it["points"], it["under"], it["score_item"] = 0, False, False
                it.pop("with_others", None)
            left = 0
        elif shown > total:
            took = []
            for _n in range(shown - total):
                donor = max((x for x in live if int(x.get("points") or 0) > 0),
                            key=lambda x: (int(x["points"]), live.index(x)))
                donor["points"] = int(donor["points"]) - 1
                donor["exact"] = False
                took.append(str(donor.get("id")))
            repairs.append(f"P2 over by {shown - total}: {sorted(set(took))}")
        short = total - sum(int(it.get("points") or 0) for it in live)
        if total and short > 0:
            scored = [x for x in live if x.get("score_item") is not False
                      and (int(x.get("points") or 0) > 0 or x.get("under")
                           or float(x.get("gain") or 0) > _EPS or float(x.get("_own") or 0) > _EPS
                           or x.get("_cleared"))]
            if scored:
                gave = []
                for k in range(short):
                    pool = [x for x in scored if int(x.get("points") or 0) <= 0] or scored
                    to = max(pool, key=lambda x: (float(x.get("gain") or 0) + float(x.get("_own") or 0),
                                                  int(x.get("points") or 0), -live.index(x)))
                    to["points"] = int(to.get("points") or 0) + 1
                    to["exact"] = False
                    to["under"] = False
                    gave.append(str(to.get("id")))
                left = 0
                repairs.append(f"P2 short by {short}: {sorted(set(gave))}")
            else:
                left = short
                if short:
                    repairs.append(f"P2 {short} pts on no item")
        # P1 - every score item below 100 shows a number or "under 1 pt".
        if total:
            for it in live:
                if it.get("score_item") is False:
                    continue
                if int(it.get("points") or 0) > 0:
                    it["under"] = False
                    continue
                if not it.get("under"):
                    it["under"] = True
                    it["exact"] = False
                    repairs.append(f"P1 score item at 0: {it.get('id')}")
                if it.get("held_by") is not None:
                    it["with_others"] = f"counts when {it['held_by']} is fixed"
                    it["held_by"] = None
                    repairs.append(f"P1 only 'counts once': {it.get('id')}")
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("review plan: contract check failed: %s", exc)
        return int(left or 0), repairs
    if repairs:
        logger.warning("SCORING_CONTRACT_REPAIRED %s", "; ".join(repairs))
    return int(left or 0), repairs


def _narrative_gaps(sim: _Sim) -> List[dict]:
    try:
        from services import sqs_service as S
        sim.measure()
        pkg = getattr(sim, "last_pkg", None) or {}
        comps = pkg.get("narrative_components") or {}
        text = S._narrative_remarks_text(sim.session["facts"])
        return S.narrative_gap_options(comps, text)
    except Exception:                                          # noqa: BLE001
        return []


def _floor(value: float) -> int:
    import math
    return int(math.floor(round(float(value), 9)))


def _whole_points(shown_after: List[float], gains: List[float], start: int,
                  residual_index: Optional[int]) -> Tuple[List[int], List[bool]]:
    """Whole points per step: what the score ON SCREEN (rounded down) moves when
    the steps are done in page order - so each lands exactly in that order, and
    the residual step (the upload row) takes exactly what is left to 100.

    A step that adds a fraction but moves no whole point there says "under 1
    pt" (owner, 24 Oct 2026: a number must be exactly what the step moves - it
    never borrows a point from another step)."""
    ints: List[int] = []
    prev = int(start)
    for value in shown_after:
        cur = max(prev, _floor(value))
        ints.append(cur - prev)
        prev = cur
    if residual_index is not None and 0 <= residual_index < len(ints):
        ints[residual_index] += max(0, 100 - prev)
    under = [False] * len(ints)
    for n in range(len(ints)):
        if ints[n] == 0 and gains[n] > _EPS and n != residual_index:
            under[n] = True
    return ints, under


def build_review_plan(row: dict, pkg: dict, kd: Optional[dict],
                      grouped: Optional[dict] = None,
                      credit_rows: Optional[List[dict]] = None,
                      declare_alone: bool = True) -> Optional[dict]:
    """The page's items, weighed in page order. {"items": [...], "total": T,
    "end": the score the plan ends at, "left": the points no item adds}.
    `credit_rows`: after forms, the dismissal rows behind the stored score's
    credits (`audit_service.get_dismissed_recommendations`)."""
    if not isinstance(pkg, dict) or not isinstance(row, dict):
        return None
    now = pkg.get("package_sqs_score")
    if now is None:
        return None
    items = page_items(row, pkg, kd, grouped)
    probes = _loss_plan_probes(pkg)
    try:
        from services.loss_history_state import loss_years_required
        full_years = int(loss_years_required(row.get("facts") or {}) or 5)
    except Exception:                                          # noqa: BLE001
        full_years = 5
    # (Before forms the copy is made exactly as it always was.)
    sim = _Sim(row, credit_rows) if credit_rows else _Sim(row)
    sim.choose_samples = True
    shown, raw, cap, reason = sim.measure()
    raw_start = float(raw)
    cap_start = cap
    if _floor(shown) != int(now):
        logger.warning("review plan: simulated start %.3f is not the score %s", shown, now)
    try:
        _h0, _s0 = _holding_stops(sim)
    except Exception:                                          # noqa: BLE001
        _h0, _s0 = set(), set()
    hold_start = (_h0, _s0)
    gains: List[float] = []
    shown_after: List[float] = []
    applied_keys: List[Tuple[str, set]] = []
    # What each step raises (a new stop or row): a follow-up's points belong to
    # the step whose answer raised it (see below).
    seen_raised = _raised(sim)
    raised_by: Dict[tuple, int] = {}
    last_did: Optional[int] = None
    for idx, it in enumerate(items):
        first = next((iid for iid, keys in applied_keys if all_covered(it["keys"], keys)), None)
        if first:
            it["mirror_of"] = first
        before_shown, before_raw, before_reason, before_cap = shown, raw, reason, cap
        try:
            hold_before = _holding_stops(sim)
        except Exception:                                      # noqa: BLE001
            hold_before = (set(), set())
        did = False
        snapshot = _snap(sim)
        sim.step_samples = []
        try:
            did = _apply(sim, it, probes, full_years)
        except Exception as exc:                               # noqa: BLE001
            logger.debug("review plan: step %s not simulated: %s", it.get("id"), exc)
        if did:
            shown, raw, cap, reason = sim.measure()
            last_did = idx
            # A sample that raised a new item, where the box may truly take
            # another answer: the step is done again with that one (`_best_sample`).
            if sim.step_samples:
                try:
                    if _raised(sim) - seen_raised:
                        shown, raw, cap, reason = _retry_with_other_samples(
                            sim, it, probes, full_years, snapshot, seen_raised, shown, raw)
                except Exception as exc:                       # noqa: BLE001
                    logger.debug("review plan: other samples not tried for %s: %s", it.get("id"), exc)
            try:
                cur = _raised(sim)
                for sig in cur - seen_raised:
                    raised_by.setdefault(sig, idx)
                seen_raised |= cur
            except Exception:                                  # noqa: BLE001
                pass
        # A step that would lower the score on screen (rule G13, 30 Oct 2026,
        # contract seed 5008: a business income limit typed before its period of
        # restoration raised the 85 hold) DECLARES that cost - the page says so
        # beside it, with what it raises - instead of hiding it. The numbers
        # still never go negative: what it costs is the package's.
        if did and _floor(shown) < _floor(before_shown):
            it["cost"] = int(_floor(before_shown) - _floor(shown))
            # TWO ROWS THAT MUST BE ANSWERED TOGETHER ARE ONE (30 Oct 2026): the
            # dip comes from a check this answer raised whose boxes another
            # listed row asks for (a business income limit raising "period of
            # restoration missing"). The pair is joined into one window
            # (`join_codependent_rows`) so no order dips the score.
            try:
                _joins = _codependent_rows(sim, it, items, raised_by, idx)
                if _joins:
                    it["joins"] = _joins
            except Exception as exc:                           # noqa: BLE001
                logger.debug("review plan: joins not read for %s: %s", it.get("id"), exc)
        shown = max(shown, before_shown)
        it["gain"] = shown - before_shown
        # Cap shares (`_share_group_releases`): what the answer moves on its own,
        # which holds it clears, which hold its step releases.
        it["_own"] = max(0.0, raw - before_raw) if did else 0.0
        it["_rawgain"] = max(0.0, raw - before_raw) if did else 0.0
        it["real_gain"] = round(it["_rawgain"], 4)
        it["_did"] = bool(did)
        it["_raw_after"] = float(raw)
        if did:
            try:
                hold_after = _holding_stops(sim)
            except Exception:                                  # noqa: BLE001
                hold_after = hold_before
            it["_cleared"] = ([k for k, b, a in (("hard", hold_before[0], hold_after[0]),
                                                  ("soft", hold_before[1], hold_after[1]))
                               if b - a])
        # A card whose own sentence held the score when the page was read holds
        # it too, even when a step above it cleared the sentence first (the
        # person reads it on its own page and is told what it is worth).
        if it.get("kind") == "card" and it.get("message") and not it.get("mirror_of"):
            _sh = _shape(it["message"])
            for k, start in (("hard", hold_start[0]), ("soft", hold_start[1])):
                if _sh in start and k not in (it.get("_cleared") or []):
                    it["_cleared"] = list(it.get("_cleared") or []) + [k]
        # Which hold this step releases - any step, not only a card: a key
        # detail or a row whose answer lifts the last 60 / 85 shares it too.
        rel = []
        if before_cap is not None and int(before_cap) <= 60 and (cap is None or int(cap) > 60):
            rel.append("hard")
        if before_cap is not None and int(before_cap) <= 85 and cap is None:
            rel.append("soft")
        it["_released"] = rel
        it["held_by"] = (_hold_label(before_reason)
                         if did and it["gain"] <= _EPS and raw - before_raw > _EPS else None)
        gains.append(it["gain"])
        shown_after.append(shown)
        # Answered by an item above it (its boxes were filled first): named on
        # it, never "No effect on the score" (second hostile review, 30 Oct 2026).
        if not did and not it.get("mirror_of") and it.get("keys"):
            _ks = set(it["keys"])
            _by = next((iid for iid, keys in applied_keys if _ks & set(keys)), None)
            if _by is not None and _by in {x["id"] for x in items}:
                _src = next(x for x in items if x["id"] == _by)
                it["_covered_by"] = str(_src.get("label") or _by)
        applied_keys.append((it["id"], set(it["keys"])))
    # A Loss History row a step raised (the plan's copy never lists them - see
    # `_loss_plan_rows`) is that step's declared follow-up (rule G2).
    try:
        _lr = _loss_plan_rows(sim, getattr(sim, "last_pkg", None) or {})
        _listed = {_signature(x) for x in items}
        for _sig, _idx in raised_by.items():
            if _sig in _lr and _sig not in _listed and 0 <= _idx < len(items):
                _ld = items[_idx].setdefault("leads_to", [])
                if _lr[_sig][:120] not in _ld:
                    _ld.append(_lr[_sig][:120])
    except Exception as exc:                                   # noqa: BLE001
        logger.debug("review plan: loss follow-ups not read: %s", exc)
    # EVERY ORDER, NOT ONLY THE PAGE'S (rule G2, 30 Oct 2026). The walk above
    # credits a follow-up to the step that raised it in page order; a person who
    # answers in another order meets it after a step that declared nothing (the
    # 30 Oct sweep: GL codes before the operations, a payroll before its table,
    # a loss-run upload before the FEIN pick). Each item is also done ALONE on
    # the page as it stands, and what that raises - a stop, a row, a Loss History
    # row - is declared on it. Names only; no number moves.
    # (Names only, no number - so an intermediate plan the page rebuilds after
    # joining / merging rows skips it; the final one runs it: `declare_alone`.)
    if declare_alone:
        try:
            _declare_alone_follow_ups(row, items, probes, full_years, credit_rows)
        except Exception as exc:                               # noqa: BLE001
            logger.debug("review plan: alone follow-ups not read: %s", exc)
    up_index = next((n for n, it in enumerate(items)
                     if it["kind"] == "doc" and it.get("step") == "upload"), None)
    if up_index is not None:
        try:
            _declare_upload_follow_ups(row, items, items[up_index], probes, full_years, credit_rows)
        except Exception as exc:                               # noqa: BLE001
            logger.debug("review plan: upload follow-ups not read: %s", exc)
    # FOLLOW-UPS (28 Oct 2026 review). A sample answer can raise an item the
    # page does not show yet - a vehicle added to an empty schedule asks for
    # garaging, radius and use; a count of employees on a package carrying no
    # workers comp asks how they are covered. Their points were "points no item
    # on this page can add yet" and the numbers fell short of 100 - score. The
    # plan now reads the page as it would stand, does those items too, and
    # gives their points to the step that raised them, marked "up to" and
    # naming them (`leads_to`) - so the numbers add up to exactly 100 - score,
    # and the raised item shows the rest of its own number once it appears.
    follow: List[Tuple[int, float, float]] = []
    if _floor(shown) < 100 or _floor(raw) < 100:
        try:
            follow = _follow_ups(sim, items, probes, full_years, raised_by, last_did, shown,
                                 row=row, credit_rows=credit_rows)
        except Exception as exc:                               # noqa: BLE001
            logger.debug("review plan: follow-ups not simulated: %s", exc)
            follow = []
        if follow:
            shown = follow[-1][2]
    # ── THE POINTS (owner, 30 Oct 2026 - SCORING_RULES.md R5 / P1-P3) ────────
    # An item's points are what its answer moves the REAL score (the pillars, no
    # cap) in page order - never the shown one, and a cap's release is never
    # handed out as points. They add up to exactly 100 - the real score. An item
    # that moves nothing but holds a cap reads "Holds the score at 85 / 60 until
    # fixed" (`hold`), with no number.
    by_id = {it["id"]: it for it in items}
    # ONE CALCULATION (R5): the real score is the scorer's own figure on the
    # payload (raw + credits in force), never a second reading of the copy - the
    # copy's deltas only weigh the items.
    try:
        _pr = pkg.get("raw_sqs_score")
        real_start = (min(100, _floor(float(_pr) + float(pkg.get("credits_applied") or 0)))
                      if isinstance(_pr, (int, float)) and not isinstance(_pr, bool) else _floor(raw_start))
    except Exception:                                          # noqa: BLE001
        real_start = _floor(raw_start)
    real_start = max(int(now), int(real_start))
    if abs(real_start - _floor(raw_start)) > 1:
        logger.warning("review plan: simulated real %.3f is not the scorer's real %s", raw_start, real_start)
    real_total = max(0, 100 - real_start)
    # Whole points: what the REAL score (rounded down) moves when the steps are
    # done in page order - each number is exactly what its answer moves, and
    # they telescope, so they add up exactly. A dip never makes a negative.
    seq: List[Tuple[int, float, float]] = [(n, float(it.get("_raw_after", raw_start)), float(it.get("_rawgain") or 0.0))
                                           for n, it in enumerate(items)]
    _cur = float(seq[-1][1]) if seq else float(raw_start)
    for raiser, g, _s in follow:
        _cur += max(0.0, float(g or 0.0))
        seq.append((raiser, _cur, max(0.0, float(g or 0.0))))
    ints: Dict[int, int] = {}
    moved: Dict[int, float] = {}
    prev = int(real_start)
    for n, v, g in seq:
        cur = max(prev, _floor(v))
        if 0 <= n < len(items):
            ints[n] = ints.get(n, 0) + (cur - prev)
            moved[n] = moved.get(n, 0.0) + g
        prev = cur
    # An upload row owns what only documents fix: what Loss History still lacks
    # once every other item is done (whole points; within a point of a real
    # Loss History gap the rest is that gap's rounding). Never another pillar's.
    if up_index is not None and prev < 100:
        _loss_gap = 0.0
        try:
            _lp0 = getattr(sim, "last_pkg", None) or {}
            for _pt in ((_lp0.get("score_trace") or {}).get("pillars") or []):
                if _pt.get("pillar") == "loss_history_alignment" and not _pt.get("not_applicable"):
                    _loss_gap = max(0.0, (100.0 - float(_pt.get("score") or 0)) * float(_pt.get("effective_weight") or 0))
        except Exception:                                      # noqa: BLE001
            _loss_gap = 0.0
        _rest = 100 - prev
        _take = (_rest if _loss_gap > _EPS and _rest <= _floor(_loss_gap) + 1
                 else min(_rest, _floor(_loss_gap + 1e-6)))
        ints[up_index] = ints.get(up_index, 0) + _take
        prev += _take
    # One fix, one number (P4): a mirror's points are its first place's.
    for n, it in enumerate(items):
        first = by_id.get(it.get("mirror_of"))
        while first is not None and first.get("mirror_of") in by_id:
            first = by_id[first["mirror_of"]]
        if first is None or first is it:
            continue
        if it.get("mirror_of") != first.get("id"):
            it["mirror_of"] = first.get("id")
        fi = items.index(first)
        ints[fi] = ints.get(fi, 0) + ints.get(n, 0)
        moved[fi] = moved.get(fi, 0.0) + moved.get(n, 0.0)
        ints[n], moved[n] = 0, 0.0
        first["_cleared"] = sorted(set(first.get("_cleared") or []) | set(it.get("_cleared") or []))
        first["_released"] = sorted(set(first.get("_released") or []) | set(it.get("_released") or []))
    live_idx = [n for n, it in enumerate(items) if not it.get("mirror_of")]
    left = 0
    # A deduction no listed item answers (SCORING_RULES.md P2) must never
    # happen - and is never silent: logged as an error, and its points split
    # over the listed items in proportion so the screen still adds up.
    unowned = max(0, 100 - prev)
    spread: Dict[int, int] = {}
    # What a step RAISES and leaves open at the end of the walk (a warning the
    # answer brings - the WC class table raising "WC payroll differs from total
    # payroll", the loss-run upload's new warning) is that step's follow-up: its
    # points are the raising step's, "up to" (second hostile review, 30 Oct 2026:
    # seeds 15 / 26 logged them unowned). Split evenly when several raised them.
    if unowned:
        try:
            _open_end = _raised(sim)
            _raisers = sorted({idx for sig, idx in raised_by.items()
                               if sig in _open_end and 0 <= idx < len(items)})
            _raisers = [next((items.index(x) for x in items if x["id"] == items[r].get("mirror_of")), r)
                        if items[r].get("mirror_of") else r for r in _raisers]
            if _raisers:
                for r, k in zip(_raisers, _largest_remainder([1.0] * len(_raisers), unowned)):
                    ints[r] = ints.get(r, 0) + k
                    items[r]["_guessed_follow"] = True
                logger.info("SCORING_FOLLOW_UP_OWNED points=%d raisers=%s", unowned,
                            [items[r].get("id") for r in _raisers])
                prev += unowned
                unowned = 0
        except Exception as exc:                               # noqa: BLE001
            logger.debug("review plan: raised items not weighed: %s", exc)
    if unowned and real_total:
        try:
            _lp = getattr(sim, "last_pkg", None) or {}
            _open = {k: v for k, v in (_lp.get("pillars") or {}).items()
                     if isinstance(v, (int, float)) and v < 100}
        except Exception:                                      # noqa: BLE001
            _open = {}
        logger.error("SCORING_UNOWNED_DEDUCTION points=%d real_start=%d pillars_left=%s - no listed item "
                     "answers them; split over the listed items in proportion", unowned, real_start, _open)
        _w = [float(ints.get(n, 0)) or (moved.get(n, 0.0) if moved.get(n, 0.0) > _EPS else 0.0) for n in live_idx]
        if sum(_w) > _EPS:
            spread = dict(zip(live_idx, _largest_remainder(_w, unowned)))
        else:
            left = unowned
    for n, it in enumerate(items):
        it.pop("with_others", None)
        it["held_by"] = None
        it.pop("hold", None)
        if it.get("mirror_of"):
            it["points"], it["under"], it["score_item"] = 0, False, True
            continue
        p = int(ints.get(n, 0)) + int(spread.get(n, 0))
        g = float(moved.get(n, 0.0))
        it["points"] = p
        it["under"] = bool(p == 0 and g > _EPS)
        it["score_item"] = bool(p > 0 or g > _EPS)
        # Exact only when the number IS what the answer moves on its own ("up
        # to" when part of it comes from what the answer raises next).
        it["exact"] = bool(p > 0 and not spread.get(n) and abs(g - p) < 1.0 and not it.get("_guessed_follow")
                           and not it.get("prose") and not it.get("hedged"))
        if p == 0 and g <= _EPS and not it.get("hold") and it.get("_covered_by"):
            it["covered_by"] = str(it["_covered_by"])[:120]
        if p == 0 and g <= _EPS:
            # Decided on the page as it was read: which holds it clears / releases.
            cleared = set(it.get("_cleared") or []) | set(it.get("_released") or [])
            if "hard" in cleared:
                it["hold"] = "Holds the score at 60 until fixed"
            elif cleared or (it.get("kind") == "dc" and cap_start is not None):
                it["hold"] = "Holds the score at 85 until fixed"
    # A row whose deduction an item above it already cleared moves 0 in page
    # order but would move the score done first: it is answered there, never
    # "No effect on the score" (second hostile review, 30 Oct 2026).
    try:
        _cov = [n for n in live_idx if not items[n].get("points") and not items[n].get("hold")
                and not items[n].get("covered_by") and items[n].get("_did")
                and items[n].get("kind") not in ("dc", "doc") and moved.get(n, 0.0) <= _EPS]
        if _cov and real_total:
            for n, g in _alone_raw_gains(row, items, _cov, probes, full_years, credit_rows).items():
                if g > _EPS:
                    items[n]["covered_by"] = "an item listed above"
    except Exception as exc:                                   # noqa: BLE001
        logger.debug("review plan: covered rows not read: %s", exc)
    left, repaired = enforce_contract(items, real_start, left)
    for it in items:
        if it.get("mirror_of") in by_id:
            it["mirror"] = int(by_id[it["mirror_of"]]["points"])
    out = {"items": [{k: v for k, v in it.items() if k not in ("resolution",) and not k.startswith("_")}
                     for it in items],
           "total": real_total, "end": round(shown, 4), "left": int(left),
           "real": real_start, "shown": int(now)}
    if repaired:
        out["contract_repaired"] = repaired
    if not getattr(sim, "pre_form", True):
        out["after_forms"] = True       # the editor's side panel reads it
    # What `declare_follow_ups` needs, so the page's FINAL plan gets its any-order
    # follow-ups without walking the page again (popped before it is sent).
    if not declare_alone:
        out["_ctx"] = (items, probes, full_years, credit_rows)
    return out


def _raiser_alone(row: dict, items: List[dict], target: dict, probes: Dict[str, str],
                  full_years: int, credit_rows: Optional[List[dict]] = None) -> Optional[int]:
    """The index of the first step (page order) whose answer, done ALONE on the
    page as it stands, raises `target` (by its signature, else its label);
    None when none does. One copy, rolled back after each step."""
    sig = _signature(target)
    label = str(target.get("label") or "")[:120]
    sim = _Sim(row, credit_rows) if credit_rows else _Sim(row)
    sim.measure()
    start = _raised(sim)
    saved = (copy.deepcopy(sim.session), set(sim.suppressed), set(sim.answered),
             list(sim.form_ids), getattr(sim, "_measured", None))
    for n, it in enumerate(items):
        if it.get("mirror_of") or not it.get("_did") or it is target:
            continue
        sim.session = copy.deepcopy(saved[0])
        sim.suppressed, sim.answered = set(saved[1]), set(saved[2])
        sim.form_ids, sim._measured = list(saved[3]), saved[4]
        try:
            if not _apply(sim, it, probes, full_years):
                continue
            new = _raised(sim) - start
            if (sig and sig in new) or (label and any(label[:60] in str(x[1] if isinstance(x, tuple) and len(x) > 1 else x) for x in new)):
                return n
        except Exception:                                      # noqa: BLE001
            continue
    return None


def _alone_raw_gains(row: dict, items: List[dict], idxs: List[int], probes: Dict[str, str],
                     full_years: int, credit_rows: Optional[List[dict]] = None) -> Dict[int, float]:
    """{index: what that item's answer moves the REAL score done ALONE on the page
    as it stands}. One copy, rolled back after each item. Read only when the
    page-order walk left points unplaced."""
    out: Dict[int, float] = {}
    sim = _Sim(row, credit_rows) if credit_rows else _Sim(row)
    base_raw = float(sim.measure()[1])
    saved = (copy.deepcopy(sim.session), set(sim.suppressed), set(sim.answered),
             list(sim.form_ids), getattr(sim, "_measured", None))
    for n in idxs:
        sim.session = copy.deepcopy(saved[0])
        sim.suppressed, sim.answered = set(saved[1]), set(saved[2])
        sim.form_ids, sim._measured = list(saved[3]), saved[4]
        try:
            if _apply(sim, items[n], probes, full_years):
                out[n] = max(0.0, float(sim.measure()[1]) - base_raw)
        except Exception:                                      # noqa: BLE001
            continue
    return out


def declare_follow_ups(row: dict, plan: Optional[dict]) -> Optional[dict]:
    """Rule G2 in any order on a built plan (`_declare_alone_follow_ups` over its
    own items), copied onto the plan's items by id; drops the private context.
    Names only - no number moves."""
    if not isinstance(plan, dict):
        return plan
    ctx = plan.pop("_ctx", None)
    if not ctx:
        return plan
    items, probes, full_years, credit_rows = ctx
    try:
        _declare_alone_follow_ups(row, items, probes, full_years, credit_rows)
    except Exception as exc:                                   # noqa: BLE001
        logger.debug("review plan: alone follow-ups not read: %s", exc)
        return plan
    leads = {it["id"]: it.get("leads_to") for it in items if it.get("leads_to")}
    for it in plan.get("items") or []:
        if isinstance(it, dict) and it.get("id") in leads:
            it["leads_to"] = list(leads[it["id"]])
    return plan


def _declare_upload_follow_ups(row: dict, items: List[dict], up: dict, probes: Dict[str, str],
                               full_years: int, credit_rows: Optional[List[dict]]) -> None:
    """THE UPLOAD ROW'S FOLLOW-UPS (owner rule G2, 30 Oct 2026). Complete loss
    runs arriving can raise what no answer on the page raises - "Do these loss
    runs belong to this insured?" (the match is not strong), the claims answer
    an attestation now contradicts, the prior carrier the runs make
    applicable, the years they cover, a stop their figures trigger. Whatever
    the person does first, those appear only once the runs are in, so the
    upload row names them (`leads_to`): the upload done ALONE on the page as it
    stands, then the Loss History plan and the stops read again. Display only -
    the row's points are the plan's."""
    from services import sqs_service as S
    sim = _Sim(row, credit_rows) if credit_rows else _Sim(row)
    start = _raised(sim)
    if not _apply(sim, up, probes, full_years):
        return
    sim.measure()
    pkg = getattr(sim, "last_pkg", None) or {}
    st = getattr(sim, "last_stops", None) or {}
    on_page = {str(it.get("label") or "")[:120] for it in items}
    leads = up.setdefault("leads_to", [])

    def add(label: Any) -> None:
        text = str(label or "")[:120]
        if text and text not in on_page and text not in leads:
            leads.append(text)

    facts, flags = sim.session["facts"], sim.session["flags"]
    try:
        steps = S.loss_history_plan(facts, flags, sim.session.get("docs") or [],
                                    pkg.get("pillars") or {}) or []
    except Exception:                                          # noqa: BLE001
        steps = []
    for s in steps:
        if isinstance(s, dict) and s.get("key") != "upload" and (
                int(s.get("points") or 0) > 0 or (s.get("key") in ("claims", "conflict") and s.get("applied"))):
            add(s.get("label"))
    raised = _raised(sim) - start
    for msg in (st.get("hard") or []) + (st.get("soft") or []) + [
            i.get("message") for i in (st.get("cross_issues") or []) if isinstance(i, dict)]:
        if ("stop", _shape(msg)) in raised:
            add(msg)
    if not leads:
        up.pop("leads_to", None)


def _raised_labels(sim: "_Sim") -> Dict[tuple, str]:
    """`_raised`'s signatures with the words a person reads for each."""
    sim.measure()
    st = getattr(sim, "last_stops", None) or {}
    pkg = getattr(sim, "last_pkg", None) or {}
    out: Dict[tuple, str] = {}
    for m in (st.get("hard") or []) + (st.get("soft") or []):
        out[("stop", _shape(m))] = str(m)
    for i in st.get("cross_issues") or []:
        if isinstance(i, dict) and i.get("message"):
            out[("stop", _shape(i["message"]))] = str(i["message"])
    for r in pkg.get("top_recommendations") or []:
        if isinstance(r, dict):
            out[("row", str(r.get("pillar")), _shape(r.get("field") or r.get("action") or ""))] = \
                str(r.get("action") or r.get("field") or "")
    out.update(_loss_plan_rows(sim, pkg))
    return out


def _declare_alone_follow_ups(row: dict, items: List[dict], probes: Dict[str, str],
                              full_years: int, credit_rows: Optional[List[dict]] = None) -> None:
    """Rule G2 in any order: each item done ALONE on the page as it stands; the
    items the page would then list that it does not list now are declared on
    it (`leads_to`), in the words that page shows (never a raw rule sentence -
    those name forms, G14). A Loss History row the copy cannot list (probe
    scoring leaves the plan's rows out) is read by `_loss_plan_rows`."""
    from services import sqs_service as S

    def fresh() -> "_Sim":
        return _Sim(row, credit_rows) if credit_rows else _Sim(row)

    def rule(x: dict) -> str:
        if x.get("code"):
            return "card:" + str(x["code"])
        keys = sorted(str(k) for k in (x.get("keys") or []))
        return f"{x.get('kind')}:" + (",".join(keys) or str(x.get("id")))

    start_rules = {rule(x) for x in items}
    listed_keys = {str(k) for x in items for k in (x.get("keys") or [])}
    base = fresh()
    base.measure()
    start_loss = _loss_plan_rows(base, getattr(base, "last_pkg", None) or {})
    start_raised = _raised(base)
    by_id = {x["id"]: x for x in items}
    # ONE copy, rolled back after each item (scored once per item, not twice).
    sim = base
    saved = (copy.deepcopy(sim.session), set(sim.suppressed), set(sim.answered),
             list(sim.form_ids), getattr(sim, "_measured", None))

    def rollback() -> None:
        sim.session = copy.deepcopy(saved[0])
        sim.suppressed, sim.answered = set(saved[1]), set(saved[2])
        sim.form_ids, sim._measured = list(saved[3]), saved[4]

    def _variants(it: dict) -> List[Dict[str, str]]:
        """The plan's own sample, then a realistic other answer per fact (a count
        other than the sample, another choice): what an answer raises can depend
        on the VALUE (live Orbin fb83c9c6, 30 Oct 2026: the sample "0 employees"
        raised nothing, the person's "6" raised the workers comp question)."""
        out: List[Dict[str, str]] = [{}]
        if it.get("kind") not in ("detail", "rec"):
            return out                       # cards / documents: their fix is fixed
        for k in it.get("keys") or []:
            if not str(k).startswith("fact:"):
                continue
            f = str(k)[5:]
            try:
                first = str(probe_value(f, row.get("facts") or {}, row))
            except Exception:                                  # noqa: BLE001
                first = ""
            alts: List[str] = []
            try:
                from services.answer_semantics import _declared_kind, _registry_entry
                kind = str(_declared_kind(f, _registry_entry(f)) or "")
            except Exception:                                  # noqa: BLE001
                kind = ""
            low = f.lower()
            if kind == "integer":
                # BOTH sides of a threshold rule ("more than 5 employees and no
                # workers comp": the sample 5 sits on the line - live Orbin
                # f80dd700, 31 Oct 2026): none, and clearly many.
                alts = ["0", "25"]
            elif kind in ("percent", "percentage") or "percent" in low or low.endswith("_pct"):
                alts = ["0", "60"]
            else:
                alts = [str(a) for a in _alternative_samples(f)][:1]
            for a in alts:
                if a != first and len(out) < 3:
                    out.append({f: a})
            if len(out) >= 3:
                break                        # at most two other answers per item
        return out

    def _declare_one(it: dict, forced: Dict[str, str]) -> None:
        rollback()
        sim.forced = dict(forced)
        try:
            if not _apply(sim, it, probes, full_years):
                return
            # Cheap first: an answer that raises no new stop, row or Loss History
            # row has nothing to declare (most items) - the page is read only
            # for the few that do.
            if not (_raised(sim) - start_raised):
                return
            pkg_now = getattr(sim, "last_pkg", None) or {}
            facts, flags = sim.session["facts"], sim.session["flags"]
            grouped_now = S.review_page_grouped_view(sim.session, pkg_now,
                                                     after_forms=not getattr(sim, "pre_form", True))
            fresh_items = page_items(sim.session, pkg_now, S.key_details(facts, flags), grouped_now)
            loss_now = _loss_plan_rows(sim, pkg_now)
        except Exception:                                      # noqa: BLE001
            return
        finally:
            sim.forced = {}
        new: List[str] = []
        for x in fresh_items:
            xk = [str(k) for k in (x.get("keys") or [])]
            if rule(x) in start_rules:
                continue
            if x.get("kind") not in ("card", "dc") and xk and all(k in listed_keys for k in xk):
                continue
            new.append(str(x.get("label") or ""))
        new += [lab for sig, lab in loss_now.items() if sig not in start_loss]
        if forced:
            # A note raised by a TRIED answer must not quote that answer's figures
            # ("reports 60% subcontracted" beside a person's 35%): figures out.
            import re as _re
            new = [_re.sub(r"\s{2,}", " ", _re.sub(r"\(?\$?\d[\d,.]*%?\)?", "", n)).strip(" -,;:") for n in new]
        new = [n[:120] for n in new if n]
        if not new:
            return
        owner = it
        while owner.get("mirror_of") in by_id:
            owner = by_id[owner["mirror_of"]]
        leads = owner.setdefault("leads_to", [])
        for lab in new:
            if lab not in leads:
                leads.append(lab)

    for it in items:
        if it.get("mirror_of") or it.get("kind") == "dc":
            continue
        for _forced in _variants(it):
            _declare_one(it, _forced)


def _signature(it: dict) -> Optional[tuple]:
    """A page item as `_raised` names what it raises."""
    if it.get("kind") == "card" and it.get("message"):
        return ("stop", _shape(it["message"]))
    if it.get("kind") == "rec":
        return ("row", str(it.get("pillar")), _shape(it.get("field") or it.get("label") or ""))
    return None


def _gaps_of(it: dict) -> tuple:
    res = it.get("resolution") if isinstance(it.get("resolution"), dict) else {}
    return tuple(sorted(str((g or {}).get("label") or "") for g in (res.get("gaps") or [])
                        if isinstance(g, dict)))


def _follow_ups(sim: "_Sim", items: List[dict], probes: Dict[str, str], full_years: int,
                raised_by: Dict[tuple, int], last_did: Optional[int],
                shown: float, row: Optional[dict] = None,
                credit_rows: Optional[List[dict]] = None) -> List[Tuple[int, float, float]]:
    """[(the step that raised it, gain, shown after)] for every item the page
    would list once the plan's steps are done, in up to three readings."""
    from services import sqs_service as S
    out: List[Tuple[int, float, float]] = []
    done_keys: set = {k for it in items for k in (it.get("keys") or [])}
    # (A narrative window whose topics changed is not "as it stood".)
    done_gaps: Dict[tuple, set] = {}
    for it in items:
        done_gaps.setdefault(tuple(it.get("keys") or []), set()).add(_gaps_of(it))
    for _reading in range(3):
        sim.measure()
        pkg_now = getattr(sim, "last_pkg", None) or {}
        facts, flags = sim.session["facts"], sim.session["flags"]
        kd_now = S.key_details(facts, flags)
        grouped_now = S.review_page_grouped_view(sim.session, pkg_now,
                                                 after_forms=not getattr(sim, "pre_form", True))
        # Every item the page would list then (an item answered above is a
        # no-op: its box is the person's answer now; `rec:<n>` ids are list
        # positions, so they say nothing about which row was done).
        fresh = page_items(sim.session, pkg_now, kd_now, grouped_now)
        moved = False
        for it in fresh:
            # An item whose fix the pass already offered, standing as it stood
            # then, is done (the person's answers are in): only a raised or a
            # changed item is a follow-up. Keeps the reading cheap.
            if (it["keys"] and all_covered(it["keys"], done_keys) and _signature(it) not in raised_by
                    and _gaps_of(it) in done_gaps.get(tuple(it["keys"]), {_gaps_of(it)})):
                continue
            before = shown
            raw_before = float(sim.measure()[1])
            if not _apply(sim, it, probes, full_years):
                continue
            _m = sim.measure()
            shown = max(_m[0], before)
            # The REAL score's move (R5 / P2, 30 Oct 2026): a follow-up is
            # weighed by what it moves the real score, never by a cap release.
            gain = max(0.0, float(_m[1]) - raw_before)
            if gain <= _EPS:
                # A raised item worth nothing yet (another hold still stands) is
                # still the raising step's declared follow-up (rule G2, 30 Oct
                # 2026): the page names it with that step, never as a surprise.
                _r0 = raised_by.get(_signature(it) or ("", ""))
                if _r0 is not None:
                    _f0 = items[_r0].get("mirror_of")
                    if _f0:
                        _r0 = next((n for n, x in enumerate(items) if x["id"] == _f0), _r0)
                    _lead = str(it.get("label") or "")[:120]
                    _leads = items[_r0].setdefault("leads_to", [])
                    if _lead and _lead not in _leads:
                        _leads.append(_lead)
                continue
            # Only the step that RAISED it owns a follow-up (hostile review, 30 Oct
            # 2026: the last step took one it never raised). Unknown = unowned
            # here; the points-to-owner pass below finds its owner.
            raiser = raised_by.get(_signature(it) or ("", ""))
            if raiser is None and row is not None:
                # Its signature moved while the walk ran (a count in the sentence
                # changed): the step that raises it is found by doing each step
                # ALONE on the page (second hostile review, 30 Oct 2026 - a
                # dropped follow-up left its points unowned).
                raiser = _raiser_alone(row, items, it, probes, full_years, credit_rows)
            if raiser is None:
                # No step raises it alone (it needs two): the last step that did
                # something owns it, its number "up to" (never unowned).
                raiser = last_did
                if raiser is not None:
                    items[raiser]["_guessed_follow"] = True
                    logger.warning("SCORING_FOLLOW_UP_RAISER_GUESSED item=%s credited to %s",
                                   it.get("id"), items[raiser].get("id"))
            if raiser is None:
                continue
            first = items[raiser].get("mirror_of")
            if first:
                raiser = next((n for n, x in enumerate(items) if x["id"] == first), raiser)
            leads = items[raiser].setdefault("leads_to", [])
            label = str(it.get("label") or "")[:120]
            if label and label not in leads:
                leads.append(label)
            out.append((raiser, gain, shown))
            moved = True
            if _floor(float(_m[1])) >= 100 and _floor(shown) >= 100:
                return out
        if not moved:
            break
    return out


# ── Sub-point rows merge (owner, 24 Oct 2026) ────────────────────────────────
# Two Recommendations rows in ONE pillar each worth under a point on their own
# (hydrant distance + fire department type, ~0.5 each) showed "under 1 pt" and
# "+1" by turns, flipping with fractions earlier on the page. They are one row:
# one window holding all their questions, the number what doing them together
# moves. A row worth a point or more, and a lone sub-point row, stay as they are.
MERGE_JOIN = " + "


def _mergeable(it: dict) -> bool:
    return (it.get("kind") == "rec" and not it.get("mirror_of") and it.get("held_by") is None
            and not it.get("prose") and not it.get("hedged") and it.get("pillar")
            and _EPS < float(it.get("real_gain", it.get("gain")) or 0.0) < 1.0 - _EPS
            and all(str(k).startswith("fact:") for k in (it.get("keys") or [])) and it.get("keys"))


def _codependent_rows(sim: "_Sim", it: dict, items: List[dict], raised_by: Dict[tuple, int],
                      idx: int) -> List[int]:
    """The listed Recommendations rows (their `row_index`) whose boxes are exactly
    what a check this step raised asks for. Only a Recommendations row joins one
    (rows merge into one window; a card or key detail keeps its declared cost)."""
    if it.get("kind") != "rec" or it.get("row_index") is None:
        return []
    from services.issue_registry import _legacy_message_resolution, resolution_for
    st = getattr(sim, "last_stops", None) or {}
    new_shapes = {sig[1] for sig, n in raised_by.items() if n == idx and sig[0] == "stop"}
    wanted: List[set] = []
    for m in (st.get("hard") or []) + (st.get("soft") or []):
        if _shape(m) in new_shapes:
            res = _legacy_message_resolution(str(m)) or {}
            if res.get("mode") == "field" and res.get("facts"):
                wanted.append({str(f) for f in res["facts"]})
    for i in st.get("cross_issues") or []:
        if isinstance(i, dict) and _shape(i.get("message")) in new_shapes:
            res = resolution_for(str(i.get("code") or "")) or {}
            if res.get("mode") == "field" and res.get("facts"):
                wanted.append({str(f) for f in res["facts"]})
    own = {str(k)[5:] for k in (it.get("keys") or []) if str(k).startswith("fact:")}
    out: List[int] = []
    for need in wanted:
        need = need - own
        if not need:
            continue
        for y in items:
            if y is it or y.get("kind") != "rec" or y.get("row_index") is None:
                continue
            ykeys = {str(k)[5:] for k in (y.get("keys") or []) if str(k).startswith("fact:")}
            if ykeys and need <= ykeys and int(y["row_index"]) not in out:
                out.append(int(y["row_index"]))
    return out


def join_codependent_rows(pkg: dict, plan: Optional[dict]) -> Optional[dict]:
    """A copy of `pkg` whose co-dependent rows (`items[].joins`, see
    `_codependent_rows`) are ONE row at the first one's place - every question in
    one window, so answering in any order never dips the score - or None."""
    if not isinstance(plan, dict) or not isinstance(pkg, dict):
        return None
    rows = pkg.get("top_recommendations")
    if not isinstance(rows, list):
        return None
    drop: set = set()
    out_rows = list(rows)
    for it in plan.get("items") or []:
        if not isinstance(it, dict) or not it.get("joins") or it.get("row_index") is None:
            continue
        x = int(it["row_index"])
        idx = [x] + [int(j) for j in it["joins"] if 0 <= int(j) < len(rows) and int(j) != x and int(j) not in drop]
        if x in drop or len(idx) < 2 or not all(isinstance(rows[i], dict) for i in idx):
            continue
        fields: List[str] = []
        for i in idx:
            for f in (rows[i].get("merged_fields") or [rows[i].get("field")]):
                if f and str(f) not in fields:
                    fields.append(str(f))
        joined = dict(out_rows[x])
        joined["action"] = MERGE_JOIN.join(
            dict.fromkeys(str(rows[i].get("action") or rows[i].get("field") or "").strip() for i in idx))
        joined["merged_fields"] = fields
        joined["resolution"] = merged_resolution(fields, None)
        joined["answer_mode"] = "field"
        for k in ("points_available", "potential_gain"):
            vals = [rows[i].get(k) for i in idx if isinstance(rows[i].get(k), (int, float))]
            if vals:
                joined[k] = sum(vals)
        out_rows[x] = joined
        drop.update(i for i in idx if i != x)
    if not drop:
        return None
    return {**pkg, "top_recommendations": [r for n, r in enumerate(out_rows) if n not in drop]}


def merged_resolution(fields: List[str], facts: Optional[dict] = None) -> dict:
    """One field window holding every merged row's questions: the facts' union,
    their controls merged (`issue_registry.field_resolution` per fact)."""
    out_facts: List[str] = []
    controls: Dict[str, Any] = {}
    needs: List[List[str]] = []
    for f in fields:
        try:
            from services.issue_registry import field_resolution
            res = field_resolution(f) or {}
        except Exception:                                      # noqa: BLE001
            res = {"mode": "field", "facts": [f]}
        group = [str(x) for x in (res.get("facts") or [f]) if x]
        for x in group:
            if x not in out_facts:
                out_facts.append(x)
        if group:
            needs.append(group)
        if isinstance(res.get("controls"), dict):
            for k, v in res["controls"].items():
                controls.setdefault(k, v)
    out: Dict[str, Any] = {"mode": "field", "facts": out_facts}
    # Each merged row is its own question, not "whichever applies": the window
    # names what is still blank and saves a partial answer as progress.
    if len(needs) > 1:
        out["needs"] = needs
    if controls:
        out["controls"] = controls
    return out


def saved_merged_groups(receipt_ids) -> Dict[str, List[List[str]]]:
    """{pillar: [[fact, ...], ...]} - merged rows a person already saved part of,
    read off their fix receipts' ids ("rec:score:<pillar>:fact:a|fact:b", the id
    the page gives a merged row). A half-saved merged row stays ONE row with every
    question in its window - the answered one shown and editable - never split
    into a lone row that hides the first answer (owner, 24 Oct 2026)."""
    out: Dict[str, List[List[str]]] = {}
    for rid in receipt_ids or []:
        rid = str(rid or "")
        if not rid.startswith("rec:score:") or "|" not in rid:
            continue
        pillar, _, keys = rid[len("rec:score:"):].partition(":")
        facts = [k[len("fact:"):] for k in keys.split("|") if k.startswith("fact:")]
        if pillar and len(facts) >= 2 and len(facts) == len(keys.split("|")):
            out.setdefault(pillar, []).append(facts)
    return out


def merge_subpoint_rows(pkg: dict, plan: Optional[dict],
                        saved_groups: Optional[Dict[str, List[List[str]]]] = None) -> Optional[dict]:
    """A copy of `pkg` whose same-pillar sub-point rows are one row (at the first
    one's place), or None when nothing merges. The plan is then built again on
    it, so the numbers and the page agree and still add up to 100 - score.
    `saved_groups` (`saved_merged_groups`): a merged row a person saved part of
    keeps its whole group - the still-open row carries the answered questions
    too, in the saved order, so its id (and its Resolved / Open again) is the
    one the first save used."""
    if not isinstance(plan, dict) or not isinstance(pkg, dict):
        return None
    rows = pkg.get("top_recommendations")
    if not isinstance(rows, list):
        return None
    groups: Dict[str, List[dict]] = {}
    for it in plan.get("items") or []:
        if isinstance(it, dict) and _mergeable(it):
            groups.setdefault(str(it["pillar"]), []).append(it)
    # A half-saved merged row: its open rows keep the saved group's questions.
    kept: Dict[int, List[str]] = {}
    for pillar, saved in (saved_groups or {}).items():
        for facts in saved:
            open_idx = [n for n, r in enumerate(rows) if isinstance(r, dict)
                        and str(r.get("pillar")) == pillar and r.get("field") in facts]
            if open_idx and len(open_idx) < len(facts):
                kept[open_idx[0]] = list(facts)
                for n in open_idx[1:]:
                    kept.setdefault(n, [])           # folded into the first
                groups.pop(pillar, None)
    groups = {p: g for p, g in groups.items() if len(g) >= 2}
    if not groups and not kept:
        return None
    if not groups:
        out_rows = list(rows)
        for n, facts in kept.items():
            if facts:
                r = dict(rows[n])
                r["merged_fields"] = facts
                r["resolution"] = merged_resolution(facts, None)
                r["answer_mode"] = "field"
                out_rows[n] = r
        return {**pkg, "top_recommendations": [r for n, r in enumerate(out_rows)
                                               if not (n in kept and not kept[n])]}
    drop: set = set()
    out_rows = list(rows)
    for pillar, members in groups.items():
        idx = [int(m["row_index"]) for m in members]
        first = rows[idx[0]]
        if not isinstance(first, dict):
            continue
        fields: List[str] = []
        for i in idx:
            r = rows[i]
            for f in (r.get("merged_fields") or [r.get("field")]):
                if f and f not in fields:
                    fields.append(str(f))
        merged = dict(first)
        merged["action"] = MERGE_JOIN.join(
            dict.fromkeys(str(rows[i].get("action") or rows[i].get("field") or "").strip() for i in idx))
        merged["merged_fields"] = fields
        merged["resolution"] = merged_resolution(fields, None)
        merged["answer_mode"] = "field"
        for k in ("points_available", "potential_gain"):
            vals = [rows[i].get(k) for i in idx if isinstance(rows[i].get(k), (int, float))]
            if vals:
                merged[k] = sum(vals)
        out_rows[idx[0]] = merged
        drop.update(idx[1:])
    return {**pkg, "top_recommendations": [r for n, r in enumerate(out_rows) if n not in drop]}
