from __future__ import annotations

import re

from server.codex_app_server import CodexTurnResult
from shared.protocol import AgentPlan, RequestEnvelope

_EXACT_EV_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*ev\b", re.IGNORECASE)


def _pick_exposure_setting(request: RequestEnvelope) -> tuple[str, str] | None:
    for setting in request.imageSnapshot.editableSettings:
        if setting.actionPath == "iop/exposure/exposure" and setting.kind == "set-float":
            return setting.actionPath, setting.settingId
    return None


def _infer_goal_delta(request: RequestEnvelope) -> float:
    text = f"{request.refinement.goalText}\n{request.message.text}"
    match = _EXACT_EV_RE.search(text)
    if match:
        return float(match.group(1))

    lowered = text.lower()
    if "darken" in lowered or "lower exposure" in lowered or "reduce exposure" in lowered:
        return -0.7

    return 0.7


class MockPlannerBridge:
    def plan(self, request: RequestEnvelope) -> CodexTurnResult:
        exposure_target = _pick_exposure_setting(request)
        if not exposure_target:
            plan = AgentPlan.model_validate(
                {
                    "assistantText": "Mock planner could not find an exposure control for this image.",
                    "continueRefining": False,
                    "operations": [],
                }
            )
            return CodexTurnResult(
                plan=plan,
                thread_id=f"mock-thread-{request.session.conversationId}",
                turn_id=f"mock-turn-{request.session.turnId}",
                raw_message=plan.model_dump_json(),
            )

        action_path, setting_id = exposure_target
        total_delta = _infer_goal_delta(request)

        if request.refinement.enabled:
            if request.refinement.passIndex == 1:
                delta = round(total_delta * 0.6, 2)
                continue_refining = request.refinement.maxPasses > 1
                assistant_text = f"Mock pass 1: starting with {delta:+.2f} EV."
            else:
                delta = round(total_delta - round(total_delta * 0.6, 2), 2)
                continue_refining = False
                assistant_text = f"Mock pass {request.refinement.passIndex}: finishing with {delta:+.2f} EV."
        else:
            delta = round(total_delta, 2)
            continue_refining = False
            assistant_text = f"Mock single-turn edit: applying {delta:+.2f} EV."

        plan = AgentPlan.model_validate(
            {
                "assistantText": assistant_text,
                "continueRefining": continue_refining,
                "operations": [
                    {
                        "operationId": f"mock-exposure-{request.refinement.passIndex}",
                        "sequence": 1,
                        "kind": "set-float",
                        "target": {
                            "type": "darktable-action",
                            "actionPath": action_path,
                            "settingId": setting_id,
                        },
                        "value": {"mode": "delta", "number": delta},
                        "reason": "Deterministic smoke-test mock response.",
                        "constraints": {
                            "onOutOfRange": "clamp",
                            "onRevisionMismatch": "fail",
                        },
                    }
                ],
            }
        )
        return CodexTurnResult(
            plan=plan,
            thread_id=f"mock-thread-{request.session.conversationId}",
            turn_id=f"mock-turn-{request.session.turnId}",
            raw_message=plan.model_dump_json(),
        )

    def cancel_request(
        self,
        *,
        request_id: str,
        app_session_id: str,
        image_session_id: str,
        conversation_id: str,
        turn_id: str,
    ) -> bool:
        del request_id
        del app_session_id
        del image_session_id
        del conversation_id
        del turn_id
        return False
