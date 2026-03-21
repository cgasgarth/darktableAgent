from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, TypedDict

from shared.protocol import AgentPlan, RequestEnvelope


@dataclass(frozen=True, slots=True)
class CancelRequestKey:
    request_id: str
    app_session_id: str
    image_session_id: str
    conversation_id: str
    turn_id: str


@dataclass(slots=True)
class CodexTurnResult:
    plan: AgentPlan
    thread_id: str
    turn_id: str
    raw_message: str


@dataclass(slots=True)
class ActiveRequestState:
    request_id: str
    app_session_id: str
    image_session_id: str
    conversation_id: str
    client_turn_id: str
    cancel_event: threading.Event = field(default_factory=threading.Event)
    cancel_reason: str | None = None
    thread_id: str | None = None
    codex_turn_id: str | None = None
    status: str = "queued"
    message: str = "Request accepted"
    last_tool_name: str | None = None
    progress_version: int = 0

    @property
    def cancel_key(self) -> CancelRequestKey:
        return CancelRequestKey(
            request_id=self.request_id,
            app_session_id=self.app_session_id,
            image_session_id=self.image_session_id,
            conversation_id=self.conversation_id,
            turn_id=self.client_turn_id,
        )


@dataclass(slots=True)
class TurnContext:
    base_request: RequestEnvelope
    preview_data_url: str
    base_preview_mime_type: str
    base_preview_bytes: bytes
    current_preview_bytes: bytes
    preview_mime_type: str
    base_image_revision_id: str
    state_payload: dict[str, Any]
    setting_by_id: dict[str, dict[str, Any]]
    base_float_setting_numbers: dict[str, float]
    live_run_enabled: bool
    max_tool_calls: int
    tool_calls_used: int = 0
    consecutive_read_only_tool_calls: int = 0
    applied_operations: list[dict[str, Any]] = field(default_factory=list)
    next_operation_sequence: int = 1
    render_event: threading.Event = field(default_factory=threading.Event)
    rendered_preview_bytes: bytes | None = None
    requires_render_callback: bool = False
    last_applied_batch: list[dict[str, Any]] = field(default_factory=list)
    last_applied_summary: str | None = None
    last_verifier_status: str | None = None
    last_verifier_summary: str | None = None


class TurnRunState(TypedDict):
    thread_id: str
    turn_id: str
    chunks: list[str]
    final_message: str | None
    turn_error: str | None
    completed: bool
    token_usage_last: dict[str, Any] | None
    token_usage_total: dict[str, Any] | None
    last_activity_at: float
    last_activity_method: str | None
