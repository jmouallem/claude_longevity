from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from db.models import UserGoal
from tools.base import ToolContext, ToolExecutionError, ToolSpec, ensure_string
from tools.registry import ToolRegistry

VALID_GOAL_TYPES = {"weight_loss", "cardiovascular", "fitness", "metabolic", "energy", "sleep", "habit", "custom"}
VALID_STATUSES = {"active", "paused", "completed", "abandoned"}


def _goal_to_dict(goal: UserGoal) -> dict[str, Any]:
    progress_pct = None
    if (
        goal.baseline_value is not None
        and goal.target_value is not None
        and goal.current_value is not None
        and goal.target_value != goal.baseline_value
    ):
        span = goal.target_value - goal.baseline_value
        done = goal.current_value - goal.baseline_value
        progress_pct = round(max(0.0, min(100.0, (done / span) * 100.0)), 1)

    return {
        "id": goal.id,
        "title": goal.title,
        "description": goal.description,
        "goal_type": goal.goal_type,
        "target_value": goal.target_value,
        "target_unit": goal.target_unit,
        "baseline_value": goal.baseline_value,
        "current_value": goal.current_value,
        "target_date": goal.target_date,
        "status": goal.status,
        "priority": goal.priority,
        "why": goal.why,
        "created_by": goal.created_by,
        "progress_pct": progress_pct,
    }


def _handle_create_goal(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    title = ensure_string(args, "title")
    goal_type = str(args.get("goal_type") or "custom").strip().lower()
    if goal_type not in VALID_GOAL_TYPES:
        goal_type = "custom"

    target_value = args.get("target_value")
    if target_value is not None:
        try:
            target_value = float(target_value)
        except (TypeError, ValueError):
            target_value = None

    baseline_value = args.get("baseline_value")
    if baseline_value is not None:
        try:
            baseline_value = float(baseline_value)
        except (TypeError, ValueError):
            baseline_value = None

    target_date = args.get("target_date")
    if target_date:
        target_date = str(target_date).strip() or None

    priority = int(args.get("priority") or 3)
    priority = max(1, min(5, priority))

    goal = UserGoal(
        user_id=ctx.user.id,
        title=title,
        description=args.get("description"),
        goal_type=goal_type,
        target_value=target_value,
        target_unit=args.get("target_unit"),
        baseline_value=baseline_value,
        current_value=baseline_value,  # starts at baseline
        target_date=target_date,
        status="active",
        priority=priority,
        why=args.get("why"),
        created_by="coach",
    )
    ctx.db.add(goal)
    ctx.db.flush()
    return {"success": True, "goal": _goal_to_dict(goal)}


def _handle_update_goal(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    goal_id = args.get("goal_id")
    if not goal_id:
        raise ToolExecutionError("`goal_id` is required")
    try:
        goal_id = int(goal_id)
    except (TypeError, ValueError):
        raise ToolExecutionError("`goal_id` must be an integer")

    goal = ctx.db.query(UserGoal).filter(UserGoal.id == goal_id, UserGoal.user_id == ctx.user.id).first()
    if not goal:
        raise ToolExecutionError(f"Goal {goal_id} not found")

    if "title" in args and args["title"]:
        goal.title = str(args["title"]).strip()
    if "description" in args:
        goal.description = args["description"]
    if "goal_type" in args and args["goal_type"]:
        gt = str(args["goal_type"]).strip().lower()
        goal.goal_type = gt if gt in VALID_GOAL_TYPES else "custom"
    if "target_value" in args and args["target_value"] is not None:
        try:
            goal.target_value = float(args["target_value"])
        except (TypeError, ValueError):
            pass
    if "target_unit" in args:
        goal.target_unit = args["target_unit"]
    if "baseline_value" in args and args["baseline_value"] is not None:
        try:
            goal.baseline_value = float(args["baseline_value"])
        except (TypeError, ValueError):
            pass
    if "current_value" in args and args["current_value"] is not None:
        try:
            goal.current_value = float(args["current_value"])
        except (TypeError, ValueError):
            pass
    if "target_date" in args:
        goal.target_date = str(args["target_date"]).strip() or None
    if "status" in args and args["status"]:
        s = str(args["status"]).strip().lower()
        if s not in VALID_STATUSES:
            raise ToolExecutionError(f"`status` must be one of {sorted(VALID_STATUSES)}")
        goal.status = s
    if "priority" in args and args["priority"] is not None:
        try:
            goal.priority = max(1, min(5, int(args["priority"])))
        except (TypeError, ValueError):
            pass
    if "why" in args:
        goal.why = args["why"]

    goal.updated_at = datetime.now(timezone.utc)
    ctx.db.flush()
    return {"success": True, "goal": _goal_to_dict(goal)}


def _handle_list_goals(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    status_filter = str(args.get("status") or "active").strip().lower()
    query = ctx.db.query(UserGoal).filter(UserGoal.user_id == ctx.user.id)
    if status_filter != "all":
        query = query.filter(UserGoal.status == status_filter)
    goals = query.order_by(UserGoal.priority.asc(), UserGoal.created_at.asc()).all()
    return {"goals": [_goal_to_dict(g) for g in goals], "count": len(goals)}


def register_goal_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="create_goal",
            description=(
                "Create a new structured health goal for the user. "
                "Call this after the user specifies a goal with a clear target and timeline. "
                "Required: title. Recommended: goal_type, target_value, target_unit, baseline_value, target_date, priority, why."
            ),
            read_only=False,
            required_fields=("title",),
            tags=("goals",),
        ),
        _handle_create_goal,
    )
    registry.register(
        ToolSpec(
            name="update_goal",
            description=(
                "Update an existing health goal. Use this when the user reports progress "
                "(update current_value), changes a target, or wants to pause/complete/abandon a goal. "
                "Required: goal_id. Include only the fields to change."
            ),
            read_only=False,
            required_fields=("goal_id",),
            tags=("goals",),
        ),
        _handle_update_goal,
    )
    registry.register(
        ToolSpec(
            name="list_goals",
            description=(
                "List the user's health goals. Returns goals filtered by status (default: active). "
                "Use status='all' to see all goals."
            ),
            read_only=True,
            tags=("goals",),
        ),
        _handle_list_goals,
    )
