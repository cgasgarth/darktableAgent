from pathlib import Path


def test_python_source_files_stay_under_600_lines() -> None:
    root = Path(__file__).resolve().parents[2]
    source_dirs = (root / "server", root / "shared")
    violations: list[str] = []

    for directory in source_dirs:
        for path in sorted(directory.rglob("*.py")):
            relative = path.relative_to(root)
            if str(relative).startswith("server/tests/"):
                continue
            if any(part in {".venv", "build"} for part in path.parts):
                continue
            line_count = len(path.read_text().splitlines())
            if line_count > 600:
                violations.append(f"{relative} ({line_count} lines)")

    assert not violations, "Python source files over 600 lines: " + ", ".join(violations)
