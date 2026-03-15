from dataclasses import dataclass

import pytest
from httpx import ASGITransport, AsyncClient

from server.app import app
from server.codex_app_server import CodexAppServerError
from shared.protocol import AgentPlan


def _sample_capabilities() -> list[dict]:
    return [
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
        },
        {
            "moduleId": "filmicrgb",
            "moduleLabel": "filmic rgb",
            "capabilityId": "filmic.preserve-highlights",
            "label": "Preserve highlights",
            "kind": "set-bool",
            "targetType": "darktable-action",
            "actionPath": "iop/filmicrgb/preserve_highlights",
            "supportedModes": ["set"],
            "defaultBool": False,
        },
        {
            "moduleId": "colorbalancergb",
            "moduleLabel": "color balance rgb",
            "capabilityId": "colorbalancergb.saturation-formula",
            "label": "Saturation formula",
            "kind": "set-choice",
            "targetType": "darktable-action",
            "actionPath": "iop/colorbalancergb/saturation_formula",
            "supportedModes": ["set"],
            "choices": [
                {"choiceValue": 0, "choiceId": "jzazbz", "label": "JzAzBz"},
                {"choiceValue": 1, "choiceId": "rgb", "label": "RGB"},
            ],
            "defaultChoiceValue": 0,
        },
        {
            "moduleId": "colorequal",
            "moduleLabel": "color equalizer",
            "capabilityId": "colorequal.sat-blue",
            "label": "Blue saturation",
            "kind": "set-float",
            "targetType": "darktable-action",
            "actionPath": "iop/colorequal/sat_blue",
            "supportedModes": ["set", "delta"],
            "minNumber": -1.0,
            "maxNumber": 1.0,
            "defaultNumber": 0.0,
            "stepNumber": 0.01,
        }
    ]


def _sample_image_snapshot() -> dict:
    return {
        "imageRevisionId": "image-12-history-1",
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
                "currentNumber": 2.8,
                "supportedModes": ["set", "delta"],
                "minNumber": -18.0,
                "maxNumber": 18.0,
                "defaultNumber": 0.0,
                "stepNumber": 0.01,
            },
            {
                "moduleId": "filmicrgb",
                "moduleLabel": "filmic rgb",
                "settingId": "setting.filmic.preserve-highlights",
                "capabilityId": "filmic.preserve-highlights",
                "label": "Preserve highlights",
                "actionPath": "iop/filmicrgb/preserve_highlights",
                "kind": "set-bool",
                "supportedModes": ["set"],
                "currentBool": True,
                "defaultBool": False,
            },
            {
                "moduleId": "colorbalancergb",
                "moduleLabel": "color balance rgb",
                "settingId": "setting.colorbalancergb.saturation-formula",
                "capabilityId": "colorbalancergb.saturation-formula",
                "label": "Saturation formula",
                "actionPath": "iop/colorbalancergb/saturation_formula",
                "kind": "set-choice",
                "supportedModes": ["set"],
                "currentChoiceValue": 1,
                "currentChoiceId": "rgb",
                "choices": [
                    {"choiceValue": 0, "choiceId": "jzazbz", "label": "JzAzBz"},
                    {"choiceValue": 1, "choiceId": "rgb", "label": "RGB"},
                ],
                "defaultChoiceValue": 0,
            },
            {
                "moduleId": "colorequal",
                "moduleLabel": "color equalizer",
                "settingId": "setting.colorequal.sat-blue",
                "capabilityId": "colorequal.sat-blue",
                "label": "Blue saturation",
                "actionPath": "iop/colorequal/sat_blue",
                "kind": "set-float",
                "currentNumber": 0.15,
                "supportedModes": ["set", "delta"],
                "minNumber": -1.0,
                "maxNumber": 1.0,
                "defaultNumber": 0.0,
                "stepNumber": 0.01,
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
        "preview": None,
        "histogram": None,
    }


def _sample_request_payload() -> dict:
    return {
        "schemaVersion": "3.0",
        "requestId": "req-1",
        "session": {
            "appSessionId": "app-1",
            "imageSessionId": "img-12",
            "conversationId": "conv-1",
            "turnId": "turn-1",
        },
        "message": {"role": "user", "text": "Make it brighter"},
        "refinement": {
            "mode": "single-turn",
            "enabled": False,
            "maxPasses": 1,
            "passIndex": 1,
            "automaticContinuation": False,
            "goalText": "Make it brighter",
        },
        "uiContext": {"view": "darkroom", "imageId": 12, "imageName": "_DSC8809.ARW"},
        "capabilityManifest": {
            "manifestVersion": "manifest-1",
            "targets": _sample_capabilities(),
        },
        "imageSnapshot": _sample_image_snapshot(),
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
        self.cancel_requests = []

    def plan(self, request):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result

    def cancel_request(  # type: ignore[no-untyped-def]
        self,
        *,
        request_id,
        app_session_id,
        image_session_id,
        conversation_id,
        turn_id,
    ):
        self.cancel_requests.append(
            {
                "request_id": request_id,
                "app_session_id": app_session_id,
                "image_session_id": image_session_id,
                "conversation_id": conversation_id,
                "turn_id": turn_id,
            }
        )
        return True


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
                    "continueRefining": False,
                    "operations": [
                        {
                            "operationId": "op-exposure-plus-0.7",
                            "sequence": 1,
                            "kind": "set-float",
                            "target": {
                                "type": "darktable-action",
                                "actionPath": "iop/exposure/exposure",
                                "settingId": "setting.exposure.primary",
                            },
                            "value": {"mode": "delta", "number": 0.7},
                            "reason": None,
                            "constraints": {
                                "onOutOfRange": "clamp",
                                "onRevisionMismatch": "fail",
                            },
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
    assert body["assistantMessage"]["text"] == "Increasing exposure by +0.7 EV."
    assert body["refinement"] == {
        "mode": "single-turn",
        "enabled": False,
        "passIndex": 1,
        "maxPasses": 1,
        "continueRefining": False,
        "stopReason": "single-turn",
    }
    assert body["plan"]["operations"] == [
        {
            "operationId": "op-exposure-plus-0.7",
            "sequence": 1,
            "kind": "set-float",
            "target": {
                "type": "darktable-action",
                "actionPath": "iop/exposure/exposure",
                "settingId": "setting.exposure.primary",
            },
            "value": {
                "mode": "delta",
                "number": 0.7,
                "choiceValue": None,
                "choiceId": None,
                "boolValue": None,
            },
            "reason": None,
            "constraints": {
                "onOutOfRange": "clamp",
                "onRevisionMismatch": "fail",
            },
        }
    ]
    assert body["operationResults"] == [{"operationId": "op-exposure-plus-0.7", "status": "planned", "error": None}]
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
                    "continueRefining": False,
                    "operations": [
                        {
                            "operationId": "op-exposure-plus-0.2",
                            "sequence": 1,
                            "kind": "set-float",
                            "target": {
                                "type": "darktable-action",
                                "actionPath": "iop/exposure/exposure",
                                "settingId": "setting.exposure.primary",
                            },
                            "value": {"mode": "delta", "number": 0.2},
                            "reason": None,
                            "constraints": {
                                "onOutOfRange": "clamp",
                                "onRevisionMismatch": "fail",
                            },
                        },
                        {
                            "operationId": "op-exposure-plus-0.5",
                            "sequence": 2,
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
    assert [operation["operationId"] for operation in body["plan"]["operations"]] == [
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
                    "continueRefining": False,
                    "operations": [],
                }
            )
        )
    )
    monkeypatch.setattr("server.app.get_codex_bridge", lambda: bridge)

    response = await api_client.post("/v1/chat", json=_sample_request_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["plan"]["operations"] == []
    assert body["assistantMessage"]["text"] == "I need a more specific edit instruction."
    assert body["refinement"]["continueRefining"] is False
    assert body["refinement"]["stopReason"] == "single-turn"


@pytest.mark.anyio
async def test_chat_returns_multi_turn_refinement_status(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = StubBridge(
        result=StubTurnResult(
            plan=AgentPlan.model_validate(
                {
                    "assistantText": "Lifting exposure first, then I want another look.",
                    "continueRefining": True,
                    "operations": [
                        {
                            "operationId": "op-exposure-plus-0.4",
                            "sequence": 1,
                            "kind": "set-float",
                            "target": {
                                "type": "darktable-action",
                                "actionPath": "iop/exposure/exposure",
                                "settingId": "setting.exposure.primary",
                            },
                            "value": {"mode": "delta", "number": 0.4},
                            "reason": None,
                            "constraints": {
                                "onOutOfRange": "clamp",
                                "onRevisionMismatch": "fail",
                            },
                        }
                    ],
                }
            )
        )
    )
    monkeypatch.setattr("server.app.get_codex_bridge", lambda: bridge)

    payload = _sample_request_payload()
    payload["message"]["text"] = "Do a full edit"
    payload["refinement"] = {
        "mode": "multi-turn",
        "enabled": True,
        "maxPasses": 10,
        "passIndex": 1,
        "automaticContinuation": False,
        "goalText": "Do a full edit",
    }

    response = await api_client.post("/v1/chat", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["refinement"] == {
        "mode": "multi-turn",
        "enabled": True,
        "passIndex": 1,
        "maxPasses": 10,
        "continueRefining": True,
        "stopReason": "continue",
    }


@pytest.mark.anyio
async def test_chat_can_use_mock_planner_backend(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DARKTABLE_AGENT_USE_MOCK_RESPONSES", "1")

    response = await api_client.post("/v1/chat", json=_sample_request_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["assistantMessage"]["text"] == "Mock single-turn edit: applying +0.70 EV."
    assert body["plan"]["operations"][0]["value"]["number"] == 0.7
    assert body["refinement"]["continueRefining"] is False


@pytest.mark.anyio
async def test_cancel_chat_forwards_request_ids_to_bridge(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = StubBridge()
    monkeypatch.setattr("server.app.get_codex_bridge", lambda: bridge)

    response = await api_client.post(
        "/v1/chat/cancel",
        json={
            "requestId": "req-1",
            "session": {
                "appSessionId": "app-1",
                "imageSessionId": "img-12",
                "conversationId": "conv-1",
                "turnId": "turn-1",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "requestId": "req-1",
        "canceled": True,
        "message": "Cancellation requested for the active chat turn",
    }
    assert bridge.cancel_requests == [
        {
            "request_id": "req-1",
            "app_session_id": "app-1",
            "image_session_id": "img-12",
            "conversation_id": "conv-1",
            "turn_id": "turn-1",
        }
    ]


@pytest.mark.anyio
async def test_cancel_chat_accepts_unknown_request_ids(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = StubBridge()
    monkeypatch.setattr("server.app.get_codex_bridge", lambda: bridge)
    bridge.cancel_request = lambda **_: False  # type: ignore[method-assign]

    response = await api_client.post(
        "/v1/chat/cancel",
        json={
            "requestId": "req-missing",
            "session": {
                "appSessionId": "app-1",
                "imageSessionId": "img-12",
                "conversationId": "conv-1",
                "turnId": "turn-1",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "requestId": "req-missing",
        "canceled": True,
        "message": "Cancellation recorded for this chat turn",
    }


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
    assert body["refinement"]["continueRefining"] is False


@pytest.mark.anyio
async def test_chat_rejects_malformed_payload(api_client: AsyncClient) -> None:
    payload = _sample_request_payload()
    payload["message"]["role"] = "assistant"

    response = await api_client.post("/v1/chat", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "error"
    assert body["operationResults"] == []
    assert "message/role" in body["error"]["message"]


@pytest.mark.anyio
async def test_chat_rejects_invalid_single_turn_refinement_shape(
    api_client: AsyncClient,
) -> None:
    payload = _sample_request_payload()
    payload["refinement"]["maxPasses"] = 3

    response = await api_client.post("/v1/chat", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "error"
    assert "single-turn refinement must use maxPasses=1" in body["error"]["message"]


@pytest.mark.anyio
async def test_chat_rejects_missing_image_snapshot(api_client: AsyncClient) -> None:
    payload = _sample_request_payload()
    payload.pop("imageSnapshot")

    response = await api_client.post("/v1/chat", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "error"
    assert "imageSnapshot" in body["error"]["message"]


@pytest.mark.anyio
async def test_chat_rejects_missing_capability_manifest(api_client: AsyncClient) -> None:
    payload = _sample_request_payload()
    payload.pop("capabilityManifest")

    response = await api_client.post("/v1/chat", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "error"
    assert "capabilityManifest" in body["error"]["message"]


@pytest.mark.anyio
async def test_chat_rejects_setting_capability_mismatch(api_client: AsyncClient) -> None:
    payload = _sample_request_payload()
    payload["imageSnapshot"]["editableSettings"][0]["capabilityId"] = "unknown.capability"

    response = await api_client.post("/v1/chat", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "error"
    assert "unknown capabilityId" in body["error"]["message"]
