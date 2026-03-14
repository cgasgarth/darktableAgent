from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "2.0"


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserMessage(StrictBaseModel):
    role: Literal["user"]
    text: str = Field(min_length=1)


class AssistantMessage(StrictBaseModel):
    role: Literal["assistant"]
    text: str = Field(min_length=1)


class UIContext(StrictBaseModel):
    view: str = Field(min_length=1)
    imageId: int | None
    imageName: str | None


class ImageMetadata(StrictBaseModel):
    imageId: int | None
    imageName: str | None
    cameraMaker: str | None
    cameraModel: str | None
    width: int
    height: int
    exifExposureSeconds: float
    exifAperture: float
    exifIso: float
    exifFocalLength: float


class ImageControl(StrictBaseModel):
    capabilityId: str = Field(min_length=1)
    label: str = Field(min_length=1)
    actionPath: str = Field(min_length=1)
    currentNumber: float | None


class Capability(StrictBaseModel):
    capabilityId: str = Field(min_length=1)
    label: str = Field(min_length=1)
    kind: Literal["set-float"]
    targetType: Literal["darktable-action"]
    actionPath: str = Field(min_length=1)
    supportedModes: list[Literal["delta", "set"]] = Field(min_length=1)
    minNumber: float
    maxNumber: float
    defaultNumber: float
    stepNumber: float

    @model_validator(mode="after")
    def validate_number_range(self) -> "Capability":
        if self.minNumber > self.maxNumber:
            raise ValueError("capability minNumber must be <= maxNumber")
        if not (self.minNumber <= self.defaultNumber <= self.maxNumber):
            raise ValueError("capability defaultNumber must be within min/max range")
        if self.stepNumber <= 0:
            raise ValueError("capability stepNumber must be positive")
        if len(set(self.supportedModes)) != len(self.supportedModes):
            raise ValueError("capability supportedModes must not contain duplicates")
        return self


class ImageHistoryItem(StrictBaseModel):
    num: int
    module: str | None
    enabled: bool
    multiPriority: int
    instanceName: str | None
    iopOrder: int


class ImageState(StrictBaseModel):
    currentExposure: float | None
    historyPosition: int
    historyCount: int
    metadata: ImageMetadata
    controls: list[ImageControl]
    history: list[ImageHistoryItem]


class RequestEnvelope(StrictBaseModel):
    schemaVersion: Literal["2.0"]
    requestId: str = Field(min_length=1)
    conversationId: str = Field(min_length=1)
    message: UserMessage
    uiContext: UIContext
    capabilities: list[Capability] = Field(min_length=1)
    imageState: ImageState

    @model_validator(mode="after")
    def validate_capability_consistency(self) -> "RequestEnvelope":
        capability_by_id: dict[str, Capability] = {}
        for capability in self.capabilities:
            if capability.capabilityId in capability_by_id:
                raise ValueError(f"duplicate capabilityId: {capability.capabilityId}")
            capability_by_id[capability.capabilityId] = capability

        for control in self.imageState.controls:
            capability = capability_by_id.get(control.capabilityId)
            if capability is None:
                raise ValueError(
                    f"imageState control references unknown capabilityId: {control.capabilityId}"
                )
            if capability.actionPath != control.actionPath:
                raise ValueError(
                    "imageState control actionPath does not match capability manifest"
                )
            if capability.label != control.label:
                raise ValueError("imageState control label does not match capability manifest")

        return self


class OperationTarget(StrictBaseModel):
    type: Literal["darktable-action"]
    actionPath: str = Field(min_length=1)


class OperationValue(StrictBaseModel):
    mode: Literal["delta", "set"]
    number: float


class PlannedOperationDraft(StrictBaseModel):
    operationId: str = Field(min_length=1)
    kind: Literal["set-float"]
    target: OperationTarget
    value: OperationValue


class AgentPlan(StrictBaseModel):
    assistantText: str = Field(min_length=1)
    operations: list[PlannedOperationDraft]

    @model_validator(mode="after")
    def validate_operation_ids(self) -> "AgentPlan":
        operation_ids = [operation.operationId for operation in self.operations]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("operationId values must be unique")
        return self


class Operation(StrictBaseModel):
    operationId: str = Field(min_length=1)
    kind: Literal["set-float"]
    status: Literal["planned", "applied", "blocked", "failed"]
    target: OperationTarget
    value: OperationValue


class ErrorInfo(StrictBaseModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ResponseEnvelope(StrictBaseModel):
    schemaVersion: Literal["2.0"] = SCHEMA_VERSION
    requestId: str
    conversationId: str
    status: Literal["ok", "error"]
    message: AssistantMessage
    operations: list[Operation]
    error: ErrorInfo | None

    @model_validator(mode="after")
    def validate_status_consistency(self) -> "ResponseEnvelope":
        if self.status == "error":
            if self.operations:
                raise ValueError("error responses must not include operations")
            if self.error is None:
                raise ValueError("error responses must include error details")
        if self.status == "ok" and self.error is not None:
            raise ValueError("ok responses must not include error details")
        return self


class ProtocolError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def build_response_from_plan(request: RequestEnvelope, plan: AgentPlan) -> ResponseEnvelope:
    return ResponseEnvelope(
        requestId=request.requestId,
        conversationId=request.conversationId,
        status="ok",
        message=AssistantMessage(role="assistant", text=plan.assistantText),
        operations=[
            Operation(
                operationId=operation.operationId,
                kind=operation.kind,
                status="planned",
                target=operation.target,
                value=operation.value,
            )
            for operation in plan.operations
        ],
        error=None,
    )


def parse_request_ids(payload: Any) -> tuple[str, str]:
    if not isinstance(payload, dict):
        return "", ""
    request_id = payload.get("requestId")
    conversation_id = payload.get("conversationId")
    return (
        request_id if isinstance(request_id, str) else "",
        conversation_id if isinstance(conversation_id, str) else "",
    )
