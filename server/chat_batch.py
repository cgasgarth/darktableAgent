from __future__ import annotations

from collections.abc import Callable

from server.batch_orchestrator import BatchOrchestrator
from server.bridge_types import PlannerBridge
from shared.batch_protocol import BatchChatRequest, BatchChatItemResult
from shared.chat_batch_protocol import (
    BatchRequestEnvelope,
    BatchRequestItem,
    BatchResponseEnvelope,
    BatchResponseItem,
)
from shared.protocol import (
    AssistantMessage,
    ErrorInfo,
    RefinementStatus,
    RequestEnvelope,
    ResponseSession,
)


def build_batch_item_request(
    batch_request: BatchRequestEnvelope, item: BatchRequestItem
) -> RequestEnvelope:
    return RequestEnvelope(
        schemaVersion=batch_request.schemaVersion,
        requestId=f"{batch_request.requestId}:{item.batchItemId}",
        session=item.session,
        message=batch_request.message,
        fast=batch_request.fast,
        refinement=batch_request.refinement,
        uiContext=item.uiContext,
        capabilityManifest=item.capabilityManifest,
        imageSnapshot=item.imageSnapshot,
    )


def build_chat_batch_response_item(
    item: BatchRequestItem, result: BatchChatItemResult
) -> BatchResponseItem:
    if result.response is not None:
        return BatchResponseItem(
            batchItemId=item.batchItemId,
            **result.response.model_dump(mode="json"),
        )

    error = result.error or ErrorInfo(
        code="internal_error", message="Unexpected server error"
    )
    return BatchResponseItem(
        batchItemId=item.batchItemId,
        requestId=result.requestId,
        session=ResponseSession.model_validate(item.session.model_dump(mode="json")),
        status="error",
        assistantMessage=AssistantMessage(role="assistant", text=error.message),
        refinement=RefinementStatus(
            mode="single-turn",
            enabled=False,
            passIndex=1,
            maxPasses=1,
            continueRefining=False,
            stopReason="single-turn",
        ),
        plan=None,
        operationResults=[],
        review=None,
        error=error,
    )


async def run_chat_batch(
    request: BatchRequestEnvelope,
    bridge_factory: Callable[[], PlannerBridge],
) -> BatchResponseEnvelope:
    internal_request = BatchChatRequest.model_validate(
        {
            "batchId": request.requestId,
            "items": [
                {
                    "candidateId": item.batchItemId,
                    "request": build_batch_item_request(request, item).model_dump(
                        mode="json"
                    ),
                }
                for item in request.items
            ],
        }
    )
    orchestrator = BatchOrchestrator(bridge_factory)
    response = await orchestrator.run(internal_request)
    batch_items = [
        build_chat_batch_response_item(item, result)
        for item, result in zip(request.items, response.results, strict=True)
    ]
    error_count = sum(1 for item in batch_items if item.status == "error")
    success_count = len(batch_items) - error_count
    if error_count == 0:
        status = "ok"
    elif success_count == 0:
        status = "error"
    else:
        status = "partial-error"
    return BatchResponseEnvelope(
        requestId=request.requestId,
        status=status,
        itemCount=len(batch_items),
        successCount=success_count,
        errorCount=error_count,
        reviewTag=response.reviewTag,
        items=batch_items,
    )
