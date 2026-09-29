import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "oracle"))

from cave import coinbase_view, config, intraday, live  # noqa: E402


def test_sample_combines_live_yubit_and_coinbase(tmp_path, monkeypatch):
    snap = tmp_path / "snapshot.json"
    snap.write_text(json.dumps({"roi": {"balance": 1000.0, "positions": []}}))
    key = tmp_path / "key.json"
    key.write_text("{}")
    monkeypatch.setattr(config, "COINBASE_KEY_FILE", key)
    monkeypatch.setattr(live, "mark", lambda roi: {"equity_usd": 1200.0})
    monkeypatch.setattr(coinbase_view, "summary", lambda: {"total": 1300.0})
    intraday._samples.clear()
    point = intraday.sample_once(snap)
    assert point["equity"] == 2500.0 and point["yubit"] == 1200.0 and point["coinbase"] == 1300.0
    assert [v for _, v in intraday.samples()] == [2500.0]


def test_sample_skips_until_yubit_snapshot_has_balance(tmp_path):
    snap = tmp_path / "snapshot.json"
    snap.write_text(json.dumps({"roi": {}}))
    assert intraday.sample_once(snap) is None


def test_daily_points_combine_yubit_runs_with_coinbase_that_day():
    roi = {"month": "2026-09", "month_start": 883.73,
           "equity_series": [{"date": "2026-09-28", "t": "2026-09-28T12:03:31Z", "equity": 1256.14}]}
    pts = intraday.daily_points(roi, {"2026-09-29": 1307.46}, 1100.0)
    assert pts[0][1] == 1983.73                    # Sep 1: combined month start
    assert pts[1][1] == round(1256.14 + 1307.46, 2)  # earliest Coinbase value stands in before history began
