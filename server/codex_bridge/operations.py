from __future__ import annotations

# pyright: reportAttributeAccessIssue=false

import copy
import json
from typing import Any

from shared.protocol import AgentPlan

from .apply_batch import prepare_apply_batch
from .config import _TOOL_APPLY_OPERATIONS, _WHITE_BALANCE_ACTION_PATH_PREFIXES, logger
from .models import TurnContext


class OperationsMixin:
    def _apply_operations_tool_call(
        self,
        context: TurnContext,
        arguments: dict[str, Any],
        *,
        thread_id: str | None = None,
        turn_id: str | None = None,
    ) -> dict[str, Any]:
        if not context.live_run_enabled:
            return self._tool_error_response(
                "apply_operations is only available when live run mode is enabled."
            )

        prepared_batch, prepare_error = prepare_apply_batch(
            context,
            arguments,
            normalize_operation=lambda raw_operation,
            sequence_number: self._normalize_tool_operation(
                context,
                raw_operation,
                sequence_number=sequence_number,
            ),
        )
        if prepare_error:
            attempted = arguments.get("operations")
            if not isinstance(attempted, list):
                attempted = []
            self._log_white_balance_tool_call(
                context,
                attempted,
                [],
                success=False,
                error=prepare_error,
            )
            return self._tool_error_response(prepare_error)

        assert prepared_batch is not None
        ordered_batch = self._order_operations_for_apply(
            prepared_batch.normalized_batch
        )
        attempted_operations_for_logging = ordered_batch
        render_warnings = prepared_batch.render_warnings
        simulated_settings = copy.deepcopy(context.setting_by_id)
        for operation in ordered_batch:
            apply_error, _ = self._apply_operation_to_settings(
                simulated_settings, operation
            )
            if apply_error:
                self._log_white_balance_tool_call(
                    context,
                    attempted_operations_for_logging,
                    [],
                    success=False,
                    error=apply_error,
                )
                return self._tool_error_response(apply_error)
        applied_batch: list[dict[str, Any]] = []
        step_summaries: list[str] = []
        latest_preview_url: str | None = None
        latest_verifier_result: dict[str, Any] | None = None

        for step_index, operation in enumerate(ordered_batch, start=1):
            apply_error = self._apply_live_operation_step(context, operation)
            if apply_error:
                self._log_white_balance_tool_call(
                    context,
                    attempted_operations_for_logging,
                    applied_batch,
                    success=False,
                    error=apply_error,
                )
                return self._tool_error_response(apply_error)

            applied_batch.append(operation)
            step_summary = self._summarize_live_operation(context, operation)
            step_summaries.append(step_summary)
            context.last_applied_summary = step_summary

            if thread_id and turn_id:
                self._set_active_request_status_for_turn_locked(
                    thread_id,
                    turn_id,
                    status="running",
                    message=(
                        f"Applied live edit step {step_index}/{len(ordered_batch)}: "
                        f"{step_summary}"
                    ),
                    last_tool_name=_TOOL_APPLY_OPERATIONS,
                )

            preview_url, verifier_result, warning = self._wait_for_live_render(context)
            if preview_url is not None:
                latest_preview_url = preview_url
            if verifier_result is not None:
                latest_verifier_result = verifier_result
            if warning is not None:
                render_warnings.append(warning)
        self._log_white_balance_tool_call(
            context,
            attempted_operations_for_logging,
            applied_batch,
            success=True,
        )

        content_items: list[dict[str, Any]] = [
            {
                "type": "inputText",
                "text": (
                    f"Applied {len(applied_batch)} operations stepwise in this call; "
                    f"{len(context.applied_operations)} total live edits applied. "
                    f"Steps: {'; '.join(step_summaries)}. "
                    "Refreshed preview image included below."
                ),
            }
        ]
        if latest_preview_url is not None:
            content_items.append(
                {
                    "type": "inputImage",
                    "imageUrl": latest_preview_url,
                }
            )
        for warning in render_warnings:
            content_items.append({"type": "inputText", "text": warning})
        if latest_verifier_result is not None:
            content_items.append(
                {
                    "type": "inputText",
                    "text": self._verifier_feedback_text(latest_verifier_result),
                }
            )
        return {"success": True, "contentItems": content_items}

    def _apply_live_operation_step(
        self,
        context: TurnContext,
        operation: dict[str, Any],
    ) -> str | None:
        apply_error, _ = self._apply_operation_to_settings(
            context.setting_by_id, operation
        )
        if apply_error:
            return apply_error

        context.applied_operations.append(operation)
        context.next_operation_sequence += 1
        context.last_applied_batch = [operation]
        image_snapshot = context.state_payload.get("imageSnapshot")
        if isinstance(image_snapshot, dict):
            image_snapshot["imageRevisionId"] = (
                f"{context.base_image_revision_id}:tool-{len(context.applied_operations)}"
            )
        self._refresh_preview_after_operations(context)
        context.requires_render_callback = True
        context.render_event.clear()
        context.rendered_preview_bytes = None
        return None

    def _wait_for_live_render(
        self, context: TurnContext
    ) -> tuple[str | None, dict[str, Any] | None, str | None]:
        logger.info(
            "waiting_for_mid_turn_render",
            extra={
                "structured": {
                    "threadId": context.base_request.session.conversationId,
                    "turnId": context.base_request.session.turnId,
                }
            },
        )
        render_arrived = context.render_event.wait(timeout=15.0)
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
            verifier_result = self._build_live_verifier_feedback(context)
            return context.preview_data_url, verifier_result, None

        warning = "Warning: mid-turn render timed out. The preview image may be stale."
        logger.warning(
            "mid_turn_render_timeout",
            extra={
                "structured": {
                    "conversationId": context.base_request.session.conversationId,
                    "turnId": context.base_request.session.turnId,
                }
            },
        )
        return None, None, warning

    def _summarize_live_operation(
        self,
        context: TurnContext,
        operation: dict[str, Any],
    ) -> str:
        target = operation.get("target")
        target_dict = target if isinstance(target, dict) else {}
        action_path = str(target_dict.get("actionPath") or "unknown")
        setting_id = str(target_dict.get("settingId") or "")
        setting = context.setting_by_id.get(setting_id, {})
        module_label = str(setting.get("moduleLabel") or "")
        control_label = str(setting.get("label") or action_path.rsplit("/", 1)[-1])
        label = " / ".join(part for part in (module_label, control_label) if part)
        if not label:
            label = action_path

        value = operation.get("value")
        if not isinstance(value, dict):
            return label

        kind = operation.get("kind")
        if kind == "set-float":
            number = value.get("number")
            mode = value.get("mode")
            if isinstance(number, (int, float)):
                if mode == "delta":
                    return f"{label} {float(number):+0.3f}"
                return f"{label} = {float(number):0.3f}"
        if kind == "set-choice":
            choice_id = value.get("choiceId")
            choice_value = value.get("choiceValue")
            if isinstance(choice_id, str) and choice_id:
                return f"{label} -> {choice_id}"
            if isinstance(choice_value, int):
                return f"{label} -> choice {choice_value}"
        if kind == "set-bool":
            bool_value = value.get("boolValue")
            if isinstance(bool_value, bool):
                return f"{label} -> {'on' if bool_value else 'off'}"
        return label

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))

    def _refresh_preview_after_operations(self, context: TurnContext) -> None:
        pass

    def _normalize_tool_operation(
        self,
        context: TurnContext,
        raw_operation: dict[str, Any],
        *,
        sequence_number: int,
    ) -> tuple[dict[str, Any], str | None]:
        for key in ("kind", "target", "value"):
            if key not in raw_operation:
                return {}, f"operation is missing required member '{key}'"

        operation_id = raw_operation.get("operationId")
        if not isinstance(operation_id, str) or not operation_id:
            operation_id = f"tool-op-{sequence_number}"

        operation_candidate = {
            "operationId": operation_id,
            "sequence": sequence_number,
            "kind": raw_operation["kind"],
            "target": raw_operation["target"],
            "value": raw_operation["value"],
            "reason": raw_operation.get("reason"),
            "constraints": raw_operation.get(
                "constraints",
                {"onOutOfRange": "clamp", "onRevisionMismatch": "fail"},
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
        target = operation.get("target")
        if not isinstance(target, dict):
            return {}, "operation target must be an object"

        setting_id = target.get("settingId")
        action_path = target.get("actionPath")
        if not isinstance(setting_id, str):
            return {}, f"operation targets unknown settingId '{setting_id}'"
        if setting_id not in context.setting_by_id:
            if isinstance(action_path, str):
                matches = self._setting_ids_for_action_path(
                    context.setting_by_id, action_path
                )
                if len(matches) == 1:
                    target["settingId"] = matches[0]
                    return operation, None
            return {}, f"operation targets unknown settingId '{setting_id}'"
        return operation, None

    @staticmethod
    def _setting_ids_for_action_path(
        setting_by_id: dict[str, dict[str, Any]],
        action_path: str,
    ) -> list[str]:
        return [
            setting_id
            for setting_id, setting in setting_by_id.items()
            if setting.get("actionPath") == action_path
        ]

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
    def _is_white_balance_action_path(action_path: str) -> bool:
        return any(
            action_path.startswith(prefix)
            for prefix in _WHITE_BALANCE_ACTION_PATH_PREFIXES
        )

    @classmethod
    def _white_balance_operation_rank(
        cls, operation: dict[str, Any]
    ) -> tuple[int, str]:
        target = operation.get("target")
        action_path = target.get("actionPath") if isinstance(target, dict) else None
        if not isinstance(action_path, str):
            return (99, "")
        leaf = action_path.rsplit("/", 1)[-1].lower()
        kind = operation.get("kind")
        if kind == "set-bool":
            return (0, leaf)
        if kind == "set-choice":
            return (1, leaf)
        if leaf == "finetune":
            return (2, leaf)
        if leaf == "temperature":
            return (3, leaf)
        if leaf == "tint":
            return (4, leaf)
        channel_order = {
            "red": 5,
            "green": 6,
            "blue": 7,
            "emerald": 8,
            "yellow": 9,
            "various": 9,
        }
        return (channel_order.get(leaf, 99), leaf)

    def _order_operations_for_apply(
        self, operations: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        ordered = list(operations)
        wb_indexes = [
            index
            for index, operation in enumerate(operations)
            if self._is_white_balance_action_path(
                str(operation.get("target", {}).get("actionPath") or "")
            )
        ]
        if len(wb_indexes) < 2:
            return ordered
        wb_operations = [operations[index] for index in wb_indexes]
        wb_operations.sort(key=self._white_balance_operation_rank)
        for index, operation in zip(wb_indexes, wb_operations, strict=False):
            ordered[index] = operation
        return ordered

    def _log_white_balance_tool_call(
        self,
        context: TurnContext,
        attempted_operations: list[Any],
        applied_operations: list[Any],
        *,
        success: bool,
        error: str | None = None,
    ) -> None:
        def _extract_paths(operations: list[Any]) -> list[str]:
            paths: list[str] = []
            for operation in operations:
                if not isinstance(operation, dict):
                    continue
                target = operation.get("target")
                if not isinstance(target, dict):
                    continue
                action_path = target.get("actionPath")
                if isinstance(action_path, str) and self._is_white_balance_action_path(
                    action_path
                ):
                    paths.append(action_path)
            return paths

        attempted_paths = _extract_paths(attempted_operations)
        applied_paths = _extract_paths(applied_operations)
        if not attempted_paths and not applied_paths:
            return

        logger.info(
            "apply_operations_white_balance",
            extra={
                "structured": {
                    "requestId": context.base_request.requestId,
                    "conversationId": context.base_request.session.conversationId,
                    "tool": _TOOL_APPLY_OPERATIONS,
                    "success": success,
                    "attemptedWhiteBalanceActionPaths": attempted_paths,
                    "appliedWhiteBalanceActionPaths": applied_paths,
                    "error": error,
                }
            },
        )

    def _apply_operation_to_settings(
        self,
        setting_by_id: dict[str, dict[str, Any]],
        operation: dict[str, Any],
    ) -> tuple[str | None, dict[str, Any] | None]:
        target = operation.get("target")
        if not isinstance(target, dict):
            return "operation target must be an object", None

        setting_id = target.get("settingId")
        action_path = target.get("actionPath")
        if not isinstance(setting_id, str) or not isinstance(action_path, str):
            return "operation target requires settingId and actionPath", None

        setting = setting_by_id.get(setting_id)
        if not isinstance(setting, dict):
            return f"unknown settingId '{setting_id}'", None
        if setting.get("actionPath") != action_path:
            return (
                f"actionPath mismatch for settingId '{setting_id}': expected "
                f"{setting.get('actionPath')}, got {action_path}",
                None,
            )

        kind = operation.get("kind")
        if setting.get("kind") != kind:
            return f"kind mismatch for settingId '{setting_id}'", None
        value = operation.get("value")
        if not isinstance(value, dict):
            return "operation value must be an object", None

        mode = value.get("mode")
        supported_modes = setting.get("supportedModes")
        if not isinstance(mode, str):
            return "operation value requires mode", None
        if isinstance(supported_modes, list) and mode not in supported_modes:
            return f"mode '{mode}' is not supported by settingId '{setting_id}'", None

        if kind == "set-float":
            number_value = value.get("number")
            if not isinstance(number_value, (int, float)):
                return (
                    f"set-float operation requires numeric value.number for '{setting_id}'",
                    None,
                )
            current = setting.get("currentNumber")
            if not isinstance(current, (int, float)):
                current = setting.get("defaultNumber")
            if not isinstance(current, (int, float)):
                current = 0.0
            requested_number = float(number_value)
            resolved_number = (
                float(current) + requested_number
                if mode == "delta"
                else requested_number
            )
            next_value = resolved_number
            min_number = setting.get("minNumber")
            max_number = setting.get("maxNumber")
            if isinstance(min_number, (int, float)):
                next_value = max(next_value, float(min_number))
            if isinstance(max_number, (int, float)):
                next_value = min(next_value, float(max_number))
            setting["currentNumber"] = next_value
            return None, {
                "actionPath": action_path,
                "settingId": setting_id,
                "kind": kind,
                "mode": mode,
                "requestedNumber": requested_number,
                "resolvedNumber": resolved_number,
                "appliedNumber": next_value,
                "wasClamped": abs(next_value - resolved_number) > 1e-12,
            }

        if kind == "set-choice":
            choice_value = value.get("choiceValue")
            if not isinstance(choice_value, int):
                return (
                    f"set-choice operation requires integer value.choiceValue for '{setting_id}'",
                    None,
                )
            choice_mapping = self._choice_mapping(setting)
            if choice_mapping and choice_value not in choice_mapping:
                return (
                    f"choiceValue {choice_value} is not valid for '{setting_id}'",
                    None,
                )
            choice_id = value.get("choiceId")
            if isinstance(choice_id, str) and choice_mapping.get(choice_value) not in {
                None,
                choice_id,
            }:
                expected_choice_id = choice_mapping.get(choice_value)
                return (
                    f"choiceId mismatch for '{setting_id}': expected {expected_choice_id}, got {choice_id}",
                    None,
                )
            setting["currentChoiceValue"] = choice_value
            if choice_value in choice_mapping:
                setting["currentChoiceId"] = choice_mapping[choice_value]
            return None, {
                "actionPath": action_path,
                "settingId": setting_id,
                "kind": kind,
                "mode": mode,
                "requestedChoiceValue": choice_value,
                "appliedChoiceValue": choice_value,
                "appliedChoiceId": setting.get("currentChoiceId"),
            }

        if kind == "set-bool":
            bool_value = value.get("boolValue")
            if not isinstance(bool_value, bool):
                return (
                    f"set-bool operation requires boolean value.boolValue for '{setting_id}'",
                    None,
                )
            setting["currentBool"] = bool_value
            return None, {
                "actionPath": action_path,
                "settingId": setting_id,
                "kind": kind,
                "mode": mode,
                "appliedBoolValue": bool_value,
            }

        return f"unsupported operation kind '{kind}'", None

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
