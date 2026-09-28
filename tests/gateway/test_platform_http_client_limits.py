"""Tests for the shared httpx.Limits helper that all long-lived platform
adapters use to tighten their keep-alive pool.

Context: #18451 — on macOS behind Cloudflare Warp, httpx's default
keepalive_expiry=5s let idle CLOSE_WAIT sockets accumulate across
multiple long-lived gateway adapters (QQ Bot, Feishu, WeCom, DingTalk,
Signal, BlueBubbles, WeCom-callback) until the process hit the default
256 fd limit.  These tests just verify the helper returns sensibly
tuned limits and respects env-var overrides; the actual fd-pressure
behaviour is only observable at runtime under load.
"""

from __future__ import annotations

import pytest

from gateway.platforms._http_client_limits import platform_httpx_limits


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("HERMES_GATEWAY_HTTPX_KEEPALIVE_EXPIRY", raising=False)
    monkeypatch.delenv("HERMES_GATEWAY_HTTPX_MAX_KEEPALIVE", raising=False)


def test_env_override_rejects_garbage(monkeypatch):
    """Malformed env values fall back to defaults rather than raising.

    Specifically: ``HERMES_GATEWAY_HTTPX_MAX_KEEPALIVE=-3`` and
    ``HERMES_GATEWAY_HTTPX_KEEPALIVE_EXPIRY=not-a-number`` should both
    fall back to their respective defaults.
    """
    monkeypatch.setenv("HERMES_GATEWAY_HTTPX_KEEPALIVE_EXPIRY", "not-a-number")
    monkeypatch.setenv("HERMES_GATEWAY_HTTPX_MAX_KEEPALIVE", "-3")
    limits = platform_httpx_limits()
    # Non-positive / non-numeric -> fell back to defaults (not the override values)
    assert limits.keepalive_expiry is not None and limits.keepalive_expiry > 0
    assert limits.max_keepalive_connections is not None
    assert limits.max_keepalive_connections > 0


def test_zero_max_keepalive_disables_keepalive(monkeypatch):
    """``=0`` must disable keepalive (httpx's documented sentinel); not fall back.

    Regression test: previously ``MAX_KEEPALIVE=0`` was treated as
    "non-positive" by ``_positive_env`` and silently replaced with the
    default of 10, so the user had no way to disable keepalive via env.
    """
    monkeypatch.setenv("HERMES_GATEWAY_HTTPX_MAX_KEEPALIVE", "0")
    limits = platform_httpx_limits()
    assert limits.max_keepalive_connections == 0


def test_positive_max_keepalive_is_honored(monkeypatch):
    """Positive integers are passed through as the keepalive-socket cap."""
    monkeypatch.setenv("HERMES_GATEWAY_HTTPX_MAX_KEEPALIVE", "7")
    limits = platform_httpx_limits()
    assert limits.max_keepalive_connections == 7


def test_zero_keepalive_expiry_falls_back_to_default(monkeypatch):
    """``EXPIRY=0`` is degenerate (every socket would expire instantly); fall back.

    The expiry knob keeps strict ``> 0`` semantics; the ``0`` sentinel is only
    meaningful for the keepalive-count knob.
    """
    monkeypatch.setenv("HERMES_GATEWAY_HTTPX_KEEPALIVE_EXPIRY", "0")
    limits = platform_httpx_limits()
    from gateway.platforms._http_client_limits import _DEFAULT_KEEPALIVE_EXPIRY_S
    assert limits.keepalive_expiry == _DEFAULT_KEEPALIVE_EXPIRY_S
