import sys
sys.path.insert(0, sys.argv[1])
from data import *
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

ss = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=14)
B = ParagraphStyle("b", parent=ss["BodyText"], fontSize=8.5, leading=11)
SM = ParagraphStyle("sm", parent=ss["BodyText"], fontSize=7.5, leading=9.5)

# line -> list of (term_suffix, eff, exp, [claims]) ; claim = (claim no, loss date, reported, description, paid, reserve, status)
RUN1 = {
    "GL": [("-20", "12/01/2020", "12/01/2021", []),
           ("-21", "12/01/2021", "12/01/2022", [("GL-22-004417", "06/09/2022", "06/10/2022", "Third-party property damage - water damage at customer site from failed PEX fitting after installation", "$36,240", "$0", "Closed")]),
           ("-22", "12/01/2022", "12/01/2023", [])],
    "AUTO": [("-20", "12/01/2020", "12/01/2021", []),
             ("-21", "12/01/2021", "12/01/2022", [("BA-22-118830", "05/17/2022", "05/18/2022", "Rear-end collision - insured Veh 2 (2022 Ram ProMaster) struck third-party vehicle at stop light; BI and PD to claimant", "$18,420", "$0", "Closed")]),
             ("-22", "12/01/2022", "12/01/2023", [("BA-23-020311", "02/03/2023", "02/06/2023", "Insured vehicle backed into customer gate - property damage", "$4,180", "$0", "Closed")])],
    "WC": [("-20", "12/01/2020", "12/01/2021", [("WC-21-77142", "09/14/2021", "09/14/2021", "Laceration to left hand from sheet metal edge - medical only", "$6,915", "$0", "Closed")]),
           ("-21", "12/01/2021", "12/01/2022", []),
           ("-22", "12/01/2022", "12/01/2023", [("WC-23-81906", "10/02/2023", "10/03/2023", "Lumbar strain lifting condenser unit - indemnity and medical", "$11,300", "$2,500", "Open")])],
    "UMB": [("-20", "12/01/2020", "12/01/2021", []), ("-21", "12/01/2021", "12/01/2022", []), ("-22", "12/01/2022", "12/01/2023", [])],
    "PROP": [("-20", "12/01/2020", "12/01/2021", []), ("-21", "12/01/2021", "12/01/2022", []), ("-22", "12/01/2022", "12/01/2023", [])],
}
RUN2 = {
    "GL": [("-23", "12/01/2023", "12/01/2024", [("GL-24-009802", "08/14/2024", "08/15/2024", "Third-party property damage - customer roof membrane damaged during rooftop unit replacement", "$22,610", "$0", "Closed")]),
           ("-24", "12/01/2024", "12/01/2025", []), ("-25", "12/01/2025", "12/01/2026", [])],
    "AUTO": [("-23", "12/01/2023", "12/01/2024", []),
             ("-24", "12/01/2024", "12/01/2025", [("BA-25-004127", "01/21/2025", "01/21/2025", "Comprehensive - windshield replacement, Veh 3 (2024 Ford F-350)", "$1,240", "$0", "Closed")]),
             ("-25", "12/01/2025", "12/01/2026", [])],
    "WC": [("-23", "12/01/2023", "12/01/2024", []),
           ("-24", "12/01/2024", "12/01/2025", [("WC-25-90433", "06/30/2025", "07/01/2025", "Back strain - fall from step ladder in mechanical room", "$8,450", "$14,000", "Open")]),
           ("-25", "12/01/2025", "12/01/2026", [])],
    "UMB": [("-23", "12/01/2023", "12/01/2024", []), ("-24", "12/01/2024", "12/01/2025", []), ("-25", "12/01/2025", "12/01/2026", [])],
    "PROP": [("-23", "12/01/2023", "12/01/2024", [("CP-24-033118", "07/28/2024", "07/30/2024", "Hail damage to warehouse roof - Premises 1 Building 2, 4150 S Kalamath St", "$48,300", "$0", "Closed")]),
             ("-24", "12/01/2024", "12/01/2025", []), ("-25", "12/01/2025", "12/01/2026", [])],
}
NAMES = {"GL": "Commercial General Liability", "AUTO": "Business Auto", "WC": "Workers Compensation and Employers Liability",
         "UMB": "Commercial Umbrella", "PROP": "Commercial Property"}


def money(s):
    return int(s.replace("$", "").replace(",", ""))


def build(run, out, valued):
    story = []
    for line, terms in run.items():
        p = POL[line]
        story.append(Paragraph("<b>%s</b>" % p["carrier"], H1))
        story.append(Paragraph("LOSS RUN REPORT - %s" % NAMES[line], ss["Heading2"]))
        story.append(Paragraph("Insured: %s &nbsp;&nbsp; FEIN: %s &nbsp;&nbsp; Mailing address: %s, %s, %s, %s %s" % (INSURED, FEIN, MAIL1, MAIL2, CITY, ST, ZIP), B))
        story.append(Paragraph("Valuation Date: %s &nbsp;&nbsp; Report requested by: %s" % (valued, AGENT), B))
        story.append(Spacer(1, 6))
        tp = tr = 0
        for sfx, eff, exp, claims in terms:
            num = p["number"][:-3] + sfx
            story.append(Paragraph("<b>Policy %s &nbsp; Term %s - %s</b>" % (num, eff, exp), B))
            if not claims:
                story.append(Paragraph("NO LOSSES REPORTED FOR THIS POLICY TERM AS OF THE VALUATION DATE.", B))
            else:
                rows = [["Claim #", "Date of Loss", "Date Reported", "Description", "Paid", "Reserve", "Total Incurred", "Status"]]
                for c in claims:
                    rows.append([c[0], c[1], c[2], Paragraph(c[3], SM), c[4], c[5], "${:,}".format(money(c[4]) + money(c[5])), c[6]])
                    tp += money(c[4]); tr += money(c[5])
                t = Table(rows, colWidths=[70, 55, 55, 300, 55, 50, 65, 45])
                t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                                       ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6e6e6")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
                story.append(t)
            story.append(Spacer(1, 6))
        story.append(Paragraph("<b>Totals for all terms shown: Paid ${:,} &nbsp; Reserve ${:,} &nbsp; Incurred ${:,}</b>".format(tp, tr, tp + tr), B))
        story.append(PageBreak())
    SimpleDocTemplate(out, pagesize=landscape(letter), leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36,
                      title="Ridgeline Mechanical loss runs").build(story)


O = "/Users/vinaysharma/Downloads/Primble-16thsep/test_kit_29oct/"
build(RUN1, O + "04_loss_runs_2021_2023.pdf", "01/10/2024")
build(RUN2, O + "later_05_loss_runs_2024_2026.pdf", "10/20/2026")
