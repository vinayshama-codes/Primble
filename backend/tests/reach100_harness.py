"""Reach-100 harness (27 Oct 2026, owner's rule: a producer who answers everything the
pre-form screen asks reaches exactly 100 - on ANY package, not only the ones we have
seen).

Two halves, both offline (no upload, no OCR, no model call - pinned by
`test_reach_100_every_package`):

* `synthetic_package(rnd)` - a random package built from scratch: one of six business
  archetypes, random coverage lines, documents (one declarations page per line, loss
  runs or not) and random trouble - facts dropped, low underlying limits, an unusual
  coinsurance, a backwards or ended term, payroll beside revenue, two documents
  disagreeing on the FEIN, claims or a clean history. No customer data.
* `solve(row)` - answers it the way a producer would, through the review page's own
  items and write doors (`review_plan.page_items` / `_Sim` / `_apply`), round after
  round, and returns the score the page would then show. A card with no answer is
  a dead end (Dismiss moves no score).
"""
from __future__ import annotations

import copy
import random
from typing import Any, Dict, List, Optional, Tuple


def _env(value: Any, source: str = "ai") -> dict:
    return {"value": value, "source": source, "confidence": "ai_high"}


_ARCHETYPES = {
    "contractor": {
        "ops": "Electrical contractor installing wiring and lighting in commercial buildings.",
        "naics": "238210", "lines": ["gl", "auto", "wc", "umbrella"], "gl_code": "92478",
        "wc_code": "5190"},
    "restaurant": {
        "ops": "Full service restaurant serving lunch and dinner with a small bar.",
        "naics": "722511", "lines": ["gl", "property", "wc"], "gl_code": "16910",
        "wc_code": "9079"},
    "office": {
        "ops": "Accounting and bookkeeping firm working from a leased office suite.",
        "naics": "541211", "lines": ["gl", "property", "cyber", "crime"], "gl_code": "41677",
        "wc_code": "8810"},
    "trucking": {
        "ops": "Regional freight hauling with a fleet of box trucks.",
        "naics": "484110", "lines": ["auto", "umbrella", "wc", "gl"], "gl_code": "99793",
        "wc_code": "7228"},
    "retail": {
        "ops": "Hardware store selling tools and building supplies to the public.",
        "naics": "444130", "lines": ["gl", "property", "crime", "inland_marine"],
        "gl_code": "13930", "wc_code": "8010"},
    "manufacturer": {
        "ops": "Machine shop fabricating metal parts for industrial customers.",
        "naics": "332710", "lines": ["gl", "property", "wc", "auto", "umbrella"],
        "gl_code": "57200", "wc_code": "3632"},
}
_FLAG = {"gl": "has_general_liability", "auto": "has_auto_coverage", "wc": "has_workers_comp",
         "property": "has_property_coverage", "umbrella": "has_umbrella", "crime": "has_crime",
         "cyber": "has_cyber", "inland_marine": "has_inland_marine"}
_FORMS = {"gl": "ACORD_126", "auto": "ACORD_127", "wc": "ACORD_130", "property": "ACORD_140",
          "umbrella": "ACORD_131", "crime": "ACORD_141"}
_LINE_NAME = {"gl": "General Liability", "auto": "Commercial Auto", "wc": "Workers Compensation",
              "property": "Commercial Property", "umbrella": "Commercial Umbrella",
              "crime": "Crime", "cyber": "Cyber Liability", "inland_marine": "Inland Marine"}


def synthetic_package(rnd: random.Random) -> dict:
    kind = rnd.choice(sorted(_ARCHETYPES))
    arch = _ARCHETYPES[kind]
    lines = [ln for ln in arch["lines"] if rnd.random() > 0.2] or [arch["lines"][0]]
    if rnd.random() < 0.2:
        lines.append(rnd.choice([ln for ln in _FLAG if ln not in lines] or ["gl"]))
    name = f"Synthetic {kind.title()} {rnd.randint(100, 999)}"
    fein = f"{rnd.randint(10, 99)}-{rnd.randint(1000000, 9999999)}"
    employees = rnd.choice([0, 3, 8, 25, 60])
    revenue = rnd.choice([400_000, 1_500_000, 6_000_000])
    payroll = int(revenue * rnd.choice([0.2, 0.35, 0.95, 1.4]))          # some unusual
    eff_year = rnd.choice([2025, 2026, 2026, 2027])
    eff = f"0{rnd.randint(1, 9)}/15/{eff_year}"
    exp = f"{eff[:6]}{eff_year + (0 if rnd.random() < 0.1 else 1)}"     # 10%: backwards term
    f: Dict[str, Any] = {
        "applicant_name": _env(name), "fein": _env(fein),
        "mailing_address": _env(f"{rnd.randint(10, 9999)} Main St, Denver, CO 80202"),
        "entity_type": _env(rnd.choice(["LLC", "Corporation"])),
        "contact_name": _env("Jordan Example"), "contact_phone": _env("303-555-0199"),
        "contact_email": _env("jordan@example.com"),
        "producer_name": _env("Example Insurance Agency"),
        "operations_description": _env(arch["ops"]), "naics_code": _env(arch["naics"]),
        "total_revenue": _env(str(revenue)), "total_payroll": _env(str(payroll)),
        "num_employees": _env(str(employees)),
        "years_in_business": _env(str(rnd.choice([1, 4, 12, 30]))),
        "effective_date": _env(eff), "expiration_date": _env(exp),
        "prior_carrier": _env("Example Mutual Insurance Company"),
    }
    flags = {_FLAG[ln]: True for ln in lines}
    if "gl" in lines:
        f["gl_each_occurrence"] = _env("$1,000,000")
        f["gl_aggregate"] = _env("$2,000,000")
        f["gl_class_code_schedule"] = _env([{"class_code": arch["gl_code"],
                                             "classification": arch["ops"][:40],
                                             "basis": "Sales", "exposure": str(revenue)}])
    if "auto" in lines:
        f["auto_liability_limit"] = _env(rnd.choice(["$1,000,000", "$1,000,000", "$500,000"]))
        n = rnd.randint(1, 6)
        f["auto_vin_schedule"] = _env([{"year": str(2015 + i), "make": "Ford", "model": "F-250",
                                        "vin": f"1FTBF2B6{i}GEB{10000 + i}", "cost_new": "45000"}
                                       for i in range(n)])
        if rnd.random() < 0.6:
            f["auto_drivers"] = _env([{"name": f"Driver {i}", "dob": "01/01/1980",
                                       "license_number": f"D{i}123456", "license_state": "CO"}
                                      for i in range(rnd.randint(1, 4))])
    if "wc" in lines:
        f["wc_payroll"] = _env(str(payroll))
        f["wc_class_codes"] = _env([{"code": arch["wc_code"], "description": arch["ops"][:30],
                                     "state": "CO", "payroll": str(payroll)}])
        f["employers_liability_limits"] = _env(rnd.choice(["$1,000,000", "$500,000", "$100,000"]))
    if "property" in lines:
        bval = rnd.choice([500_000, 2_000_000])
        f["property_locations"] = _env([{"address_line1": "100 Main St", "address_city": "Denver",
                                         "address_state": "CO", "address_zip": "80202",
                                         "building_value": str(bval), "bpp_value": "250000",
                                         "construction_type": "Masonry"}])
        f["property_building_value"] = _env(str(bval))
        f["property_bpp_value"] = _env("250000")
        f["construction_type"] = _env("Masonry")
        f["coinsurance_percentage"] = _env(rnd.choice(["80", "90", "50"]))
        if rnd.random() < 0.5:
            flags["property_has_bi_coverage"] = True
            f["business_income_limit"] = _env("$100,000")
    if "umbrella" in lines:
        f["umbrella_limit"] = _env(rnd.choice(["$1,000,000", "$5,000,000"]))
        f["umbrella_sir"] = _env("$10,000")
    if "crime" in lines:
        f["crime_limit"] = _env("$100,000")
    if "cyber" in lines:
        f["cyber_limit"] = _env("$1,000,000")
    if "inland_marine" in lines:
        f["inland_marine_total_value"] = _env("$150,000")

    # Drop a quarter of what the documents gave (never the name: the package needs one).
    for k in [k for k in f if k != "applicant_name"]:
        if rnd.random() < 0.25:
            f.pop(k)

    coverage_lines = [{"line": _LINE_NAME[ln], "carrier": "Example Mutual Insurance Company",
                       "policy_number": f"EX-{ln.upper()[:3]}-{rnd.randint(1000, 9999)}",
                       "effective_date": eff, "expiration_date": exp,
                       "premium": f"${rnd.randint(1, 30) * 1000:,}"} for ln in lines]
    f["coverage_lines"] = coverage_lines
    docs: List[dict] = []
    for i, ln in enumerate(lines):
        dfacts = {k: copy.deepcopy(v) for k, v in f.items()
                  if k in ("applicant_name", "fein", "mailing_address", "effective_date", "expiration_date")}
        if i == 1 and rnd.random() < 0.15:                                # two docs disagree
            dfacts["fein"] = _env(f"{rnd.randint(10, 99)}-{rnd.randint(1000000, 9999999)}")
        docs.append({"filename": f"{ln}_declarations.pdf", "doc_type": "dec_page",
                     "text": f"{_LINE_NAME[ln]} declarations for {name}.", "facts": dfacts})
    claims = rnd.random() < 0.5
    if rnd.random() < 0.6:
        rows = ([{"date": "03/10/2023", "claim_date": "03/12/2023", "description": "Slip and fall",
                  "line_of_business": "General Liability", "paid": "4200", "reserved_amount": "0",
                  "claim_number": "CL-1"}] if claims else [])
        docs.append({"filename": "loss_runs.pdf", "doc_type": "loss_run",
                     "text": "Loss runs. " + ("One claim." if claims else "No losses reported."),
                     "facts": {"loss_history": _env(rows)} if rows else {}})
        if rows:
            f["loss_history"] = _env(copy.deepcopy(rows))
    recs = [{"form_id": "ACORD_125"}] + [{"form_id": _FORMS[ln]} for ln in lines if ln in _FORMS]
    _merge_derivations(f)
    return {"facts": f, "flags": flags, "docs": docs, "recommendations": recs,
            "structured_issues": [], "_kind": kind, "_lines": lines}


def _merge_derivations(f: dict) -> None:
    """What the extraction merge derives from the facts it was given (a real
    package never holds a premises schedule without its `locations` list)."""
    from services.extraction_service import sync_location_list
    held = f.get("locations")
    sync_location_list(f)
    if f.get("locations") is not held and isinstance(f.get("locations"), list):
        f["locations"] = _env(f["locations"])


# ── The producer who answers everything ──────────────────────────────────────
def _page(row: dict):
    from services import review_plan as RP
    from services import sqs_service as S
    pkg = S.current_package_sqs(row, None, None)
    kd = S.key_details(row["facts"], row.get("flags") or {})
    grouped = S.review_page_grouped_view(row, pkg)
    return pkg, RP.page_items(row, pkg, kd, grouped)


def solve(row: dict, rounds: int = 6) -> Tuple[Optional[int], dict]:
    """(the score the page shows once everything it lists is answered, detail)."""
    from services import review_plan as RP
    row = copy.deepcopy(row)
    suppressed: set = set()
    dead: Dict[str, str] = {}
    for _ in range(rounds):
        pkg, items = _page(row)
        if not pkg or pkg.get("package_sqs_score") is None:
            return None, {"error": "no score"}
        sim = RP._Sim(row)
        sim.suppressed = set(suppressed)
        probes = RP._loss_plan_probes(pkg)
        try:
            from services.loss_history_state import loss_years_required
            full = int(loss_years_required(row["facts"]) or 5)
        except Exception:                                          # noqa: BLE001
            full = 5
        changed = False
        for it in items:
            res = it.get("resolution") if isinstance(it.get("resolution"), dict) else {}
            if it["kind"] == "card" and res.get("mode") in (None, "none"):
                dead[str(it.get("code"))] = str(it.get("label") or "")[:120]
                continue
            changed = RP._apply(sim, it, probes, full) or changed
        suppressed = sim.suppressed
        row = sim.session
        if not changed:
            break
    sim = RP._Sim(row)
    sim.suppressed = set(suppressed)
    shown, raw, cap, reason = sim.measure()
    pkg = getattr(sim, "last_pkg", None) or {}
    return RP._floor(shown), {"raw": raw, "cap": cap, "reason": reason, "dead": dead,
                              "pillars": pkg.get("pillars"), "not_scored": pkg.get("not_scored")}


# ── The wider sweep (28 Oct 2026 review) ─────────────────────────────────────
_ALL_LINES = list(_FLAG)
_ENTITY_TYPES = ["LLC", "Corporation", "Sole Proprietor", "Partnership", "Individual", "Joint Venture",
                 "Trust", "Not For Profit", "S Corporation", "Limited Partnership"]


def wider_package(rnd: random.Random) -> dict:
    """synthetic_package plus the edge cases (28 Oct 2026 review): no lines /
    every line, umbrella + excess tower, two umbrellas, an umbrella with no
    underlying limits, many buildings at one address, property without COPE,
    monopolistic and multi-state WC, HNOA-only auto, split auto limits, a new
    venture, an attested no-loss beside claims, short loss runs, redacted
    premiums, two documents disagreeing on the name or the dates, no / an ended
    proposed term, a renewal, entity types, odd values."""
    row = synthetic_package(rnd)
    f, flags, docs = row["facts"], row["flags"], row["docs"]
    tags = []

    def pick(p):
        return rnd.random() < p

    if pick(0.06):                                   # no lines at all
        tags.append("no_lines")
        for k in list(flags):
            flags.pop(k)
        f["coverage_lines"] = []
        row["recommendations"] = [{"form_id": "ACORD_125"}]
        row["_lines"] = []
    elif pick(0.08):                                 # every line
        tags.append("every_line")
        for ln in _ALL_LINES:
            flags[_FLAG[ln]] = True
        row["_lines"] = list(_ALL_LINES)
        f["coverage_lines"] = [{"line": _LINE_NAME[ln], "carrier": "Example Mutual Insurance Company",
                                "policy_number": f"EX-{ln[:3].upper()}-{rnd.randint(1000, 9999)}",
                                "premium": "$5,000"} for ln in _ALL_LINES]
        row["recommendations"] = [{"form_id": "ACORD_125"}] + [{"form_id": v} for v in _FORMS.values()]
    lines = row["_lines"]
    eff = (f.get("effective_date") or {}).get("value") if isinstance(f.get("effective_date"), dict) else None
    if "umbrella" in lines and pick(0.3):
        tags.append("tower")
        f["coverage_lines"].append({"line": "Excess Liability", "carrier": "Other Excess Co",
                                    "policy_number": "XS-1", "premium": "$2,000",
                                    "limit": "$5,000,000"})
    if "umbrella" in lines and pick(0.15):
        tags.append("two_umbrellas")
        f["coverage_lines"].append({"line": "Commercial Umbrella", "carrier": "Second Umbrella Co",
                                    "policy_number": "UM-2", "premium": "$3,000"})
    if "umbrella" in lines and pick(0.2):
        tags.append("umb_no_underlying")
        for k in ("gl_each_occurrence", "gl_aggregate", "auto_liability_limit", "employers_liability_limits"):
            f.pop(k, None)
    if "property" in lines and pick(0.4):
        n = rnd.randint(2, 5)
        tags.append(f"bldgs{n}")
        rows = []
        for i in range(n):
            r = {"address_line1": "100 Main St", "address_city": "Denver", "address_state": "CO",
                 "address_zip": "80202", "building_number": str(i + 1)}
            if pick(0.6):
                r["building_value"] = str(rnd.choice([300000, 900000]))
            if pick(0.5):
                r["construction_type"] = rnd.choice(["Masonry", "Frame", "Joisted Masonry"])
            if pick(0.4):
                r["year_built"] = str(rnd.choice([1960, 1995, 2010]))
            rows.append(r)
        f["property_locations"] = _env(rows)
    if "property" in lines and pick(0.2):
        tags.append("no_cope")
        for k in ("construction_type", "property_building_value", "property_bpp_value"):
            f.pop(k, None)
        pl = f.get("property_locations")
        if isinstance(pl, dict):
            for r in pl["value"]:
                for c in ("construction_type", "building_value", "bpp_value"):
                    r.pop(c, None)
    if "wc" in lines and pick(0.25):
        tags.append("monopolistic")
        flags["wc_has_monopolistic_state"] = True
        st = rnd.choice(["OH", "WA", "ND", "WY"])
        if isinstance(f.get("wc_class_codes"), dict):
            for r in f["wc_class_codes"]["value"]:
                r["state"] = st
    if "wc" in lines and pick(0.15):
        tags.append("multistate")
        flags["wc_multi_state"] = True
    if "auto" in lines and pick(0.25):
        tags.append("hnoa")
        f.pop("auto_vin_schedule", None); f.pop("auto_drivers", None)
        for cl in f["coverage_lines"]:
            if cl["line"] == "Commercial Auto":
                cl["line"] = "Hired and Non-Owned Auto"
        f["auto_covered_symbols"] = _env([{"coverage": "Liability", "symbols": ["8", "9"]}])
    if "auto" in lines and pick(0.25):
        tags.append("split")
        f.pop("auto_liability_limit", None)
        f["auto_bi_per_person"] = _env("$500,000")
        f["auto_bi_per_accident"] = _env("$1,000,000")
        if pick(0.7):
            f["auto_pd_per_accident"] = _env("$250,000")
        flags["auto_split_limits"] = True
    if pick(0.15):
        tags.append("new_venture")
        f["years_in_business"] = _env("0")
        f["business_start_date"] = _env("06/01/2026")
    if pick(0.12):
        tags.append("attest_vs_claims")
        f["loss_history_no_prior_losses_indicator"] = _env("No known losses")
        rows = [{"date": "05/01/2024", "claim_date": "05/02/2024", "description": "Rear-end collision",
                 "line_of_business": "Commercial Auto", "paid": "8000", "reserved_amount": "0",
                 "claim_number": "CL-9"}]
        f["loss_history"] = _env(rows)
    if pick(0.15):
        tags.append("short_runs")
        f["loss_run_period_start"] = _env("2024-01-01")
        f["loss_run_period_end"] = _env("2026-01-01")
    if pick(0.15):
        tags.append("redacted")
        for cl in f["coverage_lines"]:
            if pick(0.5):
                cl["premium"] = "REDACTED"
    if len(docs) >= 2 and pick(0.15):
        tags.append("conflict_name")
        docs[1].setdefault("facts", {})["applicant_name"] = _env("Totally Different Holdings Inc")
    if len(docs) >= 2 and pick(0.15):
        tags.append("conflict_dates")
        docs[1].setdefault("facts", {})["effective_date"] = _env("11/01/2026")
    if pick(0.12):
        tags.append("no_term")
        f.pop("effective_date", None); f.pop("expiration_date", None)
        for d in docs:
            (d.get("facts") or {}).pop("effective_date", None)
            (d.get("facts") or {}).pop("expiration_date", None)
    elif pick(0.1):
        tags.append("ended_term")
        f["effective_date"] = _env("03/15/2024"); f["expiration_date"] = _env("03/15/2025")
    if pick(0.15):
        tags.append("renewal")
        flags["is_renewal"] = True
        f["is_renewal"] = _env("Yes")
    if pick(0.4):
        f["entity_type"] = _env(rnd.choice(_ENTITY_TYPES))
        tags.append("ent:" + f["entity_type"]["value"])
    if pick(0.2):
        tags.append("odd")
        for k, v in rnd.sample([("total_revenue", "$0"), ("num_employees", "N/A"), ("gl_each_occurrence", "Included"),
                                ("total_payroll", "TBD"), ("naics_code", "999"), ("fein", "00-0000000"),
                                ("umbrella_limit", "$0"), ("coinsurance_percentage", "120"),
                                ("years_in_business", "-3")], 3):
            f[k] = _env(v)
    if pick(0.1):
        tags.append("contractor_flag")
        flags["is_contractor"] = True
    row["_tags"] = tags
    _merge_derivations(f)
    return row



def read_page(row: dict):
    """The review page as the route builds it: the package score, the key
    details, the page's numbers (`complete_screen_shares` - merged rows, the
    plan) and its items."""
    from services import review_plan as RP
    from services import sqs_service as S
    facts, flags = row["facts"], row.get("flags") or {}
    pkg = S.current_package_sqs(row, None, None)
    kd = S.key_details(facts, flags)
    pkg2, kd2 = S.complete_screen_shares(row, None, None, pkg, kd)
    grouped = S.review_page_grouped_view(row, pkg2)
    return pkg2, kd2, RP.page_items(row, pkg2, kd2, grouped)


def plan_problems(pkg: dict) -> List[str]:
    """The owner's rule as the page shows it: score + every item's points (a
    mirror adds nothing) = 100, no item negative, nothing above 100, nothing
    left that no item adds, the safety net idle."""
    out: List[str] = []
    score = pkg.get("package_sqs_score")
    if score is None or not 0 <= score <= 100:
        return [f"score {score}"]
    plan = pkg.get("review_plan")
    if score < 100 and not plan:
        return [f"score {score} with no plan"]
    if plan:
        items = plan.get("items") or []
        pts = [int(i.get("points") or 0) for i in items if not i.get("mirror_of")]
        if any(p < 0 for p in pts):
            out.append("negative points")
        if score + sum(pts) + int(plan.get("left") or 0) != 100:
            out.append(f"score {score} + shown {sum(pts)} + left {plan.get('left')} != 100")
        if int(plan.get("left") or 0):
            out.append(f"{plan['left']} pts no item adds")
    if pkg.get("not_scored"):
        out.append(f"not_scored {pkg['not_scored']}")
    return out


def confirm_conflict(row: dict, fact: str) -> bool:
    """A Data Consistency pick, as the confirm door records it (the
    confirmation map; the merged value is the one kept)."""
    from services.review_plan import _fv
    if str(fact).startswith("row:"):
        # A row-level row (`row_rivals`): the pick is one of the row's shown
        # values, keyed by the row key (29 Oct 2026 end-user review - the
        # harness could not pick one and stopped at 85 on the kit).
        fld = next((f for f in ((row.get("underwriting_consistency") or {}).get("fields") or [])
                    if isinstance(f, dict) and f.get("fact_key") == fact), None)
        vals = [v.get("display") for v in ((fld or {}).get("values") or []) if v.get("display")]
        conf = dict(row.get("underwriting_confirmations") or {})
        if not vals or fact in conf:
            return False
        conf[fact] = {"value": vals[0]}
        row["underwriting_confirmations"] = conf
        return True
    value = _fv(row["facts"], fact) or next(
        (_fv((d or {}).get("facts") or {}, fact) for d in row.get("docs") or []
         if _fv((d or {}).get("facts") or {}, fact)), None)
    conf = dict(row.get("underwriting_confirmations") or {})
    if value is None or fact in conf:
        return False
    conf[fact] = {"value": value}
    row["underwriting_confirmations"] = conf
    return True


def solve_checked(row: dict, rounds: int = 8, order: str = "page",
                  rnd: Optional[random.Random] = None) -> Tuple[Optional[int], List[str]]:
    """Like `solve`, but reads the page as the route does, checks the page's
    numbers at every reading (`plan_problems`), makes Data Consistency picks
    for real (no released message) and never releases a card it cannot
    answer. Returns (the final score, every problem seen)."""
    from services import review_plan as RP
    rnd = rnd or random.Random(0)
    row = copy.deepcopy(row)
    problems: List[str] = []
    for rd in range(rounds):
        pkg, _kd, items = read_page(row)
        problems += [f"r{rd}: {p}" for p in plan_problems(pkg)]
        if pkg.get("package_sqs_score") == 100 and rd:
            break
        sim = RP._Sim(row)
        probes = RP._loss_plan_probes(pkg)
        try:
            from services.loss_history_state import loss_years_required
            full = int(loss_years_required(row["facts"]) or 5)
        except Exception:                                      # noqa: BLE001
            full = 5
        seq = list(items)
        if order == "reverse":
            seq.reverse()
        elif order == "shuffle":
            rnd.shuffle(seq)
        changed = False
        for it in seq:
            res = it.get("resolution") if isinstance(it.get("resolution"), dict) else {}
            if it["kind"] == "dc":
                changed = confirm_conflict(sim.session, it["fact"]) or changed
            elif it["kind"] == "card" and res.get("mode") in (None, "none"):
                continue
            else:
                changed = RP._apply(sim, it, probes, full) or changed
        row = sim.session
        if not changed:
            break
    pkg, _kd, _items = read_page(row)
    return pkg.get("package_sqs_score"), problems


# ── THE SCORING CONTRACT (owner, 29 Oct 2026 - SCORING_RULES.md) ──────────────
# `contract_package` widens the random packages again: random line mixes, facts
# read off an uploaded ACORD (`acord_form` envelopes, an exact or transcriber
# reading), two documents disagreeing on a random fact, random loss histories,
# several holds at once, and packages that only carry hard stops. `contract_
# problems` reads a page against P1 / P2 / P4 / P5; `solve_contract` answers it
# in any order, with sample or honest answers, re-reading after every step.
_CONFLICT_FACTS = ("applicant_name", "fein", "effective_date", "expiration_date",
                   "mailing_address", "total_revenue", "entity_type")
_CLAIM_LINES = ("General Liability", "Commercial Auto", "Workers Compensation",
                "Commercial Property", "Commercial Umbrella")


def _acord_env(value: Any, transcriber: bool) -> dict:
    return {"value": value, "source": "acord_form",
            "confidence": "acord_transcriber" if transcriber else "acord_exact"}


def contract_package(rnd: random.Random) -> dict:
    row = wider_package(rnd)
    f, flags, docs = row["facts"], row["flags"], row["docs"]
    tags = row.setdefault("_tags", [])

    def pick(p):
        return rnd.random() < p

    if pick(0.15):                                   # a random line mix
        lines = rnd.sample(_ALL_LINES, rnd.randint(1, len(_ALL_LINES)))
        tags.append("mix:" + ",".join(sorted(lines)))
        for ln in _ALL_LINES:
            flags.pop(_FLAG[ln], None)
        for ln in lines:
            flags[_FLAG[ln]] = True
        row["_lines"] = lines
        f["coverage_lines"] = [{"line": _LINE_NAME[ln], "carrier": "Example Mutual Insurance Company",
                                "policy_number": f"EX-{ln[:3].upper()}-{rnd.randint(1000, 9999)}",
                                "premium": f"${rnd.randint(1, 30) * 1000:,}"} for ln in lines]
        row["recommendations"] = [{"form_id": "ACORD_125"}] + [
            {"form_id": _FORMS[ln]} for ln in lines if ln in _FORMS]
    if pick(0.3):                                    # an uploaded, filled ACORD 125
        tr = pick(0.5)
        tags.append("acord_tr" if tr else "acord_exact")
        afacts = {}
        for k in [k for k in list(f) if not k.startswith("_") and k != "coverage_lines"]:
            v = f[k]
            if isinstance(v, dict) and "value" in v and isinstance(v["value"], (str, int, float)) and pick(0.5):
                f[k] = _acord_env(v["value"], tr)
                afacts[k] = _acord_env(v["value"], tr)
        afacts.setdefault("applicant_name", _acord_env(_fv0(f, "applicant_name"), tr))
        docs.append({"filename": "acord_125.pdf", "doc_type": rnd.choice(["acord_form", "application"]),
                     "text": "ACORD 125 COMMERCIAL INSURANCE APPLICATION", "facts": afacts,
                     "acord": {"form_id": "ACORD_125"}})
    if len(docs) >= 2 and pick(0.25):                # two documents disagree
        fact = rnd.choice(_CONFLICT_FACTS)
        tags.append("dc:" + fact)
        rival = {"applicant_name": "Different Name Holdings LLC",
                 "fein": f"{rnd.randint(10, 99)}-{rnd.randint(1000000, 9999999)}",
                 "effective_date": "02/01/2027", "expiration_date": "02/01/2028",
                 "mailing_address": "9 Other Rd, Austin, TX 78701",
                 "total_revenue": str(rnd.choice([250_000, 9_000_000])),
                 "entity_type": "Corporation"}[fact]
        a, b = rnd.sample(range(len(docs)), 2)
        if _fv0(f, fact) is not None:
            docs[a].setdefault("facts", {})[fact] = _env(_fv0(f, fact))
        docs[b].setdefault("facts", {})[fact] = _env(rival)
    if pick(0.35):                                   # a random loss history
        n = rnd.randint(0, 4)
        tags.append(f"claims{n}")
        rows = [{"date": f"0{rnd.randint(1, 9)}/1{rnd.randint(0, 9)}/{rnd.choice([2021, 2022, 2023, 2024, 2025])}",
                 "claim_date": "", "description": rnd.choice(["Slip and fall", "Rear-end collision",
                                                              "Water damage", "Back strain"]),
                 "line_of_business": rnd.choice(_CLAIM_LINES), "paid": str(rnd.randint(0, 90000)),
                 "reserved_amount": str(rnd.choice([0, 0, 5000, 40000])),
                 "status": rnd.choice(["Closed", "Open"]), "claim_number": f"CL-{100 + i}"}
                for i in range(n)]
        for r in rows:
            r["claim_date"] = r["date"]
        if rows:
            f["loss_history"] = _env(rows)
        else:
            f.pop("loss_history", None)
        if pick(0.3):
            f["loss_history_no_prior_losses_indicator"] = _env(rnd.choice(["No known losses", "Yes"]))
    if pick(0.15):                                   # several holds at once
        tags.append("many_holds")
        f.pop("effective_date", None)
        f.pop("expiration_date", None)
        for d in docs:
            (d.get("facts") or {}).pop("effective_date", None)
            (d.get("facts") or {}).pop("expiration_date", None)
        if "property" in row["_lines"]:
            for k in ("construction_type", "property_building_value", "property_bpp_value"):
                f.pop(k, None)
        if "umbrella" in row["_lines"]:
            for k in ("gl_each_occurrence", "gl_aggregate", "auto_liability_limit",
                      "employers_liability_limits"):
                f.pop(k, None)
        flags["is_contractor"] = True
    _merge_derivations(f)
    return row


def _fv0(f: dict, k: str):
    v = f.get(k)
    return v.get("value") if isinstance(v, dict) else v


def contract_problems(pkg: dict) -> List[str]:
    """P1 / P2 / P4 / P5 on one reading of a page (SCORING_RULES.md)."""
    out = list(plan_problems(pkg))
    score = pkg.get("package_sqs_score")
    plan = pkg.get("review_plan") or {}
    items = [i for i in (plan.get("items") or []) if isinstance(i, dict)]
    ids = {i.get("id") for i in items}
    # The plan's own guard repaired something the plan should have got right.
    out += [f"repaired {r}" for r in plan.get("contract_repaired") or []]
    for it in items:
        pts = int(it.get("points") or 0)
        iid = it.get("id")
        if it.get("mirror_of"):
            if it["mirror_of"] not in ids:
                out.append(f"P4 mirror of nothing: {iid}")
            if pts:
                out.append(f"P4 mirror counted again: {iid} +{pts}")
            continue
        if it.get("score_item") is False:
            if pts or it.get("under"):
                out.append(f"P5 not a score item with a number: {iid}")
            continue
        if score is not None and score < 100:
            if pts <= 0 and not it.get("under"):
                out.append(f"P1 score item at 0: {iid}")
            if pts <= 0 and it.get("held_by"):
                out.append(f"P1 only 'counts once': {iid}")
        elif pts or it.get("under"):
            out.append(f"R4 a number at 100: {iid}")
    return out


_HONEST = {"rnd": None}


def _honest_probe(original):
    """A person's own answer, not the plan's sample: another choice the fact
    offers, a limit above the threshold, a different count / amount / year -
    each one the fact's own check accepts."""
    from services import review_plan as RP

    def probe(fact, facts=None, session=None):
        base = original(fact, facts, session)
        rnd = _HONEST["rnd"]
        if rnd is None or rnd.random() < 0.3:
            return base
        cands: List[str] = []
        try:
            from services.answer_options import OTHER, options_for
            cands += [o for o in (options_for(fact) or []) if o != OTHER]
        except Exception:                                      # noqa: BLE001
            pass
        low = str(fact).lower()
        is_code = any(w in low for w in ("code", "naics", "sic", "fein", "zip", "phone", "number", "symbol"))
        if str(base).replace(",", "").isdigit() and not is_code:
            n = int(str(base).replace(",", ""))
            if "year" in low and 1800 < n < 2100:
                cands.append(str(rnd.randint(1950, 2020)))
            elif n:
                cands.append(str(n * rnd.choice([2, 3, 5])))
        cands = [c for c in cands if RP._accepts(fact, c)]
        return rnd.choice(cands) if cands else base
    return probe


def _item_rule(item: dict) -> str:
    """The rule an item stands for: a card's rule code, else its kind and the
    facts / tables it answers."""
    if item.get("code"):
        return "card:" + str(item["code"])
    keys = sorted(str(k) for k in (item.get("keys") or []))
    return f"{item.get('kind')}:" + (",".join(keys) or str(item.get("id")))


def solve_contract(row: dict, order: str = "page", rnd: Optional[random.Random] = None,
                   honest: bool = False, every_step: bool = True, rounds: int = 8,
                   reader=None) -> Tuple[Optional[int], List[str], dict]:
    """Answer everything the page lists, in `order` (page / reverse / shuffle),
    re-reading the page after every step (`every_step`) and checking the
    contract at every reading. Returns (final score, problems, final row).
    R3: a reading below 100 where no listed step changes anything is "stuck"."""
    from services import review_plan as RP
    rnd = rnd or random.Random(0)
    reader = reader or (lambda r: read_page(r))
    row = copy.deepcopy(row)
    problems: List[str] = []
    original = RP.probe_value
    own_words = _honest_probe(original) if honest else None
    if honest:
        _HONEST["rnd"] = random.Random(rnd.random())
    try:
        for rd in range(rounds):
            pkg, _kd, items = reader(row)
            score = pkg.get("package_sqs_score")
            problems += [f"r{rd}: {p}" for p in contract_problems(pkg)]
            if score is None or score >= 100:
                if score is not None and score > 100:
                    problems.append(f"R4 score {score}")
                break
            seq = list(items)
            if order == "reverse":
                seq.reverse()
            elif order == "shuffle":
                rnd.shuffle(seq)
            probes = RP._loss_plan_probes(pkg)
            try:
                from services.loss_history_state import loss_years_required
                full = int(loss_years_required(row["facts"]) or 5)
            except Exception:                                  # noqa: BLE001
                full = 5
            changed = False
            done_ids: List[Any] = []
            # The page a person sees after each step: an item it no longer lists
            # (a key detail answered took its Recommendations twin off) is not
            # answered again (seed 32: the stale FEIN row re-typed a stand-in over
            # the documents' FEIN the person had just typed).
            current_rules = {_item_rule(x) for x in items}
            for it in seq:
                if every_step and _item_rule(it) not in current_rules:
                    continue
                sim = RP._Sim(row)
                res = it.get("resolution") if isinstance(it.get("resolution"), dict) else {}
                if it["kind"] == "dc":
                    did = confirm_conflict(sim.session, it["fact"])
                elif it["kind"] == "card" and res.get("mode") in (None, "none"):
                    continue
                else:
                    # A person answers in their own words first (the page's
                    # reading never sees them); what is still listed afterwards
                    # they fix as the page suggests.
                    if own_words is not None and rd == 0:
                        RP.probe_value = own_words
                    try:
                        did = RP._apply(sim, it, probes, full)
                    finally:
                        RP.probe_value = original
                if not did:
                    continue
                changed = True
                row = sim.session
                if every_step:
                    p2, _k2, _i2 = reader(row)
                    current_rules = {_item_rule(x) for x in _i2}
                    # RULE 2 (owner, 30 Oct 2026): a correct answer never raises an
                    # item that was not on the page before, other than the step's own
                    # declared follow-ups (`leads_to`). Compared by RULE, not by id -
                    # an id carries the message, and a message names what is left.
                    before = {_item_rule(x) for x in seq} | {_item_rule(x) for x in items}
                    # A row asking only for boxes already listed is not new: a
                    # merged row ("hydrant + fire department + ...") splits into
                    # its own rows once its shares change - same questions, one
                    # listed before. Cards keep their rule code (a new card is new).
                    before_keys = {str(k) for x in list(seq) + list(items) for k in (x.get("keys") or [])}
                    # The step's declared follow-ups ride on the PLAN's copy of the
                    # item (`review_plan.items[].leads_to`, labels); a page item
                    # carries none of its own.
                    # A follow-up declared by a step done earlier this round may
                    # surface after a later one (the order the person works in
                    # is theirs) - still declared, so not a surprise.
                    done_ids.append(it.get("id"))
                    allowed = set()
                    for _p in ((pkg.get("review_plan") or {}).get("items") or []):
                        if isinstance(_p, dict) and _p.get("id") in done_ids:
                            allowed |= {str(x) for x in (_p.get("leads_to") or [])}
                    allowed |= {str(x) for x in (it.get("leads_to") or [])}
                    for x in _i2:
                        rk = _item_rule(x)
                        _xk = [str(k) for k in (x.get("keys") or [])]
                        if (x.get("kind") not in ("card", "dc") and _xk and all(k in before_keys for k in _xk)):
                            continue
                        if (rk not in before and rk not in allowed and str(x.get("id")) not in allowed
                                and str(x.get("label") or "")[:120] not in allowed):
                            problems.append(f"NEW after {it['id']}: {rk}")
                    s2 = p2.get("package_sqs_score")
                    # G13 (owner, 30 Oct 2026): a correct answer never lowers the score,
                    # unless the plan declared that step's cost (`cost`).
                    _prev = getattr(sim, "_score_before", None)
                    _plan_it = next((_p for _p in ((pkg.get("review_plan") or {}).get("items") or [])
                                     if isinstance(_p, dict) and _p.get("id") == it.get("id")), {})
                    if (s2 is not None and isinstance(score, (int, float)) and s2 < score
                            and not it.get("cost") and not _plan_it.get("cost") and it.get("kind") != "dc"):
                        problems.append(f"DROP after {it['id']}: {score} -> {s2}")
                    if s2 is not None:
                        score = s2
                    if s2 is not None and s2 > 100:
                        problems.append(f"R4 score {s2}")
                    problems += [f"r{rd} after {it['id']}: {p}" for p in contract_problems(p2)
                                 if p.startswith(("P2", "score", "negative"))]
            if not changed:
                problems.append(f"R3 stuck at {score}: no listed item moves it "
                                f"({[i['id'] for i in items][:8]})")
                break
        pkg, _kd, _items = reader(row)
        final = pkg.get("package_sqs_score")
    finally:
        RP.probe_value = original
        _HONEST["rnd"] = None
    if final != 100 and not any(p.startswith("R3") for p in problems):
        problems.append(f"R2 ended at {final}")
    return final, problems, row
