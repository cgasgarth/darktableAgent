#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

MAX_LINES = 600
ROOT = Path(__file__).resolve().parent.parent
INCLUDE_DIRS = (ROOT / "server", ROOT / "shared")


def should_check(path: Path) -> bool:
    if path.suffix != ".py":
        return False
    relative = path.relative_to(ROOT)
    relative_text = str(relative)
    if relative_text.startswith("server/tests/"):
        return False
    return not any(part in path.parts for part in {".venv", "build"})


def main() -> int:
    violations: list[tuple[int, Path]] = []
    for directory in INCLUDE_DIRS:
        for path in sorted(directory.rglob("*.py")):
            if not should_check(path):
                continue
            line_count = len(path.read_text().splitlines())
            if line_count > MAX_LINES:
                violations.append((line_count, path.relative_to(ROOT)))

    if not violations:
        return 0

    print(
        f"Python source files must stay at or below {MAX_LINES} lines:", file=sys.stderr
    )
    for line_count, relative_path in violations:
        print(f"  {line_count:4d} {relative_path}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
