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


def test_past_reads_pair_with_coinbase_from_before_the_read():
    # History keeps each day's LAST value. On 2026-10-20 Coinbase dipped to $64 at 18:57 UTC, after
    # that day's 14:28 Yubit read, and the chart showed a fake $1,000 drop at the read.
    roi = {"equity_series": [{"date": "2026-10-20", "t": "2026-10-20T14:28:05Z", "equity": 1589.14},
                             {"date": "2026-10-22", "t": "2026-10-22T15:16:13Z", "equity": 1589.67}]}
    history = {"2026-10-19": 1022.65, "2026-10-20": 64.31, "2026-10-21": 1277.13, "2026-10-22": 1202.59}
    pts = intraday.daily_points(roi, history, 900.0)
    assert pts[0][1] == round(1589.14 + 1022.65, 2)  # previous day's close, not the later dip
    assert pts[1][1] == round(1589.67 + 1202.59, 2)  # newest day is still live: use it


def test_merge_backfill_replaces_samples_up_to_its_end():
    live = [(100, 1.0), (200, 2.0), (300, 3.0)]
    daily = [(10, 0.5), (250, 9.0)]
    series, kept_daily = intraday.merge_backfill(live, daily, {"end": 200, "points": [[50, 5.0], [200, 6.0]]})
    assert series == [(50, 5.0), (200, 6.0), (300, 3.0)]
    assert kept_daily == [(10, 0.5)]


def test_merge_backfill_without_file_is_a_no_op():
    assert intraday.merge_backfill([(1, 1.0)], [(2, 2.0)], None) == ([(1, 1.0)], [(2, 2.0)])


def test_reads_fill_the_stretch_before_sampling_began():
    # Samples are kept 7 days; between the backfill's end and the first sample only real reads exist.
    series, _ = intraday.merge_backfill([(400, 4.0)], [(250, 9.0), (450, 9.9)],
                                        {"end": 200, "points": [[200, 6.0]]}, read_times=[250, 450])
    assert series == [(200, 6.0), (250, 9.0), (400, 4.0)]


def test_snap_at_a_read_is_spread_back_over_the_time_since_the_previous_read():
    # Estimates drift (they can't see new trades) and jump when the new read lands on Oracle.
    samples = [(0, 100.0), (100, 110.0), (200, 120.0), (300, 160.0), (400, 161.0)]
    out = intraday.smooth_read_snaps(samples, read_times=[250])
    assert out[0] == (0, 100.0)                      # previous anchor untouched
    assert out[2] == (200, 160.0)                    # lands on the post-read level
    assert out[1] == (100, 130.0)                    # halfway → half the 40 jump
    assert out[3:] == samples[3:]                    # after the read: unchanged


def test_moves_long_after_a_read_lands_are_left_alone():
    samples = [(0, 100.0), (100, 101.0), (5000, 200.0)]
    assert intraday.smooth_read_snaps(samples, read_times=[50]) == samples


def test_small_moves_after_a_read_are_not_treated_as_snaps():
    samples = [(0, 100.0), (100, 101.0), (300, 103.0)]
    assert intraday.smooth_read_snaps(samples, read_times=[250]) == samples


def test_sample_reuses_last_coinbase_value_when_a_read_fails(tmp_path, monkeypatch):
    # A failed Coinbase read used to count as $0 → one-sample dips to Yubit-only (Oct 9/14/15).
    snap = tmp_path / "snapshot.json"
    snap.write_text(json.dumps({"roi": {"balance": 1000.0, "positions": []}}))
    key = tmp_path / "key.json"
    key.write_text("{}")
    monkeypatch.setattr(config, "COINBASE_KEY_FILE", key)
    monkeypatch.setattr(live, "mark", lambda roi: {"equity_usd": 1200.0})
    intraday._samples.clear()
    monkeypatch.setattr(coinbase_view, "summary", lambda: {"total": 1300.0})
    intraday.sample_once(snap)

    def boom():
        raise TimeoutError("coinbase down")
    monkeypatch.setattr(coinbase_view, "summary", boom)
    point = intraday.sample_once(snap)
    assert point["equity"] == 2500.0 and point["coinbase"] == 1300.0
