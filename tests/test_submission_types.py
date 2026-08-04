"""Contract tests for the submission artifact types and the archive extraction bounds.

Schema/loader level only — the artifact-side checks live in test_artifacts.py.
"""

import pytest
import yaml

from apex_sdk.spec import (
    ARTIFACT_TYPES,
    SINGLE_FILE_ARTIFACT_TYPES,
    SpecError,
    check_submission_contract,
    load_schema,
    load_spec,
    submission_advisories,
    validate_dict,
)

from test_spec import _minimal_solo


def _validate_all(spec: dict) -> None:
    """Everything `load_spec` enforces on an in-memory dict: schema shape, then cross-field rules."""
    validate_dict(spec)
    check_submission_contract(spec)


def _archive_submission(**overrides) -> dict:
    archive = {
        "format": "tar.gz",
        "entry_file": "main.py",
        "max_uncompressed_mb": 4,
        "max_files": 50,
    }
    archive.update(overrides.pop("archive", {}))
    sub = {
        "artifact_type": "archive",
        "max_size_mb": 1,
        "target_path": "/app/submission",
        "archive": archive,
    }
    sub.update(overrides)
    return sub


def test_schema_enum_matches_the_module_constant():
    # spec.ARTIFACT_TYPES is what the CLI and docs key off; drift from the schema would let the
    # toolkit accept a type the platform rejects.
    schema = load_schema()
    enum = schema["properties"]["submission"]["properties"]["artifact_type"]["enum"]
    assert tuple(enum) == ARTIFACT_TYPES


def test_every_artifact_type_validates():
    for artifact_type in SINGLE_FILE_ARTIFACT_TYPES:
        base = _minimal_solo()
        base["submission"]["artifact_type"] = artifact_type
        validate_dict(base)  # no archive block needed
    base = _minimal_solo()
    base["submission"] = _archive_submission()
    validate_dict(base)


def test_legacy_code_spec_still_validates():
    # The pre-existing three types and a submission block with no `archive` key must keep working:
    # (id, version) pairs already synced against this schema cannot be re-edited.
    for artifact_type in ("code", "torchscript", "onnx"):
        base = _minimal_solo()
        base["submission"] = {
            "artifact_type": artifact_type,
            "max_size_mb": 1,
            "target_path": "/app/submission.bin",
        }
        validate_dict(base)


def test_unknown_artifact_type_rejected():
    base = _minimal_solo()
    base["submission"]["artifact_type"] = "parquet"
    with pytest.raises(SpecError):
        validate_dict(base)


def test_archive_type_requires_archive_block():
    base = _minimal_solo()
    base["submission"] = {"artifact_type": "archive", "max_size_mb": 1, "target_path": "/app/submission"}
    with pytest.raises(SpecError, match="archive"):
        validate_dict(base)


def test_archive_block_forbidden_for_single_file_types():
    for artifact_type in SINGLE_FILE_ARTIFACT_TYPES:
        base = _minimal_solo()
        base["submission"] = _archive_submission(artifact_type=artifact_type)
        with pytest.raises(SpecError):
            validate_dict(base)


def test_archive_block_requires_all_bounds():
    for missing in ("format", "entry_file", "max_uncompressed_mb", "max_files"):
        base = _minimal_solo()
        sub = _archive_submission()
        del sub["archive"][missing]
        base["submission"] = sub
        with pytest.raises(SpecError, match=missing):
            validate_dict(base)


def test_archive_block_rejects_unknown_field_and_format():
    base = _minimal_solo()
    base["submission"] = _archive_submission(archive={"bogus": 1})
    with pytest.raises(SpecError):
        validate_dict(base)
    base["submission"] = _archive_submission(archive={"format": "rar"})
    with pytest.raises(SpecError):
        validate_dict(base)


@pytest.mark.parametrize("entry_file", ["../escape.py", "pkg/../../escape.py", "/abs/main.py", "pkg/", " main.py"])
def test_entry_file_traversal_rejected(entry_file):
    base = _minimal_solo()
    base["submission"] = _archive_submission(archive={"entry_file": entry_file})
    # An absolute entry_file is caught by the schema pattern, the rest by the cross-field check.
    with pytest.raises(SpecError, match="entry_file"):
        _validate_all(base)


def test_nested_entry_file_allowed():
    base = _minimal_solo()
    base["submission"] = _archive_submission(archive={"entry_file": "pkg/agent/main.py"})
    _validate_all(base)


def test_uncompressed_ceiling_below_upload_ceiling_rejected():
    base = _minimal_solo()
    base["submission"] = _archive_submission(max_size_mb=8, archive={"max_uncompressed_mb": 4})
    validate_dict(base)  # shape is fine; the relationship is not
    with pytest.raises(SpecError, match="max_uncompressed_mb"):
        check_submission_contract(base)


def test_load_spec_enforces_the_submission_contract(tmp_path):
    base = _minimal_solo()
    base["submission"] = _archive_submission(archive={"entry_file": "../escape.py"})
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(base))
    with pytest.raises(SpecError, match="entry_file"):
        load_spec(p, env="stage")


def test_loaded_spec_exposes_archive_accessors(tmp_path):
    base = _minimal_solo()
    base["submission"] = _archive_submission()
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(base))
    spec = load_spec(p, env="stage")
    assert spec.artifact_type == "archive"
    assert spec.is_archive_submission
    assert spec.archive["entry_file"] == "main.py"
    assert spec.target_path == "/app/submission"


def test_loaded_spec_accessors_for_single_file_type(tmp_path):
    base = _minimal_solo()
    base["submission"] = {"artifact_type": "json", "max_size_mb": 1, "target_path": "/app/policy.json"}
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(base))
    spec = load_spec(p, env="stage")
    assert spec.artifact_type == "json"
    assert not spec.is_archive_submission
    assert spec.archive is None


def test_screening_knobs_for_new_types_validate():
    base = _minimal_solo()
    base["submission"]["artifact_type"] = "csv"
    base["submission"]["target_path"] = "/app/submission.csv"
    base["screening"] = {
        "max_size_mb": 1,
        "max_rows": 10_000,
        "max_columns": 12,
        "required_columns": ["intersection_id", "phase"],
    }
    validate_dict(base)

    base["submission"]["artifact_type"] = "json"
    base["submission"]["target_path"] = "/app/submission.json"
    base["screening"] = {"max_rows": 500, "max_json_depth": 6}
    validate_dict(base)

    base["submission"]["artifact_type"] = "wasm"
    base["submission"]["target_path"] = "/app/submission.wasm"
    base["screening"] = {"wasm_allowed_imports": ["env.log"], "wasm_max_memory_pages": 64}
    validate_dict(base)

    base["submission"] = _archive_submission()
    base["screening"] = {"allowed_member_extensions": [".py"], "extra_forbidden_modules": ["socket"]}
    validate_dict(base)


def test_allowed_member_extensions_must_look_like_extensions():
    base = _minimal_solo()
    base["submission"] = _archive_submission()
    base["screening"] = {"allowed_member_extensions": ["py"]}  # missing the dot
    with pytest.raises(SpecError):
        validate_dict(base)


def test_advisory_on_suffix_mismatch():
    base = _minimal_solo()
    base["submission"] = {"artifact_type": "json", "max_size_mb": 1, "target_path": "/app/submission.py"}
    notes = submission_advisories(base)
    assert any("does not end in .json" in n for n in notes)


def test_advisory_when_archive_target_path_looks_like_a_file():
    base = _minimal_solo()
    base["submission"] = _archive_submission(target_path="/app/submission.py")
    notes = submission_advisories(base)
    assert any("extracts into it as a directory" in n for n in notes)


def test_advisory_when_entry_file_would_fail_member_screening():
    base = _minimal_solo()
    base["submission"] = _archive_submission(archive={"entry_file": "main.py"})
    base["screening"] = {"allowed_member_extensions": [".json"]}
    notes = submission_advisories(base)
    assert any("entry_file" in n and "allowed_member_extensions" in n for n in notes)


def test_advisory_when_screening_knob_does_not_apply():
    base = _minimal_solo()  # artifact_type: code
    base["screening"] = {"wasm_allowed_imports": ["env.log"], "min_weight_bytes": 1}
    notes = submission_advisories(base)
    assert any("wasm_allowed_imports" in n and "ignored for 'code'" in n for n in notes)
    assert any("min_weight_bytes" in n for n in notes)


def test_no_advisories_for_a_clean_spec():
    base = _minimal_solo()
    base["submission"] = _archive_submission()
    base["screening"] = {"allowed_member_extensions": [".py"], "extra_forbidden_modules": ["socket"]}
    assert submission_advisories(base) == []
