"""Simple trace span context manager."""

import time
from contextlib import contextmanager
from datetime import datetime, timezone

from .ids import new_id

_trace_log: list[dict] = []


@contextmanager
def trace_span(
    agent: str,
    kind: str,
    session_id: str = "",
    parent_id: str | None = None,
    **kwargs,
):
    started = time.monotonic()
    span = {
        "id": new_id("tr"),
        "session_id": session_id,
        "agent": agent,
        "kind": kind,
        "parent_id": parent_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "ok",
        "payload": kwargs,
    }
    try:
        yield span
    except Exception as e:
        span["status"] = "error"
        span["payload"]["error"] = str(e)
        raise
    finally:
        elapsed = time.monotonic() - started
        span["ended_at"] = datetime.now(timezone.utc).isoformat()
        span["latency_ms"] = int(elapsed * 1000)
        _trace_log.append(span)


def get_traces() -> list[dict]:
    return _trace_log


def flush_traces() -> list[dict]:
    traces = list(_trace_log)
    _trace_log.clear()
    return traces
