"""Provider-neutral session goal routes and backend adapter contract."""

from __future__ import annotations

import asyncio
from typing import Protocol

from fastapi import APIRouter, Request
from fastapi.responses import Response

from omnigent.entities import Conversation
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.server.auth import LEVEL_EDIT, LEVEL_READ, AuthProvider
from omnigent.server.routes._auth_helpers import get_user_id as _get_user_id
from omnigent.server.routes._auth_helpers import require_access as _require_access
from omnigent.server.schemas import (
    ClearGoalResponse,
    GoalMode,
    GoalResponse,
    SetGoalRequest,
    UpdateGoalStatusRequest,
)
from omnigent.stores import ConversationStore
from omnigent.stores.permission_store import PermissionStore


class GoalAdapter(Protocol):
    """Backend contract hidden behind ``/v1/sessions/{id}/goal``."""

    mode: GoalMode

    def supports(self, conversation: Conversation) -> bool:
        raise NotImplementedError

    async def read(
        self,
        request: Request,
        conversation: Conversation,
        *,
        user_id: str | None,
    ) -> GoalResponse | Response:
        raise NotImplementedError

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
    ) -> GoalResponse | Response:
        raise NotImplementedError

    async def update_status(
        self,
        request: Request,
        conversation: Conversation,
        *,
        user_id: str | None,
        status: str,
    ) -> GoalResponse | Response:
        raise NotImplementedError

    async def clear(
        self,
        request: Request,
        conversation: Conversation,
        *,
        user_id: str | None,
    ) -> ClearGoalResponse | Response:
        raise NotImplementedError


async def _require_goal_session(
    session_id: str,
    conversation_store: ConversationStore,
    adapters: tuple[GoalAdapter, ...],
) -> tuple[Conversation, GoalAdapter]:
    conversation = await asyncio.to_thread(conversation_store.get_conversation, session_id)
    if conversation is None:
        raise OmnigentError("Session not found", code=ErrorCode.NOT_FOUND)
    adapter = next((candidate for candidate in adapters if candidate.supports(conversation)), None)
    if adapter is None:
        raise OmnigentError(
            f"Goal mode is not supported for session {session_id!r}",
            code=ErrorCode.GOAL_NOT_SUPPORTED,
        )
    return conversation, adapter


def register_goal_routes(
    router: APIRouter,
    *,
    conversation_store: ConversationStore,
    auth_provider: AuthProvider | None,
    permission_store: PermissionStore | None,
    adapters: tuple[GoalAdapter, ...],
) -> None:
    """Register the provider-neutral session goal facade."""

    @router.get("/sessions/{session_id}/goal", response_model=GoalResponse)
    async def get_goal(request: Request, session_id: str) -> GoalResponse | Response:
        user_id = _get_user_id(request, auth_provider)
        await _require_access(
            user_id,
            session_id,
            LEVEL_READ,
            permission_store,
            conversation_store,
        )
        conversation, adapter = await _require_goal_session(
            session_id,
            conversation_store,
            adapters,
        )
        return await adapter.read(request, conversation, user_id=user_id)

    @router.put("/sessions/{session_id}/goal", response_model=GoalResponse)
    async def set_goal(
        request: Request,
        session_id: str,
        body: SetGoalRequest,
    ) -> GoalResponse | Response:
        user_id = _get_user_id(request, auth_provider)
        await _require_access(
            user_id,
            session_id,
            LEVEL_EDIT,
            permission_store,
            conversation_store,
        )
        conversation, adapter = await _require_goal_session(
            session_id,
            conversation_store,
            adapters,
        )
        objective = body.objective.strip()
        if not objective:
            raise OmnigentError(
                "Goal objective must be non-empty",
                code=ErrorCode.INVALID_INPUT,
            )
        return await adapter.set(
            request,
            conversation,
            user_id=user_id,
            objective=objective,
            token_budget=body.token_budget,
            token_budget_provided="token_budget" in body.model_fields_set,
            status=body.status,
        )

    @router.patch("/sessions/{session_id}/goal/status", response_model=GoalResponse)
    async def update_goal_status(
        request: Request,
        session_id: str,
        body: UpdateGoalStatusRequest,
    ) -> GoalResponse | Response:
        user_id = _get_user_id(request, auth_provider)
        await _require_access(
            user_id,
            session_id,
            LEVEL_EDIT,
            permission_store,
            conversation_store,
        )
        conversation, adapter = await _require_goal_session(
            session_id,
            conversation_store,
            adapters,
        )
        return await adapter.update_status(
            request,
            conversation,
            user_id=user_id,
            status=body.status,
        )

    @router.delete("/sessions/{session_id}/goal", response_model=ClearGoalResponse)
    async def clear_goal(request: Request, session_id: str) -> ClearGoalResponse | Response:
        user_id = _get_user_id(request, auth_provider)
        await _require_access(
            user_id,
            session_id,
            LEVEL_EDIT,
            permission_store,
            conversation_store,
        )
        conversation, adapter = await _require_goal_session(
            session_id,
            conversation_store,
            adapters,
        )
        return await adapter.clear(request, conversation, user_id=user_id)
