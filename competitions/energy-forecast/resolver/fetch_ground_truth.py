"""Daily data-refresh pipeline. Runs OUTSIDE any Apex sandbox (GitHub Actions
cron, see ../.github/workflows/refresh-ground-truth.yml) -- this is the one
place in the whole competition allowed to reach the internet, because it is
not miner-reachable and produces no code that runs inside a sandbox.

Two jobs, run together once a day:

1. Pull newly-published EIA-930 hourly demand for each tracked BA and append
   it to data/<ba>_history.csv (the confirmed-history file baked into the
   next referee image build -- this is what next round's "live" input windows
   are built from).
2. Publish the day's now-realized actuals as a signed, content-hashed ground
   truth feed file (data/ground_truth/<date>.json) -- this is what the
   proposed `entrypoints.resolve` (resolve.py) consumes to score the
   predictions that were locked in before this data existed.

Requires EIA_API_KEY (free: https://www.eia.gov/opendata/register.php).
EIA-930 demand is available on a near real-time basis (~1hr lag); other
fields including finalized "type: D" actuals used here typically land within
1-2 days -- resolution_delay_days=2 in spec.yaml gives margin.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from env.data import BALANCING_AUTHORITIES, DATA_DIR

EIA_API_BASE = "https://api.eia.gov/v2/electricity/rto/region-data/data/"
GROUND_TRUTH_DIR = DATA_DIR / "ground_truth"


def _fetch_ba_hours(ba: str, start: datetime, end: datetime, api_key: str) -> list[tuple[str, float]]:
    """Fetch hourly `type=D` (demand) actuals for one BA in [start, end)."""
    params = (
        f"?api_key={api_key}&frequency=hourly&data[0]=value"
        f"&facets[respondent][]={ba}&facets[type][]=D"
        f"&start={start.strftime('%Y-%m-%dT%H')}&end={end.strftime('%Y-%m-%dT%H')}"
        "&sort[0][column]=period&sort[0][direction]=asc&length=5000"
    )
    with urlopen(Request(EIA_API_BASE + params)) as resp:  # noqa: S310 -- fixed, pinned host
        payload = json.loads(resp.read())
    rows = payload["response"]["data"]
    return [(f"{r['period']}:00Z", float(r["value"])) for r in rows if r["value"] is not None]


def refresh_history(api_key: str, now: datetime) -> None:
    """Append newly-confirmed hours to each BA's pinned history CSV."""
    for ba in BALANCING_AUTHORITIES:
        path = DATA_DIR / f"{ba}_history.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        existing_last = None
        if path.exists():
            with path.open() as f:
                rows = list(csv.DictReader(f))
            existing_last = rows[-1]["timestamp"] if rows else None

        start = (
            datetime.fromisoformat(existing_last.replace("Z", "+00:00")) + timedelta(hours=1)
            if existing_last
            else now - timedelta(days=400)
        )
        new_rows = _fetch_ba_hours(ba, start, now, api_key)
        if not new_rows:
            continue

        write_header = not path.exists()
        with path.open("a", newline="") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(["timestamp", "demand_mwh"])
            writer.writerows(new_rows)


def publish_ground_truth_feed(api_key: str, target_date: datetime) -> Path:
    """Publish one day's now-realized actuals as the resolve-time ground truth feed."""
    GROUND_TRUTH_DIR.mkdir(parents=True, exist_ok=True)
    start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    feed = {ba: _fetch_ba_hours(ba, start, end, api_key) for ba in BALANCING_AUTHORITIES}
    out_path = GROUND_TRUTH_DIR / f"{start.date().isoformat()}.json"
    out_path.write_text(json.dumps(feed, sort_keys=True))
    return out_path


if __name__ == "__main__":
    api_key = os.environ["EIA_API_KEY"]
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    refresh_history(api_key, now)
    # Publish the feed for 2 days ago: EIA-930 actuals need ~1-2 days to
    # finalize, matching spec.yaml's defaults.resolution_delay_days.
    publish_ground_truth_feed(api_key, now - timedelta(days=2))
