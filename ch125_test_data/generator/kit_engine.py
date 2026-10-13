"""
kit_engine.py - the page engine for the CH125 kit.

Content FLOWS: a document pours down the page and on to the next; a ruled table
crossing a page break repeats its header unless told not to. Every item is a
real text-layer string (no images), so the kit's character count is exact and
every value a human can read is in the text layer.

Hard formats, all text-layer:
  tracked    letter-spaced teletype ("P O L I C Y  N O")
  drift      a right column printed a few points off its label's baseline
  riffled    table cells that are NOT clipped - a long cell runs under the next
  box_on/off an X (or nothing) inside a drawn box - answers by POSITION
  strike     text with a line through it (the text layer keeps it)
  tiny       4.3 pt fine print
  watermark  a rotated stamp across a page (its letters land in the text layer)
  form       ruled boxes with a small label above each value
  landscape  a wide page
"""
from __future__ import annotations

from typing import Callable, List, Optional, Sequence

from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

W, H = LETTER
LEFT = 36.0
RIGHT = 36.0
TOP_Y = H - 58.0
BOTTOM_Y = 40.0

MONO, MONO_B = "Courier", "Courier-Bold"
SANS, SANS_B = "Helvetica", "Helvetica-Bold"
SERIF, SERIF_B, SERIF_I = "Times-Roman", "Times-Bold", "Times-Italic"


class It:
    __slots__ = ("x", "text", "font", "size", "kind", "dy")

    def __init__(self, x, text, font=MONO, size=7.0, kind="plain", dy=0.0):
        self.x, self.text, self.font, self.size, self.kind, self.dy = x, text, font, size, kind, dy


class Ln:
    __slots__ = ("items", "lead", "rule", "cols", "boxes")

    def __init__(self, items=None, lead=9.6, rule=False, cols=None, boxes=None):
        self.items = items or []
        self.lead = lead
        self.rule = rule
        self.cols = cols
        self.boxes = boxes            # [(x0, x1)] ruled form boxes spanning this line


class Page:
    def __init__(self, title="", header="", wide=False):
        self.title, self.header, self.wide = title, header, wide
        self.lines: List[Ln] = []
        self.used = 0.0
        self.watermark: Optional[str] = None
        self.stamp: Optional[str] = None

    def width(self):
        return (landscape(LETTER)[0] if self.wide else W)

    def height_avail(self):
        top = (landscape(LETTER)[1] if self.wide else H) - 58.0
        return top - BOTTOM_Y


def width_of(text, font, size):
    return stringWidth(text, font, size)


def wrap(text: str, font: str, size: float, max_w: float) -> List[str]:
    out, line = [], ""
    for word in str(text).split():
        cand = f"{line} {word}" if line else word
        if width_of(cand, font, size) > max_w and line:
            out.append(line)
            line = word
        else:
            line = cand
    if line:
        out.append(line)
    return out or [""]


class Flow:
    def __init__(self, footer: str):
        self.pages: List[Page] = []
        self.footer = footer
        self.cur: Optional[Page] = None
        self.title = ""
        self.header = ""
        self.wide = False
        self.wm = None

    # ── page mechanics ────────────────────────────────────────────────────
    def _open(self):
        self.cur = Page(self.title, self.header, self.wide)
        self.cur.watermark = self.wm
        self.pages.append(self.cur)

    def new_page(self, wide: Optional[bool] = None):
        if wide is not None:
            self.wide = wide
        self._open()

    def room(self) -> float:
        if self.cur is None:
            return 0.0
        return self.cur.height_avail() - self.cur.used

    def need(self, height: float):
        if self.cur is None or self.room() < height:
            self._open()

    def add(self, ln: Ln):
        if self.cur is None or self.room() < ln.lead:
            self._open()
        self.cur.lines.append(ln)
        self.cur.used += ln.lead

    def page_w(self):
        return (self.cur.width() if self.cur else W) - LEFT - RIGHT

    # ── documents ─────────────────────────────────────────────────────────
    def doc(self, title: str, header: str = "", subtitle: str = "", new_page: bool = False,
            wide: bool = False, min_room: float = 120.0):
        """Start a document. A new document begins on a fresh page when asked, or
        when the page in progress has too little room for its opening."""
        changed = wide != self.wide
        marked = self.cur is not None and self.cur.watermark is not None
        self.wm = None
        self.title, self.header, self.wide = title, header, wide
        if new_page or changed or marked or self.cur is None or self.room() < min_room:
            self._open()
        else:
            self.gap(6)
        self.add(Ln([It(LEFT, "=" * 112, MONO, 6.2)], lead=8))
        self.add(Ln([It(LEFT, title, SANS_B, 9.0)], lead=12))
        if subtitle:
            for s in wrap(subtitle, SANS, 7.0, self.page_w()):
                self.add(Ln([It(LEFT, s, SANS, 7.0)], lead=9))

    def gap(self, h: float = 5.0):
        if self.cur is not None and self.cur.lines:
            self.add(Ln([], lead=h))

    def head(self, text: str, font=SANS_B, size=7.8):
        self.need(30)
        self.gap(4)
        self.add(Ln([It(LEFT, text, font, size)], lead=size + 3))

    def line(self, text: str, font=MONO, size=7.0, x: float = LEFT, kind="plain", lead=None):
        """One printed line - wrapped (never clipped) if it is wider than the page."""
        room = self.page_w() - (x - LEFT)
        parts = [text] if width_of(text, font, size) <= room else wrap(text, font, size, room)
        for p in parts:
            self.add(Ln([It(x, p, font, size, kind)], lead=lead or (size + 2.6)))

    def para(self, text: str, font=SANS, size=7.2, indent: float = 0.0, width: float = None,
             lead=None):
        w = (width or self.page_w()) - indent
        for s in wrap(text, font, size, w):
            self.line(s, font, size, LEFT + indent, lead=lead)

    def paras(self, texts: Sequence[str], **kw):
        for t in texts:
            self.para(t, **kw)
            self.gap(3)

    def kv(self, pairs, font=MONO, size=7.0, label_w: float = 170.0, leader: bool = False,
           x: float = LEFT):
        for k, v in pairs:
            room = self.page_w() - (x - LEFT) - label_w
            chunks = wrap(str(v), font, size, room)
            if leader:
                lab = f"{k} "
                while width_of(lab + ".", font, size) < label_w - 6:
                    lab += "."
            else:
                lab = k
            self.add(Ln([It(x, lab, font, size), It(x + label_w, chunks[0], font, size)],
                        lead=size + 2.6))
            for ch in chunks[1:]:
                self.add(Ln([It(x + label_w, ch, font, size)], lead=size + 2.6))

    def teletype(self, lines, size=6.6):
        for ln in lines:
            self.add(Ln([It(LEFT, ln, MONO, size, "tracked")], lead=size + 3.4))

    def two_column(self, left: Sequence[str], right: Sequence[str], drift: float = 0.0,
                   font=MONO, size=7.0, xr: float = 320.0):
        for i in range(max(len(left), len(right))):
            items = []
            if i < len(left):
                items.append(It(LEFT, left[i], font, size))
            if i < len(right):
                dy = drift * ((i % 3) - 1) if drift else 0.0
                items.append(It(xr, right[i], font, size, "plain", dy))
            self.add(Ln(items, lead=size + 2.8))

    def table(self, header, rows, xs, style="ruled", font=MONO, size=6.6,
              repeat_header=True, bold_header=True, clip=True):
        """ruled / plain / riffled. header may be a list of header rows."""
        pw = (self.cur.width() if self.cur else W) - RIGHT
        bounds = list(xs) + [pw]

        def cells(row, bold=False):
            out = []
            for i, (x, c) in enumerate(zip(xs, row)):
                c = "" if c is None else str(c)
                if style != "riffled" and clip:
                    maxw = bounds[i + 1] - x - 3
                    while c and width_of(c, font, size) > maxw:
                        c = c[:-1]
                f = (MONO_B if font == MONO else SANS_B) if bold else font
                out.append(It(x, c, f, size))
            return out

        hdrs = header if header and isinstance(header[0], (list, tuple)) else ([header] if header else [])
        lead = size + 3.2
        self.need(lead * (len(hdrs) + 2))
        for h in hdrs:
            self.add(Ln(cells(h, bold_header), lead=lead, rule=(style == "ruled"), cols=list(xs)))
        for row in rows:
            if self.room() < lead:
                self._open()
                if repeat_header:
                    for h in hdrs:
                        self.add(Ln(cells(h, bold_header), lead=lead, rule=(style == "ruled"),
                                    cols=list(xs)))
            self.add(Ln(cells(row), lead=lead, rule=(style == "ruled"), cols=list(xs)))

    def xcolumn(self, rows, qx=LEFT + 24, yes_x=LEFT + 452, no_x=LEFT + 482, width=410,
                font=SANS, size=6.9):
        """rows: (number, question, 'Y'|'N'|'') - the answer is an X in a column."""
        self.need(30)
        self.add(Ln([It(LEFT, "#", SANS_B, size), It(qx, "QUESTION", SANS_B, size),
                     It(yes_x - 2, "YES", SANS_B, size), It(no_x, "NO", SANS_B, size)],
                    lead=size + 4))
        for n, q, ans in rows:
            parts = wrap(q, font, size, width)
            self.need((size + 3.4) * len(parts) + 2)
            first = [It(LEFT, n, font, size), It(qx, parts[0], font, size),
                     It(yes_x, "", MONO, size, "box_on" if ans == "Y" else "box_off"),
                     It(no_x, "", MONO, size, "box_on" if ans == "N" else "box_off")]
            self.add(Ln(first, lead=size + 3.6))
            for p in parts[1:]:
                self.add(Ln([It(qx, p, font, size)], lead=size + 3.0))

    def form_row(self, cells, label_size=5.0, value_size=7.2, value_font=MONO):
        """cells: [(x0, x1, label, value)] - ruled boxes, the label above the value."""
        self.need(24)
        boxes = [(x0, x1) for x0, x1, *_ in cells]
        self.add(Ln([It(x0 + 2, lab.upper(), SANS, label_size) for x0, _x1, lab, _v in cells],
                    lead=label_size + 2.4, boxes=boxes))
        vals = []
        for x0, x1, _lab, val in cells:
            v = str(val)
            while v and width_of(v, value_font, value_size) > (x1 - x0 - 6):
                v = v[:-1]
            vals.append(It(x0 + 3, v, value_font, value_size))
        self.add(Ln(vals, lead=value_size + 3.8, boxes=boxes))

    def watermark(self, text: str):
        """Stamp the current page and every later page of this document."""
        self.wm = text
        if self.cur is not None:
            self.cur.watermark = text

    def stamp(self, text: str):
        if self.cur is not None:
            self.cur.stamp = text

    def items(self, items: List[It], lead=9.6):
        self.add(Ln(items, lead=lead))


# ════════════════════════════════════════════════════════════════════════════
# Rendering
# ════════════════════════════════════════════════════════════════════════════
def _tracked(c, x, y, text, font, size):
    gw = size * 0.6
    cx = x
    c.setFont(font, size)
    for ch in text:
        if ch == " ":
            cx += gw * 4.2
            continue
        c.drawString(cx, y, ch)
        cx += gw * 2.0


def render(path: str, pages: List[Page], footer: str, doc_title: str):
    c = canvas.Canvas(path, pagesize=LETTER, invariant=1)
    c.setTitle(doc_title)
    total = len(pages)
    for n, pg in enumerate(pages, start=1):
        size = landscape(LETTER) if pg.wide else LETTER
        c.setPageSize(size)
        pw, ph = size
        if pg.watermark:
            c.saveState()
            c.setFillGray(0.82)
            c.translate(pw / 2, ph / 2)
            c.rotate(33)
            c.setFont(SANS_B, 58)
            c.drawCentredString(0, -20, pg.watermark)
            c.restoreState()
        if pg.header:
            c.setFont(MONO, 5.8)
            c.drawString(LEFT, ph - 24, pg.header)
        c.setFont(SANS_B, 6.8)
        c.drawString(LEFT, ph - 36, pg.title)
        y = ph - 58.0
        for ln in pg.lines:
            for it in ln.items:
                if it.kind == "tracked":
                    _tracked(c, it.x, y, it.text, it.font, it.size)
                elif it.kind in ("box_on", "box_off"):
                    c.setLineWidth(0.5)
                    c.rect(it.x, y - 1.8, 7.5, 7.5, stroke=1, fill=0)
                    if it.kind == "box_on":
                        c.setFont(MONO_B, 7.6)
                        c.drawString(it.x + 1.4, y - 0.4, "X")
                elif it.kind == "strike":
                    c.setFont(it.font, it.size)
                    c.drawString(it.x, y + it.dy, it.text)
                    wdt = width_of(it.text, it.font, it.size)
                    c.setLineWidth(0.6)
                    c.line(it.x, y + it.dy + it.size * 0.32, it.x + wdt, y + it.dy + it.size * 0.32)
                else:
                    c.setFont(it.font, it.size)
                    c.drawString(it.x, y + it.dy, it.text)
            if ln.rule and ln.cols:
                c.setLineWidth(0.3)
                right = pw - RIGHT
                c.line(ln.cols[0] - 2, y - 2.6, right, y - 2.6)
                for x in ln.cols:
                    c.line(x - 2, y + ln.lead - 2.6, x - 2, y - 2.6)
                c.line(right, y + ln.lead - 2.6, right, y - 2.6)
            if ln.boxes:
                c.setLineWidth(0.35)
                for x0, x1 in ln.boxes:
                    c.line(x0, y + ln.lead - 2.2, x0, y - 2.2)
                    c.line(x1, y + ln.lead - 2.2, x1, y - 2.2)
                if ln.items and ln.items[0].size <= 5.5:
                    for x0, x1 in ln.boxes:
                        c.line(x0, y + ln.lead - 2.2, x1, y + ln.lead - 2.2)
                else:
                    for x0, x1 in ln.boxes:
                        c.line(x0, y - 2.2, x1, y - 2.2)
            y -= ln.lead
        if pg.stamp:
            c.saveState()
            c.setStrokeColorRGB(0.55, 0.1, 0.1)
            c.setFillColorRGB(0.55, 0.1, 0.1)
            c.setLineWidth(1.0)
            c.rect(pw - 210, ph - 112, 170, 34, stroke=1, fill=0)
            c.setFont(SANS_B, 7.5)
            parts = pg.stamp.split("|")
            for i, p in enumerate(parts[:3]):
                c.drawString(pw - 204, ph - 90 - i * 9, p.strip())
            c.restoreState()
        c.setFont(MONO, 5.8)
        c.drawString(LEFT, 18, footer)
        c.drawString(pw - 96, 18, f"Page {n} of {total}")
        c.showPage()
    c.save()
    return total
