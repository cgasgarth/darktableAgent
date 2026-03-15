from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "3.0"
DEFAULT_REFINEMENT_MAX_PASSES = 10

OperationKind = Literal["set-float", "set-choice", "set-bool"]
OperationMode = Literal["delta", "set"]
RefinementMode = Literal["single-turn", "multi-turn"]


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


class RefinementRequest(StrictBaseModel):
    mode: RefinementMode
    enabled: bool
    maxPasses: int = Field(ge=1, le=DEFAULT_REFINEMENT_MAX_PASSES)
    passIndex: int = Field(ge=1, le=DEFAULT_REFINEMENT_MAX_PASSES)
    automaticContinuation: bool
    goalText: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_refinement_state(self) -> "RefinementRequest":
        expected_mode: RefinementMode = "multi-turn" if self.enabled else "single-turn"
        if self.mode != expected_mode:
            raise ValueError("refinement mode does not match enabled flag")
        if self.passIndex > self.maxPasses:
            raise ValueError("refinement passIndex must be <= maxPasses")
        if not self.enabled:
            if self.maxPasses != 1:
                raise ValueError("single-turn refinement must use maxPasses=1")
            if self.passIndex != 1:
                raise ValueError("single-turn refinement must use passIndex=1")
            if self.automaticContinuation:
                raise ValueError("single-turn refinement must not be an automatic continuation")
        return self


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


class ChoiceOption(StrictBaseModel):
    choiceValue: int
    choiceId: str = Field(min_length=1)
    label: str = Field(min_length=1)


class Capability(StrictBaseModel):
    capabilityId: str = Field(min_length=1)
    label: str = Field(min_length=1)
    kind: OperationKind
    targetType: Literal["darktable-action"]
    actionPath: str = Field(min_length=1)
    supportedModes: list[OperationMode] = Field(min_length=1)
    minNumber: float | None = None
    maxNumber: float | None = None
    defaultNumber: float | None = None
    stepNumber: float | None = None
    choices: list[ChoiceOption] | None = None
    defaultChoiceValue: int | None = None
    defaultBool: bool | None = None

    @model_validator(mode="after")
    def validate_value_shape(self) -> "Capability":
        if len(set(self.supportedModes)) != len(self.supportedModes):
            raise ValueError("capability supportedModes must not contain duplicates")

        if self.kind == "set-float":
            if self.minNumber is None or self.maxNumber is None:
                raise ValueError("float capability requires minNumber/maxNumber")
            if self.defaultNumber is None or self.stepNumber is None:
                raise ValueError("float capability requires defaultNumber/stepNumber")
            if self.minNumber > self.maxNumber:
                raise ValueError("capability minNumber must be <= maxNumber")
            if not (self.minNumber <= self.defaultNumber <= self.maxNumber):
                raise ValueError("capability defaultNumber must be within min/max range")
            if self.stepNumber <= 0:
                raise ValueError("capability stepNumber must be positive")
            if self.choices is not None or self.defaultChoiceValue is not None:
                raise ValueError("float capability must not define choices")
            if self.defaultBool is not None:
                raise ValueError("float capability must not define defaultBool")
        elif self.kind == "set-choice":
            if self.supportedModes != ["set"]:
                raise ValueError('choice capability supportedModes must be exactly ["set"]')
            if not self.choices:
                raise ValueError("choice capability must define choices")
            choice_values = [choice.choiceValue for choice in self.choices]
            choice_ids = [choice.choiceId for choice in self.choices]
            if len(choice_values) != len(set(choice_values)):
                raise ValueError("choice capability values must be unique")
            if len(choice_ids) != len(set(choice_ids)):
                raise ValueError("choice capability ids must be unique")
            if self.defaultChoiceValue not in choice_values:
                raise ValueError("choice capability defaultChoiceValue must reference a choice")
            if any(
                value is not None
                for value in (
                    self.minNumber,
                    self.maxNumber,
                    self.defaultNumber,
                    self.stepNumber,
                    self.defaultBool,
                )
            ):
                raise ValueError("choice capability must not define float/bool defaults")
        elif self.kind == "set-bool":
            if self.supportedModes != ["set"]:
                raise ValueError('bool capability supportedModes must be exactly ["set"]')
            if self.defaultBool is None:
                raise ValueError("bool capability requires defaultBool")
            if any(
                value is not None
                for value in (
                    self.minNumber,
                    self.maxNumber,
                    self.defaultNumber,
                    self.stepNumber,
                    self.defaultChoiceValue,
                )
            ) or self.choices is not None:
                raise ValueError("bool capability must not define float/choice defaults")
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
    kind: OperationKind
    supportedModes: list[OperationMode] = Field(min_length=1)
    currentNumber: float | None = None
    minNumber: float | None = None
    maxNumber: float | None = None
    defaultNumber: float | None = None
    stepNumber: float | None = None
    currentChoiceValue: int | None = None
    currentChoiceId: str | None = None
    choices: list[ChoiceOption] | None = None
    defaultChoiceValue: int | None = None
    currentBool: bool | None = None
    defaultBool: bool | None = None


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
    refinement: RefinementRequest
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
                raise ValueError("editableSetting actionPath does not match capability manifest")
            if capability.label != setting.label:
                raise ValueError("editableSetting label does not match capability manifest")
            if capability.kind != setting.kind:
                raise ValueError("editableSetting kind does not match capability manifest")
            if capability.supportedModes != setting.supportedModes:
                raise ValueError(
                    "editableSetting supportedModes do not match capability manifest"
                )
            if setting.kind == "set-float":
                if setting.currentNumber is None:
                    raise ValueError("float editableSetting requires currentNumber")
                if (
                    setting.minNumber != capability.minNumber
                    or setting.maxNumber != capability.maxNumber
                    or setting.defaultNumber != capability.defaultNumber
                    or setting.stepNumber != capability.stepNumber
                ):
                    raise ValueError("float editableSetting bounds do not match capability")
            elif setting.kind == "set-choice":
                capability_choices = capability.choices or []
                if setting.choices != capability_choices:
                    raise ValueError("choice editableSetting choices do not match capability")
                if setting.defaultChoiceValue != capability.defaultChoiceValue:
                    raise ValueError(
                        "choice editableSetting defaultChoiceValue does not match capability"
                    )
            elif setting.kind == "set-bool":
                if setting.currentBool is None:
                    raise ValueError("bool editableSetting requires currentBool")
                if setting.defaultBool != capability.defaultBool:
                    raise ValueError("bool editableSetting defaultBool does not match capability")
        return self


class OperationTarget(StrictBaseModel):
    type: Literal["darktable-action"]
    actionPath: str = Field(min_length=1)
    settingId: str = Field(min_length=1)


class OperationValue(StrictBaseModel):
    mode: OperationMode
    number: float | None = None
    choiceValue: int | None = None
    choiceId: str | None = None
    boolValue: bool | None = None


class OperationConstraint(StrictBaseModel):
    onOutOfRange: Literal["clamp"]
    onRevisionMismatch: Literal["fail"]


class PlannedOperationDraft(StrictBaseModel):
    operationId: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    kind: OperationKind
    target: OperationTarget
    value: OperationValue
    reason: str | None
    constraints: OperationConstraint

    @model_validator(mode="after")
    def validate_kind_and_value(self) -> "PlannedOperationDraft":
        if self.kind == "set-float":
            if self.value.number is None:
                raise ValueError("set-float operation requires value.number")
            if self.value.choiceValue is not None or self.value.boolValue is not None:
                raise ValueError("set-float operation must not define choice/bool values")
        elif self.kind == "set-choice":
            if self.value.mode != "set":
                raise ValueError('set-choice operation must use mode "set"')
            if self.value.choiceValue is None:
                raise ValueError("set-choice operation requires value.choiceValue")
            if self.value.number is not None or self.value.boolValue is not None:
                raise ValueError("set-choice operation must not define number/bool values")
        elif self.kind == "set-bool":
            if self.value.mode != "set":
                raise ValueError('set-bool operation must use mode "set"')
            if self.value.boolValue is None:
                raise ValueError("set-bool operation requires value.boolValue")
            if self.value.number is not None or self.value.choiceValue is not None:
                raise ValueError("set-bool operation must not define number/choice values")
        return self


class AgentPlan(StrictBaseModel):
    assistantText: str = Field(min_length=1)
    continueRefining: bool
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


class ErrorInfo(StrictBaseModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class OperationResult(StrictBaseModel):
    operationId: str = Field(min_length=1)
    status: Literal["planned", "applied", "blocked", "failed"]
    error: ErrorInfo | None = None


class PlanEnvelope(StrictBaseModel):
    planId: str = Field(min_length=1)
    baseImageRevisionId: str = Field(min_length=1)
    operations: list[PlannedOperationDraft]


class RefinementStatus(StrictBaseModel):
    mode: RefinementMode
    enabled: bool
    passIndex: int = Field(ge=1, le=DEFAULT_REFINEMENT_MAX_PASSES)
    maxPasses: int = Field(ge=1, le=DEFAULT_REFINEMENT_MAX_PASSES)
    continueRefining: bool
    stopReason: Literal["single-turn", "continue", "planner-complete", "no-operations", "max-passes"]


class ResponseEnvelope(StrictBaseModel):
    schemaVersion: Literal["3.0"] = SCHEMA_VERSION
    requestId: str
    session: ResponseSession
    status: Literal["ok", "error"]
    assistantMessage: AssistantMessage
    refinement: RefinementStatus
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
    refinement = _build_refinement_status(request, plan)
    return ResponseEnvelope(
        requestId=request.requestId,
        session=ResponseSession.model_validate(request.session.model_dump()),
        status="ok",
        assistantMessage=AssistantMessage(role="assistant", text=plan.assistantText),
        refinement=refinement,
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


def _build_refinement_status(request: RequestEnvelope, plan: AgentPlan) -> RefinementStatus:
    can_continue = (
        request.refinement.enabled
        and plan.continueRefining
        and bool(plan.operations)
        and request.refinement.passIndex < request.refinement.maxPasses
    )

    if not request.refinement.enabled:
        stop_reason: Literal[
            "single-turn", "continue", "planner-complete", "no-operations", "max-passes"
        ] = "single-turn"
    elif not plan.operations:
        stop_reason = "no-operations"
    elif request.refinement.passIndex >= request.refinement.maxPasses:
        stop_reason = "max-passes"
    elif can_continue:
        stop_reason = "continue"
    else:
        stop_reason = "planner-complete"

    return RefinementStatus(
        mode=request.refinement.mode,
        enabled=request.refinement.enabled,
        passIndex=request.refinement.passIndex,
        maxPasses=request.refinement.maxPasses,
        continueRefining=can_continue,
        stopReason=stop_reason,
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
