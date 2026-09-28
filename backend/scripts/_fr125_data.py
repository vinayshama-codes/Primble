"""
_fr125_data.py - the single source of truth for the FR125 kit, VERSION 2.

    Version 1 (archived in fr125_test_data/v1_round2_test2/) was the client's
    8-19-26 case as written: one entity, one premises, one claim - and a form
    that stays mostly blank BY RULE. Round 2 test 2 was graded against it.

    Version 2 (28 Sep 2026, the owner's ask): fill the form the way the
    client's Vertafore data map (`ACORD 125 - data map 8-19-26.pdf`) fills it -
    nearly every box - WITHOUT bending a single client rule. Nothing here is
    inferred: every value the key expects is STATED somewhere in the package,
    which is exactly what the rules require ("only if verified", "blank unless
    known"). The documents simply verify more.

Every value is written ONCE here; the generator prints it and the answer key
expects it from this same object, so the two can never drift.
"""
from __future__ import annotations

# ── The submission: new business to the RECEIVING carrier ───────────────────
CARRIER             = "Granite Arch Casualty Company"
CARRIER_NAIC        = "21334"          # stated on Granite Arch's own acknowledgement
PROGRAM_NAME        = "Contractors Select Program"
PROGRAM_CODE        = "CSP-EL"
UNDERWRITER         = "Dana Whitfield"
UNDERWRITER_OFFICE  = "Denver Branch"
PROPOSED_EFF        = "10/01/2026"
PROPOSED_EXP        = "10/01/2027"
BILLING             = "Direct"
PAYMENT_PLAN_WORD   = "Monthly"
PAYMENT_PLAN_CODE   = "MO"             # ACORD tooltip: "AN - Annual, MO - Monthly..."
PAYMENT_METHOD      = "EFT"
AUDIT_WORD          = "Annual"
AUDIT_CODE          = "A"              # ACORD tooltip: "A - annual, S - semi-annual..."
REMARKS = ("Please quote General Liability at $1,000,000 / $2,000,000 and the "
           "umbrella at $2,000,000. Locations 2 and 4 are owned; Locations 1 and 3 "
           "are leased.")

# ── The producer (resolved from the LOGGED-IN ACCOUNT in the product) ────────
PRODUCER            = "Summit Commercial Insurance"
PRODUCER_L1         = "1800 Market Street"
PRODUCER_L2         = "Suite 400"
PRODUCER_CITY       = "Denver"
PRODUCER_STATE      = "CO"
PRODUCER_ZIP        = "80202"
PRODUCER_CONTACT    = "Michelle Smith"
PRODUCER_PHONE      = "303-555-0100"
PRODUCER_EMAIL      = "mproducer@example.com"
AGENCY_CUSTOMER_ID  = "FREC-001"

# ── The first named insured ──────────────────────────────────────────────────
NAME                = "Front Range Electrical Contractors LLC"
FEIN                = "12-3456789"
ENTITY              = "LLC"
NAICS               = "238210"
SIC                 = "1731"
GL_CODE             = "92478"
MAIL_L1             = "8000 Commerce Way"
MAIL_L2             = "Suite 120"
MAIL_CITY           = "Denver"
MAIL_STATE          = "CO"
MAIL_ZIP            = "80216"
BUS_PHONE           = "303-555-0175"
WEBSITE             = "www.example-electrical.com"
MEMBERS             = "3"              # the Operating Agreement's Schedule A - SCANNED only
START_DATE          = "06/15/2014"
START_DATE_WORDS    = "June 15, 2014"
NATURE              = "Contractor"

MEMBER_LIST = [("Luis Ortega", "Managing Member", "55%"),
               ("Maria Ortega", "Member", "25%"),
               ("Front Range Holdings Inc", "Member", "20%")]

# ── The other named insureds (rows B and C) ─────────────────────────────────
OTHER_INSUREDS = [
    {"name": "Front Range Service Company LLC", "fein": "45-6789012",
     "sic": "7629", "naics": "811310", "gl": "97220",
     "l1": "8000 Commerce Way", "l2": "Suite 130", "city": "Denver", "state": "CO",
     "zip": "80216", "phone": "303-555-0176", "web": "www.frservice-example.com",
     "entity": "LLC", "members": "1",
     "role": "wholly owned service subsidiary of the applicant"},
    {"name": "Commerce Way Equipment Leasing LLC", "fein": "45-1122334",
     "sic": "7359", "naics": "532412", "gl": "97111",
     "l1": "8000 Commerce Way", "l2": "Suite 140", "city": "Denver", "state": "CO",
     "zip": "80216", "phone": "303-555-0178", "web": "www.cwleasing-example.com",
     "entity": "LLC", "members": "2",
     "role": "sister company that owns and leases the fleet and lifts to the applicant"},
]
OTHER_INSURED_OPERATIONS = (
    "Front Range Service Company LLC performs after-hours electrical service calls "
    "and preventive maintenance for commercial customers. Commerce Way Equipment "
    "Leasing LLC owns the service vehicles and aerial lifts and leases them to the "
    "applicant; it has no other customers.")

# ── Parent / subsidiary (question 1a / 1b) ───────────────────────────────────
PARENT_ORG          = "Front Range Holdings Inc"
PARENT_RELATIONSHIP = "Parent holding company"
PARENT_PCT          = "80%"
SUB_ORG             = OTHER_INSUREDS[0]["name"]
SUB_RELATIONSHIP    = "Wholly owned service subsidiary"
SUB_PCT             = "100%"

# ── Contacts (page 2) - every box, including phone TYPES ────────────────────
CONTACTS = [
    {"type": "Inspection", "name": "John Smith",
     "phone": "303-555-0188", "phone_type": "Cell",
     "phone2": "303-555-0175", "phone2_type": "Business",
     "email": "john@example-electrical.com",
     "email2": "jsmith.site@example-electrical.com"},
    {"type": "Accounting", "name": "Sarah Jones",
     "phone": "303-555-0190", "phone_type": "Business",
     "phone2": "720-555-0142", "phone2_type": "Cell",
     "email": "accounting@example-electrical.com",
     "email2": "sjones@example-electrical.com"},
]

# ── Four premises ────────────────────────────────────────────────────────────
LOCATIONS = [
    {"num": "1", "bldg": "1", "l1": "8000 Commerce Way", "l2": "Suite 120",
     "city": "Denver", "county": "Denver", "state": "CO", "zip": "80216",
     "inside": True, "interest": "Tenant", "ft": "12", "pt": "1",
     "revenue": "$2,950,000", "occupied": "5,000", "public": "500",
     "total_area": "15,000", "leased": "N",
     "ops": "Administrative office, electrical contracting warehouse and material storage."},
    {"num": "2", "bldg": "1", "l1": "5300 N Federal Blvd", "l2": "",
     "city": "Denver", "county": "Adams", "state": "CO", "zip": "80221",
     "inside": False, "interest": "Owner", "ft": "4", "pt": "1",
     "revenue": "$900,000", "occupied": "8,000", "public": "0",
     "total_area": "8,000", "leased": "N",
     "ops": "Fleet yard, vehicle maintenance bay and aerial lift storage."},
    {"num": "3", "bldg": "1", "l1": "4750 Centennial Blvd", "l2": "Suite 210",
     "city": "Colorado Springs", "county": "El Paso", "state": "CO", "zip": "80919",
     "inside": True, "interest": "Tenant", "ft": "2", "pt": "0",
     "revenue": "$400,000", "occupied": "1,200", "public": "150",
     "total_area": "22,000", "leased": "N",
     "ops": "Branch estimating office for southern Colorado projects."},
    {"num": "4", "bldg": "1", "l1": "780 Kimbark St", "l2": "",
     "city": "Longmont", "county": "Boulder", "state": "CO", "zip": "80501",
     "inside": True, "interest": "Owner", "ft": "0", "pt": "0",
     "revenue": "$0", "occupied": "1,500", "public": "0",
     "total_area": "3,000", "leased": "Y",
     "ops": "Wire and conduit storage building; the other half is leased to a cabinet shop."},
]
LOC = LOCATIONS[0]                     # v1 name, kept for the tests

PRIMARY_OPERATIONS = (
    "Licensed electrical contractor performing commercial and residential "
    "electrical installation, repair and service. Work includes new wiring, "
    "service upgrades, panel replacement, lighting and electrical "
    "troubleshooting. No utility-line construction or electrical generation "
    "operations.")
INSTALL_PCT         = "100%"
INSTALL_OFF_PCT     = "90%"
RETAIL_PCT          = "0%"

# ── The fifteen questions - fourteen answered YES, with what ACORD asks ──────
# `scanned` = printed ONLY on the scanned second page of the questionnaire.
QUESTIONS = {
    "AAI": {"n": "1a", "q": "Is the applicant a subsidiary of another entity?",
            "answer": "Y", "scanned": False,
            "stated": f"Yes. The applicant is 80% owned by {PARENT_ORG}, its parent holding company."},
    "AAJ": {"n": "1b", "q": "Does the applicant have any subsidiaries?",
            "answer": "Y", "scanned": False,
            "stated": f"Yes. {SUB_ORG} is a wholly owned service subsidiary (100%)."},
    "KAA": {"n": "2", "q": "Is a formal safety program in operation?",
            "answer": "Y", "scanned": False,
            "stated": "Yes. Written manual, a full-time safety manager, monthly meetings, "
                      "OSHA-compliant, and a daily job hazard analysis."},
    "ABC": {"n": "3", "q": "Any exposure to flammables, explosives, chemicals?",
            "answer": "Y", "scanned": False,
            "stated": "Limited quantities of common jobsite adhesives and solvents stored "
                      "in approved containers."},
    "AAH": {"n": "4", "q": "Any other insurance with this company?",
            "answer": "Y", "scanned": False,
            "stated": f"Yes. Workers compensation and inland marine are written by {CARRIER}."},
    "AAC": {"n": "5", "q": "Any policy or coverage declined, cancelled or non-renewed "
                           "during the prior three years?",
            "answer": "Y", "scanned": False,
            "stated": "Alpine States non-renewed every line at 10/01/2023 because the "
                      "agency no longer represented the company."},
    "AAD": {"n": "6", "q": "Any past losses or claims relating to sexual abuse or "
                           "molestation, discrimination or negligent hiring?",
            "answer": "Y", "scanned": False,
            "stated": "A former apprentice filed an EEOC discrimination charge in 2023; "
                      "it was dismissed with no finding in November 2023."},
    "KAB": {"n": "7", "q": "Any applicant indicted for or convicted of fraud, bribery "
                           "or arson in the last five years?",
            "answer": "N", "scanned": False,
            "stated": "No applicant has been indicted for or convicted of any such crime."},
    "AAF": {"n": "8", "q": "Any uncorrected fire and/or safety code violations?",
            "answer": "Y", "scanned": True,
            "stated": "Yes. Two fire extinguishers at Location 3 carry expired inspection tags."},
    "KAK": {"n": "9", "q": "Foreclosure, repossession or bankruptcy in the last five years?",
            "answer": "Y", "scanned": True,
            "stated": "Yes. A leased compact excavator was repossessed in April 2022."},
    "KAL": {"n": "10", "q": "Any judgement or lien in the last five years?",
            "answer": "Y", "scanned": True,
            "stated": "Yes. A mechanics lien was recorded in August 2023 and released in February 2024."},
    "ABB": {"n": "11", "q": "Has the business been placed in a trust?",
            "answer": "Y", "scanned": True,
            "stated": "Yes. The managing member's interest is held by the Ortega Family Trust."},
    "KAC": {"n": "12", "q": "Any foreign operations or foreign products?",
            "answer": "Y", "scanned": True,
            "stated": "Yes. LED fixtures and control panels are imported from a supplier "
                      "in Ontario, Canada."},
    "KAM": {"n": "13", "q": "Other business ventures for which coverage is not requested?",
            "answer": "Y", "scanned": True,
            "stated": "The managing member owns Summit Solar Services LLC, a residential "
                      "solar installer that is not part of this submission."},
    "KAN": {"n": "14", "q": "Does the applicant own, lease or operate any drones?",
            "answer": "Y", "scanned": True,
            "stated": "The applicant owns one DJI Mavic 3 Enterprise drone flown by a "
                      "Part 107 certified employee for roof and site inspections."},
    "KAO": {"n": "15", "q": "Does the applicant hire others to operate drones?",
            "answer": "Y", "scanned": True,
            "stated": "The applicant hires Aerial Vantage LLC to fly progress-photography "
                      "drones on large commercial projects."},
}

SAFETY_MANAGER      = "Luis Ortega"
SAFETY_OTHER        = "Daily job hazard analysis before every shift"

OTHER_POLICIES = [("Workers Compensation", "WC-GA-448120"),
                  ("Commercial Inland Marine", "IM-GA-220915")]

NONRENEWALS = [
    {"year": "2023", "carrier": "Alpine States Insurance Company", "line": "all lines",
     "reason": "Agent no longer represents carrier",
     "detail": "Alpine States non-renewed every line at 10/01/2023 because the agency "
               "no longer represented the company."},
    {"year": "2024", "carrier": "Harbor Excess Insurance Company", "line": "umbrella",
     "reason": "Underwriting",
     "detail": "Harbor Excess non-renewed the umbrella at 10/01/2024 for underwriting "
               "reasons: no written fleet safety program."},
]
CONDITION_CORRECTED = ("A written fleet safety program with MVR review and driver "
                       "training was adopted in January 2025.")

FIRE_CODE = {"occur": "09/10/2026",
             "explain": "Colorado Springs Fire Department noted two extinguishers with "
                        "expired inspection tags at Location 3.",
             # NOT a resolution - it has not happened. The box stays EMPTY.
             "pending": "Extinguisher service is scheduled for 10/05/2026."}
REPOSSESSION = {"occur": "04/18/2022",
                "explain": "A leased compact excavator was repossessed by the lessor "
                           "after a billing dispute.",
                "resolution": "Dispute settled, balance paid in full and the lease account closed.",
                "resolved": "08/30/2022"}
LIEN = {"occur": "08/14/2023",
        "explain": "Mile High Supply recorded a mechanics lien on the Tennyson project "
                   "over a disputed invoice.",
        "resolution": "Invoice paid and the lien released.",
        "resolved": "02/27/2024"}
TRUST_NAME = "Ortega Family Trust"

# ── The current programme (the incumbent) ────────────────────────────────────
CUR_CARRIER         = "Timberline Mutual Insurance Company"
CUR_CARRIER_SHORT   = "Timberline Mutual"
CUR_CARRIER_NAIC    = "27413"
CUR_CARRIER_WEB     = "www.timberlinemutual-ins.com"
CUR_CARRIER_PHONE   = "(800) 555-0147"
CUR_EFF             = "10/01/2025"
CUR_EXP             = "10/01/2026"
CUR_BILLING         = "Agency bill - Quarterly installments"
CUR_TOTAL_PREMIUM   = "$45,500"
PRIOR_YEAR          = "2025"

PRIOR_TERMS = [
    {"year": "2025", "eff": "10/01/2025", "exp": "10/01/2026", "lines": {
        "GeneralLiability": (CUR_CARRIER, "GL-123456", "$18,450"),
        "Automobile":       (CUR_CARRIER, "BA-456789", "$14,200"),
        "Property":         (CUR_CARRIER, "CP-567890", "$8,750"),
        "OtherLine":        (CUR_CARRIER, "CU-678901", "$4,100")}},
    {"year": "2024", "eff": "10/01/2024", "exp": "10/01/2025", "lines": {
        "GeneralLiability": (CUR_CARRIER, "GL-104471", "$17,600"),
        "Automobile":       (CUR_CARRIER, "BA-431120", "$13,450"),
        "Property":         (CUR_CARRIER, "CP-540018", "$8,200"),
        "OtherLine":        (CUR_CARRIER, "CU-652207", "$3,900")}},
    {"year": "2023", "eff": "10/01/2023", "exp": "10/01/2024", "lines": {
        "GeneralLiability": (CUR_CARRIER, "GL-091233", "$16,900"),
        "Automobile":       (CUR_CARRIER, "BA-402266", "$12,980"),
        "Property":         (CUR_CARRIER, "CP-511907", "$7,850"),
        "OtherLine":        ("Harbor Excess Insurance Company", "XS-3310472", "$3,650")}},
]
GRID_LINE_NAMES = {"GeneralLiability": "General Liability", "Automobile": "Business Auto",
                   "Property": "Commercial Property", "OtherLine": "Commercial Umbrella"}
CURRENT_LINES = [{"line": GRID_LINE_NAMES[g], "grid": g, "policy": v[1], "premium": v[2]}
                 for g, v in PRIOR_TERMS[0]["lines"].items()]

# ── Loss history: three claims, valued 08/31/2026 ────────────────────────────
LOSSES = [
    {"occurrence": "09/14/2025", "claim": "09/16/2025", "line": "General Liability",
     "desc": "Customer ceiling damaged by water from a nicked sprinkler pipe during rough-in",
     "paid": "$12,400", "reserved": "$3,000", "subro": "Y", "open": "Y",
     "claim_no": "GL-25-01142"},
    {"occurrence": "03/28/2024", "claim": "03/28/2024", "line": "Business Auto",
     "desc": "Insured vehicle rear-ended third party at traffic light",
     "paid": "$4,850", "reserved": "$0", "subro": "N", "open": "N",
     "claim_no": "BA-24-00731"},
    {"occurrence": "06/02/2023", "claim": "06/03/2023", "line": "Commercial Property",
     "desc": "Theft of copper wire from the fleet yard at Location 2",
     "paid": "$6,300", "reserved": "$0", "subro": "N", "open": "N",
     "claim_no": "CP-23-00418"},
]
LOSS = LOSSES[1]                       # the auto claim with the stale fax copy
LOSS_OLD = {"paid": "$3,200", "reserved": "$1,650", "open": "Y", "valued": "06/30/2024"}
LOSS_VALUED = "08/31/2026"
LOSS_YEARS = "5"
TOTAL_PAID = "$23,550"                 # 12,400 + 4,850 + 6,300 - PAID, never incurred
TOTAL_INCURRED = "$26,550"             # the decoy: paid + reserved

# ── Additional interests ─────────────────────────────────────────────────────
MORTGAGEE = {"name": "Peak National Bank", "rank": "1",
             "l1": "1600 Broadway", "l2": "Suite 900", "city": "Denver",
             "state": "CO", "zip": "80202", "country": "US",
             "loan_no": "CML-448-2019-07", "end": "06/30/2034", "amount": "$1,150,000",
             "phone": "303-555-0240", "fax": "303-555-0241",
             "email": "loanservicing@peaknational-example.com",
             "reason": "First mortgage on the owned building at Location 2",
             "loc": "2", "bldg": "1",
             "item": "Fleet yard building, 5300 N Federal Blvd, Denver"}
LOSS_PAYEE_B = "Rocky Mountain Equipment Finance LLC"

# ── Revenue, payroll, headcount ──────────────────────────────────────────────
REVENUE_BY_YEAR = [("FY2023", "$3,880,000"), ("FY2024", "$4,020,000"),
                   ("FY2025", "$4,250,000"), ("FY2026 (projected)", "$4,610,000")]
TOTAL_PAYROLL    = "$1,640,000"
SEASONAL_TEMPS   = "6"
HEADCOUNT_TOTAL  = "20"

# ── Other parties that must stay OUT of the insured's boxes ─────────────────
LANDLORD         = "Commerce Way Partners LP"
LANDLORD_ADDR    = "1450 Wynkoop Street, Suite 300, Denver, CO 80202"
LANDLORD_PHONE   = "303-555-0122"
CO_TAX_ACCOUNT   = "12345678"
USDOT            = "3456789"
CONTRACTOR_LIC   = "EC.0112345"
WC_CARRIER       = CARRIER             # WC is written by the receiving carrier now

DECOYS = [
    (CUR_CARRIER, "Insurer_FullName_A", "the CURRENT carrier where the RECEIVING one belongs"),
    (CUR_CARRIER_NAIC, "Insurer_NAICCode_A", "the current carrier's NAIC"),
    ("GL-123456", "Policy_PolicyNumberIdentifier_A", "an EXPIRING policy number on a quote"),
    ("CG 20 11 04 13", "Policy_PolicyNumberIdentifier_A", "an ISO form number"),
    ("$18,450", "GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A",
     "the expiring GL premium on a quote"),
    (CUR_TOTAL_PREMIUM, "Policy_Payment_EstimatedTotalAmount_A", "the expiring package total"),
    (CUR_EFF, "Policy_EffectiveDate_A", "the CURRENT term's start"),
    (CUR_BILLING, "Policy_PaymentMethod_MethodDescription_A",
     "the CURRENT policy's billing, not the requested method"),
    (CUR_CARRIER_WEB, "NamedInsured_Primary_WebsiteAddress_*", "the carrier's website"),
    (CUR_CARRIER_PHONE, "NamedInsured_Primary_PhoneNumber_*", "the carrier's service line"),
    (PRODUCER_PHONE, "NamedInsured_Primary_PhoneNumber_*", "the producer's phone"),
    (CO_TAX_ACCOUNT, "NamedInsured_TaxIdentifier_*", "an 8-digit state tax account"),
    (USDOT, "NamedInsured_TaxIdentifier_*", "a 7-digit USDOT number"),
    (GL_CODE, "NamedInsured_NAICSCode_*", "a GL class code in the NAICS box"),
    ("$4,610,000", "CommercialStructure_AnnualRevenueAmount_*", "the PROJECTED revenue"),
    (TOTAL_PAYROLL, "CommercialStructure_AnnualRevenueAmount_*", "payroll is not revenue"),
    ("$4,250,000", "CommercialStructure_AnnualRevenueAmount_*",
     "the COMPANY total - each premises carries its own share"),
    (SEASONAL_TEMPS, "BusinessInformation_PartTimeEmployeeCount_*", "agency temps"),
    (LOSS_OLD["paid"], "LossHistory_PaidAmount_*", "the OLD valuation's paid"),
    (LOSS_OLD["reserved"], "LossHistory_ReservedAmount_*", "the OLD valuation's reserve"),
    (TOTAL_INCURRED, "LossHistory_TotalAmount_A", "paid + reserved is INCURRED"),
    (LANDLORD, "AdditionalInterest_FullName_*", "the landlord is no interest"),
    (LANDLORD, "NamedInsured_FullName_*", "the landlord is not a named insured"),
    (PARENT_ORG, "NamedInsured_FullName_*", "the PARENT is not a named insured"),
    (AGENCY_CUSTOMER_ID, "Producer_CustomerIdentifier_A", "another agency's customer id"),
]

# ── Customer job sites - where crews WORK, never a premises ─────────────────
_STREETS = ["Tennyson St", "E Colfax Ave", "E Orchard Rd", "E Alameda Pkwy", "Pearl St",
            "Sheridan Blvd", "W 11th Ave", "W Jefferson Ave", "E 40th Ave", "S Syracuse St",
            "Stout St", "Quebec St", "E Arapahoe Rd", "Steele St", "Justice Way",
            "S Harrison St", "W 44th Ave", "E Crestline Cir", "E 1st Ave", "W 120th Ave",
            "17th St", "E Mexico Ave", "Wewatta St", "Mt Pyramid Ct", "E 32nd Ave",
            "S Ulster St", "W 29th Ave", "E Union Ave", "Blake St", "Lawrence St"]
_CITIES = [("Denver", "80202"), ("Aurora", "80012"), ("Lakewood", "80226"),
           ("Centennial", "80112"), ("Boulder", "80302"), ("Westminster", "80031"),
           ("Englewood", "80113"), ("Greenwood Village", "80111"), ("Broomfield", "80021"),
           ("Castle Rock", "80109"), ("Wheat Ridge", "80033"), ("Littleton", "80120")]
_SCOPES = ["Tenant finish - retail bay", "Panel replacement", "Office lighting retrofit",
           "Service upgrade 400A", "Restaurant kitchen circuits", "Parking-lot lighting",
           "Condominium unit rewire", "Warehouse high-bay lighting", "Dock-door controls",
           "Data-room power", "Emergency lighting inspection", "Medical office build-out",
           "EV charger installation", "Generator transfer switch", "Fire-alarm power"]
JOB_SITES = [(f"{1000 + (i * 173) % 8900} {_STREETS[i % len(_STREETS)]}",
              _CITIES[i % len(_CITIES)][0], _CITIES[i % len(_CITIES)][1],
              _SCOPES[(i * 7) % len(_SCOPES)]) for i in range(120)]

CERT_HOLDERS = [
    ("Mortenson Construction", "1621 18th St, Suite 300", "Denver", "80202"),
    ("Saunders Construction LLC", "86 Inverness Pl N", "Englewood", "80112"),
    ("GH Phipps Construction Companies", "1080 W Hampden Ave", "Englewood", "80110"),
    ("Hensel Phelps", "420 6th Ave", "Greeley", "80631"),
    ("PCL Construction Services Inc", "2000 S Colorado Blvd", "Denver", "80222"),
    ("Haselden Construction", "6950 S Potomac St", "Centennial", "80112"),
    ("Pinkard Construction Company", "9195 W 6th Ave", "Lakewood", "80215"),
    ("Adolfson & Peterson Construction", "797 Ventura St", "Aurora", "80011"),
    ("Swinerton Builders", "1420 Wynkoop St", "Denver", "80202"),
    ("Milender White", "12655 W 54th Dr", "Arvada", "80002"),
    ("Brinkmann Constructors", "4990 Pearl East Cir", "Boulder", "80301"),
    ("Shaw Construction LLC", "300 Kalamath St", "Denver", "80223"),
    ("Cushman & Wakefield Property Mgmt", "1401 Lawrence St", "Denver", "80202"),
    ("Highwoods Realty LP", "8101 E Prentice Ave", "Greenwood Village", "80111"),
    ("Lincoln Property Company", "1801 Broadway", "Denver", "80202"),
    ("Denver Public Schools Facilities", "1860 Lincoln St", "Denver", "80203"),
    ("Aurora Public Schools", "1085 Peoria St", "Aurora", "80011"),
    ("Cherry Creek Shopping Center LLC", "3000 E 1st Ave", "Denver", "80206"),
    ("Kaiser Permanente Colorado", "10350 E Dakota Ave", "Denver", "80247"),
    ("UCHealth Facilities", "12401 E 17th Ave", "Aurora", "80045"),
    ("Brookfield Residential", "6465 S Greenwood Plaza", "Centennial", "80111"),
    ("Hines Interests LP", "1144 15th St", "Denver", "80202"),
    ("Jones Lang LaSalle Americas", "1225 17th St", "Denver", "80202"),
    ("Colliers International Denver", "4643 S Ulster St", "Denver", "80237"),
    ("City of Westminster", "4800 W 92nd Ave", "Westminster", "80031"),
    ("Boulder Valley School District", "6500 Arapahoe Rd", "Boulder", "80303"),
    ("Arapahoe County Facilities", "5334 S Prince St", "Littleton", "80120"),
    ("Western Sheet Metal Inc", "7250 E 49th Ave", "Commerce City", "80022"),
]

WIP = [(f"{24 + i // 12}-{100 + i * 7:03d}", f"{_STREETS[i % 30].split()[-2]} "
        f"{_SCOPES[i % 15].lower()}", f"${(i * 97_313) % 1_300_000 + 48_000:,}",
        f"${(i * 41_117) % 600_000:,}", f"{(i * 13) % 100}%") for i in range(30)]
WIP_BACKLOG = "${:,}".format(sum(int(r[2].strip("$").replace(",", "")) for r in WIP))
MONTHLY_REVENUE_FY2025 = [
    ("Oct 2024", "$318,000"), ("Nov 2024", "$296,500"), ("Dec 2024", "$281,000"),
    ("Jan 2025", "$302,400"), ("Feb 2025", "$311,800"), ("Mar 2025", "$349,600"),
    ("Apr 2025", "$372,100"), ("May 2025", "$388,900"), ("Jun 2025", "$401,300"),
    ("Jul 2025", "$396,700"), ("Aug 2025", "$414,200"), ("Sep 2025", "$417,500"),
]

DECOYS += [
    (WIP_BACKLOG, "CommercialStructure_AnnualRevenueAmount_*", "the WIP backlog"),
    (CERT_HOLDERS[0][0], "AdditionalInterest_FullName_*", "a certificate HOLDER"),
    (CERT_HOLDERS[0][0], "NamedInsured_FullName_*", "a certificate holder"),
    (LOSS_PAYEE_B, "AdditionalInterest_FullName_B",
     "ACORD: 'as used here, this is the name of the TRUST' - not a second interest"),
]

SCANNED_ONLY = sorted(
    [f"CommercialPolicy_Question_{c}Code_A" for c, q in QUESTIONS.items() if q["scanned"]]
    + ["NamedInsured_LegalEntity_MemberManagerCount_A", "AdditionalInterest_FullName_B"])

ABSENT_BY_DESIGN = [
    "a policy number, premium, deposit or minimum premium for the policy being QUOTED",
    "any aircraft, airport, boat or scheduled item for the additional interest",
    "a resolution for the fire-code violation - service is only SCHEDULED",
    "a second occurrence under questions 8, 9 or 10",
    "any claim before 2023 in the five-year loss history",
]
