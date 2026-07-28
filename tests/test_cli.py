"""Tests for the `apex-dev` CLI, focused on the `run` executor.

No Docker required: `apex-dev run` validates its args and prints the plan, then exits 3
because referee-driven local execution isn't implemented yet, so nothing is ever built.
The spec/submission/Dockerfile below are test fixtures (see tests/fixtures/README.md), not
an example to copy — the worked example lives in the apex-competition-hello-world repo.
"""

from pathlib import Path

import yaml

from apex_sdk.dev.cli import main

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "solo"
SPEC = FIXTURE / "spec.yaml"
INPUT = FIXTURE / "input.json"
SUBMISSION = FIXTURE / "submission.py"
DOCKERFILE = FIXTURE / "Dockerfile"


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
        "entrypoints": {
            "evaluate": {
                "command": ["python", "/app/launch.py", "--port", "8000"],
                "timeout_s": 60,
                "http_api": {"port": 8000, "readiness_path": "/health", "protocol": "gym_v1"},
            }
        },
        "referee": {
            "protocol": "gym_v1",
            "image": {"ref": "ghcr.io/x/ref", "digest": "sha256:" + "0" * 64},
            "timeout_s": 60,
        },
        "duel": {"players_per_match": 2, "num_games_default": 1, "swap_sides": True},
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


def test_solo_run_is_referee_driven_exits_3(capsys):
    # A solo eval is now a 1-player duel (player + referee sandboxes). With valid args, the
    # local run reports that referee-driven execution isn't implemented in apex-dev yet (exit 3),
    # rather than running the old insecure single-sandbox model.
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
    assert code == 3
    assert "referee" in (capsys.readouterr().err.lower())
