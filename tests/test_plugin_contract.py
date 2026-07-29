from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_plugin_versions_match_project_version() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]

    assert _json(".claude-plugin/plugin.json")["version"] == version
    claude_plugins = _json(".claude-plugin/marketplace.json")["plugins"]
    assert len(claude_plugins) == 1
    assert claude_plugins[0]["version"] == version
    assert _json(".codex-plugin/plugin.json")["version"] == version
    assert _json(".grok-plugin/plugin.json")["version"] == version
    grok_plugins = _json(".grok-plugin/marketplace.json")["plugins"]
    assert len(grok_plugins) == 1
    assert grok_plugins[0]["version"] == version


def test_plugin_manifests_use_canonical_skill_root() -> None:
    for path in (".codex-plugin/plugin.json", ".grok-plugin/plugin.json"):
        manifest = _json(path)
        assert manifest["name"] == "apex-competition-builder"
        assert manifest["skills"] == "./skills/"

    claude = _json(".claude-plugin/plugin.json")
    assert claude["name"] == "apex-competition-builder"
    assert "skills" not in claude


def test_marketplaces_point_at_repository() -> None:
    expected = {
        "source": "url",
        "url": "https://github.com/macrocosm-os/apex-competitions-builder.git",
    }
    claude = _json(".claude-plugin/marketplace.json")
    codex = _json(".agents/plugins/marketplace.json")
    grok = _json(".grok-plugin/marketplace.json")

    assert claude["plugins"][0]["source"] == "./"
    assert codex["plugins"][0]["source"] == expected
    assert grok["plugins"][0]["source"] == "./"
    assert codex["plugins"][0]["policy"] == {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL",
    }


def test_readme_documents_opencode_as_an_agent_skills_target() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "--skill apex-competition-builder -g -a opencode -y" in readme
    assert "OpenCode consumes the canonical Agent Skill directly" in readme
