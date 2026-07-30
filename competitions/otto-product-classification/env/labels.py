"""Loader for the private test labels — the ground truth, and the only secret in this design.

The platform fetches this object from R2, sha256-verifies it, and bind-mounts it READ-ONLY
into the REFEREE sandbox only (spec.private_data). This module NEVER reaches the network:
sandboxes have no egress, so an object that was not mounted is simply absent, and the correct
response is to fail loudly rather than score against nothing.

Absent, unreadable, hash-mismatched, or wrong-shaped => RuntimeError. The referee lets that
propagate, so no /data/result.json is written and the platform attributes the failure to the
REFEREE, not to the submission.
"""

from __future__ import annotations

import csv
import hashlib
import os
from pathlib import Path

from .metric import CLASS_INDEX

# Overridable so tools/local_eval.py can run without a /private mount. Safe: the referee's
# environment is platform-controlled and never miner-controlled.
TEST_LABELS_PATH = os.environ.get("TEST_LABELS_PATH", "/private/test_labels.csv")

# Pinned to the real Otto split produced by `python tools/prepare_data.py` (upstream train.csv
# sha256 11d3618a9d2dba32356c7c5f71ea2c790dcf1bd1ac1f0270f5f520b14329a3b4, 61,878 rows).
# Must stay equal to spec.yaml's private_data[0].sha256; changing either means a version bump.
TEST_LABELS_SHA256 = "87d85cf421180391e9f5224445bb23dd38ab0be000c35995d40e4ebe5c59912b"
EXPECTED_TEST_ROWS = 18559

EXPECTED_HEADER = ("id", "target")


def load_test_labels(path: str | os.PathLike | None = None, verify: bool = True) -> tuple[list[int], list[int]]:
    """Load the private ground truth as (ascending test ids, parallel class indices).

    Args:
        path: override the mount path (tools only).
        verify: check the bytes against TEST_LABELS_SHA256 and the row count against
            EXPECTED_TEST_ROWS. Pass False only for tests with synthetic labels.
    """
    p = Path(path if path is not None else TEST_LABELS_PATH)
    if not p.is_file():
        raise RuntimeError(
            f"private test labels not mounted at {p}. The platform is responsible for fetching "
            "spec.private_data and mounting it read-only; the referee must never fetch it. "
            "Refusing to score without ground truth."
        )

    raw = p.read_bytes()
    if verify:
        digest = hashlib.sha256(raw).hexdigest()
        if digest != TEST_LABELS_SHA256:
            raise RuntimeError(
                f"private test labels sha256 mismatch at {p}: got {digest}, pinned {TEST_LABELS_SHA256}. "
                "The ground truth does not match this spec version. Refusing to score."
            )

    reader = csv.reader(raw.decode("utf-8-sig").splitlines())
    header = next(reader, None)
    if header is None or tuple(h.strip() for h in header) != EXPECTED_HEADER:
        raise RuntimeError(f"private test labels header must be {','.join(EXPECTED_HEADER)}, got {header}")

    pairs: list[tuple[int, int]] = []
    for lineno, record in enumerate(reader, start=2):
        if not record:
            continue
        if len(record) != 2:
            raise RuntimeError(f"private test labels line {lineno}: expected 2 fields, got {len(record)}")
        try:
            row_id = int(record[0])
        except ValueError:
            raise RuntimeError(f"private test labels line {lineno}: {record[0]!r} is not an integer") from None
        cls = record[1].strip()
        if cls not in CLASS_INDEX:
            raise RuntimeError(f"private test labels line {lineno}: unknown class {cls!r}")
        pairs.append((row_id, CLASS_INDEX[cls]))

    if not pairs:
        raise RuntimeError(f"private test labels at {p} contain no rows")
    if verify and len(pairs) != EXPECTED_TEST_ROWS:
        raise RuntimeError(
            f"private test labels row count {len(pairs)} != expected {EXPECTED_TEST_ROWS}. "
            "A silently shrunk evaluation is exactly what the pin exists to prevent."
        )
    if len({row_id for row_id, _ in pairs}) != len(pairs):
        raise RuntimeError("private test labels contain duplicate ids")

    pairs.sort()
    return [row_id for row_id, _ in pairs], [ti for _, ti in pairs]
