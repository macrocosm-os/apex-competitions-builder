"""Contract tests for the spec loader and the bundled schema."""

import json
from pathlib import Path

import pytest

from apex_sdk.spec import SpecError, load_spec, load_schema, validate_dict

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "solo" / "spec.yaml"


def test_schema_is_loadable_and_wellformed():
    schema = load_schema()
    assert schema["title"] == "apex.competition.v1"


def test_solo_fixture_spec_is_valid():
    spec = load_spec(FIXTURE, env="stage")
    assert spec.id == "fixture_solo"
    assert spec.kind == "solo"
    assert not spec.is_duel
    # input_schema $ref resolved
    assert spec.input_schema["required"] == ["tasks"]


def test_missing_required_field_fails():
    with pytest.raises(SpecError):
        validate_dict({"schema": "apex.competition.v1", "id": "x"})


def test_duel_requires_duel_block():
    base = json.loads(json.dumps(_minimal_solo()))
    base["kind"] = "duel"  # now duel block is required
    with pytest.raises(SpecError):
        validate_dict(base)


def test_solo_forbids_duel_block():
    base = _minimal_solo()
    base["duel"] = {"players_per_match": 2, "num_games_default": 1, "swap_sides": True}
    with pytest.raises(SpecError):
        validate_dict(base)


def test_solo_defaults_to_one_player_sandbox(tmp_path):
    import yaml

    base = _minimal_solo()
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(base))
    spec = load_spec(p, env="stage")
    assert spec.num_player_sandboxes == 1


def test_solo_allows_player_sandboxes_block(tmp_path):
    import yaml

    base = _minimal_solo()
    base["solo"] = {"player_sandboxes": 2}
    validate_dict(base)  # solo block is valid for kind: solo
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(base))
    spec = load_spec(p, env="stage")
    assert spec.num_player_sandboxes == 2


def test_solo_block_rejects_unknown_field():
    base = _minimal_solo()
    base["solo"] = {"player_sandboxes": 2, "bogus": True}
    with pytest.raises(SpecError):
        validate_dict(base)


def test_solo_block_requires_player_sandboxes():
    base = _minimal_solo()
    base["solo"] = {}
    with pytest.raises(SpecError):
        validate_dict(base)


def test_player_sandboxes_minimum_is_one():
    base = _minimal_solo()
    base["solo"] = {"player_sandboxes": 0}
    with pytest.raises(SpecError):
        validate_dict(base)


def test_duel_forbids_solo_block():
    base = _minimal_solo()
    base["kind"] = "duel"
    base["duel"] = {"players_per_match": 2, "num_games_default": 1, "swap_sides": True}
    base["solo"] = {"player_sandboxes": 2}  # solo block is not allowed for duel
    with pytest.raises(SpecError):
        validate_dict(base)


def test_duel_num_player_sandboxes_from_players_per_match(tmp_path):
    import yaml

    base = _minimal_solo()
    base["kind"] = "duel"
    base["duel"] = {"players_per_match": 3, "num_games_default": 1, "swap_sides": True}
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(base))
    spec = load_spec(p, env="stage")
    assert spec.num_player_sandboxes == 3


def test_referee_block_required():
    base = _minimal_solo()
    del base["referee"]  # referee is required for both solo and duel
    with pytest.raises(SpecError):
        validate_dict(base)


def test_image_digest_pattern_enforced():
    base = _minimal_solo()
    base["image"]["digest"] = "latest"  # not a digest
    with pytest.raises(SpecError):
        validate_dict(base)


def test_resource_ceiling_enforced(tmp_path):
    import yaml

    base = _minimal_solo()
    base["resources"]["cpu_limit"] = 8  # exceeds both stage (2) and prod (4)
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(base))
    with pytest.raises(SpecError, match="cpu_limit"):
        load_spec(p, env="prod")


def _minimal_solo() -> dict:
    return {
        "schema": "apex.competition.v1",
        "id": "fixture_solo",
        "version": "0.1.0",
        "display_name": "Fixture Solo",
        "kind": "solo",
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
            "image": {"ref": "ghcr.io/x/referee", "digest": "sha256:" + "0" * 64},
            "timeout_s": 60,
        },
        "signature": {
            "cosign_identity": "https://github.com/x/y/.github/workflows/release.yml",
            "cosign_issuer": "https://token.actions.githubusercontent.com",
        },
    }


def test_screening_block_optional_and_valid():
    # Layer-1 screening is optional (defaults apply) ...
    base = _minimal_solo()
    validate_dict(base)  # no screening block -> valid
    # ... and a configured block validates.
    base["screening"] = {
        "max_size_mb": 1,
        "extra_forbidden_modules": ["socket", "subprocess"],
        "extra_forbidden_attrs_by_module": {"os": ["open", "system"]},
        "min_weight_bytes": 10240,
        "max_code_weight_ratio": 10,
    }
    validate_dict(base)


def test_screening_rejects_unknown_field():
    base = _minimal_solo()
    base["screening"] = {"bogus_knob": True}
    with pytest.raises(SpecError):
        validate_dict(base)


def test_screen_entrypoint_valid_layer2():
    base = _minimal_solo()
    base["entrypoints"]["screen"] = {
        "image": {"ref": "ghcr.io/x/screener", "digest": "sha256:" + "0" * 64},
        "command": ["python", "/app/screen.py"],
        "timeout_s": 120,
    }
    validate_dict(base)
