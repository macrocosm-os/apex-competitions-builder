"""Contract tests for the spec loader and the bundled schema."""

import json
from pathlib import Path

import pytest
import yaml

from apex_sdk.spec import SpecError, load_spec, load_schema, validate_dict

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "hello-world" / "spec.yaml"
_SHA = "a" * 64


def test_schema_is_loadable_and_wellformed():
    schema = load_schema()
    assert schema["title"] == "apex.competition.v1"


def test_hello_world_example_is_valid():
    spec = load_spec(EXAMPLE, env="stage")
    assert spec.id == "hello_world"
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
    base = _minimal_solo()
    base["resources"]["cpu_limit"] = 8  # exceeds both stage (2) and prod (4)
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(base))
    with pytest.raises(SpecError, match="cpu_limit"):
        load_spec(p, env="prod")


def test_referee_resources_optional_and_valid(tmp_path):
    # Every competition before this one left referee.resources unset -- must stay valid.
    base = _minimal_solo()
    validate_dict(base)
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(base))
    load_spec(p, env="prod")  # no referee.resources -> valid, no ceiling check to run

    # A referee that declares its own resources, within ceiling, also validates.
    base["referee"]["resources"] = {"cpu_limit": 2, "mem_limit": "1Gi", "gpu_count": 0}
    validate_dict(base)
    p.write_text(yaml.safe_dump(base))
    load_spec(p, env="prod")


def test_referee_resource_ceiling_enforced_independently_of_player(tmp_path):
    # referee.resources is checked on its own -- a heavy referee doesn't need the
    # player's resources inflated to match, and a compliant player doesn't hide an
    # over-ceiling referee.
    base = _minimal_solo()
    base["referee"]["resources"] = {"cpu_limit": 8, "mem_limit": "1Gi", "gpu_count": 0}
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(base))
    with pytest.raises(SpecError, match="referee.resources.cpu_limit"):
        load_spec(p, env="prod")


def test_referee_resources_gpu_gated_by_env_pool(tmp_path):
    base = _minimal_solo()
    base["referee"]["resources"] = {"cpu_limit": 1, "mem_limit": "512Mi", "gpu_count": 1}
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(base))
    with pytest.raises(SpecError, match="referee.resources.gpu_count"):
        load_spec(p, env="stage")  # stage has no GPU pool
    load_spec(p, env="prod")  # prod does


def _minimal_solo() -> dict:
    return {
        "schema": "apex.competition.v1",
        "id": "hello_world",
        "version": "0.1.0",
        "display_name": "Hello",
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


# --- csv artifact_type + private_data --------------------------------------------------
#
# A csv submission is a table of predictions over a FIXED public test set, scored against
# private ground truth the platform mounts read-only into the referee. `_minimal_solo()` is
# deliberately left alone: private_data's optionality is asserted against it.


def _minimal_csv() -> dict:
    """A minimal csv-artifact solo spec: private ground truth + the csv Layer-1 knobs."""
    base = _minimal_solo()
    base["submission"] = {"artifact_type": "csv", "max_size_mb": 5, "target_path": "/app/submission.csv"}
    base["screening"] = {
        "max_size_mb": 5,
        "required_columns": ["id", "Class_1", "Class_9"],
        "expected_rows": 18559,
        "id_column": "id",
        "value_min": 0,
        "value_max": 1,
        "row_sum": 1.0,
        "row_sum_tol": 1e-6,
        "allow_nan": False,
    }
    base["private_data"] = [
        {
            "uri": "r2://apex-private/otto/test_labels.csv",
            "mount_path": "/private/test_labels.csv",
            "sha256": _SHA,
            "read_only": True,
        }
    ]
    return base


def _write(tmp_path: Path, spec: dict) -> Path:
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(spec))
    return p


def test_csv_artifact_type_valid():
    validate_dict(_minimal_csv())


@pytest.mark.parametrize("knob", ["required_columns", "expected_rows", "id_column"])
def test_csv_artifact_requires_csv_screening_knobs(knob):
    # Without these three the generic screener has no csv branch to run, so every malformed
    # CSV would fall through to the referee and be attributed as a REFEREE failure.
    base = _minimal_csv()
    del base["screening"][knob]
    with pytest.raises(SpecError):
        validate_dict(base)


def test_csv_artifact_requires_screening_block_at_all():
    base = _minimal_csv()
    del base["screening"]
    with pytest.raises(SpecError):
        validate_dict(base)


def test_screening_rejects_unknown_csv_knob():
    base = _minimal_csv()
    base["screening"]["bogus_csv_knob"] = 1
    with pytest.raises(SpecError):
        validate_dict(base)


def test_private_data_is_optional():
    # Existing specs (hello-world, humanoid-parkour) declare no private_data and stay valid:
    # the block is purely additive.
    assert "private_data" not in _minimal_solo()
    validate_dict(_minimal_solo())


@pytest.mark.parametrize("field", ["uri", "mount_path", "sha256"])
def test_private_data_missing_required_subfield_fails(field):
    base = _minimal_csv()
    del base["private_data"][0][field]
    with pytest.raises(SpecError):
        validate_dict(base)


@pytest.mark.parametrize("bad", ["A" * 64, "sha256:" + "a" * 64, "a" * 63, ""])
def test_private_data_bad_sha256_fails(bad):
    base = _minimal_csv()
    base["private_data"][0]["sha256"] = bad
    with pytest.raises(SpecError):
        validate_dict(base)


@pytest.mark.parametrize("bad", ["s3://b/k", "https://x/y", "r2://bucket", "r2:///k", "file:///x"])
def test_private_data_bad_uri_fails(bad):
    base = _minimal_csv()
    base["private_data"][0]["uri"] = bad
    with pytest.raises(SpecError):
        validate_dict(base)


@pytest.mark.parametrize("bad", ["private/labels.csv", "./x", "/private/", "/"])
def test_private_data_bad_mount_path_fails(bad):
    base = _minimal_csv()
    base["private_data"][0]["mount_path"] = bad
    with pytest.raises(SpecError):
        validate_dict(base)


def test_private_data_unknown_key_fails():
    base = _minimal_csv()
    base["private_data"][0]["bucket"] = "apex-private"
    with pytest.raises(SpecError):
        validate_dict(base)


def test_private_data_read_only_false_fails():
    # read_only is const:true — the platform will never mount private data writable, so the
    # schema refuses to advertise a mode that does not exist.
    base = _minimal_csv()
    base["private_data"][0]["read_only"] = False
    with pytest.raises(SpecError):
        validate_dict(base)


def test_private_data_empty_list_fails():
    base = _minimal_csv()
    base["private_data"] = []
    with pytest.raises(SpecError):
        validate_dict(base)


@pytest.mark.parametrize(
    "target,mount",
    [
        ("/mnt/sub/predictions.csv", "/mnt/sub/predictions.csv"),  # exact collision
        ("/mnt/sub/predictions.csv", "/mnt/sub"),  # mount is a parent of the artifact
        ("/mnt/sub", "/mnt/sub/labels.csv"),  # artifact is a parent of the mount
    ],
)
def test_private_data_mount_collides_with_target_path(target, mount, tmp_path):
    # Note the common case (`/app/submission.csv`) is already caught by the reserved-path
    # rule; this covers artifact paths outside the reserved tree, in both directions.
    base = _minimal_csv()
    base["submission"]["target_path"] = target
    base["private_data"][0]["mount_path"] = mount
    with pytest.raises(SpecError, match="collides"):
        load_spec(_write(tmp_path, base), env="stage")


def test_private_data_duplicate_mount_paths_fail(tmp_path):
    # uniqueItems is not enough: two entries can differ by uri and still fight over one mount.
    base = _minimal_csv()
    base["private_data"].append(
        {"uri": "r2://apex-private/otto/other.csv", "mount_path": "/private/test_labels.csv", "sha256": "b" * 64}
    )
    with pytest.raises(SpecError, match="duplicates"):
        load_spec(_write(tmp_path, base), env="stage")


@pytest.mark.parametrize("bad", ["/data/result.json", "/etc/passwd", "/app/env/labels.py"])
def test_private_data_reserved_mount_path_fails(bad, tmp_path):
    base = _minimal_csv()
    base["private_data"][0]["mount_path"] = bad
    with pytest.raises(SpecError, match="reserved"):
        load_spec(_write(tmp_path, base), env="stage")


def test_private_data_non_normalized_mount_fails(tmp_path):
    base = _minimal_csv()
    base["private_data"][0]["mount_path"] = "/private/../secrets/labels.csv"
    with pytest.raises(SpecError, match="normalized"):
        load_spec(_write(tmp_path, base), env="stage")


def test_valid_csv_spec_loads_and_exposes_private_data(tmp_path):
    spec = load_spec(_write(tmp_path, _minimal_csv()), env="stage")
    assert spec.artifact_type == "csv"
    assert [p["mount_path"] for p in spec.private_data] == ["/private/test_labels.csv"]
    # And a spec without the block exposes an empty list rather than None.
    assert load_spec(_write(tmp_path, _minimal_solo()), env="stage").private_data == []


# --------------------------------------------------------------------- base_model
#
# `base_model` declares a FROZEN model the platform serves for harness competitions.
# The egress topology is the whole point of the block and the part that fails silently
# rather than loudly if it is wrong, so it is validated in code, not just in the schema.


def _harness_solo() -> dict:
    """A minimal spec for a harness competition: platform-served model, referee-only."""
    base = _minimal_solo()
    base["base_model"] = {"served_model": "Qwen/Qwen3-8B", "max_tokens_per_episode": 28000}
    base["referee"]["allow_internet"] = True
    base["entrypoints"]["evaluate"]["allow_internet"] = False
    return base


def test_base_model_is_optional():
    validate_dict(_minimal_solo())
    assert load_spec(EXAMPLE, env="stage").base_model == {}


def test_valid_base_model_spec_loads_and_is_exposed(tmp_path):
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(_harness_solo()))
    spec = load_spec(p, env="stage")
    assert spec.base_model["served_model"] == "Qwen/Qwen3-8B"
    assert spec.base_model["max_tokens_per_episode"] == 28000


@pytest.mark.parametrize("field", ["served_model", "max_tokens_per_episode"])
def test_base_model_missing_required_subfield_fails(field):
    base = _harness_solo()
    del base["base_model"][field]
    with pytest.raises(SpecError):
        validate_dict(base)


def test_base_model_rejects_unknown_key():
    base = _harness_solo()
    base["base_model"]["endpoint"] = "http://example.com"
    with pytest.raises(SpecError):
        validate_dict(base)


@pytest.mark.parametrize(
    "patch",
    [
        {"max_tokens_per_episode": 0},
        {"max_tokens_per_episode": 1.5},
        {"served_model": ""},
        {"temperature": -0.1},
        {"temperature": 3},
        {"max_output_tokens": 0},
    ],
)
def test_base_model_rejects_out_of_range_values(patch):
    base = _harness_solo()
    base["base_model"].update(patch)
    with pytest.raises(SpecError):
        validate_dict(base)


def test_base_model_requires_referee_egress(tmp_path):
    """The referee makes every model call, so without egress the competition cannot run."""
    base = _harness_solo()
    base["referee"]["allow_internet"] = False
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(base))
    with pytest.raises(SpecError, match="allow_internet"):
        load_spec(p, env="stage")


def test_base_model_forbids_player_egress(tmp_path):
    """A player that can reach the model directly bypasses the referee's token meter, and
    the token budget is usually the scarce resource the whole competition is built on."""
    base = _harness_solo()
    base["entrypoints"]["evaluate"]["allow_internet"] = True
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(base))
    with pytest.raises(SpecError, match="bypasses the referee"):
        load_spec(p, env="stage")


def test_referee_egress_without_a_base_model_is_rejected(tmp_path):
    """Egress exists only to reach a declared endpoint; granting it for nothing is a
    misconfiguration worth naming rather than a harmless default."""
    base = _minimal_solo()
    base["referee"]["allow_internet"] = True
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(base))
    with pytest.raises(SpecError, match="no `base_model`"):
        load_spec(p, env="stage")


def test_research_harness_competition_spec_is_valid():
    """The reference harness competition must pass the same gate the platform applies."""
    spec_path = Path(__file__).resolve().parents[1] / "competitions" / "research-harness" / "spec.yaml"
    spec = load_spec(spec_path, env="stage")
    assert spec.id == "research_harness"
    assert spec.artifact_type == "code"
    assert spec.base_model["max_tokens_per_episode"] > 0
    assert spec.raw["referee"]["allow_internet"] is True
    assert spec.raw["entrypoints"]["evaluate"]["allow_internet"] is False
