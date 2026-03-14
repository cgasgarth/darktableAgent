from dataclasses import dataclass

import pytest
from httpx import ASGITransport, AsyncClient

from server.app import app
from server.codex_app_server import CodexAppServerError
from shared.protocol import AgentPlan


def _sample_capabilities() -> list[dict]:
    return [
        {
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
    ]


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


def _sample_request_payload() -> dict:
    return {
        "schemaVersion": "2.0",
        "requestId": "req-1",
        "conversationId": "conv-1",
        "message": {"role": "user", "text": "Make it brighter"},
        "uiContext": {"view": "darkroom", "imageId": 12, "imageName": "_DSC8809.ARW"},
        "capabilities": _sample_capabilities(),
        "imageState": _sample_image_state(),
    }


@dataclass
class StubTurnResult:
    plan: AgentPlan
    thread_id: str = "thread-1"
    turn_id: str = "turn-1"
    raw_message: str = ""


class StubBridge:
    def __init__(self, result: StubTurnResult | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.requests = []

    def plan(self, request):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


@pytest.fixture
async def api_client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client


@pytest.mark.anyio
async def test_chat_returns_codex_plan_response(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = StubBridge(
        result=StubTurnResult(
            plan=AgentPlan.model_validate(
                {
                    "assistantText": "Increasing exposure by +0.7 EV.",
                    "operations": [
                        {
                            "operationId": "op-exposure-plus-0.7",
                            "kind": "set-float",
                            "target": {
                                "type": "darktable-action",
                                "actionPath": "iop/exposure/exposure",
                            },
                            "value": {"mode": "delta", "number": 0.7},
                        }
                    ],
                }
            )
        )
    )
    monkeypatch.setattr("server.app.get_codex_bridge", lambda: bridge)

    response = await api_client.post("/v1/chat", json=_sample_request_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["message"]["text"] == "Increasing exposure by +0.7 EV."
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
    assert bridge.requests[0].message.text == "Make it brighter"


@pytest.mark.anyio
async def test_chat_preserves_multi_operation_order(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = StubBridge(
        result=StubTurnResult(
            plan=AgentPlan.model_validate(
                {
                    "assistantText": "Applying two steps.",
                    "operations": [
                        {
                            "operationId": "op-exposure-plus-0.2",
                            "kind": "set-float",
                            "target": {
                                "type": "darktable-action",
                                "actionPath": "iop/exposure/exposure",
                            },
                            "value": {"mode": "delta", "number": 0.2},
                        },
                        {
                            "operationId": "op-exposure-plus-0.5",
                            "kind": "set-float",
                            "target": {
                                "type": "darktable-action",
                                "actionPath": "iop/exposure/exposure",
                            },
                            "value": {"mode": "delta", "number": 0.5},
                        },
                    ],
                }
            )
        )
    )
    monkeypatch.setattr("server.app.get_codex_bridge", lambda: bridge)

    response = await api_client.post("/v1/chat", json=_sample_request_payload())

    assert response.status_code == 200
    body = response.json()
    assert [operation["operationId"] for operation in body["operations"]] == [
        "op-exposure-plus-0.2",
        "op-exposure-plus-0.5",
    ]


@pytest.mark.anyio
async def test_chat_supports_operation_free_assistant_messages(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = StubBridge(
        result=StubTurnResult(
            plan=AgentPlan.model_validate(
                {
                    "assistantText": "I need a more specific edit instruction.",
                    "operations": [],
                }
            )
        )
    )
    monkeypatch.setattr("server.app.get_codex_bridge", lambda: bridge)

    response = await api_client.post("/v1/chat", json=_sample_request_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["operations"] == []
    assert body["message"]["text"] == "I need a more specific edit instruction."


@pytest.mark.anyio
async def test_chat_surfaces_codex_backend_errors(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = StubBridge(
        error=CodexAppServerError(
            "codex_timeout", "Codex app server timed out", status_code=504
        )
    )
    monkeypatch.setattr("server.app.get_codex_bridge", lambda: bridge)

    response = await api_client.post("/v1/chat", json=_sample_request_payload())

    assert response.status_code == 504
    body = response.json()
    assert body["status"] == "error"
    assert body["error"] == {
        "code": "codex_timeout",
        "message": "Codex app server timed out",
    }


@pytest.mark.anyio
async def test_chat_rejects_malformed_payload(api_client: AsyncClient) -> None:
    payload = _sample_request_payload()
    payload["message"]["role"] = "assistant"

    response = await api_client.post("/v1/chat", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "error"
    assert body["operations"] == []
    assert "message/role" in body["error"]["message"]


@pytest.mark.anyio
async def test_chat_rejects_missing_image_state(api_client: AsyncClient) -> None:
    payload = _sample_request_payload()
    payload.pop("imageState")

    response = await api_client.post("/v1/chat", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "error"
    assert "imageState" in body["error"]["message"]


@pytest.mark.anyio
async def test_chat_rejects_missing_capabilities(api_client: AsyncClient) -> None:
    payload = _sample_request_payload()
    payload.pop("capabilities")

    response = await api_client.post("/v1/chat", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "error"
    assert "capabilities" in body["error"]["message"]


@pytest.mark.anyio
async def test_chat_rejects_control_capability_mismatch(api_client: AsyncClient) -> None:
    payload = _sample_request_payload()
    payload["imageState"]["controls"][0]["capabilityId"] = "unknown.capability"

    response = await api_client.post("/v1/chat", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "error"
    assert "unknown capabilityId" in body["error"]["message"]
