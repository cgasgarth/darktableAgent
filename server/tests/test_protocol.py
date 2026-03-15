import pytest
from pydantic import ValidationError

from shared.protocol import AgentPlan, RequestEnvelope, build_response_from_plan


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
                {
                    "choiceValue": 0,
                    "choiceId": "jzazbz",
                    "label": "JzAzBz",
                },
                {
                    "choiceValue": 1,
                    "choiceId": "rgb",
                    "label": "RGB",
                },
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
                    {
                        "choiceValue": 0,
                        "choiceId": "jzazbz",
                        "label": "JzAzBz",
                    },
                    {
                        "choiceValue": 1,
                        "choiceId": "rgb",
                        "label": "RGB",
                    },
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
        "preview": {
            "previewId": "preview-12-1000w",
            "mimeType": "image/jpeg",
            "width": 1000,
            "height": 666,
            "base64Data": "ZmFrZS1wcmV2aWV3",
        },
        "histogram": {
            "binCount": 4,
            "channels": {
                "red": {"bins": [1, 2, 3, 4]},
                "green": {"bins": [4, 3, 2, 1]},
                "blue": {"bins": [0, 1, 0, 1]},
                "luma": {"bins": [2, 2, 2, 2]},
            },
        },
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
        "fast": False,
        "refinement": {
            "mode": "single-turn",
            "enabled": False,
            "maxPasses": 1,
            "passIndex": 1,
            "automaticContinuation": False,
            "goalText": "Make it brighter",
        },
        "uiContext": {"view": "darkroom", "imageId": 12, "imageName": "foo.CR3"},
        "capabilityManifest": {
            "manifestVersion": "manifest-1",
            "targets": _sample_capabilities(),
        },
        "imageSnapshot": _sample_image_snapshot(),
    }


def test_request_envelope_accepts_v3_payload() -> None:
    envelope = RequestEnvelope.model_validate(_sample_request_payload())

    assert envelope.schemaVersion == "3.0"
    assert envelope.refinement.mode == "single-turn"
    assert envelope.fast is False
    assert envelope.capabilityManifest.targets[0].supportedModes == ["set", "delta"]
    assert envelope.capabilityManifest.targets[1].defaultBool is False
    assert envelope.capabilityManifest.targets[2].choices[1].choiceId == "rgb"
    assert envelope.capabilityManifest.targets[3].moduleId == "colorequal"
    assert envelope.capabilityManifest.targets[4].moduleLabel == "rgb primaries"
    assert (
        envelope.imageSnapshot.editableSettings[0].actionPath == "iop/exposure/exposure"
    )
    assert envelope.imageSnapshot.editableSettings[1].currentBool is True
    assert envelope.imageSnapshot.editableSettings[2].currentChoiceId == "rgb"
    assert envelope.imageSnapshot.editableSettings[3].moduleLabel == "color equalizer"
    assert envelope.imageSnapshot.editableSettings[4].actionPath == "iop/primaries/red_hue"
    assert envelope.imageSnapshot.preview.width == 1000
    assert envelope.imageSnapshot.histogram.binCount == 4


def test_request_envelope_rejects_unknown_fields() -> None:
    payload = _sample_request_payload()
    payload["message"]["extra"] = True

    try:
        RequestEnvelope.model_validate(payload)
    except ValidationError as exc:
        assert "extra_forbidden" in str(exc)
    else:
        raise AssertionError("Expected validation failure")


def test_request_envelope_rejects_invalid_single_turn_refinement_shape() -> None:
    payload = _sample_request_payload()
    payload["refinement"]["maxPasses"] = 3

    try:
        RequestEnvelope.model_validate(payload)
    except ValidationError as exc:
        assert "single-turn refinement must use maxPasses=1" in str(exc)
    else:
        raise AssertionError("Expected validation failure")


def test_request_envelope_rejects_module_metadata_mismatch() -> None:
    payload = _sample_request_payload()
    payload["imageSnapshot"]["editableSettings"][4]["moduleId"] = "colorbalancergb"

    try:
        RequestEnvelope.model_validate(payload)
    except ValidationError as exc:
        assert "editableSetting moduleId does not match capability manifest" in str(exc)
    else:
        raise AssertionError("Expected validation failure")


def test_build_response_from_plan_preserves_ordered_operations() -> None:
    request = RequestEnvelope.model_validate(_sample_request_payload())
    plan = AgentPlan.model_validate(
        {
            "assistantText": "Applying two exposure adjustments.",
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

    response = build_response_from_plan(request, plan)

    assert response.assistantMessage.text == "Applying two exposure adjustments."
    assert [operation.operationId for operation in response.plan.operations] == [
        "op-exposure-plus-0.2",
        "op-exposure-plus-0.5",
    ]
    assert [result.status for result in response.operationResults] == ["planned", "planned"]
    assert response.session.conversationId == "conv-1"
    assert response.refinement.stopReason == "single-turn"
    assert response.refinement.continueRefining is False


def test_build_response_from_plan_marks_multi_turn_continuation() -> None:
    payload = _sample_request_payload()
    payload["message"]["text"] = "Do a full edit"
    payload["refinement"] = {
        "mode": "multi-turn",
        "enabled": True,
        "maxPasses": 10,
        "passIndex": 2,
        "automaticContinuation": True,
        "goalText": "Do a full edit",
    }
    request = RequestEnvelope.model_validate(payload)
    plan = AgentPlan.model_validate(
        {
            "assistantText": "Refining midtones and color separation.",
            "continueRefining": True,
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
                }
            ],
        }
    )

    response = build_response_from_plan(request, plan)

    assert response.refinement.mode == "multi-turn"
    assert response.refinement.passIndex == 2
    assert response.refinement.maxPasses == 10
    assert response.refinement.continueRefining is True
    assert response.refinement.stopReason == "continue"


def test_agent_plan_rejects_duplicate_operation_ids() -> None:
    try:
        AgentPlan.model_validate(
            {
                "assistantText": "Nope",
                "continueRefining": False,
                "operations": [
                    {
                        "operationId": "duplicate",
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
                        "operationId": "duplicate",
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
    except ValidationError as exc:
        assert "operationId values must be unique" in str(exc)
    else:
        raise AssertionError("Expected validation failure")


def test_agent_plan_rejects_duplicate_sequences() -> None:
    try:
        AgentPlan.model_validate(
            {
                "assistantText": "Nope",
                "continueRefining": False,
                "operations": [
                    {
                        "operationId": "one",
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
                        "operationId": "two",
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
                    },
                ],
            }
        )
    except ValidationError as exc:
        assert "operation sequence values must be unique" in str(exc)
    else:
        raise AssertionError("Expected validation failure")


def test_request_envelope_rejects_missing_image_snapshot() -> None:
    payload = _sample_request_payload()
    payload.pop("imageSnapshot")

    try:
        RequestEnvelope.model_validate(payload)
    except ValidationError as exc:
        assert "imageSnapshot" in str(exc)
    else:
        raise AssertionError("Expected validation failure")


def test_request_envelope_rejects_missing_capability_manifest() -> None:
    payload = _sample_request_payload()
    payload.pop("capabilityManifest")

    try:
        RequestEnvelope.model_validate(payload)
    except ValidationError as exc:
        assert "capabilityManifest" in str(exc)
    else:
        raise AssertionError("Expected validation failure")


def test_request_envelope_rejects_setting_capability_mismatch() -> None:
    payload = _sample_request_payload()
    payload["imageSnapshot"]["editableSettings"][0]["capabilityId"] = "unknown.capability"

    try:
        RequestEnvelope.model_validate(payload)
    except ValidationError as exc:
        assert "unknown capabilityId" in str(exc)
    else:
        raise AssertionError("Expected validation failure")


def test_agent_plan_accepts_bool_and_choice_operations() -> None:
    plan = AgentPlan.model_validate(
            {
                "assistantText": "Updating bool and choice settings.",
                "continueRefining": False,
                "operations": [
                {
                    "operationId": "op-bool",
                    "sequence": 1,
                    "kind": "set-bool",
                    "target": {
                        "type": "darktable-action",
                        "actionPath": "iop/filmicrgb/preserve_highlights",
                        "settingId": "setting.filmic.preserve-highlights",
                    },
                    "value": {"mode": "set", "boolValue": True},
                    "reason": "Keep highlight detail.",
                    "constraints": {
                        "onOutOfRange": "clamp",
                        "onRevisionMismatch": "fail",
                    },
                },
                {
                    "operationId": "op-choice",
                    "sequence": 2,
                    "kind": "set-choice",
                    "target": {
                        "type": "darktable-action",
                        "actionPath": "iop/colorbalancergb/saturation_formula",
                        "settingId": "setting.colorbalancergb.saturation-formula",
                    },
                    "value": {
                        "mode": "set",
                        "choiceValue": 0,
                        "choiceId": "jzazbz",
                    },
                    "reason": "Use the preferred formula.",
                    "constraints": {
                        "onOutOfRange": "clamp",
                        "onRevisionMismatch": "fail",
                    },
                },
            ],
        }
    )

    assert plan.operations[0].value.boolValue is True
    assert plan.operations[1].value.choiceValue == 0


def test_request_envelope_accepts_multi_turn_refinement() -> None:
    payload = _sample_request_payload()
    payload["refinement"] = {
        "mode": "multi-turn",
        "enabled": True,
        "maxPasses": 10,
        "passIndex": 2,
        "automaticContinuation": True,
        "goalText": "Make this a polished landscape",
    }

    envelope = RequestEnvelope.model_validate(payload)

    assert envelope.refinement.mode == "multi-turn"
    assert envelope.refinement.enabled is True
    assert envelope.fast is False
    assert envelope.refinement.passIndex == 2


def test_request_envelope_accepts_multi_turn_refinement_with_budget_15() -> None:
    payload = _sample_request_payload()
    payload["refinement"] = {
        "mode": "multi-turn",
        "enabled": True,
        "maxPasses": 15,
        "passIndex": 15,
        "automaticContinuation": True,
        "goalText": "Push this to a final polished look",
    }

    envelope = RequestEnvelope.model_validate(payload)

    assert envelope.refinement.maxPasses == 15
    assert envelope.refinement.passIndex == 15


def test_request_envelope_rejects_multi_turn_refinement_with_budget_16() -> None:
    payload = _sample_request_payload()
    payload["refinement"] = {
        "mode": "multi-turn",
        "enabled": True,
        "maxPasses": 16,
        "passIndex": 1,
        "automaticContinuation": False,
        "goalText": "Push this to a final polished look",
    }

    with pytest.raises(ValidationError):
        RequestEnvelope.model_validate(payload)


def test_request_envelope_rejects_single_turn_refinement_with_invalid_budget() -> None:
    payload = _sample_request_payload()
    payload["refinement"]["maxPasses"] = 3

    try:
        RequestEnvelope.model_validate(payload)
    except ValidationError as exc:
        assert "single-turn refinement must use maxPasses=1" in str(exc)
    else:
        raise AssertionError("Expected validation failure")


def test_build_response_from_plan_sets_multi_turn_continue_state() -> None:
    payload = _sample_request_payload()
    payload["refinement"] = {
        "mode": "multi-turn",
        "enabled": True,
        "maxPasses": 4,
        "passIndex": 2,
        "automaticContinuation": True,
        "goalText": "Do a polished edit",
    }
    request = RequestEnvelope.model_validate(payload)
    plan = AgentPlan.model_validate(
        {
            "assistantText": "One more finishing pass should help.",
            "continueRefining": True,
            "operations": [
                {
                    "operationId": "op-exposure-plus-0.1",
                    "sequence": 1,
                    "kind": "set-float",
                    "target": {
                        "type": "darktable-action",
                        "actionPath": "iop/exposure/exposure",
                        "settingId": "setting.exposure.primary",
                    },
                    "value": {"mode": "delta", "number": 0.1},
                    "reason": None,
                    "constraints": {
                        "onOutOfRange": "clamp",
                        "onRevisionMismatch": "fail",
                    },
                }
            ],
        }
    )

    response = build_response_from_plan(request, plan)

    assert response.refinement.model_dump() == {
        "mode": "multi-turn",
        "enabled": True,
        "passIndex": 2,
        "maxPasses": 4,
        "continueRefining": True,
        "stopReason": "continue",
    }


def test_build_response_from_plan_stops_multi_turn_without_operations() -> None:
    payload = _sample_request_payload()
    payload["refinement"] = {
        "mode": "multi-turn",
        "enabled": True,
        "maxPasses": 4,
        "passIndex": 3,
        "automaticContinuation": True,
        "goalText": "Do a polished edit",
    }
    request = RequestEnvelope.model_validate(payload)
    plan = AgentPlan.model_validate(
        {
            "assistantText": "No further safe edits are warranted.",
            "continueRefining": True,
            "operations": [],
        }
    )

    response = build_response_from_plan(request, plan)

    assert response.refinement.continueRefining is False
    assert response.refinement.stopReason == "no-operations"
