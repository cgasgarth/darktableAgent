from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "3.0"


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


class RequestSession(StrictBaseModel):
    appSessionId: str = Field(min_length=1)
    imageSessionId: str = Field(min_length=1)
    conversationId: str = Field(min_length=1)
    turnId: str = Field(min_length=1)


class ResponseSession(StrictBaseModel):
    appSessionId: str
    imageSessionId: str
    conversationId: str
    turnId: str


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


class PreviewImage(StrictBaseModel):
    previewId: str = Field(min_length=1)
    mimeType: str = Field(min_length=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    base64Data: str = Field(min_length=1)


class HistogramChannel(StrictBaseModel):
    bins: list[int] = Field(min_length=1)


class Histogram(StrictBaseModel):
    binCount: int = Field(gt=0)
    channels: dict[str, HistogramChannel] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bin_counts(self) -> "Histogram":
        for channel_name, channel in self.channels.items():
            if len(channel.bins) != self.binCount:
                raise ValueError(
                    f"histogram channel {channel_name} must contain exactly {self.binCount} bins"
                )
        return self


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


class CapabilityManifest(StrictBaseModel):
    manifestVersion: str = Field(min_length=1)
    targets: list[Capability] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_capability_ids(self) -> "CapabilityManifest":
        capability_ids = [target.capabilityId for target in self.targets]
        if len(capability_ids) != len(set(capability_ids)):
            raise ValueError("capability manifest must not contain duplicate capabilityId values")
        return self


class EditableSetting(StrictBaseModel):
    settingId: str = Field(min_length=1)
    capabilityId: str = Field(min_length=1)
    label: str = Field(min_length=1)
    actionPath: str = Field(min_length=1)
    currentNumber: float | None
    supportedModes: list[Literal["delta", "set"]] = Field(min_length=1)
    minNumber: float
    maxNumber: float
    defaultNumber: float
    stepNumber: float


class ImageHistoryItem(StrictBaseModel):
    num: int
    module: str | None
    enabled: bool
    multiPriority: int
    instanceName: str | None
    iopOrder: int


class ImageSnapshot(StrictBaseModel):
    imageRevisionId: str = Field(min_length=1)
    metadata: ImageMetadata
    historyPosition: int
    historyCount: int
    editableSettings: list[EditableSetting]
    history: list[ImageHistoryItem]
    preview: PreviewImage | None
    histogram: Histogram | None


class RequestEnvelope(StrictBaseModel):
    schemaVersion: Literal["3.0"]
    requestId: str = Field(min_length=1)
    session: RequestSession
    message: UserMessage
    uiContext: UIContext
    capabilityManifest: CapabilityManifest
    imageSnapshot: ImageSnapshot

    @model_validator(mode="after")
    def validate_capability_consistency(self) -> "RequestEnvelope":
        capability_by_id: dict[str, Capability] = {
            capability.capabilityId: capability for capability in self.capabilityManifest.targets
        }
        for setting in self.imageSnapshot.editableSettings:
            capability = capability_by_id.get(setting.capabilityId)
            if capability is None:
                raise ValueError(
                    f"editableSetting references unknown capabilityId: {setting.capabilityId}"
                )
            if capability.actionPath != setting.actionPath:
                raise ValueError(
                    "editableSetting actionPath does not match capability manifest"
                )
            if capability.label != setting.label:
                raise ValueError("editableSetting label does not match capability manifest")
            if capability.supportedModes != setting.supportedModes:
                raise ValueError(
                    "editableSetting supportedModes do not match capability manifest"
                )
        return self


class OperationTarget(StrictBaseModel):
    type: Literal["darktable-action"]
    actionPath: str = Field(min_length=1)
    settingId: str | None


class OperationValue(StrictBaseModel):
    mode: Literal["delta", "set"]
    number: float


class OperationConstraint(StrictBaseModel):
    onOutOfRange: Literal["clamp"]
    onRevisionMismatch: Literal["fail"]


class PlannedOperationDraft(StrictBaseModel):
    operationId: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    kind: Literal["set-float"]
    target: OperationTarget
    value: OperationValue
    reason: str | None
    constraints: OperationConstraint


class AgentPlan(StrictBaseModel):
    assistantText: str = Field(min_length=1)
    operations: list[PlannedOperationDraft]

    @model_validator(mode="after")
    def validate_operation_ids(self) -> "AgentPlan":
        operation_ids = [operation.operationId for operation in self.operations]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("operationId values must be unique")
        sequences = [operation.sequence for operation in self.operations]
        if len(sequences) != len(set(sequences)):
            raise ValueError("operation sequence values must be unique")
        return self


class OperationResult(StrictBaseModel):
    operationId: str = Field(min_length=1)
    status: Literal["planned", "applied", "blocked", "failed"]
    error: "ErrorInfo | None" = None


class PlanEnvelope(StrictBaseModel):
    planId: str = Field(min_length=1)
    baseImageRevisionId: str = Field(min_length=1)
    operations: list[PlannedOperationDraft]


class ErrorInfo(StrictBaseModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ResponseEnvelope(StrictBaseModel):
    schemaVersion: Literal["3.0"] = SCHEMA_VERSION
    requestId: str
    session: ResponseSession
    status: Literal["ok", "error"]
    assistantMessage: AssistantMessage
    plan: PlanEnvelope | None
    operationResults: list[OperationResult]
    error: ErrorInfo | None

    @model_validator(mode="after")
    def validate_status_consistency(self) -> "ResponseEnvelope":
        if self.status == "error":
            if self.plan is not None:
                raise ValueError("error responses must not include a plan")
            if self.operationResults:
                raise ValueError("error responses must not include operation results")
            if self.error is None:
                raise ValueError("error responses must include error details")
        if self.status == "ok":
            if self.plan is None:
                raise ValueError("ok responses must include a plan")
            if self.error is not None:
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
        session=ResponseSession.model_validate(request.session.model_dump()),
        status="ok",
        assistantMessage=AssistantMessage(role="assistant", text=plan.assistantText),
        plan=PlanEnvelope(
            planId=f"plan-{request.session.turnId}",
            baseImageRevisionId=request.imageSnapshot.imageRevisionId,
            operations=plan.operations,
        ),
        operationResults=[
            OperationResult(operationId=operation.operationId, status="planned", error=None)
            for operation in plan.operations
        ],
        error=None,
    )


def parse_request_ids(payload: Any) -> tuple[str, dict[str, str]]:
    if not isinstance(payload, dict):
        return "", {
            "appSessionId": "",
            "imageSessionId": "",
            "conversationId": "",
            "turnId": "",
        }

    session = payload.get("session")
    if not isinstance(session, dict):
        session = {}

    return (
        payload.get("requestId") if isinstance(payload.get("requestId"), str) else "",
        {
            "appSessionId": (
                session.get("appSessionId") if isinstance(session.get("appSessionId"), str) else ""
            ),
            "imageSessionId": (
                session.get("imageSessionId")
                if isinstance(session.get("imageSessionId"), str)
                else ""
            ),
            "conversationId": (
                session.get("conversationId")
                if isinstance(session.get("conversationId"), str)
                else ""
            ),
            "turnId": session.get("turnId") if isinstance(session.get("turnId"), str) else "",
        },
    )
