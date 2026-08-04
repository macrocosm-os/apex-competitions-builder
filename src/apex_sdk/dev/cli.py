"""`apex-dev` — run and preflight a competition spec locally, exactly like the platform would.

Commands:
    apex-dev preflight --spec ./spec.yaml [--input fixtures/input.json]
                       [--submission <path>] [--env stage]
        Validate the spec against apex.competition.v1, enforce resource ceilings, and
        (if given) validate --input against the spec's input_schema and --submission against
        the declared submission.artifact_type (json/csv/onnx/wasm/torchscript/code/archive).
        No Docker required. This is the gate designers run before opening a registry PR.

    apex-dev run --spec ./spec.yaml --input fixtures/input.json --submission <path>
                 (--dockerfile <path> [--context <dir>] | --image <local-tag>) [--env stage]
        Execute a SOLO spec's eval locally in Docker, mirroring the platform's SoloRunner:
        write the submission to submission.target_path and the round input to
        /data/input.json, run entrypoints.evaluate.command under the spec's resource limits
        and network policy, then read + validate /data/result.json. Either build the player
        image locally from --dockerfile or reuse a prebuilt local --image. Duel execution is
        not implemented yet (prints the plan and exits 3).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from jsonschema import Draft202012Validator

from apex_sdk.dev.artifacts import ArtifactError, check_artifact, materialize
from apex_sdk.spec import LoadedSpec, SpecError, _parse_mem_to_mi, load_spec, submission_advisories


def _load(spec_path: str, env: str) -> LoadedSpec:
    try:
        return load_spec(spec_path, env=env)
    except SpecError as e:
        print(f"✗ spec invalid:\n{e}", file=sys.stderr)
        raise SystemExit(2)


def _validate_input(spec: LoadedSpec, input_path: str) -> None:
    if not spec.input_schema:
        print("• input_schema is empty; skipping fixture validation")
        return
    p = Path(input_path)
    if not p.is_file():
        print(f"✗ input fixture not found: {p}", file=sys.stderr)
        raise SystemExit(2)
    try:
        fixture = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        print(f"✗ input fixture is not valid JSON: {e}", file=sys.stderr)
        raise SystemExit(2)
    errors = sorted(Draft202012Validator(spec.input_schema).iter_errors(fixture), key=lambda e: list(e.path))
    if errors:
        print("✗ input fixture failed the spec's input_schema:", file=sys.stderr)
        for e in errors:
            loc = "/".join(str(x) for x in e.path) or "<root>"
            print(f"  - {loc}: {e.message}", file=sys.stderr)
        raise SystemExit(2)
    print(f"✓ input fixture valid against input_schema ({p})")


def _validate_artifact(spec: LoadedSpec, submission_path: str) -> None:
    """Check a local artifact against the spec's submission block (exit 2 on mismatch)."""
    try:
        check_artifact(submission_path, spec)
    except ArtifactError as e:
        raise _die(f"submission artifact rejected:\n{e}", 2)
    print(f"✓ submission valid for artifact_type: {spec.artifact_type} ({submission_path})")


def _print_advisories(spec: LoadedSpec) -> None:
    for note in submission_advisories(spec.raw):
        print(f"⚠ {note}")


def cmd_preflight(args: argparse.Namespace) -> None:
    spec = _load(args.spec, args.env)
    print(f"✓ spec valid: {spec.id} v{spec.version} (kind={spec.kind}, env={args.env})")
    _print_advisories(spec)
    if args.input:
        _validate_input(spec, args.input)
    if args.submission:
        _validate_artifact(spec, args.submission)
    print("✓ preflight passed")


def _die(msg: str, code: int = 1) -> "SystemExit":
    print(f"✗ {msg}", file=sys.stderr)
    return SystemExit(code)


def _require_docker() -> None:
    if shutil.which("docker") is None:
        raise _die("docker CLI not found on PATH; apex-dev run needs Docker.", 4)


def _mem_limit_to_docker(mem_limit: str) -> str:
    """Convert a k8s memory quantity (e.g. 512Mi, 1.5Gi) to a docker --memory value in bytes."""
    mi = _parse_mem_to_mi(mem_limit)
    return f"{int(mi * 1024 * 1024)}b"


def _build_image(dockerfile: str, context: str | None, spec: LoadedSpec) -> str:
    df = Path(dockerfile)
    if not df.is_file():
        raise _die(f"--dockerfile not found: {df}", 2)
    ctx = Path(context) if context else df.parent
    if not ctx.is_dir():
        raise _die(f"--context is not a directory: {ctx}", 2)
    tag = f"apex-dev-{spec.id}:local"
    print(f"• building player image {tag} (dockerfile={df}, context={ctx})")
    rc, _ = _docker(["build", "-f", str(df), "-t", tag, str(ctx)])
    if rc != 0:
        raise _die(f"docker build failed (exit {rc})", rc or 1)
    return tag


def _docker(args: list[str], timeout: int | None = None) -> tuple[int, str]:
    """Run `docker <args>`, streaming combined output to stderr; return (returncode, output).

    Output is captured (not inherited) so this works under pytest's capture too. On timeout
    a TimeoutExpired propagates to the caller after partial output is flushed.
    """
    try:
        proc = subprocess.run(
            ["docker", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        if e.output:
            print(e.output, file=sys.stderr, end="")
        raise
    if proc.stdout:
        print(proc.stdout, file=sys.stderr, end="")
    return proc.returncode, proc.stdout or ""


def _run_solo(spec: LoadedSpec, args: argparse.Namespace) -> None:
    if not args.submission:
        raise _die("--submission is required for a solo run (the miner artifact to evaluate).", 2)
    submission_src = Path(args.submission)
    if not submission_src.exists():
        raise _die(f"--submission not found: {submission_src}", 2)

    has_dockerfile = bool(args.dockerfile)
    has_image = bool(args.image)
    if has_dockerfile == has_image:
        raise _die("provide exactly one of --dockerfile or --image.", 2)

    _validate_artifact(spec, args.submission)
    _require_docker()
    image = _build_image(args.dockerfile, args.context, spec) if has_dockerfile else args.image

    s = spec.raw
    ep = s["entrypoints"]["evaluate"]
    command = ep["command"]
    timeout_s = int(ep["timeout_s"])
    network_disabled = ep.get("network_disabled", True)
    target_path = s["submission"]["target_path"]
    res = s["resources"]

    with tempfile.TemporaryDirectory(prefix="apex-dev-run-") as tmp:
        tmpdir = Path(tmp)
        data_dir = tmpdir / "data"
        data_dir.mkdir()
        # The image runs as a non-root user (uid 1000, like the platform sandbox); make the
        # bind-mounted /data writable so it can write result.json on Linux hosts too.
        data_dir.chmod(0o777)
        (data_dir / "input.json").write_bytes(Path(args.input).read_bytes())
        # Lay the artifact out as the platform would: a file, or an extracted tree for archives.
        submission_host = materialize(submission_src, spec, tmpdir)
        result_path = data_dir / "result.json"

        name = f"apex-dev-{spec.id}-{uuid.uuid4().hex[:8]}"
        run_args = [
            "run",
            "--rm",
            "--name",
            name,
            "--memory",
            _mem_limit_to_docker(res["mem_limit"]),
            "--cpus",
            str(res["cpu_limit"]),
            "-v",
            f"{data_dir}:/data",
            "-v",
            f"{submission_host}:{target_path}:ro",
        ]
        if network_disabled:
            run_args += ["--network", "none"]
        run_args += [image, *command]

        print(f"• running eval: image={image} network={'none' if network_disabled else 'default'} timeout={timeout_s}s")
        kind = "extracted tree" if spec.is_archive_submission else "file"
        print(f"  submission ({kind}) -> {target_path}, input -> /data/input.json")
        try:
            rc, _ = _docker(run_args, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "kill", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            raise _die(f"eval exceeded timeout_s={timeout_s}; container killed.", 5)

        if rc != 0:
            raise _die(f"eval container exited non-zero (exit {rc}).", rc or 1)

        if not result_path.is_file():
            raise _die("eval did not write /data/result.json.", 6)
        try:
            result = json.loads(result_path.read_text())
        except json.JSONDecodeError as e:
            raise _die(f"/data/result.json is not valid JSON: {e}", 6)

        _validate_solo_result(result)
        print("\n✓ eval succeeded. result.json:")
        print(json.dumps(result, indent=2, sort_keys=True))
        raise SystemExit(0)


def _validate_solo_result(result: object) -> None:
    if not isinstance(result, dict):
        raise _die(f"result.json must be a JSON object, got {type(result).__name__}.", 6)
    # bool is a subclass of int/float — reject it explicitly for numeric fields.
    for field in ("raw_score", "eval_time_in_seconds"):
        val = result.get(field)
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise _die(f"result.json.{field} must be a number, got {val!r}.", 6)
    if not isinstance(result.get("metadata"), dict):
        raise _die(f"result.json.metadata must be an object, got {result.get('metadata')!r}.", 6)


def cmd_run(args: argparse.Namespace) -> None:
    spec = _load(args.spec, args.env)
    _validate_input(spec, args.input)
    # Every competition is now referee-driven: the miner submission runs in an isolated player
    # sandbox and the competition-owned referee sandbox scores it (a solo eval is a 1-player
    # duel). For solo we still validate the player args so mistakes surface as exit 2.
    _print_advisories(spec)
    if not spec.is_duel:
        _validate_solo_args(spec, args)
    _print_plan(spec, args.env)
    print(
        "\n⚠ Referee-driven local run (player + referee sandboxes on a shared network) is not\n"
        "  implemented in `apex-dev run` yet. `apex-dev preflight` + the plan above validate the\n"
        "  full contract; run on stage to execute. A local 2-sandbox harness is a follow-up.",
        file=sys.stderr,
    )
    raise SystemExit(3)


def _validate_solo_args(spec: LoadedSpec, args: argparse.Namespace) -> None:
    """Validate the player-run args for a solo spec (exit 2 on error)."""
    if not args.submission:
        raise _die("--submission is required for a solo run (the miner artifact to evaluate).", 2)
    src = Path(args.submission)
    if not src.exists():
        raise _die(f"--submission not found: {args.submission}", 2)
    if src.is_dir() and not spec.is_archive_submission:
        raise _die(
            f"--submission {args.submission} is a directory, but artifact_type: "
            f"{spec.artifact_type} expects a single file.",
            2,
        )
    if not src.is_dir() and not src.is_file():
        raise _die(f"--submission is neither a file nor a directory: {args.submission}", 2)
    if bool(args.dockerfile) == bool(args.image):
        raise _die("provide exactly one of --dockerfile or --image.", 2)
    _validate_artifact(spec, args.submission)


def _print_plan(spec: LoadedSpec, env: str) -> None:
    s = spec.raw
    ep = s["entrypoints"]["evaluate"]
    print("\nExecution plan")
    print(f"  kind           : {s['kind']}")
    if not spec.is_duel and spec.num_player_sandboxes > 1:
        print(f"  player sandboxes: {spec.num_player_sandboxes} (isolated copies of the same submission)")
    print(f"  player image   : {s['image']['ref']}@{s['image']['digest']}")
    sub = s["submission"]
    dest = f"{sub['target_path']}/ (extracted)" if spec.is_archive_submission else sub["target_path"]
    print(f"  submission     : {sub['artifact_type']} -> {dest}")
    if spec.is_archive_submission:
        a = sub["archive"]
        print(
            f"  bundle         : {a['format']}, entry={a['entry_file']}, "
            f"<={a['max_files']} files, <={a['max_uncompressed_mb']}MB extracted"
        )
    print(
        f"  resources      : cpu={s['resources']['cpu_limit']} mem={s['resources']['mem_limit']} "
        f"gpu={s['resources']['gpu_count']} (env={env})"
    )
    print(f"  player cmd     : {ep['command']}")
    print(f"  player to      : {ep['timeout_s']}s")
    r = s["referee"]
    print(f"  referee proto  : {r['protocol']}")
    print(f"  referee image  : {r['image']['ref']}@{r['image']['digest']}")
    print(f"  referee to     : {r['timeout_s']}s")
    if spec.is_duel:
        d = s["duel"]
        print(
            f"  duel match     : {d['players_per_match']} players, "
            f"{d['num_games_default']} games, swap_sides={d['swap_sides']}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="apex-dev", description="Local dev harness for Apex competitions.")
    sub = parser.add_subparsers(dest="command", required=True)

    pf = sub.add_parser("preflight", help="validate a spec (+ optional input fixture and submission); no Docker")
    pf.add_argument("--spec", required=True, help="path to spec.yaml")
    pf.add_argument("--input", help="path to an input fixture JSON to validate against input_schema")
    pf.add_argument(
        "--submission",
        help="path to a sample artifact to check against submission.artifact_type "
        "(a directory is accepted for artifact_type: archive)",
    )
    pf.add_argument("--env", default="stage", choices=["stage", "prod"], help="resource-ceiling env (default: stage)")
    pf.set_defaults(func=cmd_preflight)

    run = sub.add_parser("run", help="run a solo spec's eval locally in Docker")
    run.add_argument("--spec", required=True, help="path to spec.yaml")
    run.add_argument("--input", required=True, help="path to the round input fixture JSON")
    run.add_argument(
        "--submission",
        help="path to the miner artifact to evaluate (required for solo); a directory is accepted "
        "for artifact_type: archive and is laid out as the extracted submission tree",
    )
    run.add_argument("--dockerfile", help="build the player image from this Dockerfile (build context = --context)")
    run.add_argument("--context", help="docker build context for --dockerfile (default: the Dockerfile's directory)")
    run.add_argument("--image", help="use this prebuilt local image tag instead of building")
    run.add_argument("--env", default="stage", choices=["stage", "prod"], help="resource-ceiling env (default: stage)")
    run.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
