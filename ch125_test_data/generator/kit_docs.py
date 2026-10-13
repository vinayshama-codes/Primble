"""
kit_docs.py - the documents of the CH125 package, in the order a broker would
assemble them. Every value printed comes from kit_data (the truth or a decoy),
so a document can never state a value the key does not know about.
"""
from __future__ import annotations

import random

import kit_data as D
from kit_engine import (Flow, It, LEFT, MONO, MONO_B, SANS, SANS_B, SERIF, SERIF_B,
                        SERIF_I, width_of)

L1, L2, L3 = D.LOCATIONS
C0, C1 = D.CONTACTS
OHM_HDR = f"{D.OHM.upper()}  |  Policyholder service {D.OHM_PHONE}  |  {D.OHM_WEB}"
PKG_HDR = "RIVERBEND INSURANCE PARTNERS - SUBMISSION FILE CHHS-2026-NB - DOCUMENTS AS RECEIVED"


def _tick(on: bool) -> str:
    return "[X]" if on else "[ ]"


# ════════════════════════════════════════════════════════════════════════════
# 1. The agency's submission e-mail - the ONLY place the request is stated
# ════════════════════════════════════════════════════════════════════════════
def agency_email(f: Flow):
    f.doc("E-MAIL - NEW BUSINESS SUBMISSION TO APPALACHIAN RISK UNDERWRITERS", PKG_HDR,
          new_page=True)
    f.kv([("From:", f"{D.AGENCY_PRODUCER} <{D.AGENCY_EMAIL}>"),
          ("Sent:", "Monday, September 28, 2026 4:12 PM"),
          ("To:", f"{D.UNDERWRITER} <{D.UNDERWRITER_EMAIL}>"),
          ("Cc:", "Ted Lindqvist <tlindqvist@cumberlandhearth-example.com>; Jordan Pike (CSR)"),
          ("Subject:", f"NEW BUSINESS SUBMISSION - {D.NAME} - eff 12/1/26 - Ridgeline {D.PROGRAM_CODE}"),
          ("Attachments:", "CHHS_submission_package.pdf (this file)")], font=SANS, size=7.2,
         label_w=70)
    f.gap(6)
    f.paras([
        "Priya,",
        f"Attached is our new business submission for {D.NAME} for {D.CARRIER}'s "
        f"{D.PROGRAM_NAME}, which we understand Appalachian Risk Underwriters administers. "
        "This is a request for quotation - new business to Ridgeline. The account has been with "
        f"{D.OHM} (general liability and auto), {D.MAG} (property) and {D.CXS} (umbrella). Old "
        "Hickory has sent a renewal offer, but the insured has asked us to market the account and "
        "Riverbend became agent of record on 07/15/2026.",
        "LINES REQUESTED: Commercial General Liability, Commercial Property, Business Auto and a "
        "Commercial Umbrella ($5,000,000 each occurrence / aggregate).",
        "NOT REQUESTED: workers compensation (stays with Tennessee Employers Mutual, policy "
        f"{D.TEM_POLICY}); commercial inland marine (the installation floater IMF-3318207 is "
        "already written by Ridgeline and runs to 06/2027); crime (the insured declined it); "
        "cyber (discussed, not requested at this time). Equipment breakdown is wanted as an "
        "ENDORSEMENT to the property policy - this is not a request for a separate boiler and "
        "machinery policy. No liquor liability is needed - the insured does not sell or serve "
        "alcohol; the caterer at its customer event holds its own liquor license.",
        f"PROPOSED TERM: {D.PROPOSED_EFF} to {D.PROPOSED_EXP} (twelve months). We moved this from "
        f"{D.STALE_PROPOSED_EFF} so that every line starts together - see Ted's e-mail of 9/24 "
        "further down the package.",
        "BILLING: direct bill to the insured, quarterly installments, paid by ACH auto-debit. "
        "(The current Old Hickory program is Agency bill - 10 installments and the insured does "
        "not want that again.)",
        f"NAMED INSUREDS: (1) {D.NAME} and (2) its wholly owned subsidiary {D.SUB['name']}. "
        f"Please do NOT add {D.JV['name']} - the insured owns 40% of it and it buys its own "
        f"insurance. {D.FORMER_NAME} is the old name of the corporation (converted 01/01/2022), "
        "not a separate company.",
        "GENERAL LIABILITY: same limits as expiring EXCEPT damage to premises rented to you "
        "increased to $300,000 and medical expense increased to $10,000; the general aggregate "
        "to apply per location (CG 25 04 05 09). Please quote a $1,000 per occurrence property "
        "damage liability deductible (the expiring policy has none). Keep employee benefits "
        "liability at $1,000,000. Occurrence form, as expiring.",
        "AUTO: add towing and labor on vehicles 2 and 3 (the two service vans) and increase the "
        "collision deductible on vehicle 4 (the Freightliner) to $2,500. Everything else as "
        f"expiring. The {D.SOLD_VEHICLE['year']} Ford E-350 on the old schedule was sold on "
        f"{D.SOLD_VEHICLE['sold']} and came off by endorsement 2.",
        "LOSS RUNS: five years, currently valued, for every carrier (Old Hickory valued "
        "09/15/2026). The insured's former name appears on the older Old Hickory pages.",
        "OPEN ITEMS: questions 7 and 9 on the general information page are still with the "
        "insured - Margaret wants to review them with the company's attorney. We will send "
        "those answers separately; please do not treat them as answered.",
        "Thanks - happy to set up a call with Ted.",
        "Caroline",
    ], font=SANS, size=7.2)
    f.para(f"{D.AGENCY_PRODUCER}, CIC  |  Commercial Lines Producer  |  {D.AGENCY}  |  "
           f"{D.AGENCY_L1}, {D.AGENCY_L2}, {D.AGENCY_CITY}, {D.AGENCY_STATE} {D.AGENCY_ZIP}  |  "
           f"D {D.AGENCY_PHONE}  |  {D.AGENCY_EMAIL}  |  TN License {D.AGENCY_TN_LICENSE}  |  "
           f"NPN {D.AGENCY_NPN}", font=SANS, size=6.4)
    f.gap(6)
    old = [
        "-----Original Message-----",
        "From: Caroline Whitlock",
        "Sent: Tuesday, August 4, 2026 9:03 AM",
        "To: Priya Raman",
        "Subject: pre-marketing - Cumberland Hearth - target eff 11/15/2026",
        "Priya - heads up that we expect to send you Cumberland Hearth in September for an",
        f"{D.STALE_PROPOSED_EFF} effective date. Wholesale foodservice equipment distributor with a",
        "service subsidiary, about $18.6MM in revenue, four vehicles, three locations. Old",
        "Hickory renewal will be agency billed again unless we move it. I'll send the full",
        "package once the insured signs the supplemental questionnaire.",
        "Caroline",
    ]
    for ln in old:
        f.line("> " + ln, SANS, 6.8)


# ════════════════════════════════════════════════════════════════════════════
# 2. The MGA's acknowledgement - the carrier, its NAIC (fine print), the program
# ════════════════════════════════════════════════════════════════════════════
def mga_acknowledgement(f: Flow):
    f.doc(f"{D.MGA.upper()} - ACKNOWLEDGEMENT OF SUBMISSION",
          f"{D.MGA}  |  {D.MGA_ADDR[0]}, {D.MGA_ADDR[1]}, {D.MGA_ADDR[2]} {D.MGA_ADDR[3]}  |  "
          "Program administrator")
    f.kv([("Date", "October 1, 2026"),
          ("To", f"{D.AGENCY} - producer code {D.AGENCY_CARRIER_CODE} / sub-code "
                 f"{D.AGENCY_CARRIER_SUBCODE}"),
          ("Attention", D.AGENCY_PRODUCER),
          ("Applicant", f"{D.NAME} and {D.SUB['name']}"),
          ("Transaction", "New business - quotation requested"),
          ("Program", f"{D.PROGRAM_NAME} (program code {D.PROGRAM_CODE})"),
          ("Writing company", D.CARRIER),
          ("Requested policy period", f"{D.PROPOSED_EFF} to {D.PROPOSED_EXP}, 12:01 a.m. "
                                      "standard time at the mailing address"),
          ("Underwriter assigned", f"{D.UNDERWRITER}, Senior Underwriter - {D.UNDERWRITER_PHONE}"
                                   f" - {D.UNDERWRITER_EMAIL}"),
          ("Underwriting office", D.UNDERWRITER_OFFICE),
          ("Lines submitted", "Commercial General Liability; Commercial Property (with "
                              "equipment breakdown endorsement); Business Auto; Commercial "
                              "Umbrella"),
          ("Billing", "Direct bill"),
          ("Payment plan", f"{D.PAYMENT_PLAN_WORD} ({D.PAYMENT_PLAN_CODE})"),
          ("Payment method", D.PAYMENT_METHOD),
          ("Premium audit", f"{D.AUDIT_WORD} - audit code {D.AUDIT_CODE}"),
          ("Quote number", "will be assigned when the quotation is issued"),
          ], font=MONO, size=7.0, label_w=150, leader=True)
    f.head("INFORMATION REQUIRED BEFORE QUOTATION")
    f.paras([
        f"1. Loss history: {D.LOSS_YEARS} years of currently valued loss runs for every line "
        "(valued within 90 days of the proposed effective date).",
        "2. Signed ACORD 125, 126 and 127 applications and the program supplemental "
        "questionnaires.",
        "3. Answers to every general information question. A question left blank will be "
        "followed up with the insured; it will not be treated as a 'No'.",
        "4. Motor vehicle reports for every listed driver, dated within 60 days.",
        "5. Statement of values for property; confirmation of roof replacement at location 1.",
    ], font=SANS, size=7.0)
    f.head("NOTICE")
    f.para("This acknowledgement is not a binder, a quotation or an offer of coverage. No "
           "coverage is in force until a policy is bound in writing by an authorized "
           "representative. Premium indications given verbally are not binding.", font=SANS,
           size=6.8)
    f.gap(10)
    f.para(f"Policies in this program are underwritten by {D.CARRIER} (NAIC {D.CARRIER_NAIC}), "
           "Wilmington, DE, and administered by Appalachian Risk Underwriters, LLC, a licensed "
           "managing general agent (TN MGA license 0081245). Appalachian Risk Underwriters is not "
           "an insurer and does not bear risk. Ridgeline's financial strength rating and the "
           "program's state filings are available on request.", font=SANS, size=4.3)


# ════════════════════════════════════════════════════════════════════════════
# 3. The agency's intake worksheet - form boxes, dated AUGUST (some of it stale)
# ════════════════════════════════════════════════════════════════════════════
def intake_worksheet(f: Flow):
    f.doc("RIVERBEND INSURANCE PARTNERS - COMMERCIAL ACCOUNT INTAKE WORKSHEET",
          PKG_HDR, subtitle="Prepared 08/04/2026 by Jordan Pike (CSR) from the insured's "
                            "call and the expiring policies. Producer to verify before "
                            "submission.")
    X0, X1, X2, X3 = LEFT, 250, 400, 576
    f.form_row([(X0, X1, "Applicant / first named insured", D.NAME),
                (X1, X2, "FEIN", D.FEIN), (X2, X3, "Legal entity", "Corporation (C corp)")])
    f.form_row([(X0, X1, "Mailing address", D.MAIL_L1),
                (X1, X3, "City / state / ZIP", f"{D.MAIL_CITY}, {D.MAIL_STATE} {D.MAIL_ZIP}")])
    f.form_row([(X0, X1, "Business phone (main)", D.BUS_PHONE), (X1, X2, "Fax", D.FAX),
                (X2, X3, "Website", D.WEBSITE)])
    f.form_row([(X0, X1, "NAICS", D.NAICS), (X1, X2, "SIC", D.SIC),
                (X2, X3, "GL class (governing)", D.GL_CODE)])
    f.form_row([(X0, X1, "Date business started", D.START_DATE),
                (X1, X2, "Nature of business", "Wholesale"),
                (X2, X3, "Agency customer ID (our AMS)", D.AGENCY_AMS_CUSTOMER_ID)])
    f.form_row([(X0, X1, "Expiring premium - all lines", D.CUR_TOTAL_PREMIUM),
                (X1, X2, "Expiring carriers", "Old Hickory / Magnolia / Cardinal"),
                (X2, X3, "Expiring term", f"{D.CUR_EFF} - {D.CUR_EXP}")])
    f.form_row([(X0, X1, "Target effective date", D.STALE_PROPOSED_EFF),
                (X1, X2, "Employees (all)", f"{D.HEADCOUNT_TOTAL} - see HR census"),
                (X2, X3, "Revenue FY2025", "$18.6MM")])
    f.gap(4)
    f.form_row([(X0, X1, "Named insured #2", D.SUB['name']), (X1, X2, "FEIN", D.SUB['fein']),
                (X2, X3, "Entity", "LLC - see SOS report")])
    f.form_row([(X0, X1, "NI #2 mailing address", f"{D.SUB['l1']}, {D.SUB['l2']}"),
                (X1, X3, "City / state / ZIP", f"{D.SUB['city']}, {D.SUB['state']} {D.SUB['zip']}")])
    f.form_row([(X0, X1, "NI #2 phone", D.SUB['phone']), (X1, X2, "NI #2 NAICS / SIC",
                                                          f"{D.SUB['naics']} / {D.SUB['sic']}"),
                (X2, X3, "NI #2 website", D.SUB['web'])])
    f.form_row([(X0, X1, "NI #2 GL class", D.SUB['gl']),
                (X1, X3, "Relationship to applicant", D.SUB['relationship'])])
    f.head("LINES OF BUSINESS REQUESTED")
    f.line(f"{_tick(True)} Commercial General Liability   {_tick(True)} Commercial Property   "
           f"{_tick(True)} Business Auto   {_tick(True)} Umbrella   {_tick(False)} Inland Marine   "
           f"{_tick(False)} Crime   {_tick(False)} Cyber   {_tick(False)} Workers Comp (stays)",
           MONO, 6.8)
    f.head("NATURE OF BUSINESS (tick one)")
    f.line(f"{_tick(False)} Apartments {_tick(False)} Condominiums {_tick(False)} Contractor "
           f"{_tick(False)} Institutional {_tick(False)} Manufacturing {_tick(False)} Office "
           f"{_tick(False)} Restaurant {_tick(False)} Retail {_tick(False)} Service "
           f"{_tick(True)} Wholesale", MONO, 6.8)
    f.head("CONTACTS")
    f.table(["TYPE", "NAME", "PRIMARY #", "TYPE", "SECONDARY #", "TYPE", "PRIMARY E-MAIL"],
            [[C0["type"], C0["name"], C0["phone"], "CELL", C0["phone2"], "BUS", C0["email"]],
             [C1["type"], C1["name"], C1["phone"], "BUS", D.DENISE_CELL_TYPO, "CELL", C1["email"]]],
            [LEFT, 92, 172, 236, 262, 326, 352], size=6.4)
    f.para("Secondary e-mails: see the CFO's contact list. Do not use Ted Lindqvist as a "
           "contact for inspections or accounting - he asked to be copied only.", SANS, 6.6)
    f.head("DESCRIPTION OF PRIMARY OPERATIONS (for the application)")
    f.para(D.PRIMARY_OPERATIONS, SANS, 7.0)
    f.head("OPERATIONS OF OTHER NAMED INSURED")
    f.para(D.OTHER_INSURED_OPERATIONS, SANS, 7.0)
    f.head("REMARKS (for the application)")
    f.para(D.REMARKS, SANS, 7.0)
    f.head("5-YEAR LOSS SUMMARY - ALL CARRIERS (agency summary, prepared 08/04/2026 - verify "
           "against currently valued loss runs)")
    rows = []
    for x in D.LOSSES:
        paid, res = x["paid"], x["reserved"]
        if x["claim_no"] == "OHM-25-CA-018822":
            paid, res = D.STALE_SUMMARY["paid"], D.STALE_SUMMARY["reserved"]
        rows.append([x["occurrence"], x["line"], x["claim_no"], paid, res,
                     "OPEN" if x["open"] == "Y" else "CLOSED"])
    f.table(["DATE OF LOSS", "LINE", "CLAIM #", "PAID", "RESERVE", "STATUS"], rows,
            [LEFT, 100, 196, 300, 360, 420], size=6.6)
    f.para("Loss history requested by the market: last 5 years. Umbrella - no known losses.",
           SANS, 6.6)


# ════════════════════════════════════════════════════════════════════════════
# 4. The CFO's e-mail thread - corrections and the detail behind the answers
# ════════════════════════════════════════════════════════════════════════════
def cfo_thread(f: Flow):
    f.doc("E-MAIL THREAD - OPEN ITEMS (insured's CFO and the agency)", PKG_HDR)
    f.kv([("From:", f"{D.CFO} <tlindqvist@cumberlandhearth-example.com>"),
          ("Sent:", "Wednesday, September 30, 2026 7:48 AM"),
          ("To:", D.AGENCY_PRODUCER), ("Cc:", f"{D.CEO}; {D.CONTROLLER}"),
          ("Subject:", "RE: RE: Cumberland Hearth - your open items list")],
         font=SANS, size=7.0, label_w=60)
    f.gap(4)
    f.paras([
        "Caroline - final answers to your list, in your numbering. Where this disagrees with the "
        "worksheet Jordan filled in back in August, this e-mail is right.",
        f"1. Effective date - confirmed {D.PROPOSED_EFF} for all lines, twelve-month term. "
        "Please kill the November 15 date everywhere.",
        "2. Installation / service / repair share - installation, service and repair work is "
        f"{D.INSTALL_PCT} of our TOTAL sales (FY2025: $3.35 million of $18.6 million). Of total "
        f"sales, {D.INSTALL_OFF_PCT} is installation, service or repair done OFF our premises at "
        "customer kitchens; the remaining 1% is bench repair in our own shop. (You may hear '95%' "
        "from Rafael - about 95% of service CALLS are at customer sites; that is a count of calls, "
        "not a share of sales.) Retail walk-in sales at the showroom are about 4% of total sales.",
        f"3. Denise's numbers - her direct line is {C1['phone']} (business). The worksheet shows "
        f"her cell as {D.DENISE_CELL_TYPO}; that is a typo, her cell is {C1['phone2']}. Her second "
        f"e-mail is {C1['email2']} (the payables box). Rafael's second e-mail is {C0['email2']}; "
        f"his desk line {C0['phone2']} is a business line and his primary number is his cell, "
        f"{C0['phone']}.",
        "4. Annual revenues for the location boxes on the application: location 1 (Kellerman) "
        "$15,200,000; location 2 (La Vergne depot) $0 - no sales at the depot; location 3 "
        "(Franklin, the Service Co. office) $3,400,000. Those three add to the $18.6 million.",
        "5. Drones - we sold our DJI drone in June 2025. We do not own, lease or operate any "
        "drones today. We DO hire SkyFrame Imaging, LLC (FAA Part 107 certified) about twice a "
        "year to photograph completed installations for marketing; SkyFrame carries its own "
        "aviation liability insurance.",
        "6. Parent company - we are not a subsidiary of anyone. Margaret holds her 60% through "
        f"the {D.TRUST_NAME}; Owen and I hold the rest personally. The 'Ellison Family Holdings "
        "LLC' on the 2024 application was dissolved in March 2025. The business itself has NOT "
        "been placed in a trust - only Margaret's shares sit in her personal living trust.",
        f"7. Music Row Kitchen Rentals - a 40% minority interest; it is NOT a subsidiary, it buys "
        "its own insurance, and we are not asking you to cover it. Do list it as an other "
        "business venture. Our one subsidiary is the Service Co. (100%).",
        "8. Judgments and liens - we WON a judgment against Two Rivers Catering Co. in 2025 "
        "($22,480, Davidson County Chancery Court) for unpaid invoices; that money is owed TO us. "
        "There is no judgment or lien against Cumberland Hearth. The only filings in our name are "
        "Pinnacle's UCC financing statements on the equipment loan. Question 10 is No.",
        "9. Safety - the safety committee meets QUARTERLY (January, April, July, October). We "
        "stopped monthly meetings in 2023. Lorena Vasquez is our Safety & Compliance Coordinator; "
        "the written program follows OSHA general industry rules and every technician has OSHA "
        "10. Forklift operators are re-certified every year.",
        "10. Chemicals - " + D.Q125["ABC"]["explain"],
        "11. Riverside Bistro Group - yes, they filed Chapter 11 in 2024 and we wrote off a "
        "$14,200 receivable. That was a CUSTOMER's bankruptcy. Same with the combi oven we "
        "repossessed from Gallatin Pike Diner when they stopped paying - we were the one "
        "repossessing.",
        "12. Questions 7 and 9 - Margaret wants to go over those two with our attorney before we "
        "sign anything. Please leave them open; we'll answer them directly on Primble's "
        "questionnaire.",
        "13. Losses - the umbrella has never had a claim (no known losses). For the rest, go by "
        "the loss runs, not by my memory.",
        "Ted",
        f"{D.CFO} | Chief Financial Officer | {D.NAME} | direct {D.CFO_PHONE} | main "
        f"{D.BUS_PHONE} | fax {D.FAX}",
    ], font=SANS, size=7.0)
    f.gap(6)
    quoted = [
        "From: Ted Lindqvist",
        "Sent: Thursday, September 24, 2026 5:20 PM",
        "Subject: RE: Cumberland Hearth - your open items list",
        "Quick one before the full answers: Old Hickory's renewal is 12/1 and Margaret wants",
        "everything on one date - move the proposed effective date from 11/15/2026 to",
        "12/01/2026. More tomorrow.",
        "",
        "From: Caroline Whitlock",
        "Sent: Tuesday, September 22, 2026 11:02 AM",
        "Subject: Cumberland Hearth - your open items list",
        "Ted - thanks for the signed questionnaire. Open items: (1) effective date, (2) install /",
        "service %, (3) Denise's cell, (4) revenue by location, (5) drones, (6) parent company,",
        "(7) Music Row, (8) the judgment on your credit report, (9) safety meetings, (10) the",
        "chemicals detail, (11) the bankruptcy and repossession on the credit file, (12) Q7 and",
        "Q9, (13) losses.",
    ]
    for q in quoted:
        f.line("> " + q, SANS, 6.7)


# ════════════════════════════════════════════════════════════════════════════
# 5. The signed supplemental questionnaire - answers by an X in a column
# ════════════════════════════════════════════════════════════════════════════
def questionnaire_125(f: Flow):
    f.doc("GENERAL INFORMATION SUPPLEMENT - HOSPITALITY TRADES PACKAGE (signed by the insured)",
          PKG_HDR, subtitle="Answer every question. Explain all YES responses. Signed "
                            "09/22/2026 by Margaret A. Ellison, President.")
    Q = D.Q125
    rows = [(Q[c]["n"], Q[c]["q"], Q[c]["answer"]) for c in
            ("AAI", "AAJ", "KAA", "ABC", "AAH", "AAC", "AAD", "KAB", "AAF", "KAK", "KAL",
             "ABB", "KAC", "KAM", "KAN", "KAO")]
    f.xcolumn(rows)
    f.head("DETAIL FOR QUESTIONS 1-15")
    f.line("1a. Parent company name: ____________________   (none - the company is owned by "
           "three shareholders)", SANS, 6.8)
    f.table(["1b. SUBSIDIARY COMPANY NAME", "RELATIONSHIP DESCRIPTION", "% OWNED"],
            [[D.SUB["name"], D.SUB["relationship"], D.SUB["pct"]]],
            [LEFT, 250, 470], font=SANS, size=6.8)
    S = D.SAFETY
    f.line(f"2.  {_tick(S['manual'])} Safety manual   {_tick(S['position'])} Safety position   "
           f"{_tick(S['monthly'])} Monthly meetings   {_tick(S['osha'])} OSHA   "
           f"{_tick(S['other'])} Other: {S['other_text']}", MONO, 6.6)
    f.para("3.  " + D.Q125["ABC"]["explain"], SANS, 6.8)
    f.table(["4. LINE OF BUSINESS", "POLICY NUMBER", "WRITTEN BY"],
            [[D.OTHER_POLICIES[0][0], D.OTHER_POLICIES[0][1], D.CARRIER]],
            [LEFT, 220, 360], font=SANS, size=6.8)
    Cn = D.CANCEL
    f.line(f"5.  {_tick(Cn['nonpayment'])} Non-payment  {_tick(Cn['agent'])} Agent no longer "
           f"represents carrier  {_tick(Cn['nonrenewal'])} Non-renewal  "
           f"{_tick(Cn['underwriting'])} Underwriting  {_tick(Cn['corrected'])} Condition "
           f"corrected  {_tick(Cn['other'])} Other", MONO, 6.4)
    f.para(f"     Condition corrected (describe): {Cn['corrected_text']}. Non-renewed by "
           f"{Cn['carrier']}, policy {Cn['policy']}, effective {Cn['effective']}.", SANS, 6.8)
    f.para("8.  No uncorrected violations. (The 02/11/2026 fire marshal citation at Kellerman "
           "was corrected and passed re-inspection on 03/02/2026 - see the report.)", SANS, 6.8)
    f.para("10. No judgement or lien against the applicant (a judgement in OUR favour against a "
           "customer is not one).", SANS, 6.8)
    f.para("11. No. (Shares held by a shareholder's living trust do not place the business in a "
           "trust.)", SANS, 6.8)
    f.para("12. Imports Italian deck ovens and espresso machines for distribution in the USA.",
           SANS, 6.8)
    f.para("13. " + D.Q125["KAM"]["explain"], SANS, 6.8)
    f.para("14. Drone sold June 2025 - none owned, leased or operated now.", SANS, 6.8)
    f.para("15. " + D.Q125["KAO"]["explain"], SANS, 6.8)
    f.gap(6)
    f.para("Questions 7 and 9: left unanswered by the insured on 09/22/2026 pending review with "
           "counsel (agency note).", SERIF_I, 7.0)
    f.line("Signature: /s/ Margaret A. Ellison      Title: President      Date: 09/22/2026",
           SERIF, 7.4)


# ════════════════════════════════════════════════════════════════════════════
# 6. The premises schedule - abbreviated two-line headers, riffled, footnotes
# ════════════════════════════════════════════════════════════════════════════
def premises_schedule(f: Flow):
    f.doc("SCHEDULE OF PREMISES - FOR THE APPLICATION (location numbers below are the numbers "
          "to be used on this submission)", PKG_HDR)
    xs = [LEFT, 52, 68, 190, 250, 300, 318, 350, 372, 394, 426, 452, 484, 506]
    hdr = [["LOC", "BLD", "STREET", "CITY", "CNTY", "ST", "ZIP", "CITY", "INT", "OCC", "PUB",
            "TOT", "LSD", ""],
           ["#", "#", "", "", "", "", "", "LMTS", "", "SF", "SF", "SF", "TO OTH", ""]]
    rows = []
    for l in D.LOCATIONS:
        street = l["l1"] + (f", {l['l2']}" if l["l2"] else "")
        occ = D.LOC3_STALE_OCCUPIED + "*" if l["num"] == "3" else l["occupied"]
        rows.append([l["num"], l["bldg"], street, l["city"], l["county"], l["state"], l["zip"],
                     "IN" if l["inside"] else "OUT", "OWN" if l["interest"] == "Owner" else "TEN",
                     occ, l["public"], l["total_area"], l["leased"], ""])
    rows.append(["--", "--", f"{D.CLOSED_LOCATION['l1']} - CLOSED 06/30/26 - DELETE",
                 D.CLOSED_LOCATION["city"], "Davidson", "TN", D.CLOSED_LOCATION["zip"], "IN",
                 "TEN", "--", "--", "--", "--", ""])
    f.table(hdr, rows, xs, style="riffled", size=6.3)
    f.head("OPERATIONS AT EACH LOCATION")
    for l in D.LOCATIONS:
        f.para(f"LOC {l['num']} / BLDG {l['bldg']}: {l['ops']}.", SANS, 6.9)
    f.head("FOOTNOTES")
    f.paras([
        f"(1) 6,000 sq ft of the building at location 1 is subleased to {D.SUBLEASE_TENANT} "
        "(area leased to others: YES). The 58,000 sq ft total includes it; the insured occupies "
        "52,000 sq ft, of which the showroom open to the public is 2,400 sq ft.",
        "(2) Location 2 is in unincorporated Rutherford County - OUTSIDE city limits despite the "
        "La Vergne mailing address. The insured leases 12,500 sq ft of a 50,000 sq ft multi-tenant "
        "flex building; no public access.",
        f"(3) * Location 3 occupied area is corrected by lease amendment no. 1 dated 07/01/2026 "
        f"to {L3['occupied']} sq ft; the {D.LOC3_STALE_OCCUPIED} printed above is the "
        f"pre-amendment figure. The reception area open to visitors is {L3['public']} sq ft. "
        f"The building totals {L3['total_area']} sq ft.",
        f"(4) {D.CLOSED_LOCATION['l1']} (former retail outlet) closed {D.CLOSED_LOCATION['closed']}; "
        "the lease was terminated and nothing is stored there. Do not schedule it.",
    ], font=SANS, size=6.6)


# ════════════════════════════════════════════════════════════════════════════
# 7. The HR census - reversed, abbreviated columns; a roster to count against
# ════════════════════════════════════════════════════════════════════════════
_FIRST = ["Aaron", "Bianca", "Carlos", "Dana", "Elijah", "Fatima", "Gavin", "Hannah", "Isaac",
          "Jada", "Kendrick", "Lucia", "Mason", "Nadia", "Oscar", "Paige", "Quentin", "Rosa",
          "Silas", "Tia", "Uriel", "Vera", "Wesley", "Ximena", "Yusuf", "Zoe", "Brandon",
          "Cora", "Desmond", "Elena", "Felix", "Gloria", "Hector", "Imani", "Jonah", "Kayla"]
_LAST = ["Abernathy", "Brooks", "Castillo", "Dunleavy", "Easley", "Farris", "Goins", "Hutchins",
         "Iverson", "Jernigan", "Kimbrough", "Lassiter", "Maddox", "Nunley", "Overby", "Pruitt",
         "Qualls", "Rucker", "Sizemore", "Tidwell", "Upchurch", "Vaughn", "Whitfield", "Yancey",
         "Zeller", "Barnhill", "Crabtree", "Dotson", "Elrod", "Fentress"]
_DEPTS = {"1": ["Warehouse", "Warehouse", "Sales", "Office", "Delivery", "Showroom", "Purchasing"],
          "2": ["Depot"], "3": ["Service Tech", "Service Tech", "Dispatch"]}


def roster():
    rnd = random.Random(1209)
    named = [
        ("Ellison, Margaret A.", "1", "F", "Executive"), ("Lindqvist, Theodore", "1", "F", "Finance"),
        ("Okafor, Denise", "1", "F", "Finance"), ("Quintero, Rafael", "1", "F", "Facilities"),
        ("Vasquez, Lorena", "1", "F", "Safety"), ("Bellweather, Marcus T.", "1", "F", "Delivery"),
        ("Dandekar, Priyanka S.", "1", "F", "Delivery"), ("Szymanski, Gregory L.", "1", "F", "Warehouse"),
        ("Fontenot, Alicia R.", "2", "F", "Depot"), ("O'Rourke, Tamsin E.", "2", "F", "Depot"),
        ("Hollis, Dwayne K.", "3", "F", "Service Tech"),
    ]
    need = {("1", "F"): 41, ("1", "P"): 6, ("2", "F"): 3, ("2", "P"): 0, ("3", "F"): 22, ("3", "P"): 1}
    rows = []
    for nm, loc, st, dept in named:
        rows.append([nm, loc, st, dept])
        need[(loc, st)] -= 1
    k = 0
    for (loc, st), n in need.items():
        for _ in range(n):
            nm = f"{_LAST[(k * 7) % len(_LAST)]}, {_FIRST[(k * 11) % len(_FIRST)]}"
            dept = _DEPTS[loc][k % len(_DEPTS[loc])]
            rows.append([nm, loc, st, dept])
            k += 1
    rnd.shuffle(rows)
    out = []
    for i, (nm, loc, st, dept) in enumerate(rows, start=1):
        yr = 2008 + (i * 3) % 18
        out.append([f"E{1000 + i * 7}", nm, {"1": "KEL", "2": "LAV", "3": "FRK"}[loc],
                    "F/T" if st == "F" else "P/T", dept,
                    f"{(i * 5) % 12 + 1:02d}/{(i * 7) % 27 + 1:02d}/{yr}",
                    "Service Co." if loc == "3" else "Inc."])
    return out


def hr_census(f: Flow):
    f.doc("EMPLOYEE CENSUS AS OF 09/01/2026 - PAYROLL SYSTEM EXPORT (Federal EIN 62-3418806)",
          PKG_HDR)
    f.para("Location codes: KEL = 2850 Kellerman Industrial Pkwy (application location 1); LAV = "
           "410 Industrial Blvd Ste C, La Vergne (location 2); FRK = 1199 Hillsboro Commons Dr Ste "
           "220, Franklin (location 3 - employees of Cumberland Hearth Service Co., LLC). HC = "
           "head count on payroll. TMP = staffing-agency temps on site (not on payroll). TRM = "
           "terminated year to date.", SANS, 6.6)
    f.table(["LOC", "HC", "P/T", "F/T", "TMP", "TRM"],
            [["KEL", "47", "6", "41", D.TEMPS, "3"], ["LAV", "3", "0", "3", "0", "0"],
             ["FRK", "23", "1", "22", "0", "1"], ["ALL", D.HEADCOUNT_TOTAL, "7", "66", D.TEMPS, "4"]],
            [LEFT, 90, 130, 170, 210, 250], size=6.8)
    f.para(f"Temps are supplied October-December by {D.STAFFING} under a services contract and "
           "are paid by the agency. Annual payroll FY2025 (W-2 wages, both companies): "
           f"{D.PAYROLL_TOTAL}.", SANS, 6.6)
    f.head("ACTIVE EMPLOYEES (73)")
    f.table(["EMP #", "NAME", "LOC", "STATUS", "DEPT", "HIRED", "EMPLOYER"], roster(),
            [LEFT, 80, 200, 240, 280, 360, 430], size=6.3)
    f.head("TERMINATED YEAR TO DATE (4)")
    f.table(["NAME", "LOC", "TERMINATED", "REASON"],
            [["Ambrose, Kyle J.", "KEL", D.TERMINATED_DRIVER["terminated"], "Voluntary - relocated"],
             ["Faulk, Brenda", "KEL", "01/31/2026", "Retired (former accounting contact)"],
             ["Pettus, Carl", "KEL", "04/17/2026", "Voluntary"],
             ["Mobley, Shane", "FRK", "06/05/2026", "Involuntary"]],
            [LEFT, 160, 220, 300], size=6.4)


# ════════════════════════════════════════════════════════════════════════════
# 8. Financial statement - $000s; projections and backlog beside the actuals
# ════════════════════════════════════════════════════════════════════════════
def financials(f: Flow):
    f.doc(f"{D.NAME.upper()} AND SUBSIDIARY - CONSOLIDATED REVENUE (UNAUDITED) - in $000s",
          PKG_HDR)
    f.table(["", "FY2023", "FY2024", "FY2025", "FY2026 YTD (8 mo)", "FY2027 PLAN"],
            [["Equipment sales", "10,410", "11,622", "12,905", "8,720", "14,640"],
             ["Parts and supplies", "1,980", "2,190", "2,345", "1,610", "2,610"],
             ["Installation, service and repair", "2,610", "2,988", "3,350", "2,402", "3,850"],
             ["TOTAL REVENUE", "15,000", "16,800", "18,600", "12,732", "21,100"],
             ["  of which retail walk-in (showroom)", "690", "705", "744", "512", "820"]],
            [LEFT, 220, 290, 360, 430, 510], size=6.6)
    f.head("FY2025 REVENUE BY LOCATION ($000s)")
    f.table(["LOCATION", "REVENUE", "NOTE"],
            [["Kellerman (loc 1)", "15,200", "all equipment, parts and showroom sales"],
             ["La Vergne depot (loc 2)", "0", "no sales - storage and parts staging only"],
             ["Franklin - Service Co. (loc 3)", "3,400", "service, installation and repair revenue"],
             ["Total", "18,600", ""]], [LEFT, 220, 300], size=6.6)
    f.paras([
        f"Order backlog at 08/31/2026: {D.BACKLOG}. Total payroll FY2025: {D.PAYROLL_TOTAL}. FY2027 "
        f"plan revenue {D.PROJECTED_REVENUE} assumes the mezzanine expansion is complete.",
        "Installation, service and repair = 18.0% of FY2025 total revenue (3,350 / 18,600). "
        "Retail walk-in = 4.0%.",
        "Bad debt FY2024 includes a $14,200 write-off - Riverside Bistro Group (customer, Chapter 11).",
    ], font=SANS, size=6.6)


# ════════════════════════════════════════════════════════════════════════════
# 9. Corporate records - conversion, shareholders, SOS reports, W-9, credit file
# ════════════════════════════════════════════════════════════════════════════
def corporate(f: Flow):
    f.doc("TENNESSEE SECRETARY OF STATE - ARTICLES OF CONVERSION (excerpt)",
          "STATE OF TENNESSEE - DIVISION OF BUSINESS SERVICES - CERTIFIED COPY")
    f.paras([
        f"1. The name of the converting entity is {D.FORMER_NAME}, a Tennessee limited liability "
        "company organized on March 1, 2009.",
        f"2. The converting entity converts to {D.NAME}, a Tennessee for-profit corporation, "
        f"effective {D.CONVERSION_DATE}. The converted entity is the same entity as the "
        "converting entity; its assets, liabilities, employees, contracts and federal employer "
        "identification number are unchanged, and the business has been in continuous "
        "operation since March 1, 2009.",
        f"3. Secretary of State control number: {D.SOS_CONTROL}. Principal office: "
        f"{L1['l1']}, {L1['city']}, TN {L1['zip']}. Mailing address: {D.MAIL_L1}, "
        f"{D.MAIL_CITY}, TN {D.MAIL_ZIP}.",
    ], font=SERIF, size=7.6)
    f.head("SHAREHOLDER REGISTER AT 01/01/2026")
    f.table(["SHAREHOLDER", "SHARES", "%"],
            [[D.OWNERS[0][0], "6,000", D.OWNERS[0][1]], [D.OWNERS[1][0], "2,500", D.OWNERS[1][1]],
             [D.OWNERS[2][0], "1,500", D.OWNERS[2][1]]], [LEFT, 300, 380], font=SERIF, size=7.2)
    f.para("The corporation has not elected S corporation status and files federal Form 1120 "
           "as a C corporation. Ellison Family Holdings LLC, the former majority holder, was "
           "dissolved on 03/31/2025 and its shares distributed.", SERIF, 7.2)
    f.head("2026 ANNUAL REPORT - LIMITED LIABILITY COMPANY")
    f.kv([("Name", D.SUB["name"]), ("Control number", "000944012"),
          ("Date formed", D.SUB["formed"]), ("Management", "Member-managed"),
          ("Sole member", D.NAME),
          ("Number of members and managers", f"{D.SUB['members']} (the sole member, which "
                                             "manages the company)"),
          ("Principal office", f"{D.SUB['l1']}, {D.SUB['l2']}, {D.SUB['city']}, TN {D.SUB['zip']}"),
          ("Employer identification number", D.SUB["fein"])], font=SERIF, size=7.2, label_w=170)
    f.head("FORM W-9 (Rev. March 2024) - REQUEST FOR TAXPAYER IDENTIFICATION NUMBER")
    f.kv([("1 Name", D.NAME), ("3 Federal tax classification", "[X] C corporation  [ ] S corporation"
                                                                "  [ ] LLC  [ ] Partnership  [ ] Trust"),
          ("5 Address", D.MAIL_L1), ("6 City, state, ZIP", f"{D.MAIL_CITY}, {D.MAIL_STATE} {D.MAIL_ZIP}")],
         font=MONO, size=7.0, label_w=160)
    f.line("Part I  Employer identification number:", MONO, 7.0)
    f.teletype(["62-3418806"])
    f.head("BUSINESS CREDIT FILE (excerpt) - pulled 09/18/2026")
    f.kv([("Subject", f"{D.NAME} (formerly {D.FORMER_NAME})"), ("D-U-N-S", D.DUNS),
          ("TN sales and use tax acct", D.TN_SALES_TAX), ("USDOT", D.USDOT),
          ("TN unemployment acct", D.TN_DOL_ACCT),
          ("UCC filings", "2 - secured party Pinnacle Commerce Bank, N.A. (equipment, fixtures)"),
          ("Suits", "1 - subject is PLAINTIFF: Cumberland Hearth v. Two Rivers Catering Co., "
                    "Davidson Co. Chancery 25-0412-III - judgment for plaintiff $22,480 (2025)"),
          ("Trade notes", "Customer Riverside Bistro Group filed Chapter 11 (2024) - receivable "
                          "written off by subject")], font=MONO, size=6.8, label_w=150)


# ════════════════════════════════════════════════════════════════════════════
# 10. The agency's AMS export - pipe-delimited
# ════════════════════════════════════════════════════════════════════════════
def ams_export(f: Flow):
    f.doc("AMS EXPORT - RIVERBEND INSURANCE PARTNERS - CLIENT CUMBHEA-01 (raw)", PKG_HDR)
    rows = [
        f"CLIENT|CODE={D.AGENCY_AMS_CUSTOMER_ID}|NAME={D.NAME}|DBA=|TYPE=CORP|FEIN={D.FEIN.replace('-', '')}",
        f"CLIENT|MAIL1={D.MAIL_L1}|MAIL2=|CITY={D.MAIL_CITY}|ST={D.MAIL_STATE}|ZIP={D.MAIL_ZIP}",
        f"CLIENT|PHONE={D.BUS_PHONE.replace('-', '')}|FAX={D.FAX.replace('-', '')}|WEB={D.WEBSITE}",
        f"CLIENT|BOR_EFF=07/15/2026|PRIOR_AGENCY={D.PRIOR_AGENCY}|PRIOR_AGY_CODE={D.PRIOR_AGENCY_CODE}"
        f"|PRIOR_AGY_CUSTID={D.PRIOR_AGENCY_CUSTOMER_ID}",
        f"MKT|CARRIER={D.CARRIER}|VIA={D.MGA}|AGY_CODE={D.AGENCY_CARRIER_CODE}|SUB={D.AGENCY_CARRIER_SUBCODE}"
        f"|STATUS=SUBMITTED|EFF={D.PROPOSED_EFF}",
        f"POL|LOB=CGL|CARRIER={D.OHM}|NO=OHM-GL-4471902-25|EFF={D.CUR_EFF}|EXP={D.CUR_EXP}|PREM=38420|STATUS=EXPIRING",
        f"POL|LOB=AUTOB|CARRIER={D.OHM}|NO=OHM-CA-4471903-25|EFF={D.CUR_EFF}|EXP={D.CUR_EXP}|PREM=61775|STATUS=EXPIRING",
        f"POL|LOB=CPKGE|CARRIER={D.MAG}|NO=MUI-CP-0098817-25|EFF={D.CUR_EFF}|EXP={D.CUR_EXP}|PREM=27940|STATUS=EXPIRING",
        f"POL|LOB=UMBRC|CARRIER={D.CXS}|NO=CXS-UMB-220871-25|EFF={D.CUR_EFF}|EXP={D.CUR_EXP}|PREM=9880|STATUS=EXPIRING",
        f"POL|LOB=INMRC|CARRIER={D.CARRIER}|NO=IMF-3318207|EFF=06/15/2026|EXP=06/15/2027|PREM=2140|STATUS=ACTIVE",
        f"POL|LOB=WORK|CARRIER={D.TEM}|NO={D.TEM_POLICY}|EFF=01/01/2026|EXP=01/01/2027|PREM=44810|STATUS=ACTIVE-NOT MARKETED",
        f"CONT|TYPE=INSP|NAME={C0['name']}|PH1={C0['phone']}|PH1TYPE=C|PH2={C0['phone2']}|PH2TYPE=B|EM1={C0['email']}",
        f"CONT|TYPE=ACCT|NAME={C1['name']}|PH1={C1['phone']}|PH1TYPE=B|PH2={D.DENISE_CELL_TYPO}|PH2TYPE=C|EM1={C1['email']}",
        f"NOTE|07/15/2026|BOR received from {D.PRIOR_AGENCY}; book transferred.",
        "NOTE|09/30/2026|Per CFO e-mail: Denise cell corrected; proposed eff now 12/01/2026.",
    ]
    for r in rows:
        f.line(r, MONO, 6.2)


# ════════════════════════════════════════════════════════════════════════════
# 11. The GL supplemental - limits, exposures, products, questions (126)
# ════════════════════════════════════════════════════════════════════════════
def gl_supplemental(f: Flow):
    f.doc("GENERAL LIABILITY SUPPLEMENTAL APPLICATION - HOSPITALITY TRADES PACKAGE", PKG_HDR,
          subtitle="Completed by the agency from the insured's answers; signed by the insured "
                   "09/29/2026.")
    G = D.GL_LIMITS
    f.head("A. COVERAGE AND LIMITS REQUESTED (occurrence form)")
    f.table(["LIMIT", "REQUESTED", "EXPIRING"],
            [["Each occurrence", G["each_occurrence"][0], "$1,000,000"],
             ["General aggregate", G["general_aggregate"][0], "$2,000,000 per policy"],
             ["Aggregate applies", "PER LOCATION (CG 25 04 05 09)", "per policy"],
             ["Products / completed operations aggregate", G["products"][0], "$2,000,000"],
             ["Personal and advertising injury", G["personal_adv"][0], "$1,000,000"],
             ["Damage to premises rented to you", G["rented_premises"][0], G["rented_premises"][1]],
             ["Medical expense (any one person)", G["medical"][0], G["medical"][1]],
             ["Employee benefits liability", G["ebl"][0], "$1,000,000"],
             ["Property damage liability deductible", f"{D.GL_PD_DEDUCTIBLE} per occurrence", "none"],
             ["Bodily injury deductible", "none", "none"]],
            [LEFT, 260, 420], font=SANS, size=6.8)
    f.para(f"Employee benefits: per claim deductible {D.EBL['deductible']}; total employees "
           f"{D.EBL['employees']}; employees covered by benefit plans {D.EBL['covered']} (full time "
           f"only); retroactive date {D.EBL['retro']}.", SANS, 6.8)
    f.para("The kitchen layout design work is covered by a separate claims-made professional "
           "liability policy (retroactive date 03/01/2015) that is NOT part of this submission. "
           "The general liability is written on an occurrence form.", SANS, 6.8)
    f.head("B. CLASSIFICATION AND EXPOSURES - PROPOSED POLICY TERM (estimates)")
    f.table(["LOC", "HAZ", "CLASSIFICATION", "CODE", "BASIS", "EST. EXPOSURE", "TERR"],
            [[h["loc"], h["haz"], h["desc"], h["code"], h["basis"], h["exposure"], h["terr"]]
             for h in D.GL_HAZARDS], [LEFT, 58, 80, 352, 392, 428, 512], style="riffled",
            font=SANS, size=6.5)
    f.para("Basis: S = gross sales, A = area (sq ft), P = payroll. Governing class: 12683. "
           "Rates and premiums: to be quoted by the company.", SANS, 6.6)
    f.head("C. CONTRACTORS - INSTALLATION WORK")
    f.kv([("Paid to subcontractors (FY2025)", D.SUBS_PAID),
          ("Percentage of work subcontracted", D.SUBS_PCT),
          ("Full-time employees", "66"), ("Part-time employees", "7"),
          ("Type of work subcontracted", D.SUBS_WORK)], font=SANS, size=6.9, label_w=190)
    f.head("D. PRODUCTS (products sold under the applicant's own label or imported by it)")
    f.table(["PRODUCT", "GROSS SALES", "UNITS/YR", "MONTHS IN MKT", "EXPECTED LIFE (MO)"],
            [[p["name"], p["sales"], p["units"], p["months"], p["life"]] for p in D.PRODUCTS],
            [LEFT, 300, 370, 430, 500], font=SANS, size=6.5)
    for p in D.PRODUCTS:
        f.para(f"{p['name']} - intended use: {p['use']}; principal components: {p['components']}.",
               SANS, 6.7)
    f.para("All other equipment is distributed under the manufacturers' own labels and "
           "warranties and is not scheduled here.", SANS, 6.7)
    f.head("E. QUESTIONS")
    labels = {
        "GeneralLiabilityLineOfBusiness_Question_AAHCode_A": "Any product, work, accident or location excluded, uninsured or self-insured from any previous coverage?",
        "GeneralLiabilityLineOfBusiness_Question_AAICode_A": "Was tail coverage purchased under any previous policy?",
        "Contractors_Question_AABCode_A": "Does applicant draw plans, designs or specifications for others?",
        "Contractors_Question_AAICode_A": "Do any operations include blasting or utilize or store explosive material?",
        "Contractors_Question_AACCode_A": "Any excavation, tunneling, underground work or earth moving?",
        "Contractors_Question_ABBCode_A": "Do subcontractors carry coverages or limits less than the applicant?",
        "Contractors_Question_AADCode_A": "Are subcontractors allowed to work without providing a certificate of insurance?",
        "Contractors_Question_AAECode_A": "Does applicant lease equipment to others with or without operators?",
        "GeneralLiabilityLineOfBusiness_Question_AAJCode_A": "Does applicant install, service or demonstrate products?",
        "GeneralLiabilityLineOfBusiness_Question_ABACode_A": "Foreign products sold, distributed, used as components?",
        "GeneralLiabilityLineOfBusiness_Question_ABBCode_A": "Research and development conducted or new products planned?",
        "GeneralLiabilityLineOfBusiness_Question_ABCCode_A": "Guarantees, warranties, hold harmless agreements?",
        "GeneralLiabilityLineOfBusiness_Question_ABDCode_A": "Products related to the aircraft / space industry?",
        "GeneralLiabilityLineOfBusiness_Question_ABECode_A": "Products recalled, discontinued, changed?",
        "GeneralLiabilityLineOfBusiness_Question_ABFCode_A": "Products of others sold or repackaged under applicant label?",
        "GeneralLiabilityLineOfBusiness_Question_ABGCode_A": "Products under label of others?",
        "GeneralLiabilityLineOfBusiness_Question_ABHCode_A": "Vendors coverage required?",
        "GeneralLiabilityLineOfBusiness_Question_ABICode_A": "Does any named insured sell to other named insureds?",
        "GeneralLiabilityLineOfBusiness_Question_ABJCode_A": "Any medical facilities provided or medical professionals employed or contracted?",
        "GeneralLiabilityLineOfBusiness_Question_ACACode_A": "Any exposure to radioactive / nuclear materials?",
        "GeneralLiabilityLineOfBusiness_Question_ACJCode_A": "Do operations involve storing, treating, discharging, applying, disposing or transporting hazardous material?",
        "GeneralLiabilityLineOfBusiness_Question_ACBCode_A": "Any operations sold, acquired or discontinued in the last five years?",
        "GeneralLiabilityLineOfBusiness_Question_ACCCode_A": "Do you rent or loan equipment to others?",
        "Contractors_Question_AAHCode_A": "Any watercraft, docks, floats owned, hired or leased?",
        "GeneralLiabilityLineOfBusiness_Question_ACDCode_A": "Any parking facilities owned / rented?",
        "GeneralLiabilityLineOfBusiness_Question_KAGCode_A": "Is a fee charged for parking?",
        "GeneralLiabilityLineOfBusiness_Question_ACECode_A": "Recreation facilities provided?",
        "GeneralLiabilityLineOfBusiness_Question_KAACode_A": "Any lodging operations, including apartments?",
        "GeneralLiabilityLineOfBusiness_Question_KAHCode_A": "Is there a swimming pool on the premises?",
        "GeneralLiabilityLineOfBusiness_Question_ACFCode_A": "Are social events sponsored?",
        "GeneralLiabilityLineOfBusiness_Question_KABCode_A": "Are athletic teams sponsored?",
        "GeneralLiabilityLineOfBusiness_Question_ACGCode_A": "Any structural alterations contemplated?",
        "GeneralLiabilityLineOfBusiness_Question_ACHCode_A": "Any demolition exposure contemplated?",
        "GeneralLiabilityLineOfBusiness_Question_AABCode_A": "Has applicant been active in, or is it currently active in, joint ventures?",
        "GeneralLiabilityLineOfBusiness_Question_AACCode_A": "Do you lease employees to or from other employers?",
        "GeneralLiabilityLineOfBusiness_Question_AADCode_A": "Is there a labor interchange with any other business or subsidiaries?",
        "GeneralLiabilityLineOfBusiness_Question_AAFCode_A": "Have any crimes occurred or been attempted on your premises within the last three years?",
        "Contractors_Question_AAGCode_A": "Is there a formal, written safety and security policy in effect?",
    }
    n = 0
    blank_nums = []
    for code, (ans, _fld, expl) in D.Q126.items():
        if code not in labels:
            continue            # AAE and the GL AAG were never asked on this supplement
        n += 1
        shown = {"Y": "YES", "N": "NO", "": "____"}[ans]
        if not ans:
            blank_nums.append(f"E{n:02d}")
        f.para(f"E{n:02d}. {labels[code]}  ANSWER: {shown}" + (f" - {expl}." if expl else ""),
               SANS, 6.7)
    f.para(f"{', '.join(blank_nums)} were left blank by the insured (the agency will follow up).",
           SERIF_I, 6.8)
    f.head("F. ATHLETIC TEAMS, LOANED EQUIPMENT, LEASED WORKERS")
    T = D.ATHLETIC_TEAM
    f.kv([("Sport", T["sport"]), ("Contact sport", "No"), ("Age group", "Over 18"),
          ("Extent of sponsorship", T["extent"]),
          ("Equipment loaned or rented", D.LOANER["desc"] + " - large equipment, not small tools"),
          ("Instructions given on use", "Yes - operating instructions are given to the "
                                        "customer's staff at delivery"),
          ("Leased employees", f"None. Seasonal temporary workers from {D.STAFFING} are "
                               "temporary workers, not leased employees.")],
         font=SANS, size=6.8, label_w=150)
    f.head("G. ADDITIONAL INSURED REQUIRED BY CONTRACT")
    A = D.LANDLORD_AI
    f.para(f"Landlord - {A['name']}, {A['l1']}, {A['l2']}, {A['city']}, {A['state']} {A['zip']} - "
           f"as additional insured as respects the {A['item'].lower()} (location {A['loc']}, "
           "building 1); the lease requires a certificate of insurance. The location 3 landlord "
           "does not require additional insured status.", SANS, 6.8)
    f.head("H. REMARKS FOR THE GENERAL LIABILITY SECTION")
    f.para(D.GL_REMARKS, SANS, 6.8)


# ════════════════════════════════════════════════════════════════════════════
# 12. Products - spec sheets, private label, an Italian invoice, a recall memo
# ════════════════════════════════════════════════════════════════════════════
def products(f: Flow):
    f.doc("PRODUCT FILE - SPECIFICATION SHEETS, PRIVATE LABEL AGREEMENT, IMPORT INVOICE", PKG_HDR,
          )
    P = D.PRODUCTS
    f.head("CHHS PROCLEAN - PRIVATE-LABEL HEAVY DUTY DEGREASER AND OVEN CLEANER")
    f.kv([("Manufactured for", D.NAME), ("Manufactured by", "Delta Chem Blending, Inc., Memphis, TN"),
          ("Composition", "Sodium hydroxide 10-20%; nonionic surfactants 1-5%; water"),
          ("Hazard class", "Corrosive (pH 13.5) - Signal word: DANGER"),
          ("Package", "1 gallon jug (4 per case) and 55 gallon drum"),
          ("Shelf life", "24 months from blend date"), ("On the market since", "April 2022"),
          ("FY2025 units / sales", f"{P[0]['units']} gallons / {P[0]['sales']}")],
         font=MONO, size=6.8, label_w=150)
    f.head("PRIVATE LABEL SUPPLY AGREEMENT (excerpt) - Delta Chem Blending, Inc. and the applicant")
    f.para("Section 4. Blender shall manufacture the Product to the Specification and package it "
           "under Distributor's CHHS ProClean label. Section 9. Blender shall indemnify and hold "
           "harmless Distributor against claims arising from defects in formulation or "
           "manufacture, and shall name Distributor as additional insured (vendors) on "
           "Blender's products liability insurance with limits of not less than $2,000,000.",
           SERIF, 7.0)
    f.head("FORNI LOMBARDI S.r.l. - FATTURA / COMMERCIAL INVOICE No. FL-2026/0418")
    f.kv([("Data / Date", "15/03/2026 (dd/mm/yyyy)"), ("Origine / Origin", "Bergamo, Italia"),
          ("Destinatario / Consignee", f"{D.NAME}, {L1['l1']}, Nashville TN 37211 USA"),
          ("Merce / Goods", "6 x forno a gas a platea 'Lombardi DP-120' - gas deck pizza ovens"),
          ("Totale / Total", "€ 48.750,00 (EUR, Incoterms FCA Genova)"),
          ("HS code", "8419.81"), ("Warranty", "24 months parts; labor by the importer")],
         font=MONO, size=6.8, label_w=150)
    f.para(f"Imported deck ovens on the US market since {P[1]['months']} months ago; expected useful "
           f"life {P[1]['life']} months. Vettore espresso machines (Macchine Caffe Vettore S.p.A., "
           f"Milan) on the market for {P[2]['months']} months.", SANS, 6.8)
    f.head("MEMO - DISCONTINUED PRODUCT LINE (03/11/2024)")
    f.para("Effective immediately we discontinue the Volunteer Grill gas griddle line following "
           "the manufacturer's voluntary recall (CPSC recall no. 24-118, gas valve). Unsold units "
           "(22) are returned to the manufacturer; installed units are being retrofitted by the "
           "manufacturer's field team. No injuries have been reported to us.", SANS, 6.8)


# ════════════════════════════════════════════════════════════════════════════
# 13. Subcontractors and certificates; 14. loaner log; 15. safety program
# ════════════════════════════════════════════════════════════════════════════
def subcontractors(f: Flow):
    f.doc("SUBCONTRACTOR SUMMARY AND CERTIFICATE OF INSURANCE TRACKING LOG", PKG_HDR)
    f.para("Policy: no subcontractor starts work without a current certificate of insurance on "
           "file - there are no exceptions. Subcontractors must carry general liability of "
           "$1,000,000 each occurrence / $2,000,000 aggregate, auto liability $1,000,000 and "
           "statutory workers compensation, and must name the applicant as additional insured. "
           "Umbrella coverage is NOT required of subcontractors, so their total limits are lower "
           "than the applicant's.", SANS, 6.9)
    f.table(["SUBCONTRACTOR", "TRADE", "GL OCC / AGG", "UMB", "COI EXP", "COI BEFORE START", "PAID FY25"],
            [["Bellevue Electric Co.", "Electrical", "$1M / $2M", "none", "04/30/2027", "Y", "$268,400"],
             ["Rutledge Plumbing & Gas, LLC", "Gas / plumbing", "$1M / $2M", "none", "02/28/2027", "Y",
              "$143,600"], ["TOTAL", "", "", "", "", "", D.SUBS_PAID]],
            [LEFT, 170, 240, 310, 340, 400, 480], size=6.4)
    f.para(f"Work subcontracted: {D.SUBS_WORK}. Percentage of work subcontracted: {D.SUBS_PCT}.",
           SANS, 6.9)


def loaner_log(f: Flow):
    f.doc("LOANER EQUIPMENT LOG - UNITS LENT TO SERVICE CUSTOMERS", PKG_HDR)
    rows = []
    for i, s in enumerate(D.job_sites()[:18]):
        unit = ["Combi oven 10-pan", "Reach-in refrigerator 2-door", "Combi oven 6-pan",
                "Reach-in freezer 1-door"][i % 4]
        rows.append([f"LN-{2600 + i}", unit, s["customer"], f"{(i % 9) + 1:02d}/{(i * 3) % 27 + 1:02d}/2026",
                     f"{(i % 12) + 3} days", "Y"])
    f.table(["LOAN #", "UNIT", "CUSTOMER", "OUT", "DURATION", "INSTRUCTED"], rows,
            [LEFT, 90, 220, 380, 430, 490], size=6.3)
    f.para("Units are delivered and picked up by our technicians; no operator is provided; the "
           "customer's kitchen staff are shown how to operate the unit at delivery.", SANS, 6.7)


def safety_program(f: Flow):
    f.doc("WRITTEN SAFETY AND SECURITY PROGRAM - EXCERPT (rev. 01/2026)", PKG_HDR)
    f.paras([
        f"1.1 Responsibility. {D.SAFETY_COORD}, Safety & Compliance Coordinator, administers this "
        "program for both companies and reports to the President.",
        "1.2 Standards. The program follows OSHA 29 CFR 1910 (general industry) and the "
        "applicable parts of 29 CFR 1926 for installation work. All technicians complete the "
        "OSHA 10-hour course within 90 days of hire.",
        "1.3 Safety committee. The committee meets quarterly - in January, April, July and "
        "October. (Monthly meetings were held until 2023 and were replaced by the quarterly "
        "committee.)",
        "1.4 Powered industrial trucks. Forklift operators are evaluated and re-certified "
        "annually.",
        "1.5 Chemical storage. Propane cylinders: exterior locked cage, maximum twelve 33-lb "
        "cylinders. Degreaser concentrate: sealed drums in the bunded chemical room.",
        "2.1 Security. Intrusion alarm with central-station monitoring at all three locations; "
        "cameras; key-card access; gated and fenced vehicle yards.",
    ], font=SERIF, size=7.2)


# ════════════════════════════════════════════════════════════════════════════
# 16. Fire marshal and roof; 17. non-renewal and a RESCINDED cancellation
# ════════════════════════════════════════════════════════════════════════════
def fire_and_roof(f: Flow):
    f.doc("METRO NASHVILLE FIRE MARSHAL - INSPECTION REPORT", "FIRE MARSHAL'S OFFICE - "
          "COMMERCIAL INSPECTION")
    f.kv([("Premises", f"{L1['l1']}, Nashville TN {L1['zip']}"),
          ("Occupant", D.NAME), ("Inspection date", "02/11/2026"),
          ("Violation 1", "Rear warehouse egress door blocked by pallets (IFC 1031.2)"),
          ("Violation 2", "Portable fire extinguisher inspection tags expired (IFC 906.2)"),
          ("Re-inspection", "03/02/2026 - PASSED"),
          ("Status", "CORRECTED - no outstanding violations")], font=MONO, size=7.0, label_w=130)
    f.head("VOLUNTEER ROOFING & SHEET METAL - LETTER OF COMPLETION")
    f.para(f"April 18, 2025. Re: {L1['l1']}, Nashville. We have completed the full replacement "
           "of the roof with a new 60-mil TPO membrane over new insulation, including the "
           "rooftop unit curbs. The work was completed on 04/18/2025 and carries a 20-year "
           "manufacturer's warranty.", SERIF, 7.2)


def notices(f: Flow):
    f.doc(f"{D.VFM.upper()} - NOTICE OF NONRENEWAL", f"{D.VFM}  |  NAIC {D.VFM_NAIC}")
    f.kv([("Date mailed", "09/30/2024"), ("Policy", D.CANCEL["policy"]),
          ("Named insured", D.NAME), ("Expiration / nonrenewal effective", D.CANCEL["effective"]),
          ("Reason", "Underwriting - the roof at 2850 Kellerman Industrial Pkwy exceeds 25 years "
                     "of age and sustained hail damage on 07/22/2023; the risk no longer meets our "
                     "underwriting guidelines for this class.")], font=MONO, size=6.9, label_w=170)
    f.doc(f"{D.OHM.upper()} - NOTICE OF CANCELLATION FOR NONPAYMENT OF PREMIUM", OHM_HDR)
    f.kv([("Date", "03/02/2023"), ("Policy", "OHM-CA-4471903-22 (business auto)"),
          ("Named insured", D.FORMER_NAME + " (now " + D.NAME + ")"),
          ("Cancellation effective", "03/20/2023 at 12:01 a.m.")], font=MONO, size=6.9, label_w=170)
    f.head("RESCISSION OF NOTICE OF CANCELLATION - 03/14/2023")
    f.para("The premium due was received on 03/13/2023. The notice of cancellation dated "
           "03/02/2023 is RESCINDED. No cancellation took effect and coverage continued without "
           "interruption.", MONO, 6.9)


# ════════════════════════════════════════════════════════════════════════════
# 18. Leases and the mortgage loan
# ════════════════════════════════════════════════════════════════════════════
def leases_and_loan(f: Flow):
    A = D.LANDLORD_AI
    M = D.MORTGAGEE
    f.doc("LEASE ABSTRACT - LOCATION 2 (La Vergne)", PKG_HDR)
    f.kv([("Landlord", f"{A['name']}, {A['l1']}, {A['l2']}, {A['city']}, {A['state']} {A['zip']}"),
          ("Tenant", D.NAME), ("Premises", f"{L2['l1']}, {L2['l2']}, {L2['city']}, TN {L2['zip']}"),
          ("Rentable area", f"{L2['occupied']} sq ft of a {L2['total_area']} sq ft multi-tenant building"),
          ("Jurisdiction", "Unincorporated Rutherford County (outside the La Vergne city limits)"),
          ("Term", "05/01/2022 - 04/30/2029"),
          ("Insurance", "Tenant shall name Landlord as additional insured on its commercial "
                        "general liability policy and deliver a certificate of insurance.")],
         font=SERIF, size=7.0, label_w=120)
    f.doc("LEASE ABSTRACT - LOCATION 3 (Franklin) WITH AMENDMENT NO. 1", PKG_HDR)
    f.kv([("Landlord", f"{D.LOC3_LANDLORD}, 1199 Hillsboro Commons Dr, Suite 100, Franklin, TN 37067"),
          ("Tenant", f"{D.SUB['name']} (guaranteed by {D.NAME})"),
          ("Premises", f"{L3['l1']}, {L3['l2']}"),
          ("Original area", f"{D.LOC3_STALE_OCCUPIED} rentable sq ft"),
          ("Amendment no. 1 (07/01/2026)", f"Suite 220 reconfigured; premises reduced to "
                                           f"{L3['occupied']} rentable sq ft, including a {L3['public']} "
                                           "sq ft reception area open to visitors"),
          ("Building", f"{L3['total_area']} sq ft, three stories, inside the Franklin city limits"),
          ("Insurance", "Tenant carries CGL $1,000,000 / $2,000,000; additional insured status is "
                        "not required")], font=SERIF, size=7.0, label_w=120)
    f.doc(f"{M['name'].upper()} - COMMERCIAL MORTGAGE LOAN SUMMARY", "PINNACLE COMMERCE BANK - "
          "LOAN SERVICING")
    f.kv([("Borrower", D.NAME), ("Loan number", M["loan_no"]),
          ("Loan amount", f"{M['amount']} (original principal)"),
          ("Balance at 09/01/2026", D.LOAN_BALANCE_DECOY), ("Maturity", M["end"]),
          ("Collateral", f"Land and building, {L1['l1']}, Nashville TN (application location "
                         f"{M['loc']}, building {M['bldg']}); appraised value {D.BUILDING_VALUE_LOC1}"),
          ("Lien position", "First mortgage (rank 1)"),
          ("Mortgagee clause", f"{M['name']}, its successors and/or assigns (ISAOA/ATIMA)"),
          ("Insurance tracking", f"{M['l1']}, {M['l2']}, {M['city']}, {M['state']} {M['zip']} - phone "
                                 f"{M['phone']} - fax {M['fax']} - {M['email']}"),
          ("Evidence required", "A copy of the policy with the mortgagee endorsement is required; "
                                "a certificate of insurance alone is NOT acceptable."),
          ("Billing", "Do not send premium bills to the bank.")], font=MONO, size=6.8, label_w=150)


# ════════════════════════════════════════════════════════════════════════════
# 19-20. The incumbent's GL and auto declarations (teletype, schedules)
# ════════════════════════════════════════════════════════════════════════════
def gl_declarations(f: Flow):
    f.doc("OLD HICKORY MUTUAL - COMMERCIAL GENERAL LIABILITY DECLARATIONS", OHM_HDR)
    f.teletype(["COMMERCIAL GENERAL LIABILITY DECS", "POLICY NO OHM-GL-4471902-25",
                "RENEWAL OF OHM-GL-4471902-24"])
    f.kv([("Named insured", f"{D.NAME}; {D.SUB['name']}"),
          ("Mailing address", f"{D.MAIL_L1}, {D.MAIL_CITY}, {D.MAIL_STATE} {D.MAIL_ZIP}"),
          ("Policy period", f"{D.CUR_EFF} to {D.CUR_EXP}"),
          ("Company", f"{D.OHM} (NAIC {D.OHM_NAIC})"),
          ("Agent", f"{D.PRIOR_AGENCY} - agency code {D.PRIOR_AGENCY_CODE} - {D.PRIOR_AGENCY_PHONE}"),
          ("Form of business", "Corporation"),
          ("Premium audit", "Semi-annual"),
          ("Billing", "Agency bill - 10 installments")], font=MONO, size=6.9, label_w=140, leader=True)
    f.head("LIMITS OF INSURANCE")
    f.table(["COVERAGE", "LIMIT"],
            [["Each occurrence", "$1,000,000"], ["General aggregate (per policy)", "$2,000,000"],
             ["Products-completed operations aggregate", "$2,000,000"],
             ["Personal and advertising injury", "$1,000,000"],
             ["Damage to premises rented to you", "$100,000"], ["Medical expense", "$5,000"]],
            [LEFT, 300], size=6.8)
    f.head("SCHEDULE OF HAZARDS - EXPIRING TERM")
    rows = [[h["loc"], h["code"], h["desc"], f"({h['basis'].lower()})", h["exp_exposure"], h["terr"],
             h["rate"], h["premium"]] for h in D.GL_HAZARDS]
    f.table(["LOC", "CLASS", "DESCRIPTION", "BASIS", "EXPOSURE", "TERR", "RATE", "PREMIUM"], rows,
            [LEFT, 58, 96, 330, 360, 420, 456, 500], size=6.2)
    f.para("(s) gross sales per $1,000; (a) area per 1,000 sq ft; (p) payroll per $1,000. "
           "Location numbers on this schedule follow the insured's prior location list.", MONO, 6.2)
    f.kv([("Total advance premium", "$38,420"), ("Minimum premium", "$9,605")], font=MONO,
         size=6.9, label_w=140)
    f.head("EMPLOYEE BENEFITS LIABILITY COVERAGE ENDORSEMENT")
    f.kv([("Each employee limit", "$1,000,000"), ("Aggregate limit", "$3,000,000"),
          ("Deductible each employee", "$1,000"), ("Retroactive date", D.EBL["retro"])],
         font=MONO, size=6.9, label_w=140)
    f.head("FORMS AND ENDORSEMENTS")
    f.para("CG 00 01 04 13  CG 21 06 05 14  CG 21 47 12 07  CG 20 10 04 13  CG 20 37 04 13  "
           "CG 21 67 12 04  IL 00 17 11 98  IL 00 21 09 08  OHM-EBL-01 (01/20)", MONO, 6.6)


def auto_declarations(f: Flow):
    f.doc("OLD HICKORY MUTUAL - BUSINESS AUTO DECLARATIONS", OHM_HDR)
    f.teletype(["BUSINESS AUTO DECLARATIONS", "POLICY NO OHM-CA-4471903-25"])
    f.kv([("Named insured", f"{D.NAME}; {D.SUB['name']}"),
          ("Policy period", f"{D.CUR_EFF} to {D.CUR_EXP}"),
          ("USDOT", D.USDOT), ("Agent", f"{D.PRIOR_AGENCY} ({D.PRIOR_AGENCY_CODE})")],
         font=MONO, size=6.9, label_w=140, leader=True)
    f.head("COVERED AUTO SYMBOLS")
    f.table(["COVERAGE", "SYMBOL", "LIMIT"],
            [["Liability", "1", "$1,000,000 CSL"], ["Medical payments", "2", "$5,000"],
             ["Uninsured motorists", "2", "$1,000,000"], ["Underinsured motorists", "2", "$1,000,000"],
             ["Comprehensive", "7", "see schedule"], ["Collision", "7", "see schedule"],
             ["Rental reimbursement", "7", "$75/day / 30 days"], ["Hired auto liability", "8", "$1,000,000"],
             ["Non-owned auto liability", "9", "$1,000,000"]], [LEFT, 200, 260], size=6.6)
    f.head("SCHEDULE OF COVERED AUTOS AS OF 12/01/2025")
    rows = []
    sched = [v for v in D.VEHICLES if v["num"] != "3"]
    for v in sched:
        rows.append([v["num"], v["year"], f"{v['make']} {v['model']}", v["body"], v["vin"], v["gvw"],
                     v["cost"], v["cls"], v["terr"], "COMM" if v["use"] == "Commercial" else "SERV",
                     v["radius"], f"LOC {v['loc']}", v["premium"]])
    rows.append(["5", D.SOLD_VEHICLE["year"], "Ford E-350", "Cargo Van", D.SOLD_VEHICLE["vin"], "9,500",
                 "$34,180", "01499", "104", "SERV", "50", "LOC 1", "$7,880"])
    f.table(["VEH", "YR", "MAKE/MODEL", "BODY", "VIN", "GVW", "COST NEW", "CLASS", "TERR", "USE",
             "RAD", "GAR", "PREM"], rows,
            [LEFT, 52, 70, 140, 196, 284, 314, 352, 384, 410, 436, 456, 486], size=5.9)
    f.para("Garaging: LOC 1 = 2850 Kellerman Industrial Pkwy, Nashville, Davidson County, TN 37211; "
           "LOC 2 = 410 Industrial Blvd, Suite C, La Vergne, Rutherford County, TN 37086; LOC 3 = "
           "1199 Hillsboro Commons Dr, Suite 220, Franklin, Williamson County, TN 37067. All "
           "vehicles registered in Tennessee. USE: COMM = commercial, SERV = service. RAD = radius "
           "in miles.", MONO, 6.3)
    f.head("PHYSICAL DAMAGE BY VEHICLE (expiring)")
    pd = []
    for v in sched:
        coll = D.V4_EXPIRING_COLL_DED if v["num"] == "4" else v["coll_ded"]
        pd.append([v["num"], "ACV", v["comp_ded"], coll, "Y" if v["rental"] else "N", "N"])
    f.table(["VEH", "VALUATION", "COMP DED", "COLL DED", "RENTAL", "TOWING"], pd,
            [LEFT, 70, 130, 200, 270, 320], size=6.4)
    f.head("LOSS PAYEES / LIENHOLDERS")
    for a in D.AUTO_AI:
        addr = a["l1"] + (f", {a['l2']}" if a["l2"] else "")
        f.para(f"Vehicle {a['veh']}: {a['name']} - {a['type'].upper()} (rank {a['rank']}) - {addr}, "
               f"{a['city']}, {a['state']} {a['zip']} - account {a['acct']} - certificate required.",
               MONO, 6.4)
    f.head("DRIVE OTHER CAR - BROADENED COVERAGE FOR NAMED INDIVIDUALS (CA 99 10)")
    f.para(f"Named individual: {D.CEO}. (Ms. Ellison does not drive company vehicles.)", MONO, 6.4)
    f.kv([("Total auto premium", "$61,775")], font=MONO, size=6.9, label_w=140)
    f.head("ENDORSEMENT 1 - EFFECTIVE 03/09/2026 - ADD COVERED AUTO")
    v = D.VEHICLES[2]
    f.para(f"Add vehicle {v['num']}: {v['year']} {v['make']} {v['model']}, {v['body']}, VIN {v['vin']}, "
           f"GVW {v['gvw']}, cost new {v['cost']}, class {v['cls']}, territory {v['terr']}, use "
           f"SERVICE, radius {v['radius']}, garaged LOC 3, comp ded {v['comp_ded']}, coll ded "
           f"{v['coll_ded']}, ACV, no rental, no towing. Additional premium {v['premium']} "
           "pro rata.", MONO, 6.4)
    f.head("ENDORSEMENT 2 - EFFECTIVE 05/22/2026 - DELETE COVERED AUTO")
    f.para(f"Delete vehicle 5: {D.SOLD_VEHICLE['year']} Ford E-350, VIN {D.SOLD_VEHICLE['vin']} - sold "
           f"{D.SOLD_VEHICLE['sold']}. Return premium $3,120.", MONO, 6.4)
    f.head("VALUATION REPORT - CURRENT ACTUAL CASH VALUE (for information)")
    f.table(["VEH", "ACV 09/2026"], [[x["num"], x["acv_decoy"]] for x in D.VEHICLES],
            [LEFT, 90], size=6.4)


# ════════════════════════════════════════════════════════════════════════════
# 21. The auto supplemental (127)
# ════════════════════════════════════════════════════════════════════════════
def auto_supplemental(f: Flow):
    f.doc("BUSINESS AUTO SUPPLEMENTAL APPLICATION", PKG_HDR,
          subtitle="Signed by the insured 09/29/2026.")
    f.head("A. VEHICLES REQUESTED (see the expiring schedule; changes below)")
    rows = []
    for v in D.VEHICLES:
        cov = "LIAB MP UM UIM COMP COLL" + (" RENT" if v["rental"] else "") + (" TOW" if v["towing"] else "")
        rows.append([v["num"], f"{v['year']} {v['make']} {v['model']}", v["use"].upper(), v["radius"],
                     v["comp_ded"], v["coll_ded"], cov])
    f.table(["VEH", "VEHICLE", "USE", "RADIUS", "COMP", "COLL", "COVERAGES REQUESTED"], rows,
            [LEFT, 60, 200, 260, 300, 340, 384], size=6.3)
    f.para("Valuation: actual cash value on all vehicles. No full glass, no no-fault, no specified "
           "causes of loss. Covered auto symbols as expiring. All four vehicles are commercial "
           "vehicles (trucks and vans); none is a private passenger type. All are registered in TN.",
           SANS, 6.7)
    f.head("B. SPECIAL EQUIPMENT")
    for e in D.SPECIAL_EQUIPMENT:
        f.para(f"Vehicle {e['veh']}: {e['desc']} - cost {e['cost']}.", SANS, 6.8)
    f.head("C. QUESTIONS")
    labels = {
        "CommercialVehicleLineOfBusiness_Question_AAJCode_A": "With the exception of encumbrances, are any vehicles not solely owned by and registered to the applicant?",
        "CommercialVehicleLineOfBusiness_Question_ABACode_A": "Do over 50% of the employees use their own autos in the business?",
        "CommercialVehicleLineOfBusiness_Question_KADCode_A": "Is there a vehicle maintenance program in operation?",
        "CommercialVehicleLineOfBusiness_Question_ABCCode_A": "Are any vehicles leased to others?",
        "CommercialVehicleLineOfBusiness_Question_AAGCode_A": "Are any vehicles customized, altered or have special equipment?",
        "CommercialVehicleLineOfBusiness_Question_AAECode_A": "Are ICC, PUC or other filings required?",
        "CommercialVehicleLineOfBusiness_Question_AAFCode_A": "Do operations involve transporting hazardous material?",
        "CommercialVehicleLineOfBusiness_Question_AABCode_A": "Any hold harmless agreements?",
        "CommercialVehicleLineOfBusiness_Question_AACCode_A": "Any vehicles used by family members?",
        "CommercialVehicleLineOfBusiness_Question_KAECode_A": "Does the applicant obtain MVR verifications?",
        "CommercialVehicleLineOfBusiness_Question_KAFCode_A": "Does the applicant have a specific driver recruiting method?",
        "CommercialVehicleLineOfBusiness_Question_AAHCode_A": "Are any drivers not covered by workers compensation?",
        "CommercialVehicleLineOfBusiness_Question_AADCode_A": "Any vehicles owned but not scheduled on this application?",
        "CommercialVehicleLineOfBusiness_Question_AAICode_A": "Any drivers with convictions for moving traffic violations in the past 3 years?",
        "CommercialVehicleLineOfBusiness_Question_ABBCode_A": "Has the agent inspected the vehicles?",
        "CommercialVehicleLineOfBusiness_KAHCode_A": "Do you have electronic monitoring devices that record and transmit data in any of your vehicles?",
    }
    n = 0
    for code, (ans, _fld, expl) in D.Q127.items():
        if code not in labels:
            continue
        n += 1
        shown = {"Y": "Y", "N": "N", "": "_"}[ans]
        f.para(f"C{n:02d} [{shown}] {labels[code]}" + (f" {expl}." if expl else ""), SANS, 6.7)
    f.para("Federal / state filings: none - private carrier of its own goods; the USDOT number is "
           "held but no MCS-90 or BMC-91 filing applies. Forklifts are mobile equipment, not autos. "
           "All vehicles are titled and registered to the applicant; vehicles 1 and 4 are financed "
           "(encumbrances only).", SANS, 6.7)
    C = D.CONVICTION
    f.para(f"Conviction: driver {C['driver']} (Dwayne K. Hollis) - {C['desc']} on {C['date']} in "
           f"{C['place']}. No other moving violations for listed drivers in the past {C['years']} "
           "years.", SANS, 6.7)
    T = D.TELEMATICS
    f.head("D. ELECTRONIC MONITORING")
    f.line(f"Fleet monitored: {T['pct']}   {_tick(T['driver_safety'])} Driver safety   "
           f"{_tick(T['fuel'])} Fuel consumption   {_tick(T['maintenance'])} Vehicle maintenance   "
           f"{_tick(T['mileage'])} Mileage   {_tick(T['location'])} Location tracking   "
           f"{_tick(T['navigation'])} Navigation   {_tick(T['other'])} Other: {T['other_text']}",
           MONO, 6.2)
    f.para(T["additional"] + ".", SANS, 6.7)
    f.head("E. GARAGING, STORAGE AND MAXIMUM EXPOSURE")
    f.para(D.GARAGE_STORAGE + ". Maximum value of vehicles at any one location (Kellerman yard, "
           f"vehicles 1 and 4, cost new): {D.MAX_EXPOSURE}.", SANS, 6.8)
    f.head("F. REMARKS")
    f.para(D.AUTO_REMARKS, SANS, 6.8)


# ════════════════════════════════════════════════════════════════════════════
# 22. Drivers - roster (YYYYMMDD dates), MVRs, vehicle assignment
# ════════════════════════════════════════════════════════════════════════════
_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _ymd(d):          # 06/11/1984 -> 19840611
    m, dd, y = d.split("/")
    return f"{y}{m}{dd}"


def _dmy(d):          # 04/06/2015 -> 06-Apr-2015
    m, dd, y = d.split("/")
    return f"{dd}-{_MON[int(m) - 1]}-{y}"


def drivers(f: Flow):
    f.doc("AUTHORIZED DRIVER ROSTER - HR (09/2026)", PKG_HDR)
    rows = []
    for d in D.DRIVERS:
        rows.append([d["num"], f"{d['last'].upper()}, {d['first'].upper()} {d['mi']}", _ymd(d["dob"]),
                     d["sex"], d["marital"], d["lic"], d["lic_state"], d["lic_year"], d["exp"],
                     _dmy(d["hired"]), d["veh"] or "--", d["pct"] or "--",
                     f"{d['city']} {d['state']} {d['zip']}"])
    f.table(["DRV", "NAME", "DOB", "SX", "MS", "DL #", "ST", "ISS", "YRS", "HIRED", "VEH", "%",
             "CITY ST ZIP"], rows,
            [LEFT, 54, 156, 200, 214, 228, 280, 296, 318, 338, 390, 412, 432], size=6.0)
    f.para("DOB = YYYYMMDD. MS: S single, M married, D divorced. ISS = year first licensed. YRS = "
           "years of driving experience. Driver 5 is a relief driver with no assigned vehicle. "
           "Vehicle 2 is shared: driver 2 drives it 70% of the time and driver 6 30%.", SANS, 6.6)
    f.para(f"Not authorized: {D.TERMINATED_DRIVER['name']} (terminated "
           f"{D.TERMINATED_DRIVER['terminated']}); {D.CFO} (uses his own car for errands; "
           f"not a scheduled driver); {D.CEO} (Drive Other Car named individual only).", SANS, 6.6)
    f.doc("CLEARPATH MVR SERVICES - MOTOR VEHICLE RECORDS (ordered 09/14/2026)",
          "CLEARPATH MVR SERVICES - CONFIDENTIAL - FCRA/DPPA PERMISSIBLE PURPOSE: INSURANCE")
    ssn_tail = ["4471", "0287", "1563", "9902", "3318", "7740"]
    for d, tail in zip(D.DRIVERS, ssn_tail):
        f.line(f"NAME: {d['last'].upper()}, {d['first'].upper()} {d['mi']}   DOB: "
               f"{d['dob'][6:]}-{d['dob'][:2]}-{d['dob'][3:5]}   DL#: {d['lic']}   ST: {d['lic_state']}   "
               f"SSN: XXX-XX-{tail}", MONO, 6.4)
        cls = "A (CDL)" if d["num"] == "4" else "D"
        viol = "NONE REPORTED"
        if d["num"] == "3":
            viol = f"{D.CONVICTION['date']} SPEEDING 14 OVER - SIMPSON CO KY - CONVICTED"
        if d["num"] == "1":
            viol = f"{D.OLD_CONVICTION['date']} FAILURE TO YIELD - DAVIDSON CO TN - CONVICTED"
        f.line(f"  CLASS: {cls}   STATUS: VALID   ORIG ISSUE: {d['lic_year']}   VIOLATIONS: {viol}",
               MONO, 6.4)
    T = D.TERMINATED_DRIVER
    f.line(f"NAME: AMBROSE, KYLE J   DOB: 1999-04-04   DL#: {T['lic']}   ST: TN   SSN: XXX-XX-6620",
           MONO, 6.4)
    f.line("  CLASS: D   STATUS: VALID   VIOLATIONS: 07/19/2026 AT-FAULT ACCIDENT - RUTHERFORD CO TN",
           MONO, 6.4)


# ════════════════════════════════════════════════════════════════════════════
# 23. Telematics and fleet maintenance
# ════════════════════════════════════════════════════════════════════════════
def telematics(f: Flow):
    f.doc("FLEETPULSE TELEMATICS - MONTHLY FLEET SAFETY REPORT - AUGUST 2026", PKG_HDR,
          )
    f.kv([("Vehicles with active units", "4 of 4 (100%)"),
          ("Features enabled", "Driver safety scoring; GPS location tracking; mileage / IFTA "
                               "tracking; maintenance alerts; forward-facing dash cameras"),
          ("Features not enabled", "Fuel consumption tracking (not subscribed); turn-by-turn "
                                   "navigation")], font=SANS, size=6.9, label_w=150)
    rows = []
    rnd = random.Random(88)
    for day in range(1, 32):
        for v in D.VEHICLES:
            if rnd.random() < 0.35:
                continue
            rows.append([f"08/{day:02d}/2026", v["num"], f"{rnd.randint(18, 260)}",
                         f"{rnd.randint(0, 3)}", f"{rnd.randint(0, 2)}", f"{rnd.randint(4, 95)}",
                         f"{rnd.randint(72, 99)}"])
    f.table(["DATE", "VEH", "MILES", "HARSH BRK", "SPEEDING", "IDLE MIN", "SCORE"], rows,
            [LEFT, 100, 140, 190, 250, 310, 370], size=6.0)
    f.doc("FLEET MAINTENANCE POLICY (excerpt)", PKG_HDR)
    f.para(D.Q127["CommercialVehicleLineOfBusiness_Question_KADCode_A"][2] + ". Pre-trip "
           "inspections are logged daily in the FleetPulse app; defects are repaired before the "
           "vehicle returns to service.", SERIF, 7.0)


# ════════════════════════════════════════════════════════════════════════════
# 24-25. Property declarations + statement of values; umbrella declarations
# ════════════════════════════════════════════════════════════════════════════
def property_dec(f: Flow):
    f.doc(f"{D.MAG.upper()} - COMMERCIAL PROPERTY DECLARATIONS", f"{D.MAG}  |  NAIC {D.MAG_NAIC}",
          new_page=True)
    f.kv([("Policy", "MUI-CP-0098817-25"), ("Period", f"{D.CUR_EFF} to {D.CUR_EXP}"),
          ("Named insured", D.NAME), ("Premium", "$27,940"),
          ("Mortgageholder", f"{D.MORTGAGEE['name']} - premises 001"),
          ("Deductible", "$5,000 all other perils; wind / hail 1%")], font=MONO, size=6.9,
         label_w=140, leader=True)
    f.para("Premises 002 (1040 Visco Dr) deleted 07/01/2026 by endorsement CP-E3.", MONO, 6.6)
    f.doc("STATEMENT OF VALUES - CARRIER PREMISES NUMBERING", f"{D.MAG}  |  NAIC {D.MAG_NAIC}",
          new_page=True, wide=True)
    xs = [LEFT, 82, 270, 330, 372, 420, 470, 520, 580, 640, 700]
    f.table(["PREM", "ADDRESS", "CONST", "YR BLT", "STORIES", "SQ FT", "SPRKL", "BUILDING", "BPP",
             "BI", "ROOF"],
            [["001", f"{L1['l1']}, Nashville TN 37211", "Masonry NC", "1987", "1", "58,000", "Y",
              D.BUILDING_VALUE_LOC1, "$2,450,000", "$1,800,000", "2025"],
             ["002", "1040 Visco Dr, Nashville TN 37210 (DELETED)", "Frame", "1972", "1", "4,800", "N",
              "--", "$0", "--", "--"],
             ["003", f"{L2['l1']} {L2['l2']}, La Vergne TN 37086", "Tilt-up", "2004", "1", "50,000",
              "Y", "--", "$1,150,000", "--", "2004"],
             ["004", f"{L3['l1']} {L3['l2']}, Franklin TN 37067", "Steel", "2016", "3", "24,000", "Y",
              "--", "$185,000", "--", "2016"]], xs, size=6.4)
    f.para("Carrier premises numbers (001-004) are the property carrier's own numbering and differ "
           "from the application's location numbers. Total insured value $11,385,000.", MONO, 6.4)
    rnd = random.Random(7)
    f.head("BUSINESS PERSONAL PROPERTY DETAIL - PREMISES 001 (inventory by category)")
    cats = ["Combi ovens", "Deck ovens", "Espresso machines", "Reach-in refrigeration", "Walk-in panels",
            "Ice machines", "Fryers", "Ranges", "Dishwashers", "Smallwares", "Parts - gas valves",
            "Parts - compressors", "Parts - controls", "Stainless tables", "Shelving", "Hoods"]
    rows = [[c, f"{rnd.randint(4, 140)}", f"${rnd.randint(9, 260) * 1000:,}", f"Aisle {i + 1}"]
            for i, c in enumerate(cats)]
    f.table(["CATEGORY", "UNITS", "VALUE", "LOCATION IN WAREHOUSE"], rows, [LEFT, 300, 380, 480],
            size=6.4)


def umbrella_dec(f: Flow):
    f.doc(f"{D.CXS.upper()} - COMMERCIAL UMBRELLA DECLARATIONS", f"{D.CXS}  |  NAIC {D.CXS_NAIC}",
          )
    f.kv([("Policy", "CXS-UMB-220871-25"), ("Period", f"{D.CUR_EFF} to {D.CUR_EXP}"),
          ("Named insured", f"{D.NAME}; {D.SUB['name']}"),
          ("Limits", "$5,000,000 each occurrence / $5,000,000 aggregate"),
          ("Self-insured retention", "$10,000"), ("Premium", "$9,880"),
          ("History", "First umbrella placement incepted 12/01/2024 - no umbrella before that date")],
         font=MONO, size=6.9, label_w=140, leader=True)
    f.table(["UNDERLYING", "CARRIER", "POLICY", "LIMITS"],
            [["General liability", D.OHM, "OHM-GL-4471902-25", "$1,000,000 / $2,000,000"],
             ["Business auto", D.OHM, "OHM-CA-4471903-25", "$1,000,000 CSL"],
             ["Employers liability", D.TEM, D.TEM_POLICY, "$1,000,000 / $1,000,000 / $1,000,000"]],
            [LEFT, 130, 300, 400], size=6.4)


# ════════════════════════════════════════════════════════════════════════════
# 26. Loss runs - current valuation, an OLD valuation (OCR text), every carrier
# ════════════════════════════════════════════════════════════════════════════
def loss_runs(f: Flow):
    A, P, C = D.LOSSES
    f.doc("OLD HICKORY MUTUAL - LOSS RUN - VALUED 09/15/2026", OHM_HDR)
    f.kv([("Insured", f"{D.NAME} (formerly {D.FORMER_NAME})"),
          ("Period", "12/01/2021 to 09/15/2026 - general liability and business auto")],
         font=MONO, size=6.8, label_w=100)
    terms = [("2025-26", "-25", "$38,420", "$61,775"), ("2024-25", "-24", "$35,910", "$57,240"),
             ("2023-24", "-23", "$33,005", "$52,880"), ("2022-23", "-22", "$31,400", "$49,615"),
             ("2021-22", "-21", "$29,975", "$46,030")]
    rows = []
    for t, suf, glp, aup in terms:
        y0, y1 = t[:4], "20" + t[5:]
        rows.append([t, f"OHM-GL-4471902{suf}", f"12/01/{y0}", f"12/01/{y1}", glp, "0 claims"])
        rows.append([t, f"OHM-CA-4471903{suf}", f"12/01/{y0}", f"12/01/{y1}", aup,
                     "1 claim" if suf in ("-25", "-21") else "0 claims"])
    f.table(["TERM", "POLICY", "EFFECTIVE", "EXPIRATION", "WRITTEN PREM", "CLAIMS"], rows,
            [LEFT, 90, 210, 270, 330, 400], size=6.3)
    f.head("CLAIM DETAIL")
    det = [
        [A["claim_no"], A["occurrence"], A["claim"], "AUTO", A["desc"][:42], A["paid"], A["reserved"],
         "0", "OPEN", "N"],
        [A["claim_no"] + "-D", A["occurrence"], A["claim"], "AUTO", "VOID - DUPLICATE - see -018822",
         "$0", "$0", "0", "VOID", "N"],
        [C["claim_no"], C["occurrence"], C["claim"], "AUTO", C["desc"][:42], C["paid"], "$0",
         C["paid"], "CLOSED", "Y"],
    ]
    f.table(["CLAIM #", "LOSS DATE", "REPORTED", "LINE", "DESCRIPTION", "PAID", "RESERVE", "SUBRO REC",
             "STATUS", "SUBRO"], det, [LEFT, 106, 150, 192, 216, 400, 436, 470, 506, 540],
            style="riffled", size=5.9)
    f.para(f"Line of business: AUTO = Commercial Auto. Claim {C['claim_no']} was reported under the "
           f"former name {D.FORMER_NAME}; subrogation against the other driver's carrier recovered "
           f"{C['paid']}; full description - {C['desc']}. Claim {A['claim_no']}: full description - "
           f"{A['desc']}. Totals: paid "
           f"$10,187; outstanding reserve {A['reserved']}; incurred $11,687.", MONO, 6.3)
    f.doc("OLD HICKORY MUTUAL - LOSS RUN VALUED 12/31/2025 (fax copy, text recognized)", OHM_HDR)
    for ln in [
        "0LD HICK0RY MUTUAL INS C0   L0SS RUN   VALUED: 12/3l/2O25",
        "INSD: CUMBERLAND HEARTH&H0SPITALITYSUPPLY,INC.",
        "CLAIM 0HM-25-CA-0l8822  D0L 08/O9/2025  PAlD 2,1OO.OO  RESV 5,8OO.OO  0PEN",
        "CLAIM 0HM-22-CA-OO4471  D0L 03/O3/2022  PAlD 3,775.OO  RESV O.OO  CL0SED SUBR0",
    ]:
        f.line(ln, MONO, 6.6)
    f.para(f"(Clean copy of the same page: claim {A['claim_no']} as of {D.OLD_VALUATION['date']} - paid "
           f"{D.OLD_VALUATION['paid']}, reserve {D.OLD_VALUATION['reserved']}, open. This valuation is "
           "superseded by the 09/15/2026 run.)", SANS, 6.6)
    f.doc(f"{D.VFM.upper()} - LOSS RUN - 12/01/2019 TO 12/01/2024", f"{D.VFM}  |  NAIC {D.VFM_NAIC}")
    f.table(["TERM", "POLICY", "LOSS DATE", "CLAIM #", "DESCRIPTION", "PAID", "STATUS"],
            [["2019-20", "VFM-CPP-7781203", "--", "--", "no losses", "--", "--"],
             ["2020-21", "VFM-CPP-7781203", D.DECOY_LOSSES[0]["occurrence"],
              D.DECOY_LOSSES[0]["claim_no"], D.DECOY_LOSSES[0]["desc"][:40], D.DECOY_LOSSES[0]["paid"],
              "CLOSED"],
             ["2021-22", "VFM-CPP-7781203", "--", "--", "no losses", "--", "--"],
             ["2022-23", "VFM-CPP-7781203", "--", "--", "no losses", "--", "--"],
             ["2023-24", "VFM-CPP-7781203", P["occurrence"], P["claim_no"], P["desc"][:40], P["paid"],
              "CLOSED"]], [LEFT, 80, 160, 210, 280, 470, 520], style="riffled", size=6.0)
    f.para(f"Line: Commercial Property. Claim {P['claim_no']} - {P['desc']} - reported {P['claim']}; "
           f"paid {P['paid']}; reserve $0; no "
           "subrogation. Term dates: 12/01 to 12/01 each year; the 2023-24 term ran 12/01/2023 to "
           "12/01/2024 and was not renewed. Premium is not shown on this report.", MONO, 6.3)
    f.doc(f"{D.MAG.upper()} - LOSS RUN - VALUED 09/10/2026", f"{D.MAG}  |  NAIC {D.MAG_NAIC}")
    f.table(["TERM", "POLICY", "EFFECTIVE", "EXPIRATION", "PREMIUM", "LOSSES"],
            [["2024-25", "MUI-CP-0098817-24", "12/01/2024", "12/01/2025", "$25,115", "NO LOSSES REPORTED"],
             ["2025-26", "MUI-CP-0098817-25", "12/01/2025", "12/01/2026", "$27,940", "NO LOSSES REPORTED"]],
            [LEFT, 80, 190, 250, 310, 370], size=6.4)
    f.doc(f"{D.CXS.upper()} - LOSS RUN - VALUED 09/08/2026", f"{D.CXS}  |  NAIC {D.CXS_NAIC}")
    f.table(["TERM", "POLICY", "EFFECTIVE", "EXPIRATION", "PREMIUM", "LOSSES"],
            [["2024-25", "CXS-UMB-220871-24", "12/01/2024", "12/01/2025", "$9,240", "NONE"],
             ["2025-26", "CXS-UMB-220871-25", "12/01/2025", "12/01/2026", "$9,880", "NONE"]],
            [LEFT, 80, 190, 250, 310, 370], size=6.4)
    f.doc("BROOKLINE MUTUAL - LOSS RUN - MUSIC ROW KITCHEN RENTALS, LLC", "BROOKLINE MUTUAL "
          "INSURANCE CO.  |  (joint venture - separately insured)")
    J = D.DECOY_LOSSES[1]
    f.para(f"Insured: {D.JV['name']}, {D.JV['addr']} (FEIN {D.JV['fein']}). Claim {J['claim_no']}, "
           f"date of loss {J['occurrence']}: {J['desc']}. Paid {J['paid']}; closed.", MONO, 6.4)


# ════════════════════════════════════════════════════════════════════════════
# 27. The 2024 application from the PRIOR agency - SUPERSEDED, rotated stamp
# ════════════════════════════════════════════════════════════════════════════
def old_application(f: Flow):
    f.doc("COMMERCIAL INSURANCE APPLICATION - 2024 RENEWAL (prior agency)",
          f"{D.PRIOR_AGENCY}  |  {D.PRIOR_AGENCY_PHONE}  |  agency code {D.PRIOR_AGENCY_CODE}",
          new_page=True)
    f.watermark("SUPERSEDED - 2024")
    f.kv([("Date", "10/15/2024"), ("Agency customer ID", D.PRIOR_AGENCY_CUSTOMER_ID),
          ("Carrier", f"{D.OHM}  NAIC {D.OHM_NAIC}"), ("Status", "Renew"),
          ("Proposed term", "12/01/2024 - 12/01/2025"), ("Nature of business", "Retail"),
          ("Revenue", "$16,100,000"), ("Employees", "61 full time / 5 part time"),
          ("Accounting contact", "Brenda Faulk  615-555-0158"),
          ("1a Subsidiary of another entity?", "Y - parent: Ellison Family Holdings LLC, 60%"),
          ("2 Safety program", "Y - manual, monthly meetings"),
          ("5 Declined / cancelled / non-renewed?", "N"),
          ("8 Uncorrected fire code violations?", "N"),
          ("14 Own / lease / operate drones?", "Y - owns one DJI Mavic 3 for roof photos"),
          ("15 Hire others to operate drones?", "N"),
          ("Losses (3 years)", "Property - no losses in the past 3 years")],
         font=MONO, size=6.9, label_w=190, leader=True)
    f.para("This application was prepared for the 2024 renewal with the prior carrier and the "
           "prior agency and is included for history only.", SERIF_I, 7.0)


# ════════════════════════════════════════════════════════════════════════════
# 28-31. Joint venture; events; installation jobs; certificate holders
# ════════════════════════════════════════════════════════════════════════════
def jv_and_events(f: Flow):
    f.doc(f"OPERATING AGREEMENT (excerpt) - {D.JV['name'].upper()}", PKG_HDR)
    f.paras([
        f"Members: {D.NAME} - 40% membership interest; Nashville Culinary Ventures, LLC - 60%. "
        "Managed by Nashville Culinary Ventures, LLC.",
        f"Principal office: {D.JV['addr']}. EIN {D.JV['fein']}. Website {D.JV['web']}. Phone "
        f"{D.JV['phone']}.",
        "Section 7.3 Insurance. The Company shall maintain its own general liability, property and "
        "workers compensation insurance in its own name.",
    ], font=SERIF, size=7.0)
    f.doc("MEMO - CUSTOMER EVENT AND SPONSORSHIPS (marketing)", PKG_HDR)
    f.paras([
        "Customer appreciation barbecue - held each October at the Kellerman showroom and parking "
        "lot; about 250 guests; Smoke & Barrel Catering (licensed) serves beer and wine under its "
        "own liquor license and insurance.",
        f"Bowling - we sponsor the 'Cumberland Hearth Strikers' in an adult league: "
        f"{D.ATHLETIC_TEAM['extent'].lower()}. We do not sponsor any youth teams.",
        "Parking - the Kellerman lot (60 spaces) is owned by the company and is free for "
        "customers and employees.",
    ], font=SANS, size=6.9)


def job_list(f: Flow):
    f.doc("INSTALLATION JOB LIST - 2026 (customer sites - work performed AT these addresses)",
          PKG_HDR)
    rows = [[s["job"], s["customer"], s["addr"], s["city"], s["state"], s["zip"], s["value"]]
            for s in D.job_sites()]
    f.table(["JOB", "CUSTOMER", "SITE ADDRESS", "CITY", "ST", "ZIP", "CONTRACT"], rows,
            [LEFT, 80, 230, 360, 440, 470, 510], size=6.2)


def cert_holders(f: Flow):
    f.doc("CERTIFICATE OF INSURANCE HOLDERS - ISSUED 2026", PKG_HDR)
    rows = [[n, a, "GL/AUTO/UMB", "Additional insured - ongoing operations" if i % 3 else "Holder only"]
            for i, (n, a) in enumerate(D.CERT_HOLDERS)]
    f.table(["CERTIFICATE HOLDER", "ADDRESS", "INSURANCE", "STATUS"], rows,
            [LEFT, 220, 420, 480], size=6.1)
    f.para("Certificate holders are customers and general contractors who requested evidence of "
           "insurance; none of them is a named insured, a premises or an additional interest on "
           "the property.", SANS, 6.6)


# ════════════════════════════════════════════════════════════════════════════
# 32. Policy wording - the filler that pins the character count
# ════════════════════════════════════════════════════════════════════════════
_CLAUSES = [
    "We will pay those sums that the insured becomes legally obligated to pay as damages because of bodily injury or property damage to which this insurance applies.",
    "We will have the right and duty to defend the insured against any suit seeking those damages, but we have no duty to defend against suits to which this insurance does not apply.",
    "The amount we will pay for damages is limited as described in Section III - Limits Of Insurance.",
    "This insurance applies to bodily injury and property damage only if the occurrence takes place in the coverage territory and during the policy period.",
    "Expected or intended injury: bodily injury or property damage expected or intended from the standpoint of the insured is excluded.",
    "Contractual liability is excluded, except liability assumed in a contract or agreement that is an insured contract.",
    "Pollution: bodily injury or property damage arising out of the actual, alleged or threatened discharge, dispersal, seepage, migration, release or escape of pollutants is excluded.",
    "Aircraft, auto or watercraft owned or operated by or rented or loaned to any insured is excluded under this coverage form.",
    "Damage to your product arising out of it or any part of it is excluded.",
    "Damage to your work arising out of it or any part of it and included in the products-completed operations hazard is excluded.",
    "Recall of products, work or impaired property: damages claimed for any loss, cost or expense incurred for the withdrawal or recall are excluded.",
    "Supplementary payments: all expenses we incur, and reasonable expenses incurred by the insured at our request to assist us.",
    "Duties in the event of occurrence, offense, claim or suit: you must see to it that we are notified as soon as practicable.",
    "Other insurance: if other valid and collectible insurance is available to the insured for a loss we cover, our obligations are limited as described.",
    "Premium audit: we will compute all premiums for this coverage part in accordance with our rules and rates.",
    "Separation of insureds: except with respect to the limits of insurance, this insurance applies as if each named insured were the only named insured.",
    "Transfer of rights of recovery against others to us: if the insured has rights to recover all or part of any payment we have made, those rights are transferred to us.",
    "When we do not renew: if we decide not to renew this coverage part, we will mail or deliver written notice of the nonrenewal not less than 30 days before the expiration date.",
    "Coverage territory means the United States of America, including its territories and possessions, Puerto Rico and Canada.",
    "Mobile equipment means land vehicles, including any machinery or apparatus attached thereto, whether or not self-propelled.",
    "Occurrence means an accident, including continuous or repeated exposure to substantially the same general harmful conditions.",
    "Property damage means physical injury to tangible property, including all resulting loss of use of that property.",
    "Suit means a civil proceeding in which damages because of bodily injury, property damage or personal and advertising injury are alleged.",
    "Covered autos: the symbols entered next to a coverage on the declarations designate the only autos that are covered autos.",
    "We will pay for loss to a covered auto or its equipment under comprehensive coverage caused by any peril except collision.",
    "Covered property means the type of property described in this section, and limited in section C, if a limit of insurance is shown in the declarations.",
    "Coinsurance: if a coinsurance percentage is shown in the declarations, we will not pay the full amount of any loss if the value of covered property is greater.",
    "Mortgageholders: the term mortgageholder includes trustee; we will pay for covered loss of or damage to buildings or structures to each mortgageholder shown.",
    "The umbrella applies to damages in excess of the retained limit, which is the total of the applicable limits of scheduled underlying insurance or the self-insured retention.",
    "Maintenance of underlying insurance: the policies listed in the schedule of underlying insurance shall be maintained in full effect during the policy period.",
    "Cancellation: the first named insured shown in the declarations may cancel this policy by mailing or delivering to us advance written notice of cancellation.",
    "Examination of your books and records: we may examine and audit your books and records as they relate to this policy at any time during the policy period.",
    "Inspections and surveys: we have the right to make inspections and surveys at any time, to give you reports on the conditions we find and to recommend changes.",
    "Concealment, misrepresentation or fraud: this policy is void in any case of fraud by you as it relates to this policy at any time.",
    "Bankruptcy or insolvency of the insured or of the insured's estate will not relieve us of our obligations under this coverage part.",
    "Certified acts of terrorism: coverage is subject to the federal program's annual aggregate cap on insured losses.",
    "This insurance does not apply under any liability coverage to bodily injury or property damage with respect to which an insured is also an insured under a nuclear energy liability policy.",
    "Fungi or bacteria: bodily injury or property damage which would not have occurred but for the actual or threatened inhalation of fungi or bacteria is excluded.",
    "Employment-related practices: injury arising out of refusal to employ, termination, coercion, demotion, evaluation, reassignment, discipline or harassment is excluded.",
    "Liquor liability: bodily injury or property damage for which any insured may be held liable by reason of causing the intoxication of any person is excluded if the insured is in the business of selling alcoholic beverages.",
]


def wording_lines(seed: int, n: int):
    rnd = random.Random(seed)
    out = []
    while len(out) < n:
        c = _CLAUSES[rnd.randrange(len(_CLAUSES))]
        out.append(f"{rnd.randint(1, 9)}.{rnd.randint(1, 14)}  {c}")
    return out


def policy_wording(f: Flow, total_chars: int, tail: int = 0):
    """About `total_chars` characters of wording, then ONE closing line of exactly `tail`
    characters. The closing line never wraps, so it moves the page count by exactly one
    character per character - the build tunes it to hit the target exactly."""
    forms = [("CG 00 01 04 13", "COMMERCIAL GENERAL LIABILITY COVERAGE FORM"),
             ("CA 00 01 10 13", "BUSINESS AUTO COVERAGE FORM"),
             ("CP 00 10 10 12", "BUILDING AND PERSONAL PROPERTY COVERAGE FORM"),
             ("CU 00 01 12 07", "COMMERCIAL LIABILITY UMBRELLA COVERAGE FORM"),
             ("IL 00 17 11 98", "COMMON POLICY CONDITIONS")]
    left = total_chars
    k = 0
    while left > 0:
        code, name = forms[k % len(forms)]
        f.doc(f"POLICY FORMS (expiring program) - {code} - {name}", OHM_HDR, new_page=(k == 0))
        lines = wording_lines(500 + k, 60)
        for ln in lines:
            if left <= 0:
                break
            from kit_engine import wrap
            for piece in wrap(ln, SERIF, 6.8, f.page_w()):
                if left <= 0:
                    break
                piece = piece[:left] if len(piece) > left else piece
                f.line(piece, SERIF, 6.8)
                left -= len(piece)
        k += 1
    if tail > 0:
        base = "End of forms. Index: " + " / ".join(c for c, _n in forms) + " / IL 00 21 09 08 / "
        while len(base) < tail:
            base += "CG 21 06 05 14 / "
        f.line(base[:tail].rstrip() + ("." * (tail - len(base[:tail].rstrip()))), MONO, 5.8)


DOCS = [agency_email, mga_acknowledgement, intake_worksheet, cfo_thread, questionnaire_125,
        premises_schedule, hr_census, financials, corporate, ams_export, gl_supplemental,
        products, subcontractors, loaner_log, safety_program, fire_and_roof, notices,
        leases_and_loan, gl_declarations, auto_declarations, auto_supplemental, drivers,
        telematics, property_dec, umbrella_dec, loss_runs, old_application, jv_and_events,
        job_list, cert_holders]
