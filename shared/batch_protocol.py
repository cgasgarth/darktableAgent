from __future__ import annotations

import re
import uuid
from typing import Literal

from pydantic import Field, model_validator

from .protocol import (
    ErrorInfo,
    RequestEnvelope,
    ResponseEnvelope,
    SCHEMA_VERSION,
    StrictBaseModel,
)

_DEFAULT_BATCH_LIMIT = 10
_TAG_SAFE_CHARS_RE = re.compile(r"[^a-z0-9._-]+")


class BatchChatItem(StrictBaseModel):
    candidateId: str = Field(min_length=1)
    request: RequestEnvelope


class BatchSelectionConfig(StrictBaseModel):
    maxImages: int = Field(default=_DEFAULT_BATCH_LIMIT, ge=1, le=_DEFAULT_BATCH_LIMIT)
    strategy: Literal["request-order"] = "request-order"


class BatchChatRequest(StrictBaseModel):
    schemaVersion: Literal["3.0"] = SCHEMA_VERSION
    batchId: str | None = None
    reviewTag: str | None = None
    selection: BatchSelectionConfig = Field(default_factory=BatchSelectionConfig)
    items: list[BatchChatItem] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_candidate_ids(self) -> "BatchChatRequest":
        candidate_ids = [item.candidateId for item in self.items]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError(
                "batch items must not contain duplicate candidateId values"
            )
        for item in self.items:
            if item.request.refinement.enabled:
                raise ValueError(
                    "batch requests currently support single-turn refinement only"
                )
        return self


class BatchChatItemResult(StrictBaseModel):
    candidateId: str
    requestId: str
    imageSessionId: str
    imageId: int | None
    imageName: str | None
    selected: bool
    selectionRank: int | None
    reviewTag: str | None
    status: Literal["ok", "error", "skipped"]
    response: ResponseEnvelope | None
    error: ErrorInfo | None
    skipReason: Literal["batch-limit"] | None

    @model_validator(mode="after")
    def validate_status_payload(self) -> "BatchChatItemResult":
        if self.status == "ok":
            if (
                self.response is None
                or self.error is not None
                or self.skipReason is not None
            ):
                raise ValueError("ok batch results must include response only")
        elif self.status == "error":
            if (
                self.response is not None
                or self.error is None
                or self.skipReason is not None
            ):
                raise ValueError("error batch results must include error only")
        else:
            if (
                self.response is not None
                or self.error is not None
                or self.skipReason is None
            ):
                raise ValueError("skipped batch results must include skipReason only")
        return self


class BatchChatResponse(StrictBaseModel):
    schemaVersion: Literal["3.0"] = SCHEMA_VERSION
    batchId: str = Field(min_length=1)
    reviewTag: str = Field(min_length=1)
    submittedCount: int = Field(ge=1)
    selectedCount: int = Field(ge=0)
    skippedCount: int = Field(ge=0)
    results: list[BatchChatItemResult] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_counts(self) -> "BatchChatResponse":
        if self.submittedCount != len(self.results):
            raise ValueError("submittedCount must match number of results")
        selected_count = sum(1 for result in self.results if result.selected)
        skipped_count = sum(1 for result in self.results if result.status == "skipped")
        if self.selectedCount != selected_count:
            raise ValueError("selectedCount must match selected results")
        if self.skippedCount != skipped_count:
            raise ValueError("skippedCount must match skipped results")
        return self


def build_batch_id(batch_id: str | None) -> str:
    if batch_id:
        return batch_id
    return f"batch-{uuid.uuid4().hex[:12]}"


def build_review_tag(batch_id: str, review_tag: str | None) -> str:
    if review_tag:
        return review_tag
    normalized_batch_id = _TAG_SAFE_CHARS_RE.sub("-", batch_id.lower()).strip("-")
    if not normalized_batch_id:
        normalized_batch_id = "batch"
    return f"darktable|agent-batch|{normalized_batch_id}"
