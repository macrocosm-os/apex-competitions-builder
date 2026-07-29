from __future__ import annotations

import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "apex-competition-builder"
SCAFFOLD_PATH = SKILL_ROOT / "scripts" / "scaffold_competition.py"


def _load_scaffold():
    spec = importlib.util.spec_from_file_location("scaffold_competition", SCAFFOLD_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _make_template(path: Path) -> None:
    for side in ("player", "referee"):
        gym = path / side / "gym_v1"
        gym.mkdir(parents=True)
        for filename in ("__init__.py", "client.py", "player.py", "referee.py"):
            (gym / filename).write_text("# stale template copy\n", encoding="utf-8")
    (path / "spec.yaml").write_text("schema: apex.competition.v1\n", encoding="utf-8")
    _git("init", "-b", "main", cwd=path)
    _git("config", "user.name", "Test", cwd=path)
    _git("config", "user.email", "test@example.com", cwd=path)
    _git("config", "commit.gpgsign", "false", cwd=path)
    _git("add", ".", cwd=path)
    _git("commit", "-m", "initial template", cwd=path)


def test_skill_frontmatter_and_openai_metadata() -> None:
    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = text.split("---", 2)[1]
    metadata = yaml.safe_load(frontmatter)
    assert metadata["name"] == "apex-competition-builder"
    assert "Apex competition" in metadata["description"]

    openai = yaml.safe_load((SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8"))
    assert openai["interface"]["display_name"] == "Apex Competition Builder"
    assert 25 <= len(openai["interface"]["short_description"]) <= 64
    assert "$apex-competition-builder" in openai["interface"]["default_prompt"]
    assert openai["policy"]["allow_implicit_invocation"] is True


def test_skill_has_no_relative_links_outside_its_package() -> None:
    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    targets = re.findall(r"\[[^]]+\]\(([^)]+)\)", text)
    for target in targets:
        if "://" in target or target.startswith("#"):
            continue
        resolved = (SKILL_ROOT / target).resolve()
        assert resolved.is_relative_to(SKILL_ROOT.resolve()), target
        assert resolved.exists(), target


def test_skill_contains_only_runtime_scripts() -> None:
    files = sorted(path.name for path in (SKILL_ROOT / "scripts").iterdir() if path.is_file())
    assert files == ["scaffold_competition.py"]


def test_scaffold_rejects_destination_inside_toolkit() -> None:
    module = _load_scaffold()
    with pytest.raises(module.ScaffoldError, match="own repository"):
        module._validate_destination(ROOT / "generated-competition", ROOT)


def test_scaffold_rejects_an_existing_empty_destination(tmp_path: Path) -> None:
    module = _load_scaffold()
    destination = tmp_path / "existing"
    destination.mkdir()
    with pytest.raises(module.ScaffoldError, match="already exists"):
        module._validate_destination(destination, None)


def test_scaffold_clones_template_and_revendors_gym(tmp_path: Path) -> None:
    module = _load_scaffold()
    template = tmp_path / "template"
    template.mkdir()
    _make_template(template)
    template_commit = _git("rev-parse", "HEAD", cwd=template)
    destination = tmp_path / "competition"

    module.scaffold(
        destination,
        template_url=str(template),
        template_ref="main",
        toolkit_ref="v0.3.0",
        toolkit_source=ROOT / "src" / "apex_sdk" / "gym_v1",
    )

    metadata = json.loads((destination / ".apex-builder.json").read_text(encoding="utf-8"))
    assert metadata == {
        "template_url": str(template),
        "template_ref": "main",
        "template_commit": template_commit,
        "toolkit_ref": "v0.3.0",
    }
    assert _git("remote", cwd=destination) == "template-upstream"
    for side in ("player", "referee"):
        init = (destination / side / "gym_v1" / "__init__.py").read_text(encoding="utf-8")
        referee = (destination / side / "gym_v1" / "referee.py").read_text(encoding="utf-8")
        assert init.startswith("# VENDORED from apex-competitions-builder v0.3.0")
        assert "from gym_v1.client import PlayerClient" in init
        assert "from apex_sdk.gym_v1" not in init
        assert "from gym_v1.client import PlayerClient" in referee
