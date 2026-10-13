"""
kit_docs_more.py - the bulk of the CH125 package: the documents a real submission
carries around the few that answer the application - surveys, financials, payroll,
catalogues, tickets, telematics, certificates, minutes, an old application.

They are NOT filler. Each one restates some truth in another format (and must agree
with it), and many carry a dated or wrong-role value that must not reach the form.
Nothing here contradicts the key without saying so on the page (a date, a
'superseded', 'deleted', 'sold', 'terminated', 'customer', 'holder').
"""
from __future__ import annotations

import json
import random

import kit_data as D
from kit_engine import Flow, LEFT, MONO, MONO_B, SANS, SANS_B, SERIF, SERIF_I

L1, L2, L3 = D.LOCATIONS
PKG_HDR = "RIVERBEND INSURANCE PARTNERS - SUBMISSION FILE CHHS-2026-NB - DOCUMENTS AS RECEIVED"
OHM_HDR = f"{D.OHM.upper()}  |  Policyholder service {D.OHM_PHONE}  |  {D.OHM_WEB}"


# ════════════════════════════════════════════════════════════════════════════
# Underwriter Q&A and two more e-mail threads
# ════════════════════════════════════════════════════════════════════════════
def uw_questions(f: Flow):
    f.doc("E-MAIL - UNDERWRITER QUESTIONS AND ANSWERS (10/02/2026)", PKG_HDR)
    f.kv([("From:", f"{D.AGENCY_PRODUCER} <{D.AGENCY_EMAIL}>"),
          ("Sent:", "Friday, October 2, 2026 3:31 PM"), ("To:", D.UNDERWRITER),
          ("Subject:", "RE: Cumberland Hearth - underwriting questions")], font=SANS, size=7.0,
         label_w=60)
    f.gap(4)
    qa = [
        ("Who is the insurer on this - Ridgeline or ARU?",
         f"Ridgeline Specialty Insurance Company is the writing company; ARU administers the program. "
         f"(Priya confirmed Ridgeline's NAIC on the acknowledgement.)"),
        ("Is the Kellerman lot customer parking? Fee?",
         "Yes - owned lot, 60 spaces, customers and employees. No fee is charged."),
        ("Drones?", "They sold their drone in June 2025 and own none now. They hire SkyFrame Imaging "
                    "twice a year for marketing photos."),
        ("Subcontracting?", f"{D.SUBS_PCT} of the installation work, final electrical and gas "
                            f"connections only; {D.SUBS_PAID} paid to subs in FY2025."),
        ("Are all the vehicles part of a fleet?",
         "I don't know how Ridgeline defines a fleet for this question - four units. I have asked "
         "Ted and will come back to you; please treat it as open."),
        ("Questions 7 and 9 on the 125?", "Still open with the insured's attorney. Not answered."),
        ("Any swimming pool, lodging, day care or recreation facilities?",
         "Not something we asked - I'll add it to the client questionnaire."),
        ("Employees?", "66 full time and 7 part time on payroll across both companies. The 9 "
                       "seasonal workers are agency temps from Harpeth Staffing - not on payroll."),
        ("Any other insurance with Ridgeline?", "Yes - the installation floater, IMF-3318207. The "
                                                "workers compensation is NOT with Ridgeline."),
        ("Loss runs?", "Attached - Old Hickory valued 09/15/2026, Magnolia 09/10/2026, Cardinal "
                       "09/08/2026, Volunteer Fire & Marine through 12/01/2024."),
    ]
    for q, a in qa:
        f.para(f"Q: {q}", SANS_B, 6.9)
        f.para(f"A: {a}", SANS, 6.9)
        f.gap(2)


def facilities_thread(f: Flow):
    f.doc("E-MAIL THREAD - SQUARE FOOTAGE AND PREMISES (facilities manager and the agency CSR)",
          PKG_HDR)
    f.paras([
        "From: Rafael Quintero  Sent: 08/27/2026 2:14 PM  To: Jordan Pike  Subject: RE: building "
        "sizes",
        "Jordan - Kellerman is 58,000 sq ft under roof. We use 52,000 of it; the other 6,000 is "
        f"the print shop ({D.SUBLEASE_TENANT}) we sublease to on the north end. The showroom "
        "(the only part the public walks into) is 2,400 sq ft including the test kitchen.",
        "La Vergne: we have Suite C - 12,500 sq ft - in a 50,000 sq ft flex building. Nobody from "
        "the public comes there. It's in the county, not the city, even though the mail says La "
        "Vergne.",
        "Franklin: Suite 220 was 3,400 sq ft until the July amendment; we gave back a room and "
        "now have 3,100. About 300 sq ft of that is the reception area where customers drop in. "
        "The building is 24,000 sq ft.",
        "Visco Drive closed at the end of June. Keys returned, nothing left there.",
        "Rafael Quintero | Facilities Manager | cell (615) 555-0177 | desk 615.555.0168",
        "> From: Jordan Pike  Sent: 08/26/2026  Subject: building sizes",
        "> Rafael - for the application I need, for each building: total square feet, the part you "
        "occupy, the part open to the public, and whether you lease any of it to others.",
    ], font=SANS, size=6.9)


def accounting_thread(f: Flow):
    f.doc("E-MAIL THREAD - REVENUE AND PAYROLL (controller and the agency CSR)", PKG_HDR)
    f.paras([
        "From: Denise Okafor  Sent: 08/28/2026 10:02 AM  To: Jordan Pike  Subject: RE: revenue / "
        "payroll for the app",
        "Jordan - FY2025 consolidated revenue was $18.6 million. All equipment, parts and showroom "
        "sales are booked at Kellerman ($15.2M). The Service Co. books its own service revenue out "
        "of Franklin ($3.4M). La Vergne is a depot - zero revenue. The FY2027 plan is $21.1M but "
        "that is a budget, not actuals.",
        f"Payroll FY2025 was {D.PAYROLL_TOTAL} for both companies. Service technicians' payroll "
        "(Service Co.) was $1,190,000 in FY2025; we estimate $1,284,600 for the coming policy year "
        "with two raises and one added tech.",
        "Backlog of signed orders not yet delivered: $4,312,600 at the end of August.",
        "My direct line is 615-555-0165. Please use ap@cumberlandhearth-example.com for invoices.",
        "Denise",
        "> From: Jordan Pike  Sent: 08/27/2026  Subject: revenue / payroll for the app",
        "> Denise - can you give me FY2025 revenue by location, total payroll and the service "
        "payroll? Also your best number for the accounting contact.",
    ], font=SANS, size=6.9)


# ════════════════════════════════════════════════════════════════════════════
# The incumbent's loss-control survey (2025 - dated numbers)
# ════════════════════════════════════════════════════════════════════════════
def loss_control_survey(f: Flow):
    f.doc("OLD HICKORY MUTUAL - LOSS CONTROL SURVEY REPORT - SURVEY DATE 06/18/2025", OHM_HDR)
    f.kv([("Insured", D.NAME), ("Policies", "OHM-GL-4471902-24 / OHM-CA-4471903-24"),
          ("Consultant", "R. Thibodeaux, CSP"), ("Persons interviewed", f"{D.FACILITIES}; {D.CFO}"),
          ("Report date", "07/02/2025")], font=MONO, size=6.8, label_w=140)
    f.head("1. OPERATIONS (as observed 06/18/2025)")
    f.para("Wholesale distribution of commercial kitchen equipment with a service subsidiary that "
           "installs and repairs equipment at customer sites. At the survey date the insured also "
           "operated a small retail outlet at 1040 Visco Dr (since closed - see the 2026 file). "
           "Employees at survey: Kellerman 39 full time / 5 part time; La Vergne 3 / 0; Franklin "
           "20 / 1; Visco 2 / 1.", SERIF, 7.0)
    f.head("2. BUILDING - 2850 KELLERMAN INDUSTRIAL PKWY")
    f.table(["ITEM", "OBSERVATION"],
            [["Construction", "Masonry non-combustible, single story, built 1987"],
             ["Area", "58,000 sq ft (insured occupies all but the north-end sublet)"],
             ["Roof", "Replaced April 2025 - 60-mil TPO; contractor letter on file"],
             ["Sprinklers", "Wet system, 100% coverage, last tested 03/2025"],
             ["Alarm", "Central station burglar and fire alarm"],
             ["Showroom", "Public area approx. 2,400 sq ft including test kitchen"],
             ["Hazards", "Propane cylinder cage (exterior); corrosive cleaner storage room"],
             ["Housekeeping", "Fair - pallets staged near the rear exit door"]],
            [LEFT, 150], font=MONO, size=6.4)
    f.head("3. RECOMMENDATIONS")
    f.paras([
        "25-01 Keep the rear warehouse exit clear of stored material at all times. (Status at "
        "report date: open.)",
        "25-02 Implement a documented monthly inspection of portable fire extinguishers. (Status: "
        "open.)",
        "25-03 Formalize MVR review for all drivers annually. (Status: complied 09/2025.)",
        "25-04 Install telematics on all fleet units. (Status: complied 11/2025.)",
    ], font=MONO, size=6.6)
    f.head("4. FLEET (as observed)")
    f.para("Five units at survey: 2023 Isuzu NPR-HD, 2022 Ford Transit 250, 2021 Freightliner M2 106, "
           "2017 Ford E-350 and a 2015 Chevrolet Express 2500 (sold 08/2025). Drivers: seven "
           "authorized at survey, including two since terminated.", SERIF, 7.0)
    f.head("5. GENERAL")
    rnd = random.Random(31)
    notes = ["Receiving dock plates inspected and in good condition.",
             "Forklift charging area ventilated; eyewash station present.",
             "Mezzanine expansion under discussion with the owner; no permits yet.",
             "Test kitchen hood suppression system serviced semi-annually.",
             "Customer parking lot well lit; potholes noted at the east entrance.",
             "Electrical panels unobstructed; infrared scan recommended within 12 months.",
             "Security cameras cover the yard and both dock doors.",
             "Chemical room bunded; SDS binder current.",
             "Propane cage locked; 9 cylinders in storage at the time of the visit.",
             "First aid kits stocked; two employees CPR certified."]
    for i in range(18):
        f.para(f"5.{i + 1} {notes[rnd.randrange(len(notes))]}", SERIF, 6.8)


# ════════════════════════════════════════════════════════════════════════════
# Full financial statements
# ════════════════════════════════════════════════════════════════════════════
def financial_statements(f: Flow):
    f.doc(f"{D.NAME.upper()} AND SUBSIDIARY - CONSOLIDATED FINANCIAL STATEMENTS FY2025 "
          "(compiled, not audited)", PKG_HDR)
    f.head("CONSOLIDATED STATEMENT OF INCOME - YEAR ENDED 12/31/2025")
    f.table(["", "FY2025", "FY2024"],
            [["Net sales - equipment", "$12,905,114", "$11,622,480"],
             ["Net sales - parts and supplies", "$2,344,930", "$2,190,412"],
             ["Service, installation and repair revenue", "$3,349,956", "$2,987,108"],
             ["TOTAL REVENUE", "$18,600,000", "$16,800,000"],
             ["Cost of goods sold", "$11,942,330", "$10,861,904"],
             ["Gross profit", "$6,657,670", "$5,938,096"],
             ["Salaries and wages", D.PAYROLL_TOTAL, "$4,402,110"],
             ["Payroll taxes and benefits", "$1,104,226", "$988,470"],
             ["Rent - La Vergne and Franklin", "$214,800", "$228,600"],
             ["Rent - 1040 Visco Dr (closed 06/30/2026)", "$61,200", "$61,200"],
             ["Insurance", "$214,330", "$197,415"],
             ["Depreciation", "$402,550", "$377,960"],
             ["Interest - Pinnacle Commerce Bank mortgage", "$141,882", "$150,318"],
             ["Bad debt (incl. Riverside Bistro Group $14,200 - FY2024)", "$9,410", "$22,870"],
             ["Other operating expenses", "$412,076", "$395,200"],
             ["Equity in earnings of Music Row Kitchen Rentals, LLC (40%)", "$38,640", "$27,105"],
             ["NET INCOME BEFORE TAX", "$135,066", "$90,328"]],
            [LEFT, 380, 470], font=MONO, size=6.4)
    f.head("CONSOLIDATED BALANCE SHEET - 12/31/2025 (selected)")
    f.table(["", "AMOUNT"],
            [["Cash", "$1,284,410"], ["Accounts receivable, net", "$2,402,118"],
             ["Inventory", "$3,977,560"], ["Investment in Music Row Kitchen Rentals, LLC", "$412,300"],
             ["Land and building - 2850 Kellerman Industrial Pkwy (cost)", "$4,880,000"],
             ["Vehicles and equipment (cost)", "$611,450"],
             ["Mortgage payable - Pinnacle Commerce Bank, N.A.", "$2,731,960"],
             ["Equipment notes - Volunteer Truck Finance / Highline Commercial Truck Credit", "$148,220"],
             ["Shareholders' equity", "$4,906,775"]], [LEFT, 420], font=MONO, size=6.4)
    f.head("NOTES TO THE FINANCIAL STATEMENTS (selected)")
    f.paras([
        f"Note 1 - Organization. {D.NAME} (the Company) was organized as {D.FORMER_NAME} on March 1, "
        "2009 and converted to a Tennessee corporation on January 1, 2022. The consolidated "
        f"statements include its wholly owned subsidiary {D.SUB['name']}, formed March 15, 2018.",
        f"Note 4 - Investment. The Company holds a 40% membership interest in {D.JV['name']}, "
        "accounted for by the equity method. The Company does not control it and it is not "
        "consolidated.",
        "Note 6 - Debt. The mortgage loan from Pinnacle Commerce Bank, N.A. (original principal "
        "$3,150,000, matures May 1, 2034) is secured by the Kellerman land and building. Two "
        "equipment notes are secured by vehicles.",
        "Note 8 - Leases. The Company leases its La Vergne depot and, through the subsidiary, the "
        "Franklin office. The Visco Drive retail lease was terminated June 30, 2026.",
        "Note 9 - Litigation. In 2025 the Company obtained a judgment of $22,480 against a former "
        "customer, Two Rivers Catering Co., for unpaid invoices; collection is in progress. There "
        "is no litigation pending against the Company.",
        "Note 10 - Concentrations. No customer exceeded 6% of FY2025 revenue. A customer, "
        "Riverside Bistro Group, LLC, filed a Chapter 11 petition in 2024; the receivable was "
        "written off.",
        "Note 11 - Subsequent events. The Visco Drive outlet closed on June 30, 2026. The Company's "
        "drone was sold in June 2025.",
    ], font=SERIF, size=7.0)


# ════════════════════════════════════════════════════════════════════════════
# Payroll register (wages sum to the stated payroll)
# ════════════════════════════════════════════════════════════════════════════
def _scaled(weights, target):
    """Integers proportional to `weights` that sum to exactly `target`."""
    tot = sum(weights)
    out = [int(w * target / tot) for w in weights]
    out[-1] += target - sum(out)
    return out


def payroll_register(f: Flow, roster_rows):
    f.doc("PAYROLL REGISTER FY2025 - ANNUAL W-2 WAGES BY EMPLOYEE (both companies)", PKG_HDR)
    rnd = random.Random(4242)
    total = int(D.PAYROLL_TOTAL.replace("$", "").replace(",", ""))
    service_target = 1_190_000
    rows = []
    frk = [r for r in roster_rows if r[2] == "FRK"]
    other = [r for r in roster_rows if r[2] != "FRK"]
    # service-tech wages (FRK) sum to the FY2025 service payroll
    w = _scaled([rnd.randint(38000, 61000) if r[3] == "F/T" else rnd.randint(14000, 22000)
                 for r in frk], service_target)
    for r, wage in zip(frk, w):
        rows.append([r[0], r[1], r[2], r[3], "9519" if "Tech" in r[4] else "8810", f"${wage:,}"])
    w2 = _scaled([rnd.randint(28000, 96000) if r[3] == "F/T" else rnd.randint(11000, 24000)
                  for r in other], total - service_target)
    for r, wage in zip(other, w2):
        cls = {"Office": "8810", "Finance": "8810", "Executive": "8810", "Sales": "8742",
               "Delivery": "7380", "Safety": "8810", "Facilities": "8018"}.get(r[4], "8018")
        rows.append([r[0], r[1], r[2], r[3], cls, f"${wage:,}"])
    rows.sort(key=lambda r: r[0])
    f.table(["EMP #", "NAME", "LOC", "STATUS", "WC CLASS", "FY2025 WAGES"], rows,
            [LEFT, 90, 230, 270, 320, 380], size=6.2)
    f.para(f"TOTAL FY2025 W-2 WAGES {D.PAYROLL_TOTAL}. Service technicians (FRK) $1,190,000. WC "
           "classes: 8018 store - wholesale; 8810 clerical; 8742 outside sales; 7380 drivers; 9519 "
           "appliance installation and repair. Workers compensation is insured by Tennessee "
           f"Employers Mutual ({D.TEM_POLICY}) and is not part of this submission.", SANS, 6.6)


# ════════════════════════════════════════════════════════════════════════════
# Product catalogue and service tickets
# ════════════════════════════════════════════════════════════════════════════
def catalogue(f: Flow):
    f.doc("PRICE LIST 2026 - EQUIPMENT AND PARTS (excerpt)", PKG_HDR)
    rnd = random.Random(515)
    brands = [("Forni Lombardi", "IT"), ("Vettore", "IT"), ("Hartwell Refrigeration", "US"),
              ("Ozark Range Co.", "US"), ("Pemberton Fryers", "US"), ("Glacier Ice Systems", "US"),
              ("Steelcraft Fabrication", "US"), ("CHHS ProClean", "US - private label")]
    kinds = ["deck oven", "conveyor oven", "espresso machine 2-group", "espresso machine 3-group",
             "reach-in refrigerator", "walk-in cooler kit", "gas range 6-burner", "fryer 40 lb",
             "ice machine 500 lb", "worktable 30x72", "hood 10 ft", "degreaser 1 gal x4",
             "oven cleaner 1 gal x4", "gas valve kit", "thermostat", "door gasket", "compressor 1 hp"]
    rows = []
    for i in range(260):
        b, origin = brands[rnd.randrange(len(brands))]
        k = kinds[rnd.randrange(len(kinds))]
        rows.append([f"CH-{rnd.choice(['OV', 'EQ', 'RF', 'PT', 'CL'])}-{1000 + i * 13}", f"{b} {k}",
                     origin, f"${rnd.randint(9, 2400) * 10:,}", rnd.choice(["stock", "2-3 wks", "special order"])])
    f.table(["SKU", "DESCRIPTION", "ORIGIN", "LIST", "AVAIL"], rows,
            [LEFT, 110, 330, 420, 480], size=6.1)
    f.para("Imported items (origin IT) are imported by the company and distributed in the USA. "
           "Private-label items are manufactured for the company by Delta Chem Blending, Inc. The "
           "Volunteer Grill line was discontinued in 2024 and is not listed.", SANS, 6.6)


def service_tickets(f: Flow):
    f.doc("SERVICE TICKETS - SAMPLE (Cumberland Hearth Service Co., LLC)", PKG_HDR)
    rnd = random.Random(909)
    techs = ["D. Hollis", "M. Abernathy", "K. Brooks", "O. Castillo", "S. Dunleavy", "T. Easley"]
    work = ["Replaced gas valve on deck oven; leak tested; returned to service.",
            "PM visit: cleaned condenser coils, checked refrigerant charge, replaced door gasket.",
            "Installed 3-group espresso machine; water filter and drain connected; final electrical by Bellevue Electric.",
            "Recovered refrigerant from failed compressor; recovery cylinder to reclaimer.",
            "Loaner combi oven delivered while customer unit is repaired; staff shown operation.",
            "Fryer thermostat replaced; calibrated; tested.",
            "Ice machine descaled; inlet valve replaced.",
            "Hood suppression link inspection coordinated with customer's vendor."]
    sites = D.job_sites()
    for i in range(40):
        s = sites[(i * 3) % len(sites)]
        f.para(f"TICKET SV-26-{4100 + i * 17}  |  {s['customer']}  |  {s['addr']}, {s['city']}, "
               f"{s['state']} {s['zip']}  |  tech {techs[i % len(techs)]}  |  "
               f"{(i % 9) + 1:02d}/{(i * 5) % 27 + 1:02d}/2026  |  {rnd.randint(1, 7)}.{rnd.choice([0, 5])} hrs  |  "
               f"warranty {'Y' if i % 4 == 0 else 'N'}  |  {work[i % len(work)]}", MONO, 6.2)


# ════════════════════════════════════════════════════════════════════════════
# Telematics trip log, maintenance records, the MVR vendor's JSON
# ════════════════════════════════════════════════════════════════════════════
def trip_log(f: Flow):
    f.doc("FLEETPULSE - TRIP LOG EXPORT (fixed width) - SEPTEMBER 2026", PKG_HDR)
    rnd = random.Random(1717)
    f.line("DATE       VEH DRV START    END      ORIGIN                 DEST                    MI   MAXMPH EVENTS", MONO, 6.0)
    base = {"1": "KELLERMAN YARD", "2": "LA VERGNE DEPOT", "3": "FRANKLIN OFFICE", "4": "KELLERMAN YARD"}
    drv = {"1": "1", "2": "2", "3": "3", "4": "4"}
    sites = D.job_sites()
    for day in range(1, 31):
        for v in ("1", "2", "3", "4"):
            if rnd.random() < 0.25:
                continue
            d = drv[v]
            if v == "2" and rnd.random() < 0.3:
                d = "6"
            s = sites[rnd.randrange(len(sites))]
            st = f"{rnd.randint(6, 10):02d}:{rnd.randint(0, 59):02d}"
            en = f"{rnd.randint(12, 17):02d}:{rnd.randint(0, 59):02d}"
            mi = rnd.randint(8, 190 if v in ("1", "4") else 48)
            f.line(f"09/{day:02d}/2026 {v:>3} {d:>3} {st:<8} {en:<8} {base[v]:<22} "
                   f"{(s['city'] + ' ' + s['state'])[:22]:<23} {mi:>4} {rnd.randint(52, 71):>6} "
                   f"{rnd.choice(['-', '-', '-', 'HB', 'SP', 'HB+SP'])}", MONO, 6.0)


def maintenance_records(f: Flow):
    f.doc("FLEET MAINTENANCE RECORDS - LAST 12 MONTHS", PKG_HDR)
    rnd = random.Random(2323)
    rows = []
    for v in D.VEHICLES:
        odo = rnd.randint(18000, 140000)
        for k in range(12):
            odo += rnd.randint(2500, 6000)
            rows.append([v["num"], v["vin"], f"{(k % 12) + 1:02d}/{rnd.randint(1, 28):02d}/2026"
                         if k > 2 else f"{10 + k}/{rnd.randint(1, 28):02d}/2025", f"{odo:,}",
                         rnd.choice(["Oil and filter; inspection", "Brakes - front pads", "Tires rotated",
                                     "Annual DOT inspection - passed", "Liftgate service",
                                     "Battery replaced", "Coolant flush", "Wipers and lights"]),
                         rnd.choice(["in-house", "Music City Fleet Service"])])
    f.table(["VEH", "VIN", "DATE", "ODOMETER", "WORK", "BY"], rows,
            [LEFT, 60, 170, 230, 290, 450], size=6.1)


def mvr_json(f: Flow):
    f.doc("CLEARPATH MVR SERVICES - API EXPORT (JSON) - 09/14/2026", PKG_HDR)
    recs = []
    for d in D.DRIVERS:
        recs.append({"order": f"CP-{d['lic'][-5:]}", "name": f"{d['last'].upper()}, {d['first'].upper()} {d['mi']}",
                     "dob": d["dob"][6:] + "-" + d["dob"][:2] + "-" + d["dob"][3:5],
                     "dl": d["lic"], "state": d["lic_state"], "class": "A" if d["num"] == "4" else "D",
                     "status": "VALID", "points": 3 if d["num"] == "3" else 0,
                     "violations": ([{"date": "2025-05-17", "desc": "SPEEDING 11-15 OVER", "county": "SIMPSON KY"}]
                                    if d["num"] == "3" else
                                    ([{"date": "2019-09-02", "desc": "FAILURE TO YIELD", "county": "DAVIDSON TN"}]
                                     if d["num"] == "1" else []))})
    recs.append({"order": "CP-33019", "name": "AMBROSE, KYLE J", "dob": "1999-04-04",
                 "dl": D.TERMINATED_DRIVER["lic"], "state": "TN", "class": "D", "status": "VALID",
                 "points": 4, "violations": [{"date": "2026-07-19", "desc": "AT FAULT ACCIDENT",
                                              "county": "RUTHERFORD TN"}],
                 "note": "employee terminated 08/29/2026 - remove from roster"})
    for ln in json.dumps(recs, indent=1).splitlines():
        f.line(ln, MONO, 6.0)


# ════════════════════════════════════════════════════════════════════════════
# Certificates of insurance (ACORD 25 style, issued by the PRIOR agency)
# ════════════════════════════════════════════════════════════════════════════
def certificates(f: Flow):
    for i, (holder, addr) in enumerate(D.CERT_HOLDERS[:8]):
        f.doc(f"CERTIFICATE OF LIABILITY INSURANCE - DATE 0{i + 1}/1{i}/2026 (issued by the prior "
              "agency)", f"{D.PRIOR_AGENCY}  |  {D.PRIOR_AGENCY_PHONE}")
        f.kv([("PRODUCER", f"{D.PRIOR_AGENCY}, 2200 West End Ave, Nashville TN 37203"),
              ("INSURED", f"{D.NAME}, {D.MAIL_L1}, {D.MAIL_CITY} TN {D.MAIL_ZIP}"),
              ("INSURER A", f"{D.OHM}  NAIC {D.OHM_NAIC}"), ("INSURER B", f"{D.MAG}  NAIC {D.MAG_NAIC}"),
              ("INSURER C", f"{D.CXS}  NAIC {D.CXS_NAIC}")], font=MONO, size=6.6, label_w=90)
        f.table(["LTR", "TYPE OF INSURANCE", "POLICY NUMBER", "EFF", "EXP", "LIMITS"],
                [["A", "COMMERCIAL GENERAL LIABILITY - OCCUR", "OHM-GL-4471902-25", D.CUR_EFF, D.CUR_EXP,
                  "EACH OCC $1,000,000 / DMG RENTED $100,000 / MED EXP $5,000 / GEN AGG $2,000,000"],
                 ["A", "AUTOMOBILE LIABILITY - ANY AUTO", "OHM-CA-4471903-25", D.CUR_EFF, D.CUR_EXP,
                  "COMBINED SINGLE LIMIT $1,000,000"],
                 ["C", "UMBRELLA LIAB - OCCUR", "CXS-UMB-220871-25", D.CUR_EFF, D.CUR_EXP,
                  "EACH OCC $5,000,000 / AGG $5,000,000"],
                 ["B", "PROPERTY", "MUI-CP-0098817-25", D.CUR_EFF, D.CUR_EXP, "SEE POLICY"]],
                [LEFT, 52, 210, 300, 350, 400], style="riffled", size=5.8)
        f.para("DESCRIPTION OF OPERATIONS: Installation and service of commercial kitchen equipment. "
               f"The certificate holder is included as additional insured where required by written "
               "contract (CG 20 10, CG 20 37).", MONO, 6.2)
        f.para(f"CERTIFICATE HOLDER: {holder}, {addr}", MONO, 6.4)


# ════════════════════════════════════════════════════════════════════════════
# The full superseded 2024 application (prior agency) and the 2024 auto schedule
# ════════════════════════════════════════════════════════════════════════════
def old_application_full(f: Flow):
    f.doc("2024 APPLICATION - CONTINUED (prior agency) - PREMISES, PRIOR CARRIERS, LOSSES",
          f"{D.PRIOR_AGENCY}  |  {D.PRIOR_AGENCY_PHONE}  |  agency code {D.PRIOR_AGENCY_CODE}",
          new_page=True)
    f.watermark("SUPERSEDED - 2024")
    f.table(["LOC", "ADDRESS", "INT", "FT", "PT", "SQ FT", "REVENUE"],
            [["1", "2850 Kellerman Industrial Pkwy, Nashville", "OWN", "37", "4", "58,000", "$12,900,000"],
             ["2", "1040 Visco Dr, Nashville", "TEN", "2", "1", "4,800", "$1,100,000"],
             ["3", "410 Industrial Blvd Ste C, La Vergne", "TEN", "3", "0", "12,500", "$0"],
             ["4", "1199 Hillsboro Commons Dr Ste 220, Franklin", "TEN", "19", "0", "3,400", "$2,100,000"]],
            [LEFT, 60, 260, 290, 315, 340, 400], size=6.4)
    f.head("PRIOR CARRIER INFORMATION (as of 10/2024)")
    f.table(["YEAR", "GL", "AUTO", "PROPERTY", "OTHER"],
            [["2023", "Old Hickory OHM-GL-4471902-23 $33,005", "Old Hickory OHM-CA-4471903-23 $52,880",
              "Volunteer F&M VFM-CPP-7781203", "none"],
             ["2022", "Old Hickory OHM-GL-4471902-22 $31,400", "Old Hickory OHM-CA-4471903-22 $49,615",
              "Volunteer F&M VFM-CPP-7781203", "none"],
             ["2021", "Old Hickory OHM-GL-4471902-21 $29,975", "Old Hickory OHM-CA-4471903-21 $46,030",
              "Volunteer F&M VFM-CPP-7781203", "none"]],
            [LEFT, 70, 200, 330, 460], style="riffled", size=6.0)
    f.head("LOSS HISTORY (as of 10/2024 - 5 years)")
    f.table(["DATE", "LINE", "DESCRIPTION", "PAID", "STATUS"],
            [["05/14/2020", "Property", "Water damage - sprinkler head", "$12,300", "Closed"],
             ["03/03/2022", "Auto", "Van rear-ended at light", "$3,775", "Closed - subro"],
             ["07/22/2023", "Property", "Hail - roof and RTUs", "$38,400", "Open"]],
            [LEFT, 90, 160, 380, 450], size=6.4)
    f.para("(The 2023 hail claim was still open in October 2024; it closed at $41,980 - see the "
           "Volunteer Fire & Marine loss run.)", SERIF_I, 6.8)
    f.head("2024 AUTO SCHEDULE (prior term)")
    f.table(["VEH", "VEHICLE", "VIN", "STATUS NOW"],
            [["1", "2023 Isuzu NPR-HD", "JALC4W162P7004417", "still owned"],
             ["2", "2022 Ford Transit 250", "1FTBR1C82NKA31907", "still owned"],
             ["3", "2015 Chevrolet Express 2500", "1GCWGFCF5F1144028", "SOLD 08/2025"],
             ["4", "2021 Freightliner M2 106", "1FVACWDT7MHMN4471", "still owned"],
             ["5", "2017 Ford E-350", D.SOLD_VEHICLE["vin"], "SOLD 05/22/2026"]],
            [LEFT, 60, 220, 360], size=6.4)
    f.head("2024 DRIVERS (prior term)")
    f.para("Bellweather, Marcus T; Fontenot, Alicia R; Dandekar, Priyanka S; Szymanski, Gregory L; "
           "Ambrose, Kyle J (terminated 08/29/2026); Pettus, Carl (terminated 04/17/2026); "
           "Faulk, Brenda (retired 01/31/2026).", MONO, 6.6)


# ════════════════════════════════════════════════════════════════════════════
# Safety manual, board minutes, supplier list, installation agreement, lease
# insurance clause, appraisal, claim ledgers, prior-year GL schedule
# ════════════════════════════════════════════════════════════════════════════
def safety_manual(f: Flow):
    f.doc("SAFETY MANUAL - TABLE OF CONTENTS AND SELECTED CHAPTERS (rev. 01/2026)", PKG_HDR)
    toc = ["1 Policy and responsibilities", "2 Safety committee", "3 Hazard communication",
           "4 Powered industrial trucks", "5 Lockout / tagout", "6 Ladders and lifts",
           "7 Gas appliance work", "8 Refrigerant handling (EPA 608)", "9 Driver safety",
           "10 Incident reporting", "11 Security", "12 Contractors and visitors"]
    f.para("  |  ".join(toc), SANS, 6.6)
    chapters = [
        ("2 SAFETY COMMITTEE", "The committee is chaired by the Safety & Compliance Coordinator and "
         "includes one member from each department. It meets quarterly (January, April, July and "
         "October); minutes are kept for three years. Between meetings, supervisors hold brief "
         "toolbox talks at their discretion."),
        ("4 POWERED INDUSTRIAL TRUCKS", "Only trained and evaluated operators may drive forklifts. "
         "Evaluations are repeated every year and after any incident. Propane cylinders are changed "
         "outdoors at the cylinder cage using gloves and eye protection."),
        ("7 GAS APPLIANCE WORK", "Company technicians do not install gas piping. Final gas "
         "connections are made by a licensed plumbing and gas subcontractor. Technicians leak-test "
         "appliance-side connections before returning equipment to service."),
        ("8 REFRIGERANT HANDLING", "All technicians hold EPA Section 608 certification. Recovered "
         "refrigerant is held in DOT-approved recovery cylinders, transported upright and secured, "
         "and returned to a licensed reclaimer. Cylinders are never vented."),
        ("9 DRIVER SAFETY", "Drivers must hold a valid licence, a clean MVR (no major violations in "
         "three years) and, for vehicle 4, a CDL. MVRs are pulled at hire and each March. Telematics "
         "scores are reviewed weekly."),
        ("11 SECURITY", "Buildings are alarmed and monitored; yards are fenced and gated; cameras "
         "cover docks and yards; key-card access logs are retained for 90 days."),
    ]
    for t, body in chapters:
        f.head(t, SANS_B, 7.0)
        f.para(body, SERIF, 7.0)
        f.para(body.replace("The ", "Each ").replace("All ", "Every "), SERIF, 7.0)


def board_minutes(f: Flow):
    f.doc("MINUTES OF THE ANNUAL MEETING OF THE BOARD OF DIRECTORS - 03/18/2026", PKG_HDR)
    f.paras([
        f"Present: {D.CEO} (chair), {D.CFO}, Owen P. Ellison. Also present: {D.CONTROLLER} (secretary).",
        "1. Officers re-elected: Margaret A. Ellison, President; Theodore Lindqvist, Treasurer and CFO; "
        "Owen P. Ellison, Secretary.",
        "2. The board ratified the purchase of a 2024 Ram ProMaster 2500 for the Franklin service team "
        "(added to the auto policy 03/09/2026) and the sale of the 2017 Ford E-350.",
        "3. The board approved the closure of the Visco Drive retail outlet effective June 30, 2026.",
        "4. The board authorised management to obtain permits for a mezzanine in the Kellerman "
        "warehouse, construction to begin in 2027.",
        "5. The board noted the company remains a C corporation and declined to elect S status.",
        "6. Insurance: the board directed management to change agents and market the account for "
        "the December 2026 renewal.",
        "7. The board noted that the company's 40% interest in Music Row Kitchen Rentals, LLC is "
        "a passive investment managed by the majority member.",
    ], font=SERIF, size=7.0)


def supplier_list(f: Flow):
    f.doc("APPROVED SUPPLIER LIST", PKG_HDR)
    rows = [["Forni Lombardi S.r.l.", "Bergamo, Italy", "Deck ovens", "Importer of record: the company"],
            ["Macchine Caffe Vettore S.p.A.", "Milan, Italy", "Espresso machines", "Importer of record: the company"],
            ["Delta Chem Blending, Inc.", "Memphis, TN", "Private-label cleaners", "Blends under CHHS label"],
            ["Hartwell Refrigeration", "Columbus, OH", "Refrigeration", "Manufacturer's label"],
            ["Ozark Range Co.", "Springfield, MO", "Ranges", "Manufacturer's label"],
            ["Pemberton Fryers", "Dayton, OH", "Fryers", "Manufacturer's label"],
            ["Glacier Ice Systems", "Tulsa, OK", "Ice machines", "Manufacturer's label"],
            ["Steelcraft Fabrication", "Chattanooga, TN", "Stainless tables / hoods", "Manufacturer's label"],
            ["Music City Fleet Service", "Nashville, TN", "Fleet maintenance", "Service vendor"],
            ["Bellevue Electric Co.", "Nashville, TN", "Electrical subcontractor", "COI on file"],
            ["Rutledge Plumbing & Gas, LLC", "Antioch, TN", "Gas / plumbing subcontractor", "COI on file"]]
    f.table(["SUPPLIER", "LOCATION", "SUPPLIES", "NOTE"], rows, [LEFT, 200, 300, 420], size=6.3)


def installation_agreement(f: Flow):
    f.doc("STANDARD INSTALLATION AND SERVICE AGREEMENT (form CH-IA-2025) - EXCERPT", PKG_HDR)
    f.paras([
        "4. Warranty. Contractor warrants its labor for one (1) year from completion. Equipment is "
        "covered only by the manufacturer's warranty, except imported equipment for which the "
        "company provides the labor portion of the warranty.",
        "7. Indemnity. To the fullest extent permitted by law, Contractor shall indemnify and hold "
        "harmless the Owner and the General Contractor from claims arising out of Contractor's work, "
        "except to the extent caused by their sole negligence.",
        "8. Insurance. Contractor shall maintain commercial general liability of not less than "
        "$1,000,000 per occurrence and $2,000,000 aggregate, automobile liability of $1,000,000, "
        "umbrella of $5,000,000 and statutory workers compensation, and shall name the Owner and "
        "General Contractor as additional insureds for ongoing and completed operations.",
        "9. Design. Kitchen layout drawings prepared by Contractor show equipment placement only and "
        "are subject to review by the Owner's architect or engineer.",
        "11. Hazardous materials. Contractor will recover refrigerant from replaced equipment and "
        "remove it from the site for reclamation.",
    ], font=SERIF, size=7.0)


def lease_insurance_clause(f: Flow):
    f.doc("LEASE - 410 INDUSTRIAL BLVD, SUITE C - ARTICLE 12 INSURANCE (full text)", PKG_HDR)
    f.paras([
        "12.1 Tenant shall, at its expense, maintain commercial general liability insurance with "
        "limits of not less than $1,000,000 per occurrence and $2,000,000 in the aggregate, naming "
        f"Landlord, {D.LANDLORD_AI['name']}, and its property manager as additional insureds as "
        "respects the Premises.",
        "12.2 Tenant shall deliver a certificate of insurance before taking possession and at each "
        "renewal.",
        "12.3 Tenant shall insure its personal property and trade fixtures for full replacement cost. "
        "Landlord insures the building.",
        "12.4 Waiver of subrogation. Landlord and Tenant each waive rights of recovery against the "
        "other to the extent of insurance required by this Lease.",
        "12.5 The Premises (12,500 rentable square feet) lie in unincorporated Rutherford County.",
    ], font=SERIF, size=7.0)


def appraisal(f: Flow):
    f.doc("APPRAISAL SUMMARY - 2850 KELLERMAN INDUSTRIAL PKWY (for Pinnacle Commerce Bank, 2024)",
          PKG_HDR)
    f.kv([("Effective date of value", "05/01/2024"), ("Land", "6.2 acres, M-2 zoning, Davidson County"),
          ("Improvements", "58,000 sq ft masonry warehouse / office / showroom, built 1987"),
          ("Market value - as is", D.BUILDING_VALUE_LOC1),
          ("Insurable replacement cost (building)", "$7,240,000"),
          ("Flood zone", "X (minimal)"), ("Parking", "60 surface spaces, owned")],
         font=MONO, size=6.8, label_w=200)


def claim_ledgers(f: Flow):
    A, P, C = D.LOSSES
    f.doc("CLAIM PAYMENT LEDGERS (from the carriers' claim systems)", PKG_HDR)
    f.head(f"{A['claim_no']} - {D.OHM}")
    f.table(["DATE", "TRANSACTION", "AMOUNT", "PAID TO DATE", "RESERVE"],
            [["08/14/2025", "Reserve set", "", "$0", "$7,900"],
             ["10/02/2025", "Payment - awning contractor (partial)", "$2,100", "$2,100", "$5,800"],
             ["12/31/2025", "Valuation", "", "$2,100", "$5,800"],
             ["03/11/2026", "Payment - gutter replacement", "$3,850", "$5,950", "$2,000"],
             ["08/20/2026", "Payment - final awning fabric", "$462", "$6,412", "$1,500"],
             ["09/15/2026", "Valuation", "", "$6,412", "$1,500"]],
            [LEFT, 100, 300, 380, 460], size=6.4)
    f.head(f"{P['claim_no']} - {D.VFM}")
    f.table(["DATE", "TRANSACTION", "AMOUNT", "PAID TO DATE", "RESERVE"],
            [["07/24/2023", "Reserve set", "", "$0", "$45,000"],
             ["09/05/2023", "Payment - emergency roof repair", "$8,600", "$8,600", "$36,400"],
             ["02/14/2024", "Payment - RTU replacement", "$29,800", "$38,400", "$6,600"],
             ["11/08/2024", "Final payment - closed", "$3,580", "$41,980", "$0"]],
            [LEFT, 100, 300, 380, 460], size=6.4)
    f.head(f"{C['claim_no']} - {D.OHM} (former name {D.FORMER_NAME})")
    f.table(["DATE", "TRANSACTION", "AMOUNT", "PAID TO DATE", "RESERVE"],
            [["03/04/2022", "Reserve set", "", "$0", "$4,000"],
             ["03/29/2022", "Payment - body shop", "$3,775", "$3,775", "$0"],
             ["06/30/2022", "Subrogation recovery from third party's carrier", "($3,775)", "$3,775", "$0"]],
            [LEFT, 100, 300, 380, 460], size=6.4)
    f.para("Paid to date is GROSS paid; the subrogation recovery does not reduce it.", SANS, 6.6)
    f.para(f"Five-year totals, all carriers, valued September 2026: paid {D.TOTAL_PAID}; outstanding "
           f"reserve $1,500; total incurred {D.TOTAL_INCURRED}.", SANS, 6.6)


def prior_gl_schedule(f: Flow):
    f.doc("OLD HICKORY MUTUAL - GL LOCATION SCHEDULE (expiring term) - INSURER NUMBERING", OHM_HDR)
    f.table(["INS LOC", "ADDRESS", "STATUS"],
            [["001", "2850 Kellerman Industrial Pkwy, Nashville TN 37211", "active"],
             ["002", "1040 Visco Dr, Nashville TN 37210", "DELETED 07/01/2026"],
             ["003", "410 Industrial Blvd, Suite C, La Vergne TN 37086", "active"],
             ["004", "1199 Hillsboro Commons Dr, Suite 220, Franklin TN 37067", "active"]],
            [LEFT, 90, 380], size=6.4)
    f.head("SCHEDULE OF ADDITIONAL INSUREDS (blanket - written contract) - CG 20 10 / CG 20 37")
    rows = [[n, a, "ongoing + completed"] for n, a in D.CERT_HOLDERS[4:]]
    f.table(["ADDITIONAL INSURED", "ADDRESS", "SCOPE"], rows, [LEFT, 240, 450], size=6.2)
