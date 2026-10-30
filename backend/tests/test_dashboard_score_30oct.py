"""Live 6875e80c (30 Oct 2026): the page read 100, the dashboard kept 94.
Before forms the list reads the pre-form copy first, and every answer refreshes it."""
import inspect
from repositories import session_repository as sr
from routes import audit_routes as ar


def test_list_prefers_pre_form_copy_before_forms():
    src = inspect.getsource(sr.list_sessions_for_user)
    pre = src.index("THEN COALESCE((data->'pre_form_score'->>'package_sqs_score')::int")
    post = src.index("ELSE COALESCE((data->'package_sqs'->>'package_sqs_score')::int")
    assert pre < post
    assert "THEN data->'pre_form_score'->>'submission_ready'" in src


def test_every_answer_refreshes_the_dashboard_copy():
    src = inspect.getsource(ar._pre_form_readiness)
    assert "_remember_pre_form_score(session_id, sess, card[\"package_sqs\"])" in src
    assert "remember_score=True" in src
