"""SHAPE FUZZ HARNESS (owner, 30 Oct 2026).

Bugs kept being found one live package at a time - a wrapped table cell cutting a
VIN, an undated "RENEWAL OF X-24" unkeying ACORD 125's prior grid, a loss-run
valuation date kept from the OLD run, contact rows making an unused named-insured
row look used. Every one was a SHAPE nobody tested. This harness builds those
shapes at random (seeded, no customer data) and runs them through the real
deterministic post-extraction pipeline with NO model and NO network:

    per-document facts + text  ->  extraction_pipeline._finalize_pipeline
    (merge_facts, named individuals, the person-value carry, stops, the
    package score - its DB write captured, never sent)
    -> stops_now, current_package_sqs + the review page plan (read_page)
    -> pdf_service._prior_coverage_grid_build / prior_grid_set_aside_rows

and checks INVARIANTS (`problems(case, out)`), not fixtures.

`shape_case(seed)` -> the case: {"docs", "prior_facts", "truth"}. `truth` is what
the generator KNOWS (distinct vehicles, drivers, premises, prior policies, the
latest valuation date, the other insured's values, the person's values).
`run_case(case)` -> the pipeline's outputs. `problems(case, out)` -> list of
"rule: detail" strings; empty = the package is sound.
"""
from __future__ import annotations

import asyncio
import copy
import random
import re
from typing import Any, Dict, List, Optional, Tuple

# ── vocabulary ───────────────────────────────────────────────────────────────
_VIN_CH = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
_MAKES = [("FORD", "F-250"), ("CHEVROLET", "SILVERADO"), ("RAM", "2500"), ("TOYOTA", "TACOMA"),
          ("ISUZU", "NPR"), ("FREIGHTLINER", "M2"), ("GMC", "SIERRA")]
_FIRST = ["James", "Maria", "Robert", "Linda", "David", "Susan", "Carlos", "Priya", "Wei", "Aisha"]
_LAST = ["Garcia", "Nguyen", "Okafor", "Schmidt", "Patel", "Romero", "Kowalski", "Haddad"]
_STREETS = ["Main", "Oak", "Industrial", "Commerce", "Lincoln", "Market", "Quarry"]
_CITIES = [("Denver", "CO", "80202"), ("Aurora", "CO", "80012"), ("Mesa", "AZ", "85201"),
           ("Boise", "ID", "83702"), ("Tulsa", "OK", "74103")]
_CARRIERS = ["Harborview Mutual Insurance Company", "Granite Peak Casualty Company",
             "Blue Mesa Indemnity Company", "Northline Fire & Marine Insurance Company"]
_LINES = [("gl", "Commercial General Liability", "has_general_liability"),
          ("auto", "Commercial Automobile", "has_auto_coverage"),
          ("property", "Commercial Property", "has_property_coverage"),
          ("wc", "Workers Compensation", "has_workers_comp"),
          ("umbrella", "Commercial Umbrella", "has_umbrella"),
          ("crime", "Crime", "has_crime"),
          ("inland_marine", "Inland Marine", "has_inland_marine")]
_PREFIX = {"gl": "GL", "auto": "CA", "property": "CP", "wc": "WC", "umbrella": "UMB",
           "crime": "CR", "inland_marine": "IM"}


def _vin(rnd: random.Random, year: int) -> str:
    # A 17-character VIN from 1981; earlier vehicles carry a short serial.
    n = 17 if year >= 1981 else rnd.choice([8, 10, 11, 13])
    return "".join(rnd.choice(_VIN_CH) for _ in range(n))


def _mdy(y: int, m: int, d: int = 15) -> str:
    return f"{m:02d}/{d:02d}/{y}"


def _add_months(y: int, m: int, k: int) -> Tuple[int, int]:
    t = y * 12 + (m - 1) + k
    return t // 12, t % 12 + 1


def _street_variants(num: int, street: str) -> List[str]:
    return [f"{num} {street} St", f"{num} {street} Street", f"{num} {street.upper()} ST."]


# ── the generator ────────────────────────────────────────────────────────────
def shape_case(seed: int) -> dict:
    rnd = random.Random(seed)
    name = f"{rnd.choice(['Summit', 'Cedar', 'Ironwood', 'Lakeside', 'Pioneer'])} " \
           f"{rnd.choice(['Builders', 'Logistics', 'Electric', 'Foods', 'Fabrication'])} " \
           f"{rnd.choice(['LLC', 'Inc.', 'Co.'])}"
    fein = f"{rnd.randint(10, 99)}-{rnd.randint(1000000, 9999999)}"
    city, st, zp = rnd.choice(_CITIES)
    renewal = rnd.random() < 0.6
    months = rnd.choice([12, 12, 12, 6])
    # The CURRENT programme's term (on a renewal, the expiring term the decs print;
    # it may already have ended or be in force).
    cy = rnd.choice([2025, 2026])
    cm = rnd.randint(1, 12)
    ey, em = _add_months(cy, cm, months)
    eff, exp = _mdy(cy, cm), _mdy(ey, em)

    k = rnd.randint(1, 7)
    lines = rnd.sample(_LINES, k)
    one_carrier = rnd.random() < 0.5
    carriers = [_CARRIERS[0]] if one_carrier else rnd.sample(_CARRIERS, min(3, len(_CARRIERS)))
    current = []
    for i, (key, label, flag) in enumerate(lines):
        current.append({"key": key, "line": label, "flag": flag,
                        "carrier": carriers[i % len(carriers)],
                        "policy_number": f"{_PREFIX[key]}-{rnd.randint(100000, 999999)}-{str(cy)[2:]}",
                        "premium": f"${rnd.randint(2, 40) * 500:,}"})
    keys = {c["key"] for c in current}

    truth: Dict[str, Any] = {"name": name, "fein": fein, "renewal": renewal, "eff": eff, "exp": exp,
                             "current_numbers": {c["policy_number"] for c in current}}
    common = {"applicant_name": name, "fein": fein,
              "mailing_address": f"{rnd.randint(100, 9999)} {rnd.choice(_STREETS)} Ave, {city}, {st} {zp}",
              "effective_date": eff, "expiration_date": exp}
    if rnd.random() < 0.3:
        common["mailing_address"] = f"P.O. Box {rnd.randint(100, 9999)}, {city}, {st} {zp}"
        truth["po_box"] = common["mailing_address"]
    if renewal:
        common["is_renewal"] = True

    docs: List[dict] = []

    def dec(key: str, facts: dict, text: str, doc_type: str = "dec_page") -> dict:
        d = {"filename": f"{key}_{len(docs)}.pdf", "doc_type": doc_type,
             "text": text, "facts": facts, "flags": {}}
        docs.append(d)
        return d

    # One declarations page per current line.
    for c in current:
        f = dict(common)
        f["carrier_name"] = c["carrier"]
        f["policy_number"] = c["policy_number"]
        f["coverage_lines"] = [{"line": c["line"], "carrier": c["carrier"],
                                "policy_number": c["policy_number"], "effective_date": eff,
                                "expiration_date": exp, "premium": c["premium"]}]
        f["lines_of_business"] = [c["line"]]
        text = (f"{c['line'].upper()} DECLARATIONS\nNAMED INSURED: {name}\nFEIN: {fein}\n"
                f"POLICY NUMBER: {c['policy_number']}\nCOMPANY: {c['carrier']}\n"
                f"POLICY PERIOD: {eff} TO {exp}\nTOTAL PREMIUM: {c['premium']}\n")
        if renewal and rnd.random() < 0.5:
            # "RENEWAL OF X-24" - a number with no dates (live 8aa8f3ad).
            old = re.sub(r"-\d\d$", f"-{str(cy - 1)[2:]}", c["policy_number"])
            text += f"RENEWAL OF: {old}\n"
            f["prior_policy_number"] = old
        d = dec(c["key"], f, text)
        d["flags"][c["flag"]] = True
        c["doc"] = d

    # ── vehicles / drivers on the auto dec ──────────────────────────────────
    if "auto" in keys:
        ad = next(c["doc"] for c in current if c["key"] == "auto")
        nv = rnd.randint(1, 8)
        vehicles = []
        seen_vins = set()
        for i in range(nv):
            yr = rnd.choice([1972, 1979, 1985, 1999, 2008, 2015, 2019, 2023, 2024])
            mk, md = rnd.choice(_MAKES)
            vin = _vin(rnd, yr)
            while vin in seen_vins:
                vin = _vin(rnd, yr)
            seen_vins.add(vin)
            v = {"year": str(yr), "make": mk, "model": md, "vin": vin,
                 "garaging_state": st if rnd.random() < 0.7 else rnd.choice(["NM", "UT"])}
            if rnd.random() < 0.3:
                v["lienholder"] = "First Plains Bank"
            vehicles.append(v)
        truth["vins"] = [v["vin"] for v in vehicles]
        ad["facts"]["auto_vin_schedule"] = [dict(v) for v in vehicles]
        ad["text"] += "SCHEDULE OF COVERED AUTOS\n" + "".join(
            f"{i + 1} {v['year']} {v['make']} {v['model']} VIN {v['vin']}\n" for i, v in enumerate(vehicles))
        # A second document (a vehicle schedule) lists some of them again, one VIN
        # read with a character dropped or added (a wrapped cell).
        if nv > 1 and rnd.random() < 0.6:
            again = [dict(v) for v in rnd.sample(vehicles, rnd.randint(1, nv))]
            mutated = None
            if again[0]["vin"] and len(again[0]["vin"]) == 17 and rnd.random() < 0.6:
                vv = again[0]["vin"]
                mutated = vv[:-1] if rnd.random() < 0.5 else vv + rnd.choice("0123456789")
                again[0]["vin"] = mutated
            truth["vin_misreads"] = {mutated: again[0]["vin"]} if mutated else {}
            sd = dec("vehicle_schedule", dict(common, auto_vin_schedule=again),
                     "VEHICLE SCHEDULE\n" + "".join(
                         f"{v['year']} {v['make']} {v['model']} {v['vin']}\n" for v in again),
                     doc_type="schedule")
            sd["flags"]["has_auto_coverage"] = True
        nd = rnd.randint(1, 8)
        drivers, names = [], set()
        for i in range(nd):
            nm = f"{rnd.choice(_FIRST)} {rnd.choice(_LAST)}"
            if nm in names:
                continue
            names.add(nm)
            drivers.append({"name": nm, "dob": _mdy(rnd.randint(1955, 2001), rnd.randint(1, 12), rnd.randint(1, 28)),
                            "license_number": f"D{rnd.randint(1000000, 9999999)}", "license_state": st})
        truth["drivers"] = [d["name"] for d in drivers]
        ad["facts"]["auto_drivers"] = [dict(d) for d in drivers]
        ad["text"] += "DRIVER SCHEDULE\n" + "".join(
            f"{d['name']} DOB {d['dob']} LIC {d['license_number']} {d['license_state']}\n" for d in drivers)
        if rnd.random() < 0.4:
            # The same drivers again on an application, names upper-cased.
            again = [dict(d, name=d["name"].upper()) for d in drivers]
            dec("application", dict(common, auto_drivers=again),
                "DRIVER LIST\n" + "".join(f"{d['name']} {d['dob']}\n" for d in again),
                doc_type="application")

    # ── premises ────────────────────────────────────────────────────────────
    if keys & {"property", "gl"}:
        npre = rnd.randint(1, 4)
        premises = []
        used = set()
        for i in range(npre):
            num = rnd.randint(10, 9999)
            street = rnd.choice(_STREETS)
            if (num, street) in used:
                continue
            used.add((num, street))
            pc, ps, pz = rnd.choice(_CITIES)
            premises.append({"num": num, "street": street, "city": pc, "state": ps, "zip": pz,
                             "buildings": rnd.randint(1, 3)})
        truth["premises"] = [(p["num"], p["street"].lower()) for p in premises]
        rows = []
        for p in premises:
            spell = _street_variants(p["num"], p["street"])
            for b in range(p["buildings"]):
                rows.append({"address": f"{rnd.choice(spell)}, {p['city']}, {p['state']} {p['zip']}",
                             "building_number": str(b + 1),
                             "building_value": str(rnd.randint(2, 40) * 50000),
                             "construction_type": rnd.choice(["Frame", "Masonry", "Joisted Masonry"]),
                             "year_built": str(rnd.randint(1950, 2020))})
        tgt = next((c["doc"] for c in current if c["key"] == "property"), None) or \
            next(c["doc"] for c in current if c["key"] == "gl")
        tgt["facts"]["property_locations"] = rows
        tgt["facts"]["locations"] = [r["address"] for r in rows]
        tgt["text"] += "PREMISES SCHEDULE\n" + "".join(
            f"LOC {i + 1} BLDG {r['building_number']} {r['address']}\n" for i, r in enumerate(rows))

    # ── prior history ───────────────────────────────────────────────────────
    prior: List[dict] = []
    style = rnd.choice(["dated", "dated", "undated_mix", "gaps", "none"])
    if style != "none":
        years_back = [1, 2, 3] if style != "gaps" else [1, 3, 5]
        for c in current:
            for yb in years_back:
                if rnd.random() < 0.3:
                    continue
                py = cy - yb
                dated = style != "undated_mix" or rnd.random() < 0.6
                prior.append({"line": c["line"], "carrier": rnd.choice(_CARRIERS),
                              "policy_no": f"{_PREFIX[c['key']]}-{rnd.randint(100000, 999999)}-{str(py)[2:]}",
                              "effective": _mdy(py, cm) if dated else None,
                              "expiration": _mdy(py + 1, cm) if dated else None,
                              "premium": f"${rnd.randint(2, 40) * 500:,}" if rnd.random() < 0.8 else None})
        if "umbrella" in keys and rnd.random() < 0.5:
            # Two umbrella layers in one year.
            py = cy - 1
            for lab in ("Commercial Umbrella", "Excess Liability"):
                prior.append({"line": lab, "carrier": rnd.choice(_CARRIERS),
                              "policy_no": f"XS-{rnd.randint(100000, 999999)}", "effective": _mdy(py, cm),
                              "expiration": _mdy(py + 1, cm), "premium": f"${rnd.randint(5, 20) * 1000:,}"})
        if prior:
            hd = rnd.choice([c["doc"] for c in current])
            hd["facts"]["prior_coverage_by_line"] = [dict(p) for p in prior]
            hd["text"] += "PRIOR INSURANCE\n" + "".join(
                f"{p['line']} {p['carrier']} {p['policy_no']} {p['effective'] or ''} "
                f"{p['expiration'] or ''} {p['premium'] or ''}\n" for p in prior)
    truth["prior"] = prior
    truth["prior_style"] = style

    # ── loss runs ───────────────────────────────────────────────────────────
    nl = rnd.choice([0, 1, 1, 2, 3])
    runs = []
    claim_pool = [{"date": _mdy(cy - rnd.randint(1, 4), rnd.randint(1, 12)), "claim_number": f"CL-{rnd.randint(1000, 9999)}",
                   "description": rnd.choice(["Rear-end collision", "Slip and fall", "Water damage"]),
                   "paid": str(rnd.randint(1, 90) * 100), "line_of_business": rnd.choice([c["line"] for c in current])}
                  for _ in range(rnd.randint(0, 4))]
    for i in range(nl):
        vy = cy - rnd.choice([0, 0, 1, 2, 3])
        val = _mdy(vy, rnd.randint(1, 12), rnd.randint(1, 28))
        start = _mdy(cy - 5 + rnd.randint(-1, 1), cm)
        end = _mdy(vy, cm)
        attest = not claim_pool and rnd.random() < 0.5
        claims = [dict(c) for c in claim_pool if rnd.random() < 0.7]   # the same claim on two runs
        f = dict(common, loss_run_valuation_date=val, loss_run_period_start=start, loss_run_period_end=end)
        if claims:
            f["loss_history"] = claims
        txt = f"LOSS RUN\nINSURED: {name}\nVALUED AS OF {val}\nPOLICY PERIOD {start} - {end}\n"
        if attest:
            txt += "NO LOSSES REPORTED\n"
        txt += "".join(f"{c['claim_number']} {c['date']} {c['description']} PAID {c['paid']}\n" for c in claims)
        dec("loss_run", f, txt, doc_type="loss_run")
        runs.append(val)
    truth["valuations"] = runs

    # ── another insured's document ──────────────────────────────────────────
    if rnd.random() < 0.2:
        other = {"applicant_name": "Harborline Plumbing Inc.", "fein": "91-2233445",
                 "total_revenue": "$7,712,345", "num_employees": "61",
                 "mailing_address": "18 Pier Rd, Tacoma, WA 98402",
                 "dba_name": "Harborline Services"}
        dec("other_insured", dict(other),
            "COMMERCIAL GENERAL LIABILITY DECLARATIONS\nNAMED INSURED: Harborline Plumbing Inc.\n"
            "FEIN 91-2233445\n18 Pier Rd, Tacoma, WA 98402\n")
        truth["other"] = other

    # Business facts on the first document.
    docs[0]["facts"].setdefault("total_revenue", f"${rnd.randint(5, 90) * 100_000:,}")
    docs[0]["facts"].setdefault("num_employees", str(rnd.randint(1, 80)))
    docs[0]["facts"].setdefault("operations_description", "Commercial contracting and related services.")

    # ── a person's values beside the documents' ─────────────────────────────
    prior_facts: Dict[str, Any] = {}
    if rnd.random() < 0.5:
        prior_facts["num_employees"] = {"value": str(rnd.randint(81, 200)), "source": "producer",
                                        "confidence": "producer"}
    if rnd.random() < 0.3:
        prior_facts["years_in_business"] = {"value": str(rnd.randint(2, 40)), "source": "producer",
                                            "confidence": "producer"}
    truth["person"] = {k: v["value"] for k, v in prior_facts.items()}
    return {"seed": seed, "docs": docs, "prior_facts": prior_facts, "truth": truth}


# ── running the real pipeline ────────────────────────────────────────────────
def _fv(facts: dict, key: str):
    v = (facts or {}).get(key)
    return v.get("value") if isinstance(v, dict) and "value" in v else v


def run_case(case: dict, patcher=None) -> dict:
    """Run `_finalize_pipeline` (persistence captured), then the score, the page
    plan, the stops and ACORD 125's prior grid on the stored-shape row.
    `patcher(obj, name, value)` - monkeypatch.setattr (the test's)."""
    import services.extraction_pipeline as ep
    import services.yes_no_lexicon as ynl
    calls: Dict[str, Any] = {}

    async def _upd(session_id, payload, delete_facts=None, **_kw):
        calls["payload"] = payload

    async def _none(*_a, **_k):
        return None

    async def _zero(*_a, **_k):
        return 0

    patcher(ep, "upd_processing_session", _upd)
    patcher(ep, "_submitting_account_for", _none)
    patcher(ynl, "learn", _zero)
    docs = copy.deepcopy(case["docs"])
    asyncio.run(ep._finalize_pipeline(docs, "user-shape", session_id=f"shape-{case['seed']}",
                                      prior_facts=copy.deepcopy(case["prior_facts"]), prior_flags={}))
    payload = calls.get("payload") or {}
    row = {k: payload.get(k) for k in ("facts", "flags", "docs", "recommendations", "structured_issues",
                                        "underwriting_consistency", "underwriting_confirmations",
                                        "integrity", "selected_form_ids", "generated_forms")}
    row["facts"] = row["facts"] or {}
    row["flags"] = row["flags"] or {}
    row["docs"] = row["docs"] or docs
    out: Dict[str, Any] = {"payload": payload, "row": row}

    from services import sqs_service as S
    from services.stops_now import stops_now
    out["stops"] = stops_now(row, pre_form=True)
    pkg = S.current_package_sqs(row, None, None)
    kd = S.key_details(row["facts"], row["flags"])
    pkg2, _kd2 = S.complete_screen_shares(row, None, None, pkg, kd)
    out["pkg"] = pkg2
    from services import pdf_service as P
    out["grid"], out["grid_years"] = P._prior_coverage_grid_build(row["facts"])
    out["set_aside"] = P.prior_grid_set_aside_rows(row["facts"])
    try:
        from services import invariants as INV            # another lane's door, when it exists
        out["invariants"] = INV.check(row, stage="pre_form")
    except ImportError:
        out["invariants"] = None
    return out


# ── the invariants ───────────────────────────────────────────────────────────
def _alnum(v: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(v or "").upper())


def _date_key(v: Any) -> Optional[Tuple[int, int, int]]:
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(v or ""))
    return (int(m.group(3)), int(m.group(1)), int(m.group(2))) if m else None


def problems(case: dict, out: dict) -> List[str]:
    t = case["truth"]
    facts = out["row"]["facts"]
    bad: List[str] = []

    # 1. No vehicle duplicated, none lost.
    vins = t.get("vins")
    if vins:
        rows = _fv(facts, "auto_vin_schedule") or []
        got = [_alnum(r.get("vin")) for r in rows if isinstance(r, dict)]
        for v in vins:
            hits = [g for g in got if g == _alnum(v) or (len(g) >= 16 and (g in _alnum(v) or _alnum(v) in g))]
            if not hits:
                bad.append(f"vehicle lost: {v}")
            elif len(hits) > 1:
                bad.append(f"vehicle duplicated: {v} x{len(hits)} {hits}")
        if len([r for r in rows if isinstance(r, dict)]) > len(vins):
            bad.append(f"vehicle rows {len(rows)} > vehicles {len(vins)}")
        for g in got:
            if len(vins) and g and len(g) >= 16 and g not in {_alnum(v) for v in vins} \
                    and not any(_alnum(v) in g for v in vins):
                bad.append(f"vehicle kept with a misread VIN: {g}")

    # 2. No driver duplicated, none lost (a named individual may move out).
    drv = t.get("drivers")
    if drv:
        rows = _fv(facts, "auto_drivers") or []
        names = [re.sub(r"\s+", " ", str(r.get("name") or "")).strip().lower() for r in rows if isinstance(r, dict)]
        for n in drv:
            c = names.count(n.lower())
            if c == 0:
                bad.append(f"driver lost: {n}")
            elif c > 1:
                bad.append(f"driver duplicated: {n} x{c}")

    # 3. One premises is one location: the buildings of one address never read
    #    as several premises, and a P.O. box is never a premises.
    prem = t.get("premises")
    if prem:
        rows = _fv(facts, "property_locations") or []
        groups: Dict[Tuple[str, str], set] = {}
        for r in rows:
            if not isinstance(r, dict):
                continue
            a = str(r.get("address") or r.get("address_line1") or "")
            m = re.match(r"\s*(\d+)\s+([A-Za-z]+)", a)
            if not m:
                continue
            groups.setdefault((m.group(1), m.group(2).lower()), set()).add(str(r.get("building_number") or ""))
        for num, street in prem:
            if (str(num), street) not in groups:
                bad.append(f"premises lost: {num} {street}")
        per_key: Dict[Tuple[str, str, str], int] = {}
        for r in rows:
            if not isinstance(r, dict):
                continue
            a = str(r.get("address") or r.get("address_line1") or "")
            m = re.match(r"\s*(\d+)\s+([A-Za-z]+)", a)
            if m:
                k = (m.group(1), m.group(2).lower(), str(r.get("building_number") or ""))
                per_key[k] = per_key.get(k, 0) + 1
        for k, c in per_key.items():
            if c > 1:
                bad.append(f"one building listed {c} times: {k}")
        locs = _fv(facts, "locations") or []
        if t.get("po_box") and any("box" in str(l).lower() for l in (locs if isinstance(locs, list) else [])):
            bad.append("a P.O. box listed as a premises location")

    # 4. Prior history: no prior policy lost or placed twice; keyed by year.
    prior = t.get("prior") or []
    grid, years = out["grid"], out["grid_years"]
    placed = [_alnum(e.get("policy_no")) for e in grid.values() if isinstance(e, dict)]
    aside = [_alnum(r.get("policy_no")) for r in out["set_aside"]]
    if any(p.get("effective") for p in prior) and placed and not years:
        bad.append("prior grid not keyed by year though a policy is dated")
    # The grid's own three years (the current term is year one when the proposal
    # follows it - `_current_policies_before_the_proposal`); older is optional.
    dated_years = sorted({_date_key(p["effective"])[0] for p in prior if p.get("effective")}, reverse=True)
    window = set(years) if years else {str(y) for y in dated_years[:3]}
    for p in prior:
        pn = _alnum(p["policy_no"])
        y = str(_date_key(p["effective"])[0]) if p.get("effective") else None
        n = placed.count(pn) + aside.count(pn)
        if y is not None and y not in window:
            if n:
                pass                                         # beyond the window: optional
            continue
        if n == 0:
            bad.append(f"prior policy lost: {p['line']} {p['policy_no']} {y}")
        elif n > 1:
            bad.append(f"prior policy placed twice: {p['policy_no']} (grid {placed.count(pn)}, 101 {aside.count(pn)})")

    # 5. Loss valuation date = the latest included run's.
    vals = [v for v in t.get("valuations") or []]
    if vals:
        got = _fv(facts, "loss_run_valuation_date")
        want = max(vals, key=_date_key)
        if _date_key(got) != _date_key(want):
            bad.append(f"loss valuation date {got!r}, latest run {want!r}")

    # 6. No fact from another insured's document.
    other = t.get("other")
    if other:
        for k, v in other.items():
            got = _fv(facts, k)
            if got is not None and _alnum(got) == _alnum(v):
                bad.append(f"another insured's {k} = {v!r}")

    # 7. A person's value is never overwritten.
    for k, v in (t.get("person") or {}).items():
        got = _fv(facts, k)
        if str(got) != str(v):
            bad.append(f"person's {k} {v!r} became {got!r}")

    # 8. The plan adds up; the caps match the open stops.
    pkg = out["pkg"] or {}
    score = pkg.get("package_sqs_score")
    if score is None:
        # An integrity review pending (another insured's document) holds the
        # score by design (`current_package_sqs` -> None).
        if not ((out["payload"].get("integrity") or {}).get("review_required")):
            bad.append("no package score")
    else:
        plan = pkg.get("review_plan") or {}
        items = [i for i in (plan.get("items") or []) if isinstance(i, dict)]
        pts = sum(int(i.get("points") or 0) for i in items if not i.get("mirror_of"))
        if score < 100 and score + pts + int(plan.get("left") or 0) != 100:
            bad.append(f"plan: score {score} + points {pts} + left {plan.get('left')} != 100")
        if any(int(i.get("points") or 0) < 0 for i in items):
            bad.append("plan: negative points")
        for r in plan.get("contract_repaired") or []:
            bad.append(f"plan repaired: {r}")
        hard = pkg.get("open_hard_stops")
        hard_n = len(hard) if isinstance(hard, list) else int(hard or 0)
        if hard_n and score > 60:
            bad.append(f"cap: {hard_n} open hard stop(s) with score {score}")
        if pkg.get("submission_ready") and hard_n:
            bad.append("cap: submission ready with an open hard stop")

    # 9. Another lane's invariants door, when present.
    for v in out.get("invariants") or []:
        bad.append(f"invariant {v.get('rule')}: {v.get('detail')} @ {v.get('where')}")
    return bad


# ═════════════════════════════════════════════════════════════════════════════
# AFTER FORMS (30 Oct 2026) - stamp the recommended forms with NO model, score
# them as `arq_service.recalculate_session_scores` does, and check the
# after-forms rules. Added beside `run_case` / `problems`; neither changes.
# ═════════════════════════════════════════════════════════════════════════════
AFTER_FORMS = ("ACORD_125", "ACORD_126", "ACORD_127", "ACORD_130", "ACORD_131", "ACORD_140", "ACORD_25")


def _rescore_forms(row: dict, form_ids: List[str]) -> Tuple[dict, dict]:
    """(per-form sqs by id, package sqs) - the recalculation's recipe."""
    from services import sqs_service as S
    from services.stops_now import stops_now
    from services.loss_history_state import package_has_loss_runs
    from services.extraction_service import _fv as _efv
    facts, flags = row["facts"], row["flags"]
    door = stops_now(row, sorted(form_ids), pre_form=False, facts=facts, flags=flags)
    re_hard, re_soft = list(door["form_hard"]), list(door["form_soft"])
    hard, soft, cf = list(door["hard"]), list(door["soft"]), list(door["cross_issues"])
    docs = row.get("docs") or []
    present = {str(d.get("doc_type") or "") for d in docs if isinstance(d, dict) and not d.get("excluded")}
    has_loss = package_has_loss_runs(docs, facts)
    match = S._check_loss_run_insured_match(docs, _efv(facts, "applicant_name"), facts)
    narr = S._extract_narrative_doc_text(docs)
    try:
        tier2, _ = S.check_tier2(facts, flags)
    except Exception:                                          # noqa: BLE001
        tier2 = 50
    per: Dict[str, dict] = {}
    for fid in form_ids:
        g = row["generated_forms"][fid]
        g["sqs"] = per[fid] = S.calculate_sqs(
            facts=facts, flags=flags, mapped_data=g.get("field_state") or g.get("mapped", {}),
            form_schema=g.get("schema", {}), selected_form_ids=list(form_ids),
            hard_stops=re_hard, soft_stops=re_soft, tier2_score=tier2, form_id=fid,
            confidence_dict=g.get("confidence", {}), session_id="shape", user_id="user-shape",
            calculation_stage="arq_remediated", has_narrative_doc="narrative" in present,
            has_loss_run_doc=has_loss, loss_run_match=match, cross_issues_full=cf,
            narrative_doc_text=narr)
    pkg = S.calculate_package_sqs(
        facts=facts, flags=flags, form_results=list(per.values()), cross_issues=cf,
        hard_stops=hard, soft_stops=soft, session_data=row, session_id="shape",
        user_id="user-shape", calculation_stage="arq_remediated")
    row["hard_stops"], row["soft_stops"], row["cross_form_issues"] = hard, soft, cf
    row["package_sqs"] = pkg
    return per, pkg


def run_after_forms(case: dict, out: dict) -> dict:
    """Stamp ACORD 125 / 126 / 127 / 130 / 131 / 140 / 25 - whichever the
    package's lines recommend - through `form_dry_run.stamp_forms` (the
    deterministic stamp, `allow_llm=False`), store them in the generated-form
    shape, score them, and run the post-form plan and the side panel."""
    from services import form_dry_run as FD
    row = copy.deepcopy(out["row"])
    recs = [str(r.get("form_id")) for r in (row.get("recommendations") or [])
            if isinstance(r, dict) and not r.get("is_source_document")]
    form_ids = [f for f in AFTER_FORMS if f in recs]
    after: Dict[str, Any] = {"form_ids": form_ids, "row": row}
    if not form_ids or (row.get("integrity") or {}).get("review_required"):
        after["skipped"] = True
        return after
    gen, failed = FD.stamp_forms(row, form_ids, row["facts"], row["flags"])
    after["stamp_failed"] = failed
    form_ids = [f for f in form_ids if f in gen]
    row["generated_forms"] = {
        fid: {**g, "field_state": dict(g["mapped"]), "mapped": dict(g["mapped"])}
        for fid, g in gen.items()}
    row["selected_form_ids"] = list(form_ids)
    after["form_ids"] = form_ids
    after["per"], after["pkg"] = _rescore_forms(row, form_ids)
    from services.needs_attention import needs_attention
    after["attention"] = {fid: needs_attention(row["generated_forms"][fid], row["facts"], fid,
                                               flags=row["flags"]) for fid in form_ids}
    from services import sqs_service as S
    kd = S.key_details(row["facts"], row["flags"])
    try:
        after["plan_pkg"], _ = S.complete_screen_shares(row, "shape", "user-shape",
                                                        copy.deepcopy(after["pkg"]), kd)
    except Exception as ex:                                    # noqa: BLE001
        after["plan_pkg"] = {"_error": repr(ex)}
    from services import invariants as INV
    after["invariants"] = INV.check(row, stage="after_forms")
    return after


_VIN_BOX_RE = re.compile(r"VIN|VehicleIdentification", re.I)


def problems_after_forms(case: dict, out: dict, after: dict) -> List[str]:
    if after.get("skipped"):
        return []
    from services import sqs_service as S
    from services import pdf_service as P
    from services.signature_boxes import is_applicant_step
    from services.needs_attention import unused_trailing_row, box_fact_key
    row = after["row"]
    facts, flags = row["facts"], row["flags"]
    bad: List[str] = [f"stamp failed: {p}" for p in after.get("stamp_failed") or []]
    cf = row.get("cross_form_issues") or []

    # 1. The invariants door, after forms.
    for v in after.get("invariants") or []:
        bad.append(f"invariant {v.get('rule')}: {v.get('detail')} @ {v.get('where')}")

    stop_text = " ".join(str(m) for m in (row.get("hard_stops") or []) + (row.get("soft_stops") or []))
    stop_text += " ".join(str(i.get("message") or "") for i in cf if isinstance(i, dict))
    for fid in after["form_ids"]:
        g = row["generated_forms"][fid]
        mapped, conf, schema = g["mapped"], g.get("confidence") or {}, g.get("schema") or {}
        sqs = g.get("sqs") or {}
        s, raw = sqs.get("sqs_score"), sqs.get("raw_sqs_score")
        # 2. The form's score rules.
        block = S._form_download_blocker(fid, mapped, conf)
        warn = S._form_open_warning(fid, mapped, conf, schema, facts, flags, cf)
        cap = sqs.get("cap_applied")
        # A form is also held by the stops it is scored with (field-level /
        # identity, `stops_now` form_hard / form_soft) and its own gates (COPE,
        # umbrella, property) - each named on the score.
        named_hard = bool(sqs.get("ready_blockers") or sqs.get("cap_hard_stops"))
        named_soft = bool(sqs.get("cap_soft_stops") or sqs.get("soft_stops")
                          or (cap == 85 and sqs.get("cap_reason")))
        if isinstance(s, (int, float)) and isinstance(raw, (int, float)):
            if block and s > 60:
                bad.append(f"{fid}: blocker open ({block}) but score {s}")
            if warn and s > 85:
                bad.append(f"{fid}: hold open ({warn}) but score {s}")
            if cap is None and s != raw:
                bad.append(f"{fid}: nothing holds but score {s} != raw {raw}")
            if cap is not None and s != min(raw, int(cap)):
                bad.append(f"{fid}: score {s} != min(raw {raw}, cap {cap})")
            if cap == 60 and not (block or named_hard):
                bad.append(f"{fid}: 60 with no download blocker or hard stop named")
            if cap == 85 and not (warn or named_soft):
                bad.append(f"{fid}: 85 with no hold named")
            _m = re.match(r"^\s*ACORD[\s_]+(\d{2,3})\b", str(sqs.get("cap_reason") or ""))
            if _m and cap is not None and not fid.startswith(f"ACORD_{_m.group(1)}"):
                bad.append(f"{fid}: held at {cap} by another form's stop: {sqs.get('cap_reason')[:80]}")
            for _b in sqs.get("ready_blockers") or []:
                _m = re.match(r"^\s*ACORD[\s_]+(\d{2,3})\b", str(_b))
                if _m and not fid.startswith(f"ACORD_{_m.group(1)}"):
                    bad.append(f"{fid}: blocked by another form's stop: {str(_b)[:80]}")
            if raw > 85 and cap is None and (warn or block):
                bad.append(f"{fid}: a hold is open but no cap applied")
        # 3. The side panel.
        for r in after["attention"].get(fid) or []:
            f = str(r.get("field") or "")
            if r.get("status") != "missing":
                continue
            tu = (schema.get(f) or {}).get("tu", "") if isinstance(schema.get(f), dict) else ""
            if is_applicant_step(f, tu) and not r.get("applicant_step"):
                bad.append(f"{fid}: applicant signature listed as a producer to-do: {f}")
            # Blank ON PURPOSE: the box's owner withholds a value the facts
            # hold (an owned blank beside a stated fact - page-one premiums,
            # the expiring term on a renewal, another line's number). An owned
            # blank with no fact behind it is a real gap and may be listed.
            fk = box_fact_key(f)
            if fk and str(_fv(facts, fk) or "").strip() and r.get("reason") != "UNANSWERED":
                # (A table row's own empty cell is not "on purpose": the row
                # simply states nothing - `_resolve_schedule_row` is left out.)
                prev = getattr(P._SCHEMA_CTX, "schema", None)
                P._set_schema_context(schema)
                try:
                    owned_blank = P._owned_blank_claim(f, {**facts, "_form_id": fid})
                except Exception:                              # noqa: BLE001
                    owned_blank = False
                finally:
                    P._set_schema_context(prev)
                if owned_blank:
                    bad.append(f"{fid}: a box our rules leave blank listed as Missing: {f} ({fk})")
            if unused_trailing_row(f, mapped, fid):
                bad.append(f"{fid}: a box of an unused row listed as Missing: {f}")
        # 4. The boxes.
        for box, val in mapped.items():
            if isinstance(val, (list, dict)):
                bad.append(f"{fid}:{box} holds a {type(val).__name__}")
                continue
            t = str(val if val is not None else "").strip()
            if val is None or not t:
                continue
            if t.lower() in ("none", "nan", "null"):
                bad.append(f"{fid}:{box} holds {t!r}")
            if _VIN_BOX_RE.search(box):
                v = re.sub(r"[^A-Z0-9]", "", t.upper())
                if len(v) in (16, 18) and not re.search(r"\bVIN\b|vin", stop_text):
                    bad.append(f"{fid}:{box} VIN {t!r} of {len(v)} characters with no warning")

    # 5. Prior grid + ACORD 101: every prior policy in the window placed once.
    grid, years = P._prior_coverage_grid_build(copy.deepcopy(facts))
    placed = [_alnum(e.get("policy_no")) for e in grid.values() if isinstance(e, dict)]
    aside = [_alnum(r.get("policy_no")) for r in P.prior_grid_set_aside_rows(facts)]
    for p in case["truth"].get("prior") or []:
        pn = _alnum(p["policy_no"])
        y = str(_date_key(p["effective"])[0]) if p.get("effective") else None
        if years and y and y not in years:
            continue
        n = placed.count(pn) + aside.count(pn)
        if n != 1 and (y is not None or not years):
            bad.append(f"after forms: prior policy {p['policy_no']} placed {n} times")

    # 6. The post-form plan adds up to 100 - score.
    pp = after.get("plan_pkg") or {}
    if pp.get("_error"):
        bad.append(f"post-form plan failed: {pp['_error']}")
    else:
        score = pp.get("package_sqs_score")
        plan = pp.get("review_plan") or {}
        if isinstance(score, (int, float)) and score < 100 and plan:
            items = [i for i in (plan.get("items") or []) if isinstance(i, dict)]
            pts = sum(int(i.get("points") or 0) for i in items if not i.get("mirror_of"))
            if score + pts + int(plan.get("left") or 0) != 100:
                bad.append(f"post-form plan: score {score} + points {pts} + left {plan.get('left')} != 100")
            for r in plan.get("contract_repaired") or []:
                bad.append(f"post-form plan repaired: {r}")
    return bad


def fill_holding_boxes(after: dict, fid: str) -> Optional[Tuple[int, int]]:
    """Fill exactly the boxes that hold `fid` (its download blockers and the
    required Missing boxes `_form_open_warning` reads) and re-score it:
    (new score, new raw score, new cap). None when nothing holds it by a box
    (a fact-level stop, a gate or a cross-form check - a box cannot clear
    those)."""
    from services import sqs_service as S
    from services.needs_attention import needs_attention, unused_trailing_row
    from services.signature_boxes import is_applicant_step
    from services.field_qa import _gate_still_blocks
    row = after["row"]
    g = row["generated_forms"][fid]
    mapped, conf, schema = g["mapped"], g.get("confidence") or {}, g.get("schema") or {}
    facts, flags, cf = row["facts"], row["flags"], row.get("cross_form_issues") or []
    from services.form_instances import base_form_id
    sq = g.get("sqs") or {}
    box_holds = {S._form_download_blocker(fid, mapped, conf),
                 S._form_open_warning(fid, mapped, conf, schema, facts, flags, cf)} - {None}
    if [b for b in (sq.get("ready_blockers") or []) if b not in box_holds] or (
            sq.get("cap_reason") and sq.get("cap_reason") not in box_holds):
        return None                           # held by a fact-level stop or gate, not a box
    if any(isinstance(i, dict) and str(i.get("type") or "") != "advisory"
           and base_form_id(fid) in {base_form_id(str(f)) for f in (i.get("forms") or [])} for i in cf):
        return None
    holds: List[str] = []
    for field, lab in conf.items():
        lab = lab.get("label") if isinstance(lab, dict) else lab
        if lab == "missing_required_gate" and _gate_still_blocks(fid, field) \
                and str(mapped.get(field) or "").strip() in ("", "None", "null"):
            holds.append(field)
    if S._form_open_warning(fid, mapped, conf, schema, facts, flags, cf):
        for r in needs_attention(g, facts, fid, flags=flags) or []:
            f = str(r.get("field") or "")
            if r.get("status") == "missing" and r.get("required") \
                    and not is_applicant_step(f, (schema.get(f) or {}).get("tu", "") if isinstance(schema.get(f), dict) else "") \
                    and not unused_trailing_row(f, mapped, fid):
                holds.append(f)
    if not holds:
        return None
    for f in holds:
        ft = (schema.get(f) or {}).get("ft") if isinstance(schema.get(f), dict) else None
        v = "1" if ft == "/Btn" else "X1"
        g["mapped"][f] = g["field_state"][f] = v
        conf[f] = {"label": "producer"} if isinstance(conf.get(f), dict) else "producer"
    _rescore_forms(row, after["form_ids"])
    return (g["sqs"].get("sqs_score"), g["sqs"].get("raw_sqs_score"), g["sqs"].get("cap_applied"))


def _score_form_alone(row: dict, fid: str) -> dict:
    """ONE form scored with no package stop and no cross-form check - only
    what its own boxes hold it by (download blocker / required box)."""
    from services import sqs_service as S
    g = row["generated_forms"][fid]
    return S.calculate_sqs(
        facts=row["facts"], flags=row["flags"], mapped_data=g["mapped"], form_schema=g["schema"],
        selected_form_ids=list(row["generated_forms"]), hard_stops=[], soft_stops=[],
        tier2_score=50, form_id=fid, confidence_dict=g.get("confidence") or {},
        session_id="shape", user_id="user-shape", calculation_stage="arq_remediated",
        cross_issues_full=[])


def box_holds_reach_raw(after: dict, fid: str) -> Optional[str]:
    """The box half of the per-form rule, isolated from the package's stops:
    a form held by its own boxes, once exactly those boxes are filled, scores
    its raw score with no cap. A problem sentence, or None."""
    from services import sqs_service as S
    from services.needs_attention import needs_attention, unused_trailing_row
    from services.signature_boxes import is_applicant_step
    from services.field_qa import _gate_still_blocks
    row = copy.deepcopy(after["row"])
    g = row["generated_forms"][fid]
    before = _score_form_alone(row, fid)
    mapped, conf, schema = g["mapped"], g.get("confidence") or {}, g.get("schema") or {}
    block = S._form_download_blocker(fid, mapped, conf)
    warn = S._form_open_warning(fid, mapped, conf, schema, row["facts"], row["flags"], [])
    if before.get("cap_applied") is not None and before.get("cap_reason") not in (block, warn) \
            and before.get("cap_reason") not in ("Minimum Viable COPE incomplete",) \
            and not str(before.get("cap_reason") or "").startswith("Umbrella"):
        return f"{fid}: held alone by {before.get('cap_reason')!r}, not by a box"
    if not (block or warn):
        if before.get("cap_applied") is None and before.get("sqs_score") != before.get("raw_sqs_score"):
            return f"{fid}: no hold but {before.get('sqs_score')} != raw {before.get('raw_sqs_score')}"
        return None
    if before.get("cap_reason") not in (block, warn):
        return None                              # a gate also holds it - not the boxes' to clear
    holds = [f for f, lab in conf.items()
             if (lab.get("label") if isinstance(lab, dict) else lab) == "missing_required_gate"
             and _gate_still_blocks(fid, f) and str(mapped.get(f) or "").strip() in ("", "None", "null")]
    for r in needs_attention(g, row["facts"], fid, flags=row["flags"]) or []:
        f = str(r.get("field") or "")
        tu = (schema.get(f) or {}).get("tu", "") if isinstance(schema.get(f), dict) else ""
        if r.get("status") == "missing" and r.get("required") and not is_applicant_step(f, tu) \
                and not unused_trailing_row(f, mapped, fid):
            holds.append(f)
    for f in holds:
        ft = (schema.get(f) or {}).get("ft") if isinstance(schema.get(f), dict) else None
        g["mapped"][f] = g["field_state"][f] = "1" if ft == "/Btn" else "X1"
        conf[f] = "producer"
    after_fill = _score_form_alone(row, fid)
    if after_fill.get("cap_applied") is not None or after_fill.get("sqs_score") != after_fill.get("raw_sqs_score"):
        return (f"{fid}: filled {len(holds)} holding box(es) but still {after_fill.get('sqs_score')} "
                f"(raw {after_fill.get('raw_sqs_score')}, cap {after_fill.get('cap_applied')}: "
                f"{str(after_fill.get('cap_reason'))[:90]})")
    return None
