"""Runtime invariant checker (owner, 30 Oct 2026).

Bugs kept being found one live package at a time. Each rule below states a
CLASS of wrong behaviour that must never hold on ANY package; `check` runs them
all on a session at a pipeline stage and returns the breaches. The hooks
(merge, pre-form scoring, generation, recalculation) only LOG them:

    INVARIANT_BROKEN rule=<id> stage=<s> session=<id> where=<w> detail=<d>

Contract: never raises, never mutates the session, never calls an LLM or the
network. Every rule asks the existing door (named in its description) - never a
second copy of its logic. `INVARIANTS=0` turns the hooks off.

`session` is the stored row shape (facts, flags, docs, package_sqs,
generated_forms, pre_form_score, hard_stops, soft_stops, structured_issues).
At stage "pre_form" the caller may add `_page`: {"package_sqs": <what the page
prints>, "saved_pre_form_score": <the dashboard copy just saved>}.
"""
from __future__ import annotations

import copy
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

STAGES = ("merge", "pre_form", "generation", "after_forms")

RULES: Dict[str, str] = {
    "prior_policy_placed_once":
        "Every prior policy is in the ACORD 125 prior grid or on ACORD 101 - never lost, never both; "
        "the grid is keyed by year when any policy is dated (pdf_service._prior_coverage_grid_build / "
        "prior_grid_set_aside_rows).",
    "fixed_format_identifiers":
        "A VIN that is not 17 characters (model year 1981+) is named by a warning "
        "(sqs_service.vehicles_with_bad_vin).",
    "points_add_up":
        "Before forms the review plan's points add up to exactly 100 - score; no negatives, no number "
        "on a mirror, nothing numbered at 100 (review_plan).",
    "cap_matches_stops":
        "An open hard stop holds the package at 60 or below, an open warning at 85; a 60 cap names a "
        "hard stop; Submission Ready never beside a hard stop (readiness_fields).",
    "form_score_matches_holds":
        "After forms a form's own hard stop holds it at 60, its open warning at 85, and a held form "
        "names its hold (sqs_service._form_download_blocker / _form_open_warning).",
    "every_item_answerable":
        "Every listed hard stop has a resolution; a listed warning with none is released by the safety "
        "net (issue_registry / release_unanswerable_holds).",
    "no_foreign_insured_facts":
        "No applicant-scoped fact whose only documents name another insured "
        "(insured_scope.facts_only_another_insured_states).",
    "dashboard_equals_page":
        "Before forms the dashboard's pre_form_score equals the score the page prints.",
    "loss_window_consistent":
        "loss_run_valuation_date is at least the latest included loss run's date and the period ends "
        "no earlier than the latest included run (loss_history_state).",
    "no_placeholder_or_list_in_boxes":
        "No stamped box holds a leaked placeholder, a Python list / dict repr, or None / nan text.",
    "insured_is_not_carrier_or_agency":
        "G10: the applicant's name / FEIN / mailing address never equal a carrier's or the producer's.",
    "no_duplicate_rows":
        "G11: one row per VIN, per driver (name + birth date), per claim number, per premises address+building.",
    "limits_make_sense":
        "G12: GL each occurrence never exceeds the GL aggregate; the GL limit is never the umbrella limit "
        "when they differ in the documents.",
    "no_form_numbers_before_forms":
        "G14: before forms, no listed card names an ACORD form number.",
    "no_item_listed_twice":
        "G15: the same card (rule + message) is never listed twice in one screen section.",
    "every_fix_opens_something":
        "G16: every listed card with a fix offers a box, a table or a narrative.",
    "schedule_counts_match_forms":
        "G17: after forms, the vehicles / drivers the facts hold (up to a form's rows) are all printed on "
        "the ACORD 127.",
    "terms_run_forward":
        "G3: every term pair the package holds - proposed, prior, umbrella - ends after it starts "
        "(a mixed-source pair is repaired by extraction_service.follow_proposed_expiration).",
    "every_form_deduction_has_a_card":
        "G18: after forms, with the package at 100, a form below 100 lists something to answer "
        "(a card, a required box or a hold) - never a deduction with nothing to fix.",
    "fix_windows_offer_only_needed_boxes":
        "G1: a listed card's field fix never offers a box holding a good value beside one that needs "
        "fixing (issue_registry.boxes_that_need_fixing).",
}


def enabled() -> bool:
    return str(os.getenv("INVARIANTS", "1")).strip().lower() not in ("0", "false", "off", "no")


def _v(raw: Any) -> Any:
    """A fact's value (envelope or bare)."""
    if isinstance(raw, dict) and "value" in raw:
        return raw.get("value")
    return raw


def _breach(rule: str, detail: str, where: str = "") -> dict:
    return {"rule": rule, "detail": str(detail)[:200], "where": str(where or "")[:120]}


def _facts(session: dict) -> dict:
    f = session.get("facts")
    return f if isinstance(f, dict) else {}


def _pkg(session: dict) -> Optional[dict]:
    page = session.get("_page") if isinstance(session.get("_page"), dict) else {}
    p = page.get("package_sqs") if page else None
    if not isinstance(p, dict):
        p = session.get("package_sqs")
    return p if isinstance(p, dict) else None


def _score(pkg: Optional[dict]) -> Optional[int]:
    s = (pkg or {}).get("package_sqs_score")
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        return int(round(float(s)))
    return None


# ── 1 ─────────────────────────────────────────────────────────────────────────
def _norm_no(v: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(v or "").lower())


def rule_prior_policy_placed_once(session: dict, stage: str) -> List[dict]:
    facts = _facts(session)
    entries = _v(facts.get("prior_coverage_by_line"))
    if not isinstance(entries, list) or not any(isinstance(e, dict) for e in entries):
        return []
    from services.pdf_service import _prior_coverage_grid_build
    grid, years = _prior_coverage_grid_build(copy.deepcopy(facts))
    out: List[dict] = []
    placed = [e for e in grid.values() if isinstance(e, dict)]
    aside = [e for e in (getattr(grid, "set_aside", ()) or ()) if isinstance(e, dict)]
    # Never in both: the same entry object, or the same number for the same year.
    placed_keys = {(_norm_no(e.get("policy_no")), str(e.get("effective") or "")[-4:])
                   for e in placed if _norm_no(e.get("policy_no"))}
    for e in aside:
        k = (_norm_no(e.get("policy_no")), str(e.get("effective") or "")[-4:])
        if any(e is p for p in placed) or (k[0] and k in placed_keys):
            out.append(_breach("prior_policy_placed_once", "policy both in the grid and on ACORD 101",
                               "ACORD_125"))
    # Keyed by year whenever a placed policy is dated.
    if placed and not years and any(re.search(r"\b(?:19|20)\d{2}\b", str(e.get("effective") or ""))
                                    for e in placed):
        out.append(_breach("prior_policy_placed_once", "grid holds dated policies but is not keyed by year",
                           "ACORD_125"))
    # None lost: a numbered prior policy of the grid's years appears somewhere.
    shown = {_norm_no(e.get("policy_no")) for e in placed + aside} - {""}
    cur_no = _norm_no(_v(facts.get("policy_number")))
    for e in entries:
        if not isinstance(e, dict):
            continue
        n = _norm_no(e.get("policy_no"))
        if not n or n == cur_no:
            continue
        y = (re.search(r"\b(?:19|20)\d{2}\b", str(e.get("effective") or "")) or [None])[0]
        if years and y and y not in years:
            continue                       # outside the history window - not the form's to list
        if any(n == s or n in s or s in n for s in shown):
            continue
        out.append(_breach("prior_policy_placed_once", "prior policy on neither the grid nor ACORD 101",
                           "prior_coverage_by_line"))
    return out


# ── 2 ─────────────────────────────────────────────────────────────────────────
def _all_stop_text(session: dict) -> str:
    parts: List[str] = []
    for k in ("hard_stops", "soft_stops"):
        parts += [str(m) for m in (session.get(k) or [])]
    for i in session.get("structured_issues") or []:
        if isinstance(i, dict):
            parts.append(str(i.get("message") or ""))
            parts.append(str(i.get("code") or ""))
    pkg = _pkg(session) or {}
    parts += [str(m) for m in (pkg.get("ready_blockers") or [])]
    return " \n".join(parts)


def rule_fixed_format_identifiers(session: dict, stage: str) -> List[dict]:
    if stage == "merge":
        return []                          # stops are built after the merge
    from services.sqs_service import vehicles_with_bad_vin
    bad = vehicles_with_bad_vin(_facts(session))
    if not bad:
        return []
    if re.search(r"\bVIN\b|vin", _all_stop_text(session)):
        return []
    return [_breach("fixed_format_identifiers", f"{len(bad)} malformed VIN(s) with no warning naming them",
                    "auto_vin_schedule")]


# ── 3 ─────────────────────────────────────────────────────────────────────────
def rule_points_add_up(session: dict, stage: str) -> List[dict]:
    if stage != "pre_form":
        return []
    pkg = _pkg(session)
    plan = (pkg or {}).get("review_plan")
    now = _score(pkg)
    if not isinstance(plan, dict) or now is None:
        return []
    items = [i for i in (plan.get("items") or []) if isinstance(i, dict)]
    out: List[dict] = []
    # R5 / P2 (30 Oct 2026): the points add up to 100 - the REAL score; a cap
    # holds the shown number down and is never counted as points.
    now = int(plan.get("real", now))
    total = 0
    for it in items:
        pts = int(it.get("points") or 0)
        if pts < 0:
            out.append(_breach("points_add_up", "negative points", str(it.get("id"))))
        if it.get("mirror_of") and pts:
            out.append(_breach("points_add_up", "a mirror carries its own number", str(it.get("id"))))
        if now >= 100 and (pts or it.get("under")):
            out.append(_breach("points_add_up", "a number listed at 100", str(it.get("id"))))
        if not it.get("mirror_of"):
            total += max(0, pts)
    if total != max(0, 100 - now):
        out.append(_breach("points_add_up", f"points add up to {total}, page needs {max(0, 100 - now)}",
                           "review_plan"))
    if plan.get("contract_repaired"):
        out.append(_breach("points_add_up", f"plan repaired: {len(plan['contract_repaired'])} rule(s)",
                           "review_plan"))
    return out


# ── 4 ─────────────────────────────────────────────────────────────────────────
def rule_cap_matches_stops(session: dict, stage: str) -> List[dict]:
    pkg = _pkg(session)
    score = _score(pkg)
    if score is None:
        return []
    out: List[dict] = []
    blockers = [m for m in (pkg.get("ready_blockers") or []) if m]
    open_hard = int(pkg.get("open_hard_stops") or len(blockers) or 0)
    if open_hard and score > 60:
        out.append(_breach("cap_matches_stops", f"{open_hard} open hard stop(s) but score above 60", "package"))
    if open_hard and pkg.get("submission_ready"):
        out.append(_breach("cap_matches_stops", "Submission Ready beside an open hard stop", "package"))
    cap = pkg.get("cap_applied")
    if cap == 60 and not open_hard and not (pkg.get("cap_hard_stops") or []):
        out.append(_breach("cap_matches_stops", "score is 60 but no hard stop is named", "package"))
    if cap is not None and score > int(cap):
        out.append(_breach("cap_matches_stops", f"score above its own cap {cap}", "package"))
    # The stored stop lists (what the screen lists) against the number.
    hard = [m for m in (session.get("hard_stops") or []) if m]
    if stage == "pre_form" and hard and score > 60 and not open_hard:
        out.append(_breach("cap_matches_stops", f"{len(hard)} listed hard stop(s) but score above 60",
                           "package"))
    return out


# ── 5 ─────────────────────────────────────────────────────────────────────────
def rule_form_score_matches_holds(session: dict, stage: str) -> List[dict]:
    if stage not in ("generation", "after_forms"):
        return []
    from services.sqs_service import _form_download_blocker
    out: List[dict] = []
    for fid, gen in (session.get("generated_forms") or {}).items():
        if not isinstance(gen, dict):
            continue
        sqs = gen.get("sqs") if isinstance(gen.get("sqs"), dict) else None
        s = (sqs or {}).get("sqs_score")
        if not isinstance(s, (int, float)) or isinstance(s, bool):
            continue
        mapped = gen.get("mapped") if isinstance(gen.get("mapped"), dict) else {}
        conf = gen.get("confidence") if isinstance(gen.get("confidence"), dict) else {}
        if _form_download_blocker(fid, mapped, conf) and s > 60:
            out.append(_breach("form_score_matches_holds", "form's own hard stop open but score above 60", fid))
        cap = sqs.get("cap_applied")
        if cap is not None and s > int(cap):
            out.append(_breach("form_score_matches_holds", f"score above its own cap {cap}", fid))
        if cap == 60 and not (sqs.get("ready_blockers") or sqs.get("cap_hard_stops")):
            out.append(_breach("form_score_matches_holds", "score is 60 but no hard stop is named", fid))
        raw = sqs.get("raw_sqs_score")
        if cap is None and isinstance(raw, (int, float)) and s < raw:
            out.append(_breach("form_score_matches_holds", "score below its raw score with no hold", fid))
    return out


# ── 6 ─────────────────────────────────────────────────────────────────────────
def _dc_messages(session: dict) -> set:
    cached = session.get("_inv_dc_msgs")
    if cached is None:
        try:
            from services.stops_now import conflict_stop_facts
            cached = set(conflict_stop_facts(session).keys())
        except Exception:                                      # noqa: BLE001
            cached = set()
        session["_inv_dc_msgs"] = cached
    return cached


def rule_every_item_answerable(session: dict, stage: str) -> List[dict]:
    if stage == "merge":
        return []
    hard = {str(m) for m in (session.get("hard_stops") or []) if m}
    soft = {str(m) for m in (session.get("soft_stops") or []) if m}
    if not hard and not soft:
        return []
    pkg = _pkg(session) or {}
    released = {str(n.get("label") or "") for n in (pkg.get("not_scored") or []) if isinstance(n, dict)}
    out: List[dict] = []
    for i in session.get("structured_issues") or []:
        if not isinstance(i, dict) or i.get("score_neutral") or i.get("form_choice"):
            continue
        msg = str(i.get("message") or "")
        if msg not in hard and msg not in soft:
            continue
        res = i.get("resolution") if isinstance(i.get("resolution"), dict) else {}
        if res.get("add_forms") or (res.get("mode") and res.get("mode") != "none"):
            continue
        # A document disagreement is answered in Data Consistency (its card's
        # "Fix in Data Consistency"), not in a fix window.
        if msg in _dc_messages(session):
            continue
        if msg in hard:
            out.append(_breach("every_item_answerable", "hard stop with no answer", str(i.get("code"))))
        elif msg[:200] not in released and pkg.get("cap_applied") == 85 \
                and str(pkg.get("cap_reason") or "") == msg:
            out.append(_breach("every_item_answerable", "unanswerable warning still holds the 85",
                               str(i.get("code"))))
    return out


# ── 7 ─────────────────────────────────────────────────────────────────────────
def rule_no_foreign_insured_facts(session: dict, stage: str) -> List[dict]:
    from services.insured_scope import facts_only_another_insured_states
    from services.stops_now import active_documents
    hits = facts_only_another_insured_states(_facts(session), active_documents(session))
    return [_breach("no_foreign_insured_facts", "only another insured's documents state it", k)
            for k in sorted(hits)]


# ── 8 ─────────────────────────────────────────────────────────────────────────
def rule_dashboard_equals_page(session: dict, stage: str) -> List[dict]:
    if stage != "pre_form" or session.get("generated_forms"):
        return []
    page = session.get("_page") if isinstance(session.get("_page"), dict) else {}
    now = _score(page.get("package_sqs"))
    if now is None:
        return []
    saved = page.get("saved_pre_form_score", session.get("pre_form_score"))
    s = _score(saved) if isinstance(saved, dict) else None
    if s != now:
        return [_breach("dashboard_equals_page", f"dashboard {s} vs page {now}", "pre_form_score")]
    return []


# ── 9 ─────────────────────────────────────────────────────────────────────────
def rule_loss_window_consistent(session: dict, stage: str) -> List[dict]:
    from services.fact_state import typed_by_person
    from services.loss_history_state import loss_period_date
    facts = _facts(session)
    runs = [d for d in (session.get("docs") or []) if isinstance(d, dict) and not d.get("excluded")
            and d.get("doc_type") == "loss_run"]
    if not runs:
        return []
    out: List[dict] = []
    vals = [loss_period_date((d.get("facts") or {}).get("loss_run_valuation_date")) for d in runs]
    vals = [v for v in vals if v]
    if vals and not typed_by_person(facts.get("loss_run_valuation_date")):
        cur = loss_period_date(facts.get("loss_run_valuation_date"))
        if cur is None or cur < max(vals):
            out.append(_breach("loss_window_consistent", "valuation date older than the latest loss run",
                               "loss_run_valuation_date"))
    ends = [loss_period_date((d.get("facts") or {}).get("loss_run_period_end"), end=True) for d in runs]
    ends = [e for e in ends if e]
    if ends and not typed_by_person(facts.get("loss_run_period_end")):
        cur = loss_period_date(facts.get("loss_run_period_end"), end=True)
        if cur is None or cur < max(ends):
            out.append(_breach("loss_window_consistent", "loss period ends before the latest loss run",
                               "loss_run_period_end"))
    return out


# ── 10 ────────────────────────────────────────────────────────────────────────
_REPR_RE = re.compile(r"^\s*(\[\s*['\"{\[]|\{\s*['\"]\w+['\"]\s*:)")
_NULL_TEXT = {"none", "nan", "null", "undefined"}


def rule_no_placeholder_or_list_in_boxes(session: dict, stage: str) -> List[dict]:
    if stage not in ("generation", "after_forms"):
        return []
    from services.placeholder_detector import is_placeholder_value
    out: List[dict] = []
    for fid, gen in (session.get("generated_forms") or {}).items():
        mapped = (gen or {}).get("mapped") if isinstance(gen, dict) else None
        if not isinstance(mapped, dict):
            continue
        for box, val in mapped.items():
            if isinstance(val, (list, dict)):
                out.append(_breach("no_placeholder_or_list_in_boxes", "a list / dict in a box", f"{fid}:{box}"))
                continue
            if not isinstance(val, str) or not val.strip():
                continue
            t = val.strip()
            if t.lower() in _NULL_TEXT:
                out.append(_breach("no_placeholder_or_list_in_boxes", "None / nan text in a box", f"{fid}:{box}"))
            elif _REPR_RE.match(t):
                out.append(_breach("no_placeholder_or_list_in_boxes", "a Python repr in a box", f"{fid}:{box}"))
            elif is_placeholder_value(t)[0]:
                out.append(_breach("no_placeholder_or_list_in_boxes", "a leaked placeholder", f"{fid}:{box}"))
    return out


def _fv(facts, k):
    v = (facts or {}).get(k)
    return v.get("value") if isinstance(v, dict) and "value" in v else v


def _norm(v) -> str:
    import re as _re
    return _re.sub(r"[^a-z0-9]", "", str(v or "").lower())


def rule_insured_is_not_carrier_or_agency(session: dict, stage: str) -> List[dict]:
    f = session.get("facts") or {}
    out = []
    name = _norm(_fv(f, "applicant_name"))
    others = {_norm(_fv(f, k)) for k in ("carrier_name", "producer_name", "agency_name", "prior_carrier_name")}
    lines = _fv(f, "coverage_lines")
    for r in lines if isinstance(lines, list) else []:
        if isinstance(r, dict):
            others.add(_norm(r.get("carrier") or r.get("carrier_name")))
    others.discard("")
    if name and name in others:
        out.append(_breach("insured_is_not_carrier_or_agency", "applicant name equals a carrier / agency", "applicant_name"))
    mail = _norm(_fv(f, "mailing_address"))
    if mail and mail == _norm(_fv(f, "producer_address")):
        out.append(_breach("insured_is_not_carrier_or_agency", "mailing address equals the producer's", "mailing_address"))
    fein = _norm(_fv(f, "fein"))
    if fein and fein in {_norm(_fv(f, k)) for k in ("carrier_naic", "producer_code")} - {""}:
        out.append(_breach("insured_is_not_carrier_or_agency", "FEIN equals a carrier / producer code", "fein"))
    return out


def rule_no_duplicate_rows(session: dict, stage: str) -> List[dict]:
    f = session.get("facts") or {}
    out = []
    def dup(key, fn, label):
        rows = _fv(f, key)
        seen = set()
        for r in rows if isinstance(rows, list) else []:
            if not isinstance(r, dict):
                continue
            k = fn(r)
            if not k:
                continue
            if k in seen:
                out.append(_breach("no_duplicate_rows", f"{label} listed twice", key))
                return
            seen.add(k)
    dup("auto_vin_schedule", lambda r: _norm(r.get("vin")) if len(_norm(r.get("vin"))) >= 11 else "", "a VIN")
    dup("auto_drivers", lambda r: (_norm(r.get("name")), _norm(r.get("dob") or r.get("date_of_birth")))
        if _norm(r.get("name")) and _norm(r.get("dob") or r.get("date_of_birth")) else "", "a driver")
    dup("loss_history", lambda r: _norm(r.get("claim_number")) if len(_norm(r.get("claim_number"))) >= 4 else "", "a claim")
    dup("property_locations", lambda r: (_norm(r.get("address") or r.get("address_line1")),
                                         _norm(r.get("building_number")) or "1")
        if _norm(r.get("address") or r.get("address_line1")) else "", "a premises building")
    return out


def rule_limits_make_sense(session: dict, stage: str) -> List[dict]:
    f = session.get("facts") or {}
    try:
        from services.sqs_service import _to_float
    except Exception:                                          # noqa: BLE001
        return []
    out = []
    occ, agg = _to_float(_fv(f, "gl_each_occurrence")), _to_float(_fv(f, "gl_aggregate"))
    if occ and agg and occ > agg:
        out.append(_breach("limits_make_sense", "GL each occurrence above the aggregate", "gl_each_occurrence"))
    umb = _to_float(_fv(f, "umbrella_limit"))
    if umb and occ and umb == occ and agg and umb > agg:
        out.append(_breach("limits_make_sense", "GL occurrence equals the umbrella limit", "gl_each_occurrence"))
    return out


def _cards(view: Any):
    def walk(x, sec):
        if isinstance(x, dict):
            if x.get("message") and (x.get("code") or x.get("issue_id")):
                yield sec, x
                return
            for k, v in x.items():
                yield from walk(v, sec or k)
        elif isinstance(x, list):
            for v in x:
                yield from walk(v, sec)
    yield from walk(view or {}, "")


def _grouped(session: dict) -> dict:
    """The cards the screen draws: the stored view, else the review page's own
    door (`sqs_service.review_page_grouped_view`), built once per check."""
    gi = session.get("grouped_issues")
    if isinstance(gi, dict) and gi:
        return gi
    cached = session.get("_inv_grouped")
    if isinstance(cached, dict):
        return cached
    try:
        from services.sqs_service import review_page_grouped_view
        pkg = (session.get("_page") or {}).get("package_sqs") or session.get("package_sqs")
        gi = review_page_grouped_view(session, pkg, after_forms=bool(session.get("generated_forms"))) or {}
    except Exception:                                          # noqa: BLE001
        gi = {}
    session["_inv_grouped"] = gi
    return gi


def rule_no_form_numbers_before_forms(session: dict, stage: str) -> List[dict]:
    import re as _re
    if stage != "pre_form" or session.get("generated_forms"):
        return []
    gi = _grouped(session)
    out = []
    for sec, c in _cards({k: gi.get(k) for k in ("hard_stops", "warnings")}):
        if _re.search(r"\bACORD[\s_]*\d{2,3}\b", str(c.get("message") or "")):
            out.append(_breach("no_form_numbers_before_forms", "a pre-form card names a form", str(c.get("code") or "")))
    return out


def rule_every_form_deduction_has_a_card(session: dict, stage: str) -> List[dict]:
    if stage != "after_forms" or not session.get("generated_forms"):
        return []
    pkg = _pkg(session) or {}
    if pkg.get("package_sqs_score") != 100:
        return []                       # the package's own items come first
    out = []
    for fid, g in (session.get("generated_forms") or {}).items():
        q = (g or {}).get("sqs") or {} if isinstance(g, dict) else {}
        raw = q.get("raw_sqs_score")
        if not isinstance(raw, (int, float)) or raw >= 100:
            continue
        cards = [r for r in q.get("recommendations") or []
                 if isinstance(r, dict) and r.get("answer_mode") in ("field", "schedule", "narrative")]
        holds = (q.get("cap_hard_stops") or []) + (q.get("cap_soft_stops") or [])
        if not cards and not holds:
            out.append(_breach("every_form_deduction_has_a_card",
                               f"{fid} at {raw} with nothing to answer", str(fid)))
    return out


def rule_no_item_listed_twice(session: dict, stage: str) -> List[dict]:
    gi = _grouped(session)
    out = []
    for top in ("hard_stops", "warnings"):
        seen = set()
        for _sec, c in _cards(gi.get(top)):
            k = (c.get("code"), str(c.get("message") or "").strip())
            if k in seen:
                out.append(_breach("no_item_listed_twice", "a card listed twice", str(c.get("code") or "")))
            seen.add(k)
    return out


def rule_every_fix_opens_something(session: dict, stage: str) -> List[dict]:
    gi = _grouped(session)
    out = []
    for _sec, c in _cards({k: gi.get(k) for k in ("hard_stops", "warnings")}):
        r = c.get("resolution")
        if not isinstance(r, dict):
            continue
        m = r.get("mode")
        if (m == "field" and not r.get("facts")) or (m == "schedule" and not r.get("schedule_key")):
            out.append(_breach("every_fix_opens_something", f"{m} fix with nothing to open", str(c.get("code") or "")))
    return out


def rule_schedule_counts_match_forms(session: dict, stage: str) -> List[dict]:
    gen = session.get("generated_forms") or {}
    g = gen.get("ACORD_127") if isinstance(gen, dict) else None
    if not isinstance(g, dict):
        return []
    f = session.get("facts") or {}
    vins = [_norm(r.get("vin")) for r in (_fv(f, "auto_vin_schedule") or []) if isinstance(r, dict) and _norm(r.get("vin"))]
    mapped = g.get("field_state") or g.get("mapped") or {}
    printed = {_norm(v) for k, v in mapped.items() if str(k).startswith("Vehicle_VINIdentifier_") and v}
    cap = sum(1 for k in (g.get("schema") or {}) if str(k).startswith("Vehicle_VINIdentifier_")) or len(vins)
    missing = [v for v in vins[:cap] if v not in printed]
    if vins and missing:
        return [_breach("schedule_counts_match_forms", f"{len(missing)} vehicle(s) not printed on ACORD 127", "auto_vin_schedule")]
    return []


_TERM_PAIRS = (("effective_date", "expiration_date", "proposed term"),
               ("prior_effective_date", "prior_expiration_date", "prior term"),
               ("umbrella_effective_date", "umbrella_expiration_date", "umbrella term"))


def rule_terms_run_forward(session: dict, stage: str) -> List[dict]:
    from services.normalization import normalize_date
    facts = session.get("facts") or {}
    out = []
    for a, b, label in _TERM_PAIRS:
        va, vb = facts.get(a), facts.get(b)
        va = va.get("value") if isinstance(va, dict) else va
        vb = vb.get("value") if isinstance(vb, dict) else vb
        na, nb = normalize_date(str(va or "")), normalize_date(str(vb or ""))
        if na and nb and nb <= na:
            out.append(_breach("terms_run_forward", f"{label} ends on or before it starts", a))
    return out


def rule_fix_windows_offer_only_needed_boxes(session: dict, stage: str) -> List[dict]:
    from services.issue_registry import boxes_that_need_fixing, rule_code_of
    facts = session.get("facts") or {}
    out = []
    def walk(x):
        if isinstance(x, dict):
            res = x.get("resolution")
            if x.get("message") and isinstance(res, dict) and res.get("mode") == "field":
                narrowed = boxes_that_need_fixing(res, facts, rule_code_of(x))
                if list(narrowed.get("facts") or []) != list(res.get("facts") or []):
                    out.append(_breach("fix_windows_offer_only_needed_boxes",
                                       f"card offers {len(res.get('facts') or [])} boxes, "
                                       f"{len(narrowed.get('facts') or [])} need fixing",
                                       str(x.get("code") or "")))
                return
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(_grouped(session))
    return out


_RULE_FUNCS: Dict[str, Callable[[dict, str], List[dict]]] = {
    "terms_run_forward": rule_terms_run_forward,
    "insured_is_not_carrier_or_agency": rule_insured_is_not_carrier_or_agency,
    "no_duplicate_rows": rule_no_duplicate_rows,
    "limits_make_sense": rule_limits_make_sense,
    "no_form_numbers_before_forms": rule_no_form_numbers_before_forms,
    "no_item_listed_twice": rule_no_item_listed_twice,
    "every_form_deduction_has_a_card": rule_every_form_deduction_has_a_card,
    "every_fix_opens_something": rule_every_fix_opens_something,
    "schedule_counts_match_forms": rule_schedule_counts_match_forms,
    "fix_windows_offer_only_needed_boxes": rule_fix_windows_offer_only_needed_boxes,
    "prior_policy_placed_once": rule_prior_policy_placed_once,
    "fixed_format_identifiers": rule_fixed_format_identifiers,
    "points_add_up": rule_points_add_up,
    "cap_matches_stops": rule_cap_matches_stops,
    "form_score_matches_holds": rule_form_score_matches_holds,
    "every_item_answerable": rule_every_item_answerable,
    "no_foreign_insured_facts": rule_no_foreign_insured_facts,
    "dashboard_equals_page": rule_dashboard_equals_page,
    "loss_window_consistent": rule_loss_window_consistent,
    "no_placeholder_or_list_in_boxes": rule_no_placeholder_or_list_in_boxes,
}


def check(session: dict, *, stage: str) -> List[dict]:
    """Every breach of every rule on `session` at `stage`. Never raises, never
    mutates the session (each rule reads a deep copy)."""
    if not isinstance(session, dict) or stage not in STAGES:
        return []
    try:
        view = copy.deepcopy(session)
    except Exception:                                          # noqa: BLE001
        return []
    out: List[dict] = []
    for rid, fn in _RULE_FUNCS.items():
        try:
            out.extend(fn(view, stage) or [])
        except Exception as exc:                               # noqa: BLE001
            logger.debug("invariant %s skipped: %s", rid, exc)
    return out


def log_breaches(session: Optional[dict], *, stage: str, session_id: Any = None) -> List[dict]:
    """The hooks' one call: check and log each breach at WARNING. Never raises;
    a no-op with INVARIANTS=0."""
    if not enabled():
        return []
    try:
        sid = session_id or (session or {}).get("id") or (session or {}).get("session_id") or ""
        breaches = check(session or {}, stage=stage)
        for b in breaches:
            logger.warning("INVARIANT_BROKEN rule=%s stage=%s session=%s where=%s detail=%s",
                           b["rule"], stage, sid, b["where"], b["detail"])
        return breaches
    except Exception as exc:                                   # noqa: BLE001
        logger.debug("invariants not checked: %s", exc)
        return []
