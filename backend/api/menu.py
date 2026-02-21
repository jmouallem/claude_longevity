from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth.utils import get_current_user
from db.database import get_db
from db.models import User
from tools import tool_registry
from tools.base import ToolContext, ToolExecutionError


router = APIRouter(prefix="/menu", tags=["menu"])


class ArchiveRequest(BaseModel):
    archive: bool = True


@router.get("/templates")
def list_templates(
    include_archived: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        out = tool_registry.execute(
            "meal_template_list",
            {"include_archived": include_archived},
            ToolContext(db=db, user=user, specialist_id="orchestrator"),
        )
        return out.get("templates", [])
    except ToolExecutionError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/templates/{template_id}")
def get_template(
    template_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        out = tool_registry.execute(
            "meal_template_get",
            {"template_id": template_id},
            ToolContext(db=db, user=user, specialist_id="orchestrator"),
        )
        return out.get("template", {})
    except ToolExecutionError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/templates/{template_id}/versions")
def get_template_versions(
    template_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        out = tool_registry.execute(
            "meal_template_versions",
            {"template_id": template_id},
            ToolContext(db=db, user=user, specialist_id="orchestrator"),
        )
        return out
    except ToolExecutionError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/templates/{template_id}/archive")
def archive_template(
    template_id: int,
    req: ArchiveRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        out = tool_registry.execute(
            "meal_template_archive",
            {"template_id": template_id, "archive": req.archive},
            ToolContext(db=db, user=user, specialist_id="orchestrator"),
        )
        db.commit()
        return out
    except ToolExecutionError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/templates/{template_id}")
def delete_template(
    template_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        out = tool_registry.execute(
            "meal_template_delete",
            {"template_id": template_id},
            ToolContext(db=db, user=user, specialist_id="orchestrator"),
        )
        db.commit()
        return out
    except ToolExecutionError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/insights")
def get_insights(
    since_days: int = Query(default=90, ge=7, le=365),
    template_id: int | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    args: dict = {"since_days": since_days}
    if template_id is not None:
        args["template_id"] = template_id
    try:
        out = tool_registry.execute(
            "meal_response_insights",
            args,
            ToolContext(db=db, user=user, specialist_id="orchestrator"),
        )
        return out
    except ToolExecutionError as e:
        raise HTTPException(status_code=400, detail=str(e))

