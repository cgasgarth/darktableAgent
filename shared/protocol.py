from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0"


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Message(StrictBaseModel):
    role: Literal["user"]
    text: str = Field(min_length=1)


class UIContext(StrictBaseModel):
    view: str = Field(min_length=1)
    imageId: int | None
    imageName: str | None


class RequestEnvelope(StrictBaseModel):
    schemaVersion: Literal["1.0"]
    requestId: str = Field(min_length=1)
    conversationId: str = Field(min_length=1)
    message: Message
    uiContext: UIContext
    mockActionId: Literal["brighten-exposure", "darken-exposure"] | None


class ActionParameters(StrictBaseModel):
    deltaEv: float


class Action(StrictBaseModel):
    actionId: str = Field(min_length=1)
    type: Literal["adjust-exposure"]
    status: Literal["planned"]
    parameters: ActionParameters


class AssistantMessage(StrictBaseModel):
    role: Literal["assistant"]
    text: str


class ErrorInfo(StrictBaseModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ResponseEnvelope(StrictBaseModel):
    schemaVersion: Literal["1.0"] = SCHEMA_VERSION
    requestId: str
    conversationId: str
    status: Literal["ok", "error"]
    message: AssistantMessage
    actions: list[Action]
    error: ErrorInfo | None

    @model_validator(mode="after")
    def validate_status_consistency(self) -> "ResponseEnvelope":
        if self.status == "error" and self.actions:
            raise ValueError("error responses must not include actions")
        if self.status == "ok" and self.error is not None:
            raise ValueError("ok responses must not include error details")
        return self


class ProtocolError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def build_mock_response(request: RequestEnvelope) -> ResponseEnvelope:
    if request.mockActionId == "brighten-exposure":
        return ResponseEnvelope(
            requestId=request.requestId,
            conversationId=request.conversationId,
            status="ok",
            message=AssistantMessage(
                role="assistant",
                text="Planned a +0.7 EV exposure adjustment.",
            ),
            actions=[
                Action(
                    actionId="adjust-exposure-brighten",
                    type="adjust-exposure",
                    status="planned",
                    parameters=ActionParameters(deltaEv=0.7),
                )
            ],
            error=None,
        )
    if request.mockActionId == "darken-exposure":
        return ResponseEnvelope(
            requestId=request.requestId,
            conversationId=request.conversationId,
            status="ok",
            message=AssistantMessage(
                role="assistant",
                text="Planned a -0.7 EV exposure adjustment.",
            ),
            actions=[
                Action(
                    actionId="adjust-exposure-darken",
                    type="adjust-exposure",
                    status="planned",
                    parameters=ActionParameters(deltaEv=-0.7),
                )
            ],
            error=None,
        )
    return ResponseEnvelope(
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
        actions=[],
        error=None,
    )


def parse_request_ids(payload: object) -> tuple[str, str]:
    if not isinstance(payload, dict):
        return "", ""
    request_id = payload.get("requestId")
    conversation_id = payload.get("conversationId")
    return (
        request_id if isinstance(request_id, str) else "",
        conversation_id if isinstance(conversation_id, str) else "",
    )
