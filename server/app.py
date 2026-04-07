from __future__ import annotations

import asyncio
from collections.abc import Mapping
import json
import logging
import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse, Response
from pydantic import BaseModel, Field

from server.bridge_types import PlannerBridge, PlannerTurnResult, RequestProgressPayload
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
codex_logger = logging.getLogger("darktable_agent.codex")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        structured = getattr(record, "structured", None)
        if isinstance(structured, dict):
            payload.update(structured)
        if record.exc_info:
            exc_type, exc_value, _ = record.exc_info
            payload["exception"] = {
                "type": exc_type.__name__ if exc_type else None,
                "message": str(exc_value) if exc_value is not None else None,
                "traceback": self.formatException(record.exc_info),
            }
        return json.dumps(payload, separators=(",", ":"))


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
for configured_logger in (logger, codex_logger):
    configured_logger.handlers.clear()
    configured_logger.addHandler(handler)
    configured_logger.setLevel(logging.INFO)
    configured_logger.propagate = False

app = FastAPI(title="darktableAgent server", version="0.2.0")
_codex_bridge = CodexAppServerBridge()
_mock_bridge = MockPlannerBridge()


class CancelRequestEnvelope(BaseModel):
    requestId: str = Field(min_length=1)
    session: RequestSession
    reason: str | None = None


class CancelResponseEnvelope(BaseModel):
    requestId: str
    canceled: bool
    message: str


def get_codex_bridge() -> PlannerBridge:
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
        stopReason="single-turn"
        if not request.refinement.enabled
        else "planner-complete",
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
    payload = build_error_payload(
        request_id=request_id,
        session=session,
        refinement=refinement,
        code=code,
        message=message,
    )
    return JSONResponse(status_code=status_code, content=payload)


def build_error_payload(
    *,
    request_id: str,
    session: dict[str, str],
    refinement: RefinementStatus | None,
    code: str,
    message: str,
) -> dict[str, Any]:
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
    return payload.model_dump()


def _log_accepted_request(request: RequestEnvelope) -> None:
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
                "editableSettingCount": len(request.imageSnapshot.editableSettings),
                "historyPosition": request.imageSnapshot.historyPosition,
                "historyCount": request.imageSnapshot.historyCount,
                "hasPreview": request.imageSnapshot.preview is not None,
                "hasHistogram": request.imageSnapshot.histogram is not None,
                "messageText": request.message.text,
            }
        },
    )


def _log_fulfilled_request(
    request: RequestEnvelope,
    response: ResponseEnvelope,
    turn_result: PlannerTurnResult,
) -> None:
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


def _encode_sse(event: str, payload: Mapping[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    del request
    body = getattr(exc, "body", None)
    request_id, session = parse_request_ids(body)
    error_parts: list[str] = []
    for error in exc.errors():
        if not isinstance(error, dict):
            continue
        location = error.get("loc")
        if isinstance(location, tuple):
            location_text = "/".join(str(part) for part in location)
        else:
            location_text = "request"
        message = error.get("msg")
        if isinstance(message, str):
            error_parts.append(f"{location_text}: {message}")
    message = "; ".join(error_parts) or "Request validation failed"
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
                "reason": request.reason,
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
        reason=request.reason,
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
async def chat(request: RequestEnvelope) -> ResponseEnvelope | JSONResponse:
    _log_accepted_request(request)

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
    except Exception:
        logger.exception(
            "chat_request_unexpected_error",
            extra={
                "structured": {
                    "event": "chat_request_unexpected_error",
                    "requestId": request.requestId,
                    "appSessionId": request.session.appSessionId,
                    "imageSessionId": request.session.imageSessionId,
                    "conversationId": request.session.conversationId,
                    "turnId": request.session.turnId,
                }
            },
        )
        return build_error_response(
            request_id=request.requestId,
            session=request.session.model_dump(mode="json"),
            refinement=build_request_error_refinement(request),
            code="internal_error",
            message="Unexpected server error",
            status_code=500,
        )

    response = build_response_from_plan(request, turn_result.plan)
    _log_fulfilled_request(request, response, turn_result)
    return response


@app.post("/v1/chat/stream")
async def chat_stream(request: RequestEnvelope) -> StreamingResponse:
    _log_accepted_request(request)

    async def event_generator():
        bridge = get_codex_bridge()
        plan_task = asyncio.create_task(asyncio.to_thread(bridge.plan, request))
        last_progress_signature: (
            tuple[int, bool, str, int, int, int, int, str, str | None, bool] | None
        ) = None
        last_progress_payload: RequestProgressPayload | None = None

        yield _encode_sse("accepted", {"requestId": request.requestId})

        while True:
            if plan_task.done():
                break

            progress_payload = await asyncio.to_thread(
                bridge.get_request_progress,
                request_id=request.requestId,
                app_session_id=request.session.appSessionId,
                image_session_id=request.session.imageSessionId,
                conversation_id=request.session.conversationId,
                turn_id=request.session.turnId,
            )
            progress_signature = (
                progress_payload["progressVersion"],
                progress_payload["found"],
                progress_payload["status"],
                progress_payload["toolCallsUsed"],
                progress_payload["maxToolCalls"],
                progress_payload["appliedOperationCount"],
                len(progress_payload["operations"]),
                progress_payload["message"],
                progress_payload["lastToolName"],
                progress_payload["requiresRenderCallback"],
            )
            if progress_signature != last_progress_signature:
                last_progress_signature = progress_signature
                last_progress_payload = {
                    "found": progress_payload["found"],
                    "status": progress_payload["status"],
                    "toolCallsUsed": progress_payload["toolCallsUsed"],
                    "maxToolCalls": progress_payload["maxToolCalls"],
                    "appliedOperationCount": progress_payload["appliedOperationCount"],
                    "operations": list(progress_payload["operations"]),
                    "message": progress_payload["message"],
                    "lastToolName": progress_payload["lastToolName"],
                    "progressVersion": progress_payload["progressVersion"],
                    "requiresRenderCallback": progress_payload[
                        "requiresRenderCallback"
                    ],
                }
                yield _encode_sse("progress", progress_payload)

            await asyncio.sleep(0.25)

        try:
            turn_result = plan_task.result()
            response = build_response_from_plan(request, turn_result.plan)
            _log_fulfilled_request(request, response, turn_result)
            completion_progress: RequestProgressPayload = (
                {
                    "found": last_progress_payload["found"],
                    "status": last_progress_payload["status"],
                    "toolCallsUsed": last_progress_payload["toolCallsUsed"],
                    "maxToolCalls": last_progress_payload["maxToolCalls"],
                    "appliedOperationCount": last_progress_payload[
                        "appliedOperationCount"
                    ],
                    "operations": list(last_progress_payload["operations"]),
                    "message": last_progress_payload["message"],
                    "lastToolName": last_progress_payload["lastToolName"],
                    "progressVersion": last_progress_payload["progressVersion"],
                    "requiresRenderCallback": False,
                }
                if last_progress_payload is not None
                else {
                    "found": True,
                    "status": "running",
                    "toolCallsUsed": 0,
                    "maxToolCalls": request.refinement.maxPasses
                    if request.refinement.enabled
                    else 1,
                    "appliedOperationCount": len(response.plan.operations)
                    if response.plan
                    else 0,
                    "operations": [],
                    "message": "Waiting for Codex turn output",
                    "lastToolName": None,
                    "progressVersion": 0,
                    "requiresRenderCallback": False,
                }
            )
            completion_progress["found"] = True
            completion_progress["status"] = "completed"
            completion_progress["message"] = "Codex plan completed"
            completion_progress["progressVersion"] = (
                completion_progress["progressVersion"] + 1
            )
            yield _encode_sse("progress", completion_progress)
            yield _encode_sse("final", response.model_dump(mode="json"))
        except CodexAppServerError as exc:
            payload = build_error_payload(
                request_id=request.requestId,
                session=request.session.model_dump(mode="json"),
                refinement=build_request_error_refinement(request),
                code=exc.code,
                message=exc.message,
            )
            yield _encode_sse("error", payload)
        except Exception:
            logger.exception(
                "chat_request_unexpected_error",
                extra={
                    "structured": {
                        "event": "chat_request_unexpected_error",
                        "requestId": request.requestId,
                        "appSessionId": request.session.appSessionId,
                        "imageSessionId": request.session.imageSessionId,
                        "conversationId": request.session.conversationId,
                        "turnId": request.session.turnId,
                    }
                },
            )
            payload = build_error_payload(
                request_id=request.requestId,
                session=request.session.model_dump(mode="json"),
                refinement=build_request_error_refinement(request),
                code="internal_error",
                message="Unexpected server error",
            )
            yield _encode_sse("error", payload)

        yield _encode_sse("completed", {"requestId": request.requestId})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/v1/chat/render")
async def chat_render(request: Request) -> Response:
    image_session_id = request.headers.get("X-Darktable-Image-Session-Id")
    turn_id = request.headers.get("X-Darktable-Turn-Id")
    if not image_session_id or not turn_id:
        return Response(status_code=400, content="Missing tracking headers")

    payload_bytes = await request.body()
    if not payload_bytes:
        return Response(status_code=400, content="Empty body")

    bridge = get_codex_bridge()
    success = await asyncio.to_thread(
        bridge.provide_render_callback,
        image_session_id=image_session_id,
        turn_id=turn_id,
        image_bytes=payload_bytes,
    )
    if success:
        return Response(status_code=200, content="OK")
    return Response(status_code=404, content="Context not found")
