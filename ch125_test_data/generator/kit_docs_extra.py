"""
kit_docs_extra.py - the fourth layer of the CH125 package. The headline document is
the MGA's own program application, printed in a DRIFTING two-column layout (the
label and value columns sit a few points off each other, so a plain reading order
pairs a label with the wrong value). It restates the truth - it must be read, not
trusted to line order.
"""
from __future__ import annotations

import random

import kit_data as D
from kit_engine import Flow, LEFT, MONO, SANS, SANS_B, SERIF

L1, L2, L3 = D.LOCATIONS
PKG_HDR = "RIVERBEND INSURANCE PARTNERS - SUBMISSION FILE CHHS-2026-NB - DOCUMENTS AS RECEIVED"
ARU_HDR = f"{D.MGA}  |  administrator for {D.CARRIER}"
OHM_HDR = f"{D.OHM.upper()}  |  Policyholder service {D.OHM_PHONE}  |  {D.OHM_WEB}"


def program_application(f: Flow):
    f.doc("HOSPITALITY TRADES PACKAGE - PROGRAM APPLICATION (ARU form HTP-1) - completed by the agency",
          ARU_HDR)
    left = ["Applicant", "Other named insured", "Mailing address", "FEIN", "Entity", "Years in business",
            "Business started", "Proposed effective", "Proposed expiration", "Lines requested",
            "Billing / plan", "Payment method", "Locations", "Employees (FT / PT)",
            "Revenue FY2025", "Installation / service %", "Off-premises % of sales", "Subcontracted",
            "Products exposure", "Imports", "Drones", "Vehicles", "Drivers", "Losses (5 yrs paid)",
            "Prior carrier (GL/Auto)", "Prior carrier (Property)", "Prior carrier (Umbrella)"]
    right = [D.NAME, D.SUB["name"], f"{D.MAIL_L1}, {D.MAIL_CITY}, {D.MAIL_STATE} {D.MAIL_ZIP}", D.FEIN,
             "Corporation (C)", "17", D.START_DATE, D.PROPOSED_EFF, D.PROPOSED_EXP,
             "GL, Property, Auto, Umbrella", "Direct bill, quarterly", D.PAYMENT_METHOD, "3 (see schedule)",
             "66 / 7", "$18,600,000", D.INSTALL_PCT, D.INSTALL_OFF_PCT, D.SUBS_PCT,
             "Private label + imports", "Italy (ovens, espresso)", "None owned; hires a Part 107 vendor",
             "4", "6", D.TOTAL_PAID + " (3 claims)", D.OHM, f"{D.MAG} (since 12/01/2024)", D.CXS]
    f.two_column([f"{x}:" for x in left], right, drift=3.6, font=MONO, size=6.8, xr=210)
    f.head("PROGRAM QUESTIONS (Y / N)")
    qs = [("Any operations involving gas piping?", "N"), ("Any fire suppression work?", "N"),
          ("Any liquor sales?", "N"), ("Any work above three stories?", "N"),
          ("Any products manufactured by the applicant?", "N"),
          ("Any products sold under the applicant's label?", "Y"),
          ("Any imported products?", "Y"), ("Any equipment rented or loaned to others?", "Y")]
    f.xcolumn([(str(i + 1), q, a) for i, (q, a) in enumerate(qs)])


def wc_dec(f: Flow):
    f.doc("TENNESSEE EMPLOYERS MUTUAL - WORKERS COMPENSATION INFORMATION PAGE (not part of this "
          "submission)", f"{D.TEM}  |  NAIC 11236")
    f.kv([("Policy", D.TEM_POLICY), ("Period", "01/01/2026 to 01/01/2027"), ("Insured", D.NAME + "; " + D.SUB["name"]),
          ("Employers liability", "$1,000,000 / $1,000,000 / $1,000,000"), ("Estimated premium", "$44,810")],
         font=MONO, size=6.8, label_w=150)
    f.table(["CLASS", "DESCRIPTION", "EST. PAYROLL", "RATE"],
            [["8018", "Store - wholesale", "$1,402,300", "2.41"], ["8810", "Clerical", "$1,121,600", "0.18"],
             ["8742", "Salespersons - outside", "$468,900", "0.39"], ["7380", "Drivers", "$412,700", "4.96"],
             ["9519", "Household appliance installation / repair", "$1,284,600", "3.88"]],
            [LEFT, 90, 330, 420], size=6.4)
    f.para("Workers compensation stays with Tennessee Employers Mutual and is NOT being marketed. It "
           "is not a line of this submission and is not prior coverage for any line requested.", SANS, 6.6)


def premium_audit(f: Flow):
    f.doc("OLD HICKORY MUTUAL - PREMIUM AUDIT - GL TERM 12/01/2024-12/01/2025 (final)", OHM_HDR)
    f.table(["LOC", "CLASS", "BASIS", "ESTIMATED", "AUDITED"],
            [["001", "12683", "(s)", "$13,200,000", "$13,210,500"],
             ["003", "68706", "(a)", "12,500", "12,500"],
             ["004", "91127", "(p)", "$1,050,000", "$1,122,400"],
             ["002", "10150", "(s)", "$1,100,000", "$1,086,000"]], [LEFT, 80, 140, 200, 300], size=6.4)
    f.para("Audit additional premium $1,214. Location 002 (1040 Visco Dr retail outlet, class 10150) was "
           "deleted 07/01/2026 and is not part of the 2026 exposures. Insurer location numbers differ "
           "from the application's.", MONO, 6.4)


def safety_minutes(f: Flow):
    f.doc("SAFETY COMMITTEE MINUTES - 2026 (quarterly)", PKG_HDR)
    for q, d, items in (("Q1", "01/22/2026", "forklift re-certifications scheduled; extinguisher vendor changed; "
                         "telematics scores reviewed - two drivers coached"),
                        ("Q2", "04/16/2026", "fire marshal citation of 02/11 closed - re-inspection passed "
                         "03/02; egress inspections added to the weekly checklist"),
                        ("Q3", "07/23/2026", "heat illness reminders; refrigerant cylinder securing audit; "
                         "Visco Drive closure checklist completed")):
        f.para(f"{q} meeting {d} - chaired by {D.SAFETY_COORD}. Attendance 9. Items: {items}. Next "
               "meeting next quarter.", SERIF, 7.0)


def driver_qualification(f: Flow):
    f.doc("DRIVER QUALIFICATION FILE CHECKLIST", PKG_HDR)
    rows = []
    for d in D.DRIVERS:
        rows.append([d["num"], f"{d['first']} {d['mi']}. {d['last']}", "Y", "Y", "Y",
                     "Y" if d["num"] == "4" else "n/a", "03/2026", "Y"])
    rows.append(["--", "Kyle J. Ambrose", "Y", "Y", "Y", "n/a", "03/2026", "TERMINATED 08/29/2026"])
    f.table(["DRV", "NAME", "APP", "ROAD TEST", "MVR AT HIRE", "CDL MEDICAL", "ANNUAL MVR", "ACTIVE"], rows,
            [LEFT, 60, 200, 240, 290, 350, 410, 470], size=6.2)


def warranty_log(f: Flow):
    f.doc("WARRANTY CLAIM LOG - IMPORTED AND PRIVATE-LABEL PRODUCTS (2025-2026)", PKG_HDR)
    rnd = random.Random(1515)
    items = ["Lombardi DP-120 deck oven - igniter", "Lombardi DP-120 - thermostat", "Vettore V3 - pump",
             "Vettore V2 - group head gasket", "ProClean degreaser - leaking jug (case replaced)",
             "Vettore V3 - control board", "Lombardi DP-90 - stone cracked in transit"]
    sites = D.job_sites()
    rows = []
    for i in range(60):
        s = sites[rnd.randrange(len(sites))]
        rows.append([f"W-{2500 + i}", f"{rnd.randint(1, 12):02d}/{rnd.randint(1, 28):02d}/{rnd.choice([2025, 2026])}",
                     s["customer"][:26], items[rnd.randrange(len(items))], rnd.choice(["parts", "parts+labor", "replace"]),
                     "no injury"])
    f.table(["CLAIM", "DATE", "CUSTOMER", "ITEM", "REMEDY", "INJURY"], rows,
            [LEFT, 80, 140, 270, 450, 510], size=6.0)


def top_customers(f: Flow):
    f.doc("TOP 40 CUSTOMERS BY FY2025 SALES", PKG_HDR)
    rnd = random.Random(1616)
    rows = []
    for i, s in enumerate(D.job_sites()):
        rows.append([str(i + 1), s["customer"], f"{s['city']}, {s['state']}", f"${rnd.randint(60, 1100) * 1000:,}",
                     rnd.choice(["restaurant", "hotel", "school", "institution", "caterer", "venue"])])
    f.table(["#", "CUSTOMER", "CITY", "FY2025 SALES", "TYPE"], rows, [LEFT, 60, 250, 380, 470], size=6.1)


def import_log(f: Flow):
    f.doc("IMPORT SHIPMENT LOG 2025-2026", PKG_HDR)
    rnd = random.Random(1717)
    rows = []
    for i in range(24):
        sup = rnd.choice(["Forni Lombardi S.r.l.", "Macchine Caffe Vettore S.p.A."])
        rows.append([f"SH-{7100 + i * 3}", sup, rnd.choice(["Genova", "La Spezia", "Livorno"]),
                     rnd.choice(["Savannah", "Charleston", "Norfolk"]),
                     f"{rnd.randint(1, 12):02d}/{rnd.randint(1, 28):02d}/{rnd.choice([2025, 2026])}",
                     f"{rnd.randint(2, 18)} units", f"USD {rnd.randint(18, 160) * 1000:,}"])
    f.table(["SHIPMENT", "SUPPLIER", "PORT OUT", "PORT IN", "ARRIVED", "QTY", "VALUE"], rows,
            [LEFT, 80, 230, 290, 350, 410, 470], size=6.0)
    f.para("Products are imported for distribution in the USA only; the company does not export.",
           SANS, 6.5)


def incident_log(f: Flow):
    f.doc("INCIDENT AND NEAR-MISS LOG 2026", PKG_HDR)
    rows = [["01/09/2025", "Loc 2", "Attempted break-in - alarm sounded, intruder fled, nothing taken, no damage", "police report 25-00417"],
            ["02/11/2026", "Loc 1", "Fire marshal citation - blocked rear exit, expired extinguisher tags", "corrected 03/02/2026"],
            ["03/19/2026", "Loc 1", "Near miss - pallet slid off forklift forks; no injury", "retraining"],
            ["05/06/2026", "Customer site", "Near miss - technician slipped on wet floor; no injury", "toolbox talk"],
            ["08/12/2026", "Loc 1", "Propane cylinder valve leak found during change-out; cylinder isolated", "vendor replaced"]]
    f.table(["DATE", "WHERE", "WHAT", "OUTCOME"], rows, [LEFT, 90, 140, 470], style="riffled", size=6.1)
    f.para("None of these events caused injury, damage or a loss to anyone; none is a claim.", SANS, 6.5)


def cfo_name_change(f: Flow):
    f.doc("E-MAIL - LOSS RUNS UNDER THE OLD NAME (insured's CFO)", PKG_HDR)
    f.paras([
        "From: Ted Lindqvist  Sent: 09/25/2026 8:40 AM  To: Caroline Whitlock  Subject: old loss runs",
        f"Caroline - the 2022 auto claim on the Old Hickory run shows our old name, {D.FORMER_NAME}. "
        "That is us - same company, same FEIN, same vans; we converted to a corporation on 1/1/2022 "
        "and the carrier did not update the name until the 2022 renewal. Please include it in the "
        "five-year history.",
        "Music Row Kitchen Rentals' slip-and-fall is THEIR claim on THEIR policy - not ours.",
        "The 2020 sprinkler leak is older than five years from the new effective date, so leave it off "
        "the application.",
        "Ted",
    ], font=SANS, size=6.9)


def bank_reference(f: Flow):
    f.doc("BANK REFERENCE LETTER", "PINNACLE COMMERCE BANK, N.A.")
    f.para(f"September 21, 2026. To whom it may concern: {D.NAME} has banked with us since 2011. The "
           "company maintains operating accounts in good standing and a commercial mortgage loan with "
           "satisfactory payment history. This letter is provided at the customer's request and is not "
           "a guarantee. - Commercial Banking, 150 Third Ave S, Suite 900, Nashville, TN 37201",
           SERIF, 7.0)


EXTRA = ["program_application", "wc_dec", "premium_audit", "safety_minutes", "driver_qualification",
         "warranty_log", "top_customers", "import_log", "incident_log", "cfo_name_change", "bank_reference"]
