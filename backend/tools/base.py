from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from db.models import User


ToolHandler = Callable[[dict[str, Any], "ToolContext"], dict[str, Any]]


class ToolExecutionError(Exception):
    """Raised when a tool call fails validation, permissions, or execution."""


@dataclass
class ToolContext:
    db: Session
    user: User
    specialist_id: str = "orchestrator"
    reference_utc: datetime | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    read_only: bool = True
    required_fields: tuple[str, ...] = ()
    allowed_specialists: frozenset[str] | None = None
    validator: Callable[[dict[str, Any]], None] | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)


def ensure_string(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolExecutionError(f"`{key}` must be a non-empty string")
    return value.strip()
