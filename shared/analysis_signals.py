from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActiveModuleSignal(StrictBaseModel):
    moduleId: str = Field(min_length=1)
    moduleLabel: str = Field(min_length=1)
    iopOrder: int
    multiPriority: int
    instanceName: str | None = None


class TonalSignalSummary(StrictBaseModel):
    meanLuma: float = Field(ge=0.0, le=1.0)
    highlightClipEstimate: float = Field(ge=0.0, le=1.0)
    shadowCrushEstimate: float = Field(ge=0.0, le=1.0)
    highlightHeadroomEstimate: float = Field(ge=0.0, le=1.0)
    shadowHeadroomEstimate: float = Field(ge=0.0, le=1.0)


class QualitySignalSummary(StrictBaseModel):
    noiseRisk: Literal["low", "medium", "high"]
    sharpnessEstimate: Literal["unknown", "soft", "normal", "crisp"]


class RegionSignalSummary(StrictBaseModel):
    regionId: str = Field(min_length=1)
    kind: Literal["sky-candidate", "skin-candidate"]
    confidence: float = Field(ge=0.0, le=1.0)
    coverageEstimate: float = Field(ge=0.0, le=1.0)
    meanLuma: float = Field(ge=0.0, le=1.0)
    meanSaturation: float = Field(ge=0.0, le=1.0)


class ImageAnalysisSignals(StrictBaseModel):
    activeModuleCount: int = Field(ge=0)
    activeModulesInOrder: list[ActiveModuleSignal] = Field(default_factory=list)
    tonal: TonalSignalSummary | None = None
    quality: QualitySignalSummary | None = None
    regionSummaries: list[RegionSignalSummary] = Field(default_factory=list)
