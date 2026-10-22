"""Monthly ROI goal: progress of Yubit equity against the monthly target."""
import calendar
import re
from datetime import date

# Fallback for snapshots written before the daily task recorded month-start fields:
# the morning brief states it as "Month-start total balance ... was $883.73".
MONTH_START_RE = re.compile(r"[Mm]onth-start[^$]{0,60}\$([\d,]+\.?\d*)")


def month_start_from_report(text: str) -> float | None:
    match = MONTH_START_RE.search(text or "")
    return float(match.group(1).replace(",", "")) if match else None


def _month_of(iso: str) -> str:
    return (iso or "")[:7]


def net_out(transfers: list[dict], month: str, account: str = "yubit") -> float:
    """Money the account sent to other accounts in `month`, minus what it received."""
    total = 0.0
    for t in transfers or []:
        if (t.get("date") or "")[:7] != month:
            continue
        total += t["amount"] if t.get("from") == account else 0.0
        total -= t["amount"] if t.get("to") == account else 0.0
    return total


PORTFOLIO_ACCOUNTS = ("yubit", "coinbase")


def external_out(transfers: list[dict], month: str) -> float:
    """Money that left the whole portfolio in `month` (withdrawals), minus money that came in from outside."""
    total = 0.0
    for t in transfers or []:
        if (t.get("date") or "")[:7] != month:
            continue
        inside_from, inside_to = t.get("from") in PORTFOLIO_ACCOUNTS, t.get("to") in PORTFOLIO_ACCOUNTS
        total += t["amount"] if inside_from and not inside_to else 0.0
        total -= t["amount"] if inside_to and not inside_from else 0.0
    return total


def monthly_history(snapshots: list[dict], transfers: list[dict] | None = None) -> list[dict]:
    """Start and last equity of each month (approximate: deposits are not netted out).

    Start = the month-start balance the daily assistant states (its latest reconstruction wins);
    only if no snapshot that month states one, fall back to the first equity reading. Using the
    first snapshot's equity blindly made Sep 2026 start at $1,256 (a late-month reading) → −6.3%.
    """
    months: dict[str, dict] = {}
    for snap in snapshots:
        m, eq = _month_of(snap.get("as_of")), snap.get("equity_usd")
        if not m or eq is None:
            continue
        entry = months.setdefault(m, {"month": m, "start": eq, "stated": False, "end": eq})
        if snap.get("month_start_balance"):
            entry.update(start=snap["month_start_balance"], stated=True)
        entry["end"] = eq
    for entry in months.values():
        entry["start_source"] = "stated" if entry.pop("stated") else "first reading"
        out = net_out(transfers, entry["month"])
        entry["transfers_out"] = out
        entry["return_pct"] = round(((entry["end"] + out) / entry["start"] - 1) * 100, 2) if entry["start"] else None
    return [months[m] for m in sorted(months)]


def daily_points(snapshots: list[dict]) -> list[dict]:
    """One equity data point per day: the daily Yubit run's reading (latest wins if it ran twice)."""
    by_day = {}
    for snap in snapshots:
        if snap.get("equity_usd") is not None and snap.get("as_of"):
            by_day[snap["as_of"][:10]] = {"date": snap["as_of"][:10], "t": snap["as_of"], "equity": snap["equity_usd"],
                                          "arrived": snap.get("_arrived")}
    return [by_day[d] for d in sorted(by_day)]


def build(snapshots: list[dict], latest_report: str, target_pct: float, today: date | None = None,
          transfers: list[dict] | None = None) -> dict:
    """Returns count money moved to other accounts (e.g. Coinbase) as still earned by Yubit."""
    today = today or date.today()
    latest = snapshots[-1] if snapshots else None
    if not latest:
        return {"status": "no data", "target_pct": target_pct}
    equity = latest.get("equity_usd")
    same_month = _month_of(latest.get("as_of")) == today.strftime("%Y-%m")
    start = latest.get("month_start_balance") if same_month else None
    start_source = "snapshot"
    if start is None and same_month:
        start, start_source = month_start_from_report(latest_report), "morning brief"
    if start is None:
        month_snaps = [s for s in snapshots if _month_of(s.get("as_of")) == today.strftime("%Y-%m")]
        start = month_snaps[0].get("equity_usd") if month_snaps else None
        start_source = "first snapshot this month"
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    days_left = days_in_month - today.day
    out = {
        "status": "ok", "month": today.strftime("%Y-%m"), "as_of": latest.get("as_of"),
        "target_pct": target_pct, "equity": equity, "balance": latest.get("wallet_balance"),
        "unrealized_pnl": latest.get("unrealized_pnl"), "month_start": start, "month_start_source": start_source,
        "days_left": days_left, "days_in_month": days_in_month,
        "equity_series": daily_points(snapshots),
        "history": monthly_history(snapshots, transfers),
        "transfers": [t for t in transfers or [] if t.get("date", "")[:7] == today.strftime("%Y-%m")],
        "transfers_out": net_out(transfers, today.strftime("%Y-%m")),
        "coinbase_transfers_out": net_out(transfers, today.strftime("%Y-%m"), "coinbase"),
        "external_out": external_out(transfers, today.strftime("%Y-%m")),
        "positions": latest.get("positions") or [],
    }
    current = next((m for m in out["history"] if m["month"] == out["month"]), None)
    if current and start:
        current.update(start=start, start_source=start_source,
                       return_pct=round(((current["end"] + out["transfers_out"]) / start - 1) * 100, 2))
    if start and equity:
        mtd = ((equity + out["transfers_out"]) / start - 1) * 100
        target_balance = start * (1 + target_pct / 100)
        out.update({
            "mtd_pct": round(mtd, 2),
            "target_balance": round(target_balance, 2),
            "remaining_usd": round(max(0.0, target_balance - equity - out["transfers_out"]), 2),
            "progress": round(mtd / target_pct, 3) if target_pct else None,
            "on_pace": mtd >= target_pct * today.day / days_in_month,
            "hit": mtd >= target_pct,
        })
    return out

