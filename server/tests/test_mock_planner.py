from server.mock_planner import MockPlannerBridge
from shared.protocol import RequestEnvelope


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
        "message": {"role": "user", "text": "Increase exposure by exactly 0.7 EV."},
        "fast": False,
        "refinement": {
            "mode": "single-turn",
            "enabled": False,
            "maxPasses": 1,
            "passIndex": 1,
            "goalText": "Increase exposure by exactly 0.7 EV.",
        },
        "uiContext": {"view": "darkroom", "imageId": 12, "imageName": "_DSC8809.ARW"},
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
                }
            ],
            "history": [],
            "preview": None,
            "histogram": None,
        },
    }


def test_mock_planner_returns_single_turn_exposure_delta() -> None:
    planner = MockPlannerBridge()
    request = RequestEnvelope.model_validate(_sample_request_payload())

    result = planner.plan(request)

    assert result.plan.continueRefining is False
    assert result.plan.operations[0].value.number == 0.7


def test_mock_planner_splits_multi_turn_response_across_two_passes() -> None:
    planner = MockPlannerBridge()
    payload = _sample_request_payload()
    payload["refinement"] = {
        "mode": "multi-turn",
        "enabled": True,
        "maxPasses": 10,
        "passIndex": 1,
        "goalText": "Increase exposure by exactly 0.7 EV.",
    }
    first = planner.plan(RequestEnvelope.model_validate(payload))

    payload["session"]["turnId"] = "turn-2"
    payload["refinement"]["passIndex"] = 2
    second = planner.plan(RequestEnvelope.model_validate(payload))

    assert first.plan.continueRefining is True
    assert first.plan.operations[0].value.number == 0.42
    assert second.plan.continueRefining is False
    assert second.plan.operations[0].value.number == 0.28
