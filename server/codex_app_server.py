from __future__ import annotations

import base64
import binascii
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
_TOOL_GET_IMAGE_STATE = "get_image_state"
_TOOL_GET_PREVIEW_IMAGE = "get_preview_image"

_THREAD_DEVELOPER_INSTRUCTIONS = """You are darktableAgent, a structured editing planner for darktable.

Use tools to gather image context before planning edits:
- call `get_preview_image` to inspect the latest rendered preview
- call `get_image_state` to inspect editable settings and histogram
Return exactly one JSON object matching the output schema after tool calls.

Use preview as primary visual context. Use histogram + editable settings as constraints.
Only emit operations targeting provided settingId/actionPath pairs. Never invent IDs or paths.
Keep edits coherent, conservative, and executable.
If user intent is broad, infer a reasonable plan from the visible image instead of asking for more specificity.
Prefer advanced color controls (`colorequal`, `colorbalancergb`, `primaries`) when available for nuanced color work.

Refinement rules:
- Always optimize toward refinement.goalText.
- In single-turn mode, continueRefining must be false.
- In multi-turn mode, set continueRefining true only if another pass is likely useful after these operations apply.
- Set continueRefining false when image is good enough, gains are speculative, or operations is empty.
- automaticContinuation=true means this is the same ongoing agent run after darktable already applied prior operations.
- In continuation passes, treat the newly supplied preview + histogram as refreshed visual feedback for the same goal, and refine from there.
- Do not ask the user to re-state intent during continuation passes.

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


@dataclass(slots=True)
class _TurnContext:
    request: RequestEnvelope
    preview_data_url: str


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
        deadline = time.monotonic() + self._timeout_seconds
        active_request = self._register_request(request)
        try:
            model = self._model_for_request(request)
            effort = self._effort_for_request(request)
            with self._lock:
                self._raise_if_cancelled_locked(active_request)
                self._ensure_initialized_locked(deadline)
                self._raise_if_cancelled_locked(active_request)
                thread_reused = request.session.conversationId in self._conversation_threads
                thread_id = self._get_or_create_thread_locked(
                    request.session.conversationId, model, deadline
                )
                active_request.thread_id = thread_id
                return self._run_turn_locked(
                    thread_id,
                    request,
                    model,
                    effort,
                    deadline,
                    active_request,
                    thread_reused,
                )
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

    def _is_cancelled(self, active_request: _ActiveRequestState) -> bool:
        with self._state_lock:
            return (
                active_request.cancel_event.is_set()
                or active_request.request_id in self._cancelled_request_ids
            )

    def _raise_if_cancelled_locked(self, active_request: _ActiveRequestState | None) -> None:
        if active_request is None or not self._is_cancelled(active_request):
            return

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

    @staticmethod
    def _dynamic_tools() -> list[dict[str, Any]]:
        empty_object_schema = {
            "type": "object",
            "properties": {},
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
        turn_input = self._build_turn_input(request)
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

            state = {
                "thread_id": thread_id,
                "turn_id": turn_id,
                "chunks": [],
                "final_message": None,
                "turn_error": None,
                "completed": False,
                "token_usage_last": None,
                "token_usage_total": None,
            }

            while not state["completed"]:
                self._raise_if_cancelled_locked(active_request)
                message = self._read_message_locked(deadline, active_request)
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
    def _preview_data_url(request: RequestEnvelope) -> str:
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
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    def _register_turn_context(
        self,
        thread_id: str,
        turn_id: str,
        request: RequestEnvelope,
        preview_data_url: str,
    ) -> None:
        with self._state_lock:
            self._turn_contexts[(thread_id, turn_id)] = _TurnContext(
                request=request,
                preview_data_url=preview_data_url,
            )

    def _clear_turn_context(self, thread_id: str, turn_id: str) -> None:
        with self._state_lock:
            self._turn_contexts.pop((thread_id, turn_id), None)

    def _get_turn_context(self, thread_id: str, turn_id: str) -> _TurnContext | None:
        with self._state_lock:
            return self._turn_contexts.get((thread_id, turn_id))

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
        is_followup = request.refinement.automaticContinuation
        compact_settings: list[dict[str, Any]] = []
        for setting in request.imageSnapshot.editableSettings:
            compact_setting: dict[str, Any] = {
                "settingId": setting.settingId,
                "kind": setting.kind,
                "actionPath": setting.actionPath,
                "supportedModes": setting.supportedModes,
            }
            if not is_followup:
                compact_setting["moduleId"] = setting.moduleId
                compact_setting["moduleLabel"] = setting.moduleLabel
            if setting.kind == "set-float":
                compact_setting["minNumber"] = setting.minNumber
                compact_setting["maxNumber"] = setting.maxNumber
                if not is_followup:
                    compact_setting["stepNumber"] = setting.stepNumber
            elif setting.kind == "set-choice":
                compact_setting["choices"] = (
                    [choice.model_dump(mode="json") for choice in setting.choices]
                    if setting.choices
                    else []
                )
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

    def _build_turn_input(self, request: RequestEnvelope) -> list[dict[str, Any]]:
        return [
            {
                "type": "text",
                "text": self._build_turn_prompt(request),
                "text_elements": [],
            }
        ]

    def _build_turn_prompt(self, request: RequestEnvelope) -> str:
        is_followup = request.refinement.automaticContinuation
        module_grouping_line = (
            "Use moduleId/moduleLabel from get_image_state to group related controls.\n"
            if not is_followup
            else "Follow-up state may omit module labels; rely on settingId/actionPath and goal continuity.\n"
        )
        continuation_line = (
            "This is an automatic continuation pass after darktable applied prior operations and refreshed image state.\n"
            if is_followup
            else ""
        )
        return (
            "Plan the next darktable response for this request.\n\n"
            f"Goal: {request.refinement.goalText}\n"
            f"Latest user message: {request.message.text}\n"
            f"Refinement: mode={request.refinement.mode}, pass={request.refinement.passIndex}/{request.refinement.maxPasses}, automaticContinuation={str(request.refinement.automaticContinuation).lower()}\n"
            f"Image: {request.uiContext.imageName or 'unknown'} ({request.imageSnapshot.metadata.width}x{request.imageSnapshot.metadata.height})\n"
            "\n"
            "Call get_preview_image and get_image_state before returning a final plan.\n"
            "Use only the tool-provided editable settings and image state.\n"
            f"{continuation_line}"
            f"{module_grouping_line}"
            "If the user asks for a broad or aesthetic edit direction, infer a conservative supported edit plan from preview, histogram, and available controls instead of asking for more specificity.\n"
            "When advanced color modules like rgb primaries, color equalizer, or color balance rgb are present, prefer their supported controls for nuanced color shaping instead of flattening everything into exposure changes.\n"
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
    ) -> dict[str, Any]:
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
                min(remaining, 0.5),
            )
            if not ready:
                if self._process.poll() is not None:
                    self._reset_process_locked()
                    raise CodexAppServerError(
                        "codex_process_exited", "Codex app server exited unexpectedly", status_code=503
                    )
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

        context = self._get_turn_context(thread_id, turn_id)
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

        if tool_name == _TOOL_GET_PREVIEW_IMAGE:
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
            payload = self._build_prompt_payload(context.request)
            response = {
                "success": True,
                "contentItems": [
                    {
                        "type": "inputText",
                        "text": json.dumps(payload, separators=(",", ":")),
                    }
                ],
            }
        else:
            response = {
                "success": False,
                "contentItems": [
                    {
                        "type": "inputText",
                        "text": f"Unsupported tool '{tool_name}'. Supported tools: {_TOOL_GET_PREVIEW_IMAGE}, {_TOOL_GET_IMAGE_STATE}.",
                    }
                ],
            }

        logger.info(
            "codex_tool_call_handled",
            extra={
                "structured": {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "tool": tool_name,
                    "callId": call_id,
                    "success": response["success"],
                }
            },
        )
        return response

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
