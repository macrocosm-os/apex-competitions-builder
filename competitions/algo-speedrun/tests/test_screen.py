"""Tests for referee/screen.py: the AST tripwire and safe EXTRA_FILES materialization.

No external dependencies -- always runs, unlike test_train_runner.py / test_referee.py.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from screen import ScreenViolation, materialize_extra_files, screen_extra_files, screen_source


def test_clean_source_passes():
    screen_source("schedule.py", "def lr_multiplier(step, n, cfg):\n    return 1.0\n")


@pytest.mark.parametrize(
    "source",
    [
        "import socket\n",
        "import subprocess\n",
        "import threading\n",
        "import sys\n",
        "import pickle\n",
        "import os\nos.system('ls')\n",
        "import os\nos.remove('/x')\n",
        "eval('1')\n",
        "exec('1')\n",
        "__import__('os')\n",
        "import torch\ntorch.load('x')\n",
        "import torch\ntorch.hub.load('x')\n",
        "import os\nprint(os.environ)\n",
        "class X:\n    def __reduce__(self):\n        return (1,)\n",
    ],
)
def test_forbidden_patterns_blocked(source):
    with pytest.raises(ScreenViolation):
        screen_source("evil.py", source)


def test_syntax_error_is_a_screen_violation_not_a_crash():
    with pytest.raises(ScreenViolation):
        screen_source("bad.py", "def f(:\n")


def test_screen_extra_files_screens_every_entry():
    with pytest.raises(ScreenViolation):
        screen_extra_files({"ok.py": "x = 1\n", "evil.py": "import socket\n"})
    screen_extra_files({"a.py": "x = 1\n", "b.py": "y = 2\n"})  # no violation -> returns normally


class TestMaterializeExtraFiles:
    def test_writes_relative_paths_inside_scratch(self):
        with tempfile.TemporaryDirectory() as scratch:
            scratch_path = Path(scratch)
            materialize_extra_files(scratch_path, {"model.py": "x = 1", "sub/data.py": "y = 2"})
            assert (scratch_path / "model.py").read_text() == "x = 1"
            assert (scratch_path / "sub" / "data.py").read_text() == "y = 2"

    def test_rejects_absolute_path(self):
        # Path("/tmp/x") / "/etc/passwd" == Path("/etc/passwd") in pathlib -- this is
        # exactly the bug materialize_extra_files exists to prevent (see its docstring).
        with tempfile.TemporaryDirectory() as scratch:
            with pytest.raises(ScreenViolation):
                materialize_extra_files(Path(scratch), {"/etc/passwd": "pwned"})

    def test_rejects_dotdot_traversal(self):
        with tempfile.TemporaryDirectory() as scratch:
            with pytest.raises(ScreenViolation):
                materialize_extra_files(Path(scratch), {"../../etc/passwd": "pwned"})

    def test_rejects_backslash_absolute_path(self):
        with tempfile.TemporaryDirectory() as scratch:
            with pytest.raises(ScreenViolation):
                materialize_extra_files(Path(scratch), {"\\windows\\system32\\evil": "pwned"})

    def test_nothing_written_outside_scratch_on_attack(self):
        with tempfile.TemporaryDirectory() as scratch, tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "pwned.py"
            rel = f"../{Path(outside).name}/pwned.py"
            with pytest.raises(ScreenViolation):
                materialize_extra_files(Path(scratch), {rel: "x = 1"})
            assert not target.exists()
