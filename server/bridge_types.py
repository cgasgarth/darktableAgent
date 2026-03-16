from __future__ import annotations

from typing import Any, Protocol, TypedDict

from shared.protocol import AgentPlan, RequestEnvelope


class RequestProgressPayload(TypedDict):
    found: bool
    status: str
    toolCallsUsed: int
    maxToolCalls: int
    appliedOperationCount: int
    operations: list[dict[str, Any]]
    message: str
    lastToolName: str | None
    progressVersion: int


class PlannerTurnResult(Protocol):
    plan: AgentPlan
    thread_id: str
    turn_id: str
    raw_message: str


class PlannerBridge(Protocol):
    def plan(self, request: RequestEnvelope) -> PlannerTurnResult: ...

    def cancel_request(
        self,
        *,
        request_id: str,
        app_session_id: str,
        image_session_id: str,
        conversation_id: str,
        turn_id: str,
        reason: str | None = None,
    ) -> bool: ...

    def get_request_progress(
        self,
        *,
        request_id: str,
        app_session_id: str,
        image_session_id: str,
        conversation_id: str,
        turn_id: str,
    ) -> RequestProgressPayload: ...
