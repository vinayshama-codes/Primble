"""A connection URL carries its password, so it never reaches a log line.

Live Render log, 1 Nov 2026: `progress_tracker: Redis connected (rediss://default:...)`.
Walks every logging call in the backend's own code, so a new one is caught too.
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SECRET_URLS = ("REDIS_URL", "DATABASE_URL")
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}


def _secret_url_log_lines(path):
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in LOG_METHODS):
            continue
        owner = node.func.value
        if not (isinstance(owner, ast.Name) and owner.id in ("logger", "logging", "log", "_logger")):
            continue
        for arg in node.args:
            for sub in ast.walk(arg):
                if isinstance(sub, ast.Name) and any(s in sub.id for s in SECRET_URLS):
                    found.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return found


def test_no_log_line_prints_a_connection_url():
    found = []
    for folder in ("config", "routes", "services", "utils", "repositories"):
        for path in (ROOT / folder).rglob("*.py"):
            found += _secret_url_log_lines(path)
    for name in ("main.py", "worker.py"):
        if (ROOT / name).exists():
            found += _secret_url_log_lines(ROOT / name)
    assert not found, found
