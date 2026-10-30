import sys
sys.path.insert(0, sys.argv[1])
from data import *
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

OUT = sys.argv[2]
ss = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=14, spaceAfter=6)
H2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=11, spaceAfter=4)
B = ParagraphStyle("b", parent=ss["BodyText"], fontSize=8.5, leading=11)
SM = ParagraphStyle("sm", parent=ss["BodyText"], fontSize=7.5, leading=9.5)
story = []
FOOT = {"code": ""}


def P(t, s=B):
    return Paragraph(t, s)


def kv(rows, widths=(170, 340)):
    t = Table([[P("<b>%s</b>" % a), P(b)] for a, b in rows], colWidths=widths)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def grid(head, rows, widths=None):
    data = [[P("<b>%s</b>" % h, SM) for h in head]] + [[P(str(c), SM) for c in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6e6e6")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def header(line, title, code):
    p = POL[line]
    story.append(P("<b>%s</b>" % p["carrier"], H1))
    story.append(P("NAIC Company Code: %s" % p["naic"]))
    story.append(P(title, H2))
    story.append(kv([("Policy Number", p["number"]), ("Named Insured", INSURED),
                     ("Mailing Address", "%s, %s, %s, %s %s" % (MAIL1, MAIL2, CITY, ST, ZIP)),
                     ("Policy Period", "From %s to %s at 12:01 A.M. Standard Time at the insured's mailing address" % (CUR_EFF, CUR_EXP)),
                     ("Transaction", "RENEWAL of policy %s" % p["number"].replace("-25", "-24")),
                     ("Producer", "%s, %s - Producer Code 4471-PPG" % (AGENT, AGENT_ADDR))]))
    story.append(Spacer(1, 6))
    FOOT["code"] = code


def endorsement(code, title, paras):
    story.append(P("THIS ENDORSEMENT CHANGES THE POLICY. PLEASE READ IT CAREFULLY.", H2))
    story.append(P("<b>%s</b>" % title, H1))
    story.append(P("This endorsement modifies insurance provided under the coverage part shown in the Declarations."))
    for t in paras:
        story.append(Spacer(1, 4)); story.append(P(t))
    story.append(PageBreak())


BOIL = ("Coverage under this endorsement applies only to operations and premises described in the Declarations. "
        "All other terms and conditions of the policy remain unchanged. The insurance afforded by this endorsement "
        "does not apply to any loss, claim or suit first made after the expiration of the policy period, and the "
        "limits shown in the Declarations are not increased by reason of this endorsement. Where this endorsement "
        "conflicts with any other provision of the policy, the provisions of this endorsement shall govern.")

# ---------------- Common declarations / schedule of policies
story.append(P("COMMERCIAL INSURANCE RENEWAL PROGRAMME", H1))
story.append(P("Declarations Package prepared for the Named Insured", H2))
story.append(kv([("Named Insured", INSURED), ("FEIN", FEIN),
                 ("Mailing Address", "%s, %s, %s, %s %s" % (MAIL1, MAIL2, CITY, ST, ZIP)),
                 ("Business Phone", PHONE), ("Website", WEB),
                 ("Form of Business", "Limited Liability Company (2 members)"),
                 ("Programme Term", "%s to %s" % (CUR_EFF, CUR_EXP)),
                 ("Renewal Effective", "%s to %s (next annual term)" % (CUR_EXP, NEXT_EXP)),
                 ("Producer", AGENT + ", " + AGENT_ADDR)]))
story.append(Spacer(1, 8))
story.append(P("SCHEDULE OF POLICIES IN FORCE", H2))
story.append(grid(["Line", "Carrier", "NAIC", "Policy Number", "Term", "Annual Premium"],
                  [["Commercial General Liability", POL["GL"]["carrier"], POL["GL"]["naic"], POL["GL"]["number"], "%s - %s" % (CUR_EFF, CUR_EXP), POL["GL"]["premium"]],
                   ["Business Auto", POL["AUTO"]["carrier"], POL["AUTO"]["naic"], POL["AUTO"]["number"], "%s - %s" % (CUR_EFF, CUR_EXP), POL["AUTO"]["premium"]],
                   ["Workers Compensation and Employers Liability", POL["WC"]["carrier"], POL["WC"]["naic"], POL["WC"]["number"], "%s - %s" % (CUR_EFF, CUR_EXP), POL["WC"]["premium"]],
                   ["Commercial Umbrella", POL["UMB"]["carrier"], POL["UMB"]["naic"], POL["UMB"]["number"], "%s - %s" % (CUR_EFF, CUR_EXP), POL["UMB"]["premium"]],
                   ["Commercial Property", POL["PROP"]["carrier"], POL["PROP"]["naic"], POL["PROP"]["number"], "%s - %s" % (CUR_EFF, CUR_EXP), POL["PROP"]["premium"]],
                   ["", "", "", "", "Total programme premium", "$151,068"]],
                  [110, 140, 35, 85, 85, 60]))
story.append(PageBreak())

# ---------------- Insured information
story.append(P("INSURED INFORMATION SUMMARY", H1))
story.append(P("Underwriting information on file for the renewal term", H2))
story.append(kv([("Named Insured", INSURED), ("FEIN", FEIN), ("NAICS Code", NAICS + " - Plumbing, Heating, and Air-Conditioning Contractors"),
                 ("SIC Code", SIC + " - Plumbing, Heating and Air-Conditioning"), ("Business Started", START),
                 ("Years in Business", "15"), ("Annual Gross Revenue", REVENUE),
                 ("Full-Time Employees", str(FT)), ("Part-Time Employees", str(PT)),
                 ("Primary Contact", "Laura Kessler, Chief Financial Officer - (303) 555-0161 - lkessler@ridgelinemech.com"),
                 ("Inspection Contact", "Marcus Delgado, Operations Manager - (303) 555-0172"),
                 ("Description of Operations", OPS),
                 ("Subcontracted Work", "Approximately 8% of revenue subcontracted (sheet metal ductwork, crane lifts). Certificates of insurance obtained from all subcontractors."),
                 ("Safety Programme", "Written safety manual, weekly toolbox talks, OSHA 30 for all foremen.")]))
story.append(PageBreak())

# ---------------- GL
header("GL", "COMMERCIAL GENERAL LIABILITY COVERAGE PART DECLARATIONS", "SPC CG DS 01 25")
story.append(P("LIMITS OF INSURANCE", H2))
story.append(kv([("Each Occurrence Limit", "$1,000,000"), ("Damage To Premises Rented To You", "$300,000 any one premises"),
                 ("Medical Expense Limit", "$10,000 any one person"), ("Personal and Advertising Injury Limit", "$1,000,000"),
                 ("General Aggregate Limit (Other Than Products-Completed Operations)", "$2,000,000"),
                 ("Products-Completed Operations Aggregate Limit", "$2,000,000"),
                 ("Coverage Form", "Occurrence - CG 00 01 04 13"), ("Aggregate applies", "Per Project (CG 25 03)"),
                 ("Property Damage Deductible", "$2,500 per occurrence"), ("Retroactive Date", "None (occurrence form)"),
                 ("Total Advance Premium", POL["GL"]["premium"]), ("Audit Period", "Annual")]))
story.append(PageBreak())
story.append(P("CLASSIFICATION AND PREMIUM SCHEDULE - " + POL["GL"]["number"], H1))
story.append(P("Premises: Loc 1 - 4150 S Kalamath St, Denver, CO 80223; Loc 2 - 1720 Westland Rd, Cheyenne, WY 82001"))
story.append(Spacer(1, 4))
story.append(grid(["Loc", "Class Code", "Classification", "Premium Basis", "Exposure", "Rate", "Advance Premium"],
                  [list(c) for c in GL_CLASSES] + [["", "", "Total", "", "", "", POL["GL"]["premium"]]], [25, 45, 200, 60, 65, 40, 70]))
story.append(Spacer(1, 6))
story.append(P("Rates are per $1,000 of payroll or total cost. Premium shown includes products-completed operations. "
               "Additional premium for per-project aggregate and blanket additional insured endorsements is included in the total."))
story.append(PageBreak())
story.append(P("FORMS AND ENDORSEMENTS SCHEDULE - " + POL["GL"]["number"], H1))
story.append(grid(["Form Number", "Edition", "Title"],
                  [["CG 00 01", "04 13", "Commercial General Liability Coverage Form"], ["CG 21 06", "05 14", "Exclusion - Access or Disclosure of Confidential or Personal Information"],
                   ["CG 25 03", "05 09", "Designated Construction Project(s) General Aggregate Limit"], ["CG 20 10", "12 19", "Additional Insured - Owners, Lessees or Contractors"],
                   ["CG 20 37", "12 19", "Additional Insured - Completed Operations"], ["CG 24 04", "12 19", "Waiver of Transfer of Rights of Recovery"],
                   ["CG 21 47", "12 07", "Employment-Related Practices Exclusion"], ["CG 21 67", "12 04", "Fungi or Bacteria Exclusion"],
                   ["IL 00 17", "11 98", "Common Policy Conditions"], ["IL 00 21", "09 08", "Nuclear Energy Liability Exclusion"],
                   ["SPC CG 14 22", "01 23", "Contractors Primary and Non-Contributory Endorsement"]], [90, 60, 360]))
story.append(PageBreak())
endorsement("CG 20 10 12 19", "ADDITIONAL INSURED - OWNERS, LESSEES OR CONTRACTORS - SCHEDULED PERSON OR ORGANIZATION",
            ["SCHEDULE: Any person or organization whom you are required to add as an additional insured on this policy under a written contract executed prior to loss.",
             "Section II - Who Is An Insured is amended to include as an additional insured the person(s) or organization(s) shown in the Schedule, but only with respect to liability for bodily injury, property damage or personal and advertising injury caused, in whole or in part, by your acts or omissions.", BOIL, BOIL])
endorsement("CG 25 03 05 09", "DESIGNATED CONSTRUCTION PROJECT(S) GENERAL AGGREGATE LIMIT",
            ["SCHEDULE: All construction projects of the Named Insured.", "For all sums which the insured becomes legally obligated to pay as damages caused by occurrences under Section I - Coverage A, a separate Designated Construction Project General Aggregate Limit applies to each designated construction project.", BOIL, BOIL])

# ---------------- AUTO
header("AUTO", "BUSINESS AUTO DECLARATIONS", "FRM CA DS 03 25")
story.append(P("ITEM TWO - SCHEDULE OF COVERAGES AND COVERED AUTOS", H2))
story.append(grid(["Coverage", "Covered Auto Symbol", "Limit", "Premium"],
                  [["Covered Autos Liability", "1", "$1,000,000 Combined Single Limit each accident", "$27,610"],
                   ["Personal Injury Protection / Medical Payments", "2", "$5,000 each person", "$1,140"],
                   ["Uninsured Motorists", "2", "$1,000,000 each accident", "$2,180"],
                   ["Underinsured Motorists", "2", "$1,000,000 each accident", "incl."],
                   ["Comprehensive", "7", "Actual Cash Value or Cost of Repair, whichever is less, minus $1,000 deductible", "$4,310"],
                   ["Collision", "7", "Actual Cash Value or Cost of Repair, whichever is less, minus $1,000 deductible", "$6,320"],
                   ["Towing and Labor", "7", "$100 per disablement", "$120"],
                   ["Hired Auto Physical Damage", "8", "$75,000 any one auto, $1,000 deductible", "$300"],
                   ["", "", "Total Advance Premium", POL["AUTO"]["premium"]]], [150, 70, 220, 70]))
story.append(Spacer(1, 6))
story.append(kv([("Radius of Operation", "Local - under 50 miles"), ("Vehicle Use", "Service"), ("Garaging", "Denver, CO and Cheyenne, WY")]))
story.append(PageBreak())
story.append(P("ITEM THREE - SCHEDULE OF COVERED AUTOS YOU OWN - " + POL["AUTO"]["number"], H1))
story.append(grid(["Veh #", "Year", "Make", "Model", "Body Type", "VIN", "Garaging Address", "Cost New", "Comp Ded", "Coll Ded", "Premium"],
                  [list(v) for v in VEHICLES], [25, 30, 45, 55, 50, 90, 100, 45, 35, 35, 40]))
story.append(Spacer(1, 6))
story.append(grid(["Veh #", "GVW", "Class Code", "Territory", "Radius", "Use", "Lienholder"],
                  [["1", "9,070", "21499", "112", "50", "Service", "Wells Fargo Equipment Finance - Loan 77-0042218"],
                   ["2", "9,350", "21499", "112", "50", "Service", "None"],
                   ["3", "14,000", "31499", "112", "50", "Service", "Ally Bank - Loan 5521-098834"],
                   ["4", "9,500", "21499", "205", "50", "Service", "Ford Credit - Loan 4410-778215"],
                   ["5", "10,250", "31499", "112", "50", "Service", "None"]], [30, 45, 50, 45, 40, 50, 250]))
story.append(PageBreak())
story.append(P("SCHEDULE OF DRIVERS - " + POL["AUTO"]["number"], H1))
story.append(grid(["#", "Driver Name", "City / State / ZIP", "Sex", "Marital", "Date of Birth", "Yrs Exp", "Yr Lic", "License #", "Lic St", "Date of Hire", "Veh #", "Use %"],
                  [[d[0], "%s %s. %s" % (d[1], d[2], d[3]), "%s, %s %s" % (d[4], d[5], d[6]), d[7], d[8], d[9], d[10], d[11], d[12], d[13], d[14], d[15], d[16]] for d in DRIVERS],
                  [15, 80, 80, 22, 32, 50, 28, 28, 60, 25, 50, 25, 25]))
story.append(Spacer(1, 6))
story.append(P("MVRs obtained annually for all scheduled drivers. Motor vehicle record: Derek A. Nguyen - one speeding violation 03/2024 (11-15 over), Denver CO."))
story.append(PageBreak())
endorsement("CA 20 48 10 13", "DESIGNATED INSURED FOR COVERED AUTOS LIABILITY COVERAGE",
            ["This endorsement identifies person(s) or organization(s) who are \"insureds\" for Covered Autos Liability Coverage under the Who Is An Insured provision of the Coverage Form.", BOIL, BOIL])
story.append(P("FORMS SCHEDULE - " + POL["AUTO"]["number"], H1))
story.append(grid(["Form", "Edition", "Title"],
                  [["CA 00 01", "10 13", "Business Auto Coverage Form"], ["CA 01 26", "10 13", "Colorado Changes"], ["CA 01 76", "11 16", "Wyoming Changes"],
                   ["CA 20 48", "10 13", "Designated Insured for Covered Autos Liability Coverage"], ["CA 04 44", "10 13", "Waiver of Transfer of Rights of Recovery"],
                   ["CA 21 31", "10 13", "Colorado Uninsured Motorists Coverage"], ["CA 99 03", "10 13", "Auto Medical Payments Coverage"]], [90, 60, 360]))
story.append(PageBreak())

# ---------------- WC
header("WC", "WORKERS COMPENSATION AND EMPLOYERS LIABILITY POLICY - INFORMATION PAGE", "PEI WC 00 00 01 A")
story.append(kv([("Item 3.A. Workers Compensation", "Part One of the policy applies to the Workers Compensation Law of the states listed here: CO, WY"),
                 ("Item 3.B. Employers Liability", "Bodily Injury by Accident $1,000,000 each accident; Bodily Injury by Disease $1,000,000 policy limit; Bodily Injury by Disease $1,000,000 each employee"),
                 ("Item 3.C. Other States Insurance", "All states except ND, OH, WA, WY monopolistic exclusions as shown and states designated in Item 3.A."),
                 ("Officers / Members", "Laura Kessler (Member, 50%) - INCLUDED; Gregory Hale (Member, 50%) - EXCLUDED"),
                 ("Experience Modification", "%s effective %s (NCCI Risk ID 051234987)" % (XMOD, CUR_EFF)),
                 ("Premium Adjustment", "Annual audit")]))
story.append(PageBreak())
story.append(P("ITEM 4 - CLASSIFICATION OF OPERATIONS - " + POL["WC"]["number"], H1))
story.append(grid(["State", "Class Code", "Classification", "Estimated Annual Remuneration", "Rate per $100", "Estimated Premium"],
                  [list(w) for w in WC_CLASSES], [35, 45, 200, 90, 55, 70]))
story.append(Spacer(1, 6))
story.append(kv([("Total Manual Premium", "$62,644"), ("Experience Modification %s" % XMOD, "-$7,517"),
                 ("Schedule Credit", "-$21,500"), ("Expense Constant / Terrorism / Catastrophe", "$0"), ("Total Estimated Annual Premium", POL["WC"]["premium"]),
                 ("Wyoming note", "Wyoming is a monopolistic state; WY payroll shown for Other States / stop-gap Employers Liability rating only.")]))
story.append(PageBreak())
story.append(P("SCHEDULE OF FORMS AND ENDORSEMENTS - " + POL["WC"]["number"], H1))
story.append(grid(["Form", "Title"], [["WC 00 00 00 C", "Workers Compensation and Employers Liability Insurance Policy"], ["WC 00 03 13", "Waiver of Our Right to Recover From Others"],
                                      ["WC 05 06 01", "Colorado Amendatory Endorsement"], ["WC 00 03 03 D", "Employers Liability Coverage Endorsement (stop gap - WY)"],
                                      ["WC 00 04 14", "Notification of Change in Ownership Endorsement"]], [120, 390]))
story.append(PageBreak())

# ---------------- UMBRELLA
header("UMB", "COMMERCIAL UMBRELLA LIABILITY DECLARATIONS", "GSS UM DS 01 25")
story.append(kv([("Each Occurrence Limit", "$5,000,000"), ("Aggregate Limit", "$5,000,000"),
                 ("Self-Insured Retention", "$10,000 each occurrence"), ("Coverage Basis", "Occurrence - follow form of scheduled underlying insurance except as stated"),
                 ("Premium", POL["UMB"]["premium"])]))
story.append(Spacer(1, 6))
story.append(P("SCHEDULE OF UNDERLYING INSURANCE", H2))
story.append(grid(["Type of Coverage", "Carrier", "Policy Number", "Policy Period", "Limits"],
                  [["Commercial General Liability", POL["GL"]["carrier"], POL["GL"]["number"], "%s - %s" % (CUR_EFF, CUR_EXP), "$1,000,000 each occurrence / $2,000,000 general aggregate / $2,000,000 products-completed operations aggregate"],
                   ["Business Auto Liability", POL["AUTO"]["carrier"], POL["AUTO"]["number"], "%s - %s" % (CUR_EFF, CUR_EXP), "$1,000,000 combined single limit each accident"],
                   ["Employers Liability", POL["WC"]["carrier"], POL["WC"]["number"], "%s - %s" % (CUR_EFF, CUR_EXP), "$1,000,000 each accident / $1,000,000 disease policy limit / $1,000,000 disease each employee"]],
                  [100, 120, 80, 75, 135]))
story.append(PageBreak())
endorsement("GSS UM 21 04 01 23", "CONTRACTORS LIMITATION - HEIGHT AND RESIDENTIAL CONSTRUCTION",
            ["This insurance does not apply to bodily injury or property damage arising out of operations performed at a height of more than three stories above grade.", BOIL, BOIL])
story.append(P("FORMS SCHEDULE - " + POL["UMB"]["number"], H1))
story.append(grid(["Form", "Title"], [["GSS UM 00 01 01 23", "Commercial Umbrella Liability Coverage Form"], ["GSS UM 21 04 01 23", "Contractors Limitation"],
                                      ["GSS UM 21 30 01 23", "Exclusion - Professional Services"], ["IL 00 17 11 98", "Common Policy Conditions"]], [120, 390]))
story.append(PageBreak())

# ---------------- PROPERTY
header("PROP", "COMMERCIAL PROPERTY COVERAGE PART DECLARATIONS", "CPC CP DS 00 25")
story.append(grid(["Prem #", "Bldg #", "Coverage", "Limit", "Covered Cause of Loss", "Coinsurance", "Valuation", "Deductible"],
                  [["1", "1", "Building", "$2,350,000", "Special", "90%", "Replacement Cost", "$5,000"],
                   ["1", "1", "Business Personal Property", "$640,000", "Special", "90%", "Replacement Cost", "$5,000"],
                   ["1", "2", "Building", "$1,780,000", "Special", "90%", "Replacement Cost", "$5,000"],
                   ["1", "2", "Business Personal Property", "$1,150,000", "Special", "90%", "Replacement Cost", "$5,000"],
                   ["2", "1", "Building", "$910,000", "Special", "80%", "Replacement Cost", "$5,000"],
                   ["2", "1", "Business Personal Property", "$285,000", "Special", "80%", "Replacement Cost", "$5,000"],
                   ["All", "", "Business Income with Extra Expense", "$750,000", "Special", "1/3 monthly limit", "ALS", "72 hours"]],
                  [32, 32, 110, 60, 60, 55, 75, 50]))
story.append(Spacer(1, 6))
story.append(kv([("Windstorm or Hail Deductible", "2% of the building value at each premises, minimum $10,000"),
                 ("Earthquake / Flood", "Not covered"), ("Equipment Breakdown", "Included, $2,500 deductible"),
                 ("Total Advance Premium", POL["PROP"]["premium"])]))
story.append(PageBreak())
story.append(P("SCHEDULE OF LOCATIONS AND BUILDINGS (COPE) - " + POL["PROP"]["number"], H1))
for L in LOCATIONS:
    story.append(P("<b>Premises %s / Building %s</b> - %s" % (L[0], L[1], L[2]), H2))
    story.append(kv([("Occupancy", L[3]), ("Construction", L[4]), ("Year Built", L[5]), ("Number of Stories", L[6]),
                     ("Square Footage", L[7]), ("Automatic Sprinkler", L[8]), ("Protection Class", L[9]),
                     ("Roof Type", L[10]), ("Roof Year Updated", L[11]), ("Building Limit", L[12]),
                     ("Business Personal Property Limit", L[13]), ("Fire Alarm", "Central station" if L[0] == "1" else "Local"),
                     ("Distance to Hydrant / Fire Station", "250 ft / 1.2 miles" if L[0] == "1" else "400 ft / 2.8 miles")]))
    story.append(Spacer(1, 4))
    if L[1] == "2":
        story.append(PageBreak())
story.append(PageBreak())
endorsement("CP 03 21 10 12", "WINDSTORM OR HAIL PERCENTAGE DEDUCTIBLE",
            ["SCHEDULE: Premises 1 Buildings 1-2: 2%; Premises 2 Building 1: 2%. Minimum deductible $10,000 per occurrence.",
             "The Windstorm or Hail Deductible, as shown in the Schedule and set forth in this endorsement, applies to covered loss or damage caused directly or indirectly by Windstorm or Hail.", BOIL])
story.append(P("FORMS SCHEDULE - " + POL["PROP"]["number"], H1))
story.append(grid(["Form", "Title"], [["CP 00 10 10 12", "Building and Personal Property Coverage Form"], ["CP 10 30 09 17", "Causes of Loss - Special Form"],
                                      ["CP 00 30 10 12", "Business Income (and Extra Expense) Coverage Form"], ["CP 03 21 10 12", "Windstorm or Hail Percentage Deductible"],
                                      ["CP 01 40 07 06", "Exclusion of Loss Due to Virus or Bacteria"], ["IL 09 35 07 02", "Exclusion of Certain Computer-Related Losses"]], [120, 390]))


def foot(c, doc):
    c.saveState(); c.setFont("Helvetica", 7)
    c.drawString(40, 25, "%s   Named Insured: %s   Policy term %s - %s" % (FOOT["code"], INSURED, CUR_EFF, CUR_EXP))
    c.drawRightString(572, 25, "Page %d" % doc.page)
    c.restoreState()


SimpleDocTemplate(OUT, pagesize=letter, leftMargin=40, rightMargin=40, topMargin=40, bottomMargin=45,
                  title="Ridgeline Mechanical - Renewal Declarations").build(story, onFirstPage=foot, onLaterPages=foot)
