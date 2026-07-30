"""The one submission-CSV parser, shared by the player, the referee, and the tools.

Owns STRUCTURAL validity only — the shape of the file. Per-row *value* judgement lives in
env.metric.row_gate so the referee stays the sole authority on what a row is worth; a player
that could "helpfully" repair a row would be able to change its own score.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

from .metric import CLASSES, NUM_CLASSES

EXPECTED_HEADER: tuple[str, ...] = ("id", *CLASSES)


class SubmissionError(ValueError):
    """A structural problem with the whole submission file. Carries a gate name."""

    def __init__(self, gate: str, detail: str = "") -> None:
        self.gate = gate
        self.detail = detail
        super().__init__(f"{gate}: {detail}" if detail else gate)


def read_submission(path: str | os.PathLike) -> dict[int, list[float]]:
    """Parse a submission CSV into {id: [p1..p9]}.

    Structural failures raise SubmissionError with one of these gates:
        missing_file, empty_file, bad_header, bad_id, duplicate_id, wrong_width, bad_value
    Tolerates a UTF-8 BOM, CRLF line endings, and a trailing newline; rejects anything else.
    ~18.5k rows parse in ~0.2 s and cost ~8 MB resident.
    """
    p = Path(path)
    if not p.is_file():
        raise SubmissionError("missing_file", str(p))

    # utf-8-sig transparently strips a BOM if present; newline="" lets csv handle CRLF.
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            raise SubmissionError("empty_file", str(p)) from None
        if tuple(h.strip() for h in header) != EXPECTED_HEADER:
            raise SubmissionError("bad_header", f"expected {','.join(EXPECTED_HEADER)}, got {','.join(header)}")

        rows: dict[int, list[float]] = {}
        for lineno, record in enumerate(reader, start=2):
            if not record:  # a bare trailing newline yields nothing; anything else is a shape error
                continue
            if len(record) != NUM_CLASSES + 1:
                raise SubmissionError("wrong_width", f"line {lineno}: expected {NUM_CLASSES + 1} fields")
            try:
                row_id = int(record[0])
            except ValueError:
                raise SubmissionError("bad_id", f"line {lineno}: {record[0]!r} is not an integer") from None
            if row_id in rows:
                raise SubmissionError("duplicate_id", f"line {lineno}: id {row_id} already seen")
            try:
                # NaN/Inf parse fine here by design — env.metric.row_gate charges them, so a
                # miner gets a scored round with a gate histogram rather than a hard failure.
                rows[row_id] = [float(v) for v in record[1:]]
            except ValueError:
                raise SubmissionError("bad_value", f"line {lineno}: non-numeric probability") from None

    if not rows:
        raise SubmissionError("empty_file", "header only, no data rows")
    return rows
