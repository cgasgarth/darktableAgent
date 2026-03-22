from __future__ import annotations

from shared.protocol import RequestEnvelope


def build_request(
    *,
    request_id: str,
    text: str,
    goal_text: str,
    preview_base64: str,
    iso: float,
) -> RequestEnvelope:
    settings = editable_settings()
    return RequestEnvelope.model_validate(
        {
            "schemaVersion": "3.0",
            "requestId": request_id,
            "session": {
                "appSessionId": "eval-app",
                "imageSessionId": f"img-{request_id}",
                "conversationId": f"conv-{request_id}",
                "turnId": "turn-1",
            },
            "message": {"role": "user", "text": text},
            "fast": False,
            "refinement": {
                "mode": "multi-turn",
                "enabled": True,
                "maxPasses": 5,
                "passIndex": 1,
                "goalText": goal_text,
            },
            "uiContext": {
                "view": "darkroom",
                "imageId": 12,
                "imageName": f"{request_id}.ARW",
            },
            "capabilityManifest": {
                "manifestVersion": "eval-manifest-1",
                "targets": [capability_from_setting(setting) for setting in settings],
            },
            "imageSnapshot": {
                "imageRevisionId": f"rev-{request_id}",
                "metadata": {
                    "imageId": 12,
                    "imageName": f"{request_id}.ARW",
                    "cameraMaker": "Sony",
                    "cameraModel": "ILCE-7RM5",
                    "width": 9504,
                    "height": 6336,
                    "exifExposureSeconds": 0.01,
                    "exifAperture": 4.0,
                    "exifIso": iso,
                    "exifFocalLength": 35.0,
                },
                "historyPosition": 1,
                "historyCount": 1,
                "editableSettings": settings,
                "history": [
                    history_entry("temperature", "white balance", 10),
                    history_entry("exposure", "exposure", 20),
                    history_entry("filmicrgb", "filmic rgb", 30),
                    history_entry("denoiseprofile", "denoise (profiled)", 40),
                    history_entry("colorbalancergb", "color balance rgb", 50),
                    history_entry("colorequal", "color equalizer", 60),
                    history_entry("primaries", "rgb primaries", 70),
                    history_entry("clipping", "crop and rotate", 80),
                ],
                "preview": {
                    "previewId": f"preview-{request_id}",
                    "mimeType": "image/png",
                    "width": 48,
                    "height": 48,
                    "base64Data": preview_base64,
                },
                "histogram": None,
            },
        }
    )


def editable_settings() -> list[dict[str, object]]:
    return [
        float_setting(
            module_id="exposure",
            module_label="exposure",
            setting_id="setting.exposure.primary",
            capability_id="exposure.primary",
            label="Exposure",
            action_path="iop/exposure/exposure",
            current=0.0,
            minimum=-18.0,
            maximum=18.0,
        ),
        choice_setting(
            module_id="temperature",
            module_label="white balance",
            setting_id="setting.temperature.preset",
            capability_id="temperature.preset",
            label="Preset",
            action_path="iop/temperature/preset",
            current_choice_id="camera",
            current_choice_value=0,
            choices=(
                (0, "camera", "Camera"),
                (1, "daylight", "Daylight"),
                (2, "cloudy", "Cloudy"),
            ),
        ),
        float_setting(
            module_id="temperature",
            module_label="white balance",
            setting_id="setting.temperature.temperature",
            capability_id="temperature.temperature",
            label="Temperature",
            action_path="iop/temperature/temperature",
            current=0.0,
            minimum=-4000.0,
            maximum=4000.0,
        ),
        float_setting(
            module_id="temperature",
            module_label="white balance",
            setting_id="setting.temperature.tint",
            capability_id="temperature.tint",
            label="Tint",
            action_path="iop/temperature/tint",
            current=0.0,
            minimum=-1.0,
            maximum=1.0,
        ),
        float_setting(
            module_id="filmicrgb",
            module_label="filmic rgb",
            setting_id="setting.filmic.white-relative-exposure",
            capability_id="filmic.white-relative-exposure",
            label="White relative exposure",
            action_path="iop/filmicrgb/white_relative_exposure",
            current=0.0,
            minimum=-5.0,
            maximum=5.0,
        ),
        float_setting(
            module_id="denoiseprofile",
            module_label="denoise (profiled)",
            setting_id="setting.denoiseprofile.chroma",
            capability_id="denoiseprofile.chroma",
            label="Chroma",
            action_path="iop/denoiseprofile/chroma",
            current=0.0,
            minimum=0.0,
            maximum=1.0,
        ),
        float_setting(
            module_id="denoiseprofile",
            module_label="denoise (profiled)",
            setting_id="setting.denoiseprofile.luma",
            capability_id="denoiseprofile.luma",
            label="Luma",
            action_path="iop/denoiseprofile/luma",
            current=0.0,
            minimum=0.0,
            maximum=1.0,
        ),
        float_setting(
            module_id="colorbalancergb",
            module_label="color balance rgb",
            setting_id="setting.colorbalancergb.global-saturation",
            capability_id="colorbalancergb.global-saturation",
            label="Global saturation",
            action_path="iop/colorbalancergb/global_saturation",
            current=0.0,
            minimum=-1.0,
            maximum=1.0,
        ),
        float_setting(
            module_id="colorbalancergb",
            module_label="color balance rgb",
            setting_id="setting.colorbalancergb.global-contrast",
            capability_id="colorbalancergb.global-contrast",
            label="Global contrast",
            action_path="iop/colorbalancergb/global_contrast",
            current=0.0,
            minimum=-1.0,
            maximum=1.0,
        ),
        float_setting(
            module_id="colorequal",
            module_label="color equalizer",
            setting_id="setting.colorequal.sat-blue",
            capability_id="colorequal.sat-blue",
            label="Blue saturation",
            action_path="iop/colorequal/sat_blue",
            current=0.0,
            minimum=-1.0,
            maximum=1.0,
        ),
        float_setting(
            module_id="primaries",
            module_label="rgb primaries",
            setting_id="setting.primaries.red-hue",
            capability_id="primaries.red-hue",
            label="Red hue",
            action_path="iop/primaries/red_hue",
            current=0.0,
            minimum=-3.14,
            maximum=3.14,
        ),
        float_setting(
            module_id="clipping",
            module_label="crop and rotate",
            setting_id="setting.clipping.cx",
            capability_id="clipping.cx",
            label="cx",
            action_path="iop/clipping/cx",
            current=0.0,
            minimum=0.0,
            maximum=1.0,
            supported_modes=("set",),
        ),
        float_setting(
            module_id="clipping",
            module_label="crop and rotate",
            setting_id="setting.clipping.cy",
            capability_id="clipping.cy",
            label="cy",
            action_path="iop/clipping/cy",
            current=0.0,
            minimum=0.0,
            maximum=1.0,
            supported_modes=("set",),
        ),
        float_setting(
            module_id="clipping",
            module_label="crop and rotate",
            setting_id="setting.clipping.cw",
            capability_id="clipping.cw",
            label="cw",
            action_path="iop/clipping/cw",
            current=1.0,
            minimum=0.0,
            maximum=1.0,
            supported_modes=("set",),
        ),
        float_setting(
            module_id="clipping",
            module_label="crop and rotate",
            setting_id="setting.clipping.ch",
            capability_id="clipping.ch",
            label="ch",
            action_path="iop/clipping/ch",
            current=1.0,
            minimum=0.0,
            maximum=1.0,
            supported_modes=("set",),
        ),
    ]


def history_entry(
    module_id: str, instance_name: str, iop_order: int
) -> dict[str, object]:
    return {
        "num": 0,
        "module": module_id,
        "enabled": True,
        "multiPriority": 0,
        "instanceName": instance_name,
        "iopOrder": iop_order,
    }


def float_setting(
    *,
    module_id: str,
    module_label: str,
    setting_id: str,
    capability_id: str,
    label: str,
    action_path: str,
    current: float,
    minimum: float,
    maximum: float,
    supported_modes: tuple[str, ...] = ("set", "delta"),
) -> dict[str, object]:
    return {
        "moduleId": module_id,
        "moduleLabel": module_label,
        "settingId": setting_id,
        "capabilityId": capability_id,
        "label": label,
        "actionPath": action_path,
        "kind": "set-float",
        "currentNumber": current,
        "supportedModes": list(supported_modes),
        "minNumber": minimum,
        "maxNumber": maximum,
        "defaultNumber": 0.0,
        "stepNumber": 0.01,
    }


def choice_setting(
    *,
    module_id: str,
    module_label: str,
    setting_id: str,
    capability_id: str,
    label: str,
    action_path: str,
    current_choice_id: str,
    current_choice_value: int,
    choices: tuple[tuple[int, str, str], ...],
) -> dict[str, object]:
    return {
        "moduleId": module_id,
        "moduleLabel": module_label,
        "settingId": setting_id,
        "capabilityId": capability_id,
        "label": label,
        "actionPath": action_path,
        "kind": "set-choice",
        "supportedModes": ["set"],
        "currentChoiceId": current_choice_id,
        "currentChoiceValue": current_choice_value,
        "choices": [
            {"choiceValue": value, "choiceId": choice_id, "label": choice_label}
            for value, choice_id, choice_label in choices
        ],
        "defaultChoiceValue": current_choice_value,
    }


def capability_from_setting(setting: dict[str, object]) -> dict[str, object]:
    capability = {
        "moduleId": setting["moduleId"],
        "moduleLabel": setting["moduleLabel"],
        "capabilityId": setting["capabilityId"],
        "label": setting["label"],
        "kind": setting["kind"],
        "targetType": "darktable-action",
        "actionPath": setting["actionPath"],
        "supportedModes": setting["supportedModes"],
    }
    if setting["kind"] == "set-float":
        capability["minNumber"] = setting["minNumber"]
        capability["maxNumber"] = setting["maxNumber"]
        capability["defaultNumber"] = setting["defaultNumber"]
        capability["stepNumber"] = setting["stepNumber"]
    if setting["kind"] == "set-choice":
        capability["choices"] = setting["choices"]
        capability["defaultChoiceValue"] = setting["defaultChoiceValue"]
    return capability
