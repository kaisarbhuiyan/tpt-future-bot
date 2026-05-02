from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from typing import Any

EASTERN = ZoneInfo("America/New_York")

# CME Globex sessions (Eastern time)
REGULAR_SESSION_START = time(9, 30)
REGULAR_SESSION_END = time(16, 0)
GLOBEX_START = time(18, 0)  # Sunday/weekday evening
GLOBEX_END = time(17, 0)    # Next day afternoon


def _now_eastern() -> datetime:
    return datetime.now(tz=EASTERN)


def is_weekday(dt: datetime | None = None) -> bool:
    dt = dt or _now_eastern()
    return dt.weekday() < 5  # Monday=0 … Friday=4


def is_trading_now(config: Any, dt: datetime | None = None) -> tuple[bool, str]:
    """
    Returns (is_allowed: bool, reason: str).
    Called before every market scan. If False, reason explains why.
    """
    dt = dt or _now_eastern()

    if not is_weekday(dt):
        return False, f"Weekend — market closed ({dt.strftime('%A')})"

    th = config.get("trading_hours", {})
    permitted_start_str = th.get("permitted_start", "09:30")
    permitted_end_str = th.get("permitted_end", "16:00")
    eod_cutoff = th.get("eod_cutoff_minutes", 15)
    allow_premarket = th.get("allow_premarket", False)
    allow_overnight = th.get("allow_overnight", False)

    start_h, start_m = map(int, permitted_start_str.split(":"))
    end_h, end_m = map(int, permitted_end_str.split(":"))

    permitted_start = time(start_h, start_m)
    permitted_end = time(end_h, end_m)
    cutoff_time = (
        datetime.combine(dt.date(), permitted_end, tzinfo=EASTERN)
        - timedelta(minutes=eod_cutoff)
    ).time()

    current_time = dt.time()

    if current_time >= permitted_start and current_time < permitted_end:
        if current_time >= cutoff_time:
            return False, (
                f"Within EOD cutoff window — no new entries "
                f"(cutoff at {cutoff_time.strftime('%H:%M')} ET)"
            )
        return True, "Regular session — trading permitted"

    if allow_premarket and current_time < permitted_start:
        return True, "Pre-market session — trading permitted by config"

    if allow_overnight:
        if current_time >= GLOBEX_START or current_time < GLOBEX_END:
            return True, "Overnight/Globex session — trading permitted by config"

    return False, (
        f"Outside permitted trading hours "
        f"({permitted_start_str}–{permitted_end_str} ET). "
        f"Current time: {current_time.strftime('%H:%M')} ET"
    )


def minutes_until_close(config: Any, dt: datetime | None = None) -> float:
    """Returns minutes remaining until permitted_end."""
    dt = dt or _now_eastern()
    th = config.get("trading_hours", {})
    end_h, end_m = map(int, th.get("permitted_end", "16:00").split(":"))
    close_dt = datetime.combine(dt.date(), time(end_h, end_m), tzinfo=EASTERN)
    delta = (close_dt - dt).total_seconds() / 60
    return max(0.0, delta)


def is_eod_flatten_time(config: Any, dt: datetime | None = None) -> bool:
    """True when it's time to flatten all positions (at permitted_end)."""
    dt = dt or _now_eastern()
    th = config.get("trading_hours", {})
    end_h, end_m = map(int, th.get("permitted_end", "16:00").split(":"))
    close_time = time(end_h, end_m)
    current_time = dt.time()
    # Trigger within 60 seconds of close
    close_dt = datetime.combine(dt.date(), close_time, tzinfo=EASTERN)
    return abs((datetime.combine(dt.date(), current_time, tzinfo=EASTERN) - close_dt).total_seconds()) < 60
