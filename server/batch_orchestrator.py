from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from server.bridge_types import PlannerBridge
from server.codex_app_server import CodexAppServerError
from shared.batch_protocol import (
    BatchChatItem,
    BatchChatItemResult,
    BatchChatRequest,
    BatchChatResponse,
    build_batch_id,
    build_review_tag,
)
from shared.protocol import ErrorInfo, build_response_from_plan

logger = logging.getLogger("darktable_agent.server")


class BatchOrchestrator:
    def __init__(self, bridge_factory: Callable[[], PlannerBridge]) -> None:
        self._bridge_factory = bridge_factory

    async def run(self, request: BatchChatRequest) -> BatchChatResponse:
        batch_id = build_batch_id(request.batchId)
        review_tag = build_review_tag(batch_id, request.reviewTag)
        selected_items = request.items[: request.selection.maxImages]
        skipped_items = request.items[request.selection.maxImages :]
        bridge = self._bridge_factory()

        selected_results = await asyncio.gather(
            *[
                self._run_selected_item(
                    bridge=bridge,
                    item=item,
                    selection_rank=index,
                    review_tag=review_tag,
                )
                for index, item in enumerate(selected_items, start=1)
            ]
        )
        skipped_results = [
            self._build_skipped_result(item=item, review_tag=review_tag)
            for item in skipped_items
        ]
        ordered_results = [*selected_results, *skipped_results]

        return BatchChatResponse(
            batchId=batch_id,
            reviewTag=review_tag,
            submittedCount=len(request.items),
            selectedCount=len(selected_items),
            skippedCount=len(skipped_items),
            results=ordered_results,
        )

    async def _run_selected_item(
        self,
        *,
        bridge: PlannerBridge,
        item: BatchChatItem,
        selection_rank: int,
        review_tag: str,
    ) -> BatchChatItemResult:
        try:
            turn_result = await asyncio.to_thread(bridge.plan, item.request)
            response = build_response_from_plan(item.request, turn_result.plan)
            return BatchChatItemResult(
                candidateId=item.candidateId,
                requestId=item.request.requestId,
                imageSessionId=item.request.session.imageSessionId,
                imageId=item.request.uiContext.imageId,
                imageName=item.request.uiContext.imageName,
                selected=True,
                selectionRank=selection_rank,
                reviewTag=review_tag,
                status="ok",
                response=response,
                error=None,
                skipReason=None,
            )
        except CodexAppServerError as exc:
            return self._build_error_result(
                item=item,
                selection_rank=selection_rank,
                review_tag=review_tag,
                code=exc.code,
                message=exc.message,
            )
        except Exception:
            logger.exception(
                "batch_chat_item_unexpected_error",
                extra={
                    "structured": {
                        "event": "batch_chat_item_unexpected_error",
                        "candidateId": item.candidateId,
                        "requestId": item.request.requestId,
                        "imageSessionId": item.request.session.imageSessionId,
                        "conversationId": item.request.session.conversationId,
                        "turnId": item.request.session.turnId,
                    }
                },
            )
            return self._build_error_result(
                item=item,
                selection_rank=selection_rank,
                review_tag=review_tag,
                code="internal_error",
                message="Unexpected server error",
            )

    def _build_error_result(
        self,
        *,
        item: BatchChatItem,
        selection_rank: int,
        review_tag: str,
        code: str,
        message: str,
    ) -> BatchChatItemResult:
        return BatchChatItemResult(
            candidateId=item.candidateId,
            requestId=item.request.requestId,
            imageSessionId=item.request.session.imageSessionId,
            imageId=item.request.uiContext.imageId,
            imageName=item.request.uiContext.imageName,
            selected=True,
            selectionRank=selection_rank,
            reviewTag=review_tag,
            status="error",
            response=None,
            error=ErrorInfo(code=code, message=message),
            skipReason=None,
        )

    def _build_skipped_result(
        self, *, item: BatchChatItem, review_tag: str
    ) -> BatchChatItemResult:
        return BatchChatItemResult(
            candidateId=item.candidateId,
            requestId=item.request.requestId,
            imageSessionId=item.request.session.imageSessionId,
            imageId=item.request.uiContext.imageId,
            imageName=item.request.uiContext.imageName,
            selected=False,
            selectionRank=None,
            reviewTag=review_tag,
            status="skipped",
            response=None,
            error=None,
            skipReason="batch-limit",
        )
