from __future__ import annotations

# pyright: reportAttributeAccessIssue=false

import json
import select
import subprocess
import time
from typing import Any, cast

from .config import _CLIENT_INFO, logger
from .errors import CodexAppServerError
from .models import ActiveRequestState


class TransportMixin:
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
            raise CodexAppServerError(
                "codex_initialize_failed", "Codex initialize failed"
            )
        self._send_notification_locked("initialized")
        self._initialized = True

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
        if hasattr(self, "_conversation_histories"):
            self._conversation_histories.clear()
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
        if hasattr(self, "_conversation_histories"):
            self._conversation_histories.clear()
        self._turn_contexts.clear()

    def _send_request_locked(
        self,
        method: str,
        params: Any,
        deadline: float,
        active_request: ActiveRequestState | None,
    ) -> dict[str, Any]:
        request_id = self._next_request_id
        self._next_request_id += 1
        self._send_json_locked(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )

        while True:
            self._raise_if_cancelled_locked(active_request)
            message = self._read_message_locked(deadline, active_request)
            if message is None:
                continue
            if message.get("id") == request_id and "method" not in message:
                if "error" in message:
                    error = message["error"]
                    error_message = (
                        error.get("message") if isinstance(error, dict) else None
                    )
                    raise CodexAppServerError(
                        "codex_jsonrpc_error",
                        error_message
                        if isinstance(error_message, str)
                        else f"Codex {method} failed",
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
            raise CodexAppServerError(
                "codex_process_unavailable", "Codex app server is not running"
            )
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
        active_request: ActiveRequestState | None = None,
        *,
        max_wait_seconds: float | None = None,
    ) -> dict[str, Any] | None:
        if not self._process or not self._process.stdout or not self._process.stderr:
            raise CodexAppServerError(
                "codex_process_unavailable", "Codex app server is not running"
            )

        while True:
            self._raise_if_cancelled_locked(active_request)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CodexAppServerError(
                    "codex_timeout", "Codex app server timed out", status_code=504
                )

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
                        "codex_process_exited",
                        "Codex app server exited unexpectedly",
                        status_code=503,
                    )
                if max_wait_seconds is not None:
                    return None
                continue

            for stream in ready:
                line = stream.readline()
                if not line:
                    continue
                if stream is self._process.stderr:
                    logger.warning(
                        "codex_stderr", extra={"structured": {"line": line.rstrip()}}
                    )
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise CodexAppServerError(
                        "codex_invalid_json",
                        f"Codex emitted invalid JSON: {line.rstrip()}",
                    ) from exc
                if not isinstance(payload, dict):
                    raise CodexAppServerError(
                        "codex_invalid_json",
                        f"Codex emitted non-object JSON: {line.rstrip()}",
                    )
                return cast(dict[str, Any], payload)
