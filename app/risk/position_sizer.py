import math
import logging
from app.data.normalizer import get_instrument_spec
from app.risk.drawdown_tracker import AccountState

logger = logging.getLogger(__name__)


def calculate_contracts(
    symbol: str,
    atr: float,
    account_state: AccountState,
    config: dict,
) -> tuple[int, float, str]:
    """
    ATR-based position sizing for futures.

    Formula:
        dollar_risk = account_size * risk_pct_per_trade
        stop_distance_points = atr * atr_stop_multiplier
        stop_distance_dollars = stop_distance_points * point_value_per_contract
        contracts = floor(dollar_risk / stop_distance_dollars)

    Returns (contracts: int, dollar_risk: float, reason: str).
    Returns (0, 0, reason) if trade should be halted.
    """
    risk_cfg = config.get("risk", {})
    pos_cfg = config.get("position_management", {})
    acct_cfg = config.get("account", {})

    # Halt after consecutive losses
    max_consecutive = pos_cfg.get("max_consecutive_losses", 2)
    if account_state.consecutive_losses >= max_consecutive:
        return 0, 0.0, f"Trading halted: {account_state.consecutive_losses} consecutive losses"

    spec = get_instrument_spec(symbol)
    account_size = account_state.current_balance
    risk_pct = risk_cfg.get("risk_pct_per_trade", 0.0025)
    max_risk_pct = risk_cfg.get("max_risk_pct_per_trade", 0.005)
    atr_stop_mult = risk_cfg.get("atr_stop_multiplier", 1.5)
    max_contracts = acct_cfg.get("max_contracts_per_symbol", 10)

    # Dollar risk target
    dollar_risk = account_size * risk_pct
    max_dollar_risk = account_size * max_risk_pct

    # Stop distance in dollars per contract
    stop_distance_points = atr * atr_stop_mult
    dollars_per_contract = stop_distance_points * spec["point_value"]

    if dollars_per_contract <= 0:
        return 0, 0.0, "Invalid stop distance (ATR=0)"

    # Contracts
    contracts = math.floor(dollar_risk / dollars_per_contract)
    contracts = max(1, contracts)
    contracts = min(contracts, max_contracts)

    # Verify actual risk doesn't exceed max
    actual_risk = contracts * dollars_per_contract
    if actual_risk > max_dollar_risk:
        contracts = max(1, math.floor(max_dollar_risk / dollars_per_contract))
        actual_risk = contracts * dollars_per_contract

    reason = (
        f"{contracts} contract(s) | "
        f"Risk ${actual_risk:.2f} ({actual_risk / account_size * 100:.2f}%) | "
        f"ATR={atr:.2f} | Stop dist={stop_distance_points:.2f}pts"
    )
    logger.debug(reason)
    return contracts, actual_risk, reason


def adjust_size_for_streak(contracts: int, account_state: AccountState) -> int:
    """
    Optional: reduce size further after a single loss (scale-down approach).
    Currently returns unchanged — kept for extensibility.
    """
    if account_state.consecutive_losses == 1:
        # After first loss, keep same size — halting is handled by max_consecutive_losses
        pass
    return contracts
