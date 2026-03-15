from __future__ import annotations

import json
import logging
import os
import select
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass
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
_DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("DARKTABLE_AGENT_CODEX_TIMEOUT_SECONDS", "90"))
_DEFAULT_PERSONALITY = os.environ.get("DARKTABLE_AGENT_CODEX_PERSONALITY", "pragmatic")
_DEFAULT_REASONING_EFFORT = os.environ.get("DARKTABLE_AGENT_CODEX_REASONING_EFFORT", "high")
_DEFAULT_MODEL = os.environ.get("DARKTABLE_AGENT_CODEX_MODEL", "gpt-5.4")
_DEFAULT_SANDBOX = os.environ.get("DARKTABLE_AGENT_CODEX_SANDBOX", "read-only")
_DEFAULT_APPROVAL_POLICY = "never"

_THREAD_DEVELOPER_INSTRUCTIONS = """You are darktableAgent, a structured editing planner for darktable.

Never use tools, never request approvals, never ask for user input, and never run commands.
Return exactly one JSON object matching the output schema.

You are given:
- the latest user message
- a capability manifest describing writable darktable controls
- a current image snapshot with metadata, history, editable settings, and optionally a 1k rendered JPEG preview and histogram

Rules:
- Only plan operations that are explicitly supported by the capability manifest and editable settings snapshot.
- Never invent capability IDs, setting IDs, or action paths.
- Use zero operations only when the request is unsupported, unsafe, or impossible with the supplied capabilities.
- Keep assistantText brief and user-facing.
- Every operation must be immediately executable by darktable.
- Use the supplied preview and histogram when they are present.
- Prefer the specific editable settings and current values supplied in the image snapshot over generic photography assumptions.
- Treat broad creative requests like "make this a polished gallery-ready landscape" as valid when preview, histogram, or current settings are available. Infer a conservative edit plan instead of asking for narrower instructions.
- When the user asks for a full edit or a target look, proactively choose a small coherent set of supported global adjustments that fit the visible image and the current settings.
- Favor restrained, high-confidence edits over extreme changes. Preserve highlight detail, avoid crushed shadows, and avoid oversaturation unless the user explicitly asks for a stylized look.
- Prefer existing supported controls for global tone, color, detail, and presence before giving up on the request.
- If visual context is present, do not answer with "be more specific" unless no safe supported edit can be inferred.
- Use mode "delta" only for set-float operations when the capability supports delta.
- Use mode "set" for all set-choice and set-bool operations.
- For set-choice operations, return value.choiceValue and prefer including value.choiceId when it is known from the editable setting choices.
- For set-bool operations, return value.boolValue.
- Use the exact target.settingId from imageSnapshot.editableSettings so the operation is tied to the intended control instance.
- When the user requests an exact EV change, use that exact exposure delta if the exposure setting exists and supports delta.
- When the user requests to brighten or darken without an exact amount and an exposure setting exists, default to a single exposure delta of +0.7 EV or -0.7 EV.
- When the user asks for an unsupported action, explain the limitation and return no operations.
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
        self._process: subprocess.Popen[str] | None = None
        self._initialized = False
        self._next_request_id = 1
        self._conversation_threads: dict[str, str] = {}

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
        with self._lock:
            self._ensure_initialized_locked(deadline)
            thread_id = self._get_or_create_thread_locked(request.session.conversationId, deadline)
            return self._run_turn_locked(thread_id, request, deadline)

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
                    "experimentalApi": False,
                    "optOutNotificationMethods": [],
                },
            },
            deadline,
        )
        if "result" not in response:
            raise CodexAppServerError("codex_initialize_failed", "Codex initialize failed")
        self._send_notification_locked("initialized")
        self._initialized = True

    def _get_or_create_thread_locked(self, conversation_id: str, deadline: float) -> str:
        existing = self._conversation_threads.get(conversation_id)
        if existing:
            return existing

        params: dict[str, Any] = {
            "cwd": self._cwd,
            "approvalPolicy": _DEFAULT_APPROVAL_POLICY,
            "sandbox": _DEFAULT_SANDBOX,
            "personality": _DEFAULT_PERSONALITY,
            "developerInstructions": _THREAD_DEVELOPER_INSTRUCTIONS,
        }
        if _DEFAULT_MODEL:
            params["model"] = _DEFAULT_MODEL

        response = self._send_request_locked("thread/start", params, deadline)
        try:
            thread_id = response["result"]["thread"]["id"]
        except KeyError as exc:
            raise CodexAppServerError(
                "codex_thread_start_failed", "Codex did not return a thread id"
            ) from exc

        self._conversation_threads[conversation_id] = thread_id
        return thread_id

    def _run_turn_locked(
        self,
        thread_id: str,
        request: RequestEnvelope,
        deadline: float,
    ) -> CodexTurnResult:
        turn_request = {
            "threadId": thread_id,
            "input": [
                {
                    "type": "text",
                    "text": self._build_turn_prompt(request),
                    "text_elements": [],
                }
            ],
            "outputSchema": self._build_output_schema(),
            "approvalPolicy": _DEFAULT_APPROVAL_POLICY,
            "personality": _DEFAULT_PERSONALITY,
            "effort": _DEFAULT_REASONING_EFFORT,
        }
        if _DEFAULT_MODEL:
            turn_request["model"] = _DEFAULT_MODEL

        response = self._send_request_locked("turn/start", turn_request, deadline)
        try:
            turn_id = response["result"]["turn"]["id"]
        except KeyError as exc:
            raise CodexAppServerError(
                "codex_turn_start_failed", "Codex did not return a turn id"
            ) from exc

        state = {
            "thread_id": thread_id,
            "turn_id": turn_id,
            "chunks": [],
            "final_message": None,
            "turn_error": None,
            "completed": False,
        }

        while not state["completed"]:
            message = self._read_message_locked(deadline)
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

        return CodexTurnResult(
            plan=plan,
            thread_id=thread_id,
            turn_id=turn_id,
            raw_message=raw_message,
        )

    def _build_turn_prompt(self, request: RequestEnvelope) -> str:
        payload = request.model_dump(mode="json")
        return (
            "Plan the next darktable response for this request.\n\n"
            "Use the capability manifest and image state exactly as provided.\n"
            "If the user asks for a broad or aesthetic edit direction, infer a conservative supported edit plan from the preview, histogram, history, and current settings instead of asking for more specificity.\n"
            "Prefer several small coherent operations over refusing a request that can be partially satisfied with the available controls.\n"
            "Return only the JSON object required by the output schema.\n\n"
            f"{json.dumps(payload, separators=(',', ':'))}"
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

    def _send_request_locked(self, method: str, params: Any, deadline: float) -> dict[str, Any]:
        request_id = self._next_request_id
        self._next_request_id += 1
        self._send_json_locked(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )

        while True:
            message = self._read_message_locked(deadline)
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

    def _read_message_locked(self, deadline: float) -> dict[str, Any]:
        if not self._process or not self._process.stdout or not self._process.stderr:
            raise CodexAppServerError("codex_process_unavailable", "Codex app server is not running")

        while True:
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

        rejection_result: dict[str, Any] | None = None
        if method in {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
            "item/permissions/requestApproval",
            "applyPatchApproval",
            "execCommandApproval",
        }:
            rejection_result = {"decision": "denied"}

        if rejection_result is not None:
            logger.warning(
                "codex_request_denied",
                extra={"structured": {"method": method}},
            )
            self._send_json_locked({"jsonrpc": "2.0", "id": request_id, "result": rejection_result})
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
