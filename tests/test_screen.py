import json
from pathlib import Path

from apex_sdk.dev.screen import screen_package

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "solo"


def test_screen_catches_obvious_fixture_problems():
    findings = screen_package(FIXTURE)
    codes = {finding.code for finding in findings}
    assert "placeholder_digest" in codes
    assert "missing_artifact" in codes


def test_screen_catches_perfect_baseline_and_duplicate_tasks(tmp_path):
    repo = tmp_path / "candidate"
    repo.mkdir()
    (repo / "HANDOFF.md").write_text("handoff")
    (repo / "spec.yaml").write_text(
        (FIXTURE / "spec.yaml").read_text().replace("baseline_score: 0.0", "baseline_score: 1.0")
    )
    (repo / "input.schema.json").write_text((FIXTURE / "input.schema.json").read_text())
    fixture = {"tasks": [{"task_name": "same", "numbers": [1]}, {"task_name": "same", "numbers": [1]}]}
    (repo / "fixtures").mkdir()
    (repo / "fixtures" / "input.json").write_text(json.dumps(fixture))
    findings = screen_package(repo)
    codes = {finding.code for finding in findings}
    assert "perfect_baseline" in codes
    assert "duplicate_tasks" in codes


def test_screen_does_not_execute_candidate_code(tmp_path):
    repo = tmp_path / "candidate"
    repo.mkdir()
    (repo / "HANDOFF.md").write_text("handoff")
    spec = (FIXTURE / "spec.yaml").read_text().replace("baseline_score: 0.0", "baseline_score: 0.5")
    (repo / "spec.yaml").write_text(spec)
    (repo / "input.schema.json").write_text((FIXTURE / "input.schema.json").read_text())
    (repo / "player.py").write_text("raise RuntimeError('must not execute')")
    findings = screen_package(repo)
    assert all(finding.code != "candidate_execution" for finding in findings)
