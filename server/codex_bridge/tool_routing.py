from __future__ import annotations

# pyright: reportAttributeAccessIssue=false

import json
from typing import Any

from .config import (
    _DEFAULT_MAX_CONSECUTIVE_READ_ONLY_TOOL_CALLS,
    _DEFAULT_MAX_TOOL_CALLS_WITHOUT_APPLY,
    _TOOL_APPLY_OPERATIONS,
    _TOOL_GET_IMAGE_STATE,
    _TOOL_GET_PLAYBOOK,
    _TOOL_GET_PREVIEW_IMAGE,
    logger,
)
from .intent_router import list_playbooks, load_playbook


class ToolRoutingMixin:
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
                },
                "canonicalActions": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "object"},
                },
            },
            "anyOf": [
                {"required": ["operations"]},
                {"required": ["canonicalActions"]},
            ],
            "additionalProperties": False,
        }
        get_playbook_schema = {
            "type": "object",
            "properties": {
                "playbookId": {
                    "type": "string",
                    "enum": [entry.id for entry in list_playbooks()],
                }
            },
            "required": ["playbookId"],
            "additionalProperties": False,
        }
        return [
            {
                "name": _TOOL_GET_IMAGE_STATE,
                "description": "Get current image state for planning: editable settings, trimmed histogram, and compact analysis signals.",
                "inputSchema": empty_object_schema,
            },
            {
                "name": _TOOL_GET_PREVIEW_IMAGE,
                "description": "Get the current rendered preview image as a data URL for visual analysis.",
                "inputSchema": empty_object_schema,
            },
            {
                "name": _TOOL_GET_PLAYBOOK,
                "description": "Fetch one planning playbook by id. Choose playbooks yourself from the request and current image signals.",
                "inputSchema": get_playbook_schema,
            },
            {
                "name": _TOOL_APPLY_OPERATIONS,
                "description": "Apply darktable operations in the live run. You may provide raw operations or canonicalActions; supported canonical actions are bound to concrete controls before stepwise live application and render refresh.",
                "inputSchema": apply_operations_schema,
            },
        ]

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
                "codex_request_denied", extra={"structured": {"method": method}}
            )
            self._send_json_locked(
                {"jsonrpc": "2.0", "id": request_id, "result": {"decision": "decline"}}
            )
            return

        if method == "item/tool/call":
            response_payload = self._handle_dynamic_tool_call_locked(message)
            self._send_json_locked(
                {"jsonrpc": "2.0", "id": request_id, "result": response_payload}
            )
            return

        logger.warning(
            "codex_request_unsupported", extra={"structured": {"method": method}}
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

    def _handle_dynamic_tool_call_locked(
        self, message: dict[str, Any]
    ) -> dict[str, Any]:
        params = message.get("params", {})
        thread_id = params.get("threadId")
        turn_id = params.get("turnId")
        tool_name = params.get("tool")
        call_id = params.get("callId")

        if not isinstance(thread_id, str) or not isinstance(turn_id, str):
            return self._tool_error_response("Missing threadId/turnId for tool call.")
        if not isinstance(tool_name, str):
            return self._tool_error_response("Missing tool name for tool call.")

        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return self._tool_error_response("Tool arguments must be an object.")

        tool_status_message: str | None = None

        with self._state_lock:
            context = self._turn_contexts.get((thread_id, turn_id))
            if context is None:
                return self._tool_error_response(
                    "No active image context is available for this tool call."
                )

            guardrail_error = self._register_tool_call_progress_locked(
                context, tool_name
            )

        if guardrail_error is not None:
            response = self._tool_error_response(guardrail_error)
        elif tool_name == _TOOL_GET_PREVIEW_IMAGE:
            response = {
                "success": True,
                "contentItems": [
                    {"type": "inputImage", "imageUrl": context.preview_data_url}
                ],
            }
        elif tool_name == _TOOL_GET_IMAGE_STATE:
            response = {
                "success": True,
                "contentItems": [
                    {
                        "type": "inputText",
                        "text": json.dumps(
                            context.state_payload, separators=(",", ":")
                        ),
                    }
                ],
            }
        elif tool_name == _TOOL_GET_PLAYBOOK:
            playbook_id = arguments.get("playbookId")
            if not isinstance(playbook_id, str) or not playbook_id:
                response = self._tool_error_response(
                    "get_playbook requires a playbookId string."
                )
            else:
                try:
                    playbook = load_playbook(playbook_id)
                except ValueError as exc:
                    response = self._tool_error_response(str(exc))
                else:
                    tool_status_message = f"Using playbook {playbook['title']}."
                    response = {
                        "success": True,
                        "contentItems": [
                            {
                                "type": "inputText",
                                "text": json.dumps(playbook, separators=(",", ":")),
                            }
                        ],
                    }
        elif tool_name == _TOOL_APPLY_OPERATIONS:
            response = self._apply_operations_tool_call(
                context,
                arguments,
                thread_id=thread_id,
                turn_id=turn_id,
            )
        else:
            response = self._tool_error_response(
                f"Unsupported tool '{tool_name}'. Supported tools: {_TOOL_GET_PREVIEW_IMAGE}, {_TOOL_GET_IMAGE_STATE}, {_TOOL_GET_PLAYBOOK}, {_TOOL_APPLY_OPERATIONS}."
            )

        with self._state_lock:
            tool_calls_used = context.tool_calls_used
            max_tool_calls = context.max_tool_calls
            applied_operation_count = len(context.applied_operations)
            read_only_streak = context.consecutive_read_only_tool_calls
            last_applied_summary = context.last_applied_summary
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

        if response["success"] and tool_status_message:
            progress_message = tool_status_message
        elif response["success"]:
            progress_message = (
                f"Handled tool {tool_name} ({tool_calls_used}/{max_tool_calls}); {applied_operation_count} live edits"
                + (
                    f". Latest step: {last_applied_summary}"
                    if tool_name == _TOOL_APPLY_OPERATIONS and last_applied_summary
                    else ""
                )
            )
        else:
            progress_message = f"Tool {tool_name} failed ({tool_calls_used}/{max_tool_calls}): {tool_error or 'No details provided'}"

        self._set_active_request_status_for_turn_locked(
            thread_id,
            turn_id,
            status="running",
            message=progress_message,
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

        requires_render = (
            getattr(context, "requires_render_callback", False)
            and tool_name != _TOOL_APPLY_OPERATIONS
        )
        if requires_render:
            logger.info(
                "waiting_for_mid_turn_render",
                extra={"structured": {"threadId": thread_id, "turnId": turn_id}},
            )
            render_arrived = context.render_event.wait(timeout=15.0)

            with self._state_lock:
                context.requires_render_callback = False
                rendered_bytes = context.rendered_preview_bytes
                context.rendered_preview_bytes = None

            if render_arrived and rendered_bytes:
                context.preview_mime_type = "image/jpeg"
                context.current_preview_bytes = rendered_bytes
                context.preview_data_url = self._build_data_url(
                    "image/jpeg",
                    rendered_bytes,
                    revision_token=str(len(context.applied_operations)),
                )
                if response.get("success"):
                    response.setdefault("contentItems", []).append(
                        {
                            "type": "inputImage",
                            "imageUrl": context.preview_data_url,
                        }
                    )
                    if tool_name == _TOOL_APPLY_OPERATIONS:
                        verifier_result = self._build_live_verifier_feedback(context)
                        response.setdefault("contentItems", []).append(
                            {
                                "type": "inputText",
                                "text": self._verifier_feedback_text(verifier_result),
                            }
                        )
            else:
                logger.warning(
                    "mid_turn_render_timeout",
                    extra={"structured": {"threadId": thread_id, "turnId": turn_id}},
                )
                if response.get("success"):
                    response.setdefault("contentItems", []).append(
                        {
                            "type": "inputText",
                            "text": "Warning: mid-turn render timed out. The preview image may be stale.",
                        }
                    )

        return response

    @staticmethod
    def _is_read_only_tool(tool_name: str) -> bool:
        return tool_name in {
            _TOOL_GET_PREVIEW_IMAGE,
            _TOOL_GET_IMAGE_STATE,
            _TOOL_GET_PLAYBOOK,
        }

    def _register_tool_call_progress_locked(
        self, context, tool_name: str
    ) -> str | None:  # type: ignore[no-untyped-def]
        context.tool_calls_used += 1
        if context.tool_calls_used > context.max_tool_calls:
            return f"Tool call budget exceeded ({context.max_tool_calls}). Finalize the run now."

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
            "contentItems": [{"type": "inputText", "text": message}],
        }
