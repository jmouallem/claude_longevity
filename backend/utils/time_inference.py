from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


@dataclass(frozen=True)
class TimeInferenceResult:
    event_utc: datetime
    confidence: str  # high | medium | low
    reason: str
    had_explicit_date: bool = False
    had_explicit_time: bool = False


def _tzinfo(tz_name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo((tz_name or "UTC").strip() or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _local_reference(reference_utc: datetime | None, tz_name: str | None) -> datetime:
    tz = _tzinfo(tz_name)
    if isinstance(reference_utc, datetime):
        if reference_utc.tzinfo is None:
            reference_utc = reference_utc.replace(tzinfo=timezone.utc)
        return reference_utc.astimezone(tz)
    return datetime.now(timezone.utc).astimezone(tz)


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _combine_confidence(a: str, b: str) -> str:
    rank = {"low": 1, "medium": 2, "high": 3}
    return a if rank.get(a, 1) <= rank.get(b, 1) else b


def _has_explicit_clock(text: str) -> bool:
    return bool(
        re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\s*(am|pm)?\b", text)
        or re.search(r"\b(1[0-2]|0?[1-9])\s*(am|pm)\b", text)
    )


def _parse_explicit_date(text: str, ref_local: datetime) -> date | None:
    # YYYY-MM-DD
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # MM/DD[/YYYY]
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", text)
    if m:
        try:
            mm = int(m.group(1))
            dd = int(m.group(2))
            yy = m.group(3)
            if yy is None:
                yyyy = ref_local.year
            else:
                yyyy = int(yy)
                if yyyy < 100:
                    yyyy += 2000
            return date(yyyy, mm, dd)
        except ValueError:
            pass

    # Month DD[, YYYY]
    m = re.search(r"\b([a-z]{3,9})\s+(\d{1,2})(?:,\s*(\d{4}))?\b", text)
    if m:
        month_name = m.group(1).lower()
        month = _MONTHS.get(month_name)
        if month:
            try:
                dd = int(m.group(2))
                yyyy = int(m.group(3)) if m.group(3) else ref_local.year
                return date(yyyy, month, dd)
            except ValueError:
                pass

    return None


def _infer_local_date(text: str, ref_local: datetime) -> tuple[date, str, bool]:
    explicit = _parse_explicit_date(text, ref_local)
    if explicit:
        return explicit, "high", True

    if "yesterday" in text or "last night" in text:
        return ref_local.date() - timedelta(days=1), "medium", False
    if "tomorrow" in text:
        return ref_local.date() + timedelta(days=1), "medium", False

    # Early-morning past-tense disambiguation:
    # "this morning / lunch / dinner" right after midnight usually refers to previous day.
    if ref_local.hour < 4:
        past_markers = ("took", "had", "ate", "drank", "logged", "did", "went", "woke")
        same_day_markers = (
            "this morning",
            "this afternoon",
            "this evening",
            "tonight",
            "lunch",
            "dinner",
            "breakfast",
        )
        if _has_any(text, same_day_markers) and _has_any(text, past_markers):
            return ref_local.date() - timedelta(days=1), "medium", False
        # Example: "I took meds at 8:30pm" shortly after midnight likely refers to previous day.
        if _has_any(text, past_markers) and _has_explicit_clock(text) and "pm" in text:
            return ref_local.date() - timedelta(days=1), "medium", False

    if _has_any(text, ("now", "right now", "just now")):
        return ref_local.date(), "medium", False

    return ref_local.date(), "low", False


def _parse_explicit_time(text: str) -> time | None:
    m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\s*(am|pm)\b", text)
    if m:
        h = int(m.group(1))
        minute = int(m.group(2))
        meridiem = m.group(3).lower()
        if meridiem == "pm" and h != 12:
            h += 12
        if meridiem == "am" and h == 12:
            h = 0
        return time(hour=h, minute=minute)

    m = re.search(r"\b(1[0-2]|0?[1-9])\s*(am|pm)\b", text)
    if m:
        h = int(m.group(1))
        meridiem = m.group(2).lower()
        if meridiem == "pm" and h != 12:
            h += 12
        if meridiem == "am" and h == 12:
            h = 0
        return time(hour=h, minute=0)

    # 24h format (e.g., 18:30)
    m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
    if m:
        return time(hour=int(m.group(1)), minute=int(m.group(2)))

    return None


def _infer_local_time(text: str, ref_local: datetime) -> tuple[time, str, bool]:
    explicit = _parse_explicit_time(text)
    if explicit:
        return explicit, "high", True

    if _has_any(text, ("now", "right now", "just now")):
        return ref_local.timetz().replace(tzinfo=None), "high", False
    if _has_any(text, ("breakfast", "this morning", "morning")):
        return time(hour=8, minute=0), "medium", False
    if _has_any(text, ("lunch", "with lunch", "noon")):
        return time(hour=12, minute=30), "medium", False
    if _has_any(text, ("afternoon",)):
        return time(hour=15, minute=0), "medium", False
    if _has_any(text, ("dinner", "with dinner", "evening", "this evening")):
        return time(hour=18, minute=30), "medium", False
    if _has_any(text, ("night", "tonight", "bedtime", "before bed", "last night")):
        return time(hour=22, minute=0), "medium", False

    return ref_local.timetz().replace(tzinfo=None), "low", False


def infer_event_datetime(
    text: str,
    reference_utc: datetime | None,
    tz_name: str | None,
) -> TimeInferenceResult:
    normalized = " ".join((text or "").strip().lower().split())
    ref_local = _local_reference(reference_utc, tz_name)
    local_date, date_confidence, had_explicit_date = _infer_local_date(normalized, ref_local)
    local_time, time_confidence, had_explicit_time = _infer_local_time(normalized, ref_local)
    local_dt = datetime.combine(local_date, local_time, tzinfo=ref_local.tzinfo)
    combined_confidence = _combine_confidence(date_confidence, time_confidence)
    reason = f"date:{date_confidence},time:{time_confidence}"
    return TimeInferenceResult(
        event_utc=local_dt.astimezone(timezone.utc),
        confidence=combined_confidence,
        reason=reason,
        had_explicit_date=had_explicit_date,
        had_explicit_time=had_explicit_time,
    )


def infer_event_datetime_utc(
    text: str,
    reference_utc: datetime | None,
    tz_name: str | None,
) -> datetime:
    return infer_event_datetime(text, reference_utc, tz_name).event_utc


def infer_target_date_iso(
    text: str,
    reference_utc: datetime | None,
    tz_name: str | None,
) -> str:
    local_ref = _local_reference(reference_utc, tz_name)
    inferred_utc = infer_event_datetime(text, reference_utc, tz_name).event_utc
    return inferred_utc.astimezone(local_ref.tzinfo).date().isoformat()
