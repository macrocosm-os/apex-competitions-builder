"""Load and validate an `apex.competition.v1` spec.

This is the SAME validation the platform's spec syncer runs before mirroring an image
or activating a spec. Designers run it locally (via `apex-dev preflight`) so a spec that
passes here is a spec the platform will accept.
"""

from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

SCHEMA_ID = "apex.competition.v1"

# Per-env resource ceilings the platform enforces. A spec that exceeds these fails
# validation at sync time, so we reject them locally too. Keep in sync with the
# platform's syncer config.
_MEM_FLOOR_MI = 256
ENV_CEILINGS: dict[str, dict[str, Any]] = {
    "stage": {"cpu_limit": 2, "mem_mi": 2048, "gpu": False},
    "prod": {"cpu_limit": 4, "mem_mi": 4096, "gpu": True},
}

# Only Macrocosmos-controlled object storage may back private_data: the referee has no
# egress, so the platform is the only fetcher. Keep in sync with the worker's resolver.
PRIVATE_DATA_SCHEMES = ("r2://",)
# Paths the platform owns inside a sandbox. A private mount here would shadow the job's
# own wiring (input/result files, the image's own /app tree).
_RESERVED_MOUNTS = ("/data", "/app", "/proc", "/sys", "/dev", "/etc")


class SpecError(ValueError):
    """Raised when a spec is malformed or violates a platform constraint."""


@dataclass(frozen=True)
class LoadedSpec:
    """A validated spec plus the resolved input JSON Schema and its source path."""

    path: Path
    raw: dict[str, Any]
    input_schema: dict[str, Any]

    @property
    def id(self) -> str:
        return self.raw["id"]

    @property
    def version(self) -> str:
        return self.raw["version"]

    @property
    def kind(self) -> str:
        return self.raw["kind"]

    @property
    def is_duel(self) -> bool:
        return self.raw["kind"] == "duel"

    @property
    def artifact_type(self) -> str:
        return self.raw["submission"]["artifact_type"]

    @property
    def private_data(self) -> list[dict[str, Any]]:
        """Private objects the platform mounts read-only into the referee ([] if none)."""
        return self.raw.get("private_data") or []

    @property
    def base_model(self) -> dict[str, Any]:
        """The frozen base model the platform serves for this competition ({} if none)."""
        return self.raw.get("base_model") or {}


def load_schema() -> dict[str, Any]:
    """Load the bundled apex.competition.v1 JSON Schema."""
    # Schema ships inside the package data (see pyproject packaging).
    text = resources.files("apex_sdk").joinpath("schema/apex.competition.v1.json").read_text()
    return json.loads(text)


def _parse_mem_to_mi(mem: str) -> float:
    m = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(Mi|Gi)", mem)
    if not m:
        raise SpecError(f"resources.mem_limit not a valid quantity: {mem!r}")
    value, unit = float(m.group(1)), m.group(2)
    return value * 1024 if unit == "Gi" else value


def _resolve_input_schema(spec: dict[str, Any], spec_path: Path) -> dict[str, Any]:
    node = spec.get("input_schema", {})
    ref = node.get("$ref") if isinstance(node, dict) else None
    if not ref:
        # Inline schema (or empty). Return as-is.
        return node if isinstance(node, dict) else {}
    ref_path = (spec_path.parent / ref).resolve()
    if not ref_path.is_file():
        raise SpecError(f"input_schema.$ref does not resolve to a file: {ref} -> {ref_path}")
    try:
        loaded = json.loads(ref_path.read_text())
    except json.JSONDecodeError as e:
        raise SpecError(f"input_schema.$ref is not valid JSON ({ref_path}): {e}") from e
    # A referenced input schema must itself be a valid JSON Schema.
    Draft202012Validator.check_schema(loaded)
    return loaded


def validate_dict(spec: dict[str, Any]) -> None:
    """Validate a spec dict against apex.competition.v1. Raises SpecError on failure."""
    validator = Draft202012Validator(load_schema())
    errors = sorted(validator.iter_errors(spec), key=lambda e: list(e.path))
    if errors:
        lines = []
        for e in errors:
            loc = "/".join(str(p) for p in e.path) or "<root>"
            lines.append(f"  - {loc}: {e.message}")
        raise SpecError("spec failed apex.competition.v1 validation:\n" + "\n".join(lines))


def _check_resources_block(res: dict[str, Any], env: str, ceiling: dict[str, Any], where: str) -> None:
    if res["cpu_limit"] > ceiling["cpu_limit"]:
        raise SpecError(f"{where}.cpu_limit {res['cpu_limit']} exceeds {env} ceiling {ceiling['cpu_limit']}")

    mem_mi = _parse_mem_to_mi(res["mem_limit"])
    if mem_mi > ceiling["mem_mi"]:
        raise SpecError(f"{where}.mem_limit {res['mem_limit']} exceeds {env} ceiling {ceiling['mem_mi']}Mi")
    if mem_mi < _MEM_FLOOR_MI:
        raise SpecError(f"{where}.mem_limit {res['mem_limit']} below floor {_MEM_FLOOR_MI}Mi")

    if res["gpu_count"] > 0 and not ceiling["gpu"]:
        raise SpecError(f"{where}.gpu_count {res['gpu_count']} but env {env!r} has no GPU pool")


def check_resource_ceilings(spec: dict[str, Any], env: str) -> None:
    """Enforce the per-env resource ceilings and floors on both the player's `resources`
    and the referee's own, separate `resources` (optional -- most competitions only need
    to judge, not compute, and never set it). Raises SpecError on violation."""
    if env not in ENV_CEILINGS:
        raise SpecError(f"unknown env {env!r}; expected one of {sorted(ENV_CEILINGS)}")
    ceiling = ENV_CEILINGS[env]

    _check_resources_block(spec["resources"], env, ceiling, "resources")

    referee_resources = spec.get("referee", {}).get("resources")
    if referee_resources is not None:
        _check_resources_block(referee_resources, env, ceiling, "referee.resources")


def _is_under(child: str, parent: str) -> bool:
    return child == parent or child.startswith(parent.rstrip("/") + "/")


def check_private_data(spec: dict[str, Any]) -> None:
    """Enforce the private_data rules JSON Schema cannot express.

    The schema already covers per-field shape (uri scheme, absolute mount_path, sha256 hex).
    What it cannot see is the relationship BETWEEN fields and entries: two entries fighting
    over one mount point, or a mount that shadows the miner's own artifact. Both would be
    silent misconfigurations at run time, so they are hard errors here — the same code the
    platform syncer runs.
    """
    items = spec.get("private_data") or []
    target_path = spec.get("submission", {}).get("target_path")
    seen: set[str] = set()

    for i, item in enumerate(items):
        where = f"private_data[{i}]"
        uri, mount = item["uri"], item["mount_path"]

        if not uri.startswith(PRIVATE_DATA_SCHEMES):
            raise SpecError(f"{where}.uri scheme not supported: {uri!r}; expected one of {PRIVATE_DATA_SCHEMES}")

        if not mount.startswith("/") or mount != posixpath.normpath(mount):
            raise SpecError(f"{where}.mount_path must be an absolute, normalized file path: {mount!r}")
        if mount in seen:
            raise SpecError(f"{where}.mount_path duplicates an earlier mount: {mount!r}")
        seen.add(mount)
        for reserved in _RESERVED_MOUNTS:
            if _is_under(mount, reserved):
                raise SpecError(f"{where}.mount_path is a platform-reserved location: {mount!r} (under {reserved})")
        if target_path and (_is_under(mount, target_path) or _is_under(target_path, mount)):
            raise SpecError(
                f"{where}.mount_path {mount!r} collides with submission.target_path {target_path!r}; "
                "private data is mounted in the referee and must never overlap the miner artifact path"
            )


def check_base_model(spec: dict[str, Any]) -> None:
    """Enforce the egress topology a declared `base_model` requires.

    The schema covers the block's own shape. What it cannot state is the *reason* the
    topology has to be exactly this, and getting it wrong does not fail loudly at run
    time — it silently produces an unfair or unmeterable competition:

    - The referee needs egress or it cannot reach the endpoint at all.
    - The player must NOT have egress. If a harness could call the model directly it
      would bypass the referee's meter entirely, so the token budget (usually the
      scarce resource the whole competition is built around) would stop binding, and
      submissions would be ranked on how much inference they were willing to steal.
    """
    model = spec.get("base_model")
    if not model:
        # A referee with egress and nothing to reach is a mistake worth naming.
        if spec.get("referee", {}).get("allow_internet"):
            raise SpecError(
                "referee.allow_internet is true but the spec declares no `base_model`; "
                "referee egress exists only to reach a platform-declared endpoint"
            )
        return

    if not spec.get("referee", {}).get("allow_internet"):
        raise SpecError(
            "spec declares `base_model` but referee.allow_internet is not true; "
            "the referee is the only party that may call the model and it needs egress to do so"
        )
    if spec.get("entrypoints", {}).get("evaluate", {}).get("allow_internet"):
        raise SpecError(
            "spec declares `base_model` and entrypoints.evaluate.allow_internet is true; "
            "a player that can reach the model directly bypasses the referee's token meter"
        )


def load_spec(path: str | Path, env: str | None = "stage") -> LoadedSpec:
    """Load, schema-validate, resolve input_schema, and (optionally) ceiling-check a spec.

    Args:
        path: path to the spec YAML.
        env: if given, also enforce that env's resource ceilings. Pass None to skip.
    """
    spec_path = Path(path).resolve()
    if not spec_path.is_file():
        raise SpecError(f"spec file not found: {spec_path}")
    try:
        raw = yaml.safe_load(spec_path.read_text())
    except yaml.YAMLError as e:
        raise SpecError(f"spec is not valid YAML ({spec_path}): {e}") from e
    if not isinstance(raw, dict):
        raise SpecError(f"spec must be a YAML mapping, got {type(raw).__name__}")

    validate_dict(raw)
    input_schema = _resolve_input_schema(raw, spec_path)
    # Structural and env-independent: surface these even when ceiling checks are skipped.
    check_private_data(raw)
    check_base_model(raw)
    if env is not None:
        check_resource_ceilings(raw, env)

    return LoadedSpec(path=spec_path, raw=raw, input_schema=input_schema)
