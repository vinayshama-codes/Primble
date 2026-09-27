"""
_a125_data.py - SINGLE SOURCE OF TRUTH for the ACORD 125 full-form test kit.

Both the document generator and the answer key are built from the constants
below, so a value can never be printed in the PDF and expected as something
different in the key.

THE ACCOUNT
-----------
Meridian Ironworks & Mechanical, LLC - a Portland, Oregon commercial mechanical
and structural-steel contractor, submitting a RENEWAL as a QUOTE to a new
carrier effective 10/01/2026. The package it is replacing is written by a
different carrier, with the umbrella on a third. That shape is deliberate: it is
the commonest real upload and it is the one that separates

    "the policy being applied for"   (ACORD 125 page 1)
    "the policy expiring"            (ACORD 125 prior-carrier grid)

which is the distinction Brent's own answer key (`125_reference/`) is built on.

WHAT IS DELIBERATELY ABSENT
---------------------------
Listed in ABSENT_BY_DESIGN at the bottom. Nothing below states them, so any
value that reaches those boxes was invented. That is the point of the kit.

Read `271page_test_data/README-A125-HOW-TO-TEST.md`.
"""
from __future__ import annotations

# ═════════════════════════════════════════════════════════════════════════════
# 1. THE SUBMISSION - what the 125 page 1 is about
# ═════════════════════════════════════════════════════════════════════════════
FORM_DATE          = "08/24/2026"          # date the submission was prepared

PRODUCER           = "Willamette Bay Risk Partners, LLC"
PRODUCER_L1        = "4420 SW Corbett Ave"
PRODUCER_L2        = "Suite 610"
PRODUCER_CITY      = "Portland"
PRODUCER_STATE     = "OR"
PRODUCER_ZIP       = "97239"
PRODUCER_CONTACT   = "Priscilla Vandermeer"
PRODUCER_PHONE     = "(503) 555-0118"
PRODUCER_EMAIL     = "pvandermeer@willamettebayrisk.com"

# The carrier the submission is GOING TO. Named by the broker's own cover sheet,
# which is what makes it legitimate for the 125 page-1 CARRIER box.
CARRIER            = "Northbridge Atlantic Insurance Company"
CARRIER_NAIC       = "41394"

STATUS             = "QUOTE"
PROPOSED_EFF       = "10/01/2026"
PROPOSED_EXP       = "10/01/2027"

# ═════════════════════════════════════════════════════════════════════════════
# 2. THE EXPIRING PROGRAMME - prior-carrier grid, never page 1
# ═════════════════════════════════════════════════════════════════════════════
EXP_CARRIER        = "Cascadia Harbor Mutual Insurance Company"
EXP_CARRIER_NAIC   = "26251"
EXP_CARRIER_SHORT  = "Cascadia Harbor Mutual"          # spelling variant in the doc
EXP_CARRIER_ADDR   = "1000 SW Broadway, Suite 2400, Portland, OR 97205"
EXP_CARRIER_PHONE  = "(800) 555-0400"                  # OWNERSHIP decoy
EXP_CARRIER_WEB    = "www.cascadiaharbor.com"          # OWNERSHIP decoy
EXP_ACCOUNT_NO     = "4471100"                         # 7 digits - FEIN SHAPE decoy

UMB_CARRIER        = "Sentinel Cascade Excess Indemnity Company"
UMB_CARRIER_NAIC   = "38954"

EXP_EFF            = "10/01/2025"
EXP_EXP            = "10/01/2026"

# Per-line expiring policies. One number per line, two carriers - this is what
# the per-line identity resolver has to keep straight.
EXPIRING_LINES = [
    {"line": "General Liability",  "carrier": EXP_CARRIER, "naic": EXP_CARRIER_NAIC,
     "policy": "GL 4471102 25",  "premium": "$73,410"},
    {"line": "Commercial Property", "carrier": EXP_CARRIER, "naic": EXP_CARRIER_NAIC,
     "policy": "CF 4471104 25",  "premium": "$41,265"},
    {"line": "Business Auto",      "carrier": EXP_CARRIER, "naic": EXP_CARRIER_NAIC,
     "policy": "BA 4471106 25",  "premium": "$28,940"},
    {"line": "Commercial Umbrella", "carrier": UMB_CARRIER, "naic": UMB_CARRIER_NAIC,
     "policy": "XSU-9920415-25", "premium": "$12,880"},
]
EXP_TOTAL_PREMIUM  = "$156,495"        # 73,410+41,265+28,940+12,880
# Inland Marine is REQUESTED NEW at this renewal - no expiring IM policy.
NEW_LINE_NOTE      = ("Commercial Inland Marine is requested new at this renewal. "
                      "No inland marine coverage is currently in force and no "
                      "prior inland marine policy exists.")

# Year two of the loss/carrier history. Year THREE is deliberately absent.
PRIOR2_CARRIER     = "Pinnacle Grange Insurance Company"
PRIOR2_YEAR        = "2024-2025"
PRIOR2_EFF         = "10/01/2024"
PRIOR2_EXP         = "10/01/2025"
PRIOR2_LINES = [
    {"line": "General Liability",   "policy": "GL 3318740 24", "premium": "$68,150"},
    {"line": "Commercial Property", "policy": "CF 3318742 24", "premium": "$37,900"},
    {"line": "Business Auto",       "policy": "BA 3318744 24", "premium": "$26,475"},
    # NO umbrella row in year two - deliberately absent.
]
PRIOR1_YEAR        = "2025-2026"

# ═════════════════════════════════════════════════════════════════════════════
# 3. NAMED INSUREDS - FOUR stated, ACORD 125 prints THREE (rows A-C)
# ═════════════════════════════════════════════════════════════════════════════
INSUREDS = [
    {   # row A - the first named insured
        "name":  "Meridian Ironworks & Mechanical, LLC",
        "fein":  "93-2841760",
        "entity": "LLC", "members": "4",
        "sic":   "1711", "naics": "238220", "gl_code": "91746",
        "l1": "2250 NW Vaughn St", "l2": "Suite 310",
        "city": "Portland", "state": "OR", "zip": "97210",
        "phone": "(503) 555-0162",
        "web":  "",                       # ABSENT BY DESIGN - never invent one
        "start": "03/08/2007",
    },
    {   # row B
        "name":  "Cedar Bluff Steel Fabricators, Inc.",
        "fein":  "26-0459318",
        "entity": "Corporation", "members": "",
        "sic":   "3441", "naics": "332312", "gl_code": "91580",
        "l1": "811 SE Ironwood Ct", "l2": "",
        "city": "Gresham", "state": "OR", "zip": "97030",
        "phone": "(503) 555-0174",
        "web":  "www.cedarbluffsteel.com",   # B HAS one, A does not - asymmetry
        "start": "07/21/2011",
    },
    {   # row C
        "name":  "Tualatin Valley Mechanical Services, LLC",
        "fein":  "47-3318805",
        "entity": "LLC", "members": "2",
        "sic":   "1711", "naics": "238220", "gl_code": "91746",
        "l1": "15980 SW Upper Boones Ferry Rd", "l2": "",
        "city": "Tigard", "state": "OR", "zip": "97224",
        "phone": "(503) 555-0139",
        "web":  "",
        "start": "02/14/2016",
    },
    {   # OVERFLOW - stated, no slot on the form. Must never displace A/B/C.
        "name":  "Meridian Ironworks Property Holdings, LLC",
        "fein":  "88-2207734",
        "entity": "LLC", "members": "4",
        "sic":   "6512", "naics": "531120", "gl_code": "",
        "l1": "2250 NW Vaughn St", "l2": "Suite 310",
        "city": "Portland", "state": "OR", "zip": "97210",
        "phone": "(503) 555-0162",
        "web":  "",
        "start": "11/30/2019",
    },
]

PARENT_ORG         = "Harbor Line Capital Partners, LLC"
PARENT_PCT         = "82%"
PARENT_RELATION    = "Majority member of the applicant since 03/2019"
SUBSIDIARY_ORG     = "Cedar Bluff Steel Fabricators, Inc."
SUBSIDIARY_PCT     = "100%"
SUBSIDIARY_RELATION = "Wholly owned steel fabrication subsidiary"

# Applicant contacts. Row A complete; row B deliberately has NO e-mail address.
CONTACTS = [
    {"type": "Inspection", "name": "Rosalind Achterberg",
     "phone": "(503) 555-0156", "email": "rachterberg@meridianiw.com",
     "phone_kind": "Business"},
    {"type": "Accounting", "name": "Wendell Pardoe",
     "phone": "(503) 555-0193", "email": "",          # ABSENT BY DESIGN
     "phone_kind": "Business"},
]

# ═════════════════════════════════════════════════════════════════════════════
# 4. PREMISES - FIVE stated, ACORD 125 prints FOUR (rows A-D)
# ═════════════════════════════════════════════════════════════════════════════
LOCATIONS = [
    {"num": "001", "bldg": "001",
     "l1": "2250 NW Vaughn St", "l2": "Suite 310",
     "city": "Portland", "county": "Multnomah", "state": "OR", "zip": "97210",
     "inside": True, "interest": "Tenant",
     "ft": "12", "pt": "3", "revenue": "$6,480,000",
     "occupied": "9,400", "public": "800", "total_area": "26,000",
     "leased_to_others": "N",
     "ops": "Executive offices, project management, estimating and drafting"},
    {"num": "002", "bldg": "001",
     "l1": "811 SE Ironwood Ct", "l2": "",
     "city": "Gresham", "county": "Multnomah", "state": "OR", "zip": "97030",
     "inside": True, "interest": "Owner",
     "ft": "21", "pt": "4", "revenue": "$9,150,000",
     "occupied": "34,000", "public": "0", "total_area": "34,000",
     "leased_to_others": "Y",
     "ops": "Structural steel fabrication shop, paint bay and material yard"},
    {"num": "003", "bldg": "001",
     "l1": "15980 SW Upper Boones Ferry Rd", "l2": "",
     "city": "Tigard", "county": "", "state": "OR", "zip": "97224",  # county ABSENT
     "inside": True, "interest": "Tenant",
     "ft": "8", "pt": "2", "revenue": "$3,270,000",
     "occupied": "5,100", "public": "350", "total_area": "12,000",
     "leased_to_others": "N",
     "ops": "Mechanical service branch, parts counter and small tool storage"},
    {"num": "004", "bldg": "001",
     "l1": "7734 Riverbend Industrial Way", "l2": "",
     "city": "Clackamas", "county": "Clackamas", "state": "OR", "zip": "97015",
     "inside": False, "interest": "Owner",            # the only OUTSIDE city limits
     "ft": "6", "pt": "1", "revenue": "$1,840,000",
     "occupied": "15,500", "public": "0", "total_area": "15,500",
     "leased_to_others": "N",
     "ops": "Equipment yard, vehicle maintenance bay and covered rack storage"},
    {"num": "005", "bldg": "001",                      # OVERFLOW - no row E
     "l1": "4110 Marine Dr", "l2": "",
     "city": "Astoria", "county": "Clatsop", "state": "OR", "zip": "97103",
     "inside": True, "interest": "Tenant",
     "ft": "3", "pt": "1", "revenue": "$740,000",
     "occupied": "4,100", "public": "0", "total_area": "7,200",
     "leased_to_others": "N",
     "ops": "Seasonal coastal staging yard leased March through November"},
]

# ═════════════════════════════════════════════════════════════════════════════
# 5. BUSINESS INFORMATION
# ═════════════════════════════════════════════════════════════════════════════
NATURE_OF_BUSINESS = "Contractor"          # the ONLY nature ticked
TOTAL_REVENUE      = "$21,480,000"         # = 6,480+9,150+3,270+1,840+740 (thousands)
TOTAL_PAYROLL      = "$7,905,000"          # ROLE decoy against revenue
TOTAL_FT           = "50"
TOTAL_PT           = "11"
INSTALL_PCT        = "100%"
INSTALL_OFF_PCT    = "85%"

OPERATIONS = ("Commercial mechanical contracting and structural steel erection. "
              "The applicant designs, fabricates and installs HVAC piping, "
              "process piping, sheet metal duct and structural steel framing "
              "for commercial, institutional and light industrial projects "
              "throughout western Oregon and south-west Washington.")

PRIMARY_OPERATIONS = ("Licensed mechanical and structural contractor. Work "
                      "comprises shop fabrication of piping assemblies and steel "
                      "members at Location 002, followed by field erection and "
                      "installation at customer premises. Service work covers "
                      "planned maintenance, controls replacement and emergency "
                      "repair of installed systems. No residential work, no "
                      "demolition and no work at heights exceeding four storeys.")

OTHER_INSURED_OPERATIONS = ("Cedar Bluff Steel Fabricators, Inc. performs shop fabrication\n"
                            "of structural steel members. Tualatin Valley Mechanical Services,\n"
                            "LLC performs planned maintenance and emergency repair of installed\n"
                            "mechanical systems at customer premises.")

REMARKS = ("The applicant is under common control with "
           "Harbor Line Capital Partners, LLC. Location 005 is a seasonal lease "
           "and is included in values but carries no permanent staff.")

# ═════════════════════════════════════════════════════════════════════════════
# 6. LOSS HISTORY - FOUR claims, ACORD 125 prints THREE (rows A-C)
# ═════════════════════════════════════════════════════════════════════════════
LOSS_YEARS = "5"
LOSSES = [
    {"occurrence": "04/11/2024", "claim": "04/12/2024", "line": "Business Auto",
     "desc": "Company truck struck a parked vehicle in a supplier yard",
     "paid": "$7,320", "reserved": "$0", "subro": "N", "open": "C",
     "claim_no": "CH-2024-118204"},
    {"occurrence": "09/27/2023", "claim": "10/02/2023", "line": "General Liability",
     "desc": "Water intrusion from incomplete roof flashing at customer premises",
     "paid": "$38,900", "reserved": "$12,500", "subro": "N", "open": "O",
     "claim_no": "CH-2023-097755"},
    {"occurrence": "01/15/2023", "claim": "01/16/2023", "line": "Commercial Property",
     "desc": "Wind damage to warehouse roof panels at Location 002",
     "paid": "$22,140", "reserved": "$0", "subro": "Y", "open": "C",
     "claim_no": "CH-2023-088310"},
    {"occurrence": "06/08/2022", "claim": "06/09/2022",     # OVERFLOW - no row D
     "line": "Commercial Inland Marine",
     "desc": "Theft of portable welding units from an open job site",
     "paid": "$9,450", "reserved": "$0", "subro": "N", "open": "C",
     "claim_no": "PG-2022-041266"},
]
TOTAL_PAID     = "$77,810"     # 7,320+38,900+22,140+9,450  <- the BOX wants this
TOTAL_INCURRED = "$90,310"     # paid + reserved - a DIFFERENT concept, the decoy

# ═════════════════════════════════════════════════════════════════════════════
# 7. ADDITIONAL INTERESTS - the block with no canonical fact behind it
# ═════════════════════════════════════════════════════════════════════════════
INTERESTS = [
    {"name": "Ironbridge Capital Leasing Corporation",
     "interest": "Loss Payee", "rank": "1",
     "l1": "900 SW 5th Ave", "l2": "Suite 2100",
     "city": "Portland", "state": "OR", "zip": "97204",
     "account": "7741-LP-02", "loan": "$412,000",
     "phone": "(503) 555-0221", "email": "servicing@ironbridgecap.com",
     "item": "Fabrication equipment at Location 002",
     "loc": "002", "cert_required": "Y", "reason": "Equipment finance agreement"},
    {"name": "Vaughn Street Holdings LP",
     "interest": "Mortgagee", "rank": "",
     "l1": "1 SW Columbia St", "l2": "Suite 1800",
     "city": "Portland", "state": "OR", "zip": "97204",
     "account": "", "loan": "",
     "phone": "", "email": "",
     "item": "", "loc": "001", "cert_required": "", "reason": ""},
]

# ═════════════════════════════════════════════════════════════════════════════
# 8. THE FIFTEEN UNDERWRITING QUESTIONS (ACORD 125 page 3)
# ═════════════════════════════════════════════════════════════════════════════
# `answer` None means THE DOCUMENT NEVER ADDRESSES IT. Brent's flagship rule:
# blank is not "No". Those boxes must ship EMPTY, not "N".
QUESTIONS = {
    "AAI": {"n": "1a", "q": "Is the applicant a subsidiary of another entity?",
            "answer": "Y",
            "text": "The applicant is a subsidiary of Harbor Line Capital Partners, "
                    "LLC, which holds an 82% membership interest."},
    "AAJ": {"n": "1b", "q": "Does the applicant have any subsidiaries?",
            "answer": "Y",
            "text": "The applicant wholly owns Cedar Bluff Steel Fabricators, Inc."},
    "KAA": {"n": "2", "q": "Is a formal safety program in operation?",
            "answer": "Y",
            "text": "A written safety manual is maintained and a Director of Safety "
                    "is employed full time. Safety meetings are held monthly."},
    "ABC": {"n": "3", "q": "Any exposure to flammables, explosives, chemicals?",
            "answer": "Y",
            "text": "Oxygen, acetylene and propane cylinders are stored in a "
                    "ventilated exterior cage at Location 002. There is no bulk "
                    "flammable liquid storage at any location."},
    "AAH": {"n": "4", "q": "Any other insurance with this company?",
            "answer": "N",
            "text": "The applicant carries no other policies with Northbridge "
                    "Atlantic Insurance Company."},
    "AAC": {"n": "5", "q": "Any policy or coverage declined, cancelled or non-renewed?",
            "answer": "N",
            "text": "No policy or coverage has been declined, cancelled or "
                    "non-renewed in the past three years."},
    "AAD": {"n": "6", "q": "Any past losses or claims relating to sexual abuse or "
                           "molestation allegations, discrimination or negligent hiring?",
            "answer": "N",
            "text": "There have been no losses or claims of this description."},
    "KAB": {"n": "7", "q": "Has any applicant been indicted for or convicted of fraud, "
                           "bribery or arson?",
            "answer": "N",
            "text": "No principal or officer of the applicant has been indicted for "
                    "or convicted of any such offence."},
    "AAF": {"n": "8", "q": "Any uncorrected fire code violations?",
            "answer": "Y",
            "text": "Gresham Fire Marshal notice dated 05/19/2025 cites an obstructed "
                    "sprinkler head in the mezzanine rack area at Location 002. "
                    "Abatement is scheduled; the premises has not yet been "
                    "re-inspected.",
            "occurrence": "05/19/2025",
            "resolution_date": "",           # NOT resolved - must stay blank
            "resolution": ""},
    "KAK": {"n": "9", "q": "Has applicant had a foreclosure, repossession or bankruptcy?",
            "answer": None,                  # NEVER ADDRESSED - must ship BLANK
            "text": ""},
    "KAL": {"n": "10", "q": "Has applicant had a judgment or lien?",
            "answer": "Y",
            "text": "A mechanics lien was recorded against the applicant on "
                    "08/14/2023 in connection with a disputed retainage claim on a "
                    "completed project. The lien was released on 02/27/2024 "
                    "following settlement.",
            "occurrence": "08/14/2023",
            "resolution_date": "02/27/2024",
            "resolution": "Lien released following negotiated settlement of retainage"},
    "ABB": {"n": "11", "q": "Has business been placed in a trust?",
            "answer": "N",
            "text": "The business has not been placed in a trust."},
    "KAC": {"n": "12", "q": "Any foreign operations or foreign products?",
            "answer": None,                  # NEVER ADDRESSED - must ship BLANK
            "text": ""},
    "KAM": {"n": "13", "q": "Does applicant have other business ventures for which "
                            "coverage is not requested?",
            "answer": "N",
            "text": "The principals conduct no other business ventures."},
    "KAN": {"n": "14", "q": "Does applicant own, lease or operate any drones?",
            "answer": "Y",
            "text": "The applicant owns two DJI Matrice 300 RTK unmanned aircraft "
                    "used for rooftop survey and progress photography by two "
                    "Part 107 certificated employees."},
    "KAO": {"n": "15", "q": "Does applicant hire others to operate drones?",
            "answer": "N",
            "text": "The applicant does not engage third parties to operate drones."},
}

# Safety programme detail (question 2's dependent block).
SAFETY = {
    "manual": True,            # written safety manual
    "position": True,          # designated safety position
    "meetings": True,          # monthly meetings
    "osha": None,              # NEVER ADDRESSED - must ship BLANK, not "N"
    "other": None,             # NEVER ADDRESSED
    "director": "Ignatius Broadwell",
}

# ═════════════════════════════════════════════════════════════════════════════
# 9. LINES OF BUSINESS - carried, and DECLARED ABSENT
# ═════════════════════════════════════════════════════════════════════════════
LINES_CARRIED = [
    "Commercial General Liability",
    "Commercial Property",
    "Business Auto",
    "Commercial Umbrella",
    "Commercial Inland Marine",
]
# Each of these is NAMED in the document next to a denial. The words are present;
# the coverage is not. Ticking any of their boxes is the GRANT defect.
LINES_DECLINED = [
    ("Crime and Fidelity",     "NO COVERAGE"),
    ("Workers Compensation",   "Not covered under this programme"),
    ("Liquor Liability",       "Not applicable to this risk"),
    ("Cyber and Privacy",      "Coverage declined by the applicant"),
    ("Boiler and Machinery",   "NO COVERAGE"),
]

# What the broker says is attached to the submission.
ATTACHMENTS_STATED = [
    "Contractors Supplement",
    "Statement of Values",
    "Loss Summary Report",
    "Vehicle Schedule",
    "Driver Information Schedule",
]

AUDIT_PERIOD = "Annual"

# ═════════════════════════════════════════════════════════════════════════════
# 10. DELIBERATE ABSENCES - nothing in this document states any of these
# ═════════════════════════════════════════════════════════════════════════════
ABSENT_BY_DESIGN = [
    "applicant website for the FIRST named insured (row B has one, row A does not)",
    "producer fax number",
    "agency code / sub-code / customer identifier",
    "producer national identifier (NPN) and state licence number",
    "underwriter name and underwriter office",
    "billing plan, payment plan, deposit, minimum premium",
    "policy premium for the policy being applied for (it is a quote)",
    "a policy number for the policy being applied for",
    "county for Location 003 (Tigard)",
    "e-mail address for the ACCOUNTING contact",
    "question 9 - foreclosure / repossession / bankruptcy",
    "question 12 - foreign operations",
    "the OSHA element of the safety programme",
    "prior carrier year three (only two years are documented)",
    "an umbrella row in prior carrier year two",
    "a resolution date for the open fire-code violation",
]

# ═════════════════════════════════════════════════════════════════════════════
# 11. INVENTION DECOYS - real values in the document that must NOT be borrowed
# ═════════════════════════════════════════════════════════════════════════════
# Each entry: (value, the boxes it must never reach, why it is tempting)
DECOYS = [
    (EXP_CARRIER_WEB,   "NamedInsured_Primary_WebsiteAddress_*",
     "the carrier's own website, printed in 60 page headers - it out-repeats "
     "everything the applicant states"),
    (EXP_CARRIER_PHONE, "NamedInsured_Primary_PhoneNumber_*",
     "the carrier's service line, printed on every declarations page"),
    (PRODUCER_PHONE,    "NamedInsured_Primary_PhoneNumber_*",
     "the producer's phone sits beside the insured block in a two-column layout"),
    (EXP_ACCOUNT_NO,    "NamedInsured_TaxIdentifier_*",
     "a 7-digit account number in a 9-digit FEIN box - the SHAPE defect"),
    ("CG 21 47 12 07",  "Policy_PolicyNumberIdentifier_A",
     "an ISO endorsement form number reads like a policy number"),
    ("GL 4471102 25",   "Policy_PolicyNumberIdentifier_A",
     "the EXPIRING policy number in the box for the policy being applied for"),
    (EXP_CARRIER,       "Insurer_FullName_A",
     "the expiring carrier where the receiving carrier belongs"),
    ("$73,410",         "GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A",
     "the expiring GL premium in a page-one premium box on a quote"),
    (TOTAL_PAYROLL,     "CommercialStructure_AnnualRevenueAmount_*",
     "payroll in a revenue box - the MEANING defect"),
    ("91746",           "NamedInsured_NAICSCode_*",
     "a GL class code in a NAICS box"),
    (PRIOR2_CARRIER,    "Insurer_FullName_A",
     "a carrier from two years ago as the submission carrier"),
]
