from __future__ import annotations

import os
import shlex
import subprocess
import threading
import time
from pathlib import Path

from shared.protocol import RequestEnvelope

from .config import _DEFAULT_COMMAND, _DEFAULT_TIMEOUT_SECONDS, _REPO_ROOT, logger
from .errors import CodexAppServerError
from .models import CodexTurnResult
from .operations import OperationsMixin
from .prompting import PromptingMixin
from .request_state import RequestStateMixin
from .tool_routing import ToolRoutingMixin
from .transport import TransportMixin
from .turns import TurnsMixin


class CodexAppServerBridge(
    TurnsMixin,
    ToolRoutingMixin,
    OperationsMixin,
    PromptingMixin,
    TransportMixin,
    RequestStateMixin,
):
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
        self._active_requests = {}
        self._cancelled_requests = {}
        self._turn_contexts = {}

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
