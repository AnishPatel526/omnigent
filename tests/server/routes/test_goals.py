"""Tests for the provider-neutral session Goal API."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from omnigent.entities import Conversation
from omnigent.errors import OmnigentError
from omnigent.server.routes.goals import register_goal_routes
from omnigent.server.schemas import ClearGoalResponse, GoalObject, GoalResponse


class _ConversationStore:
    def __init__(self, conversation: Conversation) -> None:
        self.conversation = conversation

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        if conversation_id == self.conversation.id:
            return self.conversation
        return None


class _GoalAdapter:
    mode = "codex"

    def __init__(self, *, supported: bool = True) -> None:
        self.supported = supported
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def supports(self, conversation: Conversation) -> bool:
        return self.supported

    def _response(self, conversation: Conversation, status: str = "active") -> GoalResponse:
        return GoalResponse(
            goal=GoalObject(
                goal_id=conversation.id,
                objective="Ship Goal mode",
                status=status,
                token_budget=40_000,
                tokens_used=10,
                time_used_seconds=2,
            )
        )

    async def read(
        self,
        request: Request,
        conversation: Conversation,
        *,
        user_id: str | None,
    ) -> GoalResponse:
        self.calls.append(("read", {"user_id": user_id}))
        return self._response(conversation)

    async def set(
        self,
        request: Request,
        conversation: Conversation,
        *,
        user_id: str | None,
        objective: str,
        token_budget: int | None,
        token_budget_provided: bool,
        status: str | None,
    ) -> GoalResponse:
        self.calls.append(
            (
                "set",
                {
                    "objective": objective,
                    "token_budget": token_budget,
                    "token_budget_provided": token_budget_provided,
                    "status": status,
                },
            )
        )
        return self._response(conversation, status or "active")

    async def update_status(
        self,
        request: Request,
        conversation: Conversation,
        *,
        user_id: str | None,
        status: str,
    ) -> GoalResponse:
        self.calls.append(("update_status", {"status": status}))
        return self._response(conversation, status)

    async def clear(
        self,
        request: Request,
        conversation: Conversation,
        *,
        user_id: str | None,
    ) -> ClearGoalResponse:
        self.calls.append(("clear", {}))
        return ClearGoalResponse(cleared=True)


def _goal_app(adapter: _GoalAdapter) -> FastAPI:
    conversation = Conversation(
        id="conv_goal",
        created_at=1,
        updated_at=1,
        root_conversation_id="conv_goal",
        agent_id="ag_goal",
    )
    app = FastAPI()

    @app.exception_handler(OmnigentError)
    async def handle_omnigent_error(
        request: Request,
        exc: OmnigentError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    router = APIRouter(prefix="/v1")
    register_goal_routes(
        router,
        conversation_store=_ConversationStore(conversation),  # type: ignore[arg-type]
        auth_provider=None,
        permission_store=None,
        adapters=(adapter,),
    )
    app.include_router(router)
    return app


@pytest.mark.asyncio
async def test_goal_routes_delegate_provider_neutral_contract() -> None:
    adapter = _GoalAdapter()
    transport = httpx.ASGITransport(app=_goal_app(adapter))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        set_response = await client.put(
            "/v1/sessions/conv_goal/goal",
            json={"objective": "  Ship Goal mode  ", "token_budget": None},
        )
        read_response = await client.get("/v1/sessions/conv_goal/goal")
        status_response = await client.patch(
            "/v1/sessions/conv_goal/goal/status",
            json={"status": "paused"},
        )
        clear_response = await client.delete("/v1/sessions/conv_goal/goal")

    assert set_response.status_code == 200
    assert set_response.json()["goal"]["goal_id"] == "conv_goal"
    assert read_response.status_code == 200
    assert status_response.json()["goal"]["status"] == "paused"
    assert clear_response.json() == {"cleared": True}
    assert adapter.calls == [
        (
            "set",
            {
                "objective": "Ship Goal mode",
                "token_budget": None,
                "token_budget_provided": True,
                "status": None,
            },
        ),
        ("read", {"user_id": None}),
        ("update_status", {"status": "paused"}),
        ("clear", {}),
    ]


@pytest.mark.asyncio
async def test_goal_route_returns_typed_error_for_unsupported_session() -> None:
    adapter = _GoalAdapter(supported=False)
    transport = httpx.ASGITransport(app=_goal_app(adapter))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/sessions/conv_goal/goal")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "goal_not_supported"
    assert adapter.calls == []
