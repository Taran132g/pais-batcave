"""Intraday mark-to-market of the latest Yubit snapshot.

The Claude Desktop daily run reads the real Yubit account once a day. Between
reads, positions are re-marked at live public prices:

    equity_now = snapshot wallet_balance + Σ uPnL(position, live price)

This is an ESTIMATE: it cannot see trades placed, orders filled, or stops/targets
executed since the snapshot, nor funding accrued. Crossed stops/targets are
flagged, and the next daily snapshot resets the base. Yubit perps trade 24/7;
stock prices from Yahoo freeze outside market hours.
"""
import asyncio
import sys
from pathlib import Path

AGENTIC_OS_DIR = Path.home() / "agentic_os"
# Yubit TradFi stock CFDs: 1 lot = 100 shares. Checked against the 2026-09-28
# read: PYPL 0.06 lots, entry 53.21, profit +10.56 → mark ≈ 54.97 (PYPL ~$55).
CFD_CONTRACT_SIZE = 100
USDT_SUFFIX = "USDT"


def _base_symbol(symbol: str) -> str:
    return symbol[:-len(USDT_SUFFIX)] if symbol.endswith(USDT_SUFFIX) else symbol


def price_keys(position: dict) -> list[tuple[str, str]]:
    """(ticker, asset_class) lookups to try, in order.

    Crypto is tried before stock for untagged futures because some coin tickers
    collide with ETF tickers on Yahoo (BTC is a Grayscale fund there).
    """
    base = _base_symbol(position["symbol"])
    tagged = position.get("asset_class")
    if tagged:
        return [(base, tagged)]
    if position.get("account") == "cfd":
        return [(base, "stock")]
    return [(base, "crypto"), (base, "stock")]


def _multiplier(position: dict) -> float:
    return CFD_CONTRACT_SIZE if position.get("account") == "cfd" else 1.0


def upnl_at(position: dict, price: float) -> float:
    sign = 1 if position["side"] == "long" else -1
    return sign * (price - position["entry"]) * position["qty"] * _multiplier(position)


def _crossing(position: dict, price: float) -> str | None:
    long = position["side"] == "long"
    sl, tp = position.get("sl"), position.get("tp")
    if sl is not None and (price <= sl if long else price >= sl):
        return f"{position['symbol']} {price:,.4g} is past its stop {sl:,.4g}; may be closed"
    if tp is not None and (price >= tp if long else price <= tp):
        return f"{position['symbol']} {price:,.4g} reached its target {tp:,.4g}; may be closed"
    return None


def estimate_equity(base: dict, prices: dict[str, float]) -> dict:
    """Re-mark a snapshot at `prices` (keyed by position symbol). Never mutates base."""
    balance = base.get("wallet_balance")
    if not isinstance(balance, (int, float)):
        raise ValueError("snapshot needs wallet_balance to mark intraday")

    positions, unpriced, flags = [], [], []
    for pos in base["positions"]:
        price = prices.get(pos["symbol"])
        if price is None or pos.get("entry") is None or pos.get("qty") is None:
            unpriced.append(pos["symbol"])
            positions.append({**pos, "marked_live": False})
            continue
        upnl = upnl_at(pos, price)
        notional = abs(pos["qty"] * price * _multiplier(pos))
        positions.append({**pos, "mark": price, "upnl": round(upnl, 4),
                          "notional": round(notional, 4), "marked_live": True})
        flag = _crossing(pos, price)
        if flag:
            flags.append(flag)

    total_upnl = sum(p.get("upnl") or 0.0 for p in positions)
    return {
        "equity_usd": round(balance + total_upnl, 4),
        "wallet_balance": balance,
        "unrealized_pnl": round(total_upnl, 4),
        "positions": positions,
        "unpriced": unpriced,
        "flags": flags,
    }


async def _fetch(positions: list[dict]) -> dict[str, float]:
    if str(AGENTIC_OS_DIR) not in sys.path:
        sys.path.insert(0, str(AGENTIC_OS_DIR))
    from tools import market_prices  # never raises; None on failure

    prices = {}
    for pos in positions:
        for ticker, asset_class in price_keys(pos):
            price = await market_prices.get_price(ticker, asset_class)
            if price:
                prices[pos["symbol"]] = price
                break
    return prices


def fetch_prices(positions: list[dict]) -> dict[str, float]:
    return asyncio.run(_fetch(positions))
