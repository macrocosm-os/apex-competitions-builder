from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load_release_module():
    path = ROOT / ".github" / "scripts" / "prepare_release.py"
    spec = importlib.util.spec_from_file_location("prepare_release", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_version_bumps() -> None:
    module = _load_release_module()
    assert module.next_version("0.3.0", "patch") == "0.3.1"
    assert module.next_version("0.3.0", "minor") == "0.4.0"
    assert module.next_version("0.3.0", "major") == "1.0.0"


def test_release_workflows_parse_as_yaml() -> None:
    for name in (
        "changelog-guard.yml",
        "prepare-release.yml",
        "tag-release.yml",
    ):
        path = ROOT / ".github" / "workflows" / name
        assert yaml.safe_load(path.read_text(encoding="utf-8"))


def test_release_files_and_towncrier_marker_exist() -> None:
    assert "<!-- towncrier release notes start -->" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert (ROOT / "changelog.d" / "README.md").is_file()
    assert not (ROOT / "scripts" / "build-skill.sh").exists()
    assert not (ROOT / ".github" / "workflows" / "release.yml").exists()


def test_release_version_targets_exist() -> None:
    module = _load_release_module()
    for path in (
        module.PYPROJECT,
        module.UV_LOCK,
        *module.PLUGIN_MANIFESTS,
        *module.MARKETPLACE_MANIFESTS,
    ):
        assert path.is_file()
