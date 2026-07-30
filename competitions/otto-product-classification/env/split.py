"""Deterministic stratified train/test split of the source dataset.

Shared by tools/prepare_data.py and the tests so the split can be re-derived and audited by
anyone. The split's identity is (SPLIT_SALT, TEST_NUM, TEST_DEN) plus the source file's
sha256 — all four are pinned in HANDOFF.md and data/MANIFEST.sha256.

Why a keyed hash and not random.Random(seed).shuffle: the stdlib Mersenne Twister's output
is *probably* stable across CPython releases, but that is not a guarantee the competition's
ground truth should rest on. sha256 is stable forever, and per-class independent keying means
adding or removing a class cannot shift any other class's assignment.
"""

from __future__ import annotations

import hashlib

SPLIT_SALT = "otto_product_classification/v1"  # changing this is a new competition, not a new round
TEST_NUM, TEST_DEN = 3, 10  # exactly 30% test, integer arithmetic


def bucket(row_id: int, salt: str = SPLIT_SALT) -> int:
    """Stable pseudo-random ordering key for one row id."""
    return int.from_bytes(hashlib.sha256(f"{salt}:{row_id}".encode()).digest()[:8], "big")


def stratified_split(labels: dict[int, str], salt: str = SPLIT_SALT) -> tuple[list[int], list[int]]:
    """Split labelled ids into (train_ids, test_ids), both ascending.

    Per class: order ids by bucket(), take the first len * TEST_NUM // TEST_DEN as test.
    Integer floor, deliberately not round(): Python's round() is banker's rounding, so
    round(4240.5) == 4240 and the split size would hinge on a float coincidence.
    """
    by_class: dict[str, list[int]] = {}
    for row_id, cls in labels.items():
        by_class.setdefault(cls, []).append(row_id)

    train: list[int] = []
    test: list[int] = []
    for cls in sorted(by_class):  # deterministic class order
        ids = sorted(by_class[cls], key=lambda i: (bucket(i, salt), i))
        k = len(ids) * TEST_NUM // TEST_DEN
        test += ids[:k]
        train += ids[k:]
    return sorted(train), sorted(test)
