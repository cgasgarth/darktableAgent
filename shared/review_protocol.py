from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


ReviewDecision = Literal["apply", "review", "skip"]


class ReviewMetadata(StrictBaseModel):
    decision: ReviewDecision
    summary: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def validate_tags(self) -> "ReviewMetadata":
        normalized_tags: list[str] = []
        seen_tags: set[str] = set()
        for raw_tag in self.tags:
            tag = raw_tag.strip()
            if not tag:
                raise ValueError("review tags must not be empty")
            folded_tag = tag.casefold()
            if folded_tag in seen_tags:
                raise ValueError("review tags must be unique")
            seen_tags.add(folded_tag)
            normalized_tags.append(tag)
        self.tags = normalized_tags
        return self
