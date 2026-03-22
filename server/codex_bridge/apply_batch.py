from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from shared.canonical_plan import CanonicalEditAction

from .canonical_binder import bind_canonical_actions
from .models import TurnContext


@dataclass(frozen=True, slots=True)
class PreparedApplyBatch:
    normalized_batch: list[dict[str, Any]]
    render_warnings: list[str]


def prepare_apply_batch(
    context: TurnContext,
    arguments: dict[str, Any],
    *,
    normalize_operation: Callable[
        [dict[str, Any], int], tuple[dict[str, Any], str | None]
    ],
) -> tuple[PreparedApplyBatch | None, str | None]:
    raw_operations = arguments.get("operations")
    raw_canonical_actions = arguments.get("canonicalActions")
    if raw_operations is None:
        raw_operations = []
    if raw_canonical_actions is None:
        raw_canonical_actions = []
    if not isinstance(raw_operations, list):
        return None, "apply_operations operations must be an array."
    if not isinstance(raw_canonical_actions, list):
        return None, "apply_operations canonicalActions must be an array."
    if not raw_operations and not raw_canonical_actions:
        return None, "apply_operations requires operations and/or canonicalActions."
    if raw_operations and raw_canonical_actions:
        return (
            None,
            "apply_operations accepts raw operations or canonicalActions, not both in the same call.",
        )

    if raw_canonical_actions:
        return _prepare_canonical_batch(context, raw_canonical_actions)
    return _prepare_raw_batch(context, raw_operations, normalize_operation)


def _prepare_canonical_batch(
    context: TurnContext, raw_canonical_actions: list[Any]
) -> tuple[PreparedApplyBatch | None, str | None]:
    canonical_actions: list[CanonicalEditAction] = []
    for raw_action in raw_canonical_actions:
        try:
            canonical_actions.append(CanonicalEditAction.model_validate(raw_action))
        except Exception as exc:
            return None, f"canonicalActions entry failed schema validation: {exc}"

    binding_result = bind_canonical_actions(
        list(context.base_request.imageSnapshot.editableSettings),
        canonical_actions,
    )
    if binding_result.failures and not binding_result.operations:
        return None, "; ".join(binding_result.failures)
    if not binding_result.operations:
        return (
            None,
            "apply_operations could not bind any supported operations from canonicalActions.",
        )
    warnings = []
    if binding_result.failures:
        warnings.append("Binding notes: " + "; ".join(binding_result.failures))
    return PreparedApplyBatch(binding_result.operations, warnings), None


def _prepare_raw_batch(
    context: TurnContext,
    raw_operations: list[Any],
    normalize_operation: Callable[
        [dict[str, Any], int], tuple[dict[str, Any], str | None]
    ],
) -> tuple[PreparedApplyBatch | None, str | None]:
    normalized_batch: list[dict[str, Any]] = []
    for index, raw_operation in enumerate(raw_operations):
        if not isinstance(raw_operation, dict):
            return None, "Every apply_operations entry must be an object."
        normalized_operation, error = normalize_operation(
            raw_operation,
            context.next_operation_sequence + index,
        )
        if error:
            return None, error
        normalized_batch.append(normalized_operation)
    return PreparedApplyBatch(normalized_batch, []), None
