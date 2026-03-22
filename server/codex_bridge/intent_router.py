from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .prompt_templates import render_prompt_template

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_PLAYBOOKS_DIR = _PROMPTS_DIR / "playbooks"


@dataclass(frozen=True, slots=True)
class PlaybookEntry:
    id: str
    title: str
    summary: str
    category: str

    def to_payload(self) -> dict[str, str]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "category": self.category,
        }


def _playbook_title(playbook_id: str) -> str:
    return playbook_id.split("/")[-1].removesuffix(".txt").replace("-", " ")


def _playbook_category(playbook_id: str) -> str:
    parts = Path(playbook_id).parts
    return parts[-2].replace("_", "-") if len(parts) >= 2 else "general"


def _playbook_summary(playbook_id: str) -> str:
    rendered = render_prompt_template(playbook_id)
    return rendered.splitlines()[0].strip() if rendered else ""


def list_playbooks() -> list[PlaybookEntry]:
    entries: list[PlaybookEntry] = []
    for path in sorted(_PLAYBOOKS_DIR.rglob("*.txt")):
        playbook_id = path.relative_to(_PROMPTS_DIR).as_posix()
        entries.append(
            PlaybookEntry(
                id=playbook_id,
                title=_playbook_title(playbook_id),
                summary=_playbook_summary(playbook_id),
                category=_playbook_category(playbook_id),
            )
        )
    return entries


def playbook_catalog_payload() -> list[dict[str, str]]:
    return [entry.to_payload() for entry in list_playbooks()]


def load_playbook(playbook_id: str) -> dict[str, str]:
    available_ids = {entry.id for entry in list_playbooks()}
    if playbook_id not in available_ids:
        available = ", ".join(sorted(available_ids))
        raise ValueError(
            f"Unknown playbook '{playbook_id}'. Available playbooks: {available}"
        )
    return {
        "id": playbook_id,
        "title": _playbook_title(playbook_id),
        "summary": _playbook_summary(playbook_id),
        "body": render_prompt_template(playbook_id),
    }
