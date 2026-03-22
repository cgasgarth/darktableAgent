from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

_ENVIRONMENT = Environment(
    loader=FileSystemLoader(str(_PROMPTS_DIR)),
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
    undefined=StrictUndefined,
)


def load_prompt_template(name: str) -> str:
    return _ENVIRONMENT.get_template(name).render().strip() + "\n"


def render_prompt_template(name: str, **context: object) -> str:
    return _ENVIRONMENT.get_template(name).render(**context).strip()
