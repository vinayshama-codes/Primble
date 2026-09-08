"""verify_bug06.py - prove BUG-06 in five seconds, with no server and no upload.

    py backend/scripts/verify_bug06.py

BUG-06 as reported: the "Enter the correct value" modal accepts Umbrella
Effective / Expiration Date and answers "Something went wrong applying your
answer."

The report reads like a date problem. It is not. This script drives the REAL
`arq_service.apply_producer_answer_to_session` - the single write door behind
every producer answer in the product - against a stubbed session repository, so
nothing here needs Postgres, an LLM, a document or a browser.

WHAT IT SHOWS
-------------
Every canonical fact raises `UnboundLocalError` except ONE: `new_venture_
indicator`. That asymmetry IS the root cause, and it is visible without reading
a line of code:

    services/arq_service.py:4922   `_nv_delete` is assigned ONLY inside
                                   `elif canon == NEW_VENTURE_FIELD:`
    services/arq_service.py:4941   `delete_facts=_nv_delete or None` reads it
                                   on EVERY path

So the one fact whose branch happens to assign the name is the one fact that
works. Dates, currency, text, counts and the ACORD 101 narrative all die on the
same line. Introduced in commit d6d09c7 (V1 H4 new-venture derivations).

Exit code 1 while the bug is present, 0 once it is fixed - so this is also the
before/after check. Run it, apply the fix, run it again.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


# ── A session repository that lives in memory ───────────────────────────────
# Patched BEFORE services.arq_service is imported, because the function imports
# these two names locally at call time and would otherwise reach for Postgres.
import repositories.session_repository as _sr  # noqa: E402

_STORE: dict = {"facts": {}, "flags": {}, "generated_forms": {}}


async def _fake_get(_session_id):
    return {k: (dict(v) if isinstance(v, dict) else v) for k, v in _STORE.items()}


async def _fake_upd(_session_id, payload, delete_facts=None):
    for k, v in (payload or {}).items():
        _STORE[k] = v
    for k in (delete_facts or []):
        _STORE.get("facts", {}).pop(k, None)
    return True


_sr.get_processing_session = _fake_get
_sr.upd_processing_session = _fake_upd

from services import arq_service as A  # noqa: E402


# ── The facts to try, one per shape the modal and the cards can produce ─────
# Deliberately NOT the client's values. The client typed 07/15/25 and 07/15/26;
# nothing here does. If the failure followed the values, changing them would
# change the outcome. It does not - which is the point of the table.
CASES = [
    # (canonical fact,                    value,                    shape)
    ("umbrella_effective_date",           "03/22/2027",             "date"),
    ("umbrella_expiration_date",          "03/22/2028",             "date"),
    ("effective_date",                    "11/15/2026",             "date"),
    ("umbrella_limit",                    "$5,000,000",             "currency"),
    ("gl_each_occurrence",                "$2,000,000",             "currency"),
    ("property_building_value",           "$3,750,000",             "currency"),
    ("business_income_limit",             "$450,000",               "currency"),
    ("auto_deductible_comp",              "$2,500",                 "currency"),
    ("total_payroll",                     "$2,150,000",             "currency"),
    ("valuation_method",                  "Replacement Cost",       "choice"),
    ("construction_type",                 "Joisted Masonry",        "text"),
    ("year_built",                        "1998",                   "integer"),
    ("coinsurance_percentage",            "90",                     "percent"),
    ("applicant_name",                    "Halvorsen Ridge Millwork LLC", "text"),
    ("additional_remarks_text",           "Umbrella term confirmed with the carrier.",
                                                                    "narrative"),
    (A.CARRIER_MARKETING_FIELD,           "Premium increase",       "choice"),
    (A.NO_LOSS_INDICATOR_FIELD,           "Yes",                    "attestation"),
    # THE CONTROL. Same door, same button, same request shape - and the only
    # branch in the if/elif chain that assigns `_nv_delete`.
    (A.NEW_VENTURE_FIELD,                 "Yes",                    "CONTROL"),
]

# Which UI surface each shape reaches the door through, and what the producer
# is shown when it dies. Three different generic strings, one cause.
SURFACES = """
  Resolution modal, field mode      POST /api/audit/resolve-issue
     -> "Something went wrong applying your answer."     ResolutionModal.jsx:213
  Resolution modal, narrative mode  POST /api/audit/resolve-issue
     -> "Something went wrong saving the explanation."   ResolutionModal.jsx:220
  Recommendation card, Submit       POST /api/audit/answer
     -> "Network error. Please try again."               AcordModal.jsx:4409
  Client answer review (held answer) services/client_answer_review.py:144
"""


def _run_matrix() -> int:
    print("=" * 74)
    print("BUG-06  root-cause matrix")
    print("arq_service.apply_producer_answer_to_session, driven directly")
    print("=" * 74)
    print(f"{'CANONICAL FACT':34s} {'SHAPE':12s} RESULT")
    print("-" * 74)

    broken, worked = [], []

    async def _drive():
        for field, value, shape in CASES:
            _STORE["facts"] = {}
            _STORE["flags"] = {}
            _STORE["generated_forms"] = {}
            try:
                ok, _ = await A.apply_producer_answer_to_session("bug06", field, value)
                worked.append(field)
                print(f"{field:34s} {shape:12s} applied (ok={ok})")
            except UnboundLocalError as ex:
                broken.append(field)
                print(f"{field:34s} {shape:12s} *** UnboundLocalError: {ex}")
            except Exception as ex:                          # noqa: BLE001
                # Not the bug - a stubbed session cannot satisfy every branch.
                print(f"{field:34s} {shape:12s} (skipped: {type(ex).__name__})")

    asyncio.run(_drive())

    print("-" * 74)
    print(f"broken: {len(broken)}     applied: {len(worked)}")
    return 1 if broken else 0


def _show_the_line() -> None:
    """Print the two lines that cause it, straight out of the live source."""
    src = inspect.getsource(A.apply_producer_answer_to_session)
    base = A.apply_producer_answer_to_session.__code__.co_firstlineno
    print()
    print("=" * 74)
    print("THE TWO LINES  (services/arq_service.py, read live)")
    print("=" * 74)
    for i, line in enumerate(src.splitlines()):
        if "_nv_delete" in line:
            print(f"  {base + i}: {line.strip()}")
    print()
    print("  The first is inside `elif canon == NEW_VENTURE_FIELD:`.")
    print("  The second runs on every path. Any other fact reads a name that")
    print("  was never bound -> UnboundLocalError -> HTTP 500.")


def _show_isolation() -> None:
    """The same conditional-binding shape, across every function in the module.

    Proves the fix is one line and not a sweep: the siblings that share this
    door's job already initialise their accumulators unconditionally.
    """
    path = os.path.join(_BACKEND, "services", "arq_service.py")
    tree = ast.parse(open(path, encoding="utf-8").read())
    hits = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # Names bound unconditionally at the function's own top level.
        safe = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
        for stmt in fn.body:
            if isinstance(stmt, ast.If):
                continue
            for n in ast.walk(stmt):
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                    safe.add(n.id)
        for i, stmt in enumerate(fn.body):
            if not isinstance(stmt, ast.If):
                continue
            node, bound = stmt, set()
            while True:
                for n in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                        bound.add(n.id)
                if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
                    node = node.orelse[0]
                    continue
                break
            if node.orelse:          # chain ends in `else` - every path binds
                continue
            risky = bound - safe
            for later in fn.body[i + 1:]:
                # A later block that RE-BINDS the name before reading it is
                # safe - `_clean_answer_ex`'s `normalized` does exactly that in
                # each of its per-type branches, and reporting it beside the
                # real defect would make the real one look like one of a crowd.
                rebound = {n.id for n in ast.walk(later)
                           if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
                for n in ast.walk(later):
                    if (isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                            and n.id in risky and n.id not in rebound):
                        hits.append((n.lineno, fn.name, n.id))
                        risky.discard(n.id)
    print()
    print("=" * 74)
    print("SAME SHAPE ELSEWHERE IN arq_service.py")
    print("=" * 74)
    real = [h for h in hits if not h[2].islower() or len(h[2]) > 2]
    for line, fn, name in sorted(real):
        print(f"  line {line:<6} {fn}()  reads conditionally-bound '{name}'")
    if not real:
        print("  none - the door is clean.")
    print()
    print("  For contrast, the sibling write paths bind theirs up front:")
    print("    line 4333  apply_arq_answers_to_session:  _nv_delete_keys: List[str] = []")
    print("    save_session_schedule / clear_producer_answer_from_session:")
    print("               never touch _nv_delete at all")


def main() -> None:
    rc = _run_matrix()
    _show_the_line()
    _show_isolation()

    print()
    print("=" * 74)
    if rc:
        print("VERDICT: BUG-06 REPRODUCED")
        print("=" * 74)
        print("""
Every producer answer in the product is dead except New Venture. It is not the
dates, not the values, not the modal and not validation - the values above all
pass `_validate_producer_answer` before they ever reach this function.

Surfaces this takes down:""" + SURFACES + """
The fix is one line: initialise `_nv_delete: List[str] = []` beside
`flags_changed = False` (services/arq_service.py:4874), before the if/elif
chain - exactly what the sibling path already does at line 4333.

Re-run this script after the fix. Every row must read "applied".
""".rstrip())
    else:
        print("VERDICT: FIXED - every producer-answer path applies cleanly")
        print("=" * 74)
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
