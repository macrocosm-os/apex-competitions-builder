"""`apex-dev` — run and preflight a competition spec locally, exactly like the platform would.

Commands:
    apex-dev preflight --spec ./spec.yaml [--input fixtures/input.json] [--env stage]
        Validate the spec against apex.competition.v1, enforce resource ceilings, and
        (if --input is given) validate the fixture against the spec's input_schema.
        No Docker required. This is the gate designers run before opening a registry PR.

    apex-dev run --spec ./spec.yaml --input fixtures/input.json --submission <path>
                 (--dockerfile <path> [--context <dir>] | --image <local-tag>)
                 [--private-data MOUNT_PATH=HOST_PATH ...] [--env stage]
        Validate the full execution contract for a spec and print the plan the platform
        would follow: the player sandbox, the referee sandbox, the submission path, and any
        private_data mounts. Every competition is referee-driven (a solo eval is a 1-player
        duel), and the local two-sandbox harness is a follow-up, so this currently exits 3
        after validating. For specs that declare `private_data`, pass one --private-data per
        entry; apex-dev verifies the same sha256 the platform verifies before every job.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from apex_sdk.spec import LoadedSpec, SpecError, _parse_mem_to_mi, load_spec


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


def cmd_preflight(args: argparse.Namespace) -> None:
    spec = _load(args.spec, args.env)
    print(f"✓ spec valid: {spec.id} v{spec.version} (kind={spec.kind}, env={args.env})")
    if args.input:
        _validate_input(spec, args.input)
    if spec.base_model:
        bm = spec.base_model
        print(
            f"• base_model: {bm['served_model']} (platform-served, referee-only) "
            f"budget={bm['max_tokens_per_episode']} tokens/episode "
            f"temperature={bm.get('temperature', 0)}"
        )
    for pd in spec.private_data:
        print(f"• private_data: {pd['uri']} -> {pd['mount_path']} (platform-mounted, ro, referee only)")
    print("✓ preflight passed")


def _die(msg: str, code: int = 1) -> "SystemExit":
    print(f"✗ {msg}", file=sys.stderr)
    return SystemExit(code)


# _require_docker / _mem_limit_to_docker / _build_image / _docker / _validate_game_result are
# the building blocks of the referee-driven local harness (player + referee sandboxes on a
# shared network), which `apex-dev run` does not implement yet. They are kept, not deleted, so
# that work has a correct foundation — in particular _validate_game_result encodes the real
# gym_v1 result contract, which the code it replaced did not.
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


def _validate_game_result(result: object) -> None:
    """Validate a referee's /data/result.json against the gym_v1 GameResult contract.

    Both solo and duel go through a referee, so both write the same shape:
    {raw_scores, winner, terminal_reason, steps, metadata}. (An earlier version of this
    checked a top-level `raw_score`/`eval_time_in_seconds` pair — that was the retired
    single-sandbox contract and never matched what apex_sdk.gym_v1.GameResult serializes.)
    """
    if not isinstance(result, dict):
        raise _die(f"result.json must be a JSON object, got {type(result).__name__}.", 6)
    scores = result.get("raw_scores")
    if not isinstance(scores, list) or not scores:
        raise _die(f"result.json.raw_scores must be a non-empty array, got {scores!r}.", 6)
    for i, v in enumerate(scores):
        # bool is a subclass of int/float — reject it explicitly for numeric fields.
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise _die(f"result.json.raw_scores[{i}] must be a number, got {v!r}.", 6)
    for field in ("winner", "steps"):
        val = result.get(field)
        if isinstance(val, bool) or not isinstance(val, int):
            raise _die(f"result.json.{field} must be an integer, got {val!r}.", 6)
    if not isinstance(result.get("terminal_reason"), str):
        raise _die(f"result.json.terminal_reason must be a string, got {result.get('terminal_reason')!r}.", 6)
    if not isinstance(result.get("metadata"), dict):
        raise _die(f"result.json.metadata must be an object, got {result.get('metadata')!r}.", 6)


def _resolve_private_data(spec: LoadedSpec, pairs: list[str]) -> list[tuple[Path, str]]:
    """Map --private-data MOUNT_PATH=HOST_PATH args onto the spec's private_data entries.

    On the platform these objects are fetched from R2 and sha256-verified before the job
    starts. Locally the designer supplies the file and we verify the SAME digest — so a
    stale or wrong local labels file fails loudly here instead of silently scoring against
    the wrong ground truth. Returns (host_path, mount_path) pairs for the REFEREE
    container's read-only bind mounts.
    """
    declared = {p["mount_path"]: p for p in spec.private_data}
    supplied: dict[str, Path] = {}

    for pair in pairs:
        mount, sep, host = pair.partition("=")
        if not sep or not mount.startswith("/") or not host:
            raise _die(f"--private-data must be MOUNT_PATH=HOST_PATH with an absolute MOUNT_PATH: {pair!r}", 2)
        if mount not in declared:
            raise _die(
                f"--private-data {mount} is not declared in the spec's private_data "
                f"(declared: {sorted(declared) or 'none'}).",
                2,
            )
        p = Path(host).expanduser()
        if not p.is_file():
            raise _die(f"--private-data host file not found: {host}", 2)
        supplied[mount] = p.resolve()

    missing = sorted(set(declared) - set(supplied))
    if missing:
        raise _die(
            "spec declares private_data with no local file supplied; add "
            + " ".join(f"--private-data {m}=<path>" for m in missing),
            2,
        )

    for mount, path in supplied.items():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != declared[mount]["sha256"]:
            raise _die(
                f"--private-data {mount} sha256 mismatch: local file is {digest}, "
                f"spec pins {declared[mount]['sha256']}",
                2,
            )

    return [(supplied[m], m) for m in sorted(supplied)]


def cmd_run(args: argparse.Namespace) -> None:
    spec = _load(args.spec, args.env)
    _validate_input(spec, args.input)
    # Every competition is now referee-driven: the miner submission runs in an isolated player
    # sandbox and the competition-owned referee sandbox scores it (a solo eval is a 1-player
    # duel). For solo we still validate the player args so mistakes surface as exit 2.
    if not spec.is_duel:
        _validate_solo_args(args)
    private_mounts = _resolve_private_data(spec, args.private_data)
    _print_plan(spec, args.env, private_mounts)
    print(
        "\n⚠ Referee-driven local run (player + referee sandboxes on a shared network) is not\n"
        "  implemented in `apex-dev run` yet. `apex-dev preflight` + the plan above validate the\n"
        "  full contract; run on stage to execute. A local 2-sandbox harness is a follow-up.",
        file=sys.stderr,
    )
    raise SystemExit(3)


def _validate_solo_args(args: argparse.Namespace) -> None:
    """Validate the player-run args for a solo spec (exit 2 on error)."""
    if not args.submission:
        raise _die("--submission is required for a solo run (the miner artifact to evaluate).", 2)
    if not Path(args.submission).is_file():
        raise _die(f"--submission not found: {args.submission}", 2)
    if bool(args.dockerfile) == bool(args.image):
        raise _die("provide exactly one of --dockerfile or --image.", 2)


def _print_plan(spec: LoadedSpec, env: str, private_mounts: list[tuple[Path, str]] | None = None) -> None:
    s = spec.raw
    ep = s["entrypoints"]["evaluate"]
    print("\nExecution plan")
    print(f"  kind           : {s['kind']}")
    print(f"  player image   : {s['image']['ref']}@{s['image']['digest']}")
    print(f"  submission     : {s['submission']['artifact_type']} -> {s['submission']['target_path']}")
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
    # The frozen model is reachable from the REFEREE only: that is what keeps the token
    # meter honest, so the plan states the topology explicitly.
    if spec.base_model:
        bm = spec.base_model
        print(
            f"  base model     : {bm['served_model']} -> referee only "
            f"({bm['max_tokens_per_episode']} tokens/episode, temp={bm.get('temperature', 0)})"
        )
    # private_data is REFEREE-only by contract: a miner-reachable container that can read the
    # answer key defeats the whole design. These never go on the player's mounts.
    for host_path, mount_path in private_mounts or []:
        print(f"  private mount  : {host_path} -> {mount_path} (referee only, ro)")
    if spec.private_data and not private_mounts:
        print("  private mount  : (none supplied — pass --private-data MOUNT_PATH=HOST_PATH)")
    if spec.is_duel:
        d = s["duel"]
        print(
            f"  duel match     : {d['players_per_match']} players, "
            f"{d['num_games_default']} games, swap_sides={d['swap_sides']}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="apex-dev", description="Local dev harness for Apex competitions.")
    sub = parser.add_subparsers(dest="command", required=True)

    pf = sub.add_parser("preflight", help="validate a spec (+ optional input fixture); no Docker")
    pf.add_argument("--spec", required=True, help="path to spec.yaml")
    pf.add_argument("--input", help="path to an input fixture JSON to validate against input_schema")
    pf.add_argument("--env", default="stage", choices=["stage", "prod"], help="resource-ceiling env (default: stage)")
    pf.set_defaults(func=cmd_preflight)

    run = sub.add_parser("run", help="run a solo spec's eval locally in Docker")
    run.add_argument("--spec", required=True, help="path to spec.yaml")
    run.add_argument("--input", required=True, help="path to the round input fixture JSON")
    run.add_argument("--submission", help="path to the miner artifact to evaluate (required for solo)")
    run.add_argument("--dockerfile", help="build the player image from this Dockerfile (build context = --context)")
    run.add_argument("--context", help="docker build context for --dockerfile (default: the Dockerfile's directory)")
    run.add_argument("--image", help="use this prebuilt local image tag instead of building")
    run.add_argument(
        "--private-data",
        action="append",
        default=[],
        metavar="MOUNT_PATH=HOST_PATH",
        help="local stand-in for one spec `private_data` entry: bind-mount HOST_PATH read-only at "
        "MOUNT_PATH in the referee. Repeatable; required once per private_data entry. The file's "
        "sha256 must match the spec (the platform verifies the same digest before every job).",
    )
    run.add_argument("--env", default="stage", choices=["stage", "prod"], help="resource-ceiling env (default: stage)")
    run.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
