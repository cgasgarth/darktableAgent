from __future__ import annotations

from shared.protocol import AgentPlan

from server.evals.corpus import evaluation_corpus
from server.evals.harness import evaluate_corpus, evaluate_submission
from server.evals.models import EvaluationSubmission


def test_golden_evaluation_corpus_passes() -> None:
    results = evaluate_corpus(evaluation_corpus())

    assert results
    assert all(result.passed for result in results)


def test_harness_detects_preview_and_efficiency_regression() -> None:
    case = evaluation_corpus()[0]
    bad_submission = EvaluationSubmission(
        case_id=case.case_id,
        plan=case.golden_submission.plan,
        preview_base64=(
            case.request.imageSnapshot.preview.base64Data
            if case.request.imageSnapshot.preview is not None
            else None
        ),
        tool_calls_used=6,
        pass_count=4,
    )

    result = evaluate_submission(case, bad_submission)

    assert result.passed is False
    assert any("tool calls used" in failure for failure in result.failures)
    assert any("pass count" in failure for failure in result.failures)
    assert any("look-match distance" in failure for failure in result.failures)


def test_harness_detects_invalid_operation_targets() -> None:
    case = evaluation_corpus()[1]
    invalid_plan = AgentPlan.model_validate(
        {
            "assistantText": "Broken result.",
            "continueRefining": False,
            "operations": [
                {
                    "operationId": "bad-op",
                    "sequence": 1,
                    "kind": "set-float",
                    "target": {
                        "type": "darktable-action",
                        "actionPath": "iop/exposure/exposure",
                        "settingId": "setting.does.not.exist",
                    },
                    "value": {"mode": "delta", "number": 0.4},
                    "reason": "Broken fixture for regression coverage.",
                    "constraints": {
                        "onOutOfRange": "clamp",
                        "onRevisionMismatch": "fail",
                    },
                }
            ],
            "canonicalActions": [],
        }
    )
    submission = EvaluationSubmission(
        case_id=case.case_id,
        plan=invalid_plan,
        preview_base64=case.reference_preview_base64,
        tool_calls_used=1,
        pass_count=1,
    )

    result = evaluate_submission(case, submission)

    assert result.passed is False
    assert result.metrics is not None
    assert result.metrics.unknown_targets == 1
    assert any("unknown target count" in failure for failure in result.failures)
