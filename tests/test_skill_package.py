from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "apex-competition-builder"


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


def test_skill_keeps_competition_work_outside_the_toolkit() -> None:
    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "Never implement a competition inside the toolkit" in text
    assert "apex-competition-hello-world" in text
    assert "template-upstream" in text
    assert "player/gym_v1/" in text
    assert "referee/gym_v1/" in text
    assert "do not guess a package from PyPI" in text
