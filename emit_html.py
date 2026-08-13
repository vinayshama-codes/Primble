# -*- coding: utf-8 -*-
"""Emit the web version of the deck from the SAME DECK data build_deck.py uses,
so the .pptx and the artifact can never drift apart.

    py emit_html.py <template.html> <out.html>
"""
import html
import io
import re
import sys

sys.path.insert(0, ".")
from build_deck import DECK  # noqa: E402

ACTS = [
    ("I",   "The Opportunity",           {1, 2, 3}),
    ("II",  "Understanding the Submission", {4, 5, 6}),
    ("III", "Submission Review",         {7, 8}),
    ("IV",  "Generating the Forms",      {9, 10, 11, 12, 13, 14}),
    ("V",   "Scoring",                   {15, 16, 17}),
    ("VI",  "Closing the Gaps",          {18, 19, 20}),
    ("VII", "Delivery",                  {21, 22}),
    ("VIII","Trust, Platform & Business",{23, 24, 25, 26}),
    ("IX",  "The Case",                  {27, 28}),
]

TITLES = [
    "Cover", "The problem", "The workflow", "Take the whole package",
    "Reading hard pages", "Two businesses, one upload", "Review: what we found",
    "Review: blockers and warnings", "Form selection by tier", "How a form gets filled",
    "No proof, no answer", "Field-level confidence", "Schedules as tables",
    "Coverage intelligence", "SQS: the score", "SQS: pillars and caps",
    "The rule library", "Client questionnaire", "Producer tracking",
    "Resume any submission", "Download options", "Fits the agency stack",
    "The audit record", "Security", "Unit economics", "Pricing",
    "Why it is hard to copy", "Where we are, what we need",
]


def md(text):
    """**bold** -> <b>, then escape everything else."""
    parts = re.split(r"(\*\*[^*]+\*\*)", text)
    out = []
    for p in parts:
        if p.startswith("**") and p.endswith("**"):
            out.append("<b>" + html.escape(p[2:-2]) + "</b>")
        else:
            out.append(html.escape(p))
    return "".join(out)


def fld(b):
    lbl = html.escape(b[0])
    if len(b) == 3:
        return (f'<div class="fld num"><span class="lbl">{lbl}</span>'
                f'<span class="val">{html.escape(b[1])}'
                f'<small>{html.escape(b[2])}</small></span></div>')
    return (f'<div class="fld"><span class="lbl">{lbl}</span>'
            f'<span class="val">{md(b[1])}</span></div>')


def emit():
    total = len(DECK)
    out = []

    # ── table of contents ────────────────────────────────────────────────────
    toc = []
    for i, t in enumerate(TITLES, 1):
        toc.append(f'<li><a href="#s{i}"><span class="n">{i:02d}</span>'
                   f'<span>{html.escape(t)}</span></a></li>')
    out.append('<nav class="toc"><h3>Contents</h3><ol>' + "".join(toc) + "</ol></nav>")

    # ── slides ───────────────────────────────────────────────────────────────
    for idx, s in enumerate(DECK, 1):
        for rn, rt, members in ACTS:
            if idx == min(members) and idx != 1:
                out.append(f'<div class="divider"><span class="rn">{rn}</span>'
                           f'<span class="rt">{html.escape(rt)}</span>'
                           f'<span class="rl"></span></div>')
        head = (f'<div class="sh"><span><span class="no">{idx:02d}</span> '
                f'&nbsp;/&nbsp; {total}</span>'
                f'<span class="act">{html.escape(s["act"])}</span></div>')

        if s.get("kind") == "cover":
            out.append(
                f'<section class="slide cover" id="s{idx}">{head}'
                f'<div class="body"><h1>{md(s["h"])}</h1>'
                f'<p class="sub">{md(s["sub"])}</p></div>'
                f'<div class="fields four">{"".join(fld(b) for b in s["boxes"])}</div>'
                f'</section>')
            continue

        body = [f'<h2>{md(s["h"])}</h2>', f'<p class="thesis">{md(s["t"])}</p>']

        if s.get("flow"):
            n = len(s["flow"])
            steps = "".join(
                f'<div class="step"><div class="n">{html.escape(a)}</div>'
                f'<div class="t">{html.escape(b)}</div>'
                f'<div class="d">{html.escape(c)}</div></div>'
                for a, b, c in s["flow"])
            body.append(f'<div class="flow" style="grid-template-columns:repeat({n},1fr)">'
                        f'{steps}</div>')
        if s.get("boxes"):
            n = len(s["boxes"])
            cls = {2: "fields two", 4: "fields four"}.get(n, "fields")
            style = f' style="grid-template-columns:repeat({n},1fr)"' if n > 4 else ""
            tight = ' data-tight="1"' if s.get("pts") else ""
            body.append(f'<div class="{cls}"{style}{tight}>'
                        f'{"".join(fld(b) for b in s["boxes"])}</div>')
        if s.get("pts"):
            items = "".join(f"<li>{md(p)}</li>" for p in s["pts"])
            top = ' style="margin-top:1.7cqi"' if s.get("boxes") else ""
            body.append(f'<ul class="pts"{top}>{items}</ul>')

        out.append(
            f'<section class="slide" id="s{idx}">{head}'
            f'<div class="body">{"".join(body)}</div>'
            f'<div class="why"><span>Why it matters</span>'
            f'<span>{md(s["why"])}</span></div></section>')

    return "\n\n".join(out)


def main(tpl_path, out_path):
    tpl = io.open(tpl_path, encoding="utf-8").read()
    start = tpl.index('<nav class="toc">')
    end = tpl.index('<p class="endnote">')
    endnote = (
        '<p class="endnote"><b>Sourced from the Primble codebase.</b> '
        'Figures are rounded for a non-technical audience; the exact counts behind '
        'them live in the repository. Slide 22 marks the agency-system handoff as '
        'built-but-not-yet-a-direct-connection, and slide 28 marks what is still in '
        'flight - keep both honest in the room. The matching PowerPoint is '
        'Primble-Investor-Deck.pptx; both are generated from one source so they '
        'cannot drift.</p>')
    io.open(out_path, "w", encoding="utf-8").write(tpl[:start] + emit() + endnote + "\n\n</div>\n")
    print(f"wrote {out_path} ({len(DECK)} slides)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
