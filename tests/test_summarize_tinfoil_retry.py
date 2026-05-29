"""Tests for the Tinfoil backend's transient-error retry (v0.9.2).

The Tinfoil SDK does a network fetch at client construction
(GET https://atc.tinfoil.sh/routers) and again for the completion call.
On hosts with flaky DNS, a single transient lookup failure used to
hard-fail confidential summarization.  _summarize_tinfoil now retries
transient network/DNS errors with backoff, while failing fast on real
auth/model errors.
"""
from __future__ import annotations

import socket
import sys
import types
import urllib.error

import pytest

import millet.summarize as sm
from millet.summarize import SummaryConfig, _is_transient_network_error


# ── classifier ──────────────────────────────────────────────────────────────


def test_classifier_flags_dns_gaierror():
    assert _is_transient_network_error(socket.gaierror(-2, "Name or service not known"))


def test_classifier_flags_sdk_wrapped_router_error():
    # The SDK wraps a URLError in ValueError("Failed to fetch router addresses…").
    inner = urllib.error.URLError("[Errno -2] Name or service not known")
    outer = ValueError(f"Failed to fetch router addresses: {inner}")
    outer.__cause__ = inner
    assert _is_transient_network_error(outer)


def test_classifier_rejects_auth_error():
    assert not _is_transient_network_error(RuntimeError("401 Unauthorized: bad api key"))
    assert not _is_transient_network_error(ValueError("model 'x' not found"))


# ── retry harness ────────────────────────────────────────────────────────────


def _install_fake_tinfoil(monkeypatch, behavior):
    """Install a fake ``tinfoil`` module whose TinfoilAI(...) runs ``behavior``
    (a callable taking the 1-based attempt number) and returns a fake
    completion response when it doesn't raise."""
    state = {"attempt": 0}

    class _Msg:
        content = "## Meeting Overview\n\nAll good."

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    class _Completions:
        def create(self, **kwargs):
            return _Resp()

    class _Chat:
        completions = _Completions()

    class FakeTinfoilAI:
        def __init__(self, api_key=None):
            state["attempt"] += 1
            behavior(state["attempt"])  # may raise
            self.chat = _Chat()

    mod = types.ModuleType("tinfoil")
    mod.TinfoilAI = FakeTinfoilAI
    monkeypatch.setitem(sys.modules, "tinfoil", mod)
    # Ensure an API key is "present" so we reach the network path.
    monkeypatch.setattr(sm, "_resolve_tinfoil_api_key", lambda: "tk_fake")
    # _summarize_tinfoil does ``import time`` then time.sleep(...) for
    # backoff — patch the stdlib time.sleep so tests don't actually wait.
    import time as _t
    monkeypatch.setattr(_t, "sleep", lambda *_a, **_k: None)
    return state


def test_retries_transient_then_succeeds(monkeypatch):
    def behavior(attempt):
        if attempt == 1:
            # First client init: simulate the SDK router-discovery DNS failure.
            raise ValueError(
                "Failed to fetch router addresses: <urlopen error "
                "[Errno -2] Name or service not known>"
            )
        # Second attempt succeeds.

    state = _install_fake_tinfoil(monkeypatch, behavior)
    cfg = SummaryConfig(backend="tinfoil", model="deepseek-v4-pro")
    result = sm._summarize_tinfoil("sys", "user", cfg)
    assert state["attempt"] == 2  # retried once
    assert "Meeting Overview" in result.markdown
    assert result.backend == "tinfoil"


def test_persistent_transient_fails_after_max_attempts(monkeypatch):
    def behavior(attempt):
        raise socket.gaierror(-2, "Name or service not known")

    state = _install_fake_tinfoil(monkeypatch, behavior)
    cfg = SummaryConfig(backend="tinfoil", model="deepseek-v4-pro")
    with pytest.raises(RuntimeError, match="unreachable after"):
        sm._summarize_tinfoil("sys", "user", cfg)
    assert state["attempt"] == sm._TINFOIL_MAX_ATTEMPTS  # all attempts used


def test_auth_error_fails_fast_no_retry(monkeypatch):
    def behavior(attempt):
        raise RuntimeError("401 Unauthorized: invalid API key")

    state = _install_fake_tinfoil(monkeypatch, behavior)
    cfg = SummaryConfig(backend="tinfoil", model="deepseek-v4-pro")
    with pytest.raises(RuntimeError, match="Tinfoil TEE API error"):
        sm._summarize_tinfoil("sys", "user", cfg)
    assert state["attempt"] == 1  # no retry on a real auth error
