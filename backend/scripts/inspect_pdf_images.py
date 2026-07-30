"""What embedded images does a PDF actually contain, and what will OCR do with each?

Answers "the log says N embedded images were OCR'd but I don't see any images in
that document" without spending a cent - it makes NO Vision calls. It reports the
same gates services/ocr_service.py applies, in the same order, so the counts here
reconcile exactly with the "(N examined: ...)" summary line in the runtime log.

    cd backend
    ./venv/Scripts/python.exe scripts/inspect_pdf_images.py "C:\\path\\to\\policy.pdf"

    --save-dir DIR   also write every OCR-bound image to DIR so you can look at them
    --all            list every image, not just the first 40

Column meanings:
    stored      the raster's real pixel dimensions inside the PDF
    shown       how large it is drawn on the page, in points (72pt = 1 inch)
    page%       share of the page area it covers
    verdict     OCR / skipped, with the gate that decided it
"""
import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz  # noqa: E402
from services import ocr_service  # noqa: E402


def classify(doc, page, page_idx, img, word_boxes, page_area, seen):
    """Mirror _image_candidates' gate order and return (verdict, detail)."""
    xref = img[0]
    rw, rh = int(img[2] or 0), int(img[3] or 0)

    if xref in seen:
        return "repeat", f"same image as an earlier page (xref {xref})"
    if max(rw, rh) < ocr_service._EMB_MIN_RASTER_LONG_PX:
        return "too small", f"long side {max(rw, rh)}px < {ocr_service._EMB_MIN_RASTER_LONG_PX}"
    if min(rw, rh) < ocr_service._EMB_MIN_RASTER_SHORT_PX:
        return "too small", f"short side {min(rw, rh)}px < {ocr_service._EMB_MIN_RASTER_SHORT_PX}"

    try:
        bbox = page.get_image_bbox(img)
    except Exception:
        bbox = None
    if bbox is not None:
        if bbox.is_infinite or bbox.is_empty:
            return "too small", "no usable placement rectangle"
        if bbox.width < ocr_service._EMB_MIN_DISPLAY_PT or bbox.height < ocr_service._EMB_MIN_DISPLAY_PT:
            return "too small", f"drawn at {bbox.width:.0f}x{bbox.height:.0f}pt"
        if page_area and (bbox.get_area() / page_area) < ocr_service._EMB_MIN_AREA_RATIO:
            return "too small", f"{bbox.get_area() / page_area:.3%} of the page"

        words, coverage, text_bands = ocr_service._native_text_coverage(bbox, word_boxes)
        if (words >= ocr_service._EMB_NATIVE_COVER_MIN_WORDS
                and coverage >= ocr_service._EMB_NATIVE_COVER_RATIO):
            ink = ocr_service._image_ink_bands(page, bbox)
            if ink and len(ink) >= ocr_service._EMB_INK_MIN_BANDS:
                spread = len(text_bands & ink) / len(ink)
            else:
                spread = len(text_bands) / ocr_service._EMB_NATIVE_BAND_COUNT
            if spread >= ocr_service._EMB_NATIVE_COVER_BANDS:
                return "covered", (f"{words} words / {coverage:.0%} glyph coverage / "
                                   f"{spread:.0%} spread - already in the text layer")
    return "OCR", ""


def inspect(path, save_dir=None, show_all=False):
    doc = fitz.open(path)
    print("=" * 78)
    print(f"{os.path.basename(path)} - {doc.page_count} page(s)")
    print("=" * 78)

    seen, rows = set(), []
    verdicts, path_a, path_b = Counter(), 0, 0
    page_texts = ocr_service._pdfplumber_extract_pages(path)

    for idx in range(doc.page_count):
        page = doc[idx]
        native = page_texts[idx] if idx < len(page_texts) else ""
        if len(native.strip()) < ocr_service._MIN_NATIVE_TEXT_LEN:
            path_b += 1
            continue          # whole page is rendered and OCR'd; images not examined
        path_a += 1

        try:
            images = page.get_images(full=True)
        except Exception:
            continue
        if not images:
            continue
        word_boxes = ocr_service._native_word_boxes(page)
        page_area = page.rect.get_area()

        for img in images:
            verdict, detail = classify(doc, page, idx, img, word_boxes, page_area, seen)
            verdicts[verdict] += 1
            try:
                bbox = page.get_image_bbox(img)
                shown = f"{bbox.width:.0f}x{bbox.height:.0f}pt"
                pct = f"{bbox.get_area() / page_area:.2%}"
            except Exception:
                shown, pct = "?", "?"
            rows.append((idx + 1, img[0], f"{int(img[2] or 0)}x{int(img[3] or 0)}",
                         shown, pct, verdict, detail))
            if verdict == "OCR":
                seen.add(img[0])
                if save_dir:
                    os.makedirs(save_dir, exist_ok=True)
                    payload = ocr_service._image_payload(
                        doc, page, img[0], bbox, int(img[2] or 0), int(img[3] or 0))
                    if payload:
                        out = os.path.join(save_dir, f"p{idx + 1:04d}_x{img[0]}.png")
                        with open(out, "wb") as fh:
                            fh.write(payload)

    print(f"\n  pages with a native text layer (images examined) : {path_a}")
    print(f"  pages with no text layer (whole page OCR'd)     : {path_b}")
    print(f"  embedded images examined                        : {sum(verdicts.values())}")
    for k in ("OCR", "repeat", "covered", "too small"):
        if verdicts[k]:
            print(f"      {verdicts[k]:>5}  {k}")

    if rows:
        limit = len(rows) if show_all else 40
        print(f"\n  {'page':>5} {'xref':>6} {'stored':>12} {'shown':>13} {'page%':>7}  verdict")
        print(f"  {'-' * 70}")
        for r in rows[:limit]:
            print(f"  {r[0]:>5} {r[1]:>6} {r[2]:>12} {r[3]:>13} {r[4]:>7}  "
                  f"{r[5]}{(' - ' + r[6]) if r[6] else ''}")
        if len(rows) > limit:
            print(f"  ... {len(rows) - limit} more (use --all)")

    ocr_n = verdicts["OCR"]
    print()
    if ocr_n:
        print(f"  => {ocr_n} distinct image(s) will be sent to OCR.")
        print("     A logo or letterhead repeated across pages counts ONCE; the rest")
        print("     show as 'repeat'. Use --save-dir to see exactly what they are.")
    else:
        print("  => No embedded image will be sent to OCR.")
    doc.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("pdfs", nargs="+")
    ap.add_argument("--save-dir")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    for p in a.pdfs:
        if os.path.isfile(p):
            inspect(p, a.save_dir, a.all)
        else:
            print(f"skip (not a file): {p}")
