from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def today_for_tz(tz_name: str | None) -> date:
    """Return today's date in the user's timezone."""
    if tz_name:
        try:
            return datetime.now(ZoneInfo(tz_name)).date()
        except Exception:
            pass
    return today_utc()


def start_of_day(d: date, tz_name: str | None = None) -> datetime:
    """Return start of day as a UTC datetime, optionally in user's timezone."""
    if tz_name:
        try:
            local = datetime(d.year, d.month, d.day, tzinfo=ZoneInfo(tz_name))
            return local.astimezone(timezone.utc)
        except Exception:
            pass
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def end_of_day(d: date, tz_name: str | None = None) -> datetime:
    """Return end of day as a UTC datetime, optionally in user's timezone."""
    if tz_name:
        try:
            local = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=ZoneInfo(tz_name))
            return local.astimezone(timezone.utc)
        except Exception:
            pass
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)


def start_of_week(d: date) -> date:
    """Return Monday of the week containing d."""
    return d - timedelta(days=d.weekday())


def start_of_month(d: date) -> date:
    return d.replace(day=1)


def fasting_duration_minutes(start: datetime, end: datetime | None = None) -> int:
    """Calculate fasting duration in minutes."""
    if end is None:
        end = utcnow()
    delta = end - start
    return int(delta.total_seconds() / 60)
