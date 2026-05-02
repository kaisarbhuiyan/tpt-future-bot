"""
Unit tests for ATR-based position sizing.
"""

import pytest
from app.risk.position_sizer import calculate_contracts
from app.risk.drawdown_tracker import AccountState

BASE_CONFIG = {
    "account": {
        "account_size": 50000,
        "allowed_symbols": ["ES", "NQ"],
        "max_contracts_per_symbol": 10,
        "max_open_positions": 2,
    },
    "risk": {
        "risk_pct_per_trade": 0.0025,
        "max_risk_pct_per_trade": 0.005,
        "atr_stop_multiplier": 1.5,
    },
    "position_management": {
        "max_consecutive_losses": 2,
        "max_trades_per_day": 6,
    },
}


def make_state(**kwargs) -> AccountState:
    state = AccountState(starting_balance=50000, current_balance=50000, peak_balance=50000)
    for k, v in kwargs.items():
        setattr(state, k, v)
    return state


class TestPositionSizer:
    def test_returns_at_least_one_contract_for_normal_atr(self):
        state = make_state()
        contracts, dollar_risk, reason = calculate_contracts("ES", atr=10.0, account_state=state, config=BASE_CONFIG)
        assert contracts >= 1

    def test_es_position_sizing_math(self):
        """
        ES: ATR=10, stop_mult=1.5 → stop=15pts
        dollar_risk = 50000 * 0.0025 = $125
        dollars_per_contract = 15 * 50 = $750
        contracts = floor(125 / 750) = 0 → clamped to 1
        """
        state = make_state()
        contracts, dollar_risk, reason = calculate_contracts("ES", atr=10.0, account_state=state, config=BASE_CONFIG)
        assert contracts == 1

    def test_nq_position_sizing_math(self):
        """
        NQ: ATR=20, stop_mult=1.5 → stop=30pts
        dollar_risk = 50000 * 0.0025 = $125
        dollars_per_contract = 30 * 20 = $600
        contracts = floor(125 / 600) = 0 → clamped to 1
        """
        state = make_state()
        contracts, dollar_risk, reason = calculate_contracts("NQ", atr=20.0, account_state=state, config=BASE_CONFIG)
        assert contracts == 1

    def test_contracts_capped_at_max(self):
        """Very high account size and low ATR → would exceed max_contracts cap."""
        state = make_state(current_balance=5_000_000)
        contracts, _, _ = calculate_contracts("ES", atr=0.5, account_state=state, config=BASE_CONFIG)
        assert contracts <= 10  # max_contracts_per_symbol

    def test_returns_zero_after_max_consecutive_losses(self):
        state = make_state(consecutive_losses=2)  # At max limit
        contracts, dollar_risk, reason = calculate_contracts("ES", atr=10.0, account_state=state, config=BASE_CONFIG)
        assert contracts == 0
        assert dollar_risk == 0.0
        assert "consecutive" in reason.lower()

    def test_returns_nonzero_before_max_consecutive_losses(self):
        state = make_state(consecutive_losses=1)  # One loss — still allowed
        contracts, dollar_risk, reason = calculate_contracts("ES", atr=10.0, account_state=state, config=BASE_CONFIG)
        assert contracts >= 1

    def test_dollar_risk_does_not_exceed_max(self):
        state = make_state()
        max_risk = 50000 * 0.005  # max_risk_pct_per_trade = 0.5%
        contracts, dollar_risk, reason = calculate_contracts(
            "ES", atr=0.5, account_state=state, config=BASE_CONFIG
        )
        # dollar_risk should not exceed max_dollar_risk
        assert dollar_risk <= max_risk

    def test_unknown_symbol_raises_value_error(self):
        state = make_state()
        with pytest.raises(ValueError):
            calculate_contracts("AAPL", atr=5.0, account_state=state, config=BASE_CONFIG)

    def test_zero_atr_returns_zero_contracts(self):
        state = make_state()
        contracts, dollar_risk, reason = calculate_contracts("ES", atr=0.0, account_state=state, config=BASE_CONFIG)
        assert contracts == 0
