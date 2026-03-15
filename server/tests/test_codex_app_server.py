import pytest

from server.codex_app_server import CodexAppServerBridge, _THREAD_DEVELOPER_INSTRUCTIONS
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
            "uiContext": {
                "view": "darkroom",
                "imageId": 12,
                "imageName": "_DSC8809.ARW",
            },
            "capabilityManifest": {
                "manifestVersion": "manifest-1",
                "targets": [
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
                    "last_agent_message": '{"assistantText":"Done","operations":[]}',
                },
            },
        },
        turn_state,
    )

    assert turn_state["final_message"] == '{"assistantText":"Done","operations":[]}'
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


def test_developer_instructions_require_proactive_full_edit_planning() -> None:
    assert "Treat broad creative requests" in _THREAD_DEVELOPER_INSTRUCTIONS
    assert "If visual context is present, do not answer with \"be more specific\"" in _THREAD_DEVELOPER_INSTRUCTIONS


def test_turn_prompt_tells_codex_to_infer_broad_edit_plan_from_visual_context() -> None:
    bridge = CodexAppServerBridge(command=["codex", "app-server", "--listen", "stdio://"])

    prompt = bridge._build_turn_prompt(_sample_request())  # type: ignore[attr-defined]

    assert "infer a conservative supported edit plan" in prompt
    assert "preview, histogram, history, and current settings" in prompt
    assert '"text":"Do a full edit so this becomes a polished gallery-ready landscape photo."' in prompt
