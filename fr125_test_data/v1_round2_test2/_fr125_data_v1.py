"""
_fr125_data.py - the SINGLE SOURCE OF TRUTH for the Front Range ACORD 125 kit.

WHERE THE VALUES COME FROM
--------------------------
Every expected value below is the CLIENT'S, copied from their own answer key
(`125_reference/ACORD 125 - field completition 8-19-26.docx`, extracted to
`125_reference/_extracted.txt`). That is the point of this kit: the Meridian kit
grades us against an answer sheet I wrote, so a box I misunderstood is scored
"correct" against my own mistake. This one grades us against theirs.

The client supplied the ANSWERS, not the DOCUMENTS. Everything the documents
say - the dec pages, loss runs, questionnaire, census, job list - is written
here so that each client answer is actually stated somewhere a reader could find
it. Their own rule governs that: "If the source material does not establish the
answer to Question 9, Primble cannot check N." So every N below is printed.

WHAT IS DELIBERATELY HARD
-------------------------
Values are stated in the formats that break extraction: abbreviated table
headers, riffled columns, letter-spaced teletype, two-column drift, a landscape
schedule, figures spelled three ways, and SCANNED pages with no text layer at
all. Some facts live ONLY on a scanned page; those are tagged `SCANNED_ONLY` so
a miss can be attributed to OCR rather than to extraction.

WHAT IS DELIBERATELY TEMPTING
-----------------------------
`DECOYS` are real strings in the document that belong in a DIFFERENT box. They
are scoped to the boxes they are forbidden in, never globally.
"""
from __future__ import annotations

# ── The submission: a NEW-BUSINESS QUOTE to a new carrier ────────────────────
# The client: CARRIER = "the carrier receiving submission"; NAIC "only populate
# if carrier/NAIC is verified"; UNDERWRITER "if submission is directed to one";
# STATUS = QUOTE; POLICY NUMBER blank for a new-business quote.
CARRIER             = "Granite Arch Casualty Company"    # receiving the submission
CARRIER_NAIC        = ""                                  # NOT stated anywhere
UNDERWRITER         = "Dana Whitfield"
UNDERWRITER_OFFICE  = "Denver Branch"
PROPOSED_EFF        = "10/01/2026"
PROPOSED_EXP        = "10/01/2027"
BILLING             = "Direct"         # client: "Direct, if known"
PAYMENT_PLAN_WORD   = "Annual"         # client: "Annual, if requested/known"
PAYMENT_PLAN_CODE   = "AN"             # ACORD tooltip: "AN - Annual, MO - Monthly..."

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
AGENCY_CUSTOMER_ID  = "FREC-001"       # another agency's identifier - see DECOYS

# ── The first named insured ──────────────────────────────────────────────────
NAME                = "Front Range Electrical Contractors LLC"
FEIN                = "12-3456789"
ENTITY              = "LLC"
NAICS               = "238210"
SIC                 = "1731"
GL_CODE             = "92478"          # from the GL dec's classification schedule
MAIL_L1             = "8000 Commerce Way"
MAIL_CITY           = "Denver"
MAIL_STATE          = "CO"
MAIL_ZIP            = "80216"
BUS_PHONE           = "303-555-0175"
WEBSITE             = "www.example-electrical.com"
START_DATE          = "06/15/2014"
START_DATE_WORDS    = "June 15, 2014"
NATURE              = "Contractor"

# ── Contacts (page 2) ────────────────────────────────────────────────────────
CONTACTS = [
    {"type": "Inspection", "name": "John Smith",  "phone": "303-555-0188",
     "email": "john@example-electrical.com"},
    {"type": "Accounting", "name": "Sarah Jones", "phone": "303-555-0190",
     "email": "accounting@example-electrical.com"},
]

# ── The one premises ─────────────────────────────────────────────────────────
LOC = {
    "num": "1", "bldg": "1", "l1": "8000 Commerce Way", "city": "Denver",
    "county": "Denver", "state": "CO", "zip": "80216", "inside": True,
    "interest": "Tenant", "ft": "18", "pt": "2", "revenue": "$4,250,000",
    "occupied": "5,000", "public": "500", "total_area": "15,000",
    "leased_to_others": "N",
    "ops": ("Administrative office, electrical contracting warehouse and material "
            "storage. Crews perform commercial and residential electrical "
            "installation, wiring, panel upgrades, troubleshooting and service "
            "work at customer locations."),
}

PRIMARY_OPERATIONS = (
    "Licensed electrical contractor performing commercial and residential "
    "electrical installation, repair and service. Work includes new wiring, "
    "service upgrades, panel replacement, lighting and electrical "
    "troubleshooting. No utility-line construction or electrical generation "
    "operations.")

INSTALL_PCT         = "100%"
INSTALL_OFF_PCT     = "90%"
RETAIL_PCT          = "0%"             # the row LABEL on ACORD 125 - no box of its own

# ── The fifteen questions: the client's answers, all STATED in the document ──
# `scanned` = the answer is printed ONLY on the scanned second page of the
# signed questionnaire. A miss there is an OCR miss before it is anything else.
QUESTIONS = {
    "AAI": {"n": "1a", "answer": "N", "scanned": False,
            "q": "Is the applicant a subsidiary of another entity?",
            "stated": "The applicant is not owned or controlled by any other entity."},
    "AAJ": {"n": "1b", "answer": "N", "scanned": False,
            "q": "Does the applicant have any subsidiaries?",
            "stated": "The applicant has no subsidiaries."},
    "KAA": {"n": "2", "answer": "Y", "scanned": False,
            "q": "Is a formal safety program in operation?",
            "stated": ("Written safety manual; designated safety manager; "
                       "monthly safety meetings.")},
    "ABC": {"n": "3", "answer": "Y", "scanned": False,
            "q": "Any exposure to flammables, explosives, chemicals?",
            "stated": ("Limited quantities of common jobsite adhesives and "
                       "solvents stored in approved containers.")},
    "AAH": {"n": "4", "answer": "N", "scanned": False,
            "q": "Any other insurance with this company?",
            "stated": f"No policies are currently carried with {CARRIER}."},
    "AAC": {"n": "5", "answer": "N", "scanned": False,
            "q": "Any policy or coverage declined, cancelled or non-renewed "
                 "during the prior three years?",
            "stated": "No coverage has been declined, cancelled or non-renewed."},
    "AAD": {"n": "6", "answer": "N", "scanned": False,
            "q": "Any past losses or claims relating to sexual abuse or "
                 "molestation allegations, discrimination or negligent hiring?",
            "stated": "No such losses or claims."},
    "KAB": {"n": "7", "answer": "N", "scanned": False,
            "q": "Any applicant indicted for or convicted of fraud, bribery or "
                 "arson in the last five years?",
            "stated": "No applicant has been indicted for or convicted of any "
                      "such crime."},
    "AAF": {"n": "8", "answer": "N", "scanned": True,
            "q": "Any uncorrected fire and/or safety code violations?",
            "stated": "There are no uncorrected fire or safety code violations."},
    "KAK": {"n": "9", "answer": "N", "scanned": True,
            "q": "Foreclosure, repossession or bankruptcy in the last five years?",
            "stated": "No foreclosure, repossession or bankruptcy."},
    "KAL": {"n": "10", "answer": "N", "scanned": True,
            "q": "Any judgement or lien in the last five years?",
            "stated": "No judgments or liens."},
    "ABB": {"n": "11", "answer": "N", "scanned": True,
            "q": "Has the business been placed in a trust?",
            "stated": "The business has not been placed in a trust."},
    "KAC": {"n": "12", "answer": "N", "scanned": True,
            "q": "Any foreign operations or foreign products?",
            "stated": "No foreign operations and no foreign products."},
    "KAM": {"n": "13", "answer": "N", "scanned": True,
            "q": "Other business ventures for which coverage is not requested?",
            "stated": "No other business ventures."},
    "KAN": {"n": "14", "answer": "N", "scanned": True,
            "q": "Does the applicant own, lease or operate any drones?",
            "stated": "The applicant does not own, lease or operate drones."},
    "KAO": {"n": "15", "answer": "N", "scanned": True,
            "q": "Does the applicant hire others to operate drones?",
            "stated": "The applicant does not hire others to operate drones."},
}
SAFETY_MANAGER = "Luis Ortega"

# ── Prior carrier: ONLY the current year is substantiated ────────────────────
# Client: "populate only the year it can substantiate and request the missing
# prior-period information. It should not manufacture three or five years of
# carrier history." The loss runs cover five years but print no policy numbers
# or premiums for earlier terms - rows B and C must stay EMPTY.
CUR_CARRIER         = "Timberline Mutual Insurance Company"
CUR_CARRIER_SHORT   = "Timberline Mutual"
CUR_CARRIER_NAIC    = "27413"
CUR_CARRIER_WEB     = "www.timberlinemutual-ins.com"
CUR_CARRIER_PHONE   = "(800) 555-0147"
CUR_EFF             = "10/01/2025"
CUR_EXP             = "10/01/2026"
PRIOR_YEAR          = "2025"
CURRENT_LINES = [
    {"line": "General Liability",   "grid": "GeneralLiability",
     "policy": "GL-123456", "premium": "$18,450"},
    {"line": "Business Auto",       "grid": "Automobile",
     "policy": "BA-456789", "premium": "$14,200"},
    {"line": "Commercial Property", "grid": "Property",
     "policy": "CP-567890", "premium": "$8,750"},
    {"line": "Commercial Umbrella", "grid": "OtherLine",
     "policy": "CU-678901", "premium": "$4,100"},
]
CUR_TOTAL_PREMIUM   = "$45,500"

# Workers compensation is carried with a THIRD carrier and is NOT being applied
# for. It appears on the umbrella's schedule of underlying and on its own
# summary page. It must not take the OTHER column from the umbrella, and it must
# not tick a line-of-business box.
WC_CARRIER          = "Pinecrest Employers Assurance Company"
WC_POLICY           = "WC-7730914"
WC_PREMIUM          = "$21,960"

# ── Loss history: ONE claim, reported on two valuations ──────────────────────
# The same claim appears twice: the carrier's current loss run (valued
# 08/31/2026, CLOSED) and an old FAXED copy (valued 06/30/2024, still OPEN).
# The latest valuation is the truth; the claim must not become two rows, and
# the old paid / reserved / open figures must not survive.
LOSS = {"occurrence": "03/28/2024", "claim": "03/28/2024",
        "line": "Business Auto",
        "desc": "Insured vehicle rear-ended third party at traffic light",
        "paid": "$4,850", "reserved": "$0", "subro": "N", "open": "N",
        "claim_no": "BA-24-00731"}
LOSS_OLD = {"paid": "$3,200", "reserved": "$1,650", "open": "Y",
            "valued": "06/30/2024"}
LOSS_VALUED = "08/31/2026"
LOSS_YEARS = "5"
TOTAL_PAID = "$4,850"

# ── Company figures that are NOT the premises figures ────────────────────────
REVENUE_BY_YEAR = [("FY2023", "$3,880,000"), ("FY2024", "$4,020,000"),
                   ("FY2025", "$4,250,000"), ("FY2026 projected", "$4,610,000")]
TOTAL_PAYROLL    = "$1,640,000"
SEASONAL_TEMPS   = "6"                 # staffing-agency labour, not employees
HEADCOUNT_TOTAL  = "20"

# ── Things that exist in the documents and must reach NO box ─────────────────
LANDLORD         = "Commerce Way Partners LP"
LANDLORD_ADDR    = "1450 Wynkoop Street, Suite 300, Denver, CO 80202"
LANDLORD_PHONE   = "303-555-0122"
CO_TAX_ACCOUNT   = "12345678"          # 8-digit state sales-tax account
USDOT            = "3456789"           # 7 digits - not a FEIN
CONTRACTOR_LIC   = "EC.0112345"

# Every string here is PRINTED in the document and forbidden in the boxes named.
# (value, scope, why)
DECOYS = [
    (CUR_CARRIER, "Insurer_FullName_A",
     "the CURRENT carrier, on every dec header, where the RECEIVING carrier belongs"),
    (CUR_CARRIER_NAIC, "Insurer_NAICCode_A",
     "the current carrier's NAIC - the receiving carrier's NAIC is never stated"),
    ("GL-123456", "Policy_PolicyNumberIdentifier_A",
     "an EXPIRING policy number in the box for the policy being applied for"),
    ("CG 20 11 04 13", "Policy_PolicyNumberIdentifier_A",
     "an ISO form number reads like a policy number"),
    ("$18,450", "GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A",
     "the expiring GL premium on a quote"),
    (CUR_TOTAL_PREMIUM, "Policy_Payment_EstimatedTotalAmount_A",
     "the expiring package total on a quote"),
    (CUR_EFF, "Policy_EffectiveDate_A", "the CURRENT term's start"),
    (CUR_CARRIER_WEB, "NamedInsured_Primary_WebsiteAddress_*",
     "the carrier's website, printed in every running header"),
    (CUR_CARRIER_PHONE, "NamedInsured_Primary_PhoneNumber_*",
     "the carrier's service line, printed in every running header"),
    (PRODUCER_PHONE, "NamedInsured_Primary_PhoneNumber_*",
     "the producer's phone sits beside the applicant block"),
    (CO_TAX_ACCOUNT, "NamedInsured_TaxIdentifier_*",
     "an 8-digit state tax account is not a FEIN"),
    (USDOT, "NamedInsured_TaxIdentifier_*", "a 7-digit USDOT number is not a FEIN"),
    (GL_CODE, "NamedInsured_NAICSCode_*", "a GL class code in the NAICS box"),
    ("$4,610,000", "CommercialStructure_AnnualRevenueAmount_*",
     "the PROJECTED 2026 revenue, not the stated annual figure"),
    (TOTAL_PAYROLL, "CommercialStructure_AnnualRevenueAmount_*",
     "payroll is not revenue"),
    (HEADCOUNT_TOTAL, "BusinessInformation_FullTimeEmployeeCount_*",
     "total headcount is 18 full-time + 2 part-time, not 20 full-time"),
    (SEASONAL_TEMPS, "BusinessInformation_PartTimeEmployeeCount_*",
     "agency temps are not part-time employees"),
    (LOSS_OLD["paid"], "LossHistory_PaidAmount_*",
     "the OLD valuation's paid figure"),
    (LOSS_OLD["reserved"], "LossHistory_ReservedAmount_*",
     "the OLD valuation's reserve - the claim is closed"),
    (WC_CARRIER, "PriorCoverage_OtherLine_InsurerFullName_*",
     "workers comp is not being applied for; the umbrella owns OTHER"),
    (LANDLORD, "AdditionalInterest_FullName_*",
     "the landlord is named in a lease summary, not as an interest on any policy"),
    (LANDLORD, "NamedInsured_FullName_*", "the landlord is not a named insured"),
    (AGENCY_CUSTOMER_ID, "Producer_CustomerIdentifier_A",
     "another agency's customer id - the logged-in agency is not Summit"),
]

# The job sites. Forty-five customer addresses where crews WORK. None is a
# premises of the applicant, so none may reach a premises row.
JOB_SITES = [
    ("4410 Tennyson St", "Denver", "80212", "Tenant finish - retail bay"),
    ("1201 E Colfax Ave", "Denver", "80218", "Panel replacement"),
    ("7600 E Orchard Rd", "Greenwood Village", "80111", "Office lighting retrofit"),
    ("15151 E Alameda Pkwy", "Aurora", "80012", "Service upgrade 400A"),
    ("2800 Pearl St", "Boulder", "80302", "Restaurant kitchen circuits"),
    ("9135 Sheridan Blvd", "Westminster", "80031", "Parking-lot lighting"),
    ("300 W 11th Ave", "Denver", "80204", "Condominium unit rewire"),
    ("6851 W Jefferson Ave", "Lakewood", "80235", "Warehouse high-bay lighting"),
    ("12000 E 40th Ave", "Denver", "80239", "Dock-door controls"),
    ("5500 S Syracuse St", "Greenwood Village", "80111", "Data-room power"),
    ("1600 Stout St", "Denver", "80202", "Emergency lighting inspection"),
    ("3401 Quebec St", "Denver", "80207", "Medical office build-out"),
    ("8100 E Arapahoe Rd", "Centennial", "80112", "Tenant improvement"),
    ("250 Steele St", "Denver", "80206", "Residential service upgrade"),
    ("4000 Justice Way", "Castle Rock", "80109", "Retail fixture circuits"),
    ("1777 S Harrison St", "Denver", "80210", "Troubleshooting - tripping"),
    ("10200 W 44th Ave", "Wheat Ridge", "80033", "Shop compressor circuit"),
    ("7400 E Crestline Cir", "Greenwood Village", "80111", "Generator transfer switch"),
    ("2500 E 1st Ave", "Denver", "80206", "Lighting controls"),
    ("11001 W 120th Ave", "Broomfield", "80021", "Office EV chargers"),
    ("600 17th St", "Denver", "80202", "Suite rewire"),
    ("3900 E Mexico Ave", "Denver", "80210", "Fire-alarm power circuits"),
    ("1400 Wewatta St", "Denver", "80202", "Restaurant service"),
    ("9800 Mt Pyramid Ct", "Englewood", "80112", "Panel upgrade"),
    ("16400 E 32nd Ave", "Aurora", "80011", "Warehouse lighting"),
    ("4600 S Ulster St", "Denver", "80237", "Office tenant finish"),
    ("2100 W 29th Ave", "Denver", "80211", "Residential remodel"),
    ("7800 E Union Ave", "Denver", "80237", "Parking structure lighting"),
    ("13700 E Arapahoe Rd", "Centennial", "80112", "School classroom circuits"),
    ("1050 17th St", "Denver", "80265", "Lobby lighting"),
    ("5050 S Syracuse St", "Denver", "80237", "Data closet"),
    ("8200 S Quebec St", "Centennial", "80112", "Retail signage power"),
    ("300 E Hampden Ave", "Englewood", "80113", "Clinic build-out"),
    ("1860 Blake St", "Denver", "80202", "Loft rewire"),
    ("6400 S Fiddlers Green Cir", "Greenwood Village", "80111", "Office remodel"),
    ("201 Columbine St", "Denver", "80206", "Retail bay"),
    ("4700 N Federal Blvd", "Denver", "80211", "Service call"),
    ("7200 W Alameda Ave", "Lakewood", "80226", "Grocery refrigeration circuits"),
    ("999 18th St", "Denver", "80202", "Tenant finish"),
    ("2600 S Parker Rd", "Aurora", "80014", "Office lighting"),
    ("14200 E Alameda Ave", "Aurora", "80012", "Panel replacement"),
    ("3000 Lawrence St", "Denver", "80205", "Brewery equipment circuits"),
    ("5600 Greenwood Plaza Blvd", "Greenwood Village", "80111", "Suite upgrade"),
    ("10400 E Briarwood Ave", "Centennial", "80112", "Warehouse controls"),
    ("1700 Lincoln St", "Denver", "80203", "Emergency generator test"),
]

# ── Certificate holders - the classic Additional Interest trap ──────────────
# Real packages carry a log of the certificates the agency has issued. Every row
# is a company name and an address, printed beside the word "insured". NONE is
# an additional interest, a named insured or a premises.
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

# Work-in-progress: CONTRACT values, not revenue. The backlog total is a trap.
WIP = [
    ("24-117", "Tennyson retail bay", "$186,400", "$168,900", "91%"),
    ("24-131", "Orchard Rd lighting retrofit", "$412,750", "$290,000", "70%"),
    ("25-004", "Alameda service upgrade", "$96,200", "$96,200", "100%"),
    ("25-019", "Pearl St kitchen circuits", "$74,800", "$51,300", "69%"),
    ("25-022", "Jefferson Ave high-bay", "$238,000", "$121,400", "51%"),
    ("25-040", "Quebec St medical build-out", "$1,180,000", "$655,000", "56%"),
    ("25-058", "Arapahoe Rd tenant improvement", "$355,500", "$102,000", "29%"),
    ("25-061", "Justice Way retail fixtures", "$142,900", "$142,900", "100%"),
    ("25-077", "Crestline transfer switch", "$88,650", "$44,000", "50%"),
    ("25-083", "120th Ave EV chargers", "$524,300", "$210,000", "40%"),
    ("25-090", "Mexico Ave fire-alarm power", "$61,400", "$12,000", "20%"),
    ("25-102", "Wewatta restaurant service", "$118,700", "$98,100", "83%"),
    ("26-003", "32nd Ave warehouse lighting", "$690,000", "$140,000", "20%"),
    ("26-011", "Arapahoe classroom circuits", "$1,375,000", "$95,000", "7%"),
    ("26-015", "Syracuse data closet", "$48,900", "$0", "0%"),
    ("26-021", "Quebec retail signage", "$62,300", "$0", "0%"),
    ("26-026", "Hampden clinic build-out", "$795,300", "$0", "0%"),
]
WIP_BACKLOG = "${:,}".format(sum(int(r[2].strip("$").replace(",", "")) for r in WIP))
# ^ the contract column's total - NOT revenue. Derived, never typed.

MONTHLY_REVENUE_FY2025 = [
    ("Oct 2024", "$318,000"), ("Nov 2024", "$296,500"), ("Dec 2024", "$281,000"),
    ("Jan 2025", "$302,400"), ("Feb 2025", "$311,800"), ("Mar 2025", "$349,600"),
    ("Apr 2025", "$372,100"), ("May 2025", "$388,900"), ("Jun 2025", "$401,300"),
    ("Jul 2025", "$396,700"), ("Aug 2025", "$414,200"), ("Sep 2025", "$417,500"),
]                                   # sums to $4,250,000

DECOYS += [
    (WIP_BACKLOG, "CommercialStructure_AnnualRevenueAmount_*",
     "the work-in-progress BACKLOG is contract value, not annual revenue"),
    (CERT_HOLDERS[0][0], "AdditionalInterest_FullName_*",
     "a certificate HOLDER is not an additional interest"),
    (CERT_HOLDERS[0][0], "NamedInsured_FullName_*",
     "a certificate holder is not a named insured"),
]

# ── Facts that are printed ONLY on a scanned page ────────────────────────────
SCANNED_ONLY = sorted(
    f"CommercialPolicy_Question_{code}Code_A"
    for code, q in QUESTIONS.items() if q["scanned"])

# ── What the document deliberately NEVER states ─────────────────────────────
ABSENT_BY_DESIGN = [
    "the receiving carrier's NAIC code",
    "any audit period (for either the current or the proposed policy)",
    "any policy premium, deposit or minimum premium for the proposed policy",
    "an OSHA statement for the safety programme",
    "a phone type (home / business / cell) for either contact",
    "a secondary phone or e-mail for either contact",
    "a member / manager count for the LLC",
    "any other named insured",
    "any additional interest - every vehicle is owned outright",
    "any prior-carrier policy number or premium before the 2025-26 term",
    "a remark for the REMARKS box",
    "a second address line for the applicant or the premises",
]
