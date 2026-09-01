"""Fast, local triage checks for an Apex competition package.

This is intentionally a cheap first pass. It catches obvious onboarding problems but does not
replace the internal admission review or make a public accept/reject decision.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from apex_sdk.spec import SpecError, load_spec


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    message: str


def _digest_is_placeholder_or_invalid(value: Any) -> bool:
    return not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value) or set(value[7:]) == {"0"}


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _fixture_task_finding(fixture: Any) -> Finding | None:
    if not isinstance(fixture, dict) or not isinstance(fixture.get("tasks"), list):
        return None
    tasks = fixture["tasks"]
    if not tasks:
        return Finding("empty_tasks", "error", "input fixture contains no tasks")
    normalized = {json.dumps(task, sort_keys=True, separators=(",", ":")) for task in tasks}
    if len(normalized) == 1 and len(tasks) > 1:
        return Finding("duplicate_tasks", "error", "all input tasks are identical")
    return None


def screen_package(
    repo: str | Path, spec_path: str | Path | None = None, input_path: str | Path | None = None
) -> list[Finding]:
    """Return obvious triage findings for a competition package.

    The package is treated as untrusted data. This function reads YAML/JSON and source filenames
    only; it never imports or executes candidate code.
    """

    root = Path(repo).resolve()
    spec = Path(spec_path) if spec_path else root / "spec.yaml"
    findings: list[Finding] = []

    for required in (spec, root / "HANDOFF.md"):
        if not required.is_file():
            findings.append(
                Finding("missing_artifact", "error", f"required file is missing: {required.relative_to(root)}")
            )

    try:
        loaded = load_spec(spec)
    except (SpecError, OSError) as exc:
        findings.append(Finding("invalid_spec", "error", str(exc)))
        return findings

    raw = loaded.raw
    for name, image in (("player", raw.get("image")), ("referee", raw.get("referee", {}).get("image"))):
        digest = image.get("digest") if isinstance(image, dict) else None
        if _digest_is_placeholder_or_invalid(digest):
            findings.append(
                Finding("placeholder_digest", "error", f"{name} image digest is missing, invalid, or all zeros")
            )

    defaults = raw.get("defaults", {})
    baseline = defaults.get("baseline_score")
    lower_is_better = defaults.get("lower_is_better", False)
    if isinstance(baseline, (int, float)) and not isinstance(baseline, bool):
        if (not lower_is_better and baseline >= 1.0) or (lower_is_better and baseline <= 0.0):
            findings.append(
                Finding("perfect_baseline", "error", "baseline score is already at the apparent metric optimum")
            )

    candidate_input = Path(input_path) if input_path else root / "fixtures" / "input.json"
    if candidate_input.is_file():
        fixture = _load_json(candidate_input)
        if fixture is None:
            findings.append(
                Finding(
                    "invalid_fixture", "error", f"input fixture is not valid JSON: {candidate_input.relative_to(root)}"
                )
            )
        elif loaded.input_schema:
            errors = sorted(Draft202012Validator(loaded.input_schema).iter_errors(fixture), key=lambda e: list(e.path))
            if errors:
                findings.append(
                    Finding("fixture_schema", "error", f"input fixture fails input_schema: {errors[0].message}")
                )
            task_finding = _fixture_task_finding(fixture)
            if task_finding:
                findings.append(task_finding)

    return findings
