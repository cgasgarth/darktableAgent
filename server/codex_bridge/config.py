from __future__ import annotations

import logging
import os
from pathlib import Path

from .prompt_templates import load_prompt_template

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
_DEFAULT_MODEL = os.environ.get("DARKTABLE_AGENT_CODEX_MODEL", "gpt-5.4-mini")
_FAST_MODE_MODEL = os.environ.get(
    "DARKTABLE_AGENT_CODEX_FAST_MODE_MODEL", "gpt-5.4-mini"
)
_FAST_MODE_REASONING_EFFORT = os.environ.get(
    "DARKTABLE_AGENT_CODEX_FAST_MODE_REASONING_EFFORT", "medium"
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
_TOOL_GET_PLAYBOOK = "get_playbook"
_TOOL_APPLY_OPERATIONS = "apply_operations"
_WHITE_BALANCE_ACTION_PATH_PREFIXES = ("iop/temperature/",)

_THREAD_DEVELOPER_INSTRUCTIONS = load_prompt_template(
    "thread_developer_instructions.txt"
)
