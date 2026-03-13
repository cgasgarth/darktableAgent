import pytest
from httpx import ASGITransport, AsyncClient

from server.app import app


def _sample_image_state() -> dict:
    return {
        "currentExposure": 2.8,
        "historyPosition": 1,
        "historyCount": 1,
        "metadata": {
            "imageId": 12,
            "imageName": "_DSC8809.ARW",
            "cameraMaker": "Sony",
            "cameraModel": "ILCE-7RM5",
            "width": 9504,
            "height": 6336,
            "exifExposureSeconds": 0.01,
            "exifAperture": 4.0,
            "exifIso": 100.0,
            "exifFocalLength": 35.0,
        },
        "controls": [
            {
                "capabilityId": "exposure.primary",
                "label": "Exposure",
                "actionPath": "iop/exposure/exposure",
                "currentNumber": 2.8,
            }
        ],
        "history": [
            {
                "num": 0,
                "module": "exposure",
                "enabled": True,
                "multiPriority": 0,
                "instanceName": "exposure",
                "iopOrder": 20,
            }
        ],
    }


@pytest.fixture
async def api_client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client


@pytest.mark.anyio
async def test_chat_defaults_to_exposure_mock_response(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/v1/chat",
        json={
            "schemaVersion": "2.0",
            "requestId": "req-default",
            "conversationId": "conv-default",
            "message": {"role": "user", "text": "Hello agent"},
            "uiContext": {"view": "darkroom", "imageId": None, "imageName": None},
            "imageState": _sample_image_state(),
            "mockResponseId": None,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["message"]["text"].startswith("Mock agent: increasing the current image exposure")
    assert body["operations"] == [
        {
            "operationId": "op-exposure-plus-0.7",
            "kind": "set-float",
            "status": "planned",
            "target": {
                "type": "darktable-action",
                "actionPath": "iop/exposure/exposure",
            },
            "value": {"mode": "delta", "number": 0.7},
        }
    ]


@pytest.mark.anyio
async def test_chat_ack_response_is_operation_free(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/v1/chat",
        json={
            "schemaVersion": "2.0",
            "requestId": "req-chat-ack",
            "conversationId": "conv-chat-ack",
            "message": {"role": "user", "text": "Ping"},
            "uiContext": {"view": "darkroom", "imageId": 7, "imageName": "img.jpg"},
            "imageState": _sample_image_state(),
            "mockResponseId": "chat-echo",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["operations"] == []
    assert body["message"]["text"].startswith("Echo: Ping")


@pytest.mark.anyio
async def test_chat_exposure_minus_mock_response(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/v1/chat",
        json={
            "schemaVersion": "2.0",
            "requestId": "req-darken",
            "conversationId": "conv-darken",
            "message": {"role": "user", "text": "Darken it"},
            "uiContext": {"view": "darkroom", "imageId": 8, "imageName": "img.jpg"},
            "imageState": _sample_image_state(),
            "mockResponseId": "exposure-minus-0.7",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["operations"][0]["value"] == {"mode": "delta", "number": -0.7}


@pytest.mark.anyio
async def test_chat_preserves_multi_operation_order(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/v1/chat",
        json={
            "schemaVersion": "2.0",
            "requestId": "req-sequence",
            "conversationId": "conv-sequence",
            "message": {"role": "user", "text": "Do the sequence"},
            "uiContext": {"view": "darkroom", "imageId": 9, "imageName": "img.jpg"},
            "imageState": _sample_image_state(),
            "mockResponseId": "exposure-sequence-plus-0.7",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert [operation["operationId"] for operation in body["operations"]] == [
        "op-exposure-plus-0.2",
        "op-exposure-plus-0.5",
    ]
    assert [operation["value"]["number"] for operation in body["operations"]] == [0.2, 0.5]


@pytest.mark.anyio
async def test_chat_supports_blocked_operation_fixture(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/v1/chat",
        json={
            "schemaVersion": "2.0",
            "requestId": "req-unsupported",
            "conversationId": "conv-unsupported",
            "message": {"role": "user", "text": "Try something unsupported"},
            "uiContext": {"view": "darkroom", "imageId": 10, "imageName": "img.jpg"},
            "imageState": _sample_image_state(),
            "mockResponseId": "unsupported-action",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["operations"] == [
        {
            "operationId": "op-unsupported-action",
            "kind": "set-float",
            "status": "planned",
            "target": {
                "type": "darktable-action",
                "actionPath": "iop/exposure/not-real",
            },
            "value": {"mode": "delta", "number": 0.7},
        }
    ]


@pytest.mark.anyio
async def test_chat_rejects_malformed_payload(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/v1/chat",
        json={
            "schemaVersion": "2.0",
            "requestId": "req-bad",
            "conversationId": "conv-bad",
            "message": {"role": "assistant", "text": "nope"},
            "uiContext": {"view": "darkroom", "imageId": None, "imageName": None},
            "imageState": _sample_image_state(),
            "mockResponseId": None,
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "error"
    assert body["requestId"] == "req-bad"
    assert body["conversationId"] == "conv-bad"
    assert body["operations"] == []
    assert body["error"]["code"] == "invalid_request"


@pytest.mark.anyio
async def test_chat_rejects_missing_image_state(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/v1/chat",
        json={
            "schemaVersion": "2.0",
            "requestId": "req-missing-state",
            "conversationId": "conv-missing-state",
            "message": {"role": "user", "text": "Ping"},
            "uiContext": {"view": "darkroom", "imageId": 7, "imageName": "img.jpg"},
            "mockResponseId": "chat-echo",
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "invalid_request"
    assert "imageState" in body["error"]["message"]
