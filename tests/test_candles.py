import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "oracle"))

from cave import intraday  # noqa: E402

T0 = 1_790_000_000 - (1_790_000_000 % 86400)  # a UTC midnight


def test_buckets_samples_into_ohlc():
    samples = [(T0 + 0, 100.0), (T0 + 20, 105.0), (T0 + 40, 98.0), (T0 + 60, 101.0), (T0 + 80, 103.0)]
    candles = intraday.build_candles(samples, "1m", daily=[])
    assert candles[0] == {"time": T0, "open": 100.0, "high": 105.0, "low": 98.0, "close": 98.0}
    assert candles[1] == {"time": T0 + 60, "open": 101.0, "high": 103.0, "low": 101.0, "close": 103.0}


def test_daily_candles_backfill_days_without_samples():
    samples = [(T0 + 3600, 2500.0), (T0 + 7200, 2510.0)]
    daily = [(T0 - 2 * 86400, 1983.73), (T0 - 86400, 2400.0), (T0, 999.0)]  # today's daily point is superseded
    candles = intraday.build_candles(samples, "1d", daily=daily)
    assert [c["time"] for c in candles] == [T0 - 2 * 86400, T0 - 86400, T0]
    assert candles[0]["open"] == candles[0]["close"] == 1983.73
    assert candles[1]["open"] == 1983.73 and candles[1]["close"] == 2400.0  # opens at the prior close
    assert candles[2]["open"] == 2400.0 and candles[2]["close"] == 2510.0 and candles[2]["high"] == 2510.0


def test_limit_and_unknown_timeframe():
    samples = [(T0 + 20 * i, float(i)) for i in range(2000)]
    assert len(intraday.build_candles(samples, "1m", daily=[], limit=50)) == 50
    try:
        intraday.build_candles(samples, "7m", daily=[])
    except ValueError:
        pass
    else:
        raise AssertionError("unknown timeframe should raise")
