from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from tools.base import ToolContext, ToolExecutionError, ToolSpec
from tools.registry import ToolRegistry


def _resolve_timezone_name(ctx: ToolContext, override: str | None = None) -> str:
    candidate = (override or "").strip()
    if not candidate:
        candidate = (getattr(ctx.user.settings, "timezone", None) or "").strip()
    if not candidate:
        return "UTC"
    try:
        ZoneInfo(candidate)
        return candidate
    except Exception:
        return "UTC"


def _tool_time_now(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    override_tz = args.get("timezone")
    if override_tz is not None and not isinstance(override_tz, str):
        raise ToolExecutionError("`timezone` must be a string when provided")

    tz_name = _resolve_timezone_name(ctx, override=override_tz)
    utc_now = datetime.now(timezone.utc)
    local_now = utc_now.astimezone(ZoneInfo(tz_name))
    offset = local_now.utcoffset()
    offset_minutes = int(offset.total_seconds() // 60) if offset else 0
    sign = "+" if offset_minutes >= 0 else "-"
    abs_minutes = abs(offset_minutes)
    offset_h = abs_minutes // 60
    offset_m = abs_minutes % 60
    offset_label = f"UTC{sign}{offset_h:02d}:{offset_m:02d}"

    return {
        "timezone": tz_name,
        "utc_offset": offset_label,
        "iso_utc": utc_now.isoformat(),
        "iso_local": local_now.isoformat(),
        "local_date": local_now.strftime("%A, %B %d, %Y"),
        "local_time_24h": local_now.strftime("%H:%M:%S"),
        "local_time_12h": local_now.strftime("%I:%M:%S %p").lstrip("0"),
        "weekday": local_now.strftime("%A"),
    }


def register_time_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="time_now",
            description="Get the current local time/date in the user's timezone (or UTC fallback).",
            read_only=True,
            tags=("time", "clock", "read"),
        ),
        _tool_time_now,
    )

