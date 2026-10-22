"""Fund section of the snapshot: TNFund NAV + closed trades (with Taran's close reasons) for
trade.getpais.company. Reads the fund ledger on the Mac; the site never touches fund.db."""
import json

import pytest

from publisher import fund


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("FUND_DB_PATH", str(tmp_path / "fund.db"))
    fl = fund.ledger()
    inv = fl.add_investor("Founder", "f@example.com", is_admin=True)
    fl.record_deposit(inv["investor_id"], 1000.0, ts="2026-09-28T17:27:00+00:00")
    fl.record_snapshot(1000.0, ts="2026-09-28T17:27:00+00:00", source="yubit")
    fl.record_snapshot(1200.0, ts="2026-10-12T03:40:00+00:00", source="yubit")
    fl.record_closed_trades([
        {"symbol": "ETHUSDT", "account": "futures", "side": "long", "qty": 0.41, "entry": 2435.6,
         "exit": 2437.29, "net_pnl": -2.9483, "leverage": 200, "asset_class": "crypto",
         "opened_at": "2026-10-08T18:21:50Z", "closed_at": "2026-10-11T20:01:10Z"},
        {"symbol": "XPLUSDT", "account": "futures", "side": "long", "qty": 1163, "entry": 0.08598,
         "exit": 0.08638, "net_pnl": 0.3882, "leverage": 10, "asset_class": "crypto",
         "opened_at": "2026-10-10T01:38:08Z", "closed_at": "2026-10-10T11:16:15Z"},
    ])
    return fl


def test_fund_section_has_nav_stats_and_closed_trades(ledger, tmp_path):
    notes = tmp_path / "trade_notes.json"
    notes.write_text(json.dumps({"ETHUSDT|2026-10-11T20:01": "Hit my breakeven stop loss."}))
    out = fund.build(notes)
    assert out["status"] == "ok"
    assert out["stats"]["nav_per_unit"] == pytest.approx(1.2)
    assert [p["nav"] for p in out["nav"]] == [pytest.approx(1.0), pytest.approx(1.2)]
    assert out["monthly_returns_pct"]["2026-10"] == pytest.approx(20.0)
    eth, xpl = out["closed_trades"]                      # newest first
    assert eth["symbol"] == "ETHUSDT" and eth["reason"] == "Hit my breakeven stop loss."
    assert xpl["reason"] is None
    assert out["summary"] == {"trades": 2, "won": 1, "net_pnl": pytest.approx(-2.5601)}


def test_fund_section_without_notes_file(ledger, tmp_path):
    out = fund.build(tmp_path / "missing.json")
    assert all(t["reason"] is None for t in out["closed_trades"])
