"""AST screen and safe materialization for `EXTRA_FILES` contents.

The platform's Layer-1 ASTGuard (spec.yaml's `screening` block) only ever inspects the
literal bytes at `submission.target_path` -- it has no idea that this competition's
single file can smuggle additional virtual files inside a string-valued dict. Anything
written into `EXTRA_FILES` is model/schedule/data-loader code the referee is about to
`exec` into its own training process, so it gets the same tripwire the platform would
have applied had it been the outer file, applied here instead. This is a tripwire, not
the sandbox boundary (security-checklist.md §6) -- the referee still runs with no
internet and a per-job filesystem, same as every other referee.

This module also owns writing EXTRA_FILES to disk (`materialize_extra_files`), not just
screening its contents: the two are the same trust boundary. A prior version of
referee.py did `scratch_path / rel_path` directly, which is a real arbitrary-file-write
vulnerability -- pathlib's `/` operator silently discards the left operand when the
right one is absolute (`Path("/tmp/x") / "/etc/passwd" == Path("/etc/passwd")`), and
`..` components can walk out of scratch_path even when relative. Every path is validated
before anything touches disk.
"""

from __future__ import annotations

import ast
from pathlib import Path, PurePosixPath

FORBIDDEN_MODULES = {
    "socket", "subprocess", "urllib", "http", "requests", "ctypes", "multiprocessing",
    "threading", "asyncio", "sys", "importlib", "pickle", "marshal", "shelve", "signal",
    "mmap", "resource", "pty", "code", "codeop",
}
FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__", "input", "open"}
FORBIDDEN_ATTR_CALLS = {
    ("os", "system"), ("os", "popen"), ("os", "remove"), ("os", "unlink"),
    ("os", "rename"), ("os", "chmod"), ("subprocess", "run"),
    ("torch", "load"),  # torch.load unpickles; the sandbox has nothing sensitive to
    # load, but there's no legitimate use of it in a training-loop override.
}
# Plain attribute ACCESS to ban even when not called -- e.g. `os.environ` read (not
# `os.environ()`), and `torch.hub` (banning the module reference, not one specific call,
# since `torch.hub.load(...)` is a NESTED attribute chain (Attribute(Attribute(Name)))
# that a single-level (module, attr) call check can't see; `ast.walk` still visits the
# inner `torch.hub` Attribute node on its own, so banning the access catches every call
# through it).
FORBIDDEN_ATTR_ACCESS = {("os", "environ"), ("torch", "hub")}
FORBIDDEN_DUNDER_ATTRS = {"__reduce__", "__reduce_ex__", "__subclasses__", "__globals__", "__builtins__"}
# Defining a dunder method by this name (not just accessing it) is also blocked --
# `def __reduce__(self):` is an ast.FunctionDef, never an ast.Attribute access.
FORBIDDEN_DUNDER_DEFS = {"__reduce__", "__reduce_ex__", "__getattr__", "__setattr__"}


class ScreenViolation(ValueError):
    """A virtual file in EXTRA_FILES failed the AST screen or path-safety check."""


def screen_source(path: str, source: str) -> None:
    """Raise ScreenViolation if `source` (the contents of a virtual file `path`)
    imports or calls anything on the forbidden list. Purely syntactic -- same tripwire
    philosophy as the platform's Layer-1, not a sandbox."""
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as e:
        raise ScreenViolation(f"{path}: not valid Python ({e})") from e

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_MODULES:
                    raise ScreenViolation(f"{path}: forbidden import '{alias.name}'")
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in FORBIDDEN_MODULES:
                raise ScreenViolation(f"{path}: forbidden import '{node.module}'")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALLS:
                raise ScreenViolation(f"{path}: forbidden call '{func.id}'")
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                if (func.value.id, func.attr) in FORBIDDEN_ATTR_CALLS:
                    raise ScreenViolation(f"{path}: forbidden call '{func.value.id}.{func.attr}'")
        elif isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_DUNDER_ATTRS:
                raise ScreenViolation(f"{path}: forbidden attribute access '.{node.attr}'")
            if isinstance(node.value, ast.Name) and (node.value.id, node.attr) in FORBIDDEN_ATTR_ACCESS:
                raise ScreenViolation(f"{path}: forbidden attribute access '{node.value.id}.{node.attr}'")
        elif isinstance(node, ast.FunctionDef):
            if node.name in FORBIDDEN_DUNDER_DEFS:
                raise ScreenViolation(f"{path}: forbidden method definition '{node.name}'")


def screen_extra_files(extra_files: dict[str, str]) -> None:
    for path, source in extra_files.items():
        screen_source(path, source)


def _validate_relative_path(rel_path: str) -> PurePosixPath:
    """A submission-controlled path must be relative, POSIX-style, and free of `..`
    components. Raises ScreenViolation otherwise. Does not touch the filesystem --
    escaping via symlinks/resolve() is checked separately in materialize_extra_files."""
    if not rel_path or rel_path.startswith("/") or rel_path.startswith("\\"):
        raise ScreenViolation(f"{rel_path!r}: EXTRA_FILES paths must be relative, not absolute")
    p = PurePosixPath(rel_path)
    if p.is_absolute() or ".." in p.parts or any(part in ("", ".") for part in p.parts[:-1]):
        raise ScreenViolation(f"{rel_path!r}: EXTRA_FILES paths may not contain '..' or empty components")
    return p


def materialize_extra_files(scratch_dir: Path, extra_files: dict[str, str]) -> None:
    """Validate and write every EXTRA_FILES entry under `scratch_dir`. Raises
    ScreenViolation for any path that isn't a safe relative path or that, once resolved,
    would land outside `scratch_dir` (covers `..` traversal and absolute-path override
    of the pathlib join)."""
    scratch_resolved = scratch_dir.resolve()
    for rel_path, source in extra_files.items():
        p = _validate_relative_path(rel_path)
        dest = (scratch_dir / str(p)).resolve()
        if dest != scratch_resolved and scratch_resolved not in dest.parents:
            raise ScreenViolation(f"{rel_path!r}: resolves outside the scratch directory")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(source)
