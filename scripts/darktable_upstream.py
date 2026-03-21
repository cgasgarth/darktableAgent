#!/usr/bin/env python3
from __future__ import annotations

import argparse
import filecmp
import fnmatch
import json
import shutil
import sys
import tempfile
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "darktable-upstream.json"


@dataclass(frozen=True)
class UpstreamConfig:
    repository: str
    original_base_tag: str
    tracked_tag: str
    compare_root: Path
    ignore_globs: tuple[str, ...]
    expected_modified_files: frozenset[str]
    expected_extra_globs: tuple[str, ...]


@dataclass(frozen=True)
class CompareReport:
    tag: str
    modified_files: tuple[str, ...]
    missing_files: tuple[str, ...]
    extra_files: tuple[str, ...]
    unexpected_modified_files: tuple[str, ...]
    unexpected_missing_files: tuple[str, ...]
    unexpected_extra_files: tuple[str, ...]

    @property
    def is_clean(self) -> bool:
        return not (
            self.unexpected_modified_files
            or self.unexpected_missing_files
            or self.unexpected_extra_files
        )


def load_config() -> UpstreamConfig:
    payload = json.loads(CONFIG_PATH.read_text())
    return UpstreamConfig(
        repository=str(payload["repository"]),
        original_base_tag=str(payload["originalBaseTag"]),
        tracked_tag=str(payload["trackedTag"]),
        compare_root=REPO_ROOT / str(payload["compareRoot"]),
        ignore_globs=tuple(str(value) for value in payload.get("ignoreGlobs", [])),
        expected_modified_files=frozenset(
            str(value) for value in payload.get("expectedModifiedFiles", [])
        ),
        expected_extra_globs=tuple(
            str(value) for value in payload.get("expectedExtraGlobs", [])
        ),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--tag", help="Override the tracked upstream tag")
    status_parser.add_argument(
        "--json", action="store_true", help="Print the report as JSON"
    )

    return parser.parse_args()


def log_step(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def build_archive_url(repository: str, tag: str) -> str:
    repository_root = repository.removesuffix(".git").rstrip("/")
    if not repository_root.startswith("https://github.com/"):
        raise ValueError(f"Unsupported upstream repository: {repository}")
    owner_repo = repository_root.removeprefix("https://github.com/")
    return f"https://codeload.github.com/{owner_repo}/tar.gz/refs/tags/{tag}"


def download_and_extract_archive(repository: str, tag: str, destination: Path) -> Path:
    archive_url = build_archive_url(repository, tag)
    archive_path = destination / "upstream.tar.gz"
    log_step(f"Downloading {tag} source archive...")
    with urllib.request.urlopen(archive_url, timeout=120) as response:
        archive_path.write_bytes(response.read())

    log_step("Extracting upstream archive...")
    with tarfile.open(archive_path, mode="r:gz") as archive:
        archive.extractall(path=destination)

    extracted_roots = [path for path in destination.iterdir() if path.is_dir()]
    if len(extracted_roots) != 1:
        raise ValueError("Could not determine extracted upstream archive root")
    return extracted_roots[0]


def should_ignore(relative_path: Path, config: UpstreamConfig) -> bool:
    relative_text = relative_path.as_posix()
    return any(
        fnmatch.fnmatch(relative_text, pattern) for pattern in config.ignore_globs
    )


def iter_files(root: Path, config: UpstreamConfig) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_path = path.relative_to(root)
        if should_ignore(relative_path, config):
            continue
        files.append(relative_path)
    return sorted(files)


def matches_expected_extra(relative_text: str, config: UpstreamConfig) -> bool:
    return any(
        fnmatch.fnmatch(relative_text, pattern)
        for pattern in config.expected_extra_globs
    )


def compare_against_upstream(config: UpstreamConfig, tag: str) -> CompareReport:
    temp_dir = Path(tempfile.mkdtemp(prefix="darktable-upstream-"))
    try:
        upstream_root = download_and_extract_archive(config.repository, tag, temp_dir)
        log_step("Comparing local darktable tree to upstream...")

        upstream_files = iter_files(upstream_root, config)
        local_files = iter_files(config.compare_root, config)
        upstream_set = set(upstream_files)
        local_set = set(local_files)

        modified_files: list[str] = []
        missing_files: list[str] = []
        extra_files: list[str] = []

        for relative_path in upstream_files:
            local_path = config.compare_root / relative_path
            upstream_path = upstream_root / relative_path
            relative_text = relative_path.as_posix()
            if not local_path.exists():
                missing_files.append(relative_text)
                continue
            if not filecmp.cmp(upstream_path, local_path, shallow=False):
                modified_files.append(relative_text)

        for relative_path in sorted(local_set - upstream_set):
            extra_files.append(relative_path.as_posix())

        unexpected_modified_files = sorted(
            relative_text
            for relative_text in modified_files
            if relative_text not in config.expected_modified_files
        )
        unexpected_extra_files = sorted(
            relative_text
            for relative_text in extra_files
            if not matches_expected_extra(relative_text, config)
        )

        return CompareReport(
            tag=tag,
            modified_files=tuple(modified_files),
            missing_files=tuple(missing_files),
            extra_files=tuple(extra_files),
            unexpected_modified_files=tuple(unexpected_modified_files),
            unexpected_missing_files=tuple(sorted(missing_files)),
            unexpected_extra_files=tuple(unexpected_extra_files),
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def print_text_report(config: UpstreamConfig, report: CompareReport) -> None:
    print(f"Original base tag: {config.original_base_tag}")
    print(f"Tracked current-match tag: {config.tracked_tag}")
    print(f"Compared tag: {report.tag}")
    print(f"Modified upstream files: {len(report.modified_files)}")
    print(f"Missing upstream files: {len(report.missing_files)}")
    print(f"Local-only files: {len(report.extra_files)}")
    print(
        "Status: "
        + (
            "clean against the tracked downstream patch surface"
            if report.is_clean
            else "unexpected drift detected"
        )
    )

    if report.modified_files:
        print("\nExpected modified files:")
        for relative_text in report.modified_files:
            print(f"- {relative_text}")

    if report.extra_files:
        print("\nExpected local-only files:")
        for relative_text in report.extra_files:
            print(f"- {relative_text}")

    if report.unexpected_missing_files:
        print("\nUnexpected missing upstream files:")
        for relative_text in report.unexpected_missing_files:
            print(f"- {relative_text}")

    if report.unexpected_modified_files:
        print("\nUnexpected modified upstream files:")
        for relative_text in report.unexpected_modified_files:
            print(f"- {relative_text}")

    if report.unexpected_extra_files:
        print("\nUnexpected local-only files:")
        for relative_text in report.unexpected_extra_files:
            print(f"- {relative_text}")


def print_json_report(config: UpstreamConfig, report: CompareReport) -> None:
    payload = {
        "originalBaseTag": config.original_base_tag,
        "trackedTag": config.tracked_tag,
        "comparedTag": report.tag,
        "modifiedFiles": list(report.modified_files),
        "missingFiles": list(report.missing_files),
        "extraFiles": list(report.extra_files),
        "unexpectedModifiedFiles": list(report.unexpected_modified_files),
        "unexpectedMissingFiles": list(report.unexpected_missing_files),
        "unexpectedExtraFiles": list(report.unexpected_extra_files),
        "isClean": report.is_clean,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> int:
    args = parse_args()
    config = load_config()

    if args.command == "status":
        tag = args.tag or config.tracked_tag
        report = compare_against_upstream(config, tag)
        if args.json:
            print_json_report(config, report)
        else:
            print_text_report(config, report)
        return 0 if report.is_clean else 1

    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
