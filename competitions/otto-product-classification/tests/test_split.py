"""The split defines the ground truth, so it is tested like a contract, not a helper."""

from env.split import SPLIT_SALT, TEST_DEN, TEST_NUM, bucket, stratified_split

CLASSES = tuple(f"Class_{i}" for i in range(1, 10))


def _labels(n: int = 1000) -> dict[int, str]:
    return {i: CLASSES[i % len(CLASSES)] for i in range(1, n + 1)}


def test_split_is_exhaustive_and_disjoint():
    labels = _labels()
    train, test = stratified_split(labels)
    assert set(train) | set(test) == set(labels)
    assert not set(train) & set(test)
    assert train == sorted(train) and test == sorted(test)


def test_split_is_stratified_with_integer_floor():
    labels = _labels(1000)
    _, test = stratified_split(labels)
    for cls in CLASSES:
        n_cls = sum(1 for c in labels.values() if c == cls)
        n_test = sum(1 for i in test if labels[i] == cls)
        # Integer floor, deliberately not round(): banker's rounding would make the split size
        # depend on a float coincidence.
        assert n_test == n_cls * TEST_NUM // TEST_DEN


def test_split_is_deterministic():
    labels = _labels()
    assert stratified_split(labels) == stratified_split(labels)


def test_split_is_stable_under_class_changes():
    # Per-class independent keying: dropping a class must not move any other class's rows.
    labels = _labels()
    _, test_full = stratified_split(labels)
    reduced = {i: c for i, c in labels.items() if c != "Class_9"}
    _, test_reduced = stratified_split(reduced)
    kept = {i for i in test_full if labels[i] != "Class_9"}
    assert set(test_reduced) == kept


def test_bucket_is_pinned_forever():
    # Golden values. sha256 is stable across CPython releases in a way random.Random is not;
    # if these ever change, the competition's ground truth has silently moved.
    assert bucket(1) == int.from_bytes(__import__("hashlib").sha256(f"{SPLIT_SALT}:1".encode()).digest()[:8], "big")
    assert bucket(1) != bucket(2)
    assert bucket(1, salt="other") != bucket(1)


def test_salt_changes_the_split():
    labels = _labels()
    _, a = stratified_split(labels)
    _, b = stratified_split(labels, salt="otto_product_classification/v2")
    assert a != b
