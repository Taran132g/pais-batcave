"""Live mark-to-market of the latest daily Yubit snapshot (runs on Oracle, always on).

equity_now = snapshot wallet balance + Σ uPnL(position at live price), via yubit_mark.
Prices come from public feeds (market_prices); a price more than MAX_DEVIATION away
from the last real Yubit mark is treated as a wrong ticker match and ignored.
"""
import asyncio
import time
from datetime import datetime, timezone

from . import market_prices, yubit_mark

MAX_DEVIATION = 0.30
CACHE_S = 15

_cache: dict = {"at": 0.0, "key": None, "value": None}


async def _prices(positions: list[dict]) -> dict[str, float]:
    out = {}
    for pos in positions:
        for ticker, asset_class in yubit_mark.price_keys(pos):
            price = await market_prices.get_price(ticker, asset_class)
            if not price:
                continue
            ref = pos.get("mark") or pos.get("entry")
            if ref and abs(price / ref - 1) > MAX_DEVIATION:
                continue  # e.g. a same-named ETF, not the Yubit contract
            out[pos["symbol"]] = price
            break
    return out


def mark(trading: dict) -> dict:
    """trading = the snapshot's `roi` section (balance, positions, month_start, target_pct)."""
    key = (trading.get("as_of"), trading.get("balance"))
    if _cache["key"] == key and time.time() - _cache["at"] < CACHE_S:
        return _cache["value"]
    base = {"wallet_balance": trading.get("balance"), "positions": trading.get("positions") or []}
    prices = asyncio.run(_prices(base["positions"]))
    est = yubit_mark.estimate_equity(base, prices)
    start, target = trading.get("month_start"), trading.get("target_pct") or 20
    live = {**est, "priced_at": datetime.now(timezone.utc).isoformat()}
    if start:
        mtd = (est["equity_usd"] / start - 1) * 100
        target_balance = start * (1 + target / 100)
        live.update(mtd_pct=round(mtd, 2), progress=round(mtd / target, 3), hit=mtd >= target,
                    target_balance=round(target_balance, 2),
                    remaining_usd=round(max(0.0, target_balance - est["equity_usd"]), 2))
    for p in live["positions"]:
        margin = p.get("margin")
        if p.get("marked_live") and margin:
            p["upnl_pct"] = round(p["upnl"] / margin * 100, 2)
    _cache.update(at=time.time(), key=key, value=live)
    return live
