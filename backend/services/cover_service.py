#cover_service.py

import hashlib
import io
import json
import logging
import textwrap
from datetime import datetime, timezone
from typing import List

from config.settings import groq_chat, LLM_MODEL
from services.extraction_service import _fv, _cache_get, _cache_set

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
        {"form": fid, "score": sqs.get("sqs_score"), "grade": sqs.get("grade"),
         "tier": sqs.get("tier"), "routing": sqs.get("routing_decision"),
         "breakdown": sqs.get("breakdown", {}), "issues": sqs.get("issues", []),
         "recommendations": sqs.get("recommendations", [])}
        for fid, sqs in sqs_results.items()
    ]
    avg_sqs = int(sum(s.get("sqs_score", 0) for s in sqs_results.values()) / max(len(sqs_results), 1)) if sqs_results else 0
    applicant = _fv(facts, 'applicant_name') or 'Unknown'
    _cover_cache_key = "cover_ai:" + hashlib.md5(
        f"{applicant}|{','.join(sorted(form_ids))}|{avg_sqs}|{org_name}".encode()
    ).hexdigest()
    _cached_cover = _cache_get(_cover_cache_key)
    if _cached_cover:
        return _cached_cover
    prompt  = f"""You are an expert commercial insurance underwriting analyst.
Generate a professional cover page summary for this ACORD submission package.

SUBMISSION DATA:
Agent/User: {user.get('full_name', '') if user else ''}
Agency/Org: {org_name}
Applicant: {_fv(facts, 'applicant_name') or 'Unknown'}
Lines of Business: {facts.get('lines_of_business', [])}
Effective Date: {_fv(facts, 'effective_date') or 'Not specified'}
Operations: {_fv(facts, 'operations_description') or 'Not provided'}
Revenue: {_fv(facts, 'total_revenue') or 'Not provided'}
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
  acordly_version: "12.4.0", a2a_schema_version: "1.0"

Return ONLY the JSON object."""
    try:
        raw = groq_chat(LLM_MODEL, [{"role": "user", "content": prompt}])
        if raw.startswith("```"):
            raw = raw.replace("```json", "").replace("```", "").strip()
        s, e = raw.find("{"), raw.rfind("}")
        if s != -1 and e != -1:
            result = json.loads(raw[s : e + 1])
            result = {
                "narrative":     result.get("narrative", ""),
                "sqs_reasoning": result.get("sqs_reasoning", ""),
                "ai_block":      result.get("ai_block", {}),
            }
            _cache_set(_cover_cache_key, result)
            return result
    except Exception as ex:
        logger.error(f"Cover page AI generation failed: {ex}")

    applicant = _fv(facts, 'applicant_name') or 'Unknown'
    lobs      = ", ".join(facts.get("lines_of_business", [])) if facts.get("lines_of_business") else "commercial insurance"
    return {
        "narrative": (
            f"This ACORD submission package was prepared by {org_name} on behalf of {applicant}. "
            f"The package covers {lobs} with a proposed effective date of {_fv(facts, 'effective_date') or 'TBD'}. "
            f"All forms have been populated using AI-extracted data from the uploaded source documents. "
            f"The submission has been reviewed for completeness and quality using the Submission Quality Score (SQS) system."
        ),
        "sqs_reasoning": (
            f"The overall average SQS of {avg_sqs}/100 reflects the completeness and quality of the extracted data "
            f"across {len(form_ids)} generated form(s). Scores below 75 indicate fields requiring manual review."
        ),
        "ai_block": {
            "agent_name": (user.get("full_name", "") if user else ""),
            "org_name": org_name,
            "applicant_name": applicant,
            "forms_included": form_ids,
            "overall_avg_sqs": avg_sqs,
            "acordly_version": "12.4.0",
            "a2a_schema_version": "1.0",
        },
    }


def generate_lite_cover_narrative(
    facts: dict,
    flags: dict,
    sqs: dict,
    hard_stops: list,
    soft_stops: list,
    org_name: str,
    user: dict = None,
) -> dict:
    score   = sqs.get("sqs_score", 0)
    grade   = sqs.get("grade", "—")
    routing = sqs.get("routing_decision", "—")
    _lite_applicant = _fv(facts, 'applicant_name') or 'Unknown'
    _lite_cache_key = "cover_lite:" + hashlib.md5(
        f"{_lite_applicant}|{score}|{org_name}|{','.join(sorted(str(x) for x in hard_stops))}".encode()
    ).hexdigest()
    _cached_lite = _cache_get(_lite_cache_key)
    if _cached_lite:
        return _cached_lite
    prompt  = f"""You are an expert commercial insurance underwriting analyst.
Generate a professional pre-submission SQS summary for a producer who has uploaded their package for analysis.
This is NOT a full ACORD package — no forms have been generated. The purpose is to flag issues before the producer
proceeds with their platform of choice.

SUBMISSION DATA:
Agent/User: {user.get('full_name', '') if user else ''}
Agency/Org: {org_name}
Applicant: {_fv(facts, 'applicant_name') or 'Unknown'}
Lines of Business: {facts.get('lines_of_business', [])}
Effective Date: {_fv(facts, 'effective_date') or 'Not specified'}
Operations: {_fv(facts, 'operations_description') or 'Not provided'}
Revenue: {_fv(facts, 'total_revenue') or 'Not provided'}
SQS Score: {score}/100 (Grade: {grade}, Routing: {routing})
Hard Stops (critical blockers): {hard_stops}
Soft Stops (warnings): {soft_stops}
Risk Flags: {flags}

Respond with ONLY a valid JSON object with exactly three keys:
"narrative": 2-3 paragraphs focused on what the producer should watch out for, what information is missing,
  and how to strengthen this submission before proceeding. Plain text, no markdown.
"sqs_reasoning": One paragraph explaining the SQS score in context of the hard/soft stops found.
"ai_block": A machine-readable structured JSON object with: submission_id, generated_at,
  agent_name, applicant_name, org_name, lines_of_business, effective_date,
  total_revenue, entity_type, sqs_score, sqs_grade, sqs_routing, hard_stops, soft_stops, risk_flags,
  acordly_version: "12.4.0", a2a_schema_version: "1.0", report_type: "lite_pre_submission"

Return ONLY the JSON object."""
    try:
        raw = groq_chat(LLM_MODEL, [{"role": "user", "content": prompt}])
        if raw.startswith("```"):
            raw = raw.replace("```json", "").replace("```", "").strip()
        s, e = raw.find("{"), raw.rfind("}")
        if s != -1 and e != -1:
            result = json.loads(raw[s : e + 1])
            result = {
                "narrative":     result.get("narrative", ""),
                "sqs_reasoning": result.get("sqs_reasoning", ""),
                "ai_block":      result.get("ai_block", {}),
            }
            _cache_set(_lite_cache_key, result)
            return result
    except Exception as ex:
        logger.error(f"Lite cover narrative generation failed: {ex}")

    applicant = _fv(facts, 'applicant_name') or 'Unknown'
    lobs      = ", ".join(facts.get("lines_of_business", [])) if facts.get("lines_of_business") else "commercial insurance"
    return {
        "narrative": (
            f"This pre-submission SQS analysis was prepared by {org_name} for {applicant} covering {lobs}. "
            f"The submission received an SQS score of {score}/100 (Grade {grade}). "
            f"{'The following critical issues must be resolved before submission: ' + '; '.join(hard_stops) + '. ' if hard_stops else ''}"
            f"{'The following warnings may impact the submission quality: ' + '; '.join(soft_stops) + '.' if soft_stops else ''}"
        ),
        "sqs_reasoning": (
            f"The SQS score of {score}/100 reflects the quality of the submission based on the uploaded documents. "
            f"{'Hard stops were identified that will block this submission. ' if hard_stops else ''}"
            f"Scores below 75 indicate fields or conditions requiring attention before proceeding."
        ),
        "ai_block": {
            "agent_name": (user.get("full_name", "") if user else ""),
            "org_name": org_name,
            "applicant_name": applicant,
            "sqs_score": score,
            "sqs_grade": grade,
            "hard_stops": hard_stops,
            "soft_stops": soft_stops,
            "report_type": "lite_pre_submission",
            "acordly_version": "12.4.0",
            "a2a_schema_version": "1.0",
        },
    }


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
    hard_stops: list = None,
    soft_stops: list = None,
) -> bytes:
    generated_at = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")

    if not narrative or not narrative.strip():
        narrative = (
            f"This ACORD submission package was prepared by {org_name} for applicant "
            f"{_fv(facts, 'applicant_name') or 'Unknown'}. All forms have been populated using "
            f"AI-extracted data from the uploaded source documents."
        )

    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib import colors
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        )
        from reportlab.lib.enums import TA_RIGHT, TA_JUSTIFY, TA_CENTER, TA_LEFT

        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=letter,
            leftMargin=0.65*inch, rightMargin=0.65*inch,
            topMargin=0.65*inch, bottomMargin=0.65*inch,
        )

        NAVY       = colors.HexColor("#0f172a")
        PINK       = colors.HexColor("#e6007a")
        PINK_LIGHT = colors.HexColor("#fdf2f8")
        LIGHT      = colors.HexColor("#f8fafc")
        LIGHTER    = colors.HexColor("#f1f5f9")
        WHITE      = colors.white
        GREEN      = colors.HexColor("#10b981")
        YELLOW     = colors.HexColor("#f59e0b")
        RED        = colors.HexColor("#ef4444")
        BORDER     = colors.HexColor("#e2e8f0")
        TEXT_MAIN  = colors.HexColor("#1e293b")
        TEXT_MUTE  = colors.HexColor("#64748b")
        TEXT_HINT  = colors.HexColor("#94a3b8")
        SLATE      = colors.HexColor("#64748b")
        LOGO_BG    = colors.HexColor("#0f172a")

        def sqs_color(score):
            if score is None:
                return SLATE
            if score >= 90:
                return GREEN
            if score >= 75:
                return YELLOW
            return RED

        styles = getSampleStyleSheet()

        def S(name, **kw):
            return ParagraphStyle(name, parent=styles["Normal"], **kw)

        h1_style     = S("H1",   fontSize=14, textColor=NAVY,      fontName="Helvetica-Bold", leading=20, spaceAfter=4)
        h2_style     = S("H2",   fontSize=11, textColor=NAVY,      fontName="Helvetica-Bold", leading=16, spaceAfter=3)
        body_style   = S("Body", fontSize=9,  textColor=TEXT_MAIN,  fontName="Helvetica",      leading=14, spaceAfter=3, alignment=TA_JUSTIFY)
        label_s      = S("Lbl",  fontSize=8,  textColor=SLATE,     fontName="Helvetica-Bold")
        val_s        = S("Val",  fontSize=8,  textColor=NAVY,      fontName="Helvetica")
        small_s      = S("Sm",   fontSize=7,  textColor=TEXT_HINT,  fontName="Helvetica",      leading=10)
        reasoning_s  = S("Rsn",  fontSize=9,  textColor=TEXT_MAIN,  fontName="Helvetica-Oblique", leading=14, spaceAfter=3)
        disclaimer_s = S("Disc", fontSize=7,  textColor=TEXT_MUTE,  fontName="Helvetica-BoldOblique", leading=10)
        hidden_style = S("Hid",  fontSize=0.001, textColor=colors.white, fontName="Courier", leading=0.001, backColor=colors.white)
        logo_style   = S("Logo", fontSize=26, textColor=PINK, fontName="Helvetica-Bold", leading=32)
        powered_style = S("Pwr", fontSize=9,  textColor=PINK, fontName="Helvetica-Bold", alignment=TA_RIGHT)
        powered_date_style = S("PwrDt", fontSize=7, textColor=TEXT_HINT, fontName="Helvetica", alignment=TA_RIGHT)

        story = []

        # ── HEADER ──────────────────────────────────────────────────────────
        # Left: agency logo placeholder + agency name
        # Right: "Powered by acordly.ai" (small, pink) + date
       # Acordly logo (matches homepage: lowercase "acordly" in pink, bold, large)
        acordly_logo = Paragraph(
            '<font color="#e6007a"><b>acordly</b></font>',
            S("AcordlyLogo", fontSize=28, fontName="Helvetica-Bold", leading=34),
        )

        powered_cell = Paragraph(
            f'<font color="#e6007a"><b>Powered by acordly.ai</b></font><br/>'
            f'<font color="#94a3b8" size="7">{generated_at}</font>',
            S("Pwr2", fontSize=9, fontName="Helvetica", alignment=TA_RIGHT),
        )

        header_tbl = Table([[acordly_logo, powered_cell]], colWidths=[3.5*inch, 3.5*inch])
        header_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), NAVY),
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
            ("LEFTPADDING",   (0,0), (-1,-1), 14),
            ("RIGHTPADDING",  (0,0), (-1,-1), 14),
            ("TOPPADDING",    (0,0), (-1,-1), 16),
            ("BOTTOMPADDING", (0,0), (-1,-1), 16),
        ]))
        story.append(header_tbl)
        story.append(Spacer(1, 0.14*inch))

        # ── SUBMISSION INFO TABLE ────────────────────────────────────────────
        agent_name = (user.get("full_name", "") if user else "") or "—"
        eff_date   = _fv(facts, "effective_date") or "—"
        exp_date   = _fv(facts, "expiration_date") or "—"
        lobs_raw   = facts.get("lines_of_business", [])
        lobs       = ", ".join(lobs_raw) if lobs_raw else "—"
        forms_list = ", ".join(form_ids) if form_ids else "Pre-Submission SQS Analysis (Lite)"

        def _v(key, default="—"):
            v = _fv(facts, key)
            return str(v) if v else default

        info_rows = [
            [Paragraph("AGENT / USER",      label_s), Paragraph(agent_name,              val_s),
             Paragraph("POLICY PERIOD",     label_s), Paragraph(f"{eff_date} - {exp_date}", val_s)],
            [Paragraph("AGENCY",            label_s), Paragraph(org_name or "—",          val_s),
             Paragraph("ENTITY TYPE",       label_s), Paragraph(_v("entity_type"),        val_s)],
            [Paragraph("APPLICANT",         label_s), Paragraph(_v("applicant_name"),     val_s),
             Paragraph("ANNUAL REVENUE",    label_s), Paragraph(_v("total_revenue"),      val_s)],
            [Paragraph("LINES OF BUSINESS", label_s), Paragraph(lobs,                     val_s),
             Paragraph("EMPLOYEES",         label_s), Paragraph(_v("num_employees"),      val_s)],
            [Paragraph("FORMS INCLUDED",    label_s), Paragraph(forms_list,               val_s),
             Paragraph("PRIOR CARRIER",     label_s), Paragraph(_v("prior_carrier"),      val_s)],
            [Paragraph("MAILING ADDRESS",   label_s), Paragraph(_v("mailing_address"),    val_s),
             Paragraph("PREPARED BY",       label_s), Paragraph(f"acordly.ai · {generated_at}", small_s)],
        ]
        info_tbl = Table(info_rows, colWidths=[1.2*inch, 2.25*inch, 1.3*inch, 2.25*inch])
        info_tbl.setStyle(TableStyle([
            ("ROWBACKGROUNDS", (0,0), (-1,-1), [LIGHT, WHITE]),
            ("LEFTPADDING",    (0,0), (-1,-1), 8),
            ("RIGHTPADDING",   (0,0), (-1,-1), 8),
            ("TOPPADDING",     (0,0), (-1,-1), 5),
            ("BOTTOMPADDING",  (0,0), (-1,-1), 5),
            ("GRID",           (0,0), (-1,-1), 0.25, BORDER),
        ]))
        story.append(info_tbl)
        story.append(Spacer(1, 0.14*inch))

        # ── SQS TABLE ────────────────────────────────────────────────────────
        story.append(Paragraph("Submission Quality Scores (SQS)", h2_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
        story.append(Spacer(1, 0.06*inch))

        # No emoji — plain text routing labels only
        routing_labels = {
            "auto_quote":  "Auto-Quote",
            "review":      "Light Review",
            "full_review": "Full Review",
            "hold":        "Hold",
        }
        sqs_header = [
            Paragraph(f"<b>{h}</b>", S("TH", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold"))
            for h in ["Form", "Score", "Grade", "Tier", "Routing"]
        ]
        sqs_rows = [sqs_header]

        if sqs_results:
            for fid, sqs in sqs_results.items():
                score   = sqs.get("sqs_score", 0) if sqs else 0
                sc      = sqs_color(score)
                routing = routing_labels.get(
                    sqs.get("routing_decision", "") if sqs else "",
                    sqs.get("routing_decision", "—") if sqs else "—",
                )
                grade   = sqs.get("grade", "—") if sqs else "—"
                tier    = sqs.get("tier", "—") if sqs else "—"
                sqs_rows.append([
                    Paragraph(fid.replace("_", " "),  S("Cell", fontSize=8,  fontName="Helvetica")),
                    Paragraph(f"<b>{score}/100</b>",   S("Cell", fontSize=9,  fontName="Helvetica-Bold", textColor=sc)),
                    Paragraph(grade,                    S("Cell", fontSize=8,  fontName="Helvetica-Bold", textColor=sc)),
                    Paragraph(tier,                     S("Cell", fontSize=7,  fontName="Helvetica")),
                    Paragraph(routing,                  S("Cell", fontSize=7,  fontName="Helvetica")),
                ])
        else:
            sqs_rows.append([
                Paragraph("No SQS data", S("Cell", fontSize=8, fontName="Helvetica")),
                Paragraph("—", S("Cell", fontSize=8, fontName="Helvetica")),
                Paragraph("—", S("Cell", fontSize=8, fontName="Helvetica")),
                Paragraph("—", S("Cell", fontSize=8, fontName="Helvetica")),
                Paragraph("—", S("Cell", fontSize=8, fontName="Helvetica")),
            ])

        sqs_tbl = Table(sqs_rows, colWidths=[1.6*inch, 0.75*inch, 0.65*inch, 1.4*inch, 2.6*inch])
        sqs_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,0),  NAVY),
            ("ROWBACKGROUNDS",(0,1), (-1,-1), [WHITE, LIGHTER]),
            ("LEFTPADDING",   (0,0), (-1,-1), 7),
            ("RIGHTPADDING",  (0,0), (-1,-1), 7),
            ("TOPPADDING",    (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
            ("GRID",          (0,0), (-1,-1), 0.25, BORDER),
        ]))
        story.append(sqs_tbl)
        story.append(Spacer(1, 0.10*inch))

        # ── RED FLAGS (Lite only — when hard/soft stops are provided) ─────────
        if hard_stops or soft_stops:
            story.append(Paragraph("Red Flags & Warnings", h2_style))
            story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
            story.append(Spacer(1, 0.06*inch))
            if hard_stops:
                flag_rows = [[
                    Paragraph("<b>CRITICAL — Hard Stops</b>",
                              S("FlagHdr", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")),
                ]]
                for stop in hard_stops:
                    flag_rows.append([Paragraph(f"• {stop}", S("FlagRow", fontSize=8, textColor=colors.HexColor("#7f1d1d"), fontName="Helvetica"))])
                flag_tbl = Table(flag_rows, colWidths=[7.0*inch])
                flag_tbl.setStyle(TableStyle([
                    ("BACKGROUND",    (0,0), (-1,0),  colors.HexColor("#ef4444")),
                    ("ROWBACKGROUNDS",(0,1), (-1,-1), [colors.HexColor("#fef2f2"), WHITE]),
                    ("LEFTPADDING",   (0,0), (-1,-1), 8),
                    ("RIGHTPADDING",  (0,0), (-1,-1), 8),
                    ("TOPPADDING",    (0,0), (-1,-1), 5),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 5),
                    ("GRID",          (0,0), (-1,-1), 0.25, BORDER),
                ]))
                story.append(flag_tbl)
                story.append(Spacer(1, 0.07*inch))
            if soft_stops:
                warn_rows = [[
                    Paragraph("<b>WARNINGS — Soft Stops</b>",
                              S("WarnHdr", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")),
                ]]
                for stop in soft_stops:
                    warn_rows.append([Paragraph(f"• {stop}", S("WarnRow", fontSize=8, textColor=colors.HexColor("#78350f"), fontName="Helvetica"))])
                warn_tbl = Table(warn_rows, colWidths=[7.0*inch])
                warn_tbl.setStyle(TableStyle([
                    ("BACKGROUND",    (0,0), (-1,0),  colors.HexColor("#f59e0b")),
                    ("ROWBACKGROUNDS",(0,1), (-1,-1), [colors.HexColor("#fffbeb"), WHITE]),
                    ("LEFTPADDING",   (0,0), (-1,-1), 8),
                    ("RIGHTPADDING",  (0,0), (-1,-1), 8),
                    ("TOPPADDING",    (0,0), (-1,-1), 5),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 5),
                    ("GRID",          (0,0), (-1,-1), 0.25, BORDER),
                ]))
                story.append(warn_tbl)
                story.append(Spacer(1, 0.10*inch))

        # ── SQS REASONING ────────────────────────────────────────────────────
        if sqs_reasoning and sqs_reasoning.strip():
            story.append(Paragraph("SQS Score Explanation", h2_style))
            story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
            story.append(Spacer(1, 0.05*inch))
            story.append(Paragraph(sqs_reasoning.strip(), reasoning_s))
            story.append(Spacer(1, 0.10*inch))

        # ── NARRATIVE ────────────────────────────────────────────────────────
        story.append(Paragraph("Package Summary", h2_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
        story.append(Spacer(1, 0.05*inch))
        for para_text in narrative.split("\n"):
            para_text = para_text.strip()
            if para_text:
                story.append(Paragraph(para_text, body_style))
                story.append(Spacer(1, 0.04*inch))
        story.append(Spacer(1, 0.10*inch))

        # ── A2A DISCLAIMER ───────────────────────────────────────────────────
        # Plain text only — no emoji, safe for all ReportLab font encodings
        disclaimer_text = (
            "IMPORTANT - Hidden within this page is carrier-grade AI-to-AI (A2A) data "
            "that is invisible to human readers but interpretable by next-generation carrier "
            "AI ingestion engines. Please include this page in your underwriting submission "
            "package for a faster and more robust submission experience."
        )
        disclaimer_label = Paragraph(
            "<b>[A2A]</b>",
            S("DLbl", fontSize=8, textColor=PINK, fontName="Helvetica-Bold"),
        )
        disclaimer_body = Paragraph(disclaimer_text, disclaimer_s)

        disclaimer_data = [[disclaimer_label, disclaimer_body]]
        disclaimer_tbl = Table(disclaimer_data, colWidths=[0.45*inch, 6.55*inch])
        disclaimer_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), PINK_LIGHT),
            ("LEFTPADDING",   (0,0), (-1,-1), 8),
            ("RIGHTPADDING",  (0,0), (-1,-1), 8),
            ("TOPPADDING",    (0,0), (-1,-1), 7),
            ("BOTTOMPADDING", (0,0), (-1,-1), 7),
            ("VALIGN",        (0,0), (-1,-1), "TOP"),
            ("LINEABOVE",     (0,0), (-1,-1), 1, PINK),
            ("LINEBELOW",     (0,0), (-1,-1), 1, PINK),
        ]))
        story.append(disclaimer_tbl)
        story.append(Spacer(1, 0.10*inch))

        # ── HIDDEN A2A JSON BLOCK ─────────────────────────────────────────────
        if ai_block:
            ai_json_str   = json.dumps(ai_block, indent=2, default=str)
            wrapped_lines = []
            for line in ai_json_str.split("\n"):
                wrapped_lines.extend(
                    textwrap.wrap(line, width=110, subsequent_indent="    ")
                    if len(line) > 110 else [line]
                )
            hidden_text = (
                "\n".join(wrapped_lines)
                .replace("\n", "<br/>")
                .replace(" ", "&nbsp;")
            )
            story.append(Paragraph(hidden_text, hidden_style))
            story.append(Spacer(1, 0.06*inch))

        # ── FOOTER ───────────────────────────────────────────────────────────
        footer_data = [[
            Paragraph(
                'Generated by <font color="#e6007a"><b>acordly.ai</b></font> - AI-powered ACORD form automation',
                S("Ft", fontSize=7, textColor=TEXT_HINT, fontName="Helvetica"),
            ),
            Paragraph(
                f"Confidential - {generated_at}",
                S("FtR", fontSize=7, textColor=TEXT_HINT, fontName="Helvetica", alignment=TA_RIGHT),
            ),
        ]]
        footer_tbl = Table(footer_data, colWidths=[3.5*inch, 3.5*inch])
        footer_tbl.setStyle(TableStyle([
            ("TOPPADDING",  (0,0), (-1,-1), 6),
            ("LINEABOVE",   (0,0), (-1,-1), 0.5, BORDER),
        ]))
        story.append(footer_tbl)

        doc.build(story)
        buf.seek(0)
        result = buf.getvalue()
        if not result or len(result) < 100:
            raise ValueError("build produced empty PDF")
        return result

    except ImportError as ie:
        logger.error(f"ReportLab not installed: {ie}")
        return _build_cover_page_fallback(facts, sqs_results, form_ids, org_name, narrative, ai_block, generated_at)
    except Exception as ex:
        logger.error(f"Cover page build error: {ex}", exc_info=True)
        return _build_cover_page_fallback(facts, sqs_results, form_ids, org_name, narrative, ai_block, generated_at)


def _build_cover_page_fallback(facts, sqs_results, form_ids, org_name, narrative, ai_block, generated_at) -> bytes:
    """Plain-text PDF fallback when ReportLab fails."""
    try:
        lines = [
            "ACORDLY SUBMISSION PACKAGE COVER PAGE",
            f"Generated: {generated_at}",
            f"Prepared by: {org_name}",
            f"Applicant: {_fv(facts, 'applicant_name') or 'Unknown'}",
            f"Agency: {org_name}",
            f"Effective Date: {_fv(facts, 'effective_date') or '---'}",
            f"Lines of Business: {', '.join(facts.get('lines_of_business', [])) or '---'}",
            f"Forms: {', '.join(form_ids)}",
            "",
            "SQS SCORES:",
        ]
        for fid, sqs in (sqs_results or {}).items():
            score = sqs.get("sqs_score", 0) if sqs else 0
            grade = sqs.get("grade", "?") if sqs else "?"
            lines.append(f"  {fid}: {score}/100 ({grade})")
        lines += ["", "SUMMARY:", (narrative or "No narrative available.")[:800]]

        page_content = "BT /F1 10 Tf 40 750 Td 14 TL\n"
        for line in lines[:60]:
            safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            page_content += f"({safe}) Tj T*\n"
        page_content += "ET"

        page_content_bytes = page_content.encode("latin-1", errors="replace")
        content_len = len(page_content_bytes)

        pdf = (
            b"%PDF-1.4\n"
            b"1 0 obj\n<</Type /Catalog /Pages 2 0 R>>\nendobj\n"
            b"2 0 obj\n<</Type /Pages /Kids [3 0 R] /Count 1>>\nendobj\n"
            b"3 0 obj\n<</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources <</Font <</F1 5 0 R>>>>>>\nendobj\n"
            + f"4 0 obj\n<</Length {content_len}>>\nstream\n".encode()
            + page_content_bytes
            + b"\nendstream\nendobj\n"
            b"5 0 obj\n<</Type /Font /Subtype /Type1 /BaseFont /Helvetica>>\nendobj\n"
            b"xref\n0 6\n0000000000 65535 f \n"
            b"trailer\n<</Size 6 /Root 1 0 R>>\n"
            b"%%EOF"
        )
        return pdf
    except Exception as ex:
        logger.error(f"Fallback cover page error: {ex}")
        return (
            b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
            b"xref\n0 4\ntrailer<</Size 4/Root 1 0 R>>\n%%EOF"
        )