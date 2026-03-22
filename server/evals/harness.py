from __future__ import annotations

import argparse
import base64
import binascii
import io
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from shared.protocol import AgentPlan, EditableSetting

from server.codex_bridge.canonical_binder import bind_canonical_actions
from server.codex_bridge.verifier import VerifierMixin

from .corpus import evaluation_corpus
from .models import (
    EvaluationCase,
    EvaluationMetrics,
    EvaluationResult,
    EvaluationSubmission,
)

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None


def evaluate_submission(
    case: EvaluationCase, submission: EvaluationSubmission
) -> EvaluationResult:
    failures: list[str] = []
    if submission.case_id != case.case_id:
        failures.append(
            f"submission case_id {submission.case_id} does not match {case.case_id}"
        )

    raw_operations = [
        operation.model_dump(mode="json") for operation in submission.plan.operations
    ]
    canonical_actions = list(submission.plan.canonicalActions or [])
    binding_result = bind_canonical_actions(
        case.request.imageSnapshot.editableSettings, canonical_actions
    )
    resolved_operations = raw_operations + binding_result.operations
    validation = _validate_operations(
        case.request.imageSnapshot.editableSettings, resolved_operations
    )

    preview_metrics = _preview_metrics_from_base64(submission.preview_base64)
    look_match_distance = _look_match_distance(
        submission.preview_base64, case.reference_preview_base64
    )
    source_look_match_distance = _look_match_distance(
        case.request.imageSnapshot.preview.base64Data
        if case.request.imageSnapshot.preview is not None
        else None,
        case.reference_preview_base64,
    )

    metrics = EvaluationMetrics(
        unknown_targets=validation["unknown_targets"],
        validation_failures=validation["validation_failures"],
        canonical_binding_failures=len(binding_result.failures),
        raw_operation_count=len(raw_operations),
        canonical_action_count=len(canonical_actions),
        resolved_operation_count=len(resolved_operations),
        tool_calls_used=submission.tool_calls_used,
        pass_count=submission.pass_count,
        highlight_clip_ratio=_metric_value(preview_metrics, "highlightClipRatio"),
        shadow_crush_ratio=_metric_value(preview_metrics, "shadowCrushRatio"),
        saturation_clip_ratio=_metric_value(preview_metrics, "saturationClipRatio"),
        look_match_distance=look_match_distance,
        source_look_match_distance=source_look_match_distance,
    )

    failures.extend(_evaluate_expectations(case, submission, resolved_operations))
    failures.extend(_evaluate_thresholds(case, metrics))

    return EvaluationResult(
        case_id=case.case_id,
        workflow=case.workflow,
        passed=not failures,
        failures=tuple(failures),
        metrics=metrics,
    )


def evaluate_corpus(
    cases: list[EvaluationCase], submissions: list[EvaluationSubmission] | None = None
) -> list[EvaluationResult]:
    if submissions is None:
        submissions = [case.golden_submission for case in cases]
    submission_by_case = {submission.case_id: submission for submission in submissions}

    results: list[EvaluationResult] = []
    for case in cases:
        submission = submission_by_case.get(case.case_id)
        if submission is None:
            results.append(
                EvaluationResult(
                    case_id=case.case_id,
                    workflow=case.workflow,
                    passed=False,
                    failures=(f"missing submission for {case.case_id}",),
                )
            )
            continue
        results.append(evaluate_submission(case, submission))
    return results


def load_submission_file(file_path: str | Path) -> list[EvaluationSubmission]:
    payload = json.loads(Path(file_path).read_text())
    raw_submissions = (
        payload.get("submissions") if isinstance(payload, dict) else payload
    )
    if not isinstance(raw_submissions, list):
        raise ValueError("submission file must contain a submissions array")

    submissions: list[EvaluationSubmission] = []
    for raw_submission in raw_submissions:
        if not isinstance(raw_submission, dict):
            raise ValueError("submission entries must be objects")
        case_id = raw_submission.get("caseId")
        raw_plan = raw_submission.get("plan")
        if not isinstance(case_id, str) or not isinstance(raw_plan, dict):
            raise ValueError("submission entries require caseId and plan")
        submissions.append(
            EvaluationSubmission(
                case_id=case_id,
                plan=AgentPlan.model_validate(raw_plan),
                preview_base64=_optional_string(raw_submission.get("previewBase64")),
                tool_calls_used=_optional_int(
                    raw_submission.get("toolCallsUsed"), default=0
                ),
                pass_count=_optional_int(raw_submission.get("passCount"), default=1),
            )
        )
    return submissions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the darktableAgent evaluation harness against the stable corpus."
    )
    parser.add_argument(
        "--submissions",
        help="Optional JSON file containing submissions to score instead of the built-in golden corpus.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON results instead of the human-readable summary.",
    )
    args = parser.parse_args(argv)

    cases = evaluation_corpus()
    submissions = load_submission_file(args.submissions) if args.submissions else None
    results = evaluate_corpus(cases, submissions)
    passed = sum(1 for result in results if result.passed)

    if args.json:
        print(
            json.dumps(
                {
                    "passed": passed,
                    "total": len(results),
                    "results": [
                        {
                            "caseId": result.case_id,
                            "workflow": result.workflow,
                            "passed": result.passed,
                            "failures": list(result.failures),
                            "metrics": asdict(result.metrics)
                            if result.metrics
                            else None,
                        }
                        for result in results
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(f"Evaluation harness: {passed}/{len(results)} cases passed")
        for result in results:
            status = "PASS" if result.passed else "FAIL"
            summary = f"{status} {result.case_id} ({result.workflow})"
            if (
                result.metrics is not None
                and result.metrics.look_match_distance is not None
            ):
                summary += f" look={result.metrics.look_match_distance:.3f}"
            print(summary)
            for failure in result.failures:
                print(f"  - {failure}")

    return 0 if passed == len(results) else 1


def _evaluate_expectations(
    case: EvaluationCase,
    submission: EvaluationSubmission,
    resolved_operations: list[dict[str, Any]],
) -> list[str]:
    failures: list[str] = []
    expectation = case.expectations

    assistant_text = submission.plan.assistantText.lower()
    for phrase in expectation.assistant_text_includes:
        if phrase.lower() not in assistant_text:
            failures.append(f"assistantText did not include '{phrase}'")

    if (
        expectation.continue_refining is not None
        and submission.plan.continueRefining != expectation.continue_refining
    ):
        failures.append(
            "continueRefining was "
            f"{submission.plan.continueRefining} but expected {expectation.continue_refining}"
        )

    action_paths = {
        str(operation.get("target", {}).get("actionPath") or "")
        for operation in resolved_operations
    }
    for path in expectation.required_action_paths:
        if path not in action_paths:
            failures.append(f"required actionPath {path} was not resolved")

    action_names = {action.action for action in submission.plan.canonicalActions or []}
    for action_name in expectation.required_canonical_actions:
        if action_name not in action_names:
            failures.append(f"required canonical action {action_name} was not present")
    return failures


def _evaluate_thresholds(case: EvaluationCase, metrics: EvaluationMetrics) -> list[str]:
    failures: list[str] = []
    thresholds = case.thresholds

    if metrics.unknown_targets > thresholds.max_unknown_targets:
        failures.append(
            f"unknown target count {metrics.unknown_targets} exceeds {thresholds.max_unknown_targets}"
        )
    if metrics.validation_failures > thresholds.max_validation_failures:
        failures.append(
            "validation failure count "
            f"{metrics.validation_failures} exceeds {thresholds.max_validation_failures}"
        )
    if metrics.canonical_binding_failures > thresholds.max_canonical_binding_failures:
        failures.append(
            "canonical binding failure count "
            f"{metrics.canonical_binding_failures} exceeds {thresholds.max_canonical_binding_failures}"
        )
    if (
        thresholds.max_resolved_operation_count is not None
        and metrics.resolved_operation_count > thresholds.max_resolved_operation_count
    ):
        failures.append(
            "resolved operation count "
            f"{metrics.resolved_operation_count} exceeds {thresholds.max_resolved_operation_count}"
        )
    if (
        thresholds.max_tool_calls_used is not None
        and metrics.tool_calls_used > thresholds.max_tool_calls_used
    ):
        failures.append(
            f"tool calls used {metrics.tool_calls_used} exceeds {thresholds.max_tool_calls_used}"
        )
    if (
        thresholds.max_pass_count is not None
        and metrics.pass_count > thresholds.max_pass_count
    ):
        failures.append(
            f"pass count {metrics.pass_count} exceeds {thresholds.max_pass_count}"
        )

    failures.extend(
        _check_metric_threshold(
            "highlight clip ratio",
            metrics.highlight_clip_ratio,
            thresholds.max_highlight_clip_ratio,
        )
    )
    failures.extend(
        _check_metric_threshold(
            "shadow crush ratio",
            metrics.shadow_crush_ratio,
            thresholds.max_shadow_crush_ratio,
        )
    )
    failures.extend(
        _check_metric_threshold(
            "saturation clip ratio",
            metrics.saturation_clip_ratio,
            thresholds.max_saturation_clip_ratio,
        )
    )
    failures.extend(
        _check_metric_threshold(
            "look-match distance",
            metrics.look_match_distance,
            thresholds.max_look_match_distance,
        )
    )

    if thresholds.require_look_match_improvement:
        if (
            metrics.look_match_distance is None
            or metrics.source_look_match_distance is None
            or metrics.look_match_distance >= metrics.source_look_match_distance
        ):
            failures.append(
                "candidate preview did not improve look-match distance over the source preview"
            )
    return failures


def _check_metric_threshold(
    label: str, value: float | None, threshold: float | None
) -> list[str]:
    if value is None or threshold is None:
        return []
    if value <= threshold:
        return []
    return [f"{label} {value:.3f} exceeds {threshold:.3f}"]


def _validate_operations(
    settings: list[EditableSetting], operations: list[dict[str, Any]]
) -> dict[str, int]:
    setting_by_id = {setting.settingId: setting for setting in settings}
    unknown_targets = 0
    validation_failures = 0
    for operation in operations:
        target = operation.get("target")
        value = operation.get("value")
        if not isinstance(target, dict) or not isinstance(value, dict):
            validation_failures += 1
            continue
        setting_id = target.get("settingId")
        action_path = target.get("actionPath")
        if not isinstance(setting_id, str) or not isinstance(action_path, str):
            validation_failures += 1
            continue
        setting = setting_by_id.get(setting_id)
        if setting is None or setting.actionPath != action_path:
            unknown_targets += 1
            continue
        validation_failures += _operation_validation_failures(setting, value)
    return {
        "unknown_targets": unknown_targets,
        "validation_failures": validation_failures,
    }


def _operation_validation_failures(
    setting: EditableSetting, value: dict[str, Any]
) -> int:
    kind = setting.kind
    if kind == "set-float":
        return _float_validation_failures(setting, value)
    if kind == "set-choice":
        return _choice_validation_failures(setting, value)
    return 0


def _float_validation_failures(setting: EditableSetting, value: dict[str, Any]) -> int:
    mode = value.get("mode")
    number = value.get("number")
    if mode not in {"set", "delta"} or not isinstance(number, (int, float)):
        return 1
    candidate = float(number)
    if mode == "delta":
        candidate += float(setting.currentNumber or setting.defaultNumber or 0.0)
    minimum = setting.minNumber
    maximum = setting.maxNumber
    if minimum is None or maximum is None:
        return 0
    return 0 if minimum <= candidate <= maximum else 1


def _choice_validation_failures(setting: EditableSetting, value: dict[str, Any]) -> int:
    if value.get("mode") != "set":
        return 1
    choice_id = value.get("choiceId")
    choice_value = value.get("choiceValue")
    for choice in setting.choices or []:
        if choice_id == choice.choiceId or choice_value == choice.choiceValue:
            return 0
    return 1


def _preview_metrics_from_base64(encoded: str | None) -> dict[str, float] | None:
    image_bytes = _decode_base64(encoded)
    if image_bytes is None:
        return None
    return VerifierMixin._preview_metrics(image_bytes)


def _look_match_distance(
    candidate_base64: str | None, reference_base64: str | None
) -> float | None:
    if Image is None:
        return None
    candidate_bytes = _decode_base64(candidate_base64)
    reference_bytes = _decode_base64(reference_base64)
    if candidate_bytes is None or reference_bytes is None:
        return None

    try:
        with Image.open(io.BytesIO(candidate_bytes)) as candidate_image:
            with Image.open(io.BytesIO(reference_bytes)) as reference_image:
                candidate = candidate_image.convert("RGB")
                reference = reference_image.convert("RGB")
                candidate.thumbnail((64, 64))
                reference = reference.resize(candidate.size)
                candidate_pixels = list(candidate.getdata())
                reference_pixels = list(reference.getdata())
    except Exception:
        return None

    if not candidate_pixels or len(candidate_pixels) != len(reference_pixels):
        return None

    total_difference = 0.0
    for candidate_pixel, reference_pixel in zip(candidate_pixels, reference_pixels):
        total_difference += sum(
            abs(candidate_channel - reference_channel)
            for candidate_channel, reference_channel in zip(
                candidate_pixel, reference_pixel
            )
        )
    normalizer = len(candidate_pixels) * 3 * 255.0
    return total_difference / normalizer


def _decode_base64(encoded: str | None) -> bytes | None:
    if not encoded:
        return None
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None


def _metric_value(metrics: dict[str, float] | None, key: str) -> float | None:
    if metrics is None:
        return None
    return metrics.get(key)


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_int(value: object, *, default: int) -> int:
    return int(value) if isinstance(value, int) else default


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
