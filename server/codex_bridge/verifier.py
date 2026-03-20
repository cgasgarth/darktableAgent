from __future__ import annotations

import io
import json
from typing import Any

from .config import logger
from .models import TurnContext

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None


def _clamp_ratio(value: float) -> float:
    return max(0.0, min(1.0, value))


class VerifierMixin:
    @staticmethod
    def _preview_metrics(image_bytes: bytes) -> dict[str, float] | None:
        if Image is None or not image_bytes:
            return None

        try:
            with Image.open(io.BytesIO(image_bytes)) as image:
                image = image.convert("RGB")
                image.thumbnail((256, 256))
                pixels = list(image.getdata())
        except Exception:
            return None

        if not pixels:
            return None

        total = float(len(pixels))
        clipped_highlights = 0
        crushed_shadows = 0
        saturation_extremes = 0
        mean_luma = 0.0

        for red, green, blue in pixels:
            luma = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255.0
            mean_luma += luma
            channel_max = max(red, green, blue)
            channel_min = min(red, green, blue)
            if channel_max >= 250:
                clipped_highlights += 1
            if luma <= 0.04:
                crushed_shadows += 1
            if channel_max >= 250 and channel_min <= 5:
                saturation_extremes += 1

        return {
            "meanLuma": _clamp_ratio(mean_luma / total),
            "highlightClipRatio": _clamp_ratio(clipped_highlights / total),
            "shadowCrushRatio": _clamp_ratio(crushed_shadows / total),
            "saturationClipRatio": _clamp_ratio(saturation_extremes / total),
        }

    @staticmethod
    def _editing_profile(context: TurnContext) -> str:
        text = (
            f"{context.base_request.refinement.goalText}\n"
            f"{context.base_request.message.text}"
        ).lower()
        if any(token in text for token in ("portrait", "skin", "wedding", "face")):
            return "skin-safe"
        if any(
            token in text
            for token in ("product", "catalog", "e-commerce", "brand", "accurate")
        ):
            return "color-accurate"
        return "general"

    @staticmethod
    def _summed_deltas(
        operations: list[dict[str, Any]],
        *,
        action_terms: tuple[str, ...],
    ) -> float:
        total = 0.0
        for operation in operations:
            target = operation.get("target")
            value = operation.get("value")
            if not isinstance(target, dict) or not isinstance(value, dict):
                continue
            action_path = str(target.get("actionPath") or "").lower()
            if not any(term in action_path for term in action_terms):
                continue
            number = value.get("number")
            if isinstance(number, (int, float)):
                total += float(number)
        return total

    def _build_live_verifier_feedback(self, context: TurnContext) -> dict[str, Any]:
        base_metrics = self._preview_metrics(context.base_preview_bytes)
        current_metrics = self._preview_metrics(context.current_preview_bytes)
        profile = self._editing_profile(context)

        if base_metrics is None or current_metrics is None:
            summary = (
                "Verifier unavailable: preview metrics could not be derived from the "
                "current render, so rely on visual inspection before finalizing."
            )
            result = {
                "status": "unavailable",
                "profile": profile,
                "summary": summary,
                "checks": [],
            }
            context.last_verifier_status = result["status"]
            context.last_verifier_summary = summary
            return result

        checks: list[dict[str, Any]] = []
        exposure_delta = self._summed_deltas(
            context.last_applied_batch, action_terms=("exposure", "filmic", "toneeq")
        )
        saturation_delta = self._summed_deltas(
            context.last_applied_batch,
            action_terms=("sat", "saturation", "vibrance", "chroma"),
        )

        highlight_threshold = 0.02 if profile == "general" else 0.01
        shadow_threshold = 0.03 if profile == "general" else 0.02
        saturation_threshold = 0.01 if profile == "general" else 0.005

        highlight_increase = (
            current_metrics["highlightClipRatio"] - base_metrics["highlightClipRatio"]
        )
        if exposure_delta > 0.15 and highlight_increase > highlight_threshold:
            checks.append(
                {
                    "name": "highlight-clipping",
                    "status": "fail",
                    "detail": (
                        "Highlight clipping increased from "
                        f"{base_metrics['highlightClipRatio']:.1%} to "
                        f"{current_metrics['highlightClipRatio']:.1%}."
                    ),
                }
            )

        shadow_increase = (
            current_metrics["shadowCrushRatio"] - base_metrics["shadowCrushRatio"]
        )
        if exposure_delta < -0.15 and shadow_increase > shadow_threshold:
            checks.append(
                {
                    "name": "shadow-crush",
                    "status": "fail",
                    "detail": (
                        "Shadow crush increased from "
                        f"{base_metrics['shadowCrushRatio']:.1%} to "
                        f"{current_metrics['shadowCrushRatio']:.1%}."
                    ),
                }
            )

        saturation_increase = (
            current_metrics["saturationClipRatio"] - base_metrics["saturationClipRatio"]
        )
        if saturation_delta > 0.05 and saturation_increase > saturation_threshold:
            checks.append(
                {
                    "name": "saturation-clipping",
                    "status": "fail",
                    "detail": (
                        "Saturation clipping increased from "
                        f"{base_metrics['saturationClipRatio']:.1%} to "
                        f"{current_metrics['saturationClipRatio']:.1%}."
                    ),
                }
            )

        status = "pass" if not checks else "fail"
        if status == "pass":
            summary = (
                "Verifier pass: no major clipping or saturation regressions were "
                "detected after the latest live edits."
            )
        else:
            summary = "Verifier fail: " + " ".join(
                check["detail"]
                for check in checks
                if isinstance(check.get("detail"), str)
            )

        result = {
            "status": status,
            "profile": profile,
            "summary": summary,
            "checks": checks,
            "baseMetrics": base_metrics,
            "currentMetrics": current_metrics,
        }
        context.last_verifier_status = status
        context.last_verifier_summary = summary
        logger.info(
            "live_verifier_result",
            extra={
                "structured": {
                    "requestId": context.base_request.requestId,
                    "turnId": context.base_request.session.turnId,
                    "status": status,
                    "profile": profile,
                    "checks": checks,
                    "baseMetrics": base_metrics,
                    "currentMetrics": current_metrics,
                }
            },
        )
        return result

    @staticmethod
    def _verifier_feedback_text(result: dict[str, Any]) -> str:
        return "Verifier summary JSON:\n" + json.dumps(result, separators=(",", ":"))
