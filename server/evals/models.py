from __future__ import annotations

from dataclasses import dataclass, field

from shared.protocol import AgentPlan, RequestEnvelope


@dataclass(frozen=True, slots=True)
class EvaluationExpectations:
    required_action_paths: tuple[str, ...] = ()
    required_canonical_actions: tuple[str, ...] = ()
    assistant_text_includes: tuple[str, ...] = ()
    continue_refining: bool | None = None


@dataclass(frozen=True, slots=True)
class EvaluationThresholds:
    max_unknown_targets: int = 0
    max_validation_failures: int = 0
    max_canonical_binding_failures: int = 0
    max_resolved_operation_count: int | None = None
    max_tool_calls_used: int | None = None
    max_pass_count: int | None = None
    max_highlight_clip_ratio: float | None = None
    max_shadow_crush_ratio: float | None = None
    max_saturation_clip_ratio: float | None = None
    max_look_match_distance: float | None = None
    require_look_match_improvement: bool = False


@dataclass(frozen=True, slots=True)
class EvaluationSubmission:
    case_id: str
    plan: AgentPlan
    preview_base64: str | None = None
    tool_calls_used: int = 0
    pass_count: int = 1


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    case_id: str
    workflow: str
    description: str
    request: RequestEnvelope
    reference_preview_base64: str | None
    expectations: EvaluationExpectations
    thresholds: EvaluationThresholds
    golden_submission: EvaluationSubmission


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    unknown_targets: int
    validation_failures: int
    canonical_binding_failures: int
    raw_operation_count: int
    canonical_action_count: int
    resolved_operation_count: int
    tool_calls_used: int
    pass_count: int
    highlight_clip_ratio: float | None = None
    shadow_crush_ratio: float | None = None
    saturation_clip_ratio: float | None = None
    look_match_distance: float | None = None
    source_look_match_distance: float | None = None


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    case_id: str
    workflow: str
    passed: bool
    failures: tuple[str, ...] = field(default_factory=tuple)
    metrics: EvaluationMetrics | None = None
