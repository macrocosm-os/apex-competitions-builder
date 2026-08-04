"""Check a local submission artifact against the `submission` block of a spec.

This is the artifact-side companion to spec validation: `apex-dev preflight --submission` and
`apex-dev run` use it so a designer's reference solution fails locally, with a readable reason,
instead of being rejected by the platform's Layer-1 screener after upload.

It mirrors the platform's *structural* checks only — the parts determined by the declared
`artifact_type` and the `screening` knobs that are cheap and dependency-free (parse validity,
magic bytes, extraction bounds, header/shape limits). It is deliberately NOT the AST guard, the
weights validator, or the sandbox: passing here means the artifact is well-formed for its type,
not that it is safe. The sandbox is the boundary.

Stdlib only, like the rest of the toolkit's runtime surface.
"""

from __future__ import annotations

import csv
import io
import json
import shutil
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from apex_sdk.spec import ARCHIVE_ARTIFACT_TYPE, LoadedSpec

_MB = 1024 * 1024

# A WebAssembly module starts with the \0asm magic followed by the u32 version (1).
WASM_MAGIC = b"\x00asm"
WASM_VERSION_1 = b"\x01\x00\x00\x00"


class ArtifactError(ValueError):
    """Raised when a local artifact does not match the spec's declared submission type."""


@dataclass
class _Problems:
    """Collects every problem found so one run reports them all, like spec validation does."""

    items: list[str] = field(default_factory=list)

    def add(self, msg: str) -> None:
        self.items.append(msg)

    def raise_if_any(self, path: Path, artifact_type: str) -> None:
        if not self.items:
            return
        lines = "\n".join(f"  - {p}" for p in self.items)
        raise ArtifactError(f"submission {path} does not match artifact_type: {artifact_type}\n{lines}")


def check_artifact(path: str | Path, spec: LoadedSpec) -> None:
    """Validate the artifact at `path` against `spec`'s submission block.

    Accepts a directory only for `artifact_type: archive`, where it is validated as the tree
    that would be bundled. Raises ArtifactError listing every problem found.
    """
    src = Path(path)
    artifact_type = spec.artifact_type
    screening = spec.raw.get("screening", {})
    problems = _Problems()

    if src.is_dir():
        if artifact_type != ARCHIVE_ARTIFACT_TYPE:
            raise ArtifactError(
                f"submission {src} is a directory, but artifact_type: {artifact_type} expects a single file"
            )
        _check_archive_tree(src, spec, screening, problems)
        problems.raise_if_any(src, artifact_type)
        return
    if not src.is_file():
        raise ArtifactError(f"submission not found: {src}")

    # The upload ceiling applies to every type; for archives it bounds the compressed bundle.
    max_bytes = spec.raw["submission"]["max_size_mb"] * _MB
    size = src.stat().st_size
    if size > max_bytes:
        problems.add(f"is {size / _MB:.2f}MB, over submission.max_size_mb {spec.raw['submission']['max_size_mb']}")
    if size == 0:
        problems.add("is empty")

    checker = {
        "json": _check_json,
        "csv": _check_csv,
        "wasm": _check_wasm,
        ARCHIVE_ARTIFACT_TYPE: _check_archive_file,
    }.get(artifact_type)
    # code / onnx / torchscript have no dependency-free structural check beyond the size and
    # emptiness bounds above; their real validation is the platform's screener and your loader.
    if checker is not None and size > 0:
        checker(src, spec, screening, problems)

    problems.raise_if_any(src, artifact_type)


# --------------------------------------------------------------------------------------- json


def _json_depth(doc: object) -> int:
    """Max nesting depth of a parsed document, iteratively (no recursion limit to trip)."""
    depth = 0
    stack: list[tuple[object, int]] = [(doc, 1)]
    while stack:
        node, level = stack.pop()
        depth = max(depth, level)
        if isinstance(node, dict):
            stack.extend((v, level + 1) for v in node.values())
        elif isinstance(node, list):
            stack.extend((v, level + 1) for v in node)
    return depth


def _check_json(src: Path, spec: LoadedSpec, screening: dict, problems: _Problems) -> None:
    try:
        raw = src.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        problems.add(f"is not valid UTF-8: {e}")
        return
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as e:
        problems.add(f"is not valid JSON: {e}")
        return

    max_rows = screening.get("max_rows")
    if max_rows is not None and isinstance(doc, list) and len(doc) > max_rows:
        problems.add(f"has {len(doc)} top-level elements, over screening.max_rows {max_rows}")

    max_depth = screening.get("max_json_depth")
    if max_depth is not None:
        depth = _json_depth(doc)
        if depth > max_depth:
            problems.add(f"nests {depth} levels deep, over screening.max_json_depth {max_depth}")


# ---------------------------------------------------------------------------------------- csv


def _check_csv(src: Path, spec: LoadedSpec, screening: dict, problems: _Problems) -> None:
    try:
        text = src.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        problems.add(f"is not valid UTF-8: {e}")
        return
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        rows = list(reader)
    except csv.Error as e:
        # Includes "field larger than field limit", which is how an unquoted/unterminated quote
        # surfaces — a malformed row rather than a legitimately large one.
        problems.add(f"is not parseable as CSV: {e}")
        return
    if not rows:
        problems.add("has no rows; a CSV submission needs a header row")
        return

    header = rows[0]
    data_rows = rows[1:]

    max_columns = screening.get("max_columns")
    if max_columns is not None and len(header) > max_columns:
        problems.add(f"header has {len(header)} columns, over screening.max_columns {max_columns}")

    required = screening.get("required_columns")
    if required:
        missing = [c for c in required if c not in header]
        if missing:
            problems.add(f"header is missing screening.required_columns {missing} (header: {header})")

    max_rows = screening.get("max_rows")
    if max_rows is not None and len(data_rows) > max_rows:
        problems.add(f"has {len(data_rows)} data rows, over screening.max_rows {max_rows}")

    # A ragged row is the single most common way a hand-built CSV fixture is wrong.
    for i, row in enumerate(data_rows, start=2):
        if len(row) != len(header):
            problems.add(f"row {i} has {len(row)} fields but the header has {len(header)}")
            break


# --------------------------------------------------------------------------------------- wasm


def _check_wasm(src: Path, spec: LoadedSpec, screening: dict, problems: _Problems) -> None:
    with src.open("rb") as fh:
        preamble = fh.read(8)
    if preamble[:4] != WASM_MAGIC:
        problems.add(f"does not start with the WebAssembly magic {WASM_MAGIC!r} (got {preamble[:4]!r})")
        return
    if preamble[4:8] != WASM_VERSION_1:
        problems.add(f"declares WebAssembly version {preamble[4:8]!r}, expected {WASM_VERSION_1!r}")
    # Import and memory-page limits need a real wasm parser; the platform's screener does that.
    # Keeping this dependency-free means we validate the module header only.


# ------------------------------------------------------------------------------------ archive


def _normalize_member(name: str) -> str:
    """Normalize a member name to the path it extracts to, relative to the extraction root.

    `tar czf bundle.tar.gz -C pkg .` — the most common way a bundle gets made — names its members
    `./main.py`, and a zip may carry a trailing slash on directories. Both extract to the same
    place as the plain name, so compare and screen on the normalized form. `..` is deliberately
    NOT collapsed: it is a rejection, not something to resolve away.
    """
    stripped = name.rstrip("/")
    if not stripped or stripped == ".":
        return "."
    return PurePosixPath(stripped).as_posix()


def _member_problem(name: str) -> str | None:
    """Return why an archive member name is unsafe to extract, else None. Takes a raw name."""
    if not name.strip():
        return "has an empty name"
    if name.startswith("/") or PurePosixPath(name).is_absolute():
        return "is an absolute path"
    if ".." in PurePosixPath(name).parts:
        return "contains a '..' component"
    if "\\" in name:
        return "contains a backslash; members must use POSIX separators"
    return None


@dataclass
class _Member:
    """One bundle member. `name` is normalized; `raw` is what the bundle actually declared."""

    name: str
    size: int
    is_dir: bool
    is_link: bool
    raw: str = ""

    @classmethod
    def make(cls, raw: str, size: int, is_dir: bool, is_link: bool) -> "_Member":
        return cls(name=_normalize_member(raw), size=size, is_dir=is_dir, is_link=is_link, raw=raw)


def _check_members(members: list[_Member], spec: LoadedSpec, screening: dict, problems: _Problems) -> None:
    """Validate a bundle's member list against `submission.archive` and the screening knobs."""
    archive = spec.archive or {}
    max_files = archive.get("max_files")
    max_uncompressed = archive.get("max_uncompressed_mb")
    entry_file = archive.get("entry_file")
    allowed_ext = screening.get("allowed_member_extensions")

    if max_files is not None and len(members) > max_files:
        problems.add(f"has {len(members)} members, over submission.archive.max_files {max_files}")

    total = sum(m.size for m in members)
    if max_uncompressed is not None and total > max_uncompressed * _MB:
        problems.add(f"extracts to {total / _MB:.2f}MB, over submission.archive.max_uncompressed_mb {max_uncompressed}")

    for m in members:
        # "." is the extraction root itself (`tar -C pkg .` emits it); it is not a file to screen.
        if m.name == ".":
            continue
        if m.is_link:
            problems.add(f"member {m.raw!r} is a link; links are rejected, not followed")
            continue
        # Screen the name the bundle declared, not the normalized one — normalization must never
        # be what makes an unsafe name look safe.
        why = _member_problem(m.raw)
        if why is not None:
            problems.add(f"member {m.raw!r} {why}")
            continue
        if not m.is_dir and allowed_ext and PurePosixPath(m.name).suffix not in allowed_ext:
            problems.add(
                f"member {m.raw!r} has an extension outside " f"screening.allowed_member_extensions {allowed_ext}"
            )

    wanted = _normalize_member(entry_file) if entry_file else None
    if wanted and not any(m.name == wanted and not m.is_dir for m in members):
        problems.add(
            f"does not contain submission.archive.entry_file {entry_file!r} "
            f"(members: {sorted(m.name for m in members if not m.is_dir)[:10]})"
        )


def _read_members(src: Path, fmt: str) -> list[_Member]:
    """List a bundle's members. Raises ArtifactError if it is not the declared format."""
    if fmt == "zip":
        if not zipfile.is_zipfile(src):
            raise ArtifactError(f"submission {src} is not a zip archive (submission.archive.format: zip)")
        with zipfile.ZipFile(src) as zf:
            return [
                _Member.make(
                    raw=i.filename,
                    size=i.file_size,
                    is_dir=i.is_dir(),
                    # Unix mode lives in the high 16 bits of external_attr; 0o120000 is S_IFLNK.
                    is_link=(i.external_attr >> 16) & 0o170000 == 0o120000,
                )
                for i in zf.infolist()
            ]

    mode = "r:gz" if fmt == "tar.gz" else "r:"
    try:
        with tarfile.open(src, mode) as tf:
            return [
                _Member.make(raw=m.name, size=m.size, is_dir=m.isdir(), is_link=m.issym() or m.islnk())
                for m in tf.getmembers()
            ]
    except tarfile.TarError as e:
        raise ArtifactError(f"submission {src} is not a {fmt} archive (submission.archive.format: {fmt}): {e}") from e


def _check_archive_file(src: Path, spec: LoadedSpec, screening: dict, problems: _Problems) -> None:
    fmt = (spec.archive or {}).get("format", "tar.gz")
    _check_members(_read_members(src, fmt), spec, screening, problems)


def _check_archive_tree(src: Path, spec: LoadedSpec, screening: dict, problems: _Problems) -> None:
    """Validate a directory as the tree that would be bundled, so `--submission ./pkg` works."""
    members: list[_Member] = []
    for p in sorted(src.rglob("*")):
        members.append(
            _Member.make(
                raw=p.relative_to(src).as_posix(),
                size=0 if p.is_dir() else p.stat().st_size,
                is_dir=p.is_dir(),
                is_link=p.is_symlink(),
            )
        )
    if not members:
        problems.add("is an empty directory")
    _check_members(members, spec, screening, problems)


# ------------------------------------------------------------------------------- materialize


def materialize(path: str | Path, spec: LoadedSpec, dest: Path) -> Path:
    """Lay the artifact out on the host the way the platform lays it out in the sandbox.

    Returns the host path to bind-mount at `submission.target_path`: a file for single-file
    artifact types, or a directory holding the extracted/copied tree for `archive`.
    """
    src = Path(path)
    if not spec.is_archive_submission:
        out = dest / "submission_artifact"
        out.write_bytes(src.read_bytes())
        return out

    out = dest / "submission_tree"
    if src.is_dir():
        shutil.copytree(src, out, symlinks=False, ignore=shutil.ignore_patterns("__pycache__"))
        return out

    out.mkdir(parents=True)
    fmt = (spec.archive or {}).get("format", "tar.gz")
    # Members were validated by check_artifact; extract regular files by hand anyway so this
    # never depends on tarfile's extraction filter (which differs across 3.11/3.12).
    if fmt == "zip":
        with zipfile.ZipFile(src) as zf:
            for info in zf.infolist():
                if info.is_dir() or _member_problem(info.filename) is not None:
                    continue
                target = out / _normalize_member(info.filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(info))
    else:
        with tarfile.open(src, "r:gz" if fmt == "tar.gz" else "r:") as tf:
            for member in tf.getmembers():
                if not member.isfile() or _member_problem(member.name) is not None:
                    continue
                fh = tf.extractfile(member)
                if fh is None:
                    continue
                target = out / _normalize_member(member.name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(fh.read())
    return out
