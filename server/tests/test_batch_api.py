import pytest
from httpx import ASGITransport, AsyncClient

from server.app import app


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
        "message": {"role": "user", "text": "Increase exposure by exactly 0.7 EV."},
        "fast": False,
        "refinement": {
            "mode": "single-turn",
            "enabled": False,
            "maxPasses": 1,
            "passIndex": 1,
            "goalText": "Increase exposure by exactly 0.7 EV.",
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


@pytest.mark.anyio
async def test_batch_chat_returns_review_tag_and_skips_over_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DARKTABLE_AGENT_USE_MOCK_RESPONSES", "1")
    payload = {
        "selection": {"maxImages": 10},
        "items": [
            {
                "candidateId": f"candidate-{index}",
                "request": _sample_request_payload(f"req-{index}", index),
            }
            for index in range(1, 13)
        ],
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/v1/batch/chat", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["selectedCount"] == 10
    assert body["skippedCount"] == 2
    assert body["reviewTag"].startswith("darktable|agent-batch|")
    assert body["results"][0]["status"] == "ok"
    assert body["results"][0]["response"]["assistantMessage"]["text"].startswith(
        "Mock single-turn edit"
    )
    assert body["results"][10]["status"] == "skipped"
    assert body["results"][10]["skipReason"] == "batch-limit"


@pytest.mark.anyio
async def test_batch_chat_rejects_more_than_ten_selected_images_in_config() -> None:
    payload = {
        "selection": {"maxImages": 11},
        "items": [
            {
                "candidateId": "candidate-1",
                "request": _sample_request_payload("req-1", 1),
            }
        ],
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/v1/batch/chat", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "invalid_request"
    assert "selection/maxImages" in body["error"]["message"]


@pytest.mark.anyio
async def test_batch_chat_rejects_live_refinement_requests() -> None:
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
                        "goalText": "Increase exposure by exactly 0.7 EV.",
                    },
                },
            }
        ]
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/v1/batch/chat", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "invalid_request"
    assert "single-turn refinement only" in body["error"]["message"]


@pytest.mark.anyio
async def test_chat_batch_uses_shared_message_and_returns_review_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DARKTABLE_AGENT_USE_MOCK_RESPONSES", "1")
    payload = {
        "schemaVersion": "3.0",
        "requestId": "batch-1",
        "message": {"role": "user", "text": "Increase exposure by exactly 0.7 EV."},
        "fast": False,
        "refinement": {
            "mode": "single-turn",
            "enabled": False,
            "maxPasses": 1,
            "passIndex": 1,
            "goalText": "Increase exposure by exactly 0.7 EV.",
        },
        "items": [
            {
                "batchItemId": "item-1",
                "session": {
                    "appSessionId": "app-1",
                    "imageSessionId": "img-1",
                    "conversationId": "conv-1",
                    "turnId": "turn-1",
                },
                "uiContext": {
                    "view": "darkroom",
                    "imageId": 1,
                    "imageName": "IMG_1.CR3",
                },
                "capabilityManifest": _sample_request_payload("req-1", 1)[
                    "capabilityManifest"
                ],
                "imageSnapshot": _sample_request_payload("req-1", 1)["imageSnapshot"],
            },
            {
                "batchItemId": "item-2",
                "session": {
                    "appSessionId": "app-1",
                    "imageSessionId": "img-2",
                    "conversationId": "conv-2",
                    "turnId": "turn-2",
                },
                "uiContext": {
                    "view": "darkroom",
                    "imageId": 2,
                    "imageName": "IMG_2.CR3",
                },
                "capabilityManifest": _sample_request_payload("req-2", 2)[
                    "capabilityManifest"
                ],
                "imageSnapshot": _sample_request_payload("req-2", 2)["imageSnapshot"],
            },
        ],
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/v1/chat/batch", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["itemCount"] == 2
    assert body["reviewTag"].startswith("darktable|agent-batch|")
    assert body["items"][0]["batchItemId"] == "item-1"
    assert body["items"][0]["review"]["decision"] == "apply"
    assert body["items"][0]["session"]["imageSessionId"] == "img-1"
