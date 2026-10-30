"""Read a FLATTENED ACORD page (boxes burned into the page) by laying our
template's box rectangles over it.

A flattened PDF ("Print to PDF", an e-signature tool, an agency system that
flattens on export) still draws every typed value - but as plain page text, with
no box object and no box name. We own the template, so we know where every box
sits: the characters drawn inside a box's rectangle that the BLANK template does
not draw there are that box's value; a mark inside a checkbox ticks it.

  1. which template page: the one whose printed captions the page shares most;
  2. alignment: a scale + offset per axis FITTED to the captions printed once on
     both pages (a print-to-PDF shifts a page by a few points; "fit to page"
     prints it at 97%). The fit must explain at least half of the template
     page's captions to within 2 points with one uniform scale, or the page is
     NOT read - a reading off a misaligned page is a wrong value with exact
     confidence (review, 27 Oct 2026: at 97% the median offset read the street
     as the applicant, "APPLICANT" as the effective date and template captions
     as loss rows; a declarations page that printed "ACORD 125 (2025/03)" was
     read as an application);
  3. per box: the new characters inside its rectangle, read as text (a checkbox:
     a drawn mark, or a tick-sized character that is not a text run crossing it).
Output: the same copy dicts `read.py` builds for fillable pages. Never raises.
"""
import logging
import os
import statistics
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)
_PAD = 1.0                 # points of slack around a box
_SAME_CHAR = 1.6           # a template char within this distance is the template's own
_FIT_TOL = 2.0             # a caption the fit places within this many points is explained
_FIT_MIN_ANCHORS = 6       # ... and at least this many must be (ACORD 101 prints 10)
_FIT_MIN_SHARE = 0.5       # ... and at least this share of the template page's captions
_TPL: Dict[str, dict] = {}


class _Fit:
    """page = s * template + t, per axis (uniform scale: sx ~= sy)."""
    __slots__ = ("sx", "tx", "sy", "ty")

    def __init__(self, sx=1.0, tx=0.0, sy=1.0, ty=0.0):
        self.sx, self.tx, self.sy, self.ty = sx, tx, sy, ty

    def x(self, v):
        return self.sx * v + self.tx

    def y(self, v):
        return self.sy * v + self.ty

    def box(self, bbox, pad=0.0):
        x0, top, x1, bottom = bbox
        return (self.x(x0) - pad, self.y(top) - pad, self.x(x1) + pad, self.y(bottom) + pad)


def _axis_fit(src, dst):
    """Theil-Sen: the median pairwise slope, then the median intercept."""
    n = len(src)
    slopes = []
    step = max(1, n // 60)                         # bounded work on a caption-heavy page
    for i in range(0, n, step):
        for j in range(i + 1, n, step):
            if abs(src[i] - src[j]) > 40:
                slopes.append((dst[i] - dst[j]) / (src[i] - src[j]))
    s = statistics.median(slopes) if slopes else 1.0
    t = statistics.median(d - s * v for v, d in zip(src, dst))
    return s, t


def _fit(t_anchors: Dict[str, Tuple[float, float]], words: Dict[str, Tuple[float, float]]) -> Optional[_Fit]:
    shared = [k for k in t_anchors if k in words]
    need = max(_FIT_MIN_ANCHORS, int(round(_FIT_MIN_SHARE * len(t_anchors))))
    if len(shared) < need:
        return None
    pairs = [(t_anchors[k], words[k]) for k in shared]
    keep = pairs
    fit = None
    for _ in range(3):
        sx, tx = _axis_fit([a[0] for a, _b in keep], [b[0] for _a, b in keep])
        sy, ty = _axis_fit([a[1] for a, _b in keep], [b[1] for _a, b in keep])
        fit = _Fit(sx, tx, sy, ty)
        keep = [(a, b) for a, b in pairs
                if abs(fit.x(a[0]) - b[0]) <= _FIT_TOL and abs(fit.y(a[1]) - b[1]) <= _FIT_TOL]
        if len(keep) < need:
            return None
    if not (0.5 <= fit.sx <= 1.5) or abs(fit.sx - fit.sy) > 0.02:
        return None
    return fit


def _by_text(chars) -> Dict[str, List[Tuple[float, float]]]:
    out: Dict[str, List[Tuple[float, float]]] = {}
    for c in chars:
        out.setdefault(c["text"], []).append((c["x0"], c["top"]))
    return out


def _marks(page) -> List[Tuple[float, float, float, float]]:
    """Every drawn line / curve / rectangle's box - a tick is drawn, not typed."""
    out = []
    for kind in ("lines", "curves", "rects"):
        for o in getattr(page, kind, []) or []:
            try:
                out.append((float(o["x0"]), float(o["top"]), float(o["x1"]), float(o["bottom"])))
            except Exception:                                  # noqa: BLE001
                continue
    return out


def _new_mark_in(marks, tmarks, bbox, fit: "_Fit") -> bool:
    """A drawn mark inside the box that the blank template does not draw there."""
    x0, top, x1, bottom = fit.box(bbox, _PAD)
    bx0, btop, bx1, bbot = fit.box(bbox)
    for (a, b, c, d) in marks:
        if not (x0 <= (a + c) / 2 <= x1 and top <= (b + d) / 2 <= bottom):
            continue
        # The box's own frame (its outline, or a line on one of its edges) is not
        # a tick - a flattener draws it for every bordered box, ticked or not.
        if (abs(a - bx0) <= 2 and abs(c - bx1) <= 2 and abs(b - btop) <= 2 and abs(d - bbot) <= 2):
            continue
        if (c - a) < 0.5 or (d - b) < 0.5:
            continue                                   # a straight edge line, not a mark
        if any(abs(fit.x(ta) - a) <= _SAME_CHAR and abs(fit.y(tb) - b) <= _SAME_CHAR
               and abs(fit.x(tc) - c) <= _SAME_CHAR and abs(fit.y(td) - d) <= _SAME_CHAR
               for (ta, tb, tc, td) in tmarks):
            continue
        return True
    return False


def _template(form_id: str) -> Optional[dict]:
    """{"pages": [{"boxes": {name: (bbox, ft)}, "chars": [...], "words": {...}, "size": (w, h)}]}"""
    if form_id in _TPL:
        return _TPL[form_id]
    try:
        import pdfplumber
        import pikepdf
        from config.settings import TEMPLATE_DIR
        from utils import form_field_text as fft
        path = os.path.join(TEMPLATE_DIR, f"{form_id}.pdf")
        pages: List[dict] = []
        with pdfplumber.open(path) as pl:
            for p in pl.pages:
                words = p.extract_words()
                count: Dict[str, int] = {}
                for w in words:
                    count[w["text"]] = count.get(w["text"], 0) + 1
                pages.append({
                    "boxes": {}, "size": (float(p.width), float(p.height)),
                    "chars": _by_text(p.chars),
                    "marks": _marks(p),
                    "anchors": {w["text"]: (w["x0"], w["top"]) for w in words
                                if count[w["text"]] == 1 and len(w["text"]) >= 5 and w["text"].isalpha()},
                })
        with pikepdf.open(path) as pdf:
            for g in fft._scan_widgets(pdf).values():
                name = fft._qualified_name(g["field"])
                ft = str(fft._inherited(g["field"], "/FT") or "")
                for (pi, _w, _r, bbox) in g["widgets"]:
                    if bbox and pi < len(pages):
                        pages[pi]["boxes"].setdefault(name, (bbox, ft))
        _TPL[form_id] = {"pages": pages}
    except Exception as ex:                                    # noqa: BLE001
        logger.info("acord overlay: template %s unavailable: %s", form_id, ex)
        _TPL[form_id] = None
    return _TPL[form_id]


def _page_words(page) -> Dict[str, Tuple[float, float]]:
    words = page.extract_words()
    count: Dict[str, int] = {}
    for w in words:
        count[w["text"]] = count.get(w["text"], 0) + 1
    return {w["text"]: (w["x0"], w["top"]) for w in words if count[w["text"]] == 1}


_PAGE_OF_RE = __import__("re").compile(r"Page\s+(\d+)\s+of\s+(\d+)")


def _match_page(tpl: dict, words: Dict[str, Tuple[float, float]],
                printed_page: Optional[int] = None) -> Tuple[int, Optional[_Fit]]:
    """(template page index, fit) - (-1, None) when no template page fits. The
    page's own printed "Page n of m" decides which template page (ACORD 127's
    pages repeat their captions); captions printed once on both pages fit it."""
    best: Tuple[int, Optional[_Fit], int] = (-1, None, 0)
    indices = range(len(tpl["pages"]))
    if printed_page is not None and 0 <= printed_page < len(tpl["pages"]):
        indices = [printed_page]
    for i in indices:
        tp = tpl["pages"][i]
        shared = sum(1 for k in tp["anchors"] if k in words)
        if shared <= best[2]:
            continue
        fit = _fit(tp["anchors"], words)
        if fit is not None:
            best = (i, fit, shared)
    return best[0], best[1]


def _new_chars_in(chars, bbox, tchars, fit: "_Fit") -> list:
    """The page's characters inside the box that the blank template does not print there."""
    x0, top, x1, bottom = fit.box(bbox, _PAD)
    inside = []
    for c in chars:
        cx = (c["x0"] + c["x1"]) / 2
        cy = (c["top"] + c["bottom"]) / 2
        if not (x0 <= cx <= x1 and top <= cy <= bottom):
            continue
        if any(abs(fit.x(tx) - c["x0"]) <= _SAME_CHAR and abs(fit.y(ty) - c["top"]) <= _SAME_CHAR
               for (tx, ty) in tchars.get(c["text"], ())):
            continue                                   # the blank template's own print
        inside.append(c)
    return inside


def _char_tick(chars, bbox, tchars, fit: "_Fit", ink: Optional["_Ink"] = None) -> bool:
    """A typed tick ("X", a ZapfDingbats check) inside a checkbox: a character or
    two, wholly inside it - never a text run that crosses the box (a long value
    overflowing its own box drew letters over the next checkbox)."""
    inside = _new_chars_in(chars, bbox, tchars, fit)
    if not inside or len([c for c in inside if c["text"].strip()]) > 2 or _hidden_text_in(inside, ink):
        return False
    x0, top, x1, bottom = fit.box(bbox, _PAD)
    if any(c["x0"] < x0 - 0.5 or c["x1"] > x1 + 0.5 for c in inside):
        return False
    for c in chars:
        if c in inside or not c["text"].strip():
            continue
        cy = (c["top"] + c["bottom"]) / 2
        if top <= cy <= bottom and (x0 - 3 <= c["x1"] <= x0 or x1 <= c["x0"] <= x1 + 3):
            return False                               # the run continues just outside the box
    return True


# HIDDEN TEXT IS NO VALUE (28 Oct 2026, review). A flattened page keeps every
# glyph a box's appearance drew - also the ones its own rectangle CLIPS away: a
# long remarks box (CH125's 125 lists 26 warranty claims) runs on, invisibly,
# over the loss history and prior-carrier rows below it, and the text layer
# reports those glyphs where they would have been. Read as new characters
# inside those boxes they gave exact-confidence garbage ("d0e8c/k0 9o/v2e0n2 5-
# ig" as an occurrence date, a claim description as a prior carrier). Two rules:
#   * a new character is on the page only where the RENDERED page has ink the
#     rendered blank template has not (a grid line under a hidden glyph is the
#     template's own ink, never the glyph's);
#   * a box where two different characters sit on one spot (a visible value
#     with hidden text drawn over it) is not read at all - blank over wrong.
_INK_ZOOM = 3.0
_INK_DARK = 200          # 0-255 grey: darker than this is ink
_INK_SLACK = 2           # template ink this many pixels away still covers a pixel
_TPL_PIX: Dict[tuple, object] = {}


class _Gray:
    """A rendered page as grey bytes (PyMuPDF; no numpy in this deployment)."""
    __slots__ = ("w", "h", "data")

    def __init__(self, pix):
        self.w, self.h = pix.width, pix.height
        n = pix.n
        data = pix.samples
        self.data = data if n == 1 else bytes(data[::n])

    def dark_in(self, x0: int, x1: int, y: int) -> list:
        if not (0 <= y < self.h):
            return []
        x0, x1 = max(0, x0), min(self.w, x1)
        if x1 <= x0:
            return []
        row = self.data[y * self.w + x0: y * self.w + x1]
        return [x0 + i for i, b in enumerate(row) if b < _INK_DARK]

    def any_dark(self, x0: int, x1: int, y0: int, y1: int) -> bool:
        x0, x1 = max(0, x0), min(self.w, x1)
        if x1 <= x0:
            return False
        for y in range(max(0, y0), min(self.h, y1)):
            if min(self.data[y * self.w + x0: y * self.w + x1]) < _INK_DARK:
                return True
        return False


def _render(path: str, page_no: int):
    import fitz
    doc = fitz.open(path)
    try:
        pg = doc[page_no]
        pix = pg.get_pixmap(matrix=fitz.Matrix(_INK_ZOOM, _INK_ZOOM), colorspace=fitz.csGRAY, alpha=False)
        return pg.rect, pg.rotation, _Gray(pix)
    finally:
        doc.close()


class _Ink:
    """Is a character visible: NEW ink on the rendered page under it - dark
    pixels the rendered blank template (laid over by the page's fit) has not
    near the same spot."""

    def __init__(self, pdf_path: str, page_no: int, plumber_page, form_id: str, tpl_page: int, fit: "_Fit"):
        self.page = self.tpl = None
        self.fit = fit
        self.memo: Dict[int, bool] = {}
        try:
            rect, rot, gray = _render(pdf_path, page_no)
            if rot or abs(rect.width - float(plumber_page.width)) > 1 or abs(rect.height - float(plumber_page.height)) > 1:
                return                    # another frame: never judge, never drop
            key = (form_id, tpl_page)
            if key not in _TPL_PIX:
                from config.settings import TEMPLATE_DIR
                _TPL_PIX[key] = _render(os.path.join(TEMPLATE_DIR, f"{form_id}.pdf"), tpl_page)[2]
            self.page, self.tpl = gray, _TPL_PIX[key]
        except Exception as ex:                                # noqa: BLE001
            logger.info("acord overlay: page %d not rendered (%s) - no ink check", page_no + 1, ex)
            self.page = self.tpl = None

    def shows(self, c) -> bool:
        if self.page is None:
            return True
        k = id(c)
        if k in self.memo:
            return self.memo[k]
        ch, cw = c["bottom"] - c["top"], c["x1"] - c["x0"]
        z, f, r = _INK_ZOOM, self.fit, _INK_SLACK
        new = 0
        # the glyph's own middle: a neighbour's edge is not this glyph's ink
        x0, x1 = int((c["x0"] + 0.2 * cw) * z), int((c["x1"] - 0.2 * cw) * z) + 1
        for py in range(int((c["top"] + 0.15 * ch) * z), int((c["bottom"] - 0.15 * ch) * z) + 1):
            for px in self.page.dark_in(x0, x1, py):
                tx = int(((px / z - f.tx) / (f.sx or 1)) * z)
                ty = int(((py / z - f.ty) / (f.sy or 1)) * z)
                if self.tpl.any_dark(tx - r, tx + r + 1, ty - r, ty + r + 1):
                    continue              # the blank template's own ink
                new += 1
                if new >= 2:
                    self.memo[k] = True
                    return True
        self.memo[k] = False
        return False


def _hidden_text_in(inside, ink: Optional["_Ink"]) -> bool:
    """A letter or digit in the box the rendered page does not show: hidden
    text runs through the box, and the glyphs around it cannot be told from
    it - the box is not read (punctuation is too small to judge by ink)."""
    return ink is not None and any(str(c.get("text") or "").isalnum() and not ink.shows(c) for c in inside)


def _overprinted(inside) -> bool:
    """Two different characters on one spot of one line."""
    glyphs = [c for c in inside if str(c.get("text") or "").strip()]
    for i, a in enumerate(glyphs):
        for b in glyphs[i + 1:]:
            if a["text"] == b["text"] and abs(a["top"] - b["top"]) < 1 and abs(a["x0"] - b["x0"]) < 1:
                continue                 # one glyph drawn twice (a "bold" overprint)
            ox = min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])
            oy = min(a["bottom"], b["bottom"]) - max(a["top"], b["top"])
            if ox > 0.5 * min(a["x1"] - a["x0"], b["x1"] - b["x0"]) > 0 and \
                    oy > 0.4 * min(a["bottom"] - a["top"], b["bottom"] - b["top"]) > 0:
                return True
    return False


def _value_in(chars, bbox, tchars, fit: "_Fit", ink: Optional["_Ink"] = None) -> Optional[str]:
    """The box's text; "" for none; None when the box cannot be read."""
    inside = _new_chars_in(chars, bbox, tchars, fit)
    if not inside:
        return ""
    if _hidden_text_in(inside, ink) or _overprinted(inside):
        return None
    inside.sort(key=lambda c: (round(c["top"] / 3), c["x0"]))
    out, prev = [], None
    for c in inside:
        if prev is not None:
            same_line = abs(c["top"] - prev["top"]) < 3
            gap = c["x0"] - prev["x1"]
            if not same_line:
                out.append(" ")
            elif gap > max(1.2, 0.25 * (c.get("size") or 8)):
                out.append(" ")
        out.append(c["text"])
        prev = c
    return " ".join("".join(out).split())


def read_flattened(pdf_path: str, pages: List) -> List[dict]:
    """Copy dicts (see read.py) for the FLATTENED pages of forms we hold a template for."""
    copies: List[dict] = []
    todo = [p for p in pages if p.kind == "flattened" and p.form_id]
    if not todo:
        return copies
    try:
        import pdfplumber
        held: Dict[str, set] = {}       # template pages the current copy of a form holds
        count: Dict[str, int] = {}
        with pdfplumber.open(pdf_path) as pl:
            for pf in todo:
                tpl = _template(pf.form_id)
                if not tpl:
                    continue
                page = pl.pages[pf.page]
                pm = _PAGE_OF_RE.search(page.extract_text() or "")
                ti, fit = _match_page(tpl, _page_words(page), int(pm.group(1)) - 1 if pm else None)
                if ti < 0 or fit is None:
                    logger.info("acord overlay: %s page %d not aligned - not read", pf.form_id, pf.page + 1)
                    continue
                fid = pf.form_id
                # A new copy only when the current one already holds this template
                # page - pages out of order stay one copy (as `read._split_copies`).
                if fid not in held or ti in held[fid]:
                    count[fid] = count.get(fid, 0) + 1
                    copies.append({"form_id": fid, "copy": count[fid], "pages": [], "kind": "flattened",
                                   "edition": pf.edition, "boxes": {}, "kinds": {}, "box_page": {}})
                    held[fid] = set()
                cur = next(c for c in reversed(copies) if c["form_id"] == fid)
                cur["pages"].append(pf.page)
                held[fid].add(ti)
                tp = tpl["pages"][ti]
                ink = _Ink(pdf_path, pf.page, page, fid, ti, fit)
                chars = page.chars
                tchars = tp["chars"]
                marks = _marks(page)
                for name, (bbox, ft) in tp["boxes"].items():
                    if ft == "/Btn":
                        if _char_tick(chars, bbox, tchars, fit, ink) or _new_mark_in(marks, tp["marks"], bbox, fit):
                            cur["boxes"][name], cur["kinds"][name] = "ticked", "check"
                            cur["box_page"][name] = pf.page
                        continue
                    v = _value_in(chars, bbox, tchars, fit, ink)
                    if v is None:
                        cur.setdefault("unread_boxes", []).append(name)
                        continue
                    if v:
                        cur["boxes"][name], cur["kinds"][name] = v, "text"
                        cur["box_page"][name] = pf.page
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("acord overlay: %s unreadable: %s", pdf_path, ex)
    return copies
