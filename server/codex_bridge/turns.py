from __future__ import annotations

# pyright: reportAttributeAccessIssue=false

import time
from typing import Any

from shared.protocol import AgentPlan, RequestEnvelope

from .config import (
    _DEFAULT_APPROVAL_POLICY,
    _DEFAULT_MAX_IDLE_SECONDS,
    _DEFAULT_MODEL,
    _DEFAULT_PERSONALITY,
    _DEFAULT_REASONING_EFFORT,
    _FAST_MODE_MODEL,
    _FAST_MODE_REASONING_EFFORT,
    _DEFAULT_SANDBOX,
    _THREAD_DEVELOPER_INSTRUCTIONS,
    logger,
)
from .errors import CodexAppServerError
from .models import ActiveRequestState, CodexTurnResult, TurnRunState
from .request_state import build_output_schema


class TurnsMixin:
    @staticmethod
    def _model_for_request(request: RequestEnvelope) -> str | None:
        if request.fast and _FAST_MODE_MODEL:
            return _FAST_MODE_MODEL
        return _DEFAULT_MODEL

    @staticmethod
    def _effort_for_request(request: RequestEnvelope) -> str:
        if request.fast:
            return _FAST_MODE_REASONING_EFFORT
        return _DEFAULT_REASONING_EFFORT

    @staticmethod
    def _sanitize_request_for_agent_safety(request: RequestEnvelope) -> RequestEnvelope:
        return request

    def _get_or_create_thread_locked(
        self, conversation_id: str, model: str | None, deadline: float
    ) -> str:
        existing = self._conversation_threads.get(conversation_id)
        if existing:
            logger.info(
                "codex_thread_reused",
                extra={
                    "structured": {
                        "conversationId": conversation_id,
                        "threadId": existing,
                    }
                },
            )
            return existing

        params: dict[str, Any] = {
            "cwd": self._cwd,
            "approvalPolicy": _DEFAULT_APPROVAL_POLICY,
            "sandbox": _DEFAULT_SANDBOX,
            "personality": _DEFAULT_PERSONALITY,
            "developerInstructions": _THREAD_DEVELOPER_INSTRUCTIONS,
            "dynamicTools": self._dynamic_tools(),
        }
        if model:
            params["model"] = model

        response = self._send_request_locked("thread/start", params, deadline, None)
        try:
            thread_id = response["result"]["thread"]["id"]
        except KeyError as exc:
            raise CodexAppServerError(
                "codex_thread_start_failed", "Codex did not return a thread id"
            ) from exc

        self._conversation_threads[conversation_id] = thread_id
        logger.info(
            "codex_thread_started",
            extra={
                "structured": {"conversationId": conversation_id, "threadId": thread_id}
            },
        )
        return thread_id

    def _run_turn_locked(
        self,
        thread_id: str,
        request: RequestEnvelope,
        model: str | None,
        effort: str,
        deadline: float,
        active_request: ActiveRequestState,
        thread_reused: bool,
    ) -> CodexTurnResult:
        started_at = time.monotonic()
        preview_data_url = self._preview_data_url(request)
        turn_input = self._build_turn_input(request, preview_data_url=preview_data_url)
        self._conversation_turn_counts[active_request.conversation_id] = (
            self._conversation_turn_counts.get(active_request.conversation_id, 0) + 1
        )
        turn_index = self._conversation_turn_counts[active_request.conversation_id]
        prompt_text_chars = sum(
            len(str(item.get("text", "")))
            for item in turn_input
            if item.get("type") == "text"
        )
        image_input_chars = sum(
            len(str(item.get("url", "")))
            for item in turn_input
            if item.get("type") == "image"
        )

        try:
            turn_request = {
                "threadId": thread_id,
                "input": turn_input,
                "outputSchema": build_output_schema(AgentPlan),
                "approvalPolicy": _DEFAULT_APPROVAL_POLICY,
                "personality": _DEFAULT_PERSONALITY,
                "effort": effort,
            }
            if model:
                turn_request["model"] = model

            response = self._send_request_locked(
                "turn/start", turn_request, deadline, active_request
            )
            result = response.get("result")
            turn = result.get("turn") if isinstance(result, dict) else None
            turn_id_value = turn.get("id") if isinstance(turn, dict) else None
            if not isinstance(turn_id_value, str) or not turn_id_value:
                raise CodexAppServerError(
                    "codex_turn_start_failed", "Codex did not return a turn id"
                )
            turn_id = turn_id_value
            active_request.codex_turn_id = turn_id
            self._register_turn_context(thread_id, turn_id, request, preview_data_url)
            self._set_active_request_status_locked(
                active_request.request_id,
                status="running",
                message="Waiting for Codex turn output",
            )
            logger.info(
                "codex_turn_started",
                extra={
                    "structured": {
                        "requestId": active_request.request_id,
                        "conversationId": active_request.conversation_id,
                        "threadId": thread_id,
                        "turnId": turn_id,
                        "threadReused": thread_reused,
                        "turnIndexInConversation": turn_index,
                        "model": model,
                        "effort": effort,
                    }
                },
            )

            state: TurnRunState = {
                "thread_id": thread_id,
                "turn_id": turn_id,
                "chunks": [],
                "final_message": None,
                "turn_error": None,
                "completed": False,
                "token_usage_last": None,
                "token_usage_total": None,
                "last_activity_at": time.monotonic(),
                "last_activity_method": "turn/start",
            }

            while not state["completed"]:
                self._raise_if_cancelled_locked(active_request)
                max_wait_seconds = 0.5
                if _DEFAULT_MAX_IDLE_SECONDS > 0:
                    idle_seconds = time.monotonic() - state["last_activity_at"]
                    if idle_seconds >= _DEFAULT_MAX_IDLE_SECONDS:
                        raise CodexAppServerError(
                            "codex_stalled",
                            (
                                "Codex turn stalled without output. "
                                f"No events for {int(idle_seconds)}s after "
                                f"{state.get('last_activity_method') or 'unknown'}."
                            ),
                            status_code=504,
                        )
                    max_wait_seconds = min(
                        max_wait_seconds, _DEFAULT_MAX_IDLE_SECONDS - idle_seconds
                    )

                message = self._read_message_locked(
                    deadline,
                    active_request,
                    max_wait_seconds=max_wait_seconds,
                )
                if message is None:
                    continue
                state["last_activity_at"] = time.monotonic()
                state["last_activity_method"] = (
                    message.get("method") or "jsonrpc-response"
                )
                self._handle_message_locked(message, state)

            if state["turn_error"]:
                raise CodexAppServerError("codex_turn_failed", state["turn_error"])

            raw_message = state["final_message"] or "".join(state["chunks"]).strip()
            if not raw_message:
                raise CodexAppServerError(
                    "codex_empty_response",
                    "Codex completed the turn without returning a plan",
                )

            try:
                plan = AgentPlan.model_validate_json(raw_message)
            except Exception as exc:
                raise CodexAppServerError(
                    "codex_invalid_response",
                    f"Codex returned invalid plan JSON: {raw_message}",
                ) from exc

            context = self._get_turn_context(thread_id, turn_id)
            plan = self._finalize_plan_with_live_context(plan, context)
            self._set_active_request_status_locked(
                active_request.request_id,
                status="completed",
                message="Codex plan completed",
            )

            op_count = len(plan.operations)
            summary_text = plan.assistantText or ""
            if len(summary_text) > 200:
                summary_text = summary_text[:200] + "..."
            turn_summary = (
                f"Turn {turn_index}: {op_count} operations. {summary_text}"
            )
            conv_id = active_request.conversation_id
            if conv_id not in self._conversation_histories:
                self._conversation_histories[conv_id] = []
            self._conversation_histories[conv_id].append(turn_summary)
            self._conversation_histories[conv_id] = self._conversation_histories[conv_id][-10:]

            duration_ms = int((time.monotonic() - started_at) * 1000)
            logger.info(
                "codex_turn_completed",
                extra={
                    "structured": {
                        "requestId": active_request.request_id,
                        "conversationId": active_request.conversation_id,
                        "threadId": thread_id,
                        "turnId": turn_id,
                        "threadReused": thread_reused,
                        "turnIndexInConversation": turn_index,
                        "durationMs": duration_ms,
                        "promptTextChars": prompt_text_chars,
                        "imageInputChars": image_input_chars,
                        "tokenUsageLast": state["token_usage_last"],
                        "tokenUsageTotal": state["token_usage_total"],
                    }
                },
            )
            return CodexTurnResult(
                plan=plan,
                thread_id=thread_id,
                turn_id=turn_id,
                raw_message=raw_message,
            )
        finally:
            if active_request.codex_turn_id is not None:
                self._clear_turn_context(thread_id, active_request.codex_turn_id)
                active_request.codex_turn_id = None

    def _handle_message_locked(
        self, message: dict[str, Any], turn_state: TurnRunState | None
    ) -> None:
        if "method" in message and "id" in message:
            self._handle_server_request_locked(message)
            return
        if "method" not in message:
            return

        method = message["method"]
        raw_params = message.get("params", {})
        params = raw_params if isinstance(raw_params, dict) else {}

        if method == "error":
            if (
                turn_state
                and params.get("threadId") == turn_state["thread_id"]
                and params.get("turnId") == turn_state["turn_id"]
            ):
                raw_error = params.get("error", {})
                error = raw_error if isinstance(raw_error, dict) else {}
                turn_state["turn_error"] = self._extract_error_message(
                    error.get("message") or "Codex app server reported an error"
                )
            return

        if not turn_state:
            return
        if method == "item/agentMessage/delta":
            if (
                params.get("threadId") == turn_state["thread_id"]
                and params.get("turnId") == turn_state["turn_id"]
            ):
                delta = params.get("delta", "")
                turn_state["chunks"].append(delta if isinstance(delta, str) else "")
            return

        if method == "thread/tokenUsage/updated":
            if (
                params.get("threadId") != turn_state["thread_id"]
                or params.get("turnId") != turn_state["turn_id"]
            ):
                return
            usage = params.get("tokenUsage", {})
            if isinstance(usage, dict):
                last_usage = usage.get("last")
                total_usage = usage.get("total")
                if isinstance(last_usage, dict):
                    turn_state["token_usage_last"] = last_usage
                if isinstance(total_usage, dict):
                    turn_state["token_usage_total"] = total_usage
            return

        if method == "item/completed":
            if (
                params.get("threadId") != turn_state["thread_id"]
                or params.get("turnId") != turn_state["turn_id"]
            ):
                return
            raw_item = params.get("item", {})
            item = raw_item if isinstance(raw_item, dict) else {}
            if item.get("type") == "agentMessage":
                text = item.get("text")
                turn_state["final_message"] = text if isinstance(text, str) else None
                if item.get("phase") == "final_answer":
                    turn_state["completed"] = True
            return

        if method == "codex/event/task_complete":
            if params.get("id") != turn_state["turn_id"]:
                return
            raw_msg = params.get("msg", {})
            msg = raw_msg if isinstance(raw_msg, dict) else {}
            last_agent_message = msg.get("last_agent_message")
            if isinstance(last_agent_message, str) and last_agent_message:
                turn_state["final_message"] = last_agent_message
                turn_state["completed"] = True
            return

        if method == "turn/completed":
            if params.get("threadId") != turn_state["thread_id"]:
                return
            raw_turn = params.get("turn", {})
            turn = raw_turn if isinstance(raw_turn, dict) else {}
            if turn.get("id") != turn_state["turn_id"]:
                return
            raw_error = turn.get("error")
            if isinstance(raw_error, dict):
                turn_state["turn_error"] = self._extract_error_message(
                    raw_error.get("message") or "Codex turn failed"
                )
            turn_state["completed"] = True
