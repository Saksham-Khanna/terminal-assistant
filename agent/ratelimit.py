"""
Rate limiting and retry-with-backoff for LLM API calls.

Free-tier providers (Gemini / Groq) enforce requests-per-minute limits and
throw transient 429 (rate limit) or 5xx errors under load. This module:
  * throttles outgoing calls to a configured RPM + minimum gap (thread-safe)
  * retries transient failures with exponential backoff + jitter
  * is provider-agnostic, so all LLM call sites can share it

Config (via agentic.toml ``[llm]`` section or env vars):
  LLM_RATE_RPM        max requests per minute (default 15)
  LLM_MIN_INTERVAL    min seconds between successive calls (default 0.5)
  LLM_MAX_RETRIES     retries for transient errors (default 3)
  LLM_RETRY_BACKOFF   base seconds for exponential backoff (default 1.0)
"""

import os
import random
import threading
import time

from agent.config import get_config

_lock = threading.Lock()
_recent_calls: list[float] = []

TRANSIENT_STATUSES = {408, 429, 500, 502, 503, 504}


def _llm_section() -> dict:
    section = get_config().section("llm") or {}
    return {
        "rpm": int(os.environ.get("LLM_RATE_RPM", section.get("rpm", 15))),
        "min_interval": float(
            os.environ.get("LLM_MIN_INTERVAL", section.get("min_interval", 0.5))
        ),
        "max_retries": int(os.environ.get("LLM_MAX_RETRIES", section.get("max_retries", 3))),
        "backoff_base": float(
            os.environ.get("LLM_RETRY_BACKOFF", section.get("backoff_base", 1.0))
        ),
    }


def wait_for_rate_limit() -> None:
    """Block the calling thread until a new call is within the allowed budget.

    Tracks calls process-wide so the CLI and web UI share the same budget.
    """
    cfg = _llm_section()
    rpm = max(1, cfg["rpm"])
    min_interval = max(0.0, cfg["min_interval"])
    window = 60.0

    with _lock:
        now = time.monotonic()
        # Drop calls older than the window
        while _recent_calls and _recent_calls[0] <= now - window:
            _recent_calls.pop(0)

        # If we've hit the RPM cap, wait until the oldest call falls out.
        gap = 0.0
        if len(_recent_calls) >= rpm:
            gap = max(gap, _recent_calls[0] + window - now)
        if _recent_calls:
            gap = max(gap, min_interval - (now - _recent_calls[-1]))

    if gap > 0:
        time.sleep(gap)

    with _lock:
        _recent_calls.append(time.monotonic())


def _status_of(exc: BaseException) -> int | None:
    """Extract an HTTP-style status code from a wide range of exceptions."""
    for attr in ("code", "status_code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    if response is not None:
        value = getattr(response, "status_code", None)
        if isinstance(value, int):
            return value
    return None


def is_transient(exc: BaseException) -> bool:
    """True if the error is a transient rate-limit / server error to retry."""
    status = _status_of(exc)
    if status is not None:
        return status in TRANSIENT_STATUSES
    message = str(exc)
    markers = (
        "rate limit", "too many requests", "resource_exhausted",
        "temporarily unavailable", "timeout", "timed out", "connection",
        "server error",
    )
    return any(marker in message.lower() for marker in markers)


def backoff_seconds(attempt: int, base: float = 1.0, jitter: bool = True) -> float:
    """Exponential backoff: ``base * 2**attempt`` plus optional jitter."""
    delay = base * (2 ** attempt)
    if jitter:
        delay += random.uniform(0, 0.5)
    return delay


def with_retries(fn, *args, **kwargs):
    """Call ``fn(*args, **kwargs)`` with rate limiting, and retry with backoff.

    Re-raises the last exception once retries are exhausted, or immediately
    for non-transient errors. Every attempt (including the first) passes
    through ``wait_for_rate_limit`` so backoff attempts are throttled too.
    """
    cfg = _llm_section()
    max_retries = max(0, cfg["max_retries"])
    base = max(0.0, cfg["backoff_base"])

    attempt = 0
    while True:
        wait_for_rate_limit()
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - must catch any provider error
            if attempt >= max_retries or not is_transient(exc):
                raise
            delay = backoff_seconds(attempt, base)
            status = _status_of(exc) or type(exc).__name__
            print(f"  [llm] transient error ({status}), retrying in {delay:.1f}s "
                  f"({attempt + 1}/{max_retries})", flush=True)
            time.sleep(delay)
            attempt += 1


def with_retries_stream(factory, *args, **kwargs):
    """Retry a streaming call, but only until the first item is produced.

    ``factory(*args, **kwargs)`` must return an iterator/generator. Establishing
    the connection is retried with backoff (i.e. pulling the *first* item can be
    retried safely); once data starts flowing, errors propagate immediately
    because retrying mid-stream could duplicate or reorder earlier output.
    """
    cfg = _llm_section()
    max_retries = max(0, cfg["max_retries"])
    base = max(0.0, cfg["backoff_base"])

    attempt = 0
    while True:
        wait_for_rate_limit()
        try:
            iterator = iter(factory(*args, **kwargs))
            first = next(iterator)
        except StopIteration:
            return
        except Exception as exc:  # noqa: BLE001 - must catch any provider error
            if attempt >= max_retries or not is_transient(exc):
                raise
            delay = backoff_seconds(attempt, base)
            status = _status_of(exc) or type(exc).__name__
            print(f"  [llm] transient error ({status}), retrying in {delay:.1f}s "
                  f"({attempt + 1}/{max_retries})", flush=True)
            time.sleep(delay)
            attempt += 1
            continue
        yield first
        yield from iterator
        return
