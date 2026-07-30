# Energy Demand Forecast

Forecast the next 24 hours of electricity demand for a US grid Balancing
Authority (BA) from the last 7 days of confirmed demand. You submit a single
**ONNX forecasting model**; the leaderboard rewards genuinely predicting
demand that had not happened yet at the time you were scored — this
competition is deliberately live, not a static historical benchmark (see
"Why live, not historical" below).

## The task

- **Input**: the last 168 hourly demand values (MWh) for one BA, each hour
  paired with calendar features (hour-of-day, day-of-week as sin/cos, US
  holiday flag) — see `env/features.py::build_observation`. Demand is
  normalized by the window's own mean before being fed to your model.
- **Output**: the next 24 hourly demand values, in the same normalized units
  (the referee un-normalizes before scoring).
- **Tracked BAs**: `env/data.py::BALANCING_AUTHORITIES` — ~20 US BAs spanning
  different climates, sizes, and time zones.

## Scoring

Per instance: `skill = 1 - MAE(your forecast) / MAE(seasonal-naive)`, where
seasonal-naive just repeats the input window's last 24 hours (yesterday's
same hours). `skill = 0` means you're exactly as good as that trivial
baseline; positive is genuine forecasting skill. Degenerate flat outputs and
non-finite outputs score 0. **raw_score = mean skill across all instances in
the round.** A new submission takes the lead by beating the top raw score by
≥ 1%.

The released baseline (`baseline/baseline.onnx`, ridge regression over the
same observation) scores **~0.31** in backtest mode (see below) — beating it
is table stakes.

## Why live, not historical

Every other Apex competition scores against a fixed generator or simulator
the platform controls. That doesn't work for public grid data: if the
held-out set were drawn from already-published EIA-930 history, a submission
could just memorize the public series (the input window is a unique key into
a sequence anyone can download) instead of building a real forecaster —
"can't look up the future" only holds if the target genuinely hadn't
happened yet when you were scored.

So production rounds run in **`mode: live`**: your model sees history up to
a lock time, and the round only becomes fully scored after the real outcome
is later published (`defaults.resolution_delay_days`, currently 2, matching
EIA-930's actuals-finalization lag) — see `PLATFORM_PROPOSAL.md` for the
two-phase (`lock` → `resolve`) mechanism this needs, which is a proposed
extension to the Apex SDK, not something live today. Until it ships, this
repo also supports **`mode: backtest`**, which scores immediately against
already-known held-out history — useful for local development, baseline
training, and evaluation sizing, but NOT how production scoring works.

## Submission contract (ONNX only — no code)

- Exactly one input: `float32 [1, 1008]` (168 hours × 6 features, flattened
  row-major) — one output: `float32 [1, 24]`.
- ≤ 25 MB, single file with weights embedded (see `embed_external_data` in
  `humanoid-parkour/baseline/train_baseline.py` for the same fix if your
  exporter splits out a `.data` sidecar — this competition's baseline doesn't
  need it since it's a plain linear ONNX graph).
- Loaded with onnxruntime (CPU, single-threaded) by the public player image.

Observation layout (`env/features.py` is the source of truth): per hour,
`[normalized_demand, sin(hour), cos(hour), sin(day_of_week), cos(day_of_week),
is_holiday]`, 168 hours flattened in chronological order.

## Train and test locally

```bash
pip install numpy onnx onnxruntime -e ../../  # installs the apex_sdk package

# Placeholder data for local dev only — production uses real EIA-930 data,
# refreshed daily by resolver/fetch_ground_truth.py (needs EIA_API_KEY):
python tools/generate_synthetic_history.py --days 400

# Reference ridge-regression recipe (any algorithm works; only the ONNX
# artifact matters):
python baseline/train_baseline.py --seed 0 --num-train-instances 4000 --out my_model.onnx

# Score it through the real player+referee loop, backtest mode:
python tools/local_eval.py --onnx my_model.onnx --seed 0 --mode backtest

# Rehearse the full lock -> resolve lifecycle (see PLATFORM_PROPOSAL.md):
python tools/simulate_two_phase.py --onnx my_model.onnx --seed 0
```

## What you see after each round

Per-instance breakdowns (BA, skill, MAE vs. naive) are revealed once a round
resolves, along with the round's seed. Submissions become downloadable by
other miners after the 5-day reveal window — a real improvement is protected
for 5 days, then becomes the field's new floor.
