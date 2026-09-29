import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "oracle"))

from cave import live, market_prices  # noqa: E402

TRADING = {
    "as_of": "2026-09-28T12:00:00Z", "balance": 1000.0, "month_start": 800.0, "target_pct": 20,
    "positions": [
        {"symbol": "BTCUSDT", "account": "futures", "side": "long", "qty": 0.01, "entry": 80000, "mark": 81000,
         "asset_class": "crypto", "margin": 80},
        {"symbol": "SPCXUSDT", "account": "futures", "side": "long", "qty": 2, "entry": 150, "mark": 149,
         "asset_class": "stock", "upnl": -2.0},
    ],
}


def test_live_marks_and_rejects_wrong_ticker(monkeypatch):
    prices = {"BTC": 82000.0, "SPCX": 21.0}  # SPCX here is a same-named ETF: must be ignored

    async def fake_price(symbol, asset_class="crypto"):
        return prices.get(symbol)

    monkeypatch.setattr(market_prices, "get_price", fake_price)
    live._cache.update(at=0.0, key=None, value=None)
    out = live.mark(TRADING)
    btc = next(p for p in out["positions"] if p["symbol"] == "BTCUSDT")
    assert btc["upnl"] == 20.0 and btc["marked_live"] and btc["upnl_pct"] == 25.0
    assert out["unpriced"] == ["SPCXUSDT"]
    # equity = balance + BTC live uPnL + SPCX's last known uPnL; MTD follows the same equity
    assert out["equity_usd"] == 1018.0
    assert out["mtd_pct"] == 27.25 and out["hit"] is True
