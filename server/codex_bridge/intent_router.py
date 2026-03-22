from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from shared.protocol import RequestEnvelope

from .image_signals import build_image_analysis_signals
from .prompt_templates import render_prompt_template


@dataclass(frozen=True, slots=True)
class EditProfile:
    photoType: str
    lighting: str
    prioritySubject: str
    styleArchetype: str
    riskFlags: tuple[str, ...]
    verificationLevel: str
    playbookIds: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["riskFlags"] = list(self.riskFlags)
        payload["playbookIds"] = list(self.playbookIds)
        return payload


@dataclass(frozen=True, slots=True)
class RouteSignals:
    text: str
    iso: float
    meanLuma: float | None
    noiseRisk: str
    skyConfidence: float
    skinConfidence: float
    highlightClipEstimate: float | None


@dataclass(frozen=True, slots=True)
class RouteSpec:
    name: str
    keywords: tuple[str, ...]
    minIso: float | None = None
    minSkyConfidence: float | None = None
    minSkinConfidence: float | None = None
    requiredNoiseRisk: str | None = None


PHOTO_TYPE_SPECS: tuple[RouteSpec, ...] = (
    RouteSpec(
        name="product",
        keywords=(
            "product",
            "packshot",
            "catalog",
            "catalogue",
            "e-commerce",
            "ecommerce",
            "studio",
            "item",
            "bottle",
            "watch",
            "shoe",
        ),
    ),
    RouteSpec(
        name="portrait",
        keywords=(
            "portrait",
            "skin",
            "face",
            "headshot",
            "bride",
            "groom",
            "couple",
            "person",
            "wedding",
        ),
        minSkinConfidence=0.18,
    ),
    RouteSpec(
        name="night",
        keywords=(
            "night",
            "neon",
            "concert",
            "astro",
            "milky way",
            "city lights",
            "evening",
            "low light",
        ),
        minIso=3200.0,
        requiredNoiseRisk="high",
    ),
    RouteSpec(
        name="landscape",
        keywords=(
            "landscape",
            "mountain",
            "forest",
            "outdoor",
            "nature",
            "sky",
            "cloud",
            "sunset",
            "sunrise",
            "travel",
            "seascape",
        ),
        minSkyConfidence=0.25,
    ),
)

STYLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "bw-documentary": ("black and white", "black-and-white", "monochrome", "bw"),
    "cinematic-muted": ("cinematic", "moody", "filmic", "movie", "muted"),
    "color-accurate": (
        "accurate",
        "neutral",
        "true to life",
        "brand color",
        "catalog",
        "catalogue",
        "e-commerce",
        "ecommerce",
    ),
}


def _combined_text(request: RequestEnvelope) -> str:
    parts = [
        request.message.text,
        request.refinement.goalText,
        request.uiContext.imageName or "",
    ]
    return " ".join(part for part in parts if part).lower()


def _analysis_payload(request: RequestEnvelope) -> dict[str, Any]:
    analysis = request.imageSnapshot.analysisSignals
    if analysis is not None:
        return analysis.model_dump(mode="json")
    return build_image_analysis_signals(request)


def _region_confidence(analysis: dict[str, Any], kind: str) -> float:
    for region in analysis.get("regionSummaries", []):
        if region.get("kind") == kind:
            confidence = region.get("confidence")
            if isinstance(confidence, (int, float)):
                return float(confidence)
    return 0.0


def _route_signals(request: RequestEnvelope) -> RouteSignals:
    analysis = _analysis_payload(request)
    tonal = analysis.get("tonal") or {}
    quality = analysis.get("quality") or {}
    return RouteSignals(
        text=_combined_text(request),
        iso=float(request.imageSnapshot.metadata.exifIso or 0.0),
        meanLuma=(
            float(tonal["meanLuma"])
            if isinstance(tonal.get("meanLuma"), (int, float))
            else None
        ),
        noiseRisk=str(quality.get("noiseRisk") or "low"),
        skyConfidence=_region_confidence(analysis, "sky-candidate"),
        skinConfidence=_region_confidence(analysis, "skin-candidate"),
        highlightClipEstimate=(
            float(tonal["highlightClipEstimate"])
            if isinstance(tonal.get("highlightClipEstimate"), (int, float))
            else None
        ),
    )


def _keyword_hits(text: str, keywords: tuple[str, ...]) -> int:
    return sum(1 for keyword in keywords if keyword in text)


def _photo_type(signals: RouteSignals) -> str:
    best_name = "general"
    best_score = 0.0
    for spec in PHOTO_TYPE_SPECS:
        score = float(_keyword_hits(signals.text, spec.keywords)) * 2.0
        if spec.minIso is not None and signals.iso >= spec.minIso:
            score += 1.0
        if (
            spec.minSkyConfidence is not None
            and signals.skyConfidence >= spec.minSkyConfidence
        ):
            score += 2.0
        if (
            spec.minSkinConfidence is not None
            and signals.skinConfidence >= spec.minSkinConfidence
        ):
            score += 2.0
        if (
            spec.requiredNoiseRisk is not None
            and signals.noiseRisk == spec.requiredNoiseRisk
        ):
            score += 1.0
        if score > best_score:
            best_name = spec.name
            best_score = score
    return best_name


def _lighting(signals: RouteSignals, photo_type: str) -> str:
    if any(term in signals.text for term in ("golden hour", "sunset", "sunrise")):
        return "golden-hour"
    if any(term in signals.text for term in ("studio", "strobe", "softbox")):
        return "studio"
    if any(
        term in signals.text for term in ("mixed", "tungsten", "fluorescent", "indoor")
    ):
        return "mixed"
    if photo_type == "night" or any(
        term in signals.text for term in ("night", "neon", "evening")
    ):
        return "night"
    if signals.iso <= 400 and signals.meanLuma is not None and signals.meanLuma >= 0.28:
        return "daylight"
    return "unknown"


def _priority_subject(signals: RouteSignals, photo_type: str) -> str:
    if photo_type == "portrait" or signals.skinConfidence >= 0.18:
        return "person"
    if photo_type == "product":
        return "product"
    if signals.skyConfidence >= 0.25:
        return "sky"
    if photo_type == "landscape":
        return "scene"
    return "unknown"


def _style_archetype(signals: RouteSignals, photo_type: str) -> str:
    for style, keywords in STYLE_KEYWORDS.items():
        if _keyword_hits(signals.text, keywords) > 0:
            return style
    if photo_type == "product":
        return "color-accurate"
    if photo_type == "night" or signals.noiseRisk == "high":
        return "noise-aware"
    return "natural-clean"


def _risk_flags(
    signals: RouteSignals,
    photo_type: str,
    priority_subject: str,
    style_archetype: str,
) -> tuple[str, ...]:
    flags: list[str] = []
    if priority_subject == "person" or signals.skinConfidence >= 0.18:
        flags.append("skin-tones")
    if (
        priority_subject == "sky"
        or any(term in signals.text for term in ("highlight", "sky", "cloud", "sunset"))
        or (
            signals.highlightClipEstimate is not None
            and signals.highlightClipEstimate >= 0.02
        )
    ):
        flags.append("highlight-detail")
    if signals.noiseRisk == "high" or photo_type == "night":
        flags.append("noise-heavy")
    if style_archetype == "color-accurate" or photo_type == "product":
        flags.append("color-accuracy")
    return tuple(dict.fromkeys(flags))


def _verification_level(risk_flags: tuple[str, ...]) -> str:
    if any(
        flag in risk_flags for flag in ("skin-tones", "noise-heavy", "color-accuracy")
    ):
        return "strict"
    if risk_flags:
        return "standard"
    return "fast"


def build_edit_profile(request: RequestEnvelope) -> EditProfile:
    signals = _route_signals(request)
    photo_type = _photo_type(signals)
    style_archetype = _style_archetype(signals, photo_type)
    priority_subject = _priority_subject(signals, photo_type)
    risk_flags = _risk_flags(signals, photo_type, priority_subject, style_archetype)
    return EditProfile(
        photoType=photo_type,
        lighting=_lighting(signals, photo_type),
        prioritySubject=priority_subject,
        styleArchetype=style_archetype,
        riskFlags=risk_flags,
        verificationLevel=_verification_level(risk_flags),
        playbookIds=(
            f"playbooks/photo_type/{photo_type}.txt",
            f"playbooks/style/{style_archetype}.txt",
        ),
    )


def build_playbook_prompts(profile: EditProfile) -> list[dict[str, str]]:
    prompts: list[dict[str, str]] = []
    seen: set[str] = set()
    for path in profile.playbookIds:
        if path in seen:
            continue
        seen.add(path)
        prompts.append(
            {
                "id": path,
                "title": path.split("/")[-1].removesuffix(".txt").replace("-", " "),
                "body": render_prompt_template(path),
            }
        )
    return prompts
