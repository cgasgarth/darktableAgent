from fastapi.testclient import TestClient

from server.app import app

client = TestClient(app)


def test_chat_echo_response() -> None:
    response = client.post(
        "/v1/chat",
        json={
            "schemaVersion": "1.0",
            "requestId": "req-echo",
            "conversationId": "conv-echo",
            "message": {"role": "user", "text": "Hello agent"},
            "uiContext": {"view": "darkroom", "imageId": None, "imageName": None},
            "mockActionId": None,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["actions"] == []
    assert body["message"]["text"].startswith("Echo: Hello agent")


def test_chat_brighten_mock_action() -> None:
    response = client.post(
        "/v1/chat",
        json={
            "schemaVersion": "1.0",
            "requestId": "req-brighten",
            "conversationId": "conv-brighten",
            "message": {"role": "user", "text": "Brighten it"},
            "uiContext": {"view": "darkroom", "imageId": 7, "imageName": "img.jpg"},
            "mockActionId": "brighten-exposure",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["message"]["role"] == "assistant"
    assert body["actions"] == [
        {
            "actionId": "adjust-exposure-brighten",
            "type": "adjust-exposure",
            "status": "planned",
            "parameters": {"deltaEv": 0.7},
        }
    ]
    assert body["requestId"] == "req-brighten"
    assert body["conversationId"] == "conv-brighten"


def test_chat_darken_mock_action() -> None:
    response = client.post(
        "/v1/chat",
        json={
            "schemaVersion": "1.0",
            "requestId": "req-darken",
            "conversationId": "conv-darken",
            "message": {"role": "user", "text": "Darken it"},
            "uiContext": {"view": "darkroom", "imageId": 8, "imageName": "img.jpg"},
            "mockActionId": "darken-exposure",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["requestId"] == "req-darken"
    assert body["conversationId"] == "conv-darken"
    assert body["actions"] == [
        {
            "actionId": "adjust-exposure-darken",
            "type": "adjust-exposure",
            "status": "planned",
            "parameters": {"deltaEv": -0.7},
        }
    ]


def test_chat_rejects_malformed_payload() -> None:
    response = client.post(
        "/v1/chat",
        json={
            "schemaVersion": "1.0",
            "requestId": "req-bad",
            "conversationId": "conv-bad",
            "message": {"role": "assistant", "text": "nope"},
            "uiContext": {"view": "darkroom", "imageId": None, "imageName": None},
            "mockActionId": None,
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "error"
    assert body["requestId"] == "req-bad"
    assert body["conversationId"] == "conv-bad"
    assert body["actions"] == []
    assert body["error"]["code"] == "invalid_request"
