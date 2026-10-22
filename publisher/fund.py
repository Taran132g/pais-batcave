"""TNFund section of the snapshot for trade.getpais.company: NAV history, stats, monthly returns
and closed trades with Taran's close reasons. Read from the fund ledger on the Mac."""
import importlib
import json
import sys
from pathlib import Path

ATB_DIR = Path.home() / "Automated-Trading-Bot"   # fund_ledger.py + fund.db live here
NOTES_KEY_MINUTES = 16                            # "SYMBOL|2026-10-11T20:01" — close time to the minute


def ledger():
    """The fund ledger module (FUND_DB_PATH picks the DB; default is ATB_DIR/fund.db)."""
    if str(ATB_DIR) not in sys.path:
        sys.path.insert(0, str(ATB_DIR))
    return importlib.import_module("fund_ledger")


def _notes(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _note_key(trade: dict) -> str:
    return f"{trade['symbol']}|{trade['closed_at'][:NOTES_KEY_MINUTES]}"


def build(notes_path: Path) -> dict:
    fl = ledger()
    since = fl.inception_ts()
    notes = _notes(notes_path)
    trades = [{**t, "reason": notes.get(_note_key(t))} for t in fl.closed_trades(since=since)]
    stats = fl.fund_stats()
    return {
        "status": "ok",
        "since": since,
        "stats": {k: stats.get(k) for k in ("nav_per_unit", "equity_usd", "units_outstanding",
                                            "since_inception_twr_pct", "max_drawdown_pct",
                                            "last_snapshot_ts")},
        "monthly_returns_pct": fl.monthly_returns(),
        "nav": [{"t": p["ts"], "nav": p["nav_per_unit"], "source": p["source"]}
                for p in fl.fund_nav_series()],
        "closed_trades": trades,
        "summary": {"trades": len(trades), "won": sum(t["net_pnl"] > 0 for t in trades),
                    "net_pnl": round(sum(t["net_pnl"] for t in trades), 4)},
    }
