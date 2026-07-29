#!/usr/bin/env python3
"""Read a release version from a supported manifest on stdin."""

from __future__ import annotations

import json
import re
import sys


def version_from(path: str, text: str) -> str:
    if path == "pyproject.toml":
        pattern = r'(?m)^version\s*=\s*"([^"]+)"'
    elif path == "uv.lock":
        pattern = r'(?ms)^\[\[package\]\]\nname = "apex-competition-sdk"\nversion = "([^"]+)"'
    elif path.endswith("marketplace.json"):
        data = json.loads(text)
        return str(data["plugins"][0].get("version", ""))
    elif path.endswith(".json"):
        return str(json.loads(text).get("version", ""))
    else:
        raise SystemExit(f"unsupported version file: {path}")

    match = re.search(pattern, text)
    if not match:
        raise SystemExit(f"version not found in {path}")
    return match.group(1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: read_release_version.py <path>")
    print(version_from(sys.argv[1], sys.stdin.read()))
