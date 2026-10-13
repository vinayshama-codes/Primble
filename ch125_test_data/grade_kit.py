"""
grade_kit.py - grade one CH125 run (ACORD 125 + 126 + 127) against CH125_answer_key.json.

    # newest sessions
    backend/.venv/bin/python ch125_test_data/grade_kit.py --list
    # grade a stored session (reads generated_forms[...].mapped - never the PDF)
    backend/.venv/bin/python ch125_test_data/grade_kit.py --session <id> --out ch125_test_data/runs/run1.md
    # the key grading itself (perfect form = 100%, empty form = 0 violations)
    backend/.venv/bin/python ch125_test_data/grade_kit.py --self-test

Read-only: it SELECTs the session row and writes only the report file you name.
Scoring is backend/scripts/score_form_fill.py, unchanged - the same tiers as the
FR125 kit (exact after formatting, ACORD code = its word, meaning for narrative
boxes only).

The four numbers per form, as the client asked:
  CORRECT    the box carries the expected value
  WRONG      the box contradicts the documents (a partial narrative counts here)
  MISSING    the documents state it, the box is blank
  MADE UP    a value where the documents state NOTHING (blank_no_data violated)
plus RULE BREAKS (a client rule owns the box as blank and it was filled), FORBIDDEN
(a decoy value in its trap box), SHAPE, LEAKS, ROW-CELL and the UNRESOLVED check.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent
ROOT = KIT.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")
KEY = KIT / "CH125_answer_key.json"


def _sff():
    spec = importlib.util.spec_from_file_location("_sff", str(BACKEND / "scripts" / "score_form_fill.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


SFF = _sff()


async def _list(limit=12):
    from config.database import create_pool, get_pool
    await create_pool()
    async with get_pool().acquire() as con:
        rows = await con.fetch("SELECT id, created_at FROM processing_sessions "
                               "ORDER BY created_at DESC LIMIT $1", limit)
    for r in rows:
        print(f"{r['id']}  {r['created_at']}")


async def _load(session_id: str) -> dict:
    from config.database import create_pool
    from repositories.session_repository import get_processing_session
    await create_pool()
    s = await get_processing_session(session_id)
    if not s:
        raise SystemExit(f"no session {session_id}")
    return {f: (g or {}).get("mapped") or {} for f, g in (s.get("generated_forms") or {}).items()}


def grade_form(key: dict, form: str, stamped: dict) -> dict:
    printed = SFF.as_printed(form, stamped)
    res = SFF.score_form(form, key, printed, lambda f: None)
    rows = SFF.score_rows(form, key, printed)
    fields = key["fields_by_form"][form]
    t, det = res["tally"], res["details"]
    viol = det.get("blank_violation", [])
    made_up = [r for r in viol if fields[r[0]]["verdict"] == "blank_no_data"]
    by_rule = [r for r in viol if fields[r[0]]["verdict"] == "blank_by_rule"]
    unresolved = []
    for u in key["_meta"].get("unresolved_expected", []):
        if u["form"] != form:
            continue
        got = printed.get(u["field"], "")
        unresolved.append((u["field"], u["what"], "BLANK (correct)" if SFF.blank(got) else f"ANSWERED {got!r} (wrong)"))
    return {"n_expect": len(key["expect"][form]), "correct": t["correct"], "exact": t["correct_exact"],
            "code": t["correct_code"], "meaning": t["correct_meaning"], "wrong": t["wrong"],
            "partial": t["wrong_partial"], "missing": t["missing"], "made_up": len(made_up),
            "rule_breaks": len(by_rule), "forbidden": t["forbidden"], "shape": t["shape"],
            "leaks": t["overflow_leak"], "rows": rows, "unresolved": unresolved,
            "detail": {"wrong": det.get("wrong", []), "missing": det.get("missing", []),
                       "made_up": made_up, "rule_breaks": by_rule,
                       "forbidden": det.get("forbidden", []), "shape": det.get("shape", []),
                       "leaks": det.get("overflow_leak", []), "meaning": det.get("correct_meaning", [])}}


def report(key: dict, results: dict, label: str) -> str:
    o = [f"# {label}", "", f"Kit: {key['_meta']['kit']}  ", f"Document: `{key['_doc']}` - "
         f"{key['_meta'].get('characters', 0):,} characters, {key['_meta'].get('pages', '?')} pages", ""]
    o += ["| form | correct | wrong | missing | made up | rule breaks | forbidden | shape | leaks | "
          "accuracy of what it filled | coverage |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for form, g in results.items():
        filled = g["correct"] + g["wrong"]
        acc = f"{100 * g['correct'] / filled:.1f}%" if filled else "-"
        cov = f"{100 * g['correct'] / g['n_expect']:.1f}%" if g["n_expect"] else "-"
        o.append(f"| {form} | {g['correct']} / {g['n_expect']} | {g['wrong']} | {g['missing']} | "
                 f"{g['made_up']} | {g['rule_breaks']} | {g['forbidden']} | {g['shape']} | {g['leaks']} | "
                 f"{acc} | {cov} |")
    o.append("")
    for form, g in results.items():
        o += [f"## {form}", "", f"Correct {g['correct']} (exact {g['exact']}, code {g['code']}, by meaning "
              f"{g['meaning']}); wrong {g['wrong']} ({g['partial']} partial).", ""]
        if g["unresolved"]:
            o += ["**Blank is not No - the questions the insured never answered:**", ""]
            o += [f"- `{f}` ({w}): {v}" for f, w, v in g["unresolved"]]
            o.append("")
        if g["rows"]:
            o += ["| group | slots used | cells right | cross-row | ungrounded |", "|---|---|---|---|---|"]
            for r in g["rows"]:
                o.append(f"| {r['group']} | {r['slots_used']}/{r['slots']} | {r['cells_correct']}/"
                         f"{r['cells_expected']} | {r['cross_row']} | {r['orphan']} |")
            o.append("")
        fb = key["fields_by_form"][form]
        for bucket, title in (("wrong", "WRONG"), ("made_up", "MADE UP"), ("rule_breaks", "RULE BREAKS"),
                              ("forbidden", "FORBIDDEN (a decoy in its trap box)"), ("shape", "SHAPE"),
                              ("leaks", "LEAKS"), ("missing", "MISSING")):
            items = g["detail"][bucket]
            if not items:
                continue
            o += [f"### {title} ({len(items)})", ""]
            for row in items:
                field, want, got = row[0], row[1], row[2] if len(row) > 2 else ""
                why = fb.get(field, {}).get("why", "") or fb.get(field, {}).get("trap", "")
                o.append(f"- `{field}` - expected {want!r}" + (f", printed {got!r}" if got else "")
                         + (f" - {why}" if why else ""))
            o.append("")
    return "\n".join(o) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session")
    ap.add_argument("--dump", help="JSON: {form_id: {field: value}} or a dump_a125_run file")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--label", default="CH125 RUN")
    ap.add_argument("--out")
    a = ap.parse_args()
    key = json.loads(KEY.read_text(encoding="utf-8"))
    if a.list:
        asyncio.run(_list())
        return 0
    if a.self_test:
        for name, stamped in (("PERFECT", {f: dict(key["expect"][f]) for f in key["_forms"]}),
                              ("EMPTY", {f: {} for f in key["_forms"]})):
            res = {f: grade_form(key, f, stamped[f]) for f in key["_forms"]}
            for f, g in res.items():
                print(f"{name:8} {f}: correct {g['correct']}/{g['n_expect']} wrong {g['wrong']} "
                      f"made-up {g['made_up']} rule-breaks {g['rule_breaks']} forbidden {g['forbidden']}")
        return 0
    if a.session:
        forms = asyncio.run(_load(a.session))
    elif a.dump:
        d = json.loads(Path(a.dump).read_text(encoding="utf-8"))
        forms = {"ACORD_125": d["stamped"]} if "stamped" in d else d
    else:
        ap.error("--session, --dump, --list or --self-test")
    results = {f: grade_form(key, f, forms.get(f) or {}) for f in key["_forms"] if f in forms}
    missing = [f for f in key["_forms"] if f not in forms]
    if missing:
        print(f"  not generated in this run: {', '.join(missing)}")
    text = report(key, results, a.label)
    print(text)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"  wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
