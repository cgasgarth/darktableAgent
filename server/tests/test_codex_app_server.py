import base64
import io
import time

import pytest

from server.codex_app_server import (
    CodexAppServerBridge,
    CodexAppServerError,
    _DEFAULT_MODEL,
    _DEFAULT_REASONING_EFFORT,
    _FAST_MODE_MODEL,
    _FAST_MODE_REASONING_EFFORT,
    _TOOL_APPLY_OPERATIONS,
    _TOOL_GET_IMAGE_STATE,
    _TOOL_GET_PREVIEW_IMAGE,
    _THREAD_DEVELOPER_INSTRUCTIONS,
    TurnRunState,
)
from shared.protocol import AgentPlan, RequestEnvelope

try:
    from PIL import Image, ImageDraw
except Exception:  # pragma: no cover
    Image = None
    ImageDraw = None


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
            "fast": False,
            "refinement": {
                "mode": "multi-turn",
                "enabled": True,
                "maxPasses": 10,
                "passIndex": 1,
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
                    },
                ],
                "history": [
                    {
                        "num": 0,
                        "module": "exposure",
                        "enabled": True,
                        "multiPriority": 0,
                        "instanceName": "exposure",
                        "iopOrder": 20,
                    },
                    {
                        "num": 1,
                        "module": "colorequal",
                        "enabled": True,
                        "multiPriority": 0,
                        "instanceName": "color equalizer",
                        "iopOrder": 65,
                    },
                ],
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


def _region_preview_bytes() -> bytes:
    if Image is None or ImageDraw is None:
        pytest.skip("Pillow is required for region summary tests")
    image = Image.new("RGB", (120, 90), (180, 170, 160))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 119, 28), fill=(70, 130, 220))
    draw.rectangle((35, 28, 85, 78), fill=(210, 165, 130))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def _sample_request_with_white_balance_controls() -> RequestEnvelope:
    payload = _sample_request().model_dump(mode="json")

    wb_targets = [
        {
            "moduleId": "temperature",
            "moduleLabel": "white balance",
            "capabilityId": "temperature.preset",
            "label": "Preset",
            "kind": "set-choice",
            "targetType": "darktable-action",
            "actionPath": "iop/temperature/preset",
            "supportedModes": ["set"],
            "choices": [
                {"choiceValue": 0, "choiceId": "as-shot", "label": "as shot"},
                {
                    "choiceValue": 1,
                    "choiceId": "camera-reference",
                    "label": "camera reference",
                },
                {
                    "choiceValue": 2,
                    "choiceId": "as-shot-to-reference",
                    "label": "as shot to reference",
                },
            ],
            "defaultChoiceValue": 1,
        },
        {
            "moduleId": "temperature",
            "moduleLabel": "white balance",
            "capabilityId": "temperature.temperature",
            "label": "Temperature",
            "kind": "set-float",
            "targetType": "darktable-action",
            "actionPath": "iop/temperature/temperature",
            "supportedModes": ["set", "delta"],
            "minNumber": 2000.0,
            "maxNumber": 50000.0,
            "defaultNumber": 5003.0,
            "stepNumber": 10.0,
        },
        {
            "moduleId": "temperature",
            "moduleLabel": "white balance",
            "capabilityId": "temperature.tint",
            "label": "Tint",
            "kind": "set-float",
            "targetType": "darktable-action",
            "actionPath": "iop/temperature/tint",
            "supportedModes": ["set", "delta"],
            "minNumber": 0.135,
            "maxNumber": 2.326,
            "defaultNumber": 1.0,
            "stepNumber": 0.001,
        },
    ]
    wb_settings = [
        {
            "moduleId": "temperature",
            "moduleLabel": "white balance",
            "settingId": "setting.temperature.preset",
            "capabilityId": "temperature.preset",
            "label": "Preset",
            "actionPath": "iop/temperature/preset",
            "kind": "set-choice",
            "supportedModes": ["set"],
            "currentChoiceValue": 1,
            "currentChoiceId": "camera-reference",
            "choices": [
                {"choiceValue": 0, "choiceId": "as-shot", "label": "as shot"},
                {
                    "choiceValue": 1,
                    "choiceId": "camera-reference",
                    "label": "camera reference",
                },
                {
                    "choiceValue": 2,
                    "choiceId": "as-shot-to-reference",
                    "label": "as shot to reference",
                },
            ],
            "defaultChoiceValue": 1,
        },
        {
            "moduleId": "temperature",
            "moduleLabel": "white balance",
            "settingId": "setting.temperature.temperature",
            "capabilityId": "temperature.temperature",
            "label": "Temperature",
            "actionPath": "iop/temperature/temperature",
            "kind": "set-float",
            "currentNumber": 5003.0,
            "supportedModes": ["set", "delta"],
            "minNumber": 2000.0,
            "maxNumber": 50000.0,
            "defaultNumber": 5003.0,
            "stepNumber": 10.0,
        },
        {
            "moduleId": "temperature",
            "moduleLabel": "white balance",
            "settingId": "setting.temperature.tint",
            "capabilityId": "temperature.tint",
            "label": "Tint",
            "actionPath": "iop/temperature/tint",
            "kind": "set-float",
            "currentNumber": 1.0,
            "supportedModes": ["set", "delta"],
            "minNumber": 0.135,
            "maxNumber": 2.326,
            "defaultNumber": 1.0,
            "stepNumber": 0.001,
        },
    ]

    payload["capabilityManifest"]["targets"].extend(wb_targets)
    payload["imageSnapshot"]["editableSettings"].extend(wb_settings)
    return RequestEnvelope.model_validate(payload)


def test_default_command_uses_stdio_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DARKTABLE_AGENT_CODEX_APP_SERVER_CMD", raising=False)

    bridge = CodexAppServerBridge()

    assert bridge._command == [
        "codex",
        "app-server",
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


def test_sanitize_request_for_agent_safety_preserves_white_balance_controls() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    request = _sample_request_with_white_balance_controls()

    sanitized = bridge._sanitize_request_for_agent_safety(request)  # type: ignore[attr-defined]

    assert len(sanitized.capabilityManifest.targets) == len(
        request.capabilityManifest.targets
    )
    assert len(sanitized.imageSnapshot.editableSettings) == len(
        request.imageSnapshot.editableSettings
    )
    assert any(
        capability.actionPath == "iop/temperature/temperature"
        for capability in sanitized.capabilityManifest.targets
    )
    assert any(
        setting.actionPath == "iop/temperature/preset"
        for setting in sanitized.imageSnapshot.editableSettings
    )


def test_task_complete_marks_turn_complete() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    turn_state: TurnRunState = {
        "thread_id": "thread-1",
        "turn_id": "turn-1",
        "chunks": [],
        "final_message": None,
        "turn_error": None,
        "completed": False,
        "token_usage_last": None,
        "token_usage_total": None,
        "last_activity_at": time.time(),
        "last_activity_method": None,
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

    assert (
        turn_state["final_message"]
        == '{"assistantText":"Done","continueRefining":false,"operations":[]}'
    )
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
    request.fast = True

    assert CodexAppServerBridge._model_for_request(request) == _FAST_MODE_MODEL


def test_effort_selection_uses_default_effort_when_fast_mode_disabled() -> None:
    request = _sample_request()

    assert (
        CodexAppServerBridge._effort_for_request(request) == _DEFAULT_REASONING_EFFORT
    )


def test_effort_selection_uses_fast_mode_effort_when_fast_mode_enabled() -> None:
    request = _sample_request()
    request.fast = True

    assert (
        CodexAppServerBridge._effort_for_request(request) == _FAST_MODE_REASONING_EFFORT
    )


def test_developer_instructions_require_proactive_full_edit_planning() -> None:
    assert "Core rules" in _THREAD_DEVELOPER_INSTRUCTIONS
    assert "expert RAW photo editor" in _THREAD_DEVELOPER_INSTRUCTIONS
    assert (
        "Only emit operations targeting provided settingId/actionPath pairs."
        in _THREAD_DEVELOPER_INSTRUCTIONS
    )
    assert (
        "If user intent is broad, infer a reasonable plan"
        in _THREAD_DEVELOPER_INSTRUCTIONS
    )
    assert (
        "Consider the full set of provided tools and modules"
        in _THREAD_DEVELOPER_INSTRUCTIONS
    )
    assert "colorequal" in _THREAD_DEVELOPER_INSTRUCTIONS
    assert "primaries" in _THREAD_DEVELOPER_INSTRUCTIONS
    assert "set-choice uses value.choiceValue" in _THREAD_DEVELOPER_INSTRUCTIONS


def test_prompt_payload_includes_all_histogram_channels() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    request = _sample_request()

    payload = bridge._build_prompt_payload(request)  # type: ignore[attr-defined]
    histogram = payload["imageSnapshot"]["histogram"]

    assert histogram == {
        "binCount": 4,
        "channels": {
            "luma": {"bins": [0, 20, 50, 30]},
            "red": {"bins": [0, 10, 60, 30]},
            "green": {"bins": [0, 20, 50, 30]},
            "blue": {"bins": [0, 30, 40, 30]},
        },
    }
    analysis = payload["imageSnapshot"]["analysisSignals"]
    assert analysis["activeModuleCount"] == 2
    assert analysis["activeModulesInOrder"][0]["moduleId"] == "exposure"
    assert analysis["activeModulesInOrder"][1]["moduleId"] == "colorequal"
    assert analysis["tonal"]["highlightClipEstimate"] == pytest.approx(0.3)
    assert analysis["quality"]["noiseRisk"] == "low"
    assert analysis["quality"]["sharpnessEstimate"] == "unknown"


def test_prompt_payload_derives_region_summaries_when_preview_is_decodable() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    request = _sample_request()
    assert request.imageSnapshot.preview is not None
    request.imageSnapshot.preview.base64Data = base64.b64encode(
        _region_preview_bytes()
    ).decode()

    payload = bridge._build_prompt_payload(request)  # type: ignore[attr-defined]

    analysis = payload["imageSnapshot"]["analysisSignals"]
    region_kinds = {region["kind"] for region in analysis["regionSummaries"]}
    assert "sky-candidate" in region_kinds
    assert "skin-candidate" in region_kinds


def test_prompt_payload_rebins_histogram_when_luma_bin_count_exceeds_limit() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    request = _sample_request()
    request.imageSnapshot.histogram.binCount = 128  # type: ignore[union-attr]
    request.imageSnapshot.histogram.channels["luma"].bins = [1] * 128  # type: ignore[union-attr]

    payload = bridge._build_prompt_payload(request)  # type: ignore[attr-defined]
    histogram = payload["imageSnapshot"]["histogram"]
    rebinned = histogram["channels"]["luma"]["bins"]

    assert histogram["binCount"] == 64
    assert len(rebinned) == 64
    assert sum(rebinned) == 128


def test_prompt_payload_includes_module_context_for_live_runs() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    request = _sample_request()

    payload = bridge._build_prompt_payload(request)  # type: ignore[attr-defined]
    first_setting = payload["imageSnapshot"]["editableSettings"][0]

    assert first_setting["settingId"] == "setting.exposure.primary"
    assert first_setting["kind"] == "set-float"
    assert first_setting["actionPath"] == "iop/exposure/exposure"
    assert first_setting["supportedModes"] == ["set", "delta"]
    assert first_setting["minNumber"] == -18.0
    assert first_setting["maxNumber"] == 18.0
    assert first_setting["moduleId"] == "exposure"
    assert first_setting["moduleLabel"] == "exposure"
    assert first_setting["stepNumber"] == 0.01

    metadata = payload["imageSnapshot"]["metadata"]
    assert metadata["width"] == 9504
    assert metadata["height"] == 6336
    assert metadata["cameraMaker"] == "Sony"
    assert metadata["cameraModel"] == "ILCE-7RM5"
    assert metadata["exifIso"] == 100.0
    assert metadata["exifAperture"] == 4.0
    assert metadata["exifFocalLength"] == 35.0
    assert payload["imageSnapshot"]["preview"] == {
        "mimeType": "image/jpeg",
        "width": 1000,
        "height": 667,
        "base64Data": None,
    }


def test_turn_prompt_tells_codex_to_infer_broad_edit_plan_from_visual_context() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )

    prompt = bridge._build_turn_prompt(_sample_request())  # type: ignore[attr-defined]

    assert "Tool budget: maximum" in prompt
    assert "tool calls in this run." in prompt
    assert "Live run mode is enabled" in prompt
    assert "Turn input includes the current preview image" in prompt
    assert "compact analysis signals" in prompt
    assert "apply_operations returns the refreshed preview automatically" in prompt
    assert "Do not introduce new operations in the final JSON" in prompt
    assert "do not stop at basic exposure/contrast edits" in prompt
    assert "Apply at least one edit batch within the first" in prompt
    assert "Respect refinement state" in prompt
    assert "EXIF:" in prompt
    assert "Sony" in prompt
    assert "ISO 100.0" in prompt
    assert "Preview:" not in prompt
    assert "Histogram summary:" not in prompt
    assert "Editable modules:" not in prompt
    assert "Fast mode:" not in prompt
    assert '"base64Data"' not in prompt
    assert '"currentNumber"' not in prompt
    assert '"capabilityManifest"' not in prompt
    assert (
        "Latest user message: Do a full edit so this becomes a polished gallery-ready landscape photo."
        in prompt
    )


def test_turn_input_in_live_mode_includes_prompt_state_and_initial_preview_image() -> (
    None
):
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )

    items = bridge._build_turn_input(_sample_request())  # type: ignore[attr-defined]

    assert len(items) == 3
    assert items[0]["type"] == "text"
    assert items[1]["type"] == "text"
    assert str(items[1]["text"]).startswith("Current image state JSON:\n")
    assert '"analysisSignals"' in str(items[1]["text"])
    assert '"editableSettings"' in str(items[1]["text"])
    assert '"histogram"' in str(items[1]["text"])
    assert items[2]["type"] == "image"
    assert str(items[2]["url"]).startswith("data:image/jpeg;base64,")


def test_turn_input_with_conversation_history_prepends_history_item() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    request = _sample_request()
    conv_id = request.session.conversationId
    bridge._conversation_histories[conv_id] = [  # type: ignore[attr-defined]
        "Turn 1: 3 operations. Adjusted exposure and contrast.",
        "Turn 2: 2 operations. Fine-tuned color balance.",
    ]

    items = bridge._build_turn_input(request)  # type: ignore[attr-defined]

    assert len(items) == 4
    assert items[0]["type"] == "text"
    assert "Prior turns in this conversation" in str(items[0]["text"])
    assert "Turn 1: 3 operations" in str(items[0]["text"])
    assert "Turn 2: 2 operations" in str(items[0]["text"])
    assert items[1]["type"] == "text"
    assert items[2]["type"] == "text"
    assert str(items[2]["text"]).startswith("Current image state JSON:\n")
    assert items[3]["type"] == "image"


def test_turn_input_in_single_turn_mode_includes_prompt_and_state_text_only() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    request = _sample_request()
    request.refinement.enabled = False
    request.refinement.mode = "single-turn"
    request.refinement.maxPasses = 1
    request.refinement.passIndex = 1

    items = bridge._build_turn_input(request)  # type: ignore[attr-defined]

    assert len(items) == 2
    assert items[0]["type"] == "text"
    assert items[1]["type"] == "text"
    assert str(items[1]["text"]).startswith("Current image state JSON:\n")


def test_preview_data_url_requires_preview() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    request = _sample_request()
    request.imageSnapshot.preview = None

    with pytest.raises(CodexAppServerError) as exc:
        bridge._preview_data_url(request)  # type: ignore[attr-defined]

    assert exc.value.code == "codex_preview_unavailable"


def test_preview_data_url_fails_when_preview_base64_is_invalid() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    request = _sample_request()
    request.imageSnapshot.preview.base64Data = "not-valid-base64!!!"  # type: ignore[union-attr]

    with pytest.raises(CodexAppServerError) as exc:
        bridge._preview_data_url(request)  # type: ignore[attr-defined]

    assert exc.value.code == "codex_preview_decode_failed"


def test_preview_data_url_returns_data_url() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )

    data_url = bridge._preview_data_url(_sample_request())  # type: ignore[attr-defined]

    assert data_url.startswith("data:image/jpeg;base64,")
    encoded = data_url.split(",", 1)[1]
    assert base64.b64decode(encoded).decode("utf-8") == "fake-preview"


def test_cancel_request_marks_matching_active_turn_cancelled() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    request = _sample_request()
    active_request = bridge._register_request(request)  # type: ignore[attr-defined]

    try:
        canceled = bridge.cancel_request(
            request_id=request.requestId,
            app_session_id=request.session.appSessionId,
            image_session_id=request.session.imageSessionId,
            conversation_id=request.session.conversationId,
            turn_id=request.session.turnId,
            reason="image-changed",
        )

        assert canceled is True
        assert active_request.cancel_event.is_set() is True
        assert active_request.cancel_reason == "image-changed"
        with pytest.raises(CodexAppServerError) as exc:
            bridge._raise_if_cancelled_locked(active_request)  # type: ignore[attr-defined]
        assert exc.value.code == "request_cancelled"
        assert exc.value.message == "image-changed"
    finally:
        bridge._unregister_request(request.requestId)  # type: ignore[attr-defined]


def test_cancel_request_records_unknown_request_ids_for_future_preflight() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )

    canceled = bridge.cancel_request(
        request_id="req-future",
        app_session_id="app-1",
        image_session_id="img-12",
        conversation_id="conv-1",
        turn_id="turn-1",
        reason="apply-failed",
    )

    assert canceled is False
    request = _sample_request()
    request.requestId = "req-future"
    active_request = bridge._register_request(request)  # type: ignore[attr-defined]
    try:
        assert active_request.cancel_event.is_set() is True
        assert active_request.cancel_reason == "apply-failed"
    finally:
        bridge._unregister_request(request.requestId)  # type: ignore[attr-defined]


def test_cancel_request_does_not_preflight_cancel_non_matching_session_tuple() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )

    canceled = bridge.cancel_request(
        request_id="req-future",
        app_session_id="app-1",
        image_session_id="img-12",
        conversation_id="conv-1",
        turn_id="turn-1",
        reason="cancelled",
    )

    assert canceled is False
    request = _sample_request()
    request.requestId = "req-future"
    request.session.conversationId = "conv-2"
    active_request = bridge._register_request(request)  # type: ignore[attr-defined]
    try:
        assert active_request.cancel_event.is_set() is False
        assert active_request.cancel_reason is None
    finally:
        bridge._unregister_request(request.requestId)  # type: ignore[attr-defined]


def test_get_request_progress_returns_not_found_for_unknown_request() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    progress = bridge.get_request_progress(
        request_id="req-999",
        app_session_id="app-1",
        image_session_id="img-12",
        conversation_id="conv-1",
        turn_id="turn-999",
    )
    assert progress == {
        "found": False,
        "status": "not_found",
        "toolCallsUsed": 0,
        "maxToolCalls": 0,
        "appliedOperationCount": 0,
        "operations": [],
        "message": "No active request found for that requestId.",
        "lastToolName": None,
        "progressVersion": 0,
        "requiresRenderCallback": False,
    }


def test_get_request_progress_returns_live_applied_operations_for_active_turn() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    request = _sample_request()
    active_request = bridge._register_request(request)  # type: ignore[attr-defined]
    try:
        data_url = bridge._preview_data_url(request)  # type: ignore[attr-defined]
        bridge._register_turn_context("thread-1", "turn-1", request, data_url)  # type: ignore[attr-defined]
        active_request.thread_id = "thread-1"
        active_request.codex_turn_id = "turn-1"
        active_request.status = "running"
        active_request.message = "Waiting for Codex turn output"
        context = bridge._get_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]
        assert context is not None
        context.tool_calls_used = 3
        context.applied_operations = [
            {
                "operationId": "tool-op-1",
                "sequence": 1,
                "kind": "set-float",
                "target": {
                    "type": "darktable-action",
                    "actionPath": "iop/exposure/exposure",
                    "settingId": "setting.exposure.primary",
                },
                "value": {"mode": "delta", "number": 0.25},
                "reason": None,
                "constraints": {
                    "onOutOfRange": "clamp",
                    "onRevisionMismatch": "fail",
                },
            }
        ]

        progress = bridge.get_request_progress(
            request_id=request.requestId,
            app_session_id=request.session.appSessionId,
            image_session_id=request.session.imageSessionId,
            conversation_id=request.session.conversationId,
            turn_id=request.session.turnId,
        )
        assert progress["found"] is True
        assert progress["status"] == "running"
        assert progress["toolCallsUsed"] == 3
        assert progress["maxToolCalls"] == bridge._effective_tool_budget(request)
        assert progress["appliedOperationCount"] == 1
        assert len(progress["operations"]) == 1
        assert progress["lastToolName"] is None
        assert progress["progressVersion"] == 0
    finally:
        bridge._clear_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]
        bridge._unregister_request(request.requestId)  # type: ignore[attr-defined]


def test_get_or_create_thread_reuses_cached_thread_without_rpc() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    bridge._conversation_threads["conv-1"] = "thread-existing"  # type: ignore[attr-defined]

    def _unexpected_send_request(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError(
            "thread/start should not be called for cached conversations"
        )

    bridge._send_request_locked = _unexpected_send_request  # type: ignore[method-assign,attr-defined]

    thread_id = bridge._get_or_create_thread_locked(  # type: ignore[attr-defined]
        "conv-1", _DEFAULT_MODEL, time.monotonic() + 5.0
    )

    assert thread_id == "thread-existing"


def test_get_or_create_thread_includes_native_dynamic_tools() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    captured: dict[str, object] = {}

    def _stub_send_request(method, params, deadline, active_request):  # type: ignore[no-untyped-def]
        captured["method"] = method
        captured["params"] = params
        return {"result": {"thread": {"id": "thread-new"}}}

    bridge._send_request_locked = _stub_send_request  # type: ignore[method-assign,attr-defined]

    thread_id = bridge._get_or_create_thread_locked(  # type: ignore[attr-defined]
        "conv-2", _DEFAULT_MODEL, time.monotonic() + 5.0
    )

    assert thread_id == "thread-new"
    assert captured["method"] == "thread/start"
    params = captured["params"]  # type: ignore[assignment]
    tool_specs = params["dynamicTools"]  # type: ignore[index]
    names = {tool["name"] for tool in tool_specs}
    assert names == {
        _TOOL_GET_PREVIEW_IMAGE,
        _TOOL_GET_IMAGE_STATE,
        _TOOL_APPLY_OPERATIONS,
    }
    for tool in tool_specs:
        assert tool["inputSchema"]["type"] == "object"
        assert tool["inputSchema"]["additionalProperties"] is False


def test_handle_server_request_denies_approval_requests_with_decline() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    sent_payloads: list[dict] = []

    def _capture(payload):  # type: ignore[no-untyped-def]
        sent_payloads.append(payload)

    bridge._send_json_locked = _capture  # type: ignore[method-assign,attr-defined]

    bridge._handle_server_request_locked(  # type: ignore[attr-defined]
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "item/permissions/requestApproval",
            "params": {},
        }
    )

    assert sent_payloads == [
        {
            "jsonrpc": "2.0",
            "id": 9,
            "result": {"decision": "decline"},
        }
    ]


def test_handle_server_request_routes_preview_tool_call_to_dynamic_result() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    request = _sample_request()
    data_url = bridge._preview_data_url(request)  # type: ignore[attr-defined]
    bridge._register_turn_context("thread-1", "turn-1", request, data_url)  # type: ignore[attr-defined]
    sent_payloads: list[dict] = []

    def _capture(payload):  # type: ignore[no-untyped-def]
        sent_payloads.append(payload)

    bridge._send_json_locked = _capture  # type: ignore[method-assign,attr-defined]
    try:
        bridge._handle_server_request_locked(  # type: ignore[attr-defined]
            {
                "jsonrpc": "2.0",
                "id": 15,
                "method": "item/tool/call",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "callId": "call-1",
                    "tool": _TOOL_GET_PREVIEW_IMAGE,
                    "arguments": {},
                },
            }
        )
    finally:
        bridge._clear_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]

    assert sent_payloads[0]["id"] == 15
    result = sent_payloads[0]["result"]
    assert result["success"] is True
    assert result["contentItems"][0]["type"] == "inputImage"
    assert result["contentItems"][0]["imageUrl"] == data_url


def test_handle_server_request_routes_image_state_tool_call_to_dynamic_result() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    request = _sample_request()
    data_url = bridge._preview_data_url(request)  # type: ignore[attr-defined]
    bridge._register_turn_context("thread-1", "turn-1", request, data_url)  # type: ignore[attr-defined]
    sent_payloads: list[dict] = []

    def _capture(payload):  # type: ignore[no-untyped-def]
        sent_payloads.append(payload)

    bridge._send_json_locked = _capture  # type: ignore[method-assign,attr-defined]
    try:
        bridge._handle_server_request_locked(  # type: ignore[attr-defined]
            {
                "jsonrpc": "2.0",
                "id": 16,
                "method": "item/tool/call",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "callId": "call-2",
                    "tool": _TOOL_GET_IMAGE_STATE,
                    "arguments": {},
                },
            }
        )
    finally:
        bridge._clear_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]

    result = sent_payloads[0]["result"]
    assert result["success"] is True
    assert result["contentItems"][0]["type"] == "inputText"
    state_payload = result["contentItems"][0]["text"]
    assert '"editableSettings"' in state_payload
    assert '"histogram"' in state_payload
    assert '"base64Data":null' in state_payload


def test_apply_operations_tool_updates_state_and_stages_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    request = _sample_request()
    data_url = bridge._preview_data_url(request)  # type: ignore[attr-defined]
    bridge._register_turn_context("thread-1", "turn-1", request, data_url)  # type: ignore[attr-defined]
    sent_payloads: list[dict] = []

    def _capture(payload):  # type: ignore[no-untyped-def]
        sent_payloads.append(payload)

    bridge._send_json_locked = _capture  # type: ignore[method-assign,attr-defined]
    try:
        bridge._handle_server_request_locked(  # type: ignore[attr-defined]
            {
                "jsonrpc": "2.0",
                "id": 18,
                "method": "item/tool/call",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "callId": "call-preview-before",
                    "tool": _TOOL_GET_PREVIEW_IMAGE,
                    "arguments": {},
                },
            }
        )
        preview_before = sent_payloads[0]["result"]["contentItems"][0]["imageUrl"]
        sent_payloads.clear()

        context = bridge._get_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]
        assert context is not None

        def _mock_wait(timeout=None):
            context.rendered_preview_bytes = b"fake-preview-stage-1"
            return True

        monkeypatch.setattr(context.render_event, "wait", _mock_wait)

        bridge._handle_server_request_locked(  # type: ignore[attr-defined]
            {
                "jsonrpc": "2.0",
                "id": 19,
                "method": "item/tool/call",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "callId": "call-apply",
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
                                "value": {"mode": "delta", "number": 0.4},
                            }
                        ]
                    },
                },
            }
        )

        result = sent_payloads[0]["result"]
        assert result["success"] is True
        assert "Applied 1 operations" in result["contentItems"][0]["text"]
        assert (
            "Refreshed preview image included below"
            in result["contentItems"][0]["text"]
        )
        assert result["contentItems"][1]["type"] == "inputImage"
        auto_preview = result["contentItems"][1]["imageUrl"]
        assert auto_preview != preview_before
        assert auto_preview.endswith(
            "x-darktable-stage=1;base64,ZmFrZS1wcmV2aWV3LXN0YWdlLTE="
        )

        sent_payloads.clear()
        bridge._handle_server_request_locked(  # type: ignore[attr-defined]
            {
                "jsonrpc": "2.0",
                "id": 20,
                "method": "item/tool/call",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "callId": "call-preview-after-apply",
                    "tool": _TOOL_GET_PREVIEW_IMAGE,
                    "arguments": {},
                },
            }
        )
        preview_after = sent_payloads[0]["result"]["contentItems"][0]["imageUrl"]
        assert preview_after != preview_before
        assert preview_after.endswith(
            "x-darktable-stage=1;base64,ZmFrZS1wcmV2aWV3LXN0YWdlLTE="
        )

        sent_payloads.clear()
        bridge._handle_server_request_locked(  # type: ignore[attr-defined]
            {
                "jsonrpc": "2.0",
                "id": 21,
                "method": "item/tool/call",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "callId": "call-state-after-apply",
                    "tool": _TOOL_GET_IMAGE_STATE,
                    "arguments": {},
                },
            }
        )
        state_payload = sent_payloads[0]["result"]["contentItems"][0]["text"]
        assert '"currentNumber":0.4' in state_payload
    finally:
        bridge._clear_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]


def test_apply_operations_tool_applies_white_balance_batch_in_stable_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    request = _sample_request_with_white_balance_controls()
    data_url = bridge._preview_data_url(request)  # type: ignore[attr-defined]
    bridge._register_turn_context("thread-1", "turn-1", request, data_url)  # type: ignore[attr-defined]
    white_balance_logs: list[dict] = []
    sent_payloads: list[dict] = []

    def _capture(payload):  # type: ignore[no-untyped-def]
        sent_payloads.append(payload)

    def _capture_info(message, *args, **kwargs):  # type: ignore[no-untyped-def]
        if message == "apply_operations_white_balance":
            white_balance_logs.append(kwargs.get("extra", {}).get("structured", {}))

    bridge._send_json_locked = _capture  # type: ignore[method-assign,attr-defined]
    monkeypatch.setattr("server.codex_app_server.logger.info", _capture_info)
    try:
        context = bridge._get_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]
        assert context is not None

        def _mock_wait(timeout=None):
            context.rendered_preview_bytes = b"fake-preview-stage-3"
            return True

        monkeypatch.setattr(context.render_event, "wait", _mock_wait)

        bridge._handle_server_request_locked(  # type: ignore[attr-defined]
            {
                "jsonrpc": "2.0",
                "id": 210,
                "method": "item/tool/call",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "callId": "call-apply-wb-red",
                    "tool": _TOOL_APPLY_OPERATIONS,
                    "arguments": {
                        "operations": [
                            {
                                "kind": "set-float",
                                "target": {
                                    "type": "darktable-action",
                                    "actionPath": "iop/temperature/tint",
                                    "settingId": "setting.temperature.tint",
                                },
                                "value": {"mode": "set", "number": 1.15},
                            },
                            {
                                "kind": "set-float",
                                "target": {
                                    "type": "darktable-action",
                                    "actionPath": "iop/temperature/temperature",
                                    "settingId": "setting.temperature.temperature",
                                },
                                "value": {"mode": "delta", "number": 250.0},
                            },
                            {
                                "kind": "set-choice",
                                "target": {
                                    "type": "darktable-action",
                                    "actionPath": "iop/temperature/preset",
                                    "settingId": "setting.temperature.preset",
                                },
                                "value": {
                                    "mode": "set",
                                    "choiceValue": 2,
                                    "choiceId": "as-shot-to-reference",
                                },
                            },
                        ]
                    },
                },
            }
        )

        assert (
            context.setting_by_id["setting.temperature.preset"]["currentChoiceValue"]
            == 2
        )
        assert (
            context.setting_by_id["setting.temperature.temperature"]["currentNumber"]
            == 5253.0
        )
        assert (
            context.setting_by_id["setting.temperature.tint"]["currentNumber"] == 1.15
        )
        assert (
            context.state_payload["imageSnapshot"]["imageRevisionId"]
            == "image-12-history-1:tool-3"
        )
        assert context.preview_data_url.endswith(
            "x-darktable-stage=3;base64,ZmFrZS1wcmV2aWV3LXN0YWdlLTM="
        )
        assert [
            operation["target"]["actionPath"]
            for operation in context.applied_operations[-3:]
        ] == [
            "iop/temperature/preset",
            "iop/temperature/temperature",
            "iop/temperature/tint",
        ]
    finally:
        bridge._clear_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]

    result = sent_payloads[0]["result"]
    assert result["success"] is True
    assert "Applied 3 operations" in result["contentItems"][0]["text"]
    assert result["contentItems"][1]["type"] == "inputImage"
    assert result["contentItems"][1]["imageUrl"].endswith(
        "x-darktable-stage=3;base64,ZmFrZS1wcmV2aWV3LXN0YWdlLTM="
    )

    assert white_balance_logs
    structured = white_balance_logs[-1]
    assert structured["attemptedWhiteBalanceActionPaths"] == [
        "iop/temperature/preset",
        "iop/temperature/temperature",
        "iop/temperature/tint",
    ]
    assert structured["appliedWhiteBalanceActionPaths"] == [
        "iop/temperature/preset",
        "iop/temperature/temperature",
        "iop/temperature/tint",
    ]


def test_apply_operations_tool_resolves_unknown_setting_id_by_unique_action_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    request = _sample_request()
    data_url = bridge._preview_data_url(request)  # type: ignore[attr-defined]
    bridge._register_turn_context("thread-1", "turn-1", request, data_url)  # type: ignore[attr-defined]
    sent_payloads: list[dict] = []

    def _capture(payload):  # type: ignore[no-untyped-def]
        sent_payloads.append(payload)

    bridge._send_json_locked = _capture  # type: ignore[method-assign,attr-defined]
    try:
        context = bridge._get_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]
        assert context is not None
        monkeypatch.setattr(context.render_event, "wait", lambda timeout=None: True)

        bridge._handle_server_request_locked(  # type: ignore[attr-defined]
            {
                "jsonrpc": "2.0",
                "id": 211,
                "method": "item/tool/call",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "callId": "call-apply-exposure-unknown-setting-id",
                    "tool": _TOOL_APPLY_OPERATIONS,
                    "arguments": {
                        "operations": [
                            {
                                "kind": "set-float",
                                "target": {
                                    "type": "darktable-action",
                                    "actionPath": "iop/exposure/exposure",
                                    "settingId": "setting.iop.bilat.local.contrast.instance.0",
                                },
                                "value": {"mode": "delta", "number": 0.2},
                            }
                        ]
                    },
                },
            }
        )

        assert context.setting_by_id["setting.exposure.primary"]["currentNumber"] == 0.2
        assert (
            context.applied_operations[-1]["target"]["settingId"]
            == "setting.exposure.primary"
        )
    finally:
        bridge._clear_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]

    result = sent_payloads[0]["result"]
    assert result["success"] is True


def test_apply_operations_tool_failed_batch_logs_only_attempted_white_balance_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    request = _sample_request_with_white_balance_controls()
    data_url = bridge._preview_data_url(request)  # type: ignore[attr-defined]
    bridge._register_turn_context("thread-1", "turn-1", request, data_url)  # type: ignore[attr-defined]
    white_balance_logs: list[dict] = []
    sent_payloads: list[dict] = []

    def _capture(payload):  # type: ignore[no-untyped-def]
        sent_payloads.append(payload)

    def _capture_info(message, *args, **kwargs):  # type: ignore[no-untyped-def]
        if message == "apply_operations_white_balance":
            white_balance_logs.append(kwargs.get("extra", {}).get("structured", {}))

    bridge._send_json_locked = _capture  # type: ignore[method-assign,attr-defined]
    monkeypatch.setattr("server.codex_app_server.logger.info", _capture_info)
    try:
        context = bridge._get_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]
        assert context is not None
        monkeypatch.setattr(context.render_event, "wait", lambda timeout=None: True)

        bridge._handle_server_request_locked(  # type: ignore[attr-defined]
            {
                "jsonrpc": "2.0",
                "id": 212,
                "method": "item/tool/call",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "callId": "call-apply-wb-with-invalid-non-wb-setting",
                    "tool": _TOOL_APPLY_OPERATIONS,
                    "arguments": {
                        "operations": [
                            {
                                "kind": "set-float",
                                "target": {
                                    "type": "darktable-action",
                                    "actionPath": "iop/temperature/temperature",
                                    "settingId": "setting.temperature.temperature",
                                },
                                "value": {"mode": "delta", "number": 100.0},
                            },
                            {
                                "kind": "set-float",
                                "target": {
                                    "type": "darktable-action",
                                    "actionPath": "iop/temperature/tint",
                                    "settingId": "setting.temperature.tint",
                                },
                                "value": {"mode": "set", "number": 1.1},
                            },
                            {
                                "kind": "set-float",
                                "target": {
                                    "type": "darktable-action",
                                    "actionPath": "iop/bilat/local_contrast",
                                    "settingId": "setting.iop.bilat.local.contrast.instance.0",
                                },
                                "value": {"mode": "delta", "number": 0.1},
                            },
                        ]
                    },
                },
            }
        )

        assert context.applied_operations == []
        assert (
            context.setting_by_id["setting.temperature.temperature"]["currentNumber"]
            == 5003.0
        )
    finally:
        bridge._clear_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]

    result = sent_payloads[0]["result"]
    assert result["success"] is False
    assert "unknown settingId" in result["contentItems"][0]["text"]
    assert white_balance_logs
    structured = white_balance_logs[-1]
    assert structured["attemptedWhiteBalanceActionPaths"] == [
        "iop/temperature/temperature",
        "iop/temperature/tint",
    ]
    assert structured["appliedWhiteBalanceActionPaths"] == []


def test_apply_operations_tool_rejects_white_balance_actionpath_settingid_mismatch_without_state_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    request = _sample_request_with_white_balance_controls()
    data_url = bridge._preview_data_url(request)  # type: ignore[attr-defined]
    bridge._register_turn_context("thread-1", "turn-1", request, data_url)  # type: ignore[attr-defined]
    sent_payloads: list[dict] = []

    def _capture(payload):  # type: ignore[no-untyped-def]
        sent_payloads.append(payload)

    bridge._send_json_locked = _capture  # type: ignore[method-assign,attr-defined]
    try:
        context = bridge._get_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]
        assert context is not None
        monkeypatch.setattr(context.render_event, "wait", lambda timeout=None: True)

        bridge._handle_server_request_locked(  # type: ignore[attr-defined]
            {
                "jsonrpc": "2.0",
                "id": 211,
                "method": "item/tool/call",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "callId": "call-apply-wb-temperature",
                    "tool": _TOOL_APPLY_OPERATIONS,
                    "arguments": {
                        "operations": [
                            {
                                "kind": "set-float",
                                "target": {
                                    "type": "darktable-action",
                                    "actionPath": "iop/temperature/tint",
                                    "settingId": "setting.temperature.temperature",
                                },
                                "value": {"mode": "delta", "number": 150.0},
                            }
                        ]
                    },
                },
            }
        )

        assert (
            context.setting_by_id["setting.temperature.temperature"]["currentNumber"]
            == 5003.0
        )
        assert (
            context.state_payload["imageSnapshot"]["imageRevisionId"]
            == "image-12-history-1"
        )
        assert context.applied_operations == []
    finally:
        bridge._clear_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]

    result = sent_payloads[0]["result"]
    assert result["success"] is False
    assert "actionPath mismatch" in result["contentItems"][0]["text"]


def test_apply_operations_tool_rejects_white_balance_choice_id_mismatch_without_state_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    request = _sample_request_with_white_balance_controls()
    data_url = bridge._preview_data_url(request)  # type: ignore[attr-defined]
    bridge._register_turn_context("thread-1", "turn-1", request, data_url)  # type: ignore[attr-defined]
    sent_payloads: list[dict] = []

    def _capture(payload):  # type: ignore[no-untyped-def]
        sent_payloads.append(payload)

    bridge._send_json_locked = _capture  # type: ignore[method-assign,attr-defined]
    try:
        context = bridge._get_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]
        assert context is not None
        monkeypatch.setattr(context.render_event, "wait", lambda timeout=None: True)

        bridge._handle_server_request_locked(  # type: ignore[attr-defined]
            {
                "jsonrpc": "2.0",
                "id": 212,
                "method": "item/tool/call",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "callId": "call-apply-wb-preset",
                    "tool": _TOOL_APPLY_OPERATIONS,
                    "arguments": {
                        "operations": [
                            {
                                "kind": "set-choice",
                                "target": {
                                    "type": "darktable-action",
                                    "actionPath": "iop/temperature/preset",
                                    "settingId": "setting.temperature.preset",
                                },
                                "value": {
                                    "mode": "set",
                                    "choiceValue": 2,
                                    "choiceId": "camera-reference",
                                },
                            }
                        ]
                    },
                },
            }
        )

        assert (
            context.setting_by_id["setting.temperature.preset"]["currentChoiceValue"]
            == 1
        )
        assert (
            context.setting_by_id["setting.temperature.preset"]["currentChoiceId"]
            == "camera-reference"
        )
        assert (
            context.state_payload["imageSnapshot"]["imageRevisionId"]
            == "image-12-history-1"
        )
        assert context.applied_operations == []
    finally:
        bridge._clear_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]

    result = sent_payloads[0]["result"]
    assert result["success"] is False
    assert "choiceId mismatch" in result["contentItems"][0]["text"]


def test_apply_operations_tool_rejected_for_single_turn_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    request = _sample_request()
    request.refinement.enabled = False
    request.refinement.mode = "single-turn"
    request.refinement.maxPasses = 1
    request.refinement.passIndex = 1
    data_url = bridge._preview_data_url(request)  # type: ignore[attr-defined]
    bridge._register_turn_context("thread-1", "turn-1", request, data_url)  # type: ignore[attr-defined]
    sent_payloads: list[dict] = []

    def _capture(payload):  # type: ignore[no-untyped-def]
        sent_payloads.append(payload)

    bridge._send_json_locked = _capture  # type: ignore[method-assign,attr-defined]
    try:
        context = bridge._get_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]
        if context:
            monkeypatch.setattr(context.render_event, "wait", lambda timeout=None: True)

        bridge._handle_server_request_locked(  # type: ignore[attr-defined]
            {
                "jsonrpc": "2.0",
                "id": 21,
                "method": "item/tool/call",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "callId": "call-apply-single",
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
                                "value": {"mode": "delta", "number": 0.1},
                            }
                        ]
                    },
                },
            }
        )
    finally:
        bridge._clear_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]

    result = sent_payloads[0]["result"]
    assert result["success"] is False
    assert (
        "only available when live run mode is enabled"
        in result["contentItems"][0]["text"]
    )


def test_tool_call_budget_limits_total_tool_calls() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    request = _sample_request()
    request.refinement.maxPasses = 2
    data_url = bridge._preview_data_url(request)  # type: ignore[attr-defined]
    bridge._register_turn_context("thread-1", "turn-1", request, data_url)  # type: ignore[attr-defined]
    sent_payloads: list[dict] = []

    def _capture(payload):  # type: ignore[no-untyped-def]
        sent_payloads.append(payload)

    bridge._send_json_locked = _capture  # type: ignore[method-assign,attr-defined]
    budget = bridge._effective_tool_budget(request)
    try:
        for request_id in range(100, 100 + budget + 1):
            bridge._handle_server_request_locked(  # type: ignore[attr-defined]
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "item/tool/call",
                    "params": {
                        "threadId": "thread-1",
                        "turnId": "turn-1",
                        "callId": f"call-budget-{request_id}",
                        "tool": _TOOL_GET_IMAGE_STATE,
                        "arguments": {},
                    },
                }
            )
    finally:
        bridge._clear_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]

    from server.codex_bridge.config import _DEFAULT_MAX_CONSECUTIVE_READ_ONLY_TOOL_CALLS

    for i in range(min(_DEFAULT_MAX_CONSECUTIVE_READ_ONLY_TOOL_CALLS, budget)):
        assert sent_payloads[i]["result"]["success"] is True
    assert sent_payloads[budget]["result"]["success"] is False
    assert (
        "Tool call budget exceeded"
        in sent_payloads[budget]["result"]["contentItems"][0]["text"]
    )


def test_live_run_guardrail_requires_apply_after_initial_read_only_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    request = _sample_request()
    request.refinement.maxPasses = 20
    data_url = bridge._preview_data_url(request)  # type: ignore[attr-defined]
    bridge._register_turn_context("thread-1", "turn-1", request, data_url)  # type: ignore[attr-defined]
    sent_payloads: list[dict] = []

    def _capture(payload):  # type: ignore[no-untyped-def]
        sent_payloads.append(payload)

    bridge._send_json_locked = _capture  # type: ignore[method-assign,attr-defined]
    import server.codex_bridge.tool_routing as _tool_routing_mod

    monkeypatch.setattr(
        _tool_routing_mod, "_DEFAULT_MAX_CONSECUTIVE_READ_ONLY_TOOL_CALLS", 10
    )
    from server.codex_bridge.config import _DEFAULT_MAX_TOOL_CALLS_WITHOUT_APPLY

    call_count = _DEFAULT_MAX_TOOL_CALLS_WITHOUT_APPLY + 1
    try:
        for request_id in range(31, 31 + call_count):
            bridge._handle_server_request_locked(  # type: ignore[attr-defined]
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "item/tool/call",
                    "params": {
                        "threadId": "thread-1",
                        "turnId": "turn-1",
                        "callId": f"call-read-only-{request_id}",
                        "tool": _TOOL_GET_IMAGE_STATE,
                        "arguments": {},
                    },
                }
            )
    finally:
        bridge._clear_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]

    for i in range(_DEFAULT_MAX_TOOL_CALLS_WITHOUT_APPLY):
        assert sent_payloads[i]["result"]["success"] is True
    assert (
        sent_payloads[_DEFAULT_MAX_TOOL_CALLS_WITHOUT_APPLY]["result"]["success"]
        is False
    )
    assert (
        "No live edits have been applied yet in live mode"
        in sent_payloads[_DEFAULT_MAX_TOOL_CALLS_WITHOUT_APPLY]["result"][
            "contentItems"
        ][0]["text"]
    )


def test_read_only_guardrail_requires_apply_or_finalize_after_streak() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    request = _sample_request()
    request.refinement.maxPasses = 20
    data_url = bridge._preview_data_url(request)  # type: ignore[attr-defined]
    bridge._register_turn_context("thread-1", "turn-1", request, data_url)  # type: ignore[attr-defined]
    sent_payloads: list[dict] = []

    def _capture(payload):  # type: ignore[no-untyped-def]
        sent_payloads.append(payload)

    bridge._send_json_locked = _capture  # type: ignore[method-assign,attr-defined]
    try:
        bridge._handle_server_request_locked(  # type: ignore[attr-defined]
            {
                "jsonrpc": "2.0",
                "id": 36,
                "method": "item/tool/call",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "callId": "call-apply-first",
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
                                "value": {"mode": "delta", "number": 0.1},
                            }
                        ]
                    },
                },
            }
        )
        for request_id in (37, 38, 39, 40, 41):
            bridge._handle_server_request_locked(  # type: ignore[attr-defined]
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "item/tool/call",
                    "params": {
                        "threadId": "thread-1",
                        "turnId": "turn-1",
                        "callId": f"call-read-only-{request_id}",
                        "tool": _TOOL_GET_IMAGE_STATE,
                        "arguments": {},
                    },
                }
            )
    finally:
        bridge._clear_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]

    assert sent_payloads[0]["result"]["success"] is True
    assert sent_payloads[1]["result"]["success"] is True
    assert sent_payloads[2]["result"]["success"] is True
    assert sent_payloads[3]["result"]["success"] is True
    assert sent_payloads[4]["result"]["success"] is True
    assert sent_payloads[5]["result"]["success"] is False
    assert (
        "Too many consecutive read-only tool calls"
        in sent_payloads[5]["result"]["contentItems"][0]["text"]
    )


def test_finalize_plan_with_live_context_merges_applied_operations() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    request = _sample_request()
    data_url = bridge._preview_data_url(request)  # type: ignore[attr-defined]
    bridge._register_turn_context("thread-1", "turn-1", request, data_url)  # type: ignore[attr-defined]
    try:
        context = bridge._get_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]
        assert context is not None
        context.applied_operations.append(
            {
                "operationId": "applied-1",
                "sequence": 1,
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
            }
        )
        plan = bridge._finalize_plan_with_live_context(  # type: ignore[attr-defined]
            AgentPlan.model_validate(
                {
                    "assistantText": "done",
                    "continueRefining": True,
                    "operations": [],
                }
            ),
            context,
        )
        assert plan.continueRefining is False
        assert len(plan.operations) == 1
        assert plan.operations[0].operationId == "applied-1"
    finally:
        bridge._clear_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]


def test_finalize_plan_with_live_context_drops_unapplied_tail_operations() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    request = _sample_request()
    data_url = bridge._preview_data_url(request)  # type: ignore[attr-defined]
    bridge._register_turn_context("thread-1", "turn-1", request, data_url)  # type: ignore[attr-defined]
    try:
        context = bridge._get_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]
        assert context is not None
        context.applied_operations.append(
            {
                "operationId": "applied-1",
                "sequence": 1,
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
            }
        )
        plan = bridge._finalize_plan_with_live_context(  # type: ignore[attr-defined]
            AgentPlan.model_validate(
                {
                    "assistantText": "done",
                    "continueRefining": False,
                    "operations": [
                        {
                            "operationId": "bad-tail",
                            "sequence": 1,
                            "kind": "set-float",
                            "target": {
                                "type": "darktable-action",
                                "actionPath": "iop/colorbalancergb/contrast",
                                "settingId": "setting.iop.colorbalancergb.global.contrast.instance.0",
                            },
                            "value": {"mode": "delta", "number": 0.2},
                            "reason": None,
                            "constraints": {
                                "onOutOfRange": "clamp",
                                "onRevisionMismatch": "fail",
                            },
                        }
                    ],
                }
            ),
            context,
        )
        assert plan.continueRefining is False
        assert len(plan.operations) == 1
        assert plan.operations[0].operationId == "applied-1"
    finally:
        bridge._clear_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]


def test_handle_server_request_returns_failed_result_for_unsupported_tool() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    request = _sample_request()
    data_url = bridge._preview_data_url(request)  # type: ignore[attr-defined]
    bridge._register_turn_context("thread-1", "turn-1", request, data_url)  # type: ignore[attr-defined]
    sent_payloads: list[dict] = []

    def _capture(payload):  # type: ignore[no-untyped-def]
        sent_payloads.append(payload)

    bridge._send_json_locked = _capture  # type: ignore[method-assign,attr-defined]
    try:
        bridge._handle_server_request_locked(  # type: ignore[attr-defined]
            {
                "jsonrpc": "2.0",
                "id": 17,
                "method": "item/tool/call",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "callId": "call-3",
                    "tool": "not_a_real_tool",
                    "arguments": {},
                },
            }
        )
    finally:
        bridge._clear_turn_context("thread-1", "turn-1")  # type: ignore[attr-defined]

    result = sent_payloads[0]["result"]
    assert result["success"] is False
    assert "Unsupported tool" in result["contentItems"][0]["text"]


def test_handle_server_request_returns_failed_result_when_turn_context_missing() -> (
    None
):
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    sent_payloads: list[dict] = []

    def _capture(payload):  # type: ignore[no-untyped-def]
        sent_payloads.append(payload)

    bridge._send_json_locked = _capture  # type: ignore[method-assign,attr-defined]
    bridge._handle_server_request_locked(  # type: ignore[attr-defined]
        {
            "jsonrpc": "2.0",
            "id": 18,
            "method": "item/tool/call",
            "params": {
                "threadId": "thread-404",
                "turnId": "turn-404",
                "callId": "call-4",
                "tool": _TOOL_GET_IMAGE_STATE,
                "arguments": {},
            },
        }
    )

    result = sent_payloads[0]["result"]
    assert result["success"] is False
    assert "No active image context" in result["contentItems"][0]["text"]


def test_token_usage_notification_updates_turn_state() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    turn_state: TurnRunState = {
        "thread_id": "thread-1",
        "turn_id": "turn-1",
        "chunks": [],
        "final_message": None,
        "turn_error": None,
        "completed": False,
        "token_usage_last": None,
        "token_usage_total": None,
        "last_activity_at": time.time(),
        "last_activity_method": None,
    }

    bridge._handle_message_locked(  # type: ignore[attr-defined]
        {
            "method": "thread/tokenUsage/updated",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "tokenUsage": {
                    "last": {
                        "cachedInputTokens": 100,
                        "inputTokens": 200,
                        "outputTokens": 50,
                        "reasoningOutputTokens": 25,
                        "totalTokens": 275,
                    },
                    "total": {
                        "cachedInputTokens": 100,
                        "inputTokens": 200,
                        "outputTokens": 50,
                        "reasoningOutputTokens": 25,
                        "totalTokens": 275,
                    },
                },
            },
        },
        turn_state,
    )

    assert turn_state["token_usage_last"] is not None
    assert turn_state["token_usage_total"] is not None
    assert turn_state["token_usage_last"]["inputTokens"] == 200
    assert turn_state["token_usage_total"]["totalTokens"] == 275


def test_token_usage_notification_ignores_other_turns() -> None:
    bridge = CodexAppServerBridge(
        command=["codex", "app-server", "--listen", "stdio://"]
    )
    turn_state: TurnRunState = {
        "thread_id": "thread-1",
        "turn_id": "turn-1",
        "chunks": [],
        "final_message": None,
        "turn_error": None,
        "completed": False,
        "token_usage_last": None,
        "token_usage_total": None,
        "last_activity_at": time.time(),
        "last_activity_method": None,
    }

    bridge._handle_message_locked(  # type: ignore[attr-defined]
        {
            "method": "thread/tokenUsage/updated",
            "params": {
                "threadId": "thread-1",
                "turnId": "different-turn",
                "tokenUsage": {
                    "last": {
                        "cachedInputTokens": 1,
                        "inputTokens": 1,
                        "outputTokens": 1,
                        "reasoningOutputTokens": 1,
                        "totalTokens": 1,
                    },
                    "total": {
                        "cachedInputTokens": 1,
                        "inputTokens": 1,
                        "outputTokens": 1,
                        "reasoningOutputTokens": 1,
                        "totalTokens": 1,
                    },
                },
            },
        },
        turn_state,
    )

    assert turn_state["token_usage_last"] is None
    assert turn_state["token_usage_total"] is None
