import pytest

from server.codex_app_server import (
    CodexAppServerBridge,
    CodexAppServerError,
    _DEFAULT_MODEL,
    _DEFAULT_REASONING_EFFORT,
    _FAST_MODE_MODEL,
    _FAST_MODE_REASONING_EFFORT,
    _THREAD_DEVELOPER_INSTRUCTIONS,
)
from shared.protocol import RequestEnvelope


def _sample_request() -> RequestEnvelope:
    return RequestEnvelope.model_validate(
        {
            "schemaVersion": "3.0",
            "requestId": "req-1",
            "session": {
                "appSessionId": "app-1",
                "imageSessionId": "img-12",
                "conversationId": "conv-1",
                "turnId": "turn-1",
            },
            "message": {
                "role": "user",
                "text": "Do a full edit so this becomes a polished gallery-ready landscape photo.",
            },
            "refinement": {
                "mode": "multi-turn",
                "enabled": True,
                "maxPasses": 10,
                "passIndex": 1,
                "fastMode": False,
                "automaticContinuation": False,
                "goalText": "Do a full edit so this becomes a polished gallery-ready landscape photo.",
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
                    },
                    {
                        "moduleId": "primaries",
                        "moduleLabel": "rgb primaries",
                        "capabilityId": "primaries.red-hue",
                        "label": "Red hue",
                        "kind": "set-float",
                        "targetType": "darktable-action",
                        "actionPath": "iop/primaries/red_hue",
                        "supportedModes": ["set", "delta"],
                        "minNumber": -3.141592653589793,
                        "maxNumber": 3.141592653589793,
                        "defaultNumber": 0.0,
                        "stepNumber": 0.001,
                    }
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
                    },
                    {
                        "moduleId": "primaries",
                        "moduleLabel": "rgb primaries",
                        "settingId": "setting.primaries.red-hue",
                        "capabilityId": "primaries.red-hue",
                        "label": "Red hue",
                        "actionPath": "iop/primaries/red_hue",
                        "kind": "set-float",
                        "currentNumber": 0.05,
                        "supportedModes": ["set", "delta"],
                        "minNumber": -3.141592653589793,
                        "maxNumber": 3.141592653589793,
                        "defaultNumber": 0.0,
                        "stepNumber": 0.001,
                    }
                ],
                "history": [],
                "preview": {
                    "previewId": "preview-1",
                    "mimeType": "image/jpeg",
                    "width": 1000,
                    "height": 667,
                    "base64Data": "ZmFrZS1wcmV2aWV3",
                },
                "histogram": {
                    "binCount": 4,
                    "channels": {
                        "luma": {"bins": [0, 20, 50, 30]},
                        "red": {"bins": [0, 10, 60, 30]},
                        "green": {"bins": [0, 20, 50, 30]},
                        "blue": {"bins": [0, 30, 40, 30]},
                    },
                },
            },
        }
    )


def test_default_command_disables_configured_mcp_servers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DARKTABLE_AGENT_CODEX_APP_SERVER_CMD", raising=False)

    bridge = CodexAppServerBridge()

    assert bridge._command == [
        "codex",
        "app-server",
        "-c",
        "mcp_servers.chrome-devtools.enabled=false",
        "--listen",
        "stdio://",
    ]


def test_environment_command_override_replaces_default_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DARKTABLE_AGENT_CODEX_APP_SERVER_CMD",
        "codex app-server --listen stdio://",
    )

    bridge = CodexAppServerBridge()

    assert bridge._command == ["codex", "app-server", "--listen", "stdio://"]


def test_extract_error_message_prefers_nested_json_message() -> None:
    message = '{"error":{"message":"The real error"}}'

    assert CodexAppServerBridge._extract_error_message(message) == "The real error"


def test_task_complete_marks_turn_complete() -> None:
    bridge = CodexAppServerBridge(command=["codex", "app-server", "--listen", "stdio://"])
    turn_state = {
        "thread_id": "thread-1",
        "turn_id": "turn-1",
        "chunks": [],
        "final_message": None,
        "turn_error": None,
        "completed": False,
    }

    bridge._handle_message_locked(  # type: ignore[attr-defined]
        {
            "method": "codex/event/task_complete",
            "params": {
                "id": "turn-1",
                "msg": {
                    "last_agent_message": '{"assistantText":"Done","continueRefining":false,"operations":[]}',
                },
            },
        },
        turn_state,
    )

    assert turn_state["final_message"] == '{"assistantText":"Done","continueRefining":false,"operations":[]}'
    assert turn_state["completed"] is True


def test_output_schema_marks_nullable_object_fields_as_required() -> None:
    schema = CodexAppServerBridge._build_output_schema()

    operation_value = schema["$defs"]["OperationValue"]

    assert operation_value["required"] == [
        "mode",
        "number",
        "choiceValue",
        "choiceId",
        "boolValue",
    ]


def test_model_selection_uses_default_model_when_fast_mode_disabled() -> None:
    request = _sample_request()

    assert CodexAppServerBridge._model_for_request(request) == _DEFAULT_MODEL


def test_model_selection_uses_fast_mode_model_when_fast_mode_enabled() -> None:
    request = _sample_request()
    request.refinement.fastMode = True

    assert CodexAppServerBridge._model_for_request(request) == _FAST_MODE_MODEL


def test_effort_selection_uses_default_effort_when_fast_mode_disabled() -> None:
    request = _sample_request()

    assert CodexAppServerBridge._effort_for_request(request) == _DEFAULT_REASONING_EFFORT


def test_effort_selection_uses_fast_mode_effort_when_fast_mode_enabled() -> None:
    request = _sample_request()
    request.refinement.fastMode = True

    assert CodexAppServerBridge._effort_for_request(request) == _FAST_MODE_REASONING_EFFORT


def test_developer_instructions_require_proactive_full_edit_planning() -> None:
    assert "Treat broad creative requests" in _THREAD_DEVELOPER_INSTRUCTIONS
    assert "If visual context is present, do not answer with \"be more specific\"" in _THREAD_DEVELOPER_INSTRUCTIONS
    assert "Use refinement.goalText as the root user goal" in _THREAD_DEVELOPER_INSTRUCTIONS
    assert "moduleId/moduleLabel" in _THREAD_DEVELOPER_INSTRUCTIONS
    assert "colorbalancergb" in _THREAD_DEVELOPER_INSTRUCTIONS
    assert "primaries" in _THREAD_DEVELOPER_INSTRUCTIONS
    assert "attached as a separate image input" in _THREAD_DEVELOPER_INSTRUCTIONS


def test_turn_prompt_tells_codex_to_infer_broad_edit_plan_from_visual_context() -> None:
    bridge = CodexAppServerBridge(command=["codex", "app-server", "--listen", "stdio://"])

    prompt = bridge._build_turn_prompt(_sample_request())  # type: ignore[attr-defined]

    assert "infer a conservative supported edit plan" in prompt
    assert "preview, histogram, history, and current settings" in prompt
    assert "Respect refinement state" in prompt
    assert "Use moduleId/moduleLabel to group related controls" in prompt
    assert "rgb primaries, color equalizer, or color balance rgb" in prompt
    assert '"moduleId":"colorequal"' in prompt
    assert '"moduleId":"primaries"' in prompt
    assert "Preview: attached separately as image/jpeg 1000x667" in prompt
    assert "Histogram summary: shadows=0.00, midtones=0.70, highlights=0.30" in prompt
    assert "Editable modules: colorequal (color equalizer): 1, exposure (exposure): 1, primaries (rgb primaries): 1" in prompt
    assert '"base64Data":null' in prompt
    assert "ZmFrZS1wcmV2aWV3" not in prompt
    assert '"text":"Do a full edit so this becomes a polished gallery-ready landscape photo."' in prompt


def test_turn_input_sends_preview_as_separate_image_item() -> None:
    bridge = CodexAppServerBridge(command=["codex", "app-server", "--listen", "stdio://"])

    items = bridge._build_turn_input(_sample_request())  # type: ignore[attr-defined]

    assert items[0]["type"] == "text"
    assert items[1]["type"] == "image"
    assert items[1]["url"] == "data:image/jpeg;base64,ZmFrZS1wcmV2aWV3"


def test_turn_input_omits_image_item_without_preview() -> None:
    bridge = CodexAppServerBridge(command=["codex", "app-server", "--listen", "stdio://"])
    request = _sample_request()
    request.imageSnapshot.preview = None

    items = bridge._build_turn_input(request)  # type: ignore[attr-defined]

    assert len(items) == 1
    assert items[0]["type"] == "text"


def test_cancel_request_marks_matching_active_turn_cancelled() -> None:
    bridge = CodexAppServerBridge(command=["codex", "app-server", "--listen", "stdio://"])
    request = _sample_request()
    active_request = bridge._register_request(request)  # type: ignore[attr-defined]

    try:
        canceled = bridge.cancel_request(
            request_id=request.requestId,
            app_session_id=request.session.appSessionId,
            image_session_id=request.session.imageSessionId,
            conversation_id=request.session.conversationId,
            turn_id=request.session.turnId,
        )

        assert canceled is True
        assert active_request.cancel_event.is_set() is True
        with pytest.raises(CodexAppServerError) as exc:
            bridge._raise_if_cancelled_locked(active_request)  # type: ignore[attr-defined]
        assert exc.value.code == "request_cancelled"
    finally:
        bridge._unregister_request(request.requestId)  # type: ignore[attr-defined]


def test_cancel_request_records_unknown_request_ids_for_future_preflight() -> None:
    bridge = CodexAppServerBridge(command=["codex", "app-server", "--listen", "stdio://"])

    canceled = bridge.cancel_request(
        request_id="req-future",
        app_session_id="app-1",
        image_session_id="img-12",
        conversation_id="conv-1",
        turn_id="turn-1",
    )

    assert canceled is False
    request = _sample_request()
    request.requestId = "req-future"
    active_request = bridge._register_request(request)  # type: ignore[attr-defined]
    try:
        assert active_request.cancel_event.is_set() is True
    finally:
        bridge._unregister_request(request.requestId)  # type: ignore[attr-defined]
