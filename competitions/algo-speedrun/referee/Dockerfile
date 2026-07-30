# algo_speedrun REFEREE image (the scorer sandbox).
#
# Owns the vendored nanochat checkout, applies the miner's screened EXTRA_FILES overrides
# into a per-job scratch copy, and runs the proxy training pass. nanochat is fetched here
# at BUILD time (network access is normal for image builds -- only the running sandbox
# has no egress) as a pinned commit archive, verified against its sha256 before
# extraction, and trimmed to the training-loop critical path. See ../baseline/PROVENANCE.md
# for the exact commit/hash and what was dropped.
#
# BUILD CONTEXT = the competition directory (competitions/algo-speedrun):
#     docker build -f referee/Dockerfile -t algo-speedrun-referee .
FROM apex-referee-base

# apex-referee-base (python:3.12-slim) has neither curl nor a C++ compiler, and already
# dropped to the non-root sandbox user (uid 1000) -- apt-get needs root. Both found by
# actually building AND RUNNING this image, not assumed: curl was missing at the nanochat
# fetch step ("curl: not found"), and g++ is needed at TRAINING time, not just build
# time -- nanochat's Muon optimizer (nanochat/optim.py) calls torch.compile on its fused
# AdamW step, which JIT-compiles a C++ kernel on first optimizer.step(); without g++ this
# fails deep inside torch._inductor on every single training run, not at image build.
USER root
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates g++ && rm -rf /var/lib/apt/lists/*
USER 1000

# Matches upstream's own pyproject.toml dependency list (minus wandb, which only
# base_train.py's dropped logging path needs -- see train_runner.py's module docstring).
# Verified by actually importing gpt/dataloader/tokenizer/loss_eval/common against the
# pinned commit below: torch+pyarrow alone is NOT sufficient (dataset.py needs requests,
# common.py needs numpy+filelock, tokenizer.py needs rustbpe+tiktoken).
RUN pip install --no-cache-dir torch pyarrow numpy requests filelock kernels psutil rustbpe tiktoken

ARG NANOCHAT_COMMIT=92d63d4e8bb4df75c3b71618f31ddde2378b2bcd
ARG NANOCHAT_SHA256=aa9955ca5ba3f64792494706f8888bb9d1e43a57bdda371435e58e02a85eb8c2

RUN set -eux; \
    curl -sL "https://github.com/karpathy/nanochat/archive/${NANOCHAT_COMMIT}.tar.gz" -o /tmp/nanochat.tar.gz; \
    echo "${NANOCHAT_SHA256}  /tmp/nanochat.tar.gz" | sha256sum -c -; \
    mkdir -p /tmp/nanochat-src /app; \
    tar -xzf /tmp/nanochat.tar.gz -C /tmp/nanochat-src --strip-components=1; \
    cp -r /tmp/nanochat-src/nanochat /app/nanochat; \
    cp -r /tmp/nanochat-src/scripts /app/scripts; \
    touch /app/scripts/__init__.py; \
    rm -rf /tmp/nanochat.tar.gz

ENV PYTHONPATH=/app
ENV NANOCHAT_BASE_DIR=/app/nanochat_data

# The referee sandbox has NO egress at eval time (spec.yaml: referee.allow_internet:
# false) -- get_tokenizer() and the dataloader must find a real, already-trained
# tokenizer and real pretraining data shards on disk, not fetch either on demand. Both
# are pulled and pinned here, at BUILD time, same reasoning as the nanochat source
# itself (HANDOFF.md §5): a Docker build already has network access, and content-hash
# pinning gives the same reproducibility guarantee a live fetch never could.
#
# 1 train shard + the (always-included) val shard, per upstream's own
# `python -m nanochat.dataset -n 1` convention -- proxy-scale training needs far less
# data than a real speedrun, and this keeps the image ~180MB heavier, not 400B-tokens
# heavier. Pinned by content sha256 (verified per-file, not just of the archive).
ARG SHARD_TRAIN_SHA256=054ddbd98abf30d773c54de578fc9d579bafeb6c14e04e97bd36aa90e825bf9b
ARG SHARD_VAL_SHA256=769fe59d108dfd2cfa186c63173b83fbfb90a7adb3519519ba6eaa6ca9889f94

RUN set -eux; \
    mkdir -p ${NANOCHAT_BASE_DIR}/base_data_climbmix; \
    curl -sL "https://huggingface.co/datasets/karpathy/climbmix-400b-shuffle/resolve/main/shard_00000.parquet" \
        -o ${NANOCHAT_BASE_DIR}/base_data_climbmix/shard_00000.parquet; \
    echo "${SHARD_TRAIN_SHA256}  ${NANOCHAT_BASE_DIR}/base_data_climbmix/shard_00000.parquet" | sha256sum -c -; \
    curl -sL "https://huggingface.co/datasets/karpathy/climbmix-400b-shuffle/resolve/main/shard_06542.parquet" \
        -o ${NANOCHAT_BASE_DIR}/base_data_climbmix/shard_06542.parquet; \
    echo "${SHARD_VAL_SHA256}  ${NANOCHAT_BASE_DIR}/base_data_climbmix/shard_06542.parquet" | sha256sum -c -

# Train the tokenizer ONCE, here, deterministically from the pinned shard above --
# never at eval time. --max-chars is small on purpose: this is a proxy-scale
# competition (input.schema.json caps depth<=8), not a full nanochat run, and a smaller
# BPE training set keeps the image build fast without changing what's being measured
# (the training LOOP, not the tokenizer). See baseline/PROVENANCE.md for the exact
# command and measured baseline_raw_score this produced.
RUN python -m scripts.tok_train --max-chars 5000000

WORKDIR /app

COPY referee/screen.py /app/screen.py
COPY referee/schedule_defaults.py /app/schedule_defaults.py
COPY referee/train_runner.py /app/train_runner.py
COPY referee/referee.py /app/referee.py
