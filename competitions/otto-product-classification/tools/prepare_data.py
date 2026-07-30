"""Download the Otto Group source data and derive the competition's train/test split.

    python tools/prepare_data.py                    # download from Kaggle, split, write manifest
    python tools/prepare_data.py --from-file t.csv  # use a local train.csv, no network
    python tools/prepare_data.py --check            # re-verify hashes against data/MANIFEST.sha256

Writes:
    data/train.csv           id,feat_1..feat_93,target   (public: the miner training set)
    data/test_features.csv   id,feat_1..feat_93          (public: what miners predict on)
    private/test_labels.csv  id,target                   (PRIVATE: handed to Macrocosmos for R2)
    data/MANIFEST.sha256     hash + row count + byte size for all four files (committed)

Stdlib only — no `kaggle` CLI, no pandas. Everything is written with a fixed column order,
ascending ids, integers copied through unformatted, and "\\n" line endings, so regeneration is
byte-identical on any machine. That is what makes MANIFEST.sha256 the real reproducibility
contract rather than a hopeful checksum.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

COMP_DIR = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(COMP_DIR)]

from env.metric import CLASSES  # noqa: E402
from env.split import SPLIT_SALT, TEST_DEN, TEST_NUM, stratified_split  # noqa: E402

KAGGLE_COMP = "otto-group-product-classification-challenge"
KAGGLE_URL = f"https://www.kaggle.com/api/v1/competitions/data/download/{KAGGLE_COMP}/train.csv"
RULES_URL = f"https://www.kaggle.com/c/{KAGGLE_COMP}/rules"

NUM_FEATURES = 93
FEATURES = tuple(f"feat_{i}" for i in range(1, NUM_FEATURES + 1))
SOURCE_HEADER = ("id", *FEATURES, "target")


def _kaggle_auth() -> tuple[str, str]:
    cfg = Path.home() / ".kaggle" / "kaggle.json"
    if not cfg.is_file():
        raise SystemExit(
            f"✗ {cfg} not found. Create a Kaggle API token (Account -> Create New API Token)\n"
            f"  or pass --from-file <path to train.csv> to skip the download entirely."
        )
    data = json.loads(cfg.read_text())
    return data["username"], data["key"]


def download_source() -> bytes:
    """Fetch train.csv bytes from Kaggle. Returns the decompressed CSV."""
    user, key = _kaggle_auth()
    token = base64.b64encode(f"{user}:{key}".encode()).decode()
    req = urllib.request.Request(KAGGLE_URL, headers={"Authorization": f"Basic {token}"})
    print(f"• downloading {KAGGLE_COMP}/train.csv from Kaggle as {user}")
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            payload = resp.read()
    except urllib.error.HTTPError as e:
        # Kaggle answers 403 (and sometimes 200 with an HTML login page) until the account has
        # accepted this competition's rules once, in a browser. Say so precisely: this is the
        # single most likely first-run failure and a generic HTTP error is useless here.
        if e.code in (401, 403):
            raise SystemExit(
                f"✗ Kaggle returned HTTP {e.code}. Accept the competition rules once in a browser:\n"
                f"    {RULES_URL}\n"
                f"  then re-run. (Or pass --from-file <path to train.csv>.)"
            ) from None
        raise SystemExit(f"✗ Kaggle download failed: HTTP {e.code} {e.reason}") from None

    if payload[:2] == b"PK":  # a zip, as the competitions endpoint usually returns
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            names = [n for n in z.namelist() if n.endswith(".csv")]
            if not names:
                raise SystemExit(f"✗ downloaded zip contains no .csv: {z.namelist()}")
            return z.read(names[0])
    if payload.lstrip()[:1] == b"<":
        raise SystemExit(
            f"✗ Kaggle returned HTML instead of data — the rules have probably not been accepted:\n    {RULES_URL}"
        )
    return payload


def parse_source(raw: bytes) -> tuple[dict[int, list[str]], dict[int, str]]:
    """Parse the source train.csv into ({id: feature strings}, {id: class})."""
    reader = csv.reader(io.StringIO(raw.decode("utf-8-sig")))
    header = next(reader)
    if tuple(h.strip() for h in header) != SOURCE_HEADER:
        raise SystemExit(f"✗ unexpected source header: got {len(header)} columns starting {header[:3]}")

    features: dict[int, list[str]] = {}
    labels: dict[int, str] = {}
    for lineno, record in enumerate(reader, start=2):
        if not record:
            continue
        if len(record) != NUM_FEATURES + 2:
            raise SystemExit(f"✗ source line {lineno}: expected {NUM_FEATURES + 2} fields, got {len(record)}")
        row_id = int(record[0])
        if row_id in features:
            raise SystemExit(f"✗ source line {lineno}: duplicate id {row_id}")
        cls = record[-1].strip()
        if cls not in CLASSES:
            raise SystemExit(f"✗ source line {lineno}: unknown class {cls!r}")
        features[row_id] = record[1:-1]
        labels[row_id] = cls
    return features, labels


def _write_csv(path: Path, header: tuple[str, ...], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def _digest(path: Path) -> tuple[str, int, int]:
    raw = path.read_bytes()
    return hashlib.sha256(raw).hexdigest(), raw.count(b"\n") - 1, len(raw)


def write_manifest(path: Path, entries: dict[str, Path], source_sha: str, source_bytes: int) -> None:
    lines = [
        "# otto_product_classification data manifest — the reproducibility contract.",
        "# Regenerate with `python tools/prepare_data.py`; verify with `--check`.",
        f"# split identity: salt={SPLIT_SALT!r} test_fraction={TEST_NUM}/{TEST_DEN}",
        f"{source_sha}  upstream/train.csv  rows=61878  bytes={source_bytes}",
    ]
    for name, p in entries.items():
        sha, rows, size = _digest(p)
        lines.append(f"{sha}  {name}  rows={rows}  bytes={size}")
    path.write_text("\n".join(lines) + "\n")


def check_manifest(path: Path, base: Path) -> int:
    """Recompute hashes and diff against the manifest. Returns a process exit code."""
    if not path.is_file():
        print(f"✗ manifest not found: {path}", file=sys.stderr)
        return 1
    bad = 0
    for line in path.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        sha, name, *_ = line.split()
        if name.startswith("upstream/"):
            continue  # the source download is not kept on disk
        target = base / name
        if not target.is_file():
            print(f"✗ missing: {name}")
            bad += 1
            continue
        actual, _, _ = _digest(target)
        if actual != sha:
            print(f"✗ hash drift: {name}\n    expected {sha}\n    actual   {actual}")
            bad += 1
        else:
            print(f"✓ {name}")
    return 1 if bad else 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-file", help="path to a local Otto train.csv (skips the network)")
    ap.add_argument("--out-dir", default=str(COMP_DIR), help="competition directory to write into")
    ap.add_argument("--check", action="store_true", help="verify existing files against data/MANIFEST.sha256")
    args = ap.parse_args()

    out = Path(args.out_dir)
    if args.check:
        raise SystemExit(check_manifest(out / "data" / "MANIFEST.sha256", out))

    raw = Path(args.from_file).read_bytes() if args.from_file else download_source()
    source_sha = hashlib.sha256(raw).hexdigest()
    features, labels = parse_source(raw)
    print(f"• source: {len(labels)} rows, sha256 {source_sha}")

    train_ids, test_ids = stratified_split(labels)
    print(f"• split : {len(train_ids)} train / {len(test_ids)} test ({TEST_NUM}/{TEST_DEN}, stratified)")
    per_class = {c: sum(1 for i in test_ids if labels[i] == c) for c in CLASSES}
    for c in CLASSES:
        print(f"    {c}: test={per_class[c]}")

    train_csv = out / "data" / "train.csv"
    test_csv = out / "data" / "test_features.csv"
    labels_csv = out / "private" / "test_labels.csv"
    _write_csv(train_csv, SOURCE_HEADER, [[str(i), *features[i], labels[i]] for i in train_ids])
    _write_csv(test_csv, ("id", *FEATURES), [[str(i), *features[i]] for i in test_ids])
    _write_csv(labels_csv, ("id", "target"), [[str(i), labels[i]] for i in test_ids])

    manifest = out / "data" / "MANIFEST.sha256"
    write_manifest(
        manifest,
        {
            "data/train.csv": train_csv,
            "data/test_features.csv": test_csv,
            "private/test_labels.csv": labels_csv,
        },
        source_sha,
        len(raw),
    )

    labels_sha, _, _ = _digest(labels_csv)
    print(f"\n✓ wrote {train_csv.name}, {test_csv.name}, {labels_csv} and {manifest.name}")
    print("\nPaste these into spec.yaml and env/labels.py:")
    print(f"  spec.yaml     private_data[0].sha256 : {labels_sha}")
    print(f"  env/labels.py TEST_LABELS_SHA256     : {labels_sha}")
    print(f"  env/labels.py EXPECTED_TEST_ROWS     : {len(test_ids)}")
    print(f"  spec.yaml     screening.expected_rows: {len(test_ids)}")
    print(f"\n⚠ {labels_csv} is the PRIVATE ground truth. Hand it to a Macrocosmos maintainer for")
    print("  upload to R2; never commit it and never bake it into an image.")


if __name__ == "__main__":
    main()
