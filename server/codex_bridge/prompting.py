from __future__ import annotations

# pyright: reportAttributeAccessIssue=false

import base64
import binascii
import json
from typing import cast

from shared.protocol import AgentPlan, JsonObject, RequestEnvelope

from .config import _DEFAULT_HISTOGRAM_BINS, _DEFAULT_MAX_TOOL_CALLS_WITHOUT_APPLY
from .errors import CodexAppServerError
from .image_signals import build_image_analysis_signals
from .intent_router import playbook_catalog_payload
from .models import TurnContext
from .prompt_templates import render_prompt_template

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
        state_payload = cast(
            JsonObject, json.loads(json.dumps(self._build_prompt_payload(request)))
        )
        image_snapshot = state_payload.get("imageSnapshot", {})
        editable_settings = image_snapshot.get("editableSettings", [])
        setting_by_id: dict[str, JsonObject] = {}
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
        max_tool_calls = self._effective_tool_budget(request)
        with self._state_lock:
            self._turn_contexts[(thread_id, turn_id)] = TurnContext(
                base_request=request,
                preview_data_url=preview_data_url,
                base_preview_mime_type=preview_mime_type,
                base_preview_bytes=preview_bytes,
                current_preview_bytes=preview_bytes,
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

        if context.live_run_enabled and context.applied_operations:
            merged_operations = list(context.applied_operations)
        else:
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

        normalized_operations: list[JsonObject] = []
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
    def _rebin(source_bins: list[int], target_count: int) -> list[int]:
        source_count = len(source_bins)
        if target_count >= source_count:
            return list(source_bins)
        rebinned: list[int] = []
        for index in range(target_count):
            start = (index * source_count) // target_count
            end = ((index + 1) * source_count) // target_count
            if end <= start:
                end = min(source_count, start + 1)
            rebinned.append(sum(source_bins[start:end]))
        return rebinned

    @classmethod
    def _trim_histogram_payload(cls, request: RequestEnvelope) -> JsonObject | None:
        histogram = request.imageSnapshot.histogram
        if histogram is None:
            return None

        trimmed_channels: dict[str, dict[str, list[int]]] = {}
        for channel_name in ("luma", "red", "green", "blue"):
            channel = histogram.channels.get(channel_name)
            if channel is None or not channel.bins:
                continue
            target_count = max(1, min(_DEFAULT_HISTOGRAM_BINS, len(channel.bins)))
            trimmed_channels[channel_name] = {
                "bins": cls._rebin(channel.bins, target_count)
            }

        if not trimmed_channels:
            return None

        first_channel = next(iter(trimmed_channels.values()))
        return {
            "binCount": len(first_channel["bins"]),
            "channels": trimmed_channels,
        }

    def _build_prompt_payload(self, request: RequestEnvelope) -> JsonObject:
        compact_settings: list[JsonObject] = []
        for setting in request.imageSnapshot.editableSettings:
            compact_setting: JsonObject = {
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
        metadata_payload: JsonObject = {
            "width": metadata.width,
            "height": metadata.height,
        }
        for exif_field in (
            "cameraMaker",
            "cameraModel",
            "exifExposureSeconds",
            "exifAperture",
            "exifIso",
            "exifFocalLength",
        ):
            value = getattr(metadata, exif_field, None)
            if value is not None:
                metadata_payload[exif_field] = value
        analysis_signals = request.imageSnapshot.analysisSignals
        return {
            "imageSnapshot": {
                "imageRevisionId": request.imageSnapshot.imageRevisionId,
                "metadata": metadata_payload,
                "editableSettings": compact_settings,
                "histogram": self._trim_histogram_payload(request),
                "analysisSignals": (
                    analysis_signals.model_dump(mode="json")
                    if analysis_signals is not None
                    else build_image_analysis_signals(request)
                ),
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
    ) -> list[JsonObject]:
        items: list[JsonObject] = []

        conv_id = request.session.conversationId
        history = getattr(self, "_conversation_histories", {}).get(conv_id)
        if history:
            history_text = "Prior turns in this conversation:\n" + "\n".join(
                history[-5:]
            )
            items.append({"type": "text", "text": history_text, "text_elements": []})

        items.append(
            {
                "type": "text",
                "text": self._build_turn_prompt(request),
                "text_elements": [],
            }
        )
        items.append(
            {
                "type": "text",
                "text": "Current image state JSON:\n"
                + json.dumps(
                    self._build_prompt_payload(request), separators=(",", ":")
                ),
                "text_elements": [],
            }
        )
        if request.refinement.enabled:
            if preview_data_url is None:
                preview_data_url = self._preview_data_url(request)
            items.append({"type": "image", "url": preview_data_url})
        return items

    def _build_turn_prompt(self, request: RequestEnvelope) -> str:
        live_run_enabled = request.refinement.enabled
        max_tool_calls = self._effective_tool_budget(request)
        meta = request.imageSnapshot.metadata

        exif_parts: list[str] = []
        if getattr(meta, "cameraMaker", None):
            exif_parts.append(
                f"{meta.cameraMaker} {getattr(meta, 'cameraModel', '')}".strip()
            )
        if getattr(meta, "exifIso", None) is not None:
            exif_parts.append(f"ISO {meta.exifIso}")
        if getattr(meta, "exifAperture", None) is not None:
            exif_parts.append(f"f/{meta.exifAperture}")
        if getattr(meta, "exifFocalLength", None) is not None:
            exif_parts.append(f"{meta.exifFocalLength}mm")
        if (
            getattr(meta, "exifExposureSeconds", None) is not None
            and meta.exifExposureSeconds > 0
        ):
            if meta.exifExposureSeconds >= 1:
                exif_parts.append(f"{meta.exifExposureSeconds}s")
            else:
                exif_parts.append(f"1/{int(1 / meta.exifExposureSeconds)}s")
        exif_line = f"EXIF: {', '.join(exif_parts)}\n" if exif_parts else ""

        if live_run_enabled:
            mode_block = (
                "Live run mode is enabled: use apply_operations for iterative edits inside this same run.\n"
                "Inside each apply_operations call, operations are auto-applied one at a time with a fresh render after each step.\n"
                "Turn input includes the current preview image, editable settings, and histogram.\n"
                "After each apply_operations call, inspect the refreshed preview and re-check get_image_state when you need refreshed exact state.\n"
                f"Apply at least one edit batch within the first {_DEFAULT_MAX_TOOL_CALLS_WITHOUT_APPLY + 2} tool calls.\n"
                "When satisfied, return final JSON with continueRefining=false and usually empty operations.\n"
                "In multi-turn mode the final JSON should summarize the run; continueRefining must be false.\n"
            )
        else:
            mode_block = "Single-turn mode: do not call apply_operations; return operations directly in final JSON.\n"

        return render_prompt_template(
            "turn_prompt.j2",
            goal_text=request.refinement.goalText,
            latest_user_message=request.message.text,
            refinement_mode=request.refinement.mode,
            pass_index=request.refinement.passIndex,
            max_passes=request.refinement.maxPasses,
            max_tool_calls=max_tool_calls,
            image_name=request.uiContext.imageName or "unknown",
            width=meta.width,
            height=meta.height,
            exif_line=exif_line.strip(),
            playbooks=playbook_catalog_payload(),
            live_run_enabled=live_run_enabled,
            apply_budget_window=_DEFAULT_MAX_TOOL_CALLS_WITHOUT_APPLY + 2,
        )

    @staticmethod
    def _effective_tool_budget(request: RequestEnvelope) -> int:
        if not request.refinement.enabled:
            return 1
        return max(request.refinement.maxPasses * 3, 15)
