from __future__ import annotations

# pyright: reportAttributeAccessIssue=false

from typing import Any

from shared.protocol import AgentPlan
from server.bridge_types import RequestProgressPayload

from .config import logger
from .errors import CodexAppServerError
from .models import ActiveRequestState, CancelRequestKey, TurnContext


def build_output_schema(agent_plan_type: Any) -> dict[str, Any]:
    schema = agent_plan_type.model_json_schema()

    def _rewrite(node: Any) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                node["required"] = list(properties.keys())
                node.setdefault("additionalProperties", False)
                for child in properties.values():
                    _rewrite(child)

            for key in ("items", "anyOf", "allOf", "oneOf", "prefixItems"):
                child = node.get(key)
                if isinstance(child, list):
                    for item in child:
                        _rewrite(item)
                elif isinstance(child, dict):
                    _rewrite(child)

            defs = node.get("$defs")
            if isinstance(defs, dict):
                for child in defs.values():
                    _rewrite(child)
        elif isinstance(node, list):
            for item in node:
                _rewrite(item)

    _rewrite(schema)
    return schema


class RequestStateMixin:
    @staticmethod
    def _build_output_schema() -> dict[str, Any]:
        return build_output_schema(AgentPlan)

    def _register_request(self, request) -> ActiveRequestState:  # type: ignore[no-untyped-def]
        active_request = ActiveRequestState(
            request_id=request.requestId,
            app_session_id=request.session.appSessionId,
            image_session_id=request.session.imageSessionId,
            conversation_id=request.session.conversationId,
            client_turn_id=request.session.turnId,
        )
        with self._state_lock:
            self._active_requests[request.requestId] = active_request
            cancel_reason = self._cancelled_requests.get(active_request.cancel_key)
            if cancel_reason is not None:
                active_request.cancel_event.set()
                active_request.cancel_reason = cancel_reason
        return active_request

    def _unregister_request(self, request_id: str) -> None:
        with self._state_lock:
            active_request = self._active_requests.pop(request_id, None)
            if active_request is not None:
                self._cancelled_requests.pop(active_request.cancel_key, None)

    def cancel_request(
        self,
        *,
        request_id: str,
        app_session_id: str,
        image_session_id: str,
        conversation_id: str,
        turn_id: str,
        reason: str | None = None,
    ) -> bool:
        cancel_key = CancelRequestKey(
            request_id=request_id,
            app_session_id=app_session_id,
            image_session_id=image_session_id,
            conversation_id=conversation_id,
            turn_id=turn_id,
        )

        matched_active = False
        with self._state_lock:
            self._cancelled_requests[cancel_key] = reason or "Chat request was canceled"
            active_request = self._active_requests.get(request_id)
            if active_request and active_request.cancel_key == cancel_key:
                active_request.cancel_event.set()
                active_request.cancel_reason = reason
                active_request.status = "cancel-requested"
                active_request.message = reason or "Cancellation requested"
                matched_active = True

        return matched_active

    def get_request_progress(
        self,
        *,
        request_id: str,
        app_session_id: str,
        image_session_id: str,
        conversation_id: str,
        turn_id: str,
    ) -> RequestProgressPayload:
        with self._state_lock:
            active_request = self._active_requests.get(request_id)
            if active_request is None:
                return {
                    "found": False,
                    "status": "not_found",
                    "toolCallsUsed": 0,
                    "maxToolCalls": 0,
                    "appliedOperationCount": 0,
                    "operations": [],
                    "message": "No active request found for that requestId.",
                    "lastToolName": None,
                    "progressVersion": 0,
                    "requiresRenderCallback": False,
                }

            if (
                active_request.app_session_id != app_session_id
                or active_request.image_session_id != image_session_id
                or active_request.conversation_id != conversation_id
                or active_request.client_turn_id != turn_id
            ):
                return {
                    "found": False,
                    "status": "not_found",
                    "toolCallsUsed": 0,
                    "maxToolCalls": 0,
                    "appliedOperationCount": 0,
                    "operations": [],
                    "message": "No active request matched the provided session identifiers.",
                    "lastToolName": None,
                    "progressVersion": 0,
                    "requiresRenderCallback": False,
                }

            context: TurnContext | None = None
            if active_request.thread_id and active_request.codex_turn_id:
                context = self._turn_contexts.get(
                    (active_request.thread_id, active_request.codex_turn_id)
                )

            operations = list(context.applied_operations) if context else []
            tool_calls_used = context.tool_calls_used if context else 0
            max_tool_calls = context.max_tool_calls if context else 0
            return {
                "found": True,
                "status": active_request.status,
                "toolCallsUsed": tool_calls_used,
                "maxToolCalls": max_tool_calls,
                "appliedOperationCount": len(operations),
                "operations": operations,
                "message": active_request.message,
                "lastToolName": active_request.last_tool_name,
                "progressVersion": active_request.progress_version,
                "requiresRenderCallback": context.requires_render_callback if context else False,
            }

    def _is_cancelled(self, active_request: ActiveRequestState) -> bool:
        with self._state_lock:
            return active_request.cancel_event.is_set()

    def _raise_if_cancelled_locked(
        self, active_request: ActiveRequestState | None
    ) -> None:
        if active_request is None or not self._is_cancelled(active_request):
            return

        cancel_reason = active_request.cancel_reason or "Chat request was canceled"
        self._set_active_request_status_locked(
            active_request.request_id,
            status="cancelled",
            message=cancel_reason,
        )
        logger.info(
            "codex_request_cancelled",
            extra={
                "structured": {
                    "requestId": active_request.request_id,
                    "conversationId": active_request.conversation_id,
                    "threadId": active_request.thread_id,
                    "codexTurnId": active_request.codex_turn_id,
                    "cancelReason": active_request.cancel_reason,
                }
            },
        )
        self._reset_process_locked()
        raise CodexAppServerError("request_cancelled", cancel_reason, status_code=499)

    def _set_active_request_status_locked(
        self,
        request_id: str,
        *,
        status: str,
        message: str | None = None,
        last_tool_name: str | None = None,
    ) -> None:
        with self._state_lock:
            active_request = self._active_requests.get(request_id)
            if active_request is None:
                return
            active_request.status = status
            if message is not None:
                active_request.message = message
            if last_tool_name is not None:
                active_request.last_tool_name = last_tool_name
            active_request.progress_version += 1

    def _set_active_request_status_for_turn_locked(
        self,
        thread_id: str,
        turn_id: str,
        *,
        status: str,
        message: str,
        last_tool_name: str | None = None,
    ) -> None:
        with self._state_lock:
            for active_request in self._active_requests.values():
                if (
                    active_request.thread_id == thread_id
                    and active_request.codex_turn_id == turn_id
                ):
                    active_request.status = status
                    active_request.message = message
                    if last_tool_name is not None:
                        active_request.last_tool_name = last_tool_name
                    active_request.progress_version += 1
                    return

    def provide_render_callback(
        self,
        *,
        image_session_id: str,
        turn_id: str,
        image_bytes: bytes,
    ) -> bool:
        context: TurnContext | None = None
        with self._state_lock:
            for active_request in self._active_requests.values():
                if (
                    active_request.image_session_id == image_session_id
                    and active_request.client_turn_id == turn_id
                    and active_request.thread_id
                    and active_request.codex_turn_id
                ):
                    context = self._turn_contexts.get(
                        (active_request.thread_id, active_request.codex_turn_id)
                    )
                    break

        if context is not None:
            context.rendered_preview_bytes = image_bytes
            context.render_event.set()
            return True
        return False
