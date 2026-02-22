from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth.utils import get_current_user, require_non_admin
from db.database import get_db
from db.models import AnalysisProposal, AnalysisRun, User
from services.analysis_service import (
    combine_similar_pending_proposals,
    run_due_analyses,
    run_longitudinal_analysis,
    review_proposal,
    serialize_analysis_proposal,
    serialize_analysis_run,
)

router = APIRouter(prefix="/analysis", tags=["analysis"], dependencies=[Depends(require_non_admin)])


class RunRequest(BaseModel):
    run_type: str = "daily"
    target_date: Optional[date] = None
    force: bool = False


class ProposalReviewRequest(BaseModel):
    action: str  # approve | reject | apply
    note: Optional[str] = None


class ClearRunsResponse(BaseModel):
    status: str
    deleted_runs: int
    deleted_proposals: int


class ClearProposalsResponse(BaseModel):
    status: str
    deleted: int


class CombineProposalsResponse(BaseModel):
    status: str
    merged: int
    remaining: int


@router.get("/runs")
def list_runs(
    run_type: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=25, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(AnalysisRun).filter(AnalysisRun.user_id == user.id)
    if run_type:
        query = query.filter(AnalysisRun.run_type == run_type.strip().lower())
    if status:
        query = query.filter(AnalysisRun.status == status.strip().lower())
    rows = query.order_by(AnalysisRun.created_at.desc()).limit(limit).all()
    return [serialize_analysis_run(row) for row in rows]


@router.get("/runs/{run_id}")
def get_run(
    run_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(AnalysisRun).filter(AnalysisRun.id == run_id, AnalysisRun.user_id == user.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    return serialize_analysis_run(row)


@router.post("/runs")
async def create_run(
    payload: RunRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        run = await run_longitudinal_analysis(
            db=db,
            user=user,
            run_type=payload.run_type,
            target_date=payload.target_date,
            trigger="manual",
            force=payload.force,
        )
        return serialize_analysis_run(run)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Analysis run failed: {exc}")


@router.post("/runs/due")
async def trigger_due_runs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    runs = await run_due_analyses(db=db, user=user, trigger="manual_due")
    return {"runs": [serialize_analysis_run(row) for row in runs], "count": len(runs)}


@router.get("/proposals")
def list_proposals(
    status: Optional[str] = Query(default=None),
    run_id: Optional[int] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(AnalysisProposal).filter(AnalysisProposal.user_id == user.id)
    if status:
        query = query.filter(AnalysisProposal.status == status.strip().lower())
    if run_id is not None:
        query = query.filter(AnalysisProposal.analysis_run_id == run_id)
    rows = query.order_by(AnalysisProposal.created_at.desc()).limit(limit).all()
    return [serialize_analysis_proposal(row) for row in rows]


@router.delete("/runs", response_model=ClearRunsResponse)
def clear_runs(
    run_type: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run_query = db.query(AnalysisRun).filter(AnalysisRun.user_id == user.id)
    if run_type:
        run_query = run_query.filter(AnalysisRun.run_type == run_type.strip().lower())
    if status:
        run_query = run_query.filter(AnalysisRun.status == status.strip().lower())

    run_ids = [row.id for row in run_query.with_entities(AnalysisRun.id).all()]
    deleted_proposals = 0
    deleted_runs = 0
    if run_ids:
        deleted_proposals = (
            db.query(AnalysisProposal)
            .filter(AnalysisProposal.user_id == user.id, AnalysisProposal.analysis_run_id.in_(run_ids))
            .delete(synchronize_session=False)
        )
        deleted_runs = (
            db.query(AnalysisRun)
            .filter(AnalysisRun.user_id == user.id, AnalysisRun.id.in_(run_ids))
            .delete(synchronize_session=False)
        )
    db.commit()
    return ClearRunsResponse(status="ok", deleted_runs=int(deleted_runs), deleted_proposals=int(deleted_proposals))


@router.delete("/proposals", response_model=ClearProposalsResponse)
def clear_proposals(
    status: Optional[str] = Query(default=None),
    run_id: Optional[int] = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(AnalysisProposal).filter(AnalysisProposal.user_id == user.id)
    if status:
        query = query.filter(AnalysisProposal.status == status.strip().lower())
    if run_id is not None:
        query = query.filter(AnalysisProposal.analysis_run_id == run_id)
    deleted = query.delete(synchronize_session=False)
    db.commit()
    return ClearProposalsResponse(status="ok", deleted=int(deleted))


@router.post("/proposals/combine", response_model=CombineProposalsResponse)
def combine_proposals(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = combine_similar_pending_proposals(db, user.id)
    db.commit()
    return CombineProposalsResponse(status="ok", merged=int(result["merged"]), remaining=int(result["remaining"]))


@router.post("/proposals/{proposal_id}/review")
def review_analysis_proposal(
    proposal_id: int,
    payload: ProposalReviewRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        proposal = review_proposal(
            db=db,
            user=user,
            proposal_id=proposal_id,
            action=payload.action,
            note=payload.note,
        )
        return serialize_analysis_proposal(proposal)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Proposal review failed: {exc}")
