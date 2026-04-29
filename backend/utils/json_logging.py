import json
import logging
import traceback
from contextvars import ContextVar
from datetime import datetime, timezone

# Per-request trace ID — set by TraceIDMiddleware, defaults to "-" outside a request.
_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")


def get_trace_id() -> str:
    return _trace_id_var.get()


def set_trace_id(trace_id: str) -> None:
    _trace_id_var.set(trace_id)


class JsonFormatter(logging.Formatter):
    """One JSON object per log record; injects trace_id from the ContextVar."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts":       datetime.now(timezone.utc).isoformat(),
            "level":    record.levelname,
            "logger":   record.name,
            "trace_id": _trace_id_var.get(),
            "msg":      record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = traceback.format_exception(*record.exc_info)
        return json.dumps(payload)
