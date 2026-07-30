"""Offline test double for the frozen base model. NOT part of any shipped image.

The competition needs a real OpenAI-compatible endpoint (vLLM / llama.cpp --server /
Ollama). This stub exists so the plumbing — the tool surface, the meter, the scorer, the
reference harness — can be developed and tested with no GPU and no network.

What it does: reads the `<documents>` block the referee assembled, works out which
relation the instruction is asking about from keywords, and reports every value it finds,
one line per document:

    lab:0079 -> Neandrern
    lab:0080 -> Klosgou

That is roughly what a competent model returns when asked to extract a field per
document, so a harness that arbitrates provenance correctly is genuinely exercised.

What it does NOT do, and why the numbers it produces are plumbing checks rather than a
baseline:
  * it does not follow instructions, so the `injection` trap degrades to a plain
    contradictor against it — injection resistance can only be measured against a real
    model;
  * it does not paraphrase, reason, or fail, so absolute scores against it are an upper
    bound on what any real model would give.

Run: python tools/stub_model.py --port 877
"""

from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# instruction keyword -> pattern capturing the value inside a document body
RELATIONS: list[tuple[tuple[str, ...], re.Pattern[str]]] = [
    (("affiliat", "institute of", "works at"), re.compile(r"affiliated with the (\w+) Institute")),
    (("locat", "city"), re.compile(r"located in the city of (\w+)")),
    (("fund", "grant"), re.compile(r"funded by the (\w+) Grant")),
    (("hous", "instrument is at"), re.compile(r"housed at the (\w+) Institute")),
    (("author", "wrote", "who "), re.compile(r"authored by Dr\. (\w+)")),
    (("instrument used", "used in", "collected using"), re.compile(r"using the (\w+)")),
    (("amount", "credits", "award"), re.compile(r"award amount is (\d+) credits")),
    (("publish", "year"), re.compile(r"published in (\d{4})")),
    (
        ("authoritative record", "registry index", "withdrawn", "current record"),
        re.compile(r"current authoritative record is ([a-z]+:\d+)"),
    ),
]

_DOC_RE = re.compile(r"\[([a-z]+:\d+)\]\s*(.*?)(?=\n\[[a-z]+:\d+\]|\Z)", re.S)


def _documents(user: str) -> list[tuple[str, str]]:
    m = re.search(r"<documents>\n(.*)\n</documents>", user, re.S)
    return _DOC_RE.findall(m.group(1)) if m else []


def _answer(user: str) -> str:
    instruction = user.split("</documents>")[-1].lower()
    docs = _documents(user)
    if not docs:
        return "No documents were supplied."

    # Most specific match wins: check every relation and keep the ones whose keyword
    # appears, then prefer the one with the most hits across the documents.
    best: tuple[int, list[str]] = (0, [])
    for keywords, pattern in RELATIONS:
        if not any(kw in instruction for kw in keywords):
            continue
        lines = [f"{doc_id} -> {m.group(1)}" for doc_id, body in docs if (m := pattern.search(body))]
        if len(lines) > best[0]:
            best = (len(lines), lines)
    if best[1]:
        return "\n".join(best[1])
    return "The documents do not state that."


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
        pass  # quiet

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_error(400, "invalid json")
            return
        if not self.path.endswith("/chat/completions"):
            self.send_error(404, "not found")
            return

        messages = body.get("messages") or []
        system = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
        user = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
        text = _answer(user)
        # Trim to the requested output cap the same way a server would.
        cap = int(body.get("max_tokens") or 512)
        text = text[: cap * 4]

        payload = {
            "id": "stub",
            "object": "chat.completion",
            "model": body.get("model") or "stub",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": max(1, (len(system) + len(user)) // 4),
                "completion_tokens": max(1, len(text) // 4),
                "total_tokens": max(1, (len(system) + len(user) + len(text)) // 4),
            },
        }
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(port: int) -> ThreadingHTTPServer:
    """Start the stub on `port` (0 picks a free one). Caller owns shutdown."""
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    return server


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Offline OpenAI-compatible stub for research_harness dev.")
    ap.add_argument("--port", type=int, default=877)
    args = ap.parse_args()
    s = serve(args.port)
    print(f"stub model on http://127.0.0.1:{s.server_address[1]}")
    s.serve_forever()
