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
calls a model. Before forms only - after forms the editor keeps its own numbers.
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
    "location": "001", "line_of_business": "General Liability",
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


def probe_value(fact: str, facts: Optional[dict] = None) -> str:
    """The value a person's answer to `fact` is stood in by: a choice the fact
    offers, a limit at the scorer's own threshold, a value of the shape its name
    says, a revenue / payroll the package's own ratio check accepts, else the
    scorer's own probe (`sqs_service._package_probe_answer`)."""
    from services import sqs_service as S
    facts = facts or {}
    low = str(fact or "").lower()
    # The claims question is stood in by the answer the person's own narrative
    # gives (24 Oct 2026): the other one raises `legacy_loss_narrative_mismatch`.
    if fact == "loss_history_no_prior_losses_indicator":
        try:
            from services.loss_history_state import claims_answer_for_narrative
            agreed = claims_answer_for_narrative(facts)
            if agreed:
                return agreed
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
    if fact in thresholds and not _fv(facts, fact):
        return str(int(thresholds[fact]))
    if fact == "naics_code":
        return _neutral_naics()
    if fact == "sic_code":
        return "8999"
    if fact in ("operations_description", "description_of_operations"):
        return _NEUTRAL_TEXT
    if fact == "total_revenue":
        pay = S._to_float(_fv(facts, "total_payroll") or _fv(facts, "wc_payroll"))
        return str(int(pay * 1.25)) if pay and pay > 0 else "1000000"
    if fact in ("total_payroll", "wc_payroll"):
        rev = S._to_float(_fv(facts, "total_revenue"))
        return str(int(rev * 0.5)) if rev and rev > 0 else "500000"
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

    def __init__(self, row: dict):
        self.session = dict(row or {})
        self.session["facts"] = dict((row or {}).get("facts") or {})
        self.session["flags"] = dict((row or {}).get("flags") or {})
        self.session["docs"] = [dict(d) if isinstance(d, dict) else d
                                for d in ((row or {}).get("docs") or [])]
        self.suppressed: set = set()
        self.form_ids = [r.get("form_id") for r in ((row or {}).get("recommendations") or [])
                         if isinstance(r, dict) and r.get("form_id")]

    # The displayed score as a FLOAT (the weighted sum before it is rounded
    # down, held at the cap) and the hold that binds it.
    def measure(self) -> Tuple[float, float, Optional[int], Optional[str]]:
        from services import sqs_service as S
        from services.stops_now import stops_now
        facts, flags = self.session["facts"], self.session["flags"]
        st = stops_now(self.session, self.form_ids, pre_form=True, facts=facts, flags=flags)
        # The scorer takes its stops from the one door, unfiltered.
        pkg = S._PACKAGE_SCORER(
            facts=facts, flags=flags, form_results=[], cross_issues=st["cross_issues"],
            hard_stops=st["hard"], soft_stops=st["soft"], session_data=self.session,
            _probe=True, form_fill=False)
        self.last_pkg = pkg
        raw = weighted_float(pkg.get("pillars") or {})
        cap, reason = _released_cap(pkg, st, self.suppressed)
        shown = min(raw, float(cap)) if cap is not None else raw
        return shown, raw, cap, reason

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
        clean, _report = SC.validate_rows(key, rows, shown=shown)
        # Cells every building already states (`confirm_columns`): the real
        # window SAVES the table anyway (frontend `tableIsSaved`), and only that
        # save carries them to the package (`derive_package_cope`) - an
        # unchanged table is still a save here (live c5dc03ec, 25 Oct 2026).
        if not res.get("confirm_columns") and json.dumps(
                [dict(r) for r in clean], sort_keys=True, default=str) == json.dumps(
                [dict(r) for r in shown], sort_keys=True, default=str):
            return False
        A._write_schedule_rows(facts, key, clean, "producer")
        return json.dumps(_fv(facts, key), sort_keys=True, default=str) != before

    def narrative(self, gaps: List[dict]) -> bool:
        """The remarks a person writes in the narrative window, one sentence per
        topic it lists (`arq_service.append_producer_narrative`)."""
        from services.arq_service import compose_narrative_answer
        # Never words that contradict the claims answer (24 Oct 2026): "No
        # prior losses: ..." beside "we have had claims" is its own warning.
        try:
            from services.loss_history_state import claims_answer_stance, text_claims_stance
            answer = claims_answer_stance(self.session["facts"])
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
        run_facts = {k: {"value": _fv(facts, k), "source": "policy_doc_text"}
                     for k in ("applicant_name", "fein") if _fv(facts, k)}
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
    # 4 + 5. Hard stops, then warnings - one item per rule code.
    seen_codes: set = set()
    for card in rendered_cards(grouped):
        code = str(card.get("code") or "")
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        items.append({"id": f"card:{code}", "kind": "card", "page": card["page"], "code": code,
                      "label": card.get("message") or code, "resolution": card.get("resolution"),
                      "message": card.get("message") or ""})
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
            facts = empty or facts
        except Exception:                                      # noqa: BLE001
            pass
        changed = False
        for f in facts:
            changed = sim.answer(f, probes.get(f) or probe_value(f, sim.session["facts"])) or changed
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
                    changed = sim.answer(f, probes.get(f) or probe_value(f, _sf)) or changed
        except Exception:                                      # noqa: BLE001
            pass
        return sim.table(str(res["schedule_key"]), res) or changed
    if mode == "narrative":
        gaps = res.get("gaps")
        if not isinstance(gaps, list):
            gaps = _narrative_gaps(sim)
        return sim.narrative(gaps)
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
    for i in st.get("cross_issues") or []:
        if isinstance(i, dict) and i.get("message"):
            (hard if i.get("type") == "hard_stop" else soft).append(i["message"])
    open_hard = [m for m in hard if m not in suppressed]
    open_soft = [m for m in soft if m not in suppressed]
    if int(cap) <= 60 and hard and not open_hard:
        cap, reason = (85, open_soft[0]) if open_soft else (None, None)
    if cap is not None and int(cap) == 85 and soft and not open_soft and not open_hard:
        cap, reason = None, None
    return cap, reason


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
                      grouped: Optional[dict] = None) -> Optional[dict]:
    """The page's items, weighed in page order. {"items": [...], "total": T,
    "end": the score the plan ends at, "left": the points no item adds}."""
    if not isinstance(pkg, dict) or not isinstance(row, dict):
        return None
    now = pkg.get("package_sqs_score")
    if now is None:
        return None
    total = max(0, 100 - int(now))
    items = page_items(row, pkg, kd, grouped)
    probes = _loss_plan_probes(pkg)
    try:
        from services.loss_history_state import loss_years_required
        full_years = int(loss_years_required(row.get("facts") or {}) or 5)
    except Exception:                                          # noqa: BLE001
        full_years = 5
    sim = _Sim(row)
    shown, raw, cap, reason = sim.measure()
    if _floor(shown) != int(now):
        logger.warning("review plan: simulated start %.3f is not the score %s", shown, now)
    gains: List[float] = []
    shown_after: List[float] = []
    applied_keys: List[Tuple[str, set]] = []
    for it in items:
        first = next((iid for iid, keys in applied_keys if all_covered(it["keys"], keys)), None)
        if first:
            it["mirror_of"] = first
        before_shown, before_raw, before_reason = shown, raw, reason
        did = False
        try:
            did = _apply(sim, it, probes, full_years)
        except Exception as exc:                               # noqa: BLE001
            logger.debug("review plan: step %s not simulated: %s", it.get("id"), exc)
        if did:
            shown, raw, cap, reason = sim.measure()
        # A step never lowers the score on screen: what it would cost here is
        # the package's, not the step's (it shows nothing for it).
        shown = max(shown, before_shown)
        it["gain"] = shown - before_shown
        it["held_by"] = (_hold_label(before_reason)
                         if did and it["gain"] <= _EPS and raw - before_raw > _EPS else None)
        gains.append(it["gain"])
        shown_after.append(shown)
        applied_keys.append((it["id"], set(it["keys"])))
    up_index = next((n for n, it in enumerate(items)
                     if it["kind"] == "doc" and it.get("step") == "upload"), None)
    ints, under = _whole_points(shown_after, gains, int(now), up_index)
    reached = max([int(now)] + [_floor(v) for v in shown_after])
    left = 0 if up_index is not None else max(0, 100 - reached)
    by_id = {it["id"]: it for it in items}
    for it, n, small in zip(items, ints, under):
        it["points"] = int(n)
        it["under"] = bool(small)
        it["exact"] = not it.get("prose") and not it.get("hedged") and it.get("held_by") is None
    for it in items:
        if it.get("mirror_of") in by_id:
            it["mirror"] = int(by_id[it["mirror_of"]]["points"])
    return {"items": [{k: v for k, v in it.items() if k not in ("resolution",)} for it in items],
            "total": total, "end": round(shown, 4), "left": int(left)}


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
            and _EPS < float(it.get("gain") or 0.0) < 1.0 - _EPS
            and all(str(k).startswith("fact:") for k in (it.get("keys") or [])) and it.get("keys"))


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
