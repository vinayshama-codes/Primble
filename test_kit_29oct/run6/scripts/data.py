"""Ridgeline Mechanical Services LLC - fictional insured for the 29 Oct live test kit."""
INSURED = "Ridgeline Mechanical Services LLC"
FEIN = "84-5512309"
MAIL1, MAIL2, CITY, ST, ZIP = "4150 S Kalamath St", "Suite 200", "Denver", "CO", "80223"
PHONE = "(103) 555-0148"
WEB = "www.ridgelinemech.com"
START = "03/15/2011"
REVENUE = "$9,120,000"
FT, PT = 70, 4
NAICS, SIC = "238220", "1711"
OPS = ("Commercial and residential HVAC installation, service and repair; commercial and residential "
       "plumbing installation, service and repair; boiler and rooftop unit replacement. No work above "
       "three stories, no fire suppression sprinkler work, no gas main or utility work.")
AGENT = "Peak & Prairie Insurance Group, Inc."
AGENT_ADDR = "1600 Broadway, Suite 1450, Denver, CO 80202"
CUR_EFF, CUR_EXP = "12/01/2025", "12/01/2026"
NEXT_EXP = "12/01/2027"

POL = {
    "GL": dict(carrier="Summit Peak Casualty Company", naic="29874", number="CGL-4471209-25", premium="$30,036"),
    "AUTO": dict(carrier="Front Range Mutual Insurance Company", naic="31266", number="BAP-7720158-25", premium="$52,080"),
    "WC": dict(carrier="Pinnacle Employers Insurance Company", naic="13042", number="WC-3398041-25", premium="$33,627"),
    "UMB": dict(carrier="Granite Shield Specialty Insurance Company", naic="40217", number="CUP-5510873-25", premium="$15,350"),
    "PROP": dict(carrier="Cottonwood Property & Casualty Insurance Company", naic="226310", number="CPP-6609312-25", premium="$19,975"),
}

GL_CLASSES = [  # loc, code, description, basis, exposure, rate, premium
    ("1", "98482", "Air Conditioning Systems or Equipment - dealers or distributors and installation, servicing or repair", "Payroll", "$1,315,000", "9.412", "$12,377"),
    ("1", "98483", "Plumbing - commercial and industrial", "Payroll", "$905,000", "11.206", "$10,141"),
    ("1", "91580", "Contractors - executive supervisors or executive superintendents", "Payroll", "$210,000", "6.880", "$1,445"),
    ("2", "98482", "Air Conditioning Systems or Equipment - installation, servicing or repair", "Payroll", "$240,000", "9.412", "$2,259"),
    ("1", "91342", "Contractors - subcontracted work - in connection with construction", "Total Cost", "$442,000", "8.630", "$3,814"),
]

VEHICLES = [  # no, year, make, model, body, VIN, garaging, cost new, comp ded, coll ded, premium
    ("1", "2023", "Ford", "Transit 250", "Cargo Van", "1FTBR1C82PKA41827", "4150 S Kalamath St, Denver, CO 80223", "$52,400", "$1,000", "$1,000", "$9,860"),
    ("2", "2022", "Ram", "ProMaster 2500", "Cargo Van", "3C6LRVDG4NE118362", "4150 S Kalamath St, Denver, CO 80223", "$48,950", "$1,000", "$1,000", "$9,420"),
    ("3", "2024", "Ford", "F-350 Super Duty", "Pickup w/ Utility Body", "1FT8W3BT6RED20915", "4150 S Kalamath St, Denver, CO 80223", "$71,300", "$1,000", "$1,000", "$12,140"),
    ("4", "2025", "Ford", "E-Transit 350", "Cargo Van", "1FTBW9CK3SKA22471", "1720 Westland Rd, Cheyenne, WY 82001", "$58,700", "$1,000", "$1,000", "$11,240"),
    ("5", "2024", "Chevrolet", "Silverado 2500HD", "Pickup w/ Service Body", "1GC4YLE79RF318204", "4150 S Kalamath St, Denver, CO 80223", "$64,900", "$1,000", "$1,000", "$9,420"),
]
VIN_COUNTY = {"Denver": "Denver", "Cheyenne": "Laramie"}

DRIVERS = [  # no, first, mi, last, city, st, zip, sex, marital, dob, yrs exp, yr lic, lic no, lic st, hired, veh, use%
    ("1", "Marcus", "J", "Delgado", "Denver", "CO", "80219", "M", "M", "04/22/1979", "28", "1995", "07-412-3398", "CO", "03/15/2011", "3", "100"),
    ("2", "Tanya", "R", "Whitfield", "Lakewood", "CO", "80226", "F", "S", "09/08/1988", "19", "2004", "11-208-7741", "CO", "06/01/2014", "1", "100"),
    ("3", "Derek", "A", "Nguyen", "Aurora", "CO", "80012", "M", "M", "12/03/1991", "16", "2008", "14-559-0263", "CO", "02/10/2017", "2", "100"),
    ("4", "Samuel", "K", "Ortiz", "Englewood", "CO", "80110", "M", "S", "07/19/1996", "11", "2013", "18-337-9120", "CO", "08/22/2020", "1", "50"),
    ("5", "Kayla", "M", "Brennan", "Cheyenne", "WY", "82009", "F", "M", "02/14/1985", "22", "2001", "102847-551", "WY", "04/05/2019", "4", "100"),
    ("6", "Luis", "E", "Carrasco", "Westminster", "CO", "80031", "M", "M", "11/27/1990", "17", "2007", "12-604-1187", "CO", "01/12/2026", "5", "100"),
]

WC_CLASSES = [  # state, code, description, payroll, rate, premium
    ("CO", "5537", "HVAC Systems - installation, service and repair & drivers", "$1,315,000", "2.63", "$34,585"),
    ("CO", "5183", "Plumbing NOC & drivers", "$905,000", "2.22", "$20,091"),
    ("CO", "8810", "Clerical Office Employees NOC", "$185,000", "0.11", "$204"),
    ("CO", "8742", "Salespersons - outside", "$95,000", "0.29", "$276"),
    ("WY", "5537", "HVAC Systems - stop-gap Employers Liability only (WY state fund)", "$240,000", "3.12", "$7,488"),
]
XMOD = "0.88"

LOCATIONS = [  # loc, bldg, address, occupancy, construction, year built, stories, sq ft, sprinkler, PC, roof, roof yr, bldg value, bpp value
    ("1", "1", "4150 S Kalamath St, Denver, CO 80223", "Contractor office and fabrication shop", "Joisted Masonry", "1987", "2", "14,600", "Yes - 100% wet system", "2", "Modified bitumen", "2022", "$2,350,000", "$640,000"),
    ("1", "2", "4150 S Kalamath St, Denver, CO 80223", "Warehouse - HVAC equipment and pipe storage", "Non-Combustible", "1998", "1", "22,000", "No", "2", "Metal standing seam", "2016", "$1,780,000", "$1,150,000"),
    ("2", "1", "1720 Westland Rd, Cheyenne, WY 8200", "Branch shop and parts storage", "Masonry Non-Combustible", "2006", "1", "8,400", "No", "4", "Built-up tar and gravel", "2014", "$910,000", "$285,000"),
]
