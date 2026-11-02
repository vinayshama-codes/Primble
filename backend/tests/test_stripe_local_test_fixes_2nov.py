"""Defects found by the local test on the test Stripe account (2 Nov 2026).

LT-1: a cancel from Stripe's billing portal sets `cancel_at` (a date) and leaves
`cancel_at_period_end` false. Every reader must ask `stripe_service.is_ending`,
never the flag alone - or a cancelled plan reads as "ok", never "canceling".
"""
import ast
import os

from services.stripe_service import is_ending

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_LT1_a_portal_cancel_date_is_ending():
    # The shape the portal produced on the test account.
    assert is_ending({"cancel_at_period_end": False, "cancel_at": 1801576790})


def test_LT1_the_flag_alone_is_still_ending():
    assert is_ending({"cancel_at_period_end": True, "cancel_at": None})


def test_LT1_neither_is_not_ending():
    assert not is_ending({"cancel_at_period_end": False, "cancel_at": None})
    assert not is_ending({})
    assert not is_ending(None)


def test_LT1_a_stripe_object_reads_the_same():
    class Sub(dict):
        pass
    assert is_ending(Sub(cancel_at_period_end=False, cancel_at=1801576790))


def test_LT2_a_sign_in_loads_the_full_account():
    """The sign-in responses carry no package numbers; the app must load the
    full account (/api/auth/me) right after any sign-in, not wait for a reload."""
    src = open(os.path.join(BACKEND, "..", "frontend", "src", "hooks", "useAuth.js")).read()
    start = src.index("const login = (usr) =>")
    body = src[start:src.index("};", start)]
    assert "fetchCurrentUser()" in body and "setUser(full)" in body


def test_LT3_an_essentials_score_refreshes_the_usage_shown():
    """The lite (Essentials) score is counted by the server; the screen must
    reload the account after it, or the plan panel shows the old count."""
    src = open(os.path.join(BACKEND, "..", "frontend", "src", "components", "form", "AcordModal.jsx")).read()
    start = src.index("api/lite/generate-internal/")
    block = src[start:src.index(".finally(", start)]
    assert "setLiteSqsData(d);" in block and "refreshUser()" in block


def test_LT3_counting_clears_the_cached_account():
    """/me for a paying user is cached 30 s (and the auth user 30 s): a counted
    package must clear both, or the refresh after it shows the old usage."""
    src = open(os.path.join(BACKEND, "services", "usage_service.py")).read()
    body = src[src.index("async def count_session_usage("):src.index("async def _evaluate_counted(")]
    claimed_gate = body.index("        if not claimed:\n")
    clear = body.index("invalidate_user_cache(")
    first_return_after = body.index('return {"counted": True', claimed_gate)
    assert claimed_gate < clear < first_return_after


def test_LT4_the_essentials_score_is_the_package_score():
    """The Essentials run scores the PACKAGE through the one package scorer and
    saves it, like the full generation - never leaving its screen to show the
    ACORD form's own score while the dashboard shows the package's."""
    src = open(os.path.join(BACKEND, "routes", "form_routes.py")).read()
    start = src.index("async def lite_generate_internal(")
    body = src[start:src.index("def _lite_score_response(", start)]
    assert "calculate_package_sqs," in body and 'calculation_stage="form_generated"' in body
    assert 'hard_stops=_lite_stops["hard"]' in body and 'soft_stops=_lite_stops["soft"]' in body
    assert '{"package_sqs": package_sqs}' in body and "if package_sqs:" in body


def _flag_reads(path):
    """Places that READ the cancel flag off a Stripe object (`x.get(...)`,
    `field(x, ...)`, `x["..."]`) - writing it to Stripe is not a read."""
    tree = ast.parse(open(path).read())
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else "")
            if name in ("get", "field") and any(
                    isinstance(a, ast.Constant) and a.value == "cancel_at_period_end" for a in node.args):
                hits.append(node.lineno)
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                and node.slice.value == "cancel_at_period_end":
            hits.append(node.lineno)
    return hits


def test_LT1_no_reader_asks_the_flag_alone():
    svc = os.path.join(BACKEND, "services", "stripe_service.py")
    src = open(svc).read().splitlines()
    ending = next(i for i, ln in enumerate(src, 1) if ln.startswith("def is_ending"))
    allowed = set(range(ending, ending + 8))
    offenders = []
    for rel in ("services/stripe_service.py", "routes/stripe_routes.py"):
        for line in _flag_reads(os.path.join(BACKEND, rel)):
            if rel == "services/stripe_service.py" and line in allowed:
                continue
            offenders.append(f"{rel}:{line}")
    # Reading the state dict our own helpers return (built by is_ending) is fine.
    routes = open(os.path.join(BACKEND, "routes", "stripe_routes.py")).read().splitlines()
    offenders = [o for o in offenders
                 if not ("stripe_routes" in o and "state.get(" in routes[int(o.split(":")[1]) - 1])]
    assert not offenders, f"read the cancel flag through is_ending: {offenders}"
