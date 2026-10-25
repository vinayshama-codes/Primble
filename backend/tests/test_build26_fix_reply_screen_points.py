"""Every pre-form fix reply carries the screen's points, like a page load
(owner's live run 715b3c8f, 23 Oct 2026: the "upload loss runs" rows vanished
after each answer because the fix reply's shortcut skipped
`complete_screen_shares`)."""
import ast, asyncio, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

_SRC = os.path.join(os.path.dirname(__file__), "..", "routes", "audit_routes.py")


def _fn(name):
    tree = ast.parse(open(_SRC).read())
    for n in ast.walk(tree):
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == name:
            return ast.get_source_segment(open(_SRC).read(), n)
    raise AssertionError(name)


def test_the_fix_reply_shortcut_adds_the_screen_points():
    src = _fn("_pre_form_readiness")
    short = src.split("from routes.form_routes import _pre_form_status")[0]
    assert "complete_screen_shares" in short


def test_the_answer_reply_goes_through_the_same_helper_before_forms():
    assert "_pre_form_readiness(" in _fn("answer_recommendation")


def test_the_shortcut_reply_carries_screen_fields(monkeypatch):
    import routes.audit_routes as ar
    import services.sqs_service as sq
    monkeypatch.setattr(sq, "is_pre_form_session", lambda s: True)
    seen = {}
    def fake(sess, sid, uid, pkg, kd):
        seen["called"] = True
        return {**pkg, "screen_shares": {}, "screen_unanswerable": [{"label": "x", "points": 4}]}, kd
    monkeypatch.setattr(sq, "complete_screen_shares", fake)
    import routes.form_routes as fr
    async def no_dry(*a, **k):
        return None
    monkeypatch.setattr(fr, "_pre_form_dry_run", no_dry)
    sess = {"facts": {}, "flags": {}, "user_id": "u1"}
    card = asyncio.run(ar._pre_form_readiness(sess, "s1", {"id": "u1"},
                                              scored={"package_sqs_score": 94}))
    assert seen.get("called") and card["package_sqs"]["screen_unanswerable"][0]["points"] == 4
