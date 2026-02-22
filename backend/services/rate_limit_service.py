from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from db.database import SessionLocal
from db.models import RateLimitAuditEvent


@dataclass(frozen=True)
class RateLimitRule:
    endpoint: str
    limit: int
    window_seconds: int


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, *, key: str, limit: int, window_seconds: int) -> tuple[bool, int, int]:
        now = time.time()
        window = max(int(window_seconds), 1)
        max_hits = max(int(limit), 1)
        with self._lock:
            bucket = self._hits[key]
            cutoff = now - window
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= max_hits:
                retry_after = int(max(bucket[0] + window - now, 1))
                return False, retry_after, 0
            bucket.append(now)
            remaining = max(max_hits - len(bucket), 0)
            return True, 0, remaining


_RATE_LIMITER = InMemoryRateLimiter()


def _hash_scope(scope_key: str) -> str:
    raw = (scope_key or "").encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def record_rate_limit_event(
    *,
    endpoint: str,
    scope_key: str,
    blocked: bool,
    retry_after_seconds: int | None = None,
    user_id: int | None = None,
    ip_address: str | None = None,
    details: dict | None = None,
) -> None:
    db = SessionLocal()
    try:
        db.add(
            RateLimitAuditEvent(
                endpoint=endpoint,
                scope_key=_hash_scope(scope_key),
                blocked=bool(blocked),
                retry_after_seconds=int(retry_after_seconds) if retry_after_seconds else None,
                user_id=user_id,
                ip_address=(ip_address or "").strip()[:128] or None,
                details_json=json.dumps(details or {}, ensure_ascii=True),
            )
        )
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def enforce_rate_limit(
    *,
    rule: RateLimitRule,
    scope_key: str,
    user_id: int | None = None,
    ip_address: str | None = None,
    details: dict | None = None,
    record_allowed: bool = False,
) -> tuple[bool, int]:
    allowed, retry_after, remaining = _RATE_LIMITER.check(
        key=f"{rule.endpoint}:{scope_key}",
        limit=rule.limit,
        window_seconds=rule.window_seconds,
    )
    if not allowed or record_allowed:
        record_rate_limit_event(
            endpoint=rule.endpoint,
            scope_key=scope_key,
            blocked=not allowed,
            retry_after_seconds=retry_after if not allowed else None,
            user_id=user_id,
            ip_address=ip_address,
            details={
                **(details or {}),
                "limit": rule.limit,
                "window_seconds": rule.window_seconds,
                "remaining": remaining,
            },
        )
    return allowed, retry_after
