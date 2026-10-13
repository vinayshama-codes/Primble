"""
kit_docs_bulk.py - the third layer of the CH125 package: operating records that a
real submission file accumulates (registrations, renewal offer, program guidelines,
AR aging, inventory, fuel, training, inspections, endorsements). Every value agrees
with kit_data, or is dated / labelled as belonging to something else.
"""
from __future__ import annotations

import random

import kit_data as D
from kit_engine import Flow, LEFT, MONO, SANS, SANS_B, SERIF, SERIF_I

L1, L2, L3 = D.LOCATIONS
PKG_HDR = "RIVERBEND INSURANCE PARTNERS - SUBMISSION FILE CHHS-2026-NB - DOCUMENTS AS RECEIVED"
OHM_HDR = f"{D.OHM.upper()}  |  Policyholder service {D.OHM_PHONE}  |  {D.OHM_WEB}"
ARU_HDR = f"{D.MGA}  |  administrator for {D.CARRIER}"


def renewal_offer(f: Flow):
    """The incumbent's renewal QUOTE - decoys for the carrier, status and premium boxes."""
    f.doc("OLD HICKORY MUTUAL - RENEWAL QUOTATION (NOT ACCEPTED BY THE INSURED)", OHM_HDR)
    f.kv([("Date", "09/04/2026"), ("Renewal of", "OHM-GL-4471902-25 and OHM-CA-4471903-25"),
          ("Proposed renewal term", "12/01/2026 to 12/01/2027"),
          ("Agent", f"{D.PRIOR_AGENCY} (agent of record until 07/15/2026)")],
         font=MONO, size=6.8, label_w=150)
    f.table(["LINE", "RENEWAL PREMIUM", "EXPIRING", "CHANGE"],
            [["General liability", "$40,880", "$38,420", "+6.4%"],
             ["Business auto", "$66,210", "$61,775", "+7.2%"],
             ["Total", "$107,090", "$100,195", "+6.9%"]], [LEFT, 200, 300, 400], size=6.6)
    f.para("Billing: agency bill, 10 installments. Terms subject to a satisfactory loss control "
           "visit. This renewal quotation expires 11/15/2026. The insured has instructed its new "
           "agent to market the account; this quotation has not been accepted.", MONO, 6.6)


def program_guidelines(f: Flow):
    f.doc("HOSPITALITY TRADES PACKAGE PROGRAM - UNDERWRITING GUIDELINES (excerpt, rev. 2026)",
          ARU_HDR)
    f.paras([
        "1. Eligible classes: distributors of commercial kitchen and foodservice equipment; "
        "installation and service of commercial kitchen equipment; restaurant equipment dealers.",
        "2. Ineligible: manufacturers; gas-piping or fire-suppression contractors; operations with "
        "liquor sales.",
        "3. Program minimums (for the company's rating - NOT this applicant's premium): minimum "
        "premium per policy $2,500; minimum deposit 25% of the annual premium.",
        "4. Loss history: five years, currently valued. Large losses over $50,000 require narrative.",
        "5. Auto: maximum radius 300 miles; no for-hire hauling; MVRs within 60 days.",
        "6. Products: imported products require the importer's warranty and recall plan.",
        "7. Underwriting authority: submissions are directed to the Knoxville underwriting office.",
    ], font=SERIF, size=7.0)


def ach_authorization(f: Flow):
    f.doc("PREMIUM PAYMENT - ACH DEBIT AUTHORIZATION (signed 09/29/2026)", ARU_HDR)
    f.kv([("Payee", f"{D.CARRIER} c/o {D.MGA}"), ("Payer", D.NAME),
          ("Payment method", "ACH auto-debit from the operating account ending 4417"),
          ("Installments", "Quarterly"), ("Billing", "Direct bill to the insured"),
          ("Effective", "with the first installment of any policy bound")], font=MONO, size=6.8,
         label_w=150)


def registrations(f: Flow):
    f.doc("TENNESSEE CERTIFICATES OF REGISTRATION - COMPANY VEHICLES", "STATE OF TENNESSEE - "
          "DEPARTMENT OF REVENUE - VEHICLE SERVICES")
    plates = ["C-48817", "C-51236", "C-60014", "TRK-7720"]
    for v, plate in zip(D.VEHICLES, plates):
        lien = {"1": "Highline Commercial Truck Credit, LLC", "4": "Volunteer Truck Finance, LLC"}.get(v["num"], "none")
        f.para(f"PLATE {plate} | {v['year']} {v['make'].upper()} {v['model'].upper()} | VIN {v['vin']} | "
               f"GVW {v['gvw']} | OWNER: {D.NAME.upper()} | ADDRESS {D.MAIL_L1}, {D.MAIL_CITY} TN | "
               f"COUNTY OF REGISTRATION {D.LOCATIONS[int(v['loc']) - 1]['county'].upper()} | LIENHOLDER: "
               f"{lien} | EXPIRES 11/30/2027", MONO, 6.3)
    f.para("All four vehicles are titled and registered in Tennessee to the company. No vehicle "
           "is registered to an employee, to the subsidiary or to any other owner.", SANS, 6.6)


def sublease(f: Flow):
    f.doc("SUBLEASE AGREEMENT (excerpt) - 2850 KELLERMAN INDUSTRIAL PKWY, NORTH BAYS", PKG_HDR)
    f.paras([
        f"Sublandlord: {D.NAME}. Subtenant: {D.SUBLEASE_TENANT}. Premises: approximately 6,000 "
        "square feet at the north end of the building at 2850 Kellerman Industrial Pkwy, "
        "Nashville, with a separate entrance. Term: 01/01/2025 - 12/31/2027.",
        "Subtenant shall maintain commercial general liability insurance naming Sublandlord as "
        "additional insured, and shall not permit public access through Sublandlord's showroom.",
    ], font=SERIF, size=7.0)


def vehicle_policy(f: Flow):
    f.doc("EMPLOYEE HANDBOOK - SECTION 14: VEHICLES (rev. 2025)", PKG_HDR)
    f.paras([
        "14.1 Company vehicles may be driven only by employees on the authorized driver roster. "
        "Family members and other non-employees may not drive or ride in company vehicles.",
        "14.2 Personal vehicles. Two outside sales representatives use their own cars for sales "
        "calls and receive a mileage allowance; all other employees use company vehicles or none. "
        "Fewer than 5% of employees use their own autos in the business.",
        "14.3 Every driver is covered by the company's workers compensation insurance.",
        "14.4 Vehicles are not leased, lent or rented to anyone else.",
        "14.5 Drug and alcohol testing: pre-employment and post-accident for all drivers; random "
        "testing for the CDL driver.",
    ], font=SERIF, size=7.0)


def endorsements_text(f: Flow):
    f.doc("EXPIRING POLICY ENDORSEMENTS (Old Hickory Mutual) - SELECTED TEXT", OHM_HDR)
    f.paras([
        "CG 20 10 04 13 ADDITIONAL INSURED - OWNERS, LESSEES OR CONTRACTORS - SCHEDULED PERSON OR "
        "ORGANIZATION. Schedule: any person or organization for whom you are performing operations "
        "when you and such person or organization have agreed in writing in a contract that such "
        "person or organization be added as an additional insured on your policy.",
        "CG 20 11 04 13 ADDITIONAL INSURED - MANAGERS OR LESSORS OF PREMISES. Schedule: Brightline "
        "Flex Properties, LP - 410 Industrial Blvd, Suite C, La Vergne, TN 37086.",
        f"OHM-EBL-01 (01/20) EMPLOYEE BENEFITS LIABILITY. Each employee limit $1,000,000; aggregate "
        f"$3,000,000; deductible $1,000 each employee; retroactive date {D.EBL['retro']}.",
        f"CA 99 10 DRIVE OTHER CAR COVERAGE - BROADENED COVERAGE FOR NAMED INDIVIDUALS. Named "
        f"individual: {D.CEO}. Coverages: liability, medical payments, uninsured motorists.",
        "CA 20 01 LESSOR - ADDITIONAL INSURED AND LOSS PAYEE: not attached.",
        "CA 23 20 TRUCKERS - not applicable; the insured is a private carrier of its own goods.",
    ], font=SERIF, size=6.9)


def customs_entry(f: Flow):
    f.doc("U.S. CUSTOMS ENTRY SUMMARY (CBP 7501) - EXCERPT", PKG_HDR)
    f.kv([("Entry no.", "AB4-0418229-6"), ("Entry date", "04/02/2026"),
          ("Importer of record", f"{D.NAME}"), ("Country of origin", "IT"),
          ("Manufacturer", "Forni Lombardi S.r.l., Bergamo"),
          ("Description", "Gas-fired deck ovens for commercial bakeries and restaurants (6)"),
          ("HTS", "8419.81.5080"), ("Entered value", "USD 52,630")], font=MONO, size=6.8, label_w=150)


def ar_aging(f: Flow):
    f.doc("ACCOUNTS RECEIVABLE AGING - 08/31/2026 (customers)", PKG_HDR)
    rnd = random.Random(626)
    sites = D.job_sites()
    rows = []
    for i in range(220):
        s = sites[i % len(sites)]
        branch = "" if i < len(sites) else f" - unit {i // len(sites) + 1}"
        cur = rnd.randint(0, 48000)
        rows.append([f"C{3000 + i * 11}", (s["customer"] + branch)[:34], f"{s['city']}, {s['state']}",
                     f"${cur:,}", f"${rnd.randint(0, 9000):,}", f"${rnd.randint(0, 4000):,}",
                     f"${rnd.choice([0, 0, 0, rnd.randint(100, 2500)]):,}"])
    f.table(["CUST #", "CUSTOMER", "CITY", "CURRENT", "31-60", "61-90", "90+"], rows,
            [LEFT, 80, 250, 360, 420, 470, 520], size=6.0)
    f.para("Two Rivers Catering Co. - judgment receivable $22,480 (in collection; owed TO the "
           "company). Riverside Bistro Group - written off FY2024 (customer's Chapter 11).", SANS, 6.5)


def inventory(f: Flow):
    f.doc("INVENTORY BY LOCATION - 08/31/2026 (perpetual system)", PKG_HDR)
    rnd = random.Random(737)
    cats = ["Deck ovens", "Convection ovens", "Combi ovens", "Espresso machines", "Refrigeration",
            "Ice machines", "Fryers", "Ranges", "Dishwashers", "Smallwares", "Gas valves", "Compressors",
            "Controls / boards", "Gaskets", "Stainless tables", "Hoods", "Cleaners - private label",
            "Filters", "Burners", "Thermostats"]
    rows = []
    for loc, code in (("KEL", 1), ("LAV", 2), ("FRK", 3)):
        for c in cats:
            if code == 3 and c in ("Deck ovens", "Convection ovens", "Refrigeration", "Hoods",
                                   "Stainless tables", "Dishwashers"):
                continue
            n = rnd.randint(2, 180) if code != 3 else rnd.randint(1, 30)
            rows.append([loc, f"{loc}-{rnd.randint(1, 40):02d}-{rnd.randint(1, 9)}", c, f"{n}",
                         f"${rnd.randint(40, 9000) * n:,}"])
    f.table(["LOC", "BIN", "CATEGORY", "UNITS", "EXT. COST"], rows, [LEFT, 80, 160, 330, 390], size=6.0)
    f.para("KEL = location 1, LAV = location 2, FRK = location 3. Inventory at cost; not a "
           "statement of insurable values.", SANS, 6.5)


def fuel_cards(f: Flow, month: str = "08", name: str = "AUGUST", seed: int = 848):
    f.doc(f"FUEL CARD TRANSACTIONS - {name} 2026", PKG_HDR)
    rnd = random.Random(seed)
    drivers = {"1": "BELLWEATHER M", "2": "FONTENOT A", "3": "HOLLIS D", "4": "DANDEKAR P"}
    stations = ["Pilot #412 Nashville", "Mapco #3318 La Vergne", "Shell Franklin", "Love's #219 Smyrna",
                "Kroger Fuel Brentwood", "Marathon Bowling Green KY", "Exxon Huntsville AL"]
    rows = []
    for day in range(1, 32):
        for v in ("1", "2", "3", "4"):
            if rnd.random() < 0.55:
                continue
            drv = drivers[v] if not (v == "2" and rnd.random() < 0.3) else "O'ROURKE T"
            gal = rnd.randint(9, 61) if v in ("1", "4") else rnd.randint(8, 22)
            rows.append([f"{month}/{day:02d}/26", f"VEH {v}", drv, stations[rnd.randrange(len(stations))],
                         f"{gal}.{rnd.randint(0, 9)}", f"${gal * rnd.randint(330, 389) / 100:,.2f}",
                         "DSL" if v in ("1", "4") else "UNL"])
    f.table(["DATE", "UNIT", "DRIVER", "STATION", "GAL", "AMOUNT", "FUEL"], rows,
            [LEFT, 80, 120, 200, 370, 410, 470], size=6.0)


def training_records(f: Flow, roster_rows):
    f.doc("TRAINING RECORDS - OSHA 10, FORKLIFT, EPA 608, DEFENSIVE DRIVING", PKG_HDR)
    rnd = random.Random(959)
    rows = []
    for r in roster_rows:
        if r[3] != "F/T":
            continue
        dept = r[4]
        osha = f"{rnd.randint(1, 12):02d}/{rnd.randint(2016, 2025)}"
        fork = f"{rnd.randint(1, 12):02d}/2026" if dept in ("Warehouse", "Depot", "Delivery", "Purchasing") else "--"
        epa = "Type II" if "Tech" in dept else "--"
        dd = f"{rnd.randint(1, 12):02d}/2025" if dept in ("Delivery", "Depot", "Service Tech") else "--"
        rows.append([r[0], r[1], r[2], dept, osha, fork, epa, dd])
    f.table(["EMP #", "NAME", "LOC", "DEPT", "OSHA 10", "FORKLIFT", "EPA 608", "DEF. DRIVING"], rows,
            [LEFT, 90, 220, 260, 330, 390, 450, 500], size=6.0)


def inspections(f: Flow):
    f.doc("FIRE PROTECTION INSPECTIONS - 2026", PKG_HDR)
    f.table(["DATE", "LOCATION", "SYSTEM", "RESULT", "VENDOR"],
            [["01/14/2026", "Loc 1 Kellerman", "Wet sprinkler - annual", "Pass", "Cumberland Fire Protection"],
             ["01/14/2026", "Loc 1 Kellerman", "Test kitchen hood suppression", "Pass", "Cumberland Fire Protection"],
             ["03/02/2026", "Loc 1 Kellerman", "Extinguishers - re-tag (fire marshal follow-up)", "Pass",
              "Cumberland Fire Protection"],
             ["04/09/2026", "Loc 2 La Vergne", "Wet sprinkler - landlord's annual", "Pass", "Landlord's vendor"],
             ["05/20/2026", "Loc 3 Franklin", "Building systems - landlord", "Pass", "Landlord's vendor"],
             ["07/14/2026", "Loc 1 Kellerman", "Hood suppression - semi-annual", "Pass",
              "Cumberland Fire Protection"]], [LEFT, 90, 190, 380, 430], size=6.2)


def pm_contracts(f: Flow):
    f.doc("PREVENTIVE MAINTENANCE CONTRACT CUSTOMERS (Service Co.)", PKG_HDR)
    rnd = random.Random(1061)
    rows = []
    for i, s in enumerate(D.job_sites()):
        rows.append([f"PM-{500 + i * 7}", s["customer"], f"{s['addr']}, {s['city']} {s['state']}",
                     rnd.choice(["quarterly", "semi-annual", "monthly"]), f"${rnd.randint(18, 160) * 100:,}/yr",
                     rnd.choice(["2026-12", "2027-03", "2027-06", "2027-09"])])
    f.table(["CONTRACT", "CUSTOMER", "SITE", "VISITS", "FEE", "RENEWS"], rows,
            [LEFT, 82, 210, 400, 460, 520], size=6.0)


def trip_log_august(f: Flow, month: str = "08", name: str = "AUGUST", seed: int = 1313):
    f.doc(f"FLEETPULSE - TRIP LOG EXPORT (fixed width) - {name} 2026", PKG_HDR)
    rnd = random.Random(seed)
    f.line("DATE       VEH DRV START    END      MI   IDLE  HARSH  SPEED>10  SCORE", MONO, 6.0)
    for day in range(1, 32):
        for v in ("1", "2", "3", "4"):
            if rnd.random() < 0.3:
                continue
            d = {"1": "1", "2": "2", "3": "3", "4": "4"}[v]
            if v == "2" and rnd.random() < 0.3:
                d = "6"
            f.line(f"{month}/{day:02d}/2026 {v:>3} {d:>3} {rnd.randint(6, 10):02d}:{rnd.randint(0, 59):02d}    "
                   f"{rnd.randint(12, 17):02d}:{rnd.randint(0, 59):02d}    {rnd.randint(8, 210):>4} "
                   f"{rnd.randint(2, 70):>5} {rnd.randint(0, 3):>6} {rnd.randint(0, 2):>9} {rnd.randint(74, 99):>6}",
                   MONO, 6.0)


def checklist(f: Flow):
    f.doc("ARU SUBMISSION CHECKLIST (completed by the agency)", ARU_HDR)
    items = [("ACORD 125, 126, 127 (to be generated and signed)", True),
             ("General information supplement - signed", True),
             ("GL supplemental - signed", True), ("Auto supplemental - signed", True),
             ("Loss runs - 5 years, currently valued", True), ("MVRs within 60 days", True),
             ("Statement of values", True), ("Roof replacement confirmation", True),
             ("Questions 7 and 9 answered", False), ("Fleet question answered", False),
             ("Applicant signature on ACORD forms", False)]
    for t, done in items:
        f.line(f"{'[X]' if done else '[ ]'} {t}", MONO, 6.8)


BULK = ["renewal_offer", "program_guidelines", "ach_authorization", "checklist", "registrations",
        "sublease", "vehicle_policy", "endorsements_text", "customs_entry", "ar_aging", "inventory",
        "fuel_cards", "training_records", "inspections", "pm_contracts", "trip_log_august"]
