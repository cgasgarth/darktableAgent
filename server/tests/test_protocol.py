from pydantic import ValidationError

from shared.protocol import RequestEnvelope, build_mock_response


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


def test_request_envelope_accepts_v2_payload() -> None:
    payload = {
        "schemaVersion": "2.0",
        "requestId": "req-1",
        "conversationId": "conv-1",
        "message": {"role": "user", "text": "Make it brighter"},
        "uiContext": {"view": "darkroom", "imageId": 12, "imageName": "foo.CR3"},
        "capabilities": _sample_capabilities(),
        "imageState": _sample_image_state(),
        "mockResponseId": "exposure-plus-0.7",
    }

    envelope = RequestEnvelope.model_validate(payload)

    assert envelope.schemaVersion == "2.0"
    assert envelope.mockResponseId == "exposure-plus-0.7"
    assert envelope.capabilities[0].supportedModes == ["set", "delta"]
    assert envelope.imageState.controls[0].actionPath == "iop/exposure/exposure"


def test_request_envelope_rejects_unknown_fields() -> None:
    payload = {
        "schemaVersion": "2.0",
        "requestId": "req-1",
        "conversationId": "conv-1",
        "message": {"role": "user", "text": "Make it brighter", "extra": True},
        "uiContext": {"view": "darkroom", "imageId": None, "imageName": None},
        "capabilities": _sample_capabilities(),
        "imageState": _sample_image_state(),
        "mockResponseId": None,
    }

    try:
        RequestEnvelope.model_validate(payload)
    except ValidationError as exc:
        assert "extra_forbidden" in str(exc)
    else:
        raise AssertionError("Expected validation failure")


def test_build_mock_response_for_exposure_delta() -> None:
    request = RequestEnvelope.model_validate(
        {
            "schemaVersion": "2.0",
            "requestId": "req-2",
            "conversationId": "conv-2",
            "message": {"role": "user", "text": "Make it brighter"},
            "uiContext": {"view": "lighttable", "imageId": 99, "imageName": "bar.NEF"},
            "capabilities": _sample_capabilities(),
            "imageState": _sample_image_state(),
            "mockResponseId": "exposure-plus-0.7",
        }
    )

    response = build_mock_response(request)

    assert response.status == "ok"
    assert response.operations[0].target.actionPath == "iop/exposure/exposure"
    assert response.operations[0].value.mode == "delta"
    assert response.operations[0].value.number == 0.7
    assert response.error is None


def test_build_mock_response_defaults_to_exposure_mock() -> None:
    request = RequestEnvelope.model_validate(
        {
            "schemaVersion": "2.0",
            "requestId": "req-3",
            "conversationId": "conv-3",
            "message": {"role": "user", "text": "Anything"},
            "uiContext": {"view": "darkroom", "imageId": None, "imageName": None},
            "capabilities": _sample_capabilities(),
            "imageState": _sample_image_state(),
            "mockResponseId": None,
        }
    )

    response = build_mock_response(request)

    assert response.operations
    assert response.operations[0].value.number == 0.7


def test_build_mock_response_supports_ordered_exposure_sequence() -> None:
    request = RequestEnvelope.model_validate(
        {
            "schemaVersion": "2.0",
            "requestId": "req-4",
            "conversationId": "conv-4",
            "message": {"role": "user", "text": "Sequence"},
            "uiContext": {"view": "darkroom", "imageId": 1, "imageName": "_DSC8809.ARW"},
            "capabilities": _sample_capabilities(),
            "imageState": _sample_image_state(),
            "mockResponseId": "exposure-sequence-plus-0.7",
        }
    )

    response = build_mock_response(request)

    assert [operation.operationId for operation in response.operations] == [
        "op-exposure-plus-0.2",
        "op-exposure-plus-0.5",
    ]
    assert sum(operation.value.number for operation in response.operations) == 0.7


def test_build_mock_response_supports_absolute_exposure_set() -> None:
    request = RequestEnvelope.model_validate(
        {
            "schemaVersion": "2.0",
            "requestId": "req-set",
            "conversationId": "conv-set",
            "message": {"role": "user", "text": "Set exposure"},
            "uiContext": {"view": "darkroom", "imageId": 1, "imageName": "_DSC8809.ARW"},
            "capabilities": _sample_capabilities(),
            "imageState": _sample_image_state(),
            "mockResponseId": "exposure-set-1.25",
        }
    )

    response = build_mock_response(request)

    assert response.operations[0].value.mode == "set"
    assert response.operations[0].value.number == 1.25


def test_build_mock_response_supports_exposure_clamp_fixtures() -> None:
    request = RequestEnvelope.model_validate(
        {
            "schemaVersion": "2.0",
            "requestId": "req-clamp",
            "conversationId": "conv-clamp",
            "message": {"role": "user", "text": "Clamp exposure"},
            "uiContext": {"view": "darkroom", "imageId": 1, "imageName": "_DSC8809.ARW"},
            "capabilities": _sample_capabilities(),
            "imageState": _sample_image_state(),
            "mockResponseId": "exposure-clamp-max",
        }
    )

    max_response = build_mock_response(request)
    min_response = build_mock_response(
        request.model_copy(update={"mockResponseId": "exposure-clamp-min"})
    )

    assert max_response.operations[0].value.number == 99.0
    assert min_response.operations[0].value.number == -99.0


def test_build_mock_response_supports_blocked_operation_fixture() -> None:
    request = RequestEnvelope.model_validate(
        {
            "schemaVersion": "2.0",
            "requestId": "req-5",
            "conversationId": "conv-5",
            "message": {"role": "user", "text": "Try something unsupported"},
            "uiContext": {"view": "darkroom", "imageId": 1, "imageName": "_DSC8809.ARW"},
            "capabilities": _sample_capabilities(),
            "imageState": _sample_image_state(),
            "mockResponseId": "unsupported-action",
        }
    )

    response = build_mock_response(request)

    assert response.operations[0].operationId == "op-unsupported-action"
    assert response.operations[0].target.actionPath == "iop/exposure/not-real"


def test_request_envelope_rejects_missing_image_state() -> None:
    payload = {
        "schemaVersion": "2.0",
        "requestId": "req-missing-state",
        "conversationId": "conv-missing-state",
        "message": {"role": "user", "text": "Make it brighter"},
        "uiContext": {"view": "darkroom", "imageId": 12, "imageName": "foo.CR3"},
        "capabilities": _sample_capabilities(),
        "mockResponseId": "exposure-plus-0.7",
    }

    try:
        RequestEnvelope.model_validate(payload)
    except ValidationError as exc:
        assert "imageState" in str(exc)
    else:
        raise AssertionError("Expected validation failure")


def test_request_envelope_rejects_missing_capabilities() -> None:
    payload = {
        "schemaVersion": "2.0",
        "requestId": "req-missing-capabilities",
        "conversationId": "conv-missing-capabilities",
        "message": {"role": "user", "text": "Make it brighter"},
        "uiContext": {"view": "darkroom", "imageId": 12, "imageName": "foo.CR3"},
        "imageState": _sample_image_state(),
        "mockResponseId": "exposure-plus-0.7",
    }

    try:
        RequestEnvelope.model_validate(payload)
    except ValidationError as exc:
        assert "capabilities" in str(exc)
    else:
        raise AssertionError("Expected validation failure")


def test_request_envelope_rejects_control_manifest_mismatch() -> None:
    payload = {
        "schemaVersion": "2.0",
        "requestId": "req-mismatch",
        "conversationId": "conv-mismatch",
        "message": {"role": "user", "text": "Make it brighter"},
        "uiContext": {"view": "darkroom", "imageId": 12, "imageName": "foo.CR3"},
        "capabilities": _sample_capabilities(),
        "imageState": {
            **_sample_image_state(),
            "controls": [
                {
                    "capabilityId": "exposure.primary",
                    "label": "Exposure",
                    "actionPath": "iop/exposure/not-real",
                    "currentNumber": 2.8,
                }
            ],
        },
        "mockResponseId": "exposure-plus-0.7",
    }

    try:
        RequestEnvelope.model_validate(payload)
    except ValidationError as exc:
        assert "actionPath does not match capability manifest" in str(exc)
    else:
        raise AssertionError("Expected validation failure")
