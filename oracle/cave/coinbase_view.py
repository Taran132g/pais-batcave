"""Coinbase (Default portfolio) summary for the Trading tab. Read-only by construction:
the key's own permissions are checked first and anything that can trade or move money is refused.
"""
import json
import time
from datetime import datetime, timezone

from . import config

HISTORY_FILE = config.ROOT / "data/coinbase_history.json"   # {"YYYY-MM-DD": total} — one point per day

CACHE_S = 20  # matches the page's 20 s refresh
LABEL_OVERRIDES: dict[str, str] = {}  # account_uuid -> display name (Coinbase omits stock tickers)

_cache: dict = {"at": 0.0, "value": None}


def _d(resp) -> dict:
    return resp.to_dict() if hasattr(resp, "to_dict") else dict(resp or {})


def _f(value) -> float:
    try:
        return float(value.get("value") if isinstance(value, dict) else value)
    except (TypeError, ValueError, AttributeError):
        return 0.0


def _holding(pos: dict) -> dict | None:
    value = _f(pos.get("total_balance_fiat"))
    if value < 0.01:
        return None
    equity = pos.get("account_type") == "ACCOUNT_TYPE_CCM_EQUITY"
    name = LABEL_OVERRIDES.get(pos.get("account_uuid")) or pos.get("asset") or ("Stock" if equity else "Other")
    qty = _f(pos.get("total_balance_crypto"))
    return {
        "name": name, "kind": "cash" if pos.get("is_cash") else "stock" if equity else "crypto",
        "value": round(value, 2), "qty": qty, "avg_entry": _f(pos.get("average_entry_price")) or None,
        "price": round(value / qty, 4) if qty and not pos.get("is_cash") else None,
        "cost_basis": _f(pos.get("cost_basis")) or None, "unrealized_pnl": round(_f(pos.get("unrealized_pnl")), 2),
    }


def _merge_cash(holdings: list[dict]) -> list[dict]:
    """USD and USDC appear in several sub-accounts; show one line per cash currency."""
    out, cash = [], {}
    for h in holdings:
        if h["kind"] == "cash" or h["name"] in ("USD", "USDC"):
            c = cash.setdefault(h["name"], {**h, "kind": "cash", "value": 0.0, "qty": 0.0, "unrealized_pnl": 0.0})
            c["value"] = round(c["value"] + h["value"], 2)
            c["qty"] += h["qty"]
        else:
            out.append(h)
    return sorted(out, key=lambda h: -h["value"]) + sorted(cash.values(), key=lambda h: -h["value"])


def record_daily(total: float, day: str, path=None) -> dict:
    """Keep the latest total for each day (feeds the combined equity graph and month starts)."""
    path = path or HISTORY_FILE
    try:
        history = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        history = {}
    history[day] = round(total, 2)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(sorted(history.items()))))
    tmp.replace(path)
    return history


def month_start(history: dict, month: str, overrides: dict) -> float | None:
    """Coinbase value at the start of `month`: an explicit override, else the first value recorded that month."""
    if month in overrides:
        return float(overrides[month])
    days = sorted(d for d in history if d.startswith(month))
    return history[days[0]] if days else None


def _overrides() -> dict:
    try:
        return json.loads((config.ROOT / "goals.json").read_text())["roi"].get("coinbase_month_start", {})
    except (OSError, KeyError, json.JSONDecodeError):
        return {}


def summary() -> dict:
    if _cache["value"] and time.time() - _cache["at"] < CACHE_S:
        return _cache["value"]
    from coinbase.rest import RESTClient  # imported lazily: optional dependency

    client = RESTClient(key_file=str(config.COINBASE_KEY_FILE))
    perms = _d(client.get_api_key_permissions())
    if perms.get("can_trade") or perms.get("can_transfer"):
        raise PermissionError("Coinbase key can trade or transfer; PAIS only accepts a view-only key.")
    portfolio = next(p for p in _d(client.get_portfolios())["portfolios"] if p.get("type") == "DEFAULT")
    breakdown = _d(client.get_portfolio_breakdown(portfolio["uuid"]))["breakdown"]
    bal = breakdown["portfolio_balances"]
    holdings = _merge_cash([h for h in (_holding(p) for p in breakdown.get("spot_positions", [])) if h])
    perps = breakdown.get("perp_positions", []) + breakdown.get("futures_positions", [])
    value = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "portfolio": portfolio.get("name"),
        "total": round(_f(bal.get("total_balance")), 2),
        "cash": round(_f(bal.get("total_cash_equivalent_balance")), 2),
        "crypto": round(_f(bal.get("total_crypto_balance")), 2),
        "stocks": round(_f(bal.get("total_equities_balance")), 2),
        "futures": round(_f(bal.get("total_futures_balance")), 2),
        "unrealized_pnl": round(sum(h["unrealized_pnl"] for h in holdings)
                                + _f(bal.get("futures_unrealized_pnl")) + _f(bal.get("perp_unrealized_pnl")), 2),
        "holdings": holdings,
        "derivatives": len(perps),
        "read_only": True,
    }
    now = datetime.now(timezone.utc)
    history = record_daily(value["total"], now.strftime("%Y-%m-%d"))
    value["history"] = history
    value["month_start"] = month_start(history, now.strftime("%Y-%m"), _overrides())
    _cache.update(at=time.time(), value=value)
    return value
