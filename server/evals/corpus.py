from __future__ import annotations

from shared.protocol import AgentPlan

from .fixtures import (
    build_request,
)
from .models import (
    EvaluationCase,
    EvaluationExpectations,
    EvaluationSubmission,
    EvaluationThresholds,
)
from .previews import (
    landscape_source_preview,
    landscape_target_preview,
    mixed_source_preview,
    mixed_target_preview,
    night_source_preview,
    night_target_preview,
    portrait_source_preview,
    portrait_target_preview,
    product_source_preview,
    product_target_preview,
)


def evaluation_corpus() -> list[EvaluationCase]:
    return [
        _make_case(
            case_id="portrait-natural-baseline",
            workflow="natural-baseline",
            description="Portrait baseline with white-balance correction, highlight restraint, and gentle chroma noise cleanup.",
            request_text="Make this portrait clean and natural. Balance white balance, protect highlights, and gently reduce chroma noise.",
            source_preview=portrait_source_preview(),
            reference_preview=portrait_target_preview(),
            iso=400.0,
            expectations=EvaluationExpectations(
                required_action_paths=(
                    "iop/temperature/temperature",
                    "iop/temperature/tint",
                    "iop/filmicrgb/white_relative_exposure",
                    "iop/denoiseprofile/chroma",
                ),
                required_canonical_actions=(
                    "adjust-white-balance",
                    "recover-highlights",
                    "reduce-noise",
                ),
                assistant_text_includes=("portrait", "natural"),
                continue_refining=False,
            ),
            thresholds=EvaluationThresholds(
                max_resolved_operation_count=4,
                max_tool_calls_used=2,
                max_pass_count=1,
                max_highlight_clip_ratio=0.08,
                max_shadow_crush_ratio=0.12,
                max_saturation_clip_ratio=0.12,
                max_look_match_distance=0.01,
                require_look_match_improvement=True,
            ),
            plan_payload={
                "assistantText": "Golden portrait natural baseline.",
                "continueRefining": False,
                "operations": [],
                "canonicalActions": [
                    {
                        "action": "adjust-white-balance",
                        "temperatureDelta": -250.0,
                        "tintDelta": -0.03,
                        "rationale": "Neutralize warm skin cast.",
                    },
                    {
                        "action": "recover-highlights",
                        "strength": "low",
                        "rationale": "Protect bright forehead highlights.",
                    },
                    {
                        "action": "reduce-noise",
                        "strength": "low",
                        "noiseType": "chroma",
                        "rationale": "Clean chroma speckling without smoothing skin texture.",
                    },
                ],
            },
            tool_calls_used=2,
        ),
        _make_case(
            case_id="landscape-cinematic-muted",
            workflow="cinematic-muted",
            description="Landscape grade with restrained blue saturation, highlight recovery, and gentle contrast shaping.",
            request_text="Give this landscape a cinematic muted finish. Recover the sky, lift exposure a touch, calm the blues, and add gentle contrast.",
            source_preview=landscape_source_preview(),
            reference_preview=landscape_target_preview(),
            iso=100.0,
            expectations=EvaluationExpectations(
                required_action_paths=(
                    "iop/exposure/exposure",
                    "iop/filmicrgb/white_relative_exposure",
                    "iop/colorequal/sat_blue",
                    "iop/colorbalancergb/global_contrast",
                ),
                required_canonical_actions=(
                    "adjust-exposure",
                    "recover-highlights",
                    "grade-color",
                ),
                assistant_text_includes=("cinematic", "muted"),
                continue_refining=False,
            ),
            thresholds=EvaluationThresholds(
                max_resolved_operation_count=4,
                max_tool_calls_used=3,
                max_pass_count=1,
                max_highlight_clip_ratio=0.04,
                max_shadow_crush_ratio=0.12,
                max_saturation_clip_ratio=0.04,
                max_look_match_distance=0.01,
                require_look_match_improvement=True,
            ),
            plan_payload={
                "assistantText": "Golden cinematic muted landscape grade.",
                "continueRefining": False,
                "operations": [],
                "canonicalActions": [
                    {
                        "action": "adjust-exposure",
                        "exposureEv": 0.3,
                        "rationale": "Open the landscape slightly.",
                    },
                    {
                        "action": "recover-highlights",
                        "strength": "medium",
                        "rationale": "Hold cloud detail in the sky.",
                    },
                    {
                        "action": "grade-color",
                        "target": "blue-saturation",
                        "amount": -0.12,
                        "rationale": "Mute the blues.",
                    },
                    {
                        "action": "grade-color",
                        "target": "global-contrast",
                        "amount": 0.15,
                        "rationale": "Add gentle shape.",
                    },
                ],
            },
            tool_calls_used=3,
        ),
        _make_case(
            case_id="product-color-accurate",
            workflow="color-accurate",
            description="Product correction with neutral whites and restrained exposure movement.",
            request_text="Make this product shot color-accurate and clean. Neutralize the cast and nudge exposure without over-styling it.",
            source_preview=product_source_preview(),
            reference_preview=product_target_preview(),
            iso=200.0,
            expectations=EvaluationExpectations(
                required_action_paths=(
                    "iop/temperature/preset",
                    "iop/exposure/exposure",
                ),
                required_canonical_actions=("adjust-white-balance", "adjust-exposure"),
                assistant_text_includes=("product", "accurate"),
                continue_refining=False,
            ),
            thresholds=EvaluationThresholds(
                max_resolved_operation_count=2,
                max_tool_calls_used=1,
                max_pass_count=1,
                max_highlight_clip_ratio=0.0,
                max_shadow_crush_ratio=0.08,
                max_saturation_clip_ratio=0.02,
                max_look_match_distance=0.01,
                require_look_match_improvement=True,
            ),
            plan_payload={
                "assistantText": "Golden product cleanup for accurate neutral output.",
                "continueRefining": False,
                "operations": [],
                "canonicalActions": [
                    {
                        "action": "adjust-white-balance",
                        "presetChoiceId": "daylight",
                        "rationale": "Restore neutral whites.",
                    },
                    {
                        "action": "adjust-exposure",
                        "exposureEv": 0.1,
                        "rationale": "Lift exposure slightly for catalog presentation.",
                    },
                ],
            },
            tool_calls_used=1,
        ),
        _make_case(
            case_id="event-mixed-lighting-reframe",
            workflow="mixed-lighting",
            description="Mixed-lighting event correction with white-balance cleanup and a tighter subject crop.",
            request_text="Fix this mixed-light event frame, keep the subject natural, and crop tighter around them with a little breathing room.",
            source_preview=mixed_source_preview(),
            reference_preview=mixed_target_preview(),
            iso=1600.0,
            expectations=EvaluationExpectations(
                required_action_paths=(
                    "iop/exposure/exposure",
                    "iop/temperature/temperature",
                    "iop/temperature/tint",
                    "iop/clipping/cx",
                    "iop/clipping/cy",
                    "iop/clipping/cw",
                    "iop/clipping/ch",
                ),
                required_canonical_actions=(
                    "adjust-exposure",
                    "adjust-white-balance",
                    "crop-to-bounding-box",
                ),
                assistant_text_includes=("mixed-light", "crop"),
                continue_refining=False,
            ),
            thresholds=EvaluationThresholds(
                max_resolved_operation_count=7,
                max_tool_calls_used=3,
                max_pass_count=2,
                max_highlight_clip_ratio=0.0,
                max_shadow_crush_ratio=0.12,
                max_saturation_clip_ratio=0.06,
                max_look_match_distance=0.01,
                require_look_match_improvement=True,
            ),
            plan_payload={
                "assistantText": "Golden mixed-lighting correction with a subject reframe crop.",
                "continueRefining": False,
                "operations": [],
                "canonicalActions": [
                    {
                        "action": "adjust-exposure",
                        "exposureEv": 0.2,
                        "rationale": "Open the event frame slightly.",
                    },
                    {
                        "action": "adjust-white-balance",
                        "temperatureDelta": -180.0,
                        "tintDelta": -0.02,
                        "rationale": "Balance tungsten and cooler ambient light.",
                    },
                    {
                        "action": "crop-to-bounding-box",
                        "boxLeft": 0.25,
                        "boxTop": 0.16,
                        "boxWidth": 0.38,
                        "boxHeight": 0.52,
                        "paddingRatio": 0.08,
                        "rationale": "Tighten around the subject with breathing room.",
                    },
                ],
            },
            tool_calls_used=3,
            pass_count=2,
        ),
        _make_case(
            case_id="night-high-iso-noise-aware",
            workflow="night-high-iso",
            description="High-ISO night cleanup balancing lift, noise control, and highlight restraint.",
            request_text="Clean up this high-ISO night frame. Lift it a touch, reduce both luma and chroma noise, and keep the lights under control.",
            source_preview=night_source_preview(),
            reference_preview=night_target_preview(),
            iso=6400.0,
            expectations=EvaluationExpectations(
                required_action_paths=(
                    "iop/exposure/exposure",
                    "iop/denoiseprofile/chroma",
                    "iop/denoiseprofile/luma",
                    "iop/filmicrgb/white_relative_exposure",
                ),
                required_canonical_actions=(
                    "adjust-exposure",
                    "reduce-noise",
                    "recover-highlights",
                ),
                assistant_text_includes=("night", "noise"),
                continue_refining=False,
            ),
            thresholds=EvaluationThresholds(
                max_resolved_operation_count=4,
                max_tool_calls_used=3,
                max_pass_count=2,
                max_highlight_clip_ratio=0.0,
                max_shadow_crush_ratio=0.2,
                max_saturation_clip_ratio=0.04,
                max_look_match_distance=0.01,
                require_look_match_improvement=True,
            ),
            plan_payload={
                "assistantText": "Golden night cleanup with careful noise control.",
                "continueRefining": False,
                "operations": [],
                "canonicalActions": [
                    {
                        "action": "adjust-exposure",
                        "exposureEv": 0.25,
                        "rationale": "Lift the shadows a touch.",
                    },
                    {
                        "action": "reduce-noise",
                        "strength": "high",
                        "noiseType": "both",
                        "rationale": "Reduce high-ISO luma and chroma noise.",
                    },
                    {
                        "action": "recover-highlights",
                        "strength": "low",
                        "rationale": "Keep point lights controlled.",
                    },
                ],
            },
            tool_calls_used=3,
            pass_count=2,
        ),
    ]


def _make_case(
    *,
    case_id: str,
    workflow: str,
    description: str,
    request_text: str,
    source_preview: str,
    reference_preview: str,
    iso: float,
    expectations: EvaluationExpectations,
    thresholds: EvaluationThresholds,
    plan_payload: dict[str, object],
    tool_calls_used: int,
    pass_count: int = 1,
) -> EvaluationCase:
    request = build_request(
        request_id=f"eval-{case_id}",
        text=request_text,
        goal_text=request_text,
        preview_base64=source_preview,
        iso=iso,
    )
    golden_plan = AgentPlan.model_validate(plan_payload)
    golden_submission = EvaluationSubmission(
        case_id=case_id,
        plan=golden_plan,
        preview_base64=reference_preview,
        tool_calls_used=tool_calls_used,
        pass_count=pass_count,
    )
    return EvaluationCase(
        case_id=case_id,
        workflow=workflow,
        description=description,
        request=request,
        reference_preview_base64=reference_preview,
        expectations=expectations,
        thresholds=thresholds,
        golden_submission=golden_submission,
    )
