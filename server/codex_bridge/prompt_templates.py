from __future__ import annotations

from pathlib import Path
from string import Template

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt_template(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text().strip() + "\n"


def render_prompt_template(name: str, **context: object) -> str:
    template = Template((_PROMPTS_DIR / name).read_text())
    return template.safe_substitute(
        {key: "" if value is None else str(value) for key, value in context.items()}
    ).strip()
