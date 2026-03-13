from pydantic import ValidationError

from shared.protocol import RequestEnvelope, build_mock_response


def test_request_envelope_accepts_v1_payload() -> None:
    payload = {
        "schemaVersion": "1.0",
        "requestId": "req-1",
        "conversationId": "conv-1",
        "message": {"role": "user", "text": "Make it brighter"},
        "uiContext": {"view": "darkroom", "imageId": 12, "imageName": "foo.CR3"},
        "mockActionId": "brighten-exposure",
    }

    envelope = RequestEnvelope.model_validate(payload)

    assert envelope.schemaVersion == "1.0"
    assert envelope.mockActionId == "brighten-exposure"


def test_request_envelope_rejects_unknown_fields() -> None:
    payload = {
        "schemaVersion": "1.0",
        "requestId": "req-1",
        "conversationId": "conv-1",
        "message": {"role": "user", "text": "Make it brighter", "extra": True},
        "uiContext": {"view": "darkroom", "imageId": None, "imageName": None},
        "mockActionId": None,
    }

    try:
        RequestEnvelope.model_validate(payload)
    except ValidationError as exc:
        assert "extra_forbidden" in str(exc)
    else:
        raise AssertionError("Expected validation failure")


def test_build_mock_response_for_darken() -> None:
    request = RequestEnvelope.model_validate(
        {
            "schemaVersion": "1.0",
            "requestId": "req-2",
            "conversationId": "conv-2",
            "message": {"role": "user", "text": "Make it darker"},
            "uiContext": {"view": "lighttable", "imageId": 99, "imageName": "bar.NEF"},
            "mockActionId": "darken-exposure",
        }
    )

    response = build_mock_response(request)

    assert response.status == "ok"
    assert response.actions[0].parameters.deltaEv == -0.7
    assert response.error is None
