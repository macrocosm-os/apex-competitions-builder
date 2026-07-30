"""Tests for the `apex-dev` CLI, focused on the `run` executor.

The argument-parsing / duel tests need no Docker. The end-to-end test builds the
hello-world player image and runs it, so it is skipped when docker is unavailable.
"""

import hashlib
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

# A stand-in private ground-truth object: the bytes and the digest the spec must pin.
_LABELS = b"id,target\n1,Class_1\n"
_LABELS_SHA = hashlib.sha256(_LABELS).hexdigest()
_MOUNT = "/private/test_labels.csv"


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


# --- csv artifact_type + private_data mounts -------------------------------------------


def _minimal_csv_solo() -> dict:
    """A solo spec whose ground truth arrives as a platform-mounted private object."""
    spec = _minimal_duel()
    del spec["duel"]
    spec["kind"] = "solo"
    spec["id"] = "csv_demo"
    spec["submission"] = {"artifact_type": "csv", "max_size_mb": 5, "target_path": "/app/submission.csv"}
    # csv artifact_type requires these three Layer-1 knobs, or _load fails for the wrong reason.
    spec["screening"] = {"required_columns": ["id", "target"], "expected_rows": 1, "id_column": "id"}
    spec["private_data"] = [
        {"uri": "r2://apex-private/csv-demo/labels.csv", "mount_path": _MOUNT, "sha256": _LABELS_SHA}
    ]
    return spec


def _csv_case(tmp_path: Path, *, labels: bytes | None = _LABELS) -> tuple[Path, Path, Path]:
    """Write a csv spec, a round input, a submission, and (optionally) a local labels file."""
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(_minimal_csv_solo()))
    input_path = tmp_path / "input.json"
    input_path.write_text("{}")
    sub_path = tmp_path / "submission.csv"
    sub_path.write_text("id,target\n1,Class_1\n")
    labels_path = tmp_path / "labels.csv"
    if labels is not None:
        labels_path.write_bytes(labels)
    return spec_path, input_path, sub_path


def _run_csv(tmp_path: Path, *extra: str, labels: bytes | None = _LABELS) -> int:
    spec_path, input_path, sub_path = _csv_case(tmp_path, labels=labels)
    return _run(
        [
            "run",
            "--spec",
            str(spec_path),
            "--input",
            str(input_path),
            "--submission",
            str(sub_path),
            "--image",
            "x:local",
            *extra,
        ]
    )


def test_run_parser_accepts_repeated_private_data():
    from apex_sdk.dev.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(
        [
            "run",
            "--spec",
            "s",
            "--input",
            "i",
            "--private-data",
            "/private/a.csv=/tmp/a.csv",
            "--private-data",
            "/private/b.csv=/tmp/b.csv",
        ]
    )
    assert args.private_data == ["/private/a.csv=/tmp/a.csv", "/private/b.csv=/tmp/b.csv"]
    # default must be [] (not None) or the resolver would crash on specs without the flag.
    assert parser.parse_args(["run", "--spec", "s", "--input", "i"]).private_data == []


@pytest.mark.parametrize("pair", ["/private/test_labels.csv", "relative=/tmp/f", "/private/x.csv="])
def test_run_rejects_malformed_private_data_pair(pair, tmp_path):
    assert _run_csv(tmp_path, "--private-data", pair) == 2


def test_run_rejects_undeclared_private_data_mount(capsys):
    # hello-world declares no private_data at all.
    code = _run(
        [
            "run",
            "--spec",
            str(SPEC),
            "--input",
            str(INPUT),
            "--submission",
            str(SUBMISSION),
            "--image",
            "x:local",
            "--private-data",
            f"/private/x.csv={SUBMISSION}",
        ]
    )
    assert code == 2
    assert "not declared" in capsys.readouterr().err


def test_run_requires_private_data_for_declared_mount(tmp_path, capsys):
    assert _run_csv(tmp_path) == 2
    assert _MOUNT in capsys.readouterr().err


def test_run_private_data_missing_host_file(tmp_path):
    assert _run_csv(tmp_path, "--private-data", f"{_MOUNT}=/nope/labels.csv") == 2


def test_run_private_data_sha256_mismatch_fails(tmp_path, capsys):
    code = _run_csv(tmp_path, "--private-data", f"{_MOUNT}={tmp_path / 'labels.csv'}", labels=b"id,target\n1,Class_9\n")
    assert code == 2
    assert "sha256 mismatch" in capsys.readouterr().err


def test_run_private_data_happy_path_exits_3(tmp_path, capsys):
    # Referee-driven execution is still unimplemented (exit 3), but the mount resolves and is
    # reported in the plan — which is what makes the flag testable before the harness exists.
    code = _run_csv(tmp_path, "--private-data", f"{_MOUNT}={tmp_path / 'labels.csv'}")
    assert code == 3
    out = capsys.readouterr().out
    assert "private mount" in out
    assert f"{_MOUNT} (referee only, ro)" in out


def test_preflight_reports_private_data(tmp_path, capsys):
    spec_path, _, _ = _csv_case(tmp_path)
    assert _run(["preflight", "--spec", str(spec_path)]) == 0
    assert "r2://apex-private/csv-demo/labels.csv" in capsys.readouterr().out


def test_validate_game_result_enforces_the_gym_v1_contract():
    from apex_sdk.dev.cli import _validate_game_result

    ok = {"raw_scores": [0.5], "winner": 0, "terminal_reason": "scored", "steps": 10, "metadata": {}}
    _validate_game_result(ok)

    for mutation in (
        {"raw_scores": []},  # empty
        {"raw_scores": 0.5},  # not a list
        {"raw_scores": [True]},  # bool is not a score
        {"winner": "0"},
        {"steps": 1.5},
        {"terminal_reason": None},
        {"metadata": []},
    ):
        with pytest.raises(SystemExit) as ei:
            _validate_game_result({**ok, **mutation})
        assert ei.value.code == 6
