"""SHAPE FUZZ (owner, 30 Oct 2026) - whole classes of wrong behaviour found
without a live upload. The harness (`shape_fuzz_harness.py`) builds random
packages (vehicles incl. pre-1981 and misread VINs, drivers, premises with
several buildings and three spellings, P.O. box mailing, 1-7 current lines,
dated / undated / gapped prior history, two umbrella layers, 0-3 loss runs
with old and fresh valuation dates and repeated claims, renewal or new
business, 6- or 12-month terms, another insured's document, a person's typed
values) and runs the real `_finalize_pipeline` + score + plan + prior grid
with no model and no network, checking invariants.

Default seeds: SHAPE_FUZZ_N (default 12 in the build - ~3 s a package;
SHAPE_FUZZ_N=200 / 2000 for the sweep).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shape_fuzz_harness as H  # noqa: E402
import services.extraction_service as es  # noqa: E402

_N = int(os.environ.get("SHAPE_FUZZ_N", "12"))


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("the shape fuzz makes no model or network call")
    import httpx
    monkeypatch.setattr(httpx.Client, "send", refuse)
    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)
    for k in ("NARRATIVE_READER", "EVIDENCE_JUDGE", "CARRIER_NARRATIVE", "TRANSCRIBER"):
        monkeypatch.setenv(k, "0")


@pytest.mark.parametrize("seed", range(_N))
def test_shape_package_keeps_every_invariant(seed, monkeypatch):
    case = H.shape_case(seed)
    out = H.run_case(case, monkeypatch.setattr)
    assert H.problems(case, out) == []


def test_the_generator_is_deterministic():
    assert H.shape_case(7) == H.shape_case(7)


# ── Fix 1: a VIN read one character short or long is the same vehicle ───────
V = "1FTBF2B61GEB10001"


def _merge_two(vin_a, vin_b, year_b="2016", make_b="FORD"):
    a = {"filename": "a.pdf", "doc_type": "dec_page", "text": f"VIN {vin_a}", "flags": {},
         "facts": {"applicant_name": "X LLC", "auto_vin_schedule": [
             {"year": "2016", "make": "FORD", "model": "F-250", "vin": vin_a}]}}
    b = {"filename": "b.pdf", "doc_type": "schedule", "text": vin_b, "flags": {},
         "facts": {"applicant_name": "X LLC", "auto_vin_schedule": [
             {"year": year_b, "make": make_b, "model": "F-250", "vin": vin_b, "body_type": "PU"}]}}
    mf, _ = es.merge_facts([a, b], a)
    r = mf.get("auto_vin_schedule")
    return r.get("value") if isinstance(r, dict) else r


@pytest.mark.parametrize("misread", [V[:-1], V + "7", V[:5] + V[6:], "Z" + V])
def test_a_one_character_misread_vin_folds_into_its_vehicle(misread):
    rows = _merge_two(V, misread)
    assert [r["vin"] for r in rows] == [V]
    assert rows[0].get("body_type") == "PU"          # what the misread row adds is kept


def test_two_real_vehicles_are_never_folded():
    other = "1FTBF2B61GEB10002"                      # 17 chars: a real second VIN
    assert len(_merge_two(V, other)) == 2


def test_a_misread_vin_that_disagrees_on_year_is_not_folded():
    assert len(_merge_two(V, V[:-1], year_b="2019")) == 2


def test_a_short_serial_two_characters_off_is_not_folded():
    assert len(_merge_two(V, V[:-2])) == 2


# ── Fix 2: a policy of a year the prior grid prints is never lost ───────────
def test_a_grid_year_policy_no_box_holds_is_listed_on_acord_101():
    """The grid printed 2026 / 2024 / 2023 (the 2025 policy has no premium and
    takes no row); a 2023 inland marine policy no box held was outside the
    101's window of 2026 / 2025 / 2024 - on neither (seed 12)."""
    from services import pdf_service as P

    def e(line, no, y, prem):
        return {"line": line, "carrier": "Blue Mesa Indemnity Company", "policy_no": no,
                "effective": f"05/15/{y}", "expiration": f"05/15/{y + 1}", "premium": prem}
    facts = {"prior_coverage_by_line": [
        e("Commercial General Liability", "GL-1-26", 2026, "$1,000"),
        e("Inland Marine", "IM-2-25", 2025, None),
        e("Commercial General Liability", "GL-3-24", 2024, "$1,000"),
        e("Commercial General Liability", "GL-4-23", 2023, "$1,000"),
        e("Commercial Umbrella", "UMB-5-23", 2023, "$3,000"),
        e("Inland Marine", "IM-6-23", 2023, "$2,000")]}
    grid, years = P._prior_coverage_grid_build(facts)
    placed = [v.get("policy_no") for v in grid.values()]
    aside = [r.get("policy_no") for r in P.prior_grid_set_aside_rows(facts)]
    for no in ("GL-1-26", "GL-3-24", "GL-4-23", "UMB-5-23", "IM-6-23"):
        assert (placed + aside).count(no) == 1, (no, years, placed, aside)


# ── AFTER FORMS (30 Oct 2026): the recommended forms stamped with no model ──
_NA = int(os.environ.get("SHAPE_FUZZ_N", "15"))


@pytest.mark.parametrize("seed", range(_NA))
def test_shape_package_after_forms_keeps_every_invariant(seed, monkeypatch):
    case = H.shape_case(seed)
    out = H.run_case(case, monkeypatch.setattr)
    after = H.run_after_forms(case, out)
    assert H.problems_after_forms(case, out, after) == []
    assert _package_vs_form_problems(out, after) == []
    # Filling exactly the boxes that hold a form reaches its raw score.
    for fid in after.get("form_ids") or []:
        got = H.fill_holding_boxes(after, fid)
        if got is not None:
            new, raw, cap = got
            assert cap is None and new == raw, (fid, new, raw, cap)
        # ...and isolated from the package's own stops.
        assert H.box_holds_reach_raw(after, fid) is None


# ── Fix 3: another form's stop never holds a form (shape fuzz after forms) ──
from services.sqs_service import stops_for_form  # noqa: E402

_T1 = ("ACORD 125 minimum field missing: Producer / Agency name "
       "(Fix: Provide this value manually, or upload a document that states it.)")


def test_a_stop_naming_another_form_does_not_hold_this_one():
    stops = [_T1, "GL coverage detected but no class codes found", "ACORD 126 something"]
    assert stops_for_form(stops, "ACORD_126") == stops[1:]
    assert stops_for_form(stops, "ACORD_125") == stops[:2]
    # a copy reads its base form; a GL line's stop never holds the umbrella (30 Oct line rule)
    assert stops_for_form(stops, "ACORD_131__excess") == []
    umb = "Umbrella present with no underlying GL or Auto limits"
    assert stops_for_form([umb], "ACORD_131__excess") == [umb]
    assert stops_for_form([umb], "ACORD_126") == []
    assert stops_for_form(stops, None) == stops                          # no form: unchanged
    assert stops_for_form(None, "ACORD_126") == []


def test_a_125_tier1_warning_no_longer_caps_the_126():
    from services import sqs_service as S
    kw = dict(facts={}, flags={}, mapped_data={"X_A": "1"}, form_schema={"X_A": {}},
              selected_form_ids=["ACORD_125", "ACORD_126"], hard_stops=[], soft_stops=[_T1],
              tier2_score=50, confidence_dict={"X_A": "high"}, _simulate=True)
    assert S.calculate_sqs(form_id="ACORD_126", **kw).get("cap_applied") is None
    assert S.calculate_sqs(form_id="ACORD_125", **kw).get("cap_applied") == 85


def test_a_lines_stop_holds_only_that_lines_forms():
    from services.sqs_service import stops_for_form
    gl = "GL coverage detected but no class codes found"
    assert gl in stops_for_form([gl], "ACORD_126")
    assert gl in stops_for_form([gl], "ACORD_125")          # the application speaks for every line
    assert gl not in stops_for_form([gl], "ACORD_127")
    assert gl not in stops_for_form([gl], "ACORD_140")
    other = "Some package-wide sentence no rule group knows"
    assert other in stops_for_form([other], "ACORD_127")    # unknown group: holds every form


# ── PACKAGE checks vs FORM checks (owner, 30 Oct 2026) ──────────────────────
def _package_vs_form_problems(out, after):
    """The package score after forms equals the pre-form score; no form-scope
    card on the pre-form view; a form-scope check holds only the forms it names."""
    from services import sqs_service as S
    from services.issue_registry import FORM_SCOPE_CODES
    probs = []
    view = S.review_page_grouped_view(out["row"], out["pkg"])
    for tier in [view.get("hard_stops") or []] + list((view.get("warnings") or {}).values()):
        for c in tier or []:
            for it in c.get("items") or []:
                if it.get("code") in FORM_SCOPE_CODES:
                    probs.append(f"form-scope card before forms: {it.get('code')}")
    if after.get("skipped"):
        return probs
    before = (out.get("pkg") or {}).get("package_sqs_score")
    now = (after.get("pkg") or {}).get("package_sqs_score")
    if before is not None and now is not None and now != before:
        probs.append(f"package {before} before forms, {now} after")
    cross = (after.get("row") or {}).get("cross_form_issues") or []
    for fid, sqs in (after.get("per") or {}).items():
        reason = (sqs or {}).get("cap_reason")
        for i in cross:
            if (isinstance(i, dict) and i.get("code") in FORM_SCOPE_CODES
                    and i.get("message") == reason and fid not in (i.get("forms") or [])):
                probs.append(f"{fid} held by {i.get('code')} naming {i.get('forms')}")
    return probs
