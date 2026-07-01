"""`apex-dev` — run and preflight a competition spec locally, exactly like the platform would.

Commands:
    apex-dev preflight --spec ./spec.yaml [--input fixtures/input.json] [--env stage]
        Validate the spec against apex.competition.v1, enforce resource ceilings, and
        (if --input is given) validate the fixture against the spec's input_schema.
        No Docker required. This is the gate designers run before opening a registry PR.

    apex-dev run --spec ./spec.yaml --input fixtures/input.json [--env stage]
        Execute the spec's eval locally in Docker (build image, launch player[/referee]
        sandboxes, inject the platform env, wait for result.json), mirroring the platform
        runners. [Docker executor lands in the next SDK milestone; this pass prints the
        resolved execution plan so the contract is reviewable.]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from apex_sdk.spec import LoadedSpec, SpecError, load_spec


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
    print("✓ preflight passed")


def cmd_run(args: argparse.Namespace) -> None:
    spec = _load(args.spec, args.env)
    _validate_input(spec, args.input)
    _print_plan(spec, args.env)
    print(
        "\n⚠ Docker execution is not wired up in this SDK milestone.\n"
        "  This pass ships the spec/protocol contracts and the execution plan above.\n"
        "  The full runner (build image, launch sandboxes, collect result.json) lands next.",
        file=sys.stderr,
    )
    raise SystemExit(3)


def _print_plan(spec: LoadedSpec, env: str) -> None:
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
    print(f"  evaluate cmd   : {ep['command']}")
    print(f"  evaluate to    : {ep['timeout_s']}s")
    if spec.is_duel:
        d = s["duel"]
        print(
            f"  duel protocol  : {d['protocol']} ({d['players_per_match']} players, "
            f"{d['num_games_default']} games, swap_sides={d['swap_sides']})"
        )
        print(f"  referee image  : {d['referee_image']['ref']}@{d['referee_image']['digest']}")
        print(f"  referee to     : {d['referee_timeout_s']}s")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="apex-dev", description="Local dev harness for Apex competitions.")
    sub = parser.add_subparsers(dest="command", required=True)

    pf = sub.add_parser("preflight", help="validate a spec (+ optional input fixture); no Docker")
    pf.add_argument("--spec", required=True, help="path to spec.yaml")
    pf.add_argument("--input", help="path to an input fixture JSON to validate against input_schema")
    pf.add_argument("--env", default="stage", choices=["stage", "prod"], help="resource-ceiling env (default: stage)")
    pf.set_defaults(func=cmd_preflight)

    run = sub.add_parser("run", help="run a spec's eval locally in Docker")
    run.add_argument("--spec", required=True, help="path to spec.yaml")
    run.add_argument("--input", required=True, help="path to the round input fixture JSON")
    run.add_argument("--env", default="stage", choices=["stage", "prod"], help="resource-ceiling env (default: stage)")
    run.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
