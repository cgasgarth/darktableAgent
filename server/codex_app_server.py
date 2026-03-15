from __future__ import annotations

import base64
import binascii
import io
import json
import logging
import os
import select
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageEnhance
except Exception:  # pragma: no cover - fallback for environments without Pillow
    Image = None
    ImageEnhance = None

from shared.protocol import AgentPlan, RequestEnvelope

logger = logging.getLogger("darktable_agent.codex")

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CLIENT_INFO = {
    "name": "darktableAgent",
    "title": "darktableAgent",
    "version": "0.1.0",
}
_DEFAULT_COMMAND = [
    "codex",
    "app-server",
    "-c",
    "mcp_servers.chrome-devtools.enabled=false",
    "--listen",
    "stdio://",
]
_DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("DARKTABLE_AGENT_CODEX_TIMEOUT_SECONDS", "600"))
_DEFAULT_PERSONALITY = os.environ.get("DARKTABLE_AGENT_CODEX_PERSONALITY", "pragmatic")
_DEFAULT_REASONING_EFFORT = os.environ.get("DARKTABLE_AGENT_CODEX_REASONING_EFFORT", "high")
_DEFAULT_MODEL = os.environ.get("DARKTABLE_AGENT_CODEX_MODEL", "gpt-5.3-codex")
_FAST_MODE_MODEL = os.environ.get("DARKTABLE_AGENT_CODEX_FAST_MODE_MODEL", "gpt-5.3-codex")
_FAST_MODE_REASONING_EFFORT = os.environ.get(
    "DARKTABLE_AGENT_CODEX_FAST_MODE_REASONING_EFFORT", "low"
)
_DEFAULT_SANDBOX = os.environ.get("DARKTABLE_AGENT_CODEX_SANDBOX", "read-only")
_DEFAULT_APPROVAL_POLICY = "never"
_DEFAULT_HISTOGRAM_BINS = int(os.environ.get("DARKTABLE_AGENT_HISTOGRAM_BINS", "64"))
_DEFAULT_MAX_IDLE_SECONDS = float(
    os.environ.get("DARKTABLE_AGENT_CODEX_MAX_IDLE_SECONDS", "120")
)
_DEFAULT_MAX_CONSECUTIVE_READ_ONLY_TOOL_CALLS = int(
    os.environ.get("DARKTABLE_AGENT_MAX_CONSECUTIVE_READ_ONLY_TOOL_CALLS", "4")
)
_DEFAULT_MAX_TOOL_CALLS_WITHOUT_APPLY = int(
    os.environ.get("DARKTABLE_AGENT_MAX_TOOL_CALLS_WITHOUT_APPLY", "3")
)
_TOOL_GET_IMAGE_STATE = "get_image_state"
_TOOL_GET_PREVIEW_IMAGE = "get_preview_image"
_TOOL_APPLY_OPERATIONS = "apply_operations"
_DISALLOWED_WHITE_BALANCE_ACTION_PATH_PREFIXES = (
    "iop/temperature/",
)

_THREAD_DEVELOPER_INSTRUCTIONS = """You are darktableAgent, a structured editing planner for darktable.

Context and tool usage:
- live mode turn input already includes the current preview image
- call `get_image_state` when you need exact editable settings or histogram details
- call `get_preview_image` when you need a refreshed visual check (especially after `apply_operations`)
- in live agent runs (`mode=multi-turn`), call `apply_operations` to apply edits iteratively
Return exactly one JSON object matching the output schema after tool calls.

Use preview as primary visual context. Use histogram + editable settings as constraints.
Only emit operations targeting provided settingId/actionPath pairs. Never invent IDs or paths.
Keep edits coherent, conservative, and executable.
If user intent is broad, infer a reasonable plan from the visible image instead of asking for more specificity.
Prefer advanced color controls (`colorequal`, `colorbalancergb`, `primaries`) when available for nuanced color work.
Do not use white-balance module controls (`iop/temperature/*`); those controls are disabled for safety.

Refinement rules:
- Always optimize toward refinement.goalText.
- In single-turn mode, return operations in the final JSON; do not use `apply_operations`.
- In multi-turn mode, perform iterative tool calls within this same run:
  1) gather any missing context with read-only tools only when needed
  2) apply edits with `apply_operations` early (do not spend many calls only inspecting)
  3) re-check state/preview after edits as needed and continue until satisfied or tool budget is exhausted
- In multi-turn mode, the final JSON should summarize the run and typically return empty operations because edits were already applied via `apply_operations`.
- In multi-turn mode, continueRefining must be false in the final JSON.

Value rules:
- Use mode `delta` only for set-float when supported.
- Use mode `set` for set-choice and set-bool.
- set-choice uses value.choiceValue (and choiceId when known).
- set-bool uses value.boolValue.
- Always include the exact target.settingId from editable settings.
"""


class CodexAppServerError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(slots=True)
class CodexTurnResult:
    plan: AgentPlan
    thread_id: str
    turn_id: str
    raw_message: str


@dataclass(slots=True)
class _ActiveRequestState:
    request_id: str
    app_session_id: str
    image_session_id: str
    conversation_id: str
    client_turn_id: str
    cancel_event: threading.Event = field(default_factory=threading.Event)
    thread_id: str | None = None
    codex_turn_id: str | None = None
    status: str = "queued"
    message: str = "Request accepted"
    last_tool_name: str | None = None
    progress_version: int = 0


@dataclass(slots=True)
class _TurnContext:
    base_request: RequestEnvelope
    preview_data_url: str
    base_preview_mime_type: str
    base_preview_bytes: bytes
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


class CodexAppServerBridge:
    def __init__(
        self,
        *,
        command: list[str] | None = None,
        cwd: Path | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        command_env = os.environ.get("DARKTABLE_AGENT_CODEX_APP_SERVER_CMD")
        self._command = (
            shlex.split(command_env) if command_env else list(command or _DEFAULT_COMMAND)
        )
        self._cwd = str((cwd or _REPO_ROOT).resolve())
        self._timeout_seconds = timeout_seconds
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._initialized = False
        self._next_request_id = 1
        self._conversation_threads: dict[str, str] = {}
        self._conversation_turn_counts: dict[str, int] = {}
        self._active_requests: dict[str, _ActiveRequestState] = {}
        self._cancelled_request_ids: set[str] = set()
        self._turn_contexts: dict[tuple[str, str], _TurnContext] = {}

    @staticmethod
    def _build_output_schema() -> dict[str, Any]:
        schema = AgentPlan.model_json_schema()

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

    def plan(self, request: RequestEnvelope) -> CodexTurnResult:
        request = self._sanitize_request_for_agent_safety(request)
        deadline = time.monotonic() + self._timeout_seconds
        active_request = self._register_request(request)
        try:
            model = self._model_for_request(request)
            effort = self._effort_for_request(request)
            with self._lock:
                self._set_active_request_status_locked(
                    request.requestId,
                    status="initializing",
                    message="Initializing Codex app server",
                )
                self._raise_if_cancelled_locked(active_request)
                self._ensure_initialized_locked(deadline)
                self._raise_if_cancelled_locked(active_request)
                thread_reused = request.session.conversationId in self._conversation_threads
                self._set_active_request_status_locked(
                    request.requestId,
                    status="starting-thread",
                    message="Starting or reusing Codex thread",
                )
                thread_id = self._get_or_create_thread_locked(
                    request.session.conversationId, model, deadline
                )
                active_request.thread_id = thread_id
                self._set_active_request_status_locked(
                    request.requestId,
                    status="starting-turn",
                    message="Starting Codex turn",
                )
                return self._run_turn_locked(
                    thread_id,
                    request,
                    model,
                    effort,
                    deadline,
                    active_request,
                    thread_reused,
                )
        except CodexAppServerError as exc:
            self._set_active_request_status_locked(
                request.requestId,
                status="failed",
                message=exc.message,
            )
            logger.error(
                "codex_plan_failed",
                extra={
                    "structured": {
                        "requestId": request.requestId,
                        "conversationId": request.session.conversationId,
                        "threadId": active_request.thread_id,
                        "turnId": active_request.codex_turn_id,
                        "code": exc.code,
                        "message": exc.message,
                        "statusCode": exc.status_code,
                    }
                },
            )
            raise
        except Exception as exc:
            self._set_active_request_status_locked(
                request.requestId,
                status="failed",
                message=str(exc),
            )
            logger.exception(
                "codex_plan_unexpected_error",
                extra={
                    "structured": {
                        "requestId": request.requestId,
                        "conversationId": request.session.conversationId,
                        "threadId": active_request.thread_id,
                        "turnId": active_request.codex_turn_id,
                    }
                },
            )
            raise
        finally:
            self._unregister_request(request.requestId)

    def cancel_request(
        self,
        *,
        request_id: str,
        app_session_id: str,
        image_session_id: str,
        conversation_id: str,
        turn_id: str,
    ) -> bool:
        del app_session_id
        del image_session_id
        del turn_id

        matched_active = False
        with self._state_lock:
            self._cancelled_request_ids.add(request_id)
            active_request = self._active_requests.get(request_id)
            if active_request and active_request.conversation_id == conversation_id:
                active_request.cancel_event.set()
                active_request.status = "cancel-requested"
                active_request.message = "Cancellation requested"
                matched_active = True

        return matched_active

    def _register_request(self, request: RequestEnvelope) -> _ActiveRequestState:
        active_request = _ActiveRequestState(
            request_id=request.requestId,
            app_session_id=request.session.appSessionId,
            image_session_id=request.session.imageSessionId,
            conversation_id=request.session.conversationId,
            client_turn_id=request.session.turnId,
        )
        with self._state_lock:
            self._active_requests[request.requestId] = active_request
            if request.requestId in self._cancelled_request_ids:
                active_request.cancel_event.set()
        return active_request

    def _unregister_request(self, request_id: str) -> None:
        with self._state_lock:
            self._active_requests.pop(request_id, None)
            self._cancelled_request_ids.discard(request_id)

    def get_request_progress(
        self,
        *,
        request_id: str,
        app_session_id: str,
        image_session_id: str,
        conversation_id: str,
        turn_id: str,
    ) -> dict[str, Any]:
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
                }

            context = None
            if active_request.thread_id and active_request.codex_turn_id:
                context = self._turn_contexts.get((active_request.thread_id, active_request.codex_turn_id))

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
            }

    def _is_cancelled(self, active_request: _ActiveRequestState) -> bool:
        with self._state_lock:
            return (
                active_request.cancel_event.is_set()
                or active_request.request_id in self._cancelled_request_ids
            )

    def _raise_if_cancelled_locked(self, active_request: _ActiveRequestState | None) -> None:
        if active_request is None or not self._is_cancelled(active_request):
            return

        self._set_active_request_status_locked(
            active_request.request_id,
            status="cancelled",
            message="Chat request was canceled",
        )
        logger.info(
            "codex_request_cancelled",
            extra={
                "structured": {
                    "requestId": active_request.request_id,
                    "conversationId": active_request.conversation_id,
                    "threadId": active_request.thread_id,
                    "codexTurnId": active_request.codex_turn_id,
                }
            },
        )
        self._reset_process_locked()
        raise CodexAppServerError(
            "request_cancelled",
            "Chat request was canceled",
            status_code=499,
        )

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
                if active_request.thread_id == thread_id and active_request.codex_turn_id == turn_id:
                    active_request.status = status
                    active_request.message = message
                    if last_tool_name is not None:
                        active_request.last_tool_name = last_tool_name
                    active_request.progress_version += 1
                    return

    def _ensure_initialized_locked(self, deadline: float) -> None:
        if self._process and self._process.poll() is not None:
            self._reset_process_locked()
        if not self._process:
            self._start_process_locked()
        if self._initialized:
            return

        response = self._send_request_locked(
            "initialize",
            {
                "clientInfo": _CLIENT_INFO,
                "capabilities": {
                    "experimentalApi": True,
                    "optOutNotificationMethods": [],
                },
            },
            deadline,
            None,
        )
        if "result" not in response:
            raise CodexAppServerError("codex_initialize_failed", "Codex initialize failed")
        self._send_notification_locked("initialized")
        self._initialized = True

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

    @classmethod
    def _sanitize_request_for_agent_safety(
        cls, request: RequestEnvelope
    ) -> RequestEnvelope:
        blocked_capability_ids: set[str] = set()
        capability_targets: list[dict[str, Any]] = []
        for capability in request.capabilityManifest.targets:
            if cls._is_disallowed_white_balance_action_path(capability.actionPath):
                blocked_capability_ids.add(capability.capabilityId)
                continue
            capability_targets.append(capability.model_dump(mode="json"))

        editable_settings: list[dict[str, Any]] = []
        blocked_setting_ids: list[str] = []
        for setting in request.imageSnapshot.editableSettings:
            if (
                cls._is_disallowed_white_balance_action_path(setting.actionPath)
                or setting.capabilityId in blocked_capability_ids
            ):
                blocked_capability_ids.add(setting.capabilityId)
                blocked_setting_ids.append(setting.settingId)
                continue
            editable_settings.append(setting.model_dump(mode="json"))

        if blocked_capability_ids:
            capability_targets = [
                capability.model_dump(mode="json")
                for capability in request.capabilityManifest.targets
                if capability.capabilityId not in blocked_capability_ids
                and not cls._is_disallowed_white_balance_action_path(capability.actionPath)
            ]

        if (
            len(capability_targets) == len(request.capabilityManifest.targets)
            and len(editable_settings) == len(request.imageSnapshot.editableSettings)
        ):
            return request

        if not capability_targets:
            raise CodexAppServerError(
                "no_safe_controls_available",
                (
                    "No safe editable controls are available for this image. "
                    "White-balance module controls are blocked."
                ),
                status_code=422,
            )

        payload = request.model_dump(mode="json")
        payload["capabilityManifest"]["targets"] = capability_targets
        payload["imageSnapshot"]["editableSettings"] = editable_settings
        sanitized = RequestEnvelope.model_validate(payload)

        logger.info(
            "safety_policy_filtered_controls",
            extra={
                "structured": {
                    "requestId": request.requestId,
                    "conversationId": request.session.conversationId,
                    "blockedCapabilityCount": len(request.capabilityManifest.targets)
                    - len(capability_targets),
                    "blockedSettingCount": len(request.imageSnapshot.editableSettings)
                    - len(editable_settings),
                    "blockedSettingIds": blocked_setting_ids,
                }
            },
        )
        return sanitized

    @staticmethod
    def _dynamic_tools() -> list[dict[str, Any]]:
        empty_object_schema = {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
        apply_operations_schema = {
            "type": "object",
            "properties": {
                "operations": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "object"},
                }
            },
            "required": ["operations"],
            "additionalProperties": False,
        }
        return [
            {
                "name": _TOOL_GET_IMAGE_STATE,
                "description": (
                    "Get current image state for planning: editable settings and trimmed histogram."
                ),
                "inputSchema": empty_object_schema,
            },
            {
                "name": _TOOL_GET_PREVIEW_IMAGE,
                "description": (
                    "Get the current rendered preview image as a data URL for visual analysis."
                ),
                "inputSchema": empty_object_schema,
            },
            {
                "name": _TOOL_APPLY_OPERATIONS,
                "description": (
                    "Apply one or more darktable operations in the live run and update image state for follow-up tool calls."
                ),
                "inputSchema": apply_operations_schema,
            },
        ]

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
                "structured": {
                    "conversationId": conversation_id,
                    "threadId": thread_id,
                }
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
        active_request: _ActiveRequestState,
        thread_reused: bool,
    ) -> CodexTurnResult:
        started_at = time.monotonic()
        preview_data_url = self._preview_data_url(request)
        turn_input = self._build_turn_input(request, preview_data_url=preview_data_url)
        self._conversation_turn_counts[active_request.conversation_id] = (
            self._conversation_turn_counts.get(active_request.conversation_id, 0) + 1
        )
        turn_index = self._conversation_turn_counts[active_request.conversation_id]
        prompt_text_chars = 0
        image_input_chars = 0
        for item in turn_input:
            if item.get("type") == "text":
                prompt_text_chars += len(str(item.get("text", "")))
            elif item.get("type") == "image":
                image_input_chars += len(str(item.get("url", "")))

        try:
            turn_id: str | None = None
            turn_request = {
                "threadId": thread_id,
                "input": turn_input,
                "outputSchema": self._build_output_schema(),
                "approvalPolicy": _DEFAULT_APPROVAL_POLICY,
                "personality": _DEFAULT_PERSONALITY,
                "effort": effort,
            }
            if model:
                turn_request["model"] = model

            response = self._send_request_locked("turn/start", turn_request, deadline, active_request)
            try:
                turn_id = response["result"]["turn"]["id"]
            except KeyError as exc:
                raise CodexAppServerError(
                    "codex_turn_start_failed", "Codex did not return a turn id"
                ) from exc
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

            state = {
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
                    max_wait_seconds = min(max_wait_seconds, _DEFAULT_MAX_IDLE_SECONDS - idle_seconds)

                message = self._read_message_locked(
                    deadline,
                    active_request,
                    max_wait_seconds=max_wait_seconds,
                )
                if message is None:
                    continue
                state["last_activity_at"] = time.monotonic()
                state["last_activity_method"] = message.get("method") or "jsonrpc-response"
                self._handle_message_locked(message, state)

            if state["turn_error"]:
                raise CodexAppServerError("codex_turn_failed", state["turn_error"])

            raw_message = state["final_message"] or "".join(state["chunks"]).strip()
            if not raw_message:
                raise CodexAppServerError(
                    "codex_empty_response", "Codex completed the turn without returning a plan"
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

    @staticmethod
    def _decode_preview_image(request: RequestEnvelope) -> tuple[str, bytes]:
        preview = request.imageSnapshot.preview
        if preview is None:
            raise CodexAppServerError(
                "codex_preview_unavailable",
                "Image preview is required for agent planning",
                status_code=422,
            )

        try:
            image_bytes = base64.b64decode(preview.base64Data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise CodexAppServerError(
                "codex_preview_decode_failed",
                "Image preview could not be decoded for agent planning",
                status_code=422,
            ) from exc

        mime_type = preview.mimeType or "image/jpeg"
        return mime_type, image_bytes

    @staticmethod
    def _build_data_url(
        mime_type: str,
        image_bytes: bytes,
        *,
        revision_token: str | None = None,
    ) -> str:
        normalized_mime = mime_type.strip() or "image/jpeg"
        if revision_token:
            normalized_mime = f"{normalized_mime};x-darktable-stage={revision_token}"
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:{normalized_mime};base64,{encoded}"

    @classmethod
    def _preview_data_url(cls, request: RequestEnvelope) -> str:
        mime_type, image_bytes = cls._decode_preview_image(request)
        return cls._build_data_url(mime_type, image_bytes)

    def _register_turn_context(
        self,
        thread_id: str,
        turn_id: str,
        request: RequestEnvelope,
        preview_data_url: str,
    ) -> None:
        preview_mime_type, preview_bytes = self._decode_preview_image(request)
        state_payload = json.loads(json.dumps(self._build_prompt_payload(request)))
        image_snapshot = state_payload.get("imageSnapshot", {})
        editable_settings = image_snapshot.get("editableSettings", [])
        setting_by_id: dict[str, dict[str, Any]] = {}
        base_float_setting_numbers: dict[str, float] = {}
        if isinstance(editable_settings, list):
            for setting in editable_settings:
                if not isinstance(setting, dict):
                    continue
                setting_id = setting.get("settingId")
                if isinstance(setting_id, str) and setting_id:
                    setting_by_id[setting_id] = setting
                    if setting.get("kind") == "set-float":
                        current_number = setting.get("currentNumber")
                        if not isinstance(current_number, (int, float)):
                            current_number = setting.get("defaultNumber")
                        if isinstance(current_number, (int, float)):
                            base_float_setting_numbers[setting_id] = float(current_number)
        base_image_revision_id = request.imageSnapshot.imageRevisionId
        max_tool_calls = request.refinement.maxPasses if request.refinement.enabled else 1
        with self._state_lock:
            self._turn_contexts[(thread_id, turn_id)] = _TurnContext(
                base_request=request,
                preview_data_url=preview_data_url,
                base_preview_mime_type=preview_mime_type,
                base_preview_bytes=preview_bytes,
                preview_mime_type=preview_mime_type,
                base_image_revision_id=base_image_revision_id,
                state_payload=state_payload,
                setting_by_id=setting_by_id,
                base_float_setting_numbers=base_float_setting_numbers,
                live_run_enabled=request.refinement.enabled,
                max_tool_calls=max_tool_calls,
            )

    def _clear_turn_context(self, thread_id: str, turn_id: str) -> None:
        with self._state_lock:
            self._turn_contexts.pop((thread_id, turn_id), None)

    def _get_turn_context(self, thread_id: str, turn_id: str) -> _TurnContext | None:
        with self._state_lock:
            return self._turn_contexts.get((thread_id, turn_id))

    def _finalize_plan_with_live_context(
        self,
        plan: AgentPlan,
        context: _TurnContext | None,
    ) -> AgentPlan:
        if context is None:
            return plan

        merged_operations = [operation.model_dump(mode="json") for operation in plan.operations]
        if context.applied_operations:
            merged_operations = list(context.applied_operations) + merged_operations

        if not merged_operations:
            return AgentPlan.model_validate(
                {
                    "assistantText": plan.assistantText,
                    "continueRefining": False if context.live_run_enabled else plan.continueRefining,
                    "operations": [],
                }
            )

        normalized_operations: list[dict[str, Any]] = []
        seen_operation_ids: set[str] = set()
        for index, operation in enumerate(merged_operations, start=1):
            operation_copy = dict(operation)
            candidate_operation_id = str(operation_copy.get("operationId") or f"run-op-{index}")
            operation_id = candidate_operation_id
            duplicate_index = 2
            while operation_id in seen_operation_ids:
                operation_id = f"{candidate_operation_id}-{duplicate_index}"
                duplicate_index += 1
            seen_operation_ids.add(operation_id)
            operation_copy["operationId"] = operation_id
            operation_copy["sequence"] = index
            normalized_operations.append(operation_copy)

        return AgentPlan.model_validate(
            {
                "assistantText": plan.assistantText,
                "continueRefining": False if context.live_run_enabled else plan.continueRefining,
                "operations": normalized_operations,
            }
        )

    @staticmethod
    def _trim_histogram_payload(request: RequestEnvelope) -> dict[str, Any] | None:
        histogram = request.imageSnapshot.histogram
        if histogram is None:
            return None

        luma = histogram.channels.get("luma")
        if luma is None or not luma.bins:
            return None

        source_bins = luma.bins
        source_count = len(source_bins)
        target_count = max(1, min(_DEFAULT_HISTOGRAM_BINS, source_count))

        if target_count == source_count:
            rebinned = list(source_bins)
        else:
            rebinned: list[int] = []
            for index in range(target_count):
                start = (index * source_count) // target_count
                end = ((index + 1) * source_count) // target_count
                if end <= start:
                    end = min(source_count, start + 1)
                rebinned.append(sum(source_bins[start:end]))

        return {
            "binCount": target_count,
            "channels": {
                "luma": {
                    "bins": rebinned,
                }
            },
        }

    def _build_prompt_payload(self, request: RequestEnvelope) -> dict[str, Any]:
        compact_settings: list[dict[str, Any]] = []
        for setting in request.imageSnapshot.editableSettings:
            compact_setting: dict[str, Any] = {
                "moduleId": setting.moduleId,
                "moduleLabel": setting.moduleLabel,
                "settingId": setting.settingId,
                "kind": setting.kind,
                "actionPath": setting.actionPath,
                "supportedModes": setting.supportedModes,
            }
            if setting.kind == "set-float":
                compact_setting["currentNumber"] = setting.currentNumber
                compact_setting["minNumber"] = setting.minNumber
                compact_setting["maxNumber"] = setting.maxNumber
                compact_setting["defaultNumber"] = setting.defaultNumber
                compact_setting["stepNumber"] = setting.stepNumber
            elif setting.kind == "set-choice":
                compact_setting["currentChoiceValue"] = setting.currentChoiceValue
                compact_setting["currentChoiceId"] = setting.currentChoiceId
                compact_setting["defaultChoiceValue"] = setting.defaultChoiceValue
                compact_setting["choices"] = (
                    [choice.model_dump(mode="json") for choice in setting.choices]
                    if setting.choices
                    else []
                )
            elif setting.kind == "set-bool":
                compact_setting["currentBool"] = setting.currentBool
                compact_setting["defaultBool"] = setting.defaultBool
            compact_settings.append(compact_setting)

        metadata = request.imageSnapshot.metadata
        compact_payload: dict[str, Any] = {
            "imageSnapshot": {
                "imageRevisionId": request.imageSnapshot.imageRevisionId,
                "metadata": {
                    "width": metadata.width,
                    "height": metadata.height,
                },
                "editableSettings": compact_settings,
                "histogram": self._trim_histogram_payload(request),
                "preview": (
                    {
                        "mimeType": request.imageSnapshot.preview.mimeType,
                        "width": request.imageSnapshot.preview.width,
                        "height": request.imageSnapshot.preview.height,
                        "base64Data": None,
                    }
                    if request.imageSnapshot.preview
                    else None
                ),
            }
        }
        return compact_payload

    def _build_turn_input(
        self,
        request: RequestEnvelope,
        *,
        preview_data_url: str | None = None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": self._build_turn_prompt(request),
                "text_elements": [],
            }
        ]
        # In live mode, provide the current preview image up front so the first
        # tool call can focus on state or edits instead of fetching an initial image.
        if request.refinement.enabled:
            if preview_data_url is None:
                preview_data_url = self._preview_data_url(request)
            items.append(
                {
                    "type": "image",
                    "url": preview_data_url,
                }
            )
        return items

    def _build_turn_prompt(self, request: RequestEnvelope) -> str:
        live_run_enabled = request.refinement.enabled
        max_tool_calls = request.refinement.maxPasses if live_run_enabled else 1
        live_run_line = (
            "Live run mode is enabled: use apply_operations for iterative edits inside this same run.\n"
            "Initial turn input includes the current preview image.\n"
            "After each apply_operations call, re-check get_image_state and optionally get_preview_image before the next adjustment.\n"
            f"Apply at least one edit batch with apply_operations within the first {_DEFAULT_MAX_TOOL_CALLS_WITHOUT_APPLY} tool calls.\n"
            "When satisfied, return final JSON with continueRefining=false and usually empty operations.\n"
            if live_run_enabled
            else "Single-turn mode: do not call apply_operations; return operations directly in final JSON.\n"
        )
        return (
            "Plan the next darktable response for this request.\n\n"
            f"Goal: {request.refinement.goalText}\n"
            f"Latest user message: {request.message.text}\n"
            f"Refinement: mode={request.refinement.mode}, pass={request.refinement.passIndex}/{request.refinement.maxPasses}\n"
            f"Tool budget: maximum {max_tool_calls} tool calls in this run.\n"
            f"Image: {request.uiContext.imageName or 'unknown'} ({request.imageSnapshot.metadata.width}x{request.imageSnapshot.metadata.height})\n"
            "\n"
            "Use read-only tools only when needed for missing context.\n"
            "In live mode, the initial turn input already includes the current preview image.\n"
            "Use get_image_state for exact editable settings/histogram; use get_preview_image mainly after apply_operations for refreshed visual checks.\n"
            "Use only the tool-provided editable settings and image state.\n"
            f"{live_run_line}"
            "Use moduleId/moduleLabel from get_image_state to group related controls.\n"
            "If the user asks for a broad or aesthetic edit direction, infer a conservative supported edit plan from preview, histogram, and available controls instead of asking for more specificity.\n"
            "When advanced color modules like rgb primaries, color equalizer, or color balance rgb are present, prefer their supported controls for nuanced color shaping instead of flattening everything into exposure changes.\n"
            "White-balance module controls (`iop/temperature/*`) are disabled for safety; use other available color controls.\n"
            "Prefer several small coherent operations over refusing a request that can be partially satisfied with the available controls.\n"
            "Respect refinement state: use refinement.goalText as the target look, treat passIndex/maxPasses as the remaining budget, and set continueRefining=false once additional safe gains are exhausted.\n"
            "Return only the JSON object required by the output schema."
        )

    def _start_process_locked(self) -> None:
        try:
            self._process = subprocess.Popen(
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=self._cwd,
            )
        except OSError as exc:
            raise CodexAppServerError(
                "codex_process_start_failed",
                f"Failed to launch Codex app server: {exc}",
                status_code=503,
            ) from exc

        self._initialized = False
        self._next_request_id = 1
        self._conversation_threads.clear()
        self._conversation_turn_counts.clear()
        self._turn_contexts.clear()

    def _reset_process_locked(self) -> None:
        if self._process:
            try:
                self._process.kill()
            except OSError:
                pass
            try:
                self._process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        self._process = None
        self._initialized = False
        self._next_request_id = 1
        self._conversation_threads.clear()
        self._conversation_turn_counts.clear()
        self._turn_contexts.clear()

    def _send_request_locked(
        self,
        method: str,
        params: Any,
        deadline: float,
        active_request: _ActiveRequestState | None,
    ) -> dict[str, Any]:
        request_id = self._next_request_id
        self._next_request_id += 1
        self._send_json_locked(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )

        while True:
            self._raise_if_cancelled_locked(active_request)
            message = self._read_message_locked(deadline, active_request)
            if message.get("id") == request_id and "method" not in message:
                if "error" in message:
                    error = message["error"]
                    raise CodexAppServerError(
                        "codex_jsonrpc_error",
                        error.get("message", f"Codex {method} failed"),
                    )
                return message
            self._handle_message_locked(message, None)

    def _send_notification_locked(self, method: str, params: Any | None = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self._send_json_locked(payload)

    def _send_json_locked(self, payload: dict[str, Any]) -> None:
        if not self._process or not self._process.stdin:
            raise CodexAppServerError("codex_process_unavailable", "Codex app server is not running")
        try:
            self._process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
            self._process.stdin.flush()
        except OSError as exc:
            self._reset_process_locked()
            raise CodexAppServerError(
                "codex_transport_error", f"Failed to talk to Codex app server: {exc}"
            ) from exc

    def _read_message_locked(
        self,
        deadline: float,
        active_request: _ActiveRequestState | None = None,
        *,
        max_wait_seconds: float | None = None,
    ) -> dict[str, Any] | None:
        if not self._process or not self._process.stdout or not self._process.stderr:
            raise CodexAppServerError("codex_process_unavailable", "Codex app server is not running")

        while True:
            self._raise_if_cancelled_locked(active_request)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CodexAppServerError("codex_timeout", "Codex app server timed out", status_code=504)

            ready, _, _ = select.select(
                [self._process.stdout, self._process.stderr],
                [],
                [],
                min(
                    remaining,
                    0.5 if max_wait_seconds is None else max(0.0, max_wait_seconds),
                ),
            )
            if not ready:
                if self._process.poll() is not None:
                    self._reset_process_locked()
                    raise CodexAppServerError(
                        "codex_process_exited", "Codex app server exited unexpectedly", status_code=503
                    )
                if max_wait_seconds is not None:
                    return None
                continue

            for stream in ready:
                line = stream.readline()
                if not line:
                    continue
                if stream is self._process.stderr:
                    logger.warning("codex_stderr", extra={"structured": {"line": line.rstrip()}})
                    continue
                try:
                    return json.loads(line)
                except json.JSONDecodeError as exc:
                    raise CodexAppServerError(
                        "codex_invalid_json", f"Codex emitted invalid JSON: {line.rstrip()}"
                    ) from exc

    def _handle_message_locked(self, message: dict[str, Any], turn_state: dict[str, Any] | None) -> None:
        if "method" in message and "id" in message:
            self._handle_server_request_locked(message)
            return
        if "method" not in message:
            return

        method = message["method"]
        params = message.get("params", {})

        if method == "error":
            if turn_state and params.get("threadId") == turn_state["thread_id"] and params.get("turnId") == turn_state["turn_id"]:
                error = params.get("error", {})
                turn_state["turn_error"] = self._extract_error_message(
                    error.get("message") or "Codex app server reported an error"
                )
            return

        if not turn_state:
            return

        if method == "item/agentMessage/delta":
            if params.get("threadId") == turn_state["thread_id"] and params.get("turnId") == turn_state["turn_id"]:
                turn_state["chunks"].append(params.get("delta", ""))
            return

        if method == "thread/tokenUsage/updated":
            if params.get("threadId") != turn_state["thread_id"] or params.get("turnId") != turn_state["turn_id"]:
                return
            usage = params.get("tokenUsage", {})
            last_usage = usage.get("last")
            total_usage = usage.get("total")
            if isinstance(last_usage, dict):
                turn_state["token_usage_last"] = last_usage
            if isinstance(total_usage, dict):
                turn_state["token_usage_total"] = total_usage
            return

        if method == "item/completed":
            if params.get("threadId") != turn_state["thread_id"] or params.get("turnId") != turn_state["turn_id"]:
                return
            item = params.get("item", {})
            if item.get("type") == "agentMessage":
                turn_state["final_message"] = item.get("text")
                if item.get("phase") == "final_answer":
                    turn_state["completed"] = True
            return

        if method == "codex/event/task_complete":
            if params.get("id") != turn_state["turn_id"]:
                return
            msg = params.get("msg", {})
            if msg.get("last_agent_message"):
                turn_state["final_message"] = msg["last_agent_message"]
                turn_state["completed"] = True
            return

        if method == "turn/completed":
            if params.get("threadId") != turn_state["thread_id"]:
                return
            turn = params.get("turn", {})
            if turn.get("id") != turn_state["turn_id"]:
                return
            error = turn.get("error")
            if error:
                turn_state["turn_error"] = self._extract_error_message(
                    error.get("message") or "Codex turn failed"
                )
            turn_state["completed"] = True
            return

    def _handle_server_request_locked(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        request_id = message.get("id")
        if request_id is None:
            return

        if method in {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
            "item/permissions/requestApproval",
            "applyPatchApproval",
            "execCommandApproval",
        }:
            logger.warning(
                "codex_request_denied",
                extra={"structured": {"method": method}},
            )
            self._send_json_locked(
                {"jsonrpc": "2.0", "id": request_id, "result": {"decision": "decline"}}
            )
            return

        if method == "item/tool/call":
            response_payload = self._handle_dynamic_tool_call_locked(message)
            self._send_json_locked({"jsonrpc": "2.0", "id": request_id, "result": response_payload})
            return

        logger.warning(
            "codex_request_unsupported",
            extra={"structured": {"method": method}},
        )
        self._send_json_locked(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32000,
                    "message": f"Unsupported Codex server request: {method}",
                },
            }
        )

    def _handle_dynamic_tool_call_locked(self, message: dict[str, Any]) -> dict[str, Any]:
        params = message.get("params", {})
        thread_id = params.get("threadId")
        turn_id = params.get("turnId")
        tool_name = params.get("tool")
        call_id = params.get("callId")

        if not isinstance(thread_id, str) or not isinstance(turn_id, str):
            return {
                "success": False,
                "contentItems": [
                    {
                        "type": "inputText",
                        "text": "Missing threadId/turnId for tool call.",
                    }
                ],
            }

        if not isinstance(tool_name, str):
            return {
                "success": False,
                "contentItems": [
                    {
                        "type": "inputText",
                        "text": "Missing tool name for tool call.",
                    }
                ],
            }

        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return {
                "success": False,
                "contentItems": [
                    {
                        "type": "inputText",
                        "text": "Tool arguments must be an object.",
                    }
                ],
            }

        with self._state_lock:
            context = self._turn_contexts.get((thread_id, turn_id))
            if context is None:
                return {
                    "success": False,
                    "contentItems": [
                        {
                            "type": "inputText",
                            "text": "No active image context is available for this tool call.",
                        }
                    ],
                }

            guardrail_error = self._register_tool_call_progress_locked(context, tool_name)
            if guardrail_error is not None:
                response = self._tool_error_response(guardrail_error)
            elif tool_name == _TOOL_GET_PREVIEW_IMAGE:
                response = {
                    "success": True,
                    "contentItems": [
                        {
                            "type": "inputImage",
                            "imageUrl": context.preview_data_url,
                        }
                    ],
                }
            elif tool_name == _TOOL_GET_IMAGE_STATE:
                payload = context.state_payload
                response = {
                    "success": True,
                    "contentItems": [
                        {
                            "type": "inputText",
                            "text": json.dumps(payload, separators=(",", ":")),
                        }
                    ],
                }
            elif tool_name == _TOOL_APPLY_OPERATIONS:
                response = self._apply_operations_tool_call(context, arguments)
            else:
                response = {
                    "success": False,
                    "contentItems": [
                        {
                            "type": "inputText",
                            "text": (
                                f"Unsupported tool '{tool_name}'. Supported tools: "
                                f"{_TOOL_GET_PREVIEW_IMAGE}, {_TOOL_GET_IMAGE_STATE}, {_TOOL_APPLY_OPERATIONS}."
                            ),
                        }
                    ],
                }
            tool_calls_used = context.tool_calls_used
            max_tool_calls = context.max_tool_calls
            applied_operation_count = len(context.applied_operations)
            read_only_streak = context.consecutive_read_only_tool_calls
            tool_error = None
            if not response["success"]:
                content_items = response.get("contentItems")
                if isinstance(content_items, list):
                    for content_item in content_items:
                        if not isinstance(content_item, dict):
                            continue
                        text = content_item.get("text")
                        if isinstance(text, str) and text:
                            tool_error = text
                            break

        self._set_active_request_status_for_turn_locked(
            thread_id,
            turn_id,
            status="running",
            message=(
                (
                    f"Handled tool {tool_name} ({tool_calls_used}/{max_tool_calls}); "
                    f"{applied_operation_count} live edits"
                )
                if response["success"]
                else (
                    f"Tool {tool_name} failed ({tool_calls_used}/{max_tool_calls}): "
                    f"{tool_error or 'No details provided'}"
                )
            ),
            last_tool_name=tool_name,
        )

        logger.info(
            "codex_tool_call_handled",
            extra={
                "structured": {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "tool": tool_name,
                    "callId": call_id,
                    "success": response["success"],
                    "toolCallsUsed": tool_calls_used,
                    "maxToolCalls": max_tool_calls,
                    "appliedOperationCount": applied_operation_count,
                    "readOnlyToolCallStreak": read_only_streak,
                    "toolError": tool_error,
                }
            },
        )
        return response

    @staticmethod
    def _is_read_only_tool(tool_name: str) -> bool:
        return tool_name in {_TOOL_GET_PREVIEW_IMAGE, _TOOL_GET_IMAGE_STATE}

    def _register_tool_call_progress_locked(
        self,
        context: _TurnContext,
        tool_name: str,
    ) -> str | None:
        context.tool_calls_used += 1
        if context.tool_calls_used > context.max_tool_calls:
            return (
                f"Tool call budget exceeded ({context.max_tool_calls}). "
                "Finalize the run now."
            )

        if (
            context.live_run_enabled
            and not context.applied_operations
            and tool_name != _TOOL_APPLY_OPERATIONS
            and context.tool_calls_used > _DEFAULT_MAX_TOOL_CALLS_WITHOUT_APPLY
        ):
            return (
                "No live edits have been applied yet in live mode. "
                f"Call {_TOOL_APPLY_OPERATIONS} now with concrete operations or finalize."
            )

        if tool_name == _TOOL_APPLY_OPERATIONS:
            context.consecutive_read_only_tool_calls = 0
            return None

        if self._is_read_only_tool(tool_name):
            context.consecutive_read_only_tool_calls += 1
            if (
                context.live_run_enabled
                and context.consecutive_read_only_tool_calls
                > _DEFAULT_MAX_CONSECUTIVE_READ_ONLY_TOOL_CALLS
            ):
                return (
                    "Too many consecutive read-only tool calls. "
                    f"Call {_TOOL_APPLY_OPERATIONS} with concrete edits or finalize now."
                )
            return None

        context.consecutive_read_only_tool_calls = 0
        return None

    @staticmethod
    def _tool_error_response(message: str) -> dict[str, Any]:
        return {
            "success": False,
            "contentItems": [
                {
                    "type": "inputText",
                    "text": message,
                }
            ],
        }

    def _apply_operations_tool_call(
        self,
        context: _TurnContext,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if not context.live_run_enabled:
            return self._tool_error_response(
                "apply_operations is only available when live run mode is enabled."
            )

        raw_operations = arguments.get("operations")
        if not isinstance(raw_operations, list) or not raw_operations:
            return self._tool_error_response("apply_operations requires a non-empty operations array.")

        applied_batch: list[dict[str, Any]] = []
        for raw_operation in raw_operations:
            if not isinstance(raw_operation, dict):
                return self._tool_error_response("Every apply_operations entry must be an object.")
            normalized_operation, error = self._normalize_tool_operation(context, raw_operation)
            if error:
                return self._tool_error_response(error)
            apply_error = self._apply_operation_to_state(context, normalized_operation)
            if apply_error:
                return self._tool_error_response(apply_error)
            applied_batch.append(normalized_operation)
            context.applied_operations.append(normalized_operation)
            context.next_operation_sequence += 1

        image_snapshot = context.state_payload.get("imageSnapshot")
        if isinstance(image_snapshot, dict):
            image_snapshot["imageRevisionId"] = (
                f"{context.base_image_revision_id}:tool-{len(context.applied_operations)}"
            )
        self._refresh_preview_after_operations(context)

        return {
            "success": True,
            "contentItems": [
                {
                    "type": "inputText",
                    "text": (
                        f"Applied {len(applied_batch)} operations in this call; "
                        f"{len(context.applied_operations)} total live edits applied. "
                        "Preview refreshed for get_preview_image."
                    ),
                }
            ],
        }

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))

    def _collect_preview_adjustments(self, context: _TurnContext) -> tuple[float, float, float]:
        brightness_ev = 0.0
        contrast_delta = 0.0
        saturation_delta = 0.0

        for setting_id, setting in context.setting_by_id.items():
            if setting.get("kind") != "set-float":
                continue

            current_number = setting.get("currentNumber")
            if not isinstance(current_number, (int, float)):
                continue
            base_number = context.base_float_setting_numbers.get(setting_id, float(current_number))
            delta = float(current_number) - float(base_number)
            if abs(delta) < 1e-6:
                continue

            action_path = setting.get("actionPath")
            if not isinstance(action_path, str):
                continue
            normalized_path = action_path.lower()

            if normalized_path == "iop/exposure/exposure":
                brightness_ev += delta
                continue
            if "black level" in normalized_path or normalized_path.endswith("/black"):
                brightness_ev += 0.35 * delta
            if "toneequal/" in normalized_path and any(
                token in normalized_path
                for token in ("whites", "highlights", "mid", "shadows", "blacks", "brightness")
            ):
                brightness_ev += 0.25 * delta
            if any(token in normalized_path for token in ("contrast", "brilliance", "clarity")):
                contrast_delta += 0.6 * delta
            if any(
                token in normalized_path for token in ("saturation", "sat_", "chroma", "vibrance")
            ):
                saturation_delta += 0.7 * delta

        return brightness_ev, contrast_delta, saturation_delta

    def _render_applied_preview(self, context: _TurnContext) -> tuple[str, bytes] | None:
        if Image is None or ImageEnhance is None:
            return None

        try:
            with Image.open(io.BytesIO(context.base_preview_bytes)) as source_image:
                image = source_image.convert("RGB")
        except Exception:
            return None

        brightness_ev, contrast_delta, saturation_delta = self._collect_preview_adjustments(context)
        brightness_factor = self._clamp(2.0**brightness_ev, 0.1, 6.0)
        contrast_factor = self._clamp(1.0 + contrast_delta, 0.2, 3.0)
        saturation_factor = self._clamp(1.0 + saturation_delta, 0.0, 3.0)

        if abs(brightness_factor - 1.0) > 1e-3:
            image = ImageEnhance.Brightness(image).enhance(brightness_factor)
        if abs(contrast_factor - 1.0) > 1e-3:
            image = ImageEnhance.Contrast(image).enhance(contrast_factor)
        if abs(saturation_factor - 1.0) > 1e-3:
            image = ImageEnhance.Color(image).enhance(saturation_factor)

        output = io.BytesIO()
        base_mime = context.base_preview_mime_type.lower()
        if "png" in base_mime:
            image.save(output, format="PNG")
            return "image/png", output.getvalue()

        image.save(output, format="JPEG", quality=85, optimize=True)
        return "image/jpeg", output.getvalue()

    def _refresh_preview_after_operations(self, context: _TurnContext) -> None:
        applied_count = len(context.applied_operations)
        rendered = self._render_applied_preview(context)
        if rendered is not None:
            context.preview_mime_type, rendered_bytes = rendered
            context.preview_data_url = self._build_data_url(
                context.preview_mime_type,
                rendered_bytes,
                revision_token=str(applied_count),
            )
            return

        context.preview_data_url = self._build_data_url(
            context.preview_mime_type,
            context.base_preview_bytes,
            revision_token=str(applied_count),
        )

    def _normalize_tool_operation(
        self,
        context: _TurnContext,
        raw_operation: dict[str, Any],
    ) -> tuple[dict[str, Any], str | None]:
        required_keys = ("kind", "target", "value")
        for key in required_keys:
            if key not in raw_operation:
                return {}, f"operation is missing required member '{key}'"

        operation_id = raw_operation.get("operationId")
        if not isinstance(operation_id, str) or not operation_id:
            operation_id = f"tool-op-{context.next_operation_sequence}"

        operation_candidate = {
            "operationId": operation_id,
            "sequence": context.next_operation_sequence,
            "kind": raw_operation["kind"],
            "target": raw_operation["target"],
            "value": raw_operation["value"],
            "reason": raw_operation.get("reason"),
            "constraints": raw_operation.get(
                "constraints",
                {
                    "onOutOfRange": "clamp",
                    "onRevisionMismatch": "fail",
                },
            ),
        }

        try:
            validated = AgentPlan.model_validate(
                {
                    "assistantText": "tool staging",
                    "continueRefining": False,
                    "operations": [operation_candidate],
                }
            ).operations[0]
        except Exception as exc:
            return {}, f"operation failed schema validation: {exc}"

        operation = validated.model_dump(mode="json")
        setting_id = operation.get("target", {}).get("settingId")
        if not isinstance(setting_id, str) or setting_id not in context.setting_by_id:
            return {}, f"operation targets unknown settingId '{setting_id}'"
        return operation, None

    @staticmethod
    def _choice_mapping(setting: dict[str, Any]) -> dict[int, str]:
        choices = setting.get("choices")
        mapping: dict[int, str] = {}
        if not isinstance(choices, list):
            return mapping
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            value = choice.get("choiceValue")
            choice_id = choice.get("choiceId")
            if isinstance(value, int) and isinstance(choice_id, str) and choice_id:
                mapping[value] = choice_id
        return mapping

    @staticmethod
    def _is_disallowed_white_balance_action_path(action_path: str) -> bool:
        return any(
            action_path.startswith(prefix)
            for prefix in _DISALLOWED_WHITE_BALANCE_ACTION_PATH_PREFIXES
        )

    def _apply_operation_to_state(self, context: _TurnContext, operation: dict[str, Any]) -> str | None:
        target = operation.get("target")
        if not isinstance(target, dict):
            return "operation target must be an object"

        setting_id = target.get("settingId")
        action_path = target.get("actionPath")
        if not isinstance(setting_id, str) or not isinstance(action_path, str):
            return "operation target requires settingId and actionPath"

        setting = context.setting_by_id.get(setting_id)
        if not isinstance(setting, dict):
            return f"unknown settingId '{setting_id}'"

        if setting.get("actionPath") != action_path:
            return (
                f"actionPath mismatch for settingId '{setting_id}': expected "
                f"{setting.get('actionPath')}, got {action_path}"
            )

        if self._is_disallowed_white_balance_action_path(action_path):
            return (
                "White-balance module controls are disabled for safety "
                "(iop/temperature/*). Use other available color controls instead."
            )

        kind = operation.get("kind")
        if setting.get("kind") != kind:
            return f"kind mismatch for settingId '{setting_id}'"

        value = operation.get("value")
        if not isinstance(value, dict):
            return "operation value must be an object"

        mode = value.get("mode")
        supported_modes = setting.get("supportedModes")
        if not isinstance(mode, str):
            return "operation value requires mode"
        if isinstance(supported_modes, list) and mode not in supported_modes:
            return f"mode '{mode}' is not supported by settingId '{setting_id}'"

        if kind == "set-float":
            number_value = value.get("number")
            if not isinstance(number_value, (int, float)):
                return f"set-float operation requires numeric value.number for '{setting_id}'"
            current = setting.get("currentNumber")
            if not isinstance(current, (int, float)):
                current = setting.get("defaultNumber")
            if not isinstance(current, (int, float)):
                current = 0.0
            next_value = float(current) + float(number_value) if mode == "delta" else float(number_value)
            min_number = setting.get("minNumber")
            max_number = setting.get("maxNumber")
            if isinstance(min_number, (int, float)):
                next_value = max(next_value, float(min_number))
            if isinstance(max_number, (int, float)):
                next_value = min(next_value, float(max_number))
            setting["currentNumber"] = next_value
            return None

        if kind == "set-choice":
            choice_value = value.get("choiceValue")
            if not isinstance(choice_value, int):
                return f"set-choice operation requires integer value.choiceValue for '{setting_id}'"
            choice_mapping = self._choice_mapping(setting)
            if choice_mapping and choice_value not in choice_mapping:
                return f"choiceValue {choice_value} is not valid for '{setting_id}'"
            setting["currentChoiceValue"] = choice_value
            if choice_value in choice_mapping:
                setting["currentChoiceId"] = choice_mapping[choice_value]
            return None

        if kind == "set-bool":
            bool_value = value.get("boolValue")
            if not isinstance(bool_value, bool):
                return f"set-bool operation requires boolean value.boolValue for '{setting_id}'"
            setting["currentBool"] = bool_value
            return None

        return f"unsupported operation kind '{kind}'"

    @staticmethod
    def _extract_error_message(message: str) -> str:
        try:
            payload = json.loads(message)
        except (TypeError, json.JSONDecodeError):
            return message

        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                nested = error.get("message")
                if isinstance(nested, str) and nested:
                    return nested
        return message
