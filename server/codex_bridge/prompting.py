from __future__ import annotations

# pyright: reportAttributeAccessIssue=false

import base64
import binascii
import json
from typing import Any

from shared.protocol import AgentPlan, RequestEnvelope

from .config import _DEFAULT_HISTOGRAM_BINS, _DEFAULT_MAX_TOOL_CALLS_WITHOUT_APPLY
from .errors import CodexAppServerError
from .models import TurnContext

try:
    from PIL import Image, ImageEnhance
except Exception:  # pragma: no cover
    Image = None
    ImageEnhance = None


class PromptingMixin:
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
                            base_float_setting_numbers[setting_id] = float(
                                current_number
                            )
        max_tool_calls = (
            request.refinement.maxPasses if request.refinement.enabled else 1
        )
        with self._state_lock:
            self._turn_contexts[(thread_id, turn_id)] = TurnContext(
                base_request=request,
                preview_data_url=preview_data_url,
                base_preview_mime_type=preview_mime_type,
                base_preview_bytes=preview_bytes,
                preview_mime_type=preview_mime_type,
                base_image_revision_id=request.imageSnapshot.imageRevisionId,
                state_payload=state_payload,
                setting_by_id=setting_by_id,
                base_float_setting_numbers=base_float_setting_numbers,
                live_run_enabled=request.refinement.enabled,
                max_tool_calls=max_tool_calls,
            )

    def _clear_turn_context(self, thread_id: str, turn_id: str) -> None:
        with self._state_lock:
            self._turn_contexts.pop((thread_id, turn_id), None)

    def _get_turn_context(self, thread_id: str, turn_id: str) -> TurnContext | None:
        with self._state_lock:
            return self._turn_contexts.get((thread_id, turn_id))

    def _finalize_plan_with_live_context(
        self,
        plan: AgentPlan,
        context: TurnContext | None,
    ) -> AgentPlan:
        if context is None:
            return plan

        merged_operations = [
            operation.model_dump(mode="json") for operation in plan.operations
        ]
        if context.applied_operations:
            merged_operations = list(context.applied_operations) + merged_operations

        if not merged_operations:
            return AgentPlan.model_validate(
                {
                    "assistantText": plan.assistantText,
                    "continueRefining": False
                    if context.live_run_enabled
                    else plan.continueRefining,
                    "operations": [],
                }
            )

        normalized_operations: list[dict[str, Any]] = []
        seen_operation_ids: set[str] = set()
        for index, operation in enumerate(merged_operations, start=1):
            operation_copy = dict(operation)
            candidate_operation_id = str(
                operation_copy.get("operationId") or f"run-op-{index}"
            )
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
                "continueRefining": False
                if context.live_run_enabled
                else plan.continueRefining,
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

        return {"binCount": target_count, "channels": {"luma": {"bins": rebinned}}}

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
        return {
            "imageSnapshot": {
                "imageRevisionId": request.imageSnapshot.imageRevisionId,
                "metadata": {"width": metadata.width, "height": metadata.height},
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
            },
            {
                "type": "text",
                "text": "Current image state JSON:\n"
                + json.dumps(
                    self._build_prompt_payload(request), separators=(",", ":")
                ),
                "text_elements": [],
            },
        ]
        if request.refinement.enabled:
            if preview_data_url is None:
                preview_data_url = self._preview_data_url(request)
            items.append({"type": "image", "url": preview_data_url})
        return items

    def _build_turn_prompt(self, request: RequestEnvelope) -> str:
        live_run_enabled = request.refinement.enabled
        max_tool_calls = request.refinement.maxPasses if live_run_enabled else 1
        live_run_line = (
            "Live run mode is enabled: use apply_operations for iterative edits inside this same run.\n"
            "Initial turn input includes the current preview image plus the current editable settings and luma histogram snapshot.\n"
            "After each apply_operations call, inspect the refreshed preview image returned in that tool response and re-check get_image_state when you need refreshed exact state before the next adjustment.\n"
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
            "Initial turn input already includes the current editable settings, luma histogram snapshot, and in live mode the current preview image.\n"
            "Use get_image_state mainly after apply_operations when you need refreshed exact state; the refreshed preview image is returned directly by successful apply_operations calls, so use get_preview_image only for extra visual checks between edit batches.\n"
            "Use only the tool-provided editable settings and image state.\n"
            f"{live_run_line}"
            "Use moduleId/moduleLabel from the provided image state to group related controls.\n"
            "If the user asks for a broad or aesthetic edit direction, infer a conservative supported edit plan from preview, histogram, and available controls instead of asking for more specificity.\n"
            "When advanced color modules like rgb primaries, color equalizer, or color balance rgb are present, prefer their supported controls for nuanced color shaping instead of flattening everything into exposure changes.\n"
            "White-balance controls (`iop/temperature/*`) are available when present. Respect their bounds, supported modes, and exact target IDs.\n"
            "When batching multiple white-balance edits, apply preset-like controls before finetune/temperature/tint/channel multipliers.\n"
            "Prefer several small coherent operations over refusing a request that can be partially satisfied with the available controls.\n"
            "Respect refinement state: use refinement.goalText as the target look, treat passIndex/maxPasses as the remaining budget, and set continueRefining=false once additional safe gains are exhausted.\n"
            "Return only the JSON object required by the output schema."
        )
