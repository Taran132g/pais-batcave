"""Whole-portfolio equity sampled every 20 s on Oracle, served as candles for the Trading chart.

Samples (epoch seconds, equity) are kept for 7 days in memory and persisted every ~5 min, so
1m–4H candles come straight from samples. 1D candles also backfill older days from the daily
Yubit runs (+ Coinbase that day) so the chart reaches back before sampling began.
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
TIMEFRAMES = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
DEFAULT_LIMIT = 500

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


def build_candles(samples, tf: str, daily, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """samples/daily: [(epoch_s, equity)] oldest first. Daily candles chain open to the prior close."""
    if tf not in TIMEFRAMES:
        raise ValueError(f"unknown timeframe {tf!r}")
    if tf != "1d":
        return _bucketed(samples, TIMEFRAMES[tf])[-limit:]
    by_day = {c["time"]: c for c in _bucketed(daily, 86400)}
    by_day.update({c["time"]: c for c in _bucketed(samples, 86400)})  # real samples beat a daily snapshot
    candles, prev_close = [], None
    for day in sorted(by_day):
        c = dict(by_day[day])
        if prev_close is not None:
            c["open"] = prev_close
            c["high"], c["low"] = max(c["high"], prev_close), min(c["low"], prev_close)
        candles.append(c)
        prev_close = c["close"]
    return candles[-limit:]


def _epoch(iso_or_day: str) -> int:
    text = iso_or_day if "T" in iso_or_day else f"{iso_or_day}T00:00:00+00:00"
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())


def daily_points(roi: dict, cb_history: dict, cb_month_start: float | None) -> list[tuple[int, float]]:
    """Whole-portfolio value per daily Yubit run (+ Coinbase that day), plus the month-start point."""
    def cb_on(day: str) -> float:
        days = sorted(cb_history)
        if not days:
            return 0.0
        before = [d for d in days if d <= day]
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
        except Exception:  # noqa: BLE001 - keep sampling Yubit even if Coinbase hiccups
            cb = None
    now = int(time.time())
    equity = round(yubit + (cb or 0), 2)
    with _lock:
        _samples.append((now, equity))
    return {"t": datetime.fromtimestamp(now, timezone.utc).isoformat(), "yubit": round(yubit, 2),
            "coinbase": cb, "equity": equity}


def samples() -> list[tuple[int, float]]:
    with _lock:
        return list(_samples)


def candles(tf: str, limit: int = DEFAULT_LIMIT) -> list[dict]:
    snap = json.loads(config.SNAPSHOT_FILE.read_text())
    roi = snap.get("roi") or {}
    try:
        cb_history = json.loads(coinbase_view.HISTORY_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        cb_history = {}
    cb_start = coinbase_view.month_start(cb_history, roi.get("month") or "", coinbase_view._overrides())
    return build_candles(samples(), tf, daily_points(roi, cb_history, cb_start), limit)


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
