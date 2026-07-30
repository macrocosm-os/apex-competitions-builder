"""Every structural gate must fire — the player's startup validation depends on it."""

import pytest

from env.metric import NUM_CLASSES
from env.submission_io import EXPECTED_HEADER, SubmissionError, read_submission

HEADER = ",".join(EXPECTED_HEADER)
ROW = ",".join(["0.111111"] * NUM_CLASSES)


def _write(tmp_path, text: str, name: str = "submission.csv"):
    p = tmp_path / name
    p.write_text(text)
    return p


def test_valid_submission_parses(tmp_path):
    rows = read_submission(_write(tmp_path, f"{HEADER}\n1,{ROW}\n2,{ROW}\n"))
    assert sorted(rows) == [1, 2]
    assert len(rows[1]) == NUM_CLASSES


def test_missing_file_gate(tmp_path):
    with pytest.raises(SubmissionError) as ei:
        read_submission(tmp_path / "nope.csv")
    assert ei.value.gate == "missing_file"


@pytest.mark.parametrize(
    "text,gate",
    [
        ("", "empty_file"),
        (f"{HEADER}\n", "empty_file"),
        (f"id,wrong,cols\n1,{ROW}\n", "bad_header"),
        (",".join(c.lower() for c in EXPECTED_HEADER) + f"\n1,{ROW}\n", "bad_header"),
        (f"{HEADER}\n1,0.5,0.5\n", "wrong_width"),
        (f"{HEADER}\nabc,{ROW}\n", "bad_id"),
        (f"{HEADER}\n1,{ROW}\n1,{ROW}\n", "duplicate_id"),
        (f"{HEADER}\n1," + ",".join(["x"] * NUM_CLASSES) + "\n", "bad_value"),
    ],
)
def test_structural_gates(tmp_path, text, gate):
    with pytest.raises(SubmissionError) as ei:
        read_submission(_write(tmp_path, text))
    assert ei.value.gate == gate


def test_tolerates_bom_and_crlf(tmp_path):
    p = tmp_path / "s.csv"
    p.write_bytes(b"\xef\xbb\xbf" + f"{HEADER}\r\n1,{ROW}\r\n".encode())
    assert sorted(read_submission(p)) == [1]


def test_nan_parses_here_and_is_charged_by_the_metric(tmp_path):
    # Deliberate split of responsibility: the parser accepts NaN structurally so the referee's
    # row_gate can charge it and report a gate histogram, rather than failing the whole file.
    rows = read_submission(_write(tmp_path, f"{HEADER}\n1,nan," + ",".join(["0.111111"] * 8) + "\n"))
    from env.metric import row_gate

    assert row_gate(rows[1]) == "non_finite"
