"""Tests for the rate-limiting / retry module."""

import os
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from agent import ratelimit
from agent.ratelimit import (
    backoff_seconds,
    is_transient,
    wait_for_rate_limit,
    with_retries,
    with_retries_stream,
)


class Fake429Error(Exception):
    code = 429


class Fake500Error(Exception):
    status_code = 500


class FakeHTTPResponse:
    status_code = 503


class FakeHttpxError(Exception):
    response = FakeHTTPResponse()


class FakeFatalError(Exception):
    pass


def test_wait_for_rate_limit_rpm_cap(monkeypatch):
    monkeypatch.setattr(ratelimit, "_llm_section", lambda: {
        "rpm": 2, "min_interval": 0.0, "max_retries": 0, "backoff_base": 0.0,
    })
    ratelimit._recent_calls.clear()
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    wait_for_rate_limit()
    wait_for_rate_limit()
    assert sleeps == []  # two calls fit under rpm=2
    wait_for_rate_limit()  # third must wait
    assert len(sleeps) == 1


def test_wait_for_rate_limit_min_interval(monkeypatch):
    monkeypatch.setattr(ratelimit, "_llm_section", lambda: {
        "rpm": 100, "min_interval": 5.0, "max_retries": 0, "backoff_base": 0.0,
    })
    # Pretend a call just happened
    ratelimit._recent_calls.clear()
    ratelimit._recent_calls.append(time.monotonic())
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    wait_for_rate_limit()
    assert len(sleeps) == 1
    assert sleeps[0] > 0


def test_is_transient_status_codes():
    assert is_transient(Fake429Error())
    assert is_transient(Fake500Error())
    assert is_transient(FakeHttpxError())
    assert not is_transient(FakeFatalError())


def test_is_transient_message():
    class WeirdError(Exception):
        pass

    assert is_transient(WeirdError("Rate limit exceeded"))
    assert is_transient(WeirdError("temporarily unavailable"))
    assert not is_transient(WeirdError("some other problem"))


def test_backoff_grows_exponentially():
    base = 1.0
    delays = [backoff_seconds(i, base, jitter=False) for i in range(4)]
    assert delays[0] == 1.0
    assert delays[1] == 2.0
    assert delays[2] == 4.0
    assert delays[3] == 8.0


def test_with_retries_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(ratelimit, "_llm_section", lambda: {
        "rpm": 1000, "min_interval": 0.0, "max_retries": 3, "backoff_base": 0.0,
    })
    monkeypatch.setattr(time, "sleep", lambda s: None)

    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise Fake429Error()
        return "ok"

    assert with_retries(flaky) == "ok"
    assert calls["n"] == 3


def test_with_retries_exhausts_and_raises(monkeypatch):
    monkeypatch.setattr(ratelimit, "_llm_section", lambda: {
        "rpm": 1000, "min_interval": 0.0, "max_retries": 2, "backoff_base": 0.0,
    })
    monkeypatch.setattr(time, "sleep", lambda s: None)

    def always_fails():
        raise Fake500Error()

    with pytest.raises(Fake500Error):
        with_retries(always_fails)


def test_with_retries_does_not_retry_fatal(monkeypatch):
    monkeypatch.setattr(ratelimit, "_llm_section", lambda: {
        "rpm": 1000, "min_interval": 0.0, "max_retries": 3, "backoff_base": 0.0,
    })
    calls = {"n": 0}

    def fatal():
        calls["n"] += 1
        raise FakeFatalError()

    with pytest.raises(FakeFatalError):
        with_retries(fatal)
    assert calls["n"] == 1


def test_with_retries_stream_retries_on_first_item(monkeypatch):
    monkeypatch.setattr(ratelimit, "_llm_section", lambda: {
        "rpm": 1000, "min_interval": 0.0, "max_retries": 2, "backoff_base": 0.0,
    })
    monkeypatch.setattr(time, "sleep", lambda s: None)

    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        if calls["n"] == 1:
            raise Fake429Error()
        return iter([1, 2, 3])

    result = list(with_retries_stream(factory))
    assert result == [1, 2, 3]
    assert calls["n"] == 2


def test_with_retries_stream_mid_stream_error_not_retried(monkeypatch):
    monkeypatch.setattr(ratelimit, "_llm_section", lambda: {
        "rpm": 1000, "min_interval": 0.0, "max_retries": 2, "backoff_base": 0.0,
    })
    calls = {"n": 0}

    def gen():
        calls["n"] += 1
        yield "first"
        raise Fake500Error()

    with pytest.raises(Fake500Error):
        for item in with_retries_stream(lambda: gen()):
            assert item == "first"
    assert calls["n"] == 1  # not retried mid-stream
