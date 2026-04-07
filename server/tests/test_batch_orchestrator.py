from __future__ import annotations

from dataclasses import dataclass

import pytest

from server.batch_orchestrator import BatchOrchestrator
from server.codex_app_server import CodexAppServerError
from shared.batch_protocol import BatchChatRequest
from shared.protocol import AgentPlan


def _sample_request_payload(request_id: str, image_id: int) -> dict:
    return {
        "schemaVersion": "3.0",
        "requestId": request_id,
        "session": {
            "appSessionId": "app-1",
            "imageSessionId": f"img-{image_id}",
            "conversationId": f"conv-{image_id}",
            "turnId": f"turn-{image_id}",
        },
        "message": {"role": "user", "text": "Make it brighter"},
        "fast": False,
        "refinement": {
            "mode": "single-turn",
            "enabled": False,
            "maxPasses": 1,
            "passIndex": 1,
            "goalText": "Make it brighter",
        },
        "uiContext": {
            "view": "darkroom",
            "imageId": image_id,
            "imageName": f"IMG_{image_id}.CR3",
        },
        "capabilityManifest": {
            "manifestVersion": "manifest-1",
            "targets": [
                {
                    "moduleId": "exposure",
                    "moduleLabel": "exposure",
                    "capabilityId": "exposure.primary",
                    "label": "Exposure",
                    "kind": "set-float",
                    "targetType": "darktable-action",
                    "actionPath": "iop/exposure/exposure",
                    "supportedModes": ["set", "delta"],
                    "minNumber": -18.0,
                    "maxNumber": 18.0,
                    "defaultNumber": 0.0,
                    "stepNumber": 0.01,
                }
            ],
        },
        "imageSnapshot": {
            "imageRevisionId": f"image-{image_id}-history-1",
            "metadata": {
                "imageId": image_id,
                "imageName": f"IMG_{image_id}.CR3",
                "cameraMaker": "Sony",
                "cameraModel": "ILCE-7RM5",
                "width": 9504,
                "height": 6336,
                "exifExposureSeconds": 0.01,
                "exifAperture": 4.0,
                "exifIso": 100.0,
                "exifFocalLength": 35.0,
            },
            "historyPosition": 1,
            "historyCount": 1,
            "editableSettings": [
                {
                    "moduleId": "exposure",
                    "moduleLabel": "exposure",
                    "settingId": "setting.exposure.primary",
                    "capabilityId": "exposure.primary",
                    "label": "Exposure",
                    "actionPath": "iop/exposure/exposure",
                    "kind": "set-float",
                    "currentNumber": 0.0,
                    "supportedModes": ["set", "delta"],
                    "minNumber": -18.0,
                    "maxNumber": 18.0,
                    "defaultNumber": 0.0,
                    "stepNumber": 0.01,
                }
            ],
            "history": [],
            "preview": None,
            "histogram": None,
        },
    }


def _sample_batch_payload(count: int, *, max_images: int = 10) -> dict:
    return {
        "selection": {"maxImages": max_images},
        "items": [
            {
                "candidateId": f"candidate-{index}",
                "request": _sample_request_payload(f"req-{index}", index),
            }
            for index in range(1, count + 1)
        ],
    }


@dataclass
class _FakeTurnResult:
    plan: AgentPlan
    thread_id: str
    turn_id: str
    raw_message: str


class _SuccessBridge:
    def plan(self, request):
        plan = AgentPlan.model_validate(
            {
                "assistantText": f"Edited {request.uiContext.imageName}",
                "continueRefining": False,
                "operations": [
                    {
                        "operationId": f"op-{request.requestId}",
                        "sequence": 1,
                        "kind": "set-float",
                        "target": {
                            "type": "darktable-action",
                            "actionPath": "iop/exposure/exposure",
                            "settingId": "setting.exposure.primary",
                        },
                        "value": {"mode": "delta", "number": 0.5},
                        "reason": None,
                        "constraints": {
                            "onOutOfRange": "clamp",
                            "onRevisionMismatch": "fail",
                        },
                    }
                ],
            }
        )
        return _FakeTurnResult(
            plan=plan,
            thread_id=f"thread-{request.requestId}",
            turn_id=f"turn-{request.requestId}",
            raw_message=plan.model_dump_json(),
        )


class _MixedBridge:
    def plan(self, request):
        if request.requestId.endswith("2"):
            raise CodexAppServerError(
                "planner_failed", "Planner rejected this candidate", status_code=422
            )
        return _SuccessBridge().plan(request)


@pytest.mark.anyio
async def test_batch_orchestrator_marks_excess_items_skipped() -> None:
    request = BatchChatRequest.model_validate(_sample_batch_payload(12, max_images=10))
    orchestrator = BatchOrchestrator(_SuccessBridge)

    response = await orchestrator.run(request)

    assert response.selectedCount == 10
    assert response.skippedCount == 2
    assert response.results[9].status == "ok"
    assert response.results[10].status == "skipped"
    assert response.results[10].skipReason == "batch-limit"
    assert response.results[10].selected is False


@pytest.mark.anyio
async def test_batch_orchestrator_captures_per_item_errors() -> None:
    request = BatchChatRequest.model_validate(_sample_batch_payload(3, max_images=3))
    orchestrator = BatchOrchestrator(_MixedBridge)

    response = await orchestrator.run(request)

    assert [result.status for result in response.results] == ["ok", "error", "ok"]
    assert response.results[1].error is not None
    assert response.results[1].error.code == "planner_failed"
    assert response.results[1].reviewTag == response.reviewTag
