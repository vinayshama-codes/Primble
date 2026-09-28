"""
report_125_run.py - one ACORD 125 test run, graded every way we have, written
as the markdown section that goes into improving125-21sep.md.

    python3 backend/scripts/dump_a125_run.py <session_id> > fr125_run.json
    python3 backend/scripts/report_125_run.py \
        --key fr125_test_data/FR125_answer_key.json --dump fr125_run.json \
        --label "ROUND 2 - TEST 1" > round2_test1.md

    # a downloaded PDF instead of a dump (no extraction or pass-by-pass detail)
    python3 backend/scripts/report_125_run.py --key ... --pdf filled.pdf --text doc.txt

    # next run: compare against this one
    ... --json-out r2t1.json            then            ... --compare r2t1.json

THE FOUR NUMBERS (the owner's format, 28 Sep)
---------------------------------------------
  correct      the box holds the right value. Split three ways so nothing is
               hidden: EXACT (after formatting), CODE (ACORD's code written as
               its word, from the tooltip), MEANING (narrative boxes only)
  wrong        the box contradicts the documents; PARTIAL = everything it says
               is right but part of the meaning is missing
  missing      the documents state it, the box is blank. Split by where it was
               printed (a scanned page = OCR first) and, from a dump, by which
               pass owned the box
  made up      a value where the documents state NOTHING. Kept apart from a
               value a RULE says must be blank and from a TRAP value that
               landed in its trap box (a real value, the wrong role)
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve()
BACKEND = HERE.parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE.parent))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, str(HERE.parent / f"{name}.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


SFF = _load("score_form_fill")
FORM = "ACORD_125"


def _pct(a: int, b: int) -> str:
    return f"{100.0 * a / b:.1f}%" if b else "-"


def grade(key: dict, stamped: dict, fates: dict) -> dict:
    stamped = SFF.as_printed(FORM, stamped)        # grade what the PDF prints
    res = SFF.score_form(FORM, key, stamped, lambda f: None)
    rows = SFF.score_rows(FORM, key, stamped)
    t, det = res["tally"], res["details"]
    fields = key.get("fields") or {}
    scanned = set((key.get("_meta") or {}).get("scanned_only") or [])

    missing = [r for r in det.get("missing", [])]
    miss_scan = [r for r in missing if r[0] in scanned]
    miss_fate = Counter(fates.get(r[0], "unknown") for r in missing) if fates else Counter()

    viol = det.get("blank_violation", [])
    made_up = [r for r in viol if (fields.get(r[0]) or {}).get("verdict") == "blank_no_data"]
    by_rule = [r for r in viol if (fields.get(r[0]) or {}).get("verdict") == "blank_by_rule"]
    no_row = [r for r in viol if (fields.get(r[0]) or {}).get("verdict") == "not_applicable"]
    n_exp = len(key["expect"].get(FORM, {}))
    return {
        "n_expect": n_exp, "n_blank": len(key["must_be_blank"].get(FORM, [])),
        "n_not_scored": sum(1 for v in fields.values() if v.get("verdict") == "not_scored"),
        "correct": t["correct"], "exact": t["correct_exact"], "code": t["correct_code"],
        "meaning": t["correct_meaning"], "wrong": t["wrong"], "partial": t["wrong_partial"],
        "missing": len(missing), "missing_scanned": len(miss_scan),
        "missing_by_pass": dict(miss_fate),
        "violations": len(viol), "made_up": len(made_up), "by_rule": len(by_rule),
        "no_row": len(no_row), "forbidden": t["forbidden"], "shape": t["shape"],
        "overflow": t["overflow_leak"], "rows": rows,
        "detail": {"wrong": det.get("wrong", []), "missing": missing,
                   "made_up": made_up, "by_rule": by_rule, "no_row": no_row,
                   "forbidden": det.get("forbidden", []), "shape": det.get("shape", []),
                   "overflow": det.get("overflow_leak", []),
                   "meaning": det.get("correct_meaning", []),
                   "code": det.get("correct_code", [])},
        "scanned": scanned,
    }


def extraction(key: dict, dump: dict):
    """ENTITY-CELL from LLM call 1, when the dump and the key allow it."""
    exp = key.get("expected_facts")
    if not exp or not dump:
        return None, ""
    ext = _load("score_a125_extraction")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ext._report(dump.get("merged_facts") or {}, dump.get("raw_text") or "", exp)
    out = buf.getvalue()
    m = re.search(r"ENTITY-CELL\s+(\d+)/(\d+)", out)
    s = re.search(r"-> (\d+) correct / (\d+) wrong / (\d+) missing", out)
    return ({"cells_ok": int(m.group(1)), "cells": int(m.group(2)),
             "scalars": tuple(int(x) for x in s.groups()) if s else None,
             "invented": len(re.findall(r"^\s+INVENTED", out, re.M))} if m else None), out


def audit(dump_or_stamped: dict, raw: str, facts: dict, fates: dict, package=None):
    A = _load("audit_125_rules")
    return A.audit(dump_or_stamped, facts, raw, fates, package)


def md(label: str, key: dict, g: dict, ext, ext_text: str, aud, session: str,
       prev: dict = None, max_rows: int = 40) -> str:
    o = []
    add = o.append
    kit = (key.get("_meta") or {}).get("kit", "")
    add(f"# {label} RESULTS - {date.today().strftime('%d %b %Y')}\n")
    add(f"Kit: **{kit}**. Session `{session or 'n/a'}`. ACORD 125 only, no human "
        f"edits. Graded against the answer key by `score_form_fill.py` (meaning-aware "
        f"since 28 Sep), and against the documents alone by `audit_125_rules.py`.\n")

    def delta(k, v):
        if not prev or k not in prev:
            return ""
        d = v - prev[k]
        return f" ({'+' if d > 0 else ''}{d})" if d else " (0)"

    add("## The four numbers\n")
    add("| | boxes | |")
    add("|---|---|---|")
    add(f"| **Correct** | **{g['correct']}** of {g['n_expect']}{delta('correct', g['correct'])} "
        f"| {g['exact']} exact, {g['code']} code written as its word, "
        f"{g['meaning']} by meaning |")
    add(f"| **Wrong** | **{g['wrong']}**{delta('wrong', g['wrong'])} | "
        f"{g['partial']} of them partial - right but incomplete |")
    by_pass = ", ".join(f"{v} {k}" for k, v in sorted(g["missing_by_pass"].items())) \
        if g["missing_by_pass"] else "no dump - pass unknown"
    add(f"| **In the documents, missing from the form** | **{g['missing']}**"
        f"{delta('missing', g['missing'])} | {g['missing_scanned']} printed only on a "
        f"scanned page; by pass: {by_pass} |")
    add(f"| **Made-up values** - a value where the documents state nothing | "
        f"**{g['made_up']}**{delta('made_up', g['made_up'])} | |")
    add(f"| Wrong-role values - a trap value in its trap box | {g['forbidden']}"
        f"{delta('forbidden', g['forbidden'])} | a real value, the wrong party or term |")
    add(f"| A rule says blank, and it was filled | {g['by_rule']} | |")
    add(f"| A row with no entity, and it was filled | {g['no_row']} | |")
    add("")
    filled = g["correct"] + g["wrong"]
    add(f"**Accuracy of what it filled: {g['correct']} / {filled} = "
        f"{_pct(g['correct'], filled)}.**  ")
    add(f"**Coverage of what it should fill: {g['correct']} / {g['n_expect']} = "
        f"{_pct(g['correct'], g['n_expect'])}.**\n")

    add("## Scorecard (round 1 format)\n")
    add("| | boxes |")
    add("|---|---|")
    add(f"| Must carry a value | {g['n_expect']} |")
    add(f"| &nbsp;&nbsp;correct | **{g['correct']}** |")
    add(f"| &nbsp;&nbsp;wrong value | **{g['wrong']}** |")
    add(f"| &nbsp;&nbsp;missing (blank, should be filled) | **{g['missing']}** |")
    add(f"| Must stay empty | {g['n_blank']} |")
    add(f"| &nbsp;&nbsp;violated - a value appeared | **{g['violations']}** |")
    add(f"| **Fabricated** (scoped decoy landed) | **{g['forbidden']}** |")
    add(f"| Wrong shape (FEIN / ZIP / code format) | {g['shape']} |")
    add(f"| Overflow leak (a no-slot row displacing a real one) | {g['overflow']} |")
    add(f"| Not scored | {g['n_not_scored']} |\n")

    if g["rows"]:
        add("## Row-cell\n")
        add("| group | cells due | correct | cross-row | orphan |")
        add("|---|---|---|---|---|")
        for r in g["rows"]:
            add(f"| {r['group']} | {r['cells_expected']} | {r['cells_correct']} | "
                f"{r['cross_row']} | {r['orphan']} |")
        add("")

    add("## Extraction (LLM call 1) - read before the form\n")
    if ext:
        sc = ext.get("scalars")
        add(f"ENTITY-CELL **{ext['cells_ok']}/{ext['cells']} = "
            f"{_pct(ext['cells_ok'], ext['cells'])}**"
            + (f"; scalars {sc[0]} correct / {sc[1]} wrong / {sc[2]} missing" if sc else "")
            + (f"; **{ext['invented']} fact(s) invented** that must be empty"
               if ext["invented"] else "; nothing invented") + ".\n")
        add("<details><summary>extraction detail</summary>\n\n```\n" + ext_text.strip()
            + "\n```\n</details>\n")
    else:
        add("Not graded - needs a session dump (`dump_a125_run.py`) and a key with "
            "`expected_facts`.\n")

    add("## Rules audit - no answer key, the form against the documents\n")
    add("| rule | status | |")
    add("|---|---|---|")
    for r in aud:
        n = len(r["fail"]) or len(r["review"]) or ""
        add(f"| {r['id']} {r['title']} | {r['status']} | {n} |")
    cnt = Counter(r["status"] for r in aud)
    add(f"\n{len(aud)} rules: {cnt['PASS']} pass, {cnt['FAIL']} fail, {cnt['REVIEW']} "
        f"to review, **{cnt['NOT EXERCISED']} not exercised by this package** "
        f"(a rule the package never triggers proves nothing either way).\n")

    def listing(title: str, rows, show_got=True, why_col=True):
        if not rows:
            return
        add(f"### {title} ({len(rows)})\n")
        add("| box | expected | on the form | |" if show_got else "| box | expected | |")
        add("|---|---|---|---|" if show_got else "|---|---|---|")
        for r in rows[:max_rows]:
            cell = lambda x, n: str(x)[:n].replace("|", "\\|").replace("\n", " ")  # noqa: E731
            f, want, got = r[0], cell(r[1], 90), cell(r[2], 90) if len(r) > 2 else ""
            why = cell(r[3], 80) if len(r) > 3 and r[3] else ""
            if f in g["scanned"]:
                why = (why + " " if why else "") + "(scanned page only)"
            if show_got:
                add(f"| `{f}` | {want} | {got} | {why} |")
            else:
                add(f"| `{f}` | {want} | {why} |")
        if len(rows) > max_rows:
            add(f"\n... and {len(rows) - max_rows} more.")
        add("")

    add("## Every box that is not right\n")
    listing("Wrong", g["detail"]["wrong"])
    listing("In the documents, missing from the form", g["detail"]["missing"], show_got=False)
    listing("Made up - the documents state nothing", g["detail"]["made_up"])
    listing("Wrong role - a trap value in its trap box", g["detail"]["forbidden"])
    listing("A rule says blank", g["detail"]["by_rule"])
    listing("A row with no entity", g["detail"]["no_row"])
    listing("Wrong shape", g["detail"]["shape"])
    listing("Overflow leak", g["detail"]["overflow"])
    listing("Counted correct BY MEANING - check the wording", g["detail"]["meaning"])
    listing("Counted correct - ACORD code written as its word", g["detail"]["code"])
    fails = [(f"{r['id']}: {f}", v, why) for r in aud for f, v, why in r["fail"]]
    listing("Rules audit failures", [(a, "", b, c) for a, b, c in fails])
    return "\n".join(o)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--dump", help="JSON from dump_a125_run.py")
    ap.add_argument("--pdf", help="a filled ACORD 125 PDF, instead of a dump")
    ap.add_argument("--text", help="the uploaded text, with --pdf (for the audit)")
    ap.add_argument("--label", default="ROUND 2 - TEST 1")
    ap.add_argument("--json-out", help="save the numbers, for --compare next time")
    ap.add_argument("--compare", help="a previous --json-out, to print the change")
    ap.add_argument("--max-rows", type=int, default=40)
    a = ap.parse_args()
    key = json.loads(Path(a.key).read_text(encoding="utf-8"))
    dump, session = {}, ""
    if a.dump:
        dump = json.loads(Path(a.dump).read_text(encoding="utf-8"))
        stamped, fates = dump.get("stamped") or {}, dump.get("fates") or {}
        facts = {**(dump.get("merged_facts") or {}), **(dump.get("flags") or {})}
        raw, session = dump.get("raw_text") or "", dump.get("session_id") or ""
        if not stamped:
            ap.error("the dump has no stamped ACORD 125 - was the form generated?")
    elif a.pdf:
        stamped, fates, facts = SFF.read_acroform(Path(a.pdf)), {}, {}
        raw = Path(a.text).read_text(encoding="utf-8") if a.text else ""
        session = Path(a.pdf).name
    else:
        ap.error("give --dump or --pdf")
    g = grade(key, stamped, fates if isinstance(fates, dict) else {})
    ext, ext_text = extraction(key, dump)
    aud = audit(stamped, raw, facts, fates if isinstance(fates, dict) else {},
                (dump or {}).get("package_form_ids"))
    prev = json.loads(Path(a.compare).read_text()) if a.compare else None
    print(md(a.label, key, g, ext, ext_text, aud, session, prev, a.max_rows))
    if a.json_out:
        keep = {k: v for k, v in g.items() if isinstance(v, int)}
        Path(a.json_out).write_text(json.dumps(keep, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
