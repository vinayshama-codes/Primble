"""score_delta_probe.py - the D6 evidence table.

    py backend/scripts/score_delta_probe.py            # print the table
    py backend/scripts/score_delta_probe.py --json     # machine-readable
    py backend/scripts/score_delta_probe.py --save before.json
    py backend/scripts/score_delta_probe.py --diff before.json

WHY THIS EXISTS. D6 says Brent sees the numbers BEFORE a score-moving change
ships, not after. Every prior score change in this project was argued from code
reading; this scores a fixed panel of representative packages through the REAL
scorers so a change can be stated as a table instead of a claim.

The panel covers each line of business, the shapes the known cap gates fire on,
and the client's own live package (backend/sess.json). Nothing here is a
fixture tuned to a fix - each package is the ORDINARY, healthy shape of its
line, which is exactly where a false cap does its damage.

Offline. No DB, no LLM, no document.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")


def F(v, src="ai_high"):
    return {"value": v, "confidence": "filled", "source": src}


# ── The panel ────────────────────────────────────────────────────────────────
# Each entry: (name, facts, flags, selected_form_ids). Written as the ordinary
# healthy shape of that line - a package a broker would call complete.
_GL_CORE = {
    "applicant_name": F("PANEL TEST LLC"),
    "mailing_address": F("100 Main St, Warren, MI 48089"),
    "fein": F("84-2210987"),
    "effective_date": F("07/15/2026"),
    "expiration_date": F("07/15/2027"),
    "entity_type": F("LLC"),
    "producer_name": F("PANEL BROKERAGE"),
    "operations_description": F("Residential carpentry and remodelling contractor"),
    "total_revenue": F("2500000"),
    "total_payroll": F("800000"),
    "num_employees": F("14"),
    "naics_code": F("238160"),
    "gl_each_occurrence": F("1000000"),
    "gl_aggregate": F("2000000"),
    "gl_limits": F("each occurrence $1,000,000; aggregate $2,000,000"),
    "gl_class_codes_by_location": F("91580 Carpentry - residential"),
    "gl_form_type": F("occurrence"),
    "years_in_business": F("12"),
    "lines_of_business": F(["General Liability"]),
    "contact_name": F("Jordan Reyes"),
    "contact_email": F("jordan@paneltest.example"),
    "contact_phone": F("2485551212"),
    "sic_code": F("1751"),
}

_AUTO = {
    "auto_liability_limit": F("1000000"),
    "auto_liability_structure": F("CSL"),
    "auto_covered_symbols": F([{"coverage": "Liability", "symbols": [1]},
                               {"coverage": "Comprehensive", "symbols": [7]}]),
    "auto_deductible_comp": F("1000"),
    "auto_deductible_collision": F("1000"),
    "auto_vin_schedule": F([{"year": "2019", "make": "Ford", "model": "Transit",
                             "vin": "1FTYE1YM8KKA00001"}]),
    "auto_drivers": F([{"name": "Pat Driver", "licence": "M1234567",
                        "dob": "01/01/1985"}]),
    "auto_garaging_addresses": F([{"address": "100 Main St, Warren, MI 48089"}]),
    "auto_radius_of_operation": F("50 miles"),
    "auto_vehicle_use": F("Service"),
}

_UMB = {
    "umbrella_limit": F("3000000"),
    "umbrella_sir": F("10000"),
    "umbrella_effective_date": F("07/15/2026"),
    "umbrella_expiration_date": F("07/15/2027"),
    "schedule_of_underlying_insurance": F("GL $1M/$2M; Auto $1M CSL; EL $1M/$1M/$1M"),
    "umbrella_follow_form": F("Yes - follows form"),
    "employers_liability_limits": F("1000000/1000000/1000000"),
}

_PROP = {
    "property_building_value": F("1200000"),
    "property_bpp_value": F("250000"),
    "locations": F([{"address": "100 Main St, Warren, MI 48089"}]),
    "occupancy_type": F("Contractor office and shop"),
    "construction_type": F("Joisted Masonry"),
    "year_built": F("1998"),
    "roof_year": F("2015"),
    "sprinkler_system": F("Yes - fully sprinklered"),
    "fire_protection_class": F("Protection Class 4"),
    "valuation_method": F("Replacement Cost"),
    "coinsurance_percentage": F("80"),
    "property_deductible_wind": F("25000"),
}

_WC = {
    "wc_payroll": F("800000"),
    "wc_class_codes": F([{"class_code": "5403", "state": "MI", "payroll": "800000"}]),
    "wc_payroll_period": F("annual"),
    "wc_experience_mod": F("0.95"),
    "employers_liability_limits": F("1000000/1000000/1000000"),
}


# Supporting evidence. The narrative and loss-history pillars read the
# CLASSIFIED DOCUMENT SET, not just the facts, so a panel that passes docs=[]
# measures the harness rather than the pillar. Every synthetic package below
# therefore carries the ordinary supporting set a real submission arrives with.
#
# THE KEY IS `text`, NOT `raw_text` (fixed 2026-09-23). `_extract_narrative_doc_text`
# reads `d.get("text")`. This file supplied only `raw_text`, so the narrative body
# was INVISIBLE to the scorer and every package in the panel scored a flat 59 on
# Narrative Quality - which was then reported as a product ceiling ("no package
# can exceed 89"). It was a harness bug. A pillar that lands on the same number
# across wildly different submissions is a fixture that supplied nothing, not a
# pillar with a hidden cap. Both keys are written now so the fixture matches a
# real session whichever one a consumer reads.
_DOCS = [
    {"doc_id": "d1", "filename": "1_dec_page.pdf", "doc_type": "dec_page",
     "text": "DECLARATIONS - PANEL TEST LLC",
     "raw_text": "DECLARATIONS - PANEL TEST LLC"},
    {"doc_id": "d2", "filename": "2_loss_run.pdf", "doc_type": "loss_run",
     "text": "LOSS RUN - PANEL TEST LLC - no losses in the period"},
    {"doc_id": "d3", "filename": "3_narrative.pdf", "doc_type": "narrative",
     "text": (
         "PANEL TEST LLC is a residential carpentry and remodelling contractor "
         "established in 2014, operating from a single owned shop in Warren, "
         "Michigan with fourteen employees. Management is led by the two "
         "founding members, both with over twenty years in the trade. The "
         "company performs framing, trim and interior remodelling for "
         "homeowners and general contractors; no work is performed above three "
         "stories and no demolition is undertaken. Risk controls include a "
         "written safety programme, documented daily toolbox talks, mandatory "
         "fall-protection training and written subcontractor agreements "
         "requiring certificates of insurance and additional insured status. "
         "The account has no prior losses and has been continuously insured. "
         # The four topics this fixture used to omit, which made its Narrative
         # pillar look like a product ceiling (a flat 59) when it was simply an
         # incomplete narrative. A panel meant to measure the CEILING has to
         # supply a narrative a real broker would write.
         "Coverage requested includes general liability limits of liability and "
         "umbrella; the current coverage and insurance program are described. "
         "The incumbent prior carrier is being remarketed at renewal, and the "
         "reason for marketing is seeking competitive terms. The premises "
         "comprise one location of 12,000 square footage; number of locations, "
         "addresses and geographic spread of risk are detailed. Payroll by class "
         "code and class codes are supplied with a full payroll breakdown.")},
]

_LOSS = {
    "loss_history": F([]),
    "num_claims": F("0"),
    "total_incurred": F("0"),
    "loss_history_years": F("5"),
    "loss_run_period_start": F("07/15/2021"),
    "loss_run_period_end": F("07/15/2026"),
    "loss_run_valuation_date": F("06/30/2026"),
}

_NARR = {
    "operations_description": F(
        "Residential carpentry and remodelling contractor performing framing, "
        "trim and interior remodelling for homeowners and general contractors"),
    "narrative_account_overview": F(
        "PANEL TEST LLC is a residential carpentry and remodelling contractor "
        "established in 2014, operating from a single owned shop in Warren, "
        "Michigan with fourteen employees."),
    "narrative_management": F(
        "Led by the two founding members, both with over twenty years in the "
        "trade; no changes in ownership or management in the last five years."),
    "narrative_risk_controls": F(
        "Written safety programme, documented daily toolbox talks, mandatory "
        "fall-protection training, and written subcontractor agreements "
        "requiring certificates of insurance and additional insured status."),
    "additional_remarks_text": F(
        "No work performed above three stories. No demolition undertaken. "
        "Account continuously insured with no prior losses."),
}


def _pkg(name, extra_facts, extra_flags, forms):
    facts = dict(_GL_CORE)
    facts.update(_LOSS)
    facts.update(_NARR)
    facts.update(extra_facts)
    flags = {"has_general_liability": True, "is_commercial_policy": True,
             "is_contractor": True}
    flags.update(extra_flags)
    return (name, facts, flags, forms, list(_DOCS))


def build_panel():
    panel = [
        _pkg("GL only - complete", {}, {}, ["ACORD_125", "ACORD_126"]),
        _pkg("GL + Auto - complete", _AUTO,
             {"has_auto_coverage": True, "has_commercial_auto": True,
              "has_auto_liability": True, "auto_has_physical_damage": True},
             ["ACORD_125", "ACORD_126", "ACORD_127"]),
        _pkg("GL + Auto + Umbrella - complete", {**_AUTO, **_UMB},
             {"has_auto_coverage": True, "has_commercial_auto": True,
              "has_auto_liability": True, "has_umbrella": True},
             ["ACORD_125", "ACORD_126", "ACORD_127", "ACORD_131"]),
        _pkg("Umbrella, healthy tower (the umb_fail gate shape)", _UMB,
             {"has_umbrella": True}, ["ACORD_125", "ACORD_126", "ACORD_131"]),
        _pkg("Property - wind deductible only (the peril gate shape)", _PROP,
             {"has_property_coverage": True, "property_has_peril_deductibles": True},
             ["ACORD_125", "ACORD_140"]),
        _pkg("Property - complete, no peril deductibles", _PROP,
             {"has_property_coverage": True},
             ["ACORD_125", "ACORD_140"]),
        _pkg("Workers Comp - complete", _WC,
             {"has_workers_comp": True}, ["ACORD_125", "ACORD_130"]),
        _pkg("Everything - the full package", {**_AUTO, **_UMB, **_PROP, **_WC},
             {"has_auto_coverage": True, "has_commercial_auto": True,
              "has_auto_liability": True, "has_umbrella": True,
              "has_property_coverage": True, "has_workers_comp": True},
             ["ACORD_125", "ACORD_126", "ACORD_127", "ACORD_130",
              "ACORD_131", "ACORD_140"]),
    ]
    # ── Scenarios that need a session payload, not just facts ───────────────
    # A cross-document building-value conflict. The package scorer used to
    # hard-stop on it unconditionally; since 2026-09-23 it only does so when the
    # package actually carries property coverage (C75, which extraction_pipeline
    # had already ruled for the same fact). BOTH directions are in the panel so
    # the fix can never be mistaken for "conflicts stopped blocking".
    _uw = {"review_required": True, "fields": [{
        "fact_key": "property_building_value", "review_required": True,
        "label": "Building Value",
        "values": [{"display": "$1,200,000"}, {"display": "$1,750,000"}]}]}
    _bv_warn = ("Building Value: documents disagree ($1,200,000, $1,750,000). "
                "Fix: Confirm the correct value to apply it across forms.")
    for _label, _extra, _fl, _forms in (
        ("Building-value conflict, NO property coverage", {}, {},
         ["ACORD_125", "ACORD_126"]),
        ("Building-value conflict, WITH property coverage (control)", _PROP,
         {"has_property_coverage": True}, ["ACORD_125", "ACORD_140"]),
    ):
        _n, _f, _g, _fm, _d = _pkg(_label, _extra, _fl, _forms)
        panel.append((_n, _f, _g, _fm, _d, _uw, [_bv_warn]))

    # ── No loss runs, No Known Losses attested (Orbin item 15, 29 Sep 2026) ──
    # The ordinary healthy GL package, except the insured attests instead of
    # sending runs: the loss-run document and every loss-run fact are removed
    # and the questionnaire's own option is stored, with the flag its apply
    # path sets. Before 29 Sep the attestation scored Loss History 60; the
    # owner's decision makes it Not Applicable, so this row is where that
    # change shows up.
    _n, _f, _g, _fm, _d = _pkg("GL only - no loss runs, No Known Losses attested",
                               {}, {"no_prior_losses": True},
                               ["ACORD_125", "ACORD_126"])
    for _k in _LOSS:
        _f.pop(_k, None)
    _f["loss_history_no_prior_losses_indicator"] = F(
        "No - no claims or losses in the past 5 years", "client_arq")
    panel.append((_n, _f, _g, _fm, [d for d in _d if d.get("doc_type") != "loss_run"]))

    live = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "sess.json")
    if os.path.exists(live):
        try:
            d = json.load(open(live))
            panel.append(("LIVE - client Orbin package (sess.json)",
                          d["merged_facts"], d["flags"],
                          ["ACORD_125", "ACORD_126", "ACORD_127",
                           "ACORD_131", "ACORD_25"],
                          d.get("documents") or []))
        except Exception as ex:                                  # noqa: BLE001
            print(f"  (sess.json not loadable: {ex})", file=sys.stderr)
    return panel


def score_one(name, facts, flags, forms, docs=None, uw=None, extra_soft=None):
    from services.sqs_service import (
        evaluate_stops, calculate_package_sqs, calculate_sqs_from_facts,
        _resolve_cap,
    )
    from services.cross_form_validator import (
        run_cross_form_validation, split_cross_form_issues,
    )

    fh, fs = evaluate_stops(facts, flags)
    fs = list(fs) + list(extra_soft or [])
    cf = run_cross_form_validation(facts, flags, set(forms))
    ch, cs, _adv = split_cross_form_issues(cf)
    hard = list(fh) + list(ch)
    soft = list(fs) + list(cs)
    cap, reason = _resolve_cap(hard, soft)

    form_scores = {}
    for fid in forms:
        try:
            r = calculate_sqs_from_facts(
                facts=facts, flags=flags, selected_form_ids=forms,
                hard_stops=list(fh), soft_stops=list(fs), tier2_score=50,
                form_id=fid, session_data={"docs": docs or []},
                cross_issues_full=cf,
            )
            form_scores[fid] = {
                "score": r.get("sqs_score"),
                "raw": r.get("raw_sqs_score"),
                "cap_hard_stops": r.get("cap_hard_stops") or [],
            }
        except Exception as ex:                                  # noqa: BLE001
            form_scores[fid] = {"error": str(ex)[:120]}

    try:
        pkg = calculate_package_sqs(
            facts=facts, flags=flags, form_results=[], cross_issues=cf,
            hard_stops=hard, soft_stops=soft,
            session_data={"docs": docs or [], "selected_form_ids": forms,
                          "sqs_history": [],
                          "underwriting_consistency": uw or {}},
        )
    except Exception as ex:                                      # noqa: BLE001
        return {"name": name, "error": str(ex)[:200]}

    # The PACKAGE scorer's own ceiling, not the one derivable from the stop
    # lists alone: `calculate_package_sqs` can hold a score through a stop it
    # manufactures internally (the building-value conflict), so reading `cap`
    # off `_resolve_cap` here would under-report the real ceiling and make a
    # 60-capped package look like an 85 in this table.
    return {
        "name": name,
        "package_score": pkg.get("package_sqs_score"),
        "package_raw": pkg.get("raw_sqs_score"),
        "tier": pkg.get("tier"),
        "cap": pkg.get("cap_applied", cap),
        "cap_reason": pkg.get("cap_reason") or reason,
        "pillars": dict(pkg.get("pillars") or {}),
        "hard_stops": hard,
        "soft_stops": soft,
        "forms": form_scores,
    }


def run():
    return [score_one(*p) for p in build_panel()]


def _print(rows):
    print(f"\n{'PACKAGE':48} {'SCORE':>6} {'RAW':>5} {'CAP':>5}  HELD BY")
    print("-" * 118)
    for r in rows:
        if r.get("error"):
            print(f"{r['name'][:48]:48} {'ERR':>6}  {r['error'][:50]}")
            continue
        cap = r["cap"] if r["cap"] is not None else "-"
        held = (r["cap_reason"] or "")[:52]
        print(f"{r['name'][:48]:48} {str(r['package_score']):>6} "
              f"{str(r['package_raw']):>5} {str(cap):>5}  {held}")
    print("-" * 118)
    for r in rows:
        if r.get("error"):
            continue
        if r["hard_stops"] or r["soft_stops"]:
            print(f"\n{r['name']}")
            for m in r["hard_stops"]:
                print(f"   HARD  {m[:104]}")
            for m in r["soft_stops"]:
                print(f"   warn  {m[:104]}")
            caps = [f"{k}={v.get('cap_hard_stops')}" for k, v in r["forms"].items()
                    if v.get("cap_hard_stops")]
            if caps:
                print(f"   form gate caps: {caps}")


def _diff(before, after):
    b = {r["name"]: r for r in before}
    print(f"\n{'PACKAGE':48} {'BEFORE':>7} {'AFTER':>7}  {'DELTA':>6}  CHANGE")
    print("-" * 118)
    moved = 0
    for r in after:
        o = b.get(r["name"])
        if not o:
            print(f"{r['name'][:48]:48} {'-':>7} {str(r.get('package_score')):>7}   NEW")
            continue
        bs, as_ = o.get("package_score"), r.get("package_score")
        if bs is None or as_ is None:
            continue
        d = as_ - bs
        if d:
            moved += 1
        note = ""
        if (o.get("cap") or 0) != (r.get("cap") or 0):
            note = f"cap {o.get('cap')} -> {r.get('cap')}"
        nb, na = len(o["hard_stops"]) + len(o["soft_stops"]), \
            len(r["hard_stops"]) + len(r["soft_stops"])
        if nb != na:
            note += f"  stops {nb} -> {na}"
        flag = "  <<<" if d else ""
        print(f"{r['name'][:48]:48} {bs:>7} {as_:>7}  {d:>+6}  {note}{flag}")
    print("-" * 118)
    print(f"{moved} of {len(after)} packages moved.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save")
    ap.add_argument("--diff")
    a = ap.parse_args()
    rows = run()
    if a.save:
        json.dump(rows, open(a.save, "w"), indent=1, default=str)
        print(f"saved {len(rows)} rows -> {a.save}")
        return
    if a.diff:
        _diff(json.load(open(a.diff)), rows)
        return
    if a.json:
        print(json.dumps(rows, indent=1, default=str))
        return
    _print(rows)


if __name__ == "__main__":
    main()
