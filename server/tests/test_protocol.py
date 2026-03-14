from pydantic import ValidationError

from shared.protocol import AgentPlan, RequestEnvelope, build_response_from_plan


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
        },
        {
            "capabilityId": "filmic.preserve-highlights",
            "label": "Preserve highlights",
            "kind": "set-bool",
            "targetType": "darktable-action",
            "actionPath": "iop/filmicrgb/preserve_highlights",
            "supportedModes": ["set"],
            "defaultBool": False,
        },
        {
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
    assert envelope.capabilityManifest.targets[0].supportedModes == ["set", "delta"]
    assert envelope.capabilityManifest.targets[1].defaultBool is False
    assert envelope.capabilityManifest.targets[2].choices[1].choiceId == "rgb"
    assert (
        envelope.imageSnapshot.editableSettings[0].actionPath == "iop/exposure/exposure"
    )
    assert envelope.imageSnapshot.editableSettings[1].currentBool is True
    assert envelope.imageSnapshot.editableSettings[2].currentChoiceId == "rgb"


def test_request_envelope_rejects_unknown_fields() -> None:
    payload = _sample_request_payload()
    payload["message"]["extra"] = True

    try:
        RequestEnvelope.model_validate(payload)
    except ValidationError as exc:
        assert "extra_forbidden" in str(exc)
    else:
        raise AssertionError("Expected validation failure")


def test_build_response_from_plan_preserves_ordered_operations() -> None:
    request = RequestEnvelope.model_validate(_sample_request_payload())
    plan = AgentPlan.model_validate(
        {
            "assistantText": "Applying two exposure adjustments.",
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


def test_agent_plan_rejects_duplicate_operation_ids() -> None:
    try:
        AgentPlan.model_validate(
            {
                "assistantText": "Nope",
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
