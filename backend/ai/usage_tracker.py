from __future__ import annotations

from sqlalchemy.orm import Session

from db.models import ModelUsageEvent


def _to_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def track_model_usage(
    db: Session,
    user_id: int,
    model_used: str,
    operation: str,
    usage_type: str = "utility",
    tokens_in: int = 0,
    tokens_out: int = 0,
) -> None:
    if not db or not user_id or not model_used:
        return
    db.add(
        ModelUsageEvent(
            user_id=user_id,
            usage_type=usage_type,
            operation=operation,
            model_used=model_used,
            tokens_in=_to_int(tokens_in),
            tokens_out=_to_int(tokens_out),
        )
    )


def track_usage_from_result(
    db: Session,
    user_id: int,
    result: dict | None,
    model_used: str,
    operation: str,
    usage_type: str = "utility",
) -> None:
    if not isinstance(result, dict):
        return
    track_model_usage(
        db=db,
        user_id=user_id,
        model_used=model_used,
        operation=operation,
        usage_type=usage_type,
        tokens_in=result.get("tokens_in", 0),
        tokens_out=result.get("tokens_out", 0),
    )
