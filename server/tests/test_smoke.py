import base64
import threading

import pytest

from server.codex_app_server import (
    CodexAppServerBridge,
    _TOOL_APPLY_OPERATIONS,
    _TOOL_GET_IMAGE_STATE,
    _TOOL_GET_PREVIEW_IMAGE,
)
from shared.protocol import RequestEnvelope


def _sample_request(*, live_run: bool = True) -> RequestEnvelope:
    return RequestEnvelope.model_validate(
        {
            "schemaVersion": "3.0",
            "requestId": "req-smoke-1",
            "session": {
                "appSessionId": "app-1",
                "imageSessionId": "img-12",
                "conversationId": "conv-1",
                "turnId": "turn-1",
            },
            "message": {"role": "user", "text": "Brighten the image"},
            "fast": False,
            "refinement": {
                "mode": "multi-turn" if live_run else "single-turn",
                "enabled": live_run,
                "maxPasses": 5 if live_run else 1,
                "passIndex": 1,
                "goalText": "Brighten the image",
            },
            "uiContext": {
                "view": "darkroom",
                "imageId": 12,
                "imageName": "_DSC8809.ARW",
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
                    },
                ],
            },
            "imageSnapshot": {
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
                        "currentNumber": 0.0,
                        "supportedModes": ["set", "delta"],
                        "minNumber": -18.0,
                        "maxNumber": 18.0,
                        "defaultNumber": 0.0,
                        "stepNumber": 0.01,
                    },
                ],
                "history": [],
                "preview": {
                    "previewId": "preview-1",
                    "mimeType": "image/jpeg",
                    "width": 100,
                    "height": 67,
                    "base64Data": base64.b64encode(b"initial-preview").decode(),
                },
                "histogram": None,
            },
        }
    )


def _init_bridge_with_context(
    request: RequestEnvelope,
) -> tuple[CodexAppServerBridge, list[dict]]:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    sent: list[dict] = []
    bridge._send_json_locked = lambda payload: sent.append(payload)  # type: ignore[method-assign,attr-defined]
    bridge._register_request(request)  # type: ignore[attr-defined]
    preview_url = bridge._preview_data_url(request)  # type: ignore[attr-defined]
    bridge._register_turn_context("thread-1", "turn-1", request, preview_url)  # type: ignore[attr-defined]
    active = bridge._active_requests.get(request.requestId)  # type: ignore[attr-defined]
    if active:
        active.thread_id = "thread-1"
        active.codex_turn_id = "turn-1"
    return bridge, sent


def _apply_exposure_tool_call(
    bridge: CodexAppServerBridge,
    *,
    call_id: str = "call-1",
    request_id: int = 10,
    delta: float = 0.5,
) -> None:
    bridge._handle_server_request_locked(  # type: ignore[attr-defined]
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "item/tool/call",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "callId": call_id,
                "tool": _TOOL_APPLY_OPERATIONS,
                "arguments": {
                    "operations": [
                        {
                            "kind": "set-float",
                            "target": {
                                "type": "darktable-action",
                                "actionPath": "iop/exposure/exposure",
                                "settingId": "setting.exposure.primary",
                            },
                            "value": {"mode": "delta", "number": delta},
                        }
                    ]
                },
            },
        }
    )


def test_mid_turn_render_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """apply_operations -> render callback arrives -> preview updated in response."""
    request = _sample_request(live_run=True)
    bridge, sent = _init_bridge_with_context(request)
    context = bridge._get_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]
    assert context is not None

    rendered_jpeg = b"\xff\xd8\xff\xe0RENDERED"

    def _mock_wait(timeout=None):
        context.rendered_preview_bytes = rendered_jpeg
        return True

    monkeypatch.setattr(context.render_event, "wait", _mock_wait)
    _apply_exposure_tool_call(bridge)

    result = sent[0]["result"]
    assert result["success"] is True
    assert len(result["contentItems"]) == 2
    assert result["contentItems"][0]["type"] == "inputText"
    assert "Applied 1 operations" in result["contentItems"][0]["text"]
    assert result["contentItems"][1]["type"] == "inputImage"
    preview_url = result["contentItems"][1]["imageUrl"]
    assert "x-darktable-stage=1" in preview_url
    encoded_rendered = base64.b64encode(rendered_jpeg).decode()
    assert preview_url.endswith(f";base64,{encoded_rendered}")

    assert context.preview_data_url == preview_url
    assert context.rendered_preview_bytes is None
    assert context.requires_render_callback is False


def test_mid_turn_render_timeout_warns_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the C++ side doesn't deliver, the agent gets a warning text."""
    request = _sample_request(live_run=True)
    bridge, sent = _init_bridge_with_context(request)
    context = bridge._get_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]
    assert context is not None

    monkeypatch.setattr(context.render_event, "wait", lambda timeout=None: False)
    _apply_exposure_tool_call(bridge)

    result = sent[0]["result"]
    assert result["success"] is True
    assert len(result["contentItems"]) == 2
    assert result["contentItems"][1]["type"] == "inputText"
    assert "timed out" in result["contentItems"][1]["text"].lower()
    assert context.requires_render_callback is False


def test_provide_render_callback_sets_bytes_and_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """provide_render_callback writes bytes under lock and signals the event."""
    request = _sample_request(live_run=True)
    bridge, _ = _init_bridge_with_context(request)
    context = bridge._get_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]
    assert context is not None

    jpeg_bytes = b"\xff\xd8\xff\xe0CALLBACK"
    success = bridge.provide_render_callback(
        image_session_id="img-12",
        turn_id="turn-1",
        image_bytes=jpeg_bytes,
    )
    assert success is True
    assert context.rendered_preview_bytes == jpeg_bytes
    assert context.render_event.is_set()


def test_provide_render_callback_returns_false_for_unknown_session() -> None:
    """Callback returns False when no matching context exists."""
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    bridge._send_json_locked = lambda _: None  # type: ignore[method-assign,attr-defined]

    success = bridge.provide_render_callback(
        image_session_id="nonexistent",
        turn_id="nonexistent",
        image_bytes=b"data",
    )
    assert success is False


def test_progress_reports_requires_render_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_request_progress reflects requires_render_callback from context."""
    request = _sample_request(live_run=True)
    bridge, _ = _init_bridge_with_context(request)
    context = bridge._get_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]
    assert context is not None

    progress_before = bridge.get_request_progress(
        request_id="req-smoke-1",
        app_session_id="app-1",
        image_session_id="img-12",
        conversation_id="conv-1",
        turn_id="turn-1",
    )
    assert progress_before["requiresRenderCallback"] is False

    context.requires_render_callback = True
    progress_during = bridge.get_request_progress(
        request_id="req-smoke-1",
        app_session_id="app-1",
        image_session_id="img-12",
        conversation_id="conv-1",
        turn_id="turn-1",
    )
    assert progress_during["requiresRenderCallback"] is True


def test_read_only_tools_do_not_trigger_render() -> None:
    """get_image_state and get_preview_image must not set requires_render_callback."""
    request = _sample_request(live_run=True)
    bridge, sent = _init_bridge_with_context(request)

    for tool_name in (_TOOL_GET_IMAGE_STATE, _TOOL_GET_PREVIEW_IMAGE):
        sent.clear()
        bridge._handle_server_request_locked(  # type: ignore[attr-defined]
            {
                "jsonrpc": "2.0",
                "id": 99,
                "method": "item/tool/call",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "callId": f"call-{tool_name}",
                    "tool": tool_name,
                    "arguments": {},
                },
            }
        )
        result = sent[0]["result"]
        assert result["success"] is True

    context = bridge._get_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]
    assert context is not None
    assert context.requires_render_callback is False


def test_sequential_applies_update_preview_each_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two sequential apply_operations each produce distinct previews."""
    request = _sample_request(live_run=True)
    bridge, sent = _init_bridge_with_context(request)
    context = bridge._get_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]
    assert context is not None

    jpeg_1 = b"rendered-after-first-apply"

    def _mock_wait_1(timeout=None):
        context.rendered_preview_bytes = jpeg_1
        return True

    monkeypatch.setattr(context.render_event, "wait", _mock_wait_1)
    _apply_exposure_tool_call(bridge, call_id="call-1", request_id=10, delta=0.3)
    preview_1 = sent[0]["result"]["contentItems"][1]["imageUrl"]
    assert "x-darktable-stage=1" in preview_1

    sent.clear()
    jpeg_2 = b"rendered-after-second-apply"

    def _mock_wait_2(timeout=None):
        context.rendered_preview_bytes = jpeg_2
        return True

    monkeypatch.setattr(context.render_event, "wait", _mock_wait_2)
    _apply_exposure_tool_call(bridge, call_id="call-2", request_id=11, delta=0.2)
    preview_2 = sent[0]["result"]["contentItems"][1]["imageUrl"]
    assert "x-darktable-stage=2" in preview_2
    assert preview_1 != preview_2
