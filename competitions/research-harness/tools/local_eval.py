"""Run a full research_harness episode locally: real player HTTP, real referee, real scoring.

`apex-dev run` validates the contract but does not yet spin up the two sandboxes
(it exits 3), so this is how a miner iterates and how the baseline is measured. It is
the same referee code the platform runs — only the transport is local threads instead of
containers, and the trace goes to a local file instead of /data.

    # offline, against the stub model (plumbing only — see tools/stub_model.py)
    python tools/local_eval.py --submission baseline/submission.py --seed 7 --num-questions 12

    # against a real frozen model
    python tools/local_eval.py --submission baseline/submission.py \
        --model-url http://localhost:8080 --model-name Qwen3-8B --num-questions 64
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex_sdk.gym_v1 import RefereeContext  # noqa: E402
from apex_sdk.gym_v1.client import PlayerClient  # noqa: E402

from player.launch import HarnessPlayer  # noqa: E402
from referee.referee import ResearchReferee  # noqa: E402
from tools import stub_model  # noqa: E402


def _serve_player(submission: str) -> tuple[str, threading.Thread, object]:
    from http.server import ThreadingHTTPServer

    from apex_sdk.gym_v1.player import _make_handler

    player = HarnessPlayer(submission)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(player, "/health"))
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return f"http://127.0.0.1:{server.server_address[1]}", t, server


def main() -> int:
    ap = argparse.ArgumentParser(description="Run one research_harness episode locally.")
    ap.add_argument("--submission", required=True, help="path to the harness submission .py")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--num-questions", type=int, default=16)
    ap.add_argument("--token-pool", type=int, default=192_000)
    ap.add_argument("--trap-rate", type=float, default=0.6)
    ap.add_argument("--max-steps", type=int, default=40)
    ap.add_argument("--max-context-tokens", type=int, default=3_000)
    ap.add_argument("--model-url", help="OpenAI-compatible endpoint; omit to use the offline stub")
    ap.add_argument("--model-name", default="stub")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--max-output-tokens", type=int, default=512)
    ap.add_argument("--trace", default="", help="write the per-question trace here")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = ap.parse_args()

    stub = None
    model_url = args.model_url
    if not model_url:
        stub = stub_model.serve(0)
        threading.Thread(target=stub.serve_forever, daemon=True).start()
        model_url = f"http://127.0.0.1:{stub.server_address[1]}"
        # stderr so --json output stays machine-readable.
        print(f"• offline stub model on {model_url} (plumbing check, not a real baseline)", file=sys.stderr)

    os.environ.update(
        MODEL_BASE_URL=model_url,
        MODEL_NAME=args.model_name,
        MODEL_TEMPERATURE=str(args.temperature),
        MODEL_MAX_OUTPUT_TOKENS=str(args.max_output_tokens),
        MODEL_TOKEN_BUDGET=str(args.token_pool),
    )

    player_url, _t, server = _serve_player(args.submission)
    client = PlayerClient(player_url)
    if not client.health():
        print("✗ submission failed readiness (it did not import, or has no valid `Harness`)", file=sys.stderr)
        return 2

    trace_path = Path(args.trace) if args.trace else None

    class LocalReferee(ResearchReferee):
        """Same scorer; the trace goes to a local file instead of /data/trace.jsonl."""

        def trace(self, event: dict) -> None:
            if trace_path:
                with trace_path.open("a") as f:
                    f.write(json.dumps(event) + "\n")

    ctx = RefereeContext(
        match_id=f"local-{args.seed}",
        seed=args.seed,
        config={
            "num_questions": args.num_questions,
            "token_pool": args.token_pool,
            "trap_rate": args.trap_rate,
            "max_steps_per_question": args.max_steps,
            "max_context_tokens": args.max_context_tokens,
        },
        player_urls=[player_url],
        num_players=1,
    )
    if trace_path and trace_path.exists():
        trace_path.unlink()

    result = LocalReferee().play_game(ctx, [client])
    server.shutdown()

    md = result.metadata
    if args.json:
        print(json.dumps({"raw_scores": result.raw_scores, "metadata": md}, indent=2))
        return 0

    print(f"\nraw_score          : {result.raw_scores[0]:.4f}  (n={md['num_questions']})")
    print(f"outcomes           : {md['outcomes']}")
    print(f"by hops            : { {k: v['mean_score'] for k, v in sorted(md['by_hops'].items())} }")
    print(f"by trap            : { {k: v['mean_score'] for k, v in sorted(md['by_trap'].items())} }")
    print(f"cited a trap doc   : {sum(v['cited_trap'] for v in md['by_trap'].values())} question(s)")
    print(f"model calls        : {md['model_calls']}  tokens={md['tokens_spent']} of {md['token_pool']}")
    print(f"token utilisation  : {md['token_utilisation']:.1%}")
    print(f"eval time          : {md['eval_time_in_seconds']}s")
    per_q = [q["score"] for q in md["questions"]]
    if len(per_q) > 1:
        print(
            f"per-question stdev : {statistics.stdev(per_q):.4f}  -> sem={statistics.stdev(per_q)/len(per_q)**0.5:.4f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
