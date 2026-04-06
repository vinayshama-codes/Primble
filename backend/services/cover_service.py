import io
import json
import logging
import textwrap
from datetime import datetime, timezone
from typing import List

from config.settings import groq_client

logger = logging.getLogger(__name__)


def generate_ai_cover_narrative(
    facts: dict,
    flags: dict,
    sqs_results: dict,
    form_ids: List[str],
    org_name: str,
    user: dict = None,
) -> dict:
    sqs_summary = [
        {
            "form": fid,
            "score": sqs.get("sqs_score"),
            "grade": sqs.get("grade"),
            "tier": sqs.get("tier"),
            "routing": sqs.get("routing_decision"),
            "breakdown": sqs.get("breakdown", {}),
            "issues": sqs.get("issues", []),
            "recommendations": sqs.get("recommendations", []),
        }
        for fid, sqs in sqs_results.items()
    ]
    avg_sqs = int(
        sum(s.get("sqs_score", 0) for s in sqs_results.values()) / max(len(sqs_results), 1)
    )
    prompt = f"""You are an expert commercial insurance underwriting analyst at Acordly.
Generate a professional cover page summary for this ACORD submission package.

SUBMISSION DATA:
Agent/User: {user.get('full_name', '') if user else ''}
Agency/Org: {org_name}
Applicant: {facts.get('applicant_name', 'Unknown')}
Lines of Business: {facts.get('lines_of_business', [])}
Effective Date: {facts.get('effective_date', 'Not specified')}
Operations: {facts.get('operations_description', 'Not provided')}
Revenue: {facts.get('total_revenue', 'Not provided')}
Forms Generated: {', '.join(form_ids)}
Overall Average SQS: {avg_sqs}/100
SQS Results: {json.dumps(sqs_summary)}

Respond with ONLY a valid JSON object with exactly three keys:
"narrative": A 3-4 paragraph professional narrative (plain text, no markdown)
"sqs_reasoning": A single paragraph explaining the SQS score
"ai_block": A machine-readable structured JSON object with: submission_id, generated_at,
  agent_name, applicant_name, org_name, lines_of_business, effective_date, expiration_date,
  total_revenue, total_payroll, num_employees, entity_type, fein, naics_code, prior_carrier,
  forms_included, sqs_scores, sqs_grades, sqs_breakdowns, overall_avg_sqs,
  overall_routing_recommendation, hard_stops, soft_stops, risk_flags,
  acordly_version: "12.3.1", a2a_schema_version: "1.0"

Return ONLY the JSON object."""

    try:
        r = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = (r.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = raw.replace("```json", "").replace("```", "").strip()
        s, e = raw.find("{"), raw.rfind("}")
        if s != -1 and e != -1:
            result = json.loads(raw[s: e + 1])
            return {
                "narrative":     result.get("narrative", ""),
                "sqs_reasoning": result.get("sqs_reasoning", ""),
                "ai_block":      result.get("ai_block", {}),
            }
    except Exception as ex:
        logger.error(f"Cover page AI generation failed: {ex}")

    return {
        "narrative":     f"This ACORD submission package was prepared by {org_name} for applicant {facts.get('applicant_name', 'Unknown')}.",
        "sqs_reasoning": f"Average SQS of {avg_sqs}/100 across {len(form_ids)} form(s).",
        "ai_block": {
            "agent_name":      (user.get("full_name", "") if user else ""),
            "org_name":        org_name,
            "forms_included":  form_ids,
            "overall_avg_sqs": avg_sqs,
            "acordly_version": "12.3.1",
        },
    }


def _build_cover_page_fallback(
    facts, sqs_results, form_ids, org_name, narrative, ai_block, generated_at
) -> bytes:
    try:
        lines = [
            "ACORDLY SUBMISSION PACKAGE COVER PAGE",
            f"Generated: {generated_at}",
            f"Prepared by: {org_name}",
            f"Applicant: {facts.get('applicant_name', 'Unknown')}",
            f"Forms: {', '.join(form_ids)}",
            "",
            "SQS SCORES:",
        ]
        for fid, sqs in sqs_results.items():
            lines.append(f"  {fid}: {sqs.get('sqs_score', 0)}/100 ({sqs.get('grade', '?')})")
        lines += [
            "", "SUMMARY:", narrative[:1000],
            "", "AI DATA BLOCK:", json.dumps(ai_block, indent=2)[:2000],
        ]
        content = "\n".join(lines)
        pdf_content = (
            f"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            f"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            f"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
            f"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>\nendobj\n"
            f"4 0 obj<</Length {len(content) + 50}>>\nstream\n"
            f"BT /F1 8 Tf 40 750 Td 12 TL\n"
        )
        for line in content.split("\n")[:80]:
            safe_line = line.replace("(", "\\(").replace(")", "\\)").replace("\\", "\\\\")
            pdf_content += f"({safe_line}) Tj T*\n"
        pdf_content += (
            "ET\nendstream\nendobj\n"
            "5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
            "xref\n0 6\n0000000000 65535 f\n"
            "trailer<</Size 6/Root 1 0 R>>\n%%EOF"
        )
        return pdf_content.encode("latin-1", errors="replace")
    except Exception as ex:
        logger.error(f"Fallback cover page error: {ex}")
        return b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\nxref\n0 2\ntrailer<</Size 2/Root 1 0 R>>\n%%EOF"


def build_cover_page_pdf(
    facts: dict,
    flags: dict,
    sqs_results: dict,
    form_ids: List[str],
    org_name: str,
    narrative: str,
    ai_block: dict,
    sqs_reasoning: str = "",
    user: dict = None,
) -> bytes:
    generated_at = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")

    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib import colors
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer,
            Table, TableStyle, HRFlowable, KeepTogether,
        )
        from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY

        # ── Palette ───────────────────────────────────────────────
        NAVY       = colors.HexColor("#0f172a")
        PINK       = colors.HexColor("#e6007a")
        PINK_PALE  = colors.HexColor("#fce7f3")
        SLATE      = colors.HexColor("#64748b")
        LIGHT      = colors.HexColor("#f8fafc")
        LIGHTER    = colors.HexColor("#f1f5f9")
        WHITE      = colors.white
        GREEN      = colors.HexColor("#10b981")
        GREEN_BG   = colors.HexColor("#d1fae5")
        YELLOW     = colors.HexColor("#f59e0b")
        YELLOW_BG  = colors.HexColor("#fef3c7")
        RED        = colors.HexColor("#ef4444")
        RED_BG     = colors.HexColor("#fee2e2")
        BORDER     = colors.HexColor("#e2e8f0")
        BORDER_MID = colors.HexColor("#cbd5e1")
        TEXT_MAIN  = colors.HexColor("#1e293b")
        TEXT_MUTE  = colors.HexColor("#64748b")
        TEXT_HINT  = colors.HexColor("#94a3b8")
        HIDDEN_BG  = colors.white
        HIDDEN_FG  = colors.white

        PAGE_W, PAGE_H = letter
        HERO_H = 2.0 * inch

        def sqs_color(score):
            if score is None: return SLATE
            if score >= 90:   return GREEN
            if score >= 75:   return YELLOW
            return RED

        def sqs_bg(score):
            if score is None: return LIGHTER
            if score >= 90:   return GREEN_BG
            if score >= 75:   return YELLOW_BG
            return RED_BG

        styles = getSampleStyleSheet()

        def S(name, **kw):
            return ParagraphStyle(name, parent=styles["Normal"], **kw)

        # ── Canvas background callbacks ───────────────────────────
        def on_first_page(c, doc):
            c.saveState()
            # Full-page light background
            c.setFillColor(colors.HexColor("#f8fafc"))
            c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
            # Navy hero band
            c.setFillColor(NAVY)
            c.rect(0, PAGE_H - HERO_H, PAGE_W, HERO_H, fill=1, stroke=0)
            # Pink diagonal triangle (top-right)
            c.setFillColor(PINK)
            path = c.beginPath()
            path.moveTo(PAGE_W - 130, PAGE_H - HERO_H)
            path.lineTo(PAGE_W,       PAGE_H - HERO_H)
            path.lineTo(PAGE_W,       PAGE_H)
            path.close()
            c.drawPath(path, fill=1, stroke=0)
            # Thin pink top border
            c.setFillColor(PINK)
            c.rect(0, PAGE_H - 3, PAGE_W, 3, fill=1, stroke=0)
            # Dark decorative circle (top-left, partially clipped)
            c.setFillColor(colors.HexColor("#1e3a5f"))
            c.circle(28, PAGE_H - 8, 52, fill=1, stroke=0)
            # Pink left accent bar (body area only)
            c.setFillColor(PINK)
            c.rect(0, 0.85 * inch, 3, PAGE_H - HERO_H - 1.05 * inch, fill=1, stroke=0)
            # Dot grid texture (bottom-right)
            c.setFillColor(colors.HexColor("#dde3ec"))
            for row in range(7):
                for col in range(7):
                    cx = PAGE_W - 0.5 * inch - col * 13
                    cy = 0.4 * inch + row * 13
                    c.circle(cx, cy, 1.8, fill=1, stroke=0)
            c.restoreState()

        def on_later_pages(c, doc):
            c.saveState()
            c.setFillColor(colors.HexColor("#f8fafc"))
            c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
            c.setFillColor(PINK)
            c.rect(0, PAGE_H - 3, PAGE_W, 3, fill=1, stroke=0)
            c.setFillColor(PINK)
            c.rect(0, 0.65 * inch, 3, PAGE_H - 0.95 * inch, fill=1, stroke=0)
            c.setFillColor(colors.HexColor("#dde3ec"))
            for row in range(4):
                for col in range(4):
                    cx = PAGE_W - 0.5 * inch - col * 13
                    cy = 0.4 * inch + row * 13
                    c.circle(cx, cy, 1.8, fill=1, stroke=0)
            c.restoreState()

        # ── Derived values ────────────────────────────────────────
        agent_name = (user.get("full_name", "") if user else "") or "—"
        applicant  = facts.get("applicant_name", "—") or "—"
        eff_date   = facts.get("effective_date", "—") or "—"
        exp_date   = facts.get("expiration_date", "—") or "—"
        entity     = facts.get("entity_type", "—") or "—"
        revenue    = facts.get("total_revenue", "—") or "—"
        employees  = str(facts.get("num_employees", "—") or "—")
        lobs_raw   = facts.get("lines_of_business", [])
        lobs       = ", ".join(lobs_raw) if lobs_raw else "—"
        addr       = facts.get("mailing_address", "—") or "—"
        prior_carr = facts.get("prior_carrier", "—") or "—"
        forms_list = ", ".join(form_ids) if form_ids else "—"
        avg_sqs    = int(
            sum(s.get("sqs_score", 0) for s in sqs_results.values()) / max(len(sqs_results), 1)
        )
        sqs_hex = "#10b981" if avg_sqs >= 75 else "#f59e0b" if avg_sqs >= 60 else "#ef4444"

        routing_labels = {
            "auto_quote":  "✅ Auto-Quote",
            "review":      "🔍 Light Review",
            "full_review": "📋 Full Review",
            "hold":        "🚫 Hold",
        }

        # ── Story ─────────────────────────────────────────────────
        story = []

        # ── Section header helper ─────────────────────────────────
        def section_header(title):
            bar = Table([[""]], colWidths=[0.055 * inch], rowHeights=[0.20 * inch])
            bar.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), PINK),
                ("LEFTPADDING",   (0, 0), (-1, -1), 0),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
                ("TOPPADDING",    (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            title_p = Paragraph(
                title,
                S(f"SH_{title[:8].replace(' ','_')}",
                  fontName="Helvetica-Bold", fontSize=11, textColor=NAVY, leading=15)
            )
            hdr = Table([[bar, title_p]], colWidths=[0.11 * inch, 6.89 * inch])
            hdr.setStyle(TableStyle([
                ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING",   (0, 0), (-1, -1), 0),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
                ("TOPPADDING",    (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LINEBELOW",     (0, 0), (-1, -1), 0.5, BORDER),
            ]))
            return hdr

        # ── 1. HERO ───────────────────────────────────────────────
        def flowables_to_col(items):
            rows = [[item] for item in items]
            t = Table(rows)
            t.setStyle(TableStyle([
                ("LEFTPADDING",   (0, 0), (-1, -1), 0),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
                ("TOPPADDING",    (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]))
            return t

        hero_left = [
            Paragraph('<font color="#e6007a"><b>acordly</b></font>',
                      S("HBrand", fontSize=28, textColor=WHITE, fontName="Helvetica-Bold", leading=34)),
            Spacer(1, 3),
            Paragraph("AI-Powered ACORD Submission Package",
                      S("HTag", fontSize=9, textColor=colors.HexColor("#94a3b8"),
                        fontName="Helvetica", leading=13)),
            Spacer(1, 8),
            Paragraph(f"Submission for: {applicant}",
                      S("HTitle", fontSize=15, textColor=WHITE, fontName="Helvetica-Bold", leading=20)),
            Spacer(1, 4),
            Paragraph(f"Agency: {org_name}  ·  Agent: {agent_name}",
                      S("HSub1", fontSize=8, textColor=colors.HexColor("#cbd5e1"),
                        fontName="Helvetica", leading=12)),
            Spacer(1, 2),
            Paragraph(f"Policy Period: {eff_date} – {exp_date}",
                      S("HSub2", fontSize=8, textColor=colors.HexColor("#cbd5e1"),
                        fontName="Helvetica", leading=12)),
        ]
        hero_right = [
            Spacer(1, 6),
            Paragraph("<b>Overall SQS</b>",
                      S("SqsLbl", fontSize=8, textColor=colors.HexColor("#94a3b8"),
                        fontName="Helvetica-Bold", alignment=TA_RIGHT, leading=11)),
            Paragraph(f'<font color="{sqs_hex}"><b>{avg_sqs}</b></font><font color="#94a3b8">/100</font>',
                      S("SqsNum", fontSize=28, fontName="Helvetica-Bold",
                        alignment=TA_RIGHT, textColor=WHITE, leading=34)),
            Paragraph(f"{len(form_ids)} form(s) · v12.3.1",
                      S("SqsSub", fontSize=7, textColor=colors.HexColor("#94a3b8"),
                        fontName="Helvetica", alignment=TA_RIGHT, leading=11)),
            Spacer(1, 10),
            Paragraph(generated_at,
                      S("SqsDate", fontSize=7, textColor=colors.HexColor("#64748b"),
                        fontName="Helvetica", alignment=TA_RIGHT, leading=10)),
        ]

        hero_inner = Table(
            [[flowables_to_col(hero_left), flowables_to_col(hero_right)]],
            colWidths=[4.1 * inch, 2.9 * inch],
        )
        hero_inner.setStyle(TableStyle([
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING",   (0, 0), (-1, -1), 0),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        hero_wrapper = Table(
            [[hero_inner]],
            colWidths=[7.0 * inch],
            rowHeights=[HERO_H - 0.15 * inch],
        )
        hero_wrapper.setStyle(TableStyle([
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING",   (0, 0), (-1, -1), 16),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 16),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(hero_wrapper)
        story.append(Spacer(1, 0.16 * inch))

        # ── 2. SUBMISSION DETAILS ─────────────────────────────────
        story.append(section_header("Submission Details"))
        story.append(Spacer(1, 0.06 * inch))

        label_s = S("Lbl", fontSize=7,  textColor=SLATE,    fontName="Helvetica-Bold", leading=10)
        val_s   = S("Val", fontSize=8,  textColor=NAVY,     fontName="Helvetica",      leading=11)
        small_s = S("Sm",  fontSize=7,  textColor=TEXT_HINT, fontName="Helvetica",     leading=10)

        info_rows = [
            [Paragraph("AGENT / USER",      label_s), Paragraph(agent_name,   val_s),
             Paragraph("POLICY PERIOD",     label_s), Paragraph(f"{eff_date} – {exp_date}", val_s)],
            [Paragraph("AGENCY",            label_s), Paragraph(org_name,     val_s),
             Paragraph("ENTITY TYPE",       label_s), Paragraph(entity,       val_s)],
            [Paragraph("APPLICANT",         label_s), Paragraph(applicant,    val_s),
             Paragraph("ANNUAL REVENUE",    label_s), Paragraph(revenue,      val_s)],
            [Paragraph("LINES OF BUSINESS", label_s), Paragraph(lobs,         val_s),
             Paragraph("EMPLOYEES",         label_s), Paragraph(employees,    val_s)],
            [Paragraph("FORMS INCLUDED",    label_s), Paragraph(forms_list,   val_s),
             Paragraph("PRIOR CARRIER",     label_s), Paragraph(prior_carr,   val_s)],
            [Paragraph("MAILING ADDRESS",   label_s), Paragraph(addr,         val_s),
             Paragraph("PREPARED BY",       label_s), Paragraph(f"acordly.ai · {generated_at}", small_s)],
        ]
        info_tbl = Table(info_rows, colWidths=[1.2*inch, 2.25*inch, 1.3*inch, 2.25*inch])
        info_tbl.setStyle(TableStyle([
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [LIGHT, WHITE]),
            ("LEFTPADDING",    (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",   (0, 0), (-1, -1), 8),
            ("TOPPADDING",     (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 6),
            ("GRID",           (0, 0), (-1, -1), 0.4, BORDER),
        ]))
        story.append(info_tbl)
        story.append(Spacer(1, 0.18 * inch))

        # ── 3. SQS TABLE ─────────────────────────────────────────
        story.append(section_header("Submission Quality Scores (SQS)"))
        story.append(Spacer(1, 0.06 * inch))

        sqs_header = [
            Paragraph(h, S(f"TH{i}", fontSize=8, textColor=WHITE,
                           fontName="Helvetica-Bold", alignment=TA_CENTER))
            for i, h in enumerate(["Form", "Score", "Grade", "Tier", "Routing Decision"])
        ]
        sqs_rows = [sqs_header]

        for fid, sqs in sqs_results.items():
            score   = sqs.get("sqs_score", 0)
            sc      = sqs_color(score)
            bg      = sqs_bg(score)
            routing = routing_labels.get(sqs.get("routing_decision", ""), sqs.get("routing_decision", "—"))

            score_pill = Table(
                [[Paragraph(f"<b>{score}/100</b>",
                            S(f"Pill{fid}", fontSize=9, fontName="Helvetica-Bold",
                              textColor=sc, alignment=TA_CENTER))]],
                colWidths=[0.65 * inch],
            )
            score_pill.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), bg),
                ("TOPPADDING",    (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING",   (0, 0), (-1, -1), 2),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 2),
            ]))
            sqs_rows.append([
                Paragraph(fid.replace("_", " "),
                          S(f"FC{fid}", fontSize=8, fontName="Helvetica")),
                score_pill,
                Paragraph(f"<b>{sqs.get('grade', '—')}</b>",
                          S(f"GC{fid}", fontSize=9, fontName="Helvetica-Bold",
                            textColor=sc, alignment=TA_CENTER)),
                Paragraph(sqs.get("tier", "—"),
                          S(f"TC{fid}", fontSize=7, fontName="Helvetica")),
                Paragraph(routing,
                          S(f"RC{fid}", fontSize=8, fontName="Helvetica")),
            ])

        sqs_tbl = Table(sqs_rows, colWidths=[1.6*inch, 0.8*inch, 0.65*inch, 1.35*inch, 2.6*inch])
        sqs_tbl.setStyle(TableStyle([
            ("BACKGROUND",     (0, 0), (-1,  0), NAVY),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHTER]),
            ("LEFTPADDING",    (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",   (0, 0), (-1, -1), 8),
            ("TOPPADDING",     (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 6),
            ("LINEBELOW",      (0, 0), (-1, -1), 0.5, BORDER),
            ("ALIGN",          (1, 0), (2,  -1), "CENTER"),
        ]))
        story.append(sqs_tbl)
        story.append(Spacer(1, 0.18 * inch))

        # ── 4. SQS REASONING ─────────────────────────────────────
        if sqs_reasoning and sqs_reasoning.strip():
            reasoning_s = S("Rsn", fontSize=9, textColor=TEXT_MAIN,
                             fontName="Helvetica-Oblique", leading=14, spaceAfter=3)
            story.append(KeepTogether([
                section_header("SQS Score Explanation"),
                Spacer(1, 0.06 * inch),
                Paragraph(sqs_reasoning.strip(), reasoning_s),
                Spacer(1, 0.18 * inch),
            ]))

        # ── 5. NARRATIVE ─────────────────────────────────────────
        body_style = S("Body", fontSize=9, textColor=TEXT_MAIN, fontName="Helvetica",
                        leading=14, spaceAfter=3, alignment=TA_JUSTIFY)
        story.append(section_header("Package Summary"))
        story.append(Spacer(1, 0.06 * inch))
        for para_text in narrative.split("\n"):
            para_text = para_text.strip()
            if para_text:
                story.append(Paragraph(para_text, body_style))
                story.append(Spacer(1, 0.04 * inch))
        story.append(Spacer(1, 0.14 * inch))

        # ── 6. A2A DISCLAIMER ────────────────────────────────────
        disclaimer_s = S("Disc", fontSize=7, textColor=TEXT_MUTE,
                          fontName="Helvetica-BoldOblique", leading=10)
        disclaimer_text = (
            "IMPORTANT — Hidden within this page is carrier-grade AI-to-AI (A2A) data that is "
            "invisible to human readers but interpretable by next-generation carrier AI ingestion "
            "engines. Please include this page in your underwriting submission package for a faster "
            "and more robust submission experience."
        )
        disclaimer_tbl = Table(
            [[Paragraph("🤖", S("DIcon", fontSize=13, fontName="Helvetica")),
              Paragraph(disclaimer_text, disclaimer_s)]],
            colWidths=[0.3 * inch, 6.7 * inch],
        )
        disclaimer_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), PINK_PALE),
            ("LEFTPADDING",   (0, 0), (-1, -1), 10),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("LINEABOVE",     (0, 0), (-1,  0), 1.5, PINK),
            ("LINEBELOW",     (0, 0), (-1, -1), 1.5, PINK),
        ]))
        story.append(disclaimer_tbl)
        story.append(Spacer(1, 0.10 * inch))

        # ── 7. HIDDEN A2A JSON ────────────────────────────────────
        mono_style   = S("Mono", fontSize=0.001, textColor=HIDDEN_FG,
                          fontName="Courier", leading=0.001, backColor=HIDDEN_BG)
        ai_json_str  = json.dumps(ai_block, indent=2, default=str)
        wrapped_lines = []
        for line in ai_json_str.split("\n"):
            wrapped_lines.extend(
                textwrap.wrap(line, width=110, subsequent_indent="    ")
                if len(line) > 110 else [line]
            )
        hidden_tbl = Table(
            [[Paragraph(
                "\n".join(wrapped_lines).replace("\n", "<br/>").replace(" ", "&nbsp;"),
                mono_style,
            )]],
            colWidths=[7 * inch],
        )
        hidden_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), HIDDEN_BG),
            ("LEFTPADDING",   (0, 0), (-1, -1), 4),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
            ("TOPPADDING",    (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(hidden_tbl)
        story.append(Spacer(1, 0.06 * inch))

        # ── 8. FOOTER ────────────────────────────────────────────
        footer_tbl = Table(
            [[
                Paragraph(
                    'Generated by <font color="#e6007a"><b>acordly.ai</b></font> · AI-powered ACORD form automation',
                    S("Ft", fontSize=7, textColor=TEXT_HINT, fontName="Helvetica"),
                ),
                Paragraph(
                    f"Confidential · {generated_at}",
                    S("FtR", fontSize=7, textColor=TEXT_HINT, fontName="Helvetica", alignment=TA_RIGHT),
                ),
            ]],
            colWidths=[3.5 * inch, 3.5 * inch],
        )
        footer_tbl.setStyle(TableStyle([
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("LINEABOVE",  (0, 0), (-1, -1), 0.5, BORDER_MID),
        ]))
        story.append(footer_tbl)

        # ── Build ─────────────────────────────────────────────────
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=letter,
            leftMargin=0.65 * inch, rightMargin=0.65 * inch,
            topMargin=0,
            bottomMargin=0.55 * inch,
        )
        doc.build(story, onFirstPage=on_first_page, onLaterPages=on_later_pages)
        buf.seek(0)
        logger.info(f"Cover page PDF generated ({buf.getbuffer().nbytes} bytes)")
        return buf.getvalue()

    except ImportError:
        logger.warning("reportlab not installed — generating plain-text cover page")
        return _build_cover_page_fallback(
            facts, sqs_results, form_ids, org_name, narrative, ai_block, generated_at
        )
    except Exception as ex:
        logger.error(f"Cover page build error: {ex}")
        return _build_cover_page_fallback(
            facts, sqs_results, form_ids, org_name, narrative, ai_block, generated_at
        )