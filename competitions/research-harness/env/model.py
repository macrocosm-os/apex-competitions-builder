"""Frozen base-model client — referee-side, and the ONLY path to the model.

The base model is a *tool inside the environment*, not a sidecar attached to the
harness. Every completion is requested by the referee on the harness's behalf. That
inversion is what makes the competition well-posed:

  * metering is tamper-proof — the referee counts every token because it spends them;
  * sampling is pinned by the spec, so all submissions face an identical model and a
    round is reproducible from its seed;
  * the call log is evidence — a submission that scores well without spending tokens
    is visible in `metadata`, not a thing to be inferred;
  * the player sandbox needs no weights, so it stays inside the CPU/memory ceilings.

Transport is stdlib urllib against any OpenAI-compatible `/v1/chat/completions`
(vLLM, llama.cpp --server, Ollama, or tools/stub_model.py for offline dev), so the
referee image needs no vendor SDK.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass


class ModelUnavailable(RuntimeError):
    """The base model endpoint could not be reached or returned a malformed response.

    This is a PLATFORM/REFEREE failure, never a submission failure: a harness must not
    be scored 0 because the shared model was down. The referee lets it propagate so no
    result.json is written and the platform attributes the failure to the referee.
    """


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, prompt: int, completion: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.calls += 1


class BaseModel:
    """Calls the platform-served frozen model with spec-pinned sampling.

    `temperature` and `max_output_tokens` come from the spec's `base_model` block, not
    from the harness: a submission that could raise temperature or output length would
    be buying score with tokens nobody else was allowed to spend.
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_output_tokens: int = 512,
        timeout_s: float = 120.0,
    ):
        # Injected by the platform into the referee sandbox (see spec `base_model`).
        self.base_url = (base_url or os.environ.get("MODEL_BASE_URL", "")).rstrip("/")
        self.model = model or os.environ.get("MODEL_NAME", "")
        if not self.base_url:
            raise ModelUnavailable(
                "MODEL_BASE_URL is not set. The spec declares a `base_model`, so the platform "
                "must inject the endpoint into the referee sandbox."
            )
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.timeout_s = timeout_s
        self.usage = Usage()

    def complete(self, system: str, user: str, max_output_tokens: int | None = None) -> tuple[str, int, int]:
        """Return (text, prompt_tokens, completion_tokens) and record usage.

        The harness may request FEWER output tokens than the ceiling (a real lever: short
        extractions are cheap) but never more.
        """
        cap = min(int(max_output_tokens or self.max_output_tokens), self.max_output_tokens)
        body = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": self.temperature,
                "max_tokens": max(1, cap),
                "seed": 0,  # best-effort determinism where the server honours it
                "stream": False,
            }
        ).encode()
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                payload = json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            raise ModelUnavailable(f"base model call failed: {type(e).__name__}: {e}") from e

        try:
            text = payload["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise ModelUnavailable(f"base model returned an unexpected payload: {payload!r}") from e

        # Prefer the server's own accounting; fall back to a character estimate so a
        # server that omits `usage` still costs the harness something (a free call would
        # make the whole budget meaningless).
        usage = payload.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or max(1, len(system) + len(user)) // 4)
        completion_tokens = int(usage.get("completion_tokens") or max(1, len(text)) // 4)
        self.usage.add(prompt_tokens, completion_tokens)
        return text, prompt_tokens, completion_tokens
