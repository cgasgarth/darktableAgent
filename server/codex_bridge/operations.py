from __future__ import annotations

# pyright: reportAttributeAccessIssue=false

import copy
import io
import json
from typing import Any

from shared.protocol import AgentPlan

from .config import _TOOL_APPLY_OPERATIONS, _WHITE_BALANCE_ACTION_PATH_PREFIXES, logger
from .models import TurnContext


class OperationsMixin:
    def _apply_operations_tool_call(
        self,
        context: TurnContext,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if not context.live_run_enabled:
            return self._tool_error_response(
                "apply_operations is only available when live run mode is enabled."
            )

        raw_operations = arguments.get("operations")
        if not isinstance(raw_operations, list) or not raw_operations:
            return self._tool_error_response(
                "apply_operations requires a non-empty operations array."
            )

        normalized_batch: list[dict[str, Any]] = []
        for index, raw_operation in enumerate(raw_operations):
            if not isinstance(raw_operation, dict):
                self._log_white_balance_tool_call(
                    context,
                    raw_operations,
                    [],
                    success=False,
                    error="Every apply_operations entry must be an object.",
                )
                return self._tool_error_response(
                    "Every apply_operations entry must be an object."
                )
            normalized_operation, error = self._normalize_tool_operation(
                context,
                raw_operation,
                sequence_number=context.next_operation_sequence + index,
            )
            if error:
                self._log_white_balance_tool_call(
                    context,
                    raw_operations,
                    [],
                    success=False,
                    error=error,
                )
                return self._tool_error_response(error)
            normalized_batch.append(normalized_operation)

        ordered_batch = self._order_operations_for_apply(normalized_batch)
        simulated_settings = copy.deepcopy(context.setting_by_id)
        for operation in ordered_batch:
            apply_error, _ = self._apply_operation_to_settings(
                simulated_settings, operation
            )
            if apply_error:
                self._log_white_balance_tool_call(
                    context,
                    ordered_batch,
                    [],
                    success=False,
                    error=apply_error,
                )
                return self._tool_error_response(apply_error)

        applied_batch: list[dict[str, Any]] = []
        for operation in ordered_batch:
            apply_error, _ = self._apply_operation_to_settings(
                context.setting_by_id, operation
            )
            if apply_error:
                self._log_white_balance_tool_call(
                    context,
                    ordered_batch,
                    applied_batch,
                    success=False,
                    error=apply_error,
                )
                return self._tool_error_response(apply_error)
            applied_batch.append(operation)
            context.applied_operations.append(operation)

        context.next_operation_sequence += len(applied_batch)
        context.last_applied_batch = list(applied_batch)
        image_snapshot = context.state_payload.get("imageSnapshot")
        if isinstance(image_snapshot, dict):
            image_snapshot["imageRevisionId"] = (
                f"{context.base_image_revision_id}:tool-{len(context.applied_operations)}"
            )
        self._refresh_preview_after_operations(context)
        context.requires_render_callback = True
        context.render_event.clear()
        context.rendered_preview_bytes = None
        self._log_white_balance_tool_call(
            context,
            ordered_batch,
            applied_batch,
            success=True,
        )

        return {
            "success": True,
            "contentItems": [
                {
                    "type": "inputText",
                    "text": (
                        f"Applied {len(applied_batch)} operations in this call; "
                        f"{len(context.applied_operations)} total live edits applied. "
                        "Refreshed preview image included below."
                    ),
                }
            ],
        }

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
