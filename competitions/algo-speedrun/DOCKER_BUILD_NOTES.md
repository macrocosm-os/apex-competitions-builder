# Docker build validation notes

Both images were actually built and run in this environment (Docker Desktop, available
locally) -- not just reasoned about. This caught three real bugs the local Python-level
testing (tests/) could never have found, because they only exist at the container-image
level.

## `player/Dockerfile` -- builds clean, no issues found

```
docker build -f player/Dockerfile -t algo-speedrun-player .
```
Builds in under a second from `apex-player-base`. No dependencies beyond the stdlib
(`player/launch.py` never imports torch/nanochat), so there was nothing to find here.

## `referee/Dockerfile` -- three real bugs found and fixed by actually building it

1. **`curl: not found`.** `apex-referee-base` is `python:3.12-slim` (minimal Debian),
   which has neither `curl` nor a C toolchain. The nanochat-fetch step failed
   immediately. Fixed by adding `apt-get install curl ca-certificates g++` -- which
   itself needed `USER root` first, since the base image already drops to the non-root
   sandbox user (uid 1000) before this Dockerfile's own layers run.
2. **`InvalidCxxCompiler` at TRAINING time, not build time.** Even after fixing (1)'s
   curl issue, an actual training run inside the built image failed deep in
   `torch._inductor` with "No working C++ compiler found." nanochat's Muon optimizer
   (`nanochat/optim.py`) calls `torch.compile` on its fused AdamW step, which JIT-compiles
   a C++ kernel on first `optimizer.step()` -- this only surfaces when code actually
   *runs*, not when the image builds, and would never have been caught without running
   the built container, not just building it. Fixed by adding `g++` to the same
   `apt-get install` line as (1).
3. **This machine's Docker Desktop VM disk (58GB, found 92% full from unrelated data) is
   too small to complete a real `pip install torch` here** -- plain `pip install torch`
   on Linux pulls the full CUDA-enabled build (~2-4GB of `nvidia-*` wheels), which is
   *correct* for this competition (the referee genuinely needs GPU, per
   `referee.resources.gpu_count: 1`), not a mistake to route around. This is a genuine
   infra limit of the local verification environment, not of the Dockerfile: verified by
   substituting a CPU-only torch index (`--index-url .../whl/cpu`) in a throwaway
   diagnostic build, which completed successfully and let every OTHER step -- nanochat
   fetch+verify, data shard fetch+verify (sha256 checked), tokenizer training baked at
   build time, and (critically) an actual end-to-end training run and a full
   `referee.py` `play_game()` call including the path-traversal adversarial test -- run
   for real inside a genuine container. All of it passed. The real (CUDA) `pip install
   torch` line is what ships; only the diagnostic substitution was CPU-only, and only to
   work around this machine's disk allocation.

## What was verified inside the real (diagnostic) container, not just reasoned about

```
$ docker run --rm <image> python3 -c "... run_proxy_training(...) ..."
REAL in-container training run: {'val_bpb': 2.602179849762959, 'tokens_trained': 10240, 'wall_time_s': 16.43}

$ docker run --rm <image> python3 /app/incontainer_test.py
normal: scored [2.60218]
path-traversal: screen_violation [1000000000.0] -- /etc/pwned.py exists: False
```

A real training run against the baked-in tokenizer/data produced a val_bpb close to the
CPU measurement in `baseline/PROVENANCE.md` (2.602 vs. 2.587 for seed 0 -- small
difference expected from platform/torch-version floating-point variation between macOS
and the Linux container, not a correctness problem), and the path-traversal attack from
HANDOFF.md §8 item 1 was confirmed blocked inside the actual container filesystem, not
just in a local pytest run.

## What is still NOT verified

- The real (CUDA) `pip install torch` line has not completed a build in this
  environment -- only its logic (same Dockerfile, CPU-only torch substituted) has.
  Whoever builds this for real, on infra with adequate disk (a few GB more than this
  machine had free), should expect it to work based on the above, but should still watch
  the first real build rather than assume it.
- GPU execution itself (`gpu_count: 1`) was never exercised -- this machine has no GPU
  passthrough to Docker. Everything above ran on CPU inside the container.
- The build was not run through the platform's actual sync/cosign-verification pipeline
  -- only `docker build`/`docker run` locally.
