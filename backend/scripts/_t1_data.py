"""
_t1_data.py - the SINGLE SOURCE OF TRUTH for the T1 table-fidelity test kit.

Both the document generator (`make_t1_test_pdfs.py`) and the answer key it
writes are built from the constants below, so a value can never be printed in
the PDF and expected as something different in the key. Change a figure here
and both sides move together.

Read `t1_test_data/README-HOW-TO-TEST.md` for what each trap is for.
"""
from __future__ import annotations

# -- Package identity ---------------------------------------------------------
CARRIER          = "Cascade Summit Mutual Insurance Company"
CARRIER_NAIC     = "21326"
POLICY_NO        = "CPP 4Q 887214 26"
EFF              = "03/15/2026"
EXP              = "03/15/2027"
PRIOR_EFF        = "03/15/2025"
PRIOR_EXP        = "03/15/2026"
PKG_PREMIUM      = "$148,730"
BILLING_PLAN     = "Quarterly - 25% Down"
UNDERWRITER      = "Marguerite Solano"
UW_OFFICE        = "DEN-04"

PRODUCER         = "Halloway Ridge Insurance Advisors, LLC"
PRODUCER_L1      = "601 W Main St"
PRODUCER_L2      = "Ste 900"
PRODUCER_CITY    = "Louisville"
PRODUCER_STATE   = "KY"
PRODUCER_ZIP     = "40202"
PRODUCER_PHONE   = "(502) 555-0184"
PRODUCER_FAX     = "(502) 555-0191"
PRODUCER_EMAIL   = "submissions@hallowayridge.com"
PRODUCER_CODE    = "KY-40118"

# -- Named insureds. FOUR of them; ACORD 125 prints THREE (rows A-C). ---------
# The fourth is the deliberate overflow: it must never displace a real one.
INSUREDS = [
    {  # A
        "name": "Verdant Slope Builders, LLC",
        "fein": "84-3391027",
        "entity": "LLC",
        "members": "3",
        "sic": "1761",              # 4 digits
        "naics": "238160",          # 6 digits  <- adjacent-swap trap
        "line1": "1188 Larimer Crossing",
        "line2": "Ste 400",         # comma-free unit designator in the document
        "city": "Denver", "state": "CO", "zip": "80204",
        "phone": "(303) 555-0142",
        "web": "www.verdantslopebuilders.com",
        "start": "04/02/2009",
    },
    {  # B
        "name": "Halewood Ridge Framing, Inc.",
        "fein": "87-2205518",
        "entity": "Corporation",
        "members": "",
        "sic": "1751",
        "naics": "238350",
        "line1": "704 N Weber St",
        "line2": "Unit 12",
        "city": "Colorado Springs", "state": "CO", "zip": "80903",
        "phone": "(719) 555-0178",
        "web": "",
        "start": "11/17/2014",
    },
    {  # C
        "name": "Cotter Bench Equipment Leasing, LLC",
        "fein": "88-1740662",
        "entity": "LLC",
        "members": "2",
        "sic": "7359",
        "naics": "532412",
        "line1": "9420 E Costilla Ave",
        "line2": "Bldg 3",
        "city": "Greenwood Village", "state": "CO", "zip": "80112",
        "phone": "(720) 555-0133",
        "web": "",
        "start": "06/30/2018",
    },
    {  # D - OVERFLOW: stated in the document, no slot on the form
        "name": "Verdant Slope Property Holdings, LLC",
        "fein": "92-0668311",
        "entity": "LLC",
        "members": "3",
        "sic": "6512",
        "naics": "531120",
        "line1": "1188 Larimer Crossing",
        "line2": "Ste 400",
        "city": "Denver", "state": "CO", "zip": "80204",
        "phone": "(303) 555-0142",
        "web": "",
        "start": "01/09/2021",
    },
]

CONTACT_NAME    = "Delphine Ostrander"
CONTACT_TITLE   = "Controller"
CONTACT_PHONE   = "(303) 555-0147"
CONTACT_EMAIL   = "dostrander@verdantslopebuilders.com"
SAFETY_DIRECTOR = "Alonzo Pryce"

# -- Premises. FIVE locations; ACORD 125 prints FOUR (rows A-D). --------------
LOCATIONS = [
    {"num": "001", "bldg": "001",
     "line1": "1188 Larimer Crossing", "line2": "Ste 400",
     "city": "Denver", "county": "Denver", "state": "CO", "zip": "80204",
     "ft": "11", "pt": "2",
     "interest": "Tenant", "occupied": "6,500", "public": "1,200",
     "ops": "Executive offices, estimating and project administration",
     "leased_to_others": "No"},
    {"num": "002", "bldg": "001",
     "line1": "3390 E Overland Rd", "line2": "Unit B",
     "city": "Aurora", "county": "Arapahoe", "state": "CO", "zip": "80011",
     "ft": "9", "pt": "3",
     "interest": "Owner", "occupied": "18,000", "public": "0",
     "ops": "Materials warehouse and fabrication shop for roofing assemblies",
     "leased_to_others": "Yes"},
    {"num": "003", "bldg": "001",
     "line1": "704 N Weber St", "line2": "Unit 12",
     "city": "Colorado Springs", "county": "El Paso", "state": "CO", "zip": "80903",
     "ft": "5", "pt": "1",
     "interest": "Tenant", "occupied": "3,200", "public": "400",
     "ops": "Southern Colorado branch office and small tool storage",
     "leased_to_others": "No"},
    {"num": "004", "bldg": "001",
     "line1": "15 Foothills Service Rd", "line2": "",
     "city": "Golden", "county": "Jefferson", "state": "CO", "zip": "80401",
     "ft": "14", "pt": "2",
     "interest": "Owner", "occupied": "24,000", "public": "0",
     "ops": "Equipment yard, vehicle maintenance bay and covered material racks",
     "leased_to_others": "No"},
    {"num": "005", "bldg": "001",   # OVERFLOW - no row E on ACORD 125
     "line1": "2201 S Yuma Frontage Rd", "line2": "",
     "city": "Pueblo", "county": "Pueblo", "state": "CO", "zip": "81004",
     "ft": "3", "pt": "1",
     "interest": "Tenant", "occupied": "4,100", "public": "0",
     "ops": "Seasonal staging yard leased March through November",
     "leased_to_others": "No"},
]

# -- General Liability (ACORD 126) -------------------------------------------
GL = {
    "each_occurrence":      "$1,000,000",
    "general_aggregate":    "$2,000,000",
    "products_aggregate":   "$2,000,000",
    "personal_adv_injury":  "$1,000,000",
    "fire_damage":          "$300,000",
    "medical_expense":      "$10,000",
    "form":                 "Occurrence",
    "aggregate_applies":    "Per Project",
    "premium":              "$61,455",
    "deductible":           "$2,500",
    "deductible_basis":     "Per Claim",
    "base_form_edition":    "CG 00 01 04 13",
    "ebl_limit":            "$1,000,000",
    "ebl_retro":            "04/02/2009",
    "ebl_employees":        "51",
    "ebl_covered":          "42",
    "ebl_deductible":       "$1,000",
}

# GL SCHEDULE OF HAZARDS - three rows that ALL share territory 008.
# That shared value is the whole point: a repeating column whose cells
# legitimately repeat is the case a per-field quote reuse cap cannot survive.
GL_HAZARDS = [
    {"loc": "001", "haz": "001", "class": "91340",
     "classification": "Carpentry - construction of residential property not exceeding three stories",
     "basis": "(p) Payroll", "exposure": "1,318,000", "territory": "008",
     "po_rate": "3.412", "po_premium": "$44,970", "pr_rate": "1.106", "pr_premium": "$14,577"},
    {"loc": "002", "haz": "001", "class": "91580",
     "classification": "Contractors - subcontracted work - in connection with construction",
     "basis": "(c) Total Cost", "exposure": "2,145,000", "territory": "008",
     "po_rate": "0.902", "po_premium": "$19,348", "pr_rate": "0.000", "pr_premium": "$0"},
    {"loc": "004", "haz": "001", "class": "92478",
     "classification": "Roofing - all kinds", "basis": "(p) Payroll",
     "exposure": "486,000", "territory": "008",
     "po_rate": "8.114", "po_premium": "$39,434", "pr_rate": "2.331", "pr_premium": "$11,329"},
]

# The AUTO rating territory. DIFFERENT from the GL territory on purpose: it is
# the value that bled into the GL hazard grid on the reported run.
AUTO_TERRITORY = "104"

CONTRACTORS = {
    "subcontract_cost": "$2,145,000",
    "subcontract_pct":  "34%",
    "full_time":        "42",
    "part_time":        "9",
}

# -- Umbrella / Excess (ACORD 131) -------------------------------------------
UMB = {
    "carrier":         "Ridgeline Specialty Indemnity Company",
    "naic":            "34762",
    "policy":          "XSU 55 210934 26",
    "each_occurrence": "$5,000,000",
    "aggregate":       "$5,000,000",
    "retention":       "$10,000",
    "form":            "Occurrence",
    "premium":         "$23,900",
    "prior_policy":    "XSU 55 210934 25",
}

# SCHEDULE OF UNDERLYING INSURANCE. GL and Auto share ONE carrier and ONE
# policy number - the second legitimate-repeat trap, on a different form.
UNDERLYING = {
    "gl": {"carrier": CARRIER, "policy": POLICY_NO, "eff": EFF, "exp": EXP,
           "po_premium": "$46,900", "products_premium": "$14,555",
           "form_edition": "04 13"},
    "auto": {"carrier": CARRIER, "policy": POLICY_NO, "eff": EFF, "exp": EXP,
             "csl_premium": "$18,240", "mod": "1.00"},
    "el": {"carrier": "Foundry State Compensation Fund", "policy": "WC 9930221 26",
           "eff": EFF, "exp": EXP, "premium": "$71,410", "mod": "0.94"},
    "other_a": {"type": "Contractors Pollution Liability",
                "carrier": "Meridian Environmental Indemnity Company",
                "policy": "CPL 3308821 26", "eff": EFF, "exp": EXP,
                "csl": "$1,000,000", "premium": "$4,860",
                "description": "Contractors pollution liability, sudden and gradual"},
}

# -- Exposure figures. The products-grid bait lives here. --------------------
EXPOSURE = {
    "payroll":        "$1,804,000",
    "revenue_2025":   "$9,410,000",
    "revenue_2024":   "$8,275,000",
    "revenue_2023":   "$6,940,000",
    "foreign_sales":  None,            # NEVER stated -> must not become "$0"
    "employees_ft":   "42",
    "employees_pt":   "9",
    "fleet_count":    "17",            # a "unit count" unrelated to any product
    "warranty_years": "20",            # an "expected life" unrelated to any product
}

OPERATIONS = ("Commercial and residential re-roofing, new roof installation, "
              "sheet metal flashing fabrication and gutter installation, "
              "performed by employees and subcontracted crews across the Front Range")

# -- Loss history. FIVE losses, printed OUT OF ORDER and SPLIT across two -----
# non-adjacent sections of the document, so a row can only be assembled by
# identity and never by position.
LOSSES = [
    {"claim": "GL-2025-30712", "date": "02/28/2025", "lob": "General Liability",
     "desc": "Fall from scaffold, subcontractor employee, bodily injury",
     "paid": "$91,000", "reserved": "$145,000", "status": "Open", "subro": "No"},
    {"claim": "GL-2023-11884", "date": "07/22/2023", "lob": "General Liability",
     "desc": "Water damage to third party finishes during re-roof",
     "paid": "$38,400", "reserved": "$0", "status": "Closed", "subro": "No"},
    {"claim": "GL-2025-41220", "date": "09/03/2025", "lob": "General Liability",
     "desc": "Alleged faulty installation with resulting water intrusion",
     "paid": "$0", "reserved": "$75,000", "status": "Open", "subro": "Yes"},
    {"claim": "AU-2024-20551", "date": "11/09/2024", "lob": "Automobile",
     "desc": "Backing collision with parked vehicle, no injuries",
     "paid": "$6,215", "reserved": "$0", "status": "Closed", "subro": "Yes"},
    {"claim": "PR-2022-08109", "date": "05/16/2022", "lob": "Property",
     "desc": "Hail damage to owned warehouse roof",
     "paid": "$212,880", "reserved": "$0", "status": "Closed", "subro": "No"},
]
# Which losses print in the FIRST loss run block, and which in the far-away
# supplemental block. Indices into LOSSES.
LOSS_BLOCK_ONE = [0, 1, 2]
LOSS_BLOCK_TWO = [3, 4]

LOSS_PAID_TOTAL     = "$348,495"
LOSS_RESERVED_TOTAL = "$220,000"
LOSS_TOTAL_INCURRED = "$568,495"

# -- Expiring (prior) programme. Lexically close to the current numbers. -----
PRIOR_CARRIER = "Sentinel Prairie Casualty Company"
PRIOR = {
    "gl":       {"policy": "GL 7784120 25", "premium": "$54,120"},
    "auto":     {"policy": "CA 7784121 25", "premium": "$16,900"},
    "property": {"policy": "CF 7784122 25", "premium": "$22,455"},
    "umbrella": {"policy": UMB["prior_policy"], "premium": "$21,300",
                 "carrier": UMB["carrier"]},
}

# -- Role traps: real strings, in the document, belonging to NO identity box --
ADDL_INSURED_WORDING = (
    "Any person or organization for whom the Named Insured has agreed in writing "
    "in a contract or agreement that such person or organization be added as an "
    "additional insured on the Named Insured policy"
)
LIENHOLDER      = "Bank of the Front Range, N.A."
LIENHOLDER_L1   = "2100 Sherman Vista Blvd"
LIENHOLDER_L2   = "Ste 1400"
LIENHOLDER_CITY = "Denver"
LIENHOLDER_STATE = "CO"
LIENHOLDER_ZIP  = "80203"

# A policy CONDITION that prints the insured address in a non-identity role.
CANCELLATION_CLAUSE = (
    "Notice of cancellation will be mailed to the first Named Insured at the "
    "address shown in the Declarations, 1188 Larimer Crossing Ste 400, Denver, "
    "Colorado, and proof of mailing will be sufficient proof of notice"
)

# -- Yes/No evidence. Every sentence below is printed verbatim in the PDF. ----
# The safety-programme facts are deliberately carried by ONE cluster of
# adjacent sentences: several form boxes, one piece of evidence.
SAFETY_EVIDENCE = (
    "Verdant Slope Builders maintains a formal written safety manual, last "
    "revised January 2026, and holds documented monthly toolbox safety meetings "
    "at every active jobsite. A full-time Safety Director, Alonzo Pryce, is "
    "employed by the applicant. All field supervisors hold current OSHA 30-hour "
    "construction certification."
)

YN_EVIDENCE = {
    # "FORM|field name" -> (expected answer, the sentence printed in the document)
    "ACORD_125|CommercialPolicy_Question_KAACode_A": ("Y", SAFETY_EVIDENCE),
    "ACORD_125|CommercialPolicy_Question_AAICode_A": (
        "N", "The applicant is not a subsidiary of any other entity."),
    "ACORD_125|CommercialPolicy_Question_AAJCode_A": (
        "Y", "Verdant Slope Builders, LLC holds a controlling membership interest "
             "in Verdant Slope Property Holdings, LLC, which owns real estate only."),
    "ACORD_125|CommercialPolicy_Question_KACCode_A": (
        "N", "The applicant has no foreign operations and distributes no products "
             "outside the United States."),
    "ACORD_125|CommercialPolicy_Question_KANCode_A": (
        "Y", "The applicant owns two unmanned aerial systems used for roof survey "
             "and progress photography."),
    "ACORD_125|CommercialPolicy_Question_ABCCode_A": (
        "Y", "Sealants, adhesives and propane torch equipment are stored at the "
             "Golden equipment yard in quantities customary to the roofing trade."),
    "ACORD_126|Contractors_Question_AACCode_A": (
        "N", "No operation performed by the applicant involves excavation, "
             "tunneling, underground work or earth moving."),
    "ACORD_126|Contractors_Question_AADCode_A": (
        "N", "Subcontractors are not permitted to begin work until a current "
             "certificate of insurance has been received and logged."),
    "ACORD_126|Contractors_Question_AAECode_A": (
        "Y", "Cotter Bench Equipment Leasing, LLC leases hoists and material "
             "conveyors to unaffiliated contractors without operators."),
    "ACORD_126|Contractors_Question_AAGCode_A": ("Y", SAFETY_EVIDENCE),
    "ACORD_126|Contractors_Question_AAICode_A": (
        "N", "No operation performed by the applicant involves blasting, and no "
             "explosive material is utilized or stored."),
    "ACORD_126|GeneralLiabilityLineOfBusiness_Question_ABCCode_A": (
        "Y", "The applicant executes hold harmless agreements in favor of general "
             "contractors and issues a twenty year workmanship warranty on "
             "installed roof assemblies."),
    "ACORD_126|GeneralLiabilityLineOfBusiness_Question_ACDCode_A": (
        "N", "No parking facilities are owned or rented by the applicant."),
    "ACORD_126|GeneralLiabilityLineOfBusiness_Question_AAJCode_A": (
        "Y", "The applicant installs and services roofing assemblies at customer "
             "premises and demonstrates membrane seam techniques at trade shows."),
    "ACORD_126|GeneralLiabilityLineOfBusiness_Question_ACACode_A": (
        "N", "The applicant has no exposure to radioactive or nuclear materials."),
    "ACORD_126|GeneralLiabilityLineOfBusiness_Question_AACCode_A": (
        "N", "The applicant neither leases employees to nor from other employers."),
}

# Questions the document deliberately NEVER addresses. Blank is the only
# correct answer; anything stamped here is a borrowed-quote false positive.
YN_UNADDRESSED = [
    "ACORD_125|CommercialPolicy_Question_ABBCode_A",   # business placed in a trust
    "ACORD_125|CommercialPolicy_Question_AAFCode_A",   # uncorrected fire code violations
    "ACORD_126|GeneralLiabilityLineOfBusiness_Question_AAECode_A",  # day care
    "ACORD_126|GeneralLiabilityLineOfBusiness_Question_ACECode_A",  # recreation facilities
    "ACORD_126|GeneralLiabilityLineOfBusiness_Question_ACFCode_A",  # social events
    "ACORD_126|GeneralLiabilityLineOfBusiness_Question_ABDCode_A",  # aircraft/space
    "ACORD_126|GeneralLiabilityLineOfBusiness_Question_KAHCode_A",  # swimming pool
    "ACORD_126|GeneralLiabilityLineOfBusiness_Question_ACGCode_A",  # structural alterations
    # Added 2026-09-01 after a live run answered it "Y". The document never
    # mentions vendors coverage; what it does contain, on the noise pages, is
    # the endorsement TITLE "CG 20 10 12 19 Additional Insured - Owners,
    # Lessees Or Contractors", which the model used as its evidence. The
    # evidence gate rejects a Yes grounded on an EXCLUSION title; an
    # additional-insured endorsement title is the same shape and is not
    # covered. The same question came back blank on the previous run of this
    # identical document - so this box also measures Y/N run-to-run jitter.
    "ACORD_126|GeneralLiabilityLineOfBusiness_Question_ABHCode_A",  # vendors coverage
]
