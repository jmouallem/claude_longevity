from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_


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


def sleep_log_overlaps_window(model, start_dt: datetime, end_dt: datetime):
    """
    SQLAlchemy filter expression for sleep events that overlap a UTC window.

    Canonical precedence:
    1. If both start/end exist, include any overlap with window.
    2. If only start exists, include when start is inside window.
    3. If only end exists, include when end is inside window.
    4. Fallback to created_at for legacy rows with no start/end.
    """
    return or_(
        and_(
            model.sleep_start.isnot(None),
            model.sleep_end.isnot(None),
            model.sleep_start <= end_dt,
            model.sleep_end >= start_dt,
        ),
        and_(
            model.sleep_start.isnot(None),
            model.sleep_end.is_(None),
            model.sleep_start >= start_dt,
            model.sleep_start <= end_dt,
        ),
        and_(
            model.sleep_start.is_(None),
            model.sleep_end.isnot(None),
            model.sleep_end >= start_dt,
            model.sleep_end <= end_dt,
        ),
        and_(
            model.sleep_start.is_(None),
            model.sleep_end.is_(None),
            model.created_at >= start_dt,
            model.created_at <= end_dt,
        ),
    )
