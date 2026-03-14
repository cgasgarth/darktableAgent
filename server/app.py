from __future__ import annotations

import asyncio
import json
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from server.codex_app_server import CodexAppServerBridge, CodexAppServerError
from shared.protocol import (
    AssistantMessage,
    ErrorInfo,
    ProtocolError,
    RequestEnvelope,
    ResponseEnvelope,
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


def get_codex_bridge() -> CodexAppServerBridge:
    return _codex_bridge


def build_error_response(
    *,
    request_id: str,
    conversation_id: str,
    code: str,
    message: str,
    status_code: int,
) -> JSONResponse:
    payload = ResponseEnvelope(
        requestId=request_id,
        conversationId=conversation_id,
        status="error",
        message=AssistantMessage(role="assistant", text=message),
        operations=[],
        error=ErrorInfo(code=code, message=message),
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    del request
    body = getattr(exc, "body", None)
    request_id, conversation_id = parse_request_ids(body)
    message = "; ".join(
        f"{'/'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in exc.errors()
    )
    return build_error_response(
        request_id=request_id,
        conversation_id=conversation_id,
        code="invalid_request",
        message=message,
        status_code=422,
    )


@app.exception_handler(ProtocolError)
async def protocol_error_handler(request: Request, exc: ProtocolError) -> JSONResponse:
    del request
    return build_error_response(
        request_id="",
        conversation_id="",
        code=exc.code,
        message=exc.message,
        status_code=exc.status_code,
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/chat", response_model=ResponseEnvelope)
async def chat(request: RequestEnvelope) -> ResponseEnvelope:
    logger.info(
        "accepted_request",
        extra={
            "structured": {
                "event": "accepted_request",
                "requestId": request.requestId,
                "conversationId": request.conversationId,
                "view": request.uiContext.view,
                "imageId": request.uiContext.imageId,
                "imageName": request.uiContext.imageName,
                "capabilityCount": len(request.capabilities),
                "capabilities": [capability.model_dump() for capability in request.capabilities],
                "imageState": request.imageState.model_dump(),
                "messageText": request.message.text,
            }
        },
    )

    try:
        turn_result = await asyncio.to_thread(get_codex_bridge().plan, request)
    except CodexAppServerError as exc:
        return build_error_response(
            request_id=request.requestId,
            conversation_id=request.conversationId,
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
                "conversationId": request.conversationId,
                "codexThreadId": turn_result.thread_id,
                "codexTurnId": turn_result.turn_id,
                "operationCount": len(response.operations),
                "assistantText": response.message.text,
            }
        },
    )
    return response
