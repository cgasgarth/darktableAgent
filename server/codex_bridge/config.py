from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("darktable_agent.codex")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CLIENT_INFO = {
    "name": "darktableAgent",
    "title": "darktableAgent",
    "version": "0.1.0",
}
_DEFAULT_COMMAND = [
    "codex",
    "app-server",
    "-c",
    "mcp_servers.chrome-devtools.enabled=false",
    "--listen",
    "stdio://",
]
_DEFAULT_TIMEOUT_SECONDS = float(
    os.environ.get("DARKTABLE_AGENT_CODEX_TIMEOUT_SECONDS", "600")
)
_DEFAULT_PERSONALITY = os.environ.get("DARKTABLE_AGENT_CODEX_PERSONALITY", "pragmatic")
_DEFAULT_REASONING_EFFORT = os.environ.get(
    "DARKTABLE_AGENT_CODEX_REASONING_EFFORT", "high"
)
_DEFAULT_MODEL = os.environ.get("DARKTABLE_AGENT_CODEX_MODEL", "gpt-5.3-codex")
_FAST_MODE_MODEL = os.environ.get(
    "DARKTABLE_AGENT_CODEX_FAST_MODE_MODEL", "gpt-5.3-codex"
)
_FAST_MODE_REASONING_EFFORT = os.environ.get(
    "DARKTABLE_AGENT_CODEX_FAST_MODE_REASONING_EFFORT", "low"
)
_DEFAULT_SANDBOX = os.environ.get("DARKTABLE_AGENT_CODEX_SANDBOX", "read-only")
_DEFAULT_APPROVAL_POLICY = "never"
_DEFAULT_HISTOGRAM_BINS = int(os.environ.get("DARKTABLE_AGENT_HISTOGRAM_BINS", "64"))
_DEFAULT_MAX_IDLE_SECONDS = float(
    os.environ.get("DARKTABLE_AGENT_CODEX_MAX_IDLE_SECONDS", "120")
)
_DEFAULT_MAX_CONSECUTIVE_READ_ONLY_TOOL_CALLS = int(
    os.environ.get("DARKTABLE_AGENT_MAX_CONSECUTIVE_READ_ONLY_TOOL_CALLS", "4")
)
_DEFAULT_MAX_TOOL_CALLS_WITHOUT_APPLY = int(
    os.environ.get("DARKTABLE_AGENT_MAX_TOOL_CALLS_WITHOUT_APPLY", "3")
)
_TOOL_GET_IMAGE_STATE = "get_image_state"
_TOOL_GET_PREVIEW_IMAGE = "get_preview_image"
_TOOL_APPLY_OPERATIONS = "apply_operations"
_WHITE_BALANCE_ACTION_PATH_PREFIXES = ("iop/temperature/",)

_THREAD_DEVELOPER_INSTRUCTIONS = """You are darktableAgent, a structured editing planner for darktable.

Context and tool usage:
- live mode turn input already includes the current preview image
- turn input already includes the current editable settings and luma histogram snapshot
- call `get_image_state` only when you need refreshed exact state after edits or when state may have changed
- `apply_operations` returns the refreshed preview image automatically after successful edits
- call `get_preview_image` only when you need another visual check without applying new edits
- in live agent runs (`mode=multi-turn`), call `apply_operations` to apply edits iteratively
Return exactly one JSON object matching the output schema after tool calls.

Use preview as primary visual context. Use histogram + editable settings as constraints.
Only emit operations targeting provided settingId/actionPath pairs. Never invent IDs or paths.
Keep edits coherent, conservative, and executable.
If user intent is broad, infer a reasonable plan from the visible image instead of asking for more specificity.
Prefer advanced color controls (`colorequal`, `colorbalancergb`, `primaries`) when available for nuanced color work.
White-balance controls (`iop/temperature/*`) are available. Respect supportedModes, bounds, and exact settingId/actionPath pairs.
When batching multiple white-balance edits, prefer stable ordering: preset/choice first, then finetune, then temperature/tint, then channel multipliers.

Refinement rules:
- Always optimize toward refinement.goalText.
- In single-turn mode, return operations in the final JSON; do not use `apply_operations`.
- In multi-turn mode, perform iterative tool calls within this same run:
  1) gather any missing context with read-only tools only when needed
  2) apply edits with `apply_operations` early (do not spend many calls only inspecting)
  3) re-check state/preview after edits as needed and continue until satisfied or tool budget is exhausted
- In multi-turn mode, the final JSON should summarize the run and typically return empty operations because edits were already applied via `apply_operations`.
- In multi-turn mode, continueRefining must be false in the final JSON.

Value rules:
- Use mode `delta` only for set-float when supported.
- Use mode `set` for set-choice and set-bool.
- set-choice uses value.choiceValue (and choiceId when known).
- set-bool uses value.boolValue.
- Always include the exact target.settingId from editable settings.
"""
