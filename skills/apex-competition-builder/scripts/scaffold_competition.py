#!/usr/bin/env python3
"""Create an Apex competition repo from the worked example and vendor gym_v1."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_TEMPLATE_URL = "https://github.com/macrocosm-os/apex-competition-hello-world.git"
DEFAULT_TEMPLATE_REF = "9b2ff70df3b539497ad5f4d661793464dd7351b6"
DEFAULT_TOOLKIT_REF = "v0.3.0"
TOOLKIT_RAW_BASE = "https://raw.githubusercontent.com/macrocosm-os/apex-competitions-builder"
GYM_FILES = ("__init__.py", "client.py", "player.py", "referee.py")


class ScaffoldError(RuntimeError):
    """A user-actionable scaffold failure."""


def _run(args: list[str], *, cwd: Path | None = None) -> None:
    try:
        subprocess.run(args, cwd=cwd, check=True)
    except FileNotFoundError as exc:
        raise ScaffoldError(f"required command is not installed: {args[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise ScaffoldError(f"command failed with exit code {exc.returncode}: {' '.join(args)}") from exc


def _capture(args: list[str], *, cwd: Path) -> str:
    try:
        result = subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise ScaffoldError(f"required command is not installed: {args[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise ScaffoldError(f"command failed with exit code {exc.returncode}: {' '.join(args)}") from exc
    return result.stdout.strip()


def _toolkit_root(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        pyproject = candidate / "pyproject.toml"
        if not pyproject.is_file():
            continue
        text = pyproject.read_text(encoding="utf-8")
        if 'name = "apex-competition-sdk"' in text:
            return candidate.resolve()
    return None


def _validate_destination(destination: Path, toolkit_root: Path | None) -> None:
    if destination.exists():
        raise ScaffoldError(f"destination already exists: {destination}")
    if toolkit_root is not None and (destination == toolkit_root or toolkit_root in destination.parents):
        raise ScaffoldError(
            "competition code must live in its own repository; choose a destination outside " f"{toolkit_root}"
        )


def _read_gym_source(filename: str, toolkit_ref: str, toolkit_source: Path | None) -> str:
    if toolkit_source is not None:
        path = toolkit_source / filename
        if not path.is_file():
            raise ScaffoldError(f"missing gym_v1 source file: {path}")
        return path.read_text(encoding="utf-8")

    url = f"{TOOLKIT_RAW_BASE}/{toolkit_ref}/src/apex_sdk/gym_v1/{filename}"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, UnicodeDecodeError) as exc:
        raise ScaffoldError(f"could not download {url}: {exc}") from exc


def _vendored_source(source: str, toolkit_ref: str) -> str:
    rewritten = source.replace("from apex_sdk.gym_v1.", "from gym_v1.")
    header = (
        f"# VENDORED from apex-competitions-builder {toolkit_ref} (src/apex_sdk/gym_v1/), "
        "import root rewritten\n"
        "# apex_sdk.gym_v1 -> gym_v1. Do not hand-edit; re-run the Apex scaffold to update.\n"
    )
    return header + rewritten


def _vendor_gym(checkout: Path, toolkit_ref: str, toolkit_source: Path | None) -> None:
    rendered = {
        filename: _vendored_source(_read_gym_source(filename, toolkit_ref, toolkit_source), toolkit_ref)
        for filename in GYM_FILES
    }
    for side in ("player", "referee"):
        target = checkout / side / "gym_v1"
        if not target.is_dir():
            raise ScaffoldError(f"template is missing expected directory: {target}")
        for filename, source in rendered.items():
            (target / filename).write_text(source, encoding="utf-8")


def scaffold(
    destination: Path,
    *,
    template_url: str,
    template_ref: str,
    toolkit_ref: str,
    toolkit_source: Path | None,
) -> None:
    destination = destination.expanduser().resolve()
    root = _toolkit_root(Path(__file__).resolve())
    _validate_destination(destination, root)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f".{destination.name}-", dir=destination.parent) as temporary:
        checkout = Path(temporary) / "competition"
        _run(["git", "init", "-b", "main", str(checkout)])
        _run(["git", "remote", "add", "origin", template_url], cwd=checkout)
        _run(["git", "fetch", "--depth", "1", "origin", template_ref], cwd=checkout)
        _run(["git", "checkout", "-B", "main", "FETCH_HEAD"], cwd=checkout)
        template_commit = _capture(["git", "rev-parse", "HEAD"], cwd=checkout)
        _run(["git", "remote", "rename", "origin", "template-upstream"], cwd=checkout)
        _vendor_gym(checkout, toolkit_ref, toolkit_source)
        metadata = {
            "template_url": template_url,
            "template_ref": template_ref,
            "template_commit": template_commit,
            "toolkit_ref": toolkit_ref,
        }
        (checkout / ".apex-builder.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        checkout.replace(destination)

    print(f"Created Apex competition repository: {destination}")
    print(f"Template: {template_url}@{template_commit}")
    print(f"Vendored gym_v1 from apex-competitions-builder@{toolkit_ref}")
    print("Next: write the success statement, then replace the hello-world task and run apex-dev preflight.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="New competition repository path")
    parser.add_argument("--template-url", default=DEFAULT_TEMPLATE_URL)
    parser.add_argument("--template-ref", default=DEFAULT_TEMPLATE_REF)
    parser.add_argument("--toolkit-ref", default=DEFAULT_TOOLKIT_REF)
    parser.add_argument(
        "--toolkit-source",
        type=Path,
        help="Optional local src/apex_sdk/gym_v1 directory (primarily for offline development/tests)",
    )
    args = parser.parse_args(argv)

    try:
        scaffold(
            args.destination,
            template_url=args.template_url,
            template_ref=args.template_ref,
            toolkit_ref=args.toolkit_ref,
            toolkit_source=args.toolkit_source,
        )
    except ScaffoldError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
