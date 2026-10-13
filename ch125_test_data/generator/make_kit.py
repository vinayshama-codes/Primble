"""
make_kit.py - build the CH125 kit: one PDF of EXACTLY 300,000 characters, and an
answer key for ACORD 125 / 126 / 127.

    backend/.venv/bin/python ch125_test_data/generator/make_kit.py

THE CHARACTER COUNT. "Characters" means the PDF's text layer as pdfplumber reads it:
    sum(len(page.extract_text()) for page in pdf.pages)
- the standard, tool-agnostic measure. There are no scanned images, so the text
layer IS the whole document. The build calibrates the closing policy wording until
that sum is exactly 300,000, then verifies it.

THE KIT IS PROVED FAIR before it is written:
  * every expected value is printed (dates and amounts may be printed in another
    format - 19840611, 06-Apr-2015, $15.2 million in $000s - but are printed);
  * every decoy is printed - a trap that is not in the document tests nothing;
  * the key scores a perfect form 100% and an EMPTY form with zero violations,
    on all three forms, through backend/scripts/score_form_fill.py itself.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent
ROOT = KIT.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(BACKEND))

import kit_data as D            # noqa: E402
import kit_docs as DOCS         # noqa: E402
import kit_key as K             # noqa: E402
from kit_engine import Flow, render   # noqa: E402

PDF = KIT / "CH125_cumberland_hearth_package.pdf"
KEY = KIT / "CH125_answer_key.json"
TARGET = 300_000
FOOTER = "CHHS submission package - Riverbend Insurance Partners - assembled 10/02/2026 - confidential"


# ════════════════════════════════════════════════════════════════════════════
def doc_order():
    import kit_docs_bulk as B
    import kit_docs_extra as X
    import kit_docs_more as M
    a, m, b, x = DOCS, M, B, X
    return [a.agency_email, a.mga_acknowledgement, b.program_guidelines, b.checklist,
            b.ach_authorization, x.program_application, m.uw_questions, a.intake_worksheet, a.cfo_thread,
            m.facilities_thread, m.accounting_thread, x.cfo_name_change, a.questionnaire_125, a.premises_schedule,
            a.hr_census, lambda f: m.payroll_register(f, a.roster()), a.financials,
            m.financial_statements, b.ar_aging, x.top_customers, x.bank_reference, a.corporate, m.board_minutes, a.ams_export,
            a.gl_supplemental, a.products, b.customs_entry, x.import_log, x.warranty_log, m.catalogue, m.supplier_list,
            a.subcontractors, m.installation_agreement, a.loaner_log, m.service_tickets,
            b.pm_contracts, a.safety_program, m.safety_manual, x.safety_minutes, x.incident_log,
            lambda f: b.training_records(f, a.roster()), a.fire_and_roof, b.inspections,
            m.loss_control_survey, a.notices, a.leases_and_loan, b.sublease,
            m.lease_insurance_clause, m.appraisal, a.gl_declarations, x.premium_audit, m.prior_gl_schedule,
            b.endorsements_text, b.renewal_offer, m.certificates, a.auto_declarations,
            b.registrations, a.auto_supplemental, b.vehicle_policy, a.drivers, x.driver_qualification, m.mvr_json,
            a.telematics, m.trip_log, b.trip_log_august, lambda f: b.trip_log_august(f, "07", "JULY", 777), b.fuel_cards, lambda f: b.fuel_cards(f, "07", "JULY", 779), m.maintenance_records,
            a.property_dec, b.inventory, a.umbrella_dec, x.wc_dec, a.loss_runs, m.claim_ledgers,
            a.old_application, m.old_application_full, a.jv_and_events, a.job_list,
            a.cert_holders]


def build_pages(wording_chars: int, tail: int = 0):
    f = Flow(FOOTER)
    for doc in doc_order():
        doc(f)
    DOCS.policy_wording(f, wording_chars, tail)
    return f.pages


def page_texts(path=PDF):
    import pdfplumber
    with pdfplumber.open(str(path)) as pdf:
        return [(p.extract_text() or "") for p in pdf.pages]


def measure():
    return sum(len(t) for t in page_texts())


def calibrate():
    """Coarse: size the wording. Fine: size the one closing line (1 char = 1 char)."""
    n, tail = 54_400, 60
    for it in range(12):
        pages = build_pages(n, tail)
        render(str(PDF), pages, FOOTER, f"{D.NAME} - submission package")
        total = measure()
        print(f"  coarse #{it}: wording {n:,} + tail {tail} -> {total:,} characters ({len(pages)} pages)")
        delta = TARGET - total
        if total == TARGET:
            return pages, total
        if -tail + 20 <= delta <= 120 - tail:
            break
        n += delta
    for it in range(12):
        tail += delta
        pages = build_pages(n, tail)
        render(str(PDF), pages, FOOTER, f"{D.NAME} - submission package")
        total = measure()
        print(f"  fine #{it}: wording {n:,} + tail {tail} -> {total:,} characters")
        if total == TARGET:
            return pages, total
        delta = TARGET - total
    raise SystemExit("could not hit the exact character count")


# ════════════════════════════════════════════════════════════════════════════
def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


_MON = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_MONTH = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
          "october", "november", "december"]


def _variants(value: str):
    """Every printing of one value the documents may use."""
    v = str(value).strip()
    out = {_norm(v)}
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", v)
    if m:
        mm, dd, yy = m.groups()
        mi = int(mm) - 1
        out |= {f"{yy}{mm}{dd}", _norm(f"{yy}-{mm}-{dd}"), _norm(f"{dd}-{_MON[mi]}-{yy}"),
                _norm(f"{_MONTH[mi]} {int(dd)}, {yy}"), _norm(f"{_MON[mi]} {int(dd)}, {yy}")}
    m = re.fullmatch(r"\$([\d,]+)", v)
    if m:
        n = int(m.group(1).replace(",", ""))
        out.add(_norm(m.group(1)))
        if n % 1000 == 0 and n >= 100_000:
            out.add(_norm(f"{n // 1000:,}"))                 # in $000s
        if n % 100_000 == 0 and n >= 1_000_000:
            out.add(_norm(f"{n / 1_000_000:g} million"))
    m = re.fullmatch(r"(\d+)%", v)
    if m:
        out.add(_norm(m.group(1) + "%"))
    if v.upper() in ("TN", "KY", "NC"):
        out.add({"TN": "tennessee", "KY": "kentucky", "NC": "northcarolina"}[v.upper()])
    return {x for x in out if x}


def verify(texts) -> dict:
    hay = _norm("\n".join(texts))
    words = set(re.findall(r"[a-z0-9]{3,}", "\n".join(texts).lower()))
    problems = []
    for form in K.FORMS:
        for fld, meta in K.FIELDS[form].items():
            if meta["verdict"] != K.EXPECT:
                continue
            val = meta["value"]
            if meta["source"] in ("template", "derived") or val in ("Y", "N"):
                continue
            if fld.endswith(("ProducerIdentifier_A", "ProducerIdentifier_B", "ProducerIdentifier_C",
                             "ProducerIdentifier_D")) and str(val).isdigit() and len(str(val)) == 1:
                continue                       # a location / vehicle / driver NUMBER
            if fld.startswith("PriorCoverage_PolicyYear_"):
                continue                       # printed inside "2025-26"
            if meta["match"] == "semantic":
                lost = [w for w in re.findall(r"[a-z0-9]{3,}", str(val).lower()) if w not in words]
                if lost:
                    problems.append(f"NOT IN DOCUMENT {form}.{fld}: lost words {lost[:6]}")
                continue
            if not any(v in hay for v in _variants(val)):
                problems.append(f"NOT IN DOCUMENT {form}.{fld} = {val!r}")
    for form in K.FORMS:
        for value, scope, _why in K.decoys_for(form):
            if _norm(value) not in hay:
                problems.append(f"DECOY NOT PRINTED {form}: {value!r} ({scope})")
    # the unresolved questions must NOT be answered anywhere as a clean statement
    for probe in ("question 7 is no", "question 9 is no", "q7 n", "q9 n"):
        if _norm(probe) in hay:
            problems.append(f"an UNRESOLVED question is answered in the text: {probe}")
    problems += self_consistency()
    return problems


def self_consistency(key=None):
    spec = importlib.util.spec_from_file_location("_sff", str(BACKEND / "scripts" / "score_form_fill.py"))
    sff = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sff)
    key = key or json.loads(KEY.read_text(encoding="utf-8"))
    out = []
    for form in K.FORMS:
        perfect = dict(key["expect"][form])
        res = sff.score_form(form, key, perfect, lambda f: None)
        for kind in ("wrong", "blank_violation", "forbidden", "shape", "overflow_leak"):
            for row in res["details"].get(kind, [])[:6]:
                out.append(f"SELF-CONSISTENCY {form} ({kind}): {row}")
        if res["tally"].get("correct") != len(perfect):
            out.append(f"SELF-CONSISTENCY {form}: {res['tally'].get('correct')} of {len(perfect)}")
        for g in sff.score_rows(form, key, perfect):
            if g.get("cross_row") or g.get("cells_correct") != g.get("cells_expected"):
                out.append(f"SELF-CONSISTENCY {form} (row-cell): {g}")
        res0 = sff.score_form(form, key, {}, lambda f: None)
        for kind in ("blank_violation", "forbidden", "shape", "overflow_leak", "wrong"):
            if res0["tally"].get(kind):
                out.append(f"SELF-CONSISTENCY {form}: an EMPTY form reports {res0['tally'][kind]} {kind}")
    return out


# ════════════════════════════════════════════════════════════════════════════
_TOPIC = {"AAI": "subsidiary_of_another", "AAJ": "has_subsidiaries", "KAA": "formal_safety_program",
          "ABC": "flammables_explosives_chemicals", "AAH": "other_insurance_with_carrier",
          "AAC": "coverage_declined_cancelled_nonrenewed", "AAD": "abuse_molestation_discrimination_claims",
          "KAB": "fraud_arson_conviction", "AAF": "uncorrected_fire_safety_violations",
          "KAK": "foreclosure_repossession_bankruptcy", "KAL": "judgement_or_lien",
          "ABB": "business_in_trust", "KAC": "foreign_operations", "KAM": "other_business_ventures",
          "KAN": "owns_leases_operates_drones", "KAO": "hires_drone_operators"}


def expected_facts() -> dict:
    """What LLM call 1 should extract - graded by score_a125_extraction.py (ENTITY-CELL)."""
    return {
        "_scalars": {
            "applicant_name": D.NAME, "fein": D.FEIN, "sic_code": D.SIC, "naics_code": D.NAICS,
            "entity_type": D.ENTITY, "business_start_date": D.START_DATE,
            "effective_date": D.PROPOSED_EFF, "expiration_date": D.PROPOSED_EXP,
            "operations_description": D.PRIMARY_OPERATIONS,
            "other_named_insured_operations": D.OTHER_INSURED_OPERATIONS,
            "applicant_business_phone": D.BUS_PHONE, "applicant_website": D.WEBSITE,
            "applicant_gl_class_code": D.GL_CODE,
            "sales_installation_repair_percent": D.INSTALL_PCT,
            "sales_installation_repair_off_premises_percent": D.INSTALL_OFF_PCT,
            "audit_period": D.AUDIT_WORD,
        },
        "_lists": {
            "applicant_contacts": {
                "expected": [{"name": c["name"], "contact_type": c["type"], "phone": c["phone"],
                              "email": c["email"]} for c in D.CONTACTS],
                "key": "name", "columns": ["contact_type", "phone", "email"]},
            "property_locations": {
                "expected": [{"address": l["l1"], "county": l["county"], "full_time_employees": l["ft"],
                              "part_time_employees": l["pt"], "annual_revenue": l["revenue"],
                              "occupied_area": l["occupied"], "open_to_public_area": l["public"],
                              "total_building_area": l["total_area"]} for l in D.LOCATIONS],
                "key": "address",
                "columns": ["county", "full_time_employees", "part_time_employees", "annual_revenue",
                            "occupied_area", "open_to_public_area", "total_building_area"]},
            "named_insured_details": {
                "expected": [{"name": D.SUB["name"], "fein": D.SUB["fein"], "sic": D.SUB["sic"],
                              "naics": D.SUB["naics"], "phone": D.SUB["phone"], "website": D.SUB["web"]}],
                "key": "name", "columns": ["fein", "sic", "naics", "phone", "website"]},
            "organization_relationships": {
                "expected": [{"name": D.SUB["name"], "role": "subsidiary", "percent_owned": D.SUB["pct"]}],
                "key": "name", "columns": ["role", "percent_owned"]},
            "disclosure_answers": {
                "expected": [{"topic": _TOPIC[c], "answer": q["answer"]}
                             for c, q in D.Q125.items() if q["answer"]],
                "key": "topic", "columns": ["answer"]},
            "safety_program_elements": {
                "expected": [{"element": e} for e in ("Safety Manual", "Safety Position", "OSHA")],
                "key": "element", "columns": []},
            "loss_history": {
                "expected": [{"claim_number": x["claim_no"], "date": x["occurrence"], "paid": x["paid"],
                              "reserved_amount": x["reserved"], "open_code": "O" if x["open"] == "Y" else "C"}
                             for x in D.LOSSES],
                "key": "claim_number", "columns": ["date", "paid", "reserved_amount", "open_code"]},
            "additional_interests": {
                "expected": [{"name": D.MORTGAGEE["name"], "interest_type": "Mortgagee",
                              "lien_amount": D.MORTGAGEE["amount"], "reference_number": D.MORTGAGEE["loan_no"],
                              "phone": D.MORTGAGEE["phone"], "email": D.MORTGAGEE["email"]}],
                "key": "name",
                "columns": ["interest_type", "lien_amount", "reference_number", "phone", "email"]},
        },
        "_must_be_empty": [],
    }


# ════════════════════════════════════════════════════════════════════════════
def where_printed(texts, value):
    """Pages that print the value. A short value (a count, a code) is matched as a whole
    word, so '41' is not found inside '4471902'."""
    v = str(value).strip()
    if len(_norm(v)) <= 3:
        return []                      # a 1-3 character value is everywhere - see the source note
    if len(_norm(v)) <= 5:
        rx = re.compile(r"(?<![\w$.,/-])" + re.escape(v) + r"(?![\w.,/-]\w)")
        return [i + 1 for i, t in enumerate(texts) if rx.search(t)]
    vs = _variants(value)
    return [i + 1 for i, t in enumerate(texts) if any(x in _norm(t) for x in vs)]


def main() -> int:
    KIT.mkdir(exist_ok=True)
    print("1. building the answer key (every box on 125 / 126 / 127)")
    K.build_all()
    if "--key-only" in sys.argv:
        print("2. key only - reading the PDF already built")
        texts = page_texts()
        total = sum(len(t) for t in texts)
        if total != TARGET:
            raise SystemExit(f"the PDF on disk has {total:,} characters, not {TARGET:,} - run a full build")
    else:
        print("2. rendering and calibrating to exactly 300,000 characters")
        _pages, total = calibrate()
        texts = page_texts()
    meta = {"kit": "CH125 - Cumberland Hearth & Hospitality Supply (new business, through an MGA)",
            "account": D.NAME, "document": PDF.name,
            "built_by": "ch125_test_data/generator/make_kit.py",
            "answers_from": "the client's rules (125_reference, 8-19-26) applied to documents built "
                            "for this kit",
            "characters": total, "pages": len(texts),
            "character_measure": "sum(len(page.extract_text()) for page in pdfplumber pages)",
            "built": datetime.now().strftime("%Y-%m-%d %H:%M")}
    key = K.assemble(meta)
    key["expected_facts"] = expected_facts()
    for form in K.FORMS:
        for fld, v in K.FIELDS[form].items():
            if v["verdict"] == K.EXPECT and v["value"] not in ("Y", "N") and v["source"] == "text":
                v["pages"] = where_printed(texts, v["value"])[:6]
    KEY.write_text(json.dumps(key, indent=1), encoding="utf-8")
    print("3. verifying the kit is fair and the key is consistent")
    problems = verify(texts)
    if problems:
        for p in problems:
            print("  FAIL:", p)
        raise SystemExit(f"verification failed: {len(problems)} problem(s)")
    thin = [(i + 1, len(t)) for i, t in enumerate(texts[:-1]) if len(t) < 2000]
    print(f"  OK - {total:,} characters, {len(texts)} pages, thin pages {thin}")
    for form in K.FORMS:
        print(f"  {form}: {key['_meta']['verdict_counts'][form]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
