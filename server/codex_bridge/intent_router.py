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
    selection_hint: str

    def to_payload(self) -> dict[str, str]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "category": self.category,
            "selectionHint": self.selection_hint,
        }


def _playbook_title(playbook_id: str) -> str:
    return playbook_id.split("/")[-1].removesuffix(".txt").replace("-", " ")


def _playbook_category(playbook_id: str) -> str:
    parts = Path(playbook_id).parts
    return parts[-2].replace("_", "-") if len(parts) >= 2 else "general"


def _playbook_summary(playbook_id: str) -> str:
    rendered = render_prompt_template(playbook_id)
    return rendered.splitlines()[0].strip() if rendered else ""


def _playbook_selection_hint(playbook_id: str) -> str:
    hints = {
        "playbooks/photo_type/general.txt": (
            "Use when no more specific photo type clearly fits the scene."
        ),
        "playbooks/photo_type/landscape.txt": (
            "Use when the scene is primarily outdoor scenery and sky, distance, or tonal separation drive the edit."
        ),
        "playbooks/photo_type/night.txt": (
            "Use when the image is genuinely low-light or high-ISO and noise or light-source control is central."
        ),
        "playbooks/photo_type/portrait.txt": (
            "Use when a person is the main subject and skin tone or facial rendering is important."
        ),
        "playbooks/photo_type/product.txt": (
            "Use when the subject is a product and clean edges, neutral color, or commercial clarity matter most."
        ),
        "playbooks/style/bw-documentary.txt": (
            "Use when the requested finish is black-and-white and documentary rather than graphic or highly stylized."
        ),
        "playbooks/style/cinematic-muted.txt": (
            "Use when the user wants a restrained cinematic grade with reduced saturation and controlled contrast."
        ),
        "playbooks/style/color-accurate.txt": (
            "Use when accurate neutral color is more important than mood, especially for commercial or brand-sensitive work."
        ),
        "playbooks/style/natural-clean.txt": (
            "Use when the goal is a believable polished finish without a strong stylized look."
        ),
        "playbooks/style/noise-aware.txt": (
            "Use when visible noise or high-ISO risk should constrain contrast, shadow lifting, or detail moves."
        ),
    }
    return hints.get(
        playbook_id,
        "Use only when this playbook clearly matches the scene or requested finish.",
    )


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
                selection_hint=_playbook_selection_hint(playbook_id),
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
        "selectionHint": _playbook_selection_hint(playbook_id),
        "body": render_prompt_template(playbook_id),
    }
