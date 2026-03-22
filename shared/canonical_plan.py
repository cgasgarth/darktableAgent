from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CanonicalActionName = Literal[
    "adjust-exposure",
    "adjust-white-balance",
    "recover-highlights",
    "reduce-noise",
    "grade-color",
    "crop-normalized",
]
CanonicalStrength = Literal["low", "medium", "high"]
CanonicalNoiseType = Literal["chroma", "luma", "both"]
CanonicalGradeTarget = Literal[
    "global-saturation",
    "blue-saturation",
    "red-hue",
    "global-contrast",
]


class CanonicalBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CanonicalEditAction(CanonicalBaseModel):
    action: CanonicalActionName
    exposureEv: float | None = None
    temperatureDelta: float | None = None
    tintDelta: float | None = None
    presetChoiceId: str | None = Field(default=None, min_length=1)
    strength: CanonicalStrength | None = None
    noiseType: CanonicalNoiseType | None = None
    target: CanonicalGradeTarget | None = None
    amount: float | None = None
    left: float | None = None
    top: float | None = None
    right: float | None = None
    bottom: float | None = None
    rationale: str | None = None

    @model_validator(mode="after")
    def validate_action_shape(self) -> "CanonicalEditAction":
        if self.action == "adjust-exposure":
            if self.exposureEv is None:
                raise ValueError("adjust-exposure requires exposureEv")
        elif self.action == "adjust-white-balance":
            if (
                self.temperatureDelta is None
                and self.tintDelta is None
                and self.presetChoiceId is None
            ):
                raise ValueError(
                    "adjust-white-balance requires temperatureDelta, tintDelta, or presetChoiceId"
                )
        elif self.action == "recover-highlights":
            if self.strength is None:
                raise ValueError("recover-highlights requires strength")
        elif self.action == "reduce-noise":
            if self.strength is None:
                raise ValueError("reduce-noise requires strength")
            if self.noiseType is None:
                raise ValueError("reduce-noise requires noiseType")
        elif self.action == "grade-color":
            if self.target is None:
                raise ValueError("grade-color requires target")
            if self.amount is None:
                raise ValueError("grade-color requires amount")
        elif self.action == "crop-normalized":
            bounds = (self.left, self.top, self.right, self.bottom)
            if any(value is None for value in bounds):
                raise ValueError(
                    "crop-normalized requires left, top, right, and bottom"
                )
            assert self.left is not None
            assert self.top is not None
            assert self.right is not None
            assert self.bottom is not None
            for label, value in (
                ("left", self.left),
                ("top", self.top),
                ("right", self.right),
                ("bottom", self.bottom),
            ):
                if not 0.0 <= value <= 1.0:
                    raise ValueError(f"crop-normalized {label} must be within [0, 1]")
            if self.left >= self.right:
                raise ValueError("crop-normalized left must be less than right")
            if self.top >= self.bottom:
                raise ValueError("crop-normalized top must be less than bottom")
        return self
