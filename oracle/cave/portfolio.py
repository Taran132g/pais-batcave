"""Whole-portfolio 20% goal: Yubit (live-marked) + Coinbase. Shared by the API and the daily texts."""
from . import coinbase_view, config, live


def portfolio(roi: dict) -> dict | None:
    """Whole-portfolio goal (Yubit at its daily read + Coinbase now) for tabs without live prices."""
    if not config.COINBASE_KEY_FILE.exists() or roi.get("month_start") is None:
        return None
    try:
        cb = coinbase_view.summary()
    except Exception:  # noqa: BLE001 - portfolio view is optional; Yubit-only still renders
        return None
    if cb.get("month_start") is None:
        return None
    start = roi["month_start"] + cb["month_start"]
    try:
        yubit_equity = live.mark(roi)["equity_usd"] if roi.get("balance") is not None else roi.get("equity")
    except Exception:  # noqa: BLE001 - fall back to the daily read if price feeds are down
        yubit_equity = roi.get("equity")
    equity = (yubit_equity or 0) + cb["total"]
    target_pct = roi.get("target_pct") or 20
    mtd = (equity / start - 1) * 100
    return {"month_start": round(start, 2), "equity": round(equity, 2), "mtd_pct": round(mtd, 2),
            "target_pct": target_pct, "target_balance": round(start * (1 + target_pct / 100), 2),
            "progress": round(mtd / target_pct, 3), "hit": mtd >= target_pct}
