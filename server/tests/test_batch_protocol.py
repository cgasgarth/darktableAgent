import pytest
from pydantic import ValidationError

from shared.batch_protocol import (
    BatchChatItemResult,
    BatchChatRequest,
    build_batch_id,
    build_review_tag,
)


def _sample_request_payload(request_id: str = "req-1", image_id: int = 12) -> dict:
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


def test_batch_request_rejects_duplicate_candidate_ids() -> None:
    payload = {
        "items": [
            {"candidateId": "dup", "request": _sample_request_payload("req-1", 1)},
            {"candidateId": "dup", "request": _sample_request_payload("req-2", 2)},
        ]
    }

    with pytest.raises(ValidationError):
        BatchChatRequest.model_validate(payload)


def test_build_batch_id_and_review_tag_generate_defaults() -> None:
    batch_id = build_batch_id(None)
    review_tag = build_review_tag(batch_id, None)

    assert batch_id.startswith("batch-")
    assert review_tag.startswith("darktable|agent-batch|")


def test_batch_request_rejects_live_refinement_items() -> None:
    payload = {
        "items": [
            {
                "candidateId": "candidate-1",
                "request": {
                    **_sample_request_payload("req-1", 1),
                    "refinement": {
                        "mode": "multi-turn",
                        "enabled": True,
                        "maxPasses": 3,
                        "passIndex": 1,
                        "goalText": "Make it brighter",
                    },
                },
            }
        ]
    }

    with pytest.raises(ValidationError):
        BatchChatRequest.model_validate(payload)


def test_batch_item_result_validates_skipped_state_shape() -> None:
    with pytest.raises(ValidationError):
        BatchChatItemResult.model_validate(
            {
                "candidateId": "candidate-1",
                "requestId": "req-1",
                "imageSessionId": "img-1",
                "imageId": 1,
                "imageName": "IMG_1.CR3",
                "selected": False,
                "selectionRank": None,
                "reviewTag": "darktable|agent-batch|foo",
                "status": "skipped",
                "response": None,
                "error": None,
                "skipReason": None,
            }
        )


def test_review_metadata_rejects_duplicate_tags() -> None:
    payload = {
        "assistantText": "Edit image",
        "continueRefining": False,
        "review": {
            "decision": "review",
            "summary": "Needs eyes-on review.",
            "tags": ["portrait", "Portrait"],
        },
        "operations": [],
    }

    from shared.protocol import AgentPlan

    with pytest.raises(ValidationError):
        AgentPlan.model_validate(payload)
