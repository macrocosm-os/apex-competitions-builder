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
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from jsonschema import Draft202012Validator

SCHEMA_ID = "apex.competition.v1"

# Submission artifact types, ordered by increasing attack surface — the constrained-format
# ladder the design skill teaches. Keep in sync with the schema enum.
ARTIFACT_TYPES: tuple[str, ...] = ("json", "csv", "onnx", "wasm", "torchscript", "code", "archive")

# Every type except `archive` is written to submission.target_path as a single file; `archive`
# is extracted into target_path as a directory.
ARCHIVE_ARTIFACT_TYPE = "archive"
SINGLE_FILE_ARTIFACT_TYPES: tuple[str, ...] = tuple(t for t in ARTIFACT_TYPES if t != ARCHIVE_ARTIFACT_TYPE)

# Conventional file extension per single-file type. A target_path that disagrees is usually a
# copy-paste slip, so preflight says so — but the platform writes bytes to whatever path you
# declare, so it is an advisory, never an error.
_CONVENTIONAL_SUFFIX: dict[str, tuple[str, ...]] = {
    "json": (".json",),
    "csv": (".csv",),
    "onnx": (".onnx",),
    "wasm": (".wasm",),
    "torchscript": (".pt", ".pth"),
}

# Screening knobs that only mean something for certain artifact types. The platform ignores the
# irrelevant ones, so a mismatch is an advisory (and a signal the designer expected other checks).
_SCREENING_KNOB_TYPES: dict[str, tuple[str, ...]] = {
    "extra_forbidden_modules": ("code", "archive"),
    "extra_forbidden_calls": ("code", "archive"),
    "extra_forbidden_attr_calls": ("code", "archive"),
    "extra_forbidden_attrs_by_module": ("code", "archive"),
    "extra_forbidden_dunder_attrs": ("code", "archive"),
    "extra_forbidden_attr_access": ("code", "archive"),
    "block_dynamic_getattr": ("code", "archive"),
    "min_weight_bytes": ("torchscript", "onnx"),
    "max_code_weight_ratio": ("torchscript", "onnx"),
    "allowed_member_extensions": ("archive",),
    "max_rows": ("json", "csv"),
    "max_columns": ("csv",),
    "required_columns": ("csv",),
    "max_json_depth": ("json",),
    "wasm_allowed_imports": ("wasm",),
    "wasm_max_memory_pages": ("wasm",),
}

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
    def artifact_type(self) -> str:
        """The declared submission artifact type (one of ARTIFACT_TYPES)."""
        return self.raw["submission"]["artifact_type"]

    @property
    def is_archive_submission(self) -> bool:
        """True when the submission is a bundle the platform extracts into a directory."""
        return self.artifact_type == ARCHIVE_ARTIFACT_TYPE

    @property
    def archive(self) -> dict[str, Any] | None:
        """The `submission.archive` extraction bounds, or None for single-file artifact types."""
        node = self.raw["submission"].get("archive")
        return node if isinstance(node, dict) else None

    @property
    def target_path(self) -> str:
        """Where the platform puts the artifact: the file path, or the extraction dir for archives."""
        return self.raw["submission"]["target_path"]

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


def _entry_file_problem(entry_file: str) -> str | None:
    """Return why `entry_file` is unsafe as a path relative to the extraction root, else None."""
    if entry_file != entry_file.strip():
        return "has leading or trailing whitespace"
    if PurePosixPath(entry_file).is_absolute():
        return "must be relative to the extraction root, not absolute"
    parts = PurePosixPath(entry_file).parts
    if ".." in parts:
        return "must not contain a '..' component"
    if not parts or entry_file.endswith("/"):
        return "must name a file, not a directory"
    return None


def check_submission_contract(spec: dict[str, Any]) -> None:
    """Enforce the submission cross-field rules JSON Schema can't express.

    Raises SpecError on violation. Run in addition to `validate_dict`, which has already
    established that `submission.archive` is present exactly for `artifact_type: archive`.
    """
    sub = spec["submission"]
    artifact_type = sub["artifact_type"]
    archive = sub.get("archive")
    if archive is None:
        return
    # Defence in depth: validate_dict enforces this pairing, but this function is public.
    if artifact_type != ARCHIVE_ARTIFACT_TYPE:
        raise SpecError(f"submission.archive is only valid for artifact_type: archive, got {artifact_type!r}")

    entry_file = archive["entry_file"]
    problem = _entry_file_problem(entry_file)
    if problem is not None:
        raise SpecError(f"submission.archive.entry_file {entry_file!r} {problem}")

    # A bundle cannot extract to less than it uploads, so an uncompressed ceiling below the
    # upload ceiling rejects every submission that uses the full upload budget.
    if archive["max_uncompressed_mb"] < sub["max_size_mb"]:
        raise SpecError(
            f"submission.archive.max_uncompressed_mb {archive['max_uncompressed_mb']} is below "
            f"submission.max_size_mb {sub['max_size_mb']}; the extracted bundle can never be "
            "smaller than the upload, so no submission could pass"
        )


def submission_advisories(spec: dict[str, Any]) -> list[str]:
    """Non-fatal notes about the submission block: likely mistakes the platform tolerates.

    Surfaced by `apex-dev preflight` so a designer sees them before the platform silently
    ignores a knob they thought was protecting them.
    """
    notes: list[str] = []
    sub = spec["submission"]
    artifact_type = sub["artifact_type"]
    target_path = PurePosixPath(sub["target_path"])

    if artifact_type == ARCHIVE_ARTIFACT_TYPE:
        if target_path.suffix:
            notes.append(
                f"submission.target_path {str(target_path)!r} looks like a file, but artifact_type: archive "
                "extracts into it as a directory"
            )
        entry = sub["archive"]["entry_file"]
        allowed = spec.get("screening", {}).get("allowed_member_extensions")
        if allowed and PurePosixPath(entry).suffix not in allowed:
            notes.append(
                f"submission.archive.entry_file {entry!r} has an extension outside "
                f"screening.allowed_member_extensions {allowed}, so the entry file itself would fail screening"
            )
    else:
        expected = _CONVENTIONAL_SUFFIX.get(artifact_type)
        if expected and target_path.suffix not in expected:
            notes.append(
                f"submission.target_path {str(target_path)!r} does not end in "
                f"{' or '.join(expected)} for artifact_type: {artifact_type}"
            )

    for knob, types in _SCREENING_KNOB_TYPES.items():
        if knob in spec.get("screening", {}) and artifact_type not in types:
            notes.append(
                f"screening.{knob} only applies to artifact_type {', '.join(types)}; "
                f"it is ignored for {artifact_type!r}"
            )
    return notes


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
    check_submission_contract(raw)
    input_schema = _resolve_input_schema(raw, spec_path)
    if env is not None:
        check_resource_ceilings(raw, env)

    return LoadedSpec(path=spec_path, raw=raw, input_schema=input_schema)
