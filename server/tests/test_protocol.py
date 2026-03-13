from pydantic import ValidationError

from shared.protocol import RequestEnvelope, build_mock_response


def test_request_envelope_accepts_v2_payload() -> None:
    payload = {
        "schemaVersion": "2.0",
        "requestId": "req-1",
        "conversationId": "conv-1",
        "message": {"role": "user", "text": "Make it brighter"},
        "uiContext": {"view": "darkroom", "imageId": 12, "imageName": "foo.CR3"},
        "mockResponseId": "exposure-plus-0.7",
    }

    envelope = RequestEnvelope.model_validate(payload)

    assert envelope.schemaVersion == "2.0"
    assert envelope.mockResponseId == "exposure-plus-0.7"


def test_request_envelope_rejects_unknown_fields() -> None:
    payload = {
        "schemaVersion": "2.0",
        "requestId": "req-1",
        "conversationId": "conv-1",
        "message": {"role": "user", "text": "Make it brighter", "extra": True},
        "uiContext": {"view": "darkroom", "imageId": None, "imageName": None},
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
            "mockResponseId": "exposure-sequence-plus-0.7",
        }
    )

    response = build_mock_response(request)

    assert [operation.operationId for operation in response.operations] == [
        "op-exposure-plus-0.2",
        "op-exposure-plus-0.5",
    ]
    assert sum(operation.value.number for operation in response.operations) == 0.7


def test_build_mock_response_supports_blocked_operation_fixture() -> None:
    request = RequestEnvelope.model_validate(
        {
            "schemaVersion": "2.0",
            "requestId": "req-5",
            "conversationId": "conv-5",
            "message": {"role": "user", "text": "Try something unsupported"},
            "uiContext": {"view": "darkroom", "imageId": 1, "imageName": "_DSC8809.ARW"},
            "mockResponseId": "unsupported-action",
        }
    )

    response = build_mock_response(request)

    assert response.operations[0].operationId == "op-unsupported-action"
    assert response.operations[0].target.actionPath == "iop/exposure/not-real"
