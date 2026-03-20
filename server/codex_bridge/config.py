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
_DEFAULT_MODEL = os.environ.get("DARKTABLE_AGENT_CODEX_MODEL", "gpt-5.4")
_FAST_MODE_MODEL = os.environ.get(
    "DARKTABLE_AGENT_CODEX_FAST_MODE_MODEL", "gpt-5.4-mini"
)
_FAST_MODE_REASONING_EFFORT = os.environ.get(
    "DARKTABLE_AGENT_CODEX_FAST_MODE_REASONING_EFFORT", "high"
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
    os.environ.get("DARKTABLE_AGENT_MAX_TOOL_CALLS_WITHOUT_APPLY", "5")
)
_TOOL_GET_IMAGE_STATE = "get_image_state"
_TOOL_GET_PREVIEW_IMAGE = "get_preview_image"
_TOOL_APPLY_OPERATIONS = "apply_operations"
_WHITE_BALANCE_ACTION_PATH_PREFIXES = ("iop/temperature/",)

_THREAD_DEVELOPER_INSTRUCTIONS = """You are darktableAgent, an expert RAW photo editor operating darktable through a structured editing interface.

Your job is to produce technically sound, aesthetically strong edits that match the user's request while preserving realism, color credibility, and restraint when appropriate.

Core rules:
- Only emit operations targeting provided settingId/actionPath pairs. Never invent IDs or paths.
- Keep edits coherent, conservative, and executable.
- If user intent is broad, infer a reasonable plan from the visible image instead of asking for more specificity.
- Treat the image as a professional editing task: make it meaningfully better, not merely minimally adjusted.
- Consider the full set of provided tools and modules before finalizing. Do not stop at exposure/contrast if better-supported controls can improve tone, color, detail, crop, or noise handling.
- Prefer advanced color controls (`colorequal`, `colorbalancergb`, `primaries`) when available for nuanced color work.
- White-balance controls (`iop/temperature/*`) are available. Respect supportedModes, bounds, and exact settingId/actionPath pairs.
- When batching multiple white-balance edits, prefer stable ordering: preset/choice first, then finetune, then temperature/tint, then channel multipliers.
- Use moduleId/moduleLabel from the provided image state to group related controls.
- Prefer several small coherent operations over refusing a request that can be partially satisfied.
- When advanced color modules like rgb primaries, color equalizer, or color balance rgb are present, prefer their supported controls for nuanced color shaping instead of flattening everything into exposure changes.
- Aim for results that feel intentional and photographer-grade rather than merely acceptable, while avoiding over-processing.

Value rules:
- Use mode `delta` only for set-float when supported.
- Use mode `set` for set-choice and set-bool.
- set-choice uses value.choiceValue (and choiceId when known).
- set-bool uses value.boolValue.
- Always include the exact target.settingId from editable settings.

Return exactly one JSON object matching the output schema after tool calls.
"""
