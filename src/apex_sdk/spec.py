"""Load and validate an `apex.competition.v1` spec.

This is the SAME validation the platform's spec syncer runs before mirroring an image
or activating a spec. Designers run it locally (via `apex-dev preflight`) so a spec that
passes here is a spec the platform will accept.
"""

from __future__ import annotations

import json
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
    def num_player_sandboxes(self) -> int:
        """How many player sandboxes the platform provisions for one evaluation.

        duel -> `duel.players_per_match` (distinct submissions). solo -> 1 by default, or
        `solo.player_sandboxes` isolated sandboxes of the SAME submission when set.
        """
        if self.raw["kind"] == "duel":
            return int(self.raw["duel"]["players_per_match"])
        return int(self.raw.get("solo", {}).get("player_sandboxes", 1))


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


def check_resource_ceilings(spec: dict[str, Any], env: str) -> None:
    """Enforce the per-env resource ceilings and floors. Raises SpecError on violation."""
    if env not in ENV_CEILINGS:
        raise SpecError(f"unknown env {env!r}; expected one of {sorted(ENV_CEILINGS)}")
    ceiling = ENV_CEILINGS[env]
    res = spec["resources"]

    if res["cpu_limit"] > ceiling["cpu_limit"]:
        raise SpecError(f"resources.cpu_limit {res['cpu_limit']} exceeds {env} ceiling {ceiling['cpu_limit']}")

    mem_mi = _parse_mem_to_mi(res["mem_limit"])
    if mem_mi > ceiling["mem_mi"]:
        raise SpecError(f"resources.mem_limit {res['mem_limit']} exceeds {env} ceiling {ceiling['mem_mi']}Mi")
    if mem_mi < _MEM_FLOOR_MI:
        raise SpecError(f"resources.mem_limit {res['mem_limit']} below floor {_MEM_FLOOR_MI}Mi")

    if res["gpu_count"] > 0 and not ceiling["gpu"]:
        raise SpecError(f"resources.gpu_count {res['gpu_count']} but env {env!r} has no GPU pool")


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
    if env is not None:
        check_resource_ceilings(raw, env)

    return LoadedSpec(path=spec_path, raw=raw, input_schema=input_schema)
