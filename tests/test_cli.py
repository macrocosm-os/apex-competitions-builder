"""Tests for the `apex-dev` CLI, focused on the `run` executor.

The argument-parsing / duel tests need no Docker. The end-to-end test builds the
hello-world player image and runs it, so it is skipped when docker is unavailable.
"""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from apex_sdk.dev.cli import main

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "hello-world"
SPEC = EXAMPLE / "spec.yaml"
INPUT = EXAMPLE / "fixtures" / "input.json"
SUBMISSION = EXAMPLE / "player" / "submission.py"
DOCKERFILE = EXAMPLE / "player" / "Dockerfile"

_HAS_DOCKER = shutil.which("docker") is not None


def _minimal_duel() -> dict:
    return {
        "schema": "apex.competition.v1",
        "id": "duel_demo",
        "version": "0.1.0",
        "display_name": "Duel Demo",
        "kind": "duel",
        "process_type": "cpu",
        "resources": {"cpu_limit": 1, "mem_limit": "512Mi", "gpu_count": 0},
        "image": {"ref": "ghcr.io/x/y", "digest": "sha256:" + "0" * 64},
        "submission": {"artifact_type": "code", "max_size_mb": 1, "target_path": "/app/submission.py"},
        "input_schema": {"type": "object"},
        "defaults": {
            "baseline_score": 0.0,
            "baseline_raw_score": 0.0,
            "round_length_in_days": 1,
            "submission_reveal_days": 1,
            "lower_is_better": False,
        },
        "entrypoints": {"evaluate": {"command": ["python", "/app/launch.py"], "timeout_s": 60}},
        "duel": {
            "protocol": "gym_v1",
            "players_per_match": 2,
            "num_games_default": 1,
            "swap_sides": True,
            "referee_image": {"ref": "ghcr.io/x/ref", "digest": "sha256:" + "0" * 64},
            "referee_timeout_s": 60,
        },
        "signature": {
            "cosign_identity": "https://github.com/x/y/.github/workflows/release.yml",
            "cosign_issuer": "https://token.actions.githubusercontent.com",
        },
    }


def _run(argv: list[str]) -> int:
    """Invoke the CLI, returning the SystemExit code (0 if it exits cleanly)."""
    try:
        main(argv)
    except SystemExit as e:
        return int(e.code or 0)
    return 0


def test_run_requires_submission_for_solo():
    code = _run(["run", "--spec", str(SPEC), "--input", str(INPUT), "--image", "whatever:local"])
    assert code == 2


def test_run_requires_exactly_one_image_source():
    # neither --dockerfile nor --image
    code = _run(["run", "--spec", str(SPEC), "--input", str(INPUT), "--submission", str(SUBMISSION)])
    assert code == 2
    # both --dockerfile and --image
    code = _run(
        [
            "run",
            "--spec",
            str(SPEC),
            "--input",
            str(INPUT),
            "--submission",
            str(SUBMISSION),
            "--dockerfile",
            str(DOCKERFILE),
            "--image",
            "whatever:local",
        ]
    )
    assert code == 2


def test_run_missing_submission_file():
    code = _run(
        ["run", "--spec", str(SPEC), "--input", str(INPUT), "--submission", "/nope/missing.py", "--image", "x:local"]
    )
    assert code == 2


def test_duel_run_exits_3(tmp_path):
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(_minimal_duel()))
    input_path = tmp_path / "input.json"
    input_path.write_text("{}")
    code = _run(["run", "--spec", str(spec_path), "--input", str(input_path)])
    assert code == 3


def test_run_parser_has_expected_flags():
    from apex_sdk.dev.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(
        ["run", "--spec", "s", "--input", "i", "--submission", "sub", "--dockerfile", "df", "--context", "c"]
    )
    assert args.spec == "s"
    assert args.submission == "sub"
    assert args.dockerfile == "df"
    assert args.context == "c"


@pytest.mark.skipif(not _HAS_DOCKER, reason="docker not available")
def test_solo_end_to_end_reference_submission(capsys):
    code = _run(
        [
            "run",
            "--spec",
            str(SPEC),
            "--input",
            str(INPUT),
            "--submission",
            str(SUBMISSION),
            "--dockerfile",
            str(DOCKERFILE),
        ]
    )
    assert code == 0, "solo run should succeed for the reference submission"
    out = capsys.readouterr().out
    # The result block is printed to stdout; the reference submission sorts correctly.
    result = json.loads(out[out.index("{") : out.rindex("}") + 1])
    assert result["raw_score"] == 1.0
    assert isinstance(result["metadata"], dict)
