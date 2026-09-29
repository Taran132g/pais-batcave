import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "oracle"))

from cave import coinbase_view  # noqa: E402


class FakeClient:
    def __init__(self, perms):
        self.perms = perms

    def get_api_key_permissions(self):
        return self.perms

    def get_portfolios(self):
        return {"portfolios": [{"name": "Default", "type": "DEFAULT", "uuid": "p1"}]}

    def get_portfolio_breakdown(self, uuid):
        return {"breakdown": {"portfolio_balances": {
            "total_balance": {"value": "1306.72"}, "total_cash_equivalent_balance": {"value": "778.41"},
            "total_crypto_balance": {"value": "3.31"}, "total_equities_balance": {"value": "525"},
            "total_futures_balance": {"value": "0"}},
            "spot_positions": [
                {"asset": "", "account_uuid": "a1", "total_balance_fiat": 525, "total_balance_crypto": 3,
                 "cost_basis": "594", "average_entry_price": "198", "unrealized_pnl": -69,
                 "account_type": "ACCOUNT_TYPE_CCM_EQUITY", "is_cash": False},
                {"asset": "USD", "total_balance_fiat": 757.7, "total_balance_crypto": 757.7, "is_cash": True, "unrealized_pnl": 0},
                {"asset": "USD", "total_balance_fiat": 10.28, "total_balance_crypto": 10.28, "is_cash": True, "unrealized_pnl": 0},
                {"asset": "BTC", "total_balance_fiat": 3.27, "total_balance_crypto": 0.0000395, "is_cash": False, "unrealized_pnl": 0.1},
            ]}}


@pytest.fixture(autouse=True)
def clear_cache():
    coinbase_view._cache.update(at=0.0, value=None)
    coinbase_view.HISTORY_FILE = Path(__import__("tempfile").mkdtemp()) / "h.json"


def _patch(monkeypatch, perms):
    import types
    fake_mod = types.SimpleNamespace(RESTClient=lambda key_file: FakeClient(perms))
    monkeypatch.setitem(sys.modules, "coinbase.rest", fake_mod)
    monkeypatch.setitem(sys.modules, "coinbase", types.SimpleNamespace(rest=fake_mod))


def test_summary_merges_cash_and_labels_stock(monkeypatch):
    _patch(monkeypatch, {"can_view": True, "can_trade": False, "can_transfer": False})
    out = coinbase_view.summary()
    assert out["total"] == 1306.72 and out["stocks"] == 525.0
    names = [h["name"] for h in out["holdings"]]
    assert names == ["Stock", "BTC", "USD"]
    usd = next(h for h in out["holdings"] if h["name"] == "USD")
    assert usd["value"] == 767.98
    stock = out["holdings"][0]
    assert stock["price"] == 175.0 and stock["unrealized_pnl"] == -69


def test_refuses_keys_that_can_trade(monkeypatch):
    _patch(monkeypatch, {"can_view": True, "can_trade": True, "can_transfer": False})
    with pytest.raises(PermissionError):
        coinbase_view.summary()


def test_month_start_prefers_override_then_first_recorded_day(tmp_path):
    hist = coinbase_view.record_daily(1300.0, "2026-10-02", path=tmp_path / "h.json")
    hist = coinbase_view.record_daily(1310.0, "2026-10-05", path=tmp_path / "h.json")
    assert coinbase_view.month_start(hist, "2026-10", {}) == 1300.0
    assert coinbase_view.month_start(hist, "2026-09", {"2026-09": 1100}) == 1100.0
    assert coinbase_view.month_start(hist, "2026-11", {}) is None
