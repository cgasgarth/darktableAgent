from __future__ import annotations

import asyncio
import json
import logging
import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from server.codex_app_server import CodexAppServerBridge, CodexAppServerError
from server.mock_planner import MockPlannerBridge
from shared.protocol import (
    ErrorInfo,
    ProtocolError,
    RequestEnvelope,
    RequestSession,
    RefinementStatus,
    ResponseEnvelope,
    ResponseSession,
    AssistantMessage,
    build_response_from_plan,
    parse_request_ids,
)

logger = logging.getLogger("darktable_agent.server")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        structured = getattr(record, "structured", None)
        if isinstance(structured, dict):
            payload.update(structured)
        return json.dumps(payload, separators=(",", ":"))


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger.handlers.clear()
logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False

app = FastAPI(title="darktableAgent server", version="0.2.0")
_codex_bridge = CodexAppServerBridge()
_mock_bridge = MockPlannerBridge()


class CancelRequestEnvelope(BaseModel):
    requestId: str = Field(min_length=1)
    session: RequestSession


class CancelResponseEnvelope(BaseModel):
    requestId: str
    canceled: bool
    message: str


def get_codex_bridge() -> CodexAppServerBridge:
    if os.environ.get("DARKTABLE_AGENT_USE_MOCK_RESPONSES") == "1":
        return _mock_bridge
    return _codex_bridge


def build_request_error_refinement(request: RequestEnvelope) -> RefinementStatus:
    return RefinementStatus(
        mode=request.refinement.mode,
        enabled=request.refinement.enabled,
        passIndex=request.refinement.passIndex,
        maxPasses=request.refinement.maxPasses,
        continueRefining=False,
        stopReason="single-turn" if not request.refinement.enabled else "planner-complete",
    )


def build_error_response(
    *,
    request_id: str,
    session: dict[str, str],
    refinement: RefinementStatus | None,
    code: str,
    message: str,
    status_code: int,
) -> JSONResponse:
    payload = ResponseEnvelope(
        requestId=request_id,
        session=ResponseSession.model_validate(session),
        status="error",
        assistantMessage=AssistantMessage(role="assistant", text=message),
        refinement=refinement
        or RefinementStatus(
            mode="single-turn",
            enabled=False,
            passIndex=1,
            maxPasses=1,
            continueRefining=False,
            stopReason="single-turn",
        ),
        plan=None,
        operationResults=[],
        error=ErrorInfo(code=code, message=message),
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    del request
    body = getattr(exc, "body", None)
    request_id, session = parse_request_ids(body)
    message = "; ".join(
        f"{'/'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in exc.errors()
    )
    return build_error_response(
        request_id=request_id,
        session=session,
        refinement=None,
        code="invalid_request",
        message=message,
        status_code=422,
    )


@app.exception_handler(ProtocolError)
async def protocol_error_handler(request: Request, exc: ProtocolError) -> JSONResponse:
    del request
    return build_error_response(
        request_id="",
        session={
            "appSessionId": "",
            "imageSessionId": "",
            "conversationId": "",
            "turnId": "",
        },
        refinement=None,
        code=exc.code,
        message=exc.message,
        status_code=exc.status_code,
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/chat/cancel", response_model=CancelResponseEnvelope)
async def cancel_chat(request: CancelRequestEnvelope) -> CancelResponseEnvelope:
    logger.info(
        "cancel_request",
        extra={
            "structured": {
                "event": "cancel_request",
                "requestId": request.requestId,
                "appSessionId": request.session.appSessionId,
                "imageSessionId": request.session.imageSessionId,
                "conversationId": request.session.conversationId,
                "turnId": request.session.turnId,
            }
        },
    )

    canceled = await asyncio.to_thread(
        get_codex_bridge().cancel_request,
        request_id=request.requestId,
        app_session_id=request.session.appSessionId,
        image_session_id=request.session.imageSessionId,
        conversation_id=request.session.conversationId,
        turn_id=request.session.turnId,
    )
    message = (
        "Cancellation requested for the active chat turn"
        if canceled
        else "Cancellation recorded for this chat turn"
    )
    return CancelResponseEnvelope(
        requestId=request.requestId,
        canceled=True,
        message=message,
    )


@app.post("/v1/chat", response_model=ResponseEnvelope)
async def chat(request: RequestEnvelope) -> ResponseEnvelope:
    logger.info(
        "accepted_request",
        extra={
            "structured": {
                "event": "accepted_request",
                "requestId": request.requestId,
                "appSessionId": request.session.appSessionId,
                "imageSessionId": request.session.imageSessionId,
                "conversationId": request.session.conversationId,
                "turnId": request.session.turnId,
                "fast": request.fast,
                "refinement": request.refinement.model_dump(),
                "view": request.uiContext.view,
                "imageId": request.uiContext.imageId,
                "imageName": request.uiContext.imageName,
                "capabilityCount": len(request.capabilityManifest.targets),
                "capabilities": [
                    capability.model_dump() for capability in request.capabilityManifest.targets
                ],
                "imageSnapshot": request.imageSnapshot.model_dump(),
                "messageText": request.message.text,
            }
        },
    )

    try:
        turn_result = await asyncio.to_thread(get_codex_bridge().plan, request)
    except CodexAppServerError as exc:
        return build_error_response(
            request_id=request.requestId,
            session=request.session.model_dump(mode="json"),
            refinement=build_request_error_refinement(request),
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
        )

    response = build_response_from_plan(request, turn_result.plan)
    logger.info(
        "fulfilled_request",
        extra={
            "structured": {
                "event": "fulfilled_request",
                "requestId": request.requestId,
                "appSessionId": request.session.appSessionId,
                "imageSessionId": request.session.imageSessionId,
                "conversationId": request.session.conversationId,
                "turnId": request.session.turnId,
                "codexThreadId": turn_result.thread_id,
                "codexTurnId": turn_result.turn_id,
                "refinement": response.refinement.model_dump(),
                "operationCount": len(response.plan.operations) if response.plan else 0,
                "assistantText": response.assistantMessage.text,
            }
        },
    )
    return response
