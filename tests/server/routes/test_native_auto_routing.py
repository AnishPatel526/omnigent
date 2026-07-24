"""Unit tests for "Auto (native)" create-time routing helpers.

Covers :func:`_installed_native_harnesses` (host readiness → installed set) and
:func:`_resolve_native_auto` (route the native harness at create and resolve the
wrapper agent name), which back the new-chat "Auto" native picker option.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from omnigent.server.routes._sessions.orchestration import (
    _installed_native_harnesses,
    _resolve_native_auto,
)
from omnigent.server.smart_routing import RoutingResult


@dataclass
class _FakeHost:
    """Minimal stand-in exposing only ``configured_harnesses``."""

    configured_harnesses: dict[str, Any] | None


# ── _installed_native_harnesses ──────────────────────────────────────


def test_installed_native_harnesses_filters_not_ready() -> None:
    host = _FakeHost(
        configured_harnesses={
            "claude-native": True,
            "codex-native": "binary-missing",
            "pi-native": "needs-auth",
        }
    )
    assert _installed_native_harnesses(host) == {"claude-native"}


def test_installed_native_harnesses_fails_open_without_readiness() -> None:
    # No host / no readiness map → all candidates (older host reports nothing).
    assert _installed_native_harnesses(None) == {
        "claude-native",
        "codex-native",
        "pi-native",
    }
    assert _installed_native_harnesses(_FakeHost(configured_harnesses=None)) == {
        "claude-native",
        "codex-native",
        "pi-native",
    }


# ── _resolve_native_auto ─────────────────────────────────────────────


class _FakeRoutingClient:
    def __init__(self, result: RoutingResult | None) -> None:
        self._result = result

    async def route(self, message: str, available_models: dict[str, list[str]]) -> Any:
        del message, available_models
        return self._result


def _request_with_host(host: _FakeHost | None) -> Any:
    """Build a fake FastAPI request whose app.state.host_store returns *host*."""
    host_store = SimpleNamespace(get_host=lambda _host_id: host)
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(host_store=host_store)))


def _body(*, message: str = "refactor auth", host_id: str | None = "host_1") -> Any:
    return SimpleNamespace(native_auto_message=message, host_id=host_id)


@pytest.mark.asyncio
async def test_resolve_native_auto_binds_routed_wrapper_agent() -> None:
    """A successful route resolves to the matching native wrapper agent name."""
    host = _FakeHost(configured_harnesses={"claude-native": True, "codex-native": True})
    caps = SimpleNamespace(
        routing_client=_FakeRoutingClient(
            RoutingResult(
                model="databricks-claude-opus-4-8",
                rationale="complex task",
                harness="claude-native",
            )
        )
    )
    with patch("omnigent.runtime._globals._caps", new=caps):
        agent_name, model, verdict, error = await _resolve_native_auto(
            _body(), _request_with_host(host)
        )
    assert agent_name == "claude-native-ui"
    assert model == "databricks-claude-opus-4-8"
    assert verdict is not None
    assert error is None


@pytest.mark.asyncio
async def test_resolve_native_auto_no_installed_cli_returns_error() -> None:
    """No installed native CLI → no agent + an error (caller 400s)."""
    host = _FakeHost(
        configured_harnesses={
            "claude-native": False,
            "codex-native": "binary-missing",
            "pi-native": "needs-auth",
        }
    )
    caps = SimpleNamespace(routing_client=_FakeRoutingClient(None))
    with patch("omnigent.runtime._globals._caps", new=caps):
        agent_name, model, _verdict, error = await _resolve_native_auto(
            _body(), _request_with_host(host)
        )
    assert agent_name is None
    assert model is None
    assert error is not None


@pytest.mark.asyncio
async def test_resolve_native_auto_falls_back_when_routing_unavailable() -> None:
    """Routing returns nothing but a native CLI is installed → cheapest fallback."""
    host = _FakeHost(configured_harnesses={"codex-native": True, "pi-native": True})
    # Router yields no verdict (e.g. not configured) → fallback to cheapest
    # installed native (codex-native precedes pi-native), no model.
    caps = SimpleNamespace(routing_client=_FakeRoutingClient(None))
    with patch("omnigent.runtime._globals._caps", new=caps):
        agent_name, model, _verdict, error = await _resolve_native_auto(
            _body(), _request_with_host(host)
        )
    assert agent_name == "codex-native-ui"
    assert model is None
    assert error is not None  # surfaced as a routing-fallback card
