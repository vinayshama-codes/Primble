"""THE LOSS HISTORY PLAN, WALKED END TO END (owner, 23-24 Oct 2026, package 5472449a).

The owner's live journey on a package where every other pillar was 100:

    "no losses"                                   100
    Brent's claims .xlsx uploaded, unclassified   91   (conflict, Loss History 45)
    answered the conflict "Yes, we had claims"    88   - a truthful answer LOWERED it
    the only row: "Mark '<file>' as Loss runs" +12
    marked it                                     90   - +2, and then 4 NEW rows

Spot fixes had each looked at one screen. ONE model now holds for every Loss
History state (`sqs_service.loss_history_plan` decides the steps; the review page
weighs every item it offers in page order, `services/review_plan.py`):

  * the conflict card first (its own truthful answer), a file to mark, the
    prior carrier, ownership, years (only when the runs' own years raise it),
    "requested" (only with no runs and nothing to mark), ONE upload row that
    takes the residual - and the claims question last, where its number would
    depend on which answer is true;
  * every number is what the score gains when the step is done after the
    steps above it, so the numbers add up to 100 minus the score, the top step
    lands its number, and the others keep theirs;
  * while No Known Losses conflicts with the claims, Loss History is
    min(45, the value once the claims are confirmed) - a truthful answer never
    lowers it.

The invariants checked at EVERY step of every journey:
  I1 the Loss History items add up to its share of 100 - score (every other
     pillar is 100 here, so: to 100 - score), and so does the whole page;
  I2 doing the top step raises the score by its number (+-1);
  I3 no step and no truthful answer lowers the score;
  I4 no two items for one action, no "requested" row while a file can be
     marked, no listed item at 0 points;
  I5 after the top step the other steps keep their numbers (+-1) and no new
     step appears;
  I6 walked to its end (the upload done as complete runs: the required years,
     valued within 90 days, the insured's FEIN) every journey ends at exactly
     100, and without the upload at exactly 100 minus the upload row's start.
"""
from __future__ import annotations

import copy
import random
from datetime import date, timedelta

import pytest

from services import issue_registry as IR
from services import sqs_service as S
from services.answer_semantics import build_fact_envelope, interpret_answer
from services.loss_history_state import (
    LOSS_RUN_OWNERSHIP_FIELD, LOSS_RUN_OWNERSHIP_OPTIONS, LOSS_RUN_STATUS_OPTIONS,
    claims_question_answers, package_has_loss_runs,
)
from services.review_recommendations import with_fix_routes

NO_CLAIMS, HAD_CLAIMS = claims_question_answers()
YES = LOSS_RUN_OWNERSHIP_OPTIONS[0]
REQUESTED = LOSS_RUN_STATUS_OPTIONS[0]
INDICATOR = S.LOSS_PLAN_CLAIMS_FACT
CONFLICT = S.LOSS_PLAN_CONFLICT_CODE
INSURED = "CHOICE ELECTRIC LLC"
FEIN = "84-1234567"
SHEET = "Primble Choice Electric Synthetic Claims.xlsx"
CONFLICT_MESSAGE = ("Data consistency: a No Known Losses attestation conflicts with claims found in "
                    "the uploaded loss runs. Loss History is held at 45 until the discrepancy is "
                    "resolved - confirm with the insured which is correct.")
NARRATIVE = (
    "Company overview: Choice Electric LLC is a family-owned electrical contractor, in business since 2010, "
    "with 20 years of experience in commercial electrical work. Operations include tenant improvement wiring "
    "and service work; the scope of work is primarily commercial. The management team is experienced "
    "management with a licensed master electrician; the owner has run the business since it was founded. "
    "Risk controls: a written safety program, safety training and a preventive maintenance program. Claims "
    "history: the loss history is documented in the carrier loss runs. Coverage discussion: general liability "
    "limits requested of $1,000,000 per occurrence with an umbrella. Current carrier Amerisure; this is a "
    "renewal and the account is seeking competitive terms. Location exposure: one premises, number of "
    "locations 1. Employee handbook and hiring practices; workforce of full-time staff, annual revenue of "
    "$5,000,000. WC class code 5190 payroll by class; experience modifier (emod) 0.95."
)


def _env(v, source="producer"):
    return {"value": v, "source": source, "confidence": "producer"}


def _doc_env(v):
    return {"value": v, "source": "document", "confidence": "high"}


def _claims(years=(2025,), prefix="SIM"):
    rows = []
    for y in years:
        for n in range(2):
            rows.append({"date": f"0{n + 3}/1{n}/{y}", "claim_date": f"0{n + 3}/1{n + 2}/{y}",
                         "description": f"Third-party property damage {y}-{n}", "paid": "4200",
                         "amount": "4200", "reserved_amount": "0", "open": False, "open_code": "C",
                         "claim_number": f"{prefix}-{y}-{n}", "line_of_business": "General Liability"})
    return rows


DEC = {"doc_type": "dec_page", "filename": "25-26 Package Policy.pdf", "doc_id": "dec1",
       "facts": {"applicant_name": _doc_env(INSURED), "fein": _doc_env(FEIN),
                 "carrier_name": _doc_env("AMERISURE INSURANCE COMPANY")}}


def _base_facts(age):
    f = {k: _env("x") for k in list(S.TIER1_FIELDS) + list(S.TIER2_FIELDS)}
    f.update({"applicant_name": _env(INSURED), "effective_date": _env("01/01/2027"),
              "mailing_address": _env("1234 W Colfax Ave, Denver, CO 80204"),
              "producer_name": _env("Front Range Insurance Agency"), "entity_type": _env("LLC"),
              "lines_of_business": _env("General Liability"),
              "expiration_date": _env("01/01/2028"), "contact_name": _env("Dana"),
              "num_employees": _env("0"), "naics_code": _env("238210"),
              "total_revenue": _env("$5,000,000"), "fein": _env(FEIN),
              "operations_description": _env("Electrical contractor"),
              "additional_remarks_text": _env(NARRATIVE),
              "umbrella_limit": _env("5000000"), "gl_each_occurrence": _env("1000000"),
              "gl_aggregate": _env("2000000"),
              "schedule_of_underlying_insurance": _env("General Liability $1,000,000 / Auto Liability $1,000,000"),
              "umbrella_follow_form": _env("Follows form - explicitly stated in the submitted documents"),
              "prior_carrier": {"value": "AMERISURE INSURANCE COMPANY", "source": "derived",
                                "derivation": {"rule": "carrier_of_the_expiring_policies"}}})
    if age is None:
        # Age unknown. A person's typed N/A is no answer for years in business
        # since the 29 Oct strict review (`fact_registry.ALWAYS_EXISTS`); the
        # system's own "not applicable" still leaves the denominator (TEST
        # outdated, updated by the 29 Oct end-user review).
        f["years_in_business"] = {"value": None, "value_state": "not_applicable", "source": "derived"}
    else:
        f["years_in_business"] = _env(str(age))
    return f


def _sync_cards(row):
    """The conflict card as the upload and the recalculation keep it."""
    live = S._loss_history_conflict(row["facts"], row["flags"],
                                    package_has_loss_runs(row["docs"], row["facts"]))
    issues = [i for i in row.get("structured_issues") or [] if i.get("code") != CONFLICT]
    if live:
        issues.append(IR.make_issue(CONFLICT, "soft_warning", CONFLICT_MESSAGE))
    row["structured_issues"] = issues
    return row


def _row(age=15, sheet=False, attested=False, had_claims=False, years=(2025,), pending=False,
         sheet_fein=None):
    facts = _base_facts(age)
    flags = {"has_umbrella": True}
    docs = [copy.deepcopy(DEC)]
    if attested:
        facts[INDICATOR] = _env(NO_CLAIMS)
        flags["no_prior_losses"] = True
    if had_claims:
        facts[INDICATOR] = _env(HAD_CLAIMS)
    if pending:
        facts["loss_run_status"] = _env(REQUESTED)
    if sheet:
        rows = _claims(years)
        sheet_facts = {"applicant_name": _doc_env(INSURED), "loss_history": _doc_env(rows),
                       "num_claims": _doc_env(str(len(rows)))}
        if sheet_fein:
            sheet_facts["fein"] = _doc_env(sheet_fein)
        docs.append({"doc_type": "unknown", "filename": SHEET, "doc_id": "sheet1",
                     "classification": {"confidence": "low", "scores": {"loss_run": 2.8}},
                     "facts": sheet_facts})
        facts["loss_history"] = _doc_env(rows)
        facts["num_claims"] = _doc_env(str(len(rows)))
    return _sync_cards({"facts": facts, "flags": flags, "docs": docs, "recommendations": [],
                        "structured_issues": []})


# ── The page, as the review screen reads it ──────────────────────────────────
def _page(row):
    pkg = S.score_package_pre_generation(row)
    pkg = with_fix_routes(pkg, row["facts"])
    kd = S.key_details(row["facts"], row["flags"])
    pkg, _kd = S.complete_screen_shares(row, "s", "u", pkg, kd)
    return pkg


def _score(pkg):
    return int(pkg["package_sqs_score"])


def _lh(pkg):
    p = pkg["pillars"]["loss_history_alignment"]
    return p.get("score") if isinstance(p, dict) else p


def _loss_items(pkg):
    """The Loss History items in page order: its rows, its document rows and the
    conflict warning card."""
    out = []
    for it in (pkg.get("review_plan") or {}).get("items") or []:
        if (it["kind"] == "rec" and it.get("pillar") == "loss_history_alignment") \
                or it["kind"] == "doc" or (it["kind"] == "card" and it.get("code") == CONFLICT):
            out.append(it)
    return out


def _listed(pkg):
    """What the page lists for Loss History with a number (or a hold / under 1)."""
    return [it for it in _loss_items(pkg)
            if not it.get("mirror_of") and (it["points"] > 0 or it.get("held_by") or it.get("under"))]


def _steps(pkg):
    """The steps a person takes, in plan order: the conflict card first when it
    is on the page (its own answer), then every listed row."""
    card = [it for it in _loss_items(pkg) if it["kind"] == "card"]
    rows = [it for it in _listed(pkg) if it["kind"] != "card"]
    return card + rows


def _key(it):
    return (it["kind"], it.get("field") or it.get("step") or it.get("code"))


# ── Doing a step, as the page's doors do it ──────────────────────────────────
def _answer(row, fact, value):
    row["facts"][fact] = build_fact_envelope(fact, interpret_answer(fact, value), "producer", "filled")
    if fact == INDICATOR:
        row["flags"]["no_prior_losses"] = bool(S._attested_true(value))


def _upload(row, years, fein=FEIN):
    today = date.today()
    start = date(today.year - years, today.month, min(today.day, 28))
    runs = _claims(tuple(range(today.year - years, today.year)), prefix="RUN")
    facts = {"applicant_name": _doc_env(INSURED), "loss_history": _doc_env(runs)}
    if fein:
        facts["fein"] = _doc_env(fein)
    row["docs"].append({"doc_type": "loss_run", "filename": "carrier loss runs.pdf", "doc_id": "runs1",
                        "facts": facts})
    merged = (S._fv(row["facts"], "loss_history") or []) + runs
    row["facts"].update({"loss_history": _doc_env(merged), "num_claims": _doc_env(str(len(merged))),
                         "loss_run_period_start": _doc_env(start.isoformat()),
                         "loss_run_period_end": _doc_env(today.isoformat()),
                         "loss_run_valuation_date": _doc_env((today - timedelta(days=10)).isoformat())})


def _required_years(row):
    from services.loss_history_state import loss_years_required
    return int(loss_years_required(row["facts"]) or 5)


def _do(row, pkg, it, fein=FEIN):
    row = copy.deepcopy(row)
    probes = S.loss_plan_probes(pkg.get("loss_plan"))
    if it["kind"] == "card":
        _answer(row, INDICATOR, HAD_CLAIMS)
    elif it["kind"] == "doc" and it.get("step") == "mark":
        for d in row["docs"]:
            if d.get("doc_id") == it.get("doc_id"):
                d["doc_type"] = "loss_run"
    elif it["kind"] == "doc":
        _upload(row, _required_years(row), fein=fein)
    else:
        _answer(row, it["field"], probes.get(it["field"]) or S._package_probe_answer(it["field"])[0])
    return _sync_cards(row)


# ── The invariants ───────────────────────────────────────────────────────────
def _check_page(pkg, where):
    plan = pkg["review_plan"]
    total = 100 - _score(pkg)
    page = sum(i["points"] for i in plan["items"]) + int(plan.get("left") or 0)
    assert page == total, f"{where}: I1 the page shows {page}, 100 - score is {total}"
    loss = sum(i["points"] for i in _loss_items(pkg))
    assert loss == total, f"{where}: I1 Loss History shows {loss}, its share is {total}"
    keys = [_key(i) for i in _listed(pkg)]
    assert len(keys) == len(set(keys)), f"{where}: I4 two items for one action {keys}"
    if any(i.get("step") == "mark" for i in _listed(pkg)):
        assert not any(i.get("field") == "loss_run_status" for i in _listed(pkg)), \
            f"{where}: I4 a 'requested' row while a file can be marked"
    for i in _listed(pkg):
        assert i["points"] > 0 or i.get("held_by") or i.get("under"), f"{where}: I4 a 0-point item"


def _walk(row, pick, where, fein=FEIN, skip_upload=False, max_steps=12):
    """Do the steps `pick` chooses until none is left; check every invariant on
    the way. Returns (the score at the start, the scores, the upload's start
    points, the final page)."""
    pkg = _page(row)
    _check_page(pkg, f"{where} start")
    start_upload = next((i["points"] for i in _loss_items(pkg) if i.get("step") == "upload"), 0)
    scores = [_score(pkg)]
    done = set()
    for n in range(max_steps):
        steps = [s for s in _steps(pkg) if _key(s) not in done
                 and not (skip_upload and s.get("step") == "upload")]
        if not steps:
            break
        top = pick(steps)
        done.add(_key(top))
        before = {(_key(i)): i["points"] for i in _listed(pkg) if _key(i) != _key(top)}
        new_row = _do(row, pkg, top, fein=fein)
        after_pkg = _page(new_row)
        moved = _score(after_pkg) - _score(pkg)
        label = f"{where} step {n + 1} ({_key(top)})"
        assert moved >= 0, f"{label}: I3 the step LOWERED the score by {-moved}"
        _check_page(after_pkg, label)
        if pick is _first:
            assert abs(moved - top["points"]) <= 1, f"{label}: I2 showed {top['points']}, moved {moved}"
            now = {_key(i): i["points"] for i in _listed(after_pkg)}
            for k, pts in before.items():
                if k in now:
                    assert abs(now[k] - pts) <= 1, f"{label}: I5 {k} changed {pts} -> {now[k]}"
            for k in now:
                assert k in before or k in done, f"{label}: I5 a NEW step appeared: {k}"
        row, pkg = new_row, after_pkg
        scores.append(_score(pkg))
    return scores, start_upload, pkg


def _first(steps):
    return steps[0]


def _last(steps):
    return steps[-1]


def _shuffled(seed):
    rng = random.Random(seed)
    return lambda steps: steps[rng.randrange(len(steps))]


# ── The states, from the Choice Electric shape ───────────────────────────────
AGES = [15, 3, None]
STATES = {
    "no file": dict(),
    "no file, had claims": dict(had_claims=True),
    "no file, requested": dict(had_claims=True, pending=True),
    "claims file, unanswered": dict(sheet=True),
    "claims file, conflict": dict(sheet=True, attested=True),
    "claims file, had claims": dict(sheet=True, had_claims=True),
    "claims file, 5 claim years": dict(sheet=True, had_claims=True, years=(2021, 2022, 2023, 2024, 2025)),
    "claims file showing the FEIN": dict(sheet=True, had_claims=True, sheet_fein=FEIN),
}


def test_every_other_pillar_is_100_in_the_fixture():
    for age in AGES:
        pkg = _page(_row(age=age))
        pillars = {k: (v.get("score") if isinstance(v, dict) else v) for k, v in pkg["pillars"].items()}
        assert all(v == 100 for k, v in pillars.items() if k != "loss_history_alignment"), pillars
        assert pkg.get("cap_applied") is None


@pytest.mark.parametrize("age", AGES)
@pytest.mark.parametrize("state", list(STATES))
def test_walked_in_plan_order_every_invariant_holds_and_it_ends_at_100(age, state):
    row = _row(age=age, **STATES[state])
    scores, _upload_pts, end = _walk(row, _first, f"{state} / age {age} / plan order")
    assert scores[-1] == 100, (state, age, scores)                     # I6
    assert all(b >= a for a, b in zip(scores, scores[1:])), scores      # I3


@pytest.mark.parametrize("age", AGES)
@pytest.mark.parametrize("state", list(STATES))
def test_without_the_upload_it_ends_at_100_minus_the_upload_rows_start(age, state):
    row = _row(age=age, **STATES[state])
    scores, upload_pts, _end = _walk(row, _first, f"{state} / age {age} / answers only", skip_upload=True)
    assert scores[-1] == 100 - upload_pts, (state, age, scores, upload_pts)   # I6


@pytest.mark.parametrize("age", AGES)
@pytest.mark.parametrize("state", ["claims file, conflict", "claims file, had claims",
                                   "claims file, 5 claim years", "no file, had claims"])
@pytest.mark.parametrize("order", ["bottom up", "shuffled"])
def test_in_another_order_the_sums_hold_nothing_lowers_and_it_ends_at_100(age, state, order):
    pick = _last if order == "bottom up" else _shuffled(hash((age, state)) % 1000)
    row = _row(age=age, **STATES[state])
    scores, upload_pts, _end = _walk(row, pick, f"{state} / age {age} / {order}")
    assert scores[-1] == 100, (state, age, order, scores)
    row = _row(age=age, **STATES[state])
    scores, upload_pts, _end = _walk(row, pick, f"{state} / age {age} / {order} / no upload",
                                     skip_upload=True)
    assert scores[-1] == 100 - upload_pts, (state, age, order, scores, upload_pts)


# ── The owner's exact journey (5472449a) ─────────────────────────────────────
def _shown(pkg):
    return [(i["kind"], i.get("step") or i.get("field") or i.get("code"), i["points"])
            for i in _steps(pkg)]


def test_the_owners_journey_scores_and_rows():
    # 1. "no losses": Loss History is out of the score.
    row = _row(attested=True)
    pkg = _page(row)
    assert (_score(pkg), _lh(pkg)) == (100, None)
    assert _loss_items(pkg) == []
    # 2. Brent's claims sheet arrives, unclassified, its claim rows read: the
    # attestation now conflicts. Never above the honest answer: min(45, 25).
    row = _row(attested=True, sheet=True)
    pkg = _page(row)
    assert (_score(pkg), _lh(pkg)) == (88, 25)
    assert _shown(pkg) == [("card", CONFLICT, 0), ("doc", "mark", 2),
                           ("rec", LOSS_RUN_OWNERSHIP_FIELD, 4), ("doc", "upload", 6)]
    # 3. The truthful answer to the conflict: no drop, the same three rows.
    row = _do(row, pkg, _steps(pkg)[0])
    pkg = _page(row)
    assert (_score(pkg), _lh(pkg)) == (88, 25)
    assert _shown(pkg) == [("doc", "mark", 2), ("rec", LOSS_RUN_OWNERSHIP_FIELD, 4), ("doc", "upload", 6)]
    # 4. Marked: +2, and no new row.
    row = _do(row, pkg, _steps(pkg)[0])
    pkg = _page(row)
    assert (_score(pkg), _lh(pkg)) == (90, 35)
    assert _shown(pkg) == [("rec", LOSS_RUN_OWNERSHIP_FIELD, 4), ("doc", "upload", 6)]
    # 5. Ownership confirmed: +4.
    row = _do(row, pkg, _steps(pkg)[0])
    pkg = _page(row)
    assert (_score(pkg), _lh(pkg)) == (94, 60)
    assert _shown(pkg) == [("doc", "upload", 6)]
    # 6. Complete runs: +6, exactly 100.
    row = _do(row, pkg, _steps(pkg)[0])
    pkg = _page(row)
    assert (_score(pkg), _lh(pkg)) == (100, 100)
    assert _loss_items(pkg) == []


def test_the_owners_journey_marking_before_answering_the_conflict():
    """Marking first (the conflict skipped): the 45 binds only once the honest
    value passes it - then the conflict card, not a document row, shows it."""
    row = _row(attested=True, sheet=True)
    pkg = _page(row)
    mark = next(i for i in _steps(pkg) if i.get("step") == "mark")
    row = _do(row, pkg, mark)
    pkg = _page(row)
    assert (_score(pkg), _lh(pkg)) == (90, 35)                      # +2, as shown
    own = next(i for i in _steps(pkg) if i.get("field") == LOSS_RUN_OWNERSHIP_FIELD)
    row = _do(row, pkg, own)
    pkg = _page(row)
    assert (_score(pkg), _lh(pkg)) == (91, 45)                      # the 45 binds: the conflict was skipped
    card = next(i for i in _loss_items(pkg) if i["kind"] == "card")
    assert card["points"] == 3                                       # the release, on the card
    assert not any(i["kind"] == "doc" and not i.get("step") for i in _loss_items(pkg))
    _check_page(pkg, "marked first")


# ── The rules underneath ─────────────────────────────────────────────────────
@pytest.mark.parametrize("age", AGES)
def test_a_truthful_answer_to_the_conflict_never_lowers_loss_history(age):
    for kw in (dict(sheet=True), dict(sheet=True, pending=True), dict(sheet=True, years=(2021, 2025))):
        row = _row(age=age, attested=True, **kw)
        before = _page(row)
        answered = copy.deepcopy(row)
        _answer(answered, INDICATOR, HAD_CLAIMS)
        after = _page(_sync_cards(answered))
        assert _lh(after) >= _lh(before) and _score(after) >= _score(before), (age, kw)
        assert _lh(before) <= 45


def test_the_conflict_is_the_lower_of_45_and_the_honest_value():
    facts = _base_facts(15)
    facts.update({INDICATOR: _env(NO_CLAIMS), "loss_history": _doc_env(_claims()), "num_claims": _doc_env("2")})
    flags = {"no_prior_losses": True}
    assert S.calculate_p4_loss_history(facts, flags)[0] == 25           # no runs: claims known = 25
    assert S.calculate_p4_loss_history(facts, flags, True, "strong")[0] == 45   # runs: the 45 binds
    # A narrative's statement, contradicted by corroborated claims, is settled by
    # the person's "we have had claims" (no conflict left, no credit for it).
    facts2 = dict(facts, **{INDICATOR: _env(HAD_CLAIMS)})
    flags2 = {"narrative_states_no_losses": True}
    assert S._loss_history_conflict(facts2, flags2) is False
    assert S.calculate_p4_loss_history(facts2, flags2)[0] == 25


def test_marking_never_makes_a_new_row_appear():
    for kw in (dict(sheet=True), dict(sheet=True, attested=True), dict(sheet=True, years=(2021, 2022, 2023, 2024, 2025))):
        row = _row(**kw)
        pkg = _page(row)
        mark = next(i for i in _steps(pkg) if i.get("step") == "mark")
        before = {_key(i) for i in _listed(pkg)}
        after = _page(_do(row, pkg, mark))
        assert {_key(i) for i in _listed(after)} <= before, kw


def test_years_are_listed_only_when_the_runs_own_years_raise_the_score():
    one = _page(_do(_row(sheet=True, had_claims=True), _page(_row(sheet=True, had_claims=True)),
                    next(i for i in _steps(_page(_row(sheet=True, had_claims=True))) if i.get("step") == "mark")))
    assert not any(i.get("field") == "loss_history_years" for i in _listed(one))   # 1 year: adds nothing
    row = _row(sheet=True, had_claims=True, years=(2021, 2022, 2023, 2024, 2025))
    pkg = _page(row)
    years = [i for i in _listed(pkg) if i.get("field") == "loss_history_years"]
    assert years and years[0]["points"] > 0
    assert S.loss_plan_probes(pkg["loss_plan"])["loss_history_years"] == "5"


def test_with_nothing_known_the_claims_question_comes_first():
    """Owner, 24 Oct 2026: a business with no losses reaches 100 by answering.
    Nothing known -> the one step is the claims question, worth the whole gap
    (weighed with "no claims"); an honest "we have had claims" brings the
    request and upload rows."""
    for age in AGES:
        pkg = _page(_row(age=age))
        steps = [(i.get("field") or i.get("step")) for i in _steps(pkg)]
        assert steps == [INDICATOR], (age, steps)
        row = _row(age=age)
        _answer(row, INDICATOR, NO_CLAIMS)
        assert _score(_page(row)) == 100
        row = _row(age=age)
        _answer(row, INDICATOR, HAD_CLAIMS)
        steps = [(i.get("field") or i.get("step")) for i in _steps(_page(row))]
        assert steps == ["loss_run_status", "upload"], (age, steps)


def test_complete_runs_without_a_fein_still_land_on_an_ownership_step():
    """Runs that do not show the FEIN are not what the upload row asks for: the
    score still never drops, the page then offers the ownership answer, and that
    answer lands its number."""
    row = _row(had_claims=True)
    pkg = _page(row)
    up = next(i for i in _steps(pkg) if i.get("step") == "upload")
    row = _do(row, pkg, up, fein=None)
    after = _page(row)
    assert _score(after) >= _score(pkg)
    _check_page(after, "runs without a FEIN")
    own = [i for i in _listed(after) if i.get("field") == LOSS_RUN_OWNERSHIP_FIELD]
    assert own
    done = _page(_do(row, after, own[0]))
    assert _score(done) == 100 and abs(_score(done) - _score(after) - own[0]["points"]) <= 1


def test_the_upload_row_is_one_row_with_the_owners_words():
    pkg = _page(_row(sheet=True, had_claims=True))
    docs = [u for u in pkg["screen_unanswerable"] if u.get("action") == "add_documents"]
    assert [u["step"] for u in docs] == ["mark", "upload"]
    assert docs[1]["label"] == S.LOSS_PLAN_LABELS["upload"]
    assert all(isinstance(u.get("plan_order"), int) for u in docs)
    for r in pkg["top_recommendations"]:
        if r.get("pillar") == "loss_history_alignment":
            assert isinstance(r.get("plan_order"), int)
    texts = " ".join(u["label"] for u in pkg["screen_unanswerable"]).lower()
    assert "earlier years" not in texts and "with a valuation date" not in texts


# ── The page's own helpers read the plan (frontend, run by node) ─────────────
import json as _json
import pathlib as _pathlib
import shutil as _shutil
import subprocess as _subprocess

_UTILS = _pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "utils"
_needs_node = pytest.mark.skipif(_shutil.which("node") is None, reason="node is not installed")


def _node(tmp_path, body):
    script = tmp_path / "plan.mjs"
    script.write_text(
        f"import * as R from {_json.dumps((_UTILS / 'recommendations.js').as_uri())};\n"
        f"import * as P from {_json.dumps((_UTILS / 'screenPoints.js').as_uri())};\n{body}\n",
        encoding="utf-8")
    run = _subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return _json.loads(run.stdout)


def _page_payload(row):
    from services.issue_registry import grouped_with_package_caps
    from services.stops_now import stops_now
    pkg = _page(row)
    st = stops_now(row, pre_form=True)
    grouped = grouped_with_package_caps(row["structured_issues"], st["hard"], st["soft"], pkg,
                                        cross_issues=st["cross_issues"], facts=row["facts"])
    return {"package_sqs": pkg, "grouped_issues": grouped,
            "key_details": S.key_details(row["facts"], row["flags"])}


@_needs_node
@pytest.mark.parametrize("state", ["claims file, conflict", "claims file, 5 claim years", "no file"])
def test_the_page_lists_loss_history_in_plan_order_and_its_numbers_add_up(tmp_path, state):
    payload = _page_payload(_row(**STATES[state]))
    o = _node(tmp_path, (
        f"const er = {_json.dumps(payload, default=str)};\n"
        "const pkg = er.package_sqs;\n"
        "const model = R.buildRecommendations({packageSqs: pkg, groupedIssues: er.grouped_issues, keyDetails: er.key_details});\n"
        "const sp = P.screenPoints(pkg, er.grouped_issues, er.key_details);\n"
        "const docs = sp.unanswerable.filter((u) => u.action === 'add_documents');\n"
        "const seq = R.scoreSequence(model.score, docs).map((e) => e.kind === 'doc' ? 'doc:' + e.doc.step : 'row:' + e.item.detail);\n"
        "let shown = model.score.reduce((n, it) => n + (it.points.points || 0), 0) + docs.reduce((n, u) => n + u.points, 0);\n"
        "for (const v of sp.cards.values()) shown += v.points - (v.mirror || 0);\n"
        "for (const v of sp.details.values()) shown += v.points;\n"
        "console.log(JSON.stringify({seq, shown, score: pkg.package_sqs_score,\n"
        "  texts: model.score.map((it) => R.pointsText(it.points)),\n"
        "  card: sp.cards.has('loss_history_attestation_conflict') ? P.screenPointsText(sp.cards.get('loss_history_attestation_conflict')) : null}));"))
    assert o["shown"] == 100 - o["score"], o                                  # I1, as the page adds it
    steps = [("doc:" + (i.get("step") or "")) if i["kind"] == "doc" else ("row:" + i["label"])
             for i in _listed(_page(_row(**STATES[state]))) if i["kind"] != "card"]
    assert o["seq"] == steps, o                                               # the plan's order
    assert all(t.endswith(" pts") for t in o["texts"])
    if state == "claims file, conflict":
        assert o["card"] in ("", "No effect on the score")                    # 29 Oct: a 0 says it is not scored


@_needs_node
def test_the_points_text_names_a_hold_a_fraction_and_a_mirror(tmp_path):
    o = _node(tmp_path, (
        "const row = (extra) => ({pillar: 'loss_history_alignment', field: 'f', plan_id: 'rec:1', answer_gain: 0, answer_gain_share: true, ...extra});\n"
        "console.log(JSON.stringify({\n"
        "  held: R.pointsText(R.pointsFor(row({answer_gain_held_by: 'Property Minimum Viable COPE incomplete'}))),\n"
        "  under: R.pointsText(R.pointsFor(row({answer_gain_under: true}))),\n"
        "  zero: R.pointsFor(row({})),\n"
        "  three: R.pointsText(R.pointsFor(row({answer_gain: 3, answer_gain_is_exact: true}))),\n"
        "  mirror: R.pointsFor(row({answer_gain_mirror_of: 'card:x', answer_gain_mirror: 4})),\n"
        "  cardHeld: P.screenPointsText({points: 0, held: 'X'}),\n"
        "  cardUnder: P.screenPointsText({points: 0, under: true}),\n"
        "}));"))
    assert o["held"] == "Counts once Property Minimum Viable COPE incomplete is fixed"
    assert o["under"] == "under 1 pt"
    assert o["zero"] is None                                   # adds nothing: not listed
    assert o["three"] == "+3 pts"
    assert o["mirror"] == {"points": 4, "exact": True, "share": True, "mirror": True}
    assert o["cardHeld"] == "Counts once X is fixed" and o["cardUnder"] == "under 1 pt"


def test_no_ui_text_added_here_carries_an_em_dash():
    root = _pathlib.Path(__file__).resolve().parents[2]
    for rel in ("frontend/src/utils/recommendations.js", "frontend/src/utils/screenPoints.js",
                "frontend/src/components/form/review/Recommendations.jsx"):
        assert "—" not in (root / rel).read_text(encoding="utf-8"), rel
    for label in S.LOSS_PLAN_LABELS.values():
        assert "—" not in label
