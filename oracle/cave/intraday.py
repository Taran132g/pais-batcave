"""Whole-portfolio equity sampled every 20 s on Oracle, served as candles for the Trading chart.

Samples (epoch seconds, equity) are kept for 7 days in memory and persisted every ~5 min, so
1m–4H candles come straight from samples. 1D candles also backfill older days from the daily
Yubit runs (+ Coinbase that day) so the chart reaches back before sampling began.

data/equity_backfill.json (rebuilt on the Mac from Yubit fills + ledgers at hourly prices) replaces
everything up to its "end": samples before then were marked against stale snapshots.
"""
import json
import threading
import time
from collections import deque
from datetime import datetime, timezone

from . import coinbase_view, config, live

SAMPLE_S = 20
RETAIN_S = 7 * 86400
PERSIST_EVERY = 15  # samples (~5 min)
FILE = config.ROOT / "data/intraday.json"
BACKFILL_FILE = config.ROOT / "data/equity_backfill.json"
TIMEFRAMES = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
DEFAULT_LIMIT = 1000  # 1H then reaches back past the 2026-09-01 backfill start

_samples: deque = deque(maxlen=RETAIN_S // SAMPLE_S)
_lock = threading.Lock()


# ---------- candles (pure) ----------

def _bucketed(samples, width: int) -> list[dict]:
    out: list[dict] = []
    for ts, value in samples:
        start = int(ts) - int(ts) % width
        if out and out[-1]["time"] == start:
            c = out[-1]
            c["high"], c["low"], c["close"] = max(c["high"], value), min(c["low"], value), value
        else:
            out.append({"time": start, "open": value, "high": value, "low": value, "close": value})
    return out


def _chained(candles: list[dict]) -> list[dict]:
    """Open each candle at the prior close (no gaps between bars, and a one-sample bucket still has a body)."""
    out, prev_close = [], None
    for c in candles:
        c = dict(c)
        if prev_close is not None:
            c["open"] = prev_close
            c["high"], c["low"] = max(c["high"], prev_close), min(c["low"], prev_close)
        out.append(c)
        prev_close = c["close"]
    return out


def build_candles(samples, tf: str, daily, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """samples/daily: [(epoch_s, equity)] oldest first. Every candle opens at the prior close."""
    if tf not in TIMEFRAMES:
        raise ValueError(f"unknown timeframe {tf!r}")
    if tf != "1d":
        return _chained(_bucketed(samples, TIMEFRAMES[tf]))[-limit:]
    by_day = {c["time"]: c for c in _bucketed(daily, 86400)}
    by_day.update({c["time"]: c for c in _bucketed(samples, 86400)})  # real samples beat a daily snapshot
    return _chained([by_day[d] for d in sorted(by_day)])[-limit:]


def _epoch(iso_or_day: str) -> int:
    text = iso_or_day if "T" in iso_or_day else f"{iso_or_day}T00:00:00+00:00"
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())


def daily_points(roi: dict, cb_history: dict, cb_month_start: float | None) -> list[tuple[int, float]]:
    """Whole-portfolio value per daily Yubit run (+ Coinbase that day), plus the month-start point."""
    def cb_on(day: str) -> float:
        """Coinbase as of a Yubit read that day. Each history entry is that day's LAST value, which
        can come hours after the read, so past days use the prior day's close; the newest day is live."""
        days = sorted(cb_history)
        if not days:
            return 0.0
        if day == days[-1]:
            return cb_history[day]
        before = [d for d in days if d < day]
        return cb_history[before[-1] if before else days[0]]

    points = []
    if roi.get("month") and roi.get("month_start") is not None:
        start = roi["month_start"] + (cb_month_start or 0)
        points.append((_epoch(f"{roi['month']}-01"), round(start, 2)))
    for p in roi.get("equity_series") or []:
        day = (p.get("date") or p["t"])[:10]
        points.append((_epoch(p["t"]), round(p["equity"] + (cb_on(day) if cb_month_start is not None else 0), 2)))
    return sorted(points)


# ---------- sampling ----------

_last_cb: dict = {"total": None}


def sample_once(snapshot_file=None) -> dict | None:
    """One reading of Yubit (live-marked) + Coinbase. None if the Yubit snapshot isn't usable yet."""
    roi = json.loads((snapshot_file or config.SNAPSHOT_FILE).read_text()).get("roi") or {}
    if roi.get("balance") is None:
        return None
    yubit = live.mark(roi)["equity_usd"]
    cb = None
    if config.COINBASE_KEY_FILE.exists():
        try:
            cb = coinbase_view.summary()["total"]
            _last_cb["total"] = cb
        except Exception:  # noqa: BLE001 - keep sampling Yubit even if Coinbase hiccups
            cb = _last_cb["total"]  # a failed read must not drop Coinbase to $0 for a sample
    now = int(time.time())
    equity = round(yubit + (cb or 0), 2)
    with _lock:
        _samples.append((now, equity))
    return {"t": datetime.fromtimestamp(now, timezone.utc).isoformat(), "yubit": round(yubit, 2),
            "coinbase": cb, "equity": equity}


def samples() -> list[tuple[int, float]]:
    with _lock:
        return list(_samples)


SNAP_LEAD_S = 120         # read_times are when each read's file landed; Oracle sees it a few minutes later
SNAP_WINDOW_S = 20 * 60
MIN_SNAP_USD = 40.0       # a bigger one-sample move in that window is the estimate snapping to the read


def smooth_read_snaps(samples, read_times) -> list[tuple[int, float]]:
    """Spread each read's snap back over the time since the previous read.

    Between reads the live estimate is marked against the last snapshot, which can't see trades placed
    since, so it drifts and then jumps when the next read lands. Shifting the earlier samples by a
    linearly growing share of that jump keeps the intraday shape but ends exactly on the read.
    """
    out = list(samples)
    if len(out) < 2:
        return out
    anchor = out[0][0]
    for read in sorted(read_times):
        window = [i for i in range(1, len(out)) if read - SNAP_LEAD_S <= out[i][0] <= read + SNAP_WINDOW_S]
        if not window:
            continue
        i = max(window, key=lambda k: abs(out[k][1] - out[k - 1][1]))
        jump = out[i][1] - out[i - 1][1]
        if abs(jump) >= MIN_SNAP_USD:
            span = out[i - 1][0] - anchor
            for k in range(i):
                t, v = out[k]
                if t > anchor:
                    out[k] = (t, round(v + jump * ((t - anchor) / span if span > 0 else 1.0), 2))
        anchor = out[i][0]
    return out


def merge_backfill(live_samples, daily, backfill: dict | None, read_times=()):
    """Backfill points win up to backfill["end"]; after it, live samples with read snaps smoothed out.
    Real reads fill any stretch after the backfill that has no samples (they're kept 7 days)."""
    smoothed = smooth_read_snaps(live_samples, read_times)
    if not backfill or not backfill.get("points"):
        return smoothed, daily
    end = backfill["end"]
    points = [(int(t), float(v)) for t, v in backfill["points"]]
    first_sample = smoothed[0][0] if smoothed else float("inf")
    reads = [p for p in daily if end < p[0] < first_sample]
    return (sorted(points + reads + [p for p in smoothed if p[0] > end]),
            [p for p in daily if p[0] < points[0][0]])


_backfill_cache: dict = {"mtime": None, "data": None}


def _backfill() -> dict | None:
    """Parsed once per file change: the page polls candles every 20 s and the file holds ~15k points."""
    try:
        mtime = BACKFILL_FILE.stat().st_mtime
        if _backfill_cache["mtime"] != mtime:
            _backfill_cache.update(mtime=mtime, data=json.loads(BACKFILL_FILE.read_text()))
        return _backfill_cache["data"]
    except (OSError, json.JSONDecodeError):
        return None


def candles(tf: str, limit: int = DEFAULT_LIMIT) -> list[dict]:
    snap = json.loads(config.SNAPSHOT_FILE.read_text())
    roi = snap.get("roi") or {}
    try:
        cb_history = json.loads(coinbase_view.HISTORY_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        cb_history = {}
    cb_start = coinbase_view.month_start(cb_history, roi.get("month") or "", coinbase_view._overrides())
    read_times = [_epoch(p.get("arrived") or p["t"]) for p in roi.get("equity_series") or []]
    series, daily = merge_backfill(samples(), daily_points(roi, cb_history, cb_start), _backfill(), read_times)
    return build_candles(series, tf, daily, limit)


def _load() -> None:
    try:
        saved = json.loads(FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return
    cutoff = time.time() - RETAIN_S
    rows = []
    for p in saved:
        if isinstance(p, dict):  # older format: {"t": iso, "equity": n}
            p = (int(datetime.fromisoformat(p["t"]).timestamp()), p["equity"])
        if p[0] > cutoff:
            rows.append((int(p[0]), float(p[1])))
    with _lock:
        _samples.extend(rows)


def _persist() -> None:
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(samples(), separators=(",", ":")))
    tmp.replace(FILE)


def _loop() -> None:
    n = 0
    while True:
        started = time.time()
        try:
            sample_once()
            n += 1
            if n % PERSIST_EVERY == 0:
                _persist()
        except Exception as exc:  # noqa: BLE001 - never let the sampler thread die
            print(f"[intraday] sample failed: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(max(1.0, SAMPLE_S - (time.time() - started)))


def start() -> None:
    _load()
    threading.Thread(target=_loop, name="intraday-sampler", daemon=True).start()
