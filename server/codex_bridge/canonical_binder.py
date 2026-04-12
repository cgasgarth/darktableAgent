from __future__ import annotations

from dataclasses import dataclass

from shared.canonical_plan import CanonicalEditAction
from shared.protocol import AgentPlan, EditableSetting, RequestEnvelope

from .config import logger


@dataclass(frozen=True, slots=True)
class _BindingResult:
    operations: list[dict[str, object]]
    failures: list[str]


def bind_canonical_plan(request: RequestEnvelope, plan: AgentPlan) -> AgentPlan:
    canonical_actions = plan.canonicalActions or []
    if not canonical_actions:
        return plan

    result = bind_canonical_actions(
        request.imageSnapshot.editableSettings, canonical_actions
    )
    bound_operations = result.operations
    failures = result.failures

    combined_operations = [
        operation.model_dump(mode="json") for operation in plan.operations
    ] + bound_operations

    normalized_operations = _normalize_operations_with_unique_ids(combined_operations)

    assistant_text = plan.assistantText
    if failures:
        assistant_text = (
            assistant_text.rstrip() + "\n\nBinding notes: " + "; ".join(failures)
        )
        logger.info(
            "canonical_binding_partial_failure",
            extra={
                "structured": {
                    "requestId": request.requestId,
                    "conversationId": request.session.conversationId,
                    "failures": failures,
                }
            },
        )

    return AgentPlan.model_validate(
        {
            "assistantText": assistant_text,
            "continueRefining": plan.continueRefining,
            "operations": normalized_operations,
            "canonicalActions": [
                action.model_dump(mode="json") for action in canonical_actions
            ],
        }
    )


def bind_canonical_actions(
    settings: list[EditableSetting],
    canonical_actions: list[CanonicalEditAction],
) -> _BindingResult:
    bound_operations: list[dict[str, object]] = []
    failures: list[str] = []

    for action in canonical_actions:
        result = _bind_action(settings, action)
        bound_operations.extend(result.operations)
        failures.extend(result.failures)

    return _BindingResult(
        _normalize_operations_with_unique_ids(bound_operations), failures
    )


def _normalize_operations_with_unique_ids(
    operations: list[dict[str, object]],
) -> list[dict[str, object]]:
    normalized_operations: list[dict[str, object]] = []
    seen_operation_ids: set[str] = set()

    for index, operation in enumerate(operations, start=1):
        operation_copy = dict(operation)
        candidate_operation_id = str(
            operation_copy.get("operationId") or f"canonical-op-{index}"
        )
        operation_id = candidate_operation_id
        duplicate_index = 2
        while operation_id in seen_operation_ids:
            operation_id = f"{candidate_operation_id}-{duplicate_index}"
            duplicate_index += 1
        seen_operation_ids.add(operation_id)
        operation_copy["operationId"] = operation_id
        operation_copy["sequence"] = index
        normalized_operations.append(operation_copy)

    return normalized_operations


def _bind_action(
    settings: list[EditableSetting], action: CanonicalEditAction
) -> _BindingResult:
    if action.action == "adjust-exposure":
        return _bind_exposure(settings, action)
    if action.action == "adjust-white-balance":
        return _bind_white_balance(settings, action)
    if action.action == "recover-highlights":
        return _bind_highlights(settings, action)
    if action.action == "reduce-noise":
        return _bind_noise(settings, action)
    if action.action == "grade-color":
        return _bind_grade(settings, action)
    if action.action == "crop-normalized":
        return _bind_crop(settings, action)
    if action.action == "crop-to-bounding-box":
        return _bind_crop_box(settings, action)
    return _BindingResult([], [f"unsupported canonical action {action.action}"])


def _bind_exposure(
    settings: list[EditableSetting], action: CanonicalEditAction
) -> _BindingResult:
    setting = _find_setting(
        settings,
        kind="set-float",
        exact_action_paths=("iop/exposure/exposure",),
        label_keywords=("exposure",),
    )
    if setting is None or action.exposureEv is None:
        return _BindingResult(
            [], ["adjust-exposure could not find an exposure control"]
        )
    return _BindingResult(
        [_float_operation(setting, action.exposureEv, action.rationale)],
        [],
    )


def _bind_white_balance(
    settings: list[EditableSetting], action: CanonicalEditAction
) -> _BindingResult:
    operations: list[dict[str, object]] = []
    failures: list[str] = []

    if action.presetChoiceId is not None:
        preset_setting = _find_setting(
            settings,
            kind="set-choice",
            exact_action_paths=("iop/temperature/preset",),
            label_keywords=("preset",),
        )
        if preset_setting is None:
            failures.append("adjust-white-balance could not find a preset control")
        else:
            preset_operation = _choice_operation(
                preset_setting,
                action.presetChoiceId,
                action.rationale,
            )
            if preset_operation is None:
                failures.append(
                    f"adjust-white-balance could not bind preset {action.presetChoiceId}"
                )
            else:
                operations.append(preset_operation)

    if action.temperatureDelta is not None:
        temperature_setting = _find_setting(
            settings,
            kind="set-float",
            exact_action_paths=("iop/temperature/temperature",),
            label_keywords=("temperature",),
        )
        if temperature_setting is None:
            failures.append("adjust-white-balance could not find a temperature control")
        else:
            operations.append(
                _float_operation(
                    temperature_setting,
                    action.temperatureDelta,
                    action.rationale,
                )
            )

    if action.tintDelta is not None:
        tint_setting = _find_setting(
            settings,
            kind="set-float",
            exact_action_paths=("iop/temperature/tint",),
            label_keywords=("tint",),
        )
        if tint_setting is None:
            failures.append("adjust-white-balance could not find a tint control")
        else:
            operations.append(
                _float_operation(tint_setting, action.tintDelta, action.rationale)
            )

    return _BindingResult(operations, failures)


def _bind_highlights(
    settings: list[EditableSetting], action: CanonicalEditAction
) -> _BindingResult:
    delta_map = {"low": -0.25, "medium": -0.5, "high": -0.75}
    setting = _find_setting(
        settings,
        kind="set-float",
        exact_action_paths=(
            "iop/filmicrgb/white_relative_exposure",
            "iop/toneequalizer/highlights",
        ),
        module_ids=("filmicrgb", "toneequalizer"),
        action_keywords=("highlight", "white_relative_exposure"),
        label_keywords=("highlight", "white relative exposure"),
    )
    if setting is None or action.strength is None:
        return _BindingResult(
            [], ["recover-highlights could not find a highlight control"]
        )
    return _BindingResult(
        [_float_operation(setting, delta_map[action.strength], action.rationale)],
        [],
    )


def _bind_noise(
    settings: list[EditableSetting], action: CanonicalEditAction
) -> _BindingResult:
    delta_map = {"low": 0.1, "medium": 0.2, "high": 0.35}
    assert action.strength is not None
    amount = delta_map[action.strength]
    noise_type = action.noiseType or "both"
    operations: list[dict[str, object]] = []
    failures: list[str] = []
    requested_targets = (
        ("chroma",)
        if noise_type == "chroma"
        else ("luma",)
        if noise_type == "luma"
        else ("chroma", "luma")
    )
    for channel in requested_targets:
        setting = _find_setting(
            settings,
            kind="set-float",
            exact_action_paths=(f"iop/denoiseprofile/{channel}",),
            module_ids=("denoiseprofile",),
            action_keywords=(channel, "denoise"),
            label_keywords=(channel, "noise"),
        )
        if setting is None:
            failures.append(f"reduce-noise could not find a {channel} noise control")
            continue
        operations.append(_float_operation(setting, amount, action.rationale))
    return _BindingResult(operations, failures)


def _bind_grade(
    settings: list[EditableSetting], action: CanonicalEditAction
) -> _BindingResult:
    if action.target is None or action.amount is None:
        return _BindingResult([], ["grade-color is missing target or amount"])

    match action.target:
        case "global-saturation":
            setting = _find_setting(
                settings,
                kind="set-float",
                exact_action_paths=(
                    "iop/colorbalancergb/global_saturation",
                    "iop/colorequal/sat_global",
                ),
                action_keywords=("saturation",),
                label_keywords=("saturation",),
            )
        case "blue-saturation":
            setting = _find_setting(
                settings,
                kind="set-float",
                exact_action_paths=("iop/colorequal/sat_blue",),
                module_ids=("colorequal",),
                action_keywords=("blue", "saturation"),
                label_keywords=("blue", "saturation"),
            )
        case "red-hue":
            setting = _find_setting(
                settings,
                kind="set-float",
                exact_action_paths=("iop/primaries/red_hue",),
                module_ids=("primaries",),
                action_keywords=("red", "hue"),
                label_keywords=("red", "hue"),
            )
        case "global-contrast":
            setting = _find_setting(
                settings,
                kind="set-float",
                exact_action_paths=("iop/colorbalancergb/global_contrast",),
                action_keywords=("contrast",),
                label_keywords=("contrast",),
            )
        case _:
            setting = None

    if setting is None:
        return _BindingResult(
            [], [f"grade-color could not find a control for {action.target}"]
        )
    return _BindingResult(
        [_float_operation(setting, action.amount, action.rationale)],
        [],
    )


def _bind_crop(
    settings: list[EditableSetting], action: CanonicalEditAction
) -> _BindingResult:
    assert action.left is not None
    assert action.top is not None
    assert action.right is not None
    assert action.bottom is not None
    axis_values = {
        "cx": action.left,
        "cy": action.top,
        "cw": action.right,
        "ch": action.bottom,
    }
    return _bind_crop_axis_values(
        settings,
        axis_values,
        rationale=action.rationale,
        failure_prefix="crop-normalized",
    )


def _bind_crop_box(
    settings: list[EditableSetting], action: CanonicalEditAction
) -> _BindingResult:
    assert action.boxLeft is not None
    assert action.boxTop is not None
    assert action.boxWidth is not None
    assert action.boxHeight is not None
    padding_ratio = action.paddingRatio or 0.0

    left = _clamp(action.boxLeft)
    top = _clamp(action.boxTop)
    right = _clamp(action.boxLeft + action.boxWidth)
    bottom = _clamp(action.boxTop + action.boxHeight)
    pad_x = action.boxWidth * padding_ratio
    pad_y = action.boxHeight * padding_ratio

    axis_values = {
        "cx": _clamp(left - pad_x),
        "cy": _clamp(top - pad_y),
        "cw": _clamp(right + pad_x),
        "ch": _clamp(bottom + pad_y),
    }
    return _bind_crop_axis_values(
        settings,
        axis_values,
        rationale=action.rationale,
        failure_prefix="crop-to-bounding-box",
    )


def _bind_crop_axis_values(
    settings: list[EditableSetting],
    axis_values: dict[str, float],
    *,
    rationale: str | None,
    failure_prefix: str,
) -> _BindingResult:
    operations: list[dict[str, object]] = []
    failures: list[str] = []
    for axis, value in axis_values.items():
        setting = _find_setting(
            settings,
            kind="set-float",
            exact_action_paths=(f"iop/clipping/{axis}", f"iop/crop/{axis}"),
            module_ids=("clipping", "crop"),
            action_keywords=(axis,),
            label_keywords=(axis,),
        )
        if setting is None:
            failures.append(f"{failure_prefix} could not find a {axis} control")
            continue
        operations.append(_float_operation(setting, value, rationale, prefer_set=True))
    return _BindingResult(operations, failures)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _find_setting(
    settings: list[EditableSetting],
    *,
    kind: str,
    exact_action_paths: tuple[str, ...] = (),
    module_ids: tuple[str, ...] = (),
    action_keywords: tuple[str, ...] = (),
    label_keywords: tuple[str, ...] = (),
) -> EditableSetting | None:
    candidates: list[tuple[int, EditableSetting]] = []
    for setting in settings:
        if setting.kind != kind:
            continue
        score = 0
        action_path = setting.actionPath.lower()
        label = setting.label.lower()
        module_id = setting.moduleId.lower()
        if setting.actionPath in exact_action_paths:
            score += 100
        if module_id in module_ids:
            score += 20
        score += sum(8 for keyword in action_keywords if keyword in action_path)
        score += sum(6 for keyword in label_keywords if keyword in label)
        if score > 0:
            candidates.append((score, setting))

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            -item[0],
            item[1].moduleId,
            item[1].actionPath,
            item[1].settingId,
        )
    )
    return candidates[0][1]


def _float_operation(
    setting: EditableSetting,
    amount: float,
    rationale: str | None,
    *,
    prefer_set: bool = False,
) -> dict[str, object]:
    if not prefer_set and "delta" in setting.supportedModes:
        mode = "delta"
        number = amount
    else:
        current_number = setting.currentNumber
        if current_number is None:
            current_number = setting.defaultNumber or 0.0
        mode = "set"
        number = float(current_number) + amount if not prefer_set else amount

    return {
        "operationId": f"bind-{setting.settingId}",
        "sequence": 1,
        "kind": "set-float",
        "target": {
            "type": "darktable-action",
            "actionPath": setting.actionPath,
            "settingId": setting.settingId,
        },
        "value": {"mode": mode, "number": number},
        "reason": rationale,
        "constraints": {"onOutOfRange": "clamp", "onRevisionMismatch": "fail"},
    }


def _choice_operation(
    setting: EditableSetting,
    choice_id: str,
    rationale: str | None,
) -> dict[str, object] | None:
    choices = setting.choices or []
    for choice in choices:
        if choice.choiceId != choice_id:
            continue
        return {
            "operationId": f"bind-{setting.settingId}",
            "sequence": 1,
            "kind": "set-choice",
            "target": {
                "type": "darktable-action",
                "actionPath": setting.actionPath,
                "settingId": setting.settingId,
            },
            "value": {
                "mode": "set",
                "choiceValue": choice.choiceValue,
                "choiceId": choice.choiceId,
            },
            "reason": rationale,
            "constraints": {
                "onOutOfRange": "clamp",
                "onRevisionMismatch": "fail",
            },
        }
    return None
