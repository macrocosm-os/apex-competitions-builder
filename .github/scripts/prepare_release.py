#!/usr/bin/env python3
"""Build the changelog and bump every release version in lockstep."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"

PLUGIN_MANIFESTS = (
    ROOT / ".codex-plugin" / "plugin.json",
    ROOT / ".grok-plugin" / "plugin.json",
    ROOT / ".claude-plugin" / "plugin.json",
)
MARKETPLACE_MANIFESTS = (
    ROOT / ".grok-plugin" / "marketplace.json",
    ROOT / ".claude-plugin" / "marketplace.json",
)

VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
PYPROJECT_RE = re.compile(r'^(version\s*=\s*")([^"]+)(")\s*$', re.MULTILINE)
UV_LOCK_RE = re.compile(r'(?ms)^(\[\[package\]\]\nname = "apex-competition-sdk"\nversion = ")([^"]+)(")')


def parse_version(value: str) -> tuple[int, int, int]:
    match = VERSION_RE.fullmatch(value.strip())
    if not match:
        raise SystemExit(f"invalid semver, expected X.Y.Z: {value!r}")
    return tuple(int(group) for group in match.groups())


def current_version() -> str:
    match = PYPROJECT_RE.search(PYPROJECT.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit("could not find project version in pyproject.toml")
    return match.group(2)


def next_version(current: str, bump: str) -> str:
    major, minor, patch = parse_version(current)
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def replace_once(path: Path, pattern: re.Pattern[str], version: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = pattern.subn(rf"\g<1>{version}\g<3>", text, count=1)
    if count != 1:
        raise SystemExit(f"{path.relative_to(ROOT)}: expected one {label}, found {count}")
    path.write_text(updated, encoding="utf-8")


def bump_json(path: Path, version: str, *, marketplace: bool = False) -> None:
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    if marketplace:
        plugins = data.get("plugins") or []
        if len(plugins) != 1:
            raise SystemExit(f"{path.relative_to(ROOT)}: expected exactly one plugin")
        plugins[0]["version"] = version
    else:
        data["version"] = version
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def run_towncrier(version: str, *, draft: bool) -> None:
    command = [sys.executable, "-m", "towncrier", "build", "--version", version, "--yes"]
    if draft:
        command.append("--draft")
    subprocess.run(command, cwd=ROOT, check=True)


def bump_all(version: str) -> list[Path]:
    touched = [PYPROJECT, UV_LOCK]
    replace_once(PYPROJECT, PYPROJECT_RE, version, "project version")
    replace_once(UV_LOCK, UV_LOCK_RE, version, "lockfile package version")
    for path in PLUGIN_MANIFESTS:
        if path.exists():
            bump_json(path, version)
            touched.append(path)
    for path in MARKETPLACE_MANIFESTS:
        if path.exists():
            bump_json(path, version, marketplace=True)
            touched.append(path)
    return touched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--bump", choices=("patch", "minor", "major"))
    group.add_argument("--version")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    current = current_version()
    version = args.version or next_version(current, args.bump)
    parse_version(version)
    if parse_version(version) <= parse_version(current) and not args.dry_run:
        raise SystemExit(f"refusing to release {version} over current version {current}")

    print(f"Current version: {current}")
    print(f"Next version:    {version}")
    if args.dry_run:
        run_towncrier(version, draft=True)
        return 0

    run_towncrier(version, draft=False)
    touched = bump_all(version)
    print("Bumped release files:")
    for path in touched:
        print(f"  - {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
