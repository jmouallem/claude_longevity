import csv
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from auth.utils import get_current_user, hash_password, require_admin, verify_password
from db.database import get_db
from db.models import (
    AdminAuditLog,
    AnalysisProposal,
    AnalysisRun,
    FeedbackEntry,
    Message,
    ModelUsageEvent,
    User,
)
from services.user_reset_service import reset_user_data_for_user

router = APIRouter(prefix="/admin", tags=["admin"])

_MODELS_FILE = Path(__file__).parent.parent / "data" / "models.json"
_CSV_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t")
_DELETE_BATCH_SIZE = 500


def _pricing() -> dict:
    try:
        payload = json.loads(_MODELS_FILE.read_text(encoding="utf-8"))
        return payload.get("pricing", {})
    except Exception:
        return {}


def _audit(
    db: Session,
    admin_user_id: int,
    action: str,
    target_user_id: int | None = None,
    details: dict | None = None,
    success: bool = True,
) -> None:
    row = AdminAuditLog(
        admin_user_id=admin_user_id,
        target_user_id=target_user_id,
        action=action,
        details_json=json.dumps(details or {}, ensure_ascii=True),
        success=success,
    )
    db.add(row)


def _csv_safe(value: object) -> str:
    text = "" if value is None else str(value)
    stripped = text.lstrip()
    if stripped and stripped[0] in _CSV_DANGEROUS_PREFIXES:
        return f"'{text}"
    return text


class AdminUserRow(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    has_api_key: bool
    force_password_change: bool
    created_at: Optional[str] = None


class AdminUserListResponse(BaseModel):
    total: int
    users: list[AdminUserRow]


class AdminResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=256)


class AdminChangeOwnPasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=256)


class AdminResetDataResponse(BaseModel):
    status: str
    removed_files: int


class AdminDeleteUserResponse(BaseModel):
    status: str
    removed_files: int


class AdminStatsResponse(BaseModel):
    total_users: int
    total_admins: int
    active_users_7d: int
    active_users_30d: int
    total_messages: int
    total_usage_requests: int
    total_tokens_in: int
    total_tokens_out: int
    estimated_cost_usd: float
    analysis_runs: int
    analysis_proposals: int


class AdminFeedbackRow(BaseModel):
    id: int
    feedback_type: str
    title: str
    details: Optional[str] = None
    source: str
    specialist_id: Optional[str] = None
    specialist_name: Optional[str] = None
    created_by_user_id: Optional[int] = None
    created_by_username: Optional[str] = None
    created_at: Optional[str] = None


def _build_admin_feedback_query(
    db: Session,
    feedback_type: Optional[str] = None,
    source: Optional[str] = None,
    specialist_id: Optional[str] = None,
    user_search: Optional[str] = None,
):
    q = db.query(FeedbackEntry)
    feedback_filter = (feedback_type or "").strip().lower()
    source_filter = (source or "").strip().lower()
    specialist_filter = (specialist_id or "").strip().lower()
    user_filter = (user_search or "").strip().lower()

    if feedback_filter:
        q = q.filter(FeedbackEntry.feedback_type == feedback_filter)
    if source_filter:
        q = q.filter(FeedbackEntry.source == source_filter)
    if specialist_filter:
        q = q.filter(FeedbackEntry.specialist_id == specialist_filter)
    if user_filter:
        needle = f"%{user_filter}%"
        q = q.join(User, User.id == FeedbackEntry.created_by_user_id).filter(
            or_(
                func.lower(User.username).like(needle),
                func.lower(User.display_name).like(needle),
            )
        )
    return q


@router.get("/users", response_model=AdminUserListResponse)
def list_users(
    search: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    include_admins: bool = Query(default=False),
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(User)
    if not include_admins:
        query = query.filter(User.role != "admin")
    if search:
        needle = f"%{search.strip().lower()}%"
        query = query.filter(
            or_(
                func.lower(User.username).like(needle),
                func.lower(User.display_name).like(needle),
            )
        )

    total = query.count()
    users = query.order_by(User.created_at.desc(), User.id.desc()).offset(offset).limit(limit).all()
    rows: list[AdminUserRow] = []
    for u in users:
        has_api_key = bool(u.settings and u.settings.api_key_encrypted)
        rows.append(
            AdminUserRow(
                id=u.id,
                username=u.username,
                display_name=u.display_name,
                role=u.role or "user",
                has_api_key=has_api_key,
                force_password_change=bool(u.force_password_change),
                created_at=u.created_at.isoformat() if u.created_at else None,
            )
        )
    _audit(
        db=db,
        admin_user_id=admin_user.id,
        action="admin.users.list",
        details={"search": search or "", "limit": limit, "offset": offset, "include_admins": include_admins, "returned": len(rows)},
        success=True,
    )
    db.commit()
    return AdminUserListResponse(total=total, users=rows)


@router.post("/password/change")
def admin_change_own_password(
    req: AdminChangeOwnPasswordRequest,
    admin_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if (admin_user.role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    current = (req.current_password or "").strip()
    new_password = req.new_password or ""
    if not current:
        raise HTTPException(status_code=400, detail="Current password is required")
    if not verify_password(current, admin_user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    if verify_password(new_password, admin_user.password_hash):
        raise HTTPException(status_code=400, detail="New password must be different from current password")

    admin_user.password_hash = hash_password(new_password)
    admin_user.force_password_change = False
    admin_user.token_version = int(admin_user.token_version or 0) + 1
    _audit(
        db=db,
        admin_user_id=admin_user.id,
        target_user_id=admin_user.id,
        action="admin.self.change_password",
        details={"username": admin_user.username},
        success=True,
    )
    db.commit()
    return {"status": "ok"}


@router.post("/users/{target_user_id}/reset-password")
def admin_reset_password(
    target_user_id: int,
    req: AdminResetPasswordRequest,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == target_user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.role == "admin":
        raise HTTPException(status_code=400, detail="Admin accounts cannot be reset from this endpoint")

    target.password_hash = hash_password(req.new_password)
    target.force_password_change = True
    target.token_version = int(target.token_version or 0) + 1
    _audit(
        db=db,
        admin_user_id=admin_user.id,
        target_user_id=target.id,
        action="admin.user.reset_password",
        details={"username": target.username},
        success=True,
    )
    db.commit()
    return {"status": "ok"}


@router.post("/users/{target_user_id}/reset-data", response_model=AdminResetDataResponse)
def admin_reset_user_data(
    target_user_id: int,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == target_user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.role == "admin":
        raise HTTPException(status_code=400, detail="Admin accounts cannot be reset from this endpoint")

    result = reset_user_data_for_user(db, target)
    target.token_version = int(target.token_version or 0) + 1
    _audit(
        db=db,
        admin_user_id=admin_user.id,
        target_user_id=target.id,
        action="admin.user.reset_data",
        details={"username": target.username, "removed_files": result["removed_files"]},
        success=True,
    )
    db.commit()
    return AdminResetDataResponse(status="ok", removed_files=result["removed_files"])


@router.delete("/users/{target_user_id}", response_model=AdminDeleteUserResponse)
def admin_delete_user(
    target_user_id: int,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == target_user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.role == "admin":
        raise HTTPException(status_code=400, detail="Admin accounts cannot be deleted from this endpoint")

    target_id = target.id
    target_username = target.username
    result = reset_user_data_for_user(db, target)
    db.delete(target)
    _audit(
        db=db,
        admin_user_id=admin_user.id,
        target_user_id=None,
        action="admin.user.delete",
        details={"target_user_id": target_id, "username": target_username, "removed_files": result["removed_files"]},
        success=True,
    )
    db.commit()
    return AdminDeleteUserResponse(status="ok", removed_files=result["removed_files"])


@router.get("/feedback", response_model=list[AdminFeedbackRow])
def admin_list_feedback(
    feedback_type: Optional[str] = Query(default=None),
    source: Optional[str] = Query(default=None),
    specialist_id: Optional[str] = Query(default=None),
    user_search: Optional[str] = Query(default=None, alias="user"),
    limit: int = Query(default=500, ge=1, le=5000),
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = (
        _build_admin_feedback_query(
            db=db,
            feedback_type=feedback_type,
            source=source,
            specialist_id=specialist_id,
            user_search=user_search,
        )
        .order_by(FeedbackEntry.created_at.desc(), FeedbackEntry.id.desc())
        .limit(limit)
        .all()
    )
    user_ids = {r.created_by_user_id for r in rows if r.created_by_user_id}
    username_by_id: dict[int, str] = {}
    if user_ids:
        users = db.query(User.id, User.username).filter(User.id.in_(list(user_ids))).all()
        username_by_id = {u.id: u.username for u in users}

    _audit(
        db=db,
        admin_user_id=admin_user.id,
        action="admin.feedback.list",
        details={
            "feedback_type": feedback_type or "",
            "source": source or "",
            "specialist_id": specialist_id or "",
            "user": user_search or "",
            "limit": limit,
            "returned": len(rows),
        },
        success=True,
    )
    db.commit()
    return [
        AdminFeedbackRow(
            id=r.id,
            feedback_type=r.feedback_type,
            title=r.title,
            details=r.details,
            source=r.source,
            specialist_id=r.specialist_id,
            specialist_name=r.specialist_name,
            created_by_user_id=r.created_by_user_id,
            created_by_username=username_by_id.get(r.created_by_user_id or -1),
            created_at=r.created_at.isoformat() if r.created_at else None,
        )
        for r in rows
    ]


@router.get("/feedback/export")
def admin_export_feedback_csv(
    feedback_type: Optional[str] = Query(default=None),
    source: Optional[str] = Query(default=None),
    specialist_id: Optional[str] = Query(default=None),
    user_search: Optional[str] = Query(default=None, alias="user"),
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = (
        _build_admin_feedback_query(
            db=db,
            feedback_type=feedback_type,
            source=source,
            specialist_id=specialist_id,
            user_search=user_search,
        )
        .order_by(FeedbackEntry.created_at.desc(), FeedbackEntry.id.desc())
        .all()
    )

    user_ids = {r.created_by_user_id for r in rows if r.created_by_user_id}
    username_by_id: dict[int, str] = {}
    if user_ids:
        users = db.query(User.id, User.username).filter(User.id.in_(list(user_ids))).all()
        username_by_id = {u.id: u.username for u in users}

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id",
            "created_at",
            "feedback_type",
            "title",
            "details",
            "source",
            "specialist_id",
            "specialist_name",
            "created_by_user_id",
            "created_by_username",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r.id,
                r.created_at.isoformat() if r.created_at else "",
                _csv_safe(r.feedback_type),
                _csv_safe(r.title),
                _csv_safe(r.details or ""),
                _csv_safe(r.source),
                _csv_safe(r.specialist_id or ""),
                _csv_safe(r.specialist_name or ""),
                r.created_by_user_id or "",
                _csv_safe(username_by_id.get(r.created_by_user_id or -1, "")),
            ]
        )

    _audit(
        db=db,
        admin_user_id=admin_user.id,
        action="admin.feedback.export_csv",
        details={
            "feedback_type": feedback_type or "",
            "source": source or "",
            "specialist_id": specialist_id or "",
            "user": user_search or "",
            "rows": len(rows),
        },
        success=True,
    )
    db.commit()

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="feedback_export.csv"'},
    )


@router.delete("/feedback/{feedback_id}")
def admin_delete_feedback_entry(
    feedback_id: int,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = db.query(FeedbackEntry).filter(FeedbackEntry.id == feedback_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Feedback entry not found")
    snapshot = {
        "feedback_id": row.id,
        "feedback_type": row.feedback_type,
        "source": row.source,
        "created_by_user_id": row.created_by_user_id,
    }
    db.delete(row)
    _audit(
        db=db,
        admin_user_id=admin_user.id,
        target_user_id=snapshot["created_by_user_id"],
        action="admin.feedback.delete",
        details=snapshot,
        success=True,
    )
    db.commit()
    return {"status": "ok"}


@router.delete("/feedback")
def admin_clear_feedback(
    feedback_type: Optional[str] = Query(default=None),
    source: Optional[str] = Query(default=None),
    specialist_id: Optional[str] = Query(default=None),
    user_search: Optional[str] = Query(default=None, alias="user"),
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user_filter = (user_search or "").strip()
    q = _build_admin_feedback_query(
        db=db,
        feedback_type=feedback_type,
        source=source,
        specialist_id=specialist_id,
        user_search=user_filter,
    )
    count = 0
    if user_filter:
        # Join-based filters cannot use query.delete() in SQLAlchemy.
        while True:
            batch_ids = [row.id for row in q.with_entities(FeedbackEntry.id).limit(_DELETE_BATCH_SIZE).all()]
            if not batch_ids:
                break
            db.query(FeedbackEntry).filter(FeedbackEntry.id.in_(batch_ids)).delete(synchronize_session=False)
            db.flush()
            count += len(batch_ids)
    else:
        count = q.count()
        if count:
            q.delete(synchronize_session=False)

    _audit(
        db=db,
        admin_user_id=admin_user.id,
        action="admin.feedback.clear",
        details={
            "feedback_type": feedback_type or "",
            "source": source or "",
            "specialist_id": specialist_id or "",
            "user": user_filter,
            "deleted": int(count),
        },
        success=True,
    )
    db.commit()
    return {"status": "ok", "deleted": int(count)}


@router.get("/stats/overview", response_model=AdminStatsResponse)
def admin_stats_overview(
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    since_7d = now - timedelta(days=7)
    since_30d = now - timedelta(days=30)

    total_users = db.query(User).filter(User.role != "admin").count()
    total_admins = db.query(User).filter(User.role == "admin").count()

    active_users_7d = (
        db.query(func.count(func.distinct(Message.user_id)))
        .join(User, User.id == Message.user_id)
        .filter(User.role != "admin", Message.created_at >= since_7d)
        .scalar()
        or 0
    )
    active_users_30d = (
        db.query(func.count(func.distinct(Message.user_id)))
        .join(User, User.id == Message.user_id)
        .filter(User.role != "admin", Message.created_at >= since_30d)
        .scalar()
        or 0
    )

    total_messages = (
        db.query(func.count(Message.id))
        .join(User, User.id == Message.user_id)
        .filter(User.role != "admin")
        .scalar()
        or 0
    )

    usage_rows = (
        db.query(
            ModelUsageEvent.model_used,
            func.sum(ModelUsageEvent.tokens_in).label("tokens_in"),
            func.sum(ModelUsageEvent.tokens_out).label("tokens_out"),
            func.count(ModelUsageEvent.id).label("requests"),
        )
        .join(User, User.id == ModelUsageEvent.user_id)
        .filter(User.role != "admin")
        .group_by(ModelUsageEvent.model_used)
        .all()
    )
    assistant_rows = (
        db.query(
            Message.model_used,
            func.sum(Message.tokens_in).label("tokens_in"),
            func.sum(Message.tokens_out).label("tokens_out"),
            func.count(Message.id).label("requests"),
        )
        .join(User, User.id == Message.user_id)
        .filter(User.role != "admin", Message.role == "assistant")
        .group_by(Message.model_used)
        .all()
    )
    pricing = _pricing()
    total_usage_requests = 0
    total_tokens_in = 0
    total_tokens_out = 0
    total_cost = 0.0
    for row in [*usage_rows, *assistant_rows]:
        model_id = row.model_used or ""
        tokens_in = int(row.tokens_in or 0)
        tokens_out = int(row.tokens_out or 0)
        req_count = int(row.requests or 0)
        total_usage_requests += req_count
        total_tokens_in += tokens_in
        total_tokens_out += tokens_out
        price = pricing.get(model_id, {})
        total_cost += (tokens_in * float(price.get("input_per_mtok", 0.0)) / 1_000_000)
        total_cost += (tokens_out * float(price.get("output_per_mtok", 0.0)) / 1_000_000)

    analysis_runs = (
        db.query(func.count(AnalysisRun.id))
        .join(User, User.id == AnalysisRun.user_id)
        .filter(User.role != "admin")
        .scalar()
        or 0
    )
    analysis_proposals = (
        db.query(func.count(AnalysisProposal.id))
        .join(User, User.id == AnalysisProposal.user_id)
        .filter(User.role != "admin")
        .scalar()
        or 0
    )

    _audit(
        db=db,
        admin_user_id=admin_user.id,
        action="admin.stats.overview",
        details={"timestamp": now.isoformat()},
        success=True,
    )
    db.commit()

    return AdminStatsResponse(
        total_users=int(total_users),
        total_admins=int(total_admins),
        active_users_7d=int(active_users_7d),
        active_users_30d=int(active_users_30d),
        total_messages=int(total_messages),
        total_usage_requests=int(total_usage_requests),
        total_tokens_in=int(total_tokens_in),
        total_tokens_out=int(total_tokens_out),
        estimated_cost_usd=round(total_cost, 4),
        analysis_runs=int(analysis_runs),
        analysis_proposals=int(analysis_proposals),
    )


class AdminAuditRow(BaseModel):
    id: int
    action: str
    success: bool
    created_at: Optional[str]
    admin_username: str
    target_username: Optional[str] = None
    details_json: Optional[str] = None


@router.get("/audit", response_model=list[AdminAuditRow])
def get_admin_audit(
    limit: int = Query(default=100, ge=1, le=500),
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _ = admin_user
    rows = db.query(AdminAuditLog).order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc()).limit(limit).all()
    user_ids = {r.admin_user_id for r in rows if r.admin_user_id} | {r.target_user_id for r in rows if r.target_user_id}
    users = db.query(User.id, User.username).filter(User.id.in_(list(user_ids))).all() if user_ids else []
    user_map = {u.id: u.username for u in users}
    return [
        AdminAuditRow(
            id=r.id,
            action=r.action,
            success=bool(r.success),
            created_at=r.created_at.isoformat() if r.created_at else None,
            admin_username=user_map.get(r.admin_user_id, f"user:{r.admin_user_id}"),
            target_username=user_map.get(r.target_user_id) if r.target_user_id else None,
            details_json=r.details_json,
        )
        for r in rows
    ]
