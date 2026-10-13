"""
kit_data.py - the TRUTH for the CH125 kit (Cumberland Hearth & Hospitality Supply).

Every value the answer key expects lives here, once. The documents in
kit_docs.py print these values (and the decoys below) in hard formats; the key
in kit_key.py is built from these same constants, so the key and the documents
can never disagree about a value.

The account is synthetic. Every name, number, address, phone, e-mail, VIN,
licence and FEIN is invented (555 phone numbers, example.com domains).

Rules the key follows (the client's 8-19-26 "field completion" document):
  * the 125 page one is the policy BEING APPLIED FOR - receiving carrier, NAIC
    only if verified, no policy number / premium on a new-business quote;
  * blank is not No - a question the documents never answer stays BLANK and is
    listed as UNRESOLVED (insured confirmation required);
  * prior carrier: only what the documents substantiate;
  * loss history from verified loss runs, latest valuation, total = PAID;
  * "no known losses" narrative never becomes a verified loss history;
  * other named insureds / additional interests only when documented AS such.
"""
from __future__ import annotations

# ════════════════════════════════════════════════════════════════════════════
# THE TRANSACTION
# ════════════════════════════════════════════════════════════════════════════
TODAY = "10/05/2026"
PROPOSED_EFF = "12/01/2026"
PROPOSED_EXP = "12/01/2027"
STALE_PROPOSED_EFF = "11/15/2026"          # the August worksheet - superseded
CUR_EFF, CUR_EXP = "12/01/2025", "12/01/2026"

# the carrier RECEIVING the submission - through an MGA
CARRIER = "Ridgeline Specialty Insurance Company"
CARRIER_NAIC = "41297"
MGA = "Appalachian Risk Underwriters, LLC"
MGA_ADDR = ("800 S Gay St, Suite 1400", "Knoxville", "TN", "37929")
PROGRAM_NAME = "Hospitality Trades Package Program"
PROGRAM_CODE = "HTP-TN"
UNDERWRITER = "Priya Raman"
UNDERWRITER_OFFICE = "Knoxville"
UNDERWRITER_PHONE = "865-555-0122"
UNDERWRITER_EMAIL = "praman@aru-example.com"

BILLING = "Direct"                          # direct bill to the insured
PAYMENT_PLAN_WORD, PAYMENT_PLAN_CODE = "Quarterly", "QT"
PAYMENT_METHOD = "ACH auto-debit"
AUDIT_WORD, AUDIT_CODE = "Annual", "A"
LOSS_YEARS = "5"

# the submitting agency (scored manually against the logged-in account)
AGENCY = "Riverbend Insurance Partners, LLC"
AGENCY_L1, AGENCY_L2 = "401 Church St", "Suite 1700"
AGENCY_CITY, AGENCY_STATE, AGENCY_ZIP = "Nashville", "TN", "37219"
AGENCY_PRODUCER = "Caroline Whitlock"
AGENCY_PHONE = "615-555-0410"
AGENCY_EMAIL = "cwhitlock@riverbend-example.com"
AGENCY_NPN = "19448210"
AGENCY_TN_LICENSE = "2204418"
AGENCY_AMS_CUSTOMER_ID = "CUMBHEA-01"
AGENCY_CARRIER_CODE, AGENCY_CARRIER_SUBCODE = "RIV-0417", "22"

# the PRIOR agency (still printed on the incumbent's paperwork) - decoys
PRIOR_AGENCY = "Volunteer State Insurance Agency, Inc."
PRIOR_AGENCY_CODE = "VSA-2291"
PRIOR_AGENCY_CUSTOMER_ID = "CUMB-0044"
PRIOR_AGENCY_PHONE = "615-555-0333"

# ════════════════════════════════════════════════════════════════════════════
# THE APPLICANT AND THE OTHER NAMED INSURED
# ════════════════════════════════════════════════════════════════════════════
NAME = "Cumberland Hearth & Hospitality Supply, Inc."
SHORT = "Cumberland Hearth"
FORMER_NAME = "Cumberland Restaurant Supply, LLC"          # converted 01/01/2022
CONVERSION_DATE = "01/01/2022"
START_DATE = "03/01/2009"                                  # continuous operation
FEIN = "62-3418806"
NAICS = "423440"
SIC = "5046"
GL_CODE = "12683"                                          # governing class
BUS_PHONE = "615-555-0142"
FAX = "615-555-0149"
WEBSITE = "www.cumberlandhearth-example.com"
MAIL_L1, MAIL_L2 = "P.O. Box 41120", ""
MAIL_CITY, MAIL_STATE, MAIL_ZIP = "Nashville", "TN", "37204-1120"
ENTITY = "Corporation"                                      # a C corporation

SUB = {
    "name": "Cumberland Hearth Service Co., LLC",
    "fein": "47-2290113", "sic": "7699", "naics": "811310", "gl": "91127",
    "phone": "615-555-0143", "web": "www.chhservice-example.com",
    "l1": "1199 Hillsboro Commons Dr", "l2": "Suite 220", "city": "Franklin",
    "state": "TN", "zip": "37067", "members": "1", "formed": "03/15/2018",
    "relationship": "Wholly owned subsidiary - installation and service",
    "pct": "100%",
}
OTHER_INSURED_OPERATIONS = (
    "Cumberland Hearth Service Co., LLC installs, services and repairs commercial "
    "kitchen equipment at customer locations, including preventive maintenance "
    "contracts and 24-hour emergency service; it has no sales of its own beyond "
    "parts used on service calls.")
PRIMARY_OPERATIONS = (
    "Wholesale distributor of commercial kitchen and foodservice equipment, parts "
    "and supplies to restaurants, hotels, schools and institutional kitchens in "
    "Tennessee, Kentucky and northern Alabama. Imports Italian deck ovens and "
    "espresso machines and sells a private-label degreaser made by a contract "
    "blender. Through its subsidiary it installs, services and repairs the "
    "equipment at customer locations. No manufacturing; final electrical and gas "
    "connections are subcontracted to licensed trades.")
INSTALL_PCT = "18%"            # of TOTAL SALES (ACORD's tooltip)
INSTALL_OFF_PCT = "17%"        # of TOTAL SALES, performed off premises
REMARKS = (
    "Seasonal warehouse labor (up to 9 workers, October through December) is "
    "supplied by Harpeth Staffing Solutions, Inc. under a services contract; these "
    "workers are not employees of the applicant and are not included in the "
    "employee counts.")

OWNERS = [("Margaret A. Ellison Revocable Trust", "60%"),
          ("Theodore Lindqvist", "25%"), ("Owen P. Ellison", "15%")]
TRUST_NAME = "Margaret A. Ellison Revocable Trust"          # a SHAREHOLDER, not Q11
JV = {"name": "Music Row Kitchen Rentals, LLC", "pct": "40%",
      "addr": "1601 Division St, Nashville, TN 37203", "fein": "85-1047712",
      "web": "www.musicrowkitchens-example.com", "phone": "615-555-0122"}

# identifiers that are NOT the FEIN (decoys)
SOS_CONTROL = "000817423"      # nine digits - looks like an EIN without the hyphen
DUNS = "07-881-4420"           # nine digits in a 2-3-4 pattern
TN_SALES_TAX = "1003447185"
USDOT = "3217744"
TN_DOL_ACCT = "0447155"

# people
CEO = "Margaret A. Ellison"
CFO = "Theodore Lindqvist"
CFO_PHONE = "615-555-0161"
CONTROLLER = "Denise Okafor"
FACILITIES = "Rafael Quintero"
SAFETY_COORD = "Lorena Vasquez"

CONTACTS = [
    {"type": "Inspection", "name": "Rafael Quintero",
     "phone": "615-555-0177", "phone_type": "Cell",
     "phone2": "615-555-0168", "phone2_type": "Business",
     "email": "rquintero@cumberlandhearth-example.com",
     "email2": "facilities@cumberlandhearth-example.com"},
    {"type": "Accounting", "name": "Denise Okafor",
     "phone": "615-555-0165", "phone_type": "Business",
     "phone2": "615-555-0190", "phone2_type": "Cell",
     "email": "dokafor@cumberlandhearth-example.com",
     "email2": "ap@cumberlandhearth-example.com"},
]
DENISE_CELL_TYPO = "615-555-0109"          # the August worksheet - corrected by e-mail

# ════════════════════════════════════════════════════════════════════════════
# PREMISES - numbered as THIS submission numbers them
# ════════════════════════════════════════════════════════════════════════════
LOCATIONS = [
    {"num": "1", "bldg": "1", "l1": "2850 Kellerman Industrial Pkwy", "l2": "",
     "city": "Nashville", "county": "Davidson", "state": "TN", "zip": "37211",
     "inside": True, "interest": "Owner", "ft": "41", "pt": "6",
     "revenue": "$15,200,000", "occupied": "52,000", "public": "2,400",
     "total_area": "58,000", "leased": "Y",
     "ops": "Headquarters: offices, showroom with test kitchen, and the main "
            "distribution warehouse for commercial kitchen equipment and parts",
     "territory": "004"},
    {"num": "2", "bldg": "1", "l1": "410 Industrial Blvd", "l2": "Suite C",
     "city": "La Vergne", "county": "Rutherford", "state": "TN", "zip": "37086",
     "inside": False, "interest": "Tenant", "ft": "3", "pt": "0",
     "revenue": "$0", "occupied": "12,500", "public": "0",
     "total_area": "50,000", "leased": "N",
     "ops": "Parts depot and overflow storage; no sales and no customer access",
     "territory": "005"},
    {"num": "3", "bldg": "1", "l1": "1199 Hillsboro Commons Dr", "l2": "Suite 220",
     "city": "Franklin", "county": "Williamson", "state": "TN", "zip": "37067",
     "inside": True, "interest": "Tenant", "ft": "22", "pt": "1",
     "revenue": "$3,400,000", "occupied": "3,100", "public": "300",
     "total_area": "24,000", "leased": "N",
     "ops": "Service dispatch office of Cumberland Hearth Service Co., LLC; "
            "technicians report here; small parts cage",
     "territory": "006"},
]
LOC3_STALE_OCCUPIED = "3,400"             # corrected by the lease amendment footnote
CLOSED_LOCATION = {"l1": "1040 Visco Dr", "city": "Nashville", "zip": "37210",
                   "closed": "06/30/2026"}
SUBLEASE_TENANT = "Gallatin Pike Printing Co."      # 6,000 sq ft at location 1
TOTAL_REVENUE = "$18,600,000"
PROJECTED_REVENUE = "$21,100,000"
BACKLOG = "$4,312,600"
PAYROLL_TOTAL = "$4,918,300"
HEADCOUNT_TOTAL = "73"
TEMPS = "9"
BUILDING_VALUE_LOC1 = "$6,900,000"

# ════════════════════════════════════════════════════════════════════════════
# ACORD 125 GENERAL INFORMATION - code -> question, answer, the stated detail
#   answer "" = the documents NEVER answer it: blank + UNRESOLVED
# ════════════════════════════════════════════════════════════════════════════
Q125 = {
    "AAI": {"n": "1a", "q": "Is the applicant a subsidiary of another entity?", "answer": "N"},
    "AAJ": {"n": "1b", "q": "Does the applicant have any subsidiaries?", "answer": "Y"},
    "KAA": {"n": "2", "q": "Is a formal safety program in operation?", "answer": "Y"},
    "ABC": {"n": "3", "q": "Any exposure to flammables, explosives, chemicals?", "answer": "Y",
            "explain": "Propane: up to twelve 33-lb forklift cylinders stored in a locked "
                       "exterior cage at the Kellerman warehouse. Private-label degreaser "
                       "concentrate (sodium hydroxide based, corrosive) stored in sealed "
                       "drums in a bunded chemical room. No explosives."},
    "AAH": {"n": "4", "q": "Any other insurance with this company?", "answer": "Y"},
    "AAC": {"n": "5", "q": "Any policy or coverage declined, cancelled or non-renewed during "
                              "the prior three years?", "answer": "Y"},
    "AAD": {"n": "6", "q": "Any past losses or claims relating to sexual abuse or molestation "
                              "allegations, discrimination or negligent hiring?", "answer": "N"},
    "KAB": {"n": "7", "q": "During the last five years has any applicant been indicted for or "
                              "convicted of any degree of the crime of fraud, bribery, arson?",
            "answer": ""},
    "AAF": {"n": "8", "q": "Any uncorrected fire and/or safety code violations?", "answer": "N"},
    "KAK": {"n": "9", "q": "Has applicant had a foreclosure, repossession, bankruptcy or filed "
                              "for bankruptcy during the last five years?", "answer": ""},
    "KAL": {"n": "10", "q": "Has applicant had a judgement or lien during the last five years?",
            "answer": "N"},
    "ABB": {"n": "11", "q": "Has business been placed in a trust?", "answer": "N"},
    "KAC": {"n": "12", "q": "Any foreign operations, foreign products distributed in USA, or US "
                               "products sold / distributed in foreign countries?", "answer": "Y"},
    "KAM": {"n": "13", "q": "Does applicant have other business ventures for which coverage is "
                               "not requested?", "answer": "Y",
            "explain": "Owns a 40% minority interest in Music Row Kitchen Rentals, LLC, a "
                       "shared commercial kitchen rental at 1601 Division St, Nashville; it is "
                       "insured separately and coverage is not requested."},
    "KAN": {"n": "14", "q": "Does applicant own / lease / operate any drones?", "answer": "N"},
    "KAO": {"n": "15", "q": "Does applicant hire others to operate drones?", "answer": "Y",
            "explain": "Hires SkyFrame Imaging, LLC (FAA Part 107 certified) about twice a year "
                       "to photograph completed installations for marketing; SkyFrame carries "
                       "its own aviation liability insurance."},
}
SAFETY = {"manual": True, "position": True, "monthly": False, "osha": True, "other": True,
          "other_text": "Quarterly safety committee meetings and annual forklift operator "
                        "certification"}
OTHER_POLICIES = [("Commercial Inland Marine", "IMF-3318207")]   # with Ridgeline
CANCEL = {"nonpayment": False, "agent": False, "nonrenewal": True, "underwriting": True,
          "corrected": True, "other": False,
          "corrected_text": "Roof replaced with a new TPO membrane at 2850 Kellerman "
                            "Industrial Pkwy; work completed 04/18/2025",
          "carrier": "Volunteer Fire & Marine Insurance Company",
          "policy": "VFM-CPP-7781203", "effective": "12/01/2024"}

# ════════════════════════════════════════════════════════════════════════════
# PRIOR CARRIER - only what the documents substantiate (rows A, B, C)
# ════════════════════════════════════════════════════════════════════════════
OHM = "Old Hickory Mutual Insurance Company"; OHM_NAIC = "27718"
OHM_PHONE = "1-800-555-0198"; OHM_WEB = "www.oldhickorymutual-example.com"
MAG = "Magnolia Underwriters Insurance Company"; MAG_NAIC = "15542"
CXS = "Cardinal Excess Insurance Company"; CXS_NAIC = "39087"
VFM = "Volunteer Fire & Marine Insurance Company"; VFM_NAIC = "21997"
TEM = "Tennessee Employers Mutual"; TEM_POLICY = "TEM-WC-0558213"   # WC, not requested

PRIOR_TERMS = [   # (carrier, policy, premium) per grid column; None = not substantiated
    {"year": "2025", "eff": "12/01/2025", "exp": "12/01/2026", "lines": {
        "GeneralLiability": (OHM, "OHM-GL-4471902-25", "$38,420"),
        "Automobile": (OHM, "OHM-CA-4471903-25", "$61,775"),
        "Property": (MAG, "MUI-CP-0098817-25", "$27,940"),
        "OtherLine": (CXS, "CXS-UMB-220871-25", "$9,880")}},
    {"year": "2024", "eff": "12/01/2024", "exp": "12/01/2025", "lines": {
        "GeneralLiability": (OHM, "OHM-GL-4471902-24", "$35,910"),
        "Automobile": (OHM, "OHM-CA-4471903-24", "$57,240"),
        "Property": (MAG, "MUI-CP-0098817-24", "$25,115"),
        "OtherLine": (CXS, "CXS-UMB-220871-24", "$9,240")}},
    {"year": "2023", "eff": "12/01/2023", "exp": "12/01/2024", "lines": {
        "GeneralLiability": (OHM, "OHM-GL-4471902-23", "$33,005"),
        "Automobile": (OHM, "OHM-CA-4471903-23", "$52,880"),
        "Property": (VFM, "VFM-CPP-7781203", None),      # VF&M's loss run prints no premium
        "OtherLine": None}},                              # no umbrella before 12/01/2024
]
GRID_LINE_NAMES = ["GeneralLiability", "Automobile", "Property", "OtherLine"]
# the 4th and 5th years exist in the 5-year loss run - the grid has three rows
OLDER_TERMS = [
    {"year": "2022", "gl": ("OHM-GL-4471902-22", "$31,400"), "auto": ("OHM-CA-4471903-22", "$49,615")},
    {"year": "2021", "gl": ("OHM-GL-4471902-21", "$29,975"), "auto": ("OHM-CA-4471903-21", "$46,030")},
]
CUR_TOTAL_PREMIUM = "$138,015"     # 38,420 + 61,775 + 27,940 + 9,880 - the expiring programme

# ════════════════════════════════════════════════════════════════════════════
# LOSS HISTORY - 5 years, latest valuation (09/15/2026), PAID total
# ════════════════════════════════════════════════════════════════════════════
LOSSES = [
    {"claim_no": "OHM-25-CA-018822", "occurrence": "08/09/2025", "claim": "08/11/2025",
     "line": "Commercial Auto",
     "desc": "Box truck backing at a customer's loading dock struck and damaged the "
             "customer's awning and gutter",
     "paid": "$6,412", "reserved": "$1,500", "subro": "N", "open": "Y",
     "carrier": OHM, "policy": "OHM-CA-4471903-25"},
    {"claim_no": "VFM-23-P-30418", "occurrence": "07/22/2023", "claim": "07/24/2023",
     "line": "Commercial Property",
     "desc": "Hail damage to the roof and rooftop HVAC units at 2850 Kellerman "
             "Industrial Pkwy",
     "paid": "$41,980", "reserved": "$0", "subro": "N", "open": "N",
     "carrier": VFM, "policy": "VFM-CPP-7781203"},
    {"claim_no": "OHM-22-CA-004471", "occurrence": "03/03/2022", "claim": "03/04/2022",
     "line": "Commercial Auto",
     "desc": "Insured service van rear-ended by a third party while stopped at a "
             "traffic light; vehicle damage only",
     "paid": "$3,775", "reserved": "$0", "subro": "Y", "open": "N",
     "carrier": OHM, "policy": "OHM-CA-4471903-21"},
]
TOTAL_PAID = "$52,167"
TOTAL_INCURRED = "$53,667"
OLD_VALUATION = {"date": "12/31/2025", "paid": "$2,100", "reserved": "$5,800"}
STALE_SUMMARY = {"date": "08/04/2026", "paid": "$5,950", "reserved": "$2,000"}
DECOY_LOSSES = [   # never a row on the 125
    {"why": "outside the five-year period", "occurrence": "05/14/2020",
     "claim_no": "VFM-20-P-11907", "desc": "Water damage from a failed sprinkler head in the showroom",
     "paid": "$12,300"},
    {"why": "the joint venture's own claim (a separate LLC, coverage not requested)",
     "occurrence": "02/02/2025", "claim_no": "BRK-25-GL-0612",
     "desc": "Renter slipped on a wet floor in the shared kitchen", "paid": "$9,850"},
]

# ════════════════════════════════════════════════════════════════════════════
# ADDITIONAL INTEREST on the 125 - the mortgagee on location 1
# ════════════════════════════════════════════════════════════════════════════
MORTGAGEE = {"name": "Pinnacle Commerce Bank, N.A.", "l1": "150 Third Ave S", "l2": "Suite 900",
             "city": "Nashville", "state": "TN", "zip": "37201", "country": "US",
             "rank": "1", "loan_no": "7004418829", "end": "05/01/2034",
             "amount": "$3,150,000", "phone": "615-555-0300", "fax": "615-555-0301",
             "email": "insurance.tracking@pinnaclecb-example.com",
             "reason": "First mortgage on the building at location 1",
             "loc": "1", "bldg": "1",
             "item": "Building at 2850 Kellerman Industrial Pkwy, Nashville"}
LOAN_BALANCE_DECOY = "$2,684,512"

# ════════════════════════════════════════════════════════════════════════════
# ACORD 126 - GENERAL LIABILITY (requested, not expiring)
# ════════════════════════════════════════════════════════════════════════════
GL_LIMITS = {   # requested ; expiring value where it differs
    "each_occurrence": ("$1,000,000", None),
    "general_aggregate": ("$2,000,000", None),
    "products": ("$2,000,000", None),
    "personal_adv": ("$1,000,000", None),
    "rented_premises": ("$300,000", "$100,000"),
    "medical": ("$10,000", "$5,000"),
    "ebl": ("$1,000,000", None),
}
GL_PD_DEDUCTIBLE = "$1,000"
EBL = {"deductible": "$1,000", "employees": "73", "covered": "66", "retro": "12/01/2019"}
GL_HAZARDS = [   # proposed-term exposures; expiring exposure / rate / premium are decoys
    {"loc": "1", "haz": "1", "code": "12683",
     "desc": "Kitchen and Restaurant Equipment Distributors - commercial",
     "basis": "S", "exposure": "$14,950,000", "terr": "004",
     "exp_exposure": "$13,700,000", "rate": "1.842", "premium": "$25,235"},
    {"loc": "2", "haz": "1", "code": "68706",
     "desc": "Warehouses - private - occupied by the named insured",
     "basis": "A", "exposure": "12,500", "terr": "005",
     "exp_exposure": "12,500", "rate": "96.210", "premium": "$1,203"},
    {"loc": "3", "haz": "1", "code": "91127",
     "desc": "Appliances and Accessories - installation, servicing or repair - commercial",
     "basis": "P", "exposure": "$1,284,600", "terr": "006",
     "exp_exposure": "$1,190,000", "rate": "9.886", "premium": "$11,764"},
]
SUBS_PAID = "$412,000"
SUBS_PCT = "22%"
SUBS_WORK = ("Final electrical connections by licensed electricians and gas and plumbing "
             "hookups by licensed plumbers")
SUBCONTRACTORS = ["Bellevue Electric Co.", "Rutledge Plumbing & Gas, LLC"]
PRODUCTS = [
    {"name": "CHHS ProClean private-label degreaser and oven cleaner", "sales": "$186,000",
     "units": "24,800", "months": "54", "life": "24",
     "use": "Degreasing and cleaning commercial kitchen equipment",
     "components": "Sodium hydroxide, surfactants and water"},
    {"name": "Forni Lombardi imported gas deck pizza ovens", "sales": "$2,340,000",
     "units": "156", "months": "96", "life": "180",
     "use": "Commercial baking in restaurant kitchens",
     "components": "Steel shell, refractory stone deck and gas burners"},
    {"name": "Vettore imported commercial espresso machines", "sales": "$1,120,000",
     "units": "410", "months": "72", "life": "120",
     "use": "Commercial espresso preparation",
     "components": "Stainless steel boiler, pumps and electronic controls"},
]
LANDLORD_AI = {"name": "Brightline Flex Properties, LP", "l1": "3300 West End Ave",
               "l2": "Suite 400", "city": "Nashville", "state": "TN", "zip": "37203",
               "loc": "2", "bldg": "1",
               "item": "Leased premises at 410 Industrial Blvd, Suite C, La Vergne"}
LOC3_LANDLORD = "Hillsboro Commons Office Partners, LLC"
GL_REMARKS = ("Per-location general aggregate (CG 25 04) requested for all three "
              "locations; the landlord of location 2 is to be added as additional "
              "insured as the lease requires.")
STAFFING = "Harpeth Staffing Solutions, Inc."

# 126 questions: code -> (answer, explanation field suffix or None, explanation)
#   "" = never answered by the documents: blank + UNRESOLVED
Q126 = {
    "GeneralLiabilityLineOfBusiness_Question_AAHCode_A": ("N", None, ""),
    "GeneralLiabilityLineOfBusiness_Question_AAICode_A": ("N", None, ""),
    "Contractors_Question_AABCode_A": ("Y", "GeneralLiabilityLineOfBusiness_ApplicantDrawPlansForOthersExplanation_A",
        "Prepares CAD kitchen layout drawings showing equipment placement for customers' "
        "kitchens; layouts are reviewed by the customer's architect or engineer"),
    "Contractors_Question_AAICode_A": ("N", None, ""),
    "Contractors_Question_AACCode_A": ("N", None, ""),
    "Contractors_Question_ABBCode_A": ("Y", "GeneralLiabilityLineOfBusiness_SubcontractorsCarryLowerLimitsExplanation_A",
        "Subcontractors carry $1,000,000 / $2,000,000 general liability but are not required "
        "to carry umbrella coverage"),
    "Contractors_Question_AADCode_A": ("N", None, ""),
    "Contractors_Question_AAECode_A": ("Y", "GeneralLiabilityLineOfBusiness_ApplicantLeaseEquipmentToOthersExplanation_A",
        "Loaner combi ovens and reach-in refrigerators are provided to customers, without "
        "operators, while their own equipment is being repaired"),
    "GeneralLiabilityLineOfBusiness_Question_AAJCode_A": ("Y", "GeneralLiabilityLineOfBusiness_ApplicantInstallServiceProductsExplanation_A",
        "Installs and services the commercial kitchen equipment it sells, through its "
        "subsidiary, and demonstrates equipment in the test kitchen at the Kellerman showroom"),
    "GeneralLiabilityLineOfBusiness_Question_ABACode_A": ("Y", None, ""),
    "GeneralLiabilityLineOfBusiness_Question_ABBCode_A": ("Y", "GeneralLiabilityLineOfBusiness_ResearchDevelopmentConductedNewProductsPlannedExplanation_A",
        "A private-label descaler is planned for 2027, to be blended by the same contract "
        "blender as the degreaser"),
    "GeneralLiabilityLineOfBusiness_Question_ABCCode_A": ("Y", "GeneralLiabilityLineOfBusiness_GuaranteesWarrantiesHoldHarmlessExplanation_A",
        "One-year labor warranty on installations; installation contracts include hold "
        "harmless agreements in favor of the general contractor"),
    "GeneralLiabilityLineOfBusiness_Question_ABDCode_A": ("N", None, ""),
    "GeneralLiabilityLineOfBusiness_Question_ABECode_A": ("Y", "GeneralLiabilityLineOfBusiness_ProductsRecalledDiscontinuedExplanation_A",
        "Discontinued the Volunteer Grill gas griddle line in 2024 after the manufacturer's "
        "recall; unsold units were returned to the manufacturer"),
    "GeneralLiabilityLineOfBusiness_Question_ABFCode_A": ("Y", "GeneralLiabilityLineOfBusiness_ProductsOfOthersSoldUnderApplicantLabelExplanation_A",
        "The CHHS ProClean degreaser is manufactured by Delta Chem Blending, Inc. and sold "
        "under the applicant's label"),
    "GeneralLiabilityLineOfBusiness_Question_ABGCode_A": ("N", None, ""),
    "GeneralLiabilityLineOfBusiness_Question_ABHCode_A": ("N", None, ""),
    "GeneralLiabilityLineOfBusiness_Question_ABICode_A": ("Y", "GeneralLiabilityLineOfBusiness_NamedInsuredSellToOtherNamedInsuredExplanation_R",
        "The applicant sells replacement parts at cost to its subsidiary, Cumberland Hearth "
        "Service Co., LLC, for use on service calls"),
    "GeneralLiabilityLineOfBusiness_Question_ABJCode_A": ("N", None, ""),
    "GeneralLiabilityLineOfBusiness_Question_ACACode_A": ("N", None, ""),
    "GeneralLiabilityLineOfBusiness_Question_ACJCode_A": ("Y", "GeneralLiabilityLineOfBusiness_OperationsInvolveStoringDisposingTransportingHazardousMaterialExplanation_A",
        "Stores corrosive degreaser concentrate in sealed drums, and technicians recover "
        "used refrigerant and transport the recovery cylinders to a licensed reclaimer"),
    "GeneralLiabilityLineOfBusiness_Question_ACBCode_A": ("Y", "GeneralLiabilityLineOfBusiness_AnyListedOperationsSoldAcquiredLastFiveYearsExplanation_A",
        "Acquired the assets of Bluegrass Bakery Equipment Service (Bowling Green, KY) in "
        "2023; closed the retail outlet at 1040 Visco Dr on 06/30/2026"),
    "GeneralLiabilityLineOfBusiness_Question_ACCCode_A": ("Y", "GeneralLiabilityLineOfBusiness_MachineryOrEquipmentLoanedRentedOthersExplanation_A",
        "Loaner combi ovens and reach-in refrigerators lent to service customers during "
        "repairs"),
    "Contractors_Question_AAHCode_A": ("N", None, ""),
    "GeneralLiabilityLineOfBusiness_Question_ACDCode_A": ("Y", "GeneralLiabilityLineOfBusiness_AnyParkingFacilitiesOwnedRentedExplanation_A",
        "Owned surface parking lot at 2850 Kellerman Industrial Pkwy, 60 spaces for "
        "customers and employees"),
    "GeneralLiabilityLineOfBusiness_Question_KAGCode_A": ("N", None, ""),
    "GeneralLiabilityLineOfBusiness_Question_ACECode_A": ("", None, ""),
    "GeneralLiabilityLineOfBusiness_Question_KAACode_A": ("", None, ""),
    "GeneralLiabilityLineOfBusiness_Question_KAHCode_A": ("", None, ""),
    "GeneralLiabilityLineOfBusiness_Question_ACFCode_A": ("Y", "GeneralLiabilityLineOfBusiness_SportingOrSocialEventsSponsoredExplanation_A",
        "Annual customer appreciation barbecue at the Kellerman showroom (about 250 guests); "
        "alcohol is served by a licensed caterer"),
    "GeneralLiabilityLineOfBusiness_Question_KABCode_A": ("Y", None, ""),
    "GeneralLiabilityLineOfBusiness_Question_ACGCode_A": ("Y", "GeneralLiabilityLineOfBusiness_StructuralAlterationsContemplatedExplanation_A",
        "A mezzanine addition in the Kellerman warehouse is planned for 2027; permits are "
        "pending"),
    "GeneralLiabilityLineOfBusiness_Question_ACHCode_A": ("N", None, ""),
    "GeneralLiabilityLineOfBusiness_Question_AABCode_A": ("Y", "GeneralLiabilityLineOfBusiness_ApplicantActiveJointVenturesExplanation_A",
        "40% member of Music Row Kitchen Rentals, LLC, a shared commercial kitchen rental; "
        "insured separately"),
    "GeneralLiabilityLineOfBusiness_Question_AACCode_A": ("N", None, ""),
    "GeneralLiabilityLineOfBusiness_Question_AADCode_A": ("Y", "GeneralLiabilityLineOfBusiness_LabourInterchangeOtherBusinessSubsidiariesExplanation_A",
        "Technicians of the applicant and of its subsidiary are interchanged as workload "
        "requires"),
    "GeneralLiabilityLineOfBusiness_Question_AAECode_A": ("", None, ""),
    "GeneralLiabilityLineOfBusiness_Question_AAFCode_A": ("Y", "GeneralLiabilityLineOfBusiness_CrimesOccurredOrAttemptedLastThreeYearsExplanation_A",
        "Attempted break-in at the La Vergne parts depot on 01/09/2025; the alarm sounded, "
        "the intruder fled, nothing was taken and there was no damage"),
    "Contractors_Question_AAGCode_A": ("Y", "GeneralLiabilityLineOfBusiness_FormalSafetySecurityPolicyInEffectExplanation_A",
        "Written safety program and a written security policy (alarm, cameras, gated yard, "
        "key-card access) maintained by the Safety and Compliance Coordinator"),
    "GeneralLiabilityLineOfBusiness_Question_AAGCode_A": ("", None, ""),
}
ATHLETIC_TEAM = {"sport": "Bowling (adult league)", "contact": "N", "over18": True,
                 "extent": "Team shirts and league fees only"}
LOANER = {"desc": "Loaner combi ovens and reach-in refrigerators lent to service customers "
                  "during repairs", "large": True, "small": False, "instruction": "Y"}

# ════════════════════════════════════════════════════════════════════════════
# ACORD 127 - BUSINESS AUTO (requested)
# ════════════════════════════════════════════════════════════════════════════
DRIVERS = [
    {"num": "1", "first": "Marcus", "mi": "T", "last": "Bellweather", "city": "Nashville",
     "state": "TN", "zip": "37211", "sex": "M", "marital": "M", "dob": "06/11/1984",
     "exp": "25", "lic_year": "2001", "lic": "104883127", "lic_state": "TN",
     "hired": "04/06/2015", "veh": "1", "pct": "100"},
    {"num": "2", "first": "Alicia", "mi": "R", "last": "Fontenot", "city": "Antioch",
     "state": "TN", "zip": "37013", "sex": "F", "marital": "S", "dob": "11/02/1991",
     "exp": "18", "lic_year": "2008", "lic": "117260554", "lic_state": "TN",
     "hired": "03/15/2019", "veh": "2", "pct": "70"},
    {"num": "3", "first": "Dwayne", "mi": "K", "last": "Hollis", "city": "Franklin",
     "state": "KY", "zip": "42134", "sex": "M", "marital": "D", "dob": "01/23/1978",
     "exp": "31", "lic_year": "1995", "lic": "H22118430", "lic_state": "KY",
     "hired": "07/01/2023", "veh": "3", "pct": "100"},
    {"num": "4", "first": "Priyanka", "mi": "S", "last": "Dandekar", "city": "Brentwood",
     "state": "TN", "zip": "37027", "sex": "F", "marital": "M", "dob": "08/30/1996",
     "exp": "14", "lic_year": "2012", "lic": "121904773", "lic_state": "TN",
     "hired": "09/20/2021", "veh": "4", "pct": "100"},
    {"num": "5", "first": "Gregory", "mi": "L", "last": "Szymanski", "city": "Mount Juliet",
     "state": "TN", "zip": "37122", "sex": "M", "marital": "M", "dob": "02/14/1969",
     "exp": "41", "lic_year": "1985", "lic": "098317562", "lic_state": "TN",
     "hired": "01/11/2010", "veh": "", "pct": ""},
    {"num": "6", "first": "Tamsin", "mi": "E", "last": "O'Rourke", "city": "Smyrna",
     "state": "TN", "zip": "37167", "sex": "F", "marital": "S", "dob": "12/05/2001",
     "exp": "9", "lic_year": "2017", "lic": "130555287", "lic_state": "TN",
     "hired": "02/26/2024", "veh": "2", "pct": "30"},
]
TERMINATED_DRIVER = {"name": "Kyle J. Ambrose", "terminated": "08/29/2026",
                     "lic": "126633019", "dob": "04/04/1999"}
CONVICTION = {"driver": "3", "date": "05/17/2025", "desc": "Speeding - 14 mph over the posted limit",
              "place": "Simpson County, KY", "years": "3"}
OLD_CONVICTION = {"driver": "1", "date": "09/02/2019", "desc": "Failure to yield"}  # outside 3 yrs

VEHICLES = [
    {"num": "1", "year": "2023", "make": "Isuzu", "model": "NPR-HD", "body": "Box Truck",
     "vin": "JALC4W162P7004417", "gvw": "14,500", "cost": "$78,450", "loc": "1",
     "use": "Commercial", "radius": "150", "terr": "104", "cls": "21499",
     "comp_ded": "$1,000", "coll_ded": "$1,000", "towing": False, "rental": True,
     "acv_decoy": "$61,300", "premium": "$14,982"},
    {"num": "2", "year": "2022", "make": "Ford", "model": "Transit 250", "body": "Cargo Van",
     "vin": "1FTBR1C82NKA31907", "gvw": "9,070", "cost": "$52,310", "loc": "2",
     "use": "Service", "radius": "50", "terr": "112", "cls": "01499",
     "comp_ded": "$500", "coll_ded": "$1,000", "towing": True, "rental": False,
     "acv_decoy": "$38,900", "premium": "$11,407"},
    {"num": "3", "year": "2024", "make": "Ram", "model": "ProMaster 2500", "body": "Cargo Van",
     "vin": "3C6LRVDG4RE118802", "gvw": "9,350", "cost": "$56,980", "loc": "3",
     "use": "Service", "radius": "50", "terr": "118", "cls": "01499",
     "comp_ded": "$500", "coll_ded": "$1,000", "towing": True, "rental": False,
     "acv_decoy": "$51,200", "premium": "$11,866"},
    {"num": "4", "year": "2021", "make": "Freightliner", "model": "M2 106", "body": "Straight Truck",
     "vin": "1FVACWDT7MHMN4471", "gvw": "33,000", "cost": "$142,600", "loc": "1",
     "use": "Commercial", "radius": "200", "terr": "104", "cls": "31499",
     "comp_ded": "$1,000", "coll_ded": "$2,500", "towing": False, "rental": True,
     "acv_decoy": "$103,750", "premium": "$23,520"},
]
V4_EXPIRING_COLL_DED = "$1,000"
SOLD_VEHICLE = {"year": "2017", "make": "Ford", "model": "E-350", "vin": "1FDWE3FL4HDC22016",
                "sold": "05/22/2026"}
SPECIAL_EQUIPMENT = [
    {"veh": "3", "desc": "Refrigerant recovery unit and steel shelving", "cost": "$7,400"},
    {"veh": "4", "desc": "Hydraulic liftgate (3,000 lb)", "cost": "$6,850"},
]
AUTO_AI = [
    {"name": "Volunteer Truck Finance, LLC", "type": "Lienholder", "l1": "2210 Murfreesboro Pike",
     "l2": "", "city": "Nashville", "state": "TN", "zip": "37217", "acct": "55-2190-388",
     "veh": "4", "rank": "1"},
    {"name": "Highline Commercial Truck Credit, LLC", "type": "Loss Payee",
     "l1": "9001 Corporate Center Dr", "l2": "Suite 300", "city": "Charlotte", "state": "NC",
     "zip": "28226", "acct": "HC-778104", "veh": "1", "rank": "1"},
]
TELEMATICS = {"pct": "100%", "driver_safety": True, "fuel": False, "maintenance": True,
              "mileage": True, "location": True, "navigation": False, "other": True,
              "other_text": "Forward-facing dash cameras",
              "additional": "FleetPulse telematics units in all four vehicles report "
                            "harsh braking, speeding, idle time, mileage and maintenance "
                            "alerts to the Safety and Compliance Coordinator weekly"}
GARAGE_STORAGE = ("Vehicles are parked overnight inside the fenced, gated and camera-monitored "
                  "yard at each garaging location")
MAX_EXPOSURE = "$221,050"          # V1 + V4 at location 1 (cost new)
AUTO_REMARKS = ("Towing and labor added on vehicles 2 and 3; the collision deductible on "
                "vehicle 4 increases to $2,500 at this submission.")
Q127 = {   # code -> (answer, explanation field or None, explanation)
    "CommercialVehicleLineOfBusiness_Question_AAJCode_A": ("N", None, ""),
    "CommercialVehicleLineOfBusiness_Question_ABACode_A": ("N", None, ""),
    "CommercialVehicleLineOfBusiness_Question_KADCode_A": ("Y", "CommercialVehicleLineOfBusiness_VehicleMaintenanceProgramInOperationExplanation_A",
        "Written preventive maintenance schedule: oil and inspection every 5,000 miles, annual "
        "DOT inspections, performed by an in-house technician and Music City Fleet Service"),
    "CommercialVehicleLineOfBusiness_Question_ABCCode_A": ("N", None, ""),
    "CommercialVehicleLineOfBusiness_Question_AAGCode_A": ("Y", None, ""),
    "CommercialVehicleLineOfBusiness_Question_AAECode_A": ("N", None, ""),
    "CommercialVehicleLineOfBusiness_Question_AAFCode_A": ("Y", "CommercialVehicleLineOfBusiness_OperationInvolveTransportingHazardousMaterialsExplanation_A",
        "Vehicle 3 carries recovered refrigerant cylinders (non-flammable compressed gas) to a "
        "licensed reclaimer; quantities are below placarding thresholds"),
    "CommercialVehicleLineOfBusiness_Question_AABCode_A": ("N", None, ""),
    "CommercialVehicleLineOfBusiness_Question_AACCode_A": ("N", None, ""),
    "CommercialVehicleLineOfBusiness_Question_KAECode_A": ("Y", "CommercialVehicleLineOfBusiness_ApplicantObtainMVRVerificationsExplanation_A",
        "MVRs are obtained at hire and every March through Clearpath MVR Services"),
    "CommercialVehicleLineOfBusiness_Question_KAFCode_A": ("Y", "CommercialVehicleLineOfBusiness_ApplicantSpecificDriverRecruitingMethodExplanation_K",
        "Drivers are recruited from internal technician and warehouse staff; three years of "
        "driving experience and a clean MVR are required, and a CDL for vehicle 4"),
    "CommercialVehicleLineOfBusiness_Question_AAHCode_A": ("N", None, ""),
    "CommercialVehicleLineOfBusiness_Question_AADCode_A": ("N", None, ""),
    "CommercialVehicleLineOfBusiness_Question_AAICode_A": ("Y", None, ""),
    "CommercialVehicleLineOfBusiness_Question_ABBCode_A": ("N", None, ""),
    "CommercialVehicleLineOfBusiness_Question_KAGCode_A": ("", None, ""),
    "CommercialVehicleLineOfBusiness_KAHCode_A": ("Y", None, ""),
}

# ════════════════════════════════════════════════════════════════════════════
# BULK - people and places that must never become a premises / insured / interest
# ════════════════════════════════════════════════════════════════════════════
_STREETS = ["Broadway", "Charlotte Ave", "Nolensville Pike", "Gallatin Pike", "Murfreesboro Pike",
            "West End Ave", "Hillsboro Pike", "Lebanon Pike", "Dickerson Pike", "Harding Pl",
            "Thompson Ln", "Old Hickory Blvd", "Bell Rd", "Elm Hill Pike", "Shelby Ave",
            "Main St", "Church St", "Commerce St", "Demonbreun St", "Edgehill Ave"]
_CITIES = [("Nashville", "37203"), ("Nashville", "37206"), ("Nashville", "37211"),
           ("Franklin", "37064"), ("Murfreesboro", "37129"), ("Brentwood", "37027"),
           ("Hendersonville", "37075"), ("Clarksville", "37040"), ("Bowling Green", "42101"),
           ("Huntsville", "35801"), ("Lebanon", "37087"), ("Gallatin", "37066")]
_CUSTOMERS = ["Hattie's Hot Chicken", "Belle Meade Bistro", "Germantown Tavern",
              "Marathon Village Pizza Co.", "The Gulch Oyster Bar", "Opry Mills Food Court",
              "Vanderbilt Dining Services", "Lipscomb Commons Cafe", "Bowling Green Bagel Works",
              "Huntsville Smokehouse", "Clarksville Diner", "Gallatin Pike Diner",
              "Riverside Bistro Group", "Two Rivers Catering Co.", "Sylvan Park Bakery",
              "Hillsboro Village Creamery", "12South Taproom", "East Bank Biscuit Co.",
              "Cool Springs Hotel", "Brentwood Country Club", "Murfreesboro Public Schools",
              "Williamson County Schools", "Rutherford Senior Living", "Lebanon Steakhouse",
              "Hendersonville Grill", "Midtown Noodle House", "Five Points Pizza",
              "Green Hills Grille", "Donelson Fish House", "Antioch Taqueria",
              "Smyrna Station Cafe", "Bellevue Bakery", "Madison Meat & Three",
              "Inglewood Lounge", "Sobro Sushi", "Capitol Hotel Kitchen",
              "Music City Center Catering", "Nissan Stadium Concessions",
              "Belmont University Dining", "Fisk Commons Kitchen"]


def job_sites():
    """40 customer installation sites - addresses that must NEVER be a premises."""
    out = []
    for i, cust in enumerate(_CUSTOMERS):
        num = 1100 + (i * 187) % 8800
        street = _STREETS[(i * 7) % len(_STREETS)]
        city, zp = _CITIES[(i * 5) % len(_CITIES)]
        state = "KY" if city == "Bowling Green" else ("AL" if city == "Huntsville" else "TN")
        out.append({"customer": cust, "addr": f"{num} {street}", "city": city, "state": state,
                    "zip": zp, "job": f"J-26{(i * 37) % 900 + 100:03d}",
                    "value": f"${(i * 4337) % 90000 + 8000:,}"})
    return out


CERT_HOLDERS = [   # name, address - printed beside the word "insurance"
    ("Hattie's Hot Chicken Holdings, LLC", "712 Monroe St, Nashville, TN 37208"),
    ("Cool Springs Hotel Partners, LP", "700 Cool Springs Blvd, Franklin, TN 37067"),
    ("Vanderbilt University", "2301 Vanderbilt Pl, Nashville, TN 37235"),
    ("Murfreesboro City Schools", "2552 S Church St, Murfreesboro, TN 37127"),
    ("Brasfield & Gorrie, LLC", "3021 7th Ave S, Birmingham, AL 35233"),
    ("Hoar Construction, LLC", "2 Metroplex Dr, Birmingham, AL 35209"),
    ("Messer Construction Co.", "643 W Court St, Cincinnati, OH 45203"),
    ("Brentwood Country Club", "5715 Old Hickory Blvd, Nashville, TN 37215"),
    ("Music City Center", "201 Rep. John Lewis Way S, Nashville, TN 37203"),
    ("Rutherford Senior Living, Inc.", "1820 Memorial Blvd, Murfreesboro, TN 37129"),
    ("Williamson County Board of Education", "1320 W Main St, Franklin, TN 37064"),
    ("Belmont University", "1900 Belmont Blvd, Nashville, TN 37212"),
    ("Opry Mills Mall LP", "433 Opry Mills Dr, Nashville, TN 37214"),
    ("Capitol Hotel Owner LLC", "231 6th Ave N, Nashville, TN 37219"),
    ("Bowling Green Bagel Works, Inc.", "931 State St, Bowling Green, KY 42101"),
    ("Huntsville Smokehouse LLC", "2311 Memorial Pkwy SW, Huntsville, AL 35801"),
    ("Nissan Stadium Concessions Co.", "1 Titans Way, Nashville, TN 37213"),
    ("Hendersonville Grill Co.", "100 Main St, Hendersonville, TN 37075"),
    ("The Gulch Oyster Bar LLC", "605 11th Ave S, Nashville, TN 37203"),
    ("Lebanon Steakhouse, Inc.", "1405 W Main St, Lebanon, TN 37087"),
]

# ════════════════════════════════════════════════════════════════════════════
# DECOYS - (value, scope glob, why). Each is PRINTED in the package and wrong
# only in the boxes named here.
# ════════════════════════════════════════════════════════════════════════════
DECOYS_125 = [
    (MGA, "Insurer_FullName_A", "the MGA administers - Ridgeline is the insurer"),
    (OHM, "Insurer_FullName_A", "the CURRENT carrier, not the one receiving the submission"),
    (OHM_NAIC, "Insurer_NAICCode_A", "the current carrier's NAIC"),
    ("OHM-GL-4471902-25", "Policy_PolicyNumberIdentifier_A", "an EXPIRING policy number on a new-business quote"),
    ("IMF-3318207", "Policy_PolicyNumberIdentifier_A", "the existing inland marine policy (question 4), not this one"),
    ("CG 25 04 05 09", "Policy_PolicyNumberIdentifier_A", "an ISO form number"),
    ("$38,420", "GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A", "the expiring GL premium"),
    ("$61,775", "CommercialVehicleLineOfBusiness_PremiumAmount_A", "the expiring auto premium"),
    (CUR_TOTAL_PREMIUM, "Policy_Payment_EstimatedTotalAmount_A", "the expiring programme total"),
    ("$107,090", "Policy_Payment_EstimatedTotalAmount_A", "the INCUMBENT's renewal quotation (not accepted)"),
    ("$40,880", "GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A", "the incumbent's renewal GL premium"),
    ("$66,210", "CommercialVehicleLineOfBusiness_PremiumAmount_A", "the incumbent's renewal auto premium"),
    ("$2,500", "Policy_Payment_MinimumPremiumAmount_A", "the PROGRAM's minimum - not this policy's"),
    ("$9,605", "Policy_Payment_MinimumPremiumAmount_A", "the incumbent GL policy's minimum premium"),
    (CUR_EFF, "Policy_EffectiveDate_A", "the CURRENT term's start"),
    (STALE_PROPOSED_EFF, "Policy_EffectiveDate_A", "the August worksheet's date - superseded on 09/24"),
    ("Agency bill - 10 installments", "Policy_PaymentMethod_MethodDescription_A", "the expiring billing"),
    (PRIOR_AGENCY_CUSTOMER_ID, "Producer_CustomerIdentifier_A", "the PRIOR agency's customer id"),
    (PRIOR_AGENCY_CODE, "Insurer_ProducerIdentifier_A", "the PRIOR agency's code with the incumbent"),
    (OHM_WEB, "NamedInsured_Primary_WebsiteAddress_*", "the incumbent carrier's website"),
    (OHM_PHONE, "NamedInsured_Primary_PhoneNumber_*", "the incumbent carrier's service line"),
    (FAX, "NamedInsured_Primary_PhoneNumber_A", "the applicant's FAX line"),
    (AGENCY_PHONE, "NamedInsured_Primary_PhoneNumber_*", "the agency's phone"),
    (SOS_CONTROL, "NamedInsured_TaxIdentifier_*", "a 9-digit Secretary of State control number"),
    (DUNS, "NamedInsured_TaxIdentifier_*", "a 9-digit D-U-N-S number"),
    (USDOT, "NamedInsured_TaxIdentifier_*", "a USDOT number"),
    (JV["fein"], "NamedInsured_TaxIdentifier_*", "the joint venture's FEIN"),
    ("68706", "NamedInsured_GeneralLiabilityCode_A", "a non-governing GL class"),
    (GL_CODE, "NamedInsured_NAICSCode_*", "a GL class code in the NAICS box"),
    (FORMER_NAME, "NamedInsured_FullName_*", "the FORMER name - the LLC converted in 2022"),
    (JV["name"], "NamedInsured_FullName_*", "the joint venture - coverage not requested"),
    (TRUST_NAME, "NamedInsured_FullName_*", "a shareholder, not an insured"),
    (TRUST_NAME, "BusinessInformation_ParentOrganizationName_A", "a 60% shareholder's trust is not a parent company"),
    (TRUST_NAME, "AdditionalInterest_FullName_B", "question 11 is NO - the shareholder's trust is not the business placed in trust"),
    (LANDLORD_AI["name"], "NamedInsured_FullName_*", "the location 2 landlord"),
    (JV["name"], "Subsidiary_OrganizationName_A", "a 40% minority interest is not a subsidiary"),
    (TOTAL_REVENUE, "CommercialStructure_AnnualRevenueAmount_*", "the COMPANY total - each premises carries its own"),
    (PROJECTED_REVENUE, "CommercialStructure_AnnualRevenueAmount_*", "the PROJECTED 2027 revenue"),
    (BACKLOG, "CommercialStructure_AnnualRevenueAmount_*", "the order backlog"),
    (PAYROLL_TOTAL, "CommercialStructure_AnnualRevenueAmount_*", "payroll is not revenue"),
    (HEADCOUNT_TOTAL, "BusinessInformation_FullTimeEmployeeCount_*", "total headcount, full and part time"),
    (TEMPS, "BusinessInformation_PartTimeEmployeeCount_*", "agency temps are not employees"),
    (LOC3_STALE_OCCUPIED, "BuildingOccupancy_OccupiedArea_C", "corrected by the lease amendment"),
    ("95%", "CommercialStructure_InstallationRepairWorkOffPremisesPercent_A", "share of SERVICE CALLS at customer sites - not of total sales"),
    (DENISE_CELL_TYPO, "NamedInsured_Contact_*PhoneNumber_*", "a typo corrected in the CFO's e-mail"),
    (CFO_PHONE, "NamedInsured_Contact_*PhoneNumber_*", "the CFO is not a listed contact"),
    (OLD_VALUATION["paid"], "LossHistory_PaidAmount_*", "the 12/31/2025 valuation"),
    (OLD_VALUATION["reserved"], "LossHistory_ReservedAmount_*", "the 12/31/2025 valuation"),
    (STALE_SUMMARY["paid"], "LossHistory_PaidAmount_*", "the agency summary of 08/04/2026 - stale"),
    (STALE_SUMMARY["reserved"], "LossHistory_ReservedAmount_*", "the agency summary of 08/04/2026 - stale"),
    (TOTAL_INCURRED, "LossHistory_TotalAmount_A", "paid + reserved is INCURRED"),
    ("$38,400", "LossHistory_PaidAmount_*", "the hail claim as of 10/2024 - it closed at $41,980"),
    ("$12,900,000", "CommercialStructure_AnnualRevenueAmount_*", "the SUPERSEDED 2024 application's figure"),
    (LOAN_BALANCE_DECOY, "AdditionalInterest_LoanAmount_A", "the current balance - the loan amount is $3,150,000"),
    (BUILDING_VALUE_LOC1, "AdditionalInterest_LoanAmount_A", "the building value"),
    (LANDLORD_AI["name"], "AdditionalInterest_FullName_A", "the GL additional insured belongs on the 126"),
    (AUTO_AI[0]["name"], "AdditionalInterest_FullName_A", "a vehicle lienholder belongs on the 127"),
    ("OHM-GL-4471902-22", "PriorCoverage_*", "a FOURTH year - the grid holds three"),
    ("OHM-CA-4471903-22", "PriorCoverage_*", "a FOURTH year - the grid holds three"),
    (TEM, "PriorCoverage_OtherLine_InsurerFullName_*", "workers compensation is not part of this programme's grid"),
]
DECOYS_126 = [
    (OHM, "Insurer_FullName_A", "the current carrier"),
    (OHM_NAIC, "Insurer_NAICCode_A", "the current carrier's NAIC"),
    ("OHM-GL-4471902-25", "Policy_PolicyNumberIdentifier_A", "the EXPIRING GL policy number"),
    (CUR_EFF, "Policy_EffectiveDate_A", "the current term's start"),
    ("$100,000", "GeneralLiability_FireDamageRentedPremises_EachOccurrenceLimitAmount_A", "the EXPIRING limit - $300,000 is requested"),
    ("$5,000", "GeneralLiability_MedicalExpense_EachPersonLimitAmount_A", "the EXPIRING limit - $10,000 is requested"),
    ("$5,000,000", "GeneralLiability_*LimitAmount_A", "the umbrella limit"),
    ("$13,700,000", "GeneralLiability_Hazard_Exposure_*", "the EXPIRING exposure - the proposed estimate is $14,950,000"),
    ("$1,190,000", "GeneralLiability_Hazard_Exposure_*", "the EXPIRING payroll - the proposed estimate is $1,284,600"),
    ("$13,210,500", "GeneralLiability_Hazard_Exposure_*", "the AUDITED 2024-25 sales"),
    ("$1,122,400", "GeneralLiability_Hazard_Exposure_*", "the AUDITED 2024-25 payroll"),
    ("10150", "GeneralLiability_Hazard_ClassCode_*", "the DELETED Visco Drive retail class"),
    ("$25,235", "GeneralLiability_Hazard_*PremiumAmount_*", "an expiring class premium"),
    ("1.842", "GeneralLiability_Hazard_*Rate_*", "an expiring rate"),
    ("$38,420", "GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A", "the expiring GL premium"),
    ("12683", "ProductAndCompletedOperations_ProductName_*", "a GL rating class is not a product"),
    ("Kitchen and Restaurant Equipment Distributors - commercial", "ProductAndCompletedOperations_ProductName_*", "a rating classification is not a product"),
    ("Volunteer Grill", "ProductAndCompletedOperations_ProductName_*", "a DISCONTINUED line"),
    (STAFFING, "AdditionalInterest_FullName_*", "temporary workers from a staffing firm are not leased employees"),
    (HEADCOUNT_TOTAL, "Contractors_FullTimeEmployeeCount_A", "total headcount, full and part time"),
    (TEMPS, "Contractors_PartTimeEmployeeCount_A", "agency temps are not employees"),
    ("03/01/2015", "GeneralLiability_ClaimsMade_*", "the E&O policy's retro date - GL is occurrence"),
    ("03/01/2015", "GeneralLiability_EmployeeBenefits_RetroactiveDate_A", "the E&O retro date - EBL retro is 12/01/2019"),
    (MORTGAGEE["name"], "AdditionalInterest_FullName_A", "the property mortgagee is not a GL additional insured"),
]
DECOYS_127 = [
    (OHM, "Insurer_FullName_A", "the current carrier"),
    ("OHM-CA-4471903-25", "Policy_PolicyNumberIdentifier_A", "the EXPIRING auto policy number"),
    (CUR_EFF, "Policy_EffectiveDate_A", "the current term's start"),
    (V4_EXPIRING_COLL_DED, "Vehicle_Collision_DeductibleAmount_D", "the EXPIRING deductible - $2,500 is requested"),
    ("$14,982", "Vehicle_TotalPremiumAmount_*", "an expiring vehicle premium"),
    ("$23,520", "Vehicle_TotalPremiumAmount_*", "an expiring vehicle premium"),
    ("$61,300", "Vehicle_CostNewAmount_*", "the current ACV, not cost new"),
    ("$103,750", "Vehicle_CostNewAmount_*", "the current ACV, not cost new"),
    (SOLD_VEHICLE["vin"], "Vehicle_VINIdentifier_*", "SOLD 05/22/2026 by endorsement 2"),
    ("1GCWGFCF5F1144028", "Vehicle_VINIdentifier_*", "the 2015 Chevrolet Express - SOLD 08/2025"),
    (TERMINATED_DRIVER["lic"], "Driver_LicenseNumberIdentifier_*", "a driver TERMINATED 08/29/2026"),
    ("Ambrose", "Driver_Surname_*", "a driver TERMINATED 08/29/2026"),
    ("Ellison", "Driver_Surname_*", "the owner is a Drive Other Car named individual, not a driver"),
    ("Lindqvist", "Driver_Surname_*", "the CFO drives his own car - not a listed driver"),
    ("4471", "Driver_TaxIdentifier_*", "masked SSN fragments never print"),
    (OLD_CONVICTION["date"], "AccidentConviction_TrafficViolationDate_A", "outside the three-year look-back"),
    (USDOT, "*", "a USDOT number is not on the 127"),
    (MORTGAGEE["name"], "AdditionalInterest_FullName_*", "the building mortgagee is not a vehicle interest"),
]

# rows with no slot / entities that are NOT this account's - must appear nowhere in scope
def expected_absent_125():
    vals = [s["addr"] for s in job_sites()] + [n for n, _a in CERT_HOLDERS]
    vals += [a.split(",")[0] for _n, a in CERT_HOLDERS]
    vals += [CLOSED_LOCATION["l1"], JV["addr"].split(",")[0], SUBLEASE_TENANT,
             LANDLORD_AI["name"], LOC3_LANDLORD, STAFFING, "Riverside Bistro Group",
             "Two Rivers Catering Co.", "Forni Lombardi S.r.l.", "Delta Chem Blending, Inc."]
    return {"scope": ["CommercialStructure_PhysicalAddress_LineOne_*", "NamedInsured_FullName_*",
                      "AdditionalInterest_FullName_*", "AdditionalInterest_MailingAddress_LineOne_*",
                      "LossHistory_OccurrenceDate_*", "LossHistory_PaidAmount_*",
                      "PriorCoverage_*"],
            "values": vals + [d["occurrence"] for d in DECOY_LOSSES] + [d["paid"] for d in DECOY_LOSSES]
                      + [t["gl"][0] for t in OLDER_TERMS] + [t["auto"][0] for t in OLDER_TERMS]}


ABSENT_BY_DESIGN = [
    "a policy number, premium, deposit or minimum premium for the policy being QUOTED",
    "an answer to 125 question 7 (fraud / bribery / arson) or question 9 (foreclosure, "
    "repossession, bankruptcy) - the insured never answered them; the package mentions a "
    "CUSTOMER's bankruptcy and a repossession BY the applicant, which answer nothing",
    "an answer to 126 recreation facilities, lodging, swimming pool, day care and "
    "promotional-literature questions, and 127 'all vehicles part of a fleet'",
    "a premium for the 2023-24 property term (the Volunteer Fire & Marine loss run prints none)",
    "an umbrella before 12/01/2024 (the first umbrella incepted then)",
    "a resolution block for question 8 - the 02/11/2026 citation was CORRECTED, so 8 is No",
    "any claim older than five years in the loss history",
    "a producer NPN / state licence from the account (the account profile has no such field)",
]

UNRESOLVED_EXPECTED = [   # the client's 'UNRESOLVED - insured confirmation required' list
    ("ACORD_125", "CommercialPolicy_Question_KABCode_A", "Q7 fraud / bribery / arson conviction"),
    ("ACORD_125", "CommercialPolicy_Question_KAKCode_A", "Q9 foreclosure / repossession / bankruptcy"),
    ("ACORD_126", "GeneralLiabilityLineOfBusiness_Question_ACECode_A", "recreation facilities"),
    ("ACORD_126", "GeneralLiabilityLineOfBusiness_Question_KAACode_A", "lodging operations"),
    ("ACORD_126", "GeneralLiabilityLineOfBusiness_Question_KAHCode_A", "swimming pool"),
    ("ACORD_126", "GeneralLiabilityLineOfBusiness_Question_AAECode_A", "day care facilities"),
    ("ACORD_126", "GeneralLiabilityLineOfBusiness_Question_AAGCode_A", "promotional literature safety representations"),
    ("ACORD_127", "CommercialVehicleLineOfBusiness_Question_KAGCode_A", "all vehicles part of a fleet"),
    ("ACORD_125", "PriorCoverage_Property_TotalPremiumAmount_C", "2023-24 property premium - request it"),
]
