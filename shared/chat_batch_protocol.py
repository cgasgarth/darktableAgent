from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .protocol import (
    RefinementRequest,
    RequestSession,
    ResponseEnvelope,
    SCHEMA_VERSION,
    StrictBaseModel,
    UIContext,
    UserMessage,
    CapabilityManifest,
    ImageSnapshot,
)


class BatchRequestItem(StrictBaseModel):
    batchItemId: str = Field(min_length=1)
    session: RequestSession
    uiContext: UIContext
    capabilityManifest: CapabilityManifest
    imageSnapshot: ImageSnapshot


class BatchRequestEnvelope(StrictBaseModel):
    schemaVersion: Literal["3.0"] = SCHEMA_VERSION
    requestId: str = Field(min_length=1)
    message: UserMessage
    fast: bool
    refinement: RefinementRequest
    items: list[BatchRequestItem] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_batch_shape(self) -> "BatchRequestEnvelope":
        if self.refinement.enabled:
            raise ValueError(
                "batch requests currently support single-turn refinement only"
            )
        batch_item_ids = [item.batchItemId for item in self.items]
        if len(batch_item_ids) != len(set(batch_item_ids)):
            raise ValueError(
                "batch requests must not contain duplicate batchItemId values"
            )
        return self


class BatchResponseItem(ResponseEnvelope):
    batchItemId: str = Field(min_length=1)


class BatchResponseEnvelope(StrictBaseModel):
    schemaVersion: Literal["3.0"] = SCHEMA_VERSION
    requestId: str = Field(min_length=1)
    status: str
    itemCount: int = Field(ge=0)
    successCount: int = Field(ge=0)
    errorCount: int = Field(ge=0)
    reviewTag: str = Field(min_length=1)
    items: list[BatchResponseItem]

    @model_validator(mode="after")
    def validate_counts(self) -> "BatchResponseEnvelope":
        if self.itemCount != len(self.items):
            raise ValueError("itemCount must match number of items")
        return self
