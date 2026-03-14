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
        "uiContext": {"view": "darkroom", "imageId": 12, "imageName": "foo.CR3"},
        "capabilities": _sample_capabilities(),
        "imageState": _sample_image_state(),
    }


def test_request_envelope_accepts_v2_payload() -> None:
    envelope = RequestEnvelope.model_validate(_sample_request_payload())

    assert envelope.schemaVersion == "2.0"
    assert envelope.capabilities[0].supportedModes == ["set", "delta"]
    assert envelope.imageState.controls[0].actionPath == "iop/exposure/exposure"


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

    response = build_response_from_plan(request, plan)

    assert response.message.text == "Applying two exposure adjustments."
    assert [operation.operationId for operation in response.operations] == [
        "op-exposure-plus-0.2",
        "op-exposure-plus-0.5",
    ]
    assert [operation.status for operation in response.operations] == ["planned", "planned"]


def test_agent_plan_rejects_duplicate_operation_ids() -> None:
    try:
        AgentPlan.model_validate(
            {
                "assistantText": "Nope",
                "operations": [
                    {
                        "operationId": "duplicate",
                        "kind": "set-float",
                        "target": {
                            "type": "darktable-action",
                            "actionPath": "iop/exposure/exposure",
                        },
                        "value": {"mode": "delta", "number": 0.2},
                    },
                    {
                        "operationId": "duplicate",
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
    except ValidationError as exc:
        assert "operationId values must be unique" in str(exc)
    else:
        raise AssertionError("Expected validation failure")


def test_request_envelope_rejects_missing_image_state() -> None:
    payload = _sample_request_payload()
    payload.pop("imageState")

    try:
        RequestEnvelope.model_validate(payload)
    except ValidationError as exc:
        assert "imageState" in str(exc)
    else:
        raise AssertionError("Expected validation failure")


def test_request_envelope_rejects_missing_capabilities() -> None:
    payload = _sample_request_payload()
    payload.pop("capabilities")

    try:
        RequestEnvelope.model_validate(payload)
    except ValidationError as exc:
        assert "capabilities" in str(exc)
    else:
        raise AssertionError("Expected validation failure")


def test_request_envelope_rejects_control_capability_mismatch() -> None:
    payload = _sample_request_payload()
    payload["imageState"]["controls"][0]["capabilityId"] = "unknown.capability"

    try:
        RequestEnvelope.model_validate(payload)
    except ValidationError as exc:
        assert "unknown capabilityId" in str(exc)
    else:
        raise AssertionError("Expected validation failure")
