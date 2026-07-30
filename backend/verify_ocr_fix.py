"""Point this at YOUR OWN PDFs and it tells you, per file, whether the fix did
anything and whether it did anything harmful.

    cd backend
    ./venv/Scripts/python.exe verify_ocr_fix.py "C:\\path\\to\\a.pdf" [more.pdf ...]

For each file it reports:
  * what the OLD code would have extracted (native text layer only, unless the
    whole document had under 100 characters)
  * what the NEW code extracts
  * RECOVERED  - text the old code silently dropped. This is the fix working.
  * LOST       - text the old code had and the new code does not. Must be zero.
  * DUPLICATED - lines emitted more than once. Should be zero or near-zero.
  * a per-image disposition breakdown (examined / skipped and why)

Read the breakdown, not just LOST. LOST is a REGRESSION check: it compares new
output against old, so it is blind to an image the new filter discarded, since
the old code did not have that text either. "dropped at a cap" and "covered by
a text layer" are where under-recovery shows up.

It makes real Google Vision calls, so it costs roughly $1.50 per 1000 pages.
"""
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from dotenv import load_dotenv
    load_dotenv(".env")
except Exception:
    pass

from services import ocr_service  # noqa: E402


async def old_behaviour(path):
    """Exactly what the previous implementation did: native text only, with a
    whole-document OCR fallback that fired only under 100 characters."""
    loop = asyncio.get_running_loop()
    text = await loop.run_in_executor(
        ocr_service._OCR_EXECUTOR, ocr_service._pdfplumber_extract, path)
    if len(text.strip()) < ocr_service._MIN_NATIVE_TEXT_LEN:
        imgs = await loop.run_in_executor(
            ocr_service._OCR_EXECUTOR, ocr_service.extract_images_from_pdf, path)
        for ip in imgs:
            t, _ = await ocr_service.ocr_image_file(ip)
            text += t + "\n"
            try:
                os.remove(ip)
            except OSError:
                pass
    return text.strip()


def lines(t, minlen=12):
    out = []
    for ln in t.splitlines():
        s = re.sub(r"\s+", " ", ln).strip()
        if len(s) >= minlen:
            out.append(s)
    return out


def report(path):
    print("=" * 78)
    print(os.path.basename(path))
    print("=" * 78)

    calls = {"n": 0, "imgs": 0}
    real = ocr_service._vision_batch_call

    def counting(payloads):
        calls["n"] += 1
        calls["imgs"] += len(payloads)
        return real(payloads)

    # Capture the disposition of every embedded image. Without this the report
    # below can only ever show a REGRESSION against the old code - it is blind
    # to under-recovery, because anything NEITHER implementation extracts looks
    # identical to "there was nothing there".
    budget = ocr_service._DocBudget()
    real_build = ocr_service._build_window_jobs

    def shared_budget(pdf_path, idxs, texts, _b):
        return real_build(pdf_path, idxs, texts, budget)

    ocr_service._vision_batch_call = counting
    ocr_service._build_window_jobs = shared_budget
    try:
        old = asyncio.run(old_behaviour(path))
        calls["n"] = calls["imgs"] = 0
        new, low_conf = asyncio.run(ocr_service.extract_text_from_pdf(path))
    finally:
        ocr_service._vision_batch_call = real
        ocr_service._build_window_jobs = real_build

    old_l, new_l = lines(old), lines(new)
    old_s, new_s = set(old_l), set(new_l)
    recovered = [l for l in new_l if l not in old_s]
    lost = [l for l in old_l if l not in new_s]
    dupes = {l: new_l.count(l) for l in set(new_l) if new_l.count(l) > 1}

    print(f"  old code extracted : {len(old):>7} chars, {len(old_l)} lines")
    print(f"  new code extracted : {len(new):>7} chars, {len(new_l)} lines")
    print(f"  Vision requests    : {calls['n']} ({calls['imgs']} images)")
    print(f"  low-confidence     : {len(low_conf)} token(s)"
          f"{'  [needs_manual_review]' if 'needs_manual_review' in low_conf else ''}")

    # What became of every embedded image. LOST (below) compares against the
    # OLD code and therefore cannot see an image THIS code filtered out - the
    # old code did not have that text either. Read this block for that.
    print(f"\n  embedded images    : {budget.images_examined} examined")
    if budget.images_examined:
        for label, value, note in (
            ("repeat of an earlier page", budget.skipped_duplicate, ""),
            ("covered by a text layer", budget.skipped_covered,
             "<-- verify these really are searchable scans"),
            ("too small to hold text", budget.skipped_small, ""),
            ("could not decode", budget.skipped_unreadable,
             "<-- INVESTIGATE" if budget.skipped_unreadable else ""),
            ("dropped at a cap", budget.skipped_capped,
             "<-- DATA LOSS, raise the cap" if budget.skipped_capped else ""),
        ):
            if value:
                print(f"      {value:>4} {label} {note}")
    if budget.pages_images_unexamined:
        print(f"      {budget.pages_images_unexamined:>4} page(s) never examined "
              f"(document image cap exhausted)  <-- DATA LOSS")

    print(f"\n  RECOVERED by the fix ({len(recovered)} lines) "
          f"{'<-- the fix is doing work' if recovered else '(this file had nothing hidden in images)'}")
    for l in recovered[:15]:
        print(f"      + {l[:88]}")
    if len(recovered) > 15:
        print(f"      ... {len(recovered)-15} more")

    print(f"\n  LOST vs old code ({len(lost)} lines)  "
          f"{'*** INVESTIGATE ***' if lost else 'none - good'}"
          f"   [regression only - see the image breakdown above for under-recovery]")
    for l in lost[:15]:
        print(f"      - {l[:88]}")

    print(f"\n  DUPLICATED lines ({len(dupes)})  "
          f"{'*** INVESTIGATE ***' if len(dupes) > 3 else 'ok'}")
    for l, c in list(dupes.items())[:8]:
        print(f"      {c}x {l[:84]}")
    print()
    return len(lost), len(dupes), len(recovered)


if __name__ == "__main__":
    targets = sys.argv[1:]
    if not targets:
        print(__doc__)
        raise SystemExit(2)
    tot_lost = tot_dup = tot_rec = 0
    for p in targets:
        if not os.path.isfile(p):
            print(f"skip (not a file): {p}")
            continue
        l, d, r = report(p)
        tot_lost += l
        tot_dup += d
        tot_rec += r
    print("=" * 78)
    print(f"TOTAL across {len(targets)} file(s): "
          f"{tot_rec} lines recovered, {tot_lost} lost, {tot_dup} duplicated")
    print("PASS: nothing lost" if tot_lost == 0 else "FAIL: content was lost")
