from __future__ import annotations

import base64
import binascii
import io
from typing import Literal, TypedDict

from shared.analysis_signals import (
    ActiveModuleSignal,
    ImageAnalysisSignals,
    QualitySignalSummary,
    RegionSignalSummary,
    TonalSignalSummary,
)
from shared.protocol import JsonObject, RequestEnvelope


class PreviewPixel(TypedDict):
    red: float
    green: float
    blue: float
    luma: float
    saturation: float


class PreviewSamples(TypedDict):
    width: int
    height: int
    samples: list[PreviewPixel]
    lumas: list[float]
    saturations: list[float]
    grayscale: list[float]


try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None


def _clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, value))


def _quantile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    index = int(_clamp_unit(fraction) * (len(sorted_values) - 1))
    return sorted_values[index]


def _decode_preview_bytes(request: RequestEnvelope) -> bytes | None:
    preview = request.imageSnapshot.preview
    if preview is None:
        return None
    try:
        return base64.b64decode(preview.base64Data, validate=True)
    except (binascii.Error, ValueError):
        return None


def _preview_samples(image_bytes: bytes) -> PreviewSamples | None:
    if Image is None or not image_bytes:
        return None

    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image = image.convert("RGB")
            image.thumbnail((96, 96))
            width, height = image.size
            pixels = list(image.getdata())
    except Exception:
        return None

    if not pixels or width <= 0 or height <= 0:
        return None

    grayscale: list[float] = []
    lumas: list[float] = []
    saturations: list[float] = []
    samples: list[PreviewPixel] = []
    for red, green, blue in pixels:
        luma = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255.0
        saturation = (max(red, green, blue) - min(red, green, blue)) / 255.0
        grayscale.append((red + green + blue) / 3.0)
        lumas.append(luma)
        saturations.append(saturation)
        samples.append(
            {
                "red": red / 255.0,
                "green": green / 255.0,
                "blue": blue / 255.0,
                "luma": luma,
                "saturation": saturation,
            }
        )

    return {
        "width": width,
        "height": height,
        "samples": samples,
        "lumas": lumas,
        "saturations": saturations,
        "grayscale": grayscale,
    }


def _tonal_from_preview(preview_samples: PreviewSamples) -> TonalSignalSummary:
    lumas = sorted(float(value) for value in preview_samples["lumas"])
    samples = preview_samples["samples"]
    total = max(1, len(samples))
    clipped = sum(
        1
        for sample in samples
        if max(sample["red"], sample["green"], sample["blue"]) >= 0.98
    )
    crushed = sum(1 for sample in samples if sample["luma"] <= 0.04)
    return TonalSignalSummary(
        meanLuma=_clamp_unit(sum(lumas) / total),
        highlightClipEstimate=_clamp_unit(clipped / total),
        shadowCrushEstimate=_clamp_unit(crushed / total),
        highlightHeadroomEstimate=_clamp_unit(1.0 - _quantile(lumas, 0.95)),
        shadowHeadroomEstimate=_clamp_unit(_quantile(lumas, 0.05)),
    )


def _tonal_from_histogram(request: RequestEnvelope) -> TonalSignalSummary | None:
    histogram = request.imageSnapshot.histogram
    if histogram is None:
        return None
    channel = histogram.channels.get("luma")
    if channel is None or not channel.bins:
        return None

    bins = channel.bins
    total = sum(bins)
    if total <= 0:
        return None

    mean_luma = 0.0
    cumulative = 0
    p05 = 0.0
    p95 = 1.0
    found_p05 = False
    for index, count in enumerate(bins):
        midpoint = (index + 0.5) / len(bins)
        mean_luma += midpoint * (count / total)
        cumulative += count
        fraction = cumulative / total
        if not found_p05 and fraction >= 0.05:
            p05 = midpoint
            found_p05 = True
        if fraction >= 0.95:
            p95 = midpoint
            break

    return TonalSignalSummary(
        meanLuma=_clamp_unit(mean_luma),
        highlightClipEstimate=_clamp_unit(bins[-1] / total),
        shadowCrushEstimate=_clamp_unit(bins[0] / total),
        highlightHeadroomEstimate=_clamp_unit(1.0 - p95),
        shadowHeadroomEstimate=_clamp_unit(p05),
    )


def _sharpness_estimate(
    preview_samples: PreviewSamples | None,
) -> Literal["unknown", "soft", "normal", "crisp"]:
    if preview_samples is None:
        return "unknown"
    width = int(preview_samples["width"])
    height = int(preview_samples["height"])
    grayscale = [float(value) for value in preview_samples["grayscale"]]
    if width < 2 or height < 2 or len(grayscale) != width * height:
        return "unknown"

    edge_sum = 0.0
    edge_count = 0
    for y in range(height - 1):
        row = y * width
        next_row = (y + 1) * width
        for x in range(width - 1):
            idx = row + x
            edge_sum += abs(grayscale[idx] - grayscale[idx + 1])
            edge_sum += abs(grayscale[idx] - grayscale[next_row + x])
            edge_count += 2
    if edge_count == 0:
        return "unknown"
    edge_mean = (edge_sum / edge_count) / 255.0
    if edge_mean < 0.035:
        return "soft"
    if edge_mean < 0.075:
        return "normal"
    return "crisp"


def _noise_risk(
    request: RequestEnvelope,
    tonal: TonalSignalSummary | None,
) -> Literal["low", "medium", "high"]:
    iso = float(request.imageSnapshot.metadata.exifIso or 0.0)
    mean_luma = tonal.meanLuma if tonal is not None else 0.5
    if iso >= 3200 or (iso >= 1600 and mean_luma < 0.35):
        return "high"
    if iso >= 800 or mean_luma < 0.2:
        return "medium"
    return "low"


def _region_slice(
    preview_samples: PreviewSamples,
    *,
    x_start: float,
    x_end: float,
    y_start: float,
    y_end: float,
) -> list[PreviewPixel]:
    width = int(preview_samples["width"])
    height = int(preview_samples["height"])
    samples = preview_samples["samples"]
    left = max(0, min(width - 1, int(width * x_start)))
    right = max(left + 1, min(width, int(width * x_end)))
    top = max(0, min(height - 1, int(height * y_start)))
    bottom = max(top + 1, min(height, int(height * y_end)))
    region: list[PreviewPixel] = []
    for y in range(top, bottom):
        start = y * width + left
        end = y * width + right
        region.extend(samples[start:end])
    return region


def _region_stats(region: list[PreviewPixel]) -> tuple[float, float]:
    if not region:
        return 0.0, 0.0
    mean_luma = sum(sample["luma"] for sample in region) / len(region)
    mean_saturation = sum(sample["saturation"] for sample in region) / len(region)
    return _clamp_unit(mean_luma), _clamp_unit(mean_saturation)


def _region_summaries(
    preview_samples: PreviewSamples | None,
) -> list[RegionSignalSummary]:
    if preview_samples is None:
        return []

    summaries: list[RegionSignalSummary] = []
    top_band = _region_slice(
        preview_samples, x_start=0.0, x_end=1.0, y_start=0.0, y_end=0.3
    )
    if top_band:
        mean_luma, mean_saturation = _region_stats(top_band)
        blue_dominance = sum(
            1 for sample in top_band if sample["blue"] > sample["green"] > sample["red"]
        ) / len(top_band)
        if blue_dominance > 0.35 and mean_luma > 0.25:
            summaries.append(
                RegionSignalSummary(
                    regionId="top-band-sky",
                    kind="sky-candidate",
                    confidence=_clamp_unit(blue_dominance),
                    coverageEstimate=_clamp_unit(blue_dominance),
                    meanLuma=mean_luma,
                    meanSaturation=mean_saturation,
                )
            )

    center_band = _region_slice(
        preview_samples, x_start=0.25, x_end=0.75, y_start=0.2, y_end=0.8
    )
    if center_band:
        mean_luma, mean_saturation = _region_stats(center_band)
        skin_coverage = sum(
            1
            for sample in center_band
            if sample["red"] > 0.37
            and sample["green"] > 0.16
            and sample["blue"] > 0.08
            and sample["red"] > sample["green"] > sample["blue"]
            and (sample["red"] - sample["green"]) > 0.06
        ) / len(center_band)
        if skin_coverage > 0.08:
            summaries.append(
                RegionSignalSummary(
                    regionId="center-band-skin",
                    kind="skin-candidate",
                    confidence=_clamp_unit(min(1.0, skin_coverage * 3.0)),
                    coverageEstimate=_clamp_unit(skin_coverage),
                    meanLuma=mean_luma,
                    meanSaturation=mean_saturation,
                )
            )

    return summaries[:2]


def _active_modules(request: RequestEnvelope) -> tuple[int, list[ActiveModuleSignal]]:
    label_by_module: dict[str, str] = {}
    for setting in request.imageSnapshot.editableSettings:
        if setting.moduleId not in label_by_module:
            label_by_module[setting.moduleId] = setting.moduleLabel

    active_history = sorted(
        [
            item
            for item in request.imageSnapshot.history
            if item.enabled and item.module
        ],
        key=lambda item: (item.iopOrder, item.multiPriority, item.num),
    )
    signals = [
        ActiveModuleSignal(
            moduleId=str(item.module),
            moduleLabel=label_by_module.get(str(item.module), str(item.module)),
            iopOrder=item.iopOrder,
            multiPriority=item.multiPriority,
            instanceName=item.instanceName,
        )
        for item in active_history[:12]
    ]
    return len(active_history), signals


def build_image_analysis_signals(request: RequestEnvelope) -> JsonObject:
    preview_samples = _preview_samples(_decode_preview_bytes(request) or b"")
    tonal = _tonal_from_preview(preview_samples) if preview_samples else None
    if tonal is None:
        tonal = _tonal_from_histogram(request)

    active_count, active_modules = _active_modules(request)
    noise_risk: Literal["low", "medium", "high"] = _noise_risk(request, tonal)
    sharpness_estimate: Literal["unknown", "soft", "normal", "crisp"] = (
        _sharpness_estimate(preview_samples)
    )
    quality = QualitySignalSummary(
        noiseRisk=noise_risk,
        sharpnessEstimate=sharpness_estimate,
    )
    signals = ImageAnalysisSignals(
        activeModuleCount=active_count,
        activeModulesInOrder=active_modules,
        tonal=tonal,
        quality=quality,
        regionSummaries=_region_summaries(preview_samples),
    )
    return signals.model_dump(mode="json")
