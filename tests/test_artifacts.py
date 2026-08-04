"""Tests for the local artifact checker behind `apex-dev preflight --submission` / `run`.

These mirror the platform's structural Layer-1 checks, so the failure cases here are the ones a
designer's reference solution would be rejected for after upload. No Docker, no network.
"""

import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest
import yaml

from apex_sdk.dev.artifacts import ArtifactError, check_artifact, materialize
from apex_sdk.dev.cli import main
from apex_sdk.spec import load_spec

from test_spec import _minimal_solo

WASM_HEADER = b"\x00asm\x01\x00\x00\x00"


def _spec(tmp_path: Path, submission: dict, screening: dict | None = None, name: str = "spec.yaml"):
    base = _minimal_solo()
    base["submission"] = submission
    if screening is not None:
        base["screening"] = screening
    p = tmp_path / name
    p.write_text(yaml.safe_dump(base))
    return load_spec(p, env="stage")


def _single(artifact_type: str, target_path: str, max_size_mb: float = 1) -> dict:
    return {"artifact_type": artifact_type, "max_size_mb": max_size_mb, "target_path": target_path}


def _archive(max_size_mb: float = 1, **archive) -> dict:
    bounds = {"format": "tar.gz", "entry_file": "main.py", "max_uncompressed_mb": 4, "max_files": 50}
    bounds.update(archive)
    return {
        "artifact_type": "archive",
        "max_size_mb": max_size_mb,
        "target_path": "/app/submission",
        "archive": bounds,
    }


def _make_tar(path: Path, files: dict[str, bytes], compress: bool = True) -> Path:
    """Build a tarball. A name ending in '/' becomes a directory member, as real `tar` emits."""
    with tarfile.open(path, "w:gz" if compress else "w") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            if name.endswith("/"):
                info.type = tarfile.DIRTYPE
                tf.addfile(info)
                continue
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return path


def _make_zip(path: Path, files: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return path


# ---------------------------------------------------------------------------------------- json


def test_json_artifact_accepted(tmp_path):
    spec = _spec(tmp_path, _single("json", "/app/submission.json"))
    art = tmp_path / "submission.json"
    art.write_text(json.dumps({"phases": [{"id": 1, "green_s": 30}]}))
    check_artifact(art, spec)


def test_malformed_json_rejected(tmp_path):
    spec = _spec(tmp_path, _single("json", "/app/submission.json"))
    art = tmp_path / "submission.json"
    art.write_text('{"phases": [1, 2,}')
    with pytest.raises(ArtifactError, match="not valid JSON"):
        check_artifact(art, spec)


def test_json_row_and_depth_limits_enforced(tmp_path):
    spec = _spec(
        tmp_path,
        _single("json", "/app/submission.json"),
        screening={"max_rows": 2, "max_json_depth": 3},
    )
    art = tmp_path / "submission.json"
    art.write_text(json.dumps([1, 2, 3, 4]))
    with pytest.raises(ArtifactError, match="max_rows"):
        check_artifact(art, spec)

    art.write_text(json.dumps({"a": {"b": {"c": {"d": 1}}}}))
    with pytest.raises(ArtifactError, match="max_json_depth"):
        check_artifact(art, spec)


def test_deeply_nested_json_does_not_blow_the_stack(tmp_path):
    # The depth walk is iterative; a document json.loads accepts must not crash the checker.
    spec = _spec(tmp_path, _single("json", "/app/submission.json"), screening={"max_json_depth": 4})
    art = tmp_path / "submission.json"
    art.write_text("[" * 400 + "]" * 400)
    with pytest.raises(ArtifactError, match="max_json_depth"):
        check_artifact(art, spec)


# ----------------------------------------------------------------------------------------- csv


def test_csv_artifact_accepted(tmp_path):
    spec = _spec(
        tmp_path,
        _single("csv", "/app/submission.csv"),
        screening={"required_columns": ["intersection_id", "phase"], "max_columns": 4, "max_rows": 10},
    )
    art = tmp_path / "submission.csv"
    art.write_text("intersection_id,phase,green_s\n1,A,30\n2,B,25\n")
    check_artifact(art, spec)


def test_csv_missing_required_column_rejected(tmp_path):
    spec = _spec(
        tmp_path,
        _single("csv", "/app/submission.csv"),
        screening={"required_columns": ["intersection_id", "phase"]},
    )
    art = tmp_path / "submission.csv"
    art.write_text("intersection_id,green_s\n1,30\n")
    with pytest.raises(ArtifactError, match="required_columns"):
        check_artifact(art, spec)


def test_ragged_csv_row_rejected(tmp_path):
    spec = _spec(tmp_path, _single("csv", "/app/submission.csv"))
    art = tmp_path / "submission.csv"
    art.write_text("a,b,c\n1,2,3\n4,5\n")
    with pytest.raises(ArtifactError, match="row 3 has 2 fields"):
        check_artifact(art, spec)


def test_csv_row_and_column_limits_enforced(tmp_path):
    spec = _spec(tmp_path, _single("csv", "/app/submission.csv"), screening={"max_rows": 1, "max_columns": 2})
    art = tmp_path / "submission.csv"
    art.write_text("a,b,c\n1,2,3\n4,5,6\n")
    with pytest.raises(ArtifactError) as e:
        check_artifact(art, spec)
    assert "max_columns" in str(e.value)
    assert "max_rows" in str(e.value)


def test_non_utf8_csv_rejected(tmp_path):
    spec = _spec(tmp_path, _single("csv", "/app/submission.csv"))
    art = tmp_path / "submission.csv"
    art.write_bytes(b"a,b\n\xff\xfe,2\n")
    with pytest.raises(ArtifactError, match="not valid UTF-8"):
        check_artifact(art, spec)


# ---------------------------------------------------------------------------------------- wasm


def test_wasm_artifact_accepted(tmp_path):
    spec = _spec(tmp_path, _single("wasm", "/app/submission.wasm"))
    art = tmp_path / "submission.wasm"
    art.write_bytes(WASM_HEADER + b"\x00" * 32)
    check_artifact(art, spec)


def test_wasm_without_magic_rejected(tmp_path):
    spec = _spec(tmp_path, _single("wasm", "/app/submission.wasm"))
    art = tmp_path / "submission.wasm"
    art.write_bytes(b"#!/usr/bin/env python\nprint(1)\n")
    with pytest.raises(ArtifactError, match="WebAssembly magic"):
        check_artifact(art, spec)


def test_wasm_wrong_version_rejected(tmp_path):
    spec = _spec(tmp_path, _single("wasm", "/app/submission.wasm"))
    art = tmp_path / "submission.wasm"
    art.write_bytes(b"\x00asm\x02\x00\x00\x00")
    with pytest.raises(ArtifactError, match="version"):
        check_artifact(art, spec)


# ------------------------------------------------------------------------------------- archive


def test_tarball_of_python_files_accepted(tmp_path):
    spec = _spec(tmp_path, _archive(), screening={"allowed_member_extensions": [".py"]})
    art = _make_tar(
        tmp_path / "submission.tar.gz",
        {"main.py": b"import helper\n", "helper.py": b"X = 1\n"},
    )
    check_artifact(art, spec)


def test_zip_bundle_accepted(tmp_path):
    spec = _spec(tmp_path, _archive(format="zip"))
    art = _make_zip(tmp_path / "submission.zip", {"main.py": b"pass\n"})
    check_artifact(art, spec)


def test_dot_prefixed_members_accepted(tmp_path):
    # `tar czf bundle.tar.gz -C pkg .` names members ./main.py — the most common way a bundle gets
    # built. Those extract to the same paths as the plain names, so entry_file must still match.
    spec = _spec(tmp_path, _archive(), screening={"allowed_member_extensions": [".py"]})
    art = _make_tar(
        tmp_path / "submission.tar.gz",
        {"./": b"", "./main.py": b"pass\n", "./pkg/helper.py": b"X = 1\n"},
    )
    check_artifact(art, spec)


def test_zip_with_trailing_slash_directories_accepted(tmp_path):
    spec = _spec(tmp_path, _archive(format="zip"), screening={"allowed_member_extensions": [".py"]})
    art = tmp_path / "submission.zip"
    with zipfile.ZipFile(art, "w") as zf:
        zf.writestr("pkg/", b"")
        zf.writestr("main.py", b"pass\n")
        zf.writestr("pkg/helper.py", b"X = 1\n")
    check_artifact(art, spec)


def test_nested_entry_file_matched_after_normalization(tmp_path):
    spec = _spec(tmp_path, _archive(entry_file="pkg/main.py"))
    art = _make_tar(tmp_path / "submission.tar.gz", {"./pkg/main.py": b"pass\n"})
    check_artifact(art, spec)


def test_normalization_does_not_launder_an_unsafe_name(tmp_path):
    # "./../escape.py" normalizes to "../escape.py"; it must still be rejected, and reported
    # under the name the bundle actually declared.
    spec = _spec(tmp_path, _archive())
    art = _make_tar(tmp_path / "submission.tar.gz", {"main.py": b"pass\n", "./../escape.py": b"pwn\n"})
    with pytest.raises(ArtifactError, match=r"'\./\.\./escape\.py'"):
        check_artifact(art, spec)


def test_archive_in_the_wrong_format_rejected(tmp_path):
    spec = _spec(tmp_path, _archive(format="zip"))
    art = _make_tar(tmp_path / "submission.tar.gz", {"main.py": b"pass\n"})
    with pytest.raises(ArtifactError, match="not a zip archive"):
        check_artifact(art, spec)


def test_archive_missing_entry_file_rejected(tmp_path):
    spec = _spec(tmp_path, _archive(entry_file="main.py"))
    art = _make_tar(tmp_path / "submission.tar.gz", {"solution.py": b"pass\n"})
    with pytest.raises(ArtifactError, match="entry_file"):
        check_artifact(art, spec)


def test_archive_traversal_member_rejected(tmp_path):
    spec = _spec(tmp_path, _archive())
    art = _make_tar(
        tmp_path / "submission.tar.gz",
        {"main.py": b"pass\n", "../../etc/cron.d/pwn": b"* * * * * root sh\n"},
    )
    with pytest.raises(ArtifactError, match=r"'\.\.' component"):
        check_artifact(art, spec)


def test_archive_absolute_member_rejected(tmp_path):
    spec = _spec(tmp_path, _archive())
    art = _make_tar(tmp_path / "submission.tar.gz", {"main.py": b"pass\n", "/etc/passwd": b"x\n"})
    with pytest.raises(ArtifactError, match="absolute path"):
        check_artifact(art, spec)


def test_archive_symlink_member_rejected(tmp_path):
    spec = _spec(tmp_path, _archive())
    art = tmp_path / "submission.tar.gz"
    with tarfile.open(art, "w:gz") as tf:
        data = b"pass\n"
        info = tarfile.TarInfo("main.py")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo("secrets")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        tf.addfile(link)
    with pytest.raises(ArtifactError, match="is a link"):
        check_artifact(art, spec)


def test_archive_file_count_limit_enforced(tmp_path):
    spec = _spec(tmp_path, _archive(max_files=2))
    art = _make_tar(
        tmp_path / "submission.tar.gz",
        {"main.py": b"pass\n", "a.py": b"pass\n", "b.py": b"pass\n"},
    )
    with pytest.raises(ArtifactError, match="max_files"):
        check_artifact(art, spec)


def test_decompression_bomb_rejected(tmp_path):
    # 8MB of zeros compresses to a few KB; the uncompressed bound is what catches it.
    spec = _spec(tmp_path, _archive(max_uncompressed_mb=1))
    art = _make_tar(tmp_path / "submission.tar.gz", {"main.py": b"pass\n", "bomb.bin": b"\x00" * (8 * 1024 * 1024)})
    with pytest.raises(ArtifactError, match="max_uncompressed_mb"):
        check_artifact(art, spec)


def test_archive_member_extension_allowlist_enforced(tmp_path):
    spec = _spec(tmp_path, _archive(), screening={"allowed_member_extensions": [".py"]})
    art = _make_tar(tmp_path / "submission.tar.gz", {"main.py": b"pass\n", "weights.bin": b"\x00" * 16})
    with pytest.raises(ArtifactError, match="allowed_member_extensions"):
        check_artifact(art, spec)


def test_directory_accepted_for_archive_type(tmp_path):
    spec = _spec(tmp_path, _archive(), screening={"allowed_member_extensions": [".py"]})
    tree = tmp_path / "pkg"
    (tree / "sub").mkdir(parents=True)
    (tree / "main.py").write_text("import sub.helper\n")
    (tree / "sub" / "helper.py").write_text("X = 1\n")
    check_artifact(tree, spec)


def test_directory_rejected_for_single_file_type(tmp_path):
    spec = _spec(tmp_path, _single("json", "/app/submission.json"))
    tree = tmp_path / "pkg"
    tree.mkdir()
    with pytest.raises(ArtifactError, match="expects a single file"):
        check_artifact(tree, spec)


def test_empty_directory_rejected(tmp_path):
    spec = _spec(tmp_path, _archive())
    tree = tmp_path / "pkg"
    tree.mkdir()
    with pytest.raises(ArtifactError, match="empty directory"):
        check_artifact(tree, spec)


# ------------------------------------------------------------------------------- size / common


def test_oversize_artifact_rejected(tmp_path):
    spec = _spec(tmp_path, _single("code", "/app/submission.py", max_size_mb=0.001))
    art = tmp_path / "submission.py"
    art.write_text("# " + "x" * 4096 + "\n")
    with pytest.raises(ArtifactError, match="max_size_mb"):
        check_artifact(art, spec)


def test_empty_artifact_rejected(tmp_path):
    spec = _spec(tmp_path, _single("code", "/app/submission.py"))
    art = tmp_path / "submission.py"
    art.write_bytes(b"")
    with pytest.raises(ArtifactError, match="is empty"):
        check_artifact(art, spec)


def test_missing_artifact_rejected(tmp_path):
    spec = _spec(tmp_path, _single("code", "/app/submission.py"))
    with pytest.raises(ArtifactError, match="not found"):
        check_artifact(tmp_path / "nope.py", spec)


def test_all_problems_reported_at_once(tmp_path):
    spec = _spec(tmp_path, _archive(max_files=1, entry_file="main.py"))
    art = _make_tar(tmp_path / "submission.tar.gz", {"a.py": b"pass\n", "../b.py": b"pass\n"})
    with pytest.raises(ArtifactError) as e:
        check_artifact(art, spec)
    msg = str(e.value)
    assert "max_files" in msg and "'..' component" in msg and "entry_file" in msg


def test_existing_types_are_only_size_checked(tmp_path):
    # code/onnx/torchscript keep their pre-existing behaviour: no structural check here, so an
    # arbitrary blob passes. Their real validation is the platform screener and your loader.
    for artifact_type in ("code", "onnx", "torchscript"):
        spec = _spec(tmp_path, _single(artifact_type, "/app/submission.bin"), name=f"{artifact_type}.yaml")
        art = tmp_path / f"{artifact_type}.bin"
        art.write_bytes(b"\x01\x02\x03not really a model")
        check_artifact(art, spec)


# ------------------------------------------------------------------------------- materialize


def test_materialize_single_file(tmp_path):
    spec = _spec(tmp_path, _single("json", "/app/submission.json"))
    art = tmp_path / "submission.json"
    art.write_text('{"a": 1}')
    dest = tmp_path / "host"
    dest.mkdir()
    out = materialize(art, spec, dest)
    assert out.is_file()
    assert json.loads(out.read_text()) == {"a": 1}


def test_materialize_extracts_a_tarball(tmp_path):
    spec = _spec(tmp_path, _archive())
    art = _make_tar(tmp_path / "submission.tar.gz", {"main.py": b"pass\n", "pkg/helper.py": b"X = 1\n"})
    dest = tmp_path / "host"
    dest.mkdir()
    out = materialize(art, spec, dest)
    assert (out / "main.py").read_text() == "pass\n"
    assert (out / "pkg" / "helper.py").read_text() == "X = 1\n"


def test_materialize_extracts_a_zip(tmp_path):
    spec = _spec(tmp_path, _archive(format="zip"))
    art = _make_zip(tmp_path / "submission.zip", {"main.py": b"pass\n", "pkg/helper.py": b"X = 1\n"})
    dest = tmp_path / "host"
    dest.mkdir()
    out = materialize(art, spec, dest)
    assert (out / "main.py").read_text() == "pass\n"
    assert (out / "pkg" / "helper.py").read_text() == "X = 1\n"


def test_materialize_normalizes_dot_prefixed_members(tmp_path):
    spec = _spec(tmp_path, _archive())
    art = _make_tar(tmp_path / "submission.tar.gz", {"./main.py": b"pass\n", "./pkg/helper.py": b"X = 1\n"})
    dest = tmp_path / "host"
    dest.mkdir()
    out = materialize(art, spec, dest)
    # The player looks for entry_file at the extraction root, not under a './' directory.
    assert (out / "main.py").read_text() == "pass\n"
    assert (out / "pkg" / "helper.py").read_text() == "X = 1\n"


def test_materialize_never_writes_outside_the_tree(tmp_path):
    # check_artifact rejects these bundles, but materialize must not depend on that having run.
    spec = _spec(tmp_path, _archive())
    art = _make_tar(tmp_path / "submission.tar.gz", {"main.py": b"pass\n", "../escaped.py": b"pwn\n"})
    dest = tmp_path / "host"
    dest.mkdir()
    out = materialize(art, spec, dest)
    assert (out / "main.py").is_file()
    assert not (dest / "escaped.py").exists()
    assert not (tmp_path / "escaped.py").exists()


def test_materialize_copies_a_directory(tmp_path):
    spec = _spec(tmp_path, _archive())
    tree = tmp_path / "pkg"
    (tree / "__pycache__").mkdir(parents=True)
    (tree / "main.py").write_text("pass\n")
    (tree / "__pycache__" / "main.pyc").write_bytes(b"\x00")
    dest = tmp_path / "host"
    dest.mkdir()
    out = materialize(tree, spec, dest)
    assert (out / "main.py").read_text() == "pass\n"
    assert not (out / "__pycache__").exists()


# --------------------------------------------------------------------------------------- CLI


def _run(argv: list[str]) -> int:
    try:
        main(argv)
    except SystemExit as e:
        return int(e.code or 0)
    return 0


def _spec_file(tmp_path: Path, submission: dict, screening: dict | None = None) -> Path:
    base = _minimal_solo()
    base["submission"] = submission
    if screening is not None:
        base["screening"] = screening
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(base))
    return p


def test_preflight_accepts_a_matching_artifact(tmp_path, capsys):
    spec_path = _spec_file(tmp_path, _single("csv", "/app/submission.csv"))
    art = tmp_path / "submission.csv"
    art.write_text("a,b\n1,2\n")
    assert _run(["preflight", "--spec", str(spec_path), "--submission", str(art)]) == 0
    assert "submission valid for artifact_type: csv" in capsys.readouterr().out


def test_preflight_rejects_a_mismatched_artifact(tmp_path, capsys):
    spec_path = _spec_file(tmp_path, _single("wasm", "/app/submission.wasm"))
    art = tmp_path / "submission.wasm"
    art.write_text("def act(obs): return 0\n")
    assert _run(["preflight", "--spec", str(spec_path), "--submission", str(art)]) == 2
    assert "WebAssembly magic" in capsys.readouterr().err


def test_preflight_prints_advisories(tmp_path, capsys):
    spec_path = _spec_file(tmp_path, _single("json", "/app/submission.py"))
    assert _run(["preflight", "--spec", str(spec_path)]) == 0
    assert "does not end in .json" in capsys.readouterr().out


def test_run_accepts_a_directory_for_archive_submissions(tmp_path, capsys):
    spec_path = _spec_file(tmp_path, _archive())
    input_path = tmp_path / "input.json"
    input_path.write_text("{}")
    tree = tmp_path / "pkg"
    tree.mkdir()
    (tree / "main.py").write_text("pass\n")
    # Exit 3 = args and artifact accepted, referee-driven execution not implemented yet.
    code = _run(
        [
            "run",
            "--spec",
            str(spec_path),
            "--input",
            str(input_path),
            "--submission",
            str(tree),
            "--image",
            "player:local",
        ]
    )
    assert code == 3
    out = capsys.readouterr().out
    assert "submission valid for artifact_type: archive" in out
    assert "tar.gz, entry=main.py" in out


def test_run_rejects_a_directory_for_single_file_submissions(tmp_path, capsys):
    spec_path = _spec_file(tmp_path, _single("json", "/app/submission.json"))
    input_path = tmp_path / "input.json"
    input_path.write_text("{}")
    tree = tmp_path / "pkg"
    tree.mkdir()
    code = _run(
        [
            "run",
            "--spec",
            str(spec_path),
            "--input",
            str(input_path),
            "--submission",
            str(tree),
            "--image",
            "player:local",
        ]
    )
    assert code == 2
    assert "expects a single file" in capsys.readouterr().err


def test_run_rejects_a_bad_artifact_before_touching_docker(tmp_path, capsys):
    spec_path = _spec_file(tmp_path, _archive(entry_file="main.py"))
    input_path = tmp_path / "input.json"
    input_path.write_text("{}")
    art = _make_tar(tmp_path / "submission.tar.gz", {"solution.py": b"pass\n"})
    code = _run(
        [
            "run",
            "--spec",
            str(spec_path),
            "--input",
            str(input_path),
            "--submission",
            str(art),
            "--dockerfile",
            str(tmp_path / "Dockerfile"),
        ]
    )
    assert code == 2
    assert "entry_file" in capsys.readouterr().err
