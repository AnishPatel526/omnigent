"""E2E: the New Chat picker's "Auto" native-routing option.

The landing composer (``NewChatLandingScreen`` in
``web/src/shell/NewChatDialog.tsx``) offers an **"Auto"** row at the top of the
**Harnesses** group when smart routing is enabled (``/v1/info`` →
``smart_routing_enabled``) and at least one native CLI (claude-native /
codex-native / pi-native) is ready on the selected host
(``configured_harnesses``). The row binds to no real agent (its active state is
independent of the selected agent), and Send posts ``native_auto: true`` +
``native_auto_message`` so the server routes among installed native CLIs and
binds the chosen wrapper agent. The typed message is delivered normally after
navigation, as usual.

The ``page.route`` stubbing and async-in-a-fresh-thread shape are inherited from
``chat/test_hide_unconfigured_harnesses.py`` and
``start_session/test_start_session.py``.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
from collections.abc import Coroutine
from typing import Any

from playwright.async_api import Route, async_playwright, expect

_HOST_ID = "host_e2e"
_HOST_NAME = "e2e-host"
_CLAUDE_AGENT_ID = "ag_claude_e2e"

# Bare create endpoint: ``/v1/sessions`` with an optional query, but NOT
# ``/v1/sessions/{id}/...``.
_SESSIONS_RE = re.compile(r"/v1/sessions(\?.*)?$")


def _run_in_fresh_loop(coro: Coroutine[Any, Any, None]) -> None:
    """Run *coro* in a dedicated thread with its own event loop."""
    captured: dict[str, Exception] = {}

    def _worker() -> None:
        try:
            asyncio.run(coro)
        except Exception as exc:  # surfaced on the calling thread
            captured["error"] = exc

    thread = threading.Thread(target=_worker)
    thread.start()
    thread.join()
    if "error" in captured:
        raise captured["error"]


async def _wait_until(predicate, *, timeout_s: float = 15.0) -> None:
    """Poll ``predicate`` on the event loop until true or timeout."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"condition not met within {timeout_s:.0f}s")


def _hosts_body() -> str:
    """Stub ``GET /v1/hosts``: one online host with claude-native ready."""
    return json.dumps(
        {
            "hosts": [
                {
                    "host_id": _HOST_ID,
                    "name": _HOST_NAME,
                    "owner": "e2e",
                    "status": "online",
                    "configured_harnesses": {"claude-native": True},
                }
            ]
        }
    )


def _agents_body() -> str:
    """Stub ``GET /v1/agents``: a native Claude agent (makes the group exist)."""
    return json.dumps(
        {
            "data": [
                {
                    "id": _CLAUDE_AGENT_ID,
                    "name": "claude-native-ui",
                    "display_name": "Claude Code",
                    "description": "Anthropic's coding agent",
                    "harness": "claude-native",
                    "skills": [],
                }
            ]
        }
    )


async def _register_routes(page, create_bodies: list[Any]) -> None:
    """Stub host/agent discovery, force smart routing on, capture the create POST."""

    async def handle_hosts(route: Route) -> None:
        await route.fulfill(status=200, content_type="application/json", body=_hosts_body())

    async def handle_agents(route: Route) -> None:
        await route.fulfill(status=200, content_type="application/json", body=_agents_body())

    async def handle_events(route: Route) -> None:
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"queued": True, "item_id": "ci_e2e"}),
        )

    async def handle_info(route: Route) -> None:
        # Patch only smart_routing_enabled on the real /v1/info body so the Auto
        # row is offered without hard-coding the full (evolving) info shape.
        resp = await route.fetch()
        body = await resp.json()
        body["smart_routing_enabled"] = True
        await route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    async def handle_sessions(route: Route) -> None:
        if route.request.method == "POST":
            create_bodies.append(route.request.post_data_json)
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"id": "conv_auto_native_e2e"}),
            )
        else:
            await route.continue_()

    await page.route("**/v1/info", handle_info)
    await page.route("**/v1/hosts", handle_hosts)
    await page.route("**/v1/agents", handle_agents)
    await page.route("**/v1/sessions/*/events", handle_events)
    await page.route(_SESSIONS_RE, handle_sessions)


def test_auto_native_row_appears_and_posts_native_auto(
    seeded_session: tuple[str, str],
) -> None:
    """The Auto row shows under Harnesses; Send posts native_auto + message.

    1. With smart routing on and claude-native ready, the picker's Harnesses
       group leads with an "Auto" row.
    2. Selecting it and hitting Send posts ``native_auto: true`` +
       ``native_auto_message`` with no ``harness_override``/``model_override``.
    """
    base_url, session_id = seeded_session
    del session_id  # this flow creates its own (stubbed) session
    _run_in_fresh_loop(_drive(base_url))


async def _drive(base_url: str) -> None:
    create_bodies: list[Any] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        try:
            await _register_routes(page, create_bodies)
            await page.add_init_script(
                f"""window.localStorage.setItem(
                    "omnigent:recent-workspaces",
                    JSON.stringify({{ {_HOST_ID}: ["/work/repo"] }})
                );"""
            )
            await page.goto(f"{base_url}/")
            await page.get_by_test_id("new-chat-landing-input").wait_for(
                state="visible", timeout=30_000
            )

            # 1. The Auto row leads the Harnesses group.
            await page.get_by_test_id("new-chat-landing-agent-select").click()
            auto_row = page.get_by_test_id("new-chat-landing-harness-auto-native")
            await expect(auto_row).to_be_visible(timeout=30_000)

            # 2. Select it, type a task, and Send.
            await auto_row.click()
            await page.get_by_test_id("new-chat-landing-input").fill("build me a feature")
            await page.get_by_test_id("new-chat-landing-submit").click()

            await _wait_until(lambda: len(create_bodies) == 1)
            body = create_bodies[0]
            assert body.get("native_auto") is True, body
            assert body.get("native_auto_message") == "build me a feature", body
            assert body.get("cost_control_mode_override") == "on", body
            assert body.get("harness_override") is None, body
            assert body.get("model_override") is None, body
        finally:
            await browser.close()
