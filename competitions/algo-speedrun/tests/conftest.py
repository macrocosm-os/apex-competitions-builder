"""Test setup for algo_speedrun.

`test_screen.py` needs nothing beyond the stdlib and always runs. `test_train_runner.py`
and `test_referee.py` exercise real training against real nanochat code (per HANDOFF.md's
"actually run it, don't just reason about it" standard) and need torch + a nanochat
checkout on the path -- neither is a normal pip dependency of this repo (nanochat is
fetched at referee image BUILD time, see referee/Dockerfile), so those tests skip
themselves (rather than fail) when the environment isn't set up, via each test module's
own `pytest.importorskip`.

To actually run the full suite locally:
    pip install torch pyarrow numpy requests filelock kernels psutil rustbpe tiktoken
    curl -sL https://github.com/karpathy/nanochat/archive/<pinned commit, see
        ../baseline/PROVENANCE.md>.tar.gz | tar -xz --strip-components=1 -C /tmp/nanochat_src
    mv /tmp/nanochat_src/nanochat /tmp/nanochat_src/../nanochat  # nanochat/ importable
    PYTHONPATH=/tmp/nanochat_src/.. pytest competitions/algo-speedrun/tests/
"""

from __future__ import annotations

import sys
from pathlib import Path

REFEREE_DIR = Path(__file__).resolve().parent.parent / "referee"
if str(REFEREE_DIR) not in sys.path:
    sys.path.insert(0, str(REFEREE_DIR))
