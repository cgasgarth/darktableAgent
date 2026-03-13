import pytest
from httpx import ASGITransport, AsyncClient

from server.app import app


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
            "mockResponseId": "exposure-minus-0.7",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["operations"][0]["value"] == {"mode": "delta", "number": -0.7}


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
