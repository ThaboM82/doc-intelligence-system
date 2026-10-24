"""
Periodic Pushgateway export when PROMETHEUS_PUSHGATEWAY_URL is set.

Start from FastAPI lifespan; no-op if URL is unset.

Env
---
  PROMETHEUS_PUSHGATEWAY_URL       e.g. http://pushgateway:9091
  PROMETHEUS_PUSH_INTERVAL_SEC     default 60 (min 15)
  PROMETHEUS_PUSH_ON_START         true = push once immediately (default true)
  PROMETHEUS_PUSH_JOB              job label (read by push_metrics)
  PROMETHEUS_PUSH_INSTANCE         instance label (read by push_metrics)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None
_started_at: float | None = None
_last_push_at: float | None = None
_last_ok: bool | None = None
_last_error: str | None = None
_push_count: int = 0
_error_count: int = 0
_lock = asyncio.Lock()


def _interval_sec() -> int:
    try:
        return max(15, int(os.getenv("PROMETHEUS_PUSH_INTERVAL_SEC", "60")))
    except ValueError:
        return 60


def _push_on_start() -> bool:
    return os.getenv("PROMETHEUS_PUSH_ON_START", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def push_loop_enabled() -> bool:
    """True when a Pushgateway URL is configured."""
    return bool((os.getenv("PROMETHEUS_PUSHGATEWAY_URL") or "").strip())


def get_push_loop_status() -> dict[str, Any]:
    """Ops snapshot for /health, /ready, or admin diagnostics."""
    running = _task is not None and not _task.done()
    return {
        "enabled": push_loop_enabled(),
        "running": running,
        "interval_sec": _interval_sec() if push_loop_enabled() else None,
        "push_on_start": _push_on_start(),
        "started_at": _started_at,
        "last_push_at": _last_push_at,
        "last_ok": _last_ok,
        "last_error": _last_error,
        "push_count": _push_count,
        "error_count": _error_count,
        "gateway": (os.getenv("PROMETHEUS_PUSHGATEWAY_URL") or "").rstrip("/")
        or None,
        "job": os.getenv("PROMETHEUS_PUSH_JOB", "doc-intelligence-api"),
        "instance": os.getenv("PROMETHEUS_PUSH_INSTANCE") or None,
    }


async def push_once() -> bool:
    """
    Single async push (usable outside the loop).
    Returns True if push_metrics reported success.
    """
    global _last_push_at, _last_ok, _last_error, _push_count, _error_count

    async with _lock:
        try:
            from backend.observability.metrics import (
                push_metrics,
                push_metrics_enabled,
            )

            if not push_metrics_enabled():
                _last_ok = False
                _last_error = "push_metrics_enabled=false"
                _last_push_at = time.time()
                return False

            ok = await asyncio.to_thread(push_metrics)
            _last_push_at = time.time()
            _last_ok = bool(ok)
            if ok:
                _push_count += 1
                _last_error = None
            else:
                _error_count += 1
                _last_error = "push_metrics returned False"
            return bool(ok)
        except Exception as exc:
            _error_count += 1
            _last_ok = False
            _last_error = str(exc)[:300]
            _last_push_at = time.time()
            logger.debug("push_once failed: %s", exc)
            return False


async def _loop() -> None:
    interval = _interval_sec()
    if _push_on_start():
        await push_once()
    while True:
        await asyncio.sleep(interval)
        await push_once()


def start_push_loop() -> bool:
    """
    Idempotent start; no-op if gateway URL unset.
    Returns True if the background task is running (started or already active).
    """
    global _task, _started_at

    if not push_loop_enabled():
        logger.debug("Pushgateway URL not set; push loop disabled")
        return False

    if _task is not None and not _task.done():
        return True

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("start_push_loop: no running event loop")
        return False

    _task = loop.create_task(_loop(), name="prometheus-push-loop")
    _started_at = time.time()
    logger.info(
        "Pushgateway loop started → %s every %ss (on_start=%s)",
        (os.getenv("PROMETHEUS_PUSHGATEWAY_URL") or "").rstrip("/"),
        _interval_sec(),
        _push_on_start(),
    )
    return True


async def stop_push_loop() -> None:
    """Cancel loop and attempt a final push."""
    global _task

    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("push loop stop: %s", exc)
        _task = None

    try:
        await push_once()
    except Exception:
        pass


def reset_push_loop_stats() -> None:
    """Test helper: clear counters (does not stop the loop)."""
    global _last_push_at, _last_ok, _last_error, _push_count, _error_count
    _last_push_at = None
    _last_ok = None
    _last_error = None
    _push_count = 0
    _error_count = 0


__all__ = [
    "start_push_loop",
    "stop_push_loop",
    "push_once",
    "push_loop_enabled",
    "get_push_loop_status",
    "reset_push_loop_stats",
]