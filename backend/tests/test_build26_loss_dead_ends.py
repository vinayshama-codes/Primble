"""No Loss History deduction is a dead end (23 Oct 2026, package fc04c74f).

Brent's claims spreadsheet (12 claims, all 2025, no FEIN or policy number) was read as
loss runs. Score 90, every pillar 100 except Loss History at 35, and the only row on
the screen was `('loss_history_alignment', 'fein', 0 pts)`: the "ownership could not be
fully verified" message routed to the PACKAGE FEIN (already filled), the run's own FEIN
cannot be typed, the years were never asked on the possible path, and a stale "loss
runs requested / pending" answer sat in the facts. Nothing the producer could do raised
the score.

The class: every Loss History point the pillar is short is now an item that names what
lifts it - an answer (ownership, years, carrier) or a document - and the screen's
numbers add up to exactly 100 minus the score.
"""
import itertools

import pytest

from services import sqs_service as S
from services.answer_options import options_for
from services.answer_routing import answer_mode
from services.loss_history_state import (
    LOSS_RUN_OWNERSHIP_FIELD, LOSS_RUN_OWNERSHIP_OPTIONS, loss_run_years_suggestion,
    resolve_loss_history_state, stored_pending_counts,
)
from services.loss_run_identity import match_loss_run_identity

YES = LOSS_RUN_OWNERSHIP_OPTIONS[0]
NO = LOSS_RUN_OWNERSHIP_OPTIONS[1]
PENDING = "Loss runs have been requested and are pending"


def _env(v):
    return {"value": v, "source": "producer", "confidence": "producer"}


def _doc_env(v):
    return {"value": v, "source": "document", "confidence": "high"}


def _claims(year=2025, n=12):
    return [{"date": f"{year}-{(i % 12) + 1:02d}-10", "description": f"Water damage {i}",
             "paid": "1000", "claim_number": f"C{i}"} for i in range(n)]


def _run_doc(name="Acme Roofing LLC", fein=None, policy=None):
    f = {}
    if name:
        f["applicant_name"] = _doc_env(name)
    if fein:
        f["fein"] = _doc_env(fein)
    if policy:
        f["policy_number"] = _doc_env(policy)
    return {"doc_type": "loss_run", "filename": "claims.xlsx", "facts": f}


def _fc04_package(**extra):
    """fc04c74f's shape: a clean package, a name-only claims sheet, 12 claims in 2025,
    no readable years, and the producer's stale "requested / pending" answer."""
    facts = {k: _env("x") for k in list(S.TIER1_FIELDS) + list(S.TIER2_FIELDS)}
    facts.update({"applicant_name": _env("Acme Roofing LLC"), "effective_date": _env("01/01/2027"),
                  "expiration_date": _env("01/01/2028"), "contact_name": _env("Dana"),
                  "num_employees": _env("0"), "naics_code": _env("238160"),
                  "total_revenue": _env("$5,000,000"), "years_in_business": _env("15"),
                  "fein": _env("12-3456789"), "operations_description": _env("Roofing contractor"),
                  "prior_carrier": _env("Old Carrier Co"),
                  "loss_run_status": _env(PENDING),
                  "loss_history": _doc_env(_claims()), "num_claims": _doc_env("12")})
    facts.update(extra)
    flags = {"has_general_liability": True}
    return facts, flags, [_run_doc()]


def _score(facts, flags, docs):
    kw = dict(flags=flags, form_results=[], cross_issues=[], hard_stops=[], soft_stops=[],
              session_data={"docs": docs}, form_fill=False)
    pkg = S.calculate_package_sqs(facts=facts, **kw)
    pkg, _kd = S.complete_screen_shares({"facts": facts, "flags": flags, "docs": docs}, "s", "u", pkg, None)
    return pkg


def _loss(pkg):
    p = pkg["pillars"]["loss_history_alignment"]
    return p.get("score") if isinstance(p, dict) else p


def _shown_total(pkg):
    """Every number the page prints, once: since 24 Oct 2026 the page's one plan
    (`review_plan` - key details, cards, rows, document rows, each worth what it
    adds after the items above it) plus what no item can add."""
    plan = pkg.get("review_plan")
    if plan:
        return sum(i["points"] for i in plan["items"]) + int(plan.get("left") or 0)
    return (sum(v[0] for v in (pkg.get("screen_shares") or {}).values())
            + sum(v[0] for v in (pkg.get("screen_card_points") or {}).values())
            + sum(v[0] for v in (pkg.get("screen_dc_points") or {}).values())
            + sum(u["points"] for u in (pkg.get("screen_unanswerable") or [])))


def _asked_facts(pkg):
    return {str(r["field"]) for r in pkg.get("top_recommendations") or [] if r.get("field")}


# ── 1. Ownership: a producer's answer through the one match door ─────────────
def test_the_ownership_fact_is_registered_answerable_and_a_choice():
    assert answer_mode(LOSS_RUN_OWNERSHIP_FIELD)["mode"] == "field"
    assert options_for(LOSS_RUN_OWNERSHIP_FIELD) == list(LOSS_RUN_OWNERSHIP_OPTIONS)


@pytest.mark.parametrize("run, expected_yes", [
    (_run_doc(), "strong"),                                       # name only -> possible
    (_run_doc(name=None), "possible"),                            # no name on the run: never promoted
    (_run_doc(name="Other Company Inc"), "no_match"),             # another company: never promoted
    (_run_doc(name="Prior Name Inc", fein="12-3456789"), "strong"),  # tax ID matches, name differs
])
def test_a_yes_makes_a_name_matched_run_strong_and_a_no_changes_nothing(run, expected_yes):
    facts, _flags, _docs = _fc04_package()
    dec = {"doc_type": "declarations", "filename": "dec.pdf",
           "facts": {"applicant_name": _doc_env("Acme Roofing LLC"), "fein": _doc_env("12-3456789")}}
    docs = [run, dec]
    before = match_loss_run_identity(docs, "Acme Roofing LLC", facts)["tier"]
    yes = match_loss_run_identity(docs, "Acme Roofing LLC", dict(facts, **{LOSS_RUN_OWNERSHIP_FIELD: _env(YES)}))
    no = match_loss_run_identity(docs, "Acme Roofing LLC", dict(facts, **{LOSS_RUN_OWNERSHIP_FIELD: _env(NO)}))
    assert yes["tier"] == expected_yes
    assert no["tier"] == before
    if expected_yes == "strong":
        assert "person_confirmed" in yes["matched_on"]


def test_the_ownership_messages_route_to_the_ownership_fact_and_a_mismatch_stays_put():
    assert S.loss_recommendation_field(
        "Loss run ownership could not be fully verified - name matches but FEIN/policy number not confirmed"
    ) == LOSS_RUN_OWNERSHIP_FIELD
    assert S.loss_recommendation_field(
        "Loss run ownership partially verified - confirm the run belongs to this insured") == LOSS_RUN_OWNERSHIP_FIELD
    assert S.loss_recommendation_field(
        "Loss run insured name does not match - verify these runs belong to this submission") == "applicant_name"


# ── 2. Claim years are asked on every match path ──────────────────────────────
@pytest.mark.parametrize("tier", ["strong", "moderate", "possible", "no_match"])
def test_unreadable_years_are_asked_on_every_match_path(tier):
    facts, flags, _docs = _fc04_package()
    _s, recs = S.calculate_p4_loss_history(facts, flags, has_loss_run_doc=True, loss_run_match=tier)
    assert "loss_history_years" in {S.loss_recommendation_field(m) for m in recs}


def test_the_years_suggestion_comes_from_the_runs_own_rows_and_is_never_stored():
    facts, _flags, _docs = _fc04_package()
    assert loss_run_years_suggestion(facts) == [2025]
    assert loss_run_years_suggestion({"loss_history": _claims(2023, 2) + _claims(2025, 3)}) == [2023, 2025]
    assert loss_run_years_suggestion({}) is None
    pkg = _score(*_fc04_package())
    assert "loss_history_years" not in facts                      # suggested, not written
    # The plan weighs the TRUE value (the runs' own years, 23 Oct 2026): "1 year" on
    # runs pinned at 60 adds nothing (option B), so it is weighed and not listed.
    years = next(s for s in pkg["loss_plan"] if s["key"] == "years")
    assert years["probe"] == "1" and "2025" in years["label"] and "1 year" in years["label"]
    assert years["points"] == 0 and not years["applied"]
    assert not any(r.get("field") == "loss_history_years" for r in pkg["top_recommendations"])


# ── 3. A stale "pending" answer never counts once runs are on file ────────────
def test_a_persons_pending_answer_is_ignored_once_runs_are_on_file():
    facts = {"loss_run_status": _env(PENDING)}
    assert stored_pending_counts(facts, {}, has_loss_run_doc=False) is True
    assert stored_pending_counts(facts, {}, has_loss_run_doc=True) is False
    # The document's OWN statement (a cover letter typed as a loss run) still counts...
    letter = {"loss_run_status": _doc_env("pending")}
    assert stored_pending_counts(letter, {}, has_loss_run_doc=True) is True
    # ...but not beside claim rows.
    assert stored_pending_counts(dict(letter, loss_history=_claims(n=2)), {}, True) is False
    facts = dict(facts, prior_carrier=_env("Old Carrier Co"))
    score, recs = S.calculate_p4_loss_history(facts, {}, has_loss_run_doc=True, loss_run_match="possible")
    assert score == 35 and not any("requested / pending" in m.lower() for m in recs)
    assert resolve_loss_history_state(facts, {}, True) != "loss_runs_pending"
    assert S._get_loss_history_state(facts, {}, True, "possible") != "loss_runs_pending"


def test_the_pending_row_is_never_offered_while_runs_are_on_file():
    pkg = _score(*_fc04_package())
    texts = " ".join(str(r.get("action")) for r in pkg["top_recommendations"]).lower()
    assert "requested / pending" not in texts
    assert "loss_run_status" not in _asked_facts(pkg)


# ── 4 + proof: the fc04c74f shape ────────────────────────────────────────────
def _upload_rows(pkg):
    return [u for u in pkg.get("screen_unanswerable") or []
            if u.get("action") == "add_documents" and u.get("step") == "upload"]


def test_fc04c74f_the_shortfall_is_answerable_or_named_and_adds_up():
    facts, flags, docs = _fc04_package()
    pkg = _score(facts, flags, docs)
    assert _loss(pkg) == 35
    loss_rows = [r for r in pkg["top_recommendations"] if r.get("pillar") == "loss_history_alignment"]
    assert "fein" not in {r.get("field") for r in loss_rows}       # the dead row is gone
    shares = pkg["screen_shares"]
    assert shares[LOSS_RUN_OWNERSHIP_FIELD][0] > 0                 # ownership is worth points
    # ONE upload row for everything only new documents supply (23 Oct 2026) - no
    # "earlier years" / "valuation date" pair.
    ups = _upload_rows(pkg)
    assert len(ups) == 1 and ups[0]["label"] == S.LOSS_PLAN_LABELS["upload"] and ups[0]["points"] > 0
    assert _shown_total(pkg) == 100 - pkg["package_sqs_score"]

    answered = dict(facts, **{LOSS_RUN_OWNERSHIP_FIELD: _env(YES), "loss_history_years": _env("1")})
    after = _score(answered, flags, docs)
    assert _loss(after) > _loss(pkg)
    assert after["package_sqs_score"] > pkg["package_sqs_score"]
    # 1 of 5 years on a 15-year business: the rest is the one upload row, with its points.
    ups = _upload_rows(after)
    assert len(ups) == 1 and ups[0]["points"] > 0
    assert _shown_total(after) == 100 - after["package_sqs_score"]
    assert {LOSS_RUN_OWNERSHIP_FIELD, "loss_history_years"}.isdisjoint(
        {f for f, v in after["screen_shares"].items() if v[0] > 0})


def test_loss_items_add_up_to_the_pillar_shortfall_on_every_path():
    """The plan's steps (23 Oct 2026, `loss_history_plan`) add up to what the
    package gains when Loss History reaches its maximum, on every match path;
    every step names its lift and none is negative."""
    facts, flags, _docs = _fc04_package()
    runs = [_run_doc(), _run_doc(name=None), _run_doc(name="Other Company Inc"),
            _run_doc(fein="12-3456789")]
    variants = [{}, {"loss_history_years": _env("2")}, {"prior_carrier": None},
                {LOSS_RUN_OWNERSHIP_FIELD: _env(NO)}, {"loss_run_valuation_date": _env("2025-01-01")},
                {"years_in_business": _env("3")}]
    for run, var in itertools.product(runs, variants):
        f = dict(facts, **var)
        pkg = S.calculate_package_sqs(facts=f, flags=flags, form_results=[], cross_issues=[],
                                      hard_stops=[], soft_stops=[], session_data={"docs": [run]},
                                      form_fill=False, _probe=True)
        pillars = dict(pkg["pillars"])
        plan = S.loss_history_plan(f, flags, [run], pillars)
        p4 = pillars["loss_history_alignment"]
        if p4 is None or p4 >= 100:
            assert plan is None
            continue
        full = S._weighted_pillar_sum({**pillars, "loss_history_alignment": 100}, S.SPEC_PILLAR_WEIGHTS)
        assert sum(s["points"] for s in plan) == min(100, full) - pkg["raw_sqs_score"], (run, var)
        assert all(s["points"] >= 0 for s in plan)
        for s in plan:                                             # every step names its lift
            assert s.get("fact") or s.get("label")


# ── 5. The standing guard ─────────────────────────────────────────────────────
def _guard_packages():
    from tests.test_reach_100_before_forms_15oct import _umbrella_package
    out = []
    f, kw = _umbrella_package()
    out.append((f, kw["flags"], kw["session_data"]["docs"]))
    out.append(_fc04_package())
    out.append(_fc04_package(**{LOSS_RUN_OWNERSHIP_FIELD: _env(YES), "loss_history_years": _env("1")}))
    f, fl, _d = _fc04_package()
    out.append((f, fl, [_run_doc(name=None)]))
    out.append((f, fl, [_run_doc(fein="12-3456789")]))
    out.append((dict(f, loss_history_years=_env("5"), loss_run_valuation_date=_env("2020-01-01")),
                fl, [_run_doc()]))
    out.append((dict(f, loss_history=None, num_claims=None), fl, []))   # no runs, a pending answer
    # 715b3c8f (23 Oct): ownership Yes -> strong, years unreadable, pinned at 60 -
    # with and without years on the claim rows, and with years answered "1".
    yes = {LOSS_RUN_OWNERSHIP_FIELD: _env(YES)}
    out.append(_fc04_package(**yes))
    out.append(_fc04_package(**yes, loss_history=None, num_claims=None))
    out.append(_fc04_package(**yes, loss_history=[{"date": "3/15/25", "description": "Hail", "paid": "900",
                                                   "claim_number": "A1"}]))
    out.append(_fc04_package(**yes, loss_history_years=_env("1")))
    # 5472449a (23 Oct): claims answered "yes", the claims sheet uploaded but not
    # typed a loss run (its classifier scored loss_run best), and the same with
    # no such document (the request row and the upload row split one cause).
    out.append(_5472_package(unmarked=True))
    out.append(_5472_package(unmarked=False))
    return out


def _5472_package(unmarked=True):
    f, fl, _d = _fc04_package(loss_history_no_prior_losses_indicator=_env("Yes - we have had claims or losses"),
                              num_claims=_env("12"), total_incurred=_env("322650"),
                              loss_history=None, loss_run_status=None)
    sheet = {"doc_type": "unknown", "filename": "Brent claims.xlsx",
             "classification": {"confidence": "low",
                                "scores": {"loss_run": 0.61, "narrative": 0.2} if unmarked else {"narrative": 0.4}}}
    return f, fl, [sheet]


def _page_total(pkg):
    """What the page prints: every share, plus any row carrying points of its own
    that no share covers (two rows claiming one cause count twice)."""
    shares = pkg.get("screen_shares") or {}
    extra = sum(int(r.get("answer_gain") or 0) for r in pkg.get("top_recommendations") or []
                if r.get("field") and str(r["field"]) not in shares and r.get("pillar") != "hard_stops_present")
    return _shown_total(pkg) + extra


def _expected_document_rows(facts, docs):
    """The Loss History gaps only a document lifts, read off the facts: since 23
    Oct 2026 ONE row asks for them all (complete, current runs naming the
    insured's FEIN) - never an "earlier years" row beside a "valuation date" row."""
    from services.loss_history_state import loss_years_required
    if not any(d.get("doc_type") == "loss_run" for d in docs):
        return []
    if (S._resolve_loss_history_years(facts) < (loss_years_required(facts) or 5)
            or S._loss_run_age_days(facts) is None):
        return [S.LOSS_PLAN_LABELS["upload"]]
    return []


@pytest.mark.parametrize("n", range(13))
def test_shown_points_add_up_to_100_minus_score_and_each_share_has_its_row(n):
    facts, flags, docs = _guard_packages()[n]
    pkg = _score(facts, flags, docs)
    if pkg.get("cap_applied") is not None or pkg["package_sqs_score"] >= 100:
        pytest.skip("capped or full")
    assert _shown_total(pkg) == 100 - pkg["package_sqs_score"]
    assert _page_total(pkg) == 100 - pkg["package_sqs_score"]      # no two rows claim one point
    asked = _asked_facts(pkg) | set(S.screen_fields(facts, flags, [], [], []))
    for fact, (pts, *_rest) in (pkg.get("screen_shares") or {}).items():
        if pts > 0:
            assert fact in asked, fact                             # never points on a box nobody asks
    for u in pkg.get("screen_unanswerable") or []:
        assert u.get("label") and u["points"] > 0                 # never an unexplained gap
    # Every Loss History gap only a document lifts is its own row, on every match path.
    if _loss(pkg) is not None and _loss(pkg) < 100:
        doc_rows = [u["label"] for u in pkg.get("screen_unanswerable") or []
                    if u.get("action") == "add_documents"]
        for want in _expected_document_rows(facts, docs):
            assert any(want in lbl for lbl in doc_rows), (want, doc_rows)


# ── 6. Option B: a years answer never lowers Loss History (owner, 23 Oct) ─────
def test_a_years_answer_never_lowers_loss_history_and_the_valuation_date_is_its_own_row():
    facts, flags, docs = _fc04_package()
    yes = dict(facts, **{LOSS_RUN_OWNERSHIP_FIELD: _env(YES)})
    only_yes = _score(yes, flags, docs)
    after = _score(dict(yes, loss_history_years=_env("1")), flags, docs)
    assert _loss(only_yes) == 60
    assert _loss(after) >= 60                                       # never 55
    # The missing valuation date is part of the ONE upload row (23 Oct 2026), "valued
    # within 90 days", with its points.
    ups = _upload_rows(after)
    assert len(ups) == 1 and "valued within 90 days" in ups[0]["label"] and ups[0]["points"] > 0
    assert _shown_total(after) == 100 - after["package_sqs_score"]
    # The rule is about a PERSON's answer: a document-read year count scores as before.
    doc_years = dict(yes, loss_history_years=_doc_env("1"))
    tier = match_loss_run_identity(docs, "Acme Roofing LLC", doc_years)["tier"]
    assert S.calculate_p4_loss_history(doc_years, flags, has_loss_run_doc=True, loss_run_match=tier)[0] == 55


def test_with_option_b_the_years_answer_is_listed_only_when_its_true_value_raises_it():
    """Option B (23 Oct 2026): the years answer never lowers Loss History, and the
    plan weighs it with the runs' OWN years. On runs pinned at 60 with claims in one
    year, "1" adds nothing - not listed; with claims in five years, "5" lifts it."""
    pkg = _score(*_fc04_package(**{LOSS_RUN_OWNERSHIP_FIELD: _env(YES)}))
    assert not any(r.get("field") == "loss_history_years" for r in pkg["top_recommendations"])
    five = [c for y in (2021, 2022, 2023, 2024, 2025) for c in _claims(y, 1)]
    for n, c in enumerate(five):
        c["claim_number"] = f"C5-{n}"
    pkg = _score(*_fc04_package(**{LOSS_RUN_OWNERSHIP_FIELD: _env(YES), "loss_history": _doc_env(five)}))
    years = [r for r in pkg["top_recommendations"] if r.get("field") == "loss_history_years"]
    assert years and years[0]["answer_gain"] > 0 and "(5 years)" in years[0]["action"]


# ── 7. 5472449a: the runs are uploaded, only not typed as loss runs ──────────
def test_an_unmarked_claims_sheet_is_one_mark_as_loss_runs_row():
    pkg = _score(*_5472_package(unmarked=True))
    texts = " ".join(str(r.get("action")) for r in pkg["top_recommendations"]).lower()
    assert "request loss runs" not in texts and "loss_run_status" not in _asked_facts(pkg)
    rows = [u for u in pkg["screen_unanswerable"] if u.get("action") == "add_documents"]
    # The mark first, then the ONE upload row for what the sheet will not supply (the
    # coordinator's rule, 24 Oct 2026: every later step is listed before the mark, so
    # marking never makes a row appear). Never a "request" row while it can be marked.
    assert [u["label"] for u in rows] == ["Mark 'Brent claims.xlsx' as Loss runs", S.LOSS_PLAN_LABELS["upload"]]
    assert [u["step"] for u in rows] == ["mark", "upload"]
    assert _page_total(pkg) == 100 - pkg["package_sqs_score"]


def test_with_no_runs_the_request_and_the_upload_split_one_shortfall():
    pkg = _score(*_5472_package(unmarked=False))
    req = pkg["screen_shares"]["loss_run_status"][0]
    up = sum(u["points"] for u in pkg["screen_unanswerable"] if u["label"] == S.LOSS_PLAN_LABELS["upload"])
    assert req > 0 and up > 0
    assert _page_total(pkg) == 100 - pkg["package_sqs_score"]
