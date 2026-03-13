from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "2.0"
DEFAULT_MOCK_RESPONSE_ID = "exposure-plus-0.7"


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
    mockResponseId: str | None = None


class OperationTarget(StrictBaseModel):
    type: Literal["darktable-action"]
    actionPath: str = Field(min_length=1)


class OperationValue(StrictBaseModel):
    mode: Literal["delta", "set"]
    number: float


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


def build_mock_response_catalog(request: RequestEnvelope) -> dict[str, ResponseEnvelope]:
    exposure_up = ResponseEnvelope(
        requestId=request.requestId,
        conversationId=request.conversationId,
        status="ok",
        message=AssistantMessage(
            role="assistant",
            text=(
                "Mock agent: increasing the current image exposure by +0.7 EV "
                "through the exposure slider."
            ),
        ),
        operations=[
            Operation(
                operationId="op-exposure-plus-0.7",
                kind="set-float",
                status="planned",
                target=OperationTarget(
                    type="darktable-action",
                    actionPath="iop/exposure/exposure",
                ),
                value=OperationValue(mode="delta", number=0.7),
            )
        ],
        error=None,
    )

    exposure_down = ResponseEnvelope(
        requestId=request.requestId,
        conversationId=request.conversationId,
        status="ok",
        message=AssistantMessage(
            role="assistant",
            text=(
                "Mock agent: decreasing the current image exposure by -0.7 EV "
                "through the exposure slider."
            ),
        ),
        operations=[
            Operation(
                operationId="op-exposure-minus-0.7",
                kind="set-float",
                status="planned",
                target=OperationTarget(
                    type="darktable-action",
                    actionPath="iop/exposure/exposure",
                ),
                value=OperationValue(mode="delta", number=-0.7),
            )
        ],
        error=None,
    )

    exposure_sequence = ResponseEnvelope(
        requestId=request.requestId,
        conversationId=request.conversationId,
        status="ok",
        message=AssistantMessage(
            role="assistant",
            text=(
                "Mock agent: running an ordered two-step exposure edit "
                "(+0.2 EV, then +0.5 EV)."
            ),
        ),
        operations=[
            Operation(
                operationId="op-exposure-plus-0.2",
                kind="set-float",
                status="planned",
                target=OperationTarget(
                    type="darktable-action",
                    actionPath="iop/exposure/exposure",
                ),
                value=OperationValue(mode="delta", number=0.2),
            ),
            Operation(
                operationId="op-exposure-plus-0.5",
                kind="set-float",
                status="planned",
                target=OperationTarget(
                    type="darktable-action",
                    actionPath="iop/exposure/exposure",
                ),
                value=OperationValue(mode="delta", number=0.5),
            ),
        ],
        error=None,
    )

    exposure_set = ResponseEnvelope(
        requestId=request.requestId,
        conversationId=request.conversationId,
        status="ok",
        message=AssistantMessage(
            role="assistant",
            text="Mock agent: setting exposure to exactly +1.25 EV.",
        ),
        operations=[
            Operation(
                operationId="op-exposure-set-1.25",
                kind="set-float",
                status="planned",
                target=OperationTarget(
                    type="darktable-action",
                    actionPath="iop/exposure/exposure",
                ),
                value=OperationValue(mode="set", number=1.25),
            )
        ],
        error=None,
    )

    exposure_clamp_max = ResponseEnvelope(
        requestId=request.requestId,
        conversationId=request.conversationId,
        status="ok",
        message=AssistantMessage(
            role="assistant",
            text="Mock agent: pushing exposure above the supported range to test max clamping.",
        ),
        operations=[
            Operation(
                operationId="op-exposure-clamp-max",
                kind="set-float",
                status="planned",
                target=OperationTarget(
                    type="darktable-action",
                    actionPath="iop/exposure/exposure",
                ),
                value=OperationValue(mode="set", number=99.0),
            )
        ],
        error=None,
    )

    exposure_clamp_min = ResponseEnvelope(
        requestId=request.requestId,
        conversationId=request.conversationId,
        status="ok",
        message=AssistantMessage(
            role="assistant",
            text="Mock agent: pushing exposure below the supported range to test min clamping.",
        ),
        operations=[
            Operation(
                operationId="op-exposure-clamp-min",
                kind="set-float",
                status="planned",
                target=OperationTarget(
                    type="darktable-action",
                    actionPath="iop/exposure/exposure",
                ),
                value=OperationValue(mode="set", number=-99.0),
            )
        ],
        error=None,
    )

    unsupported_action = ResponseEnvelope(
        requestId=request.requestId,
        conversationId=request.conversationId,
        status="ok",
        message=AssistantMessage(
            role="assistant",
            text=(
                "Mock agent: attempting one unsupported action so darktable "
                "can report a blocked operation cleanly."
            ),
        ),
        operations=[
            Operation(
                operationId="op-unsupported-action",
                kind="set-float",
                status="planned",
                target=OperationTarget(
                    type="darktable-action",
                    actionPath="iop/exposure/not-real",
                ),
                value=OperationValue(mode="delta", number=0.7),
            )
        ],
        error=None,
    )

    status_summary = ResponseEnvelope(
        requestId=request.requestId,
        conversationId=request.conversationId,
        status="ok",
        message=AssistantMessage(
            role="assistant",
            text=(
                "Mock agent status: server reachable, chat contract valid, "
                "and exposure edits are ready to apply."
            ),
        ),
        operations=[],
        error=None,
    )

    chat_echo = ResponseEnvelope(
        requestId=request.requestId,
        conversationId=request.conversationId,
        status="ok",
        message=AssistantMessage(
            role="assistant",
            text=(
                f"Echo: {request.message.text} "
                f"(view={request.uiContext.view}, imageId={request.uiContext.imageId}, "
                f"imageName={request.uiContext.imageName})"
            ),
        ),
        operations=[],
        error=None,
    )

    return {
        DEFAULT_MOCK_RESPONSE_ID: exposure_up,
        "exposure-minus-0.7": exposure_down,
        "exposure-sequence-plus-0.7": exposure_sequence,
        "exposure-set-1.25": exposure_set,
        "exposure-clamp-max": exposure_clamp_max,
        "exposure-clamp-min": exposure_clamp_min,
        "unsupported-action": unsupported_action,
        "status-summary": status_summary,
        "chat-echo": chat_echo,
    }


def build_mock_response(request: RequestEnvelope) -> ResponseEnvelope:
    mock_id = request.mockResponseId or DEFAULT_MOCK_RESPONSE_ID
    catalog = build_mock_response_catalog(request)
    return catalog.get(mock_id, catalog[DEFAULT_MOCK_RESPONSE_ID])


def parse_request_ids(payload: object) -> tuple[str, str]:
    if not isinstance(payload, dict):
        return "", ""
    request_id = payload.get("requestId")
    conversation_id = payload.get("conversationId")
    return (
        request_id if isinstance(request_id, str) else "",
        conversation_id if isinstance(conversation_id, str) else "",
    )
